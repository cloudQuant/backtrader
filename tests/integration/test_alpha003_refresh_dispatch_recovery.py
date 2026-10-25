"""Exercise runner-owned dispatch recovery before and after a fresh query pass."""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading
import time

import pytest

from tests.unit import test_alpha003_simnow_runner as runner_fixtures
from tests.unit.stores import test_factor_execution_facts as facts_fixtures


RUNNER = runner_fixtures.RUNNER
UTC = timezone.utc


class _SourceClock:
    """Drive live bar/query time from the explicit synthetic source tape."""

    def __init__(self, event_times):
        self._times = tuple(event_times)
        self._index = 0
        self._scheduled = []
        self._now = self._times[0] - timedelta(seconds=65)
        self._lock = threading.RLock()

    def utc_now(self):
        with self._lock:
            return self._now

    def monotonic_ns(self):
        return time.monotonic_ns()

    def time_ns(self):
        return int(self.utc_now().timestamp() * 1_000_000_000)

    def time(self):
        return self.utc_now().timestamp()

    def wait(self, _timeout):
        return None

    def schedule_at(self, when, callback):
        if not isinstance(when, datetime) or when.tzinfo is None or not callable(callback):
            raise TypeError("scheduled source events need an aware time and callback")
        with self._lock:
            self._scheduled.append((when, callback))
            self._scheduled.sort(key=lambda item: item[0])
            ready = self._take_due_locked()
        self._dispatch(ready)

    def _take_due_locked(self):
        ready = []
        while self._scheduled and self._scheduled[0][0] <= self._now:
            _when, callback = self._scheduled.pop(0)
            ready.append(callback)
        return ready

    @staticmethod
    def _dispatch(callbacks):
        for callback in callbacks:
            callback()

    def advance(self, delta):
        with self._lock:
            self._now += delta
            now = self._now
            ready = self._take_due_locked()
        self._dispatch(ready)
        return now

    def wait_interruptibly(self, timeout_seconds, wait_for_event):
        if wait_for_event(0.0):
            return True
        with self._lock:
            while self._index < len(self._times) and self._times[self._index] <= self._now:
                self._index += 1
            next_bar = self._times[self._index] if self._index < len(self._times) else None
            next_provider = self._scheduled[0][0] if self._scheduled else None
            candidates = [item for item in (next_bar, next_provider) if item is not None]
            if candidates:
                next_event = min(candidates)
                self._now = max(self._now, next_event)
                if next_bar == next_event:
                    self._index += 1
                ready = self._take_due_locked()
                has_event = True
            else:
                ready = []
                has_event = False
        if not has_event:
            return wait_for_event(min(float(timeout_seconds), 0.01))
        self._dispatch(ready)
        return False

    def reset(self):
        with self._lock:
            self._index = 0
            self._scheduled.clear()
            self._now = self._times[0] - timedelta(seconds=65)


def _datetime_proxy(clock):
    real_datetime = datetime

    class _Meta(type):
        def __instancecheck__(cls, value):
            del cls
            return isinstance(value, real_datetime)

        def __getattr__(cls, name):
            del cls
            return getattr(real_datetime, name)

    class _DateTime(metaclass=_Meta):
        @classmethod
        def now(cls, tz=None):
            del cls
            value = clock.utc_now()
            return value.replace(tzinfo=None) if tz is None else value.astimezone(tz)

        @classmethod
        def utcnow(cls):
            del cls
            return clock.utc_now().replace(tzinfo=None)

        def __new__(cls, *args, **kwargs):
            del cls
            return real_datetime(*args, **kwargs)

    return _DateTime


def _source_bars(tape, plan):
    planned_closes = {minute.close_time for minute in plan["grid"].minutes}
    bars = defaultdict(deque)
    for source in tape["bars"]:
        end = datetime.fromisoformat(source["bucket_end"].replace("Z", "+00:00"))
        if end not in planned_closes:
            continue
        row = dict(source)
        for name in ("bucket_start", "bucket_end", "available_at"):
            row[name] = datetime.fromisoformat(row[name].replace("Z", "+00:00"))
        bars[row["instrument"]].append(row)
    event_times = tuple(
        sorted(
            row["available_at"] + timedelta(milliseconds=200)
            for rows in bars.values()
            for row in rows
        )
    )
    return bars, event_times


