# pyright: reportAny=false, reportExplicitAny=false
"""Standard-metric extraction helpers for Cerebro backtests.

Exposes :data:`STANDARD_METRIC_FIELDS` (the canonical key list),
:func:`get_backtest_metrics` (which collects the raw values from a
completed run) and :func:`write_metrics` (which serialises the
result as JSON). An alias
:data:`extract_backtest_metrics` is also provided for callers that
prefer the longer name.
"""
from __future__ import absolute_import, division, print_function, unicode_literals

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STANDARD_METRIC_FIELDS = (
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


def get_backtest_metrics(cerebro: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Extract raw standard metrics from a completed Cerebro backtest.

    Pulls the strategy instance from ``cerebro.runstrats[0][0]`` and
    reads the ``sharpe``, ``returns``, ``drawdown`` and ``trades``
    analyzers plus the broker's final portfolio value. The returned
    dict contains exactly the keys listed in
    :data:`STANDARD_METRIC_FIELDS` and is the raw payload consumed by
    downstream normalisation or reporting layers.

    Args:
        cerebro: A Cerebro instance whose first run strategy has
            already produced the four expected analyzers
            (``sharpe``, ``returns``, ``drawdown``, ``trades``).
        config: Configuration dict. Only ``config["backtest"]
            ["initial_cash"]`` is read, used as the baseline for
            ``return_rate``.

    Returns:
        dict: Mapping of standard metric name -> value (floats for
        percentages and counts, broker value for ``final_value``).
    """

    strat = cerebro.runstrats[0][0]
    initial_cash = float(config["backtest"]["initial_cash"])
    final_value = float(cerebro.broker.getvalue())

    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    return {
        "bar_num": strat.bar_num,
        "buy_count": trades.get("long", {}).get("total"),
        "sell_count": trades.get("short", {}).get("total"),
        "win_count": trades.get("won", {}).get("total"),
        "loss_count": trades.get("lost", {}).get("total"),
        "trade_num": trades.get("total", {}).get("total"),
        "final_value": final_value,
        "sharpe_ratio": sharpe["sharperatio"],
        "annual_return": returns["rnorm"],
        "max_drawdown": drawdown["max"]["drawdown"],
        "return_rate": (final_value / initial_cash - 1.0) * 100.0,
    }


def write_metrics(metrics: dict[str, Any], base_dir: str, filename: str = "py_result.json") -> Path:
    """Serialize ``metrics`` as JSON inside ``base_dir``.

    Args:
        metrics: Mapping of metric name -> JSON-serialisable value.
            Typically the output of :func:`get_backtest_metrics`.
        base_dir: Directory where the JSON file will be written.
            Created implicitly by :class:`pathlib.Path` (the
            underlying ``open`` will fail if it does not exist).
        filename: JSON file name. Defaults to ``"py_result.json"``.

    Returns:
        Path: The absolute (or relative) path to the written file.
    """
    output_path = Path(base_dir) / filename
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2)
    return output_path


extract_backtest_metrics = get_backtest_metrics
extract_metrics = get_backtest_metrics
