"""Offline contract tests for the unregistered CTP action authority adapter."""

from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

from backtrader_runtime import ctp_managed_action_authority as authority
from backtrader_runtime import ctp_managed_actionref_floor as actionref_floor


NOW = 1_800_000_000_000_000_000
HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


@dataclass
class FakeExecutionScope:
    provider: str = "ctp"
    environment: str = "simnow"
    account_key: str = "account:" + HEX_A
    key: str = "scope:" + HEX_B
    strategy_id: str = "strategy.sa_midfreq_cross_exchange"
    trading_day: str = "20260926"


@dataclass
class FakeOwner:
    owner_intent_id: str = "owner.i9.1"
    account_key: str = "account:" + HEX_A
    scope_key: str = "scope:" + HEX_B


@dataclass
class FakeLease:
    scope_key: str = "account:" + HEX_A
    owner_id: str = "writer.owner.1"
    fencing_token: int = 1
    expires_at_ns: int = NOW + 10_000_000_000


@dataclass
class FakeSession:
    owner_intent_id: str = "owner.i9.1"
    account_key: str = "account:" + HEX_A
    scope_key: str = "scope:" + HEX_B
    trading_day: str = "20260926"
    session_generation_id: str = "session.gen.1"
    dispatch_front_id: int = 11
    dispatch_session_id: int = 22
    source_instance_id: str = "source.instance.1"
    native_client_epoch: str = "e" * 32
    native_api_source_id: str = "source.api.1"
    native_spi_source_id: str = "source.spi.1"
    native_api_generation: int = 3
    source_connection_generation: int = 4
    connection_generation: int = 4
    source_high_watermark: int = 1
    session_binding_sha256: str = ""


@dataclass
class FakeCorrelation:
    version: int
    account_key: str
    scope_key: str
    trading_day: str
    operation: str
    command_id: str
    request_payload_sha256: str
    reservation_managed_intent_id: str
    managed_action_id: str
    runtime_order_id: str
    order_ref: str
    cancel_target_exchange_id: str | None
    cancel_target_order_sys_id: str | None
    cancel_target_front_id: int | None
    cancel_target_session_id: int | None
    approval_use_id: str
    approval_digest: str
    session_binding_sha256: str
    session_generation_id: str
    dispatch_front_id: int
    dispatch_session_id: int
    native_request_id: int
    native_action_ref: int | None
    native_request_payload_sha256: str


@dataclass
class FakeCommand:
    account_key: str
    scope_key: str
    trading_day: str
    operation: str
    command_id: str
    request_payload: dict
    request_payload_sha256: str
    reservation_managed_intent_id: str
    order_ref: str | None
    cancel_target_order_ref: str | None
    cancel_target_exchange_id: str | None
    cancel_target_order_sys_id: str | None
    cancel_target_front_id: int | None
    cancel_target_session_id: int | None
    approval_use_id: str
    approval_digest: str
    session_binding: dict
    session_binding_sha256: str
    status: str
    correlation_key: FakeCorrelation
    native_request_payload: dict
    native_request_payload_sha256: str
    authority_binding_sha256: str = HEX_C


@dataclass
class FakeAuthority:
    authority_type: str
    command_binding_sha256: str
    approval_use_id: str
    approval_digest: str
    source_digest_sha256: str
    verifier_id: str
    verified_at_ns: int
    expires_at_ns: int


@dataclass
class FakeNativeBinding:
    binding_id: str = "binding.one.1"
    owner_intent_id: str = "owner.i9.1"
    account_key: str = "account:" + HEX_A
    scope_key: str = "scope:" + HEX_B
    command_id: str = "command.one.1"
    operation: str = "SUBMIT"
    trading_day: str = "20260926"
    request_payload_json: str = ""
    request_payload_sha256: str = ""
    reservation_managed_intent_id: str = "intent.one"
    managed_action_id: str = "intent.one"
    runtime_order_id: str = "bt-managed-v1:" + "a" * 64
    order_ref: str = "000000000123"
    native_request_id: int = 41
    native_action_ref: int | None = None
    native_request_payload_json: str = ""
    native_request_payload_sha256: str = ""
    cancel_target_order_ref: str | None = None
    cancel_target_exchange_id: str | None = None
    cancel_target_order_sys_id: str | None = None
    cancel_target_front_id: int | None = None
    cancel_target_session_id: int | None = None
    session_binding_sha256: str = ""
    session_generation_id: str = "session.gen.1"
    dispatch_front_id: int = 11
    dispatch_session_id: int = 22
    writer_owner_id: str = "writer.owner.1"
    writer_fencing_token: int = 1
    expires_at_ns: int = NOW + 2_000_000_000


class FakeStore:
    def __init__(self, command, session):
        self.command = command
        self.session = session
        self._issued_ctp_callback_session_owners = {"owner.i9.1": OWNER}
        self.readback_calls = 0
        self.lease_calls = 0
        self.claim_calls = 0

    def read_ctp_dispatch_command(self, scope, command_id):
        self.readback_calls += 1
        assert scope is EXECUTION_SCOPE
        assert command_id == self.command.command_id
        return self.command

    def assert_writer_lease(self, scope, lease):
        self.lease_calls += 1
        assert scope is EXECUTION_SCOPE
        assert lease is WRITER_LEASE

    def read_ctp_callback_session_context_facts(self, owner):
        assert owner is OWNER
        return self.session, "broker-redacted", "user-redacted"


class FakeScopeResolver:
    def __init__(self, value):
        self.value = value
        self.calls = 0
        self.command = None

    def resolve(self, command, execution_scope):
        self.calls += 1
        assert command is self.command
        assert execution_scope is EXECUTION_SCOPE
        return self.value

    def validate_action_context(
        self,
        command,
        execution_scope,
        *,
        session_binding,
        session_broker_id,
        session_user_id,
    ):
        assert session_binding is not None
        assert session_broker_id == "broker-redacted"
        assert session_user_id == "user-redacted"
        return self.resolve(command, execution_scope)


