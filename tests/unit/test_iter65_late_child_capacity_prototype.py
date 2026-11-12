"""Current local capacity behavior under deliberately contradictory test evidence.

The temporary journal and ParentAuthority are real.  The account, admission,
Gateway and evidence are synthetic: the late cumulative fill deliberately
contradicts the earlier test-only assertion that the terminal watermark was
aligned.  No actual Gateway, provider, account or network is involved.  These
assertions describe a baseline, not the intended iteration 65 contract.
"""

from decimal import Decimal
from pathlib import Path
import sys
import time

import pytest

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_execution.contracts import ExecutionScope
from bt_api_execution.errors import IntentConflictError, InvalidStateTransition
from bt_api_execution.parent_authority import ParentAuthority
from bt_api_execution.store import SqliteExecutionStore


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    yield
    root = Path(__file__).resolve().parents[3]
    assert root.name == "wt-iter65"
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(root):
                escaped[name] = source
    assert not escaped, escaped


class SyntheticGateway:
    """Local test port; its result is not an authenticated Gateway receipt."""

    def register_parent(self, _spec, _operation_id):
        return {"state": "ACCEPTED"}

    def verify(self, result, _spec, _operation_id):
        return result["state"]


def open_authority(path):
    scope = ExecutionScope("FAKE", "test", "synthetic-account", "synthetic-strategy", "20261109")
    store = SqliteExecutionStore(path)
    lease = store.acquire_or_renew_lease(scope, "synthetic-writer", ttl_ns=300_000_000_000)
    authority = ParentAuthority(store, scope, lease, admission=lambda _action, _value: True,
                                gateway=SyntheticGateway())
    return store, authority


def parent_spec():
    return {
        "parent_ref": "parent-1", "registration_operation_id": "register-1",
        "risk_operation_id": "risk-1", "account_scope": "synthetic-account",
        "strategy_scope": "synthetic-strategy", "execution_domain_ref": "synthetic-domain",
        "instrument": MarketInstrumentKey("ctp", "SHFE", "synthetic", "future", "rb", "rb").to_dict(),
        "quantity": "5", "quantity_unit": "lots", "side": "buy", "offset": "open",
        "limit_price": "5", "creation_trading_day": "20261109", "allowed_trading_days": ["20261109"],
        "expires_at_ns": time.time_ns() + 60_000_000_000, "grant_revision": "synthetic-grant",
        "plan_digest": "a" * 64, "plan_version": "v1", "target_position_ref": None,
        "risk_selected": False, "time_in_force": "GTD",
    }


def child_spec(child_id, quantity, digest):
    return {"child_id": child_id, "request_key": "request-" + child_id,
            "trading_day": "20261109", "offset": "open", "quantity": quantity,
            "payload_digest": digest * 64}


def evidence(event_id, filled, *, aligned):
    return {"parent_ref": "parent-1", "child_id": "child-1", "event_id": event_id,
            "state": "TERMINAL", "filled_quantity": filled, "watermark_aligned": aligned,
            "source": "synthetic-test-only"}


def child_rows(store):
    return store._connection.execute(
        "SELECT child_id, quantity, filled_quantity, state FROM execution_parent_children "
        "WHERE parent_id=? ORDER BY child_id", ("parent-1",)
    ).fetchall()


def occupied(rows):
    return sum((Decimal(row["filled_quantity"]) if row["state"] == "TERMINAL"
                else Decimal(row["quantity"]) for row in rows), Decimal("0"))


def evidence_count(store):
    return store._connection.execute(
        "SELECT COUNT(*) FROM execution_parent_child_evidence WHERE parent_id=?", ("parent-1",)
    ).fetchone()[0]


def test_late_corrected_terminal_evidence_after_reallocation_is_baseline_only(tmp_path):
    path = tmp_path / "synthetic-parent.sqlite"
    store, authority = open_authority(path)
    first = evidence("terminal-1", "3", aligned=True)
    late = evidence("late-correction-1", "4", aligned=True)
    try:
        authority.accept(parent_spec())
        assert authority.register("parent-1")["gateway_state"] == "ACCEPTED"
        authority.prepare_child("parent-1", child_spec("child-1", "5", "b"))
        authority.claim_child("parent-1", "child-1")

        with pytest.raises(InvalidStateTransition, match="watermark not aligned"):
            authority.observe_child("parent-1", "child-1", evidence("unaligned", "3", aligned=False))
        assert evidence_count(store) == 0

        assert authority.observe_child("parent-1", "child-1", first)["filled_quantity"] == "3"
        assert authority.prepare_child("parent-1", child_spec("child-2", "2", "c"))["state"] == "PREPARED"
        assert occupied(child_rows(store)) == Decimal("5")

        # Deliberate conflicting evidence: a previously aligned terminal cut
        # is followed by a higher cumulative fill.  This is not a claim that a
        # real Gateway or venue supplied either observation.
        result = authority.observe_child("parent-1", "child-1", late)
        assert result["state"] == "TERMINAL" and result["filled_quantity"] == "4"
        assert occupied(child_rows(store)) == Decimal("6")
        with pytest.raises(InvalidStateTransition, match="parent capacity exhausted"):
            authority.prepare_child("parent-1", child_spec("child-3", "1", "d"))
        assert evidence_count(store) == 2
        assert authority.observe_child("parent-1", "child-1", late) == result
        assert evidence_count(store) == 2
        with pytest.raises(IntentConflictError, match="child evidence identity conflict"):
            authority.observe_child("parent-1", "child-1", {**late, "filled_quantity": "5"})
        assert evidence_count(store) == 2

        # This is only a local durable claim: no SDK call or Gateway dispatch
        # is made.  Record whether the already prepared child is rechecked.
        assert authority.claim_child("parent-1", "child-2")["child_id"] == "child-2"
        rows = child_rows(store)
        assert rows[1]["state"] == "UNKNOWN"
        assert occupied(rows) == Decimal("6")
    finally:
        store.close()

    reopened, authority = open_authority(path)
    try:
        rows = child_rows(reopened)
        assert [(row["child_id"], row["state"], row["filled_quantity"]) for row in rows] == [
            ("child-1", "TERMINAL", "4"), ("child-2", "UNKNOWN", "0")]
        assert occupied(rows) == Decimal("6")
        assert evidence_count(reopened) == 2
        assert authority.observe_child("parent-1", "child-1", late)["filled_quantity"] == "4"
        assert evidence_count(reopened) == 2
    finally:
        reopened.close()
