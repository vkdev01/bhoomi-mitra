"""Tests for the agent loop, the tool registry and the offline planner."""

from __future__ import annotations

import pytest

from bhoomi.adapters.fixtures import FixtureGeoProvider
from bhoomi.adapters.offline_llm import RuleBasedLanguageModel
from bhoomi.application.assistant import AskAssistant, AskRequest
from bhoomi.application.tool_registry import ToolRegistry
from bhoomi.application.tools import build_tool_registry
from bhoomi.domain.messages import Message, ModelTurn, Role, ToolCall, ToolOutcome, ToolSpec

# -- registry -------------------------------------------------------------


def _outcome(name: str = "t") -> ToolOutcome:
    return ToolOutcome(name=name, ok=True, summary="fine")


def test_registry_stores_and_lists_specs():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="echo", description="d", parameters={"type": "object"}),
        lambda args: _outcome("echo"),
    )
    assert registry.names() == ("echo",)
    assert registry.specs()[0].name == "echo"


def test_registry_rejects_duplicate_names():
    registry = ToolRegistry()
    spec = ToolSpec(name="echo", description="d", parameters={"type": "object"})
    registry.register(spec, lambda args: _outcome())
    with pytest.raises(ValueError):
        registry.register(spec, lambda args: _outcome())


def test_registry_invokes_a_handler():
    registry = ToolRegistry().register(
        ToolSpec(name="echo", description="d", parameters={"type": "object"}),
        lambda args: ToolOutcome(name="echo", ok=True, summary=str(args["x"])),
    )
    assert registry.invoke("echo", {"x": 1}).summary == "1"


def test_registry_turns_exceptions_into_failed_outcomes():
    def boom(args):
        raise RuntimeError("kaput")

    registry = ToolRegistry().register(
        ToolSpec(name="boom", description="d", parameters={"type": "object"}), boom
    )
    outcome = registry.invoke("boom", {})
    assert outcome.ok is False
    assert "kaput" in outcome.summary


def test_registry_reports_an_unknown_tool_as_a_failed_outcome():
    """A hallucinated tool name must not crash the agent loop."""
    outcome = ToolRegistry().invoke("nope", {})
    assert outcome.ok is False
    assert "Unknown tool" in outcome.summary


# -- tool handlers --------------------------------------------------------


@pytest.fixture()
def registry(fixture_path) -> ToolRegistry:
    geo = FixtureGeoProvider(fixture_path)
    return build_tool_registry(geo, geo, geo, geo)


def test_resolve_place_tool_returns_census_data(registry):
    outcome = registry.invoke("resolve_place", {"place": "Sekuru"})
    assert outcome.ok
    assert outcome.payload["population"] == 10207
    assert "10,207" in outcome.summary


def test_resolve_place_tool_reports_unknown_places(registry):
    outcome = registry.invoke("resolve_place", {"place": "Atlantis"})
    assert outcome.ok is False
    assert "Atlantis" in outcome.summary


def test_land_cover_tool_reports_percentages(registry):
    outcome = registry.invoke("land_cover", {"lat": 16.2794, "lon": 80.5884})
    assert outcome.ok
    assert "%" in outcome.summary
    assert outcome.payload["classes"]


def test_land_cover_tool_validates_coordinates(registry):
    outcome = registry.invoke("land_cover", {"lat": "abc", "lon": 80.0})
    assert outcome.ok is False


def test_land_cover_tool_requires_coordinates(registry):
    outcome = registry.invoke("land_cover", {})
    assert outcome.ok is False
    assert "missing required argument" in outcome.summary


def test_nearby_facilities_tool_filters_by_kind(registry):
    outcome = registry.invoke(
        "nearby_facilities", {"lat": 16.2794, "lon": 80.5884, "radius_m": 20000, "kind": "postal"}
    )
    assert outcome.ok
    assert all(f["kind"] == "postal" for f in outcome.payload["facilities"])


def test_nearby_facilities_tool_rejects_unknown_kind(registry):
    outcome = registry.invoke(
        "nearby_facilities", {"lat": 16.2794, "lon": 80.5884, "kind": "spaceport"}
    )
    assert outcome.ok is False


