"""Finite local native-broker evidence for the Iteration 23 candidate.

This test deliberately uses a finite in-memory fake transport.  It exercises
the public ``BtApiStore -> 3x BtApiFeed -> BtApiBroker -> Cerebro`` path after
the real low-frequency candidate has formed a conversion signal.  The single
PUT order is then accepted, cancelled, and followed by one duplicate late
trade report.  It is not SimNow/CTP-SDK, external-fill, or profitability
evidence.
"""

from __future__ import annotations

import collections
import datetime as dt
import importlib
import socket
from dataclasses import replace
from typing import Any, Mapping

import backtrader as bt
import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.events import TickEvent
from backtrader.feeds import BarEvidence, ClockMapping
from backtrader.stores.btapistore import BtApiStore
from tests.fixtures.fake_btapi import FakeBtApiClient

runner = importlib.import_module("examples.014_1_ctp_options_lowfreq.run")
strategy_module = importlib.import_module(
    "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
)

BASE = dt.datetime(2026, 9, 10, 1, 0, tzinfo=dt.timezone.utc)
CLOCK_DOMAIN = "iter23-local-native-broker-clock"
RULES_HASH = "iter23-local-native-broker-rules-v1"
EXCHANGE = "CZCE"
FUTURE = "CZCE.SA701"
CALL = "CZCE.SA701C1080"
PUT = "CZCE.SA701P1080"
CLIENT_ORDER_ID = "iter23-native-chain-put-1"
EXTERNAL_ORDER_ID = "iter23-local-ctp-order-1"
LATE_TRADE_ID = "iter23-local-late-trade-1"
COMPLETE_ENTRY_CLIENT_IDS = {
    PUT: "iter23-local-complete-put-1",
    FUTURE: "iter23-local-complete-future-1",
    CALL: "iter23-local-complete-call-1",
}


