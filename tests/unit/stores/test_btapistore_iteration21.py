import asyncio
import datetime as dt
import os
import threading
import time
from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.brokers import btapibroker as broker_module
from backtrader.events import BarEvent, FundingEvent, OrderBookSnapshot, TickEvent
from backtrader.feeds import btapifeed as feed_module
from backtrader.order import OrderBase
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError

VENUE = "OKX___SWAP"
SYMBOL = "BTC-USDT-SWAP"


class AsyncSdk:
    def __init__(self, *, position_mode="dual_side", block_first=False):
        self.exchange_kwargs = {VENUE: {"environment": "demo"}}
        self.position_mode = position_mode
        self.events = defaultdict(deque)
        self.calls = []
        self.sequence = 0
        self.block_first = block_first
        self.release = False
        self.positions = []
        self.open_orders = []
        self.closed = False
        self.poll_calls = []
        self.clock_domain_id = "async-sdk-test-process-monotonic"
        self.credential_fingerprint = "a" * 64
        self.account_id = f"okx-credential-{self.credential_fingerprint}"
        self.fencing_epoch = 1

    def new_client_order_id(self, venue):
        self.sequence += 1
        return f"client-{self.sequence}"

    def get_execution_identity(self, venue):
        return {
            "provider": venue.partition("___")[0],
            "environment": "demo",
            "account_id": self.account_id,
            "credential_fingerprint": self.credential_fingerprint,
            "account_authority": "credential_fingerprint",
            "exchange_name": venue,
            "strategy_id": "test",
            "fencing_epoch": self.fencing_epoch,
        }

    def get_all_balances(self, *, normalized=False):
        assert normalized
        return {VENUE: {"cash": 10000, "value": 10000, "exchange_name": VENUE}}

    def get_portfolio_balance(self, *, venue_balances):
        return {"cash": 10000, "value": 10000}

    def get_execution_summary(self):
        return {
            "session_enabled": True,
            "unknown_ids": [],
            "active_orders": 0,
            "fee_unresolved_orders": [],
            "funding_unresolved_orders": [],
            "trading_blocked": False,
            "reconciliation_errors": {},
        }

    def get_position(self, venue, symbol, *, normalized=False):
        assert normalized
        return deepcopy(self.positions)

    def get_open_orders(self, venue, symbol, *, normalized=False):
        assert normalized
        return deepcopy(self.open_orders)

    def get_account_config(self, venue, *, normalized=False):
        assert normalized
        return {
            "exchange_name": venue,
            "position_mode": self.position_mode,
            "can_trade": True,
        }

    def get_order_readiness(
        self,
        venue,
        symbol,
        quantity_native,
        *,
        margin_mode="cross",
        position_mode=None,
        normalized=False,
    ):
        assert normalized
        return {
            "ready": self.position_mode == position_mode,
            "definite_failure": self.position_mode != position_mode,
            "reasons": [] if self.position_mode == position_mode else ["position_mode"],
            "position_mode": self.position_mode,
            "symbol": symbol,
            "exchange_name": venue,
        }

    def get_exchange_info(self, venue, symbol, *, normalized=False):
        assert normalized
        return {
            "symbol": symbol,
            "exchange_name": venue,
            "min_size": 1,
            "lot_size": 1,
            "quantity_unit": "contracts",
        }

    def subscribe(self, name, topics):
        self.calls.append(("subscribe", name, topics))

    def poll_events(self, venue, *, max_raw_items, coalesce_market_snapshots):
        self.poll_calls.append((venue, max_raw_items, coalesce_market_snapshots))
        rows = []
        for _ in range(min(max_raw_items, len(self.events[venue]))):
            row = deepcopy(self.events[venue].popleft())
            row.setdefault("received_monotonic_ns", time.monotonic_ns())
            row.setdefault("clock_domain_id", self.clock_domain_id)
            rows.append(row)
        return rows

    async def async_make_order(self, venue, request, *, normalized=False):
        assert normalized
        self.calls.append(
            (
                "submit",
                request.client_order_id,
                request.reduce_only,
                request.offset,
                request.position_side,
            )
        )
        if self.block_first and len([row for row in self.calls if row[0] == "submit"]) == 1:
            while not self.release:
                await asyncio.sleep(0.001)
        if request.reduce_only:
            self.positions = []
        return {
            "kind": "order",
            "symbol": request.symbol,
            "client_order_id": request.client_order_id,
            "order_id": request.client_order_id,
            "status": "filled",
            "filled": str(request.quantity),
            "price": "100",
        }

    async def async_cancel_order(self, venue, request, *, normalized=False):
        assert normalized
        self.calls.append(("cancel", request.client_order_id, False))
        return {
            "kind": "order",
            "symbol": request.symbol,
            "client_order_id": request.client_order_id,
            "order_id": request.order_id,
            "status": "submitted",
        }

    async def async_query_order(self, venue, request, *, normalized=False):
        assert normalized
        self.calls.append(("query", request.client_order_id, False))
        return {
            "kind": "order",
            "symbol": request.symbol,
            "client_order_id": request.client_order_id,
            "order_id": request.order_id,
            "status": "canceled",
            "terminal_confirmed": True,
        }

    def close(self):
        self.closed = True


@dataclass(frozen=True)
class TypedFreshness:
    source: str
    observed_at: dt.datetime
    stale: bool = False
    stale_reason: str = ""


@dataclass(frozen=True)
class TypedInstrument:
    exchange_name: str
    symbol: str
    contract_value: Decimal
    contract_multiplier: Decimal
    price_tick: Decimal
    quantity_step: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    quantity_unit: str
    quote_currency: str
    status: str
    freshness: TypedFreshness
    available: bool = True


@dataclass(frozen=True)
class TypedFunding:
    exchange_name: str
    symbol: str
    rate: Decimal
    next_funding_time: dt.datetime
    settlement_interval_seconds: int
    source: str
    freshness: TypedFreshness
    available: bool = True


@dataclass(frozen=True)
class TypedFee:
    exchange_name: str
    symbol: str
    account_id: str
    maker_rate: Decimal
    taker_rate: Decimal
    currency: str
    source: str
    freshness: TypedFreshness
    available: bool = True


@dataclass(frozen=True)
class TypedReadiness:
    exchange_name: str
    symbol: str
    account_id: str
    can_trade: bool
    position_mode: str
    instrument_status: str
    blocked_reasons: tuple
    freshness: TypedFreshness
    available: bool = True

    @property
    def ready(self):
        return (
            self.available
            and self.can_trade
            and self.position_mode == "dual_side"
            and self.instrument_status == "live"
            and not self.blocked_reasons
        )


