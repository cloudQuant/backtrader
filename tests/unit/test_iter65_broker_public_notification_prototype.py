"""Current public notification boundary for a synthetic non-venue adjustment.

This is an isolated negative experiment, not an implementation of transfers.
The Gateway host, Broker and Strategy are real, with a temporary journal and
synthetic existing command/RPC fixtures. No new venue event or identity is
fabricated for the attempted adjustment, and no network or account is used.
Calling Order.execute intentionally mutates the in-memory Order; no claim is
made that the attempted operation has no local side effects.
"""

from pathlib import Path
import sys

import pytest

from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.brokers.test_iter63_gateway_stream_consumer import attach
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import ready as ready
from tests.unit.live_state.test_gateway_pending import inputs as inputs


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    yield
    workspace = Path(__file__).resolve().parents[3]
    assert workspace.name == "wt-iter65"
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(workspace):
                escaped[name] = source
    assert not escaped, escaped


def test_public_execution_and_notification_without_event_cannot_project_adjustment(
        state, ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, events=())
    checkpoint = host.load_execution_checkpoint()
    snapshots = host.iter_order_snapshots()
    assert order.executed.size == 0
    assert broker.positions["rb"].size == 0
    assert not strategy._trades and not strategy._orderspending and not strategy.events

    # Public Order.execute mutates the in-memory order; this does not create a
    # verified Gateway event, a virtual transfer identity, or a position fact.
    order.execute(order.data.datetime[0], 0.5, 10, 0, 0, 0, 0.5, 5, 0, 0, 0, 0.5, 10)
    assert order.executed.size == 0.5 and order.status == order.Partial
    broker.notify(order)
    notice = broker.get_notification()
    assert notice is not None and notice.executed.size == 0.5

    # The framework's normal notification entry validates the Gateway binding
    # before changing Strategy trade/notification state. No event was armed.
    with pytest.raises(ValueError, match="NOT_ARMED"):
        strategy._addnotification(notice)
    assert order.executed.size == 0.5  # the earlier public mutation remains
    assert broker.positions["rb"].size == 0
    assert not strategy._trades and not strategy._orderspending and not strategy.events
    assert host.load_execution_checkpoint() == checkpoint
    assert host.iter_order_snapshots() == snapshots
    assert calls["ack"] == []

    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, host._binding)
    assert reopened.load_execution_checkpoint() == checkpoint
    assert reopened.iter_order_snapshots() == snapshots


def test_broker_does_not_implement_public_order_history(ready, inputs, monkeypatch):
    _, broker, _, _, _, _ = attach(ready, inputs, monkeypatch, events=())
    with pytest.raises(NotImplementedError):
        broker.add_order_history([], notify=True)
