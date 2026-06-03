from __future__ import annotations

import re

from src.core.config import RouterConfig
from src.core.registry import ModelConfig, ModelRegistry, ModelRole
from src.schemas.unified import TaskType, UnifiedRequest

_CODING_RE = re.compile(
    r"\b(code|function|def |class |method|debug|bug|error|implement|algorithm|"
    r"python|javascript|typescript|rust|go|java|c\+\+|sql|api|test|refactor|"
    r"optimize|variable|loop|array|list|dict|import|module|package|library|"
    r"git|commit|dockerfile|yaml|json|html|css|async|await|thread|process|"
    r"compile|build|lint|type.?hint|return type|signature|unittest|pytest|"
    r"stack trace|exception|traceback)\b",
    re.IGNORECASE,
)

_AGENT_RE = re.compile(
    r"\b(tool_call|function.call|execute|search the web|browse|terminal|"
    r"command|workflow|automate|scrape|fetch|download|upload|"
    r"schedule|task queue|run a script|bash|shell)\b",
    re.IGNORECASE,
)

_PRIORITY_ORDER = ["quality", "balanced", "fast"]


class SmartRouter:
    def __init__(self, registry: ModelRegistry, config: RouterConfig):
        self._registry = registry
        self._config = config

    def detect_task_type(self, request: UnifiedRequest) -> TaskType:
        if request.task_type != TaskType.auto:
            return request.task_type

        if request.tools:
            return TaskType.agent

        all_text = " ".join(m.text_content() for m in request.messages)
        estimated_tokens = len(all_text) // 4
        if estimated_tokens > self._config.long_context_threshold_tokens:
            return TaskType.long_context

        last_user = next(
            (m for m in reversed(request.messages) if m.role == "user"), None
        )
        if last_user:
            text = last_user.text_content()
            if _CODING_RE.search(text):
                return TaskType.coding
            if _AGENT_RE.search(text):
                return TaskType.agent

        return TaskType.chat

    def select_model(self, request: UnifiedRequest) -> ModelConfig | None:
        if request.model_id:
            model = self._registry.get_model(request.model_id)
            if model:
                return model

        task_type = self.detect_task_type(request)
        role = _TASK_TO_ROLE.get(task_type, ModelRole.chat)
        candidates = self._registry.get_models_by_role(role)

        if not candidates:
            candidates = self._registry.get_all_models()

        for priority in _PRIORITY_ORDER:
            for model in candidates:
                if model.priority == priority:
                    return model

        return candidates[0] if candidates else None

    def get_fallback_chain(self, model_id: str) -> list[str]:
        model = self._registry.get_model(model_id)
        if not model:
            return []
        chain_name = _ROLE_TO_CHAIN.get(model.role, "chat")
        chain = self._registry.get_fallback_chain(chain_name)
        if model_id in chain:
            return chain[chain.index(model_id) + 1 :]
        return chain


_TASK_TO_ROLE: dict[TaskType, ModelRole] = {
    TaskType.coding: ModelRole.coding,
    TaskType.agent: ModelRole.agent,
    TaskType.long_context: ModelRole.long_context,
    TaskType.chat: ModelRole.chat,
}

_ROLE_TO_CHAIN: dict[ModelRole, str] = {
    ModelRole.coding: "coding",
    ModelRole.chat: "chat",
    ModelRole.agent: "agent",
    ModelRole.long_context: "long_context",
}
