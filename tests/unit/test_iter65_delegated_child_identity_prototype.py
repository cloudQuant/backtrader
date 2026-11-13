"""65.01 sequential offline observations of delegated child identity.

The journal and parent authority are real local components; all identities,
registry checks, grants, fences, clock and order data are synthetic. These tests
are not evidence of real admission, Risk, concurrency, dispatch or an account.
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
from bt_api_gateway.direct_delegation import GatewayDelegateGrant, GatewayDelegationDenied, authorize_delegated_command
from bt_api_gateway.direct_parent_authority import GatewayParentAuthority
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.gateway_order_contract import decode_gateway_order_request

WORKSPACE = Path(__file__).resolve().parents[3]
KEY = MarketInstrumentKey('ctp', 'SHFE', 'synthetic', 'future', 'rb2601', 'rb2601')
IDENTITY = WireIdentity(WireRole.SERVICE, 'synthetic-exec', 'synthetic-actor')
ACCOUNT, STRATEGY, DOMAIN = 'synthetic-account', 'synthetic-strategy', 'synthetic-domain'
PARENT, PRINCIPAL = 'synthetic-parent', 'synthetic-exec'


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
    # This fixture is not Registry admission or a real authorization fence.
    yield


def make_authority(journal, guard):
    return GatewayParentAuthority(journal, guard, now_ns=lambda: 100,
        trading_day=lambda: '20261109', transfer_completed=lambda db, spec: '0', same_day_only=True)


@pytest.fixture
def gateway(tmp_path):
    guard_dir = tmp_path / 'guard'
    guard_dir.mkdir()
    guard = LocalAccountSessionGuard(guard_dir, ACCOUNT, 'synthetic-owner')
    generation = guard.acquire()
    try:
        path = tmp_path / 'journal.sqlite'
        journal = GatewayDirectCommandJournal.create(path, ACCOUNT, generation=generation)
        journal.enable_controls(guard)
        journal.enable_strategy_ledger(guard)
        journal.enable_account_extensions(guard)
        journal.enable_parent_authority(guard)
        authority = make_authority(journal, guard)
        spec = dict(account_scope=ACCOUNT, strategy_scope=STRATEGY, parent_ref=PARENT,
            registration_operation_id='register-parent', execution_domain_ref=DOMAIN,
            instrument=KEY.to_dict(), quantity='2', quantity_unit='lots', side='buy', offset='open',
            limit_price='100', creation_trading_day='20261109', allowed_trading_days=['20261109'],
            expires_at_ns=1000, grant_revision='v1', target_position_ref=None,
            plan_digest='a' * 64, plan_version='v1', time_in_force='GTD')
        assert authority.register_parent(spec, principal=PRINCIPAL, actor_ref='synthetic-actor',
            fence=fence, recheck=lambda: True)['state'] == 'ACTIVE'
        yield journal, authority, guard, generation, path
    finally:
        guard.release()


def reopen(gateway):
    journal, _, guard, generation, path = gateway
    reopened = GatewayDirectCommandJournal(path, ACCOUNT, generation=generation,
        expected_journal_id=journal.journal_id, minimum_revision=0, controls_enabled=True,
        strategy_ledger_enabled=True, account_extensions_enabled=True, parent_authority_enabled=True)
    return reopened, make_authority(reopened, guard)


def reserve(journal, authority, child_id, request_key):
    payload = OrderRequest(symbol='rb2601', side=Side.BUY, order_type=OrderType.LIMIT,
        quantity=Decimal('1'), account_id=ACCOUNT, client_order_id=request_key,
        price=Decimal('100'), idempotency_key=request_key, quantity_unit='lots', offset='open',
        exchange_id='SHFE').to_dict()
    decode_gateway_order_request(payload, ACCOUNT)
    command = GatewayDelegatedCommand(ACCOUNT, STRATEGY, DOMAIN, PRINCIPAL, 'synthetic-actor',
        'execution', 'synthetic-run', request_key, gateway_payload_digest(payload), KEY, 'v1', PARENT, child_id)
    grant = GatewayDelegateGrant(IDENTITY, ACCOUNT, STRATEGY, DOMAIN, 'execution', 'v1',
        frozenset({KEY}), frozenset({'direct.reserve', 'direct.dispatch'}))
    context = SimpleNamespace(identity=IDENTITY,
        scope=WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=STRATEGY, run_id='synthetic-run'),
        principal_ref=PRINCIPAL, registration_id='synthetic-registration')
    permit = authorize_delegated_command(context, grant, command, 'direct.reserve', payload,
        registry_recheck=lambda _: True, current_grant=lambda: grant,
        instrument_recheck=lambda _: True, parent_recheck=authority.recheck_child)
    return journal.reserve(STRATEGY, request_key, PRINCIPAL, payload,
        reservation_fence=fence, delegation_permit=permit)


def test_equal_identity_is_reserved_and_replayed_after_reopen(gateway):
    journal, authority, *_ = gateway
    initial = reserve(journal, authority, 'child-a', 'child-a')
    assert initial.status == 'RESERVED'
    journal, authority = reopen(gateway)
    assert journal.get(STRATEGY, 'child-a', PRINCIPAL) == initial
    assert reserve(journal, authority, 'child-a', 'child-a') == initial


def test_unequal_identity_duplicate_child_rejected_and_capacity_preserved(gateway):
    journal, authority, *_ = gateway
    initial = reserve(journal, authority, 'child-a', 'request-a')
    assert initial.status == 'RESERVED'
    journal, authority = reopen(gateway)
    assert reserve(journal, authority, 'child-a', 'request-a') == initial
    with pytest.raises(GatewayDelegationDenied, match='DELEGATION_DENIED'):
        reserve(journal, authority, 'child-a', 'request-b')
    with pytest.raises(DirectCommandJournalError, match='NOT_FOUND'):
        journal.get(STRATEGY, 'request-b', PRINCIPAL)
    second = reserve(journal, authority, 'child-b', 'request-b')
    assert second.status == 'RESERVED' and second.reservation_id != initial.reservation_id
    with pytest.raises(GatewayDelegationDenied, match='DELEGATION_DENIED'):
        reserve(journal, authority, 'child-c', 'request-c')
    with pytest.raises(DirectCommandJournalError, match='NOT_FOUND'):
        journal.get(STRATEGY, 'request-c', PRINCIPAL)
    journal, authority = reopen(gateway)
    assert reserve(journal, authority, 'child-a', 'request-a') == initial
    assert reserve(journal, authority, 'child-b', 'request-b') == second


def test_same_request_different_child_conflicts_after_reopen(gateway):
    journal, authority, *_ = gateway
    initial = reserve(journal, authority, 'child-a', 'request-a')
    journal, authority = reopen(gateway)
    with pytest.raises(DirectCommandJournalError, match='REQUEST_CONFLICT'):
        reserve(journal, authority, 'child-b', 'request-a')
    assert journal.get(STRATEGY, 'request-a', PRINCIPAL) == initial
    # The rejected envelope has not consumed the second unit of parent capacity.
    second = reserve(journal, authority, 'child-b', 'request-b')
    assert second.status == 'RESERVED'
    journal, authority = reopen(gateway)
    assert reserve(journal, authority, 'child-a', 'request-a') == initial
    assert reserve(journal, authority, 'child-b', 'request-b') == second
