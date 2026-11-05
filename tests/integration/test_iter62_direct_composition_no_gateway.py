"""Iteration 62 (62.08, INV62-03): the direct composition loads no Gateway component.

A fresh interpreter builds the CTP direct composition exactly as the
``examples/live/007_ctp/*_direct`` runners do (``BtApiStore`` with SDK write
admission and no execution component, the direct ``BtApiBroker``, a
``BtApiFeed`` and Cerebro wiring) and lets the Store's SDK assembly construct
its ``BtApi`` facade. None of the optional Gateway/service modules may be
imported. A control run imports the SDK Gateway CTP composition to prove the
detector sees them.

INTEGRATION_SIM: separate local process; synthetic credentials; fronts point
at a closed loopback port, clock verification is off and a socket guard
refuses any non-loopback connect/send. No account, CTP front or network.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("bt_api_py.direct_api_assembly")
pytest.importorskip("bt_api_ctp")

_ROOT = Path(__file__).resolve().parents[2]
_FORBIDDEN_ROOTS = (
    "bt_api_gateway",
    "bt_api_transport_zmq",
    "zmq",
    "msgpack",
    "bt_api_execution",
    "bt_api_risk",
    "bt_api_monitor",
)

_PROBE = textwrap.dedent(
    """
    import json, socket, sys, tempfile

    def _loopback(address):
        host = address[0] if isinstance(address, tuple) else address
        return host in ("127.0.0.1", "::1", "localhost")

    _connect, _sendto = socket.socket.connect, socket.socket.sendto

    def _guarded_connect(self, address):
        if not _loopback(address):
            raise OSError("network disabled by test guard")
        return _connect(self, address)

    def _guarded_sendto(self, data, *args):
        if not _loopback(args[-1]):
            raise OSError("network disabled by test guard")
        return _sendto(self, data, *args)

    socket.socket.connect, socket.socket.sendto = _guarded_connect, _guarded_sendto

    import backtrader as bt
    from bt_api_base.market_protocol import MarketInstrumentKey
    from backtrader.stores.btapistore import BtApiStore

    if sys.argv[1] == "control":
        import bt_api_py.ctp_account_process  # the Gateway CTP composition

    route = "CTP___FUTURE"
    store = BtApiStore(
        provider="ctp",
        contract_metadata={
            "rb2701": {
                "instrument_key": MarketInstrumentKey(
                    "ctp", "SHFE", "demo", "future", "rb2701", "rb2701"
                ),
                "price_tick": 1.0,
                "multiplier": 10.0,
            }
        },
        exchange_kwargs={
            route: {
                "broker_id": "9999",
                "user_id": "synthetic-user",
                "password": "synthetic-password",
                "app_id": "synthetic-app",
                "auth_code": "0000000000000000",
                "td_front": "tcp://127.0.0.1:1",
                "md_front": "tcp://127.0.0.1:1",
                "ctp_env_profile": "config_front_pair",
                "private_topic_mode": "restart",
            }
        },
        write_admission={route: True},
        market_clock_verification=False,
        symbol_routes={"rb2701": route},
    )
    broker = store.getbroker(
        strategy_dir=tempfile.mkdtemp(), first_init=True, position_mode="net"
    )
    data = store.getdata(
        dataname="rb2701", timeframe=bt.TimeFrame.Ticks, compression=1, backfill_start=False
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    cerebro.adddata(data, name="rb2701")
    assembly = store._ensure_sdk_direct_api_assembly()
    api = assembly.ensure_api()
    routes = list(api.list_exchanges())
    assembly.close_api()
    roots = set(json.loads(sys.argv[2]))
    print(json.dumps({
        "direct_write_mode": store._direct_write_mode,
        "routes": routes,
        "loaded": sorted(m for m in sys.modules if m.split(".")[0] in roots),
    }))
    """
)


def _probe(mode: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, mode, json.dumps(_FORBIDDEN_ROOTS)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"},
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


@pytest.mark.integration
def test_ctp_direct_composition_imports_no_gateway_or_service_component():
    result = _probe("direct")
    assert result["direct_write_mode"] is True
    assert result["routes"] == ["CTP___FUTURE"]
    assert result["loaded"] == []


@pytest.mark.integration
def test_the_detector_sees_a_gateway_client_import():
    result = _probe("control")
    assert "bt_api_gateway" in {name.split(".")[0] for name in result["loaded"]}
