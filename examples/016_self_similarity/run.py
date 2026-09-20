#!/usr/bin/env python
"""Run the iteration-35 self-similarity strategy (backtest or optimise).

Usage:
    python run.py                                    # single backtest, config.yaml
    python run.py --fromdate 2021-09-01 --todate 2021-10-31
    python run.py --mode optimize                    # parameter grid sweep
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import multiprocessing
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Optional

import backtrader as bt
import numpy as np
import yaml

try:
    from .self_similarity_strategy import (
        DECISION_SKIP,
        DataValidationError,
        SelfSimilarityStrategy,
        SimilarityEngine,
    )
except ImportError:  # Direct execution through this directory's run.py.
    from self_similarity_strategy import (  # type: ignore
        DECISION_SKIP,
        DataValidationError,
        SelfSimilarityStrategy,
        SimilarityEngine,
    )

from backtrader.utils.load_data import load_config, load_mt5_csv

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DEFAULT_CONFIG = HERE / "config.yaml"

ROOT_KEYS = {
    "schema_version",
    "strategy_id",
    "mode",
    "data",
    "params",
    "backtest",
    "logging",
    "optimize",
    "outputs",
}
DATA_KEYS = {"file", "fromdate", "todate"}
PARAM_KEYS = {
    "window_bars",
    "horizon_bars",
    "lookback_days",
    "corr_threshold",
    "prob_threshold",
    "exit_multiple",
    "min_matches",
    "use_bracket",
}
BACKTEST_KEYS = {"initial_cash", "size", "commission_pct", "slippage_pct"}


class RunnerConfigurationError(ValueError):
    """Raised before Cerebro construction when config.yaml is invalid."""


def _check_keys(section: Mapping, allowed: set, name: str) -> None:
    unknown = set(section) - allowed
    if unknown:
        raise RunnerConfigurationError(
            "unknown %s keys: %s (allowed: %s)" % (name, sorted(unknown), sorted(allowed))
        )


def load_yaml_config(path: Path) -> dict:
    """Load and validate config.yaml (unknown keys are rejected, D35-09)."""
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise RunnerConfigurationError("config root must be a mapping")
    _check_keys(raw, ROOT_KEYS, "root")
    _check_keys(raw.get("data", {}), DATA_KEYS, "data")
    _check_keys(raw.get("params", {}), PARAM_KEYS, "params")
    _check_keys(raw.get("backtest", {}), BACKTEST_KEYS, "backtest")
    optimize = raw.get("optimize", {})
    _check_keys(optimize, {"grid", "workers", "fromdate", "todate"}, "optimize")
    grid_keys = set(optimize.get("grid", {}))
    if not grid_keys <= PARAM_KEYS:
        raise RunnerConfigurationError(
            "optimize.grid keys must be params subset, got %s" % sorted(grid_keys)
        )
    return load_config(raw, repo=REPO)


def _as_date(value, name):
    if value in (None, ""):
        return None
    return pd_timestamp(value, name)


_FRAME_CACHE: dict = {}
"""Per-process loaded frames.