class FakePermitSource:
    def __init__(self):
        self.permit = None
        self.calls = []

    def read_permit(self, permit_id):
        self.calls.append(permit_id)
        return self.permit


class FakeRevocationSource:
    def __init__(self):
        self.snapshot = None

    def read_revocation(self, permit):
        return self.snapshot


class FakeFenceSource:
    def __init__(self):
        self.snapshot = None

    def read_active_fence(self, scope):
        return self.snapshot


class FakeClock:
    def __init__(self, values=None):
        self.values = list(values or [NOW, NOW, NOW, NOW])
        self.last = self.values[-1]

    def now_ns(self):
        if self.values:
            self.last = self.values.pop(0)
        return self.last


class FakeActionRefLedgerSource:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.calls = []

    def read_action_ref_ledger(self, account_key):
        self.calls.append(account_key)
        return self.snapshot

    def set_current_status(self, status):
        if self.snapshot is None:
            return
        rows = tuple(
            replace(row, status=status) if row.command_id == "command.one.1" else row
            for row in self.snapshot.allocations
        )
        self.snapshot = replace(
            self.snapshot,
            allocations=rows,
            ledger_epoch=self.snapshot.ledger_epoch + 1,
            mapping_sha256=actionref_floor.ctp_managed_action_ref_mapping_sha256(rows),
        )


EXECUTION_SCOPE = FakeExecutionScope()
OWNER = FakeOwner()
WRITER_LEASE = FakeLease()
SCOPE = authority.CtpManagedActionScopeV1(
    provider="ctp",
    environment="simnow",
    mode="simulation",
    preset="sandbox",
    runtime_id="runtime.013_3",
    strategy_id="strategy.sa_midfreq_cross_exchange",
    runtime_registration_digest=HEX_A,
    mode_registration_digest=HEX_B,
    config_digest=HEX_C,
    effective_digest="d" * 64,
    profile_digest="f" * 64,
    account_fingerprint_sha256=HEX_A,
    front_pair_sha256="2" * 64,
    front_pair_set_sha256="3" * 64,
)


def _session_payload(session):
    return {
        "binding_type": "ctp_callback_session_binding.v1",
        "owner_intent_id": session.owner_intent_id,
        "account_key": session.account_key,
        "scope_key": session.scope_key,
        "trading_day": session.trading_day,
        "session_generation_id": session.session_generation_id,
        "dispatch_front_id": session.dispatch_front_id,
        "dispatch_session_id": session.dispatch_session_id,
        "source_tags": {
            "source_instance_id": session.source_instance_id,
            "native_client_epoch": session.native_client_epoch,
            "native_api_source_id": session.native_api_source_id,
            "native_spi_source_id": session.native_spi_source_id,
            "native_api_generation": session.native_api_generation,
            "connection_generation": session.source_connection_generation,
        },
        "source_high_watermark": session.source_high_watermark,
    }


def _digest(value):
    return hashlib.sha256(authority._canonical_json(value)).hexdigest()


