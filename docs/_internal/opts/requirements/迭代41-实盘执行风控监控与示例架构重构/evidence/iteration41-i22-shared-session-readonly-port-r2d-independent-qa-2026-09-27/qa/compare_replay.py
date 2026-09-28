from pathlib import Path
import difflib
base=Path(r'D:\temp\iteration41-r2d-independent-audit-20260927\patch-replay-final')
cand=Path(r'D:\temp\iteration41-r2d-shared-session-readonly-port-20260927')
files=['backtrader/stores/ctp_account_actor_port.py','tests/unit/stores/test_btapistore_iteration22.py','tests/unit/stores/test_ctp_shared_session_read_port.py']
results={}
for rel in files:
    a=base.joinpath(rel).read_bytes(); b=cand.joinpath(rel).read_bytes()
    x=a.replace(bytes([13,10]),bytes([10])); y=b.replace(bytes([13,10]),bytes([10]))
    results[rel]={'normalized_equal':x==y,'replay_crlf_count':a.count(bytes([13,10])),'candidate_crlf_count':b.count(bytes([13,10]))}
    if x!=y:
        print('DIFF',rel)
        print(''.join(list(difflib.unified_diff(x.decode().splitlines(True),y.decode().splitlines(True)))[:30]))
print(results)
assert all(v['normalized_equal'] for v in results.values())
