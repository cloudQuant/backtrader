"""Offline tests for the single-instrument, zero-trading-write CTP MD probe."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import backtrader_runtime.ctp_sdk_market_readonly as market_readonly
from backtrader_runtime.ctp_sandbox_readonly_admission import CtpSandboxReadOnlyRegistration
from backtrader_runtime.registry import RegisteredRuntime


_PRODUCTION_ACCOUNT_LOCK_ROOT = market_readonly._account_lock_root


BROKER_ID = "9999"
USER_ID = "demo"
PASSWORD = "hidden-market-password"
ACCOUNT_FP = hashlib.sha256("{0}:{1}".format(BROKER_ID, USER_ID).encode()).hexdigest()
TD_FRONT = "tcp://180.168.146.187:10130"
MD_FRONT = "tcp://180.168.146.187:10131"
INSTRUMENT = "IF2612"


@pytest.fixture(autouse=True)
def _isolate_account_probe_lock_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Give every test process a private OS-lock directory.

    The probe deliberately keeps a process-wide lock per account, so probes
    launched by separate pytest workers otherwise contend on the same fake
    account and shared OS lock file. Keeping the production key and
    lock implementation intact still exercises same-test contention while
    separating independent test invocations.
    """
    monkeypatch.setattr(
        market_readonly,
        "_account_lock_root",
        lambda: tmp_path / market_readonly._LOCK_DIRECTORY_NAME,
    )
    monkeypatch.setattr(market_readonly, "_PROCESS_LOCKS", {})
    monkeypatch.setattr(market_readonly, "_PENDING_LEASES", {})
    monkeypatch.setattr(market_readonly, "_native_stop_receipt_type", lambda: _FakeStopReceipt)
    _fake_sdk()


class _Credentials:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def require_credential(self, name: str) -> str:
        self.calls.append(name)
        return {
            "broker_id": BROKER_ID,
            "user_id": USER_ID,
            "password": PASSWORD,
        }[name]


def _admission(tmp_path: Path) -> CtpSandboxReadOnlyRegistration:
    runtime_dir = tmp_path / "registered-ctp"
    runtime_dir.mkdir(exist_ok=True)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="iteration41.ctp.market-probe",
        strategy_id="iteration41.ctp.market_probe",
        allowed_presets=("sandbox",),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=(),
        sandbox_write_policy="deny",
        approval_receipt_digest=None,
    )
    return CtpSandboxReadOnlyRegistration(
        runtime_registration=registration,
        environment="simnow_set2",
        sdk_profile="set2_7x24",
        account_fingerprint_sha256=ACCOUNT_FP,
        allowed_secrets_ref="config_yaml",
        instrument_id=INSTRUMENT,
        exchange_id="CFFEX",
        hedge_flag="1",
        td_front=TD_FRONT,
        md_front=MD_FRONT,
        session_ttl_seconds=30.0,
    )


