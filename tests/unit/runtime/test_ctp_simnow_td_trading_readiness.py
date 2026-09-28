"""Fake-client tests for the non-authorizing SimNow TD readiness adapter."""

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
from backtrader_runtime.ctp_simnow_managed_runtime import CtpSimNowNativeReadiness
from backtrader_runtime.ctp_simnow_td_trading_readiness import (
    CtpSimNowTdTradingReadinessConfig,
    CtpSimNowTdTradingReadinessError,
    verify_ctp_simnow_td_trading_readiness,
)
from backtrader_runtime.registry import RegisteredRuntime, RuntimeRegistry, validate_runtime_config

RUNTIME_ID = "iteration41.ctp.simnow.td-readiness-test"
STRATEGY_ID = "iteration41.ctp.simnow.td_readiness_test"
MD_FRONT = "tcp://127.0.0.1:11001"
TD_FRONT = "tcp://127.0.0.1:12001"
BROKER_ID = "9999"
USER_ID = "offline-td-readiness-test"
TRADING_DAY = "20260924"
REQUEST_COUNTERS = (
    "authenticate",
    "login",
    "settlement_confirm",
    "order_insert",
    "order_action",
    "query_account",
    "query_positions",
    "query_orders",
    "query_trades",
    "query_instruments",
    "query_margin_rate",
    "query_commission_rate",
    "query_depth_market_data",
    "query_option_trade_cost",
    "query_option_commission_rate",
    "query_settlement_confirmation",
)


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
                "  password: test-only-password",
                "  app_id: test-only-app",
                "  auth_code: test-only-auth",
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
    registry = RuntimeRegistry((registered,), registry_id="test.simnow.td-readiness")
    policy = CtpSimNowManagedExecutionPolicy(
        runtime_registration=registered,
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=2,
        max_gross_position=2,
        min_price=Decimal("100"),
        max_price=Decimal("200"),
        price_tick=Decimal("1"),
        approval_key_id="offline-td-readiness-test-key",
        approval_ttl_seconds=20,
    )
    effective = validate_runtime_config(runtime_dir, registry)

    def connector(_host: str, _port: int, _timeout: float):
        return SimpleNamespace(
            latency_ms=10.0,
            dns_resolution_ms=0.0,
            tcp_connect_ms=10.0,
            close=lambda: None,
        )

    return select_ctp_simnow_managed_scope(
        effective,
        registry,
        policy,
        connector=connector,
        repeated_samples=1,
    )


def _account_short() -> str:
    return hashlib.sha256(f"{BROKER_ID}:{USER_ID}".encode()).hexdigest()[:16]


class _QueryResult:
    request_type = "settlement_confirmation"
    request_id = 73
    connection_generation = 1
    account_fingerprint = _account_short()
    is_last_seen = True
    error_code = 0
    error_message = ""
    timed_out = False
    complete = True
    late_callback_count = 0
    unsupported = False
    submit_code = 0

    def __init__(
        self,
        *,
        broker: str = BROKER_ID,
        investor: str = USER_ID,
        confirm_date: str = TRADING_DAY,
        settlement_id: int = 1,
    ) -> None:
        self.records = (
            {
                "BrokerID": broker,
                "InvestorID": investor,
                "ConfirmDate": confirm_date,
                "SettlementID": settlement_id,
            },
        )


