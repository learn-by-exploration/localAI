from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.anthropic_compat import router as anthropic_router
from src.api.diagnostics_api import router as diagnostics_router
from src.api.metrics_api import router as metrics_router
from src.api.models_api import router as models_router
from src.api.openai_compat import router as openai_router
from src.api.profile_api import router as profile_router
from src.core.config import load_config
from src.core.guardrails import ResourceGuardrails
from src.core.lifecycle import ModelLifecycle
from src.core.profiler import ModelProfiler
from src.core.profile_manager import ProfileManager
from src.core.queue_manager import RequestQueue
from src.core.registry import ModelRegistry
from src.core.router import SmartRouter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()

    registry = ModelRegistry(config.models_config_path)
    registry.load()
    logger.info(f"Registry loaded: {len(registry.get_all_models())} models")

    lifecycle = ModelLifecycle(registry, config)
    smart_router = SmartRouter(registry, config.router)
    queue = RequestQueue(config.resources.max_concurrent_requests)
    guardrails = ResourceGuardrails(config.resources)
    profiler = ModelProfiler(config.profiler)

    profile_manager = ProfileManager(registry, lifecycle)

    app.state.config = config
    app.state.registry = registry
    app.state.lifecycle = lifecycle
    app.state.smart_router = smart_router
    app.state.queue = queue
    app.state.guardrails = guardrails
    app.state.profiler = profiler
    app.state.profile_manager = profile_manager

    default = registry.get_default_model()
    if default:
        logger.info(f"Auto-loading default model: {default.id}")
        await lifecycle.load_model(default.id)

    logger.info(f"Local AI Gateway ready → http://localhost:{config.port}")

    yield

    logger.info("Shutting down — unloading model...")
    await lifecycle.unload_current()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Local AI Gateway",
        version="1.0.0",
        description=(
            "Local model orchestration with OpenAI and Anthropic-compatible APIs. "
            "Supports Ollama, llama.cpp, vLLM, and SGLang runtimes."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(openai_router)
    app.include_router(anthropic_router)
    app.include_router(models_router)
    app.include_router(metrics_router)
    app.include_router(profile_router)
    app.include_router(diagnostics_router)

    # Serve the dashboard at /
    dashboard_path = Path(__file__).parent / "dashboard" / "static"
    if dashboard_path.exists():
        app.mount("/", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")

    return app


app = create_app()
