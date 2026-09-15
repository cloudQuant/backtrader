"""Bounded, zero-write Set-2 engineering observation coverage for Iteration 24.

The fixture deliberately drives the real Store/Feed/Broker/Cerebro path with
three strict CTP-v2 streams.  It never opens a socket or reads an environment
file: the SDK-shaped object, live clock mapping, feed clock and closed-bar
evidence provider are all injected by the test.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib
import threading
from types import MappingProxyType, SimpleNamespace
from typing import Any, Dict, Iterable, Mapping

import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.events import TickEvent
from backtrader.feeds import BarEvidence, ClockMapping
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore
from tests.fixtures.fake_btapi import FakeBtApiClient

runner = importlib.import_module("examples.014_2_ctp_options_midfreq.run")
adapter = importlib.import_module("examples.014_2_ctp_options_midfreq.simnow_adapter")

CONFIG = runner.load_config()
CANDIDATE = CONFIG["candidate"]
FUTURE = CANDIDATE["contracts"]["future"]
CALL = CANDIDATE["contracts"]["call"]
PUT = CANDIDATE["contracts"]["put"]
SYMBOLS = (FUTURE, CALL, PUT)
BASE = dt.datetime(2026, 1, 5, 9, 0, tzinfo=dt.timezone.utc)
LIVE_DOMAIN = "iter24-engineering-live-clock"


class FixedLiveClock:
    """An explicitly injected monotonic clock in the mapping's domain."""

    def monotonic_ns(self) -> int:
        return 1_000_000_000


def _live_mapping(domain: str = LIVE_DOMAIN, *, synthetic: bool = False) -> ClockMapping:
    return ClockMapping(
        mapping_id=f"iter24-engineering-mapping:{domain}",
        wall_utc_at_anchor=BASE,
        mono_ns_at_anchor=1_000_000_000,
        clock_domain_id=domain,
        connection_generation=7,
        source="tests.iter24.engineering.live-clock",
        error_bound_ns=0,
        valid_until_mono_ns=1_000_000_000 + 10**15,
        rules_hash=CANDIDATE["rules_hash"],
        synthetic=synthetic,
    )


def _tick_at(symbol: str, *, timestamp: dt.datetime, ingest_seq: int) -> TickEvent:
    """Build a strict CTP-v2 source event carrying the injected live domain."""

    bid, ask, bid_qty, ask_qty = (
        (999.0, 1001.0, 2.0, 2.0)
        if symbol == FUTURE
        else ((9.0, 11.0, 1.0, 3.0) if symbol == CALL else (9.0, 11.0, 3.0, 1.0))
    )
    mapping = _live_mapping()
    received_at = timestamp + dt.timedelta(microseconds=1)
    event_id = f"iter24-engineering:{symbol}:{ingest_seq}"
    event = TickEvent(
        timestamp=timestamp.timestamp(),
        symbol=symbol,
        exchange=CANDIDATE["exchange"],
        asset_type="ctp-future" if symbol == FUTURE else "ctp-option",
        local_time=timestamp.timestamp(),
        exchange_time=timestamp.timestamp(),
        received_wall_time=received_at.timestamp(),
        received_monotonic_ns=mapping.map_wall_to_mono_ns(received_at),
        sequence=ingest_seq,
        snapshot_or_delta="snapshot",
        continuity_status="continuous",
        source="tests.iter24.engineering.source",
        event_id=event_id,
        price=(bid + ask) / 2.0,
        volume=1.0,
        direction="buy",
        trade_id=event_id,
        bid_price=bid,
        ask_price=ask,
        bid_volume=bid_qty,
        ask_volume=ask_qty,
    )
    event.datetime = timestamp.replace(tzinfo=None)
    event.schema_version = "ctp.quote.v2"
    event.volume_semantics = "delta"
    event.cum_volume = 100.0 + ingest_seq
    event.cumulative_volume = 100.0 + ingest_seq
    event.delta_volume = 1.0
    event.volume_complete = True
    event.volume_quality = "CONTINUOUS"
    event.trading_day = timestamp.strftime("%Y%m%d")
    event.action_day = event.trading_day
    event.event_time_utc = timestamp
    event.recv_time_utc = received_at
    event.recv_monotonic_ns = mapping.map_wall_to_mono_ns(received_at)
    event.received_monotonic_ns = event.recv_monotonic_ns
    event.clock_domain_id = LIVE_DOMAIN
    event.connection_generation = 7
    event.subscription_epoch = 1
    event.ingest_seq = ingest_seq
    event.rules_hash = CANDIDATE["rules_hash"]
    event.session_segment = "engineering-minute"
    event.source_clock_quality = "verified"
    event.receive_clock_quality = "verified"
    event.source_clock_error_ms = 0.0
    event.receive_clock_error_ms = 0.0
    event.freshness_verified = True
    event.execution_eligible = True
    event.quality_flags = ()
    event.event_time_source = "exchange-event-fixture"
    event.stale = False
    event.stale_reason = ""
    return event


def _source_snapshot(
    tick: TickEvent, *, clock_mapping: ClockMapping, clock_mode: str
) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "event_id": tick.event_id,
            "symbol": tick.symbol,
            "exchange": tick.exchange,
            "event_time": tick.event_time_utc,
            "received_at": tick.recv_time_utc,
            "received_monotonic_ns": tick.received_monotonic_ns,
            "ingest_seq": tick.ingest_seq,
            "generation": tick.connection_generation,
            "trading_day": tick.trading_day,
            "session_segment": tick.session_segment,
            "rules_hash": tick.rules_hash,
            "clock_domain": clock_mapping.clock_domain_id,
            "clock_mode": clock_mode,
            "candidate_id": CANDIDATE["candidate_id"],
            "quality": "GOOD",
            "volume_complete": tick.volume_complete,
            "bid": tick.bid_price,
            "ask": tick.ask_price,
            "bid_qty": tick.bid_volume,
            "ask_qty": tick.ask_volume,
            "last": tick.price,
            "source": tick.source,
            "event_time_source": tick.event_time_source,
            "source_clock_error_ms": tick.source_clock_error_ms,
            "receive_clock_error_ms": tick.receive_clock_error_ms,
        }
    )


