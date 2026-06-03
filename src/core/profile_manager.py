"""
Hot-reload profile switching — swaps the model registry between local and cloud
without restarting the gateway process.
"""
from __future__ import annotations

import logging
from pathlib import Path

from src.core.lifecycle import ModelLifecycle
from src.core.registry import ModelRegistry

logger = logging.getLogger(__name__)

_CONFIGS: dict[str, str] = {
    "local": "config/models.yaml",
    "cloud": "config/cloud_models.yaml",
}


class ProfileManager:
    def __init__(self, registry: ModelRegistry, lifecycle: ModelLifecycle):
        self._registry = registry
        self._lifecycle = lifecycle
        self._current = "local"

    @property
    def current(self) -> str:
        return self._current

    async def switch(self, profile: str, api_keys: dict[str, str] | None = None) -> dict:
        if profile not in _CONFIGS:
            raise ValueError(f"Unknown profile '{profile}'. Choose: {list(_CONFIGS)}")

        config_path = _CONFIGS[profile]
        if not Path(config_path).exists():
            raise FileNotFoundError(f"Config not found: {config_path}")

        logger.info(f"Switching profile: {self._current} → {profile}")

        if api_keys:
            self._lifecycle.set_api_keys(api_keys)

        # Save previous state for rollback
        prev_config_path = self._registry._config_path
        prev_profile = self._current

        # Unload current model
        await self._lifecycle.unload_current()
        await self._lifecycle.clear_cached_adapters()

        # Hot-reload registry — rollback if load fails
        try:
            self._registry._config_path = Path(config_path)
            self._registry.load()
        except Exception as e:
            logger.error(f"Registry reload failed, rolling back to {prev_profile}: {e}")
            self._registry._config_path = prev_config_path
            try:
                self._registry.load()
                default = self._registry.get_default_model()
                if default:
                    await self._lifecycle.load_model(default.id)
            except Exception:
                logger.exception("Best-effort rollback failed")
            raise

        self._current = profile

        logger.info(f"Registry reloaded: {len(self._registry.get_all_models())} models")

        # Auto-load default model in new profile
        default = self._registry.get_default_model()
        loaded_model = None
        if default:
            success = await self._lifecycle.load_model(default.id)
            if success:
                loaded_model = default.id
                logger.info(f"Auto-loaded: {default.id}")
            else:
                logger.warning(f"Auto-load failed for {default.id}")

        return {
            "profile": self._current,
            "models": [m.id for m in self._registry.get_all_models()],
            "default_model": loaded_model,
            "model_count": len(self._registry.get_all_models()),
        }

    def get_status(self) -> dict:
        return {
            "profile": self._current,
            "models": [
                {"id": m.id, "name": m.name, "runner": m.runner.value, "role": m.role.value}
                for m in self._registry.get_all_models()
            ],
            "available_profiles": list(_CONFIGS.keys()),
        }