def test_route_tool_returns_a_distance(registry):
    outcome = registry.invoke(
        "route_to_facility",
        {"lat1": 16.2794, "lon1": 80.5884, "lat2": 16.2841, "lon2": 80.5921},
    )
    assert outcome.ok
    assert outcome.payload["distance_km"] > 0


def test_tool_schemas_are_valid_openai_shapes(registry):
    for spec in registry.specs():
        payload = spec.as_dict()
        assert payload["type"] == "function"
        assert payload["function"]["name"]
        assert payload["function"]["parameters"]["type"] == "object"


# -- agent loop -----------------------------------------------------------


def test_assistant_answers_after_using_tools(registry):
    assistant = AskAssistant(
        RuleBasedLanguageModel(["Sekuru"]), registry, data_source="fixture"
    )
    answer = assistant.handle(AskRequest(question="Tell me about Sekuru"))
    assert "Sekuru" in answer.answer
    assert not answer.degraded
    assert [t.name for t in answer.tool_trace] == [
        "resolve_place",
        "land_cover",
        "nearby_facilities",
    ]


def test_assistant_mentions_the_nearest_hospital(registry):
    assistant = AskAssistant(RuleBasedLanguageModel(["Sekuru"]), registry)
    answer = assistant.handle(
        AskRequest(question="Tell me about Sekuru and the nearest hospital")
    )
    assert "hospital" in answer.answer.lower()


def test_assistant_asks_for_clarification_when_no_place(registry):
    assistant = AskAssistant(RuleBasedLanguageModel(["Sekuru"]), registry)
    answer = assistant.handle(AskRequest(question="what is this"))
    assert "village" in answer.answer.lower() or "place" in answer.answer.lower()


def test_assistant_rejects_an_empty_question(registry):
    with pytest.raises(ValueError):
        AskAssistant(RuleBasedLanguageModel(), registry).handle(AskRequest(question="  "))


def test_assistant_stops_when_the_model_returns_prose(registry):
    class Immediate:
        def respond(self, messages, tools):
            return ModelTurn(content="Hello there.")

    answer = AskAssistant(Immediate(), registry).handle(AskRequest(question="hi"))
    assert answer.answer == "Hello there."
    assert answer.tool_trace == ()
    assert answer.degraded is True


def test_assistant_respects_the_step_budget(registry):
    class Loop:
        def __init__(self):
            self.calls = 0

        def respond(self, messages, tools):
            self.calls += 1
            if tools:
                return ModelTurn(
                    tool_calls=(ToolCall(name="resolve_place", arguments={"place": "Sekuru"}, call_id="c"),)
                )
            return ModelTurn(content="Wrapped up.")

    loop = Loop()
    answer = AskAssistant(loop, registry).handle(AskRequest(question="x", max_steps=2))
    assert answer.answer == "Wrapped up."
    assert answer.degraded is True
    assert any("budget" in note for note in answer.notes)


def test_assistant_continues_after_a_failed_tool(registry):
    assistant = AskAssistant(RuleBasedLanguageModel(["Sekuru"]), registry)
    answer = assistant.handle(AskRequest(question="Tell me about Atlantis"))
    assert answer.answer  # still produced something
    assert answer.tool_trace[0].ok is False


def test_assistant_passes_tool_results_back_as_observations(registry):
    seen: list[list[Message]] = []

    class Recorder:
        def __init__(self):
            self.step = 0

        def respond(self, messages, tools):
            seen.append(list(messages))
            self.step += 1
            if self.step == 1:
                return ModelTurn(
                    tool_calls=(ToolCall(name="resolve_place", arguments={"place": "Sekuru"}, call_id="c1"),)
                )
            return ModelTurn(content="done")

    AskAssistant(Recorder(), registry).handle(AskRequest(question="x"))
    final = seen[-1]
    assert any(m.role is Role.TOOL for m in final)
    tool_message = next(m for m in final if m.role is Role.TOOL)
    assert tool_message.tool_call_id == "c1"
    assert "Sekuru" in tool_message.content


def test_tool_outcome_serialises_to_json_content():
    outcome = ToolOutcome(name="t", ok=True, summary="s", payload={"a": 1})
    import json

    assert json.loads(outcome.as_tool_content())["data"] == {"a": 1}