def _ticks(minutes: int = 2) -> Dict[str, list[TickEvent]]:
    result: Dict[str, list[TickEvent]] = {symbol: [] for symbol in SYMBOLS}
    for minute in range(minutes):
        for second in range(60):
            timestamp = BASE + dt.timedelta(minutes=minute, seconds=second)
            for symbol_index, symbol in enumerate(SYMBOLS, start=1):
                result[symbol].append(
                    _tick_at(
                        symbol,
                        timestamp=timestamp,
                        ingest_seq=(minute + 1) * 100_000 + second * 3 + symbol_index,
                    )
                )
    return result


class LiveFixtureApi(FakeBtApiClient):
    """A non-EOF source so the observation ends only through its deadline."""

    def __init__(
        self,
        *,
        live_ticks: Mapping[str, Iterable[TickEvent]],
        session_state: Mapping[str, Any] | None = None,
        session_state_available: bool = True,
    ) -> None:
        super().__init__(live_ticks=live_ticks)
        self._symbols = tuple(SYMBOLS)
        self._next_symbol = 0
        self.connect_calls = 0
        self.disconnect_calls = 0
        # Exposes the public managed-CTP session surface that the real Store
        # must bind after connection.  This local fixture remains offline.
        self.exchange_kwargs = {"CTP___FUTURE": {}}
        self.session_state_available = session_state_available
        self.ctp_session_state_calls: list[str] = []
        self.execution_route_calls: list[str] = []
        self.execution_configuration_calls: list[dict[str, Any]] = []
        self.session_state = {
            "environment_profile": "set2_7x24_4000x",
            "account_fingerprint": "test-iter24-account-fingerprint",
            "read_only_ready": True,
            "execution_gate_armed": False,
            "connection_generation": 7,
        }
        if session_state is not None:
            self.session_state.update(dict(session_state))

    def connect(self) -> None:
        self.connect_calls += 1
        super().connect()

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        super().disconnect()

    def poll_tick(self, dataname: str) -> Any:
        if dataname != self._symbols[self._next_symbol]:
            return None
        tick = super().poll_tick(dataname)
        if tick is not None:
            self._next_symbol = (self._next_symbol + 1) % len(self._symbols)
        return tick

    def get_ctp_session_state(self, exchange_name: str = "CTP___FUTURE") -> dict[str, Any]:
        assert exchange_name == "CTP___FUTURE"
        self.ctp_session_state_calls.append(exchange_name)
        if not self.session_state_available:
            raise RuntimeError("fixture session state unavailable")
        return {"connected": self.connected, "ready": True, **self.session_state}

    def configure_execution(self, config: Mapping[str, Any]) -> None:
        self.execution_configuration_calls.append(dict(config))

    def arm_execution_from_preflight(self, *_args: Any, **_kwargs: Any) -> None:
        self.execution_route_calls.append("arm_execution_from_preflight")

    def arm_execution_from_approval(self, *_args: Any, **_kwargs: Any) -> None:
        self.execution_route_calls.append("arm_execution_from_approval")

    def confirm_ctp_settlement_from_approval(self, *_args: Any, **_kwargs: Any) -> None:
        self.execution_route_calls.append("confirm_ctp_settlement_from_approval")

    def custom_execution_route(self, *_args: Any, **_kwargs: Any) -> None:
        self.execution_route_calls.append("custom_execution_route")


class LiveEvidenceProvider:
    """Make immutable BarEvidence only from the source quote snapshots."""

    def __init__(
        self,
        source_ticks: Mapping[str, Iterable[TickEvent]],
        mapping: ClockMapping,
        *,
        mode: str = "live",
    ) -> None:
        self.mapping = mapping
        self.mode = mode
        self.emitted: list[BarEvidence] = []
        self._by_bucket: Dict[tuple[str, dt.datetime], tuple[Mapping[str, Any], ...]] = {}
        buckets: Dict[tuple[str, dt.datetime], list[Mapping[str, Any]]] = {}
        for symbol, ticks in source_ticks.items():
            for tick in ticks:
                snapshot = _source_snapshot(tick, clock_mapping=mapping, clock_mode=mode)
                bucket_end = snapshot["event_time"].replace(second=0, microsecond=0) + dt.timedelta(
                    minutes=1
                )
                buckets.setdefault((symbol, bucket_end), []).append(snapshot)
        for key, entries in buckets.items():
            self._by_bucket[key] = tuple(sorted(entries, key=lambda item: int(item["ingest_seq"])))

    def __call__(self, bar: Any) -> BarEvidence:
        quotes = tuple(
            quote
            for quote in self._by_bucket[(bar.symbol, bar.bucket_end)]
            if bar.first_ingest_seq <= int(quote["ingest_seq"]) <= bar.last_ingest_seq
        )
        assert quotes
        evidence = BarEvidence(
            symbol=bar.symbol,
            exchange=bar.exchange,
            bucket_start=bar.bucket_start,
            bucket_end=bar.bucket_end,
            available_at=bar.available_at,
            seal_received_mono=self.mapping.map_wall_to_mono_ns(bar.available_at) / 1_000_000_000.0,
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
            quote_events=quotes,
            clock_domain=self.mapping.clock_domain_id,
            clock_mode=self.mode,
            candidate_id=CANDIDATE["candidate_id"],
            timeframe_seconds=60.0,
            trade_count=bar.trade_count,
            complete=bar.complete,
            clock_mapping=self.mapping,
        )
        self.emitted.append(evidence)
        return evidence


