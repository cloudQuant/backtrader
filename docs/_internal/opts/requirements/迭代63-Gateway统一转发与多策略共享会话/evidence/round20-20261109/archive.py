"""Archive only explicitly selected R20 synthetic logs; never overwrite evidence."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TMP = Path('/tmp')
OUT = Path('/Users/yunjinqi/Documents/new_projects/backtrader/docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话/evidence/round20-20261109')
STAGING = Path('/tmp/iter63-r20-archive/staging')
CAPTURED = Path('/tmp/iter63-r20-archive/captured.json')
SELF = Path('/tmp/iter63-r20-archive/archive.py')
INSTALLS = {
    'v1': TMP / 'iter63-r20-install-20261109-x3vllCQQ',
    'v2': TMP / 'iter63-r20-install-20261109-v2-bbNdwxzS',
    'v3': TMP / 'iter63-r20-install-20261109-v3-0mIL2v0a',
}


def top_files(base, suffixes, destination):
    if not base.is_dir():
        return []
    return [(p, Path(destination) / p.name) for p in sorted(base.iterdir())
            if p.is_file() and not p.is_symlink() and
            (p.suffix in suffixes or p.name == 'SOURCE_FROZEN')]


def origin_files(base, destination):
    if not base.is_dir() or base.is_symlink():
        return []
    selected = []
    for group in sorted(base.iterdir()):
        if not group.is_dir() or group.is_symlink():
            continue
        if not re.fullmatch(r'(?:sdk-[0-9]+-[0-9]+|unbound|guard-preflight)', group.name):
            continue
        for file in sorted(group.iterdir()):
            if file.is_file() and not file.is_symlink() and re.fullmatch(r'[0-9]+\.jsonl', file.name):
                selected.append((file, Path(destination) / group.name / file.name))
    return selected


def collect():
    items = []
    items += top_files(TMP / 'iter63-r20-primary', {'.log', '.json', '.py', '.txt'}, 'primary')
    for source, dest in [
        ('iter63-r20-account', 'worker-account'),
        ('iter63-r20-market-component', 'worker-market-component'),
        ('iter63-r20-session', 'worker-session'),
    ]:
        items += top_files(TMP / source, {'.log'}, dest)
    for pattern, dest in [('iter63-r20-runtime.log', 'worker-runtime'),
                          ('iter63-r20-market-tests*.log', 'worker-market')]:
        items += [(p, Path(dest) / p.name) for p in sorted(TMP.glob(pattern))
                  if p.is_file() and not p.is_symlink()]
    for version, base in INSTALLS.items():
        dest = Path('installed') / version
        items += top_files(base, {'.log', '.json', '.jsonl', '.py', '.txt', '.md'}, dest)
        items += top_files(base / 'bootstrap', {'.py'}, dest / 'bootstrap')
        items += top_files(base / 'plans', {'.txt', '.json'}, dest / 'plans')
        items += origin_files(base / 'origin-logs', dest / 'origin-logs')
    # The first workspace owns the source runner used for these source runs.
    base = INSTALLS['v1'] / 'source-runner'
    items += top_files(base, {'.py', '.json', '.log', '.txt'}, 'source-runner')
    items += top_files(base / 'bootstrap', {'.py'}, 'source-runner/bootstrap')
    items += origin_files(base / 'origin-logs', 'source-runner/origin-logs')
    # v2/v3 have their own frozen selectors, not a complete runner.
    for version in ('v2', 'v3'):
        items += top_files(INSTALLS[version] / 'source-runner', {'.json'},
                           Path('installed') / version / 'source-runner')
    items.append((SELF, Path('archive.py')))
    targets = [str(dst) for _, dst in items]
    if len(set(targets)) != len(targets):
        raise RuntimeError('duplicate archive destination')
    return items


def stable_bytes(path):
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or path.is_symlink():
        raise RuntimeError('source is not a regular file: ' + str(path))
    with path.open('rb') as handle:
        data = handle.read()
    after = path.stat(follow_symlinks=False)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise RuntimeError('source changed while reading: ' + str(path))
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def origin_audit(items, root):
    rows = []
    for path, dest in items:
        if 'origin-logs' not in dest.parts or path.suffix != '.jsonl':
            continue
        events, pids, errors = Counter(), set(), 0
        archived = root / dest
        if not archived.exists():
            archived = archived.with_name(archived.name + '.gz')
            content = gzip.decompress(archived.read_bytes())
        else:
            content = archived.read_bytes()
        for line in content.splitlines():
            try:
                row = json.loads(line)
                events[row.get('event', '')] += 1
                if type(row.get('pid')) is int:
                    pids.add(row['pid'])
            except (ValueError, TypeError, AttributeError):
                errors += 1
        rows.append({'archive': str(archived.relative_to(root)), 'pids': sorted(pids),
                     'guard_installed': events['guard-installed'] > 0,
                     'exit_audit_present': events['audit-ok'] > 0,
                     'violations': events['VIOLATION'], 'malformed_lines': errors})
    pending = sorted({pid for row in rows if row['guard_installed'] and not row['exit_audit_present']
                      for pid in row['pids'] if pid > 0})
    alive = set()
    for index in range(0, len(pending), 100):
        subset = pending[index:index + 100]
        proc = subprocess.run(['ps', '-p', ','.join(map(str, subset)), '-o', 'pid='],
                              capture_output=True, text=True, timeout=10, check=False)
        if proc.returncode not in (0, 1):
            raise RuntimeError('PID inspection failed')
        alive.update(int(line.strip()) for line in proc.stdout.splitlines() if line.strip().isdigit())
    for row in rows:
        if row['guard_installed'] and not row['exit_audit_present']:
            row['pids_currently_present'] = [pid for pid in row['pids'] if pid in alive]
    return {'observed_utc': datetime.now(timezone.utc).isoformat(),
            'note': 'PID presence is a point-in-time observation and can include PID reuse; no process is signaled.',
            'origin_files': len(rows), 'rows': rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--finalize', action='store_true')
    args = parser.parse_args()
    items = collect()
    if not args.finalize and not args.capture:
        counts = Counter(str(target.parts[0]) for _, target in items)
        print(json.dumps({'candidate_count': len(items), 'groups': dict(counts),
                          'destination_exists': OUT.exists()}, indent=2))
        return
    if args.capture and args.finalize:
        raise RuntimeError('choose one phase')
    if args.capture and (OUT.exists() or STAGING.exists() or CAPTURED.exists()):
        raise RuntimeError('destination or staging already exists; no files overwritten')
    if args.finalize and (not OUT.is_dir() or not CAPTURED.is_file() or STAGING.exists()):
        raise RuntimeError('capture missing or staging exists')
    previous = json.loads(CAPTURED.read_text()) if args.finalize else []
    by_source = {row['source']: row for row in previous}
    STAGING.mkdir(parents=True)
    try:
        manifest = list(previous)
        for source, relative in items:
            data = stable_bytes(source)
            if str(source) in by_source:
                old = by_source[str(source)]
                archived = OUT / old['archive']
                if digest(data) != old['source_sha256'] or digest(archived.read_bytes()) != old['archive_sha256']:
                    raise RuntimeError('previously captured file changed: ' + str(source))
                continue
            compressed = len(data) >= 262144
            if compressed:
                relative = relative.with_name(relative.name + '.gz')
                payload = gzip.compress(data, compresslevel=9, mtime=0)
            else:
                payload = data
            target = STAGING / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as handle:
                handle.write(payload)
            if compressed and gzip.decompress(target.read_bytes()) != data:
                raise RuntimeError('gzip mismatch')
            manifest.append({'source': str(source), 'archive': str(relative),
                             'source_sha256': digest(data), 'archive_sha256': digest(payload),
                             'gzip': compressed})
        # All audited origin files are captured in phase one; later run files
        # require separate review instead of updating the original snapshot.
        if args.capture:
            audit = origin_audit(items, STAGING)
            (Path('/tmp/iter63-r20-archive/origin-audit-initial.json')).write_text(
                json.dumps(audit, indent=2) + '\n')
        # Independently re-read all archive payloads and validate both hashes.
        for row in manifest[len(previous):]:
            payload = (STAGING / row['archive']).read_bytes()
            if digest(payload) != row['archive_sha256']:
                raise RuntimeError('archive checksum mismatch')
            raw = gzip.decompress(payload) if row['gzip'] else payload
            if digest(raw) != row['source_sha256']:
                raise RuntimeError('source checksum mismatch')
        OUT.parent.mkdir(parents=True, exist_ok=True)
        if args.capture:
            shutil.copytree(STAGING, OUT, dirs_exist_ok=False)
        else:
            for row in manifest[len(previous):]:
                target = OUT / row['archive']
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as handle:
                    handle.write((STAGING / row['archive']).read_bytes())
        for row in manifest:
            if digest((OUT / row['archive']).read_bytes()) != row['archive_sha256']:
                raise RuntimeError('destination checksum mismatch')
        if args.capture:
            with CAPTURED.open('x') as handle:
                handle.write(json.dumps(manifest, indent=2) + '\n')
        else:
            audit = origin_audit(items, OUT)
            with (OUT / 'origin-audit-summary.json').open('x') as handle:
                handle.write(json.dumps(audit, indent=2) + '\n')
            audit_bytes = (OUT / 'origin-audit-summary.json').read_bytes()
            manifest.append({'source': str(OUT / 'origin-audit-summary.json'),
                             'archive': 'origin-audit-summary.json',
                             'source_sha256': digest(audit_bytes),
                             'archive_sha256': digest(audit_bytes), 'gzip': False})
            with (OUT / 'artifact-sha256.json').open('x') as handle:
                handle.write(json.dumps(manifest, indent=2) + '\n')
        shutil.rmtree(STAGING)
        print(json.dumps({'archived': len(manifest), 'new': len(manifest) - len(previous),
                          'destination': str(OUT), 'origin_files': audit['origin_files']}, indent=2))
    except BaseException:
        # Preserve the failed staging for inspection; never touch prior evidence.
        raise


if __name__ == '__main__':
    main()