@pytest.fixture
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail immediately if this finite local fixture tries to open a socket."""

    attempts: list[str] = []

    def blocked(operation: str):
        def reject(*_args: Any, **_kwargs: Any) -> None:
            attempts.append(operation)
            raise AssertionError(f"network operation is forbidden in this local test: {operation}")

        return reject

    monkeypatch.setattr(socket, "create_connection", blocked("socket.create_connection"))
    monkeypatch.setattr(socket.socket, "connect", blocked("socket.socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", blocked("socket.socket.connect_ex"))
    monkeypatch.setattr(socket.socket, "sendto", blocked("socket.socket.sendto"))
    yield attempts
    assert attempts == []


class FixedClock:
    """Feed-only synthetic monotonic clock for deterministic bar sealing."""

    def monotonic_ns(self) -> int:
        return 1_000_000_000


class SealedBarClock:
    """Same-domain decision clock that can advance only after the local run."""

    def __init__(self, *, freeze_entry_callbacks: bool = False) -> None:
        self.strategy: Any = None
        self._risk_advance_ns: int | None = None
        self._freeze_entry_callbacks = freeze_entry_callbacks
        self._entry_callback_ns: int | None = None

    def advance_to_risk_deadline(self, now_monotonic_ns: int) -> None:
        self._risk_advance_ns = int(now_monotonic_ns)

    def advance_to_entry_callback(self, now_monotonic_ns: int) -> None:
        """Expose a local callback at a deterministic, monotonic clock time."""

        callback_ns = int(now_monotonic_ns)
        if self._entry_callback_ns is not None:
            assert callback_ns >= self._entry_callback_ns
        self._entry_callback_ns = callback_ns

    def __call__(self) -> dict[str, Any]:
        current = getattr(self.strategy, "_current_clock_now_ns", None)
        current = 0 if current is None else int(current)
        execution_window = getattr(self.strategy, "_execution_window", None)
        if (
            self._freeze_entry_callbacks
            and getattr(self.strategy, "_state", None) == "ENTERING"
            and execution_window is not None
        ):
            # A finite local callback test must choose an explicit arrival time.
            # Keep completion facts inside the real strategy's fixed 60-second
            # window rather than silently treating later feed progress as a
            # command-response timestamp.
            current = int(execution_window.decision_mono_ns) + 100_000_000
            if self._entry_callback_ns is not None:
                current = max(current, self._entry_callback_ns)
        if self._risk_advance_ns is not None:
            current = max(current, self._risk_advance_ns)
        return {
            "now_monotonic_ns": current,
            "clock_domain_id": CLOCK_DOMAIN,
            "generation": 7,
            "trusted": True,
            "source": "iter23.local-native-broker.fixture-clock",
            "boot_id": "iter23-local-native-broker-fixture-boot",
        }


class FinitePublicCtpTransport(FakeBtApiClient):
    """Public fake-client surface with finite C/P/F ticks and local commands."""

    def __init__(
        self,
        live_ticks: Mapping[str, list[TickEvent]],
        *,
        final_watermark: dt.datetime,
        interleave_symbols: tuple[str, str, str],
    ) -> None:
        super().__init__(
            balance={"cash": 100_000.0, "value": 100_000.0},
            live_ticks=live_ticks,
        )
        self._final_watermark = final_watermark
        self._interleave_symbols = interleave_symbols
        self._next_interleave_symbol = 0
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.lifecycle: list[str] = []
        self._bt_order_ref: int | None = None

    def connect(self) -> None:
        self.connect_calls += 1
        self.lifecycle.append("connect")
        self.connected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.lifecycle.append("disconnect")
        self.connected = False

    def poll_tick(self, dataname: str) -> TickEvent | None:
        expected = self._interleave_symbols[self._next_interleave_symbol]
        if dataname != expected:
            return None
        tick = super().poll_tick(dataname)
        if tick is not None:
            self._next_interleave_symbol = (self._next_interleave_symbol + 1) % len(
                self._interleave_symbols
            )
        return tick

    def is_source_exhausted(self, symbol: str) -> bool:
        return not self.live_ticks.get(symbol)

    def get_source_event_time_watermark(self, _symbol: str) -> dt.datetime:
        return self._final_watermark

    def submit_order(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = dict(payload)
        self.submitted_orders.append(payload)
        self._bt_order_ref = int(payload["bt_order_ref"])
        assert payload["client_order_id"] == CLIENT_ORDER_ID
        assert payload["symbol"] == PUT
        assert payload["side"] == "buy"
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
        assert self._bt_order_ref is not None
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
            "price": 42.0,
            "trade_id": LATE_TRADE_ID,
            "exchange_id": EXCHANGE,
        }
        # A terminal cancel cannot authorize a second order.  The one genuine
        # late fill remains observable; its exact duplicate must not book a
        # second contract.
        self.push_broker_update(late_trade)
        self.push_broker_update(late_trade)
        return {"status": "accepted", "terminal_confirmed": False}


class CompleteEntryPublicCtpTransport(FinitePublicCtpTransport):
    """Finite compatibility transport that completes each planned entry leg.

    This remains a test-only, old public-client fixture.  Its identifiers and
    cumulative fill reports exercise the Backtrader mapping surface only; they
    do not stand in for SDK, CTP, or SimNow execution evidence.
    """

    def __init__(
        self,
        live_ticks: Mapping[str, list[TickEvent]],
        *,
        final_watermark: dt.datetime,
        interleave_symbols: tuple[str, str, str],
    ) -> None:
        super().__init__(
            live_ticks,
            final_watermark=final_watermark,
            interleave_symbols=interleave_symbols,
        )
        self.external_order_ids: dict[int, str] = {}

    def submit_order(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = dict(payload)
        self.submitted_orders.append(payload)
        bt_order_ref = int(payload["bt_order_ref"])
        symbol = str(payload["symbol"])
        side = str(payload["side"])
        client_order_id = str(payload["client_order_id"])
        assert client_order_id == COMPLETE_ENTRY_CLIENT_IDS[symbol]
        assert side in {"buy", "sell"}

        external_order_id = f"iter23-local-complete-order-{bt_order_ref}"
        self.external_order_ids[bt_order_ref] = external_order_id
        # Return the finite fixture's complete cumulative checkpoint directly
        # through the public Store command response.  The real Broker still
        # emits Accepted, maps the identifiers, and then applies Completed
        # before the strategy chooses whether to submit the next leg.
        return {
            "id": external_order_id,
            "order_ref": client_order_id,
            "status": "completed",
            "filled": 1,
            "price": float(payload["price"]),
            "exchange_id": EXCHANGE,
        }


class MappingAuditBtApiBroker(BtApiBroker):
    """Test-only observer of the real Broker's mapping state at Accepted."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.accepted_mapping_snapshots: list[dict[str, Any]] = []
        super().__init__(*args, **kwargs)

    def notify(self, order: Any) -> None:
        if order.status == order.Accepted:
            client_order_id = order.info.get("ctp_order_ref")
            external_order_id = order.info.get("external_order_id")
            self.accepted_mapping_snapshots.append(
                {
                    "ref": order.ref,
                    "client_order_id": client_order_id,
                    "external_order_id": external_order_id,
                    "client_mapping": self._orders_by_client_ref.get(client_order_id) is order,
                    "external_mapping": self._orders_by_external_id.get(external_order_id) is order,
                }
            )
        super().notify(order)


