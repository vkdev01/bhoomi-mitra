"""Use case: answer a citizen's question with an agentic tool loop.

The loop is deliberately small and explicit:

    model -> tool calls -> observations -> model -> ... -> final prose

It is bounded, fully traced, and the model is only ever given observations that
came back from real tool invocations. Nothing here knows what a hospital is or
what Bhuvan is; that lives in the tools and the adapters.
"""

from __future__ import annotations

from dataclasses import dataclass

from bhoomi.application.tool_registry import ToolRegistry
from bhoomi.domain.messages import (
    AssistantAnswer,
    Message,
    Role,
    ToolOutcome,
)
from bhoomi.domain.ports import LanguageModel

SYSTEM_PROMPT = """You are Bhoomi Mitra, a helpful civic-information assistant for \
people in India. You answer questions about a village or town using official \
ISRO / NRSC Bhuvan data: land use and land cover statistics, nearby hospitals \
and post offices, and road routing.

How to work:
1. Decide which tools you need. Prefer calling a tool over guessing.
2. Use `resolve_place` first whenever you are not sure of a village's location.
3. Call `land_cover`, `nearby_facilities` and `route_to_facility` as needed.
4. Base every number you quote on a tool result. If a tool returns no data, say \
so plainly instead of inventing a figure.
5. When the tool results are enough, answer in the user's language, in warm, \
plain, everyday wording. Keep it short: two to five sentences. Mention that the \
source is ISRO Bhuvan.

Never claim to have data you did not fetch. Never invent place names, \
distances or percentages."""

_FINAL_NUDGE = (
    "You have used the tools you needed. Now write the final answer for the "
    "citizen in their language, using only the tool results above."
)


@dataclass(frozen=True, slots=True)
class AskRequest:
    question: str
    language_code: str = "en-IN"
    max_steps: int = 5


class AskAssistant:
    """Runs the tool-calling loop for one question."""

    def __init__(
        self,
        llm: LanguageModel,
        tools: ToolRegistry,
        *,
        data_source: str = "unknown",
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._data_source = data_source

    def handle(self, request: AskRequest) -> AssistantAnswer:
        if not request.question.strip():
            raise ValueError("question must not be empty")

        messages: list[Message] = [
            Message(role=Role.SYSTEM, content=SYSTEM_PROMPT),
            Message(
                role=Role.USER,
                content=(
                    f"{request.question.strip()}\n\n"
                    f"(Answer in {request.language_code}.)"
                ),
            ),
        ]
        trace: list[ToolOutcome] = []
        notes: list[str] = []

        for _ in range(max(1, request.max_steps)):
            turn = self._llm.respond(messages, self._tools.specs())

            if not turn.wants_tools:
                return self._finish(
                    turn.content, request, trace, notes, degraded=not trace
                )

            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=turn.content,
                    tool_calls=turn.tool_calls,
                )
            )
            for call in turn.tool_calls:
                outcome = self._tools.invoke(call.name, call.arguments)
                trace.append(outcome)
                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=outcome.as_tool_content(),
                        tool_call_id=call.call_id or call.name,
                    )
                )

        # Step budget exhausted: ask for a wrap-up with no tools available.
        notes.append(
            "The assistant reached its tool-call budget and summarised what it had."
        )
        closing = self._llm.respond(
            [*messages, Message(role=Role.USER, content=_FINAL_NUDGE)], ()
        )
        return self._finish(
            closing.content or "I could not gather enough information to answer.",
            request,
            trace,
            notes,
            degraded=True,
        )

    def _finish(
        self,
        text: str,
        request: AskRequest,
        trace: list[ToolOutcome],
        notes: list[str],
        *,
        degraded: bool,
    ) -> AssistantAnswer:
        failed = [o for o in trace if not o.ok]
        if failed and not notes:
            notes.append(
                f"{len(failed)} tool call(s) did not return data; the answer may "
                "be incomplete."
            )
        return AssistantAnswer(
            answer=text.strip(),
            language_code=request.language_code,
            tool_trace=tuple(trace),
            data_source=self._data_source,
            degraded=degraded,
            notes=tuple(notes),
        )
