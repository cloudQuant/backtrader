"""65.01 current local parent-lease behavior, not a production recovery contract.

Only fresh temporary SQLite journals and synthetic identities/ports are used.
The raw SqliteExecutionStore cases are distinct from the factory-bound
open_ctp_account_store case. The latter does not establish an independent
cross-process flow lock or prove real single-writer exclusivity. None of these
assertions proves real authorization, Gateway dispatch, native CTP behavior,
or a future service's restart behavior.
"""

from hashlib import sha256
import json
from pathlib import Path
import time

import pytest

import bt_api_base
import bt_api_execution
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_execution.contracts import ExecutionScope
from bt_api_execution.errors import ContractValidationError, DurableStoreError, InvalidStateTransition
from bt_api_execution.parent_authority import ParentAuthority
from bt_api_execution.store import SqliteExecutionStore


WORKSPACE = Path(__file__).resolve().parents[3]
SYNTHETIC_ACCOUNT = "ctp-account-ref.v1:" + sha256(b"iter65-isolated-fixture").hexdigest()
DAY = "20261109"
TABLES_WITHOUT_LEGACY_WRITES = (
    "execution_outbox",
    "cancellation_outbox",
    "ctp_order_identity_reservations",
    "ctp_order_ref_watermarks",
    "ctp_order_ref_account_watermarks",
    "ctp_dispatch_commands",
)


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    for module in (bt_api_base, bt_api_execution):
        assert Path(module.__file__).resolve().is_relative_to(WORKSPACE)


class SyntheticGateway:
    """In-memory port; not an authenticated Gateway or a provider call."""

    def __init__(self):
        self.calls = []

    def register_parent(self, spec, operation_id):
        self.calls.append((spec["parent_ref"], operation_id))
        return {"state": "ACCEPTED"}

    def verify(self, response, spec, operation_id):
        return response["state"]


def make_spec(scope):
    instrument = MarketInstrumentKey("ctp", "SHFE", "synthetic", "future", "rb", "rb")
    return {
        "parent_ref": "synthetic-parent", "registration_operation_id": "synthetic-register",
        "risk_operation_id": "synthetic-risk", "account_scope": scope.account_ref,
        "strategy_scope": scope.strategy_id, "execution_domain_ref": "synthetic-domain",
        "instrument": instrument.to_dict(), "quantity": "5", "quantity_unit": "lots",
        "side": "buy", "offset": "open", "limit_price": "10",
        "creation_trading_day": DAY, "allowed_trading_days": [DAY],
        "expires_at_ns": time.time_ns() + 60_000_000_000, "grant_revision": "synthetic-grant",
        "plan_digest": "a" * 64, "plan_version": "v1", "target_position_ref": None,
        "risk_selected": False, "time_in_force": "DAY",
    }


def counts(store):
    # Assert each actual table exists, then compare row counts around the parent
    # operations rather than interpreting empty schema as absent functionality.
    return {
        table: store._connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        for table in TABLES_WITHOUT_LEGACY_WRITES
    }