def _tick_at(symbol: str, price: float, ingest_seq: int, timestamp: dt.datetime) -> TickEvent:
    """Build one strict CTP-v2-shaped local quote for a closed 15-minute bar."""

    event = TickEvent(
        timestamp=timestamp.timestamp(),
        symbol=symbol,
        exchange=EXCHANGE,
        asset_type="option" if symbol != FUTURE else "futures",
        local_time=timestamp.timestamp(),
        price=price,
        volume=1.0,
        direction="buy",
        bid_price=price - 1.0,
        ask_price=price + 1.0,
        bid_volume=2.0,
        ask_volume=2.0,
    )
    event.datetime = timestamp.replace(tzinfo=None)
    event.schema_version = "ctp.quote.v2"
    event.volume_semantics = "delta"
    event.cum_volume = 100.0 + ingest_seq
    event.cumulative_volume = 100.0 + ingest_seq
    event.delta_volume = 1.0
    event.volume_complete = True
    event.volume_quality = "CONTINUOUS"
    event.trading_day = "20260910"
    event.action_day = "20260910"
    event.event_time_utc = timestamp
    event.recv_time_utc = timestamp + dt.timedelta(microseconds=ingest_seq)
    event.recv_monotonic_ns = 1_000_000_000 + ingest_seq
    event.received_monotonic_ns = event.recv_monotonic_ns
    event.clock_domain_id = CLOCK_DOMAIN
    event.connection_generation = 7
    event.subscription_epoch = 3
    event.ingest_seq = ingest_seq
    event.rules_hash = RULES_HASH
    event.session_segment = "local-native-broker"
    event.source = "iter23.local-native-broker.fixture"
    event.source_clock_quality = "verified"
    event.receive_clock_quality = "verified"
    event.source_clock_error_ms = 0.0
    event.receive_clock_error_ms = 0.0
    event.freshness_verified = True
    event.execution_eligible = True
    event.quality_flags = ()
    event.event_time_source = "action_day_update_time"
    event.stale = False
    event.stale_reason = ""
    event.continuity_status = "continuous"
    event.snapshot_or_delta = "snapshot"
    return event


def _candidate_ticks() -> (
    tuple[dict[str, Any], dict[str, Any], dict[str, list[TickEvent]], dt.datetime]
):
    """Convert the existing eligible candidate fixture to finite Feed input."""

    config = runner.load_config()
    candidate = config["candidate"]
    assert (candidate["future"], candidate["call"], candidate["put"]) == (FUTURE, CALL, PUT)
    bars_by_symbol = runner.replay_bars(candidate, "eligible")
    live_ticks = {}
    for symbol_index, (symbol, bars) in enumerate(bars_by_symbol.items(), start=1):
        live_ticks[symbol] = [
            _tick_at(
                symbol,
                float(bar["close"]),
                (bar_index * 10) + symbol_index,
                bar["datetime"].replace(tzinfo=dt.timezone.utc) + dt.timedelta(milliseconds=500),
            )
            for bar_index, bar in enumerate(bars, start=1)
        ]
    final_bar_start = bars_by_symbol[FUTURE][-1]["datetime"].replace(tzinfo=dt.timezone.utc)
    return (
        config,
        candidate,
        live_ticks,
        final_bar_start + dt.timedelta(minutes=15, milliseconds=500),
    )


def _closed_bar_evidence(bar: Any) -> BarEvidence:
    """Freeze only the Feed-sealed bar attributes into public evidence."""

    mapping = ClockMapping(
        mapping_id="iter23-local-native-broker-closed-bar-mapping",
        wall_utc_at_anchor=BASE,
        mono_ns_at_anchor=1_000_000_000,
        clock_domain_id=bar.clock_domain_id,
        connection_generation=bar.connection_generation,
        source="iter23.local-native-broker.closed-bar-fixture",
        error_bound_ns=0,
        valid_until_mono_ns=1_000_000_000 + 10**15,
        rules_hash=bar.rules_hash,
        synthetic=True,
    )
    return BarEvidence(
        symbol=bar.symbol,
        exchange=bar.exchange,
        bucket_start=bar.bucket_start,
        bucket_end=bar.bucket_end,
        available_at=bar.available_at,
        seal_received_mono=mapping.map_wall_to_mono_ns(bar.available_at) / 1_000_000_000.0,
        seal_received_at=bar.available_at,
        trading_day=bar.trading_day,
        generation=bar.connection_generation,
        session_segment=bar.session_segment,
        rules_hash=bar.rules_hash,
        quality=bar.quality,
        volume_complete=bar.volume_complete,
        first_ingest_seq=bar.first_ingest_seq,
        last_ingest_seq=bar.last_ingest_seq,
        quote_cutoff_seq=bar.quote_cutoff_seq,
        bar_id=bar.bar_id,
        bar_sequence=bar.bar_sequence,
        closure_reason=bar.closure_reason,
        watermark=bar.watermark,
        max_event_time=bar.max_event_time,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        openinterest=bar.openinterest,
        clock_domain=bar.clock_domain_id,
        clock_mode="replay",
        candidate_id="iter23-local-native-broker-v1",
        timeframe_seconds=900.0,
        trade_count=1,
        complete=bar.complete,
        clock_mapping=mapping,
    )


