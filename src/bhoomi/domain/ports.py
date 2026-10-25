"""Ports: the interfaces the application layer depends on.

These are ``typing.Protocol`` definitions, so implementations need not import
them (structural typing). That keeps the dependency arrow pointing inwards:
adapters know about ports, ports know nothing about adapters.

The interfaces are deliberately small and single-purpose (Interface
Segregation Principle). A test double only has to implement the one capability
under test, and a new data source can implement just ``LandCoverProvider``
without pretending to be a routing engine.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from bhoomi.domain.models import (
    Coordinates,
    Facility,
    FacilityKind,
    LandCoverProfile,
    Route,
    Village,
)


@runtime_checkable
class PlaceResolver(Protocol):
    """Turns a human place reference into a known village."""

    def resolve(self, place: str) -> Village:
        """Resolve a free-text place name. Raises ``PlaceNotFoundError``."""
        ...

    def reverse(self, point: Coordinates) -> Village:
        """Resolve coordinates to the containing village. Raises ``PlaceNotFoundError``."""
        ...


@runtime_checkable
class LandCoverProvider(Protocol):
    """Supplies land-use/land-cover statistics for an area."""

    def profile_for(
        self,
        point: Coordinates,
        *,
        radius_m: int,
        year: str | None = None,
    ) -> LandCoverProfile:
        ...


@runtime_checkable
class FacilityProvider(Protocol):
    """Finds civic facilities near a point."""

    def nearby(
        self,
        point: Coordinates,
        *,
        radius_m: int,
        kind: FacilityKind | None = None,
    ) -> Sequence[Facility]:
        ...


@runtime_checkable
class RouteProvider(Protocol):
    """Computes a road route between two points."""

    def route(self, origin: Coordinates, destination: Coordinates) -> Route:
        ...


@runtime_checkable
class LanguageModel(Protocol):
    """A tool-calling chat model.

    ``respond`` must be pure with respect to conversation state: the caller owns
    the transcript and passes it in every turn. That makes the agent loop
    replayable and trivially testable.
    """

    def respond(
        self,
        messages: Sequence[Any],
        tools: Sequence[Any],
    ) -> Any:
        ...


@runtime_checkable
class SpeechTranscriber(Protocol):
    """Speech to text."""

    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        language_code: str | None = None,
    ) -> str:
        ...


@runtime_checkable
class SpeechSynthesizer(Protocol):
    """Text to speech."""

    def synthesize(self, text: str, *, language_code: str) -> bytes:
        ...


@runtime_checkable
class Translator(Protocol):
    """Text translation between Indian languages and English."""

    def translate(
        self,
        text: str,
        *,
        source_language_code: str,
        target_language_code: str,
    ) -> str:
        ...
