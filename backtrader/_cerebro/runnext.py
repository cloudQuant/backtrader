"""Cerebro event-driven engine mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: ``_runnext`` (modern, with
the direct-load fast path) and ``_runnext_old`` (oldsync). Hot loop - any
edit here must be justified against AC28-09.
"""

import datetime
import math
import sys
import threading
import time
from datetime import timezone

from ..brokers import BackBroker
from ..feed import AbstractDataBase
from ..strategy import Strategy
from ..utils import date2num
from ..utils.dateintern import _num2date_cached
from ..utils.log_message import get_logger

UTC = timezone.utc
_LIVE_COHORT_BROKER_IDLE_POLL_SECONDS = 0.05

# Keep the historical logger name (D28-04.6): routing/filters must not change.
logger = get_logger("backtrader.cerebro")


def _snapshot_live_cohort_feed_state(data):
    """Capture the bounded line state changed by one normal feed advance."""
    roots = tuple(getattr(getattr(data, "lines", None), "lines", ()))
    pending = list(roots)
    seen = set()
    snapshots = []
    while pending:
        line = pending.pop()
        if id(line) in seen:
            continue
        seen.add(id(line))
        pending.extend(tuple(getattr(line, "bindings", ())))

        array = line.array
        length = len(array)
        index = line._idx
        is_qbuffer = getattr(line, "mode", None) == getattr(line, "QBuffer", object())
        # QBuffer is bounded by its configured capacity. Save that bounded ring
        # so a failed advance can restore an evicted head exactly.
        qbuffer_values = tuple(array) if is_qbuffer else None
        first = array[0] if length else None
        last = array[-1] if length else None
        active = array[index] if 0 <= index < length else None
        caches = tuple(
            (name, getattr(line, name, None))
            for name in ("_dt_cache_idx", "_dt_cache_value", "_dt_cache_tz", "_dt_cache_dt")
        )
        snapshots.append(
            (
                line,
                array,
                index,
                line.lencount,
                length,
                is_qbuffer,
                qbuffer_values,
                first,
                last,
                active,
                caches,
            )
        )

    notifications = getattr(data, "notifs", None)
    feed_state = (
        getattr(data, "_laststatus", None),
        getattr(data, "_live_notified", None),
        getattr(data, "_cohort_last_delivered_slot_index", None),
        len(notifications) if notifications is not None else None,
    )
    return tuple(snapshots), feed_state


def _restore_live_cohort_feed_state(data, checkpoint):
    """Restore line cursors and one-bar writes after a failed batch advance."""
    snapshots, feed_state = checkpoint
    errors = []
    for (
        line,
        original_array,
        index,
        lencount,
        length,
        is_qbuffer,
        qbuffer_values,
        first,
        last,
        active,
        caches,
    ) in reversed(snapshots):
        try:
            if line.array is not original_array:
                line.array = original_array
            array = original_array
            if is_qbuffer:
                array.clear()
                array.extend(qbuffer_values)
            else:
                current_length = len(array)
                if current_length > length:
                    for _ in range(current_length - length):
                        array.pop()
                elif current_length < length:
                    if current_length == length - 1 and length:
                        array.append(last)
                    else:
                        raise RuntimeError("unbounded line lost more than its last slot")
                if length:
                    array[0] = first
                    array[length - 1] = last
                    if 0 <= index < length:
                        array[index] = active
            line._idx = index
            line.lencount = lencount
            for name, value in caches:
                setattr(line, name, value)
        except Exception as exc:
            errors.append(exc)

    old_status, old_live_notified, old_slot_index, notification_count = feed_state
    if old_status is not None:
        data._laststatus = old_status
    if old_live_notified is not None:
        data._live_notified = old_live_notified
    if old_slot_index is not None:
        data._cohort_last_delivered_slot_index = old_slot_index
    notifications = getattr(data, "notifs", None)
    if notifications is not None and notification_count is not None:
        try:
            while len(notifications) > notification_count:
                notifications.pop()
        except Exception as exc:
            errors.append(exc)
    return tuple(errors)


