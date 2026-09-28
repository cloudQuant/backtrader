from pathlib import Path
import hashlib
candidate=Path(r'D:\temp\case33_em01_o02_integration_20260928')
verify=Path(r'D:\temp\case33_em01_o02_applyverify_20260928')
for rel in ('examples/007_ctp/live_certification/simnow_penetration/common/completion_invariants.py','tests/unit/live_certification/test_simnow_completion_invariants.py'):
 a=(candidate/rel).read_bytes(); b=(verify/rel).read_bytes()
 print(rel,'same_bytes=',a==b,'candidate_sha256=',hashlib.sha256(a).hexdigest(),'applied_sha256=',hashlib.sha256(b).hexdigest())
