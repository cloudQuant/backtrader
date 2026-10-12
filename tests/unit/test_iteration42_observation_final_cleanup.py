"""014_2 run_live final-cleanup regression through the public handler.

The frozen candidate's public ``run_live`` function is executed directly.  The
Store/front, broker, Cerebro, strategy and feed are deterministic leaves; the
handler's admission, status projection, finalizer, JSON persistence and stdout
remain the candidate implementation.  This is a source/fake regression, not a
provider or account test.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

_REPO = Path(os.environ.get("I42_CLEANUP_REPO_ROOT", str(Path(__file__).resolve().parents[2])))
_CANDIDATE = Path(os.environ.get("I42_CLEANUP_CANDIDATE_ROOT", str(_REPO)))
_ENTRY = "014_2_ctp_options_midfreq"
_RELATIVE_ENTRY = Path("examples") / "unified" / _ENTRY
_SECRET = "synthetic-secret-must-not-escape-0142"


def _healthy_store_health() -> dict[str, object]:
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


class _FakeStore:
    instances: ClassVar[list[_FakeStore]] = []
    mode = "healthy"
    run_file: Path | None = None

    def __init__(self, **kwargs: object) -> None:
        self.config = dict(kwargs.get("config") or {})
        self.index = len(type(self).instances)
        self.started = False
        self.stop_calls = 0
        self.queries: list[str] = []
        self.feed_requests: list[dict[str, object]] = []
        self.provenance: dict[str, object] = {}
        type(self).instances.append(self)

    def start(self) -> None:
        self.started = True

    def registered_sim_wait_ready(self, timeout: float = 0.0) -> bool:
        return True

    def registered_sim_login_facts(self) -> dict[str, object]:
        return {
            "read_only_ready": True,
            "trading_ready": True,
            "trading_day": "20261012",
            "connection_generation": 9,
        }

    def registered_sim_query(self, kind: str, timeout: float = 0.0, **filters: object):
        self.queries.append(kind)
        if type(self).mode == "failed_front_uncertain" and kind == "account_result":
            raise RuntimeError(f"bounded fake query detail: {_SECRET}")
        if kind in {"account_result", "positions_result"}:
            return {"rows": []}
        if kind == "instruments_result":
            instrument = str(filters.get("instrument_id") or "")
            expected = next(
                (
                    row
                    for symbol, row in _LIVE_CONFIG["instrument_metadata"].items()
                    if symbol.split(".", 1)[-1] == instrument
                ),
                None,
            )
            if expected is None:
                raise AssertionError("synthetic instrument query did not match public config")
            return {
                "rows": [
                    {
                        "InstrumentID": instrument,
                        "PriceTick": expected["price_tick"],
                        "VolumeMultiple": expected["volume_multiple"],
                    }
                ]
            }
        raise AssertionError(f"unexpected synthetic query kind: {kind}")

    def configure_live_tick_provenance(self, provenance: object) -> None:
        self.provenance = dict(provenance or {})

    def getdata(self, **kwargs: object) -> object:
        self.feed_requests.append(dict(kwargs))
        return SimpleNamespace(dataname=kwargs.get("dataname"))

    def stop(self, timeout: float = 0.0) -> dict[str, object]:
        self.stop_calls += 1
        if type(self).run_file is not None and type(self).run_file.exists():
            before_final_close = json.loads(type(self).run_file.read_text(encoding="utf-8"))
            assert before_final_close.get("status") != "OBSERVATION_PASS", (
                "the handler persisted success before Store.stop returned"
            )
        if type(self).mode in {"stop_exception", "failed_front_uncertain"}:
            raise RuntimeError(f"synthetic stop detail: {_SECRET}")
        health = _healthy_store_health()
        if type(self).mode == "worker_pending":
            health["worker_alive"] = True
        elif type(self).mode == "queue_pending":
            health["queue_depth"] = 1
        elif type(self).mode == "shutdown_incomplete":
            health["shutdown_state"] = "INCOMPLETE"
        return health


class _BusinessResultStrategy:
    """A fixed, explicit one-minute business result for handler-only coverage."""

    def __init__(self, **kwargs: object) -> None:
        self.config = kwargs.get("config")

    def build_report(self) -> dict[str, object]:
        return {
            "status": "OBSERVATION_SOURCE_FAKE",
            "ordinary_decision_count": 0,
            "orders_submitted": 0,
            "minute_events": [
                {
                    "kind": "WARMUP",
                    "origin": "next",
                    "history_bars": 1,
                    "synthetic_source": "bounded-handler-regression",
                }
            ],
            "feed_evidence": {"required": True, "clock_mode": "live", "fault": None},
        }


class _FakeCerebro:
    def __init__(self, **kwargs: object) -> None:
        self._event_stop = SimpleNamespace(is_set=lambda: True)
        self.runstrats: list[list[object]] = []
        self._strategy_cls = None
        self._strategy_kwargs: dict[str, object] = {}
        self.feeds: list[tuple[object, str | None]] = []

    def setbroker(self, broker: object) -> None:
        self.broker = broker

    def adddata(self, feed: object, name: str | None = None) -> None:
        self.feeds.append((feed, name))

    def addstrategy(self, strategy_cls: object, **kwargs: object) -> None:
        self._strategy_cls = strategy_cls
        self._strategy_kwargs = dict(kwargs)

    def run(self) -> None:
        assert self._strategy_cls is _BusinessResultStrategy
        self.runstrats = [[self._strategy_cls(**self._strategy_kwargs)]]

    def runstop(self) -> None:
        return None


class _FakeClockMapping:
    mapping_id = "source-fake-0142-live-map"
    synthetic = False


class _FakeLiveClock:
    def __init__(self, *, generation: int, rules_hash: str, source: str, validity_seconds: float) -> None:
        self.generation = generation
        self.domain = "source-fake-0142-clock-domain"
        self.mapping = _FakeClockMapping()
        self.mapping.rules_hash = rules_hash

    def provenance(self, *, session_segment: str) -> dict[str, object]:
        return {
            "clock_domain_id": self.domain,
            "rules_hash": self.mapping.rules_hash,
            "session_segment": session_segment,
            "generation": self.generation,
            "source": "source-fake-clock",
        }


class _NoThread:
    def __init__(self, **kwargs: object) -> None:
        self.name = kwargs.get("name")

    def start(self) -> None:
        return None

    def join(self, timeout: float | None = None) -> None:
        return None


_BASE_CONFIG = {
    "mode": "replay",
    "candidate": {
        "candidate_id": "source-fake-0142-handler",
        "exchange": "CZCE",
        "rules_hash": "source-fake-rules-hash",
        "option_style": "European",
        "strike": 1000,
        "multiplier": 10,
        "discount_factor": 1,
        "contracts": {
            "future": "CZCE.FG2601",
            "call": "CZCE.FG2601C1000",
            "put": "CZCE.FG2601P1000",
        },
        "quantities": {"future": 1, "call": 1, "put": 1},
        "price_ticks": {"future": 1, "call": 1, "put": 1},
    },
    "budget": {
        "capital_limit_cny": 10000,
        "working_limit_cny": 8000,
        "recovery_reserve_cny": 2000,
        "path_requirement_cny": 5000,
    },
    "signal": {
        "bar_minutes": 1,
        "history_bars": 60,
        "residual_floor_cny": 30,
        "z_entry": 2.5,
        "minimum_net_edge_cny": 20,
        "cost_bound_cny": 5,
    },
    "features": {
        "short_window_seconds": 5,
        "long_window_seconds": 60,
        "max_segment_seconds": 2,
        "max_cross_leg_skew_ms": 500,
        "minimum_new_snapshots": 3,
        "persistence_ratio": 0.8,
        "max_adverse_pressure": 0.5,
    },
    "replay": {"initial_cash_cny": 10000, "scenario": "no_edge"},
}

_CREDENTIAL_NAMES = {
    "broker_id_env": "FAKE_CTP_BROKER",
    "user_id_env": "FAKE_CTP_USER",
    "password_env": "FAKE_CTP_PASSWORD",
    "app_id_env": "FAKE_CTP_APP_ID",
    "auth_code_env": "FAKE_CTP_AUTH_CODE",
}
_ENV = {
    "FAKE_CTP_BROKER": "source-fake-broker",
    "FAKE_CTP_USER": "source-fake-user",
    "FAKE_CTP_PASSWORD": "source-fake-password",
    "FAKE_CTP_APP_ID": "source-fake-app",
    "FAKE_CTP_AUTH_CODE": "source-fake-auth",
}
_SYMBOLS = _BASE_CONFIG["candidate"]["contracts"]
_LIVE_CONFIG = {
    "schema_version": 1,
    "venue": "simnow",
    "credentials": _CREDENTIAL_NAMES,
    "fronts": {
        "pairs": [
            {"index": 0, "kind": "standard", "td_env": "FAKE_TD_0", "md_env": "FAKE_MD_0", "td_front": "td://synthetic/0", "md_front": "md://synthetic/0"},
            {"index": 1, "kind": "standard", "td_env": "FAKE_TD_1", "md_env": "FAKE_MD_1", "td_front": "td://synthetic/1", "md_front": "md://synthetic/1"},
        ]
    },
    "timeouts": {
        "run_seconds": 0.01,
        "login_seconds": 0.01,
        "query_seconds": 0.01,
        "drain_seconds": 0.01,
        "stop_seconds": 0.01,
    },
    "live_market_data": {"allow_zero_login_response": False},
    "live_candidate": {
        "exchange": "CZCE",
        "contracts": dict(_SYMBOLS),
        "strike": 1000,
        "multiplier": 10,
        "discount_factor": 1,
        "option_style": "European",
        "quantities": {"future": 1, "call": 1, "put": 1},
        "price_ticks": {"future": 1, "call": 1, "put": 1},
    },
    "instrument_metadata": {
        symbol: {"price_tick": 1, "volume_multiple": 10}
        for symbol in _SYMBOLS.values()
    },
    "policy": {"allow_write": False},
    "observation": {"quote_limit": 240, "max_pending_decisions": 8},
}


def _load_real_validator(repo: Path):
    source_dir = repo / _RELATIVE_ENTRY
    sys.path.insert(0, str(source_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "i42_0142_public_strategy_validator", source_dir / "ctp_options_midfreq_strategy.py"
        )
        assert spec is not None and spec.loader is not None
        strategy = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = strategy
        spec.loader.exec_module(strategy)
        return strategy
    finally:
        sys.path.remove(str(source_dir))


def _install_handler_leaves(monkeypatch, candidate_file: Path, strategy_validator):
    _FakeStore.instances = []
    _FakeStore.mode = "healthy"
    _FakeStore.run_file = None
    spec = importlib.util.spec_from_file_location("i42_0142_candidate_run", candidate_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    simnow = types.ModuleType("simnow_direct")
    simnow.SimNowDirectError = type("SimNowDirectError", (RuntimeError,), {})
    simnow.RegisteredSimStore = _FakeStore
    simnow.canonical_sha256 = lambda value: hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    def select_front_pair(configured, env, **kwargs):
        ordered = []
        for pair in configured:
            ordered.append(
                {
                    **dict(pair),
                    "kind": pair.get("kind", "standard"),
                    "whitelisted": True,
                    "score_ms": 1.0 + int(pair["index"]),
                }
            )
        return {"ordered_pairs": ordered, "receipt": {"source": "source-fake-front-selector", "count": len(ordered)}}

    simnow.select_front_pair = select_front_pair
    monkeypatch.setitem(sys.modules, "simnow_direct", simnow)

    legacy = types.ModuleType("legacy_runner")
    validated_config = strategy_validator.validate_config(_BASE_CONFIG)
    legacy.load_config = lambda: validated_config
    monkeypatch.setitem(sys.modules, "legacy_runner", legacy)

    fake_backtrader = types.ModuleType("backtrader")
    fake_backtrader.__path__ = []
    fake_backtrader.Cerebro = _FakeCerebro
    fake_backtrader.TimeFrame = SimpleNamespace(Minutes=1)
    brokers_package = types.ModuleType("backtrader.brokers")
    brokers_package.__path__ = []
    broker_module = types.ModuleType("backtrader.brokers.btapibroker")
    broker_module.BtApiBroker = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "backtrader", fake_backtrader)
    monkeypatch.setitem(sys.modules, "backtrader.brokers", brokers_package)
    monkeypatch.setitem(sys.modules, "backtrader.brokers.btapibroker", broker_module)

    strategy_module = types.ModuleType("ctp_options_midfreq_strategy")
    strategy_module.CTPOptionsMidFrequencyStrategy = _BusinessResultStrategy
    monkeypatch.setitem(sys.modules, "ctp_options_midfreq_strategy", strategy_module)

    module.sys = SimpleNamespace(version_info=(3, 11, 5))
    module._load_raw_config = lambda: {module.LIVE_ADAPTER_KEY: _LIVE_CONFIG}
    module._load_env = lambda: dict(_ENV)
    module._ensure_dev_sdk_path = lambda strict=False: None
    module._LiveClock = _FakeLiveClock
    monkeypatch.setattr(module.threading, "Thread", _NoThread)
    monkeypatch.setattr(module.signal, "getsignal", lambda *_args: None)
    monkeypatch.setattr(module.signal, "signal", lambda *_args: None)
    return module


def _args(module, evidence_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        allow_write=False,
        run_seconds=0.01,
        evidence_dir=str(evidence_dir),
        tier_decision=SimpleNamespace(
            as_evidence=lambda: {"effective_tier": "live", "reason": "synthetic-live-request"}
        ),
    )


def _run_summary(capsys) -> dict[str, object]:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1, lines
    return json.loads(lines[0])


@pytest.fixture
def handler(monkeypatch):
    repo = _REPO.resolve()
    candidate_file = (_CANDIDATE / _RELATIVE_ENTRY / "run.py").resolve()
    monkeypatch.syspath_prepend(str((repo / _RELATIVE_ENTRY).resolve()))
    strategy_validator = _load_real_validator(repo)
    value = _install_handler_leaves(monkeypatch, candidate_file, strategy_validator)
    yield value
    sys.modules.pop("i42_0142_candidate_run", None)
    sys.modules.pop("i42_0142_public_strategy_validator", None)


def _persisted_and_printed(module, evidence_dir: Path, capsys):
    printed = _run_summary(capsys)
    persisted = json.loads((evidence_dir / "run.json").read_text(encoding="utf-8"))
    assert printed == persisted
    return printed


def test_0142_live_handler_projects_business_success_only_after_confirmed_close(
    handler, capsys, tmp_path
):
    module = handler
    evidence_dir = tmp_path / "healthy"
    run_file = evidence_dir / "run.json"
    _FakeStore.run_file = run_file
    exit_code = module.run_live(_args(module, evidence_dir))
    summary = _persisted_and_printed(module, evidence_dir, capsys)

    assert exit_code == 0, summary
    assert summary["status"] == "OBSERVATION_PASS"
    assert summary["cleanup_status"] == "closed"
    assert summary["observation"]["feature_minutes"] == 1
    assert summary["observation"]["feed_evidence_fault"] is None
    assert len(_FakeStore.instances) == 1
    assert _FakeStore.instances[0].stop_calls == 1
    assert len(_FakeStore.instances[0].feed_requests) == 3
    assert all(call.get("dispatch_bars") is True for call in _FakeStore.instances[0].feed_requests)
    assert module._OBSERVATION_CLEANUP_KEEPALIVE == []


@pytest.mark.parametrize(
    ("close_mode", "expected_failure"),
    [
        ("stop_exception", {"phase": "store_stop", "exception_type": "RuntimeError"}),
        (
            "worker_pending",
            {"phase": "store_stop", "reason": "health_flag_not_false", "field": "worker_alive"},
        ),
        (
            "queue_pending",
            {"phase": "store_stop", "reason": "health_count_not_zero", "field": "queue_depth"},
        ),
        ("shutdown_incomplete", {"phase": "store_stop", "reason": "shutdown_state_not_pass"}),
    ],
)
def test_0142_live_handler_overrides_success_and_retains_uncertain_store(
    handler, capsys, tmp_path, close_mode, expected_failure
):
    module = handler
    evidence_dir = tmp_path / close_mode
    _FakeStore.mode = close_mode
    _FakeStore.run_file = evidence_dir / "run.json"

    exit_code = module.run_live(_args(module, evidence_dir))
    summary = _persisted_and_printed(module, evidence_dir, capsys)

    assert exit_code == 2
    assert summary["status"] == "BLOCKED"
    assert summary["reason"] == "cleanup_uncertain"
    assert summary["cleanup_status"] == "uncertain"
    assert summary["cleanup_prior_outcome"]["status"] == "OBSERVATION_PASS", summary
    assert expected_failure in summary["cleanup_error"]["failures"]
    assert len(_FakeStore.instances) == 1
    store = _FakeStore.instances[0]
    assert store.stop_calls == 1
    assert len(module._OBSERVATION_CLEANUP_KEEPALIVE) == 1
    assert module._OBSERVATION_CLEANUP_KEEPALIVE[0] is store
    serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    persisted_text = (evidence_dir / "run.json").read_text(encoding="utf-8")
    assert _SECRET not in serialized
    assert _SECRET not in persisted_text


def test_0142_uncertain_failed_front_cleanup_stops_once_preserves_attempt_and_never_tries_next(
    handler, capsys, tmp_path
):
    module = handler
    evidence_dir = tmp_path / "failed-front"
    _FakeStore.mode = "failed_front_uncertain"
    _FakeStore.run_file = evidence_dir / "run.json"

    exit_code = module.run_live(_args(module, evidence_dir))
    summary = _persisted_and_printed(module, evidence_dir, capsys)

    assert exit_code == 2
    assert summary["status"] == "BLOCKED"
    assert summary["reason"] == "cleanup_uncertain"
    assert summary["cleanup_status"] == "uncertain"
    assert summary["cleanup_prior_outcome"]["business_error_type"] == "RuntimeError"
    attempts = summary["admission_attempts"]
    assert len(attempts) == 1
    assert attempts[0]["index"] == 0
    assert attempts[0]["error_type"] == "RuntimeError"
    assert attempts[0]["cleanup_status"] == "uncertain"
    assert len(_FakeStore.instances) == 1
    store = _FakeStore.instances[0]
    assert store.queries == ["account_result"]
    assert store.stop_calls == 1
    assert len(module._OBSERVATION_CLEANUP_KEEPALIVE) == 1
    assert module._OBSERVATION_CLEANUP_KEEPALIVE[0] is store
    serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    persisted_text = (evidence_dir / "run.json").read_text(encoding="utf-8")
    assert _SECRET not in serialized
    assert _SECRET not in persisted_text
