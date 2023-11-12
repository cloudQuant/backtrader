from __future__ import absolute_import, division, print_function, unicode_literals

from datetime import datetime

from backtrader.feed import DataBase
from backtrader import date2num, num2date
from backtrader.utils.py3 import queue, with_metaclass

from backtrader.stores.ctpstore import CTPStore

import akshare as ak
import pytz


class MetaCTPData(DataBase.__class__):
    def __init__(cls, name, bases, dct):
        """Class has already been created ... register"""
        # Initialize the class
        super(MetaCTPData, cls).__init__(name, bases, dct)
        # Register with the store
        CTPStore.DataCls = cls


class CTPData(with_metaclass(MetaCTPData, DataBase)):
    """CTP Data Feed.

    Params:

      - `historical` (default: `False`)

        If set to `True` the data feed will stop after doing the first
        download of data.

        The standard data feed parameters `fromdate` and `todate` will be
        used as reference.

    """

    params = (
        ("historical", False),  # 是否仅仅回填历史数据，不接收实时数据。也就是下载完历史数据就结束。一般不用
        ("num_init_backfill", 100),  # 初始回填bar的数目
    )

    _store = CTPStore

    # States for the Finite State Machine in _load
    _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(3)

    def islive(self):
        """True notifies `Cerebro` that `preloading` and `runonce` should be deactivated"""
        return True

    def __init__(self, **kwargs):
        self.o = self._store(**kwargs)
        self.qlive = self.o.register(self)

    def start(self):
        """
        """
        super(CTPData, self).start()
        # 订阅标的行情
        self.o.subscribe(data=self)
        self._get_backfill_data()
        self._state = self._ST_HISTORBACK

    def _get_backfill_data(self):
        """ 获取回填数据
        """
        self.put_notification(self.DELAYED)
        print('_get_backfill_data')
        self.qhist = queue.Queue()  # qhist是存放历史行情数据的队列,用于回填历史数据,未来考虑从数据库或第三方加载,可参考vnpy的处理
        #
        CHINA_TZ = pytz.timezone("Asia/Shanghai")
        #
        symbol = (self.p.dataname).split('.')[0]
        futures_sina_df = ak.futures_zh_minute_sina(symbol=symbol, period="1").tail(self.p.num_init_backfill)
        # 改列名
        futures_sina_df.columns = ['datetime', 'OpenPrice', 'HighPrice', 'LowPrice', 'LastPrice', 'BarVolume', 'hold']
        # 增加symbol列
        futures_sina_df['symbol'] = self.p.dataname
        # 改数据类型
        for i in range(self.p.num_init_backfill):
            msg = futures_sina_df.iloc[i].to_dict()
            dt = datetime.strptime(msg['datetime'], "%Y-%m-%d %H:%M:%S")
            dt = CHINA_TZ.localize(dt)
            msg['datetime'] = dt
            msg['OpenPrice'] = float(msg['OpenPrice'])
            msg['HighPrice'] = float(msg['HighPrice'])
            msg['LowPrice'] = float(msg['LowPrice'])
            msg['LastPrice'] = float(msg['LastPrice'])
            msg['BarVolume'] = int(msg['BarVolume'])
            msg['hold'] = int(msg['hold'])
            msg["OpenInterest"] = 0
            print('回填', msg)
            self.qhist.put(msg)
        # 放一个空字典,表示回填结束
        self.qhist.put({})
        return True

    def stop(self):
        """Stops and tells the store to stop"""
        super(CTPData, self).stop()
        self.o.stop()

    def haslivedata(self):
        return bool(self.qlive)  # do not return the obj

    def _load(self):
        """ 
        return True  代表从数据源获取数据成功
        return False 代表因为某种原因(比如历史数据源全部数据已经输出完毕)数据源关闭
        return None  代表暂时无法从数据源获取最新数据,但是以后会有(比如实时数据源中最新的bar还未生成)
        """
        if self._state == self._ST_OVER:
            return False

        while True:
            if self._state == self._ST_LIVE:
                try:
                    msg = self.qlive.get(False)
                    print('msg _load', msg)
                except queue.Empty:
                    return None
                if msg:
                    print('load 1min bar 实盘')
                    if self._load_candle(msg):
                        return True  # loading worked

            elif self._state == self._ST_HISTORBACK:
                msg = self.qhist.get()
                if msg is None:
                    # Situation not managed. Simply bail out
                    self.put_notification(self.DISCONNECTED)
                    self._state = self._ST_OVER
                    return False  # error management cancelled the queue
                elif msg:
                    if self._load_candle_history(msg):
                        print('load candle 历史回填')
                        return True  # loading worked
                    # not loaded ... date may have been seen
                    continue
                else:  # 处理空{},注意空{}不等于None.来了空{}就意味着回填数据输出完毕
                    # End of histdata
                    if self.p.historical:  # only historical
                        self.put_notification(self.DISCONNECTED)
                        self._state = self._ST_OVER
                        return False  # end of historical

                # Live is also wished - go for it
                self._state = self._ST_LIVE
                self.put_notification(self.LIVE)

    def _load_candle(self, msg):
        if msg.symbol != self.p.dataname.split('.')[0]:
            print('return', msg.symbol, self.p.dataname)
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
        if msg['symbol'] != self.p.dataname:
            return
        dt = date2num(msg['datetime'])
        # time already seen
        if dt <= self.lines.datetime[-1]:
            return False
        self.lines.datetime[0] = dt
        self.lines.open[0] = msg['OpenPrice']
        self.lines.high[0] = msg['HighPrice']
        self.lines.low[0] = msg['LowPrice']
        self.lines.close[0] = msg['LastPrice']
        self.lines.volume[0] = msg['BarVolume']
        self.lines.openinterest[0] = msg['OpenInterest']
        return True
