"""Integration tests for the FastAPI app using TestClient."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

# We patch heavy lifecycle/adapter calls so tests run without Ollama installed


REGISTRY_YAML = {
    "models": [
        {
            "id": "test-coder",
            "name": "Test Coder",
            "runner": "ollama",
            "model": "test:7b",
            "role": "coding",
            "priority": "fast",
        }
    ],
    "aliases": [{"alias": "active", "model_id": "test-coder"}],
    "fallback_chains": [],
    "default_model": "test-coder",
}


@pytest.fixture
def models_yaml(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text(yaml.dump(REGISTRY_YAML))
    return str(path)


@pytest.fixture
def client(models_yaml, monkeypatch):
    monkeypatch.setenv("MODELS_CONFIG", models_yaml)

    # Prevent auto-loading model on startup
    with patch("src.core.lifecycle.ModelLifecycle.load_model", new_callable=AsyncMock, return_value=True), \
         patch("src.core.lifecycle.ModelLifecycle.unload_current", new_callable=AsyncMock):
        from src.main import create_app
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def test_get_models(client):
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert any(m["id"] == "test-coder" for m in data["data"])


def test_api_models_list(client):
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert "active" in data
    assert "system" in data


def test_api_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "system" in data
    assert "queue" in data


def test_api_diagnostics(client):
    resp = client.get("/api/diagnostics")
    assert resp.status_code == 200
    data = resp.json()
    assert "profile" in data
    assert "status" in data
    assert "queue" in data
    assert "system" in data
    assert "models" in data
    assert "recommendations" in data


def test_metrics_endpoint(client):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "timestamp" in data
    assert "system" in data
    assert "queue" in data


def test_start_model_not_found(client):
    resp = client.post("/api/models/start", json={"model_id": "nonexistent"})
    assert resp.status_code == 404


def test_stop_model(client):
    resp = client.post("/api/models/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
