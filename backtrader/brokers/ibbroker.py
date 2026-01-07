#!/usr/bin/env python
"""Interactive Brokers Broker Module - IB trading implementation.

This module provides the IBBroker for trading through Interactive
Brokers TWS or IB Gateway.

Classes:
    IBOrderState: Wraps IB OrderState object.
    IBOrder: IB-specific order implementation.
    IBBroker: Broker implementation for IB trading.

Example:
    >>> store = bt.stores.IBStore(port=7497)
    >>> cerebro.setbroker(store.getbroker())
"""

import collections
import threading
import uuid
from datetime import date, datetime, timedelta

import ib.ext.Order

from ..broker import BrokerBase
from ..comminfo import CommInfoBase
from ..order import Order, OrderBase
from ..stores import ibstore
from ..utils import date2num, num2date
from ..utils.py3 import bstr, queue

bytes = bstr  # py2/3 need for ibpy


# IB Order Status
class IBOrderState:
    """Wraps Interactive Brokers OrderState object.

    This class wraps the IB OrderState object to provide convenient
    access to order state fields and string representation.

    Attributes:
        status: Order status.
        initMargin: Initial margin requirement.
        maintMargin: Maintenance margin requirement.
        equityWithLoan: Equity with loan value.
        commission: Commission charged.
        minCommission: Minimum commission.
        maxCommission: Maximum commission.
        commissionCurrency: Currency of commission.
        warningText: Warning message text.
    """

    # wraps OrderState object and can print it
    _fields = [
        "status",
        "initMargin",
        "maintMargin",
        "equityWithLoan",
        "commission",
        "minCommission",
        "maxCommission",
        "commissionCurrency",
        "warningText",
    ]

    def __init__(self, orderstate):
        """Initialize the IBOrderState from an IB OrderState object.

        Args:
            orderstate: IB OrderState object containing order state information.
        """
        for field in self._fields:
            setattr(self, field, getattr(orderstate, field, None))

    def __str__(self):
        txt = []
        txt.append("--- ORDERSTATE BEGIN")
        for field in self._fields:
            txt.append(f"{field.capitalize()}: {getattr(self, field)}")
        txt.append("--- ORDERSTATE END")
        return "\n".join(txt)


