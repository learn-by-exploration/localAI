"""
title: Gateway Control
author: local-ai-gateway
description: Start/stop your local AI gateway and switch between local/cloud profiles — all from Open WebUI chat. Commands: start, stop, status, switch to local, switch to cloud, list models.
version: 2.0.0
required_open_webui_version: 0.3.0
"""

import httpx
from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        GATEWAY_URL: str = Field(
            default="http://host.docker.internal:8080",
            description="Local AI Gateway URL",
        )
        CONTROL_URL: str = Field(
            default="http://host.docker.internal:8089",
            description="Control server URL (handles start/stop when gateway is down)",
        )
        GATEWAY_SECRET: str = Field(
            default="",
            description="Optional X-Gateway-Secret for protected gateway/control endpoints",
        )
        OPENAI_API_KEY: str = Field(
            default="",
            description="OpenAI API key for cloud mode",
        )
        ANTHROPIC_API_KEY: str = Field(
            default="",
            description="Anthropic API key for cloud mode",
        )

    def __init__(self):
        self.name = "Gateway Control"
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": "gateway-control", "name": "🔀 Gateway Control"}]

    async def pipe(self, body: dict, __user: dict = {}) -> str:
        gw = self.valves.GATEWAY_URL
        ctrl = self.valves.CONTROL_URL
        headers = self._auth_headers()

        messages = body.get("messages", [])
        if not messages:
            return self._help()

        msg = messages[-1].get("content", "").lower().strip()

        async with httpx.AsyncClient(timeout=60.0) as client:

            # ── START ──────────────────────────────────────────────────────────
            if _intent(msg, ["start", "wake up", "turn on", "boot up", "spin up"]):
                try:
                    resp = await client.post(f"{ctrl}/start", headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    steps = "\n".join(f"  - {s}" for s in data.get("steps", []))
                    model = data.get("model_name") or data.get("model_id") or "loading..."
                    vram = data.get("vram_used_mb")
                    vram_total = data.get("vram_total_mb")
                    vram_str = f"{vram}MB / {vram_total}MB" if vram else "—"
                    return (
                        "✅ **Gateway started**\n\n"
                        f"{steps}\n\n"
                        f"**Active model:** {model}\n"
                        f"**VRAM:** {vram_str}\n\n"
                        "_Ready. Switch to `qwen-small` or any other model in the dropdown._"
                    )
                except Exception as e:
                    return f"❌ Could not reach control server: {e}\n\nTry: `bash start.sh` in the terminal."

            # ── STOP ───────────────────────────────────────────────────────────
            elif _intent(msg, ["stop", "shut down", "shutdown", "sleep", "turn off",
                                "done for today", "done for the day", "i'm done",
                                "im done", "free gpu", "free vram"]):
                try:
                    resp = await client.post(f"{ctrl}/stop", headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    steps = "\n".join(f"  - {s}" for s in data.get("steps", []))
                    return (
                        "🛑 **Gateway stopped**\n\n"
                        f"{steps}\n\n"
                        "GPU memory freed. Open WebUI stays running.\n\n"
                        "_Type `start` here when you want to work again._"
                    )
                except Exception as e:
                    return f"❌ Could not reach control server: {e}\n\nTry: `bash stop.sh` in the terminal."

            # ── STATUS ─────────────────────────────────────────────────────────
            elif _intent(msg, ["status", "what's running", "whats running",
                                "current profile", "show status", "what mode",
                                "which model", "health check"]):
                try:
                    # Try control server first (works even if gateway is down)
                    ctrl_resp = await client.get(f"{ctrl}/status", headers=headers)
                    ctrl_resp.raise_for_status()
                    ctrl_data = ctrl_resp.json()
                    ollama_up = ctrl_data.get("ollama", False)
                    gateway_up = ctrl_data.get("gateway", False)

                    if not gateway_up:
                        return (
                            "⚠️ **Gateway is offline**\n\n"
                            f"- Ollama: {'✅ running' if ollama_up else '❌ stopped'}\n"
                            f"- Gateway: ❌ stopped\n"
                            f"- Open WebUI: ✅ running\n\n"
                            "Type `start` to bring everything back up."
                        )

                    # Gateway is up — get full status
                    gw_resp = await client.get(f"{gw}/api/profile", headers=headers)
                    gw_resp.raise_for_status()
                    gw_data = gw_resp.json()
                    sys_resp = await client.get(f"{gw}/api/status")
                    sys_data = sys_resp.json().get("system", {})

                    profile = gw_data.get("profile", "local")
                    icon = "🖥️" if profile == "local" else "☁️"
                    active = gw_data.get("active_model_name") or gw_data.get("active_model") or "—"
                    gw_status = gw_data.get("gateway_status", "—")

                    vram = sys_data.get("vram_used_mb")
                    vram_total = sys_data.get("vram_total_mb")
                    vram_str = f"{vram}MB / {vram_total}MB" if vram else "N/A"

                    models_list = "\n".join(
                        f"  - `{m['id']}` ({m['role']}, {m['runner']})"
                        for m in gw_data.get("models", [])
                    )

                    return (
                        f"{icon} **Profile: {profile.upper()}**\n\n"
                        f"| Service | Status |\n"
                        f"|---|---|\n"
                        f"| Ollama | {'✅ running' if ollama_up else '❌ stopped'} |\n"
                        f"| Gateway | ✅ running |\n"
                        f"| Open WebUI | ✅ running |\n\n"
                        f"**Active model:** {active} ({gw_status})\n"
                        f"**VRAM:** {vram_str}\n"
                        f"**RAM:** {sys_data.get('ram_percent', '—')}%\n"
                        f"**CPU:** {sys_data.get('cpu_percent', '—')}%\n"
                        f"**GPU temp:** {sys_data.get('gpu_temp', '—')}°C\n\n"
                        f"**Available models:**\n{models_list}"
                    )
                except Exception as e:
                    return f"❌ Error: {e}"

            # ── SWITCH TO LOCAL ────────────────────────────────────────────────
            elif _intent(msg, ["switch to local", "use local", "go local", "local mode"]):
                return await self._switch(client, gw, ctrl, "local", headers)

            # ── SWITCH TO CLOUD ────────────────────────────────────────────────
            elif _intent(msg, ["switch to cloud", "use cloud", "go cloud",
                                "cloud mode", "restore cloud", "reset to cloud"]):
                return await self._switch(client, gw, ctrl, "cloud", headers)

            # ── LIST MODELS ────────────────────────────────────────────────────
            elif _intent(msg, ["list models", "show models", "what models",
                                "available models"]):
                try:
                    resp = await client.get(f"{gw}/v1/models")
                    models = resp.json().get("data", [])
                    lines = "\n".join(f"- `{m['id']}`" for m in models)
                    return f"**Available models ({len(models)}):**\n\n{lines}"
                except Exception as e:
                    return f"❌ Gateway unreachable. Type `start` to bring it up.\n({e})"

            # ── HELP ───────────────────────────────────────────────────────────
            else:
                return self._help()

    async def _switch(self, client, gw, ctrl, profile, headers):
        # Start gateway first if it's down
        try:
            await client.get(f"{gw}/api/status", timeout=3)
        except Exception:
            start_resp = await client.post(f"{ctrl}/start", headers=headers)
            start_resp.raise_for_status()
            import asyncio; await asyncio.sleep(5)

        payload: dict = {"profile": profile}
        if self.valves.OPENAI_API_KEY:
            payload["openai_api_key"] = self.valves.OPENAI_API_KEY
        if self.valves.ANTHROPIC_API_KEY:
            payload["anthropic_api_key"] = self.valves.ANTHROPIC_API_KEY

        try:
            resp = await client.post(f"{gw}/api/profile", json=payload, headers=headers)
            if resp.status_code == 400:
                detail = resp.json().get("detail", "")
                return (
                    f"❌ **Cannot switch to {profile}**: {detail}\n\n"
                    "Set your API keys in this function's settings:\n"
                    "Admin → Functions → Gateway Control → ⚙️"
                )
            resp.raise_for_status()
            data = resp.json()
            icon = "🖥️" if profile == "local" else "☁️"
            runtime = "Ollama (on your machine)" if profile == "local" else "OpenAI / Anthropic APIs"
            active = data.get("default_model", "—")
            models = ", ".join(f"`{m}`" for m in data.get("models", []))
            msg = "Your API limits are no longer at risk. All requests run on your GPU." if profile == "local" \
                else "Requests are forwarded to cloud APIs."
            return (
                f"{icon} **Switched to {profile.upper()} mode**\n\n"
                f"**Runtime:** {runtime}\n"
                f"**Active model:** `{active}`\n"
                f"**Available:** {models}\n\n"
                f"_{msg}_"
            )
        except Exception as e:
            return f"❌ Error: {e}"

    def _help(self) -> str:
        return (
            "**🔀 Gateway Control**\n\n"
            "| Command | Action |\n"
            "|---|---|\n"
            "| `start` | Start gateway + Ollama |\n"
            "| `stop` | Unload model, stop gateway + Ollama |\n"
            "| `status` | Show what's running + system metrics |\n"
            "| `switch to local` | Use Ollama (your GPU) |\n"
            "| `switch to cloud` | Use OpenAI / Anthropic APIs |\n"
            "| `list models` | Show available models |\n\n"
            "**Open WebUI always stays running** — only the gateway and Ollama start/stop.\n\n"
            "When you're done for the day, just type `stop`."
        )

    def _auth_headers(self) -> dict:
        if not self.valves.GATEWAY_SECRET:
            return {}
        return {"X-Gateway-Secret": self.valves.GATEWAY_SECRET}


def _intent(msg: str, phrases: list[str]) -> bool:
    return any(p in msg for p in phrases)
