"""Tool definitions exposed to the language model.

Each tool is a thin adapter over one or more ports. Handlers contain no business
rules beyond marshalling arguments and summarising a result, which keeps them
easy to reason about and easy to test one at a time.

``build_tool_registry`` is the single place that knows the full tool surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bhoomi.application.tool_registry import ToolRegistry
from bhoomi.domain.errors import ToolInvocationError
from bhoomi.domain.lulc import label_for
from bhoomi.domain.messages import ToolOutcome, ToolSpec
from bhoomi.domain.models import Coordinates, FacilityKind
from bhoomi.domain.ports import (
    FacilityProvider,
    LandCoverProvider,
    PlaceResolver,
    RouteProvider,
)

_POINT_SCHEMA = {
    "lat": {"type": "number", "description": "Latitude in decimal degrees"},
    "lon": {"type": "number", "description": "Longitude in decimal degrees"},
}


def _require(args: Mapping[str, Any], *names: str) -> None:
    missing = [n for n in names if args.get(n) in (None, "")]
    if missing:
        raise ToolInvocationError(
            f"missing required argument(s): {', '.join(missing)}"
        )


def _point(args: Mapping[str, Any], lat_key: str = "lat", lon_key: str = "lon") -> Coordinates:
    _require(args, lat_key, lon_key)
    try:
        return Coordinates(lat=float(args[lat_key]), lon=float(args[lon_key]))
    except (TypeError, ValueError) as exc:
        raise ToolInvocationError(f"invalid coordinates: {exc}") from exc


def build_tool_registry(
    places: PlaceResolver,
    land_cover: LandCoverProvider,
    facilities: FacilityProvider,
    routes: RouteProvider | None,
) -> ToolRegistry:
    registry = ToolRegistry()

    # -- resolve_place ----------------------------------------------------
    def resolve_place(args: Mapping[str, Any]) -> ToolOutcome:
        _require(args, "place")
        village = places.resolve(str(args["place"]))
        payload = {
            "name": village.name,
            "district": village.district,
            "state": village.state,
            "population": village.population,
            "households": village.households,
            "location": None if village.location is None else village.location.as_dict(),
        }
        summary = f"Resolved {village.label}"
        if village.population is not None:
            summary += f" (population {village.population:,})"
        if village.location is None:
            summary += "; no coordinates published"
        return ToolOutcome(
            name="resolve_place", ok=True, summary=summary, payload=payload
        )

    registry.register(
        ToolSpec(
            name="resolve_place",
            description=(
                "Resolve an Indian village or town name to its census details and "
                "coordinates. Call this before any spatial lookup."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "place": {
                        "type": "string",
                        "description": "Village or town name, e.g. 'Sekuru' or 'Warangal'",
                    }
                },
                "required": ["place"],
            },
        ),
        resolve_place,
    )

    # -- land_cover -------------------------------------------------------
    def land_cover_tool(args: Mapping[str, Any]) -> ToolOutcome:
        point = _point(args)
        radius = int(args.get("radius_m") or 5000)
        year = args.get("year") or None
        profile = land_cover.profile_for(point, radius_m=radius, year=year)
        top = profile.ranked()[:4]
        payload = {
            "year": profile.year,
            "total_area_sq_km": round(profile.total_area_sq_km, 3),
            "classes": [c.as_dict() for c in profile.ranked()],
        }
        summary = (
            f"Land cover for {profile.year}: "
            + "; ".join(
                f"{c.label} {c.share_pct:.1f}%" if c.share_pct is not None
                else f"{c.label} {c.area_sq_km:.2f} sq km"
                for c in top
            )
        ) if top else f"No land-cover classes returned for {profile.year}"
        return ToolOutcome(
            name="land_cover", ok=True, summary=summary, payload=payload
        )

    registry.register(
        ToolSpec(
            name="land_cover",
            description=(
                "Land use / land cover statistics around a point, from NRSC LULC "
                "data. Returns area and percentage per class."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **_POINT_SCHEMA,
                    "radius_m": {
                        "type": "integer",
                        "description": "Radius in metres (default 5000)",
                    },
                    "year": {
                        "type": "string",
                        "description": "LULC year label such as '2015_16' (optional)",
                    },
                },
                "required": ["lat", "lon"],
            },
        ),
        land_cover_tool,
    )

    # -- nearby_facilities ------------------------------------------------
    def nearby_facilities(args: Mapping[str, Any]) -> ToolOutcome:
        point = _point(args)
        radius = int(args.get("radius_m") or 5000)
        raw_kind = args.get("kind")
        kind = FacilityKind.from_api(str(raw_kind)) if raw_kind else None
        found = list(facilities.nearby(point, radius_m=radius, kind=kind))
        found.sort(
            key=lambda f: f.distance_m if f.distance_m is not None else float("inf")
        )
        payload = {"count": len(found), "facilities": [f.as_dict() for f in found[:10]]}
        if not found:
            summary = f"No facilities found within {radius} m"
        else:
            summary = f"{len(found)} facility(ies) within {radius} m; nearest: " + ", ".join(
                f"{f.name} ({f.kind.value})" for f in found[:3]
            )
        return ToolOutcome(
            name="nearby_facilities", ok=True, summary=summary, payload=payload
        )

    registry.register(
        ToolSpec(
            name="nearby_facilities",
            description=(
                "Find hospitals and/or post offices within a radius of a point, "
                "nearest first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **_POINT_SCHEMA,
                    "radius_m": {"type": "integer", "description": "Radius in metres"},
                    "kind": {
                        "type": "string",
                        "enum": ["hospital", "postal"],
                        "description": "Restrict to one facility type (optional)",
                    },
                },
                "required": ["lat", "lon"],
            },
        ),
        nearby_facilities,
    )

    # -- route_to_facility ------------------------------------------------
    if routes is not None:

        def route_to_facility(args: Mapping[str, Any]) -> ToolOutcome:
            origin = _point(args, "lat1", "lon1")
            destination = _point(args, "lat2", "lon2")
            route = routes.route(origin, destination)
            payload = {
                "distance_km": route.distance_km,
                "duration_min": route.duration_min,
            }
            if route.distance_km is None:
                summary = "No road route found between those points"
            else:
                summary = f"Road distance about {route.distance_km:.1f} km"
                if route.duration_min is not None:
                    summary += f", roughly {route.duration_min:.0f} minutes"
            return ToolOutcome(
                name="route_to_facility", ok=True, summary=summary, payload=payload
            )

        registry.register(
            ToolSpec(
                name="route_to_facility",
                description=(
                    "Shortest road route between two points in the same state. "
                    "Use it to tell someone how far the nearest hospital is."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat1": {"type": "number"},
                        "lon1": {"type": "number"},
                        "lat2": {"type": "number"},
                        "lon2": {"type": "number"},
                    },
                    "required": ["lat1", "lon1", "lat2", "lon2"],
                },
            ),
            route_to_facility,
        )

    return registry


def describe_lulc_code(code: str) -> str:
    """Small helper kept public for the web layer's legend endpoint."""
    return label_for(code)
