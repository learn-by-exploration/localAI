from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from src.api.deps import get_lifecycle, get_registry
from src.core.lifecycle import ModelLifecycle
from src.core.profile_manager import ProfileManager
from src.core.registry import ModelRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Profile"])

_SECRET = os.getenv("GATEWAY_SECRET", "")


def _check_auth(x_gateway_secret: str | None) -> None:
    if not _SECRET:
        return  # No secret configured — local-only, skip check
    if x_gateway_secret != _SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Gateway-Secret header")


def get_profile_manager(request: Request) -> ProfileManager:
    return request.app.state.profile_manager


class SwitchRequest(BaseModel):
    profile: str
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None


@router.get("/profile")
async def get_profile(
    pm: ProfileManager = Depends(get_profile_manager),
    lifecycle: ModelLifecycle = Depends(get_lifecycle),
    x_gateway_secret: str | None = Header(default=None),
):
    _check_auth(x_gateway_secret)
    status = pm.get_status()
    model_status = await lifecycle.get_status()
    return {
        **status,
        "active_model": model_status.get("model_id"),
        "active_model_name": model_status.get("model_name"),
        "gateway_status": model_status.get("status"),
    }


@router.post("/profile")
async def switch_profile(
    body: SwitchRequest,
    pm: ProfileManager = Depends(get_profile_manager),
    x_gateway_secret: str | None = Header(default=None),
):
    _check_auth(x_gateway_secret)

    # Pass keys directly to pm.switch() — never write to os.environ
    api_keys: dict[str, str] = {}
    if body.openai_api_key:
        api_keys["openai"] = body.openai_api_key
    if body.anthropic_api_key:
        api_keys["anthropic"] = body.anthropic_api_key

    if body.profile == "cloud":
        has_openai = bool(api_keys.get("openai") or os.getenv("OPENAI_API_KEY"))
        has_anthropic = bool(api_keys.get("anthropic") or os.getenv("ANTHROPIC_API_KEY"))
        if not has_openai and not has_anthropic:
            raise HTTPException(
                status_code=400,
                detail="Missing API keys: OPENAI_API_KEY, ANTHROPIC_API_KEY. "
                       "Set them in .env or pass openai_api_key/anthropic_api_key in the request body.",
            )

    try:
        result = await pm.switch(body.profile, api_keys=api_keys)
        return {"ok": True, **result}
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Profile switch failed")
        raise HTTPException(status_code=500, detail="Switch failed — check server logs")
