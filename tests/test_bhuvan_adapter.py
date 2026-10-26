"""Bhuvan adapter tests against a stub transport.

These exercise the wire-format mapping — the part most likely to break when
NRSC changes a field name — without touching the network.
"""

from __future__ import annotations

import httpx
import pytest

from bhoomi.adapters.bhuvan import (
    BhuvanFacilityProvider,
    BhuvanLulc50kProvider,
    BhuvanLulc250kProvider,
    BhuvanPlaceResolver,
    BhuvanRouteProvider,
    circle_wkt,
)
from bhoomi.adapters.http import parse_json_body
from bhoomi.domain.errors import (
    PlaceNotFoundError,
    UpstreamAuthError,
    UpstreamUnavailableError,
)
from bhoomi.domain.models import Coordinates, FacilityKind
from tests.conftest import make_json_client

POINT = Coordinates(lat=16.2794, lon=80.5884)


def _handler(path_fragment: str, payload, *, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert path_fragment in str(request.url.path)
        if isinstance(payload, str):
            return httpx.Response(status, text=payload)
        return httpx.Response(status, json=payload)

    return handler


# -- circle geometry ------------------------------------------------------


def test_circle_wkt_is_closed_and_valid():
    wkt = circle_wkt(POINT, 5000, segments=8)
    assert wkt.startswith("POLYGON((")
    assert wkt.endswith("))")
    body = wkt[len("POLYGON(("):-2]
    points = body.split(", ")
    assert len(points) == 9
    assert points[0] == points[-1]


def test_circle_wkt_rejects_non_positive_radius():
    with pytest.raises(ValueError):
        circle_wkt(POINT, 0)


def test_circle_wkt_grows_with_radius():
    small = circle_wkt(POINT, 1000, segments=4)
    large = circle_wkt(POINT, 4000, segments=4)
    first_small = float(small[len("POLYGON(("):].split(",")[0].split()[0])
    first_large = float(large[len("POLYGON(("):].split(",")[0].split()[0])
    assert first_large > first_small


# -- place resolution -----------------------------------------------------


def test_resolve_maps_the_documented_field_names():
    payload = [
        {
            "name1": "SEKURU ",
            "vid": "2817004002130200",
            "no_hh": "2747",
            "tot_p": "10207",
            "dhq_name": "GUNTUR",
            "thq_name": "CHEBROLU",
            "state": "ANDHRA PRADESH",
            "lat": "16.2794",
            "lon": "80.5884",
        }
    ]
    client = make_json_client(_handler("curl_village_geocode", payload))
    resolver = BhuvanPlaceResolver(client, "token")
    village = resolver.resolve("sekuru")

    assert village.name == "Sekuru"
    assert village.population == 10207
    assert village.households == 2747
    assert village.district == "Guntur"
    assert village.sub_district == "Chebrolu"
    assert village.state == "Andhra Pradesh"
    assert village.location == Coordinates(lat=16.2794, lon=80.5884)
    assert village.village_id == "2817004002130200"


def test_resolve_accepts_alternative_field_names():
    payload = [{"village": "Demo", "population": "500", "district": "D", "latitude": 1.0, "longitude": 2.0}]
    client = make_json_client(_handler("curl_village_geocode", payload))
    village = BhuvanPlaceResolver(client, "t").resolve("demo")
    assert village.population == 500
    assert village.location == Coordinates(lat=1.0, lon=2.0)


def test_resolve_empty_result_raises_place_not_found():
    client = make_json_client(_handler("curl_village_geocode", []))
    with pytest.raises(PlaceNotFoundError):
        BhuvanPlaceResolver(client, "t").resolve("nowhere")


def test_resolve_false_body_raises_place_not_found():
    client = make_json_client(_handler("curl_village_geocode", "false"))
    with pytest.raises(PlaceNotFoundError):
        BhuvanPlaceResolver(client, "t").resolve("nowhere")


def test_reverse_keeps_the_query_point_when_none_returned():
    payload = [{"name1": "SEKURU", "tot_p": "10"}]
    client = make_json_client(_handler("curl_reverse_village", payload))
    village = BhuvanPlaceResolver(client, "t").reverse(POINT)
    assert village.name == "Sekuru"
    assert village.location == POINT


def test_resolver_requires_a_token():
    client = make_json_client(_handler("x", []))
    with pytest.raises(ValueError):
        BhuvanPlaceResolver(client, "")


# -- auth and transport errors -------------------------------------------


def test_invalid_token_body_becomes_upstream_auth_error():
    body = '{"error":"invalid_token","error_description":"The access token provided is invalid"}'
    client = make_json_client(_handler("curl_village_geocode", body))
    with pytest.raises(UpstreamAuthError):
        BhuvanPlaceResolver(client, "bad").resolve("sekuru")


def test_http_403_becomes_upstream_auth_error():
    client = make_json_client(_handler("curl_village_geocode", "denied", status=403))
    with pytest.raises(UpstreamAuthError):
        BhuvanPlaceResolver(client, "t").resolve("sekuru")


def test_http_500_becomes_upstream_unavailable():
    client = make_json_client(_handler("curl_village_geocode", "boom", status=500))
    with pytest.raises(UpstreamUnavailableError):
        BhuvanPlaceResolver(client, "t").resolve("sekuru")


def test_non_json_body_becomes_upstream_unavailable():
    client = make_json_client(_handler("curl_village_geocode", "<html>oops</html>"))
    with pytest.raises(UpstreamUnavailableError):
        BhuvanPlaceResolver(client, "t").resolve("sekuru")


# -- JSON extraction ------------------------------------------------------


def test_parse_json_body_handles_html_wrapper():
    wrapped = '<html><script src="echarts.js"></script>\n[{"Year":"2015_16","Area in Sq. Km":"3.1"}]\n</html>'
    assert parse_json_body(wrapped) == [{"Year": "2015_16", "Area in Sq. Km": "3.1"}]


def test_parse_json_body_handles_plain_json():
    assert parse_json_body('{"a": 1}') == {"a": 1}


def test_parse_json_body_rejects_html_without_json():
    with pytest.raises(UpstreamUnavailableError):
        parse_json_body("<html>nothing here</html>")


def test_parse_json_body_rejects_empty():
    with pytest.raises(UpstreamUnavailableError):
        parse_json_body("   ")


# -- facilities -----------------------------------------------------------


def test_facilities_are_parsed_and_typed():
    payload = [
        {"name": "PHC Chebrolu", "theme": "hospital", "lat": 16.2841, "lon": 80.5921, "distance": 620.5},
        {"name": "Sekuru PO", "theme": "postal", "lat": 16.278, "lon": 80.587, "distance": 180.0},
    ]
    client = make_json_client(_handler("curl_hos_pos_prox", payload))
    found = BhuvanFacilityProvider(client, "t").nearby(POINT, radius_m=5000)
    assert len(found) == 2
    assert found[0].kind is FacilityKind.HOSPITAL
    assert found[1].kind is FacilityKind.POST_OFFICE
    assert found[0].distance_m == pytest.approx(620.5)


def test_facility_without_a_kind_is_skipped_when_unfiltered():
    payload = [{"name": "Mystery", "lat": 1.0, "lon": 2.0}]
    client = make_json_client(_handler("curl_hos_pos_prox", payload))
    assert BhuvanFacilityProvider(client, "t").nearby(POINT, radius_m=5000) == ()


def test_facility_kind_filter_is_sent_as_the_theme():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["theme"] = request.url.params.get("theme")
        return httpx.Response(200, json=[])

    client = make_json_client(handler)
    BhuvanFacilityProvider(client, "t").nearby(
        POINT, radius_m=1000, kind=FacilityKind.HOSPITAL
    )
    assert captured["theme"] == "hospital"


# -- routing --------------------------------------------------------------


def test_route_reads_geojson_and_estimates_length():
    geometry = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[80.5884, 16.2794], [80.5921, 16.2841]],
                },
            }
        ],
    }
    client = make_json_client(_handler("curl_routing_state", geometry))
    route = BhuvanRouteProvider(client, "t").route(POINT, Coordinates(lat=16.2841, lon=80.5921))
    assert route.distance_km is not None
    assert 0 < route.distance_km < 2
    assert route.geometry is not None


