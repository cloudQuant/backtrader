"""Focused fakes for the iteration-42 multi-instrument registered-sim gate.

One SDK registered-sim admission authorizes exactly one instrument, so a
cross-leg (m/RM) strategy must switch the arm strictly between writes.  These
tests exercise the wrapper-level switching protocol with fake arm/disarm and
fake native clients; they never construct a native session.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
CANONICAL = REPO / "examples" / "013_3_sa_midfreq_simnow" / "simnow_direct.py"
VENDORED = REPO / "examples" / "013_1_midfreq_cross_arbitrage" / "simnow_direct.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def simnow_direct():
    return _load_module(CANONICAL, "iteration42_simnow_direct_tests")


class _FakeNativeClient:
    """Records the exact capability object handed to each native write."""

    def __init__(self):
        self.insert_calls = []
        self.action_calls = []

    def submit_order_insert(self, field, request_id, *, execution_capability=None, **kwargs):
        self.insert_calls.append((dict(vars(field)), request_id, execution_capability))
        return 0

    def submit_order_action(self, field, request_id, *, execution_capability=None, **kwargs):
        self.action_calls.append((dict(vars(field)), request_id, execution_capability))
        return 0


def _wrapper_with_fake_arms(simnow_direct, instruments):
    """Build a wrapper whose arm/disarm calls are recorded instead of native."""
    wrapper = simnow_direct.RegisteredSimWrapper(
        broker_id="fake",
        investor_id="fake",
        password="fake",
        md_front="tcp://127.0.0.1:1",
        td_front="tcp://127.0.0.1:2",
    )
    calls = []

    def fake_arm(instrument_id, exchange_id="", md_front="", *, strategy_identity_sha256,
                 execution_cycle_id, preflight_sha256):
        calls.append(("arm", instrument_id.upper(), exchange_id.upper()))
        wrapper._registered_sim_capability = object()
        wrapper._registered_sim_state = {"state": f"armed:{instrument_id.upper()}"}
        return {
            "armed": True,
            "instrument": instrument_id,
            "exchange_id": exchange_id.upper(),
            "state": dict(wrapper._registered_sim_state),
        }

    def fake_disarm(reason="fake"):
        calls.append(("disarm", str(reason)))
        had = wrapper._registered_sim_capability is not None
        wrapper._registered_sim_capability = None
        return {"disarmed": True, "reason": str(reason), "native": had}

    wrapper.arm_registered_sim_execution = fake_arm
    wrapper.disarm_registered_sim_execution = fake_disarm
    wrapper.configure_registered_sim_arm_templates(instruments)
    wrapper.trader_client = _FakeNativeClient()
    return wrapper, calls


def _templates():
    return {
        ("m2612", "DCE"): {
            "md_front": "tcp://md:1",
            "strategy_identity_sha256": "0" * 64,
            "execution_cycle_id": "cycle-1",
            "preflight_sha256": "1" * 64,
        },
        ("RM612", "CZCE"): {
            "md_front": "tcp://md:2",
            "strategy_identity_sha256": "0" * 64,
            "execution_cycle_id": "cycle-1",
            "preflight_sha256": "2" * 64,
        },
    }


def test_vendored_copy_is_byte_identical():
    assert VENDORED.read_bytes() == CANONICAL.read_bytes()


def test_ensure_arm_is_idempotent_for_the_same_instrument(simnow_direct):
    wrapper, calls = _wrapper_with_fake_arms(simnow_direct, _templates())
    wrapper.ensure_registered_sim_arm_for("m2612", "DCE")
    wrapper.ensure_registered_sim_arm_for("m2612", "DCE")
    assert calls == [("arm", "M2612", "DCE")]
    assert wrapper._registered_sim_armed_key == ("M2612", "DCE")


def test_ensure_arm_switches_only_between_writes(simnow_direct):
    wrapper, calls = _wrapper_with_fake_arms(simnow_direct, _templates())
    wrapper.ensure_registered_sim_arm_for("m2612", "DCE")
    wrapper.ensure_registered_sim_arm_for("RM612", "CZCE")
    wrapper.ensure_registered_sim_arm_for("m2612", "DCE")
    assert calls == [
        ("arm", "M2612", "DCE"),
        ("disarm", "registered_sim_instrument_switch"),
        ("arm", "RM612", "CZCE"),
        ("disarm", "registered_sim_instrument_switch"),
        ("arm", "M2612", "DCE"),
    ]
    history = wrapper.registered_sim_arm_history()
    assert [item["instrument"] for item in history] == ["M2612", "RM612", "M2612"]
    assert all("at_epoch" in item for item in history)


def test_native_dispatch_switches_to_the_outbound_instrument(simnow_direct):
    wrapper, calls = _wrapper_with_fake_arms(simnow_direct, _templates())
    wrapper.ensure_registered_sim_arm_for("m2612", "DCE")
    insert_field = SimpleNamespace(InstrumentID="RM612", ExchangeID="CZCE", OrderRef="ref-1")
    assert wrapper._send_native_order_insert(insert_field, 101) == 0
    # The gate switched to RM before the insert and handed the live capability.
    assert calls[-2:] == [("disarm", "registered_sim_instrument_switch"), ("arm", "RM612", "CZCE")]
    assert wrapper.trader_client.insert_calls[-1][0]["InstrumentID"] == "RM612"
    assert wrapper.trader_client.insert_calls[-1][2] is wrapper._registered_sim_capability
    assert wrapper._order_state["ref-1"] == "active"

    action_field = SimpleNamespace(InstrumentID="m2612", ExchangeID="DCE", OrderRef="ref-2")
    assert wrapper._send_native_order_action(action_field, 102) == 0
    assert calls[-2:] == [("disarm", "registered_sim_instrument_switch"), ("arm", "M2612", "DCE")]
    assert wrapper.trader_client.action_calls[-1][0]["InstrumentID"] == "m2612"
    assert wrapper.trader_client.action_calls[-1][2] is wrapper._registered_sim_capability


def test_missing_template_refuses_before_any_native_call(simnow_direct):
    wrapper, calls = _wrapper_with_fake_arms(simnow_direct, _templates())
    with pytest.raises(simnow_direct.BtApiStoreError):
        wrapper.ensure_registered_sim_arm_for("SA701", "CZCE")
    assert calls == []
    assert wrapper.trader_client.insert_calls == []


def test_without_templates_dispatch_keeps_single_arm_semantics(simnow_direct):
    wrapper = simnow_direct.RegisteredSimWrapper(
        broker_id="fake",
        investor_id="fake",
        password="fake",
        md_front="tcp://127.0.0.1:1",
        td_front="tcp://127.0.0.1:2",
    )
    wrapper.trader_client = _FakeNativeClient()
    field = SimpleNamespace(InstrumentID="SA701", ExchangeID="CZCE", OrderRef="ref-x")
    with pytest.raises(simnow_direct.BtApiStoreError):
        # No templates and no arm: the stock fail-closed behaviour is intact.
        wrapper._send_native_order_insert(field, 7)
    assert wrapper.trader_client.insert_calls == []


def test_dispatch_hook_is_inert_until_templates_are_configured(simnow_direct):
    wrapper, calls = _wrapper_with_fake_arms(simnow_direct, {})
    wrapper._registered_sim_prepare_dispatch(SimpleNamespace(InstrumentID="m2612", ExchangeID="DCE"))
    assert calls == []
