"""Tests for the map layer catalogue."""

from __future__ import annotations

from bhoomi.domain.map_layers import (
    BHUVAN_ATTRIBUTION,
    LULC_YEAR_CODES,
    default_overlay_id,
    lulc_overlays,
    raster_bases,
    year_label,
)

SERVICE = "https://example.test/LULC250K.exe"


def test_year_label_formats_the_code():
    assert year_label("1516") == "2015-16"
    assert year_label("0405") == "2004-05"
    assert year_label("2021") == "2020-21"


def test_year_label_passes_through_unknown_codes():
    assert year_label("all") == "all"


def test_one_overlay_per_advertised_year():
    overlays = lulc_overlays(SERVICE)
    assert len(overlays) == len(LULC_YEAR_CODES)


def test_overlay_layer_names_match_the_service():
    overlays = lulc_overlays(SERVICE)
    assert overlays[0].layer_name == "LULC250K_0405"
    assert overlays[-1].layer_name == "LULC250K_2425"


def test_overlay_ids_are_unique():
    overlays = lulc_overlays(SERVICE)
    assert len({o.id for o in overlays}) == len(overlays)


def test_overlay_carries_service_url_and_attribution():
    overlay = lulc_overlays(SERVICE)[0]
    assert overlay.service_url == SERVICE
    assert overlay.attribution == BHUVAN_ATTRIBUTION
    assert 0 < overlay.opacity <= 1


def test_overlay_serialises_for_the_wire():
    payload = lulc_overlays(SERVICE)[0].as_dict()
    assert set(payload) == {
        "id", "title", "layer_name", "service_url", "year", "attribution", "opacity"
    }


def test_default_overlay_is_the_latest_year():
    overlays = lulc_overlays(SERVICE)
    assert default_overlay_id(overlays) == overlays[-1].id


def test_default_overlay_of_nothing_is_none():
    assert default_overlay_id(()) is None


def test_two_base_layers_are_offered():
    bases = raster_bases("https://tiles.test/{z}/{y}/{x}")
    assert [b.id for b in bases] == ["satellite", "plain"]


def test_satellite_base_carries_a_url_template():
    satellite = raster_bases("https://tiles.test/{z}/{y}/{x}")[0]
    assert "{z}" in (satellite.url_template or "")
    assert "Esri" in satellite.attribution


def test_plain_base_has_no_url_template():
    plain = raster_bases("https://tiles.test/{z}/{y}/{x}")[1]
    assert plain.url_template is None
    assert plain.background_colour.startswith("#")
