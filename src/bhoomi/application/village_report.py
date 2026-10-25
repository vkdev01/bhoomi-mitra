"""Use case: assemble a civic "what is this place like" report.

This is the deterministic half of the application. It composes four independent
ports into one aggregate and degrades gracefully: a failure in the routing
service must not lose the land-cover answer. Each optional step therefore
records a note instead of raising.
"""

from __future__ import annotations

from dataclasses import dataclass

from bhoomi.domain.errors import PlaceNotFoundError
from bhoomi.domain.models import (
    Coordinates,
    Facility,
    FacilityKind,
    Route,
    Village,
    VillageReport,
)
from bhoomi.domain.ports import (
    FacilityProvider,
    LandCoverProvider,
    PlaceResolver,
    RouteProvider,
)


@dataclass(frozen=True, slots=True)
class ReportRequest:
    """Either ``place`` or ``point`` must be supplied."""

    place: str | None = None
    point: Coordinates | None = None
    radius_m: int = 5000
    year: str | None = None
    include_routes: bool = True
    facility_kinds: tuple[FacilityKind, ...] = (
        FacilityKind.HOSPITAL,
        FacilityKind.POST_OFFICE,
    )

    def __post_init__(self) -> None:
        if not self.place and self.point is None:
            raise ValueError("ReportRequest needs either 'place' or 'point'")
        if self.radius_m <= 0:
            raise ValueError("radius_m must be positive")


class BuildVillageReport:
    """Composes place, land-cover, facility and route providers.

    Every collaborator is injected as a port, so this class is testable with
    plain fakes and gains new data sources without modification.
    """

    def __init__(
        self,
        places: PlaceResolver,
        land_cover: LandCoverProvider,
        facilities: FacilityProvider,
        routes: RouteProvider | None = None,
        *,
        data_source: str = "unknown",
    ) -> None:
        self._places = places
        self._land_cover = land_cover
        self._facilities = facilities
        self._routes = routes
        self._data_source = data_source

    def execute(self, request: ReportRequest) -> VillageReport:
        notes: list[str] = []

        village = self._resolve(request, notes)
        point = village.location or request.point

        if point is None:
            notes.append(
                "Coordinates are not published for this village, so land-cover "
                "and facility lookups were skipped. Try a nearby town name or "
                "supply a latitude/longitude."
            )
            return VillageReport(
                village=village,
                radius_m=request.radius_m,
                notes=tuple(notes),
                data_source=self._data_source,
            )

        land_cover = self._land_cover_safely(point, request, notes)
        facilities = self._facilities_safely(point, request, notes)
        routes = self._routes_safely(point, facilities, request, notes)

        return VillageReport(
            village=village,
            land_cover=land_cover,
            facilities=facilities,
            routes=routes,
            radius_m=request.radius_m,
            notes=tuple(notes),
            data_source=self._data_source,
        )

    # -- steps ------------------------------------------------------------

    def _resolve(self, request: ReportRequest, notes: list[str]) -> Village:
        if request.point is not None and not request.place:
            try:
                return self._places.reverse(request.point)
            except PlaceNotFoundError:
                notes.append(
                    "The reverse-geocoding service had no village for these "
                    "coordinates; reporting on the point itself."
                )
                return Village(name="Selected point", location=request.point)

        try:
            return self._places.resolve(request.place or "")
        except PlaceNotFoundError:
            if request.point is not None:
                notes.append(
                    f"No village matched {request.place!r}; using the supplied "
                    "coordinates instead."
                )
                return Village(name=request.place or "Selected point", location=request.point)
            raise

    def _land_cover_safely(self, point, request, notes):
        try:
            return self._land_cover.profile_for(
                point, radius_m=request.radius_m, year=request.year
            )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Land-cover statistics unavailable: {exc}")
            return None

    def _facilities_safely(self, point, request, notes) -> tuple[Facility, ...]:
        collected: list[Facility] = []
        for kind in request.facility_kinds:
            try:
                collected.extend(
                    self._facilities.nearby(
                        point, radius_m=request.radius_m, kind=kind
                    )
                )
            except Exception as exc:  # noqa: BLE001
                notes.append(f"{kind.value.title()} lookup unavailable: {exc}")
        return tuple(collected)

    def _routes_safely(self, point, facilities, request, notes) -> tuple[Route, ...]:
        if not request.include_routes or self._routes is None:
            return ()

        hospitals = [f for f in facilities if f.kind is FacilityKind.HOSPITAL]
        with_location = [f for f in hospitals if f.location is not None]
        if not with_location:
            return ()

        with_location.sort(
            key=lambda f: f.distance_m if f.distance_m is not None else float("inf")
        )
        nearest = with_location[0]
        try:
            route = self._routes.route(point, nearest.location)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Routing unavailable: {exc}")
            return ()

        return (Route(
            distance_km=route.distance_km,
            duration_min=route.duration_min,
            geometry=route.geometry,
            destination_name=nearest.name,
        ),)
