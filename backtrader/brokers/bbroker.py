#!/usr/bin/env python
"""Back Broker Module - Backtesting broker simulation.

This module provides the BackBroker for simulating broker behavior
during backtesting.

Classes:
    BackBroker: Broker simulator for backtesting (alias: BrokerBack).

Example:
    >>> cerebro = bt.Cerebro()
    >>> # Uses BackBroker by default
"""

import collections
import datetime

from backtrader.broker import BrokerBase

# from backtrader.comminfo import CommInfoBase
from backtrader.order import BuyOrder, Order, SellOrder
from backtrader.parameters import Float, ParameterDescriptor
from backtrader.position import Position
from backtrader.utils.py3 import integer_types, string_types

__all__ = ["BackBroker", "BrokerBack"]


class _CashDescriptor(ParameterDescriptor):
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self

        try:
            cash = object.__getattribute__(obj, "_cash")
            if cash is not None:
                return cash
        except AttributeError:
            pass

        return super().__get__(obj, objtype)


class BackBroker(BrokerBase):
    """Broker Simulator

    The simulation supports different order types, checking a submitted order
    cash requirements against current cash, keeping track of cash and value
    for each iteration of ``cerebro`` and keeping the current position on
    different datas.

    *cash* is adjusted on each iteration for instruments like ``futures`` for
     which a price change implies in real brokers the addition/subtraction of
     cash.
      # This backtesting simulation class supports different order types, checks if current cash meets the cash requirements for submitted orders,
      # checks cash and value at each bar, and positions on different data feeds

    Supported order types:

      - ``Market``: to be executed with the 1st tick of the next bar (namely
        the ``open`` price)

      - ``Close``: meant for intraday in which the order is executed with the
        closing price of the last bar of the session

      - ``Limit``: executes if the given limit price is seen during the
        session

      - ``Stop``: executes a ``Market`` order if the given stop price is seen

      - ``StopLimit``: sets a ``Limit`` order in motion if the given stop
        price is seen

      # Supported order types include the five basic types above. In fact, there are other order types supported. Refer to previous tutorials
      # https://blog.csdn.net/qq_26948675/article/details/122868368

    Because the broker is instantiated by ``Cerebro`` and there should be
    (mostly) no reason to replace the broker, the params are not controlled
    by the user for the instance.  To change this there are two options:

      1. Manually create an instance of this class with the desired params
         and use ``cerebro.broker = instance`` to set the instance as the
         broker for the ``run`` execution

      2. Use the ``set_xxx`` to set the value using
         ``cerebro.broker.set_xxx`` where ```xxx`` stands for the name of the
         parameter to set

      .. note::

         ``cerebro.broker`` is a *property* supported by the ``getbroker``
         and ``setbroker`` methods of ``Cerebro``

      # Normally there is no need to set broker parameters. If setting is needed, there are usually two methods: first is to create a broker instance, then cerebro.broker = instance
      # The second method is to use cerebro.broker.set_xxx to set different parameters


    Params:
          # The meanings of some parameters are below

      - ``cash`` (default: ``10000``): starting cash
          # cash is the starting capital amount, default is 10000

      - ``commission`` (default: ``CommInfoBase(percabs=True)``)
        base commission scheme which applies to all assets
          # Commission class for how to charge commissions, margin, etc. for asset trading. Default is CommInfoBase(percabs=True)

      - ``checksubmit`` (default: ``True``)
        check margin/cash before accepting an order into the system
        # Whether to check if margin and cash are sufficient when passing an order to the system. Default is to check

      - ``eosbar`` (default: ``False``):
        With intraday bars consider a bar with the same ``time`` as the end
        of session to be the end of the session. This is not usually the
        case, because some bars (final auction) are produced by many
        exchanges for many products for a couple of minutes after the end of
        the session
          # End-of-session bar, default is False. For intraday bars, consider a bar with the same time as the end of session as the end of day's trading.
          # However, this is usually not the case, because many assets' bars are formed through final auctions at many exchanges a few minutes after the end of the day's trading time

      - ``filler`` (default: ``None``)

        A callable with signature: ``callable(order, price, ago)``

          - ``order``: obviously the order in execution. This provides access
            to the *data* (and with it the *ohlc* and *volume* values), the
            *execution type*, remaining size (``order.executed.remsize``) and
            others.

            Please check the ``Order`` documentation and reference for things
            available inside an ``Order`` instance

          - ``price`` the price at which the order is going to be executed in
            the ``ago`` bar

          - ``ago``: index meant to be used with ``order.data`` for the
            extraction of the *ohlc* and *volume* prices. In most cases this
            will be ``0`` but on a corner case for ``Close`` orders, this
            will be ``-1``.

            In order to get the bar volume (for example) do: ``volume =
            order.data.voluume[ago]``

        The callable must return the *executed size* (a value >= 0)

        The callable may of course be an object with ``__call__`` matching
        the aforementioned signature

        With the default ``None`` orders will be completely executed in a
        single shot

        # filler is a callable object, default is None. In this case, all trading volume can be executed; if filler is not None,
        # it will calculate the executable order size based on order, price, ago
        # Reference articles: https://blog.csdn.net/qq_26948675/article/details/124566885?spm=1001.2014.3001.5501
        # https://yunjinqi.blog.csdn.net/article/details/113445040


      - ``slip_perc`` (default: ``0.0``) Percentage in absolute terms (and
        positive) that should be used to slip prices up/down for buy/sell
        orders

        Note:

          - ``0.01`` is ``1%``

          - ``0.001`` is ``0.1%``
          # Percentage slippage form

      - ``slip_fixed`` (default: ``0.0``) Percentage in units (and positive)
        that should be used to slip prices up/down for buy/sell orders

        Note: if ``slip_perc`` is non zero, it takes precedence over this.

          # Fixed slippage form. If percentage slippage is not 0, only percentage slippage is considered

      - ``slip_open`` (default: ``False``) whether to slip prices for order
        execution which would specifically used the *opening* price of the
        next bar. An example would be ``Market`` order which is executed with
        the next available tick, i.e: the opening price of the bar.

        This also applies to some of the other executions, because the logic
        tries to detect if the *opening* price would match the requested
        price/execution type when moving to a new bar.
          # Whether to use the next bar's opening price when calculating slippage

      - ``slip_match`` (default: ``True``)

        If ``True`` the broker will offer a match by capping slippage at
        ``high/low`` prices in case they would be exceeded.

        If ``False`` the broker will not match the order with the current
        prices and will try execution during the next iteration
          # If the price with slippage exceeds the high or low price, and if slip_match is set to True, the execution price will be calculated based on the high or low price
          # If not set to True, it will wait for the next bar to attempt execution

      - ``slip_limit`` (default: ``True``)

        ``Limit`` orders, given the exact match price requested, will be
        matched even if ``slip_match`` is ``False``.

        This option controls that behavior.

        If ``True``, then ``Limit`` orders will be matched by capping prices
        to the ``limit`` / ``high/low`` prices

        If ``False`` and slippage exceeds the cap, then there will be no
        match
          # Limit orders will seek strict matching, even when slip_match is False
          # If slip_limit is set to True, limit orders will be executed if they are between the high and low prices
          # If set to False, limit orders with slippage that exceeds high and low prices will not be executed

      - ``slip_out`` (default: ``False``)

        Provide *slippage* even if the price falls outside the ``high`` -
        ``low`` range.
          # When slip_out is set to True, slippage will be provided even if the price exceeds the high-low range

      - ``coc`` (default: ``False``)

        *Cheat-On-Close* Setting this to ``True`` with ``set_coc`` enables
         matching a ``Market`` order to the closing price of the bar in which
         the order was issued. This is actually *cheating*, because the bar
         is *closed* and any order should first be matched against the prices
         in the next bar
          # When coc is set to True, when placing a market order, it allows execution at the closing price
      - ``coo`` (default: ``False``)

        *Cheat-On-Open* Setting this to ``True`` with ``set_coo`` enables
         matching a ``Market`` order to the opening price, by for example
         using a timer with ``cheat`` set to ``True``, because such a timer
         gets executed before the broker has evaluated
          # When coo is set to True, market orders are allowed to execute at the opening price, similar to tbquant mode

      - ``int2pnl`` (default: ``True``)

        Assign generated interest (if any) to the profit and loss of
        operation that reduces a position (be it long or short). There may be
        cases in which this is undesired, because different strategies are
        competing and the interest would be assigned on a non-deterministic
        basis to any of them.
        # int2pnl, default is True. TODO: Understand literally as transferring generated interest costs to pnl

      - ``shortcash`` (default: ``True``)

        If True then cash will be increased when a stocklike asset is shorted
        and the calculated value for the asset will be negative.

        If ``False`` then the cash will be deducted as operation cost and the
        calculated value will be positive to end up with the same amount

        # For stock-like assets, if this parameter is set to True, when short selling, the available cash will increase, but the asset value will be negative
        # If this parameter is set to False, when short selling, the available cash decreases, and the asset value is positive

      - ``fundstartval`` (default: ``100.0``)

        This parameter controls the start value for measuring the performance
        in a fund-like way, i.e.: cash can be added and deducted increasing
        the amount of shares. Performance is not measured using the net
        asset value of the portfolio but using the value of the fund
        # fundstartval will calculate performance in fund mode

      - ``fundmode`` (default: ``False``)

        If this is set to ``True`` analyzers like ``TimeReturn`` can
        automatically calculate returns based on the fund value and not on
        the total net asset value
        # If fundmode is set to True, some analyzers like TimeReturn will use fund value to calculate returns

    """

    # Use the new parameter descriptor system
    cash = _CashDescriptor(default=10000.0, type_=float, doc="Starting cash amount")

    checksubmit = ParameterDescriptor(
        default=True, type_=bool, doc="Check margin/cash before accepting orders"
    )

    eosbar = ParameterDescriptor(
        default=False,
        type_=bool,
        doc="Consider bar with same time as end of session as end of session",
    )

    filler = ParameterDescriptor(default=None, doc="Volume filler callable for order execution")

    slip_perc = ParameterDescriptor(
        default=0.0, type_=float, validator=Float(min_val=0.0), doc="Percentage slippage for orders"
    )

    slip_fixed = ParameterDescriptor(
        default=0.0, type_=float, validator=Float(min_val=0.0), doc="Fixed slippage for orders"
    )

    slip_open = ParameterDescriptor(
        default=False, type_=bool, doc="Apply slippage to opening prices"
    )

    slip_match = ParameterDescriptor(
        default=True, type_=bool, doc="Cap slippage at high/low prices"
    )

    slip_limit = ParameterDescriptor(
        default=True, type_=bool, doc="Allow limit order matching with slippage capping"
    )

    slip_out = ParameterDescriptor(
        default=False, type_=bool, doc="Provide slippage even outside high-low range"
    )

    coc = ParameterDescriptor(
        default=False, type_=bool, doc="Cheat-On-Close: match market orders to closing price"
    )

    coo = ParameterDescriptor(
        default=False, type_=bool, doc="Cheat-On-Open: match market orders to opening price"
    )

    int2pnl = ParameterDescriptor(
        default=True, type_=bool, doc="Assign interest to profit and loss"
    )

    shortcash = ParameterDescriptor(
        default=True, type_=bool, doc="Increase cash when shorting stocklike assets"
    )

    fundstartval = ParameterDescriptor(
        default=100.0,
        type_=float,
        validator=Float(min_val=0.0),
        doc="Starting value for fund-like performance measurement",
    )

    fundmode = ParameterDescriptor(
        default=False, type_=bool, doc="Enable fund-like performance calculation"
    )

    def __init__(self, **kwargs):
        """Initialize the BackBroker instance.

        Args:
            **kwargs: Keyword arguments for parameter initialization
        """
        super().__init__(**kwargs)
        # Used to save order history records
        self._cash_addition = None
        self._ocol = None
        self._fundshares = None
        self._fundval = None
        self._ocos = None
        self._pchildren = None
        self.submitted = None
        self.notifs = None
        self.d_credit = None
        self.positions = None
        self._toactivate = None
        self.pending = None
        self.orders = None
        self._unrealized = None
        self._leverage = None
        self._valuemktlever = None
        self._valuelever = None
        self._valuemkt = None
        self._value = None
        # Comment: Do not directly set self.cash = None, this will override the value in the parameter system
        # Instead use _cash as an internal state variable, initialize it in init()
        self._cash = None
        self.startingcash = None
        self._userhist = []
        # Used to save fund history records
        self._fundhist = []
        # share_value, net asset value
        # Used to save fund shares and net asset value
        self._fhistlast = [float("NaN"), float("NaN")]

    def init(self):
        """Initialize broker state and internal data structures.

        This method sets up the initial cash, positions, orders, and other
        broker-related data structures. Called during cerebro initialization.
        """
        super().init()
        # Initial cash at the start - obtained from parameter system
        cash_param = self.get_param("cash")
        self.startingcash = self._cash = cash_param
        # Unleveraged account value
        self._value = self._cash
        # Unleveraged position value
        self._valuemkt = 0.0  # no open position
        # Leveraged account value
        self._valuelever = 0.0  # no open position
        # Leveraged position market value
        self._valuemktlever = 0.0  # no open position
        # Leverage
        self._leverage = 1.0  # initially nothing is open
        # Unrealized profit
        self._unrealized = 0.0  # no open position
        # Orders
        self.orders = list()  # will only be appending
        # Double-ended queue
        self.pending = collections.deque()  # popleft and append(right)
        self._toactivate = collections.deque()  # to activate in next cycle
        # Position
        self.positions = collections.defaultdict(Position)
        # Interest rate
        self.d_credit = collections.defaultdict(float)  # credit per data
        # Double-ended queue for notification info
        self.notifs = collections.deque()
        # Double-ended queue for submissions
        self.submitted = collections.deque()

        # to keep dependent orders if needed
        # If independent orders need to be kept
        self._pchildren = collections.defaultdict(collections.deque)
        # ocos
        self._ocos = dict()
        # ocol
        self._ocol = collections.defaultdict(list)
        # fund value
        self._fundval = self.get_param("fundstartval")
        # fund shares
        self._fundshares = self.get_param("cash") / self._fundval
        # Cash addition
        self._cash_addition = collections.deque()

    def get_notification(self):
        """Get the next notification from the notification queue.

        Returns:
            Order notification if available, None otherwise
        """
        try:
            return self.notifs.popleft()
        except IndexError:
            pass

        return None

    # Set fund mode
    def set_fundmode(self, fundmode, fundstartval=None):
        """Set the actual fundmode (True or False)

        If the argument fundstartval is not ``None``, it will use
        """
        self.set_param("fundmode", fundmode)
        if fundstartval is not None:
            self.set_fundstartval(fundstartval)

    def get_fundmode(self):
        """Get the current fund mode status.

        Returns:
            bool: True if fund mode is enabled, False otherwise
        """
        return self.get_param("fundmode")

    def set_fundstartval(self, fundstartval):
        """Set the starting value for fund-like performance tracking.

        Args:
            fundstartval: The starting value for the fund
        """
        self.set_param("fundstartval", fundstartval)

    def set_int2pnl(self, int2pnl):
        """Configure assignment of interest to profit and loss.

        Args:
            int2pnl: If True, interest is assigned to PnL when positions close
        """
        self.set_param("int2pnl", int2pnl)

    def set_coc(self, coc):
        """Configure Cheat-On-Close behavior.

        When enabled, market orders can execute at the closing price of the
        bar in which they were issued.

        Args:
            coc: If True, enable cheat-on-close
        """
        self.set_param("coc", coc)

    def set_coo(self, coo):
        """Configure Cheat-On-Open behavior.

        When enabled, market orders can execute at the opening price.

        Args:
            coo: If True, enable cheat-on-open
        """
        self.set_param("coo", coo)

    def set_shortcash(self, shortcash):
        """Configure short cash behavior for stock-like assets.

        Args:
            shortcash: If True, increase cash when shorting stock-like assets
        """
        self.set_param("shortcash", shortcash)

    def set_slippage_perc(
        self, perc, slip_open=True, slip_limit=True, slip_match=True, slip_out=False
    ):
        """Configure percentage-based slippage.

        Args:
            perc: Slippage percentage (e.g., 0.01 for 1%)
            slip_open: Apply slippage to opening prices
            slip_limit: Allow limit order matching with slippage capping
            slip_match: Cap slippage at high/low prices
            slip_out: Provide slippage even outside high-low range
        """
        self.set_param("slip_perc", perc)
        self.set_param("slip_fixed", 0.0)
        self.set_param("slip_open", slip_open)
        self.set_param("slip_limit", slip_limit)
        self.set_param("slip_match", slip_match)
        self.set_param("slip_out", slip_out)

    def set_slippage_fixed(
        self, fixed, slip_open=True, slip_limit=True, slip_match=True, slip_out=False
    ):
        """Configure fixed-point slippage.

        Args:
            fixed: Fixed slippage amount in price units
            slip_open: Apply slippage to opening prices
            slip_limit: Allow limit order matching with slippage capping
            slip_match: Cap slippage at high/low prices
            slip_out: Provide slippage even outside high-low range
        """
        self.set_param("slip_perc", 0.0)
        self.set_param("slip_fixed", fixed)
        self.set_param("slip_open", slip_open)
        self.set_param("slip_limit", slip_limit)
        self.set_param("slip_match", slip_match)
        self.set_param("slip_out", slip_out)

    def set_filler(self, filler):
        """Set a volume filler callable for order execution.

        Args:
            filler: Callable with signature (order, price, ago) -> executed_size
        """
        self.set_param("filler", filler)

    def set_checksubmit(self, checksubmit):
        """Set whether to check margin/cash before accepting orders.

        Args:
            checksubmit: If True, validate margin/cash before order submission
        """
        self.set_param("checksubmit", checksubmit)

    def set_eosbar(self, eosbar):
        """Set end-of-session bar behavior.

        Args:
            eosbar: If True, consider bar with same time as end of session as EOS
        """
        self.set_param("eosbar", eosbar)

    seteosbar = set_eosbar

    def get_cash(self):
        """Get the current available cash.

        Returns:
            float: Current cash amount. Returns parameter value if not yet
                initialized, otherwise returns current cash status.
        """
        if hasattr(self, "_cash") and self._cash is not None:
            return self._cash
        else:
            return self.get_param("cash")

    getcash = get_cash

    # CRITICAL FIX: Override __getattribute__ to return runtime _cash value
    # when accessing broker.cash, instead of the initial parameter value
    # def __getattribute__(self, name):
    #     """Override attribute access to return runtime cash value.

    #     Args:
    #         name: Attribute name being accessed

    #     Returns:
    #         Runtime _cash value if accessing 'cash', otherwise the attribute value
    #     """
    #     if name == "cash":
    #         # Use object.__getattribute__ to avoid recursion
    #         try:
    #             _cash = object.__getattribute__(self, "_cash")
    #             if _cash is not None:
    #                 return _cash
    #         except AttributeError:
    #             pass
    #         # Fall back to parameter value if _cash not set yet
    #         try:
    #             param_manager = object.__getattribute__(self, "_param_manager")
    #             return param_manager.get("cash", 10000.0)
    #         except AttributeError:
    #             return 10000.0  # Default value
    #     return object.__getattribute__(self, name)

    __getattribute__ = object.__getattribute__

    def set_cash(self, cash):
        """Set the broker cash amount.

        Args:
            cash: Cash amount to set
        """
        self.startingcash = self._cash = cash
        self.set_param("cash", cash)
        self._value = cash

    setcash = set_cash

    def add_cash(self, cash):
        """Add or remove cash from the system.

        Args:
            cash: Cash amount to add (use negative value to remove)
        """
        self._cash_addition.append(cash)

    def get_fundshares(self):
        """Get the current number of fund shares.

        Returns:
            float: Current number of shares in fund-like mode
        """
        return self._fundshares

    fundshares = property(get_fundshares)

    def get_fundvalue(self):
        """Get the fund share value.

        Returns:
            float: Current fund-like share value
        """
        return self._fundval

    fundvalue = property(get_fundvalue)

    def cancel(self, order, bracket=False):
        """Cancel an order.

        Args:
            order: The order to cancel
            bracket: If True, cancel as part of bracket order

        Returns:
            bool: True if order was cancelled, False if not found
        """
        try:
            self.pending.remove(order)
        except ValueError:
            # If the list didn't have the element we didn't cancel anything
            return False

        order.cancel()
        self.notify(order)
        self._ococheck(order)
        if not bracket:
            self._bracketize(order, cancel=True)
        return True

    # Get value, if data is not specified, get the value of the entire account
    def get_value(self, datas=None, mkt=False, lever=False):
        """Returns the portfolio value of the given datas (if datas is ``None``, then
        the total portfolio value will be returned (alias: ``getvalue``)
        """
        if datas is None:
            if mkt:
                return self._valuemkt if not lever else self._valuemktlever

            return self._value if not lever else self._valuelever

        return self._get_value(datas=datas, lever=lever)

    getvalue = get_value

    # TODO This function is only declared here and not used anywhere else, unused function, commented out
    # def get_value_lever(self, datas=None, mkt=False):
    #     return self.get_value(datas=datas, mkt=mkt)

    def _get_value(self, datas=None, lever=False):
        """Calculate portfolio value for given data feeds.

        Args:
            datas: Data feeds to calculate value for (None for all)
            lever: If True, return leveraged value

        Returns:
            float: Portfolio value
        """
        # Position value
        pos_value = 0.0
        # Unleveraged position value
        pos_value_unlever = 0.0
        # Unrealized profit
        unrealized = 0.0

        shortcash = self.get_param("shortcash")
        positions = self.positions
        getcommissioninfo = self.getcommissioninfo

        # If cash is added, add the cash to self._cash
        cash_addition = self._cash_addition
        while cash_addition:
            c = cash_addition.popleft()
            self._fundshares += c / self._fundval
            self._cash += c

        # If datas is None, loop through self.positions; if datas is not None, loop through datas
        for data in datas or positions:
            # Get commission related info
            comminfo = getcommissioninfo(data)
            # Get data position
            position = positions[data]
            close0 = data.close[0]
            # use valuesize:  returns raw value, rather than negative adj val
            # If shortcash is False, use comminfo.getvalue to get data value
            # If shortcash is True, use comminfo.getvaluesize to get data value
            if not shortcash:
                dvalue = comminfo.getvalue(position, close0)
            else:
                dvalue = comminfo.getvaluesize(position.size, close0)
            # Get unrealized profit of data
            dunrealized = comminfo.profitandloss(position.size, position.price, close0)
            leverage = comminfo.get_leverage()
            # If datas is not None and datas is a list containing one data
            if datas and len(datas) == 1:
                # If lever is True and dvalue is greater than 0, calculate the initial dvalue value, then divide by leverage and add unrealized profit to get data value
                if lever and dvalue > 0:
                    dvalue -= dunrealized
                    return (dvalue / leverage) + dunrealized
                # If lever is False or dvalue<0 due to shortcash, return dvalue
                return dvalue  # raw data value requested, short selling is neg
            # If shortcash is False
            if not shortcash:
                dvalue = abs(dvalue)  # short selling adds value in this case
            # Position value equals position value plus data value
            pos_value += dvalue
            # Unrealized profit equals unrealized profit plus data unrealized profit
            unrealized += dunrealized
            # If dvalue is greater than 0, calculate unleveraged position value
            if dvalue > 0:  # long position - unlever
                dvalue -= dunrealized
                # TODO Why is it necessary to reset pos_value_unlever every time
                pos_value_unlever += dvalue / leverage
                pos_value_unlever += dunrealized
            else:
                pos_value_unlever += dvalue
        # If not in fundhist mode, calculate _value and fundval
        if not self._fundhist:
            # TODO Commented out unused v
            # self._value = v = self._cash + pos_value_unlever
            self._value = self._cash + pos_value_unlever
            self._fundval = self._value / self._fundshares  # update fundvalue
        # If in fundhist mode
        else:
            # Try to fetch a value
            # Call function _process_fund_history() to get fval and fvalue
            fval, fvalue = self._process_fund_history()
            # _value equals fvalue
            self._value = fvalue
            # cash equals fvalue minus unleveraged position
            self._cash = fvalue - pos_value_unlever
            # _fundval = fval
            self._fundval = fval
            # _fund shares
            self._fundshares = fvalue / fval
            # Leverage multiplier
            lev = pos_value / (pos_value_unlever or 1.0)

            # update the calculated values above to the historical values
            # Unleveraged position value
            pos_value_unlever = fvalue
            # Leveraged position value
            pos_value = fvalue * lev
        # Unleveraged position value
        self._valuemkt = pos_value_unlever
        # Leveraged account value
        self._valuelever = self._cash + pos_value
        # Leveraged position value
        self._valuemktlever = pos_value
        # Leverage ratio
        self._leverage = pos_value / (pos_value_unlever or 1.0)
        # Unrealized profit
        self._unrealized = unrealized

        return self._value if not lever else self._valuelever

    def get_leverage(self):
        """Get the current account leverage ratio.

        Returns:
            float: Current leverage ratio
        """
        return self._leverage

    # Get pending orders
    def get_orders_open(self, safe=False):
        """Returns an iterable with the orders which are still open (either not
        executed or partially executed)

        The orders returned must not be touched.

        If order manipulation is needed, set the parameter ``safe`` to True
        """
        if safe:
            os = [x.clone() for x in self.pending]
        else:
            os = [x for x in self.pending]

        return os

    def getposition(self, data):
        """Get the current position status for a data feed.

        Args:
            data: Data feed to get position for

        Returns:
            Position: Current position instance for the data feed
        """
        return self.positions[data]

    def orderstatus(self, order):
        """Get the status of an order.

        Args:
            order: Order object or order reference

        Returns:
            Order.Status: The current status of the order
        """
        try:
            o = self.orders.index(order)
        except ValueError:
            o = order

        return o.status

    def _take_children(self, order):
        """Handle parent-child relationship for bracket orders.

        Args:
            order: Order to process for parent-child relationship

        Returns:
            Parent order reference if successful, None if order rejected
        """
        # Order ID
        oref = order.ref
        # Get parent order ID of order, if not found then it's itself
        pref = getattr(order.parent, "ref", oref)  # parent ref or self
        # If child order ID and parent order ID are not equal
        if oref != pref:
            # If parent order ID is not in _pchildren, the order will be rejected and return None
            if pref not in self._pchildren:
                order.reject()  # parent not there - may have been rejected
                self.notify(order)  # reject child, notify
                return None
        # If they are equal, return parent order ID
        return pref

    def submit(self, order, check=True):
        """Submit an order to the broker.

        Args:
            order: Order object to submit
            check: If True, validate order before submission

        Returns:
            Order: The submitted order or parent order if part of bracket
        """
        # Get parent order ID of order or its own ID, if this ID is None, return order itself
        pref = self._take_children(order)
        if pref is None:  # order has not been taken
            return order
        # pc is a deque that saves parent and children orders
        pc = self._pchildren[pref]
        pc.append(order)  # store in parent/children queue
        # If order is transmit, call transmit function for orders in pc and return the last order
        if order.transmit:  # if single order, sent and queue cleared
            # if parent-child, the parent will be sent, the other kept
            rets = [self.transmit(x, check=check) for x in pc]
            return rets[-1]  # last one is the one triggering transmission

        return order

    def transmit(self, order, check=True):
        """Transmit an order for execution.

        Args:
            order: Order to transmit
            check: If True, check margin/cash before accepting

        Returns:
            Order: The transmitted order
        """
        # If check is True and checksubmit is True
        if check and self.get_param("checksubmit"):
            # Orderssubmit
            order.submit()
            # Append order to submitted
            self.submitted.append(order)
            # Append order to orders
            self.orders.append(order)
            # Notify order
            self.notify(order)
        # If either check or checksubmit is False, append order to submit_accept
        else:
            self.submit_accept(order)
        # Return order
        return order

    def check_submitted(self):
        """Check and validate submitted orders against available cash and margin.

        Processes all orders in the submitted queue and validates them
        against current cash and margin requirements.
        """
        # Currently available cash
        cash = self._cash
        # Position
        positions = dict()
        # When submitted is not empty
        while self.submitted:
            # Remove leftmost order and get it
            order = self.submitted.popleft()
            # If the result of calling _take_children(order) is None, this order will be rejected, continue to next order
            if self._take_children(order) is None:  # children not taken
                continue
            # Get commission info class
            # comminfo = self.getcommissioninfo(order.data)
            # TODO Commented out unused comminfo
            # Get position
            position = positions.setdefault(order.data, self.positions[order.data].clone())
            # pseudo-execute the order to get the remaining cash after exec
            # Cash obtained after assuming order execution
            cash = self._execute(order, cash=cash, position=position)
            # If remaining cash is greater than 0, call submit_accept to accept order
            if cash >= 0.0:
                self.submit_accept(order)
                continue
            # If cash is less than 0, insufficient margin, notify order status, call _ococheck and _bracketize
            order.margin()
            self.notify(order)
            self._ococheck(order)
            self._bracketize(order, cancel=True)

    def submit_accept(self, order):
        """Accept and activate a submitted order.

        Args:
            order: Order to accept
        """
        # TODO Set additional pannotated attribute for order, purpose unknown for now
        order.pannotated = None
        # Order submit
        order.submit()
        # Order accept
        order.accept()
        # Add order to pending orders
        self.pending.append(order)
        # Notify order status
        self.notify(order)

    def _bracketize(self, order, cancel=False):
        """Handle bracket order activation or cancellation.

        Args:
            order: Order in a bracket order group
            cancel: If True, cancel remaining orders in bracket
        """
        # Ordersid
        oref = order.ref
        # Parent order ID or own ID
        pref = getattr(order.parent, "ref", oref)
        # If two IDs are equal, parent is True
        parent = oref == pref
        # Get order deque
        pc = self._pchildren[pref]  # defdict - guaranteed
        # If cancel is True or parent is not True,
        if cancel or not parent:  # cancel left or child exec -> cancel other
            # If pc has orders, will keep running, cancel orders
            while pc:
                self.cancel(pc.popleft(), bracket=True)  # idempotent
            # Delete this key, value
            del self._pchildren[pref]  # defdict guaranteed
        # If neither of the above conditions is met, i.e., cancel is False and parent is True
        else:  # not cancel -> parent exec'd
            # Clear parent order, then change child order status to inactive
            pc.popleft()  # remove parent
            for o in pc:  # activate children
                self._toactivate.append(o)

    def _ococheck(self, order):
        """Check and handle OCO (One-Cancels-Other) order relationships.

        Args:
            order: Order to check for OCO relationships
        """
        # ocoref = self._ocos[order.ref] or order.ref  # a parent or self
        parentref = self._ocos[order.ref]
        ocoref = self._ocos.get(parentref, None)
        ocol = self._ocol.pop(ocoref, None)
        if ocol:
            for i in range(len(self.pending) - 1, -1, -1):
                o = self.pending[i]
                if o is not None and o.ref in ocol:
                    del self.pending[i]
                    o.cancel()
                    self.notify(o)

    def _ocoize(self, order, oco):
        """Set up OCO (One-Cancels-Other) relationship for an order.

        Args:
            order: Order to set up OCO relationship for
            oco: OCO order reference (None for new OCO group)
        """
        oref = order.ref
        if oco is None:
            self._ocos[oref] = oref  # current order is parent
            self._ocol[oref].append(oref)  # create ocogroup
        else:
            ocoref = self._ocos[oco.ref]  # ref to group leader
            self._ocos[oref] = ocoref  # ref to group leader
            self._ocol[ocoref].append(oref)  # add to group

    def add_order_history(self, orders, notify=True):
        """Add historical orders to the broker.

        Args:
            orders: Iterable of historical orders to add
            notify: If True, send notifications for these orders
        """
        oiter = iter(orders)
        o = next(oiter, None)
        self._userhist.append([o, oiter, notify])

    def set_fund_history(self, fund):
        """Set fund history for fund-like performance tracking.

        Args:
            fund: Iterable of [datetime, share_value, net_asset_value] items
        """
        # iterable with the following pro item
        # [datetime, share_value, net asset value]
        fiter = iter(fund)
        f = list(next(fiter))  # must not be empty
        self._fundhist = [f, fiter]
        # self._fhistlast = f[1:]

        self.set_cash(float(f[2]))

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
        parent=None,
        transmit=True,
        histnotify=False,
        _checksubmit=True,
        **kwargs,
    ):
        """Create and submit a buy order.

        Args:
            owner: Strategy or object creating the order
            data: Data feed for the order
            size: Order size (positive for buy)
            price: Order price (for limit/stop orders)
            plimit: Limit price for stop-limit orders
            exectype: Order execution type
            valid: Order validity
            tradeid: Trade identifier
            oco: OCO (One-Cancels-Other) order reference
            trailamount: Trailing stop amount
            trailpercent: Trailing stop percentage
            parent: Parent order (for bracket orders)
            transmit: If True, transmit order immediately
            histnotify: If True, notify for historical orders
            _checksubmit: If True, validate order before submission
            **kwargs: Additional order parameters

        Returns:
            Order: The submitted buy order
        """
        order = BuyOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            histnotify=histnotify,
        )

        order.addinfo(**kwargs)
        self._ocoize(order, oco)

        return self.submit(order, check=_checksubmit)

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
        parent=None,
        transmit=True,
        histnotify=False,
        _checksubmit=True,
        **kwargs,
    ):
        """Create and submit a sell order.

        Args:
            owner: Strategy or object creating the order
            data: Data feed for the order
            size: Order size (positive for sell)
            price: Order price (for limit/stop orders)
            plimit: Limit price for stop-limit orders
            exectype: Order execution type
            valid: Order validity
            tradeid: Trade identifier
            oco: OCO (One-Cancels-Other) order reference
            trailamount: Trailing stop amount
            trailpercent: Trailing stop percentage
            parent: Parent order (for bracket orders)
            transmit: If True, transmit order immediately
            histnotify: If True, notify for historical orders
            _checksubmit: If True, validate order before submission
            **kwargs: Additional order parameters

        Returns:
            Order: The submitted sell order
        """
        order = SellOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            histnotify=histnotify,
        )

        order.addinfo(**kwargs)
        self._ocoize(order, oco)

        return self.submit(order, check=_checksubmit)

    # Execute order
    def _execute(self, order, ago=None, price=None, cash=None, position=None, dtcoc=None):
        # ago = None is used a flag for pseudo execution
        # # print(f"Order size:{order.executed.remsize}")  # Removed for performance
        # If ago is not None and price is None, do nothing and return
        if ago is not None and price is None:
            return  # no psuedo exec no price - no execution

        # Get the order size to execute
        if self.get_param("filler") is None or ago is None:
            # Order gets full size or pseudo-execution
            size = order.executed.remsize
        else:
            # Execution depends on volume filler
            size = self.get_param("filler")(order, price, ago)
            if not order.isbuy():
                size = -size

        # Get comminfo object for the data
        # Get commission info class
        comminfo = self.getcommissioninfo(order.data)

        # Check if something has to be compensated
        # If data's _compensate is not None, get _compensate's commission info class, otherwise use data's
        if order.data._compensate is not None:
            data = order.data._compensate
            cinfocomp = self.getcommissioninfo(data)  # for actual commission
        else:
            data = order.data
            cinfocomp = comminfo

        # Adjust position with operation size
        # If ago is not None, get position, position average price, update position related info, and calculate pnl and cash
        if ago is not None:
            # Real execution with date
            position = self.positions[data]
            pprice_orig = position.price

            psize, pprice, opened, closed = position.pseudoupdate(size, price)

            # if part/all of a position has been closed, then there has been
            # a profitandloss ... record it
            pnl = comminfo.profitandloss(-closed, pprice_orig, price)
            cash = self._cash
        # If ago is None
        else:
            # pnl = 0
            pnl = 0
            # If cheat_on_open is False
            if not self.get_param("coo"):
                # Price
                price = pprice_orig = order.created.price
            # If cheat_on_open = True
            else:
                # When doing cheat on open, the price to be considered for a
                # market order is the opening price and not the default closing
                # price with which the order was created
                # If it's a market order, price equals the day's opening price, otherwise equals the created price
                if order.exectype == Order.Market:
                    price = pprice_orig = order.data.open[0]
                else:
                    price = pprice_orig = order.created.price
            # Update position size and price
            psize, pprice, opened, closed = position.update(size, price)

        # "Closing" totally or partially is possible. Cash may be re-injected
        # If closed
        if closed:
            # Adjust to returned value for closed items & acquired opened items
            # If shortcash is True, closing value is calculated using comminfo.getvaluesize,
            # If shortcash is False, closing value is calculated using comminfo.getoperationcost
            if self.get_param("shortcash"):
                closedvalue = comminfo.getvaluesize(-closed, pprice_orig)
            else:
                closedvalue = comminfo.getoperationcost(closed, pprice_orig)

            # If closedvalue > 0, calculate closecash after adjusting for leverage
            closecash = closedvalue
            if closedvalue > 0:  # long position closed
                closecash /= comminfo.get_leverage()  # inc cash with lever
            # If stocklike, cash equals cash plus closecash plus pnl
            # If stocklike is False, cash equals cash + closecash
            cash += closecash + pnl * comminfo.stocklike
            # Calculate and subtract commission
            # Commission when closing position
            closedcomm = comminfo.getcommission(closed, price)
            # Cash equals cash minus closing commission
            cash -= closedcomm
            # If ago is not None
            if ago is not None:
                # Cashadjust closed contracts: prev close vs exec price
                # The operation can inject or take cash out
                # Adjust cash and update
                cash += comminfo.cashadjust(-closed, position.adjbase, price)

                # Update system cash
                self._cash = cash
        # If not closed
        else:
            closedvalue = closedcomm = 0.0

        # If opened
        popened = opened
        if opened:
            # Calculate opening value
            if self.get_param("shortcash"):
                # # print(f"opened:{opened},price:{price}")  # Removed for performance
                openedvalue = comminfo.getvaluesize(opened, price)
            else:
                openedvalue = comminfo.getoperationcost(opened, price)

            # Calculate cash used for opening
            opencash = openedvalue
            if openedvalue > 0:  # long position being opened
                opencash /= comminfo.get_leverage()  # dec cash with level
            # # print(f"openedvalue:{openedvalue},opencash:{opencash},cash:{cash}")  # Removed for performance
            # Subtract cash obtained after opening
            cash -= opencash  # original behavior
            # Commission for opening
            openedcomm = cinfocomp.getcommission(opened, price)
            # Cash obtained after subtracting opening commission
            cash -= openedcomm
            # If cash is less than 0, opening position is not possible
            if cash < 0.0:
                # execution is not possible - nullify
                opened = 0
                openedvalue = openedcomm = 0.0

            # If ago is not None
            elif ago is not None:  # real execution
                # If absolute position size is greater than absolute opening size
                if abs(psize) > abs(opened):
                    # some futures were opened - adjust the cash of the
                    # previously existing futures to the operation price and
                    # use that as new adjustment base, because it already is
                    # for the new futures At the end of the cycle the
                    # adjustment to the close price will be done for all open
                    # futures from a common base price with regard to the
                    # close price
                    # Size to adjust
                    adjsize = psize - opened
                    # Adjust cash
                    cash += comminfo.cashadjust(adjsize, position.adjbase, price)

                # record adjust price base for end of bar cash adjustment
                # Update position adjbase price
                position.adjbase = price

                # update system cash - checking if opened is still != 0
                self._cash = cash
        # If opened is False
        else:
            openedvalue = openedcomm = 0.0

        # If ago equals None, return cash
        if ago is None:
            # return cash from pseudo-execution
            return cash
        # Order execution size
        execsize = closed + opened
        # If order execution size is greater than 0
        if execsize:
            # Confimrm the operation to the comminfo object
            # TODO Confirm required commission, this doesn't accept return value with any variable, seems useless
            comminfo.confirmexec(execsize, price)

            # do a real position update if something was executed
            # Update position
            position.update(execsize, price, data.datetime.datetime())
            # If closed and transferring interest to pnl, closing commission includes interest charges
            if closed and self.get_param("int2pnl"):  # Assign accumulated interest data
                closedcomm += self.d_credit.pop(data, 0.0)

            # Execute and notify the order
            # Execute order and notify order
            order.execute(
                dtcoc or data.datetime[ago],
                execsize,
                price,
                closed,
                closedvalue,
                closedcomm,
                opened,
                openedvalue,
                openedcomm,
                comminfo.margin,
                pnl,
                psize,
                pprice,
            )

            order.addcomminfo(comminfo)

            self.notify(order)
            self._ococheck(order)

        # If opened but insufficient cash, will indicate margin
        if popened and not opened:
            # opened was not executed - not enough cash
            order.margin()
            self.notify(order)
            self._ococheck(order)
            self._bracketize(order, cancel=True)

    def notify(self, order):
        """Add an order notification to the notification queue.

        Args:
            order: Order to create notification for
        """
        self.notifs.append(order.clone())

    # Try to execute historical
    def _try_exec_historical(self, order):
        self._execute(order, ago=0, price=order.created.price)

    # Try to execute market order
    def _try_exec_market(self, order, popen, phigh, plow):
        # ago = 0
        # TODO Commented out unused ago
        # If cheat_on_close is True or cheat_on_open in order is True
        if self.get_param("coc") and order.info.get("coc", True):
            # Order creation time
            dtcoc = order.created.dt
            # Execution price
            exprice = order.created.pclose
        # If coc is not True
        else:
            # If current is not cheat_on_open, and data time is less than or equal to creation time, return without executing
            if not self.get_param("coo") and order.data.datetime[0] <= order.created.dt:
                return  # can only execute after creation time
            # Set dtcoc to None
            dtcoc = None
            # Execution price equals popen
            exprice = popen
        # For buy and sell orders, get prices after considering slippage respectively
        if order.isbuy():
            p = self._slip_up(phigh, exprice, doslip=self.get_param("slip_open"))
        else:
            p = self._slip_down(plow, exprice, doslip=self.get_param("slip_open"))
        # Execute order
        self._execute(order, ago=0, price=p, dtcoc=dtcoc)

    # Try to execute close order
    def _try_exec_close(self, order, pclose):
        # pannotated allows to keep track of the closing bar if there is no
        # information which lets us know that the current bar is the closing
        # bar (like matching end of session bar)
        # The actual matching will be done one bar afterwards but using the
        # information from the actual closing bar
        # Get current time
        dt0 = order.data.datetime[0]
        # don't use "len" -> in replay the close can be reached with same len
        # If current time is greater than order creation time
        if dt0 > order.created.dt:  # can only execute after creation time
            # or (self.get_param('eosbar') and dt0 == order.dteos):
            # If current time is greater than or equal to order's end of day time
            if dt0 >= order.dteos:
                # past the end of session or right at it and eosbar is True
                # If order.pannotated is a price and dt0 is greater than end of day time, set ago to -1, execution price equals previous close price
                if order.pannotated and dt0 > order.dteos:
                    ago = -1
                    execprice = order.pannotated
                # Otherwise, ago equals 0, execution price equals pclose
                else:
                    ago = 0
                    execprice = pclose
                # Execute order
                self._execute(order, ago=ago, price=execprice)
                return

        # If no execution has taken place ... annotate the closing price
        # If dt0 is less than or equal to order creation time, update order's pannotated to price
        order.pannotated = pclose

    # Try to execute limit order
    def _try_exec_limit(self, order, popen, phigh, plow, plimit):
        # If buy order
        if order.isbuy():
            # If plimit is greater than or equal to popen
            if plimit >= popen:
                # open smaller/equal than requested - buy cheaper
                # Calculate pmax
                pmax = min(phigh, plimit)
                # Calculate price after adding slippage
                p = self._slip_up(pmax, popen, doslip=self.get_param("slip_open"), lim=True)
                # Execute order
                self._execute(order, ago=0, price=p)
            # If plimit is greater than or equal to plow, execute order
            elif plimit >= plow:
                # day low below req price ... match limit price
                self._execute(order, ago=0, price=plimit)
        # Sell order
        else:  # Sell
            # plimit is less than or equal to popen
            if plimit <= popen:
                # open greater/equal than requested - sell more expensive
                # Calculate pmin
                # # TODO Commented out unused pmin
                # pmin = max(plow, plimit)
                # Calculate price after adding slippage
                p = self._slip_down(plimit, popen, doslip=self.get_param("slip_open"), lim=True)
                # Execute order
                self._execute(order, ago=0, price=p)
            # If plimit is less than or equal to high price, execute order
            elif plimit <= phigh:
                # day high above req price ... match limit price
                self._execute(order, ago=0, price=plimit)

    # Try to execute stop price
    def _try_exec_stop(self, order, popen, phigh, plow, pcreated, pclose):
        # Buy order
        if order.isbuy():
            # popen is greater than or equal to pcreated
            if popen >= pcreated:
                # price penetrated with an open gap - use open
                # Calculate price considering slippage
                p = self._slip_up(phigh, popen, doslip=self.get_param("slip_open"))
                # Execute order
                self._execute(order, ago=0, price=p)
            # If phigh is less than or equal to pcreated
            elif phigh >= pcreated:
                # price penetrated during the session - use trigger price
                # Calculate price considering slippage
                p = self._slip_up(phigh, pcreated)
                # Execute order
                self._execute(order, ago=0, price=p)
        # Sell order
        else:  # Sell
            # If popen is less than pcreated
            if popen <= pcreated:
                # price penetrated with an open gap - use open
                # Calculate price considering slippage
                p = self._slip_down(plow, popen, doslip=self.get_param("slip_open"))
                # Execute order
                self._execute(order, ago=0, price=p)
            # If plow is less than or equal to pcreated
            elif plow <= pcreated:
                # price penetrated during the session - use trigger price
                # Calculate price considering slippage
                p = self._slip_down(plow, pcreated)
                # Execute order
                self._execute(order, ago=0, price=p)

        # not (completely) executed and trailing stop
        #  If order is alive and order type is StopTrail, adjust price based on pclose
        if order.alive() and order.exectype == Order.StopTrail:
            order.trailadjust(pclose)

    # Try to execute stop-limit order
    def _try_exec_stoplimit(self, order, popen, phigh, plow, pclose, pcreated, plimit):
        # Similar to stop orders, except stop orders place market orders when stop is triggered, while this places limit orders
        if order.isbuy():
            if popen >= pcreated:
                order.triggered = True
                self._try_exec_limit(order, popen, phigh, plow, plimit)

            elif phigh >= pcreated:
                # price penetrated upwards during the session
                order.triggered = True
                # can calculate execution for a few cases - datetime is fixed
                if popen > pclose:
                    if plimit >= pcreated:  # limit above stop trigger
                        p = self._slip_up(phigh, pcreated, lim=True)
                        self._execute(order, ago=0, price=p)
                    elif plimit >= pclose:
                        self._execute(order, ago=0, price=plimit)
                else:  # popen < pclose
                    if plimit >= pcreated:
                        p = self._slip_up(phigh, pcreated, lim=True)
                        self._execute(order, ago=0, price=p)
        else:  # Sell
            if popen <= pcreated:
                # price penetrated downwards with an open gap
                order.triggered = True
                self._try_exec_limit(order, popen, phigh, plow, plimit)

            elif plow <= pcreated:
                # price penetrated downwards during the session
                order.triggered = True
                # can calculate execution for a few cases - datetime is fixed
                if popen <= pclose:
                    if plimit <= pcreated:
                        p = self._slip_down(plow, pcreated, lim=True)
                        self._execute(order, ago=0, price=p)
                    elif plimit <= pclose:
                        self._execute(order, ago=0, price=plimit)
                else:
                    # popen > pclose
                    if plimit <= pcreated:
                        p = self._slip_down(plow, pcreated, lim=True)
                        self._execute(order, ago=0, price=p)

        # not (completely) executed and trailing stop
        if order.alive() and order.exectype == Order.StopTrailLimit:
            order.trailadjust(pclose)

    # Add upward slippage
    def _slip_up(self, pmax, price, doslip=True, lim=False):
        if not doslip:
            return price

        slip_perc = self.get_param("slip_perc")
        slip_fixed = self.get_param("slip_fixed")
        if slip_perc:
            pslip = price * (1 + slip_perc)
        elif slip_fixed:
            pslip = price + slip_fixed
        else:
            return price

        if pslip <= pmax:  # slipping can return price
            return pslip
        elif self.get_param("slip_match") or (lim and self.get_param("slip_limit")):
            if not self.get_param("slip_out"):
                return pmax

            return pslip  # non existent price

        return None  # no price can be returned

    # Add downward slippage
    def _slip_down(self, pmin, price, doslip=True, lim=False):
        if not doslip:
            return price

        slip_perc = self.get_param("slip_perc")
        slip_fixed = self.get_param("slip_fixed")
        if slip_perc:
            pslip = price * (1 - slip_perc)
        elif slip_fixed:
            pslip = price - slip_fixed
        else:
            return price

        if pslip >= pmin:  # slipping can return price
            return pslip
        elif self.get_param("slip_match") or (lim and self.get_param("slip_limit")):
            if not self.get_param("slip_out"):
                return pmin

            return pslip  # non existent price

        return None  # no price can be returned

    # Try to execute order
    def _try_exec(self, order):
        # Data that generated the order
        data = order.data
        # Get open, high, low, close prices respectively, use tick data if available
        popen = getattr(data, "tick_open", None)
        if popen is None:
            popen = data.open[0]
        phigh = getattr(data, "tick_high", None)
        if phigh is None:
            phigh = data.high[0]
        plow = getattr(data, "tick_low", None)
        if plow is None:
            plow = data.low[0]
        pclose = getattr(data, "tick_close", None)
        if pclose is None:
            pclose = data.close[0]

        pcreated = order.created.price
        plimit = order.created.pricelimit

        # Execute separately according to different order types
        if order.exectype == Order.Market:
            self._try_exec_market(order, popen, phigh, plow)

        elif order.exectype == Order.Close:
            self._try_exec_close(order, pclose)

        elif order.exectype == Order.Limit:
            self._try_exec_limit(order, popen, phigh, plow, pcreated)

        elif order.triggered and order.exectype in [Order.StopLimit, Order.StopTrailLimit]:
            self._try_exec_limit(order, popen, phigh, plow, plimit)

        elif order.exectype in [Order.Stop, Order.StopTrail]:
            self._try_exec_stop(order, popen, phigh, plow, pcreated, pclose)

        elif order.exectype in [Order.StopLimit, Order.StopTrailLimit]:
            self._try_exec_stoplimit(order, popen, phigh, plow, pclose, pcreated, plimit)

        elif order.exectype == Order.Historical:
            self._try_exec_historical(order)

    # Process fund history
    def _process_fund_history(self):
        fhist = self._fundhist  # [last element, iterator]
        f, funds = fhist
        if not f:
            return self._fhistlast

        dt = f[0]  # date/datetime instance
        if isinstance(dt, string_types):
            dtfmt = "%Y-%m-%d"
            if "T" in dt:
                dtfmt += "T%H:%M:%S"
                if "." in dt:
                    dtfmt += ".%f"
            dt = datetime.datetime.strptime(dt, dtfmt)
            f[0] = dt  # update value

        elif isinstance(dt, datetime.datetime):
            pass
        elif isinstance(dt, datetime.date):
            dt = datetime.datetime(year=dt.year, month=dt.month, day=dt.day)
            f[0] = dt  # Update the value

        # Synchronization with the strategy is not possible because the broker
        # is called before the strategy advances. The 2 lines below would do it
        # if possible
        # st0 = self.cerebro.runningstrats[0]
        # if dt <= st0.datetime.datetime():
        if dt <= self.cerebro._dtmaster:
            self._fhistlast = f[1:]
            fhist[0] = list(next(funds, []))

        return self._fhistlast

    # Process order history
    def _process_order_history(self):
        for uhist in self._userhist:
            uhorder, uhorders, uhnotify = uhist
            while uhorder is not None:
                uhorder = list(uhorder)  # to support assignment (if tuple)
                try:
                    dataidx = uhorder[3]  # 2nd field
                except IndexError:
                    dataidx = None  # Field not present, use default

                if dataidx is None:
                    d = self.cerebro.datas[0]
                elif isinstance(dataidx, integer_types):
                    d = self.cerebro.datas[dataidx]
                else:  # assume string
                    d = self.cerebro.datasbyname[dataidx]

                if not len(d):
                    break  # may start later than other data feeds

                dt = uhorder[0]  # date/datetime instance
                if isinstance(dt, string_types):
                    dtfmt = "%Y-%m-%d"
                    if "T" in dt:
                        dtfmt += "T%H:%M:%S"
                        if "." in dt:
                            dtfmt += ".%f"
                    dt = datetime.datetime.strptime(dt, dtfmt)
                    uhorder[0] = dt
                elif isinstance(dt, datetime.datetime):
                    pass
                elif isinstance(dt, datetime.date):
                    dt = datetime.datetime(year=dt.year, month=dt.month, day=dt.day)
                    uhorder[0] = dt

                if dt > d.datetime.datetime():
                    break  # cannot execute yet 1st in queue, stop processing

                size = uhorder[1]
                price = uhorder[2]
                owner = self.cerebro.runningstrats[0]
                if size > 0:
                    self.buy(
                        owner=owner,
                        data=d,
                        size=size,
                        price=price,
                        exectype=Order.Historical,
                        histnotify=uhnotify,
                        _checksubmit=False,
                    )

                elif size < 0:
                    self.sell(
                        owner=owner,
                        data=d,
                        size=abs(size),
                        price=price,
                        exectype=Order.Historical,
                        histnotify=uhnotify,
                        _checksubmit=False,
                    )

                # update to next potential order
                uhist[0] = uhorder = next(uhorders, None)

    def next(self):
        """Process broker operations for the current time step.

        This method:
        - Activates pending orders
        - Validates submitted orders
        - Calculates interest charges
        - Processes order history
        - Executes pending orders
        - Adjusts cash for mark-to-market
        """
        positions = self.positions
        getcommissioninfo = self.getcommissioninfo
        d_credit = self.d_credit
        pending = self.pending
        notify = self.notify
        ococheck = self._ococheck
        bracketize = self._bracketize
        try_exec = self._try_exec

        toactivate = self._toactivate
        while toactivate:
            toactivate.popleft().activate()

        checksubmit = self.get_param("checksubmit")
        if checksubmit:
            self.check_submitted()

        # Discount any cash for positions hold
        # Interest charges
        credit = 0.0
        for data, pos in positions.items():
            if pos:
                comminfo = getcommissioninfo(data)
                dt0 = data.datetime.datetime()
                dcredit = comminfo.get_credit_interest(data, pos, dt0)
                d_credit[data] += dcredit
                credit += dcredit
                pos.datetime = dt0  # mark last credit operation

        self._cash -= credit
        # Process order history
        self._process_order_history()

        # Iterate once over all elements of the pending queue
        # Add a None to pending orders
        pending.append(None)
        # Loop through pending orders once, break when reaching None
        while True:
            order = pending.popleft()
            if order is None:
                break

            if order.expire():
                notify(order)
                ococheck(order)
                bracketize(order, cancel=True)

            elif not order.active():
                pending.append(order)  # cannot yet be processed

            else:
                try_exec(order)
                if order.alive():
                    pending.append(order)

                elif order.status == Order.Completed:
                    # a bracket parent order may have been executed
                    bracketize(order)

        # Operations have been executed ... adjust cash end of bar
        # At the end of bar, adjust cash based on position info
        cash = self._cash
        for data, pos in positions.items():
            # futures change cash every bar
            if pos:
                comminfo = getcommissioninfo(data)
                close0 = data.close[0]
                cash += comminfo.cashadjust(pos.size, pos.adjbase, close0)
                # record the last adjustment price
                pos.adjbase = close0

        self._cash = cash

        self._get_value()  # update value


# Alias
BrokerBack = BackBroker
