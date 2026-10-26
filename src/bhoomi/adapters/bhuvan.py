"""Bhuvan (ISRO / NRSC) adapters.

Four small classes, each implementing exactly one port, all sharing one HTTP
client and one access token. Splitting them this way means a caller that only
needs routing never has to depend on land-cover code (Interface Segregation),
and a change to the LULC wire format cannot break geocoding (Single
Responsibility).

Endpoint contracts follow the Bhuvan API documentation at
https://bhuvan-app1.nrsc.gov.in/api/ . Response field names differ slightly
between endpoints and have drifted over time, so the mappers below accept a set
of known aliases and fail loudly rather than guessing.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from bhoomi.adapters.http import HttpJsonClient
from bhoomi.domain.errors import PlaceNotFoundError, UpstreamUnavailableError
from bhoomi.domain.lulc import label_for
from bhoomi.domain.models import (
    Coordinates,
    Facility,
    FacilityKind,
    LandCoverClass,
    LandCoverProfile,
    Route,
    Village,
)

_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


def _first(record: Mapping[str, Any], *keys: str) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        if key in record:
            value = record[key]
            if value not in (None, "", "None", "null"):
                return value
    return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return None if number is None else int(round(number))


def _records(payload: Any) -> list[Mapping[str, Any]]:
    """Normalise the several list-shaped responses Bhuvan can return."""
    if payload is None or payload is False:
        return []
    if isinstance(payload, Mapping):
        for key in ("data", "results", "features", "records", "output"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [r for r in nested if isinstance(r, Mapping)]
        return [payload]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, Mapping)]
    return []


def circle_wkt(point: Coordinates, radius_m: int, segments: int = 16) -> str:
    """Approximate a circle as a closed WKT polygon.

    Good enough for statistics over a few kilometres; not a geodesic buffer.
    """
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    lat_delta = radius_m / 111_320.0
    cos_lat = max(0.01, math.cos(math.radians(point.lat)))
    lon_delta = radius_m / (111_320.0 * cos_lat)

    points = []
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        points.append(
            (point.lon + lon_delta * math.cos(angle), point.lat + lat_delta * math.sin(angle))
        )
    points.append(points[0])
    body = ", ".join(f"{lon:.6f} {lat:.6f}" for lon, lat in points)
    return f"POLYGON(({body}))"


class BhuvanPlaceResolver:
    """Implements ``PlaceResolver`` over the village geocoding services."""

    _NAME_KEYS = ("name1", "village", "name", "villagename", "village_name", "VILL_NAME")
    _DISTRICT_KEYS = ("dhq_name", "district", "dist_name", "district_name")
    _SUBDISTRICT_KEYS = ("thq_name", "sub_district", "subdistrict", "mandal", "tehsil")
    _STATE_KEYS = ("state", "state_name", "st_name", "stname")

    def __init__(self, client: HttpJsonClient, token: str) -> None:
        if not token:
            raise ValueError("Bhuvan access token is required")
        self._client = client
        self._token = token

    def resolve(self, place: str) -> Village:
        clean = (place or "").strip()
        if not clean:
            raise PlaceNotFoundError("no place name supplied")
        payload = self._client.get(
            "api_proximity/curl_village_geocode.php",
            params={"village": clean, "token": self._token},
            headers=_FORM_HEADERS,
        )
        records = _records(payload)
        if not records:
            raise PlaceNotFoundError(f"Bhuvan has no village named {clean!r}")
        return self._to_village(records[0], fallback_name=clean)

    def reverse(self, point: Coordinates) -> Village:
        payload = self._client.get(
            "api_proximity/curl_reverse_village.php",
            params={"lat": point.lat, "lon": point.lon, "token": self._token},
            headers=_FORM_HEADERS,
        )
        records = _records(payload)
        if not records:
            raise PlaceNotFoundError(
                f"no village at {point.lat}, {point.lon}"
            )
        village = self._to_village(records[0], fallback_name="Unknown village")
        if village.location is None:
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
        return village

    def _to_village(self, record: Mapping[str, Any], *, fallback_name: str) -> Village:
        name = _first(record, *self._NAME_KEYS) or fallback_name
        lat = _as_float(_first(record, "lat", "latitude", "y", "LATITUDE"))
        lon = _as_float(_first(record, "lon", "longitude", "x", "LONGITUDE"))
        location = (
            Coordinates(lat=lat, lon=lon) if lat is not None and lon is not None else None
        )
        return Village(
            name=str(name).strip().title(),
            state=_maybe_str(_first(record, *self._STATE_KEYS)),
            district=_maybe_str(_first(record, *self._DISTRICT_KEYS)),
            sub_district=_maybe_str(_first(record, *self._SUBDISTRICT_KEYS)),
            population=_as_int(_first(record, "tot_p", "population", "tot_pop", "total_population")),
            households=_as_int(_first(record, "no_hh", "households", "total_households")),
            location=location,
            village_id=_maybe_str(_first(record, "vid", "village_id", "code")),
        )


class BhuvanFacilityProvider:
    """Implements ``FacilityProvider`` over the proximity service."""

    _NAME_KEYS = ("name", "facility_name", "hospital_name", "po_name", "office_name")
    _ADDRESS_KEYS = ("address", "addr", "location_name", "village", "district")

    def __init__(self, client: HttpJsonClient, token: str) -> None:
        if not token:
            raise ValueError("Bhuvan access token is required")
        self._client = client
        self._token = token

    def nearby(
        self,
        point: Coordinates,
        *,
        radius_m: int,
        kind: FacilityKind | None = None,
    ) -> Sequence[Facility]:
        theme = "all" if kind is None else kind.value
        payload = self._client.get(
            "api_proximity/curl_hos_pos_prox.php",
            params={
                "theme": theme,
                "lat": point.lat,
                "lon": point.lon,
                "buffer": radius_m,
                "token": self._token,
            },
            headers=_FORM_HEADERS,
        )
        facilities: list[Facility] = []
        for record in _records(payload):
            raw_kind = _first(record, "theme", "type", "category", "facility_type")
            try:
                resolved_kind = (
                    FacilityKind.from_api(str(raw_kind)) if raw_kind else kind
                )
            except ValueError:
                resolved_kind = kind
            if resolved_kind is None:
                continue

            lat = _as_float(_first(record, "lat", "latitude", "y"))
            lon = _as_float(_first(record, "lon", "longitude", "x"))
            name = _first(record, *self._NAME_KEYS)
            facilities.append(
                Facility(
                    kind=resolved_kind,
                    name=str(name).strip() if name else f"Unnamed {resolved_kind.value}",
                    location=(
                        Coordinates(lat=lat, lon=lon)
                        if lat is not None and lon is not None
                        else None
                    ),
                    distance_m=_as_float(_first(record, "distance", "dist", "distance_m")),
                    address=_maybe_str(_first(record, *self._ADDRESS_KEYS)),
                )
            )
        return tuple(facilities)


class BhuvanRouteProvider:
    """Implements ``RouteProvider`` over the shortest-path service."""

    def __init__(self, client: HttpJsonClient, token: str) -> None:
        if not token:
            raise ValueError("Bhuvan access token is required")
        self._client = client
        self._token = token

    def route(self, origin: Coordinates, destination: Coordinates) -> Route:
        payload = self._client.get(
            "routing/curl_routing_state.php",
            params={
                "lat1": origin.lat,
                "lon1": origin.lon,
                "lat2": destination.lat,
                "lon2": destination.lon,
                "token": self._token,
            },
            headers=_FORM_HEADERS,
        )
        if payload in (None, False, [], {}):
            return Route()

        distance_km = None
        duration_min = None
        geometry: Any = None

        if isinstance(payload, Mapping):
            geometry = _extract_geometry(payload)
            distance_km = _as_float(_first(payload, "distance", "distance_km", "length"))
            duration_min = _as_float(_first(payload, "duration", "time", "duration_min"))

        if distance_km is None and isinstance(geometry, Mapping):
            distance_km = _geometry_length_km(geometry)

        return Route(
            distance_km=distance_km,
            duration_min=duration_min,
            geometry=geometry if isinstance(geometry, Mapping) else None,
        )


class BhuvanLulc50kProvider:
    """Implements ``LandCoverProvider`` over the 1:50,000 AOI statistics service."""

    def __init__(self, client: HttpJsonClient, token: str) -> None:
        if not token:
            raise ValueError("Bhuvan access token is required")
        self._client = client
        self._token = token

    def profile_for(
        self, point: Coordinates, *, radius_m: int, year: str | None = None
    ) -> LandCoverProfile:
        payload = self._client.get(
            "lulc/curl_aoi.php",
            params={"geom": circle_wkt(point, radius_m), "token": self._token},
            headers=_FORM_HEADERS,
        )
        return _profile_from_aoi(payload, year or "current")


class BhuvanLulc250kProvider:
    """Implements ``LandCoverProvider`` over the multi-year 1:250,000 service."""

    def __init__(self, client: HttpJsonClient, token: str) -> None:
        if not token:
            raise ValueError("Bhuvan access token is required")
        self._client = client
        self._token = token

    def profile_for(
        self, point: Coordinates, *, radius_m: int, year: str | None = None
    ) -> LandCoverProfile:
        payload = self._client.post(
            "lulc250k/curl_lulc250k.php",
            params={
                "polygon": circle_wkt(point, radius_m),
                "year": year or "all",
                "option": "json",
                "token": self._token,
            },
            headers=_FORM_HEADERS,
        )
        records = _records(payload)
        if not records:
            raise UpstreamUnavailableError("LULC 250k service returned no records")
        return _profile_from_year_records(records, year)


# -- parsing helpers ------------------------------------------------------


def _profile_from_aoi(payload: Any, year: str) -> LandCoverProfile:
    """Parse the ``curl_aoi`` shape: either per-state code columns or records."""
    records = _records(payload)
    if not records:
        raise UpstreamUnavailableError("LULC AOI service returned no records")

    areas: dict[str, float] = {}
    for record in records:
        if _first(record, "LULC Description", "description", "class", "lulc") is not None:
            code = str(_first(record, "LULC Code", "code", "lulc_code") or "")
            label = str(_first(record, "LULC Description", "description", "class", "lulc"))
            area = _as_float(_first(record, "Area in Sq. Km", "area", "area_sq_km")) or 0.0
            areas[label_for(code, label)] = areas.get(label_for(code, label), 0.0) + area
        else:
            for key, value in record.items():
                if not str(key).lower().startswith("l") or key.lower() == "lulc":
                    continue
                area = _as_float(value)
                if area is None:
                    continue
                label = label_for(str(key))
                areas[label] = areas.get(label, 0.0) + area

    return _build_profile(year, areas)


def _profile_from_year_records(
    records: Iterable[Mapping[str, Any]], requested_year: str | None
) -> LandCoverProfile:
    by_year: dict[str, dict[str, float]] = {}
    for record in records:
        year = str(_first(record, "Year", "year") or requested_year or "unknown")
        code = str(_first(record, "LULC Code", "code", "lulc_code") or "")
        raw_label = _first(record, "LULC Description", "description", "class")
        label = label_for(code, None if raw_label is None else str(raw_label))
        area = _as_float(_first(record, "Area in Sq. Km", "area", "area_sq_km")) or 0.0
        bucket = by_year.setdefault(year, {})
        bucket[label] = bucket.get(label, 0.0) + area

    if not by_year:
        raise UpstreamUnavailableError("LULC 250k service returned no usable records")

    chosen = (
        requested_year
        if requested_year and requested_year in by_year
        else sorted(by_year)[-1]
    )
    return _build_profile(chosen, by_year[chosen])


def _build_profile(year: str, areas: Mapping[str, float]) -> LandCoverProfile:
    total = sum(areas.values())
    if total <= 0:
        raise UpstreamUnavailableError(
            "LULC service returned no usable class areas; this usually means the "
            "area is outside its coverage or the request was rejected"
        )
    classes = tuple(
        LandCoverClass(
            code=_code_for_label(label),
            label=label,
            area_sq_km=area,
            share_pct=(100.0 * area / total) if total > 0 else None,
        )
        for label, area in sorted(areas.items(), key=lambda kv: kv[1], reverse=True)
        if area > 0
    )
    return LandCoverProfile(year=year, classes=classes, total_area_sq_km=total)


def _code_for_label(label: str) -> str:
    from bhoomi.domain.lulc import code_for_label

    return code_for_label(label) or label


def _extract_geometry(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Pull a geometry out of the several shapes the routing service returns.

    The service has been observed returning a bare ``LineString``, a single
    ``Feature``, and a ``FeatureCollection``. All three collapse to a geometry.
    """
    kind = payload.get("type")

    if kind in {"LineString", "MultiLineString"}:
        return payload

    if kind == "Feature":
        inner = payload.get("geometry")
        return inner if isinstance(inner, Mapping) else None

    if kind == "FeatureCollection":
        for feature in payload.get("features") or []:
            if isinstance(feature, Mapping):
                inner = feature.get("geometry")
                if isinstance(inner, Mapping):
                    return inner
        return None

    inner = payload.get("geometry")
    return inner if isinstance(inner, Mapping) else None


def _maybe_str(value: Any) -> str | None:
    if value in (None, "", "None", "null"):
        return None
    return str(value).strip().title()


def _geometry_length_km(geometry: Mapping[str, Any]) -> float | None:
    """Sum haversine lengths over a GeoJSON LineString/MultiLineString."""
    coords: list[list[tuple[float, float]]] = []
    if geometry.get("type") == "LineString":
        coords = [[(float(x), float(y)) for x, y, *_ in geometry.get("coordinates", [])]]
    elif geometry.get("type") == "MultiLineString":
        coords = [
            [(float(x), float(y)) for x, y, *_ in line]
            for line in geometry.get("coordinates", [])
        ]
    else:
        return None

    total = 0.0
    for line in coords:
        for (lon1, lat1), (lon2, lat2) in zip(line, line[1:], strict=False):
            total += _haversine_km(lat1, lon1, lat2, lon2)
    return total or None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))
