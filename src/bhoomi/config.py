"""Application settings, read once from the environment.

Deliberately dependency-free: a frozen dataclass plus ``os.environ``. Secrets
are never logged and never defaulted to a real value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_TRUE = {"1", "true", "yes", "on"}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the composition root needs to wire the application."""

    sarvam_api_key: str | None = None
    bhuvan_token: str | None = None

    sarvam_base_url: str = "https://api.sarvam.ai"
    bhuvan_base_url: str = "https://bhuvan-app1.nrsc.gov.in/api"

    chat_model: str = "sarvam-105b"
    stt_model: str = "saaras:v3"
    tts_model: str = "bulbul:v3"
    tts_speaker: str = "anushka"
    translate_model: str = "mayura:v1"

    lulc_scale: str = "250k"
    data_mode: str = "auto"  # auto | live | fixture

    http_timeout_s: float = 20.0
    http_max_retries: int = 2

    default_language: str = "en-IN"
    default_radius_m: int = 5000
    max_agent_steps: int = 5

    fixture_path: Path = field(
        default_factory=lambda: Path(
            _env("BHOOMI_FIXTURE_PATH")
            or Path(__file__).resolve().parents[2] / "fixtures" / "demo_geo.json"
        )
    )

    # -- derived ----------------------------------------------------------

    @property
    def wants_live_geo(self) -> bool:
        if self.data_mode == "fixture":
            return False
        if self.data_mode == "live":
            return True
        return bool(self.bhuvan_token)

    @property
    def wants_live_llm(self) -> bool:
        if self.data_mode == "fixture":
            return False
        if self.data_mode == "live":
            return True
        return bool(self.sarvam_api_key)

    @property
    def wants_live_speech(self) -> bool:
        return bool(self.sarvam_api_key)

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            sarvam_api_key=_env("SARVAM_API_KEY"),
            bhuvan_token=_env("BHUVAN_TOKEN"),
            sarvam_base_url=_env("SARVAM_BASE_URL", "https://api.sarvam.ai") or "",
            bhuvan_base_url=_env("BHUVAN_BASE_URL", "https://bhuvan-app1.nrsc.gov.in/api") or "",
            chat_model=_env("SARVAM_CHAT_MODEL", "sarvam-105b") or "sarvam-105b",
            stt_model=_env("SARVAM_STT_MODEL", "saaras:v3") or "saaras:v3",
            tts_model=_env("SARVAM_TTS_MODEL", "bulbul:v3") or "bulbul:v3",
            tts_speaker=_env("SARVAM_TTS_SPEAKER", "anushka") or "anushka",
            translate_model=_env("SARVAM_TRANSLATE_MODEL", "mayura:v1") or "mayura:v1",
            lulc_scale=(_env("BHUVAN_LULC_SCALE", "250k") or "250k").lower(),
            data_mode=(_env("BHOOMI_DATA_MODE", "auto") or "auto").lower(),
            http_timeout_s=_env_float("BHOOMI_HTTP_TIMEOUT_S", 20.0),
            http_max_retries=_env_int("BHOOMI_HTTP_RETRIES", 2),
            default_language=_env("BHOOMI_DEFAULT_LANGUAGE", "en-IN") or "en-IN",
            default_radius_m=_env_int("BHOOMI_DEFAULT_RADIUS_M", 5000),
            max_agent_steps=_env_int("BHOOMI_MAX_AGENT_STEPS", 5),
        )

    def public_summary(self) -> dict[str, object]:
        """Safe to expose over HTTP: never includes a secret."""
        return {
            "geo_source": "bhuvan-live" if self.wants_live_geo else "fixture",
            "llm_source": "sarvam-105b" if self.wants_live_llm else "rule-based-offline",
            "speech_available": self.wants_live_speech,
            "lulc_scale": self.lulc_scale,
            "data_mode": self.data_mode,
            "chat_model": self.chat_model,
            "default_language": self.default_language,
            "default_radius_m": self.default_radius_m,
        }
