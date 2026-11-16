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
pytestmark = pytest.mark.skipif(os.name != 'posix', reason='local setup requires POSIX')


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob('*') if path.is_file()}


def test_prepare_and_verify_then_refuse_repeat_without_overwriting(tmp_path):
    state = prepare_gateway_state(tmp_path)
    assert str(uuid.UUID(state.strategy_uuid, version=4)) == state.strategy_uuid
    marker = tmp_path / 'state/gateway_example_init.json'
    assert json.loads(marker.read_text()) == {'version': 1, 'strategy_uuid': state.strategy_uuid}
    assert marker.stat().st_mode & 0o777 == 0o600
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
    folder.mkdir(mode=0o700)
    (folder / 'identity.json').write_bytes(content)
    before = snapshot(tmp_path)
    with pytest.raises(RuntimeError, match='STATE_SETUP_NOT_EMPTY'):
        prepare_gateway_state(tmp_path)
    assert snapshot(tmp_path) == before


def test_pristine_companion_without_identity_is_not_replaced(tmp_path):
    folder = tmp_path / 'state'
    folder.mkdir(mode=0o700)
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
    (strategy / 'state').symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
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
        if fullname.startswith(("bt_api_", "backtrader.strategies")):
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
        (tmp_path / 'state').mkdir(mode=0o700)
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
