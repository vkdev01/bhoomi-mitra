"""Fixture adapter tests."""

from __future__ import annotations

import pytest

from bhoomi.adapters.fixtures import FixtureGeoProvider, haversine_m
from bhoomi.domain.errors import PlaceNotFoundError
from bhoomi.domain.models import Coordinates, FacilityKind


@pytest.fixture()
def provider(fixture_path) -> FixtureGeoProvider:
    return FixtureGeoProvider(fixture_path)


def test_resolve_is_case_insensitive(provider):
    assert provider.resolve("SEKURU").name == "Sekuru"


def test_resolve_accepts_an_alias(provider):
    assert provider.resolve("chebrolu").name == "Sekuru"


def test_resolve_carries_census_fields(provider):
    village = provider.resolve("Sekuru")
    assert village.population == 10207
    assert village.households == 2747
    assert village.district == "Guntur"


def test_resolve_unknown_place_raises_with_suggestions(provider):
    with pytest.raises(PlaceNotFoundError) as exc:
        provider.resolve("Atlantis")
    assert "Sekuru" in str(exc.value)


def test_resolve_empty_place_raises(provider):
    with pytest.raises(PlaceNotFoundError):
        provider.resolve("   ")


def test_reverse_returns_nearest_village_and_keeps_the_query_point(provider):
    point = Coordinates(lat=16.28, lon=80.59)
    village = provider.reverse(point)
    assert village.name == "Sekuru"
    assert village.location == point


def test_land_cover_shares_sum_to_100(provider):
    profile = provider.profile_for(Coordinates(lat=16.2794, lon=80.5884), radius_m=5000)
    assert sum(c.share_pct for c in profile.classes) == pytest.approx(100.0, abs=0.01)


def test_land_cover_scales_with_radius(provider):
    point = Coordinates(lat=16.2794, lon=80.5884)
    small = provider.profile_for(point, radius_m=5000)
    large = provider.profile_for(point, radius_m=10000)
    assert large.total_area_sq_km == pytest.approx(small.total_area_sq_km * 4, rel=0.01)


def test_facilities_are_sorted_by_distance(provider):
    point = Coordinates(lat=16.2794, lon=80.5884)
    found = provider.nearby(point, radius_m=20000)
    distances = [f.distance_m for f in found]
    assert distances == sorted(distances)


def test_facilities_can_be_filtered_by_kind(provider):
    point = Coordinates(lat=16.2794, lon=80.5884)
    posts = provider.nearby(point, radius_m=20000, kind=FacilityKind.POST_OFFICE)
    assert posts
    assert all(f.kind is FacilityKind.POST_OFFICE for f in posts)


def test_facilities_respect_the_radius(provider):
    point = Coordinates(lat=16.2794, lon=80.5884)
    assert provider.nearby(point, radius_m=100) == ()


def test_route_is_longer_than_the_straight_line(provider):
    origin = Coordinates(lat=16.2794, lon=80.5884)
    destination = Coordinates(lat=16.2420, lon=80.6400)
    route = provider.route(origin, destination)
    straight_km = haversine_m(origin, destination) / 1000
    assert route.distance_km > straight_km
    assert route.duration_min > 0
    assert route.geometry["type"] == "LineString"


def test_route_to_the_same_point_is_zero(provider):
    point = Coordinates(lat=16.0, lon=80.0)
    assert provider.route(point, point).distance_km == 0.0


def test_haversine_matches_a_known_distance():
    # Guntur to Vijayawada is about 32 km as the crow flies.
    a = Coordinates(lat=16.3067, lon=80.4365)
    b = Coordinates(lat=16.5062, lon=80.6480)
    assert 30_000 < haversine_m(a, b) < 34_000


def test_haversine_of_a_point_with_itself_is_zero():
    point = Coordinates(lat=16.3067, lon=80.4365)
    assert haversine_m(point, point) == 0.0


def test_provider_declares_its_data_source(provider):
    assert provider.data_source == "fixture"
