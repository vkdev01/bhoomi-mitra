"""HTTP routes.

Thin by design: parse the request, call one use case, map the result. All error
translation happens in the exception handlers registered by ``create_app``.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from bhoomi.application.assistant import AskRequest
from bhoomi.application.village_report import ReportRequest
from bhoomi.composition import Container
from bhoomi.domain.errors import PlaceNotFoundError, UpstreamUnavailableError
from bhoomi.domain.map_layers import (
    default_overlay_id,
    lulc_overlays,
    raster_bases,
)
from bhoomi.domain.models import Coordinates
from bhoomi.web.presenters import report_to_out
from bhoomi.web.schemas import (
    AskIn,
    AskOut,
    ConfigOut,
    HealthOut,
    MapLayersOut,
    RasterBaseOut,
    ReportIn,
    ReportOut,
    ToolTraceOut,
    VoiceOut,
    WmsOverlayOut,
)

router = APIRouter()

LANGUAGES = [
    "en-IN", "hi-IN", "bn-IN", "ta-IN", "te-IN", "mr-IN", "gu-IN",
    "kn-IN", "ml-IN", "pa-IN", "or-IN", "as-IN", "ur-IN",
]


def _container(request: Request) -> Container:
    return request.app.state.container


@router.get("/health", response_model=HealthOut, tags=["ops"])
def health(request: Request) -> HealthOut:
    return HealthOut(status="ok", data_source=_container(request).data_source)


@router.get("/api/config", response_model=ConfigOut, tags=["meta"])
def config(request: Request) -> ConfigOut:
    container = _container(request)
    summary = container.settings.public_summary()
    return ConfigOut(
        **summary,
        languages=LANGUAGES,
        sample_places=_sample_places(container),
    )


@router.get("/api/map/layers", response_model=MapLayersOut, tags=["map"])
def map_layers(request: Request) -> MapLayersOut:
    """The base maps and ISRO thematic overlays the interface can draw."""
    settings = _container(request).settings
    overlays = lulc_overlays(settings.bhuvan_wms_url)
    bases = raster_bases(settings.satellite_tile_url)
    return MapLayersOut(
        base_layers=[RasterBaseOut(**b.as_dict()) for b in bases],
        overlays=[WmsOverlayOut(**o.as_dict()) for o in overlays],
        default_overlay_id=default_overlay_id(overlays),
    )


@router.post("/api/village/report", response_model=ReportOut, tags=["village"])
def village_report(payload: ReportIn, request: Request) -> ReportOut:
    container = _container(request)
    point = (
        Coordinates(lat=payload.lat, lon=payload.lon)
        if payload.lat is not None and payload.lon is not None
        else None
    )
    result = container.report.execute(
        ReportRequest(
            place=payload.place,
            point=point,
            radius_m=payload.radius_m,
            year=payload.year,
            include_routes=payload.include_routes,
        )
    )
    return report_to_out(result)


@router.post("/api/assistant/ask", response_model=AskOut, tags=["assistant"])
def assistant_ask(payload: AskIn, request: Request) -> AskOut:
    container = _container(request)
    answer = container.assistant.handle(
        AskRequest(
            question=_with_location(payload.question, payload.place, payload.lat, payload.lon),
            language_code=payload.language_code,
            max_steps=container.settings.max_agent_steps,
        )
    )
    return AskOut(
        answer=answer.answer,
        language_code=answer.language_code,
        tool_trace=[
            ToolTraceOut(name=t.name, ok=t.ok, summary=t.summary) for t in answer.tool_trace
        ],
        data_source=answer.data_source,
        degraded=answer.degraded,
        notes=list(answer.notes),
    )


@router.post("/api/assistant/voice", response_model=VoiceOut, tags=["assistant"])
async def assistant_voice(
    request: Request,
    audio: UploadFile = File(...),  # noqa: B008 - FastAPI dependency idiom
    language_code: str = Form("en-IN"),
    place: str | None = Form(None),
) -> VoiceOut:
    container = _container(request)
    if container.transcriber is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Speech is unavailable because SARVAM_API_KEY is not configured. "
                "Use /api/assistant/ask instead."
            ),
        )

    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio upload")
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="audio exceeds 10 MB")

    transcript = container.transcriber.transcribe(
        raw,
        filename=audio.filename or "recording.wav",
        language_code=language_code,
    )
    question = _with_location(transcript, place, None, None)

    answer = container.assistant.handle(
        AskRequest(
            question=question,
            language_code=language_code,
            max_steps=container.settings.max_agent_steps,
        )
    )

    audio_b64 = None
    audio_mime = None
    if container.synthesizer is not None and answer.answer:
        try:
            spoken = container.synthesizer.synthesize(
                answer.answer, language_code=language_code
            )
            audio_b64 = base64.b64encode(spoken).decode("ascii")
            audio_mime = "audio/mpeg"
        except UpstreamUnavailableError:
            audio_b64 = None

    return VoiceOut(
        answer=answer.answer,
        language_code=answer.language_code,
        tool_trace=[
            ToolTraceOut(name=t.name, ok=t.ok, summary=t.summary) for t in answer.tool_trace
        ],
        data_source=answer.data_source,
        degraded=answer.degraded,
        notes=list(answer.notes),
        transcript=transcript,
        audio_base64=audio_b64,
        audio_mime=audio_mime,
    )


# -- helpers --------------------------------------------------------------


def _with_location(
    question: str, place: str | None, lat: float | None, lon: float | None
) -> str:
    hints = []
    if place:
        hints.append(f"Place: {place}.")
    if lat is not None and lon is not None:
        hints.append(f"Coordinates: {lat}, {lon}.")
    return f"{question.strip()} {' '.join(hints)}".strip()


def _sample_places(container: Container) -> list[str]:
    try:
        import json

        raw = json.loads(container.settings.fixture_path.read_text(encoding="utf-8"))
        return [str(v.get("name", "")) for v in raw.get("villages", []) if v.get("name")]
    except Exception:  # noqa: BLE001
        return []


# Re-exported so the app factory can register handlers against the same types.
__all__ = ["router", "PlaceNotFoundError"]
