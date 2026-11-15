"""65.01 offline probe of existing controls around the dispatch marker.

All identity, authority and native activity here are synthetic.  This is not
the proposed Runtime normal-stop barrier, a real account or a provider test.
"""

from contextlib import contextmanager
from pathlib import Path
import sys

import pytest

from bt_api_base.direct_write_protocol import NativeOrderIdentity, PreDispatchRecord, WriteOperation
from bt_api_gateway.direct_command_journal import DirectCommandJournalError
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_iter65_stop_barrier_prototype import child, delegated, fence, gateway, register


def _setup(gateway):
    journal, authority, control = gateway
    register(authority, 'strategy-a', 'parent-a')
    row = child(journal, authority, 'strategy-a', 'parent-a', 'child-a')
    _, permit = delegated(authority, 'strategy-a', 'parent-a', 'child-a', 'direct.dispatch')
    return journal, control, row, permit


def _start(journal, row, permit):
    return journal.begin_dispatch(
        row.strategy_scope, row.request_key, row.reservation_id, row.digest,
        row.principal, row.version, {'ref': 'fake-native'}, ('fake-key',),
        delegation_permit=permit, delegation_fence=fence,
    )


def _apply(control, mode):
    return control.apply('cause', mode, scope_kind='strategy',
                         scope_value='strategy-a', origin='operator')


def _blocked(journal, row):
    with journal._transaction() as db:
        return db.execute(
            'SELECT cause_id FROM direct_control_blocked WHERE account=? AND reservation_id=?',
            (journal.account_scope, row.reservation_id),
        ).fetchall()


@pytest.mark.parametrize('mode', ['STOP_NEW', 'FREEZE', 'DRAIN'])
def test_control_before_marker_leaves_reservation_without_marker(gateway, mode):
    journal, control, row, permit = _setup(gateway)
    _apply(control, mode)
    with pytest.raises(DirectCommandJournalError, match='CONTROL_PREVIOUSLY_BLOCKED'):
        _start(journal, row, permit)
    current = journal.get(row.strategy_scope, row.request_key, row.principal)
    assert current.status == 'RESERVED' and current.version == row.version
    assert current.native_identity_json is None and current.strong_identity_keys == ()
    assert [entry['cause_id'] for entry in _blocked(journal, row)] == ['cause']
    assert control.targets('cause') == ()


@pytest.mark.parametrize('mode', ['STOP_NEW', 'FREEZE', 'DRAIN'])
def test_control_after_marker_retains_dispatching_and_drain_target(gateway, mode):
    journal, control, row, permit = _setup(gateway)
    started = _start(journal, row, permit)
    assert started.newly_started and started.record.status == 'DISPATCHING'
    _apply(control, mode)
    current = journal.get(row.strategy_scope, row.request_key, row.principal)
    assert current == started.record and current.version == row.version + 1
    assert current.native_identity_json is not None and current.strong_identity_keys == ('fake-key',)
    assert _blocked(journal, row) == []
    targets = control.targets('cause')
    if mode == 'DRAIN':
        assert [(target['reservation_id'], target['state']) for target in targets] == [
            (row.reservation_id, 'PENDING')
        ]
    else:
        assert targets == ()


class _FakeClaim:
    """Test-only claim; no real expiry, writer coordination, or authorization."""

    def ready(self):
        return True

    def claim_native(self, record, identity, validate):
        validate(0)
        return object()

    def native_check(self, claim):
        return lambda: True

    def retire(self, claim):
        pass


@contextmanager
def _request_fence(_row):
    yield lambda: None


@pytest.mark.parametrize('mode', ['STOP_NEW', 'FREEZE', 'DRAIN'])
def test_injected_control_after_marker_does_not_stop_fake_native_check(gateway, mode):
    journal, control, row, permit = _setup(gateway)
    observed = []

    def fake_provider(payload, port, account):
        identity = NativeOrderIdentity('CTP', 'fake-child-a', {'trading_day': '20261109'}, 1)
        marker = port.commit(PreDispatchRecord(
            WriteOperation.PLACE, account, 'CTP', payload['symbol'], identity, None,
            payload, '20261109', 1, 'fake-created-at',
        ))
        assert marker == row.reservation_id
        assert journal.get(row.strategy_scope, row.request_key, row.principal).status == 'DISPATCHING'
        # Deliberately injected reentrant control models an interleaving at a
        # test seam; it does not establish that the real owner schedules it.
        _apply(control, mode)
        with port.native_fence() as check:
            check()
            observed.append('fake-handler-reached')
        return None  # no claimed provider outcome; dispatcher records UNKNOWN

    dispatcher = GatewayDirectDispatcher(
        journal, 'CTP', control._guard, fake_provider,
        lambda _identity: ('fake-dispatch-key',), lambda _row: True, claim_port=_FakeClaim(),
    )
    result = dispatcher.dispatch(
        row.strategy_scope, row.request_key, row.principal, row.reservation_id,
        row.digest, row.version, request_fence=_request_fence, delegation_permit=permit,
    )
    assert observed == ['fake-handler-reached']
    assert result.status == 'UNKNOWN'
    targets = control.targets('cause')
    assert [(target['reservation_id'], target['state']) for target in targets] == (
        [(row.reservation_id, 'PENDING')] if mode == 'DRAIN' else []
    )
