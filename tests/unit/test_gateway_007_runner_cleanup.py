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
    import signal
    import backtrader as bt
    import backtrader.live_trading as live
    import backtrader.stores.btapistore as stores
    import calendar_gate

    original_handlers = {getattr(signal, name): signal.getsignal(getattr(signal, name))
                         for name in ('SIGTERM', 'SIGBREAK') if hasattr(signal, name)}
    seen = SimpleNamespace(fail=None, objects=[], native_writes=0, stops=0, finishes=[], heartbeats=0, heartbeat_live=False, finish_raises=False, summary_signal=None, finish_signal=None, exit_code=None)
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
            if seen.fail == 'guard_install': self._api = object()
            if seen.fail == 'feed': raise RuntimeError('secret feed')
            return object()
        def stop(self, timeout=None):
            seen.stops += 1
            if seen.fail == 'guard_install': raise RuntimeError('secret stop error')
            self._gateway_start_attempted = True
            self._gateway_closed = True
            self._api = self._gateway_execution_db = self._gateway_run_lock = None
            self._gateway_composition_uncertain = False

    class Broker:
        def setcommission(self, **kwargs): pass
        def get_shutdown_summary(self):
            if seen.summary_signal: raise seen.summary_signal('secret summary signal')
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
            if seen.fail == 'exit_code': raise SystemExit(seen.exit_code)
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
            if seen.finish_signal: raise seen.finish_signal('secret finish signal')
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
    try:
        yield seen
    finally:
        for signum, handler in original_handlers.items():
            signal.signal(signum, handler)
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


@pytest.mark.parametrize('with_run_id,expected', [
    (False, 'stop_request_requires_run_id'),
    (True, 'stop_request_identity_unavailable'),
])
def test_stop_request_setup_has_finite_original_code(scenario, monkeypatch, tmp_path, capsys, with_run_id, expected):
    import backtrader.live_state as live_state
    def fail_identity(_):
        raise RuntimeError('secret identity failure')
    monkeypatch.setattr(live_state, 'load_identity', fail_identity)
    args = ['--stop-request-file', str(tmp_path / 'stop')]
    if with_run_id:
        args += ['--run-id', '3c92edfe-7e69-4a1b-9a87-54d2a9e42c03']
    assert runner.main(type('Strategy', (), {}), 'test', tmp_path, args) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'BLOCKED' and result['error_code'] == expected
    assert scenario.stops == 0 and not RETAINED


@pytest.mark.parametrize('phase', ['summary', 'finish'])
@pytest.mark.parametrize('signal_type', [KeyboardInterrupt, SystemExit])
def test_summary_and_finish_interrupts_propagate_after_cleanup(scenario, phase, signal_type, capsys):
    setattr(scenario, phase + '_signal', signal_type)
    with pytest.raises(signal_type) as caught:
        scenario.run()
    assert 'secret' not in str(caught.value)
    assert 'secret' not in capsys.readouterr().out
    assert scenario.stops == 1 and scenario.heartbeats == 1
    assert len(scenario.finishes) == 1 and not scenario.heartbeat_live and not RETAINED


@pytest.mark.parametrize('signal_type', [KeyboardInterrupt, SystemExit])
def test_finish_interrupt_does_not_escape_unconfirmed_cleanup(scenario, signal_type):
    scenario.fail = 'inner_uncertain'
    scenario.finish_signal = signal_type
    def inspect(lifecycle):
        assert lifecycle in RETAINED and lifecycle.store is scenario.objects[0]
        assert scenario.heartbeats == 1 and not scenario.heartbeat_live
        assert len(scenario.finishes) == 1
        raise Escape()
    with pytest.raises(Escape):
        scenario.run(inspect)
    assert scenario.stops == 1 and len(scenario.objects) == 1


@pytest.mark.parametrize('code,expected', [(None, None), (0, 0), (2, 2), ('secret exit code', 1)])
def test_clean_system_exit_preserves_safe_code(scenario, capsys, code, expected):
    scenario.fail = 'exit_code'
    scenario.exit_code = code
    with pytest.raises(SystemExit) as caught:
        scenario.run()
    assert caught.value.code == expected
    assert 'secret' not in capsys.readouterr().out
    assert scenario.stops == 1 and scenario.heartbeats == 1


