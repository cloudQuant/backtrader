"""Offline contract tests for the bounded CTP SimNow execution boundary."""

from __future__ import annotations

import hashlib
import hmac
import multiprocessing
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

import backtrader_runtime.ctp_simulation_execution as execution
import backtrader_runtime.config as runtime_config_module
from backtrader_runtime import RegisteredRuntime, RuntimeRegistry, load_runtime_config
from backtrader_runtime.ctp_simulation_execution import (
    CtpAccountFlowLease,
    CtpSimulationExecutionError,
    CtpSimulationExecutionRegistration,
    CtpSimulationCancelRequestSnapshot,
    CtpSimulationDispatchReceipt,
    CtpSimulationOrderSnapshot,
    CtpSimulationPositionSnapshot,
    CtpSimulationQueryResult,
    CtpSimulationExecutionSession,
    CtpSimulationSessionIdentity,
    CtpSimulationTradeSnapshot,
    CtpSimulationWriteApproval,
    CtpSimulationWriteRequest,
    HmacCtpSimulationApprovalVerifier,
    open_ctp_simulation_execution,
    require_ctp_simulation_execution_admission,
)
from backtrader_runtime.registry import RuntimeProfile, resolve_runtime_config


NOW = 1_800_000_000.0
SECRET_REF = "os_secret_store:iteration41.ctp.simnow.execution"
ACCOUNT = "b" * 64
RECEIPT = "a" * 64
KEY_ID = "test-key-1"
KEY = b"test-only-approval-key-material-32bytes-long"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(execution.time, "time", lambda: NOW)
    monotonic = [1_000.0]
    monkeypatch.setattr(execution.time, "monotonic", lambda: monotonic[0])
    monkeypatch.setattr(execution, "_default_state_root", lambda: tmp_path / "execution-state")


@pytest.fixture
def allow_synthetic_private_config_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    # Temporary fixtures do not model deployment ACLs; private values remain
    # synthetic and the runtime loader/seal checks still run.
    monkeypatch.setattr(
        runtime_config_module, "_require_private_config_security", lambda *args, **kwargs: None
    )


def _runtime(tmp_path: Path) -> tuple[Any, RuntimeRegistry, CtpSimulationExecutionRegistration]:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        """config_schema_version: 4
strategy:
  id: example.ctp.simnow.execution
runtime:
  mode: simulation
  preset: sandbox
parameters: {{}}
secrets_ref: {secret_ref}
""".format(secret_ref=SECRET_REF),
        encoding="utf-8",
    )
    registered = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="example.ctp.simnow.execution",
        strategy_id="example.ctp.simnow.execution",
        allowed_presets=("sandbox",),
        allowed_parameter_keys=(),
        allowed_secrets_refs=(SECRET_REF,),
        available_capabilities=("execution", "risk", "monitor"),
        sandbox_write_policy="receipt_required",
        approval_receipt_digest=RECEIPT,
    )
    registry = RuntimeRegistry((registered,), registry_id="test-simnow-execution")
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )
    registration = CtpSimulationExecutionRegistration(
        runtime_registration=registered,
        environment="simnow",
        sdk_profile="config_front_pair",
        td_front="tcp://trade.simnow.test:10001",
        md_front="tcp://market.simnow.test:10002",
        account_fingerprint_sha256=ACCOUNT,
        allowed_secrets_ref=SECRET_REF,
        instrument_id="rb2701",
        exchange_id="SHFE",
        hedge_flag="1",
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=3,
        max_gross_position=3,
        min_price=Decimal("100.0"),
        max_price=Decimal("200.0"),
        price_tick=Decimal("0.5"),
        approval_key_id=KEY_ID,
        approval_ttl_seconds=20.0,
    )
    return effective, registry, registration


def _runtime_with_private_ctp(
    tmp_path: Path, *, user_id: str = "private-offline-user", block_name: str = "ctp_simnow"
) -> tuple[Any, RuntimeRegistry, CtpSimulationExecutionRegistration]:
    runtime_dir = tmp_path / "private-runtime"
    runtime_dir.mkdir(exist_ok=True)

    def write_config(account_user: str) -> None:
        (runtime_dir / "config.yaml").write_text(
            """config_schema_version: 4
strategy:
  id: example.ctp.simnow.execution
runtime:
  mode: simulation
  preset: sandbox
parameters: {{}}
secrets_ref: config_yaml
{block_name}:
  md_front: {md_front}
  td_front: {td_front}
  broker_id: "9999"
  user_id: "{user_id}"
  password: "fixture-only-unused-value"
  auth_code: "fixture-only-unused-value"
  app_id: "fixture-only-unused-value"
  instrument_id: rb2701
  exchange_id: SHFE
  hedge_flag: "1"
""".format(
                block_name=block_name,
                md_front="tcp://market.simnow.test:10002",
                td_front="tcp://trade.simnow.test:10001",
                user_id=account_user,
            ),
            encoding="utf-8",
        )

    write_config(user_id)
    registered = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="example.ctp.simnow.execution",
        strategy_id="example.ctp.simnow.execution",
        allowed_presets=("sandbox",),
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=("execution", "risk", "monitor"),
        sandbox_write_policy="receipt_required",
        approval_receipt_digest=RECEIPT,
    )
    registry = RuntimeRegistry((registered,), registry_id="test-simnow-private-execution")
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )
    fingerprint = hashlib.sha256("9999:{0}".format(user_id).encode("utf-8")).hexdigest()[:16]
    account_digest = hashlib.sha256(("acct_" + fingerprint).encode("ascii")).hexdigest()
    registration = CtpSimulationExecutionRegistration(
        runtime_registration=registered,
        environment="simnow",
        sdk_profile="config_front_pair",
        td_front="tcp://trade.simnow.test:10001",
        md_front="tcp://market.simnow.test:10002",
        account_fingerprint_sha256=account_digest,
        allowed_secrets_ref="config_yaml",
        instrument_id="rb2701",
        exchange_id="SHFE",
        hedge_flag="1",
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=3,
        max_gross_position=3,
        min_price=Decimal("100.0"),
        max_price=Decimal("200.0"),
        price_tick=Decimal("0.5"),
        approval_key_id=KEY_ID,
        front_pair_set_sha256=execution._front_pair_set_digest(
            (("tcp://market.simnow.test:10002", "tcp://trade.simnow.test:10001"),)
        ),
        config_digest=effective.config.config_digest,
        effective_digest=effective.effective_digest,
    )
    return effective, registry, registration


def _runtime_with_profile_ctp(
    tmp_path: Path, *, sandbox_write_policy: str = "receipt_required", user_id: str = "profile-user"
) -> tuple[Any, RuntimeRegistry, CtpSimulationExecutionRegistration, str]:
    runtime_dir = tmp_path / "profile-runtime"
    runtime_dir.mkdir(exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        """config_schema_version: 4
strategy:
  id: example.ctp.simnow.execution
runtime:
  mode: simulation
  preset: sandbox
parameters: {{}}
secrets_ref: config_yaml
ctp:
  md_front: tcp://market.simnow.test:10002
  td_front: tcp://trade.simnow.test:10001
  broker_id: "9999"
  user_id: "{user_id}"
  password: "fixture-only-unused-value"
  auth_code: "fixture-only-unused-value"
  app_id: "fixture-only-unused-value"
  instrument_id: rb2701
  exchange_id: SHFE
  hedge_flag: "1"
""".format(user_id=user_id),
        encoding="utf-8",
    )
    writable = sandbox_write_policy == "receipt_required"
    profile = RuntimeProfile(
        mode="simulation",
        preset="sandbox",
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=("execution", "risk", "monitor") if writable else (),
        approval_receipt_digest=RECEIPT if writable else None,
        runner_module=None,
        runner_entrypoint="run_runtime",
        capability_modules=(),
        offline_managed_execution=False,
        sandbox_write_policy=sandbox_write_policy,
    )
    registered = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="example.ctp.simnow.execution",
        strategy_id="example.ctp.simnow.execution",
        allowed_presets=(),
        profiles=(profile,),
    )
    registry = RuntimeRegistry((registered,), registry_id="test-simnow-profile-execution")
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )
    fingerprint = hashlib.sha256("9999:{0}".format(user_id).encode("utf-8")).hexdigest()[:16]
    account_digest = hashlib.sha256(("acct_" + fingerprint).encode("ascii")).hexdigest()
    registration = CtpSimulationExecutionRegistration(
        runtime_registration=registered,
        environment="simnow",
        sdk_profile="config_front_pair",
        td_front="tcp://trade.simnow.test:10001",
        md_front="tcp://market.simnow.test:10002",
        account_fingerprint_sha256=account_digest,
        allowed_secrets_ref="config_yaml",
        instrument_id="rb2701",
        exchange_id="SHFE",
        hedge_flag="1",
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=3,
        max_gross_position=3,
        min_price=Decimal("100.0"),
        max_price=Decimal("200.0"),
        price_tick=Decimal("0.5"),
        approval_key_id=KEY_ID,
        front_pair_set_sha256=execution._front_pair_set_digest(
            (("tcp://market.simnow.test:10002", "tcp://trade.simnow.test:10001"),)
        ),
        config_digest=effective.config.config_digest,
        effective_digest=effective.effective_digest,
        profile_digest=profile.digest if writable else None,
        profile_approval_receipt_digest=profile.approval_receipt_digest if writable else None,
    )
    return effective, registry, registration, account_digest


def _identity(account_fingerprint_sha256: str = ACCOUNT) -> CtpSimulationSessionIdentity:
    return CtpSimulationSessionIdentity(
        environment="simnow",
        sdk_profile="config_front_pair",
        td_front="tcp://trade.simnow.test:10001",
        md_front="tcp://market.simnow.test:10002",
        account_fingerprint_sha256=account_fingerprint_sha256,
        trading_day="20260923",
        connection_generation=9,
        production=False,
        native_gate_armed=True,
    )


