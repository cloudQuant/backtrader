import asyncio
import datetime as dt
import threading
import time
from collections import deque
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backtrader.stores import btapistore as store_module
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError

VENUE = "OKX___SWAP"
SYMBOL = "BTC-USDT-SWAP"


def _funding(*, rate="0.0001", available=True, stale=False, seconds=3600, interval=28800):
    observed_at = dt.datetime.now(dt.timezone.utc)
    return {
        "exchange_name": VENUE,
        "symbol": SYMBOL,
        "rate": Decimal(rate),
        "next_funding_time": observed_at + dt.timedelta(seconds=seconds),
        "settlement_interval_seconds": interval,
        "source": "exchange",
        "freshness": {
            "source": "exchange",
            "observed_at": observed_at,
            "stale": stale,
            "stale_reason": "sdk_stale" if stale else "",
        },
        "available": available,
    }


def _transport_unavailable():
    observed_at = dt.datetime.now(dt.timezone.utc)
    return {
        "exchange_name": VENUE,
        "symbol": SYMBOL,
        "rate": None,
        "next_funding_time": None,
        "settlement_interval_seconds": None,
        "source": "unavailable",
        "freshness": {
            "source": "unavailable",
            "observed_at": observed_at,
            "stale": True,
            "stale_reason": "funding_transport_failed",
        },
        "available": False,
        "unavailable_reason": "funding_transport_failed",
    }


class FundingSdk:
    def __init__(self, snapshots=()):
        self.exchange_kwargs = {VENUE: {"environment": "demo"}}
        self.snapshots = deque(snapshots)
        self.funding_calls = 0
        self.funding_threads = []
        self.funding_started = threading.Event()
        self.release_funding = threading.Event()
        self.block_funding = False
        self.order_completed = threading.Event()

    def get_funding_snapshot(self, venue, symbol):
        assert (venue, symbol) == (VENUE, SYMBOL)
        self.funding_calls += 1
        self.funding_threads.append(threading.get_ident())
        self.funding_started.set()
        if self.block_funding:
            self.release_funding.wait(2)
        value = self.snapshots.popleft()
        if isinstance(value, BaseException):
            raise value
        return value

    async def async_make_order(self, venue, request, *, normalized=False):
        assert venue == VENUE
        assert normalized is True
        await asyncio.sleep(0)
        self.order_completed.set()
        return {
            "kind": "order",
            "symbol": request.symbol,
            "client_order_id": request.client_order_id,
            "order_id": request.client_order_id,
            "status": "filled",
            "filled": "1",
            "price": "100",
        }

    async def async_cancel_order(self, venue, request, *, normalized=False):
        return await self.async_make_order(venue, request, normalized=normalized)

    async def async_query_order(self, venue, request, *, normalized=False):
        return await self.async_make_order(venue, request, normalized=normalized)

    def get_all_balances(self, *, normalized=False):
        assert normalized is True
        return {VENUE: {"cash": 1000, "value": 1000, "exchange_name": VENUE}}

    def get_portfolio_balance(self, *, venue_balances):
        assert venue_balances
        return {"cash": 1000, "value": 1000}

    def get_position(self, venue, symbol, *, normalized=False):
        assert normalized is True
        return []

    def get_open_orders(self, venue, symbol, *, normalized=False):
        assert normalized is True
        return []

    def get_execution_summary(self):
        return {
            "session_enabled": False,
            "unknown_ids": [],
            "active_orders": 0,
            "fee_unresolved_orders": [],
            "funding_unresolved_orders": [],
            "trading_blocked": False,
        }

    def close(self):
        pass


def _store(api, **config):
    return BtApiStore(
        provider="btapi",
        api=api,
        config={
            "exchange_kwargs": api.exchange_kwargs,
            "symbol_routes": {SYMBOL: VENUE},
            "funding_max_age_seconds": 30,
            "funding_refresh_interval_seconds": 0,
            **config,
        },
    )


def test_sync_funding_api_remains_compatible_and_seeds_typed_cache():
    api = FundingSdk([_funding()])
    store = _store(api)

    direct = store.get_funding_snapshot(SYMBOL)
    cached = store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)

    assert isinstance(direct["next_funding_time"], float)
    assert cached["available"] is True
    assert cached["rate"] == Decimal("0.0001")
    assert cached["freshness"]["stale"] is False
    assert cached["cache_age_seconds"] >= 0
    assert cached["cache_generation"] == 0
    assert cached["last_refresh_error"] is None
    assert api.funding_calls == 1


