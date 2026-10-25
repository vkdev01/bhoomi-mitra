"""Domain -> HTTP DTO mapping.

Kept apart from the routes so that changing the wire format never touches
routing logic, and so the mapping can be unit-tested on its own.
"""

from __future__ import annotations

from bhoomi.domain.models import LandCoverProfile, VillageReport
from bhoomi.web.schemas import (
    FacilityOut,
    LandCoverClassOut,
    LandCoverOut,
    ReportOut,
    RouteOut,
    VillageOut,
)


def village_to_out(village) -> VillageOut:
    return VillageOut(
        name=village.name,
        state=village.state,
        district=village.district,
        sub_district=village.sub_district,
        population=village.population,
        households=village.households,
        location=None if village.location is None else village.location.as_dict(),
        village_id=village.village_id,
    )


def land_cover_to_out(profile: LandCoverProfile) -> LandCoverOut:
    return LandCoverOut(
        year=profile.year,
        total_area_sq_km=round(profile.total_area_sq_km, 4),
        classes=[
            LandCoverClassOut(
                code=c.code,
                label=c.label,
                area_sq_km=round(c.area_sq_km, 4),
                share_pct=None if c.share_pct is None else round(c.share_pct, 2),
            )
            for c in profile.ranked()
        ],
    )


def report_to_out(report: VillageReport) -> ReportOut:
    return ReportOut(
        village=village_to_out(report.village),
        land_cover=None if report.land_cover is None else land_cover_to_out(report.land_cover),
        facilities=[
            FacilityOut(
                kind=f.kind.value,
                name=f.name,
                location=None if f.location is None else f.location.as_dict(),
                distance_m=None if f.distance_m is None else round(f.distance_m, 1),
                address=f.address,
            )
            for f in report.facilities
        ],
        routes=[
            RouteOut(
                distance_km=None if r.distance_km is None else round(r.distance_km, 2),
                duration_min=None if r.duration_min is None else round(r.duration_min, 1),
                destination_name=r.destination_name,
                geometry=dict(r.geometry) if r.geometry else None,
            )
            for r in report.routes
        ],
        radius_m=report.radius_m,
        notes=list(report.notes),
        data_source=report.data_source,
    )