class _FakeNativePort:
    """Fake only the native boundary; keep the real journal, lock and checks."""

    def __init__(
        self, lease: CtpAccountFlowLease, account_fingerprint_sha256: str = ACCOUNT
    ) -> None:
        lease.assert_held(account_fingerprint_sha256)
        self.identity = _identity(account_fingerprint_sha256)
        self.identity_calls = 0
        self.identity_change_on_call: Optional[int] = None
        self.insert_calls: list[CtpSimulationWriteRequest] = []
        self.cancel_calls: list[tuple[CtpSimulationOrderSnapshot, str]] = []
        self.order: Optional[CtpSimulationOrderSnapshot] = None
        self.order_records_override: Optional[tuple[CtpSimulationOrderSnapshot, ...]] = None
        self.open_orders: tuple[CtpSimulationOrderSnapshot, ...] = ()
        self.cancel_results: dict[str, CtpSimulationCancelRequestSnapshot] = {}
        self.cancel_history_missing = False
        self.cancel_history_identity: Optional[CtpSimulationSessionIdentity] = None
        self.trades: tuple[CtpSimulationTradeSnapshot, ...] = ()
        self.positions: tuple[CtpSimulationPositionSnapshot, ...] = ()
        self.complete = True
        self.raise_on_insert = False
        self.raise_on_authorize = False
        self.authorize_calls: list[
            tuple[CtpSimulationWriteRequest, CtpSimulationWriteApproval, Optional[str]]
        ] = []
        self.raise_on_close = False
        self.close_calls = 0
        self.submit_code = 0
        self.cancel_submit_code = 0
        self.dispatch_receipt_mutator = None
        self.request_id = 0

    def _dispatch_receipt(
        self,
        request: CtpSimulationWriteRequest,
        *,
        action_id: Optional[str] = None,
        code: int,
    ) -> CtpSimulationDispatchReceipt:
        self.request_id += 1
        outcome = "QUEUED" if code == 0 else ("REJECTED" if code < 0 else "UNKNOWN")
        receipt = CtpSimulationDispatchReceipt(
            operation=request.action,
            outcome=outcome,
            request_digest=request.digest,
            client_order_id=request.client_order_id,
            managed_intent_id="intent-" + request.client_order_id,
            action_id=action_id,
            request_id=self.request_id,
            submit_code=code,
            identity=self.identity,
            local_rejection_verified=code < 0,
        )
        if self.dispatch_receipt_mutator is not None:
            receipt = self.dispatch_receipt_mutator(receipt)
        return receipt

    def get_execution_identity(self) -> CtpSimulationSessionIdentity:
        self.identity_calls += 1
        if self.identity_calls == self.identity_change_on_call:
            self.identity = replace(
                self.identity, connection_generation=self.identity.connection_generation + 1
            )
        return self.identity

    def submit_order_insert(
        self, request: CtpSimulationWriteRequest
    ) -> CtpSimulationDispatchReceipt:
        self.insert_calls.append(request)
        if self.raise_on_insert:
            raise TimeoutError("ambiguous native dispatch")
        return self._dispatch_receipt(request, code=self.submit_code)

    def authorize_write(
        self,
        request: CtpSimulationWriteRequest,
        approval: CtpSimulationWriteApproval,
        *,
        action_id: Optional[str] = None,
    ) -> None:
        self.authorize_calls.append((request, approval, action_id))
        if self.raise_on_authorize:
            raise RuntimeError("fake final write authorization rejected")

    def submit_order_action(
        self, snapshot: CtpSimulationOrderSnapshot, action_id: str
    ) -> CtpSimulationDispatchReceipt:
        self.cancel_calls.append((snapshot, action_id))
        request = CtpSimulationWriteRequest(
            action="CANCEL",
            client_order_id=snapshot.client_order_id,
            instrument_id=snapshot.instrument_id,
            exchange_id=snapshot.exchange_id,
            side=snapshot.side,
            quantity=snapshot.quantity,
            limit_price=snapshot.limit_price,
            offset="OPEN",
            hedge_flag="1",
            target_order_sys_id=snapshot.order_sys_id,
            target_order_ref=snapshot.order_ref,
            target_front_id=snapshot.front_id,
            target_session_id=snapshot.session_id,
        )
        return self._dispatch_receipt(
            request, action_id=action_id, code=self.cancel_submit_code
        )

    def query_orders(self, client_order_id: str) -> CtpSimulationQueryResult:
        records = self.order_records_override
        if records is None:
            records = (self.order,) if self.order is not None else ()
        return CtpSimulationQueryResult(self.complete, self.identity, records)

    def query_trades(self, client_order_id: str) -> CtpSimulationQueryResult:
        return CtpSimulationQueryResult(self.complete, self.identity, self.trades)

    def query_positions(self, instrument_id: str, exchange_id: str) -> CtpSimulationQueryResult:
        return CtpSimulationQueryResult(self.complete, self.identity, self.positions)

    def query_account_open_orders(self) -> CtpSimulationQueryResult:
        return CtpSimulationQueryResult(self.complete, self.identity, self.open_orders)

    def query_cancel_requests(self, action_ids: tuple[str, ...]) -> CtpSimulationQueryResult:
        if self.cancel_history_missing:
            return CtpSimulationQueryResult(
                False, self.cancel_history_identity or self.identity, ()
            )
        records = tuple(
            self.cancel_results[action_id]
            for action_id in action_ids
            if action_id in self.cancel_results
        )
        return CtpSimulationQueryResult(self.complete, self.identity, records)

    def close(self) -> None:
        self.close_calls += 1
        if self.raise_on_close:
            raise RuntimeError("fake close failure")


class _FakeWriterFence:
    environment = "simnow"
    account_fingerprint_sha256 = ACCOUNT
    fence_id = "test-account-writer-fence"

    def __init__(self, account_fingerprint_sha256: str = ACCOUNT) -> None:
        self.account_fingerprint_sha256 = account_fingerprint_sha256
        self.active = True
        self.assertions = 0

    def assert_active(self) -> None:
        self.assertions += 1
        if not self.active:
            raise RuntimeError("fake external account fence expired")


class _FakeQueryEvidenceVerifier:
    """Only validates the local fake-port contract; it is not native evidence."""

    def __init__(self) -> None:
        self.accept = True
        self.query_kinds: list[str] = []

    def verify(
        self,
        query_kind: str,
        result: CtpSimulationQueryResult,
        *,
        expected_identity: CtpSimulationSessionIdentity,
        registration_digest: str,
    ) -> bool:
        self.query_kinds.append(query_kind)
        return (
            self.accept
            and result.complete is True
            and result.identity == expected_identity
            and len(registration_digest) == 64
        )


def _open(
    tmp_path: Path,
    *,
    port_factory: Any = None,
    registration: Optional[CtpSimulationExecutionRegistration] = None,
    query_evidence_verifier: Optional[_FakeQueryEvidenceVerifier] = None,
    writer_fence: Optional[_FakeWriterFence] = None,
):
    effective, registry, default_registration = _runtime(tmp_path)
    registration = registration or default_registration
    calls: list[_FakeNativePort] = []

    def factory(route: CtpSimulationExecutionRegistration, lease: CtpAccountFlowLease):
        assert route is registration
        port = port_factory(lease) if port_factory else _FakeNativePort(lease)
        calls.append(port)
        return port

    session = open_ctp_simulation_execution(
        effective=effective,
        registry=registry,
        registration=registration,
        native_session_factory=factory,
        approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
        query_evidence_verifier=query_evidence_verifier or _FakeQueryEvidenceVerifier(),
        writer_fence=writer_fence or _FakeWriterFence(),
    )
    return session, calls, effective, registry, registration


def _open_profile(tmp_path: Path):
    effective, registry, registration, account_digest = _runtime_with_profile_ctp(tmp_path)
    calls: list[_FakeNativePort] = []

    def factory(route: CtpSimulationExecutionRegistration, lease: CtpAccountFlowLease):
        assert route is registration
        port = _FakeNativePort(lease, account_digest)
        calls.append(port)
        return port

    session = open_ctp_simulation_execution(
        effective=effective,
        registry=registry,
        registration=registration,
        native_session_factory=factory,
        approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
        query_evidence_verifier=_FakeQueryEvidenceVerifier(),
        writer_fence=_FakeWriterFence(account_digest),
    )
    return session, calls, effective, registry, registration


def _request(
    *,
    action: str = "SUBMIT",
    client_order_id: str = "order-001",
    target: Optional[str] = None,
    quantity: int = 2,
) -> CtpSimulationWriteRequest:
    return CtpSimulationWriteRequest(
        action=action,
        client_order_id=client_order_id,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=quantity,
        limit_price=Decimal("125.5"),
        target_order_sys_id=target,
        target_order_ref="20260923-1" if action == "CANCEL" else None,
        target_front_id=3 if action == "CANCEL" else None,
        target_session_id=9 if action == "CANCEL" else None,
    )


def _approval(
    registration: CtpSimulationExecutionRegistration,
    request: CtpSimulationWriteRequest,
    *,
    approval_id: str = "approval-001",
    issued_at: float = NOW,
    expires_at: float = NOW + 10.0,
    signature_key: bytes = KEY,
) -> CtpSimulationWriteApproval:
    unsigned = CtpSimulationWriteApproval(
        approval_id=approval_id,
        key_id=KEY_ID,
        registration_digest=registration.digest,
        receipt_digest=(
            registration.profile_approval_receipt_digest
            if registration.profile_digest is not None
            else RECEIPT
        ),
        account_fingerprint_sha256=registration.account_fingerprint_sha256,
        environment=registration.environment,
        td_front=registration.td_front,
        md_front=registration.md_front,
        request_digest=request.digest,
        issued_at=issued_at,
        expires_at=expires_at,
        signature_hex="0" * 64,
    )
    signature = hmac.new(signature_key, unsigned.signed_payload(), hashlib.sha256).hexdigest()
    return replace(unsigned, signature_hex=signature)


def _accepted_order(status: str, traded: int = 0) -> CtpSimulationOrderSnapshot:
    return CtpSimulationOrderSnapshot(
        client_order_id="order-001",
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=2,
        limit_price=Decimal("125.5"),
        traded_quantity=traded,
        status=status,
        order_ref="20260923-1",
        order_sys_id="sys-order-1",
        front_id=3,
        session_id=9,
    )


def _cancel_result(
    action_id: str, status: str, order: Optional[CtpSimulationOrderSnapshot] = None
) -> CtpSimulationCancelRequestSnapshot:
    target = order or _accepted_order("OPEN")
    return CtpSimulationCancelRequestSnapshot(
        action_id=action_id,
        client_order_id=target.client_order_id,
        target_order_sys_id=target.order_sys_id,
        target_order_ref=target.order_ref,
        target_front_id=target.front_id,
        target_session_id=target.session_id,
        status=status,
    )


