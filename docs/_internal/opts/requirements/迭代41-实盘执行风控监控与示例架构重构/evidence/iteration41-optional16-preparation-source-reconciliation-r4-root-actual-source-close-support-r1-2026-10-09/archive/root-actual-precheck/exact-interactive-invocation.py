from pathlib import Path as _O16R4R3Path
import hashlib as _O16R4R3Hash, types as _O16R4R3Types, importlib.util as _O16R4R3ImportUtil
_O16R4R3Namespace = globals()
_O16R4R3PathValue = _O16R4R3Path('D:/source_code/backtrader/.codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_r4_r3.py')
with _O16R4R3PathValue.open('rb') as _O16R4R3Stream: _O16R4R3Raw = _O16R4R3Stream.read(60977)
assert len(_O16R4R3Raw) == 60976 and _O16R4R3Hash.sha256(_O16R4R3Raw).hexdigest() == '4a55ca904544c297fa1a87c6ca944ec5aa865ebc39a9e820ce0506492ee1d23d'
_O16R4R3Alias = '_root_optional16_r4_r3_exact_caller_oct9'
assert _O16R4R3Alias not in sys.modules
_O16R4R3Module = _O16R4R3Types.ModuleType(_O16R4R3Alias)
_O16R4R3Module.__file__ = str(_O16R4R3PathValue)
_O16R4R3Module.__package__ = ''
_O16R4R3Module.__spec__ = _O16R4R3ImportUtil.spec_from_file_location(_O16R4R3Alias, _O16R4R3PathValue)
sys.modules[_O16R4R3Alias] = _O16R4R3Module
_O16R4R3Code = compile(_O16R4R3Raw, str(_O16R4R3PathValue), 'exec', dont_inherit=True)
exec(_O16R4R3Code, _O16R4R3Module.__dict__)
_O16R4R3Pending = [_O16R4R3Code]
_O16R4R3Expected = {}
while _O16R4R3Pending:
    _O16R4R3Item = _O16R4R3Pending.pop()
    _O16R4R3Expected.setdefault(_O16R4R3Item.co_qualname, []).append(_O16R4R3Item)
    _O16R4R3Pending.extend(_O16R4R3Sub for _O16R4R3Sub in _O16R4R3Item.co_consts if type(_O16R4R3Sub) is _O16R4R3Types.CodeType)
_O16R4R3Bindings = dict(_O16R4R3Module.__dict__)
_O16R4R3Functions = [(k,v) for k,v in _O16R4R3Bindings.items() if type(v) is _O16R4R3Types.FunctionType and v.__module__ == _O16R4R3Alias]
assert len(_O16R4R3Functions) > 20
for _O16R4R3Key, _O16R4R3Function in _O16R4R3Functions:
    assert _O16R4R3Function.__globals__ is _O16R4R3Module.__dict__
    assert _O16R4R3Function.__code__ in _O16R4R3Expected[_O16R4R3Function.__qualname__]
_O16R4R3Result = _O16R4R3Module.run(_O16R4R3Namespace, expected_caller_sha256='4a55ca904544c297fa1a87c6ca944ec5aa865ebc39a9e820ce0506492ee1d23d')
assert set(_O16R4R3Module.__dict__) == set(_O16R4R3Bindings)
assert all(_O16R4R3Module.__dict__[k] is v for k,v in _O16R4R3Bindings.items())
assert _O16R4R3Hash.sha256(_O16R4R3PathValue.read_bytes()).hexdigest() == '4a55ca904544c297fa1a87c6ca944ec5aa865ebc39a9e820ce0506492ee1d23d'
for _O16R4R3Key, _O16R4R3Function in _O16R4R3Functions:
    assert _O16R4R3Function.__globals__ is _O16R4R3Module.__dict__ and _O16R4R3Function.__code__ in _O16R4R3Expected[_O16R4R3Function.__qualname__]
print({'phase':'ROOT_R4_RECONCILIATION_SINGLE_CALL_RETURNED','status':_O16R4R3Result.get('status'),'reason':_O16R4R3Result.get('reason'),'failure_phase':_O16R4R3Result.get('phase'),'attempted':_O16R4R3Result.get('attempted'),'fresh_review_scope_normal_exit':_O16R4R3Result.get('fresh_review_scope_normal_exit'),'formal_optional16_pass_count':0,'root_caller_bindings_preserved':True,'root_function_count':len(_O16R4R3Functions)})
