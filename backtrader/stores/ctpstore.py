#!/usr/bin/env python
"""CTP Store Module - CTP futures trading.

This module provides the CTPStore for connecting to CTP (China Futures)
through ctpbee for futures trading.

Classes:
    MyCtpbeeApi: Custom CTP API wrapper.
    CTPStore: Singleton store for CTP connections.

Example:
    >>> store = bt.stores.CTPStore(
    ...     userid='your_id',
    ...     password='your_password',
    ...     brokerid='your_broker'
    ... )
    >>> cerebro.setbroker(store.getbroker())
"""

import logging
import threading
from time import sleep

import numpy as np
from ctpbee import CtpBee, CtpbeeApi
from ctpbee.constant import (
    AccountData,
    BarData,
    CancelRequest,
    ContractData,
    Direction,
    Exchange,
    LogData,
    Offset,
    OrderData,
    OrderRequest,
    OrderType,
    PositionData,
    Status,
    TickData,
    TradeData,
)
from ctpbee.func import Helper as CtpHelper
from ctpbee.helpers import datetime2timestamp, get_last_timeframe_timestamp, timestamp2datetime

from backtrader.mixins import ParameterizedSingletonMixin
from backtrader.utils.py3 import queue

logger = logging.getLogger(__name__)


class MyCtpbeeApi(CtpbeeApi):
    """Custom CTP API wrapper for handling CTP events and market data.

    This class extends CtpbeeApi to provide custom handling for tick data,
    bar data, orders, trades, positions, and account information from the
    CTP (China Futures) market.

    Attributes:
        md_queue: Market data queue for distributing bar data to feeds.
        order_queue: Queue for order status update events.
        trade_queue: Queue for trade fill events.
        is_position_ok: Flag indicating if position data has been received.
        is_account_ok: Flag indicating if account data has been received.
    """

    def __init__(self, name, timeframe=None, compression=None, md_queue=None,
                 order_queue=None, trade_queue=None):
        """Initialize the MyCtpbeeApi instance.

        Args:
            name: Name/identifier for this API instance.
            timeframe: Bar timeframe (4=minutes, 5=days, others=1min default).
            compression: Bar compression multiplier (e.g., 5 for 5-minute bars).
            md_queue: Market data queue for distributing bar data to feeds.
            order_queue: Queue for order status update events.
            trade_queue: Queue for trade fill events.
        """
        super().__init__(name)
        self.md_queue = md_queue  # Market data queue
        self.order_queue = order_queue
        self.trade_queue = trade_queue
        self.is_position_ok = False
        self.is_account_ok = False
        self._bar_timeframe = timeframe
        self._bar_compression = compression
        self._bar_begin_time = None
        self._bar_end_time = None
        self._bar_interval = None
        self._data_name = None
        self.time_diff = None
        # Contract info cache: local_symbol -> ContractData
        self.contracts = {}
        # Bar update market data
        self.bar_datetime = None
        self.bar_open_price = 0.0
        self.bar_high_price = -np.inf
        self.bar_low_price = np.inf
        self.bar_close_price = 0.0
        self.bar_volume = 0.0

    def subscribe(self, dataname, timeframe, compression):
        """Subscribe to market data for a specific instrument.

        Args:
            dataname: Instrument symbol to subscribe to.
            timeframe: Bar timeframe code (4=minutes, 5=days).
            compression: Bar compression multiplier (e.g., 5 for 5-minute bars).

        Note:
            This sets up the bar interval calculation based on the timeframe and
            compression. Timeframe 4 is for minutes, 5 is for days, and any other
            value defaults to 1-minute bars.
        """
        # print(f"------Start subscribing to data------")  # Removed for performance
        if dataname is not None:
            self.action.subscribe(dataname)
            self._bar_timeframe = timeframe
            self._bar_compression = compression
            self._data_name = dataname
            # print(f"-----Successfully subscribed to data {dataname},{timeframe},{compression}--------")  # Removed for performance
            if self._bar_timeframe == 4:
                self.time_diff = 60 * self._bar_compression
                self._bar_interval = str(self._bar_compression) + "m"
            # If daily timeframe
            elif self._bar_timeframe == 5:
                self.time_diff = 86400 * self._bar_compression
                self._bar_interval = str(self._bar_compression) + "d"
            # If other timeframes, default is one minute
            else:
                self.time_diff = 60
                self._bar_interval = "1m"

    def on_contract(self, contract: ContractData):
        """Handle pushed contract information, cache for later use."""
        if hasattr(contract, 'local_symbol') and contract.local_symbol:
            self.contracts[contract.local_symbol] = contract
        if hasattr(contract, 'symbol') and contract.symbol:
            self.contracts[contract.symbol] = contract

    def on_log(self, log: LogData):
        """Handle log messages."""
        if hasattr(log, 'msg'):
            logger.debug(f"[CTP] {log.msg}")

    def on_tick(self, tick: TickData) -> None:
        """Handle pushed tick data"""
        # print('on_tick: ', tick)
        # print(f"Enter on_tick, {tick.datetime}")
        # If bar end time is None, need to calculate bar end time
        if self._bar_end_time is None:
            # Get the most recent bar update time, then calculate bar end time
            nts = datetime2timestamp(tick.datetime)
            self._bar_begin_time = get_last_timeframe_timestamp(int(nts), self.time_diff)
            self._bar_end_time = self._bar_begin_time + self.time_diff
            self._bar_end_time = timestamp2datetime(self._bar_begin_time)

        # If current tick time is greater than or equal to bar end time, push bar to queue, otherwise update kline
        nts = tick.datetime
        # print(f"nts = {nts}, self._bar_begin_time = {self._bar_begin_time}, self._bar_end_time = {self._bar_end_time}")
        if nts >= self._bar_end_time:
            bar = BarData._create_class(
                {
                    "symbol": tick.symbol,
                    "exchange": tick.exchange,
                    "datetime": tick.datetime,
                    "interval": self._bar_interval,
                    "volume": self.bar_volume,
                    "open_price": self.bar_open_price,
                    "high_price": self.bar_high_price,
                    "low_price": self.bar_low_price,
                    "close_price": self.bar_close_price,
                }
            )
            self.md_queue[self._data_name].put(bar)
            self.bar_datetime = self._bar_begin_time
            self.bar_open_price = tick.last_price
            self.bar_high_price = tick.last_price
            self.bar_low_price = tick.last_price
            self.bar_close_price = tick.last_price
            self.bar_volume = tick.volume
            self._bar_begin_time = self._bar_end_time
            self._bar_end_time = timestamp2datetime(
                datetime2timestamp(self._bar_end_time) + self.time_diff
            )
        else:
            self.bar_datetime = self._bar_begin_time
            self.bar_high_price = max(self.bar_high_price, tick.last_price)
            self.bar_low_price = min(self.bar_low_price, tick.last_price)
            self.bar_close_price = tick.last_price
            self.bar_volume += tick.volume

    def on_bar(self, bar: BarData) -> None:
        """Handle bar generated by ctpbee"""
        print(
            "on_bar: ",
            bar.local_symbol,
            bar.datetime,
            bar.open_price,
            bar.high_price,
            bar.low_price,
            bar.close_price,
            bar.volume,
            bar.interval,
        )
        self.md_queue[bar.local_symbol].put(bar)  # Distribute market data to corresponding queue

    def on_init(self, init):
        """Handle initialization event from CTP API.

        Args:
            init: Initialization status/information from CTP.
        """
        pass

    def on_order(self, order: OrderData) -> None:
        """Handle order response — push to order_queue for CTPBroker to process."""
        logger.debug(f"[CTP] on_order: {order.order_id} status={order.status} "
                     f"symbol={order.symbol} dir={order.direction} "
                     f"price={order.price} vol={order.volume}")
        if self.order_queue is not None:
            self.order_queue.put(order)

    def on_trade(self, trade: TradeData) -> None:
        """Handle trade response — push to trade_queue for CTPBroker to process."""
        logger.debug(f"[CTP] on_trade: {trade.order_id} symbol={trade.symbol} "
                     f"dir={trade.direction} price={trade.price} vol={trade.volume}")
        if self.trade_queue is not None:
            self.trade_queue.put(trade)

    def on_position(self, position: PositionData) -> None:
        """Handle position response."""
        self.is_position_ok = True

    def on_account(self, account: AccountData) -> None:
        """Handle account information."""
        self.is_account_ok = True


