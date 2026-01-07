#!/usr/bin/env python
from datetime import datetime

from ..feed import DataBase
from ..utils.date import Localizer


class RollOver(DataBase):
    # Roll over to the next future when conditions are met
    """Class that rolls over to the next future when a condition is met

    Params:

        - ``checkdate`` (default: ``None``)

          This must be a *callable* with the following signature::

            Checkdate(dt, d):

          Where:

            - ``dt`` is a ``datetime.datetime`` object
            - ``d`` is the current data feed for the active future

          Expected Return Values:

            - ``True``: as long as the callable returns this, a switchover can
              happen to the next future

        If a commodity expires on the 3rd Friday of March, `checkdate` could
        return `True` for the entire week in which the expiration takes
        place.

            - ``False``: the expiration cannot take place

        # This parameter is a callable object checkdate(dt,d), where dt is a time object, d is current active data,
        # If return value is True, will switch to next contract; if False, will not switch to next contract

        - ``checkcondition`` (default: ``None``)

          **Note**: This will only be called if ``checkdate`` has returned
          ``True``

          If ``None`` this will evaluate to ``True`` (execute roll over)
          internally

          Else this must be a *callable* with this signature::

            Checkcondition(d0, d1)

          Where:

            - ``d0`` is the current data feed for the active future
            - ``d1`` is the data feed for the next expiration

          Expected Return Values:

            - ``True``: roll-over to the next future

        Following with the example from ``checkdate``, this could say that the
        roll-over can only happen if the *volume* from ``d0`` is already less
        than the volume from ``d1``

            - ``False``: the expiration cannot take place
        # When checkdate returns True, this function will be called, this must be a callable object, checkcondition(d0,d1)
        # Where d0 is current active futures contract, d1 is next expiring contract, if True, will switch from d0 to d1, if not, switch will not happen.
    """

    params = (
        # ('rolls', []),  # array of futures to roll over
        ("checkdate", None),  # callable
        ("checkcondition", None),  # callable
    )

    def islive(self):
        # Make data live form, will avoid preloading and runonce
        """Returns ``True`` to notify ``Cerebro`` that preloading and runonce
        should be deactivated"""
        return True

    def __init__(self, *args, **kwargs):
        # Handle timeframe and compression parameters, originally handled by metaclass
        if args:
            # Copy timeframe and compression from first data source
            kwargs.setdefault("timeframe", getattr(args[0], "_timeframe", None))
            kwargs.setdefault("compression", getattr(args[0], "_compression", None))

        super().__init__(**kwargs)

        # Prepare futures contracts for rollover
        self._dts = None
        self._dexp = None
        self._d = None
        self._ds = None
        self._rolls = args

    def start(self):
        super().start()
        # Loop through all data, prepare to start
        for d in self._rolls:
            d.setenvironment(self._env)
            d._start()

        # put the references in a separate list to have pops
        # todo Using list again here seems not very useful, because self._rolls is already list format
        self._ds = list(self._rolls)
        # First data
        self._d = self._ds.pop(0) if self._ds else None
        # Expiration data
        self._dexp = None
        # Here defaults a minimum time, when comparing with any time, will move
        self._dts = [datetime.min for xx in self._ds]

    def stop(self):
        # End data
        super().stop()
        for d in self._rolls:
            d.stop()

    def _gettz(self):
        # Get specific timezone
        """To be overriden by subclasses which may auto-calculate the
        timezone"""
        if self._rolls:
            return self._rolls[0]._gettz()
        return Localizer(self.p.tz)

    def _checkdate(self, dt, d):
        # Calculate if current rollover conditions are met
        if self.p.checkdate is not None:
            return self.p.checkdate(dt, d)

        return False

    def _checkcondition(self, d0, d1):
        # Prepare to start rollover
        if self.p.checkcondition is not None:
            return self.p.checkcondition(d0, d1)

        return True

    def _load(self):
        # Method to load data
        while self._d is not None:
            # When self._d is not None, call next
            _next = self._d.next()
            # If _next value is None, continue calling next
            if _next is None:  # no values yet, more will come
                continue
            # If _next value is False, current data switches to next data,
            if _next is False:  # no values from current data src
                if self._ds:
                    self._d = self._ds.pop(0)
                    self._dts.pop(0)
                else:
                    self._d = None
                continue
            # Current time of current data
            dt0 = self._d.datetime.datetime()  # current dt for active data

            # Synchronize other datas using dt0
            # Synchronize other data based on current time
            for i, d_dt in enumerate(zip(self._ds, self._dts)):
                d, dt = d_dt
                # If other data's time is less than current time, move other data forward, increase time, and save time to self._dts
                while dt < dt0:
                    if d.next() is None:
                        continue
                    self._dts[i] = dt = d.datetime.datetime()

            # Move expired future as much as needed
            # Move expired data
            while self._dexp is not None:
                if not self._dexp.next():
                    self._dexp = None
                    break

                if self._dexp.datetime.datetime() < dt0:
                    continue

            if self._dexp is None and self._checkdate(dt0, self._d):
                # rule has been met ... check other factors only if 2 datas
                # still there
                if self._ds and self._checkcondition(self._d, self._ds[0]):
                    # Time to switch to next data
                    self._dexp = self._d
                    self._d = self._ds.pop(0)
                    self._dts.pop(0)

            # Fill the line and tell we die
            self.lines.datetime[0] = self._d.lines.datetime[0]
            self.lines.open[0] = self._d.lines.open[0]
            self.lines.high[0] = self._d.lines.high[0]
            self.lines.low[0] = self._d.lines.low[0]
            self.lines.close[0] = self._d.lines.close[0]
            self.lines.volume[0] = self._d.lines.volume[0]
            self.lines.openinterest[0] = self._d.lines.openinterest[0]
            return True

        # Out of the loop -> self._d is None, no data feed to return from
        return False
