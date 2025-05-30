import collections
from backtrader import BrokerBase, Order, BuyOrder, SellOrder
from backtrader.position import Position

from backtrader.stores.ctpstore import CTPStore


class MetaCTPBroker(BrokerBase.__class__):
    def __init__(cls, name, bases, dct):
        """Class has already been created ... register"""
        # Initialize the class
        super(MetaCTPBroker, cls).__init__(name, bases, dct)
        CTPStore.BrokerCls = cls


class CTPBroker(BrokerBase, metaclass=MetaCTPBroker):
    """Broker implementation for ctp

    This class maps the orders/positions from MetaTrader to the
    internal API of `backtrader`.

    Params:

      - `Use_positions` (default:`False`): When connecting to the broker
        provider use the existing positions to kickstart the broker.

        Set to `False` during instantiation to disregard any existing
        position
    """

    params = (("use_positions", True),)

    def __init__(self, **kwargs):
        super(CTPBroker, self).__init__()
        self.o = CTPStore(**kwargs)

        self.orders = collections.OrderedDict()  # orders by order id
        self.notifs = collections.deque()  # holds orders which are notified

        self.startingcash = self.cash = 0.0
        self.startingvalue = self.value = 0.0
        self.positions = collections.defaultdict(Position)

    def start(self):
        super(CTPBroker, self).start()
        # Get balance on start
        self.o.get_balance()
        self.startingcash = self.cash = self.o.get_cash()
        self.startingvalue = self.value = self.o.get_value()

        if self.p.use_positions:
            positions = self.o.get_positions()
            if positions is None:
                return
            for p in positions:  # 同一标的可能来一长一短两个仓位记录
                size = p["volume"] if p["direction"] == "long" else -p["volume"]  # 短仓为负数
                price = p["price"]  # 以后再写，因长短仓同时存处理稍微复杂一些
                final_size = (
                    self.positions[p["local_symbol"]].size + size
                )  # 设置本地净仓位数量（循环完后就是净仓位了，因为已经把长短仓抵消了）
                # 以下处理仓位价格，循环完毕后，如果净仓位大于0，则净仓位价格为远端长仓价格（平均价格），否则为短仓价格。
                # 所以，如果远端同时存在长短仓，则此价格并不是长短仓的平均价格（无法定义）。但若远端不同时存在长短仓，则此价格正确，为仓位平均价格
                final_price = 0
                if final_size < 0:
                    if p["direction"] == "short":
                        final_price = price
                    else:
                        final_price = self.positions[p["local_symbol"]].price
                else:
                    if p["direction"] == "short":
                        final_price = self.positions[p["local_symbol"]].price
                    else:
                        final_price = price
                # 循环
                self.positions[p["local_symbol"]] = Position(final_size, final_price)

    def stop(self):
        super(CTPBroker, self).stop()
        self.o.stop()

    def getcash(self):
        self.cash = self.o.get_cash()
        return self.cash

    def getvalue(self):
        self.value = self.o.get_value()
        return self.value

    def getposition(self, data, clone=True):
        pos = self.positions[data._dataname]
        if clone:
            pos = pos.clone()
        return pos

    def orderstatus(self, order):
        o = self.orders[order.ref]
        return o.status

    def _submit(self, oref):
        order = self.orders[oref]
        order.submit(self)
        self.notify(order)

    def _reject(self, oref):
        order = self.orders[oref]
        order.reject(self)
        self.notify(order)

    def _accept(self, oref):
        order = self.orders[oref]
        order.accept()
        self.notify(order)

    def _cancel(self, oref):
        order = self.orders[oref]
        order.cancel()
        self.notify(order)

    def _expire(self, oref):
        order = self.orders[oref]
        order.expire()
        self.notify(order)

    def notify(self, order):
        self.notifs.append(order.clone())

    def get_notification(self):
        if not self.notifs:
            return None
        return self.notifs.popleft()

    def next(self):
        self.notifs.append(None)  # mark notification boundary
