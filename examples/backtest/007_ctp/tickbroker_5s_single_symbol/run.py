#!/usr/bin/env python
"""TickBroker 5s backtest: ``SingleSymbolMaStrategy`` on ticks synthesized from the
configured 5-second bars.

Offline only: the market data is the in-memory scenario in ``config.yaml``. No
live Store, credentials or network connection is used.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

import backtrader as bt
import yaml
from backtrader.brokers.tickbroker import TickBroker
from backtrader.channel import DataChannel, StreamingEventQueue
from backtrader.events import TickEvent

from single_symbol_ma_strategy import SingleSymbolMaStrategy

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


class MemoryChannel(DataChannel):
    """In-memory data channel for backtesting with pre-loaded events.

    This channel stores events in memory and yields them during backtest
    without requiring a real data source connection.
    """

    def __init__(self, channel_type, symbol, events):
        """Initialize memory channel.

        Args:
            channel_type: Type of channel ('tick', 'bar', etc.).
            symbol: Symbol name.
            events: Iterable of events to yield.
        """
        super().__init__(symbol=symbol, validate=False, auto_fix=False)
        self.channel_type = str(channel_type)
        self._events = list(events)

    def load(self):
        """Load events from channel.

        Yields:
            Events stored in the channel.
        """
        for event in self._events:
            yield event


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


def _build_ticks_from_bars(symbol, bar_points, start_timestamp, bar_seconds, extra_tick=True):
    """Build tick events from bar points.

    Args:
        symbol: Symbol name.
        bar_points: List of bar point dictionaries.
        start_timestamp: Base timestamp.
        bar_seconds: Bar interval in seconds.
        extra_tick: Whether to add final tick after bars.

    Returns:
        List of TickEvent objects.
    """
    ticks = []
    parsed_points = [_parse_bar_point(point) for point in bar_points]
    for index, (offset, _open, _high, _low, close, volume) in enumerate(parsed_points):
        timestamp = float(start_timestamp) + offset + float(bar_seconds) - 0.001
        ticks.append(
            TickEvent(
                timestamp=timestamp,
                symbol=str(symbol),
                exchange="SIM",
                asset_type="futures",
                local_time=timestamp,
                price=float(close),
                volume=float(volume),
                direction="buy",
                trade_id=f"{symbol}-bar-tick-{index}",
            )
        )
    if extra_tick and parsed_points:
        last_offset, _open, _high, _low, last_close, last_volume = parsed_points[-1]
        timestamp = float(start_timestamp) + last_offset + float(bar_seconds) + 0.001
        ticks.append(
            TickEvent(
                timestamp=timestamp,
                symbol=str(symbol),
                exchange="SIM",
                asset_type="futures",
                local_time=timestamp,
                price=float(last_close),
                volume=float(last_volume or 1.0),
                direction="buy",
                trade_id=f"{symbol}-bar-tick-final",
            )
        )
    return ticks


def build_tick_backtest_channel(config):
    """Build tick backtest channel from configuration.

    Args:
        config: Configuration dictionary with scenario details.

    Returns:
        StreamingEventQueue configured for tick backtesting.

    Raises:
        ValueError: If scenario type is not supported.
    """
    scenario = dict(config.get("scenario") or {})
    scenario_type = str(scenario.get("type") or "").strip().lower()
    start_timestamp = float(scenario.get("start_timestamp", 1710000000.0))
    bar_seconds = int(scenario.get("bar_seconds", config.get("bar_seconds", 5)))

    if scenario_type == "single_symbol_bars":
        symbol = str(scenario.get("symbol") or config["strategy_params"]["symbol"])
        ticks = _build_ticks_from_bars(
            symbol, scenario.get("bars") or [], start_timestamp, bar_seconds
        )
        return StreamingEventQueue(
            channels=[MemoryChannel("tick", symbol, ticks)],
            preload_window=1.0,
            adaptive=False,
        )

    if scenario_type == "pair_bars":
        channels = []
        for symbol, bars in dict(scenario.get("bars") or {}).items():
            ticks = _build_ticks_from_bars(symbol, bars, start_timestamp, bar_seconds)
            channels.append(MemoryChannel("tick", symbol, ticks))
        return StreamingEventQueue(channels=channels, preload_window=1.0, adaptive=False)

    raise ValueError(f"Unsupported tickbroker 5s scenario: {scenario_type}")


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Run the TickBroker 5s SingleSymbolMaStrategy backtest"
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
    cerebro.setbroker(TickBroker(cash=initial_cash, **broker_kwargs))
    cerebro.addstrategy(SingleSymbolMaStrategy, **dict(config.get("strategy_params") or {}))
    log_dir = attach_trade_logger(cerebro, config, config_path)

    channel = build_tick_backtest_channel(config)

    print(f"Running TickBroker 5s backtest with {config_path}")
    if log_dir is not None:
        print(f"TradeLogger dir: {log_dir}")
    print(f"Initial cash: {cerebro.broker.getcash():.2f}")

    results = cerebro.run(channel=channel)

    strategy = results[0]
    broker = cerebro.broker
    print(f"Final cash: {broker.getcash():.2f}")
    print(f"Final value: {broker.getvalue():.2f}")
    print(json.dumps(strategy.get_summary(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