class _FakeMdClient:
    instances: list["_FakeMdClient"] = []
    behavior = "ready"
    late_ready_hook: Any = None

    def __init__(self, front: str, broker_id: str, user_id: str, password: str) -> None:
        assert front == MD_FRONT
        assert (broker_id, user_id, password) == (BROKER_ID, USER_ID, PASSWORD)
        self.front = front
        self.broker_id = broker_id
        self.user_id = user_id
        if type(self).behavior == "initial_front_drift":
            self.front = "tcp://127.0.0.1:19001"
        elif type(self).behavior == "initial_identity_drift":
            self.user_id = "other"
        self._state_lock = threading.RLock()
        self._connected = False
        self._loggedin = False
        self.subscriptions: list[list[str]] = []
        self.stopped = 0
        self._connection_generation = 11
        self._thread = None
        self._event_thread = None
        type(self).instances.append(self)

    @property
    def connection_generation(self) -> int:
        with self._state_lock:
            return self._connection_generation

    def subscribe(self, instruments: list[str]) -> None:
        self.subscriptions.append(list(instruments))

    def start(self, *, block: bool) -> None:
        assert block is False
        if type(self).behavior == "late_ready":
            if type(self).late_ready_hook is not None:
                type(self).late_ready_hook()
            else:
                time.sleep(0.05)
        with self._state_lock:
            self._connected = True
            self._loggedin = type(self).behavior != "no_login"
        if type(self).behavior == "zero_error_login_identity":
            self.on_error(SimpleNamespace(ErrorID=0))
        elif type(self).behavior != "no_login":
            if type(self).behavior == "missing_login_identity":
                login_field = SimpleNamespace(TradingDay="20260923")
            elif type(self).behavior == "wrong_login_identity":
                login_field = SimpleNamespace(
                    BrokerID=BROKER_ID,
                    UserID="other",
                    TradingDay="20260923",
                )
            else:
                login_field = SimpleNamespace(
                    BrokerID=self.broker_id,
                    UserID=self.user_id,
                    TradingDay="20260923",
                )
            self.on_login(login_field)
            if type(self).behavior == "zero_error_after_login":
                self.on_error(SimpleNamespace(ErrorID=0))
            if type(self).behavior == "before_ack_tick":
                self.on_tick(
                    SimpleNamespace(
                        InstrumentID=INSTRUMENT,
                        ExchangeID="CFFEX",
                        LastPrice=3600.0,
                        Volume=1,
                    )
                )
        if type(self).behavior == "reconnect_before_ack":
            with self._state_lock:
                self._connection_generation += 1
        if type(self).behavior in {
            "ready",
            "tick",
            "tick_identity_drift",
            "tick_front_drift",
            "tick_generation_drift",
            "before_ack_tick",
            "wrong_exchange_tick",
            "wrong_instrument_tick",
            "invalid_tick",
            "disconnect_during_observation",
            "join_pending",
            "late_ready",
            "reconnect_drift",
            "front_drift",
            "logged_out",
            "reconnect_before_ack",
            "client_identity_drift",
            "stop_failed",
        }:
            if type(self).behavior == "client_identity_drift":
                self.user_id = "other"
            self.on_subscribe(SimpleNamespace(InstrumentID=INSTRUMENT), SimpleNamespace(ErrorID=0))
        elif type(self).behavior == "wrong_instrument_ack":
            self.on_subscribe(SimpleNamespace(InstrumentID="rb2610"), SimpleNamespace(ErrorID=0))
        elif type(self).behavior == "rejected_ack":
            self.on_subscribe(SimpleNamespace(InstrumentID=INSTRUMENT), SimpleNamespace(ErrorID=7))
        if type(self).behavior in {
            "tick",
            "tick_identity_drift",
            "tick_front_drift",
            "tick_generation_drift",
        }:
            if type(self).behavior == "tick_identity_drift":
                self.user_id = "other"
            elif type(self).behavior == "tick_front_drift":
                self.front = "tcp://127.0.0.1:19001"
            elif type(self).behavior == "tick_generation_drift":
                with self._state_lock:
                    self._connection_generation += 1
            self.on_tick(
                SimpleNamespace(
                    InstrumentID=INSTRUMENT,
                    ExchangeID="CFFEX",
                    LastPrice=3600.0,
                    Volume=1,
                )
            )
        if type(self).behavior == "wrong_exchange_tick":
            self.on_tick(
                SimpleNamespace(
                    InstrumentID=INSTRUMENT,
                    ExchangeID="SHFE",
                    LastPrice=3600.0,
                    Volume=1,
                )
            )
        if type(self).behavior == "wrong_instrument_tick":
            self.on_tick(
                SimpleNamespace(
                    InstrumentID="rb2610",
                    ExchangeID="CFFEX",
                    LastPrice=3600.0,
                    Volume=1,
                )
            )
        if type(self).behavior == "invalid_tick":
            self.on_tick(
                SimpleNamespace(
                    InstrumentID=INSTRUMENT,
                    ExchangeID="CFFEX",
                    LastPrice=float("nan"),
                    Volume=-1,
                )
            )
        if type(self).behavior == "join_pending":
            self.join_release = threading.Event()
            self._thread = threading.Thread(target=self.join_release.wait, daemon=True)
            self._thread.start()
        if type(self).behavior == "disconnect_during_observation":

            def disconnect_later() -> None:
                time.sleep(0.02)
                with self._state_lock:
                    self._connected = False
                    self._loggedin = False
                self.on_disconnect(0x1001)

            self._event_thread = threading.Thread(target=disconnect_later, daemon=True)
            self._event_thread.start()
        if type(self).behavior == "reconnect_drift":
            with self._state_lock:
                self._connection_generation += 1
        elif type(self).behavior == "front_drift":
            self.front = "tcp://127.0.0.1:19001"
        elif type(self).behavior == "logged_out":
            with self._state_lock:
                self._loggedin = False

    def stop(self) -> None:
        self.stopped += 1
        if type(self).behavior == "stop_failed":
            raise RuntimeError("provider failure containing sensitive details")

    def stop_and_wait(self, timeout: float = 2.0) -> Any:
        self.stop()
        join_thread = self._thread
        thread_alive = bool(join_thread is not None and join_thread.is_alive())
        return _FakeStopReceipt(
            connection_generation=self.connection_generation,
            join_required=join_thread is not None,
            join_completed=join_thread is not None and not thread_alive,
            native_released=not thread_alive,
            thread_alive=thread_alive,
            timed_out=thread_alive,
        )


class _FakeStopReceipt:
    def __init__(
        self,
        *,
        connection_generation: int = 11,
        join_required: bool = False,
        join_completed: bool = False,
        native_released: bool = True,
        thread_alive: bool | None = False,
        timed_out: bool = False,
        complete: bool | None = None,
    ) -> None:
        self.connection_generation = connection_generation
        self.join_required = join_required
        self.join_completed = join_completed
        self.native_released = native_released
        self.thread_alive = thread_alive
        self.timed_out = timed_out
        self._complete = (
            native_released and (not join_required or join_completed) and thread_alive is False
            if complete is None
            else complete
        )

    @property
    def complete(self) -> bool:
        return self._complete


class _PublicReceiptMdClient(_FakeMdClient):
    receipt: Any = _FakeStopReceipt()

    def __init__(self, front: str, broker_id: str, user_id: str, password: str) -> None:
        super().__init__(front, broker_id, user_id, password)
        self.stop_and_wait_calls: list[float] = []

    def stop_and_wait(self, timeout: float = 2.0) -> Any:
        self.stop_and_wait_calls.append(timeout)
        self.stop()
        return type(self).receipt


