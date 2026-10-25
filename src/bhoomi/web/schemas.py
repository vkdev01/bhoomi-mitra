"""HTTP request/response models.

Pydantic lives only here. The domain and application layers stay framework-free,
and the wire format can change without touching business logic.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class PointIn(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude (WGS84)")
    lon: float = Field(..., ge=-180, le=180, description="Longitude (WGS84)")


class ReportIn(BaseModel):
    place: str | None = Field(
        default=None, description="Village or town name, e.g. 'Sekuru'"
    )
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int = Field(default=5000, gt=0, le=50_000)
    year: str | None = Field(default=None, description="LULC year, e.g. '2015_16'")
    include_routes: bool = True

    @model_validator(mode="after")
    def _need_a_location(self) -> ReportIn:
        if not self.place and (self.lat is None or self.lon is None):
            raise ValueError("provide either 'place' or both 'lat' and 'lon'")
        return self


class LandCoverClassOut(BaseModel):
    code: str
    label: str
    area_sq_km: float
    share_pct: float | None = None


class LandCoverOut(BaseModel):
    year: str
    total_area_sq_km: float
    classes: list[LandCoverClassOut]


class FacilityOut(BaseModel):
    kind: str
    name: str
    location: dict[str, float] | None = None
    distance_m: float | None = None
    address: str | None = None


class RouteOut(BaseModel):
    distance_km: float | None = None
    duration_min: float | None = None
    destination_name: str | None = None
    geometry: dict[str, Any] | None = None


class VillageOut(BaseModel):
    name: str
    state: str | None = None
    district: str | None = None
    sub_district: str | None = None
    population: int | None = None
    households: int | None = None
    location: dict[str, float] | None = None
    village_id: str | None = None


class ReportOut(BaseModel):
    village: VillageOut
    land_cover: LandCoverOut | None = None
    facilities: list[FacilityOut] = []
    routes: list[RouteOut] = []
    radius_m: int
    notes: list[str] = []
    data_source: str


class AskIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    language_code: str = Field(default="en-IN", max_length=10)
    place: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class ToolTraceOut(BaseModel):
    name: str
    ok: bool
    summary: str


class AskOut(BaseModel):
    answer: str
    language_code: str
    tool_trace: list[ToolTraceOut] = []
    data_source: str
    degraded: bool = False
    notes: list[str] = []


class VoiceOut(AskOut):
    transcript: str = ""
    audio_base64: str | None = None
    audio_mime: str | None = None


class ConfigOut(BaseModel):
    geo_source: str
    llm_source: str
    speech_available: bool
    lulc_scale: str
    data_mode: str
    chat_model: str
    default_language: str
    default_radius_m: int
    languages: list[str]
    sample_places: list[str] = []


class HealthOut(BaseModel):
    status: str
    data_source: str
