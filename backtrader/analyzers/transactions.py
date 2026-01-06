#!/usr/bin/env python
import collections

from ..analyzer import Analyzer
from ..order import Order
from ..position import Position


# Transactions
class Transactions(Analyzer):
    """This analyzer reports the transactions occurred with each every data in
    the system

    It looks at the order execution bits to create a `Position` starting from
    0 during each `next` cycle.

    The result is used during next to record the transactions

    Params:

      - Headers (default: ``True``)

        Add an initial key to the dictionary holding the results with the names
        of the datas

        This analyzer was modeled to facilitate the integration with
        ``pyfolio``, and the header names are taken from the samples used for
        it::

          'Date', 'amount', 'price', 'sid', 'symbol', 'value'

    Methods:

      - Get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    """

    # Parameters
    params = (
        ("headers", False),
        ("_pfheaders", ("date", "amount", "price", "sid", "symbol", "value")),
    )

    # Initialize
    def __init__(self, *args, **kwargs):
        # CRITICAL FIX: Call super().__init__() first to initialize self.p
        super().__init__(*args, **kwargs)
        self._idnames = None
        self._positions = None

    def start(self):
        super().start()
        # If headers is True, initialize rets
        if self.p.headers:
            self.rets[self.p._pfheaders[0]] = [list(self.p._pfheaders[1:])]
        # Positions
        self._positions = collections.defaultdict(Position)
        # Index and data names
        self._idnames = list(enumerate(self.strategy.getdatanames()))

    # Order information processing
    def notify_order(self, order):
        # An order could have several partial executions per cycle (unlikely
        # but possible) and therefore: collect each new execution notification
        # and let the work for the next

        # We use a fresh Position object for each round to get a summary of what
        # the execution bits have done in that round
        # If order is not executed, ignore
        if order.status not in [Order.Partial, Order.Completed]:
            return  # It's not an execution
        # Get position of the data that generated the order
        pos = self._positions[order.data._name]
        # Loop
        for exbit in order.executed.iterpending():
            # If execution info is None, break
            if exbit is None:
                break  # end of pending reached
            # Update position information
            pos.update(exbit.size, exbit.price)

    # Called once per bar
    def next(self):
        # super(Transactions, self).next()  # let dtkey update
        # Entries
        entries = []
        # For index and data names
        for i, dname in self._idnames:
            # Get position of the data
            pos = self._positions.get(dname, None)
            # If position is not None, if position is not 0, save position related data
            if pos is not None:
                size, price = pos.size, pos.price
                if size:
                    entries.append([size, price, i, dname, -size * price])
        # If position is not 0, update current bar's position data
        if entries:
            self.rets[self.strategy.datetime.datetime()] = entries
        # Clear self._positions
        self._positions.clear()
