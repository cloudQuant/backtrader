"""Offline lifecycle tests: no Gateway, provider, or native trade is started."""
import importlib.util
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

EXAMPLE = Path(__file__).resolve().parents[2] / 'examples/live/007_ctp'
sys.path.insert(0, str(EXAMPLE))
spec = importlib.util.spec_from_file_location('gateway_cleanup_test_runner', EXAMPLE / 'gateway_client_runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from gateway_runner_lifecycle import RETAINED, RunnerLifecycle


class Escape(BaseException):
    pass


@pytest.fixture
def scenario(monkeypatch, tmp_path):
    import backtrader as bt
    import backtrader.live_trading as live
    import backtrader.stores.btapistore as stores
    import calendar_gate

    seen = SimpleNamespace(fail=None, objects=[], native_writes=0, stops=0, finishes=[], heartbeats=0, heartbeat_live=False, finish_raises=False)
    key = SimpleNamespace(native_symbol='X', venue='V')
    parsed = SimpleNamespace(instruments_by_ref={'x': key}, exchange_name='E', execution_selection=None)
    config = {'gateway_resource_provider': 'fake', 'gateway_strategy': {}, 'symbols': ['X'],
              'contracts': {'X': {'quantity_unit': 'contracts', 'time_in_force': 'DAY', 'price_tick': 1}},
              'trade_logger': {'enabled': False}}
    host, profiles = object(), {'p': object()}
    monkeypatch.setattr(runner, 'load_config', lambda _: config)
    monkeypatch.setattr(runner, 'validate_config', lambda _: parsed)
    monkeypatch.setattr(runner, 'gateway_calendar_scopes', lambda *_: {})
    monkeypatch.setattr(runner, 'configure_run_logging', lambda *_: None)
    monkeypatch.setattr(runner, 'resolve_resources', lambda *a, **k: (host, profiles))
    monkeypatch.setattr(calendar_gate, 'check_gateway_calendar', lambda *a, **k: SimpleNamespace(code=None))

    class Store:
        def __init__(self, **kwargs):
            if seen.fail == 'store':
                raise RuntimeError('secret constructor')
            seen.objects.append(self)
            self._gateway_start_attempted = False
            self._gateway_closed = False
            self._gateway_composition_uncertain = False
            self._api = self._gateway_execution_db = self._gateway_run_lock = None
        def getbroker(self, **kwargs):
            if seen.fail == 'broker': raise RuntimeError('secret broker')
            return Broker()
        def getdata(self, **kwargs):
            if seen.fail == 'feed': raise RuntimeError('secret feed')
            return object()
        def stop(self, timeout=None):
            seen.stops += 1
            self._gateway_start_attempted = True
            self._gateway_closed = True
            self._api = self._gateway_execution_db = self._gateway_run_lock = None
            self._gateway_composition_uncertain = False

    class Broker:
        def setcommission(self, **kwargs): pass
        def get_shutdown_summary(self):
            if seen.fail == 'summary': raise RuntimeError('secret summary')
            return {'status': 'OBSERVATION_ONLY'}

    class Cerebro:
        def __init__(self, **kwargs): pass
        def setbroker(self, broker): pass
        def adddata(self, data, **kwargs): pass
        def addstrategy(self, strategy, **kwargs): pass
        def addanalyzer(self, analyzer, **kwargs):
            if seen.fail == 'analyzer': raise RuntimeError('secret analyzer')
        def runstrategies(self):
            store = seen.objects[0]
            store._gateway_start_attempted = True
            store._api = object()
            store._gateway_execution_db = object()
            store._gateway_run_lock = object()
            if seen.fail in ('inner_uncertain', 'inner_interrupt', 'inner_exit'):
                # Cerebro attempted a partial stop but the original API and lock remain.
                seen.stops += 1
                if seen.fail == 'inner_interrupt': raise KeyboardInterrupt('secret interrupt')
                if seen.fail == 'inner_exit': raise SystemExit('secret exit')
                raise RuntimeError('secret inner')
            store.stop()
            if seen.fail == 'inner_clean': raise RuntimeError('secret inner clean')
            if seen.fail == 'interrupt_clean': raise KeyboardInterrupt('secret interrupt')
            if seen.fail == 'exit_clean': raise SystemExit('secret exit')
        def run(self):
            if seen.fail == 'pre_run': raise RuntimeError('secret pre run')
            self.runstrategies()

    class Termination(nullcontext):
        request_state = None
    class Writer:
        def __init__(self, *a, **k):
            if seen.fail == 'writer_init': raise RuntimeError('secret writer init')
        def start(self):
            seen.heartbeat_live = True
            if seen.fail == 'writer_start': raise RuntimeError('secret writer start')
        def finish(self, **kwargs):
            seen.finishes.append(kwargs)
            if seen.fail == 'finish' or seen.finish_raises: raise RuntimeError('secret finish')
            return SimpleNamespace(outcome='UNKNOWN', exit_code=1)
        def stop_heartbeat(self):
            seen.heartbeats += 1
            seen.heartbeat_live = False

    monkeypatch.setattr(stores, 'BtApiStore', Store)
    monkeypatch.setattr(bt, 'Cerebro', Cerebro)
    monkeypatch.setattr(live, 'stop_on_terminate', lambda *a, **k: Termination())
    monkeypatch.setattr(live, 'RunStatusWriter', Writer)
    seen.host, seen.profiles = host, profiles
    seen.run = lambda hook=None: runner.main(type('Strategy', (), {}), 'test', tmp_path, [], _retained_wait=hook)
    yield seen
    RETAINED.clear()


@pytest.mark.parametrize('phase', ['store', 'broker', 'feed', 'writer_init', 'writer_start', 'analyzer', 'pre_run', 'inner_clean', 'summary', 'finish'])
def test_failure_is_bounded_and_does_not_repeat_confirmed_stop(scenario, capsys, phase):
    scenario.fail = phase
    assert scenario.run() == (1 if phase in ('pre_run', 'inner_clean', 'summary', 'finish') else 2)
    out = capsys.readouterr().out
    assert 'secret' not in out
    assert all(json.loads(line)['error_code'].startswith('GATEWAY_') for line in out.splitlines())
    assert scenario.stops == (1 if phase in ('inner_clean', 'summary', 'finish') else 0)
    assert scenario.native_writes == 0
    if phase in ('writer_start', 'analyzer', 'pre_run', 'inner_clean', 'summary', 'finish'):
        assert scenario.heartbeats == 1 and not scenario.heartbeat_live
    if phase == 'summary': assert scenario.finishes[0]['broker_summary'] is None
    if phase == 'inner_clean': assert scenario.finishes[0]['broker_summary']['status'] == 'UNKNOWN'


@pytest.mark.parametrize('phase', ['inner_uncertain', 'inner_interrupt', 'inner_exit'])
@pytest.mark.parametrize('finish_raises', [False, True])
def test_unconfirmed_keeps_same_objects_and_never_restarts(scenario, capsys, phase, finish_raises):
    scenario.fail = phase
    scenario.finish_raises = finish_raises
    def inspect(lifecycle):
        assert lifecycle in RETAINED
        assert lifecycle.store is scenario.objects[0]
        assert lifecycle.host is scenario.host and lifecycle.profiles is scenario.profiles
        assert lifecycle.contract is not None and lifecycle.termination is not None
        assert len(scenario.finishes) == 1
        assert scenario.finishes[0]["broker_summary"] is None
        assert scenario.finishes[0]["exception"] is not None
        from backtrader.live_trading.run_status import derive_outcome
        outcome, flags = derive_outcome(**scenario.finishes[0])
        assert outcome == "CRASHED" and flags["unknown_unresolved"] is True
        assert scenario.heartbeats == 1 and not scenario.heartbeat_live
        raise Escape()
    with pytest.raises(Escape): scenario.run(inspect)
    assert len(scenario.objects) == 1 and scenario.stops == 1
    assert scenario.native_writes == 0
    assert 'GATEWAY_CLEANUP_UNCERTAIN' in capsys.readouterr().out


def test_before_run_one_bounded_stop_and_unreadable_state_is_uncertain():
    class Store:
        _gateway_start_attempted = False
        _gateway_closed = False
        _gateway_composition_uncertain = False
        _gateway_execution_db = None
        _gateway_run_lock = None
        _api = object()
        calls = 0
        def stop(self, timeout):
            assert timeout == 5.0
            self.calls += 1
            self._api = None
    lifecycle = RunnerLifecycle(object(), {})
    lifecycle.store = Store()
    assert lifecycle.prepare_cleanup() is True
    assert lifecycle.store.calls == 1 and lifecycle.cleanup_confirmed()
    class Unreadable:
        @property
        def _gateway_start_attempted(self): raise RuntimeError()
    lifecycle.store = Unreadable()
    assert lifecycle.cleanup_confirmed() is False


def test_cli_wait_does_not_exit_on_termination_signals():
    import os
    import selectors
    import signal
    import subprocess
    import time

    if os.name != 'posix':
        pytest.skip('POSIX signal behavior')
    code = """
import sys
sys.path.insert(0, sys.argv[1])
from gateway_runner_lifecycle import RunnerLifecycle
lifecycle = RunnerLifecycle(object(), {})
lifecycle.store = object()
lifecycle.runstrategies_entered = True
assert lifecycle.prepare_cleanup() is False
lifecycle.retain()
raise AssertionError('retained wait returned')
"""
    process = subprocess.Popen([sys.executable, '-c', code, str(EXAMPLE)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=10), 'retained state was not emitted'
            assert json.loads(process.stdout.readline())['error_code'] == 'GATEWAY_CLEANUP_UNCERTAIN'
        for sig in (signal.SIGINT, signal.SIGTERM):
            os.kill(process.pid, sig)
            time.sleep(0.1)
            assert process.poll() is None
    finally:
        process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize('phase,error', [('interrupt_clean', KeyboardInterrupt), ('exit_clean', SystemExit)])
def test_clean_interrupt_escapes_only_after_cleanup_and_status(scenario, phase, error):
    scenario.fail = phase
    with pytest.raises(error) as caught:
        scenario.run()
    assert 'secret' not in str(caught.value)
    assert scenario.stops == 1 and scenario.heartbeats == 1
    assert not scenario.heartbeat_live and len(scenario.finishes) == 1


@pytest.mark.parametrize('field,value', [('_api', object()), ('_gateway_run_lock', object()),
    ('_gateway_execution_db', object()), ('_gateway_composition_uncertain', True),
    ('_gateway_composition_uncertain', None), ('_gateway_closed', False)])
def test_each_started_store_cleanup_fact_is_required(field, value):
    store = SimpleNamespace(_api=None, _gateway_run_lock=None, _gateway_execution_db=None,
        _gateway_composition_uncertain=False, _gateway_start_attempted=True, _gateway_closed=True)
    lifecycle = RunnerLifecycle(object(), {})
    lifecycle.store = store
    assert lifecycle.cleanup_confirmed() is True
    setattr(store, field, value)
    assert lifecycle.cleanup_confirmed() is False
