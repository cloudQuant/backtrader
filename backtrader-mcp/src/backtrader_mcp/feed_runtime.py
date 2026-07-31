"""Trusted construction of typed feeds from immutable canonical CSV objects."""

from __future__ import annotations

import csv
import io
import json
import math
import os
from pathlib import Path
from typing import Any

import backtrader as bt

TIMEFRAMES = {
    "ticks": bt.TimeFrame.Ticks,
    "microseconds": bt.TimeFrame.MicroSeconds,
    "seconds": bt.TimeFrame.Seconds,
    "minutes": bt.TimeFrame.Minutes,
    "days": bt.TimeFrame.Days,
    "weeks": bt.TimeFrame.Weeks,
    "months": bt.TimeFrame.Months,
    "years": bt.TimeFrame.Years,
}


def _canonical_rows(path: str) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("materialized canonical CSV has no rows")
    return rows


def _csv_buffer(header: list[str], rows: list[list[str]]) -> io.StringIO:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    stream.seek(0)
    return stream


def _timeframe(config: dict[str, Any]) -> int:
    try:
        return TIMEFRAMES[config["source_timeframe"]]
    except KeyError as exc:
        raise ValueError("unknown materialized source timeframe") from exc


def _build_feed(config: dict[str, Any]) -> tuple[Any, int]:
    path = config["canonical_csv_path"]
    source_timeframe = _timeframe(config)
    compression = config["source_compression"]
    input_format = config["input_format"]
    rows = _canonical_rows(path)
    common = {"timeframe": source_timeframe, "compression": compression}
    if input_format in {"generic_csv", "canonical_csv_v1"}:
        feed = bt.feeds.GenericCSVData(
            dataname=path,
            dtformat="%Y-%m-%dT%H:%M:%S",
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=6,
            headers=True,
            **common,
        )
    elif input_format == "backtrader_csv":
        stream = _csv_buffer(
            ["date", "time", "open", "high", "low", "close", "volume", "openinterest"],
            [
                [
                    row["datetime"][:10],
                    row["datetime"][11:19],
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                    row["openinterest"],
                ]
                for row in rows
            ],
        )
        feed = bt.feeds.BacktraderCSVData(dataname=stream, headers=True, **common)
    elif input_format == "yahoo_csv":
        stream = _csv_buffer(
            ["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"],
            [
                [
                    row["datetime"][:10],
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["close"],
                    row["volume"],
                ]
                for row in rows
            ],
        )
        feed = bt.feeds.YahooFinanceCSVData(
            dataname=stream,
            headers=True,
            reverse=False,
            adjclose=False,
            round=False,
            **common,
        )
    elif input_format == "mt5_csv":
        stream = _csv_buffer(
            ["date", "time", "open", "high", "low", "close", "volume"],
            [
                [
                    row["datetime"][:10].replace("-", "."),
                    row["datetime"][11:16],
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                ]
                for row in rows
            ],
        )
        # Backtrader's MT4CSVData is also the controlled adapter for MT5's
        # compatible date/time/OHLCV export shape.
        feed = bt.feeds.MT4CSVData(dataname=stream, headers=True, **common)
    elif input_format in {"pandas", "pandas_custom_lines"}:
        import pandas as pd

        frame = pd.read_csv(path)
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise")
        frame = frame.set_index("datetime")
        feed_class: type[Any] = bt.feeds.PandasData
        custom_lines = tuple(config.get("custom_lines", ()))
        if input_format == "pandas_custom_lines":
            if not custom_lines:
                raise ValueError("pandas_custom_lines has no declared custom lines")
            feed_class = type(
                "MaterializedPandasCustomLines",
                (bt.feeds.PandasData,),
                {
                    "lines": custom_lines,
                    "params": tuple((line, line) for line in custom_lines),
                },
            )
        feed = feed_class(
            dataname=frame,
            datetime=None,
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            openinterest="openinterest",
            **common,
        )
    else:
        raise ValueError(f"unsupported materialized feed format: {input_format}")
    return feed, len(rows)


