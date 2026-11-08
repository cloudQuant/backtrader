"""Summarize only recorded processes; explicitly report absent exit audits."""
import json
from pathlib import Path
T = Path('/tmp/iter63-r15-install-20261109-0CwgPSqi')
root = T/'origin-logs'
if not root.is_dir():
    raise RuntimeError('no origin logs')
for run in sorted(root.iterdir()):
    print('RUN', run.name, flush=True)
    for path in sorted(run.glob('*.jsonl')):
        events = [json.loads(line) for line in path.read_text().splitlines()]
        names = [row['event'] for row in events]
        print('PID', path.stem, 'guard', names.count('guard-installed'), 'resolved', names.count('resolved'),
              'audit', names.count('audit-ok'), 'violations', names.count('VIOLATION'),
              'exit_audit_missing', 'audit-ok' not in names, flush=True)
        if 'guard-installed' not in names or 'VIOLATION' in names:
            raise RuntimeError(('origin guard missing or violation', str(path)))