# IB Order, for certain IB orders that backtrader doesn't support,
# can be set via keyword arguments
class IBOrder(OrderBase, ib.ext.Order.Order):
    """Subclasses the IBPy order to provide the minimum extra functionality
    needed to be compatible with the internally defined orders

    Once ``OrderBase`` has processed the parameters, the __init__ method takes
    over to use the parameter values and set the appropriate values in the
    ib.ext.Order.Order object

    Any extra parameters supplied with kwargs are applied directly to the
    ib.ext.Order.Order object, which could be used as follows::

      Example: if the four order execution types directly supported by
      ``backtrader`` are not enough, in the case of, for example
      *Interactive Brokers* the following could be passed as *kwargs*:

        orderType='LIT', lmtPrice=10.0, auxPrice=9.8

      This would override the settings created by ``backtrader`` and
      generate a ``LIMIT IF TOUCHED`` order with a *touched* price of 9.8
      and a *limit* price of 10.0.

    This would be done almost always from the ``Buy`` and ``Sell`` methods of
    the ``Strategy`` subclass being used in ``Cerebro``
    """

    def __str__(self):
        """Get the printout from the base class and add some ib.Order specific
        fields"""
        basetxt = super().__str__()
        tojoin = [basetxt]
        tojoin.append(f"Ref: {self.ref}")
        tojoin.append(f"orderId: {self.m_orderId}")
        tojoin.append(f"Action: {self.m_action}")
        tojoin.append(f"Size (ib): {self.m_totalQuantity}")
        tojoin.append(f"Lmt Price: {self.m_lmtPrice}")
        tojoin.append(f"Aux Price: {self.m_auxPrice}")
        tojoin.append(f"OrderType: {self.m_orderType}")
        tojoin.append(f"Tif (Time in Force): {self.m_tif}")
        tojoin.append(f"GoodTillDate: {self.m_goodTillDate}")
        return "\n".join(tojoin)

    # Map backtrader order types to the ib specifics
    # Match order types between backtrader and IB
    _IBOrdTypes = {
        None: bytes("MKT"),  # default
        Order.Market: bytes("MKT"),
        Order.Limit: bytes("LMT"),
        Order.Close: bytes("MOC"),
        Order.Stop: bytes("STP"),
        Order.StopLimit: bytes("STPLMT"),
        Order.StopTrail: bytes("TRAIL"),
        Order.StopTrailLimit: bytes("TRAIL LIMIT"),
    }

    # Initialize, convert from backtrader order type to IB order type
    def __init__(self, action, **kwargs):
        """Initialize the IBOrder with action and order parameters.

        Args:
            action (str): Order direction, either 'BUY' or 'SELL'.
            **kwargs: Additional order parameters including price, size,
                exectype, valid, and other IB-specific parameters.

        Raises:
            KeyError: If invalid order type is specified.
        """
        # Marker to indicate an openOrder has been seen with
        # PendinCancel/Canceled which is an indication of an upcoming
        # cancellation
        # Whether order will expire
        self._willexpire = False
        # Order direction
        self.ordtype = self.Buy if action == "BUY" else self.Sell

        super().__init__()
        ib.ext.Order.Order.__init__(self)  # Invoke 2nd base class

        # Now fill in the specific IB parameters
        # Order type
        self.m_orderType = self._IBOrdTypes[self.exectype]
        # todo m_permid?
        self.m_permid = 0

        # 'B' or 'S' should be enough
        # Order direction
        self.m_action = bytes(action)

        # Set the prices
        # Set IB order parameters based on order type and price
        self.m_lmtPrice = 0.0
        self.m_auxPrice = 0.0

        if self.exectype == self.Market:  # is it really necessary for Market?
            pass
        elif self.exectype == self.Close:  # is it ireally necessary for Close?
            pass
        elif self.exectype == self.Limit:
            self.m_lmtPrice = self.price
        elif self.exectype == self.Stop:
            self.m_auxPrice = self.price  # stop price / exec is market
        elif self.exectype == self.StopLimit:
            self.m_lmtPrice = self.pricelimit  # req limit execution
            self.m_auxPrice = self.price  # trigger price
        elif self.exectype == self.StopTrail:
            if self.trailamount is not None:
                self.m_auxPrice = self.trailamount
            elif self.trailpercent is not None:
                # value expected in % format ... multiply 100.0
                self.m_trailingPercent = self.trailpercent * 100.0
        elif self.exectype == self.StopTrailLimit:
            self.m_trailStopPrice = self.m_lmtPrice = self.price
            # The limit offset is set relative to the price difference in TWS
            self.m_lmtPrice = self.pricelimit
            if self.trailamount is not None:
                self.m_auxPrice = self.trailamount
            elif self.trailpercent is not None:
                # value expected in % format ... multiply 100.0
                self.m_trailingPercent = self.trailpercent * 100.0
        # IB order quantity
        self.m_totalQuantity = abs(self.size)  # ib takes only positives
        # Whether to submit to IB server
        self.m_transmit = self.transmit
        # Parent order
        if self.parent is not None:
            self.m_parentId = self.parent.m_orderId

        # Time In Force: DAY, GTC, IOC, GTD
        # Set order validity period
        if self.valid is None:
            tif = "GTC"  # Good till canceled
        elif isinstance(self.valid, (datetime, date)):
            tif = "GTD"  # Good till date
            self.m_goodTillDate = bytes(self.valid.strftime("%Y%m%d %H:%M:%S"))
        elif isinstance(self.valid, (timedelta,)):
            if self.valid == self.DAY:
                tif = "DAY"
            else:
                tif = "GTD"  # Good till date
                valid = datetime.now() + self.valid  # .now, using localtime
                self.m_goodTillDate = bytes(valid.strftime("%Y%m%d %H:%M:%S"))

        elif self.valid == 0:
            tif = "DAY"
        else:
            tif = "GTD"  # Good till date
            valid = num2date(self.valid)
            self.m_goodTillDate = bytes(valid.strftime("%Y%m%d %H:%M:%S"))

        self.m_tif = bytes(tif)

        # OCA
        self.m_ocaType = 1  # Cancel all remaining orders with block

        # pass any custom arguments to the order
        # Pass keyword arguments to IB order
        for k in kwargs:
            setattr(self, (not hasattr(self, k)) * "m_" + k, kwargs[k])


