from __future__ import absolute_import, division, print_function, unicode_literals

import collections
from datetime import datetime
from time import sleep

import backtrader as bt
from backtrader.metabase import MetaParams
from backtrader.utils.py3 import queue, with_metaclass

from ctpbee import CtpbeeApi, CtpBee, helper
from ctpbee.constant import *



class MyCtpbeeApi(CtpbeeApi):

    def __init__(self, name, md_queue=None):
        super().__init__(name)
        self.md_queue = md_queue  # 行情队列
        self.is_position_ok = False
        self.is_account_ok = False

    def on_contract(self, contract: ContractData):
        """ 处理推送的合约信息 """
        # print(contract)
        pass

    def on_log(self, log: LogData):
        """ 处理日志信息 ,特殊需求才用到 """
        pass

    def on_tick(self, tick: TickData) -> None:
        """ 处理推送的tick """
        # print('on_tick: ', tick)
        pass

    def on_bar(self, bar: BarData) -> None:
        """ 处理ctpbee生成的bar """
        print('on_bar: ', bar.local_symbol, bar.datetime, bar.open_price, bar.high_price, bar.low_price,
              bar.close_price, bar.volume, bar.interval)
        self.md_queue[bar.local_symbol].put(bar)  # 分发行情数据到对应的队列

    def on_init(self, init):
        pass

    def on_order(self, order: OrderData) -> None:
        """ 报单回报 """
        print('on_order: ', order)
        # 这里应该将ctpbee的order类型转换为backtrader的order类型,然后通过notify_order通知策略
        pass

    def on_trade(self, trade: TradeData) -> None:
        """ 成交回报 """
        print('on_trade: ', trade)
        # 这里应该通过ctpbee的trade去更新backtrader的order,然后通过notify_order通知策略
        pass

    def on_position(self, position: PositionData) -> None:
        """ 处理持仓回报 """
        # print('on_position', position)
        self.is_position_ok = True

    def on_account(self, account: AccountData) -> None:
        """ 处理账户信息 """
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


class CTPStore(with_metaclass(MetaSingleton, object)):
    """
    Singleton class wrapping
    """

    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register

    params = (
        ("debug", False),
    )

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
        print('positions===>', self.main_ctpbee_api.center.positions)
        print('account===>', self.main_ctpbee_api.center.account)

    def register(self, feed):
        """ 注册feed行情队列,传入feed,为它创建一个queue,并加进字典
        """
        self.q_feed_qlive[feed.p.dataname] = queue.Queue()
        return self.q_feed_qlive[feed.p.dataname]

    def subscribe(self, data):
        if data is not None:
            self.main_ctpbee_api.action.subscribe(data.p.dataname)

    def stop(self):
        pass

    def get_positions(self):
        positions = self.main_ctpbee_api.center.positions
        print('positions:', positions)
        return positions

    def get_balance(self):
        account = self.main_ctpbee_api.center.account
        print('account:', account)
        self._cash = account.available
        self._value = account.balance

    def get_cash(self):
        return self._cash

    def get_value(self):
        return self._value
