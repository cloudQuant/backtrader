#!/usr/bin/env python
"""Trade Module - Position and trade tracking.

This module provides the Trade class for tracking the lifecycle of trades
including size, price, commission, and profit/loss calculations.

Key Classes:
    Trade: Tracks the life of a trade from opening to closing.
    TradeHistory: Records status and event updates for each trade.

A trade starts at 0, can be increased (adding to position) or reduced
(closing part of position), and is considered closed when size returns to 0.
Trades can be long (positive size) or short (negative size).

Example:
    Accessing trade information:
    >>> trade.status  # Created, Open, or Closed
    >>> trade.pnl  # Current profit/loss
    >>> trade.pnlcomm  # PnL minus commission
"""
import itertools

from .utils import AutoOrderedDict
from .utils.date import num2date
from .utils.py3 import range


# Trade history
class TradeHistory(AutoOrderedDict):
    """Represents the status and update event for each update a Trade has

    This object is a dictionary which allows '.' notation
    # This class saves the status and event updates for each trade
    Attributes:
      - ``status`` (``dict`` with '.' notation): Holds the resulting status of
        an update event and has the following sub-attributes
        # Status, dict format, accessible via '.', used to save the status of an update event, with the following sub-attributes
        - ``status`` (``int``): Trade status
            # Trade status, integer format
        - ``dt`` (``float``): float coded datetime
            # Time, string format
        - ``barlen`` (``int``): number of bars the trade has been active
            # Number of bars when trade was generated
        - ``size`` (``int``): current size of the Trade
            # Current size of the trade, in integer format. In actual trading, non-integer trade sizes may be used
        - ``price`` (``float``): current price of the Trade
            # Current price of the trade
        - ``value`` (``float``): current monetary value of the Trade
            # Current monetary value of the trade
        - ``pnl`` (``float``): current profit and loss of the Trade
            # Current profit and loss of the trade
        - ``pnlcomm`` (``float``): current profit and loss minus commission
            # Current net profit and loss of the trade
      - ``event`` (``dict`` with '.' notation): Holds the event update
        - parameters
        # Event attributes, saves event update parameters
        - ``order`` (``object``): the order which initiated the``update``
            # Order that generated the trade
        - ``size`` (``int``): size of the update
            # Size of the update
        - ``price`` (``float``):price of the update
            # Price of the update
        - ``commission`` (``float``): price of the update
            # Commission of the update
    """

    # Initialize
    def __init__(self, status, dt, barlen, size, price, value, pnl, pnlcomm, tz, event=None):
        """Initializes the object to the current status of the Trade"""
        super().__init__()
        self.status.status = status
        self.status.dt = dt
        self.status.barlen = barlen
        self.status.size = size
        self.status.price = price
        self.status.value = value
        self.status.pnl = pnl
        self.status.pnlcomm = pnlcomm
        self.status.tz = tz
        if event is not None:
            self.event = event

    def __reduce__(self):
        return (
            self.__class__,
            (
                self.status.status,
                self.status.dt,
                self.status.barlen,
                self.status.size,
                self.status.price,
                self.status.value,
                self.status.pnl,
                self.status.pnlcomm,
                self.status.tz,
                self.event,
            ),
        )

    # Do event update
    def doupdate(self, order, size, price, commission):
        """Used to fill the ``update`` part of the history entry"""
        self.event.order = order
        self.event.size = size
        self.event.price = price
        self.event.commission = commission

        # Do not allow updates (avoids typing errors)
        self._close()

    def datetime(self, tz=None, naive=True):
        """Returns a datetime for the time the update event happened"""
        return num2date(self.status.dt, tz or self.status.tz, naive)


