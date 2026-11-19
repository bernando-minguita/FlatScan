"""Run each test file in its own process with a hard timeout.

Why this exists: the GUI tests create Qt worker threads that can outlive the
interpreter on Windows. A plain `python -m pytest tests` therefore prints its
summary and then appears to hang, which is confusing locally and fatal in CI.
Running one file per process with a timeout keeps results deterministic.

Usage:
    python tools/run_tests.py                # every tests/test_*.py
    python tools/run_tests.py tests/test_export.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_SECONDS = 300


def main(argv: list[str]) -> int:
    os.chdir(ROOT)
    files = argv or sorted(str(p) for p in Path("tests").glob("test_*.py"))
    if not files:
        print("No test files found.")
        return 1

    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    log: list[str] = []
    failures = 0
    for path in files:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(path),
                    "--tb=short",
                    "-p",
                    "no:cacheprovider",
                ],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                env=env,
            )
            tail = (result.stdout + result.stderr).strip().splitlines()[-8:]
            entry = f"=== {path} EXIT={result.returncode}\n" + "\n".join(tail)
            if result.returncode != 0:
                failures += 1
        except subprocess.TimeoutExpired:
            entry = f"=== {path} TIMEOUT after {TIMEOUT_SECONDS}s"
            failures += 1
        log.append(entry)
        print(entry, flush=True)

    Path("pytest_out.txt").write_text("\n\n".join(log), encoding="utf-8")
    print(f"\n{len(files) - failures}/{len(files)} test files passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
