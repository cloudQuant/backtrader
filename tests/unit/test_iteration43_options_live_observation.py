"""R5b-2 observation-lifecycle coverage for the options entry (014_1).

Kept separate from the pair-family file because 014_1 resolves three legs from
``candidate.future/call/put`` and reads its live settings from the
``live_adapter`` section, so its prelude differs; the observation contract that
is asserted here is identical.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "examples" / "unified" / "014_1_ctp_options_lowfreq"


def _healthy_close_health() -> dict[str, object]:
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


class WriteTouched(AssertionError):
    """Raised when the observation path reaches any write-capable method."""


class FakeStore:
    instances: list[FakeStore] = []
    fail_stop_indexes: set[int] = set()
    fail_wait_ready_indexes: set[int] = set()
    fail_query_indexes: set[int] = set()
    close_health_by_index: dict[int, object] = {}
    write_health_by_index: dict[int, object] = {}
    fail_write_health_indexes: set[int] = set()

    def __init__(self, **kwargs: object) -> None:
        self.init_config = dict(kwargs.get("config") or {})
        self.index = len(FakeStore.instances)
        self.lifecycle: list[str] = []
        self.queries: list[str] = []
        self.stop_calls = 0
        FakeStore.instances.append(self)

    def start(self) -> None:
        self.lifecycle.append("start")

    def stop(self, timeout: float = 0.0) -> object:
        self.lifecycle.append("stop")
        self.stop_calls += 1
        if self.index in FakeStore.fail_stop_indexes:
            raise RuntimeError("synthetic stop failure secret")
        return FakeStore.close_health_by_index.get(self.index, _healthy_close_health())

    def registered_sim_wait_ready(self, timeout: float = 0.0) -> bool:
        self.lifecycle.append("wait_ready")
        if self.index in FakeStore.fail_wait_ready_indexes:
            raise RuntimeError("synthetic wait_ready failure")
        return True

    def registered_sim_login_facts(self) -> dict[str, object]:
        return {"read_only_ready": True, "trading_day": "20261009", "connection_generation": 1}

    def registered_sim_query(self, kind: str, timeout: float = 0.0, **filters: object) -> dict[str, object]:
        self.queries.append(kind)
        if self.index in FakeStore.fail_query_indexes:
            raise RuntimeError("synthetic query failure")
        rows = {
            "account_result": 1,
            "positions_result": [{"Position": 2}, {"Position": 0}],
            "orders_result": [{"OrderStatus": "3", "VolumeTotal": 1, "VolumeTraded": 0}, {"OrderStatus": "5"}],
            "trades_result": 3,
        }
        value = rows.get(kind)
        if isinstance(value, int):
            return {"rows": [{} for _ in range(value)]}
        return {"rows": value or []}

    def registered_sim_write_health(self) -> object:
        if self.index in FakeStore.fail_write_health_indexes:
            raise RuntimeError("synthetic write-health failure secret")
        # Faithful public API shape; these Store-local facts do not prove
        # native-wide or process-wide absence of writes.
        return FakeStore.write_health_by_index.get(
            self.index,
            {"armed": False, "frozen": False, "active_orders": 0},
        )

    def __getattr__(self, name: str):
        if any(word in name for word in ("arm", "submit", "cancel", "send", "freeze", "disarm")):
            raise WriteTouched(f"observation path touched write method {name!r}")
        raise AttributeError(name)


LIVE = {
    "schema_version": 1,
    "venue": "simnow",
    "credentials": {
        "broker_id_env": "FAKE_BROKER",
        "user_id_env": "FAKE_USER",
        "password_env": "FAKE_PASSWORD",
        "app_id_env": "FAKE_APP",
        "auth_code_env": "FAKE_AUTH",
    },
    "fronts": {"pairs": [{"index": 0, "md_front": "m://fake:1", "td_front": "t://fake:2"}]},
    "timeouts": {"login_seconds": 1.0, "query_seconds": 1.0, "stop_seconds": 1.0},
    "live_market_data": {"allow_zero_login_response": False},
}


@pytest.fixture
def entry(monkeypatch, tmp_path):
    FakeStore.instances = []
    FakeStore.fail_stop_indexes = set()
    FakeStore.fail_wait_ready_indexes = set()
    FakeStore.fail_query_indexes = set()
    FakeStore.close_health_by_index = {}
    FakeStore.write_health_by_index = {}
    FakeStore.fail_write_health_indexes = set()
    fake = types.ModuleType("simnow_direct")
    fake.SimNowDirectError = type("SimNowDirectError", (RuntimeError,), {})
    fake.RegisteredSimStore = FakeStore
    fake.canonical_sha256 = lambda value: "0" * 64
    fake.strategy_identity_sha256 = lambda path, scope: "1" * 64
    fake.select_front_pair = lambda configured, env, **kwargs: {
        "ordered_pairs": [dict(pair, kind=pair.get("kind") or "standard", whitelisted=None, score_ms=1.5) for pair in configured]
    }
    legacy = types.ModuleType("legacy_runner")
    legacy.load_config = lambda: {
        "candidate": {"future": "ZCE.FG601", "call": "ZCE.FG601C10000", "put": "ZCE.FG601P10000"}
    }
    blocker = types.ModuleType("backtrader.brokers.btapibroker")
    blocker.BtApiBroker = lambda *a, **k: (_ for _ in ()).throw(WriteTouched("BtApiBroker constructed"))
    monkeypatch.setitem(sys.modules, "simnow_direct", fake)
    monkeypatch.setitem(sys.modules, "legacy_runner", legacy)
    monkeypatch.setitem(sys.modules, "backtrader.brokers.btapibroker", blocker)
    monkeypatch.syspath_prepend(str(FOLDER))
    spec = importlib.util.spec_from_file_location("entry_run_014_1", FOLDER / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "_load_raw_config", lambda: {module.LIVE_ADAPTER_KEY: dict(LIVE)})
    monkeypatch.setattr(module, "_live_section_errors", lambda live: [])
    monkeypatch.setattr(
        module,
        "_load_env",
        lambda: {
            "FAKE_BROKER": "9999",
            "FAKE_USER": "observer",
            "FAKE_PASSWORD": "secret-not-printed",
            "FAKE_APP": "app",
            "FAKE_AUTH": "auth",
        },
    )
    monkeypatch.setattr(module, "_ensure_dev_sdk_path", lambda strict=False: None)

    yield module, tmp_path
    sys.modules.pop("entry_run_014_1", None)


def _args(tmp_path: Path, module) -> SimpleNamespace:
    decision = module.entry_tier.decide({"entry": {"tier": "live"}}, None)
    return SimpleNamespace(evidence_dir=str(tmp_path / "evidence"), run_seconds=None, drill=False, allow_write=False, tier_decision=decision)


def _payload(capsys) -> dict[str, object]:
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line.strip()]
    assert lines, "the observation channel printed nothing"
    assert len(lines) == 1, lines
    return json.loads(lines[-1])


def test_options_observe_lifecycle_reads_and_never_writes(entry, capsys) -> None:
    module, tmp_path = entry
    assert module.run_live_observe(_args(tmp_path, module)) == 0
    summary = _payload(capsys)

    assert summary["status"] == "LIVE_OBSERVE_PASS", summary
    assert summary["channel"] == "observe" and summary["mode"] == "live", summary
    assert summary["entry_tier"]["effective_tier"] == "live", summary
    assert summary["write_grant_result"] == "not_required_observation_only", summary
    assert summary["legs"] == ["ZCE.FG601", "ZCE.FG601C10000", "ZCE.FG601P10000"], summary
    assert summary["readings"] == {
        "account_rows": 1,
        "position_rows": 2,
        "open_position_rows": 1,
        "order_rows": 2,
        "active_order_rows": 1,
        "trade_rows": 3,
    }, summary
    assert summary["write_health"] == {
        "armed": False,
        "frozen": False,
        "active_orders": 0,
    }

    store = FakeStore.instances[0]
    assert store.lifecycle == ["start", "wait_ready", "stop"], store.lifecycle
    assert store.stop_calls == 1
    assert summary["cleanup_status"] == "closed", summary
    assert store.queries == ["positions_result", "orders_result", "account_result", "trades_result"], store.queries
    persisted = json.loads((tmp_path / "evidence" / "run.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "LIVE_OBSERVE_PASS", persisted
    assert persisted["cleanup_status"] == "closed", persisted


@pytest.mark.parametrize(
    "variant",
    [
        "incomplete",
        "fail",
        "missing_field",
        "none",
        "worker_alive",
        "funding_inflight_type",
        "queue_type",
        "queue_nonzero",
    ],
)
def test_options_unconfirmed_front_close_health_blocks_and_prevents_retry(
    entry, monkeypatch, capsys, variant: str
) -> None:
    module, tmp_path = entry
    FakeStore.fail_query_indexes = {0}
    health = _healthy_close_health()
    close_health: object = health
    if variant == "incomplete":
        health["shutdown_state"] = "INCOMPLETE"
    elif variant == "fail":
        health["shutdown_state"] = "FAIL"
    elif variant == "missing_field":
        health.pop("funding_worker_alive")
    elif variant == "none":
        close_health = None
    elif variant == "worker_alive":
        health["worker_alive"] = True
    elif variant == "funding_inflight_type":
        health["funding_inflight"] = 0
    elif variant == "queue_type":
        health["queue_depth"] = False
    elif variant == "queue_nonzero":
        health["queue_depth"] = 1
    FakeStore.close_health_by_index = {0: close_health}
    first = LIVE["fronts"]["pairs"][0]
    second = {**first, "index": 1, "md_front": "m://fake:3", "td_front": "t://fake:4"}
    monkeypatch.setattr(
        module,
        "_load_raw_config",
        lambda: {module.LIVE_ADAPTER_KEY: {**LIVE, "fronts": {"pairs": [first, second]}}},
    )

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _payload(capsys)
    persisted = json.loads((tmp_path / "evidence" / "run.json").read_text(encoding="utf-8"))

    assert code != 0, code
    assert summary["status"] == persisted["status"] == "BLOCKED", summary
    assert summary["reason"] == persisted["reason"] == "cleanup_uncertain", summary
    expected_error = {
        "incomplete": {"reason": "shutdown_state_not_pass"},
        "fail": {"reason": "shutdown_state_not_pass"},
        "missing_field": {"reason": "health_field_missing", "field": "funding_worker_alive"},
        "none": {"reason": "health_not_mapping"},
        "worker_alive": {"reason": "health_flag_not_false", "field": "worker_alive"},
        "funding_inflight_type": {"reason": "health_flag_not_false", "field": "funding_inflight"},
        "queue_type": {"reason": "health_count_not_zero", "field": "queue_depth"},
        "queue_nonzero": {"reason": "health_count_not_zero", "field": "queue_depth"},
    }[variant]
    assert summary["cleanup_status"] == "uncertain", summary
    assert summary["cleanup_error"] == {"phase": "front_attempt_stop", **expected_error}, summary
    assert len(FakeStore.instances) == len(summary["admission_attempts"]) == 1, summary
    assert FakeStore.instances[0].stop_calls == 1
    assert module._OBSERVATION_CLEANUP_KEEPALIVE == [FakeStore.instances[0]]
    assert persisted["cleanup_error"] == summary["cleanup_error"], persisted


def test_options_selected_store_stop_failure_blocks_and_retains_ownership(entry, capsys) -> None:
    module, tmp_path = entry
    FakeStore.fail_stop_indexes = {0}
    FakeStore.write_health_by_index = {
        0: {"armed": True, "frozen": False, "active_orders": 0}
    }

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _payload(capsys)
    persisted = json.loads((tmp_path / "evidence" / "run.json").read_text(encoding="utf-8"))

    assert code != 0, code
    assert summary["status"] == persisted["status"] == "BLOCKED", summary
    assert summary["reason"] == persisted["reason"] == "cleanup_uncertain", summary
    assert summary["write_health_error"] == persisted["write_health_error"] == {
        "reason": "health_flag_not_false",
        "field": "armed",
    }, summary
    assert summary["cleanup_error"] == persisted["cleanup_error"] == {
        "phase": "selected_store_stop",
        "exception_type": "RuntimeError",
    }, summary
    assert summary["cleanup_status"] == persisted["cleanup_status"] == "uncertain", summary
    assert "synthetic stop failure secret" not in json.dumps(summary), summary
    assert summary["admission_attempts"][0]["cleanup_status"] == "uncertain", summary
    assert FakeStore.instances[0].stop_calls == 1
    assert module._OBSERVATION_CLEANUP_KEEPALIVE == [FakeStore.instances[0]]


def test_options_wait_ready_and_stop_failure_blocks_without_retry(entry, monkeypatch, capsys) -> None:
    module, tmp_path = entry
    FakeStore.fail_wait_ready_indexes = {0}
    FakeStore.fail_stop_indexes = {0}
    configured_pair = LIVE["fronts"]["pairs"][0]
    second_pair = {**configured_pair, "index": 1, "md_front": "m://fake:3", "td_front": "t://fake:4"}
    monkeypatch.setattr(
        module,
        "_load_raw_config",
        lambda: {module.LIVE_ADAPTER_KEY: {**LIVE, "fronts": {"pairs": [configured_pair, second_pair]}}},
    )

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _payload(capsys)
    persisted = json.loads((tmp_path / "evidence" / "run.json").read_text(encoding="utf-8"))

    assert code != 0, code
    assert summary["status"] == persisted["status"] == "BLOCKED", summary
    assert summary["reason"] == "cleanup_uncertain", summary
    assert summary["cleanup_status"] == "uncertain", summary
    assert summary["cleanup_error"]["phase"] == "front_attempt_stop", summary
    assert summary["admission_attempts"][0]["reason"] == "login_not_ready", summary
    assert summary["admission_attempts"][0]["cleanup_status"] == "uncertain", summary
    assert "synthetic stop failure secret" not in json.dumps(summary), summary
    assert len(FakeStore.instances) == 1, "an uncertain front was followed by a second store"
    assert FakeStore.instances[0].stop_calls == 1
    assert module._OBSERVATION_CLEANUP_KEEPALIVE == [FakeStore.instances[0]]
    assert persisted["cleanup_error"] == summary["cleanup_error"], persisted


def test_options_failed_first_front_cleanup_error_stops_candidate_retry(entry, monkeypatch, capsys) -> None:
    module, tmp_path = entry
    FakeStore.fail_query_indexes = {0}
    FakeStore.fail_stop_indexes = {0}
    configured_pair = LIVE["fronts"]["pairs"][0]
    second_pair = {**configured_pair, "index": 1, "md_front": "m://fake:3", "td_front": "t://fake:4"}
    monkeypatch.setattr(
        module,
        "_load_raw_config",
        lambda: {module.LIVE_ADAPTER_KEY: {**LIVE, "fronts": {"pairs": [configured_pair, second_pair]}}},
    )

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _payload(capsys)
    persisted = json.loads((tmp_path / "evidence" / "run.json").read_text(encoding="utf-8"))

    assert code != 0, code
    assert summary["status"] == persisted["status"] == "BLOCKED", summary
    assert summary["reason"] == "cleanup_uncertain", summary
    assert summary["cleanup_status"] == "uncertain", summary
    assert summary["admission_attempts"][0]["cleanup_error"]["exception_type"] == "RuntimeError", summary
    assert "synthetic stop failure secret" not in json.dumps(summary), summary
    assert len(summary["admission_attempts"]) == len(FakeStore.instances) == 1, summary
    assert FakeStore.instances[0].stop_calls == 1
    assert module._OBSERVATION_CLEANUP_KEEPALIVE == [FakeStore.instances[0]]
    assert persisted["admission_attempts"] == summary["admission_attempts"], persisted


def test_options_observe_does_not_refuse_a_dirty_account(entry, monkeypatch, capsys) -> None:
    """Residual exposure is the write drill's gate; observation reports it and passes."""

    module, tmp_path = entry
    assert module.run_live_observe(_args(tmp_path, module)) == 0
    summary = _payload(capsys)
    assert summary["readings"]["open_position_rows"] == 1, summary
    assert summary["readings"]["active_order_rows"] == 1, summary
    assert summary["status"] == "LIVE_OBSERVE_PASS", summary


