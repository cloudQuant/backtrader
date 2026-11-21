"""Launch the six selected source-only mutation checks with a minimal environment."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
runner = root / 'run_mutation.py'
source = root / 'backtrader/service/service_recovery_attestation.py'
test = root / 'tests/unit/test_iter71_service_recovery_attestor_fill_validation.py'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
pins = [digest(source), digest(test), digest(runner)]
env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR') if k in os.environ}
env.update({'TEMP': str(root), 'TMP': str(root), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'})
records = []
for case in ('currency', 'time'):
    for mode in ('clean', 'mutant', 'clean'):
        p = subprocess.run([sys.executable, '-I', '-S', '-B', str(runner), case, mode],
                           cwd=root, env=env, capture_output=True, text=True, encoding='utf-8',
                           errors='strict', timeout=30)
        record = dict(case=case, mode=mode, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
        records.append(record)
        print(json.dumps(record,ensure_ascii=False),flush=True)
        assert [digest(source), digest(test), digest(runner)] == pins, 'input changed'
        if mode == 'clean':
            assert p.returncode == 0 and 'TARGET_PASS' in p.stdout, 'clean failed'
        else:
            assert p.returncode != 0 and 'DID NOT RAISE' in p.stderr, 'mutant not killed by target'
result = dict(base='c5fc2e7e954eae104d4acae5accdd9bf30e9c44d', source_sha256=pins[0],
              test_sha256=pins[1], runner_sha256=pins[2], records=records)
(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('ALL_CHECKS_PASSED',flush=True)
