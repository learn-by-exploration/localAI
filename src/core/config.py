from __future__ import annotations

import os

from pydantic import BaseModel


class ResourceLimits(BaseModel):
    max_vram_mb: int = 12000
    max_ram_mb: int = 28000  # 90% of 31GB; override with MAX_RAM_MB env var
    max_concurrent_requests: int = 2
    auto_unload_after_seconds: int = 600
    max_tokens_per_request: int = 32000


class RouterConfig(BaseModel):
    default_role: str = "coding"
    long_context_threshold_tokens: int = 2000


class ProfilerConfig(BaseModel):
    benchmark_prompt: str = "Write a Python function that computes fibonacci numbers."
    benchmark_max_tokens: int = 150
    results_file: str = "data/profiler_results.json"


class AppConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    models_config_path: str = "config/models.yaml"
    resources: ResourceLimits = ResourceLimits()
    router: RouterConfig = RouterConfig()
    profiler: ProfilerConfig = ProfilerConfig()
    log_level: str = "INFO"


def load_config() -> AppConfig:
    config = AppConfig()

    if val := os.getenv("MAX_VRAM_MB"):
        config.resources.max_vram_mb = int(val)
    if val := os.getenv("MAX_RAM_MB"):
        config.resources.max_ram_mb = int(val)
    if val := os.getenv("PORT"):
        config.port = int(val)
    if val := os.getenv("MODELS_CONFIG"):
        config.models_config_path = val
    if val := os.getenv("AUTO_UNLOAD_SECONDS"):
        config.resources.auto_unload_after_seconds = int(val)

    return config
