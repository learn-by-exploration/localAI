"""
Lightweight control server — always running on the host.
Lets Open WebUI start/stop the gateway and Ollama via HTTP.
Port: 8089  (separate from gateway :8080)
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Gateway Control Server", version="1.0.0")
# Bind only to localhost — never expose control server to the network.
# CORSMiddleware is still needed for the Open WebUI browser client.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_SECRET = os.getenv("GATEWAY_SECRET", "")


def _check_auth(x_gateway_secret: str | None) -> None:
    if not _SECRET:
        return  # No secret configured — local-only mode, skip check
    if x_gateway_secret != _SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Gateway-Secret header")

GATEWAY_URL = "http://localhost:8080"
GATEWAY_LOG = "/tmp/gateway.log"
BASE_DIR = Path(__file__).parent


def _gateway_running() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen(f"{GATEWAY_URL}/api/status", timeout=3)
        return True
    except Exception:
        return False


def _ollama_running() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        return True
    except Exception:
        return False


def _system_ollama_service_exists() -> bool:
    result = subprocess.run(
        ["systemctl", "status", "ollama.service"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode in (0, 3)


def _systemctl_ollama(action: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["systemctl", "--no-ask-password", action, "ollama.service"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.returncode == 0, result.stderr.strip()


def _ollama_pids() -> list[int]:
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,comm=,args="],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []

    pids: list[int] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) < 3:
            continue
        pid_text, command, args = parts
        if command != "ollama" or "serve" not in args.split():
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid != os.getpid():
            pids.append(pid)
    return pids


async def _stop_ollama() -> str:
    if not _ollama_running():
        return "ollama was not running"

    if _system_ollama_service_exists():
        stopped, error = _systemctl_ollama("stop")
        if stopped:
            for _ in range(10):
                await asyncio.sleep(0.5)
                if not _ollama_running():
                    return "ollama stopped"
        else:
            logger.warning(f"Could not stop ollama.service without admin permission: {error}")
            return "ollama still running; system service needs admin permission to stop"

    pids = _ollama_pids()
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning(f"Could not terminate Ollama pid {pid}: {e}")

    for _ in range(10):
        await asyncio.sleep(0.5)
        if not _ollama_running():
            return "ollama stopped"

    for pid in _ollama_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning(f"Could not kill Ollama pid {pid}: {e}")

    for _ in range(6):
        await asyncio.sleep(0.5)
        if not _ollama_running():
            return "ollama stopped"

    return "ollama stop failed; still running"


def _get_status_sync() -> dict:
    ollama = _ollama_running()
    gateway = _gateway_running()
    model_info = {}

    if gateway:
        try:
            import urllib.request, json
            with urllib.request.urlopen(f"{GATEWAY_URL}/api/status", timeout=5) as r:
                data = json.loads(r.read())
            model_info = {
                "model_id": data.get("model_id"),
                "model_name": data.get("model_name"),
                "model_status": data.get("status"),
                "vram_used_mb": data.get("system", {}).get("vram_used_mb"),
                "vram_total_mb": data.get("system", {}).get("vram_total_mb"),
                "gpu_temp": data.get("system", {}).get("gpu_temp"),
            }
        except Exception:
            pass

    return {
        "ollama": ollama,
        "gateway": gateway,
        **model_info,
    }


@app.get("/status")
def status(x_gateway_secret: str | None = Header(default=None)):
    _check_auth(x_gateway_secret)
    return _get_status_sync()


@app.post("/start")
async def start(x_gateway_secret: str | None = Header(default=None)):
    _check_auth(x_gateway_secret)
    steps = []

    # Start Ollama
    if not _ollama_running():
        if _system_ollama_service_exists():
            _systemctl_ollama("start")
        else:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        for _ in range(15):
            await asyncio.sleep(1)
            if _ollama_running():
                steps.append("ollama started")
                break
        else:
            steps.append("ollama start timed out")
    else:
        steps.append("ollama already running")

    # Start gateway — open log file in a with-block to avoid fd leak
    if not _gateway_running():
        uvicorn = os.path.expanduser("~/.local/bin/uvicorn")
        if not os.path.exists(uvicorn):
            uvicorn = "uvicorn"

        with open(GATEWAY_LOG, "w") as log_f:
            subprocess.Popen(
                [uvicorn, "src.main:app", "--host", "0.0.0.0", "--port", "8080"],
                cwd=str(BASE_DIR),
                stdout=log_f,
                stderr=subprocess.STDOUT,
            )
        for _ in range(30):
            await asyncio.sleep(2)
            if _gateway_running():
                steps.append("gateway started")
                break
        else:
            steps.append("gateway start timed out")
    else:
        steps.append("gateway already running")

    return {"ok": True, "steps": steps, **_get_status_sync()}


@app.post("/stop")
async def stop(x_gateway_secret: str | None = Header(default=None)):
    _check_auth(x_gateway_secret)
    steps = []

    # Unload model from VRAM first
    if _gateway_running():
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{GATEWAY_URL}/api/models/stop")
            steps.append("model unloaded from VRAM")
        except Exception:
            pass

        # Kill gateway
        result = subprocess.run(["fuser", "-k", "8080/tcp"], capture_output=True)
        steps.append("gateway stopped")
        await asyncio.sleep(1)
    else:
        steps.append("gateway was not running")

    steps.append(await _stop_ollama())

    return {"ok": True, "steps": steps}


if __name__ == "__main__":
    import uvicorn
    # Bind to localhost only — control server must never be network-exposed
    uvicorn.run(app, host="127.0.0.1", port=8089, log_level="info")
