"""A deterministic, rule-based stand-in for the language model.

Why this exists: the agent loop, the tool registry and the whole application
should be exercisable without a Sarvam API key — in CI, in a demo, and on a
fresh clone. This class implements the same ``LanguageModel`` port and performs
a genuine multi-step tool plan, so it tests the *loop*, not a mock of it.

It is intentionally dumb: keyword matching, no comprehension. It is not a
substitute for Sarvam-105B and the UI says so.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from bhoomi.domain.messages import Message, ModelTurn, Role, ToolCall, ToolSpec

_PLACE_HINT = re.compile(
    r"\b(?:in|near|at|about|around|for)\s+([A-Z][A-Za-z]{2,})", re.UNICODE
)
_HOSPITAL_WORDS = ("hospital", "clinic", "doctor", "health", "medical", "dispensary")
_POST_WORDS = ("post office", "postal", "post-office", "dak")
_LAND_WORDS = ("land", "crop", "farm", "forest", "built", "agricultur", "cover", "use")
_ROUTE_WORDS = ("far", "distance", "how long", "route", "travel", "drive", "reach")


class RuleBasedLanguageModel:
    """Implements ``LanguageModel`` with keyword rules and no network access."""

    def __init__(self, known_places: Sequence[str] = ()) -> None:
        self._known = [p for p in known_places if p]

    # -- port -------------------------------------------------------------

    def respond(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> ModelTurn:
        available = {t.name for t in tools}
        question = _last_user_text(messages)
        observations = _observations(messages)

        if not observations:
            call = self._plan_first(question, available)
            if call is None:
                return ModelTurn(
                    content=(
                        "I could not work out which place you mean. Please name a "
                        "village or town, for example: \"Tell me about Sekuru\"."
                    )
                )
            return ModelTurn(tool_calls=(call,))

        if self._needs_spatial(question, observations, available):
            calls = self._plan_spatial(question, observations, available)
            if calls:
                return ModelTurn(tool_calls=tuple(calls))

        return ModelTurn(content=self._compose(question, observations))

    # -- planning ---------------------------------------------------------

    def _plan_first(self, question: str, available: set[str]) -> ToolCall | None:
        place = self._extract_place(question)
        if place and "resolve_place" in available:
            return ToolCall(
                name="resolve_place", arguments={"place": place}, call_id="call_1"
            )
        return None

    def _needs_spatial(
        self,
        question: str,
        observations: Mapping[str, Mapping[str, Any]],
        available: set[str],
    ) -> bool:
        if not _has_coordinates(observations):
            return False
        wants_land = any(w in question.lower() for w in _LAND_WORDS) or not observations.get(
            "nearby_facilities"
        )
        return ("land_cover" in available and "land_cover" not in observations) or (
            "nearby_facilities" in available and "nearby_facilities" not in observations
        ) or (wants_land and "land_cover" in available and "land_cover" not in observations)

    def _plan_spatial(
        self,
        question: str,
        observations: Mapping[str, Mapping[str, Any]],
        available: set[str],
    ) -> list[ToolCall]:
        coords = _has_coordinates(observations)
        if coords is None:
            return []
        lat, lon = coords
        calls: list[ToolCall] = []

        if "land_cover" in available and "land_cover" not in observations:
            calls.append(
                ToolCall(
                    name="land_cover",
                    arguments={"lat": lat, "lon": lon, "radius_m": 5000},
                    call_id="call_2",
                )
            )

        if "nearby_facilities" in available and "nearby_facilities" not in observations:
            lowered = question.lower()
            kind = None
            if any(w in lowered for w in _HOSPITAL_WORDS):
                kind = "hospital"
            elif any(w in lowered for w in _POST_WORDS):
                kind = "postal"
            args: dict[str, Any] = {"lat": lat, "lon": lon, "radius_m": 10000}
            if kind:
                args["kind"] = kind
            calls.append(
                ToolCall(name="nearby_facilities", arguments=args, call_id="call_3")
            )
        return calls

    def _extract_place(self, question: str) -> str | None:
        lowered = question.lower()
        for place in self._known:
            if place.lower() in lowered:
                return place
        match = _PLACE_HINT.search(question)
        if match:
            return match.group(1)
        # Fall back to any capitalised token that is not sentence-initial filler.
        for token in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", question):
            if token.lower() not in {"tell", "what", "which", "how", "the", "please"}:
                return token
        return None

    # -- composing --------------------------------------------------------

    def _compose(
        self, question: str, observations: Mapping[str, Mapping[str, Any]]
    ) -> str:
        parts: list[str] = []

        resolved = observations.get("resolve_place")
        if resolved and resolved.get("ok"):
            data = resolved.get("data") or {}
            label = ", ".join(
                str(v)
                for v in (
                    data.get("name"),
                    data.get("district"),
                    data.get("state"),
                )
                if v
            )
            line = f"{label}."
            if data.get("population"):
                line += f" Population {data['population']:,}."
            parts.append(line)

        land = observations.get("land_cover")
        if land and land.get("ok"):
            data = land.get("data") or {}
            classes = data.get("classes") or []
            if classes:
                top = classes[:3]
                described = ", ".join(
                    f"{c['label']} {c['share_pct']:.0f}%"
                    if c.get("share_pct") is not None
                    else f"{c['label']} {c['area_sq_km']:.1f} sq km"
                    for c in top
                )
                parts.append(
                    f"Land cover around it ({data.get('year', 'latest')}) is mainly "
                    f"{described}."
                )

        fac = observations.get("nearby_facilities")
        if fac and fac.get("ok"):
            data = fac.get("data") or {}
            facilities = data.get("facilities") or []
            hospitals = [f for f in facilities if f.get("kind") == "hospital"]
            posts = [f for f in facilities if f.get("kind") == "postal"]
            if hospitals:
                nearest = hospitals[0]
                line = f"Nearest hospital: {nearest['name']}"
                if nearest.get("distance_m") is not None:
                    line += f", about {nearest['distance_m'] / 1000:.1f} km away"
                parts.append(line + ".")
            if posts:
                nearest_post = posts[0]
                line = f"Nearest post office: {nearest_post['name']}"
                if nearest_post.get("distance_m") is not None:
                    line += f", about {nearest_post['distance_m'] / 1000:.1f} km away"
                parts.append(line + ".")
            if not hospitals and not posts:
                parts.append("I found no hospital or post office in that radius.")

        failed = [k for k, v in observations.items() if not v.get("ok")]
        if failed and not parts:
            return (
                "I could not fetch the data for that place right now "
                f"({', '.join(failed)}). Please try again in a moment."
            )

        if not parts:
            return "I did not find any data for that place."

        return " ".join(parts) + " (Source: ISRO Bhuvan.)"


# -- helpers --------------------------------------------------------------


def _last_user_text(messages: Sequence[Message]) -> str:
    for message in reversed(messages):
        if message.role is Role.USER:
            return message.content
    return ""


def _observations(messages: Sequence[Message]) -> dict[str, dict[str, Any]]:
    """Collect tool results keyed by tool name, latest wins."""
    by_call_id: dict[str, str] = {}
    for message in messages:
        for call in message.tool_calls:
            by_call_id[call.call_id or call.name] = call.name

    collected: dict[str, dict[str, Any]] = {}
    for message in messages:
        if message.role is not Role.TOOL:
            continue
        try:
            payload = json.loads(message.content)
        except (json.JSONDecodeError, TypeError):
            continue
        name = by_call_id.get(message.tool_call_id or "", "")
        if name:
            collected[name] = payload
    return collected


def _has_coordinates(
    observations: Mapping[str, Mapping[str, Any]]
) -> tuple[float, float] | None:
    resolved = observations.get("resolve_place")
    if not resolved:
        return None
    location = (resolved.get("data") or {}).get("location")
    if not location:
        return None
    try:
        return float(location["lat"]), float(location["lon"])
    except (KeyError, TypeError, ValueError):
        return None