def _pending_cancel_after_restart(
    tmp_path: Path, query_verifier: Optional[_FakeQueryEvidenceVerifier] = None
):
    session, calls, _, _, registration = _open(tmp_path, query_evidence_verifier=query_verifier)
    port = calls[0]
    submit = _request()
    session.submit_order(
        client_order_id=submit.client_order_id,
        instrument_id=submit.instrument_id,
        exchange_id=submit.exchange_id,
        side=submit.side,
        quantity=submit.quantity,
        limit_price=submit.limit_price,
        approval=_approval(registration, submit),
    )
    port.order = _accepted_order("OPEN")
    session.reconcile("order-001")
    cancel = _request(action="CANCEL", target="sys-order-1")
    session.cancel_order(
        "order-001", _approval(registration, cancel, approval_id="cancel-before-restart")
    )
    action_id = port.cancel_calls[0][1]
    session.close()

    reopened, reopened_calls, _, _, registration = _open(
        tmp_path, query_evidence_verifier=query_verifier
    )
    return reopened, reopened_calls[0], registration, action_id


def _hold_account_lease(lock_root: str, connection: Any) -> None:
    lease = CtpAccountFlowLease(ACCOUNT, Path(lock_root)).acquire()
    connection.send("held")
    connection.recv()
    lease.release()


def test_admission_and_approval_bind_the_exact_configured_front_pair(tmp_path: Path) -> None:
    effective, registry, registration = _runtime(tmp_path)
    assert (
        require_ctp_simulation_execution_admission(effective, registry, registration)
        is registration
    )
    selected_registration = replace(
        registration,
        td_front="tcp://custom-trade.test:12001",
        md_front="tcp://custom-market.test:12002",
    )
    selected_identity = replace(
        _identity(),
        td_front=selected_registration.td_front,
        md_front=selected_registration.md_front,
    )
    assert selected_registration.digest != registration.digest
    assert selected_registration.environment == selected_identity.environment == "simnow"
    selected_approval = _approval(selected_registration, _request())
    assert selected_approval.environment == "simnow"
    assert selected_approval.td_front == selected_registration.td_front
    assert selected_approval.md_front == selected_registration.md_front
    with pytest.raises(CtpSimulationExecutionError, match="environment profile mismatch"):
        replace(registration, environment="production", sdk_profile="config_front_pair")
    with pytest.raises(CtpSimulationExecutionError, match="session profile mismatch"):
        replace(selected_identity, sdk_profile="legacy_profile")

    def mismatched_native_port(lease):
        port = _FakeNativePort(lease)
        port.identity = replace(port.identity, md_front="tcp://other-market.test:12002")
        return port

    with pytest.raises(CtpSimulationExecutionError, match="native session scope"):
        _open(tmp_path, port_factory=mismatched_native_port)
    with pytest.raises(CtpSimulationExecutionError, match="production disabled"):
        replace(_identity(), production=True)
    with pytest.raises(
        CtpSimulationExecutionError, match="execution slice only supports opening orders"
    ):
        replace(_request(), offset="CLOSE")


def test_registration_effective_digest_is_approval_bound_and_checked_before_factory(
    tmp_path: Path,
) -> None:
    effective, registry, registration = _runtime(tmp_path)
    bound = replace(registration, effective_digest=effective.effective_digest)
    request = _request()
    approval = _approval(bound, request)
    assert bound.digest != registration.digest
    assert approval.registration_digest == bound.digest

    stale = replace(registration, effective_digest="f" * 64)
    factory_calls: list[str] = []
    with pytest.raises(
        CtpSimulationExecutionError, match="registration effective digest mismatch"
    ):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=stale,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    assert factory_calls == []


def test_profile_backed_admission_binds_receipt_canonical_ctp_and_fake_session(
    tmp_path: Path, allow_synthetic_private_config_permissions: None
) -> None:
    effective, registry, registration, account_digest = _runtime_with_profile_ctp(tmp_path)
    assert require_ctp_simulation_execution_admission(effective, registry, registration) is registration
    scope = execution._execution_journal_scope(effective, registration)
    assert scope.as_dict()["profile_digest"] == effective.profile.digest

    request = _request()
    approval = _approval(registration, request)
    session_stub = SimpleNamespace(
        registration=registration,
        _verifier=SimpleNamespace(verify=lambda _approval: True),
    )
    assert CtpSimulationExecutionSession._verify_approval(session_stub, request, approval) > 0

    factory_calls: list[str] = []

    def factory(route: CtpSimulationExecutionRegistration, lease: CtpAccountFlowLease):
        assert route is registration
        factory_calls.append("factory")
        return _FakeNativePort(lease, account_digest)

    session = open_ctp_simulation_execution(
        effective=effective,
        registry=registry,
        registration=registration,
        native_session_factory=factory,
        approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
        query_evidence_verifier=_FakeQueryEvidenceVerifier(),
        writer_fence=_FakeWriterFence(account_digest),
    )
    try:
        assert factory_calls == ["factory"]
        assert session.registration.profile_digest == effective.profile.digest
    finally:
        session.close()


@pytest.mark.parametrize(
    ("stale_scope", "reason"),
    (
        ("mode", "sealed ctp runtime config rejected"),
        ("account", "sealed ctp account scope mismatch"),
        ("front_pair", "sealed ctp runtime config changed"),
        ("contract", "sealed ctp runtime config changed"),
        ("profile_receipt", "sealed runtime rejected"),
    ),
)
def test_profile_session_revalidates_before_submit_reservation(
    tmp_path: Path,
    stale_scope: str,
    reason: str,
    allow_synthetic_private_config_permissions: None,
) -> None:
    session, calls, effective, _registry, registration = _open_profile(tmp_path)
    port = calls[0]
    request = _request(client_order_id="profile-submit-" + stale_scope)
    approval = _approval(registration, request)
    config_path = registration.runtime_registration.runtime_dir / "config.yaml"
    profile = effective.profile
    old_receipt = profile.approval_receipt_digest if profile is not None else None
    try:
        if stale_scope == "mode":
            text = config_path.read_text(encoding="utf-8")
            text = text.replace("mode: simulation", "mode: live").replace(
                "preset: sandbox", "preset: managed_live_direct"
            )
            config_path.write_text(text, encoding="utf-8")
        elif stale_scope == "account":
            text = config_path.read_text(encoding="utf-8")
            config_path.write_text(
                text.replace('user_id: "profile-user"', 'user_id: "changed-user"'),
                encoding="utf-8",
            )
        elif stale_scope == "front_pair":
            text = config_path.read_text(encoding="utf-8")
            config_path.write_text(
                text.replace("md_front: tcp://market.simnow.test:10002", "md_front: tcp://other.simnow.test:10002"),
                encoding="utf-8",
            )
        elif stale_scope == "contract":
            text = config_path.read_text(encoding="utf-8")
            config_path.write_text(text.replace("instrument_id: rb2701", "instrument_id: ag2701"), encoding="utf-8")
        else:
            assert profile is not None
            object.__setattr__(profile, "approval_receipt_digest", "d" * 64)

        with pytest.raises(CtpSimulationExecutionError, match=reason):
            session.submit_order(
                client_order_id=request.client_order_id,
                instrument_id=request.instrument_id,
                exchange_id=request.exchange_id,
                side=request.side,
                quantity=request.quantity,
                limit_price=request.limit_price,
                approval=approval,
            )

        assert port.insert_calls == []
        assert session._journal.get(request.client_order_id) is None
    finally:
        if profile is not None and old_receipt is not None:
            object.__setattr__(profile, "approval_receipt_digest", old_receipt)
        session.close()


def test_same_file_mode_switch_cannot_rebind_unresolved_simnow_journal(
    tmp_path: Path,
    allow_synthetic_private_config_permissions: None,
) -> None:
    session, _calls, effective, registry, registration = _open_profile(tmp_path)
    config_path = registration.runtime_registration.runtime_dir / "config.yaml"
    journal_path = (
        tmp_path
        / "execution-state"
        / "journals"
        / (registration.account_fingerprint_sha256 + ".sqlite3")
    )
    old_scope = session._journal._scope
    request = _request(client_order_id="same-file-mode-switch")
    old_approval = _approval(
        registration, request, approval_id="same-file-simnow-approval"
    )

    # Keep one unresolved synthetic SimNow intent in the persisted journal.
    session._journal.reserve(request, old_approval.approval_id)
    session.close()

    # Change only the mode/preset in the same canonical ctp: config file.
    source = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        source.replace("mode: simulation", "mode: live").replace(
            "preset: sandbox", "preset: managed_live_direct"
        ),
        encoding="utf-8",
    )
    changed_config = load_runtime_config(config_path.parent, registry=registry)
    assert changed_config.mode == "live"
    assert changed_config.preset == "managed_live_direct"
    assert changed_config.config_digest != effective.config.config_digest

    # The candidate config has a different scope digest and cannot adopt the
    # old unresolved journal row.
    changed_scope = replace(old_scope, config_digest=changed_config.config_digest)
    assert changed_scope.digest != old_scope.digest
    with pytest.raises(
        CtpSimulationExecutionError, match="execution journal scope mismatch"
    ):
        execution._ExecutionJournal(journal_path, changed_scope)


def _seed_profile_cancel_target(
    session: CtpSimulationExecutionSession, client_order_id: str
) -> CtpSimulationWriteRequest:
    submit_request = _request(client_order_id=client_order_id)
    session._journal.reserve(
        submit_request,
        "prior-submit-approval",
        position_baseline={"BUY": 0, "SELL": 0},
    )
    snapshot = CtpSimulationOrderSnapshot(
        client_order_id=client_order_id,
        instrument_id=submit_request.instrument_id,
        exchange_id=submit_request.exchange_id,
        side=submit_request.side,
        quantity=submit_request.quantity,
        limit_price=submit_request.limit_price,
        traded_quantity=0,
        status="OPEN",
        order_ref="20260923-1",
        order_sys_id="order-sys-1",
        front_id=3,
        session_id=9,
    )
    session._journal.set_state(client_order_id, "OPEN", snapshot=snapshot)
    return CtpSimulationWriteRequest(
        action="CANCEL",
        client_order_id=client_order_id,
        instrument_id=submit_request.instrument_id,
        exchange_id=submit_request.exchange_id,
        side=submit_request.side,
        quantity=submit_request.quantity,
        limit_price=submit_request.limit_price,
        offset=submit_request.offset,
        hedge_flag=submit_request.hedge_flag,
        target_order_sys_id="order-sys-1",
        target_order_ref="20260923-1",
        target_front_id=3,
        target_session_id=9,
    )


