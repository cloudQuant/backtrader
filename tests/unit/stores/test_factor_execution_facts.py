"""Integration checks for the RegisteredSim no-I/O execution-facts bridge."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from types import SimpleNamespace
import time

import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.events import TickEvent
from backtrader.order import BuyOrder, Order, SellOrder
from backtrader.stores import execution_decision_journal as execution_decision_journal_module
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionKey,
    ExecutionIntentKey,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator
from backtrader.stores.factor_execution_facts import (
    FactorExecutionTarget,
    project_factor_execution_facts,
    refresh_factor_execution_queries,
)
from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper


_INSTRUMENT = "rb2510"
_EXCHANGE = "SHFE"
_ACCOUNT = "fake-account-1"
_TRADING_DAY = "20261024"
_REGISTERED_TICK_SOURCE = "ctp-native-live"
_UNTRUSTED_TICK_SOURCE = "fake-ctp-event"


@dataclass(frozen=True)
class _QuerySource:
    issuer: object
    request_type: str
    request_id: int
    connection_generation: int
    account_fingerprint: str
    trading_day: str
    started_at_utc: datetime
    completed_at_utc: datetime
    started_monotonic: float
    completed_monotonic: float
    trusted_expires_monotonic: float
    records_sha256: str
    explicit_request_filters: tuple


@dataclass(frozen=True)
class _QueryResult:
    """Typed fake provider leaf with the public CTP QueryResult contract."""

    request_type: str
    request_id: int
    connection_generation: int
    account_fingerprint: str
    started_at_utc: datetime
    completed_at_utc: datetime
    is_last_seen: bool
    error_code: object
    error_message: str
    timed_out: bool
    complete: bool
    records: tuple
    late_callback_count: int
    unsupported: bool
    submit_code: int
    query_source: _QuerySource


class _QueryClient:
    def __init__(self):
        self._query_issuer = object()
        self._connection_generation = 1
        self._account_fingerprint = _ACCOUNT
        self._trading_day = _TRADING_DAY
        self.is_ready = True
        self.is_trading_ready = True
        self._gate_state = {
            "managed": False,
            "armed": False,
            "instrument": None,
            "authorized_instruments": [],
            "connection_generation": self._connection_generation,
            "trading_day": self._trading_day,
            "scope_version": "ctp-contract-bundle-v1",
            "proof_sha256": "c" * 64,
            "environment_profile": "simnow_demo",
            "revocation_reason": None,
        }

    def get_query_session_scope(self):
        return SimpleNamespace(
            issuer=self._query_issuer,
            connection_generation=self._connection_generation,
            account_fingerprint=self._account_fingerprint,
            trading_day=self._trading_day,
            read_only_ready=True,
        )

    def get_execution_gate_state(self):
        return dict(self._gate_state)

    def get_session_state(self):
        return {
            "account_fingerprint": self._account_fingerprint,
            "connection_generation": self._connection_generation,
            "trading_day": self._trading_day,
            "trading_ready": self.is_trading_ready,
        }

    def arm_execution_for_registered_sim(
        self,
        *,
        instrument_id,
        exchange_id,
        md_front,
        strategy_identity_sha256,
        execution_cycle_id,
        preflight_sha256,
    ):
        del exchange_id, md_front, strategy_identity_sha256, execution_cycle_id, preflight_sha256
        self._gate_state = {
            "managed": True,
            "armed": True,
            "instrument": instrument_id,
            "authorized_instruments": [instrument_id],
            "connection_generation": self._connection_generation,
            "trading_day": self._trading_day,
            "scope_version": "ctp-contract-bundle-v1",
            "proof_sha256": "c" * 64,
            "environment_profile": "simnow_demo",
            "revocation_reason": None,
        }
        return object(), dict(self._gate_state)


class _ProviderLeaves:
    """Fake only the CTP query/tick leaves; the Store and Broker stay real."""

    def __init__(self, *, query_rows=None, query_time=None, tick=None, ticks=None, **kwargs):
        del kwargs
        self.trader_client = _QueryClient()
        self.query_rows = dict(query_rows or {})
        self.query_time = query_time or datetime.now(timezone.utc)
        self.tick = tick
        self.ticks = dict(ticks or {})
        self.query_calls = []
        self._next_request_id = 0
        self._registered_sim_allow_writes = True
        self._use_observed_query_clock = False

    def _query(self, request_type, rows, *, filters=()):
        self._next_request_id += 1
        request_id = self._next_request_id
        if self._use_observed_query_clock:
            # After a durable execution receipt, model the provider query's
            # actual synchronous start/completion boundary. A static planned
            # timestamp can otherwise make a query invoked after the receipt
            # appear older than that receipt.
            started = datetime.now(timezone.utc)
        else:
            started = self.query_time - timedelta(milliseconds=2)
        mono = time.monotonic()
        records_sha256 = sha256(
            json.dumps(
                rows,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        completed = (
            datetime.now(timezone.utc)
            if self._use_observed_query_clock
            else self.query_time - timedelta(milliseconds=1)
        )
        source = _QuerySource(
            issuer=self.trader_client._query_issuer,
            request_type=request_type,
            request_id=request_id,
            connection_generation=self.trader_client._connection_generation,
            account_fingerprint=self.trader_client._account_fingerprint,
            trading_day=self.trader_client._trading_day,
            started_at_utc=started,
            completed_at_utc=completed,
            started_monotonic=mono - 0.002,
            completed_monotonic=mono - 0.001,
            trusted_expires_monotonic=mono + 30.0,
            records_sha256=records_sha256,
            explicit_request_filters=tuple(filters),
        )
        return _QueryResult(
            request_type=request_type,
            request_id=request_id,
            connection_generation=self.trader_client._connection_generation,
            account_fingerprint=self.trader_client._account_fingerprint,
            started_at_utc=started,
            completed_at_utc=completed,
            is_last_seen=True,
            error_code=None,
            error_message="",
            timed_out=False,
            complete=True,
            records=tuple(rows),
            late_callback_count=0,
            unsupported=False,
            submit_code=0,
            query_source=source,
        )

    def _query_family(self, family, request_type, **filters):
        self.query_calls.append((family, dict(filters)))
        rows = self.query_rows.get(family, [])
        source_filters = ("HedgeFlag",) if family == "instrument_margin_rate_result" else ()
        return self._query(request_type, rows, filters=source_filters)

    def query_account_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query_family("account_result", "account", **filters)

    def query_positions_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query_family("positions_result", "positions", **filters)

    def query_orders_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query_family("orders_result", "orders", **filters)

    def query_trades_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query_family("trades_result", "trades", **filters)

    def query_instruments_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query_family("instruments_result", "instruments", **filters)

    def query_instrument_margin_rate_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query_family("instrument_margin_rate_result", "margin_rate", **filters)

    def poll_tick(self, symbol):
        if symbol in self.ticks:
            return self.ticks.pop(symbol)
        if symbol != _INSTRUMENT:
            return None
        tick, self.tick = self.tick, None
        return tick


class _FakeRegisteredSimWrapper(RegisteredSimWrapper, _ProviderLeaves):
    pass


class _MissingRegisteredTickSourceStore(RegisteredSimStore):
    def __getattribute__(self, name):
        if name == "registered_sim_tick_source":
            raise AttributeError(name)
        return object.__getattribute__(self, name)


class _MismatchedConsumedSourceStore(RegisteredSimStore):
    def get_latest_tick_snapshot(self, dataname):
        tick = super().get_latest_tick_snapshot(dataname)
        if tick is not None:
            tick.source = "different-registered-source"
        return tick


def _quote(
    *,
    event_time,
    received_at=None,
    symbol=_INSTRUMENT,
    exchange=_EXCHANGE,
    generation=1,
    sequence=1,
    trading_day=_TRADING_DAY,
    source=_REGISTERED_TICK_SOURCE,
):
    received_at = received_at or event_time + timedelta(milliseconds=10)
    tick = TickEvent(
        timestamp=event_time.timestamp(),
        symbol=symbol,
        exchange=exchange,
        price=100.0,
        volume=1.0,
        bid_price=99.0,
        ask_price=101.0,
        bid_volume=5.0,
        ask_volume=6.0,
        exchange_time=event_time.timestamp(),
        received_wall_time=received_at.timestamp(),
        sequence=sequence,
        snapshot_or_delta="snapshot",
        continuity_status="continuous",
        stale=False,
        source=source,
        event_id="tick-{}".format(sequence),
        coalesced_count=1,
    )
    tick.instrument_id = symbol
    tick.exchange_id = exchange
    tick.trading_day = trading_day
    tick.connection_generation = generation
    tick.stream_generation = generation
    tick.ingest_seq = sequence
    return tick


def _query_rows(*, positions=(), orders=(), trades=(), account=None, include_margin=True):
    orders = tuple(dict(row, TradingDay=row.get("TradingDay", _TRADING_DAY)) for row in orders)
    trades = tuple(dict(row, TradingDay=row.get("TradingDay", _TRADING_DAY)) for row in trades)
    rows = {
        "account_result": [
            account
            or {
                "Available": "100000",
                "CurrMargin": "0",
            }
        ],
        "positions_result": list(positions),
        "orders_result": list(orders),
        "trades_result": list(trades),
        "instruments_result": [
            {
                "InstrumentID": _INSTRUMENT,
                "ExchangeID": _EXCHANGE,
                "IsTrading": 1,
                "VolumeMultiple": 10,
                "PriceTick": 1,
                "LowerLimitPrice": 1,
                "UpperLimitPrice": 1000,
            }
        ],
        "instrument_margin_rate_result": (
            [
                {
                    "InstrumentID": _INSTRUMENT,
                    "ExchangeID": _EXCHANGE,
                    "HedgeFlag": "1",
                    "LongMarginRatioByMoney": "0.1",
                    "LongMarginRatioByVolume": "0",
                    "ShortMarginRatioByMoney": "0.1",
                    "ShortMarginRatioByVolume": "0",
                }
            ]
            if include_margin
            else []
        ),
    }
    return rows


def _dated_position_row(
    quantity,
    *,
    position_date="TODAY",
    side="LONG",
    hedge_flag="1",
    trading_day=_TRADING_DAY,
    today_position=None,
    yd_position=None,
    **overrides,
):
    """One exact public CTP position bucket for source-backed close tests."""

    quantity = str(quantity)
    today = quantity if position_date == "TODAY" else "0"
    row = {
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "PosiDirection": "2" if side == "LONG" else "3",
        "HedgeFlag": hedge_flag,
        "PositionDate": "1" if position_date == "TODAY" else "2",
        "TradingDay": trading_day,
        "Position": quantity,
        "TodayPosition": today if today_position is None else str(today_position),
        "YdPosition": ("0" if position_date == "TODAY" else quantity)
        if yd_position is None
        else str(yd_position),
        "LongFrozen": "0",
        "ShortFrozen": "0",
        "CombLongFrozen": "0",
        "CombShortFrozen": "0",
        "StrikeFrozen": "0",
        "AbandonFrozen": "0",
        "LongFrozenAmount": "0",
        "ShortFrozenAmount": "0",
        "FrozenMargin": "0",
        "FrozenCash": "0",
        "FrozenCommission": "0",
        "StrikeFrozenAmount": "0",
        "YdStrikeFrozen": "0",
    }
    row.update(overrides)
    return row


def _query_trade_for_fill(
    *, trade_id, order_ref, order_sys_id, filled_at, quantity, price, offset_flag="0"
):
    source_time = filled_at.astimezone(timezone(timedelta(hours=8)))
    return {
        "TradeID": trade_id,
        "OrderRef": order_ref,
        "OrderSysID": order_sys_id,
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "Direction": "0" if Decimal(str(quantity)) > 0 else "1",
        "OffsetFlag": offset_flag,
        "HedgeFlag": "1",
        "Volume": str(abs(Decimal(str(quantity)))),
        "Price": str(price),
        "TradeDate": source_time.strftime("%Y%m%d"),
        "TradeTime": source_time.strftime("%H:%M:%S.%f"),
        "TradingDay": _TRADING_DAY,
    }


def _execution_id_from_trade_row(row):
    """Mirror the public identity inputs without conflating TradeDate/day."""

    return "ctp:{}:{}".format(row["TradeDate"], row["TradeID"])


def test_execution_identity_uses_trade_date_across_trading_day_boundary():
    row = _query_trade_for_fill(
        trade_id="crossnight-trade",
        order_ref="17",
        order_sys_id="native-17",
        filled_at=datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc),
        quantity="1",
        price="100",
    )

    assert row["TradingDay"] == _TRADING_DAY
    assert row["TradeDate"] == "20261025"
    assert _execution_id_from_trade_row(row) == "ctp:20261025:crossnight-trade"


def _system_under_test(
    *,
    now=None,
    rows=None,
    tick=None,
    query_time=None,
    journal_path=":memory:",
    store_cls=RegisteredSimStore,
    provenance_source=_UNTRUSTED_TICK_SOURCE,
    allow_writes=True,
):
    now = now or datetime.now(timezone.utc)
    api = _FakeRegisteredSimWrapper(
        registered_sim_allow_writes=allow_writes,
        query_rows=rows or _query_rows(),
        query_time=query_time or now - timedelta(seconds=1),
        tick=tick or _quote(event_time=now - timedelta(milliseconds=200)),
    )
    api.live_tick_provenance = {"source": provenance_source}
    store = store_cls(
        api=api,
        allow_writes=allow_writes,
        live_tick_provenance={"source": provenance_source},
    )
    store._connected = True
    data = SimpleNamespace(_name=_INSTRUMENT)
    broker = BtApiBroker(
        store=store,
        contract_metadata={_INSTRUMENT: {"instrument_id": _INSTRUMENT, "exchange_id": _EXCHANGE}},
    )
    journal = ExecutionDecisionJournal(journal_path)
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope="acct-scope",
        strategy_scope="alpha003",
        logical_run_id="run-1",
        max_order_intents_per_grid=4,
        max_order_intents_per_run=1000,
    )
    target = FactorExecutionTarget("rb", _INSTRUMENT, _EXCHANGE, data)
    return api, store, broker, journal, coordinator, target


def _build_source_backed_read_only_reconciliation_case(scenario="positive"):
    """Build read-only retirement facts through the real Store/Broker/Book path.

    Provider queries remain typed fake leaves. The returned ``facts`` are
    always produced by the production projection and are never constructed
    directly by this helper.
    """
    scenarios = {
        "positive",
        "stale_query",
        "session_mismatch",
        "unknown_order",
        "pending_order",
        "active_order",
        "frozen",
    }
    if scenario not in scenarios:
        raise ValueError("unsupported read-only reconciliation scenario")

    now = datetime.now(timezone.utc)
    query_time = now - timedelta(minutes=1) if scenario == "stale_query" else now
    remote_order = None
    if scenario in {"pending_order", "active_order"}:
        remote_order = {
            "OrderRef": "94",
            "OrderSysID": "sys-active-94",
            "InstrumentID": _INSTRUMENT,
            "ExchangeID": _EXCHANGE,
            "OrderStatus": "3",
            "Direction": "0",
            "CombOffsetFlag": "0",
            "VolumeTotal": "1",
            "FrontID": 4,
            "SessionID": 7,
            "TradingDay": _TRADING_DAY,
        }
    rows = _query_rows(orders=(remote_order,) if remote_order is not None else ())
    api, store, broker, journal, coordinator, target = _system_under_test(
        now=now,
        rows=rows,
        query_time=query_time,
        tick=None,
        allow_writes=False,
    )
    receipt = _refresh_all(store, target)

    intent = None
    if scenario == "active_order":
        decision_key = ExecutionDecisionKey(
            account_scope="acct-scope",
            strategy_scope="alpha003",
            logical_run_id="run-1",
            cohort_id="read-only-fixture",
            close_time=(now - timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
            decision_kind="alpha003-rebalance",
        )
        intent_key = ExecutionIntentKey(
            action="SUBMIT",
            instrument=_INSTRUMENT,
            side="BUY",
            position_effect="OPEN",
            leg=0,
        )
        decision = journal.record_decision(
            decision_key,
            {"batch_id": "read-only-batch", "mode": "native"},
            intent_keys=(intent_key,),
        )
        intent = journal.prepare_intent(
            decision.decision_id,
            intent_key,
            {"exchange": _EXCHANGE, "quantity": "1", "price": "100"},
            original_identity={
                "backtrader_order_ref": 94,
                "operation": "insert",
                "instrument_id": _INSTRUMENT,
                "exchange_id": _EXCHANGE,
                "order_ref": "94",
                "order_sys_id": "sys-active-94",
                "trading_day": _TRADING_DAY,
            },
        )
        assert journal.claim_dispatch(intent.intent_id) is not None
        journal.record_dispatch_result(
            intent.intent_id,
            state="KNOWN",
            provider_identity={"order_ref": "94", "order_sys_id": "sys-active-94"},
            outcome_code="accepted",
        )
        order = BuyOrder(
            owner=None,
            data=target.data,
            size=1,
            price=100,
            exectype=Order.Limit,
            simulated=True,
        )
        order.status = Order.Accepted
        order.info.update(
            {
                "external_order_ref": "94",
                "order_sys_id": "sys-active-94",
                "instrument_id": _INSTRUMENT,
                "exchange_id": _EXCHANGE,
                "factor_position_effect": "OPEN",
                "factor_strategy_scope": "alpha003",
                "factor_intent_id": intent.intent_id,
                "front_id": 4,
                "session_id": 7,
                "execution_unknown": False,
                "cancel_requested_remote": False,
                "cancel_intent_active": False,
                "managed_execution_cancel_pending": False,
            }
        )
        broker.orders[order.ref] = order

    if scenario == "unknown_order":
        api._order_state["unknown-94"] = "unknown"
    elif scenario == "session_mismatch":
        api.trader_client._account_fingerprint = "different-account"
    elif scenario == "frozen":
        store.registered_sim_freeze("read-only fixture freeze")

    # Read-only session identity remains observable even without permission to
    # trade; this is distinct from the current trading-ready fact.
    api.trader_client.is_ready = False
    api.trader_client.is_trading_ready = False
    projection_now = datetime.now(timezone.utc)
    facts = project_factor_execution_facts(
        store,
        broker,
        targets=(target,),
        account_scope="acct-scope",
        strategy_scope="alpha003",
        now=projection_now,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=10),
        query_set=receipt.query_set,
    )
    return SimpleNamespace(
        api=api,
        store=store,
        broker=broker,
        journal=journal,
        coordinator=coordinator,
        target=target,
        receipt=receipt,
        query_set=receipt.query_set,
        now=projection_now,
        facts=facts,
        intent=intent,
    )


def _multi_target_system_under_test(*, now, target_specs, missing_template=()):
    """Keep the real Store/Broker/coordinator path with only provider leaves faked."""

    rows = _query_rows()
    rows["instruments_result"] = [
        {
            "InstrumentID": instrument,
            "ExchangeID": exchange,
            "IsTrading": 1,
            "VolumeMultiple": 10,
            "PriceTick": 1,
            "LowerLimitPrice": 1,
            "UpperLimitPrice": 1000,
        }
        for _target_id, instrument, exchange in target_specs
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
        for _target_id, instrument, exchange in target_specs
    ]
    ticks = {
        instrument: _quote(
            event_time=now - timedelta(milliseconds=200),
            symbol=instrument,
            exchange=exchange,
            sequence=index + 1,
        )
        for index, (_target_id, instrument, exchange) in enumerate(target_specs)
    }
    api = _FakeRegisteredSimWrapper(
        registered_sim_allow_writes=True,
        query_rows=rows,
        query_time=now - timedelta(seconds=1),
        ticks=ticks,
    )
    api.live_tick_provenance = {"source": _UNTRUSTED_TICK_SOURCE}
    store = RegisteredSimStore(
        api=api,
        allow_writes=True,
        live_tick_provenance={"source": _UNTRUSTED_TICK_SOURCE},
    )
    store._connected = True
    targets = tuple(
        FactorExecutionTarget(target_id, instrument, exchange, SimpleNamespace(_name=instrument))
        for target_id, instrument, exchange in target_specs
    )
    contract_metadata = {
        instrument: {"instrument_id": instrument, "exchange_id": exchange}
        for _target_id, instrument, exchange in target_specs
    }
    broker = BtApiBroker(store=store, contract_metadata=contract_metadata)
    journal = ExecutionDecisionJournal(":memory:")
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope="acct-scope",
        strategy_scope="alpha003",
        logical_run_id="run-1",
        max_order_intents_per_grid=4,
        max_order_intents_per_run=1000,
    )
    arm_templates = {
        (instrument, exchange): {
            "md_front": "tcp://127.0.0.1:1",
            "strategy_identity_sha256": "a" * 64,
            "execution_cycle_id": "cycle-{}".format(target_id),
            "preflight_sha256": "b" * 64,
        }
        for target_id, instrument, exchange in target_specs
        if (target_id, instrument, exchange) not in missing_template
    }
    store.registered_sim_configure_arm_templates(arm_templates)
    return api, store, broker, journal, coordinator, targets, arm_templates


def _refresh_all(store, target):
    receipt = refresh_factor_execution_queries(
        store,
        targets=(target,),
        overall_timeout=4.0,
    )
    assert receipt.blockers == ()
    assert receipt.pending_families == ()
    assert len(receipt.attempted_families) == 6
    return receipt


def _refresh_complete_facts_after_callback(api, store, target, *, sequence, trading_day):
    """Take a fresh full query set after durable execution/book receipts.

    The provider leaf stamps each query when this synchronous refresh actually
    starts and completes. It does not reuse the earlier planned timestamp or
    move the projection clock forward to admit future source facts.
    """
    api._use_observed_query_clock = True
    receipt = _refresh_all(store, target)
    query_completed_at = receipt.query_set.completed_at_utc
    quote_received_at = datetime.now(timezone.utc)
    assert quote_received_at >= query_completed_at
    api.tick = _quote(
        event_time=query_completed_at,
        received_at=quote_received_at,
        sequence=sequence,
        trading_day=trading_day,
    )
    consumed = _consume_quote(store)
    assert consumed is not None
    projection_now = datetime.now(timezone.utc)
    assert receipt.query_set.completed_at_utc <= projection_now
    assert consumed.timestamp <= projection_now.timestamp()
    assert consumed.received_wall_time >= receipt.query_set.completed_at_utc.timestamp()
    assert consumed.received_wall_time <= projection_now.timestamp()
    return receipt, projection_now, consumed


def _arm(store):
    store.registered_sim_configure_arm_templates(
        {
            (_INSTRUMENT, _EXCHANGE): {
                "md_front": "tcp://127.0.0.1:1",
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "cycle-1",
                "preflight_sha256": "b" * 64,
            }
        }
    )
    store.registered_sim_arm(
        instrument=_INSTRUMENT,
        exchange=_EXCHANGE,
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256="a" * 64,
        execution_cycle_id="cycle-1",
        preflight_sha256="b" * 64,
    )


def _consume_quote(store):
    return store.poll_tick(_INSTRUMENT)


def _project(
    store,
    broker,
    target,
    now,
    *,
    query_set=None,
    max_query_age=timedelta(seconds=10),
):
    return project_factor_execution_facts(
        store,
        broker,
        targets=(target,),
        account_scope="acct-scope",
        strategy_scope="alpha003",
        now=now,
        quote_max_age=timedelta(seconds=2),
        max_query_age=max_query_age,
        query_set=query_set,
    )


def test_real_registered_store_and_broker_project_a_complete_flat_snapshot():
    now = datetime.now(timezone.utc)
    api, store, broker, journal, coordinator, target = _system_under_test(now=now)
    receipt = _refresh_all(store, target)
    _arm(store)
    consumed = _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert consumed is not None
    assert tuple(fact.family for fact in receipt.query_provenance) == (
        "account_result",
        "orders_result",
        "trades_result",
        "instruments_result",
        "positions_result",
        "instrument_margin_rate_result",
    )
    assert facts.account is not None
    assert facts.account.available_margin == Decimal("100000")
    assert facts.account.used_margin == Decimal(0)
    assert facts.positions[0].quantity == Decimal(0), facts.blockers
    assert facts.positions[0].long_quantity == Decimal(0)
    assert facts.positions[0].short_quantity == Decimal(0)
    assert facts.quotes[0].quality == "GOOD"
    assert facts.quotes[0].source_ref == consumed.event_id
    assert facts.instruments[0].long_margin_per_hand == Decimal("101.0")
    assert facts.risk_reduction_ready is True, facts.blockers
    assert facts.open_risk_ready is True
    assert facts.blockers == ()
    assert coordinator.position_book is not None
    assert journal is coordinator.journal
    assert len(api.query_calls) == 6


def test_configured_templates_keep_all_target_routes_plannable_with_one_active_grant():
    now = datetime.now(timezone.utc)
    target_specs = (
        ("rb", "rb2510", "SHFE"),
        ("cu", "cu2510", "SHFE"),
        ("au", "au2512", "SHFE"),
    )
    (
        api,
        store,
        broker,
        _journal,
        _coordinator,
        targets,
        templates,
    ) = _multi_target_system_under_test(now=now, target_specs=target_specs)
    receipt = refresh_factor_execution_queries(
        store,
        targets=targets,
        overall_timeout=4.0,
    )
    assert receipt.blockers == ()
    assert receipt.pending_families == ()
    assert receipt.query_set is not None
    for target in targets:
        assert store.poll_tick(target.instrument) is not None

    # One target currently holds the single SDK grant. Planning facts for the
    # other exact, configured routes remain eligible without pretending that
    # their capabilities are armed.
    first = targets[0]
    first_template = templates[(first.instrument, first.exchange)]
    store.registered_sim_arm(
        instrument=first.instrument,
        exchange=first.exchange,
        **first_template,
    )
    facts = project_factor_execution_facts(
        store,
        broker,
        targets=targets,
        account_scope="acct-scope",
        strategy_scope="alpha003",
        now=now,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=10),
        query_set=receipt.query_set,
    )

    assert facts.blockers == (), facts.blockers
    assert len(facts.positions) == len(facts.quotes) == len(facts.instruments) == 3
    assert facts.account is not None and facts.account.route_permitted is True
    assert facts.open_risk_ready is True, facts.blockers
    assert [route.eligible for route in facts.route_eligibilities] == [True, True, True]
    assert all(route.arm_template_configured is True for route in facts.route_eligibilities)
    assert all(route.arm_templates_configured is True for route in facts.route_eligibilities)
    assert all(route.arm_api_available is True for route in facts.route_eligibilities)
    assert all(route.current_session_trading_ready is True for route in facts.route_eligibilities)
    assert [route.capability_matches_route for route in facts.route_eligibilities] == [
        True,
        False,
        False,
    ]
    # `capability_armed` is the SDK's current global arm state. Per-route
    # identity is represented separately by `capability_matches_route`.
    assert [route.capability_armed for route in facts.route_eligibilities] == [True, True, True]
    assert len(api.registered_sim_arm_history()) == 1


def test_read_only_reconciliation_accepts_coherent_flat_shadow_without_quote_or_grant():
    case = _build_source_backed_read_only_reconciliation_case()
    facts = case.facts

    assert facts.account is not None
    assert facts.account.route_permitted is False
    assert facts.quotes[0].quality != "GOOD"
    assert facts.route_eligibilities[0].capability_armed is False
    assert facts.route_eligibilities[0].current_session_trading_ready is False
    assert facts.positions[0].quantity == Decimal(0)
    assert facts.working_orders == ()
    assert facts.risk_reduction_ready is False
    assert facts.read_only_reconciliation_ready is True, facts.read_only_reconciliation_blockers
    assert facts.read_only_reconciliation_blockers == ()


def test_read_only_reconciliation_keeps_book_blocker_for_joined_active_order():
    case = _build_source_backed_read_only_reconciliation_case(scenario="active_order")
    facts = case.facts

    assert case.intent is not None
    # The active order is joined and known, but the durable position book
    # intentionally marks its instrument attribution unresolved while that
    # order is live. Retirement readiness must preserve that blocker; Strategy
    # separately checks the owned working order as well.
    assert facts.read_only_reconciliation_ready is False
    assert "INSTRUMENT_ORDER_UNRESOLVED" in facts.read_only_reconciliation_blockers
    assert len(facts.working_orders) == 1
    working = facts.working_orders[0]
    assert working.state == "ACCEPTED"
    assert working.owner_strategy_scope == "alpha003"
    assert working.owner_intent_id == case.intent.intent_id
    assert working.execution_unknown is False
    # Strategy performs its existing no-owned-working-order retirement check.
    assert working.owner_strategy_scope == facts.strategy_scope


def test_cancel_ignores_book_order_reservation_only_for_exact_owned_join():
    case = _build_source_backed_read_only_reconciliation_case(scenario="active_order")
    facts = case.facts

    assert facts.positions[0].position_book_status == "UNKNOWN"
    assert facts.positions[0].position_book_blocker_code == "INSTRUMENT_ORDER_UNRESOLVED"
    assert "INSTRUMENT_ORDER_UNRESOLVED" in facts.blockers
    assert "INSTRUMENT_ORDER_UNRESOLVED" in facts.read_only_reconciliation_blockers
    assert "INSTRUMENT_ORDER_UNRESOLVED" not in facts.order_cancel_blockers
    preserved_position_only = (
        "position_metadata_unavailable:rb",
        "position_book_cursor_unavailable:rb",
        "broker_position_projection_unavailable:rb",
    )
    facts_with_position_only = replace(facts, blockers=facts.blockers + preserved_position_only)
    assert all(
        code not in facts_with_position_only.order_cancel_blockers
        for code in preserved_position_only
    )
    # The shadow fixture has no write permission; classifying this position
    # blocker cannot turn it into cancellation authority.
    assert facts.order_cancel_ready is False

    order = facts.working_orders[0]
    invalid_variants = (
        replace(order, owner_strategy_scope="other-strategy"),
        replace(order, owner_intent_id=None),
        replace(order, execution_unknown=True),
        replace(order, cancel_pending=True),
        replace(order, state="UNKNOWN"),
        replace(order, target_id=None),
        replace(order, exchange="DCE"),
        replace(order, broker_order_ref=None),
        replace(order, front_id=None),
        replace(order, session_id=None),
    )
    for invalid_order in invalid_variants:
        invalid_facts = replace(facts, working_orders=(invalid_order,))
        assert "INSTRUMENT_ORDER_UNRESOLVED" in invalid_facts.order_cancel_blockers

    no_order_facts = replace(facts, working_orders=())
    assert "INSTRUMENT_ORDER_UNRESOLVED" in no_order_facts.order_cancel_blockers

    mismatched_facts = replace(
        facts,
        blockers=facts.blockers + ("remote_broker_order_front_mismatch:94",),
    )
    assert "INSTRUMENT_ORDER_UNRESOLVED" not in mismatched_facts.order_cancel_blockers
    assert "remote_broker_order_front_mismatch:94" in mismatched_facts.order_cancel_blockers


def _build_source_backed_partial_close_with_working_close_order(
    *, remote_order_sys_id="native-cancel-19", remote_order_status="3"
):
    """Project a live owned CLOSE against a source-backed partial position."""

    _facts, live_inputs = _build_source_backed_dated_close_facts(partial_close=True)
    api = live_inputs["api"]
    broker = live_inputs["broker"]
    journal = live_inputs["journal"]
    target = live_inputs["target"]
    now = live_inputs["now"]
    order = SellOrder(
        owner=None,
        data=target.data,
        size=1,
        price=101,
        exectype=Order.Limit,
        simulated=True,
    )
    close_time = (now + timedelta(milliseconds=1)).isoformat().replace("+00:00", "Z")
    decision_key = ExecutionDecisionKey(
        account_scope="acct-scope",
        strategy_scope="alpha003",
        logical_run_id="run-1",
        cohort_id="partial-close-cancel",
        close_time=close_time,
        decision_kind="alpha003-rebalance",
    )
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="SELL",
        position_effect="CLOSE",
        leg=0,
    )
    decision = journal.record_decision(
        decision_key,
        {"batch_id": "partial-close-cancel-1", "mode": "native"},
        intent_keys=(intent_key,),
    )
    intent = journal.prepare_intent(
        decision.decision_id,
        intent_key,
        {
            "exchange": _EXCHANGE,
            "owner_intent_id": live_inputs["intent"].intent_id,
            "owner_position_effect": "OPEN",
            "owner_side": "BUY",
            "quantity": "1",
            "price": "101",
        },
        owner_intent_id=live_inputs["intent"].intent_id,
        original_identity={
            "backtrader_order_ref": order.ref,
            "operation": "insert",
            "instrument_id": _INSTRUMENT,
            "exchange_id": _EXCHANGE,
            "order_ref": "19",
            "order_sys_id": "native-cancel-19",
            "front_id": 4,
            "session_id": 7,
            "trading_day": _TRADING_DAY,
        },
    )
    assert journal.claim_dispatch(intent.intent_id) is not None
    journal.record_dispatch_result(
        intent.intent_id,
        state="KNOWN",
        provider_identity={"order_ref": "19", "order_sys_id": "native-cancel-19"},
        outcome_code="accepted",
    )

    order.status = Order.Accepted
    order.info.update(
        {
            "external_order_ref": "19",
            "order_sys_id": "native-cancel-19",
            "registered_sim_ctp_order_sys_id": "native-cancel-19",
            "registered_sim_ctp_order_sys_id_source": "ctp_order_callback",
            "_registered_sim_ctp_identity_binding_captured": True,
            "_registered_sim_ctp_identity_binding_valid": True,
            "factor_position_effect": "CLOSE",
            "factor_strategy_scope": "alpha003",
            "factor_intent_id": intent.intent_id,
            "front_id": 4,
            "session_id": 7,
            "execution_unknown": False,
            "cancel_requested_remote": False,
            "cancel_intent_active": False,
            "managed_execution_cancel_pending": False,
        }
    )
    broker.orders[order.ref] = order

    api.query_rows["orders_result"] = [
        {
            "OrderRef": "17",
            "OrderSysID": "native-17",
            "InstrumentID": _INSTRUMENT,
            "ExchangeID": _EXCHANGE,
            "OrderStatus": "0",
            "FrontID": 4,
            "SessionID": 7,
            "TradingDay": _TRADING_DAY,
        },
        {
            "OrderRef": "18",
            "OrderSysID": "native-18",
            "InstrumentID": _INSTRUMENT,
            "ExchangeID": _EXCHANGE,
            "OrderStatus": "0",
            "FrontID": 4,
            "SessionID": 7,
            "TradingDay": _TRADING_DAY,
        },
        {
            "OrderRef": "19",
            "OrderSysID": remote_order_sys_id,
            "InstrumentID": _INSTRUMENT,
            "ExchangeID": _EXCHANGE,
            "OrderStatus": remote_order_status,
            "Direction": "1",
            "CombOffsetFlag": "3",
            "VolumeTotal": "1",
            "FrontID": 4,
            "SessionID": 7,
            "TradingDay": _TRADING_DAY,
        },
    ]
    receipt, projection_now, _consumed = _refresh_complete_facts_after_callback(
        api,
        live_inputs["store"],
        target,
        sequence=11,
        trading_day=_TRADING_DAY,
    )
    facts = _project(
        live_inputs["store"],
        broker,
        target,
        projection_now,
        query_set=receipt.query_set,
    )
    live_inputs.update(
        {
            "active_close_intent": intent,
            "active_close_order": order,
            "now": projection_now,
            "query_set": receipt.query_set,
            "query_receipt": receipt,
        }
    )
    return facts, live_inputs


def test_order_cancel_ignores_only_dated_close_unavailable_for_exact_owned_close_join():
    facts, live_inputs = _build_source_backed_partial_close_with_working_close_order()
    try:
        assert len(facts.working_orders) == 1
        working = facts.working_orders[0]
        assert (working.side, working.position_effect, working.state) == (
            "SELL",
            "CLOSE",
            "ACCEPTED",
        )
        assert facts.positions[0].position_book_status == "UNKNOWN"
        assert facts.positions[0].position_book_blocker_code == "INSTRUMENT_ORDER_UNRESOLVED"
        leg = facts.dated_close_legs[0]
        unavailable = "dated_close_leg_unavailable:rb:LONG:1:TODAY"
        assert leg.ready is False
        assert "DATED_TARGET_HAS_WORKING_ORDER" in leg.blockers
        assert "DATED_GLOBAL_RISK_EVIDENCE_BLOCKED" in leg.blockers
        assert unavailable in facts.blockers
        assert "INSTRUMENT_ORDER_UNRESOLVED" in facts.blockers
        # Cancellation classification does not make the dated leg or global risk
        # projection ready for another close/open action.
        assert facts.risk_reduction_ready is False
        assert facts.order_cancel_blockers == ()
        assert facts.order_cancel_ready is True, facts.order_cancel_blockers
    finally:
        live_inputs["journal"].close()


@pytest.mark.parametrize("scenario", ("sysid_mismatch", "missing_join", "unknown_order"))
def test_order_cancel_keeps_dated_close_blocked_without_valid_owned_join(scenario):
    if scenario == "sysid_mismatch":
        facts, live_inputs = _build_source_backed_partial_close_with_working_close_order(
            remote_order_sys_id="different-native-id"
        )
        try:
            assert "remote_broker_order_sys_id_mismatch:19" in facts.order_cancel_blockers
            assert "dated_close_leg_unavailable:rb:LONG:1:TODAY" not in facts.order_cancel_blockers
            assert facts.order_cancel_ready is False
        finally:
            live_inputs["journal"].close()
        return

    status = "a" if scenario == "unknown_order" else "3"
    facts, live_inputs = _build_source_backed_partial_close_with_working_close_order(
        remote_order_status=status
    )
    try:
        if scenario == "missing_join":
            del live_inputs["broker"].orders[live_inputs["active_close_order"].ref]
            facts = _project(
                live_inputs["store"],
                live_inputs["broker"],
                live_inputs["target"],
                live_inputs["now"],
                query_set=live_inputs["query_set"],
            )
            assert "remote_working_order_missing_from_broker:19" in facts.order_cancel_blockers
        else:
            assert "remote_working_order_status_unknown:19" in facts.order_cancel_blockers
        assert "dated_close_leg_unavailable:rb:LONG:1:TODAY" in facts.order_cancel_blockers
        assert facts.order_cancel_ready is False
    finally:
        live_inputs["journal"].close()


def test_read_only_reconciliation_missing_account_with_dated_rows_fails_closed():
    facts, _live_inputs = _build_source_backed_dated_close_facts()
    incomplete = replace(facts, account=None)

    assert incomplete.read_only_reconciliation_ready is False
    assert "read_only_account_projection_unavailable" in (
        incomplete.read_only_reconciliation_blockers
    )


@pytest.mark.parametrize(
    "scenario,expected_prefix",
    (
        ("stale_query", "read_only_core_query_provenance_incomplete"),
        ("session_mismatch", "read_only_core_query_provenance_incomplete"),
        ("unknown_order", "read_only_unknown_orders_present_or_unobserved"),
        ("pending_order", "remote_working_order_missing_from_broker"),
        ("frozen", "read_only_route_frozen_or_unobserved"),
    ),
)
def test_read_only_reconciliation_rejects_stale_or_unresolved_source(scenario, expected_prefix):
    case = _build_source_backed_read_only_reconciliation_case(scenario=scenario)

    assert case.facts.read_only_reconciliation_ready is False
    assert any(
        blocker.startswith(expected_prefix)
        for blocker in case.facts.read_only_reconciliation_blockers
    ), case.facts.read_only_reconciliation_blockers


@pytest.mark.parametrize(
    "blocker",
    ("route_query_identity_mismatch:rb", "OPEN_INTENT_QUANTITY_EXCEEDED"),
)
def test_read_only_reconciliation_does_not_hide_query_or_unknown_blockers(blocker):
    facts = _build_source_backed_read_only_reconciliation_case().facts
    facts_with_blocker = replace(facts, blockers=facts.blockers + (blocker,))

    assert facts_with_blocker.read_only_reconciliation_ready is False
    assert blocker in facts_with_blocker.read_only_reconciliation_blockers


def test_missing_target_template_blocks_global_readiness_without_filtering_targets():
    now = datetime.now(timezone.utc)
    target_specs = (
        ("rb", "rb2510", "SHFE"),
        ("cu", "cu2510", "SHFE"),
        ("au", "au2512", "SHFE"),
    )
    missing = (target_specs[-1],)
    (
        _api,
        store,
        broker,
        _journal,
        _coordinator,
        targets,
        templates,
    ) = _multi_target_system_under_test(
        now=now,
        target_specs=target_specs,
        missing_template=missing,
    )
    receipt = refresh_factor_execution_queries(store, targets=targets, overall_timeout=4.0)
    assert receipt.blockers == ()
    for target in targets:
        assert store.poll_tick(target.instrument) is not None
    first = targets[0]
    store.registered_sim_arm(
        instrument=first.instrument,
        exchange=first.exchange,
        **templates[(first.instrument, first.exchange)],
    )

    facts = project_factor_execution_facts(
        store,
        broker,
        targets=targets,
        account_scope="acct-scope",
        strategy_scope="alpha003",
        now=now,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=10),
        query_set=receipt.query_set,
    )

    assert len(facts.positions) == len(facts.quotes) == len(facts.instruments) == 3
    assert len(facts.route_eligibilities) == 3
    assert facts.route_eligibilities[-1].arm_templates_configured is True
    assert facts.route_eligibilities[-1].arm_template_configured is None
    assert facts.route_eligibilities[-1].eligible is False
    assert "route_arm_template_missing:au" in facts.blockers


def test_sealed_empty_arm_template_map_does_not_fall_back_to_active_grant_mode():
    now = datetime.now(timezone.utc)
    _api, store, _broker, _journal, _coordinator, target = _system_under_test(now=now)
    store.registered_sim_configure_arm_templates({})
    receipt = _refresh_all(store, target)

    facts = project_factor_execution_facts(
        store,
        _broker,
        targets=(target,),
        account_scope="acct-scope",
        strategy_scope="alpha003",
        now=now,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=10),
        query_set=receipt.query_set,
    )

    route = facts.route_eligibilities[0]
    assert route.arm_templates_configured is True
    assert route.arm_template_configured is False
    assert route.eligible is False
    assert "route_arm_template_missing:rb" in facts.blockers
    assert facts.open_risk_ready is False


def test_history_inventory_keeps_current_position_separate_from_yd_baseline():
    now = datetime.now(timezone.utc)
    # CTP YdPosition is the prior-day baseline. A partial dated close may make
    # the current HISTORY Position smaller; the bridge must retain both values
    # and use only Position as the current bucket quantity.
    history_row = _dated_position_row(
        "1",
        position_date="HISTORY",
        today_position="0",
        yd_position="4",
    )
    api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(positions=(history_row,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    row = facts.positions[0].dated_inventory_rows[0]
    assert row.position_date_code == "2"
    assert row.position_date == "HISTORY"
    assert row.position == Decimal("1")
    assert row.today_position == Decimal("0")
    assert row.yd_position == Decimal("4")
    assert row.blockers == ()
    # Broker is flat in this fixture, so source inventory cannot be traded as
    # owned strategy exposure and the facts remain blocked.
    assert facts.risk_reduction_ready is False
    assert any("broker_ctp_position_side_mismatch" in item for item in facts.blockers)


@pytest.mark.parametrize(
    "mutation, expected_blocker",
    (
        ({"PositionDate": "9"}, "POSITION_DATE_UNSUPPORTED_OR_UNOBSERVED"),
        ({"TradingDay": "20261023"}, "POSITION_TRADING_DAY_MISSING_OR_MISMATCH"),
        ({"LongFrozen": "1"}, "POSITION_FREEZE_PRESENT"),
        ({"TodayPosition": "0"}, "TODAY_POSITION_CONTRADICTION"),
        ({"LongFrozenAmount": None}, "POSITION_FREEZE_FIELDS_UNOBSERVED"),
        ({"HedgeFlag": "9"}, "HEDGE_FLAG_UNSUPPORTED_OR_UNOBSERVED"),
    ),
)
def test_dated_inventory_projection_blocks_ambiguous_or_reserved_source_rows(
    mutation, expected_blocker
):
    now = datetime.now(timezone.utc)
    source_row = _dated_position_row("1")
    source_row.update(mutation)
    api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(positions=(source_row,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.positions
    assert not facts.risk_reduction_ready
    row = facts.positions[0].dated_inventory_rows[0]
    assert expected_blocker in row.blockers


def test_terminal_order_facts_are_bound_to_the_complete_orders_query_observation():
    now = datetime.now(timezone.utc)
    terminal = {
        "OrderRef": "17",
        "OrderSysID": "native-17",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "OrderStatus": "5",
        "FrontID": 2,
        "SessionID": 41,
        "VolumeTotalOriginal": 3,
        "VolumeTraded": 0,
        "VolumeTotal": 3,
    }
    _api, store, broker, _journal, coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(orders=(terminal,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    first = _project(store, broker, target, now, query_set=receipt.query_set)
    second = _project(store, broker, target, now, query_set=receipt.query_set)

    assert len(first.terminal_orders) == 1
    fact = first.terminal_orders[0]
    orders_query = next(item for item in first.query_provenance if item.family == "orders_result")
    assert fact.order_ref == "17"
    assert fact.order_sys_id == "native-17"
    assert fact.instrument == _INSTRUMENT
    assert fact.exchange == _EXCHANGE
    assert fact.terminal_status == "5"
    assert fact.terminal_state == "CANCELED"
    assert fact.evidence_kind == "complete_orders_query_observation"
    assert fact.snapshot_id == first.snapshot_id
    assert fact.request_id == orders_query.request_id
    assert fact.connection_generation == orders_query.connection_generation
    assert fact.account_fingerprint == orders_query.account_fingerprint
    assert fact.trading_day == orders_query.trading_day
    assert fact.available_at == orders_query.completed_at
    assert fact.front_id == 2
    assert fact.session_id == 41
    assert fact.volume_total_original == Decimal(3)
    assert fact.volume_traded == Decimal(0)
    assert fact.volume_total == Decimal(3)
    assert fact.observation_id.startswith("orders-query-row:")
    assert second.terminal_orders[0].observation_id == fact.observation_id
    assert not any(
        blocker.startswith("terminal_order_not_reconciled:") for blocker in first.blockers
    )

    # An unowned historical row is not silently adopted. The coordinator may
    # clear it only with positive same-route flatness after the orders query.
    proof = coordinator.terminal_order_reconciliation_snapshot(first)
    assert proof.items[0].status == "EXTERNAL_TERMINAL_FLAT"
    disposition = coordinator.reconcile_terminal_order_observations(first)
    assert disposition.items[0].status == "EXTERNAL_TERMINAL_FLAT", disposition.items[0]
    resolved = _project(store, broker, target, now, query_set=receipt.query_set)
    assert not any(
        blocker.startswith("terminal_order_not_reconciled:") for blocker in resolved.blockers
    )
    assert resolved.risk_reduction_ready is True, resolved.risk_reduction_blockers
    assert resolved.open_risk_ready is True, resolved.blockers


@pytest.mark.parametrize(
    "source_key,fact_name",
    (
        ("FrontID", "front_id"),
        ("SessionID", "session_id"),
        ("VolumeTotalOriginal", "volume_total_original"),
        ("VolumeTraded", "volume_traded"),
        ("VolumeTotal", "volume_total"),
    ),
)
def test_terminal_order_facts_preserve_missing_unknown_recovery_fields(source_key, fact_name):
    now = datetime.now(timezone.utc)
    terminal = {
        "OrderRef": "18",
        "OrderSysID": "native-18",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "OrderStatus": "5",
        "FrontID": 2,
        "SessionID": 42,
        "VolumeTotalOriginal": 4,
        "VolumeTraded": 0,
        "VolumeTotal": 4,
    }
    terminal.pop(source_key)
    _api, store, broker, _journal, coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(orders=(terminal,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert len(facts.terminal_orders) == 1
    fact = facts.terminal_orders[0]
    assert getattr(fact, fact_name) is None
    assert fact.front_id == (None if fact_name == "front_id" else 2)
    assert fact.session_id == (None if fact_name == "session_id" else 42)
    assert fact.volume_total_original == (
        None if fact_name == "volume_total_original" else Decimal(4)
    )
    assert fact.volume_traded == (None if fact_name == "volume_traded" else Decimal(0))
    assert fact.volume_total == (None if fact_name == "volume_total" else Decimal(4))
    # Missing recovery-only columns do not invalidate unrelated legacy
    # terminal history; the UNKNOWN recovery coordinator applies stricter
    # requirements only when this row matches an unresolved native intent.
    assert not any(
        blocker.startswith("terminal_order_not_reconciled:") for blocker in facts.blockers
    )
    assert coordinator.terminal_order_reconciliation_snapshot(facts).items[0].status == (
        "EXTERNAL_TERMINAL_FLAT"
    )


def test_trade_observation_preserves_query_and_native_fill_facts_without_fee_inference():
    now = datetime.now(timezone.utc)
    trade_at = now - timedelta(seconds=2)
    ctp_time = trade_at.astimezone(timezone(timedelta(hours=8)))
    trade = {
        "TradeID": "trade-23",
        "OrderRef": "23",
        "OrderSysID": "native-23",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "Direction": "0",
        "OffsetFlag": "0",
        "Volume": "0.5",
        "Price": "100.25",
        "TradeDate": ctp_time.strftime("%Y%m%d"),
        "TradeTime": ctp_time.strftime("%H:%M:%S.%f"),
    }
    _api, store, broker, _journal, coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(trades=(trade,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert len(facts.trade_observations) == 1
    observation = facts.trade_observations[0]
    trades_query = next(item for item in facts.query_provenance if item.family == "trades_result")
    assert observation.trade_id == "trade-23"
    assert observation.order_ref == "23"
    assert observation.order_sys_id == "native-23"
    assert observation.instrument == _INSTRUMENT
    assert observation.exchange == _EXCHANGE
    assert observation.direction == "0"
    assert observation.side == "BUY"
    assert observation.offset == "0"
    assert observation.position_effect == "OPEN"
    assert observation.volume == Decimal("0.5")
    assert observation.price == Decimal("100.25")
    assert observation.trade_time_utc == trade_at
    assert observation.fee is None
    assert observation.evidence_kind == "complete_trades_query_observation"
    assert observation.snapshot_id == facts.snapshot_id
    assert observation.request_id == trades_query.request_id
    assert observation.connection_generation == trades_query.connection_generation
    assert observation.available_at == trades_query.completed_at
    assert observation.observation_id.startswith("trades-query-row:")
    disposition = coordinator.trade_reconciliation_snapshot(facts)
    assert disposition.items[0].status == "EXTERNAL_FLAT", disposition.items[0]
    assert not any(
        blocker.startswith("trade_observation_not_reconciled:") for blocker in facts.blockers
    )
    assert facts.risk_reduction_ready is True, facts.risk_reduction_blockers
    assert facts.open_risk_ready is True
    assert "ctp_unmatched_trade_rows_present:1" in facts.diagnostics
    assert not any("ctp_unmatched_trade" in blocker for blocker in facts.blockers)


def test_unowned_trade_is_not_external_flat_while_route_has_working_order():
    now = datetime.now(timezone.utc)
    ctp_time = (now - timedelta(seconds=2)).astimezone(timezone(timedelta(hours=8)))
    trade = {
        "TradeID": "unowned-trade-1",
        "OrderRef": "25",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "Direction": "0",
        "OffsetFlag": "0",
        "Volume": "1",
        "Price": "100",
        "TradeDate": ctp_time.strftime("%Y%m%d"),
        "TradeTime": ctp_time.strftime("%H:%M:%S.%f"),
    }
    working_order = {
        "OrderRef": "26",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "OrderStatus": "3",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotal": "1",
    }
    _api, store, broker, _journal, coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(trades=(trade,), orders=(working_order,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)
    disposition = coordinator.trade_reconciliation_snapshot(facts)

    assert disposition.items[0].status == "BLOCKED"
    assert disposition.items[0].blocker_code == "UNMATCHED_TRADE_POSITION_OR_ORDER_UNRESOLVED"
    assert facts.risk_reduction_ready is False


def test_store_unmatched_trade_count_must_match_the_complete_query_rows():
    now = datetime.now(timezone.utc)
    ctp_time = (now - timedelta(seconds=2)).astimezone(timezone(timedelta(hours=8)))
    trade = {
        "TradeID": "unmatched-count-trade",
        "OrderRef": "27",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "Direction": "0",
        "OffsetFlag": "0",
        "Volume": "1",
        "Price": "100",
        "TradeDate": ctp_time.strftime("%Y%m%d"),
        "TradeTime": ctp_time.strftime("%H:%M:%S.%f"),
    }
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(trades=(trade,)),
    )
    store.get_ctp_query_health = lambda: {
        "evidence_complete": True,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
    }
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert "ctp_unmatched_trade_count_mismatch" in facts.blockers
    assert facts.risk_reduction_ready is False
    assert facts.open_risk_ready is False


def test_duplicate_trade_ids_and_unparseable_trade_time_block_query_fill_projection():
    now = datetime.now(timezone.utc)
    duplicate = {
        "TradeID": "duplicate-trade",
        "OrderRef": "24",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "Direction": "0",
        "OffsetFlag": "0",
        "Volume": "1",
        "Price": "100",
        "TradeDate": "20261024",
        "TradeTime": "10:00:00",
    }
    invalid = dict(duplicate, TradeID="invalid-time", TradeTime="not-a-time")
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(trades=(duplicate, dict(duplicate), invalid)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.trade_observations == ()
    assert "remote_trade_fields_unobserved:invalid-time" in facts.blockers
    assert "remote_trade_id_duplicate:duplicate-trade" in facts.blockers


def test_duplicate_terminal_native_order_identity_is_not_selected_as_evidence():
    now = datetime.now(timezone.utc)
    first = {
        "OrderRef": "18",
        "OrderSysID": "native-18a",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "OrderStatus": "5",
    }
    second = dict(first, OrderSysID="native-18b")
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(orders=(first, second)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.terminal_orders == ()
    assert "remote_terminal_order_identity_duplicate:18:rb2510:SHFE" in facts.blockers


def test_projection_is_no_io_and_incremental_refresh_respects_limits():
    now = datetime.now(timezone.utc)
    api, store, broker, _journal, _coordinator, target = _system_under_test(now=now)
    core = refresh_factor_execution_queries(
        store, targets=(target,), overall_timeout=4.0, max_queries=5
    )
    assert len(core.attempted_families) == 5
    assert core.pending_families == ("instrument_margin_rate_result:rb",)

    margin = refresh_factor_execution_queries(
        store,
        targets=(target,),
        include_core=False,
        margin_target_ids=("rb",),
        max_queries=1,
        overall_timeout=4.0,
    )
    assert margin.attempted_families == ("instrument_margin_rate_result:rb",)
    assert margin.pending_families == ()
    calls_before_projection = tuple(api.query_calls)

    facts = _project(store, broker, target, now, query_set=core.query_set)

    assert tuple(api.query_calls) == calls_before_projection
    assert facts.available_at == max(
        fact.completed_at
        for fact in facts.query_provenance
        if fact.family
        in {
            "account_result",
            "positions_result",
            "orders_result",
            "trades_result",
            "instruments_result",
        }
    )


def test_partial_core_refresh_cannot_splice_into_a_previously_complete_query_set():
    now = datetime.now(timezone.utc)
    _api, store, broker, _journal, _coordinator, target = _system_under_test(now=now)
    complete = _refresh_all(store, target)
    assert complete.query_set is not None

    partial = refresh_factor_execution_queries(
        store,
        targets=(target,),
        overall_timeout=4.0,
        include_core=True,
        margin_target_ids=(),
        max_queries=1,
    )
    assert partial.query_set is None
    assert partial.attempted_families == ("account_result",)
    assert partial.pending_families
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=complete.query_set)

    assert facts.snapshot_id is None
    assert facts.account is None
    assert "completed_query_set_receipt_mismatch" in facts.blockers


def test_target_capacity_is_finite_and_supports_large_configured_pools():
    now = datetime.now(timezone.utc)
    _api, store, _broker, _journal, _coordinator, _target = _system_under_test(now=now)

    def make_targets(count):
        return tuple(
            FactorExecutionTarget(
                "target-{}".format(index),
                "rb{:04d}".format(index),
                _EXCHANGE,
                SimpleNamespace(_name="rb{:04d}".format(index)),
            )
            for index in range(count)
        )

    receipt = refresh_factor_execution_queries(
        store,
        targets=make_targets(256),
        overall_timeout=4.0,
        max_queries=1,
    )
    assert receipt.attempted_families == ("account_result",)
    assert receipt.pending_families
    assert receipt.deadline_reached is False

    with pytest.raises(ValueError, match="bounded refresh limit"):
        refresh_factor_execution_queries(
            store,
            targets=make_targets(257),
            overall_timeout=4.0,
            max_queries=1,
        )


def test_decision_clock_does_not_advance_to_a_future_consumed_quote():
    wall_now = datetime.now(timezone.utc)
    decision_now = wall_now - timedelta(seconds=1)
    quote_event = decision_now + timedelta(milliseconds=100)
    quote_received = decision_now + timedelta(milliseconds=200)
    api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=decision_now - timedelta(milliseconds=100),
        tick=_quote(event_time=quote_event, received_at=quote_received),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, decision_now, query_set=receipt.query_set)

    assert quote_received < wall_now
    assert "consumed_quote_from_future:rb" in facts.blockers
    assert facts.quotes[0].quality != "GOOD"
    assert facts.risk_reduction_ready is False
    assert facts.open_risk_ready is False
    assert api.query_calls  # only the explicit refresh above queried


def test_quote_source_is_bound_to_registered_store_not_tick_or_provenance_mapping():
    now = datetime.now(timezone.utc)
    tick = _quote(event_time=now - timedelta(milliseconds=200))
    tick.source = "different-registered-source"
    api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        tick=tick,
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    raw_tick = api.tick
    consumed = _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert raw_tick.source == "different-registered-source"
    assert consumed.source == store.registered_sim_tick_source
    assert store.registered_sim_tick_source == _REGISTERED_TICK_SOURCE
    assert api.live_tick_provenance["source"] == _UNTRUSTED_TICK_SOURCE
    assert facts.quotes[0].source == store.registered_sim_tick_source
    assert facts.quotes[0].quality == "GOOD"


def test_quote_registered_source_mismatch_from_consumed_snapshot_is_blocked():
    now = datetime.now(timezone.utc)
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        store_cls=_MismatchedConsumedSourceStore,
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.quotes[0].quality == "SOURCE_MISMATCH"
    assert "consumed_quote_registered_source_mismatch:rb" in facts.blockers
    assert facts.risk_reduction_ready is False


def test_quote_with_missing_registered_source_does_not_fall_back_to_matching_tick_or_mapping():
    now = datetime.now(timezone.utc)
    api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        store_cls=_MissingRegisteredTickSourceStore,
        provenance_source=_REGISTERED_TICK_SOURCE,
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert api.live_tick_provenance["source"] == facts.quotes[0].source
    assert facts.quotes[0].quality == "PROVENANCE_UNOBSERVED"
    assert "consumed_quote_registered_source_unobserved:rb" in facts.blockers
    assert facts.risk_reduction_ready is False


@pytest.mark.parametrize("registered_source", ["", " ", 7])
def test_quote_with_invalid_registered_source_stays_quality_blocked(registered_source):
    now = datetime.now(timezone.utc)
    invalid_store = type(
        "_InvalidRegisteredTickSourceStore",
        (RegisteredSimStore,),
        {"registered_sim_tick_source": registered_source},
    )
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        store_cls=invalid_store,
        provenance_source=_REGISTERED_TICK_SOURCE,
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.quotes[0].quality == "PROVENANCE_INVALID"
    assert "consumed_quote_registered_source_invalid:rb" in facts.blockers
    assert facts.risk_reduction_ready is False


def test_quote_trading_day_must_match_the_complete_query_set():
    now = datetime.now(timezone.utc)
    tick = _quote(event_time=now - timedelta(milliseconds=200))
    tick.trading_day = "20261023"
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        tick=tick,
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.quotes[0].trading_day == "20261023"
    assert "consumed_quote_trading_day_mismatch:rb" in facts.blockers
    assert facts.quotes[0].quality == "TRADING_DAY_MISMATCH"
    assert facts.risk_reduction_ready is False


def test_quote_outside_independent_freshness_limit_is_stale():
    now = datetime.now(timezone.utc)
    tick = _quote(
        event_time=now - timedelta(seconds=4),
        received_at=now - timedelta(seconds=3, milliseconds=900),
    )
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        tick=tick,
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert "consumed_quote_stale:rb" in facts.blockers
    assert facts.quotes[0].quality == "STALE"
    assert facts.risk_reduction_ready is False


@pytest.mark.parametrize("row_trading_day", [None, "20261023"])
def test_trade_query_row_trading_day_is_checked_separately_from_trade_date(row_trading_day):
    now = datetime.now(timezone.utc)
    ctp_time = (now - timedelta(seconds=2)).astimezone(timezone(timedelta(hours=8)))
    trade = {
        "TradeID": "wrong-day-trade",
        "OrderRef": "91",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "Direction": "0",
        "OffsetFlag": "0",
        "Volume": "1",
        "Price": "100",
        "TradeDate": "20261023",
        "TradingDay": row_trading_day,
        "TradeTime": ctp_time.strftime("%H:%M:%S.%f"),
    }
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(trades=(trade,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.trade_observations == ()
    assert "remote_trade_trading_day_mismatch:wrong-day-trade" in facts.blockers


def test_night_session_trade_date_may_precede_its_trading_day():
    now = datetime.now(timezone.utc)
    ctp_time = (now - timedelta(seconds=2)).astimezone(timezone(timedelta(hours=8)))
    trade = {
        "TradeID": "night-trade",
        "OrderRef": "91",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "Direction": "0",
        "OffsetFlag": "0",
        "Volume": "1",
        "Price": "100",
        "TradeDate": "20261023",
        "TradingDay": _TRADING_DAY,
        "TradeTime": ctp_time.strftime("%H:%M:%S.%f"),
    }
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(trades=(trade,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert len(facts.trade_observations) == 1
    assert facts.trade_observations[0].trade_date == "20261023"
    assert facts.trade_observations[0].trading_day == _TRADING_DAY
    assert "remote_trade_trading_day_mismatch:night-trade" not in facts.blockers


@pytest.mark.parametrize("row_trading_day", [None, "20261023"])
def test_terminal_order_query_row_trading_day_mismatch_is_rejected(row_trading_day):
    now = datetime.now(timezone.utc)
    terminal = {
        "OrderRef": "92",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "OrderStatus": "5",
        "TradingDay": row_trading_day,
    }
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(orders=(terminal,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.terminal_orders == ()
    assert "remote_terminal_order_trading_day_mismatch:92" in facts.blockers


@pytest.mark.parametrize(
    "missing_from,field,expected_prefix",
    (
        ("broker", "front_id", "broker_order_front_unobserved"),
        ("broker", "session_id", "broker_order_session_unobserved"),
        ("remote", "FrontID", "remote_broker_order_front_unobserved"),
        ("remote", "SessionID", "remote_broker_order_session_unobserved"),
    ),
)
def test_active_order_missing_front_or_session_identity_cannot_join_to_broker(
    missing_from, field, expected_prefix
):
    now = datetime.now(timezone.utc)
    remote = {
        "OrderRef": "93",
        "OrderSysID": "sys-93",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "OrderStatus": "3",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotal": "1",
        "FrontID": 4,
        "SessionID": 7,
    }
    if missing_from == "remote":
        remote.pop(field)
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(orders=(remote,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    order = BuyOrder(
        owner=None,
        data=target.data,
        size=1,
        price=100,
        exectype=Order.Limit,
        simulated=True,
    )
    order.status = Order.Accepted
    local_info = {
        "external_order_ref": "93",
        "order_sys_id": "sys-93",
        "factor_position_effect": "OPEN",
        "factor_strategy_scope": "alpha003",
        "factor_intent_id": "intent-93",
        "front_id": 4,
        "session_id": 7,
        "execution_unknown": False,
        "cancel_requested_remote": False,
        "cancel_intent_active": False,
        "managed_execution_cancel_pending": False,
    }
    if missing_from == "broker":
        local_info.pop(field)
    order.info.update(local_info)
    broker.orders[order.ref] = order

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    blocker_suffix = order.ref if missing_from == "broker" else "93"
    assert "{}:{}".format(expected_prefix, blocker_suffix) in facts.blockers
    assert facts.order_cancel_ready is False


def test_order_cancel_readiness_does_not_depend_on_a_market_quote():
    now = datetime.now(timezone.utc)
    remote = {
        "OrderRef": "94",
        "OrderSysID": "sys-94",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "OrderStatus": "3",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotal": "1",
        "FrontID": 4,
        "SessionID": 7,
    }
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=_query_rows(orders=(remote,)),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    order = BuyOrder(
        owner=None,
        data=target.data,
        size=1,
        price=100,
        exectype=Order.Limit,
        simulated=True,
    )
    order.status = Order.Accepted
    order.info.update(
        {
            "external_order_ref": "94",
            "order_sys_id": "sys-94",
            "factor_position_effect": "OPEN",
            "factor_strategy_scope": "alpha003",
            "factor_intent_id": "intent-94",
            "front_id": 4,
            "session_id": 7,
            "execution_unknown": False,
            "cancel_requested_remote": False,
            "cancel_intent_active": False,
            "managed_execution_cancel_pending": False,
        }
    )
    broker.orders[order.ref] = order
    store._latest_ticks.clear()

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.risk_reduction_ready is False
    assert "consumed_quote_unavailable:rb" in facts.blockers
    assert facts.order_cancel_ready is True, facts.order_cancel_blockers


def test_future_query_completion_stays_blocked_against_injected_decision_clock():
    wall_now = datetime.now(timezone.utc)
    query_time = wall_now - timedelta(milliseconds=100)
    api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=query_time,
        query_time=query_time,
        tick=_quote(event_time=query_time - timedelta(milliseconds=20)),
    )
    receipt = _refresh_all(store, target)
    decision_now = query_time - timedelta(seconds=1)
    calls_before_projection = tuple(api.query_calls)

    facts = _project(store, broker, target, decision_now, query_set=receipt.query_set)

    assert facts.snapshot_id is None
    assert facts.account is None
    assert "query_snapshot_invalid_or_stale:account_result" in facts.blockers
    assert tuple(api.query_calls) == calls_before_projection


def test_old_consumed_quote_is_blocked_after_current_store_stream_gap():
    now = datetime.now(timezone.utc)
    _api, store, broker, _journal, _coordinator, target = _system_under_test(now=now)
    receipt = _refresh_all(store, target)
    _arm(store)
    old_tick = _consume_quote(store)
    assert old_tick is not None

    later_event = _quote(event_time=now - timedelta(milliseconds=50), sequence=2)
    later_event.event_id = "dropped-tick-2"
    store.mark_feed_dropped(later_event, "fixture_gap")
    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.quotes[0].source_ref == old_tick.event_id
    assert facts.quotes[0].quality == "STREAM_NOT_READY"
    assert "consumed_stream_not_currently_ready:rb" in facts.blockers
    assert facts.risk_reduction_ready is False


def test_quote_older_than_the_complete_risk_snapshot_is_not_reused():
    now = datetime.now(timezone.utc)
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        query_time=now - timedelta(milliseconds=500),
        tick=_quote(
            event_time=now - timedelta(seconds=2),
            received_at=now - timedelta(seconds=1, milliseconds=500),
        ),
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert "consumed_quote_before_risk_snapshot:rb" in facts.blockers
    assert facts.quotes[0].quality == "OLDER_THAN_RISK_SNAPSHOT"
    assert facts.risk_reduction_ready is False
    assert facts.open_risk_ready is False


def test_missing_capital_facts_do_not_become_zero_or_block_safe_reduction():
    now = datetime.now(timezone.utc)
    rows = _query_rows(account={"Balance": "100000", "CurrMargin": "0"}, include_margin=False)
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=rows,
    )
    receipt = refresh_factor_execution_queries(
        store,
        targets=(target,),
        overall_timeout=4.0,
        include_core=True,
        margin_target_ids=(),
    )
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.account is not None
    assert facts.account.available_margin is None
    assert facts.account.used_margin == Decimal(0)
    assert facts.instruments[0].long_margin_per_hand is None
    assert facts.instruments[0].short_margin_per_hand is None
    assert facts.risk_reduction_ready is True, facts.blockers
    assert facts.open_risk_ready is False
    assert "available_margin_unobserved" in facts.blockers


def _build_source_backed_dated_close_facts(
    missing_fact=None,
    *,
    position_date="TODAY",
    partial_close=False,
    journal_path=":memory:",
    native_callback_mode=None,
    monkeypatch=None,
):
    """Run real Store/Broker/Coordinator/Book reads and return immutable facts.

    The provider query and tick leaves are deterministic fakes; this helper
    deliberately exercises the production Store cache, Broker projection,
    journal reconciliation and position-book path. Strategy tests may consume
    its result instead of manufacturing a ``ready=True`` DTO.
    """
    if position_date not in {"TODAY", "HISTORY"}:
        raise ValueError("unsupported fixture position_date")
    if partial_close and position_date != "TODAY":
        raise ValueError("partial-close fixture requires the current trading day")
    opening_quantity = Decimal("2") if partial_close else Decimal("1")
    now = datetime.now(timezone.utc)
    close_time = (now - timedelta(seconds=5)).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    position_row = _dated_position_row(opening_quantity)
    account = {"Balance": "100000", "CurrMargin": "0"} if missing_fact == "capital" else None
    rows = _query_rows(
        positions=(position_row,),
        account=account,
        include_margin=missing_fact != "capital",
    )
    api, store, broker, journal, coordinator, target = _system_under_test(
        now=now, rows=rows, journal_path=journal_path
    )
    decision_key = ExecutionDecisionKey(
        account_scope="acct-scope",
        strategy_scope="alpha003",
        logical_run_id="run-1",
        cohort_id="rb-cohort",
        close_time=close_time,
        decision_kind="alpha003-rebalance",
    )
    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    decision = journal.record_decision(
        decision_key,
        {"batch_id": "batch-1", "mode": "native", "risk_policy_id": "a003-risk-v1"},
        intent_keys=(intent_key,),
    )
    economics = {
        "exchange": _EXCHANGE,
        "risk_policy_id": "a003-risk-v1",
        "batch_id": "batch-1",
        "quantity": str(opening_quantity),
        "price": "100",
    }
    if missing_fact != "stop_price":
        economics["factor_stop_price"] = "95"
    if missing_fact != "risk_policy":
        economics["risk_policy"] = {"stop_loss_ticks": 5, "max_loss_per_position": "25"}
    intent = journal.prepare_intent(
        decision.decision_id,
        intent_key,
        economics,
        original_identity={
            "backtrader_order_ref": 17,
            "operation": "insert",
            "instrument_id": _INSTRUMENT,
            "exchange_id": _EXCHANGE,
            "order_ref": "17",
            "order_sys_id": "native-17",
            "front_id": 4,
            "session_id": 7,
            "account_fingerprint": _ACCOUNT,
            "trading_day": _TRADING_DAY,
        },
    )
    assert journal.claim_dispatch(intent.intent_id) is not None
    journal.record_dispatch_result(
        intent.intent_id,
        state="KNOWN",
        provider_identity={"order_ref": "17", "order_sys_id": "native-17"},
        outcome_code="accepted",
    )
    # Store and Broker are real; seed only the Broker's ordinary cached
    # position projection that a native trade callback would have produced.
    broker.positions[_INSTRUMENT].update(int(opening_quantity), 100.0)

    # A complete orders/positions set after the durable fill receipt lets the
    # real coordinator release the pending-order owner. The test first queries
    # the trade, persists its receipt, then refreshes the full set before this
    # terminal reconciliation.
    terminal_row = {
        "OrderRef": "17",
        "OrderSysID": "native-17",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "OrderStatus": "0",
        "FrontID": 4,
        "SessionID": 7,
        "TradingDay": _TRADING_DAY,
    }
    api.query_rows["orders_result"] = [terminal_row]
    fill_time = now - timedelta(seconds=2)
    open_trade_row = _query_trade_for_fill(
        trade_id="trade-open-1",
        order_ref="17",
        order_sys_id="native-17",
        filled_at=fill_time,
        quantity=str(opening_quantity),
        price="100",
    )
    assert open_trade_row["TradingDay"] == _TRADING_DAY
    native_receipt = None
    if native_callback_mode is not None:
        if native_callback_mode not in {
            "acknowledged",
            "unacknowledged_restart",
            "unacknowledged_same_process",
        }:
            raise ValueError("unsupported native callback fixture mode")
        if native_callback_mode != "acknowledged":
            if monkeypatch is None:
                raise ValueError("unacknowledged native callback fixture requires monkeypatch")
            monkeypatch.setattr(
                execution_decision_journal_module,
                "_current_process_instance_id",
                lambda: "native-process",
            )
        native_order = SimpleNamespace(
            info={
                "factor_intent_id": intent.intent_id,
                "factor_strategy_scope": "alpha003",
                "external_order_ref": "17",
                "instrument_id": _INSTRUMENT,
                "exchange_id": _EXCHANGE,
                "factor_position_effect": "OPEN",
            },
            isbuy=lambda: True,
            addinfo=lambda **_values: None,
        )
        native_update = {
            "trade_id": open_trade_row["TradeID"],
            "order_ref": open_trade_row["OrderRef"],
            "instrument": open_trade_row["InstrumentID"],
            "exchange_id": open_trade_row["ExchangeID"],
            "size": opening_quantity,
            "price": open_trade_row["Price"],
            "details": {
                "TradeID": open_trade_row["TradeID"],
                "OrderRef": open_trade_row["OrderRef"],
                "OrderSysID": open_trade_row["OrderSysID"],
                "InstrumentID": open_trade_row["InstrumentID"],
                "ExchangeID": open_trade_row["ExchangeID"],
                "Volume": open_trade_row["Volume"],
                "Price": open_trade_row["Price"],
                "TradeDate": open_trade_row["TradeDate"],
                "TradeTime": open_trade_row["TradeTime"],
            },
        }
        native_receipt, native_projection, native_acknowledged = coordinator.record_trade_callback(
            native_update, native_order
        )
        assert native_projection.status in ("APPLIED", "DUPLICATE")
        assert native_acknowledged is False
        if native_callback_mode == "acknowledged":
            journal.acknowledge_callback(native_receipt.receipt_id)
        elif native_callback_mode == "unacknowledged_restart":
            monkeypatch.setattr(
                execution_decision_journal_module,
                "_current_process_instance_id",
                lambda: "query-process",
            )
        native_receipt = journal.callback_receipt(
            intent.intent_id,
            "ctp-trade:"
            + sha256(_execution_id_from_trade_row(open_trade_row).encode()).hexdigest(),
        )
    api.query_rows["trades_result"] = [open_trade_row]
    query_time = datetime.now(timezone.utc) - timedelta(milliseconds=100)
    api.query_time = query_time
    api.tick = _quote(
        event_time=query_time,
        received_at=query_time + timedelta(milliseconds=1),
        sequence=7,
    )
    if native_callback_mode in {
        "unacknowledged_restart",
        "unacknowledged_same_process",
    }:
        # The restart-disposition proof binds a real query started after the
        # native receipt. Use the fake provider's observed clock for these
        # cases instead of the ordinary planned timestamp, which intentionally
        # predates the actual refresh call.
        api._use_observed_query_clock = True
    receipt = _refresh_all(store, target)
    if native_callback_mode in {
        "unacknowledged_restart",
        "unacknowledged_same_process",
    }:
        query_time = receipt.query_set.completed_at_utc
        api.tick = _quote(
            event_time=query_time,
            received_at=datetime.now(timezone.utc),
            sequence=7,
        )
    _arm(store)
    consumed = _consume_quote(store)
    assert consumed is not None
    projection_now = datetime.now(timezone.utc)
    assert receipt.query_set.completed_at_utc <= projection_now
    assert consumed.received_wall_time <= projection_now.timestamp()
    facts = _project(store, broker, target, projection_now, query_set=receipt.query_set)
    assert (
        facts.account_scope == coordinator.account_scope
        and facts.strategy_scope == coordinator.strategy_scope
        and facts.snapshot_id is not None
        and facts.available_at is not None
        and facts.account is not None
        and facts.account.snapshot_id == facts.snapshot_id
    ), (
        facts.account_scope,
        coordinator.account_scope,
        facts.strategy_scope,
        coordinator.strategy_scope,
        facts.snapshot_id,
        facts.available_at,
        facts.account,
        facts.blockers,
    )
    trade_page = coordinator.reconcile_trade_observations(
        facts,
        refresh_receipt=receipt,
        limit=128,
    )
    assert trade_page.observation_count == 1
    assert trade_page.truncated is False
    if native_callback_mode == "unacknowledged_same_process":
        assert trade_page.items[0].status == "DUPLICATE", trade_page.items[0]
        assert trade_page.items[0].blocker_code == "CALLBACK_QUERY_RESTART_NOT_PROVEN"
        # Without a durable query disposition, the native callback remains
        # pending delivery and the Book must fail closed on that state.
        dated_page = coordinator.position_book.reconcile_dated_trade_observations(
            facts,
            reconciliation_page=trade_page,
            limit=128,
        )
        assert dated_page.items[0].status == "BLOCKED", dated_page.items[0]
        assert dated_page.items[0].blocker_code == "DATED_TRADE_NATIVE_ACK_STATE_MISMATCH"
        return facts, {
            "api": api,
            "store": store,
            "broker": broker,
            "journal": journal,
            "coordinator": coordinator,
            "target": target,
            "intent": intent,
            "native_receipt": native_receipt,
            "trade_page": trade_page,
            "dated_page": dated_page,
            "opening_execution_id": _execution_id_from_trade_row(open_trade_row),
        }
    assert trade_page.items[0].status == (
        "DUPLICATE" if native_callback_mode is not None else "APPLIED"
    ), trade_page.items[0]
    dated_page = coordinator.position_book.reconcile_dated_trade_observations(
        facts,
        reconciliation_page=trade_page,
        limit=128,
    )
    assert dated_page.observation_count == 1
    assert dated_page.truncated is False
    assert dated_page.items[0].status == "APPLIED", dated_page.items[0]
    dated_source_facts = facts
    dated_source_trade_page = trade_page
    # The trade receipt above updates the durable position book after the
    # source snapshot. Read a new complete core set before treating those
    # positions as current or reconciling a terminal order.
    receipt, projection_now, _consumed = _refresh_complete_facts_after_callback(
        api,
        store,
        target,
        sequence=8,
        trading_day=_TRADING_DAY,
    )
    facts = _project(store, broker, target, projection_now, query_set=receipt.query_set)
    trade_page = coordinator.reconcile_trade_observations(
        facts,
        refresh_receipt=receipt,
        limit=128,
    )
    assert trade_page.observation_count == 1
    assert trade_page.truncated is False
    assert trade_page.items[0].status == "DUPLICATE", trade_page.items[0]
    dated_page = coordinator.position_book.reconcile_dated_trade_observations(
        facts,
        reconciliation_page=trade_page,
        limit=128,
    )
    assert dated_page.observation_count == 1
    assert dated_page.truncated is False
    assert dated_page.items[0].status == "DUPLICATE", dated_page.items[0]
    facts = _project(store, broker, target, projection_now, query_set=receipt.query_set)
    terminal_page = coordinator.reconcile_terminal_order_observations(facts, limit=128)
    assert terminal_page.observation_count == 1
    assert terminal_page.truncated is False
    assert terminal_page.items[0].status == "RESOLVED", terminal_page.items[0]
    facts = _project(store, broker, target, projection_now, query_set=receipt.query_set)

    if partial_close:
        # Persist a source-backed CLOSE fill against the exact OPEN owner, then
        # reconcile a strictly later complete position query. The Book must
        # retain the original lot and expose only the one-hand remainder.
        close_decision_time = max(
            fill_time + timedelta(milliseconds=1),
            projection_now - timedelta(seconds=1),
        )
        close_time = close_decision_time.isoformat().replace("+00:00", "Z")
        close_decision_key = ExecutionDecisionKey(
            account_scope="acct-scope",
            strategy_scope="alpha003",
            logical_run_id="run-1",
            cohort_id="rb-cohort",
            close_time=close_time,
            decision_kind="alpha003-rebalance",
        )
        close_intent_key = ExecutionIntentKey(
            action="SUBMIT",
            instrument=_INSTRUMENT,
            side="SELL",
            position_effect="CLOSE",
            leg=0,
        )
        close_decision = journal.record_decision(
            close_decision_key,
            {"batch_id": "batch-close-1", "mode": "native"},
            intent_keys=(close_intent_key,),
        )
        close_intent = journal.prepare_intent(
            close_decision.decision_id,
            close_intent_key,
            {
                "exchange": _EXCHANGE,
                "owner_intent_id": intent.intent_id,
                "owner_position_effect": "OPEN",
                "owner_side": "BUY",
                "quantity": "1",
                "price": "101",
            },
            owner_intent_id=intent.intent_id,
            original_identity={
                "backtrader_order_ref": 18,
                "operation": "insert",
                "instrument_id": _INSTRUMENT,
                "exchange_id": _EXCHANGE,
                "order_ref": "18",
                "order_sys_id": "native-18",
                "trading_day": _TRADING_DAY,
            },
        )
        assert journal.claim_dispatch(close_intent.intent_id) is not None
        journal.record_dispatch_result(
            close_intent.intent_id,
            state="KNOWN",
            provider_identity={"order_ref": "18", "order_sys_id": "native-18"},
            outcome_code="accepted",
        )
        api.query_rows["positions_result"] = [_dated_position_row("1")]
        api.query_rows["orders_result"] = [
            terminal_row,
            {
                "OrderRef": "18",
                "OrderSysID": "native-18",
                "InstrumentID": _INSTRUMENT,
                "ExchangeID": _EXCHANGE,
                "OrderStatus": "0",
                "TradingDay": _TRADING_DAY,
            },
        ]
        close_trade_time = max(
            close_decision_time + timedelta(milliseconds=1),
            datetime.now(timezone.utc) - timedelta(milliseconds=500),
        )
        close_trade_row = _query_trade_for_fill(
            trade_id="trade-close-1",
            order_ref="18",
            order_sys_id="native-18",
            filled_at=close_trade_time,
            quantity="-1",
            price="101",
            offset_flag="3",
        )
        api.query_rows["trades_result"] = [open_trade_row, close_trade_row]
        broker.positions[_INSTRUMENT].update(-1, 101.0)
        close_query_time = datetime.now(timezone.utc) - timedelta(milliseconds=100)
        api.query_time = close_query_time
        api.tick = _quote(
            event_time=close_query_time,
            received_at=close_query_time + timedelta(milliseconds=1),
            sequence=9,
        )
        close_receipt = _refresh_all(store, target)
        assert _consume_quote(store) is not None
        projection_now = datetime.now(timezone.utc)
        assert close_receipt.query_set.completed_at_utc <= projection_now
        facts = _project(
            store,
            broker,
            target,
            projection_now,
            query_set=close_receipt.query_set,
        )
        trade_page = coordinator.reconcile_trade_observations(
            facts,
            refresh_receipt=close_receipt,
            limit=128,
        )
        assert trade_page.observation_count == 2
        assert trade_page.truncated is False
        assert {item.status for item in trade_page.items} == {"APPLIED", "DUPLICATE"}
        dated_page = coordinator.position_book.reconcile_dated_trade_observations(
            facts,
            reconciliation_page=trade_page,
            limit=128,
        )
        assert dated_page.observation_count == 2
        assert dated_page.truncated is False
        assert {item.status for item in dated_page.items} == {"APPLIED", "DUPLICATE"}
        facts = _project(
            store,
            broker,
            target,
            projection_now,
            query_set=close_receipt.query_set,
        )
        # The CLOSE fill receipt is newer than this set, so refresh all core
        # query families before terminal/current-position reconciliation.
        close_receipt, projection_now, _consumed = _refresh_complete_facts_after_callback(
            api,
            store,
            target,
            sequence=10,
            trading_day=_TRADING_DAY,
        )
        facts = _project(
            store,
            broker,
            target,
            projection_now,
            query_set=close_receipt.query_set,
        )
        trade_page = coordinator.reconcile_trade_observations(
            facts,
            refresh_receipt=close_receipt,
            limit=128,
        )
        assert trade_page.observation_count == 2
        assert trade_page.truncated is False
        assert {item.status for item in trade_page.items} == {"DUPLICATE"}
        dated_page = coordinator.position_book.reconcile_dated_trade_observations(
            facts,
            reconciliation_page=trade_page,
            limit=128,
        )
        assert dated_page.observation_count == 2
        assert dated_page.truncated is False
        assert {item.status for item in dated_page.items} == {"DUPLICATE"}
        facts = _project(
            store,
            broker,
            target,
            projection_now,
            query_set=close_receipt.query_set,
        )
        terminal_page = coordinator.reconcile_terminal_order_observations(facts, limit=128)
        assert terminal_page.observation_count == 2
        assert terminal_page.truncated is False
        assert all(item.status in {"RESOLVED", "DUPLICATE"} for item in terminal_page.items)
        facts = _project(
            store,
            broker,
            target,
            projection_now,
            query_set=close_receipt.query_set,
        )
        receipt = close_receipt

    if position_date == "HISTORY":
        # The opening fill is durably source-bound to the prior query day.
        # Refresh a new complete query set on the next trading day, where CTP
        # reports the explicit HISTORY bucket's current Position. YdPosition
        # intentionally differs and is not used as the current balance.
        history_day = (datetime.strptime(_TRADING_DAY, "%Y%m%d") + timedelta(days=1)).strftime(
            "%Y%m%d"
        )
        api.trader_client._trading_day = history_day
        api.query_rows["positions_result"] = [
            _dated_position_row(
                "1",
                position_date="HISTORY",
                trading_day=history_day,
                today_position="0",
                yd_position="4",
            )
        ]
        # The complete current-day order/trade results contain no new rows;
        # the opening fill's exact T-day evidence remains in the position book.
        api.query_rows["orders_result"] = []
        api.query_rows["trades_result"] = []
        history_receipt, projection_now, _consumed = _refresh_complete_facts_after_callback(
            api,
            store,
            target,
            sequence=9,
            trading_day=history_day,
        )
        facts = _project(
            store,
            broker,
            target,
            projection_now,
            query_set=history_receipt.query_set,
        )
        trade_page = coordinator.reconcile_trade_observations(
            facts,
            refresh_receipt=history_receipt,
            limit=128,
        )
        assert trade_page.observation_count == 0
        assert trade_page.truncated is False
        dated_page = coordinator.position_book.reconcile_dated_trade_observations(
            facts,
            reconciliation_page=trade_page,
            limit=128,
        )
        assert dated_page.observation_count == 0
        assert dated_page.truncated is False
        facts = _project(
            store,
            broker,
            target,
            projection_now,
            query_set=history_receipt.query_set,
        )
        terminal_page = coordinator.reconcile_terminal_order_observations(facts, limit=128)
        assert terminal_page.observation_count == 0
        assert terminal_page.truncated is False
        facts = _project(
            store,
            broker,
            target,
            projection_now,
            query_set=history_receipt.query_set,
        )
        receipt = history_receipt

    if missing_fact == "average_price":
        position = replace(facts.positions[0], average_price=None)
        facts = replace(
            facts,
            positions=(position,),
            blockers=tuple(sorted(set(facts.blockers) | {"position_average_price_unobserved:rb"})),
        )

    position = facts.positions[0]
    assert position.quantity == Decimal("1")
    assert position.broker_quantity == Decimal("1")
    assert position.long_quantity == Decimal("1")
    assert position.short_quantity == Decimal("0")
    assert position.owner_strategy_scope == "alpha003"
    assert position.owner_intent_id == intent.intent_id
    assert position.average_price == (None if missing_fact == "average_price" else Decimal("100"))
    assert position.stop_price == (None if missing_fact == "stop_price" else Decimal("95"))
    assert position.held_eligible_bars is None
    assert position.opening_fee_total is None
    assert position.opening_fees_known is False
    assert len(position.dated_inventory_rows) == 1
    assert position.dated_inventory_rows[0].position_date == position_date
    assert position.dated_inventory_rows[0].position == Decimal("1")
    assert len(facts.dated_close_legs) == 1
    close_leg = facts.dated_close_legs[0]
    assert close_leg.ready is True, close_leg.blockers
    expected_offset_flag, expected_offset = (
        ("3", "close_today") if position_date == "TODAY" else ("4", "close_yesterday")
    )
    assert close_leg.position_date == position_date
    assert close_leg.offset_flag == expected_offset_flag
    assert close_leg.offset == expected_offset
    assert close_leg.side == "SELL"
    assert close_leg.available_quantity == Decimal("1")
    assert close_leg.owner_intent_id == intent.intent_id
    assert close_leg.query_set_id == facts.query_set_id
    assert close_leg.source_row_ids == (position.dated_inventory_rows[0].source_row_id,)
    assert close_leg.opening_execution_ids == (_execution_id_from_trade_row(open_trade_row),)
    if partial_close:
        assert close_leg.provider_quantity == Decimal("1")
        assert close_leg.owned_quantity == Decimal("1")
        assert close_leg.available_quantity == Decimal("1")
        assert close_leg.close_execution_ids == (_execution_id_from_trade_row(close_trade_row),)
        assert len(close_leg.lots) == 1
        assert close_leg.lots[0].opened_quantity == Decimal("2")
        assert close_leg.lots[0].closed_quantity == Decimal("1")
        assert close_leg.lots[0].remaining_quantity == Decimal("1")
    assert "position_held_age_unavailable:rb" in facts.blockers
    assert "position_opening_fee_unavailable:rb" in facts.blockers
    if missing_fact == "stop_price":
        assert "position_stop_price_unobserved:rb" in facts.blockers
    if missing_fact == "risk_policy":
        assert "position_risk_policy_metadata_unavailable:rb" in facts.blockers
    if missing_fact == "average_price":
        assert "position_average_price_unobserved:rb" in facts.blockers
    if missing_fact == "capital":
        assert facts.account.available_margin is None
        assert facts.instruments[0].long_margin_per_hand is None
        assert facts.instruments[0].short_margin_per_hand is None
        assert "available_margin_unobserved" in facts.blockers
    assert facts.quotes[0].quality == "GOOD"
    assert facts.route_eligibilities[0].eligible is True
    assert facts.risk_reduction_ready is True, facts.risk_reduction_blockers
    assert facts.open_risk_ready is False
    return facts, {
        "api": api,
        "store": store,
        "broker": broker,
        "journal": journal,
        "coordinator": coordinator,
        "target": target,
        "intent": intent,
        "now": projection_now,
        "query_set": receipt.query_set,
        "query_receipt": receipt,
        "trade_page": trade_page,
        "dated_page": dated_page,
        "dated_source_facts": dated_source_facts,
        "dated_source_trade_page": dated_source_trade_page,
        "native_receipt": native_receipt,
        "opening_execution_id": _execution_id_from_trade_row(open_trade_row),
        "closing_execution_id": (
            _execution_id_from_trade_row(close_trade_row) if partial_close else None
        ),
    }


def test_dated_trade_query_origin_keeps_same_receipt_binding_strict():
    facts, live_inputs = _build_source_backed_dated_close_facts()
    journal = live_inputs["journal"]
    intent = live_inputs["intent"]
    execution_id = live_inputs["opening_execution_id"]
    query_callback_id = "query-trade:" + sha256(execution_id.encode()).hexdigest()
    query_receipt = journal.callback_receipt(intent.intent_id, query_callback_id)
    fill = journal._connection.execute(
        "SELECT receipt_id FROM factor_position_fills WHERE execution_id=?",
        (execution_id,),
    ).fetchone()

    assert query_receipt is not None and query_receipt.acknowledged is True
    assert fill["receipt_id"] == query_receipt.receipt_id
    # The helper returns the final idempotent re-read, after the first page
    # applied the dated observation and the second correctly reports duplicate.
    assert live_inputs["dated_page"].items[0].status == "DUPLICATE"
    assert len(facts.dated_close_legs) == 1
    assert facts.dated_close_legs[0].ready is True


def test_dated_trade_accepts_acknowledged_native_origin_and_separate_query_receipt():
    _facts, live_inputs = _build_source_backed_dated_close_facts(
        native_callback_mode="acknowledged"
    )
    journal = live_inputs["journal"]
    intent = live_inputs["intent"]
    execution_id = live_inputs["opening_execution_id"]
    native_receipt = live_inputs["native_receipt"]
    query_receipt = journal.callback_receipt(
        intent.intent_id,
        "query-trade:" + sha256(execution_id.encode()).hexdigest(),
    )
    fill = journal._connection.execute(
        "SELECT receipt_id FROM factor_position_fills WHERE execution_id=?",
        (execution_id,),
    ).fetchone()

    assert native_receipt.acknowledged is True
    assert query_receipt is not None and query_receipt.acknowledged is True
    assert native_receipt.receipt_id != query_receipt.receipt_id
    assert fill["receipt_id"] == native_receipt.receipt_id
    assert live_inputs["dated_page"].items[0].status == "DUPLICATE"
    assert journal.callback_query_disposition(native_receipt.receipt_id) is None
    assert len(_facts.dated_close_legs) == 1
    assert _facts.dated_close_legs[0].ready is True


def test_dated_snapshot_rejects_native_evidence_tampering_after_reconciliation(monkeypatch):
    facts, live_inputs = _build_source_backed_dated_close_facts(native_callback_mode="acknowledged")
    coordinator = live_inputs["coordinator"]
    journal = live_inputs["journal"]
    intent = live_inputs["intent"]
    execution_id = live_inputs["opening_execution_id"]
    native_callback_id = "ctp-trade:" + sha256(execution_id.encode()).hexdigest()
    original_callback_receipt = journal.callback_receipt
    actual_native_receipt = original_callback_receipt(intent.intent_id, native_callback_id)
    assert actual_native_receipt is not None

    def altered_native_receipt(receipt_intent_id, callback_id):
        receipt = original_callback_receipt(receipt_intent_id, callback_id)
        if receipt is None or callback_id != native_callback_id:
            return receipt
        evidence = dict(receipt.evidence_payload)
        evidence["price"] = "101"
        return replace(receipt, evidence_payload=evidence)

    monkeypatch.setattr(journal, "callback_receipt", altered_native_receipt)
    proof = coordinator.position_book.dated_snapshot(facts, target_id="rb")

    assert proof.status == "UNKNOWN"
    assert proof.ready is False
    assert proof.blocker_code == "DATED_TRADE_NATIVE_ECONOMICS_MISMATCH"
    assert proof.buckets == ()


def test_dated_trade_accepts_unacknowledged_native_fill_only_with_restart_proof(monkeypatch):
    _facts, live_inputs = _build_source_backed_dated_close_facts(
        native_callback_mode="unacknowledged_restart",
        monkeypatch=monkeypatch,
    )
    journal = live_inputs["journal"]
    intent = live_inputs["intent"]
    execution_id = live_inputs["opening_execution_id"]
    native_receipt = live_inputs["native_receipt"]
    query_receipt = journal.callback_receipt(
        intent.intent_id,
        "query-trade:" + sha256(execution_id.encode()).hexdigest(),
    )
    disposition = journal.callback_query_disposition(native_receipt.receipt_id)
    native_state = journal._connection.execute(
        "SELECT acknowledged,delivery_pending FROM execution_decision_callbacks WHERE receipt_id=?",
        (native_receipt.receipt_id,),
    ).fetchone()

    assert native_receipt.acknowledged is False
    assert query_receipt is not None and query_receipt.acknowledged is True
    assert disposition is not None
    assert disposition.query_receipt_id == query_receipt.receipt_id
    assert disposition.execution_id == execution_id
    assert tuple(native_state) == (0, 0)
    # The helper returns the second, idempotent dated-page read after the first
    # query-origin receipt already applied the persisted observation.
    assert live_inputs["dated_page"].items[0].status == "DUPLICATE"
    assert len(_facts.dated_close_legs) == 1
    assert _facts.dated_close_legs[0].ready is True


def test_dated_trade_rejects_unacknowledged_native_fill_without_restart_proof(monkeypatch):
    _facts, live_inputs = _build_source_backed_dated_close_facts(
        native_callback_mode="unacknowledged_same_process",
        monkeypatch=monkeypatch,
    )

    assert live_inputs["trade_page"].items[0].status == "DUPLICATE"
    assert live_inputs["trade_page"].items[0].blocker_code == ("CALLBACK_QUERY_RESTART_NOT_PROVEN")
    assert live_inputs["dated_page"].items[0].blocker_code == (
        "DATED_TRADE_NATIVE_ACK_STATE_MISMATCH"
    )
    assert live_inputs["dated_page"].items[0].status == "BLOCKED"


@pytest.mark.parametrize(
    ("evidence_field", "replacement", "expected_blocker"),
    (
        ("execution_id", "ctp:wrong:trade", "DATED_TRADE_NATIVE_EVIDENCE_MISMATCH"),
        ("price", "101", "DATED_TRADE_NATIVE_ECONOMICS_MISMATCH"),
    ),
)
def test_dated_trade_rejects_native_only_execution_or_economics_mismatch(
    evidence_field, replacement, expected_blocker
):
    facts, live_inputs = _build_source_backed_dated_close_facts(native_callback_mode="acknowledged")
    from backtrader.stores.factor_position_book import (
        _dated_trade_journal_binding_error,
        _dated_trade_source_values,
    )

    trade_page = live_inputs["dated_source_trade_page"]
    facts = live_inputs["dated_source_facts"]
    observation = facts.trade_observations[0]
    source_values, error_code = _dated_trade_source_values(
        facts,
        observation,
        trade_page.items[0],
        query_set_id=facts.query_set_id,
    )
    assert error_code is None
    execution_id = live_inputs["opening_execution_id"]
    values = dict(source_values)
    original_journal = live_inputs["journal"]
    query_callback_id = "query-trade:" + sha256(execution_id.encode()).hexdigest()
    query_receipt = original_journal.callback_receipt(
        live_inputs["intent"].intent_id, query_callback_id
    )
    assert query_receipt is not None and query_receipt.acknowledged is True
    native_callback_id = "ctp-trade:" + sha256(execution_id.encode()).hexdigest()

    class _AlteredNativeReceiptJournal:
        def callback_receipt(self, intent_id, callback_id):
            receipt = original_journal.callback_receipt(intent_id, callback_id)
            if callback_id != native_callback_id or receipt is None:
                return receipt
            altered_evidence = dict(receipt.evidence_payload)
            altered_evidence[evidence_field] = replacement
            return replace(receipt, evidence_payload=altered_evidence)

        def callback_query_disposition(self, native_receipt_id):
            return original_journal.callback_query_disposition(native_receipt_id)

    journal = original_journal
    with journal._read_lock():
        cursor = journal._connection.cursor()
        try:
            fill = cursor.execute(
                "SELECT * FROM factor_position_fills WHERE execution_id=?",
                (live_inputs["opening_execution_id"],),
            ).fetchone()
            callback = cursor.execute(
                "SELECT * FROM execution_decision_callbacks WHERE receipt_id=?",
                (query_receipt.receipt_id,),
            ).fetchone()
            blocker = _dated_trade_journal_binding_error(
                cursor,
                fill,
                callback,
                values,
                journal=_AlteredNativeReceiptJournal(),
                intent_id=live_inputs["intent"].intent_id,
                receipt_id=query_receipt.receipt_id,
                execution_id=execution_id,
            )
        finally:
            cursor.close()

    assert blocker == expected_blocker


@pytest.mark.parametrize(
    "missing_fact", (None, "stop_price", "risk_policy", "average_price", "capital")
)
def test_missing_open_risk_facts_preserve_proven_position_reduction_facts(missing_fact):
    _build_source_backed_dated_close_facts(missing_fact)


def test_source_backed_history_open_fill_maps_to_close_yesterday_leg():
    facts, live_inputs = _build_source_backed_dated_close_facts(position_date="HISTORY")

    position = facts.positions[0]
    leg = facts.dated_close_legs[0]
    assert position.dated_inventory_rows[0].trading_day == facts.account.trading_day
    assert position.dated_inventory_rows[0].position == Decimal("1")
    assert position.dated_inventory_rows[0].yd_position == Decimal("4")
    assert leg.ready is True, leg.blockers
    assert leg.position_date == "HISTORY"
    assert leg.offset_flag == "4"
    assert leg.offset == "close_yesterday"
    assert leg.side == "SELL"
    assert leg.available_quantity == Decimal("1")
    assert leg.owner_intent_id == live_inputs["intent"].intent_id
    assert leg.query_set_id == live_inputs["query_set"].query_set_id


def test_source_backed_partial_close_keeps_owned_today_remainder():
    facts, live_inputs = _build_source_backed_dated_close_facts(partial_close=True)

    assert facts.positions[0].quantity == Decimal("1")
    assert facts.positions[0].broker_quantity == Decimal("1")
    leg = facts.dated_close_legs[0]
    assert leg.ready is True, leg.blockers
    assert leg.position_date == "TODAY"
    assert leg.offset_flag == "3"
    assert leg.offset == "close_today"
    assert leg.available_quantity == Decimal("1")
    assert leg.close_execution_ids == (live_inputs["closing_execution_id"],)


def test_source_backed_dated_close_proof_survives_journal_and_coordinator_restart(tmp_path):
    journal_path = tmp_path / "dated-position.sqlite3"
    facts, live_inputs = _build_source_backed_dated_close_facts(journal_path=journal_path)
    original_broker = live_inputs["broker"]
    target = live_inputs["target"]
    broker_position = original_broker.getposition(target.data)
    live_inputs["journal"].close()

    reopened_journal = ExecutionDecisionJournal(journal_path)
    reopened_broker = BtApiBroker(
        store=live_inputs["store"],
        contract_metadata={_INSTRUMENT: {"instrument_id": _INSTRUMENT, "exchange_id": _EXCHANGE}},
    )
    # A process restart creates a new Broker too. Restore only its ordinary
    # current Broker projection from the prior Broker snapshot; ownership and
    # dated lots still come solely from the reopened journal/book.
    reopened_broker.positions[_INSTRUMENT].update(broker_position.size, broker_position.price)
    reopened_coordinator = FactorExecutionCoordinator(
        reopened_broker,
        reopened_journal,
        account_scope="acct-scope",
        strategy_scope="alpha003",
        logical_run_id="run-1",
        max_order_intents_per_grid=4,
        max_order_intents_per_run=1000,
    )
    reprojected = _project(
        live_inputs["store"],
        reopened_broker,
        target,
        live_inputs["now"],
        query_set=live_inputs["query_set"],
    )

    assert reprojected.snapshot_id == facts.snapshot_id
    assert reprojected.query_set_id == facts.query_set_id
    assert reprojected.positions[0].owner_intent_id == live_inputs["intent"].intent_id
    assert len(reprojected.dated_close_legs) == 1
    assert reprojected.dated_close_legs[0].ready is True
    assert reprojected.dated_close_legs[0].opening_execution_ids == (
        live_inputs["opening_execution_id"],
    )
    assert reopened_coordinator.position_book is not None


def test_unattributed_mixed_date_inventory_does_not_create_close_legs():
    now = datetime.now(timezone.utc)
    rows = _query_rows(
        positions=(
            _dated_position_row("1", position_date="TODAY", yd_position="0"),
            _dated_position_row("1", position_date="HISTORY", today_position="0", yd_position="2"),
        )
    )
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=rows,
    )
    broker.positions[_INSTRUMENT].update(2, 100.0)
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert facts.positions[0].quantity == Decimal("2")
    assert {row.position_date for row in facts.positions[0].dated_inventory_rows} == {
        "TODAY",
        "HISTORY",
    }
    assert all(row.blockers == () for row in facts.positions[0].dated_inventory_rows)
    assert not any(leg.ready for leg in facts.dated_close_legs)
    assert facts.risk_reduction_ready is False


def test_external_position_and_remote_only_order_are_explicitly_blocked():
    now = datetime.now(timezone.utc)
    external = {
        "InstrumentID": "i2509",
        "ExchangeID": "DCE",
        "PosiDirection": "2",
        "Position": "1.5",
    }
    remote_order = {
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "OrderRef": "remote-8",
        "OrderStatus": "3",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotal": "0.5",
    }
    rows = _query_rows(positions=(external,), orders=(remote_order,))
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=rows,
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert any(item.target_id is None and item.instrument == "i2509" for item in facts.positions)
    assert any(
        item.order_ref == "remote-8" and item.execution_unknown is True
        for item in facts.working_orders
    )
    assert "external_position_outside_target_scope:i2509:DCE" in facts.blockers
    assert "remote_working_order_missing_from_broker:remote-8" in facts.blockers
    assert facts.account is not None
    assert facts.account.current_notional is None
    assert facts.account.current_worst_case_loss is None
    assert facts.risk_reduction_ready is False
    assert facts.open_risk_ready is False


def test_opposing_remote_position_sides_are_not_netted():
    now = datetime.now(timezone.utc)
    rows = _query_rows(
        positions=(
            {
                "InstrumentID": _INSTRUMENT,
                "ExchangeID": _EXCHANGE,
                "PosiDirection": "2",
                "Position": "1",
            },
            {
                "InstrumentID": _INSTRUMENT,
                "ExchangeID": _EXCHANGE,
                "PosiDirection": "3",
                "Position": "1",
            },
        )
    )
    _api, store, broker, _journal, _coordinator, target = _system_under_test(
        now=now,
        rows=rows,
    )
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)

    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    assert "opposing_position_sides_present:rb2510" in facts.blockers
    assert "OPPOSING_POSITION_SIDES_PRESENT" in facts.blockers
    assert facts.account is not None
    assert facts.account.current_notional is None
    assert facts.risk_reduction_ready is False


def test_cancelled_refresh_stops_before_query_and_leaves_pending_families():
    now = datetime.now(timezone.utc)
    api, store, _broker, _journal, _coordinator, target = _system_under_test(now=now)
    import threading

    cancel = threading.Event()
    cancel.set()
    receipt = refresh_factor_execution_queries(
        store,
        targets=(target,),
        overall_timeout=1.0,
        cancel_event=cancel,
    )

    assert receipt.cancelled is True
    assert receipt.attempted_families == ()
    assert receipt.pending_families[0] == "account_result"
    assert api.query_calls == []


def test_fact_records_are_immutable():
    now = datetime.now(timezone.utc)
    _api, store, broker, _journal, _coordinator, target = _system_under_test(now=now)
    receipt = _refresh_all(store, target)
    _arm(store)
    _consume_quote(store)
    facts = _project(store, broker, target, now, query_set=receipt.query_set)

    with pytest.raises((AttributeError, TypeError)):
        facts.available_at = now + timedelta(seconds=1)
