"""Offline Gateway initialization: temporary directories only, no account activity."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from backtrader.live_state.gateway_initialization import (
    _write_new_identity_marker,
    prepare_gateway_state,
    verify_gateway_preparation,
)
from backtrader.live_state.state_dir import StrategyStateDir

ROOT = Path(__file__).resolve().parents[3]
RUNNER_DIR = ROOT / 'examples/live/007_ctp'


def _mkdir_owner_only(path: Path) -> None:
    """Create an owner-only directory on POSIX (0o700) or Windows (owner-only DACL)."""
    path.mkdir(mode=0o700)
    if os.name == 'nt':
        from bt_api_py._win32_security import _set_owner_only_acl
        _set_owner_only_acl(path)


def _assert_marker_owner_only(marker: Path) -> None:
    if os.name == 'posix':
        assert marker.stat().st_mode & 0o777 == 0o600
    else:
        from bt_api_py._win32_security import inspect_owner
        info = inspect_owner(marker)
        assert info.is_current_user and not info.others_writable


def snapshot(directory):
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in directory.rglob('*') if path.is_file()}


def test_prepare_and_verify_then_refuse_repeat_without_overwriting(tmp_path):
    state = prepare_gateway_state(tmp_path)
    assert str(uuid.UUID(state.strategy_uuid, version=4)) == state.strategy_uuid
    marker = tmp_path / 'state/gateway_example_init.json'
    assert json.loads(marker.read_text()) == {'version': 1, 'strategy_uuid': state.strategy_uuid}
    _assert_marker_owner_only(marker)
    assert (tmp_path / 'state/gateway_example_init.reserve').is_file()
    assert (tmp_path / '.gateway_example_init.reserve').is_file()
    verify_gateway_preparation(state)
    before = snapshot(tmp_path)
    with pytest.raises(RuntimeError, match='STATE_SETUP_NOT_EMPTY'):
        prepare_gateway_state(tmp_path)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('content', [b'{bad', b'{}', b'{"version":1,"strategy_uuid":"x"}'])
def test_nonempty_or_corrupt_state_is_never_touched(tmp_path, content):
    folder = tmp_path / 'state'
    _mkdir_owner_only(folder)
    (folder / 'identity.json').write_bytes(content)
    before = snapshot(tmp_path)
    with pytest.raises(RuntimeError, match='STATE_SETUP_NOT_EMPTY'):
        prepare_gateway_state(tmp_path)
    assert snapshot(tmp_path) == before


def test_pristine_companion_without_identity_is_not_replaced(tmp_path):
    folder = tmp_path / 'state'
    _mkdir_owner_only(folder)
    (folder / 'sequence.json').write_text('{}')
    before = snapshot(tmp_path)
    with pytest.raises(RuntimeError, match='STATE_SETUP_NOT_EMPTY'):
        prepare_gateway_state(tmp_path)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('point', ['before_identity', 'before_marker'])
def test_partial_failure_never_rebuilds_identity(tmp_path, monkeypatch, point):
    import backtrader.live_state.gateway_initialization as init
    if point == 'before_identity':
        monkeypatch.setattr(init.StrategyStateDir, 'initialize', lambda *_: (_ for _ in ()).throw(RuntimeError('private detail')))
    else:
        monkeypatch.setattr(init, '_write_marker_at', lambda *_: (_ for _ in ()).throw(RuntimeError('private detail')))
    with pytest.raises(RuntimeError, match='private detail'):
        prepare_gateway_state(tmp_path)
    before = snapshot(tmp_path)
    assert 'state/gateway_example_init.reserve' in before
    assert ('state/identity.json' in before) == (point == 'before_marker')
    with pytest.raises(RuntimeError, match='STATE_SETUP_NOT_EMPTY'):
        prepare_gateway_state(tmp_path)
    assert snapshot(tmp_path) == before


def test_existing_legacy_marker_still_verifies_and_rejects_corruption(tmp_path):
    state = StrategyStateDir.initialize(tmp_path)
    _write_new_identity_marker(state)
    verify_gateway_preparation(state)
    marker = tmp_path / 'state/gateway_example_init.json'
    marker.write_text('{"version":1,"version":1,"strategy_uuid":"x"}')
    with pytest.raises(RuntimeError, match='STATE_SETUP_MARKER_INVALID'):
        verify_gateway_preparation(state)


def test_symlink_state_directory_is_not_followed(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    strategy = tmp_path / 'strategy'
    strategy.mkdir()
    link = strategy / 'state'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            raise
        # Non-elevated Windows supports NTFS directory junctions (reparse points).
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                       check=True, capture_output=True)
    if os.name == 'posix':
        with pytest.raises(OSError):
            prepare_gateway_state(strategy)
    else:
        with pytest.raises(RuntimeError, match='STATE_SETUP_DIRECTORY_UNTRUSTED'):
            prepare_gateway_state(strategy)
    assert list(outside.iterdir()) == []


def cli(directory, *extra):
    return subprocess.run([sys.executable, '-m', 'backtrader.live_state', 'gateway-init', str(directory), *extra],
                          cwd=ROOT, capture_output=True, text=True, timeout=30)


def test_cli_subprocess_success_and_repeat_are_bounded(tmp_path):
    result = cli(tmp_path)
    assert result.returncode == 0 and result.stderr == ''
    assert len(result.stdout.splitlines()) == 1 and str(tmp_path) not in result.stdout
    body = json.loads(result.stdout)
    assert set(body) == {'ok', 'code', 'strategy_uuid'}
    assert body['ok'] is True and body['code'] == 'GATEWAY_LOCAL_STATE_INITIALIZED'
    assert str(uuid.UUID(body['strategy_uuid'], version=4)) == body['strategy_uuid']
    before = snapshot(tmp_path)
    second = cli(tmp_path)
    assert second.returncode == 1 and second.stderr == ''
    assert json.loads(second.stdout) == {'ok': False, 'code': 'GATEWAY_LOCAL_STATE_INITIALIZATION_FAILED'}
    assert str(tmp_path) not in second.stdout and snapshot(tmp_path) == before
    invalid = cli(tmp_path, 'private-argument')
    assert invalid.returncode == 2 and invalid.stderr == ''
    assert 'private-argument' not in invalid.stdout and str(tmp_path) not in invalid.stdout


def test_concurrent_cli_initialization_has_exactly_one_winner(tmp_path):
    command = [sys.executable, '-m', 'backtrader.live_state', 'gateway-init', str(tmp_path)]
    children = [subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for _ in range(2)]
    outcomes = [(child.returncode, out, err)
                for child in children for out, err in [child.communicate(timeout=30)]]
    assert sorted(code for code, _, _ in outcomes) == [0, 1]
    assert all(not err and len(out.splitlines()) == 1 for _, out, err in outcomes)
    success = next(json.loads(out) for code, out, _ in outcomes if code == 0)
    state = StrategyStateDir(tmp_path)
    assert state.strategy_uuid == success['strategy_uuid']
    verify_gateway_preparation(state)


def test_example_first_init_uses_same_state_and_needs_operator_configuration(tmp_path):
    sys.path.insert(0, str(RUNNER_DIR))
    try:
        spec = importlib.util.spec_from_file_location('gateway_local_resources_test', RUNNER_DIR / 'gateway_local_resources.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with pytest.raises(module.ResourceSetupRequired) as exc:
            module.load_local_resources(None, strategy_dir=tmp_path, first_init=True,
                                        upgrade_state=False, security_files=None)
        assert exc.value.code == 'LOCAL_STATE_INITIALIZED_CONFIGURE_IDENTITY'
        verify_gateway_preparation(StrategyStateDir(tmp_path))
    finally:
        sys.path.pop(0)


@pytest.mark.parametrize('kind', ['cli', 'example'])
def test_preparation_does_not_load_sdk_user_strategy_or_open_network(tmp_path, kind):
    (tmp_path / 'config.yaml').write_text('sensitive configuration')
    (tmp_path / '.env').write_text('sensitive environment')
    (tmp_path / 'private.key').write_text('sensitive key')
    code = """
