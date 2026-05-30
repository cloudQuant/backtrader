#!/usr/bin/env python
"""Trade Logger Observer - Comprehensive logging for backtrader.

This module provides the TradeLogger observer for automatically recording
all trading activities including orders, trades, positions, indicators,
and signals.

Features:
    - Order logging (order.log)
    - Trade logging (trade.log)
    - Position logging (position.log) - every bar
    - Indicator logging (indicator.log) - every bar
    - Signal logging (signal.log) - on buy/sell
    - Tick logging (tick.log) - every tick received
    - Bar logging (bar.log) - every synthesized bar
    - Position snapshot (current_position.yaml)
    - Optional MySQL support

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addobserver(bt.observers.TradeLogger,
    ...                     log_dir='./logs',
    ...                     log_orders=True,
    ...                     log_trades=True,
    ...                     log_positions=True,
    ...                     log_indicators=True,
    ...                     log_signals=True)
    >>> cerebro.run()
"""

import collections
import json
import logging
import os
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from ..observer import Observer
from ..utils.log_message import get_logger

logger = get_logger(__name__)

# Shanghai timezone (UTC+8) used for all log timestamps
_SHANGHAI_TZ = timezone(timedelta(hours=8))

# Optional MySQL support
try:
    import pymysql

    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# Optional YAML support