def _run_live_observation(
    *,
    api: LiveFixtureApi | None = None,
    evidence_mapping: ClockMapping | None = None,
    trusted_mapping: ClockMapping | None = None,
    evidence_mode: str = "live",
) -> tuple[dict[str, Any], LiveFixtureApi, LiveEvidenceProvider]:
    source = _ticks()
    api = api or LiveFixtureApi(live_ticks=copy.deepcopy(source))
    evidence_mapping = evidence_mapping or _live_mapping()
    provider = LiveEvidenceProvider(source, evidence_mapping, mode=evidence_mode)
    report = runner.run_engineering_observation(
        copy.deepcopy(CONFIG),
        api=api,
        environment_profile="simnow_second_7x24",
        run_seconds=1.0,
        feed_clock=FixedLiveClock(),
        clock_mapping=trusted_mapping or _live_mapping(),
        closed_bar_evidence_provider=provider,
    )
    return report, api, provider


def _contains_raw_value(value: Any, raw_value: str) -> bool:
    """Check a report for one secret without rendering its large diagnostics."""

    if isinstance(value, Mapping):
        return any(_contains_raw_value(item, raw_value) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_raw_value(item, raw_value) for item in value)
    return value == raw_value


def test_engineering_observation_runs_real_three_feed_strategy_with_live_evidence() -> None:
    report, api, provider = _run_live_observation()

    assert report["status"] == "PASS_ENGINEERING_STRATEGY_OBSERVATION"
    assert report["mode"] == "shadow"
    assert report["purpose"] == "observation"
    assert "environment_profile" not in report
    assert report["session_binding"] == {
        "source": "BtApiStore.get_ctp_session_state",
        "session_environment_profile": "set2_7x24_4000x",
        "profile_family_prefix": "set2_7x24",
        "account_fingerprint_sha256": hashlib.sha256(
            b"test-iter24-account-fingerprint"
        ).hexdigest(),
        "read_only_ready": True,
        "execution_armed": False,
        "connection_generation": 7,
        "clock_mapping_id": "iter24-engineering-mapping:iter24-engineering-live-clock",
        "clock_mapping_generation": 7,
    }
    assert not _contains_raw_value(report, "test-iter24-account-fingerprint")
    assert api.ctp_session_state_calls
    assert report["chain"] == {
        "store": "BtApiStore",
        "feeds": ["BtApiFeed", "BtApiFeed", "BtApiFeed"],
        "broker": "BtApiBroker",
        "cerebro": "Cerebro",
        "strategy": "CTPOptionsMidFrequencyStrategy",
    }
    assert report["duration"]["requested_seconds"] == 1.0
    assert report["duration"]["deadline_stop_requested"] is True
    assert report["feed_evidence"]["accepted_complete_three_leg_input"] is True
    assert report["feed_evidence"]["clock_mode"] == "live"
    assert report["feed_evidence"]["clock_domain"] == LIVE_DOMAIN
    assert len(provider.emitted) >= 3
    assert {evidence.symbol for evidence in provider.emitted} == set(SYMBOLS)
    assert all(evidence.clock_mapping.synthetic is False for evidence in provider.emitted)
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert report["write_guard"]["forbidden_write_attempts"] == {}
    assert report["adapter_scoped_write_attempts"] == 0
    assert report["external_trade_writes"] == "NOT_PROVEN"
    assert report["external_trade_writes_basis"] == (
        "NOT_PROVEN: the adapter membrane and market_data_only Broker only observe "
        "adapter-routed attempts; they cannot attest raw external provider writes."
    )
    # The adapter does not rewrite this field, so it exercises the strategy's
    # own engineering-observation report branch rather than only its wrapper.
    assert report["strategy"]["external_network_requests"] == "NOT_PROVEN"
    assert report["strategy"]["external_trade_writes"] == "NOT_PROVEN"
    assert report["strategy"]["adapter_scoped_write_attempts"] == 0
    assert report["shutdown"]["status"] == "OBSERVATION_ONLY"
    assert report["shutdown"]["store_shutdown_state"] == "PASS"
    assert report["gates"] == {
        "G3_first_set_read_only": "NOT_RUN_ENGINEERING_STRATEGY_OBSERVATION",
        "G3_evaluation": "NOT_APPLICABLE_ENGINEERING_ONLY",
        "G4_simnow_mechanical": "NOT_RUN",
    }


