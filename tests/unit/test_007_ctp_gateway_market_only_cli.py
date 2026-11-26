from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType, ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = ROOT / "examples" / "live" / "007_ctp_gateway" / "market_only_cli.py"
SPEC = importlib.util.spec_from_file_location("_test_007_market_only_cli", CLI_PATH)
assert SPEC is not None and SPEC.loader is not None
cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cli
SPEC.loader.exec_module(cli)
resources = cli._load_sibling("market_only_resources")
runner = cli._load_sibling("market_only_runner")


def _valid_document(generation_id: str = "generation-test") -> dict:
    return {
        "schema_version": 1,
        "generation_id": generation_id,
        "gateway": {
            "ctp_profile": "test_profile",
            "rpc_endpoint": "tcp://127.0.0.1:27001",
            "market_endpoint": "tcp://127.0.0.1:27002",
            "source_ref": "market-source-test",
            "entitlement_ref": "market-entitlement-test",
        },
    }


def test_connection_document_rejects_extra_fields_bad_refs_and_non_loopback():
    expected = ("market-source-test", "market-entitlement-test")
    original = resources._expected_refs
    resources._expected_refs = lambda _profile: expected
    try:
        valid = _valid_document()
        assert resources.validate_market_connection_document(
            valid, generation_id="generation-test"
        )["market_endpoint"] == "tcp://127.0.0.1:27002"

        extra = _valid_document()
        extra["resources"] = "must-not-be-read"
        with pytest.raises(resources.MarketOnlyResourceError, match="CONNECTION_SCHEMA_INVALID"):
            resources.validate_market_connection_document(extra, generation_id="generation-test")

        bad_ref = _valid_document()
        bad_ref["gateway"]["source_ref"] = "other"
        with pytest.raises(resources.MarketOnlyResourceError, match="GATEWAY_REFERENCE_MISMATCH"):
            resources.validate_market_connection_document(bad_ref, generation_id="generation-test")

        non_loopback = _valid_document()
        non_loopback["gateway"]["rpc_endpoint"] = "tcp://0.0.0.0:27001"
        with pytest.raises(resources.MarketOnlyResourceError, match="GATEWAY_ENDPOINT_INVALID"):
            resources.validate_market_connection_document(non_loopback, generation_id="generation-test")
    finally:
        resources._expected_refs = original


def test_loader_reads_only_fixed_connection_and_three_key_files(tmp_path, monkeypatch):
    zmq = pytest.importorskip("zmq")
    root = tmp_path / "generation-test"
    (root / "gateway" / "keys").mkdir(parents=True)
    config_path = root / "gateway" / "market_connection.json"
    raw = json.dumps(_valid_document(), separators=(",", ":")).encode("utf-8")
    server_public, _server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    keys = {
        "server.public": server_public,
        "client.public": client_public,
        "client.secret": client_secret,
    }
    reads = []

    monkeypatch.setattr(resources, "_validate_resource_tree", lambda _root: None)
    monkeypatch.setattr(resources, "_expected_refs", lambda _profile: ("market-source-test", "market-entitlement-test"))

    def read_json(path):
        reads.append(Path(path))
        assert Path(path) == config_path
        return raw

    def read_key(path, *, private):
        path = Path(path)
        reads.append(path)
        assert path.parent == root / "gateway" / "keys"
        assert path.name in keys
        assert private is (path.name == "client.secret")
        return keys[path.name]

    monkeypatch.setattr(resources, "_read_private_json", read_json)
    monkeypatch.setattr(resources, "_read_key_file", read_key)

    class FakeConnection:
        def __init__(self, **values):
            self.values = values

        def __repr__(self):
            return "FakeConnection(<keys-redacted>)"

    sdk_module = ModuleType("bt_api_py.ctp_gateway_composition")
    sdk_module.GatewayClientConnection = FakeConnection
    monkeypatch.setitem(sys.modules, "bt_api_py.ctp_gateway_composition", sdk_module)

    loaded = resources.load_market_connection(root)
    assert loaded.generation_id == "generation-test"
    assert loaded.connection_json_sha256 == hashlib.sha256(raw).hexdigest()
    assert loaded.connection.values["rpc_endpoint"] == "tcp://127.0.0.1:27001"
    assert loaded.connection.values["client_secret_key"] == client_secret
    assert {path.name for path in reads if path.parent.name == "keys"} == set(keys)
    assert not any(path.name in {"resources.json", "server.secret"} for path in reads)
    assert "ctp_profile" not in loaded.connection.values
    assert client_secret.decode("ascii") not in repr(loaded.connection)

    mismatched_keys = dict(keys)
    mismatched_keys["client.public"] = server_public
    monkeypatch.setattr(
        resources,
        "_read_key_file",
        lambda path, *, private: mismatched_keys[Path(path).name],
    )
    with pytest.raises(resources.MarketOnlyResourceError, match="CLIENT_KEY_PAIR_INVALID"):
        resources.load_market_connection(root)


