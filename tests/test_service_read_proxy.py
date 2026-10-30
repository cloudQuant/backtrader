"""Focused contracts for the optional read-only service Store adapter."""

from __future__ import annotations

import threading
import unittest
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from bt_api_base.account_protocol import (
    AccountBalance,
    AccountKey,
    AccountObservation,
    AccountOpenOrder,
    AccountPosition,
    AccountResourceKey,
    AccountValuation,
)
from bt_api_base.market_history_protocol import MarketBar, MarketHistoryPage
from bt_api_base.market_protocol import (
    MARKET_EVENT_OPERATION,
    MARKET_EVENT_SCHEMA,
    MARKET_EVENT_SCHEMA_VERSION,
    MarketInstrumentKey,
    MarketSubscriptionKey,
)
from bt_api_base.service_protocol import (
    WIRE_PROTOCOL_VERSION,
    WireEnvelope,
    WireHeader,
    WireIdentity,
    WireMessageKind,
    WireRole,
    WireScope,
)

from backtrader.dataseries import TimeFrame
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from backtrader.stores.service_read_proxy import (
    ServiceCtpTickBinding,
    ServiceFeedBinding,
    ServiceOrderBookBinding,
    ServiceReadProxy,
    ServiceReadProxyError,
    _bar_identity,
    _bar_to_dict,
    _finite_float,
)


ACCOUNT = AccountKey("venue", "spot", "paper", "account-1")
RESOURCE = AccountResourceKey("spot", "spot-wallet")
INSTRUMENT = MarketInstrumentKey("venue", "spot", "paper", "spot", "BTC-USD", "BTCUSD")
MARKET_KEY = MarketSubscriptionKey("source", "entitlement", INSTRUMENT, "bar", timeframe="1m")
STREAM_SCOPE = WireScope("execution-domain", account_ref="account-1")
OBSERVED = "2026-10-01T12:03:00Z"
NOW = datetime(2026, 10, 1, 12, 3, tzinfo=timezone.utc)


def _bar(minute: int, *, close: str | None = None) -> MarketBar:
    opened = f"2026-10-01T12:{minute:02d}:00Z"
    closed = f"2026-10-01T12:{minute + 1:02d}:00Z"
    value = close or str(100 + minute)
    return MarketBar(
        open_time_utc=opened,
        close_time_utc=closed,
        open=value,
        high=value,
        low=value,
        close=value,
        volume="2",
        open_interest=None,
    )


def _event(sequence: int, bar: MarketBar, *, sent_at=OBSERVED) -> WireEnvelope:
    header = WireHeader(
        protocol_version=WIRE_PROTOCOL_VERSION,
        kind=WireMessageKind.EVENT,
        message_id=f"event-{sequence}",
        correlation_id=None,
        identity=WireIdentity(WireRole.SERVICE, "service", "service"),
        scope=STREAM_SCOPE,
        operation=MARKET_EVENT_OPERATION,
        schema_id=MARKET_EVENT_SCHEMA,
        schema_version=MARKET_EVENT_SCHEMA_VERSION,
        sent_at_utc=sent_at,
        stream_id=MARKET_KEY.stream_id,
        stream_epoch="epoch-1",
        sequence=sequence,
    )
    return WireEnvelope(
        header,
        {"key": MARKET_KEY.to_dict(), "data": bar.to_dict()},
    )


def _observation(
    *,
    positions: tuple[AccountPosition, ...] = (),
    open_orders: tuple[AccountOpenOrder, ...] | None = (),
    open_orders_complete: bool = True,
    valuation: AccountValuation | None = None,
) -> AccountObservation:
    return AccountObservation(
        account_key=ACCOUNT,
        observation_id="observation-1",
        coverage=(RESOURCE,),
        balances=(
            AccountBalance(
                RESOURCE,
                "USD",
                "100",
                "90",
                "10",
                OBSERVED,
            ),
        ),
        positions=positions,
        valuation=valuation or AccountValuation("USD", "90", "100", OBSERVED),
        started_at_utc="2026-10-01T12:02:00Z",
        completed_at_utc=OBSERVED,
        consistency="provider_atomic",
        balances_complete=True,
        positions_complete=True,
        open_orders=open_orders,
        open_orders_complete=open_orders_complete,
    )


