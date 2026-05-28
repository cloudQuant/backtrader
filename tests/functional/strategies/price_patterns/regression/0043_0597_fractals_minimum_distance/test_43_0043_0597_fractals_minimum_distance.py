from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path


CATEGORY = "price_patterns"
STRATEGY_NAME = "0043_0597_fractals_minimum_distance"
STRATEGY_INDEX = "43"
TIMEOUT_SEC = 180

TEST_DIR = Path(__file__).parent.resolve()
STRATEGY_DIR = TEST_DIR
RUN_PY = STRATEGY_DIR / "run.py"
SOURCE_RESULT = STRATEGY_DIR / "backtest_result.json"
EXPECTED_PATH = TEST_DIR / "expected.json"


def _find_backtrader_repo() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "backtrader").is_dir() and (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Cannot find backtrader repo root")


def _find_back_trader_root() -> Path:
    # Vendored migration: no longer requires external back_trader workspace
    return Path(__file__).resolve().parents[5]


BACKTRADER_REPO = _find_backtrader_repo()
BACK_TRADER_ROOT = _find_back_trader_root()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_strategy() -> dict:
    if not RUN_PY.exists():
        raise AssertionError(f"Missing run.py: {RUN_PY}")

    original_result = SOURCE_RESULT.read_text(encoding="utf-8") if SOURCE_RESULT.exists() else None
    env = os.environ.copy()
    pythonpath = [
        str(BACKTRADER_REPO),
        str(BACK_TRADER_ROOT),
        env.get("PYTHONPATH", ""),
    ]
    env["PYTHONPATH"] = os.pathsep.join(item for item in pythonpath if item)

    try:
        subprocess.run(
            [sys.executable, str(RUN_PY)],
            cwd=str(STRATEGY_DIR),
            env=env,
            check=True,
            timeout=TIMEOUT_SEC,
            text=True,
            capture_output=True,
        )
        if not SOURCE_RESULT.exists():
            raise AssertionError(f"Strategy did not write result: {SOURCE_RESULT}")
        return _load_json(SOURCE_RESULT)
    finally:
        if original_result is None:
            if SOURCE_RESULT.exists():
                SOURCE_RESULT.unlink()
        else:
            SOURCE_RESULT.write_text(original_result, encoding="utf-8")


def _assert_number_close(actual: object, expected: object, key: str) -> None:
    if expected is None:
        return
    assert actual is not None, f"{key}: expected={expected}, got=None"

    exp = float(expected)
    act = float(actual)
    assert math.isfinite(act), f"{key}: expected={exp}, got={actual}"

    tolerance = max(1e-6, abs(exp) * 1e-6)
    assert abs(act - exp) <= tolerance, f"{key}: expected={exp}, got={act}"


def _assert_metrics(actual: dict, expected: dict) -> None:
    exact_keys = [
        "rows",
        "bar_num",
        "buy_count",
        "sell_count",
        "win_count",
        "loss_count",
        "trade_num",
        "total_trades",
        "stop_count",
        "contracts",
    ]
    float_keys = [
        "sum_profit",
        "final_value",
        "sharpe_ratio",
        "annual_return",
        "max_drawdown",
        "return_rate",
    ]

    for key in exact_keys:
        if key in expected and expected[key] is not None:
            assert actual.get(key) == expected[key], (
                f"{key}: expected={expected[key]}, got={actual.get(key)}"
            )

    for key in float_keys:
        if key in expected:
            _assert_number_close(actual.get(key), expected[key], key)


def test_test_43_0043_0597_fractals_minimum_distance() -> None:
    """Regression test for price_patterns/0043_0597_fractals_minimum_distance"""
    expected = _load_json(EXPECTED_PATH)
    actual = _run_strategy()
    _assert_metrics(actual, expected)


if __name__ == "__main__":
    test_test_43_0043_0597_fractals_minimum_distance()
