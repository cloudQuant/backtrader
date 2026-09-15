"""Finite local native-broker evidence for the Iteration 25 candidate.

This is intentionally a test-only, zero-network transport.  It proves a
small causal slice through the production Store/Feed/Broker/Cerebro objects:
the candidate obtains its tick-only intent from three Feed callbacks, then a
test-only strategy subclass uses the public ``Strategy.buy``/``cancel`` path.

The Store deliberately stays on its legacy fake-client branch
(``_sdk_mode=False``), while the Broker deliberately has
``market_data_only=False`` so the local public order mapping can be exercised.
Consequently this is neither CTP SDK evidence nor a market-data-only admission
gate. It does not arm a CTP session, read credentials, contact SimNow, or
establish market/fill/PnL/HFT acceptance.
"""

from __future__ import annotations

import collections
import copy
import http.client
import importlib
import logging
import socket
import urllib.request
from typing import Any, Mapping

import backtrader as bt
import pytest
import requests

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.ctpcohort import CtpCohortNow
from backtrader.stores.btapistore import BtApiStore
from tests.fixtures.fake_btapi import FakeBtApiClient

runner = importlib.import_module("examples.015_ctp_options_highfreq.run")
strategy_module = importlib.import_module(
    "examples.015_ctp_options_highfreq.ctp_options_highfreq_strategy"
)

RAW_CONFIG, _ = runner.load_config()
CONFIG = runner.effective_config(RAW_CONFIG, mode="replay", purpose="formula")
FIXTURE, _, _ = runner.load_fixture(CONFIG)
BUNDLE = runner.validate_bundle(FIXTURE, CONFIG)
SYMBOLS = tuple(BUNDLE[role]["symbol"] for role in ("future", "call", "put"))
FUTURE, CALL, PUT = SYMBOLS
EXCHANGE = BUNDLE["future"]["exchange_id"]
CLIENT_ORDER_ID = "iter25-native-chain-put-1"
EXTERNAL_ORDER_ID = "iter25-local-ctp-order-1"
LATE_TRADE_ID = "iter25-local-late-trade-1"
UNKNOWN_LATE_TRADE_ID = "iter25-local-unknown-late-trade-1"


