"""Contract tests: the same expectations against both implementations.

This is the Liskov Substitution check done properly. Every assertion here is
written once and executed twice — once against the bundled fixture provider and
once against the real Bhuvan adapters wired to a stub transport that speaks the
documented wire format. If the two ever diverge in behaviour, one of these
fails.
"""

from __future__ import annotations

import httpx
import pytest

from bhoomi.adapters.bhuvan import (
    BhuvanFacilityProvider,
    BhuvanLulc250kProvider,
    BhuvanPlaceResolver,
    BhuvanRouteProvider,
)
from bhoomi.adapters.fixtures import FixtureGeoProvider
from bhoomi.domain.models import Coordinates, FacilityKind
from bhoomi.domain.ports import (
    FacilityProvider,
    LandCoverProvider,
    PlaceResolver,
    RouteProvider,
)
from tests.conftest import make_json_client

POINT = Coordinates(lat=16.2794, lon=80.5884)


def _bhuvan_handler(request: httpx.Request) -> httpx.Response:
    path = str(request.url.path)
    if "curl_village_geocode" in path or "curl_reverse_village" in path:
        return httpx.Response(
            200,
            json=[
                {
                    "name1": "SEKURU",
                    "vid": "2817004002130200",
                    "no_hh": "2747",
                    "tot_p": "10207",
                    "dhq_name": "GUNTUR",
                    "thq_name": "CHEBROLU",
                    "state": "ANDHRA PRADESH",
                    "lat": "16.2794",
                    "lon": "80.5884",
                }
            ],
        )
    if "curl_hos_pos_prox" in path:
        theme = request.url.params.get("theme", "all")
        rows = [
            {"name": "PHC Chebrolu", "theme": "hospital", "lat": 16.2841, "lon": 80.5921, "distance": 620.0},
            {"name": "Sekuru PO", "theme": "postal", "lat": 16.278, "lon": 80.587, "distance": 180.0},
        ]
        if theme in {"hospital", "postal"}:
            rows = [r for r in rows if r["theme"] == theme]
        return httpx.Response(200, json=rows)
    if "curl_routing_state" in path:
        return httpx.Response(
            200,
            json={
                "type": "LineString",
                "coordinates": [[80.5884, 16.2794], [80.5921, 16.2841]],
            },
        )
    if "curl_lulc250k" in path:
        return httpx.Response(
            200,
            json=[
                {"Year": "2015_16", "LULC Code": "l02", "LULC Description": "Agricultural land", "Area in Sq. Km": "22.4"},
                {"Year": "2015_16", "LULC Code": "l01", "LULC Description": "Built-up land", "Area in Sq. Km": "3.1"},
            ],
        )
    return httpx.Response(404, json={"error": "unexpected path", "path": path})


class BhuvanBundle:
    """Presents the four Bhuvan adapters as one object, like the fixture provider."""

    def __init__(self) -> None:
        self._client = make_json_client(_bhuvan_handler)
        token = "test-token"
        self.places = BhuvanPlaceResolver(self._client, token)
        self.land_cover = BhuvanLulc250kProvider(self._client, token)
        self.facilities = BhuvanFacilityProvider(self._client, token)
        self.routes = BhuvanRouteProvider(self._client, token)


@pytest.fixture(params=["fixture", "bhuvan"])
def bundle(request, fixture_path):
    if request.param == "fixture":
        geo = FixtureGeoProvider(fixture_path)
        return {"places": geo, "land_cover": geo, "facilities": geo, "routes": geo}
    b = BhuvanBundle()
    return {
        "places": b.places,
        "land_cover": b.land_cover,
        "facilities": b.facilities,
        "routes": b.routes,
    }


# -- ports are satisfied structurally -------------------------------------


def test_bundle_satisfies_every_port(bundle):
    assert isinstance(bundle["places"], PlaceResolver)
    assert isinstance(bundle["land_cover"], LandCoverProvider)
    assert isinstance(bundle["facilities"], FacilityProvider)
    assert isinstance(bundle["routes"], RouteProvider)


# -- shared behaviour -----------------------------------------------------


def test_resolve_returns_a_village_with_population(bundle):
    village = bundle["places"].resolve("Sekuru")
    assert village.name.lower().startswith("sekuru")
    assert village.population == 10207


def test_reverse_returns_a_village(bundle):
    village = bundle["places"].reverse(POINT)
    assert village.name


def test_land_cover_returns_positive_area(bundle):
    profile = bundle["land_cover"].profile_for(POINT, radius_m=5000, year="2015_16")
    assert profile.total_area_sq_km > 0
    assert profile.classes


def test_land_cover_shares_sum_to_100(bundle):
    profile = bundle["land_cover"].profile_for(POINT, radius_m=5000, year="2015_16")
    assert sum(c.share_pct for c in profile.classes) == pytest.approx(100.0, abs=0.01)


def test_facilities_include_a_hospital_and_a_post_office(bundle):
    found = bundle["facilities"].nearby(POINT, radius_m=5000)
    kinds = {f.kind for f in found}
    assert FacilityKind.HOSPITAL in kinds
    assert FacilityKind.POST_OFFICE in kinds


def test_facility_filtering_is_honoured(bundle):
    hospitals = bundle["facilities"].nearby(
        POINT, radius_m=5000, kind=FacilityKind.HOSPITAL
    )
    assert hospitals
    assert all(f.kind is FacilityKind.HOSPITAL for f in hospitals)


def test_route_has_a_positive_distance(bundle):
    route = bundle["routes"].route(POINT, Coordinates(lat=16.2841, lon=80.5921))
    assert route.distance_km is not None
    assert route.distance_km > 0


def test_route_geometry_is_geojson(bundle):
    route = bundle["routes"].route(POINT, Coordinates(lat=16.2841, lon=80.5921))
    assert route.geometry is not None
    assert route.geometry.get("type") in {"LineString", "MultiLineString", "FeatureCollection"}
