#!/usr/bin/env python
from .comminfo import CommInfoBase
from .parameters import ParameterDescriptor, ParameterizedBase

# from . import fillers as fillers
# from . import fillers as filler


# Create a mixin to handle aliases without using metaclasses
class BrokerAliasMixin:
    """Mixin to provide method aliases without using metaclasses"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Create aliases if they don't exist
        if not hasattr(self, "get_cash"):
            self.get_cash = self.getcash
        if not hasattr(self, "get_value"):
            self.get_value = self.getvalue


# broker base class - using new parameter system
class BrokerBase(BrokerAliasMixin, ParameterizedBase):
    # Use new parameter descriptor
    commission = ParameterDescriptor(
        default=CommInfoBase(percabs=True), doc="Default commission scheme for all assets"
    )

    # Initialize
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.comminfo = dict()
        self.init()

    # This init uses None as key, commission as value
    def init(self):
        # called from init and from start
        if None not in self.comminfo:
            self.comminfo = dict({None: self.get_param("commission")})

    # Start
    def start(self):
        self.init()

    # Stop
    def stop(self):
        pass

    # Add order history
    def add_order_history(self, orders, notify=False):
        # Add order history. See cerebro for details
        raise NotImplementedError

    # Set fund history
    def set_fund_history(self, fund):
        # Add fund history. See cerebro for details
        raise NotImplementedError

    # Get commission info, if data._name is in commission info dict, get corresponding value, otherwise use default self.p.commission
    def getcommissioninfo(self, data):
        # Retrieves the ``CommissionInfo`` scheme associated with the given ``data``
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
        # Adds a ``CommissionInfo`` object that will be the default for all assets if ``name`` is ``None``
        self.comminfo[name] = comminfo

    # Get cash
    def getcash(self):
        raise NotImplementedError

    # Get value
    def getvalue(self, datas=None):
        raise NotImplementedError

    # Get fund shares
    def get_fundshares(self):
        # Returns the current number of shares in the fund-like mode
        return 1.0  # the abstract mode has only 1 share

    fundshares = property(get_fundshares)

    # Get fund value
    def get_fundvalue(self):
        return self.getvalue()

    fundvalue = property(get_fundvalue)

    # Set fund mode
    def set_fundmode(self, fundmode, fundstartval=None):
        """Set the actual fundmode (True or False)

        If the argument fundstartval is not `None`, it will use
        """
        pass  # do nothing, not all brokers can support this

    # Get fund mode
    def get_fundmode(self):
        # Returns the actual fundmode (True or False)
        return False

    fundmode = property(get_fundmode, set_fundmode)

    # Get position
    def getposition(self, data):
        raise NotImplementedError

    # Submit
    def submit(self, order):
        raise NotImplementedError

    # Cancel
    def cancel(self, order):
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
        raise NotImplementedError

    # Next bar
    def next(self):
        pass


# __all__ = ['BrokerBase', 'fillers', 'filler']