class TypedSdk(AsyncSdk):
    def _freshness(self):
        return TypedFreshness("exchange", dt.datetime(2026, 9, 7, tzinfo=dt.timezone.utc))

    def get_instrument_spec(self, venue, symbol):
        self.calls.append(("get_instrument_spec", venue, symbol))
        return TypedInstrument(
            venue,
            symbol,
            Decimal("0.01"),
            Decimal("1"),
            Decimal("0.1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("0"),
            "contracts",
            "USDT",
            "live",
            self._freshness(),
        )

    def get_funding_snapshot(self, venue, symbol):
        self.calls.append(("get_funding_snapshot", venue, symbol))
        return TypedFunding(
            venue,
            symbol,
            Decimal("0.0001"),
            dt.datetime(2026, 9, 7, 8, tzinfo=dt.timezone.utc),
            28_800,
            "exchange",
            self._freshness(),
        )

    def get_fee_schedule(self, venue, symbol, account_id):
        self.calls.append(("get_fee_schedule", venue, symbol, account_id))
        return TypedFee(
            venue,
            symbol,
            account_id,
            Decimal("0.0002"),
            Decimal("0.0005"),
            "USDT",
            "exchange",
            self._freshness(),
        )

    def get_trading_readiness(
        self,
        venue,
        symbol,
        account_id,
        quantity_native,
        *,
        margin_mode,
        position_mode,
    ):
        self.calls.append(
            (
                "get_trading_readiness",
                venue,
                symbol,
                account_id,
                quantity_native,
                margin_mode,
                position_mode,
            )
        )
        return TypedReadiness(
            venue,
            symbol,
            account_id,
            True,
            self.position_mode,
            "live",
            (),
            self._freshness(),
        )


def make_store(api, **config):
    return BtApiStore(
        provider="btapi",
        api=api,
        config={
            "exchange_kwargs": api.exchange_kwargs,
            "symbol_routes": {SYMBOL: VENUE},
            **config,
        },
    )


def make_owned_store(api_cls):
    return BtApiStore(
        provider="btapi",
        api_cls=api_cls,
        config={
            "exchange_kwargs": {VENUE: {"environment": "demo"}},
            "symbol_routes": {SYMBOL: VENUE},
        },
    )


def account_risk_payload(api, *, baseline="10000.00", current="9999.50", loss_limit_bps=None):
    identity = api.get_execution_identity(VENUE)
    ledger_identity = {
        key: identity[key]
        for key in ("provider", "environment", "account_id", "credential_fingerprint")
    }
    now = time.monotonic_ns()
    baseline_value = Decimal(baseline)
    current_value = Decimal(current)
    loss = max(baseline_value - current_value, Decimal("0"))
    loss_bps = loss * Decimal("10000") / baseline_value
    limit = None if loss_limit_bps is None else Decimal(str(loss_limit_bps))
    return {
        "schema_version": 1,
        "ledger_identities": [ledger_identity],
        "configured_venues": [VENUE],
        "baseline_equity_by_venue": {VENUE: {"currency": "USDT", "equity": baseline}},
        "current_equity_by_venue": {VENUE: {"currency": "USDT", "equity": current}},
        "baseline_equity": Decimal(baseline),
        "current_equity": Decimal(current),
        "currency": "USDT",
        "generation": identity["fencing_epoch"],
        "fencing_epoch": identity["fencing_epoch"],
        "owner_pid": os.getpid(),
        "as_of_monotonic_ns": now,
        "clock_domain_id": f"process:{os.getpid()}:monotonic",
        "blocked_reasons": [],
        "evidence_errors": {},
        "durable": True,
        "trading_blocked": False,
        "evidence_complete": True,
        "loss_limit_bps": None if limit is None else str(limit),
        "loss_limit_breached": False,
        "loss_breached_at": None,
        "loss_amount": None if limit is None else str(loss),
        "loss_limit_amount": (
            None if limit is None else str(baseline_value * limit / Decimal("10000"))
        ),
        "loss_bps_observed": None if limit is None else str(loss_bps),
        "peak_loss_bps": None if limit is None else str(loss_bps),
    }


def account_risk_prebaseline_payload(api):
    snapshot = account_risk_payload(api)
    snapshot.update(
        baseline_equity=None,
        baseline_equity_by_venue=None,
        blocked_reasons=["account_evidence_incomplete", "baseline_missing"],
        durable=False,
        trading_blocked=True,
        evidence_complete=False,
    )
    return snapshot


def local_order(ref=1, *, offset="open", reduce_only=False):
    info = {
        "position_side": "long",
        "offset": offset,
        "reduce_only": reduce_only,
        "quantity_unit": "contracts",
    }
    return SimpleNamespace(
        data=SimpleNamespace(_name=SYMBOL),
        ref=ref,
        size=1,
        price=100,
        created=SimpleNamespace(price=100),
        pricelimit=None,
        valid=None,
        exectype=OrderBase.Limit,
        tradeid=0,
        isbuy=lambda: True,
        info=info,
        addinfo=lambda **kwargs: info.update(kwargs),
    )


def test_async_submit_returns_receipt_without_waiting_for_transport():
    api = AsyncSdk(block_first=True)
    store = make_store(api)
    store.start()
    try:
        started = time.perf_counter()
        receipt = store.submit_order(local_order())
        elapsed = time.perf_counter() - started

        assert receipt["queued"] is True
        assert receipt["status"] == "submitted"
        assert elapsed < 0.05
        api.release = True
        assert store.wait_for_commands(1)
        completion = store.poll_broker_update()
        assert completion["kind"] == "command_completion"
        assert completion["success"] is True
    finally:
        api.release = True
        store.stop()


def test_market_data_only_store_rejects_direct_submit_and_cancel_without_transport():
    """A caller with a Store reference cannot bypass Broker's MDO guard."""
    api = AsyncSdk()
    store = make_store(api)
    store.start()
    try:
        # Simulate the already-started CTP Store's read-only session fence.
        # ``AsyncSdk`` deliberately implements only the public command API,
        # not the optional dynamic execution-config reconfiguration endpoint.
        store._sdk_execution_config["market_data_only"] = True
        submit = store.submit_order(local_order())
        cancel = store.cancel_order_ref("external-order", dataname=SYMBOL)
        direct_submit = store.enqueue_order(local_order(2, offset="close", reduce_only=True))
        direct_cancel = store.enqueue_cancel("external-order", dataname=SYMBOL)

        for receipt, operation in (
            (submit, "submit"),
            (cancel, "cancel"),
            (direct_submit, "submit"),
            (direct_cancel, "cancel"),
        ):
            assert receipt["command"] == operation
            assert receipt["queued"] is False
            assert receipt["status"] == "rejected"
            assert receipt["error_code"] == "market_data_only"

        assert not [call for call in api.calls if call[0] in {"submit", "cancel"}]
        assert store.get_command_health()["queue_depth"] == 0
        assert store.get_command_health()["rejected_market_data_only"] == 4
    finally:
        store.stop()


def test_unknown_submit_mapping_freezes_and_rejects_queued_opening_before_transport():
    class UnknownFirstSdk(AsyncSdk):
        async def async_make_order(self, venue, request, *, normalized=False):
            assert normalized
            self.calls.append(("submit", request.client_order_id, False, request.offset, None))
            if len([row for row in self.calls if row[0] == "submit"]) == 1:
                while not self.release:
                    await asyncio.sleep(0.001)
                return {
                    "kind": "order",
                    "symbol": request.symbol,
                    "client_order_id": request.client_order_id,
                    "status": "submitted",
                    "execution_unknown": True,
                    "error_code": "transport_ack_lost",
                }
            raise AssertionError("queued opening must not reach transport after an unknown result")

    api = UnknownFirstSdk()
    store = make_store(api)
    store.start()
    try:
        first = store.submit_order(local_order(1))
        deadline = time.monotonic() + 1
        while not api.calls and time.monotonic() < deadline:
            time.sleep(0.001)
        second = store.submit_order(local_order(2))
        assert first["queued"] is True and second["queued"] is True

        api.release = True
        assert store.wait_for_commands(1)
        completions = [store.poll_broker_update(), store.poll_broker_update()]
        by_ref = {row["bt_order_ref"]: row for row in completions}

        assert len([row for row in api.calls if row[0] == "submit"]) == 1
        assert by_ref[1]["success"] is False
        assert by_ref[1]["status"] == "unknown"
        assert by_ref[1]["execution_unknown"] is True
        assert by_ref[2]["success"] is False
        assert by_ref[2]["status"] == "rejected"
        assert by_ref[2]["execution_unknown"] is False
        assert by_ref[2]["remote_write_attempted"] is False
        assert by_ref[2]["error_code"] == "openings_frozen_after_unknown"
        health = store.get_command_health()
        assert health["accepting_openings"] is False
        assert health["risk_state_latched"] is True
        assert health["discarded_open"] == 1
    finally:
        api.release = True
        store.stop()


def test_wait_for_commands_includes_unsent_completion_publication(monkeypatch):
    api = AsyncSdk(block_first=True)
    store = make_store(api)
    store.start()
    publication_started = threading.Event()
    release_publication = threading.Event()
    original_append = store._append_sdk_update

    def blocked_append(update):
        if update.get("error_code") == "openings_frozen_before_send":
            publication_started.set()
            release_publication.wait(1)
        return original_append(update)

    monkeypatch.setattr(store, "_append_sdk_update", blocked_append)
    try:
        assert store.submit_order(local_order(1))["queued"] is True
        deadline = time.monotonic() + 1
        while not api.calls and time.monotonic() < deadline:
            time.sleep(0.001)
        assert store.submit_order(local_order(2))["queued"] is True
        store.freeze_openings("test_freeze")
        api.release = True
        assert publication_started.wait(1)

        assert store.wait_for_commands(0.01) is False
        assert store.get_command_health()["publications_pending"] == 1
        release_publication.set()
        assert store.wait_for_commands(1) is True
        completions = [store.poll_broker_update(), store.poll_broker_update()]
        assert {row["bt_order_ref"] for row in completions} == {1, 2}
        assert (
            next(row for row in completions if row["bt_order_ref"] == 2)["remote_write_attempted"]
            is False
        )
    finally:
        api.release = True
        release_publication.set()
        store.stop()


def test_public_execution_latch_reserves_purged_opening_publication(monkeypatch):
    api = AsyncSdk(block_first=True)
    store = make_store(api)
    store.start()
    publication_started = threading.Event()
    release_publication = threading.Event()
    latch_finished = threading.Event()
    original_append = store._append_sdk_update

    def blocked_append(update):
        if update.get("error_code") == "openings_frozen_after_unknown":
            publication_started.set()
            release_publication.wait(1)
        return original_append(update)

    def latch():
        try:
            store.latch_execution_evidence_loss("trade_identity_mismatch")
        finally:
            latch_finished.set()

    monkeypatch.setattr(store, "_append_sdk_update", blocked_append)
    latch_thread = threading.Thread(target=latch, daemon=True)
    try:
        assert store.submit_order(local_order(1))["queued"] is True
        deadline = time.monotonic() + 1
        while not api.calls and time.monotonic() < deadline:
            time.sleep(0.001)
        assert store.submit_order(local_order(2))["queued"] is True

        latch_thread.start()
        assert publication_started.wait(1)
        api.release = True
        deadline = time.monotonic() + 1
        while store.get_command_health()["inflight"] and time.monotonic() < deadline:
            time.sleep(0.001)

        assert store.wait_for_commands(0.01) is False
        assert store.get_command_health()["publications_pending"] == 1
        assert latch_finished.is_set() is False

        release_publication.set()
        latch_thread.join(1)
        assert latch_finished.is_set() is True
        assert store.wait_for_commands(1) is True
        completions = [store.poll_broker_update(), store.poll_broker_update()]
        assert {row["bt_order_ref"] for row in completions} == {1, 2}
        rejected = next(row for row in completions if row["bt_order_ref"] == 2)
        assert rejected["status"] == "rejected"
        assert rejected["remote_write_attempted"] is False
    finally:
        api.release = True
        release_publication.set()
        latch_thread.join(1)
        store.stop()


def test_sdk_session_never_falls_back_to_synchronous_write_after_async_rejection():
    class UnsupportedAsyncSdk(AsyncSdk):
        async def async_make_order(self, venue, request, *, normalized=False):
            raise NotImplementedError("typed async write unavailable")

        def make_order(self, *_args, **_kwargs):
            raise AssertionError("Store must not bypass the SDK async session")

    api = UnsupportedAsyncSdk()
    store = make_store(api)
    store.start()
    try:
        receipt = store.submit_order(local_order())
        assert receipt["queued"] is True
        assert store.wait_for_commands(1)
        completion = store.poll_broker_update()
        assert completion["success"] is False
        assert completion["status"] == "unknown"
        assert completion["execution_unknown"] is True
        assert completion["error_code"] == "NotImplementedError"
    finally:
        store.stop()


def test_priority_queue_preserves_reserved_risk_capacity_and_order():
    api = AsyncSdk(block_first=True)
    store = make_store(api, command_queue_size=5, command_reserved_capacity=2)
    store.start()
    try:
        first = store.submit_order(local_order(1))
        assert first["queued"]
        deadline = time.monotonic() + 1
        while not api.calls and time.monotonic() < deadline:
            time.sleep(0.001)

        second = store.submit_order(local_order(2))
        third = store.submit_order(local_order(3))
        fourth = store.submit_order(local_order(4))
        rejected = store.submit_order(local_order(5))
        close = store.submit_order(local_order(6, offset="close", reduce_only=True))
        assert second["queued"] and third["queued"] and fourth["queued"] and close["queued"]
        assert rejected["queued"] is False
        assert rejected["error_code"] == "command_queue_reserved_capacity"

        api.release = True
        assert store.wait_for_commands(1)
        submits = [row for row in api.calls if row[0] == "submit"]
        assert submits[0][1] == first["client_order_id"]
        assert submits[1][2] is True
        assert store.get_command_health()["rejected_open"] == 1
    finally:
        api.release = True
        store.stop()


def test_causal_fields_and_gap_health_are_observable_and_fail_closed():
    api = AsyncSdk()
    store = make_store(api, book_queue_size=4)
    store.start()
    store.subscribe(SYMBOL)
    api.events[VENUE].extend(
        [
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.0,
                "exchange": VENUE,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 10,
                "previous_sequence": 9,
                "snapshot_or_delta": "delta",
                "continuity_status": "continuous",
                "event_id": "book-10",
                "coalesced_count": 3,
            },
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.1,
                "exchange": VENUE,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 12,
                "previous_sequence": 11,
                "snapshot_or_delta": "delta",
                "continuity_status": "continuous",
                "event_id": "book-12",
            },
        ]
    )
    try:
        first = store.poll_orderbook(SYMBOL)
        second = store.poll_orderbook(SYMBOL)
        assert isinstance(first, OrderBookSnapshot)
        assert first.event_id == "book-10"
        assert first.exchange_time == first.timestamp
        assert first.received_monotonic_ns > 0
        assert first.clock_domain_id
        assert second.stale is True
        assert second.stale_reason == "sequence_gap"
        health = store.get_stream_health(SYMBOL)
        assert health["sdk_ingress"] == 4
        assert health["sdk_coalesced"] == 2
        assert health["sequence_gap"] == 1
        assert health["stale"] is True
        assert all(call[2] == () for call in api.poll_calls)
    finally:
        store.stop()