def _candidate_strategy_kwargs(
    config: Mapping[str, Any], candidate: Mapping[str, Any], sealed_bar_clock: SealedBarClock
) -> dict[str, Any]:
    """Bind every candidate-controlled threshold used by the real strategy."""

    params = dict(config["strategy_params"])
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    params.update(
        candidate_id=f"{config['strategy_id']}-replay-v1",
        future_symbol=candidate["future"],
        call_symbol=candidate["call"],
        put_symbol=candidate["put"],
        strike=candidate["strike"],
        multiplier=candidate["multiplier"],
        discount=candidate["discount"],
        capital_limit=config["budget"]["capital_limit"],
        ordinary_limit=config["budget"]["ordinary_limit"],
        recovery_reserve=config["budget"]["recovery_reserve"],
        first_send_seconds=config["timing"]["first_send_seconds"],
        completion_seconds=config["timing"]["completion_seconds"],
        minimum_hold_seconds=config["timing"]["minimum_hold_seconds"],
        maximum_hold_seconds=config["timing"]["maximum_hold_seconds"],
        risk_bar_max_age_seconds=config["timing"]["risk_bar_max_age_seconds"],
        session_stop_entry_seconds=config["timing"]["session_stop_entry_seconds"],
        session_exit_seconds=config["timing"]["session_exit_seconds"],
        session_handover_seconds=config["timing"]["session_handover_seconds"],
        price_ticks=dict.fromkeys(symbols, params["price_tick"]),
        exchange_limits={
            symbol: {
                "lower": 0.01,
                "upper": 10_000_000.0,
                "source": "synthetic-replay-price-limit-fixture",
            }
            for symbol in symbols
        },
        fee_schedule=dict.fromkeys(
            (
                "open_buy",
                "open_sell",
                "close_buy",
                "close_sell",
                "close_today_buy",
                "close_today_sell",
            ),
            float(params["round_trip_cost"]) / 6.0,
        ),
        exit_reserve=0.0,
        financing_reserve=0.0,
        model_reserve=0.0,
        clock_provider=sealed_bar_clock,
        require_feed_bar_evidence=True,
        bar_evidence_clock_domain=CLOCK_DOMAIN,
        rules_hash=RULES_HASH,
    )
    return params


class NativeBrokerProbeStrategy(strategy_module.CtpOptionsLowfreqStrategy):
    """Test-only adapter: the real conversion state machine submits one PUT."""

    def __init__(self) -> None:
        sealed_bar_clock = self.p.clock_provider
        assert isinstance(sealed_bar_clock, SealedBarClock)
        sealed_bar_clock.strategy = self
        self.entry_attempts: list[dict[str, Any]] = []
        self.submission_attempts: list[dict[str, Any]] = []
        self.order_callback_statuses: list[str] = []
        self.trade_callback_sizes: list[float] = []
        self.accepted_binding: dict[str, Any] | None = None
        self.put_order: Any = None
        self._cancel_requested = False
        super().__init__()

    def _start_entry(
        self,
        direction: str,
        limits: Mapping[str, Mapping[str, float]],
        score: float,
        timestamp: dt.datetime,
    ) -> None:
        self.entry_attempts.append(
            {
                "direction": direction,
                "legs": self._entry_legs_for(direction, limits),
                "timestamp": timestamp,
            }
        )
        super()._start_entry(direction, limits, score, timestamp)

    def _submit_next_leg(self) -> None:
        if self._state == "ENTERING" and self._leg_index < len(self._planned_legs):
            self.submission_attempts.append(dict(self._planned_legs[self._leg_index]))
        super()._submit_next_leg()

    def buy(self, *args: Any, **kwargs: Any) -> Any:
        data = kwargs.get("data")
        if getattr(data, "_name", None) == PUT:
            kwargs.setdefault("client_order_id", CLIENT_ORDER_ID)
            kwargs.setdefault("exchange_id", EXCHANGE)
            kwargs.setdefault("offset", "open")
        order = super().buy(*args, **kwargs)
        if getattr(data, "_name", None) == PUT:
            self.put_order = order
        return order

    def notify_order(self, order: Any) -> None:
        self.order_callback_statuses.append(order.getstatusname())
        super().notify_order(order)
        if (
            self._cancel_requested
            or order.status != order.Accepted
            or getattr(getattr(order, "data", None), "_name", None) != PUT
        ):
            return
        self._cancel_requested = True
        local_order = self.put_order or self.broker.orders.get(order.ref)
        self.accepted_binding = {
            "external_order_id": order.info.get("external_order_id"),
            "ctp_order_ref": order.info.get("ctp_order_ref"),
            "external_mapping": self.broker._orders_by_external_id.get(EXTERNAL_ORDER_ID)
            is local_order,
            "client_mapping": self.broker._orders_by_client_ref.get(CLIENT_ORDER_ID) is local_order,
        }
        self.cancel(order)

    def notify_trade(self, trade: Any) -> None:
        self.trade_callback_sizes.append(float(trade.size))


