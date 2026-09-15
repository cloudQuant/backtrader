"""Zero-write Set-2 engineering observation coverage for Iteration 25.

The fixtures exercise the native Store/Feed/Broker/Cerebro chain without a
socket, credentials, or an order-capable transport.  They are engineering
evidence only and never establish HFT admission or a SimNow G3/G4 result.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import hashlib
import importlib
import threading
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

import pytest

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds import ClockMapping, CtpCohortNow
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore
from tests.fixtures.fake_btapi import FakeBtApiClient

runner = importlib.import_module("examples.015_ctp_options_highfreq.run")
adapter = importlib.import_module("examples.015_ctp_options_highfreq.engineering_smoke")

RAW_CONFIG, _ = runner.load_config()
CONFIG = runner.effective_config(RAW_CONFIG, mode="shadow", purpose="observation")
LIVE_DOMAIN = "iter25-engineering-live-clock"


class LiveClock:
    """Use the injected source delivery clock; never fall back to process time."""

    def __init__(self) -> None:
        self._now_ns: int | None = None

    def advance(self, tick: Any) -> None:
        self._now_ns = int(tick.recv_monotonic_ns)

    def monotonic_ns(self) -> int:
        if self._now_ns is None:
            raise AssertionError("feed read the clock before a live tick delivery")
        return self._now_ns


class LiveNowProvider:
    """Caller-owned live CtpCohortNow evidence for each feed dispatch."""

    def __init__(self, mapping: ClockMapping, *, wrong_domain: bool = False) -> None:
        self.mapping = mapping
        self.wrong_domain = wrong_domain
        self.calls: list[tuple[str, int]] = []

    def __call__(self, tick: Any) -> CtpCohortNow:
        self.calls.append((str(tick.symbol), int(tick.ingest_seq)))
        return CtpCohortNow(
            now_monotonic_ns=int(tick.recv_monotonic_ns),
            now_epoch=tick.recv_time_utc,
            clock_domain_id=(
                "foreign-clock-domain" if self.wrong_domain else self.mapping.clock_domain_id
            ),
            receive_clock_error_ms=0.0,
            receive_clock_quality="verified",
            freshness_verified=True,
        )


class ObservationApi(FakeBtApiClient):
    """A non-EOF local transport that ends only through Cerebro.runstop()."""

    def __init__(
        self,
        ticks: Mapping[str, Iterable[Any]],
        *,
        clock: LiveClock,
        session_state: Any = None,
    ) -> None:
        super().__init__(live_ticks=ticks)
        self._symbols = tuple(ticks)
        self._next_symbol = 0
        self._clock = clock
        self.exchange_kwargs = {"CTP___FUTURE": {}}
        self._session_state = (
            {
                "environment_profile": "set2_7x24_shadow",
                "read_only_ready": True,
                "execution_gate_armed": False,
                "account_fingerprint": "iter25-observation-account",
                "connection_generation": 1,
                "trading_day": "20260910",
            }
            if session_state is None
            else session_state
        )
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.session_state_calls: list[str] = []
        self.session_state_connected_at_call: list[bool] = []

    def connect(self) -> None:
        self.connect_calls += 1
        super().connect()

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        super().disconnect()

    def get_ctp_session_state(self, *, exchange_name: str) -> Any:
        self.session_state_calls.append(exchange_name)
        self.session_state_connected_at_call.append(bool(self.connected))
        if isinstance(self._session_state, Mapping):
            return {"connected": self.connected, **copy.deepcopy(dict(self._session_state))}
        return self._session_state

    def poll_tick(self, dataname: str) -> Any:
        if dataname != self._symbols[self._next_symbol]:
            return None
        tick = super().poll_tick(dataname)
        if tick is not None:
            self._clock.advance(tick)
            self._next_symbol = (self._next_symbol + 1) % len(self._symbols)
        return tick


def _live_ticks() -> tuple[dict[str, list[Any]], Mapping[str, Any]]:
    fixture, _, _ = runner.load_fixture(CONFIG)
    bundle = runner.validate_bundle(fixture, CONFIG)
    ticks: dict[str, list[Any]] = {
        str(bundle[role]["symbol"]): [] for role in ("future", "call", "put")
    }
    for event in runner._cohort_events(fixture, bundle, "valid_cohort"):
        tick = copy.deepcopy(event.data)
        tick.clock_domain_id = LIVE_DOMAIN
        tick.source = "tests.iter25.engineering.live-ctp-source"
        tick.event_time_source = "ctp_gateway_exchange_timestamp"
        ticks[str(tick.symbol)].append(tick)
    return ticks, bundle


def _mapping(
    ticks: Mapping[str, Iterable[Any]], bundle: Mapping[str, Any], *, synthetic: bool = False
) -> ClockMapping:
    first = next(iter(next(iter(ticks.values()))))
    received_at = dt.datetime.fromisoformat(str(first.recv_time_utc).replace("Z", "+00:00"))
    return ClockMapping(
        mapping_id="iter25-engineering-live-mapping",
        wall_utc_at_anchor=received_at,
        mono_ns_at_anchor=int(first.recv_monotonic_ns),
        clock_domain_id=LIVE_DOMAIN,
        connection_generation=1,
        source="tests.iter25.engineering.live-clock",
        # Fixture timestamp formatting is microsecond-resolution while the
        # captured monotonic readings retain nanoseconds.  This is a bounded
        # live-clock calibration tolerance, not synthetic time.
        error_bound_ns=1_000,
        valid_until_mono_ns=int(first.recv_monotonic_ns) + 10**15,
        rules_hash=runner.canonical_sha256(bundle),
        synthetic=synthetic,
    )


def _install_controlled_runner_clock(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Make one observation's runner-owned watchdogs deterministic."""

    state = SimpleNamespace(now=0.0, timers=[])

    class ControlledTimer:
        def __init__(self, interval: float, function: Any) -> None:
            self.interval = interval
            self.function = function
            self.deadline: float | None = None
            self.fired = False
            self.cancelled = False
            self.started = False
            self.joined = False
            state.timers.append(self)

        def start(self) -> None:
            if self.started:
                raise AssertionError("controlled timer started more than once")
            self.started = True
            self.deadline = state.now + self.interval

        def cancel(self) -> None:
            self.cancelled = True

        def join(self, timeout: float | None = None) -> None:
            assert self.started
            assert self.cancelled or self.fired
            self.joined = True

        def is_alive(self) -> bool:
            return (
                self.started and self.deadline is not None and not self.fired and not self.cancelled
            )

    def advance(seconds: float) -> None:
        state.now += seconds
        for timer in tuple(state.timers):
            if timer.is_alive() and state.now >= timer.deadline:
                timer.fired = True
                timer.function()

    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr(
        runner,
        "threading",
        SimpleNamespace(Timer=ControlledTimer, Event=threading.Event, Lock=threading.Lock),
    )
    return state, advance


