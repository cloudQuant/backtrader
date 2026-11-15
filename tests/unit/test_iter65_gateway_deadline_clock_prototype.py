"""65.01 synthetic Gateway wall-clock rollback observation, not a target contract.

Uses a temporary actual Gateway SQLite journal and synthetic account, identity,
authorization callbacks and wall clock. No account, provider or network I/O.
The current observation does not prove real clock behavior or establish trading
source, authorization, production readiness or the desired deadline semantics.
"""

from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from bt_api_base.gateway_delegation_protocol import GatewayDelegatedCommand
from bt_api_base.gateway_direct_protocol import gateway_payload_digest
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_gateway.direct_command_journal import DirectCommandJournalError, GatewayDirectCommandJournal
from bt_api_gateway.direct_delegation import GatewayDelegateGrant, GatewayDelegationDenied, authorize_delegated_command
from bt_api_gateway.direct_parent_authority import GatewayParentAuthority
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.gateway_order_contract import decode_gateway_order_request

WORKSPACE = Path(__file__).resolve().parents[3]
KEY = MarketInstrumentKey('ctp', 'SHFE', 'synthetic', 'future', 'rb2601', 'rb2601')
IDENTITY = WireIdentity(WireRole.SERVICE, 'synthetic-exec', 'synthetic-actor')


@pytest.fixture(scope='module', autouse=True)
def isolated_sources():
    yield
    wrong = {}
    for name, module in tuple(sys.modules.items()):
        if name == 'backtrader' or name.startswith(('backtrader.', 'bt_api_py', 'bt_api_')):
            source = getattr(module, '__file__', None)
            if source and not Path(source).resolve().is_relative_to(WORKSPACE):
                wrong[name] = source
    assert not wrong, f'non-worktree modules: {wrong}'


@contextmanager
def synthetic_fence():
    # A local test stub, not authentication or a production account grant.
    yield


def test_deadline_observation_and_child_after_synthetic_clock_rollback(tmp_path):
    guard_dir = tmp_path / 'guard'
    guard_dir.mkdir()
    guard = LocalAccountSessionGuard(guard_dir, 'synthetic-account', 'synthetic-owner')
    generation = guard.acquire()
    try:
        journal = GatewayDirectCommandJournal.create(tmp_path / 'gateway.sqlite',
                                                      'synthetic-account', generation=generation)
        journal.enable_controls(guard)
        journal.enable_strategy_ledger(guard)
        journal.enable_account_extensions(guard)
        journal.enable_parent_authority(guard)
        clock = {'now': 100}
        authority = GatewayParentAuthority(journal, guard, now_ns=lambda: clock['now'],
            trading_day=lambda: '20261109', transfer_completed=lambda db, spec: '0', same_day_only=True)
        access = dict(principal='synthetic-exec', actor_ref='synthetic-actor',
                      fence=synthetic_fence, recheck=lambda: True)
        spec = dict(account_scope='synthetic-account', strategy_scope='synthetic-strategy',
            parent_ref='synthetic-parent', registration_operation_id='synthetic-register',
            execution_domain_ref='synthetic-domain', instrument=KEY.to_dict(), quantity='10',
            quantity_unit='lots', side='buy', offset='open', limit_price='100',
            creation_trading_day='20261109', allowed_trading_days=['20261109'],
            expires_at_ns=1000, grant_revision='v1', target_position_ref=None,
            plan_digest='a' * 64, plan_version='v1', time_in_force='GTD')
        assert authority.register_parent(spec, **access)['state'] == 'ACTIVE'
        args = ('synthetic-account', 'synthetic-strategy', 'synthetic-parent', 'synthetic-register')
        def make_child(name):
            payload = OrderRequest(symbol='rb2601', side=Side.BUY, order_type=OrderType.LIMIT,
                quantity=Decimal('1'), account_id='synthetic-account', client_order_id=name,
                price=Decimal('100'), idempotency_key=name, quantity_unit='lots',
                offset='open', exchange_id='SHFE').to_dict()
            decode_gateway_order_request(payload, 'synthetic-account')
            command = GatewayDelegatedCommand('synthetic-account', 'synthetic-strategy', 'synthetic-domain',
                'synthetic-exec', 'synthetic-actor', 'execution', 'synthetic-run', name,
                gateway_payload_digest(payload), KEY, 'v1', 'synthetic-parent', name)
            return command, payload

        grant = GatewayDelegateGrant(IDENTITY, 'synthetic-account', 'synthetic-strategy',
            'synthetic-domain', 'execution', 'v1', frozenset({KEY}), frozenset({'direct.reserve'}))
        context = SimpleNamespace(identity=IDENTITY, scope=WireScope('synthetic-domain',
            account_ref='synthetic-account', strategy_ref='synthetic-strategy', run_id='synthetic-run'),
            principal_ref='synthetic-exec', registration_id='synthetic-registration')

        def child_is_eligible(command, payload):
            with journal._transaction() as db:
                return authority.recheck_child(db, command, payload)

        def reserve(command, payload):
            permit = authorize_delegated_command(context, grant, command, 'direct.reserve', payload,
                registry_recheck=lambda _: True, current_grant=lambda: grant,
                instrument_recheck=lambda _: True, parent_recheck=authority.recheck_child)
            return journal.reserve('synthetic-strategy', command.request_key, 'synthetic-exec', payload,
                reservation_fence=synthetic_fence, delegation_permit=permit)

        expired_child, expired_payload = make_child('child-at-expiry')
        assert authority.query_parent(*args, **access)['state'] == 'ACTIVE'
        assert child_is_eligible(expired_child, expired_payload) is True
        clock['now'] = 1000
        assert authority.query_parent(*args, **access)['state'] == 'EXPIRED'
        assert child_is_eligible(expired_child, expired_payload) is False
        with pytest.raises(GatewayDelegationDenied):
            reserve(expired_child, expired_payload)
        with pytest.raises(DirectCommandJournalError, match='NOT_FOUND'):
            journal.get('synthetic-strategy', 'child-at-expiry', 'synthetic-exec')
        # Query expiration is currently a projection: the durable row stays ACTIVE.
        with journal._transaction() as db:
            assert db.execute('SELECT state FROM direct_execution_parents WHERE parent_ref=?',
                              ('synthetic-parent',)).fetchone()['state'] == 'ACTIVE'
        clock['now'] = 999
        assert authority.query_parent(*args, **access)['state'] == 'ACTIVE'
        rollback_child, rollback_payload = make_child('child-after-rollback')
        assert child_is_eligible(rollback_child, rollback_payload) is True

        # Confirm the real reserve path also admits this synthetic child after
        # rollback, with explicitly synthetic grant and currentness callbacks.
        row = reserve(rollback_child, rollback_payload)
        assert row.status == 'RESERVED'
    finally:
        guard.release()
