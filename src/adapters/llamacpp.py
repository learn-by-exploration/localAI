from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.adapters._subprocess_openai import SubprocessOpenAIAdapter

if TYPE_CHECKING:
    from src.core.registry import ModelConfig


class LlamaCppAdapter(SubprocessOpenAIAdapter):
    """
    Adapter for llama.cpp server (llama-server binary).
    Exposes an OpenAI-compatible API on the configured port.

    Install: https://github.com/ggerganov/llama.cpp#build
    Run manually: llama-server -m model.gguf --port 8081
    """

    default_port = 8081

    def _get_start_command(self, model_config: ModelConfig) -> list[str]:
        model_path = model_config.model_path or model_config.model
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"GGUF model not found: {model_path}")

        server_bin = self._config.get("server_path", "llama-server")
        return [
            server_bin,
            "--model", model_path,
            "--port", str(self._port),
            "--host", "127.0.0.1",
            "--ctx-size", str(model_config.context_length),
            "--n-gpu-layers", "999",
            "--flash-attn",
        ]
