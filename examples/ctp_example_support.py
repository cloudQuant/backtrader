"""CTP Futures Examples Support Module.

This module provides common utilities, configurations, and base classes
for CTP futures trading examples using the backtrader framework.

It includes:
- SimNow environment configurations for testing
- Placeholder data feed for testing without real connection
- Memory channel for inter-thread communication
- Base strategy class for configurable futures strategies
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
from pathlib import Path

import backtrader as bt
import yaml

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.channel import DataChannel
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = Path(__file__).resolve().parent

SIMNOW_ENVIRONMENTS = {
    "new_7x24": {
        "name": "SimNow New 7x24",
        "td_address": "tcp://182.254.243.31:40001",
        "md_address": "tcp://182.254.243.31:40011",
    },
    "new_group1": {
        "name": "SimNow New Group 1",
        "td_address": "tcp://182.254.243.31:30001",
        "md_address": "tcp://182.254.243.31:30011",
    },
    "new_group2": {
        "name": "SimNow New Group 2",
        "td_address": "tcp://182.254.243.31:30002",
        "md_address": "tcp://182.254.243.31:30012",
    },
    "new_group3": {
        "name": "SimNow New Group 3",
        "td_address": "tcp://182.254.243.31:30003",
        "md_address": "tcp://182.254.243.31:30013",
    },
}

AUTO_SIMNOW_ENV = "auto"
SIMNOW_ENV_PRIORITY = (
    "new_7x24",
    "new_group1",
    "new_group2",
    "new_group3",
)
DEFAULT_SIMNOW_ENV = AUTO_SIMNOW_ENV
DEFAULT_BROKER_ID = "9999"
DEFAULT_APP_ID = "simnow_client_test"
DEFAULT_AUTH_CODE = "0000000000000000"


def load_dotenv_if_available():
    """Load environment variables from .env file if dotenv is available."""
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass


load_dotenv_if_available()


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


def load_json_config(config_arg: str | None, base_dir: Path, default_name: str) -> tuple[dict, Path]:
    """Load configuration from JSON file.

    Args:
        config_arg: Config file path argument or None.
        base_dir: Base directory for relative paths.
        default_name: Default config file name.

    Returns:
        Tuple of (config_dict, config_path).
    """
    return load_config(config_arg, base_dir, default_name)


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


def parse_timeframe(value):
    """Parse timeframe string or integer to backtrader TimeFrame.

    Args:
        value: TimeFrame as int or string ('ticks', 'seconds', 'minutes', 'days').

    Returns:
        bt.TimeFrame value.

    Raises:
        ValueError: If timeframe string is not supported.
    """
    if isinstance(value, int):
        return value

    normalized = str(value or "ticks").strip().lower()
    mapping = {
        "ticks": bt.TimeFrame.Ticks,
        "seconds": bt.TimeFrame.Seconds,
        "minutes": bt.TimeFrame.Minutes,
        "days": bt.TimeFrame.Days,
    }
    if normalized not in mapping:
        raise ValueError(f"Unsupported timeframe: {value}")
    return mapping[normalized]


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


class _ScalarLine:
    """Simple scalar line implementation for placeholder data."""

    def __init__(self, value=0.0):
        """Initialize scalar line.

        Args:
            value: Initial value.
        """
        self.value = value

    def __getitem__(self, index):
        return self.value

    def __setitem__(self, index, value):
        self.value = value

    def datetime(self, index=0):
        """Get datetime value.

        Args:
            index: Line index (unused for scalar).

        Returns:
            Datetime value or epoch if conversion fails.
        """
        try:
            return bt.num2date(self.value)
        except Exception:
            return _dt.datetime.fromtimestamp(0.0)

    def date(self, index=0):
        """Get date value.

        Args:
            index: Line index (unused for scalar).

        Returns:
            Date portion of datetime.
        """
        return self.datetime(index).date()


class _PlaceholderParams:
    """Placeholder parameters for PlaceholderData."""

    def __init__(self):
        """Initialize with default session end time."""
        self.sessionend = _dt.time(23, 59, 59, 999990)


class PlaceholderData:
    """Placeholder data feed for testing without real data connection.

    This class provides a minimal data feed implementation that can be
    used for testing strategies in environments without real market data.
    """

    def __init__(self, symbol):
        """Initialize placeholder data feed.

        Args:
            symbol: Symbol name.
        """
        self._name = str(symbol)
        self.name = self._name
        self.symbol = self._name
        self._compensate = None
        self._len = 0
        self.p = _PlaceholderParams()
        self.datetime = _ScalarLine(0.0)
        self.close = _ScalarLine(0.0)

    def __len__(self):
        """Return data length."""
        return int(self._len)

    def __bool__(self):
        """Return True for truthiness check."""
        return True

    @staticmethod
    def date2num(value):
        """Convert datetime to backtrader numeric format."""
        return bt.date2num(value)

    @staticmethod
    def num2date(value):
        """Convert backtrader numeric format to datetime."""
        return bt.num2date(value)


BASE_FUTURES_STRATEGY_PARAMS = (
    ("printlog", True),
    ("enable_trading", True),
    ("stop_after_ticks", 0),
    ("open_offset", "open"),
    ("close_offset", "close_today"),
    ("force_entry_after_ticks", 0),
    ("force_exit_after_ticks", 0),
    ("cancel_pending_after_ticks", 0),
)


class ConfigurableFuturesStrategyBase(bt.Strategy):
    """Base strategy class for configurable futures trading.

    This base class provides common functionality for futures trading
    strategies including order management, position tracking, and
    configurable trading parameters.
    """
    params = BASE_FUTURES_STRATEGY_PARAMS

    def __init__(self):
        """Initialize strategy state."""
        self.pending_refs = set()
        self.pending_orders = {}
        self.pending_order_submitted_ticks = {}
        self.position_cache = {}
        self.placeholder_data = {}
        self.signal_count = 0
        self.completed_roundtrips = 0
        self.data_status = {}
        self._last_order_status = {}

    def log(self, message):
        """Log message if printlog parameter is enabled.

        Args:
            message: Message to log.
        """
        if self.p.printlog:
            print(f"[{self.__class__.__name__}] {message}")

    def notify_data(self, data, status, *args, **kwargs):
        """Handle data feed status changes.

        Args:
            data: Data feed that changed status.
            status: New status value.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        status_name = data._getstatusname(status)
        self.data_status[getattr(data, "_name", "")] = status_name
        self.log(f"data {getattr(data, '_name', '')} -> {status_name}")

    def _resolve_data(self, symbol):
        """Resolve data feed by symbol name.

        Args:
            symbol: Symbol name to resolve.

        Returns:
            Data feed for the symbol, or a PlaceholderData if not found.
        """
        symbol = str(symbol)
        resolved_data = None
        if getattr(self, "datas", None):
            try:
                resolved_data = self.getdatabyname(symbol)
            except Exception:
                resolved_data = None

            if resolved_data is None:
                for data in self.datas:
                    if getattr(data, "_name", None) == symbol:
                        resolved_data = data
                        break
                    if getattr(data, "_dataname", None) == symbol:
                        resolved_data = data
                        break

        if resolved_data is not None:
            try:
                if len(resolved_data) > 0:
                    return resolved_data
            except Exception:
                return resolved_data

        data = self.placeholder_data.get(symbol)
        if data is None:
            data = PlaceholderData(symbol)
            self.placeholder_data[symbol] = data
        return data

    def _refresh_position(self, symbol):
        """Refresh and cache position size for symbol.

        Args:
            symbol: Symbol name.

        Returns:
            Current position size.
        """
        symbol = str(symbol)
        data = self._resolve_data(symbol)
        try:
            position = self.broker.getposition(data)
            size = float(getattr(position, "size", 0.0) or 0.0)
        except Exception:
            size = float(self.position_cache.get(symbol, 0.0))
        self.position_cache[symbol] = size
        return size

    def _position_size(self, symbol):
        """Get cached position size for symbol.

        Args:
            symbol: Symbol name.

        Returns:
            Cached position size.
        """
        symbol = str(symbol)
        if symbol not in self.position_cache:
            return self._refresh_position(symbol)
        return float(self.position_cache[symbol])

    def _submit_market(self, side, symbol, size, offset, signal_tag):
        """Submit a market order.

        Args:
            side: Order side ('buy' or 'sell').
            symbol: Symbol name.
            size: Order size.
            offset: Order offset ('open' or 'close_today').
            signal_tag: Signal identifier tag.

        Returns:
            Order instance or None.
        """
        quantity = int(round(abs(float(size or 0.0))))
        if quantity <= 0:
            return None

        if not self.p.enable_trading:
            self.log(
                f"signal only {signal_tag}: {side.upper()} {symbol} size={quantity} offset={offset}"
            )
            return None

        kwargs = {
            "data": self._resolve_data(symbol),
            "size": quantity,
            "exectype": bt.Order.Market,
        }
        extra_info = {"offset": offset, "signal_tag": signal_tag}
        broker_module = str(type(self.broker).__module__ or "").lower()
        is_live_btapi_broker = broker_module.endswith("btapibroker") or "btapibroker" in broker_module
        if is_live_btapi_broker:
            kwargs.update(extra_info)
        order = self.buy(**kwargs) if side == "buy" else self.sell(**kwargs)
        if order is not None:
            if not is_live_btapi_broker:
                order.addinfo(**extra_info)
            self.pending_refs.add(order.ref)
            self.pending_orders[order.ref] = order
            self.pending_order_submitted_ticks[order.ref] = int(getattr(self, "_tick_count", 0))
            self.signal_count += 1
            self.log(
                f"submit {side.upper()} {symbol} size={quantity} offset={offset} ref={order.ref}"
            )
        return order

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: Order instance.
        """
        symbol = (
            getattr(order.data, "_name", None)
            or getattr(order.data, "symbol", None)
            or "UNKNOWN"
        )
        status_name = order.getstatusname()
        previous_status = self._last_order_status.get(order.ref)
        if previous_status == order.status:
            return
        self._last_order_status[order.ref] = order.status

        if order.status in (order.Submitted, order.Accepted):
            self.log(f"order {order.ref} {status_name} {symbol}")
            return

        if order.status in (order.Partial, order.Completed):
            self._refresh_position(symbol)
            self.log(
                f"order {order.ref} {status_name} {symbol} "
                f"price={float(order.executed.price or 0.0):.2f} "
                f"size={float(order.executed.size or 0.0):.0f}"
            )
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            error_msg = getattr(order.info, "error_msg", "")
            suffix = f" error={error_msg}" if error_msg else ""
            self.log(f"order {order.ref} {status_name} {symbol}{suffix}")

        if not order.alive():
            self.pending_refs.discard(order.ref)
            self.pending_orders.pop(order.ref, None)
            self.pending_order_submitted_ticks.pop(order.ref, None)
            self._refresh_position(symbol)
            self.after_terminal_order(order)

    def after_terminal_order(self, order):
        """Hook called after a terminal order (filled/canceled/rejected).

        Args:
            order: Terminal order instance.
        """

    def forced_order_mode_enabled(self):
        """Check if forced order mode is enabled.

        Returns:
            True if force entry or force exit after tick limits are set.
        """
        return int(self.p.force_entry_after_ticks or 0) > 0 or int(self.p.force_exit_after_ticks or 0) > 0

    def reconcile_pending_order_states(self):
        """Reconcile all pending order states by calling notify_order."""
        for order in list(self.pending_orders.values()):
            self.notify_order(order)

    def maybe_cancel_stale_orders(self):
        """Cancel stale orders that have exceeded tick threshold.

        Returns:
            True if any orders were canceled.
        """
        cancel_after_ticks = int(self.p.cancel_pending_after_ticks or 0)
        if cancel_after_ticks <= 0:
            return False

        current_tick = int(getattr(self, "_tick_count", 0))
        canceled_any = False
        for ref in list(self.pending_refs):
            order = self.pending_orders.get(ref)
            submitted_tick = self.pending_order_submitted_ticks.get(ref)
            if order is None or submitted_tick is None:
                continue
            if current_tick - int(submitted_tick) < cancel_after_ticks:
                continue
            self.log(f"cancel stale order ref={ref} after {current_tick - int(submitted_tick)} ticks")
            self.cancel(order)
            canceled_any = True
        return canceled_any

    def maybe_stop_after_tick_limit(self):
        """Stop strategy if tick limit is reached and no pending orders.

        Returns:
            True if strategy was stopped.
        """
        limit = int(self.p.stop_after_ticks or 0)
        if limit > 0 and self._tick_count >= limit and not self.pending_refs:
            self.log(f"tick limit reached ({limit}), stopping")
            self.cerebro.runstop()
            return True
        return False

    def stop_if_roundtrips_complete(self, target_roundtrips):
        """Stop strategy if target roundtrips reached and no pending orders.

        Args:
            target_roundtrips: Target number of completed roundtrips.

        Returns:
            True if strategy was stopped.
        """
        target = int(target_roundtrips or 0)
        if target > 0 and self.completed_roundtrips >= target and not self.pending_refs:
            self.log(f"roundtrip target reached ({target}), stopping")
            self.cerebro.runstop()
            return True
        return False

    def get_summary(self):
        """Get strategy execution summary.

        Returns:
            Dictionary with strategy statistics.
        """
        return {
            "strategy": self.__class__.__name__,
            "tick_count": int(getattr(self, "_tick_count", 0)),
            "event_count": int(getattr(self, "_event_count", 0)),
            "signals": int(self.signal_count),
            "roundtrips": int(self.completed_roundtrips),
            "positions": {key: float(value) for key, value in sorted(self.position_cache.items())},
            "pending_refs": sorted(self.pending_refs),
        }


def get_simnow_credentials():
    """Get SimNow credentials from environment variables.

    Returns:
        Tuple of (investor_id, password).

    Raises:
        RuntimeError: If credentials are not set.
    """
    investor_id = os.getenv("SIMNOW_USER_ID") or os.getenv("simnow_user_id")
    password = os.getenv("SIMNOW_PASSWORD") or os.getenv("simnow_password")
    if not investor_id or not password:
        raise RuntimeError(
            "Missing SimNow credentials. Set SIMNOW_USER_ID and SIMNOW_PASSWORD in the environment or .env."
        )
    return investor_id, password


def _normalize_simnow_env_key(raw_value):
    """Normalize SimNow environment key to lowercase string.

    Args:
        raw_value: Raw environment value.

    Returns:
        Normalized lowercase string.
    """
    return str(raw_value or "").strip().lower()


def iter_simnow_env_candidates(env_key=None, strict=False):
    """Iterate over SimNow environment candidates in priority order.

    Args:
        env_key: Specific environment key to use.
        strict: If True, return only the specified environment.

    Yields:
        Environment keys in priority order.

    Raises:
        ValueError: If environment key is not supported.
    """
    selected_env = _normalize_simnow_env_key(env_key or os.getenv("SIMNOW_ENV") or DEFAULT_SIMNOW_ENV)
    if not selected_env:
        selected_env = DEFAULT_SIMNOW_ENV

    if selected_env != AUTO_SIMNOW_ENV and selected_env not in SIMNOW_ENVIRONMENTS:
        raise ValueError(
            f"Unsupported SimNow environment {selected_env!r}. "
            f"Choose from: {AUTO_SIMNOW_ENV}, {', '.join(sorted(SIMNOW_ENVIRONMENTS))}."
        )

    if strict and selected_env != AUTO_SIMNOW_ENV:
        return [selected_env]

    candidates = []
    if selected_env != AUTO_SIMNOW_ENV:
        candidates.append(selected_env)

    for candidate in SIMNOW_ENV_PRIORITY:
        if candidate in SIMNOW_ENVIRONMENTS and candidate not in candidates:
            candidates.append(candidate)

    for candidate in SIMNOW_ENVIRONMENTS:
        if candidate not in candidates:
            candidates.append(candidate)

    return candidates


def create_simnow_connection(env_key=None):
    """Create SimNow connection parameters.

    Args:
        env_key: Specific environment key to use.

    Returns:
        Dictionary with connection parameters.

    Raises:
        ValueError: If environment is not supported.
    """
    selected_env = _normalize_simnow_env_key(env_key or os.getenv("SIMNOW_ENV") or DEFAULT_SIMNOW_ENV)
    if selected_env not in SIMNOW_ENVIRONMENTS:
        raise ValueError(
            f"Unsupported SimNow environment {selected_env!r}. "
            f"Choose from: {', '.join(sorted(SIMNOW_ENVIRONMENTS))}."
        )

    investor_id, password = get_simnow_credentials()
    env_config = SIMNOW_ENVIRONMENTS[selected_env]
    return {
        "td_address": env_config["td_address"],
        "md_address": env_config["md_address"],
        "broker_id": DEFAULT_BROKER_ID,
        "investor_id": investor_id,
        "password": password,
        "app_id": DEFAULT_APP_ID,
        "auth_code": DEFAULT_AUTH_CODE,
        "simnow_env": selected_env,
        "simnow_name": env_config["name"],
    }


def create_live_store(config):
    """Create live BtApi store from configuration.

    Args:
        config: Configuration dictionary with simnow_env, store_kwargs, etc.

    Returns:
        Tuple of (BtApiStore, connection_info).
    """
    config_env = _normalize_simnow_env_key(config.get("simnow_env") or "")
    env_override = _normalize_simnow_env_key(os.getenv("SIMNOW_ENV") or "")
    requested_env = config_env or DEFAULT_SIMNOW_ENV
    if requested_env in {"", AUTO_SIMNOW_ENV} and env_override:
        requested_env = env_override
    strict_env = bool(config.get("simnow_strict_env", False))
    candidates = tuple(iter_simnow_env_candidates(requested_env, strict=strict_env))
    store_kwargs = dict(config.get("store_kwargs") or {})
    if not candidates:
        raise RuntimeError("Unable to resolve any SimNow environment candidates")

    candidate_env = candidates[0]
    connection = create_simnow_connection(candidate_env)
    store_config = dict(
        provider="ctp",
        td_address=connection["td_address"],
        md_address=connection["md_address"],
        broker_id=connection["broker_id"],
        investor_id=connection["investor_id"],
        password=connection["password"],
        app_id=connection["app_id"],
        auth_code=connection["auth_code"],
        **store_kwargs,
    )

    # Do not eager-start the live store here. BtApiFeed/BtApiBroker must own
    # the startup sequence inside Cerebro; starting the CTP clients before the
    # feed is attached causes live runs to exit immediately with 0 ticks/0
    # events, and the process may later crash while the native md/trader
    # threads are still shutting down.
    connection["requested_simnow_env"] = requested_env
    connection["fallback_used"] = requested_env not in {"", AUTO_SIMNOW_ENV, candidate_env}
    connection["attempted_simnow_envs"] = candidates
    return BtApiStore(**store_config), connection


def create_live_broker(store, config):
    """Create live broker from store and configuration.

    Args:
        store: BtApiStore instance.
        config: Configuration dictionary with broker settings.

    Returns:
        BtApiBroker instance.
    """
    broker_kwargs = dict(config.get("broker") or {})
    return BtApiBroker(store=store, **broker_kwargs)


def add_live_feeds(cerebro, store, config):
    """Add live feeds to cerebro from configuration.

    Args:
        cerebro: Cerebro instance.
        store: BtApiStore instance.
        config: Configuration dictionary with feed and symbols settings.

    Returns:
        List of added data feeds.
    """
    feed_config = dict(config.get("feed") or {})
    timeframe = parse_timeframe(feed_config.pop("timeframe", "ticks"))
    compression = int(feed_config.pop("compression", 1))
    backfill_start = bool(feed_config.pop("backfill_start", False))

    feeds = []
    for symbol in config.get("symbols") or []:
        data = BtApiFeed(
            store=store,
            dataname=symbol,
            timeframe=timeframe,
            compression=compression,
            backfill_start=backfill_start,
            **feed_config,
        )
        cerebro.adddata(data, name=symbol)
        feeds.append(data)
    return feeds


def run_cerebro_with_timeout(cerebro, timeout_seconds=60):
    """Run cerebro with a timeout that stops execution.

    Args:
        cerebro: Cerebro instance to run.
        timeout_seconds: Timeout in seconds before forcing stop.

    Returns:
        List of strategy results.
    """
    timer = threading.Timer(float(timeout_seconds), cerebro.runstop)
    timer.daemon = True
    timer.start()
    try:
        return cerebro.run()
    finally:
        timer.cancel()
