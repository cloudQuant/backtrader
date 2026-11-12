"""65.01 offline observation of existing Gateway controls and parents.

All identities, grants, clocks and rechecks below are synthetic local fixtures.
This exercises the actual SQLite journal, parent authority and control entry
points, without RPC, provider I/O or any claim of real authorization.

The current control cause is not the proposed independent Runtime stop barrier.
These sequential examples do not prove a stop/register/reserve/dispatch race,
dual-lease behavior, durable Runtime intent, execution lease, or transfer fence.
"""

from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from bt_api_base.gateway_delegation_protocol import GatewayDelegatedCommand
from bt_api_base.gateway_direct_protocol import gateway_payload_digest
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_gateway.direct_command_journal import DirectCommandJournalError, GatewayDirectCommandJournal
from bt_api_gateway.direct_control import GatewayDirectControl
from bt_api_gateway.direct_delegation import GatewayDelegateGrant, GatewayDelegationDenied, authorize_delegated_command
from bt_api_gateway.direct_parent_authority import GatewayParentAuthority
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.gateway_order_contract import decode_gateway_order_request

WORKSPACE = Path(__file__).resolve().parents[3]
KEY = MarketInstrumentKey('ctp', 'SHFE', 'synthetic', 'future', 'rb2601', 'rb2601')
IDENTITY = WireIdentity(WireRole.SERVICE, 'synthetic-exec', 'synthetic-actor')


@pytest.fixture(scope='module', autouse=True)
def source_locations():
    yield
    wrong = {}
    for name, module in tuple(sys.modules.items()):
        if name == 'backtrader' or name.startswith(('backtrader.', 'bt_api_py', 'bt_api_')):
            source = getattr(module, '__file__', None)
            if source and not Path(source).resolve().is_relative_to(WORKSPACE):
                wrong[name] = source
    assert not wrong, f'non-worktree modules: {wrong}'


@contextmanager
def fence():
    # Synthetic ACL fence: this is not authentication or a production grant.
    yield


@pytest.fixture
def gateway(tmp_path):
    directory = tmp_path / 'guard'
    directory.mkdir()
    guard = LocalAccountSessionGuard(directory, 'synthetic-account', 'synthetic-owner')
    generation = guard.acquire()
    try:
        journal = GatewayDirectCommandJournal.create(tmp_path / 'journal.sqlite', 'synthetic-account', generation=generation)
        journal.enable_controls(guard)
        journal.enable_strategy_ledger(guard)
        journal.enable_account_extensions(guard)
        journal.enable_parent_authority(guard)
        authority = GatewayParentAuthority(journal, guard, now_ns=lambda: 100,
            trading_day=lambda: '20261109', transfer_completed=lambda db, spec: '0', same_day_only=True)
        yield journal, authority, GatewayDirectControl(journal, guard)
    finally:
        guard.release()


def parent(strategy, name):
    return dict(account_scope='synthetic-account', strategy_scope=strategy, parent_ref=name,
        registration_operation_id='register-' + name, execution_domain_ref='synthetic-domain',
        instrument=KEY.to_dict(), quantity='10', quantity_unit='lots', side='buy', offset='open',
        limit_price='100', creation_trading_day='20261109', allowed_trading_days=['20261109'],
        expires_at_ns=1000, grant_revision='v1', target_position_ref=None,
        plan_digest='a' * 64, plan_version='v1', time_in_force='GTD')


def register(authority, strategy, name):
    return authority.register_parent(parent(strategy, name), principal='synthetic-exec',
        actor_ref='synthetic-actor', fence=fence, recheck=lambda: True)


def delegated(authority, strategy, parent_name, name, operation='direct.reserve'):
    payload = OrderRequest(symbol='rb2601', side=Side.BUY, order_type=OrderType.LIMIT,
        quantity=Decimal('1'), account_id='synthetic-account', client_order_id=name,
        price=Decimal('100'), idempotency_key=name, quantity_unit='lots', offset='open',
        exchange_id='SHFE').to_dict()
    decode_gateway_order_request(payload, 'synthetic-account')
    cmd = GatewayDelegatedCommand('synthetic-account', strategy, 'synthetic-domain',
        'synthetic-exec', 'synthetic-actor', 'execution', 'synthetic-run', name,
        gateway_payload_digest(payload), KEY, 'v1', parent_name, name)
    grant = GatewayDelegateGrant(IDENTITY, 'synthetic-account', strategy, 'synthetic-domain',
        'execution', 'v1', frozenset({KEY}), frozenset({'direct.reserve', 'direct.dispatch'}))
    context = SimpleNamespace(identity=IDENTITY,
        scope=WireScope('synthetic-domain', account_ref='synthetic-account',
                        strategy_ref=strategy, run_id='synthetic-run'),
        principal_ref='synthetic-exec', registration_id='synthetic-registration')
    permit = authorize_delegated_command(context, grant, cmd, operation, payload,
        registry_recheck=lambda _: True, current_grant=lambda: grant,
        instrument_recheck=lambda _: True, parent_recheck=authority.recheck_child)
    return payload, permit


