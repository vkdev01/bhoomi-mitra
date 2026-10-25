"""Catalogue of map layers the interface can draw.

Pure data: no HTTP, no framework. The web layer serialises this and the browser
turns it into map layers, which keeps every upstream service URL in one place
instead of hardcoded in the front end.

Two kinds of layer exist here:

* ``RasterBase`` - a tiled backdrop (satellite imagery, or a plain grey canvas).
* ``WmsOverlay`` - an OGC Web Map Service layer drawn on top, which is how ISRO
  publishes its thematic data. The Bhuvan LULC 250k service advertises one layer
  per reference year, so each year becomes its own overlay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The year codes the Bhuvan LULC 1:250,000 service advertises, in order.
LULC_YEAR_CODES: tuple[str, ...] = (
    "0405", "0506", "0607", "0708", "0809", "0910",
    "1011", "1112", "1213", "1314", "1415", "1516",
    "1617", "1718", "1819", "2021", "2122", "2223",
    "2324", "2425",
)

BHUVAN_ATTRIBUTION = "Land cover: ISRO / NRSC Bhuvan LULC 1:250,000"
SATELLITE_ATTRIBUTION = "Imagery © Esri, Maxar, Earthstar Geographics"
PLAIN_ATTRIBUTION = "Plain canvas"


@dataclass(frozen=True, slots=True)
class RasterBase:
    """A tiled background layer."""

    id: str
    title: str
    url_template: str | None
    attribution: str
    max_zoom: int = 18
    background_colour: str = "#eef2ef"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url_template": self.url_template,
            "attribution": self.attribution,
            "max_zoom": self.max_zoom,
            "background_colour": self.background_colour,
        }


@dataclass(frozen=True, slots=True)
class WmsOverlay:
    """An OGC WMS layer to draw over the base."""

    id: str
    title: str
    layer_name: str
    service_url: str
    year: str
    attribution: str
    opacity: float = 0.8

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "layer_name": self.layer_name,
            "service_url": self.service_url,
            "year": self.year,
            "attribution": self.attribution,
            "opacity": self.opacity,
        }


def year_label(code: str) -> str:
    """Turn ``1516`` into ``2015-16``. Falls back to the raw code."""
    if len(code) == 4 and code.isdigit():
        return f"20{code[:2]}-{code[2:]}"
    return code


def lulc_overlays(service_url: str) -> tuple[WmsOverlay, ...]:
    """One overlay per LULC reference year the service publishes."""
    return tuple(
        WmsOverlay(
            id=f"lulc-{code}",
            title=f"Land cover {year_label(code)}",
            layer_name=f"LULC250K_{code}",
            service_url=service_url,
            year=year_label(code),
            attribution=BHUVAN_ATTRIBUTION,
        )
        for code in LULC_YEAR_CODES
    )


def raster_bases(satellite_url: str) -> tuple[RasterBase, ...]:
    """Satellite imagery first, then a plain canvas as the offline fallback."""
    return (
        RasterBase(
            id="satellite",
            title="Satellite",
            url_template=satellite_url,
            attribution=SATELLITE_ATTRIBUTION,
            max_zoom=19,
        ),
        RasterBase(
            id="plain",
            title="Plain",
            url_template=None,
            attribution=PLAIN_ATTRIBUTION,
            max_zoom=19,
        ),
    )


def default_overlay_id(overlays: tuple[WmsOverlay, ...]) -> str | None:
    """The most recent year, which is the most useful default."""
    return overlays[-1].id if overlays else None