def test_sdk_event_without_causal_provenance_is_dropped_and_marks_stream_stale():
    api = AsyncSdk()
    store = make_store(api)
    store.start()
    store.subscribe(SYMBOL)
    raw = {
        "kind": "orderbook",
        "symbol": SYMBOL,
        "timestamp": 1_788_600_000.0,
        "bids": [(100, 1)],
        "asks": [(101, 1)],
        "sequence": 1,
        "snapshot_or_delta": "snapshot",
        "continuity_status": "continuous",
        "event_id": "missing-clock",
    }
    api.poll_events = lambda *_args, **_kwargs: [raw]
    try:
        assert store.poll_orderbook(SYMBOL) is None
        health = store.get_stream_health(SYMBOL)
        assert health["stale"] is True
        assert health["last_drop_event_id"] == "missing-clock"
        assert health["last_drop_reason"] == "causal_provenance_missing_or_invalid"
        assert health["book_conservation"] is True
    finally:
        store.stop()


def test_snapshot_sequences_may_jump_without_assuming_plus_one_continuity():
    api = AsyncSdk()
    store = make_store(api, book_queue_size=4)
    store.start()
    store.subscribe(SYMBOL)
    api.events[VENUE].extend(
        [
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.0,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 100,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "continuous",
            },
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.1,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 250,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "continuous",
            },
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.2,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 400,
                "previous_sequence": 250,
                "snapshot_or_delta": "delta",
                "continuity_status": "continuous",
            },
        ]
    )
    try:
        books = [store.poll_orderbook(SYMBOL) for _ in range(3)]
        assert [book.sequence for book in books] == [100, 250, 400]
        health = store.get_stream_health(SYMBOL)
        assert health.get("sequence_gap", 0) == 0
        assert health["stale"] is False
    finally:
        store.stop()


def test_gap_remains_stale_until_a_verified_snapshot_recovers_the_book():
    api = AsyncSdk()
    store = make_store(api, book_queue_size=4)
    store.start()
    store.subscribe(SYMBOL)
    api.events[VENUE].extend(
        [
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.0,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 10,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "continuous",
            },
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.1,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 12,
                "previous_sequence": 11,
                "snapshot_or_delta": "delta",
                "continuity_status": "continuous",
            },
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.2,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 20,
                "previous_sequence": 12,
                "snapshot_or_delta": "delta",
                "continuity_status": "continuous",
            },
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.3,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 500,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "recovered",
            },
        ]
    )
    try:
        books = [store.poll_orderbook(SYMBOL) for _ in range(4)]
        assert [book.stale for book in books] == [False, True, True, False]
        assert books[1].stale_reason == "sequence_gap"
        assert books[2].stale_reason == "sequence_gap"
        assert store.get_stream_health(SYMBOL)["stale"] is False
    finally:
        store.stop()


def test_strategy_delivery_counts_one_causal_event_across_orderbook_and_bar_aliases():
    store = make_store(AsyncSdk())
    event = OrderBookSnapshot(
        timestamp=1_788_600_000.0,
        symbol=SYMBOL,
        bids=[(100, 1)],
        asks=[(101, 1)],
        event_id="shared-causal-event",
    )

    store.mark_strategy_delivered(event)
    store.mark_strategy_delivered(event)

    health = store.get_stream_health(SYMBOL)
    assert health["strategy_delivered"] == 1
    assert health["strategy_delivery_alias"] == 1


def test_typed_sdk_contracts_are_adapted_without_losing_decimal_or_freshness():
    api = TypedSdk()
    store = make_store(api)
    try:
        instrument = store.get_instrument_spec(SYMBOL)
        funding = store.get_funding_snapshot(SYMBOL)
        fee = store.get_fee_schedule(SYMBOL, account_id=api.account_id)
        readiness = store.get_trading_readiness(
            SYMBOL,
            Decimal("1"),
            expected_position_mode="dual_side",
            account_id=api.account_id,
        )

        assert instrument["multiplier"] == Decimal("0.01")
        assert instrument["lot_size"] == Decimal("1")
        assert instrument["freshness"]["source"] == "exchange"
        assert funding["rate"] == Decimal("0.0001")
        assert (
            funding["next_funding_time"]
            == dt.datetime(2026, 9, 7, 8, tzinfo=dt.timezone.utc).timestamp()
        )
        assert fee["taker_rate"] == Decimal("0.0005")
        assert readiness["ready"] is True
        assert readiness["reasons"] == []
        assert readiness["position_mode"] == "dual_side"
        assert {call[0] for call in api.calls} >= {
            "get_instrument_spec",
            "get_funding_snapshot",
            "get_fee_schedule",
            "get_trading_readiness",
        }
    finally:
        store.stop()


def test_causal_event_fields_preserve_legacy_positional_constructor_order():
    tick = TickEvent(1.0, SYMBOL, VENUE, "swap", None, 100.0, 2.0, "sell")
    book = OrderBookSnapshot(
        1.0,
        SYMBOL,
        VENUE,
        "swap",
        None,
        [(100.0, 1.0)],
        [(101.0, 1.0)],
    )
    funding = FundingEvent(1.0, SYMBOL, VENUE, "swap", None, 0.001, 100.0, 2.0, 0.002)
    bar = BarEvent(1.0, SYMBOL, VENUE, "swap", None, 99.0, 101.0, 98.0, 100.0, 10.0, 3.0)

    assert (tick.price, tick.volume, tick.direction) == (100.0, 2.0, "sell")
    assert (book.best_bid, book.best_ask) == (100.0, 101.0)
    assert (funding.rate, funding.mark_price) == (0.001, 100.0)
    assert (bar.open, bar.high, bar.low, bar.close) == (99.0, 101.0, 98.0, 100.0)
    for event in (tick, book, funding, bar):
        assert event.exchange_time == event.timestamp
        assert event.received_monotonic_ns > 0
        assert event.event_id


@pytest.mark.parametrize("position_mode", ["net", "unknown"])
def test_sdk_broker_preflight_fails_before_any_write(position_mode):
    api = AsyncSdk(position_mode=position_mode)
    store = make_store(api)
    broker = store.getbroker(position_mode="dual_side")
    try:
        with pytest.raises(ValueError, match="position mode"):
            broker.start()
        assert not [row for row in api.calls if row[0] == "submit"]
    finally:
        store.stop()


def test_sdk_broker_startup_rejects_nonzero_remote_position():
    api = AsyncSdk()
    api.positions = [
        {
            "symbol": SYMBOL,
            "quantity": "1",
            "quantity_known": True,
            "position_side": "long",
            "price": "100",
        }
    ]
    store = make_store(api)
    broker = store.getbroker(
        position_mode="dual_side",
        sdk_preflight=False,
        validation_enabled=False,
        force_refresh_queries=False,
    )
    try:
        with pytest.raises(ValueError, match="execution state is not proven clean and flat"):
            broker.start()
        assert broker._startup_ready is False
        assert broker._trading_enabled is False
        assert store.get_command_health()["accepting_openings"] is False
        assert broker.getposition(SimpleNamespace(_name=SYMBOL), side="long").size == 0

        api.positions = []
        broker.start()
        assert broker._startup_ready is True
        assert broker._trading_enabled is True
        assert broker.getposition(SimpleNamespace(_name=SYMBOL), side="long").size == 0
        broker.stop()
    finally:
        store.stop()


def _started_broker(api):
    store = make_store(api)
    data = store.getdata(
        dataname=SYMBOL,
        historical_bars=[
            {
                "datetime": dt.datetime(2026, 9, 1),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 1,
                "openinterest": 0,
            }
        ],
    )
    data._start()
    assert data.load()
    broker = store.getbroker(
        position_mode="dual_side",
        position_sync_policy="startup",
        force_refresh_queries=False,
        account_refresh_interval=3600,
        positions_refresh_interval=3600,
        open_orders_refresh_interval=3600,
    )
    broker.addcommissioninfo(
        bt.ComminfoFuturesPercent(commission=0, mult=1, margin=1),
        name=SYMBOL,
    )
    broker.start()
    return store, broker, data


