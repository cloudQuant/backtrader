"""Audit exactly one run-id directory, never merge evidence from separate runs."""
import json
import sys
from pathlib import Path

ROOT=Path('/tmp/iter63-r26-sdk-install-20261109-xAIrOrDl/origin-logs')
if len(sys.argv)!=2 or not sys.argv[1] or '/' in sys.argv[1] or sys.argv[1] in ('.','..'):
    raise SystemExit('usage: audit_run.py RUN_ID')
run=sys.argv[1];directory=ROOT/run
if not directory.is_dir(): raise RuntimeError('run log group not found')
report=[]
for path in sorted(directory.glob('*.jsonl')):
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    if not rows or any(str(x.get('pid'))!=path.stem or x.get('run_id')!=run for x in rows):
        raise RuntimeError(('origin run/pid mismatch',str(path)))
    events=[x.get('event') for x in rows]
    if 'guard-installed' not in events or 'VIOLATION' in events: raise RuntimeError(('missing guard or violation',str(path)))
    report.append({'pid':int(path.stem),'ppids':sorted({x['ppid'] for x in rows}),
                   'guard':True,'resolved':events.count('resolved'),'exit_audit_missing':'audit-ok' not in events})
if not report: raise RuntimeError('empty run group')
print(json.dumps({'run_id':run,'files':len(report),'missing_exit_audits':sum(x['exit_audit_missing'] for x in report),'processes':report},sort_keys=True))