def _fixture(monkeypatch, operation="SUBMIT"):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    WRITER_LEASE.expires_at_ns = NOW + 10_000_000_000
    session = FakeSession()
    session_payload = _session_payload(session)
    session.session_binding_sha256 = _digest(session_payload)
    logical = {"InstrumentID": "rb2610", "VolumeTotalOriginal": 1}
    native_request_id = 41
    if operation == "CANCEL":
        native_action_ref = 7
        order_ref = "000000000123"
        cancel_target = {
            "order_ref": order_ref,
            "exchange_id": "SHFE",
            "order_sys_id": "sys-9",
            "front_id": 11,
            "session_id": 22,
        }
        logical.update(
            OrderRef=cancel_target["order_ref"],
            ExchangeID=cancel_target["exchange_id"],
            OrderSysID=cancel_target["order_sys_id"],
            FrontID=cancel_target["front_id"],
            SessionID=cancel_target["session_id"],
        )
    else:
        native_action_ref = None
        order_ref = "000000000123"
        cancel_target = None
    request_hash = _digest(logical)
    if operation == "CANCEL":
        native_payload = dict(logical, OrderActionRef=native_action_ref)
    else:
        native_payload = dict(logical)
    native_hash = _digest(native_payload)
    permit_id = "permit.one.1"
    command_id = "command.one.1"
    corr = FakeCorrelation(
        version=2,
        account_key=EXECUTION_SCOPE.account_key,
        scope_key=EXECUTION_SCOPE.key,
        trading_day=EXECUTION_SCOPE.trading_day,
        operation=operation,
        command_id=command_id,
        request_payload_sha256=request_hash,
        reservation_managed_intent_id="intent.one",
        managed_action_id="action.one" if operation == "CANCEL" else "intent.one",
        runtime_order_id="bt-managed-v1:" + "a" * 64,
        order_ref=order_ref,
        cancel_target_exchange_id=None if cancel_target is None else cancel_target["exchange_id"],
        cancel_target_order_sys_id=None if cancel_target is None else cancel_target["order_sys_id"],
        cancel_target_front_id=None if cancel_target is None else cancel_target["front_id"],
        cancel_target_session_id=None if cancel_target is None else cancel_target["session_id"],
        approval_use_id=permit_id,
        approval_digest="0" * 64,
        session_binding_sha256=session.session_binding_sha256,
        session_generation_id=session.session_generation_id,
        dispatch_front_id=session.dispatch_front_id,
        dispatch_session_id=session.dispatch_session_id,
        native_request_id=native_request_id,
        native_action_ref=native_action_ref,
        native_request_payload_sha256=native_hash,
    )
    command = FakeCommand(
        account_key=EXECUTION_SCOPE.account_key,
        scope_key=EXECUTION_SCOPE.key,
        trading_day=EXECUTION_SCOPE.trading_day,
        operation=operation,
        command_id=command_id,
        request_payload=logical,
        request_payload_sha256=request_hash,
        reservation_managed_intent_id="intent.one",
        order_ref=order_ref if operation == "SUBMIT" else None,
        cancel_target_order_ref=None if cancel_target is None else cancel_target["order_ref"],
        cancel_target_exchange_id=None if cancel_target is None else cancel_target["exchange_id"],
        cancel_target_order_sys_id=None if cancel_target is None else cancel_target["order_sys_id"],
        cancel_target_front_id=None if cancel_target is None else cancel_target["front_id"],
        cancel_target_session_id=None if cancel_target is None else cancel_target["session_id"],
        approval_use_id=permit_id,
        approval_digest="0" * 64,
        session_binding=session_payload,
        session_binding_sha256=session.session_binding_sha256,
        status="READY",
        correlation_key=corr,
        native_request_payload=native_payload,
        native_request_payload_sha256=native_hash,
    )
    store = FakeStore(command, session)
    resolver = FakeScopeResolver(SCOPE)
    resolver.command = command
    permit_source = FakePermitSource()
    revocation_source = FakeRevocationSource()
    fence_source = FakeFenceSource()
    clock = FakeClock()
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    pinned_key = authority.CtpPinnedEd25519ActionKey(
        issuer="issuer.test",
        key_id="key.test.1",
        audience="ctp-i9-store-claim",
        public_key=public_key,
        valid_from_ns=NOW - 10_000_000_000,
        valid_until_ns=NOW + 60_000_000_000,
    )
    signature_verifier = authority.PinnedEd25519CtpActionPermitVerifier((pinned_key,))
    command.approval_use_id = permit_id
    command.approval_digest = "0" * 64
    corr.approval_use_id = permit_id
    scope_digest = SCOPE.digest
    action_digest = authority.CtpManagedActionAuthorityAdapter._action_digest(command, SCOPE)
    permit_kwargs = {
        "permit_id": permit_id,
        "issuer": "issuer.test",
        "key_id": "key.test.1",
        "audience": "ctp-i9-store-claim",
        "environment": SCOPE.environment,
        "mode": SCOPE.mode,
        "preset": SCOPE.preset,
        "scope_sha256": scope_digest,
        "action_sha256": action_digest,
        "issued_at_ns": NOW - 1_000_000_000,
        "expires_at_ns": NOW + 4_000_000_000,
        "revocation_epoch": 9,
        "fence_id": "fence.account.1",
        "fence_epoch": 12,
        "fence_owner_id": "service.owner.1",
        "nonce": "nonce.unique.1",
        "signature_hex": "0" * 128,
    }
    unsigned = authority.CtpManagedActionPermitV1(**permit_kwargs)
    signed = private_key.sign(unsigned.signed_payload()).hex()
    permit = authority.CtpManagedActionPermitV1(**dict(permit_kwargs, signature_hex=signed))
    command.approval_digest = permit.digest
    corr.approval_digest = permit.digest
    permit_source.permit = permit
    revocation_source.snapshot = authority.CtpManagedActionRevocationSnapshot(
        permit_id=permit_id,
        key_id="key.test.1",
        epoch=9,
        revoked=False,
        key_active=True,
        observed_at_ns=NOW - 1_000_000,
        valid_until_ns=NOW + 2_000_000_000,
        source_digest_sha256="4" * 64,
    )
    fence_source.snapshot = authority.CtpManagedActionWriterFenceSnapshot(
        fence_id="fence.account.1",
        owner_id="service.owner.1",
        account_fingerprint_sha256=SCOPE.account_fingerprint_sha256,
        environment=SCOPE.environment,
        mode=SCOPE.mode,
        epoch=12,
        observed_at_ns=NOW - 1_000_000,
        expires_at_ns=NOW + 3_000_000_000,
        source_digest_sha256="5" * 64,
    )
    fake_types = (
        FakeStore,
        FakeExecutionScope,
        FakeOwner,
        FakeSession,
        FakeLease,
        FakeCommand,
        FakeAuthority,
    )
    monkeypatch.setattr(authority, "_load_v17_types", lambda: fake_types)
    monkeypatch.setattr(authority, "_load_v17_native_binding_type", lambda: FakeNativeBinding)
    action_ref_ledger_source = FakeActionRefLedgerSource()
    if operation == "CANCEL":
        allocations = (
            actionref_floor.CtpManagedActionRefAllocationV1(
                account_key=EXECUTION_SCOPE.account_key,
                native_action_ref=native_action_ref,
                command_id=command_id,
                scope_key=EXECUTION_SCOPE.key,
                managed_action_id=corr.managed_action_id,
                status="READY",
            ),
        )
        action_ref_ledger_source.snapshot = actionref_floor.CtpManagedActionRefLedgerSnapshotV1(
            account_key=EXECUTION_SCOPE.account_key,
            cutover_id="cutover.account.1",
            cutover_floor=5,
            observed_native_high_water=6,
            counter_high_water=native_action_ref,
            ledger_epoch=1,
            ledger_sources=("g5", "v21"),
            allocations=allocations,
            unresolved_unknown_count=0,
            observed_at_ns=NOW - 1_000_000,
            valid_until_ns=NOW + 1_000_000_000,
            native_floor_source_digest_sha256="6" * 64,
            merged_ledger_source_digest_sha256="7" * 64,
            mapping_sha256=actionref_floor.ctp_managed_action_ref_mapping_sha256(allocations),
        )
    adapter = authority.CtpManagedActionAuthorityAdapter(
        store=store,
        scope=EXECUTION_SCOPE,
        owner_handle=OWNER,
        writer_lease=WRITER_LEASE,
        scope_resolver=resolver,
        permit_source=permit_source,
        signature_verifier=signature_verifier,
        revocation_source=revocation_source,
        fence_source=fence_source,
        trusted_clock=clock,
        action_ref_ledger_source=action_ref_ledger_source,
    )
    # Bind the test objects after creating the adapter.
    return SimpleNamespace(
        adapter=adapter,
        command=command,
        corr=corr,
        store=store,
        resolver=resolver,
        permit=permit,
        permit_source=permit_source,
        revocation_source=revocation_source,
        fence_source=fence_source,
        clock=clock,
        private_key=private_key,
        pinned_key=pinned_key,
        signature_verifier=signature_verifier,
        action_ref_ledger_source=action_ref_ledger_source,
        native_binding=FakeNativeBinding(
            operation=operation,
            request_payload_json=authority._canonical_json(logical).decode("ascii"),
            request_payload_sha256=request_hash,
            managed_action_id=corr.managed_action_id,
            native_request_payload_json=authority._canonical_json(native_payload).decode("ascii"),
            native_request_payload_sha256=native_hash,
            native_action_ref=native_action_ref,
            cancel_target_order_ref=None if cancel_target is None else cancel_target["order_ref"],
            cancel_target_exchange_id=None
            if cancel_target is None
            else cancel_target["exchange_id"],
            cancel_target_order_sys_id=None
            if cancel_target is None
            else cancel_target["order_sys_id"],
            cancel_target_front_id=None if cancel_target is None else cancel_target["front_id"],
            cancel_target_session_id=None if cancel_target is None else cancel_target["session_id"],
            session_binding_sha256=session.session_binding_sha256,
        ),
    )


