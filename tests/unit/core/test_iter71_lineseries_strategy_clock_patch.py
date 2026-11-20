"""Keep lineseries' legacy clock patch explicit instead of import-time."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


_IMPORT_PROBE = r'''
import sys

patch_calls = []

def trace_import(frame, event, _arg):
    if (
        event == "call"
        and frame.f_globals.get("__name__") == "backtrader.lineseries"
        and frame.f_code.co_name == "_patch_strategy_clk_update"
    ):
        patch_calls.append(frame.f_code.co_firstlineno)
    if frame.f_globals.get("__name__") == "backtrader.lineseries":
        return trace_import
    return None

sys.settrace(trace_import)
import backtrader
sys.settrace(None)

from backtrader.strategy import Strategy
import backtrader.lineseries as lineseries

assert patch_calls == [], patch_calls
strategy_clock_update = Strategy._clk_update
assert strategy_clock_update.__code__.co_filename.endswith("strategy.py")
assert lineseries._patch_strategy_clk_update() is True
assert Strategy._clk_update is not strategy_clock_update
assert Strategy._clk_update.__code__.co_filename.endswith("lineseries.py")
'''


@pytest.mark.parametrize("light_import", (False, True), ids=("default", "light"))
def test_fresh_package_import_keeps_strategy_clock_patch_explicit(light_import):
    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    if light_import:
        env["BACKTRADER_LIGHT_IMPORT"] = "1"
    else:
        env.pop("BACKTRADER_LIGHT_IMPORT", None)

    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
