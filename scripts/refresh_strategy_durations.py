#!/usr/bin/env python3
"""Regenerate tests/functional/strategies/.test_durations.json.

The committed durations file drives the per-file ``slow`` auto-marking in
``conftest.py`` (see docs/SLOW_TESTS_TODO.md TODO-9). A strategy test file
whose recorded duration is at/above the configured percentile (default p50,
i.e. the slowest ~50%) is tagged ``slow`` and skipped by ``make test-fast``.

Run this after adding/removing strategy tests or when timings drift:

    python scripts/refresh_strategy_durations.py            # measure + write
    python scripts/refresh_strategy_durations.py --from-log /tmp/dur.log

``--from-log`` parses an existing ``pytest --durations=0`` log instead of
re-running the suite.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STRAT_REL = "tests/functional/strategies/"
OUT = REPO / "tests/functional/strategies/.test_durations.json"

_LINE = re.compile(r"\s*([0-9.]+)s\s+(call|setup|teardown)\s+(\S+)")


def parse_log(text: str) -> dict[str, float]:
    agg: dict[str, float] = defaultdict(float)
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        nid = m.group(3)
        if STRAT_REL in nid:
            agg[nid.split("::")[0]] += float(m.group(1))
    return {k: round(v, 3) for k, v in sorted(agg.items())}


def measure() -> dict[str, float]:
    """Run the strategy suite once with --durations=0 and parse the output."""
    with tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False) as tmp:
        log_path = tmp.name
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/functional/strategies",
        "--durations=0", "-n", "8", "-q",
        "-p", "no:cacheprovider",
    ]
    print("Running:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    Path(log_path).write_text(proc.stdout + proc.stderr, encoding="utf-8")
    print(f"pytest exit code: {proc.returncode} (durations captured regardless)")
    return parse_log(proc.stdout + proc.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-log", type=Path, default=None,
                    help="Parse an existing pytest --durations log instead of re-running.")
    args = ap.parse_args()

    if args.from_log is not None:
        data = parse_log(args.from_log.read_text(encoding="utf-8"))
    else:
        data = measure()

    if not data:
        print("ERROR: no strategy durations parsed; aborting (kept existing file).", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=0, sort_keys=True), encoding="utf-8")
    vals = sorted(data.values())
    median = vals[len(vals) // 2]
    print(f"Wrote {OUT} with {len(data)} files; median={median:.2f}s "
          f"(files >= median are tagged slow by default).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