def test_engineering_observation_accepts_one_transferred_store_without_rewrapping_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The supplied Store is the only Store and owns exactly one SDK lifecycle."""

    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))
    store = adapter.BtApiStore(
        provider="btapi",
        api=api,
        config={
            "market_data_only": True,
            "execution_config": {"market_data_only": True},
        },
        autostart=False,
    )
    store.start()
    provider = LiveEvidenceProvider(source, _live_mapping())

    def unexpected_second_store(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("store= observation must not construct a second BtApiStore")

    def forbidden_sdk_api(self: BtApiStore) -> Any:
        del self
        raise AssertionError("store= observation must not access store.sdk_api")

    # The instance above is deliberately created before replacing the adapter
    # constructor.  The observation must use that exact instance and must not
    # obtain/re-wrap ``store.sdk_api`` into another Store.
    monkeypatch.setattr(adapter, "BtApiStore", unexpected_second_store)
    monkeypatch.setattr(BtApiStore, "sdk_api", property(forbidden_sdk_api))

    report = runner.run_engineering_observation(
        copy.deepcopy(CONFIG),
        api=None,
        store=store,
        store_ownership="transfer",
        environment_profile="simnow_second_7x24",
        run_seconds=1.0,
        feed_clock=FixedLiveClock(),
        clock_mapping=_live_mapping(),
        closed_bar_evidence_provider=provider,
    )

    assert report["status"] == "PASS_ENGINEERING_STRATEGY_OBSERVATION"
    assert report["chain"]["store"] == "BtApiStore"
    assert report["store_ownership"] == "INJECTED_STORE_LIFECYCLE_TRANSFERRED"
    assert api.connect_calls == 1
    assert api.disconnect_calls == 1
    assert api.connected is False
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert report["adapter_scoped_write_attempts"] == 0
    assert report["external_trade_writes"] == "NOT_PROVEN"


def test_store_transfer_rejects_an_overridden_write_audit_recorder() -> None:
    """The public Store audit must remain the base aggregate implementation."""

    class NoOpRecorderStore(BtApiStore):
        def record_market_data_only_broker_rejection(self, _operation: str) -> None:
            return None

    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))
    store = NoOpRecorderStore(
        provider="btapi",
        api=api,
        config={"execution_config": {"market_data_only": True}},
        autostart=False,
    )
    store.start()
    try:
        with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
            adapter._require_injected_store_transfer(store, ownership="transfer")

        assert error.value.code == "INJECTED_STORE_AUDIT_CONTRACT_REQUIRED"
        assert store.is_connected is True
        assert api.connect_calls == 1
        assert api.disconnect_calls == 0
    finally:
        store.stop()

    assert api.disconnect_calls == 1


def test_engineering_observation_reuses_connected_preflight_store_without_second_connect() -> None:
    """A read-only preflight may transfer its live Store and generation in-place."""

    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))
    store = adapter.BtApiStore(
        provider="btapi",
        api=api,
        config={
            "market_data_only": True,
            "execution_config": {"market_data_only": True},
        },
        autostart=False,
    )
    # This models the operator's read-only bundle preflight connecting the
    # Store before explicitly transferring its lifecycle to the strategy.
    store.start()
    assert api.connect_calls == 1
    assert store.is_connected is True
    provider = LiveEvidenceProvider(source, _live_mapping())

    report = runner.run_engineering_observation(
        copy.deepcopy(CONFIG),
        api=None,
        store=store,
        store_ownership="transfer",
        environment_profile="simnow_second_7x24",
        run_seconds=1.0,
        feed_clock=FixedLiveClock(),
        clock_mapping=_live_mapping(),
        closed_bar_evidence_provider=provider,
    )

    assert report["status"] == "PASS_ENGINEERING_STRATEGY_OBSERVATION"
    assert report["session_binding"]["connection_generation"] == 7
    assert api.connect_calls == 1
    assert api.disconnect_calls == 1
    assert api.connected is False
    assert store.is_connected is False
    assert api.submitted_orders == []
    assert api.cancelled_orders == []


@pytest.mark.parametrize(
    ("health_key", "busy_value"),
    (
        ("read_only_metadata_probe_active", True),
        ("broker_update_queue_depth", 1),
        ("broker_update_dropped", 1),
        ("risk_state_latched", True),
        ("funding_pending", 1),
    ),
)
def test_busy_preflight_store_is_not_transferred_or_stopped(
    monkeypatch: pytest.MonkeyPatch, health_key: str, busy_value: Any
) -> None:
    """An active preflight probe is not silently claimed by the strategy graph."""

    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))
    store = adapter.BtApiStore(
        provider="btapi",
        api=api,
        config={"market_data_only": True, "execution_config": {"market_data_only": True}},
        autostart=False,
    )
    store.start()
    original_health = store.get_command_health

    def busy_health() -> Mapping[str, Any]:
        health = dict(original_health())
        health[health_key] = busy_value
        return health

    monkeypatch.setattr(store, "get_command_health", busy_health)
    try:
        with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
            runner.run_engineering_observation(
                copy.deepcopy(CONFIG),
                api=None,
                store=store,
                store_ownership="transfer",
                environment_profile="simnow_second_7x24",
                run_seconds=1.0,
                feed_clock=FixedLiveClock(),
                clock_mapping=_live_mapping(),
                closed_bar_evidence_provider=LiveEvidenceProvider(source, _live_mapping()),
            )

        assert error.value.code == "INJECTED_STORE_BUSY"
        assert store.is_connected is True
        assert api.connect_calls == 1
        assert api.disconnect_calls == 0
    finally:
        monkeypatch.setattr(store, "get_command_health", original_health)
        store.stop()

    assert api.disconnect_calls == 1


def test_idle_command_worker_is_valid_for_store_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty SDK command worker is not a conflicting preflight activity."""

    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))
    store = adapter.BtApiStore(
        provider="btapi",
        api=api,
        config={"market_data_only": True, "execution_config": {"market_data_only": True}},
        autostart=False,
    )
    store.start()
    original_health = store.get_command_health

    def idle_worker_health() -> Mapping[str, Any]:
        health = dict(original_health())
        health["worker_alive"] = True
        return health

    monkeypatch.setattr(store, "get_command_health", idle_worker_health)
    try:
        assert adapter._require_injected_store_transfer(store, ownership="transfer") == 0
    finally:
        monkeypatch.setattr(store, "get_command_health", original_health)
        store.stop()