def _replace_signed_permit(fixture, **changes):
    values = dict(fixture.permit.__dict__)
    values.update(changes)
    values["signature_hex"] = "0" * 128
    unsigned = authority.CtpManagedActionPermitV1(**values)
    values["signature_hex"] = fixture.private_key.sign(unsigned.signed_payload()).hex()
    signed = authority.CtpManagedActionPermitV1(**values)
    fixture.permit_source.permit = signed
    fixture.command.approval_digest = signed.digest
    fixture.corr.approval_digest = signed.digest
    return signed


def test_submit_permit_is_ed25519_verified_and_binds_exact_store_row(monkeypatch):
    fixture = _fixture(monkeypatch)

    result = fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    assert type(result) is FakeAuthority
    assert result.authority_type == "ctp_dispatch_authority.v1"
    assert result.command_binding_sha256 == fixture.command.authority_binding_sha256
    assert result.approval_use_id == fixture.permit.permit_id
    assert result.approval_digest == fixture.permit.digest
    assert result.verified_at_ns == NOW
    assert result.expires_at_ns == NOW + 249_000_000
    assert fixture.store.readback_calls == 1
    assert fixture.store.lease_calls == 2
    assert fixture.permit_source.calls == [fixture.permit.permit_id]


def _verify_claimed_fixture(fixture):
    fixture.command.status = "CLAIMED"
    fixture.action_ref_ledger_source.set_current_status("CLAIMED")
    return fixture.adapter.verify_claimed_action(
        fixture.command,
        fixture.native_binding,
        now_ns=NOW,
    )


def test_claimed_phase_revalidates_permit_without_issuing_or_consuming_authority(monkeypatch):
    fixture = _fixture(monkeypatch)

    result = _verify_claimed_fixture(fixture)

    assert result is None
    assert fixture.store.command.status == "CLAIMED"
    assert fixture.permit_source.calls == [fixture.permit.permit_id]
    assert fixture.store.claim_calls == 0
    assert fixture.store.lease_calls >= 2


def test_claimed_phase_accepts_store_allocated_cancel_binding(monkeypatch):
    fixture = _fixture(monkeypatch, operation="CANCEL")

    assert _verify_claimed_fixture(fixture) is None
    assert fixture.native_binding.native_action_ref == 7
    assert fixture.native_binding.native_request_id == 41
    assert fixture.store.claim_calls == 0
    assert len(fixture.action_ref_ledger_source.calls) == 2


def test_claimed_phase_rejects_revocation_fence_and_expiry_changes(monkeypatch):
    fixture = _fixture(monkeypatch)
    fixture.command.status = "CLAIMED"
    fixture.revocation_source.snapshot = replace(
        fixture.revocation_source.snapshot,
        revoked=True,
        source_digest_sha256="6" * 64,
    )
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        _verify_claimed_fixture(fixture)

    fixture = _fixture(monkeypatch)
    fixture.command.status = "CLAIMED"
    fixture.fence_source.snapshot = replace(
        fixture.fence_source.snapshot,
        epoch=fixture.fence_source.snapshot.epoch + 1,
        source_digest_sha256="7" * 64,
    )
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        _verify_claimed_fixture(fixture)

    fixture = _fixture(monkeypatch)
    fixture.command.status = "CLAIMED"
    expired_now = NOW + 5_000_000_000
    fixture.clock.values = [expired_now] * 4
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_claimed_action(
            fixture.command,
            fixture.native_binding,
            now_ns=expired_now,
        )

    fixture = _fixture(monkeypatch)
    fixture.command.status = "CLAIMED"
    fixture.revocation_source.snapshot = replace(
        fixture.revocation_source.snapshot,
        observed_at_ns=NOW - 240_000_000,
    )
    fixture.fence_source.snapshot = replace(
        fixture.fence_source.snapshot,
        observed_at_ns=NOW - 240_000_000,
    )
    fixture.clock.values = [NOW, NOW, NOW + 11_000_000, NOW + 11_000_000]
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_claimed_action(
            fixture.command,
            fixture.native_binding,
            now_ns=NOW,
        )


