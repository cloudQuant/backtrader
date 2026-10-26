"""Root same-host finite diagnosis after complete normal close; no provider call."""
def observe():
    import json
    from pathlib import Path
    from backtrader.stores.btapistore import BtApiStoreError
    import bt_api_ctp.md_diagnostics as diagnostics
    destination = Path('D:/temp/i51-root-discovery-diagnostic-20261027-r2.json')
    assert not destination.exists()
    state = ROOT_STATE
    original = state['result']
    assert state['closed'] is True and original['native_close_confirmed'] is True
    error = state['original_error']
    reason = 'UNCLASSIFIED_ORIGINAL_ERROR'
    if type(error) is BtApiStoreError and type(error.args) is tuple and len(error.args) == 1 and type(error.args[0]) is str:
        if error.args[0] == 'CTP market data login did not become ready within 20s':
            reason = 'MD_LOGIN_NOT_READY_20S'
        elif error.args[0] == 'CTP trader login did not become ready within 20s':
            reason = 'TD_LOGIN_NOT_READY_20S'
    md = state['store']._api.md_client
    observation = md.login_callback_diagnostic
    assert type(observation) is diagnostics.MdLoginCallbackDiagnostic
    assert type(observation.callback_count) is int and 0 <= observation.callback_count <= 1000
    row = {'callback_count': observation.callback_count}
    enums = {
        'disposition': diagnostics.MdLoginCallbackDisposition,
        'request_id_relation': diagnostics.MdLoginRequestIdRelation,
        'response_error_status': diagnostics.MdLoginResponseErrorStatus,
        'broker_id_shape': diagnostics.MdLoginBrokerIdShape,
        'user_id_shape': diagnostics.MdLoginUserIdShape,
        'trading_day_shape': diagnostics.MdLoginTradingDayShape,
        'native_broker_id_shape': diagnostics.MdLoginNativeFieldShape,
        'native_user_id_shape': diagnostics.MdLoginNativeFieldShape,
    }
    for name, expected_type in enums.items():
        value = getattr(observation, name)
        assert type(value) is expected_type
        row[name] = value.value
    result = {'status':'ROOT_VALUE_FREE_POSTCLOSE_OBSERVATION','reason':reason,'md_login_callback':row,'original_result_unchanged':state['result'] is original,'native_close_confirmed':True,'private_context_closed':True,'provider_or_cleanup_invoked':False}
    with destination.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2)
        stream.write('\n')
    print(json.dumps(result))

observe()
