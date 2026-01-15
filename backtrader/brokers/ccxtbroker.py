#!/usr/bin/env python
"""CCXT Broker Module - Cryptocurrency exchange broker.

This module provides the CCXTBroker for trading on cryptocurrency
exchanges through the CCXT library.

Classes:
    CCXTOrder: CCXT-specific order implementation.
    CCXTBroker: Broker implementation for CCXT trading.

Functions:
    _register_ccxt_broker_class: Registers broker with store.

Example:
    >>> store = bt.stores.CCXTStore(exchange='binance')
    >>> cerebro.setbroker(store.getbroker())
"""


import collections
import json
from datetime import datetime

from ..broker import BrokerBase
from ..order import Order
from ..position import Position
from ..stores.ccxtstore import CCXTStore
from ..utils.py3 import queue


class CCXTOrder(Order):
    """CCXT-specific order implementation.

    This class extends the base Order class to support orders placed through
    the CCXT library for cryptocurrency exchange trading.

    Attributes:
        ccxt_order: Raw CCXT order dictionary from the exchange.
        executed_fills: List of fill IDs that have been processed.
    """

    def __init__(self, owner, data, exectype, side, amount, price, ccxt_order):
        """Initialize a CCXTOrder instance.

        Args:
            owner: The strategy or object that owns this order.
            data: The data feed associated with this order.
            exectype: Order execution type (Market, Limit, Stop, etc.).
            side: Order side ('buy' or 'sell').
            amount: Order size/quantity.
            price: Order price (None for market orders).
            ccxt_order: Raw CCXT order dictionary from the exchange.
        """
        self.owner = owner
        self.data = data
        self.exectype = exectype
        self.ordtype = self.Buy if side == "buy" else self.Sell
        self.size = float(amount)
        self.price = float(price) if price else None
        self.ccxt_order = ccxt_order
        self.executed_fills = []
        super().__init__()


