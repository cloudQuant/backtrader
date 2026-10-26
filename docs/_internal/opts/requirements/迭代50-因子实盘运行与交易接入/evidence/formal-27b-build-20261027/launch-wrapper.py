"""Launch one frozen formal profile; record real exit and immutable source pins."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import psutil

parser = argparse.ArgumentParser()
parser.add_argument('--case', choices=('27a-native', '27a-build', '27b-native', '27b-build'), required=True)
parser.add_argument('--root', required=True)
args = parser.parse_args()
work = Path(args.root).resolve()
assert not work.exists(), 'Require a fresh round directory'
runner = Path('D:/source_code/backtrader/scripts/run_iteration50_live_factor_benchmark.py')
python = Path('D:/temp/i5051c-20261025-r6/venv/Scripts/python.exe')
package = Path('D:/temp/i5051c-20261025-r6/venv/Lib/site-packages')
wheel = Path('D:/temp/i5051b-03852948a7a4/wheel/back_trader_python-1.4.0-py3-none-any.whl')
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert sha(runner) == '75ca8866f6adb7fb8fc2dd361107d7749170d2cb453ba4cff4754a334567c2db'
assert sha(wheel) == 'bc33814b37ab44963ab9a964e689ee7c2665ed9a709b5bcbe0eb0bcd9770b7ee'
memory = psutil.virtual_memory()
assert memory.available >= 2 * 1024**3, 'Need >=2 GiB free before the formal profile'
which, mode = args.case.split('-')
work.mkdir(parents=True)
output = work / 'result.json'
command = [str(python), '-I', str(runner), '--mode', mode,
           '--factors', 'alpha003' if which == '27a' else 'representative-six',
           '--scenario', 'standard' if which == '27a' else '27b',
           '--recovery-mode', 'same-generation', '--grids', '100000',
           '--warmup-bars', '64' if which == '27a' else '316',
           '--duration-seconds', '0' if which == '27a' else '7200',
           '--output', str(output), '--source-revision', 'a69a494e7b26251703c130c2b9083f9ce196ef2c',
           '--package-root', str(package)]
before = {'case': args.case, 'command': command, 'runner_sha256': sha(runner),
          'source_commit': 'a69a494e7b26251703c130c2b9083f9ce196ef2c',
          'wheel_sha256': sha(wheel), 'available_memory_bytes': memory.available,
          'started_unix': time.time(), 'evidence_level': 'LOCAL_INSTALLED_SYNTHETIC_PERFORMANCE'}
(work / 'launch.json').write_text(json.dumps(before, indent=2) + '\n', encoding='utf-8')
environment = os.environ.copy()
for key in ('PYTHONPATH', 'PYTHONHOME'):
    environment.pop(key, None)
with (work / 'stdout.bin').open('xb') as stdout, (work / 'stderr.bin').open('xb') as stderr:
    completed = subprocess.run(command, cwd=work, env=environment, stdout=stdout, stderr=stderr)
after = {'exit_code': completed.returncode, 'ended_unix': time.time(),
         'runner_sha256': sha(runner), 'result_exists': output.is_file()}
(work / 'completion.json').write_text(json.dumps(after, indent=2) + '\n', encoding='utf-8')
assert after['runner_sha256'] == before['runner_sha256'], 'Runner changed during formal profile'
print(json.dumps(after), flush=True)
raise SystemExit(completed.returncode)
