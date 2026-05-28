#!/usr/bin/env python3
"""Refactor tests/functional/strategies/ tests to parametrize runonce flag.

Transforms each test file so that the test function:
  1. Imports pytest (if not already)
  2. Is decorated with @pytest.mark.parametrize("runonce", [True, False])
  3. Accepts `runonce` parameter
  4. Replaces `cerebro.run(...)` with `cerebro.run(runonce=runonce, ...)` (preserving other kwargs)

Idempotent: re-running on already-transformed files leaves them unchanged.

Usage:
    python3 scripts/parametrize_runonce_tests.py            # dry run
    python3 scripts/parametrize_runonce_tests.py --apply    # actually write
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = REPO_ROOT / "tests" / "functional" / "strategies"


# Match imports of backtrader (we want to insert pytest near the top, after backtrader)
RE_TEST_DEF = re.compile(r"^def (test_[A-Za-z0-9_]+)\(([^)]*)\)\s*:\s*$", re.MULTILINE)
RE_PYTEST_IMPORT = re.compile(r"^(import pytest|from pytest)\b", re.MULTILINE)
RE_PARAMETRIZE = re.compile(r"@pytest\.mark\.parametrize\([\"']runonce[\"']")
# Match cerebro.run( — handle both `cerebro.run()` and `cerebro.run(args)` and any object name like `self.cerebro.run(`
RE_CEREBRO_RUN = re.compile(r"(\b\w+(?:\.\w+)*\.run)\(([^)]*)\)")


def transform_file(path: Path) -> tuple[bool, str, list[str]]:
    """Transform a single test file. Returns (changed, new_content, notes)."""
    notes: list[str] = []
    src = path.read_text(encoding="utf-8")
    original = src

    # Skip if already transformed
    if RE_PARAMETRIZE.search(src):
        return False, src, ["already parametrized — skipped"]

    # Find test function. Each file has exactly one per analysis.
    matches = list(RE_TEST_DEF.finditer(src))
    if not matches:
        return False, src, ["no test_xxx() function found — skipped"]
    if len(matches) > 1:
        return False, src, [f"multiple test functions found ({len(matches)}) — skipped, requires manual review"]

    m = matches[0]
    func_name = m.group(1)
    existing_params = m.group(2).strip()
    notes.append(f"function: {func_name}({existing_params})")

    # 1. Add `import pytest` if missing — insert after first import block
    if not RE_PYTEST_IMPORT.search(src):
        # Insert right after "import backtrader as bt" or last `^import ` / `^from ` line
        import_lines = list(re.finditer(r"^(?:import|from) [^\n]+\n", src, re.MULTILINE))
        if import_lines:
            last_import = import_lines[-1]
            insert_pos = last_import.end()
            src = src[:insert_pos] + "import pytest\n" + src[insert_pos:]
            notes.append("added: import pytest")
        else:
            notes.append("WARN: no import block found")

    # Re-locate the test function after potential insertion
    matches = list(RE_TEST_DEF.finditer(src))
    if not matches:
        return False, src, notes + ["WARN: lost test function after import insert"]
    m = matches[0]

    # 2. Replace `def test_xxx(...):` with parametrize decorator + `def test_xxx(runonce, ...):`
    decorator = '@pytest.mark.parametrize("runonce", [True, False])\n'
    if existing_params:
        new_def = f"def {func_name}(runonce, {existing_params}):"
    else:
        new_def = f"def {func_name}(runonce):"
    src = src[:m.start()] + decorator + new_def + src[m.end():]
    notes.append("added: @pytest.mark.parametrize and runonce param")

    # 3. Replace `cerebro.run(...)` calls — inject runonce=runonce as the FIRST kwarg
    def repl(match: re.Match) -> str:
        head = match.group(1)  # e.g. "cerebro.run"
        args = match.group(2).strip()
        if args:
            return f"{head}(runonce=runonce, {args})"
        return f"{head}(runonce=runonce)"

    new_src, n_replaced = RE_CEREBRO_RUN.subn(repl, src)
    # Filter: only count actual cerebro-style runs by inspecting matches —
    # simple heuristic: most files have exactly one `cerebro.run(...)`. Other `.run(`
    # calls (e.g. `subprocess.run`) are extremely unlikely in these strategy tests.
    src = new_src
    notes.append(f"replaced .run(...) calls: {n_replaced}")

    if n_replaced == 0:
        return False, original, notes + ["WARN: no .run(...) replaced — reverting"]

    return True, src, notes


def main() -> int:
    apply = "--apply" in sys.argv

    files = sorted(TARGET_DIR.rglob("test_*.py"))
    print(f"Found {len(files)} test files in {TARGET_DIR.relative_to(REPO_ROOT)}")
    print()

    summary = {"changed": 0, "skipped": 0, "warnings": 0}
    for path in files:
        rel = path.relative_to(REPO_ROOT)
        changed, new_content, notes = transform_file(path)
        warn = any("WARN" in n for n in notes)
        if warn:
            summary["warnings"] += 1
            print(f"⚠️  {rel}")
            for n in notes:
                print(f"      {n}")
        elif changed:
            summary["changed"] += 1
            if apply:
                path.write_text(new_content, encoding="utf-8")
                print(f"✓  {rel}")
            else:
                print(f"·  {rel}  (would change)")
        else:
            summary["skipped"] += 1

    print()
    print(f"Summary: {summary['changed']} changed, "
          f"{summary['skipped']} skipped, "
          f"{summary['warnings']} warnings")
    if not apply:
        print("DRY RUN — re-run with --apply to write changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
