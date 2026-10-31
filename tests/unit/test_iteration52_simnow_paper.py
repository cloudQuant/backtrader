"""Iteration 52 SimNow registered-sim paper adapter contracts (fakes only).

Everything here runs without ``bt_api_ctp``, an SDK, an account or a network
socket.  The loaded ``simnow_direct`` module is replaced by a fake module whose
``RegisteredSimStore`` records lifecycle calls; ``simnow_paper`` itself is
imported from its example path because ``052_...`` is not a Python package
name.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "examples" / "unified" / "052_provider_demo_roundtrip" / "simnow_paper.py"
LEAF = HELPER.parent
if str(LEAF) not in sys.path:
    sys.path.insert(0, str(LEAF))

SECRET_PASSWORD = "S3CRET-PASSWORD-052"
SECRET_APP_ID = "S3CRET-APP-ID-052"
SECRET_AUTH = "S3CRET-AUTH-CODE-052"
SECRET_USER = "S3CRET-INVESTOR-052"


@pytest.fixture(scope="module")
def paper():
    spec = importlib.util.spec_from_file_location("iteration52_simnow_paper_test", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve string annotations through ``sys.modules``.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


class FakeRegisteredSimStore:
    """Value-free stand-in for the 013_3 ``RegisteredSimStore``."""

    def __init__(self, **kwargs):
        self.init_kwargs = dict(kwargs)
        self.contract_metadata = {}
        self.started = 0
        self.stopped = 0
        self.arms = []
        self.disarms = []
        self.freezes = []
        self.queries = []
        self.ready = True
        self.login = {
            "trading_day": "20261012",
            "connection_generation": 1,
            "read_only_ready": True,
            "trading_ready": True,
        }
        self.rows = {
            "account_result": [{"Balance": 1000000.0, "Available": 1000000.0}],
            "positions_result": [],
            "orders_result": [],
            "instruments_result": [
                {
                    "InstrumentID": "SA605",
                    "ExchangeID": "CZCE",
                    "PriceTick": 1,
                    "VolumeMultiple": 20,
                }
            ],
        }
        self.execution_summary = {"unknown_ids": [], "active_orders": 0}
        self.query_error = False
        self.armed = False
        self.frozen = False

    def start(self, data=None, broker=None):
        self.started += 1
        return {"started": True, "data": data, "broker": broker}

    def stop(self, timeout=None):
        self.stopped += 1
        return {"shutdown_state": "PASS", "timeout": timeout}

    def registered_sim_wait_ready(self, timeout):
        return self.ready

    def registered_sim_login_facts(self):
        return dict(self.login)

    def registered_sim_query(self, family, timeout=8.0, attempts=2, **filters):
        self.queries.append({"family": family, "filters": dict(filters)})
        if self.query_error:
            raise RuntimeError("fake_query_failure")
        return {"rows": list(self.rows.get(family, [])), "complete": True}

    def registered_sim_arm(self, **kwargs):
        self.arms.append(dict(kwargs))
        self.armed = True
        return {"armed": True, "state": {"state": "ARMED"}}

    def registered_sim_disarm(self, reason="disarm"):
        self.disarms.append(str(reason))
        self.armed = False
        return {"disarmed": True, "reason": str(reason)}

    def registered_sim_freeze(self, reason):
        self.freezes.append(str(reason))
        self.armed = False
        self.frozen = True
        return {"frozen": True, "reason": str(reason)}

    def registered_sim_status(self):
        return {
            "armed": self.armed,
            "frozen": self.frozen,
            "reason": self.freezes[-1] if self.freezes else "",
        }

    def get_execution_summary(self):
        return dict(self.execution_summary)


def _plan(paper, **overrides):
    values = {
        "instrument": "SA605",
        "exchange": "CZCE",
        "md_front": "tcp://127.0.0.1:1",
        "td_front": "tcp://127.0.0.1:2",
        "broker_id": "9999",
        "user_id": SECRET_USER,
        "password": SECRET_PASSWORD,
        "app_id": SECRET_APP_ID,
        "auth_code": SECRET_AUTH,
        "strategy_identity_sha256": "a" * 64,
        "execution_cycle_id": "iteration52-test-run",
        "price_tick": 1.0,
        "volume_multiple": 20.0,
        "quantity_step": 1.0,
        "min_quantity": 1.0,
        "max_quantity": 1.0,
        "login_timeout": 0.05,
        "query_timeout": 0.05,
        "stop_timeout": 0.05,
    }
    values.update(overrides)
    return paper.build_simnow_plan(**values)


def _store(paper, **overrides):
    base = overrides.pop("base", FakeRegisteredSimStore)
    store_class = paper.build_store_class(base)
    return store_class(plan=_plan(paper, **overrides))


def _reason(callable_obj):
    with pytest.raises(Exception) as info:
        callable_obj()
    return info.value


# --------------------------------------------------------------- method mapping
def test_required_session_surface_on_a_flat_armed_account(paper):
    store = _store(paper)
    store.start()

    assert store.started == 1
    assert len(store.arms) == 1
    assert store.arms[0]["instrument"] == "SA605"
    assert store.arms[0]["exchange"] == "CZCE"
    assert store.arms[0]["md_front"] == "tcp://127.0.0.1:1"
    assert store.arms[0]["strategy_identity_sha256"] == "a" * 64
    assert store.arms[0]["execution_cycle_id"] == "iteration52-test-run"

    environment = store.get_environment_info("SA605")
    assert environment["environment"] == "simulation"
    assert environment["venue"] == "SIMNOW"

    account = store.get_account_config("SA605")
    assert account["can_trade"] is True
    assert account["position_mode"] == "dual_side"
    assert account["reasons"] == []

    spec = store.get_instrument_spec("SA605")
    assert spec["multiplier"] == 20.0
    assert spec["tick_size"] == 1.0
    assert spec["quantity_unit"] == "contracts"
    assert store.contract_metadata["SA605"]["multiplier"] == 20.0

    readiness = store.get_order_readiness("SA605", 1.0, position_mode="dual_side")
    assert readiness["ready"] is True
    assert readiness["reasons"] == []

    snapshot = store.get_reconcile_snapshot()
    assert snapshot["positions"] == []
    assert snapshot["open_orders"] == []
    assert snapshot["execution_summary"]["unknown_ids"] == []
    assert snapshot["execution_summary"]["active_orders"] == 0


def test_symbol_scope_mismatch_fails_closed(paper):
    store = _store(paper)
    store.start()
    error = _reason(lambda: store.get_environment_info("RB605"))
    assert error.reason == "simnow_paper_symbol_scope_mismatch"


# --------------------------------------------------------------- missing pieces
def test_missing_front_pair_is_a_finite_error(paper):
    error = _reason(lambda: _plan(paper, md_front=""))
    assert isinstance(error, paper.SimNowPaperError)
    assert error.reason == "simnow_front_pair_missing"


def test_missing_sdk_file_is_a_finite_error(paper, tmp_path):
    error = _reason(lambda: paper.load_simnow_direct(tmp_path / "absent_simnow_direct.py"))
    assert isinstance(error, paper.SimNowPaperError)
    assert error.reason == "simnow_direct_missing"


def test_store_factory_requires_a_registered_sim_base(paper):
    module = SimpleNamespace()
    error = _reason(lambda: paper.make_store_factory(_plan(paper), simnow_module=module))
    assert error.reason == "simnow_store_base_unavailable"


def test_login_not_ready_blocks_start(paper):
    store = _store(paper)
    store.ready = False
    error = _reason(store.start)
    assert error.reason == "simnow_paper_login_not_ready"
    assert store.freezes == ["simnow_paper_start_failed"]
    assert store.stopped == 1


def test_missing_instrument_row_blocks_start(paper):
    store = _store(paper)
    store.rows["instruments_result"] = []
    error = _reason(store.start)
    assert error.reason == "simnow_paper_instrument_missing"
    assert store.freezes == ["simnow_paper_start_failed"]
    assert store.arms == []


def test_instrument_metadata_mismatch_blocks_start(paper):
    store = _store(paper)
    store.rows["instruments_result"][0]["VolumeMultiple"] = 10
    error = _reason(store.start)
    assert error.reason == "simnow_paper_instrument_metadata_mismatch"
    assert store.arms == []


def test_open_position_blocks_start(paper):
    store = _store(paper)
    store.rows["positions_result"] = [
        {"InstrumentID": "SA605", "ExchangeID": "CZCE", "Position": 1}
    ]
    error = _reason(store.start)
    assert error.reason == "simnow_paper_account_not_flat"
    assert store.arms == []


def test_active_order_blocks_start(paper):
    store = _store(paper)
    store.rows["orders_result"] = [
        {"InstrumentID": "SA605", "ExchangeID": "CZCE", "OrderStatus": "1"}
    ]
    error = _reason(store.start)
    assert error.reason == "simnow_paper_open_orders_present"
    assert store.arms == []


def test_query_failure_blocks_start(paper):
    store = _store(paper)
    store.query_error = True
    error = _reason(store.start)
    assert error.reason == "simnow_paper_query_failed"
    assert store.arms == []


# ----------------------------------------------------------------- arm exactly once
def test_arm_happens_exactly_once(paper):
    store = _store(paper)
    store.start()
    assert len(store.arms) == 1

    # The runtime feed calls Store.start(data=feed) after the session preflight.
    store.start(data=object())
    assert store.started == 2
    assert len(store.arms) == 1

    error = _reason(store._simnow_arm_once)
    assert error.reason == "simnow_paper_arm_twice"


# --------------------------------------------------------------- stop semantics
def test_clean_stop_disarms(paper):
    store = _store(paper)
    store.start()
    health = store.stop(timeout=0.05)

    assert health["shutdown_state"] == "PASS"
    assert store.disarms == ["simnow_paper_clean_stop"]
    assert store.freezes == []
    facts = store.simnow_paper_facts()
    assert facts["stop"]["action"] == "disarm"
    assert facts["stop"]["reason"] == "simnow_paper_clean_stop"


def test_unknown_execution_freezes_at_stop(paper):
    store = _store(paper)
    store.start()
    store.execution_summary = {"unknown_ids": ["unknown-intent"], "active_orders": 0}
    store.stop(timeout=0.05)

    assert store.disarms == []
    assert store.freezes == ["simnow_paper_residual_exposure"]
    facts = store.simnow_paper_facts()
    assert facts["stop"]["action"] == "freeze"
    assert facts["stop"]["unknown_ids"] == 1


def test_residual_position_freezes_at_stop(paper):
    store = _store(paper)
    store.start()
    store.rows["positions_result"] = [
        {"InstrumentID": "SA605", "ExchangeID": "CZCE", "Position": 1}
    ]
    store.stop(timeout=0.05)

    assert store.freezes == ["simnow_paper_residual_exposure"]
    facts = store.simnow_paper_facts()
    assert facts["stop"]["final_position_rows"] == 1


def test_unresolved_final_query_freezes_at_stop(paper):
    store = _store(paper)
    store.start()
    store.query_error = True
    store.stop(timeout=0.05)

    assert store.freezes and store.freezes[0] == "simnow_paper_stop_unresolved"
    facts = store.simnow_paper_facts()
    assert facts["stop"]["action"] == "freeze"
    assert facts["stop"]["reason"] == "simnow_paper_stop_unresolved"


def test_existing_freeze_is_not_disarmed(paper):
    store = _store(paper)
    store.start()
    store.registered_sim_freeze("prior_freeze")
    store.stop(timeout=0.05)

    assert store.disarms == []
    assert store.freezes == ["prior_freeze"]
    facts = store.simnow_paper_facts()
    assert facts["stop"]["action"] == "frozen"
    assert store.stopped == 1


# ----------------------------------------------------------------- repr / secrets
def test_credentials_never_appear_in_repr(paper):
    plan = _plan(paper)
    text = repr(plan) + " " + str(plan)
    for secret in (SECRET_PASSWORD, SECRET_APP_ID, SECRET_AUTH, SECRET_USER):
        assert secret not in text

    store = _store(paper)
    store.start()
    text = repr(store) + " " + str(store.simnow_paper_facts())
    for secret in (SECRET_PASSWORD, SECRET_APP_ID, SECRET_AUTH, SECRET_USER):
        assert secret not in text
    assert plan.md_front not in repr(plan)
    assert plan.td_front not in repr(plan)


def test_store_factory_does_not_retain_session_config(paper):
    module = SimpleNamespace(RegisteredSimStore=FakeRegisteredSimStore)
    factory = paper.make_store_factory(_plan(paper), simnow_module=module)
    session_secret = "SESSION-ONLY-SECRET-052"
    config = {
        "exchange_kwargs": {"CTP___FUTURES": {"password": session_secret}},
        "symbol_routes": {"SA605": "CTP___FUTURES"},
    }
    store = factory(config=config, profile=object())
    assert session_secret not in repr(store)
    assert session_secret not in str(store.init_kwargs)


# --------------------------------------------------------------- strategy adapter
def test_strategy_adapter_forces_gfd_without_touching_the_source(paper):
    class DummyStrategy:
        def __init__(self):
            self.p = SimpleNamespace(time_in_force="GFD")
            self.calls = []

        def buy(self, *args, **kwargs):
            self.calls.append(("buy", kwargs))
            return "buy"

        def sell(self, *args, **kwargs):
            self.calls.append(("sell", kwargs))
            return "sell"

    adapted = paper.adapt_roundtrip_strategy(DummyStrategy)
    instance = adapted()
    assert instance.buy(1, time_in_force="IOC") == "buy"
    assert instance.sell(1, time_in_force="IOC") == "sell"
    assert instance.calls[0][1]["time_in_force"] == "GFD"
    assert instance.calls[1][1]["time_in_force"] == "GFD"
    # The original class is untouched.
    original = DummyStrategy()
    original.buy(1, time_in_force="IOC")
    assert original.calls[0][1]["time_in_force"] == "IOC"
