"""Offline fake-provider smoke for the optional16 component mounts.

Drives ``examples/000_live_certification/optional16/components.py`` with a fake
venue client and the real dev-SDK components (``bt_api_risk`` DurableRiskGate,
``bt_api_execution`` ManagedExecution/Cancellation facades over a real SQLite
store, ``bt_api_monitor`` DurableOutbox).  This exercises the exact mount code
the iteration-41 acceptance used for the crypto path, without network or
account access:

* the shared risk gate runs reserve -> claim -> settle once per increase and
  its durable dispatch-inflight latch rejects the second increase;
* the execution facade returns the venue reply identity (orderId/status);
* the monitor outbox durably appends/acknowledges every operation and serves a
  signed readback page;
* disabled components are never imported and the surface degrades to a
  pass-through.

Skips when the dev SDK tree is unavailable.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
OPTIONAL16 = REPO / "examples" / "000_live_certification" / "optional16"
DEV_SDK = Path("D:/bt_api_py/bt_api")
_DEV_SRC_DIRS = (
    DEV_SDK / "bt_api_base" / "src",
    DEV_SDK / "bt_api_risk" / "src",
    DEV_SDK / "bt_api_execution" / "src",
    DEV_SDK / "bt_api_monitor" / "src",
)


def _ensure_dev_sdk() -> None:
    if not all(path.is_dir() for path in _DEV_SRC_DIRS):
        pytest.skip("dev bt_api_py component tree is unavailable")
    for path in reversed(_DEV_SRC_DIRS):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


@pytest.fixture(scope="module")
def components():
    _ensure_dev_sdk()
    spec = importlib.util.spec_from_file_location(
        "iter42_optional16_components", OPTIONAL16 / "components.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeVenueClient:
    """The smallest honest venue surface the case client exposes."""

    transport = "direct"

    def __init__(self) -> None:
        self.calls = []

    def connect(self):
        return {"host": "fake"}

    def account_config(self):
        return {"ok": True}

    def balances(self):
        return []

    def position_risk(self, symbol=None):
        return {}

    def open_orders(self, symbol=None):
        return []

    def query_order(self, symbol, *, order_id=None, client_order_id=None):
        return {"status": "NEW"}

    def filters(self, symbol):
        return {}

    def mark_price(self, symbol):
        return {"price": "100"}

    def place_order(self, symbol, side, **kwargs):
        self.calls.append(("place", symbol, side, dict(kwargs)))
        return {
            "orderId": "FAKE-1",
            "status": "NEW",
            "_client_order_id": kwargs.get("client_order_id"),
        }

    def cancel_order(self, symbol, **kwargs):
        self.calls.append(("cancel", symbol, dict(kwargs)))
        return {"status": "CANCELED"}

    def describe(self):
        return {"transport": "direct"}


def _config(case_id: str = "ITER42-SMOKE-1") -> dict:
    return {
        "case_id": case_id,
        "environment": {"name": "demo"},
        "policy": {"max_orders": 1, "max_notional_usdt": 1000},
        "venue": "binance",
    }


def _topology(**flags) -> dict:
    values = {"transport": "direct", "execution": False, "risk": False, "monitor": False}
    values.update(flags)
    return values


def _env() -> dict:
    return {
        "OPTIONAL16_SDK_ROOT": str(DEV_SDK),
        "OPTIONAL16_RUN_DIR": tempfile.mkdtemp(prefix="iter42-o16-smoke-"),
    }


def test_full_mount_runs_one_risk_increase_with_monitor_readback(components):
    base = _FakeVenueClient()
    wrapped = components.wrap_client(
        base,
        _config(),
        _topology(execution=True, risk=True, monitor=True),
        _env(),
    )
    assert wrapped.connect() == {"host": "fake"}
    reply = wrapped.place_order(
        "BTCUSDT", "BUY", order_type="LIMIT", quantity="0.001", price="100", time_in_force="GTC"
    )
    assert reply["orderId"] == "FAKE-1"
    assert reply.get("clientOrderId") or reply.get("_client_order_id")
    assert base.calls[-1][0] == "place"

    described = wrapped.describe()
    risk = described["components"]["risk"]
    assert risk["counts"]["reserved"] == 1
    assert risk["counts"]["claimed"] == 1
    assert risk["counts"]["settled"] == 1
    execution = described["components"]["execution"]
    assert execution["last_record"]["state"] == "ACKED"
    assert execution["last_record"]["provider_order_id"] == "FAKE-1"
    assert execution["admission_gate"] == "SharedRiskAdmissionAdapter(DurableRiskGate)"
    monitor = described["components"]["monitor"]
    assert monitor["counts"]["appended"] >= 2
    assert monitor["counts"]["acknowledged"] >= 2
    assert monitor["readback"]["ok"] is True
    assert monitor["readback"]["events"] >= 2
    assert {event["kind"] for event in monitor["events"]} >= {"connect", "place_order"}


def test_second_risk_increase_is_rejected_by_the_durable_latch(components):
    base = _FakeVenueClient()
    wrapped = components.wrap_client(
        base,
        _config("ITER42-SMOKE-2"),
        _topology(execution=True, risk=True, monitor=True),
        _env(),
    )
    wrapped.place_order("BTCUSDT", "BUY", order_type="LIMIT", quantity="0.001", price="100")
    dispatch_count = sum(1 for call in base.calls if call[0] == "place")
    with pytest.raises(RuntimeError, match="risk_rejected"):
        wrapped.place_order("BTCUSDT", "BUY", order_type="LIMIT", quantity="0.001", price="100")
    assert sum(1 for call in base.calls if call[0] == "place") == dispatch_count
    assert wrapped.describe()["components"]["risk"]["denials"]


def test_market_order_with_risk_fails_closed_before_dispatch(components):
    base = _FakeVenueClient()
    wrapped = components.wrap_client(
        base,
        _config("ITER42-SMOKE-3"),
        _topology(execution=True, risk=True, monitor=True),
        _env(),
    )
    with pytest.raises(RuntimeError, match="NOTIONAL_UNAVAILABLE"):
        wrapped.place_order("BTCUSDT", "BUY", order_type="MARKET", quantity="0.001")
    assert not [call for call in base.calls if call[0] == "place"]


def test_disabled_components_never_import_and_stay_pass_through(components):
    for package in ("bt_api_risk", "bt_api_execution", "bt_api_monitor"):
        sys.modules.pop(package, None)
    base = _FakeVenueClient()
    wrapped = components.wrap_client(base, _config("ITER42-SMOKE-4"), _topology(), _env())
    reply = wrapped.place_order(
        "BTCUSDT", "BUY", order_type="LIMIT", quantity="0.001", price="100"
    )
    assert reply["orderId"] == "FAKE-1"
    described = wrapped.describe()
    assert all(not item.get("active") for item in described["components"].values())
    assert all("package" not in item for item in described["components"].values())
    assert not any(package in sys.modules for package in ("bt_api_risk", "bt_api_execution", "bt_api_monitor"))


def test_cancel_after_place_returns_the_venue_identity(components):
    base = _FakeVenueClient()
    wrapped = components.wrap_client(
        base,
        _config("ITER42-SMOKE-5"),
        _topology(execution=True, risk=True, monitor=True),
        _env(),
    )
    reply = wrapped.place_order(
        "BTCUSDT", "BUY", order_type="LIMIT", quantity="0.001", price="100"
    )
    cancel_reply = wrapped.cancel_order("BTCUSDT", order_id=reply["orderId"])
    assert cancel_reply["status"] == "CANCELED"
    assert base.calls[-1][0] == "cancel"
    described = wrapped.describe()
    monitor = described["components"]["monitor"]
    assert monitor["counts"]["appended"] >= 2
    kinds = {event["kind"] for event in monitor["events"]}
    assert {"place_order", "cancel_order"} <= kinds
