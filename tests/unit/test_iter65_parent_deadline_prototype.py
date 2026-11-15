"""Local deadline observations, using a synthetic parent clock and fake ports.

This does not establish clock, trading-day, grant, or provider authority.  The
SQLite writer lease uses the store's real clock, independently of the parent
module's synthetic clock.
"""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import backtrader
import bt_api_py
import bt_api_base
import bt_api_execution
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_execution.contracts import ExecutionScope
from bt_api_execution.errors import (
    ContractValidationError,
    IntentConflictError,
    InvalidStateTransition,
)
from bt_api_execution import parent_authority
from bt_api_execution.parent_authority import ParentAuthority
from bt_api_execution.store import SqliteExecutionStore


pytestmark = pytest.mark.skip(reason=(
    "RETIRED iteration-65 prototype: it models deadline handling on the pre-continuity "
    "SDK parent-origin contract that no longer exists. ParentAuthority keeps Gateway "
    "registration local (PENDING) while _gateway_continuity_proven() is False, so the "
    "register/child paths it exercises are unreachable; the SDK's own iter65 "
    "origin/vertical tests cover the current seam. Rebuilding it here would fabricate "
    "an unproven continuity anchor."
))


@pytest.fixture(autouse=True)
def workspace_module_sources():
    """Check the actual test process, including modules loaded by each test."""
    root = Path(__file__).resolve().parents[3]
    # The workspace holds this repository and the sibling SDK checkout.
    assert (root / 'backtrader').is_dir() and (root / 'bt_api_py').is_dir()

    def check():
        for required in (backtrader, bt_api_py, bt_api_base, bt_api_execution):
            assert Path(required.__file__).resolve().is_relative_to(root)
        for name, module in tuple(sys.modules.items()):
            if not (name == 'backtrader' or name.startswith('backtrader.') or
                    name == 'bt_api' or name.startswith('bt_api.') or
                    name.startswith('bt_api_')):
                continue
            paths = []
            if getattr(module, '__file__', None):
                paths.append(module.__file__)
            paths.extend(getattr(module, '__path__', ()))
            for path in paths:
                assert Path(path).resolve().is_relative_to(root), (name, path)

    check()
    yield
    check()


class SyntheticClock:
    now_ns = 1_000

    def time_ns(self):
        return self.now_ns


class GatewayStub:
    def __init__(self):
        self.calls = []

    def register_parent(self, spec, operation_id):
        self.calls.append((spec['parent_ref'], operation_id))
        return {'state': 'ACCEPTED'}

    def verify(self, response, spec, operation_id):
        return response['state']


def make_spec(parent_id='p1'):
    return dict(
        parent_ref=parent_id, registration_operation_id='register-' + parent_id,
        risk_operation_id='risk-' + parent_id, account_scope='a', strategy_scope='s',
        execution_domain_ref='d',
        instrument=MarketInstrumentKey('ctp', 'SHFE', 'simnow', 'future', 'rb', 'rb').to_dict(),
        quantity='5', quantity_unit='LOT', side='buy', offset='open', limit_price='5',
        creation_trading_day='20261109', allowed_trading_days=['20261109', '20261110'],
        expires_at_ns=2_000, grant_revision='g1', plan_digest='a' * 64,
        plan_version='v1', target_position_ref=None, risk_selected=False, time_in_force='GTD',
    )


def child(child_id='c1'):
    return dict(child_id=child_id, request_key=child_id, trading_day='20261109',
                offset='open', quantity='1', payload_digest='b' * 64)


def open_authority(path, gateway, actions):
    scope = ExecutionScope('FAKE', 'test', 'a', 's', '20261109')
    store = SqliteExecutionStore(path)
    lease = store.acquire_or_renew_lease(scope, 'writer', ttl_ns=300_000_000_000)

    def admission(action, _value):
        actions.append(action)
        return True  # Bounded test stub, not an authorization assertion.

    return store, ParentAuthority(store, scope, lease, admission=admission, gateway=gateway)