def test_claimed_phase_rechecks_original_store_binding_expiry_at_final_sample(monkeypatch):
    fixture = _fixture(monkeypatch)
    fixture.command.status = "CLAIMED"
    binding_expires = NOW + 200_000_000
    store_now = binding_expires - 100_000
    fixture.native_binding = replace(
        fixture.native_binding,
        expires_at_ns=binding_expires,
    )
    fixture.clock.values = [store_now, store_now, store_now, binding_expires + 100_000]

    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_claimed_action(
            fixture.command,
            fixture.native_binding,
            now_ns=store_now,
        )


def test_claimed_phase_binds_exact_native_payload_and_approval_identity(monkeypatch):
    fixture = _fixture(monkeypatch)
    fixture.command.status = "CLAIMED"
    wrong_binding = replace(fixture.native_binding, native_request_id=42)
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_claimed_action(
            fixture.command,
            wrong_binding,
            now_ns=NOW,
        )
    assert fixture.permit_source.calls == []

    fixture = _fixture(monkeypatch)
    fixture.command.status = "CLAIMED"
    fixture.command.approval_use_id = "permit.other"
    fixture.corr.approval_use_id = "permit.other"
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        _verify_claimed_fixture(fixture)


def test_cancel_permit_excludes_preallocated_actionref_but_verifies_store_transform(monkeypatch):
    fixture = _fixture(monkeypatch, operation="CANCEL")

    result = fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    assert result.authority_type == "ctp_dispatch_authority.v1"
    assert fixture.command.native_request_payload["OrderActionRef"] == 7
    assert fixture.corr.native_request_id == 41
    assert fixture.corr.native_action_ref == 7
    assert len(fixture.action_ref_ledger_source.calls) == 2


def test_cancel_is_denied_without_account_wide_actionref_floor_source(monkeypatch):
    fixture = _fixture(monkeypatch, operation="CANCEL")
    fixture.adapter._action_ref_ledger_source = None

    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    assert fixture.store.claim_calls == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_native_high_water": 5},
        {"cutover_floor": 4},
        {"cutover_id": "cutover.replaced.1"},
    ],
)
def test_higher_ledger_epoch_cannot_roll_back_floor_or_change_cutover(monkeypatch, changes):
    fixture = _fixture(monkeypatch, operation="CANCEL")
    fixture.adapter.verify_action(fixture.command, now_ns=NOW)
    previous = fixture.action_ref_ledger_source.snapshot
    fixture.action_ref_ledger_source.snapshot = replace(
        previous,
        ledger_epoch=previous.ledger_epoch + 1,
        **changes,
    )

    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


def test_higher_ledger_epoch_cannot_erase_allocated_mapping_or_lower_counter(monkeypatch):
    fixture = _fixture(monkeypatch, operation="CANCEL")
    previous = fixture.action_ref_ledger_source.snapshot
    later = actionref_floor.CtpManagedActionRefAllocationV1(
        account_key=EXECUTION_SCOPE.account_key,
        native_action_ref=8,
        command_id="command.cancel.queued",
        scope_key=EXECUTION_SCOPE.key,
        managed_action_id="action.cancel.queued",
        status="READY",
    )
    allocations = previous.allocations + (later,)
    fixture.action_ref_ledger_source.snapshot = replace(
        previous,
        ledger_epoch=previous.ledger_epoch + 1,
        allocations=allocations,
        counter_high_water=8,
        mapping_sha256=actionref_floor.ctp_managed_action_ref_mapping_sha256(allocations),
    )
    fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture.action_ref_ledger_source.snapshot = replace(
        fixture.action_ref_ledger_source.snapshot,
        ledger_epoch=fixture.action_ref_ledger_source.snapshot.ledger_epoch + 1,
        allocations=previous.allocations,
        counter_high_water=7,
        mapping_sha256=actionref_floor.ctp_managed_action_ref_mapping_sha256(previous.allocations),
    )
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


@pytest.mark.parametrize(
    ("field", "delete", "replacement"),
    [
        ("OrderSysID", True, None),
        ("SessionID", False, 99),
    ],
)
def test_cancel_payload_must_echo_all_target_fields(monkeypatch, field, delete, replacement):
    fixture = _fixture(monkeypatch, operation="CANCEL")
    if delete:
        del fixture.command.request_payload[field]
    else:
        fixture.command.request_payload[field] = replacement
    logical_hash = _digest(fixture.command.request_payload)
    fixture.command.request_payload_sha256 = logical_hash
    fixture.corr.request_payload_sha256 = logical_hash
    fixture.command.native_request_payload = dict(
        fixture.command.request_payload,
        OrderActionRef=fixture.corr.native_action_ref,
    )
    native_hash = _digest(fixture.command.native_request_payload)
    fixture.command.native_request_payload_sha256 = native_hash
    fixture.corr.native_request_payload_sha256 = native_hash

    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    assert fixture.action_ref_ledger_source.calls == []
    assert fixture.permit_source.calls == []


@pytest.mark.parametrize(
    "scope",
    [
        lambda: replace(SCOPE, provider="other-provider"),
        lambda: replace(
            SCOPE,
            environment="production",
            mode="live",
            preset="managed_live_direct",
        ),
        lambda: replace(SCOPE, strategy_id="strategy.other"),
    ],
)
def test_resolver_scope_must_match_pinned_execution_scope(monkeypatch, scope):
    fixture = _fixture(monkeypatch)
    fixture.resolver.value = scope()

    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


