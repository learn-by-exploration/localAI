from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel


class OAIContentPart(BaseModel):
    type: str
    text: str | None = None


class OAIMessage(BaseModel):
    role: str
    content: Union[str, list[OAIContentPart], None] = None
    name: str | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None


class OAIFunctionDef(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] = {}


class OAITool(BaseModel):
    type: Literal["function"] = "function"
    function: OAIFunctionDef


class OAIChatRequest(BaseModel):
    model: str
    messages: list[OAIMessage]
    temperature: float | None = 0.7
    max_tokens: int | None = None
    top_p: float | None = None
    stream: bool | None = False
    tools: list[OAITool] | None = None
    tool_choice: Any | None = None
    n: int | None = 1
    stop: Union[str, list[str], None] = None
    frequency_penalty: float | None = 0.0
    presence_penalty: float | None = 0.0
    user: str | None = None


class OAIDelta(BaseModel):
    role: str | None = None
    content: str | None = None


class OAIChoice(BaseModel):
    index: int
    message: OAIMessage | None = None
    delta: OAIDelta | None = None
    finish_reason: str | None = None
    logprobs: None = None


class OAIUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class OAIChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[OAIChoice]
    usage: OAIUsage | None = None


class OAIStreamChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[OAIChoice]


class OAIModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "local"


class OAIModelsResponse(BaseModel):
    object: str = "list"
    data: list[OAIModelInfo]
