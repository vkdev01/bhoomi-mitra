"""NRSC land-use / land-cover legend.

The Bhuvan LULC services return numeric class codes (``l01``..``l24``) rather
than human labels. This module is the single place that maps codes to readable
names, so a legend change never touches the adapters or the use cases.

The map below covers the classes commonly present in the 1:50,000 and
1:250,000 NRSC legends. It is intentionally conservative: an unrecognised code
is surfaced verbatim rather than guessed at, because a wrong land-cover label
is worse than an honest code.
"""

from __future__ import annotations

_LEVEL_TWO: dict[str, str] = {
    "l01": "Built-up land",
    "l02": "Agricultural land",
    "l03": "Forest",
    "l04": "Wasteland",
    "l05": "Water bodies",
    "l06": "Others",
    "l07": "Barren / rocky",
    "l08": "Shifting cultivation",
    "l09": "Plantation",
    "l10": "Aquaculture",
    "l11": "Salt pan",
    "l12": "Snow / glacial",
    "l13": "Sandy area",
    "l14": "Mining / industrial",
    "l15": "Scrub land",
    "l16": "Tree clad area",
    "l17": "Crop land",
    "l18": "Fallow land",
    "l19": "Deciduous forest",
    "l20": "Evergreen forest",
    "l21": "Degraded forest",
    "l22": "Tank / reservoir",
    "l23": "River / stream",
    "l24": "Grassland",
}

# Some Bhuvan endpoints return prose labels already; keep a reverse lookup so
# downstream code can compare classes by meaning rather than by code.
_BY_LABEL = {v.lower(): k for k, v in _LEVEL_TWO.items()}


def label_for(code: str, fallback: str | None = None) -> str:
    """Return a readable label for a LULC code.

    Falls back to ``fallback`` (typically the label the API itself sent), then
    to the raw code. Never invents a class name.
    """
    if fallback and fallback.strip():
        return fallback.strip()
    key = (code or "").strip().lower()
    if key.isdigit():
        key = f"l{int(key):02d}"
    return _LEVEL_TWO.get(key, code or "Unknown")


def code_for_label(label: str) -> str | None:
    """Best-effort reverse lookup used by fixture data and tests."""
    return _BY_LABEL.get((label or "").strip().lower())


def known_codes() -> tuple[str, ...]:
    return tuple(_LEVEL_TWO)
