#!/usr/bin/env python3
"""Flatten tests/functional/strategies/<cat>/regression/<NNNN_name>/ tests up to <cat>/.

Moves test_*.py and any sibling auxiliary files (backtest_result.json, etc.) up
one level, then renames test files to test_<NNNN>_<name>.py using the folder's
4-digit numeric prefix.

Also rewrites every `parents[6]` literal to `parents[4]` because the file moves
two directories shallower.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STRATEGIES = REPO / "tests" / "functional" / "strategies"


def main() -> int:
    moved = 0
    skipped: list[str] = []
    folder_pattern = re.compile(r"^(\d{4})_(.+)$")

    for cat_dir in sorted(STRATEGIES.iterdir()):
        if not cat_dir.is_dir():
            continue
        regression_dir = cat_dir / "regression"
        if not regression_dir.exists() or not regression_dir.is_dir():
            continue

        for sub in sorted(regression_dir.iterdir()):
            if not sub.is_dir():
                continue
            if sub.name.startswith("__"):
                continue

            match = folder_pattern.match(sub.name)
            if not match:
                skipped.append(f"unmatched folder name: {sub}")
                continue
            number, name_part = match.group(1), match.group(2)

            # Find the single test_*.py file inside
            test_files = [p for p in sub.glob("test_*.py")]
            if len(test_files) != 1:
                skipped.append(f"expected exactly one test file in {sub}, got {len(test_files)}")
                continue
            test_src = test_files[0]

            # Auxiliary files (everything except __init__.py, __pycache__, the test file)
            aux_files = [
                p for p in sub.iterdir()
                if p != test_src
                and p.name not in {"__init__.py", "__pycache__"}
                and not p.name.endswith(".pyc")
            ]

            # New target test path
            new_test_name = f"test_{number}_{name_part}.py"
            new_test_path = cat_dir / new_test_name
            if new_test_path.exists():
                skipped.append(f"target already exists: {new_test_path}")
                continue

            # Read, patch parents[6] -> parents[4], write to new location
            text = test_src.read_text(encoding="utf-8")
            patched = text.replace("parents[6]", "parents[4]")
            new_test_path.write_text(patched, encoding="utf-8")

            # Move auxiliary files to category dir, prefix with the same number+name
            # to avoid collisions (e.g. backtest_result.json from each strategy)
            for aux in aux_files:
                if aux.is_dir():
                    new_aux = cat_dir / f"{number}_{name_part}_{aux.name}"
                    if new_aux.exists():
                        shutil.rmtree(new_aux)
                    shutil.move(str(aux), str(new_aux))
                else:
                    new_aux = cat_dir / f"{number}_{name_part}_{aux.name}"
                    if new_aux.exists():
                        new_aux.unlink()
                    shutil.move(str(aux), str(new_aux))

            # Remove source dir (now contains only __init__.py and __pycache__)
            shutil.rmtree(sub)
            moved += 1

        # Clean up empty regression directory if no subdirs remain
        leftover = [p for p in regression_dir.iterdir() if p.name != "__pycache__"]
        if all(p.name == "__init__.py" for p in leftover):
            shutil.rmtree(regression_dir)

    print(f"Moved {moved} tests")
    if skipped:
        print(f"Skipped {len(skipped)} entries:")
        for s in skipped:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