import builtins, importlib.abc, importlib.util, os, runpy, socket, sys
attempts = []
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("bt_api_", "backtrader.strategies") if os.name == "posix" else (
            "backtrader.strategies", "bt_api_ctp", "bt_api_okx", "bt_api_binance",
            "bt_api_gateway", "bt_api_risk", "bt_api_execution", "bt_api_monitor",
        )
        if fullname.startswith(blocked):
            attempts.append(fullname)
            raise AssertionError("forbidden import")
sys.meta_path.insert(0, Block())
def no_network(*args, **kwargs):
    raise AssertionError("forbidden network")
socket.socket.connect = no_network
socket.socket.connect_ex = no_network
original_open = builtins.open
def guarded_open(file, *args, **kwargs):
    if isinstance(file, (str, bytes, os.PathLike)) and os.path.basename(os.fsdecode(file)) in (
        "config.yaml", ".env", "private.key"
    ):
        raise AssertionError("protected file opened")
    return original_open(file, *args, **kwargs)
builtins.open = guarded_open
import backtrader
def no_run(*args, **kwargs):
    raise AssertionError("Cerebro was run")
backtrader.Cerebro.run = no_run
root, kind = sys.argv[1:3]
if kind == "cli":
    sys.argv = ["backtrader.live_state", "gateway-init", root]
    try:
        runpy.run_module("backtrader.live_state", run_name="__main__")
    except SystemExit:
        assert not attempts, attempts
        raise
