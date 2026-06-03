from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.deps import get_guardrails, get_lifecycle, get_profiler, get_queue, get_registry
from src.core.guardrails import ResourceGuardrails
from src.core.lifecycle import ModelLifecycle
from src.core.profiler import ModelProfiler
from src.core.queue_manager import RequestQueue
from src.core.registry import ModelRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Model Management"])


class ModelIdBody(BaseModel):
    model_id: str


@router.get("/models")
async def list_models(
    registry: ModelRegistry = Depends(get_registry),
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    guardrails: ResourceGuardrails = Depends(get_guardrails),
    profiler: ModelProfiler = Depends(get_profiler),
):
    status = await lifecycle.get_status()
    metrics = guardrails.get_system_metrics()
    profile_data = profiler.get_all_results()

    return {
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "runner": m.runner.value,
                "role": m.role.value,
                "priority": m.priority,
                "context_length": m.context_length,
                "vram_required_mb": m.vram_required_mb,
                "tags": m.tags,
                "loaded": status.get("model_id") == m.id,
                "profile": profile_data.get(m.id),
            }
            for m in registry.get_all_models()
        ],
        "aliases": registry.get_aliases(),
        "active": status,
        "system": metrics,
    }


@router.post("/models/start")
async def start_model(
    body: ModelIdBody,
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    registry: ModelRegistry = Depends(get_registry),
    guardrails: ResourceGuardrails = Depends(get_guardrails),
):
    model = registry.get_model(body.model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{body.model_id}' not found")

    can_load, reason = guardrails.check_can_load(model.vram_required_mb)
    if not can_load:
        raise HTTPException(status_code=503, detail=reason)

    success = await lifecycle.load_model(body.model_id)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=lifecycle._load_error or "Failed to start model",
        )
    return {"status": "started", "model_id": body.model_id}


@router.post("/models/stop")
async def stop_model(
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    queue: RequestQueue = Depends(get_queue),
):
    idle = await queue.wait_until_idle(timeout_s=10.0)
    await lifecycle.unload_current()
    return {"status": "stopped", "graceful": idle}


@router.post("/models/switch")
async def switch_model(
    body: ModelIdBody,
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    registry: ModelRegistry = Depends(get_registry),
):
    if not registry.get_model(body.model_id):
        raise HTTPException(status_code=404, detail=f"Model '{body.model_id}' not found")

    success = await lifecycle.load_model(body.model_id)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=lifecycle._load_error or "Failed to switch model",
        )
    return {"status": "switched", "model_id": body.model_id}


@router.post("/models/{model_id}/profile")
async def profile_model(
    model_id: str,
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    profiler: ModelProfiler = Depends(get_profiler),
):
    if lifecycle._loaded_model_id != model_id:
        raise HTTPException(status_code=400, detail="Model is not loaded")
    adapter = lifecycle.get_current_adapter()
    if not adapter:
        raise HTTPException(status_code=503, detail="No adapter")
    result = await profiler.profile(model_id, adapter)
    return result.to_dict()


@router.get("/status")
async def get_status(
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    guardrails: ResourceGuardrails = Depends(get_guardrails),
    queue: RequestQueue = Depends(get_queue),
):
    status = await lifecycle.get_status()
    metrics = guardrails.get_system_metrics()
    return {
        **status,
        "system": metrics,
        "queue": queue.stats(),
    }