def _validate_frozen_paths(feed_configs: list[dict[str, Any]]) -> None:
    frozen_configs = json.loads(os.environ["BACKTRADER_MCP_FEEDS_JSON"])
    if type(feed_configs) is not list or any(type(config) is not dict for config in feed_configs):
        raise ValueError("feed configs must be plain JSON objects")
    if feed_configs != frozen_configs:
        raise ValueError("feed configs do not match the worker-frozen configuration")
    raw_paths = json.loads(os.environ["BACKTRADER_MCP_DATASETS_JSON"])
    if type(raw_paths) is not dict or any(
        type(name) is not str or type(path) is not str for name, path in raw_paths.items()
    ):
        raise ValueError("worker dataset path binding is invalid")
    seen: set[str] = set()
    for config in feed_configs:
        name = config.get("name")
        path = config.get("canonical_csv_path")
        if (
            not isinstance(name, str)
            or name in seen
            or not isinstance(path, str)
            or raw_paths.get(name) != path
        ):
            raise ValueError("feed config does not match the worker-frozen dataset paths")
        seen.add(name)


def _add_feed(
    cerebro: Any,
    feed: Any,
    strategy_name: str,
    operation: dict[str, Any],
) -> Any:
    mode = operation["mode"]
    if mode == "direct":
        return cerebro.adddata(feed, name=strategy_name)
    kwargs = {
        "timeframe": TIMEFRAMES[operation["timeframe"]],
        "compression": operation["compression"],
    }
    if mode == "resample":
        return cerebro.resampledata(feed, name=strategy_name, **kwargs)
    if mode == "replay":
        return cerebro.replaydata(feed, name=strategy_name, **kwargs)
    raise ValueError("unknown bar operation")


def _count(trades: Any, section: str) -> int:
    value = trades.get(section, {}).get("total")
    return int(value) if isinstance(value, (int, float)) else 0


def _finite_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def run_materialized_backtest(
    strategy_class: type[Any],
    feed_configs: list[dict[str, Any]],
    feed_bindings: list[dict[str, str]],
    *,
    starting_cash: float,
    commission: float,
    run_mode: str,
    archetype: str,
) -> dict[str, Any]:
    """Run a generated strategy using only worker-verified materialized inputs."""

    _validate_frozen_paths(feed_configs)
    configs = {config["name"]: config for config in feed_configs}
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(starting_cash)
    cerebro.broker.setcommission(commission=commission)
    runtime_evidence: list[dict[str, Any]] = []
    for binding in feed_bindings:
        config = configs[binding["dataset_feed"]]
        feed, source_row_count = _build_feed(config)
        operation = config["bar_operation"]
        added = _add_feed(cerebro, feed, binding["strategy_name"], operation)
        runtime_evidence.append(
            {
                "dataset_feed": config["name"],
                "strategy_feed": binding["strategy_name"],
                "input_format": config["input_format"],
                "adapter": config["adapter"],
                "constructed_class": type(feed).__name__,
                "bar_operation": operation,
                "source_row_count": source_row_count,
                "registered_class": type(added).__name__,
            }
        )
    cerebro.addstrategy(strategy_class)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    strategies = cerebro.run(runonce=run_mode == "runonce")
    strategy = strategies[0]
    trades = strategy.analyzers.trades.get_analysis()
    sharpe = strategy.analyzers.sharpe.get_analysis().get("sharperatio")
    returns = strategy.analyzers.returns.get_analysis()
    drawdown = strategy.analyzers.drawdown.get_analysis()
    final_value = float(cerebro.broker.getvalue())
    for evidence, data in zip(runtime_evidence, cerebro.datas):
        evidence["output_bar_count"] = int(data.buflen())
    metrics = {
        "bar_num": int(len(strategy)),
        "buy_count": _count(trades, "long"),
        "sell_count": _count(trades, "short"),
        "win_count": _count(trades, "won"),
        "loss_count": _count(trades, "lost"),
        "trade_num": _count(trades, "total"),
        "final_value": _finite_or_none(final_value),
        "sharpe_ratio": _finite_or_none(sharpe),
        "annual_return": _finite_or_none(returns.get("rnorm")),
        "max_drawdown": _finite_or_none(drawdown.get("max", {}).get("drawdown")),
        "return_rate": _finite_or_none((final_value / starting_cash - 1.0) * 100.0),
    }
    return {
        "schema_version": "run-result-v1",
        "run_mode": run_mode,
        "archetype": archetype,
        "metrics": metrics,
        "feed_runtime": runtime_evidence,
    }