class CompleteEntryBrokerProbeStrategy(strategy_module.CtpOptionsLowfreqStrategy):
    """Test-only observer for a complete local conversion entry callback chain."""

    def __init__(self) -> None:
        sealed_bar_clock = self.p.clock_provider
        assert isinstance(sealed_bar_clock, SealedBarClock)
        sealed_bar_clock.strategy = self
        self.entry_attempts: list[dict[str, Any]] = []
        self.submission_attempts: list[dict[str, Any]] = []
        self.entry_callback_event_log: list[tuple[str, str, int]] = []
        self.order_callback_statuses: list[tuple[str, str]] = []
        self.accepted_bindings: list[dict[str, Any]] = []
        self.callback_facts: list[dict[str, Any]] = []
        self._attested_order_refs: set[int] = set()
        self._entry_chain_stopped = False
        super().__init__()

    def _start_entry(
        self,
        direction: str,
        limits: Mapping[str, Mapping[str, float]],
        score: float,
        timestamp: dt.datetime,
    ) -> None:
        self.entry_attempts.append(
            {
                "direction": direction,
                "legs": self._entry_legs_for(direction, limits),
                "timestamp": timestamp,
            }
        )
        super()._start_entry(direction, limits, score, timestamp)

    def _submit_next_leg(self) -> None:
        if self._state == "ENTERING" and self._leg_index < len(self._planned_legs):
            leg = dict(self._planned_legs[self._leg_index])
            self.submission_attempts.append(leg)
            sealed_bar_clock = self.p.clock_provider
            assert isinstance(sealed_bar_clock, SealedBarClock)
            self.entry_callback_event_log.append(
                ("submit", str(leg["symbol"]), int(sealed_bar_clock()["now_monotonic_ns"]))
            )
        super()._submit_next_leg()

    def _with_entry_identity(self, side: str, *args: Any, **kwargs: Any) -> Any:
        data = kwargs.get("data")
        symbol = getattr(data, "_name", None)
        if self._state == "ENTERING" and symbol in COMPLETE_ENTRY_CLIENT_IDS:
            kwargs.setdefault("client_order_id", COMPLETE_ENTRY_CLIENT_IDS[symbol])
            kwargs.setdefault("exchange_id", EXCHANGE)
            kwargs.setdefault("offset", "open")
        submit = super().buy if side == "buy" else super().sell
        return submit(*args, **kwargs)

    def buy(self, *args: Any, **kwargs: Any) -> Any:
        return self._with_entry_identity("buy", *args, **kwargs)

    def sell(self, *args: Any, **kwargs: Any) -> Any:
        return self._with_entry_identity("sell", *args, **kwargs)

    def notify_order(self, order: Any) -> None:
        symbol = str(getattr(getattr(order, "data", None), "_name", ""))
        status = order.getstatusname()
        self.order_callback_statuses.append((symbol, status))
        if (
            order.status == order.Completed
            and self._state == "ENTERING"
            and order.ref not in self._attested_order_refs
        ):
            # The legacy public callback carries the completion mapping but not
            # the strategy's scoped execution-fact protocol.  Bind a test-only
            # same-order/same-scope fact before the real state machine decides
            # whether the next protection leg is permitted.
            assert self._execution_window is not None
            assert self._active_decision_id is not None
            assert self._active_basket_id is not None
            self._attested_order_refs.add(order.ref)
            self._submitted_order_ids_by_leg.setdefault(symbol, set()).add(str(order.ref))
            fill_ns = self._execution_window.decision_mono_ns + (
                (self._leg_index + 1) * 100_000_000
            )
            sealed_bar_clock = self.p.clock_provider
            assert isinstance(sealed_bar_clock, SealedBarClock)
            sealed_bar_clock.advance_to_entry_callback(fill_ns)
            self.entry_callback_event_log.append(("completed", symbol, fill_ns))
            fact = {
                "leg": symbol,
                "quantity": 1,
                "status": "completed",
                "fill_lower_ns": fill_ns,
                "fill_upper_ns": fill_ns,
                "source": "synthetic_local_broker_callback",
                "clock_domain": CLOCK_DOMAIN,
                "generation": 7,
                "decision_id": self._active_decision_id,
                "basket_id": self._active_basket_id,
                "order_id": str(order.ref),
                "fact_id": f"iter23-local-fake-callback-{order.ref}",
                "source_identity": "iter23-local-fake-broker-callback-v1",
            }
            self.callback_facts.append(fact)
            self.record_execution_fact(fact)
        super().notify_order(order)
        if order.status == order.Accepted:
            self.accepted_bindings.append(
                {
                    "symbol": symbol,
                    "side": "buy" if order.isbuy() else "sell",
                    "client_order_id": order.info.get("ctp_order_ref"),
                    "external_order_id": order.info.get("external_order_id"),
                }
            )
        if self._state == "OPEN" and not self._entry_chain_stopped:
            # The finite fixture ends at a completed entry.  Stop Cerebro
            # instead of inventing later bar decisions or a fake exit path.
            self._entry_chain_stopped = True
            self.env.runstop()


