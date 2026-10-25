"""Source-backed Alpha003 execution across an explicit main-contract rollover.

The only synthetic inputs are the CTP SDK leaves and finite bar/tick tapes.
The daily runner, selection bundles, Cerebro engines, Alpha003 Strategy,
RegisteredSim Store, Broker, coordinator, journal, query refresh and shutdown
paths are the production implementations.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from enum import Enum
import importlib
import json
import math
import threading
import time
from types import SimpleNamespace

import pytest

from tests.unit import test_alpha003_simnow_runner as runner_fixtures
from tests.unit.stores import test_factor_execution_facts as facts_fixtures


RUNNER = runner_fixtures.RUNNER
UTC = timezone.utc
LOCAL = timezone(timedelta(hours=8))
_BAR_COUNT = 50
_QUOTE_TICK_SIZE = Decimal("0.1")


def _epoch_price_offset(epoch_id):
    return 100.0 * (epoch_id - 1)


def _tick_aligned_quote_prices(price, tick_size=_QUOTE_TICK_SIZE):
    last = Decimal(str(price))
    tick = Decimal(str(tick_size))
    tick_count = last / tick
    bid = tick_count.to_integral_value(rounding=ROUND_FLOOR) * tick
    ask = tick_count.to_integral_value(rounding=ROUND_CEILING) * tick
    if bid == ask:
        bid -= tick
        ask += tick
    rounded_last = tick_count.to_integral_value(rounding=ROUND_HALF_UP) * tick
    return rounded_last, bid, ask


def _bar_rows(plan, *, epoch_id, clock_domain_id):
    rows_by_instrument = defaultdict(deque)
    source_events = []
    for ordinal, minute in enumerate(plan["grid"].minutes[:_BAR_COUNT], 1):
        members = {member.product: member for member in minute.members}
        for target_index, target in enumerate(plan["targets"]):
            product = plan["product_by_target"][target]
            instrument = plan["routes"][product]
            member = members[product]
            close_time = minute.close_time
            start_time = close_time - timedelta(minutes=1)
            offset = _epoch_price_offset(epoch_id)
            open_price = (
                100.0
                + offset
                + (ordinal % 7) * 0.13
                + ((ordinal * (target_index + 1)) % 5) * 0.07
                + target_index * 0.03
            )
            close_price = open_price + (0.2 if (ordinal + target_index) % 2 else -0.2)
            row = {
                "instrument": instrument,
                "symbol": instrument,
                "exchange": product.exchange_id,
                "bucket_start": start_time,
                "bucket_end": close_time,
                "available_at": close_time + timedelta(seconds=2),
                "trading_day": member.trading_day.strftime("%Y%m%d"),
                "session_segment": member.session_id,
                "timezone_id": "UTC",
                "clock_domain_id": clock_domain_id,
                "connection_generation": "roll-epoch-{}-generation-1".format(epoch_id),
                "bar_sequence": ordinal,
                "bar_id": "epoch-{}:{}:{}".format(epoch_id, target, ordinal),
                "timestamp": close_time.timestamp(),
                "present": True,
                "complete": True,
                "quality": "GOOD",
                "quality_flags": (),
                "open": open_price,
                "high": max(open_price, close_price) + 0.5,
                "low": min(open_price, close_price) - 0.5,
                "close": close_price,
                "volume": float(100 + ((ordinal * (target_index + 2)) % 11) * 10),
                "openinterest": 0.0,
            }
            rows_by_instrument[instrument].append(row)
            source_events.append(row)
    return rows_by_instrument, tuple(source_events)


def _truncate_plan(plan):
    result = dict(plan)
    result["grid"] = replace(plan["grid"], minutes=plan["grid"].minutes[:_BAR_COUNT])
    return result


def _has_causal_action_facts(rows, expected_instruments):
    for row in rows:
        source = row.get("execution_fact_source")
        if not isinstance(source, dict) or not source.get("query_set_id"):
            continue
        snapshot_at = source.get("available_at")
        projection_now = source.get("projection_now")
        quotes = tuple(source.get("quotes", ()))
        if (
            not isinstance(snapshot_at, datetime)
            or not isinstance(projection_now, datetime)
            or {quote[0] for quote in quotes} != set(expected_instruments)
        ):
            continue
        if all(
            isinstance(event_at, datetime)
            and isinstance(received_at, datetime)
            and snapshot_at <= event_at <= received_at <= projection_now
            for _instrument, event_at, received_at, _quality in quotes
        ):
            return True
    return False


def _diagnostic_json_value(value, *, depth=0):
    """Project bounded source-fake diagnostics to JSON-safe public scalars."""

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _diagnostic_json_value(value.value, depth=depth + 1)
    if value is None or type(value) in (bool, int, str):
        return value[:512] if type(value) is str else value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if depth >= 5:
        return "<depth-limit>"
    if isinstance(value, dict):
        return {
            str(key)[:128]: _diagnostic_json_value(item, depth=depth + 1)
            for key, item in tuple(value.items())[:32]
        }
    if isinstance(value, (tuple, list)):
        return [_diagnostic_json_value(item, depth=depth + 1) for item in value[:32]]
    return "<{}>".format(type(value).__name__)


def _write_rollover_diagnostic(path, payload):
    projected = _diagnostic_json_value(payload)
    encoded = json.dumps(
        projected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    raw = encoded.encode("utf-8")
    if len(raw) > 32_768:
        raise AssertionError("rollover diagnostic exceeded its 32 KiB bound")
    path.write_bytes(raw)
    return path


class _CausalSourceClock:
    """Advance UTC only to finite source events; use real monotonic deadlines."""

    def __init__(self):
        self._lock = threading.RLock()
        self._now = datetime(2026, 10, 22, 0, 0, tzinfo=UTC)
        self._bar_times = ()
        self._bar_index = 0
        self._scheduled = []
        self._consumed_tick_samples = deque(maxlen=32)

    def set_epoch_events(self, events):
        with self._lock:
            # The engine sees each bar only after its scheduled CTP quote has
            # been delivered. The risk snapshot must come from the preceding
            # complete query set; strategy projection then reads the real
            # consumed quote without forcing a newer query snapshot.
            self._bar_times = tuple(
                sorted({row["available_at"] + timedelta(milliseconds=200) for row in events})
            )
            self._bar_index = 0
            self._consumed_tick_samples.clear()
            if self._scheduled:
                raise AssertionError("prior-epoch CTP callbacks remain when the next epoch starts")
            self._now = self._bar_times[0] - timedelta(seconds=65)

    @property
    def pending_callback_count(self):
        with self._lock:
            return len(self._scheduled)

    @property
    def pending_callback_owner_counts(self):
        with self._lock:
            counts = defaultdict(int)
            for _when, owner, _callback in self._scheduled:
                api = getattr(owner, "_api", None)
                context = getattr(api, "_context", None)
                epoch_id = getattr(context, "epoch_id", None)
                label = (
                    "md-epoch-{}".format(epoch_id)
                    if type(epoch_id) is int
                    else type(owner).__name__
                )
                counts[label] += 1
            return tuple(sorted(counts.items()))

    def utc_now(self):
        with self._lock:
            return self._now

    def time(self):
        return self.utc_now().timestamp()

    def time_ns(self):
        return int(self.utc_now().timestamp() * 1_000_000_000)

    @staticmethod
    def monotonic():
        return time.monotonic()

    @staticmethod
    def monotonic_ns():
        return time.monotonic_ns()

    @staticmethod
    def sleep(seconds):
        time.sleep(seconds)

    def schedule_at(self, when, callback, *, owner):
        if (
            not isinstance(when, datetime)
            or when.tzinfo is None
            or not callable(callback)
            or owner is None
        ):
            raise TypeError("scheduled CTP events require aware time and a callback")
        if getattr(owner, "stopped", False):
            raise AssertionError("stopped fake MD clients cannot schedule new callbacks")
        with self._lock:
            self._scheduled.append((when, owner, callback))
            self._scheduled.sort(key=lambda item: item[0])
            due = self._take_due_locked()
        self._dispatch(due)

    def cancel_owner(self, owner):
        """Cancel only queued events owned by the fake client that just stopped."""

        with self._lock:
            retained = []
            removed = 0
            for item in self._scheduled:
                if item[1] is owner:
                    removed += 1
                else:
                    retained.append(item)
            self._scheduled = retained
            return removed

    def _take_due_locked(self):
        due = []
        while self._scheduled and self._scheduled[0][0] <= self._now:
            _when, _owner, callback = self._scheduled.pop(0)
            due.append(callback)
        return due

    @staticmethod
    def _dispatch(callbacks):
        for callback in callbacks:
            callback()

    def advance(self, delta):
        with self._lock:
            self._now += delta
            due = self._take_due_locked()
        self._dispatch(due)
        return self.utc_now()

    def note_consumed_tick(self, tick):
        """Record a quote only after the real Store poll consumed its callback."""
        try:
            instrument = str(tick.instrument_id)
            event_time = float(tick.exchange_time)
            received_at = float(tick.received_wall_time)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return
        with self._lock:
            self._consumed_tick_samples.append((instrument, event_time, received_at))

    def wait_interruptibly(self, timeout_seconds, wait_for_event):
        if wait_for_event(0.0):
            return True
        with self._lock:
            while (
                self._bar_index < len(self._bar_times)
                and self._bar_times[self._bar_index] <= self._now
            ):
                self._bar_index += 1
            next_bar = (
                self._bar_times[self._bar_index] if self._bar_index < len(self._bar_times) else None
            )
            next_provider = self._scheduled[0][0] if self._scheduled else None
            candidates = [value for value in (next_bar, next_provider) if value is not None]
            if not candidates:
                due = []
            else:
                next_event = min(candidates)
                self._now = max(self._now, next_event)
                if next_bar == next_event:
                    self._bar_index += 1
                due = self._take_due_locked()
        if not candidates:
            return wait_for_event(min(float(timeout_seconds), 0.01))
        self._dispatch(due)
        return False

    def wait(self, timeout_seconds):
        """Match Cerebro's injected-clock contract when no wake source is bound."""

        def no_wake(wait_timeout):
            self.sleep(wait_timeout)
            return False

        return self.wait_interruptibly(timeout_seconds, no_wake)


