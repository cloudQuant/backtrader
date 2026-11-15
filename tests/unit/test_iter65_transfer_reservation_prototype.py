"""65.01 observation of the transfer-completed callback, not a target contract.

The pending transfer is only a test fixture; Gateway has no corresponding
transfer API or persisted pending transfer in this test. The local authority,
transaction and journal are real; account, identity, grant and fence are
synthetic. No provider, network, real account or concurrent request is used.
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


@pytest.fixture
def environment(tmp_path):
    guard_dir = tmp_path / 'guard'
    guard_dir.mkdir()
    guard = LocalAccountSessionGuard(guard_dir, 'synthetic-account', 'synthetic-owner')
    generation = guard.acquire()
    try:
        journal = GatewayDirectCommandJournal.create(
            tmp_path / 'gateway.sqlite', 'synthetic-account', generation=generation)
        journal.enable_controls(guard)
        journal.enable_strategy_ledger(guard)
        journal.enable_account_extensions(guard)
        journal.enable_parent_authority(guard)
        # `pending_status` and `pending_quantity` model only another component's
        # hypothetical state. They do not create a Gateway transfer reservation.
        transfer = {'pending_status': None, 'pending_quantity': '0', 'completed': '0'}
        authority = GatewayParentAuthority(
            journal, guard, now_ns=lambda: 100, trading_day=lambda: '20261109',
            transfer_completed=lambda db, spec: transfer['completed'], same_day_only=True)
        spec = dict(account_scope='synthetic-account', strategy_scope='synthetic-strategy',
                    parent_ref='synthetic-parent', registration_operation_id='synthetic-register',
                    execution_domain_ref='synthetic-domain', instrument=KEY.to_dict(), quantity='10',
                    quantity_unit='lots', side='buy', offset='open', limit_price='100',
                    creation_trading_day='20261109', allowed_trading_days=['20261109'],
                    expires_at_ns=1000, grant_revision='v1', target_position_ref=None,
                    plan_digest='a' * 64, plan_version='v1', time_in_force='GTD')
        assert authority.register_parent(spec, principal='synthetic-exec', actor_ref='synthetic-actor',
                                         fence=synthetic_fence, recheck=lambda: True)['state'] == 'ACTIVE'
        grant = GatewayDelegateGrant(IDENTITY, 'synthetic-account', 'synthetic-strategy',
            'synthetic-domain', 'execution', 'v1', frozenset({KEY}), frozenset({'direct.reserve'}))
        context = SimpleNamespace(identity=IDENTITY, scope=WireScope('synthetic-domain',
            account_ref='synthetic-account', strategy_ref='synthetic-strategy', run_id='synthetic-run'),
            principal_ref='synthetic-exec', registration_id='synthetic-registration')

        def reserve(name, quantity):
            payload = OrderRequest(symbol='rb2601', side=Side.BUY, order_type=OrderType.LIMIT,
                quantity=Decimal(quantity), account_id='synthetic-account', client_order_id=name,
                price=Decimal('100'), idempotency_key=name, quantity_unit='lots',
                offset='open', exchange_id='SHFE').to_dict()
            decode_gateway_order_request(payload, 'synthetic-account')
            command = GatewayDelegatedCommand('synthetic-account', 'synthetic-strategy', 'synthetic-domain',
                'synthetic-exec', 'synthetic-actor', 'execution', 'synthetic-run', name,
                gateway_payload_digest(payload), KEY, 'v1', 'synthetic-parent', name)
            permit = authorize_delegated_command(context, grant, command, 'direct.reserve', payload,
                registry_recheck=lambda _: True, current_grant=lambda: grant,
                instrument_recheck=lambda _: True, parent_recheck=authority.recheck_child)
            return journal.reserve('synthetic-strategy', name, 'synthetic-exec', payload,
                reservation_fence=synthetic_fence, delegation_permit=permit)

        yield transfer, journal, reserve
    finally:
        guard.release()


@pytest.mark.parametrize('pending_status', ['PREPARED', 'UNKNOWN'])
def test_synthetic_pending_transfer_is_not_in_completed_callback(environment, pending_status):
    transfer, journal, reserve = environment
    transfer.update(pending_status=pending_status, pending_quantity='6', completed='0')
    # Current observation only: the real authority receives completed=0 and
    # does not know this in-memory fixture says another six lots are pending.
    assert reserve('child-six', '6').status == 'RESERVED'
    assert journal.get('synthetic-strategy', 'child-six', 'synthetic-exec').status == 'RESERVED'


@pytest.mark.parametrize(('child_quantity', 'accepted'), [('6', False), ('4', True)])
def test_completed_transfer_callback_limits_new_child(environment, child_quantity, accepted):
    transfer, journal, reserve = environment
    transfer.update(pending_status=None, pending_quantity='0', completed='6')
    # Each parameter case gets its own fresh journal and parent of ten lots.
    if accepted:
        assert reserve('child', child_quantity).status == 'RESERVED'
    else:
        with pytest.raises(GatewayDelegationDenied):
            reserve('child', child_quantity)
        with pytest.raises(DirectCommandJournalError, match='NOT_FOUND'):
            journal.get('synthetic-strategy', 'child', 'synthetic-exec')
