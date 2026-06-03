from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, Request

logger = logging.getLogger(__name__)
from fastapi.responses import StreamingResponse

from src.api.deps import get_guardrails, get_lifecycle, get_profiler, get_queue
from src.core.guardrails import ResourceGuardrails
from src.core.lifecycle import ModelLifecycle
from src.core.profiler import ModelProfiler
from src.core.queue_manager import RequestQueue

router = APIRouter(prefix="/api", tags=["Metrics"])


@router.get("/metrics")
async def get_metrics(
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    guardrails: ResourceGuardrails = Depends(get_guardrails),
    queue: RequestQueue = Depends(get_queue),
    profiler: ModelProfiler = Depends(get_profiler),
):
    status = await lifecycle.get_status()
    loaded_id = status.get("model_id")
    profile = profiler.get_result(loaded_id).to_dict() if loaded_id and profiler.get_result(loaded_id) else None

    return {
        "timestamp": int(time.time()),
        "system": guardrails.get_system_metrics(),
        "model": status,
        "queue": queue.stats(),
        "profiler": profile,
    }


@router.get("/metrics/stream")
async def metrics_stream(
    request: Request,
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    guardrails: ResourceGuardrails = Depends(get_guardrails),
    queue: RequestQueue = Depends(get_queue),
):
    async def generate():
        consecutive_errors = 0
        while True:
            if await request.is_disconnected():
                break
            try:
                status = await lifecycle.get_status()
                payload = {
                    "timestamp": int(time.time()),
                    "system": guardrails.get_system_metrics(),
                    "model": status,
                    "queue": queue.stats(),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                consecutive_errors = 0
            except Exception:
                consecutive_errors += 1
                logger.warning(f"Metrics SSE error ({consecutive_errors} consecutive)")
                if consecutive_errors >= 5:
                    logger.error("Metrics SSE: 5 consecutive errors, closing stream")
                    break
            await asyncio.sleep(2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