# Registration mechanism, automatically register broker class when module is imported
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
        """Initialize the CCXTBroker instance.

        Args:
            broker_mapping: Optional dictionary containing custom mappings for
                order types and status values. Expected format:
                {
                    'order_types': {bt.Order.Market: 'market', ...},
                    'mappings': {
                        'closed_order': {'key': 'status', 'value': 'closed'},
                        'canceled_order': {'key': 'status', 'value': 'canceled'}
                    }
                }
            debug: If True, enable debug output.
            **kwargs: Additional arguments passed to CCXTStore (exchange,
                api_key, secret, etc.).

        Raises:
            KeyError: If broker_mapping is malformed (caught silently).
        """
        super().__init__()

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
        """Get and update the account balance from the exchange.

        This method manually refreshes the account balance from the exchange,
        updating the broker's cash and value attributes. This can help alleviate
        rate limit issues by allowing manual balance checks instead of automatic
        checks before/after each operation.

        Returns:
            tuple: (cash, value) where cash is available funds and value is
                total portfolio value.
        """
        self.store.get_balance()
        self.cash = self.store._cash
        self.value = self.store._value
        return self.cash, self.value

    def get_wallet_balance(self, currency_list, params=None):
        """Get wallet balance for specific currencies.

        This method allows manual checking of balances for multiple currencies,
        useful for dealing with multiple assets or margin balances.

        Args:
            currency_list: List of currency symbols to query (e.g., ['BTC', 'ETH']).
            params: Optional dictionary of parameters to pass to the exchange API.

        Returns:
            dict: Dictionary mapping currency symbols to their balance information:
                {
                    'BTC': {'cash': <free_amount>, 'value': <total_amount>},
                    'ETH': {'cash': <free_amount>, 'value': <total_amount>},
                    ...
                }
        """
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
        """Get the current available cash balance.

        Returns:
            float: Current available cash/funds in the broker currency.

        Note:
            This method returns cached cash values to avoid repeated REST API calls.
            Use get_balance() to refresh from the exchange.
        """
        # Get cash seems to always be called before get value,
        # Therefore, it makes sense to add getbalance here.
        # return self.store.getcash(self.currency)
        self.cash = self.store._cash
        return self.cash

    def getvalue(self, datas=None):
        """Get the current portfolio value.

        Args:
            datas: Unused parameter (kept for API compatibility).

        Returns:
            float: Current total portfolio value including cash and positions.

        Note:
            This method returns cached value to avoid repeated REST API calls.
            Use get_balance() to refresh from the exchange.
        """
        # return self.store.getvalue(self.currency)
        self.value = self.store._value
        return self.value

    def get_notification(self):
        """Get the next order notification from the queue.

        Returns:
            Order or None: The next order notification, or None if no
                notifications are available.
        """
        try:
            return self.notifs.get(False)
        except queue.Empty:
            return None

    def notify(self, order):
        """Add an order notification to the queue.

        Args:
            order: The order to notify (typically a clone of the order).
        """
        self.notifs.put(order)

    def getposition(self, data, clone=True):
        """Get the current position for a data feed.

        Args:
            data: The data feed to get the position for.
            clone: If True (default), return a clone of the position to prevent
                modification of the internal state.

        Returns:
            Position: The position object for the specified data feed.
        """
        # return self.o.getposition(data._dataname, clone=clone)
        pos = self.positions[data._dataname]
        if clone:
            pos = pos.clone()
        return pos

    def next(self):
        """Called on each iteration to update broker state.

        This method is called by the backtrader engine on each iteration.
        It rate-limits order status checking to once every 3 seconds to avoid
        hitting exchange API rate limits.

        Note:
            Debug printing has been removed for performance reasons.
        """
        if self.debug:
            pass  # print("Broker next() called")  # Removed for performance
        # ===========================================
        # Perform operation every 3 seconds
        nts = datetime.now().timestamp()
        if nts - self._last_op_time < 3:
            return
        self._last_op_time = nts
        # ===========================================
        self._next()

    def _next(self):
        """
        1. For spot trading, don't use market orders, only use limit orders. When market orders are needed,
           simulate with limit orders, because some exchanges' market order size field is amount, backtrader
           doesn't consider this case and will error, so market orders are not adapted here
        2. For futures, Chinese futures simultaneous long and short positions on same symbol are not supported,
           because backtrader doesn't consider this case, so here we only support one-direction position
           for same symbol at same time
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
            if (
                "trades" in ccxt_order and ccxt_order["trades"] is not None
            ):  # Check if this order has fills
                for fill in ccxt_order["trades"]:  # Iterate through all fills of this order
                    if fill not in o_order.executed_fills:  # Whether this fill has been processed
                        fill_id, fill_dt, fill_size, fill_price = (
                            fill["id"],
                            fill["datetime"],
                            fill["amount"],
                            fill["price"],
                        )
                        o_order.executed_fills.append(
                            fill_id
                        )  # Record that this fill has been processed
                        fill_size = (
                            fill_size if o_order.isbuy() else -fill_size
                        )  # Meet backtrader specification, sell orders or short positions use negative numbers
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
                        )  # Process this fill, internally marks order status, partial or complete fill
                        # Prepare to notify upper strategy
                        # self.get_balance() #Refresh account balance (balance no longer updated, reduce communication to improve performance, can be updated as needed in strategy)
                        pos = self.getposition(
                            o_order.data, clone=False
                        )  # Get corresponding position
                        pos.update(fill_size, fill_price)  # Refresh position
                        # -------------------------------------------------------------------
                        # Using order.executed.remsize to judge if all filled may be unreliable for market buy orders,
                        # so use following code to judge if partial or complete fill
                        if (
                            status == "open"
                        ):  # If status is still open when there are fills, it must be partially filled
                            o_order.partial()
                        elif (
                            status == "closed"
                        ):  # If status is closed when there are fills, it means completely filled
                            o_order.completed()
                        # -------------------------------------------------------------------
                        self.notify(o_order.clone())  # Notify strategy
            else:
                fill_dt, cum_fill_size, average_fill_price = (
                    ccxt_order["timestamp"],
                    ccxt_order["filled"],
                    ccxt_order["average"],
                )
                if cum_fill_size > abs(
                    o_order.executed.size
                ):  # Check if there are new fills this time
                    new_cum_fill_value = (
                        cum_fill_size * average_fill_price
                    )  # Cumulative fill quantity * average fill price = cumulative fill total value
                    old_cum_fill_value = abs(o_order.executed.size) * o_order.executed.price
                    fill_value = new_cum_fill_value - old_cum_fill_value  # Value of this new fill
                    fill_size = cum_fill_size - abs(
                        o_order.executed.size
                    )  # Quantity of this new fill
                    fill_price = fill_value / fill_size  # Price of this new fill
                    fill_size = (
                        fill_size if o_order.isbuy() else -fill_size
                    )  # Meet backtrader specification, sell orders or short positions use negative numbers
                    o_order.execute(
                        fill_dt, fill_size, fill_price, 0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0
                    )  # Process this fill, internally marks order status, partial or complete fill
                    # Prepare to notify upper strategy
                    # self.get_balance() #Refresh account balance (balance no longer updated, reduce communication to improve performance, can be updated as needed in strategy)
                    pos = self.getposition(o_order.data, clone=False)  # Get corresponding position
                    pos.update(fill_size, fill_price)  # Refresh position
                    # -------------------------------------------------------------------
                    # Using order.executed.remsize to judge if all filled may be unreliable for market buy orders,
                    # so use following code to judge if partial or complete fill
                    if (
                        status == "open"
                    ):  # If status is still open when there are fills, it must be partially filled
                        o_order.partial()
                    elif (
                        status == "closed"
                    ):  # If status is closed when there are fills, it means completely filled
                        o_order.completed()
                    # -------------------------------------------------------------------
                    self.notify(o_order.clone())  # Notify strategy

            if self.debug:
                pass  # print(json.dumps(ccxt_order, indent=self.indent))  # Removed for performance

            # Check if the order is closed
            if status == "closed":
                # If the order is completely filled, it will be in this status. Since strategy has been notified above, no need to notify again here
                self.open_orders.remove(o_order)
            elif status == "canceled":
                # Consider two cases: user placed limit order without fills and cancelled directly,
                # user placed limit order with partial fills then cancelled
                # self.get_balance() #Refresh account balance (balance no longer updated, reduce communication to improve performance, can be updated as needed in strategy)
                o_order.cancel()  # Mark order as cancelled
                self.notify(o_order.clone())  # Notify strategy
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
        self.notify(order.clone())  # Send order creation notification first
        self._next()  # Then check if order has been filled, send notification if filled
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
        """Create a buy order.

        Args:
            owner: The strategy creating this order.
            data: The data feed to trade.
            size: Order size (positive for buy).
            price: Order price (None for market orders).
            plimit: Limit price for stop-limit orders.
            exectype: Order execution type (Market, Limit, Stop, StopLimit).
            valid: Order validity (e.g., Good Till Cancelled).
            tradeid: Trade identifier.
            oco: One-Cancels-Other order ID.
            trailamount: Trailing stop amount.
            trailpercent: Trailing stop percentage.
            **kwargs: Additional parameters including 'params' for CCXT-specific
                options.

        Returns:
            CCXTOrder: The created order instance.
        """
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
        """Create a sell order.

        Args:
            owner: The strategy creating this order.
            data: The data feed to trade.
            size: Order size (positive for sell, will be converted internally).
            price: Order price (None for market orders).
            plimit: Limit price for stop-limit orders.
            exectype: Order execution type (Market, Limit, Stop, StopLimit).
            valid: Order validity (e.g., Good Till Cancelled).
            tradeid: Trade identifier.
            oco: One-Cancels-Other order ID.
            trailamount: Trailing stop amount.
            trailpercent: Trailing stop percentage.
            **kwargs: Additional parameters including 'params' for CCXT-specific
                options.

        Returns:
            CCXTOrder: The created order instance.
        """
        del kwargs["parent"]
        del kwargs["transmit"]
        return self._submit(owner, data, exectype, "sell", size, price, kwargs)

    def cancel(self, order):
        """Cancel an open order.

        Args:
            order: The CCXTOrder instance to cancel.

        Returns:
            CCXTOrder: The canceled order instance.

        Note:
            If the order is already filled or canceled, this method returns
            the order without taking action. Otherwise, it cancels the order
            on the exchange and updates the order status.
        """
        oID = order.ccxt_order["id"]

        if self.debug:
            print("Broker cancel() called")
            print(f"Fetching Order ID: {oID}")

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

        # Unify strategy notification processing in next function
        self._next()
        if ccxt_order["status"] == "canceled":
            order.cancel()

        return order

    def get_orders_open(self, safe=False):
        """Get all open orders from the exchange.

        Args:
            safe: Unused parameter (kept for API compatibility).

        Returns:
            list: List of open order dictionaries from the exchange.
        """
        return self.store.fetch_open_orders()

    def private_end_point(self, type, endpoint, params):
        """Call a private API endpoint on the exchange.

        This method allows access to any private, non-unified endpoint provided
        by the CCXT exchange. For more details, see:
        https://github.com/ccxt/ccxt/wiki/Manual#implicit-api-methods

        Args:
            type: HTTP method type ('Get', 'Post', 'Put', or 'Delete').
            endpoint: String containing the endpoint address (e.g., 'order/{id}/cancel').
            params: Dictionary of parameters to send with the request.

        Returns:
            dict: Exchange-specific JSON result from the API, returned as-is
                without parsing.

        Example:
            To get a list of all available methods with an exchange instance:
            >>> print(dir(ccxt.hitbtc()))

            To call a private endpoint:
            >>> broker.private_end_point(
            ...     'Get',
            ...     'order/{id}/cancel',
            ...     {'id': '12345'}
            ... )
        """
        endpoint_str = endpoint.replace("/", "_")
        endpoint_str = endpoint_str.replace("{", "")
        endpoint_str = endpoint_str.replace("}", "")

        method_str = "private_" + type.lower() + endpoint_str.lower()

        return self.store.private_end_point(type=type, endpoint=method_str, params=params)
