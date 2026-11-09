"""Local Submitted intent is durable independently of the execution cursor."""
import pytest

from tests.unit.live_state.conftest import state as state
from tests.unit.live_state.test_gateway_pending import inputs as inputs
from tests.unit.live_state.test_iter63_gateway_order_bootstrap import _snapshot, _upgrade, _v4, data


def test_local_notification_atomic_and_idempotent(state, inputs):
    binding, _, make = inputs
    _v4(state, binding)
    host = _upgrade(state, binding).upgrade_for_local_notifications()
    ref, snapshot = _snapshot()
    snapshot["state"]["orders"]["key-a"]["status"] = 1
    host.save_submitted_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snapshot)
    before = data(state)
    notices = host.local_order_notifications()
    assert notices['key-a']['status'] == 'pending'
    ident = notices['key-a']['notification_id']
    assert len(ident) == 64
    host.save_submitted_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snapshot)
    assert data(state) == before
    assert host.load_execution_checkpoint().applied_sequence == 0
    with pytest.raises(ValueError, match='CONFLICT'):
        host.confirm_local_order_notifications({'key-a': 'a' * 64})
    assert data(state) == before
    host.confirm_local_order_notifications({'key-a': ident})
    assert host.local_order_notifications()['key-a']['status'] == 'confirmed'
    host.confirm_local_order_notifications({'key-a': ident})
    assert host.load_execution_checkpoint().applied_sequence == 0
