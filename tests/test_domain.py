"""Domain-layer tests: pure logic, no collaborators."""

from __future__ import annotations

import pytest

from bhoomi.domain.errors import PlaceNotFoundError
from bhoomi.domain.lulc import code_for_label, label_for
from bhoomi.domain.models import (
    Coordinates,
    FacilityKind,
    LandCoverClass,
    LandCoverProfile,
    Village,
    VillageReport,
)


def test_coordinates_reject_out_of_range_latitude():
    with pytest.raises(ValueError):
        Coordinates(lat=91.0, lon=0.0)


def test_coordinates_reject_out_of_range_longitude():
    with pytest.raises(ValueError):
        Coordinates(lat=0.0, lon=181.0)


def test_coordinates_are_immutable():
    import dataclasses

    point = Coordinates(lat=16.0, lon=80.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        point.lat = 17.0  # type: ignore[misc]


def test_village_label_skips_missing_parts():
    village = Village(name="sekuru", district="guntur", state="andhra pradesh")
    assert village.label == "Sekuru, Guntur, Andhra Pradesh"


def test_village_label_with_only_name():
    assert Village(name="sekuru").label == "Sekuru"


def test_land_cover_profile_ranks_and_summarises():
    profile = LandCoverProfile(
        year="2015_16",
        classes=(
            LandCoverClass(code="l02", label="Agricultural land", area_sq_km=22.4),
            LandCoverClass(code="l01", label="Built-up land", area_sq_km=3.1),
        ),
        total_area_sq_km=25.5,
    )
    assert profile.ranked()[0].label == "Agricultural land"
    assert profile.dominant().code == "l02"
    assert profile.share_of("agricultur") == pytest.approx(87.84, abs=0.01)


def test_land_cover_share_of_unknown_label_is_zero():
    profile = LandCoverProfile(
        year="2015_16",
        classes=(LandCoverClass(code="l02", label="Agricultural land", area_sq_km=1.0),),
        total_area_sq_km=1.0,
    )
    assert profile.share_of("glacier") == 0.0


def test_land_cover_profile_rejects_negative_area():
    with pytest.raises(ValueError):
        LandCoverProfile(year="x", classes=(), total_area_sq_km=-1.0)


def test_land_cover_profile_empty_has_no_dominant():
    assert LandCoverProfile(year="x", classes=(), total_area_sq_km=0.0).dominant() is None


def test_facility_kind_parsing_accepts_aliases():
    assert FacilityKind.from_api("hospitals") is FacilityKind.HOSPITAL
    assert FacilityKind.from_api("POSTAL") is FacilityKind.POST_OFFICE
    assert FacilityKind.from_api("post_office") is FacilityKind.POST_OFFICE


def test_facility_kind_rejects_nonsense():
    with pytest.raises(ValueError):
        FacilityKind.from_api("spaceport")


def test_village_report_filters_facilities_by_kind():
    from bhoomi.domain.models import Facility

    report = VillageReport(
        village=Village(name="X"),
        facilities=(
            Facility(kind=FacilityKind.HOSPITAL, name="A"),
            Facility(kind=FacilityKind.POST_OFFICE, name="B"),
        ),
    )
    assert [f.name for f in report.facilities_of(FacilityKind.HOSPITAL)] == ["A"]


def test_lulc_label_lookup_by_code():
    assert label_for("l02") == "Agricultural land"
    assert label_for("L01") == "Built-up land"


def test_lulc_label_prefers_api_supplied_label():
    assert label_for("l99", "Custom class") == "Custom class"


def test_lulc_label_falls_back_to_raw_code():
    assert label_for("zz9") == "zz9"


def test_lulc_reverse_lookup():
    assert code_for_label("Built-up land") == "l01"
    assert code_for_label("not a class") is None


def test_place_not_found_is_a_domain_error():
    from bhoomi.domain.errors import BhoomiError

    assert issubclass(PlaceNotFoundError, BhoomiError)
