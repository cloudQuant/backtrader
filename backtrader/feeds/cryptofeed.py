import time
import backtrader as bt
from datetime import datetime, UTC
from backtrader.feed import DataBase
from backtrader import date2num, num2date
from backtrader.utils.py3 import queue, with_metaclass
from backtrader.stores.cryptostore import CryptoStore


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
        ('backfill_start', False),  # do backfilling at the start
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

    def __init__(self,
                 **kwargs):
        """feed初始化的时候,先初始化store,实现与交易所对接"""
        print("kwargs: ", kwargs)
        self.exchange = kwargs.pop('exchange')
        self.asset_type = kwargs.pop("asset_type")
        self.symbol = kwargs.pop("symbol")
        self.debug = kwargs.pop("debug")
        self.currency = kwargs.pop("currency", "USDT")
        self.kwargs = kwargs
        self.update_kwargs()
        self.store = self._store(self.exchange, self.asset_type, self.symbol,
                                 self.debug, self.currency, **self.kwargs)
        self._data = self.store.data_queue  # data queue for price data
        self.bar_time = None
        print("CryptoFeed init success, debug = {}".format(self.debug))


    def update_kwargs(self):
        timeframe = self.p.timeframe
        compression = self.p.compression
        period = self._GRANULARITIES[(timeframe, compression)]
        self.kwargs['topics'] = [{"topic": "kline", "symbol": self.symbol, "period": period}]
        print("update kwargs successfully")
        print(self.kwargs)


    def start(self):
        print("CryptoFeed begin to start")
        DataBase.start(self)
        if self.p.fromdate:
            print("begin to fetch data from fromdate")
            self._state = self._ST_HISTORBACK
            self.put_notification(self.DELAYED)
            self._update_history_bar(self.p.fromdate)
            print("update history bar successfully")
        else:
            print("self.fromdate is None")
            self._state = self._ST_LIVE
            self.put_notification(self.LIVE)

    def _load(self):
        """
        return True  更新数据成功，历史数据或者实时数据
        return False 代表K线是最新的，但是K线还没有闭合
        return None  代表当前无法从消息队列中获取数据
        """
        if self._state == self._ST_OVER:
            return False
        while True:
            if self._state == self._ST_LIVE:
                return self._load_bar()
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
                        self.store.wss_start()
                        self._state = self._ST_LIVE
                        self.put_notification(self.LIVE)
                        continue

    def _update_history_bar(self, fromdate):
        print("begin update history bar")
        granularity = self.get_granularity(self._timeframe, self._compression)
        self.store.download_history_bars(self.symbol, granularity, count=100, start_time=fromdate, end_time=None)
        print("update history bar successfully")

    def _load_bar(self):
        try:
            bar = self._data.get(block=False)  # 不阻塞
        except queue.Empty:
            return None  # no data in the queue
        bar.init_data()
        bar_data = bar.get_all_data()
        bar_status = bar_data["bar_status"]
        timestamp = bar_data["open_time"]
        dtime = datetime.fromtimestamp(timestamp // 1000, tz=UTC)
        if bar_status is False:
            # print("bar_datetime", dtime, bar_data['high_price'], bar_data['low_price'], bar_data['close_price'], bar_data["volume"])
            return None
        num_time = bt.date2num(dtime)
        self.lines.datetime[0] = num_time
        self.lines.open[0] = bar_data["open_price"]
        self.lines.high[0] = bar_data["high_price"]
        self.lines.low[0] = bar_data["low_price"]
        self.lines.close[0] = bar_data["close_price"]
        self.lines.volume[0] = bar_data["volume"]
        return True

    def utc_to_ts(self, dt):
        fromdate = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute)
        epoch = datetime(1970, 1, 1)
        return int((fromdate - epoch).total_seconds() * 1000)

    def haslivedata(self):
        return self._state == self._ST_LIVE and not self._data.empty()

    def islive(self):
        return not self.p.historical

    def get_granularity(self, timeframe, compression):
        granularity = self._GRANULARITIES.get((timeframe, compression))
        if granularity is None:
            raise ValueError("backtrader bt_api_py module doesn't support fetching OHLCV "
                             "data for time frame %s, compression %s" % \
                             (bt.TimeFrame.getname(timeframe), compression))
        return granularity