import collections
from datetime import datetime
from time import sleep
import time
import numpy as np
import backtrader as bt
from backtrader.metabase import MetaParams
from backtrader.utils.py3 import queue
from backtrader.utils.date import (
    get_last_timeframe_timestamp,
    datetime2str,
    str2datetime,
    datetime2timestamp,
    timestamp2datetime,
)
from ctpbee import CtpbeeApi, CtpBee, helper
from ctpbee.constant import *


class MyCtpbeeApi(CtpbeeApi):

    def __init__(self, name, timeframe=None, compression=None, md_queue=None):
        super().__init__(name)
        self.md_queue = md_queue  # 行情队列
        self.is_position_ok = False
        self.is_account_ok = False
        self._bar_timeframe = timeframe
        self._bar_compression = compression
        self._bar_begin_time = None
        self._bar_end_time = None
        self._bar_interval = None
        self._data_name = None
        self.time_diff = None
        # 更新bar的行情
        self.bar_datetime = None
        self.bar_open_price = 0.0
        self.bar_high_price = -np.inf
        self.bar_low_price = np.inf
        self.bar_close_price = 0.0
        self.bar_volume = 0.0

    def subscribe(self, dataname, timeframe, compression):
        print(f"------开始订阅数据------")
        if dataname is not None:
            self.action.subscribe(dataname)
            self._bar_timeframe = timeframe
            self._bar_compression = compression
            self._data_name = dataname
            print(f"-----订阅数据成功{dataname},{timeframe},{compression}--------")
            if self._bar_timeframe == 4:
                self.time_diff = 60 * self._bar_compression
                self._bar_interval = str(self._bar_compression) + "m"
            # 如果是日线级别
            elif self._bar_timeframe == 5:
                self.time_diff = 86400 * self._bar_compression
                self._bar_interval = str(self._bar_compression) + "d"
            # 如果是其他周期，默认是一分钟
            else:
                self.time_diff = 60
                self._bar_interval = "1m"

    def on_contract(self, contract: ContractData):
        """处理推送的合约信息"""
        # print(contract)
        pass

    def on_log(self, log: LogData):
        """处理日志信息 ,特殊需求才用到"""
        pass

    def on_tick(self, tick: TickData) -> None:
        """处理推送的tick"""
        # print('on_tick: ', tick)
        # print(f"进入on_tick, {tick.datetime}")
        # 如果bar结束时间是None的话,需要计算出bar结束时间
        if self._bar_end_time is None:
            # 获取最近一次bar更新的时间,然后计算bar结束的时间
            nts = datetime2timestamp(tick.datetime)
            self._bar_begin_time = get_last_timeframe_timestamp(int(nts), self.time_diff)
            self._bar_end_time = self._bar_begin_time + self.time_diff
            self._bar_end_time = timestamp2datetime(self._bar_begin_time)

        # 如果当前的tick的时间大于等于了bar结束的时间,就push bar到队列中,否则就更新k线
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
        """处理ctpbee生成的bar"""
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
        self.md_queue[bar.local_symbol].put(bar)  # 分发行情数据到对应的队列

    def on_init(self, init):
        pass

    def on_order(self, order: OrderData) -> None:
        """报单回报"""
        print("on_order: ", order)
        # 这里应该将ctpbee的order类型转换为backtrader的order类型,然后通过notify_order通知策略
        pass

    def on_trade(self, trade: TradeData) -> None:
        """成交回报"""
        print("on_trade: ", trade)
        # 这里应该通过ctpbee的trade去更新backtrader的order,然后通过notify_order通知策略
        pass

    def on_position(self, position: PositionData) -> None:
        """处理持仓回报"""
        # print('on_position', position)
        self.is_position_ok = True

    def on_account(self, account: AccountData) -> None:
        """处理账户信息"""
        # print('on_account', account)
        self.is_account_ok = True


class MetaSingleton(MetaParams):
    """Metaclass to make a metaclassed class a singleton"""

    def __init__(cls, name, bases, dct):
        super(MetaSingleton, cls).__init__(name, bases, dct)
        cls._singleton = None

    def __call__(cls, *args, **kwargs):
        if cls._singleton is None:
            cls._singleton = super(MetaSingleton, cls).__call__(*args, **kwargs)
        return cls._singleton


class CTPStore(metaclass=MetaSingleton):
    """
    Singleton class wrapping
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

    def __init__(self, ctp_setting, *args, **kwargs):
        super(CTPStore, self).__init__()
        # 连接设置
        self.ctp_setting = ctp_setting
        # 初始值
        self._cash = 0.0
        self._value = 0.0
        # feed行情队列字典,保存每个feed的行情队列. key为feed,value为对应行情queue
        self.q_feed_qlive = dict()
        self.main_ctpbee_api = MyCtpbeeApi("main_ctpbee_api", md_queue=self.q_feed_qlive)
        self.app = CtpBee("ctpstore", __name__, refresh=True)
        self.app.config.from_mapping(ctp_setting)
        self.app.add_extension(self.main_ctpbee_api)
        self.app.start(log_output=True)
        while True:
            sleep(1)
            if self.main_ctpbee_api.is_account_ok:
                break
        # 调试输出
        print("positions===>", self.main_ctpbee_api.center.positions)
        print("account===>", self.main_ctpbee_api.center.account)

    def register(self, feed):
        """注册feed行情队列,传入feed,为它创建一个queue,并加进字典"""
        self.q_feed_qlive[feed.p.dataname] = queue.Queue()
        return self.q_feed_qlive[feed.p.dataname]

    # def subscribe(self, data):
    #     print(f"------开始订阅数据------")
    #     if data is not None:
    #         self.main_ctpbee_api.action.subscribe(data.p.dataname)
    #         print(f"-----订阅数据成功{data.p.dataname}--------")

    def stop(self):
        pass

    def get_positions(self):
        positions = self.main_ctpbee_api.center.positions
        print("positions:", positions)
        return positions

    def get_balance(self):
        account = self.main_ctpbee_api.center.account
        print("account:", account)
        self._cash = account.available
        self._value = account.balance

    def get_cash(self):
        return self._cash

    def get_value(self):
        return self._value
