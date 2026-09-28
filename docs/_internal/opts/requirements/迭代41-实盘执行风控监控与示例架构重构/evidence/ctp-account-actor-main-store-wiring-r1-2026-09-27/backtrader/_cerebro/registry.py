"""Cerebro configuration/registration mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: data feed registration,
timers, timezone/calendar, signals, stores, writers, sizers, indicators,
analyzers, observers, strategy registration and timer dispatch.
"""

import collections
import datetime
import itertools

from .. import feeds
from ..timer import Timer
from ..tradingcal import PandasMarketCalendar, TradingCalendarBase
from ..utils.log_message import get_logger
from ..utils.py3 import map, string_types, zip  # noqa: F401

logger = get_logger(__name__)

collectionsAbc = collections.abc


class RegistryMixin:
    """Configuration/registration half of Cerebro (see module docstring)."""

    @staticmethod
    def iterize(iterable):
        """Convert each element in iterable to be iterable itself.

        Args:
            iterable: Input iterable whose elements may not be iterable.

        Returns:
            list: New list where each element is guaranteed to be iterable.
        """
        niterable = []
        for elem in iterable:
            if isinstance(elem, string_types) or not isinstance(elem, collectionsAbc.Iterable):
                elem = (elem,)

            niterable.append(elem)

        return niterable

    def set_fund_history(self, fund):
        """
        Add a history of orders to be directly executed in the broker for
        performance evaluation

          - ``fund``: is an iterable (ex: list, tuple, iterator, generator)
            in which each element will be also iterable (with length) with
            the following sub-elements (two formats are possible)

            ``[datetime, share_value, net asset value]``

            **Note**: it must be sorted (or produce sorted elements) by
              datetime ascending

            where:

              - ``datetime`` is a python ``date/datetime`` instance or a string
                with format YYYY-MM-DD[THH:MM:SS[.us]] where the elements in
                brackets are optional
              - ``share_value`` is a float/integer
              - ``net_asset_value`` is a float/integer
        """
        self._fhistory = fund

    def add_order_history(self, orders, notify=True):
        """
        Add a history of orders to be directly executed in the broker for
        performance evaluation

          - ``orders``: is an iterable (ex: list, tuple, iterator, generator)
            in which each element will be also iterable (with length) with
            the following sub-elements (two formats are possible)

            ``[datetime, size, price]`` or ``[datetime, size, price, data]``

            **Note**: it must be sorted (or produce sorted elements) by
              datetime ascending

            where:

              - ``datetime`` is a python ``date/datetime`` instance or a string
                with format YYYY-MM-DD[THH:MM:SS[.us]] where the elements in
                brackets are optional
              - ``size`` is an integer (positive to *buy*, negative to *sell*)
              - ``price`` is a float/integer
              - ``data`` if present can take any of the following values

                - *None* - The 1st data feed will be used as target
                - *integer* - The data with that index (insertion order in
                  **Cerebro**) will be used
                - *string* - a data with that name, assigned for example with
                  ``cerebro.addata(data, name=value)``, will be the target

          - ``notify`` (default: *True*)

            If ``True``, the first strategy inserted in the system will be
            notified of the artificial orders created following the information
            from each order in ``orders``

        **Note**: Implicit in the description is the need to add a data feed
          which is the target of the orders.This is, for example, needed by
          analyzers which track, for example, the returns
        """
        self._ohistory.append((orders, notify))

    def notify_timer(self, timer, when, *args, **kwargs):
        """Receives a timer notification where ``timer`` is the timer that was
        returned by ``add_timer``, and ``when`` is the calling time. ``args``
        and ``kwargs`` are any additional arguments passed to ``add_timer``

        The actual `when` time can be later, but the system may have not been
        able to call the timer before. This value is the timer value and no the
        system time.
        """

    def _add_timer(
        self,
        owner,
        when,
        offset=datetime.timedelta(),
        repeat=datetime.timedelta(),
        weekdays=None,
        weekcarry=False,
        monthdays=None,
        monthcarry=True,
        allow=None,
        tzdata=None,
        strats=False,
        cheat=False,
        *args,
        **kwargs,
    ):
        """Internal method to really create the timer (not started yet) which
        can be called by cerebro instances or other objects which can access
        cerebro"""

        # Normalize mutable-default placeholders (B006): Timer treats None as
        # "all days", identical to the previous empty-list default.
        weekdays = [] if weekdays is None else weekdays
        monthdays = [] if monthdays is None else monthdays
        timer = Timer(
            tid=len(self._pretimers),
            owner=owner,
            strats=strats,
            when=when,
            offset=offset,
            repeat=repeat,
            weekdays=weekdays,
            weekcarry=weekcarry,
            monthdays=monthdays,
            monthcarry=monthcarry,
            allow=allow,
            tzdata=tzdata,
            cheat=cheat,
            *args,
            **kwargs,
        )

        self._pretimers.append(timer)
        return timer

    def add_timer(
        self,
        when,
        offset=datetime.timedelta(),
        repeat=datetime.timedelta(),
        weekdays=None,
        weekcarry=False,
        monthdays=None,
        monthcarry=True,
        allow=None,
        tzdata=None,
        strats=False,
        cheat=False,
        *args,
        **kwargs,
    ):
        """
        Schedules a timer to invoke ``notify_timer``

        Arguments:

          - ``when``: can be

            - ``datetime.time`` instance (see below ``tzdata``)
            - ``bt.timer.SESSION_START`` to reference a session start
            - ``bt.timer.SESSION_END`` to reference a session end

         - ``offset`` which must be a ``datetime.timedelta`` instance

           Used to offset the value ``when``. It has a meaningful use in
           combination with ``SESSION_START`` and ``SESSION_END``, to indicate
           things like a timer being called ``15 minutes`` after the session
            starts.

          - ``repeat`` which must be a ``datetime.timedelta`` instance

            Indicates if after a first call, further calls will be scheduled
            within the same session at the scheduled `repeat` delta

            Once the timer goes over the end of the session, it is reset to the
            original value for ``when``

          - ``weekdays``: a **sorted** iterable with integers indicating on
            which days (iso codes, Monday is 1, Sunday is 7) the timers can
            be actually invoked

            If not specified, the timer will be active on all days

          - ``weekcarry`` (default: ``False``). If ``True`` and the weekday was
            not seen (ex: trading holiday), the timer will be executed on the
            next day (even if in a new week)

          - ``monthdays``: a **sorted** iterable with integers indicating on
            which days of the month a timer has to be executed. For example,
            always on day *15* of the month

            If not specified, the timer will be active on all days

          - ``monthcarry`` (default: ``True``). If the day was not seen
            (weekend, trading holiday), the timer will be executed on the next
            available day.

          - ``allow`` (default: ``None``). A callback which receives a
            `datetime.date`` instance and returns ``True`` if the date is
            allowed for timers or else returns ``False``

          - ``tzdata`` which can be either ``None`` (default), a ``pytz``
            instance or a ``data feed`` instance.

            ``None``: ``when`` is interpreted at face value (which translates
            to handling it as if it is UTC even if it's not)

            ``pytz`` instance: ``when`` will be interpreted as being specified
            in the local time specified by the timezone instance.

            ``data feed`` instance: ``when`` will be interpreted as being
            specified in the local time specified by the ``tz`` parameter of
            the data feed instance.

            **Note**: If ``when`` is either ``SESSION_START`` or
              ``SESSION_END`` and ``tzdata`` is ``None``, the first *data feed*
              in the system (aka ``self.data0``) will be used as the reference
              to find out the session times.

          - ``strats`` (default: ``False``) call also the ``notify_timer`` of strategies

          - ``cheat`` (default ``False``) if ``True`` the timer will be called
            before the broker has a chance to evaluate the orders. This opens
            the chance to issue orders based on opening price, for example, right
            before the session starts
          - ``*args``: any extra args will be passed to ``notify_timer``

          - ``**kwargs``: any extra kwargs will be passed to ``notify_timer``

        Return Value:

          - The created timer

        """
        # NOTE: *args (extra notify_timer args) are forwarded positionally after
        # the named timer kwargs; _add_timer collects them into its own *args.
        return self._add_timer(
            owner=self,
            when=when,
            offset=offset,
            repeat=repeat,
            weekdays=weekdays,
            weekcarry=weekcarry,
            monthdays=monthdays,
            monthcarry=monthcarry,
            allow=allow,
            tzdata=tzdata,
            strats=strats,
            cheat=cheat,
            *args,
            **kwargs,
        )

    def addtz(self, tz):
        """This can also be done with the parameter ``tz``

        Adds a global timezone for strategies. The argument ``tz`` can be

          - ``None``: in this case the datetime displayed by strategies will be
            in UTC, which has always been the standard behavior

          - ``pytz`` instance. It will be used as such to convert UTC times to
            the chosen timezone

          - ``string``. Instantiating a ``pytz`` instance will be attempted.

          - ``integer``. Use, for the strategy, the same timezone as the
            corresponding ``data`` in the ``self.datas`` iterable (``0`` would
            use the timezone from ``data0``)

        """
        self.p.tz = tz

    def addcalendar(self, cal):
        """Adds a global trading calendar to the system. Individual data feeds
        may have separate calendars which override the global one

        ``cal`` can be an instance of ``TradingCalendar`` a string or an
        instance of ``pandas_market_calendars``. A string will be
        instantiated as a ``PandasMarketCalendar`` (which needs the module
        ``pandas_market_calendar`` installed in the system).

        If a subclass of `TradingCalendarBase` is passed (not an instance), it
        will be instantiated
        """
        # Handle string or pandas calendar with valid_days attribute
        if isinstance(cal, string_types) or hasattr(cal, "valid_days"):
            cal = PandasMarketCalendar(calendar=cal)
        # Handle TradingCalendarBase subclass or instance
        else:
            try:
                if issubclass(cal, TradingCalendarBase):
                    cal = cal()
            except TypeError:  # already an instance
                logger.debug("registry:324 ignored TypeError")
        self._tradingcal = cal

    def add_signal(self, sigtype, sigcls, *sigargs, **sigkwargs):
        """Add a signal to be used with SignalStrategy."""
        self.signals.append((sigtype, sigcls, sigargs, sigkwargs))

    def signal_strategy(self, stratcls, *args, **kwargs):
        """Set a SignalStrategy subclass to receive signals."""
        self._signal_strat = (stratcls, args, kwargs)

    def signal_concurrent(self, onoff):
        """Allow concurrent orders when signals are pending."""
        self._signal_concurrent = onoff

    def signal_accumulate(self, onoff):
        """If signals are added to the system and the `accumulate` value is
        set to True, entering the market when already in the market, will be
        allowed to increase a position"""
        self._signal_accumulate = onoff

    def addstore(self, store):
        """Add a Store instance to the system."""
        if store not in self.stores:
            self.stores.append(store)

    def _maybe_add_store(self, candidate):
        """Register a store exposed by a broker or data feed."""
        store = getattr(candidate, "store", None) or getattr(candidate, "_store", None)
        if store is not None:
            self.addstore(store)

    def addwriter(self, wrtcls, *args, **kwargs):
        """Adds an ``Writer`` class to the mix. Instantiation will be done at
        ``run`` time in cerebro"""
        self.writers.append((wrtcls, args, kwargs))

    def addsizer(self, sizercls, *args, **kwargs):
        """Adds a ``Sizer`` class (and args) which is the default sizer for any
        strategy added to cerebro
        """
        self.sizers[None] = (sizercls, args, kwargs)

    def addsizer_byidx(self, idx, sizercls, *args, **kwargs):
        """Adds a ``Sizer`` class by idx. This idx is a reference compatible to
        the one returned by ``addstrategy``. Only the strategy referenced by
        ``idx`` will receive this size
        """
        self.sizers[idx] = (sizercls, args, kwargs)

    def addindicator(self, indcls, *args, **kwargs):
        """Add an Indicator class to be instantiated at run time."""
        self.indicators.append((indcls, args, kwargs))

    def addanalyzer(self, ancls: type, *args, **kwargs) -> None:
        """Add an Analyzer class to be instantiated at run time."""
        self.analyzers.append((ancls, args, kwargs))

    def addobserver(self, obscls: type, *args, **kwargs) -> None:
        """
        Adds an ``Observer`` class to the mix. Instantiation will be done at
        ``run`` time
        """
        self.observers.append((False, obscls, args, kwargs))

    def addobservermulti(self, obscls, *args, **kwargs):
        """

        It will be added once per "data" in the system. A use case is a
        buy/sell observer that observes individual data.

        A counter-example is the CashValue, which observes system-wide values
        """
        self.observers.append((True, obscls, args, kwargs))

    def adddata(self, data, name: str = None):
        """
        Adds a ``Data Feed`` instance to the mix.

        If ``name`` is not None, it will be put into ``data._name`` which is
        meant for decoration/plotting purposes.
        """
        # Set data name if provided
        if name is not None:
            data._name = name
            data.name = name
        # Assign unique ID to each data feed
        data._id = next(self._dataid)
        # Set data's environment to this cerebro
        data.setenvironment(self)
        # Add to data list
        self.datas.append(data)
        # Store in name lookup dictionary
        self.datasbyname[data._name] = data
        # Get feed from data
        feed = data.getfeed()
        # Add feed if not already present
        if feed and feed not in self.feeds:
            self.feeds.append(feed)
        self._maybe_add_store(data)
        # Set live mode if data is live
        if data.islive():
            self._dolive = True

        return data

    def chaindata(self, *args, **kwargs):
        """
        Chains several data feeds into one

        If ``name`` is passed as named argument and not `None`, it will be put
        into ``data._name`` which is meant for decoration/plotting purposes.

        If `None`, then the name of the first data will be used
        """
        dname = kwargs.pop("name", None)
        if dname is None:
            dname = args[0]._dataname
        d = feeds.Chainer(dataname=dname, *args)
        self.adddata(d, name=dname)

        return d

    def rolloverdata(self, *args, **kwargs):
        """Chains several data feeds into one

        If ``name`` is passed as named argument and is not None, it will be put
        into ``data._name`` which is meant for decoration/plotting purposes.

        If `None`, then the name of the first data will be used

        Any other kwargs will be passed to the RollOver class

        """
        dname = kwargs.pop("name", None)
        if dname is None:
            dname = args[0]._dataname
        d = feeds.RollOver(dataname=dname, *args, **kwargs)
        self.adddata(d, name=dname)

        return d

    def replaydata(self, dataname, name=None, **kwargs):
        """
        Adds a ``Data Feed`` to be replayed by the system

        If ``name`` is not None, it will be put into ``data._name`` which is
        meant for decoration/plotting purposes.

        Any other kwargs like ``timeframe``, ``compression``, ``todate`` which
        are supported by the replay filter will be passed transparently
        """
        if any(dataname is x for x in self.datas):
            dataname = dataname.clone()

        dataname.replay(**kwargs)
        self.adddata(dataname, name=name)
        self._doreplay = True

        return dataname

    def resampledata(self, dataname, name=None, **kwargs):
        """
        Adds a ``Data Feed`` to be resample by the system

        If ``name`` is not None, it will be put into ``data._name`` which is
        meant for decoration/plotting purposes.

        Any other kwargs like ``timeframe``, ``compression``, ``todate`` which
        are supported by the resample filter will be passed transparently
        """
        if any(dataname is x for x in self.datas):
            dataname = dataname.clone()

        dataname.resample(**kwargs)
        self.adddata(dataname, name=name)
        self._doreplay = True

        return dataname

    def optcallback(self, cb):
        """
        Adds a *callback* to the list of callbacks that will be called with the
        optimizations when each of the strategies has been run

        The signature: cb(strategy)
        """
        self.optcbs.append(cb)

    def optstrategy(self, strategy, *args, **kwargs):
        """
        Adds a ``Strategy`` class to the mix for optimization. Instantiation
        will happen during ``run`` time.

        args and kwargs MUST BE iterables that hold the values to check.

        Example: if a Strategy accepts a parameter `period`, for optimization
        purposes, the call to ``optstrategy`` looks like:

          - cerebro.optstrategy(MyStrategy, period=(15, 25))

        This will execute an optimization for values 15 and 25. Whereas

          - cerebro.optstrategy(MyStrategy, period=range(15, 25))

        will execute MyStrategy with ``period`` values 15 -> 25 (25 not
        included, because ranges are semi-open in Python)

        If a parameter is passed but shall not be optimized, the call looks
        like:

          - cerebro.optstrategy(MyStrategy, period=(15,))

        Notice that `period` is still passed as an iterable ... of just one element

        ``backtrader`` will anyhow try to identify situations like:

          - cerebro.optstrategy(MyStrategy, period=15)

        and will create an internal pseudo-iterable if possible
        """
        self._dooptimize = True
        args = self.iterize(args)
        optargs = itertools.product(*args)

        optkeys = list(kwargs)

        vals = self.iterize(kwargs.values())
        optvals = itertools.product(*vals)

        okwargs1 = map(zip, itertools.repeat(optkeys), optvals)

        optkwargs = map(dict, okwargs1)

        it = itertools.product([strategy], optargs, optkwargs)
        self.strats.append(it)

    def addstrategy(self, strategy: type, *args, **kwargs) -> int:
        """
        Adds a ``Strategy`` class to the mix for a single pass run.
        Instantiation will happen during ``run`` time.

        Args and kwargs will be passed to the strategy as they are during
        instantiation.

        Returns the index with which addition of other objects (like sizers)
        can be referenced
        """
        self.strats.append([(strategy, args, kwargs)])
        return len(self.strats) - 1

    # Check timer
    def _check_timers(self, runstrats, dt0, cheat=False):
        # If cheat is False, timers equals self._timers, otherwise equals self._timerscheat
        timers = self._timers if not cheat else self._timerscheat
        # For timer in timers
        for t in timers:
            # Use timer.check(dt0), if returns True, enter below, otherwise check next timer
            if not t.check(dt0):
                continue
            # CRITICAL FIX: Remove 'when' from kwargs to avoid conflict with position argument
            # when is already passed as t.lastwhen (2nd argument)
            timer_kwargs = {k: v for k, v in t.kwargs.items() if k != "when"}
            # Notify timer
            t.params.owner.notify_timer(t, t.lastwhen, *t.args, **timer_kwargs)
            # If strategy needs to use timer (t.params.strats is True), iterate strategies and call notify_timer
            if t.params.strats:
                for strat in runstrats:
                    strat.notify_timer(t, t.lastwhen, *t.args, **timer_kwargs)