def test_cached_getter_coalesces_refreshes_and_never_reads_sdk_on_caller_thread():
    api = FundingSdk([_funding()])
    api.block_funding = True
    store = _store(api)
    store.start()
    caller_thread = threading.get_ident()
    try:
        first = store.request_funding_refresh(SYMBOL)
        assert api.funding_started.wait(1)
        second = store.request_funding_refresh(SYMBOL)
        pending = store.get_cached_funding_snapshot(SYMBOL, request_refresh=True)

        assert first["status"] == "queued"
        assert second["status"] == "already_pending"
        assert pending["available"] is False
        assert pending["refresh_pending"] is True
        assert api.funding_calls == 1
        assert api.funding_threads == [api.funding_threads[0]]
        assert api.funding_threads[0] != caller_thread

        api.release_funding.set()
        assert store.wait_for_funding_refreshes(1)
        assert store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)["available"] is True
        assert store.get_funding_refresh_health()["coalesced"] >= 2
    finally:
        api.release_funding.set()
        store.stop()


def test_slow_funding_refresh_does_not_delay_order_command_lane():
    api = FundingSdk([_funding()])
    api.block_funding = True
    store = _store(api)
    store.start()
    try:
        store.request_funding_refresh(SYMBOL)
        assert api.funding_started.wait(1)

        receipt = store._enqueue_sdk_command(
            {
                "operation": "submit",
                "venue": VENUE,
                "symbol": SYMBOL,
                "request": SimpleNamespace(symbol=SYMBOL, client_order_id="close-1"),
                "bt_order_ref": 1,
                "client_order_id": "close-1",
            },
            priority_name="close",
        )

        assert receipt["queued"] is True
        assert api.order_completed.wait(1)
        assert store.wait_for_commands(1)
        assert store.get_funding_refresh_health()["inflight"] is True
    finally:
        api.release_funding.set()
        store.wait_for_funding_refreshes(1)
        store.stop()


def test_transport_error_keeps_only_unexpired_last_good_snapshot():
    api = FundingSdk([_funding(), TimeoutError("network timeout")])
    store = _store(api, funding_max_age_seconds=0.2)
    store.start()
    try:
        assert store.request_funding_refresh(SYMBOL)["queued"] is True
        assert store.wait_for_funding_refreshes(1)
        assert store.request_funding_refresh(SYMBOL, force=True)["queued"] is True
        assert store.wait_for_funding_refreshes(1)

        retained = store.get_cached_funding_snapshot(
            SYMBOL, max_age_seconds=0.2, request_refresh=False
        )
        assert retained["available"] is True
        assert retained["last_refresh_error"] == "TimeoutError"

        time.sleep(0.25)
        expired = store.get_cached_funding_snapshot(
            SYMBOL, max_age_seconds=0.2, request_refresh=False
        )
        assert expired["available"] is False
        assert expired["freshness"]["stale"] is True
        assert expired["freshness"]["stale_reason"] == "funding_cache_ttl_expired"
        assert expired["last_refresh_error"] == "TimeoutError"
    finally:
        store.stop()


def test_typed_transport_unavailable_retains_only_an_unexpired_last_good_snapshot():
    api = FundingSdk([_funding(), _transport_unavailable(), _transport_unavailable()])
    store = _store(api, funding_max_age_seconds=0.2)
    store.start()
    try:
        store.request_funding_refresh(SYMBOL)
        assert store.wait_for_funding_refreshes(1)
        store.request_funding_refresh(SYMBOL, force=True)
        assert store.wait_for_funding_refreshes(1)

        retained = store.get_cached_funding_snapshot(
            SYMBOL, max_age_seconds=10, request_refresh=False
        )
        assert retained["available"] is True
        assert retained["last_refresh_error"] == "funding_transport_failed"
        health = store.get_funding_refresh_health(SYMBOL)
        assert health["failed"] == 1
        assert health["transport_errors"] == 1

        time.sleep(0.25)
        store.request_funding_refresh(SYMBOL, force=True)
        assert store.wait_for_funding_refreshes(1)
        expired = store.get_cached_funding_snapshot(
            SYMBOL, max_age_seconds=10, request_refresh=False
        )
        assert expired["available"] is False
        assert expired["freshness"]["stale_reason"] == "funding_transport_failed"
    finally:
        store.stop()


