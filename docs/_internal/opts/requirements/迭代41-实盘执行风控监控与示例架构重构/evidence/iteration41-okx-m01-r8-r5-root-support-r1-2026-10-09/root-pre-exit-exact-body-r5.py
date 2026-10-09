_R5ExitDriverPath = Path('D:/source_code/backtrader/.codex-tmp/okx_m01_r8_r5_root_driver_r2_20261009.py')
_R5ExitDriverRaw = _R5ExitDriverPath.read_bytes()
assert len(_R5ExitDriverRaw) == 29420 and hashlib.sha256(_R5ExitDriverRaw).hexdigest() == 'ddee4f2eb6058c61b0c2ef69964d33fdca82a85ead733e272d391f6f41d3d369'
_R5ExitFilename = verify_caller.__code__.co_filename
assert Path(_R5ExitFilename).resolve() == _R5ExitDriverPath.resolve()
_R5ExitCodes = [compile(_R5ExitDriverRaw, _R5ExitFilename, 'exec', dont_inherit=True)]
_R5ExitExpected = {}
while _R5ExitCodes:
    _R5ExitCode = _R5ExitCodes.pop()
    _R5ExitExpected.setdefault(_R5ExitCode.co_qualname, []).append(_R5ExitCode)
    _R5ExitCodes.extend(v for v in _R5ExitCode.co_consts if type(v) is types.CodeType)
_R5ExitRootFunctions = [(k,v) for k,v in list(globals().items()) if type(v) is types.FunctionType and v.__module__ == '__main__' and v.__code__.co_filename == _R5ExitFilename]
assert len(_R5ExitRootFunctions) > 8
for _R5ExitName, _R5ExitFunction in _R5ExitRootFunctions:
    assert _R5ExitFunction.__globals__ is globals() and _R5ExitFunction.__code__ in _R5ExitExpected[_R5ExitFunction.__qualname__]
verify_caller(caller, caller_raw, expected, initial=False)
verify_snapshot(caller, root_binding)
assert set(caller.__dict__) == set(caller_globals)
assert all(caller.__dict__[k] is v for k,v in caller_globals.items() if k != '_INVOCATION_STARTED')
assert caller._RETAINED_CONTEXTS is retained_registry and retained_registry == []
assert ACTUAL_RESULT is receipt['result'] and receipt['caller_scope_clean'] is True
assert ACTUAL_RESULT['host_exit_permitted'] is True and ACTUAL_RESULT['scope_exit_confirmed'] is True and ACTUAL_RESULT['outer_normal_postverify_and_close'] is True
assert all(ACTUAL_RESULT[k] == 0 for k in ('retained_gate_context_count','retained_runtime_registry_count','retained_reader_context_count','caller_retained_reference_count'))
assert ACTUAL_RESULT['gate_result']['cleanup_confirmed'] is True and ACTUAL_RESULT['gate_result']['job_zero_after_cleanup'] is True and ACTUAL_RESULT['gate_result']['all_observed_handles_closed'] is True
assert ACTUAL_RESULT['private_inputs_read'] is False and ACTUAL_RESULT['account_provider_operations'] is False
_R5ExitOutside = json.loads((OUTPUT / 'root-outside-git-postverification.json').read_bytes())
assert _R5ExitOutside['status'] == 'OUTSIDE_HOST_GIT_POSTVERIFIED' and _R5ExitOutside['git_pre_post_equal'] is True
assert _R5ExitOutside['git'] == before and _R5ExitOutside['public_pins_verified'] == 31 and _R5ExitOutside['host_id'] == 39102
_R5ExitReceiptRaw = ROOT_RESULT_PATH.read_bytes()
assert len(_R5ExitReceiptRaw) == 6305 and hashlib.sha256(_R5ExitReceiptRaw).hexdigest() == _R5ExitOutside['root_receipt_sha256'] == 'c3e3f36358dabe335039f19dfe9b62ea23b42823d2b86f883ec9c150a6b19dc2'
assert all(read_pinned(ROOT / row['path'], row['bytes'], row['sha256']) == public_raw[row['path']] for row in public_rows)
ROOT_STATE['outside_git_postverified'] = True
ROOT_STATE['exit_permitted'] = True
_R5ExitObservation = {'status':'LIVE_BINDINGS_AND_CLEAN_CUSTODY_VERIFIED','host_id':39102,'root_function_bindings_checked':len(_R5ExitRootFunctions),'caller_bindings_preserved':True,'caller_registry_empty':True,'source_scope_closed':True,'job_zero_and_all_observed_handles_closed':True,'outside_git_postverified':True,'public_pins_checked':31,'original_root_receipt_preserved':True,'normal_host_exit_permitted':True,'host_exit_already_occurred':False,'formal_m01_pass_count':0}
with (OUTPUT / 'root-pre-exit-observation.json').open('x',encoding='utf-8') as _R5ExitStream: _R5ExitStream.write(json.dumps(_R5ExitObservation,sort_keys=True,indent=2)+'\n')
print(_R5ExitObservation)