def _fake_sdk(*, behavior: str = "ready") -> None:
    _FakeMdClient.instances.clear()
    _FakeMdClient.behavior = behavior
    _FakeMdClient.late_ready_hook = None


def test_probe_uses_exact_admitted_front_and_one_instrument_without_requiring_a_tick(
    tmp_path: Path,
) -> None:
    _fake_sdk()
    result = market_readonly._probe_ctp_market_readonly(
        admission=_admission(tmp_path),
        credential_source=_Credentials(),
        client_type=_FakeMdClient,
        timeout_seconds=1.0,
    )

    client = _FakeMdClient.instances[-1]
    assert client.front == MD_FRONT
    assert client.subscriptions == [[INSTRUMENT]]
    assert client.stopped == 1
    assert result.market_login_ready is True
    assert result.subscription_acknowledged is True
    assert result.market_path_ready is True
    assert result.first_tick_observed is False
    assert result.tick_observation_count == 0
    assert result.tick_binding is None
    assert result.client_stop_returned is True
    assert result.native_join_pending is False
    assert result.probe_session_closed is True
    assert result.trading_writes == 0
    assert result.settlement_writes == 0
    assert result.order_submission_authorized is False
    assert result.md_front_sha256 == hashlib.sha256(MD_FRONT.encode()).hexdigest()
    assert result.account_fingerprint_sha256 == ACCOUNT_FP
    assert result.exchange_id == "CFFEX"
    assert "password" not in repr(result).lower()
    assert MD_FRONT not in repr(result)
    assert result.as_public_dict()["probe_session_closed"] is True


def test_public_native_stop_receipt_is_used_once_and_must_certify_release_and_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_sdk()
    _PublicReceiptMdClient.receipt = _FakeStopReceipt(
        join_required=True,
        join_completed=True,
        native_released=True,
        thread_alive=False,
    )
    monkeypatch.setattr(market_readonly, "_native_stop_receipt_type", lambda: _FakeStopReceipt)

    result = market_readonly._probe_ctp_market_readonly(
        admission=_admission(tmp_path),
        credential_source=_Credentials(),
        client_type=_PublicReceiptMdClient,
        timeout_seconds=1.0,
    )

    client = _PublicReceiptMdClient.instances[-1]
    assert client.stopped == 1
    assert len(client.stop_and_wait_calls) == 1
    assert 0 < client.stop_and_wait_calls[0] <= market_readonly._MAX_NATIVE_JOIN_WAIT_SECONDS
    assert result.probe_session_closed is True
    assert market_readonly._PROCESS_LOCKS[market_readonly._account_lock_key(ACCOUNT_FP)].locked() is False


def test_stop_without_exact_receipt_keeps_account_lease_held(
    tmp_path: Path,
) -> None:
    _fake_sdk()

    class LegacyStopOnlyMdClient(_FakeMdClient):
        stop_and_wait = None

    admission = _admission(tmp_path)
    account_key = market_readonly._account_lock_key(ACCOUNT_FP)
    try:
        with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
            market_readonly._probe_ctp_market_readonly(
                admission=admission,
                credential_source=_Credentials(),
                client_type=LegacyStopOnlyMdClient,
                timeout_seconds=1.0,
            )
        assert caught.value.reason == "market_client_stop_failed"
        assert caught.value.close_state == "native_stop_receipt_unknown"

        process_lock = market_readonly._PROCESS_LOCKS[account_key]
        assert process_lock.locked() is True
        second_credentials = _Credentials()
        with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as busy:
            market_readonly._probe_ctp_market_readonly(
                admission=admission,
                credential_source=second_credentials,
                client_type=LegacyStopOnlyMdClient,
                timeout_seconds=1.0,
            )
        assert busy.value.reason == "account_probe_busy"
        assert second_credentials.calls == []
    finally:
        with market_readonly._PENDING_LEASES_GUARD:
            pending = market_readonly._PENDING_LEASES.pop(account_key, None)
        if pending is not None:
            pending[0].release()


