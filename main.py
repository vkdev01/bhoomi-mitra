"""Entry point that works without installing the package.

Replit (and any host) can run `python main.py` straight from a clone: this puts
``src/`` on the path and hands over to the package entry point. Installing with
``pip install -e .`` gives you the ``bhoomi`` console script instead.
"""

from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bhoomi.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
