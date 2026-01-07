#!/usr/bin/env python
"""
Refactored CommInfo system (Day 44)

Migrated CommInfo system from MetaParams to new ParameterizedBase system.
Maintains fully backward compatible API interface.
"""

from .parameters import BoolParam, Float, ParameterDescriptor, ParameterizedBase


class CommInfoBase(ParameterizedBase):
    """Base Class for the Commission Schemes.

    Migrated from MetaParams to ParameterizedBase system for better
    parameter management and validation.

    Params:
      - commission (def: 0.0): base commission value in percentage or monetary units
      - mult (def 1.0): multiplier applied to the asset for value/profit
      - margin (def: None): amount of monetary units needed to open/hold an operation
      - automargin (def: False): Used by get_margin to automatically calculate margin
      - commtype (def: None): Commission type (COMM_PERC/COMM_FIXED)
      - stocklike (def: False): Indicates if the instrument is Stock-like or Futures-like
      - percabs (def: False): whether commission is XX% or 0.XX when commtype is COMM_PERC
      - interest (def: 0.0): yearly interest charged for holding short selling position
      - interest_long (def: False): whether to charge interest on long positions
      - leverage (def: 1.0): amount of leverage for the asset
    """

    # Commission type constants
    COMM_PERC, COMM_FIXED = 0, 1

    # Parameter descriptor definitions
    commission = ParameterDescriptor(
        default=0.0,
        type_=float,
        validator=Float(min_val=0.0),  # Non-negative validation
        doc="Base commission, percentage or monetary units",
    )

    mult = ParameterDescriptor(
        default=1.0,
        type_=float,
        validator=Float(min_val=0.001),
        doc="Asset multiplier",  # Must be positive
    )

    margin = ParameterDescriptor(default=None, doc="Margin amount")

    commtype = ParameterDescriptor(
        default=None, type_=(int, type(None)), doc="Commission type (COMM_PERC/COMM_FIXED)"
    )

    stocklike = BoolParam(default=False, doc="Whether stock type")

    percabs = BoolParam(default=False, doc="Whether percentage is absolute value")

    interest = ParameterDescriptor(
        default=0.0,
        type_=float,
        validator=Float(min_val=0.0),
        doc="Annual interest rate",  # Non-negative validation
    )

    interest_long = BoolParam(default=False, doc="Whether to charge interest on long positions")

    leverage = ParameterDescriptor(
        default=1.0,
        type_=float,
        validator=Float(min_val=0.001),
        doc="Leverage level",  # Must be positive
    )

    automargin = ParameterDescriptor(default=False, type_=(bool, float), doc="Automatic margin calculation")

    def __init__(self, **kwargs):
        """Initialize CommInfo object"""
        super().__init__()

        # Special handling for margin parameter None value validation
        if "margin" in kwargs:
            margin_value = kwargs["margin"]
            if margin_value is not None and margin_value < 0.0:
                raise ValueError(f"margin must be non-negative, got {margin_value}")

        # Set passed parameters
        for name, value in kwargs.items():
            if name in self._param_manager._descriptors:
                # Skip margin standard validation, already handled above
                if name == "margin":
                    self._param_manager.set(name, value, skip_validation=True)
                else:
                    self.set_param(name, value)

        # Execute parameter post-processing and compatibility settings
        self._post_init_setup()

    def _post_init_setup(self):
        """Parameter post-processing and internal state setup"""
        # Get initial values from parameters
        self._stocklike = self.get_param("stocklike")
        self._commtype = self.get_param("commtype")

        # Compatibility logic: if commtype is None, set type based on margin (consistent with original implementation)
        if self._commtype is None:
            if self.get_param("margin"):
                self._stocklike = False
                self._commtype = self.COMM_FIXED
            else:
                self._stocklike = True
                self._commtype = self.COMM_PERC

        # Parameter post-processing (consistent with original implementation)
        if not self._stocklike and not self.get_param("margin"):
            # Directly modify value in parameter manager to avoid validation issues
            self._param_manager.set("margin", 1.0, skip_validation=True)

        # Handle percentage commission conversion (important! consistent with original implementation)
        if self._commtype == self.COMM_PERC and not self.get_param("percabs"):
            current_commission = self.get_param("commission")
            # Directly modify parameter value to avoid duplicate conversion
            self._param_manager.set("commission", current_commission / 100.0, skip_validation=True)

        # Calculate interest rate
        self._creditrate = self.get_param("interest") / 365.0

    def __getattribute__(self, name):
        """Override attribute access to return processed values for stocklike"""
        if name == "stocklike":
            try:
                return self._stocklike
            except AttributeError:
                # Fall back to parameter value if _stocklike not yet set
                return super().__getattribute__(name)
        return super().__getattribute__(name)

    def get_margin(self, price):
        """Returns the actual margin/guarantees needed for a single item of the
        asset at the given price. The default implementation has this policy:

          - Use param ``margin`` if param ``automargin`` evaluates to ``False``
          - Use param ``mult`` * ``price`` if ``automargin < 0``
          - Use param ``automargin`` * ``price`` if ``automargin > 0``
        """
        automargin = self.get_param("automargin")
        if not automargin:
            return self.get_param("margin")
        elif automargin < 0:
            return price * self.get_param("mult")
        return price * automargin

    def get_leverage(self):
        """Returns the level of leverage allowed for this commission scheme"""
        return self.get_param("leverage")

    def getsize(self, price, cash):
        """Returns the needed size to meet a cash operation at a given price"""
        leverage = self.get_param("leverage")
        if not self._stocklike:
            return leverage * (cash // self.get_margin(price))
        return leverage * (cash // price)

    def getoperationcost(self, size, price):
        """Returns the needed amount of cash an operation would cost"""
        if not self._stocklike:
            return abs(size) * self.get_margin(price)
        return abs(size) * price

    def getvaluesize(self, size, price):
        """Returns the value of size for given a price. For future-like
        objects it is fixed at size * margin"""
        if not self._stocklike:
            return abs(size) * self.get_margin(price)
        return size * price

    def getvalue(self, position, price):
        """Returns the value of a position given a price. For future-like
        objects it is fixed at size * margin"""
        if not self._stocklike:
            return abs(position.size) * self.get_margin(price)

        size = position.size
        if size >= 0:
            return size * price

        # With stocks, a short position is worth more as the price goes down
        value = position.price * size  # original value
        value += (position.price - price) * size  # increased value
        return value

    def _getcommission(self, size, price, pseudoexec):
        """Calculates the commission of an operation at a given price

        pseudoexec: if True the operation has not yet been executed
        """
        commission = self.get_param("commission")
        if self._commtype == self.COMM_PERC:
            return abs(size) * commission * price
        return abs(size) * commission

    def getcommission(self, size, price):
        """Calculates the commission of an operation at a given price"""
        return self._getcommission(size, price, pseudoexec=True)

    def confirmexec(self, size, price):
        """Confirms execution and returns commission"""
        return self._getcommission(size, price, pseudoexec=False)

    def profitandloss(self, size, price, newprice):
        """Return actual profit and loss a position has"""
        mult = self.get_param("mult")
        return size * (newprice - price) * mult

    def cashadjust(self, size, price, newprice):
        """Calculates cash adjustment for a given price difference"""
        if not self._stocklike:
            mult = self.get_param("mult")
            return size * (newprice - price) * mult
        return 0.0

    def get_credit_interest(self, data, pos, dt):
        """Calculates the credit due for short selling or product specific"""
        size, price = pos.size, pos.price

        if size > 0 and not self.get_param("interest_long"):
            return 0.0  # long positions not charged

        dt0 = dt.date()
        dt1 = pos.datetime.date()

        if dt0 <= dt1:
            return 0.0

        return self._get_credit_interest(data, size, price, (dt0 - dt1).days, dt0, dt1)

    def _get_credit_interest(self, data, size, price, days, dt0, dt1):
        """
        This method returns the cost in terms of credit interest charged by
        the broker.

        The formula: ``days * price * abs(size) * (interest / 365)``
        """
        return days * self._creditrate * abs(size) * price


class CommissionInfo(CommInfoBase):
    """Base Class for the actual Commission Schemes.

    CommInfoBase was created to keep support for the original, incomplete,
    support provided by *backtrader*. New commission schemes derive from this
    class which subclasses ``CommInfoBase``.

    The default value of ``percabs`` is also changed to ``True``
    """

    percabs = BoolParam(default=True, doc="Whether percentage is absolute value")


class ComminfoDC(CommInfoBase):
    """Digital currency commission class"""

    stocklike = ParameterDescriptor(default=False, type_=bool)
    commtype = ParameterDescriptor(default=CommInfoBase.COMM_PERC, type_=int)
    percabs = ParameterDescriptor(default=True, type_=bool)
    interest = ParameterDescriptor(default=3.0, type_=float)

    def _getcommission(self, size, price, pseudoexec):
        commission = self.get_param("commission")
        mult = self.get_param("mult")
        return abs(size) * price * mult * commission

    def get_margin(self, price):
        """Calculate the margin required for digital currency trading.

        Args:
            price: Current price of the asset.

        Returns:
            float: Margin calculated as price * mult * margin parameter.
        """
        mult = self.get_param("mult")
        margin = self.get_param("margin")
        return price * mult * margin

    def get_credit_interest(self, data, pos, dt):
        """Simplified implementation for digital currency interest calculation"""
        size, price = pos.size, pos.price
        dt0 = dt
        dt1 = pos.datetime
        gap_seconds = (dt0 - dt1).seconds
        days = gap_seconds / (24 * 60 * 60)

        mult = self.get_param("mult")
        position_value = size * price * mult

        # Simplified interest calculation logic
        total_value = self.broker.getvalue() if hasattr(self, "broker") else abs(position_value)
        if size > 0 and position_value > total_value:
            return days * self._creditrate * (position_value - total_value)
        elif size > 0 and position_value <= total_value:
            return 0
        elif size < 0:
            return days * self._creditrate * position_value
        return 0


class ComminfoFuturesPercent(CommInfoBase):
    """Futures percentage commission class"""

    commission = ParameterDescriptor(default=0.0, type_=float)
    mult = ParameterDescriptor(default=1.0, type_=float)
    margin = ParameterDescriptor(default=None)
    stocklike = ParameterDescriptor(default=False, type_=bool)
    commtype = ParameterDescriptor(default=CommInfoBase.COMM_PERC, type_=int)
    percabs = ParameterDescriptor(default=True, type_=bool)

    def _getcommission(self, size, price, pseudoexec):
        commission = self.get_param("commission")
        mult = self.get_param("mult")
        return abs(size) * price * mult * commission

    def get_margin(self, price):
        """Calculate the margin required for futures percentage commission.

        Args:
            price: Current price of the asset.

        Returns:
            float: Margin calculated as price * mult * margin parameter.
        """
        mult = self.get_param("mult")
        margin = self.get_param("margin")
        return price * mult * margin


class ComminfoFuturesFixed(CommInfoBase):
    """Futures fixed commission class"""

    commission = ParameterDescriptor(default=0.0, type_=float)
    mult = ParameterDescriptor(default=1.0, type_=float)
    margin = ParameterDescriptor(default=None)
    stocklike = ParameterDescriptor(default=False, type_=bool)
    commtype = ParameterDescriptor(default=CommInfoBase.COMM_FIXED, type_=int)
    percabs = ParameterDescriptor(default=True, type_=bool)

    def _getcommission(self, size, price, pseudoexec):
        commission = self.get_param("commission")
        return abs(size) * commission

    def get_margin(self, price):
        """Calculate the margin required for futures fixed commission.

        Args:
            price: Current price of the asset.

        Returns:
            float: Margin calculated as price * mult * margin parameter.
        """
        mult = self.get_param("mult")
        margin = self.get_param("margin")
        return price * mult * margin


class ComminfoFundingRate(CommInfoBase):
    """Funding rate class"""

    commission = ParameterDescriptor(default=0.0, type_=float)
    mult = ParameterDescriptor(default=1.0, type_=float)
    margin = ParameterDescriptor(default=None)
    stocklike = ParameterDescriptor(default=False, type_=bool)
    commtype = ParameterDescriptor(default=CommInfoBase.COMM_PERC, type_=int)
    percabs = ParameterDescriptor(default=True, type_=bool)

    def _getcommission(self, size, price, pseudoexec):
        commission = self.get_param("commission")
        mult = self.get_param("mult")
        total_commission = abs(size) * price * mult * commission
        return total_commission

    def get_margin(self, price):
        """Calculate the margin required for funding rate trading.

        Args:
            price: Current price of the asset.

        Returns:
            float: Margin calculated as price * mult * margin parameter.
        """
        mult = self.get_param("mult")
        margin = self.get_param("margin")
        return price * mult * margin

    def get_credit_interest(self, data, pos, dt):
        """Calculate funding rate for Binance futures"""
        size, price = pos.size, pos.price

        # Calculate current position value
        try:
            current_price = data.mark_price_open[1]
        except (IndexError, AttributeError):
            current_price = getattr(data, "mark_price_close", [price])[0]

        mult = self.get_param("mult")
        position_value = size * current_price * mult

        # Get current funding rate
        try:
            funding_rate = data.current_funding_rate[1]
        except (IndexError, AttributeError):
            funding_rate = 0.0

        total_funding_rate = funding_rate * position_value
        return total_funding_rate