def test_matching_wrong_scope_fence_and_signed_permit_cannot_rebind_store_account(monkeypatch):
    fixture = _fixture(monkeypatch)
    wrong_scope = replace(SCOPE, account_fingerprint_sha256="9" * 64)
    fixture.resolver.value = wrong_scope
    old_fence = fixture.fence_source.snapshot
    fixture.fence_source.snapshot = replace(
        old_fence, account_fingerprint_sha256=wrong_scope.account_fingerprint_sha256
    )
    permit = _replace_signed_permit(
        fixture,
        scope_sha256=wrong_scope.digest,
        action_sha256=authority.CtpManagedActionAuthorityAdapter._action_digest(
            fixture.command, wrong_scope
        ),
    )
    fixture.signature_verifier.verify(permit, now_ns=NOW)

    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f.command.native_request_payload.__setitem__("LimitPrice", 123),
        lambda f: setattr(f.command, "status", "CLAIMED"),
        lambda f: setattr(f.store, "command", SimpleNamespace(**vars(f.command))),
    ],
)
def test_store_readback_or_native_payload_mismatch_fails_closed(monkeypatch, mutate):
    fixture = _fixture(monkeypatch)
    mutate(fixture)

    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


def test_signature_tamper_wrong_key_or_wrong_digest_is_rejected(monkeypatch):
    fixture = _fixture(monkeypatch)
    fixture.command.approval_digest = "9" * 64
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    tampered = authority.CtpManagedActionPermitV1(
        **dict(fixture.permit.__dict__, action_sha256="8" * 64)
    )
    fixture.permit_source.permit = tampered
    fixture.command.approval_digest = tampered.digest
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    other_public = (
        Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    wrong_pin = authority.CtpPinnedEd25519ActionKey(
        issuer=fixture.pinned_key.issuer,
        key_id=fixture.pinned_key.key_id,
        audience=fixture.pinned_key.audience,
        public_key=other_public,
        valid_from_ns=fixture.pinned_key.valid_from_ns,
        valid_until_ns=fixture.pinned_key.valid_until_ns,
    )
    fixture.adapter._signature_verifier = authority.PinnedEd25519CtpActionPermitVerifier(
        (wrong_pin,)
    )
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


@pytest.mark.parametrize(
    "field,value",
    [("revoked", True), ("epoch", 10), ("key_active", False)],
)
def test_revocation_true_or_epoch_mismatch_fails_closed(monkeypatch, field, value):
    fixture = _fixture(monkeypatch)
    snapshot = fixture.revocation_source.snapshot
    fixture.revocation_source.snapshot = authority.CtpManagedActionRevocationSnapshot(
        permit_id=snapshot.permit_id,
        key_id=snapshot.key_id,
        epoch=value if field == "epoch" else snapshot.epoch,
        revoked=value if field == "revoked" else snapshot.revoked,
        key_active=value if field == "key_active" else snapshot.key_active,
        observed_at_ns=snapshot.observed_at_ns,
        valid_until_ns=snapshot.valid_until_ns,
        source_digest_sha256=snapshot.source_digest_sha256,
    )

    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


def test_fence_mismatch_unknown_sources_and_clock_skew_fail_closed(monkeypatch):
    fixture = _fixture(monkeypatch)
    old = fixture.fence_source.snapshot
    fixture.fence_source.snapshot = authority.CtpManagedActionWriterFenceSnapshot(
        fence_id=old.fence_id,
        owner_id=old.owner_id,
        account_fingerprint_sha256=old.account_fingerprint_sha256,
        environment=old.environment,
        mode=old.mode,
        epoch=old.epoch + 1,
        observed_at_ns=old.observed_at_ns,
        expires_at_ns=old.expires_at_ns,
        source_digest_sha256=old.source_digest_sha256,
    )
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    fixture.permit_source.permit = None
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    fixture.revocation_source.snapshot = None
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    old = fixture.revocation_source.snapshot
    fixture.revocation_source.snapshot = authority.CtpManagedActionRevocationSnapshot(
        permit_id=old.permit_id,
        key_id=old.key_id,
        epoch=old.epoch,
        revoked=False,
        key_active=True,
        observed_at_ns=NOW - 250_000_001,
        valid_until_ns=NOW + 2_000_000_000,
        source_digest_sha256=old.source_digest_sha256,
    )
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    old = fixture.fence_source.snapshot
    fixture.fence_source.snapshot = authority.CtpManagedActionWriterFenceSnapshot(
        fence_id=old.fence_id,
        owner_id=old.owner_id,
        account_fingerprint_sha256=old.account_fingerprint_sha256,
        environment=old.environment,
        mode=old.mode,
        epoch=old.epoch,
        observed_at_ns=NOW - 250_000_001,
        expires_at_ns=old.expires_at_ns,
        source_digest_sha256=old.source_digest_sha256,
    )
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    fixture.clock.values = [NOW + 251_000_000, NOW + 251_000_000]
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


def test_expired_or_overlong_permit_and_clock_rollback_fail_closed(monkeypatch):
    fixture = _fixture(monkeypatch)
    fixture.clock.values = [NOW + 5_000_000_000] * 4
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW + 5_000_000_000)

    fixture = _fixture(monkeypatch)
    _replace_signed_permit(fixture, expires_at_ns=NOW + 5_000_000_001)
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    _replace_signed_permit(fixture, issued_at_ns=NOW + 250_000_001)
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    fixture.clock.values = [NOW, NOW, NOW, NOW, NOW - 1, NOW - 1]
    fixture.adapter.verify_action(fixture.command, now_ns=NOW)
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW - 1)


