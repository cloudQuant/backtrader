"""Fake-only contract tests for the unregistered I3 one-shot MD adapter."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import backtrader_runtime.ctp_sdk_market_readonly as market_readonly
from backtrader_runtime.ctp_i3_oneshot_md_readonly import probe_i3_oneshot_md_readonly
from backtrader_runtime.ctp_sandbox_readonly_admission import CtpSandboxReadOnlyRegistration
from backtrader_runtime.ctp_sdk_market_readonly import CtpSdkMarketReadOnlyError
from backtrader_runtime.registry import RegisteredRuntime


BROKER_ID = "9999"
USER_ID = "i3-fake-user"
PASSWORD = "fake-only-password"
ACCOUNT_FP = hashlib.sha256("{0}:{1}".format(BROKER_ID, USER_ID).encode()).hexdigest()
TD_FRONT = "tcp://127.0.0.1:10130"
MD_FRONT = "tcp://127.0.0.1:10131"
INSTRUMENT = "IF2612"
EXCHANGE = "CFFEX"


class CtpNativeStopReceipt:
    """Small exact-type stand-in for the I3 SDK public receipt."""

    __module__ = "bt_api_ctp.ctp.client"

    def __init__(
        self,
        generation: int,
        *,
        join_required: bool = False,
        join_completed: bool = True,
        native_released: bool = True,
        thread_alive: bool | None = False,
        timed_out: bool = False,
        client_stop_returned: bool | None = True,
    ) -> None:
        self.connection_generation = generation
        self.join_required = join_required
        self.join_completed = join_completed
        self.native_released = native_released
        self.thread_alive = thread_alive
        self.timed_out = timed_out
        self.client_stop_returned = client_stop_returned

    @property
    def complete(self) -> bool:
        return (
            self.native_released
            and (not self.join_required or self.join_completed)
            and self.thread_alive is False
            and not self.timed_out
            and self.client_stop_returned is True
        )


class OneShotMdDiagnosticClient:
    """Fake I3 client with the same callback and stop receipt surface."""

    __module__ = "bt_api_ctp.ctp.client"
    behavior = "ready"
    active_callbacks = 0
    broker_id_shape: Any = None
    user_id_shape: Any = None
    trading_day_shape: Any = None
    native_broker_id_shape: Any = None
    native_user_id_shape: Any = None
    instances: list["OneShotMdDiagnosticClient"] = []

    def __init__(self, front: str, broker_id: str, user_id: str, password: str) -> None:
        assert front == MD_FRONT
        assert (broker_id, user_id, password) == (BROKER_ID, USER_ID, PASSWORD)
        self.front = front
        self.broker_id = broker_id
        self.user_id = user_id
        self._state_lock = threading.RLock()
        self._connection_generation = 0
        self._connected = False
        self._loggedin = False
        self._thread: threading.Thread | None = None
        self.on_login = None
        self.on_error = None
        self.on_disconnect = None
        self.on_subscribe = None
        self.on_tick = None
        self.events: list[str] = []
        self.subscriptions: list[list[str]] = []
        self.stop_calls = 0
        self.trader_requests = 0
        self.order_requests = 0
        self._join_release: threading.Event | None = None
        self._diag_count = 0
        self._diag_disposition = "none"
        self._diag_request_relation = "not_observed"
        self._diag_error_status = "not_observed"
        self._terminal = False
        self._terminal_reason = None
        self._subscription_acknowledged = False
        self._first_tick = False
        type(self).instances.append(self)

    @property
    def connection_generation(self) -> int:
        with self._state_lock:
            return self._connection_generation

    @property
    def login_callback_diagnostic(self) -> Any:
        diagnostic = SimpleNamespace(
            callback_count=self._diag_count,
            disposition=SimpleNamespace(value=self._diag_disposition),
            request_id_relation=SimpleNamespace(value=self._diag_request_relation),
            response_error_status=SimpleNamespace(value=self._diag_error_status),
        )
        if type(self).broker_id_shape is not None:
            diagnostic.broker_id_shape = type(self).broker_id_shape
        if type(self).user_id_shape is not None:
            diagnostic.user_id_shape = type(self).user_id_shape
        if type(self).trading_day_shape is not None:
            diagnostic.trading_day_shape = type(self).trading_day_shape
        if type(self).native_broker_id_shape is not None:
            diagnostic.native_broker_id_shape = type(self).native_broker_id_shape
        if type(self).native_user_id_shape is not None:
            diagnostic.native_user_id_shape = type(self).native_user_id_shape
        return diagnostic

    @property
    def diagnostic_terminal(self) -> bool:
        return self._terminal

    @property
    def diagnostic_terminal_reason(self) -> str | None:
        return self._terminal_reason

    @property
    def diagnostic_subscription_acknowledged(self) -> bool:
        return self._subscription_acknowledged

    @property
    def diagnostic_first_tick_received(self) -> bool:
        return self._first_tick

    @property
    def diagnostic_callbacks_active(self) -> int:
        if type(self).behavior == "missing_callback_state":
            raise AttributeError("diagnostic_callbacks_active")
        return type(self).active_callbacks

    def start(self, *, block: bool) -> None:
        assert block is False
        self.events.append("start")
        with self._state_lock:
            self._connection_generation += 1
            self._connected = True
            self._loggedin = False
        if type(self).behavior == "login_timeout":
            return
        if type(self).behavior == "nonzero_login_id":
            self._diag_count = 1
            self._diag_disposition = "request_id_mismatch"
            self._diag_request_relation = "higher"
            self._diag_error_status = "zero"
            self._terminal = True
            self._terminal_reason = "login_request_id_mismatch"
            self.on_error(SimpleNamespace(ErrorID=0))
            return
        if type(self).behavior == "provider_rejected":
            self._diag_count = 1
            self._diag_disposition = "provider_rejected"
            self._diag_request_relation = "zero"
            self._diag_error_status = "nonzero"
            self._terminal = True
            self._terminal_reason = "provider_login_rejected"
            self.on_error(SimpleNamespace(ErrorID=7))
            return
        if type(self).behavior in {
            "broker_identity_rejected",
            "broker_identity_rejected_join_pending",
            "user_identity_rejected",
            "trading_day_rejected",
        }:
            self._diag_count = 1
            self._diag_disposition = "identity_rejected"
            self._diag_request_relation = "zero"
            self._diag_error_status = "zero"
            self._terminal = True
            self._terminal_reason = {
                "broker_identity_rejected": "broker_id_mismatch",
                "broker_identity_rejected_join_pending": "broker_id_mismatch",
                "user_identity_rejected": "user_id_mismatch",
                "trading_day_rejected": "trading_day_invalid",
            }[type(self).behavior]
            if type(self).behavior == "broker_identity_rejected_join_pending":
                self._join_release = threading.Event()
                self._thread = threading.Thread(target=self._join_release.wait, daemon=True)
                self._thread.start()
            self.on_error(SimpleNamespace(ErrorID=0))
            return
        with self._state_lock:
            self._loggedin = True
        self._diag_count = 1
        self._diag_disposition = "accepted"
        self._diag_request_relation = "zero"
        self._diag_error_status = "zero"
        login = SimpleNamespace(BrokerID=BROKER_ID, UserID=USER_ID)
        if type(self).behavior == "wrong_login_broker":
            login.BrokerID = "other-broker"
        if type(self).behavior == "wrong_login_identity":
            login.UserID = "other-user"
        self.events.append("login_callback")
        self.on_login(login)

    def subscribe(self, instruments: list[str]) -> int:
        assert self._loggedin is True
        self.events.append("subscribe")
        self.subscriptions.append(list(instruments))
        if type(self).behavior == "ack_timeout":
            return 0
        behavior = type(self).behavior
        if behavior == "wrong_ack_instrument":
            self.on_subscribe(SimpleNamespace(InstrumentID="rb2610"), SimpleNamespace(ErrorID=0))
            return 0
        if behavior == "wrong_ack_error":
            self.on_subscribe(SimpleNamespace(InstrumentID=INSTRUMENT), SimpleNamespace(ErrorID=7))
            return 0

        self._subscription_acknowledged = True
        self.events.append("ack_callback")
        self.on_subscribe(SimpleNamespace(InstrumentID=INSTRUMENT), SimpleNamespace(ErrorID=0))
        if behavior == "tick_timeout":
            return 0

        if behavior == "changed_connection_generation":
            with self._state_lock:
                self._connection_generation += 1

        tick_instrument = "rb2610" if behavior == "wrong_tick_instrument" else INSTRUMENT
        tick_exchange = "SHFE" if behavior == "wrong_tick_exchange" else EXCHANGE
        if behavior == "wrong_tick_identity":
            self.user_id = "other-user"
        if behavior == "wrong_tick_front":
            self.front = "tcp://127.0.0.1:19001"
        with self._state_lock:
            self._connected = False
            self._loggedin = False
        self._terminal = True
        self._terminal_reason = "diagnostic_complete"
        self._first_tick = True
        self._diag_disposition = "terminal"
        self.events.append("tick_callback")
        self.on_tick(
            SimpleNamespace(
                InstrumentID=tick_instrument,
                ExchangeID=tick_exchange,
                LastPrice=3600.0,
                Volume=1,
            )
        )
        if behavior == "complete_stop_with_active_callback":
            # The user callback returned, while its enclosing SDK SPI wrapper
            # still appears active as the probe begins cleanup.
            type(self).active_callbacks = 1
        if behavior == "join_pending":
            self._join_release = threading.Event()
            self._thread = threading.Thread(target=self._join_release.wait, daemon=True)
            self._thread.start()
        return 0

    def stop_and_wait(self, *, timeout: float) -> CtpNativeStopReceipt:
        assert timeout > 0
        self.stop_calls += 1
        if type(self).behavior in {"join_pending", "broker_identity_rejected_join_pending"}:
            return CtpNativeStopReceipt(
                self._connection_generation,
                join_required=True,
                join_completed=False,
                native_released=False,
                thread_alive=True,
                timed_out=True,
            )
        if type(self).behavior in {"stop_raised_receipt", "stop_inflight_receipt"}:
            return CtpNativeStopReceipt(
                self._connection_generation,
                client_stop_returned=(
                    False if type(self).behavior == "stop_raised_receipt" else None
                ),
            )
        receipt = CtpNativeStopReceipt(self._connection_generation)
        if type(self).behavior == "invalid_stop_receipt":
            receipt.connection_generation += 1
        if type(self).behavior == "missing_stop_completion_field":
            del receipt.client_stop_returned
        return receipt


OneShotMdDiagnosticClient.instances = []


class _Credentials:
    def __init__(self) -> None:
        self.names: list[str] = []

    def require_credential(self, name: str) -> str:
        self.names.append(name)
        return {"broker_id": BROKER_ID, "user_id": USER_ID, "password": PASSWORD}[name]


def _admission(tmp_path: Path) -> CtpSandboxReadOnlyRegistration:
    runtime_dir = tmp_path / "registered-ctp"
    runtime_dir.mkdir(exist_ok=True)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="iteration41.ctp.i3-md-diagnostic",
        strategy_id="iteration41.ctp.i3_md_diagnostic",
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


@pytest.fixture(autouse=True)
def _isolate_fake_probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setattr(
        market_readonly,
        "_account_lock_root",
        lambda: tmp_path / market_readonly._LOCK_DIRECTORY_NAME,
    )
    monkeypatch.setattr(market_readonly, "_PROCESS_LOCKS", {})
    monkeypatch.setattr(market_readonly, "_PENDING_LEASES", {})
    monkeypatch.setattr(OneShotMdDiagnosticClient, "behavior", "ready")
    monkeypatch.setattr(OneShotMdDiagnosticClient, "active_callbacks", 0)
    monkeypatch.setattr(OneShotMdDiagnosticClient, "broker_id_shape", None)
    monkeypatch.setattr(OneShotMdDiagnosticClient, "user_id_shape", None)
    monkeypatch.setattr(OneShotMdDiagnosticClient, "trading_day_shape", None)
    monkeypatch.setattr(OneShotMdDiagnosticClient, "native_broker_id_shape", None)
    monkeypatch.setattr(OneShotMdDiagnosticClient, "native_user_id_shape", None)
    OneShotMdDiagnosticClient.instances = []
    yield
    for client in OneShotMdDiagnosticClient.instances:
        if client._join_release is not None:
            client._join_release.set()
        if client._thread is not None:
            client._thread.join(timeout=1.0)
    for lease, _client, _thread in list(market_readonly._PENDING_LEASES.values()):
        lease.release()
    market_readonly._PENDING_LEASES.clear()


def _run(tmp_path: Path, *, behavior: str = "ready", timeout: float = 0.5) -> Any:
    OneShotMdDiagnosticClient.behavior = behavior
    return probe_i3_oneshot_md_readonly(
        admission=_admission(tmp_path),
        credential_source=_Credentials(),
        client_type=OneShotMdDiagnosticClient,
        stop_receipt_type=CtpNativeStopReceipt,
        timeout_seconds=timeout,
    )


def test_id_zero_login_then_one_exact_subscription_ack_and_tick(tmp_path: Path) -> None:
    observation = _run(tmp_path)
    client = OneShotMdDiagnosticClient.instances[0]

    assert observation.login_request_id == 0
    assert observation.market_login_ready is True
    assert observation.subscription_acknowledged is True
    assert observation.matching_tick_observed is True
    assert observation.probe_session_closed is True
    assert observation.order_submission_authorized is False
    assert observation.trading_writes == observation.settlement_writes == 0
    assert client.events.index("login_callback") < client.events.index("subscribe")
    assert client.subscriptions == [[INSTRUMENT]]
    assert client.stop_calls == 1
    assert client.trader_requests == client.order_requests == 0


@pytest.mark.parametrize(
    ("behavior", "reason"),
    [
        ("nonzero_login_id", "market_login_identity_mismatch"),
        ("wrong_login_identity", "market_login_identity_mismatch"),
        ("wrong_login_broker", "market_login_identity_mismatch"),
        ("wrong_ack_instrument", "market_subscription_rejected"),
        ("wrong_ack_error", "market_subscription_rejected"),
        ("wrong_tick_instrument", "market_probe_failed"),
        ("wrong_tick_exchange", "market_probe_failed"),
        ("wrong_tick_identity", "market_client_identity_mismatch"),
        ("wrong_tick_front", "market_front_binding_mismatch"),
        ("changed_connection_generation", "market_connection_generation_changed"),
    ],
)
def test_scope_or_callback_mismatch_fails_closed(
    tmp_path: Path, behavior: str, reason: str
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior=behavior)

    assert error.value.reason == reason
    assert error.value.client_stop_returned is True
    assert error.value.close_state == "stop_returned"


@pytest.mark.parametrize(
    ("behavior", "count", "disposition", "relation", "status", "category"),
    [
        ("nonzero_login_id", 1, "request_id_mismatch", "higher", "zero", "request_id_mismatch"),
        ("provider_rejected", 1, "provider_rejected", "zero", "nonzero", "provider_rejected"),
        (
            "broker_identity_rejected",
            1,
            "identity_rejected",
            "zero",
            "zero",
            "broker_id_mismatch",
        ),
        (
            "user_identity_rejected",
            1,
            "identity_rejected",
            "zero",
            "zero",
            "user_id_mismatch",
        ),
        (
            "trading_day_rejected",
            1,
            "identity_rejected",
            "zero",
            "zero",
            "trading_day_invalid",
        ),
        ("login_timeout", 0, "none", "not_observed", "not_observed", None),
    ],
)
def test_login_failure_carries_only_fixed_sdk_diagnostics(
    tmp_path: Path,
    behavior: str,
    count: int,
    disposition: str,
    relation: str,
    status: str,
    category: str | None,
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior=behavior, timeout=0.03 if behavior == "login_timeout" else 0.5)

    assert error.value.login_callback_count == count
    assert error.value.login_callback_disposition == disposition
    assert error.value.login_request_id_relation == relation
    assert error.value.login_response_error_status == status
    assert error.value.login_failure_category == category
    assert error.value.login_user_id_shape is None
    assert error.value.login_trading_day_shape is None


@pytest.mark.parametrize(
    "shape",
    [
        "not_observed",
        "unreadable",
        "empty",
        "ascii_mismatch",
        "nonascii_or_replacement",
        "whitespace_or_control",
        "exact_match",
    ],
)
def test_broker_id_shape_is_copied_as_an_allowlisted_value_and_keeps_failure_category(
    tmp_path: Path, shape: str
) -> None:
    OneShotMdDiagnosticClient.broker_id_shape = SimpleNamespace(value=shape)

    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="user_identity_rejected")

    assert error.value.login_broker_id_shape == shape
    assert error.value.login_failure_category == "user_id_mismatch"


def test_broker_id_shape_and_matching_failure_category_coexist(tmp_path: Path) -> None:
    OneShotMdDiagnosticClient.broker_id_shape = SimpleNamespace(value="ascii_mismatch")

    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="broker_identity_rejected")

    assert error.value.login_broker_id_shape == "ascii_mismatch"
    assert error.value.login_failure_category == "broker_id_mismatch"


@pytest.mark.parametrize(
    "shape",
    [
        "not_observed",
        "unreadable",
        "empty",
        "ascii_mismatch",
        "nonascii_or_replacement",
        "whitespace_or_control",
        "exact_match",
    ],
)
def test_i6_user_id_shape_is_copied_without_changing_failure_category(
    tmp_path: Path, shape: str
) -> None:
    OneShotMdDiagnosticClient.user_id_shape = SimpleNamespace(value=shape)

    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="user_identity_rejected")

    assert error.value.login_user_id_shape == shape
    assert error.value.login_failure_category == "user_id_mismatch"


@pytest.mark.parametrize(
    "shape",
    [
        "not_observed",
        "unreadable",
        "empty",
        "invalid_format",
        "invalid_calendar",
        "valid",
    ],
)
def test_i6_trading_day_shape_is_copied_without_changing_failure_category(
    tmp_path: Path, shape: str
) -> None:
    OneShotMdDiagnosticClient.trading_day_shape = SimpleNamespace(value=shape)

    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="trading_day_rejected")

    assert error.value.login_trading_day_shape == shape
    assert error.value.login_failure_category == "trading_day_invalid"


@pytest.mark.parametrize(
    ("attribute", "error_attribute"),
    [
        ("user_id_shape", "login_user_id_shape"),
        ("trading_day_shape", "login_trading_day_shape"),
    ],
)
def test_i6_unknown_identity_shapes_are_omitted_without_raw_leakage(
    tmp_path: Path, attribute: str, error_attribute: str
) -> None:
    setattr(OneShotMdDiagnosticClient, attribute, SimpleNamespace(value="private-raw-value"))

    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="user_identity_rejected")

    assert getattr(error.value, error_attribute) is None
    assert "private-raw-value" not in str(error.value)
    assert "private-raw-value" not in repr(vars(error.value))


@pytest.mark.parametrize(
    "diagnostic_shape",
    [
        None,
        SimpleNamespace(),
        SimpleNamespace(value=None),
        SimpleNamespace(value=1),
        SimpleNamespace(value="private-raw-broker-id"),
    ],
)
def test_absent_or_invalid_broker_id_shape_is_omitted_without_raw_leakage(
    tmp_path: Path, diagnostic_shape: Any
) -> None:
    OneShotMdDiagnosticClient.broker_id_shape = diagnostic_shape

    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="user_identity_rejected")

    assert error.value.login_broker_id_shape is None
    assert error.value.login_failure_category == "user_id_mismatch"
    assert "private-raw-broker-id" not in str(error.value)
    assert "private-raw-broker-id" not in repr(vars(error.value))


def test_market_readonly_error_filters_direct_unallowlisted_shape() -> None:
    error = CtpSdkMarketReadOnlyError(
        "market_login_identity_mismatch",
        login_broker_id_shape="private-raw-broker-id",
    )

    assert error.login_broker_id_shape is None
    assert "private-raw-broker-id" not in str(error)
    assert "private-raw-broker-id" not in repr(vars(error))


def test_market_readonly_error_filters_unallowlisted_i6_identity_shapes() -> None:
    error = CtpSdkMarketReadOnlyError(
        "market_login_identity_mismatch",
        login_user_id_shape="private-raw-user-id",
        login_trading_day_shape="private-raw-trading-day",
    )

    assert error.login_user_id_shape is None
    assert error.login_trading_day_shape is None
    assert "private-raw-user-id" not in str(error)
    assert "private-raw-trading-day" not in str(error)
    assert "private-raw-user-id" not in repr(vars(error))
    assert "private-raw-trading-day" not in repr(vars(error))


def test_join_failure_preserves_callback_diagnostics_after_stop_attempt(tmp_path: Path) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="join_pending")

    assert error.value.close_state == "native_join_pending"
    assert error.value.login_callback_count == 1
    assert error.value.login_callback_disposition == "terminal"
    assert error.value.login_request_id_relation == "zero"
    assert error.value.login_response_error_status == "zero"
    assert error.value.login_failure_category is None


def test_native_login_field_shapes_reach_identity_failure_after_pending_join(
    tmp_path: Path,
) -> None:
    OneShotMdDiagnosticClient.native_broker_id_shape = SimpleNamespace(value="empty")
    OneShotMdDiagnosticClient.native_user_id_shape = SimpleNamespace(
        value="nonempty_terminated"
    )

    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="broker_identity_rejected_join_pending")

    assert error.value.reason == "market_client_stop_failed"
    assert error.value.primary_reason == "market_login_identity_mismatch"
    assert error.value.close_state == "native_join_pending"
    assert error.value.login_failure_category == "broker_id_mismatch"
    assert error.value.login_broker_id_shape is None
    assert error.value.native_broker_id_shape == "empty"
    assert error.value.native_user_id_shape == "nonempty_terminated"


def test_unknown_native_login_field_shapes_are_omitted(tmp_path: Path) -> None:
    sentinel = "private-native-field-bytes"
    OneShotMdDiagnosticClient.native_broker_id_shape = SimpleNamespace(value=sentinel)
    OneShotMdDiagnosticClient.native_user_id_shape = SimpleNamespace(value="unterminated")

    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="broker_identity_rejected")

    assert error.value.native_broker_id_shape is None
    assert error.value.native_user_id_shape == "unterminated"
    assert sentinel not in str(error.value)
    assert sentinel not in repr(vars(error.value))


@pytest.mark.parametrize(
    ("behavior", "reason"),
    [
        ("login_timeout", "market_login_timeout"),
        ("ack_timeout", "subscription_ack_timeout"),
        ("tick_timeout", "matching_tick_not_observed"),
    ],
)
def test_missing_callback_times_out_and_closes(tmp_path: Path, behavior: str, reason: str) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior=behavior, timeout=0.03)

    assert error.value.reason == reason
    assert error.value.client_stop_returned is True
    assert error.value.close_state == "stop_returned"


def test_pending_native_join_is_not_success_and_keeps_account_lease(
    tmp_path: Path,
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="join_pending")

    client = OneShotMdDiagnosticClient.instances[0]
    assert error.value.reason == "market_client_stop_failed"
    assert error.value.close_state == "native_join_pending"
    assert error.value.client_stop_returned is True
    assert client._join_release is not None
    assert any(entry[1] is client for entry in market_readonly._PENDING_LEASES.values())


@pytest.mark.parametrize(
    ("behavior", "stop_returned"),
    [
        ("stop_raised_receipt", False),
        ("stop_inflight_receipt", None),
    ],
)
def test_native_teardown_without_client_stop_return_does_not_release_lease(
    tmp_path: Path, behavior: str, stop_returned: bool | None
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior=behavior)

    client = OneShotMdDiagnosticClient.instances[0]
    assert error.value.reason == "market_client_stop_failed"
    assert error.value.close_state == "native_stop_incomplete"
    assert error.value.client_stop_returned is stop_returned
    assert any(entry[1] is client for entry in market_readonly._PENDING_LEASES.values())


def test_legacy_receipt_without_client_stop_completion_field_fails_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="missing_stop_completion_field")

    client = OneShotMdDiagnosticClient.instances[0]
    assert error.value.reason == "market_client_stop_failed"
    assert error.value.close_state == "native_stop_receipt_unknown"
    assert error.value.client_stop_returned is None
    assert any(entry[1] is client for entry in market_readonly._PENDING_LEASES.values())


def test_incoherent_stop_receipt_is_rejected_and_lease_is_retained(tmp_path: Path) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="invalid_stop_receipt")

    client = OneShotMdDiagnosticClient.instances[0]
    assert error.value.reason == "market_client_stop_failed"
    assert error.value.close_state == "native_stop_receipt_unknown"
    assert error.value.client_stop_returned is None
    assert any(entry[1] is client for entry in market_readonly._PENDING_LEASES.values())


def test_complete_stop_receipt_with_active_callback_is_rejected_and_lease_retained(
    tmp_path: Path,
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="complete_stop_with_active_callback")

    client = OneShotMdDiagnosticClient.instances[0]
    assert error.value.reason == "market_client_stop_failed"
    assert error.value.close_state == "native_stop_receipt_unknown"
    assert client.diagnostic_callbacks_active == 1
    assert client.stop_calls == 1
    assert any(entry[1] is client for entry in market_readonly._PENDING_LEASES.values())


def test_complete_stop_receipt_without_public_callback_state_fails_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(CtpSdkMarketReadOnlyError) as error:
        _run(tmp_path, behavior="missing_callback_state")

    client = OneShotMdDiagnosticClient.instances[0]
    assert error.value.reason == "market_client_stop_failed"
    assert error.value.close_state == "native_stop_receipt_unknown"
    assert client.stop_calls == 1
    assert any(entry[1] is client for entry in market_readonly._PENDING_LEASES.values())
