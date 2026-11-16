"""Offline public example configuration and resource boundaries; no services or keys."""
import copy
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / 'examples/live/007_ctp'


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runner = _module('gateway_007_execution_runner', EXAMPLE / 'gateway_client_runner.py')
loader = _module('gateway_007_execution_resources', EXAMPLE / 'gateway_local_resources.py')
TEMPLATES = subprocess.check_output(
    ['git', 'ls-files', 'examples/live/007_ctp/*_gateway/config.yaml'], cwd=ROOT, text=True
).splitlines()


@pytest.mark.parametrize('path', TEMPLATES)
def test_public_template_selects_bounded_execution_and_separate_keys(path):
    assert len(TEMPLATES) == 11
    path = ROOT / path
    config = runner.load_config(path)
    parsed = runner.validate_config(config)
    selection = parsed.execution_selection
    assert parsed.risk_selection is not None
    assert selection is not None
    assert selection.routing.schema_version == 2
    assert selection.security_profile_ref == 'execution-security'
    profiles = loader.validate_security_file_config(parsed, config['gateway_resource_files'], path.parent)
    assert len(profiles) == 3
    routing = config['gateway_strategy']['execution']['routing']
    rules = routing['rules']
    for symbol in config['symbols']:
        selected = [r for r in rules if r['match']['instrument']['native_symbol'] == symbol]
        assert {r['match']['offset'] for r in selected} == {'open', 'close', 'close_today', 'close_yesterday'}
        for rule in selected:
            assert rule['match']['order_types'] == ['limit']
            assert 'side' not in rule['match']
            assert rule['schedule_binding']['price_step'] == format(config['contracts'][symbol]['price_tick'], 'g')
            assert rule['schedule_binding']['quantity_step'] == '1'
            assert rule['trading_day'] == '20260105'
            assert rule['allowed_trading_days'] == ['20260105']
            assert rule['deadline']['at'] == '2026-01-05T15:00:00+08:00'
            if rule['match']['offset'] != 'open':
                assert rule['target_position_ref'].startswith('replace-')


def sample():
    return runner.load_config(ROOT / TEMPLATES[0])


@pytest.mark.parametrize('name', ['risk', 'execution'])
def test_mismatched_logical_trading_run_rejected(name):
    config = sample()
    config['gateway_strategy'][name]['route']['scope']['run_id'] = 'different-run'
    with pytest.raises(ValueError):
        runner.validate_config(config)


def test_unselected_and_top_level_guard():
    config = sample()
    config['gateway_strategy'].pop('execution')
    config['gateway_resource_files'].pop('execution-security')
    parsed = runner.validate_config(config)
    assert parsed.execution_selection is None
    loader.validate_security_file_config(parsed, config['gateway_resource_files'], ROOT)
    config['execution'] = {}
    with pytest.raises(runner.GatewayExecutionConfigUnsupported):
        runner.validate_config(config)


def test_execution_requires_risk_and_invalid_config_never_reads_keys(monkeypatch, tmp_path, capsys):
    config = sample()
    config['gateway_strategy']['risk'] = 'none'
    with pytest.raises(ValueError):
        runner.validate_config(config)
    path = tmp_path / 'config.yaml'
    import yaml
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setattr(runner, 'resolve_resources', lambda *a, **k: pytest.fail('resources opened'))
    assert runner.main(type('Strategy', (), {}), 'test', tmp_path, ['--config', str(path)]) == 2
    assert 'GATEWAY_CONFIG_INVALID' in capsys.readouterr().out


def test_execution_key_reference_and_paths_cannot_overlap():
    config = sample()
    parsed = runner.validate_config(config)
    raw = copy.deepcopy(config['gateway_resource_files'])
    raw['execution-security']['server_public_key_file'] = raw['security']['server_public_key_file']
    with pytest.raises(RuntimeError, match='SECURITY_PROFILES_INVALID'):
        loader.validate_security_file_config(parsed, raw, ROOT)