def _assert_controlled_watchdogs_closed(state: Any, *, active_interval: float) -> None:
    assert [timer.name for timer in state.timers] == [
        "iter25-engineering-observation-lifecycle-deadline",
        "iter25-engineering-observation-watchdog",
    ]
    assert state.timers[0].interval == pytest.approx(3600.0)
    assert state.timers[1].interval == pytest.approx(active_interval)
    assert all(timer.started and timer.joined for timer in state.timers)
    assert (
        state.timers[0].cancelled and not state.timers[0].fired and not state.timers[0].is_alive()
    )
    assert state.timers[1].cancelled and state.timers[1].fired and not state.timers[1].is_alive()


def _assert_lifecycle_deadline_closed(state: Any, *, interval: float) -> None:
    assert [timer.name for timer in state.timers] == [
        "iter25-engineering-observation-lifecycle-deadline"
    ]
    assert state.timers[0].interval == pytest.approx(interval)
    assert state.timers[0].started and state.timers[0].joined
    assert state.timers[0].fired and state.timers[0].cancelled and not state.timers[0].is_alive()


def _provider_then_trigger_deadline(
    provider: LiveNowProvider,
    state: Any,
    advance: Any,
    *,
    after_calls: int,
    duration: float,
) -> Any:
    """Stop only after a Feed has invoked the provider enough times."""

    def bounded_provider(tick: Any) -> CtpCohortNow:
        value = provider(tick)
        if len(provider.calls) == after_calls:
            assert len(state.timers) == 2
            advance(duration)
        return value

    return bounded_provider


def _run_observation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    wrong_domain: bool = False,
    session_state: Any = None,
) -> tuple[dict[str, Any], ObservationApi, LiveNowProvider, Any]:
    state, advance = _install_controlled_runner_clock(monkeypatch)
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(ticks, clock=clock, session_state=session_state)
    provider = LiveNowProvider(mapping, wrong_domain=wrong_domain)
    report = runner.run_engineering_observation(
        copy.deepcopy(CONFIG),
        api=api,
        environment_profile="simnow_second_7x24",
        run_seconds=0.05,
        feed_clock=clock,
        clock_mapping=mapping,
        live_now_provider=_provider_then_trigger_deadline(
            provider,
            state,
            advance,
            after_calls=6,
            duration=0.05,
        ),
    )
    return report, api, provider, state


