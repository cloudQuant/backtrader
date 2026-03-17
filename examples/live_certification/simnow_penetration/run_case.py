#!/usr/bin/env python
"""Run one or more SimNow penetration certification cases in isolated subprocesses.

Usage
-----
    # Run a single case
    python run_case.py C01

    # Run several cases
    python run_case.py C01 T01 T02 T03

    # Run ALL cases (sequential)
    python run_case.py --all

    # Specify custom report directory
    python run_case.py C01 --report-root ./my_reports
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_SUITE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SUITE_DIR.parents[2]
_CASES_DIR = _SUITE_DIR / "cases"

# ---------------------------------------------------------------------------
# Case registry: maps case_id -> case file
# ---------------------------------------------------------------------------

CASE_REGISTRY: dict[str, Path] = {}


def _discover_cases():
    """Scan cases/ directory and build {case_id: path} registry."""
    for p in sorted(_CASES_DIR.glob("*.py")):
        if p.name.startswith("_") or p.name == "__init__.py":
            continue
        # Extract case_id from filename, e.g. C01_connect_and_login.py -> C01
        case_id = p.stem.split("_", 1)[0]
        CASE_REGISTRY[case_id] = p


_discover_cases()

# Ordered list following the spec sequence
CASE_ORDER = [
    "C01",
    "T01", "T02", "T03",
    "M01", "M02", "M03", "M04", "M05",
    "O01", "O02", "O03",
    "TH01", "TH02", "TH03", "TH04", "TH05", "TH06",
    "V01", "V02", "V03",
    "E01", "E02", "E03",
    "EM01", "EM02", "EM03",
    "B01", "B02",
    "L01", "L02", "L03", "L04",
]

# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 180


def run_case(case_id: str, report_root: Path, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run a single case in an isolated subprocess, return result dict."""
    case_file = CASE_REGISTRY.get(case_id)
    if case_file is None:
        print(f"[ERROR] Unknown case: {case_id}")
        print(f"  Available: {', '.join(sorted(CASE_REGISTRY))}")
        return {"case_id": case_id, "status": "FAIL", "failure_reason": "Unknown case_id"}

    report_dir = report_root / case_id
    report_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-u", str(case_file),
        "--report-dir", str(report_dir),
    ]

    print(f"\n{'='*60}")
    print(f"  Running {case_id}: {case_file.stem}")
    print(f"  Report -> {report_dir}")
    print(f"{'='*60}")

    try:
        completed = subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] {case_id} exceeded {timeout}s")
        return {"case_id": case_id, "status": "BLOCKED", "failure_reason": f"Timeout {timeout}s"}

    # Relay output
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)

    # Read result.json if available
    result_path = report_dir / "result.json"
    if result_path.exists():
        with open(result_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    # Fallback
    status = {0: "PASS", 1: "FAIL", 2: "BLOCKED"}.get(completed.returncode, "FAIL")
    return {"case_id": case_id, "status": status, "failure_reason": f"exit_code={completed.returncode}"}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary(results: list[dict], report_root: Path):
    """Print and save a summary table."""
    print(f"\n{'='*60}")
    print("  CERTIFICATION SUMMARY")
    print(f"{'='*60}\n")

    pass_count = sum(1 for r in results if r.get("status") == "PASS")
    fail_count = sum(1 for r in results if r.get("status") == "FAIL")
    blocked_count = sum(1 for r in results if r.get("status") == "BLOCKED")

    for r in results:
        status = r.get("status", "?")
        case_id = r.get("case_id", "?")
        reason = r.get("failure_reason", "")
        icon = {"PASS": "✓", "FAIL": "✗", "BLOCKED": "◉"}.get(status, "?")
        line = f"  {icon} [{status:7s}] {case_id}"
        if reason:
            line += f"  -- {reason[:80]}"
        print(line)

    print(f"\n  Total: {len(results)}  PASS: {pass_count}  FAIL: {fail_count}  BLOCKED: {blocked_count}")

    # Save summary JSON
    summary_path = report_root / "summary.json"
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total": len(results),
        "pass": pass_count,
        "fail": fail_count,
        "blocked": blocked_count,
        "results": results,
    }
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(f"\n  Summary saved -> {summary_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Run SimNow penetration certification cases",
    )
    parser.add_argument(
        "cases", nargs="*",
        help="Case IDs to run (e.g. C01 T01). Omit for --all.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run all 33 cases in spec order",
    )
    parser.add_argument(
        "--report-root", default="",
        help="Root directory for reports (default: reports/latest)",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"Per-case timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_cases",
        help="List all available cases and exit",
    )
    args = parser.parse_args()

    if args.list_cases:
        print("Available cases:")
        for cid in CASE_ORDER:
            path = CASE_REGISTRY.get(cid)
            tag = " (not found)" if path is None else ""
            print(f"  {cid}: {path.stem if path else '?'}{tag}")
        return

    report_root = (
        Path(args.report_root) if args.report_root
        else _SUITE_DIR / "reports" / "latest"
    )
    report_root.mkdir(parents=True, exist_ok=True)

    case_ids = CASE_ORDER if args.all else args.cases
    if not case_ids:
        parser.print_help()
        return

    results = []
    for cid in case_ids:
        result = run_case(cid, report_root, timeout=args.timeout)
        results.append(result)

    print_summary(results, report_root)


if __name__ == "__main__":
    main()
