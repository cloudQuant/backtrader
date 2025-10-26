#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-


import collections
import json
from datetime import datetime

from backtrader import BrokerBase, Order
from backtrader.position import Position
from backtrader.utils.py3 import queue
from backtrader.stores.ccxtstore import CCXTStore


class CCXTOrder(Order):
    def __init__(self, owner, data, exectype, side, amount, price, ccxt_order):
        self.owner = owner
        self.data = data
        self.exectype = exectype
        self.ordtype = self.Buy if side == "buy" else self.Sell
        self.size = float(amount)
        self.price = float(price) if price else None
        self.ccxt_order = ccxt_order
        self.executed_fills = []
        super(CCXTOrder, self).__init__()


# 注册机制，在导入模块时自动注册broker类
def _register_ccxt_broker_class(broker_cls):
    """Register broker class with the store when module is loaded"""
    CCXTStore.BrokerCls = broker_cls
    return broker_cls


@_register_ccxt_broker_class
class CCXTBroker(BrokerBase):
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

    order_types = {
        Order.Market: "market",
        Order.Limit: "limit",
        Order.Stop: "stop",  # stop-loss for kraken, stop for bitmex
        Order.StopLimit: "stop limit",
    }

    mappings = {
        "closed_order": {"key": "status", "value": "closed"},
        "canceled_order": {"key": "status", "value": "canceled"},
    }

    def __init__(self, broker_mapping=None, debug=False, **kwargs):
        super(CCXTBroker, self).__init__()

        self.cash = None
        if broker_mapping is not None:
            try:
                self.order_types = broker_mapping["order_types"]
            except KeyError:  # Might not want to change the order types
                pass
            try:
                self.mappings = broker_mapping["mappings"]
            except KeyError:  # might not want to change the mappings
                pass

        self.store = CCXTStore(**kwargs)

        self.currency = self.store.currency

        self.positions = collections.defaultdict(Position)

        self.debug = debug
        self.indent = 4  # For pretty printing dictionaries

        self.notifs = queue.Queue()  # holds orders which are notified

        self.open_orders = list()

        self.startingcash = self.store._cash
        self.startingvalue = self.store._value

        self._last_op_time = 0

    def get_balance(self):
        self.store.get_balance()
        self.cash = self.store._cash
        self.value = self.store._value
        return self.cash, self.value

    def get_wallet_balance(self, currency_list, params=None):
        result = {}
        if params is None:
            params = {}
        balance = self.store.get_wallet_balance(params=params)
        for currency in currency_list:
            result[currency] = {}
            result[currency]["cash"] = balance["free"].get(currency, 0)
            result[currency]["value"] = balance["total"].get(currency, 0)
        return result

    def getcash(self):
        # Get cash seems to always be called before get value,
        # Therefore, it makes sense to add getbalance here.
        # return self.store.getcash(self.currency)
        self.cash = self.store._cash
        return self.cash

    def getvalue(self, datas=None):
        # return self.store.getvalue(self.currency)
        self.value = self.store._value
        return self.value

    def get_notification(self):
        try:
            return self.notifs.get(False)
        except queue.Empty:
            return None

    def notify(self, order):
        self.notifs.put(order)

    def getposition(self, data, clone=True):
        # return self.o.getposition(data._dataname, clone=clone)
        pos = self.positions[data._dataname]
        if clone:
            pos = pos.clone()
        return pos

    def next(self):
        if self.debug:
            pass  # print("Broker next() called")  # Removed for performance
        # ===========================================
        # 每隔3秒操作一下
        nts = datetime.now().timestamp()
        if nts - self._last_op_time < 3:
            return
        self._last_op_time = nts
        # ===========================================
        self._next()

    def _next(self):
        """
        1. 对于现货,不要使用市价单,只使用限价单,需要市价单时候也用限价单去模拟,因为有些交易所的市价单的size字段是金额,backtrader
        没考虑这种情况会出错,所以这里不适配市价单
        2. 对于期货,不支持中国期货同一标的同时开多仓和空仓,因为backtrader没考虑这种情况,所以这里我们同一标的同一时间只支持一个方向的仓位
        """
        for o_order in list(self.open_orders):
            oID = o_order.ccxt_order["id"]

            # Print debug before fetching so we know which order is giving an
            # issue if it crashes
            if self.debug:
                pass  # print("Fetching Order ID: {}".format(oID))  # Removed for performance

            # Get the order
            ccxt_order = self.store.fetch_order(oID, o_order.data.p.dataname)
            status = ccxt_order["status"]

            # Check for new fills
            if "trades" in ccxt_order and ccxt_order["trades"] is not None:  # 判断此订单是否有成交
                for fill in ccxt_order["trades"]:  # 遍历此订单的所有成交
                    if fill not in o_order.executed_fills:  # 该成交是否被处理
                        fill_id, fill_dt, fill_size, fill_price = (
                            fill["id"],
                            fill["datetime"],
                            fill["amount"],
                            fill["price"],
                        )
                        o_order.executed_fills.append(fill_id)  # 记录该成交已经被处理
                        fill_size = (
                            fill_size if o_order.isbuy() else -fill_size
                        )  # 满足backtrader规范,卖单或空头仓位用负数表示
                        o_order.execute(
                            fill_dt,
                            fill_size,
                            fill_price,
                            0,
                            0.0,
                            0.0,
                            0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0,
                            0.0,
                        )  # 处理该成交,内部会标注订单状态,部分成交还是完全成交
                        # 准备通知上层策略
                        # self.get_balance() #刷新账户余额 (余额不再更新,减少通信提高性能,可以在策略中根据需要自主去更新)
                        pos = self.getposition(o_order.data, clone=False)  # 获取对应仓位
                        pos.update(fill_size, fill_price)  # 刷新仓位
                        # -------------------------------------------------------------------
                        # 用order.executed.remsize判断是否全部成交在市价买单的情况下可能不靠谱,所以用如下代码判断是否部分或者全部成交
                        if status == "open":  # 有成交的情况下状态仍然是open的话那肯定是部分成交
                            o_order.partial()
                        elif status == "closed":  # 有成交的情况下如果状态是closed那意味着全部成交
                            o_order.completed()
                        # -------------------------------------------------------------------
                        self.notify(o_order.clone())  # 通知策略
            else:
                fill_dt, cum_fill_size, average_fill_price = (
                    ccxt_order["timestamp"],
                    ccxt_order["filled"],
                    ccxt_order["average"],
                )
                if cum_fill_size > abs(o_order.executed.size):  # 判断本次是否有新的成交
                    new_cum_fill_value = (
                        cum_fill_size * average_fill_price
                    )  # 累计成交数量*平均成交价=累计成交总价值
                    old_cum_fill_value = abs(o_order.executed.size) * o_order.executed.price
                    fill_value = new_cum_fill_value - old_cum_fill_value  # 本次新成交的价值
                    fill_size = cum_fill_size - abs(o_order.executed.size)  # 本次新成交的数量
                    fill_price = fill_value / fill_size  # 本次新成交的价格
                    fill_size = (
                        fill_size if o_order.isbuy() else -fill_size
                    )  # 满足backtrader规范,卖单或空头仓位用负数表示
                    o_order.execute(
                        fill_dt, fill_size, fill_price, 0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0
                    )  # 处理该成交,内部会标注订单状态,部分成交还是完全成交
                    # 准备通知上层策略
                    # self.get_balance() #刷新账户余额 (余额不再更新,减少通信提高性能,可以在策略中根据需要自主去更新)
                    pos = self.getposition(o_order.data, clone=False)  # 获取对应仓位
                    pos.update(fill_size, fill_price)  # 刷新仓位
                    # -------------------------------------------------------------------
                    # 用order.executed.remsize判断是否全部成交在市价买单的情况下可能不靠谱,所以用如下代码判断是否部分或者全部成交
                    if status == "open":  # 有成交的情况下状态仍然是open的话那肯定是部分成交
                        o_order.partial()
                    elif status == "closed":  # 有成交的情况下如果状态是closed那意味着全部成交
                        o_order.completed()
                    # -------------------------------------------------------------------
                    self.notify(o_order.clone())  # 通知策略

            if self.debug:
                pass  # print(json.dumps(ccxt_order, indent=self.indent))  # Removed for performance

            # Check if the order is closed
            if status == "closed":
                # 如果该订单全部成交完成就是此状态,因为上面已经通知过策略,所以这里不再重复通知
                self.open_orders.remove(o_order)
            elif status == "canceled":
                # 考虑两种情况:用户下了限价单没有成交,直接取消了,用户下了限价单部分成交,然后再取消
                # self.get_balance() #刷新账户余额 (余额不再更新,减少通信提高性能,可以在策略中根据需要自主去更新)
                o_order.cancel()  # 标注订单为取消状态
                self.notify(o_order.clone())  # 通知策略
                self.open_orders.remove(o_order)

    def _submit(self, owner, data, exectype, side, amount, price, params):
        order_type = self.order_types.get(exectype) if exectype else "market"
        created = int(data.datetime.datetime(0).timestamp() * 1000)
        # Extract CCXT specific params if passed to the order
        params = params["params"] if "params" in params else params
        params["created"] = created  # Add timestamp of order creation for backtesting
        ret_ord = self.store.create_order(
            symbol=data.p.dataname,
            order_type=order_type,
            side=side,
            amount=amount,
            price=price,
            params=params,
        )
        order = CCXTOrder(owner, data, exectype, side, amount, price, ret_ord)
        self.open_orders.append(order)
        self.notify(order.clone())  # 先发一个订单创建通知
        self._next()  # 然后判断订单是否已经成交,有成交就发通知
        return order

    def buy(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        **kwargs,
    ):
        del kwargs["parent"]
        del kwargs["transmit"]
        return self._submit(owner, data, exectype, "buy", size, price, kwargs)

    def sell(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        **kwargs,
    ):
        del kwargs["parent"]
        del kwargs["transmit"]
        return self._submit(owner, data, exectype, "sell", size, price, kwargs)

    def cancel(self, order):

        oID = order.ccxt_order["id"]

        if self.debug:
            print("Broker cancel() called")
            print("Fetching Order ID: {}".format(oID))

        # check first if the order has already been filled, otherwise an error
        # might be raised if we try to cancel an order that is not open.
        ccxt_order = self.store.fetch_order(oID, order.data.p.dataname)

        if self.debug:
            print(json.dumps(ccxt_order, indent=self.indent))

        if (
            ccxt_order[self.mappings["closed_order"]["key"]]
            == self.mappings["closed_order"]["value"]
        ) or (
            ccxt_order[self.mappings["canceled_order"]["key"]]
            == self.mappings["canceled_order"]["value"]
        ):
            return order

        ccxt_order = self.store.cancel_order(oID, order.data.p.dataname)

        if self.debug:
            print(json.dumps(ccxt_order, indent=self.indent))
            print("Value Received: {}".format(ccxt_order[self.mappings["canceled_order"]["key"]]))
            print("Value Expected: {}".format(self.mappings["canceled_order"]["value"]))

        # 统一在next函数中处理策略通知
        self._next()
        if ccxt_order["status"] == "canceled":
            order.cancel()

        return order

    def get_orders_open(self, safe=False):
        return self.store.fetch_open_orders()

    def private_end_point(self, type, endpoint, params):
        """
        Open method to allow calls to be made to any private end point.
        See here: https://github.com/ccxt/ccxt/wiki/Manual#implicit-api-methods

        - type: String, 'Get', 'Post','Put' or 'Delete'.
        - endpoint = String containing the endpoint address e.g. 'order/{id}/cancel'
        - Params: Dict: An implicit method takes a dictionary of parameters, sends
          the request to the exchange and returns an exchange-specific JSON
          result from the API as is unparsed.

        To get a list of all available methods with an exchange instance,
        including implicit methods and unified methods you can simply do the
        following:

        print(dir(ccxt.hitbtc()))
        """
        endpoint_str = endpoint.replace("/", "_")
        endpoint_str = endpoint_str.replace("{", "")
        endpoint_str = endpoint_str.replace("}", "")

        method_str = "private_" + type.lower() + endpoint_str.lower()

        return self.store.private_end_point(type=type, endpoint=method_str, params=params)