@pytest.mark.parametrize('clean', [True, False])
def test_terminate_guard_covers_real_context_exit_join(clean):
    """Only fake Store/Cerebro are used; the real TerminateStop restores its handler before join."""
    import os
    import selectors
    import signal
    import subprocess
    import time

    if os.name != 'posix':
        pytest.skip('POSIX signal behavior')
    code = '''
import signal, sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from gateway_runner_lifecycle import RunnerLifecycle
from backtrader.live_trading import stop_on_terminate
class Cerebro:
    _run_active = True
    def runstop(self): print("RUNSTOP", flush=True)
class Join:
    def join(self, timeout):
        print("JOIN", flush=True)
        sys.stdin.readline()
lifecycle = RunnerLifecycle(object(), {})
lifecycle.store = SimpleNamespace(_gateway_start_attempted=True, _gateway_closed=sys.argv[2] == "clean",
    _gateway_composition_uncertain=False, _api=None if sys.argv[2] == "clean" else object(),
    _gateway_execution_db=None, _gateway_run_lock=None)
lifecycle.runstrategies_entered = True
termination = stop_on_terminate(Cerebro())
lifecycle.termination = termination
original = signal.getsignal(signal.SIGTERM)
lifecycle.install_signal_guard()
print("BEFORE", flush=True)
sys.stdin.readline()
with termination:
    lifecycle.deliver_guarded_stop()
    termination._deliverer = Join()
    print("RUN", flush=True)
    sys.stdin.readline()
confirmed = lifecycle.prepare_cleanup()
if confirmed:
    lifecycle.restore_signal_guard()
    assert signal.getsignal(signal.SIGTERM) == original
    print("CLEAN", flush=True)
else:
    lifecycle.arm_retention()
    lifecycle.retain()
    raise AssertionError("retained wait returned")
'''
    process = subprocess.Popen([sys.executable, '-u', '-c', code, str(EXAMPLE),
                                'clean' if clean else 'uncertain'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        def line():
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                result = bytearray()
                while not result.endswith(b'\n'):
                    assert selector.select(timeout=10), 'child did not reach expected phase'
                    byte = os.read(process.stdout.fileno(), 1)
                    assert byte, 'child exited before expected phase'
                    result.extend(byte)
                return result.decode().strip()

        assert line() == 'BEFORE'
        os.kill(process.pid, signal.SIGTERM)
        process.stdin.write('\n'); process.stdin.flush()
        assert line() == 'RUNSTOP'  # Signal during outer guard is delivered on entry.
        assert line() == 'RUN'
        os.kill(process.pid, signal.SIGTERM)
        assert line() == 'RUNSTOP'  # Normal active-run SIGTERM still requests runstop.
        process.stdin.write('\n'); process.stdin.flush()
        assert line() == 'JOIN'  # TerminateStop has already restored the outer guard.
        os.kill(process.pid, signal.SIGTERM)
        time.sleep(0.1)
        assert process.poll() is None
        process.stdin.write('\n'); process.stdin.flush()
        if clean:
            assert line() == 'CLEAN'
            assert process.wait(timeout=5) == 0
        else:
            assert json.loads(line())['error_code'] == 'GATEWAY_CLEANUP_UNCERTAIN'
            time.sleep(0.1)
            assert process.poll() is None
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize('signal_type', [KeyboardInterrupt, SystemExit])
def test_later_finish_interrupt_overrides_ordinary_run_failure(scenario, signal_type):
    scenario.fail = 'inner_clean'
    scenario.finish_signal = signal_type
    with pytest.raises(signal_type) as caught:
        scenario.run()
    assert 'secret' not in str(caught.value)
    assert scenario.stops == 1 and scenario.heartbeats == 1 and not scenario.heartbeat_live


def test_guard_install_error_with_uncertain_cleanup_is_retained(scenario, monkeypatch, capsys):
    scenario.fail = 'guard_install'
    def failed_install(_):
        raise RuntimeError('secret signal guard error')
    monkeypatch.setattr(RunnerLifecycle, 'install_signal_guard', failed_install)
    def inspect(lifecycle):
        assert lifecycle in RETAINED and lifecycle.store is scenario.objects[0]
        assert scenario.stops == 1 and scenario.heartbeats == 1
        raise Escape()
    with pytest.raises(Escape):
        scenario.run(inspect)
    assert 'secret' not in capsys.readouterr().out


def test_uncertain_cleanup_never_restores_guard(scenario, monkeypatch):
    scenario.fail = 'inner_uncertain'
    def failed_restore(_):
        raise AssertionError('must not restore before cleanup is confirmed')
    with monkeypatch.context() as patch:
        patch.setattr(RunnerLifecycle, 'restore_signal_guard', failed_restore)
        with pytest.raises(Escape):
            scenario.run(lambda lifecycle: (_ for _ in ()).throw(Escape()))

def test_market_data_only_observation_only_is_a_clean_stop():
    summary = {
        "status": "UNKNOWN",
        "gateway_status": "OBSERVATION_ONLY",
        "market_data_only": True,
        "active_order_count": 0,
        "observed_remote_open_order_count": 0,
        "gateway_working_orders": {"unresolved_working_orders": 0},
    }
    assert runner.contract_broker_summary(summary)["status"] == "STOPPED"


def test_observation_only_without_market_data_only_stays_unknown():
    summary = {
        "status": "UNKNOWN",
        "gateway_status": "OBSERVATION_ONLY",
        "active_order_count": 0,
        "gateway_working_orders": {"unresolved_working_orders": 0},
    }
    assert runner.contract_broker_summary(summary)["status"] == "UNKNOWN"
