from __future__ import annotations

from fastapi import Request

from src.core.guardrails import ResourceGuardrails
from src.core.profile_manager import ProfileManager
from src.core.lifecycle import ModelLifecycle
from src.core.profiler import ModelProfiler
from src.core.queue_manager import RequestQueue
from src.core.registry import ModelRegistry
from src.core.router import SmartRouter


def get_registry(request: Request) -> ModelRegistry:
    return request.app.state.registry


def get_lifecycle(request: Request) -> ModelLifecycle:
    return request.app.state.lifecycle


def get_router(request: Request) -> SmartRouter:
    return request.app.state.smart_router


def get_queue(request: Request) -> RequestQueue:
    return request.app.state.queue


def get_guardrails(request: Request) -> ResourceGuardrails:
    return request.app.state.guardrails


def get_profiler(request: Request) -> ModelProfiler:
    return request.app.state.profiler


def get_profile_manager(request: Request) -> ProfileManager:
    return request.app.state.profile_manager
