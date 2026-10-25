"""Domain entities and value objects.

Pure data. No I/O, no framework imports, no knowledge of Bhuvan or Sarvam.
Everything here is immutable (frozen dataclasses / enums) so that values can be
shared freely between layers without defensive copying.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FacilityKind(StrEnum):
    """The kinds of civic facility the Bhuvan proximity service can return."""

    HOSPITAL = "hospital"
    POST_OFFICE = "postal"

    @classmethod
    def from_api(cls, raw: str) -> FacilityKind:
        normalised = (raw or "").strip().lower()
        if normalised in {"hospital", "hospitals", "health"}:
            return cls.HOSPITAL
        if normalised in {"postal", "post", "postoffice", "post_office"}:
            return cls.POST_OFFICE
        raise ValueError(f"Unknown facility kind: {raw!r}")


@dataclass(frozen=True, slots=True)
class Coordinates:
    """A WGS84 point."""

    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.lat <= 90.0:
            raise ValueError(f"latitude out of range: {self.lat}")
        if not -180.0 <= self.lon <= 180.0:
            raise ValueError(f"longitude out of range: {self.lon}")

    def as_dict(self) -> dict[str, float]:
        return {"lat": self.lat, "lon": self.lon}


@dataclass(frozen=True, slots=True)
class Village:
    """A census village as resolved by the Bhuvan geocoding services."""

    name: str
    state: str | None = None
    district: str | None = None
    sub_district: str | None = None
    population: int | None = None
    households: int | None = None
    location: Coordinates | None = None
    village_id: str | None = None

    @property
    def label(self) -> str:
        parts = [self.name.title()]
        for part in (self.sub_district, self.district, self.state):
            if part:
                parts.append(part.title())
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class LandCoverClass:
    """One land-use/land-cover class and how much of the area it occupies."""

    code: str
    label: str
    area_sq_km: float
    share_pct: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "area_sq_km": round(self.area_sq_km, 4),
            "share_pct": None if self.share_pct is None else round(self.share_pct, 2),
        }


@dataclass(frozen=True, slots=True)
class LandCoverProfile:
    """Land-cover composition of a place for one reference year."""

    year: str
    classes: tuple[LandCoverClass, ...]
    total_area_sq_km: float

    def __post_init__(self) -> None:
        if self.total_area_sq_km < 0:
            raise ValueError("total_area_sq_km cannot be negative")

    def ranked(self) -> tuple[LandCoverClass, ...]:
        return tuple(sorted(self.classes, key=lambda c: c.area_sq_km, reverse=True))

    def dominant(self) -> LandCoverClass | None:
        ranked = self.ranked()
        return ranked[0] if ranked else None

    def share_of(self, label_fragment: str) -> float:
        """Combined share of every class whose label contains ``label_fragment``."""
        needle = label_fragment.strip().lower()
        if not needle:
            return 0.0
        total = sum(
            c.area_sq_km for c in self.classes if needle in c.label.lower()
        )
        if self.total_area_sq_km <= 0:
            return 0.0
        return round(100.0 * total / self.total_area_sq_km, 2)


@dataclass(frozen=True, slots=True)
class Facility:
    """A hospital or post office returned by the proximity service."""

    kind: FacilityKind
    name: str
    location: Coordinates | None = None
    distance_m: float | None = None
    address: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "name": self.name,
            "location": None if self.location is None else self.location.as_dict(),
            "distance_m": None if self.distance_m is None else round(self.distance_m, 1),
            "address": self.address,
        }


@dataclass(frozen=True, slots=True)
class Route:
    """A road route between two points, with GeoJSON geometry when available."""

    distance_km: float | None = None
    duration_min: float | None = None
    geometry: Mapping[str, Any] | None = None
    destination_name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "distance_km": None if self.distance_km is None else round(self.distance_km, 2),
            "duration_min": None if self.duration_min is None else round(self.duration_min, 1),
            "destination_name": self.destination_name,
            "geometry": self.geometry,
        }


@dataclass(frozen=True, slots=True)
class VillageReport:
    """Aggregate produced by the ``BuildVillageReport`` use case."""

    village: Village
    land_cover: LandCoverProfile | None = None
    facilities: tuple[Facility, ...] = ()
    routes: tuple[Route, ...] = ()
    radius_m: int = 5000
    notes: tuple[str, ...] = field(default_factory=tuple)
    data_source: str = "unknown"

    def facilities_of(self, kind: FacilityKind) -> tuple[Facility, ...]:
        return tuple(f for f in self.facilities if f.kind is kind)
