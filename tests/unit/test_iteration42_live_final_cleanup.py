"""End-to-end source-fake checks for the Iteration 42 write handlers.

The candidate ``run_live`` functions are executed directly.  Only provider,
broker, strategy, thread and signal leaves are fake; cleanup and final output
remain production handler code from each selected candidate.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

REPO = Path(
    os.environ.get("I42_CLEANUP_REPO_ROOT", str(Path(__file__).resolve().parents[2]))
)
CANDIDATE = Path(os.environ.get("I42_CLEANUP_CANDIDATE_ROOT", str(REPO))) / "examples" / "unified"
ENTRIES = {
    "013_1": ("013_1_midfreq_cross_arbitrage", "write"),
    "013_2": ("013_2_highfreq_calendar_arbitrage", "write"),
    "013_3": ("013_3_sa_midfreq_simnow", "write"),
    "014_1": ("014_1_ctp_options_lowfreq", "write"),
}


def healthy_close_health() -> dict[str, object]:
    return {
        "shutdown_state": "PASS",
        "worker_alive": False,
        "close_thread_alive": False,
        "funding_worker_alive": False,
        "restart_blocked_by_worker": False,
        "restart_blocked_by_close": False,
        "funding_restart_blocked_by_worker": False,
        "read_only_metadata_probe_active": False,
        "funding_inflight": False,
        "queue_depth": 0,
        "inflight": 0,
        "publications_pending": 0,
        "broker_update_queue_depth": 0,
        "funding_queue_depth": 0,
        "funding_pending": 0,
    }


class FakeStore:
    instances: ClassVar[list[FakeStore]] = []
    mode = "normal"
    expected_run_file: Path | None = None
    order_refs_override: tuple[str, ...] | None = None
    trade_rows_override: list[dict[str, object]] | None = None

    def __init__(self, **kwargs: object) -> None:
        self.index = len(type(self).instances)
        self.config = dict(kwargs.get("config") or {})
        self.stop_calls = 0
        self.disarm_calls = 0
        self.arm_calls = 0
        self.lifecycle: list[str] = []
        order_refs = type(self).order_refs_override or (
            "entry-m",
            "close-m",
            "entry-rm",
            "close-rm",
        )
        self._api = SimpleNamespace(_order_state={order_ref: {} for order_ref in order_refs})
        type(self).instances.append(self)

    def start(self) -> None:
        self.lifecycle.append("start")

    def registered_sim_wait_ready(self, timeout: float = 0.0) -> bool:
        return True

    def registered_sim_login_facts(self) -> dict[str, object]:
        return {
            "read_only_ready": True,
            "trading_ready": True,
            "trading_day": "20261012",
            "connection_generation": 3,
        }

    def registered_sim_query(self, kind: str, timeout: float = 0.0, **filters: object):
        if kind == "positions_result":
            return {"rows": []}
        if kind == "orders_result":
            return {"rows": []}
        if kind == "account_result":
            return {"rows": [{"Balance": 100000.0}]}
        if kind == "trades_result":
            if type(self).trade_rows_override is not None:
                return {"rows": list(type(self).trade_rows_override)}
            return {
                "rows": [
                    {"OrderRef": "entry-m", "InstrumentID": "M2601", "OffsetFlag": "0", "Volume": 1},
                    {"OrderRef": "close-m", "InstrumentID": "M2601", "OffsetFlag": "1", "Volume": 1},
                    {"OrderRef": "entry-rm", "InstrumentID": "RM2601", "OffsetFlag": "0", "Volume": 1},
                    {"OrderRef": "close-rm", "InstrumentID": "RM2601", "OffsetFlag": "1", "Volume": 1},
                ]
            }
        return {"rows": []}

    def registered_sim_arm(self, **kwargs: object) -> dict[str, object]:
        self.arm_calls += 1
        if type(self).mode.startswith("admission_error"):
            raise RuntimeError("synthetic admission secret")
        return {"armed": True, "state": "ARMED"}

    def registered_sim_disarm(self, reason: str) -> None:
        self.disarm_calls += 1
        self.lifecycle.append("disarm")
        if type(self).mode == "admission_error" or (
            type(self).mode == "disarm_error" and reason != "admission_verify_next_leg"
        ):
            raise RuntimeError("synthetic disarm secret")

    def registered_sim_freeze(self, reason: str) -> dict[str, object]:
        self.lifecycle.append("freeze")
        return {"frozen": True}

    def registered_sim_configure_arm_templates(self, templates: object) -> None:
        self.lifecycle.append("configure_templates")

    def registered_sim_ensure_arm(self, instrument: str, exchange: str) -> None:
        self.lifecycle.append("ensure_arm")

    def registered_sim_status(self) -> str:
        return "ARMED"

    def registered_sim_arm_history(self) -> list[object]:
        return []

    def getdata(self, **kwargs: object) -> object:
        return object()

    def configure_live_tick_provenance(self, provenance: object) -> None:
        pass

    def stop(self, timeout: float = 0.0) -> object:
        self.stop_calls += 1
        self.lifecycle.append("stop")
        if type(self).expected_run_file is not None and type(self).expected_run_file.exists():
            before_close = json.loads(type(self).expected_run_file.read_text(encoding="utf-8"))
            assert before_close.get("status") != "PASS", "PASS was persisted before Store.stop confirmation"
        if type(self).mode == "stop_error":
            raise RuntimeError("synthetic stop secret")
        health = healthy_close_health()
        if type(self).mode == "worker_pending":
            health["worker_alive"] = True
        elif type(self).mode == "stop_nonpass":
            health["shutdown_state"] = "INCOMPLETE"
        elif type(self).mode == "admission_error_worker_pending":
            health["worker_alive"] = True
        return health


class FakeStrategy:
    def __init__(self, **kwargs: object) -> None:
        self.state = "STOPPED_FLAT"
        self.state_reason = "synthetic_complete"

    def _report_context(self) -> dict[str, object]:
        return {
            "state": self.state,
            "state_reason": self.state_reason,
            "halted": False,
            "pair_actions": [],
        }

    def report(self) -> dict[str, object]:
        return {"state": "STOPPED_FLAT", "basket_status": "FLAT"}


class FakeRuntimeControl:
    def __init__(self) -> None:
        self.stop_reason = None

    def request_stop(self, reason: str) -> None:
        self.stop_reason = reason


class FakeClockMapping:
    mapping_id = "source-fake-clock-map"
    synthetic = False


class FakeLiveClock:
    def __init__(self, *, generation: int, rules_hash: str, source: str, validity_seconds: float) -> None:
        self.generation = generation
        self.rules_hash = rules_hash
        self.source = source
        self.domain = "source-fake-clock-domain"
        self.mapping = FakeClockMapping()

    def provenance(self, *, session_segment: str) -> dict[str, object]:
        return {
            "clock_domain_id": self.domain,
            "rules_hash": self.rules_hash,
            "session_segment": session_segment,
            "generation": self.generation,
            "source": self.source,
        }

    def observation(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "generation": self.generation,
            "mapping_id": self.mapping.mapping_id,
            "trusted": True,
        }


class NoThread:
    def __init__(self, **kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        pass


def _load_candidate(monkeypatch, key: str):
    folder, _kind = ENTRIES[key]
    candidate_dir = CANDIDATE / folder
    source_dir = REPO / "examples" / "unified" / folder
    monkeypatch.syspath_prepend(str(source_dir))
    spec = importlib.util.spec_from_file_location(f"candidate_run_{key}", candidate_dir / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "sys", SimpleNamespace(version_info=(3, 11, 5)))
    return module, source_dir


def _install_leaf_modules(monkeypatch) -> None:
    FakeStore.instances = []
    FakeStore.mode = "normal"
    FakeStore.expected_run_file = None
    FakeStore.order_refs_override = None
    FakeStore.trade_rows_override = None

    simnow = types.ModuleType("simnow_direct")
    simnow.SimNowDirectError = type("SimNowDirectError", (RuntimeError,), {})
    simnow.RegisteredSimStore = FakeStore
    simnow.canonical_sha256 = lambda value: "a" * 64
    simnow.strategy_identity_sha256 = lambda *args, **kwargs: "b" * 64
    simnow.select_front_pair = lambda configured, env, **kwargs: {
        "ordered_pairs": [
            dict(pair, kind=pair.get("kind", "standard"), whitelisted=None, score_ms=1.0)
            for pair in configured
        ],
        "receipt": {"samples": 3},
    }
    monkeypatch.setitem(sys.modules, "simnow_direct", simnow)

    legacy = types.ModuleType("legacy_runner")
    legacy.load_config = lambda: {
        "timing": {
            "idle_interval_ms": 50,
            "first_send_seconds": 10,
            "completion_seconds": 20,
            "minimum_hold_seconds": 1,
            "maximum_hold_seconds": 30,
            "risk_bar_max_age_seconds": 15,
            "session_stop_entry_seconds": 60,
            "session_exit_seconds": 30,
            "session_handover_seconds": 10,
        },
        "candidate": {
            "future": "ZCE.FG601",
            "call": "ZCE.FG601C10000",
            "put": "ZCE.FG601P10000",
            "strike": 10000,
            "multiplier": 10,
            "discount": 0.0,
        },
        "strategy_params": {"order_lots": 1},
        "budget": {"capital_limit": 100000.0, "ordinary_limit": 50000.0, "recovery_reserve": 10000.0},
    }
    legacy.close_offset_for_exchange = lambda exchange: "1"
    legacy.account_fingerprint = lambda broker_id, user_id: "fake-account-fingerprint"

    class FakeRiskStore:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def load_or_create(self, **kwargs: object) -> None:
            pass

    legacy.DailyRiskStore = FakeRiskStore
    legacy.EvidenceWriter = lambda *args, **kwargs: object()
    legacy._strategy_params = lambda *args, **kwargs: {}
    legacy._attach_trade_logger = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "legacy_runner", legacy)

    backtrader = types.ModuleType("backtrader")
    backtrader.__path__ = []
    backtrader.TimeFrame = SimpleNamespace(Minutes=1)

    class FakeCerebro:
        def __init__(self, **kwargs: object) -> None:
            self._event_stop = SimpleNamespace(is_set=lambda: True)
            self.runstrats: list[list[object]] = []
            self.strategy = None

        def setbroker(self, broker: object) -> None:
            pass

        def adddata(self, feed: object, name: str | None = None) -> None:
            pass

        def addstrategy(self, strategy: object, **kwargs: object) -> None:
            self.strategy = strategy(**kwargs)

        def run(self) -> None:
            self.runstrats = [[self.strategy]]

        def runstop(self) -> None:
            pass

    backtrader.Cerebro = FakeCerebro
    brokers = types.ModuleType("backtrader.brokers")
    brokers.__path__ = []
    broker_module = types.ModuleType("backtrader.brokers.btapibroker")
    broker_module.BtApiBroker = lambda **kwargs: object()
    monkeypatch.setitem(sys.modules, "backtrader", backtrader)
    monkeypatch.setitem(sys.modules, "backtrader.brokers", brokers)
    monkeypatch.setitem(sys.modules, "backtrader.brokers.btapibroker", broker_module)

    strategy_module = types.ModuleType("pair_arbitrage_strategy")
    strategy_module.PairArbitrageStrategy = FakeStrategy
    monkeypatch.setitem(sys.modules, "pair_arbitrage_strategy", strategy_module)
    calendar_strategy_module = types.ModuleType("calendar_arbitrage_strategy")
    calendar_strategy_module.PairArbitrageStrategy = FakeStrategy
    monkeypatch.setitem(sys.modules, "calendar_arbitrage_strategy", calendar_strategy_module)
    sa_module = types.ModuleType("sa_midfreq_strategy")
    sa_module.RuntimeControl = FakeRuntimeControl
    sa_module.SAMidFrequencyStrategy = FakeStrategy
    monkeypatch.setitem(sys.modules, "sa_midfreq_strategy", sa_module)
    options_strategy_module = types.ModuleType("ctp_options_lowfreq_strategy")
    options_strategy_module.CtpOptionsLowfreqStrategy = FakeStrategy
    monkeypatch.setitem(sys.modules, "ctp_options_lowfreq_strategy", options_strategy_module)


def _credentials() -> tuple[dict[str, str], dict[str, str]]:
    names = {
        "broker_id_env": "FAKE_BROKER",
        "user_id_env": "FAKE_USER",
        "password_env": "FAKE_PASSWORD",
        "app_id_env": "FAKE_APP",
        "auth_code_env": "FAKE_AUTH",
    }
    env = dict(zip(names.values(), ("9999", "fake-user", "fake-pass", "fake-app", "fake-auth")))
    return names, env


def _pair(index: int) -> dict[str, object]:
    return {"index": index, "md_front": f"m://fake:{index + 1}", "td_front": f"t://fake:{index + 2}"}


def _configure_handler(monkeypatch, key: str, module, source_dir: Path, tmp_path: Path) -> None:
    names, env = _credentials()
    common = {
        "credentials": names,
        "fronts": {"pairs": [_pair(0), _pair(1)]},
        "timeouts": {"login_seconds": 1.0, "query_seconds": 1.0, "stop_seconds": 1.0, "drain_seconds": 1.0, "run_seconds": 0.01},
        "policy": {"max_actions": 4},
        "strategy_params": {"order_lots": 1},
        "feed": {},
        "live_contracts": {"symbols": "auto", "exchanges": {"SHFE": "x"}},
        "live_market_data": {"allow_zero_login_response": False},
        "instrument_metadata": {},
        "live_contract": {"instrument": "SA2601", "exchange": "CZCE"},
    }
    config_path = tmp_path / f"{key}-config.yaml"
    config_path.write_text("public fake config\n", encoding="utf-8")
    monkeypatch.setattr(module, "_load_env", lambda: env)
    monkeypatch.setattr(module, "_ensure_dev_sdk_path", lambda strict=False: None)

    if key in {"013_1", "013_2"}:
        monkeypatch.setattr(module, "_load_config", lambda: (common, config_path))
        monkeypatch.setattr(module, "_new_section_errors", lambda config: [])
        monkeypatch.setattr(module, "_resolve_live_contracts", lambda config: [("m2601", "DCE"), ("rm2601", "CZCE")])
        monkeypatch.setattr(
            module,
            "_live_preflight",
            lambda *args, **kwargs: {
                "login": {"trading_day": "20261012", "connection_generation": 3},
                "trading_day": "20261012",
                "metadata": [{"price_tick": 1.0}, {"price_tick": 1.0}],
                "account_rows": 1,
                "positions_open_rows": 0,
                "orders_active_rows": 0,
                "starting_equity": 100000.0,
            },
        )
        monkeypatch.setattr(module, "_attach_trade_logger", lambda *args, **kwargs: None)
    elif key == "013_3":
        monkeypatch.setattr(module, "_load_config", lambda: (common, {}, config_path))
        monkeypatch.setattr(module, "_new_section_errors", lambda config: [])
        monkeypatch.setattr(
            module,
            "_live_preflight",
            lambda *args, **kwargs: {
                "login": {"trading_day": "20261012", "connection_generation": 3},
                "trading_day": "20261012",
                "metadata": {},
                "account_rows": 1,
                "positions_open_rows": 0,
                "orders_active_rows": 0,
                "starting_equity": 100000.0,
                "fee": {"source": "synthetic", "verified": True},
            },
        )
    elif key == "014_1":
        live = {**common, "live_candidate": {}, "fronts": {"pairs": [_pair(0), _pair(1)]}}
        case_home = tmp_path / "candidate-home-014_1"
        case_home.mkdir(parents=True, exist_ok=True)
        (case_home / "config.yaml").write_text("public fake config\n", encoding="utf-8")
        monkeypatch.setattr(module, "HERE", case_home)
        monkeypatch.setattr(module, "_load_raw_config", lambda: {module.LIVE_ADAPTER_KEY: live})
        monkeypatch.setattr(module, "_live_section_errors", lambda value: [])
        monkeypatch.setattr(
            module,
            "_leg_metadata",
            lambda store, code, exchange, live, full_symbol, timeout: {
                "symbol": full_symbol,
                "price_tick": 1.0,
                "volume_multiple": 20.0,
                "lower_limit": 1.0,
                "upper_limit": 20000.0,
            },
        )
        monkeypatch.setattr(
            module,
            "_leg_commission",
            lambda *args, **kwargs: {"source": "synthetic", "verified": True},
        )
        monkeypatch.setattr(module, "_LiveClock", FakeLiveClock)
    if key == "014_1":
        monkeypatch.setattr(module, "_attach_trade_logger", lambda *args, **kwargs: None)


def _args(module, tmp_path: Path) -> SimpleNamespace:
    decision = module.entry_tier.decide({"entry": {"tier": "live"}}, None)
    return SimpleNamespace(
        allow_write=True,
        run_seconds=0.01,
        evidence_dir=str(tmp_path / "evidence"),
        drill=False,
        drill_delay_seconds=None,
        drill_window_seconds=None,
        drill_warmup_bars=None,
        drill_side="long",
        tier_decision=decision,
    )


def _payload(capsys) -> dict[str, object]:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1, lines
    return json.loads(lines[0])


@pytest.fixture
def write_entry(monkeypatch, tmp_path):
    _install_leaf_modules(monkeypatch)
    monkeypatch.setattr(sys.modules["signal"], "signal", lambda *args: None)
    monkeypatch.setattr(sys.modules["signal"], "getsignal", lambda *args: None)
    modules = {}
    for key in ENTRIES:
        module, source_dir = _load_candidate(monkeypatch, key)
        _configure_handler(monkeypatch, key, module, source_dir, tmp_path)
        modules[key] = module
    yield modules, tmp_path


@pytest.mark.parametrize("key", ("013_1", "013_2"))
def test_write_handler_pass_is_persisted_only_after_confirmed_store_close(write_entry, monkeypatch, capsys, key):
    modules, tmp_path = write_entry
    module = modules[key]
    monkeypatch.setattr(module.threading, "Thread", NoThread)
    run_file = tmp_path / "evidence" / "run.json"
    FakeStore.expected_run_file = run_file

    code = module.run_live(_args(module, tmp_path))
    summary = _payload(capsys)
    persisted = json.loads(run_file.read_text(encoding="utf-8"))

    assert code == 0, summary
    assert summary == persisted
    assert summary["status"] == "PASS"
    assert summary["cleanup_status"] == "closed"
    assert FakeStore.instances[0].stop_calls == 1
    assert FakeStore.instances[0].disarm_calls == 2


def _install_business_success_rows(key: str) -> None:
    FakeStore.mode = "business_success"
    if key == "013_3":
        FakeStore.order_refs_override = ("entry-sa", "close-sa")
        FakeStore.trade_rows_override = [
            {"OrderRef": "entry-sa", "InstrumentID": "SA2601", "OffsetFlag": "0", "Volume": 1},
            {"OrderRef": "close-sa", "InstrumentID": "SA2601", "OffsetFlag": "1", "Volume": 1},
        ]
        return

    codes = ("FG601", "FG601C10000", "FG601P10000")
    FakeStore.order_refs_override = tuple(
        ref for code in codes for ref in (f"entry-{code}", f"close-{code}")
    )
    FakeStore.trade_rows_override = [
        {
            "OrderRef": order_ref,
            "InstrumentID": code,
            "OffsetFlag": offset,
            "Volume": 1,
        }
        for code in codes
        for order_ref, offset in ((f"entry-{code}", "0"), (f"close-{code}", "1"))
    ]


@pytest.mark.parametrize("key", ("013_3", "014_1"))
@pytest.mark.parametrize("close_mode", ("normal", "stop_error", "stop_nonpass"))
def test_write_business_pass_is_finalized_by_real_handler_close_result(
    write_entry, monkeypatch, capsys, key, close_mode
):
    modules, tmp_path = write_entry
    module = modules[key]
    monkeypatch.setattr(module.threading, "Thread", NoThread)
    _install_business_success_rows(key)
    if close_mode != "normal":
        FakeStore.mode = close_mode
    run_file = tmp_path / "evidence" / "run.json"
    FakeStore.expected_run_file = run_file

    code = module.run_live(_args(module, tmp_path))
    summary = _payload(capsys)
    persisted = json.loads(run_file.read_text(encoding="utf-8"))

    assert summary == persisted
    assert len(FakeStore.instances) == 1
    assert FakeStore.instances[0].stop_calls == 1
    if close_mode == "normal":
        assert code == 0, summary
        assert summary["status"] == "PASS", summary
        assert summary["cleanup_status"] == "closed"
        assert "cleanup_error" not in summary
    else:
        assert code == 2, summary
        assert summary["status"] == "BLOCKED", summary
        assert summary["reason"] == "cleanup_uncertain"
        assert summary["cleanup_status"] == "uncertain"
        assert summary["cleanup_prior_outcome"]["status"] == "PASS"
        assert summary["cleanup_error"]["failures"]
        assert FakeStore.instances[0] in module._OBSERVATION_CLEANUP_KEEPALIVE
        assert "synthetic stop secret" not in json.dumps(summary)


@pytest.mark.parametrize("key", ("013_1", "013_2", "013_3", "014_1"))
def test_uncertain_admission_cleanup_keeps_primary_type_and_attempt_and_stops_retries(
    write_entry, monkeypatch, capsys, key
):
    modules, tmp_path = write_entry
    module = modules[key]
    FakeStore.mode = "admission_error"
    code = module.run_live(_args(module, tmp_path))
    summary = _payload(capsys)
    persisted = json.loads((tmp_path / "evidence" / "run.json").read_text(encoding="utf-8"))

    assert code == 2
    assert summary == persisted
    assert summary["status"] == "BLOCKED"
    assert summary["reason"] == "cleanup_uncertain", json.dumps(summary, sort_keys=True)
    assert summary["cleanup_status"] == "uncertain"
    assert summary["cleanup_prior_outcome"] == {"business_error_type": "RuntimeError"}
    assert len(summary["admission_attempts"]) == 1
    assert summary["admission_attempts"][0]["error_type"] == "RuntimeError"
    assert summary["admission_attempts"][0]["cleanup_status"] == "uncertain"
    assert summary["cleanup_error"]["failures"][0] == {
        "phase": "registered_sim_disarm",
        "exception_type": "RuntimeError",
    }
    assert "synthetic admission secret" not in json.dumps(summary)
    assert "synthetic disarm secret" not in json.dumps(summary)
    assert len(FakeStore.instances) == 1
    assert FakeStore.instances[0].stop_calls == 1
    assert FakeStore.instances[0].disarm_calls == 1
    assert FakeStore.instances[0] in module._OBSERVATION_CLEANUP_KEEPALIVE


@pytest.mark.parametrize("key", ("013_1", "013_2", "013_3", "014_1"))
def test_uncertain_admission_worker_pending_is_recorded_once_without_next_front(
    write_entry, capsys, key
):
    modules, tmp_path = write_entry
    module = modules[key]
    FakeStore.mode = "admission_error_worker_pending"

    code = module.run_live(_args(module, tmp_path))
    summary = _payload(capsys)
    persisted = json.loads((tmp_path / "evidence" / "run.json").read_text(encoding="utf-8"))

    assert code == 2
    assert summary == persisted
    assert summary["reason"] == "cleanup_uncertain"
    assert summary["cleanup_prior_outcome"] == {"business_error_type": "RuntimeError"}
    assert len(summary["admission_attempts"]) == 1
    assert summary["admission_attempts"][0]["error_type"] == "RuntimeError"
    assert summary["cleanup_error"]["failures"] == [
        {
            "phase": "store_stop",
            "reason": "health_flag_not_false",
            "field": "worker_alive",
        }
    ]
    assert len(FakeStore.instances) == 1
    assert FakeStore.instances[0].stop_calls == 1
    assert FakeStore.instances[0].disarm_calls == 1
    assert FakeStore.instances[0] in module._OBSERVATION_CLEANUP_KEEPALIVE
    assert "synthetic admission secret" not in json.dumps(summary)


@pytest.mark.parametrize("key", ("013_1", "013_2"))
@pytest.mark.parametrize(
    "failure", ("stop_error", "stop_nonpass", "worker_pending", "disarm_error")
)
def test_write_handler_cleanup_failure_overrides_pass_with_bounded_projection(
    write_entry, monkeypatch, capsys, key, failure
):
    modules, tmp_path = write_entry
    module = modules[key]
    monkeypatch.setattr(module.threading, "Thread", NoThread)
    FakeStore.mode = failure
    run_file = tmp_path / "evidence" / "run.json"
    FakeStore.expected_run_file = run_file

    code = module.run_live(_args(module, tmp_path))
    summary = _payload(capsys)
    persisted = json.loads(run_file.read_text(encoding="utf-8"))

    assert code == 2
    assert summary == persisted
    assert summary["status"] == "BLOCKED"
    assert summary["reason"] == "cleanup_uncertain"
    assert summary["cleanup_status"] == "uncertain"
    assert summary["cleanup_prior_outcome"] == {"status": "PASS"}, summary
    expected = {
        "stop_error": {"phase": "store_stop", "exception_type": "RuntimeError"},
        "stop_nonpass": {"phase": "store_stop", "reason": "shutdown_state_not_pass"},
        "worker_pending": {
            "phase": "store_stop",
            "reason": "health_flag_not_false",
            "field": "worker_alive",
        },
        "disarm_error": {"phase": "registered_sim_disarm", "exception_type": "RuntimeError"},
    }[failure]
    assert expected in summary["cleanup_error"]["failures"]
    assert FakeStore.instances[0].stop_calls == 1
    assert FakeStore.instances[0] in module._OBSERVATION_CLEANUP_KEEPALIVE
    assert "synthetic stop secret" not in json.dumps(summary)
    assert "synthetic disarm secret" not in json.dumps(summary)
