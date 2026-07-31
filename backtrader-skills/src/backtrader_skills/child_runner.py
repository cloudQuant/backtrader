"""Candidate-loading implementation used only inside the fixed child process."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

from .data import DataRegistry
from .errors import ContractError, ExecutionError
from .runtime import RuntimePaths

METRIC_FIELDS = (
    "bar_num",
    "buy_count",
    "sell_count",
    "win_count",
    "loss_count",
    "trade_num",
    "final_value",
    "sharpe_ratio",
    "annual_return",
    "max_drawdown",
    "return_rate",
)


def _import_backtrader(target: Path):
    target_text = str(target.resolve())
    if target_text not in sys.path:
        sys.path.insert(0, target_text)
    import backtrader as bt

    return bt


def _load_generated_class(candidate: Path, bt):
    module_name = f"_backtrader_skills_candidate_{candidate.stem}"
    spec = importlib.util.spec_from_file_location(module_name, candidate)
    if spec is None or spec.loader is None:
        raise ExecutionError("candidate module loader could not be created")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    candidates = [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and value is not bt.Strategy
        and issubclass(value, bt.Strategy)
        and value.__dict__.get("backtrader_skills_generated") is True
    ]
    if len(candidates) != 1:
        raise ExecutionError("candidate must expose exactly one generated Strategy class")
    return candidates[0]


def _timeframe(bt, name: str):
    aliases = {
        "ticks": bt.TimeFrame.Ticks,
        "microseconds": bt.TimeFrame.MicroSeconds,
        "seconds": bt.TimeFrame.Seconds,
        "minutes": bt.TimeFrame.Minutes,
        "days": bt.TimeFrame.Days,
        "weeks": bt.TimeFrame.Weeks,
        "months": bt.TimeFrame.Months,
        "years": bt.TimeFrame.Years,
    }
    try:
        return aliases[name.lower()]
    except KeyError as error:
        raise ContractError(f"unsupported Backtrader timeframe: {name}") from error


def _feed_class(bt, custom_lines: list[str]):
    if not custom_lines:
        return bt.feeds.GenericCSVData
    params = tuple((line, 7 + index) for index, line in enumerate(custom_lines))
    return type(
        "ManifestGenericCSVData",
        (bt.feeds.GenericCSVData,),
        {"lines": tuple(custom_lines), "params": params},
    )


def _add_manifest_feeds(cerebro, target: Path, manifest: dict[str, Any], bt) -> None:
    objects = RuntimePaths(target).dataset_objects
    for feed_record in manifest["feeds"]:
        feed_type = _feed_class(bt, feed_record.get("custom_lines", []))
        object_path = objects / feed_record["object"]["file"]
        feed = feed_type(
            dataname=str(object_path),
            headers=True,
            dtformat=feed_record["datetime_format"],
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=6,
            timeframe=_timeframe(bt, feed_record["timeframe"]),
            compression=feed_record["compression"],
        )
        name = feed_record["name"]
        if feed_record.get("resample"):
            options = feed_record["resample"]
            cerebro.resampledata(
                feed,
                name=name,
                timeframe=_timeframe(bt, options["timeframe"]),
                compression=int(options.get("compression", 1)),
            )
        elif feed_record.get("replay"):
            options = feed_record["replay"]
            cerebro.replaydata(
                feed,
                name=name,
                timeframe=_timeframe(bt, options["timeframe"]),
                compression=int(options.get("compression", 1)),
            )
        else:
            cerebro.adddata(feed, name=name)


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _extract_metrics(cerebro, initial_cash: float) -> dict[str, Any]:
    from backtrader.utils.get_metrics import get_backtest_metrics

    raw = get_backtest_metrics(cerebro, {"backtest": {"initial_cash": initial_cash}})
    counts = {
        key: int(raw.get(key) or 0)
        for key in (
            "bar_num",
            "buy_count",
            "sell_count",
            "win_count",
            "loss_count",
            "trade_num",
        )
    }
    metrics = {
        **counts,
        "final_value": float(raw["final_value"]),
        "sharpe_ratio": _finite_or_none(raw.get("sharpe_ratio")),
        "annual_return": float(raw.get("annual_return") or 0.0),
        "max_drawdown": float(raw.get("max_drawdown") or 0.0),
        "return_rate": float(raw.get("return_rate") or 0.0),
    }
    if tuple(metrics) != METRIC_FIELDS:
        raise ExecutionError("metric field contract drifted")
    return metrics


def run_strategy_class_for_test(
    target: Path,
    strategy_class,
    dataset_id: str,
    *,
    runonce: bool,
) -> dict[str, Any]:
    target = target.resolve()
    bt = _import_backtrader(target)
    registry = DataRegistry(RuntimePaths(target))
    manifest = registry.get_manifest(dataset_id, verify=True)
    strategy_ir = getattr(strategy_class, "backtrader_skills_ir", None)
    cash = 100000.0
    commission = 0.0
    stake = 1
    if isinstance(strategy_ir, dict):
        cash = float(strategy_ir.get("cash", cash))
        commission = float(strategy_ir.get("commission", commission))
        stake = int(strategy_ir.get("sizer", {}).get("stake", stake))
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)
    cerebro.addsizer(bt.sizers.FixedSize, stake=stake)
    _add_manifest_feeds(cerebro, target, manifest, bt)
    cerebro.addstrategy(strategy_class)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    results = cerebro.run(runonce=runonce)
    if len(results) != 1:
        raise ExecutionError("fixed runner expected exactly one strategy result")
    strategy = results[0]
    metrics = _extract_metrics(cerebro, cash)
    return {
        "mode": "runonce" if runonce else "runnext",
        "metrics": metrics,
        "metric_units": {
            "bar_num": "bars_seen_by_strategy",
            "buy_count": "long_trade_records",
            "sell_count": "short_trade_records",
            "win_count": "closed_winning_trades",
            "loss_count": "closed_losing_trades",
            "trade_num": "trade_records",
            "final_value": "account_currency",
            "sharpe_ratio": "dimensionless_or_null",
            "annual_return": "ratio",
            "max_drawdown": "percent",
            "return_rate": "percent",
        },
        "events": list(getattr(strategy, "_skills_events", [])),
        "backtrader": {
            "version": getattr(bt, "__version__", "unknown"),
            "import_path": str(Path(bt.__file__).resolve()),
        },
    }


def run_candidate(target: Path, candidate: Path, dataset_id: str, mode: str) -> dict[str, Any]:
    bt = _import_backtrader(target)
    strategy_class = _load_generated_class(candidate, bt)
    return run_strategy_class_for_test(
        target, strategy_class, dataset_id, runonce=mode == "runonce"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--mode", choices=("runonce", "runnext"), required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_candidate(
        args.target.resolve(), args.candidate.resolve(), args.dataset_id, args.mode
    )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