class DecisionClock:
    """A deterministic same-domain decision-time attestor for the test Feed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.deliveries: list[tuple[str, int, int]] = []
        self.monotonic_reads: list[int] = []
        self._clock_domain_id: str | None = None
        self._now_monotonic_ns: int | None = None

    def advance_for_delivery(self, tick: Any) -> None:
        """Advance only when the local fake transport actually releases a tick."""

        now_monotonic_ns = int(tick.recv_monotonic_ns)
        clock_domain_id = str(tick.clock_domain_id)
        if self._clock_domain_id is None:
            self._clock_domain_id = clock_domain_id
        else:
            assert clock_domain_id == self._clock_domain_id
        if self._now_monotonic_ns is not None:
            assert now_monotonic_ns > self._now_monotonic_ns
        self._now_monotonic_ns = now_monotonic_ns
        self.deliveries.append((str(tick.symbol), int(tick.ingest_seq), now_monotonic_ns))

    def monotonic_ns(self) -> int:
        if self._now_monotonic_ns is None:
            raise AssertionError("Feed requested a decision clock before a local tick delivery")
        self.monotonic_reads.append(self._now_monotonic_ns)
        return self._now_monotonic_ns

    def __call__(self, tick: Any) -> CtpCohortNow:
        if self._clock_domain_id is None or self._now_monotonic_ns is None:
            raise AssertionError("decision evidence requires an already delivered local tick")
        assert str(tick.clock_domain_id) == self._clock_domain_id
        assert int(tick.recv_monotonic_ns) == self._now_monotonic_ns
        self.calls.append((str(tick.symbol), int(tick.ingest_seq)))
        return CtpCohortNow(
            now_monotonic_ns=self._now_monotonic_ns,
            now_epoch=tick.recv_time_utc,
            clock_domain_id=self._clock_domain_id,
            receive_clock_error_ms=0.0,
            receive_clock_quality="verified",
            freshness_verified=True,
        )


@pytest.fixture
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Turn any outbound socket operation into an immediate test failure."""

    attempts: list[str] = []

    def blocked(operation: str):
        def reject(*_args: Any, **_kwargs: Any) -> None:
            attempts.append(operation)
            raise AssertionError(f"network operation is forbidden in this local test: {operation}")

        return reject

    # Keep the recovery diagnostic path active while preventing a host-owned
    # transport handler from being mistaken for test traffic.
    for module in (
        importlib.import_module(BtApiStore.__module__),
        importlib.import_module(BtApiBroker.__module__),
    ):
        isolated_logger = logging.Logger(f"{module.__name__}.network_guard", logging.NOTSET)
        isolated_logger.propagate = False
        isolated_logger.addHandler(logging.NullHandler())
        monkeypatch.setattr(module, "logger", isolated_logger)

    # Do not replace ``socket.socket``: on Windows the Proactor event loop
    # builds its own local self-pipe with socketpair(), which would turn test
    # infrastructure into a false CTP-network attempt.  These high-level
    # egress points are portable, while the supplied finite fake transport and
    # the blocked Store factories prove this test cannot construct an SDK
    # client instead.
    for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        monkeypatch.setattr(socket, name, blocked(f"socket.{name}"))
    monkeypatch.setattr(http.client.HTTPConnection, "connect", blocked("HTTPConnection.connect"))
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", blocked("HTTPSConnection.connect"))
    monkeypatch.setattr(urllib.request, "urlopen", blocked("urllib.request.urlopen"))
    monkeypatch.setattr(requests.sessions.Session, "request", blocked("requests.Session.request"))
    store_module = importlib.import_module(BtApiStore.__module__)
    monkeypatch.setattr(
        store_module, "_resolve_bt_api_client", blocked("BtApiStore._resolve_bt_api_client")
    )
    monkeypatch.setattr(
        store_module,
        "_create_ctp_gateway_wrapper_class",
        blocked("BtApiStore._create_ctp_gateway_wrapper_class"),
    )
    yield attempts
    assert attempts == []


