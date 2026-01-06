from datetime import datetime

import akshare as ak
import pytz

from backtrader.feed import DataBase
from backtrader.stores.ctpstore import CTPStore
from backtrader.utils.py3 import queue

from ..utils import date2num


class CTPData(DataBase):
    """CTP Data Feed.

    Params:

      - `Historical` (default: `False`)

        If set to `True` the data feed will stop after doing the first
        download of data.

        The standard data feed parameters `fromdate` and `todate` will be
        used as reference.

    """

    params = (
        (
            "historical",
            False,
        ),  # Whether to only backfill historical data, not receive live data. End after downloading historical data. Generally not used
        ("num_init_backfill", 100),  # Number of bars for initial backfill
    )

    _store = CTPStore

    # States for the Finite State Machine in _load
    _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(3)

    def islive(self):
        """True notifies `Cerebro` that `preloading` and `runonce` should be deactivated"""
        return True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Handle original metaclass registration functionality
        CTPStore.DataCls = self.__class__

        self._state = None
        self.o = self._store(**kwargs)
        self.qlive = self.o.register(self)

    def start(self):
        """ """
        super().start()
        # Subscribe to market data
        # self.o.subscribe(data=self)
        self.o.main_ctpbee_api.subscribe(self.p.dataname, self._timeframe, self._compression)
        self._get_backfill_data()
        self._state = self._ST_HISTORBACK

    def _get_backfill_data(self):
        """Get backfill data"""
        self.put_notification(self.DELAYED)
        # print("_get_backfill_data")  # Removed for performance
        self.qhist = (
            queue.Queue()
        )  # qhist is queue for storing historical market data, for backfilling historical data. Future consideration: load from database or third-party, refer to vnpy handling
        #
        CHINA_TZ = pytz.timezone("Asia/Shanghai")
        #
        symbol = self.p.dataname.split(".")[0]
        if self._timeframe == 4:
            futures_sina_df = ak.futures_zh_minute_sina(
                symbol=symbol, period=str(self._compression)
            ).tail(self.p.num_init_backfill)
        # If daily timeframe
        elif self._bar_timeframe == 5:
            futures_sina_df = ak.futures_zh_daily_sina(symbol=symbol)
        # If other timeframes, default is one minute
        else:
            futures_sina_df = ak.futures_zh_minute_sina(symbol=symbol, period="1").tail(
                self.p.num_init_backfill
            )
        # Rename columns
        futures_sina_df.columns = [
            "datetime",
            "OpenPrice",
            "HighPrice",
            "LowPrice",
            "LastPrice",
            "BarVolume",
            "hold",
        ]
        # Add symbol column
        futures_sina_df["symbol"] = self.p.dataname
        # Change data types
        for i in range(self.p.num_init_backfill):
            msg = futures_sina_df.iloc[i].to_dict()
            dt = datetime.strptime(msg["datetime"], "%Y-%m-%d %H:%M:%S")
            dt = CHINA_TZ.localize(dt)
            msg["datetime"] = dt
            msg["OpenPrice"] = float(msg["OpenPrice"])
            msg["HighPrice"] = float(msg["HighPrice"])
            msg["LowPrice"] = float(msg["LowPrice"])
            msg["LastPrice"] = float(msg["LastPrice"])
            msg["BarVolume"] = int(msg["BarVolume"])
            msg["hold"] = int(msg["hold"])
            msg["OpenInterest"] = 0
            # print('backfill', msg)
            self.qhist.put(msg)
        # Put empty dict to indicate backfill finished
        self.qhist.put({})
        return True

    def stop(self):
        """Stops and tells the store to stop"""
        super().stop()
        self.o.stop()

    def haslivedata(self):
        return bool(self.qlive)  # do not return the obj

    def _load(self):
        """
        return True means successfully got data from data source
        return False means data source closed for some reason (e.g., historical data source finished outputting all data)
        return None means temporarily cannot get latest data from data source, but will have later (e.g., latest bar in live data source not yet generated)
        """
        if self._state == self._ST_OVER:
            return False

        while True:
            if self._state == self._ST_LIVE:
                try:
                    msg = self.qlive.get(False)
                    # print("msg _load", msg)  # Removed for performance
                except queue.Empty:
                    return None
                if msg:
                    if self._load_candle(msg):
                        return True  # loading worked

            elif self._state == self._ST_HISTORBACK:
                msg = self.qhist.get()
                if msg is None:
                    # The Situation isn't managed. Bail out
                    self.put_notification(self.DISCONNECTED)
                    self._state = self._ST_OVER
                    return False  # error management cancelled the queue
                elif msg:
                    if self._load_candle_history(msg):
                        # print("load candle historical backfill")  # Removed for performance
                        return True  # loading worked
                    # not loaded ... date may have been seen
                    continue
                else:  # Handle empty {}, note empty {} is not equal to None. Empty {} means backfill data output finished
                    # End of histdata
                    if self.p.historical:  # only historical
                        self.put_notification(self.DISCONNECTED)
                        self._state = self._ST_OVER
                        return False  # end of historical

                # Live is also wished - go for it
                self._state = self._ST_LIVE
                self.put_notification(self.LIVE)

    def _load_candle(self, msg):
        if msg.symbol != self.p.dataname.split(".")[0]:
            # print("return", msg.symbol, self.p.dataname)  # Removed for performance
            return
        if msg.open_price == 0:
            # print("return, msg.symbol open_price is 0")  # Removed for performance
            return
        dt = date2num(msg.datetime)
        # time already seen
        if dt <= self.lines.datetime[-1]:
            return False
        self.lines.datetime[0] = dt
        self.lines.open[0] = msg.open_price
        self.lines.high[0] = msg.high_price
        self.lines.low[0] = msg.low_price
        self.lines.close[0] = msg.close_price
        self.lines.volume[0] = msg.volume
        self.lines.openinterest[0] = 0
        return True

    def _load_candle_history(self, msg):
        if msg["symbol"] != self.p.dataname:
            return
        dt = date2num(msg["datetime"])
        # time already seen
        if dt <= self.lines.datetime[-1]:
            return False
        self.lines.datetime[0] = dt
        self.lines.open[0] = msg["OpenPrice"]
        self.lines.high[0] = msg["HighPrice"]
        self.lines.low[0] = msg["LowPrice"]
        self.lines.close[0] = msg["LastPrice"]
        self.lines.volume[0] = msg["BarVolume"]
        self.lines.openinterest[0] = msg["OpenInterest"]
        return True
