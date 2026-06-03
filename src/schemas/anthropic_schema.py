from __future__ import annotations

from typing import Any, Union

from pydantic import BaseModel


class AnthropicContentBlock(BaseModel):
    type: str
    text: str | None = None


class AnthropicMessage(BaseModel):
    role: str
    content: Union[str, list[AnthropicContentBlock]]

    def text_content(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return " ".join(b.text or "" for b in self.content)


class AnthropicTool(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict[str, Any] = {}


class AnthropicSystemBlock(BaseModel):
    type: str = "text"
    text: str = ""
    cache_control: dict | None = None


class AnthropicRequest(BaseModel):
    model: str
    messages: list[AnthropicMessage]
    # Claude Code sends system as a list of content blocks; plain clients send a string
    system: Union[str, list[AnthropicSystemBlock], None] = None
    max_tokens: int = 4096
    temperature: float | None = None
    top_p: float | None = None
    stream: bool | None = False
    tools: list[AnthropicTool] | None = None

    def system_text(self) -> str | None:
        if self.system is None:
            return None
        if isinstance(self.system, str):
            return self.system
        return " ".join(b.text for b in self.system if b.text)


class AnthropicResponseContent(BaseModel):
    type: str
    text: str | None = None


class AnthropicUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class AnthropicResponse(BaseModel):
    id: str
    type: str = "message"
    role: str = "assistant"
    content: list[AnthropicResponseContent]
    model: str
    stop_reason: str | None = None
    stop_sequence: str | None = None
    usage: AnthropicUsage
