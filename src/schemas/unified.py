from __future__ import annotations

from enum import Enum
from typing import Union

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    coding = "coding"
    chat = "chat"
    agent = "agent"
    long_context = "long_context"
    auto = "auto"


class MessageRole(str, Enum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"
    function = "function"


class ContentPart(BaseModel):
    type: str
    text: str | None = None


class UnifiedMessage(BaseModel):
    role: MessageRole
    content: Union[str, list[ContentPart]]

    def text_content(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return " ".join(p.text or "" for p in self.content)


class ToolDefinition(BaseModel):
    name: str
    description: str = ""
    parameters: dict = Field(default_factory=dict)


class UnifiedRequest(BaseModel):
    messages: list[UnifiedMessage]
    system: str | None = None
    tools: list[ToolDefinition] | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float | None = None
    stream: bool = False
    model_id: str | None = None
    task_type: TaskType = TaskType.auto
    request_id: str | None = None


class UnifiedDelta(BaseModel):
    content: str | None = None
    role: str | None = None


class UnifiedChoice(BaseModel):
    index: int = 0
    message: UnifiedMessage | None = None
    delta: UnifiedDelta | None = None
    finish_reason: str | None = None


class UnifiedUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class UnifiedResponse(BaseModel):
    id: str
    model: str
    choices: list[UnifiedChoice]
    usage: UnifiedUsage | None = None
    created: int = 0
