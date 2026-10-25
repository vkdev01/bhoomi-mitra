"""Shared test fixtures.

The suite runs entirely offline: fixture geo data plus the rule-based planner.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from bhoomi.adapters.http import HttpJsonClient
from bhoomi.composition import build_container
from bhoomi.config import Settings
from bhoomi.web.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "fixtures" / "demo_geo.json"


@pytest.fixture(scope="session")
def fixture_path() -> Path:
    return FIXTURE_PATH


@pytest.fixture()
def fixture_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def settings() -> Settings:
    """Settings pinned to fixtures: no network, no secrets."""
    return Settings(
        sarvam_api_key=None,
        bhuvan_token=None,
        data_mode="fixture",
        fixture_path=FIXTURE_PATH,
        default_language="en-IN",
        default_radius_m=5000,
        max_agent_steps=5,
    )


@pytest.fixture()
def container(settings: Settings):
    built = build_container(settings)
    yield built
    built.close()


@pytest.fixture()
def client(container):
    app = create_app(container)
    with TestClient(app) as test_client:
        yield test_client


def make_json_client(handler, *, base_url: str = "https://example.test") -> HttpJsonClient:
    """Build an ``HttpJsonClient`` over a stub transport (no sockets)."""
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, timeout=5.0)
    return HttpJsonClient(base_url, max_retries=0, client=http_client)
