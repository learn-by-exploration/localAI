from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.api.deps import get_lifecycle, get_queue, get_router
from src.core.lifecycle import ModelLifecycle
from src.core.queue_manager import RequestQueue
from src.core.router import SmartRouter
from src.schemas.anthropic_schema import (
    AnthropicRequest,
    AnthropicResponse,
    AnthropicResponseContent,
    AnthropicUsage,
)
from src.schemas.unified import MessageRole, UnifiedMessage, UnifiedRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Anthropic Compatible"])


def _to_unified(req: AnthropicRequest) -> UnifiedRequest:
    messages: list[UnifiedMessage] = []
    for msg in req.messages:
        text = msg.text_content() if hasattr(msg, "text_content") else str(msg.content)
        try:
            role = MessageRole(msg.role)
        except ValueError:
            role = MessageRole.user
        messages.append(UnifiedMessage(role=role, content=text))

    return UnifiedRequest(
        messages=messages,
        system=req.system,
        temperature=req.temperature if req.temperature is not None else 0.7,
        max_tokens=req.max_tokens,
        top_p=req.top_p,
        stream=req.stream or False,
    )


async def _ensure_model(
    unified_req: UnifiedRequest,
    lifecycle: ModelLifecycle,
    smart_router: SmartRouter,
) -> str:
    model = smart_router.select_model(unified_req)
    if not model:
        raise HTTPException(status_code=503, detail="No model available")

    if lifecycle._loaded_model_id != model.id:
        success = await lifecycle.load_model(model.id)
        if not success:
            for fb_id in smart_router.get_fallback_chain(model.id):
                if await lifecycle.load_model(fb_id):
                    return fb_id
            raise HTTPException(status_code=503, detail="Failed to load model")

    return lifecycle._loaded_model_id or model.id


@router.post("/v1/messages")
async def messages(
    req: AnthropicRequest,
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    smart_router: SmartRouter = Depends(get_router),
    queue: RequestQueue = Depends(get_queue),
):
    unified_req = _to_unified(req)
    model_id = await _ensure_model(unified_req, lifecycle, smart_router)

    adapter = lifecycle.get_current_adapter()
    if not adapter:
        raise HTTPException(status_code=503, detail="No adapter available")

    lifecycle.touch()

    if unified_req.stream:
        return StreamingResponse(
            _anthropic_stream(adapter, unified_req, model_id, queue),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    result = await queue.execute(adapter.chat, unified_req)
    content = result.choices[0].message.content if result.choices[0].message else ""

    return AnthropicResponse(
        id=result.id,
        model=model_id,
        content=[AnthropicResponseContent(type="text", text=content)],
        stop_reason="end_turn",
        usage=AnthropicUsage(
            input_tokens=result.usage.prompt_tokens if result.usage else 0,
            output_tokens=result.usage.completion_tokens if result.usage else 0,
        ),
    )


async def _anthropic_stream(
    adapter, request: UnifiedRequest, model_id: str, queue: RequestQueue
) -> AsyncGenerator[str, None]:
    msg_id = f"msg_{uuid.uuid4().hex[:8]}"

    def _ev(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    async with queue.stream_slot():
        yield _ev("message_start", {
            "type": "message_start",
            "message": {
                "id": msg_id, "type": "message", "role": "assistant",
                "model": model_id, "content": [], "stop_reason": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        })
        yield _ev("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        })
        yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"

        async for raw in adapter.stream(request):
            if not raw.startswith("data: ") or raw.strip() == "data: [DONE]":
                continue
            try:
                data = json.loads(raw[6:])
                text = data["choices"][0].get("delta", {}).get("content", "")
                if text:
                    yield _ev("content_block_delta", {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": text},
                    })
            except Exception:
                pass

        yield _ev("content_block_stop", {"type": "content_block_stop", "index": 0})
        yield _ev("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 0},
        })
        yield _ev("message_stop", {"type": "message_stop"})