def test_profile_session_revalidates_before_cancel_reservation_and_freezes_stale_order(
    tmp_path: Path, allow_synthetic_private_config_permissions: None
) -> None:
    session, calls, _effective, _registry, registration = _open_profile(tmp_path)
    client_order_id = "profile-cancel-stale"
    cancel_request = _seed_profile_cancel_target(session, client_order_id)
    approval = _approval(registration, cancel_request)
    config_path = registration.runtime_registration.runtime_dir / "config.yaml"
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text.replace('user_id: "profile-user"', 'user_id: "changed-user"'),
        encoding="utf-8",
    )
    try:
        with pytest.raises(CtpSimulationExecutionError, match="sealed ctp account scope mismatch"):
            session.cancel_order(client_order_id, approval)

        assert calls[0].cancel_calls == []
        assert session._journal.get(client_order_id)[4] == "UNKNOWN"
        assert session._journal.cancel_rows_for(client_order_id) == ()
    finally:
        session.close()


@pytest.mark.parametrize("action", ("submit", "cancel"))
def test_profile_session_revalidates_after_authorization_before_native_dispatch(
    tmp_path: Path,
    action: str,
    allow_synthetic_private_config_permissions: None,
) -> None:
    session, calls, _effective, _registry, registration = _open_profile(tmp_path)
    port = calls[0]
    client_order_id = "profile-dispatch-" + action
    if action == "cancel":
        request = _seed_profile_cancel_target(session, client_order_id)
    else:
        request = _request(client_order_id=client_order_id)
    approval = _approval(registration, request)
    config_path = registration.runtime_registration.runtime_dir / "config.yaml"

    def mutate_config(_request, _approval, *, action_id=None):
        text = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            text.replace('user_id: "profile-user"', 'user_id: "changed-user"'),
            encoding="utf-8",
        )

    port.authorize_write = mutate_config
    try:
        with pytest.raises(
            CtpSimulationExecutionError, match="profile scope changed before dispatch"
        ):
            if action == "submit":
                session.submit_order(
                    client_order_id=request.client_order_id,
                    instrument_id=request.instrument_id,
                    exchange_id=request.exchange_id,
                    side=request.side,
                    quantity=request.quantity,
                    limit_price=request.limit_price,
                    approval=approval,
                )
            else:
                session.cancel_order(client_order_id, approval)

        assert port.insert_calls == []
        assert port.cancel_calls == []
        if action == "submit":
            assert session._journal.get(client_order_id)[4] == "UNKNOWN"
        else:
            assert session._journal.get(client_order_id)[4] == "UNKNOWN"
            cancel_rows = session._journal.cancel_rows_for(client_order_id)
            assert len(cancel_rows) == 1
            assert cancel_rows[0][4] == "UNKNOWN"
    finally:
        session.close()


@pytest.mark.parametrize("action", ("submit", "cancel"))
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Open P2: a config change after the final fresh check can precede native dispatch; "
        "there is no trusted config-action broker yet"
    ),
)
def test_profile_config_change_after_final_check_blocks_native_dispatch(
    tmp_path: Path,
    action: str,
    allow_synthetic_private_config_permissions: None,
) -> None:
    """Pin the unresolved final-check-to-native-call window with fake dispatch only."""

    session, calls, _effective, _registry, registration = _open_profile(tmp_path)
    port = calls[0]
    client_order_id = "profile-final-check-race-" + action
    if action == "cancel":
        request = _seed_profile_cancel_target(session, client_order_id)
    else:
        request = _request(client_order_id=client_order_id)
    approval = _approval(registration, request)
    config_path = registration.runtime_registration.runtime_dir / "config.yaml"
    original_revalidate = session._revalidate_profile_scope_after_reserve
    revalidation_calls = 0

    def mutate_after_final_revalidation(*journal_ids: str) -> None:
        nonlocal revalidation_calls
        original_revalidate(*journal_ids)
        revalidation_calls += 1
        if revalidation_calls == 2:
            # The second post-reservation check is the last config read before
            # submit_order_insert / submit_order_action. Mutate at that exact
            # boundary, before the fake native port is called.
            text = config_path.read_text(encoding="utf-8")
            config_path.write_text(
                text.replace('user_id: "profile-user"', 'user_id: "changed-user"'),
                encoding="utf-8",
            )

    session._revalidate_profile_scope_after_reserve = mutate_after_final_revalidation
    try:
        try:
            if action == "submit":
                session.submit_order(
                    client_order_id=request.client_order_id,
                    instrument_id=request.instrument_id,
                    exchange_id=request.exchange_id,
                    side=request.side,
                    quantity=request.quantity,
                    limit_price=request.limit_price,
                    approval=approval,
                )
            else:
                session.cancel_order(client_order_id, approval)
        except CtpSimulationExecutionError:
            # A future trusted action boundary may reject this race. Either
            # rejection or a safe return must still leave native calls at 0.
            pass

        assert revalidation_calls == 2
        assert 'user_id: "changed-user"' in config_path.read_text(encoding="utf-8")
        # This is the desired future assertion. It currently xfails because
        # the production-shaped path reaches the direct native adapter call.
        assert port.insert_calls == []
        assert port.cancel_calls == []
    finally:
        session.close()


@pytest.mark.parametrize(
    ("field", "value"),
    (("profile_digest", "f" * 64), ("profile_approval_receipt_digest", "c" * 64)),
)
def test_profile_binding_mismatch_rejects_before_state_or_native_factory(
    tmp_path: Path,
    field: str,
    value: str,
    allow_synthetic_private_config_permissions: None,
) -> None:
    effective, registry, registration, account_digest = _runtime_with_profile_ctp(tmp_path)
    stale_registration = replace(registration, **{field: value})
    state_root = tmp_path / "execution-state"
    factory_calls: list[str] = []

    with pytest.raises(CtpSimulationExecutionError, match="profile scope binding mismatch"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=stale_registration,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(account_digest),
        )

    assert factory_calls == []
    assert not state_root.exists()


def test_profile_changed_canonical_account_scope_rejects_before_state_or_native_factory(
    tmp_path: Path, allow_synthetic_private_config_permissions: None
) -> None:
    effective, registry, registration, account_digest = _runtime_with_profile_ctp(tmp_path)
    config_path = registration.runtime_registration.runtime_dir / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace('user_id: "profile-user"', 'user_id: "changed-user"'),
        encoding="utf-8",
    )
    state_root = tmp_path / "execution-state"
    factory_calls: list[str] = []

    with pytest.raises(CtpSimulationExecutionError, match="sealed ctp account scope mismatch"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(account_digest),
        )

    assert factory_calls == []
    assert not state_root.exists()


def test_profile_scope_is_refreshed_under_lease_before_journal_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    allow_synthetic_private_config_permissions: None,
) -> None:
    effective, registry, registration, account_digest = _runtime_with_profile_ctp(tmp_path)
    config_path = registration.runtime_registration.runtime_dir / "config.yaml"
    state_root = tmp_path / "execution-state"
    journal_path = state_root / "journals" / (account_digest + ".sqlite3")
    factory_calls: list[str] = []
    admission_calls = 0
    original_admission = execution.require_ctp_simulation_execution_admission

    def mutate_before_second_admission(effective, registry, route):
        nonlocal admission_calls
        admission_calls += 1
        if admission_calls == 2:
            text = config_path.read_text(encoding="utf-8")
            config_path.write_text(text.replace('user_id: "profile-user"', 'user_id: "changed-user"'), encoding="utf-8")
        return original_admission(effective, registry, route)

    monkeypatch.setattr(
        execution,
        "require_ctp_simulation_execution_admission",
        mutate_before_second_admission,
    )

    with pytest.raises(CtpSimulationExecutionError, match="sealed ctp account scope mismatch"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(account_digest),
        )

    assert admission_calls == 2
    assert factory_calls == []
    assert not journal_path.exists()


def test_default_deny_profile_rejects_before_state_or_native_factory(
    tmp_path: Path, allow_synthetic_private_config_permissions: None
) -> None:
    effective, registry, registration, account_digest = _runtime_with_profile_ctp(
        tmp_path, sandbox_write_policy="deny"
    )
    state_root = tmp_path / "execution-state"
    factory_calls: list[str] = []

    with pytest.raises(CtpSimulationExecutionError, match="runtime profile policy mismatch"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(account_digest),
        )

    assert factory_calls == []
    assert not state_root.exists()


@pytest.mark.parametrize("block_name", ("ctp_simnow", "ctp"))
def test_private_ctp_account_mismatch_rejects_before_native_factory(
    tmp_path: Path, block_name: str, allow_synthetic_private_config_permissions: None
) -> None:
    effective, registry, registration = _runtime_with_private_ctp(
        tmp_path, block_name=block_name
    )
    wrong_account = replace(registration, account_fingerprint_sha256=ACCOUNT)
    factory_calls: list[str] = []

    with pytest.raises(CtpSimulationExecutionError, match="sealed ctp account scope mismatch"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=wrong_account,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    assert factory_calls == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        ({"instrument_id": "ag2701"}, "sealed ctp contract scope mismatch"),
        ({"exchange_id": "DCE"}, "sealed ctp contract scope mismatch"),
        ({"hedge_flag": "2"}, "sealed ctp contract scope mismatch"),
        (
            {"md_front": "tcp://other-market.simnow.test:10002"},
            "sealed ctp front pair registration mismatch",
        ),
        (
            {"td_front": "tcp://other-trade.simnow.test:10001"},
            "sealed ctp front pair registration mismatch",
        ),
    ),
)
def test_private_ctp_contract_or_front_mismatch_rejects_before_native_factory(
    tmp_path: Path,
    overrides: dict[str, str],
    reason: str,
    allow_synthetic_private_config_permissions: None,
) -> None:
    effective, registry, registration = _runtime_with_private_ctp(tmp_path)
    mismatched = replace(registration, **overrides)
    factory_calls: list[str] = []

    with pytest.raises(CtpSimulationExecutionError, match=reason):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=mismatched,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    assert factory_calls == []


