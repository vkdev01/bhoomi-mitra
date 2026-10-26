#!/usr/bin/env python3
"""Check that live credentials actually work, capability by capability.

Run this after putting BHUVAN_TOKEN and/or SARVAM_API_KEY in your environment.
It exercises the real adapters against the real services and tells you exactly
which capability is broken and why, instead of leaving you to guess from a
generic error in the browser.

    export BHUVAN_TOKEN=...
    export SARVAM_API_KEY=...
    python scripts/check_live.py

Exit codes: 0 = everything configured works, 1 = something failed,
2 = nothing configured yet.
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from bhoomi.adapters.bhuvan import (  # noqa: E402
    BhuvanFacilityProvider,
    BhuvanLulc250kProvider,
    BhuvanPlaceResolver,
    BhuvanRouteProvider,
)
from bhoomi.adapters.http import HttpJsonClient  # noqa: E402
from bhoomi.adapters.sarvam import SarvamLanguageModel, SarvamSynthesizer  # noqa: E402
from bhoomi.config import Settings  # noqa: E402
from bhoomi.domain.errors import (  # noqa: E402
    BhoomiError,
    PlaceNotFoundError,
    UpstreamAuthError,
    UpstreamUnavailableError,
)
from bhoomi.domain.models import Coordinates  # noqa: E402

# A real village in Andhra Pradesh, the one Bhuvan's own documentation uses.
PROBE_POINT = Coordinates(lat=16.2794, lon=80.5884)
PROBE_PLACE = "sekuru"

results: list[tuple[str, str, str]] = []  # (capability, status, detail)


def record(capability: str, status: str, detail: str = "") -> None:
    results.append((capability, status, detail))
    mark = {"ok": "PASS", "fail": "FAIL", "skip": "SKIP"}[status]
    line = f"  {mark}  {capability}"
    if detail:
        line += f" — {detail}"
    print(line)


def explain(exc: Exception) -> str:
    if isinstance(exc, UpstreamAuthError):
        return f"token rejected: {exc}"
    if isinstance(exc, PlaceNotFoundError):
        return f"reachable, but no data: {exc}"
    if isinstance(exc, UpstreamUnavailableError):
        return f"service unreachable: {exc}"
    if isinstance(exc, BhoomiError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def check_bhuvan(settings: Settings) -> None:
    if not settings.bhuvan_token:
        for capability in (
            "Bhuvan village geocoding",
            "Bhuvan LULC statistics",
            "Bhuvan hospital/post office proximity",
            "Bhuvan routing",
        ):
            record(capability, "skip", "BHUVAN_TOKEN not set")
        return

    client = HttpJsonClient(
        settings.bhuvan_base_url,
        timeout_s=settings.http_timeout_s,
        max_retries=0,  # fail fast while diagnosing
    )
    token = settings.bhuvan_token
    try:
        village = BhuvanPlaceResolver(client, token).resolve(PROBE_PLACE)
        detail = f"resolved {village.label}"
        if village.population:
            detail += f", population {village.population:,}"
        record("Bhuvan village geocoding", "ok", detail)
    except Exception as exc:  # noqa: BLE001
        record("Bhuvan village geocoding", "fail", explain(exc))

    try:
        profile = BhuvanLulc250kProvider(client, token).profile_for(
            PROBE_POINT, radius_m=5000
        )
        top = profile.dominant()
        record(
            "Bhuvan LULC statistics",
            "ok",
            f"{profile.year}, {len(profile.classes)} classes"
            + (f", mostly {top.label}" if top else ""),
        )
    except Exception as exc:  # noqa: BLE001
        record("Bhuvan LULC statistics", "fail", explain(exc))

    try:
        found = BhuvanFacilityProvider(client, token).nearby(
            PROBE_POINT, radius_m=5000
        )
        record(
            "Bhuvan hospital/post office proximity",
            "ok",
            f"{len(found)} facilities nearby",
        )
    except Exception as exc:  # noqa: BLE001
        record("Bhuvan hospital/post office proximity", "fail", explain(exc))

    try:
        route = BhuvanRouteProvider(client, token).route(
            PROBE_POINT, Coordinates(lat=16.2841, lon=80.5921)
        )
        if route.distance_km is None:
            record("Bhuvan routing", "fail", "reachable, but no route returned")
        else:
            record("Bhuvan routing", "ok", f"{route.distance_km:.1f} km")
    except Exception as exc:  # noqa: BLE001
        record("Bhuvan routing", "fail", explain(exc))

    client.close()


def check_sarvam(settings: Settings) -> None:
    if not settings.sarvam_api_key:
        record("Sarvam chat (agent reasoning)", "skip", "SARVAM_API_KEY not set")
        record("Sarvam text-to-speech", "skip", "SARVAM_API_KEY not set")
        return

    client = HttpJsonClient(
        settings.sarvam_base_url,
        timeout_s=settings.http_timeout_s,
        max_retries=0,
        default_headers={"api-subscription-key": settings.sarvam_api_key},
    )
    try:
        from bhoomi.domain.messages import Message, Role

        turn = SarvamLanguageModel(client, model=settings.chat_model).respond(
            [Message(role=Role.USER, content="Reply with the single word: ready")], ()
        )
        reply = (turn.content or "").strip()
        record("Sarvam chat (agent reasoning)", "ok", f"{settings.chat_model} replied {reply[:40]!r}")
    except Exception as exc:  # noqa: BLE001
        record("Sarvam chat (agent reasoning)", "fail", explain(exc))

    try:
        audio = SarvamSynthesizer(client, model=settings.tts_model).synthesize(
            "Testing one two three.", language_code="en-IN"
        )
        record("Sarvam text-to-speech", "ok", f"{len(audio):,} bytes of audio")
    except Exception as exc:  # noqa: BLE001
        record("Sarvam text-to-speech", "fail", explain(exc))

    client.close()


def main() -> int:
    settings = Settings.from_env()
    print("Checking live credentials against the real services\n")

    check_bhuvan(settings)
    check_sarvam(settings)

    ok = [r for r in results if r[1] == "ok"]
    failed = [r for r in results if r[1] == "fail"]
    skipped = [r for r in results if r[1] == "skip"]

    print(f"\n{len(ok)} passed, {len(failed)} failed, {len(skipped)} skipped")

    if failed:
        print("\nWhat to fix:")
        for capability, _, detail in failed:
            print(f"  - {capability}: {detail}")
        if any("token rejected" in d for _, _, d in failed):
            print(
                "\n  Bhuvan tokens expire. Get a fresh one at\n"
                "  https://bhuvan-app1.nrsc.gov.in/api/ (log in, then 'Get Access Token').\n"
                "  Tokens are issued per theme, so select the themes you need."
            )
        return 1

    if ok and not skipped:
        print("\nEverything is live. Start the app and the badges should read")
        print("'live ISRO Bhuvan' and the chat model name, both in green.")
        print("Run it with:  BHOOMI_DATA_MODE=live python main.py")
        return 0

    if ok and skipped:
        print("\nPartly live: the capabilities marked SKIP will fall back to")
        print("sample data or the offline planner. Set the missing variable to")
        print("complete the picture.")
        return 0

    print("\nNothing configured yet. See .env.example, or read the README section")
    print("'Turning on live data'. The app still runs without any of this.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
