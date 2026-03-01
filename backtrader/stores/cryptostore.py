"""Crypto Store Module - bt_api_py integration.

This module provides the CryptoStore for connecting to bt_api_py
for cryptocurrency trading.

Classes:
    CryptoStore: Store for bt_api_py connections.

Example:
    >>> exchange_params = {...}
    >>> store = bt.stores.CryptoStore(exchange_params)
    >>> cerebro.setbroker(store.getbroker())
"""

import queue
import time
import traceback
from datetime import datetime, timedelta, timezone

from bt_api_py.bt_api import BtApi
from bt_api_py.containers import BarData, OrderData, RequestData, TradeData
from bt_api_py.functions.log_message import SpdLogManager


# class CryptoStore(with_metaclass(MetaSingleton, object)):
class CryptoStore:
    """Store for bt_api_py cryptocurrency exchange connections.

    This store manages connections to cryptocurrency exchanges via the bt_api_py
    library, handling data feeds, order management, and account information.

    Attributes:
        BrokerCls: Broker class for auto-registration.
        DataCls: Data class for auto-registration.
        GetDataNum: Counter for data instances created.
        kwargs: Exchange connection parameters.
        feed_api: BtApi instance for exchange communication.
        data_queues: Dictionary of data queues from feed API.
        exchange_feeds: Dictionary of exchange feed instances.
        debug: Boolean flag for debug mode.
        logger: Logger instance for logging.
        subscribe_bar_num: Number of subscribed bar feeds.
        cache_bar_dict: Dictionary for caching bar data.
        bar_queues: Dictionary of bar queues.
        order_queue: Queue for order data.
        trade_queue: Queue for trade data.
        crypto_datas: Dictionary of crypto data instances.
    """

    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register

    def getdata(self, *args, **kwargs):
        """Returns ``DataCls`` with args, kwargs"""
        self.GetDataNum += 1
        return self.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered ``BrokerCls``"""
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self, exchange_params, debug=True, *args, **kwargs):
        """Initialize the CryptoStore.

        Args:
            exchange_params: Dictionary containing exchange connection parameters
                including API keys, exchange name, and other configuration.
            debug: Boolean flag for debug mode. Defaults to True.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        """
        super().__init__(*args, **kwargs)
        self.GetDataNum = 0
        self.kwargs = exchange_params
        self.feed_api = BtApi(exchange_params, debug=debug)
        self.data_queues = self.feed_api.data_queues
        self.exchange_feeds = self.feed_api.exchange_feeds
        self.debug = debug
        self.logger = self.init_logger()
        self.subscribe_bar_num = 0
        self.cache_bar_dict = {}
        self.bar_queues = {}
        self.order_queue = queue.Queue()
        self.trade_queue = queue.Queue()
        self.feed_api.update_total_balance()
        self.crypto_datas = {}
        self.log(f"value = {self.feed_api.get_total_value()}")
        self.log(f"cash = {self.feed_api.get_total_cash()}")
        self.log(f"feed_api.keys() = {self.feed_api.exchange_feeds.keys()}")
        self.log("------crypto store initialized successfully------")

    def init_logger(self):
        """Initialize the logger for the store.

        Returns:
            SpdLogManager: Configured logger instance. Logs are written to
                'cryptofeed.log' file and optionally printed to console based
                on debug mode.
        """
        if self.debug:
            print_info = True
        else:
            print_info = False
        logger = SpdLogManager(
            file_name="cryptofeed.log", logger_name="feed", print_info=print_info
        ).create_logger()
        return logger

    def log(self, txt, level="info"):
        """Log a message at the specified level.

        Args:
            txt: The message text to log.
            level: The logging level. Must be one of 'info', 'warning', 'error',
                or 'debug'. Defaults to 'info'.
        """
        if level == "info":
            self.logger.info(txt)
        elif level == "warning":
            self.logger.warning(txt)
        elif level == "error":
            self.logger.error(txt)
        elif level == "debug":
            self.logger.debug(txt)
        else:
            pass

    @staticmethod
    def dispatch_data_to_queue(data, queues):
        """Dispatch market data to appropriate queues based on data type.

        This static method processes different types of market data (RequestData
        and BarData) and routes them to the appropriate queue based on exchange
        name, asset type, and symbol.

        Args:
            data: Market data object (RequestData or BarData).
            queues: Dictionary of queues keyed by 'exchange___asset_type___symbol'.
        """
        if isinstance(data, RequestData):
            # print("push history bars to queue")  # Removed for performance
            data.init_data()
            for data in data.get_data():
                exchange_name = data.get_exchange_name()
                asset_type = data.get_asset_type()
                symbol = data.get_symbol_name()
                if "-" not in symbol:
                    if "USDT" in symbol:
                        symbol = symbol.replace("USDT", "-USDT")
                    if "USDC" in symbol:
                        symbol = symbol.replace("USDC", "-USDC")
                if "SWAP" in symbol:
                    symbol = symbol.replace("-SWAP", "")
                if "SPOT" in symbol:
                    symbol = symbol.replace("-SPOT", "")
                key_name = exchange_name + "___" + asset_type + "___" + symbol
                if key_name not in queues:
                    queues[key_name] = queue.Queue()
                    # print(f"{key_name} queue created!, queues.keys() = {queues.keys()}")  # Removed for performance
                q = queues[key_name]
                q.put(data)
        elif isinstance(data, BarData):
            data.init_data()
            exchange_name = data.get_exchange_name()
            asset_type = data.get_asset_type()
            symbol = data.get_symbol_name()
            if "-" not in symbol:
                if "USDT" in symbol:
                    symbol = symbol.replace("USDT", "-USDT")
                if "USDC" in symbol:
                    symbol = symbol.replace("USDC", "-USDC")
            if "SWAP" in symbol:
                symbol = symbol.replace("-SWAP", "")
            if "SPOT" in symbol:
                symbol = symbol.replace("-SPOT", "")
            key_name = exchange_name + "___" + asset_type + "___" + symbol
            if key_name not in queues:
                queues[key_name] = queue.Queue()
                # print(f"{key_name} queue created!, queues.keys() = {queues.keys()}")  # Removed for performance
            q = queues[key_name]
            q.put(data)

    def deal_data_feed(self):
        """Process data and distribute to appropriate queues"""
        if self.subscribe_bar_num == self.GetDataNum:
            for exchange_name, data_queue in self.data_queues.items():
                # self.log(f"deal data feed, run {exchange_name}, total_keys = {self.data_queues.keys()}")
                self._load_cache_data(data_queue)

    def _load_cache_data(self, data_queue):
        while True:
            try:
                data = data_queue.get(block=False)  # Non-blocking
            except queue.Empty:
                return None  # no data in the queue
            data.init_data()
            # if data.get_bar_status():
            #     self.log(f"{self.data_queues.keys()}")
            #     self.log(f"cryptostore push test info: {data.get_all_data()}")
            # self.log(f"{self.bar_queues} , {self.subscribe_bar_num}")
            if not isinstance(data, BarData):
                pass
                # print(data)  # Removed for performance
            if isinstance(data, BarData):
                queues = self.bar_queues
                exchange = data.get_exchange_name()
                asset_type = data.get_asset_type()
                symbol = data.get_symbol_name()
                bar_status = data.get_bar_status()
                bar_timestamp = data.get_open_time()
                # self.log(f"begin to run live data, {self.subscribe_bar_num}, {self.GetDataNum}")
                # if bar_status:
                #     all_data = data.get_all_data()
                #     timestamp = all_data["open_time"]
                #     # dtime_utc = datetime.fromtimestamp(timestamp // 1000, tz=UTC)
                #     # Convert timestamp to UTC time (ensure it's UTC time)
                #     dtime_utc = datetime.fromtimestamp(timestamp // 1000, tz=pytz.UTC)
                #     # self.log(f"cryptostore subscribe test {dtime_utc}, info: {all_data}")
                if "-" not in symbol:
                    if "USDT" in symbol:
                        symbol = symbol.replace("USDT", "-USDT")
                    if "USDC" in symbol:
                        symbol = symbol.replace("USDC", "-USDC")
                if "SWAP" in symbol:
                    symbol = symbol.replace("-SWAP", "")
                if "SPOT" in symbol:
                    symbol = symbol.replace("-SPOT", "")
                key_name = exchange + "___" + asset_type + "___" + symbol
                # crypto_feed_instance = self.crypto_datas.get(key_name, None)
                # if crypto_feed_instance:
                #     now_bar_time = crypto_feed_instance.get_bar_time()
                #     if now_bar_time and data.get_open_time() <= now_bar_time:
                #         continue
                # Process real-time data pushed by WebSocket
                if len(self.bar_queues) > 1:
                    if bar_status:
                        if bar_timestamp not in self.cache_bar_dict:
                            self.cache_bar_dict[bar_timestamp] = {}
                        self.cache_bar_dict[bar_timestamp][key_name] = data
                        # self.log(f"cache bar info: {self.cache_bar_dict}")
                    # If only one timestamp currently exists
                    if len(self.cache_bar_dict) == 1:
                        bar_timestamp_list = list(self.cache_bar_dict.keys())
                        for bar_timestamp in bar_timestamp_list:
                            value_dict = self.cache_bar_dict[bar_timestamp]
                            # self.log(f"cache bar length: {len(value_dict)}, {self.subscribe_bar_num}")
                            if len(value_dict) == self.subscribe_bar_num:
                                for key_name, data in value_dict.items():
                                    q = queues[key_name]
                                    q.put(data)
                                self.cache_bar_dict.pop(bar_timestamp)

                    # If there are two or more K-line timestamps, remove the earliest one
                    if len(self.cache_bar_dict) > 1:
                        min_timestamp = min(self.cache_bar_dict.keys())
                        for key_name, data in self.cache_bar_dict[min_timestamp].items():
                            q = queues[key_name]
                            q.put(data)
                            self.cache_bar_dict.pop(min_timestamp)
                else:
                    CryptoStore.dispatch_data_to_queue(data, queues)
                    # all_data = data.get_all_data()
                    # timestamp = all_data["open_time"]
                    # # dtime_utc = datetime.fromtimestamp(timestamp // 1000, tz=UTC)
                    # # Convert timestamp to UTC time (ensure it's UTC time)
                    # dtime_utc = datetime.fromtimestamp(timestamp // 1000, tz=pytz.UTC)
                    # bar_status = all_data["bar_status"]
                    # if bar_status:
                    #     self.log(f"cryptostore dispatch_data_to_queue test {dtime_utc} info: {all_data}")
            elif isinstance(data, OrderData):
                # print("get new order data", data)  # Removed for performance
                self.order_queue.put(data)

            elif isinstance(data, TradeData):
                self.trade_queue.put(data)
            else:
                data.init_data()
                self.log(f"unconsidered info:{data.get_all_data()}")

    def download_history_bars(
        self, dataname, granularity, count=100, start_time=None, end_time=None
    ):
        """Download historical bar data from the exchange.

        Args:
            dataname: Data name in format 'exchange___asset_type___symbol'.
            granularity: Time period for bars (e.g., '1m', '5m', '1H', '1D').
            count: Number of bars to download per request. Defaults to 100.
            start_time: Start time for data download. Can be string (ISO format)
                or datetime object. Defaults to None.
            end_time: End time for data download. Can be string (ISO format)
                or datetime object. Defaults to None (uses current time).

        Returns:
            list: List of BarData objects containing historical OHLCV data.

        Raises:
            ValueError: If an unsupported granularity period is provided.
            TypeError: If an unsupported time format is provided.
        """
        self.log(f"store {self.feed_api.exchange_feeds.keys()}")
        bar_data_list = []
        exchange, asset_type, symbol = dataname.split("___")
        exchange_name = exchange + "___" + asset_type

        def calculate_time_delta(period, count):
            """Dynamically calculate time delta based on period and count"""
            period_to_minutes = {
                "1m": 1,
                "3m": 3,
                "5m": 5,
                "15m": 15,
                "30m": 30,
                "1H": 60,
                "1D": 1440,  # 1 day = 24 hours = 1440 minutes
            }
            if period in period_to_minutes:
                total_minutes = period_to_minutes[period] * count
                # Convert to hours (optional)
                total_hours = int(total_minutes / 60)
                # Return timedelta object representing total time span
                return timedelta(hours=total_hours)
            raise ValueError(f"Unsupported period: {period}")

        def parse_time(input_time):
            """Parse time, supporting string and datetime types, and convert time to UTC"""
            if isinstance(input_time, str):
                local_time = datetime.fromisoformat(input_time)
                return local_time.astimezone(timezone.utc)
            elif isinstance(input_time, datetime):
                if input_time.tzinfo is None:
                    local_time = input_time.replace(tzinfo=timezone.utc).astimezone()
                else:
                    local_time = input_time
                return local_time.astimezone(timezone.utc)
            elif input_time is None:
                return None
            else:
                raise TypeError(f"Unsupported time format: {type(input_time)}")

        def update_stop_time(stop_time):
            """Update stop_time to current time to ensure recency"""
            now = datetime.now(timezone.utc)
            if stop_time is None or stop_time < now:
                return now
            return stop_time

        # Parse start time and end time as UTC
        begin_time = parse_time(start_time)
        stop_time = parse_time(end_time)

        # If no end time, align to current time based on granularity
        stop_time = update_stop_time(stop_time)

        feed = self.exchange_feeds[exchange_name]
        if begin_time is None and count is not None:
            # If no start time, only pass count to get the most recent 'count' bars
            data = feed.get_kline(symbol, granularity, count, extra_data=None)
            data.init_data()
            bar_data_list.extend(data.get_data())
            self.log(f"download completely:{exchange_name}, {symbol}, new {count} bar")
            return bar_data_list

        if begin_time is not None:
            # Download data in a loop
            while begin_time < stop_time:
                try:
                    # Calculate end time for current time period
                    time_delta = calculate_time_delta(granularity, count)
                    current_end_time = min(begin_time + time_delta, stop_time)

                    # Convert timestamps to milliseconds
                    begin_stamp = int(1000.0 * begin_time.timestamp())
                    end_stamp = int(1000.0 * current_end_time.timestamp())

                    # Download data
                    data = feed.get_kline(
                        symbol,
                        granularity,
                        count=count,
                        start_time=begin_stamp,
                        end_time=end_stamp,
                        extra_data=None,
                    )
                    bar_data = data.get_data()
                    # print("symbol = ", symbol, "period = ", granularity, "count = ", count, start_time, end_time)  # Removed for performance
                    # print("bar_data", type(bar_data), bar_data)  # Removed for performance
                    bar_data_list.extend(bar_data)
                    self.log(
                        f"download successfully:{exchange_name}, {symbol}, period: {granularity}, "
                        f"begin: {begin_time}, end: {current_end_time}"
                    )
                    new_data = feed.get_kline(
                        "BTC-USDT", "15m", 2, start_time=begin_stamp, end_time=end_stamp
                    )
                    new_data.get_data()
                    # print("new_bar_data", type(new_bar_list), new_bar_list)  # Removed for performance
                    assert 0
                    time.sleep(0.2)
                    # Update start time
                    begin_time = current_end_time
                    # time.sleep(0.1)
                    # If data download is complete, exit loop
                    if begin_time >= stop_time:
                        break
                except Exception as e:
                    error_info = traceback.format_exception(type(e), e, e.__traceback__)
                    self.log(f"download fail, retry: {error_info}")
                    time.sleep(3)  # Pause for 3 seconds before retry

            self.log(
                f"download all data completely:{exchange_name}, {symbol}, period: {granularity}"
            )
        return bar_data_list

    def getcash(self, cache=True):
        """Get the total cash balance in the account.

        Args:
            cache: If True, returns cached cash value without updating balance.
                If False, updates balance from exchange before returning. Defaults
                to True.

        Returns:
            float: Total cash balance in the account.
        """
        if cache is True:
            return self.feed_api.get_total_cash()
        else:
            self.feed_api.update_total_balance()
            return self.feed_api.get_total_cash()

    def getvalue(self, cache=True):
        """Get the total account value (cash + holdings).

        Args:
            cache: If True, returns cached value without updating balance.
                If False, updates balance from exchange before returning. Defaults
                to True.

        Returns:
            float: Total account value including cash and holdings.
        """
        if cache is True:
            return self.feed_api.get_total_value()
        else:
            self.feed_api.update_total_balance()
            return self.feed_api.get_total_value()

    # Used to get unfilled order information
    def get_open_orders(self, data=None):
        """Get unfilled/open orders from the exchange.

        Args:
            data: Optional data object to filter orders by symbol.

        Returns:
            list: List of open order objects. Currently returns None.
        """
        pass

    def make_order(
        self,
        data,
        vol,
        price=None,
        order_type="buy-limit",
        offset="open",
        post_only=False,
        client_order_id=None,
        extra_data=None,
        **kwargs,
    ):
        """Create and submit an order to the exchange.

        Args:
            data: Data object containing exchange and symbol information.
            vol: Order volume/quantity.
            price: Order price. Required for limit orders. Defaults to None.
            order_type: Type of order (e.g., 'buy-limit', 'sell-market').
                Defaults to 'buy-limit'.
            offset: Order offset, 'open' for opening positions, 'close' for
                closing positions. Defaults to 'open'.
            post_only: If True, order will only be a maker (no taker fee).
                Defaults to False.
            client_order_id: Optional client-defined order ID. Defaults to None.
            extra_data: Additional order data. Defaults to None.
            **kwargs: Additional keyword arguments for the exchange API.

        Returns:
            Order response from the exchange API.
        """
        exchange_name = data.get_exchange_name()
        exchange_api = self.exchange_feeds[exchange_name]
        symbol_name = data.get_symbol_name()
        # print(f"offset = {offset}")  # Removed for performance
        return exchange_api.make_order(
            symbol_name,
            vol,
            price,
            order_type,
            offset=offset,
            post_only=post_only,
            client_order_id=client_order_id,
            extra_data=extra_data,
            **kwargs,
        )

    def cancel_order(self, order):
        """Cancel an existing order on the exchange.

        Args:
            order: Order object containing exchange, symbol, and order ID information.

        Returns:
            Cancel order response from the exchange API.
        """
        # print("begin to cancel order")  # Removed for performance
        exchange_name = order.data.get_exchange_name()
        exchange_api = self.exchange_feeds[exchange_name]
        symbol_name = order.data.get_symbol_name()
        new_order = order.bt_api_data
        new_order.init_data()
        order_id = new_order.get_order_id()
        # print(f"order_id = {order_id}")  # Removed for performance
        # print(f"symbol_name = {symbol_name}")  # Removed for performance
        return exchange_api.cancel_order(symbol_name, order_id)
