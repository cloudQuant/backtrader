"""Execute one frozen R25 stage with persisted stdout, exact command and exit code."""
from __future__ import annotations
import hashlib
import json
import time
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

T = Path('/tmp/iter63-r28-candidate2-20261109-hLnRZEKN')
CONDA = '/Users/yunjinqi/opt/anaconda3/bin/conda'
PY = [CONDA, 'run', '--no-capture-output', '-n', 'base', 'python']
KINDS = ('bt',)
STAGES = {'snapshot','tests-copy','tests-copy-retry1','build','install','verify','tests','guard-preflight','verify-final','final-bt','capture-editable-deps','verify-before','verify-after-classified'}


def run(name, command, *, kind=None):
    log = T/(name+'.log')
    if log.exists():
        raise RuntimeError(('refusing to overwrite previous evidence', str(log)))
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith(('CTP_', 'OKX_', 'BINANCE_', 'HTX_', 'IB_')):
            env.pop(key, None)
    env.update({'TMPDIR': str(T/'tmp'), 'PIP_NO_CACHE_DIR': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
    if kind is not None:
        env['R25_TEST_KIND'] = kind
    run_id = name+'-'+str(os.getpid())+'-'+str(time.time_ns())
    env['R25_ORIGIN_RUN'] = run_id
    selector = T/'selectors.json'
    selector_sha = hashlib.sha256(selector.read_bytes()).hexdigest() if selector.is_file() else None
    started = datetime.now(timezone.utc).isoformat()
    header = {'run_id':run_id,'launcher_pid':os.getpid(),'launcher_ppid':os.getppid(),
              'selector_sha256':selector_sha,'argv':command,'stage':name}
    with log.open('wb') as output:
        output.write(('RUN_METADATA '+json.dumps(header,sort_keys=True)+'\n').encode())
        output.flush()
        completed = subprocess.run(command, cwd=T, env=env, stdout=output, stderr=subprocess.STDOUT, check=False)
        output.write(('RUN_EXIT '+str(completed.returncode)+'\n').encode())
    record = {'run_id': run_id, 'launcher_pid':os.getpid(), 'launcher_ppid':os.getppid(), 'selector_sha256':selector_sha, 'stage': name, 'argv': command, 'cwd': str(T), 'kind': kind, 'started_utc': started,
              'finished_utc': datetime.now(timezone.utc).isoformat(), 'exit_code': completed.returncode, 'stdout_stderr': str(log),
              'environment_policy': 'TMPDIR=workspace/tmp; pip cache disabled; no secrets recorded'}
    with (T/'executions.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, sort_keys=True)+'\n')
    print(name, 'exit', completed.returncode, 'run_id',run_id,'log', log, flush=True)
    return completed.returncode


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in STAGES:
        raise SystemExit('usage: run.py '+ '|'.join(sorted(STAGES)))
    if not (T/'SOURCE_FROZEN').is_file():
        raise SystemExit('R25 freeze marker absent; refusing all stages')
    (T/'tmp').mkdir(exist_ok=True)
    stage = sys.argv[1]
    if stage in {'snapshot', 'tests-copy', 'tests-copy-retry1'}:
        op = {'snapshot':'snapshot','tests-copy':'tests','tests-copy-retry1':'tests'}[stage]
        return run(stage, PY+[str(T/'prepare.py'),op])
    if stage == 'build':
        for kind in ('bt',):
            source = T/'source'/kind
            if not source.is_dir() or (source/'build').exists() or (source/'dist').exists() or list(source.rglob('*.egg-info')):
                raise RuntimeError(('missing source or stale build output', kind))
        wheels = list((T/'wheels').glob('*.whl'))
        if len(wheels) != 7:
            raise RuntimeError(('expected six fixed and msgpack wheels before build',len(wheels)))
        return run(stage, PY+['-m','pip','wheel','--no-index','--no-deps','--no-build-isolation','--wheel-dir',str(T/'wheels'),*[str(T/'source'/kind) for kind in ('bt',)]])
    if stage == 'install':
        target = T/'install/src'
        if target.exists():
            raise RuntimeError('isolated install target must not already exist')
        wheels = sorted((T/'wheels').glob('*.whl'))
        if len(wheels) != 8:
            raise RuntimeError(('expected six fixed, msgpack and one rebuilt wheel',len(wheels)))
        return run(stage, PY+['-m','pip','install','--no-index','--no-deps','--target',str(target),*[str(wheel) for wheel in wheels]])
    if stage in {'verify','verify-before','verify-final','verify-after-classified'}:
        return run(stage, PY+['-I',str(T/'verify.py')])
    if stage == 'guard-preflight':
        return run(stage, PY+['-I',str(T/'guard_preflight.py')],kind='sdk')
    if stage == 'capture-editable-deps':
        return run(stage, PY+['-I',str(T/'capture_editable_deps.py')])
    if stage == 'audit-final':
        return run(stage, PY+['-I',str(T/'audit_origins.py')])
    if stage == 'audit':
        return run(stage, PY+['-I',str(T/'audit_origins.py')])
    if stage == 'commits-final':
        return run(stage, PY+['-I',str(T/'verify_commits.py')])
    if stage == 'commits':
        return run(stage, PY+['-I',str(T/'verify_commits.py')])
    if stage.startswith('final-'):
        kind = stage.removeprefix('final-')
        return run(kind+'-frozen-final', PY+['-I',str(T/'run_installed.py')],kind=kind)
    exits = [run(kind+'-installed',PY+['-I',str(T/'run_installed.py')],kind=kind) for kind in KINDS]
    return 1 if any(exits) else 0

if __name__ == '__main__':
    raise SystemExit(main())