def test_broker_keeps_submitted_until_private_order_event():
    api = AsyncSdk()
    store, broker, data = _started_broker(api)
    try:
        order = broker.buy(
            None,
            data,
            size=1,
            price=100,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        assert order.status == bt.Order.Submitted
        assert store.wait_for_commands(1)
        broker.next()
        assert order.status == bt.Order.Submitted

        api.events[VENUE].append(
            {
                "kind": "order",
                "symbol": SYMBOL,
                "client_order_id": order.info["client_order_id"],
                "order_id": order.info["client_order_id"],
                "status": "accepted",
            }
        )
        broker.next()
        assert order.status == bt.Order.Accepted
    finally:
        broker.stop()


def test_broker_reconciles_unknown_result_mapping_with_original_client_id():
    class UnknownResultSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.release_query = False

        async def async_make_order(self, venue, request, *, normalized=False):
            assert normalized
            self.calls.append(("submit", request.client_order_id, False, "open", "long"))
            return {
                "kind": "order",
                "symbol": request.symbol,
                "client_order_id": request.client_order_id,
                "status": "submitted",
                "execution_unknown": True,
                "error_code": "transport_timeout",
            }

        async def async_query_order(self, venue, request, *, normalized=False):
            assert normalized
            self.calls.append(("query", request.client_order_id, False))
            while not self.release_query:
                await asyncio.sleep(0.001)
            return {
                "kind": "order",
                "symbol": request.symbol,
                "client_order_id": request.client_order_id,
                "order_id": "venue-1",
                "status": "canceled",
                "terminal_confirmed": True,
            }

    api = UnknownResultSdk()
    store, broker, data = _started_broker(api)
    try:
        order = broker.buy(
            None,
            data,
            size=1,
            price=100,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        client_id = order.info["client_order_id"]
        assert store.wait_for_commands(1)
        broker.next()
        assert order.alive() and order.info["execution_unknown"] is True
        assert order.info["reconcile_requested"] is True

        api.release_query = True
        assert store.wait_for_commands(1)
        broker.next()
        assert order.status == bt.Order.Canceled
        assert order.info["execution_unknown"] is False
        query = next(row for row in api.calls if row[0] == "query")
        assert query[1] == client_id
    finally:
        api.release_query = True
        broker.stop()


def test_unclassified_submit_transport_error_stays_live_and_reconciles_original_id():
    class UnclassifiedTransportSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.release_query = False

        async def async_make_order(self, venue, request, *, normalized=False):
            assert normalized
            self.calls.append(("submit", request.client_order_id, False))
            raise ConnectionError("connection reset after possible write")

        async def async_query_order(self, venue, request, *, normalized=False):
            assert normalized
            self.calls.append(("query", request.client_order_id, False))
            while not self.release_query:
                await asyncio.sleep(0.001)
            return {
                "kind": "order",
                "symbol": request.symbol,
                "client_order_id": request.client_order_id,
                "status": "canceled",
                "terminal_confirmed": True,
            }

    api = UnclassifiedTransportSdk()
    store, broker, data = _started_broker(api)
    try:
        order = broker.buy(
            None,
            data,
            size=1,
            price=100,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        client_id = order.info["client_order_id"]
        assert store.wait_for_commands(1)
        broker.next()
        assert order.alive() and order.info["execution_unknown"] is True
        assert broker._order_for_client_ref(client_id, {"exchange_name": VENUE}) is order
        deadline = time.monotonic() + 1
        while not any(row[0] == "query" for row in api.calls) and time.monotonic() < deadline:
            time.sleep(0.001)
        assert next(row for row in api.calls if row[0] == "query")[1] == client_id
    finally:
        api.release_query = True
        broker.stop()


def test_shutdown_flattens_only_known_leg_and_requires_remote_flat_proof():
    api = AsyncSdk()
    store, broker, data = _started_broker(api)
    order = broker.buy(
        None,
        data,
        size=1,
        price=100,
        exectype=bt.Order.Limit,
        position_side="long",
        offset="open",
    )
    assert store.wait_for_commands(1)
    broker.next()
    api.positions = [
        {
            "symbol": SYMBOL,
            "quantity": 1,
            "quantity_known": True,
            "position_side": "long",
            "price": 100,
        }
    ]
    api.events[VENUE].append(
        {
            "kind": "trade",
            "symbol": SYMBOL,
            "client_order_id": order.info["client_order_id"],
            "order_id": order.info["client_order_id"],
            "trade_id": "opened-before-shutdown",
            "side": "buy",
            "position_side": "long",
            "offset": "open",
            "position_mode": "dual_side",
            "quantity_unit": "contracts",
            "size": "1",
            "price": "100",
        }
    )
    broker.next()
    assert broker.getposition(data, side="long").size == 1
    summary = broker.stop()

    close_calls = [row for row in api.calls if row[0] == "submit" and row[2] is True]
    assert len(close_calls) == 1
    assert close_calls[0][3:] == ("close", "long")
    assert summary["status"] == "PASS"
    assert summary["reason"] == "remote_flat_proven"


@pytest.mark.parametrize(
    "summary_change",
    [
        {"active_orders": 1},
        {"fee_unresolved_orders": ["order-1"]},
        {"funding_unresolved_orders": ["order-1"]},
        {"evidence_complete": False},
        {"evidence_errors": ["incomplete"]},
        {"reconciliation_errors": {"order-1": "timeout"}},
        {"generation": 2},
        {"fencing_epoch": 2},
    ],
)
def test_broker_flat_proof_rejects_unsettled_or_unfenced_execution_summary(summary_change):
    store = make_store(AsyncSdk())
    broker = store.getbroker(position_mode="dual_side")
    identity_binding_sha256 = "b" * 64
    summary_as_of_monotonic_ns = time.monotonic_ns()
    summary = {
        "session_enabled": True,
        "unknown_ids": [],
        "active_orders": 0,
        "fee_unresolved_orders": [],
        "funding_unresolved_orders": [],
        "trading_blocked": False,
        "reconciliation_errors": {},
        "evidence_complete": True,
        "evidence_errors": [],
        "generation": 1,
        "session_generation": 1,
        "fencing_epoch": 1,
        "as_of_monotonic_ns": summary_as_of_monotonic_ns,
        "identity_binding_sha256": identity_binding_sha256,
    }
    result = {
        "configured_venues": ["okx"],
        "reconciled_venues": ["okx"],
        "positions": [],
        "open_orders": [],
        "unknown_ids": [],
        "trading_blocked": False,
        "evidence_complete": True,
        "evidence_errors": [],
        "generation": 1,
        "session_generation": 1,
        "fencing_epoch": 1,
        "as_of_monotonic_ns": time.monotonic_ns(),
        "identity_binding_sha256": identity_binding_sha256,
        "execution_summary": summary,
    }
    assert broker._reconcile_proves_flat(result) is True
    summary.update(summary_change)
    assert broker._reconcile_proves_flat(result) is False


@pytest.mark.parametrize(
    "position_row",
    [
        {"quantity": True, "quantity_known": True},
        {"quantity": 0, "quantity_known": False},
        {"quantity_known": True},
        "not-a-position-mapping",
    ],
)
def test_broker_flat_proof_rejects_unknown_or_non_numeric_position_quantity(position_row):
    store = make_store(AsyncSdk())
    store.start()
    try:
        broker = store.getbroker(position_mode="dual_side", sdk_preflight=False)
        snapshot = store._sdk_reconcile_snapshot()
        assert broker._reconcile_proves_flat(snapshot) is True
        snapshot["positions"] = [position_row]
        assert broker._reconcile_proves_flat(snapshot) is False
    finally:
        store.stop()


def test_sdk_reconcile_filters_only_proven_zero_query_position_snapshots():
    api = AsyncSdk()
    api.positions = [
        {
            "symbol": SYMBOL,
            "quantity": "0.000",
            "quantity_known": True,
            "quantity_exact_zero": True,
            "position_side": "long",
        },
        {
            "symbol": "ETH-USDT-SWAP",
            "quantity": 0,
            "quantity_known": False,
            "position_side": "long",
        },
        {
            "symbol": "SOL-USDT-SWAP",
            "quantity": "0.25",
            "quantity_known": True,
            "quantity_exact_zero": False,
            "position_side": "short",
        },
        {
            "symbol": "XRP-USDT-SWAP",
            "quantity": Decimal("1E-400"),
            "quantity_known": True,
            "quantity_exact_zero": False,
            "position_side": "long",
        },
    ]
    store = make_store(api)
    store.start()
    try:
        snapshot = store._sdk_reconcile_snapshot()
        assert [row["symbol"] for row in snapshot["positions"]] == [
            "ETH-USDT-SWAP",
            "SOL-USDT-SWAP",
            "XRP-USDT-SWAP",
        ]
        assert snapshot["positions"][0]["quantity_known"] is False
    finally:
        store.stop()


def test_logger_sink_failure_only_increments_health(monkeypatch):
    api = AsyncSdk()
    store = make_store(api)
    broker = store.getbroker(position_mode="dual_side")
    before = broker.get_logging_health().get("logging_errors", 0)

    def broken_sink(*_args, **_kwargs):
        raise RuntimeError("sink failed")

    monkeypatch.setattr(broker_module.logger, "warning", broken_sink)
    broker_module._safe_log("warning", "safe")

    assert broker.get_logging_health()["logging_errors"] == before + 1


def test_shutdown_deadline_discards_unsent_commands_and_isolates_late_completion():
    api = AsyncSdk(block_first=True)
    store = make_store(api, command_shutdown_timeout=0.01)
    store.start()
    first = store.submit_order(local_order(101))
    deadline = time.monotonic() + 1
    while not [row for row in api.calls if row[0] == "submit"] and time.monotonic() < deadline:
        time.sleep(0.001)
    second = store.submit_order(local_order(102))

    assert first["queued"] and second["queued"]
    health = store.stop(timeout=0.01)
    assert health["shutdown_state"] == "INCOMPLETE"
    assert health["discarded_unsent"] == 1
    assert health["command_drop_records"][-1]["bt_order_ref"] == 102
    assert health["restart_blocked_by_worker"] is True
    with pytest.raises(BtApiStoreError, match="previous SDK command worker"):
        store.start()

    api.release = True
    deadline = time.monotonic() + 1
    while store.get_command_health()["worker_alive"] and time.monotonic() < deadline:
        time.sleep(0.001)
    assert not store.get_command_health()["worker_alive"]
    assert len([row for row in api.calls if row[0] == "submit"]) == 1
    health = store.get_command_health()
    assert health["late_completion_dropped"] == 1
    assert health["broker_update_conservation"] is True

    store.start()
    try:
        assert store.get_command_health()["session_generation"] == 2
        assert store.poll_broker_update() is None
    finally:
        store.stop()


def test_broker_update_queue_records_evicted_identity_and_conserves_updates():
    store = make_store(AsyncSdk(), broker_update_queue_size=2)
    store.start()
    try:
        for index in range(3):
            store._append_sdk_update(
                {
                    "kind": "order",
                    "client_order_id": f"client-{index}",
                    "exchange_name": VENUE,
                    "status": "accepted",
                }
            )
        update = store.poll_broker_update()
        assert update["client_order_id"] == "client-1"
        health = store.get_command_health()
        assert health["broker_update_ingress"] == 3
        assert health["broker_update_delivered"] == 1
        assert health["broker_update_dropped"] == 1
        assert health["broker_update_queue_depth"] == 1
        assert health["broker_update_conservation"] is True
        assert health["risk_state_latched"] is True
        assert health["broker_update_drop_records"][-1]["client_order_id"] == "client-0"

        assert store.poll_broker_update()["client_order_id"] == "client-2"
        snapshot = store.get_reconcile_snapshot()
        assert snapshot["evidence_complete"] is True
        recovered = store.get_command_health()
        assert recovered["broker_update_dropped"] == 1
        assert recovered["risk_state_latched"] is False
        assert recovered["broker_update_conservation"] is True
    finally:
        store.stop()


def test_stale_reconcile_cannot_clear_a_newer_risk_incident():
    store = make_store(AsyncSdk())
    store.start()
    try:
        first_epoch = store._latch_risk_state_unknown("first_incident")
        stale_snapshot = store._sdk_reconcile_snapshot()
        second_epoch = store._latch_risk_state_unknown("newer_incident")

        assert second_epoch > first_epoch
        assert (
            store._maybe_clear_risk_state_latch(stale_snapshot, incident_epoch=first_epoch) is False
        )
        health = store.get_command_health()
        assert health["risk_state_latched"] is True
        assert health["risk_incident_epoch"] == second_epoch
        assert health["last_risk_incident_reason"] == "newer_incident"

        fresh_snapshot = store._sdk_reconcile_snapshot()
        assert (
            store._maybe_clear_risk_state_latch(fresh_snapshot, incident_epoch=second_epoch) is True
        )
        assert store.get_command_health()["risk_state_latched"] is False
    finally:
        store.stop()


def test_reconcile_completion_cannot_clear_while_a_different_command_is_inflight():
    store = make_store(AsyncSdk())
    store.start()
    try:
        incident_epoch = store._latch_risk_state_unknown("execution_unknown")
        snapshot = store._sdk_reconcile_snapshot()
        with store._command_condition:
            store._command_inflight = 1
            store._command_inflight_receipt_id = "next-query"
            store._command_inflight_operation = "query"

        assert (
            store._maybe_clear_risk_state_latch(
                snapshot,
                incident_epoch=incident_epoch,
                allow_current_reconcile_inflight=True,
                current_reconcile_receipt_id="completed-reconcile",
            )
            is False
        )
        assert store.get_command_health()["risk_state_latched"] is True
    finally:
        with store._command_condition:
            store._command_inflight = 0
            store._command_inflight_receipt_id = None
            store._command_inflight_operation = None
        store.stop()


def test_orderbook_queue_overflow_records_evicted_causal_identity():
    api = AsyncSdk()
    store = make_store(api, book_queue_size=1)
    store.start()
    store.subscribe(SYMBOL)
    api.events[VENUE].extend(
        [
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.0 + index,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": index + 1,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "continuous",
                "event_id": f"book-{index}",
            }
            for index in range(2)
        ]
    )
    try:
        book = store.poll_orderbook(SYMBOL)
        health = store.get_stream_health(SYMBOL)
        assert book.event_id == "book-1"
        assert book.stale is True
        assert health["last_drop_event_id"] == "book-0"
        assert health["last_enqueued_event_id"] == "book-1"
        assert health["last_drop_kind"] == "orderbook"
    finally:
        store.stop()


def test_sdk_missing_one_async_method_fails_closed_without_sync_fallback():
    class IncompleteSdk(AsyncSdk):
        async_cancel_order = None

        def make_order(self, *_args, **_kwargs):
            raise AssertionError("synchronous submit fallback is forbidden")

        def cancel_order(self, *_args, **_kwargs):
            raise AssertionError("synchronous cancel fallback is forbidden")

    api = IncompleteSdk()
    store = make_store(api)
    store.start()
    try:
        with pytest.raises(BtApiStoreError, match="async_cancel_order"):
            store.submit_order(local_order())
        with pytest.raises(BtApiStoreError, match="async_cancel_order"):
            store.cancel_order_ref("client-1", dataname=SYMBOL)
        broker = store.getbroker(position_mode="dual_side", sdk_preflight=False)
        with pytest.raises(ValueError, match="async_make_order.*async_cancel_order"):
            broker.start()
        assert not [row for row in api.calls if row[0] in {"submit", "cancel"}]
    finally:
        store.stop()


def test_sdk_client_reference_is_venue_scoped_and_bt_ref_wins():
    store = make_store(AsyncSdk())
    store._sdk_exchanges["BINANCE___USDT_FUTURES"] = {"environment": "demo"}
    broker = store.getbroker(position_mode="dual_side", sdk_preflight=False)
    okx_order = SimpleNamespace(data=SimpleNamespace(_name=SYMBOL))
    binance_order = SimpleNamespace(data=SimpleNamespace(_name="BTCUSDT"))
    broker.orders = {1: okx_order, 2: binance_order}
    broker._remember_client_ref(okx_order, "7", {"exchange_name": VENUE})
    broker._remember_client_ref(binance_order, "7", {"exchange_name": "BINANCE___USDT_FUTURES"})
    broker._orders_by_external_id["shared"] = okx_order

    assert broker._lookup_order({"exchange_name": VENUE, "client_order_id": "7"}) is okx_order
    assert (
        broker._lookup_order({"exchange_name": "BINANCE___USDT_FUTURES", "client_order_id": "7"})
        is binance_order
    )
    assert broker._lookup_order({"exchange_name": VENUE, "client_order_id": "1"}) is None
    assert (
        broker._lookup_order(
            {
                "exchange_name": "BINANCE___USDT_FUTURES",
                "client_order_id": "missing",
                "order_id": "shared",
            }
        )
        is None
    )
    assert (
        broker._lookup_order(
            {
                "bt_order_ref": "1",
                "exchange_name": "BINANCE___USDT_FUTURES",
                "client_order_id": "7",
            }
        )
        is okx_order
    )


def test_recursive_runtime_redaction_covers_events_logs_and_exceptions(monkeypatch):
    secret = "sensitive-demo-secret"
    store = make_store(AsyncSdk(), credentials={"api_key": secret})
    event = store.emit_runtime_event(
        "redaction_probe",
        error_msg=f"request failed with {secret}",
        details={
            "nested": {"password": secret},
            "headers": [f"Authorization: Bearer {secret}"],
            "errors": [RuntimeError(secret)],
        },
    )
    assert secret not in repr(event)
    assert event["details"]["nested"]["password"] == "***"
    assert event["details"]["errors"] == ["RuntimeError"]

    error = RuntimeError({"token": secret}, f"transport leaked {secret}")
    store.sanitize_exception(error)
    assert secret not in repr(error)

    captured = []
    monkeypatch.setattr(broker_module.logger, "warning", lambda *args: captured.append(args))
    broker_module._safe_log("warning", "failure: %s", {"api_secret": secret})
    monkeypatch.setattr(feed_module.logger, "debug", lambda *args: captured.append(args))
    nested = SimpleNamespace(
        api_secret=secret,
        url=(
            "https://demo.invalid/private?signature=ephemeral-signature"
            "&listenKey=ephemeral-listen"
        ),
    )
    nested.child = nested
    feed_module._safe_log("debug", "failure: %s", nested)
    assert secret not in repr(captured)
    assert "ephemeral-signature" not in repr(captured)
    assert "ephemeral-listen" not in repr(captured)
    assert "<recursive>" in repr(captured)


def test_feed_emits_one_live_transition_per_stale_recovery():
    store = make_store(AsyncSdk())
    feed = store.getdata(dataname=SYMBOL, timeframe=bt.TimeFrame.Ticks)
    assert feed._handle_event_health(
        {"stale": True, "continuity_status": "gap", "event_id": "gap-1"}
    )
    assert not feed._handle_event_health(
        {"stale": False, "continuity_status": "recovered", "event_id": "book-2"}
    )
    assert not feed._handle_event_health(
        {"stale": False, "continuity_status": "continuous", "event_id": "book-3"}
    )
    statuses = [status for status, _args, _kwargs in feed.get_notifications()]
    assert statuses == [feed.DELAYED, feed.LIVE]


@pytest.mark.parametrize("operation", ("_load", "_check"))
def test_feed_drain_does_not_mark_gap_live_until_verified_recovery(operation):
    store = make_store(AsyncSdk())
    feed = store.getdata(dataname=SYMBOL, timeframe=bt.TimeFrame.Ticks)
    feed._start()
    rows = deque([{"stale": True, "continuity_status": "gap", "event_id": "gap-1"}])
    store.poll_tick = lambda _symbol: None
    store.poll_orderbook = lambda _symbol: rows.popleft() if rows else None
    feed._qcheck = 0
    try:
        getattr(feed, operation)()
        statuses = [
            status
            for status, _args, _kwargs in feed.get_notifications()
            if status in {feed.DELAYED, feed.LIVE}
        ]
        assert statuses == [feed.DELAYED]

        rows.append(
            {
                "stale": False,
                "continuity_status": "recovered",
                "event_id": "snapshot-2",
            }
        )
        getattr(feed, operation)()
        statuses.extend(
            status
            for status, _args, _kwargs in feed.get_notifications()
            if status in {feed.DELAYED, feed.LIVE}
        )
        assert statuses == [feed.DELAYED, feed.LIVE]
    finally:
        store.stop()


def test_cancel_unknown_query_live_allows_retry_but_blocks_new_opening():
    class CancelUnknownSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.query_status = "accepted"

        async def async_cancel_order(self, venue, request, *, normalized=False):
            assert normalized
            self.calls.append(("cancel", request.client_order_id, False))
            raise TimeoutError("api_key=sensitive-demo-secret")

        async def async_query_order(self, venue, request, *, normalized=False):
            assert normalized
            self.calls.append(("query", request.client_order_id, False))
            return {
                "kind": "order",
                "symbol": request.symbol,
                "client_order_id": request.client_order_id,
                "order_id": request.order_id,
                "status": self.query_status,
                "terminal_confirmed": self.query_status == "canceled",
            }

    api = CancelUnknownSdk()
    store, broker, data = _started_broker(api)
    try:
        order = broker.buy(
            None,
            data,
            size=1,
            price=100,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        assert store.wait_for_commands(1)
        broker.next()

        broker.cancel(order)
        assert store.wait_for_commands(1)
        broker.next()
        assert store.wait_for_commands(1)
        broker.next()
        assert order.info["cancel_execution_unknown"] is False
        assert order.info["cancel_requested_remote"] is True
        assert order.info["cancel_intent_active"] is True
        assert order.info["cancel_retry_attempts"] == 2

        blocked = broker.buy(
            None,
            data,
            size=1,
            price=99,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        assert blocked.status == bt.Order.Rejected
        assert blocked.info["error_code"] == "cancel_intent_active"

        broker.cancel(order)
        assert store.wait_for_commands(1)
        assert len([row for row in api.calls if row[0] == "cancel"]) == 2
        api.query_status = "canceled"
        broker.next()
        assert store.wait_for_commands(1)
        broker.next()
        assert order.status == bt.Order.Canceled
        state = broker.get_order_reconciliation_state(order)
        assert state["execution_unknown"] is False
        assert state["cancel_execution_unknown"] is False
        assert state["cancel_intent_active"] is False
    finally:
        api.query_status = "canceled"
        broker.stop()


def test_next_without_bar_enforces_execution_and_cancel_deadlines():
    class BlockingCancelSdk(AsyncSdk):
        async def async_cancel_order(self, venue, request, *, normalized=False):
            assert normalized
            self.calls.append(("cancel", request.client_order_id, False))
            while not self.release:
                await asyncio.sleep(0.001)
            return {
                "kind": "order",
                "symbol": request.symbol,
                "client_order_id": request.client_order_id,
                "order_id": request.order_id,
                "status": "submitted",
            }

    api = BlockingCancelSdk()
    store, broker, data = _started_broker(api)
    try:
        order = broker.buy(
            None,
            data,
            size=1,
            price=100,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
            execution_deadline_monotonic_ns=time.monotonic_ns() - 1,
            cancel_timeout_ns=1_000_000,
        )
        assert store.wait_for_commands(1)
        broker.next()
        deadline = time.monotonic() + 1
        while not [row for row in api.calls if row[0] == "cancel"] and time.monotonic() < deadline:
            time.sleep(0.001)
        assert len([row for row in api.calls if row[0] == "cancel"]) == 1
        time.sleep(0.005)

        broker.next()
        broker.next()
        assert order.info["execution_deadline_cancel_requested"] is True
        assert order.info["cancel_execution_unknown"] is True
        assert order.info["cancel_deadline_unknown_marked"] is True
        assert len([row for row in api.calls if row[0] == "cancel"]) == 1
    finally:
        api.release = True
        broker.stop()


def test_cancel_confirmation_before_deadline_stays_definitive():
    class DefinitiveCancelSdk(AsyncSdk):
        async def async_query_order(self, venue, request, *, normalized=False):
            assert normalized
            self.calls.append(("query", request.client_order_id, False))
            return {
                "kind": "order",
                "symbol": request.symbol,
                "client_order_id": request.client_order_id,
                "order_id": request.order_id,
                "status": "canceled",
                "terminal_confirmed": True,
            }

    api = DefinitiveCancelSdk()
    store, broker, data = _started_broker(api)
    try:
        order = broker.buy(
            None,
            data,
            size=1,
            price=100,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
            execution_deadline_monotonic_ns=time.monotonic_ns() - 1,
            cancel_timeout_seconds=1,
        )
        assert store.wait_for_commands(1)
        broker.next()
        assert store.wait_for_commands(1)
        broker.next()
        assert store.wait_for_commands(1)
        broker.next()
        assert order.status == bt.Order.Canceled
        assert order.info["cancel_execution_unknown"] is False
        assert len([row for row in api.calls if row[0] == "cancel"]) == 1
    finally:
        broker.stop()


def test_sdk_write_contract_rejects_sync_named_methods_and_non_mapping_results():
    class SyncNamedSdk(AsyncSdk):
        def async_make_order(self, *_args, **_kwargs):
            return {}

        def async_cancel_order(self, *_args, **_kwargs):
            return {}

        def async_query_order(self, *_args, **_kwargs):
            return {}

    sync_store = make_store(SyncNamedSdk())
    sync_store.start()
    try:
        assert sync_store.uses_async_commands is False
        with pytest.raises(BtApiStoreError, match="async_make_order"):
            sync_store.submit_order(local_order())
    finally:
        sync_store.stop()

    class NullResultSdk(AsyncSdk):
        async def async_make_order(self, venue, request, *, normalized=False):
            assert normalized

    null_store = make_store(NullResultSdk())
    null_store.start()
    try:
        assert null_store.submit_order(local_order())["queued"] is True
        assert null_store.wait_for_commands(1)
        completion = null_store.poll_broker_update()
        assert completion["success"] is False
        assert completion["status"] == "unknown"
        assert completion["execution_unknown"] is True
        assert completion["error_code"] == "BtApiStoreError"
    finally:
        null_store.stop()


def test_invalid_recovery_snapshot_remains_stale_and_is_conserved():
    api = AsyncSdk()
    store = make_store(api)
    store.start()
    store.subscribe(SYMBOL)
    api.events[VENUE].extend(
        [
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.0,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 10,
                "previous_sequence": 9,
                "snapshot_or_delta": "delta",
                "continuity_status": "gap",
                "event_id": "gap-book",
            },
            {
                "kind": "orderbook",
                "symbol": SYMBOL,
                "timestamp": 1_788_600_000.1,
                "bids": [(102, 1)],
                "asks": [(101, 1)],
                "sequence": 20,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "recovered",
                "event_id": "bad-recovery",
            },
        ]
    )
    try:
        first = store.poll_orderbook(SYMBOL)
        assert first.event_id == "gap-book" and first.stale is True
        assert store.poll_orderbook(SYMBOL) is None
        health = store.get_stream_health(SYMBOL)
        assert health["stale"] is True
        assert health["stale_reason"] == "invalid_orderbook_snapshot"
        assert health["last_drop_event_id"] == "bad-recovery"
        assert health["book_dropped"] == 1
        assert health["book_feed_inflight"] == 1
        assert health["book_conservation"] is True
        assert store._sdk_sequences[(VENUE, SYMBOL)] == 10
    finally:
        store.stop()


@pytest.mark.parametrize(
    ("event_changes", "expected_reason"),
    [
        ({"sequence": None}, "orderbook_sequence_missing_or_invalid"),
        ({"sequence": 0}, "orderbook_sequence_missing_or_invalid"),
        ({"continuity_status": "unknown"}, "orderbook_continuity_missing_or_invalid"),
        ({"continuity_status": "unverified"}, "orderbook_continuity_missing_or_invalid"),
        (
            {"snapshot_or_delta": None},
            "orderbook_snapshot_kind_missing_or_invalid",
        ),
    ],
)
def test_unverified_orderbook_identity_is_dropped_and_latches_stale(event_changes, expected_reason):
    api = AsyncSdk()
    store = make_store(api)
    store.start()
    store.subscribe(SYMBOL)
    raw = {
        "kind": "orderbook",
        "symbol": SYMBOL,
        "timestamp": 1_788_600_000.0,
        "bids": [(100, 1)],
        "asks": [(101, 1)],
        "sequence": 1,
        "snapshot_or_delta": "snapshot",
        "continuity_status": "snapshot",
        "event_id": "unverified-book",
    }
    raw.update(event_changes)
    api.events[VENUE].append(raw)
    try:
        assert store.poll_orderbook(SYMBOL) is None
        health = store.get_stream_health(SYMBOL)
        assert health["stale"] is True
        assert health["last_drop_event_id"] == "unverified-book"
        assert health["last_drop_reason"] == expected_reason
        assert health["book_conservation"] is True
    finally:
        store.stop()


def test_polled_book_has_terminal_drop_evidence_when_strategy_dispatch_is_unavailable():
    api = AsyncSdk()
    store = make_store(api)
    store.start()
    store.subscribe(SYMBOL)
    api.events[VENUE].append(
        {
            "kind": "orderbook",
            "symbol": SYMBOL,
            "timestamp": 1_788_600_000.0,
            "bids": [(100, 1)],
            "asks": [(101, 1)],
            "sequence": 1,
            "snapshot_or_delta": "snapshot",
            "continuity_status": "continuous",
            "event_id": "undispatched-book",
        }
    )
    try:
        book = store.poll_orderbook(SYMBOL)
        assert store.get_stream_health(SYMBOL)["book_conservation"] is True
        store.mark_feed_dropped(book, "strategy_dispatch_unavailable")
        health = store.get_stream_health(SYMBOL)
        assert health["book_feed_inflight"] == 0
        assert health["book_dropped"] == 1
        assert health["book_conservation"] is True
        assert health["market_drop_records"][-1] == {
            "event_id": "undispatched-book",
            "kind": "orderbook",
            "reason": "strategy_dispatch_unavailable",
            "safety_impact": "event_not_visible_to_strategy",
            "stream_generation": 1,
        }
    finally:
        store.stop()


def test_close_timeout_blocks_restart_until_close_generation_exits():
    release = threading.Event()
    close_started = threading.Event()

    class SlowCloseSdk(AsyncSdk):
        def close(self):
            close_started.set()
            release.wait(1)
            self.closed = True

    api = SlowCloseSdk()
    store = make_store(api, command_shutdown_timeout=0.01)
    store.start()
    health = store.stop(timeout=0.01)
    assert close_started.is_set()
    assert health["shutdown_state"] == "INCOMPLETE"
    assert health["close_thread_alive"] is True
    assert health["restart_blocked_by_close"] is True
    with pytest.raises(BtApiStoreError, match="close callback"):
        store.start()

    release.set()
    deadline = time.monotonic() + 1
    while store.get_command_health()["close_thread_alive"] and time.monotonic() < deadline:
        time.sleep(0.001)
    store.start()
    try:
        assert store.get_command_health()["session_generation"] == 2
        assert store.get_command_health()["restart_blocked_by_close"] is False
    finally:
        store.stop()


def test_broker_pass_requires_complete_sdk_evidence_and_store_pass(monkeypatch):
    class UnknownSdk(AsyncSdk):
        def get_execution_summary(self):
            return {
                "session_enabled": True,
                "unknown_ids": ["persisted-unknown"],
                "trading_blocked": True,
            }

    store = make_store(UnknownSdk())
    broker = store.getbroker(position_mode="dual_side", sdk_preflight=False)
    try:
        with pytest.raises(ValueError, match="execution state is not proven clean and flat"):
            broker.start()
        assert broker._startup_ready is False
        assert broker._trading_enabled is False
        assert store.get_command_health()["accepting_openings"] is False
    finally:
        store.stop()

    store, broker, _ = _started_broker(AsyncSdk())
    original_stop = store.stop
    monkeypatch.setattr(
        store,
        "stop",
        lambda timeout=None: {"shutdown_state": "INCOMPLETE", "close_timeouts": 1},
    )
    try:
        summary = broker.stop()
        assert summary["status"] == "INCOMPLETE"
        assert summary["reason"] == "store_shutdown_incomplete"
        assert summary["store_shutdown_state"] == "INCOMPLETE"
    finally:
        monkeypatch.setattr(store, "stop", original_stop)
        original_stop()


def test_reconcile_snapshot_is_complete_public_copy_and_redacted():
    store = make_store(AsyncSdk())
    store.start()
    broker = store.getbroker(position_mode="dual_side", sdk_preflight=False)
    try:
        snapshot = store._sdk_reconcile_snapshot()
        snapshot["diagnostic_url"] = (
            "https://demo.invalid/private?signature=ephemeral-signature"
            "&listenKey=ephemeral-listen"
        )
        broker._last_reconcile_result = snapshot
        public = broker.get_last_reconcile_result()
        assert public["evidence_complete"] is True
        assert public["configured_venues"] == public["reconciled_venues"] == ["okx"]
        assert public["unknown_ids"] == [] and public["trading_blocked"] is False
        assert public["ledger_partitions"][VENUE] == {
            "provider": "OKX",
            "environment": "demo",
            "account_id": f"okx-credential-{'a' * 64}",
            "strategy_id": "test",
        }
        assert public["as_of"] and public["as_of_monotonic_ns"] > 0
        assert public["generation"] == public["session_generation"] == 1
        assert public["fencing_epoch"] == 1
        assert public["execution_summary"]["generation"] == 1
        assert public["execution_summary"]["fencing_epoch"] == 1
        assert public["execution_identities"][VENUE]["fencing_epoch"] == 1
        assert "ephemeral-signature" not in repr(public)
        assert "ephemeral-listen" not in repr(public)
        public["positions"].append({"quantity": 999})
        assert broker.get_last_reconcile_result()["positions"] == []
    finally:
        store.stop()


def test_required_account_risk_refresh_precedes_and_binds_reconcile_summary():
    class RiskRefreshSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.risk_refreshed = False
            self.risk_reads = 0
            self.reconcile_events = []

        def get_account_risk_snapshot(self):
            self.reconcile_events.append("risk")
            self.risk_reads += 1
            self.risk_refreshed = True
            return account_risk_payload(self)

        def get_execution_summary(self):
            self.reconcile_events.append(f"summary:{self.risk_refreshed}")
            summary = super().get_execution_summary()
            if not self.risk_refreshed:
                summary.update(
                    evidence_complete=False,
                    trading_blocked=True,
                    evidence_errors=["account_risk_snapshot_refresh_required"],
                )
            return summary

    api = RiskRefreshSdk()
    store = make_store(api, require_account_risk=True)
    store.start()
    try:
        snapshot = store._sdk_reconcile_snapshot()

        assert api.reconcile_events == ["risk", "summary:True"]
        assert snapshot["evidence_complete"] is True
        assert snapshot["trading_blocked"] is False
        assert snapshot["account_risk_snapshot"]["evidence_complete"] is True
        assert snapshot["account_risk_snapshot"]["durable"] is True
        assert snapshot["account_risk_snapshot"]["trading_blocked"] is False
        assert (
            snapshot["account_risk_snapshot"]["identity_binding_sha256"]
            == snapshot["identity_binding_sha256"]
        )
        assert snapshot["account_risk_snapshot"]["fencing_epoch"] == snapshot["fencing_epoch"]

        cached = store.get_account_risk_snapshot()
        assert cached == snapshot["account_risk_snapshot"]
        assert api.risk_reads == 1
    finally:
        store.stop()


def test_required_account_risk_refresh_failure_is_sanitized_and_fails_reconcile_closed():
    class RiskReadError(RuntimeError):
        code = "account_risk_read_failed"

    risk_error = RiskReadError("api_key=private-risk-key")

    class FailingRiskSdk(AsyncSdk):
        def get_account_risk_snapshot(self):
            raise risk_error

    store = make_store(FailingRiskSdk(), require_account_risk=True)
    store.start()
    try:
        snapshot = store._sdk_reconcile_snapshot()

        assert snapshot["evidence_complete"] is False
        assert snapshot["trading_blocked"] is True
        assert "account_risk:account_risk_read_failed" in snapshot["evidence_errors"]
        risk_snapshot = snapshot["account_risk_snapshot"]
        assert risk_snapshot["error_code"] == "account_risk_read_failed"
        assert risk_snapshot["evidence_complete"] is False
        assert risk_snapshot["durable"] is False
        assert risk_snapshot["trading_blocked"] is True
        assert "private-risk-key" not in repr(snapshot)
        assert "private-risk-key" not in repr(risk_error)
    finally:
        store.stop()


def test_required_account_risk_expected_prebaseline_defers_to_execution_latch():
    class PreBaselineRiskSdk(AsyncSdk):
        def get_account_risk_snapshot(self):
            return account_risk_prebaseline_payload(self)

        def get_execution_summary(self):
            summary = super().get_execution_summary()
            summary.update(
                evidence_errors=["account_risk_baseline_required"],
                trading_blocked=True,
            )
            return summary

    store = make_store(PreBaselineRiskSdk(), require_account_risk=True)
    store.start()
    try:
        snapshot = store._sdk_reconcile_snapshot()

        assert snapshot["evidence_complete"] is True
        assert snapshot["evidence_errors"] == []
        assert snapshot["execution_summary"]["evidence_errors"] == [
            "account_risk_baseline_required"
        ]
        risk_snapshot = snapshot["account_risk_snapshot"]
        assert risk_snapshot["blocked_reasons"] == [
            "account_evidence_incomplete",
            "baseline_missing",
        ]
        assert "sdk_evidence_errors_present" not in risk_snapshot["evidence_errors"]
    finally:
        store.stop()


@pytest.mark.parametrize("extra_evidence", ["blocked_reason", "provider_error"])
def test_required_account_risk_prebaseline_does_not_relax_extra_evidence(extra_evidence):
    class InvalidPreBaselineRiskSdk(AsyncSdk):
        def get_account_risk_snapshot(self):
            snapshot = account_risk_prebaseline_payload(self)
            if extra_evidence == "blocked_reason":
                snapshot["blocked_reasons"].append("execution_unknown")
            else:
                snapshot["evidence_errors"] = {f"{VENUE}:account": "read_failed"}
            return snapshot

        def get_execution_summary(self):
            summary = super().get_execution_summary()
            summary.update(
                evidence_errors=["account_risk_baseline_required"],
                trading_blocked=True,
            )
            return summary

    store = make_store(InvalidPreBaselineRiskSdk(), require_account_risk=True)
    store.start()
    try:
        snapshot = store._sdk_reconcile_snapshot()

        assert snapshot["evidence_complete"] is False
        assert snapshot["trading_blocked"] is True
        assert "account_risk:account_risk_evidence_incomplete" in snapshot["evidence_errors"]
        if extra_evidence == "provider_error":
            assert (
                "sdk_evidence_errors_present"
                in snapshot["account_risk_snapshot"]["evidence_errors"]
            )
    finally:
        store.stop()


def test_order_query_enqueue_rejection_and_timeout_retry_with_same_identity(monkeypatch):
    class RetryQuerySdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.query_calls = 0

        async def async_make_order(self, venue, request, *, normalized=False):
            assert normalized
            return {
                "kind": "order",
                "symbol": request.symbol,
                "client_order_id": request.client_order_id,
                "status": "submitted",
                "execution_unknown": True,
            }

        async def async_query_order(self, venue, request, *, normalized=False):
            assert normalized
            self.query_calls += 1
            self.calls.append(("query", request.client_order_id, False))
            if self.query_calls == 1:
                raise TimeoutError("query response lost")
            return {
                "kind": "order",
                "symbol": request.symbol,
                "client_order_id": request.client_order_id,
                "status": "canceled",
                "terminal_confirmed": True,
            }

    api = RetryQuerySdk()
    store, broker, data = _started_broker(api)
    broker.set_param("reconcile_retry_backoff", 0)
    original_enqueue = store.enqueue_query
    enqueue_calls = []

    def reject_once(*args, **kwargs):
        enqueue_calls.append((args, kwargs))
        if len(enqueue_calls) == 1:
            return {"queued": False, "error_code": "command_queue_full"}
        return original_enqueue(*args, **kwargs)

    monkeypatch.setattr(store, "enqueue_query", reject_once)
    try:
        order = broker.buy(
            None,
            data,
            size=1,
            price=100,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        client_id = order.info["client_order_id"]
        assert store.wait_for_commands(1)
        broker.next()
        blocked = broker.buy(
            None,
            data,
            size=1,
            price=99,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        assert blocked.status == bt.Order.Rejected
        assert blocked.info["error_code"] == "unknown_execution_exposure"

        assert store.wait_for_commands(1)
        broker.next()
        assert store.wait_for_commands(1)
        broker.next()
        assert order.status == bt.Order.Canceled
        assert order.info["reconcile_attempts"] == 3
        assert [row[1] for row in api.calls if row[0] == "query"] == [client_id, client_id]
        state = broker.get_order_reconciliation_state(order.ref)
        assert state["execution_unknown"] is False
        state["execution_unknown"] = True
        assert broker.get_order_reconciliation_state(order.ref)["execution_unknown"] is False
    finally:
        broker.stop()


def test_store_restart_resets_market_identity_and_increments_generation():
    api = AsyncSdk()
    store = make_store(api)
    store.start()
    store.subscribe(SYMBOL)
    api.events[VENUE].append(
        {
            "kind": "orderbook",
            "symbol": SYMBOL,
            "timestamp": 1_788_600_000.0,
            "bids": [(100, 1)],
            "asks": [(101, 1)],
            "sequence": 10,
            "snapshot_or_delta": "snapshot",
            "continuity_status": "continuous",
            "event_id": "generation-one-book",
        }
    )
    book = store.poll_orderbook(SYMBOL)
    store.mark_strategy_delivered(book)
    first = store.get_stream_health(SYMBOL)
    assert first["stream_generation"] == 1
    assert first["book_ingress"] == first["book_strategy_delivered"] == 1
    assert first["book_conservation"] is True

    store.stop()
    store.start()
    try:
        second = store.get_stream_health(SYMBOL)
        assert second["stream_generation"] == 2
        assert second["book_ingress"] == second["book_strategy_delivered"] == 0
        assert second["market_drop_records"] == []
        assert second["stale"] is False
        assert second["book_conservation"] is True
    finally:
        store.stop()


@pytest.mark.parametrize(
    ("attribute", "method_name", "expected_error"),
    [
        ("positions", "get_positions", "sdk_get_position_response_must_be_list"),
        ("open_orders", "fetch_open_orders", "sdk_get_open_orders_response_must_be_list"),
    ],
)
def test_sdk_account_collections_reject_mapping_as_empty_list(
    attribute, method_name, expected_error
):
    api = AsyncSdk()
    setattr(api, attribute, {})
    store = make_store(api)

    with pytest.raises(BtApiStoreError, match=expected_error):
        getattr(store, method_name)(force=True, raise_errors=True)


@pytest.mark.parametrize(
    ("attribute", "expected_error"),
    [
        ("positions", "sdk_get_position_response_must_be_list"),
        ("open_orders", "sdk_get_open_orders_response_must_be_list"),
    ],
)
def test_sdk_reconcile_rejects_non_list_account_collections(attribute, expected_error):
    api = AsyncSdk()
    setattr(api, attribute, {})

    with pytest.raises(BtApiStoreError, match=expected_error):
        make_store(api).get_reconcile_snapshot()


def test_public_reconcile_and_execution_summary_are_safe_read_only_views():
    store, broker, _data = _started_broker(AsyncSdk())
    try:
        receipt = broker.request_reconcile()
        assert receipt["queued"] is True
        assert broker.request_reconcile() == {"queued": True, "status": "already_pending"}
        assert store.wait_for_commands(1)
        broker.next()
        snapshot = broker.get_last_reconcile_result()
        assert snapshot["evidence_complete"] is True
        assert snapshot["configured_venues"] == snapshot["reconciled_venues"] == ["okx"]
        assert snapshot["generation"] == snapshot["execution_summary"]["generation"] == 1
        assert snapshot["fencing_epoch"] == snapshot["execution_summary"]["fencing_epoch"] == 1
        assert snapshot["as_of_monotonic_ns"] > 0

        summary = broker.get_execution_summary()
        assert summary["unknown_ids"] == []
        summary["unknown_ids"].append("caller-mutation")
        assert broker.get_execution_summary()["unknown_ids"] == []
    finally:
        broker.stop()


def test_account_risk_snapshot_fails_closed_without_public_sdk_contract():
    store = make_store(AsyncSdk())
    broker = store.getbroker(position_mode="dual_side", sdk_preflight=False)
    snapshot = broker.get_account_risk_snapshot()
    assert snapshot == {
        "schema_version": 1,
        "baseline_equity": None,
        "current_equity": None,
        "realized_net": None,
        "configured_venues": ["okx"],
        "configured_venue_routes": [VENUE],
        "baseline_equity_by_venue": None,
        "current_equity_by_venue": None,
        "currency": None,
        "generation": 0,
        "fencing_epoch": 0,
        "as_of_monotonic_ns": 0,
        "owner_pid": None,
        "clock_domain_id": "",
        "identity_binding_sha256": "",
        "durable": False,
        "trading_blocked": True,
        "loss_limit_bps": None,
        "loss_limit_breached": False,
        "loss_breached_at": None,
        "loss_amount": None,
        "loss_limit_amount": None,
        "loss_bps_observed": None,
        "peak_loss_bps": None,
        "evidence_complete": False,
        "evidence_errors": ["account_risk_snapshot_unavailable"],
        "error_code": "account_risk_snapshot_unavailable",
    }


def test_account_risk_snapshot_requires_complete_durable_sdk_evidence():
    class RiskSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.risk = {
                **account_risk_payload(self),
                "realized_net": Decimal("-0.50"),
                "diagnostic_url": "https://demo.invalid?signature=secret-signature",
            }

        def get_account_risk_snapshot(self):
            self.risk["as_of_monotonic_ns"] = time.monotonic_ns()
            return self.risk

    api = RiskSdk()
    store = make_store(api)
    broker = store.getbroker(position_mode="dual_side", sdk_preflight=False)
    snapshot = broker.get_account_risk_snapshot()
    assert snapshot["configured_venues"] == ["okx"]
    assert snapshot["durable"] is True
    assert snapshot["evidence_complete"] is True
    assert len(snapshot["identity_binding_sha256"]) == 64
    assert "secret-signature" not in snapshot["diagnostic_url"]
    snapshot["generation"] = 999
    assert broker.get_account_risk_snapshot()["generation"] == 1

    api.risk["ledger_identities"][0]["account_id"] = "wrong-account"
    incomplete = broker.get_account_risk_snapshot()
    assert incomplete["evidence_complete"] is False
    assert incomplete["durable"] is False
    assert incomplete["trading_blocked"] is True
    assert "account_risk_identity_mismatch" in incomplete["evidence_errors"]


def test_account_risk_snapshot_binds_sdk_loss_limit_and_recomputes_loss_contract():
    class RiskSdk(AsyncSdk):
        def get_account_risk_snapshot(self):
            return account_risk_payload(self, loss_limit_bps="50")

    api = RiskSdk()
    store = make_store(api, account_maximum_loss_bps="50")
    snapshot = store.get_account_risk_snapshot()

    assert snapshot["durable"] is True
    assert snapshot["loss_limit_bps"] == "50"
    assert Decimal(snapshot["loss_amount"]) == Decimal("0.5")
    assert Decimal(snapshot["loss_bps_observed"]) == Decimal("0.5")

    store._sdk_execution_config["account_maximum_loss_bps"] = "25"
    mismatch = store.get_account_risk_snapshot()
    assert mismatch["evidence_complete"] is False
    assert mismatch["trading_blocked"] is True
    assert "account_maximum_loss_limit_mismatch" in mismatch["evidence_errors"]


def test_live_broker_account_risk_read_uses_cache_and_refreshes_off_callback_thread():
    class SlowRiskSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.risk_threads = []

        def get_account_risk_snapshot(self, *, initialize_baseline=False):
            self.risk_threads.append(threading.get_ident())
            if not initialize_baseline:
                time.sleep(0.08)
            return account_risk_payload(self)

    api = SlowRiskSdk()
    store = make_store(
        api,
        require_account_risk=True,
        account_risk_refresh_interval=0.05,
    )
    broker = store.getbroker(
        position_mode="dual_side",
        sdk_preflight=False,
        validation_enabled=False,
        force_refresh_queries=False,
    )
    try:
        broker.start()
        api.risk_threads.clear()
        time.sleep(0.06)
        callback_thread = threading.get_ident()
        started = time.perf_counter()
        snapshot = broker.get_account_risk_snapshot()
        elapsed = time.perf_counter() - started

        assert elapsed < 0.05
        assert snapshot["evidence_complete"] is True
        assert store.wait_for_commands(1)
        broker.next()
        assert api.risk_threads
        assert all(thread_id != callback_thread for thread_id in api.risk_threads)
    finally:
        broker.stop()


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (lambda row: row.update(schema_version=2), "invalid_schema_version"),
        (
            lambda row: row.update(configured_venues=["OKX___SPOT"]),
            "configured_venues_mismatch",
        ),
        (lambda row: row.update(generation=2), "account_risk_generation_fence_mismatch"),
        (
            lambda row: row.update(evidence_errors={VENUE: "contradiction"}),
            "sdk_evidence_errors_present",
        ),
        (
            lambda row: row.update(blocked_reasons=["contradiction"]),
            "sdk_blocked_reasons_present",
        ),
        (lambda row: row.update(current_equity="9999.40"), "current_equity_aggregate_mismatch"),
        (
            lambda row: row.update(
                owner_pid=os.getpid() + 1,
                clock_domain_id=f"process:{os.getpid() + 1}:monotonic",
            ),
            "account_risk_clock_domain_mismatch",
        ),
        (
            lambda row: row.update(as_of_monotonic_ns=time.monotonic_ns() + 10**12),
            "account_risk_timestamp_in_future",
        ),
    ],
)
def test_account_risk_contract_rejects_contradictory_or_unbound_evidence(mutation, expected_error):
    class RiskSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.risk = account_risk_payload(self)

        def get_account_risk_snapshot(self):
            now = time.monotonic_ns()
            if self.risk["as_of_monotonic_ns"] <= now:
                self.risk["as_of_monotonic_ns"] = now
            return self.risk

    api = RiskSdk()
    mutation(api.risk)
    snapshot = make_store(api).get_account_risk_snapshot()

    assert snapshot["evidence_complete"] is False
    assert snapshot["durable"] is False
    assert snapshot["trading_blocked"] is True
    assert expected_error in snapshot["evidence_errors"]


def test_identity_mismatch_cannot_mutate_account_risk_baseline():
    class WrongIdentityRiskSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.risk_calls = 0

        def get_execution_identity(self, venue):
            identity = super().get_execution_identity(venue)
            identity["provider"] = "BINANCE"
            return identity

        def get_account_risk_snapshot(self, *, initialize_baseline=False):
            self.risk_calls += 1
            return account_risk_payload(self)

    api = WrongIdentityRiskSdk()
    store = make_store(api, require_account_risk=True)
    store.start()
    try:
        with pytest.raises(BtApiStoreError, match="account_risk_baseline_not_proven"):
            store.initialize_account_risk_baseline()
        assert api.risk_calls == 0
    finally:
        store.stop()


def test_account_risk_snapshot_rejects_timestamp_created_before_current_call():
    class CachedRiskSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.risk = account_risk_payload(self)
            self.risk["as_of_monotonic_ns"] = time.monotonic_ns() - 10_000_000

        def get_account_risk_snapshot(self):
            return self.risk

    snapshot = make_store(CachedRiskSdk()).get_account_risk_snapshot()

    assert snapshot["evidence_complete"] is False
    assert snapshot["durable"] is False
    assert snapshot["trading_blocked"] is True
    assert "account_risk_timestamp_precedes_call" in snapshot["evidence_errors"]


def test_execution_identity_first_binding_is_atomic_across_threads():
    class RacingIdentitySdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.barrier = threading.Barrier(2)
            self.identity_calls = 0
            self.call_lock = threading.Lock()

        def get_execution_identity(self, venue):
            with self.call_lock:
                call = self.identity_calls
                self.identity_calls += 1
            identity = super().get_execution_identity(venue)
            if call:
                fingerprint = "b" * 64
                identity.update(
                    credential_fingerprint=fingerprint,
                    account_id=f"okx-credential-{fingerprint}",
                )
            self.barrier.wait(timeout=1)
            return identity

    store = make_store(RacingIdentitySdk())
    results = []

    def validate():
        try:
            store._validated_sdk_identity(VENUE)
            results.append("accepted")
        except BtApiStoreError as exc:
            results.append(str(exc))

    threads = [threading.Thread(target=validate) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert sorted(results) == ["accepted", "execution_identity_changed_within_session"]


def test_execution_identity_fence_must_advance_across_store_generations():
    first = AsyncSdk()
    second = AsyncSdk()
    sessions = deque((first, second))

    def api_factory(**_kwargs):
        return sessions.popleft()

    store = make_owned_store(api_factory)
    store.start()
    assert store._validated_sdk_identity(VENUE)["fencing_epoch"] == 1
    assert store._validated_sdk_identity(VENUE)["fencing_epoch"] == 1
    store.stop()

    store.start()
    try:
        with pytest.raises(
            BtApiStoreError,
            match="execution_identity_fencing_epoch_not_advanced",
        ):
            store._validated_sdk_identity(VENUE)
    finally:
        store.stop()


def test_execution_identity_accepts_strictly_newer_fence_after_restart():
    first = AsyncSdk()
    second = AsyncSdk()
    second.fencing_epoch = 2
    sessions = deque((first, second))

    def api_factory(**_kwargs):
        return sessions.popleft()

    store = make_owned_store(api_factory)
    store.start()
    assert store._validated_sdk_identity(VENUE)["fencing_epoch"] == 1
    store.stop()

    store.start()
    try:
        assert store._validated_sdk_identity(VENUE)["fencing_epoch"] == 2
        assert store._validated_sdk_identity(VENUE)["fencing_epoch"] == 2
    finally:
        store.stop()


@pytest.mark.parametrize("async_commands", [True, False], ids=["async", "sync"])
def test_owned_sdk_stop_preserves_validated_redacted_account_risk_snapshot(async_commands):
    class RiskSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            if not async_commands:
                self.async_make_order = None
                self.async_cancel_order = None
                self.async_query_order = None
            self.risk = {
                **account_risk_payload(self),
                "realized_net": Decimal("-0.50"),
                "api_secret": "secret-value",
                "diagnostic_url": "https://demo.invalid?signature=secret-signature",
            }

        def get_account_risk_snapshot(self):
            self.risk["as_of_monotonic_ns"] = time.monotonic_ns()
            return self.risk

    instances = []

    def api_factory(**_kwargs):
        api = RiskSdk()
        instances.append(api)
        return api

    store = make_owned_store(api_factory)
    store.start()
    api = instances[-1]
    store.stop()

    snapshot = store.get_account_risk_snapshot()
    assert api.closed is True
    assert store._api is None
    assert snapshot["generation"] == 1
    assert snapshot["api_secret"] == "***"
    assert "secret-signature" not in snapshot["diagnostic_url"]

    api.risk["generation"] = 999
    snapshot["configured_venues"].clear()
    assert store.get_account_risk_snapshot()["generation"] == 1
    assert store.get_account_risk_snapshot()["configured_venues"] == ["okx"]


def test_owned_sdk_stop_reuses_current_account_risk_cache_without_remote_read():
    class CountingRiskSdk(AsyncSdk):
        def __init__(self):
            super().__init__()
            self.risk_reads = 0

        def get_account_risk_snapshot(self):
            self.risk_reads += 1
            return account_risk_payload(self)

    instances = []

    def api_factory(**_kwargs):
        api = CountingRiskSdk()
        instances.append(api)
        return api

    store = make_owned_store(api_factory)
    store.start()
    api = instances[-1]
    assert store.get_account_risk_snapshot()["evidence_complete"] is True
    assert api.risk_reads == 1

    health = store.stop(timeout=0.5)

    assert health["shutdown_state"] == "PASS"
    assert health["close_thread_alive"] is False
    assert api.risk_reads == 1


def test_owned_sdk_restart_does_not_reuse_previous_account_risk_snapshot():
    class FirstRiskSdk(AsyncSdk):
        def get_account_risk_snapshot(self):
            return {**account_risk_payload(self), "realized_net": Decimal("-0.50")}

    second = AsyncSdk()
    second.fencing_epoch = 2
    sessions = deque((FirstRiskSdk(), second))

    def api_factory(**_kwargs):
        return sessions.popleft()

    store = make_owned_store(api_factory)
    store.start()
    store.stop()
    assert store.get_account_risk_snapshot()["generation"] == 1

    store.start()
    try:
        snapshot = store.get_account_risk_snapshot()
        assert snapshot["error_code"] == "account_risk_snapshot_unavailable"
        assert snapshot["generation"] == 0
    finally:
        store.stop()
