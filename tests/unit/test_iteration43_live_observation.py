"""Iteration 43 R5b: the live tier without a write grant is a real zero-write session.

``run_live_observe`` must open the session lifecycle for real -- select a whole
front pair, log in, read, close -- while making an order submission structurally
impossible.  The fakes below therefore *are* the tripwires: the observation path
only ever sees read methods, and any write method raises immediately.

The entry module is loaded the way an operator runs it (its own folder on
``sys.path``), so the test exercises the real helper chain including credential
reference resolution, row extraction and instrument-metadata validation.  Only
the OS/provider leaves are faked.
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
# The two entries whose live tier is a SimNow pair-family session: same support
# modules, same read surface, so one fixture covers both.
ENTRIES = ("013_1_midfreq_cross_arbitrage", "013_2_highfreq_calendar_arbitrage")


class WriteTouched(AssertionError):
    """Raised when the observation path reaches any write-capable method."""


WRITE_METHODS = frozenset(
    {
        "registered_sim_arm",
        "registered_sim_disarm",
        "registered_sim_freeze",
        "arm_registered_sim_execution",
        "configure_registered_sim_arm_templates",
        "registered_sim_ensure_arm",
        "_send_native_order_insert",
        "_send_native_order_action",
    }
)


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


class FakeStore:
    """Read-only SimNow session double with an explicit lifecycle log."""

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
        return {
            "read_only_ready": True,
            "trading_ready": False,
            "trading_day": "20261009",
            "connection_generation": 1,
        }

    def registered_sim_query(self, kind: str, timeout: float = 0.0, **filters: object) -> dict[str, object]:
        self.queries.append(kind)
        if self.index in FakeStore.fail_query_indexes:
            raise RuntimeError("synthetic query failure")
        if kind == "instruments_result":
            instrument = str(filters.get("instrument_id") or "")
            return {
                "rows": [
                    {
                        "InstrumentID": instrument,
                        "ExchangeID": filters.get("exchange_id"),
                        "PriceTick": 1.0,
                        "VolumeMultiple": 10.0,
                    }
                ]
            }
        rows = {"account_result": 2, "positions_result": 1, "orders_result": 0, "trades_result": 3}
        return {"rows": [{} for _ in range(rows.get(kind, 0))]}

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
        if name in WRITE_METHODS or "arm" in name or "submit" in name or "cancel" in name or "send" in name:
            raise WriteTouched(f"observation path touched write method {name!r}")
        raise AttributeError(name)


def _fake_simnow() -> types.ModuleType:
    module = types.ModuleType("simnow_direct")
    module.SimNowDirectError = type("SimNowDirectError", (RuntimeError,), {})
    module.RegisteredSimStore = FakeStore
    module.canonical_sha256 = lambda value: "0" * 64
    module.strategy_identity_sha256 = lambda path, scope: "1" * 64
    # Like the real selector, the ranking only reorders the pairs it is given.
    module.select_front_pair = lambda configured, env, **kwargs: {
        "ordered_pairs": [dict(pair, kind=pair.get("kind") or "standard") for pair in configured]
    }
    return module


def _config(pairs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "venue": "simnow",
        "credentials": {
            "broker_id_env": "FAKE_BROKER",
            "user_id_env": "FAKE_USER",
            "password_env": "FAKE_PASSWORD",
            "app_id_env": "FAKE_APP",
            "auth_code_env": "FAKE_AUTH",
        },
        "live_contracts": {"symbols": "auto", "exchanges": {"SHFE": "x"}},
        "fronts": {"pairs": pairs},
        "timeouts": {"login_seconds": 1.0, "query_seconds": 1.0, "stop_seconds": 1.0},
        "live_market_data": {"allow_zero_login_response": False},
        "instrument_metadata": {"rb": {"price_tick": 1.0, "volume_multiple": 10.0}},
        "policy": {},
        "strategy_params": {},
    }


PAIR = {"index": 0, "md_front": "m://fake:1", "td_front": "t://fake:2", "whitelisted": None, "score_ms": 1.5}


@pytest.fixture(params=ENTRIES)
def entry(request, monkeypatch, tmp_path):
    """Load the entry module with its folder importable and only leaves faked."""

    folder = request.param
    folder_root = ROOT / "examples" / "unified" / folder

    FakeStore.instances = []
    FakeStore.fail_stop_indexes = set()
    FakeStore.fail_wait_ready_indexes = set()
    FakeStore.fail_query_indexes = set()
    FakeStore.close_health_by_index = {}
    FakeStore.write_health_by_index = {}
    FakeStore.fail_write_health_indexes = set()
    monkeypatch.syspath_prepend(str(folder_root))
    monkeypatch.setitem(sys.modules, "simnow_direct", _fake_simnow())
    # A broker construction would mean the observation path escaped into the
    # trading stack, so importing it at all is a failure.
    blocker = types.ModuleType("backtrader.brokers.btapibroker")
    blocker.BtApiBroker = lambda *a, **k: (_ for _ in ()).throw(WriteTouched("BtApiBroker constructed"))
    monkeypatch.setitem(sys.modules, "backtrader.brokers.btapibroker", blocker)
    spec = importlib.util.spec_from_file_location(f"entry_run_{folder}", folder_root / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module, tmp_path, folder_root
    sys.modules.pop(f'entry_run_{folder}', None)


def _prepare(monkeypatch, module, folder_root: Path, pairs: list[dict[str, object]]) -> None:
    config = _config(pairs)
    monkeypatch.setattr(module, "_load_config", lambda: (config, folder_root / "config.yaml"))
    monkeypatch.setattr(module, "_new_section_errors", lambda value: [])
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
    monkeypatch.setattr(module, "_resolve_live_contracts", lambda value: [("RB2601", "SHFE"), ("RB2605", "SHFE")])


def _args(tmp_path: Path, module, tier: str = "live") -> SimpleNamespace:
    decision = module.entry_tier.decide({"entry": {"tier": tier}}, None)
    return SimpleNamespace(
        evidence_dir=str(tmp_path / "evidence"), run_seconds=None, drill=False, allow_write=False, tier_decision=decision
    )


def _summary(capsys) -> dict[str, object]:
    payload = [line for line in capsys.readouterr().out.strip().splitlines() if line.strip()]
    assert payload, "the observation channel printed nothing"
    assert len(payload) == 1, payload
    return json.loads(payload[-1])


def test_observe_lifecycle_reads_and_never_writes(entry, monkeypatch, capsys) -> None:
    module, tmp_path, folder_root = entry
    _prepare(monkeypatch, module, folder_root, [PAIR])

    code = module.run_live_observe(_args(tmp_path, module))
    assert code == 0, code
    summary = _summary(capsys)

    assert summary["status"] == "LIVE_OBSERVE_PASS", summary
    assert summary["mode"] == "live" and summary["channel"] == "observe", summary
    assert summary["entry_tier"]["effective_tier"] == "live", summary
    assert summary["write_grant_result"] == "not_required_observation_only", summary
    assert summary["write_health"] == {
        "armed": False,
        "frozen": False,
        "active_orders": 0,
    }
    assert summary["readings"]["account_rows"] == 2, summary
    assert summary["readings"]["position_rows"] == 1, summary
    assert summary["readings"]["trade_rows"] == 3, summary
    assert [row["instrument"] for row in summary["readings"]["instruments"]] == ["RB2601", "RB2605"], summary

    store = FakeStore.instances[0]
    assert store.lifecycle == ["start", "wait_ready", "stop"], store.lifecycle
    assert store.stop_calls == 1
    assert summary["cleanup_status"] == "closed", summary
    assert store.queries == [
        "account_result",
        "positions_result",
        "orders_result",
        "trades_result",
        "instruments_result",
        "instruments_result",
    ], store.queries
    assert len(FakeStore.instances) == 1
    assert (tmp_path / "evidence" / "run.json").is_file()
    persisted = json.loads((tmp_path / "evidence" / "run.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "LIVE_OBSERVE_PASS", persisted
    assert persisted["cleanup_status"] == "closed", persisted


def test_selected_store_stop_failure_blocks_and_retains_ownership(entry, monkeypatch, capsys) -> None:
    module, tmp_path, folder_root = entry
    FakeStore.fail_stop_indexes = {0}
    FakeStore.write_health_by_index = {
        0: {"armed": True, "frozen": False, "active_orders": 0}
    }
    _prepare(monkeypatch, module, folder_root, [PAIR])

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _summary(capsys)
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


def test_wait_ready_and_stop_failure_blocks_without_retry(entry, monkeypatch, capsys) -> None:
    module, tmp_path, folder_root = entry
    FakeStore.fail_wait_ready_indexes = {0}
    FakeStore.fail_stop_indexes = {0}
    second_pair = {**PAIR, "index": 1, "md_front": "m://fake:3", "td_front": "t://fake:4"}
    _prepare(monkeypatch, module, folder_root, [PAIR, second_pair])

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _summary(capsys)
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


def test_failed_first_front_cleanup_error_stops_candidate_retry(entry, monkeypatch, capsys) -> None:
    module, tmp_path, folder_root = entry
    FakeStore.fail_query_indexes = {0}
    FakeStore.fail_stop_indexes = {0}
    second_pair = {**PAIR, "index": 1, "md_front": "m://fake:3", "td_front": "t://fake:4"}
    _prepare(monkeypatch, module, folder_root, [PAIR, second_pair])

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _summary(capsys)
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
def test_unconfirmed_front_close_health_blocks_and_prevents_retry(
    entry, monkeypatch, capsys, variant: str
) -> None:
    module, tmp_path, folder_root = entry
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
    second_pair = {**PAIR, "index": 1, "md_front": "m://fake:3", "td_front": "t://fake:4"}
    _prepare(monkeypatch, module, folder_root, [PAIR, second_pair])

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _summary(capsys)
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


def test_observe_blocks_when_no_pair_observable(entry, monkeypatch, capsys) -> None:
    module, tmp_path, folder_root = entry
    _prepare(monkeypatch, module, folder_root, [])

    code = module.run_live_observe(_args(tmp_path, module))
    assert code != 0
    summary = _summary(capsys)
    assert summary["status"] == "BLOCKED", summary
    assert summary["reason"] == "no_observable_front_pair", summary
    assert FakeStore.instances == [], "a session was opened with no configured pair"


def test_live_tier_routes_by_write_grant_not_by_refusal(entry, monkeypatch) -> None:
    """Without a grant the live tier observes; with one it runs the drill."""

    module, tmp_path, folder_root = entry
    seen: list[str] = []
    monkeypatch.setattr(module, "run_live", lambda args: seen.append("drill") or 0)
    monkeypatch.setattr(module, "run_live_observe", lambda args: seen.append("observe") or 0)
    monkeypatch.setattr(module, "_load_config", lambda: (_config([PAIR]), Path("config.yaml")))

    module.main(["--live"])
    assert seen == ["observe"], seen
    seen.clear()
    module.main(["--live", "--allow-write"])
    assert seen == ["drill"], seen
    seen.clear()
    monkeypatch.setattr(module, "_load_config", lambda: (_config([PAIR]), Path("config.yaml")))
    assert module.main([]) != 0 or seen == [], seen
    # An absent declaration with no flag stays dry, so neither handler runs.
    assert seen == [], seen


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
def test_write_health_contract_blocks_unconfirmed_facts(
    entry, monkeypatch, capsys, health: object, expected: dict[str, str]
) -> None:
    module, tmp_path, folder_root = entry
    FakeStore.write_health_by_index = {0: health}
    _prepare(monkeypatch, module, folder_root, [PAIR])

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _summary(capsys)
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


def test_write_health_method_exception_is_finite_and_still_closes(
    entry, monkeypatch, capsys
) -> None:
    module, tmp_path, folder_root = entry
    FakeStore.fail_write_health_indexes = {0}
    _prepare(monkeypatch, module, folder_root, [PAIR])

    code = module.run_live_observe(_args(tmp_path, module))
    summary = _summary(capsys)
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


def test_optional_zero_write_health_counters_are_accepted(
    entry, monkeypatch, capsys
) -> None:
    module, tmp_path, folder_root = entry
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
    _prepare(monkeypatch, module, folder_root, [PAIR])

    assert module.run_live_observe(_args(tmp_path, module)) == 0
    summary = _summary(capsys)
    assert summary["status"] == "LIVE_OBSERVE_PASS", summary
    assert summary["write_health"] == health, summary
    assert FakeStore.instances[0].stop_calls == 1