def test_engineering_observation_runs_actual_highfreq_strategy_on_real_native_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report, api, provider, state = _run_observation(monkeypatch)

    assert report["status"] == "PASS_ENGINEERING_STRATEGY_OBSERVATION"
    assert report["mode"] == "shadow"
    assert report["purpose"] == "observation"
    assert report["requested_environment_profile"] == "simnow_second_7x24"
    assert report["store_ownership"] == "ADAPTER_OWNED_STORE_FROM_API"
    assert report["session_binding"] == {
        "source": "BtApiStore.get_ctp_session_state",
        "exchange_name": "CTP___FUTURE",
        "actual_environment_profile": "set2_7x24_shadow",
        "profile_family_prefix": "set2_7x24",
        "account_fingerprint_sha256": hashlib.sha256(b"iter25-observation-account").hexdigest(),
        "read_only_ready": True,
        "execution_gate_armed": False,
        "connection_generation": 1,
        "clock_mapping_id": "iter25-engineering-live-mapping",
        "clock_mapping_generation": 1,
        "trading_day": "20260910",
    }
    assert "account_fingerprint" not in report["session_binding"]
    assert "iter25-observation-account" not in repr(report)
    assert report["chain"] == {
        "store": "BtApiStore",
        "feeds": ["BtApiFeed", "BtApiFeed", "BtApiFeed"],
        "broker": "BtApiBroker",
        "cerebro": "Cerebro",
        "strategy": "CtpOptionsHighfreqStrategy",
    }
    assert report["duration"]["requested_seconds"] == 0.05
    assert report["duration"]["strategy_started"] is True
    assert report["duration"]["active_window_elapsed_seconds"] == pytest.approx(0.05)
    assert report["duration"]["deadline_stop_requested"] is True
    assert report["duration"]["lifecycle_deadline_stop_requested"] is False
    assert report["duration"]["elapsed_within_maximum"] is True
    assert report["duration"]["maximum_seconds"] == 3600.0
    assert report["feed_evidence"]["clock_domain"] == LIVE_DOMAIN
    assert report["feed_evidence"]["accepted_symbols"] == ["FG701", "FG701C970", "FG701P970"]
    assert report["feed_evidence"]["trusted_cohort_now_calls"] >= 6
    assert len(provider.calls) >= 6
    assert report["strategy"]["callback_counts"]["tick"] >= 6
    assert report["strategy"]["hft_status"] == "NOT_ADMITTED"
    assert report["write_guard"]["forbidden_write_attempts"] == {}
    assert report["adapter_scoped_write_attempts"] == 0
    assert report["external_trade_writes"] == "NOT_PROVEN"
    assert report["external_trade_writes_basis"] == (
        "NOT_PROVEN: the adapter membrane and market_data_only Broker only observe "
        "adapter-routed attempts; they cannot attest raw external provider writes."
    )
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False
    assert api.connect_calls == 1
    assert api.disconnect_calls == 1
    assert len(api.session_state_calls) >= 2
    assert set(api.session_state_calls) == {"CTP___FUTURE"}
    assert api.session_state_connected_at_call
    assert all(api.session_state_connected_at_call)
    assert state.now == pytest.approx(0.05)
    _assert_controlled_watchdogs_closed(state, active_interval=0.05)
    assert report["shutdown"] == {
        "status": "OBSERVATION_ONLY",
        "market_data_only": True,
        "cancel_requested": 0,
        "close_requested": 0,
        "store_shutdown_state": "PASS",
    }
    assert report["gates"] == {
        "G3_first_set_read_only": "NOT_RUN_ENGINEERING_STRATEGY_OBSERVATION",
        "G3_evaluation": "NOT_APPLICABLE_ENGINEERING_ONLY",
        "G4_simnow_mechanical": "NOT_RUN",
        "HFT_admission": "NOT_ADMITTED",
    }


