#!/usr/bin/env python
"""Run the iteration 35-1 FNN-embedding retrieval strategy.

Usage:
    python run.py                                    # single backtest, config.yaml
    python run.py --fromdate 2021-09-01 --todate 2021-10-31
    python run.py --mode optimize                    # budgeted parameter sweep
    python run.py --mode diagnose                    # cosine similarity distribution
    python run.py --retrain                          # ignore model cache, retrain
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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
    from .fnn_embedding_strategy import (
        DECISION_SKIP,
        DataValidationError,
        FnnEmbeddingStrategy,
        FnnRetrievalEngine,
        round_trip_cost,
    )
    from .fnn_autoencoder import RollingTrainer
except ImportError:  # Direct execution through this directory's run.py.
    from fnn_embedding_strategy import (  # type: ignore
        DECISION_SKIP,
        DataValidationError,
        FnnEmbeddingStrategy,
        FnnRetrievalEngine,
        round_trip_cost,
    )
    from fnn_autoencoder import RollingTrainer  # type: ignore

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
    "training",
    "backtest",
    "logging",
    "optimize",
    "outputs",
}
DATA_KEYS = {"file", "fromdate", "todate"}
PARAM_KEYS = {
    "window_bars",
    "horizon_bars",
    "top_n",
    "sim_threshold",
    "prob_threshold",
    "min_matches",
    "k_cost",
    "exit_multiple",
    "sim_neutral",
    "atr_floor",
    "spread_floor",
    "use_bracket",
}
TRAINING_KEYS = {
    "embed_dim",
    "retrain_freq",
    "stride",
    "norm_window",
    "norm_min",
    "epochs",
    "lr",
    "batch",
    "patience",
    "seed",
    "max_train_samples",
}
BACKTEST_KEYS = {"initial_cash", "size", "commission_pct", "slippage_pct", "spread_cost_pct"}
OPTIMIZE_KEYS = {"grid", "workers", "budget", "fromdate", "todate"}
GRID_ALLOWED = {"window_bars", "sim_threshold", "prob_threshold", "top_n", "min_matches", "k_cost"}
DEFAULT_TRIAL_BUDGET = 24


class RunnerConfigurationError(ValueError):
    """Raised before Cerebro construction when config.yaml is invalid."""


def _check_keys(section: Mapping, allowed: set, name: str) -> None:
    unknown = set(section) - allowed
    if unknown:
        raise RunnerConfigurationError(
            "unknown %s keys: %s (allowed: %s)" % (name, sorted(unknown), sorted(allowed))
        )


def load_yaml_config(path: Path) -> dict:
    """Load and validate config.yaml (unknown keys rejected, D351-09)."""
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise RunnerConfigurationError("config root must be a mapping")
    _check_keys(raw, ROOT_KEYS, "root")
    _check_keys(raw.get("data", {}), DATA_KEYS, "data")
    _check_keys(raw.get("params", {}), PARAM_KEYS, "params")
    _check_keys(raw.get("training", {}), TRAINING_KEYS, "training")
    _check_keys(raw.get("backtest", {}), BACKTEST_KEYS, "backtest")
    optimize = raw.get("optimize", {})
    _check_keys(optimize, OPTIMIZE_KEYS, "optimize")
    grid_keys = set(optimize.get("grid", {}))
    if not grid_keys <= GRID_ALLOWED:
        raise RunnerConfigurationError(
            "optimize.grid keys must be trading-layer params %s, got %s"
            % (sorted(GRID_ALLOWED), sorted(grid_keys))
        )
    return load_config(raw, repo=REPO)


def _as_date(value, name):
    if value in (None, ""):
        return None
    import pandas as pd

    try:
        return pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise RunnerConfigurationError("invalid %s: %r" % (name, value)) from exc


_FRAME_CACHE: dict = {}


def get_frame(file_path: str, fromdate, todate):
    """Per-process frame cache; the fork pool inherits it copy-on-write."""
    key = (str(file_path), str(fromdate), str(todate))
    if key not in _FRAME_CACHE:
        _FRAME_CACHE[key] = load_mt5_csv(file_path, fromdate, todate)
    return _FRAME_CACHE[key]


def _outputs(cfg: Mapping[str, Any]) -> dict:
    out = cfg.get("outputs", {})
    return {
        "result_json": HERE / out.get("result_json", "backtest_result.json"),
        "optimize_csv": HERE / out.get("optimize_csv", "optimize_results.csv"),
        "optimize_json": HERE / out.get("optimize_json", "optimize_results.json"),
        "models_dir": HERE / out.get("models_dir", "models"),
        "features_dir": HERE / out.get("features_dir", "features_cache"),
        "reports_dir": HERE / out.get("reports_dir", "reports"),
    }


def _cache_key(cfg: Mapping[str, Any], fromdate, todate, window_bars: int) -> str:
    digest = hashlib.sha1(
        json.dumps(
            {
                "file": cfg["data"]["file"],
                "fromdate": str(fromdate),
                "todate": str(todate),
                "window": window_bars,
                "training": cfg.get("training", {}),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:10]
    return digest


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
    use_cache: bool = True,
) -> dict:
    """Run one backtest and return the standard result payload (D351-13)."""
    data_cfg = cfg["data"]
    fromdate = _as_date(fromdate or data_cfg.get("fromdate"), "fromdate")
    todate = _as_date(todate or data_cfg.get("todate"), "todate")
    frame = get_frame(data_cfg["file"], fromdate, todate)

    params = dict(cfg["params"])
    if params_override:
        params.update(params_override)
    training = dict(cfg.get("training", {}))

    backtest_cfg = cfg.get("backtest", {})
    initial_cash = float(backtest_cfg.get("initial_cash", 100000.0))
    size = float(backtest_cfg.get("size", 1.0))
    commission_pct = float(backtest_cfg.get("commission_pct", 0.0002))
    slippage_pct = float(backtest_cfg.get("slippage_pct", 0.0))
    spread_cost_pct = float(backtest_cfg.get("spread_cost_pct", 0.00015))

    out = _outputs(cfg)
    engine = FnnRetrievalEngine(
        frame,
        window_bars=params["window_bars"],
        horizon_bars=params["horizon_bars"],
        stride=training.get("stride", 1),
        norm_window=training.get("norm_window", 2000),
        norm_min=training.get("norm_min", 500),
        sim_threshold=params["sim_threshold"],
        prob_threshold=params["prob_threshold"],
        min_matches=params["min_matches"],
        top_n=params["top_n"],
        sim_neutral=params["sim_neutral"],
        cost_gate=params["k_cost"] * round_trip_cost(commission_pct, spread_cost_pct),
    )
    trainer = RollingTrainer(
        engine.library,
        training,
        models_dir=out["models_dir"],
        reports_dir=out["reports_dir"],
        cache_key=_cache_key(cfg, fromdate, todate, params["window_bars"]),
        use_cache=use_cache,
    )
    # The initial encoder is trained lazily inside the strategy loop as
    # soon as MIN_TRAIN_SAMPLES labels are realised before the decision
    # instant (walk-forward, G351-02 defence 1).
    cerebro = bt.Cerebro()
    # Named feed is mandatory: unnamed PandasData trips TradeLogger's
    # DataFrame truthiness (iteration-35 implementation lesson).
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
        FnnEmbeddingStrategy,
        window_bars=params["window_bars"],
        horizon_bars=params["horizon_bars"],
        top_n=params["top_n"],
        sim_threshold=params["sim_threshold"],
        prob_threshold=params["prob_threshold"],
        min_matches=params["min_matches"],
        k_cost=params["k_cost"],
        exit_multiple=params["exit_multiple"],
        sim_neutral=params["sim_neutral"],
        atr_floor=params["atr_floor"],
        spread_floor=params["spread_floor"],
        use_bracket=bool(params.get("use_bracket", True)),
        size=size,
        retrain_freq=training.get("retrain_freq", 20),
        spread_cost_pct=spread_cost_pct,
        print_log=enable_logging,
        signals_path=signals_path,
        engine=engine,
        trainer=trainer,
    )
    strat = cerebro.run()[0]
    result = build_result_payload(
        strat, frame, initial_cash, params, data_cfg["file"], fromdate, todate, trainer
    )
    if write_results:
        result_path = out["result_json"]
        result_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print("result written: %s" % result_path)
    return result


def build_result_payload(
    strat, frame, initial_cash: float, params: Mapping, file_path, fromdate, todate, trainer
) -> dict:
    """Assemble backtest_result.json per D351-13 (functional-suite fields)."""
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
    evaluated = [s for s in signals if s["reason"] != "POSITION_OPEN"]
    sims = [s["top_sim_mean"] for s in evaluated if s.get("n_selected")]
    holding = [
        (t["exit_dt"] - t["entry_dt"]).total_seconds() / 60.0
        for t in trades
        if t.get("exit_dt") and t.get("entry_dt")
    ]
    retentions = [
        r["neighborhood_retention"]
        for r in trainer.train_reports
        if r.get("neighborhood_retention") == r.get("neighborhood_retention")
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
        "avg_top_sim": float(np.mean(sims)) if sims else 0.0,
        "avg_holding_bars": float(np.mean(holding)) if holding else 0.0,
        "forced_liquidation_count": 1 if strat.position else 0,
        "avg_selected_matches": float(
            np.mean([s["n_selected"] for s in evaluated if s["n_selected"]])
        )
        if any(s["n_selected"] for s in evaluated)
        else 0.0,
        "lib_size": strat.engine.library.n,
        "retrain_count": strat.retrain_count,
        "neighborhood_retention_mean": float(np.mean(retentions)) if retentions else None,
        "encoder_versions_used": sorted(strat.encoder_versions_used),
        "trial_count": 1,
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
# Optimisation (budgeted, cached models, no training inside workers)
# ---------------------------------------------------------------------------


def _optimize_worker(payload: Mapping[str, Any]) -> dict:
    cfg = payload["config"]
    result = run_single(
        cfg,
        fromdate=payload["fromdate"],
        todate=payload["todate"],
        params_override=payload["params"],
        enable_logging=False,
        write_results=False,
        use_cache=True,
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
                "avg_top_sim",
                "forced_liquidation_count",
            )
        }
    )
    return row


def run_optimize(cfg: Mapping[str, Any]) -> list:
    """Grid sweep under the trial budget; one metrics row per combination."""
    optimize = cfg.get("optimize", {})
    grid: Mapping[str, list] = optimize.get("grid", {})
    if not grid:
        raise RunnerConfigurationError("optimize.grid is empty")
    keys = sorted(grid)
    combos = [dict(zip(keys, values)) for values in itertools.product(*(grid[k] for k in keys))]
    budget = int(optimize.get("budget", DEFAULT_TRIAL_BUDGET))
    if len(combos) > budget:
        raise RunnerConfigurationError(
            "grid expands to %d combinations, over trial budget %d (D351-11)"
            % (len(combos), budget)
        )
    fromdate = _as_date(optimize.get("fromdate"), "optimize.fromdate")
    todate = _as_date(optimize.get("todate"), "optimize.todate")

    # Ensure the model cache exists before forking (workers never train).
    get_frame(cfg["data"]["file"], fromdate, todate)
    run_single(
        cfg,
        fromdate=fromdate,
        todate=todate,
        enable_logging=False,
        write_results=False,
        use_cache=True,
    )

    payloads = [
        {"config": cfg, "params": combo, "fromdate": fromdate, "todate": todate} for combo in combos
    ]
    workers = int(optimize.get("workers", 8))
    started = time.perf_counter()
    rows: list = []
    if workers <= 1:
        for payload in payloads:
            rows.append(_optimize_worker(payload))
    else:
        # spawn (not fork): the parent has already initialised torch during
        # the cache warm-up and forked children re-entering torch/BLAS can
        # deadlock; fresh interpreters pay a small import cost instead.
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=workers) as pool:
            rows.extend(pool.map(_optimize_worker, payloads))
    elapsed = time.perf_counter() - started

    for row in rows:
        net = row.get("final_value")
        row["net_profit"] = float(net) - float(cfg["backtest"]["initial_cash"])
        trades = row.get("trade_num") or 0
        row["win_rate"] = (row.get("win_count", 0) / trades) if trades else 0.0
        row["params_hash"] = json.dumps(row["params"], sort_keys=True)
    rows.sort(key=lambda r: tuple(r["params"][k] for k in keys))

    out = _outputs(cfg)
    csv_path = out["optimize_csv"]
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
            "avg_top_sim",
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
    out["optimize_json"].write_text(
        json.dumps(
            {"rows": rows, "grid": grid, "workers": workers, "elapsed_seconds": elapsed},
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    registry = out["reports_dir"] / "trial_registry.md"
    with registry.open("a", encoding="utf-8") as fh:
        fh.write(
            "- %s combos=%d budget=%d elapsed=%.1fs\n"
            % (time.strftime("%Y-%m-%d %H:%M:%S"), len(rows), budget, elapsed)
        )
    print("optimisation done: %d combinations in %.1fs -> %s" % (len(rows), elapsed, csv_path))
    return rows


# ---------------------------------------------------------------------------
# Similarity distribution diagnostic (D351-06.3, run before freezing thresholds)
# ---------------------------------------------------------------------------


def run_diagnose(cfg: Mapping[str, Any], *, fromdate=None, todate=None, probes: int = 20) -> dict:
    """Probe the full-library cosine similarity distribution (design B5)."""
    data_cfg = cfg["data"]
    fromdate = _as_date(fromdate or data_cfg.get("fromdate"), "fromdate")
    todate = _as_date(todate or data_cfg.get("todate"), "todate")
    frame = get_frame(data_cfg["file"], fromdate, todate)
    params = dict(cfg["params"])
    training = dict(cfg.get("training", {}))
    out = _outputs(cfg)

    engine = FnnRetrievalEngine(
        frame,
        window_bars=params["window_bars"],
        horizon_bars=params["horizon_bars"],
        stride=training.get("stride", 1),
        norm_window=training.get("norm_window", 2000),
        norm_min=training.get("norm_min", 500),
        sim_threshold=params["sim_threshold"],
        prob_threshold=params["prob_threshold"],
        min_matches=params["min_matches"],
        top_n=params["top_n"],
        sim_neutral=params["sim_neutral"],
        cost_gate=0.0,
    )
    trainer = RollingTrainer(
        engine.library,
        training,
        models_dir=out["models_dir"],
        reports_dir=out["reports_dir"],
        cache_key=_cache_key(cfg, fromdate, todate, params["window_bars"]),
    )
    trainer.advance_to(frame.index[len(frame) // 2], trigger="diagnose")
    if trainer.current_bundle() is None:
        raise RunnerConfigurationError(
            "not enough realised samples for an initial encoder; widen the segment"
        )
    trainer.apply_to_library(engine.library)

    lib = engine.library
    sims_all: list[float] = []
    probe_idx = np.linspace(0, len(frame) - 1, probes).astype(int)
    for row in probe_idx:
        dt = frame.index[row]
        key = engine._dt_to_row.get(dt)
        if key is None:
            continue
        v = trainer.current_bundle().encode_single(engine._features_full[key])
        v = v / (np.linalg.norm(v) + 1e-12)
        sims = (lib.embeddings @ v) / (np.linalg.norm(lib.embeddings, axis=1) + 1e-12)
        sims_all.extend(float(s) for s in sims)
    arr = np.asarray(sims_all, dtype=float)
    summary = {
        "probes": int(probes),
        "n_similarities": int(arr.size),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p99": float(np.percentile(arr, 99)),
        "p999": float(np.percentile(arr, 99.9)),
        "max": float(arr.max()),
        "hit_rate@default": float((arr >= float(params["sim_threshold"])).mean()),
        "default_threshold": float(params["sim_threshold"]),
    }
    out["reports_dir"].mkdir(parents=True, exist_ok=True)
    (out["reports_dir"] / "sim_distribution.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--mode", choices=("backtest", "optimize", "diagnose"), default=None)
    parser.add_argument("--fromdate", default=None)
    parser.add_argument("--todate", default=None)
    parser.add_argument(
        "--retrain", action="store_true", help="bypass the model cache and retrain from scratch"
    )
    args = parser.parse_args(argv)

    cfg = load_yaml_config(Path(args.config))
    mode = args.mode or cfg.get("mode", "backtest")
    started = time.perf_counter()
    try:
        if mode == "optimize":
            run_optimize(cfg)
        elif mode == "diagnose":
            run_diagnose(cfg, fromdate=args.fromdate, todate=args.todate)
        else:
            result = run_single(
                cfg,
                fromdate=args.fromdate,
                todate=args.todate,
                use_cache=not args.retrain,
            )
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
