from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.api.deps import get_lifecycle, get_queue, get_registry, get_router
from src.core.lifecycle import ModelLifecycle
from src.core.queue_manager import RequestQueue
from src.core.registry import ModelRegistry
from src.core.router import SmartRouter
from src.schemas.openai_schema import (
    OAIChatRequest,
    OAIChatResponse,
    OAIChoice,
    OAIMessage,
    OAIModelInfo,
    OAIModelsResponse,
    OAIUsage,
)
from src.schemas.unified import MessageRole, TaskType, UnifiedMessage, UnifiedRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["OpenAI Compatible"])

# Model names that should NOT be used as registry lookups
_CLOUD_MODEL_ALIASES = {
    "gpt-4", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo",
    "active", "auto",
}


def _to_unified(req: OAIChatRequest) -> UnifiedRequest:
    messages: list[UnifiedMessage] = []
    system: str | None = None

    for msg in req.messages:
        if msg.role == "system":
            system = msg.content if isinstance(msg.content, str) else ""
            continue
        raw = msg.content or ""
        text = raw if isinstance(raw, str) else " ".join(
            p.get("text", "") if isinstance(p, dict) else (p.text or "")
            for p in raw
        )
        try:
            role = MessageRole(msg.role)
        except ValueError:
            role = MessageRole.user
        messages.append(UnifiedMessage(role=role, content=text))

    # Pass model_id only if it's a real registry ID (not a cloud name)
    model_id = req.model if req.model not in _CLOUD_MODEL_ALIASES else None

    return UnifiedRequest(
        messages=messages,
        system=system,
        temperature=req.temperature if req.temperature is not None else 0.7,
        max_tokens=req.max_tokens,
        top_p=req.top_p,
        stream=req.stream or False,
        model_id=model_id,
    )


async def _ensure_model(
    unified_req: UnifiedRequest,
    lifecycle: ModelLifecycle,
    smart_router: SmartRouter,
) -> None:
    model = smart_router.select_model(unified_req)
    if not model:
        raise HTTPException(status_code=503, detail="No model available in registry")

    if lifecycle._loaded_model_id == model.id:
        return

    success = await lifecycle.load_model(model.id)
    if success:
        return

    for fallback_id in smart_router.get_fallback_chain(model.id):
        success = await lifecycle.load_model(fallback_id)
        if success:
            return

    raise HTTPException(status_code=503, detail="Failed to load any model")


@router.get("/v1/models")
async def list_models(registry: ModelRegistry = Depends(get_registry)) -> OAIModelsResponse:
    return OAIModelsResponse(
        data=[OAIModelInfo(id=m.id) for m in registry.get_all_models()]
    )


@router.post("/v1/chat/completions")
async def chat_completions(
    req: OAIChatRequest,
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    smart_router: SmartRouter = Depends(get_router),
    queue: RequestQueue = Depends(get_queue),
):
    unified_req = _to_unified(req)
    await _ensure_model(unified_req, lifecycle, smart_router)

    adapter = lifecycle.get_current_adapter()
    if not adapter:
        raise HTTPException(status_code=503, detail="No adapter available")

    lifecycle.touch()

    if unified_req.stream:
        return StreamingResponse(
            _stream_gen(adapter, unified_req, queue),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    result = await queue.execute(adapter.chat, unified_req)
    choice = result.choices[0]
    return OAIChatResponse(
        id=result.id,
        created=result.created or int(time.time()),
        model=result.model,
        choices=[
            OAIChoice(
                index=0,
                message=OAIMessage(
                    role="assistant",
                    content=choice.message.content if choice.message else "",
                ),
                finish_reason=choice.finish_reason,
            )
        ],
        usage=OAIUsage(
            prompt_tokens=result.usage.prompt_tokens if result.usage else 0,
            completion_tokens=result.usage.completion_tokens if result.usage else 0,
            total_tokens=result.usage.total_tokens if result.usage else 0,
        )
        if result.usage
        else None,
    )


async def _stream_gen(adapter, request: UnifiedRequest, queue: RequestQueue) -> AsyncGenerator[str, None]:
    async with queue.stream_slot():
        async for chunk in adapter.stream(request):
            yield chunk