def test_run_live_scopes_dispatch_recovery_before_queries_and_replays_after_restart(
    tmp_path, monkeypatch
):
    """A DISPATCHING OPEN is reconciled before feeds run, then read-only replayed."""

    ctp_client_module = None
    for module_name in ("bt_api_ctp.ctp.client", "bt_api_py.ctp.client"):
        try:
            ctp_client_module = __import__(module_name, fromlist=["MdClient", "TraderClient"])
            break
        except ImportError:
            continue
    if ctp_client_module is None:
        pytest.skip("CTP SDK client module is unavailable")

    import backtrader.stores.btapistore as btapistore_module
    import backtrader.stores.execution_decision_journal as journal_module
    import backtrader.stores.factor_execution as factor_execution_module
    import backtrader.stores.factor_execution_facts as facts_module
    import backtrader.stores.registered_sim as registered_sim_module

    start_day = runner_fixtures.CURRENT_DAY
    decision_at = runner_fixtures.DECISION_AT
    account_scope = "alpha003-refresh-recovery-account"
    strategy_scope = "alpha003-refresh-recovery-strategy"
    logical_run_id = "alpha003-refresh-recovery-run"
    account_fingerprint = account_scope
    trading_day = start_day.strftime("%Y%m%d")

    config = runner_fixtures._base_config(tmp_path, "live")
    config_path, config, full_plan, tape, _quotes = runner_fixtures._write_source_inputs(
        tmp_path,
        config,
        current_day=start_day,
        decision_at=decision_at,
    )
    plan = dict(full_plan)
    plan["grid"] = replace(full_plan["grid"], minutes=full_plan["grid"].minutes[:50])
    bars_by_instrument, event_times = _source_bars(tape, plan)
    continuation_minutes = full_plan["grid"].minutes[50:100]
    assert len(continuation_minutes) == 50
    continuation_plan = dict(full_plan)
    continuation_plan["grid"] = replace(full_plan["grid"], minutes=continuation_minutes)
    continuation_bars, continuation_event_times = _source_bars(tape, continuation_plan)

    route_rows = [
        (
            plan["routes"][plan["product_by_target"][target]],
            plan["product_by_target"][target].exchange_id,
        )
        for target in plan["targets"]
    ]
    recovery_target = next(target for target in plan["targets"] if target.endswith(".A"))
    recovery_instrument = plan["routes"][plan["product_by_target"][recovery_target]]
    recovery_exchange = plan["product_by_target"][recovery_target].exchange_id
    terminal_order = {
        "OrderRef": "501",
        "OrderSysID": "sys-501",
        "InstrumentID": recovery_instrument,
        "ExchangeID": recovery_exchange,
        "TradingDay": trading_day,
        "FrontID": 4,
        "SessionID": 7,
        "OrderStatus": "5",
        "OrderSubmitStatus": "0",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotalOriginal": 1,
        "VolumeTraded": 0,
        "VolumeTotal": 1,
        "LimitPrice": 100.0,
    }
    query_rows = facts_fixtures._query_rows(orders=(terminal_order,))
    query_rows["instruments_result"] = [
        {
            "InstrumentID": instrument,
            "ExchangeID": exchange,
            "IsTrading": 1,
            "VolumeMultiple": 10,
            "PriceTick": 0.1,
            "LowerLimitPrice": 80,
            "UpperLimitPrice": 130,
        }
        for instrument, exchange in route_rows
    ]
    query_rows["instrument_margin_rate_result"] = [
        {
            "InstrumentID": instrument,
            "ExchangeID": exchange,
            "HedgeFlag": "1",
            "LongMarginRatioByMoney": "0.1",
            "LongMarginRatioByVolume": "0",
            "ShortMarginRatioByMoney": "0.1",
            "ShortMarginRatioByVolume": "0",
        }
        for instrument, exchange in route_rows
    ]

    journal_path = tmp_path / "dispatch-recovery.sqlite3"
    from backtrader.stores.execution_decision_journal import (
        ExecutionDecisionKey,
        ExecutionDecisionJournal,
        ExecutionIntentKey,
    )

    decision_key = ExecutionDecisionKey(
        account_scope=account_scope,
        strategy_scope=strategy_scope,
        logical_run_id=logical_run_id,
        cohort_id="alpha003:alpha003-one-minute-v1:1",
        close_time=decision_at.isoformat(),
        decision_kind="RECOVERY_SEED",
    )
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=recovery_instrument,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    original_identity = {
        "operation": "insert",
        "order_ref": "501",
        "instrument_id": recovery_instrument,
        "exchange_id": recovery_exchange,
        "trading_day": trading_day,
        "account_fingerprint": account_fingerprint,
        "connection_generation": 1,
        "front_id": 4,
        "session_id": 7,
        "order_sys_id": "sys-501",
    }
    seed = ExecutionDecisionJournal(journal_path)
    try:
        decision_record = seed.record_decision(
            decision_key,
            {
                "intent_economics": (
                    {
                        "quantity": "1",
                        "position_effect": "OPEN",
                        "exchange": recovery_exchange,
                    },
                )
            },
            intent_keys=(intent_key,),
        )
        intent_record = seed.prepare_intent(
            decision_record.decision_id,
            intent_key,
            {
                "quantity": "1",
                "side": "BUY",
                "position_effect": "OPEN",
                "exchange": recovery_exchange,
            },
            original_identity=original_identity,
        )
        claim = seed.claim_dispatch(intent_record.intent_id)
        assert claim is not None
        assert seed.intent(intent_record.intent_id).state == "DISPATCHING"
    finally:
        seed.close()

    clocks = []
    bar_maps = []
    api_instances = []
    bound_refresh_loops = []
    scope_events = []
    query_observations = []
    refresh_observations = []
    refresh_attempt_observations = []
    trade_receipt_observations = []
    terminal_receipt_observations = []
    reconciliation_trace = []
    projection_observations = []
    strategy_projection_calls = []
    barrier_threads = []
    active_scope = threading.local()
    hold_next_refresh_query = threading.Event()
    refresh_query_entered = threading.Event()
    refresh_query_release = threading.Event()
    busy_projection_seen = threading.Event()
    engine_turn_started = threading.Event()
    barrier_probe = {}

    def current_clock():
        return clocks[-1]

    class SyntheticMdClient:
        def __init__(self, **_kwargs):
            self._state_lock = threading.RLock()
            self._connection_generation = 2
            self.on_tick = None
            self.on_tick_with_generation = None
            self.on_disconnect = None
            self.on_disconnect_with_generation = None
            self.on_error = None
            self._subscribed = set()
            self._scheduled_bar_ids = set()
            self.stopped = False
            self._api = api_instances[-1]

        @property
        def connection_generation(self):
            return self._connection_generation

        def start(self, block=False):
            assert block is False

        def wait_ready(self, timeout=20):
            del timeout
            return True

        def subscribe(self, _instruments):
            instruments = tuple(str(item) for item in _instruments)
            self._subscribed.update(instruments)
            for instrument in instruments:
                rows = self._api._source_bars.get(instrument)
                if rows is None:
                    continue
                for row in tuple(rows):
                    bar_id = row["bar_id"]
                    if bar_id in self._scheduled_bar_ids:
                        continue
                    self._scheduled_bar_ids.add(bar_id)

                    def deliver(instrument=instrument, row=row):
                        tick_row = dict(row)
                        tick_row["event_time"] = row["bucket_end"] + timedelta(
                            seconds=2, milliseconds=10
                        )
                        self._dispatch_tick(
                            self._raw_tick(
                                instrument, row["exchange"], row["trading_day"], tick_row
                            )
                        )

                    current_clock().schedule_at(
                        row["available_at"] + timedelta(milliseconds=200), deliver
                    )
            return True

        @staticmethod
        def _raw_tick(instrument, exchange, day, source_row):
            event_time = (
                source_row.get("event_time")
                or source_row.get("bucket_end")
                or source_row["available_at"]
            )
            local = event_time.astimezone(timezone(timedelta(hours=8)))
            price = float(source_row.get("close", 100.0))
            return SimpleNamespace(
                InstrumentID=instrument,
                ExchangeID=exchange,
                LastPrice=price,
                Volume=0,
                BidPrice1=price - 0.1,
                AskPrice1=price + 0.1,
                BidVolume1=5,
                AskVolume1=6,
                OpenInterest=0.0,
                Turnover=0.0,
                TradingDay=day.replace("-", ""),
                ActionDay=local.strftime("%Y%m%d"),
                UpdateTime=local.strftime("%H:%M:%S"),
                UpdateMillisec=local.microsecond // 1000,
            )

        def _dispatch_tick(self, payload):
            with self._state_lock:
                callback = self.on_tick_with_generation
                generation = self._connection_generation
            if not callable(callback):
                raise AssertionError("production wrapper did not bind the generation tick callback")
            callback(payload, generation)
            return generation

        def schedule_winddown_quote(self, instrument, query_set_id, query_completed_at):
            api = self._api
            if instrument in api._winddown_scheduled_instruments:
                return
            route = next(
                ((route, exchange) for route, exchange in route_rows if route == instrument),
                None,
            )
            if route is None:
                raise AssertionError("winddown quote route was not configured")
            _route, exchange = route
            event_time = query_completed_at + timedelta(milliseconds=5)
            delivery_at = query_completed_at + timedelta(milliseconds=25)
            source_row = {
                "bucket_end": event_time,
                "available_at": delivery_at,
                "close": 100.0,
                "volume": 0,
            }
            api._winddown_scheduled_instruments.add(instrument)
            api._winddown_query_set_for[instrument] = query_set_id

            def deliver():
                generation = self._dispatch_tick(
                    self._raw_tick(instrument, exchange, trading_day, source_row)
                )
                api.winddown_tick_observations.append((instrument, query_set_id, generation))

            current_clock().schedule_at(delivery_at, deliver)

        def stop(self):
            self.stopped = True

    class SyntheticTraderClient(facts_fixtures._ProviderLeaves):
        def __init__(self, **_kwargs):
            super().__init__(query_rows=query_rows, query_time=current_clock().utc_now())
            self.trader_client._account_fingerprint = account_fingerprint
            self.trader_client._connection_generation = 2
            self.trader_client._trading_day = trading_day
            self.trader_client.is_ready = True
            self.trader_client.is_trading_ready = True
            self._account_fingerprint = account_fingerprint
            self._connection_generation = 2
            self._trading_day = trading_day
            self.is_ready = True
            self.is_trading_ready = True
            self.is_read_only_ready = True
            self._front_id = 4
            self._session_id = 7
            self.stopped = False

        def start(self, block=False):
            assert block is False

        def wait_ready(self, timeout=20):
            del timeout
            return True

        def stop(self):
            self.stopped = True

        def get_query_session_scope(self):
            return self.trader_client.get_query_session_scope()

        def get_session_state(self):
            state = self.trader_client.get_session_state()
            state.update(
                front_id=self._front_id,
                session_id=self._session_id,
                read_only_ready=True,
                trading_ready=True,
            )
            return state

        def get_execution_gate_state(self):
            return self.trader_client.get_execution_gate_state()

        def query_account(self, timeout=5):
            del timeout
            rows = query_rows.get("account_result", ())
            return dict(rows[0]) if rows else None

        def query_positions(self, timeout=5):
            del timeout
            return [dict(row) for row in query_rows.get("positions_result", ())]

        def _query_family(self, family, request_type, **filters):
            self.query_rows = dict(query_rows)
            current_clock().advance(timedelta(milliseconds=1))
            started = current_clock().utc_now()
            self.query_time = started + timedelta(milliseconds=3)
            query_observations.append(
                {
                    "family": family,
                    "started_at": started,
                    "inside_recovery_scope": getattr(active_scope, "active", False),
                    "thread_id": threading.get_ident(),
                }
            )
            if hold_next_refresh_query.is_set() and not barrier_probe.get("claimed"):
                barrier_probe["claimed"] = True
                barrier_probe["query_started_at"] = time.monotonic()
                refresh_query_entered.set()
                if not refresh_query_release.wait(barrier_timeout_seconds):
                    barrier_probe["query_release_timeout"] = True
            result = super()._query_family(family, request_type, **filters)
            current_clock().advance(timedelta(milliseconds=3))
            return result

    monkeypatch.setattr(ctp_client_module, "MdClient", SyntheticMdClient)
    monkeypatch.setattr(ctp_client_module, "TraderClient", SyntheticTraderClient)
    CtpClientWrapper = btapistore_module._create_ctp_wrapper_class()

    class BarTapeWrapper(CtpClientWrapper):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._source_bars = bar_maps[-1]
            self._winddown_scheduled_instruments = set()
            self._winddown_query_set_for = {}
            self.winddown_tick_observations = []
            self.stopped = False
            api_instances.append(self)

        def poll_bar(self, instrument):
            rows = self._source_bars.get(instrument)
            if not rows or rows[0]["available_at"] > current_clock().utc_now():
                return None
            return rows.popleft()

        def stop(self, timeout=None):
            result = super().stop(timeout=timeout)
            self.stopped = True
            return result

        def disconnect(self):
            result = super().disconnect()
            self.stopped = True
            return result

    original_factory = registered_sim_module._make_api_factory
    monkeypatch.setattr(
        registered_sim_module,
        "_make_api_factory",
        lambda allow_writes, history_limit, terminal_limit, _api_cls: original_factory(
            allow_writes, history_limit, terminal_limit, BarTapeWrapper
        ),
    )
    first_bar = tape["bars"][0]
    store_config = {
        "md_front": "tcp://127.0.0.1:1",
        "td_front": "tcp://127.0.0.1:2",
        "broker_id": "synthetic-broker",
        "investor_id": account_fingerprint,
        "password": "synthetic-only",
    }
    api_kwargs = {
        "live_tick_provenance": {
            "clock_domain_id": first_bar["clock_domain_id"],
            "rules_hash": "a" * 64,
            "session_segment": first_bar["session_segment"],
        }
    }
    monkeypatch.setattr(RUNNER, "_live_env_config", lambda _config: (store_config, api_kwargs))
    monkeypatch.setattr(RUNNER, "RunnerWallClock", lambda: current_clock())

    real_datetime_proxy = _datetime_proxy
    original_scope = factor_execution_module.FactorExecutionCoordinator.terminal_recovery_scope
    original_bind_strategy = RUNNER.QueryRefreshLoop.bind_strategy
    original_refresh = facts_module.refresh_factor_execution_queries
    original_project_facts = facts_module.project_factor_execution_facts
    original_trade_reconcile = (
        factor_execution_module.FactorExecutionCoordinator.reconcile_trade_observations
    )
    original_terminal_reconcile = (
        factor_execution_module.FactorExecutionCoordinator.reconcile_terminal_order_observations
    )

    @contextmanager
    def traced_scope(coordinator, *, timeout_seconds=5.0):
        with original_scope(coordinator, timeout_seconds=timeout_seconds) as started_at:
            scope_events.append(("enter", started_at, threading.get_ident()))
            active_scope.active = True
            active_scope.started_at = started_at
            current_clock().advance(timedelta(milliseconds=1))
            try:
                yield started_at
            finally:
                active_scope.active = False
                scope_events.append(("exit", current_clock().utc_now(), threading.get_ident()))

    def capture_strategy(loop, strategy):
        result = original_bind_strategy(loop, strategy)
        bound_refresh_loops.append((loop, strategy))
        original_next = strategy.next
        original_notify_idle = strategy.notify_idle

        def serialized_next(*args, **kwargs):
            engine_turn_started.set()
            started = time.monotonic()
            thread_id = threading.get_ident()
            before = sum(item["thread_id"] == thread_id for item in strategy_projection_calls)
            if hold_next_refresh_query.is_set() and not barrier_probe.get(
                "engine_turn_query_waited"
            ):
                barrier_probe["engine_turn_query_waited"] = True
                barrier_probe["engine_query_ready"] = refresh_query_entered.wait(
                    barrier_timeout_seconds
                )
            result = original_next(*args, **kwargs)
            if strategy.last_execution_block_reason == "EXECUTION_FACT_REFRESH_IN_PROGRESS":
                after = sum(item["thread_id"] == thread_id for item in strategy_projection_calls)
                projection_observations.append(
                    {
                        "source": "next",
                        "elapsed_seconds": time.monotonic() - started,
                        "facts_cleared": strategy.last_execution_facts is None,
                        "projection_calls": after - before,
                        "query_held": (
                            refresh_query_entered.is_set() and not refresh_query_release.is_set()
                        ),
                    }
                )
                busy_projection_seen.set()
            return result

        def serialized_notify_idle(*args, **kwargs):
            engine_turn_started.set()
            started = time.monotonic()
            thread_id = threading.get_ident()
            before = sum(item["thread_id"] == thread_id for item in strategy_projection_calls)
            result = original_notify_idle(*args, **kwargs)
            if strategy.last_execution_block_reason == "EXECUTION_FACT_REFRESH_IN_PROGRESS":
                after = sum(item["thread_id"] == thread_id for item in strategy_projection_calls)
                projection_observations.append(
                    {
                        "source": "notify_idle",
                        "elapsed_seconds": time.monotonic() - started,
                        "facts_cleared": strategy.last_execution_facts is None,
                        "projection_calls": after - before,
                        "query_held": (
                            refresh_query_entered.is_set() and not refresh_query_release.is_set()
                        ),
                    }
                )
                busy_projection_seen.set()
            return result

        strategy.next = serialized_next
        strategy.notify_idle = serialized_notify_idle
        store = getattr(getattr(strategy, "broker", None), "store", None)
        original_poll_tick = getattr(store, "poll_tick", None)
        if callable(original_poll_tick):

            def poll_tick_and_retire_winddown(dataname):
                tick = original_poll_tick(dataname)
                api = api_instances[-1] if api_instances else None
                if tick is not None and api is not None:
                    if dataname in api._winddown_query_set_for:
                        api._winddown_query_set_for.pop(dataname, None)
                        api._winddown_scheduled_instruments.discard(dataname)
                return tick

            store.poll_tick = poll_tick_and_retire_winddown
        return result

    def traced_refresh(*args, **kwargs):
        receipt = original_refresh(*args, **kwargs)
        refresh_observations.append(
            {
                "receipt": receipt,
                "inside_recovery_scope": getattr(active_scope, "active", False),
                "thread_id": threading.get_ident(),
            }
        )
        api = api_instances[-1] if api_instances else None
        query_set = getattr(receipt, "query_set", None)
        if (
            api is not None
            and query_set is not None
            and not getattr(receipt, "blockers", ())
            and not getattr(receipt, "pending_families", ())
            and getattr(receipt, "cancelled", False) is False
            and getattr(receipt, "deadline_reached", False) is False
            and all(not rows for rows in api._source_bars.values())
            and api.md_client is not None
        ):
            for instrument, _exchange in route_rows:
                api.md_client.schedule_winddown_quote(
                    instrument, query_set.query_set_id, query_set.completed_at_utc
                )
        return receipt

    def traced_project_facts(*args, **kwargs):
        strategy_projection_calls.append(
            {"thread_id": threading.get_ident(), "at": time.monotonic()}
        )
        return original_project_facts(*args, **kwargs)

    original_refresh_once = RUNNER.QueryRefreshLoop.refresh_once
    original_start = RUNNER.QueryRefreshLoop.start
    original_reconcile_all = RUNNER.QueryRefreshLoop._reconcile_all
    original_reconcile_dated = RUNNER.QueryRefreshLoop._reconcile_dated_trades

    def traced_refresh_once(loop):
        if barrier_probe.get("hold_background_until_engine") and not barrier_probe.get(
            "background_refresh_started"
        ):
            barrier_probe["background_refresh_started"] = True
            barrier_probe["engine_turn_started"] = engine_turn_started.wait(barrier_timeout_seconds)
        try:
            receipt = original_refresh_once(loop)
        except Exception as error:
            refresh_attempt_observations.append(
                {
                    "outcome": "ERROR",
                    "error_code": loop._execution_error_code(error),
                    "receipt_id": getattr(
                        getattr(loop.last_receipt, "query_set", None), "query_set_id", None
                    ),
                    "thread_id": threading.get_ident(),
                }
            )
            raise
        refresh_attempt_observations.append(
            {
                "outcome": "RETURNED",
                "error_code": loop.last_error_code,
                "receipt_id": getattr(getattr(receipt, "query_set", None), "query_set_id", None),
                "thread_id": threading.get_ident(),
            }
        )
        return receipt

    def traced_start(loop):
        if barrier_probe.get("armed"):
            return original_start(loop)
        barrier_probe["armed"] = True
        barrier_probe["hold_background_until_engine"] = True
        hold_next_refresh_query.set()

        def release_after_engine_busy_read():
            entered = refresh_query_entered.wait(barrier_timeout_seconds)
            barrier_probe["query_entered"] = entered
            if not entered:
                refresh_query_release.set()
                return
            saw_busy = busy_projection_seen.wait(barrier_timeout_seconds)
            barrier_probe["busy_projection_seen"] = saw_busy
            barrier_probe["released_after_busy"] = saw_busy
            barrier_probe["release_elapsed_seconds"] = (
                time.monotonic() - barrier_probe["query_started_at"]
            )
            refresh_query_release.set()

        release_thread = threading.Thread(
            target=release_after_engine_busy_read,
            name="alpha003-refresh-projection-barrier",
            daemon=True,
        )
        barrier_threads.append(release_thread)
        release_thread.start()
        original_start(loop)

    def traced_reconcile_all(
        method,
        facts,
        allowed_statuses,
        label,
        *,
        refresh_receipt=None,
        diagnostic_sink=None,
    ):
        def traced_page_method(*args, **kwargs):
            page = method(*args, **kwargs)
            reconciliation_trace.append(
                {
                    "label": label,
                    "outcome": "PAGE",
                    "query_set_id": facts.query_set_id,
                    "inside_recovery_scope": getattr(active_scope, "active", False),
                    "statuses": tuple(
                        (
                            getattr(item, "status", None),
                            getattr(item, "blocker_code", None),
                        )
                        for item in page.items
                    ),
                }
            )
            return page

        try:
            result = original_reconcile_all(
                traced_page_method,
                facts,
                allowed_statuses,
                label,
                refresh_receipt=refresh_receipt,
                diagnostic_sink=diagnostic_sink,
            )
        except Exception as error:
            reconciliation_trace.append(
                {
                    "label": label,
                    "outcome": "ERROR",
                    "error_code": RUNNER.QueryRefreshLoop._execution_error_code(error),
                    "query_set_id": facts.query_set_id,
                    "inside_recovery_scope": getattr(active_scope, "active", False),
                    "diagnostic_sink": (
                        tuple(diagnostic_sink) if type(diagnostic_sink) is list else None
                    ),
                    "receipt_query_set_id": (
                        None if refresh_receipt is None else refresh_receipt.query_set.query_set_id
                    ),
                }
            )
            raise
        reconciliation_trace.append(
            {
                "label": label,
                "outcome": "COMPLETE",
                "query_set_id": facts.query_set_id,
                "receipt_query_set_id": (
                    None if refresh_receipt is None else refresh_receipt.query_set.query_set_id
                ),
            }
        )
        return result

    def traced_reconcile_dated(loop, facts, *, refresh_receipt, diagnostic_sink=None):
        try:
            result = original_reconcile_dated(
                loop,
                facts,
                refresh_receipt=refresh_receipt,
                diagnostic_sink=diagnostic_sink,
            )
        except Exception as error:
            reconciliation_trace.append(
                {
                    "label": "dated_trades",
                    "outcome": "ERROR",
                    "error_code": loop._execution_error_code(error),
                    "query_set_id": facts.query_set_id,
                    "receipt_query_set_id": (
                        None if refresh_receipt is None else refresh_receipt.query_set.query_set_id
                    ),
                }
            )
            raise
        reconciliation_trace.append(
            {
                "label": "dated_trades",
                "outcome": "COMPLETE",
                "query_set_id": facts.query_set_id,
                "receipt_query_set_id": refresh_receipt.query_set.query_set_id,
            }
        )
        return result

    def traced_trade_reconcile(coordinator, facts, **kwargs):
        receipt = kwargs.get("refresh_receipt")
        trade_receipt_observations.append(
            (facts.query_set_id, receipt.query_set.query_set_id, receipt)
        )
        return original_trade_reconcile(coordinator, facts, **kwargs)

    def traced_terminal_reconcile(coordinator, facts, **kwargs):
        receipt = kwargs.get("refresh_receipt")
        terminal_receipt_observations.append(
            (
                facts.query_set_id,
                None if receipt is None else receipt.query_set.query_set_id,
                receipt,
                getattr(active_scope, "active", False),
            )
        )
        return original_terminal_reconcile(coordinator, facts, **kwargs)

    monkeypatch.setattr(
        factor_execution_module.FactorExecutionCoordinator,
        "terminal_recovery_scope",
        traced_scope,
    )
    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "bind_strategy", capture_strategy)
    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "refresh_once", traced_refresh_once)
    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "start", traced_start)
    monkeypatch.setattr(
        RUNNER.QueryRefreshLoop, "_reconcile_all", staticmethod(traced_reconcile_all)
    )
    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "_reconcile_dated_trades", traced_reconcile_dated)
    monkeypatch.setattr(facts_module, "refresh_factor_execution_queries", traced_refresh)
    monkeypatch.setattr(facts_module, "project_factor_execution_facts", traced_project_facts)
    monkeypatch.setattr(
        factor_execution_module.FactorExecutionCoordinator,
        "reconcile_trade_observations",
        traced_trade_reconcile,
    )
    monkeypatch.setattr(
        factor_execution_module.FactorExecutionCoordinator,
        "reconcile_terminal_order_observations",
        traced_terminal_reconcile,
    )

    config["live"].update(
        account_scope=account_scope,
        strategy_scope=strategy_scope,
        logical_run_id=logical_run_id,
        journal_path=str(journal_path),
        ready_timeout_seconds=5.0,
        refresh_timeout_seconds=2.0,
        refresh_overall_timeout_seconds=10.0,
        refresh_interval_seconds=60.0,
        quote_max_age_seconds=60.0,
        query_max_age_seconds=7200.0,
        shutdown_grace_seconds=5.0,
        allow_writes=False,
        arm_templates=[],
    )
    barrier_timeout_seconds = float(config["live"]["refresh_timeout_seconds"])
    config["cohort"].update(
        max_pending_slots=1,
        max_live_bar_age_seconds=30.0,
        max_future_skew_seconds=0.0,
    )
    config["risk"]["run_end_policy"] = "CLOSE_ALL"
    config["output"]["decision_tape_max_bytes"] = 50_000_000

    def run_one(run_number):
        run_plan = plan if run_number == 1 else continuation_plan
        run_source_bars = bars_by_instrument if run_number == 1 else continuation_bars
        run_event_times = event_times if run_number == 1 else continuation_event_times
        clock = _SourceClock(run_event_times)
        clocks.append(clock)
        run_bars = defaultdict(deque)
        for instrument, rows in run_source_bars.items():
            run_bars[instrument].extend(dict(row) for row in rows)
        bar_maps.append(run_bars)
        config["output"]["decision_tape_path"] = str(tmp_path / f"tape-{run_number}.jsonl")
        config_path.write_text(
            runner_fixtures.yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        monkeypatch.setattr(
            journal_module, "time", SimpleNamespace(time_ns=clock.time_ns, monotonic=time.monotonic)
        )
        monkeypatch.setattr(
            btapistore_module,
            "time",
            SimpleNamespace(
                time=clock.time,
                monotonic=time.monotonic,
                monotonic_ns=clock.monotonic_ns,
                sleep=time.sleep,
            ),
        )
        date_proxy = real_datetime_proxy(clock)
        monkeypatch.setattr(facts_module, "datetime", date_proxy)
        monkeypatch.setattr(factor_execution_module, "datetime", date_proxy)
        monkeypatch.setattr(RUNNER, "datetime", date_proxy)
        try:
            return RUNNER.run_live(
                config,
                config_path,
                run_plan,
                "native",
                1,
                decision=SimpleNamespace(effective_tier="shadow"),
                allow_write_flag=False,
            )
        except BaseException as error:
            diagnostic = None
            if bound_refresh_loops:
                loop, strategy = bound_refresh_loops[-1]
                diagnostic = {
                    "error": type(error).__name__,
                    "strategy_shutdown": strategy.shutdown_blocker,
                    "strategy_ready": strategy.shutdown_ready,
                    "refresh_status": loop.shutdown_status,
                    "refresh_blocker": loop.shutdown_blocker,
                    "refresh_error": loop.last_error_code,
                    "reconciliation_blockers": loop.last_reconciliation_blockers,
                    "facts_read_only_ready": (
                        None
                        if loop.last_facts is None
                        else loop.last_facts.read_only_reconciliation_ready
                    ),
                    "facts_blockers": (
                        None if loop.last_facts is None else loop.last_facts.blockers[:20]
                    ),
                    "query_count": len(query_observations),
                    "refresh_count": len(refresh_observations),
                    "refresh_attempts": tuple(refresh_attempt_observations[-4:]),
                    "reconciliation_trace": tuple(reconciliation_trace[-8:]),
                    "projection_observations": tuple(projection_observations),
                    "barrier_probe": dict(barrier_probe),
                    "tick_scheduled": len(
                        getattr(api_instances[-1].md_client, "_scheduled_bar_ids", ())
                    ),
                }
            raise AssertionError(f"run_live failed; diagnostics={diagnostic!r}") from error

    first_result = run_one(1)
    assert first_result["status"] == "LIVE_RUN_COMPLETE", first_result
    assert first_result["write_mode"] is False
    assert first_result["cleanup_complete"] is True
    assert len(api_instances) == 1
    assert api_instances[0].stopped is True
    for barrier_thread in barrier_threads:
        barrier_thread.join(timeout=1.0)
        assert not barrier_thread.is_alive()
    assert barrier_probe.get("query_entered") is True, barrier_probe
    assert barrier_probe.get("busy_projection_seen") is True, barrier_probe
    assert barrier_probe.get("released_after_busy") is True, barrier_probe
    assert projection_observations, projection_observations
    assert any(item["query_held"] for item in projection_observations), projection_observations
    assert all(item["facts_cleared"] for item in projection_observations)
    assert all(item["projection_calls"] == 0 for item in projection_observations)
    assert all(item["elapsed_seconds"] < 0.25 for item in projection_observations)

    recovered = ExecutionDecisionJournal(journal_path)
    try:
        resolved = recovered.intent(intent_record.intent_id)
        assert resolved is not None
        assert resolved.state == "KNOWN"
        assert resolved.dispatch_state is None
        assert resolved.provider_identity is None
        assert resolved.outcome_code is None
        assert recovered.instrument_resolution(intent_record.intent_id) is not None
        assert recovered.active_instrument_owner(account_scope, recovery_instrument) is None
    finally:
        recovered.close()

    assert len(scope_events) == 2, scope_events
    assert scope_events[0][0] == "enter" and scope_events[1][0] == "exit"
    recovery_thread = scope_events[0][2]
    assert scope_events[1][2] == recovery_thread
    first_run_refreshes = [
        item for item in refresh_observations if item["thread_id"] == recovery_thread
    ]
    assert len(first_run_refreshes) >= 2, first_run_refreshes
    assert all(item["inside_recovery_scope"] for item in first_run_refreshes[:2])
    scoped_queries = [item for item in query_observations if item["inside_recovery_scope"]]
    assert scoped_queries
    assert all(item["thread_id"] == recovery_thread for item in scoped_queries)
    assert all(item["started_at"] >= scope_events[0][1] for item in scoped_queries)
    assert all(
        facts_id == receipt_id and receipt is not None
        for facts_id, receipt_id, receipt in trade_receipt_observations[:1]
    )
    first_terminal = terminal_receipt_observations[0]
    assert first_terminal[0] == first_terminal[1]
    assert first_terminal[2] is refresh_observations[1]["receipt"]
    assert first_terminal[3] is True
    assert first_result["strategy_order_events"]["events"] == []
    assert reconciliation_trace, reconciliation_trace

    # A fresh ordinary Runner/Store/Broker over the same durable journal must
    # read the exact stored no-fill proof without demanding another recovery
    # scope or recreating the historical Backtrader Order.
    second_result = run_one(2)
    assert second_result["status"] == "LIVE_RUN_COMPLETE", second_result
    assert second_result["write_mode"] is False
    assert second_result["cleanup_complete"] is True
    assert len(api_instances) == 2
    assert api_instances[1].stopped is True
    assert len(scope_events) == 2, scope_events
    second_terminal = terminal_receipt_observations[-1]
    assert second_terminal[0] == second_terminal[1]
    assert second_terminal[3] is False
    assert second_result["strategy_order_events"]["events"] == []

    reopened = ExecutionDecisionJournal(journal_path)
    try:
        final_intent = reopened.intent(intent_record.intent_id)
        assert final_intent is not None and final_intent.state == "KNOWN"
        assert final_intent.dispatch_state is None
        assert final_intent.provider_identity is None
        assert final_intent.outcome_code is None
        assert reopened.active_instrument_owner(account_scope, recovery_instrument) is None
    finally:
        reopened.close()
