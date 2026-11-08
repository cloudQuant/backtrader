"""Match frozen source/test manifests to current worktrees and exact Git commits."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

T = Path('/tmp/iter63-r23-install-20261109-s5p4b4ec')
if not (T / 'SOURCE_FROZEN').is_file():
    raise SystemExit('R23 freeze marker absent')

failures = []
commits = {}
for manifest in ('source-manifest.json', 'test-manifest.json'):
    rows = json.loads((T / manifest).read_text())
    for row in rows:
        repo = row['repo']
        if repo not in commits:
            commits[repo] = subprocess.check_output(
                ['git', '-C', repo, 'rev-parse', 'HEAD'], text=True
            ).strip()
        for field in ('source', 'copy'):
            path = Path(row[field])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                failures.append({'manifest': manifest, 'field': field, 'path': str(path)})
        result = subprocess.run(
            ['git', '-C', repo, 'show', commits[repo] + ':' + row['relative']],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        if result.returncode != 0 or hashlib.sha256(result.stdout).hexdigest() != row['sha256']:
            failures.append({'manifest': manifest, 'field': 'commit', 'repo': repo,
                             'commit': commits[repo], 'relative': row['relative']})
    print('MANIFEST_COMMIT_AUDIT', manifest, 'rows', len(rows), flush=True)
print('COMMITS', json.dumps(commits, sort_keys=True), flush=True)
if failures:
    print('NOT_COMMITTED_OR_DRIFTED', json.dumps(failures, sort_keys=True), flush=True)
    raise SystemExit(1)
print('COPY_WORKTREE_COMMIT_SHA_MATCH', flush=True)