class _AccountClient:
    expected_account = ACCOUNT
    required_coverage = (RESOURCE,)
    require_open_orders = True

    def __init__(self, observation):
        self.view = SimpleNamespace(observation=observation)
        self.refresh_count = 0
        self.close_count = 0
        self.fail_reads = False

    def refresh(self):
        self.refresh_count += 1
        if self.fail_reads:
            raise RuntimeError("stale account state")
        return self.view

    def snapshot(self):
        if self.fail_reads:
            raise RuntimeError("stale account state")
        return self.view

    def close(self):
        self.close_count += 1


class _MarketClient:
    key = MARKET_KEY
    stream_scope = STREAM_SCOPE
    healthy = True
    recovery_required = False

    def __init__(self, history_bars=(), *, snapshot=None, events=()):
        self.history_bars = tuple(history_bars)
        self.snapshot = snapshot
        self.events = deque(events)
        self.calls = []
        self.close_count = 0
        self.fail_close_once = False
        self.observed_at = OBSERVED
        self.recovery_on_poll = False

    def start(self):
        self.calls.append("start")
        sequence = 0 if self.snapshot is None else self.snapshot.header.sequence
        return SimpleNamespace(
            snapshot=self.snapshot,
            snapshot_kind="latest_event",
            snapshot_complete=False,
            full_baseline_available=False,
            stream_id=self.key.stream_id,
            snapshot_epoch="epoch-1",
            snapshot_sequence=sequence,
            cursor_epoch="epoch-1",
            cursor_sequence=sequence,
            resync_required=False,
        )

    def history(self, request):
        self.calls.append("history")
        start = datetime.fromisoformat(request.start_time_utc[:-1] + "+00:00")
        end = datetime.fromisoformat(request.end_time_utc[:-1] + "+00:00")
        selected = tuple(
            bar
            for bar in self.history_bars
            if datetime.fromisoformat(bar.open_time_utc[:-1] + "+00:00") >= start
            and datetime.fromisoformat(bar.close_time_utc[:-1] + "+00:00") <= end
        )
        page_bars = selected[: request.limit]
        complete = len(selected) <= request.limit
        continuation = None if complete else page_bars[-1].close_time_utc
        return MarketHistoryPage(
            request=request,
            bars=page_bars,
            complete=complete,
            next_start_time_utc=continuation,
            observed_at_utc=self.observed_at,
        )

    def poll(self, *, timeout_ms=0):
        event = self.events.popleft() if self.events else None
        if self.recovery_on_poll:
            self.recovery_required = True
        return event

    def close(self):
        self.close_count += 1
        if self.fail_close_once:
            self.fail_close_once = False
            raise RuntimeError("close retry")


class _LazyWriteLeaf:
    """Expose real-looking write methods that record only actual dispatch."""

    service_read_only = True

    def __init__(self):
        self.calls: list[str] = []

    def connect(self):
        self.calls.append("connect")

    def disconnect(self):
        self.calls.append("disconnect")

    def supports_position_mode(self, mode):
        return mode == "net"

    def __getattr__(self, name):
        if name not in {"submit_order", "create_order", "cancel_order"}:
            raise AttributeError(name)

        def dispatch(*_args, **_kwargs):
            self.calls.append(name)
            return {"accepted": True}

        return dispatch


def _position(side="net", quantity="-2", average_price="-5.25"):
    return AccountPosition(
        resource=RESOURCE,
        instrument=INSTRUMENT,
        side=side,
        quantity=quantity,
        qty_unit="contracts",
        average_price=average_price,
        price_currency="USD",
        observed_at_utc=OBSERVED,
    )


