"""Fake-only checks for the unregistered shared simulation/live composition."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from backtrader_runtime.ctp_managed_account_runtime_candidate import (
    CtpManagedActionAuthorityVerifierSlot,
    CtpManagedAccountRuntimeCandidate,
    CtpManagedAccountRuntimeCandidateError,
    _account_family_digest,
)
from backtrader_runtime.ctp_managed_action_authority import (
    CtpManagedActionAuthorityAdapter,
    CtpManagedActionAuthorityError,
)


def test_deferred_authority_slot_rejects_until_one_exact_adapter_is_bound():
    slot = CtpManagedActionAuthorityVerifierSlot()
    command = object()
    with pytest.raises(CtpManagedActionAuthorityError):
        slot.verify_action(command, now_ns=123)

    adapter = object.__new__(CtpManagedActionAuthorityAdapter)
    calls = []
    adapter.verify_action = lambda value, *, now_ns: calls.append((value, now_ns)) or "ok"

    slot.bind(adapter)
    assert slot.bound is True
    assert slot.verify_action(command, now_ns=124) == "ok"
    assert calls == [(command, 124)]

    with pytest.raises(CtpManagedAccountRuntimeCandidateError):
        slot.bind(adapter)


def test_deferred_authority_slot_rejects_duck_verifier_and_never_reopens_after_close():
    slot = CtpManagedActionAuthorityVerifierSlot()
    with pytest.raises(CtpManagedAccountRuntimeCandidateError):
        slot.bind(SimpleNamespace(verify_action=lambda *_args, **_kwargs: object()))

    adapter = object.__new__(CtpManagedActionAuthorityAdapter)
    adapter.verify_action = lambda *_args, **_kwargs: "should not run"
    slot.bind(adapter)
    slot.close()
    assert slot.closed is True
    assert slot.bound is False
    with pytest.raises(CtpManagedActionAuthorityError):
        slot.verify_action(object(), now_ns=125)
    with pytest.raises(CtpManagedAccountRuntimeCandidateError):
        slot.bind(adapter)


@pytest.mark.parametrize(
    "account_ref",
    [
        "broker-user",
        "ctp-account-ref.v1:" + "A" * 64,
        "ctp-account-ref.v1:" + "0" * 63,
        "ctp-account-ref.v1:" + "0" * 64 + ":extra",
    ],
)
def test_account_family_lock_key_requires_canonical_opaque_ctp_account_ref(account_ref):
    with pytest.raises(CtpManagedAccountRuntimeCandidateError):
        _account_family_digest(SimpleNamespace(account_ref=account_ref))


def test_account_family_lock_key_is_mode_independent_and_never_uses_account_key():
    account_ref = "ctp-account-ref.v1:" + "a" * 64
    simulation = SimpleNamespace(account_ref=account_ref, account_key="account:" + "1" * 64)
    live = SimpleNamespace(account_ref=account_ref, account_key="account:" + "2" * 64)
    assert _account_family_digest(simulation) == "a" * 64
    assert _account_family_digest(live) == "a" * 64


def _account_runtime_resolver(
    tmp_path, *, mode, config_path=None, registry=None, registration=None
):
    import json
    from decimal import Decimal

    from bt_api_execution.contracts import ExecutionScope

    from backtrader_runtime.ctp_managed_action_scope_resolver import (
        SealedCtpManagedActionScopeResolverV1,
        ctp_managed_account_ref_v1,
    )
    from backtrader_runtime.ctp_private_config_setup import (
        _create_private_file,
        _protect_target_directory,
        _verified_target_directory,
    )
    from backtrader_runtime.ctp_production_execution_admission import (
        CtpProductionExecutionRegistration,
    )
    from backtrader_runtime.ctp_simnow_managed_operator import (
        CtpSimNowManagedExecutionPolicy,
    )
    from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES
    from backtrader_runtime.registry import RegisteredRuntime, RuntimeProfile, RuntimeRegistry

    runtime_id = "synthetic.ctp.account-runtime"
    strategy_id = "synthetic.ctp.account-runtime.strategy"
    front_pair = ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001")
    if config_path is None:
        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        config_path = runtime_dir / "config.yaml"
    else:
        runtime_dir = config_path.parent

    mode_name = "simulation" if mode == "simulation" else "live"
    preset = "sandbox" if mode == "simulation" else "managed_live_direct"
    document = {
        "config_schema_version": 4,
        "strategy": {"id": strategy_id},
        "runtime": {"mode": mode_name, "preset": preset},
        "parameters": {},
        "secrets_ref": "config_yaml",
        "ctp": {
            "front_pairs": [
                {"md_front": front_pair[0], "td_front": front_pair[1]},
                {"md_front": "tcp://127.0.0.1:11002", "td_front": "tcp://127.0.0.1:12002"},
            ],
            "instrument_id": "rb2701",
            "exchange_id": "SHFE",
            "hedge_flag": "1",
            "broker_id": "offline-broker",
            "user_id": "offline-user",
            "password": "offline-only",
            "app_id": "offline-only",
            "auth_code": "offline-only",
        },
    }
    if not config_path.exists():
        content = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with _verified_target_directory(runtime_dir) as descriptor:
            _protect_target_directory(descriptor)
            created = _create_private_file(descriptor, config_path, content)
        if created.retained_fd is not None:
            os.close(created.retained_fd)
    else:
        content = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with config_path.open("r+b") as stream:
            stream.seek(0)
            stream.write(content)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(config_path, 0o600)

    if registry is None:
        profiles = (
            RuntimeProfile(
                mode="simulation",
                preset="sandbox",
                allowed_parameter_keys=(),
                allowed_secrets_refs=("config_yaml",),
                available_capabilities=("execution", "risk", "monitor"),
                approval_receipt_digest="a" * 64,
                runner_module=None,
                runner_entrypoint="run_runtime",
                capability_modules=(),
                offline_managed_execution=False,
                sandbox_write_policy="receipt_required",
            ),
            RuntimeProfile(
                mode="live",
                preset="managed_live_direct",
                allowed_parameter_keys=(),
                allowed_secrets_refs=("config_yaml",),
                available_capabilities=MANAGED_WRITE_CAPABILITIES,
                approval_receipt_digest="b" * 64,
                runner_module=None,
                runner_entrypoint="run_runtime",
                capability_modules=(),
                offline_managed_execution=False,
                sandbox_write_policy="deny",
            ),
        )
        registration = RegisteredRuntime(
            runtime_dir=runtime_dir,
            strategy_id=strategy_id,
            runtime_id=runtime_id,
            allowed_presets=(),
            profiles=profiles,
        )
        registry = RuntimeRegistry((registration,), registry_id="synthetic.account.runtime")
    else:
        strategy_id = registration.strategy_id

    if mode == "simulation":
        admission = CtpSimNowManagedExecutionPolicy(
            runtime_registration=registration,
            allowed_sides=("BUY", "SELL"),
            quantity_step=1,
            max_quantity=2,
            max_gross_position=2,
            min_price=Decimal("100"),
            max_price=Decimal("200"),
            price_tick=Decimal("1"),
            approval_key_id="offline-test-key",
        )
        environment = "simnow"
    else:
        admission = CtpProductionExecutionRegistration(
            runtime_registration=registration,
            environment="production",
            account_binding_sha256=None,
            md_front=None,
            td_front=None,
            instrument_id=None,
            exchange_id=None,
            hedge_flag=None,
            approval_receipt_id="ctp-production:receipt.synthetic",
            approval_receipt_sha256="b" * 64,
            artifact_id="ctp-production:artifact.synthetic",
            artifact_sha256="d" * 64,
            allowed_sides=("BUY", "SELL"),
            allowed_offsets=("OPEN",),
            quantity_step=1,
            max_order_quantity=2,
            max_gross_position=2,
            min_price=Decimal("100"),
            max_price=Decimal("200"),
            price_tick=Decimal("1"),
            max_order_notional=Decimal("1000"),
            scope_binding_mode="sealed_config",
        )
        environment = "production"
    scope = ExecutionScope(
        provider="ctp",
        environment=environment,
        account_ref=ctp_managed_account_ref_v1("offline-broker", "offline-user"),
        strategy_id=strategy_id,
        trading_day="20260926",
    )
    resolver = SealedCtpManagedActionScopeResolverV1(
        registry, registration, admission, front_pair, scope
    )
    return resolver, scope, config_path, registry, registration


def _public_candidate(resolver, scope):
    from backtrader_runtime.ctp_managed_action_authority import (
        CtpPinnedEd25519ActionKey,
        PinnedEd25519CtpActionPermitVerifier,
    )

    permit_source, signature_verifier, revocation_source, fence_source, trusted_clock = (
        _offline_authority_ports(CtpPinnedEd25519ActionKey, PinnedEd25519CtpActionPermitVerifier)
    )
    inert = object()
    return CtpManagedAccountRuntimeCandidate.create_for_sealed_scope(
        execution_scope=scope,
        scope_resolver=resolver,
        permit_source=permit_source,
        signature_verifier=signature_verifier,
        revocation_source=revocation_source,
        fence_source=fence_source,
        trusted_clock=trusted_clock,
        client_factory=inert,
        lifecycle_supervisor=inert,
        native_field_factory=inert,
        callback_verifier=inert,
        trade_fact_verifier=inert,
    )


def _offline_authority_ports(key_type=None, verifier_type=None):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if key_type is None or verifier_type is None:
        from backtrader_runtime.ctp_managed_action_authority import (
            CtpPinnedEd25519ActionKey,
            PinnedEd25519CtpActionPermitVerifier,
        )

        key_type = CtpPinnedEd25519ActionKey
        verifier_type = PinnedEd25519CtpActionPermitVerifier
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    key = key_type(
        issuer="offline-test-issuer",
        key_id="offline-test-key",
        audience="offline-test-runtime",
        public_key=public_key,
        valid_from_ns=1,
        valid_until_ns=9_999_999_999_999_999_999,
    )

    class PermitSource:
        def read_permit(self, _permit_id):
            return None

    class RevocationSource:
        def read_revocation(self, _permit):
            return None

    class FenceSource:
        def read_active_fence(self, _scope):
            return None

    class TrustedClock:
        def now_ns(self):
            return 1

    return PermitSource(), verifier_type((key,)), RevocationSource(), FenceSource(), TrustedClock()


def test_public_factory_uses_one_legacy_account_path_for_both_modes(tmp_path, monkeypatch):
    from backtrader_runtime import ctp_simulation_execution

    pytest.importorskip("bt_api_execution.store")
    state_root = tmp_path / "account-state"
    state_root.mkdir()
    monkeypatch.setattr(ctp_simulation_execution, "_prepare_state_root", lambda: state_root)
    simulation_resolver, simulation_scope, config_path, registry, registration = (
        _account_runtime_resolver(tmp_path, mode="simulation")
    )
    simulation = _public_candidate(simulation_resolver, simulation_scope)
    simulation._acquire_legacy_flow_and_open_store()
    expected_path = state_root / "journals" / (simulation._legacy_account_fingerprint + ".sqlite3")
    assert simulation._store_path == expected_path
    owner = simulation._store.acquire_ctp_account_family_owner(simulation_scope)
    simulation._validate_family_owner(owner)
    simulation._validate_store_identity(
        simulation._store.read_ctp_account_store_identity(simulation_scope),
        expected_path=expected_path,
        expected_owner=owner,
    )
    simulation._store.close()
    simulation._flow_lease.release()

    before = expected_path.read_bytes()
    live_resolver, live_scope, _, _, _ = _account_runtime_resolver(
        tmp_path,
        mode="live",
        config_path=config_path,
        registry=registry,
        registration=registration,
    )
    live = _public_candidate(live_resolver, live_scope)
    with pytest.raises(CtpManagedAccountRuntimeCandidateError):
        live._acquire_legacy_flow_and_open_store()
    assert live._store_path == expected_path
    assert expected_path.read_bytes() == before
    assert simulation_scope.account_ref == live_scope.account_ref
    assert simulation_scope.account_key != live_scope.account_key
    if live._flow_lease is not None:
        live._flow_lease.release()


def test_public_factory_fake_login_and_cross_mode_restart_share_one_v20_store(
    tmp_path, monkeypatch
):
    from backtrader_runtime import ctp_simulation_execution
    from backtrader_runtime.ctp_i9_account_session_candidate import (
        CtpI9NativeLifecycleSupervisor,
    )

    pytest.importorskip("bt_api_execution.store")
    pytest.importorskip("bt_api_ctp.ctp.client")
    state_root = tmp_path / "account-state"
    state_root.mkdir()
    monkeypatch.setattr(ctp_simulation_execution, "_prepare_state_root", lambda: state_root)
    simulation_resolver, simulation_scope, config_path, registry, registration = (
        _account_runtime_resolver(tmp_path, mode="simulation")
    )
    client_module = __import__("bt_api_ctp.ctp.client", fromlist=["TraderClient"])

    class FakeApi:
        def __init__(self):
            self.spi = None
            self.join_started = False
            self.calls = []

        def RegisterSpi(self, spi):
            self.spi = spi

        def SubscribePrivateTopic(self, _topic):
            return None

        def SubscribePublicTopic(self, _topic):
            return None

        def RegisterFront(self, _front):
            return None

        def Init(self):
            self.spi.OnFrontConnected()

        def Join(self):
            self.join_started = True
            return 0

        def Release(self):
            self.calls.append("Release")

        def ReqAuthenticate(self, field, request_id):
            self.calls.append(("ReqAuthenticate", request_id))
            self.spi.OnRspAuthenticate(
                SimpleNamespace(BrokerID=field.BrokerID, UserID=field.UserID),
                SimpleNamespace(ErrorID=0, ErrorMsg=""),
                request_id,
                True,
            )
            return 0

        def ReqUserLogin(self, field, request_id):
            self.calls.append(("ReqUserLogin", request_id))
            self.spi.OnRspUserLogin(
                SimpleNamespace(
                    BrokerID=field.BrokerID,
                    UserID=field.UserID,
                    TradingDay="20260926",
                    FrontID=7,
                    SessionID=19,
                    MaxOrderRef="17",
                ),
                SimpleNamespace(ErrorID=0, ErrorMsg=""),
                request_id,
                True,
            )
            return 0

    class FakeApiFactory:
        instances = []

        @classmethod
        def CreateFtdcTraderApi(cls, _flow_path):
            api = FakeApi()
            cls.instances.append(api)
            return api

    class FakeSupervisor(CtpI9NativeLifecycleSupervisor):
        def start_client(self, client):
            client.start()

        def stop_client(self, client):
            client.stop()

    monkeypatch.setattr(client_module, "_check_native_module", lambda: None)
    monkeypatch.setattr(client_module, "_flow_dir", lambda _name: "fake-account-flow")
    monkeypatch.setattr(client_module, "_register_ctp_native_api", lambda _api: None)
    monkeypatch.setattr(client_module, "CThostFtdcTraderApi", FakeApiFactory)
    FakeApiFactory.instances = []
    candidate_box = []

    def client_factory():
        candidate = candidate_box[0]
        owner_rows = candidate._store._connection.execute(
            "SELECT owner_state FROM ctp_dispatch_callback_session_owners WHERE account_key=?",
            (simulation_scope.account_key,),
        ).fetchall()
        assert tuple(row[0] for row in owner_rows) == ("PREPARED",)
        return client_module.TraderClient(
            "tcp://127.0.0.1:1", "offline-broker", "offline-user", "offline-password"
        )

    permit_source, signature_verifier, revocation_source, fence_source, trusted_clock = (
        _offline_authority_ports()
    )
    simulation = CtpManagedAccountRuntimeCandidate.create_for_sealed_scope(
        execution_scope=simulation_scope,
        scope_resolver=simulation_resolver,
        permit_source=permit_source,
        signature_verifier=signature_verifier,
        revocation_source=revocation_source,
        fence_source=fence_source,
        trusted_clock=trusted_clock,
        client_factory=client_factory,
        lifecycle_supervisor=FakeSupervisor(),
        native_field_factory=lambda _operation, _payload: object(),
        callback_verifier=object(),
        trade_fact_verifier=object(),
    )
    candidate_box.append(simulation)
    simulation.start()
    path = simulation._store_path
    expected_path = state_root / "journals" / (simulation._legacy_account_fingerprint + ".sqlite3")
    assert path == expected_path
    assert simulation.authority_verifier_slot.bound is True
    assert FakeApiFactory.instances[0].calls == [("ReqAuthenticate", 1), ("ReqUserLogin", 2)]
    assert not any("ReqOrder" in str(call) for call in FakeApiFactory.instances[0].calls)
    simulation.close()
    assert simulation._closed is True

    before = path.read_bytes()
    live_resolver, live_scope, _, _, _ = _account_runtime_resolver(
        tmp_path,
        mode="live",
        config_path=config_path,
        registry=registry,
        registration=registration,
    )
    live = CtpManagedAccountRuntimeCandidate.create_for_sealed_scope(
        execution_scope=live_scope,
        scope_resolver=live_resolver,
        permit_source=permit_source,
        signature_verifier=signature_verifier,
        revocation_source=revocation_source,
        fence_source=fence_source,
        trusted_clock=trusted_clock,
        client_factory=client_factory,
        lifecycle_supervisor=FakeSupervisor(),
        native_field_factory=lambda _operation, _payload: object(),
        callback_verifier=object(),
        trade_fact_verifier=object(),
    )
    candidate_box[0] = live
    with pytest.raises(CtpManagedAccountRuntimeCandidateError):
        live.start()
    assert live._store_path == path
    assert path.read_bytes() == before
    assert len(FakeApiFactory.instances) == 1
    assert simulation_scope.account_ref == live_scope.account_ref
    assert simulation_scope.account_key != live_scope.account_key


def test_public_factory_rejects_existing_legacy_journal_without_rewriting_it(tmp_path, monkeypatch):
    import sqlite3

    from backtrader_runtime import ctp_simulation_execution

    pytest.importorskip("bt_api_execution.store")
    state_root = tmp_path / "account-state"
    state_root.mkdir()
    monkeypatch.setattr(ctp_simulation_execution, "_prepare_state_root", lambda: state_root)
    resolver, scope, _config_path, _registry, _registration = _account_runtime_resolver(
        tmp_path, mode="simulation"
    )
    candidate = _public_candidate(resolver, scope)
    from backtrader_runtime.ctp_managed_action_scope_resolver import (
        _simnow_legacy_admission_account_digest,
    )

    private = resolver._fresh_effective().config.ctp
    legacy_digest = _simnow_legacy_admission_account_digest(private)
    journal_dir = state_root / "journals"
    journal_dir.mkdir()
    legacy_path = journal_dir / (legacy_digest + ".sqlite3")
    connection = sqlite3.connect(str(legacy_path))
    connection.execute(
        """CREATE TABLE ctp_sim_orders (
            client_order_id TEXT PRIMARY KEY,
            approval_id TEXT NOT NULL UNIQUE,
            request_digest TEXT NOT NULL,
            request_json TEXT NOT NULL,
            state TEXT NOT NULL,
            order_ref TEXT,
            order_sys_id TEXT,
            front_id INTEGER,
            session_id INTEGER,
            status TEXT,
            traded_quantity INTEGER NOT NULL DEFAULT 0,
            position_digest TEXT,
            updated_at REAL NOT NULL
        )"""
    )
    connection.commit()
    connection.close()
    before = legacy_path.read_bytes()

    with pytest.raises(CtpManagedAccountRuntimeCandidateError):
        candidate._acquire_legacy_flow_and_open_store()
    assert legacy_path.read_bytes() == before
    readonly = sqlite3.connect(legacy_path.as_uri() + "?mode=ro", uri=True)
    try:
        assert readonly.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        assert readonly.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ctp_sim_orders'"
        ).fetchone() == ("ctp_sim_orders",)
        assert (
            readonly.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='execution_meta'"
            ).fetchone()
            is None
        )
    finally:
        readonly.close()
    if candidate._flow_lease is not None:
        candidate._flow_lease.release()
