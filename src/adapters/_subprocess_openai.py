"""
Shared base for adapters that launch a subprocess and expose an OpenAI-compatible API.
llama.cpp, vLLM, and SGLang all work this way.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
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

_STARTUP_POLL_INTERVAL = 1.0
_STARTUP_TIMEOUT = 60


class SubprocessOpenAIAdapter(BaseAdapter):
    """Adapter for runtimes that expose an OpenAI-compatible HTTP API."""

    default_port: int = 8081

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._port = self._config.get("port", self.default_port)
        self._base_url = f"http://127.0.0.1:{self._port}"
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))
        self._process: subprocess.Popen | None = None

    def _get_start_command(self, model_config: ModelConfig) -> list[str]:
        raise NotImplementedError

    async def start(self, model_config: ModelConfig) -> bool:
        cmd = self._get_start_command(model_config)
        logger.info(f"Starting: {' '.join(cmd)}")
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as e:
            logger.error(f"Executable not found: {e}")
            return False

        for _ in range(_STARTUP_TIMEOUT):
            await asyncio.sleep(_STARTUP_POLL_INTERVAL)
            if self._process.poll() is not None:
                logger.error("Process exited immediately")
                return False
            if await self.health():
                logger.info(f"Server ready on port {self._port}")
                return True

        logger.error(f"Server did not become ready after {_STARTUP_TIMEOUT}s")
        await self.stop(model_config)
        return False

    async def stop(self, model_config: ModelConfig) -> bool:
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
        await self._client.aclose()
        return True

    async def health(self) -> bool:
        try:
            resp = await self._client.get(f"{self._base_url}/health", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def info(self, model_config: ModelConfig) -> AdapterInfo:
        if self._process is None:
            return AdapterInfo(status=AdapterStatus.stopped, port=self._port)
        if self._process.poll() is not None:
            return AdapterInfo(status=AdapterStatus.error, port=self._port, error="Process exited")
        is_healthy = await self.health()
        return AdapterInfo(
            status=AdapterStatus.running if is_healthy else AdapterStatus.loading,
            pid=self._process.pid,
            port=self._port,
        )

    async def chat(self, request: UnifiedRequest) -> UnifiedResponse:
        messages = self._build_messages(request)
        payload = self._build_payload(messages, request, stream=False)
        resp = await self._client.post(
            f"{self._base_url}/v1/chat/completions", json=payload, timeout=300.0
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        return UnifiedResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}"),
            model=data.get("model", "local"),
            choices=[
                UnifiedChoice(
                    index=0,
                    message=UnifiedMessage(
                        role=MessageRole.assistant,
                        content=choice["message"]["content"],
                    ),
                    finish_reason=choice.get("finish_reason"),
                )
            ],
            usage=UnifiedUsage(
                prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                total_tokens=data.get("usage", {}).get("total_tokens", 0),
            )
            if "usage" in data
            else None,
            created=int(time.time()),
        )

    async def stream(self, request: UnifiedRequest) -> AsyncGenerator[str, None]:
        messages = self._build_messages(request)
        payload = self._build_payload(messages, request, stream=True)
        done_sent = False
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                timeout=httpx.Timeout(300.0, connect=10.0),
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        yield line + "\n\n"
                        if line.strip() == "data: [DONE]":
                            done_sent = True
        except Exception:
            logger.exception("Error in subprocess OpenAI stream")
        finally:
            if not done_sent:
                yield "data: [DONE]\n\n"

    @staticmethod
    def _build_payload(messages: list[dict], request: UnifiedRequest, stream: bool) -> dict:
        payload: dict = {
            "model": "local",
            "messages": messages,
            "stream": stream,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        return payload