def test_store_write_guard_reports_rejected_market_data_only_delta() -> None:
    """A Store-local rejection is surfaced instead of being reported as zero."""

    class RejectedStore:
        def get_command_health(self) -> Mapping[str, Any]:
            return {
                "shutdown_state": "PASS",
                "accepting_openings": False,
                "rejected_market_data_only": 3,
            }

    guard = adapter._store_write_guard(RejectedStore(), baseline=1, ownership="INJECTED_STORE")

    assert guard["rejected_market_data_only"] == {"baseline": 1, "final": 3, "delta": 2}
    assert guard["forbidden_write_attempts"] == {"store_market_data_only_rejected": 2}


def test_engineering_observation_rejects_ambiguous_or_untransferred_store_before_connect() -> None:
    """A caller must choose exactly one input and explicitly hand over stop ownership."""

    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))
    store = adapter.BtApiStore(
        provider="btapi",
        api=api,
        config={"market_data_only": True},
        autostart=False,
    )
    provider = LiveEvidenceProvider(source, _live_mapping())

    with pytest.raises(adapter.EngineeringSmokeBlocked) as ambiguous:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            store=store,
            store_ownership="transfer",
            environment_profile="simnow_second_7x24",
            run_seconds=1.0,
            feed_clock=FixedLiveClock(),
            clock_mapping=_live_mapping(),
            closed_bar_evidence_provider=provider,
        )
    assert ambiguous.value.code == "ENGINEERING_STORE_INPUT"

    with pytest.raises(adapter.EngineeringSmokeBlocked) as untransferred:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=None,
            store=store,
            environment_profile="simnow_second_7x24",
            run_seconds=1.0,
            feed_clock=FixedLiveClock(),
            clock_mapping=_live_mapping(),
            closed_bar_evidence_provider=provider,
        )
    assert untransferred.value.code == "STORE_OWNERSHIP_TRANSFER_REQUIRED"
    assert api.connect_calls == 0
    assert api.disconnect_calls == 0
    assert api.connected is False


def test_engineering_smoke_does_not_claim_raw_external_provider_write_count() -> None:
    """Unstarted local construction has no raw-provider write attestation."""

    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))

    report = adapter.build_engineering_smoke(config=copy.deepcopy(CONFIG), api=api)

    assert report["external_trade_writes"] == "NOT_PROVEN"
    assert report["adapter_scoped_write_attempts"] == "NOT_OBSERVED"
    assert report["external_trade_writes_basis"] == (
        "NOT_PROVEN: an unstarted construction graph cannot attest raw external provider writes."
    )


def test_engineering_observation_accepts_a_public_second_set_profile_variant() -> None:
    source = _ticks()
    api = LiveFixtureApi(
        live_ticks=copy.deepcopy(source),
        session_state={"environment_profile": "set2_7x24_future_public_route"},
    )
    report, _, _ = _run_live_observation(api=api)

    assert report["session_binding"]["session_environment_profile"] == (
        "set2_7x24_future_public_route"
    )


def test_engineering_observation_rejects_replay_clock_before_api_start() -> None:
    source = _ticks()
    api = LiveFixtureApi(live_ticks=source)
    replay_mapping = _live_mapping(synthetic=True)
    provider = LiveEvidenceProvider(source, replay_mapping, mode="replay")

    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=1.0,
            feed_clock=FixedLiveClock(),
            clock_mapping=replay_mapping,
            closed_bar_evidence_provider=provider,
        )

    assert error.value.code == "LIVE_CLOCK_MAPPING_REQUIRED"
    assert api.connected is False


def test_engineering_observation_rejects_cross_domain_provider_evidence() -> None:
    foreign_mapping = _live_mapping("iter24-other-live-clock")
    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        _run_live_observation(evidence_mapping=foreign_mapping)

    assert error.value.code == "LIVE_EVIDENCE_MAPPING_REQUIRED"


def test_engineering_observation_guard_blocks_write_surface_without_delegating() -> None:
    api = LiveFixtureApi(live_ticks={})
    guard = adapter._ObservationReadOnlyApi(api)

    for method_name in (
        "submit_order",
        "cancel_order",
        "settlement_confirm",
        "configure_ctp_execution_authorization",
        "arm_execution_from_preflight",
        "arm_execution_from_approval",
        "confirm_ctp_settlement_from_approval",
        "custom_execution_route",
    ):
        with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
            getattr(guard, method_name)()
        assert error.value.code == "FORBIDDEN_WRITE_ATTEMPT"

    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert set(guard.audit()["forbidden_write_attempts"]) == {
        "submit_order",
        "cancel_order",
        "settlement_confirm",
        "configure_ctp_execution_authorization",
        "arm_execution_from_preflight",
        "arm_execution_from_approval",
        "confirm_ctp_settlement_from_approval",
        "custom_execution_route",
    }
    assert api.execution_route_calls == []

    assert guard.get_ctp_session_state() == api.get_ctp_session_state()
    guard.configure_execution({"market_data_only": True})
    assert api.execution_configuration_calls == [{"market_data_only": True}]
    for invalid_config in ({"market_data_only": False}, {"market_data_only": True, "extra": 1}):
        with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
            guard.configure_execution(invalid_config)
        assert error.value.code == "FORBIDDEN_WRITE_ATTEMPT"
    assert api.execution_configuration_calls == [{"market_data_only": True}]