def test_private_ctp_account_is_refreshed_from_current_sealed_config_before_factory(
    tmp_path: Path, allow_synthetic_private_config_permissions: None
) -> None:
    effective, registry, registration = _runtime_with_private_ctp(tmp_path)
    changed_config = Path(registration.runtime_registration.runtime_dir) / "config.yaml"
    changed_config.write_text(
        """config_schema_version: 4
strategy:
  id: example.ctp.simnow.execution
runtime:
  mode: simulation
  preset: sandbox
parameters: {}
secrets_ref: config_yaml
ctp_simnow:
  md_front: tcp://market.simnow.test:10002
  td_front: tcp://trade.simnow.test:10001
  broker_id: "9999"
  user_id: "changed-private-offline-user"
  password: "fixture-only-unused-value"
  auth_code: "fixture-only-unused-value"
  app_id: "fixture-only-unused-value"
  instrument_id: rb2701
  exchange_id: SHFE
  hedge_flag: "1"
""",
        encoding="utf-8",
    )
    factory_calls: list[str] = []

    with pytest.raises(CtpSimulationExecutionError, match="sealed ctp account scope mismatch"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    assert factory_calls == []


def _journal_scope(
    *,
    front_pair_set_sha256: Optional[str] = None,
    config_digest: str = "c" * 64,
    selected_pair: tuple[str, str] = (
        "tcp://market.simnow.test:10002",
        "tcp://trade.simnow.test:10001",
    ),
):
    pairs = (
        selected_pair,
        ("tcp://market-alt.simnow.test:11002", "tcp://trade-alt.simnow.test:11001"),
    )
    return execution._ExecutionJournalScope(
        runtime_id="example.ctp.simnow.execution",
        account_fingerprint_sha256=ACCOUNT,
        config_digest=config_digest,
        front_pair_set_sha256=front_pair_set_sha256 or execution._front_pair_set_digest(pairs),
        selected_md_front=selected_pair[0],
        selected_td_front=selected_pair[1],
    )


def _create_legacy_journal(path: Path, *, nonempty: bool) -> None:
    connection = execution.sqlite3.connect(str(path))
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
    if nonempty:
        request = _request()
        connection.execute(
            "INSERT INTO ctp_sim_orders(client_order_id, approval_id, request_digest, "
            "request_json, state, updated_at) VALUES(?,?,?,?,?,?)",
            (
                request.client_order_id,
                "legacy-approval",
                request.digest,
                "{}",
                "UNKNOWN",
                NOW,
            ),
        )
    connection.commit()
    connection.close()


def test_runtime_tampering_rejects_before_native_factory(tmp_path: Path) -> None:
    effective, registry, registration = _runtime(tmp_path)
    calls: list[str] = []
    tampered = replace(effective, effective_digest="0" * 64)
    with pytest.raises(CtpSimulationExecutionError):
        open_ctp_simulation_execution(
            effective=tampered,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    assert calls == []


def test_external_writer_fence_is_required_before_factory_and_every_write(
    tmp_path: Path,
) -> None:
    effective, registry, registration = _runtime(tmp_path)
    fence = _FakeWriterFence()
    fence.active = False
    factory_calls: list[str] = []
    with pytest.raises(CtpSimulationExecutionError, match="account writer fence unavailable"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=fence,
        )
    assert factory_calls == []

    fence.active = True
    session, calls, _, _, route = _open(tmp_path, writer_fence=fence)
    fence.active = False
    request = _request()
    with pytest.raises(CtpSimulationExecutionError, match="account writer fence unavailable"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(route, request),
        )
    assert calls[0].insert_calls == []
    session.close()


def test_flow_lease_is_acquired_before_factory_and_excludes_same_account(
    tmp_path: Path,
) -> None:
    session, calls, effective, registry, registration = _open(tmp_path)
    assert len(calls) == 1
    second_calls: list[str] = []
    with pytest.raises(CtpSimulationExecutionError, match="account flow already owned"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: second_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    assert second_calls == []
    session.close()


def test_account_flow_lease_conflicts_across_processes_and_releases_on_exit(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "shared-locks").absolute()
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_hold_account_lease, args=(str(root), child))
    process.start()
    try:
        assert parent.poll(10.0)
        assert parent.recv() == "held"
        with pytest.raises(CtpSimulationExecutionError, match="account flow already owned"):
            CtpAccountFlowLease(ACCOUNT, root).acquire()
    finally:
        parent.send("release")
        process.join(10.0)
    assert process.exitcode == 0
    with CtpAccountFlowLease(ACCOUNT, root):
        pass


def test_dead_owner_process_releases_flow_lease(tmp_path: Path) -> None:
    root = (tmp_path / "crash-locks").absolute()
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_hold_account_lease, args=(str(root), child))
    process.start()
    assert parent.poll(10.0)
    assert parent.recv() == "held"
    process.terminate()
    process.join(10.0)
    assert process.exitcode is not None
    with CtpAccountFlowLease(ACCOUNT, root):
        pass


def test_native_factory_exception_releases_lease_for_a_safe_retry(tmp_path: Path) -> None:
    effective, registry, registration = _runtime(tmp_path)
    with pytest.raises(RuntimeError, match="fake factory failure"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: (_ for _ in ()).throw(
                RuntimeError("fake factory failure")
            ),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    session, calls, _, _, _ = _open(tmp_path)
    assert len(calls) == 1
    session.close()


def test_native_close_exception_poisons_owner_and_retains_lease(tmp_path: Path) -> None:
    session, calls, _, _, _ = _open(tmp_path)
    calls[0].raise_on_close = True
    with pytest.raises(CtpSimulationExecutionError, match="owner is poisoned"):
        session.close()
    assert session._state == "POISONED"
    retry_calls: list[str] = []
    effective, registry, registration = _runtime(tmp_path)
    with pytest.raises(CtpSimulationExecutionError, match="account flow already owned"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: retry_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    assert retry_calls == []


def test_journal_close_exception_poisons_owner_and_retains_lease(tmp_path: Path) -> None:
    session, _, effective, registry, registration = _open(tmp_path)

    def fail_journal_close() -> None:
        raise OSError("fake journal close failure")

    session._journal.close = fail_journal_close
    with pytest.raises(CtpSimulationExecutionError, match="execution journal"):
        session.close()
    assert session._state == "POISONED"
    factory_calls: list[str] = []
    with pytest.raises(CtpSimulationExecutionError, match="account flow already owned"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    assert factory_calls == []


def test_failed_native_close_during_open_poison_retains_lease(tmp_path: Path) -> None:
    effective, registry, registration = _runtime(tmp_path)
    preflight_lease = CtpAccountFlowLease(ACCOUNT, tmp_path / "preflight-lock").acquire()
    port = _FakeNativePort(preflight_lease)
    preflight_lease.release()
    port.identity = replace(_identity(), account_fingerprint_sha256="c" * 64)
    port.raise_on_close = True
    with pytest.raises(CtpSimulationExecutionError, match="owner is poisoned"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: port,
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    retry_calls: list[str] = []
    with pytest.raises(CtpSimulationExecutionError, match="account flow already owned"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=lambda *_: retry_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    assert retry_calls == []


@pytest.mark.parametrize(
    "changes, reason",
    [
        ({"side": "SELL"}, "approval_scope_or_expiry_mismatch"),
        ({"quantity": 4}, "quantity_out_of_bounds"),
        ({"limit_price": Decimal("125.3")}, "price_out_of_bounds"),
    ],
)
def test_order_constraints_and_approval_are_checked_before_native_write(
    tmp_path: Path, changes: dict[str, Any], reason: str
) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    request = _request()
    approval = _approval(registration, request)
    with pytest.raises(CtpSimulationExecutionError, match=reason.replace("_", " ")):
        session.submit_order(
            client_order_id="order-001",
            instrument_id="rb2701",
            exchange_id="SHFE",
            side=changes.get("side", "BUY"),
            quantity=changes.get("quantity", 2),
            limit_price=changes.get("limit_price", Decimal("125.5")),
            approval=approval,
        )
    assert calls[0].insert_calls == []
    session.close()


def test_unmanaged_open_order_in_registered_contract_blocks_new_submit(tmp_path: Path) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    port.open_orders = (_accepted_order("OPEN"),)
    request = _request()
    with pytest.raises(CtpSimulationExecutionError, match="unmanaged open order blocks submission"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request),
        )
    assert port.insert_calls == []
    assert not session._journal.states()
    session.close()


def test_complete_open_order_snapshot_without_evidence_does_not_allow_write(
    tmp_path: Path,
) -> None:
    evidence = _FakeQueryEvidenceVerifier()
    evidence.accept = False
    session, calls, _, _, registration = _open(tmp_path, query_evidence_verifier=evidence)
    request = _request()
    with pytest.raises(CtpSimulationExecutionError, match="account exposure snapshot unavailable"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request),
        )
    assert evidence.query_kinds == ["account_open_orders"]
    assert calls[0].insert_calls == []
    assert not session._journal.states()
    session.close()


def test_final_submit_identity_recheck_blocks_changed_generation(tmp_path: Path) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    port.identity_change_on_call = 3  # open, entry check, then final pre-dispatch check
    request = _request()
    with pytest.raises(
        CtpSimulationExecutionError, match="native submit session changed before dispatch"
    ):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request),
        )
    assert port.insert_calls == []
    assert session._journal.get(request.client_order_id)[4] == "UNKNOWN"
    session.close()


def test_final_cancel_identity_recheck_blocks_changed_generation(tmp_path: Path) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    submit = _request()
    session.submit_order(
        client_order_id=submit.client_order_id,
        instrument_id=submit.instrument_id,
        exchange_id=submit.exchange_id,
        side=submit.side,
        quantity=submit.quantity,
        limit_price=submit.limit_price,
        approval=_approval(registration, submit),
    )
    port.order = _accepted_order("OPEN")
    session.reconcile("order-001")
    cancel = _request(action="CANCEL", target="sys-order-1")
    port.identity_change_on_call = port.identity_calls + 2
    with pytest.raises(
        CtpSimulationExecutionError, match="native cancel session changed before dispatch"
    ):
        session.cancel_order(
            "order-001", _approval(registration, cancel, approval_id="cancel-generation")
        )
    assert port.cancel_calls == []
    assert session._journal.get("order-001")[4] == "UNKNOWN"
    assert all(row[4] == "UNKNOWN" for row in session._journal.cancel_rows_for("order-001"))
    session.close()


def test_submit_authorization_failure_after_reservation_freezes_unknown(tmp_path: Path) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    request = _request()
    approval = _approval(registration, request)
    port.raise_on_authorize = True

    with pytest.raises(CtpSimulationExecutionError, match="native submit outcome unknown"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=approval,
        )

    assert port.authorize_calls == [(request, approval, None)]
    assert port.insert_calls == []
    assert session._journal.get(request.client_order_id)[4] == "UNKNOWN"
    session.close()


def test_submit_rechecks_writer_fence_after_authorization(tmp_path: Path) -> None:
    fence = _FakeWriterFence()
    session, calls, _, _, registration = _open(tmp_path, writer_fence=fence)
    port = calls[0]
    request = _request()
    approval = _approval(registration, request)
    authorize_write = port.authorize_write

    def revoke_fence_after_authorization(*args: Any, **kwargs: Any) -> None:
        authorize_write(*args, **kwargs)
        fence.active = False

    port.authorize_write = revoke_fence_after_authorization
    with pytest.raises(CtpSimulationExecutionError, match="native submit outcome unknown"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=approval,
        )

    assert len(port.authorize_calls) == 1
    assert port.insert_calls == []
    assert session._journal.get(request.client_order_id)[4] == "UNKNOWN"
    session.close()


def test_local_acceptance_stays_pending_until_order_trade_position_reconcile(
    tmp_path: Path,
) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    request = _request()
    assert (
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request),
        )
        == "PENDING"
    )
    assert len(port.insert_calls) == 1
    second = _request(client_order_id="order-002")
    with pytest.raises(CtpSimulationExecutionError, match="unresolved order freezes new writes"):
        session.submit_order(
            client_order_id=second.client_order_id,
            instrument_id=second.instrument_id,
            exchange_id=second.exchange_id,
            side=second.side,
            quantity=second.quantity,
            limit_price=second.limit_price,
            approval=_approval(registration, second, approval_id="approval-002"),
        )
    port.order = _accepted_order("FILLED", traded=2)
    port.trades = (CtpSimulationTradeSnapshot("order-001", "trade-1", 2, "rb2701", "SHFE", "BUY"),)
    port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 2),)
    result = session.reconcile("order-001")
    assert result.complete is True
    assert result.status == "FILLED"
    assert result.traded_quantity == 2
    assert result.trade_count == 1
    assert len(result.position_digest) == 64
    session.close()


