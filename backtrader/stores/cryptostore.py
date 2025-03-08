import queue
import threading
import time
import traceback

import pytz
import pandas as pd
from datetime import datetime, timedelta, timezone
from bt_api_py.containers import OrderData, BarData, TradeData, RequestData
from backtrader.store import MetaSingleton
from backtrader.utils.py3 import with_metaclass
from bt_api_py.bt_api import BtApi
from bt_api_py.functions.log_message import SpdLogManager


# class CryptoStore(with_metaclass(MetaSingleton, object)):
class CryptoStore(object):
    """bt_api_py and backtrader store
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
        logger = SpdLogManager(file_name='cryptofeed.log',
                               logger_name="feed",
                               print_info=print_info).create_logger()
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
            print("push history bars to queue")
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
                    print(f"{key_name} queue created!, queues.keys() = {queues.keys()}")
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
                print(f"{key_name} queue created!, queues.keys() = {queues.keys()}")
            q = queues[key_name]
            q.put(data)

    def deal_data_feed(self):
        """处理数据并分发到相应的队列"""
        if self.subscribe_bar_num == self.GetDataNum:
            for exchange_name, data_queue in self.data_queues.items():
                # self.log(f"deal data feed, run {exchange_name}, total_keys = {self.data_queues.keys()}")
                self._load_cache_data(data_queue)

    def _load_cache_data(self,data_queue):
        while True:
            try:
                data = data_queue.get(block=False)  # 不阻塞
            except queue.Empty:
                return None  # no data in the queue
            data.init_data()
            # if data.get_bar_status():
            #     self.log(f"{self.data_queues.keys()}")
            #     self.log(f"cryptostore push test info: {data.get_all_data()}")
                # self.log(f"{self.bar_queues} , {self.subscribe_bar_num}")
            if not isinstance(data, BarData):
                print(data)
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
                #     # 将时间戳转换为 UTC 时间（确保它是 UTC 时间）
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
                # 处理websocket推送的实时数据
                if len(self.bar_queues) > 1:
                    if bar_status:
                        if bar_timestamp not in self.cache_bar_dict:
                            self.cache_bar_dict[bar_timestamp] = {}
                        self.cache_bar_dict[bar_timestamp][key_name] = data
                        # self.log(f"cache bar info: {self.cache_bar_dict}")
                    # 如果当前仅存在一个时间
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

                    # 如果存在两个以上时间的K线了，就把最小时间清除了
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
                    # # 将时间戳转换为 UTC 时间（确保它是 UTC 时间）
                    # dtime_utc = datetime.fromtimestamp(timestamp // 1000, tz=pytz.UTC)
                    # bar_status = all_data["bar_status"]
                    # if bar_status:
                    #     self.log(f"cryptostore dispatch_data_to_queue test {dtime_utc} info: {all_data}")
            elif isinstance(data, OrderData):
                print("get new order data", data)
                self.order_queue.put(data)

            elif isinstance(data, TradeData):
                self.trade_queue.put(data)
            else:
                data.init_data()
                self.log(f"un considered info:{data.get_all_data()}")

    def download_history_bars(self, dataname, granularity, count=100, start_time=None, end_time=None):
        self.log(f"store {self.feed_api.exchange_feeds.keys()}")
        bar_data_list = []
        exchange, asset_type, symbol = dataname.split("___")
        exchange_name = exchange + "___" + asset_type

        def calculate_time_delta(period):
            """根据 period 计算增量时间"""
            time_deltas = {
                "1m": timedelta(hours=1),
                "3m": timedelta(hours=5),
                "5m": timedelta(hours=9),
                "15m": timedelta(hours=25),
                "30m": timedelta(hours=50),
                "1H": timedelta(hours=100),
                "1D": timedelta(days=100),
            }
            if period in time_deltas:
                return time_deltas[period]
            raise ValueError(f"Unsupported period: {period}")

        def parse_time(input_time):
            """解析时间，支持字符串和 datetime 类型，并将时间转换为 UTC"""
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
            """更新 stop_time 到当前时间，确保实时性"""
            now = datetime.now(timezone.utc)
            if stop_time is None or stop_time < now:
                return now
            return stop_time

        # 解析开始时间和结束时间为 UTC
        begin_time = parse_time(start_time)
        stop_time = parse_time(end_time)

        # 如果没有结束时间，则根据 granularity 对齐为当前时间
        stop_time = update_stop_time(stop_time)

        feed = self.exchange_feeds[exchange_name]
        if begin_time is None and count is not None:
            # 如果没有开始时间，只传入 count，获取最近 count 条数据
            data = feed.get_kline(symbol, granularity, count, extra_data=None)
            data.init_data()
            bar_data_list.extend(data.get_data())
            self.log(f"download completely:{exchange_name}, {symbol}, new {count} bar")
            return bar_data_list

        if begin_time is not None:
            # 循环下载数据
            while begin_time < stop_time:
                try:
                    # 计算当前时间段的结束时间
                    time_delta = calculate_time_delta(granularity)
                    current_end_time = min(begin_time + time_delta, stop_time)

                    # 转换时间戳为毫秒
                    begin_stamp = int(1000.0 * begin_time.timestamp())
                    end_stamp = int(1000.0 * current_end_time.timestamp())

                    # 下载数据
                    data = feed.get_kline(
                        symbol, granularity, start_time=begin_stamp, end_time=end_stamp, extra_data=None
                    )
                    bar_data_list.extend(data.get_data())
                    self.log(f"download successfully:{exchange_name}, {symbol}, period: {granularity}, "
                             f"begin: {begin_time}, end: {current_end_time}")

                    # 更新开始时间
                    begin_time = current_end_time

                    # 如果数据已经下载完成，跳出循环
                    if begin_time >= stop_time:
                        break
                except Exception as e:
                    error_info = traceback.format_exception(e)
                    self.log(f"download fail, retry: {error_info}")
                    time.sleep(3)  # 暂停 3 秒后重试

            self.log(f"download all data completely:{exchange_name}, {symbol}, period: {granularity}")
        return bar_data_list


    def getcash(self, cache=True):
        if cache is True:
            return self.feed_api.get_total_cash()
        else:
            self.feed_api.update_total_balance()
            return self.feed_api.get_total_cash()

    def getvalue(self,cache=True):
        if cache is True:
            return self.feed_api.get_total_value()
        else:
            self.feed_api.update_total_balance()
            return self.feed_api.get_total_value()

    # 用于获取未成交的订单信息
    def get_open_orders(self, data=None):
        pass

    def make_order(self, data, vol, price=None, order_type='buy-limit',
                   offset='open', post_only=False, client_order_id=None, extra_data=None, **kwargs):
        exchange_name = data.get_exchange_name()
        exchange_api = self.exchange_feeds[exchange_name]
        symbol_name = data.get_symbol_name()
        print(f"offset = {offset}")
        return exchange_api.make_order(symbol_name, vol, price, order_type, offset=offset, post_only=post_only,client_order_id=client_order_id, extra_data=extra_data, **kwargs)

    def cancel_order(self, order):
        print("begin to cancel order")
        exchange_name = order.data.get_exchange_name()
        exchange_api = self.exchange_feeds[exchange_name]
        symbol_name = order.data.get_symbol_name()
        new_order = order.bt_api_data
        new_order.init_data()
        order_id = new_order.get_order_id()
        print(f"order_id = {order_id}")
        print(f"symbol_name = {symbol_name}")
        return exchange_api.cancel_order(symbol_name, order_id)