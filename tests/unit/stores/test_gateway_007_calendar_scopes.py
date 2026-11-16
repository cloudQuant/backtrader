"""007 Gateway Feed calendar scope wiring: offline, synthetic inputs only."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tests.unit.stores.test_iter67_gateway_calendar_dry_run import synthetic_config

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / 'examples/live/007_ctp/gateway_client_runner.py'
spec = importlib.util.spec_from_file_location('gateway_007_calendar_scope_runner', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def config_pair(*, enabled=True, range_read=False):
    config = synthetic_config()
    config['symbols'].append('IH2612')
    config['contracts']['IH2612'] = copy.deepcopy(config['contracts']['IF2612'])
    gateway = config['gateway_strategy']
    instrument = copy.deepcopy(gateway['instruments_by_ref']['main'])
    instrument.update(instrument_id='IH2612', native_symbol='IH2612')
    gateway['instruments_by_ref']['second'] = instrument
    subscription = copy.deepcopy(gateway['market_settings']['subscriptions']['main'])
    subscription['key']['instrument'] = copy.deepcopy(instrument)
    gateway['market_settings']['subscriptions']['second'] = subscription
    config['calendars'] = {'root': 'package_seed'}
    config['trade_logger'] = {'enabled': False}
    if enabled:
        bindings = gateway['client_config']['clients']['gateway']['settings']['bindings']
        bindings.append({**bindings[0], 'mount': 'store.calendar'})
        gateway['calendar_settings'] = {
            'mode': 'SIMULATION_ONLY', 'range_read': range_read,
            'scopes': [
                {'route': 'CTP___FUTURE', 'venue': 'CFFEX', 'kind': 'future',
                 'product': 'IF', 'contract': 'IF2612'},
                {'route': 'CTP___FUTURE', 'venue': 'CFFEX', 'kind': 'future',
                 'product': 'declared-product', 'contract': 'IH2612'},
            ],
        }
    return config


def write_config(tmp_path, config):
    path = tmp_path / 'public.yaml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    return path


@pytest.mark.parametrize('range_read', [False, True])
def test_dry_run_validates_explicit_pair_and_range_grant(tmp_path, capsys, range_read):
    config = config_pair(range_read=range_read)
    path = write_config(tmp_path, config)
    parsed = runner.validate_config(config)
    scopes = runner.gateway_calendar_scopes(parsed, config['symbols'])
    assert scopes['IF2612'] == {'calendar_route': 'CTP___FUTURE', 'calendar_venue': 'CFFEX',
                                'calendar_kind': 'future', 'calendar_product': 'IF',
                                'calendar_contract': 'IF2612'}
    assert scopes['IH2612']['calendar_product'] == 'declared-product'
    operations = parsed.calendar_settings.requested_operations
    assert operations == ({'calendar.query.v1', 'calendar.windows.v1'} if range_read
                          else {'calendar.query.v1'})
    assert runner.main(type('Strategy', (), {}), 'test', tmp_path,
                       ['--config', str(path), '--dry-run']) == 0
    assert 'offline_config_validation' in capsys.readouterr().out


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'conflicting', 'wrong_route',
                                     'wrong_venue', 'wrong_contract', 'unknown', 'feed_override',
                                     'local_scope_override'])
def test_bad_explicit_scopes_refused_during_offline_validation(tmp_path, capsys, mutation):
    config = config_pair()
    settings = config['gateway_strategy']['calendar_settings']
    scopes = settings['scopes']
    if mutation == 'missing': scopes.pop()
    elif mutation == 'duplicate': scopes[1] = copy.deepcopy(scopes[0])
    elif mutation == 'conflicting': scopes[1] = {**scopes[0], 'product': 'OTHER'}
    elif mutation == 'wrong_route': scopes[0]['route'] = 'OTHER'
    elif mutation == 'wrong_venue': scopes[0]['venue'] = 'SHFE'
    elif mutation == 'wrong_contract': scopes[0]['contract'] = 'OTHER'
    elif mutation == 'unknown': scopes[0]['unknown'] = 'unexpected'
    elif mutation == 'feed_override': config['feed'] = {'calendar_product': 'spoof'}
    else: config['calendars']['feed_scope'] = {'product': 'spoof'}
    path = write_config(tmp_path, config)
    assert runner.main(type('Strategy', (), {}), 'test', tmp_path,
                       ['--config', str(path), '--dry-run']) == 2
    assert 'GATEWAY_CONFIG_INVALID' in capsys.readouterr().out


@pytest.mark.parametrize('enabled', [False, True])
def test_main_passes_only_explicit_scopes_to_each_feed(tmp_path, monkeypatch, enabled):
    import backtrader as bt
    import backtrader.live_trading as live
    import backtrader.stores.btapistore as stores
    from contextlib import nullcontext

    config = config_pair(enabled=enabled)
    path = write_config(tmp_path, config)
    seen = {}
    class Broker:
        def setcommission(self, **kwargs): pass
        def get_shutdown_summary(self): return {'status': 'PASS', 'gateway_working_orders': {'unresolved_working_orders': 0}}
    class Store:
        _gateway_start_attempted = False
        _gateway_closed = False
        _gateway_composition_uncertain = False
        _api = _gateway_execution_db = _gateway_run_lock = None
        def __init__(self, **kwargs): pass
        def getbroker(self, **kwargs): return Broker()
        def getdata(self, **kwargs):
            seen[kwargs['dataname']] = kwargs
            return object()
    class Cerebro:
        def __init__(self, **kwargs): pass
        def setbroker(self, *args): pass
        def adddata(self, *args, **kwargs): pass
        def addstrategy(self, *args, **kwargs): pass
        def addanalyzer(self, *args, **kwargs): pass
        def runstop(self): pass
        def run(self): pass
    class Termination(nullcontext):
        request_state = None
    class Writer:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def finish(self, **kwargs): return SimpleNamespace(outcome='PASS', exit_code=0)
    monkeypatch.setattr(runner, 'configure_run_logging', lambda *args: None)
    monkeypatch.setattr(runner, 'resolve_resources', lambda *args, **kwargs: (object(), {}))
    monkeypatch.setattr(stores, 'BtApiStore', Store)
    monkeypatch.setattr(bt, 'Cerebro', Cerebro)
    monkeypatch.setattr(live, 'stop_on_terminate', lambda *args, **kwargs: Termination())
    monkeypatch.setattr(live, 'RunStatusWriter', Writer)
    assert runner.main(type('Strategy', (), {}), 'test', tmp_path, ['--config', str(path)]) == 0
    for symbol, kwargs in seen.items():
        actual = {k: v for k, v in kwargs.items() if k.startswith('calendar_')}
        if enabled:
            scope = next(item for item in config['gateway_strategy']['calendar_settings']['scopes']
                         if item['contract'] == symbol)
            assert actual == {'calendar_' + key: value for key, value in scope.items()}
        else:
            assert actual == {}
    assert set(seen) == set(config['symbols'])


def test_bad_scope_and_unconfigured_root_refuse_before_resources(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, 'resolve_resources', lambda *args, **kwargs: pytest.fail('resources accessed'))
    config = config_pair()
    config['gateway_strategy']['calendar_settings']['scopes'][0]['contract'] = 'OTHER'
    path = write_config(tmp_path, config)
    assert runner.main(type('Strategy', (), {}), 'test', tmp_path, ['--config', str(path)]) == 2
    assert 'GATEWAY_CONFIG_INVALID' in capsys.readouterr().out
    config = config_pair()
    del config['calendars']
    path = write_config(tmp_path, config)
    assert runner.main(type('Strategy', (), {}), 'test', tmp_path, ['--config', str(path)]) == 2
    assert 'calendar_root_unconfigured' in capsys.readouterr().out