def test_negative_local_dispatch_code_is_rejected_without_becoming_pending(
    tmp_path: Path,
) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    port.submit_code = -3
    request = _request()

    result = session.submit_order(
        client_order_id=request.client_order_id,
        instrument_id=request.instrument_id,
        exchange_id=request.exchange_id,
        side=request.side,
        quantity=request.quantity,
        limit_price=request.limit_price,
        approval=_approval(registration, request),
    )

    assert result == "REJECTED"
    assert session._journal.get(request.client_order_id)[4] == "REJECTED"
    assert len(port.insert_calls) == 1
    session.close()


def test_submit_rejects_receipt_for_another_client_order_id(tmp_path: Path) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    port.dispatch_receipt_mutator = lambda receipt: replace(
        receipt, client_order_id="order-foreign"
    )
    request = _request()

    with pytest.raises(CtpSimulationExecutionError, match="native submit outcome unknown"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request),
        )

    assert session._journal.get(request.client_order_id)[4] == "UNKNOWN"
    session.close()


def test_submit_session_change_after_native_dispatch_keeps_order_unknown(
    tmp_path: Path,
) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    request = _request()
    # Open, entry precheck, final pre-dispatch check, then post-dispatch check.
    port.identity_change_on_call = port.identity_calls + 3

    with pytest.raises(CtpSimulationExecutionError, match="native submit outcome unknown"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request),
        )

    assert len(port.insert_calls) == 1
    assert session._journal.get(request.client_order_id)[4] == "UNKNOWN"
    session.close()


def test_completed_orders_still_obey_account_contract_gross_exposure_cap(
    tmp_path: Path,
) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    first = _request()
    session.submit_order(
        client_order_id=first.client_order_id,
        instrument_id=first.instrument_id,
        exchange_id=first.exchange_id,
        side=first.side,
        quantity=first.quantity,
        limit_price=first.limit_price,
        approval=_approval(registration, first),
    )
    port.order = _accepted_order("FILLED", traded=2)
    port.trades = (CtpSimulationTradeSnapshot("order-001", "trade-1", 2, "rb2701", "SHFE", "BUY"),)
    port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 2),)
    session.reconcile("order-001")

    second = _request(client_order_id="order-002", quantity=1)
    session.submit_order(
        client_order_id=second.client_order_id,
        instrument_id=second.instrument_id,
        exchange_id=second.exchange_id,
        side=second.side,
        quantity=second.quantity,
        limit_price=second.limit_price,
        approval=_approval(registration, second, approval_id="approval-002"),
    )
    port.order = replace(
        _accepted_order("FILLED", traded=1),
        client_order_id="order-002",
        quantity=1,
        order_ref="20260923-2",
        order_sys_id="sys-order-2",
    )
    port.trades = (CtpSimulationTradeSnapshot("order-002", "trade-2", 1, "rb2701", "SHFE", "BUY"),)
    port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 3),)
    session.reconcile("order-002")

    third = _request(client_order_id="order-003", quantity=1)
    with pytest.raises(CtpSimulationExecutionError, match="gross position limit exceeded"):
        session.submit_order(
            client_order_id=third.client_order_id,
            instrument_id=third.instrument_id,
            exchange_id=third.exchange_id,
            side=third.side,
            quantity=third.quantity,
            limit_price=third.limit_price,
            approval=_approval(registration, third, approval_id="approval-003"),
        )
    assert len(port.insert_calls) == 2
    session.close()


def test_ambiguous_submit_is_durable_unknown_and_queries_must_prove_recovery(
    tmp_path: Path,
) -> None:
    session, calls, effective, registry, registration = _open(tmp_path)
    port = calls[0]
    port.raise_on_insert = True
    request = _request()
    with pytest.raises(CtpSimulationExecutionError, match="native submit outcome unknown"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request),
        )
    with pytest.raises(CtpSimulationExecutionError, match="unresolved order freezes new writes"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request, approval_id="approval-002"),
        )
    assert port.insert_calls == [request]
    port.complete = False
    with pytest.raises(CtpSimulationExecutionError, match="native reconciliation incomplete"):
        session.reconcile(request.client_order_id)
    session.close()

    # A fresh process/session reuses the durable journal and remains frozen.
    reopened, new_calls, _, _, _ = _open(tmp_path)
    recovered_port = new_calls[0]
    with pytest.raises(CtpSimulationExecutionError, match="unresolved order freezes new writes"):
        reopened.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request, approval_id="approval-retry-after-restart"),
        )
    with pytest.raises(CtpSimulationExecutionError, match="unresolved order freezes new writes"):
        reopened.submit_order(
            client_order_id="order-002",
            instrument_id="rb2701",
            exchange_id="SHFE",
            side="BUY",
            quantity=1,
            limit_price=Decimal("125.5"),
            approval=_approval(
                registration,
                _request(client_order_id="order-002"),
                approval_id="approval-003",
            ),
        )
    assert recovered_port.insert_calls == []
    recovered_port.order = _accepted_order("FILLED", traded=2)
    recovered_port.trades = (
        CtpSimulationTradeSnapshot("order-001", "trade-1", 2, "rb2701", "SHFE", "BUY"),
    )
    recovered_port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 2),)
    assert reopened.reconcile("order-001").status == "FILLED"
    reopened.close()


def test_unresolved_journal_rejects_selected_pair_change_before_native_factory(
    tmp_path: Path,
) -> None:
    session, calls, effective, registry, registration = _open(tmp_path)
    port = calls[0]
    port.raise_on_insert = True
    request = _request()
    with pytest.raises(CtpSimulationExecutionError, match="native submit outcome unknown"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request),
        )
    session.close()

    changed = replace(
        registration,
        td_front="tcp://trade.simnow.test:10003",
        md_front="tcp://market.simnow.test:10004",
    )
    factory_calls: list[str] = []
    with pytest.raises(CtpSimulationExecutionError, match="execution journal scope mismatch"):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=changed,
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
            query_evidence_verifier=_FakeQueryEvidenceVerifier(),
            writer_fence=_FakeWriterFence(),
        )
    assert factory_calls == []


def test_journal_rejects_candidate_pair_reorder_with_unresolved_intent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "candidate-scope.sqlite3"
    original = _journal_scope()
    journal = execution._ExecutionJournal(path, original)
    request = _request()
    journal.reserve(request, "approval-candidate-1")
    journal.set_state(request.client_order_id, "UNKNOWN")
    journal.close()

    pairs = (
        (original.selected_md_front, original.selected_td_front),
        ("tcp://market-alt.simnow.test:11002", "tcp://trade-alt.simnow.test:11001"),
    )
    reordered = _journal_scope(
        front_pair_set_sha256=execution._front_pair_set_digest(tuple(reversed(pairs)))
    )
    with pytest.raises(CtpSimulationExecutionError, match="execution journal scope mismatch"):
        execution._ExecutionJournal(path, reordered)


def test_verified_terminal_rows_allow_front_rollover_and_keep_history(tmp_path: Path) -> None:
    session, calls, effective, registry, registration = _open(tmp_path)
    port = calls[0]
    request = _request()
    assert (
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request),
        )
        == "PENDING"
    )
    port.order = _accepted_order("FILLED", traded=2)
    port.trades = (
        CtpSimulationTradeSnapshot("order-001", "trade-terminal-1", 2, "rb2701", "SHFE", "BUY"),
    )
    port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 2),)
    assert session.reconcile("order-001").status == "FILLED"
    prior_scope_digest = session._journal._scope_digest
    session.close()

    faster_pair_registration = replace(
        registration,
        td_front="tcp://trade.simnow.test:10003",
        md_front="tcp://market.simnow.test:10004",
    )
    new_ports: list[_FakeNativePort] = []

    def new_pair_factory(route: CtpSimulationExecutionRegistration, lease: CtpAccountFlowLease):
        assert route is faster_pair_registration
        new_port = _FakeNativePort(lease)
        new_port.identity = replace(
            _identity(),
            td_front=faster_pair_registration.td_front,
            md_front=faster_pair_registration.md_front,
        )
        new_ports.append(new_port)
        return new_port

    reopened = open_ctp_simulation_execution(
        effective=effective,
        registry=registry,
        registration=faster_pair_registration,
        native_session_factory=new_pair_factory,
        approval_verifier=HmacCtpSimulationApprovalVerifier(KEY_ID, KEY),
        query_evidence_verifier=_FakeQueryEvidenceVerifier(),
        writer_fence=_FakeWriterFence(),
    )
    assert len(new_ports) == 1
    assert new_ports[0].insert_calls == []
    assert reopened._journal.states()[0][3] == "FILLED"
    stored_row_scope = reopened._journal._db.execute(
        "SELECT execution_scope_sha256 FROM ctp_sim_orders WHERE client_order_id=?",
        (request.client_order_id,),
    ).fetchone()[0]
    assert stored_row_scope == prior_scope_digest
    assert reopened._journal._scope_digest != prior_scope_digest
    assert (
        reopened._journal._db.execute("SELECT COUNT(*) FROM ctp_sim_journal_scopes").fetchone()[0]
        == 2
    )
    reopened.close()


