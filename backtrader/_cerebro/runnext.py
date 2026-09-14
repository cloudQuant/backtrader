"""Cerebro event-driven engine mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: ``_runnext`` (modern, with
the direct-load fast path) and ``_runnext_old`` (oldsync). Hot loop - any
edit here must be justified against AC28-09.
"""

import datetime
from datetime import timezone

from ..brokers import BackBroker
from ..feed import AbstractDataBase
from ..strategy import Strategy
from ..utils import date2num
from ..utils.dateintern import _num2date_cached
from ..utils.log_message import get_logger

UTC = timezone.utc

# Keep the historical logger name (D28-04.6): routing/filters must not change.
logger = get_logger("backtrader.cerebro")


class RunNextMixin:
    """Event-driven engine half of Cerebro (see module docstring)."""

    # Old runnext method, similar to runnext
    def _runnext_old(self, runstrats):
        """
        Actual implementation of run in full next mode. All objects have its
        `next` method invoked on each data arrival
        """
        data0 = self.datas[0]
        d0ret = True
        while d0ret or d0ret is None:
            lastret = False
            # Notify anything from the store even before moving datas
            # because datas may not move due to an error reported by the store
            self._storenotify()
            if self._event_stop:  # stop if requested
                return
            self._datanotify()
            if self._event_stop:  # stop if requested
                return

            d0ret = data0.next()
            if d0ret:
                for data in self.datas[1:]:
                    if not data.next(datamaster=data0):  # no delivery
                        data._check(forcedata=data0)  # check forcing output
                        data.next(datamaster=data0)  # retry

            elif d0ret is None:
                # meant for things like live feeds which may not produce a bar
                # at the moment but need the loop to run for notifications and
                # getting resample and others to produce timely bars
                data0._check()
                for data in self.datas[1:]:
                    data._check()
            else:
                lastret = data0._last()
                for data in self.datas[1:]:
                    lastret += data._last(datamaster=data0)

                if not lastret:
                    # Only go extra round if something was changed by "lasts"
                    break

            # Datas may have generated a new notification after next
            self._datanotify()
            if self._event_stop:  # stop if requested
                return

            self._brokernotify()
            if self._event_stop:  # stop if requested
                return

            if d0ret or lastret:  # bars produced by data or filters
                for strat in runstrats:
                    strat._next()
                    if self._event_stop:  # stop if requested
                        return

                    self._next_writers(runstrats)

        # Last notification chance before stopping
        self._datanotify()
        if self._event_stop:  # stop if requested
            return
        self._storenotify()
        if self._event_stop:  # stop if requested
            return

    # runnext method, core of the framework, event-driven core for data execution
    def _runnext(self, runstrats):
        """Actual implementation of run in full next mode.

        All objects have their ``next`` method invoked on each data arrival.

        The loop has four phases per iteration:

        1. **Notification**: store and data notifications dispatched.
        2. **Feed advance**: each data feed is advanced; ``d0ret`` computed.
        3. **Time alignment**: feeds aligned to master datetime ``dt0``;
           slower feeds rewound, faster feeds tick-filled.
        4. **Strategy dispatch**: timers fired, broker notified, strategies
           receive ``_next()`` / ``_next_open()``.
        """
        try:
            # Sort data by time period
            datas = sorted(self.datas, key=lambda x: (x._timeframe, x._compression))
            # Other data
            datas1 = datas[1:]
            # Main data
            data0 = datas[0]
            has_qcheck = any(d.p.qcheck for d in datas)
            cheat_on_open = self.p.cheat_on_open
            has_timers = bool(self._timers)
            has_timerscheat = bool(self._timerscheat)
            has_stores = bool(self.stores)
            has_runwriters = bool(self.runwriters)
            if len(runstrats) == 1:
                single_runstrat = runstrats[0]
                single_runstrat_next = single_runstrat._next
                single_runstrat_next_open = single_runstrat._next_open
            else:
                single_runstrat = None
                single_runstrat_next = None
                single_runstrat_next_open = None
            idle_notifiers = tuple(
                strat.notify_idle
                for strat in runstrats
                if type(strat).notify_idle is not Strategy.notify_idle
            )
            d0ret = True
            # index for resample only, not replay
            rsonly = [i for i, x in enumerate(datas) if x.resampling and not x.replaying]
            # Check if only doing resample
            onlyresample = len(datas) == len(rsonly)
            # Check if no data needs resample
            noresample = not rsonly
            # Number of cloned data
            clonecount = sum(d._clone for d in datas)
            # Number of data
            ldatas = len(datas)
            single_data = ldatas == 1
            single_default_datanotify = (
                single_data and type(data0).get_notifications is AbstractDataBase.get_notifications
            )
            single_default_haslivedata = (
                single_data and type(data0).haslivedata is AbstractDataBase.haslivedata
            )
            data0_datetime_line = data0.datetime if single_data else None
            broker = self._broker
            broker_next = broker.next
            broker_next_without_bar = bool(getattr(broker, "next_without_bar", False))
            broker_userhist = getattr(broker, "_userhist", None)
            broker_fundhist = getattr(broker, "_fundhist", None)
            default_broker_notifications = (
                type(broker).get_notification is BackBroker.get_notification
            )
            default_backbroker_next = (
                default_broker_notifications and type(broker).next is BackBroker.next
            )
            if default_broker_notifications:
                broker_notifications = broker.notifs
                broker_get_notification = None
            else:
                broker_notifications = None
                broker_get_notification = broker.get_notification
            if default_backbroker_next:
                broker_pending = broker.pending
                broker_submitted = broker.submitted
                broker_toactivate = broker._toactivate
                broker_cash_addition = broker._cash_addition
                broker_dual_side_mode = broker._dual_side_mode
            else:
                broker_pending = None
                broker_submitted = None
                broker_toactivate = None
                broker_cash_addition = None
                broker_dual_side_mode = False
            data0_direct_load = None
            if single_data and not has_qcheck and single_default_haslivedata:
                try:
                    if data0._runnext_direct_load_ready():
                        data0_direct_load = getattr(data0, "_runnext_direct_load", data0.load)
                except AttributeError:
                    data0_direct_load = None
            if data0_direct_load is not None and single_runstrat is not None:
                try:
                    if (
                        single_runstrat._fast_simple_clock_update
                        and single_runstrat._single_clock_data is data0
                        and type(single_runstrat)._next is Strategy._next
                    ):
                        single_runstrat_next = single_runstrat._next_fast_simple_direct_clock
                        object.__setattr__(single_runstrat, "_next", single_runstrat_next)
                except AttributeError:
                    pass
            # Number of non-cloned data
            ldatas_noclones = ldatas - clonecount
            # Default dt0 at max time
            dt0 = date2num(datetime.datetime.max) - 2  # default at max
            if (
                data0_direct_load is not None
                and single_runstrat_next is not None
                and getattr(single_runstrat_next, "__func__", None)
                is Strategy._next_fast_simple_direct_clock
                and default_broker_notifications
                and default_backbroker_next
                and single_default_datanotify
                and not has_timers
                and not has_timerscheat
                and not cheat_on_open
                and not has_stores
                and not has_runwriters
                and not broker_userhist
                and not broker_fundhist
            ):
                if data0.notifs:
                    self._datanotify()
                    if self._event_stop:
                        return
                quicknotify = self.p.quicknotify
                strat_forward_line = single_runstrat._single_line_forward_line
                strat_clock_datetime_line = single_runstrat._single_clock_datetime_line
                strat_forward_append = strat_forward_line.array.append
                strat_clock_datetime_array = strat_clock_datetime_line.array
                strat_dlens = single_runstrat._dlens
                strat_minperiod = single_runstrat._single_minperiod
                strat_minperiod_len_line = single_runstrat._single_minperiod_len_line
                strat_minperstatus = strat_minperiod - strat_minperiod_len_line.lencount
                strat_orderspending = single_runstrat._orderspending
                strat_tradespending = single_runstrat._tradespending
                strat_dict = single_runstrat.__dict__
                strat_next = single_runstrat.next
                strat_nextstart = single_runstrat.nextstart
                strat_prenext = single_runstrat.prenext
                strat_clear = single_runstrat.clear
                while True:
                    if not data0_direct_load():
                        break

                    if not (
                        broker._no_open_positions
                        and not broker_pending
                        and not broker_submitted
                        and not broker_toactivate
                        and not broker_cash_addition
                        and not broker_dual_side_mode
                        and not broker_notifications
                    ):
                        broker_next()

                    while broker_notifications:
                        order = broker_notifications.popleft()
                        owner = order.owner
                        if owner is None:
                            owner = single_runstrat
                        owner._addnotification(order, quicknotify=quicknotify)

                    if self._event_stop:
                        return

                    if strat_orderspending or strat_tradespending:
                        Strategy._next(single_runstrat)
                        strat_orderspending = single_runstrat._orderspending
                        strat_tradespending = single_runstrat._tradespending
                        strat_minperstatus = single_runstrat._minperstatus
                    else:
                        dt_value = strat_clock_datetime_array[strat_clock_datetime_line._idx]
                        strat_forward_line._idx += 1
                        strat_forward_line.lencount += 1
                        strat_forward_append(dt_value)
                        strat_dlens[0] = strat_clock_datetime_line.lencount

                        strat_minperstatus -= 1
                        strat_dict["_minperstatus"] = strat_minperstatus
                        if strat_minperstatus < 0:
                            strat_next()
                        elif strat_minperstatus == 0:
                            strat_nextstart()
                        else:
                            strat_prenext()
                        if strat_orderspending or strat_tradespending:
                            strat_clear()
                            strat_orderspending = single_runstrat._orderspending
                            strat_tradespending = single_runstrat._tradespending
                    if self._event_stop:
                        return

                if data0.notifs:
                    self._datanotify()
                return
            # Note: 'while True' (not 'while d0ret or d0ret is None') is intentional:
            # when d0ret becomes False, the else branch still runs _last() on feeds
            # and only breaks if no feed produces additional data.
            while True:
                # if any has live data in the buffer, no data will wait anything
                # If any live data exists, newqcheck is False
                if single_data:
                    newqcheck = True if single_default_haslivedata else not data0.haslivedata()
                else:
                    newqcheck = not any(d.haslivedata() for d in datas)
                # If live data exists
                if not newqcheck:
                    # If no data has reached the live status or all, wait for
                    # the next incoming data
                    # livecount is the number of live data
                    if single_data:
                        livecount = data0._laststatus == data0.LIVE
                    else:
                        livecount = sum(d._laststatus == d.LIVE for d in datas)
                    # Override qcheck for mixed live/historical: wait only when
                    # no feeds are LIVE or ALL non-clone feeds are LIVE.
                    # When only some feeds are LIVE, skip wait for faster iteration.
                    newqcheck = not livecount or livecount == ldatas_noclones

                lastret = False
                # Notify anything from the store even before moving datas
                # because datas may not move due to an error reported by the store
                # Notify store related info
                if has_stores:
                    self._storenotify()
                    if self._event_stop:  # stop if requested
                        return
                # Notify data related info
                if not single_default_datanotify or data0.notifs:
                    self._datanotify()
                if self._event_stop:  # stop if requested
                    return

                # record starting time and tell feeds to discount the elapsed time
                # from the qcheck value
                # Record start time and notify feed to subtract elapsed time from qcheck
                if data0_direct_load is not None:
                    drets = (data0_direct_load(),)
                else:
                    drets = []
                if data0_direct_load is None and newqcheck and has_qcheck:
                    qstart = datetime.datetime.now(UTC)
                    for d in datas:
                        qlapse = datetime.datetime.now(UTC) - qstart
                        d.do_qcheck(newqcheck, qlapse.total_seconds())
                        d_next = d.next(ticks=False)
                        drets.append(d_next)
                elif data0_direct_load is None:
                    for d in datas:
                        if has_qcheck:
                            d.do_qcheck(False, 0.0)
                        d_next = d.next(ticks=False)
                        drets.append(d_next)
                # Iterate drets, if d0ret is False and any dret is None, d0ret is None
                if single_data:
                    dret0 = drets[0]
                    d0ret = bool(dret0)
                    if not d0ret and dret0 is None:
                        d0ret = None
                else:
                    d0ret = any(dret for dret in drets)
                    if not d0ret and any(dret is None for dret in drets):
                        d0ret = None
                # If d0ret is not None
                if d0ret:
                    # Get time
                    if single_data:
                        try:
                            data0_datetime_idx = data0_datetime_line._idx
                            if data0_datetime_idx >= 0:
                                dt0 = data0_datetime_line.array[data0_datetime_idx]
                            else:
                                dt0 = data0_datetime_line[0]
                        except (AttributeError, IndexError):
                            dt0 = data0.datetime[0]
                        dts = [dt0]
                        dmaster = data0
                    else:
                        dts = []
                        for i, ret in enumerate(drets):
                            dts.append(datas[i].datetime[0] if ret else None)
                        # Get index to minimum datetime
                        # Get minimum time
                        if onlyresample or noresample:
                            dt0 = min(d for d in dts if d is not None)
                        else:
                            dt0 = min(
                                (d for i, d in enumerate(dts) if d is not None and i not in rsonly)
                            )
                        # Get master data and time
                        dmaster = datas[dts.index(dt0)]  # and timemaster
                    # Guard: dt0 < 1 means ordinal date before 0001-01-01
                    # (invalid/sentinel value from uninitialized data)
                    if dt0 < 1:
                        logger.warning(
                            "Invalid datetime value dt0=%s detected in _runnext, aborting run loop",
                            dt0,
                        )
                        return
                    if broker_userhist or broker_fundhist:
                        udtmaster = _num2date_cached(dt0)
                        self._udtmaster = udtmaster
                        self._dtmaster = (
                            udtmaster
                            if getattr(dmaster, "_tz", None) is None
                            else dmaster.num2date(dt0)
                        )

                    # Try to get something for those that didn't return
                    # Loop through drets
                    for i, ret in enumerate(drets):
                        # If ret is not None, continue to next ret
                        if ret:  # dts already contains a valid datetime for this i
                            continue

                        # try to get data by checking with a master
                        # Get data and try to set time for dts
                        d = datas[i]
                        d._check(forcedata=dmaster)  # check to force output
                        if d.next(datamaster=dmaster, ticks=False):  # retry
                            dts[i] = d.datetime[0]  # good -> store

                    # make sure only those at dmaster level end up delivering
                    # Iterate dts
                    for i, dti in enumerate(dts):
                        # If dti is not None
                        if dti is not None:
                            # Get data
                            di = datas[i]
                            if dti > dt0:
                                di.rewind()  # cannot deliver yet
                            # If not replay
                            elif not di.replaying:
                                # Replay forces tick fill, else force here
                                try:
                                    tick_direct_filled = di._tick_direct_filled
                                except AttributeError:
                                    tick_direct_filled = False
                                if not tick_direct_filled:
                                    di._tick_fill(force=True)
                # If d0ret is None, iterate each data and call _check()
                elif d0ret is None:
                    # meant for things like live feeds which may not produce a bar
                    # at the moment but need the loop to run for notifications and
                    # getting resample and others to produce timely bars
                    for data in datas:
                        data._check()
                # If other case
                else:
                    lastret = data0._last()
                    for data in datas1:
                        lastret += data._last(datamaster=data0)
                    if not lastret:
                        # Only go extra round if something was changed by "lasts"
                        break

                # Datas may have generated a new notification after next
                # Notify data info
                if not single_default_datanotify or data0.notifs:
                    self._datanotify()
                if self._event_stop:  # stop if requested
                    return
                # Check timer and iterate strategies, call _next_open() to run
                if d0ret or lastret:  # if any bar, check timers before broker
                    if has_timerscheat:
                        self._check_timers(runstrats, dt0, cheat=True)
                    if cheat_on_open:
                        if single_runstrat is not None:
                            single_runstrat_next_open()
                            if self._event_stop:  # stop if requested
                                return
                        else:
                            for strat in runstrats:
                                strat._next_open()
                                if self._event_stop:  # stop if requested
                                    return
                # Live brokers can receive fills during a gap in market bars.
                # Bar-matching brokers still require populated data lines.
                poll_without_bar = d0ret is None and broker_next_without_bar
                if d0ret or lastret or poll_without_bar:
                    skip_broker_next = False
                    if default_backbroker_next:
                        skip_broker_next = (
                            broker._no_open_positions
                            and not broker_pending
                            and not broker_submitted
                            and not broker_toactivate
                            and not broker_userhist
                            and not broker_cash_addition
                            and not broker_fundhist
                            and not broker_dual_side_mode
                            and not broker_notifications
                        )
                    if not skip_broker_next:
                        broker_next()
                    if default_broker_notifications:
                        while broker_notifications:
                            order = broker_notifications.popleft()
                            owner = order.owner
                            if owner is None:
                                owner = self.runningstrats[0]  # default
                            owner._addnotification(order, quicknotify=self.p.quicknotify)
                    else:
                        while True:
                            order = broker_get_notification()
                            if order is None:
                                break
                            owner = order.owner
                            if owner is None:
                                owner = self.runningstrats[0]  # default
                            owner._addnotification(order, quicknotify=self.p.quicknotify)
                    if poll_without_bar:
                        for strat in runstrats:
                            if not self.p.quicknotify:
                                strat._notify()
                            strat.clear()
                    if self._event_stop:  # stop if requested
                        return

                if d0ret is None:
                    for notify_idle in idle_notifiers:
                        notify_idle()
                        if self._event_stop:
                            return

                # Notify timer and iterate strategies to run
                if d0ret or lastret:  # bars produced by data or filters
                    if has_timers:
                        self._check_timers(runstrats, dt0, cheat=False)
                    if single_runstrat is not None:
                        single_runstrat_next()
                        if self._event_stop:  # stop if requested
                            return

                        if has_runwriters:
                            self._next_writers(runstrats)
                    else:
                        for strat in runstrats:
                            strat._next()
                            if self._event_stop:  # stop if requested
                                return

                            if has_runwriters:
                                self._next_writers(runstrats)
            # Last notification chance before stopping
            # Notify data info
            if not single_default_datanotify or data0.notifs:
                self._datanotify()
            if self._event_stop:  # stop if requested
                return
            # Notify store info
            if has_stores:
                self._storenotify()
                if self._event_stop:  # stop if requested
                    return
        except Exception:
            logger.exception("Unhandled exception in _runnext")
            raise
