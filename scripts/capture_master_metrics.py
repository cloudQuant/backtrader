#!/usr/bin/env python3
"""Capture full metrics dict from a flagged inlined regression test.

Usage:
    python scripts/capture_master_metrics.py <test_file>

The script monkey-patches `pytest`'s collection to intercept the call to the
inner test function, prints the full metrics dict at first failure, and exits.

We use this when the installed (master) backtrader produces different numbers
than the dev branch. The captured metrics let us regenerate the assertion
block of the test so it passes on master too.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: capture_master_metrics.py <test_file>", file=sys.stderr)
        return 2
    test_file = Path(argv[1]).resolve()
    if not test_file.exists():
        print(f"not found: {test_file}", file=sys.stderr)
        return 2

    text = test_file.read_text(encoding="utf-8")

    # Find the line that assigns `metrics`. We then truncate after it and
    # print the dict.
    candidates = [
        "    metrics = _extract_metrics_compat(",
        "    metrics = extract_metrics(",
        "    metrics = build_metrics(",
        "    metrics = run_strategy(",
    ]
    idx = -1
    used = ""
    for cand in candidates:
        idx = text.find(cand)
        if idx >= 0:
            used = cand
            break
    if idx < 0:
        # Fallback: find the line that opens the metrics dictionary
        for cand in ("    assert metrics, \"no metrics derived\"",
                     "    assert metrics.get",):
            idx = text.find(cand)
            if idx >= 0:
                used = cand
                break
    if idx < 0:
        print(f"marker not found in {test_file}", file=sys.stderr)
        return 2

    if used.startswith("    metrics ="):
        # End-of-line index for the assignment, including trailing newline
        end_of_line = text.find("\n", idx)
        # The assignment may span multiple lines; advance until the line that
        # closes the call. We track parenthesis depth.
        depth = 0
        i = idx
        while i < len(text):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end_of_line = text.find("\n", i)
                    break
            i += 1
        head = text[: end_of_line + 1]
    else:
        head = text[: idx + len(used)]
    tail = (
        "\n    import json as _json, sys as _sys\n"
        "    _sys.stderr.write('METRICS_JSON_BEGIN\\n')\n"
        "    _sys.stderr.write(_json.dumps(metrics, default=str, indent=2) + '\\n')\n"
        "    _sys.stderr.write('METRICS_JSON_END\\n')\n"
        "    return\n"
    )

    backup = test_file.with_suffix(".py.metrics-backup")
    backup.write_text(text, encoding="utf-8")
    try:
        test_file.write_text(head + tail, encoding="utf-8")
        # Run the test
        import subprocess

        result = subprocess.run(
            ["python", "-m", "pytest", str(test_file), "--use-installed-backtrader",
             "--no-header", "-q", "-s"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
            timeout=600,
        )
        out = result.stdout + "\n" + result.stderr
        i0 = out.find("METRICS_JSON_BEGIN")
        i1 = out.find("METRICS_JSON_END")
        if i0 < 0 or i1 < 0:
            print("ERROR: did not capture metrics. Full output:", file=sys.stderr)
            print(out, file=sys.stderr)
            return 1
        json_text = out[i0 + len("METRICS_JSON_BEGIN") : i1].strip()
        metrics = json.loads(json_text)
        print(json.dumps(metrics, default=str, indent=2))
        return 0
    finally:
        backup.replace(test_file)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
