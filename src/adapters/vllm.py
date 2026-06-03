from __future__ import annotations

from typing import TYPE_CHECKING

from src.adapters._subprocess_openai import SubprocessOpenAIAdapter

if TYPE_CHECKING:
    from src.core.registry import ModelConfig


class VLLMAdapter(SubprocessOpenAIAdapter):
    """
    Adapter for vLLM (pip install vllm).
    Best for full-precision HuggingFace models; needs significant VRAM.

    Install: pip install vllm
    Docs: https://docs.vllm.ai
    """

    default_port = 8082

    def _get_start_command(self, model_config: ModelConfig) -> list[str]:
        cmd = [
            "python",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            model_config.model,
            "--port",
            str(self._port),
            "--host",
            "127.0.0.1",
            "--max-model-len",
            str(model_config.context_length),
        ]

        if quantization := self._config.get("quantization"):
            cmd += ["--quantization", quantization]

        if dtype := self._config.get("dtype"):
            cmd += ["--dtype", dtype]

        return cmd
