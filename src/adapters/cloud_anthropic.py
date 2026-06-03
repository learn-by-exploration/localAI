"""
Cloud passthrough adapter — forwards requests to the real Anthropic API.
Used when GATEWAY_PROFILE=cloud and the model runner is 'cloud_anthropic'.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import httpx

from src.adapters.base import AdapterInfo, AdapterStatus, BaseAdapter
from src.schemas.unified import (
    MessageRole,
    UnifiedChoice,
    UnifiedMessage,
    UnifiedRequest,
    UnifiedResponse,
    UnifiedUsage,
)

if TYPE_CHECKING:
    from src.core.registry import ModelConfig

logger = logging.getLogger(__name__)

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"


class CloudAnthropicAdapter(BaseAdapter):
    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._api_key: str = self._config.get("api_key", "")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
            },
        )

    async def start(self, model_config: ModelConfig) -> bool:
        if not self._api_key:
            logger.error("ANTHROPIC_API_KEY not set — cloud mode unavailable")
            return False
        logger.info(f"Cloud Anthropic mode: {model_config.model}")
        return True

    async def stop(self, model_config: ModelConfig) -> bool:
        await self._client.aclose()
        return True

    async def health(self) -> bool:
        return bool(self._api_key)

    async def info(self, model_config: ModelConfig) -> AdapterInfo:
        if self._api_key:
            return AdapterInfo(status=AdapterStatus.running)
        return AdapterInfo(status=AdapterStatus.error, error="ANTHROPIC_API_KEY not set")

    async def chat(self, request: UnifiedRequest) -> UnifiedResponse:
        messages = [
            {"role": m.role.value, "content": m.text_content() if not isinstance(m.content, str) else m.content}
            for m in request.messages
            if m.role.value in ("user", "assistant")
        ]
        payload: dict = {
            "model": request.model_id or "claude-haiku-4-5-20251001",
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
        }
        if request.system:
            payload["system"] = request.system
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        resp = await self._client.post(_ANTHROPIC_API_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()

        text = data["content"][0].get("text", "") if data.get("content") else ""
        return UnifiedResponse(
            id=data.get("id", f"msg_{uuid.uuid4().hex[:8]}"),
            model=data.get("model", payload["model"]),
            choices=[
                UnifiedChoice(
                    index=0,
                    message=UnifiedMessage(role=MessageRole.assistant, content=text),
                    finish_reason=data.get("stop_reason", "stop"),
                )
            ],
            usage=UnifiedUsage(
                prompt_tokens=data.get("usage", {}).get("input_tokens", 0),
                completion_tokens=data.get("usage", {}).get("output_tokens", 0),
                total_tokens=data.get("usage", {}).get("input_tokens", 0)
                + data.get("usage", {}).get("output_tokens", 0),
            ),
            created=int(time.time()),
        )

    async def stream(self, request: UnifiedRequest) -> AsyncGenerator[str, None]:
        messages = [
            {"role": m.role.value, "content": m.text_content() if not isinstance(m.content, str) else m.content}
            for m in request.messages
            if m.role.value in ("user", "assistant")
        ]
        payload: dict = {
            "model": request.model_id or "claude-haiku-4-5-20251001",
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
            "stream": True,
        }
        if request.system:
            payload["system"] = request.system

        # Anthropic streaming is already in Anthropic SSE format — pass through
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created = int(time.time())
        model_name = payload["model"]

        done_sent = False
        try:
            async with self._client.stream("POST", _ANTHROPIC_API_URL, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        ev = json.loads(raw)
                        ev_type = ev.get("type", "")
                        if ev_type == "content_block_delta":
                            text = ev.get("delta", {}).get("text", "")
                            if text:
                                chunk = {
                                    "id": response_id,
                                    "object": "chat.completion.chunk",
                                    "created": created,
                                    "model": model_name,
                                    "choices": [
                                        {
                                            "index": 0,
                                            "delta": {"role": "assistant", "content": text},
                                            "finish_reason": None,
                                        }
                                    ],
                                }
                                yield f"data: {json.dumps(chunk)}\n\n"
                        elif ev_type == "message_stop":
                            chunk = {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model_name,
                                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"
                            yield "data: [DONE]\n\n"
                            done_sent = True
                    except Exception:
                        pass
        except Exception:
            logger.exception("Error in cloud Anthropic stream")
        finally:
            if not done_sent:
                yield "data: [DONE]\n\n"