@pytest.mark.parametrize('version', [6, 7, 8])
def test_resource_loader_accepts_existing_versions_without_upgrading(tmp_path, monkeypatch, version):
    from types import SimpleNamespace
    from backtrader.live_state.state_dir import StrategyStateDir
    from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
    from tests.unit.live_state.test_iter63_gateway_order_bootstrap import _v4, _upgrade

    state = StrategyStateDir.initialize(tmp_path)
    binding = GatewayCommandBinding('journal-a', 'account-a', state.strategy_uuid, 'principal-a')
    _v4(state, binding)
    host = _upgrade(state, binding).upgrade_for_local_notifications()
    if version >= 7:
        host.upgrade_for_risk_routing()
    if version == 8:
        host.upgrade_for_execution_routing()
    before = Path(state.pending.path).read_bytes()
    config = SimpleNamespace(binding=binding, execution_selection=object() if version == 8 else None)
    monkeypatch.setattr(loader, '_security_profiles', lambda *args: {})
    loader.load_local_resources(config, strategy_dir=tmp_path, first_init=False,
                                upgrade_state=False, security_files={})
    assert Path(state.pending.path).read_bytes() == before
    if version == 8:
        config.execution_selection = None
        with pytest.raises(RuntimeError, match='GATEWAY_STATE_EXECUTION_SELECTION_REQUIRED'):
            loader.load_local_resources(config, strategy_dir=tmp_path, first_init=False,
                                        upgrade_state=False, security_files={})
        assert Path(state.pending.path).read_bytes() == before


def test_expired_template_rejects_each_limit_route_before_execution():
    import sqlite3
    from decimal import Decimal
    from bt_api_py._contracts.models import OrderRequest, OrderType, Side
    from bt_api_py.execution_routing import ExecutionOrderRouter, ExecutionRoutingOutcome, install_execution_routing_tables
    from bt_api_py.gateway_direct_client import build_gateway_order_intent

    config = sample()
    parsed = runner.validate_config(config)
    db = sqlite3.connect(':memory:', isolation_level=None)
    try:
        db.execute('BEGIN IMMEDIATE')
        install_execution_routing_tables(db)
        db.commit()
        router = ExecutionOrderRouter(db=db, config=parsed.execution_selection.routing,
                                      execution_port=None, risk_selected=True,
                                      clock=lambda: 1800000000000000000)
        for symbol in config['symbols']:
            for side in (Side.BUY, Side.SELL):
                for offset in ('open', 'close', 'close_today', 'close_yesterday'):
                    key = f'{symbol}-{side.value}-{offset}'
                    request = OrderRequest(symbol=symbol, side=side, order_type=OrderType.LIMIT,
                        quantity=Decimal('1'), account_id='account', client_order_id=key,
                        price=Decimal('100'), idempotency_key=key, quantity_unit='contracts',
                        exchange_id=config['contracts'][symbol]['exchange'], offset=offset)
                    intent = build_gateway_order_intent(parsed.binding, parsed.route, request, ttl_seconds=10)
                    result = router.route(intent)
                    assert result.outcome is ExecutionRoutingOutcome.EXECUTION_REJECTED
                    assert result.code == 'EXECUTION_DEADLINE_EXPIRED'
    finally:
        db.close()


def test_protected_curve_files_load_all_profiles_and_reject_bad_execution_pair(tmp_path):
    import os
    import zmq
    from bt_api_py.service_runtime import ClientCurveKeys

    if os.name != 'posix':
        pytest.skip('local protected key loader requires POSIX')
    config = sample()
    parsed = runner.validate_config(config)
    directory = tmp_path.resolve() / 'keys'
    directory.mkdir(mode=0o700)
    expected, raw = {}, {}
    for name in ('security', 'risk-security', 'execution-security'):
        server_public, _ = zmq.curve_keypair()
        public, secret = zmq.curve_keypair()
        expected[name] = (server_public, public, secret)
        values = (server_public, public, secret)
        fields = ('server_public_key_file', 'client_public_key_file', 'client_secret_key_file')
        paths = {}
        for field, value in zip(fields, values):
            path = directory / (name + '-' + field)
            path.write_bytes(value + b'\n')
            path.chmod(0o600)
            paths[field] = str(path)
        raw[name] = paths
    loaded = loader._security_profiles(parsed, raw, directory)
    assert set(loaded) == set(expected)
    for name, values in expected.items():
        assert isinstance(loaded[name], ClientCurveKeys)
        assert (loaded[name].server_key, loaded[name].public_key, loaded[name].secret_key) == values
    bad_public, _ = zmq.curve_keypair()
    Path(raw['execution-security']['client_public_key_file']).write_bytes(bad_public + b'\n')
    with pytest.raises(RuntimeError, match='CURVE_KEY_PAIR_INVALID'):
        loader._security_profiles(parsed, raw, directory)