def test_engineering_observation_reuses_one_explicitly_transferred_store_without_sdk_unwrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A preflight-owned Store must be the graph's only lifecycle root."""

    state, advance = _install_controlled_runner_clock(monkeypatch)
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    api = ObservationApi(ticks, clock=clock)
    store = BtApiStore(
        provider="btapi",
        api=api,
        config={"execution_config": {"market_data_only": True}},
        autostart=False,
    )
    # This stands in for the operator's bounded, read-only preflight.  The
    # mapping is deliberately acquired after this Store has joined its final
    # connection generation, before lifecycle ownership is handed off.
    store.start()
    mapping = _mapping(ticks, bundle)
    provider = LiveNowProvider(mapping)

    def unexpected_second_store(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise AssertionError("transferred Store path constructed a second Store")

    def forbidden_sdk_api(self: BtApiStore) -> Any:
        del self
        raise AssertionError("transferred Store path accessed store.sdk_api")

    monkeypatch.setattr(runner.bt.stores, "BtApiStore", unexpected_second_store)
    monkeypatch.setattr(BtApiStore, "sdk_api", property(forbidden_sdk_api))

    report = runner.run_engineering_observation(
        copy.deepcopy(CONFIG),
        store=store,
        store_ownership="transfer",
        environment_profile="simnow_second_7x24",
        run_seconds=0.05,
        feed_clock=clock,
        clock_mapping=mapping,
        live_now_provider=_provider_then_trigger_deadline(
            provider,
            state,
            advance,
            after_calls=6,
            duration=0.05,
        ),
    )

    assert report["status"] == "PASS_ENGINEERING_STRATEGY_OBSERVATION"
    assert report["store_ownership"] == "INJECTED_STORE_LIFECYCLE_TRANSFERRED"
    assert report["write_guard"]["store_market_data_only"] == {
        "source": "BtApiStore.get_command_health",
        "ownership": "INJECTED_STORE",
        "forbidden_write_attempts": {},
        "market_data_only": "PROVEN_BY_SESSION_BINDING_AND_BROKER",
        "rejected_market_data_only": {"baseline": 0, "final": 0, "delta": 0},
    }
    assert report["write_guard"]["forbidden_write_attempts"] == {}
    assert report["write_guard"]["broker_market_data_only"]["total_rejected"] == 0
    assert report["external_trade_writes_basis"] == (
        "NOT_PROVEN: public BtApiStore lifecycle and market-data-only state do not attest "
        "raw external provider writes."
    )
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connect_calls == 1
    assert api.disconnect_calls == 1
    assert api.connected is False
    assert state.now == pytest.approx(0.05)
    _assert_controlled_watchdogs_closed(state, active_interval=0.05)


def test_store_transfer_rejects_an_overridden_write_audit_recorder() -> None:
    """A no-op aggregate recorder must not make an HFT observation look clean."""

    class NoOpRecorderStore(BtApiStore):
        def record_market_data_only_broker_rejection(self, _operation: str) -> None:
            return None

    ticks, _ = _live_ticks()
    clock = LiveClock()
    api = ObservationApi(ticks, clock=clock)
    store = NoOpRecorderStore(
        provider="btapi",
        api=api,
        config={"execution_config": {"market_data_only": True}},
        autostart=False,
    )
    store.start()
    try:
        with pytest.raises(adapter.EngineeringObservationBlocked) as error:
            runner._require_injected_store_transfer(
                store,
                ownership="transfer",
                observation_blocked=adapter.EngineeringObservationBlocked,
            )

        assert error.value.code == "INJECTED_STORE_AUDIT_CONTRACT_REQUIRED"
        assert store.is_connected is True
        assert api.connect_calls == 1
        assert api.disconnect_calls == 0
    finally:
        store.stop()

    assert api.disconnect_calls == 1


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
    """An active read-only probe cannot be handed off to an HFT graph."""

    ticks, bundle = _live_ticks()
    clock = LiveClock()
    api = ObservationApi(ticks, clock=clock)
    store = BtApiStore(
        provider="btapi",
        api=api,
        config={"execution_config": {"market_data_only": True}},
        autostart=False,
    )
    store.start()
    original_health = store.get_command_health

    def busy_health() -> Mapping[str, Any]:
        health = dict(original_health())
        health[health_key] = busy_value
        return health

    monkeypatch.setattr(store, "get_command_health", busy_health)
    mapping = _mapping(ticks, bundle)
    try:
        with pytest.raises(adapter.EngineeringObservationBlocked) as error:
            runner.run_engineering_observation(
                copy.deepcopy(CONFIG),
                store=store,
                store_ownership="transfer",
                environment_profile="simnow_second_7x24",
                run_seconds=0.05,
                feed_clock=clock,
                clock_mapping=mapping,
                live_now_provider=LiveNowProvider(mapping),
            )

        assert error.value.code == "INJECTED_STORE_BUSY"
        assert store.is_connected is True
        assert api.connect_calls == 1
        assert api.disconnect_calls == 0
    finally:
        monkeypatch.setattr(store, "get_command_health", original_health)
        store.stop(timeout=2.0)

    assert api.disconnect_calls == 1


def test_idle_command_worker_is_valid_for_store_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Store's own empty SDK worker does not invalidate a clean hand-off."""

    ticks, _bundle = _live_ticks()
    clock = LiveClock()
    api = ObservationApi(ticks, clock=clock)
    store = BtApiStore(
        provider="btapi",
        api=api,
        config={"execution_config": {"market_data_only": True}},
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
        assert (
            runner._require_injected_store_transfer(
                store,
                ownership="transfer",
                observation_blocked=adapter.EngineeringObservationBlocked,
            )
            == 0
        )
    finally:
        monkeypatch.setattr(store, "get_command_health", original_health)
        store.stop(timeout=2.0)


def test_store_write_guard_reports_rejected_market_data_only_delta() -> None:
    """A rejected Store command is not erased by the terminal health report."""

    class RejectedStore:
        def get_command_health(self) -> Mapping[str, Any]:
            return {
                "shutdown_state": "PASS",
                "accepting_openings": False,
                "rejected_market_data_only": 4,
            }

    guard = runner._injected_store_write_guard(
        RejectedStore(),
        baseline=1,
        ownership="INJECTED_STORE",
        observation_blocked=adapter.EngineeringObservationBlocked,
    )

    assert guard["rejected_market_data_only"] == {"baseline": 1, "final": 4, "delta": 3}
    assert guard["forbidden_write_attempts"] == {"store_market_data_only_rejected": 3}


def test_engineering_observation_requires_explicit_store_ownership_before_taking_it_down() -> None:
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    api = ObservationApi(ticks, clock=clock)
    store = BtApiStore(
        provider="btapi",
        api=api,
        config={"execution_config": {"market_data_only": True}},
        autostart=False,
    )
    store.start()
    mapping = _mapping(ticks, bundle)

    try:
        with pytest.raises(adapter.EngineeringObservationBlocked) as error:
            runner.run_engineering_observation(
                copy.deepcopy(CONFIG),
                store=store,
                environment_profile="simnow_second_7x24",
                run_seconds=0.05,
                feed_clock=clock,
                clock_mapping=mapping,
                live_now_provider=LiveNowProvider(mapping),
            )

        assert error.value.code == "STORE_OWNERSHIP_TRANSFER_REQUIRED"
        assert store.is_connected is True
        assert api.connect_calls == 1
        assert api.disconnect_calls == 0
    finally:
        store.stop(timeout=2.0)

    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_rejects_mixed_api_and_store_before_store_transfer() -> None:
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    api = ObservationApi(ticks, clock=clock)
    store = BtApiStore(
        provider="btapi",
        api=api,
        config={"execution_config": {"market_data_only": True}},
        autostart=False,
    )
    store.start()
    mapping = _mapping(ticks, bundle)

    try:
        with pytest.raises(adapter.EngineeringObservationBlocked) as error:
            runner.run_engineering_observation(
                copy.deepcopy(CONFIG),
                api=api,
                store=store,
                store_ownership="transfer",
                environment_profile="simnow_second_7x24",
                run_seconds=0.05,
                feed_clock=clock,
                clock_mapping=mapping,
                live_now_provider=LiveNowProvider(mapping),
            )

        assert error.value.code == "ENGINEERING_STORE_INPUT"
        assert store.is_connected is True
        assert api.connect_calls == 1
        assert api.disconnect_calls == 0
    finally:
        store.stop(timeout=2.0)

    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_rejects_synthetic_mapping_before_api_start() -> None:
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle, synthetic=True)
    api = ObservationApi(ticks, clock=clock)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.05,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == "LIVE_CLOCK_MAPPING_REQUIRED"
    assert api.connected is False
    assert api.connect_calls == 0


def test_engineering_observation_rejects_wrong_domain_provider_and_still_shuts_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The provider enters before this test advances the active watchdog.
    # Freeze only the runner's lifecycle references so
    # Store/Feed/Cerebro still exercise their normal local teardown paths.
    state, advance = _install_controlled_runner_clock(monkeypatch)
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(ticks, clock=clock)
    provider = LiveNowProvider(mapping, wrong_domain=True)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.05,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=_provider_then_trigger_deadline(
                provider,
                state,
                advance,
                after_calls=1,
                duration=0.05,
            ),
        )

    assert error.value.code == "TRUSTED_COHORT_NOW_DOMAIN"
    assert provider.calls
    assert state.now == pytest.approx(0.05)
    _assert_controlled_watchdogs_closed(state, active_interval=0.05)
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_rejects_mapping_that_cannot_cover_full_observation_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The provider enters before this test advances the active watchdog.
    state, advance = _install_controlled_runner_clock(monkeypatch)
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    last_tick_ns = max(int(tick.recv_monotonic_ns) for stream in ticks.values() for tick in stream)
    mapping = dataclasses.replace(
        _mapping(ticks, bundle),
        # All fixture ticks remain individually valid, but the mapping has
        # less than the requested window left after the initial coherent time.
        valid_until_mono_ns=last_tick_ns + 1_000_000,
    )
    api = ObservationApi(ticks, clock=clock)
    provider = LiveNowProvider(mapping)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.1,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=_provider_then_trigger_deadline(
                provider,
                state,
                advance,
                after_calls=1,
                duration=0.1,
            ),
        )

    assert error.value.code == "LIVE_CLOCK_MAPPING_DURATION_REQUIRED"
    assert provider.calls
    assert state.now == pytest.approx(0.1)
    _assert_controlled_watchdogs_closed(state, active_interval=0.1)
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False
    assert api.disconnect_calls == 1


