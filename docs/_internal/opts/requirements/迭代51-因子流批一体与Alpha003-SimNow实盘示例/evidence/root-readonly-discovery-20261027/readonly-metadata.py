"""Finite read-only facts in the original host; no cleanup or provider methods."""
def _observe_original_discovery_once():
    from pathlib import Path
    import json
    from datetime import datetime, timezone
    from backtrader.stores.btapistore import BtApiStoreError
    destination = Path('D:/temp/i51-root-discovery-readonly-metadata-20261027-r1.json')
    if destination.exists():
        raise RuntimeError('OBSERVATION_ALREADY_EXISTS')
    state = ROOT_STATE
    original = state['result']
    assert original['status'] == 'BLOCKED_RETAINED_NATIVE_CUSTODY'
    assert state['closed'] is False
    error = state['original_error']
    reason = 'UNCLASSIFIED_ORIGINAL_ERROR'
    if type(error) is BtApiStoreError and type(error.args) is tuple and len(error.args) == 1:
        if type(error.args[0]) is str:
            if error.args[0] == 'CTP market data login did not become ready within 20s':
                reason = 'MD_LOGIN_NOT_READY_20S'
            elif error.args[0] == 'CTP trader login did not become ready within 20s':
                reason = 'TD_LOGIN_NOT_READY_20S'
    output = {'schema': 1, 'observation_at': datetime.now(timezone.utc).isoformat(),
              'reason': reason, 'original_result_unchanged': True,
              'private_context_retained': True, 'cleanup_or_provider_called': False, 'clients': {}}
    custody = state['close_error'].custody
    assert custody.store is state['store'] and custody.wrapper is state['store']._api
    for name, client, lock_name in (('md', custody.md_client, '_state_lock'),
                                    ('trader', custody.trader_client, '_query_state_lock')):
        with getattr(client, lock_name):
            thread = client._last_stop_join_thread
            tracker = client._last_stop_join_tracker
            row = {'published_api_absent': client._api is None,
                   'saved_stopped_api_present': client._last_stopped_native_api is not None,
                   'join_thread_alive': thread.is_alive() if thread is not None else None,
                   'generation': client._last_stopped_connection_generation}
        if tracker is not None:
            with tracker._lock:
                phase = tracker._observation.state
                row['join_phase'] = phase if phase in ('not_started', 'pending', 'returned', 'failed') else 'UNRECOGNIZED'
                row['join_finished'] = tracker._finished.is_set()
        output['clients'][name] = row
    destination.write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')


_observe_original_discovery_once()