def test_options_live_routes_by_write_grant(entry, monkeypatch) -> None:
    module, tmp_path = entry
    seen: list[str] = []
    monkeypatch.setattr(module, "run_live", lambda args: seen.append("drill") or 0)
    monkeypatch.setattr(module, "run_live_observe", lambda args: seen.append("observe") or 0)
    module.main(["--live"])
    assert seen == ["observe"], seen
    seen.clear()
    module.main(["--live", "--allow-write"])
    assert seen == ["drill"], seen


@pytest.mark.parametrize(
    "health, expected",
    [
        pytest.param(None, {"reason": "health_not_mapping"}, id="none"),
        pytest.param({}, {"reason": "health_field_missing", "field": "armed"}, id="missing-armed"),
        pytest.param(
            {"armed": False},
            {"reason": "health_field_missing", "field": "frozen"},
            id="missing-frozen",
        ),
        pytest.param(
            {"armed": False, "frozen": False},
            {"reason": "health_field_missing", "field": "active_orders"},
            id="missing-active-orders",
        ),
        pytest.param(
            {"armed": 0, "frozen": False, "active_orders": 0},
            {"reason": "health_flag_not_false", "field": "armed"},
            id="armed-wrong-type",
        ),
        pytest.param(
            {"armed": True, "frozen": False, "active_orders": 0},
            {"reason": "health_flag_not_false", "field": "armed"},
            id="armed",
        ),
        pytest.param(
            {"armed": False, "frozen": 0, "active_orders": 0},
            {"reason": "health_flag_not_false", "field": "frozen"},
            id="frozen-wrong-type",
        ),
        pytest.param(
            {"armed": False, "frozen": True, "active_orders": 0},
            {"reason": "health_flag_not_false", "field": "frozen"},
            id="frozen",
        ),
        pytest.param(
            {"armed": False, "frozen": False, "active_orders": False},
            {"reason": "health_count_not_zero", "field": "active_orders"},
            id="active-orders-bool",
        ),
        pytest.param(
            {"armed": False, "frozen": False, "active_orders": 1},
            {"reason": "health_count_not_zero", "field": "active_orders"},
            id="active-orders-nonzero",
        ),
        pytest.param(
            {
                "armed": False,
                "frozen": False,
                "active_orders": 0,
                "native_send_calls": 1,
            },
            {"reason": "health_count_not_zero", "field": "native_send_calls"},
            id="optional-counter-nonzero",
        ),
        pytest.param(
            {
                "armed": False,
                "frozen": False,
                "active_orders": 0,
                "submit_calls": True,
            },
            {"reason": "health_count_not_zero", "field": "submit_calls"},
            id="optional-counter-wrong-type",
        ),
    ],
)
def test_options_write_health_contract_blocks_unconfirmed_facts(
    entry, capsys, health: object, expected: dict[str, str]
) -> None:
    module, tmp_path = entry
    FakeStore.write_health_by_index = {0: health}

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _payload(capsys)
    persisted = json.loads((tmp_path / "evidence" / "run.json").read_text(encoding="utf-8"))

    assert code != 0, code
    assert summary["status"] == persisted["status"] == "BLOCKED", summary
    assert summary["reason"] == persisted["reason"] == "write_health_unconfirmed", summary
    assert summary["write_health_error"] == persisted["write_health_error"] == expected, summary
    assert "write_health" not in summary
    assert summary["cleanup_status"] == persisted["cleanup_status"] == "closed", summary
    assert len(FakeStore.instances) == 1, summary
    assert FakeStore.instances[0].stop_calls == 1
    assert module._OBSERVATION_CLEANUP_KEEPALIVE == []
    assert "synthetic write-health failure secret" not in json.dumps(summary)


