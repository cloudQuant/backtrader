from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or '..' in pure.parts or not pure.parts:
        raise RuntimeError('unsafe manifest path')
    return Path(*pure.parts)


def copy_checked(source: Path, target: Path, expected_bytes: int, expected_sha256: str) -> None:
    if not source.is_file():
        raise RuntimeError(f'missing pinned input: {source.name}')
    if source.stat().st_size != expected_bytes or sha256(source) != expected_sha256:
        raise RuntimeError(f'pinned input mismatch: {source.name}')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size != expected_bytes or sha256(target) != expected_sha256:
            raise RuntimeError(f'clean-root collision: {target.name}')
        return
    shutil.copyfile(source, target)


def find_repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / 'backtrader_runtime').is_dir() and (candidate / 'docs').is_dir():
            return candidate
    raise RuntimeError('repository root not found')


def main() -> int:
    round_dir = Path(__file__).resolve().parent.parent
    manifest = json.loads((round_dir / 'manifest.json').read_text(encoding='utf-8'))
    repo_root = find_repo_root()
    packet = repo_root / safe_relative(manifest['r2_packet']['path'])
    packet_pins_path = packet / 'pins.json'
    packet_pins = json.loads(packet_pins_path.read_text(encoding='utf-8'))
    if packet_pins_path.stat().st_size != manifest['r2_packet']['pins_bytes'] or sha256(packet_pins_path) != manifest['r2_packet']['pins_sha256']:
        raise RuntimeError('R2 packet pins do not match the frozen packet identity')

    for row in packet_pins['packet_files']:
        rel = safe_relative(row['path'])
        path = packet / rel
        if path.stat().st_size != row['bytes'] or sha256(path) != row['sha256']:
            raise RuntimeError(f'R2 packet file mismatch: {rel.name}')
    for row in packet_pins['source_payload_files']:
        rel = safe_relative(row['path'])
        path = packet / 'source' / rel
        if path.stat().st_size != row['bytes'] or sha256(path) != row['sha256']:
            raise RuntimeError(f'R2 source snapshot mismatch: {rel.name}')

    temp_base = repo_root / '.codex-tmp'
    temp_base.mkdir(exist_ok=True)
    clean_root = Path(tempfile.mkdtemp(prefix='c01d2-', dir=temp_base))
    clean_packet = clean_root / packet.name
    shutil.copytree(packet, clean_packet)

    for row in packet_pins['source_payload_files']:
        rel = safe_relative(row['path'])
        copy_checked(packet / 'source' / rel, clean_root / rel, row['bytes'], row['sha256'])

    for row in manifest['test_only_snapshots']:
        snapshot = round_dir / safe_relative(row['snapshot'])
        target = clean_root / safe_relative(row['path'])
        copy_checked(snapshot, target, row['bytes'], row['sha256'])

    test_copies = [
        'test_certification_simnow_c01_root_custody_v16_source_fake.py',
        'test_certification_simnow_c01_root_entry_v18_source_fake.py',
        'test_certification_simnow_c01_root_v16_source_fake.py',
        'test_root_activation_wrapper_r1_source_fake.py',
    ]
    for name in test_copies:
        source = clean_packet / 'reference' / 'v18-tests' / name
        row = next(item for item in packet_pins['packet_files'] if item['path'] == f'reference/v18-tests/{name}')
        copy_checked(source, clean_root / 'tests' / 'unit' / 'runtime' / name, row['bytes'], row['sha256'])

    r1_id = packet_pins['r1_parent_diagnostic_packet_id']
    r1_source = clean_packet / 'reference' / 'r1-parent-diagnostic' / 'observation.json'
    r1_pin = next(item for item in packet_pins['packet_files'] if item['path'] == 'reference/r1-parent-diagnostic/observation.json')
    copy_checked(r1_source, clean_root / r1_id / 'observation.json', r1_pin['bytes'], r1_pin['sha256'])

    config = clean_root / 'pytest.ini'
    config.write_text('[pytest]\n', encoding='utf-8')
    site_packages = Path(sys.prefix) / 'Lib' / 'site-packages'
    if not site_packages.is_dir():
        raise RuntimeError('expected isolated Windows site-packages directory is unavailable')
    os.chdir(clean_root)
    os.environ.pop('PYTHONPATH', None)
    os.environ.pop('PYTEST_ADDOPTS', None)
    os.environ.pop('PYTEST_PLUGINS', None)
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    sys.path[:0] = [str(clean_root), str(site_packages)]

    import pytest

    if sys.version_info[:2] != (3, 11) or pytest.__version__ != '8.0.0':
        raise RuntimeError(f'expected Python 3.11 and pytest 8.0.0; observed {sys.version.split()[0]} and pytest {pytest.__version__}')

    class PathOnlyBootstrap:
        def pytest_collection_modifyitems(self, session, config, items):
            driver = sys.modules.get('_simnow_v18_root_driver_source_fake')
            if driver is None:
                raise RuntimeError('frozen R2 source-fake driver was not collected')
            expected_packet = clean_root / driver.PACKET_ID
            if driver.PACKET_DIR.resolve() != expected_packet.resolve():
                raise RuntimeError('frozen packet copy path mismatch')
            driver.ROOT = clean_root
            driver.EVIDENCE = clean_root
            driver.V18_PACKET_DIR = expected_packet / 'reference' / 'v18-activation'
            driver.R1_DIAGNOSTIC_COPY = 'reference/r1-parent-diagnostic/observation.json'
            packet_diag = expected_packet / driver.R1_DIAGNOSTIC_COPY
            alias_diag = clean_root / driver.R1_DIAGNOSTIC_PACKET_ID / 'observation.json'
            if sha256(packet_diag) != driver.R1_DIAGNOSTIC_SHA256 or sha256(alias_diag) != driver.R1_DIAGNOSTIC_SHA256:
                raise RuntimeError('pinned R1 diagnostic copy mismatch')
            if sha256(driver.V18_PACKET_DIR / 'pins.json') != driver.V18_PINS_SHA256:
                raise RuntimeError('pinned V18 activation pins mismatch')

        def pytest_runtest_call(self, item):
            wrapper = item.funcargs.get('wrapper')
            if wrapper is not None:
                wrapper.REPO_ROOT = clean_root

    tests = [
        clean_packet / 'qa' / 'test_root_actual_driver_source_fake.py',
        clean_packet / 'reference' / 'v18-tests' / 'test_root_activation_wrapper_r1_source_fake.py',
    ]
    args = [
        *(str(path) for path in tests),
        '-q',
        '-p', 'no:cacheprovider',
        '-c', str(config),
        '--rootdir', str(clean_root),
        '--confcutdir', str(clean_root),
        '--basetemp', str(clean_root / 'pytest-basetemp'),
    ]
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        exit_code = int(pytest.main(args, plugins=[PathOnlyBootstrap()]))
    text = output.getvalue().replace('\r\n', '\n').replace('\r', '\n')
    output_path = round_dir / 'qa' / 'pytest-output.txt'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding='utf-8')
    sys.stdout.write(text)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