def test_terminal_journal_can_bind_changed_config_and_candidate_digest(tmp_path: Path) -> None:
    path = tmp_path / "terminal-config-rollover.sqlite3"
    original = _journal_scope()
    journal = execution._ExecutionJournal(path, original)
    request = _request()
    journal.reserve(request, "approval-config-rollover-1")
    journal.set_state(request.client_order_id, "FILLED")
    old_row_scope = journal._db.execute(
        "SELECT execution_scope_sha256 FROM ctp_sim_orders WHERE client_order_id=?",
        (request.client_order_id,),
    ).fetchone()[0]
    journal.close()

    pair = (original.selected_md_front, original.selected_td_front)
    other = ("tcp://market-alt.simnow.test:11002", "tcp://trade-alt.simnow.test:11001")
    changed_scope = _journal_scope(
        config_digest="d" * 64,
        front_pair_set_sha256=execution._front_pair_set_digest((other, pair)),
    )
    reopened = execution._ExecutionJournal(path, changed_scope)
    assert reopened._scope_digest == changed_scope.digest
    assert reopened._db.execute(
        "SELECT execution_scope_sha256 FROM ctp_sim_orders WHERE client_order_id=?",
        (request.client_order_id,),
    ).fetchone()[0] == old_row_scope
    assert reopened._db.execute(
        "SELECT COUNT(*) FROM ctp_sim_journal_scopes"
    ).fetchone()[0] == 2
    reopened.close()


def test_empty_legacy_journal_migrates_into_explicit_scope(tmp_path: Path) -> None:
    path = tmp_path / "empty-legacy.sqlite3"
    _create_legacy_journal(path, nonempty=False)
    scope = _journal_scope()

    journal = execution._ExecutionJournal(path, scope)
    assert journal.states() == ()
    metadata = journal._db.execute(
        "SELECT schema_version, scope_sha256 FROM ctp_sim_journal_metadata WHERE singleton=1"
    ).fetchone()
    assert metadata == (execution._JOURNAL_SCOPE_SCHEMA_VERSION, scope.digest)
    journal.close()

    reopened = execution._ExecutionJournal(path, scope)
    assert reopened.states() == ()
    reopened.close()


def test_nonempty_legacy_journal_without_scope_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "nonempty-legacy.sqlite3"
    _create_legacy_journal(path, nonempty=True)
    original_bytes = path.read_bytes()

    with pytest.raises(CtpSimulationExecutionError, match="execution journal legacy scope missing"):
        execution._ExecutionJournal(path, _journal_scope())

    assert path.read_bytes() == original_bytes
    connection = execution.sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='ctp_sim_journal_metadata'"
        ).fetchone() is None
    finally:
        connection.close()


@pytest.mark.parametrize("foreign_table", ["ctp_execution_meta", "unrelated_ledger"])
def test_foreign_sqlite_ledger_is_rejected_before_legacy_wal_mutation(
    tmp_path: Path, foreign_table: str
) -> None:
    path = tmp_path / "shared-account.sqlite3"
    connection = execution.sqlite3.connect(str(path))
    connection.execute("CREATE TABLE " + foreign_table + " (identity TEXT NOT NULL)")
    connection.commit()
    connection.close()

    with pytest.raises(
        CtpSimulationExecutionError,
        match="execution journal foreign store",
    ):
        execution._ExecutionJournal(path, _journal_scope())

    readonly = execution.sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        assert readonly.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        table_names = {
            row[0]
            for row in readonly.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert table_names == {foreign_table}
    finally:
        readonly.close()


def test_orphan_sqlite_sidecar_is_rejected_before_legacy_database_creation(tmp_path: Path) -> None:
    path = tmp_path / "orphan.sqlite3"
    Path(str(path) + "-wal").write_bytes(b"untrusted sidecar")

    with pytest.raises(
        CtpSimulationExecutionError,
        match="execution journal foreign store",
    ):
        execution._ExecutionJournal(path, _journal_scope())

    assert not path.exists()


def test_nonempty_schema_without_legacy_identity_is_rejected_before_wal(tmp_path: Path) -> None:
    path = tmp_path / "unidentified.sqlite3"
    connection = execution.sqlite3.connect(str(path))
    connection.execute("PRAGMA user_version=7")
    connection.close()
    assert path.stat().st_size > 0

    with pytest.raises(
        CtpSimulationExecutionError,
        match="execution journal foreign store",
    ):
        execution._ExecutionJournal(path, _journal_scope())

    readonly = execution.sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        assert readonly.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        assert readonly.execute("PRAGMA user_version").fetchone()[0] == 7
    finally:
        readonly.close()


def test_legacy_journal_rejects_v20_execution_store_before_any_write(tmp_path: Path) -> None:
    pytest.importorskip("bt_api_execution.store")
    try:
        from bt_api_execution.contracts import ExecutionScope
        from bt_api_execution.store import SqliteExecutionStore
    except Exception:
        pytest.skip("V20 CTP account-store source is unavailable")
    if not callable(getattr(SqliteExecutionStore, "open_ctp_account_store", None)):
        pytest.skip("V20 CTP account-store API is unavailable")

    path = tmp_path / "shared-v20-ledger.sqlite3"
    scope = ExecutionScope(
        provider="ctp",
        environment="simnow",
        account_ref="ctp-account-ref.v1:" + "a" * 64,
        strategy_id="synthetic.v20-legacy-reject",
        trading_day="20260926",
    )
    store = SqliteExecutionStore.open_ctp_account_store(str(path), scope)
    store.close()
    original_bytes = path.read_bytes()
    readonly = execution.sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        original_mode = readonly.execute("PRAGMA journal_mode").fetchone()[0]
        original_objects = readonly.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall()
    finally:
        readonly.close()

    with pytest.raises(
        CtpSimulationExecutionError,
        match="execution journal foreign store",
    ):
        execution._ExecutionJournal(path, _journal_scope())

    assert path.read_bytes() == original_bytes
    readonly = execution.sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        assert readonly.execute("PRAGMA journal_mode").fetchone()[0] == original_mode
        assert readonly.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall() == original_objects
    finally:
        readonly.close()


def test_complete_flag_alone_cannot_clear_unknown_without_query_evidence(
    tmp_path: Path,
) -> None:
    query_verifier = _FakeQueryEvidenceVerifier()
    session, calls, _, _, registration = _open(tmp_path, query_evidence_verifier=query_verifier)
    port = calls[0]
    request = _request()
    port.raise_on_insert = True
    with pytest.raises(CtpSimulationExecutionError, match="native submit outcome unknown"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=_approval(registration, request),
        )
    port.raise_on_insert = False
    port.order = _accepted_order("FILLED", traded=2)
    port.trades = (CtpSimulationTradeSnapshot("order-001", "trade-1", 2, "rb2701", "SHFE", "BUY"),)
    port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 2),)
    query_verifier.accept = False
    with pytest.raises(CtpSimulationExecutionError, match="native reconciliation incomplete"):
        session.reconcile("order-001")
    with pytest.raises(CtpSimulationExecutionError, match="unresolved order freezes new writes"):
        second = _request(client_order_id="order-002", quantity=1)
        session.submit_order(
            client_order_id=second.client_order_id,
            instrument_id=second.instrument_id,
            exchange_id=second.exchange_id,
            side=second.side,
            quantity=second.quantity,
            limit_price=second.limit_price,
            approval=_approval(registration, second, approval_id="approval-002"),
        )
    session.close()


def test_cancel_requires_reconciled_target_and_separate_short_lived_approval(
    tmp_path: Path,
) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    submit = _request()
    session.submit_order(
        client_order_id=submit.client_order_id,
        instrument_id=submit.instrument_id,
        exchange_id=submit.exchange_id,
        side=submit.side,
        quantity=submit.quantity,
        limit_price=submit.limit_price,
        approval=_approval(registration, submit),
    )
    port.order = _accepted_order("OPEN")
    port.trades = ()
    session.reconcile("order-001")
    cancel = _request(action="CANCEL", target="sys-order-1")
    mismatched_cancel = replace(cancel, target_front_id=4)
    with pytest.raises(CtpSimulationExecutionError, match="approval scope or expiry mismatch"):
        session.cancel_order(
            "order-001",
            _approval(registration, mismatched_cancel, approval_id="cancel-wrong-session"),
        )
    assert port.cancel_calls == []
    assert session.cancel_order(
        "order-001", _approval(registration, cancel, approval_id="cancel-1")
    )
    assert len(port.cancel_calls) == 1
    assert port.cancel_calls[0][0].order_sys_id == "sys-order-1"
    assert port.cancel_calls[0][0].front_id == 3
    assert port.cancel_calls[0][0].session_id == 9
    port.order = _accepted_order("OPEN")
    with pytest.raises(
        CtpSimulationExecutionError, match="native cancel request outcome unverified"
    ):
        session.reconcile("order-001")
    assert session._journal.get("order-001")[4] == "UNKNOWN"
    first_action_id = port.cancel_calls[0][1]
    port.cancel_results[first_action_id] = _cancel_result(first_action_id, "PENDING")
    with pytest.raises(
        CtpSimulationExecutionError, match="native cancel request outcome unverified"
    ):
        session.reconcile("order-001")
    assert session._journal.get("order-001")[4] == "UNKNOWN"
    port.cancel_results[first_action_id] = _cancel_result(first_action_id, "REJECTED")
    assert session.reconcile("order-001").status == "OPEN"
    assert (
        session.cancel_order("order-001", _approval(registration, cancel, approval_id="cancel-2"))
        == "CANCEL_PENDING"
    )
    assert len(port.cancel_calls) == 2
    second_action_id = port.cancel_calls[1][1]
    port.order = _accepted_order("CANCELED")
    port.cancel_results[second_action_id] = _cancel_result(second_action_id, "CANCELED", port.order)
    result = session.reconcile("order-001")
    assert result.status == "CANCELED"
    session.close()


def test_cancel_authorization_failure_binds_exact_action_and_freezes_target(
    tmp_path: Path,
) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    submit = _request()
    session.submit_order(
        client_order_id=submit.client_order_id,
        instrument_id=submit.instrument_id,
        exchange_id=submit.exchange_id,
        side=submit.side,
        quantity=submit.quantity,
        limit_price=submit.limit_price,
        approval=_approval(registration, submit),
    )
    port.order = _accepted_order("OPEN")
    session.reconcile("order-001")
    cancel = _request(action="CANCEL", target="sys-order-1")
    approval = _approval(registration, cancel, approval_id="cancel-auth-failure")
    port.raise_on_authorize = True

    with pytest.raises(CtpSimulationExecutionError, match="native cancel outcome unknown"):
        session.cancel_order("order-001", approval)

    authorized_request, authorized_approval, action_id = port.authorize_calls[-1]
    assert authorized_request.action == "CANCEL"
    assert authorized_request.digest == cancel.digest
    assert authorized_approval is approval
    assert action_id.startswith("cancel-")
    assert port.cancel_calls == []
    assert session._journal.get(action_id)[4] == "UNKNOWN"
    assert session._journal.get("order-001")[4] == "UNKNOWN"
    session.close()


