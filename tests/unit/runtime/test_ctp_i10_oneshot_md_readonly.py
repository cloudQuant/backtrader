"""Fake-only contract tests for the unregistered I10 MD observation adapter."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backtrader_runtime import ctp_i10_oneshot_md_readonly as adapter
from backtrader_runtime.ctp_sandbox_readonly_admission import CtpSandboxReadOnlyRegistration
import backtrader_runtime.ctp_sdk_market_readonly as market_readonly
from backtrader_runtime.ctp_sdk_market_readonly import CtpSdkMarketReadOnlyError
from backtrader_runtime.registry import RegisteredRuntime


BROKER_ID = "9999"
USER_ID = "i10-fake-user"
PASSWORD = "fake-only-password"
ACCOUNT_FP = hashlib.sha256(f"{BROKER_ID}:{USER_ID}".encode("utf-8")).hexdigest()
TD_FRONT = "tcp://127.0.0.1:10130"
MD_FRONT = "tcp://127.0.0.1:10131"
INSTRUMENT = "IF2612"
EXCHANGE = "CFFEX"
TRADING_DAY = "20260925"


class _FakeLease:
    instances: list["_FakeLease"] = []

    def __init__(self, _account_key: str) -> None:
        self.account_key = _account_key
        self.released = False
        type(self).instances.append(self)

    def acquire(self) -> None:
        return None

    def release(self) -> None:
        self.released = True


class CtpNativeStopReceipt:
    __module__ = "bt_api_ctp.ctp.client"

    def __init__(self, generation: int, *, complete: bool = True) -> None:
        self.connection_generation = generation
        self.join_required = True
        self.join_completed = complete
        self.native_released = complete
        self.thread_alive = False
        self.timed_out = not complete
        self.client_stop_returned = True
        self.complete = complete


class OneShotMdDiagnosticClient:
    """Synthetic I10 surface covering both login callback outcomes."""

    __module__ = "bt_api_ctp.ctp.client"
    mode = "verified"
    wrong_login_user = False
    wrong_tick_day = False
    submit_result: Any = 0
    stop_receipt_complete = True
    stop_callback_count = 0
    stop_clock = None
    stop_clock_advance = 0.0
    instances: list["OneShotMdDiagnosticClient"] = []

    def __init__(
        self,
        front: str,
        broker_id: str,
        user_id: str,
        _password: str,
        *,
        expected_diagnostic_instrument: str,
    ) -> None:
        self.front = front
        self.broker_id = broker_id
        self.user_id = user_id
        self.expected_diagnostic_instrument = expected_diagnostic_instrument
        self.mode = type(self).mode
        self.wrong_login_user = type(self).wrong_login_user
        self.wrong_tick_day = type(self).wrong_tick_day
        self._state_lock = threading.RLock()
        self._connection_generation = 0
        self._connected = False
        self._loggedin = False
        self._active_md_identity = None
        self._diagnostic_identity_unverified = False
        self._diagnostic_identity_unverified_active = False
        self._diagnostic_identity_unverified_trading_day = None
        self._diagnostic_terminal = False
        self._diagnostic_terminal_reason = None
        self._diagnostic_subscription_acknowledged = False
        self._diagnostic_first_tick_received = False
        self.diagnostic_callbacks_active = type(self).stop_callback_count
        self.subscriptions: list[list[str]] = []
        self.stop_calls = 0
        self.on_login = None
        self.on_identity_unverified = None
        self.on_error = None
        self.on_disconnect = None
        self.on_subscribe = None
        self.on_tick = None
        type(self).instances.append(self)

    @property
    def connection_generation(self) -> int:
        return self._connection_generation

    @property
    def login_callback_diagnostic(self) -> Any:
        unverified = self.mode == "identity_unverified"
        disposition = (
            "identity_unverified"
            if unverified
            else "terminal"
            if self._diagnostic_terminal
            else "accepted"
        )
        shapes = (
            ("empty", "empty", "valid", "empty", "empty")
            if unverified
            else (
                "exact_match",
                "exact_match",
                "valid",
                "nonempty_terminated",
                "nonempty_terminated",
            )
        )
        names = (
            "broker_id_shape",
            "user_id_shape",
            "trading_day_shape",
            "native_broker_id_shape",
            "native_user_id_shape",
        )
        result = SimpleNamespace(
            callback_count=1,
            disposition=SimpleNamespace(value=disposition),
            request_id_relation=SimpleNamespace(value="zero"),
            response_error_status=SimpleNamespace(value="zero"),
        )
        for name, shape in zip(names, shapes):
            setattr(result, name, SimpleNamespace(value=shape))
        return result

    @property
    def active_md_identity(self) -> Any:
        with self._state_lock:
            if not self._connected or not self._loggedin:
                return None
            return self._active_md_identity

    @property
    def diagnostic_identity_unverified(self) -> bool:
        return self._diagnostic_identity_unverified

    @property
    def diagnostic_subscription_acknowledged(self) -> bool:
        return self._diagnostic_subscription_acknowledged

    @property
    def diagnostic_first_tick_received(self) -> bool:
        return self._diagnostic_first_tick_received

    @property
    def diagnostic_terminal(self) -> bool:
        return self._diagnostic_terminal

    @property
    def diagnostic_terminal_reason(self) -> str | None:
        return self._diagnostic_terminal_reason

    def start(self, *, block: bool) -> None:
        assert block is False
        with self._state_lock:
            self._connection_generation = 1
            self._connected = True
            if self.mode == "identity_unverified":
                self._diagnostic_identity_unverified = True
                self._diagnostic_identity_unverified_active = True
                self._diagnostic_identity_unverified_trading_day = TRADING_DAY
            else:
                self._loggedin = True
                self._active_md_identity = SimpleNamespace(
                    front=self.front,
                    broker_id=self.broker_id,
                    user_id=self.user_id,
                    connection_generation=1,
                    request_id=0,
                    trading_day=TRADING_DAY,
                    authenticated=True,
                )
        if self.mode == "identity_unverified":
            self.on_identity_unverified()
        else:
            self.on_login(
                SimpleNamespace(
                    BrokerID=self.broker_id,
                    UserID="wrong" if self.wrong_login_user else self.user_id,
                    TradingDay=TRADING_DAY,
                )
            )

    def subscribe(self, instruments: list[str]) -> Any:
        assert instruments == [self.expected_diagnostic_instrument]
        self.subscriptions.append(list(instruments))
        if type(self).submit_result != 0 or type(type(self).submit_result) is not int:
            return type(self).submit_result
        instrument = instruments[0]
        self._diagnostic_subscription_acknowledged = True
        self.on_subscribe(
            SimpleNamespace(InstrumentID=instrument),
            SimpleNamespace(ErrorID=0),
        )
        with self._state_lock:
            self._diagnostic_first_tick_received = True
            self._diagnostic_terminal = True
            self._diagnostic_terminal_reason = "diagnostic_complete"
            self._connected = False
            self._loggedin = False
            self._active_md_identity = None
            self._diagnostic_identity_unverified_active = False
        self.on_tick(
            SimpleNamespace(
                InstrumentID=instrument,
                ExchangeID=EXCHANGE,
                TradingDay="20260926" if self.wrong_tick_day else TRADING_DAY,
                LastPrice=123.5,
                Volume=1,
            )
        )
        return 0

    def stop_and_wait(self, *, timeout: float) -> CtpNativeStopReceipt:
        assert timeout > 0
        self.stop_calls += 1
        if type(self).stop_clock is not None:
            type(self).stop_clock.advance(type(self).stop_clock_advance)
        return CtpNativeStopReceipt(
            self._connection_generation,
            complete=type(self).stop_receipt_complete,
        )


class _FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _admission(tmp_path: Path) -> CtpSandboxReadOnlyRegistration:
    runtime_dir = tmp_path / "registered-ctp"
    runtime_dir.mkdir(exist_ok=True)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="iteration41.ctp.i10-md-observation",
        strategy_id="iteration41.ctp.i10_md_observation",
        allowed_presets=("sandbox",),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=(),
        sandbox_write_policy="deny",
        approval_receipt_digest=None,
    )
    return CtpSandboxReadOnlyRegistration(
        runtime_registration=registration,
        environment="simnow",
        sdk_profile="config_front_pair",
        account_fingerprint_sha256=ACCOUNT_FP,
        allowed_secrets_ref="config_yaml",
        instrument_id=INSTRUMENT,
        exchange_id=EXCHANGE,
        hedge_flag="1",
        td_front=TD_FRONT,
        md_front=MD_FRONT,
        session_ttl_seconds=30.0,
    )


class _Credentials:
    def require_credential(self, name: str) -> str:
        return {"broker_id": BROKER_ID, "user_id": USER_ID, "password": PASSWORD}[name]


def _run(
    tmp_path: Path,
    *,
    mode: str = "verified",
    wrong_login_user: bool = False,
    wrong_tick_day: bool = False,
    timeout_seconds: float = 0.5,
    submit_result: Any = 0,
    stop_receipt_complete: bool = True,
    stop_callback_count: int = 0,
    stop_clock: _FakeClock | None = None,
    stop_clock_advance: float = 0.0,
) -> Any:
    OneShotMdDiagnosticClient.mode = mode
    OneShotMdDiagnosticClient.wrong_login_user = wrong_login_user
    OneShotMdDiagnosticClient.wrong_tick_day = wrong_tick_day
    OneShotMdDiagnosticClient.submit_result = submit_result
    OneShotMdDiagnosticClient.stop_receipt_complete = stop_receipt_complete
    OneShotMdDiagnosticClient.stop_callback_count = stop_callback_count
    OneShotMdDiagnosticClient.stop_clock = stop_clock
    OneShotMdDiagnosticClient.stop_clock_advance = stop_clock_advance
    OneShotMdDiagnosticClient.instances = []
    _FakeLease.instances = []
    try:
        return adapter.probe_i10_oneshot_md_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=OneShotMdDiagnosticClient,
            stop_receipt_type=CtpNativeStopReceipt,
            timeout_seconds=timeout_seconds,
        )
    finally:
        OneShotMdDiagnosticClient.mode = "verified"
        OneShotMdDiagnosticClient.wrong_login_user = False
        OneShotMdDiagnosticClient.wrong_tick_day = False
        OneShotMdDiagnosticClient.submit_result = 0
        OneShotMdDiagnosticClient.stop_receipt_complete = True
        OneShotMdDiagnosticClient.stop_callback_count = 0
        OneShotMdDiagnosticClient.stop_clock = None
        OneShotMdDiagnosticClient.stop_clock_advance = 0.0


@pytest.fixture(autouse=True)
def _use_fake_lease(monkeypatch: pytest.MonkeyPatch) -> Any:
    pending_leases: dict[str, Any] = {}
    monkeypatch.setattr(adapter, "_AccountLease", _FakeLease)
    monkeypatch.setattr(market_readonly, "_PENDING_LEASES", pending_leases)
    yield
    for lease, _client, _thread in pending_leases.values():
        lease.release()
    pending_leases.clear()


@pytest.mark.parametrize(
    ("mode", "expected_state"),
    [
        ("verified", "verified"),
        ("identity_unverified", "identity_unverified"),
    ],
)
def test_i10_adapter_distinguishes_login_identity_and_observes_one_contract(
    tmp_path: Path,
    mode: str,
    expected_state: str,
) -> None:
    observation = _run(tmp_path, mode=mode)

    assert type(observation) is adapter.CtpI10OneShotMdObservation
    assert observation.login_identity_state == expected_state
    assert observation.verified_login_observed is (mode == "verified")
    assert observation.identity_unverified is (mode == "identity_unverified")
    assert observation.instrument_id == INSTRUMENT
    assert observation.subscription_acknowledged is True
    assert observation.matching_tick_observed is True
    assert observation.same_trading_day_observed is True
    assert observation.probe_session_closed is True
    assert observation.market_login_ready is False
    assert observation.account_ready is False
    assert observation.trading_ready is False
    assert observation.order_submission_authorized is False
    assert observation.trading_writes == observation.settlement_writes == 0


def test_i10_adapter_rejects_verified_identity_mismatch_before_subscription(
    tmp_path: Path,
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, mode="verified", wrong_login_user=True)

    assert error.value.reason == "market_login_identity_mismatch"
    assert error.value.i10_progress_evidence == adapter.CtpI10OneShotMdProgressEvidence()
    assert OneShotMdDiagnosticClient.instances[0].subscriptions == []


def test_i10_adapter_rejects_successful_close_that_finishes_after_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(adapter, "time", SimpleNamespace(monotonic=clock.monotonic))

    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(
            tmp_path,
            timeout_seconds=5.0,
            stop_clock=clock,
            stop_clock_advance=6.0,
        )

    assert error.value.reason == "probe_deadline_expired"
    assert error.value.i10_progress_evidence == adapter.CtpI10OneShotMdProgressEvidence(
        login_identity_state="verified",
        subscription_acknowledged=True,
        matching_tick_observed=True,
        same_trading_day_observed=True,
    )
    assert OneShotMdDiagnosticClient.instances[0].stop_calls == 1
    assert _FakeLease.instances[0].released is True


@pytest.mark.parametrize(
    ("mode", "expected_identity"),
    [("verified", "verified"), ("identity_unverified", "identity_unverified")],
)
def test_i10_adapter_retains_lease_when_stop_receipt_is_incomplete(
    tmp_path: Path,
    mode: str,
    expected_identity: str,
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, mode=mode, stop_receipt_complete=False)

    assert error.value.reason == "market_client_stop_failed"
    assert error.value.close_state == "native_stop_incomplete"
    assert error.value.i10_progress_evidence == adapter.CtpI10OneShotMdProgressEvidence(
        login_identity_state=expected_identity,
        subscription_acknowledged=True,
        matching_tick_observed=True,
        same_trading_day_observed=True,
    )
    assert _FakeLease.instances[0].released is False


def test_i10_adapter_retains_lease_while_sdk_callbacks_remain_active(tmp_path: Path) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, stop_callback_count=1)

    assert error.value.reason == "market_client_stop_failed"
    assert error.value.close_state == "native_stop_receipt_unknown"
    assert error.value.i10_progress_evidence == adapter.CtpI10OneShotMdProgressEvidence(
        login_identity_state="verified",
        subscription_acknowledged=True,
        matching_tick_observed=True,
        same_trading_day_observed=True,
    )
    assert _FakeLease.instances[0].released is False


def test_i10_adapter_rejects_nonzero_or_noninteger_subscription_submit(
    tmp_path: Path,
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, submit_result=None)

    assert error.value.reason == "market_subscription_rejected"
    assert error.value.i10_progress_evidence == adapter.CtpI10OneShotMdProgressEvidence(
        login_identity_state="verified"
    )
    assert OneShotMdDiagnosticClient.instances[0].subscriptions == [[INSTRUMENT]]
    assert _FakeLease.instances[0].released is True


def test_i10_failure_retains_ack_but_not_an_unmatched_tick(
    tmp_path: Path,
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, wrong_tick_day=True)

    assert error.value.reason == "market_probe_failed"
    assert error.value.i10_progress_evidence == adapter.CtpI10OneShotMdProgressEvidence(
        login_identity_state="verified",
        subscription_acknowledged=True,
    )