def test_ctp_parent_data_survives_but_public_family_owner_cannot_be_reacquired(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-execution.sqlite"
    scope = ExecutionScope("ctp", "simulation", SYNTHETIC_ACCOUNT, "synthetic-strategy", DAY)
    def forbid_native_identity(*_args, **_kwargs):
        raise AssertionError("this prototype must not reserve a CTP order identity")
    monkeypatch.setattr(SqliteExecutionStore, "reserve_ctp_order_identity", forbid_native_identity)
    store = SqliteExecutionStore(path)
    gateway = SyntheticGateway()
    try:
        family = store.acquire_ctp_account_family_owner(scope)
        lease = store.acquire_or_renew_lease(
            scope, "synthetic-writer", ttl_ns=300_000_000_000, ctp_account_family_owner=family
        )
        # Always-true fixture makes no claim about actual account authentication.
        authority = ParentAuthority(store, scope, lease, admission=lambda action, value: True, gateway=gateway)
        before = counts(store)
        accepted = authority.accept(make_spec(scope))
        assert accepted["gateway_state"] == "PENDING"
        assert authority.register("synthetic-parent")["gateway_state"] == "ACCEPTED"
        child = authority.prepare_child("synthetic-parent", {
            "child_id": "synthetic-child", "request_key": "synthetic-request", "trading_day": DAY,
            "offset": "open", "quantity": "3", "payload_digest": "b" * 64,
        })
        assert child["state"] == "PREPARED"
        assert authority.get("synthetic-parent")["gateway_state"] == "ACCEPTED"
        assert gateway.calls == [("synthetic-parent", "synthetic-register")]
        assert counts(store) == before
    finally:
        store.close()

    reopened = SqliteExecutionStore(path)
    try:
        # This checks durable raw rows, not successful authenticated recovery.
        parent = reopened._connection.execute(
            "SELECT request_json, gateway_state FROM execution_parent_records WHERE parent_id=?",
            ("synthetic-parent",),
        ).fetchone()
        child = reopened._connection.execute(
            "SELECT request_json, state FROM execution_parent_children WHERE parent_id=? AND child_id=?",
            ("synthetic-parent", "synthetic-child"),
        ).fetchone()
        assert parent["gateway_state"] == "ACCEPTED"
        assert json.loads(parent["request_json"])["account_scope"] == SYNTHETIC_ACCOUNT
        assert child["state"] == "PREPARED"
        assert json.loads(child["request_json"])["quantity"] == "3"
        assert counts(reopened) == before
        with pytest.raises(InvalidStateTransition, match="already has a persistent owner"):
            reopened.acquire_ctp_account_family_owner(scope)
        with pytest.raises(InvalidStateTransition, match="owner must precede the writer lease"):
            reopened.acquire_or_renew_lease(scope, "synthetic-writer", ttl_ns=300_000_000_000)
        with pytest.raises(ContractValidationError, match="exact same-Store"):
            reopened.acquire_or_renew_lease(
                scope, "synthetic-writer", ttl_ns=300_000_000_000, ctp_account_family_owner=family
            )
    finally:
        reopened.close()


def test_fake_scope_control_can_reopen_with_original_writer(tmp_path):
    """A non-CTP fixture is a comparison, not evidence of CTP recovery."""
    path = tmp_path / "synthetic-fake.sqlite"
    scope = ExecutionScope("fake", "offline", "synthetic-account", "synthetic-strategy", DAY)
    gateway = SyntheticGateway()
    store = SqliteExecutionStore(path)
    try:
        lease = store.acquire_or_renew_lease(scope, "synthetic-writer", ttl_ns=300_000_000_000)
        authority = ParentAuthority(store, scope, lease, admission=lambda action, value: True, gateway=gateway)
        authority.accept(make_spec(scope))
        authority.register("synthetic-parent")
        authority.prepare_child("synthetic-parent", {
            "child_id": "synthetic-child", "request_key": "synthetic-request", "trading_day": DAY,
            "offset": "open", "quantity": "3", "payload_digest": "b" * 64,
        })
    finally:
        store.close()

    reopened = SqliteExecutionStore(path)
    try:
        lease = reopened.acquire_or_renew_lease(scope, "synthetic-writer", ttl_ns=300_000_000_000)
        authority = ParentAuthority(reopened, scope, lease, admission=lambda action, value: True, gateway=gateway)
        assert authority.get("synthetic-parent")["gateway_state"] == "ACCEPTED"
        child = authority.prepare_child("synthetic-parent", {
            "child_id": "synthetic-child-2", "request_key": "synthetic-request-2", "trading_day": DAY,
            "offset": "open", "quantity": "2", "payload_digest": "c" * 64,
        })
        assert child["state"] == "PREPARED"
    finally:
        reopened.close()


def test_factory_bound_ctp_parent_records_reopen_but_family_owner_is_not_reissued(tmp_path, monkeypatch):
    """Actual local CTP factory plus synthetic ports; no provider or real account."""
    path = tmp_path / "synthetic-factory.sqlite"
    account = "ctp-account-ref.v1:" + sha256(b"iter65-factory-fixture").hexdigest()
    scope = ExecutionScope("ctp", "simulation", account, "synthetic-strategy", DAY)
    def forbid_native_identity(*_args, **_kwargs):
        raise AssertionError("this prototype must not reserve a CTP order identity")
    monkeypatch.setattr(SqliteExecutionStore, "reserve_ctp_order_identity", forbid_native_identity)
    gateway = SyntheticGateway()
    store = SqliteExecutionStore.open_ctp_account_store(path, scope)
    try:
        family = store.acquire_ctp_account_family_owner(scope)
        lease = store.acquire_or_renew_lease(
            scope, "synthetic-writer", ttl_ns=300_000_000_000, ctp_account_family_owner=family
        )
        authority = ParentAuthority(store, scope, lease, admission=lambda action, value: True, gateway=gateway)
        before = counts(store)
        authority.accept(make_spec(scope))
        assert authority.register("synthetic-parent")["gateway_state"] == "ACCEPTED"
        child = authority.prepare_child("synthetic-parent", {
            "child_id": "synthetic-child", "request_key": "synthetic-request", "trading_day": DAY,
            "offset": "open", "quantity": "3", "payload_digest": "b" * 64,
        })
        assert child["state"] == "PREPARED"
        assert counts(store) == before
        identity = store.read_ctp_account_store_identity(scope)
    finally:
        store.close()

    reopened = SqliteExecutionStore.open_ctp_account_store(path, scope)
    try:
        assert reopened.read_ctp_account_store_identity(scope) == identity
        parent = reopened._connection.execute(
            "SELECT request_json, gateway_state FROM execution_parent_records WHERE parent_id=?",
            ("synthetic-parent",),
        ).fetchone()
        child = reopened._connection.execute(
            "SELECT request_json, state FROM execution_parent_children WHERE parent_id=? AND child_id=?",
            ("synthetic-parent", "synthetic-child"),
        ).fetchone()
        assert parent["gateway_state"] == "ACCEPTED"
        assert json.loads(parent["request_json"])["account_scope"] == account
        assert child["state"] == "PREPARED"
        assert json.loads(child["request_json"])["quantity"] == "3"
        assert counts(reopened) == before
        with pytest.raises(InvalidStateTransition, match="already has a persistent owner"):
            reopened.acquire_ctp_account_family_owner(scope)
        with pytest.raises(InvalidStateTransition, match="owner must precede the writer lease"):
            reopened.acquire_or_renew_lease(scope, "synthetic-writer", ttl_ns=300_000_000_000)
    finally:
        reopened.close()

    other_account = "ctp-account-ref.v1:" + sha256(b"iter65-other-factory-fixture").hexdigest()
    other_scope = ExecutionScope("ctp", "simulation", other_account, "synthetic-strategy", DAY)
    with pytest.raises(DurableStoreError, match="account identity does not match"):
        SqliteExecutionStore.open_ctp_account_store(path, other_scope)


def test_fake_scope_same_writer_id_is_shared_by_two_local_stores(tmp_path):
    """Sequential local calls only; this does not test a service's flow lock."""
    path = tmp_path / "synthetic-dual-store.sqlite"
    scope = ExecutionScope("fake", "offline", "synthetic-account", "synthetic-strategy", DAY)
    first = SqliteExecutionStore(path)
    second = None
    try:
        first_lease = first.acquire_or_renew_lease(scope, "synthetic-writer", ttl_ns=300_000_000_000)
        first_authority = ParentAuthority(first, scope, first_lease, admission=lambda action, value: True,
                                          gateway=SyntheticGateway())
        first_authority.accept(make_spec(scope))

        second = SqliteExecutionStore(path)
        second_lease = second.acquire_or_renew_lease(scope, "synthetic-writer", ttl_ns=300_000_000_000)
        assert first_lease.fencing_token == second_lease.fencing_token
        assert first_lease.owner_id == second_lease.owner_id
        second_authority = ParentAuthority(second, scope, second_lease, admission=lambda action, value: True,
                                           gateway=SyntheticGateway())
        second_spec = make_spec(scope)
        second_spec.update(parent_ref="synthetic-parent-2", registration_operation_id="synthetic-register-2",
                           risk_operation_id="synthetic-risk-2")
        second_authority.accept(second_spec)
        assert first_authority.get("synthetic-parent")["gateway_state"] == "PENDING"
        assert second_authority.get("synthetic-parent-2")["gateway_state"] == "PENDING"
    finally:
        if second is not None:
            second.close()
        first.close()