class _Trader:
    """Public-method-only fake that models the SDK query promotion contract."""

    def __init__(self, *, record: _QueryResult | None = None) -> None:
        self.generation = 1
        self.day = TRADING_DAY
        self.record = record or _QueryResult()
        self.stop_calls = 0
        self.verify_calls: list[float] = []
        self.write_method_calls = 0
        self.counts = dict.fromkeys(REQUEST_COUNTERS, 0)
        self.counts["authenticate"] = 1
        self.counts["login"] = 1
        self.state = self._initial_state()

    def _initial_state(self) -> dict[str, Any]:
        return {
            "account_fingerprint": _account_short(),
            "connected": True,
            "auth_state": "authenticated",
            "login_state": "logged_in",
            "settlement_state": "not_requested",
            "read_only_ready": True,
            "trading_ready": False,
            "auto_settlement_confirm": False,
            "connection_generation": self.generation,
            "trading_day": self.day,
            "settlement_connection_generation": None,
            "settlement_account_fingerprint": None,
            "settlement_trading_day": None,
            "settlement_proof_source": "none",
            "settlement_proof_query_request_id": None,
            "settlement_readback_verified": False,
            "execution_gate_armed": False,
            "last_error": {},
        }

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
        return dict(self.state)

    def get_front_binding_state(self) -> dict[str, Any]:
        return {
            "configured_front": TD_FRONT,
            "registered_front": TD_FRONT,
            "connection_confirmed_front": TD_FRONT,
            "connected": True,
            "connection_generation": self.generation,
            "native_api_current": True,
            "bound_identity_current": True,
        }

    def get_query_session_scope(self) -> Any:
        return SimpleNamespace(
            read_only_ready=True,
            connection_generation=self.generation,
            trading_day=self.day,
            broker_id=BROKER_ID,
            investor_id=USER_ID,
            account_fingerprint=_account_short(),
        )

    def get_request_counts(self) -> dict[str, int]:
        return dict(self.counts)

    def verify_settlement_confirmation(self, *, timeout: float):
        self.verify_calls.append(timeout)
        self.counts["query_settlement_confirmation"] += 1
        self.state.update(
            {
                "settlement_state": "confirmed",
                "trading_ready": True,
                "settlement_connection_generation": self.generation,
                "settlement_account_fingerprint": _account_short(),
                "settlement_trading_day": self.day,
                "settlement_proof_source": "confirmation_query",
                "settlement_proof_query_request_id": self.record.request_id,
                "settlement_readback_verified": True,
            }
        )
        return self.record

    def confirm_settlement(self, *args: Any, **kwargs: Any) -> None:
        self.write_method_calls += 1
        raise AssertionError("settlement confirmation is a native write")

    def submit_order_insert(self, *args: Any, **kwargs: Any) -> None:
        self.write_method_calls += 1
        raise AssertionError("order insertion is a native write")

    def submit_order_action(self, *args: Any, **kwargs: Any) -> None:
        self.write_method_calls += 1
        raise AssertionError("order cancellation is a native write")


def _inputs(tmp_path: Path, *, record: _QueryResult | None = None):
    selection = _selection(tmp_path)
    registration = selection.execution_registration
    client = _Trader(record=record)
    config = CtpSimNowTdTradingReadinessConfig(
        md_front=MD_FRONT,
        td_front=TD_FRONT,
        broker_id=BROKER_ID,
        user_id=USER_ID,
    )
    readiness = CtpSimNowNativeReadiness(
        config_digest=selection.config_digest,
        registration_digest=registration.digest,
        account_fingerprint_sha256=registration.account_fingerprint_sha256,
        md_front=MD_FRONT,
        td_front=TD_FRONT,
        td_ready=True,
        md_ready=True,
    )
    return client, selection, config, readiness


def test_td_readiness_rejects_confirmation_only_port_before_provider_query(
    tmp_path: Path,
) -> None:
    client, selection, config, prior = _inputs(tmp_path)
    cleanup_calls: list[str] = []

    with pytest.raises(CtpSimNowTdTradingReadinessError) as raised:
        verify_ctp_simnow_td_trading_readiness(
            client,
            selection,
            config,
            native_readiness=prior,
            failure_cleanup=lambda: cleanup_calls.append("closed"),
        )

    assert raised.value.reason == "managed_simnow_td_settlement_day_binding_unavailable"
    assert raised.value.close_state == "closed"
    assert cleanup_calls == ["closed"]
    assert client.verify_calls == []
    assert client.counts["query_settlement_confirmation"] == 0
    assert client.counts["settlement_confirm"] == 0
    assert client.counts["order_insert"] == 0
    assert client.counts["order_action"] == 0
    assert client.write_method_calls == 0
    assert client.stop_calls == 0


def test_td_readiness_requires_owner_cleanup_and_reports_partial_close(
    tmp_path: Path,
) -> None:
    client, selection, config, prior = _inputs(tmp_path)

    with pytest.raises(CtpSimNowTdTradingReadinessError) as raised:
        verify_ctp_simnow_td_trading_readiness(
            client,
            selection,
            config,
            native_readiness=prior,
        )

    assert raised.value.reason == "managed_simnow_td_failure_cleanup_required"
    assert raised.value.close_state == "close_failed"
    assert client.verify_calls == []
    assert client.stop_calls == 1


def test_td_readiness_reports_owner_cleanup_failure_without_retrying_native_stop(
    tmp_path: Path,
) -> None:
    client, selection, config, prior = _inputs(tmp_path)

    def failed_owner_cleanup() -> None:
        raise RuntimeError("offline owner cleanup failure")

    with pytest.raises(CtpSimNowTdTradingReadinessError) as raised:
        verify_ctp_simnow_td_trading_readiness(
            client,
            selection,
            config,
            native_readiness=prior,
            failure_cleanup=failed_owner_cleanup,
        )

    assert raised.value.reason == "managed_simnow_td_settlement_day_binding_unavailable"
    assert raised.value.close_state == "close_failed"
    assert client.stop_calls == 0
    assert client.write_method_calls == 0
