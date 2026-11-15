"""Offline control/marker ordering with the real Gateway claim coordinator.

The coverage seal, account, identities, authorization and provider are all
synthetic. The injected same-thread interleaving does not prove that an owner
normally schedules control RPCs during dispatch. No venue call occurs.
"""

from contextlib import contextmanager
from pathlib import Path
import sys
import time

import pytest

from bt_api_base.direct_write_protocol import NativeOrderIdentity, PreDispatchRecord, WriteOperation
from bt_api_gateway.direct_dispatch import DirectDispatchError, GatewayDirectDispatcher
from bt_api_py.gateway_dispatch_claim import (
    DispatchClaimError,
    GATEWAY_DISPATCH_COVERAGE,
    GatewayDispatchClaimCoordinator,
    GatewayJournalDispatchChangePort,
    GatewayNativeDispatchClaimPort,
    seal_gateway_dispatch_coverage,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_iter65_stop_barrier_prototype import child, delegated, gateway, register


@pytest.fixture(scope='module', autouse=True)
def worktree_sources():
    yield
    workspace = Path(__file__).resolve().parents[3]
    assert workspace.name == 'wt-iter65'
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == 'backtrader' or name.startswith(('backtrader.', 'bt_api_py', 'bt_api_')):
            source = getattr(module, '__file__', None)
            if source and not Path(source).resolve().is_relative_to(workspace):
                escaped[name] = source
    assert not escaped, escaped


@contextmanager
def _request_fence(_row):
    # Test-only substitute, not a Registry or authority proof.
    yield lambda: None


def _epochs(claims):
    snapshot = claims.capture()
    try:
        return {name: (epoch, status) for name, epoch, status in snapshot.versions}
    finally:
        claims.discard_snapshot(snapshot)


@pytest.mark.parametrize('mode', ['STOP_NEW', 'FREEZE', 'DRAIN'])
@pytest.mark.parametrize('placement', ['before_marker', 'after_marker', 'after_marker_expired'])
def test_control_order_against_real_claim(gateway, monkeypatch, mode, placement):
    journal, authority, control = gateway
    claims, sealer = GatewayDispatchClaimCoordinator.with_coverage_sealer(
        journal.account_scope, journal.generation,
    )
    journal.install_dispatch_change_port(guard=control._guard, port=GatewayJournalDispatchChangePort(claims))
    # These labels are asserted by the test only; no real writer coverage is claimed.
    synthetic_wired = frozenset(label for labels in GATEWAY_DISPATCH_COVERAGE.values() for label in labels)
    seal_gateway_dispatch_coverage(claims, sealer, wired=synthetic_wired)
    register(authority, 'strategy-a', 'parent-a')
    row = child(journal, authority, 'strategy-a', 'parent-a', 'child-a')
    _, permit = delegated(authority, 'strategy-a', 'parent-a', 'child-a', 'direct.dispatch')
    claim_port = GatewayNativeDispatchClaimPort(claims, journal_id='synthetic-journal')
    observed = []

    def inject_control():
        before = _epochs(claims)
        control.apply('cause', mode, scope_kind='strategy', scope_value='strategy-a', origin='operator')
        after = _epochs(claims)
        for domain in ('parent_facts', 'control'):
            assert before[domain][1] == after[domain][1] == 'READY'
            assert after[domain][0] > before[domain][0]
        observed.append('control-committed')

    def fake_provider(payload, port, account):
        identity = NativeOrderIdentity('CTP', 'synthetic-child', {'trading_day': '20261109'}, 1)
        record = PreDispatchRecord(
            WriteOperation.PLACE, account, 'CTP', payload['symbol'], identity, None,
            payload, '20261109', 1, 'synthetic-created-at',
        )
        if placement == 'before_marker':
            inject_control()  # claim already issued, but marker not committed
            try:
                port.commit(record)
            except Exception as error:
                observed.append(('marker-refused', getattr(error, 'code', None)))
            return None
        marker = port.commit(record)
        assert marker == row.reservation_id
        observed.append('marker-committed')
        inject_control()  # test-only reentrant call, not a real owner RPC schedule
        with port.native_fence() as check:
            if placement == 'after_marker_expired':
                real_clock = time.monotonic_ns
                with monkeypatch.context() as local_patch:
                    local_patch.setattr(time, 'monotonic_ns', lambda: real_clock() + 3_000_000_000)
                    with pytest.raises(DispatchClaimError, match='DISPATCH_CLAIM_EXPIRED'):
                        check()
                observed.append('age-check-refused')
            else:
                assert check() is True
                observed.append('fake-handler-reached')
        return None  # no provider receipt; UNKNOWN rather than fabricated success

    dispatcher = GatewayDirectDispatcher(
        journal, 'CTP', control._guard, fake_provider,
        lambda _identity: ('synthetic-native-key',), lambda _row: True, claim_port=claim_port,
    )
    try:
        arguments = (row.strategy_scope, row.request_key, row.principal, row.reservation_id,
                     row.digest, row.version)
        if placement == 'before_marker':
            with pytest.raises(DirectDispatchError, match='PRE_DISPATCH_FAILED'):
                dispatcher.dispatch(*arguments, request_fence=_request_fence, delegation_permit=permit)
            current = journal.get(row.strategy_scope, row.request_key, row.principal)
            assert observed == ['control-committed', ('marker-refused', 'CONTROL_PREVIOUSLY_BLOCKED')]
            assert current.status == 'RESERVED' and current.native_identity_json is None
            assert control.targets('cause') == ()
        else:
            result = dispatcher.dispatch(*arguments, request_fence=_request_fence, delegation_permit=permit)
            tail = 'age-check-refused' if placement == 'after_marker_expired' else 'fake-handler-reached'
            assert observed == ['marker-committed', 'control-committed', tail]
            assert result.status == 'UNKNOWN'
            targets = control.targets('cause')
            assert [(target['reservation_id'], target['state']) for target in targets] == (
                [(row.reservation_id, 'PENDING')] if mode == 'DRAIN' else []
            )
        assert claims.capacity_status()['commands'] == 0
    finally:
        claims.close()
