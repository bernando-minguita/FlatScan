"""Application entry point for FlatScan — perspective correction for ID cards and documents."""

from __future__ import annotations

import sys

from app.application import run


def main() -> int:
    """Start the desktop application and return its exit code."""

    return run()


if __name__ == "__main__":
    sys.exit(main())