@pytest.mark.parametrize('explicit', [True, False])
def test_main_keeps_logical_run_and_uses_process_run_id_for_writer(tmp_path, monkeypatch, explicit):
    import uuid
    import yaml
    import backtrader as bt
    import backtrader.live_trading as live
    import backtrader.live_state as live_state
    import backtrader.stores.btapistore as store_module
    from contextlib import nullcontext
    from types import SimpleNamespace

    config = sample()
    config['trade_logger'] = {'enabled': False}
    path = tmp_path / 'public-config.yaml'
    path.write_text(yaml.safe_dump(config))
    original = path.read_bytes()
    seen = {}

    def resources(name, *, config, **kwargs):
        seen['resource_routes'] = (config.route, config.risk_selection.route,
                                   config.execution_selection.route)
        return object(), {}

    class Broker:
        def setcommission(self, **kwargs): pass
        def get_shutdown_summary(self): return {'status': 'PASS', 'gateway_working_orders': {'unresolved_working_orders': 0}}

    class Store:
        def __init__(self, *, config, **kwargs):
            seen['store_config'] = config['gateway_strategy']
        def getbroker(self, **kwargs): return Broker()
        def getdata(self, **kwargs): return object()

    class Cerebro:
        def __init__(self, **kwargs): pass
        def setbroker(self, broker): pass
        def adddata(self, data, **kwargs): pass
        def addstrategy(self, strategy, **kwargs): pass
        def addanalyzer(self, analyzer, **kwargs): pass
        def run(self): pass

    class Termination(nullcontext):
        request_state = None

    class Writer:
        def __init__(self, directory, **kwargs): seen['writer_id'] = kwargs['run_id']
        def start(self): pass
        def finish(self, **kwargs): return SimpleNamespace(outcome='PASS', exit_code=0)

    monkeypatch.setattr(runner, 'configure_run_logging', lambda *args: None)
    monkeypatch.setattr(runner, 'resolve_resources', resources)
    monkeypatch.setattr(store_module, 'BtApiStore', Store)
    monkeypatch.setattr(bt, 'Cerebro', Cerebro)
    def termination(*args, **kwargs):
        seen['stop_id'] = kwargs['stop_request_run_id']
        return Termination()
    monkeypatch.setattr(live, 'stop_on_terminate', termination)
    monkeypatch.setattr(live, 'RunStatusWriter', Writer)
    monkeypatch.setattr(live_state, 'load_identity', lambda *args: SimpleNamespace(strategy_uuid='strategy'))
    requested = '3c92edfe-7e69-4a1b-9a87-54d2a9e42c03'
    args = ['--config', str(path)] + (
        ['--run-id', requested, '--stop-request-file', str(tmp_path / 'stop')] if explicit else []
    )
    assert runner.main(type('Strategy', (), {}), 'synthetic', tmp_path, args) == 0
    run_id = seen['writer_id']
    assert str(uuid.UUID(run_id)) == run_id
    if explicit:
        assert run_id == requested
        assert seen['stop_id'] == run_id
    logical_run = config['gateway_strategy']['route']['scope']['run_id']
    assert run_id != logical_run
    assert {route.scope.run_id for route in seen['resource_routes']} == {logical_run}
    gateway = seen['store_config']
    assert {gateway['route']['scope']['run_id'], gateway['risk']['route']['scope']['run_id'],
            gateway['execution']['route']['scope']['run_id']} == {logical_run}
    assert gateway == config['gateway_strategy']
    assert path.read_bytes() == original


def test_main_stop_file_without_run_id_rejected_before_resource_access(tmp_path, monkeypatch, capsys):
    import json
    import yaml
    path = tmp_path / 'public-config.yaml'
    path.write_text(yaml.safe_dump(sample()))
    monkeypatch.setattr(runner, 'resolve_resources', lambda *args, **kwargs: pytest.fail('resources accessed'))
    assert runner.main(type('Strategy', (), {}), 'synthetic', tmp_path,
                       ['--config', str(path), '--stop-request-file', str(tmp_path / 'stop')]) == 2
    assert json.loads(capsys.readouterr().out)['error_code'] == 'stop_request_requires_run_id'
