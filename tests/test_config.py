"""Tests for settings and the .env loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from bhoomi.config import Settings, load_dotenv


@pytest.fixture()
def clean_env(monkeypatch):
    """Make sure no ambient credential leaks into these assertions."""
    for name in ("BHUVAN_TOKEN", "SARVAM_API_KEY", "BHOOMI_DEFAULT_LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _write_env(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


def test_dotenv_values_are_loaded(clean_env, tmp_path):
    path = _write_env(tmp_path, "BHUVAN_TOKEN=abc123\nSARVAM_API_KEY=xyz789\n")
    settings = Settings.from_env(dotenv_path=path)
    assert settings.bhuvan_token == "abc123"
    assert settings.sarvam_api_key == "xyz789"


def test_real_environment_wins_over_dotenv(clean_env, tmp_path):
    clean_env.setenv("BHUVAN_TOKEN", "from-the-real-env")
    path = _write_env(tmp_path, "BHUVAN_TOKEN=from-the-file\n")
    assert Settings.from_env(dotenv_path=path).bhuvan_token == "from-the-real-env"


def test_dotenv_quotes_and_comments_are_handled(clean_env, tmp_path):
    path = _write_env(
        tmp_path,
        '# a comment\n\nBHUVAN_TOKEN="quoted"\nSARVAM_API_KEY=\'single\'\n',
    )
    settings = Settings.from_env(dotenv_path=path)
    assert settings.bhuvan_token == "quoted"
    assert settings.sarvam_api_key == "single"


def test_missing_dotenv_is_not_an_error(clean_env, tmp_path):
    settings = Settings.from_env(dotenv_path=tmp_path / "nope.env")
    assert settings.bhuvan_token is None


def test_malformed_lines_are_skipped(clean_env, tmp_path):
    path = _write_env(tmp_path, "this line has no equals sign\nBHUVAN_TOKEN=ok\n")
    assert Settings.from_env(dotenv_path=path).bhuvan_token == "ok"


def test_empty_values_are_treated_as_unset(clean_env, tmp_path):
    path = _write_env(tmp_path, "BHUVAN_TOKEN=\n")
    settings = Settings.from_env(dotenv_path=path)
    assert settings.bhuvan_token is None
    assert settings.wants_live_geo is False


def test_load_dotenv_is_idempotent(clean_env, tmp_path):
    path = _write_env(tmp_path, "BHUVAN_TOKEN=once\n")
    load_dotenv(path)
    load_dotenv(path)
    assert Settings.from_env(dotenv_path=path).bhuvan_token == "once"


# -- mode selection -------------------------------------------------------


def test_fixture_mode_never_uses_live_services():
    settings = Settings(bhuvan_token="t", sarvam_api_key="k", data_mode="fixture")
    assert settings.wants_live_geo is False
    assert settings.wants_live_llm is False


def test_live_mode_forces_live_services():
    settings = Settings(bhuvan_token=None, sarvam_api_key=None, data_mode="live")
    assert settings.wants_live_geo is True
    assert settings.wants_live_llm is True


def test_auto_mode_follows_the_presence_of_credentials():
    with_token = Settings(bhuvan_token="t", data_mode="auto")
    without = Settings(bhuvan_token=None, data_mode="auto")
    assert with_token.wants_live_geo is True
    assert without.wants_live_geo is False


def test_public_summary_never_contains_a_secret():
    settings = Settings(bhuvan_token="super-secret-token", sarvam_api_key="super-secret-key")
    summary = str(settings.public_summary())
    assert "super-secret" not in summary


# -- per-theme Bhuvan tokens ---------------------------------------------


def test_capability_token_falls_back_to_the_general_one():
    settings = Settings(bhuvan_token="general")
    assert settings.bhuvan_token_for("lulc") == "general"
    assert settings.bhuvan_token_for("routing") == "general"


def test_capability_token_prefers_the_specific_one():
    settings = Settings(bhuvan_token="general", bhuvan_token_lulc="lulc-only")
    assert settings.bhuvan_token_for("lulc") == "lulc-only"
    assert settings.bhuvan_token_for("routing") == "general"


def test_no_tokens_means_no_live_capabilities():
    settings = Settings(data_mode="auto")
    assert settings.live_geo_capabilities == ()
    assert settings._geo_source_label() == "fixture"


def test_partial_tokens_report_mixed():
    settings = Settings(bhuvan_token_lulc="x", bhuvan_token_proximity="y")
    assert set(settings.live_geo_capabilities) == {"lulc", "proximity"}
    assert settings._geo_source_label() == "mixed"


def test_all_tokens_report_fully_live():
    settings = Settings(
        bhuvan_token_geocoding="a",
        bhuvan_token_lulc="b",
        bhuvan_token_proximity="c",
        bhuvan_token_routing="d",
    )
    assert settings._geo_source_label() == "bhuvan-live"


def test_fixture_mode_ignores_tokens_entirely():
    settings = Settings(data_mode="fixture", bhuvan_token="x")
    assert settings.live_geo_capabilities == ()
    assert settings._geo_source_label() == "fixture"
