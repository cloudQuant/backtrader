import hashlib
import json
import statistics
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'manifest.json').read_text(encoding='utf8'))
worker = root / 'worker.py'

def tree_hash(directory):
    digest = hashlib.sha256()
    for path in sorted((directory / 'backtrader').rglob('*.py')):
        digest.update(path.relative_to(directory).as_posix().encode() + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()

labels = ['head_old', 'head_safe', 'wip_old', 'wip_safe']
trees = {label: tree_hash(root / label) for label in labels}
data = {'manifest': manifest, 'worker_sha256': hashlib.sha256(worker.read_bytes()).hexdigest(),
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'trees_before': trees, 'samples': []}
output = root / 'results.json'
orders = [('head', ['old', 'safe', 'safe', 'old', 'safe', 'old', 'old', 'safe']),
          ('wip', ['old', 'safe', 'safe', 'old', 'safe', 'old', 'old', 'safe'])]
for group, order in orders:
    for style in order:
        label = group + '_' + style
        completed = subprocess.run([sys.executable, '-B', str(worker), str(root / label), label],
                                   cwd=root, capture_output=True, text=True, timeout=180, check=True)
        result = json.loads(completed.stdout)
        data['samples'].append(result)
        output.write_text(json.dumps(data, indent=2) + '\n', encoding='utf8')
        print(label, f"{result['seconds']:.6f}", result['line_output_sha256'], flush=True)

data['trees_after'] = {label: tree_hash(root / label) for label in labels}
assert data['trees_before'] == data['trees_after']
for group, _ in orders:
    samples = [row for row in data['samples'] if row['label'].startswith(group)]
    assert len({row['line_output_sha256'] for row in samples}) == 1
    assert len({row['strategy_next_callbacks'] for row in samples}) == 1
    old = [row['seconds'] for row in samples if row['label'].endswith('_old')]
    safe = [row['seconds'] for row in samples if row['label'].endswith('_safe')]
    data[group + '_summary'] = {'old_seconds': old, 'safe_seconds': safe,
                                'old_median': statistics.median(old), 'safe_median': statistics.median(safe),
                                'median_improvement_pct': (1 - statistics.median(safe) / statistics.median(old)) * 100}
output.write_text(json.dumps(data, indent=2) + '\n', encoding='utf8')
print(json.dumps({key: data[key] for key in ('head_summary', 'wip_summary')}, indent=2))
