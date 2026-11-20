#!/usr/bin/env python3
"""Regenerate tests/functional/strategies/.test_durations.json.

The committed durations file drives the per-file ``slow`` auto-marking in
``conftest.py`` (see docs/SLOW_TESTS_TODO.md TODO-9). The fast-tier cutoff
uses the same ``BT_SLOW_PERCENTILE`` setting as collection (default p35).
Measurements use the same worker count and per-test timeout as the Makefile
targets; workers default to four and can be set to zero for serial execution.

Run this after adding/removing strategy tests or when timings drift:

    python scripts/refresh_strategy_durations.py            # measure + write
    python scripts/refresh_strategy_durations.py --from-log /tmp/dur.log

``--from-log`` accepts only a complete successful ``pytest --durations=0``
console log with strategy duration rows. Failed, truncated, or unrelated logs
leave the committed duration snapshot untouched.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STRAT_REL = "tests/functional/strategies/"
OUT = REPO / "tests/functional/strategies/.test_durations.json"
DEFAULT_WORKERS = 4
DEFAULT_TEST_TIMEOUT_SECONDS = 300
PROCESS_TIMEOUT_SECONDS = 7200
DEFAULT_SLOW_PERCENTILE = 35.0

_LINE = re.compile(r"\s*([0-9.]+)s\s+(call|setup|teardown)\s+(\S+)")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SUMMARY_LINE = re.compile(
    r"^\s*=*\s*(.*?)\s+in\s+(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)s\s*=*\s*$"
)
_SUCCESS_COUNT = re.compile(r"\b[1-9][0-9,]*\s+(?:passed|skipped|xfailed|xpassed)\b")
_FAILURE_COUNT = re.compile(r"\b[1-9][0-9,]*\s+(?:failed|errors?)\b")


def parse_log(text: str) -> dict[str, float]:
    """Parse pytest --durations output into a dict of file -> total_seconds.

    Args:
        text: The stdout/stderr output from pytest --durations=0.

    Returns:
        Dict mapping test file paths to their total duration in seconds.
    """
    agg: dict[str, float] = defaultdict(float)
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        nid = m.group(3)
        if STRAT_REL in nid:
            try:
                duration = float(m.group(1))
            except ValueError as exc:
                raise ValueError("pytest log contains an invalid duration") from exc
            if not math.isfinite(duration) or duration < 0:
                raise ValueError("pytest log duration must be finite and non-negative")
            key = nid.split("::")[0]
            total = agg[key] + duration
            if not math.isfinite(total):
                raise ValueError("aggregated pytest duration must be finite")
            agg[key] = total
    return {k: round(v, 3) for k, v in sorted(agg.items())}


def validate_successful_pytest_log(text: str) -> None:
    """Require a completed, successful pytest terminal summary in the log."""
    clean = _ANSI_ESCAPE.sub("", text)
    summaries = []
    for index, line in enumerate(clean.splitlines()):
        match = _SUMMARY_LINE.match(line)
        if match is not None:
            summaries.append((index, match.group(1).strip()))
    if not summaries:
        raise ValueError("pytest log is incomplete: terminal summary is missing")
    nonempty_lines = [
        index for index, line in enumerate(clean.splitlines()) if line.strip()
    ]
    if not nonempty_lines or summaries[-1][0] != nonempty_lines[-1]:
        raise ValueError("pytest log has output after its terminal summary")
    if any(_FAILURE_COUNT.search(summary) for _index, summary in summaries):
        raise ValueError("pytest log reports failures or errors")
    if not _SUCCESS_COUNT.search(summaries[-1][1]):
        raise ValueError("pytest log has no successful test outcome in its final summary")


def parse_complete_log(text: str) -> dict[str, float]:
    """Parse durations only from a completed successful strategy pytest log."""
    validate_successful_pytest_log(text)
    data = parse_log(text)
    if not data:
        raise ValueError("pytest log contains no strategy duration records")
    return data


def configured_percentile() -> float:
    """Return the collection-time slow percentile, including its fallback."""
    try:
        percentile = float(os.environ.get("BT_SLOW_PERCENTILE", "35"))
    except ValueError:
        percentile = DEFAULT_SLOW_PERCENTILE
    if not math.isfinite(percentile):
        raise ValueError("BT_SLOW_PERCENTILE must be finite")
    return min(max(percentile, 0.0), 100.0)


def percentile_threshold(values, percentile: float) -> float | None:
    """Match conftest's linear-interpolated threshold for a duration list."""
    if not math.isfinite(float(percentile)):
        raise ValueError("slow percentile must be finite")
    percentile = min(max(float(percentile), 0.0), 100.0)
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = (percentile / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    fraction = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * fraction


def pytest_command() -> list[str]:
    """Build the same worker/watchdog profile used by the Makefile lanes."""
    try:
        workers = int(os.environ.get("BT_TEST_WORKERS", str(DEFAULT_WORKERS)))
        test_timeout = int(os.environ.get(
            "BT_TEST_TIMEOUT", str(DEFAULT_TEST_TIMEOUT_SECONDS)))
    except ValueError as exc:
        raise ValueError("BT_TEST_WORKERS and BT_TEST_TIMEOUT must be integers") from exc
    if workers < 0 or test_timeout <= 0:
        raise ValueError("BT_TEST_WORKERS must be >= 0 and BT_TEST_TIMEOUT > 0")
    return [
        sys.executable, "-m", "pytest",
        "tests/functional/strategies",
        "--durations=0", f"--timeout={test_timeout}",
        "-n", str(workers), "-q",
        "-p", "no:cacheprovider",
    ]


def run_pytest(cmd: list[str], timeout_seconds: float = PROCESS_TIMEOUT_SECONDS):
    """Run pytest with a hard wall-clock bound in addition to per-test timeout."""
    return subprocess.run(
        cmd, cwd=str(REPO), capture_output=True, text=True,
        timeout=timeout_seconds,
    )


def _captured_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def measure() -> dict[str, float]:
    """Run the strategy suite with the standard profile and parse durations."""
    try:
        cmd = pytest_command()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return {}
    print("Running:", " ".join(cmd), flush=True)
    try:
        proc = run_pytest(cmd)
    except subprocess.TimeoutExpired as exc:
        partial = _captured_text(exc.stdout) + _captured_text(exc.stderr)
        print(
            f"ERROR: strategy pytest exceeded the {PROCESS_TIMEOUT_SECONDS}s process limit; "
            f"captured {len(partial)} characters and kept the existing durations file.",
            file=sys.stderr,
        )
        return {}
    output = proc.stdout + proc.stderr
    print(f"pytest exit code: {proc.returncode}")
    if proc.returncode != 0:
        print("ERROR: pytest failed; kept the existing durations file.", file=sys.stderr)
        return {}
    try:
        return parse_complete_log(output)
    except ValueError as exc:
        print(f"ERROR: {exc}; kept the existing durations file.", file=sys.stderr)
        return {}


def write_durations_atomically(data: dict[str, float]) -> None:
    """Replace the duration snapshot from a fully written same-directory temp."""
    if not data or any(not math.isfinite(float(value)) or value < 0 for value in data.values()):
        raise ValueError("duration snapshot must contain finite non-negative values")
    payload = json.dumps(data, indent=0, sort_keys=True, allow_nan=False)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    mode = (OUT.stat().st_mode & 0o777) if OUT.exists() else 0o644
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".test_durations.",
            suffix=".tmp",
            dir=str(OUT.parent),
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.chmod(str(temp_path), mode)
        os.replace(str(temp_path), str(OUT))
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def main() -> int:
    """Regenerate the test durations JSON file.

    Returns:
        int: Exit code (0 for success, 1 for error).
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-log", type=Path, default=None,
                    help="Parse an existing pytest --durations log instead of re-running.")
    args = ap.parse_args()

    try:
        if args.from_log is not None:
            data = parse_complete_log(args.from_log.read_text(encoding="utf-8"))
        else:
            data = measure()
        vals = sorted(data.values())
        percentile = configured_percentile()
        threshold = percentile_threshold(vals, percentile)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}; kept existing durations file.", file=sys.stderr)
        return 1

    if not data or threshold is None:
        print("ERROR: no strategy durations parsed; aborting (kept existing file).", file=sys.stderr)
        return 1

    slow_count = sum(value >= threshold for value in vals)
    try:
        write_durations_atomically(data)
    except OSError as exc:
        print(f"ERROR: could not replace durations file: {exc}; kept existing file.",
              file=sys.stderr)
        return 1
    print(f"Wrote {OUT} with {len(data)} files; p{percentile:g}="
          f"{threshold:.2f}s ({slow_count} files at/above the slow threshold).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