def test_native_broker_chain_routes_one_conversion_put_then_dedupes_cancel_race_trade(
    forbid_network: list[str],
) -> None:
    """The real Iter23 candidate stays fail-safe across a local cancel/fill race."""

    config, candidate, live_ticks, final_watermark = _candidate_ticks()
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    sealed_bar_clock = SealedBarClock()
    transport = FinitePublicCtpTransport(
        live_ticks,
        final_watermark=final_watermark,
        interleave_symbols=symbols,
    )
    metadata = {
        symbol: {
            "tick_size": 1.0,
            "contract_multiplier": candidate["multiplier"],
            "min_size": 1,
            "lot_size": 1,
            "quantity_step": 1,
            "currency": "CNY",
        }
        for symbol in symbols
    }
    store = BtApiStore(
        provider="btapi",
        api=transport,
        cash=float(config["budget"]["capital_limit"]),
        contract_metadata=metadata,
        autostart=False,
    )
    broker = BtApiBroker(
        store=store,
        provider="btapi",
        cash=float(config["budget"]["capital_limit"]),
        value=float(config["budget"]["capital_limit"]),
        contract_metadata=metadata,
        cancel_wait_remote=True,
        market_data_only=False,
        sdk_preflight=False,
        flatten_on_stop=False,
        force_refresh_queries=False,
        account_refresh_interval=3_600.0,
        positions_refresh_interval=3_600.0,
        open_orders_refresh_interval=3_600.0,
    )
    # The fake supports only the old public compatibility branch.  This test
    # must never become evidence of SDK authorization or a CTP session.
    assert store._sdk_mode is False
    assert broker.get_param("market_data_only") is False
    assert transport.connected is False
    assert store.is_connected is False

    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(broker)
    feeds = []
    for symbol in symbols:
        feed = store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Minutes,
            compression=15,
            backfill_start=False,
            dispatch_ticks=False,
            dispatch_bars=True,
            qcheck=0,
            price_tick=1.0,
            clock=FixedClock(),
            closed_bar_evidence_provider=lambda bar: replace(
                _closed_bar_evidence(bar),
                candidate_id=f"{config['strategy_id']}-replay-v1",
            ),
        )
        feeds.append(feed)
        cerebro.adddata(feed, name=symbol)
    cerebro.addstrategy(
        NativeBrokerProbeStrategy,
        **_candidate_strategy_kwargs(config, candidate, sealed_bar_clock),
    )

    [strategy] = cerebro.run(preload=False, runonce=False)

    assert [entry["direction"] for entry in strategy.entry_attempts] == ["conversion"]
    assert strategy.entry_attempts[0]["legs"] == [
        {"symbol": PUT, "side": "buy", "price": 42.0, "size": 1},
        {"symbol": FUTURE, "side": "buy", "price": 1002.0, "size": 1},
        {"symbol": CALL, "side": "sell", "price": 138.0, "size": 1},
    ]
    # The cancel terminal forbids advancing to F or the naked option sell C.
    assert strategy.submission_attempts == [strategy.entry_attempts[0]["legs"][0]]
    assert strategy.put_order is not None
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

    order = strategy.put_order
    assert order.status == bt.Order.Completed
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
            "price": 42.0,
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

    # The strategy never treats a late local fill as authority to send a
    # second leg.  It remains stopped with possible exposure and its own
    # independent hold projection raises the recovery posture at deadline.
    assert strategy._state == "HALTED"
    assert strategy._possible_exposure is True
    assert "ORDER_TERMINAL_WITHOUT_FULL_FILL" in strategy._rejections
    assert strategy._basket_status == "ORDINARY_ENTRY_PROJECTED"
    assert strategy._current_clock_now_ns is not None
    sealed_bar_clock.advance_to_risk_deadline(
        strategy._current_clock_now_ns + (int(strategy.p.maximum_hold_seconds) + 1) * 1_000_000_000
    )
    strategy.notify_idle()
    assert strategy._state == "HALTED"
    assert strategy._basket_status == "RECOVERY_REQUIRED"
    assert any(event["kind"] == "risk_deadline_reached" for event in strategy._cycle_events)
    assert len(transport.submitted_orders) == 1
    assert len(transport.cancelled_orders) == 1

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


