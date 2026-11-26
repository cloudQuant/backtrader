from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "examples" / "live" / "007_ctp_gateway" / "market_only_probe.py"
SPEC = importlib.util.spec_from_file_location("_test_007_market_only_probe", PROBE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe_module
SPEC.loader.exec_module(probe_module)


def _sdk():
    market_protocol = pytest.importorskip("bt_api_base.market_protocol")
    tick_protocol = pytest.importorskip("bt_api_base.market_tick_protocol")
    service_protocol = pytest.importorskip("bt_api_base.service_protocol")
    service_market = pytest.importorskip("bt_api_py.service_market")
    ctp_process = pytest.importorskip("bt_api_py.ctp_account_process")
    return market_protocol, tick_protocol, service_protocol, service_market, ctp_process


class FakeMonotonic:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class FakeClient:
    def __init__(self, key, bootstrap, deliveries=(), *, monotonic=None):
        self.key = key
        self._bootstrap = bootstrap
        self._deliveries = list(deliveries)
        self._monotonic = monotonic
        self.healthy = True
        self.recovery_required = False
        self.closed = False
        self.poll_timeouts = []

    def start(self):
        return self._bootstrap

    def poll_with_receipt(self, *, timeout_ms):
        self.poll_timeouts.append(timeout_ms)
        if self._deliveries:
            return self._deliveries.pop(0)
        if self._monotonic is not None:
            self._monotonic.value += 1.0
        return None

    def close(self):
        self.closed = True


def _context(snapshot_sequence=0, snapshot=None):
    market_protocol, tick_protocol, service_protocol, service_market, ctp_process = _sdk()
    instrument = market_protocol.MarketInstrumentKey(
        provider="ctp",
        venue="SHFE",
        environment="demo",
        product_type="future",
        instrument_id="rb2701",
        native_symbol="rb2701",
    )
    key = market_protocol.MarketSubscriptionKey(
        source_ref="market-source-test",
        entitlement_ref="market-entitlement-test",
        instrument=instrument,
        channel=ctp_process.CTP_MARKET_TICK_CHANNEL,
    )
    source = market_protocol.MarketSourceDescriptor(
        key=key,
        stream_id=key.stream_id,
        epoch="epoch-test",
        provider="ctp",
        source="ctp.native.md",
        connection_generation=1,
        clock_domain_id="clock-domain-test",
        clock_source_session_id="session-test",
        clock_source="ctp.exchange",
    )
    bootstrap = service_market.MarketBootstrap(
        snapshot=snapshot,
        snapshot_kind="latest_event",
        snapshot_complete=False,
        full_baseline_available=False,
        stream_id=source.stream_id,
        snapshot_epoch=source.epoch,
        snapshot_sequence=snapshot_sequence,
        cursor_epoch=source.epoch,
        cursor_sequence=snapshot_sequence,
        resync_required=False,
        source_descriptor=source,
    )
    return market_protocol, tick_protocol, service_protocol, service_market, key, source, bootstrap


def _payload(tick_protocol, key, provider_time="2026-11-26T02:00:00Z", *, price=987654321.25):
    return tick_protocol.MarketTickPayload(
        instrument=key.instrument,
        last_price=price,
        bid_price=None,
        ask_price=None,
        bid_size=None,
        ask_size=None,
        lower_limit=None,
        upper_limit=None,
        turnover=None,
        open_interest=2.0,
        delta_volume=1.0,
        cumulative_volume=None,
        volume_complete=False,
        volume_quality="unknown",
        continuity_status="continuous",
        trading_date=None,
        event_session_date=None,
        provider_event_time_utc=provider_time,
        event_time_provenance="unavailable" if provider_time is None else "provider_reported",
        received_at_utc=None,
        received_monotonic_ns=None,
        provider_source="ctp.native.md",
        quality_contract_ref=None,
        provider_connection_generation=1,
        provider_sequence=1,
        provider_subscription_epoch=1,
        clock_domain_id="clock-domain-test",
        clock_source_session_id="session-test",
        clock_source="ctp.exchange",
        source_clock_quality=tick_protocol.MarketClockQuality.UNKNOWN,
        receive_clock_quality=tick_protocol.MarketClockQuality.UNKNOWN,
        freshness_status=tick_protocol.MarketFreshnessStatus.UNAVAILABLE,
        execution_eligible=False,
    )


def _frame(
    sequence,
    *,
    provider_time="2026-11-26T02:00:00Z",
    key=None,
    operation=None,
    stream_epoch=None,
    data_changes=None,
    price=987654321.25,
):
    market_protocol, tick_protocol, service_protocol, _service_market, default_key, source, _bootstrap = _context()
    key = key or default_key
    event = _payload(tick_protocol, default_key, provider_time, price=price)
    data = event.to_dict()
    if data_changes:
        data.update(data_changes)
    header = service_protocol.WireHeader(
        protocol_version=service_protocol.WIRE_PROTOCOL_VERSION,
        kind=service_protocol.WireMessageKind.EVENT,
        message_id=f"message-{sequence}",
        correlation_id=None,
        identity=service_protocol.WireIdentity(
            role=service_protocol.WireRole.SERVICE,
            principal_ref="principal:market-test",
            actor_ref="actor:market-test",
        ),
        scope=service_protocol.WireScope(execution_domain_ref="paper:market-test"),
        operation=operation or market_protocol.MARKET_EVENT_OPERATION,
        schema_id=market_protocol.MARKET_EVENT_SCHEMA,
        schema_version=market_protocol.MARKET_EVENT_SCHEMA_VERSION,
        sent_at_utc="2026-11-26T02:00:00Z",
        stream_id=source.stream_id,
        stream_epoch=stream_epoch or source.epoch,
        sequence=sequence,
    )
    return service_protocol.WireEnvelope(
        header=header,
        payload={"key": key.to_dict(), "data": data},
    )


def _receipt(frame, *, source="pub", received_at=None):
    _market_protocol, _tick_protocol, _service_protocol, service_market, _ctp_process = _sdk()
    received_at = received_at or datetime(2026, 11, 26, 2, 0, tzinfo=timezone.utc)
    wall_ns = int(received_at.timestamp()) * 1_000_000_000 + received_at.microsecond * 1_000
    return service_market.MarketReceiveReceipt(
        source=source,
        stream_id=frame.header.stream_id,
        stream_epoch=frame.header.stream_epoch,
        sequence=frame.header.sequence,
        message_id=frame.header.message_id,
        received_wall_ns=wall_ns,
        received_monotonic_ns=10_000_000_000,
        pid=os.getpid(),
        thread_id=threading.get_ident(),
        request_message_id="read-after-request" if source == "replay" else None,
        reply_message_id="read-after-reply" if source == "replay" else None,
    )


def _probe(deliveries=(), *, snapshot_sequence=0, snapshot=None, monotonic=None, wall=None):
    _market_protocol, _tick_protocol, _service_protocol, _service_market, key, _source, bootstrap = _context(
        snapshot_sequence, snapshot
    )
    clock = monotonic or FakeMonotonic()
    client = FakeClient(key, bootstrap, deliveries, monotonic=clock)
    probe = probe_module.MarketHubProbe(
        client,
        symbol="rb2701",
        venue="SHFE",
        monotonic_clock=clock,
        wall_clock=wall or (lambda: datetime(2026, 11, 26, 2, 0, tzinfo=timezone.utc)),
    )
    return probe, client, clock


def test_frozen_mapping_payload_and_tuple_arrays_are_validated_and_bound():
    frame = _frame(1)
    assert type(frame.payload) is MappingProxyType
    assert type(frame.payload["data"]) is MappingProxyType
    assert type(frame.payload["data"]["freshness_reason_codes"]) is tuple
    probe, _client, _clock = _probe([(frame, _receipt(frame))])

    probe.start()
    result = probe.poll_for(1).to_dict()

    assert result["valid_count"] == 1
    assert result["rejected_count"] == 0
    assert result["pub_count"] == 1
    assert result["age_classification_counts"]["RECENT_UNVERIFIED"] == 1


def test_plain_dict_wire_data_uses_the_sdk_market_tick_decoder():
    _market_protocol, tick_protocol, *_rest = _sdk()
    _mp, _tp, _sp, _sm, key, _source, _bootstrap_value = _context()
    raw = _payload(tick_protocol, key).to_dict()

    decoded = tick_protocol.market_tick_payload_from_wire(raw)

    assert type(decoded) is tick_protocol.MarketTickPayload
    assert decoded.instrument == key.instrument


@pytest.mark.parametrize(
    ("frame_changes", "expected_receipt"),
    [
        ({"operation": "market.other"}, "pub"),
        ({"stream_epoch": "wrong-epoch"}, "unknown"),
        ({"data_changes": {"unexpected": "shape"}}, "pub"),
    ],
)
def test_bad_header_epoch_and_dto_are_rejected_without_raw_diagnostics(frame_changes, expected_receipt):
    frame = _frame(1, **frame_changes)
    probe, _client, _clock = _probe([(frame, _receipt(frame))])
    probe.start()

    result = probe.poll_for(1).to_dict()

    assert result["valid_count"] == 0
    assert result["rejected_count"] == 1
    if expected_receipt == "unknown":
        assert result["unknown_receipt_count"] == 1
    else:
        assert result["pub_count"] == 1
    assert "unexpected" not in json.dumps(result)


def test_exact_subscription_key_is_required():
    market_protocol, _tick_protocol, *_rest = _sdk()
    _mp, _tp, _sp, _sm, default_key, _source, _bootstrap_value = _context()
    other_instrument = market_protocol.MarketInstrumentKey(
        provider="ctp",
        venue="SHFE",
        environment="demo",
        product_type="future",
        instrument_id="hc2701",
        native_symbol="hc2701",
    )
    other_key = market_protocol.MarketSubscriptionKey(
        source_ref=default_key.source_ref,
        entitlement_ref=default_key.entitlement_ref,
        instrument=other_instrument,
        channel=default_key.channel,
    )
    frame = _frame(1, key=other_key)
    probe, _client, _clock = _probe([(frame, _receipt(frame))])
    probe.start()

    result = probe.poll_for(1).to_dict()

    assert result["valid_count"] == 0
    assert result["rejected_count"] == 1
    assert result["pub_count"] == 1


def test_sequence_gaps_reject_discontinuous_frame_and_recover_at_next_cursor():
    gap = _frame(2)
    following = _frame(3)
    probe, _client, _clock = _probe(
        [(gap, _receipt(gap)), (following, _receipt(following))]
    )
    probe.start()

    result = probe.poll_for(1).to_dict()

    assert result["sequence_gaps"] == 1
    assert result["rejected_count"] == 1
    assert result["valid_count"] == 1


def test_poll_receipts_separate_pub_replay_and_unknown():
    pub = _frame(1)
    replay = _frame(2)
    unknown = _frame(3)
    probe, _client, _clock = _probe(
        [
            (pub, _receipt(pub, source="pub")),
            (replay, _receipt(replay, source="replay")),
            (unknown, None),
        ]
    )
    probe.start()

    result = probe.poll_for(1).to_dict()

    assert result["valid_count"] == 3
    assert result["pub_count"] == 1
    assert result["replay_count"] == 1
    assert result["unknown_receipt_count"] == 1


@pytest.mark.parametrize(
    "field_name",
    ["sequence", "received_wall_ns", "received_monotonic_ns", "pid", "thread_id"],
)
def test_receipt_numeric_fields_require_exact_int_not_bool(field_name):
    frame = _frame(1)
    receipt = _receipt(frame)
    invalid_receipt = replace(receipt, **{field_name: True})
    probe, _client, _clock = _probe([(frame, invalid_receipt)])
    probe.start()

    result = probe.poll_for(1).to_dict()

    assert result["valid_count"] == 1
    assert result["pub_count"] == 0
    assert result["unknown_receipt_count"] == 1


def test_bootstrap_cursor_sequence_requires_exact_int_not_bool():
    _mp, _tp, _sp, _sm, key, _source, bootstrap = _context(snapshot_sequence=1)
    invalid_bootstrap = replace(bootstrap, cursor_sequence=True)
    clock = FakeMonotonic()
    probe = probe_module.MarketHubProbe(
        FakeClient(key, invalid_bootstrap, monotonic=clock),
        symbol="rb2701",
        venue="SHFE",
        monotonic_clock=clock,
        wall_clock=lambda: datetime(2026, 11, 26, 2, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(probe_module.MarketProbeError) as exc_info:
        probe.start()

    assert exc_info.value.code == "MARKET_BOOTSTRAP_INVALID"


def test_old_future_and_unknown_provider_clock_are_never_reported_fresh():
    local = datetime(2026, 11, 26, 2, 0, tzinfo=timezone.utc)
    old = _frame(1, provider_time="2026-11-26T01:00:00Z")
    future = _frame(2, provider_time="2026-11-26T02:00:01Z")
    unknown = _frame(3, provider_time=None)
    recent_unknown_quality = _frame(4, provider_time="2026-11-26T01:59:59Z")
    deliveries = [
        (old, _receipt(old, received_at=local)),
        (future, _receipt(future, received_at=local)),
        (unknown, _receipt(unknown, received_at=local)),
        (recent_unknown_quality, _receipt(recent_unknown_quality, received_at=local)),
    ]
    probe, _client, _clock = _probe(deliveries, wall=lambda: local)
    probe.start()

    result = probe.poll_for(1).to_dict()

    ages = result["age_classification_counts"]
    assert result["valid_count"] == 4
    assert ages["STALE_OR_DELAYED_CANDIDATE"] == 1
    assert ages["RECENT_UNVERIFIED"] == 1
    assert ages["NOT_ASSESSED"] == 2
    assert "FRESH" not in json.dumps(result)


def test_output_is_allowlisted_and_does_not_leak_quote_or_connection_values():
    frame = _frame(1, price=987654321.25)
    probe, _client, _clock = _probe([(frame, _receipt(frame))])
    probe.start()
    output = json.dumps(probe.poll_for(1).to_dict(), sort_keys=True)

    assert "987654321.25" not in output
    assert "rb2701" not in output
    for private_label in (
        "market-source-test",
        "market-entitlement-test",
        "principal:market-test",
        "actor:market-test",
        "paper:market-test",
        "epoch-test",
        "clock-domain-test",
        "session-test",
    ):
        assert private_label not in output
    assert "endpoint" not in output
    assert json.loads(output)["failure_code"] is None
    assert set(json.loads(output)) == {
        "probe_status",
        "cleanup_status",
        "failure_code",
        "valid_count",
        "rejected_count",
        "pub_count",
        "replay_count",
        "unknown_receipt_count",
        "sequence_gaps",
        "first_provider_event_time_utc",
        "last_provider_event_time_utc",
        "first_local_receive_time_utc",
        "last_local_receive_time_utc",
        "age_classification_counts",
    }


def test_dependency_preflight_runs_before_resource_loader(monkeypatch):
    events = []
    clock = FakeMonotonic()
    _mp, _tp, _sp, _sm, key, _source, bootstrap = _context()

    class Lease:
        active = False
        retained = False
        held = False

        def acquire(self):
            events.append("lease_acquire")
            self.held = True

        def mark_active(self, **_kwargs):
            self.active = True

        def mark_uncertain(self):
            self.retained = True

        def clear_active_marker(self):
            self.active = False

        def release_clean(self):
            self.held = False

        def release_unstarted(self):
            self.held = False

    class Runtime:
        def start(self):
            pass

        def close(self):
            pass

    client = FakeClient(key, bootstrap, monotonic=clock)
    runtime = Runtime()
    original_preflight = probe_module.preflight_market_probe_dependencies
    def preflight():
        events.append("preflight")
        dependencies = original_preflight()
        return probe_module._ProbeDependencies(
            resources=dependencies.resources,
            runtime_factory=lambda _connection, *, start: (runtime, object()),
            client_factory=lambda *_args: client,
        )

    def resource_loader(_path):
        events.append("resource_loader")
        return SimpleNamespace(generation_id="generation-test", connection=object())

    monkeypatch.setattr(probe_module, "preflight_market_probe_dependencies", preflight)
    result = probe_module.run_market_probe(
        "synthetic-root",
        symbol="rb2701",
        venue="SHFE",
        duration_seconds=1,
        resource_loader=resource_loader,
        lease_factory=Lease,
        monotonic_clock=clock,
    )

    assert result.probe_status == "complete"
    assert result.failure_code is None
    assert events.index("preflight") < events.index("resource_loader")


def test_public_dependency_preflight_binds_default_composition_without_starting_it():
    dependencies = probe_module.preflight_market_probe_dependencies()

    assert dependencies.runtime_factory.__module__ == "bt_api_py.ctp_gateway_composition"
    assert dependencies.client_factory.__module__ == "bt_api_py.ctp_gateway_composition"
    assert dependencies.resources.__name__.endswith("market_only_resources")
    for module_name in (
        "zmq",
        "zmq.utils.z85",
        "bt_api_base.market_tick_protocol",
        "bt_api_base.service_protocol",
        "bt_api_py.ctp_account_process",
        "bt_api_py.ctp_gateway_composition",
        "bt_api_py.gateway_market_runtime",
        "bt_api_py.service_config",
        "bt_api_py.service_market",
        "bt_api_py.service_runtime",
        "bt_api_transport_zmq.market_v2",
        "bt_api_transport_zmq.server",
        "bt_api_transport_zmq.service_v2",
    ):
        assert module_name in sys.modules
    if os.name == "nt":
        assert "bt_api_py._win32_security" in sys.modules


def test_summary_failure_code_is_restricted_to_fixed_ascii_allowlist():
    summary = replace(
        probe_module._SummaryBuilder().freeze(),
        failure_code="endpoint-private-reference",
    )

    assert summary.failure_code == "MARKET_PROBE_FAILED"
    assert "endpoint-private-reference" not in json.dumps(summary.to_dict())


def test_lock_busy_and_existing_uncertainty_have_finite_failure_codes(monkeypatch):
    lock = threading.Lock()
    retained = []
    monkeypatch.setattr(probe_module, "_PROBE_LOCK", lock)
    monkeypatch.setattr(probe_module, "_UNCERTAIN_PROBES", retained)
    lock.acquire()
    busy = probe_module.run_market_probe(
        "synthetic-root", symbol="rb2701", venue="SHFE", duration_seconds=1
    )
    assert busy.failure_code == "PROBE_LOCK_BUSY"
    assert busy.cleanup_status == "not_started"
    lock.release()

    retained.append(object())
    uncertain = probe_module.run_market_probe(
        "synthetic-root", symbol="rb2701", venue="SHFE", duration_seconds=1
    )
    assert uncertain.failure_code == "MARKET_PROBE_UNCERTAIN_SESSION_RETAINED"
    assert uncertain.cleanup_status == "uncertain"
    assert lock.locked()


def test_probe_methods_are_owner_thread_bound():
    probe, _client, _clock = _probe()
    probe.start()
    failures = []

    def poll_on_other_thread():
        try:
            probe.poll_for(1)
        except probe_module.MarketProbeError as error:
            failures.append(error.code)

    thread = threading.Thread(target=poll_on_other_thread)
    thread.start()
    thread.join()

    assert failures == ["MARKET_PROBE_OWNER_THREAD_MISMATCH"]


def test_session_closes_client_then_runtime_then_identity_lease():
    calls = []

    class Client:
        def close(self):
            calls.append("client")

    class Runtime:
        def close(self):
            calls.append("runtime")

    class Lease:
        active = True
        retained = False
        held = True

        def clear_active_marker(self):
            calls.append("clear_marker")
            self.active = False

        def release_clean(self):
            calls.append("release_clean")
            self.held = False

        def release_unstarted(self):
            raise AssertionError("active lease must not use unstarted release")

        def mark_uncertain(self):
            calls.append("mark_uncertain")

    session = probe_module._ProbeSession()
    session.client = Client()
    session.runtime = Runtime()
    session.lease = Lease()

    assert session.close_once() is True
    assert calls == ["client", "runtime", "clear_marker", "release_clean"]


def test_cleanup_uncertain_retains_session_runtime_client_and_global_latch(monkeypatch):
    lock = threading.Lock()
    retained = []
    monkeypatch.setattr(probe_module, "_PROBE_LOCK", lock)
    monkeypatch.setattr(probe_module, "_UNCERTAIN_PROBES", retained)
    clock = FakeMonotonic()
    _mp, _tp, _sp, _sm, key, _source, bootstrap = _context()
    closed = []

    class Lease:
        active = False
        held = False
        retained = False

        def acquire(self):
            self.held = True

        def mark_active(self, **_kwargs):
            self.active = True

        def mark_uncertain(self):
            self.retained = True

        def clear_active_marker(self):
            raise AssertionError("uncertain client close cannot clear marker")

        def release_clean(self):
            raise AssertionError("uncertain client close cannot release lease")

        def release_unstarted(self):
            raise AssertionError("active lease must be retained")

    class Runtime:
        def start(self):
            pass

        def close(self):
            closed.append("runtime")

    class Client(FakeClient):
        def close(self):
            closed.append("client")
            service_market = _sdk()[3]
            raise service_market.ServiceMarketError("UNSUBSCRIPTION_UNCERTAIN")

    runtime = Runtime()
    client = Client(key, bootstrap, monotonic=clock)
    lease = Lease()
    result = probe_module.run_market_probe(
        "synthetic-root",
        symbol="rb2701",
        venue="SHFE",
        duration_seconds=1,
        resource_loader=lambda _path: SimpleNamespace(
            generation_id="generation-test", connection=object()
        ),
        lease_factory=lambda: lease,
        runtime_factory=lambda _connection, *, start: (runtime, object()),
        client_factory=lambda *_args: client,
        monotonic_clock=clock,
        wall_clock=lambda: datetime(2026, 11, 26, 2, 0, tzinfo=timezone.utc),
    )

    assert result.probe_status == "failed"
    assert result.cleanup_status == "uncertain"
    assert len(retained) == 1
    assert retained[0].client is client
    assert retained[0].runtime is runtime
    assert retained[0].lease is lease
    assert lease.retained is True
    assert closed == ["client"]
    assert lock.locked()
    assert result.failure_code == "MARKET_UNSUBSCRIPTION_UNCERTAIN"
    assert "synthetic private close detail" not in json.dumps(result.to_dict())


@pytest.mark.parametrize("failure_stage", ["runtime_start", "client_start"])
def test_uncertain_startup_is_not_closed_or_retried(failure_stage, monkeypatch):
    lock = threading.Lock()
    retained = []
    monkeypatch.setattr(probe_module, "_PROBE_LOCK", lock)
    monkeypatch.setattr(probe_module, "_UNCERTAIN_PROBES", retained)
    clock = FakeMonotonic()
    _mp, _tp, _sp, _sm, key, _source, bootstrap = _context()
    cleanup_calls = []

    class Lease:
        active = False
        held = False
        retained = False

        def acquire(self):
            self.held = True

        def mark_active(self, **_kwargs):
            self.active = True

        def mark_uncertain(self):
            self.retained = True

        def clear_active_marker(self):
            cleanup_calls.append("clear_marker")

        def release_clean(self):
            cleanup_calls.append("release_clean")

        def release_unstarted(self):
            cleanup_calls.append("release_unstarted")

    class Runtime:
        def start(self):
            if failure_stage == "runtime_start":
                raise OSError("synthetic startup uncertainty")

        def close(self):
            cleanup_calls.append("runtime_close")

    class Client(FakeClient):
        def start(self):
            if failure_stage == "client_start":
                raise OSError("synthetic startup uncertainty")
            return super().start()

        def close(self):
            cleanup_calls.append("client_close")

    lease = Lease()
    runtime = Runtime()
    client = Client(key, bootstrap, monotonic=clock)
    result = probe_module.run_market_probe(
        "synthetic-root",
        symbol="rb2701",
        venue="SHFE",
        duration_seconds=1,
        resource_loader=lambda _path: SimpleNamespace(
            generation_id="generation-test", connection=object()
        ),
        lease_factory=lambda: lease,
        runtime_factory=lambda _connection, *, start: (runtime, object()),
        client_factory=lambda *_args: client,
        monotonic_clock=clock,
    )

    assert result.cleanup_status == "uncertain"
    assert result.failure_code == (
        "MARKET_RUNTIME_START_FAILED"
        if failure_stage == "runtime_start"
        else "MARKET_CLIENT_START_FAILED"
    )
    assert cleanup_calls == []
    assert retained and retained[0].runtime is runtime
    if failure_stage == "client_start":
        assert retained[0].client is client
    assert lease.retained is True
    assert lock.locked()