def test_fixed_key_reader_requires_exact_z85_length_and_private_acl(tmp_path, monkeypatch):
    zmq = pytest.importorskip("zmq")
    public, _secret = zmq.curve_keypair()
    dacl_checks = []

    class FakeSecurity:
        def __init__(self, value):
            self.value = value

        def read_bounded_windows(self, path, limit, *, protected):
            assert Path(path).name == "client.secret"
            assert limit == 40 and protected is True
            return self.value

    monkeypatch.setattr(resources, "_windows_security", lambda: FakeSecurity(public))
    monkeypatch.setattr(resources, "_local_resource_module", lambda: SimpleNamespace(
        _assert_private_dacl_windows=lambda path: dacl_checks.append(Path(path).name)
    ))
    assert resources._read_key_file(tmp_path / "client.secret", private=True) == public
    assert dacl_checks == ["client.secret", "client.secret"]

    monkeypatch.setattr(resources, "_windows_security", lambda: FakeSecurity(public + b"x"))
    with pytest.raises(resources.MarketOnlyResourceError, match="KEY_LENGTH_INVALID"):
        resources._read_key_file(tmp_path / "client.secret", private=True)


def test_loader_rejects_noncanonical_or_traversing_resource_root(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "generation-test"
    root.mkdir()
    with pytest.raises(resources.MarketOnlyResourceError, match="RESOURCE_ROOT_INVALID"):
        resources._canonical_resource_root(parent / "unused" / ".." / "generation-test")


def test_generation_root_accepts_79_chars_and_rejects_long_or_unsafe_names(tmp_path):
    accepted_name = "g" + "x" * 78
    accepted_root = tmp_path / accepted_name
    accepted_root.mkdir()
    assert resources._canonical_resource_root(accepted_root)[1] == accepted_name

    too_long_name = "g" + "x" * 128
    assert len(too_long_name) == 129
    assert resources._GENERATION_RE.fullmatch(too_long_name) is None

    invalid_character = tmp_path / "generation.test"
    invalid_character.mkdir()
    with pytest.raises(resources.MarketOnlyResourceError, match="RESOURCE_ROOT_INVALID"):
        resources._canonical_resource_root(invalid_character)


@pytest.mark.parametrize("run_id", ["A" * 32, "a" * 31, "a" * 33, "run-test"])
def test_identity_lease_rejects_run_ids_outside_32_lowercase_hex(tmp_path, run_id):
    lease = resources.GlobalMarketIdentityLease(tmp_path)
    lease._lock = SimpleNamespace(held=True, _fd=0)
    with pytest.raises(resources.MarketOnlyResourceError, match="MARKET_IDENTITY_LEASE_INVALID"):
        lease.mark_active(generation_id="generation-test", run_id=run_id)


def test_cli_rejects_group_or_repeated_strategy_before_resource_read(tmp_path):
    reads = []
    lease_calls = []
    args = [
        "--strategy", "sa_dual_ma_gateway",
        "--strategy", "sa_dual_ma_gateway",
        "--duration-seconds", "60",
        "--resource-root", str(tmp_path / "generation-test"),
    ]
    with pytest.raises(SystemExit):
        cli.main(
            args,
            resource_loader=lambda *_: reads.append("loaded"),
            lease_factory=lambda: lease_calls.append("lease"),
        )
    assert reads == []
    assert lease_calls == []

    with pytest.raises(SystemExit):
        cli.main(
            [
                "--strategy", "sa_dual_ma_gateway,tickbroker_single_symbol_gateway",
                "--duration-seconds", "60",
                "--resource-root", str(tmp_path / "generation-test"),
            ],
            resource_loader=lambda *_: reads.append("loaded"),
            lease_factory=lambda: lease_calls.append("lease"),
        )
    assert reads == []
    assert lease_calls == []


def test_cli_uncertain_global_identity_blocks_before_resource_read(tmp_path):
    reads = []

    class UncertainLease:
        def acquire(self):
            raise resources.MarketOnlyResourceError("MARKET_IDENTITY_CLEANUP_UNCERTAIN")

        def release_unstarted(self):
            pass

    code = cli.main(
        ["--strategy", "sa_dual_ma_gateway", "--duration-seconds", "10", "--resource-root", str(tmp_path)],
        resource_loader=lambda *_args: reads.append("read"),
        lease_factory=UncertainLease,
    )
    assert code == 2
    assert reads == []


def test_cli_wires_one_run_to_global_lease_and_receipt(tmp_path, monkeypatch):
    root = tmp_path / "generation-test"
    root.mkdir()
    loaded = SimpleNamespace(
        resource_root=root,
        generation_id="generation-test",
        connection=object(),
        connection_json_sha256="a" * 64,
    )
    calls = []

    class FakeLease:
        def __init__(self):
            self.acquired = False
            self.released = False

        def acquire(self):
            self.acquired = True
            calls.append("acquire")

        def release_unstarted(self):
            self.released = True

    class FakeReceipt:
        def __init__(self, path, **values):
            self.path = Path(path)
            self.values = values

    receipt_instances = []

    def receipt_factory(path, **kwargs):
        receipt = FakeReceipt(path, **kwargs)
        receipt_instances.append(receipt)
        return receipt

    def fake_runner(strategy_name, **kwargs):
        calls.append((strategy_name, kwargs))

    monkeypatch.setattr(resources, "_secure_windows_directory", lambda *_args, **_kwargs: None)
    code = cli.main(
        ["--strategy", "sa_dual_ma_gateway", "--duration-seconds", "30", "--resource-root", str(root)],
        resource_loader=lambda path: loaded,
        lease_factory=FakeLease,
        runner=fake_runner,
        receipt_factory=receipt_factory,
    )
    assert code == 0
    assert calls[0] == "acquire"
    strategy_name, kwargs = calls[1]
    assert strategy_name == "sa_dual_ma_gateway"
    assert kwargs["connection"] is loaded.connection
    assert kwargs["run_seconds"] == 30
    assert kwargs["generation_id"] == "generation-test"
    assert kwargs["run_identity"].run_root.parent == root / "strategies-market-only"
    assert kwargs["identity_guard"].acquired
    assert receipt_instances[0].path.parent == kwargs["run_identity"].run_root
    assert receipt_instances[0].values["connection_json_sha256"] == "a" * 64


def test_receipt_aggregates_ticks_without_prices_or_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "_local_resource_module", lambda: SimpleNamespace(
        _assert_private_dacl_windows=lambda _path: None
    ))
    path = tmp_path / "receipt.json"
    sink = resources.MarketOnlyReceiptSink(
        path,
        generation_id="generation-test",
        run_id="a" * 32,
        connection_json_sha256="b" * 64,
    )
    sink.record_start(
        generation_id="generation-test",
        run_id="a" * 32,
        strategy="sa_dual_ma_gateway",
        instruments=[("SA701", "CZCE")],
    )
    secret = b"SYNTHETIC-SECRET-NEVER-RECEIPTED"
    event_time = datetime(2026, 11, 26, 2, 0, tzinfo=timezone.utc)
    for sequence in range(1, 151):
        sink.record_tick(SimpleNamespace(
            symbol="SA701",
            price=987654.321,
            event_time=event_time,
            source_event=SimpleNamespace(cursor=SimpleNamespace(sequence=sequence)),
            secret_key=secret,
        ))
    broker = runner.MarketOnlyBroker()
    with pytest.raises(runner.MarketOnlyOrderRejected):
        broker.buy(None)
    with pytest.raises(runner.MarketOnlyOrderRejected):
        broker.cancel(None)
    with pytest.raises(runner.MarketOnlyPositionUnknown):
        broker.getposition(object())
    strategy_type = runner._guarded_strategy("sa_dual_ma_gateway")
    strategy = object.__new__(strategy_type)
    strategy.market_only_order_attempts = 0
    strategy.market_only_order_rejections = 0
    strategy.market_only_cancel_attempts = 0
    strategy.market_only_cancel_rejections = 0
    with pytest.raises(runner.MarketOnlyOrderRejected):
        strategy.buy(None)
    with pytest.raises(runner.MarketOnlyOrderRejected):
        strategy.cancel(None)

    class FakeCerebro:
        def getbroker(self):
            return broker

    runner._write_receipt_scope(sink, FakeCerebro(), [strategy])
    with pytest.raises(resources.MarketOnlyResourceError, match="RECEIPT_WRITE_SCOPE_INVALID"):
        sink.record_zero_write_scope({"account": "SYNTHETIC-ACCOUNT-NAME"})
    sink.record_cleanup(status="clean")

    raw = path.read_bytes()
    document = json.loads(raw)
    assert len(raw) < 4096
    assert document["ticks"]["SA701"]["count"] == 150
    assert document["ticks"]["SA701"]["first_sequence"] == 1
    assert document["ticks"]["SA701"]["last_sequence"] == 150
    assert [event["type"] for event in document["events"]].count("tick") == 0
    scope = next(event for event in document["events"] if event["type"] == "zero_write_scope")
    assert scope["metrics"]["strategy_order_rejections"] == 1
    assert scope["metrics"]["broker_order_rejections"] == 1
    assert scope["metrics"]["account_read_attempts"] == 1
    assert scope["metrics"]["market_operation_counts_instrumented"] is False
    assert scope["global_zero_write_claim"] is False
    assert b"987654.321" not in raw
    assert secret not in raw


