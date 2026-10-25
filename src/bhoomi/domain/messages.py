"""Conversation and tool-call value objects shared by the agent loop.

These mirror the OpenAI-style tool-calling protocol that Sarvam's chat endpoint
speaks, but they are plain dataclasses so the application layer can reason about
a conversation without depending on the Sarvam SDK or on ``httpx``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A request from the model to run one tool."""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    call_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(dict(self.arguments), ensure_ascii=False),
            },
        }


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """The schema the model sees when deciding whether to call a tool."""

    name: str
    description: str
    parameters: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [call.as_dict() for call in self.tool_calls]
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        return payload


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """One assistant turn: either prose, or a batch of tool calls, or both."""

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """The result of invoking one tool, plus a short human-readable summary."""

    name: str
    ok: bool
    summary: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def as_tool_content(self) -> str:
        return json.dumps(
            {"ok": self.ok, "summary": self.summary, "data": dict(self.payload)},
            ensure_ascii=False,
            default=str,
        )


@dataclass(frozen=True, slots=True)
class AssistantAnswer:
    """What the assistant use case returns to the web layer."""

    answer: str
    language_code: str
    tool_trace: tuple[ToolOutcome, ...] = ()
    data_source: str = "unknown"
    degraded: bool = False
    notes: tuple[str, ...] = ()