class FinitePublicTransport(FakeBtApiClient):
    """Public test transport with explicit local-only request accounting.

    It deliberately implements only the public compatibility surface used by
    ``BtApiStore``.  ``connect`` and command calls mutate in-memory queues;
    no socket, subprocess, credential loader, or external client is present.
    """

    def __init__(
        self,
        live_ticks: Mapping[str, list[Any]],
        *,
        decision_clock: DecisionClock,
        unknown_first_put: bool = False,
    ) -> None:
        super().__init__(
            balance={"cash": 100_000.0, "value": 100_000.0},
            live_ticks=live_ticks,
        )
        self._decision_clock = decision_clock
        self._unknown_first_put = unknown_first_put
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.lifecycle: list[str] = []
        self.delivered_ticks: list[Any] = []
        self._expected_symbols = collections.deque(
            symbol for _round in range(2) for symbol in SYMBOLS
        )

    def connect(self) -> None:
        self.connect_calls += 1
        self.lifecycle.append("connect")
        self.connected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.lifecycle.append("disconnect")
        self.connected = False

    def poll_tick(self, dataname: str) -> Any:
        if self._expected_symbols and dataname != self._expected_symbols[0]:
            return None
        tick = super().poll_tick(dataname)
        if tick is not None:
            expected = self._expected_symbols.popleft()
            assert expected == dataname
            self._decision_clock.advance_for_delivery(tick)
            self.delivered_ticks.append(tick)
        return tick

    def is_source_exhausted(self, _symbol: str) -> bool:
        return not self._expected_symbols

    def get_source_event_time_watermark(self, _symbol: str) -> Any:
        return None

    def submit_order(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = dict(payload)
        self.submitted_orders.append(payload)
        self._bt_order_ref = payload["bt_order_ref"]
        assert payload["client_order_id"] == CLIENT_ORDER_ID
        assert payload["symbol"] == PUT
        if self._unknown_first_put:
            # The normal response gives the real Broker its original local /
            # remote association.  The next inbound order update then marks
            # that very order UNKNOWN, before a late authoritative trade and
            # its duplicate are delivered.  Nothing in this fixture touches a
            # socket or a real SDK session.
            self.push_broker_update(
                {
                    "kind": "order",
                    "status": "accepted",
                    "execution_unknown": True,
                    "external_order_id": EXTERNAL_ORDER_ID,
                    "order_ref": CLIENT_ORDER_ID,
                    "data_name": PUT,
                    "side": "buy",
                    "exchange_id": EXCHANGE,
                }
            )
            late_trade = {
                "kind": "trade",
                "bt_order_ref": self._bt_order_ref,
                "external_order_id": EXTERNAL_ORDER_ID,
                "order_ref": CLIENT_ORDER_ID,
                "data_name": PUT,
                "symbol": PUT,
                "side": "buy",
                "offset": "open",
                "size": 1,
                "price": 10.0,
                "trade_id": UNKNOWN_LATE_TRADE_ID,
                "exchange_id": EXCHANGE,
            }
            self.push_broker_update(late_trade)
            self.push_broker_update(late_trade)
            return {
                "id": EXTERNAL_ORDER_ID,
                "order_ref": CLIENT_ORDER_ID,
                "status": "accepted",
            }
        self.push_broker_update(
            {
                "kind": "order",
                "status": "accepted",
                "external_order_id": EXTERNAL_ORDER_ID,
                "order_ref": CLIENT_ORDER_ID,
                "data_name": PUT,
                "side": "buy",
                "exchange_id": EXCHANGE,
            }
        )
        return {
            "id": EXTERNAL_ORDER_ID,
            "order_ref": CLIENT_ORDER_ID,
            "status": "accepted",
        }

    def cancel_order(self, order_ref: str, dataname: str | None = None) -> Mapping[str, Any]:
        self.cancelled_orders.append({"order_ref": order_ref, "dataname": dataname})
        assert order_ref == EXTERNAL_ORDER_ID
        assert dataname == PUT
        # The venue first confirms cancellation.  It subsequently reports a
        # late fill against the original BT ref.  The duplicate has the same
        # stable trade identity and must not book a second contract.
        self.push_broker_update(
            {
                "kind": "order",
                "status": "canceled",
                "external_order_id": EXTERNAL_ORDER_ID,
                "order_ref": CLIENT_ORDER_ID,
                "data_name": PUT,
                "side": "buy",
                "filled": 0,
                "exchange_id": EXCHANGE,
                "terminal_confirmed": True,
            }
        )
        late_trade = {
            "kind": "trade",
            "bt_order_ref": self._bt_order_ref,
            "external_order_id": EXTERNAL_ORDER_ID,
            "order_ref": CLIENT_ORDER_ID,
            "data_name": PUT,
            "symbol": PUT,
            "side": "buy",
            "offset": "open",
            "size": 1,
            "price": 10.0,
            "trade_id": LATE_TRADE_ID,
            "exchange_id": EXCHANGE,
        }
        self.push_broker_update(late_trade)
        self.push_broker_update(late_trade)
        return {"status": "accepted", "terminal_confirmed": False}


class UnknownIngressAuditBtApiBroker(BtApiBroker):
    """Capture the real Broker association at UNKNOWN ingress, before late fills."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.unknown_ingress_binding: dict[str, int | None] | None = None
        super().__init__(*args, **kwargs)

    def _apply_order_update(self, update: Mapping[str, Any], *, from_query: bool = False):
        if update.get("execution_unknown") is True:
            order = self._lookup_order(update)
            self.unknown_ingress_binding = {
                "matched_order_ref": getattr(order, "ref", None),
                "external_mapping_ref": getattr(
                    self._orders_by_external_id.get(EXTERNAL_ORDER_ID), "ref", None
                ),
                "client_mapping_ref": getattr(
                    self._orders_by_client_ref.get(CLIENT_ORDER_ID), "ref", None
                ),
            }
        return super()._apply_order_update(update, from_query=from_query)


class NativeBrokerProbeStrategy(strategy_module.CtpOptionsHighfreqStrategy):
    """Test-only subclass that consumes one candidate intent through Broker."""

    cancel_on_accepted = True

    def __init__(self) -> None:
        super().__init__()
        self.put_order = None
        self.accepted_binding: dict[str, Any] | None = None
        self.unknown_binding: dict[str, Any] | None = None
        self.tick_callback_symbols: list[str] = []
        self.order_callback_statuses: list[str] = []
        self.trade_callback_sizes: list[float] = []

    def notify_tick(self, tick: Any) -> None:
        self.tick_callback_symbols.append(str(tick.symbol))
        super().notify_tick(tick)

    def _consider_cohort(self, cohort: Any, *, now: CtpCohortNow) -> None:
        intent_count = len(self._ordinary_intents)
        super()._consider_cohort(cohort, now=now)
        if self.put_order is not None or len(self._ordinary_intents) == intent_count:
            return

        self.put_order = self.buy(
            data=self.getdatabyname(PUT),
            size=1,
            price=10.0,
            exectype=bt.Order.Limit,
            offset="open",
            client_order_id=CLIENT_ORDER_ID,
            exchange_id=EXCHANGE,
        )

    def notify_order(self, order: Any) -> None:
        self.order_callback_statuses.append(order.getstatusname())
        if bool(order.info.get("execution_unknown", False)) and order.alive():
            self.unknown_binding = {
                "order_ref": order.ref,
                "external_order_id": order.info.get("external_order_id"),
                "ctp_order_ref": order.info.get("ctp_order_ref"),
            }
            return
        if (
            self.put_order is None
            or order.ref != self.put_order.ref
            or order.status != order.Accepted
        ):
            return
        if self.accepted_binding is not None:
            return
        broker = self.broker
        self.accepted_binding = {
            "external_order_id": order.info.get("external_order_id"),
            "ctp_order_ref": order.info.get("ctp_order_ref"),
            "external_mapping": broker._orders_by_external_id.get(EXTERNAL_ORDER_ID)
            is self.put_order,
            "client_mapping": broker._orders_by_client_ref.get(CLIENT_ORDER_ID) is self.put_order,
        }
        if not self.cancel_on_accepted:
            return
        self.cancel(order)

    def notify_trade(self, trade: Any) -> None:
        self.trade_callback_sizes.append(float(trade.size))


class UnknownRecoveryBrokerProbeStrategy(NativeBrokerProbeStrategy):
    """Keep the first local ACK passive until UNKNOWN ingress is observed."""

    # This probe models only the fail-closed recovery observation: it
    # deliberately never cancels, retries, or creates a replacement order.
    cancel_on_accepted = False


def _fixture_ticks() -> dict[str, list[Any]]:
    """Reuse only Iter25's frozen local quotes as a finite Feed source."""

    ticks: dict[str, list[Any]] = {symbol: [] for symbol in SYMBOLS}
    for event in runner._cohort_events(FIXTURE, BUNDLE, "valid_cohort"):
        ticks[event.data.symbol].append(copy.deepcopy(event.data))
    assert all(len(ticks[symbol]) == 2 for symbol in SYMBOLS)
    return ticks


def test_native_broker_chain_routes_one_candidate_put_and_dedupes_cancel_race_trade(
    forbid_network: list[str],
) -> None:
    """Run the finite Store/3 Feed/Broker/Cerebro path with one local order."""

    decision_clock = DecisionClock()
    transport = FinitePublicTransport(_fixture_ticks(), decision_clock=decision_clock)
    store = BtApiStore(provider="btapi", api=transport, cash=100_000.0, autostart=False)
    broker = BtApiBroker(
        store=store,
        provider="btapi",
        cash=100_000.0,
        value=100_000.0,
        cancel_wait_remote=True,
        market_data_only=False,
        sdk_preflight=False,
        flatten_on_stop=False,
        force_refresh_queries=False,
        account_refresh_interval=3_600.0,
        positions_refresh_interval=3_600.0,
        open_orders_refresh_interval=3_600.0,
    )
    # This test exercises the legacy fake-client route only. It must not
    # become accidental evidence for CTP SDK authorization or read-only gates.
    assert store._sdk_mode is False
    assert broker.get_param("market_data_only") is False
    assert transport.connected is False
    assert store.is_connected is False
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(broker)
    feeds = []
    for symbol in SYMBOLS:
        feed = store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Ticks,
            compression=1,
            backfill_start=False,
            dispatch_ticks=True,
            dispatch_bars=False,
            dispatch_orderbooks=False,
            qcheck=0,
            price_tick=1.0,
            clock=decision_clock,
            ctp_decision_now_provider=decision_clock,
        )
        feeds.append(feed)
        cerebro.adddata(feed, name=symbol)
    cerebro.addstrategy(NativeBrokerProbeStrategy, **runner._strategy_params(CONFIG, BUNDLE))

    [strategy] = cerebro.run(preload=False, runonce=False)

    assert len(strategy._ordinary_intents) == 1
    assert strategy._ordinary_intents[0]["direction"] == "conversion"
    assert strategy.tick_callback_symbols == [FUTURE, CALL, PUT, FUTURE, CALL, PUT]
    assert decision_clock.calls == [
        (FUTURE, 1),
        (CALL, 2),
        (PUT, 3),
        (FUTURE, 4),
        (CALL, 5),
        (PUT, 6),
    ]
    assert [(symbol, sequence) for symbol, sequence, _now in decision_clock.deliveries] == (
        decision_clock.calls
    )
    delivered_now = [now for _symbol, _sequence, now in decision_clock.deliveries]
    assert all(earlier < later for earlier, later in zip(delivered_now, delivered_now[1:]))
    assert decision_clock.monotonic_reads
    assert set(decision_clock.monotonic_reads).issubset(set(delivered_now))
    assert [tick.cohort_decision_now_monotonic_ns for tick in transport.delivered_ticks] == [
        tick.recv_monotonic_ns for tick in transport.delivered_ticks
    ]
    assert [tick.recv_age_seconds for tick in transport.delivered_ticks] == pytest.approx([0.0] * 6)

    order = strategy.put_order
    assert order is not None
    # The canceled terminal must be observed before the late one-lot fill;
    # the actual fill then legitimately changes the local terminal to
    # Completed rather than being silently discarded.
    assert order.status == bt.Order.Completed
    assert strategy.accepted_binding == {
        "external_order_id": EXTERNAL_ORDER_ID,
        "ctp_order_ref": CLIENT_ORDER_ID,
        "external_mapping": True,
        "client_mapping": True,
    }
    accepted_index = strategy.order_callback_statuses.index("Accepted")
    canceled_index = strategy.order_callback_statuses.index("Canceled")
    completed_index = strategy.order_callback_statuses.index("Completed")
    assert accepted_index < canceled_index < completed_index
    assert strategy.order_callback_statuses.count("Accepted") == 1
    assert strategy.order_callback_statuses.count("Canceled") == 1
    assert strategy.order_callback_statuses.count("Completed") == 1
    assert strategy.trade_callback_sizes == [1.0]
    assert order.executed.size == pytest.approx(1.0)
    assert broker.positions[PUT].size == pytest.approx(1.0)
    assert (EXTERNAL_ORDER_ID, PUT, LATE_TRADE_ID) in broker._seen_trade_ids
    assert broker._pending_trade_updates == collections.deque()

    assert transport.submitted_orders == [
        {
            "symbol": PUT,
            "data_name": PUT,
            "bt_order_ref": order.ref,
            "side": "buy",
            "size": 1,
            "price": 10.0,
            "order_type": "limit",
            "valid": None,
            "tradeid": 0,
            "offset": "open",
            "client_order_id": CLIENT_ORDER_ID,
            "exchange_id": EXCHANGE,
            "position_mode": "net",
        }
    ]
    assert transport.cancelled_orders == [{"order_ref": EXTERNAL_ORDER_ID, "dataname": PUT}]
    assert forbid_network == []
    assert transport.broker_updates == collections.deque()
    assert len(feeds) == 3
    assert transport.connect_calls == 1
    assert transport.disconnect_calls == 1
    assert transport.lifecycle == ["connect", "disconnect"]
    assert transport.connected is False
    assert store.is_connected is False
    assert store._started is False
    assert store._sdk_mode is False
    assert broker._live_started is False
    assert broker._startup_ready is False
    assert broker.get_param("market_data_only") is False
    assert broker.get_param("cancel_wait_remote") is True


