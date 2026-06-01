"""Shared helpers for branch-compare runners.

These wrappers re-use the strategy code embedded in the inlined regression
tests under tests/functional/strategies/<cat>/test_<NNNN>_<name>.py so the
exact same strategy and data loading runs on dev and master via the
scripts/run_strategy_branch_compare.py harness.

Each strategy gets a small `run.py` next door that imports `run_strategy()`
from this module with the path of the test file plus a strategy class
attribute name; the wrapper then:
  * Loads the inlined test module by file path
  * Builds cerebro using the test module's helpers
  * Adds bt.observers.TradeLogger so order/trade/signal/etc. logs land in
    $BT_TRADE_LOG_DIR (set by run_strategy_branch_compare.py)
  * Runs runonce=True (matches the regression test config)
  * Writes backtest_result.json next to run.py for hash comparison
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Callable

import backtrader as bt


def _load_test_module(test_path: Path):
    spec = importlib.util.spec_from_file_location(test_path.stem, test_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[test_path.stem] = mod
    spec.loader.exec_module(mod)
    return mod


def _trade_log_dir() -> str:
    """Resolve the TradeLogger log directory from env (set by branch-compare)."""
    candidates = ("BT_TRADE_LOG_DIR", "BT_TRADELOGGER_LOG_DIR", "TRADE_LOG_DIR")
    for key in candidates:
        value = os.environ.get(key)
        if value:
            return value
    # Local fallback when run.py is invoked manually without the harness.
    return str(Path(__file__).parent / "logs")


def _attach_trade_logger(cerebro: bt.Cerebro) -> None:
    log_dir = _trade_log_dir()
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    cerebro.addobserver(
        bt.observers.TradeLogger,
        log_dir=log_dir,
        log_format="json",
        log_orders=True,
        log_trades=True,
        log_positions=True,
        log_indicators=True,    # per-bar indicator values for divergence localization
        log_signals=True,
        log_ticks=False,
        log_bars=False,
        log_system=True,
        log_monitoring=False,
        log_errors=True,
        log_value=True,
        log_position_snapshot=True,
        log_to_console=False,
    )


def _safe(value):
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return None
    return value


def _strat_metrics(strat, cerebro, initial_cash):
    sharpe = strat.analyzers.sharpe.get_analysis() if hasattr(strat.analyzers, "sharpe") else {}
    returns = strat.analyzers.returns.get_analysis() if hasattr(strat.analyzers, "returns") else {}
    drawdown = strat.analyzers.drawdown.get_analysis() if hasattr(strat.analyzers, "drawdown") else {}
    trades = strat.analyzers.trades.get_analysis() if hasattr(strat.analyzers, "trades") else {}
    sqn = strat.analyzers.sqn.get_analysis() if hasattr(strat.analyzers, "sqn") else {}
    final_value = float(cerebro.broker.getvalue())
    closed = trades.get("total", {}).get("closed", 0)
    won = trades.get("won", {}).get("total", 0)
    lost = trades.get("lost", {}).get("total", 0)
    metrics = {
        "initial_cash": float(initial_cash),
        "final_value": final_value,
        "net_pnl": round(final_value - float(initial_cash), 6),
        "max_drawdown": _safe(drawdown.get("max", {}).get("drawdown", 0.0)),
        "sharpe_ratio": _safe(sharpe.get("sharperatio")),
        "annual_return": _safe(returns.get("rnorm")),
        "return_rate": _safe(returns.get("rtot")),
        "sqn": _safe(sqn.get("sqn")),
        "total_trades_closed": int(closed),
        "won": int(won),
        "lost": int(lost),
    }
    for attr in ("bar_num", "signal_count", "buy_count", "sell_count",
                 "trade_count", "win_count", "loss_count"):
        if hasattr(strat, attr):
            metrics[attr] = getattr(strat, attr)
    return metrics


def run_strategy(test_file: Path, run_py_dir: Path) -> int:
    """Load the inlined test module, run cerebro with TradeLogger, dump result.

    Returns 0 on success, non-zero on failure.
    """
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    mod = _load_test_module(test_file)
    cfg = mod.load_config()
    # Override hardcoded data path so master and dev worktrees both pick up
    # the same CSV from BT_BRANCH_COMPARE_DATA_ROOT (set by the harness or
    # falling back to the dev repo). Without this the master worktree may
    # not have the dev-only test fixture.
    data_root_override = os.environ.get("BT_BRANCH_COMPARE_DATA_ROOT")
    if data_root_override and "data" in cfg and "file" in cfg["data"]:
        original = Path(cfg["data"]["file"])
        # Replace any absolute prefix up to /tests/datas/ with the override.
        marker = "tests/datas/"
        path_str = str(original)
        if marker in path_str:
            tail = path_str.split(marker, 1)[1]
            cfg["data"]["file"] = str(Path(data_root_override) / "tests" / "datas" / tail)
            print(f"[branch_compare] data file -> {cfg['data']['file']}")
    inputs = mod.load_backtest_frame(cfg)
    cerebro = mod.build_cerebro(cfg, inputs)
    _attach_trade_logger(cerebro)
    initial_cash = cerebro.broker.getvalue()
    results = cerebro.run(runonce=True)
    strat = results[0] if not isinstance(results[0], list) else results[0][0]
    metrics = _strat_metrics(strat, cerebro, initial_cash)
    out_path = run_py_dir / "backtest_result.json"
    out_path.write_text(json.dumps(metrics, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"[branch_compare] wrote {out_path}")
    print(f"[branch_compare] metrics={metrics}")
    return 0


def main_for_test(test_file: Path) -> int:
    run_py_dir = Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else Path(__file__).parent
    return run_strategy(test_file, run_py_dir)