def test_incomplete_public_stop_receipt_keeps_account_lease_after_join_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_sdk(behavior="join_pending")
    _PublicReceiptMdClient.receipt = _FakeStopReceipt(
        join_required=True,
        join_completed=False,
        native_released=False,
        thread_alive=True,
        timed_out=True,
    )
    monkeypatch.setattr(market_readonly, "_native_stop_receipt_type", lambda: _FakeStopReceipt)
    admission = _admission(tmp_path)
    account_key = market_readonly._account_lock_key(ACCOUNT_FP)
    try:
        with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
            market_readonly._probe_ctp_market_readonly(
                admission=admission,
                credential_source=_Credentials(),
                client_type=_PublicReceiptMdClient,
                timeout_seconds=1.0,
            )

        client = _PublicReceiptMdClient.instances[-1]
        assert caught.value.reason == "market_client_stop_failed"
        assert caught.value.close_state == "native_join_pending"
        assert caught.value.client_stop_returned is True
        assert client.stopped == 1
        assert len(client.stop_and_wait_calls) == 1
        with market_readonly._PENDING_LEASES_GUARD:
            pending = market_readonly._PENDING_LEASES[account_key]
        assert pending[1] is client

        with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as busy:
            market_readonly._probe_ctp_market_readonly(
                admission=admission,
                credential_source=_Credentials(),
                client_type=_PublicReceiptMdClient,
                timeout_seconds=1.0,
            )
        assert busy.value.reason == "account_probe_busy"

        client.join_release.set()
        client._thread.join(1.0)
        process_lock = market_readonly._PROCESS_LOCKS[account_key]
        assert not client._thread.is_alive()
        assert process_lock.locked() is True
        after_join_credentials = _Credentials()
        with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as busy_after_join:
            market_readonly._probe_ctp_market_readonly(
                admission=admission,
                credential_source=after_join_credentials,
                client_type=_PublicReceiptMdClient,
                timeout_seconds=1.0,
            )
        assert busy_after_join.value.reason == "account_probe_busy"
        assert after_join_credentials.calls == []
    finally:
        client = _PublicReceiptMdClient.instances[-1]
        release = getattr(client, "join_release", None)
        if release is not None:
            release.set()
        with market_readonly._PENDING_LEASES_GUARD:
            pending = market_readonly._PENDING_LEASES.pop(account_key, None)
        if pending is not None:
            pending[0].release()


def test_unknown_or_inconsistent_public_stop_receipt_pins_lease_without_second_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_sdk()
    _PublicReceiptMdClient.receipt = _FakeStopReceipt(
        connection_generation=10,
        join_required=True,
        join_completed=True,
        native_released=True,
        thread_alive=False,
    )
    monkeypatch.setattr(market_readonly, "_native_stop_receipt_type", lambda: _FakeStopReceipt)
    admission = _admission(tmp_path)
    account_key = market_readonly._account_lock_key(ACCOUNT_FP)
    try:
        with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
            market_readonly._probe_ctp_market_readonly(
                admission=admission,
                credential_source=_Credentials(),
                client_type=_PublicReceiptMdClient,
                timeout_seconds=1.0,
            )

        client = _PublicReceiptMdClient.instances[-1]
        assert caught.value.reason == "market_client_stop_failed"
        assert caught.value.close_state == "native_stop_receipt_unknown"
        assert caught.value.client_stop_returned is True
        assert client.stopped == 1
        assert len(client.stop_and_wait_calls) == 1
        with market_readonly._PENDING_LEASES_GUARD:
            pending = market_readonly._PENDING_LEASES[account_key]
        assert pending[1] is client
    finally:
        with market_readonly._PENDING_LEASES_GUARD:
            pending = market_readonly._PENDING_LEASES.pop(account_key, None)
        if pending is not None:
            pending[0].release()


def test_tick_is_only_an_optional_matching_instrument_observation(
    tmp_path: Path,
) -> None:
    _fake_sdk(behavior="tick")
    result = market_readonly._probe_ctp_market_readonly(
        admission=_admission(tmp_path),
        credential_source=_Credentials(),
        client_type=_FakeMdClient,
        timeout_seconds=1.0,
        tick_observation_seconds=0.2,
    )
    assert result.market_path_ready is True
    assert result.first_tick_observed is True
    assert result.tick_observation_count == 1
    assert result.tick_binding is not None
    assert result.tick_binding.account_fingerprint_sha256 == ACCOUNT_FP
    assert result.tick_binding.md_front_sha256 == hashlib.sha256(MD_FRONT.encode()).hexdigest()
    assert result.tick_binding.instrument_id == INSTRUMENT
    assert result.tick_binding.exchange_id == "CFFEX"
    assert result.tick_binding.connection_generation == result.connection_generation == 11
    assert result.probe_session_closed is True
    assert result.trading_writes == result.settlement_writes == 0
    assert result.order_submission_authorized is False
    assert result.account_fingerprint_sha256 == ACCOUNT_FP
    assert ACCOUNT_FP not in repr(result)
    public = result.as_public_dict()
    assert public["tick_observation_count"] == 1
    assert public["tick_binding"] == {
        "account_bound": True,
        "connection_generation": 11,
        "exchange_id": "CFFEX",
        "instrument_id": INSTRUMENT,
        "md_front_sha256": hashlib.sha256(MD_FRONT.encode()).hexdigest(),
    }
    assert public["account_scope_bound"] is True
    assert ACCOUNT_FP not in repr(public)
    assert public["trading_writes"] == public["settlement_writes"] == 0
    assert public["probe_session_closed"] is True


def test_tick_callback_is_not_counted_when_observation_window_is_disabled(
    tmp_path: Path,
) -> None:
    _fake_sdk(behavior="tick")
    result = market_readonly._probe_ctp_market_readonly(
        admission=_admission(tmp_path),
        credential_source=_Credentials(),
        client_type=_FakeMdClient,
        timeout_seconds=1.0,
    )

    assert result.market_path_ready is True
    assert result.tick_observation_count == 0
    assert result.tick_binding is None