# Trade class
class Trade:
    """Keeps track the life of an trade: size, price,
    commission (and value?)

    A trade starts at 0 can be increased and reduced and can
    be considered closed if it goes back to 0.

    The trade can be long (positive size) or short (negative size)

    A trade is not meant to be reversed (no support in the logic for it)
    # Track the life of a trade: size, price, commission (and value?)
    # A trade starts at 0, can be increased and reduced, and is considered closed when it returns to 0
    # A trade can be long (positive size) or short (negative size)
    # A trade cannot reverse from long to short or short to long, such logic is not supported

    Member Attributes:

      - ``ref``: unique trade identifier
        # Trade identifier
      - ``status`` (``int``): one of Created, Open, Closed
        # Trade status
      - ``tradeid``: grouping tradeid passed to orders during creation
        The default in orders is 0
        # Trade id passed to orders during creation, default value in orders is 0
      - ``size`` (``int``): current size of the trade
        # Current size of the trade
      - ``price`` (``float``): current price of the trade
        # Current price of the trade
      - ``value`` (``float``): current value of the trade
        # Current market value of the trade
      - ``commission`` (``float``): current accumulated commission
        # Current accumulated commission
      - ``pnl`` (``float``): current profit and loss of the trade (gross pnl)
        # Current profit and loss
      - ``pnlcomm`` (``float``): current profit and loss of the trade minus
        commission (net pnl)
        # Current net profit and loss after deducting commission
      - ``isclosed`` (``bool``): records if the last update closed (set size to
        null the trade
        # Whether the last update event closed this trade, if closed, set size to null
      - ``isopen`` (``bool``): records if any update has opened the trade
        # Whether the trade has been opened
      - ``justopened`` (``bool``): if the trade was just opened
        # Whether the trade was just opened
      - ``baropen`` (``int``): bar in which this trade was opened
        # Record which bar opened the position
      - ``dtopen`` (``float``): float coded datetime in which the trade was
        opened
        # Record the time when the trade was opened, can use open_datetime or num2date to get Python format time
        - Use method ``open_datetime`` to get a Python datetime.datetime
          or use the platform provided ``num2date`` method
      - ``barclose`` (``int``): bar in which this trade was closed
        # Which bar the trade ended on
      - ``dtclose`` (``float``): float coded datetime in which the trade was
        closed
        - Use method ``close_datetime`` to get a Python datetime.datetime
          or use the platform provided ``num2date`` method
        # Record the time when the trade was closed, can use close_datetime or num2date to get Python format time
      - ``barlen`` (``int``): number of bars this trade was open
        # Number of bars when trade was open
      - ``historyon`` (``bool``): whether history has to be recorded
        # Whether to record historical trade update events
      - ``history`` (``list``): holds a list updated with each "update" event
        containing the resulting status and parameters used in the update
        The first entry in the history is the Opening Event
        The last entry in the history is the Closing Event
        # Use a list to save past trade events and status, first is opening event, last is closing event

    """

    # Trade counter
    refbasis = itertools.count(1)
    # Trade status names
    status_names = ["Created", "Open", "Closed"]
    Created, Open, Closed = range(3)

    # Print trade related information
    def __str__(self):
        toprint = (
            "ref",
            "data",
            "tradeid",
            "size",
            "price",
            "value",
            "commission",
            "pnl",
            "pnlcomm",
            "justopened",
            "isopen",
            "isclosed",
            "baropen",
            "dtopen",
            "barclose",
            "dtclose",
            "barlen",
            "historyon",
            "history",
            "status",
        )

        return "\n".join(":".join((x, str(getattr(self, x)))) for x in toprint)

    # Initialize
    def __init__(
        self, data=None, tradeid=0, historyon=False, size=0, price=0.0, value=0.0, commission=0.0
    ):
        """Initialize a Trade object.

        Args:
            data: Data source associated with this trade.
            tradeid: Unique identifier for the trade.
            historyon: Whether to record trade history.
            size: Initial position size.
            price: Initial price.
            value: Initial value.
            commission: Initial commission.
        """
        self.long = None
        self.ref = next(self.refbasis)
        self.data = data
        self.tradeid = tradeid
        self.size = size
        self.price = price
        self.value = value
        self.commission = commission

        self.pnl = 0.0
        self.pnlcomm = 0.0

        self.justopened = False
        self.isopen = False
        self.isclosed = False

        self.baropen = 0
        self.dtopen = 0.0
        self.barclose = 0
        self.dtclose = 0.0
        self.barlen = 0

        self.historyon = historyon
        self.history = list()

        self.status = self.Created

    # Return absolute size of trade, seems slightly odd
    def __len__(self):
        """Absolute size of the trade"""
        return abs(self.size)

    # Check if trade is 0, when trade size is 0, trade is closed, if not 0, trade is open
    def __bool__(self):
        """Trade size is not 0"""
        return self.size != 0

    __nonzero__ = __bool__

    # Return data name
    def getdataname(self):
        """Shortcut to retrieve the name of the data this trade references"""
        return self.data._name

    # Return opening time
    def open_datetime(self, tz=None, naive=True):
        """Returns a datetime.datetime object with the datetime in which
        the trade was opened
        """
        # data contains num2date method
        return self.data.num2date(self.dtopen, tz=tz, naive=naive)

    # Return closing time
    def close_datetime(self, tz=None, naive=True):
        """Returns a datetime.datetime object with the datetime in which
        the trade was closed
        """
        return self.data.num2date(self.dtclose, tz=tz, naive=naive)

    # Update trade event
    def update(self, order, size, price, value, commission, pnl, comminfo):
        """
        Updates the current trade. The logic does not check if the
        trade is reversed, which is not conceptually supported by the
        object.

        If an update sets the size attribute to 0, "closed" will be
        set to true

        Updates may be received twice for each order, once for the existing
        size which has been closed (sell undoing a buy) and a second time for
        the the opening part (sell reversing a buy)
        # Update current trade. Logic doesn't check if trade is reversed, not conceptually supported
        Args:
            order: the order object which has (completely or partially)
                generated this updatede
            # Order that caused trade update
            size (int): amount to update the order
                if size has the same sign as the current trade a
                position increase will happen
                if size has the opposite sign as current op size a
                reduction/close will happen
            # Size to update trade, if size sign matches current trade, position increases; if size sign doesn't match current trade, causes position reduction or close
            price (float): always be positive to ensure consistency
            # Price, always positive to ensure consistency. Unknown what happens if negative
            value (float): (unused) cost incurred in new size/price op
                           Not used because the value is calculated for the
                           trade
            # Market value, not used because value is calculated through trade
            commission (float): incurred commission in the new size/price op
            # Commission generated by new trade
            pnl (float): (unused) generated by the executed part
                         Not used because the trade has an independent pnl
            # Profit/loss generated by executed part, not used because trade has independent profit/loss
            comminfo: commission information
        """
        # If update size is 0, return directly
        if not size:
            return  # empty update, skip all other calculations

        # Commission can only increase
        # Commission keeps increasing
        self.commission += commission

        # Update size and keep a reference for logic a calculations
        # Update trade size
        oldsize = self.size
        self.size += size  # size will carry the opposite sign if reducing

        # Check if it has been currently opened
        # If original position was 0 but current position is not 0, this means position just opened
        self.justopened = bool(not oldsize and size)
        # If position just opened, update baropen, dtopen and long
        if self.justopened:
            self.baropen = len(self.data)
            self.dtopen = 0.0 if order.p.simulated else self.data.datetime[0]
            self.long = self.size > 0

        # Any size means the trade was opened
        # Check if current trade is open
        self.isopen = bool(self.size)

        # Update current trade length
        # Update current trade's holding bar count
        self.barlen = len(self.data) - self.baropen

        # record if the position was closed (set to null)
        # If original position was not 0 but current position is 0, trade has been closed
        self.isclosed = bool(oldsize and not self.size)

        # record last bar for the trade
        # If already closed, update isopen, barclose, dtclose, status attributes
        if self.isclosed:
            self.isopen = False
            self.barclose = len(self.data)
            self.dtclose = self.data.datetime[0]

            self.status = self.Closed
        # If currently open, update status
        elif self.isopen:
            self.status = self.Open
        # If adding to position
        if abs(self.size) > abs(oldsize):
            # position increased (be it positive or negative)
            # update the average price
            self.price = (oldsize * self.price + size * price) / self.size
            pnl = 0.0
        # If closing part of position
        else:  # abs(self.size) < abs(oldsize)
            # position reduced/closed
            # Calculate profit/loss
            pnl = comminfo.profitandloss(-size, self.price, price)
        # Trade profit/loss
        self.pnl += pnl
        # Trade net profit/loss
        self.pnlcomm = self.pnl - self.commission
        # Update trade value
        self.value = comminfo.getvaluesize(self.size, self.price)

        # Update the history if needed
        # If needed, add trade's history status, save to self.history
        if self.historyon:
            dt0 = self.data.datetime[0] if not order.p.simulated else 0.0
            histentry = TradeHistory(
                self.status,
                dt0,
                self.barlen,
                self.size,
                self.price,
                self.value,
                self.pnl,
                self.pnlcomm,
                self.data._tz,
            )
            histentry.doupdate(order, size, price, commission)
            self.history.append(histentry)
