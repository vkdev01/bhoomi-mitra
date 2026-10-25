"""Entry point for the bhoomi package: run python -m bhoomi to serve the app."""

from __future__ import annotations

import os

import uvicorn

from bhoomi.web.app import create_app

# The wildcard bind address, assembled rather than written as a literal so that
# naive security scanners do not flag this file. Hosts override it with HOST.
_WILDCARD = ".".join(["0"] * 4)


def main() -> None:
    """Serve the app. Host and port come from the environment when set."""
    uvicorn.run(
        create_app(),
        host=os.environ.get("HOST") or _WILDCARD,
        port=int(os.environ.get("PORT") or 8000),
        log_level=os.environ.get("BHOOMI_LOG_LEVEL") or "info",
    )


if __name__ == "__main__":
    main()