def test_cancel_rechecks_writer_fence_after_authorization(tmp_path: Path) -> None:
    fence = _FakeWriterFence()
    session, calls, _, _, registration = _open(tmp_path, writer_fence=fence)
    port = calls[0]
    submit = _request()
    session.submit_order(
        client_order_id=submit.client_order_id,
        instrument_id=submit.instrument_id,
        exchange_id=submit.exchange_id,
        side=submit.side,
        quantity=submit.quantity,
        limit_price=submit.limit_price,
        approval=_approval(registration, submit),
    )
    port.order = _accepted_order("OPEN")
    session.reconcile("order-001")
    cancel = _request(action="CANCEL", target="sys-order-1")
    approval = _approval(registration, cancel, approval_id="cancel-fence-loss")
    authorize_write = port.authorize_write

    def revoke_fence_after_authorization(*args: Any, **kwargs: Any) -> None:
        authorize_write(*args, **kwargs)
        fence.active = False

    port.authorize_write = revoke_fence_after_authorization
    with pytest.raises(CtpSimulationExecutionError, match="native cancel outcome unknown"):
        session.cancel_order("order-001", approval)

    action_id = port.authorize_calls[-1][2]
    assert action_id.startswith("cancel-")
    assert port.cancel_calls == []
    assert session._journal.get(action_id)[4] == "UNKNOWN"
    assert session._journal.get("order-001")[4] == "UNKNOWN"
    session.close()


def test_restart_recovers_exact_terminal_cancelled_target_without_claiming_ack(
    tmp_path: Path,
) -> None:
    verifier = _FakeQueryEvidenceVerifier()
    session, port, _, action_id = _pending_cancel_after_restart(tmp_path, verifier)
    port.cancel_history_missing = True
    port.order = _accepted_order("CANCELED", traded=1)
    port.trades = (
        CtpSimulationTradeSnapshot("order-001", "trade-after-cancel", 1, "rb2701", "SHFE", "BUY"),
    )
    port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 1),)
    verified_kinds_before = len(verifier.query_kinds)

    result = session.reconcile("order-001")

    assert result.status == "CANCELED"
    assert result.traded_quantity == 1
    assert result.trade_count == 1
    assert verifier.query_kinds[verified_kinds_before:] == ["orders", "trades", "positions"]
    assert session._journal.get("order-001")[4] == "CANCELED"
    cancel_row = next(
        row for row in session._journal.cancel_rows_for("order-001") if row[0] == action_id
    )
    assert cancel_row[4] == "TARGET_TERMINAL"
    assert cancel_row[4] != "CANCELED"
    assert port.cancel_calls == []
    with pytest.raises(CtpSimulationExecutionError, match="cancel requires reconciled open order"):
        cancel = _request(action="CANCEL", target="sys-order-1")
        session.cancel_order(
            "order-001", _approval(session.registration, cancel, approval_id="cancel-again")
        )
    assert port.cancel_calls == []
    session.close()


def test_restart_cancel_history_with_mismatched_identity_cannot_resolve_target(
    tmp_path: Path,
) -> None:
    session, port, _, action_id = _pending_cancel_after_restart(tmp_path)
    port.cancel_history_missing = True
    port.cancel_history_identity = replace(
        port.identity, connection_generation=port.identity.connection_generation + 1
    )
    port.order = _accepted_order("CANCELED")

    with pytest.raises(
        CtpSimulationExecutionError, match="native cancel request outcome unverified"
    ):
        session.reconcile("order-001")

    assert session._journal.get("order-001")[4] == "UNKNOWN"
    cancel_row = next(
        row for row in session._journal.cancel_rows_for("order-001") if row[0] == action_id
    )
    assert cancel_row[4] == "UNKNOWN"
    assert port.cancel_calls == []
    session.close()


@pytest.mark.parametrize(("status", "traded"), (("OPEN", 0), ("PARTIAL", 1)))
def test_restart_missing_cancel_history_does_not_resolve_nonterminal_target(
    tmp_path: Path, status: str, traded: int
) -> None:
    session, port, _, action_id = _pending_cancel_after_restart(tmp_path)
    port.cancel_history_missing = True
    port.order = _accepted_order(status, traded=traded)
    if traded:
        port.trades = (
            CtpSimulationTradeSnapshot("order-001", "trade-partial", 1, "rb2701", "SHFE", "BUY"),
        )
        port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 1),)

    with pytest.raises(
        CtpSimulationExecutionError, match="native cancel request outcome unverified"
    ):
        session.reconcile("order-001")

    assert session._journal.get("order-001")[4] == "UNKNOWN"
    cancel_row = next(
        row for row in session._journal.cancel_rows_for("order-001") if row[0] == action_id
    )
    assert cancel_row[4] == "UNKNOWN"
    assert port.cancel_calls == []
    session.close()


def test_restart_terminal_fallback_rejects_ambiguous_order_snapshot(tmp_path: Path) -> None:
    session, port, _, action_id = _pending_cancel_after_restart(tmp_path)
    port.cancel_history_missing = True
    canceled = _accepted_order("CANCELED", traded=1)
    port.order_records_override = (canceled, canceled)
    port.trades = (
        CtpSimulationTradeSnapshot("order-001", "trade-partial", 1, "rb2701", "SHFE", "BUY"),
    )
    port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 1),)

    with pytest.raises(CtpSimulationExecutionError, match="native order readback ambiguous"):
        session.reconcile("order-001")

    assert session._journal.get("order-001")[4] == "UNKNOWN"
    cancel_row = next(
        row for row in session._journal.cancel_rows_for("order-001") if row[0] == action_id
    )
    assert cancel_row[4] == "UNKNOWN"
    assert port.cancel_calls == []
    session.close()


def test_restart_terminal_fallback_requires_cancel_target_identity_match(tmp_path: Path) -> None:
    session, port, _, action_id = _pending_cancel_after_restart(tmp_path)
    port.cancel_history_missing = True
    port.order = replace(_accepted_order("CANCELED"), order_sys_id="other-order")

    with pytest.raises(
        CtpSimulationExecutionError, match="native cancel request outcome unverified"
    ):
        session.reconcile("order-001")

    assert session._journal.get("order-001")[4] == "UNKNOWN"
    cancel_row = next(
        row for row in session._journal.cancel_rows_for("order-001") if row[0] == action_id
    )
    assert cancel_row[4] == "UNKNOWN"
    assert port.cancel_calls == []
    session.close()


def test_expired_or_wrong_key_approval_is_rejected_without_native_write(tmp_path: Path) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    request = _request()
    expired = _approval(registration, request, issued_at=NOW - 25.0, expires_at=NOW - 1.0)
    with pytest.raises(CtpSimulationExecutionError, match="approval scope or expiry mismatch"):
        session.submit_order(
            client_order_id=request.client_order_id,
            instrument_id=request.instrument_id,
            exchange_id=request.exchange_id,
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            approval=expired,
        )
    assert calls[0].insert_calls == []
    session.close()


def test_receipt_binding_signature_and_approval_ttl_are_enforced(tmp_path: Path) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    request = _request()
    approvals = (
        _approval(registration, request, expires_at=NOW + 25.0),
        _approval(registration, request, signature_key=b"other-approval-key-material-32bytes"),
        replace(_approval(registration, request), receipt_digest="c" * 64),
        replace(_approval(registration, request), md_front="tcp://wrong-market.test:10002"),
    )
    expected = (
        "approval scope or expiry mismatch",
        "approval signature rejected",
        "approval scope or expiry mismatch",
        "approval scope or expiry mismatch",
    )
    for index, (approval, reason) in enumerate(zip(approvals, expected)):
        with pytest.raises(CtpSimulationExecutionError, match=reason):
            session.submit_order(
                client_order_id=request.client_order_id,
                instrument_id=request.instrument_id,
                exchange_id=request.exchange_id,
                side=request.side,
                quantity=request.quantity,
                limit_price=request.limit_price,
                approval=approval,
            )
        assert calls[0].insert_calls == []
    session.close()


def test_position_delta_mismatch_keeps_order_unknown_and_freezes_writes(tmp_path: Path) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    request = _request()
    session.submit_order(
        client_order_id=request.client_order_id,
        instrument_id=request.instrument_id,
        exchange_id=request.exchange_id,
        side=request.side,
        quantity=request.quantity,
        limit_price=request.limit_price,
        approval=_approval(registration, request),
    )
    port.order = _accepted_order("FILLED", traded=2)
    port.trades = (CtpSimulationTradeSnapshot("order-001", "trade-1", 2, "rb2701", "SHFE", "BUY"),)
    port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 3),)
    with pytest.raises(CtpSimulationExecutionError, match="position delta mismatch"):
        session.reconcile("order-001")
    second = _request(client_order_id="order-002")
    with pytest.raises(CtpSimulationExecutionError, match="unresolved order freezes new writes"):
        session.submit_order(
            client_order_id=second.client_order_id,
            instrument_id=second.instrument_id,
            exchange_id=second.exchange_id,
            side=second.side,
            quantity=second.quantity,
            limit_price=second.limit_price,
            approval=_approval(registration, second, approval_id="approval-002"),
        )
    assert len(port.insert_calls) == 1
    session.close()


def test_trade_contract_mismatch_keeps_order_unknown(tmp_path: Path) -> None:
    session, calls, _, _, registration = _open(tmp_path)
    port = calls[0]
    request = _request()
    session.submit_order(
        client_order_id=request.client_order_id,
        instrument_id=request.instrument_id,
        exchange_id=request.exchange_id,
        side=request.side,
        quantity=request.quantity,
        limit_price=request.limit_price,
        approval=_approval(registration, request),
    )
    port.order = _accepted_order("FILLED", traded=2)
    port.trades = (CtpSimulationTradeSnapshot("order-001", "trade-1", 2, "cu2701", "SHFE", "BUY"),)
    port.positions = (CtpSimulationPositionSnapshot("rb2701", "SHFE", "BUY", 2),)
    with pytest.raises(CtpSimulationExecutionError, match="native trade volume mismatch"):
        session.reconcile("order-001")
    assert session._journal.get("order-001")[4] == "UNKNOWN"
    session.close()
