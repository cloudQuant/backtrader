"""BT Store/Feeds consume a synthetic local ServiceHost over real CURVE."""

import os
from pathlib import Path
import subprocess
import sys

import bt_api_py
import pytest
import zmq


pytestmark = pytest.mark.skipif(not zmq.has("curve"), reason="CURVE unavailable")


def test_gateway_store_two_feeds_on_host_curve(tmp_path):
    sdk_root = Path(bt_api_py.__file__).resolve().parent.parent
    bt_root = Path(__file__).resolve().parents[2]
    script = r'''
import datetime as dt
import os
from pathlib import Path
import threading
from types import SimpleNamespace

from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore
from bt_api_py.gateway_api import GatewayBtApi
from tests.integration.test_gateway_calendar_strategy_host import test_host_curve_strategy_calendar_lifecycle

original = GatewayBtApi.trading_calendar_query
seen = {}
in_probe = False

def query(self, exchange_name, **kwargs):
    global in_probe
    result = original(self, exchange_name, **kwargs)
    if in_probe or result.status != "COMPLETE":
        return result
    identity = (result.registration_id, result.binding["calendar_ref"])
    if seen.get(identity, 0) >= 2:
        return result
    in_probe = True
    try:
        route = kwargs["route"]
        store = object.__new__(BtApiStore)
        for name, value in {
            "_gateway_mode": True, "_service_read_only": False, "_started": True,
            "_connected": True, "_gateway_closed": False, "_gateway_pid": os.getpid(),
            "_gateway_run_lock": SimpleNamespace(held=True),
            "_gateway_strategy_config": SimpleNamespace(calendar_settings=object()), "_api": self,
            "_gateway_session_generation": 0, "_calendar_status_generation": 0,
            "_stream_generation": 0, "_sdk_exchanges": {route: {}},
            "_calendar_status_transitions": False, "_calendar_status_stopping": False,
            "_calendar_status_lock": threading.RLock(),
        }.items():
            setattr(store, name, value)
        def make_feed():
            return BtApiFeed(dataname=kwargs["contract"], store=store, provider="btapi",
                calendar_route=route, calendar_venue=kwargs["venue"], calendar_kind=kwargs["kind"],
                calendar_product=kwargs["product"], calendar_contract=kwargs["contract"])
        day = dt.date.fromisoformat(kwargs["trading_day"])
        first = make_feed().trading_session(trading_day=day)
        second = make_feed().trading_session(trading_day=day)
        assert first.status == second.status == "COMPLETE"
        assert first.gateway_binding == second.gateway_binding
        assert first.gateway_binding.registration_id == result.registration_id
        assert first.gateway_binding.service_epoch == result.service_epoch
        assert first.calendar_ref == result.binding["calendar_ref"]
        assert first.source_ids == () and first.account_use == "NOT_AUTHORIZED"
        seen[identity] = seen.get(identity, 0) + 1
    finally:
        in_probe = False
    return result

GatewayBtApi.trading_calendar_query = query
test_host_curve_strategy_calendar_lifecycle(Path(os.environ["CALENDAR_BT_TEST_DIR"]))
assert {version for _, version in seen} == {"v1", "v2"}
assert len({registration for registration, _ in seen}) >= 2
assert any(version == "v1" and count >= 2 for (_, version), count in seen.items())
'''
    environment = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join((str(sdk_root), str(bt_root))),
        "CALENDAR_BT_TEST_DIR": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run([sys.executable, "-c", script], cwd=sdk_root, env=environment,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr


def test_gateway_range_two_feeds_on_host_curve(tmp_path):
    sdk_root = Path(bt_api_py.__file__).resolve().parent.parent
    bt_root = Path(__file__).resolve().parents[2]
    script = r'''
import datetime as dt
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import pytest
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore
from bt_api_py.gateway_api import GatewayBtApi
from tests.integration.test_gateway_calendar_strategy_ranges import test_curve_facade_range_is_pinned_scoped_and_unverified

original = GatewayBtApi.trading_calendar_windows
seen = set()
in_probe = False
concurrent_result = []
captured = []

def make_feed(api, kwargs):
    route = kwargs["route"]
    store = object.__new__(BtApiStore)
    for name, value in {
        "_gateway_mode": True, "_service_read_only": False, "_started": True,
        "_connected": True, "_gateway_closed": False, "_gateway_pid": os.getpid(),
        "_gateway_run_lock": SimpleNamespace(held=True),
        "_gateway_strategy_config": SimpleNamespace(calendar_settings=SimpleNamespace(range_read=True)),
        "_api": api, "_gateway_session_generation": 0, "_calendar_status_generation": 0,
        "_stream_generation": 0, "_sdk_exchanges": {route: {}},
        "_calendar_status_transitions": False, "_calendar_status_stopping": False,
        "_calendar_status_lock": threading.RLock(),
    }.items(): setattr(store, name, value)
    return BtApiFeed(dataname=kwargs["contract"], store=store, provider="btapi",
        calendar_route=route, calendar_venue=kwargs["venue"], calendar_kind=kwargs["kind"],
        calendar_product=kwargs["product"], calendar_contract=kwargs["contract"])

def windows(self, exchange_name, **kwargs):
    global in_probe
    if not in_probe and threading.current_thread() is not threading.main_thread():
        in_probe = True
        try:
            start = dt.datetime.fromisoformat(kwargs["start_utc"].replace("Z", "+00:00"))
            end = dt.datetime.fromisoformat(kwargs["end_utc"].replace("Z", "+00:00"))
            view = make_feed(self, kwargs).trading_windows(start, end)
            assert (view.status, view.reason, view.windows, view.incomplete) == (
                "UNKNOWN", "OWNER_CHANGED", (), True)
            concurrent_result.append(True)
            return captured[-1]
        finally:
            in_probe = False
    result = original(self, exchange_name, **kwargs)
    if in_probe:
        captured.append(result)
        return result
    if result.status != "COMPLETE":
        return result
    key = (kwargs["venue"], kwargs["kind"], kwargs["product"], kwargs["contract"], result.binding["calendar_ref"])
    if key in seen:
        return result
    in_probe = True
    try:
        start = dt.datetime.fromisoformat(kwargs["start_utc"].replace("Z", "+00:00"))
        end = dt.datetime.fromisoformat(kwargs["end_utc"].replace("Z", "+00:00"))
        first = make_feed(self, kwargs).trading_windows(start, end)
        second = make_feed(self, kwargs).trading_windows(start, end)
        assert first.status == second.status == "COMPLETE"
        assert first.gateway_binding == second.gateway_binding
        assert first.gateway_binding.registration_id == result.registration_id
        assert first.gateway_binding.service_epoch == result.service_epoch
        assert first.gateway_policy.declaration == "DEPLOYMENT_DECLARED_UNVERIFIED"
        assert [(w.window_id, w.trading_day.isoformat(), w.start_utc.isoformat().replace("+00:00", "Z"),
                 w.end_utc.isoformat().replace("+00:00", "Z")) for w in first.windows] == [
            (w["window_id"], w["trading_day"], w["start_utc"], w["end_utc"]) for w in result.windows]
        assert first.gateway_binding.source_authentication == "NOT_PROVEN"
        assert first.gateway_binding.trade_authorization == "NONE"
        if result.binding["calendar_ref"] == "v1":
            assert [(w.window_id, w.trading_day.isoformat()) for w in first.windows] == [
                ("night", "2026-01-05"), ("day", "2026-01-05"), ("day", "2026-01-06")]
        seen.add(key)
    finally:
        in_probe = False
    return result

GatewayBtApi.trading_calendar_windows = windows
patcher = pytest.MonkeyPatch()
try:
    test_curve_facade_range_is_pinned_scoped_and_unverified(Path(os.environ["CALENDAR_BT_TEST_DIR"]), patcher)
finally:
    patcher.undo()
assert len(seen) >= 4
assert {item[-1] for item in seen} == {"v1", "v2"}
assert {item[0] for item in seen} >= {"SIM", "SIM2"}
assert concurrent_result == [True]
'''
    environment = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join((str(sdk_root), str(bt_root))),
        "CALENDAR_BT_TEST_DIR": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run([sys.executable, "-c", script], cwd=sdk_root, env=environment,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr


def test_gateway_range_long_holiday_on_host_curve(tmp_path):
    sdk_root = Path(bt_api_py.__file__).resolve().parent.parent
    bt_root = Path(__file__).resolve().parents[2]
    script = r'''
import datetime as dt
import os, queue, threading
from pathlib import Path
from types import SimpleNamespace
import zmq
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.service_protocol import WireScope
from bt_api_py.gateway_api import GatewayBtApi
from bt_api_py.gateway_calendar_service import CalendarGrant, GatewayCalendarService, ReceiptCheckedCalendarStore
from bt_api_py.gateway_direct_client import GatewayClientRoute
from bt_api_py.gateway_strategy_calendar import GatewayCalendarClientSettings
from bt_api_py.gateway_strategy_client import GatewayStrategyClientSession
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_client_config, parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_runtime import ClientCurveKeys
from bt_api_py.trading_calendar_range_simulation import CalendarRangePolicy
from bt_api_py.trading_calendar_store import TradingCalendarStore
from tests.integration.test_iter63_gateway_direct_service import ACCOUNT, CLIENT_A, DOMAIN, SERVICE, _client_config, _service_config
from tests.integration.test_iter63_gateway_dual_ports import _resources
from tests.integration.test_service_account_instrument_metadata import _free_endpoint
from tests.unit.test_iter63_gateway_strategy_client import Host
from tests.unit.test_trading_calendar_binding import binding
from tests.unit.test_trading_calendar_range_simulation import setup_long_holiday

root = Path(os.environ["CALENDAR_BT_TEST_DIR"])
calendar_dir = root / "calendar"; calendar_dir.mkdir()
setup_long_holiday(calendar_dir)
bound = binding(ReceiptCheckedCalendarStore(TradingCalendarStore(calendar_dir)), day=dt.date(2026, 1, 12))
endpoint = _free_endpoint()
server_keys, client_keys = zmq.curve_keypair(), zmq.curve_keypair()
raw = _service_config(endpoint).to_public_dict()
raw["components"]["gateway"]["settings"]["bind_ports"].append("service.calendar_read")
client_raw = _client_config(endpoint, CLIENT_A).to_public_dict()
binds = client_raw["clients"]["gateway"]["settings"]["bindings"]
binds.append(dict(binds[0], mount="store.calendar"))
scope = WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=CLIENT_A.actor_ref)
direct_ops = frozenset({"direct.command_status"})
principal = PrincipalGrant(CLIENT_A, (
    ResourceGrant("gateway-a", "service.direct_write", "scope-a", scope, direct_ops),
    ResourceGrant("gateway-a", "service.calendar_read", "scope-a", scope,
                  frozenset({"calendar.query.v1", "calendar.windows.v1"}))))
authority = TrustedServiceAuthority(identity=SERVICE, scope=WireScope(DOMAIN), scope_ref="scope-a",
    scope_version="v1", security_ref="security-a", security_version="v1",
    registration_policy_ref="direct-policy-v1", registration_policy_version="v1",
    service_requirements_ref="direct-requirements-v1", service_requirements_version="v1",
    curve_public_key=server_keys[0], curve_secret_key=server_keys[1],
    principals={client_keys[0]: CLIENT_A.principal_ref}, grants={CLIENT_A.principal_ref: (principal,)})
ready, stop = queue.Queue(), threading.Event()
def serve():
    host = None
    try:
        direct, _, _ = _resources(root)
        grant = CalendarGrant(CLIENT_A.principal_ref, DOMAIN, ACCOUNT, CLIENT_A.actor_ref,
                              "run-a", "route-a", "SIM", "future", "x", "x2601")
        policy = CalendarRangePolicy("holiday", "route-a", "SIM", "future", "x", "x2601", 10, 0)
        service = GatewayCalendarService(grants=frozenset({grant}), range_policies=frozenset({policy}))
        service.rebind(bound)
        host = ServiceHost(parse_service_config(raw), authority, root / "registry.sqlite", lambda *_:
            ComponentResources.borrowed({"binding": direct, "calendar_service": service}, ready=lambda: True))
        host.start(); ready.put(("ready", direct._journal.journal_id))
        while not stop.is_set(): host.serve_once(10)
    except BaseException as exc:
        ready.put(("error", type(exc).__name__, str(exc)))
    finally:
        if host is not None and host.state == "started": host.close()
thread = threading.Thread(target=serve); thread.start()
session = None
try:
    started = ready.get(timeout=15); assert started[0] == "ready", started
    route = GatewayClientRoute("broker.direct_write", SERVICE.actor_ref, "gateway-a", "scope-a",
        WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=CLIENT_A.actor_ref, run_id="run-a"), CLIENT_A)
    settings = GatewayCalendarClientSettings("SIMULATION_ONLY", (dict(route="route-a", venue="SIM",
        kind="future", product="x", contract="x2601"),), True)
    session = GatewayStrategyClientSession(parse_client_config(client_raw),
        binding=GatewayCommandBinding(started[1], ACCOUNT, CLIENT_A.actor_ref, CLIENT_A.principal_ref),
        route=route, peer=SERVICE, security_profiles={"security-a": ClientCurveKeys(server_keys[0], *client_keys)},
        host=Host(), requested_operations=direct_ops, calendar_settings=settings)
    session.start(timeout_seconds=10)
    api = GatewayBtApi(session, exchange_name="route-a")
    store = object.__new__(BtApiStore)
    for name, value in {
        "_gateway_mode": True, "_service_read_only": False, "_started": True, "_connected": True,
        "_gateway_closed": False, "_gateway_pid": os.getpid(), "_gateway_run_lock": SimpleNamespace(held=True),
        "_gateway_strategy_config": SimpleNamespace(calendar_settings=SimpleNamespace(range_read=True)),
        "_api": api, "_gateway_session_generation": 0, "_calendar_status_generation": 0,
        "_stream_generation": 0, "_sdk_exchanges": {"route-a": {}}, "_calendar_status_transitions": False,
        "_calendar_status_stopping": False, "_calendar_status_lock": threading.RLock(),
    }.items(): setattr(store, name, value)
    def make_feed():
        return BtApiFeed(dataname="x2601", store=store, provider="btapi", calendar_route="route-a",
            calendar_venue="SIM", calendar_kind="future", calendar_product="x", calendar_contract="x2601")
    start, end = dt.datetime(2026, 1, 2, 13, tzinfo=dt.timezone.utc), dt.datetime(2026, 1, 2, 14, tzinfo=dt.timezone.utc)
    first, second = make_feed().trading_windows(start, end), make_feed().trading_windows(start, end)
    assert first.status == second.status == "COMPLETE" and first.gateway_binding == second.gateway_binding
    assert len(first.windows) == 1 and first.windows[0].trading_day == dt.date(2026, 1, 12)
    assert first.windows[0].start_utc == start and first.gateway_policy.max_advance_days == 10
    assert first.gateway_policy.declaration == "DEPLOYMENT_DECLARED_UNVERIFIED"
finally:
    if session is not None: session.close(timeout_seconds=10)
    stop.set(); thread.join(15)
    assert not thread.is_alive()
'''
    environment = {"PATH": os.defpath, "PYTHONPATH": os.pathsep.join((str(sdk_root), str(bt_root))),
                   "CALENDAR_BT_TEST_DIR": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-c", script], cwd=sdk_root, env=environment,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
