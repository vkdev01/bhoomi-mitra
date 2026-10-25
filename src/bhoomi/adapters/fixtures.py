"""In-memory fixture adapters.

These implement the same four spatial ports as the Bhuvan adapters, using
bundled sample data instead of the network. That gives us three things:

* the app is runnable and demonstrable without an ISRO access token;
* the use cases and the agent loop are testable deterministically;
* the same contract tests can run against both implementations, which is how we
  actually verify Liskov substitutability rather than just asserting it.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from bhoomi.domain.errors import PlaceNotFoundError
from bhoomi.domain.models import (
    Coordinates,
    Facility,
    FacilityKind,
    LandCoverClass,
    LandCoverProfile,
    Route,
    Village,
)

DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "fixtures" / "demo_geo.json"
)

# Straight-line distance understates road distance; this factor and the average
# speed are documented estimates, not measured values.
_DETOUR_FACTOR = 1.3
_AVERAGE_SPEED_KMPH = 30.0


def haversine_m(a: Coordinates, b: Coordinates) -> float:
    radius = 6_371_008.8
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    d_phi = phi2 - phi1
    d_lambda = math.radians(b.lon - a.lon)
    h = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(h))


class FixtureGeoProvider:
    """A ``PlaceResolver`` + ``LandCoverProvider`` + ``FacilityProvider`` +
    ``RouteProvider`` backed by a JSON file."""

    data_source = "fixture"

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else DEFAULT_FIXTURE_PATH
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        self._villages: list[Mapping[str, Any]] = list(raw.get("villages", []))
        self._land_cover: Mapping[str, Any] = raw.get("land_cover", {})
        self._facilities: Mapping[str, Any] = raw.get("facilities", {})

    # -- PlaceResolver ----------------------------------------------------

    def resolve(self, place: str) -> Village:
        needle = (place or "").strip().lower()
        if not needle:
            raise PlaceNotFoundError("no place name supplied")

        for record in self._villages:
            names = {str(record.get("name", "")).lower()}
            names.update(str(a).lower() for a in record.get("aliases", []))
            if needle in names:
                return self._to_village(record)

        for record in self._villages:
            if needle in str(record.get("name", "")).lower():
                return self._to_village(record)

        raise PlaceNotFoundError(
            f"No sample village matches {place!r}. "
            f"Try one of: {', '.join(str(v['name']) for v in self._villages)}"
        )

    def reverse(self, point: Coordinates) -> Village:
        best: tuple[float, Mapping[str, Any]] | None = None
        for record in self._villages:
            centre = self._village_point(record)
            if centre is None:
                continue
            distance = haversine_m(point, centre)
            if best is None or distance < best[0]:
                best = (distance, record)
        if best is None:
            raise PlaceNotFoundError("no fixture villages with coordinates")
        village = self._to_village(best[1])
        return Village(
            name=village.name,
            state=village.state,
            district=village.district,
            sub_district=village.sub_district,
            population=village.population,
            households=village.households,
            location=point,
            village_id=village.village_id,
        )

    # -- LandCoverProvider ------------------------------------------------

    def profile_for(
        self, point: Coordinates, *, radius_m: int, year: str | None = None
    ) -> LandCoverProfile:
        village = self.reverse(point)
        block = self._land_cover.get(village.name) or {}
        classes = block.get("classes", [])
        if not classes:
            raise PlaceNotFoundError(
                f"No sample land-cover data for {village.name}"
            )

        scale = (radius_m / 5000.0) ** 2
        built = tuple(
            LandCoverClass(
                code=str(entry.get("code", "")),
                label=str(entry.get("label", "")),
                area_sq_km=float(entry.get("area_sq_km", 0.0)) * scale,
            )
            for entry in classes
        )
        total = sum(c.area_sq_km for c in built)
        return LandCoverProfile(
            year=str(block.get("year", year or "unknown")),
            classes=tuple(
                LandCoverClass(
                    code=c.code,
                    label=c.label,
                    area_sq_km=c.area_sq_km,
                    share_pct=(100.0 * c.area_sq_km / total) if total else None,
                )
                for c in built
            ),
            total_area_sq_km=total,
        )

    # -- FacilityProvider -------------------------------------------------

    def nearby(
        self,
        point: Coordinates,
        *,
        radius_m: int,
        kind: FacilityKind | None = None,
    ) -> Sequence[Facility]:
        village = self.reverse(point)
        entries = self._facilities.get(village.name, [])
        results: list[Facility] = []
        for entry in entries:
            entry_kind = FacilityKind.from_api(str(entry.get("kind", "")))
            if kind is not None and entry_kind is not kind:
                continue
            location = Coordinates(
                lat=float(entry["lat"]), lon=float(entry["lon"])
            )
            distance = haversine_m(point, location)
            if distance > radius_m:
                continue
            results.append(
                Facility(
                    kind=entry_kind,
                    name=str(entry.get("name", "")),
                    location=location,
                    distance_m=distance,
                    address=entry.get("address"),
                )
            )
        results.sort(key=lambda f: f.distance_m or float("inf"))
        return tuple(results)

    # -- RouteProvider ----------------------------------------------------

    def route(self, origin: Coordinates, destination: Coordinates) -> Route:
        straight_km = haversine_m(origin, destination) / 1000.0
        if straight_km <= 0:
            return Route(distance_km=0.0, duration_min=0.0)
        distance_km = straight_km * _DETOUR_FACTOR
        return Route(
            distance_km=distance_km,
            duration_min=distance_km / _AVERAGE_SPEED_KMPH * 60.0,
            geometry={
                "type": "LineString",
                "coordinates": [
                    [origin.lon, origin.lat],
                    [destination.lon, destination.lat],
                ],
            },
        )

    # -- internals --------------------------------------------------------

    @staticmethod
    def _village_point(record: Mapping[str, Any]) -> Coordinates | None:
        lat, lon = record.get("lat"), record.get("lon")
        if lat is None or lon is None:
            return None
        return Coordinates(lat=float(lat), lon=float(lon))

    def _to_village(self, record: Mapping[str, Any]) -> Village:
        return Village(
            name=str(record.get("name", "")),
            state=record.get("state"),
            district=record.get("district"),
            sub_district=record.get("sub_district"),
            population=record.get("population"),
            households=record.get("households"),
            location=self._village_point(record),
            village_id=record.get("village_id"),
        )
