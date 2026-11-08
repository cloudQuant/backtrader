"""Execute one frozen R15 stage with persisted stdout, exact command and exit code."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

T = Path('/tmp/iter63-r15-install-20261109-0CwgPSqi')
CONDA = '/Users/yunjinqi/opt/anaconda3/bin/conda'
PY = [CONDA, 'run', '--no-capture-output', '-n', 'base', 'python']
KINDS = ('base', 'gateway', 'ctp', 'sdk')
STAGES = {'snapshot','fixed','tests-copy','build','install','verify','tests','guard-preflight','audit','commits','verify-final','final-base','final-gateway','final-ctp','final-sdk','retry-ctp','audit-final','commits-final'}


def run(name, command, *, kind=None):
    log = T/(name+'.log')
    if log.exists():
        raise RuntimeError(('refusing to overwrite previous evidence', str(log)))
    env = os.environ.copy()
    env.update({'TMPDIR': str(T/'tmp'), 'PIP_NO_CACHE_DIR': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
    if name == 'ctp-installed-relocated':
        env['R15_CTP_RELOCATED'] = '1'
    if kind is not None:
        env['R15_TEST_KIND'] = kind
    started = datetime.now(timezone.utc).isoformat()
    with log.open('wb') as output:
        completed = subprocess.run(command, cwd=T, env=env, stdout=output, stderr=subprocess.STDOUT, check=False)
    record = {'stage': name, 'argv': command, 'cwd': str(T), 'kind': kind, 'started_utc': started,
              'finished_utc': datetime.now(timezone.utc).isoformat(), 'exit_code': completed.returncode, 'stdout_stderr': str(log),
              'environment_policy': 'TMPDIR=workspace/tmp; pip cache disabled; no secrets recorded'}
    with (T/'executions.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, sort_keys=True)+'\n')
    print(name, 'exit', completed.returncode, 'log', log, flush=True)
    return completed.returncode


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in STAGES:
        raise SystemExit('usage: run.py '+ '|'.join(sorted(STAGES)))
    if not (T/'SOURCE_FROZEN').is_file():
        raise SystemExit('R15 freeze marker absent; refusing all stages')
    (T/'tmp').mkdir(exist_ok=True)
    stage = sys.argv[1]
    if stage in {'snapshot', 'fixed', 'tests-copy'}:
        op = {'snapshot':'snapshot','fixed':'fixed','tests-copy':'tests'}[stage]
        return run(stage, PY+[str(T/'prepare.py'),op])
    if stage == 'build':
        for kind in KINDS:
            source = T/'source'/kind
            if not source.is_dir() or (source/'build').exists() or (source/'dist').exists() or list(source.rglob('*.egg-info')):
                raise RuntimeError(('missing source or stale build output', kind))
        wheels = list((T/'wheels').glob('*.whl'))
        if len(wheels) != 3:
            raise RuntimeError(('expected exactly three fixed R11 wheels before build',len(wheels)))
        return run(stage, PY+['-m','pip','wheel','--no-index','--no-deps','--no-build-isolation','--wheel-dir',str(T/'wheels'),*[str(T/'source'/kind) for kind in KINDS]])
    if stage == 'install':
        target = T/'install/src'
        if target.exists():
            raise RuntimeError('isolated install target must not already exist')
        wheels = sorted((T/'wheels').glob('*.whl'))
        if len(wheels) != 7:
            raise RuntimeError(('expected three fixed and four rebuilt wheels',len(wheels)))
        return run(stage, PY+['-m','pip','install','--no-index','--no-deps','--target',str(target),*[str(wheel) for wheel in wheels]])
    if stage in {'verify','verify-final'}:
        return run(stage, PY+['-I',str(T/'verify.py')])
    if stage == 'guard-preflight':
        return run(stage, PY+['-I',str(T/'guard_preflight.py')],kind='sdk')
    if stage == 'audit-final':
        return run(stage, PY+['-I',str(T/'audit_origins.py')])
    if stage == 'retry-ctp':
        return run('ctp-installed-relocated', PY+['-I',str(T/'run_installed.py')],kind='ctp')
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
