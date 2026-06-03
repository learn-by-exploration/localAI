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

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
GATEWAY_LOG = "/tmp/gateway.log"
BASE_DIR = Path(__file__).parent
GATEWAY_SERVICE = "local-ai-gateway.service"


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


def _user_service_exists(service: str) -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "status", service],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode in (0, 3)


def _systemctl_user(service: str, action: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["systemctl", "--user", "--no-ask-password", action, service],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.returncode == 0, result.stderr.strip()


def _service_active(service: str, user: bool = False) -> bool:
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd.extend(["is-active", "--quiet", service])
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


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


def _docker_bridge_reachable() -> bool:
    return os.getenv("CONTROL_HOST", "") in {"172.17.0.1", "host.docker.internal"} or "172.17.0.1" in _local_ipv4_addresses()


def _local_ipv4_addresses() -> list[str]:
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, check=False)
    except Exception:
        return []
    return [part for part in result.stdout.split() if part.count(".") == 3]


def _diagnostics_sync() -> dict:
    status = _get_status_sync()
    gateway_service_exists = _user_service_exists(GATEWAY_SERVICE)
    ollama_service_exists = _system_ollama_service_exists()
    recommendations: list[str] = []

    if not status["gateway"] and not gateway_service_exists:
        recommendations.append("Install local-ai-gateway.service with ./install.sh for cleaner start/stop.")
    if not status["ollama"] and ollama_service_exists:
        recommendations.append("Run systemctl --no-ask-password start ollama.service or install the polkit rule if permission fails.")
    if not _docker_bridge_reachable():
        recommendations.append("For Docker Open WebUI, bind control/gateway to 172.17.0.1 and use host.docker.internal.")
    if not _SECRET:
        recommendations.append("Set GATEWAY_SECRET in ~/.config/local-ai-gateway/gateway.env and Open WebUI valves.")

    return {
        **status,
        "gateway_url": GATEWAY_URL,
        "gateway_service": {
            "name": GATEWAY_SERVICE,
            "installed": gateway_service_exists,
            "active": _service_active(GATEWAY_SERVICE, user=True),
        },
        "control": {
            "secret_enabled": bool(_SECRET),
            "local_ipv4": _local_ipv4_addresses(),
        },
        "ollama_service": {
            "name": "ollama.service",
            "installed": ollama_service_exists,
            "active": _service_active("ollama.service"),
            "pids": _ollama_pids(),
        },
        "docker": {
            "bridge_hint": "172.17.0.1",
            "host_alias": "host.docker.internal",
        },
        "recommendations": recommendations,
    }


@app.get("/status")
def status(x_gateway_secret: str | None = Header(default=None)):
    _check_auth(x_gateway_secret)
    return _get_status_sync()


@app.get("/diagnostics")
def diagnostics(x_gateway_secret: str | None = Header(default=None)):
    _check_auth(x_gateway_secret)
    return _diagnostics_sync()


@app.post("/start")
async def start(x_gateway_secret: str | None = Header(default=None)):
    _check_auth(x_gateway_secret)
    steps = []

    # Start Ollama
    if not _ollama_running():
        if _system_ollama_service_exists():
            started, error = _systemctl_ollama("start")
            if not started:
                logger.warning(f"Could not start ollama.service without admin permission: {error}")
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
        if _user_service_exists(GATEWAY_SERVICE):
            started, error = _systemctl_user(GATEWAY_SERVICE, "start")
            if not started:
                logger.warning(f"Could not start {GATEWAY_SERVICE}: {error}")
        else:
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

        if _user_service_exists(GATEWAY_SERVICE):
            stopped, error = _systemctl_user(GATEWAY_SERVICE, "stop")
            if not stopped:
                logger.warning(f"Could not stop {GATEWAY_SERVICE}: {error}")
        else:
            subprocess.run(["fuser", "-k", "8080/tcp"], capture_output=True, check=False)
        await asyncio.sleep(1)
        steps.append("gateway stopped" if not _gateway_running() else "gateway stop failed; still running")
    else:
        steps.append("gateway was not running")

    steps.append(await _stop_ollama())

    return {"ok": True, "steps": steps}


if __name__ == "__main__":
    import uvicorn
    # Bind to localhost only — control server must never be network-exposed
    uvicorn.run(app, host="127.0.0.1", port=8089, log_level="info")
