"""Pure-local tests for the shared Iteration 23/24/25 mechanical cycle."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

cycle_module = importlib.import_module("examples.ctp_options_simnow_mechanical_cycle")


class FakeOrder:
    def __init__(self, ref, **info):
        self.ref = ref
        self.status = 1
        self._status_name = "Accepted"
        self.info = info

    def getstatusname(self):
        return self._status_name


class FakeBroker:
    def __init__(self):
        self.calls = []
        self._ref = 0

    def _new(self, action, **kwargs):
        self._ref += 1
        order = FakeOrder(self._ref, **kwargs)
        self.calls.append((action, kwargs, order))
        return order

    def buy(self, **kwargs):
        return self._new("buy", **kwargs)

    def sell(self, **kwargs):
        return self._new("sell", **kwargs)

    def cancel(self, order):
        self.calls.append(("cancel", order))
        return order


def snapshot(**changes):
    value = {
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "account_fingerprint": "acct_hash_only",
        "trading_day": "20260911",
        "connection_generation": 1,
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "nonzero_positions": [],
        "active_orders": [],
    }
    value.update(changes)
    return value


def proof():
    base = snapshot()
    semantic = cycle_module._semantic_hash(base)
    return {
        "settlement_verified": True,
        "bundle_preflight": dict(base),
        "reconciliation_rounds": (dict(base), dict(base)),
        "reconciliation_semantic_hashes": (semantic, semantic),
        "execution_authorization": {
            "armed": True,
            "account_fingerprint": "acct_hash_only",
            "connection_generation": 1,
        },
    }


def make_cycle():
    broker = FakeBroker()
    cycle = cycle_module.MechanicalCycle(
        broker=broker,
        owner=object(),
        feeds={"F": object()},
        cycle_id="cycle-23-test",
    )
    cycle.arm(proof())
    cycle.plan_entry(
        [cycle_module.MechanicalLeg("F", "buy", 1000.0, object())],
        intent_id="intent-open",
    )
    return cycle, broker


def native_fill(order, *, cycle_id="cycle-23-test", intent_id="intent-open:open:0"):
    order.status = 4
    order._status_name = "Completed"
    order.info.update(
        execution_cycle_id=cycle_id,
        intent_id=intent_id,
        ctp_order_ref="native-ref",
        front_id=10,
        session_id=20,
        external_order_id="sys-1",
        trade_id="trade-1",
        connection_generation=1,
        execution_fill_source="trade",
    )
    return order


def test_unarmed_cycle_has_no_write_boundary_call():
    broker = FakeBroker()
    cycle = cycle_module.MechanicalCycle(
        broker=broker, owner=object(), feeds={"F": object()}, cycle_id="cycle-unarmed"
    )
    with pytest.raises(cycle_module.MechanicalCycleBlocked, match="CYCLE_NOT_ARMED"):
        cycle.plan_entry([cycle_module.MechanicalLeg("F", "buy", 1, object())], intent_id="i")
    assert broker.calls == []


def test_one_leg_open_close_and_two_round_flat_closes_without_profit_claim():
    cycle, broker = make_cycle()
    opened = cycle.submit_next_entry()
    cycle.on_order_update(native_fill(opened))
    cycle.plan_exit(
        [cycle_module.MechanicalLeg("F", "sell", 1001.0, object())], intent_id="intent-close"
    )
    closed = cycle.submit_next_exit()
    cycle.on_order_update(native_fill(closed, intent_id="intent-close:close:0"))
    cycle.finalize_flat(snapshot(), snapshot())
    assert cycle.state == "CLOSED_FLAT"
    assert [item[0] for item in broker.calls] == ["buy", "sell"]
    assert all("account_fingerprint" not in row for row in cycle.journal)
    assert all("native-ref" not in str(row) for row in cycle.journal)


def test_local_mock_fill_without_native_confirmation_is_not_a_fill():
    cycle, _ = make_cycle()
    order = cycle.submit_next_entry()
    order.status = 4
    order._status_name = "Completed"
    with pytest.raises(
        cycle_module.MechanicalCycleBlocked, match="NATIVE_FILL_IDENTITY_INCOMPLETE"
    ):
        cycle.on_order_update(order)
    assert cycle.state == "RECOVERY_REQUIRED"


def test_completed_integer_status_without_execution_fill_source_is_not_native_fill():
    cycle, _ = make_cycle()
    order = cycle.submit_next_entry()
    order.status = 4
    order._status_name = "Completed"
    order.info.update(
        execution_cycle_id="cycle-23-test",
        intent_id="intent-open:open:0",
        ctp_order_ref="native-ref",
        front_id=10,
        session_id=20,
        external_order_id="sys-1",
        trade_id="trade-1",
        connection_generation=1,
    )
    with pytest.raises(
        cycle_module.MechanicalCycleBlocked, match="NATIVE_FILL_IDENTITY_INCOMPLETE"
    ):
        cycle.on_order_update(order)


def test_missing_ctp_alias_is_fail_closed_even_with_trade_source():
    cycle, _ = make_cycle()
    order = cycle.submit_next_entry()
    native_fill(order)
    del order.info["external_order_id"]
    with pytest.raises(
        cycle_module.MechanicalCycleBlocked, match="NATIVE_FILL_IDENTITY_INCOMPLETE"
    ):
        cycle.on_order_update(order)


def test_exit_side_must_match_derived_opposite_entry_side():
    cycle, _ = make_cycle()
    opened = cycle.submit_next_entry()
    cycle.on_order_update(native_fill(opened))
    with pytest.raises(cycle_module.MechanicalCycleBlocked, match="EXIT_PLAN_NOT_EQUIVALENT"):
        cycle.plan_exit(
            [cycle_module.MechanicalLeg("F", "buy", 1001.0, object())],
            intent_id="intent-close",
        )


def test_close_fill_reaches_close_filled_before_flat_reconciliation():
    cycle, _ = make_cycle()
    opened = cycle.submit_next_entry()
    cycle.on_order_update(native_fill(opened))
    cycle.plan_exit(
        [cycle_module.MechanicalLeg("F", "sell", 1001.0, object())],
        intent_id="intent-close",
    )
    closed = cycle.submit_next_exit()
    cycle.on_order_update(native_fill(closed, intent_id="intent-close:close:0"))
    assert cycle.state == "CLOSE_FILLED"
    with pytest.raises(
        cycle_module.MechanicalCycleBlocked, match="FINAL_RECONCILIATION_NOT_SAFE_OR_FLAT"
    ):
        cycle.finalize_flat(snapshot(flat=False), snapshot(flat=False))


@pytest.mark.parametrize("status", ("Partial", "Unknown", "pending_cancel"))
def test_partial_or_unknown_stops_ordinary_opening(status):
    cycle, _ = make_cycle()
    order = cycle.submit_next_entry()
    order.status = 3
    order._status_name = status
    with pytest.raises(cycle_module.MechanicalCycleBlocked, match="PARTIAL_OR_UNKNOWN_FILL"):
        cycle.on_order_update(order)
    assert cycle.state == "RECOVERY_REQUIRED"


def test_cancel_then_late_native_fill_is_recovery_not_reopen():
    cycle, broker = make_cycle()
    order = cycle.submit_next_entry()
    cycle.cancel_pending()
    native_fill(order)
    with pytest.raises(cycle_module.MechanicalCycleBlocked, match="LATE_FILL_AFTER_CANCEL"):
        cycle.on_order_update(order)
    assert cycle.state == "RECOVERY_REQUIRED"
    assert broker.calls[-1][0] == "cancel"


def test_reconnect_stops_even_when_generation_is_unchanged():
    cycle, _ = make_cycle()
    cycle.submit_next_entry()
    with pytest.raises(cycle_module.MechanicalCycleBlocked, match="RECONNECT_REQUIRES_REARM"):
        cycle.reconnect(1)
    assert cycle.state == "RECOVERY_REQUIRED"


def test_arm_rejects_nonflat_or_unstable_proof():
    for bad in (
        {"bundle_preflight": snapshot(flat=False)},
        {"bundle_preflight": snapshot(unknown_intent_count=1, flat=False)},
        {"bundle_preflight": snapshot(evidence_complete=False)},
    ):
        value = proof()
        value.update(bad)
        with pytest.raises(cycle_module.MechanicalCycleBlocked):
            cycle_module.MechanicalCycle(
                broker=FakeBroker(), owner=object(), feeds={"F": object()}, cycle_id="bad"
            ).arm(value)


def test_cycle_has_no_direct_api_or_store_private_boundary():
    source = Path(cycle_module.__file__).read_text(encoding="utf-8")
    assert "._api" not in source
    assert "submit_order" not in source
    assert "cancel_order" not in source
    assert (
        "self.broker.buy" in source
        and "self.broker.sell" in source
        and "self.broker.cancel" in source
    )
