from __future__ import annotations

import asyncio
import logging
import os
import time

from src.adapters.base import BaseAdapter
from src.adapters.cloud_anthropic import CloudAnthropicAdapter
from src.adapters.cloud_openai import CloudOpenAIAdapter
from src.adapters.llamacpp import LlamaCppAdapter
from src.adapters.ollama import OllamaAdapter
from src.adapters.sglang import SGLangAdapter
from src.adapters.vllm import VLLMAdapter
from src.core.config import AppConfig
from src.core.registry import ModelConfig, ModelRegistry, RuntimeType

logger = logging.getLogger(__name__)


def _make_adapter(runtime: RuntimeType, config: dict | None = None, api_keys: dict[str, str] | None = None) -> BaseAdapter:
    api_keys = api_keys or {}
    match runtime:
        case RuntimeType.ollama:
            return OllamaAdapter(config)
        case RuntimeType.llamacpp:
            return LlamaCppAdapter(config)
        case RuntimeType.vllm:
            return VLLMAdapter(config)
        case RuntimeType.sglang:
            return SGLangAdapter(config)
        case RuntimeType.cloud_openai:
            return CloudOpenAIAdapter({"api_key": api_keys.get("openai") or os.getenv("OPENAI_API_KEY", ""), **(config or {})})
        case RuntimeType.cloud_anthropic:
            return CloudAnthropicAdapter({"api_key": api_keys.get("anthropic") or os.getenv("ANTHROPIC_API_KEY", ""), **(config or {})})
        case _:
            raise ValueError(f"Unknown runtime: {runtime}")


class ModelLifecycle:
    def __init__(self, registry: ModelRegistry, config: AppConfig):
        self._registry = registry
        self._config = config
        # Keyed by model_id (not RuntimeType) so per-model port/config is respected
        self._adapters: dict[str, BaseAdapter] = {}
        self._loaded_model_id: str | None = None
        self._last_request_time: float = time.time()
        self._api_keys: dict[str, str] = {}
        # asyncio.Lock prevents concurrent load_model calls racing on _loaded_model_id
        self._load_lock: asyncio.Lock = asyncio.Lock()
        self._load_error: str | None = None
        self._idle_task: asyncio.Task | None = None

    def _adapter(self, model_id: str, runtime: RuntimeType, extra: dict | None = None, port: int | None = None) -> BaseAdapter:
        if model_id not in self._adapters:
            cfg = dict(extra or {})
            if port:
                cfg["port"] = port
            self._adapters[model_id] = _make_adapter(runtime, cfg or None, self._api_keys)
        return self._adapters[model_id]

    async def load_model(self, model_id: str) -> bool:
        model = self._registry.get_model(model_id)
        if not model:
            logger.error(f"Model '{model_id}' not in registry")
            return False

        async with self._load_lock:
            # Re-check inside lock — another coroutine may have loaded it while we waited
            if self._loaded_model_id == model_id:
                return True

            if self._loaded_model_id:
                await self._unload(self._loaded_model_id)
                self._loaded_model_id = None

            self._load_error = None
            try:
                adapter = self._adapter(model_id, model.runner, model.extra or {}, model.port)
                success = await adapter.start(model)
                if success:
                    self._loaded_model_id = model_id
                    self.touch()
                    self._restart_idle_timer()
                    logger.info(f"Loaded model: {model_id}")
                else:
                    self._load_error = f"Adapter failed to start {model_id}"
                    logger.error(self._load_error)
                return success
            except Exception as e:
                self._load_error = str(e)
                logger.exception(f"Unexpected error loading {model_id}")
                return False

    async def unload_current(self) -> None:
        async with self._load_lock:
            if self._loaded_model_id:
                await self._unload(self._loaded_model_id)
                self._loaded_model_id = None

    async def _unload(self, model_id: str) -> None:
        model = self._registry.get_model(model_id)
        adapter = self._adapters.pop(model_id, None)
        if model and adapter:
            await adapter.stop(model)
        logger.info(f"Unloaded model: {model_id}")

    async def clear_cached_adapters(self) -> None:
        for model_id in list(self._adapters):
            await self._unload(model_id)

    def set_api_keys(self, api_keys: dict[str, str]) -> None:
        for provider, key in api_keys.items():
            if key:
                self._api_keys[provider] = key

    def get_current_adapter(self) -> BaseAdapter | None:
        if not self._loaded_model_id:
            return None
        model = self._registry.get_model(self._loaded_model_id)
        if not model:
            return None
        return self._adapters.get(self._loaded_model_id)

    def get_current_model(self) -> ModelConfig | None:
        if not self._loaded_model_id:
            return None
        return self._registry.get_model(self._loaded_model_id)

    async def get_status(self) -> dict:
        is_loading = self._load_lock.locked()
        if is_loading:
            return {"status": "loading", "model_id": None, "model_name": None}

        if not self._loaded_model_id:
            return {"status": "idle", "model_id": None, "model_name": None}

        model = self._registry.get_model(self._loaded_model_id)
        if not model:
            return {"status": "error", "model_id": self._loaded_model_id, "model_name": None}

        adapter = self._adapters.get(self._loaded_model_id)
        info = await adapter.info(model) if adapter else None
        idle_s = int(time.time() - self._last_request_time)

        return {
            "status": info.status.value if info else "unknown",
            "model_id": self._loaded_model_id,
            "model_name": model.name,
            "runner": model.runner.value,
            "role": model.role.value,
            "priority": model.priority,
            "context_length": model.context_length,
            "pid": info.pid if info else None,
            "port": info.port if info else None,
            "idle_seconds": idle_s,
            "error": (info.error if info else None) or self._load_error,
        }

    def touch(self) -> None:
        self._last_request_time = time.time()

    def _restart_idle_timer(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = asyncio.create_task(self._idle_watchdog())

    async def _idle_watchdog(self) -> None:
        timeout = self._config.resources.auto_unload_after_seconds
        try:
            while self._loaded_model_id:
                await asyncio.sleep(60)
                if not self._loaded_model_id:
                    break
                idle = time.time() - self._last_request_time
                if idle >= timeout:
                    logger.info(f"Auto-unloading after {idle:.0f}s idle")
                    await self.unload_current()
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Idle watchdog crashed — auto-unload disabled until next model load")
