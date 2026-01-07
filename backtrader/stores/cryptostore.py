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
    """bt_api_py and backtrader store"""

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
        if self.debug:
            print_info = True
        else:
            print_info = False
        logger = SpdLogManager(
            file_name="cryptofeed.log", logger_name="feed", print_info=print_info
        ).create_logger()
        return logger

    def log(self, txt, level="info"):
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
                    error_info = traceback.format_exception(e)
                    self.log(f"download fail, retry: {error_info}")
                    time.sleep(3)  # Pause for 3 seconds before retry

            self.log(
                f"download all data completely:{exchange_name}, {symbol}, period: {granularity}"
            )
        return bar_data_list

    def getcash(self, cache=True):
        if cache is True:
            return self.feed_api.get_total_cash()
        else:
            self.feed_api.update_total_balance()
            return self.feed_api.get_total_cash()

    def getvalue(self, cache=True):
        if cache is True:
            return self.feed_api.get_total_value()
        else:
            self.feed_api.update_total_balance()
            return self.feed_api.get_total_value()

    # Used to get unfilled order information
    def get_open_orders(self, data=None):
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