def child(journal, authority, strategy, parent_name, name):
    payload, permit = delegated(authority, strategy, parent_name, name)
    return journal.reserve(strategy, name, 'synthetic-exec', payload,
                           reservation_fence=fence, delegation_permit=permit)


@pytest.mark.parametrize('mode', ['STOP_NEW', 'FREEZE', 'DRAIN'])
def test_existing_strategy_cause_blocks_child_but_not_parent_registration(gateway, mode):
    journal, authority, control = gateway
    cause = control.apply('cause', mode, scope_kind='strategy', scope_value='strategy-a', origin='operator')
    # Observation: the current register entry point accepts a new ACTIVE parent
    # after the cause; the child reserve transaction independently rejects it.
    assert register(authority, 'strategy-a', 'parent-a')['state'] == 'ACTIVE'
    with pytest.raises(DirectCommandJournalError, match='CONTROL_' + mode):
        child(journal, authority, 'strategy-a', 'parent-a', 'blocked-child')
    with pytest.raises(DirectCommandJournalError, match='NOT_FOUND'):
        journal.get('strategy-a', 'blocked-child', 'synthetic-exec')
    assert register(authority, 'strategy-b', 'parent-b')['state'] == 'ACTIVE'
    assert child(journal, authority, 'strategy-b', 'parent-b', 'other-child').status == 'RESERVED'
    released = control.resume('cause', expected_version=cause['version'], operation_id='resume')
    assert released['active'] == 0 and released['version'] == 2
    assert child(journal, authority, 'strategy-a', 'parent-a', 'after-resume').status == 'RESERVED'


def test_independent_causes_and_versioned_release(gateway):
    journal, authority, control = gateway
    register(authority, 'strategy-a', 'parent-a')
    control.apply('lease-cause', 'DRAIN', scope_kind='strategy', scope_value='strategy-a', origin='system')
    control.apply('operator-cause', 'FREEZE', scope_kind='strategy', scope_value='strategy-a', origin='operator')
    with pytest.raises(DirectCommandJournalError, match='CONTROL_VERSION_CONFLICT'):
        control.resume('lease-cause', expected_version=2, operation_id='stale-resume')
    control.resume('lease-cause', expected_version=1, operation_id='resume-lease')
    with pytest.raises(DirectCommandJournalError, match='CONTROL_FREEZE'):
        child(journal, authority, 'strategy-a', 'parent-a', 'still-blocked')
    control.resume('operator-cause', expected_version=1, operation_id='resume-operator')
    assert child(journal, authority, 'strategy-a', 'parent-a', 'unblocked').status == 'RESERVED'


def test_cancelled_parent_does_not_revive_when_control_is_released(gateway):
    journal, authority, control = gateway
    register(authority, 'strategy-a', 'parent-a')
    existing = child(journal, authority, 'strategy-a', 'parent-a', 'existing-child')
    control.apply('drain', 'DRAIN', scope_kind='strategy', scope_value='strategy-a', origin='operator')
    cancelled = authority.cancel_parent('synthetic-account', 'strategy-a', 'parent-a',
        'register-parent-a', 'cancel-parent-a', 1, principal='synthetic-exec',
        actor_ref='synthetic-actor', fence=fence, recheck=lambda: True)
    assert cancelled['state'] == 'CANCEL_REQUESTED'
    assert [(t['child_id'], t['phase']) for t in cancelled['targets']] == [('existing-child', 'RELEASE_PENDING')]
    control.resume('drain', expected_version=1, operation_id='resume-drain')
    with pytest.raises(GatewayDelegationDenied):
        child(journal, authority, 'strategy-a', 'parent-a', 'after-cancel')
    assert journal.get('strategy-a', 'existing-child', 'synthetic-exec') == existing


def test_reservation_preceding_cause_stays_dispatch_blocked_after_release(gateway):
    journal, authority, control = gateway
    register(authority, 'strategy-a', 'parent-a')
    existing = child(journal, authority, 'strategy-a', 'parent-a', 'existing-child')
    _, permit = delegated(authority, 'strategy-a', 'parent-a', 'existing-child', 'direct.dispatch')
    control.apply('drain', 'DRAIN', scope_kind='strategy', scope_value='strategy-a', origin='operator')
    control.resume('drain', expected_version=1, operation_id='resume-drain')
    with pytest.raises(DirectCommandJournalError, match='CONTROL_PREVIOUSLY_BLOCKED'):
        journal.begin_dispatch(existing.strategy_scope, existing.request_key, existing.reservation_id,
            existing.digest, existing.principal, existing.version, {'ref': 'synthetic-native'},
            ('synthetic-key',), delegation_permit=permit, delegation_fence=fence)
    assert journal.get('strategy-a', 'existing-child', 'synthetic-exec') == existing
