"""R5b-2 observation-lifecycle coverage for the SA SimNow entry (013_3).

013_3 resolves its instrument and exchange through ``live_contract`` and its
``_load_config`` returns a sanitized view alongside the full config, so it needs
its own fixture; the asserted contract is the same one the pair family holds:
login, read, close, and no write method reachable.
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
FOLDER = ROOT / "examples" / "unified" / "013_3_sa_midfreq_simnow"


class WriteTouched(AssertionError):
    """Raised when the observation path reaches any write-capable method."""


class FakeStore:
    instances: list[FakeStore] = []

    def __init__(self, **kwargs: object) -> None:
        self.init_config = dict(kwargs.get("config") or {})
        self.lifecycle: list[str] = []
        self.queries: list[str] = []
        FakeStore.instances.append(self)

    def start(self) -> None:
        self.lifecycle.append("start")

    def stop(self, timeout: float = 0.0) -> None:
        self.lifecycle.append("stop")

    def registered_sim_wait_ready(self, timeout: float = 0.0) -> bool:
        self.lifecycle.append("wait_ready")
        return True

    def registered_sim_login_facts(self) -> dict[str, object]:
        return {"read_only_ready": True, "trading_day": "20261009", "connection_generation": 1}

    def registered_sim_query(self, kind: str, timeout: float = 0.0, **filters: object) -> dict[str, object]:
        self.queries.append(kind)
        if kind == "instruments_result":
            return {"rows": [{"InstrumentID": filters.get("instrument_id"), "PriceTick": 1.0, "VolumeMultiple": 20.0}]}
        rows = {"account_result": 1, "positions_result": 2, "orders_result": 1, "trades_result": 0}
        return {"rows": [{} for _ in range(rows.get(kind, 0))]}

    def registered_sim_write_health(self) -> dict[str, int]:
        return {"arm_calls": 0, "submit_calls": 0, "cancel_calls": 0, "native_send_calls": 0}

    def __getattr__(self, name: str):
        if any(word in name for word in ("arm", "submit", "cancel", "send", "freeze", "disarm")):
            raise WriteTouched(f"observation path touched write method {name!r}")
        raise AttributeError(name)


CONFIG = {
    "credentials": {
        "broker_id_env": "FAKE_BROKER",
        "user_id_env": "FAKE_USER",
        "password_env": "FAKE_PASSWORD",
        "app_id_env": "FAKE_APP",
        "auth_code_env": "FAKE_AUTH",
    },
    "live_contract": {"instrument": "SA2601", "exchange": "CZCE"},
    "fronts": {"pairs": [{"index": 0, "md_front": "m://fake:1", "td_front": "t://fake:2"}]},
    "timeouts": {"login_seconds": 1.0, "query_seconds": 1.0, "stop_seconds": 1.0},
    "live_market_data": {"allow_zero_login_response": False},
}


@pytest.fixture
def entry(monkeypatch, tmp_path):
    FakeStore.instances = []
    fake = types.ModuleType("simnow_direct")
    fake.SimNowDirectError = type("SimNowDirectError", (RuntimeError,), {})
    fake.RegisteredSimStore = FakeStore
    fake.canonical_sha256 = lambda value: "0" * 64
    fake.strategy_identity_sha256 = lambda path, scope: "1" * 64
    fake.select_front_pair = lambda configured, env, **kwargs: {
        "ordered_pairs": [
            dict(pair, kind=pair.get("kind") or "standard", whitelisted=None, score_ms=1.5) for pair in configured
        ]
    }
    blocker = types.ModuleType("backtrader.brokers.btapibroker")
    blocker.BtApiBroker = lambda *a, **k: (_ for _ in ()).throw(WriteTouched("BtApiBroker constructed"))
    monkeypatch.setitem(sys.modules, "simnow_direct", fake)
    monkeypatch.setitem(sys.modules, "backtrader.brokers.btapibroker", blocker)
    monkeypatch.syspath_prepend(str(FOLDER))
    spec = importlib.util.spec_from_file_location("entry_run_013_3", FOLDER / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(
        module,
        "_load_config",
        lambda: (dict(CONFIG), {key: value for key, value in CONFIG.items() if key != "credentials"}, FOLDER / "config.yaml"),
    )
    monkeypatch.setattr(module, "_new_section_errors", lambda config: [])
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
    sys.modules.pop("entry_run_013_3", None)


def _args(tmp_path: Path, module) -> SimpleNamespace:
    decision = module.entry_tier.decide({"entry": {"tier": "live"}}, None)
    return SimpleNamespace(
        evidence_dir=str(tmp_path / "evidence"), run_seconds=None, drill=False, allow_write=False, tier_decision=decision
    )


def _payload(capsys) -> dict[str, object]:
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line.strip()]
    assert lines, "the observation channel printed nothing"
    return json.loads(lines[-1])


def test_sa_observe_lifecycle_reads_and_never_writes(entry, capsys) -> None:
    module, tmp_path = entry
    assert module.run_live_observe(_args(tmp_path, module)) == 0
    summary = _payload(capsys)

    assert summary["status"] == "LIVE_OBSERVE_PASS", summary
    assert summary["channel"] == "observe" and summary["mode"] == "live", summary
    assert summary["entry_tier"]["effective_tier"] == "live", summary
    assert summary["write_grant_result"] == "not_required_observation_only", summary
    assert summary["instrument"] == "SA2601" and summary["exchange"] == "CZCE", summary
    assert summary["write_health"] == {"arm_calls": 0, "submit_calls": 0, "cancel_calls": 0, "native_send_calls": 0}
    assert summary["readings"]["instrument_rows"] == 1, summary

    store = FakeStore.instances[0]
    assert store.lifecycle == ["start", "wait_ready", "stop"], store.lifecycle
    assert store.queries == [
        "positions_result",
        "orders_result",
        "instruments_result",
        "account_result",
        "trades_result",
    ], store.queries
    assert (tmp_path / "evidence" / "run.json").is_file()


def test_sa_observe_blocks_without_a_session_when_no_pair(entry, monkeypatch, capsys) -> None:
    module, tmp_path = entry
    monkeypatch.setattr(module, "_load_config", lambda: ({**CONFIG, "fronts": {"pairs": []}}, {}, FOLDER / "config.yaml"))
    assert module.run_live_observe(_args(tmp_path, module)) != 0
    summary = _payload(capsys)
    assert summary["reason"] == "no_observable_front_pair", summary
    assert FakeStore.instances == [], "a session was opened with no configured pair"


def test_sa_live_routes_by_write_grant(entry, monkeypatch) -> None:
    module, _tmp_path = entry
    seen: list[str] = []
    monkeypatch.setattr(module, "run_live", lambda args: seen.append("drill") or 0)
    monkeypatch.setattr(module, "run_live_observe", lambda args: seen.append("observe") or 0)
    module.main(["--live"])
    assert seen == ["observe"], seen
    seen.clear()
    module.main(["--live", "--allow-write"])
    assert seen == ["drill"], seen
