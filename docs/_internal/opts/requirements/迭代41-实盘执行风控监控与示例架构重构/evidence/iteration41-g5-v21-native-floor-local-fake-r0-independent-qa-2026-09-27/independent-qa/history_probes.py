from pathlib import Path
import json, tempfile

import test_ctp_dispatch_commands as t
from bt_api_execution import ContractValidationError, DurableStoreError, SqliteExecutionStore as BaseStore

root = Path(tempfile.mkdtemp(prefix='v21-actionref-probes-'))
results = {}

def make(store, label, *, day='20260927'):
    scope = t.ExecutionScope('ctp', 'simulation', t._ctp_account_ref(), 'strategy.qa.' + label, day)
    lease = t._lease(store, scope, owner='outbox-owner')
    _reservation, arguments = t._prepare_v17_cancel(store, scope, lease, label, session_generation_id='qa-session-' + label)
    return scope, lease, arguments

def fake_store(label):
    return t.SqliteExecutionStore(root / (label + '.sqlite3'), fake_native_action_ref_floor=37)

# Default Store cannot allocate after ordinary typed OrderRef seed/projection verifier facts.
base = BaseStore(root / 'base-no-floor.sqlite3')
try:
    scope, lease, args = make(base, 'base')
    try:
        base.stage_ctp_dispatch_command(**args)
    except ContractValidationError as exc:
        assert 'trusted external CTP native ActionRef floor authority is unavailable' in str(exc)
        results['base_seed_and_projection_verifiers'] = 'FAIL_CLOSED_NO_COMMAND'
    else:
        raise AssertionError('default Store unexpectedly allocated without floor authority')
    assert base.read_ctp_dispatch_command(scope, args['command_id']) is None
finally:
    base.close()

# The plan explicitly treats counter > visible allocations as a burned high-water mark.
s = fake_store('burned-highwater')
try:
    scope1, lease1, args1 = make(s, 'burned-one')
    first = s.stage_ctp_dispatch_command(**args1)
    assert first.correlation_key.native_action_ref == 38
    s._connection.execute('UPDATE ctp_native_action_ref_counters SET last_action_ref=39 WHERE account_key=?', (scope1.account_key,))
    scope2, lease2, args2 = make(s, 'burned-two', day='20260928')
    second = s.stage_ctp_dispatch_command(**args2)
    assert second.correlation_key.native_action_ref == 40
    results['counter_ahead_burned_gap'] = {'first':38,'counter_burned':39,'next':40}
finally:
    s.close()

# Counter below a known allocation must fence a new stage.
s = fake_store('counter-below-allocation')
try:
    scope1, lease1, args1 = make(s, 'below-one')
    first = s.stage_ctp_dispatch_command(**args1)
    s._connection.execute('DROP TRIGGER ctp_native_action_ref_counter_monotonic')
    s._connection.execute('UPDATE ctp_native_action_ref_counters SET last_action_ref=37 WHERE account_key=?', (scope1.account_key,))
    scope2, lease2, args2 = make(s, 'below-two', day='20260928')
    try:
        s.stage_ctp_dispatch_command(**args2)
    except DurableStoreError as exc:
        assert 'counter is below allocation history' in str(exc)
        results['counter_below_allocation'] = 'FAIL_CLOSED'
    else:
        raise AssertionError('counter below allocation history was accepted')
    assert s.read_ctp_dispatch_command(scope2, args2['command_id']) is None
finally:
    s.close()

# Missing counter while allocation rows remain must fence.
s = fake_store('missing-counter')
try:
    scope1, lease1, args1 = make(s, 'missing-one')
    s.stage_ctp_dispatch_command(**args1)
    s._connection.execute('DROP TRIGGER ctp_native_action_ref_counter_no_delete')
    s._connection.execute('DELETE FROM ctp_native_action_ref_counters WHERE account_key=?', (scope1.account_key,))
    scope2, lease2, args2 = make(s, 'missing-two', day='20260928')
    try:
        s.stage_ctp_dispatch_command(**args2)
    except DurableStoreError as exc:
        assert 'counter is missing with allocation history' in str(exc)
        results['missing_counter_with_allocations'] = 'FAIL_CLOSED'
    else:
        raise AssertionError('missing counter with allocation rows was accepted')
    assert s.read_ctp_dispatch_command(scope2, args2['command_id']) is None
finally:
    s.close()

# Existing command replay must fail when its immutable ActionRef mapping is absent.
s = fake_store('missing-command-mapping')
try:
    scope, lease, args = make(s, 'map-one')
    staged = s.stage_ctp_dispatch_command(**args)
    s._connection.execute('DROP TRIGGER ctp_native_action_ref_allocations_immutable_delete')
    s._connection.execute('DELETE FROM ctp_native_action_ref_allocations WHERE account_key=? AND command_id=?', (scope.account_key, args['command_id']))
    try:
        s.stage_ctp_dispatch_command(**args)
    except DurableStoreError as exc:
        assert 'ActionRef allocation is missing or mismatched' in str(exc)
        results['replay_without_action_mapping'] = 'FAIL_CLOSED'
    else:
        raise AssertionError('command replay accepted without allocation mapping')
finally:
    s.close()

# Counter rollback is blocked by its monotonicity trigger.
s = fake_store('counter-rollback')
try:
    scope, lease, args = make(s, 'rollback-one')
    s.stage_ctp_dispatch_command(**args)
    try:
        s._connection.execute('UPDATE ctp_native_action_ref_counters SET last_action_ref=37 WHERE account_key=?', (scope.account_key,))
    except Exception as exc:
        assert 'must increment by one' in str(exc)
        results['counter_rollback'] = 'TRIGGER_BLOCKED'
    else:
        raise AssertionError('counter rollback succeeded')
finally:
    s.close()

print(json.dumps(results, sort_keys=True, indent=2))