@pytest.mark.parametrize(
    "behavior", ("wrong_exchange_tick", "wrong_instrument_tick", "invalid_tick")
)
def test_tick_observation_requires_exchange_and_minimally_valid_market_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    behavior: str,
) -> None:
    _fake_sdk(behavior=behavior)
    result = market_readonly._probe_ctp_market_readonly(
        admission=_admission(tmp_path),
        credential_source=_Credentials(),
        client_type=_FakeMdClient,
        timeout_seconds=1.0,
        tick_observation_seconds=0.2,
    )

    assert result.market_path_ready is True
    assert result.first_tick_observed is False
    assert result.tick_observation_count == 0
    assert result.tick_binding is None


def test_tick_before_exact_subscription_ack_is_not_observation(tmp_path: Path) -> None:
    _fake_sdk(behavior="before_ack_tick")
    result = market_readonly._probe_ctp_market_readonly(
        admission=_admission(tmp_path),
        credential_source=_Credentials(),
        client_type=_FakeMdClient,
        timeout_seconds=1.0,
        tick_observation_seconds=0.04,
    )

    assert result.market_path_ready is True
    assert result.tick_observation_count == 0
    assert result.tick_binding is None
    assert result.probe_session_closed is True


def test_tick_observation_timeout_is_bounded_and_reports_no_tick(tmp_path: Path) -> None:
    _fake_sdk()
    started = time.monotonic()
    result = market_readonly._probe_ctp_market_readonly(
        admission=_admission(tmp_path),
        credential_source=_Credentials(),
        client_type=_FakeMdClient,
        timeout_seconds=1.0,
        tick_observation_seconds=0.04,
    )
    elapsed = time.monotonic() - started

    assert 0.03 <= elapsed < 0.75
    assert result.market_path_ready is True
    assert result.tick_observation_count == 0
    assert result.tick_binding is None
    assert result.probe_session_closed is True
    assert result.trading_writes == result.settlement_writes == 0


def test_disconnect_during_tick_observation_rejects_and_closes_client(tmp_path: Path) -> None:
    _fake_sdk(behavior="disconnect_during_observation")
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=1.0,
            tick_observation_seconds=0.2,
        )

    client = _FakeMdClient.instances[-1]
    if client._event_thread is not None:
        client._event_thread.join(1.0)
    assert caught.value.reason == "market_front_disconnected"
    assert caught.value.close_state == "stop_returned"
    assert client.front == MD_FRONT
    assert client.stopped == 1


@pytest.mark.parametrize(
    ("behavior", "expected_reason"),
    (
        ("tick_identity_drift", "market_client_identity_mismatch"),
        ("tick_front_drift", "market_front_binding_mismatch"),
        ("tick_generation_drift", "market_connection_generation_changed"),
    ),
)
def test_tick_callback_requires_current_account_front_and_generation_binding(
    tmp_path: Path,
    behavior: str,
    expected_reason: str,
) -> None:
    _fake_sdk(behavior=behavior)
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=1.0,
            tick_observation_seconds=0.04,
        )

    client = _FakeMdClient.instances[-1]
    assert caught.value.reason == expected_reason
    assert caught.value.close_state == "stop_returned"
    assert client.front == ("tcp://127.0.0.1:19001" if behavior == "tick_front_drift" else MD_FRONT)
    assert client.stopped == 1
    assert len(_FakeMdClient.instances) == 1


def test_login_timeout_stops_client_and_redacts_provider_details(
    tmp_path: Path,
) -> None:
    _fake_sdk(behavior="no_login")
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=0.03,
        )

    assert caught.value.reason == "market_login_timeout"
    assert caught.value.close_state == "stop_returned"
    assert _FakeMdClient.instances[-1].stopped == 1
    assert len(_FakeMdClient.instances) == 1
    assert _FakeMdClient.instances[-1].front == MD_FRONT
    assert PASSWORD not in str(caught.value)
    assert MD_FRONT not in str(caught.value)


@pytest.mark.parametrize(
    ("behavior", "expected_reason"),
    (
        ("wrong_login_identity", "market_login_identity_mismatch"),
        ("missing_login_identity", "market_login_identity_unavailable"),
    ),
)
def test_probe_requires_login_response_identity_to_match_sealed_credentials(
    tmp_path: Path,
    behavior: str,
    expected_reason: str,
) -> None:
    _fake_sdk(behavior=behavior)
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=1.0,
        )

    assert caught.value.reason == expected_reason
    assert caught.value.close_state == "stop_returned"
    assert _FakeMdClient.instances[-1].stopped == 1
    assert PASSWORD not in str(caught.value)
    assert USER_ID not in str(caught.value)


@pytest.mark.parametrize(
    ("behavior", "expected_reason"),
    (
        ("zero_error_login_identity", "market_login_identity_mismatch"),
        ("zero_error_after_login", "market_subscription_rejected"),
    ),
)
def test_zero_error_callback_fails_closed_while_login_or_subscription_is_pending(
    tmp_path: Path,
    behavior: str,
    expected_reason: str,
) -> None:
    _fake_sdk(behavior=behavior)
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=1.0,
        )

    assert caught.value.reason == expected_reason
    assert caught.value.close_state == "stop_returned"
    assert _FakeMdClient.instances[-1].stopped == 1
    assert PASSWORD not in str(caught.value)