class _LiveBarCohortWake:
    """One compare-before-wait condition shared by cohort Stores."""

    def __init__(self):
        self._condition = threading.Condition()
        self._generation = 0

    def snapshot(self):
        with self._condition:
            return self._generation

    def notify(self):
        with self._condition:
            self._generation += 1
            self._condition.notify_all()

    def wait(self, generation, timeout):
        with self._condition:
            if self._generation != generation:
                return True
            return self._condition.wait_for(
                lambda: self._generation != generation,
                timeout=timeout,
            )


def _live_cohort_broker_timeout(broker):
    """Return the nearest BtApiBroker time-driven poll deadline, if known."""
    if not getattr(broker, "next_without_bar", False):
        return None

    params = getattr(broker, "p", None)
    if params is None:
        return None
    now = time.monotonic()
    deadlines = []

    def add_refresh_deadline(last_attr, interval_attr):
        interval = float(getattr(params, interval_attr, 0.0) or 0.0)
        if interval <= 0:
            deadlines.append(0.0)
            return
        if not math.isfinite(interval):
            return
        last = float(getattr(broker, last_attr, 0.0) or 0.0)
        if last <= 0:
            deadlines.append(0.0)
        else:
            remaining = max(0.0, last + interval - now)
            if math.isfinite(remaining):
                deadlines.append(remaining)

    if getattr(broker, "_live_started", False):
        uses_async = getattr(broker, "_uses_async_commands", None)
        async_pending = bool(
            callable(uses_async)
            and uses_async()
            and getattr(broker, "_periodic_reconcile_pending", False)
        )
        if not async_pending:
            if getattr(params, "position_sync_policy", "periodic") == "startup":
                if getattr(broker, "_positions_snapshot_loaded", False):
                    audit_interval = float(getattr(params, "position_audit_interval", 0.0) or 0.0)
                    pending_trades = bool(getattr(broker, "_pending_trade_updates", ()))
                    open_orders_get = getattr(broker, "get_orders_open", None)
                    try:
                        open_orders = bool(open_orders_get()) if callable(open_orders_get) else True
                    except Exception:
                        open_orders = True
                    if audit_interval > 0 and not pending_trades and not open_orders:
                        add_refresh_deadline("_last_position_audit", "position_audit_interval")
                else:
                    add_refresh_deadline("_last_positions_refresh", "positions_refresh_interval")
            else:
                add_refresh_deadline("_last_account_refresh", "account_refresh_interval")
                add_refresh_deadline("_last_positions_refresh", "positions_refresh_interval")
                add_refresh_deadline("_last_open_orders_refresh", "open_orders_refresh_interval")

    order_info_get = getattr(broker, "_order_info_get", None)
    orders = getattr(broker, "orders", None)
    if callable(order_info_get) and orders is not None:
        now_ns = time.monotonic_ns()
        for order in tuple(orders.values()):
            alive = getattr(order, "alive", None)
            if not callable(alive) or not alive():
                continue
            if bool(order_info_get(order, "service_execution_recovery_managed", False)):
                continue
            deadline_keys = []
            cancel_triggered = bool(
                order_info_get(order, "execution_deadline_cancel_requested", False)
            )
            if not cancel_triggered:
                execution_deadline_get = getattr(broker, "_execution_deadline", None)
                if callable(execution_deadline_get):
                    try:
                        execution_deadline = execution_deadline_get(order)
                    except Exception:
                        execution_deadline = None
                else:
                    execution_deadline = None
                    for key in (
                        "execution_deadline_monotonic_ns",
                        "order_deadline_monotonic_ns",
                        "deadline_monotonic_ns",
                    ):
                        value = order_info_get(order, key)
                        if value in (None, ""):
                            continue
                        try:
                            execution_deadline = int(value)
                        except (TypeError, ValueError, OverflowError):
                            execution_deadline = None
                        break
                if execution_deadline is not None:
                    try:
                        deadline_ns = int(execution_deadline)
                    except (TypeError, ValueError, OverflowError):
                        deadline_ns = 0
                    if deadline_ns > 0:
                        remaining = max(0.0, (deadline_ns - now_ns) / 1_000_000_000.0)
                        if math.isfinite(remaining):
                            deadlines.append(remaining)
            if bool(order_info_get(order, "cancel_requested_remote", False)) and not bool(
                order_info_get(order, "cancel_deadline_unknown_marked", False)
            ):
                deadline_keys.append("cancel_deadline_monotonic_ns")
            if not bool(order_info_get(order, "reconcile_requested", False)):
                deadline_keys.append("reconcile_next_monotonic_ns")
            if not bool(order_info_get(order, "cancel_requested_remote", False)) and bool(
                order_info_get(order, "cancel_reconcile_confirmed_live", False)
            ):
                deadline_keys.append("cancel_retry_due_monotonic_ns")
            for key in deadline_keys:
                value = order_info_get(order, key)
                if value in (None, ""):
                    continue
                try:
                    deadline_ns = int(value)
                except (TypeError, ValueError, OverflowError):
                    continue
                if deadline_ns > 0:
                    remaining = max(0.0, (deadline_ns - now_ns) / 1_000_000_000.0)
                    if math.isfinite(remaining):
                        deadlines.append(remaining)

    return min(deadlines) if deadlines else None