try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class TradeLogger(Observer):
    """Observer that automatically logs all trading activities.

    This observer tracks and records:
    - Order status changes (submitted, executed, canceled, etc.)
    - Trade openings and closings with PnL
    - Position changes on every bar
    - Indicator values on every bar
    - Buy/sell signals

    Params:
        log_dir (str): Directory for log files. Default: './logs'
        log_orders (bool): Enable order logging. Default: True
        log_trades (bool): Enable trade logging. Default: True
        log_positions (bool): Enable position logging. Default: True
        log_indicators (bool): Enable indicator logging. Default: True
        log_signals (bool): Enable signal logging. Default: True
        log_ticks (bool): Enable tick logging. Default: True
        log_bars (bool): Enable bar logging. Default: True
        log_position_snapshot (bool): Enable YAML position snapshot. Default: True
        snapshot_file (str): Snapshot filename. Default: 'current_position.yaml'
        log_format (str): Log format ('json' or 'text'). Default: 'json'
        log_to_console (bool): Also print to console. Default: False

        mysql_enabled (bool): Enable MySQL logging. Default: False
        mysql_host (str): MySQL host. Default: 'localhost'
        mysql_port (int): MySQL port. Default: 3306
        mysql_user (str): MySQL user. Default: 'root'
        mysql_password (str): MySQL password. Default: ''
        mysql_database (str): MySQL database. Default: 'backtrader'

    Example:
        >>> cerebro.addobserver(bt.observers.TradeLogger,
        ...                     log_dir='./logs',
        ...                     mysql_enabled=True,
        ...                     mysql_database='trading_logs')
    """

    _stclock = True
    _ltype = 2  # LineIterator.ObsType - ensure observer is registered for next() calls
    lines = ("dummy",)  # Observer requires at least one line

    params = dict(
        # File logging settings
        log_dir="./logs",
        log_orders=True,
        log_trades=True,
        log_positions=True,
        log_indicators=True,
        log_signals=True,
        log_ticks=True,
        log_bars=True,
        log_system=True,
        log_monitoring=True,
        log_errors=True,
        log_value=True,
        log_position_snapshot=True,
        snapshot_file="current_position.yaml",
        log_format="json",
        log_to_console=False,
        submit_count_warn_threshold=0,
        cancel_count_warn_threshold=0,
        submit_cancel_total_warn_threshold=0,
        duplicate_order_warn_threshold=0,
        duplicate_order_window_seconds=60.0,
        # MySQL settings - disabled by default
        mysql_enabled=False,
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="",
        mysql_database="backtrader",
    )

    def __init__(self):
        """Initialize the TradeLogger observer."""
        super().__init__()
        # CRITICAL: Set _ltype AFTER super().__init__() and ensure registration
        self._ltype = 2  # LineIterator.ObsType
        # Register self to owner's _lineiterators if not already done
        if hasattr(self, "_owner") and self._owner is not None:
            if hasattr(self._owner, "_lineiterators"):
                if self._ltype in self._owner._lineiterators:
                    if self not in self._owner._lineiterators[self._ltype]:
                        self._owner._lineiterators[self._ltype].append(self)
        self._order_logger = None
        self._trade_logger = None
        self._position_logger = None
        self._indicator_logger = None
        self._signal_logger = None
        self._system_logger = None
        self._monitor_logger = None
        self._tick_logger = None
        self._bar_logger = None
        self._value_logger = None
        self._error_logger = None
        self._mysql_conn = None
        self._last_position_state = {}
        self._run_id = self._generate_run_id()
        self._monitoring = collections.Counter()
        self._duplicate_requests = collections.defaultdict(collections.deque)
        self._triggered_thresholds = set()
        self._loggers_initialized = False

    def start(self):
        """Called at the start of the backtest/live run."""
        # CRITICAL: Ensure registration to _lineiterators for next() to be called
        self._ltype = 2  # LineIterator.ObsType
        if hasattr(self, "_owner") and self._owner is not None:
            if hasattr(self._owner, "_lineiterators"):
                if self._ltype in self._owner._lineiterators:
                    if self not in self._owner._lineiterators[self._ltype]:
                        self._owner._lineiterators[self._ltype].append(self)
        self._ensure_loggers_initialized()
        self._log_event(
            "system",
            "session_started",
            level="INFO",
            details={"observer": self.__class__.__name__},
        )

    def _ensure_loggers_initialized(self):
        """Ensure loggers are initialized (lazy initialization)."""
        if self._loggers_initialized:
            return
        self._loggers_initialized = True
        self._init_loggers()
        if self.p.mysql_enabled:
            self._init_mysql()

    def _init_loggers(self):
        """Initialize all file loggers using Python standard logging."""
        os.makedirs(self.p.log_dir, exist_ok=True)

        if self.p.log_orders:
            self._order_logger = self._create_file_logger(
                "bt_order", os.path.join(self.p.log_dir, "order.log")
            )

        if self.p.log_trades:
            self._trade_logger = self._create_file_logger(
                "bt_trade", os.path.join(self.p.log_dir, "trade.log")
            )

        if self.p.log_positions:
            self._position_logger = self._create_file_logger(
                "bt_position", os.path.join(self.p.log_dir, "position.log")
            )

        if self.p.log_indicators:
            self._indicator_logger = self._create_file_logger(
                "bt_indicator", os.path.join(self.p.log_dir, "indicator.log")
            )

        if self.p.log_signals:
            self._signal_logger = self._create_file_logger(
                "bt_signal", os.path.join(self.p.log_dir, "signal.log")
            )

        if self.p.log_ticks:
            self._tick_logger = self._create_file_logger(
                "bt_tick", os.path.join(self.p.log_dir, "tick.log")
            )

        if self.p.log_bars:
            self._bar_logger = self._create_file_logger(
                "bt_bar", os.path.join(self.p.log_dir, "bar.log")
            )

        if self.p.log_system:
            self._system_logger = self._create_file_logger(
                "bt_system", os.path.join(self.p.log_dir, "system.log")
            )

        if self.p.log_monitoring:
            self._monitor_logger = self._create_file_logger(
                "bt_monitor", os.path.join(self.p.log_dir, "monitor.log")
            )

        if self.p.log_value:
            self._value_logger = self._create_file_logger(
                "bt_value", os.path.join(self.p.log_dir, "value.log")
            )

        if self.p.log_errors:
            self._error_logger = self._create_file_logger(
                "bt_error", os.path.join(self.p.log_dir, "error.log")
            )

    def _create_file_logger(self, name, file_path):
        """Create a file logger using Python standard logging.

        Args:
            name: Logger name
            file_path: Path to log file

        Returns:
            logging.Logger instance
        """
        logger = logging.getLogger(f"{name}:{id(self)}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        for handler in list(logger.handlers):
            try:
                handler.close()
            except Exception as e:
                logger.debug("Failed to close log handler: %s", e)
        logger.handlers = []  # Clear existing handlers

        # File handler - write to file
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(file_handler)

        # Console handler - optional
        if self.p.log_to_console:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
            logger.addHandler(console_handler)

        return logger

    @staticmethod
    def _generate_run_id():
        """Generate a stable per-run identifier for correlation."""
        timestamp = datetime.now(_SHANGHAI_TZ).strftime("%Y%m%d%H%M%S")
        return f"trade-log-{timestamp}-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _log_time_str():
        """Return the current Shanghai (UTC+8) timestamp as an ISO string."""
        return datetime.now(_SHANGHAI_TZ).isoformat(timespec="milliseconds")

    def _store_provider(self):
        """Return the active live provider when available."""
        try:
            broker = getattr(self._owner, "broker", None)
            store = getattr(broker, "store", None)
            if store is not None:
                return getattr(store, "provider", "")
            return getattr(broker, "provider", "")
        except Exception as e:
            logger.debug("Failed to read store provider: %s", e)
            return ""

    def _session_id(self):
        """Return the active store session id when available."""
        try:
            broker = getattr(self._owner, "broker", None)
            store = getattr(broker, "store", None)
            return getattr(store, "session_id", "") if store is not None else ""
        except Exception as e:
            logger.debug("Failed to read session id: %s", e)
            return ""

    @staticmethod
    def _safe_order_info(order, key, default=None):
        """Read a value from order.info with a stable fallback."""
        info = getattr(order, "info", None)
        if info is None:
            return default

        try:
            value = getattr(info, key)
            if isinstance(value, Mapping) and not value:
                return default
            return value
        except AttributeError:
            # No attribute named `key`; try the dict-style .get() path below.
            pass
        except Exception:
            # Attribute access raised unexpectedly; fall back to .get() below.
            pass

        get_method = getattr(info, "get", None)
        if callable(get_method):
            try:
                value = get_method(key, default)
                if isinstance(value, Mapping) and not value:
                    return default
                return value
            except Exception:
                return default

        return default

    def _base_event(self, event_type, level="INFO", event_time=None, **fields):
        """Create a common structured event payload."""
        payload = {
            "log_time": self._log_time_str(),
            "event_time": event_time or self._get_datetime_str(),
            "event_type": event_type,
            "level": str(level).upper(),
            "run_id": self._run_id,
            "session_id": self._session_id(),
            "provider": self._store_provider(),
            "strategy_name": self._get_strategy_name(),
        }
        payload.update(fields)
        return payload

    def _emit_payload(self, logger, payload, text_line=None):
        """Write a structured payload to a logger."""
        if logger is None:
            return

        if self.p.log_format == "json":
            logger.info(json.dumps(payload, ensure_ascii=False, default=str))
            return

        if text_line is None:
            parts = [
                payload.get("log_time", ""),
                payload.get("level", "INFO"),
                payload.get("event_type", ""),
            ]
            for key in ("data_name", "status", "error_code", "error_msg"):
                value = payload.get(key)
                if value not in ("", None):
                    parts.append(f"{key}={value}")
            details = payload.get("details")
            if details:
                parts.append(str(details))
            text_line = " | ".join(str(part) for part in parts if part != "")

        logger.info(text_line)

    def _log_event(self, category, event_type, level="INFO", text_line=None, **fields):
        """Route a structured event into the appropriate runtime log."""
        logger_map = {
            "system": self._system_logger,
            "monitor": self._monitor_logger,
            "error": self._error_logger,
        }
        payload = self._base_event(event_type, level=level, **fields)
        self._emit_payload(logger_map.get(category), payload, text_line=text_line)
        return payload

    def _log_internal_error(self, source, exc):
        try:
            self._log_event(
                "error",
                "observer_internal_error",
                level="ERROR",
                error_code=str(source),
                error_msg=str(exc),
                details={"source": str(source)},
            )
        except Exception:
            logger.error("TradeLogger internal error in %s: %s", source, exc)

    def _monitor_threshold(self, counter_name, threshold, event_type):
        """Emit a warning event when a monitoring threshold is crossed."""
        if threshold <= 0:
            return

        value = int(self._monitoring.get(counter_name, 0))
        if value < threshold:
            return

        key = (counter_name, threshold)
        if key in self._triggered_thresholds:
            return

        self._triggered_thresholds.add(key)
        self._log_event(
            "monitor",
            event_type,
            level="WARNING",
            details={"counter": counter_name, "value": value, "threshold": threshold},
        )

    def _make_duplicate_key(self, action_type, details):
        """Build a duplicate-request key within the configured time window."""

        def normalize(value):
            return "" if value is None else str(value)

        return (
            action_type,
            normalize(details.get("data_name")),
            normalize(details.get("side")),
            normalize(details.get("offset")),
            normalize(details.get("size")),
            normalize(details.get("price")),
            normalize(details.get("order_ref")),
        )

    def _track_request_monitoring(self, action_type, details):
        """Update request counters, duplicate detection, and threshold checks."""
        if action_type == "submit":
            self._monitoring["submit_count"] += 1
            self._monitoring["submit_cancel_total"] += 1
            self._monitor_threshold(
                "submit_count",
                int(self.p.submit_count_warn_threshold or 0),
                "submit_count_threshold_reached",
            )
            self._monitor_threshold(
                "submit_cancel_total",
                int(self.p.submit_cancel_total_warn_threshold or 0),
                "submit_cancel_total_threshold_reached",
            )
        elif action_type == "cancel":
            self._monitoring["cancel_count"] += 1
            self._monitoring["submit_cancel_total"] += 1
            self._monitor_threshold(
                "cancel_count",
                int(self.p.cancel_count_warn_threshold or 0),
                "cancel_count_threshold_reached",
            )
            self._monitor_threshold(
                "submit_cancel_total",
                int(self.p.submit_cancel_total_warn_threshold or 0),
                "submit_cancel_total_threshold_reached",
            )

        key = self._make_duplicate_key(action_type, details)
        window = float(self.p.duplicate_order_window_seconds or 0.0)
        if window <= 0:
            return

        now = time.time()
        queue = self._duplicate_requests[key]
        queue.append(now)
        while queue and (now - queue[0]) > window:
            queue.popleft()

        if len(queue) <= 1:
            return

        counter_name = f"duplicate_{action_type}_count"
        self._monitoring[counter_name] += 1
        self._log_event(
            "monitor",
            "duplicate_order_detected",
            level="WARNING",
            details={
                "action_type": action_type,
                "duplicate_count": len(queue),
                **details,
            },
        )
        self._monitor_threshold(
            counter_name,
            int(self.p.duplicate_order_warn_threshold or 0),
            "duplicate_order_threshold_reached",
        )

    def _init_mysql(self):
        """Initialize MySQL connection and create tables."""
        if not MYSQL_AVAILABLE:
            logger.warning("pymysql not installed, MySQL logging disabled")
            if self.p.log_to_console:
                print("[TradeLogger] Warning: pymysql not installed, MySQL logging disabled")
            return

        try:
            self._mysql_conn = pymysql.connect(
                host=self.p.mysql_host,
                port=self.p.mysql_port,
                user=self.p.mysql_user,
                password=self.p.mysql_password,
                database=self.p.mysql_database,
                charset="utf8mb4",
                autocommit=True,
            )
            self._create_mysql_tables()
        except Exception as e:
            logger.error("MySQL connection failed: %s", e)
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL connection failed: {e}")
            self._mysql_conn = None

    def _create_mysql_tables(self):
        """Create MySQL tables if they don't exist."""
        if not self._mysql_conn:
            return

        cursor = self._mysql_conn.cursor()

        # Orders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bt_orders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                datetime DATETIME,
                ref INT,
                order_type VARCHAR(10),
                status VARCHAR(20),
                size DOUBLE,
                price DOUBLE,
                executed_price DOUBLE,
                executed_size DOUBLE,
                executed_value DOUBLE,
                commission DOUBLE,
                data_name VARCHAR(50),
                strategy_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_datetime (datetime),
                INDEX idx_ref (ref),
                INDEX idx_data_name (data_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bt_trades (
                id INT AUTO_INCREMENT PRIMARY KEY,
                datetime DATETIME,
                ref INT,
                data_name VARCHAR(50),
                size DOUBLE,
                price DOUBLE,
                value DOUBLE,
                pnl DOUBLE,
                pnlcomm DOUBLE,
                commission DOUBLE,
                isclosed BOOLEAN,
                isopen BOOLEAN,
                baropen INT,
                barclose INT,
                barlen INT,
                strategy_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_datetime (datetime),
                INDEX idx_data_name (data_name),
                INDEX idx_isclosed (isclosed)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Positions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bt_positions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                datetime DATETIME,
                data_name VARCHAR(50),
                size DOUBLE,
                price DOUBLE,
                value DOUBLE,
                strategy_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_datetime (datetime),
                INDEX idx_data_name (data_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Indicators table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bt_indicators (
                id INT AUTO_INCREMENT PRIMARY KEY,
                datetime DATETIME,
                indicator_name VARCHAR(100),
                indicator_value DOUBLE,
                data_name VARCHAR(50),
                strategy_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_datetime (datetime),
                INDEX idx_indicator_name (indicator_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Signals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bt_signals (
                id INT AUTO_INCREMENT PRIMARY KEY,
                datetime DATETIME,
                action VARCHAR(10),
                size DOUBLE,
                price DOUBLE,
                data_name VARCHAR(50),
                reason VARCHAR(255),
                strategy_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_datetime (datetime),
                INDEX idx_action (action)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.close()

    def _get_datetime_str(self):
        """Get current datetime as string."""
        try:
            dt = self._owner.datetime.datetime()
            return str(dt)
        except Exception as e:
            logger.debug("Failed to read strategy datetime: %s", e)
            return str(datetime.now(_SHANGHAI_TZ))

    def _get_strategy_name(self):
        """Get the strategy class name."""
        if self._owner is None:
            return "Unknown"
        try:
            return self._owner.__class__.__name__
        except Exception as e:
            logger.debug("Failed to read strategy name: %s", e)
            return "Unknown"

    def _get_broker_value(self):
        """Get current broker portfolio value."""
        try:
            broker = getattr(self._owner, "broker", None)
            if broker is None:
                return 0.0
            return float(broker.getvalue())
        except Exception as e:
            logger.debug("Failed to read broker value: %s", e)
            return 0.0

    def _get_broker_cash(self):
        """Get current broker cash."""
        try:
            broker = getattr(self._owner, "broker", None)
            if broker is None:
                return 0.0
            return float(broker.getcash())
        except Exception as e:
            logger.debug("Failed to read broker cash: %s", e)
            return 0.0

    def _iter_position_datas(self):
        """Yield data-like objects that can be queried for positions."""
        if not hasattr(self, "_owner") or self._owner is None:
            return []

        datas = list(getattr(self._owner, "datas", []) or [])
        if datas:
            return datas

        placeholder_data = getattr(self._owner, "placeholder_data", None)
        if isinstance(placeholder_data, dict):
            return [data for _, data in sorted(placeholder_data.items()) if data is not None]

        if placeholder_data:
            try:
                return [data for data in placeholder_data if data is not None]
            except TypeError:
                # placeholder_data is not iterable; fall through to empty list.
                pass

        return []

    @staticmethod
    def _position_market_value(data, position):
        """Best-effort mark-to-market value for data-less strategies."""
        if position.size == 0:
            return 0.0

        try:
            return float(position.size) * float(data.close[0])
        except Exception:
            return float(position.size) * float(getattr(position, "price", 0.0) or 0.0)

    def _log_bar_snapshots(self):
        """Log per-bar OHLC snapshots during regular backtests."""
        if not self._bar_logger:
            return

        if not hasattr(self, "_owner") or self._owner is None:
            return

        if not hasattr(self._owner, "datas") or not self._owner.datas:
            return

        broker_value = self._get_broker_value()
        broker_cash = self._get_broker_cash()

        for data in self._owner.datas:
            try:
                data_name = getattr(data, "_name", str(data))
                log_data = {
                    "log_time": self._log_time_str(),
                    "event_type": "bar",
                    "strategy_name": self._get_strategy_name(),
                    "data_name": data_name,
                    "datetime": self._get_datetime_str(),
                    "open": float(data.open[0]),
                    "high": float(data.high[0]),
                    "low": float(data.low[0]),
                    "close": float(data.close[0]),
                    "volume": float(data.volume[0]) if hasattr(data, "volume") else 0.0,
                    "openinterest": (
                        float(data.openinterest[0]) if hasattr(data, "openinterest") else 0.0
                    ),
                    "broker_value": broker_value,
                    "broker_cash": broker_cash,
                }
                self._emit_payload(
                    self._bar_logger,
                    log_data,
                    text_line=(
                        f"{log_data['log_time']} | BAR | datetime={log_data['datetime']} | "
                        f"data_name={data_name} | open={log_data['open']:.4f} | "
                        f"high={log_data['high']:.4f} | low={log_data['low']:.4f} | "
                        f"close={log_data['close']:.4f} | volume={log_data['volume']:.2f} | "
                        f"broker_value={broker_value:.2f} | broker_cash={broker_cash:.2f}"
                    ),
                )
            except Exception as e:
                logger.debug(
                    "Failed to log bar snapshot for %s: %s", getattr(data, "_name", str(data)), e
                )
                continue

    def next(self):
        """Called on every bar - log positions and indicators."""
        self._ensure_loggers_initialized()

        # Set dummy line value (required for observer)
        self.lines.dummy[0] = 0

        try:
            if self.p.log_bars:
                self._log_bar_snapshots()

            if self.p.log_value:
                self._log_value()

            if self.p.log_positions:
                self._log_positions()

            if self.p.log_indicators:
                self._log_indicators()

            if self.p.log_position_snapshot:
                self._save_position_snapshot()
        except Exception as e:
            self._log_internal_error("next", e)
            if self.p.log_to_console:
                import traceback

                print(f"[TradeLogger] Error in next(): {e}")
                traceback.print_exc()

    def notify_order(self, order):
        """Log order status changes."""
        self._ensure_loggers_initialized()

        if not self.p.log_orders:
            return

        log_data = self._format_order(order)
        self._emit_payload(self._order_logger, log_data, text_line=self._format_order_text(order))

        if str(order.getstatusname()).lower() == "rejected":
            self._log_event(
                "error",
                "order_rejected",
                level="ERROR",
                data_name=log_data.get("data_name"),
                order_ref=order.ref,
                error_code=log_data.get("error_code", ""),
                error_msg=log_data.get("error_msg", ""),
                status=log_data.get("status"),
                details={"order_type": log_data.get("order_type")},
            )

        # MySQL logging
        if self.p.mysql_enabled and self._mysql_conn:
            self._insert_order_mysql(log_data)

    def notify_trade(self, trade):
        """Log trade information."""
        self._ensure_loggers_initialized()

        if not self.p.log_trades:
            return

        log_data = self._format_trade(trade)
        self._emit_payload(self._trade_logger, log_data, text_line=self._format_trade_text(trade))

        # MySQL logging
        if self.p.mysql_enabled and self._mysql_conn:
            self._insert_trade_mysql(log_data)

    def log_signal(self, action, size, price, data_name=None, reason=None):
        """Log a trading signal.

        Args:
            action (str): 'buy' or 'sell'
            size (float): Order size
            price (float): Signal price
            data_name (str, optional): Data feed name
            reason (str, optional): Signal reason/description
        """
        self._ensure_loggers_initialized()

        if not self.p.log_signals:
            return

        owner_data_name = getattr(getattr(self._owner, "data", None), "_name", None)
        if owner_data_name is None:
            position_datas = self._iter_position_datas()
            if position_datas:
                owner_data_name = getattr(position_datas[0], "_name", None)

        log_data = {
            "log_time": self._log_time_str(),
            "datetime": self._get_datetime_str(),
            "action": action,
            "size": size,
            "price": price,
            "data_name": data_name or owner_data_name,
            "reason": reason or "",
            "strategy_name": self._get_strategy_name(),
        }
        self._emit_payload(
            self._signal_logger,
            log_data,
            text_line=(
                f"{log_data['log_time']} | {action.upper()} | datetime={log_data['datetime']} | "
                f"data_name={log_data['data_name'] or ''} | size={size} | "
                f"price={price} | reason={reason or ''}"
            ),
        )

        # MySQL logging
        if self.p.mysql_enabled and self._mysql_conn:
            self._insert_signal_mysql(log_data)

    def notify_tick_event(self, tick):
        """Log a tick event.

        Called by the strategy's _notify_tick_to_observers when a new tick arrives.

        Args:
            tick: Tick data object with attributes like symbol, price, volume, etc.
        """
        self._ensure_loggers_initialized()

        if not self.p.log_ticks or not self._tick_logger:
            return

        try:
            # Extract tick fields — support both dict-like and attribute-based objects
            if hasattr(tick, "to_dict") and callable(tick.to_dict):
                tick_dict = tick.to_dict()
            elif isinstance(tick, dict):
                tick_dict = dict(tick)
            else:
                tick_dict = {}
                for attr in (
                    "symbol",
                    "price",
                    "volume",
                    "timestamp",
                    "datetime",
                    "bid_price",
                    "ask_price",
                    "bid_volume",
                    "ask_volume",
                    "openinterest",
                    "turnover",
                    "trade_id",
                    "exchange",
                    "exchange_id",
                    "instrument_id",
                    "trading_day",
                    "update_time",
                    "update_millisec",
                    "asset_type",
                    "local_time",
                ):
                    val = getattr(tick, attr, None)
                    if val is not None:
                        tick_dict[attr] = val

            log_data = {
                "log_time": self._log_time_str(),
                "event_type": "tick",
                "strategy_name": self._get_strategy_name(),
                **tick_dict,
            }
            self._emit_payload(
                self._tick_logger,
                log_data,
                text_line=(
                    f"{log_data['log_time']} | TICK | "
                    f"symbol={tick_dict.get('symbol', '')} | "
                    f"price={tick_dict.get('price', '')} | "
                    f"volume={tick_dict.get('volume', '')} | "
                    f"bid={tick_dict.get('bid_price', '')} | "
                    f"ask={tick_dict.get('ask_price', '')}"
                ),
            )
        except Exception as e:
            self._log_internal_error("notify_tick_event", e)

    def notify_bar_event(self, bar):
        """Log a bar event.

        Called by the strategy's _notify_bar_to_observers when a new bar is synthesized.

        Args:
            bar: Bar data object with attributes like symbol, open, high, low, close, volume.
        """
        self._ensure_loggers_initialized()

        if not self.p.log_bars or not self._bar_logger:
            return

        try:
            if hasattr(bar, "to_dict") and callable(bar.to_dict):
                bar_dict = bar.to_dict()
            elif isinstance(bar, dict):
                bar_dict = dict(bar)
            else:
                bar_dict = {}
                for attr in (
                    "symbol",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "timestamp",
                    "datetime",
                    "interval",
                    "period",
                    "exchange",
                    "asset_type",
                    "turnover",
                    "openinterest",
                    "trading_day",
                ):
                    val = getattr(bar, attr, None)
                    if val is not None:
                        bar_dict[attr] = val

            broker_value = self._get_broker_value()
            broker_cash = self._get_broker_cash()
            log_data = {
                "log_time": self._log_time_str(),
                "event_type": "bar",
                "strategy_name": self._get_strategy_name(),
                "broker_value": broker_value,
                "broker_cash": broker_cash,
                **bar_dict,
            }
            self._emit_payload(
                self._bar_logger,
                log_data,
                text_line=(
                    f"{log_data['log_time']} | BAR | "
                    f"symbol={bar_dict.get('symbol', '')} | "
                    f"O={bar_dict.get('open', '')} H={bar_dict.get('high', '')} "
                    f"L={bar_dict.get('low', '')} C={bar_dict.get('close', '')} | "
                    f"vol={bar_dict.get('volume', '')} | "
                    f"broker_value={broker_value:.2f} | broker_cash={broker_cash:.2f}"
                ),
            )
        except Exception as e:
            self._log_internal_error("notify_bar_event", e)

    def notify_store_event(self, msg, *args, **kwargs):
        """Log a structured runtime event forwarded from a store."""
        self._ensure_loggers_initialized()

        event = kwargs.get("event")
        if not isinstance(event, dict):
            event = {
                "event_type": str(msg),
                "level": "INFO",
                "details": {"args": args, "kwargs": kwargs},
            }

        event_type = str(event.get("event_type") or msg or "runtime_event")
        level = str(event.get("level") or "INFO").upper()
        details = dict(event.get("details") or {})
        data_name = details.get("data_name")

        category = "system"
        if level in {"ERROR", "CRITICAL"} or event.get("error_code") or event.get("error_msg"):
            category = "error"
        elif (
            event_type.startswith("order_")
            or event_type.startswith("duplicate_")
            or event_type.startswith("batch_cancel_")
        ):
            category = "monitor"

        self._log_event(
            category,
            event_type,
            level=level,
            event_time=event.get("timestamp"),
            data_name=data_name,
            order_ref=event.get("order_ref") or details.get("order_ref"),
            error_code=event.get("error_code", ""),
            error_msg=event.get("error_msg", ""),
            account_id_masked=event.get("account_id_masked", ""),
            provider=event.get("provider") or self._store_provider(),
            session_id=event.get("session_id") or self._session_id(),
            status=event.get("status", ""),
            details=details,
        )

        if event_type in {"order_submit_request", "order_reject_local", "order_reject_remote"}:
            self._track_request_monitoring("submit", details)
        elif event_type == "order_cancel_request":
            self._track_request_monitoring("cancel", details)

    def notify_data_event(self, data, status, *args, **kwargs):
        """Log data-feed runtime status forwarded from Cerebro."""
        self._ensure_loggers_initialized()

        data_name = getattr(data, "_name", None) or getattr(data, "_dataname", None) or repr(data)
        status_names = getattr(data, "_NOTIFNAMES", ())
        if isinstance(status, int) and 0 <= status < len(status_names):
            status_name = status_names[status]
        else:
            status_name = str(status)

        level = "INFO"
        if status_name in {"DISCONNECTED", "CONNBROKEN"}:
            level = "ERROR"
        elif status_name == "DELAYED":
            level = "WARNING"

        self._log_event(
            "system" if level == "INFO" else "error",
            "data_status",
            level=level,
            data_name=data_name,
            status=status_name,
            details={"args": args, "kwargs": kwargs},
        )

    def _log_value(self):
        """Log portfolio value and cash on every bar."""
        if not self._value_logger:
            return

        if not hasattr(self, "_owner") or self._owner is None:
            return

        broker_value = self._get_broker_value()
        broker_cash = self._get_broker_cash()

        log_data = {
            "log_time": self._log_time_str(),
            "datetime": self._get_datetime_str(),
            "strategy_name": self._get_strategy_name(),
            "broker_value": broker_value,
            "broker_cash": broker_cash,
        }

        self._emit_payload(
            self._value_logger,
            log_data,
            text_line=(
                f"{log_data['log_time']} | "
                f"datetime={log_data['datetime']} | "
                f"value={broker_value:.2f} | cash={broker_cash:.2f}"
            ),
        )

    def _log_positions(self):
        """Log position information for all data feeds."""
        if not self._position_logger and not (self.p.mysql_enabled and self._mysql_conn):
            return

        if not hasattr(self, "_owner") or self._owner is None:
            return

        position_datas = self._iter_position_datas()
        if not position_datas:
            return

        broker_value = self._get_broker_value()
        broker_cash = self._get_broker_cash()

        for data in position_datas:
            position = self._owner.getposition(data)
            data_name = getattr(data, "_name", str(data))
            market_value = self._position_market_value(data, position)

            log_data = {
                "log_time": self._log_time_str(),
                "datetime": self._get_datetime_str(),
                "data_name": data_name,
                "size": position.size,
                "price": position.price,
                "value": market_value,
                "broker_value": broker_value,
                "broker_cash": broker_cash,
                "strategy_name": self._get_strategy_name(),
            }

            # File logging
            if self._position_logger:
                self._emit_payload(
                    self._position_logger,
                    log_data,
                    text_line=(
                        f"{log_data['log_time']} | POSITION | datetime={log_data['datetime']} | "
                        f"data_name={data_name} | size={position.size} | "
                        f"price={position.price:.4f} | "
                        f"value={log_data['value']:.2f} | "
                        f"broker_value={broker_value:.2f} | broker_cash={broker_cash:.2f}"
                    ),
                )

            # MySQL logging
            if self.p.mysql_enabled and self._mysql_conn:
                self._insert_position_mysql(log_data)

    def _log_indicators(self):
        """Log all indicator values from the strategy."""
        if not self._indicator_logger and not (self.p.mysql_enabled and self._mysql_conn):
            return

        indicators_data = self._collect_indicators()

        if not indicators_data:
            return

        log_data = {
            "log_time": self._log_time_str(),
            "datetime": self._get_datetime_str(),
            "strategy_name": self._get_strategy_name(),
            **indicators_data,
        }

        # File logging
        if self._indicator_logger:
            indicator_str = " | ".join(
                [f"{k}={v:.4f}" for k, v in indicators_data.items() if isinstance(v, (int, float))]
            )
            self._emit_payload(
                self._indicator_logger,
                log_data,
                text_line=(
                    f"{log_data['log_time']} | INDICATOR | datetime={log_data['datetime']} | "
                    f"{indicator_str}"
                ),
            )

        # MySQL logging - insert each indicator separately
        if self.p.mysql_enabled and self._mysql_conn:
            for name, value in indicators_data.items():
                if isinstance(value, (int, float)):
                    self._insert_indicator_mysql(name, value)

    def _collect_indicators(self):
        """Collect all indicator values from the strategy.

        Returns:
            dict: Dictionary of indicator names and their current values.
        """
        indicators = {}

        try:
            # Get all indicators from the strategy
            if hasattr(self._owner, "_lineiterators"):
                for item in self._owner._lineiterators.get(self._owner.IndType, []):
                    self._extract_indicator_values(item, indicators)

            # Also check for indicators stored as attributes
            for attr_name in dir(self._owner):
                if attr_name.startswith("_"):
                    continue
                try:
                    attr = getattr(self._owner, attr_name)
                    if hasattr(attr, "lines") and hasattr(attr, "__len__"):
                        self._extract_indicator_values(attr, indicators, attr_name)
                except Exception as e:
                    logger.debug("Failed to read indicator attr %s: %s", attr_name, e)
                    continue

        except Exception as e:
            logger.debug("Failed to collect indicator values: %s", e)

        # Check for custom indicators method on the strategy
        if hasattr(self._owner, "get_custom_indicators") and callable(
            self._owner.get_custom_indicators
        ):
            try:
                custom = self._owner.get_custom_indicators()
                if isinstance(custom, dict):
                    indicators.update(custom)
            except Exception as e:
                logger.debug("Failed to get custom indicators: %s", e)

        return indicators

    def _extract_indicator_values(self, indicator, indicators_dict, prefix=""):
        """Extract values from an indicator object.

        Args:
            indicator: The indicator object
            indicators_dict: Dictionary to store values
            prefix: Optional prefix for indicator names
        """
        try:
            # Get indicator class name
            ind_name = indicator.__class__.__name__
            if prefix:
                ind_name = f"{prefix}_{ind_name}"

            # Get line values
            if hasattr(indicator, "lines"):
                for line_name in indicator.lines.getlinealiases():
                    try:
                        line = getattr(indicator.lines, line_name)
                        if len(line) > 0:
                            value = line[0]
                            if value is not None and not (
                                hasattr(value, "__float__") and float(value) != float(value)
                            ):
                                full_name = (
                                    f"{ind_name}_{line_name}"
                                    if line_name != ind_name.lower()
                                    else ind_name
                                )
                                indicators_dict[full_name] = float(value)
                    except Exception as e_line:
                        logger.debug("Failed to read indicator line %s: %s", line_name, e_line)
                        continue
        except Exception as e:
            logger.debug("Failed to extract indicator values: %s", e)

    def _save_position_snapshot(self):
        """Save current position snapshot to YAML file."""
        if not YAML_AVAILABLE:
            return

        snapshot = {
            "datetime": self._get_datetime_str(),
            "strategy": self._get_strategy_name(),
            "positions": {},
        }

        for data in self._iter_position_datas():
            position = self._owner.getposition(data)
            data_name = getattr(data, "_name", str(data))

            if position.size != 0:
                try:
                    current_price = round(float(data.close[0]), 4)
                except Exception:
                    current_price = round(float(getattr(position, "price", 0.0) or 0.0), 4)
                snapshot["positions"][data_name] = {
                    "size": position.size,
                    "price": round(position.price, 4),
                    "value": round(self._position_market_value(data, position), 2),
                    "current_price": current_price,
                }

        snapshot_path = os.path.join(self.p.log_dir, self.p.snapshot_file)
        try:
            with open(snapshot_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    snapshot, f, allow_unicode=True, default_flow_style=False, sort_keys=False
                )
        except Exception as e:
            logger.debug("Failed to save position snapshot: %s", e)
            if self.p.log_to_console:
                print(f"[TradeLogger] Failed to save position snapshot: {e}")

    def _format_order(self, order):
        """Format order data for logging."""
        data = getattr(order, "data", None)
        return {
            "log_time": self._log_time_str(),
            "datetime": self._get_datetime_str(),
            "ref": order.ref,
            "order_type": "Buy" if order.isbuy() else "Sell",
            "status": order.getstatusname(),
            "size": order.size,
            "price": order.price,
            "executed_price": order.executed.price if order.executed.size else None,
            "executed_size": order.executed.size,
            "executed_value": order.executed.value,
            "commission": order.executed.comm,
            "data_name": getattr(data, "_name", None) if data is not None else None,
            "strategy_name": self._get_strategy_name(),
            "external_order_id": self._safe_order_info(order, "external_order_id"),
            "error_code": self._safe_order_info(order, "error_code", ""),
            "error_msg": self._safe_order_info(order, "error_msg", ""),
        }

    def _format_order_text(self, order):
        """Format order data as text."""
        return (
            f"{self._log_time_str()} | "
            f"{'BUY' if order.isbuy() else 'SELL'} | "
            f"datetime={self._get_datetime_str()} | "
            f"ref={order.ref} | status={order.getstatusname()} | "
            f"size={order.size} | price={order.price} | "
            f"executed_price={order.executed.price if order.executed.size else None}"
        )

    def _format_trade(self, trade):
        """Format trade data for logging."""
        return {
            "log_time": self._log_time_str(),
            "datetime": self._get_datetime_str(),
            "ref": trade.ref,
            "data_name": trade.data._name,
            "size": trade.size,
            "price": trade.price,
            "value": trade.value,
            "pnl": trade.pnl,
            "pnlcomm": trade.pnlcomm,
            "commission": trade.commission,
            "isclosed": trade.isclosed,
            "isopen": trade.isopen,
            "baropen": trade.baropen,
            "barclose": trade.barclose if trade.isclosed else None,
            "barlen": trade.barlen,
            "strategy_name": self._get_strategy_name(),
        }

    def _format_trade_text(self, trade):
        """Format trade data as text."""
        status = "CLOSED" if trade.isclosed else ("OPEN" if trade.isopen else "UPDATE")
        return (
            f"{self._log_time_str()} | {status} | "
            f"datetime={self._get_datetime_str()} | ref={trade.ref} | data={trade.data._name} | "
            f"size={trade.size} | price={trade.price:.4f} | value={trade.value:.4f} | "
            f"commission={trade.commission:.4f} | pnl={trade.pnl:.2f} | pnlcomm={trade.pnlcomm:.2f}"
        )

    def _insert_order_mysql(self, log_data):
        """Insert order record into MySQL."""
        if not self._mysql_conn:
            return

        try:
            cursor = self._mysql_conn.cursor()
            cursor.execute(
                """
                INSERT INTO bt_orders (datetime, ref, order_type, status, size, price,
                    executed_price, executed_size, executed_value, commission, data_name, strategy_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    log_data["datetime"],
                    log_data["ref"],
                    log_data["order_type"],
                    log_data["status"],
                    log_data["size"],
                    log_data["price"],
                    log_data["executed_price"],
                    log_data["executed_size"],
                    log_data["executed_value"],
                    log_data["commission"],
                    log_data["data_name"],
                    log_data["strategy_name"],
                ),
            )
            cursor.close()
        except Exception as e:
            logger.debug("MySQL insert order failed: %s", e)
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL insert order failed: {e}")

    def _insert_trade_mysql(self, log_data):
        """Insert trade record into MySQL."""
        if not self._mysql_conn:
            return

        try:
            cursor = self._mysql_conn.cursor()
            cursor.execute(
                """
                INSERT INTO bt_trades (datetime, ref, data_name, size, price, value,
                    pnl, pnlcomm, commission, isclosed, isopen, baropen, barclose, barlen, strategy_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    log_data["datetime"],
                    log_data["ref"],
                    log_data["data_name"],
                    log_data["size"],
                    log_data["price"],
                    log_data["value"],
                    log_data["pnl"],
                    log_data["pnlcomm"],
                    log_data["commission"],
                    log_data["isclosed"],
                    log_data["isopen"],
                    log_data["baropen"],
                    log_data["barclose"],
                    log_data["barlen"],
                    log_data["strategy_name"],
                ),
            )
            cursor.close()
        except Exception as e:
            logger.debug("MySQL insert trade failed: %s", e)
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL insert trade failed: {e}")

    def _insert_position_mysql(self, log_data):
        """Insert position record into MySQL."""
        if not self._mysql_conn:
            return

        try:
            cursor = self._mysql_conn.cursor()
            cursor.execute(
                """
                INSERT INTO bt_positions (datetime, data_name, size, price, value, strategy_name)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    log_data["datetime"],
                    log_data["data_name"],
                    log_data["size"],
                    log_data["price"],
                    log_data["value"],
                    log_data["strategy_name"],
                ),
            )
            cursor.close()
        except Exception as e:
            logger.debug("MySQL insert position failed: %s", e)
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL insert position failed: {e}")

    def _insert_indicator_mysql(self, indicator_name, indicator_value):
        """Insert indicator record into MySQL."""
        if not self._mysql_conn:
            return

        try:
            cursor = self._mysql_conn.cursor()
            cursor.execute(
                """
                INSERT INTO bt_indicators (datetime, indicator_name, indicator_value, strategy_name)
                VALUES (%s, %s, %s, %s)
            """,
                (
                    self._get_datetime_str(),
                    indicator_name,
                    indicator_value,
                    self._get_strategy_name(),
                ),
            )
            cursor.close()
        except Exception as e:
            logger.debug("MySQL insert indicator failed: %s", e)
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL insert indicator failed: {e}")

    def _insert_signal_mysql(self, log_data):
        """Insert signal record into MySQL."""
        if not self._mysql_conn:
            return

        try:
            cursor = self._mysql_conn.cursor()
            cursor.execute(
                """
                INSERT INTO bt_signals (datetime, action, size, price, data_name, reason, strategy_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    log_data["datetime"],
                    log_data["action"],
                    log_data["size"],
                    log_data["price"],
                    log_data["data_name"],
                    log_data["reason"],
                    log_data["strategy_name"],
                ),
            )
            cursor.close()
        except Exception as e:
            logger.debug("MySQL insert signal failed: %s", e)
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL insert signal failed: {e}")

    def stop(self):
        """Called at the end of the backtest/live run."""
        if self.p.log_monitoring:
            self._log_event(
                "monitor",
                "monitoring_summary",
                level="INFO",
                details=dict(self._monitoring),
            )

        self._log_event(
            "system",
            "session_stopped",
            level="INFO",
            details={"observer": self.__class__.__name__},
        )

        # Save final position snapshot
        if self.p.log_position_snapshot:
            self._save_position_snapshot()

        # Close MySQL connection
        if self._mysql_conn:
            try:
                self._mysql_conn.close()
            except Exception as e:
                logger.debug("Failed to close MySQL connection: %s", e)
