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


class CryptoStore(with_metaclass(MetaSingleton, object)):
    """bt_api_py and backtrader store
    """
    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register
    GetDataNum = 0
    @classmethod
    def getdata(cls, *args, **kwargs):
        """Returns ``DataCls`` with args, kwargs"""
        cls.GetDataNum += 1
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered ``BrokerCls``"""
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self, exchange_params, debug=True, *args, **kwargs):
        self.kwargs = exchange_params
        self.feed_api = BtApi(exchange_params, debug=debug)
        self.data_queues = self.feed_api.data_queues
        self.exchange_feeds = self.feed_api.exchange_feeds
        self.debug = debug
        self.logger = self.init_logger()
        self.subscribe_bar_num = 0
        self.cache_bar_dict = {}
        self.bar_queues = {}
        self.order_queues = {}
        self.trade_queues = {}
        self.feed_api.update_total_balance()
        self.crypto_datas = {}
        self.log(f"value = {self.feed_api.get_total_value()}")
        self.log(f"cash = {self.feed_api.get_total_cash()}")
        self.log(f"feed_api.keys() = {self.feed_api.exchange_feeds.keys()}")
        # # 控制线程运行的事件
        # self.stop_event = threading.Event()
        # self.lock = threading.Lock()  # 添加锁
        # # 启动线程处理数据
        # self.data_feed_thread = threading.Thread(target=self.run_data_feed, daemon=True)
        # self.data_feed_thread.start()
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
                try:
                    data = data_queue.get(block=False)  # 不阻塞
                except queue.Empty:
                    return None  # no data in the queue
                data.init_data()
                # if data.get_bar_status():
                #     self.log(f"cryptostore push test info : {data.get_all_data()}")
                #     self.log(f"{self.bar_queues} , {self.subscribe_bar_num}")
                if isinstance(data, BarData):
                    queues = self.bar_queues
                    exchange_name = data.get_exchange_name()
                    asset_type = data.get_asset_type()
                    symbol = data.get_symbol_name()
                    bar_status = data.get_bar_status()
                    if not bar_status:
                        continue
                    self.log(f"begin to run live data, {self.subscribe_bar_num}, {self.GetDataNum}")
                    if bar_status:
                        all_data = data.get_all_data()
                        timestamp = all_data["open_time"]
                        # dtime_utc = datetime.fromtimestamp(timestamp // 1000, tz=UTC)
                        # 将时间戳转换为 UTC 时间（确保它是 UTC 时间）
                        dtime_utc = datetime.fromtimestamp(timestamp // 1000, tz=pytz.UTC)
                        self.log(f"cryptostore subscribe test {dtime_utc}, info: {all_data}")
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
                    crypto_feed_instance = self.crypto_datas.get(key_name, None)
                    if crypto_feed_instance:
                        now_bar_time = crypto_feed_instance.get_bar_time()
                        if now_bar_time and data.get_open_time() <= now_bar_time:
                            continue
                    # 处理websocket推送的实时数据
                    if len(self.bar_queues)>0:
                        if bar_status:
                            self.cache_bar_dict[key_name] = data
                        if len(self.cache_bar_dict) == self.subscribe_bar_num:
                            for key_name,data in self.cache_bar_dict.items():
                                q=queues[key_name]
                                q.put(data)
                            self.cache_bar_dict = {}
                    else:
                        CryptoStore.dispatch_data_to_queue(data, queues)
                        all_data = data.get_all_data()
                        timestamp = all_data["open_time"]
                        # dtime_utc = datetime.fromtimestamp(timestamp // 1000, tz=UTC)
                        # 将时间戳转换为 UTC 时间（确保它是 UTC 时间）
                        dtime_utc = datetime.fromtimestamp(timestamp // 1000, tz=pytz.UTC)
                        bar_status = all_data["bar_status"]
                        if bar_status:
                            self.log(f"cryptostore dispatch_data_to_queue test {dtime_utc} info: {all_data}")
                elif isinstance(data, OrderData):
                    queues = self.order_queues
                    CryptoStore.dispatch_data_to_queue(data, queues)
                elif isinstance(data, TradeData):
                    queues = self.trade_queues
                    CryptoStore.dispatch_data_to_queue(data, queues)
                else:
                    data.init_data()
                    self.log(f"un considered info:{data.get_all_data()}")

    # def run_data_feed(self):
    #     """启动数据处理线程"""
    #     while not self.stop_event.is_set():  # 持续运行直到停止事件被设置
    #         self.deal_data_feed()
    #         time.sleep(0.1)  # 防止占用过多的 CPU
    #
    # def stop_data_feed_thread(self):
    #     """停止数据处理线程"""
    #     self.stop_event.set()  # 设置停止事件
    #     self.data_feed_thread.join()  # 等待线程结束


    def download_history_bars(self, dataname, granularity, count=100, start_time=None, end_time=None):
        self.log(f"store {self.feed_api.exchange_feeds.keys()}")
        bar_data_list = []
        exchange,asset_type,symbol = dataname.split("___")
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
                # 假设输入的字符串时间是本地时间
                local_time = datetime.fromisoformat(input_time)
                return local_time.astimezone(timezone.utc)
            elif isinstance(input_time, datetime):
                # 如果是 datetime 类型，确保转换为 UTC
                if input_time.tzinfo is None:
                    local_time = input_time.replace(tzinfo=timezone.utc).astimezone()  # 假设为本地时间
                else:
                    local_time = input_time
                return local_time.astimezone(timezone.utc)
            elif input_time is None:
                return None
            else:
                raise TypeError(f"Unsupported time format: {type(input_time)}")

        # 解析开始时间和结束时间为 UTC
        begin_time = parse_time(start_time)
        stop_time = parse_time(end_time)

        # 如果没有结束时间，则根据 granularity 对其为当前时间
        if stop_time is None:
            stop_time = datetime.now(timezone.utc)  # 当前时间为 UTC
            # period_seconds = int(granularity[:-1]) * 60 if "m" in granularity else int(granularity[:-1]) * 3600
            # stop_time = now - timedelta(seconds=now.timestamp() % period_seconds) - timedelta(seconds=60)

        # 调整结束时间，确保结束时间与整分钟对齐
        # begin_time = adjust_begin_time(begin_time)
        # stop_time = adjust_end_time(stop_time)

        feed = self.exchange_feeds[exchange_name]
        if begin_time is None and count is not None:
            # 如果没有开始时间，只传入 count，获取最近 count 条数据
            data = feed.get_kline(symbol, granularity, count, extra_data=None)
            data.init_data()
            for bar_data in data.get_data():
                bar_data_list.append(bar_data)
            # self.feed_api.push_bar_data_to_queue(exchange_name, data)
            self.log(f"download completely:{exchange_name}, {symbol}, new {count} bar")
            return bar_data_list

        if begin_time is not None:
            # 如果未提供结束时间，则默认为当前时间并对齐到period
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
                    for bar_data in data.get_data():
                        bar_data_list.append(bar_data)
                    # self.feed_api.push_bar_data_to_queue(exchange_name, data)
                    print(f"download successfully:{exchange_name}, {symbol}, period: {granularity}, "
                          f"begin: {begin_time}, end: {current_end_time}")
                    data.init_data()
                    # print(data.get_data())
                    bar_list = []
                    for bar in data.get_data():
                        bar.init_data()
                        bar_list.append(bar.get_all_data())
                    df = pd.DataFrame(bar_list)
                    # print(df.head())
                    df['open_time'] = [datetime.fromtimestamp(i // 1000, tz=pytz.UTC) for i in df['open_time']]
                    df['server_time'] = [datetime.fromtimestamp(i // 1000, tz=pytz.UTC) for i in df['server_time']]
                    print(df[['server_time', 'open_time', "close_price", "bar_status"]])
                    # # print(f"print successfully: {symbol}, period: {granularity}")
                    # 更新开始时间
                    begin_time = current_end_time
                    # 如果数据已经下载完成，跳出循环
                    if begin_time >= stop_time:
                        break
                except Exception as e:
                    error_info = traceback.format_exception(e)
                    self.log(f"download fail, retry: {error_info}")
                    time.sleep(3)  # 暂停 3 秒后重试
            print(f"download all data completely:{exchange_name}, {symbol}, period: {granularity}")
        return bar_data_list

    # def __del__(self):
    #     """确保对象销毁时停止线程"""
    #     self.stop_data_feed_thread()