def test_route_null_body_yields_empty_route():
    client = make_json_client(_handler("curl_routing_state", "null"))
    route = BhuvanRouteProvider(client, "t").route(POINT, Coordinates(lat=17.0, lon=81.0))
    assert route.distance_km is None


# -- land cover -----------------------------------------------------------


def test_lulc_250k_parses_year_records():
    payload = [
        {"Year": "2015_16", "LULC Code": "l02", "LULC Description": "Agricultural land", "Area in Sq. Km": "22.4"},
        {"Year": "2015_16", "LULC Code": "l01", "LULC Description": "Built-up land", "Area in Sq. Km": "3.1"},
        {"Year": "2018_19", "LULC Code": "l02", "LULC Description": "Agricultural land", "Area in Sq. Km": "20.0"},
    ]
    client = make_json_client(_handler("curl_lulc250k", payload))
    profile = BhuvanLulc250kProvider(client, "t").profile_for(POINT, radius_m=5000, year="2015_16")
    assert profile.year == "2015_16"
    assert profile.total_area_sq_km == pytest.approx(25.5)
    assert profile.ranked()[0].label == "Agricultural land"


def test_lulc_250k_picks_latest_year_when_unspecified():
    payload = [
        {"Year": "2015_16", "LULC Description": "Agricultural land", "Area in Sq. Km": "22.4"},
        {"Year": "2018_19", "LULC Description": "Built-up land", "Area in Sq. Km": "5.0"},
    ]
    client = make_json_client(_handler("curl_lulc250k", payload))
    profile = BhuvanLulc250kProvider(client, "t").profile_for(POINT, radius_m=5000)
    assert profile.year == "2018_19"


