from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from src.schemas.unified import UnifiedRequest, UnifiedResponse

if TYPE_CHECKING:
    from src.core.registry import ModelConfig


class AdapterStatus(str, Enum):
    running = "running"
    stopped = "stopped"
    loading = "loading"
    error = "error"


@dataclass
class AdapterInfo:
    status: AdapterStatus
    pid: int | None = None
    port: int | None = None
    vram_mb: int | None = None
    ram_mb: int | None = None
    tokens_per_sec: float | None = None
    error: str | None = None


class BaseAdapter(ABC):
    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @abstractmethod
    async def start(self, model_config: ModelConfig) -> bool: ...

    @abstractmethod
    async def stop(self, model_config: ModelConfig) -> bool: ...

    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def info(self, model_config: ModelConfig) -> AdapterInfo: ...

    @abstractmethod
    async def chat(self, request: UnifiedRequest) -> UnifiedResponse: ...

    @abstractmethod
    async def stream(self, request: UnifiedRequest) -> AsyncGenerator[str, None]: ...

    def _build_messages(self, request: UnifiedRequest) -> list[dict]:
        messages: list[dict] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for msg in request.messages:
            content = (
                msg.content
                if isinstance(msg.content, str)
                else msg.text_content()
            )
            messages.append({"role": msg.role.value, "content": content})
        return messages