The optimiser pre-loads each data segment once in the parent process and
uses a ``fork`` pool so children inherit these frames copy-on-write; this
avoids re-paying the multi-pass datetime parsing (~2.5 min per full load)
in every child for every grid combination.
"""


def get_frame(file_path: str, fromdate, todate):
    key = (str(file_path), str(fromdate), str(todate))
    if key not in _FRAME_CACHE:
        _FRAME_CACHE[key] = load_mt5_csv(file_path, fromdate, todate)
    return _FRAME_CACHE[key]


def pd_timestamp(value, name: str):
    import pandas as pd

    try:
        return pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise RunnerConfigurationError("invalid %s: %r" % (name, value)) from exc


# ---------------------------------------------------------------------------
# Single backtest
# ---------------------------------------------------------------------------


def run_single(
    cfg: Mapping[str, Any],
    *,
    fromdate=None,
    todate=None,
    params_override: Optional[Mapping[str, Any]] = None,
    enable_logging: bool = True,
    write_results: bool = True,
) -> dict:
    """Run one backtest and return the standard result payload."""

    data_cfg = cfg["data"]
    fromdate = _as_date(fromdate or data_cfg.get("fromdate"), "fromdate")
    todate = _as_date(todate or data_cfg.get("todate"), "todate")
    frame = get_frame(data_cfg["file"], fromdate, todate)

    params = dict(cfg["params"])
    if params_override:
        params.update(params_override)
    engine = SimilarityEngine(
        frame,
        params["window_bars"],
        params["horizon_bars"],
        params["lookback_days"],
        corr_threshold=params["corr_threshold"],
        prob_threshold=params["prob_threshold"],
        min_matches=params["min_matches"],
    )

    backtest_cfg = cfg.get("backtest", {})
    initial_cash = float(backtest_cfg.get("initial_cash", 100000.0))
    size = float(backtest_cfg.get("size", 1.0))
    commission_pct = float(backtest_cfg.get("commission_pct", 0.0))
    slippage_pct = float(backtest_cfg.get("slippage_pct", 0.0))

    cerebro = bt.Cerebro()
    # ``name`` is mandatory here: an unnamed PandasData leaves ``_name=None``
    # and TradeLogger's ``or``-chain in _iter_position_datas would bool() the
    # underlying DataFrame (raises every bar). Naming short-circuits it.
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="XAUUSD_M1")
    cerebro.broker.setcash(initial_cash)
    if commission_pct:
        cerebro.broker.setcommission(commission=commission_pct)
    if slippage_pct:
        cerebro.broker.set_slippage_perc(slippage_pct)

    signals_path = None
    logging_cfg = cfg.get("logging", {})
    if enable_logging and logging_cfg.get("trade_logger", False):
        log_dir = HERE / logging_cfg.get("log_dir", "logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        cerebro.addobserver(
            bt.observers.TradeLogger,
            log_dir=str(log_dir),
            log_orders=bool(logging_cfg.get("log_orders", True)),
            log_trades=bool(logging_cfg.get("log_trades", True)),
            log_signals=bool(logging_cfg.get("log_signals", True)),
            log_value=bool(logging_cfg.get("log_value", False)),
            log_positions=bool(logging_cfg.get("log_positions", False)),
            log_indicators=bool(logging_cfg.get("log_indicators", False)),
            log_ticks=bool(logging_cfg.get("log_ticks", False)),
            log_bars=bool(logging_cfg.get("log_bars", False)),
            log_system=bool(logging_cfg.get("log_system", True)),
            log_monitoring=bool(logging_cfg.get("log_monitoring", False)),
            log_errors=bool(logging_cfg.get("log_errors", True)),
            mysql_enabled=False,
        )
        if logging_cfg.get("signals_jsonl"):
            signals_path = HERE / logging_cfg["signals_jsonl"]
            signals_path.unlink(missing_ok=True)

    cerebro.addstrategy(
        SelfSimilarityStrategy,
        window_bars=params["window_bars"],
        horizon_bars=params["horizon_bars"],
        lookback_days=params["lookback_days"],
        corr_threshold=params["corr_threshold"],
        prob_threshold=params["prob_threshold"],
        exit_multiple=params["exit_multiple"],
        min_matches=params["min_matches"],
        use_bracket=bool(params.get("use_bracket", True)),
        size=size,
        print_log=enable_logging,
        signals_path=signals_path,
        engine=engine,
    )
    strat = cerebro.run()[0]
    result = build_result_payload(
        strat, frame, initial_cash, params, data_cfg["file"], fromdate, todate
    )
    if write_results:
        outputs = cfg.get("outputs", {})
        result_path = HERE / outputs.get("result_json", "backtest_result.json")
        result_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print("result written: %s" % result_path)
    return result


def build_result_payload(
    strat, frame, initial_cash: float, params: Mapping, file_path, fromdate, todate
) -> dict:
    """Assemble backtest_result.json per D35-13 (functional-suite fields)."""
    equity = np.asarray(strat.equity_curve, dtype=float)
    trades = strat.closed_trades
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    final_value = float(strat.broker.getvalue())
    first_dt = frame.index[0]
    last_dt = frame.index[-1]
    years = max((last_dt - first_dt).total_seconds() / (365.25 * 86400), 1e-9)

    ratios = np.diff(np.log(np.maximum(equity, 1e-12)))
    bars_per_year = len(equity) / years
    if len(ratios) and float(ratios.std(ddof=1)) > 0:
        sharpe = float(ratios.mean() / ratios.std(ddof=1) * math.sqrt(bars_per_year))
    else:
        sharpe = float("nan")
    if final_value > 0 and initial_cash > 0:
        annual_return = (final_value / initial_cash) ** (1.0 / years) - 1.0
    else:
        annual_return = float("nan")
    if len(equity):
        peak = np.maximum.accumulate(equity)
        drawdowns = 1.0 - equity / peak
        max_drawdown = float(drawdowns.max())
    else:
        max_drawdown = float("nan")

    signals = strat.signal_log
    evaluated = [s for s in signals if s["reason"] not in ("POSITION_OPEN",)]
    selected = [s["n_selected"] for s in evaluated if s["n_selected"]]
    holding = [
        (t["exit_dt"] - t["entry_dt"]).total_seconds() / 60.0
        for t in trades
        if t.get("exit_dt") and t.get("entry_dt")
    ]
    return {
        "rows": int(len(frame)),
        "bar_num": int(len(frame)),
        "buy_count": sum(1 for t in trades if t["direction"] == "LONG"),
        "sell_count": sum(1 for t in trades if t["direction"] == "SHORT"),
        "win_count": len(wins),
        "loss_count": len(losses),
        "sum_profit": float(sum(t["pnl"] for t in trades)),
        "trade_num": len(trades),
        "stop_count": sum(1 for t in trades if t["exit_kind"] == "STOP"),
        "take_count": sum(1 for t in trades if t["exit_kind"] == "TAKE"),
        "final_value": final_value,
        "sharpe_ratio": sharpe,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "return_rate": (final_value / initial_cash - 1.0) * 100.0,
        "signal_count": len(evaluated),
        "signal_skip_count": sum(1 for s in evaluated if s["decision"] == DECISION_SKIP),
        "position_open_bars": sum(1 for s in signals if s["reason"] == "POSITION_OPEN"),
        "avg_selected_matches": float(np.mean(selected)) if selected else 0.0,
        "avg_holding_bars": float(np.mean(holding)) if holding else 0.0,
        "forced_liquidation_count": 1 if strat.position else 0,
        "params": dict(params),
        "data": {
            "file": str(file_path),
            "fromdate": str(fromdate) if fromdate is not None else None,
            "todate": str(todate) if todate is not None else None,
            "rows": int(len(frame)),
            "first_dt": str(first_dt),
            "last_dt": str(last_dt),
        },
    }


# ---------------------------------------------------------------------------
# Optimisation
# ---------------------------------------------------------------------------


def _optimize_worker(payload: Mapping[str, Any]) -> dict:
    """Run one grid combination in a child process (no logging artefacts)."""
    cfg = payload["config"]
    result = run_single(
        cfg,
        fromdate=payload["fromdate"],
        todate=payload["todate"],
        params_override=payload["params"],
        enable_logging=False,
        write_results=False,
    )
    row = {"params": payload["params"]}
    row.update(
        {
            key: result[key]
            for key in (
                "final_value",
                "trade_num",
                "win_count",
                "loss_count",
                "sharpe_ratio",
                "annual_return",
                "max_drawdown",
                "signal_count",
                "avg_selected_matches",
                "forced_liquidation_count",
            )
        }
    )
    return row


def run_optimize(cfg: Mapping[str, Any]) -> list:
    """Grid sweep with a process pool; emits one metrics row per combination."""
    optimize = cfg.get("optimize", {})
    grid: Mapping[str, list] = optimize.get("grid", {})
    if not grid:
        raise RunnerConfigurationError("optimize.grid is empty")
    keys = sorted(grid)
    combos = [dict(zip(keys, values)) for values in itertools.product(*(grid[k] for k in keys))]
    fromdate = _as_date(optimize.get("fromdate"), "optimize.fromdate")
    todate = _as_date(optimize.get("todate"), "optimize.todate")

    payloads = [
        {"config": cfg, "params": combo, "fromdate": fromdate, "todate": todate} for combo in combos
    ]
    workers = int(optimize.get("workers", 8))
    started = time.perf_counter()
    # Warm the per-process frame cache once; children forked below inherit it
    # copy-on-write (macOS default is spawn, so request fork explicitly: the
    # payload is pure CPU backtesting with no threaded state).
    get_frame(cfg["data"]["file"], fromdate, todate)
    rows: list = []
    if workers <= 1:
        for payload in payloads:
            rows.append(_optimize_worker(payload))
    else:
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(processes=workers) as pool:
            rows.extend(pool.map(_optimize_worker, payloads))
    elapsed = time.perf_counter() - started

    # normalise types and derive compact metric columns
    for row in rows:
        result_net = row.get("final_value")
        row["net_profit"] = float(result_net) - float(cfg["backtest"]["initial_cash"])
        trades = row.get("trade_num") or 0
        row["win_rate"] = (row.get("win_count", 0) / trades) if trades else 0.0
        row["params_hash"] = json.dumps(row["params"], sort_keys=True)
    rows.sort(key=lambda r: tuple(r["params"][k] for k in keys))

    outputs = cfg.get("outputs", {})
    csv_path = HERE / outputs.get("optimize_csv", "optimize_results.csv")
    columns = (
        ["params_hash"]
        + keys
        + [
            "net_profit",
            "final_value",
            "trade_num",
            "win_count",
            "loss_count",
            "win_rate",
            "sharpe_ratio",
            "annual_return",
            "max_drawdown",
            "signal_count",
            "avg_selected_matches",
            "forced_liquidation_count",
        ]
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(
                [row.get(col, "") for col in columns[:1]]
                + [row["params"][k] for k in keys]
                + [row.get(col, "") for col in columns[1 + len(keys) :]]
            )
    json_path = HERE / outputs.get("optimize_json", "optimize_results.json")
    json_path.write_text(
        json.dumps(
            {"rows": rows, "grid": grid, "workers": workers, "elapsed_seconds": elapsed},
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    print("optimisation done: %d combinations in %.1fs -> %s" % (len(rows), elapsed, csv_path))
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--mode", choices=("backtest", "optimize"), default=None)
    parser.add_argument("--fromdate", default=None)
    parser.add_argument("--todate", default=None)
    args = parser.parse_args(argv)

    cfg = load_yaml_config(Path(args.config))
    mode = args.mode or cfg.get("mode", "backtest")
    started = time.perf_counter()
    try:
        if mode == "optimize":
            run_optimize(cfg)
        else:
            result = run_single(cfg, fromdate=args.fromdate, todate=args.todate)
            print(
                "trades=%d net=%.2f final=%.2f sharpe=%.3f maxdd=%.3f (%.1fs)"
                % (
                    result["trade_num"],
                    result["sum_profit"],
                    result["final_value"],
                    result["sharpe_ratio"]
                    if result["sharpe_ratio"] == result["sharpe_ratio"]
                    else 0.0,
                    result["max_drawdown"]
                    if result["max_drawdown"] == result["max_drawdown"]
                    else 0.0,
                    time.perf_counter() - started,
                )
            )
    except (RunnerConfigurationError, DataValidationError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
