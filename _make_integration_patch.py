from pathlib import Path
from difflib import unified_diff
repo=Path(r'D:\source_code\backtrader')
candidate=Path(r'D:\temp\case33_em01_o02_integration_20260928')
test=candidate/'tests/unit/live_certification/test_simnow_completion_invariants.py'
test.write_bytes(test.read_bytes().replace(b'\r\n',b'\n'))
files=(
'examples/007_ctp/live_certification/simnow_penetration/common/completion_invariants.py',
'tests/unit/live_certification/test_simnow_completion_invariants.py',
)
chunks=[]
for rel in files:
    old=(repo/rel).read_bytes().decode('utf-8').splitlines(keepends=True)
    new=(candidate/rel).read_bytes().decode('utf-8').splitlines(keepends=True)
    chunks.extend(unified_diff(old,new,fromfile='a/'+rel,tofile='b/'+rel,n=3))
patch=candidate/'case33_em01_o02_integration.patch'
patch.write_bytes(''.join(chunks).encode('utf-8'))
print('wrote',patch)
