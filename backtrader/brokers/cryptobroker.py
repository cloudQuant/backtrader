import collections
import json
from datetime import datetime

from backtrader import BrokerBase, Order
from backtrader.position import Position
from backtrader.utils.py3 import queue, with_metaclass
from backtrader.stores.cryptostore import CryptoStore
from backtrader.utils.log_message import SpdLogManager


class CryptoOrder(Order):
    def __init__(self, owner, data, exectype, side, amount, price, data_type, bt_api_data):
        self.owner = owner
        self.data = data
        self.exectype = exectype
        self.ordtype = self.Buy if side == 'buy' else self.Sell
        self.size = float(amount)
        self.price = float(price) if price else None
        self.data_type = data_type if data_type is not None else "order"
        self.bt_api_data = bt_api_data
        self.executed_fills = []
        super(CryptoOrder, self).__init__()


class MetaCryptoBroker(BrokerBase.__class__):
    def __init__(cls, name, bases, dct):
        """Class has already been created ... register"""
        # Initialize the class
        super(MetaCryptoBroker, cls).__init__(name, bases, dct)
        CryptoStore.BrokerCls = cls


class CryptoBroker(with_metaclass(MetaCryptoBroker, BrokerBase)):
    """Broker implementation for CCXT cryptocurrency trading library.
    This class maps the orders/positions from CCXT to the
    internal API of `backtrader`.

    Broker mapping added as I noticed that there are differences between the expected
    order_types and retuned status from canceling an order

    Added a new mappings parameter to the script with defaults.

    Added a get_balance function. Manually check the account balance and update brokers
    self.cash and self.value. This helps alleviate rate limit issues.

    Added a new get_wallet_balance method. This will allow manual checking of any coins
        The method will allow setting parameters. Useful for dealing with multiple assets

    Modified getcash() and getvalue():
        Backtrader will call getcash and getvalue before and after next, slowing things down
        with rest calls. As such, th

    The broker mapping should contain a new dict for order_types and mappings like below:

    broker_mapping = {
        'order_types': {
            bt.Order.Market: 'market',
            bt.Order.Limit: 'limit',
            bt.Order.Stop: 'stop-loss', #stop-loss for kraken, stop for bitmex
            bt.Order.StopLimit: 'stop limit'
        },
        'mappings':{
            'closed_order':{
                'key': 'status',
                'value':'closed'
                },
            'canceled_order':{
                'key': 'result',
                'value':1}
                }
        }

    Added new private_end_point method to allow using any private non-unified end point
    """
    def __init__(self, store=None, **kwargs):
        super(CryptoBroker, self).__init__()
        self.value = None
        self.cash = None
        self.startingvalue = None
        self.startingcash = None
        self.store = None
        self.debug = None
        self.logger = self.init_logger()
        self.init_store(store)
        self.positions = collections.defaultdict(Position)
        self.indent = 4  # For pretty printing dictionaries
        self.notifs = queue.Queue()  # holds orders which are notified
        self.open_orders = list()
        self._last_op_time = 0

    def init_store(self, store):
        if store is not None:
            self.store = store
        else:
            self.store = self.strategy.datas[0].store
        self.debug = self.store.debug
        self.startingcash = self.store.getcash()
        self.startingvalue = self.store.getvalue()
        self.log("init store success, debug = {}".format(self.debug))


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

    def getcash(self, data = None, cache=True):
        cash = self.store.getcash(cache=cache)
        if data is None:
            data = self.cerebro.datas[0]
        if data is not None:
            exchange_name = data.get_exchange_name()
            symbol_name = data.get_symbol_name()
            currency = symbol_name.split("-")[1]
            cash = cash.get(exchange_name, -1.0)
            if isinstance(cash,dict) and currency is not None:
                cash = cash.get(currency, -1.0)
                if isinstance(cash,dict):
                    cash = cash['cash']
                    return cash
        return cash

    def getvalue(self, data = None, cache=True):
        value = self.store.getvalue(cache=cache)
        if data is None:
            data = self.cerebro.datas[0]
        if data is not None:
            exchange_name = data.get_exchange_name()
            symbol_name = data.get_symbol_name()
            currency = symbol_name.split("-")[1]
            value = value.get(exchange_name, -1.0)
            if isinstance(value,dict) and currency is not None:
                value = value.get(currency, -1.0)
                if isinstance(value,dict):
                    value = value['value']
                    return value
        return value

    def get_notification(self):
        try:
            return self.notifs.get(False)
        except queue.Empty:
            return None

    def notify(self, order):
        self.notifs.put(order)

    def getposition(self, data, clone=True):
        # return self.o.getposition(data._dataname, clone=clone)
        pos = self.positions[data.get_name()]
        if clone:
            pos = pos.clone()
        return pos

    def next(self):
        # ===========================================
        # 每隔3秒操作一下
        nts = datetime.now().timestamp()
        if nts - self._last_op_time < 1:
            return
        self._last_op_time = nts
        # ===========================================
        self._next()

    def _next(self):
        # 从store中获取order信息, trade信息, position信息, account信息,并传递给strategy
        while True:
            try:
                data = self.store.order_queue.get(block=False)  # 不阻塞
            except queue.Empty:
                break  # no data in the queue
            order = self.convert_bt_api_order_to_backtrader_order(data)
            self.notify(order)
        while True:
            try:
                data = self.store.trade_queue.get(block=False)
            except queue.Empty:
                break
            trade = self.convert_bt_api_trade_to_backtrader_trade(data)
            self.notify(trade)

    def getdatabyname(self, name):
        for data in self.cerebro.datas:
            print(data.get_name(), name)
            if data.get_name() == name:
                return data
        return None


    def convert_bt_api_order_to_backtrader_order(self, data):
        data.init_data()
        exchange_name = data.get_exchange_name()
        symbol_name = data.get_symbol_name()
        if "-" not in symbol_name:
            if "USDT" in symbol_name:
                symbol_name = symbol_name.replace("USDT", "-USDT")
        asset_type = data.get_asset_type()
        data_name = exchange_name + "___" + asset_type + "___" + symbol_name
        exectype = data.get_order_type()
        order_side = data.get_order_side()
        order_amount = data.get_order_size()
        order_price = data.get_order_price()
        trade_data = self.getdatabyname(data_name)
        return CryptoOrder(None, trade_data, exectype, order_side, order_amount, order_price, "order", data)

    def convert_bt_api_trade_to_backtrader_trade(self, data):
        data.init_data()
        exchange_name = data.get_exchange_name()
        symbol_name = data.get_symbol_name()
        if "-" not in symbol_name:
            if "USDT" in symbol_name:
                symbol_name = symbol_name.replace("USDT", "-USDT")
        asset_type = data.get_asset_type()
        data_name = exchange_name + "___" + asset_type + "___" + symbol_name
        exectype = data.get_trade_type()
        trade_volume = data.get_trade_volume()
        price = data.get_price()
        trade_data = self.getdatabyname(data_name)
        return CryptoOrder(None, trade_data, exectype, exectype, trade_volume, price, "trade", data)

    def _submit(self, owner, data, size, side=None, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None,
            **kwargs):
        order_type = side + "-" + exectype
        ret_ord = self.store.make_order(data, size, price=price, order_type=order_type,
                                        **kwargs)
        order = CryptoOrder(owner, data, exectype, side, size, price, "order", ret_ord)
        # self.open_orders.append(order)
        # self.notify(order.clone())  # 先发一个订单创建通知
        # self._next()  # 然后判断订单是否已经成交,有成交就发通知
        return order

    # 买入下单
    def buy(self, owner, data, size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None,
            **kwargs):
        kwargs.pop('parent', None)
        kwargs.pop('transmit', None)
        return self._submit(owner, data, size, 'buy', price, exectype=exectype, **kwargs)

    # 卖出下单
    def sell(self, owner, data, size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None,
             **kwargs):
        kwargs.pop('parent', None)
        kwargs.pop('transmit', None)
        return self._submit(owner, data, size, 'sell', price, exectype=exectype, **kwargs)

    # 取消未成交的某个订单
    def cancel(self, order):
        self.store.cancel_order(order)


    # 用于平掉所有的仓位
    def close(self, owner, data):
        pass

    # 用户通过这个接口获取未成交的订单信息
    def get_open_orders(self, data=None, cache=True):
        if cache:
            return self.open_orders
        else:
            return self.store.get_open_orders(data)

    # def getposition(self, data, clone=True):
    #     pos = self.positions[data._dataname]
    #     if clone:
    #         pos = pos.clone()
    #     return pos
    #
    # def orderstatus(self, order):
    #     o = self.orders[order.ref]
    #     return o.status
    #
    # def _submit(self, oref):
    #     order = self.orders[oref]
    #     order.submit(self)
    #     self.notify(order)
    #
    # def _reject(self, oref):
    #     order = self.orders[oref]
    #     order.reject(self)
    #     self.notify(order)
    #
    # def _accept(self, oref):
    #     order = self.orders[oref]
    #     order.accept()
    #     self.notify(order)
    #
    # def _cancel(self, oref):
    #     order = self.orders[oref]
    #     order.cancel()
    #     self.notify(order)
    #
    # def _expire(self, oref):
    #     order = self.orders[oref]
    #     order.expire()
    #     self.notify(order)
    #
    # def notify(self, order):
    #     self.notifs.append(order.clone())
    #
    # def get_notification(self):
    #     if not self.notifs:
    #         return None
    #     return self.notifs.popleft()

    # def next(self):
    #     self.notifs.append(None)  # mark notification boundary

