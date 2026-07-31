"""Deterministic 7-archetype by 2-profile strategy scaffolding."""

from __future__ import annotations

from .contracts import SCAFFOLD_PROFILES, StrategySpec
from .errors import InvalidRequest


def _params(spec: StrategySpec) -> str:
    defaults: dict[str, int | float | str | bool] = {
        "period": 20,
        "fast": 10,
        "slow": 30,
        "rsi_period": 14,
        "entry_z": 1.5,
        "exit_z": 0.3,
        "risk_fraction": 0.02,
    }
    defaults.update(spec.parameter_defaults)
    rendered = ",\n        ".join(f"{key}={value!r}" for key, value in sorted(defaults.items()))
    return f"dict(\n        {rendered},\n    )"


def _strategy_body(spec: StrategySpec) -> str:
    class_name = spec.class_name
    standard_lines = {"open", "high", "low", "close", "volume", "openinterest"}
    custom_lines = [line for line in spec.feeds[0]["lines"] if line not in standard_lines]
    precomputed_body = (
        f"""
        self.feature_signal = self.data.{custom_lines[0]}

    def next(self):
        if not self.position and self.feature_signal[0] > 0:
            self.buy()
        elif self.position and self.feature_signal[0] <= 0:
            self.close()
"""
        if custom_lines
        else """
        self.baseline = bt.indicators.SMA(self.data.close, period=self.p.period)

    def next(self):
        feature_signal = self.data.close[0] - self.baseline[0]
        if not self.position and feature_signal > 0:
            self.buy()
        elif self.position and feature_signal <= 0:
            self.close()
"""
    )
    bodies = {
        "single_data_indicator": """
        self.signal = bt.indicators.SMA(self.data.close, period=self.p.period)

    def next(self):
        if not self.position and self.data.close[0] > self.signal[0]:
            self.buy()
        elif self.position and self.data.close[0] < self.signal[0]:
            self.close()
""",
        "multi_indicator_system": """
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

    def next(self):
        if not self.position and self.fast_ma[0] > self.slow_ma[0] and self.rsi[0] < 70:
            self.buy()
        elif self.position and (self.fast_ma[0] < self.slow_ma[0] or self.rsi[0] > 75):
            self.close()
""",
        "multi_asset_allocation": """
        self.relative = self.data0.close / self.data1.close
        self.relative_ma = bt.indicators.SMA(self.relative, period=self.p.period)

    def next(self):
        if not self.getposition(self.data0) and self.relative[0] > self.relative_ma[0]:
            self.buy(data=self.data0)
        elif self.getposition(self.data0) and self.relative[0] < self.relative_ma[0]:
            self.close(data=self.data0)
""",
        "multi_timeframe": """
        self.primary_ma = bt.indicators.SMA(self.data0.close, period=self.p.fast)
        self.secondary_ma = bt.indicators.SMA(self.data1.close, period=self.p.slow)

    def next(self):
        if not self.position and self.data0.close[0] > self.primary_ma[0] and self.data1.close[0] > self.secondary_ma[0]:
            self.buy(data=self.data0)
        elif self.position and self.data0.close[0] < self.primary_ma[0]:
            self.close(data=self.data0)
""",
        "pairs_spread": """
        self.spread = self.data0.close - self.data1.close
        self.center = bt.indicators.SMA(self.spread, period=self.p.period)

    def next(self):
        deviation = self.spread[0] - self.center[0]
        if not self.getposition(self.data0) and deviation < -self.p.entry_z:
            self.buy(data=self.data0)
        elif self.getposition(self.data0) and abs(deviation) < self.p.exit_z:
            self.close(data=self.data0)
""",
        "order_risk": """
        self.trend = bt.indicators.SMA(self.data.close, period=self.p.period)
        self.entry_price = None

    def next(self):
        if not self.position and self.data.close[0] > self.trend[0]:
            size = max(1, int((self.broker.getvalue() * self.p.risk_fraction) / self.data.close[0]))
            self.buy(size=size)
            self.entry_price = float(self.data.close[0])
        elif self.position and (self.data.close[0] < self.trend[0] or self.data.close[0] < self.entry_price * 0.95):
            self.close()
""",
        "precomputed_ml": precomputed_body,
    }
    return (
        "import backtrader as bt\n\n\n"
        f"class {class_name}(bt.Strategy):\n"
        f"    params = {_params(spec)}\n\n"
        "    def __init__(self):\n"
        f"{bodies[spec.archetype].rstrip()}\n"
    )


def _runner(spec: StrategySpec, import_line: str) -> str:
    feed_bindings = [
        {
            "dataset_feed": dataset_feed,
            "strategy_name": strategy_feed["name"],
        }
        for dataset_feed, strategy_feed in zip(spec.dataset_feed_names, spec.feeds)
    ]
    return f"""import json
import os
from pathlib import Path

from backtrader_mcp.feed_runtime import run_materialized_backtest

{import_line}


def run_backtest():
    feed_configs = json.loads(os.environ["BACKTRADER_MCP_FEEDS_JSON"])
    result_path = Path(os.environ["BACKTRADER_MCP_RESULT"])
    run_mode = os.environ["BACKTRADER_MCP_RUN_MODE"]
    result = run_materialized_backtest(
        {spec.class_name},
        feed_configs,
        {feed_bindings!r},
        starting_cash={spec.starting_cash!r},
        commission={spec.commission!r},
        run_mode=run_mode,
        archetype={spec.archetype!r},
    )
    result_path.write_text(json.dumps(result, sort_keys=True, default=str), encoding="utf-8")
    return result


if __name__ == "__main__":
    run_backtest()
"""


def scaffold_files(spec: StrategySpec, profile: str) -> dict[str, str]:
    if profile not in SCAFFOLD_PROFILES:
        raise InvalidRequest("unknown scaffold profile")
    strategy = _strategy_body(spec)
    if profile == "single_test":
        runner = _runner(spec, "")
        combined = (
            strategy
            + "\n\n"
            + runner.replace(f"\n\nclass {spec.class_name}", f"\n\nclass {spec.class_name}", 1)
        )
        # The runner has no import because the strategy is in the same module.
        return {"test_strategy.py": combined, "strategy_spec.json": ""}
    return {
        "strategy.py": strategy,
        "run.py": _runner(spec, f"from strategy import {spec.class_name}"),
        "strategy_spec.json": "",
    }