def _cap_live_cohort_wait_for_broker(cohort_timeout, broker_timeout):
    """Bound broker maintenance waits without delaying a due cohort slot."""
    if broker_timeout is None:
        return cohort_timeout
    if cohort_timeout <= 0:
        return cohort_timeout
    if broker_timeout <= 0:
        return min(cohort_timeout, _LIVE_COHORT_BROKER_IDLE_POLL_SECONDS)
    return min(cohort_timeout, broker_timeout)


def _cleanup_live_bar_cohort_wakers(owner, waker, bindings):
    """Attempt every Store unbind and preserve any active engine exception."""
    active_error = sys.exc_info()[1]
    cleanup_errors = []
    for store, token in reversed(bindings):
        unregister = getattr(store, "_unregister_live_bar_event_waker", None)
        if callable(unregister):
            try:
                unregister(token)
            except Exception as cleanup_error:
                cleanup_errors.append(cleanup_error)
    if getattr(owner, "_live_bar_cohort_waker", None) is waker:
        owner._live_bar_cohort_waker = None
    if cleanup_errors:
        if active_error is None:
            raise cleanup_errors[0]
        for cleanup_error in cleanup_errors:
            logger.error(
                "Failed to unregister a live-bar cohort event waker",
                exc_info=(
                    type(cleanup_error),
                    cleanup_error,
                    cleanup_error.__traceback__,
                ),
            )


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
        cohort_waker = None
        cohort_waker_bindings = []
        try:
            # Sort data by time period
            datas = sorted(self.datas, key=lambda x: (x._timeframe, x._compression))
            # Other data
            datas1 = datas[1:]
            # Main data
            data0 = datas[0]
            live_bar_cohort = getattr(self, "_live_bar_cohort", None)
            if live_bar_cohort is not None:
                cohort_waker = _LiveBarCohortWake()
                self._live_bar_cohort_waker = cohort_waker
                registered_store_ids = set()
                for store in tuple(self.stores):
                    if id(store) in registered_store_ids:
                        continue
                    registered_store_ids.add(id(store))
                    register = getattr(store, "_register_live_bar_event_waker", None)
                    if callable(register):
                        token = register(cohort_waker.notify)
                        cohort_waker_bindings.append((store, token))
            # Cohort mode uses its injected causal UTC/monotonic clock and one
            # shared wait.  The regular qcheck clock uses process wall time.
            has_qcheck = not live_bar_cohort and any(d.p.qcheck for d in datas)
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
            if (
                not live_bar_cohort
                and single_data
                and not has_qcheck
                and single_default_haslivedata
            ):
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
                    logger.debug("runnext:200 ignored AttributeError")
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
                    if self._event_stop:
                        return

                if data0.notifs:
                    self._datanotify()
                return
            # Note: 'while True' (not 'while d0ret or d0ret is None') is intentional:
            # when d0ret becomes False, the else branch still runs _last() on feeds
            # and only breaks if no feed produces additional data.
            while True:
                # Take this before source collection. A provider callback that
                # arrives at any point in this iteration changes the generation
                # and defeats the later wait under the same condition lock.
                cohort_wake_generation = (
                    cohort_waker.snapshot() if cohort_waker is not None else None
                )
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
                cohort_wait = False
                cohort_terminal = False
                cohort_status = None
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
                if live_bar_cohort is not None:
                    clock = self.live_bar_cohort_clock
                    try:
                        now_monotonic_ns = clock.monotonic_ns()
                        source_time_utc = clock.utc_now()
                        if (
                            type(now_monotonic_ns) is not int
                            or now_monotonic_ns <= 0
                            or not isinstance(source_time_utc, datetime.datetime)
                            or source_time_utc.tzinfo is None
                            or source_time_utc.utcoffset() != datetime.timedelta(0)
                        ):
                            raise ValueError("live cohort clock returned an invalid UTC sample")
                        for data in self.datas:
                            data._cohort_collect_source(now_monotonic_ns)
                        prepared_result = live_bar_cohort.prepare_round(
                            now_monotonic_ns,
                            source_time_utc=source_time_utc,
                        )
                        cohort_status = prepared_result.status
                        if cohort_status == "READY":
                            prepared = prepared_result.prepared
                            if prepared is None:
                                raise RuntimeError("READY cohort result has no prepared batch")
                            envelopes = tuple(
                                prepared.envelope_for_feed(data) for data in self.datas
                            )
                            if any(envelope is None for envelope in envelopes):
                                raise RuntimeError(
                                    "prepared cohort does not cover every Cerebro feed"
                                )
                            staged_deliveries = []
                            line_checkpoints = []
                            batch_published = False
                            try:
                                # Stage every exact raw value set before the
                                # first normal feed.next() can advance a line.
                                for data, envelope in zip(self.datas, envelopes):
                                    staged_deliveries.append(
                                        data._prepare_live_bar_cohort_delivery(envelope)
                                    )
                                line_checkpoints = [
                                    _snapshot_live_cohort_feed_state(data) for data in self.datas
                                ]
                                for data, envelope, stage in zip(
                                    self.datas, envelopes, staged_deliveries
                                ):
                                    data._arm_live_bar_cohort_envelope(envelope, stage)
                                drets = [data.next(ticks=False) for data in datas]
                                if any(result is not True for result in drets):
                                    raise RuntimeError(
                                        "a prepared cohort member did not advance exactly once"
                                    )
                                for data, envelope, stage in zip(
                                    self.datas, envelopes, staged_deliveries
                                ):
                                    data._preflight_live_bar_cohort_delivery_commit(envelope, stage)
                                committed_batch = live_bar_cohort.record_delivery_batch(
                                    tuple(
                                        (data, envelope, stage.close_time)
                                        for data, envelope, stage in zip(
                                            self.datas, envelopes, staged_deliveries
                                        )
                                    )
                                )
                                batch_published = True
                                for data, envelope, stage in zip(
                                    self.datas, envelopes, staged_deliveries
                                ):
                                    data._commit_live_bar_cohort_delivery(envelope, stage)
                                batch = live_bar_cohort.current_batch()
                                if (
                                    batch is None
                                    or batch is not committed_batch
                                    or batch.status != "COMPLETE"
                                    or batch.batch_id != prepared.batch_id
                                    or batch.cohort_id != prepared.cohort_id
                                    or batch.close_time != prepared.close_time
                                    or len(batch.members) != len(envelopes)
                                ):
                                    raise RuntimeError(
                                        "Cerebro observed an incomplete cohort batch"
                                    )
                                for data, envelope in zip(self.datas, envelopes):
                                    receipt = batch.receipt_for_feed(data)
                                    if (
                                        receipt is None
                                        or receipt.envelope is not envelope
                                        or receipt.batch_id != prepared.batch_id
                                        or receipt.close_time != envelope.close_time
                                    ):
                                        raise RuntimeError(
                                            "completed cohort receipt does not match its feed"
                                        )
                            except Exception as delivery_error:
                                rollback_errors = []
                                if not batch_published:
                                    for data, checkpoint in zip(self.datas, line_checkpoints):
                                        rollback_errors.extend(
                                            _restore_live_cohort_feed_state(data, checkpoint)
                                        )
                                live_bar_cohort._freeze("engine_batch_delivery_failed")
                                for data in self.datas:
                                    abort = getattr(data, "_abort_live_bar_cohort_delivery", None)
                                    if callable(abort):
                                        abort()
                                    data._cohort_delivery_failed = True
                                if rollback_errors:
                                    raise RuntimeError(
                                        "cohort delivery failed and line rollback was incomplete"
                                    ) from delivery_error
                                raise
                            try:
                                # Feed line delivery is complete for every
                                # member before any bar notification callback.
                                for data, envelope in zip(self.datas, envelopes):
                                    data._dispatch_live_bar_cohort_envelope(envelope)
                            except Exception:
                                live_bar_cohort._freeze("engine_batch_delivery_failed")
                                raise
                        elif cohort_status in ("WAITING", "WAITING_AVAILABILITY", "NOT_DUE"):
                            drets = [None] * len(datas)
                            cohort_wait = True
                            if cohort_status == "WAITING" and all(
                                data._cohort_source_is_exhausted() for data in self.datas
                            ):
                                live_bar_cohort._freeze(
                                    "finite_source_exhausted_before_complete_batch"
                                )
                                cohort_status = "GAP_EOF"
                                cohort_terminal = True
                        elif cohort_status in ("GAP", "AVAILABILITY_TIMEOUT", "EXHAUSTED"):
                            drets = [None] * len(datas)
                            cohort_terminal = True
                        else:
                            raise RuntimeError(
                                "unsupported live cohort prepare status: %s" % cohort_status
                            )
                    except Exception:
                        if not live_bar_cohort.frozen:
                            live_bar_cohort._freeze("engine_cohort_round_failed")
                        for data in self.datas:
                            data._cohort_armed_envelope = None
                            data._cohort_delivery_failed = True
                        raise
                elif data0_direct_load is not None:
                    drets = (data0_direct_load(),)
                else:
                    drets = []
                if (
                    live_bar_cohort is None
                    and data0_direct_load is None
                    and newqcheck
                    and has_qcheck
                ):
                    qstart = datetime.datetime.now(UTC)
                    for d in datas:
                        qlapse = datetime.datetime.now(UTC) - qstart
                        d.do_qcheck(newqcheck, qlapse.total_seconds())
                        d_next = d.next(ticks=False)
                        drets.append(d_next)
                elif live_bar_cohort is None and data0_direct_load is None:
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

                if cohort_terminal:
                    break

                if cohort_wait:
                    # Keep broker polling and idle callbacks above, then wait
                    # until the earliest cohort or broker deadline. Provider
                    # callbacks use the same generation-checked engine condition.
                    clock = self.live_bar_cohort_clock
                    wait_decision = live_bar_cohort.next_wait_timeout(
                        clock.utc_now(), clock.monotonic_ns()
                    )
                    if wait_decision.status == "WAITING":
                        timeout = wait_decision.timeout_seconds
                        if timeout is not None:
                            timeout = float(timeout)
                            if not math.isfinite(timeout) or timeout < 0:
                                raise RuntimeError("live cohort returned an invalid wait timeout")
                            broker_timeout = _live_cohort_broker_timeout(broker)
                            timeout = _cap_live_cohort_wait_for_broker(timeout, broker_timeout)
                            if timeout > 0:
                                wait_interruptibly = getattr(clock, "wait_interruptibly", None)
                                if cohort_waker_bindings and callable(wait_interruptibly):

                                    def wait_for_event(
                                        wait_timeout,
                                        generation=cohort_wake_generation,
                                    ):
                                        wait_timeout = float(wait_timeout)
                                        if not math.isfinite(wait_timeout) or wait_timeout < 0:
                                            raise RuntimeError(
                                                "clock supplied an invalid event wait timeout"
                                            )
                                        return cohort_waker.wait(generation, wait_timeout)

                                    interrupted = wait_interruptibly(timeout, wait_for_event)
                                    if type(interrupted) is not bool:
                                        raise RuntimeError(
                                            "clock wait_interruptibly must return bool"
                                        )
                                else:
                                    # Legacy injected clocks retain their causal
                                    # wait behavior; event interruption is an
                                    # explicit optional clock capability.
                                    clock.wait(timeout)
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
        finally:
            _cleanup_live_bar_cohort_wakers(self, cohort_waker, cohort_waker_bindings)
