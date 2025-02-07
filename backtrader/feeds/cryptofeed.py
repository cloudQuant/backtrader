import time
import traceback
import pytz
import backtrader as bt
from bt_api_py.containers import BarData
from datetime import datetime, UTC
from backtrader.feed import DataBase
from backtrader.utils.py3 import queue, with_metaclass
from backtrader.stores.cryptostore import CryptoStore
from bt_api_py.functions.log_message import SpdLogManager


class MetaCryptoFeed(DataBase.__class__):
    def __init__(cls, name, bases, dct):
        """Class has already been created ... register"""
        # Initialize the class
        super(MetaCryptoFeed, cls).__init__(name, bases, dct)
        # Register with the store
        CryptoStore.DataCls = cls


class CryptoFeed(with_metaclass(MetaCryptoFeed, DataBase)):
    """
    CryptoCurrency eXchange Trading Library Data Feed.
    Params:
      - ``historical`` (default: ``False``)
        If set to ``True`` the data feed will stop after doing the first
        download of data.
        The standard data feed parameters ``fromdate`` and ``todate`` will be
        used as reference.
      - ``backfill_start`` (default: ``True``)
        Perform backfilling at the start. The maximum possible historical data
        will be fetched in a single request.
    """

    params = (
        ('historical', False),  # only historical download
        ('backfill_start', False),  # do backfill at the start
        ("timeframe", None),
        ("compression", None),
    )

    _store = CryptoStore

    # States for the Finite State Machine in _load
    _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(3)

    _GRANULARITIES = {
        (bt.TimeFrame.Minutes, 1): '1m',
        (bt.TimeFrame.Minutes, 3): '3m',
        (bt.TimeFrame.Minutes, 5): '5m',
        (bt.TimeFrame.Minutes, 15): '15m',
        (bt.TimeFrame.Minutes, 30): '30m',
        (bt.TimeFrame.Minutes, 60): '1h',
        (bt.TimeFrame.Minutes, 90): '90m',
        (bt.TimeFrame.Minutes, 120): '2h',
        (bt.TimeFrame.Minutes, 180): '3h',
        (bt.TimeFrame.Minutes, 240): '4h',
        (bt.TimeFrame.Minutes, 360): '6h',
        (bt.TimeFrame.Minutes, 480): '8h',
        (bt.TimeFrame.Minutes, 720): '12h',
        (bt.TimeFrame.Days, 1): '1d',
        (bt.TimeFrame.Days, 3): '3d',
        (bt.TimeFrame.Weeks, 1): '1w',
        (bt.TimeFrame.Weeks, 2): '2w',
        (bt.TimeFrame.Months, 1): '1M',
        (bt.TimeFrame.Months, 3): '3M',
        (bt.TimeFrame.Months, 6): '6M',
        (bt.TimeFrame.Years, 1): '1y',
    }

    def __init__(self,store,
                 debug=True, *args, **kwargs):
        """feed初始化的时候,先初始化store,实现与交易所对接"""
        self.debug = debug
        self.logger = self.init_logger()
        self.store = store
        self.store.crypto_datas[self.p.dataname] = self
        self._bar_data = None
        self.bar_time = None
        self.history_bars = None
        self._state = self._ST_HISTORBACK
        self.exchange_name, self.asset_type, self.symbol = self.p.dataname.split('___')
        self.period = self.get_granularity(self.p.timeframe, self.p.compression)
        self.subscribe_live_bars()
        self.download_history_bars()
        self.p.todate = None         # 下载完成历史数据之后,需要把todate给充值为None, 否则next被限制
        print("CryptoFeed init success, debug = {}, data_num = {}".format(self.debug, self.store.GetDataNum))

    def get_bar_time(self):
        return self.bar_time

    def download_history_bars(self):
        self.history_bars = self.store.download_history_bars(self.p.dataname, self.period, count=100, start_time=self.p.fromdate, end_time=self.p.todate)
        self.log(f"download {self.p.dataname}, {self.period}, history bar successfully")

    def subscribe_live_bars(self):
        if not self.p.historical:
            topics = [{"topic": "kline", "symbol": self.symbol, "period": self.period}]
            self.store.feed_api.subscribe(self.p.dataname, topics)
            self.log("subscribe {} topics: {} successfully".format(self.p.dataname, topics))

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

    def _init_data_queue(self):
        key_name = self.p.dataname
        self.log(f"self.store.bar_queues.keys() = {self.store.bar_queues.keys()}")
        while key_name not in self.store.bar_queues:
            time.sleep(1)
            self.log("self.store.bar_queues not found {}".format(key_name))
        return self.store.bar_queues[key_name]


    def start(self):
        self.log("CryptoFeed begin to start")
        DataBase.start(self)
        if self.p.fromdate:
            self._state = self._ST_HISTORBACK
            self.put_notification(self.DELAYED)
            self._update_history_bar()
            self.log(f"update history bar successfully, self._state = {self._state}")
            # while True:
            #     ret = self._load()
            #     if ret is False or ret is None:
            #         break
        else:
            self.log("self.fromdate is None")
            self._state = self._ST_LIVE
            self.put_notification(self.LIVE)

    def _load(self):
        """
        return True 更新数据成功，历史数据或者实时数据
        return False 代表K线是最新的，但是K线还没有闭合
        return None 代表当前无法从消息队列中获取数据
        """
        if self._state == self._ST_OVER:
            return False
        while True:
            self.store.deal_data_feed()
            if self._state == self._ST_LIVE:
                ret = self._load_bar()
                # if ret is not None:
                #     self.log(f"self._state = {self._state}, ret = {ret}")
                return ret
            elif self._state == self._ST_HISTORBACK:
                ret = self._load_bar()
                if ret:
                    return ret
                else:
                    # End of historical data
                    if self.p.historical:  # only historical
                        self.put_notification(self.DISCONNECTED)
                        self._state = self._ST_OVER
                        return False  # end of historical
                    else:
                        # 订阅K线
                        # timeframe = self.p.timeframe
                        # compression = self.p.compression
                        # period = self._GRANULARITIES[(timeframe, compression)]
                        # topics = [{"topic": "kline", "symbol": self.symbol, "period": period}]
                        # self.store.feed_api.subscribe(self.p.dataname, topics)
                        self._state = self._ST_LIVE
                        self.put_notification(self.LIVE)
                        self.store.subscribe_bar_num+=1
                        continue


    def _update_history_bar(self):
        queues = self.store.bar_queues
        for data in self.history_bars[:-1]:     # 不考虑最近的一根K线,是因为请求的时候，返回的K线是能是没走完的
            self.store.dispatch_data_to_queue(data, queues)

    def _load_bar(self):
        if self._bar_data is None:
            self._bar_data = self._init_data_queue()
            # self.log("self._bar_data initialized")
        try:
            # self.log("try to fetch data from queue")
            data = self._bar_data.get(block=False)  # 不阻塞
        except queue.Empty:
            # self.log(f"cannot get data")
            return None
        except Exception as e:
            error_info = traceback.format_exception(e)
            self.log(f"error:{error_info}")
            return None
        data.init_data()
        bar_data = data.get_all_data()
        timestamp = bar_data["open_time"]
        # dtime_utc = datetime.fromtimestamp(timestamp // 1000, tz=UTC)
        # 将时间戳转换为 UTC 时间（确保它是 UTC 时间）
        dtime_utc = datetime.fromtimestamp(timestamp//1000, tz=pytz.UTC)
        bar_status = bar_data["bar_status"]
        if bar_status is False:
            # print("bar_datetime", bar_data['high_price'], bar_data['low_price'], bar_data['close_price'], bar_data["volume"])
            return None
        self.bar_time = timestamp
        num_time = bt.date2num(dtime_utc)
        self.lines.datetime[0] = num_time
        self.lines.open[0] = bar_data["open_price"]
        self.lines.high[0] = bar_data["high_price"]
        self.lines.low[0] = bar_data["low_price"]
        self.lines.close[0] = bar_data["close_price"]
        self.lines.volume[0] = bar_data["volume"]
        result = True
        self.log(f"bar_data: {result}, "
                 f"now_time = {dtime_utc}, "
                 f"exchange_name:{bar_data['exchange_name']}_{bar_data['asset_type']}, "
                 f"close_price:{bar_data['close_price']}, ")
        return result

    def islive(self):
        return self._state == self._ST_LIVE

    def get_granularity(self, timeframe, compression):
        granularity = self._GRANULARITIES.get((timeframe, compression))
        if granularity is None:
            raise ValueError("backtrader bt_api_py module doesn't support fetching OHLCV "
                             "data for time frame %s, compression %s" % \
                             (bt.TimeFrame.getname(timeframe), compression))

        return granularity