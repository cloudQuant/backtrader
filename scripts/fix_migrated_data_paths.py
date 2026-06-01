#!/usr/bin/env python3
"""Fix data path resolution in migrated regression run.py files.

Three patterns to fix:

  Pattern A — `Path(__file__).parent.parent.parent.parent / 'datas' / X`
              originally pointed to tests/functional/datas/ when the strategy lived
              at tests/functional/strategies_regression/<cat>/<name>/. After migration
              to tests/functional/strategies/<cat>/regression/<name>/, this resolves
              to tests/functional/strategies/<cat>/datas/ which doesn't exist.

  Pattern B — `BASE_DIR.parents[2] / 'datas' / X` — same issue.

  Pattern C — `BASE_DIR.parent.parent.parent / 'datas' / X` (3 ups) — points to
              tests/functional/strategies/datas/ which doesn't exist.

Fix: replace each pattern with a direct reference to the public test data dir,
computed as `Path(__file__).resolve().parents[6] / 'tests' / 'datas'`.

Layout:
  parents[0] = <name>/
  parents[1] = regression/
  parents[2] = <cat>/
  parents[3] = strategies/
  parents[4] = functional/
  parents[5] = tests/
  parents[6] = repo root
  parents[6] / 'tests' / 'datas' = the public data dir.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / "tests" / "functional" / "strategies"

# Replacement target — the new public data dir.
NEW_DATA_PREFIX = (
    "Path(__file__).resolve().parents[6] / 'tests' / 'datas'"
)

PATTERNS = [
    # Pattern A: Path(__file__).parent.parent.parent.parent / 'datas'
    (
        re.compile(r"Path\(__file__\)\.parent\.parent\.parent\.parent / 'datas'"),
        NEW_DATA_PREFIX,
    ),
    # Pattern B: BASE_DIR.parents[2] / 'datas'
    (
        re.compile(r"BASE_DIR\.parents\[2\] / 'datas'"),
        NEW_DATA_PREFIX,
    ),
    # Pattern C: BASE_DIR.parent.parent.parent / 'datas'
    (
        re.compile(r"BASE_DIR\.parent\.parent\.parent / 'datas'"),
        NEW_DATA_PREFIX,
    ),
]


def fix_file(path: Path) -> bool:
    """Apply pattern fixes; return True if any fix was applied."""
    src = path.read_text(encoding="utf-8")
    new = src
    for pat, repl in PATTERNS:
        new = pat.sub(repl, new)
    if new != src:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def main() -> int:
    fixed = []
    for run_py in ROOT.glob("*/regression/*/run.py"):
        if fix_file(run_py):
            fixed.append(run_py.relative_to(REPO).as_posix())
    print(f"Fixed {len(fixed)} files:")
    for p in fixed:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