@pytest.fixture
def clock(monkeypatch):
    clock = SyntheticClock()
    # Replacing only this module's reference avoids changing store.time.time_ns.
    monkeypatch.setattr(parent_authority, 'time', SimpleNamespace(time_ns=clock.time_ns))
    return clock


def test_expired_replay_conflict_and_persisted_deadline(tmp_path, clock):
    gateway, actions = GatewayStub(), []
    path = tmp_path / 'journal.sqlite'
    store, authority = open_authority(path, gateway, actions)
    spec = make_spec()
    accepted = authority.accept(spec)
    authority.register('p1')
    prepared = authority.prepare_child('p1', child())
    assert gateway.calls == [('p1', 'register-p1')]

    clock.now_ns = spec['expires_at_ns']
    replay = authority.accept(spec)
    assert replay['request_sha256'] == accepted['request_sha256']
    assert json.loads(replay['request_json'])['expires_at_ns'] == 2_000
    with pytest.raises(IntentConflictError):
        authority.accept(dict(spec, expires_at_ns=3_000))
    with pytest.raises(ContractValidationError, match='deadline has expired'):
        authority.accept(make_spec('new'))
    assert authority.prepare_child('p1', child())['request_sha256'] == prepared['request_sha256']
    with pytest.raises(InvalidStateTransition, match='child authority unavailable'):
        authority.prepare_child('p1', child('new'))
    with pytest.raises(InvalidStateTransition, match='child dispatch fenced'):
        authority.claim_child('p1', 'c1')
    assert gateway.calls == [('p1', 'register-p1')]
    store.close()

    store, authority = open_authority(path, gateway, actions)
    assert json.loads(authority.get('p1')['request_json'])['expires_at_ns'] == 2_000
    assert authority.accept(spec)['request_sha256'] == accepted['request_sha256']
    with pytest.raises(InvalidStateTransition, match='child dispatch fenced'):
        authority.claim_child('p1', 'c1')
    assert gateway.calls == [('p1', 'register-p1')]
    store.close()


def test_pending_registration_after_deadline_and_clock_rollback(tmp_path, clock):
    gateway, actions = GatewayStub(), []
    path = tmp_path / 'journal.sqlite'
    store, authority = open_authority(path, gateway, actions)
    spec = make_spec()
    authority.accept(spec)
    clock.now_ns = 2_001
    with pytest.raises(InvalidStateTransition, match='registration prerequisite missing'):
        authority.register('p1')
    assert gateway.calls == []
    store.close()

    store, authority = open_authority(path, gateway, actions)
    with pytest.raises(InvalidStateTransition, match='registration prerequisite missing'):
        authority.register('p1')
    assert gateway.calls == []
    # GAP: current local check has no persisted high-water clock fence.
    clock.now_ns = 1_999
    assert authority.register('p1')['gateway_state'] == 'ACCEPTED'
    assert gateway.calls == [('p1', 'register-p1')]
    assert json.loads(authority.get('p1')['request_json'])['expires_at_ns'] == 2_000
    store.close()


def test_child_after_deadline_and_clock_rollback(tmp_path, clock):
    gateway, actions = GatewayStub(), []
    store, authority = open_authority(tmp_path / 'journal.sqlite', gateway, actions)
    authority.accept(make_spec())
    authority.register('p1')
    authority.prepare_child('p1', child())
    clock.now_ns = 2_001
    before = list(actions)
    with pytest.raises(InvalidStateTransition, match='child authority unavailable'):
        authority.prepare_child('p1', child('new'))
    with pytest.raises(InvalidStateTransition, match='child dispatch fenced'):
        authority.claim_child('p1', 'c1')
    assert actions == before  # Expiry short-circuits both child admission calls.
    clock.now_ns = 1_999
    # GAP: rollback permits local preparation/claim; claim is not provider dispatch.
    assert authority.prepare_child('p1', child('new'))['state'] == 'PREPARED'
    assert authority.claim_child('p1', 'c1') == child()
    assert actions[-2:] == ['child', 'dispatch_child']
    assert gateway.calls == [('p1', 'register-p1')]
    store.close()
