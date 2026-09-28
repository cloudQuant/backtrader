"""Offline-only tests for the unregistered SimNow native readiness adapter."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import backtrader_runtime.config as runtime_config
import backtrader_runtime.ctp_native_shutdown as ctp_native_shutdown_module
from backtrader_runtime.ctp_simnow_managed_operator import (
    CtpSimNowManagedExecutionPolicy,
    select_ctp_simnow_managed_scope,
)
from backtrader_runtime.ctp_simnow_native_readiness import (
    CtpSimNowNativeReadinessError,
    CtpSimNowNativeStartupConfig,
    start_ctp_simnow_native_readiness,
    stop_ctp_simnow_native_clients,
)
from backtrader_runtime.registry import RegisteredRuntime, RuntimeRegistry, validate_runtime_config

RUNTIME_ID = "iteration41.ctp.simnow.native-readiness-test"
STRATEGY_ID = "iteration41.ctp.simnow.native_readiness_test"
MD_FRONT = "tcp://127.0.0.1:11001"
TD_FRONT = "tcp://127.0.0.1:12001"
BROKER_ID = "9999"
USER_ID = "offline-native-test"
TRADING_DAY = "20260924"


@pytest.fixture(autouse=True)
def _allow_synthetic_private_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)
    monkeypatch.setattr(
        ctp_native_shutdown_module,
        "_native_stop_receipt_type",
        lambda: _FakeNativeStopReceipt,
    )


@dataclass(frozen=True)
class _FakeNativeStopReceipt:
    connection_generation: int
    join_required: bool = False
    join_completed: bool = True
    native_released: bool = True
    thread_alive: bool = False
    timed_out: bool = False

    @property
    def complete(self) -> bool:
        return (
            self.native_released
            and (not self.join_required or self.join_completed)
            and self.thread_alive is False
            and self.timed_out is False
        )


def _selection(tmp_path: Path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "config.yaml").write_text(
        "\n".join(
            [
                "config_schema_version: 4",
                "strategy:",
                "  id: " + STRATEGY_ID,
                "runtime:",
                "  mode: simulation",
                "  preset: sandbox",
                "parameters: {}",
                "secrets_ref: config_yaml",
                "ctp:",
                "  md_front: " + MD_FRONT,
                "  td_front: " + TD_FRONT,
                "  instrument_id: rb2701",
                "  exchange_id: SHFE",
                "  hedge_flag: '1'",
                "  broker_id: '" + BROKER_ID + "'",
                "  user_id: " + USER_ID,
                "  password: offline-test-password",
                "  app_id: offline-test-app",
                "  auth_code: offline-test-auth",
                "",
            ]
        ),
        encoding="utf-8",
    )
    registered = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id=RUNTIME_ID,
        strategy_id=STRATEGY_ID,
        allowed_presets=("sandbox",),
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=("execution", "risk", "monitor"),
        sandbox_write_policy="receipt_required",
        approval_receipt_digest="a" * 64,
    )
    registry = RuntimeRegistry((registered,), registry_id="test.simnow.native-readiness")
    policy = CtpSimNowManagedExecutionPolicy(
        runtime_registration=registered,
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=2,
        max_gross_position=2,
        min_price=Decimal("100"),
        max_price=Decimal("200"),
        price_tick=Decimal("1"),
        approval_key_id="offline-native-test-key",
        approval_ttl_seconds=20,
    )
    effective = validate_runtime_config(runtime_dir, registry)

    def connector(host: str, port: int, _timeout: float):
        return SimpleNamespace(
            latency_ms=10.0,
            dns_resolution_ms=0.0,
            tcp_connect_ms=10.0,
            close=lambda: None,
        )

    selection = select_ctp_simnow_managed_scope(
        effective,
        registry,
        policy,
        connector=connector,
        repeated_samples=1,
    )
    assert selection.execution_registration.md_front == MD_FRONT
    assert selection.execution_registration.td_front == TD_FRONT
    return selection


def _account_short() -> str:
    return hashlib.sha256(f"{BROKER_ID}:{USER_ID}".encode()).hexdigest()[:16]


class _Trader:
    def __init__(self, *, day: str = TRADING_DAY, generation: int = 1) -> None:
        self.day = day
        self.ready_generation = generation
        self.generation = 0
        self.started = False
        self.stop_calls = 0
        self.start_calls = 0
        self.request_counts = {"order_insert": 0, "order_action": 0}

    def start(self, block: bool = False) -> None:
        assert block is False
        self.start_calls += 1
        self.started = True
        self.generation = self.ready_generation

    def stop(self) -> None:
        self.stop_calls += 1

    @property
    def connection_generation(self) -> int:
        return self.generation

    def stop_and_wait(self, *, timeout: float) -> _FakeNativeStopReceipt:
        assert timeout > 0
        self.stop_calls += 1
        return _FakeNativeStopReceipt(self.connection_generation)

    def get_session_state(self) -> dict[str, Any]:
        return {
            "account_fingerprint": _account_short(),
            "connected": self.started,
            "read_only_ready": self.started,
            "trading_ready": False,
            "auto_settlement_confirm": False,
            "connection_generation": self.generation,
            "trading_day": self.day,
            "last_error": {},
        }

    def get_front_binding_state(self) -> dict[str, Any]:
        return {
            "configured_front": TD_FRONT,
            "registered_front": TD_FRONT,
            "connection_confirmed_front": TD_FRONT,
            "connected": self.started,
            "native_api_current": self.started,
            "bound_identity_current": True,
            "connection_generation": self.generation,
        }

    def get_query_session_scope(self) -> Any:
        return SimpleNamespace(
            read_only_ready=self.started,
            connection_generation=self.generation,
            trading_day=self.day,
            broker_id=BROKER_ID,
            investor_id=USER_ID,
            account_fingerprint=_account_short(),
        )


class _Md:
    def __init__(self, day: str = TRADING_DAY, *, first_generation: int = 1) -> None:
        self.front = MD_FRONT
        self.broker_id = BROKER_ID
        self.user_id = USER_ID
        self.day = day
        self.first_generation = first_generation
        self.generation = 0
        self.identity = None
        self.is_ready = False
        self.auto_resubscribe_on_login = True
        self.on_login = None
        self.on_error = None
        self.on_disconnect = None
        self.on_subscribe = None
        self.on_tick = None
        self.start_calls = 0
        self.subscribe_calls: list[list[str]] = []
        self.stop_calls = 0
        self.emit_tick = True
        self.generation_change_on_subscribe = False

    @property
    def connection_generation(self) -> int:
        return self.generation

    @property
    def active_md_identity(self) -> Any:
        return self.identity

    def start(self, block: bool = False) -> None:
        assert block is False
        self.start_calls += 1
        self.generation = self.first_generation
        self.is_ready = True
        self.identity = SimpleNamespace(
            front=MD_FRONT,
            broker_id=BROKER_ID,
            user_id=USER_ID,
            connection_generation=self.generation,
            trading_day=self.day,
            authenticated=True,
        )
        self.on_login(SimpleNamespace())

    def subscribe(self, instruments: list[str]) -> None:
        self.subscribe_calls.append(list(instruments))
        if self.generation_change_on_subscribe:
            self.generation += 1
            self.identity = SimpleNamespace(
                front=MD_FRONT,
                broker_id=BROKER_ID,
                user_id=USER_ID,
                connection_generation=self.generation,
                trading_day=self.day,
                authenticated=True,
            )
        self.on_subscribe(SimpleNamespace(InstrumentID="rb2701"), SimpleNamespace(ErrorID=0))
        if self.emit_tick:
            self.on_tick(
                SimpleNamespace(
                    InstrumentID="rb2701",
                    ExchangeID="SHFE",
                    LastPrice=100.0,
                    Volume=1,
                )
            )

    def stop(self) -> None:
        self.stop_calls += 1

    def stop_and_wait(self, *, timeout: float) -> _FakeNativeStopReceipt:
        assert timeout > 0
        self.stop_calls += 1
        return _FakeNativeStopReceipt(self.connection_generation)


def _config() -> CtpSimNowNativeStartupConfig:
    return CtpSimNowNativeStartupConfig(
        td_front=TD_FRONT,
        md_front=MD_FRONT,
        broker_id=BROKER_ID,
        user_id=USER_ID,
        password="offline-test-password",
    )


def _run(selection, trader, md, *, timeout: float = 1.0, market_client_sink=None):
    kept = []
    evidence = start_ctp_simnow_native_readiness(
        trader,
        selection,
        _config(),
        md_client_factory=lambda *_args: md,
        market_client_sink=market_client_sink if market_client_sink is not None else kept.append,
        timeout_seconds=timeout,
    )
    return evidence, kept


def test_public_one_shot_startup_requires_td_md_ack_and_first_matching_tick(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path)
    trader = _Trader()
    md = _Md()

    evidence, kept = _run(selection, trader, md)

    assert type(evidence).__name__ == "CtpSimNowNativeReadiness"
    assert evidence.matches(selection)
    assert evidence.td_ready is True and evidence.md_ready is True
    assert evidence.td_trading_ready is False
    assert evidence.order_submission_authorized is False
    assert kept == [md]
    assert trader.start_calls == md.start_calls == 1
    assert md.subscribe_calls == [["rb2701"]]
    assert trader.stop_calls == md.stop_calls == 0
    assert trader.request_counts == {"order_insert": 0, "order_action": 0}


def test_timeout_without_first_matching_tick_stops_both_clients(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    trader = _Trader()
    md = _Md()
    md.emit_tick = False

    with pytest.raises(CtpSimNowNativeReadinessError) as rejected:
        _run(selection, trader, md, timeout=0.05)

    assert rejected.value.reason == "managed_simnow_native_readiness_timeout"
    assert rejected.value.close_state == "closed"
    assert trader.stop_calls == md.stop_calls == 1


def test_managed_failure_cleanup_hook_owns_each_stop_once(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    trader = _Trader()
    md = _Md()
    md.emit_tick = False
    cleanup_calls = []

    def managed_cleanup():
        cleanup_calls.append("close")
        assert md.stop_calls == trader.stop_calls == 0
        md.stop()
        trader.stop()

    with pytest.raises(CtpSimNowNativeReadinessError) as rejected:
        start_ctp_simnow_native_readiness(
            trader,
            selection,
            _config(),
            md_client_factory=lambda *_args: md,
            market_client_sink=lambda _client: None,
            failure_cleanup=managed_cleanup,
            timeout_seconds=0.05,
        )

    assert rejected.value.close_state == "closed"
    assert cleanup_calls == ["close"]
    assert md.stop_calls == trader.stop_calls == 1


def test_generation_change_during_subscription_fails_closed(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    trader = _Trader()
    md = _Md()
    md.generation_change_on_subscribe = True

    with pytest.raises(CtpSimNowNativeReadinessError) as rejected:
        _run(selection, trader, md)

    assert rejected.value.reason in {
        "managed_simnow_md_generation_changed",
        "managed_simnow_md_identity_or_generation_mismatch",
    }
    assert trader.stop_calls == md.stop_calls == 1


def test_reconnect_before_first_md_login_is_not_accepted(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    trader = _Trader()
    md = _Md(first_generation=2)

    with pytest.raises(CtpSimNowNativeReadinessError) as rejected:
        _run(selection, trader, md)

    assert rejected.value.reason == "managed_simnow_md_identity_or_generation_mismatch"
    assert trader.stop_calls == md.stop_calls == 1


def test_td_md_trading_day_mismatch_fails_closed(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    trader = _Trader(day="20260924")
    md = _Md(day="20260925")

    with pytest.raises(CtpSimNowNativeReadinessError) as rejected:
        _run(selection, trader, md)

    assert rejected.value.reason in {
        "managed_simnow_trading_day_mismatch",
        "managed_simnow_md_generation_or_day_changed",
    }
    assert trader.stop_calls == md.stop_calls == 1


def test_md_factory_failure_stops_already_constructed_trader(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    trader = _Trader()

    with pytest.raises(CtpSimNowNativeReadinessError) as rejected:
        start_ctp_simnow_native_readiness(
            trader,
            selection,
            _config(),
            md_client_factory=lambda *_args: (_ for _ in ()).throw(RuntimeError("redact me")),
            market_client_sink=lambda _client: None,
        )

    assert rejected.value.reason == "managed_simnow_md_client_construction_failed"
    assert trader.stop_calls == 1
    assert "redact me" not in str(rejected.value)


def test_rejected_late_market_sink_prevents_md_start(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    trader = _Trader()
    md = _Md()

    def closed_sink(_client: Any) -> None:
        raise CtpSimNowNativeReadinessError("managed_simnow_md_client_registration_closed")

    with pytest.raises(CtpSimNowNativeReadinessError):
        _run(selection, trader, md, market_client_sink=closed_sink)

    assert md.start_calls == 0
    assert trader.start_calls == 0
    assert md.stop_calls == trader.stop_calls == 1


def test_explicit_shutdown_attempts_both_clients() -> None:
    events: list[str] = []

    class BadStop:
        def __init__(self, name: str) -> None:
            self.name = name
            self.calls = 0
            self.connection_generation = 1

        def stop_and_wait(self, *, timeout: float) -> _FakeNativeStopReceipt:
            assert timeout > 0
            self.calls += 1
            events.append(self.name)
            return _FakeNativeStopReceipt(
                1,
                join_required=True,
                join_completed=False,
                native_released=False,
                thread_alive=True,
                timed_out=True,
            )

    trader = BadStop("td")
    md = BadStop("md")
    with pytest.raises(CtpSimNowNativeReadinessError) as rejected:
        stop_ctp_simnow_native_clients(trader, md)
    assert rejected.value.reason == "managed_simnow_native_close_failed"
    assert trader.calls == md.calls == 1
    assert events == ["md", "td"]
