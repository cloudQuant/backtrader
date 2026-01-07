#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Backtrader Broker Module.

This module provides the broker system for order execution and portfolio
management. It handles order creation, position tracking, cash management,
and commission calculation.

Key Classes:
    BrokerBase: Base class for broker implementations.
    BrokerAliasMixin: Mixin providing method aliases.

The broker system supports:
    - Order execution (buy, sell, cancel)
    - Position management
    - Cash and value tracking
    - Commission schemes
    - Order history
"""
from .comminfo import CommInfoBase
from .parameters import ParameterDescriptor, ParameterizedBase

# from . import fillers as fillers
# from . import fillers as filler


# Create a mixin to handle aliases without using metaclasses
class BrokerAliasMixin:
    """Mixin to provide method aliases without using metaclasses.

    This mixin creates method aliases for compatibility with different
    naming conventions (e.g., get_cash/getcash, get_value/getvalue).
    """

    def __init__(self, *args, **kwargs):
        """Initialize the broker alias mixin.

        Creates method aliases for compatibility:
            - get_cash -> getcash
            - get_value -> getvalue

        Args:
            *args: Positional arguments passed to parent.
            **kwargs: Keyword arguments passed to parent.
        """
        super().__init__(*args, **kwargs)
        # Create aliases if they don't exist
        if not hasattr(self, "get_cash"):
            self.get_cash = self.getcash
        if not hasattr(self, "get_value"):
            self.get_value = self.getvalue


# broker base class - using new parameter system
class BrokerBase(BrokerAliasMixin, ParameterizedBase):
    """Base class for broker implementations.

    The broker handles order execution, position tracking, and cash management.
    It supports commission schemes, margin requirements, and order history.

    Attributes:
        commission: Default commission scheme for all assets.
        comminfo: Dictionary mapping asset names to commission info objects.

    Params:
        commission: Default commission scheme (CommInfoBase instance).
    """
    # Use new parameter descriptor
    commission = ParameterDescriptor(
        default=CommInfoBase(percabs=True), doc="Default commission scheme for all assets"
    )

    # Initialize
    def __init__(self, **kwargs):
        """Initialize the broker instance.

        Args:
            **kwargs: Keyword arguments passed to parent class.
        """
        super().__init__(**kwargs)
        self.comminfo = dict()
        self.init()

    # This init uses None as key, commission as value
    def init(self):
        """Initialize the commission info dictionary.

        Sets up the default commission scheme if not already present.
        Called from both __init__ and start methods.
        """
        # called from init and from start
        if None not in self.comminfo:
            self.comminfo = dict({None: self.get_param("commission")})

    # Start
    def start(self):
        """Start the broker. Re-initializes commission info."""
        self.init()

    # Stop
    def stop(self):
        """Stop the broker.

        Override this method in subclasses for cleanup operations.
        """
        pass

    # Add order history
    def add_order_history(self, orders, notify=False):
        """Add order history to the broker.

        Args:
            orders: Orders to add to history.
            notify: Whether to notify about these orders.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        # Add order history. See cerebro for details
        raise NotImplementedError

    # Set fund history
    def set_fund_history(self, fund):
        """Set fund history for the broker.

        Args:
            fund: Fund history data.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        # Add fund history. See cerebro for details
        raise NotImplementedError

    # Get commission info, if data._name is in commission info dict, get corresponding value, otherwise use default self.p.commission
    def getcommissioninfo(self, data):
        """Get the commission info for a given data.

        Args:
            data: Data feed to get commission info for.

        Returns:
            CommInfoBase: The commission info for the data, or the default.
        """
        # if data._name in self.comminfo:
        #     return self.comminfo[data._name]
        # todo Avoid accessing protected attribute ._name, when loading data, .name attribute has been added, use .name instead of _name to avoid pycharm warnings
        if hasattr(data, "name") and data.name in self.comminfo:
            return self.comminfo[data.name]

        return self.comminfo[None]

    # Set commission
    def setcommission(
        self,
        commission=0.0,
        margin=None,
        mult=1.0,
        commtype=None,
        percabs=True,
        stocklike=False,
        interest=0.0,
        interest_long=False,
        leverage=1.0,
        automargin=False,
        name=None,
    ):
        """This method sets a `` CommissionInfo`` object for assets managed in
        the broker with the parameters. Consult the reference for
        ``CommInfoBase``

        If name is `None`, this will be the default for assets for which no
        other ``CommissionInfo`` scheme can be found
        """

        comm = CommInfoBase(
            commission=commission,
            margin=margin,
            mult=mult,
            commtype=commtype,
            stocklike=stocklike,
            percabs=percabs,
            interest=interest,
            interest_long=interest_long,
            leverage=leverage,
            automargin=automargin,
        )
        self.comminfo[name] = comm

    # Add commission info
    def addcommissioninfo(self, comminfo, name=None):
        """Add a CommissionInfo object for an asset.

        Args:
            comminfo: The CommissionInfo object to add.
            name: Asset name. If None, sets as default for all assets.
        """
        # Adds a ``CommissionInfo`` object that will be the default for all assets if ``name`` is ``None``
        self.comminfo[name] = comminfo

    # Get cash
    def getcash(self):
        """Get the current available cash.

        Returns:
            float: Current cash amount.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    # Get value
    def getvalue(self, datas=None):
        """Get the current portfolio value.

        Args:
            datas: Data feeds to calculate value for (optional).

        Returns:
            float: Current portfolio value.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    # Get fund shares
    def get_fundshares(self):
        """Get the current number of shares in fund-like mode.

        Returns:
            float: Number of shares (1.0 for abstract mode).
        """
        # Returns the current number of shares in the fund-like mode
        return 1.0  # the abstract mode has only 1 share

    fundshares = property(get_fundshares)

    # Get fund value
    def get_fundvalue(self):
        """Get the current fund value.

        Returns:
            float: Current fund value.
        """
        return self.getvalue()

    fundvalue = property(get_fundvalue)

    # Set fund mode
    def set_fundmode(self, fundmode, fundstartval=None):
        """Set the fund mode for the broker.

        Args:
            fundmode: True to enable fund mode, False otherwise.
            fundstartval: Initial fund value (optional).

        Note:
            Not all brokers support fund mode.
        """
        pass  # do nothing, not all brokers can support this

    # Get fund mode
    def get_fundmode(self):
        """Get the current fund mode status.

        Returns:
            bool: True if fund mode is enabled, False otherwise.
        """
        # Returns the actual fundmode (True or False)
        return False

    fundmode = property(get_fundmode, set_fundmode)

    # Get position
    def getposition(self, data):
        """Get the current position for a data feed.

        Args:
            data: Data feed to get position for.

        Returns:
            Position: Current position for the data feed.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    # Submit
    def submit(self, order):
        """Submit an order to the broker.

        Args:
            order: Order object to submit.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    # Cancel
    def cancel(self, order):
        """Cancel a pending order.

        Args:
            order: Order object to cancel.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    # Buy order
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
            owner: Strategy/owner creating the order.
            data: Data feed for the order.
            size: Size of the order (positive for buy).
            price: Limit price (optional).
            plimit: Profit limit price (optional).
            exectype: Execution type (Market, Limit, Stop, etc.).
            valid: Validity period for the order.
            tradeid: Trade identifier.
            oco: One-cancels-other order reference.
            trailamount: Trailing amount for stop orders.
            trailpercent: Trailing percent for stop orders.
            **kwargs: Additional keyword arguments.

        Returns:
            Order: The created order object.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    # Sell order
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
            owner: Strategy/owner creating the order.
            data: Data feed for the order.
            size: Size of the order (positive for sell).
            price: Limit price (optional).
            plimit: Profit limit price (optional).
            exectype: Execution type (Market, Limit, Stop, etc.).
            valid: Validity period for the order.
            tradeid: Trade identifier.
            oco: One-cancels-other order reference.
            trailamount: Trailing amount for stop orders.
            trailpercent: Trailing percent for stop orders.
            **kwargs: Additional keyword arguments.

        Returns:
            Order: The created order object.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    # Next bar
    def next(self):
        """Process the next bar in the backtest.

        Called by the cerebro engine for each iteration.
        Override in subclasses to perform per-bar operations.
        """
        pass


# __all__ = ['BrokerBase', 'fillers', 'filler']
