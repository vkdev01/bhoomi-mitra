"""The tool registry the agent loop dispatches through.

Open/Closed in practice: adding a capability to the assistant means registering
another ``ToolSpec`` + handler at the composition root. Neither this module nor
``AskAssistant`` changes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from bhoomi.domain.messages import ToolOutcome, ToolSpec

ToolHandler = Callable[[Mapping[str, Any]], ToolOutcome]


@dataclass(slots=True)
class ToolRegistry:
    """A name -> (schema, handler) map with duplicate-name protection."""

    _specs: dict[str, ToolSpec] = field(default_factory=dict)
    _handlers: dict[str, ToolHandler] = field(default_factory=dict)

    def register(self, spec: ToolSpec, handler: ToolHandler) -> ToolRegistry:
        if spec.name in self._specs:
            raise ValueError(f"tool already registered: {spec.name}")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler
        return self

    def specs(self) -> Sequence[ToolSpec]:
        return tuple(self._specs.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def has(self, name: str) -> bool:
        return name in self._handlers

    def invoke(self, name: str, arguments: Mapping[str, Any]) -> ToolOutcome:
        """Run a tool, converting any failure into a ``ToolOutcome``.

        A failing tool must never abort the agent loop: the model gets the
        failure back as observation and can recover or explain it.
        """
        handler = self._handlers.get(name)
        if handler is None:
            return ToolOutcome(
                name=name,
                ok=False,
                summary=f"Unknown tool {name!r}; available: {', '.join(self.names())}",
                payload={"error": "unknown_tool"},
            )
        try:
            return handler(dict(arguments or {}))
        except Exception as exc:  # noqa: BLE001 - deliberately broad at the boundary
            return ToolOutcome(
                name=name,
                ok=False,
                summary=f"Tool {name} failed: {type(exc).__name__}: {exc}",
                payload={"error": str(exc)},
            )