@pytest.mark.parametrize(
    ("behavior", "expected_reason"),
    (
        ("reconnect_drift", "market_connection_generation_changed"),
        ("reconnect_before_ack", "market_connection_generation_changed"),
        ("client_identity_drift", "market_client_identity_mismatch"),
        ("front_drift", "market_front_binding_mismatch"),
        ("logged_out", "market_session_not_ready"),
    ),
)
def test_probe_rechecks_current_generation_readiness_and_front_at_completion(
    tmp_path: Path,
    behavior: str,
    expected_reason: str,
) -> None:
    _fake_sdk(behavior=behavior)
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=1.0,
        )

    assert caught.value.reason == expected_reason
    assert caught.value.close_state == "stop_returned"
    assert _FakeMdClient.instances[-1].stopped == 1
    assert PASSWORD not in str(caught.value)
    assert USER_ID not in str(caught.value)


@pytest.mark.parametrize(
    ("behavior", "expected_reason"),
    (
        ("initial_front_drift", "market_front_binding_mismatch"),
        ("initial_identity_drift", "market_client_identity_mismatch"),
    ),
)
def test_probe_checks_client_front_and_identity_before_start(
    tmp_path: Path,
    behavior: str,
    expected_reason: str,
) -> None:
    _fake_sdk(behavior=behavior)
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=1.0,
        )

    client = _FakeMdClient.instances[-1]
    assert caught.value.reason == expected_reason
    assert caught.value.close_state == "stop_returned"
    assert client.stopped == 1
    assert client.subscriptions == []


def test_callbacks_after_start_consumes_deadline_are_not_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_sdk(behavior="late_ready")
    clock = [100.0]
    monkeypatch.setattr(market_readonly, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    _FakeMdClient.late_ready_hook = lambda: clock.__setitem__(0, 101.1)
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=1.0,
        )

    assert caught.value.reason == "probe_deadline_expired"
    assert caught.value.close_state == "stop_returned"
    assert _FakeMdClient.instances[-1].stopped == 1


def test_expired_probe_deadline_still_gives_native_stop_bounded_grace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_sdk(behavior="late_ready")
    _PublicReceiptMdClient.behavior = "late_ready"
    _PublicReceiptMdClient.receipt = _FakeStopReceipt()
    clock = [100.0]
    monkeypatch.setattr(market_readonly, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    _PublicReceiptMdClient.late_ready_hook = lambda: clock.__setitem__(0, 101.1)
    monkeypatch.setattr(market_readonly, "_native_stop_receipt_type", lambda: _FakeStopReceipt)

    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=_PublicReceiptMdClient,
            timeout_seconds=1.0,
        )

    client = _PublicReceiptMdClient.instances[-1]
    assert caught.value.reason == "probe_deadline_expired"
    assert client.stop_and_wait_calls == [market_readonly._MAX_NATIVE_JOIN_WAIT_SECONDS]
    assert caught.value.close_state == "stop_returned"
    assert caught.value.client_stop_returned is True


@pytest.mark.parametrize(
    ("behavior", "timeout", "expected_reason"),
    (
        ("wrong_instrument_ack", 0.05, "subscription_ack_timeout"),
        ("rejected_ack", 1.0, "market_subscription_rejected"),
    ),
)
def test_probe_rejects_missing_or_negative_exact_subscription_ack_and_stops_client(
    tmp_path: Path,
    behavior: str,
    timeout: float,
    expected_reason: str,
) -> None:
    _fake_sdk(behavior=behavior)
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=timeout,
        )
    assert caught.value.reason == expected_reason
    assert caught.value.close_state == "stop_returned"
    assert PASSWORD not in str(caught.value)
    assert MD_FRONT not in str(caught.value)
    assert _FakeMdClient.instances[-1].stopped == 1


def test_probe_rejects_account_mismatch_before_constructing_md_client(
    tmp_path: Path,
) -> None:
    loaded = []

    def unexpected_sdk_load(*_args: Any, **_kwargs: Any) -> None:
        loaded.append(True)
        raise AssertionError("SDK import must not occur for an account mismatch")

    class WrongAccount(_Credentials):
        def require_credential(self, name: str) -> str:
            self.calls.append(name)
            values = {
                "broker_id": BROKER_ID,
                "user_id": "other",
                "password": PASSWORD,
            }
            return values[name]

    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=WrongAccount(),
            client_type=unexpected_sdk_load,
            timeout_seconds=1.0,
        )
    assert caught.value.reason == "credential_account_mismatch"
    assert loaded == []


def test_stop_failure_pins_client_and_account_lease_until_manual_cleanup(
    tmp_path: Path,
) -> None:
    _fake_sdk(behavior="stop_failed")
    admission = _admission(tmp_path)
    account_key = market_readonly._account_lock_key(ACCOUNT_FP)
    try:
        with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
            market_readonly._probe_ctp_market_readonly(
                admission=admission,
                credential_source=_Credentials(),
                client_type=_FakeMdClient,
                timeout_seconds=1.0,
            )

        client = _FakeMdClient.instances[-1]
        assert caught.value.reason == "market_client_stop_failed"
        assert caught.value.close_state == "stop_failed"
        assert client.stopped == 1
        with market_readonly._PENDING_LEASES_GUARD:
            pending = market_readonly._PENDING_LEASES[account_key]
        assert pending[1] is client

        second_credentials = _Credentials()
        with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as busy:
            market_readonly._probe_ctp_market_readonly(
                admission=admission,
                credential_source=second_credentials,
                client_type=_FakeMdClient,
                timeout_seconds=1.0,
            )
        assert busy.value.reason == "account_probe_busy"
        assert second_credentials.calls == []
    finally:
        # This fake has no native API. Release the intentionally pinned lease
        # so this test cannot contaminate another offline probe test.
        with market_readonly._PENDING_LEASES_GUARD:
            pending = market_readonly._PENDING_LEASES.pop(account_key, None)
        if pending is not None:
            pending[0].release()