def test_non_transport_refresh_failure_invalidates_last_good_snapshot():
    api = FundingSdk([_funding(), RuntimeError("invalid contract")])
    store = _store(api)
    store.start()
    try:
        store.request_funding_refresh(SYMBOL)
        assert store.wait_for_funding_refreshes(1)
        store.request_funding_refresh(SYMBOL, force=True)
        assert store.wait_for_funding_refreshes(1)

        failed = store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)
        assert failed["available"] is False
        assert failed["freshness"]["stale_reason"] == "funding_refresh_failed"
        assert failed["last_refresh_error"] == "RuntimeError"
    finally:
        store.stop()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("exchange_name", "BINANCE___USDT_FUTURE", "funding_exchange_name_mismatch"),
        ("symbol", "ETH-USDT-SWAP", "funding_symbol_mismatch"),
        ("exchange_name", None, "funding_exchange_name_missing"),
        ("symbol", None, "funding_symbol_missing"),
    ],
)
def test_sdk_funding_identity_mismatch_or_omission_invalidates_last_good(field, value, reason):
    malformed = _funding()
    if value is None:
        malformed.pop(field)
    else:
        malformed[field] = value
    api = FundingSdk([_funding(), malformed])
    store = _store(api)
    store.start()
    try:
        store.request_funding_refresh(SYMBOL)
        assert store.wait_for_funding_refreshes(1)
        store.request_funding_refresh(SYMBOL, force=True)
        assert store.wait_for_funding_refreshes(1)

        rejected = store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)
        assert rejected["available"] is False
        assert rejected["freshness"]["stale_reason"] == reason
        assert rejected["last_refresh_error"] == reason
    finally:
        store.stop()


def test_explicit_sdk_unavailable_or_invalid_schedule_replaces_last_good_immediately():
    unavailable = _funding(available=False)
    invalid_interval = _funding(interval=0)
    api = FundingSdk([_funding(), unavailable, invalid_interval])
    store = _store(api)
    store.start()
    try:
        for expected_available in (True, False, False):
            assert store.request_funding_refresh(SYMBOL, force=True)["queued"] is True
            assert store.wait_for_funding_refreshes(1)
            current = store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)
            assert current["available"] is expected_available

        assert current["freshness"]["stale"] is True
        assert current["freshness"]["stale_reason"] == "funding_interval_invalid"
    finally:
        store.stop()


def test_sdk_stale_snapshot_is_never_treated_as_last_good():
    api = FundingSdk([_funding(), _funding(stale=True)])
    store = _store(api)
    store.start()
    try:
        store.request_funding_refresh(SYMBOL)
        assert store.wait_for_funding_refreshes(1)
        assert store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)["available"] is True

        store.request_funding_refresh(SYMBOL, force=True)
        assert store.wait_for_funding_refreshes(1)
        stale = store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)
        assert stale["available"] is False
        assert stale["freshness"]["stale_reason"] == "sdk_stale"
    finally:
        store.stop()


def test_cache_fails_closed_at_funding_schedule_boundary():
    api = FundingSdk([_funding(seconds=0.2)])
    store = _store(api, funding_max_age_seconds=10)
    store.start()
    try:
        store.request_funding_refresh(SYMBOL)
        assert store.wait_for_funding_refreshes(1)
        assert store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)["available"] is True

        time.sleep(0.25)
        expired = store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)
        assert expired["available"] is False
        assert expired["freshness"]["stale_reason"] == "funding_schedule_expired"
    finally:
        store.stop()