def test_lulc_250k_empty_raises():
    client = make_json_client(_handler("curl_lulc250k", []))
    with pytest.raises(UpstreamUnavailableError):
        BhuvanLulc250kProvider(client, "t").profile_for(POINT, radius_m=5000)


def test_lulc_50k_parses_code_columns():
    payload = [{"State": "AP", "l01": 3.1, "l02": 22.4, "l05": 1.6}]
    client = make_json_client(_handler("curl_aoi", payload))
    profile = BhuvanLulc50kProvider(client, "t").profile_for(POINT, radius_m=5000)
    labels = {c.label for c in profile.classes}
    assert "Built-up land" in labels
    assert profile.total_area_sq_km == pytest.approx(27.1)


def test_lulc_50k_parses_described_records():
    payload = [
        {"LULC Code": "l02", "LULC Description": "Agricultural land", "Area in Sq. Km": 10.0},
        {"LULC Code": "l01", "LULC Description": "Built-up land", "Area in Sq. Km": 2.0},
    ]
    client = make_json_client(_handler("curl_aoi", payload))
    profile = BhuvanLulc50kProvider(client, "t").profile_for(POINT, radius_m=5000)
    assert profile.total_area_sq_km == pytest.approx(12.0)


def test_lulc_50k_shares_are_percentages():
    payload = [{"l01": 1.0, "l02": 3.0}]
    client = make_json_client(_handler("curl_aoi", payload))
    profile = BhuvanLulc50kProvider(client, "t").profile_for(POINT, radius_m=5000)
    assert sum(c.share_pct for c in profile.classes) == pytest.approx(100.0)


# -- wrapped error bodies -------------------------------------------------


def test_lulc_error_body_wrapped_in_html_is_detected():
    """The LULC service wraps its JSON in an HTML page, errors included."""
    body = (
        '<!DOCTYPE HTML><html><head><script src="echarts.js"></script></head>\n'
        '{"error":"invalid_token","error_description":"The access token provided is invalid"}\n'
        "</html>"
    )
    client = make_json_client(_handler("curl_lulc250k", body))
    with pytest.raises(UpstreamAuthError):
        BhuvanLulc250kProvider(client, "bad").profile_for(POINT, radius_m=5000)


def test_lulc_with_no_usable_area_raises_instead_of_returning_empty():
    payload = [{"Year": "2015_16", "LULC Code": "l02", "LULC Description": "Agricultural land", "Area in Sq. Km": "0"}]
    client = make_json_client(_handler("curl_lulc250k", payload))
    with pytest.raises(UpstreamUnavailableError):
        BhuvanLulc250kProvider(client, "t").profile_for(POINT, radius_m=5000)


def test_lulc_50k_with_no_usable_area_raises():
    client = make_json_client(_handler("curl_aoi", [{"State": "AP"}]))
    with pytest.raises(UpstreamUnavailableError):
        BhuvanLulc50kProvider(client, "t").profile_for(POINT, radius_m=5000)
