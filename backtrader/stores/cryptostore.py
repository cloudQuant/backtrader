import queue
import threading
import time

from bt_api_py.containers import OrderData, BarData, TradeData
from backtrader.store import MetaSingleton
from backtrader.utils.py3 import with_metaclass
from bt_api_py.bt_api import BtApi
from bt_api_py.functions.log_message import SpdLogManager


class CryptoStore(with_metaclass(MetaSingleton, object)):
    """bt_api_py and backtrader store
    """
    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register

    @classmethod
    def getdata(cls, *args, **kwargs):
        """Returns ``DataCls`` with args, kwargs"""
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered ``BrokerCls``"""
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self, exchange_params, debug=True, *args, **kwargs):
        self.exchange_name = list(exchange_params.keys())[0]
        self.kwargs = exchange_params
        self.feed_api = BtApi(exchange_params, debug=debug)
        self.data_queues = self.feed_api.data_queues
        self.exchange_feeds = self.feed_api.exchange_feeds
        self.debug = debug
        self.logger = self.init_logger()
        self.bar_queues = {}
        self.order_queues = {}
        self.trade_queues = {}
        self.feed_api.update_total_balance()
        # 控制线程运行的事件
        self.stop_event = threading.Event()
        # 启动线程处理数据
        self.data_feed_thread = threading.Thread(target=self.run_data_feed, daemon=True)
        self.data_feed_thread.start()
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
        data.init_data()
        exchange_name = data.get_exchange_name()
        asset_type = data.get_asset_type()
        symbol = data.get_symbol_name()
        key_name = exchange_name + "___" + asset_type + "___" + symbol
        if key_name not in queues:
            queues[key_name] = queue.Queue()
        q = queues[key_name]
        q.put(data)

    def deal_data_feed(self):
        """处理数据并分发到相应的队列"""
        while True:
            for exchange_name, data_queue in self.data_queues.items():
                try:
                    data = data_queue.get(block=False)  # 不阻塞
                except queue.Empty:
                    return None  # no data in the queue
                data.init_data()
                # self.log(f"test info : {data.get_all_data()}")
                if isinstance(data, BarData):
                    queues = self.bar_queues
                    CryptoStore.dispatch_data_to_queue(data, queues)
                elif isinstance(data, OrderData):
                    queues = self.order_queues
                    CryptoStore.dispatch_data_to_queue(data, queues)
                elif isinstance(data, TradeData):
                    queues = self.trade_queues
                    CryptoStore.dispatch_data_to_queue(data, queues)
                else:
                    data.init_data()
                    self.log(f"暂时未处理的信息类型:{data.get_all_data()}")

    def run_data_feed(self):
        """启动数据处理线程"""
        while not self.stop_event.is_set():  # 持续运行直到停止事件被设置
            self.deal_data_feed()
            time.sleep(0.1)  # 防止占用过多的 CPU

    def stop_data_feed_thread(self):
        """停止数据处理线程"""
        self.stop_event.set()  # 设置停止事件
        self.data_feed_thread.join()  # 等待线程结束

    def download_history_bars(self, symbol, granularity, count=100, start_time=None, end_time=None):
        exchange_name = self.exchange_name
        data = self.feed_api.download_history_bars(exchange_name, symbol, granularity, count, start_time, end_time)
        return data

    def __del__(self):
        """确保对象销毁时停止线程"""
        self.stop_data_feed_thread()