@pytest.mark.parametrize(
    ("session_patch", "expected_code"),
    (
        ({"environment_profile": "set1_7x24_shadow"}, "CTP_SESSION_PROFILE_REQUIRED"),
        ({"connection_generation": 2}, "CTP_SESSION_GENERATION_REQUIRED"),
        ({"execution_gate_armed": 0}, "CTP_SESSION_EXECUTION_GATE_REQUIRED"),
        ({"account_fingerprint": ""}, "CTP_SESSION_FINGERPRINT_REQUIRED"),
        ({"read_only_ready": False}, "CTP_SESSION_READ_ONLY_REQUIRED"),
    ),
)
def test_engineering_observation_rejects_mismatched_connected_session_identity(
    session_patch: Mapping[str, Any], expected_code: str
) -> None:
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    session_state = {
        "environment_profile": "set2_7x24_shadow",
        "connected": True,
        "read_only_ready": True,
        "execution_gate_armed": False,
        "account_fingerprint": "iter25-observation-account",
        "connection_generation": 1,
    }
    session_state.update(session_patch)
    api = ObservationApi(ticks, clock=clock, session_state=session_state)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.05,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == expected_code
    assert len(api.session_state_calls) >= 2
    assert set(api.session_state_calls) == {"CTP___FUTURE"}
    assert api.session_state_connected_at_call
    assert all(api.session_state_connected_at_call)
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_rejecting_session_runs_broker_and_data_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(
        ticks,
        clock=clock,
        session_state={
            "environment_profile": "set2_7x24_shadow",
            "read_only_ready": False,
            "execution_gate_armed": False,
            "account_fingerprint": "iter25-observation-account",
            "connection_generation": 1,
        },
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

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.05,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == "CTP_SESSION_READ_ONLY_REQUIRED"
    assert shutdown_summaries
    shutdown = shutdown_summaries[-1]
    assert isinstance(shutdown, Mapping)
    assert shutdown["status"] == "OBSERVATION_ONLY"
    assert shutdown["market_data_only"] is True
    assert shutdown["cancel_requested"] == 0
    assert shutdown["close_requested"] == 0
    assert shutdown["store_shutdown_state"] == "PASS"
    assert sorted(stopped_datanames) == sorted(ticks)
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False


def test_engineering_observation_rejects_lifecycle_overrun_during_session_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, advance = _install_controlled_runner_clock(monkeypatch)
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(ticks, clock=clock)
    original_binding = runner._require_ctp_session_binding

    def slow_binding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        advance(0.06)
        return original_binding(*args, **kwargs)

    monkeypatch.setattr(adapter, "ENGINEERING_OBSERVATION_MAX_SECONDS", 0.05)
    monkeypatch.setattr(runner, "_require_ctp_session_binding", slow_binding)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.02,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == "OBSERVATION_LIFECYCLE_DURATION_EXCEEDED"
    assert state.now == pytest.approx(0.06)
    _assert_lifecycle_deadline_closed(state, interval=0.05)
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_lifecycle_budget_covers_partial_feed_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, advance = _install_controlled_runner_clock(monkeypatch)
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(ticks, clock=clock)
    original_getdata = BtApiStore.getdata
    original_broker_stop = BtApiBroker.stop
    original_feed_stop = BtApiFeed.stop
    original_store_stop = BtApiStore.stop
    broker_stops: list[Any] = []
    stopped_datanames: list[str] = []
    store_stops: list[Any] = []

    def slow_first_feed(self: Any, *args: Any, **kwargs: Any) -> Any:
        feed = original_getdata(self, *args, **kwargs)
        advance(0.06)
        return feed

    def capture_broker_stop(self: BtApiBroker, *args: Any, **kwargs: Any) -> Any:
        result = original_broker_stop(self, *args, **kwargs)
        broker_stops.append(result)
        return result

    def capture_feed_stop(self: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        stopped_datanames.append(str(self._dataname))
        return original_feed_stop(self, *args, **kwargs)

    def capture_store_stop(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_store_stop(self, *args, **kwargs)
        store_stops.append(result)
        return result

    monkeypatch.setattr(adapter, "ENGINEERING_OBSERVATION_MAX_SECONDS", 0.05)
    monkeypatch.setattr(BtApiStore, "getdata", slow_first_feed)
    monkeypatch.setattr(BtApiBroker, "stop", capture_broker_stop)
    monkeypatch.setattr(BtApiFeed, "stop", capture_feed_stop)
    monkeypatch.setattr(BtApiStore, "stop", capture_store_stop)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.02,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == "OBSERVATION_LIFECYCLE_DURATION_EXCEEDED"
    assert state.now == pytest.approx(0.06)
    _assert_lifecycle_deadline_closed(state, interval=0.05)
    assert broker_stops == [{"status": "NOT_STARTED"}]
    assert stopped_datanames == [next(iter(ticks))]
    assert store_stops[-1]["shutdown_state"] == "NOT_STARTED"
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False


def test_engineering_observation_construction_failure_stops_partial_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(ticks, clock=clock)
    original_getdata = BtApiStore.getdata
    original_broker_stop = BtApiBroker.stop
    original_feed_stop = BtApiFeed.stop
    original_store_stop = BtApiStore.stop
    getdata_calls = 0
    broker_stops: list[Any] = []
    stopped_datanames: list[str] = []
    store_stops: list[Any] = []

    def fail_after_first_feed(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal getdata_calls
        getdata_calls += 1
        if getdata_calls == 2:
            raise RuntimeError("fixture construction failure")
        return original_getdata(self, *args, **kwargs)

    def capture_broker_stop(self: BtApiBroker, *args: Any, **kwargs: Any) -> Any:
        result = original_broker_stop(self, *args, **kwargs)
        broker_stops.append(result)
        return result

    def capture_feed_stop(self: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        stopped_datanames.append(str(self._dataname))
        return original_feed_stop(self, *args, **kwargs)

    def capture_store_stop(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_store_stop(self, *args, **kwargs)
        store_stops.append(result)
        return result

    monkeypatch.setattr(BtApiStore, "getdata", fail_after_first_feed)
    monkeypatch.setattr(BtApiBroker, "stop", capture_broker_stop)
    monkeypatch.setattr(BtApiFeed, "stop", capture_feed_stop)
    monkeypatch.setattr(BtApiStore, "stop", capture_store_stop)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.02,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == "ENGINEERING_CONSTRUCTION_FAILED"
    assert getdata_calls == 2
    assert broker_stops == [{"status": "NOT_STARTED"}]
    assert stopped_datanames == [next(iter(ticks))]
    assert store_stops
    assert store_stops[-1]["shutdown_state"] == "NOT_STARTED"
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False


def test_engineering_observation_run_error_requires_shutdown_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(ticks, clock=clock)
    original_run = bt.Cerebro.run

    def fail_after_normal_teardown(self: bt.Cerebro, *args: Any, **kwargs: Any) -> Any:
        original_run(self, *args, **kwargs)
        raise RuntimeError("fixture run failure after normal teardown")

    def invalid_started_shutdown_summary(self: BtApiBroker) -> dict[str, Any]:
        del self
        return {
            "status": "OBSERVATION_ONLY",
            "market_data_only": True,
            "cancel_requested": 1,
            "close_requested": 0,
            "store_shutdown_state": "PASS",
        }

    monkeypatch.setattr(bt.Cerebro, "run", fail_after_normal_teardown)
    monkeypatch.setattr(BtApiBroker, "get_shutdown_summary", invalid_started_shutdown_summary)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.02,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == "SHUTDOWN_INCOMPLETE"
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False


def test_engineering_observation_run_error_with_summary_getter_failure_forces_graph_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed summary read cannot bypass the explicit error-path teardown."""

    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(ticks, clock=clock)
    original_run = bt.Cerebro.run
    original_broker_stop = BtApiBroker.stop
    original_feed_stop = BtApiFeed.stop
    original_store_stop = BtApiStore.stop
    normal_teardown_finished = False
    forced_broker_stops: list[None] = []
    forced_feed_stops: list[str] = []
    forced_store_stops: list[None] = []

    def fail_after_normal_teardown(self: bt.Cerebro, *args: Any, **kwargs: Any) -> Any:
        nonlocal normal_teardown_finished
        original_run(self, *args, **kwargs)
        normal_teardown_finished = True
        raise RuntimeError("fixture run failure after normal teardown")

    def failing_shutdown_summary(self: BtApiBroker) -> Any:
        del self
        raise RuntimeError("fixture shutdown-summary getter failure")

    def capture_broker_stop(self: BtApiBroker, *args: Any, **kwargs: Any) -> Any:
        if normal_teardown_finished:
            forced_broker_stops.append(None)
        return original_broker_stop(self, *args, **kwargs)

    def capture_feed_stop(self: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        if normal_teardown_finished:
            forced_feed_stops.append(str(self._dataname))
        return original_feed_stop(self, *args, **kwargs)

    def capture_store_stop(self: Any, *args: Any, **kwargs: Any) -> Any:
        if normal_teardown_finished:
            forced_store_stops.append(None)
        return original_store_stop(self, *args, **kwargs)

    monkeypatch.setattr(bt.Cerebro, "run", fail_after_normal_teardown)
    monkeypatch.setattr(BtApiBroker, "get_shutdown_summary", failing_shutdown_summary)
    monkeypatch.setattr(BtApiBroker, "stop", capture_broker_stop)
    monkeypatch.setattr(BtApiFeed, "stop", capture_feed_stop)
    monkeypatch.setattr(BtApiStore, "stop", capture_store_stop)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.02,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == "SHUTDOWN_INCOMPLETE"
    assert forced_broker_stops == [None]
    assert set(forced_feed_stops) == set(ticks)
    assert forced_store_stops == [None]
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False


def test_engineering_observation_construction_cleanup_failure_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(ticks, clock=clock)
    original_getdata = BtApiStore.getdata
    original_feed_stop = BtApiFeed.stop
    original_store_stop = BtApiStore.stop
    getdata_calls = 0
    stopped_datanames: list[str] = []
    store_stops: list[Any] = []

    def fail_after_first_feed(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal getdata_calls
        getdata_calls += 1
        if getdata_calls == 2:
            raise RuntimeError("fixture construction failure")
        return original_getdata(self, *args, **kwargs)

    def fail_broker_stop(self: BtApiBroker, *args: Any, **kwargs: Any) -> Any:
        del self, args, kwargs
        raise RuntimeError("fixture broker cleanup failure")

    def capture_feed_stop(self: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        stopped_datanames.append(str(self._dataname))
        return original_feed_stop(self, *args, **kwargs)

    def capture_store_stop(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_store_stop(self, *args, **kwargs)
        store_stops.append(result)
        return result

    monkeypatch.setattr(BtApiStore, "getdata", fail_after_first_feed)
    monkeypatch.setattr(BtApiBroker, "stop", fail_broker_stop)
    monkeypatch.setattr(BtApiFeed, "stop", capture_feed_stop)
    monkeypatch.setattr(BtApiStore, "stop", capture_store_stop)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.02,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == "SHUTDOWN_INCOMPLETE"
    assert getdata_calls == 2
    assert stopped_datanames == [next(iter(ticks))]
    assert store_stops
    assert store_stops[-1]["shutdown_state"] == "NOT_STARTED"
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False


def test_engineering_observation_accepts_concrete_second_set_session_profile_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report, api, _, state = _run_observation(
        monkeypatch,
        session_state={
            "environment_profile": "set2_7x24_future_public_route",
            "read_only_ready": True,
            "execution_gate_armed": False,
            "account_fingerprint": "iter25-observation-account",
            "connection_generation": 1,
        },
    )

    assert report["session_binding"]["actual_environment_profile"] == (
        "set2_7x24_future_public_route"
    )
    assert len(api.session_state_calls) >= 2
    assert set(api.session_state_calls) == {"CTP___FUTURE"}
    assert state.now == pytest.approx(0.05)
    _assert_controlled_watchdogs_closed(state, active_interval=0.05)


def test_engineering_observation_rejects_unavailable_connected_session_identity() -> None:
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(ticks, clock=clock, session_state=False)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.05,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == "CTP_SESSION_STATE_REQUIRED"
    assert len(api.session_state_calls) >= 2
    assert set(api.session_state_calls) == {"CTP___FUTURE"}
    assert api.session_state_connected_at_call
    assert all(api.session_state_connected_at_call)
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_write_membrane_never_delegates_any_write_method() -> None:
    api = ObservationApi({}, clock=LiveClock())
    api.unclassified_mutation = lambda: (_ for _ in ()).throw(AssertionError("delegated write"))
    configured: list[dict[str, bool]] = []
    api.configure_execution = lambda config: configured.append(dict(config))
    guard = adapter._ObservationReadOnlyApi(api)

    for method_name in (
        "submit_order",
        "cancel_order",
        "settlement_confirm",
        "configure_ctp_execution_authorization",
        "prepare_execution_recovery",
        "disarm_execution",
        "arm_execution_from_preflight",
        "arm_execution_from_approval",
        "confirm_ctp_settlement_from_approval",
        "unclassified_mutation",
    ):
        with pytest.raises(adapter.EngineeringObservationBlocked) as error:
            getattr(guard, method_name)()
        assert error.value.code == "FORBIDDEN_WRITE_ATTEMPT"

    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert set(guard.audit()["forbidden_write_attempts"]) == {
        "submit_order",
        "cancel_order",
        "settlement_confirm",
        "configure_ctp_execution_authorization",
        "prepare_execution_recovery",
        "disarm_execution",
        "arm_execution_from_preflight",
        "arm_execution_from_approval",
        "confirm_ctp_settlement_from_approval",
        "unclassified_mutation",
    }
    guard.configure_execution({"market_data_only": True})
    assert configured == [{"market_data_only": True}]


@pytest.mark.parametrize("seconds", (0, -1, 3600.1))
def test_engineering_observation_rejects_unbounded_duration_before_api_start(
    seconds: float,
) -> None:
    ticks, bundle = _live_ticks()
    clock = LiveClock()
    mapping = _mapping(ticks, bundle)
    api = ObservationApi(ticks, clock=clock)

    with pytest.raises(adapter.EngineeringObservationBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=seconds,
            feed_clock=clock,
            clock_mapping=mapping,
            live_now_provider=LiveNowProvider(mapping),
        )

    assert error.value.code == "ENGINEERING_DURATION"
    assert api.connected is False
    assert api.connect_calls == 0
