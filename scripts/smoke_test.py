#!/usr/bin/env python3
"""End-to-end smoke test against a real running server.

Boots uvicorn on a free port, exercises the public HTTP surface, prints a short
report, and exits non-zero if anything is wrong. Used locally and on Replit to
prove the app actually serves, not just that the units pass.

    python scripts/smoke_test.py [--port 8009] [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

CHECKS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")


def free_port(preferred: int) -> int:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


def wait_until_up(base: str, timeout_s: float = 45.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.4)
    return False


def request(base: str, path: str, payload: dict | None = None):
    url = f"{base}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode()
            return response.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8009)
    parser.add_argument("--keep", action="store_true", help="leave the server running")
    args = parser.parse_args()

    port = free_port(args.port)
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "BHOOMI_DATA_MODE": os.environ.get("BHOOMI_DATA_MODE", "auto")}

    print(f"Starting server on {base} (BHOOMI_DATA_MODE={env['BHOOMI_DATA_MODE']})")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "bhoomi.web.app:create_app",
         "--factory", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        if not wait_until_up(base):
            out = ""
            if proc.poll() is not None:
                out = (proc.stdout.read() if proc.stdout else "")[-1500:]
            record("server boots", False, out or "timed out")
            return 1
        record("server boots", True, base)

        status, body = request(base, "/health")
        record("/health returns 200", status == 200, f"status={status}")
        data_source = json.loads(body).get("data_source", "?") if status == 200 else "?"

        status, body = request(base, "/api/config")
        config = json.loads(body) if status == 200 else {}
        record("/api/config returns 200", status == 200, f"geo={config.get('geo_source')}")
        record(
            "config exposes no secret",
            "api_key" not in body.lower() and "token" not in body.lower(),
        )

        status, body = request(base, "/")
        record("index page served", status == 200 and "Bhoomi Mitra" in body)

        status, body = request(base, "/openapi.json")
        record("OpenAPI schema published", status == 200)

        status, body = request(base, "/api/village/report",
                               {"place": "Sekuru", "radius_m": 20000})
        report = json.loads(body) if status == 200 else {}
        record("village report returns 200", status == 200, f"status={status}")
        record(
            "report carries a village",
            bool(report.get("village", {}).get("name")),
            str(report.get("village", {}).get("name")),
        )
        record(
            "report carries land cover",
            bool(report.get("land_cover", {}).get("classes")),
            f"{len(report.get('land_cover', {}).get('classes', []))} classes",
        )
        record(
            "report carries facilities",
            bool(report.get("facilities")),
            f"{len(report.get('facilities', []))} found",
        )

        status, body = request(base, "/api/assistant/ask",
                               {"question": "Tell me about Sekuru and the nearest hospital",
                                "language_code": "en-IN"})
        answer = json.loads(body) if status == 200 else {}
        record("assistant returns 200", status == 200, f"status={status}")
        record("assistant produced an answer", bool(answer.get("answer")))
        record(
            "assistant used tools",
            len(answer.get("tool_trace", [])) > 0,
            ", ".join(t["name"] for t in answer.get("tool_trace", [])),
        )
        print(f"\n  sample answer: {answer.get('answer', '')[:220]}")

        status, body = request(base, "/api/village/report", {"place": "Atlantis"})
        record("unknown place maps to 404", status == 404, f"status={status}")

        status, body = request(base, "/api/village/report", {"radius_m": 100})
        record("missing location maps to 422", status == 422, f"status={status}")

        if args.keep:
            print(f"\nServer left running at {base} (pid {proc.pid})")
            return 0
    finally:
        if not args.keep:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    failed = [name for name, ok, _ in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed "
          f"(data source: {data_source})")
    if failed:
        print("failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