def test_injected_store_guard_does_not_confuse_queue_availability_with_execution_permission() -> (
    None
):
    """Async Stores can queue rejected MDO commands while execution remains unarmed."""

    class AsyncMarketDataOnlyStore:
        def get_command_health(self) -> Mapping[str, Any]:
            return {
                # This is queue availability, not an order grant.  The
                # session-binding and Broker checks are exercised by the full
                # transferred-Store observation tests above.
                "accepting_openings": True,
                "rejected_market_data_only": 0,
                "shutdown_state": "PASS",
            }

    audit = adapter._store_write_guard(
        AsyncMarketDataOnlyStore(),
        baseline=0,
        ownership="INJECTED_STORE",
    )

    assert audit == {
        "source": "BtApiStore.get_command_health",
        "ownership": "INJECTED_STORE",
        "forbidden_write_attempts": {},
        "command_queue_accepting_openings": True,
        "market_data_only": "PROVEN_BY_SESSION_BINDING_AND_BROKER",
        "rejected_market_data_only": {"baseline": 0, "final": 0, "delta": 0},
    }


@pytest.mark.parametrize(
    ("session_state", "available", "code"),
    (
        ({"environment_profile": "set1_group2"}, True, "SECOND_SET_SESSION_PROFILE_REQUIRED"),
        ({"environment_profile": " set2_7x24_4000x "}, True, "SECOND_SET_SESSION_PROFILE_REQUIRED"),
        ({"account_fingerprint": ""}, True, "SESSION_ACCOUNT_FINGERPRINT_REQUIRED"),
        ({"read_only_ready": False}, True, "SESSION_READ_ONLY_NOT_READY"),
        ({"execution_gate_armed": True}, True, "SESSION_EXECUTION_GATE_NOT_UNARMED"),
        ({"execution_gate_armed": "False"}, True, "SESSION_EXECUTION_GATE_NOT_UNARMED"),
        ({"connection_generation": 7.0}, True, "SESSION_GENERATION_REQUIRED"),
        ({"connection_generation": "7"}, True, "SESSION_GENERATION_REQUIRED"),
        ({"connection_generation": 8}, True, "SESSION_GENERATION_MISMATCH"),
        ({}, False, "CTP_SESSION_STATE_UNAVAILABLE"),
    ),
)
def test_engineering_observation_fails_closed_on_unbound_second_set_session(
    session_state: Mapping[str, Any],
    available: bool,
    code: str,
) -> None:
    source = _ticks()
    api = LiveFixtureApi(
        live_ticks=copy.deepcopy(source),
        session_state=session_state,
        session_state_available=available,
    )

    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        _run_live_observation(api=api)

    assert error.value.code == code
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False
    assert api.connect_calls == 1
    assert api.disconnect_calls == 1