def test_global_lease_serializes_and_uncertain_marker_blocks_later_process(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("the production lease deliberately fails closed outside Windows")

    class Security:
        @staticmethod
        def is_reparse_point(path):
            return Path(path).is_symlink()

    class LocalResourceModule:
        @staticmethod
        def _assert_private_dacl_windows(path):
            assert Path(path).exists()
            assert not Path(path).is_symlink()

    locks = set()

    class FakeFileLock:
        def __init__(self, path, *, timeout):
            self.path = str(path)
            self._fd = None

        @property
        def held(self):
            return self._fd is not None

        def try_acquire(self):
            if self.path in locks:
                return False
            self._fd = os.open(self.path, os.O_RDWR)
            locks.add(self.path)
            return True

        def release(self):
            if self._fd is not None:
                fd, self._fd = self._fd, None
                locks.discard(self.path)
                os.close(fd)

    def replace_bytes(path, data):
        path = Path(path)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    state_root = tmp_path / "global-market-only"
    state_root.mkdir()
    monkeypatch.setattr(resources, "_windows_supported", lambda: True)
    monkeypatch.setattr(resources, "_windows_security", lambda: Security())
    monkeypatch.setattr(resources, "_secure_windows_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(resources, "_local_resource_module", lambda: LocalResourceModule())
    monkeypatch.setattr(resources, "FileLock", FakeFileLock)
    monkeypatch.setattr(resources, "atomic_write_bytes", replace_bytes)

    first = resources.GlobalMarketIdentityLease(state_root)
    first.acquire()
    second = resources.GlobalMarketIdentityLease(state_root)
    with pytest.raises(resources.MarketOnlyResourceError, match="MARKET_IDENTITY_ALREADY_LOCKED"):
        second.acquire()

    first.mark_active(generation_id="generation-test", run_id="a" * 32)
    first.mark_uncertain()
    assert first.held and first.retained
    assert json.loads(first.marker_path.read_text(encoding="utf-8"))["status"] == "uncertain"

    # Simulate process death: the OS lock disappears, while the durable marker remains.
    first._lock.release()
    blocked = resources.GlobalMarketIdentityLease(state_root)
    with pytest.raises(resources.MarketOnlyResourceError, match="MARKET_IDENTITY_CLEANUP_UNCERTAIN"):
        blocked.acquire()
    assert first.marker_path.exists()

    race_root = tmp_path / "marker-race"
    race_root.mkdir()
    raced = resources.GlobalMarketIdentityLease(race_root)
    raced.acquire()
    raced.mark_active(generation_id="generation-test", run_id="b" * 32)
    raced_marker_identity = raced._marker_identity
    replacement = raced.marker_path.with_name("replacement.json")
    replacement.write_text('{"foreign":true}', encoding="utf-8")
    os.replace(replacement, raced.marker_path)
    raced.mark_uncertain()
    assert raced.retained and raced.held
    assert raced._marker_identity == raced_marker_identity
    assert json.loads(raced.marker_path.read_text(encoding="utf-8")) == {"foreign": True}
    raced._lock.release()

    clean_root = tmp_path / "clean-global"
    clean_root.mkdir()
    clean = resources.GlobalMarketIdentityLease(clean_root)
    clean.acquire()
    clean.mark_active(generation_id="generation-test", run_id="c" * 32)
    clean.clear_active_marker()
    clean.release_clean()
    assert not clean.marker_path.exists()
    assert not clean.held


def test_mappingproxy_market_tick_payload_is_accepted_by_market_reader():
    market_protocol = pytest.importorskip("bt_api_base.market_protocol")
    tick_protocol = pytest.importorskip("bt_api_base.market_tick_protocol")
    service_protocol = pytest.importorskip("bt_api_base.service_protocol")

    instrument = market_protocol.MarketInstrumentKey(
        provider="ctp", venue="SHFE", environment="demo", product_type="future",
        instrument_id="rb2701", native_symbol="rb2701",
    )
    key = market_protocol.MarketSubscriptionKey(
        source_ref="market-source-test", entitlement_ref="market-entitlement-test",
        instrument=instrument, channel="tick",
    )
    source = market_protocol.MarketSourceDescriptor(
        key=key, stream_id=key.stream_id, epoch="epoch-1", provider="ctp",
        source="ctp.native.md", connection_generation=1,
        clock_domain_id="clock-domain-test", clock_source_session_id="session-test",
        clock_source="ctp.exchange",
    )
    payload = tick_protocol.MarketTickPayload(
        instrument=instrument,
        last_price=123.5, bid_price=None, ask_price=None, bid_size=None, ask_size=None,
        lower_limit=None, upper_limit=None, turnover=None, open_interest=2.0,
        delta_volume=1.0, cumulative_volume=None, volume_complete=False,
        volume_quality="unknown", continuity_status="continuous",
        trading_date=None, event_session_date=None,
        provider_event_time_utc="2026-11-26T02:00:00Z", event_time_provenance="provider_reported",
        received_at_utc=None, received_monotonic_ns=None, provider_source="ctp.native.md",
        quality_contract_ref=None, provider_connection_generation=1, provider_sequence=7,
        provider_subscription_epoch=1, clock_domain_id="clock-domain-test",
        clock_source_session_id="session-test", clock_source="ctp.exchange",
        source_clock_quality=tick_protocol.MarketClockQuality.UNKNOWN,
        receive_clock_quality=tick_protocol.MarketClockQuality.UNKNOWN,
        freshness_status=tick_protocol.MarketFreshnessStatus.UNAVAILABLE,
        execution_eligible=False,
    )
    header = service_protocol.WireHeader(
        protocol_version=service_protocol.WIRE_PROTOCOL_VERSION,
        kind=service_protocol.WireMessageKind.EVENT,
        message_id="message-7", correlation_id=None,
        identity=service_protocol.WireIdentity(
            role=service_protocol.WireRole.SERVICE,
            principal_ref="principal:market-test", actor_ref="actor:market-test",
        ),
        scope=service_protocol.WireScope(execution_domain_ref="paper:market-test"),
        operation=market_protocol.MARKET_EVENT_OPERATION,
        schema_id=market_protocol.MARKET_EVENT_SCHEMA,
        schema_version=market_protocol.MARKET_EVENT_SCHEMA_VERSION,
        sent_at_utc="2026-11-26T02:00:00Z",
        stream_id=source.stream_id, stream_epoch=source.epoch, sequence=7,
    )
    frame = service_protocol.WireEnvelope(
        header=header,
        payload={"key": key.to_dict(), "data": payload.to_dict()},
    )
    assert type(frame.payload) is MappingProxyType
    assert type(frame.payload["data"]) is MappingProxyType

    reader = runner.ServiceMarketTickReader(SimpleNamespace(key=key), "rb2701", "SHFE")
    reader._source = source
    reader._epoch = source.epoch
    result = reader._project(frame, 7)
    assert result.symbol == "rb2701"
    assert result.price == 123.5
    assert result.source_event.cursor.sequence == 7


def test_close_failure_keeps_original_failure_if_marker_update_raises(tmp_path, monkeypatch):
    retained = []
    monkeypatch.setattr(runner, "_UNCERTAIN_SESSIONS", retained)

    class CloseFailSession:
        def __init__(self, connection):
            self.connection = connection

        def start(self):
            pass

        def close(self):
            raise OSError("synthetic close uncertainty")

    class FakeBroker:
        market_only_order_attempts = 0
        market_only_order_rejections = 0
        market_only_cancel_attempts = 0
        market_only_cancel_rejections = 0
        market_only_account_read_attempts = 0

    class FakeCerebro:
        def run(self, **_kwargs):
            return []

        def getbroker(self):
            return FakeBroker()

    class Guard:
        retained = False

        def __init__(self):
            self.uncertain_calls = 0

        def mark_active(self, **_kwargs):
            pass

        def mark_uncertain(self):
            self.uncertain_calls += 1
            self.retained = True
            raise OSError("synthetic marker rewrite failure")

        def clear_active_marker(self):
            raise AssertionError("close failure cannot take clean path")

        def release_clean(self):
            raise AssertionError("uncertain cleanup cannot release")

    class Receipt:
        def __init__(self):
            self.cleanup = []

        def record_start(self, **_kwargs):
            pass

        def record_zero_write_scope(self, _metrics):
            pass

        def record_cleanup(self, *, status):
            self.cleanup.append(status)

    guard = Guard()
    receipt = Receipt()
    monkeypatch.setattr(runner, "CtpGatewayMarketOnlySession", CloseFailSession)
    monkeypatch.setattr(runner, "_create_cerebro", lambda *_args, **_kwargs: FakeCerebro())
    with pytest.raises(runner.MarketOnlyError, match="MARKET_SESSION_CLOSE_UNCERTAIN"):
        runner.run_market_only(
            "sa_dual_ma_gateway",
            connection=object(),
            run_root=tmp_path / "run-root",
            generation_id="generation-test",
            receipt_sink=receipt,
            identity_guard=guard,
        )
    assert guard.uncertain_calls == 1
    assert retained[-2] is not None
    assert retained[-1] is guard
    assert receipt.cleanup == ["uncertain"]


def test_windows_lease_handles_absent_reparse_error_and_narrows_created_files(
    tmp_path, monkeypatch
):
    narrowed = []
    dacl_checked = []

    class WinSecurityLike:
        @staticmethod
        def ensure_directory_chain(path, create=False):
            if create:
                Path(path).mkdir(parents=True, exist_ok=True)

        @staticmethod
        def inspect_owner(_path):
            return SimpleNamespace(is_current_user=True, others_writable=False)

        @staticmethod
        def is_reparse_point(path):
            if not Path(path).exists():
                raise RuntimeError("NOFOLLOW_UNAVAILABLE")
            return False

        @staticmethod
        def _set_owner_only_acl(path):
            narrowed.append(Path(path).name)

    monkeypatch.setattr(resources, "_windows_supported", lambda: True)
    monkeypatch.setattr(resources, "_windows_security", lambda: WinSecurityLike())
    monkeypatch.setattr(
        resources,
        "_local_resource_module",
        lambda: SimpleNamespace(
            _assert_private_dacl_windows=lambda path: dacl_checked.append(Path(path).name)
        ),
    )

    state_root = tmp_path / "lease-state"
    lease = resources.GlobalMarketIdentityLease(state_root)
    lease.acquire()
    lease.mark_active(generation_id="gen-win-1", run_id="a" * 32)
    lease.clear_active_marker()
    lease.release_clean()

    assert "identity.lock" in narrowed
    assert "cleanup-marker.json" in narrowed
    assert "identity.lock" in dacl_checked
    assert "cleanup-marker.json" in dacl_checked

    receipt_path = tmp_path / "receipt.json"
    sink = resources.MarketOnlyReceiptSink(
        receipt_path,
        generation_id="gen-win-1",
        run_id="a" * 32,
        connection_json_sha256="b" * 64,
    )
    sink.record_cleanup(status="clean")
    assert "receipt.json" in narrowed
    assert "receipt.json" in dacl_checked

