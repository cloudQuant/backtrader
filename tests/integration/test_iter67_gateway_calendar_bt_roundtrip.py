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
