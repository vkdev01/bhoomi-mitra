"""Composition root.

The only module that knows which concrete adapter is in play. Everything else
receives ports. Swapping fixtures for live Bhuvan, or the rule-based planner for
Sarvam-105B, happens here and nowhere else.

Order of decisions:
    geo   -> live Bhuvan if a token is configured, else fixtures
    llm   -> Sarvam chat if a key is configured, else the rule-based planner
    speech-> Sarvam speech if a key is configured, else unavailable (the UI
             hides the microphone)
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from bhoomi.adapters.bhuvan import (
    BhuvanFacilityProvider,
    BhuvanLulc50kProvider,
    BhuvanLulc250kProvider,
    BhuvanPlaceResolver,
    BhuvanRouteProvider,
)
from bhoomi.adapters.fixtures import FixtureGeoProvider
from bhoomi.adapters.http import HttpJsonClient
from bhoomi.adapters.offline_llm import RuleBasedLanguageModel
from bhoomi.adapters.sarvam import (
    SarvamLanguageModel,
    SarvamSynthesizer,
    SarvamTranscriber,
    SarvamTranslator,
)
from bhoomi.application.assistant import AskAssistant
from bhoomi.application.tools import build_tool_registry
from bhoomi.application.village_report import BuildVillageReport
from bhoomi.config import Settings
from bhoomi.domain.ports import (
    FacilityProvider,
    LandCoverProvider,
    PlaceResolver,
    RouteProvider,
    SpeechSynthesizer,
    SpeechTranscriber,
    Translator,
)


@dataclass(slots=True)
class Container:
    """Everything the web layer needs, already wired."""

    settings: Settings
    places: PlaceResolver
    land_cover: LandCoverProvider
    facilities: FacilityProvider
    routes: RouteProvider | None
    report: BuildVillageReport
    assistant: AskAssistant
    transcriber: SpeechTranscriber | None = None
    synthesizer: SpeechSynthesizer | None = None
    translator: Translator | None = None
    data_source: str = "unknown"
    _closers: list = field(default_factory=list)

    def close(self) -> None:
        for closer in self._closers:
            with contextlib.suppress(Exception):  # best-effort shutdown
                closer()
        self._closers.clear()


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings.from_env()
    closers: list = []

    # -- geo ------------------------------------------------------------
    # Bhuvan hands out one token per theme, so each capability is wired
    # independently. A capability without a token falls back to the fixture
    # provider rather than failing the whole request, and the data source is
    # reported as "mixed" so nobody mistakes sample figures for live ones.
    fixture = FixtureGeoProvider(settings.fixture_path)
    places: PlaceResolver = fixture
    land_cover: LandCoverProvider = fixture
    facilities: FacilityProvider = fixture
    routes: RouteProvider | None = fixture
    live: list[str] = []

    if settings.wants_live_geo:
        geo_client = HttpJsonClient(
            settings.bhuvan_base_url,
            timeout_s=settings.http_timeout_s,
            max_retries=settings.http_max_retries,
        )
        closers.append(geo_client.close)

        geocoding_token = settings.bhuvan_token_for("geocoding")
        if geocoding_token:
            places = BhuvanPlaceResolver(geo_client, geocoding_token)
            live.append("geocoding")

        proximity_token = settings.bhuvan_token_for("proximity")
        if proximity_token:
            facilities = BhuvanFacilityProvider(geo_client, proximity_token)
            live.append("proximity")

        routing_token = settings.bhuvan_token_for("routing")
        if routing_token:
            routes = BhuvanRouteProvider(geo_client, routing_token)
            live.append("routing")

        lulc_token = settings.bhuvan_token_for("lulc")
        if lulc_token:
            land_cover = (
                BhuvanLulc50kProvider(geo_client, lulc_token)
                if settings.lulc_scale == "50k"
                else BhuvanLulc250kProvider(geo_client, lulc_token)
            )
            live.append("lulc")

    data_source = (
        "bhuvan-live" if len(live) == 4 else "mixed" if live else "fixture"
    )

    # -- language model --------------------------------------------------
    if settings.wants_live_llm:
        llm_client = HttpJsonClient(
            settings.sarvam_base_url,
            timeout_s=settings.http_timeout_s,
            max_retries=settings.http_max_retries,
            default_headers={"api-subscription-key": settings.sarvam_api_key or ""},
        )
        closers.append(llm_client.close)
        llm = SarvamLanguageModel(llm_client, model=settings.chat_model)
    else:
        llm = RuleBasedLanguageModel(known_places=_fixture_place_names(settings))

    # -- speech ----------------------------------------------------------
    transcriber: SpeechTranscriber | None = None
    synthesizer: SpeechSynthesizer | None = None
    translator: Translator | None = None
    if settings.wants_live_speech:
        speech_client = HttpJsonClient(
            settings.sarvam_base_url,
            timeout_s=settings.http_timeout_s,
            max_retries=settings.http_max_retries,
            default_headers={"api-subscription-key": settings.sarvam_api_key or ""},
        )
        closers.append(speech_client.close)
        transcriber = SarvamTranscriber(speech_client, model=settings.stt_model)
        synthesizer = SarvamSynthesizer(
            speech_client, model=settings.tts_model, speaker=settings.tts_speaker
        )
        translator = SarvamTranslator(speech_client, model=settings.translate_model)

    # -- use cases -------------------------------------------------------
    registry = build_tool_registry(places, land_cover, facilities, routes)
    report = BuildVillageReport(
        places, land_cover, facilities, routes, data_source=data_source
    )
    assistant = AskAssistant(llm, registry, data_source=data_source)

    return Container(
        settings=settings,
        places=places,
        land_cover=land_cover,
        facilities=facilities,
        routes=routes,
        report=report,
        assistant=assistant,
        transcriber=transcriber,
        synthesizer=synthesizer,
        translator=translator,
        data_source=data_source,
        _closers=closers,
    )


def _fixture_place_names(settings: Settings) -> list[str]:
    """Candidate place names for the offline planner's keyword matching."""
    try:
        import json

        raw = json.loads(settings.fixture_path.read_text(encoding="utf-8"))
        names: list[str] = []
        for record in raw.get("villages", []):
            names.append(str(record.get("name", "")))
            names.extend(str(a) for a in record.get("aliases", []))
        return [n for n in names if n]
    except Exception:  # noqa: BLE001 - fixtures are optional
        return []
