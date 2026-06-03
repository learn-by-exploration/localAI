import pytest
import yaml

from src.core.registry import ModelRegistry, ModelRole, RuntimeType


SAMPLE_YAML = {
    "models": [
        {
            "id": "test-coder",
            "name": "Test Coder 7B",
            "runner": "ollama",
            "model": "test-coder:7b",
            "role": "coding",
            "priority": "fast",
            "context_length": 8192,
            "vram_required_mb": 5000,
        },
        {
            "id": "test-chat",
            "name": "Test Chat 9B",
            "runner": "ollama",
            "model": "test-chat:9b",
            "role": "chat",
            "priority": "balanced",
        },
        {
            "id": "test-disabled",
            "name": "Disabled Model",
            "runner": "ollama",
            "model": "disabled:7b",
            "role": "chat",
            "enabled": False,
        },
    ],
    "aliases": [
        {"alias": "claude-sonnet", "model_id": "test-coder"},
        {"alias": "gpt-4", "model_id": "test-coder"},
    ],
    "fallback_chains": [
        {"name": "coding", "models": ["test-coder", "test-chat"]},
    ],
    "default_model": "test-coder",
}


@pytest.fixture
def registry(tmp_path):
    config_file = tmp_path / "models.yaml"
    config_file.write_text(yaml.dump(SAMPLE_YAML))
    reg = ModelRegistry(str(config_file))
    reg.load()
    return reg


def test_get_model_by_id(registry):
    model = registry.get_model("test-coder")
    assert model is not None
    assert model.id == "test-coder"
    assert model.runner == RuntimeType.ollama


def test_resolve_alias(registry):
    model = registry.get_model("claude-sonnet")
    assert model is not None
    assert model.id == "test-coder"


def test_resolve_gpt_alias(registry):
    model = registry.get_model("gpt-4")
    assert model is not None
    assert model.id == "test-coder"


def test_disabled_model_excluded(registry):
    model = registry.get_model("test-disabled")
    assert model is None


def test_get_models_by_role_coding(registry):
    models = registry.get_models_by_role(ModelRole.coding)
    assert len(models) == 1
    assert models[0].id == "test-coder"


def test_get_models_by_role_chat(registry):
    models = registry.get_models_by_role(ModelRole.chat)
    assert len(models) == 1
    assert models[0].id == "test-chat"


def test_get_default_model(registry):
    model = registry.get_default_model()
    assert model is not None
    assert model.id == "test-coder"


def test_fallback_chain(registry):
    chain = registry.get_fallback_chain("coding")
    assert "test-coder" in chain
    assert "test-chat" in chain


def test_unknown_model_returns_none(registry):
    assert registry.get_model("nonexistent") is None


def test_get_all_models_excludes_disabled(registry):
    all_models = registry.get_all_models()
    ids = [m.id for m in all_models]
    assert "test-disabled" not in ids
    assert len(ids) == 2


def test_get_all_identifiers_includes_aliases(registry):
    ids = registry.get_all_identifiers()
    assert "test-coder" in ids
    assert "claude-sonnet" in ids
    assert "gpt-4" in ids
