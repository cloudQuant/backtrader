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

import json
import logging
import os
from datetime import datetime

from ..observer import Observer

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
    lines = ('dummy',)  # Observer requires at least one line

    params = dict(
        # File logging settings
        log_dir='./logs',
        log_orders=True,
        log_trades=True,
        log_positions=True,
        log_indicators=True,
        log_signals=True,
        log_position_snapshot=True,
        snapshot_file='current_position.yaml',
        log_format='json',
        log_to_console=False,

        # MySQL settings - disabled by default
        mysql_enabled=False,
        mysql_host='localhost',
        mysql_port=3306,
        mysql_user='root',
        mysql_password='',
        mysql_database='backtrader',
    )

    def __init__(self):
        """Initialize the TradeLogger observer."""
        super().__init__()
        # CRITICAL: Set _ltype AFTER super().__init__() and ensure registration
        self._ltype = 2  # LineIterator.ObsType
        # Register self to owner's _lineiterators if not already done
        if hasattr(self, '_owner') and self._owner is not None:
            if hasattr(self._owner, '_lineiterators'):
                if self._ltype in self._owner._lineiterators:
                    if self not in self._owner._lineiterators[self._ltype]:
                        self._owner._lineiterators[self._ltype].append(self)
        self._order_logger = None
        self._trade_logger = None
        self._position_logger = None
        self._indicator_logger = None
        self._signal_logger = None
        self._mysql_conn = None
        self._last_position_state = {}
        self._loggers_initialized = False

    def start(self):
        """Called at the start of the backtest/live run."""
        # CRITICAL: Ensure registration to _lineiterators for next() to be called
        self._ltype = 2  # LineIterator.ObsType
        if hasattr(self, '_owner') and self._owner is not None:
            if hasattr(self._owner, '_lineiterators'):
                if self._ltype in self._owner._lineiterators:
                    if self not in self._owner._lineiterators[self._ltype]:
                        self._owner._lineiterators[self._ltype].append(self)
        self._ensure_loggers_initialized()

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
                'bt_order', os.path.join(self.p.log_dir, 'order.log'))

        if self.p.log_trades:
            self._trade_logger = self._create_file_logger(
                'bt_trade', os.path.join(self.p.log_dir, 'trade.log'))

        if self.p.log_positions:
            self._position_logger = self._create_file_logger(
                'bt_position', os.path.join(self.p.log_dir, 'position.log'))

        if self.p.log_indicators:
            self._indicator_logger = self._create_file_logger(
                'bt_indicator', os.path.join(self.p.log_dir, 'indicator.log'))

        if self.p.log_signals:
            self._signal_logger = self._create_file_logger(
                'bt_signal', os.path.join(self.p.log_dir, 'signal.log'))

    def _create_file_logger(self, name, file_path):
        """Create a file logger using Python standard logging.

        Args:
            name: Logger name
            file_path: Path to log file

        Returns:
            logging.Logger instance
        """
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.handlers = []  # Clear existing handlers

        # File handler - write to file
        file_handler = logging.FileHandler(file_path, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(file_handler)

        # Console handler - optional
        if self.p.log_to_console:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(logging.Formatter('[%(name)s] %(message)s'))
            logger.addHandler(console_handler)

        return logger

    def _init_mysql(self):
        """Initialize MySQL connection and create tables."""
        if not MYSQL_AVAILABLE:
            print("[TradeLogger] Warning: pymysql not installed, MySQL logging disabled")
            return

        try:
            self._mysql_conn = pymysql.connect(
                host=self.p.mysql_host,
                port=self.p.mysql_port,
                user=self.p.mysql_user,
                password=self.p.mysql_password,
                database=self.p.mysql_database,
                charset='utf8mb4',
                autocommit=True
            )
            self._create_mysql_tables()
        except Exception as e:
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
        except Exception:
            return str(datetime.now())

    def _get_strategy_name(self):
        """Get the strategy class name."""
        try:
            return self._owner.__class__.__name__
        except Exception:
            return 'Unknown'

    def next(self):
        """Called on every bar - log positions and indicators."""
        self._ensure_loggers_initialized()

        # Set dummy line value (required for observer)
        self.lines.dummy[0] = 0

        try:
            if self.p.log_positions:
                self._log_positions()

            if self.p.log_indicators:
                self._log_indicators()

            if self.p.log_position_snapshot:
                self._save_position_snapshot()
        except Exception as e:
            import traceback
            if self.p.log_to_console:
                print(f"[TradeLogger] Error in next(): {e}")
                traceback.print_exc()

    def notify_order(self, order):
        """Log order status changes."""
        self._ensure_loggers_initialized()
        
        if not self.p.log_orders:
            return

        log_data = self._format_order(order)

        # File logging
        if self._order_logger:
            if self.p.log_format == 'json':
                self._order_logger.info(json.dumps(log_data, ensure_ascii=False, default=str))
            else:
                self._order_logger.info(self._format_order_text(order))

        # MySQL logging
        if self.p.mysql_enabled and self._mysql_conn:
            self._insert_order_mysql(log_data)

    def notify_trade(self, trade):
        """Log trade information."""
        self._ensure_loggers_initialized()
        
        if not self.p.log_trades:
            return

        log_data = self._format_trade(trade)

        # File logging
        if self._trade_logger:
            if self.p.log_format == 'json':
                self._trade_logger.info(json.dumps(log_data, ensure_ascii=False, default=str))
            else:
                self._trade_logger.info(self._format_trade_text(trade))

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

        log_data = {
            'datetime': self._get_datetime_str(),
            'action': action,
            'size': size,
            'price': price,
            'data_name': data_name or (self._owner.data._name if hasattr(self._owner, 'data') else None),
            'reason': reason or '',
            'strategy_name': self._get_strategy_name(),
        }

        # File logging
        if self._signal_logger:
            if self.p.log_format == 'json':
                self._signal_logger.info(json.dumps(log_data, ensure_ascii=False, default=str))
            else:
                self._signal_logger.info(
                    f"{log_data['datetime']} | {action.upper()} | size={size} | "
                    f"price={price} | {reason or ''}"
                )

        # MySQL logging
        if self.p.mysql_enabled and self._mysql_conn:
            self._insert_signal_mysql(log_data)

    def _log_positions(self):
        """Log position information for all data feeds."""
        if not self._position_logger and not (self.p.mysql_enabled and self._mysql_conn):
            return

        if not hasattr(self, '_owner') or self._owner is None:
            return

        if not hasattr(self._owner, 'datas') or not self._owner.datas:
            return

        for data in self._owner.datas:
            position = self._owner.getposition(data)
            data_name = getattr(data, '_name', str(data))

            log_data = {
                'datetime': self._get_datetime_str(),
                'data_name': data_name,
                'size': position.size,
                'price': position.price,
                'value': position.size * data.close[0] if position.size != 0 else 0,
                'strategy_name': self._get_strategy_name(),
            }

            # File logging
            if self._position_logger:
                if self.p.log_format == 'json':
                    self._position_logger.info(json.dumps(log_data, ensure_ascii=False, default=str))
                else:
                    self._position_logger.info(
                        f"{log_data['datetime']} | {data_name} | "
                        f"size={position.size} | price={position.price:.4f} | "
                        f"value={log_data['value']:.2f}"
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
            'datetime': self._get_datetime_str(),
            'strategy_name': self._get_strategy_name(),
            **indicators_data
        }

        # File logging
        if self._indicator_logger:
            if self.p.log_format == 'json':
                self._indicator_logger.info(json.dumps(log_data, ensure_ascii=False, default=str))
            else:
                indicator_str = ' | '.join([f"{k}={v:.4f}" for k, v in indicators_data.items() if isinstance(v, (int, float))])
                self._indicator_logger.info(f"{log_data['datetime']} | {indicator_str}")

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
            if hasattr(self._owner, '_lineiterators'):
                for item in self._owner._lineiterators.get(self._owner.IndType, []):
                    self._extract_indicator_values(item, indicators)

            # Also check for indicators stored as attributes
            for attr_name in dir(self._owner):
                if attr_name.startswith('_'):
                    continue
                try:
                    attr = getattr(self._owner, attr_name)
                    if hasattr(attr, 'lines') and hasattr(attr, '__len__'):
                        self._extract_indicator_values(attr, indicators, attr_name)
                except Exception:
                    continue

        except Exception:
            pass

        return indicators

    def _extract_indicator_values(self, indicator, indicators_dict, prefix=''):
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
            if hasattr(indicator, 'lines'):
                for line_name in indicator.lines.getlinealiases():
                    try:
                        line = getattr(indicator.lines, line_name)
                        if len(line) > 0:
                            value = line[0]
                            if value is not None and not (hasattr(value, '__float__') and float(value) != float(value)):
                                full_name = f"{ind_name}_{line_name}" if line_name != ind_name.lower() else ind_name
                                indicators_dict[full_name] = float(value)
                    except Exception:
                        continue
        except Exception:
            pass

    def _save_position_snapshot(self):
        """Save current position snapshot to YAML file."""
        if not YAML_AVAILABLE:
            return

        snapshot = {
            'datetime': self._get_datetime_str(),
            'strategy': self._get_strategy_name(),
            'positions': {}
        }

        for data in self._owner.datas:
            position = self._owner.getposition(data)
            data_name = getattr(data, '_name', str(data))

            if position.size != 0:
                snapshot['positions'][data_name] = {
                    'size': position.size,
                    'price': round(position.price, 4),
                    'value': round(position.size * data.close[0], 2),
                    'current_price': round(data.close[0], 4),
                }

        snapshot_path = os.path.join(self.p.log_dir, self.p.snapshot_file)
        try:
            with open(snapshot_path, 'w', encoding='utf-8') as f:
                yaml.dump(snapshot, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            if self.p.log_to_console:
                print(f"[TradeLogger] Failed to save position snapshot: {e}")

    def _format_order(self, order):
        """Format order data for logging."""
        return {
            'datetime': self._get_datetime_str(),
            'ref': order.ref,
            'order_type': 'Buy' if order.isbuy() else 'Sell',
            'status': order.getstatusname(),
            'size': order.size,
            'price': order.price,
            'executed_price': order.executed.price if order.executed.size else None,
            'executed_size': order.executed.size,
            'executed_value': order.executed.value,
            'commission': order.executed.comm,
            'data_name': order.data._name if order.data else None,
            'strategy_name': self._get_strategy_name(),
        }

    def _format_order_text(self, order):
        """Format order data as text."""
        return (
            f"{self._get_datetime_str()} | "
            f"{'BUY' if order.isbuy() else 'SELL'} | "
            f"ref={order.ref} | status={order.getstatusname()} | "
            f"size={order.size} | price={order.price}"
        )

    def _format_trade(self, trade):
        """Format trade data for logging."""
        return {
            'datetime': self._get_datetime_str(),
            'ref': trade.ref,
            'data_name': trade.data._name,
            'size': trade.size,
            'price': trade.price,
            'value': trade.value,
            'pnl': trade.pnl,
            'pnlcomm': trade.pnlcomm,
            'commission': trade.commission,
            'isclosed': trade.isclosed,
            'isopen': trade.isopen,
            'baropen': trade.baropen,
            'barclose': trade.barclose if trade.isclosed else None,
            'barlen': trade.barlen,
            'strategy_name': self._get_strategy_name(),
        }

    def _format_trade_text(self, trade):
        """Format trade data as text."""
        status = 'CLOSED' if trade.isclosed else ('OPEN' if trade.isopen else 'UPDATE')
        return (
            f"{self._get_datetime_str()} | {status} | "
            f"ref={trade.ref} | data={trade.data._name} | "
            f"size={trade.size} | pnl={trade.pnl:.2f} | pnlcomm={trade.pnlcomm:.2f}"
        )

    def _insert_order_mysql(self, log_data):
        """Insert order record into MySQL."""
        if not self._mysql_conn:
            return

        try:
            cursor = self._mysql_conn.cursor()
            cursor.execute("""
                INSERT INTO bt_orders (datetime, ref, order_type, status, size, price,
                    executed_price, executed_size, executed_value, commission, data_name, strategy_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                log_data['datetime'], log_data['ref'], log_data['order_type'],
                log_data['status'], log_data['size'], log_data['price'],
                log_data['executed_price'], log_data['executed_size'],
                log_data['executed_value'], log_data['commission'],
                log_data['data_name'], log_data['strategy_name']
            ))
            cursor.close()
        except Exception as e:
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL insert order failed: {e}")

    def _insert_trade_mysql(self, log_data):
        """Insert trade record into MySQL."""
        if not self._mysql_conn:
            return

        try:
            cursor = self._mysql_conn.cursor()
            cursor.execute("""
                INSERT INTO bt_trades (datetime, ref, data_name, size, price, value,
                    pnl, pnlcomm, commission, isclosed, isopen, baropen, barclose, barlen, strategy_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                log_data['datetime'], log_data['ref'], log_data['data_name'],
                log_data['size'], log_data['price'], log_data['value'],
                log_data['pnl'], log_data['pnlcomm'], log_data['commission'],
                log_data['isclosed'], log_data['isopen'], log_data['baropen'],
                log_data['barclose'], log_data['barlen'], log_data['strategy_name']
            ))
            cursor.close()
        except Exception as e:
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL insert trade failed: {e}")

    def _insert_position_mysql(self, log_data):
        """Insert position record into MySQL."""
        if not self._mysql_conn:
            return

        try:
            cursor = self._mysql_conn.cursor()
            cursor.execute("""
                INSERT INTO bt_positions (datetime, data_name, size, price, value, strategy_name)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                log_data['datetime'], log_data['data_name'], log_data['size'],
                log_data['price'], log_data['value'], log_data['strategy_name']
            ))
            cursor.close()
        except Exception as e:
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL insert position failed: {e}")

    def _insert_indicator_mysql(self, indicator_name, indicator_value):
        """Insert indicator record into MySQL."""
        if not self._mysql_conn:
            return

        try:
            cursor = self._mysql_conn.cursor()
            cursor.execute("""
                INSERT INTO bt_indicators (datetime, indicator_name, indicator_value, strategy_name)
                VALUES (%s, %s, %s, %s)
            """, (
                self._get_datetime_str(), indicator_name, indicator_value,
                self._get_strategy_name()
            ))
            cursor.close()
        except Exception as e:
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL insert indicator failed: {e}")

    def _insert_signal_mysql(self, log_data):
        """Insert signal record into MySQL."""
        if not self._mysql_conn:
            return

        try:
            cursor = self._mysql_conn.cursor()
            cursor.execute("""
                INSERT INTO bt_signals (datetime, action, size, price, data_name, reason, strategy_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                log_data['datetime'], log_data['action'], log_data['size'],
                log_data['price'], log_data['data_name'], log_data['reason'],
                log_data['strategy_name']
            ))
            cursor.close()
        except Exception as e:
            if self.p.log_to_console:
                print(f"[TradeLogger] MySQL insert signal failed: {e}")

    def stop(self):
        """Called at the end of the backtest/live run."""
        # Save final position snapshot
        if self.p.log_position_snapshot:
            self._save_position_snapshot()

        # Close MySQL connection
        if self._mysql_conn:
            try:
                self._mysql_conn.close()
            except Exception:
                pass
