#!/usr/bin/env python3
"""Branch-compare runner for mean_reversion/test_0208_1161_universal_investor."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BC_LOCAL = _HERE.parent
_BC_FROM_ROOT = (
    Path(os.environ["BT_BRANCH_COMPARE_DATA_ROOT"]) / "studies" / "branch_compare"
    if os.environ.get("BT_BRANCH_COMPARE_DATA_ROOT")
    else None
)
for cand in (_BC_LOCAL, _BC_FROM_ROOT):
    if cand and (cand / "_common.py").exists():
        if str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
        break

from _common import main_for_test  # noqa: E402

_DATA_ROOT = os.environ.get("BT_BRANCH_COMPARE_DATA_ROOT")
REPO = Path(_DATA_ROOT) if _DATA_ROOT else _HERE.parents[2]
TEST_FILE = (
    REPO
    / "tests/functional/strategies/mean_reversion/test_0208_1161_universal_investor.py"
)


if __name__ == "__main__":
    raise SystemExit(main_for_test(TEST_FILE))
