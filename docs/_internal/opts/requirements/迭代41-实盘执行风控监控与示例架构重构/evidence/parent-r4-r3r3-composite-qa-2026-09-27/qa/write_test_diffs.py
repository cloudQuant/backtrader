from pathlib import Path
import difflib
root=Path(r'D:\temp\iteration41-parent-r4-r3r3-composite-20260927-r1')
orig=root/'provenance'/'r3r3-original'
cand=root/'parent-source'/'tests'
for old,new,name in [
    (orig/'test_cancel_dispatch_resolution_proof.py',cand/'test_cancel_dispatch_resolution_proof.py','r3r3-issuer-proof-adapted-to-r4.diff'),
    (orig/'test_cancel_dispatch_resolution_proof_store.py',cand/'test_cancel_dispatch_resolution_proof_store.py','r3r3-issuer-store-adapted-to-r4.diff'),
]:
    diff=''.join(difflib.unified_diff(old.read_text(encoding='utf-8').splitlines(keepends=True),new.read_text(encoding='utf-8').splitlines(keepends=True),fromfile='provenance/'+old.name,tofile='candidate/tests/'+new.name))
    (root/'provenance'/name).write_text(diff,encoding='utf-8',newline='\n')
