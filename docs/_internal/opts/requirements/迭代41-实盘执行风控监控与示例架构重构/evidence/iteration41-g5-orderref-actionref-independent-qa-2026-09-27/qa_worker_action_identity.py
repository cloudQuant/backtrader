from __future__ import annotations
import ast, hashlib, inspect, json, sys
from pathlib import Path
ROOT=Path(r'D:\temp\iteration41-g5-order-authority-independent-qa-20260927')
PATCHED=ROOT/'candidate'/'main_repo_patch'/'backtrader'/'stores'/'ctp_i9_parent_request_builder.py'
WORKER=ROOT/'main-focus'/'backtrader'/'stores'/'ctp_i9_managed_dispatch.py'
sys.path.insert(0,str(ROOT/'main-focus'))
from backtrader.stores.ctp_i9_managed_dispatch import CtpI9SingleWorkerPort
text=PATCHED.read_text(encoding='utf-8'); tree=ast.parse(text)
call=None
for node in ast.walk(tree):
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='stage_prepared_dispatch' and isinstance(node.func.value,ast.Name) and node.func.value.id=='worker':
        if any(k.arg=='action_identity' for k in node.keywords): call=node; break
assert call is not None
method=CtpI9SingleWorkerPort.stage_prepared_dispatch
sig=inspect.signature(method)
assert tuple(sig.parameters)==('self','prepared'),str(sig)
try:
    sig.bind(object(),object(),action_identity=object())
except TypeError as e:
    bind_rejection=f'{type(e).__name__}: {e}'
else: raise AssertionError('worker contract unexpectedly accepted G5 extension')
# Actual Python call binding on an exact-signature negative spy occurs before its body.
seen=[]
class CurrentShapeWorker:
    def stage_prepared_dispatch(self, prepared):
        seen.append(prepared)
try:
    CurrentShapeWorker().stage_prepared_dispatch(object(),action_identity=object())
except TypeError as e:
    call_rejection=f'{type(e).__name__}: {e}'
else: raise AssertionError('missing action_identity keyword did not reject')
assert seen==[],seen
patch_lines=text.splitlines()
reserve_line=next(i for i,s in enumerate(patch_lines,1) if 'reserve_cancel_action_identity(' in s)
call_line=call.lineno
assert reserve_line<call_line,(reserve_line,call_line)
wrapper=next((s.strip() for s in patch_lines[call_line:call_line+35] if 'I9 cancel staging/readback failed closed' in s),None)
assert wrapper is not None
result={'status':'PASS_FAIL_CLOSED_CONTRACT','patched_builder':str(PATCHED),'patched_builder_sha256':hashlib.sha256(PATCHED.read_bytes()).hexdigest().upper(),'worker_port_source':str(WORKER),'worker_port_sha256':hashlib.sha256(WORKER.read_bytes()).hexdigest().upper(),'worker_signature':str(sig),'candidate_keyword_call_line':call_line,'action_identity_reserved_line':reserve_line,'action_identity_persisted_before_unsupported_worker_call':True,'signature_bind_rejection':bind_rejection,'exact_shape_call_rejection':call_rejection,'worker_body_calls':len(seen),'builder_wraps_exception_as':wrapper,'full_builder_runtime':'NOT RUN: exact parent worker/source-only candidate is not present in frozen input; Backtrader focused source tests skip it','provider_sdk_native_network_credentials':'not used'}
out=ROOT/'evidence'/'worker-action-identity-reject.json'; out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(result,indent=2,sort_keys=True))