def test_stop_failure_retains_redacted_primary_probe_reason(tmp_path: Path) -> None:
    _fake_sdk(behavior="no_login")
    admission = _admission(tmp_path)
    account_key = market_readonly._account_lock_key(ACCOUNT_FP)

    class StopFailsAfterLoginTimeout(_FakeMdClient):
        def stop(self) -> None:
            super().stop()
            raise RuntimeError("provider failure containing sensitive details")

    try:
        with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
            market_readonly._probe_ctp_market_readonly(
                admission=admission,
                credential_source=_Credentials(),
                client_type=StopFailsAfterLoginTimeout,
                timeout_seconds=0.02,
            )
        assert caught.value.reason == "market_client_stop_failed"
        assert caught.value.close_state == "stop_failed"
        assert caught.value.primary_reason == "market_login_timeout"
        assert caught.value.front_callback_observed is False
        assert caught.value.client_stop_returned is False
        assert "sensitive" not in str(caught.value)
    finally:
        with market_readonly._PENDING_LEASES_GUARD:
            pending = market_readonly._PENDING_LEASES.pop(account_key, None)
        if pending is not None:
            pending[0].release()


def test_login_timeout_reports_front_callback_generation_without_accepting_login(
    tmp_path: Path,
) -> None:
    _fake_sdk(behavior="no_login")

    class FrontConnectedWithoutLogin(_FakeMdClient):
        def start(self, *, block: bool) -> None:
            super().start(block=block)
            with self._state_lock:
                self._connection_generation += 1

    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=FrontConnectedWithoutLogin,
            timeout_seconds=0.02,
        )
    assert caught.value.reason == "market_login_timeout"
    assert caught.value.front_callback_observed is True
    assert FrontConnectedWithoutLogin.instances[-1].stopped == 1


def test_login_timeout_preserves_fixed_sdk_callback_diagnostic(tmp_path: Path) -> None:
    _fake_sdk(behavior="no_login")

    class LoginCallbackFiltered(_FakeMdClient):
        @property
        def login_callback_diagnostic(self) -> SimpleNamespace:
            return SimpleNamespace(
                callback_count=1,
                disposition=SimpleNamespace(value="request_id_mismatch"),
                request_id_relation=SimpleNamespace(value="higher"),
                response_error_status=SimpleNamespace(value="nonzero"),
            )

    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=LoginCallbackFiltered,
            timeout_seconds=0.02,
        )
    assert caught.value.reason == "market_login_timeout"
    assert caught.value.login_callback_count == 1
    assert caught.value.login_callback_disposition == "request_id_mismatch"
    assert caught.value.login_request_id_relation == "higher"
    assert caught.value.login_response_error_status == "nonzero"


def test_login_timeout_preserves_only_allowlisted_native_field_shapes(tmp_path: Path) -> None:
    _fake_sdk(behavior="no_login")

    class NativeFieldShapeDiagnostic(_FakeMdClient):
        @property
        def login_callback_diagnostic(self) -> SimpleNamespace:
            return SimpleNamespace(
                callback_count=1,
                disposition=SimpleNamespace(value="identity_rejected"),
                request_id_relation=SimpleNamespace(value="zero"),
                response_error_status=SimpleNamespace(value="zero"),
                native_broker_id_shape=SimpleNamespace(value="nonempty_terminated"),
                native_user_id_shape=SimpleNamespace(value="unterminated"),
            )

    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=NativeFieldShapeDiagnostic,
            timeout_seconds=0.02,
        )
    assert caught.value.native_broker_id_shape == "nonempty_terminated"
    assert caught.value.native_user_id_shape == "unterminated"


def test_unrecognized_native_field_shapes_are_omitted(tmp_path: Path) -> None:
    _fake_sdk(behavior="no_login")

    class UnknownNativeFieldShapeDiagnostic(_FakeMdClient):
        @property
        def login_callback_diagnostic(self) -> SimpleNamespace:
            return SimpleNamespace(
                callback_count=1,
                disposition=SimpleNamespace(value="identity_rejected"),
                native_broker_id_shape=SimpleNamespace(value="raw_provider_message"),
                native_user_id_shape=SimpleNamespace(value="unterminated"),
            )

    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=UnknownNativeFieldShapeDiagnostic,
            timeout_seconds=0.02,
        )
    assert caught.value.native_broker_id_shape is None
    assert caught.value.native_user_id_shape == "unterminated"
    assert "raw_provider_message" not in str(caught.value)


