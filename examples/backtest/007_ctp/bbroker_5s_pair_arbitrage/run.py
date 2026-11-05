#!/usr/bin/env python
"""BackBroker 5s backtest: ``PairSpreadStrategy`` on standard 5-second pandas bar feeds.

Offline only: the market data is the in-memory scenario in ``config.yaml``. No
live Store, credentials or network connection is used.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

import backtrader as bt
import pandas as pd
import yaml
from backtrader.brokers.bbroker import BackBroker

from pair_spread_strategy import PairSpreadStrategy

RUN_DIR = Path(__file__).resolve().parent


def resolve_config_path(config_arg: str | None, base_dir: Path, default_name: str) -> Path:
    """Resolve configuration file path from argument or default.

    Args:
        config_arg: Config file path argument or None.
        base_dir: Base directory for relative paths.
        default_name: Default config file name.

    Returns:
        Resolved absolute path to config file.
    """
    candidate = Path(config_arg) if config_arg else Path(default_name)
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return candidate


def load_config(config_arg: str | None, base_dir: Path, default_name: str) -> tuple[dict, Path]:
    """Load configuration from YAML or JSON file.

    Args:
        config_arg: Config file path argument or None.
        base_dir: Base directory for relative paths.
        default_name: Default config file name.

    Returns:
        Tuple of (config_dict, config_path).

    Raises:
        ValueError: If config format is not supported.
    """
    config_path = resolve_config_path(config_arg, base_dir, default_name)
    with config_path.open("r", encoding="utf-8") as handle:
        suffix = config_path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            return yaml.safe_load(handle) or {}, config_path
        if suffix == ".json":
            return json.load(handle), config_path
        raise ValueError(f"Unsupported config format: {config_path}")


def attach_trade_logger(cerebro, config, config_path: Path):
    """Attach TradeLogger observer to cerebro from config.

    Args:
        cerebro: Cerebro instance.
        config: Configuration dictionary with trade_logger settings.
        config_path: Path to config file for resolving relative log_dir.

    Returns:
        Path to log directory, or None if trade logger is disabled.
    """
    trade_logger_config = dict(config.get("trade_logger") or {})
    enabled = bool(trade_logger_config.pop("enabled", True))
    if not enabled:
        return None

    raw_log_dir = trade_logger_config.pop("log_dir", None)
    if raw_log_dir:
        log_dir = Path(raw_log_dir)
        if not log_dir.is_absolute():
            log_dir = (config_path.parent / log_dir).resolve()
    else:
        timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = (config_path.parent / "logs" / config_path.stem / timestamp).resolve()

    trade_logger_config.setdefault("log_format", "json")
    trade_logger_config.setdefault("log_to_console", False)
    trade_logger_config.setdefault("log_orders", True)
    trade_logger_config.setdefault("log_trades", True)
    trade_logger_config.setdefault("log_positions", True)
    trade_logger_config.setdefault("log_indicators", True)
    trade_logger_config.setdefault("log_signals", True)
    trade_logger_config.setdefault("log_ticks", True)
    trade_logger_config.setdefault("log_bars", True)
    trade_logger_config.setdefault("log_system", True)
    trade_logger_config.setdefault("log_monitoring", True)
    trade_logger_config.setdefault("log_errors", True)
    trade_logger_config.setdefault("log_value", True)
    trade_logger_config.setdefault("log_position_snapshot", True)

    cerebro.addobserver(
        bt.observers.TradeLogger,
        log_dir=str(log_dir),
        **trade_logger_config,
    )
    return log_dir


def _parse_bar_point(raw_point):
    if isinstance(raw_point, dict):
        return (
            float(raw_point["offset"]),
            float(raw_point["open"]),
            float(raw_point["high"]),
            float(raw_point["low"]),
            float(raw_point["close"]),
            float(raw_point.get("volume", 0.0)),
        )

    if isinstance(raw_point, (list, tuple)) and len(raw_point) >= 6:
        return (
            float(raw_point[0]),
            float(raw_point[1]),
            float(raw_point[2]),
            float(raw_point[3]),
            float(raw_point[4]),
            float(raw_point[5]),
        )

    raise ValueError(f"Unsupported bar point: {raw_point!r}")


def add_bbroker_backtest_feeds(cerebro, config):
    """Add backtest feeds to cerebro from configuration.

    Args:
        cerebro: Cerebro instance.
        config: Configuration dictionary with scenario details.
    """
    scenario = dict(config.get("scenario") or {})
    scenario_type = str(scenario.get("type") or "").strip().lower()
    start_timestamp = float(scenario.get("start_timestamp", 1710000000.0))

    if scenario_type == "single_symbol_bars":
        symbol = str(scenario.get("symbol") or config["strategy_params"]["symbol"])
        _add_single_dataframe(cerebro, symbol, scenario.get("bars") or [], start_timestamp)
        return

    if scenario_type == "pair_bars":
        for symbol, bars in dict(scenario.get("bars") or {}).items():
            _add_single_dataframe(cerebro, symbol, bars, start_timestamp)
        return

    raise ValueError(f"Unsupported backbroker 5s scenario: {scenario_type}")


def _add_single_dataframe(cerebro, symbol, bar_points, start_timestamp):
    rows = []
    for raw_point in bar_points:
        offset, open_, high, low, close, volume = _parse_bar_point(raw_point)
        dt = pd.to_datetime(float(start_timestamp) + offset, unit="s", utc=True)
        rows.append(
            {
                "datetime": dt,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "openinterest": 0.0,
            }
        )
    frame = pd.DataFrame(rows).set_index("datetime")
    data = bt.feeds.PandasData(
        dataname=frame,
        timeframe=bt.TimeFrame.Seconds,
        compression=5,
    )
    cerebro.adddata(data, name=str(symbol))


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Run the BackBroker 5s PairSpreadStrategy backtest"
    )
    parser.add_argument(
        "--config", default="config.yaml", help="YAML config path, relative to this directory"
    )
    return parser


def main(argv=None) -> int:
    """Run the backtest and print the final account and strategy summary.

    Returns:
        int: Exit code (0 for success).
    """
    args = _build_parser().parse_args(argv)
    config, config_path = load_config(args.config, RUN_DIR, "config.yaml")

    broker_kwargs = dict(config.get("broker") or {})
    initial_cash = float(config.get("initial_cash", broker_kwargs.pop("cash", 100000.0)))
    cerebro = bt.Cerebro()
    cerebro.setbroker(BackBroker(cash=initial_cash, **broker_kwargs))
    cerebro.addstrategy(PairSpreadStrategy, **dict(config.get("strategy_params") or {}))
    log_dir = attach_trade_logger(cerebro, config, config_path)

    add_bbroker_backtest_feeds(cerebro, config)

    print(f"Running BackBroker 5s backtest with {config_path}")
    if log_dir is not None:
        print(f"TradeLogger dir: {log_dir}")
    print(f"Initial cash: {cerebro.broker.getcash():.2f}")

    results = cerebro.run()

    strategy = results[0]
    broker = cerebro.broker
    print(f"Final cash: {broker.getcash():.2f}")
    print(f"Final value: {broker.getvalue():.2f}")
    print(json.dumps(strategy.get_summary(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
