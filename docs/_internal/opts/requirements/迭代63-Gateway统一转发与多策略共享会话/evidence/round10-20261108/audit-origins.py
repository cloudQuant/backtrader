import json
from pathlib import Path
T=Path('/tmp/iter63-r10-packaging-Zc9un7t2')
for run in sorted((T/'origin-logs').iterdir()):
 print('RUN',run.name,flush=True)
 for p in sorted(run.glob('*.jsonl')):
  events=[json.loads(x) for x in p.read_text().splitlines()]; names=[e['event'] for e in events]
  print('PID',p.stem,'guard',names.count('guard-installed'),'resolved',names.count('resolved'),'audit',names.count('audit-ok'),'violations',names.count('VIOLATION'),flush=True)
  assert 'guard-installed' in names and 'VIOLATION' not in names