def test_authority_expiry_is_bounded_by_snapshot_freshness_key_and_lease(monkeypatch):
    fixture = _fixture(monkeypatch)
    near_expiry_key = replace(fixture.pinned_key, valid_until_ns=NOW + 100_000_000)
    fixture.adapter._signature_verifier = authority.PinnedEd25519CtpActionPermitVerifier(
        (near_expiry_key,)
    )

    result = fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    assert result.expires_at_ns == near_expiry_key.valid_until_ns

    fixture = _fixture(monkeypatch)
    fixture.adapter._writer_lease.expires_at_ns = NOW + 100_000_000
    result = fixture.adapter.verify_action(fixture.command, now_ns=NOW)
    assert result.expires_at_ns == fixture.adapter._writer_lease.expires_at_ns

    fixture = _fixture(monkeypatch)
    fixture.revocation_source.snapshot = replace(
        fixture.revocation_source.snapshot,
        observed_at_ns=NOW - 240_000_000,
        valid_until_ns=NOW + 2_000_000_000,
    )
    fixture.fence_source.snapshot = replace(
        fixture.fence_source.snapshot,
        observed_at_ns=NOW - 230_000_000,
        expires_at_ns=NOW + 3_000_000_000,
    )
    result = fixture.adapter.verify_action(fixture.command, now_ns=NOW)
    assert result.expires_at_ns == NOW + 10_000_000


def test_ed25519_pin_mapping_cannot_be_mutated_or_reassigned(monkeypatch):
    fixture = _fixture(monkeypatch)
    pins = fixture.signature_verifier._keys

    with pytest.raises(TypeError):
        pins["attacker.key"] = fixture.pinned_key
    with pytest.raises(AttributeError, match="immutable"):
        fixture.signature_verifier._keys = {}

    assert fixture.signature_verifier.verify(fixture.permit, now_ns=NOW)[0]


def test_real_store_rejects_authority_after_snapshot_freshness_cutoff(tmp_path, monkeypatch):
    """The V17 transaction must reject a locally verified authority after delay."""

    try:
        from importlib.metadata import version

        if version("bt_api_execution") != "0.2.0":
            pytest.skip("the exact V17 execution source candidate is required")
        execution = importlib.import_module("bt_api_execution")
        store_module = importlib.import_module("bt_api_execution.store")
    except Exception:
        pytest.skip("the exact V17 execution source candidate is required")

    scope = execution.ExecutionScope(
        "CTP", "simulation", "acct.action-authority-delay", "strategy.test", "20260926"
    )
    store = store_module.SqliteExecutionStore(tmp_path / "delayed-claim.sqlite3")
    try:
        lease = store.acquire_or_renew_lease(scope, "test-delayed-claim-owner")
        source_digests = (
            ("backtrader_prototype", hashlib.sha256(b"delay-a").hexdigest()),
            ("sdk_jsonl", hashlib.sha256(b"delay-b").hexdigest()),
        )
        legacy_scope = execution.ExecutionScope(
            "CTP", "simulation", scope.account_ref, "strategy.legacy", "20260925"
        )
        legacy_mapping = store_module.CtpOrderRefLegacyMapping(
            source_name="backtrader_prototype",
            account_key=scope.account_key,
            trading_day="20260925",
            scope_key=legacy_scope.key,
            managed_intent_id="legacy.delay.intent",
            runtime_order_id="legacy.delay.runtime",
            order_ref="000000000012",
        )
        generation = "generation.delay.claim"
        proof = store_module.CtpOrderRefSeedProof(
            trading_day=scope.trading_day,
            native_max_order_ref="000000000010",
            legacy_ledger_max_order_ref="000000000012",
            legacy_ledger_sha256=execution.payload_sha256(dict(source_digests)),
            account_key=scope.account_key,
            scope_key=scope.key,
            session_generation_id=generation,
            native_front_id=4,
            native_session_id=91,
            existing_native_order_refs=("000000000009", "000000000010"),
            legacy_source_sha256=source_digests,
            legacy_mappings=(legacy_mapping,),
        )
        intent_id = "intent.authority.delay"
        runtime_order_id = "bt-managed-v1:" + hashlib.sha256(intent_id.encode()).hexdigest()
        reservation = store.seed_ctp_order_ref_and_reserve_identity(
            scope, proof, intent_id, runtime_order_id, writer_lease=lease
        )
        command_id = "command.authority.delay"
        approval_use_id = "permit.authority.delay"
        approval_digest = hashlib.sha256(b"test signed permit digest").hexdigest()
        receipt_id = "a" * 32
        session_binding = {
            "session_generation_id": generation,
            "dispatch_front_id": 4,
            "dispatch_session_id": 91,
        }
        store.stage_ctp_dispatch_command(
            scope,
            command_id,
            "SUBMIT",
            {"OrderRef": reservation.order_ref, "InstrumentID": "rb2710"},
            approval_use_id=approval_use_id,
            approval_digest=approval_digest,
            session_binding=session_binding,
            writer_lease=lease,
            managed_intent_id=intent_id,
            order_ref=reservation.order_ref,
            session_generation_id=generation,
            dispatch_front_id=4,
            dispatch_session_id=91,
            native_request_id=101,
            local_queue_receipt_id=receipt_id,
        )
        store.record_ctp_dispatch_queue_receipt(
            scope,
            command_id,
            {
                "kind": "command_receipt",
                "command": "submit",
                "receipt_id": receipt_id,
                "queued": True,
            },
            writer_lease=lease,
        )

        class FreshnessCappedAuthority:
            def verify_action(self, staged, *, now_ns):
                return store_module.CtpDispatchAuthority(
                    authority_type="ctp_dispatch_authority.v1",
                    command_binding_sha256=staged.authority_binding_sha256,
                    approval_use_id=staged.approval_use_id,
                    approval_digest=staged.approval_digest,
                    source_digest_sha256=hashlib.sha256(b"fresh snapshots").hexdigest(),
                    verifier_id="test-freshness-capped-verifier",
                    verified_at_ns=now_ns,
                    expires_at_ns=now_ns + authority._MAX_TRUST_SNAPSHOT_AGE_NS,
                )

        claim_start_ns = __import__("time").time_ns()
        claim_times = iter(
            (claim_start_ns, claim_start_ns + authority._MAX_TRUST_SNAPSHOT_AGE_NS + 1)
        )
        monkeypatch.setattr(store_module.time, "time_ns", lambda: next(claim_times))

        with pytest.raises(store_module.ContractValidationError, match="authority is expired"):
            store.claim_ctp_dispatch_command(
                scope,
                command_id,
                writer_lease=lease,
                authority_verifier=FreshnessCappedAuthority(),
                required_local_queue_receipt_id=receipt_id,
            )

        persisted = store.read_ctp_dispatch_command(scope, command_id)
        assert persisted.status == "READY"
    finally:
        store.close()


