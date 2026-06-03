from __future__ import annotations

from typing import TYPE_CHECKING

from src.adapters._subprocess_openai import SubprocessOpenAIAdapter

if TYPE_CHECKING:
    from src.core.registry import ModelConfig


class SGLangAdapter(SubprocessOpenAIAdapter):
    """
    Adapter for SGLang (pip install sglang).
    High-throughput inference with structured generation support.

    Install: pip install "sglang[all]"
    Docs: https://docs.sglang.ai
    """

    default_port = 8083

    def _get_start_command(self, model_config: ModelConfig) -> list[str]:
        cmd = [
            "python",
            "-m",
            "sglang.launch_server",
            "--model-path",
            model_config.model,
            "--port",
            str(self._port),
            "--host",
            "127.0.0.1",
            "--context-length",
            str(model_config.context_length),
        ]

        if tp := self._config.get("tensor_parallel_size"):
            cmd += ["--tp", str(tp)]

        return cmd
