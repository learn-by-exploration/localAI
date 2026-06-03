import pytest
import yaml

from src.core.config import RouterConfig
from src.core.registry import ModelRegistry
from src.core.router import SmartRouter
from src.schemas.unified import MessageRole, TaskType, ToolDefinition, UnifiedMessage, UnifiedRequest


REGISTRY_YAML = {
    "models": [
        {"id": "coder", "name": "Coder", "runner": "ollama", "model": "coder:7b", "role": "coding", "priority": "quality"},
        {"id": "chat",  "name": "Chat",  "runner": "ollama", "model": "chat:9b",  "role": "chat",   "priority": "balanced"},
        {"id": "agent", "name": "Agent", "runner": "ollama", "model": "agent:7b", "role": "agent",  "priority": "balanced"},
        {"id": "long",  "name": "Long",  "runner": "ollama", "model": "long:14b", "role": "long_context", "priority": "quality"},
    ],
    "fallback_chains": [
        {"name": "coding",       "models": ["coder", "chat"]},
        {"name": "chat",         "models": ["chat", "coder"]},
        {"name": "agent",        "models": ["agent", "coder"]},
        {"name": "long_context", "models": ["long", "coder"]},
    ],
    "aliases": [],
    "default_model": "coder",
}


@pytest.fixture
def router(tmp_path):
    config_file = tmp_path / "models.yaml"
    config_file.write_text(yaml.dump(REGISTRY_YAML))
    reg = ModelRegistry(str(config_file))
    reg.load()
    return SmartRouter(reg, RouterConfig())


def _req(content: str, tools=None, task_type=TaskType.auto) -> UnifiedRequest:
    return UnifiedRequest(
        messages=[UnifiedMessage(role=MessageRole.user, content=content)],
        task_type=task_type,
        tools=tools,
    )


class TestTaskDetection:
    def test_coding_keywords(self, router):
        req = _req("Write a Python function to sort a list")
        assert router.detect_task_type(req) == TaskType.coding

    def test_debug_keyword(self, router):
        req = _req("debug this function that crashes")
        assert router.detect_task_type(req) == TaskType.coding

    def test_tools_means_agent(self, router):
        req = _req("search the web for results", tools=[
            ToolDefinition(name="search", description="search tool", parameters={})
        ])
        assert router.detect_task_type(req) == TaskType.agent

    def test_explicit_task_type_respected(self, router):
        req = _req("hello", task_type=TaskType.coding)
        assert router.detect_task_type(req) == TaskType.coding

    def test_long_context_detection(self, router):
        # >2000 token estimate (~8000 chars)
        long_text = "word " * 2000
        req = _req(long_text)
        assert router.detect_task_type(req) == TaskType.long_context

    def test_general_chat_default(self, router):
        req = _req("What is the capital of France?")
        assert router.detect_task_type(req) == TaskType.chat


class TestModelSelection:
    def test_coding_request_selects_coder(self, router):
        req = _req("write a Python class")
        model = router.select_model(req)
        assert model is not None
        assert model.id == "coder"

    def test_explicit_model_id_respected(self, router):
        req = _req("hello", task_type=TaskType.auto)
        req.model_id = "chat"
        model = router.select_model(req)
        assert model is not None
        assert model.id == "chat"

    def test_tools_selects_agent_model(self, router):
        req = _req("do a task", tools=[
            ToolDefinition(name="exec", description="", parameters={})
        ])
        model = router.select_model(req)
        assert model is not None
        assert model.id == "agent"

    def test_returns_model_even_for_unknown_type(self, router):
        req = _req("random question")
        model = router.select_model(req)
        assert model is not None


class TestFallbackChain:
    def test_fallback_chain_excludes_primary(self, router):
        chain = router.get_fallback_chain("coder")
        assert "coder" not in chain
        assert "chat" in chain

    def test_unknown_model_returns_empty(self, router):
        chain = router.get_fallback_chain("nonexistent")
        assert chain == []