def test_writer_lease_expiry_or_bool_during_verification_fails_closed(monkeypatch):
    fixture = _fixture(monkeypatch)
    fixture.adapter._writer_lease.expires_at_ns = True
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    fixture.adapter._writer_lease.expires_at_ns = NOW + 500_000_000
    fixture.clock.values = [NOW, NOW, NOW + 500_000_001, NOW + 500_000_001]
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


def test_verification_after_key_expiry_is_rejected(monkeypatch):
    fixture = _fixture(monkeypatch)
    expires_at_ns = NOW + 1_000_000_000
    fixture.adapter._signature_verifier = authority.PinnedEd25519CtpActionPermitVerifier(
        (replace(fixture.pinned_key, valid_until_ns=expires_at_ns),)
    )
    delayed_now = expires_at_ns + 1
    fixture.clock.values = [delayed_now] * 4

    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=delayed_now)


def test_revocation_epoch_cannot_roll_back_within_verifier_lifetime(monkeypatch):
    fixture = _fixture(monkeypatch)
    fixture.adapter.verify_action(fixture.command, now_ns=NOW)
    permit = _replace_signed_permit(fixture, revocation_epoch=8)
    fixture.revocation_source.snapshot = authority.CtpManagedActionRevocationSnapshot(
        permit_id=permit.permit_id,
        key_id=permit.key_id,
        epoch=8,
        revoked=False,
        key_active=True,
        observed_at_ns=NOW - 1_000_000,
        valid_until_ns=NOW + 2_000_000_000,
        source_digest_sha256="6" * 64,
    )
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: authority.CtpManagedActionPermitV1(
            permit_id="permit.bool.1",
            issuer="issuer.test",
            key_id="key.test.1",
            audience="ctp-i9-store-claim",
            environment="simnow",
            mode="simulation",
            preset="sandbox",
            scope_sha256=HEX_A,
            action_sha256=HEX_B,
            issued_at_ns=True,
            expires_at_ns=NOW + 1,
            revocation_epoch=1,
            fence_id="fence.1",
            fence_epoch=1,
            fence_owner_id="owner.1",
            nonce="nonce.1",
            signature_hex="0" * 128,
        ),
        lambda: authority.CtpManagedActionRevocationSnapshot(
            permit_id="permit.bool.1",
            key_id="key.test.1",
            epoch=True,
            revoked=False,
            key_active=True,
            observed_at_ns=NOW,
            valid_until_ns=NOW + 1,
            source_digest_sha256=HEX_A,
        ),
        lambda: authority.CtpManagedActionWriterFenceSnapshot(
            fence_id="fence.1",
            owner_id="owner.1",
            account_fingerprint_sha256=HEX_A,
            environment="simnow",
            mode="simulation",
            epoch=True,
            observed_at_ns=NOW,
            expires_at_ns=NOW + 1,
            source_digest_sha256=HEX_B,
        ),
    ],
)
def test_bool_is_not_accepted_for_integer_claim_fields(factory):
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        factory()


def test_bool_clock_and_untyped_trust_snapshots_are_rejected(monkeypatch):
    fixture = _fixture(monkeypatch)
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=True)

    fixture = _fixture(monkeypatch)
    fixture.fence_source.snapshot = {"fence_id": "fence.account.1"}
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    fixture.corr.native_request_id = True
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch, operation="CANCEL")
    fixture.corr.native_action_ref = True
    fixture.command.native_request_payload["OrderActionRef"] = True
    fixture.command.native_request_payload_sha256 = _digest(fixture.command.native_request_payload)
    fixture.corr.native_request_payload_sha256 = fixture.command.native_request_payload_sha256
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    fixture.resolver.value = {"mode": "simulation", "preset": "sandbox"}
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


def test_writer_lease_and_current_store_session_are_required(monkeypatch):
    fixture = _fixture(monkeypatch)
    fixture.store.assert_writer_lease = lambda scope, lease: (_ for _ in ()).throw(RuntimeError())
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    fixture.command.session_binding["session_generation_id"] = "different"
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)

    fixture = _fixture(monkeypatch)
    stored = FakeCommand(**vars(fixture.command))
    stored.authority_binding_sha256 = "7" * 64
    fixture.store.command = stored
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        fixture.adapter.verify_action(fixture.command, now_ns=NOW)


def test_default_factory_is_rejecting_and_constructor_rejects_bool_verifier(monkeypatch):
    verifier = authority.default_ctp_managed_action_authority_verifier()
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        verifier.verify_action(object(), now_ns=NOW)
    fixture = _fixture(monkeypatch)
    with pytest.raises(authority.CtpManagedActionAuthorityError):
        authority.CtpManagedActionAuthorityAdapter(
            store=fixture.store,
            scope=EXECUTION_SCOPE,
            owner_handle=OWNER,
            writer_lease=WRITER_LEASE,
            scope_resolver=fixture.resolver,
            permit_source=fixture.permit_source,
            signature_verifier=lambda *_args, **_kwargs: True,
            revocation_source=fixture.revocation_source,
            fence_source=fixture.fence_source,
            trusted_clock=fixture.clock,
        )
