from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any


class RequestQueue:
    def __init__(self, max_concurrent: int = 2):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_count = 0
        self._queued_count = 0
        self._total_processed = 0
        self._total_errors = 0
        self._last_request_time: float | None = None

    async def execute(self, task: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        self._queued_count += 1
        acquired = False
        try:
            async with self._semaphore:
                acquired = True
                self._queued_count = max(0, self._queued_count - 1)
                self._active_count += 1
                self._last_request_time = time.time()
                try:
                    result = await task(*args, **kwargs)
                    self._total_processed += 1
                    return result
                except Exception:
                    self._total_errors += 1
                    raise
                finally:
                    self._active_count -= 1
        finally:
            if not acquired:
                self._queued_count = max(0, self._queued_count - 1)

    @asynccontextmanager
    async def stream_slot(self) -> AsyncGenerator[None, None]:
        """Acquire a concurrency slot for a streaming response."""
        self._queued_count += 1
        acquired = False
        try:
            async with self._semaphore:
                acquired = True
                self._queued_count = max(0, self._queued_count - 1)
                self._active_count += 1
                self._last_request_time = time.time()
                try:
                    yield
                    self._total_processed += 1
                except Exception:
                    self._total_errors += 1
                    raise
                finally:
                    self._active_count -= 1
        finally:
            if not acquired:
                self._queued_count = max(0, self._queued_count - 1)

    @property
    def active_requests(self) -> int:
        return self._active_count

    @property
    def queued_requests(self) -> int:
        return self._queued_count

    @property
    def total_processed(self) -> int:
        return self._total_processed

    @property
    def total_errors(self) -> int:
        return self._total_errors

    def stats(self) -> dict:
        return {
            "active": self._active_count,
            "queued": self._queued_count,
            "total_processed": self._total_processed,
            "total_errors": self._total_errors,
            "last_request_at": self._last_request_time,
        }

    async def wait_until_idle(self, timeout_s: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while self._active_count > 0:
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.1)
        return True
