"""Authenticated synthetic CTP day switch during one real 007 lifecycle.

The market adapter is deliberately inert: this exercises no market-data or
native order capability. Calendar composition, registration, reads, and the
BT Store/Broker/Feed/Cerebro lifecycle are real. This does not exercise the
complete Risk, Execution, Monitor or Runtime order chain.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest
import zmq
import bt_api_py


@pytest.mark.skipif(not zmq.has("curve"), reason="CURVE unavailable")
def test_formal_mock_native_day_switch_in_one_007_lifecycle(tmp_path):
    sdk = Path(os.environ.get("BT_API_TEST_SDK_ROOT", Path(bt_api_py.__file__).resolve().parent.parent)).resolve()
    bt = Path(__file__).resolve().parents[2]
    script = r'''
import ast, contextlib, datetime as dt, io, json, os, runpy, shutil, subprocess, sys, threading
from copy import deepcopy
from pathlib import Path
import pytest, yaml
import backtrader as bt
import bt_api_py
import bt_api_ctp
installed = os.environ.get('BT_API_TEST_INSTALLED_ROOT')
if installed:
    installed = Path(installed).resolve()
    assert Path(bt.__file__).resolve().is_relative_to(installed)
    assert Path(bt_api_py.__file__).resolve().is_relative_to(installed)
    assert Path(bt_api_ctp.__file__).resolve().is_relative_to(installed)
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_py.gateway_strategy_client import GatewayStrategyClientSession
from bt_api_py.gateway_strategy_config import GatewayStrategyConfig
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_runtime import ClientCurveKeys
from bt_api_py.trading_calendar_mock_publication import MockCalendarPublication
from bt_api_py import trading_calendar_mock_cli as mock_cli
from tests.integration.test_ctp_gateway_operator_calendar import configured, application
from tests.test_iter63_ctp_gateway_trading import FakeSession
from tests.test_iter63_gateway_direct_owner import wait_for
from tests.unit.test_gateway_calendar_day_switch import reconnect
from tests.unit.test_trading_calendar_observation_run import env_without_network
from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
import backtrader.service.gateway_market_adapter as market_adapter

root = Path(os.environ['CASE_ROOT']); btroot = Path(os.environ['BT_ROOT'])
sys.path.insert(0, os.environ['CTP_TEST_ROOT'])
from test_iter63_gateway_session import prepared
mp = pytest.MonkeyPatch()
initial_threads = {t.ident for t in threading.enumerate() if not t.daemon}
child = subprocess.run([sys.executable, '-m', 'bt_api_py.trading_calendar_observation_run', 'run',
    '--mock', '--mock-year', '2026', '--budget-seconds', '30', '--trusted-local-posix'],
    env=env_without_network(root), capture_output=True, text=True, timeout=180)
assert child.returncode == 10, (child.stdout, child.stderr)
run = json.loads(child.stdout.splitlines()[-1]); calendar_root = run['simulation_root']
operator = MockCalendarPublication(root=calendar_root, run_id=run['run_id'])
assert operator.initialize(mode='manual')['status'] == 'INITIALIZED'
proposal = operator.prepare(candidate_id=run['derived_id'])
assert operator.publish(proposal=proposal, publication_id='MOCK_pub1', version_id='MOCK_v1',
    reviewer='MOCK_reviewer', confirmed_at='2026-11-13T00:00:00.000000Z', emit=lambda _: None)['status'] == 'COMMITTED'

doc, file, svc_config, public, secret = configured(root, mp, bootstrap=False)
scope = doc['clients'][0]['resources'][0]['scope']; ident = doc['clients'][0]['identity']; peer = doc['authority']['identity']
cal_scope = dict(route='CTP___FUTURE', venue='SHFE', kind='future', product='mock_future', contract='mock_shfe_future_contract')
grant = doc['calendars']['grants'][0]; grant.update(cal_scope)
policy = doc['calendars']['range_policies'][0]; policy.update(cal_scope); policy['max_advance_days'] = 3
doc['calendars']['root'] = calendar_root
doc['calendars']['day_switch'] = dict(source='CTP_AUTHENTICATED_SESSION',
    poll_interval_seconds=0.02, owner_wait_seconds=0.1, close_timeout_seconds=2)
doc['clients'][0]['resources'][0]['operations'] = ['direct.command_status']
file.write_text(json.dumps(doc), encoding='utf-8')

native_root = root / 'native-fixture'; native_root.mkdir()
create_real, _, _, feeds, natives, _, _, _ = prepared.__wrapped__(native_root, mp)
original_connect, original_close = FakeSession.connect, FakeSession.close
calls = []
def connect(shell, *, generation, timeout):
    original_connect(shell, generation=generation, timeout=timeout)
    shell.calendar_delegate = create_real()
    shell.calendar_delegate.connect(generation=generation, timeout=timeout)
    calls.append(('connected', threading.get_ident()))
def close(shell):
    assert shell.calendar_delegate.close() is True
    calls.append(('closed', threading.get_ident()))
    return original_close(shell)
def capture(shell):
    token = shell.calendar_delegate.capture_calendar_session()
    calls.append(('capture', threading.get_ident(), token))
    return token
def is_current(shell, token):
    result = shell.calendar_delegate.calendar_session_is_current(token)
    calls.append(('current', threading.get_ident(), result, token.trading_day))
    return result
mp.setattr(FakeSession, 'connect', connect)
mp.setattr(FakeSession, 'close', close)
mp.setattr(FakeSession, 'capture_calendar_session', capture, raising=False)
mp.setattr(FakeSession, 'calendar_session_is_current', is_current, raising=False)

# Extract the public synthetic config builder without importing BT's tests package
# into this SDK-tests-first interpreter.
source = (btroot / 'tests/unit/stores/test_iter67_gateway_calendar_dry_run.py').read_text()
tree = ast.parse(source); node = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'synthetic_config')
namespace = {'deepcopy': deepcopy}; exec(compile(ast.Module(body=[node], type_ignores=[]), '<fixture>', 'exec'), namespace)
config = namespace['synthetic_config'](); config.update(calendars={'root': 'package_seed'}, broker={'market_data_only': True}, trade_logger={'enabled': False})
symbol = cal_scope['contract']; config['symbols'] = [symbol]; config['contracts'] = {symbol: dict(exchange='SHFE', quantity_unit='contracts', time_in_force='GFD', price_tick=0.2)}
g = config['gateway_strategy']; g['binding'] = dict(journal_id=doc['settings']['expected_journal_id'], account_scope=scope['account_ref'], strategy_scope=ident['actor_ref'], principal=ident['principal_ref'])
g['route']['identity'] = ident; g['route']['scope'] = dict(scope, run_id='run-a'); g['route'].update(service_id=peer['actor_ref'], instance_id='gateway-a', scope_ref='scope-a')
g['peer'] = peer; g['requested_operations'] = ['direct.command_status']
instrument = g['instruments_by_ref']['main']; instrument.update(venue='SHFE', instrument_id=symbol, native_symbol=symbol)
g['market_settings']['subscriptions']['main']['key']['instrument'] = deepcopy(instrument)
g['calendar_settings'] = dict(mode='SIMULATION_ONLY', scopes=[cal_scope], range_read=True)
client = g['client_config']; client['registration']['strategy_ref'] = ident['actor_ref']
endpoint = svc_config.communication['profiles']['server-transport']['endpoints']['rpc_bind']
for b in client['clients']['gateway']['settings']['bindings']:
    b.update(service_id=peer['actor_ref'], instance_id='gateway-a', scope_ref='scope-a')
    if 'account_ref' in b: b['account_ref'] = scope['account_ref']
client['clients']['gateway']['settings']['bindings'].append(dict(client['clients']['gateway']['settings']['bindings'][0], mount='store.calendar'))
client['communication']['profiles']['transport']['endpoints']['rpc_connect'] = endpoint

# Isolate only the non-calendar market runtime. All direct/calendar registrations,
# CURVE, session and calendar reads remain the production implementations.
def create_session(self, *, host, security_profiles, cancel_host=None, delegated_cancel_host=None):
    v = self._values()
    client_copy = v['client_config'].to_public_dict()
    bindings = client_copy['clients']['gateway']['settings']['bindings']
    bindings[:] = [entry for entry in bindings if entry['mount'] != 'store.market']
    client_copy['communication']['profiles']['transport']['endpoints'].pop('market_connect')
    return GatewayStrategyClientSession(parse_client_config(client_copy), binding=v['binding'], route=v['route'], peer=v['peer'],
        security_profiles=security_profiles, host=host, cancel_host=cancel_host, delegated_cancel_host=delegated_cancel_host,
        requested_operations=v['requested_operations'], calendar_settings=v['calendar_settings'])
mp.setattr(GatewayStrategyConfig, 'create_session', create_session)
class EmptyMarket:
    def __init__(self, *a, **k): pass
    def start(self): pass
    def close(self): pass
    def recovery_reason(self, *a): return 'SYNTHETIC_MARKET_ISOLATED'
    def poll(self): return None
mp.setattr(market_adapter, 'GatewayMarketAdapter', EmptyMarket)

runner = runpy.run_path(str(btroot / 'examples/live/007_ctp/gateway_client_runner.py'))
main = runner['main']; run_globals = main.__globals__
path = root / 'input.yaml'; path.write_text(yaml.safe_dump(config), encoding='utf-8')
state = StrategyStateDir.initialize(root)
binding = GatewayCommandBinding(**g['binding'])
GatewayPendingHost.upgrade_for_gateway(root, state.strategy_uuid, binding)
GatewayPendingHost.upgrade_for_cancellation(root, state.strategy_uuid, binding)
consumer = gateway_execution_consumer_ref(principal_ref=ident['principal_ref'], actor_ref=ident['actor_ref'],
    execution_domain_ref=scope['execution_domain_ref'], account_scope=scope['account_ref'], strategy_scope=ident['actor_ref'])
GatewayPendingHost.upgrade_for_execution(root, state.strategy_uuid, binding, consumer_ref=consumer)
host = GatewayPendingHost.upgrade_for_order_state(root, state.strategy_uuid, binding)
run_globals['resolve_resources'] = lambda *a, **k: (host, {'security': ClientCurveKeys(doc['authority']['curve_public_key'].encode('ascii'), public, secret)})
seen = []
stores = []
def read_feed(feed, day, expected, night_day):
    session = feed.trading_session(trading_day=day)
    start = dt.datetime.combine(night_day, dt.time(13), tzinfo=dt.timezone.utc)
    windows = feed.trading_windows(start, start + dt.timedelta(hours=1))
    store = feed.store.trading_calendar_query(
        cal_scope['route'], venue=cal_scope['venue'], kind=cal_scope['kind'],
        product=cal_scope['product'], contract=cal_scope['contract'],
        trading_day=day, mode='SIMULATION_ONLY')
    for item in (session, windows):
        assert item.status == 'COMPLETE'
        b = item.gateway_binding
        assert b.calendar_ref == expected and b.load_status == 'CURRENT'
        assert (b.data_origin, b.source_authentication, b.trade_authorization) == ('SYNTHETIC_MOCK', 'NOT_PROVEN', 'NONE')
    assert store.status == 'COMPLETE'
    assert store.registration_id == session.gateway_binding.registration_id == windows.gateway_binding.registration_id
    assert store.binding['calendar_ref'] == expected
    assert store.binding['data_origin'] == 'SYNTHETIC_MOCK'
    assert (store.source_authentication, store.trade_authorization) == ('NOT_PROVEN', 'NONE')
    assert store.binding['bound_trading_day'] == day.isoformat()
    afternoon = [window for window in session.windows if window.window_id == 'afternoon']
    assert len(afternoon) == 1
    expected_end = dt.time(15, 0) if expected == 'MOCK_v1' else dt.time(14, 30)
    assert afternoon[0].end_local.time() == expected_end
    assert [row['end_utc'] for row in store.windows if row['window_id'] == 'afternoon'] == [
        dt.datetime.combine(day, dt.time(7 if expected == 'MOCK_v1' else 6,
                                         0 if expected == 'MOCK_v1' else 30), tzinfo=dt.timezone.utc).isoformat().replace('+00:00', 'Z')]
    assert [(w.window_id, w.trading_day, w.start_utc) for w in windows.windows] == [('night', day, start)]
    assert windows.incomplete is False
    return session.gateway_binding

class Probe(bt.Strategy):
    def start(self):
        f = self.datas[0]
        stores.append(f.store)
        first, second = dt.date(2026, 11, 6), dt.date(2026, 11, 9)
        def initial_ready():
            return f.trading_session(trading_day=first).status == 'COMPLETE'
        wait_for(initial_ready, timeout=15)
        before = read_feed(f, first, 'MOCK_v1', dt.date(2026, 11, 5))
        first_token = [entry[2] for entry in calls if entry[0] == 'capture'][-1]
        assert first_token.trading_day == '20261106'
        pending = mock_cli.update(root=calendar_root, run_id=run['run_id'], variant='AFTERNOON_CHANGE')
        assert pending['status'] == 'PENDING_REVIEW'
        committed = mock_cli._confirm(operator, review_id=pending['review_id'],
            review_sha256=pending['review_payload_sha256'], reviewer='MOCK_reviewer',
            confirmed_at='2026-11-13T00:00:00.000000Z')
        assert committed['status'] == 'COMMITTED'
        old_count = sum(entry[0] == 'capture' for entry in calls)
        reconnect(feeds[0], natives[0], mp, first)
        wait_for(lambda: sum(entry[0] == 'capture' for entry in calls) >= old_count + 2, timeout=8)
        same_token = [entry[2] for entry in calls if entry[0] == 'capture'][-1]
        assert same_token.trading_day == first_token.trading_day
        assert same_token.connection_generation > first_token.connection_generation
        same = read_feed(f, first, 'MOCK_v1', dt.date(2026, 11, 5))
        assert same == before
        reconnect(feeds[0], natives[0], mp, second)
        def advanced():
            result = f.trading_session(trading_day=second)
            return result.status == 'COMPLETE' and result.calendar_ref == pending['version_id']
        wait_for(advanced, timeout=15)
        after = read_feed(f, second, pending['version_id'], first)
        assert (after.registration_id, after.service_epoch, after.source_generation) == (
            before.registration_id, before.service_epoch, before.source_generation)
        assert after.bound_trading_day == second
        assert any(entry[0] == 'current' and entry[2:] == (True, '20261109') for entry in calls)
        assert natives[0].calls == []
        seen.append(True)
        self.env.runstop()

app = application(svc_config, root / 'launch.yaml')
def run_once():
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(Probe, 'formal mock', root, ['--config', str(path), '--run-seconds', '5'])
    assert code == 1
    assert json.loads(output.getvalue().splitlines()[-1]) == {'status': 'UNKNOWN', 'mode': 'gateway', 'exit_code': 1}
    store = stores[-1]
    assert store._gateway_closed and store._api is None and store._gateway_run_lock is None
    assert store._broker.get_shutdown_summary()['status'] == 'OBSERVATION_ONLY'
    assert all(not feed._session_active for feed in store._data_feeds)

try:
    app.start(timeout_seconds=10)
    run_once()
    assert seen == [True]
finally:
    app.stop(timeout_seconds=10)
    assert app.status['state'] == 'closed'
    assert sum(entry[0] == 'closed' for entry in calls) == 1
    assert len({entry[1] for entry in calls}) == 1
    assert not any(t.name == 'ctp-calendar-day-switch' and t.is_alive() for t in threading.enumerate())
    assert not [t.name for t in threading.enumerate() if not t.daemon and t.ident not in initial_threads]
    mp.undo(); shutil.rmtree(calendar_root)
'''
    installed = os.environ.get("BT_API_TEST_INSTALLED_ROOT")
    paths = ([installed] if installed else []) + [str(sdk), str(bt)]
    ctp_tests = os.environ.get("BT_API_TEST_CTP_TEST_ROOT", str(sdk / "bt_api/bt_api_ctp/tests"))
    env = {"PATH": os.defpath, "PYTHONPATH": os.pathsep.join(paths),
           "CASE_ROOT": str(tmp_path), "BT_ROOT": str(bt), "CTP_TEST_ROOT": ctp_tests,
           "PYTHONDONTWRITEBYTECODE": "1"}
    if installed:
        env["BT_API_TEST_INSTALLED_ROOT"] = installed
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
