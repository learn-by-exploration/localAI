from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from src.core.config import ProfilerConfig
from src.schemas.unified import MessageRole, TaskType, UnifiedMessage, UnifiedRequest

logger = logging.getLogger(__name__)


class ProfileResult:
    __slots__ = (
        "model_id",
        "tokens_per_sec",
        "first_token_latency_ms",
        "total_tokens",
        "error",
        "timestamp",
    )

    def __init__(
        self,
        model_id: str,
        tokens_per_sec: float,
        first_token_latency_ms: float,
        total_tokens: int,
        error: str | None = None,
        timestamp: float | None = None,
    ) -> None:
        self.model_id = model_id
        self.tokens_per_sec = tokens_per_sec
        self.first_token_latency_ms = first_token_latency_ms
        self.total_tokens = total_tokens
        self.error = error
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "tokens_per_sec": round(self.tokens_per_sec, 2),
            "first_token_latency_ms": round(self.first_token_latency_ms, 1),
            "total_tokens": self.total_tokens,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class ModelProfiler:
    def __init__(self, config: ProfilerConfig):
        self._config = config
        self._results: dict[str, ProfileResult] = {}
        self._load()

    def _load(self) -> None:
        path = Path(self._config.results_file)
        if not path.exists():
            return
        try:
            with open(path) as f:
                data = json.load(f)
            for model_id, r in data.items():
                self._results[model_id] = ProfileResult(**r)
        except Exception as e:
            logger.warning(f"Could not load profiler results: {e}")

    def _save(self) -> None:
        path = Path(self._config.results_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump({k: v.to_dict() for k, v in self._results.items()}, f, indent=2)

    async def profile(self, model_id: str, adapter) -> ProfileResult:
        request = UnifiedRequest(
            messages=[
                UnifiedMessage(
                    role=MessageRole.user,
                    content=self._config.benchmark_prompt,
                )
            ],
            max_tokens=self._config.benchmark_max_tokens,
            stream=True,
            task_type=TaskType.chat,
        )

        first_token_time: float | None = None
        token_count = 0
        start = time.monotonic()
        error: str | None = None

        try:
            async for chunk in adapter.stream(request):
                if first_token_time is None and chunk and "content" in chunk:
                    first_token_time = time.monotonic()
                token_count += 1
        except Exception as e:
            error = str(e)
            logger.warning(f"Profile error for {model_id}: {e}")

        elapsed = time.monotonic() - start
        latency_ms = ((first_token_time or start) - start) * 1000
        tps = token_count / elapsed if elapsed > 0 else 0

        result = ProfileResult(
            model_id=model_id,
            tokens_per_sec=tps,
            first_token_latency_ms=latency_ms,
            total_tokens=token_count,
            error=error,
        )
        self._results[model_id] = result
        self._save()
        return result

    def get_result(self, model_id: str) -> ProfileResult | None:
        return self._results.get(model_id)

    def get_all_results(self) -> dict[str, dict]:
        return {k: v.to_dict() for k, v in self._results.items()}