def test_native_broker_chain_completes_conversion_entry_one_leg_at_a_time(
    forbid_network: list[str],
) -> None:
    """A local callback fixture may advance only P-buy -> F-buy -> C-sell.

    This is deliberately narrower than an execution admission test: the
    transport is a finite old public-client fake and the strategy receives
    test-only, scoped completion facts.  It proves the Store/Feed/Broker/
    Cerebro callback handoff and the strategy's protection-leg ordering, not
    a CTP SDK, SimNow, or actual-fill result.
    """

    config, candidate, live_ticks, final_watermark = _candidate_ticks()
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    sealed_bar_clock = SealedBarClock(freeze_entry_callbacks=True)
    transport = CompleteEntryPublicCtpTransport(
        live_ticks,
        final_watermark=final_watermark,
        interleave_symbols=symbols,
    )
    metadata = {
        symbol: {
            "tick_size": 1.0,
            "contract_multiplier": candidate["multiplier"],
            "min_size": 1,
            "lot_size": 1,
            "quantity_step": 1,
            "currency": "CNY",
        }
        for symbol in symbols
    }
    store = BtApiStore(
        provider="btapi",
        api=transport,
        cash=float(config["budget"]["capital_limit"]),
        contract_metadata=metadata,
        autostart=False,
    )
    broker = MappingAuditBtApiBroker(
        store=store,
        provider="btapi",
        cash=float(config["budget"]["capital_limit"]),
        value=float(config["budget"]["capital_limit"]),
        contract_metadata=metadata,
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
    for symbol in symbols:
        feed = store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Minutes,
            compression=15,
            backfill_start=False,
            dispatch_ticks=False,
            dispatch_bars=True,
            qcheck=0,
            price_tick=1.0,
            clock=FixedClock(),
            closed_bar_evidence_provider=lambda bar: replace(
                _closed_bar_evidence(bar),
                candidate_id=f"{config['strategy_id']}-replay-v1",
            ),
        )
        feeds.append(feed)
        cerebro.adddata(feed, name=symbol)
    params = _candidate_strategy_kwargs(config, candidate, sealed_bar_clock)
    # This scenario isolates the normal entry sequence.  It does not invent an
    # exit signal or make a claim about a real holding/exit lifecycle.
    params["minimum_holding_minutes"] = 120
    params["minimum_hold_seconds"] = 7_200
    params["maximum_hold_seconds"] = 7_200
    cerebro.addstrategy(CompleteEntryBrokerProbeStrategy, **params)

    [strategy] = cerebro.run(preload=False, runonce=False)

    assert not strategy._quarantined_execution_facts, strategy._quarantined_execution_facts
    assert strategy._state == "OPEN", (strategy._rejections, strategy._fill_timing)

    expected_legs = [
        {"symbol": PUT, "side": "buy", "price": 42.0, "size": 1},
        {"symbol": FUTURE, "side": "buy", "price": 1002.0, "size": 1},
        {"symbol": CALL, "side": "sell", "price": 138.0, "size": 1},
    ]
    assert [entry["direction"] for entry in strategy.entry_attempts] == ["conversion"]
    assert strategy.entry_attempts[0]["legs"] == expected_legs
    assert strategy.submission_attempts == expected_legs, {
        "state": strategy._state,
        "rejections": strategy._rejections,
        "fill_timing": strategy._fill_timing,
        "quarantined": strategy._quarantined_execution_facts,
        "callback_facts": strategy.callback_facts,
    }
    assert [event[:2] for event in strategy.entry_callback_event_log] == [
        ("submit", PUT),
        ("completed", PUT),
        ("submit", FUTURE),
        ("completed", FUTURE),
        ("submit", CALL),
        ("completed", CALL),
    ]
    entry_event_time = {
        (kind, symbol): timestamp for kind, symbol, timestamp in strategy.entry_callback_event_log
    }
    assert entry_event_time[("submit", FUTURE)] >= entry_event_time[("completed", PUT)]
    assert entry_event_time[("submit", CALL)] >= entry_event_time[("completed", FUTURE)]

    submitted = transport.submitted_orders
    assert [
        (payload["symbol"], payload["side"], payload["size"], payload["price"])
        for payload in submitted
    ] == [
        (PUT, "buy", 1, 42.0),
        (FUTURE, "buy", 1, 1002.0),
        (CALL, "sell", 1, 138.0),
    ]
    assert [payload["offset"] for payload in submitted] == ["open", "open", "open"]
    assert [payload["client_order_id"] for payload in submitted] == [
        COMPLETE_ENTRY_CLIENT_IDS[PUT],
        COMPLETE_ENTRY_CLIENT_IDS[FUTURE],
        COMPLETE_ENTRY_CLIENT_IDS[CALL],
    ]
    assert len({payload["bt_order_ref"] for payload in submitted}) == 3
    assert transport.cancelled_orders == []

    accepted = [
        (symbol, status)
        for symbol, status in strategy.order_callback_statuses
        if status == "Accepted"
    ]
    completed = [
        (symbol, status)
        for symbol, status in strategy.order_callback_statuses
        if status == "Completed"
    ]
    assert accepted == [(PUT, "Accepted"), (FUTURE, "Accepted"), (CALL, "Accepted")]
    assert completed == [(PUT, "Completed"), (FUTURE, "Completed"), (CALL, "Completed")]
    assert not any(
        status in {"Canceled", "Partial", "Rejected", "Expired"}
        for _symbol, status in strategy.order_callback_statuses
    )
    assert [binding["symbol"] for binding in strategy.accepted_bindings] == [
        PUT,
        FUTURE,
        CALL,
    ]
    assert [binding["side"] for binding in strategy.accepted_bindings] == ["buy", "buy", "sell"]
    assert [binding["client_order_id"] for binding in strategy.accepted_bindings] == [
        COMPLETE_ENTRY_CLIENT_IDS[PUT],
        COMPLETE_ENTRY_CLIENT_IDS[FUTURE],
        COMPLETE_ENTRY_CLIENT_IDS[CALL],
    ]
    expected_external_order_ids = [
        transport.external_order_ids[payload["bt_order_ref"]] for payload in submitted
    ]
    assert [binding["external_order_id"] for binding in strategy.accepted_bindings] == (
        expected_external_order_ids
    )
    assert len(set(expected_external_order_ids)) == 3
    assert [snapshot["client_order_id"] for snapshot in broker.accepted_mapping_snapshots] == [
        COMPLETE_ENTRY_CLIENT_IDS[PUT],
        COMPLETE_ENTRY_CLIENT_IDS[FUTURE],
        COMPLETE_ENTRY_CLIENT_IDS[CALL],
    ]
    assert [snapshot["ref"] for snapshot in broker.accepted_mapping_snapshots] == [
        payload["bt_order_ref"] for payload in submitted
    ]
    assert [snapshot["external_order_id"] for snapshot in broker.accepted_mapping_snapshots] == (
        expected_external_order_ids
    )
    assert all(
        snapshot["client_mapping"] and snapshot["external_mapping"]
        for snapshot in broker.accepted_mapping_snapshots
    )

    assert strategy._state == "OPEN"
    assert strategy._basket_status == "OPEN_UNVERIFIED"
    assert strategy._rejections == []
    assert strategy._confirmed_fill_by_leg == {PUT: 1.0, FUTURE: 1.0, CALL: 1.0}
    assert len(strategy.callback_facts) == 3
    assert len(strategy._quarantined_execution_facts) == 0
    assert {fact["order_id"] for fact in strategy.callback_facts} == {
        str(payload["bt_order_ref"]) for payload in submitted
    }
    assert {fact["clock_domain"] for fact in strategy.callback_facts} == {CLOCK_DOMAIN}
    assert {fact["generation"] for fact in strategy.callback_facts} == {7}
    assert [fact["fill_lower_ns"] for fact in strategy.callback_facts] == sorted(
        fact["fill_lower_ns"] for fact in strategy.callback_facts
    )
    assert sealed_bar_clock._entry_callback_ns == strategy.callback_facts[-1]["fill_upper_ns"]
    assert broker.positions[PUT].size == pytest.approx(1.0)
    assert broker.positions[FUTURE].size == pytest.approx(1.0)
    assert broker.positions[CALL].size == pytest.approx(-1.0)

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
