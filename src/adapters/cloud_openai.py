"""
Cloud passthrough adapter — forwards requests to the real OpenAI API.
Used when GATEWAY_PROFILE=cloud and the model runner is 'cloud_openai'.
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

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class CloudOpenAIAdapter(BaseAdapter):
    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._api_key: str = self._config.get("api_key", "")
        self._base_url: str = self._config.get("base_url", _DEFAULT_BASE_URL)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    async def start(self, model_config: ModelConfig) -> bool:
        if not self._api_key:
            logger.error("OPENAI_API_KEY not set — cloud mode unavailable")
            return False
        logger.info(f"Cloud OpenAI mode: {model_config.model} via {self._base_url}")
        return True

    async def stop(self, model_config: ModelConfig) -> bool:
        await self._client.aclose()
        return True

    async def health(self) -> bool:
        return bool(self._api_key)

    async def info(self, model_config: ModelConfig) -> AdapterInfo:
        if self._api_key:
            return AdapterInfo(status=AdapterStatus.running)
        return AdapterInfo(status=AdapterStatus.error, error="OPENAI_API_KEY not set")

    async def chat(self, request: UnifiedRequest) -> UnifiedResponse:
        messages = self._build_messages(request)
        payload: dict = {
            "model": request.model_id or "gpt-4o",
            "messages": messages,
            "stream": False,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens

        resp = await self._client.post(f"{self._base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        return UnifiedResponse(
            id=data["id"],
            model=data["model"],
            choices=[
                UnifiedChoice(
                    index=0,
                    message=UnifiedMessage(
                        role=MessageRole.assistant,
                        content=choice["message"]["content"] or "",
                    ),
                    finish_reason=choice.get("finish_reason"),
                )
            ],
            usage=UnifiedUsage(
                prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                total_tokens=data.get("usage", {}).get("total_tokens", 0),
            ),
            created=data.get("created", int(time.time())),
        )

    async def stream(self, request: UnifiedRequest) -> AsyncGenerator[str, None]:
        messages = self._build_messages(request)
        payload: dict = {
            "model": request.model_id or "gpt-4o",
            "messages": messages,
            "stream": True,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens

        done_sent = False
        try:
            async with self._client.stream(
                "POST", f"{self._base_url}/chat/completions", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        yield line + "\n\n"
                        if line.strip() == "data: [DONE]":
                            done_sent = True
        except Exception:
            logger.exception("Error in cloud OpenAI stream")
        finally:
            if not done_sent:
                yield "data: [DONE]\n\n"