def _run_rollover(tmp_path, monkeypatch, *, unknown_dispatch=False):
    import backtrader.stores.btapistore as btapistore_module
    import backtrader.stores.execution_decision_journal as journal_module
    import backtrader.stores.registered_sim as registered_sim_module

    first_day = date(2026, 10, 22)
    second_day = date(2026, 10, 23)
    first_decision = datetime(2026, 10, 21, 9, 10, tzinfo=UTC)
    second_decision = datetime(2026, 10, 22, 9, 10, tzinfo=UTC)
    config = runner_fixtures._base_config(tmp_path, "live")
    first_bundle = runner_fixtures._write_json(
        tmp_path / "selection-first.json",
        runner_fixtures._selection_bundle(
            current_day=first_day,
            decision_at=first_decision,
            select_first=False,
            session_end=(10, 59),
        ),
    )
    config["selection"]["bundle"] = str(first_bundle)
    config["selection"]["authorized_products"] = ["DCE.M", "DCE.A"]
    config_path, config, first_plan, _tape, _quotes = runner_fixtures._write_source_inputs(
        tmp_path,
        config,
        current_day=first_day,
        decision_at=first_decision,
        connection_generation=1,
        session_end=(10, 59),
    )
    second_bundle = runner_fixtures._write_json(
        tmp_path / "selection-second.json",
        runner_fixtures._selection_bundle(
            current_day=second_day,
            decision_at=second_decision,
            select_first=True,
            session_end=(10, 59),
        ),
    )
    config["selection"]["daily_bundles"] = [str(second_bundle)]
    config["live"].update(
        account_scope="alpha003-rollover-account",
        strategy_scope="alpha003-rollover-strategy",
        logical_run_id="alpha003-rollover-run",
        journal_path=str(tmp_path / "rollover-decisions.sqlite"),
        ready_timeout_seconds=1.0,
        refresh_timeout_seconds=1.0,
        refresh_overall_timeout_seconds=8.0,
        # Match the accepted order-chain fixture cadence: let the engine
        # consume the post-query CTP quote before another full query set can
        # supersede the same coherent risk snapshot.
        refresh_interval_seconds=0.25,
        quote_max_age_seconds=60.0,
        query_max_age_seconds=7200.0,
        shutdown_grace_seconds=0.05 if unknown_dispatch else 5.0,
        allow_writes=True,
    )
    config["risk"]["run_end_policy"] = "CLOSE_ALL"
    config["cohort"].update(
        max_pending_slots=1,
        max_live_bar_age_seconds=30.0,
        max_future_skew_seconds=0.0,
    )
    config["output"]["decision_tape_path"] = str(tmp_path / "rollover.jsonl")
    config["output"]["decision_tape_max_bytes"] = 50_000_000
    config_path.write_text(
        runner_fixtures.yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    simnow_store_config, _unused_api_kwargs = runner_fixtures._official_simnow_store_config()
    contexts = {}
    api_instances = []
    trace = []
    refresh_condition = threading.Condition()
    fact_turn_lock = threading.RLock()
    refresh_state = {"started": 0, "completed": 0}
    clock = _CausalSourceClock()
    batch_observations = []

    client_module = None
    for module_name in ("bt_api_ctp.ctp.client", "bt_api_py.ctp.client"):
        try:
            client_module = __import__(module_name, fromlist=["MdClient", "TraderClient"])
            break
        except ImportError:
            continue
    if client_module is None:
        pytest.skip("CTP SDK client module is unavailable")

    def build_context(plan, epoch_id):
        trading_day = next(iter(plan["manifest"].trading_days)).current_trading_day
        bars_by_instrument, events = _bar_rows(
            plan,
            epoch_id=epoch_id,
            clock_domain_id=config["cohort"]["clock_domain_id"],
        )
        rows = facts_fixtures._query_rows()
        routes = tuple(
            (
                target,
                plan["routes"][plan["product_by_target"][target]],
                plan["product_by_target"][target].exchange_id,
            )
            for target in plan["targets"]
        )
        price_offset = _epoch_price_offset(epoch_id)
        rows["instruments_result"] = [
            {
                "InstrumentID": instrument,
                "ExchangeID": exchange,
                "IsTrading": 1,
                "VolumeMultiple": 10,
                "PriceTick": float(_QUOTE_TICK_SIZE),
                "LowerLimitPrice": 80.0 + price_offset,
                "UpperLimitPrice": 130.0 + price_offset,
            }
            for _target, instrument, exchange in routes
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
            for _target, instrument, exchange in routes
        ]
        context = SimpleNamespace(
            epoch_id=epoch_id,
            trading_day=trading_day,
            plan=plan,
            routes=routes,
            rows=rows,
            bars=bars_by_instrument,
            source_events=events,
            last_bar_close_by_instrument={row["instrument"]: row["close"] for row in events},
            unknown_dispatch=unknown_dispatch and epoch_id == 1,
            api=None,
            native_calls=[],
            native_insert_attempts=0,
            native_cancel_attempts=0,
            nonzero_insert_result_count=0,
            query_families=[],
            fill_count=0,
            source_tick_samples=[],
        )
        contexts[epoch_id] = context
        return context

    class Alpha003MdClient:
        def __init__(self, **_kwargs):
            self._state_lock = threading.RLock()
            self._connection_generation = 1
            self.on_tick = None
            self.on_tick_with_generation = None
            self.on_disconnect = None
            self.on_disconnect_with_generation = None
            self.on_error = None
            self._scheduled_bar_ids = set()
            self.stopped = False
            self.stop_calls = 0
            self._api = api_instances[-1]

        @property
        def connection_generation(self):
            return self._connection_generation

        def start(self, block=False):
            assert block is False

        def wait_ready(self, timeout=20):
            del timeout
            return True

        @staticmethod
        def _raw_tick(instrument, exchange, trading_day, event_time, price):
            local = event_time.astimezone(LOCAL)
            last_price, bid_price, ask_price = _tick_aligned_quote_prices(price)
            return SimpleNamespace(
                InstrumentID=instrument,
                ExchangeID=exchange,
                LastPrice=float(last_price),
                Volume=0,
                BidPrice1=float(bid_price),
                AskPrice1=float(ask_price),
                BidVolume1=5,
                AskVolume1=6,
                OpenInterest=0.0,
                Turnover=0.0,
                TradingDay=trading_day.strftime("%Y%m%d"),
                ActionDay=local.strftime("%Y%m%d"),
                UpdateTime=local.strftime("%H:%M:%S"),
                UpdateMillisec=local.microsecond // 1000,
            )

        def _dispatch_tick(self, payload):
            with self._state_lock:
                callback = self.on_tick_with_generation
                generation = self._connection_generation
            if not callable(callback):
                raise AssertionError("production CTP wrapper did not bind the tick callback")
            callback(payload, generation)
            api = self._api
            instrument = str(getattr(payload, "InstrumentID", ""))
            queues = getattr(api, "_tick_queues", {})
            event = None
            if isinstance(queues, dict):
                event = next(
                    (
                        queue[-1]
                        for queue in queues.values()
                        if queue
                        and str(getattr(queue[-1], "instrument_id", "")) == instrument
                    ),
                    None,
                )
            if event is not None:
                raw = getattr(event, "ctp_raw_tick", {})
                api._context.source_tick_samples.append(
                    (
                        instrument,
                        raw.get("TradingDay"),
                        raw.get("ActionDay"),
                        raw.get("UpdateTime"),
                        raw.get("UpdateMillisec"),
                        raw.get("Volume"),
                        raw.get("volume_issue"),
                        bool(getattr(event, "bar_eligible", False)),
                    )
                )

        def subscribe(self, instruments):
            context = self._api._context
            for instrument in tuple(str(value) for value in instruments):
                for row in tuple(context.bars.get(instrument, ())):
                    bar_id = row["bar_id"]
                    if bar_id in self._scheduled_bar_ids:
                        continue
                    self._scheduled_bar_ids.add(bar_id)
                    delivery_at = row["available_at"] + timedelta(milliseconds=200)

                    def deliver(row=row, instrument=instrument):
                        event_time = row["bucket_end"] + timedelta(seconds=2, milliseconds=10)
                        payload = self._raw_tick(
                            instrument,
                            row["exchange"],
                            context.trading_day,
                            event_time,
                            row["close"],
                        )
                        self._dispatch_tick(payload)
                        api = self._api
                        if (
                            api._pending_close_callback is not None
                            and api._pending_close_instrument == instrument
                        ):
                            order_ref = api._pending_close_callback
                            api._pending_close_callback = None
                            api._pending_close_instrument = None
                            api.trader_client.emit_fill(order_ref)

                    clock.schedule_at(delivery_at, deliver, owner=self)

        def schedule_winddown_quote(self, instrument, query_set_id, query_completed_at):
            api = self._api
            if instrument in api._winddown_scheduled:
                return
            route = next((item for item in api._context.routes if item[1] == instrument), None)
            if route is None:
                raise AssertionError("winddown quote is not bound to the epoch route")
            _target, _instrument, exchange = route
            api._winddown_scheduled.add(instrument)
            instrument_events = tuple(
                row for row in api._context.source_events if row["instrument"] == instrument
            )
            if not instrument_events:
                raise AssertionError("winddown quote has no finite source-event schedule")
            final_source_delivery = max(
                row["available_at"] + timedelta(milliseconds=200)
                for row in instrument_events
            )
            scheduled_from = max(query_completed_at, clock.utc_now(), final_source_delivery)
            event_time = scheduled_from + timedelta(milliseconds=5)
            delivery_at = scheduled_from + timedelta(milliseconds=25)

            def deliver():
                payload = self._raw_tick(
                    instrument,
                    exchange,
                    api._context.trading_day,
                    event_time,
                    api._context.last_bar_close_by_instrument[instrument],
                )
                self._dispatch_tick(payload)
                if (
                    api._pending_close_callback is not None
                    and api._pending_close_instrument == instrument
                ):
                    order_ref = api._pending_close_callback
                    api._pending_close_callback = None
                    api._pending_close_instrument = None
                    api.trader_client.emit_fill(order_ref)
                trace.append(("winddown_quote", api._context.epoch_id, instrument, query_set_id))
                api._winddown_scheduled.discard(instrument)

            clock.schedule_at(delivery_at, deliver, owner=self)

        def stop(self):
            self.stop_calls += 1
            self.stopped = True
            pending_before = clock.pending_callback_count
            cancelled = clock.cancel_owner(self)
            trace.append(
                (
                    "md_stop",
                    self._api._context.epoch_id,
                    self.stop_calls,
                    pending_before,
                    cancelled,
                    clock.pending_callback_count,
                )
            )

    class Alpha003TraderClient(facts_fixtures._ProviderLeaves):
        def __init__(self, **_kwargs):
            context = current_context["value"]
            super().__init__(query_rows=context.rows, query_time=clock.utc_now(), ticks={})
            self._context = context
            self._api = context.api
            self.trader_client._account_fingerprint = "alpha003-rollover-account"
            self.trader_client._trading_day = context.trading_day.strftime("%Y%m%d")
            self.trader_client._connection_generation = 1
            self._front_id = 41 + context.epoch_id
            self._session_id = 9 + context.epoch_id
            self._next_order_ref_value = 1000 + context.epoch_id * 100
            self._req_id = 0
            self.is_ready = True
            self.is_read_only_ready = True
            self.is_trading_ready = True
            self.stopped = False
            self.stop_calls = 0
            self._provider_orders = {}
            self._fake_active_capability = None

        def start(self, block=False):
            assert block is False

        def wait_ready(self, timeout=20):
            del timeout
            return True

        def stop(self):
            self.stop_calls += 1
            self.stopped = True
            trace.append(("trader_stop", self._context.epoch_id, self.stop_calls))

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
                raise AssertionError("disarm must name the exact active fake SDK capability")
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
            self.query_rows = self._context.rows
            started = clock.utc_now()
            self.query_time = started + timedelta(milliseconds=2)
            self._context.query_families.append(family)
            result = super()._query_family(family, request_type, **filters)
            clock.advance(timedelta(milliseconds=2))
            return result

        def query_account(self, timeout=5):
            del timeout
            return dict(self._context.rows["account_result"][0])

        def query_positions(self, timeout=5):
            del timeout
            return [dict(row) for row in self._context.rows["positions_result"]]

        def query_instrument(self, instrument, exchange_id="", timeout=5):
            del timeout
            return next(
                (
                    dict(row)
                    for row in self._context.rows["instruments_result"]
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
                    for row in self._context.rows["instrument_margin_rate_result"]
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
            self._context.native_insert_attempts += 1
            if execution_capability is not self._fake_active_capability:
                raise AssertionError("insert lacks the exact RegisteredSim SDK capability")
            order_ref = str(field.OrderRef)
            offset_flag = str(field.CombOffsetFlag)
            offset = {"0": "open", "1": "close", "3": "close_today", "4": "close_yesterday"}.get(
                offset_flag
            )
            if offset is None:
                raise AssertionError("unexpected CTP offset value")
            identity = {
                "order_ref": order_ref,
                "order_sys_id": "roll-sys-" + order_ref,
                "instrument_id": str(field.InstrumentID),
                "exchange_id": str(field.ExchangeID),
                "side": "buy" if str(field.Direction) == "0" else "sell",
                "offset_flag": offset_flag,
                "offset": offset,
                "size": int(field.VolumeTotalOriginal),
                "price": float(field.LimitPrice),
                "front_id": self._front_id,
                "session_id": self._session_id,
            }
            self._provider_orders[order_ref] = identity
            item = (
                "insert_unknown"
                if self._context.unknown_dispatch and offset == "open"
                else "insert",
                self._context.epoch_id,
                identity["instrument_id"],
                offset,
                order_ref,
                request_id,
            )
            self._context.native_calls.append(item)
            trace.append(item)
            if self._context.unknown_dispatch and offset == "open":
                # A nonzero native return is an actual RegisteredSim UNKNOWN
                # dispatch: the production Store latches and revokes it.
                self._context.nonzero_insert_result_count += 1
                return 7
            self._publish_order(identity, status="3", filled=0, remaining=identity["size"])
            self.on_order(self._ctp_order_event(identity, "3", 0, identity["size"]))
            if offset == "open" and self._context.fill_count == 0:
                self._api._pending_fill_callback = order_ref
                self._api._pending_fill_instrument = identity["instrument_id"]
            elif offset.startswith("close"):
                self._api._pending_close_callback = order_ref
                self._api._pending_close_instrument = identity["instrument_id"]
            self._api._mark_refresh_required()
            return 0

        def submit_order_action(self, field, request_id, *, execution_capability):
            self._context.native_cancel_attempts += 1
            if execution_capability is not self._fake_active_capability:
                raise AssertionError("cancel lacks the exact RegisteredSim SDK capability")
            order_ref = str(field.OrderRef)
            identity = self._provider_orders[order_ref]
            item = (
                "cancel",
                self._context.epoch_id,
                identity["instrument_id"],
                identity["offset"],
                order_ref,
                request_id,
            )
            self._context.native_calls.append(item)
            trace.append(item)
            self._publish_order(identity, status="5", filled=0, remaining=identity["size"])
            self.on_order(self._ctp_order_event(identity, "5", 0, identity["size"]))
            self._api._mark_refresh_required()
            return 0

        def _ctp_order_event(self, identity, status, filled, remaining):
            local = clock.utc_now().astimezone(LOCAL)
            return SimpleNamespace(
                OrderRef=identity["order_ref"],
                OrderSysID=identity["order_sys_id"],
                InstrumentID=identity["instrument_id"],
                ExchangeID=identity["exchange_id"],
                FrontID=identity["front_id"],
                SessionID=identity["session_id"],
                OrderStatus=status,
                OrderSubmitStatus="0",
                Direction="0" if identity["side"] == "buy" else "1",
                CombOffsetFlag=identity["offset_flag"],
                VolumeTotalOriginal=identity["size"],
                VolumeTraded=filled,
                VolumeTotal=remaining,
                LimitPrice=identity["price"],
                TradingDay=self._context.trading_day.strftime("%Y%m%d"),
                InsertTime=local.strftime("%H:%M:%S"),
                UpdateTime=local.strftime("%H:%M:%S"),
            )

        def _publish_order(self, identity, *, status, filled, remaining):
            row = {
                "OrderRef": identity["order_ref"],
                "OrderSysID": identity["order_sys_id"],
                "InstrumentID": identity["instrument_id"],
                "ExchangeID": identity["exchange_id"],
                "TradingDay": self._context.trading_day.strftime("%Y%m%d"),
                "FrontID": identity["front_id"],
                "SessionID": identity["session_id"],
                "OrderStatus": status,
                "OrderSubmitStatus": "0",
                "Direction": "0" if identity["side"] == "buy" else "1",
                "CombOffsetFlag": identity["offset_flag"],
                "VolumeTotalOriginal": identity["size"],
                "VolumeTraded": filled,
                "VolumeTotal": remaining,
                "LimitPrice": identity["price"],
            }
            orders = self._context.rows["orders_result"]
            orders[:] = [
                item for item in orders if str(item.get("OrderRef")) != identity["order_ref"]
            ]
            orders.append(row)

        def emit_fill(self, order_ref):
            identity = self._provider_orders[str(order_ref)]
            quantity = identity["size"]
            self._publish_order(identity, status="0", filled=quantity, remaining=0)
            self.on_order(self._ctp_order_event(identity, "0", quantity, 0))
            local = clock.utc_now().astimezone(LOCAL)
            trade_id = "roll-{}-{}".format(identity["offset"], identity["order_ref"])
            trade = SimpleNamespace(
                TradeID=trade_id,
                OrderRef=identity["order_ref"],
                OrderSysID=identity["order_sys_id"],
                InstrumentID=identity["instrument_id"],
                ExchangeID=identity["exchange_id"],
                Direction="0" if identity["side"] == "buy" else "1",
                OffsetFlag=identity["offset_flag"],
                HedgeFlag="1",
                Volume=quantity,
                Price=identity["price"],
                TradeDate=local.strftime("%Y%m%d"),
                TradeTime=local.strftime("%H:%M:%S"),
                TradingDay=self._context.trading_day.strftime("%Y%m%d"),
            )
            self.on_trade(trade)
            self._context.rows["trades_result"].append(
                {
                    "TradeID": trade_id,
                    "OrderRef": identity["order_ref"],
                    "OrderSysID": identity["order_sys_id"],
                    "InstrumentID": identity["instrument_id"],
                    "ExchangeID": identity["exchange_id"],
                    "Direction": trade.Direction,
                    "OffsetFlag": identity["offset_flag"],
                    "HedgeFlag": "1",
                    "Volume": str(quantity),
                    "Price": str(identity["price"]),
                    "TradeDate": trade.TradeDate,
                    "TradeTime": trade.TradeTime,
                    "TradingDay": trade.TradingDay,
                }
            )
            if identity["offset"] == "open":
                position = facts_fixtures._dated_position_row(
                    quantity,
                    side="LONG" if identity["side"] == "buy" else "SHORT",
                    trading_day=self._context.trading_day.strftime("%Y%m%d"),
                    PositionCost=str(Decimal(quantity) * Decimal(str(identity["price"])) * 10),
                    InstrumentID=identity["instrument_id"],
                    ExchangeID=identity["exchange_id"],
                )
                self._context.rows["positions_result"][:] = [
                    row
                    for row in self._context.rows["positions_result"]
                    if row.get("InstrumentID") != identity["instrument_id"]
                ]
                self._context.rows["positions_result"].append(position)
                self._context.fill_count += 1
                self._api._pending_fill_callback = None
                self._api._pending_fill_instrument = None
            else:
                self._context.rows["positions_result"][:] = [
                    row
                    for row in self._context.rows["positions_result"]
                    if row.get("InstrumentID") != identity["instrument_id"]
                ]
                trace.append(("close_fill", self._context.epoch_id, identity["instrument_id"]))
            self._api._mark_refresh_required()

    monkeypatch.setattr(client_module, "MdClient", Alpha003MdClient)
    monkeypatch.setattr(client_module, "TraderClient", Alpha003TraderClient)
    ctp_wrapper = btapistore_module._create_ctp_wrapper_class()

    class Alpha003BarTapeMixin(ctp_wrapper):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            context = current_context["value"]
            self._context = context
            context.api = self
            self._pending_fill_callback = None
            self._pending_fill_instrument = None
            self._pending_close_callback = None
            self._pending_close_instrument = None
            self._required_refresh_start = None
            self._winddown_scheduled = set()
            self._connected_once = False
            api_instances.append(self)
            trace.append(("api_created", context.epoch_id))

        @property
        def closed(self):
            return bool(
                self.md_client is not None
                and self.trader_client is not None
                and self.md_client.stopped
                and self.trader_client.stopped
            )

        def connect(self):
            super().connect()
            self._connected_once = True

        def disconnect(self):
            super().disconnect()
            if self.closed:
                trace.append(("api_closed", self._context.epoch_id))

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
                    timeout=5.0,
                ):
                    raise AssertionError("query refresh did not follow a native write")
                self._required_refresh_start = None

        def poll_bar(self, instrument):
            self._wait_for_refresh()
            if (
                instrument == self._pending_fill_instrument
                and self._pending_fill_callback is not None
                and self._context.fill_count == 0
            ):
                self.trader_client.emit_fill(self._pending_fill_callback)
            rows = self._context.bars.get(instrument)
            if not rows or rows[0]["available_at"] > clock.utc_now():
                return None
            return rows.popleft()

    current_context = {"value": None}
    original_factory = registered_sim_module._make_api_factory
    monkeypatch.setattr(
        registered_sim_module,
        "_make_api_factory",
        lambda allow_writes, history_limit, terminal_limit, _api_cls: original_factory(
            allow_writes, history_limit, terminal_limit, Alpha003BarTapeMixin
        ),
    )
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
    monkeypatch.setattr(RUNNER, "RunnerWallClock", lambda: clock)
    monkeypatch.setattr(
        RUNNER,
        "_live_env_config",
        lambda _config: (
            {
                **simnow_store_config,
                "broker_id": "9999",
                "investor_id": "fixture",
                "password": "unused",
            },
            {
                "live_tick_provenance": {
                    "clock_domain_id": config["cohort"]["clock_domain_id"],
                    "rules_hash": "a" * 64,
                    "session_segment": current_context["value"].source_events[0]["session_segment"],
                }
            },
        ),
    )
    monkeypatch.setattr(
        journal_module,
        "time",
        SimpleNamespace(time_ns=clock.time_ns, monotonic=time.monotonic),
    )

    config["live"]["arm_templates"] = [
        {
            "target": target,
            "md_front": simnow_store_config["md_address"],
            "strategy_identity_sha256": "a" * 64,
            "execution_cycle_id": "alpha003-roll-" + target,
            "preflight_sha256": "b" * 64,
        }
        for target in first_plan["authorized_targets"]
    ]
    config_path.write_text(
        runner_fixtures.yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    strategy_module = importlib.import_module("alpha003_strategy")
    original_snapshot = strategy_module.Alpha003TargetStrategy._current_batch_snapshot
    captured_batch_states = set()
    snapshot_call_count = 0
    batch_facts_by_id = {}
    strategy_facts_by_batch = {}
    quote_predicate_sample_state = {"stale": None, "target_ready": None}

    def record_batch_snapshot(strategy):
        nonlocal snapshot_call_count
        batch, snapshot = original_snapshot(strategy)
        snapshot_call_count += 1
        if batch is not None and snapshot is not None:
            epoch_id = getattr(batch, "epoch_id", None)
            batch_id = getattr(batch, "batch_id", None)
            readiness = getattr(snapshot, "readiness", None)
            readiness = getattr(readiness, "value", readiness)
            factor_rows = []
            for factor_name, factor_result in tuple(getattr(snapshot, "factors", {}).items())[:4]:
                outputs = tuple(getattr(factor_result, "values", {}).items())
                available_count = 0
                finite_count = 0
                for _target, output in outputs:
                    status = getattr(output, "status", None)
                    status = getattr(status, "value", status)
                    value = getattr(output, "value", None)
                    if status == "OUTPUT_AVAILABLE":
                        available_count += 1
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        finite_count += 1
                factor_rows.append((str(factor_name), len(outputs), available_count, finite_count))
            if type(epoch_id) is int and batch_id is not None:
                batch_facts_by_id[(epoch_id, str(batch_id))] = {
                    "epoch_id": epoch_id,
                    "batch_id": str(batch_id),
                    "batch_status": getattr(batch, "status", None),
                    "batch_complete": getattr(snapshot, "batch_complete", None),
                    "readiness": readiness,
                    "readiness_reasons": tuple(
                        str(reason)
                        for reason in tuple(getattr(snapshot, "readiness_reasons", ()) or ())[:4]
                    ),
                    "factor_outputs": tuple(factor_rows),
                }
        if (
            batch is not None
            and snapshot is not None
            and getattr(batch, "status", None) == "COMPLETE"
        ):
            epoch_id = strategy.p.cohort.epoch_id
            readiness = getattr(snapshot, "readiness", None)
            readiness = getattr(readiness, "value", readiness)
            key = (epoch_id, readiness)
            if key not in captured_batch_states:
                captured_batch_states.add(key)
                data = []
                for feed in strategy.datas:
                    try:
                        value = float(feed.close[0])
                        length = len(feed)
                    except (TypeError, ValueError):
                        value, length = None, len(feed)
                    data.append(
                        (
                            feed._name,
                            getattr(feed, "_dataname", None),
                            length,
                            value,
                        )
                    )
                batch_observations.append(
                    {
                        "epoch_id": epoch_id,
                        "batch_id": getattr(batch, "batch_id", None),
                        "close_time": getattr(batch, "close_time", None),
                        "readiness": readiness,
                        "data": tuple(data),
                    }
                )
                trace.append(
                    ("batch_snapshot", epoch_id, readiness, getattr(batch, "batch_id", None))
                )
        return batch, snapshot

    monkeypatch.setattr(
        strategy_module.Alpha003TargetStrategy,
        "_current_batch_snapshot",
        record_batch_snapshot,
    )

    original_strategy_run_live = strategy_module.Alpha003TargetStrategy._run_live

    def traced_strategy_run_live(
        strategy,
        batch,
        snapshot,
        now,
        ordinal,
        session_close,
        run_end,
        *,
        is_new_batch,
        session_reason=None,
    ):
        result = original_strategy_run_live(
            strategy,
            batch,
            snapshot,
            now,
            ordinal,
            session_close,
            run_end,
            is_new_batch=is_new_batch,
            session_reason=session_reason,
        )
        epoch_id = getattr(batch, "epoch_id", None) if batch is not None else None
        batch_id = getattr(batch, "batch_id", None) if batch is not None else None
        if type(epoch_id) is int and batch_id is not None:
            decision = getattr(strategy, "last_target_decision", None)
            plan = getattr(strategy, "last_order_plan", None)
            decision_targets = tuple(getattr(decision, "targets", ()) or ())
            actions = tuple(getattr(plan, "actions", ()) or ())
            execution_facts = getattr(strategy, "last_execution_facts", None)
            execution_fact_source = None
            execution_fact_summary = None
            if execution_facts is not None:
                target_by_instrument = {
                    getattr(route, "instrument", None): getattr(route, "target_id", None)
                    for route in tuple(getattr(execution_facts, "route_eligibilities", ()))
                }
                route_by_target = {
                    getattr(route, "target_id", None): route
                    for route in tuple(getattr(execution_facts, "route_eligibilities", ()))
                }
                instrument_by_target = {
                    getattr(item, "target_id", None): item
                    for item in tuple(getattr(execution_facts, "instruments", ()))
                }
                target_available_at = getattr(decision, "available_at", None)
                plan_reason = getattr(plan, "reason", None)
                plan_reason = getattr(plan_reason, "value", plan_reason)
                target_status = getattr(decision, "status", None)
                target_status = getattr(target_status, "value", target_status)
                is_quote_stale = plan_reason == "CURRENT_QUOTE_INVALID_OR_STALE"
                is_target_ready = target_status == "TARGETS_READY"
                capture_quote_sample = (
                    is_quote_stale and quote_predicate_sample_state["stale"] is None
                ) or (
                    not is_quote_stale
                    and is_target_ready
                    and quote_predicate_sample_state["target_ready"] is None
                )
                if capture_quote_sample:
                    targets_by_id = {
                        getattr(target, "target_id", None): target for target in decision_targets
                    }
                    quote_rows = []
                    for quote in tuple(getattr(execution_facts, "quotes", ()))[:4]:
                        instrument = getattr(quote, "instrument", None)
                        target_id = target_by_instrument.get(instrument)
                        instrument_fact = instrument_by_target.get(target_id)
                        route_fact = route_by_target.get(target_id)
                        target = targets_by_id.get(target_id)
                        target_position = getattr(target, "target_position", None)
                        side = (
                            "BUY"
                            if isinstance(target_position, (int, float, Decimal))
                            and target_position > 0
                            else "SELL"
                            if isinstance(target_position, (int, float, Decimal))
                            and target_position < 0
                            else None
                        )
                        quote_rows.append(
                            {
                                "target_id": target_id,
                                "target_position": target_position,
                                "side": side,
                                "instrument": instrument,
                                "exchange": getattr(quote, "exchange", None),
                                "source": getattr(quote, "source", None),
                                "source_ref": getattr(quote, "source_ref", None),
                                "metadata_snapshot_id": getattr(
                                    quote, "metadata_snapshot_id", None
                                ),
                                "generation": getattr(quote, "generation", None),
                                "sequence": getattr(quote, "sequence", None),
                                "event_time": getattr(quote, "event_time", None),
                                "available_at": getattr(quote, "available_at", None),
                                "bid": getattr(quote, "bid", None),
                                "ask": getattr(quote, "ask", None),
                                "bid_size": getattr(quote, "bid_size", None),
                                "ask_size": getattr(quote, "ask_size", None),
                                "tick_size": getattr(quote, "tick_size", None),
                                "lower_limit": getattr(quote, "lower_limit", None),
                                "upper_limit": getattr(quote, "upper_limit", None),
                                "quality": getattr(quote, "quality", None),
                                "risk_instrument": getattr(instrument_fact, "instrument", None),
                                "risk_exchange": getattr(instrument_fact, "exchange", None),
                                "risk_snapshot_id": getattr(instrument_fact, "snapshot_id", None),
                                "risk_available_at": getattr(instrument_fact, "available_at", None),
                                "risk_tick_size": getattr(instrument_fact, "tick_size", None),
                                "risk_lower_limit": getattr(instrument_fact, "lower_limit", None),
                                "risk_upper_limit": getattr(instrument_fact, "upper_limit", None),
                                "risk_trading_permitted": getattr(
                                    instrument_fact, "trading_permitted", None
                                ),
                                "route_eligible": getattr(route_fact, "eligible", None),
                                "route_reason_codes": tuple(
                                    getattr(route_fact, "reason_codes", ()) or ()
                                )[:4],
                                "metadata_matches_risk": getattr(
                                    quote, "metadata_snapshot_id", None
                                )
                                == getattr(instrument_fact, "snapshot_id", None),
                            }
                        )
                    candidate_sample = {
                        "epoch_id": epoch_id,
                        "batch_id": str(batch_id),
                        "ordinal": ordinal,
                        "readiness": getattr(
                            getattr(snapshot, "readiness", None),
                            "value",
                            getattr(snapshot, "readiness", None),
                        ),
                        "target_status": target_status,
                        "target_reason": getattr(decision, "reason", None),
                        "plan_status": getattr(plan, "status", None),
                        "plan_reason": plan_reason,
                        "batch_available_at": getattr(batch, "available_at", None),
                        "target_available_at": target_available_at,
                        "plan_decision_available_at": getattr(plan, "decision_available_at", None),
                        "evaluated_at": now,
                        "risk_snapshot_available_at": getattr(
                            execution_facts, "available_at", None
                        ),
                        "query_set_id": getattr(execution_facts, "query_set_id", None),
                        "quote_max_age_seconds": getattr(
                            getattr(strategy, "_risk_policy", None),
                            "quote_max_age_seconds",
                            None,
                        ),
                        "quotes": tuple(quote_rows),
                    }
                    if is_quote_stale:
                        quote_predicate_sample_state["stale"] = candidate_sample
                    elif is_target_ready:
                        quote_predicate_sample_state["target_ready"] = candidate_sample
                execution_fact_source = {
                    "query_set_id": getattr(execution_facts, "query_set_id", None),
                    "available_at": getattr(execution_facts, "available_at", None),
                    "projection_now": now,
                    "quotes": tuple(
                        (
                            getattr(quote, "instrument", None),
                            getattr(quote, "event_time", None),
                            getattr(quote, "available_at", None),
                            getattr(quote, "quality", None),
                        )
                        for quote in tuple(getattr(execution_facts, "quotes", ()))[:4]
                    ),
                }
                execution_fact_summary = {
                    "snapshot_id": getattr(execution_facts, "snapshot_id", None),
                    "query_set_id": getattr(execution_facts, "query_set_id", None),
                    "available_at": getattr(execution_facts, "available_at", None),
                    "blockers": tuple(getattr(execution_facts, "blockers", ()) or ())[:16],
                    "aggregate_write_blockers": tuple(
                        getattr(execution_facts, "aggregate_write_blockers", ()) or ()
                    )[:16],
                    "risk_reduction_blockers": tuple(
                        getattr(execution_facts, "risk_reduction_blockers", ()) or ()
                    )[:16],
                    "risk_reduction_ready": getattr(execution_facts, "risk_reduction_ready", None),
                    "open_risk_ready": getattr(execution_facts, "open_risk_ready", None),
                    "order_cancel_ready": getattr(execution_facts, "order_cancel_ready", None),
                    "quotes": tuple(
                        (
                            target_by_instrument.get(getattr(item, "instrument", None)),
                            getattr(item, "instrument", None),
                            getattr(item, "quality", None),
                            getattr(item, "event_time", None),
                            getattr(item, "available_at", None),
                        )
                        for item in tuple(getattr(execution_facts, "quotes", ()))[:4]
                    ),
                    "query_provenance": tuple(
                        (
                            getattr(item, "family", None),
                            getattr(item, "target_id", None),
                            getattr(item, "query_complete", None),
                            getattr(item, "scope_complete", None),
                            getattr(item, "completed_at", None),
                        )
                        for item in tuple(getattr(execution_facts, "query_provenance", ()))[:12]
                    ),
                    "routes": tuple(
                        (
                            getattr(item, "target_id", None),
                            getattr(item, "eligible", None),
                            getattr(item, "arm_template_membership", None),
                            tuple(getattr(item, "reason_codes", ()) or ())[:6],
                        )
                        for item in tuple(getattr(execution_facts, "route_eligibilities", ()))[:4]
                    ),
                }
            target_decision_summary = None
            if decision is not None:
                target_decision_summary = {
                    "status": getattr(decision, "status", None),
                    "reason": getattr(decision, "reason", None),
                    "available_at": getattr(decision, "available_at", None),
                    "eligible_grid_index": getattr(decision, "eligible_grid_index", None),
                    "authorized_targets": tuple(getattr(decision, "authorized_targets", ()) or ())[
                        :8
                    ],
                    "eligible_targets": tuple(getattr(decision, "eligible_targets", ()) or ())[:8],
                    "targets": tuple(
                        (
                            str(getattr(target, "target_id", "")),
                            getattr(target, "target_position", None),
                            getattr(target, "raw_score", None),
                            getattr(target, "oriented_score", None),
                        )
                        for target in decision_targets[:4]
                    ),
                }
            strategy_facts_by_batch[(epoch_id, str(batch_id))] = {
                "epoch_id": epoch_id,
                "batch_id": str(batch_id),
                "ordinal": ordinal,
                "batch_available_at": getattr(batch, "available_at", None),
                "target_decision_available_at": getattr(decision, "available_at", None),
                "evaluated_at": now,
                "plan_decision_available_at": getattr(plan, "decision_available_at", None),
                "readiness": getattr(
                    getattr(snapshot, "readiness", None),
                    "value",
                    getattr(snapshot, "readiness", None),
                ),
                "target_status": getattr(decision, "status", None),
                "target_reason": getattr(decision, "reason", None),
                "target_selection": tuple(
                    (
                        str(getattr(target, "target_id", "")),
                        getattr(target, "target_position", None),
                        getattr(target, "raw_score", None),
                    )
                    for target in decision_targets[:4]
                ),
                "target_decision_summary": target_decision_summary,
                "plan_status": getattr(plan, "status", None),
                "plan_reason": getattr(plan, "reason", None),
                "actions": tuple(
                    (
                        getattr(action, "action", None),
                        getattr(action, "position_effect", None),
                        getattr(action, "target_id", None),
                    )
                    for action in actions[:4]
                ),
                "execution_fact_source": execution_fact_source,
                "execution_fact_summary": execution_fact_summary,
                "last_signal_block_reason": getattr(strategy, "last_signal_block_reason", None),
                "last_execution_block_reason": getattr(
                    strategy, "last_execution_block_reason", None
                ),
            }
        return result

    monkeypatch.setattr(
        strategy_module.Alpha003TargetStrategy,
        "_run_live",
        traced_strategy_run_live,
    )

    original_make_cohort = RUNNER._make_cohort

    def traced_make_cohort(epoch_config, grid, *, begin_at=None, **kwargs):
        cohort = original_make_cohort(epoch_config, grid, begin_at=begin_at, **kwargs)
        trace.append(("cohort_assembled", epoch_config["cohort"]["epoch_id"]))
        return cohort

    monkeypatch.setattr(RUNNER, "_make_cohort", traced_make_cohort)
    original_load_plan = RUNNER.load_market_plan

    def traced_load_plan(current_config, current_path, *, bundle_path=None):
        plan = original_load_plan(current_config, current_path, bundle_path=bundle_path)
        if bundle_path is not None:
            assert api_instances and api_instances[-1].closed is True
            plan = _truncate_plan(plan)
            trace.append(("second_bundle_loaded", str(bundle_path)))
        return plan

    monkeypatch.setattr(RUNNER, "load_market_plan", traced_load_plan)
    original_run_live = RUNNER.run_live

    def epoch_run(epoch_config, current_path, plan, *args, **kwargs):
        epoch_id = epoch_config["cohort"]["epoch_id"]
        context = build_context(plan, epoch_id)
        current_context["value"] = context
        if epoch_id > 1:
            pending_callbacks = clock.pending_callback_count
            trace.append(("prior_callbacks_drained", epoch_id - 1, pending_callbacks))
            if pending_callbacks:
                raise AssertionError("old provider callbacks remain after epoch retirement")
        clock.set_epoch_events(context.source_events)
        trace.append(("epoch_run_start", epoch_id, RUNNER._route_summary(plan)))
        result = original_run_live(epoch_config, current_path, plan, *args, **kwargs)
        trace.append(("epoch_run_returned", epoch_id))
        return result

    monkeypatch.setattr(RUNNER, "run_live", epoch_run)
    original_refresh_once = RUNNER.QueryRefreshLoop.refresh_once
    original_poll_tick = btapistore_module.BtApiStore.poll_tick

    def traced_poll_tick(store, symbol):
        tick = original_poll_tick(store, symbol)
        if tick is not None:
            clock.note_consumed_tick(tick)
        return tick

    monkeypatch.setattr(btapistore_module.BtApiStore, "poll_tick", traced_poll_tick)

    def traced_refresh_once(loop):
        with fact_turn_lock:
            with refresh_condition:
                refresh_state["started"] += 1
                started = refresh_state["started"]
                refresh_condition.notify_all()
            try:
                receipt = original_refresh_once(loop)
                context = current_context["value"]
                query_set = getattr(receipt, "query_set", None)
                if (
                    context is not None
                    and query_set is not None
                    and not getattr(receipt, "blockers", ())
                    and not getattr(receipt, "pending_families", ())
                    and all(not rows for rows in context.bars.values())
                    and context.api is not None
                    and context.api.md_client is not None
                ):
                    completed_at = query_set.completed_at_utc
                    for _target, instrument, _exchange in context.routes:
                        context.api.md_client.schedule_winddown_quote(
                            instrument, query_set.query_set_id, completed_at
                        )
                return receipt
            finally:
                with refresh_condition:
                    refresh_state["completed"] = max(refresh_state["completed"], started)
                    refresh_condition.notify_all()

    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "refresh_once", traced_refresh_once)
    first_plan = _truncate_plan(RUNNER.load_market_plan(config, config_path))
    evidence = {
        "config": config,
        "first_plan": first_plan,
        "second_bundle": second_bundle,
        "contexts": contexts,
        "apis": api_instances,
        "trace": trace,
        "batches": batch_observations,
    }

    def failure_facts(error=None):
        def id_projection(values):
            if values is None:
                return None, None
            values = tuple(str(value) for value in values)
            return len(values), values[:4]

        context_facts = []
        for epoch_id, context in sorted(contexts.items())[:3]:
            call_counts = defaultdict(int)
            for call in context.native_calls:
                call_counts[str(call[0])] += 1
            family_counts = defaultdict(int)
            for family in context.query_families:
                family_counts[str(family)] += 1
            trader = (
                getattr(context.api, "trader_client", None) if context.api is not None else None
            )
            margin_target_counts = defaultdict(int)
            for family, filters in tuple(getattr(trader, "query_calls", ()) or ())[:128]:
                if family == "instrument_margin_rate_result":
                    margin_target_counts[str(filters.get("instrument_id"))] += 1
            context_facts.append(
                {
                    "epoch_id": epoch_id,
                    "unknown_dispatch_enabled": context.unknown_dispatch,
                    "native_insert_attempts": context.native_insert_attempts,
                    "native_cancel_attempts": context.native_cancel_attempts,
                    "nonzero_insert_result_count": context.nonzero_insert_result_count,
                    "native_call_count": len(context.native_calls),
                    "native_call_counts": tuple(sorted(call_counts.items())),
                    "native_calls_sample": tuple(context.native_calls[:8]),
                    "query_family_count": len(context.query_families),
                    "query_family_counts": tuple(sorted(family_counts.items())),
                    "margin_query_target_counts": tuple(sorted(margin_target_counts.items())),
                    "fill_count": context.fill_count,
                    "source_tick_samples": tuple(context.source_tick_samples[-12:]),
                }
            )

        api_facts = []
        for api in api_instances[:3]:
            facts = None
            facts_method = getattr(api, "registered_sim_execution_facts", None)
            if callable(facts_method):
                try:
                    raw_facts = facts_method()
                    order_state = {}
                    for key in (
                        "unknown_ids",
                        "active_order_ids",
                        "dispatching_order_ids",
                        "terminal_order_ids",
                    ):
                        count, sample = id_projection(raw_facts.get(key))
                        order_state[key + "_count"] = count
                        order_state[key + "_sample"] = sample
                    order_state["frozen"] = raw_facts.get("frozen")
                    facts = order_state
                except BaseException as facts_error:
                    facts = {"read_error_type": type(facts_error).__name__}
            md_client = getattr(api, "md_client", None)
            trader_client = getattr(api, "trader_client", None)
            context = getattr(api, "_context", None)
            api_facts.append(
                {
                    "epoch_id": getattr(context, "epoch_id", None),
                    "closed": getattr(api, "closed", None),
                    "md_stopped": getattr(md_client, "stopped", None),
                    "md_stop_calls": getattr(md_client, "stop_calls", None),
                    "trader_stopped": getattr(trader_client, "stopped", None),
                    "trader_stop_calls": getattr(trader_client, "stop_calls", None),
                    "order_state": facts,
                }
            )

        trace_counts = defaultdict(int)
        for row in trace:
            if row:
                trace_counts[str(row[0])] += 1
        complete_batches = [
            row
            for row in batch_facts_by_id.values()
            if row["batch_status"] == "COMPLETE" and row["batch_complete"] is True
        ]
        readiness_counts = defaultdict(int)
        factor_counts = defaultdict(lambda: [0, 0, 0])
        for row in complete_batches:
            readiness_counts[str(row["readiness"])] += 1
            for factor_name, output_count, available_count, finite_count in row["factor_outputs"]:
                totals = factor_counts[factor_name]
                totals[0] += output_count
                totals[1] += available_count
                totals[2] += finite_count

        def count_field(rows, field):
            counts = defaultdict(int)
            for row in rows:
                counts[str(row.get(field))] += 1
            return tuple(sorted(counts.items()))

        strategy_rows = tuple(strategy_facts_by_batch.values())
        action_counts = defaultdict(int)
        for row in strategy_rows:
            for action in row["actions"]:
                action_counts[str(action[0])] += 1

        def is_target_ready_or_open_blocked(row):
            status = getattr(row["target_status"], "value", row["target_status"])
            reason = getattr(row["plan_reason"], "value", row["plan_reason"])
            return status == "TARGETS_READY" or (
                reason is not None and "OPEN_RISK_FACTS_BLOCKED" in str(reason)
            )

        later_reads = getattr(error, "later_bundle_reads", ()) if error is not None else ()
        epoch_attempts = (
            tuple(getattr(error, "assembly_attempts", ()))
            if error is not None
            else tuple(row[1] for row in trace if row and row[0] == "epoch_run_start")
        )
        return {
            "failure_type": type(error).__name__ if error is not None else None,
            "failure_code": getattr(error, "code", None) if error is not None else None,
            "next_bundle_read_count": (
                getattr(error, "next_bundle_read_count", None)
                if error is not None
                else sum(1 for row in trace if row and row[0] == "second_bundle_loaded")
            ),
            "later_bundle_read_count": len(later_reads),
            "assembly_attempts": epoch_attempts,
            "next_bundle_loaded": (
                getattr(error, "next_bundle_loaded", None) if error is not None else None
            ),
            "next_epoch_load_permitted": (
                getattr(error, "next_epoch_load_permitted", None) if error is not None else None
            ),
            "trace_event_counts": tuple(sorted(trace_counts.items())),
            "context_facts": tuple(context_facts),
            "api_facts": tuple(api_facts),
            "pending_callback_count": clock.pending_callback_count,
            "pending_callback_owner_counts": clock.pending_callback_owner_counts,
            "consumed_tick_samples": tuple(clock._consumed_tick_samples),
            "snapshot_call_count": snapshot_call_count,
            "refresh_started": refresh_state["started"],
            "refresh_completed": refresh_state["completed"],
            "unique_batch_count": len(batch_facts_by_id),
            "complete_batch_count": len(complete_batches),
            "complete_batch_readiness_counts": tuple(sorted(readiness_counts.items())),
            "complete_batch_factor_output_counts": tuple(
                (name, *counts) for name, counts in sorted(factor_counts.items())
            ),
            "strategy_fact_count": len(strategy_rows),
            "target_status_counts": count_field(strategy_rows, "target_status"),
            "target_reason_counts": count_field(strategy_rows, "target_reason"),
            "plan_status_counts": count_field(strategy_rows, "plan_status"),
            "plan_reason_counts": count_field(strategy_rows, "plan_reason"),
            "action_counts": tuple(sorted(action_counts.items())),
            "quote_predicate_sample": (
                quote_predicate_sample_state["stale"]
                or quote_predicate_sample_state["target_ready"]
            ),
            "signal_block_reason_counts": count_field(strategy_rows, "last_signal_block_reason"),
            "execution_block_reason_counts": count_field(
                strategy_rows, "last_execution_block_reason"
            ),
            "strategy_facts_sample": tuple(strategy_rows[-3:]),
            "strategy_decision_samples": tuple(
                row for row in strategy_rows if is_target_ready_or_open_blocked(row)
            )[:6],
            "action_source_order_samples": tuple(row for row in strategy_rows if row["actions"])[
                :4
            ],
        }

    def persist_failure_facts(facts):
        diagnostic_path = tmp_path / "rollover-failure-facts.json"
        aggregate_facts = {
            key: value for key, value in facts.items() if key != "quote_predicate_sample"
        }
        return _write_rollover_diagnostic(
            diagnostic_path,
            {
                "schema": "alpha003.rollover.failure_facts.v1",
                "epoch_count": len(contexts),
                "quote_predicate_sample": facts.get("quote_predicate_sample"),
                "facts": aggregate_facts,
            },
        )

    try:
        result = RUNNER.run_live_epochs(
            config,
            config_path,
            first_plan,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=True,
        )
    except BaseException as error:
        diagnostic = failure_facts(error)
        diagnostic_path = persist_failure_facts(diagnostic)
        diagnostic["diagnostic_path"] = str(diagnostic_path)
        evidence["failure_facts"] = diagnostic
        error.rollover_diagnostics = diagnostic
        error.rollover_evidence = evidence
        raise
    diagnostic = failure_facts()
    diagnostic_path = persist_failure_facts(diagnostic)
    diagnostic["diagnostic_path"] = str(diagnostic_path)
    evidence["failure_facts"] = diagnostic
    return result, evidence


def test_main_contract_rollover_closes_old_route_before_fresh_new_epoch(tmp_path, monkeypatch):
    result, evidence = _run_rollover(tmp_path, monkeypatch)

    assert result["status"] == "LIVE_EPOCH_SEQUENCE_COMPLETE"
    assert result["epoch_count"] == 2
    assert result["assembly_attempts"] == [1, 2]
    assert len(evidence["apis"]) == 2
    old_api, new_api = evidence["apis"]
    assert old_api.closed is True and new_api.closed is True

    old_routes = result["epochs"][0]["routes"]
    new_routes = result["epochs"][1]["routes"]
    assert set(old_routes) == set(new_routes) == {"DCE.M", "DCE.Y", "DCE.A"}
    assert all(old_routes[target] == target.split(".")[1] + "2612" for target in old_routes)
    assert all(new_routes[target] == target.split(".")[1] + "2611" for target in new_routes)

    old_calls = evidence["contexts"][1].native_calls
    assert any(call[0] == "cancel" for call in old_calls), evidence["failure_facts"]
    assert any(call[0] == "insert" and call[3].startswith("close") for call in old_calls), evidence[
        "failure_facts"
    ]
    assert all(call[2] in set(old_routes.values()) for call in old_calls), old_calls
    assert any(call[0] == "close_fill" for call in evidence["trace"]), evidence["trace"][-20:]
    assert evidence["contexts"][1].rows["positions_result"] == []
    assert evidence["contexts"][2].native_calls
    old_order_events = result["epochs"][0]["strategy_order_events"]["events"]
    assert any(event["status"] == "CANCELED" for event in old_order_events), old_order_events
    assert any(event["status"] == "COMPLETED" for event in old_order_events), old_order_events
    assert _has_causal_action_facts(
        evidence["failure_facts"]["action_source_order_samples"],
        {route[1] for route in evidence["contexts"][1].routes},
    ), evidence["failure_facts"]

    trace = evidence["trace"]
    cancel_index = next(
        index for index, row in enumerate(trace) if row[0] == "cancel" and row[1] == 1
    )
    close_index = next(
        index
        for index, row in enumerate(trace)
        if row[0] == "insert" and row[1] == 1 and row[3].startswith("close")
    )
    retired_index = trace.index(("api_closed", 1))
    close_fill_index = next(
        index
        for index, row in enumerate(trace)
        if row[0] == "close_fill" and row[1] == 1 and row[2] in set(old_routes.values())
    )
    bundle_index = next(
        index for index, row in enumerate(trace) if row[0] == "second_bundle_loaded"
    )
    new_cohort_index = trace.index(("cohort_assembled", 2))
    callbacks_index = trace.index(("prior_callbacks_drained", 1, 0))
    assert (
        cancel_index
        < close_index
        < close_fill_index
        < retired_index
        < bundle_index
        < callbacks_index
        < new_cohort_index
    )

    batches = {
        epoch_id: [item for item in evidence["batches"] if item["epoch_id"] == epoch_id]
        for epoch_id in (1, 2)
    }
    assert all(batches.values()), evidence["batches"]
    first_data = batches[1][0]["data"]
    second_data = batches[2][0]["data"]
    assert {row[0] for row in first_data} == set(old_routes)
    assert {row[0] for row in second_data} == set(new_routes)
    assert all(row[1] == old_routes[row[0]] and row[2] == 1 for row in first_data)
    assert all(row[1] == new_routes[row[0]] and row[2] == 1 for row in second_data)
    assert all(100.0 <= row[3] < 110.0 for row in first_data)
    assert all(200.0 <= row[3] < 210.0 for row in second_data)
    assert any(item["readiness"] == "LIVE_READY" for item in batches[2]), batches[2]
    ready_index = next(
        index
        for index, row in enumerate(trace)
        if row[0] == "batch_snapshot" and row[1] == 2 and row[2] == "LIVE_READY"
    )
    new_open_index = next(
        index
        for index, row in enumerate(trace)
        if row[0] == "insert" and row[1] == 2 and row[3] == "open"
    )
    assert ready_index < new_open_index


def test_unknown_old_epoch_order_blocks_next_bundle_and_new_open(tmp_path, monkeypatch):
    error = None
    evidence = None
    try:
        _result, evidence = _run_rollover(tmp_path, monkeypatch, unknown_dispatch=True)
    except BaseException as exc:
        error = exc
        evidence = getattr(exc, "rollover_evidence", None)
    diagnostic = evidence.get("failure_facts", {}) if isinstance(evidence, dict) else None
    assert error is not None, diagnostic
    diagnostic = getattr(error, "rollover_diagnostics", {})
    diagnostic_message = "bounded fake-fixture facts: {!r}".format(diagnostic)
    # The fake SDK dispatch result is not a planner flag: RegisteredSim sees a
    # real native-method nonzero result, freezes the old route and records the
    # exact order reference as UNKNOWN.
    assert getattr(error, "next_bundle_read_count", None) == 0, diagnostic_message
    assert getattr(error, "next_bundle_loaded", None) is False, diagnostic_message
    assert getattr(error, "next_epoch_load_permitted", None) is False, diagnostic_message
    assert getattr(error, "assembly_attempts", None) == (1,), diagnostic_message
    assert evidence is not None
    assert len(evidence["apis"]) == 1, diagnostic_message
    api = evidence["apis"][0]
    context = evidence["contexts"][1]
    unknown_calls = [call for call in context.native_calls if call[0] == "insert_unknown"]
    assert len(unknown_calls) == 1, diagnostic_message
    unknown_id = unknown_calls[0][4]
    registered_state = api.registered_sim_execution_facts()
    assert registered_state["unknown_ids"] == [unknown_id], diagnostic_message
    assert not any(call[0] == "cancel" for call in context.native_calls)
    assert not any(call[0] == "insert" for call in context.native_calls)
    assert _has_causal_action_facts(
        diagnostic["action_source_order_samples"],
        {route[1] for route in context.routes},
    ), diagnostic_message
    assert not any(row[0] == "second_bundle_loaded" for row in evidence["trace"])
    assert not any(row[0] == "api_created" and row[1] == 2 for row in evidence["trace"])
    assert not any(row[0] == "cohort_assembled" and row[1] == 2 for row in evidence["trace"])