def test_caller_max_age_cannot_extend_store_configured_cache_deadline():
    api = FundingSdk([_funding(seconds=3600)])
    store = _store(api, funding_max_age_seconds=0.05)

    store.get_funding_snapshot(SYMBOL)
    time.sleep(0.08)
    expired = store.get_cached_funding_snapshot(SYMBOL, max_age_seconds=3600, request_refresh=False)

    assert expired["available"] is False
    assert expired["freshness"]["stale_reason"] == "funding_cache_ttl_expired"
    assert (
        expired["cache_deadline_monotonic"]
        <= store.get_funding_refresh_health()["cache_entries"][f"{VENUE}:{SYMBOL}"][
            "deadline_monotonic"
        ]
    )


def test_source_observation_age_reduces_ttl_and_is_reported_as_cache_age(monkeypatch):
    wall_time = [1_800_000_000.0]
    monotonic_time = [500.0]
    observed_at = dt.datetime.fromtimestamp(wall_time[0] - 0.4, dt.timezone.utc)
    snapshot = _funding(seconds=3600)
    snapshot["freshness"]["observed_at"] = observed_at
    snapshot["next_funding_time"] = dt.datetime.fromtimestamp(wall_time[0] + 3600, dt.timezone.utc)
    monkeypatch.setattr(store_module.time, "time", lambda: wall_time[0])
    monkeypatch.setattr(store_module.time, "monotonic", lambda: monotonic_time[0])
    store = _store(FundingSdk([snapshot]), funding_max_age_seconds=1.0)

    store.get_funding_snapshot(SYMBOL)
    fresh = store.get_cached_funding_snapshot(SYMBOL, max_age_seconds=10, request_refresh=False)

    assert fresh["available"] is True
    assert fresh["cache_age_seconds"] == pytest.approx(0.4)
    assert fresh["cache_deadline_monotonic"] == pytest.approx(500.6)

    wall_time[0] += 0.61
    monotonic_time[0] += 0.61
    expired = store.get_cached_funding_snapshot(SYMBOL, max_age_seconds=10, request_refresh=False)
    assert expired["available"] is False
    assert expired["cache_age_seconds"] == pytest.approx(1.01)
    assert expired["freshness"]["stale_reason"] == "funding_cache_ttl_expired"


@pytest.mark.parametrize(
    ("observed_at", "reason"),
    [
        (None, "funding_observed_at_missing"),
        (dt.datetime(2026, 9, 8), "funding_observed_at_timezone_missing"),
        ("2026-09-08T00:00:00Z", "funding_observed_at_invalid"),
        (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5),
            "funding_observed_at_in_future",
        ),
        (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5),
            "funding_cache_ttl_expired",
        ),
    ],
)
def test_sdk_available_funding_rejects_invalid_or_expired_source_time(observed_at, reason):
    malformed = _funding(seconds=3600)
    if observed_at is None:
        malformed["freshness"].pop("observed_at")
    else:
        malformed["freshness"]["observed_at"] = observed_at
    api = FundingSdk([_funding(), malformed])
    store = _store(api, funding_max_age_seconds=30)

    assert store.get_funding_snapshot(SYMBOL)["available"] is True
    direct = store.get_funding_snapshot(SYMBOL)
    cached = store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)

    assert direct["available"] is False
    assert direct["freshness"]["stale_reason"] == reason
    assert cached["available"] is False
    assert cached["freshness"]["stale_reason"] == reason


def test_restart_fences_late_refresh_completion_from_previous_generation():
    api = FundingSdk([_funding(rate="0.0001"), _funding(rate="0.0002")])
    api.block_funding = True
    store = _store(api)
    store.start()
    store.request_funding_refresh(SYMBOL)
    assert api.funding_started.wait(1)

    stopped = store.stop(timeout=0.01)
    assert stopped["funding_restart_blocked_by_worker"] is True
    with pytest.raises(BtApiStoreError, match="funding refresh worker"):
        store.start()

    api.block_funding = False
    api.release_funding.set()
    assert store.wait_for_funding_refreshes(1)
    store.start()
    second_generation = store.get_funding_refresh_health()["generation"]
    store.request_funding_refresh(SYMBOL)
    try:
        assert store.wait_for_funding_refreshes(1)
        current = store.get_cached_funding_snapshot(SYMBOL, request_refresh=False)
        assert current["available"] is True
        assert current["rate"] == Decimal("0.0002")
        assert current["cache_generation"] == second_generation
        assert store.get_funding_refresh_health()["stale_generation_results"] == 1
    finally:
        api.release_funding.set()
        store.stop()
