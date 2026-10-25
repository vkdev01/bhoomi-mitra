"""Use-case tests for ``BuildVillageReport``.

Fakes are hand-written and minimal, which is the payoff of the narrow ports:
each test implements only the capability it needs.
"""

from __future__ import annotations

import pytest

from bhoomi.adapters.fixtures import FixtureGeoProvider
from bhoomi.application.village_report import BuildVillageReport, ReportRequest
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

POINT = Coordinates(lat=16.2794, lon=80.5884)


# -- fakes ----------------------------------------------------------------


class StubPlaces:
    def __init__(self, village: Village | None = None, *, fail_reverse: bool = False):
        self._village = village or Village(name="Sekuru", location=POINT)
        self._fail_reverse = fail_reverse

    def resolve(self, place: str) -> Village:
        if self._village is None:
            raise PlaceNotFoundError(place)
        return self._village

    def reverse(self, point: Coordinates) -> Village:
        if self._fail_reverse:
            raise PlaceNotFoundError("none")
        return self._village


class StubLandCover:
    def __init__(self, *, explode: bool = False):
        self._explode = explode
        self.calls = 0

    def profile_for(self, point, *, radius_m, year=None):
        self.calls += 1
        if self._explode:
            raise RuntimeError("LULC down")
        return LandCoverProfile(
            year=year or "2015_16",
            classes=(LandCoverClass(code="l02", label="Agricultural land", area_sq_km=10.0, share_pct=100.0),),
            total_area_sq_km=10.0,
        )


class StubFacilities:
    def __init__(self, *, explode_kind: FacilityKind | None = None):
        self._explode_kind = explode_kind

    def nearby(self, point, *, radius_m, kind=None):
        if kind is self._explode_kind:
            raise RuntimeError("proximity down")
        if kind is FacilityKind.POST_OFFICE:
            return (Facility(kind=FacilityKind.POST_OFFICE, name="PO", distance_m=100.0),)
        return (
            Facility(
                kind=FacilityKind.HOSPITAL,
                name="PHC",
                location=Coordinates(lat=16.2841, lon=80.5921),
                distance_m=620.0,
            ),
        )


class StubRoutes:
    def __init__(self, *, explode: bool = False):
        self._explode = explode
        self.calls = 0

    def route(self, origin, destination):
        self.calls += 1
        if self._explode:
            raise RuntimeError("routing down")
        return Route(distance_km=1.2, duration_min=3.0)


def _use_case(**kwargs) -> BuildVillageReport:
    defaults = dict(
        places=kwargs.pop("places", StubPlaces()),
        land_cover=kwargs.pop("land_cover", StubLandCover()),
        facilities=kwargs.pop("facilities", StubFacilities()),
        routes=kwargs.pop("routes", StubRoutes()),
    )
    return BuildVillageReport(**defaults, **kwargs)


# -- request validation ---------------------------------------------------


def test_request_needs_a_place_or_a_point():
    with pytest.raises(ValueError):
        ReportRequest()


def test_request_rejects_non_positive_radius():
    with pytest.raises(ValueError):
        ReportRequest(place="Sekuru", radius_m=0)


# -- happy path -----------------------------------------------------------


def test_report_combines_all_sources():
    report = _use_case().execute(ReportRequest(place="Sekuru"))

    assert report.village.name == "Sekuru"
    assert report.land_cover is not None
    assert len(report.facilities) == 2
    assert len(report.routes) == 1
    assert report.notes == ()


def test_route_targets_the_nearest_hospital():
    report = _use_case().execute(ReportRequest(place="Sekuru"))
    assert report.routes[0].destination_name == "PHC"


def test_data_source_is_stamped_on_the_report():
    report = _use_case(data_source="fixture").execute(ReportRequest(place="Sekuru"))
    assert report.data_source == "fixture"


def test_point_only_request_uses_reverse_geocoding():
    report = _use_case().execute(ReportRequest(point=POINT))
    assert report.village.name == "Sekuru"


# -- degradation ----------------------------------------------------------


def test_land_cover_failure_is_noted_not_raised():
    report = _use_case(land_cover=StubLandCover(explode=True)).execute(
        ReportRequest(place="Sekuru")
    )
    assert report.land_cover is None
    assert any("Land-cover" in note for note in report.notes)
    assert report.facilities  # the rest still arrived


def test_facility_failure_is_noted_not_raised():
    report = _use_case(facilities=StubFacilities(explode_kind=FacilityKind.HOSPITAL)).execute(
        ReportRequest(place="Sekuru")
    )
    assert any("Hospital" in note for note in report.notes)
    assert len(report.facilities) == 1  # the post office survived


def test_routing_failure_is_noted_not_raised():
    report = _use_case(routes=StubRoutes(explode=True)).execute(
        ReportRequest(place="Sekuru")
    )
    assert report.routes == ()
    assert any("Routing" in note for note in report.notes)


def test_routes_can_be_switched_off():
    report = _use_case(routes=StubRoutes()).execute(
        ReportRequest(place="Sekuru", include_routes=False)
    )
    assert report.routes == ()


def test_no_routes_without_a_route_provider():
    report = BuildVillageReport(
        places=StubPlaces(), land_cover=StubLandCover(), facilities=StubFacilities(), routes=None
    ).execute(ReportRequest(place="Sekuru"))
    assert report.routes == ()


def test_village_without_coordinates_skips_spatial_lookups():
    places = StubPlaces(village=Village(name="Nowhere"))
    land_cover = StubLandCover()
    report = _use_case(places=places, land_cover=land_cover).execute(
        ReportRequest(place="Nowhere")
    )
    assert land_cover.calls == 0
    assert any("Coordinates are not published" in n for n in report.notes)


def test_unresolvable_place_with_no_fallback_raises():
    class Missing(StubPlaces):
        def resolve(self, place):
            raise PlaceNotFoundError(place)

    with pytest.raises(PlaceNotFoundError):
        _use_case(places=Missing()).execute(ReportRequest(place="Atlantis"))


def test_unresolvable_place_falls_back_to_supplied_point():
    class Missing(StubPlaces):
        def resolve(self, place):
            raise PlaceNotFoundError(place)

    report = _use_case(places=Missing()).execute(
        ReportRequest(place="Atlantis", point=POINT)
    )
    assert report.village.location == POINT
    assert any("No village matched" in n for n in report.notes)


def test_reverse_geocode_failure_falls_back_to_the_point():
    places = StubPlaces(fail_reverse=True)
    report = _use_case(places=places).execute(ReportRequest(point=POINT))
    assert report.village.location == POINT
    assert any("reverse-geocoding" in n for n in report.notes)


# -- integration with the real fixture adapter ----------------------------


def test_works_against_the_fixture_adapter_end_to_end(fixture_path):
    geo = FixtureGeoProvider(fixture_path)
    report = BuildVillageReport(geo, geo, geo, geo, data_source="fixture").execute(
        ReportRequest(place="Sekuru", radius_m=20000)
    )
    assert report.village.population == 10207
    assert report.land_cover.dominant().label == "Agricultural land"
    assert report.facilities_of(FacilityKind.HOSPITAL)
    assert report.routes and report.routes[0].distance_km > 0
