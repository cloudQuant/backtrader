#!/usr/bin/env python3
"""Branch-compare runner for trend_following/test_0194_0417_fx_chaos_scalp."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# Resolve the shared _common module: prefer a sibling copy (when run from
# the canonical repo), else fall back to the data-root override (when run
# inside a temporary master worktree where _common.py was not copied).
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

# Resolve the test file: prefer the data-root override (so master worktree
# uses the dev test code), else use the current repo's path.
_DATA_ROOT = os.environ.get("BT_BRANCH_COMPARE_DATA_ROOT")
if _DATA_ROOT:
    REPO = Path(_DATA_ROOT)
else:
    REPO = _HERE.parents[2]
TEST_FILE = (
    REPO
    / "tests/functional/strategies/trend_following/test_0194_0417_fx_chaos_scalp.py"
)


if __name__ == "__main__":
    raise SystemExit(main_for_test(TEST_FILE))
