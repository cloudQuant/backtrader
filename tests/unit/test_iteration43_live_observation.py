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


class FakeStore:
    """Read-only SimNow session double with an explicit lifecycle log."""

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
        return {
            "read_only_ready": True,
            "trading_ready": False,
            "trading_day": "20261009",
            "connection_generation": 1,
        }

    def registered_sim_query(self, kind: str, timeout: float = 0.0, **filters: object) -> dict[str, object]:
        self.queries.append(kind)
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

    def registered_sim_write_health(self) -> dict[str, int]:
        return {"arm_calls": 0, "submit_calls": 0, "cancel_calls": 0, "native_send_calls": 0}

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
    assert summary["write_health"] == {"arm_calls": 0, "submit_calls": 0, "cancel_calls": 0, "native_send_calls": 0}
    assert summary["readings"]["account_rows"] == 2, summary
    assert summary["readings"]["position_rows"] == 1, summary
    assert summary["readings"]["trade_rows"] == 3, summary
    assert [row["instrument"] for row in summary["readings"]["instruments"]] == ["RB2601", "RB2605"], summary

    store = FakeStore.instances[0]
    assert store.lifecycle == ["start", "wait_ready", "stop"], store.lifecycle
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