class CTPStore(ParameterizedSingletonMixin):
    """
    Singleton class wrapping CTP connection using ParameterizedSingletonMixin.

    This class now uses ParameterizedSingletonMixin instead of MetaSingleton metaclass
    to implement the singleton pattern. This provides the same functionality without
    metaclasses while maintaining full backward compatibility.
    """

    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register

    params = (("debug", False),)

    @classmethod
    def getdata(cls, *args, **kwargs):
        """Returns `DataCls` with args, kwargs"""
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered `BrokerCls`"""
        return cls.BrokerCls(*args, **kwargs)

    # Exchange mapping: symbol suffix/prefix -> ctpbee Exchange enum
    EXCHANGE_MAP = {
        'SHFE': Exchange.SHFE,
        'DCE': Exchange.DCE,
        'CZCE': Exchange.CZCE,
        'CFFEX': Exchange.CFFEX,
        'INE': Exchange.INE,
        'GFEX': Exchange.GFEX,
    }

    def __init__(self, ctp_setting=None, *args, **kwargs):
        """Initialize the CTPStore instance.

        Args:
            ctp_setting: Dictionary containing CTP connection settings including
                userid, password, brokerid, and other connection parameters.
            *args: Additional positional arguments (unused).
            **kwargs: Additional keyword arguments (unused).

        Note:
            This initializes the CtpBee app with the provided settings and waits
            for the account information to be loaded before returning.
        """
        super().__init__()
        # Connection settings
        if ctp_setting is None:
            ctp_setting = kwargs.get('ctp_setting', {})
        self.ctp_setting = ctp_setting
        self._is_connected = False
        self._stopped = False
        # Initial values
        self._cash = 0.0
        self._value = 0.0
        # Order/trade event queues for broker
        self.order_queue = queue.Queue()
        self.trade_queue = queue.Queue()
        # Feed market data queue dictionary
        self.q_feed_qlive = dict()
        # CTP order_id -> backtrader order ref mapping
        self._order_id_map = {}  # ctp_order_id -> bt_order_ref
        self._lock = threading.Lock()

        self.main_ctpbee_api = MyCtpbeeApi(
            "main_ctpbee_api",
            md_queue=self.q_feed_qlive,
            order_queue=self.order_queue,
            trade_queue=self.trade_queue,
        )
        self.app = CtpBee("ctpstore", __name__, refresh=True)
        self.app.config.from_mapping(ctp_setting)
        self.app.add_extension(self.main_ctpbee_api)
        self.app.start(log_output=True)
        # Wait for account data to be ready
        timeout = 30
        waited = 0
        while waited < timeout:
            sleep(1)
            waited += 1
            if self.main_ctpbee_api.is_account_ok:
                break
        if not self.main_ctpbee_api.is_account_ok:
            logger.warning("[CTPStore] Timeout waiting for account data")
        self._is_connected = True
        logger.info(f"[CTPStore] Connected. positions={self.main_ctpbee_api.center.positions}")
        logger.info(f"[CTPStore] account={self.main_ctpbee_api.center.account}")

    def register(self, feed):
        """Register feed market data queue, pass feed, create a queue for it, and add to dictionary"""
        self.q_feed_qlive[feed.p.dataname] = queue.Queue()
        return self.q_feed_qlive[feed.p.dataname]

    # def subscribe(self, data):
    #     print(f"------Start subscribing to data------")
    #     if data is not None:
    #         self.main_ctpbee_api.action.subscribe(data.p.dataname)
    #         print(f"-----Successfully subscribed to data {data.p.dataname}--------")

    def stop(self):
        """Stop the CTP store and disconnect from CTP."""
        if self._stopped:
            return
        self._stopped = True
        self._is_connected = False
        try:
            self.app.release()
        except Exception as e:
            logger.warning(f"[CTPStore] Error during release: {e}")
        logger.info("[CTPStore] Stopped")

    @property
    def is_connected(self):
        return self._is_connected and not self._stopped

    def _detect_exchange(self, symbol):
        """Detect the exchange for a given symbol.

        Args:
            symbol: Instrument symbol, e.g. 'rb2501.SHFE' or 'rb2501'

        Returns:
            Exchange enum value, or Exchange.SHFE as default.
        """
        if '.' in symbol:
            parts = symbol.split('.')
            exchange_str = parts[-1].upper()
            if exchange_str in self.EXCHANGE_MAP:
                return self.EXCHANGE_MAP[exchange_str]
        # Try to detect from contract cache
        pure_symbol = symbol.split('.')[0] if '.' in symbol else symbol
        contract = self.main_ctpbee_api.contracts.get(pure_symbol)
        if contract and hasattr(contract, 'exchange'):
            return contract.exchange
        # Default
        return Exchange.SHFE

    def send_order(self, symbol, direction, offset, order_type, volume, price):
        """Send an order to CTP via ctpbee.

        Args:
            symbol: Instrument symbol (e.g. 'rb2501.SHFE' or 'rb2501').
            direction: ctpbee Direction enum (LONG or SHORT).
            offset: ctpbee Offset enum (OPEN, CLOSE, CLOSETODAY, CLOSEYESTERDAY).
            order_type: ctpbee OrderType enum (LIMIT, MARKET).
            volume: Number of contracts.
            price: Order price.

        Returns:
            str: CTP order ID, or None on failure.
        """
        exchange = self._detect_exchange(symbol)
        pure_symbol = symbol.split('.')[0] if '.' in symbol else symbol

        req = OrderRequest(
            symbol=pure_symbol,
            exchange=exchange,
            direction=direction,
            offset=offset,
            type=order_type,
            volume=volume,
            price=price,
        )
        try:
            order_id = self.main_ctpbee_api.action.send_order(req)
            logger.info(f"[CTPStore] send_order: {pure_symbol} {direction} {offset} "
                        f"price={price} vol={volume} -> order_id={order_id}")
            return order_id
        except Exception as e:
            logger.error(f"[CTPStore] send_order failed: {e}")
            return None

    def cancel_order(self, symbol, order_id):
        """Cancel an order on CTP.

        Args:
            symbol: Instrument symbol.
            order_id: CTP order ID string.

        Returns:
            bool: True if cancel request was sent successfully.
        """
        exchange = self._detect_exchange(symbol)
        pure_symbol = symbol.split('.')[0] if '.' in symbol else symbol

        req = CancelRequest(
            symbol=pure_symbol,
            exchange=exchange,
            order_id=order_id,
        )
        try:
            self.main_ctpbee_api.action.cancel_order(req)
            logger.info(f"[CTPStore] cancel_order: {order_id} symbol={pure_symbol}")
            return True
        except Exception as e:
            logger.error(f"[CTPStore] cancel_order failed: {e}")
            return False

    def get_positions(self):
        """Get current positions from CTP.

        Returns:
            list: Position data from CTP center.
        """
        try:
            positions = self.main_ctpbee_api.center.positions
            return positions
        except Exception as e:
            logger.error(f"[CTPStore] get_positions failed: {e}")
            return []

    def get_balance(self):
        """Get account balance information from CTP.

        Updates the internal cash and value attributes from the CTP account.
        """
        try:
            account = self.main_ctpbee_api.center.account
            self._cash = account.available
            self._value = account.balance
        except Exception as e:
            logger.error(f"[CTPStore] get_balance failed: {e}")

    def get_cash(self):
        """Get available cash from the account."""
        return self._cash

    def get_value(self):
        """Get total account value."""
        return self._value
