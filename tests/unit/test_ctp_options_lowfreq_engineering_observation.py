"""Bounded, zero-write Set-2 engineering observation coverage for Iteration 23.

The fixture drives the actual Store/Feed/Broker/Cerebro/low-frequency-strategy
chain through a finite amount of strict CTP-v2-shaped market data, then lets a
deadline stop the otherwise-live source.  It never reads credentials, opens a
socket, or treats the local fixture as CTP/SimNow execution evidence.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib
import threading
import time
from typing import Any, Iterable, Mapping

import pytest

from backtrader.events import TickEvent
from backtrader.feeds import BarEvidence, ClockMapping
from backtrader.feeds.btapifeed import BtApiFeed
from tests.fixtures.fake_btapi import FakeBtApiClient

runner = importlib.import_module("examples.014_1_ctp_options_lowfreq.run")
adapter = importlib.import_module("examples.014_1_ctp_options_lowfreq.simnow_adapter")

CONFIG = runner.load_config()
BASE = dt.datetime(2026, 9, 14, 1, 0, tzinfo=dt.timezone.utc)
LIVE_DOMAIN = "iter23-engineering-live-clock"
RULES_HASH = "iter23-engineering-live-rules-v1"
CANDIDATE_ID = "ctp_options_lowfreq-second-set-engineering-observation-v1"


class FixedLiveClock:
    """Caller-owned monotonic source; it never falls back to process time."""

    def monotonic_ns(self) -> int:
        return 1_000_000_000


class ObservationApi(FakeBtApiClient):
    """A local source which stays live until the observation deadline stops it."""

    def __init__(
        self,
        ticks: Mapping[str, Iterable[Any]],
        *,
        session_state: Mapping[str, Any] | None = None,
        session_state_available: bool = True,
        connect_delay_seconds: float = 0.0,
    ) -> None:
        super().__init__(live_ticks=ticks)
        self._symbols = tuple(ticks)
        self._next_symbol = 0
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.connect_delay_seconds = connect_delay_seconds
        # Exposes one public managed-CTP route to the Store without making
        # this local fixture an SDK or external-session attestation.
        self.exchange_kwargs = {"CTP___FUTURE": {}}
        self.session_state_available = session_state_available
        self.ctp_session_state_calls: list[str] = []
        self.execution_route_calls: list[str] = []
        self.session_state = {
            "environment_profile": "set2_7x24_4000x",
            "account_fingerprint": "test-iter23-account-fingerprint",
            "read_only_ready": True,
            "execution_gate_armed": False,
            "connection_generation": 7,
        }
        if session_state is not None:
            self.session_state.update(dict(session_state))

    def connect(self) -> None:
        self.connect_calls += 1
        super().connect()
        if self.connect_delay_seconds:
            time.sleep(self.connect_delay_seconds)

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        super().disconnect()

    def poll_tick(self, dataname: str) -> Any:
        if not self._symbols or dataname != self._symbols[self._next_symbol]:
            return None
        tick = super().poll_tick(dataname)
        if tick is not None:
            self._next_symbol = (self._next_symbol + 1) % len(self._symbols)
        return tick

    def is_source_exhausted(self, _symbol: str) -> bool:
        # The timer, not local fixture EOF, must own the bounded shutdown.
        return False

    def get_ctp_session_state(self, exchange_name: str = "CTP___FUTURE") -> dict[str, Any]:
        assert exchange_name == "CTP___FUTURE"
        self.ctp_session_state_calls.append(exchange_name)
        if not self.session_state_available:
            raise RuntimeError("fixture session state unavailable")
        return {"connected": self.connected, "ready": True, **self.session_state}

    def submit_order(self, _payload: Mapping[str, Any]) -> None:
        raise AssertionError("zero-write engineering observation must not submit orders")

    def cancel_order(self, _order_ref: str, dataname: str | None = None) -> None:
        raise AssertionError(
            f"zero-write engineering observation must not cancel an order for {dataname}"
        )

    def arm_execution_from_preflight(self, *_args: Any, **_kwargs: Any) -> None:
        self.execution_route_calls.append("arm_execution_from_preflight")

    def arm_execution_from_approval(self, *_args: Any, **_kwargs: Any) -> None:
        self.execution_route_calls.append("arm_execution_from_approval")

    def confirm_ctp_settlement_from_approval(self, *_args: Any, **_kwargs: Any) -> None:
        self.execution_route_calls.append("confirm_ctp_settlement_from_approval")

    def custom_execution_route(self, *_args: Any, **_kwargs: Any) -> None:
        self.execution_route_calls.append("custom_execution_route")


def _tick(symbol: str, price: float, sequence: int, timestamp: dt.datetime) -> TickEvent:
    event = TickEvent(
        timestamp=timestamp.timestamp(),
        symbol=symbol,
        exchange="CZCE",
        asset_type="futures" if symbol == CONFIG["candidate"]["future"] else "option",
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
    event.cum_volume = 100.0 + sequence
    event.cumulative_volume = 100.0 + sequence
    event.delta_volume = 1.0
    event.volume_complete = True
    event.volume_quality = "CONTINUOUS"
    event.trading_day = "20260914"
    event.action_day = "20260914"
    event.event_time_utc = timestamp
    event.recv_time_utc = timestamp + dt.timedelta(microseconds=sequence)
    event.recv_monotonic_ns = 1_000_000_000 + sequence
    event.received_monotonic_ns = event.recv_monotonic_ns
    event.clock_domain_id = LIVE_DOMAIN
    event.connection_generation = 7
    event.subscription_epoch = 3
    event.ingest_seq = sequence
    event.rules_hash = RULES_HASH
    event.session_segment = "second-set-engineering-observation"
    event.source = "tests.iter23.engineering.live-ctp-source"
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


def _ticks() -> dict[str, list[TickEvent]]:
    candidate = CONFIG["candidate"]
    first = BASE
    # The second bucket closes the first 15-minute bucket through the Feed's
    # native watermark path.  The source then remains live until runstop().
    second = BASE + dt.timedelta(minutes=15, milliseconds=500)
    return {
        candidate["future"]: [
            _tick(candidate["future"], 1000.0, 1, first),
            _tick(candidate["future"], 1001.0, 4, second),
        ],
        candidate["call"]: [
            _tick(candidate["call"], 30.0, 2, first),
            _tick(candidate["call"], 31.0, 5, second),
        ],
        candidate["put"]: [
            _tick(candidate["put"], 30.0, 3, first),
            _tick(candidate["put"], 29.0, 6, second),
        ],
    }


def _mapping(*, synthetic: bool = False, domain: str = LIVE_DOMAIN) -> ClockMapping:
    return ClockMapping(
        mapping_id="iter23-engineering-live-mapping",
        wall_utc_at_anchor=BASE,
        mono_ns_at_anchor=1_000_000_000,
        clock_domain_id=domain,
        connection_generation=7,
        source="tests.iter23.engineering.live-clock",
        error_bound_ns=0,
        valid_until_mono_ns=1_000_000_000 + 10**15,
        rules_hash=RULES_HASH,
        synthetic=synthetic,
    )


class LiveEvidenceProvider:
    """Turn a Feed-owned frozen bar event into one trusted live BarEvidence."""

    def __init__(self, mapping: ClockMapping) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def __call__(self, bar: Any) -> BarEvidence:
        self.calls.append(str(bar.symbol))
        seal_received_at = bar.available_at
        return BarEvidence(
            symbol=bar.symbol,
            exchange=bar.exchange,
            bucket_start=bar.bucket_start,
            bucket_end=bar.bucket_end,
            available_at=bar.available_at,
            seal_received_mono=(
                self.mapping.map_wall_to_mono_ns(seal_received_at) / 1_000_000_000.0
            ),
            seal_received_at=seal_received_at,
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
            # A foreign provider can build internally valid evidence only by
            # declaring its own mapping domain; the adapter must reject it
            # before Feed-level event matching can accept anything.
            clock_domain=self.mapping.clock_domain_id,
            clock_mode="live",
            candidate_id=CANDIDATE_ID,
            timeframe_seconds=900.0,
            trade_count=bar.trade_count,
            complete=bar.complete,
            clock_mapping=self.mapping,
        )


def _run_observation(
    *,
    api: ObservationApi | None = None,
    evidence_mapping: ClockMapping | None = None,
    session_state: Mapping[str, Any] | None = None,
    session_state_available: bool = True,
    connect_delay_seconds: float = 0.0,
    run_seconds: float = 0.05,
) -> tuple[dict[str, Any], ObservationApi, LiveEvidenceProvider]:
    ticks = _ticks()
    clock_mapping = _mapping()
    api = api or ObservationApi(
        ticks,
        session_state=session_state,
        session_state_available=session_state_available,
        connect_delay_seconds=connect_delay_seconds,
    )
    provider = LiveEvidenceProvider(evidence_mapping or clock_mapping)
    report = runner.run_engineering_observation(
        copy.deepcopy(CONFIG),
        api=api,
        environment_profile="simnow_second_7x24",
        run_seconds=run_seconds,
        feed_clock=FixedLiveClock(),
        clock_mapping=clock_mapping,
        closed_bar_evidence_provider=provider,
    )
    return report, api, provider


def test_engineering_observation_runs_actual_lowfreq_strategy_on_native_chain() -> None:
    report, api, provider = _run_observation()

    assert report["status"] == "PASS_ENGINEERING_STRATEGY_OBSERVATION"
    assert report["mode"] == "shadow"
    assert report["purpose"] == "observation"
    assert "environment_profile" not in report
    assert report["session_binding"] == {
        "source": "BtApiStore.get_ctp_session_state",
        "session_environment_profile": "set2_7x24_4000x",
        "profile_family_prefix": "set2_7x24",
        "account_fingerprint_sha256": hashlib.sha256(
            b"test-iter23-account-fingerprint"
        ).hexdigest(),
        "read_only_ready": True,
        "execution_armed": False,
        "connection_generation": 7,
        "clock_mapping_id": "iter23-engineering-live-mapping",
        "clock_mapping_generation": 7,
    }
    assert "test-iter23-account-fingerprint" not in repr(report)
    assert api.ctp_session_state_calls
    assert report["chain"] == {
        "store": "BtApiStore",
        "feeds": ["BtApiFeed", "BtApiFeed", "BtApiFeed"],
        "broker": "BtApiBroker",
        "cerebro": "Cerebro",
        "strategy": "CtpOptionsLowfreqStrategy",
    }
    assert report["duration"]["requested_seconds"] == 0.05
    assert report["duration"]["deadline_stop_requested"] is True
    assert report["duration"]["lifecycle_deadline_stop_requested"] is False
    assert report["duration"]["total_lifecycle_within_maximum"] is True
    assert report["feed_evidence"] == {
        "provider_emitted_count": 3,
        "accepted_complete_three_leg_input": True,
        "status": "PASS",
        "clock_mode": "live",
        "clock_domain": LIVE_DOMAIN,
        "clock_mapping_id": "iter23-engineering-live-mapping",
        "clock_mapping_generation": 7,
        "bar_only_strict": True,
    }
    assert sorted(provider.calls) == sorted(
        CONFIG["candidate"][key] for key in ("future", "call", "put")
    )
    assert report["strategy_logic"] == {
        "status": "NOT_EVALUATED_INSUFFICIENT_CLOSED_BARS",
        "required_closed_bars": 40,
        "observed_complete_three_leg_bars": 1,
        "signal_or_order_claim": "NOT_APPLICABLE_LIFECYCLE_ONLY",
    }
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
        "lowfreq_signal_logic": "NOT_EVALUATED_INSUFFICIENT_CLOSED_BARS",
    }


def test_engineering_observation_accepts_a_public_second_set_profile_variant() -> None:
    report, _, _ = _run_observation(
        session_state={"environment_profile": "set2_7x24_future_public_route"}
    )

    assert report["session_binding"]["session_environment_profile"] == (
        "set2_7x24_future_public_route"
    )


def test_engineering_observation_rejects_replay_mapping_before_api_start() -> None:
    api = ObservationApi(_ticks())
    replay_mapping = _mapping(synthetic=True)

    with pytest.raises(adapter.SimNowBlocked, match="LIVE_CLOCK_MAPPING_REQUIRED"):
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.05,
            feed_clock=FixedLiveClock(),
            clock_mapping=replay_mapping,
            closed_bar_evidence_provider=LiveEvidenceProvider(replay_mapping),
        )

    assert api.connected is False
    assert api.connect_calls == 0


def test_engineering_observation_rejects_cross_scope_evidence_and_still_shuts_down() -> None:
    foreign_mapping = _mapping(domain="iter23-foreign-live-clock")
    clock_mapping = _mapping()
    api = ObservationApi(_ticks())

    with pytest.raises(adapter.SimNowBlocked, match="LIVE_EVIDENCE_MAPPING_REQUIRED"):
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.05,
            feed_clock=FixedLiveClock(),
            clock_mapping=clock_mapping,
            closed_bar_evidence_provider=LiveEvidenceProvider(foreign_mapping),
        )

    assert api.submitted_orders == []
    assert api.cancelled_orders == []
    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_write_membrane_never_delegates_writes() -> None:
    api = ObservationApi({})
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
        "custom_execution_route",
    ):
        with pytest.raises(adapter.SimNowBlocked, match="FORBIDDEN_WRITE_ATTEMPT"):
            getattr(guard, method_name)()

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
        "custom_execution_route",
    }
    assert api.execution_route_calls == []


@pytest.mark.parametrize(
    ("session_state", "available", "reason"),
    (
        ({"environment_profile": "set1_group2"}, True, "SECOND_SET_SESSION_PROFILE_REQUIRED"),
        (
            {"environment_profile": " set2_7x24_future_public_route "},
            True,
            "SECOND_SET_SESSION_PROFILE_REQUIRED",
        ),
        ({"account_fingerprint": ""}, True, "SESSION_ACCOUNT_FINGERPRINT_REQUIRED"),
        ({"read_only_ready": False}, True, "SESSION_READ_ONLY_NOT_READY"),
        ({"execution_gate_armed": True}, True, "SESSION_EXECUTION_GATE_NOT_UNARMED"),
        ({"connection_generation": 8}, True, "SESSION_GENERATION_MISMATCH"),
        ({"connection_generation": 7.9}, True, "SESSION_GENERATION_REQUIRED"),
        ({"connection_generation": "7"}, True, "SESSION_GENERATION_REQUIRED"),
        ({}, False, "CTP_SESSION_STATE_UNAVAILABLE"),
    ),
)
def test_engineering_observation_fails_closed_on_unbound_second_set_session(
    session_state: Mapping[str, Any],
    available: bool,
    reason: str,
) -> None:
    with pytest.raises(adapter.SimNowBlocked, match=reason):
        _run_observation(
            session_state=session_state,
            session_state_available=available,
        )


@pytest.mark.parametrize("seconds", (0, -1, 3600.1))
def test_engineering_observation_rejects_unbounded_duration_before_api_start(
    seconds: float,
) -> None:
    api = ObservationApi(_ticks())

    with pytest.raises(adapter.SimNowBlocked, match="ENGINEERING_DURATION"):
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=seconds,
            feed_clock=FixedLiveClock(),
            clock_mapping=_mapping(),
            closed_bar_evidence_provider=LiveEvidenceProvider(_mapping()),
        )

    assert api.connected is False
    assert api.connect_calls == 0


def test_engineering_observation_global_lifecycle_deadline_stops_slow_prebind_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The global lifecycle deadline starts before Store binding can block."""

    monkeypatch.setattr(adapter, "ENGINEERING_OBSERVATION_MAX_SECONDS", 0.05)

    report, api, _ = _run_observation(
        connect_delay_seconds=0.06,
        run_seconds=0.05,
    )

    assert report["status"] == "INCOMPLETE_ENGINEERING_STRATEGY_OBSERVATION"
    assert report["duration"]["lifecycle_deadline_stop_requested"] is True
    assert report["duration"]["total_lifecycle_within_maximum"] is False
    assert report["duration"]["elapsed_seconds"] > 0.05
    assert "OBSERVATION_TOTAL_LIFECYCLE_DURATION_EXCEEDED" in report["failure_codes"]
    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_global_deadline_starts_before_slow_cerebro_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lifecycle cap covers a blocking native Cerebro constructor too."""

    monkeypatch.setattr(adapter, "ENGINEERING_OBSERVATION_MAX_SECONDS", 0.05)
    api = ObservationApi(_ticks())
    lifecycle_timer_started = threading.Event()
    original_timer = adapter.threading.Timer
    original_cerebro = adapter.bt.Cerebro

    def recording_timer(*args: Any, **kwargs: Any) -> threading.Timer:
        timer = original_timer(*args, **kwargs)
        original_start = timer.start

        def start() -> None:
            lifecycle_timer_started.set()
            original_start()

        timer.start = start
        return timer

    def slow_cerebro(*args: Any, **kwargs: Any) -> Any:
        assert lifecycle_timer_started.is_set()
        time.sleep(0.06)
        return original_cerebro(*args, **kwargs)

    monkeypatch.setattr(adapter.threading, "Timer", recording_timer)
    monkeypatch.setattr(adapter.bt, "Cerebro", slow_cerebro)

    with pytest.raises(adapter.SimNowBlocked, match="OBSERVATION_LIFECYCLE_DURATION_EXCEEDED"):
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.05,
            feed_clock=FixedLiveClock(),
            clock_mapping=_mapping(),
            closed_bar_evidence_provider=LiveEvidenceProvider(_mapping()),
        )

    assert lifecycle_timer_started.is_set()
    assert api.connect_calls == 0
    assert api.connected is False
    assert api.submitted_orders == []
    assert api.cancelled_orders == []


def test_engineering_observation_binding_failure_explicitly_stops_full_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the binding reason only after Broker, all Feeds, and Store stop cleanly."""

    broker_summaries: list[Mapping[str, Any]] = []
    store_health: list[Mapping[str, Any]] = []
    stopped_datanames: list[str] = []
    original_broker_stop = adapter.BtApiBroker.stop
    original_store_stop = adapter.BtApiStore.stop
    original_feed_stop = BtApiFeed.stop

    def record_broker_stop(instance: Any) -> Any:
        result = original_broker_stop(instance)
        summary = instance.get_shutdown_summary()
        assert isinstance(summary, Mapping)
        broker_summaries.append(summary)
        return result

    def record_store_stop(instance: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_store_stop(instance, *args, **kwargs)
        assert isinstance(result, Mapping)
        store_health.append(result)
        return result

    def record_feed_stop(instance: Any) -> Any:
        stopped_datanames.append(str(instance._dataname))
        return original_feed_stop(instance)

    monkeypatch.setattr(adapter.BtApiBroker, "stop", record_broker_stop)
    monkeypatch.setattr(adapter.BtApiStore, "stop", record_store_stop)
    monkeypatch.setattr(BtApiFeed, "stop", record_feed_stop)

    with pytest.raises(adapter.SimNowBlocked, match="SECOND_SET_SESSION_PROFILE_REQUIRED"):
        _run_observation(session_state={"environment_profile": "set1_group2"})

    assert len(broker_summaries) == 1
    assert broker_summaries[0]["status"] == "OBSERVATION_ONLY"
    assert broker_summaries[0]["store_shutdown_state"] == "PASS"
    assert sorted(stopped_datanames) == sorted(
        CONFIG["candidate"][key] for key in ("future", "call", "put")
    )
    assert store_health
    assert store_health[-1]["shutdown_state"] == "PASS"


def test_engineering_observation_binding_failure_becomes_shutdown_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed Feed stop takes precedence over the original binding rejection."""

    stopped_datanames: list[str] = []
    original_feed_stop = BtApiFeed.stop
    failing_dataname = CONFIG["candidate"]["call"]

    def fail_one_feed_stop(instance: Any) -> Any:
        dataname = str(instance._dataname)
        stopped_datanames.append(dataname)
        if dataname == failing_dataname:
            raise RuntimeError("injected feed-stop failure")
        return original_feed_stop(instance)

    monkeypatch.setattr(BtApiFeed, "stop", fail_one_feed_stop)

    with pytest.raises(adapter.SimNowBlocked) as error:
        _run_observation(session_state={"environment_profile": "set1_group2"})

    assert str(error.value) == "ENGINEERING_OBSERVATION_SHUTDOWN_INCOMPLETE"
    assert "SECOND_SET_SESSION_PROFILE_REQUIRED" not in str(error.value)
    assert sorted(stopped_datanames) == sorted(
        CONFIG["candidate"][key] for key in ("future", "call", "put")
    )


def test_engineering_observation_startup_error_explicitly_stops_full_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial Feed startup still stops Broker, every Feed, and Store."""

    broker_summaries: list[Mapping[str, Any]] = []
    store_health: list[Mapping[str, Any]] = []
    stopped_datanames: list[str] = []
    failing_dataname = CONFIG["candidate"]["call"]
    original_broker_stop = adapter.BtApiBroker.stop
    original_store_stop = adapter.BtApiStore.stop
    original_feed_start = BtApiFeed.start
    original_feed_stop = BtApiFeed.stop

    def record_broker_stop(instance: Any) -> Any:
        result = original_broker_stop(instance)
        summary = instance.get_shutdown_summary()
        assert isinstance(summary, Mapping)
        broker_summaries.append(summary)
        return result

    def record_store_stop(instance: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_store_stop(instance, *args, **kwargs)
        assert isinstance(result, Mapping)
        store_health.append(result)
        return result

    def fail_one_feed_start(instance: Any) -> Any:
        if str(instance._dataname) == failing_dataname:
            raise RuntimeError("injected feed-start failure")
        return original_feed_start(instance)

    def record_feed_stop(instance: Any) -> Any:
        stopped_datanames.append(str(instance._dataname))
        return original_feed_stop(instance)

    monkeypatch.setattr(adapter.BtApiBroker, "stop", record_broker_stop)
    monkeypatch.setattr(adapter.BtApiStore, "stop", record_store_stop)
    monkeypatch.setattr(BtApiFeed, "start", fail_one_feed_start)
    monkeypatch.setattr(BtApiFeed, "stop", record_feed_stop)

    with pytest.raises(adapter.SimNowBlocked) as error:
        _run_observation()

    assert str(error.value) == "ENGINEERING_OBSERVATION_RUNTIME"
    assert len(broker_summaries) == 1
    assert broker_summaries[0]["status"] == "OBSERVATION_ONLY"
    assert broker_summaries[0]["store_shutdown_state"] == "PASS"
    assert sorted(stopped_datanames) == sorted(
        CONFIG["candidate"][key] for key in ("future", "call", "put")
    )
    assert store_health[-1]["shutdown_state"] == "PASS"


def test_engineering_observation_unproven_normal_teardown_precedes_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid post-run summary cannot be hidden behind a raw run error."""

    original_shutdown_summary = adapter.BtApiBroker.get_shutdown_summary
    foreign_mapping = _mapping(domain="iter23-foreign-live-clock")
    clock_mapping = _mapping()
    api = ObservationApi(_ticks())

    def invalidate_completed_summary(instance: Any) -> Any:
        summary = original_shutdown_summary(instance)
        if isinstance(summary, Mapping) and summary.get("status") == "OBSERVATION_ONLY":
            return {**summary, "status": "INCOMPLETE"}
        return summary

    monkeypatch.setattr(
        adapter.BtApiBroker,
        "get_shutdown_summary",
        invalidate_completed_summary,
    )

    with pytest.raises(adapter.SimNowBlocked) as error:
        runner.run_engineering_observation(
            copy.deepcopy(CONFIG),
            api=api,
            environment_profile="simnow_second_7x24",
            run_seconds=0.05,
            feed_clock=FixedLiveClock(),
            clock_mapping=clock_mapping,
            closed_bar_evidence_provider=LiveEvidenceProvider(foreign_mapping),
        )

    assert str(error.value) == "ENGINEERING_OBSERVATION_SHUTDOWN_INCOMPLETE"
    assert api.connected is False
    assert api.disconnect_calls == 1


def test_engineering_observation_construction_failure_stops_partial_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-start Feed construction failure still tears down every built node."""

    stopped_datanames: list[str] = []
    store_stop_calls: list[dict[str, Any]] = []
    original_getdata = adapter.BtApiStore.getdata
    original_feed_stop = BtApiFeed.stop
    original_store_stop = adapter.BtApiStore.stop
    getdata_calls = 0
    api = ObservationApi(_ticks())

    def fail_second_getdata(instance: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal getdata_calls
        getdata_calls += 1
        if getdata_calls == 2:
            raise RuntimeError("injected partial-feed construction failure")
        return original_getdata(instance, *args, **kwargs)

    def record_feed_stop(instance: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        stopped_datanames.append(str(instance._dataname))
        return original_feed_stop(instance, *args, **kwargs)

    def record_store_stop(instance: Any, *args: Any, **kwargs: Any) -> Any:
        store_stop_calls.append(dict(kwargs))
        return original_store_stop(instance, *args, **kwargs)

    monkeypatch.setattr(adapter.BtApiStore, "getdata", fail_second_getdata)
    monkeypatch.setattr(BtApiFeed, "stop", record_feed_stop)
    monkeypatch.setattr(adapter.BtApiStore, "stop", record_store_stop)

    with pytest.raises(adapter.SimNowBlocked) as error:
        _run_observation(api=api)

    assert str(error.value) == "ENGINEERING_OBSERVATION_RUNTIME"
    assert stopped_datanames == [CONFIG["candidate"]["future"]]
    assert store_stop_calls == [{"timeout": 2.0}]
    assert api.connect_calls == 0
    assert api.connected is False
    assert api.submitted_orders == []
    assert api.cancelled_orders == []


def test_engineering_observation_construction_shutdown_failure_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unproven construction teardown must replace the initiating raw error."""

    stopped_datanames: list[str] = []
    store_stop_calls: list[dict[str, Any]] = []
    original_getdata = adapter.BtApiStore.getdata
    original_feed_stop = BtApiFeed.stop
    original_store_stop = adapter.BtApiStore.stop
    getdata_calls = 0
    api = ObservationApi(_ticks())

    def fail_second_getdata(instance: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal getdata_calls
        getdata_calls += 1
        if getdata_calls == 2:
            raise RuntimeError("injected partial-feed construction failure")
        return original_getdata(instance, *args, **kwargs)

    def fail_broker_stop(instance: Any, *args: Any, **kwargs: Any) -> Any:
        del instance, args, kwargs
        raise RuntimeError("injected broker construction shutdown failure")

    def record_feed_stop(instance: BtApiFeed, *args: Any, **kwargs: Any) -> Any:
        stopped_datanames.append(str(instance._dataname))
        return original_feed_stop(instance, *args, **kwargs)

    def record_store_stop(instance: Any, *args: Any, **kwargs: Any) -> Any:
        store_stop_calls.append(dict(kwargs))
        return original_store_stop(instance, *args, **kwargs)

    monkeypatch.setattr(adapter.BtApiStore, "getdata", fail_second_getdata)
    monkeypatch.setattr(adapter.BtApiBroker, "stop", fail_broker_stop)
    monkeypatch.setattr(BtApiFeed, "stop", record_feed_stop)
    monkeypatch.setattr(adapter.BtApiStore, "stop", record_store_stop)

    with pytest.raises(adapter.SimNowBlocked) as error:
        _run_observation(api=api)

    assert str(error.value) == "ENGINEERING_OBSERVATION_SHUTDOWN_INCOMPLETE"
    assert stopped_datanames == [CONFIG["candidate"]["future"]]
    assert store_stop_calls == [{"timeout": 2.0}]
    assert api.connect_calls == 0
    assert api.connected is False
    assert api.submitted_orders == []
    assert api.cancelled_orders == []
