"""Isolated Root local-component gate; synthetic data, no account or provider."""
from pathlib import Path
import hashlib
import json
import os
import stat
import sys
import time

ROOT = Path('D:/source_code/backtrader')
MON = Path('D:/bt_api_py/bt_api/bt_api_monitor')
BASE = Path('D:/bt_api_py/bt_api/bt_api_base/src')
SITE = Path('D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages')
PINS = {
    'src/bt_api_monitor/__init__.py': (5970, 'f0b816c83f92d0e01ccc92f8f9e20ba67acde7ccb439289c4148ea581574617a'),
    'src/bt_api_monitor/durable.py': (25889, 'fec232682272bd1295a12821222a7d687ee59ca9a2c216b080f7eb67b3706f0e'),
    'src/bt_api_monitor/readonly_events.py': (27217, '91e2dd7c9f19b2b09b4b22247506e800135e513448f9aca11a73fb0ed5363631'),
    'tests/test_readonly_events.py': (26508, 'e3ed4e4bbf7e28b5d1fc21c4f0267c7b06785b273e2c5366b4269119b3e4ce8a'),
}
OUT = ROOT / 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-bt-api-monitor-readonly-events-r3-root-local-gate-2026-10-08'


def verify_sources():
    for relative, (size, digest) in PINS.items():
        path = MON / relative
        path.relative_to(MON)
        before = path.lstat()
        assert stat.S_ISREG(before.st_mode) and not path.is_symlink()
        assert not (getattr(before, 'st_file_attributes', 0) & 0x400)
        assert before.st_size == size and size <= 128 * 1024
        with path.open('rb') as stream:
            raw = stream.read(size + 1)
        after = path.stat()
        assert len(raw) == size and hashlib.sha256(raw).hexdigest() == digest
        assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)


def main():
    assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
    assert tuple(sys.version_info[:2]) == (3, 11)
    verify_sources()
    os.environ.pop('PYTHONPATH', None)
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    sys.path[:0] = [str(MON / 'src'), str(BASE), str(SITE)]
    ini = ROOT / '.codex-tmp/monr3-root-empty.ini'
    with ini.open('xb') as stream:
        stream.write(b'')
    temp = ROOT / '.codex-tmp/monr3-root-t'
    assert not temp.exists() and temp.resolve().parent == (ROOT / '.codex-tmp').resolve()
    import pytest
    started = time.monotonic()
    code = int(pytest.main(['-q', '--noconftest', '-c', str(ini),
                           str(MON / 'tests/test_readonly_events.py'), '--tb=short',
                           '--basetemp', str(temp)]))
    import bt_api_monitor
    import bt_api_monitor.durable as durable
    import bt_api_monitor.readonly_events as readonly
    import bt_api_base
    origins = {
        'bt_api_monitor': Path(bt_api_monitor.__file__).resolve() == (MON / 'src/bt_api_monitor/__init__.py').resolve(),
        'bt_api_monitor.durable': Path(durable.__file__).resolve() == (MON / 'src/bt_api_monitor/durable.py').resolve(),
        'bt_api_monitor.readonly_events': Path(readonly.__file__).resolve() == (MON / 'src/bt_api_monitor/readonly_events.py').resolve(),
        'bt_api_base': Path(bt_api_base.__file__).resolve().is_relative_to(BASE.resolve()),
    }
    verify_sources()
    result = {'schema': 'iteration41.monitor.readonly.r3.root-local-component-gate.v1',
              'classification': 'LOCAL_COMPONENT_ONLY', 'pytest_exit_code': code,
              'source_pins_verified_before_after': True, 'origin_checks': origins,
              'sdk_parent_imported': 'bt_api_py' in sys.modules,
              'elapsed_seconds': round(time.monotonic() - started, 6),
              'interpreter': str(Path(sys.executable).resolve()),
              'python_flags': ['-I', '-S', '-B', '-X', 'utf8'],
              'pytest_plugin_autoload_disabled': True, 'PYTHONPATH_removed': True,
              'project_conftest_disabled': True, 'synthetic_event_fixture': True,
              'provider_or_account_called': False, 'formal_case_pass_count': 0,
              'files': {k: {'bytes': v[0], 'sha256': v[1]} for k, v in PINS.items()}}
    OUT.mkdir()
    raw = (json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
    with (OUT / 'observation.json').open('xb') as stream:
        stream.write(raw)
    print(json.dumps({'status': 'LOCAL_GATE_PASSED' if code == 0 and all(origins.values()) else 'LOCAL_GATE_FAILED',
                      'observation_sha256': hashlib.sha256(raw).hexdigest(),
                      'pytest_exit_code': code, 'origin_checks': origins,
                      'formal_case_pass_count': 0}, sort_keys=True), flush=True)
    return code if code else (0 if all(origins.values()) else 2)


if __name__ == '__main__':
    raise SystemExit(main())
