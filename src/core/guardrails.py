from __future__ import annotations

import logging
import subprocess

import psutil

from src.core.config import ResourceLimits

logger = logging.getLogger(__name__)


def get_vram_usage_mb() -> int | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            return sum(int(v) for v in lines if v.strip())
    except Exception:
        pass
    return None


def get_vram_total_mb() -> int | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            return sum(int(v) for v in lines if v.strip())
    except Exception:
        pass
    return None


def get_gpu_temp() -> float | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return None


def get_cpu_temp() -> float | None:
    try:
        temps = psutil.sensors_temperatures()
        for key in ("coretemp", "k10temp", "cpu_thermal"):
            if key in temps and temps[key]:
                return temps[key][0].current
    except Exception:
        pass
    return None


class ResourceGuardrails:
    def __init__(self, limits: ResourceLimits):
        self._limits = limits

    def check_can_load(self, vram_required_mb: int | None = None) -> tuple[bool, str]:
        vm = psutil.virtual_memory()
        ram_used_mb = vm.used // (1024 * 1024)
        if ram_used_mb > self._limits.max_ram_mb:
            return False, f"RAM {ram_used_mb}MB exceeds limit {self._limits.max_ram_mb}MB"

        if vram_required_mb:
            vram_used = get_vram_usage_mb()
            if vram_used is not None:
                if vram_used + vram_required_mb > self._limits.max_vram_mb:
                    free = self._limits.max_vram_mb - vram_used
                    return (
                        False,
                        f"Need {vram_required_mb}MB VRAM but only {free}MB free",
                    )

        return True, "OK"

    def get_system_metrics(self) -> dict:
        vm = psutil.virtual_memory()
        vram_used = get_vram_usage_mb()
        vram_total = get_vram_total_mb()
        return {
            "vram_used_mb": vram_used,
            "vram_total_mb": vram_total,
            "vram_percent": round(vram_used / vram_total * 100, 1)
            if vram_used is not None and vram_total
            else None,
            "ram_used_mb": vm.used // (1024 * 1024),
            "ram_total_mb": vm.total // (1024 * 1024),
            "ram_percent": round(vm.percent, 1),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "gpu_temp": get_gpu_temp(),
            "cpu_temp": get_cpu_temp(),
        }