def test_native_broker_chain_keeps_unknown_put_identity_for_one_late_trade_only(
    forbid_network: list[str],
) -> None:
    """UNKNOWN ingress must retain one order identity until the late trade arrives.

    This is deliberately a local Store/Feed/Broker/Cerebro regression, not an
    SDK, CTP, SimNow, real-fill, or HFT admission result.
    """

    decision_clock = DecisionClock()
    transport = FinitePublicTransport(
        _fixture_ticks(),
        decision_clock=decision_clock,
        unknown_first_put=True,
    )
    store = BtApiStore(provider="btapi", api=transport, cash=100_000.0, autostart=False)
    broker = UnknownIngressAuditBtApiBroker(
        store=store,
        provider="btapi",
        cash=100_000.0,
        value=100_000.0,
        cancel_wait_remote=True,
        market_data_only=False,
        sdk_preflight=False,
        flatten_on_stop=False,
        force_refresh_queries=False,
        account_refresh_interval=3_600.0,
        positions_refresh_interval=3_600.0,
        open_orders_refresh_interval=3_600.0,
    )
    assert store._sdk_mode is False
    assert broker.get_param("market_data_only") is False

    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(broker)
    feeds = []
    for symbol in SYMBOLS:
        feed = store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Ticks,
            compression=1,
            backfill_start=False,
            dispatch_ticks=True,
            dispatch_bars=False,
            dispatch_orderbooks=False,
            qcheck=0,
            price_tick=1.0,
            clock=decision_clock,
            ctp_decision_now_provider=decision_clock,
        )
        feeds.append(feed)
        cerebro.adddata(feed, name=symbol)
    cerebro.addstrategy(
        UnknownRecoveryBrokerProbeStrategy, **runner._strategy_params(CONFIG, BUNDLE)
    )

    [strategy] = cerebro.run(preload=False, runonce=False)

    assert len(strategy._ordinary_intents) == 1
    assert strategy._ordinary_intents[0]["direction"] == "conversion"
    order = strategy.put_order
    assert order is not None
    assert strategy.unknown_binding == {
        "order_ref": order.ref,
        "external_order_id": EXTERNAL_ORDER_ID,
        "ctp_order_ref": CLIENT_ORDER_ID,
    }
    assert broker.unknown_ingress_binding == {
        "matched_order_ref": order.ref,
        "external_mapping_ref": order.ref,
        "client_mapping_ref": order.ref,
    }

    # The initial ACK is held passive, UNKNOWN is seen against the same order,
    # and only its late authoritative fill completes it.  The duplicate TradeID
    # cannot create a second callback, execution bit, or position mutation.
    accepted_index = strategy.order_callback_statuses.index("Accepted")
    completed_index = strategy.order_callback_statuses.index("Completed")
    assert accepted_index < completed_index
    assert strategy.order_callback_statuses.count("Accepted") == 2
    assert strategy.order_callback_statuses.count("Completed") == 1
    assert order.status == bt.Order.Completed
    assert strategy.trade_callback_sizes == [1.0]
    assert order.executed.size == pytest.approx(1.0)
    assert len(order.executed.exbits) == 1
    assert broker.positions[PUT].size == pytest.approx(1.0)
    assert (EXTERNAL_ORDER_ID, PUT, UNKNOWN_LATE_TRADE_ID) in broker._seen_trade_ids
    assert broker._pending_trade_updates == collections.deque()

    assert [
        (payload["symbol"], payload["side"], payload["client_order_id"])
        for payload in transport.submitted_orders
    ] == [(PUT, "buy", CLIENT_ORDER_ID)]
    assert transport.cancelled_orders == []
    assert forbid_network == []
    assert transport.broker_updates == collections.deque()
    assert len(feeds) == 3
    assert transport.connect_calls == 1
    assert transport.disconnect_calls == 1
    assert transport.lifecycle == ["connect", "disconnect"]
    assert transport.connected is False
    assert store.is_connected is False
    assert store._started is False
    assert store._sdk_mode is False
    assert broker._live_started is False
    assert broker._startup_ready is False
    assert broker.get_param("market_data_only") is False
    assert broker.get_param("cancel_wait_remote") is True
