"""Run the actual 002 offline CLI against its default leaf-local fixtures."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_default_backtrader_alignment_cli_runs(tmp_path):
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "examples/backtest/002_hft_alignment_demo/run_backtrader.py"),
         "--strategy", "plain_grid", "--max-decisions", "500"],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert math.isfinite(payload["balance"])
    assert math.isfinite(payload["position"])
    assert payload["num_trades"] > 0
    assert payload["num_trades"] == len(payload["fills"])
    for fill in payload["fills"]:
        assert fill["side"] in {"buy", "sell"}
        for key in ("price", "size"):
            assert math.isfinite(fill[key]) and fill[key] > 0