else:
    spec = importlib.util.spec_from_file_location("gateway_local_resources", sys.argv[3])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.load_local_resources(None, strategy_dir=root, first_init=True,
                                    upgrade_state=False, security_files=None)
    except module.ResourceSetupRequired as exc:
        assert exc.code == "LOCAL_STATE_INITIALIZED_CONFIGURE_IDENTITY"
    else:
        raise AssertionError("setup result missing")
    assert not attempts, attempts
"""
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path), kind,
                             str(RUNNER_DIR / 'gateway_local_resources.py')], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stderr == ''
    if kind == 'cli':
        assert json.loads(result.stdout)['code'] == 'GATEWAY_LOCAL_STATE_INITIALIZED'


@pytest.mark.parametrize('point', ['before_marker', 'after_marker'])
def test_directory_replacement_is_detected_and_original_evidence_retained(tmp_path, monkeypatch, point):
    import backtrader.live_state.gateway_initialization as init
    def swap():
        (tmp_path / 'state').rename(tmp_path / 'detached')
        _mkdir_owner_only(tmp_path / 'state')
    if point == 'before_marker':
        original = init.StrategyStateDir.initialize
        def initialize(*args):
            result = original(*args)
            swap()
            return result
        monkeypatch.setattr(init.StrategyStateDir, 'initialize', initialize)
    else:
        original = init._write_marker_at
        def write_marker(*args):
            original(*args)
            swap()
        monkeypatch.setattr(init, '_write_marker_at', write_marker)
    with pytest.raises(RuntimeError, match='STATE_SETUP_DIRECTORY_CHANGED'):
        prepare_gateway_state(tmp_path)
    assert (tmp_path / 'detached/gateway_example_init.reserve').exists()
    assert (tmp_path / 'detached/identity.json').exists()
    assert (tmp_path / 'detached/gateway_example_init.json').exists() == (point == 'after_marker')
    assert list((tmp_path / 'state').iterdir()) == []
    old_uuid = json.loads((tmp_path / 'detached/identity.json').read_text())['strategy_uuid']
    before = snapshot(tmp_path)
    monkeypatch.undo()
    with pytest.raises(RuntimeError, match='STATE_SETUP_ALREADY_ATTEMPTED'):
        prepare_gateway_state(tmp_path)
    assert json.loads((tmp_path / 'detached/identity.json').read_text())['strategy_uuid'] == old_uuid
    assert not (tmp_path / 'state/identity.json').exists()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('location', ['state/gateway_example_init.reserve', '.gateway_example_init.reserve'])
def test_replaced_reservation_is_detected_and_identity_not_rebuilt(tmp_path, monkeypatch, location):
    import backtrader.live_state.gateway_initialization as init
    original = init.StrategyStateDir.initialize
    def initialize(*args):
        state = original(*args)
        reservation = tmp_path / location
        reservation.unlink()
        reservation.write_bytes(b'')
        return state
    monkeypatch.setattr(init.StrategyStateDir, 'initialize', initialize)
    with pytest.raises(RuntimeError, match='STATE_SETUP_RESERVATION_CHANGED'):
        prepare_gateway_state(tmp_path)
    before = snapshot(tmp_path)
    assert 'state/identity.json' in before and 'state/gateway_example_init.json' not in before
    with pytest.raises(RuntimeError, match='STATE_SETUP_NOT_EMPTY'):
        prepare_gateway_state(tmp_path)
    assert snapshot(tmp_path) == before


def test_failure_before_state_creation_preserves_root_reservation(tmp_path, monkeypatch):
    import backtrader.live_state.gateway_initialization as init
    def fail_mkdir(*args, **kwargs):
        raise OSError('synthetic failure')
    if os.name == 'nt' and hasattr(init, '_mkdir_owner_only_windows'):
        monkeypatch.setattr(init, '_mkdir_owner_only_windows', fail_mkdir)
    else:
        monkeypatch.setattr(init.os, 'mkdir', fail_mkdir)
    with pytest.raises(OSError, match='synthetic failure'):
        prepare_gateway_state(tmp_path)
    assert (tmp_path / '.gateway_example_init.reserve').is_file()
    assert not (tmp_path / 'state').exists()
    before = snapshot(tmp_path)
    monkeypatch.undo()
    with pytest.raises(RuntimeError, match='STATE_SETUP_ALREADY_ATTEMPTED'):
        prepare_gateway_state(tmp_path)
    assert not (tmp_path / 'state').exists() and snapshot(tmp_path) == before


def test_prepare_calls_verify_gateway_preparation_before_returning(tmp_path, monkeypatch):
    import backtrader.live_state.gateway_initialization as init
    called = []

    def failing_verify(state):
        called.append(state.strategy_uuid)
        raise RuntimeError('STATE_SETUP_MARKER_INVALID')

    monkeypatch.setattr(init, 'verify_gateway_preparation', failing_verify)
    with pytest.raises(RuntimeError, match='STATE_SETUP_MARKER_INVALID'):
        prepare_gateway_state(tmp_path)
    assert len(called) == 1


@pytest.mark.skipif(os.name != 'nt', reason='Windows Win32 security verification vector')
def test_windows_verify_does_not_swallow_programming_error(tmp_path, monkeypatch):
    import bt_api_py._win32_security as win32_sec

    state = prepare_gateway_state(tmp_path)
    monkeypatch.setattr(
        win32_sec,
        'read_bounded_windows',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AttributeError('synthetic_bug')),
    )
    with pytest.raises(AttributeError, match='synthetic_bug'):
        verify_gateway_preparation(state)


@pytest.mark.skipif(os.name != 'nt', reason='Windows Win32 marker disappearance vector')
def test_windows_missing_marker_raises_finite_error(tmp_path):
    state = prepare_gateway_state(tmp_path)
    marker = tmp_path / 'state/gateway_example_init.json'
    marker.unlink()
    with pytest.raises(RuntimeError, match='STATE_SETUP_MARKER_INVALID'):
        verify_gateway_preparation(state)


@pytest.mark.skipif(os.name != 'nt', reason='Windows Win32 reservation mutation vector')
def test_windows_modified_reservation_size_is_rejected(tmp_path, monkeypatch):
    import backtrader.live_state.gateway_initialization as init

    original = init.StrategyStateDir.initialize

    def mutate_reservation(*args):
        state = original(*args)
        (tmp_path / 'state/gateway_example_init.reserve').write_bytes(b'x')
        return state

    monkeypatch.setattr(init.StrategyStateDir, 'initialize', mutate_reservation)
    with pytest.raises(RuntimeError, match='STATE_SETUP_RESERVATION_CHANGED'):
        prepare_gateway_state(tmp_path)


@pytest.mark.skipif(os.name != 'nt', reason='Windows Win32 owner-only state_dir vector')
def test_windows_state_dir_created_owner_only(tmp_path):
    from bt_api_py._win32_security import inspect_owner

    prepare_gateway_state(tmp_path)
    info = inspect_owner(tmp_path / 'state', others_may_write_check=True)
    assert info.is_current_user and not info.others_writable
    for reserve in (tmp_path / '.gateway_example_init.reserve', tmp_path / 'state/gateway_example_init.reserve'):
        rinfo = inspect_owner(reserve, others_may_write_check=True)
        assert rinfo.is_current_user and not rinfo.others_writable