def test_unknown_sdk_login_diagnostic_is_omitted(tmp_path: Path) -> None:
    _fake_sdk(behavior="no_login")

    class UnknownLoginDiagnostic(_FakeMdClient):
        @property
        def login_callback_diagnostic(self) -> SimpleNamespace:
            return SimpleNamespace(
                callback_count=1,
                disposition=SimpleNamespace(value="raw_provider_message"),
            )

    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=_Credentials(),
            client_type=UnknownLoginDiagnostic,
            timeout_seconds=0.02,
        )
    assert caught.value.login_callback_count is None
    assert caught.value.login_callback_disposition is None
    assert caught.value.login_request_id_relation is None
    assert caught.value.login_response_error_status is None


def test_same_account_probe_is_rejected_while_an_existing_probe_is_active(
    tmp_path: Path,
) -> None:
    started = threading.Event()
    release_start = threading.Event()
    created: list[Any] = []

    class BlockingMdClient(_FakeMdClient):
        def start(self, *, block: bool) -> None:
            assert block is False
            created.append(self)
            started.set()
            assert release_start.wait(2.0)
            with self._state_lock:
                self._connected = True
                self._loggedin = True
            self.on_login(SimpleNamespace(BrokerID=BROKER_ID, UserID=USER_ID))
            self.on_subscribe(SimpleNamespace(InstrumentID=INSTRUMENT), SimpleNamespace(ErrorID=0))

    results: list[Any] = []

    def run_first() -> None:
        results.append(
            market_readonly._probe_ctp_market_readonly(
                admission=_admission(tmp_path),
                credential_source=_Credentials(),
                client_type=BlockingMdClient,
                timeout_seconds=1.5,
            )
        )

    worker = threading.Thread(target=run_first)
    worker.start()
    assert started.wait(1.0)
    second_credentials = _Credentials()
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=_admission(tmp_path),
            credential_source=second_credentials,
            client_type=BlockingMdClient,
            timeout_seconds=1.0,
        )
    assert caught.value.reason == "account_probe_busy"
    assert second_credentials.calls == []
    assert len(created) == 1

    release_start.set()
    worker.join(2.0)
    assert not worker.is_alive()
    assert len(results) == 1 and results[0].market_path_ready is True


def test_account_lock_root_is_independent_of_process_temp_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = _PRODUCTION_ACCOUNT_LOCK_ROOT()
    for name in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(name, str(tmp_path / name))
    second = _PRODUCTION_ACCOUNT_LOCK_ROOT()
    assert first == second


def test_account_lease_excludes_another_process_with_a_different_temp_root(
    tmp_path: Path,
) -> None:
    """Different process temp settings still contend on the same OS lock."""

    account_key = uuid.uuid4().hex
    lease = market_readonly._AccountLease(account_key)
    lease.acquire()
    try:
        child_tmp = tmp_path / "child-temp"
        child_tmp.mkdir()
        child_code = """
import pathlib
import sys
import backtrader_runtime.ctp_sdk_market_readonly as module
module._account_lock_root = lambda: pathlib.Path(sys.argv[1])
lease = module._AccountLease(sys.argv[2])
try:
    lease.acquire()
except module.CtpSdkMarketReadOnlyError as error:
    print(error.reason)
else:
    lease.release()
    print("acquired")
"""
        child_environment = os.environ.copy()
        for name in ("TMP", "TEMP", "TMPDIR"):
            child_environment[name] = str(child_tmp)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                child_code,
                str(market_readonly._account_lock_root()),
                account_key,
            ],
            cwd=Path(__file__).resolve().parents[3],
            env=child_environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "account_probe_busy"
    finally:
        lease.release()


def test_same_account_lease_remains_held_after_incomplete_join_receipt(
    tmp_path: Path,
) -> None:
    _fake_sdk(behavior="join_pending")
    admission = _admission(tmp_path)
    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=admission,
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=1.0,
        )
    client = _FakeMdClient.instances[-1]
    assert caught.value.reason == "market_client_stop_failed"
    assert caught.value.close_state == "native_join_pending"
    assert caught.value.client_stop_returned is True

    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=admission,
            credential_source=_Credentials(),
            client_type=_FakeMdClient,
            timeout_seconds=1.0,
        )
    assert caught.value.reason == "account_probe_busy"

    client.join_release.set()
    client._thread.join(1.0)
    key = market_readonly._account_lock_key(ACCOUNT_FP)
    process_lock = market_readonly._PROCESS_LOCKS[key]
    assert not client._thread.is_alive()
    assert process_lock.locked() is True
    try:
        with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as after_join:
            market_readonly._probe_ctp_market_readonly(
                admission=admission,
                credential_source=_Credentials(),
                client_type=_FakeMdClient,
                timeout_seconds=1.0,
            )
        assert after_join.value.reason == "account_probe_busy"
    finally:
        with market_readonly._PENDING_LEASES_GUARD:
            pending = market_readonly._PENDING_LEASES.pop(key, None)
        if pending is not None:
            pending[0].release()


def test_invalid_admission_is_rejected_before_client_type_is_used() -> None:
    loaded = []

    def unexpected_client_type(*_args: Any, **_kwargs: Any) -> None:
        loaded.append(True)

    with pytest.raises(market_readonly.CtpSdkMarketReadOnlyError) as caught:
        market_readonly._probe_ctp_market_readonly(
            admission=object(),
            credential_source=_Credentials(),
            client_type=unexpected_client_type,
        )
    assert caught.value.reason == "admission_required"
    assert loaded == []