# IB Commission and Margin Calculation Method
class IBCommInfo(CommInfoBase):
    """
    Commissions are calculated by ib, but the trade calculations in the
    ```Strategy`` rely on the order carrying a CommInfo object attached for the
    calculation of the operation cost and value.

    These are non-critical information, but removing them from the trade could
    break existing usage, and it is better to provide a CommInfo objet which
    enables those calculations even if with approvimate values.

    The margin calculation is not known in advance information with IB
    (margin impact can be gotten from OrderState objects, and therefore it is
    left as a future exercise to get it"""

    def getvaluesize(self, size, price):
        """Calculate the value size for margin calculation.

        Args:
            size (float): Position size.
            price (float): Price of the instrument.

        Returns:
            float: The value size calculated as absolute size times price.
        """
        # In real life, the margin approaches the price
        return abs(size) * price

    def getoperationcost(self, size, price):
        """Returns the necessary amount of cash an operation would cost"""
        # Same reasoning as above
        return abs(size) * price


# Registration mechanism, automatically register broker class when module is imported
def _register_broker_class(broker_cls):
    """Register broker class with the store when module is loaded"""
    from backtrader.stores import ibstore

    ibstore.IBStore.BrokerCls = broker_cls
    return broker_cls


# IBbroker - no longer using metaclass
@_register_broker_class
class IBBroker(BrokerBase):
    """Broker implementation for Interactive Brokers.

    This class maps the orders/positions from Interactive Brokers to the
    internal API of `backtrader`.

    Notes:

      - ``tradeid`` is not really supported, because the profit and loss are
        taken directly from IB. Because (as expected) calculates it in FIFO
        manner, the pnl is not accurate for the tradeid.

      - Position

        If there is an open position for an asset at the beginning of
        operaitons or orders given by other means, change a position, the trades
        calculated in the `Strategy` in cerebro will not reflect the reality.

        To avoid this, this broker would have to do its own position
        management which would also allow tradeid with multiple ids (profit and
        loss would also be calculated locally), but could be considered to be
        defeating the purpose of working with a live broker

    # tradeid is no longer supported, because profit and loss are obtained directly from IB,
    # tradeid's pnl is not accurate
    # If there are positions or orders at the start, the trades calculated by the strategy
    # will not consider the actual situation. To avoid this, this broker would have to do
    # separate position management, allowing tradeid to have multiple id values (profit and
    # loss calculated locally), can be seen as a compromise for live broker
    """

    # IBBroker has no extra parameters, so no need to define parameters

    def __init__(self, **kwargs):
        """Initialize the IBBroker with IBStore connection.

        Args:
            **kwargs: Arguments passed to IBStore for connection setup
                (e.g., host, port, clientId).
        """
        super().__init__()
        # ibstore
        self.ib = ibstore.IBStore(**kwargs)
        # Starting cash, starting value
        self.startingcash = self.cash = 0.0
        self.startingvalue = self.value = 0.0
        # Create an order lock
        self._lock_orders = threading.Lock()  # control access
        # Set orders by id
        self.orderbyid = dict()  # orders by order id
        # Execution information
        self.executions = dict()  # notified executions
        # Order status
        self.ordstatus = collections.defaultdict(dict)
        # Notify order information
        self.notifs = queue.Queue()  # holds orders which are notified
        self.tonotify = collections.deque()  # hold oids to be notified

    # Start
    def start(self):
        """Start the broker and IBStore connection.

        Requests account updates and initializes cash and value from IB.
        Sets starting cash and value to 0.0 if connection fails.
        """
        super().start()
        self.ib.start(broker=self)
        # If connection successful, get account information, update cash and value
        if self.ib.connected():
            self.ib.reqAccountUpdates()
            self.startingcash = self.cash = self.ib.get_acc_cash()
            self.startingvalue = self.value = self.ib.get_acc_value()
        else:
            self.startingcash = self.cash = 0.0
            self.startingvalue = self.value = 0.0

    # Stop
    def stop(self):
        """Stop the broker and IBStore connection.

        Stops the IB connection and cleans up resources.
        """
        super().stop()
        self.ib.stop()

    # Get cash
    def getcash(self):
        """Get the current cash balance from IB.

        Returns:
            float: Current cash balance in the account.
        """
        # This call cannot block if no answer is available from ib
        self.cash = self.ib.get_acc_cash()
        return self.cash

    # Get account value
    def getvalue(self, datas=None):
        """Get the current account value from IB.

        Args:
            datas: Not used, kept for API compatibility.

        Returns:
            float: Current account value including cash and positions.
        """
        self.value = self.ib.get_acc_value()
        return self.value

    # Get position
    def getposition(self, data, clone=True):
        """Get the current position for a data feed from IB.

        Args:
            data: Data feed object.
            clone (bool): Whether to return a cloned position object.
                Defaults to True.

        Returns:
            Position object containing size, price, and other position details.
        """
        return self.ib.getposition(data.tradecontract, clone=clone)

    # Cancel order
    def cancel(self, order):
        """Cancel an active order.

        Args:
            order: IBOrder object to cancel.

        Note:
            If order is already cancelled or not found, this method
            does nothing.
        """
        try:
            _order = self.orderbyid[order.m_orderId]
        except (ValueError, KeyError):
            return  # not found, it was not an order

        if order.status == Order.Cancelled:  # already cancelled
            return

        self.ib.cancelOrder(order.m_orderId)

    # Order status
    def orderstatus(self, order):
        """Get the current status of an order.

        Args:
            order: IBOrder object to query.

        Returns:
            Order.Status: The current status of the order.
        """
        try:
            o = self.orderbyid[order.m_orderId]
        except (ValueError, KeyError):
            o = order

        return o.status

    # Submit order
    def submit(self, order):
        """Submit an order to Interactive Brokers.

        Args:
            order: IBOrder object to submit.

        Returns:
            IBOrder: The submitted order object.
        """
        order.submit(self)

        # ocoize if needed
        if order.oco is None:  # Generate a UniqueId
            order.m_ocaGroup = bytes(uuid.uuid4())
        else:
            order.m_ocaGroup = self.orderbyid[order.oco.m_orderId].m_ocaGroup

        self.orderbyid[order.m_orderId] = order
        self.ib.placeOrder(order.m_orderId, order.data.tradecontract, order)
        self.notify(order)

        return order

    # Get commission and margin information
    def getcommissioninfo(self, data):
        """Get commission information for a data feed.

        Args:
            data: Data feed object.

        Returns:
            IBCommInfo: Commission info object with multiplier and
                stocklike settings based on the contract type.
        """
        contract = data.tradecontract
        try:
            mult = float(contract.m_multiplier)
        except (ValueError, TypeError):
            mult = 1.0

        stocklike = contract.m_secType not in (
            "FUT",
            "OPT",
            "FOP",
        )

        return IBCommInfo(mult=mult, stocklike=stocklike)

    # Create order
    def _makeorder(
        self,
        action,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        **kwargs,
    ):
        """Create an IBOrder with the specified parameters.

        Args:
            action (str): Order direction ('BUY' or 'SELL').
            owner: Owner object (typically a strategy).
            data: Data feed object.
            size (int): Order size (positive for buy, negative for sell).
            price (float, optional): Limit or stop price.
            plimit (float, optional): Limit price for stop-limit orders.
            exectype (Order.ExecType, optional): Order execution type.
            valid (datetime/timedelta, optional): Order validity period.
            tradeid (int, optional): Trade identifier. Defaults to 0.
            **kwargs: Additional IB-specific order parameters.

        Returns:
            IBOrder: Configured order object with commission info attached.
        """
        order = IBOrder(
            action,
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            m_clientId=self.ib.clientId,
            m_orderId=self.ib.nextOrderId(),
            **kwargs,
        )

        order.addcomminfo(self.getcommissioninfo(data))
        return order

    # Buy
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
        **kwargs,
    ):
        """Create and submit a buy order.

        Args:
            owner: Owner object (typically a strategy).
            data: Data feed object.
            size (int): Order size (negative for buy orders).
            price (float, optional): Limit or stop price.
            plimit (float, optional): Limit price for stop-limit orders.
            exectype (Order.ExecType, optional): Order execution type.
            valid (datetime/timedelta, optional): Order validity period.
            tradeid (int, optional): Trade identifier. Defaults to 0.
            **kwargs: Additional IB-specific order parameters.

        Returns:
            IBOrder: The submitted buy order.
        """
        order = self._makeorder(
            "BUY", owner, data, size, price, plimit, exectype, valid, tradeid, **kwargs
        )

        return self.submit(order)

    # Sell
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
        **kwargs,
    ):
        """Create and submit a sell order.

        Args:
            owner: Owner object (typically a strategy).
            data: Data feed object.
            size (int): Order size (positive for sell orders).
            price (float, optional): Limit or stop price.
            plimit (float, optional): Limit price for stop-limit orders.
            exectype (Order.ExecType, optional): Order execution type.
            valid (datetime/timedelta, optional): Order validity period.
            tradeid (int, optional): Trade identifier. Defaults to 0.
            **kwargs: Additional IB-specific order parameters.

        Returns:
            IBOrder: The submitted sell order.
        """
        order = self._makeorder(
            "SELL", owner, data, size, price, plimit, exectype, valid, tradeid, **kwargs
        )

        return self.submit(order)

    # Save notification information
    def notify(self, order):
        """Store a cloned order notification in the notification queue.

        Args:
            order: IBOrder object to notify.
        """
        self.notifs.put(order.clone())

    # Get notification information
    def get_notification(self):
        """Get the next notification from the queue.

        Returns:
            IBOrder or None: The next order notification, or None if queue is empty.
        """
        try:
            return self.notifs.get(False)
        except queue.Empty:
            pass

        return None

    # next, add a None, sets a notification boundary
    def next(self):
        """Mark a notification boundary.

        Places None in the notification queue to signal the end of
        current notifications.
        """
        self.notifs.put(None)  # mark notificatino boundary

    # Order statuses in msg
    # Order status in message
    (SUBMITTED, FILLED, CANCELLED, INACTIVE, PENDINGSUBMIT, PENDINGCANCEL, PRESUBMITTED) = (
        "Submitted",
        "Filled",
        "Cancelled",
        "Inactive",
        "PendingSubmit",
        "PendingCancel",
        "PreSubmitted",
    )

    # Push order status
    def push_orderstatus(self, msg):
        """Process and update order status from IB message.

        Args:
            msg: Order status message from IB containing orderId,
                status, and filled quantity.

        Note:
            Handles various order states including Submitted, Cancelled,
            Inactive, Filled, PendingSubmit, PreSubmitted, and PendingCancel.
        """
        # Cancelled and Submitted with Filled = 0 can be pushed immediately
        try:
            order = self.orderbyid[msg.orderId]
        except KeyError:
            return  # not found, it was not an order

        if msg.status == self.SUBMITTED and msg.filled == 0:
            if order.status == order.Accepted:  # duplicate detection
                return

            order.accept(self)
            self.notify(order)

        elif msg.status == self.CANCELLED:
            # duplicate detection
            if order.status in [order.Cancelled, order.Expired]:
                return

            if order._willexpire:
                # An openOrder has been seen with PendingCancel/Cancelled
                # and this happens when an order expires
                order.expire()
            else:
                # Pure user cancellation happens without an openOrder
                order.cancel()
            self.notify(order)

        elif msg.status == self.PENDINGCANCEL:
            # In theory, this message should not be seen according to the docs,
            # but other messages like PENDINGSUBMIT which are similarly
            # described in the docs have been received in the demo
            if order.status == order.Cancelled:  # duplicate detection
                return

            # We do nothing because the situation is handled with the 202 error
            # code if no orderStatus with CANCELLED is seen
            # order.cancel()
            # self.notify(order)

        elif msg.status == self.INACTIVE:
            # This is tricky, because the instances seen have led to
            # order rejection in the demo, but according to the docs, there may
            # be a number of reasons, and it seems like it could be reactivated
            if order.status == order.Rejected:  # duplicate detection
                return

            order.reject(self)
            self.notify(order)

        elif msg.status in [self.SUBMITTED, self.FILLED]:
            # These two are kept inside the order until execdetails and
            # commission are all in place - commission is the last to come
            self.ordstatus[msg.orderId][msg.filled] = msg

        elif msg.status in [self.PENDINGSUBMIT, self.PRESUBMITTED]:
            # According to the docs, these statuses can only be set by the
            #  programmer, but the demo account sent it back at random times with
            # "filled"
            if msg.filled:
                self.ordstatus[msg.orderId][msg.filled] = msg
        else:  # Unknown status ...
            pass

    # Push execution
    def push_execution(self, ex):
        """Store an execution report from IB.

        Args:
            ex: Execution object containing execution details including
                execution ID, order ID, shares, price, and time.
        """
        self.executions[ex.m_execId] = ex

    # Push order, commission and other information
    def push_commissionreport(self, cr):
        """Process commission report and update order execution details.

        Args:
            cr: Commission report object containing execution ID,
                commission amount, and realized P&L.

        Note:
            This method updates the order with execution details,
            calculates closed/opened positions and commissions, and
            triggers order notifications.
        """
        with self._lock_orders:
            ex = self.executions.pop(cr.m_execId)
            oid = ex.m_orderId
            order = self.orderbyid[oid]
            ostatus = self.ordstatus[oid].pop(ex.m_cumQty)

            position = self.getposition(order.data, clone=False)
            pprice_orig = position.price
            size = ex.m_shares if ex.m_side[0] == "B" else -ex.m_shares
            price = ex.m_price
            # use pseudoupdate and let the updateportfolio do the real update?
            psize, pprice, opened, closed = position.update(size, price)

            # split commission between closed and opened
            comm = cr.m_commission
            closedcomm = comm * closed / size
            openedcomm = comm - closedcomm

            comminfo = order.comminfo
            closedvalue = comminfo.getoperationcost(closed, pprice_orig)
            openedvalue = comminfo.getoperationcost(opened, price)

            # default in m_pnl is MAXFLOAT
            pnl = cr.m_realizedPNL if closed else 0.0

            # The internal broker calc should yield the same result
            # pnl = comminfo.profitandloss(-closed, pprice_orig, price)

            # Use the actual time provided by the execution object
            # The report from TWS is in actual local time, not the data's tz
            dt = date2num(datetime.strptime(ex.m_time, "%Y%m%d  %H:%M:%S"))

            # Need to simulate a margin, but it plays no role, because it is
            # controlled by a real broker. Let's set the price of the item
            margin = order.data.close[0]

            order.execute(
                dt,
                size,
                price,
                closed,
                closedvalue,
                closedcomm,
                opened,
                openedvalue,
                openedcomm,
                margin,
                pnl,
                psize,
                pprice,
            )

            if ostatus.status == self.FILLED:
                order.completed()
                self.ordstatus.pop(oid)  # nothing left to be reported
            else:
                order.partial()

            if oid not in self.tonotify:  # Lock needed
                self.tonotify.append(oid)

    # Push portfolio update information
    def push_portupdate(self):
        """Process portfolio update and notify pending orders.

        Note:
            Called when IBStore receives a portfolio update. Notifies
            all orders pending notification. Portfolio updates intermixed
            with split executions signal that the strategy can be notified.
        """
        # If the IBStore receives a Portfolio update, then this method will be
        # indicated. If the execution of an order is split in serveral lots,
        # updatePortfolio messages will be intermixed, which is used as a
        # signal to indicate that the strategy can be notified
        with self._lock_orders:
            while self.tonotify:
                oid = self.tonotify.popleft()
                order = self.orderbyid[oid]
                self.notify(order)

    # Push order error information
    def push_ordererror(self, msg):
        """Process order error messages from IB.

        Args:
            msg: Error message object containing error code and order ID.

        Note:
            Handles error code 202 (order cancellation) and 201 (order rejection).
            All other error codes result in order rejection.
        """
        with self._lock_orders:
            try:
                order = self.orderbyid[msg.id]
            except (KeyError, AttributeError):
                return  # no order or no id in error

            if msg.errorCode == 202:
                if not order.alive():
                    return
                order.cancel()

            elif msg.errorCode == 201:  # rejected
                if order.status == order.Rejected:
                    return
                order.reject()

            else:
                order.reject()  # default for all other cases

            self.notify(order)

    # Push order status
    def push_orderstate(self, msg):
        """Process order state messages from IB.

        Args:
            msg: Order state message containing orderId and orderState
                with status information.

        Note:
            Detects when orders are about to expire by checking for
            PendingCancel/Cancelled status in openOrder messages.
        """
        with self._lock_orders:
            try:
                order = self.orderbyid[msg.orderId]
            except (KeyError, AttributeError):
                return  # no order or no id in error

            if msg.orderState.m_status in ["PendingCancel", "Cancelled", "Canceled"]:
                # This is most likely due to an expiration
                order._willexpire = True
