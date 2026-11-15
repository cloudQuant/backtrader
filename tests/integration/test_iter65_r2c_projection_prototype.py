"""Offline R2-C identity and scheduling probe, using synthetic provider facts.

The in-process fake provider observations and local SQLite journals do not
establish venue, account, Gateway-service or parent/child authority.  The
existing Broker and SDK consumer are used unchanged; no identity is rewritten.
"""

from decimal import Decimal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import iter60_gateway_execution_support as support


def _facts():
    # Distinct fictional provider order and client IDs, scoped to strategy A.
    return [
        support.order_obs("fake-order-1", "sa-child-1", "open", "0", "1"),
        support.trade_obs("fake-trade-1", "fake-order-1", "1"),
        support.order_obs("fake-order-2", "sa-child-2", "open", "0", "1"),
        support.trade_obs("fake-trade-2", "fake-order-2", "1"),
    ]


def _close(stack):
    binding = stack.broker._gateway_execution_bindings[id(stack.a)]
    binding.consumer.close()
    stack.broker.close_gateway_execution_events()
    stack.broker.close_strategy_notification_recovery()
    stack.ledger.close()


@pytest.mark.parametrize("separate_orders", [False, True])
def test_distinct_child_ids_are_not_automatically_folded_into_parent(tmp_path, separate_orders):
    stack = support.stack(tmp_path, "gateway")
    try:
        if separate_orders:
            orders = [support.place(stack, size=1, client=f"sa-child-{n}") for n in (1, 2)]
        else:
            orders = [support.place(stack, size=2, client="sa-parent")]
        support.cycle(stack)
        baseline = list(stack.received)
        facts = _facts()
        assert [facts[n].order.client_order_id for n in (0, 2)] == ["sa-child-1", "sa-child-2"]
        assert [facts[n].trade.order_id for n in (1, 3)] == ["fake-order-1", "fake-order-2"]
        support.publish(tmp_path / "gateway.sqlite3", facts)
        applied = stack.broker.poll_gateway_execution_events()
        support.cycle(stack)
        binding = stack.broker._gateway_execution_bindings[id(stack.a)]
        assert binding.consumer.checkpoint().cursor == 4
        assert [binding.store.client_for_external(f"fake-order-{n}") for n in (1, 2)] == [
            "sa-child-1", "sa-child-2"
        ]
        state = stack.broker.gateway_execution_events_state(stack.a)
        if separate_orders:
            assert applied == state["applied"] == 4
            assert [order.executed.size for order in orders] == [-1, -1]
            assert support.position(stack) == Decimal("0")
            assert len(stack.received) > len(baseline)
        else:
            assert applied == state["applied"] == 0
            assert state["orphaned"] == 4
            assert orders[0].executed.size == 0
            assert support.position(stack) == Decimal("2")
            assert stack.received == baseline
    finally:
        _close(stack)


@pytest.mark.parametrize("mode", ["direct_active", "gateway_waiting"])
def test_next_returns_before_r2c_poll_in_selected_modes(tmp_path, monkeypatch, mode):
    stack = support.stack(tmp_path, "gateway")
    try:
        parent = support.place(stack, size=2, client="sa-parent")
        support.cycle(stack)
        support.publish(tmp_path / "gateway.sqlite3", _facts())
        if mode == "direct_active":
            # Exercise the actual _direct_active flag and next dispatch; the
            # direct body is replaced only to isolate its scheduling branch.
            stack.broker._direct_on = True
            direct_calls = []
            monkeypatch.setattr(stack.broker, "_direct_next", lambda: direct_calls.append(True))
        else:
            stack.store._gateway_mode = True
            stack.store.is_connected = False
            stack.store.gateway_session_state = lambda: "WAITING"
            stack.broker.cerebro.runningstrats = [stack.a]
        stack.broker.next()
        binding = stack.broker._gateway_execution_bindings[id(stack.a)]
        assert binding.consumer.checkpoint().cursor == 0
        assert stack.broker.gateway_execution_events_state(stack.a)["orphaned"] == 0
        if mode == "direct_active":
            assert direct_calls == [True]
        else:
            assert stack.broker._gateway_waiting_for_session is True
        # Explicit polling is possible here and proves the page was waiting.
        assert stack.broker.poll_gateway_execution_events() == 0
        assert binding.consumer.checkpoint().cursor == 4
        assert stack.broker.gateway_execution_events_state(stack.a)["orphaned"] == 4
        assert parent.executed.size == 0
    finally:
        _close(stack)