def test_engineering_observation_session_rejection_proves_broker_feed_store_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _ticks()
    api = LiveFixtureApi(
        live_ticks=copy.deepcopy(source),
        session_state={"read_only_ready": False},
    )
    shutdown_summaries: list[Any] = []
    stopped_datanames: list[str] = []
    original_broker_stop = BtApiBroker.stop
    original_feed_stop = BtApiFeed.stop

    def capture_broker_stop(self: BtApiBroker, *args: Any, **kwargs: Any) -> Any:
        summary = original_broker_stop(self, *args, **kwargs)
        shutdown_summaries.append(summary)
        return summary

    def capture_feed_stop(self: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        stopped_datanames.append(str(self._dataname))
        return original_feed_stop(self, *args, **kwargs)

    monkeypatch.setattr(BtApiBroker, "stop", capture_broker_stop)
    monkeypatch.setattr(BtApiFeed, "stop", capture_feed_stop)

    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        _run_live_observation(api=api)

    assert error.value.code == "SESSION_READ_ONLY_NOT_READY"
    assert shutdown_summaries
    shutdown = shutdown_summaries[-1]
    assert isinstance(shutdown, Mapping)
    assert shutdown["status"] == "OBSERVATION_ONLY"
    assert shutdown["market_data_only"] is True
    assert shutdown["cancel_requested"] == 0
    assert shutdown["close_requested"] == 0
    assert shutdown["store_shutdown_state"] == "PASS"
    assert sorted(stopped_datanames) == sorted(SYMBOLS)
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_reports_shutdown_incomplete_before_binding_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _ticks()
    api = LiveFixtureApi(
        live_ticks=copy.deepcopy(source),
        session_state={"read_only_ready": False},
    )
    stopped_datanames: list[str] = []
    original_feed_stop = BtApiFeed.stop

    def fail_broker_stop(self: BtApiBroker, *args: Any, **kwargs: Any) -> Any:
        del self, args, kwargs
        raise RuntimeError("fixture broker shutdown failure")

    def capture_feed_stop(self: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        stopped_datanames.append(str(self._dataname))
        return original_feed_stop(self, *args, **kwargs)

    monkeypatch.setattr(BtApiBroker, "stop", fail_broker_stop)
    monkeypatch.setattr(BtApiFeed, "stop", capture_feed_stop)

    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        _run_live_observation(api=api)

    assert error.value.code == "OBSERVATION_SHUTDOWN_INCOMPLETE"
    assert sorted(stopped_datanames) == sorted(SYMBOLS)
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False


def test_engineering_observation_unproven_normal_teardown_precedes_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid post-run summary cannot be hidden behind a raw run error."""

    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))
    original_shutdown_summary = BtApiBroker.get_shutdown_summary
    foreign_mapping = _live_mapping("iter24-other-live-clock")

    def invalidate_completed_summary(instance: BtApiBroker) -> Any:
        summary = original_shutdown_summary(instance)
        if isinstance(summary, Mapping) and summary.get("status") == "OBSERVATION_ONLY":
            return {**summary, "status": "INCOMPLETE"}
        return summary

    monkeypatch.setattr(BtApiBroker, "get_shutdown_summary", invalidate_completed_summary)

    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        _run_live_observation(api=api, evidence_mapping=foreign_mapping)

    assert error.value.code == "OBSERVATION_SHUTDOWN_INCOMPLETE"
    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_construction_failure_stops_partial_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))
    provider = LiveEvidenceProvider(source, _live_mapping())
    stopped_datanames: list[str] = []
    store_stop_calls: list[dict[str, Any]] = []
    original_getdata = adapter.BtApiStore.getdata
    original_feed_stop = BtApiFeed.stop
    original_store_stop = adapter.BtApiStore.stop
    getdata_calls = 0

    def fail_second_getdata(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal getdata_calls
        getdata_calls += 1
        if getdata_calls == 2:
            raise RuntimeError("fixture partial-feed construction failure")
        return original_getdata(self, *args, **kwargs)

    def capture_feed_stop(self: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        stopped_datanames.append(str(self._dataname))
        return original_feed_stop(self, *args, **kwargs)

    def capture_store_stop(self: Any, *args: Any, **kwargs: Any) -> Any:
        store_stop_calls.append(dict(kwargs))
        return original_store_stop(self, *args, **kwargs)

    monkeypatch.setattr(adapter.BtApiStore, "getdata", fail_second_getdata)
    monkeypatch.setattr(BtApiFeed, "stop", capture_feed_stop)
    monkeypatch.setattr(adapter.BtApiStore, "stop", capture_store_stop)

    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=1.0,
            feed_clock=FixedLiveClock(),
            clock_mapping=_live_mapping(),
            closed_bar_evidence_provider=provider,
        )

    assert error.value.code == "ENGINEERING_OBSERVATION_RUNTIME"
    assert stopped_datanames == [FUTURE]
    assert store_stop_calls == [{"timeout": 2.0}]
    assert api.connect_calls == 0
    assert api.connected is False
    assert api.submitted_orders == []
    assert api.cancelled_orders == []


def test_engineering_observation_construction_shutdown_failure_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))
    provider = LiveEvidenceProvider(source, _live_mapping())
    stopped_datanames: list[str] = []
    store_stop_calls: list[dict[str, Any]] = []
    original_getdata = adapter.BtApiStore.getdata
    original_feed_stop = BtApiFeed.stop
    original_store_stop = adapter.BtApiStore.stop
    getdata_calls = 0

    def fail_second_getdata(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal getdata_calls
        getdata_calls += 1
        if getdata_calls == 2:
            raise RuntimeError("fixture partial-feed construction failure")
        return original_getdata(self, *args, **kwargs)

    def fail_broker_stop(self: BtApiBroker, *args: Any, **kwargs: Any) -> Any:
        del self, args, kwargs
        raise RuntimeError("fixture broker construction shutdown failure")

    def capture_feed_stop(self: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        stopped_datanames.append(str(self._dataname))
        return original_feed_stop(self, *args, **kwargs)

    def capture_store_stop(self: Any, *args: Any, **kwargs: Any) -> Any:
        store_stop_calls.append(dict(kwargs))
        return original_store_stop(self, *args, **kwargs)

    monkeypatch.setattr(adapter.BtApiStore, "getdata", fail_second_getdata)
    monkeypatch.setattr(BtApiBroker, "stop", fail_broker_stop)
    monkeypatch.setattr(BtApiFeed, "stop", capture_feed_stop)
    monkeypatch.setattr(adapter.BtApiStore, "stop", capture_store_stop)

    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=1.0,
            feed_clock=FixedLiveClock(),
            clock_mapping=_live_mapping(),
            closed_bar_evidence_provider=provider,
        )

    assert error.value.code == "OBSERVATION_SHUTDOWN_INCOMPLETE"
    assert stopped_datanames == [FUTURE]
    assert store_stop_calls == [{"timeout": 2.0}]
    assert api.connect_calls == 0
    assert api.connected is False
    assert api.submitted_orders == []
    assert api.cancelled_orders == []


def test_engineering_observation_global_deadline_starts_before_slow_feed_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow second Feed consumes the timer started before graph construction."""

    # Keep this construction-boundary test deterministic under xdist load.
    # Only the adapter's lifecycle clock/timer are virtualized: Store, Feed,
    # Cerebro and graph teardown continue to use their production references.
    now = 0.0
    timers: list[Any] = []

    class ControlledTimer:
        def __init__(self, interval: float, function: Any) -> None:
            self.interval = interval
            self.function = function
            self.deadline: float | None = None
            self.fired = False
            self.cancelled = False
            timers.append(self)

        def start(self) -> None:
            self.deadline = now + self.interval

        def cancel(self) -> None:
            self.cancelled = True

        def join(self, timeout: float | None = None) -> None:
            assert self.cancelled or self.fired

        def is_alive(self) -> bool:
            return self.deadline is not None and not self.fired and not self.cancelled

    def advance(seconds: float) -> None:
        nonlocal now
        now += seconds
        for timer in tuple(timers):
            if timer.is_alive() and now >= timer.deadline:
                timer.fired = True
                timer.function()

    monkeypatch.setattr(adapter, "ENGINEERING_OBSERVATION_MAX_SECONDS", 0.05)
    monkeypatch.setattr(adapter, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(
        adapter,
        "threading",
        SimpleNamespace(Timer=ControlledTimer, Event=threading.Event, Lock=threading.Lock),
    )
    source = _ticks()
    api = LiveFixtureApi(live_ticks=copy.deepcopy(source))
    provider = LiveEvidenceProvider(source, _live_mapping())
    stopped_datanames: list[str] = []
    store_stop_calls: list[dict[str, Any]] = []
    broker_stop_calls = 0
    original_getdata = adapter.BtApiStore.getdata
    original_broker_stop = BtApiBroker.stop
    original_feed_stop = BtApiFeed.stop
    original_store_stop = adapter.BtApiStore.stop
    getdata_calls = 0

    def slow_second_getdata(instance: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal getdata_calls
        getdata_calls += 1
        if getdata_calls == 2:
            # The lifecycle timer has already started before this slow Feed is
            # constructed.  Advance past its budget while construction blocks.
            assert len(timers) == 1
            assert timers[0].is_alive()
            advance(0.06)
        return original_getdata(instance, *args, **kwargs)

    def capture_broker_stop(instance: BtApiBroker, *args: Any, **kwargs: Any) -> Any:
        nonlocal broker_stop_calls
        broker_stop_calls += 1
        return original_broker_stop(instance, *args, **kwargs)

    def capture_feed_stop(instance: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        stopped_datanames.append(str(instance._dataname))
        return original_feed_stop(instance, *args, **kwargs)

    def capture_store_stop(instance: Any, *args: Any, **kwargs: Any) -> Any:
        store_stop_calls.append(dict(kwargs))
        return original_store_stop(instance, *args, **kwargs)

    monkeypatch.setattr(adapter.BtApiStore, "getdata", slow_second_getdata)
    monkeypatch.setattr(BtApiBroker, "stop", capture_broker_stop)
    monkeypatch.setattr(BtApiFeed, "stop", capture_feed_stop)
    monkeypatch.setattr(adapter.BtApiStore, "stop", capture_store_stop)

    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.02,
            feed_clock=FixedLiveClock(),
            clock_mapping=_live_mapping(),
            closed_bar_evidence_provider=provider,
        )

    assert error.value.code == "OBSERVATION_LIFECYCLE_DURATION_EXCEEDED"
    assert len(timers) == 1
    assert timers[0].name == "iter24-engineering-observation-lifecycle-deadline"
    assert timers[0].interval == pytest.approx(0.05)
    assert timers[0].fired and timers[0].cancelled
    assert not timers[0].is_alive()
    assert broker_stop_calls == 1
    assert stopped_datanames == [FUTURE, CALL]
    assert store_stop_calls == [{"timeout": 2.0}]
    assert api.connect_calls == 0
    assert api.connected is False
    assert api.submitted_orders == []
    assert api.cancelled_orders == []


def test_engineering_observation_reports_lifecycle_deadline_exhausted_before_full_watchdog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Freeze setup time and deliver the real lifecycle callback only when the
    # injected connection consumes its budget. Real scheduler delays must not
    # turn this runtime/report case into the separate construction-failure case.
    now = 0.0
    timers: list[Any] = []

    class ControlledTimer:
        def __init__(self, interval: float, function: Any) -> None:
            self.interval = interval
            self.function = function
            self.deadline: float | None = None
            self.fired = False
            self.cancelled = False
            timers.append(self)

        def start(self) -> None:
            self.deadline = now + self.interval

        def cancel(self) -> None:
            self.cancelled = True

        def join(self, timeout: float | None = None) -> None:
            assert self.cancelled or self.fired

        def is_alive(self) -> bool:
            return self.deadline is not None and not self.fired and not self.cancelled

    def advance(seconds: float) -> None:
        nonlocal now
        now += seconds
        for timer in tuple(timers):
            if timer.is_alive() and now >= timer.deadline:
                timer.fired = True
                timer.function()

    class SlowConnectApi(LiveFixtureApi):
        def connect(self) -> None:
            assert now == 0.0
            super().connect()
            advance(0.06)

    monkeypatch.setattr(adapter, "ENGINEERING_OBSERVATION_MAX_SECONDS", 0.05)
    # Replace only the adapter's references, not the process-wide time/threading
    # modules used by the real Store/Feed/Cerebro and their shutdown paths.
    monkeypatch.setattr(adapter, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(
        adapter,
        "threading",
        SimpleNamespace(Timer=ControlledTimer, Event=threading.Event, Lock=threading.Lock),
    )
    source = _ticks()
    api = SlowConnectApi(live_ticks=copy.deepcopy(source))
    provider = LiveEvidenceProvider(source, _live_mapping())

    report = runner.run_engineering_observation(
        copy.deepcopy(CONFIG),
        api=api,
        environment_profile="simnow_second_7x24",
        run_seconds=0.02,
        feed_clock=FixedLiveClock(),
        clock_mapping=_live_mapping(),
        closed_bar_evidence_provider=provider,
    )

    assert report["status"] == "INCOMPLETE_ENGINEERING_STRATEGY_OBSERVATION"
    assert report["duration"]["elapsed_seconds"] > report["duration"]["maximum_seconds"]
    assert report["duration"]["elapsed_within_maximum"] is False
    assert report["duration"]["lifecycle_deadline_stop_requested"] is True
    assert "OBSERVATION_LIFECYCLE_DURATION_EXCEEDED" in report["failure_codes"]
    assert report["duration"]["elapsed_seconds"] == pytest.approx(0.06)
    assert api.connect_calls == 1
    assert len(timers) == 1  # No fresh post-connect runtime watchdog was granted.
    assert timers[0].name == "iter24-engineering-observation-lifecycle-deadline"
    assert timers[0].interval == pytest.approx(0.05)
    assert timers[0].fired and timers[0].cancelled
    assert not timers[0].is_alive()
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False


@pytest.mark.parametrize("seconds", (0, -1, 3600.1))
def test_engineering_observation_rejects_unbounded_duration_without_api_start(
    seconds: float,
) -> None:
    api = LiveFixtureApi(live_ticks={})
    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=seconds,
            feed_clock=FixedLiveClock(),
            clock_mapping=_live_mapping(),
            closed_bar_evidence_provider=lambda _bar: None,
        )
    assert error.value.code == "ENGINEERING_DURATION"
    assert api.connected is False