def test_options_write_health_method_exception_is_finite_and_still_closes(
    entry, capsys
) -> None:
    module, tmp_path = entry
    FakeStore.fail_write_health_indexes = {0}

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _payload(capsys)
    persisted = json.loads((tmp_path / "evidence" / "run.json").read_text(encoding="utf-8"))

    assert code != 0, code
    assert summary["status"] == persisted["status"] == "BLOCKED", summary
    assert summary["reason"] == persisted["reason"] == "write_health_unconfirmed", summary
    assert summary["write_health_error"] == persisted["write_health_error"] == {
        "reason": "health_unreadable"
    }, summary
    assert "write_health" not in summary
    assert summary["cleanup_status"] == persisted["cleanup_status"] == "closed", summary
    assert FakeStore.instances[0].stop_calls == 1
    assert module._OBSERVATION_CLEANUP_KEEPALIVE == []
    assert "synthetic write-health failure secret" not in json.dumps(summary)


def test_options_optional_zero_write_health_counters_are_accepted(entry, capsys) -> None:
    module, tmp_path = entry
    health = {
        "armed": False,
        "frozen": False,
        "active_orders": 0,
        "arm_calls": 0,
        "submit_calls": 0,
        "cancel_calls": 0,
        "native_send_calls": 0,
    }
    FakeStore.write_health_by_index = {0: health}

    assert module.run_live_observe(_args(tmp_path, module)) == 0
    summary = _payload(capsys)
    assert summary["status"] == "LIVE_OBSERVE_PASS", summary
    assert summary["write_health"] == health, summary
    assert FakeStore.instances[0].stop_calls == 1
