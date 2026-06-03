from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException

from src.api.deps import get_guardrails, get_lifecycle, get_profile_manager, get_queue, get_registry
from src.core.guardrails import ResourceGuardrails
from src.core.lifecycle import ModelLifecycle
from src.core.profile_manager import ProfileManager
from src.core.queue_manager import RequestQueue
from src.core.registry import ModelRegistry

router = APIRouter(prefix="/api", tags=["Diagnostics"])

_SECRET = os.getenv("GATEWAY_SECRET", "")


def _check_auth(x_gateway_secret: str | None) -> None:
    if not _SECRET:
        return
    if x_gateway_secret != _SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Gateway-Secret header")


@router.get("/diagnostics")
async def diagnostics(
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    registry: ModelRegistry = Depends(get_registry),
    queue: RequestQueue = Depends(get_queue),
    guardrails: ResourceGuardrails = Depends(get_guardrails),
    profile_manager: ProfileManager = Depends(get_profile_manager),
    x_gateway_secret: str | None = Header(default=None),
):
    _check_auth(x_gateway_secret)
    status = await lifecycle.get_status()
    metrics = guardrails.get_system_metrics()
    models = registry.get_all_models()
    recommendations: list[str] = []

    if not models:
        recommendations.append("No enabled models found in the active models config.")
    if status.get("status") == "idle":
        recommendations.append("No model loaded. Start a model or send a chat request.")
    if queue.queued_requests:
        recommendations.append("Requests are queued. Consider lowering concurrency or using a smaller model.")
    if metrics.get("vram_used_mb") and metrics.get("vram_total_mb"):
        if metrics["vram_used_mb"] / max(metrics["vram_total_mb"], 1) > 0.9:
            recommendations.append("VRAM usage is high. Stop the current model before loading a larger one.")

    return {
        "profile": profile_manager.current,
        "status": status,
        "queue": queue.stats(),
        "system": metrics,
        "models": {
            "count": len(models),
            "default": registry.get_default_model().id if registry.get_default_model() else None,
            "enabled_ids": [m.id for m in models],
            "aliases": registry.get_aliases(),
        },
        "config": {
            "models_config": str(registry._config_path),
            "secret_enabled": bool(_SECRET),
        },
        "recommendations": recommendations,
    }
