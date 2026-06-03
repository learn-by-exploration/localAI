from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel


class RuntimeType(str, Enum):
    ollama = "ollama"
    llamacpp = "llamacpp"
    vllm = "vllm"
    sglang = "sglang"
    cloud_openai = "cloud_openai"
    cloud_anthropic = "cloud_anthropic"


class ModelRole(str, Enum):
    coding = "coding"
    chat = "chat"
    agent = "agent"
    long_context = "long_context"
    embedding = "embedding"


class ModelConfig(BaseModel):
    id: str
    name: str
    runner: RuntimeType
    model: str
    model_path: str | None = None
    role: ModelRole = ModelRole.chat
    priority: str = "balanced"
    context_length: int = 8192
    vram_required_mb: int | None = None
    port: int | None = None
    enabled: bool = True
    tags: list[str] = []
    extra: dict = {}


class FallbackChain(BaseModel):
    name: str
    models: list[str]


class ModelAlias(BaseModel):
    alias: str
    model_id: str


class ModelsConfig(BaseModel):
    models: list[ModelConfig]
    fallback_chains: list[FallbackChain] = []
    aliases: list[ModelAlias] = []
    default_model: str | None = None


class ModelRegistry:
    def __init__(self, config_path: str):
        self._config_path = Path(config_path)
        self._models: dict[str, ModelConfig] = {}
        self._aliases: dict[str, str] = {}
        self._chains: dict[str, list[str]] = {}
        self._default_model_id: str | None = None

    def load(self) -> None:
        with open(self._config_path) as f:
            data = yaml.safe_load(f)
        config = ModelsConfig(**data)
        self._models = {m.id: m for m in config.models if m.enabled}
        self._aliases = {a.alias: a.model_id for a in config.aliases}
        self._chains = {c.name: c.models for c in config.fallback_chains}
        self._default_model_id = config.default_model

    def get_model(self, model_id: str) -> ModelConfig | None:
        resolved = self._aliases.get(model_id, model_id)
        return self._models.get(resolved)

    def get_models_by_role(self, role: ModelRole) -> list[ModelConfig]:
        return [m for m in self._models.values() if m.role == role]

    def get_fallback_chain(self, chain_name: str) -> list[str]:
        return self._chains.get(chain_name, [])

    def get_all_models(self) -> list[ModelConfig]:
        return list(self._models.values())

    def get_default_model(self) -> ModelConfig | None:
        if self._default_model_id:
            return self.get_model(self._default_model_id)
        models = self.get_all_models()
        return models[0] if models else None

    def resolve_alias(self, name: str) -> str:
        return self._aliases.get(name, name)

    def get_all_identifiers(self) -> list[str]:
        return list(self._models.keys()) + list(self._aliases.keys())

    def get_aliases(self) -> dict[str, str]:
        return dict(self._aliases)
