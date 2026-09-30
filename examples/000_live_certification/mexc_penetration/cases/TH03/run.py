"""Run only the TH03 strict live certification case for mexc."""

from __future__ import annotations

import sys
from pathlib import Path


CASE_DIR = Path(__file__).resolve().parent
VENUE_ROOT = CASE_DIR.parents[1]
for local_path in (str(CASE_DIR), str(VENUE_ROOT)):
    if local_path not in sys.path:
        sys.path.insert(0, local_path)

from TH03_strategy import CASE_ID, CASE_SPEC, PROOF_FIELDS  # noqa: E402
from _certification.cli import run_case_cli  # noqa: E402


if CASE_DIR.name != CASE_ID:
    raise RuntimeError("case entry point and directory name differ")


if __name__ == "__main__":
    raise SystemExit(run_case_cli('mexc', CASE_ID, CASE_SPEC, PROOF_FIELDS))