def _proxy(
    observation=None,
    *,
    market=None,
    position_mode="net",
    quantity_multiplier="10",
    history_start="2026-10-01T12:00:00Z",
    history_end="2026-10-01T12:02:00Z",
    clock=lambda: NOW,
    **kwargs,
):
    account = _AccountClient(observation or _observation())
    market = market or _MarketClient()
    binding = ServiceFeedBinding(
        market_client=market,
        resource=RESOURCE,
        qty_unit="contracts",
        timeframe="1m",
        quantity_multiplier=quantity_multiplier,
        history_start_utc=history_start,
        history_end_utc=history_end,
    )
    proxy = ServiceReadProxy(
        account,
        {"BTC-USD": binding},
        valuation_currency="USD",
        position_mode=position_mode,
        clock=clock,
        **kwargs,
    )
    return proxy, account, market


class ServiceReadProxyTests(unittest.TestCase):
    def test_bar_history_capability_is_in_memory_and_accepts_interval_aliases(self):
        proxy, account, market = _proxy()

        # The capability query is usable before connect and must not touch either
        # injected facade.
        self.assertTrue(
            proxy.supports_bar_history("BTC-USD", timeframe=TimeFrame.Seconds, compression=60)
        )
        self.assertTrue(
            proxy.supports_bar_history("BTC-USD", timeframe=TimeFrame.Minutes, compression=1)
        )
        self.assertEqual(account.refresh_count, 0)
        self.assertEqual(market.calls, [])

        # The configured wire interval may use a different fixed-unit spelling.
        alias_market = _MarketClient()
        alias_market.key = MarketSubscriptionKey(
            "source", "entitlement", INSTRUMENT, "bar", timeframe="60s"
        )
        alias_binding = ServiceFeedBinding(alias_market, RESOURCE, "contracts", "60s")
        alias_proxy = ServiceReadProxy(
            _AccountClient(_observation()),
            {"BTC-USD": alias_binding},
            valuation_currency="USD",
            position_mode="net",
        )
        self.assertTrue(
            alias_proxy.supports_bar_history("BTC-USD", timeframe=TimeFrame.Minutes, compression=1)
        )
        self.assertEqual(alias_market.calls, [])

    def test_bar_history_capability_fails_closed_for_unsupported_bindings_and_inputs(self):
        proxy, _, _ = _proxy()

        unsupported = (
            ("missing", TimeFrame.Minutes, 1),
            ("BTC-USD", TimeFrame.Seconds, 59),
            ("BTC-USD", TimeFrame.Weeks, 1),
            ("BTC-USD", TimeFrame.Minutes, 0),
            ("BTC-USD", TimeFrame.Minutes, True),
            ("BTC-USD", [], 1),
            (None, TimeFrame.Minutes, 1),
        )
        for dataname, timeframe, compression in unsupported:
            with self.subTest(dataname=dataname, timeframe=timeframe, compression=compression):
                self.assertFalse(
                    proxy.supports_bar_history(
                        dataname, timeframe=timeframe, compression=compression
                    )
                )

        tick_market = _MarketClient()
        tick_market.key = MarketSubscriptionKey("source", "entitlement", INSTRUMENT, "ctp.quote.v2")
        tick_binding = ServiceCtpTickBinding(tick_market, RESOURCE, "contracts", "session-1")
        orderbook_market = _MarketClient()
        orderbook_market.key = MarketSubscriptionKey(
            "source", "entitlement", INSTRUMENT, "orderbook", depth=5
        )
        orderbook_binding = ServiceOrderBookBinding(orderbook_market, RESOURCE, "contracts")
        for binding in (tick_binding, orderbook_binding):
            with self.subTest(binding=type(binding).__name__):
                non_bar_proxy = ServiceReadProxy(
                    _AccountClient(_observation()),
                    {"BTC-USD": binding},
                    valuation_currency="USD",
                    position_mode="net",
                )
                self.assertFalse(
                    non_bar_proxy.supports_bar_history(
                        "BTC-USD", timeframe=TimeFrame.Minutes, compression=1
                    )
                )
                self.assertEqual(binding.market_client.calls, [])

    def test_bar_history_capability_enforces_owner_thread_and_closed_state(self):
        proxy, _, _ = _proxy()
        result = []

        def query_from_other_thread():
            try:
                result.append(
                    proxy.supports_bar_history(
                        "BTC-USD", timeframe=TimeFrame.Minutes, compression=1
                    )
                )
            except ServiceReadProxyError as exc:
                result.append(exc.code)

        worker = threading.Thread(target=query_from_other_thread)
        worker.start()
        worker.join()
        self.assertEqual(result, ["WRONG_OWNER_THREAD"])

        proxy._closing = True
        self.assertFalse(
            proxy.supports_bar_history("BTC-USD", timeframe=TimeFrame.Minutes, compression=1)
        )
        proxy._closing = False
        proxy.disconnect()
        self.assertFalse(
            proxy.supports_bar_history("BTC-USD", timeframe=TimeFrame.Minutes, compression=1)
        )

    def test_account_valuation_and_net_quantity_use_explicit_units(self):
        proxy, _, _ = _proxy(_observation(positions=(_position(),)))
        proxy.connect()

        self.assertEqual(proxy.get_balance(), {"cash": 90.0, "value": 100.0})
        (position,) = proxy.get_positions()
        self.assertEqual(position["data_name"], "BTC-USD")
        self.assertEqual(position["size"], -20.0)
        self.assertEqual(position["direction"], "short")
        self.assertEqual(position["price"], -5.25)
        self.assertTrue(proxy.supports_position_mode("net"))
        self.assertFalse(proxy.supports_position_mode("dual_side"))

    def test_dual_side_keeps_long_and_short_legs_separate(self):
        positions = (
            _position("long", "2", "10"),
            _position("short", "3", "-11"),
        )
        proxy, _, _ = _proxy(
            _observation(positions=positions),
            position_mode="dual_side",
        )
        proxy.connect()

        rows = proxy.get_positions()
        self.assertEqual(
            [(row["direction"], row["size"]) for row in rows],
            [
                ("long", 20.0),
                ("short", 30.0),
            ],
        )
        self.assertTrue(proxy.supports_position_mode("dual_side"))
        self.assertFalse(proxy.supports_position_mode("net"))

    def test_dual_side_rejects_negative_leg_quantity(self):
        malformed = _position("short", "1", "11")
        object.__setattr__(malformed, "quantity", "-1")
        proxy, _, _ = _proxy(
            _observation(positions=(malformed,)),
            position_mode="dual_side",
        )
        proxy.connect()

        with self.assertRaisesRegex(ServiceReadProxyError, "POSITION_QUANTITY_INVALID"):
            proxy.get_positions()

    def test_open_orders_require_a_complete_provider_snapshot(self):
        proxy, _, _ = _proxy(_observation(open_orders=None, open_orders_complete=False))
        proxy.connect()
        with self.assertRaisesRegex(ServiceReadProxyError, "OPEN_ORDERS_INCOMPLETE"):
            proxy.fetch_open_orders()

        complete_proxy, _, _ = _proxy(_observation(open_orders=(), open_orders_complete=True))
        complete_proxy.connect()
        self.assertEqual(complete_proxy.fetch_open_orders(), [])

    def test_market_starts_before_history_and_identical_bootstrap_bar_is_deduped(self):
        first, latest = _bar(0), _bar(1)
        market = _MarketClient(
            (first, latest),
            snapshot=_event(2, latest),
            events=(_event(3, _bar(2)),),
        )
        proxy, _, _ = _proxy(market=market)
        proxy.connect()
        proxy.subscribe("BTC-USD")
        bars = proxy.fetch_bars(
            "BTC-USD",
            timeframe=TimeFrame.Minutes,
            compression=1,
        )

        self.assertEqual(market.calls, ["start", "history"])
        self.assertEqual(
            [bar["timestamp"] for bar in bars],
            [
                "2026-10-01T12:00:00Z",
                "2026-10-01T12:01:00Z",
            ],
        )
        self.assertEqual(proxy.poll_bar("BTC-USD")["timestamp"], "2026-10-01T12:02:00Z")
        self.assertIsNone(proxy.poll_bar("BTC-USD"))

    def test_live_events_require_aligned_closed_bars_of_the_bound_duration(self):
        cases = (
            (
                MarketBar(
                    "2026-10-01T12:00:00Z",
                    "2026-10-01T12:02:00Z",
                    "1",
                    "1",
                    "1",
                    "1",
                    "1",
                ),
                OBSERVED,
                "MARKET_BAR_TIMEFRAME_MISMATCH",
            ),
            (
                MarketBar(
                    "2026-10-01T12:00:30Z",
                    "2026-10-01T12:01:30Z",
                    "1",
                    "1",
                    "1",
                    "1",
                    "1",
                ),
                OBSERVED,
                "MARKET_BAR_ALIGNMENT_INVALID",
            ),
            (
                _bar(2),
                "2026-10-01T12:02:59Z",
                "MARKET_BAR_NOT_CLOSED_AT_SENT",
            ),
        )
        for bar, sent_at, code in cases:
            with self.subTest(code=code):
                market = _MarketClient(events=(_event(1, bar, sent_at=sent_at),))
                proxy, _, _ = _proxy(market=market)
                proxy.connect()
                proxy.subscribe("BTC-USD")

                with self.assertRaisesRegex(ServiceReadProxyError, code):
                    proxy.poll_bar("BTC-USD")

    def test_live_events_reject_future_close_and_keep_only_last_identity(self):
        future = MarketBar(
            "2026-10-01T12:03:00Z",
            "2026-10-01T12:04:00Z",
            "1",
            "1",
            "1",
            "1",
            "1",
        )
        future_proxy, _, _ = _proxy(market=_MarketClient(events=(_event(1, future),)))
        future_proxy.connect()
        future_proxy.subscribe("BTC-USD")
        with self.assertRaisesRegex(ServiceReadProxyError, "MARKET_BAR_FUTURE"):
            future_proxy.poll_bar("BTC-USD")

        canonical = MarketBar(
            "2026-10-01T12:00:00.000Z",
            "2026-10-01T12:01:00.000Z",
            "1",
            "1",
            "1",
            "1",
            "1",
        )
        duplicate = replace(
            canonical,
            open_time_utc="2026-10-01T12:00:00Z",
            close_time_utc="2026-10-01T12:01:00Z",
        )
        market = _MarketClient(events=(_event(1, canonical), _event(2, duplicate)))
        proxy, _, _ = _proxy(market=market)
        proxy.connect()
        proxy.subscribe("BTC-USD")
        self.assertIsNotNone(proxy.poll_bar("BTC-USD"))
        self.assertIsNone(proxy.poll_bar("BTC-USD"))
        self.assertFalse(hasattr(proxy, "_emitted_by_open"))
        self.assertEqual(len(proxy._last_emitted_identity), 1)

        canonical_row = _bar_to_dict(canonical)
        unnormalized_row = {
            **canonical_row,
            "close_time_utc": "2026-10-01T12:01:00.000001Z",
        }
        self.assertNotEqual(_bar_identity(canonical_row), _bar_identity(unnormalized_row))

    def test_live_stream_resync_state_and_out_of_order_bars_fail_closed(self):
        stream = _MarketClient(events=(_event(3, _bar(2)),))
        stream.recovery_on_poll = True
        proxy, _, _ = _proxy(market=stream)
        proxy.connect()
        proxy.subscribe("BTC-USD")

        with self.assertRaisesRegex(ServiceReadProxyError, "MARKET_STREAM_UNHEALTHY"):
            proxy.poll_bar("BTC-USD")

        historical = (_bar(0), _bar(1))
        out_of_order = _MarketClient(
            historical,
            snapshot=_event(2, historical[-1]),
            events=(_event(3, historical[0]),),
        )
        proxy, _, _ = _proxy(market=out_of_order)
        proxy.connect()
        proxy.subscribe("BTC-USD")
        proxy.fetch_bars(
            "BTC-USD",
            timeframe=TimeFrame.Minutes,
            compression=1,
        )

        with self.assertRaisesRegex(ServiceReadProxyError, "LIVE_BAR_OUT_OF_ORDER"):
            proxy.poll_bar("BTC-USD")

    def test_hour_key_accepts_sixty_minute_backtrader_compression(self):
        hour_key = MarketSubscriptionKey(
            "source",
            "entitlement",
            INSTRUMENT,
            "bar",
            timeframe="1h",
        )
        market = _MarketClient()
        market.key = hour_key
        market.observed_at = "2026-10-01T13:00:00Z"
        binding = ServiceFeedBinding(
            market,
            RESOURCE,
            "contracts",
            "1h",
            history_start_utc="2026-10-01T12:00:00Z",
            history_end_utc="2026-10-01T13:00:00Z",
        )
        account = _AccountClient(_observation())
        proxy = ServiceReadProxy(
            account,
            {"BTC-USD": binding},
            valuation_currency="USD",
            position_mode="net",
            clock=lambda: datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc),
        )
        proxy.connect()
        proxy.subscribe("BTC-USD")

        self.assertEqual(
            proxy.fetch_bars(
                "BTC-USD",
                timeframe=TimeFrame.Minutes,
                compression=60,
            ),
            [],
        )

    def test_weekly_bindings_and_backtrader_week_timeframes_are_rejected(self):
        market = _MarketClient()
        with self.assertRaisesRegex(ValueError, "weekly feeds are unsupported"):
            ServiceFeedBinding(
                market,
                RESOURCE,
                "contracts",
                "1w",
            )

        proxy, _, market = _proxy()
        proxy.connect()
        proxy.subscribe("BTC-USD")
        with self.assertRaisesRegex(ServiceReadProxyError, "TIMEFRAME_UNSUPPORTED"):
            proxy.fetch_bars(
                "BTC-USD",
                timeframe=TimeFrame.Weeks,
                compression=1,
            )
        self.assertEqual(market.calls, ["start"])

    def test_decimal_conversion_rejects_nonzero_underflow(self):
        with self.assertRaisesRegex(ServiceReadProxyError, "NUMBER_UNDERFLOW"):
            _finite_float(Decimal("1e-1000"), "tiny")

    def test_conflicting_bootstrap_overlap_is_rejected(self):
        historical = _bar(1)
        conflicting = _bar(1, close="999")
        market = _MarketClient(
            (_bar(0), historical),
            snapshot=_event(2, conflicting),
        )
        proxy, _, _ = _proxy(market=market)
        proxy.connect()
        proxy.subscribe("BTC-USD")

        with self.assertRaisesRegex(ServiceReadProxyError, "HISTORY_LIVE_CONFLICT"):
            proxy.fetch_bars(
                "BTC-USD",
                timeframe=TimeFrame.Minutes,
                compression=1,
            )

    def test_history_pagination_is_bounded_and_truncation_is_not_hidden(self):
        bars = (_bar(0), _bar(1))
        market = _MarketClient(bars)
        proxy, _, _ = _proxy(
            market=market,
            history_end="2026-10-01T12:03:00Z",
            history_page_size=1,
            max_history_pages=1,
            default_history_limit=3,
        )
        proxy.connect()
        proxy.subscribe("BTC-USD")

        with self.assertRaisesRegex(ServiceReadProxyError, "HISTORY_PAGE_LIMIT"):
            proxy.fetch_bars(
                "BTC-USD",
                timeframe=TimeFrame.Minutes,
                compression=1,
            )

    def test_unmapped_account_instrument_fails_closed(self):
        other = MarketInstrumentKey("venue", "spot", "paper", "spot", "ETH-USD", "ETHUSD")
        position = AccountPosition(
            resource=RESOURCE,
            instrument=other,
            side="net",
            quantity="1",
            qty_unit="contracts",
            average_price="2",
            price_currency="USD",
            observed_at_utc=OBSERVED,
        )
        proxy, _, _ = _proxy(_observation(positions=(position,)))

        with self.assertRaisesRegex(ServiceReadProxyError, "ACCOUNT_INSTRUMENT_UNMAPPED"):
            proxy.connect()

    def test_failed_close_remains_retryable_and_closes_only_facades(self):
        market = _MarketClient()
        market.fail_close_once = True
        proxy, account, market = _proxy(market=market)
        proxy.connect()

        with self.assertRaisesRegex(RuntimeError, "close retry"):
            proxy.disconnect()
        self.assertFalse(proxy.is_connected)
        with self.assertRaisesRegex(ServiceReadProxyError, "PROXY_NOT_CONNECTED"):
            proxy.get_balance()

        proxy.disconnect()
        self.assertEqual(market.close_count, 2)
        self.assertEqual(account.close_count, 1)
        self.assertFalse(proxy.is_connected)

    def test_stopped_service_store_requires_fresh_facades_for_restart(self):
        proxy, _, _ = _proxy()
        store = BtApiStore(provider="btapi", api=proxy)
        store.start()

        store.stop()

        with self.assertRaisesRegex(BtApiStoreError, "fresh client facades"):
            store.start()

    def test_lazy_service_proxy_factory_is_rejected_before_connect(self):
        proxy, account, market = _proxy()

        class ProxyFactory:
            def __new__(cls, **kwargs):
                return proxy

        store = BtApiStore(provider="btapi", api_cls=ProxyFactory)
        self.assertFalse(store._service_read_only)
        with self.assertRaisesRegex(BtApiStoreError, "injected with api="):
            store.start()
        self.assertEqual(account.close_count, 1)
        self.assertEqual(market.close_count, 1)

    def test_read_only_store_blocks_write_entrypoints_before_lazy_dispatch(self):
        api = _LazyWriteLeaf()
        store = BtApiStore(provider="btapi", api=api)
        order = SimpleNamespace(ref=17, data=None, info={})
        self.assertTrue(callable(api.submit_order))
        self.assertTrue(callable(api.cancel_order))

        writes = (
            ("submit_order", lambda: store.submit_order(order)),
            ("legacy_submit", lambda: store._submit_order_legacy(order)),
            ("enqueue_order", lambda: store.enqueue_order(order)),
            ("cancel_order", lambda: store.cancel_order(order)),
            ("cancel_order_ref", lambda: store.cancel_order_ref(17, dataname="BTC-USD")),
            ("legacy_cancel", lambda: store._cancel_order_ref_legacy(17, dataname="BTC-USD")),
            ("enqueue_cancel", lambda: store.enqueue_cancel(17, dataname="BTC-USD")),
        )
        for name, invoke in writes:
            with self.subTest(entrypoint=name), self.assertRaisesRegex(
                BtApiStoreError, "read-only service proxy"
            ):
                invoke()

        self.assertEqual(api.calls, [])

    def test_read_only_broker_requires_market_data_only_before_store_connect(self):
        api = _LazyWriteLeaf()
        store = BtApiStore(provider="btapi", api=api)
        broker = BtApiBroker(
            store=store,
            market_data_only=False,
            validation_enabled=False,
        )

        with self.assertRaisesRegex(ValueError, "market_data_only=True"):
            broker.start()

        self.assertEqual(api.calls, [])

    def test_read_only_broker_refreshes_and_propagates_post_start_failures(self):
        proxy, account, _ = _proxy()
        store = BtApiStore(provider="btapi", api=proxy)
        broker = BtApiBroker(
            store=store,
            market_data_only=True,
            position_sync_policy="startup",
            validation_enabled=False,
            force_refresh_queries=False,
            account_refresh_interval=3600,
            positions_refresh_interval=3600,
            open_orders_refresh_interval=3600,
        )
        broker.start()
        self.assertTrue(broker._startup_ready)
        self.assertTrue(broker._positions_snapshot_loaded)
        refresh_count = account.refresh_count
        account.fail_reads = True

        try:
            with self.assertRaisesRegex(RuntimeError, "stale account state"):
                broker.getcash()
            with self.assertRaisesRegex(RuntimeError, "stale account state"):
                broker.getposition("BTC-USD")
            with self.assertRaisesRegex(RuntimeError, "stale account state"):
                broker.fetch_open_orders()
            self.assertEqual(account.refresh_count, refresh_count + 3)
        finally:
            store.stop()


if __name__ == "__main__":
    unittest.main()
