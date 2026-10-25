"""Source-backed ordinary Alpha003 live order path over RegisteredSim.

Only provider SDK leaves and the bounded source bar/tick tape are synthetic.
The 028 Runner, Alpha003 Strategy, cohort, Broker, Store, query refresh,
execution coordinator, and journal are the production implementations.
"""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import threading
import time

import pytest

from tests.unit import test_alpha003_simnow_runner as runner_fixtures
from tests.unit.stores import test_factor_execution_facts as facts_fixtures


RUNNER = runner_fixtures.RUNNER
UTC = timezone.utc


def test_alpha003_live_strategy_submits_and_cancels_through_registered_sim(tmp_path, monkeypatch):
    """Ordinary Alpha003 decisions traverse real Store/Broker/query lifecycles."""
    import backtrader.stores.execution_decision_journal as journal_module
    import backtrader.stores.registered_sim as registered_sim_module
    import backtrader.brokers.btapibroker as broker_module
    import backtrader.stores.factor_execution as factor_execution_module
    import backtrader.stores.factor_position_book as factor_position_book_module

    start_day = runner_fixtures.CURRENT_DAY
    decision_at = runner_fixtures.DECISION_AT
    config = runner_fixtures._base_config(tmp_path, "live")
    config_path, config, full_plan, tape, _quotes = runner_fixtures._write_source_inputs(
        tmp_path,
        config,
        current_day=start_day,
        decision_at=decision_at,
    )

    # Fifty actual factor bars are enough to reach the fixture's first Alpha003
    # target while keeping this order-chain regression small.
    minute_count = 50
    plan = dict(full_plan)
    plan["grid"] = replace(full_plan["grid"], minutes=full_plan["grid"].minutes[:minute_count])
    planned_closes = {minute.close_time for minute in plan["grid"].minutes}
    bars_by_instrument = defaultdict(deque)

    def refill_bars():
        for source in tape["bars"]:
            end = datetime.fromisoformat(source["bucket_end"].replace("Z", "+00:00"))
            if end not in planned_closes:
                continue
            event = dict(source)
            for name in ("bucket_start", "bucket_end", "available_at"):
                event[name] = datetime.fromisoformat(event[name].replace("Z", "+00:00"))
            bars_by_instrument[event["instrument"]].append(event)

    refill_bars()

    def make_query_rows():
        rows = facts_fixtures._query_rows()
        rows["instruments_result"] = [
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
        rows["instrument_margin_rate_result"] = [
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
        return rows

    route_rows = [
        (
            plan["routes"][plan["product_by_target"][target]],
            plan["product_by_target"][target].exchange_id,
        )
        for target in plan["targets"]
    ]
    query_rows = make_query_rows()

    event_times = tuple(
        sorted(
            {
                event["available_at"] + timedelta(milliseconds=200)
                for rows in bars_by_instrument.values()
                for event in rows
            }
        )
    )

    class SourceClock:
        """UTC follows explicit bar availability; monotonic remains real."""

        def __init__(self, times):
            self._times = tuple(times)
            self._index = 0
            self._scheduled = []
            # Keep the first close inside the Runner's cohort window; its
            # bucket begins about one minute before event availability.
            self._now = self._times[0] - timedelta(seconds=65)
            self._lock = threading.RLock()

        def utc_now(self):
            with self._lock:
                return self._now

        def monotonic_ns(self):
            return time.monotonic_ns()

        def time(self):
            return self.utc_now().timestamp()

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

        def reset(self, times):
            with self._lock:
                self._times = tuple(times)
                self._index = 0
                self._scheduled.clear()
                self._now = self._times[0] - timedelta(seconds=65)

        def time_ns(self):
            return int(self.utc_now().timestamp() * 1_000_000_000)

        def wait(self, timeout_seconds):
            del timeout_seconds

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
                has_event = bool(candidates)
                if not has_event:
                    ready = []
            if not has_event:
                return wait_for_event(min(float(timeout_seconds), 0.01))
            self._dispatch(ready)
            return False

    clock = SourceClock(event_times)
    refresh_condition = threading.Condition()
    # Keep the ordinary Strategy projection and the real refresh/publication
    # transaction on one deterministic fake-provider turn.  SourceClock's
    # lock protects only its timestamp and cannot protect the query-set
    # receipt while QueryRefreshLoop temporarily invalidates it.
    fact_turn_lock = threading.RLock()
    refresh_state = {"started": 0, "completed": 0, "errors": []}
    refresh_receipts = []
    api_instances = []
    fill_timeline = []

    def note_fill_event(kind, **facts):
        if len(fill_timeline) >= 512 or not api_instances or api_instances[-1]._phase != 1:
            return
        fill_timeline.append(
            {
                "sequence": len(fill_timeline),
                "kind": kind,
                "source_time": clock.utc_now().isoformat(),
                "monotonic_ns": time.monotonic_ns(),
                **facts,
            }
        )

    store_write_calls = []
    broker_rejections = []
    reconciliation_observations = []
    dated_page_failure_recorded = {"value": False}
    broker_position_observations = []
    book_position_observations = []
    broker_update_observations = []
    terminal_position_trace = {
        "next_sequence": 0,
        "records": [],
        "record_indexes": {},
        "call_order": [],
        "dropped_unique_inputs": 0,
        "dropped_call_order": 0,
        "observer_errors": 0,
        "first_mismatch": None,
        "last_mismatch": None,
        "first_mismatch_after_broker_update": None,
        "last_broker_update": None,
    }
    active_terminal_observations = []
    terminal_position_event_lock = threading.Lock()

    original_terminal_reconcile = (
        factor_execution_module.FactorExecutionCoordinator.reconcile_terminal_order_observations
    )
    original_one_terminal_reconcile = (
        factor_execution_module.FactorExecutionCoordinator._reconcile_one_terminal_order
    )
    original_terminal_position_consistent = factor_execution_module._terminal_position_consistent

    def begin_terminal_position_event():
        with terminal_position_event_lock:
            terminal_position_trace["next_sequence"] += 1
            return (
                terminal_position_trace["next_sequence"],
                terminal_position_trace["last_broker_update"],
            )

    def record_broker_update_event(event):
        with terminal_position_event_lock:
            terminal_position_trace["next_sequence"] += 1
            event["sequence"] = terminal_position_trace["next_sequence"]
            terminal_position_trace["last_broker_update"] = event
            return event["sequence"]

    def diagnostic_value(value):
        return {
            "type": "{}.{}".format(type(value).__module__, type(value).__qualname__),
            "value": repr(value),
        }

    def terminal_position_inputs(position, facts, observation):
        if position is None:
            return None
        broker_quantity = getattr(position, "broker_quantity", None)
        long_quantity = getattr(position, "long_quantity", None)
        short_quantity = getattr(position, "short_quantity", None)
        broker_is_decimal = isinstance(broker_quantity, Decimal)
        long_is_decimal = isinstance(long_quantity, Decimal)
        short_is_decimal = isinstance(short_quantity, Decimal)
        broker_is_finite = broker_is_decimal and broker_quantity.is_finite()
        long_is_finite = long_is_decimal and long_quantity.is_finite()
        short_is_finite = short_is_decimal and short_quantity.is_finite()
        long_nonnegative = long_is_finite and long_quantity >= 0
        short_nonnegative = short_is_finite and short_quantity >= 0
        sides_consistent = bool(
            long_is_finite and short_is_finite and not (long_quantity > 0 and short_quantity > 0)
        )
        net_quantity_matches = bool(
            broker_is_finite
            and long_is_finite
            and short_is_finite
            and broker_quantity == long_quantity - short_quantity
        )
        try:
            same_time = bool(
                factor_execution_module._same_time(
                    getattr(position, "available_at", None),
                    getattr(facts, "available_at", None),
                )
            )
        except Exception:
            same_time = None
        checks = {
            "snapshot_matches": getattr(position, "snapshot_id", None)
            == getattr(facts, "snapshot_id", None),
            "available_at_matches": same_time,
            "broker_is_finite_decimal": broker_is_finite,
            "long_is_finite_decimal": long_is_finite,
            "long_is_nonnegative": long_nonnegative,
            "short_is_finite_decimal": short_is_finite,
            "short_is_nonnegative": short_nonnegative,
            "sides_are_consistent": sides_consistent,
            "net_quantity_matches_sides": net_quantity_matches,
        }
        comparison_result = (
            all(value is True for value in checks.values()) if None not in checks.values() else None
        )
        return {
            "target": {
                "target_id": getattr(position, "target_id", None),
                "instrument": getattr(position, "instrument", None),
                "exchange": getattr(position, "exchange", None),
                "observation_id": getattr(observation, "observation_id", None),
                "observation_instrument": getattr(observation, "instrument", None),
                "observation_exchange": getattr(observation, "exchange", None),
            },
            "snapshot": {
                "position": diagnostic_value(getattr(position, "snapshot_id", None)),
                "facts": diagnostic_value(getattr(facts, "snapshot_id", None)),
            },
            "available_at": {
                "position": diagnostic_value(getattr(position, "available_at", None)),
                "facts": diagnostic_value(getattr(facts, "available_at", None)),
            },
            "quantities": {
                "broker": diagnostic_value(broker_quantity),
                "long": diagnostic_value(long_quantity),
                "short": diagnostic_value(short_quantity),
            },
            "checks": checks,
            "comparison_result": comparison_result,
        }

    def record_terminal_position_check(
        *,
        sequence,
        source,
        position,
        facts,
        observation,
        result,
        blocker_code=None,
        broker_update_before_check=None,
    ):
        try:
            inputs = terminal_position_inputs(position, facts, observation)
            input_key = json.dumps(
                inputs,
                default=str,
                sort_keys=True,
                separators=(",", ":"),
            )
            if isinstance(result, bool):
                result_projection = result
            else:
                result_projection = {
                    "type": "{}.{}".format(type(result).__module__, type(result).__qualname__),
                    "status": getattr(result, "status", None),
                    "blocker_code": getattr(result, "blocker_code", None),
                }
            is_mismatch = (
                result is False or blocker_code == "TERMINAL_POSITION_RECONCILIATION_MISMATCH"
            )
            with terminal_position_event_lock:
                row_index = terminal_position_trace["record_indexes"].get(input_key)
                if row_index is None and len(terminal_position_trace["records"]) < 16:
                    row_index = len(terminal_position_trace["records"])
                    terminal_position_trace["record_indexes"][input_key] = row_index
                    terminal_position_trace["records"].append(
                        {"input": inputs, "first_sequence": sequence, "sources": [], "calls": []}
                    )
                elif row_index is None:
                    terminal_position_trace["dropped_unique_inputs"] += 1

                call = {
                    "sequence": sequence,
                    "source": source,
                    "input_index": row_index,
                    "result": result_projection,
                    "blocker_code": blocker_code,
                    "broker_update_before_check": (
                        None
                        if broker_update_before_check is None
                        else broker_update_before_check["sequence"]
                    ),
                }
                if len(terminal_position_trace["call_order"]) < 256:
                    terminal_position_trace["call_order"].append(call)
                else:
                    terminal_position_trace["dropped_call_order"] += 1
                if row_index is not None:
                    row = terminal_position_trace["records"][row_index]
                    if source not in row["sources"]:
                        row["sources"].append(source)
                    if len(row["calls"]) < 32:
                        row["calls"].append(call)
                if is_mismatch:
                    mismatch = {
                        "sequence": sequence,
                        "source": source,
                        "input_index": row_index,
                        "input": inputs,
                        "result": result_projection,
                        "blocker_code": blocker_code,
                        "broker_update_before_check": broker_update_before_check,
                    }
                    current = terminal_position_trace["first_mismatch"]
                    if current is None or sequence < current["sequence"]:
                        terminal_position_trace["first_mismatch"] = mismatch
                    current_last = terminal_position_trace["last_mismatch"]
                    if current_last is None or sequence > current_last["sequence"]:
                        terminal_position_trace["last_mismatch"] = mismatch
                    current_after_update = terminal_position_trace[
                        "first_mismatch_after_broker_update"
                    ]
                    if (
                        broker_update_before_check is not None
                        and sequence > broker_update_before_check["sequence"]
                        and (
                            current_after_update is None
                            or sequence < current_after_update["sequence"]
                        )
                    ):
                        terminal_position_trace["first_mismatch_after_broker_update"] = mismatch
        except Exception:
            # Diagnostics must never change a production predicate or callback path.
            with terminal_position_event_lock:
                terminal_position_trace["observer_errors"] += 1

    def traced_terminal_position_consistent(position, facts):
        sequence, broker_update_before_check = begin_terminal_position_event()
        observation = active_terminal_observations[-1] if active_terminal_observations else None
        result = original_terminal_position_consistent(position, facts)
        record_terminal_position_check(
            sequence=sequence,
            source="_terminal_position_consistent",
            position=position,
            facts=facts,
            observation=observation,
            result=result,
            broker_update_before_check=broker_update_before_check,
        )
        return result

    monkeypatch.setattr(
        factor_execution_module,
        "_terminal_position_consistent",
        traced_terminal_position_consistent,
    )

    def traced_one_terminal_reconcile(coordinator, facts, observation, **kwargs):
        sequence, broker_update_before_check = begin_terminal_position_event()
        active_terminal_observations.append(observation)
        try:
            result = original_one_terminal_reconcile(coordinator, facts, observation, **kwargs)
        finally:
            active_terminal_observations.pop()
        blocker_code = getattr(result, "blocker_code", None)
        if blocker_code == "TERMINAL_POSITION_RECONCILIATION_MISMATCH":
            matches = tuple(
                position
                for position in getattr(facts, "positions", ())
                if getattr(position, "instrument", None) == getattr(observation, "instrument", None)
                and getattr(position, "exchange", None) == getattr(observation, "exchange", None)
            )
            record_terminal_position_check(
                sequence=sequence,
                source="_reconcile_one_terminal_order_inline",
                position=matches[0] if len(matches) == 1 else None,
                facts=facts,
                observation=observation,
                result=result,
                blocker_code=blocker_code,
                broker_update_before_check=broker_update_before_check,
            )
        return result

    monkeypatch.setattr(
        factor_execution_module.FactorExecutionCoordinator,
        "_reconcile_one_terminal_order",
        traced_one_terminal_reconcile,
    )

    original_dated_trade_reconcile = (
        factor_position_book_module.FactorPositionBook.reconcile_dated_trade_observations
    )

    def traced_dated_trade_reconcile(position_book, *args, **kwargs):
        page = original_dated_trade_reconcile(position_book, *args, **kwargs)
        api = api_instances[-1] if api_instances else None
        items = tuple(getattr(page, "items", ()))
        item_states = tuple(
            (getattr(item, "status", None), getattr(item, "blocker_code", None))
            for item in items[:16]
        )
        has_blocker = any(
            status not in {"APPLIED", "DUPLICATE", "EXTERNAL_FLAT"} or blocker_code is not None
            for status, blocker_code in item_states
        )
        if (
            api is not None
            and api._phase == 1
            and has_blocker
            and not dated_page_failure_recorded["value"]
        ):
            dated_page_failure_recorded["value"] = True
            note_fill_event(
                "dated_trade_reconciliation_failure_page",
                offset=getattr(page, "offset", None),
                observation_count=getattr(page, "observation_count", None),
                item_states=item_states,
            )
        return page

    monkeypatch.setattr(
        factor_position_book_module.FactorPositionBook,
        "reconcile_dated_trade_observations",
        traced_dated_trade_reconcile,
    )

    def traced_terminal_reconcile(coordinator, facts, **kwargs):
        page = original_terminal_reconcile(coordinator, facts, **kwargs)
        observation = {
            "query_set_id": getattr(facts, "query_set_id", None),
            "available_at": getattr(facts, "available_at", None),
            "observation_count": getattr(page, "observation_count", None),
            "truncated": getattr(page, "truncated", None),
            "items": tuple(
                (
                    getattr(item, "observation_id", None),
                    getattr(item, "status", None),
                    getattr(item, "blocker_code", None),
                    getattr(item, "intent_id", None),
                )
                for item in getattr(page, "items", ())
            ),
        }
        reconciliation_observations.append(observation)
        if any(
            item[1] not in {"RESOLVED", "DUPLICATE", "EXTERNAL_TERMINAL_FLAT"}
            for item in observation["items"]
        ):
            note_fill_event("terminal_reconciliation_blocked", **observation)
        return page

    monkeypatch.setattr(
        factor_execution_module.FactorExecutionCoordinator,
        "reconcile_terminal_order_observations",
        traced_terminal_reconcile,
    )

    original_reject_order = broker_module.BtApiBroker._reject_order

    def traced_reject_order(broker, order, error_code, error_msg):
        broker_rejections.append(
            {
                "ref": getattr(order, "ref", None),
                "data_name": getattr(getattr(order, "data", None), "_name", None),
                "size": getattr(order, "size", None),
                "error_code": error_code,
                "error_msg": error_msg,
            }
        )
        return original_reject_order(broker, order, error_code, error_msg)

    monkeypatch.setattr(broker_module.BtApiBroker, "_reject_order", traced_reject_order)

    original_position_snapshot = broker_module.BtApiBroker.execution_position_snapshot

    def traced_position_snapshot(broker, data):
        snapshot = original_position_snapshot(broker, data)
        broker_position_observations.append(
            (
                getattr(data, "_name", None),
                None if snapshot is None else getattr(snapshot, "quantity", None),
                None if snapshot is None else getattr(snapshot, "long_quantity", None),
                None if snapshot is None else getattr(snapshot, "short_quantity", None),
            )
        )
        return snapshot

    monkeypatch.setattr(
        broker_module.BtApiBroker, "execution_position_snapshot", traced_position_snapshot
    )

    for method_name in ("_apply_order_update", "_apply_trade_update"):
        original_method = getattr(broker_module.BtApiBroker, method_name)

        def trace_broker_update(broker, update, *args, _method=original_method, **kwargs):
            position_before = tuple(
                (key, getattr(position, "size", None)) for key, position in broker.positions.items()
            )
            result = _method(broker, update, *args, **kwargs)
            position_after = tuple(
                (key, getattr(position, "size", None)) for key, position in broker.positions.items()
            )
            last_broker_update = {
                "method": _method.__name__,
                "update_kind": update.get("kind"),
                "status": update.get("status"),
                "order_ref": update.get("order_ref"),
                "trade_id": update.get("trade_id"),
                "position_before": position_before[-8:],
                "position_after": position_after[-8:],
            }
            update_sequence = record_broker_update_event(last_broker_update)
            broker_update_observations.append(
                (
                    _method.__name__,
                    update.get("kind"),
                    update.get("status"),
                    update.get("order_ref"),
                    update.get("trade_id"),
                    result,
                    position_after,
                )
            )
            note_fill_event(
                "broker_update_applied",
                method=_method.__name__,
                observer_sequence=update_sequence,
                update_kind=update.get("kind"),
                status=update.get("status"),
                order_ref=update.get("order_ref"),
                trade_id=update.get("trade_id"),
                result=result,
                position_before=position_before,
                position_after=position_after,
            )
            return result

        monkeypatch.setattr(broker_module.BtApiBroker, method_name, trace_broker_update)

    import backtrader.stores.factor_position_book as position_book_module

    original_book_snapshot = position_book_module.FactorPositionBook.snapshot

    def traced_book_snapshot(book, **kwargs):
        snapshot = original_book_snapshot(book, **kwargs)
        book_position_observations.append(
            (
                kwargs.get("instrument"),
                getattr(snapshot, "status", None),
                getattr(snapshot, "blocker_code", None),
                getattr(snapshot, "signed_quantity", None),
                getattr(snapshot, "attributed_signed_quantity", None),
                getattr(snapshot, "owner_intent_id", None),
            )
        )
        return snapshot

    monkeypatch.setattr(position_book_module.FactorPositionBook, "snapshot", traced_book_snapshot)

    original_store_submit = registered_sim_module.RegisteredSimStore.submit_order

    def traced_store_submit(store, order):
        identity = {
            "ref": getattr(order, "ref", None),
            "data_name": getattr(getattr(order, "data", None), "_name", None),
            "size": getattr(order, "size", None),
            "price": getattr(order, "price", None),
            "info": dict(getattr(order, "info", {})),
        }
        try:
            result = original_store_submit(store, order)
        except Exception as exc:
            store_write_calls.append(
                {
                    "operation": "submit",
                    "identity": identity,
                    "error_type": type(exc).__name__,
                    "error_code": getattr(exc, "code", None),
                    "error": str(exc),
                }
            )
            raise
        store_write_calls.append(
            {"operation": "submit", "identity": identity, "result": repr(result)}
        )
        return result

    monkeypatch.setattr(
        registered_sim_module.RegisteredSimStore, "submit_order", traced_store_submit
    )

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

    # Preserve the generated CTP wrapper's callback timestamps while binding
    # its wall clock to the explicit provider schedule used by this fixture.
    # Monotonic time remains real for query TTLs and bounded waits.
    monkeypatch.setattr(
        btapistore_module,
        "time",
        SimpleNamespace(
            time=clock.time,
            monotonic=time.monotonic,
            monotonic_ns=time.monotonic_ns,
            sleep=time.sleep,
        ),
    )

    class Alpha003MdClient:
        """Synthetic MD SDK leaf; production wrapper owns callback binding/normalization."""

        def __init__(self, **_kwargs):
            self._state_lock = threading.RLock()
            self._connection_generation = 1
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
            with self._state_lock:
                return self._connection_generation

        def start(self, block=False):
            assert block is False

        def wait_ready(self, timeout=20):
            del timeout
            return True

        @staticmethod
        def _raw_tick(instrument, exchange, trading_day, event_time):
            local = event_time.astimezone(timezone(timedelta(hours=8)))
            return SimpleNamespace(
                InstrumentID=instrument,
                ExchangeID=exchange,
                LastPrice=100.0,
                Volume=0,
                BidPrice1=99.9,
                AskPrice1=100.1,
                BidVolume1=5,
                AskVolume1=6,
                OpenInterest=0.0,
                Turnover=0.0,
                TradingDay=trading_day.replace("-", ""),
                ActionDay=local.strftime("%Y%m%d"),
                UpdateTime=local.strftime("%H:%M:%S"),
                UpdateMillisec=local.microsecond // 1000,
            )

        def _dispatch_tick(self, payload):
            # Match the SDK's generation-aware callback contract: capture the
            # callback and source generation together, then invoke outside the
            # client lock. The production wrapper owns normalization/queueing.
            with self._state_lock:
                callback = self.on_tick_with_generation
                generation = self._connection_generation
            if not callable(callback):
                raise AssertionError("production wrapper did not bind generation tick callback")
            callback(payload, generation)
            return generation

        def subscribe(self, instruments):
            with self._state_lock:
                self._subscribed.update(str(item) for item in instruments)
            for instrument in tuple(str(item) for item in instruments):
                rows = self._api._source_bars.get(instrument)
                if rows is None:
                    continue
                for row in tuple(rows):
                    bar_id = row["bar_id"]
                    if bar_id in self._scheduled_bar_ids:
                        continue
                    self._scheduled_bar_ids.add(bar_id)
                    delivery_at = row["available_at"] + timedelta(milliseconds=200)

                    def deliver(instrument=instrument, row=row, bar_id=bar_id):
                        event_time = row["bucket_end"] + timedelta(seconds=2, milliseconds=10)
                        payload = self._raw_tick(
                            instrument,
                            row["exchange"],
                            row["trading_day"],
                            event_time,
                        )
                        callback_generation = self._dispatch_tick(payload)
                        self._api.tick_observations.append(
                            (
                                instrument,
                                bar_id,
                                callback_generation,
                                row["connection_generation"],
                            )
                        )
                        if (
                            self._api._phase == 1
                            and not any(self._api._source_bars.values())
                            and self._api._pending_close_instrument == instrument
                            and self._api._pending_close_callback is not None
                        ):
                            order_ref = self._api._pending_close_callback
                            self._api._pending_close_callback = None
                            self._api._pending_close_instrument = None
                            self._api.trader_client.emit_fill(order_ref)

                    clock.schedule_at(delivery_at, deliver)

        def schedule_winddown_quote(self, instrument, query_set_id, query_completed_at):
            api = self._api
            if instrument in api._winddown_scheduled_instruments:
                return
            route = next(
                ((item, exchange) for item, exchange in route_rows if item == instrument), None
            )
            if route is None:
                raise AssertionError("winddown quote route was not configured")
            _instrument, exchange = route
            event_time = query_completed_at + timedelta(milliseconds=5)
            delivery_at = query_completed_at + timedelta(milliseconds=25)
            api._winddown_scheduled_instruments.add(instrument)
            api._winddown_query_set_for[instrument] = query_set_id
            api._winddown_metadata[instrument] = {
                "query_set_id": query_set_id,
                "query_completed_at": query_completed_at.isoformat(),
                "event_time": event_time.isoformat(),
                "delivery_at": delivery_at.isoformat(),
            }

            def deliver():
                payload = self._raw_tick(
                    instrument,
                    exchange,
                    start_day.strftime("%Y%m%d"),
                    event_time,
                )
                generation = self._dispatch_tick(payload)
                api.tick_observations.append(
                    (instrument, "winddown:" + query_set_id, generation, "provider-scheduled")
                )
                if (
                    api._phase == 1
                    and api._pending_close_instrument == instrument
                    and api._pending_close_callback is not None
                ):
                    order_ref = api._pending_close_callback
                    api._pending_close_callback = None
                    api._pending_close_instrument = None
                    api.trader_client.emit_fill(order_ref)

            clock.schedule_at(delivery_at, deliver)

        def stop(self):
            self.stopped = True

        def capture_tick_callback(self, payload):
            """Capture generation with callback under SDK lock, invoke outside it."""
            with self._state_lock:
                callback = self.on_tick_with_generation
                generation = self._connection_generation
            if not callable(callback):
                raise AssertionError("production wrapper did not bind generation tick callback")
            return lambda: callback(payload, generation)

        def dispatch_disconnect(self, reason, generation=None):
            with self._state_lock:
                callback = self.on_disconnect_with_generation
                captured_generation = (
                    self._connection_generation if generation is None else generation
                )
            if callable(callback):
                callback(reason, captured_generation)

    class Alpha003TraderClient(facts_fixtures._ProviderLeaves):
        """Synthetic typed-query/trader SDK leaf under the real CTP wrapper."""

        def __init__(self, **_kwargs):
            super().__init__(query_rows=query_rows, query_time=clock.utc_now(), ticks={})
            self._api = api_instances[-1]
            self.trader_client._account_fingerprint = "alpha003-factor-chain-account"
            self.trader_client._trading_day = start_day.strftime("%Y%m%d")
            self.trader_client._connection_generation = 1
            self._front_id = 4
            self._session_id = 7
            self._req_id = 0
            self._next_order_ref_value = 100
            self.is_ready = True
            self.is_read_only_ready = True
            self.is_trading_ready = True
            self.stopped = False
            self.native_calls = self._api.native_calls
            self._provider_orders = {}
            self._fake_active_capability = None

        def start(self, block=False):
            assert block is False

        def wait_ready(self, timeout=20):
            del timeout
            return True

        def stop(self):
            self.stopped = True

        def next_order_ref(self):
            self._next_order_ref_value += 1
            return str(self._next_order_ref_value)

        def get_query_session_scope(self):
            return self.trader_client.get_query_session_scope()

        def get_execution_gate_state(self):
            return dict(self.trader_client.get_execution_gate_state())

        def get_session_state(self):
            state = self.trader_client.get_session_state()
            state.update(
                front_id=self._front_id,
                session_id=self._session_id,
                read_only_ready=self.is_read_only_ready,
                trading_ready=self.is_trading_ready,
            )
            return state

        def arm_execution_for_registered_sim(self, **kwargs):
            capability, state = self.trader_client.arm_execution_for_registered_sim(**kwargs)
            self._fake_active_capability = capability
            return capability, state

        def disarm_execution_gate(self, capability, reason):
            if capability is not self._fake_active_capability:
                raise AssertionError("fake SDK disarm must name the active capability")
            self._fake_active_capability = None
            state = dict(self.trader_client._gate_state)
            state.update(
                managed=False,
                armed=False,
                instrument=None,
                authorized_instruments=[],
                revocation_reason=reason,
            )
            self.trader_client._gate_state = state
            return {"revoked": True}

        def _query_family(self, family, request_type, **filters):
            self.query_rows = dict(query_rows)
            started_at = clock.utc_now()
            self.query_time = started_at + timedelta(milliseconds=2)
            result = super()._query_family(family, request_type, **filters)
            clock.advance(timedelta(milliseconds=2))
            note_fill_event(
                "query_completed",
                family=family,
                request_id=getattr(result, "request_id", None),
                query_started_at=started_at.isoformat(),
                query_completed_at=str(getattr(result, "completed_at_utc", None)),
                row_count=(
                    None if getattr(result, "records", None) is None else len(result.records)
                ),
                query_complete=getattr(result, "complete", None),
            )
            return result

        def query_account(self, timeout=5):
            del timeout
            return dict(query_rows["account_result"][0])

        def query_positions(self, timeout=5):
            del timeout
            return [dict(row) for row in query_rows["positions_result"]]

        def query_instrument(self, instrument, exchange_id="", timeout=5):
            del timeout
            return next(
                (
                    dict(row)
                    for row in query_rows["instruments_result"]
                    if row.get("InstrumentID") == instrument
                    and (not exchange_id or row.get("ExchangeID") == exchange_id)
                ),
                None,
            )

        def query_instrument_margin_rate(self, instrument, exchange_id="", timeout=5):
            del timeout
            return next(
                (
                    dict(row)
                    for row in query_rows["instrument_margin_rate_result"]
                    if row.get("InstrumentID") == instrument
                    and (not exchange_id or row.get("ExchangeID") == exchange_id)
                ),
                None,
            )

        def query_instrument_commission_rate(self, instrument, exchange_id="", timeout=5):
            del timeout
            return {
                "InstrumentID": instrument,
                "ExchangeID": exchange_id,
                "OpenRatioByMoney": "0",
                "OpenRatioByVolume": "0",
                "CloseRatioByMoney": "0",
                "CloseRatioByVolume": "0",
                "CloseTodayRatioByMoney": "0",
                "CloseTodayRatioByVolume": "0",
            }

        def submit_order_insert(self, field, request_id, *, execution_capability):
            if execution_capability is not self._fake_active_capability:
                raise AssertionError("native insert did not receive the exact SDK grant")
            order_ref = str(field.OrderRef)
            offset_flag = str(field.CombOffsetFlag)
            identity = {
                "order_ref": order_ref,
                "order_sys_id": "sys-" + order_ref,
                "instrument_id": str(field.InstrumentID),
                "exchange_id": str(field.ExchangeID),
                "side": "buy" if str(field.Direction) == "0" else "sell",
                "offset_flag": offset_flag,
                "offset": {
                    "0": "open",
                    "1": "close",
                    "3": "close_today",
                    "4": "close_yesterday",
                }.get(offset_flag),
                "size": int(field.VolumeTotalOriginal),
                "price": float(field.LimitPrice),
                "front_id": self._front_id,
                "session_id": self._session_id,
            }
            if identity["offset"] is None:
                raise AssertionError("unexpected CTP offset in source-backed order")
            self._provider_orders[order_ref] = identity
            self.native_calls.append(
                (
                    "insert",
                    identity["instrument_id"],
                    identity["exchange_id"],
                    order_ref,
                    request_id,
                )
            )
            self._publish_order(identity, status="3", filled=0, remaining=identity["size"])
            order_callback = self.on_order
            if not callable(order_callback):
                raise AssertionError("production wrapper did not bind the CTP order callback")
            order_callback(self._ctp_order_event(identity, "3", 0, identity["size"]))
            if (
                self._api._phase == 1
                and identity["offset"] == "open"
                and self._api._pending_fill_callback is None
                and not self._api._applied_fill_query
            ):
                self._api._pending_fill_callback = order_ref
                self._api._pending_fill_instrument = identity["instrument_id"]
            elif self._api._phase == 1 and identity["offset"].startswith("close"):
                self._api._pending_close_callback = order_ref
                self._api._pending_close_instrument = identity["instrument_id"]
            self._api._mark_refresh_required()
            return 0

        def submit_order_action(self, field, request_id, *, execution_capability):
            if execution_capability is not self._fake_active_capability:
                raise AssertionError("native cancel did not receive the exact SDK grant")
            order_ref = str(field.OrderRef)
            identity = self._provider_orders[order_ref]
            self.native_calls.append(
                (
                    "cancel",
                    identity["instrument_id"],
                    identity["exchange_id"],
                    order_ref,
                    request_id,
                )
            )
            self._publish_order(identity, status="5", filled=0, remaining=identity["size"])
            self.on_order(self._ctp_order_event(identity, "5", 0, identity["size"]))
            self._api._mark_refresh_required()
            return 0

        def _ctp_order_event(self, identity, status, filled, remaining):
            local = clock.utc_now().astimezone(timezone(timedelta(hours=8)))
            return SimpleNamespace(
                OrderRef=identity["order_ref"],
                OrderSysID=identity["order_sys_id"],
                InstrumentID=identity["instrument_id"],
                ExchangeID=identity["exchange_id"],
                FrontID=identity["front_id"],
                SessionID=identity["session_id"],
                OrderStatus=status,
                OrderSubmitStatus="3",
                Direction="0" if identity["side"] == "buy" else "1",
                CombOffsetFlag=identity["offset_flag"],
                VolumeTotalOriginal=identity["size"],
                VolumeTraded=filled,
                VolumeTotal=remaining,
                LimitPrice=identity["price"],
                TradingDay=start_day.strftime("%Y%m%d"),
                InsertTime=local.strftime("%H:%M:%S"),
                UpdateTime=local.strftime("%H:%M:%S"),
            )

        def _publish_order(self, identity, *, status, filled, remaining):
            row = {
                "OrderRef": identity["order_ref"],
                "OrderSysID": identity["order_sys_id"],
                "InstrumentID": identity["instrument_id"],
                "ExchangeID": identity["exchange_id"],
                "TradingDay": start_day.strftime("%Y%m%d"),
                "FrontID": identity["front_id"],
                "SessionID": identity["session_id"],
                "OrderStatus": status,
                "OrderSubmitStatus": "3",
                "Direction": "0" if identity["side"] == "buy" else "1",
                "CombOffsetFlag": identity["offset_flag"],
                "VolumeTotalOriginal": identity["size"],
                "VolumeTraded": filled,
                "VolumeTotal": remaining,
                "LimitPrice": identity["price"],
            }
            rows = query_rows["orders_result"]
            rows[:] = [item for item in rows if str(item.get("OrderRef")) != identity["order_ref"]]
            rows.append(row)

        def emit_fill(self, order_ref):
            identity = self._provider_orders[str(order_ref)]
            quantity = identity["size"]
            self._publish_order(identity, status="0", filled=quantity, remaining=0)
            self.on_order(self._ctp_order_event(identity, "0", quantity, 0))
            local = clock.utc_now().astimezone(timezone(timedelta(hours=8)))
            trade_id = "alpha003-{}-{}".format(identity["offset"], identity["order_ref"])
            offset_flag = identity["offset_flag"]
            trade = SimpleNamespace(
                TradeID=trade_id,
                OrderRef=identity["order_ref"],
                OrderSysID=identity["order_sys_id"],
                InstrumentID=identity["instrument_id"],
                ExchangeID=identity["exchange_id"],
                Direction="0" if identity["side"] == "buy" else "1",
                OffsetFlag=offset_flag,
                HedgeFlag="1",
                Volume=quantity,
                Price=100.0,
                TradeDate=local.strftime("%Y%m%d"),
                TradeTime=local.strftime("%H:%M:%S"),
                TradingDay=start_day.strftime("%Y%m%d"),
            )
            self.on_trade(trade)
            query_rows["trades_result"].append(
                {
                    "TradeID": trade_id,
                    "OrderRef": identity["order_ref"],
                    "OrderSysID": identity["order_sys_id"],
                    "InstrumentID": identity["instrument_id"],
                    "ExchangeID": identity["exchange_id"],
                    "Direction": trade.Direction,
                    "OffsetFlag": offset_flag,
                    "HedgeFlag": "1",
                    "Volume": str(quantity),
                    "Price": "100",
                    "TradeDate": trade.TradeDate,
                    "TradeTime": trade.TradeTime,
                    "TradingDay": start_day.strftime("%Y%m%d"),
                }
            )
            if identity["offset"] == "open":
                position = facts_fixtures._dated_position_row(
                    quantity,
                    side="LONG" if identity["side"] == "buy" else "SHORT",
                    trading_day=start_day.strftime("%Y%m%d"),
                    PositionCost=str(Decimal(quantity) * Decimal("1000")),
                )
                position.update(
                    InstrumentID=identity["instrument_id"], ExchangeID=identity["exchange_id"]
                )
                query_rows["positions_result"][:] = [
                    row
                    for row in query_rows["positions_result"]
                    if row.get("InstrumentID") != identity["instrument_id"]
                ]
                query_rows["positions_result"].append(position)
            else:
                query_rows["positions_result"][:] = [
                    row
                    for row in query_rows["positions_result"]
                    if row.get("InstrumentID") != identity["instrument_id"]
                ]
            note_fill_event(
                "provider_callback_fill",
                order_ref=identity["order_ref"],
                trade_id=trade_id,
                offset=identity["offset"],
                query_position_rows=tuple(
                    (row.get("InstrumentID"), row.get("Position"))
                    for row in query_rows["positions_result"]
                ),
            )
            self._api._mark_refresh_required()
            if identity["offset"] == "open":
                self._api._pending_fill_callback = None
                self._api._pending_fill_instrument = None
                self._api._applied_fill_query = True

    monkeypatch.setattr(ctp_client_module, "MdClient", Alpha003MdClient)
    monkeypatch.setattr(ctp_client_module, "TraderClient", Alpha003TraderClient)

    CtpClientWrapper = btapistore_module._create_ctp_wrapper_class()

    class Alpha003BarTapeMixin(CtpClientWrapper):
        """Only the completed-bar tape is fake; all live CTP paths stay real."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._source_bars = bars_by_instrument
            self._phase = len(api_instances)
            self._sent_tick_for = set()
            self._winddown_metadata = {}
            self._winddown_query_set_for = {}
            self._winddown_scheduled_instruments = set()
            self._pending_fill_callback = None
            self._pending_fill_instrument = None
            self._pending_close_callback = None
            self._pending_close_instrument = None
            self._applied_fill_query = False
            self.native_calls = []
            self.tick_observations = []
            self.winddown_tick_observations = []
            self.winddown_poll_attempts = 0
            self.winddown_poll_blockers = []
            self._required_refresh_start = None
            api_instances.append(self)

        @property
        def closed(self):
            return bool(
                self.md_client is not None
                and self.trader_client is not None
                and self.md_client.stopped
                and self.trader_client.stopped
            )

        def _mark_refresh_required(self):
            with refresh_condition:
                self._required_refresh_start = refresh_state["started"] + 1

        def _wait_for_refresh(self):
            with refresh_condition:
                required = self._required_refresh_start
                if required is None:
                    return
                if not refresh_condition.wait_for(
                    lambda: refresh_state["completed"] >= required,
                    timeout=4.0,
                ):
                    raise AssertionError(
                        "complete provider query refresh did not follow order write"
                    )
                self._required_refresh_start = None

        def poll_bar(self, instrument):
            self._wait_for_refresh()
            if (
                self._phase == 1
                and instrument == self._pending_fill_instrument
                and self._pending_fill_callback is not None
                and not self._applied_fill_query
            ):
                order_ref = self._pending_fill_callback
                note_fill_event(
                    "provider_fill_scheduled_from_bar_tape",
                    order_ref=order_ref,
                    instrument=instrument,
                    query_position_before=tuple(
                        (row.get("InstrumentID"), row.get("Position"))
                        for row in query_rows["positions_result"]
                    ),
                )
                self.trader_client.emit_fill(order_ref)
            rows = self._source_bars.get(instrument)
            if not rows or rows[0]["available_at"] > clock.utc_now():
                return None
            row = rows.popleft()
            self._sent_tick_for.discard(row["bar_id"])
            return row

    def client_generation(api):
        return api.md_client.connection_generation

    original_factory = registered_sim_module._make_api_factory
    monkeypatch.setattr(
        registered_sim_module,
        "_make_api_factory",
        lambda allow_writes, history_limit, terminal_limit, api_cls: original_factory(
            allow_writes, history_limit, terminal_limit, Alpha003BarTapeMixin
        ),
    )
    first_source_bar = tape["bars"][0]
    synthetic_store_config, synthetic_api_kwargs = runner_fixtures._official_simnow_store_config()
    synthetic_store_config.update(
        {
            "environment": "simnow",
            "broker_id": "9999",
            "investor_id": "fixture",
            "password": "unused",
        }
    )
    synthetic_api_kwargs = {
        **synthetic_api_kwargs,
        "live_tick_provenance": {
            "clock_domain_id": first_source_bar["clock_domain_id"],
            "rules_hash": "a" * 64,
            "session_segment": first_source_bar["session_segment"],
        },
    }
    monkeypatch.setattr(
        RUNNER,
        "_live_env_config",
        lambda _config: (dict(synthetic_store_config), dict(synthetic_api_kwargs)),
    )
    monkeypatch.setattr(RUNNER, "RunnerWallClock", lambda: clock)

    captured_strategies = []
    trade_notify_observations = []
    strategy_decision_trace = []
    idle_decision_trace = []
    store_tick_trace = []
    chain_trace = []
    risk_scope_trace = []
    risk_dispatch_trace = []
    diagnostic_path = (
        Path(__file__).resolve().parents[2]
        / ".codex-tmp"
        / "alpha003_registered_sim_order_chain_{}.json".format(time.time_ns())
    )

    def persist_diagnostic(stage, *, result_value=None, error=None, archive_evidence=None):
        def result_summary(value):
            if not isinstance(value, dict):
                return None
            if "phase1" in value or "phase2" in value:
                return {
                    phase: result_summary(value.get(phase))
                    for phase in ("phase1", "phase2")
                    if phase in value
                }
            summary = {
                key: value.get(key)
                for key in (
                    "write_mode",
                    "shutdown_status",
                    "cleanup_complete",
                    "resource_shutdown",
                    "strategy_shutdown_blocker",
                    "strategy_shutdown_post_join_blocker",
                    "decision_tape",
                    "decision_tape_readback",
                )
                if key in value
            }
            events = value.get("strategy_order_events")
            if isinstance(events, dict):
                summary["strategy_order_events"] = {
                    "events": tuple(tuple(events.get("events") or ())[-32:])
                }
            return summary

        strategy = captured_strategies[-1] if captured_strategies else None
        refresh_loop = (
            getattr(getattr(strategy, "p", None), "control_refresh_loop", None)
            if strategy is not None
            else None
        )
        fact = getattr(strategy, "last_execution_facts", None)
        plan_now = getattr(strategy, "last_order_plan", None)
        payload = {
            "schema": "alpha003_registered_sim_order_chain_diagnostic_v1",
            "stage": stage,
            "captured_at_utc": clock.utc_now().isoformat(),
            "argv": tuple(sys.argv),
            "error": (None if error is None else (type(error).__name__, str(error)[:512])),
            "refresh": {
                "started": refresh_state["started"],
                "completed": refresh_state["completed"],
                "errors": tuple(refresh_state["errors"][-16:]),
                "receipts": tuple(refresh_receipts[-32:]),
                "published_query_set_id": getattr(
                    getattr(getattr(refresh_loop, "last_receipt", None), "query_set", None),
                    "query_set_id",
                    None,
                ),
                "published_facts_query_set_id": getattr(
                    getattr(refresh_loop, "last_facts", None), "query_set_id", None
                ),
                "last_error_code": getattr(refresh_loop, "last_error_code", None),
            },
            "strategy": (
                None
                if strategy is None
                else {
                    "last_batch_id": strategy._last_batch_id,
                    "last_execution_block_reason": strategy.last_execution_block_reason,
                    "facts": (
                        None
                        if fact is None
                        else {
                            "snapshot_id": getattr(fact, "snapshot_id", None),
                            "query_set_id": getattr(fact, "query_set_id", None),
                            "available_at": getattr(fact, "available_at", None),
                            "blockers": getattr(fact, "blockers", None),
                            "risk_reduction_blockers": getattr(
                                fact, "risk_reduction_blockers", None
                            ),
                            "order_cancel_blockers": getattr(fact, "order_cancel_blockers", None),
                            "quotes": tuple(
                                (
                                    getattr(quote, "instrument", None),
                                    getattr(quote, "source", None),
                                    getattr(quote, "sequence", None),
                                    getattr(quote, "event_time", None),
                                    getattr(quote, "available_at", None),
                                    getattr(quote, "quality", None),
                                )
                                for quote in getattr(fact, "quotes", ())
                            ),
                        }
                    ),
                    "plan": (
                        None
                        if plan_now is None
                        else {
                            "status": getattr(plan_now, "status", None),
                            "reason": getattr(plan_now, "reason", None),
                            "actions": tuple(
                                (
                                    getattr(action, "action", None),
                                    getattr(action, "instrument", None),
                                    getattr(action, "position_effect", None),
                                    getattr(action, "quantity", None),
                                    getattr(action, "offset", None),
                                    getattr(action, "reason", None),
                                )
                                for action in getattr(plan_now, "actions", ())
                            ),
                        }
                    ),
                    "order_events": tuple(
                        dict(event) if hasattr(event, "items") else str(event)[:512]
                        for event in tuple(getattr(strategy, "order_events", ()) or ())[-16:]
                    ),
                    "trade_events": tuple(
                        dict(event)
                        for event in tuple(getattr(strategy, "trade_events", ()) or ())[-16:]
                    ),
                }
            ),
            "trade_notify_observations": tuple(trade_notify_observations[-32:]),
            "apis": tuple(
                {
                    "phase": current_api._phase,
                    "closed": current_api.closed,
                    "native_calls": tuple(current_api.native_calls[-64:]),
                }
                for current_api in api_instances[-2:]
            ),
            "provider_rows": {
                family: tuple(query_rows.get(family, ())[-32:])
                for family in (
                    "account_result",
                    "positions_result",
                    "orders_result",
                    "trades_result",
                    "instruments_result",
                    "instrument_margin_rate_result",
                )
            },
            "archive_evidence": archive_evidence,
            "refresh_counts": (refresh_state["started"], refresh_state["completed"]),
            "strategy_callbacks": tuple(strategy_decision_trace[-256:]),
            "provider_timeline": tuple(fill_timeline[-512:]),
            "store_ticks": tuple(store_tick_trace[-128:]),
            "chain_trace": tuple(chain_trace[-128:]),
            "risk_scopes": tuple(risk_scope_trace[-64:]),
            "risk_dispatch": tuple(risk_dispatch_trace[-32:]),
            "reconciliation": tuple(reconciliation_observations[-32:]),
            "terminal_position_checks": tuple(
                {
                    "input": record["input"],
                    "first_sequence": record["first_sequence"],
                    "sources": tuple(record["sources"]),
                    "calls": tuple(record["calls"]),
                }
                for record in sorted(
                    terminal_position_trace["records"], key=lambda item: item["first_sequence"]
                )
            ),
            "terminal_position_call_order": tuple(
                sorted(terminal_position_trace["call_order"], key=lambda item: item["sequence"])
            ),
            "terminal_position_trace_bounds": {
                "unique_inputs_limit": 16,
                "unique_inputs_dropped": terminal_position_trace["dropped_unique_inputs"],
                "call_order_limit": 256,
                "call_order_dropped": terminal_position_trace["dropped_call_order"],
                "observer_errors": terminal_position_trace["observer_errors"],
            },
            "terminal_position_first_mismatch": terminal_position_trace["first_mismatch"],
            "terminal_position_last_mismatch": terminal_position_trace["last_mismatch"],
            "terminal_position_first_mismatch_after_broker_update": terminal_position_trace[
                "first_mismatch_after_broker_update"
            ],
            "terminal_position_last_broker_update": terminal_position_trace["last_broker_update"],
            "broker_position_observations": tuple(broker_position_observations[-16:]),
            "store_write_calls": tuple(store_write_calls[-64:]),
            "broker_rejections": tuple(broker_rejections[-64:]),
            "result": result_summary(result_value),
        }
        diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostic_path.write_text(
            json.dumps(payload, default=str, sort_keys=True, indent=2), encoding="utf-8"
        )
        return str(diagnostic_path)

    original_scope_enter = factor_execution_module.FactorExecutionDecisionScope.__enter__

    def traced_scope_enter(scope):
        try:
            result = original_scope_enter(scope)
        except Exception as error:
            if getattr(scope, "risk_only", False):
                risk_scope_trace.append(
                    {
                        "kind": "risk_scope_enter_failed",
                        "decision_kind": getattr(scope.key, "decision_kind", None),
                        "close_time": getattr(scope.key, "close_time", None),
                        "intents": tuple(scope.intent_keys),
                        "error": (type(error).__name__, str(error)),
                    }
                )
            raise
        if getattr(scope, "risk_only", False):
            risk_scope_trace.append(
                {
                    "kind": "risk_scope_entered",
                    "decision_kind": getattr(scope.key, "decision_kind", None),
                    "close_time": getattr(scope.key, "close_time", None),
                    "decision_id": scope.decision_id,
                    "intent_keys": tuple(scope.intent_keys),
                    "dispatch_allowed": scope.dispatch_allowed,
                    "is_new_grid": scope.is_new_grid,
                    "run_order_intents_used": scope.run_order_intents_used,
                }
            )
        if len(risk_scope_trace) > 64:
            del risk_scope_trace[:-64]
        return result

    monkeypatch.setattr(
        factor_execution_module.FactorExecutionDecisionScope,
        "__enter__",
        traced_scope_enter,
    )
    original_bind_strategy = RUNNER.QueryRefreshLoop.bind_strategy

    def capture_bound_strategy(loop, strategy):
        original_bind_strategy(loop, strategy)
        captured_strategies.append(strategy)

        original_next = strategy.next
        original_notify_idle = strategy.notify_idle
        original_run_live = strategy._run_live
        original_notify_trade = strategy.notify_trade
        strategy_index = len(captured_strategies) - 1

        def observe_notify_trade(trade):
            result = original_notify_trade(trade)
            event = dict(strategy.trade_events[-1])
            assert event["ref"] == trade.ref
            trade_notify_observations.append(
                {
                    "strategy_index": strategy_index,
                    "event": event,
                    "trade_ref": trade.ref,
                    "instrument_id": getattr(trade.data, "_dataname", None),
                    "data_name": getattr(trade.data, "_name", None),
                    "long": trade.long,
                    "size": str(trade.size),
                    "price": str(trade.price),
                    "pnl": str(trade.pnl),
                    "pnlcomm": str(trade.pnlcomm),
                    "commission": str(trade.commission),
                    "isclosed": bool(trade.isclosed),
                }
            )
            return result

        strategy.notify_trade = observe_notify_trade

        def trace_strategy_turn(callback_name, callback, *args, **kwargs):
            with fact_turn_lock:
                # This timestamp is the strategy turn's first source-clock
                # observation, after it owns the same lock as query refresh.
                callback_requested_at = clock.utc_now()
                refresh_loop = strategy.p.control_refresh_loop
                receipt_before = getattr(refresh_loop, "last_receipt", None)
                before_query_set = getattr(
                    getattr(receipt_before, "query_set", None), "query_set_id", None
                )
                before_refresh = (refresh_state["started"], refresh_state["completed"])
                try:
                    result = callback(*args, **kwargs)
                except Exception as exc:
                    if len(strategy_decision_trace) < 256:
                        strategy_decision_trace.append(
                            {
                                "kind": "strategy_callback_error",
                                "callback": callback_name,
                                "requested_at": callback_requested_at.isoformat(),
                                "query_set_before": before_query_set,
                                "refresh_started_completed_before": before_refresh,
                                "error": (type(exc).__name__, str(exc)[:512]),
                            }
                        )
                    raise
                api = api_instances[-1] if api_instances else None
                if api is not None and api._phase == 1 and len(strategy_decision_trace) < 256:
                    facts = strategy.last_execution_facts
                    plan_now = strategy.last_order_plan
                    receipt_after = getattr(refresh_loop, "last_receipt", None)
                    strategy_decision_trace.append(
                        {
                            "kind": "strategy_callback",
                            "callback": callback_name,
                            "requested_at": callback_requested_at.isoformat(),
                            "entered_at": clock.utc_now().isoformat(),
                            "refresh_started_completed_before": before_refresh,
                            "refresh_started_completed_after": (
                                refresh_state["started"],
                                refresh_state["completed"],
                            ),
                            "query_set_before": before_query_set,
                            "query_set_after": getattr(
                                getattr(receipt_after, "query_set", None),
                                "query_set_id",
                                None,
                            ),
                            "last_error_code": getattr(refresh_loop, "last_error_code", None),
                            "batch_id": strategy._last_batch_id,
                            "execution_block_reason": strategy.last_execution_block_reason,
                            "facts": (
                                None
                                if facts is None
                                else {
                                    "snapshot_id": getattr(facts, "snapshot_id", None),
                                    "query_set_id": getattr(facts, "query_set_id", None),
                                    "available_at": getattr(facts, "available_at", None),
                                    "blockers": getattr(facts, "blockers", None),
                                    "risk_reduction_blockers": getattr(
                                        facts, "risk_reduction_blockers", None
                                    ),
                                    "order_cancel_blockers": getattr(
                                        facts, "order_cancel_blockers", None
                                    ),
                                    "quotes": tuple(
                                        (
                                            getattr(quote, "instrument", None),
                                            getattr(quote, "source", None),
                                            getattr(quote, "sequence", None),
                                            getattr(quote, "event_time", None),
                                            getattr(quote, "available_at", None),
                                            getattr(quote, "quality", None),
                                        )
                                        for quote in getattr(facts, "quotes", ())
                                    ),
                                }
                            ),
                            "plan": (
                                None
                                if plan_now is None
                                else {
                                    "status": getattr(plan_now, "status", None),
                                    "reason": getattr(plan_now, "reason", None),
                                    "actions": tuple(
                                        (
                                            getattr(action, "action", None),
                                            getattr(action, "instrument", None),
                                            getattr(action, "position_effect", None),
                                            getattr(action, "quantity", None),
                                            getattr(action, "offset", None),
                                            getattr(action, "reason", None),
                                        )
                                        for action in getattr(plan_now, "actions", ())
                                    ),
                                }
                            ),
                        }
                    )
                return result

        def traced_next(*args, **kwargs):
            return trace_strategy_turn("next", original_next, *args, **kwargs)

        def traced_notify_idle(*args, **kwargs):
            return trace_strategy_turn("notify_idle", original_notify_idle, *args, **kwargs)

        strategy.next = traced_next
        strategy.notify_idle = traced_notify_idle

        def traced_run_live(batch, snapshot, now, ordinal, session_close, run_end, **kwargs):
            result = original_run_live(
                batch, snapshot, now, ordinal, session_close, run_end, **kwargs
            )
            api = api_instances[-1] if api_instances else None
            if api is not None and api._phase == 1 and strategy.shutdown_requested:
                facts = strategy.last_execution_facts
                plan_now = strategy.last_order_plan
                observation = {
                    "sequence": len(chain_trace),
                    "kind": "strategy_run_live",
                    "now": now.isoformat() if hasattr(now, "isoformat") else now,
                    "batch_id": getattr(batch, "batch_id", None),
                    "run_end": run_end,
                    "snapshot_id": getattr(facts, "snapshot_id", None),
                    "query_set_id": getattr(facts, "query_set_id", None),
                    "facts_available_at": getattr(facts, "available_at", None),
                    "risk_reduction_ready": getattr(facts, "risk_reduction_ready", None),
                    "risk_reduction_blockers": getattr(facts, "risk_reduction_blockers", None),
                    "positions": tuple(
                        (
                            getattr(position, "instrument", None),
                            getattr(position, "quantity", None),
                            getattr(position, "position_book_status", None),
                            getattr(position, "position_book_blocker_code", None),
                            getattr(position, "owner_strategy_scope", None),
                            getattr(position, "owner_intent_id", None),
                            getattr(position, "stop_price", None),
                        )
                        for position in getattr(facts, "positions", ())
                    ),
                    "quotes": tuple(
                        (
                            getattr(quote, "instrument", None),
                            getattr(quote, "event_time", None),
                            getattr(quote, "available_at", None),
                            getattr(quote, "quality", None),
                        )
                        for quote in getattr(facts, "quotes", ())
                    ),
                    "plan": (
                        getattr(plan_now, "status", None),
                        getattr(plan_now, "reason", None),
                        tuple(
                            (
                                getattr(action, "action", None),
                                getattr(action, "instrument", None),
                                getattr(action, "position_effect", None),
                                getattr(action, "quantity", None),
                                getattr(action, "offset", None),
                                getattr(action, "reason", None),
                            )
                            for action in getattr(plan_now, "actions", ())
                        ),
                    ),
                    "shutdown": (
                        strategy.shutdown_ready,
                        strategy.shutdown_blocker,
                    ),
                    "latest_winddown_ticks": tuple(api.winddown_tick_observations[-3:]),
                }
                idle_decision_trace.append(observation)
                chain_trace.append(observation)
                if len(idle_decision_trace) > 128:
                    del idle_decision_trace[:-128]
                if len(chain_trace) > 128:
                    del chain_trace[:-128]
            return result

        strategy._run_live = traced_run_live

        original_dispatch_live_actions = strategy._dispatch_live_actions

        def traced_dispatch_live_actions(actions, batch):
            result = original_dispatch_live_actions(actions, batch)
            api = api_instances[-1] if api_instances else None
            if api is not None and api._phase == 1:
                risk_dispatch_trace.append(
                    {
                        "kind": "dispatch_live_actions_returned",
                        "actions": tuple(
                            (
                                getattr(action, "action", None),
                                getattr(action, "instrument", None),
                                getattr(action, "side", None),
                                getattr(action, "position_effect", None),
                                getattr(action, "quantity", None),
                                getattr(action, "offset", None),
                            )
                            for action in actions
                        ),
                        "orders": tuple(
                            (
                                ref,
                                getattr(order, "status", None),
                                getattr(getattr(order, "data", None), "_name", None),
                                getattr(order, "size", None),
                                getattr(getattr(order, "info", None), "factor_intent_id", None),
                            )
                            for ref, order in getattr(strategy, "_orders_by_broker_ref", {}).items()
                        )[-8:],
                        "store_writes": len(store_write_calls),
                        "native_calls": len(api.native_calls),
                    }
                )
                if len(risk_dispatch_trace) > 32:
                    del risk_dispatch_trace[:-32]
            return result

        strategy._dispatch_live_actions = traced_dispatch_live_actions

        store = getattr(getattr(strategy, "broker", None), "store", None)
        original_poll_tick = getattr(store, "poll_tick", None)
        if callable(original_poll_tick):

            def traced_store_poll_tick(dataname):
                tick = original_poll_tick(dataname)
                api = api_instances[-1] if api_instances else None
                if tick is not None and api is not None and api._phase == 1:
                    observation = {
                        "sequence": len(chain_trace),
                        "kind": "store_poll_tick_returned",
                        "instrument": dataname,
                        "event_id": getattr(tick, "event_id", None),
                        "event_time": getattr(tick, "event_time", None),
                        "received_wall_time": getattr(tick, "received_wall_time", None),
                        "source": getattr(tick, "source", None),
                        "query_set_id": api._winddown_query_set_for.get(dataname),
                        "source_clock": clock.utc_now().isoformat(),
                    }
                    store_tick_trace.append(observation)
                    chain_trace.append(observation)
                    query_set_id = api._winddown_query_set_for.get(dataname)
                    if query_set_id is not None:
                        api.winddown_tick_observations.append(
                            {
                                "instrument": dataname,
                                "query_set_id": query_set_id,
                                "event_id": getattr(tick, "event_id", None),
                                "event_time": getattr(tick, "event_time", None),
                                "received_wall_time": getattr(tick, "received_wall_time", None),
                                "source": getattr(tick, "source", None),
                            }
                        )
                        api._winddown_query_set_for.pop(dataname, None)
                        api._winddown_scheduled_instruments.discard(dataname)
                    if len(store_tick_trace) > 128:
                        del store_tick_trace[:-128]
                    if len(chain_trace) > 128:
                        del chain_trace[:-128]
                return tick

            store.poll_tick = traced_store_poll_tick

    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "bind_strategy", capture_bound_strategy)

    original_refresh = RUNNER.QueryRefreshLoop.refresh_once

    def counted_refresh(loop):
        # The test fake provider advances its event clock during each typed
        # query. Keep the entire refresh transaction, including publication
        # and its bounded trace record, indivisible from Strategy clock reads.
        with fact_turn_lock:
            with refresh_condition:
                refresh_state["started"] += 1
                started = refresh_state["started"]
                refresh_condition.notify_all()
            refresh_started_at = clock.utc_now()
            try:
                receipt = original_refresh(loop)
                refresh_receipts.append(
                    {
                        "attempt": started,
                        "started_at": refresh_started_at.isoformat(),
                        "completed_at": clock.utc_now().isoformat(),
                        "error_code": getattr(loop, "last_error_code", None),
                        "query_set_id": getattr(
                            getattr(receipt, "query_set", None), "query_set_id", None
                        ),
                        "requested_families": getattr(receipt, "requested_families", None),
                        "attempted_families": getattr(receipt, "attempted_families", None),
                        "pending_families": getattr(receipt, "pending_families", None),
                        "cancelled": getattr(receipt, "cancelled", None),
                        "deadline_reached": getattr(receipt, "deadline_reached", None),
                        "blockers": getattr(receipt, "blockers", None),
                        "provenance": tuple(
                            (
                                getattr(item, "family", None),
                                getattr(item, "target_id", None),
                                getattr(item, "query_complete", None),
                                getattr(item, "source_owned", None),
                                getattr(item, "scope_complete", None),
                                getattr(item, "request_id", None),
                                getattr(item, "completed_at", None),
                            )
                            for item in getattr(receipt, "query_provenance", ())
                        ),
                    }
                )
                query_set = getattr(receipt, "query_set", None)
                api = api_instances[-1] if api_instances else None
                if (
                    api is not None
                    and api._phase == 1
                    and query_set is not None
                    and not getattr(receipt, "blockers", ())
                    and not getattr(receipt, "pending_families", ())
                    and getattr(receipt, "cancelled", False) is False
                    and getattr(receipt, "deadline_reached", False) is False
                    and all(not rows for rows in bars_by_instrument.values())
                    and api.md_client is not None
                ):
                    query_completed_at = query_set.completed_at_utc
                    for instrument, _exchange in route_rows:
                        api.md_client.schedule_winddown_quote(
                            instrument,
                            query_set.query_set_id,
                            query_completed_at,
                        )
                return receipt
            except Exception as exc:
                reconciliation_blockers = tuple(
                    getattr(loop, "last_reconciliation_blockers", ())[:16]
                )
                with refresh_condition:
                    refresh_state["errors"].append(
                        (
                            clock.utc_now().isoformat(),
                            type(exc).__name__,
                            getattr(exc, "code", None),
                            str(exc)[:512],
                            reconciliation_blockers,
                        )
                    )
                note_fill_event(
                    "refresh_failed",
                    exception_type=type(exc).__name__,
                    code=getattr(exc, "code", None),
                    message=str(exc)[:512],
                    runner_reconciliation_blockers=reconciliation_blockers,
                )
                raise
            finally:
                with refresh_condition:
                    refresh_state["completed"] = max(refresh_state["completed"], started)
                    refresh_condition.notify_all()

    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "refresh_once", counted_refresh)
    # Journal timestamps are a test clock leaf, aligned with the typed query
    # source and the same virtual event clock. Production code remains intact.
    monkeypatch.setattr(
        journal_module,
        "time",
        SimpleNamespace(time_ns=clock.time_ns, monotonic=time.monotonic),
    )

    config["live"].update(
        account_scope="alpha003-factor-chain-account",
        strategy_scope="alpha003-factor-chain",
        logical_run_id="alpha003-factor-chain-run",
        journal_path=str(tmp_path / "factor-chain.sqlite"),
        ready_timeout_seconds=1.0,
        refresh_timeout_seconds=1.0,
        refresh_overall_timeout_seconds=5.0,
        refresh_interval_seconds=0.01,
        quote_max_age_seconds=60.0,
        query_max_age_seconds=7200.0,
        shutdown_grace_seconds=5.0,
        allow_writes=True,
        arm_templates=[
            {
                "target": target,
                "md_front": synthetic_store_config["md_address"],
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "alpha003-factor-chain-" + target,
                "preflight_sha256": "b" * 64,
            }
            for target in plan["authorized_targets"]
        ],
    )
    config["risk"]["run_end_policy"] = "CLOSE_ALL"
    config["cohort"].update(
        max_pending_slots=1,
        max_live_bar_age_seconds=30.0,
        max_future_skew_seconds=0.0,
    )
    config["output"]["decision_tape_path"] = str(tmp_path / "factor-chain-tape.jsonl")
    config["output"]["decision_tape_max_bytes"] = 50_000_000
    config_path.write_text(
        runner_fixtures.yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    try:
        result = RUNNER.run_live(
            config,
            config_path,
            plan,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=True,
        )
    except Exception as exc:
        persist_diagnostic("known_cancel_run_exception", error=exc)
        observations = tuple(item for api in api_instances for item in api.tick_observations[-9:])
        cleanup = getattr(exc, "cleanup_results", None)
        failure = getattr(exc, "live_epoch_evidence", None)
        resources = getattr(exc, "retained_live_resources", {})
        resource_names = tuple(resources) if hasattr(resources, "__iter__") else ()
        refresh_loop = resources.get("refresh_loop") if hasattr(resources, "get") else None
        broker = resources.get("broker") if hasattr(resources, "get") else None
        store = resources.get("store") if hasattr(resources, "get") else None
        try:
            broker_shutdown = broker.get_shutdown_summary() if broker is not None else None
        except Exception as summary_error:
            broker_shutdown = type(summary_error).__name__
        try:
            store_health = store.get_command_health() if store is not None else None
        except Exception as health_error:
            store_health = type(health_error).__name__
        strategy = (
            getattr(refresh_loop, "_strategy", None)
            if refresh_loop is not None
            else (captured_strategies[-1] if captured_strategies else None)
        )
        strategy_events = tuple(dict(event) for event in getattr(strategy, "order_events", ()))[
            -12:
        ]
        fact = getattr(strategy, "last_execution_facts", None)
        fact_summary = (
            None
            if fact is None
            else {
                "blockers": getattr(fact, "blockers", None),
                "risk_reduction_blockers": getattr(fact, "risk_reduction_blockers", None),
                "order_cancel_blockers": getattr(fact, "order_cancel_blockers", None),
                "query_set_id": getattr(fact, "query_set_id", None),
            }
        )
        native_calls = tuple(call for api in api_instances for call in api.native_calls)
        raise AssertionError(
            f"actual Cerebro chain failed: {exc}; ticks={observations!r}; "
            f"native_calls={native_calls!r}; resources={resource_names!r}; "
            f"store_write_calls={tuple(store_write_calls)!r}; "
            f"broker_rejections={tuple(broker_rejections)!r}; "
            f"refresh_errors={tuple(refresh_state['errors'])!r}; "
            f"refresh_receipts={tuple(refresh_receipts[-8:])!r}; "
            f"refresh_counts={(refresh_state['started'], refresh_state['completed'])!r}; "
            f"terminal_reconciliation={tuple(reconciliation_observations[-8:])!r}; "
            f"provider_terminal_rows={tuple(query_rows['orders_result'])!r}; "
            f"broker_shutdown={broker_shutdown!r}; store_health={store_health!r}; "
            f"strategy_block_reason={getattr(strategy, 'last_execution_block_reason', None)!r}; "
            f"strategy_events={strategy_events!r}; facts={fact_summary!r}; "
            f"cleanup={cleanup!r}; live_failure={failure!r}"
        ) from exc

    persist_diagnostic("known_cancel_run_returned", result_value={"phase1": result})
    assert len(api_instances) == 1
    cancel_api = api_instances[0]
    assert cancel_api.closed is True
    inserts = [call for call in cancel_api.native_calls if call[0] == "insert"]
    cancels = [call for call in cancel_api.native_calls if call[0] == "cancel"]
    assert inserts, (
        result,
        tuple(store_write_calls),
        tuple(broker_rejections),
        tuple(refresh_receipts[-8:]),
        tuple(
            (
                getattr(strategy, "last_execution_block_reason", None),
                getattr(getattr(strategy, "last_order_plan", None), "status", None),
                getattr(getattr(strategy, "last_order_plan", None), "reason", None),
                getattr(strategy, "last_execution_facts", None),
            )
            for strategy in captured_strategies[-1:]
        ),
        str(diagnostic_path),
    )
    assert cancels, result
    assert all(call[2] == "DCE" for call in inserts + cancels)
    assert result["write_mode"] is True
    assert result["shutdown_status"] == "PASS"
    events = result["strategy_order_events"]["events"]
    assert any(event["status"] == "ACCEPTED" for event in events), events
    assert any(event["status"] == "CANCELED" for event in events), events
    assert result["cleanup_complete"] is True

    # Start a second source-backed run on fresh journal/query state.  Its
    # factor OPEN receives one full CTP fill through the ordinary callback
    # queue, and the strategy then sends its configured run-end CLOSE_ALL.
    query_rows.clear()
    query_rows.update(make_query_rows())
    bars_by_instrument.clear()
    refill_bars()
    clock.reset(event_times)
    # The first run also exercises a fast refresh cadence while bars arrive.
    # During the second run, allow one bounded quote-only maintenance turn to
    # consume every target's real post-query tick before the next full query
    # set supersedes that snapshot. Query age and quote freshness gates remain
    # unchanged; only the fake run's refresh schedule is realistic for this
    # three-feed provider cadence.
    config["live"]["refresh_interval_seconds"] = 0.25
    config["live"].update(
        logical_run_id="alpha003-factor-chain-fill-close-run",
        journal_path=str(tmp_path / "factor-chain-fill-close.sqlite"),
    )
    config["output"]["decision_tape_path"] = str(tmp_path / "factor-chain-fill-close-tape.jsonl")
    config_path.write_text(
        runner_fixtures.yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    try:
        fill_close_result = RUNNER.run_live(
            config,
            config_path,
            plan,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=True,
        )
    except Exception as exc:
        persist_diagnostic("fill_close_run_exception", result_value={"phase1": result}, error=exc)
        resources = getattr(exc, "retained_live_resources", {})
        refresh_loop = resources.get("refresh_loop") if hasattr(resources, "get") else None
        live_failure = getattr(exc, "live_epoch_evidence", None)
        live_failure_summary = (
            None
            if not isinstance(live_failure, dict)
            else {
                key: live_failure.get(key)
                for key in (
                    "engine_winddown_status",
                    "engine_winddown_reason",
                    "strategy_shutdown_requested",
                    "strategy_shutdown_ready",
                    "strategy_shutdown_blocker",
                    "strategy_shutdown_post_join_confirmed",
                    "strategy_shutdown_post_join_blocker",
                    "refresh_status",
                    "refresh_blocker",
                    "refresh_error_code",
                    "reconciliation_blockers",
                    "strategy_order_events",
                )
            }
        )
        strategy = (
            getattr(refresh_loop, "_strategy", None)
            if refresh_loop is not None
            else (captured_strategies[-1] if captured_strategies else None)
        )
        broker = resources.get("broker") if hasattr(resources, "get") else None
        broker_positions = []
        if broker is not None and strategy is not None:
            for data in tuple(getattr(strategy, "datas", ())):
                try:
                    position = broker.execution_position_snapshot(data)
                    broker_positions.append(
                        (getattr(data, "_name", None), position, broker.getposition(data).size)
                    )
                except Exception as snapshot_error:
                    broker_positions.append(
                        (getattr(data, "_name", None), type(snapshot_error).__name__)
                    )
        fact = getattr(strategy, "last_execution_facts", None)
        native_calls = tuple(call for api in api_instances for call in api.native_calls)
        first_bad_reconciliation = next(
            (
                observation
                for observation in reconciliation_observations
                if any(
                    item[1] not in {"RESOLVED", "DUPLICATE", "EXTERNAL_TERMINAL_FLAT"}
                    for item in observation["items"]
                )
            ),
            None,
        )
        callback_index = next(
            (
                index
                for index, event in enumerate(fill_timeline)
                if event["kind"] == "provider_callback_fill"
            ),
            0,
        )
        fill_timing_window = tuple(fill_timeline[callback_index : callback_index + 28])
        terminal_tail = tuple(
            (
                observation["query_set_id"],
                observation["available_at"],
                tuple((item[1], item[2]) for item in observation["items"]),
            )
            for observation in reconciliation_observations[-8:]
        )
        refresh_tail = tuple(
            (
                receipt["attempt"],
                receipt["error_code"],
                receipt["query_set_id"],
                receipt["blockers"],
            )
            for receipt in refresh_receipts[-8:]
        )
        strategy_state = (
            None
            if strategy is None
            else (
                getattr(strategy, "shutdown_requested", None),
                getattr(strategy, "shutdown_ready", None),
                getattr(strategy, "shutdown_blocker", None),
                getattr(strategy, "last_execution_block_reason", None),
            )
        )
        plan = getattr(strategy, "last_order_plan", None)
        plan_summary = (
            None
            if plan is None
            else {
                "status": getattr(plan, "status", None),
                "reason": getattr(plan, "reason", None),
                "actions": tuple(
                    (
                        getattr(action, "action", None),
                        getattr(action, "target_id", None),
                        getattr(action, "instrument", None),
                        getattr(action, "side", None),
                        getattr(action, "position_effect", None),
                        getattr(action, "quantity", None),
                        getattr(action, "offset", None),
                        getattr(action, "reason", None),
                    )
                    for action in getattr(plan, "actions", ())
                ),
                "decision_available_at": getattr(plan, "decision_available_at", None),
                "decision_batch_id": getattr(plan, "decision_batch_id", None),
            }
        )
        fact_summary = (
            None
            if fact is None
            else {
                "blockers": getattr(fact, "blockers", None),
                "risk_reduction_blockers": getattr(fact, "risk_reduction_blockers", None),
                "order_cancel_blockers": getattr(fact, "order_cancel_blockers", None),
                "risk_reduction_ready": getattr(fact, "risk_reduction_ready", None),
                "open_risk_ready": getattr(fact, "open_risk_ready", None),
                "snapshot_id": getattr(fact, "snapshot_id", None),
                "query_set_id": getattr(fact, "query_set_id", None),
                "available_at": getattr(fact, "available_at", None),
                "account": getattr(fact, "account", None),
                "positions": tuple(
                    (
                        getattr(position, "target_id", None),
                        getattr(position, "instrument", None),
                        getattr(position, "quantity", None),
                        getattr(position, "owner_strategy_scope", None),
                        getattr(position, "owner_intent_id", None),
                        getattr(position, "average_price", None),
                        getattr(position, "stop_price", None),
                        getattr(position, "held_eligible_bars", None),
                        getattr(position, "position_book_status", None),
                        getattr(position, "position_book_blocker_code", None),
                    )
                    for position in getattr(fact, "positions", ())
                ),
                "quotes": tuple(
                    (
                        getattr(quote, "instrument", None),
                        getattr(quote, "bid", None),
                        getattr(quote, "ask", None),
                        getattr(quote, "event_time", None),
                        getattr(quote, "available_at", None),
                        getattr(quote, "quality", None),
                    )
                    for quote in getattr(fact, "quotes", ())
                ),
                "working_orders": tuple(
                    (
                        getattr(order, "instrument", None),
                        getattr(order, "state", None),
                        getattr(order, "position_effect", None),
                        getattr(order, "owner_intent_id", None),
                        getattr(order, "remaining_quantity", None),
                    )
                    for order in getattr(fact, "working_orders", ())
                ),
            }
        )
        query_completion_trace = tuple(
            (
                receipt["attempt"],
                receipt["query_set_id"],
                max((item[-1] for item in receipt["provenance"]), default=None),
            )
            for receipt in refresh_receipts[-8:]
        )
        tick_trace_summary = tuple(
            (
                item["sequence"],
                item["instrument"],
                item["query_set_id"],
                item["event_time"],
                item["received_wall_time"],
                item["source_clock"],
            )
            for item in store_tick_trace[-12:]
        )
        store_write_summary = tuple(
            (
                call.get("operation"),
                ((call.get("identity") or {}).get("info") or {}).get("instrument_id"),
                ((call.get("identity") or {}).get("info") or {}).get("exchange_id"),
                (call.get("identity") or {}).get("size"),
                ((call.get("identity") or {}).get("info") or {}).get("factor_position_effect"),
                ((call.get("identity") or {}).get("info") or {}).get("factor_intent_id"),
                ((call.get("identity") or {}).get("info") or {}).get("offset"),
                call.get("result"),
            )
            for call in store_write_calls[-12:]
        )
        idle_trace_summary = tuple(
            (
                item["sequence"],
                item["now"],
                item["query_set_id"],
                item["facts_available_at"],
                item["risk_reduction_ready"],
                item["risk_reduction_blockers"],
                item["positions"],
                item["quotes"],
                item["plan"],
                item["shutdown"],
            )
            for item in idle_decision_trace[-12:]
        )
        raise AssertionError(
            f"factor-driven OPEN/fill/CLOSE run failed: {exc}; "
            f"native_calls={native_calls!r}; "
            f"store_writes={store_write_summary!r}; "
            f"risk_scopes={tuple(risk_scope_trace[-8:])!r}; "
            f"risk_dispatch={tuple(risk_dispatch_trace[-8:])!r}; "
            f"broker_rejections={tuple(broker_rejections[-8:])!r}; "
            f"refresh_errors={tuple(refresh_state['errors'][:4])!r}; "
            f"refresh_tail={refresh_tail!r}; "
            f"fill_timing_window={fill_timing_window!r}; "
            f"query_completion_trace={query_completion_trace!r}; "
            f"terminal_tail={terminal_tail!r}; "
            f"first_bad_terminal_reconciliation={first_bad_reconciliation!r}; "
            f"broker_updates={tuple(broker_update_observations[-8:])!r}; "
            f"runner_reconciliation_blockers={tuple(getattr(refresh_loop, 'last_reconciliation_blockers', ())[-16:])!r}; "
            f"strategy_state={strategy_state!r}; "
            f"strategy_plan={plan_summary!r}; strategy_fact={fact_summary!r}; "
            f"live_failure={live_failure_summary!r}; "
            f"quote_only_tail={tuple(api_instances[-1].winddown_tick_observations[-9:])!r}; "
            f"store_tick_trace={tick_trace_summary!r}; "
            f"idle_decision_trace={idle_trace_summary!r}; "
            f"last_execution_block_reason={getattr(strategy, 'last_execution_block_reason', None)!r}; "
            f"remaining_source_bars={tuple((key, len(value)) for key, value in api_instances[-1]._source_bars.items())!r}; "
            f"winddown_poll_attempts={api_instances[-1].winddown_poll_attempts}; "
            f"winddown_poll_blockers={tuple(api_instances[-1].winddown_poll_blockers[-8:])!r}"
        ) from exc

    persist_diagnostic(
        "fill_close_run_returned",
        result_value={"phase1": result, "phase2": fill_close_result},
    )
    assert len(api_instances) == 2
    fill_close_api = api_instances[1]
    assert fill_close_api.closed is True
    submissions = [call for call in store_write_calls if call["operation"] == "submit"]
    assert any(
        call["identity"]["info"].get("factor_position_effect") == "OPEN" for call in submissions
    ), submissions
    assert any(
        call["identity"]["info"].get("factor_position_effect") == "CLOSE" for call in submissions
    ), (
        "ordinary Alpha003 produced no factor CLOSE; "
        f"submissions={tuple((call['identity']['data_name'], call['identity']['size'], call['identity']['info'].get('factor_position_effect'), call['identity']['info'].get('factor_intent_id'), call['identity']['info'].get('factor_reason'), call['identity']['info'].get('offset')) for call in submissions)!r}; "
        f"native_calls={tuple(fill_close_api.native_calls)!r}; "
        f"strategy_events={fill_close_result['strategy_order_events']!r}; "
        f"reconciliation={tuple(reconciliation_observations[-12:])!r}; "
        f"broker_updates={tuple(broker_update_observations[-12:])!r}; "
        f"fill_timeline={tuple(fill_timeline)!r}; "
        f"provider_positions={tuple(query_rows['positions_result'])!r}; "
        f"provider_trades={tuple(query_rows['trades_result'])!r}; "
        f"shutdown={(fill_close_result['shutdown_status'], fill_close_result['strategy_shutdown_blocker'], fill_close_result['strategy_shutdown_post_join_blocker'])!r}"
    )
    filled_open_instruments = {
        str(row.get("InstrumentID"))
        for row in query_rows["trades_result"]
        if str(row.get("OffsetFlag")) == "0"
    }
    assert filled_open_instruments, query_rows["trades_result"]
    assert any(
        call[0] == "insert" and call[1] in filled_open_instruments
        for call in fill_close_api.native_calls
    ), (fill_close_api.native_calls, filled_open_instruments)
    assert any(call[0] == "cancel" for call in fill_close_api.native_calls)
    assert fill_close_result["write_mode"] is True
    assert fill_close_result["shutdown_status"] == "PASS"
    fill_close_events = fill_close_result["strategy_order_events"]["events"]
    assert any(event["status"] == "COMPLETED" for event in fill_close_events), fill_close_events
    assert any(event["status"] == "CANCELED" for event in fill_close_events), fill_close_events
    assert fill_close_result["cleanup_complete"] is True

    shutdown = {item["resource"]: item for item in fill_close_result["resource_shutdown"]}
    assert shutdown["query_refresh"]["joined"] is True, shutdown
    assert shutdown["query_refresh"]["status"] == "RETURNED", shutdown
    assert shutdown["broker"]["status"] == "PASS", shutdown
    assert shutdown["broker"]["store_shutdown_state"] == "PASS", shutdown
    assert shutdown["store"]["status"] == "CLOSED_BY_BROKER", shutdown
    assert shutdown["store"]["shutdown_state"] == "PASS", shutdown
    assert shutdown["journal"]["status"] == "CLOSED", shutdown
    assert shutdown["decision_tape"]["status"] == "CLOSED", shutdown
    assert fill_close_result["decision_tape"]["closed"] is True
    assert fill_close_result["decision_tape"]["failed"] is False
    assert fill_close_result["decision_tape_readback"]["record_count"] == (
        fill_close_result["decision_tape"]["record_count"]
    )

    # Observe the original Strategy notify_trade events and the actual
    # Backtrader Trade object passed by Broker.  The strategy event intentionally
    # publishes aggregate PnL (gross/net), while the real Trade object carries
    # the aggregate commission used to derive the net value.
    fill_close_strategy_index = len(captured_strategies) - 1
    strategy_trade_events = tuple(dict(event) for event in captured_strategies[-1].trade_events)
    trade_observations = tuple(
        observation
        for observation in trade_notify_observations
        if observation["strategy_index"] == fill_close_strategy_index
    )
    assert tuple(event["status"] for event in strategy_trade_events) == ("OPEN", "CLOSED"), (
        strategy_trade_events,
        trade_observations,
    )
    assert len(trade_observations) == len(strategy_trade_events) == 2
    assert tuple(observation["event"] for observation in trade_observations) == (
        strategy_trade_events
    )
    assert tuple(observation["isclosed"] for observation in trade_observations) == (
        False,
        True,
    )
    for event, observation in zip(strategy_trade_events, trade_observations):
        assert event["ref"] == observation["trade_ref"]
        for field in ("size", "price", "pnl", "pnlcomm"):
            assert Decimal(event[field]) == Decimal(observation[field]), (
                event,
                observation,
                field,
            )

    close_submissions = [
        call
        for call in submissions
        if call["identity"]["info"].get("factor_position_effect") == "CLOSE"
    ]
    assert len(close_submissions) == 1, close_submissions
    close_identity = close_submissions[0]["identity"]
    close_intent_id = close_identity["info"].get("factor_intent_id")
    assert isinstance(close_intent_id, str) and close_intent_id
    close_trades = [
        row
        for row in query_rows["trades_result"]
        if str(row.get("InstrumentID")) == str(close_identity["info"].get("instrument_id"))
        and str(row.get("OffsetFlag")) == "1"
    ]
    assert len(close_trades) == 1, close_trades
    close_trade = close_trades[0]
    open_trades = [
        row
        for row in query_rows["trades_result"]
        if str(row.get("InstrumentID")) == str(close_identity["info"].get("instrument_id"))
        and str(row.get("OffsetFlag")) == "0"
    ]
    assert len(open_trades) == 1, open_trades
    open_trade = open_trades[0]

    open_event, closed_event = strategy_trade_events
    open_observation, closed_observation = trade_observations
    assert open_observation["instrument_id"] == closed_observation["instrument_id"]
    assert open_observation["instrument_id"] == str(open_trade["InstrumentID"])
    assert closed_observation["instrument_id"] == str(close_trade["InstrumentID"])
    assert open_event["ref"] == closed_event["ref"]
    assert open_event["status"] == "OPEN" and closed_event["status"] == "CLOSED"

    open_quantity = Decimal(str(open_trade["Volume"]))
    open_direction = str(open_trade["Direction"])
    assert open_direction in {"0", "1"}, open_trade
    signed_open_quantity = open_quantity if open_direction == "0" else -open_quantity
    assert Decimal(open_event["size"]) == signed_open_quantity, (open_event, open_trade)
    assert open_observation["long"] is (signed_open_quantity > 0), (
        open_observation,
        open_trade,
    )
    assert Decimal(closed_event["size"]) == 0, (closed_event, close_trade)
    assert closed_observation["long"] is open_observation["long"]

    open_price = Decimal(str(open_trade["Price"]))
    close_price = Decimal(str(close_trade["Price"]))
    close_direction = str(close_trade["Direction"])
    assert close_direction in {"0", "1"}, close_trade
    assert close_direction != open_direction, (open_trade, close_trade)
    assert Decimal(str(close_trade["Volume"])) == open_quantity, (open_trade, close_trade)
    assert Decimal(open_event["price"]) == open_price, (open_event, open_trade)
    # A closed Backtrader Trade retains its average entry price.  Its realized
    # closing execution price and quantity are reported by the completed order
    # projection and the source-backed CTP trade row below.
    assert Decimal(closed_event["price"]) == open_price, (closed_event, open_trade)
    assert close_price == open_price
    instrument_row = next(
        row
        for row in query_rows["instruments_result"]
        if str(row.get("InstrumentID")) == str(open_trade["InstrumentID"])
        and str(row.get("ExchangeID")) == str(open_trade["ExchangeID"])
    )
    expected_gross_pnl = (
        (close_price - open_price)
        * signed_open_quantity
        * Decimal(str(instrument_row["VolumeMultiple"]))
    )
    assert Decimal(open_event["pnl"]) == 0
    assert Decimal(closed_event["pnl"]) == expected_gross_pnl
    for event, observation in zip(strategy_trade_events, trade_observations):
        event_commission = Decimal(event["pnl"]) - Decimal(event["pnlcomm"])
        trade_commission = Decimal(observation["commission"])
        assert abs(event_commission - trade_commission) <= Decimal("0.00000001"), (
            event,
            observation,
        )
    assert Decimal(closed_observation["commission"]) >= Decimal(open_observation["commission"]) >= 0

    # Reopen the exact run journal only after Runner reports it CLOSED.  The
    # archive verifier and the read-only SQL below bind the provider callback,
    # native OrderRef, complete-query terminal observation, flat position
    # snapshot, and durable intent resolution for this actual Strategy CLOSE.
    from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
    from backtrader.stores.execution_journal_archive import (
        verify_execution_journal_archive,
    )

    journal_path = tmp_path / "factor-chain-fill-close.sqlite"
    archive_path = tmp_path / "factor-chain-fill-close-archive.sqlite3"
    archive_writer = ExecutionDecisionJournal(journal_path)
    try:
        archive_receipt = archive_writer.archive_snapshot(archive_path)
    finally:
        archive_writer.close()
    assert (
        verify_execution_journal_archive(
            archive_path,
            expected_schema_version=ExecutionDecisionJournal._SCHEMA_VERSION,
            expected_sha256=archive_receipt.sha256,
        )
        == archive_receipt
    )
    with closing(sqlite3.connect(archive_path.as_uri() + "?mode=ro", uri=True)) as archived:
        archived.execute("PRAGMA query_only = ON")
        callback_bindings = archived.execute(
            """SELECT i.intent_id,n.order_ref,n.instrument,n.exchange,n.trading_day,
                      c.receipt_id,c.callback_id,c.acknowledged,c.evidence_payload_json
               FROM execution_decision_callbacks AS c
               JOIN execution_decision_intents AS i ON i.intent_id=c.intent_id
               JOIN execution_native_intent_identities AS n ON n.intent_id=i.intent_id
               WHERE c.acknowledged=1
               ORDER BY c.created_at_ns"""
        ).fetchall()
        terminal_chain = archived.execute(
            """SELECT n.order_ref,n.instrument,n.exchange,n.trading_day,
                      c.callback_id,c.acknowledged,c.evidence_payload_json,
                      r.query_id,r.state,r.terminal_state,r.terminal_event_id,
                      r.position_snapshot_id,r.position_flat,
                      z.terminal_state,z.terminal_event_id,z.reconciliation_id,
                      z.position_snapshot_id,z.position_flat
               FROM execution_decision_intents AS i
               JOIN execution_native_intent_identities AS n ON n.intent_id=i.intent_id
               JOIN execution_decision_callbacks AS c
                 ON c.intent_id=i.intent_id AND c.callback_id LIKE 'ctp-trade:%'
               JOIN execution_intent_reconciliations AS r ON r.intent_id=i.intent_id
               JOIN execution_intent_resolutions AS z ON z.intent_id=i.intent_id
               WHERE i.intent_id=?
               ORDER BY r.created_at_ns DESC,c.created_at_ns DESC,c.callback_id ASC LIMIT 1""",
            (close_intent_id,),
        ).fetchone()
    assert terminal_chain is not None, close_intent_id
    (
        native_order_ref,
        native_instrument,
        native_exchange,
        native_trading_day,
        callback_id,
        callback_acknowledged,
        callback_payload_json,
        query_id,
        reconciliation_state,
        terminal_state,
        terminal_event_id,
        position_snapshot_id,
        position_flat,
        resolution_state,
        resolution_event_id,
        resolution_id,
        resolution_snapshot_id,
        resolution_flat,
    ) = terminal_chain
    callback_payload = json.loads(callback_payload_json)
    assert native_order_ref == str(close_trade["OrderRef"]), terminal_chain
    assert native_instrument == str(close_trade["InstrumentID"]), terminal_chain
    assert native_exchange == str(close_trade["ExchangeID"]), terminal_chain
    assert native_trading_day == str(close_trade["TradingDay"]), terminal_chain
    assert callback_id and callback_acknowledged == 1, terminal_chain
    assert callback_payload.get("evidence_kind") == "native_trade_callback", terminal_chain
    assert callback_payload["provider_trade_id"] == str(close_trade["TradeID"]), (
        callback_payload,
        close_trade,
    )
    assert query_id == terminal_event_id
    assert reconciliation_state == "KNOWN"
    assert terminal_state == resolution_state == "FILLED"
    assert resolution_event_id == terminal_event_id
    assert resolution_id
    assert position_snapshot_id == resolution_snapshot_id
    assert position_flat == resolution_flat == 1
    assert any(
        call[0] == "insert"
        and call[1] == native_instrument
        and call[2] == native_exchange
        and call[3] == native_order_ref
        for call in fill_close_api.native_calls
    ), (fill_close_api.native_calls, terminal_chain)

    callbacks_by_trade_id = defaultdict(list)
    for row in callback_bindings:
        payload = json.loads(row[8])
        trade_id = payload.get("provider_trade_id")
        if trade_id in {str(open_trade["TradeID"]), str(close_trade["TradeID"])}:
            callbacks_by_trade_id[trade_id].append((row, payload))
    assert set(callbacks_by_trade_id) == {
        str(open_trade["TradeID"]),
        str(close_trade["TradeID"]),
    }, callbacks_by_trade_id
    open_native_rows = [
        row
        for row, payload in callbacks_by_trade_id[str(open_trade["TradeID"])]
        if payload.get("evidence_kind") == "native_trade_callback"
    ]
    assert len(open_native_rows) == 1, open_native_rows
    open_intent_id = open_native_rows[0][0]

    completed_order_events = [
        event
        for event in fill_close_result["strategy_order_events"]["events"]
        if event["status"] == "COMPLETED"
    ]
    for trade_row, effect, trade_observation in (
        (open_trade, "OPEN", open_observation),
        (close_trade, "CLOSE", closed_observation),
    ):
        native_ref = str(trade_row["OrderRef"])
        trade_id = str(trade_row["TradeID"])
        callback_pair = callbacks_by_trade_id[trade_id]
        assert len(callback_pair) == 2, (trade_id, callback_pair)
        callback_by_kind = {}
        for callback_row, callback_payload in callback_pair:
            evidence_kind = callback_payload.get("evidence_kind")
            assert evidence_kind in {
                "native_trade_callback",
                "complete_trades_query_observation",
            }, (trade_id, callback_row, callback_payload)
            assert evidence_kind not in callback_by_kind, (trade_id, callback_pair)
            callback_by_kind[evidence_kind] = (callback_row, callback_payload)
            assert callback_row[7] == 1, (trade_id, callback_row)
        assert set(callback_by_kind) == {
            "native_trade_callback",
            "complete_trades_query_observation",
        }, (trade_id, callback_by_kind)
        native_callback_row, native_callback_payload = callback_by_kind["native_trade_callback"]
        query_callback_row, query_callback_payload = callback_by_kind[
            "complete_trades_query_observation"
        ]
        assert native_callback_row[:5] == query_callback_row[:5], (
            native_callback_row,
            query_callback_row,
        )
        native_receipt_id, native_callback_id = native_callback_row[5:7]
        query_receipt_id, query_callback_id = query_callback_row[5:7]
        assert native_receipt_id != query_receipt_id, callback_pair
        assert native_callback_id.startswith("ctp-trade:"), native_callback_row
        assert query_callback_id.startswith("query-trade:"), query_callback_row
        native_digest = native_callback_id[len("ctp-trade:") :]
        query_digest = query_callback_id[len("query-trade:") :]
        assert len(native_digest) == len(query_digest) == 64, callback_pair
        assert native_digest == query_digest and all(
            char in "0123456789abcdef" for char in native_digest
        ), callback_pair
        intent_id, observed_native_ref, instrument, exchange, trading_day = native_callback_row[:5]
        assert observed_native_ref == native_ref, (native_callback_row, trade_row)
        assert instrument == str(trade_row["InstrumentID"]), (native_callback_row, trade_row)
        assert exchange == str(trade_row["ExchangeID"]), (native_callback_row, trade_row)
        assert trading_day == str(trade_row["TradingDay"]), (native_callback_row, trade_row)
        expected_execution_id = "ctp:{}:{}".format(trade_row["TradeDate"], trade_id)
        local_fill_time = datetime.strptime(
            "{} {}".format(trade_row["TradeDate"], trade_row["TradeTime"]),
            "%Y%m%d %H:%M:%S",
        ).replace(tzinfo=timezone(timedelta(hours=8)))
        utc_fill_time = local_fill_time.astimezone(UTC)
        utc_epoch = datetime(1970, 1, 1, tzinfo=UTC)
        elapsed = utc_fill_time - utc_epoch
        expected_filled_at_ns = (
            elapsed.days * 86400 + elapsed.seconds
        ) * 1_000_000_000 + elapsed.microseconds * 1_000
        expected_common_payload = {
            "event_type": "execution_fill",
            "exchange": exchange,
            "execution_id": expected_execution_id,
            "fee": None,
            "filled_at_ns": expected_filled_at_ns,
            "instrument_id": instrument,
            "order_ref": native_ref,
            "order_sys_id": str(trade_row["OrderSysID"]),
            "price": str(Decimal(str(trade_row["Price"]))),
            "provider_trade_id": trade_id,
            "quantity": str(Decimal(str(trade_row["Volume"]))),
            "time_source": "CTP_TradeDate_TradeTime_UTC_PLUS_08",
        }
        for field, expected in expected_common_payload.items():
            assert native_callback_payload.get(field) == expected, (
                trade_id,
                field,
                native_callback_payload,
            )
            assert query_callback_payload.get(field) == expected, (
                trade_id,
                field,
                query_callback_payload,
            )
        assert query_callback_payload.get("evidence_kind") == ("complete_trades_query_observation")
        assert query_callback_payload.get("query_observation_id")
        assert query_callback_payload.get("snapshot_id")
        assert query_callback_payload.get("request_id", 0) > 0
        assert query_callback_payload.get("connection_generation", 0) > 0
        assert query_callback_payload.get("account_fingerprint") == (
            "alpha003-factor-chain-account"
        )
        assert query_callback_payload.get("account_scope") == ("alpha003-factor-chain-account")
        assert query_callback_payload.get("strategy_scope") == "alpha003-factor-chain"
        assert query_callback_payload.get("trading_day") == trading_day
        assert native_callback_row[0] == query_callback_row[0] == intent_id
        if effect == "OPEN":
            assert str(trade_row["OffsetFlag"]) == "0", trade_row
            assert str(trade_row["Direction"]) in {"0", "1"}, trade_row
        else:
            assert str(trade_row["OffsetFlag"]) == "1", trade_row
        matching_submissions = [
            call
            for call in submissions
            if call["identity"]["info"].get("factor_intent_id") == intent_id
            and call["identity"]["info"].get("factor_position_effect") == effect
        ]
        assert len(matching_submissions) == 1, (trade_row, native_callback_row, submissions)
        submission = matching_submissions[0]["identity"]
        assert Decimal(str(abs(submission["size"]))) == Decimal(str(trade_row["Volume"]))
        assert trade_observation["instrument_id"] == instrument
        order_events = [
            event for event in completed_order_events if event["ref"] == submission["ref"]
        ]
        assert len(order_events) == 1, (submission, completed_order_events)
        assert Decimal(order_events[0]["executed_size"]) == Decimal(str(submission["size"]))
        assert Decimal(order_events[0]["executed_price"]) == Decimal(str(trade_row["Price"]))
        assert any(
            call[0] == "insert"
            and call[1] == str(trade_row["InstrumentID"])
            and call[2] == str(trade_row["ExchangeID"])
            and call[3] == native_ref
            for call in fill_close_api.native_calls
        ), (trade_row, fill_close_api.native_calls)
        with closing(sqlite3.connect(archive_path.as_uri() + "?mode=ro", uri=True)) as archived:
            archived.execute("PRAGMA query_only = ON")
            position_fills = archived.execute(
                """SELECT account_scope,instrument,exchange,execution_id,receipt_id,
                          intent_id,strategy_scope,position_effect,order_side,
                          owner_intent_id,quantity,price,fee,filled_at_ns
                   FROM factor_position_fills WHERE intent_id=?""",
                (intent_id,),
            ).fetchall()
        assert len(position_fills) == 1, (trade_id, position_fills)
        (
            account_scope,
            fill_instrument,
            fill_exchange,
            fill_execution_id,
            fill_receipt_id,
            fill_intent_id,
            strategy_scope,
            position_effect,
            order_side,
            owner_intent_id,
            fill_quantity,
            fill_price,
            fill_fee,
            fill_filled_at_ns,
        ) = position_fills[0]
        expected_side = "BUY" if str(trade_row["Direction"]) == "0" else "SELL"
        expected_owner_intent = None if effect == "OPEN" else open_intent_id
        assert account_scope == "alpha003-factor-chain-account", position_fills
        assert fill_instrument == instrument and fill_exchange == exchange, position_fills
        assert fill_execution_id == expected_execution_id, position_fills
        assert fill_receipt_id in {native_receipt_id, query_receipt_id}, position_fills
        assert fill_intent_id == intent_id, position_fills
        assert strategy_scope == "alpha003-factor-chain", position_fills
        assert position_effect == effect and order_side == expected_side, position_fills
        assert owner_intent_id == expected_owner_intent, position_fills
        assert Decimal(fill_quantity) == Decimal(str(trade_row["Volume"])), position_fills
        assert Decimal(fill_price) == Decimal(str(trade_row["Price"])), position_fills
        assert fill_fee is None, position_fills
        assert fill_filled_at_ns == expected_filled_at_ns, position_fills
    with closing(sqlite3.connect(archive_path.as_uri() + "?mode=ro", uri=True)) as archived:
        archived.execute("PRAGMA query_only = ON")
        all_position_fills = archived.execute(
            "SELECT execution_id,intent_id FROM factor_position_fills ORDER BY execution_id"
        ).fetchall()
    assert len(all_position_fills) == 2, all_position_fills
    assert {row[0] for row in all_position_fills} == {
        "ctp:{}:{}".format(open_trade["TradeDate"], open_trade["TradeID"]),
        "ctp:{}:{}".format(close_trade["TradeDate"], close_trade["TradeID"]),
    }, all_position_fills
    persist_diagnostic(
        "complete",
        result_value={"phase1": result, "phase2": fill_close_result},
        archive_evidence={
            "path": str(archive_path),
            "sha256": archive_receipt.sha256,
            "size_bytes": archive_receipt.size_bytes,
            "table_row_counts": dict(archive_receipt.table_row_counts),
            "verified": True,
            "terminal_chain": terminal_chain,
            "provider_trade_id": close_trade.get("TradeID"),
            "strategy_trade_events": strategy_trade_events,
            "trade_notify_observations": trade_observations,
        },
    )
