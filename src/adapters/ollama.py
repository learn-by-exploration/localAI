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
    UnifiedDelta,
    UnifiedMessage,
    UnifiedRequest,
    UnifiedResponse,
    UnifiedUsage,
)

if TYPE_CHECKING:
    from src.core.registry import ModelConfig

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaAdapter(BaseAdapter):
    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._base_url = self._config.get("base_url", _DEFAULT_BASE_URL)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))
        self._current_model: str | None = None

    async def start(self, model_config: ModelConfig) -> bool:
        if not await self.health():
            logger.error("Ollama daemon is not running. Start it with: ollama serve")
            return False

        available = await self._list_local_models()
        if model_config.model not in available:
            logger.info(f"Pulling {model_config.model} (this may take a while)...")
            if not await self._pull(model_config.model):
                return False

        logger.info(f"Loading {model_config.model} into memory...")
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/generate",
                json={"model": model_config.model, "prompt": "", "keep_alive": "30m"},
                timeout=120.0,
            )
            if resp.status_code == 200:
                self._current_model = model_config.model
                return True
            logger.error(f"Failed to load model: {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return False

    async def stop(self, model_config: ModelConfig) -> bool:
        try:
            await self._client.post(
                f"{self._base_url}/api/generate",
                json={"model": model_config.model, "prompt": "", "keep_alive": "0"},
                timeout=30.0,
            )
        except Exception as e:
            logger.warning(f"Error unloading model: {e}")
        self._current_model = None
        await self._client.aclose()
        return True

    async def health(self) -> bool:
        try:
            resp = await self._client.get(f"{self._base_url}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def info(self, model_config: ModelConfig) -> AdapterInfo:
        if not await self.health():
            return AdapterInfo(status=AdapterStatus.error, error="Ollama not running")

        available = await self._list_local_models()
        if self._current_model == model_config.model:
            return AdapterInfo(status=AdapterStatus.running)
        if model_config.model in available:
            return AdapterInfo(status=AdapterStatus.stopped)
        return AdapterInfo(status=AdapterStatus.stopped, error="Model not pulled")

    async def chat(self, request: UnifiedRequest) -> UnifiedResponse:
        messages = self._build_messages(request)
        model = self._current_model or request.model_id or "unknown"

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": self._build_options(request),
        }

        resp = await self._client.post(
            f"{self._base_url}/api/chat", json=payload, timeout=300.0
        )
        resp.raise_for_status()
        data = resp.json()

        content = data.get("message", {}).get("content", "")
        usage = None
        if "prompt_eval_count" in data:
            usage = UnifiedUsage(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            )

        return UnifiedResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            model=model,
            choices=[
                UnifiedChoice(
                    index=0,
                    message=UnifiedMessage(role=MessageRole.assistant, content=content),
                    finish_reason=data.get("done_reason", "stop"),
                )
            ],
            usage=usage,
            created=int(time.time()),
        )

    async def stream(self, request: UnifiedRequest) -> AsyncGenerator[str, None]:
        messages = self._build_messages(request)
        model = self._current_model or request.model_id or "unknown"

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": self._build_options(request),
        }

        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created = int(time.time())
        done_sent = False

        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=httpx.Timeout(300.0, connect=10.0),
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if data.get("done", False):
                        chunk = {
                            "id": response_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [
                                {"index": 0, "delta": {}, "finish_reason": data.get("done_reason", "stop")}
                            ],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                        done_sent = True
                        break

                    content = data.get("message", {}).get("content", "")
                    if content:
                        chunk = {
                            "id": response_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"role": "assistant", "content": content},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
        except Exception:
            logger.exception("Error in Ollama stream")
        finally:
            if not done_sent:
                yield "data: [DONE]\n\n"

    async def _list_local_models(self) -> list[str]:
        try:
            resp = await self._client.get(f"{self._base_url}/api/tags", timeout=5.0)
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []

    async def _pull(self, model_name: str) -> bool:
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/api/pull",
                json={"name": model_name},
                timeout=httpx.Timeout(3600.0, connect=10.0),
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "error" in data:
                        logger.error(f"Pull error from Ollama: {data['error']}")
                        return False
                    if status := data.get("status", ""):
                        logger.info(f"  pull: {status}")
            return True
        except Exception as e:
            logger.error(f"Pull failed: {e}")
            return False

    def _build_options(self, request: UnifiedRequest) -> dict:
        opts: dict = {}
        if request.temperature is not None:
            opts["temperature"] = request.temperature
        if request.top_p is not None:
            opts["top_p"] = request.top_p

        # Per-model minimum token budget (important for Qwen3 thinking phase).
        # Models that use chain-of-thought (thinking tokens) need room for
        # both the internal reasoning AND the final answer.
        min_tokens: int = self._config.get("min_tokens", 0)
        if request.max_tokens:
            opts["num_predict"] = max(request.max_tokens, min_tokens)
        elif min_tokens:
            opts["num_predict"] = min_tokens
        # If neither is set, Ollama uses its own default — do not restrict.

        return opts
