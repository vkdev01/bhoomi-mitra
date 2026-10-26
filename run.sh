#!/usr/bin/env bash
# Host entry point (Replit, containers). Ensures dependencies exist, then serves.
#
# Replit does not always run an install step for an imported repo, so this makes
# the app self-sufficient. pip is a no-op once the wheels are cached.
set -euo pipefail
cd "$(dirname "$0")"

python -m pip install --quiet --disable-pip-version-check -r requirements.txt
exec python main.py
