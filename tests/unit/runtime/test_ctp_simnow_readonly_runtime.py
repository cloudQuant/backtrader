"""Composition tests for the sealed CTP SimNow zero-write entry point.

All native SDK and Credential Manager behavior is simulated.  These tests do
not connect to SimNow, enumerate Windows credentials, or submit a CTP request.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

import backtrader_runtime.capability_imports as capability_imports
import backtrader_runtime.config as runtime_config
import backtrader_runtime.credential_resolver as credential_resolver
import backtrader_runtime.ctp_artifact_provenance as ctp_artifact_provenance
import backtrader_runtime.ctp_sdk_market_readonly as market_readonly
import backtrader_runtime.ctp_simnow_readonly_runtime as readonly_runtime
from backtrader_runtime.config import load_runtime_config
from backtrader_runtime.credential_resolver import (
    CTP_AUTHENTICATION_CREDENTIAL_KEYS,
    ResolvedRuntimeCredentials,
    RuntimeCredentialScope,
)
from backtrader_runtime.ctp_sandbox_readonly_admission import CtpSandboxReadOnlyRegistration
from backtrader_runtime.ctp_simnow_readonly_runtime import (
    CtpSimNowReadOnlyRuntimeError,
    open_ctp_simnow_readonly_runtime,
)
from backtrader_runtime.errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from backtrader_runtime.registry import RegisteredRuntime, RuntimeRegistry, resolve_runtime_config


SECRET_REF = "config_yaml"
TD_FRONT = "tcp://180.168.146.187:10130"
MD_FRONT = "tcp://180.168.146.187:10131"
ACCOUNT_FINGERPRINT = hashlib.sha256(b"9999:demo").hexdigest()
SECRET_VALUES = {
    "broker_id": "9999",
    "user_id": "demo",
    "password": "sentinel-raw-password-never-log",
    "app_id": "reviewed-app",
    "auth_code": "sentinel-raw-auth-code-never-log",
}
WRITE_KEYS = ("settlement_confirm", "order_insert", "order_action")
QUERY_NAMES = (
    "account",
    "positions",
    "orders",
    "trades",
    "instruments",
    "margin_rate",
    "commission_rate",
)
_MD_CLIENT_LOADS = []


class _FakeNativeStopReceipt:
    """Exact-shape receipt for the fake SDK's bounded native stop."""

    def __init__(
        self,
        *,
        connection_generation: int,
        join_required: bool,
        join_completed: bool,
        native_released: bool,
        thread_alive: bool,
        timed_out: bool,
    ) -> None:
        self.connection_generation = connection_generation
        self.join_required = join_required
        self.join_completed = join_completed
        self.native_released = native_released
        self.thread_alive = thread_alive
        self.timed_out = timed_out

    @property
    def complete(self) -> bool:
        return (
            self.native_released
            and (not self.join_required or self.join_completed)
            and self.thread_alive is False
            and not self.timed_out
        )


@pytest.fixture(autouse=True)
def _isolate_private_config_permission_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)
    monkeypatch.setattr(credential_resolver, "_require_posix_private_config_acl", lambda *a: None)
    monkeypatch.setattr(credential_resolver, "_require_windows_private_config_acl", lambda *a: None)
    # Isolate the account-lock directory per test so parallel pytest workers
    # using this fake account do not collide; each test still exercises the
    # real same-account lock behavior within its own scope.
    monkeypatch.setattr(
        market_readonly,
        "_account_lock_root",
        lambda: tmp_path / market_readonly._LOCK_DIRECTORY_NAME,
    )
    monkeypatch.setattr(market_readonly, "_PROCESS_LOCKS", {})
    monkeypatch.setattr(market_readonly, "_PENDING_LEASES", {})
    monkeypatch.setattr(market_readonly, "_native_stop_receipt_type", lambda: _FakeNativeStopReceipt)
    _FakeClient.instances.clear()
    _FakeClient.fail_start = False
    _FakeMdClient.instances.clear()
    _FakeMdClient.behavior = "ready"
    yield
    with market_readonly._PENDING_LEASES_GUARD:
        pending = tuple(market_readonly._PENDING_LEASES.values())
        market_readonly._PENDING_LEASES.clear()
    for lease, _client, _thread in pending:
        lease.release()


def _is_capability_module(name: object) -> bool:
    return isinstance(name, str) and name.split(".", 1)[0].startswith("bt_api_")


@contextmanager
def _isolated_capability_modules():
    """Avoid ambient SDK cache state when testing the strict import boundary."""

    saved = {
        module_name: module
        for module_name, module in tuple(sys.modules.items())
        if _is_capability_module(module_name)
    }
    for module_name in saved:
        sys.modules.pop(module_name, None)
    try:
        yield
    finally:
        for module_name in tuple(sys.modules):
            if _is_capability_module(module_name):
                sys.modules.pop(module_name, None)
        sys.modules.update(saved)


def _write_capability_package(root: Path, status: str) -> Path:
    package = root / "bt_api_ctp"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("STATUS = {0!r}\n".format(status), encoding="utf-8")
    return package


def _write_installed_base_package(root: Path) -> None:
    package = root / "bt_api_base"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# installed dependency\n", encoding="utf-8")


def _use_strict_installed_capability_context(
    monkeypatch: pytest.MonkeyPatch, purelib: Path
) -> None:
    monkeypatch.setattr(
        capability_imports.sysconfig,
        "get_paths",
        lambda: {"purelib": str(purelib), "platlib": str(purelib)},
    )
    monkeypatch.setattr(
        readonly_runtime,
        "trusted_installed_capability_import_context",
        capability_imports.trusted_installed_capability_import_context,
    )


def _write_config(
    runtime_dir: Path,
    *,
    front_pairs: tuple[tuple[str, str], ...] | None = None,
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if front_pairs is None:
        fronts_yaml = "  md_front: {0}\n  td_front: {1}\n".format(MD_FRONT, TD_FRONT)
    else:
        fronts_yaml = "  front_pairs:\n" + "".join(
            "    - md_front: {0}\n      td_front: {1}\n".format(md_front, td_front)
            for md_front, td_front in front_pairs
        )
    (runtime_dir / "config.yaml").write_text(
        """config_schema_version: 4
strategy:
  id: iteration41.ctp.sandbox_readonly
runtime:
  mode: simulation
  preset: sandbox
parameters: {{}}
secrets_ref: {0}
ctp_simnow:
{1}  instrument_id: IF2612
  exchange_id: CFFEX
  hedge_flag: '1'
  broker_id: '9999'
  user_id: demo
  password: {2}
  app_id: reviewed-app
  auth_code: {3}
""".format(
        SECRET_REF,
        fronts_yaml,
        SECRET_VALUES["password"],
        SECRET_VALUES["auth_code"],
        ),
        encoding="utf-8",
    )
    if os.name == "posix":
        runtime_dir.chmod(0o700)
        (runtime_dir / "config.yaml").chmod(0o600)


def _inputs(
    runtime_dir: Path,
    *,
    front_pairs: tuple[tuple[str, str], ...] | None = None,
    selected_pair: tuple[str, str] | None = None,
):
    _write_config(runtime_dir, front_pairs=front_pairs)
    if selected_pair is None:
        selected_pair = front_pairs[0] if front_pairs else (MD_FRONT, TD_FRONT)
    selected_md_front, selected_td_front = selected_pair
    runtime_registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="iteration41.ctp.sandbox-readonly",
        strategy_id="iteration41.ctp.sandbox_readonly",
        allowed_presets=("sandbox",),
        allowed_secrets_refs=(SECRET_REF,),
        available_capabilities=(),
        sandbox_write_policy="deny",
        approval_receipt_digest=None,
    )
    registry = RuntimeRegistry((runtime_registration,), registry_id="test.ctp-simnow-readonly")
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )
    admission = CtpSandboxReadOnlyRegistration(
        runtime_registration=runtime_registration,
        environment="simnow",
        sdk_profile="config_front_pair",
        account_fingerprint_sha256=ACCOUNT_FINGERPRINT,
        allowed_secrets_ref=SECRET_REF,
        instrument_id="IF2612",
        exchange_id="CFFEX",
        hedge_flag="1",
        td_front=selected_td_front,
        md_front=selected_md_front,
        session_ttl_seconds=30.0,
    )
    scope = RuntimeCredentialScope(
        runtime_id=runtime_registration.runtime_id,
        strategy_id=effective.strategy_id,
        provider="ctp",
        provider_environment="simnow",
        policy_environment="sandbox",
        mode="simulation",
        preset="sandbox",
        account_access="sandbox_private_read",
        account_fingerprint_sha256=ACCOUNT_FINGERPRINT,
        secrets_ref=SECRET_REF,
        credential_keys=CTP_AUTHENTICATION_CREDENTIAL_KEYS,
        effective_config_digest=effective.effective_digest,
        registration_digest=runtime_registration.digest,
    )
    return {
        "admission": admission,
        "effective": effective,
        "registration": runtime_registration,
        "registry": registry,
        "scope": scope,
    }


class _FakeClient:
    instances = []
    fail_start = False

    def __init__(
        self,
        front,
        broker_id,
        user_id,
        password,
        *,
        app_id,
        auth_code,
        auto_settlement_confirm,
    ) -> None:
        assert (broker_id, user_id) == ("9999", "demo")
        assert password == SECRET_VALUES["password"]
        assert app_id == SECRET_VALUES["app_id"]
        assert auth_code == SECRET_VALUES["auth_code"]
        assert auto_settlement_confirm is False
        self.started = False
        self.stopped = 0
        self._thread = None
        self._join_active = False
        self._native_init_started = False
        self.front = front
        self.counts = dict.fromkeys(WRITE_KEYS, 0)
        self.calls = []
        type(self).instances.append(self)

    def start(self, *, block: bool) -> None:
        assert block is False
        if type(self).fail_start:
            raise RuntimeError(SECRET_VALUES["password"])
        self.started = True

    def wait_ready(self, *, timeout: float) -> bool:
        assert 0 < timeout <= 15
        return True

    def stop(self) -> None:
        self.stopped += 1

    def get_session_state(self):
        return {"auto_settlement_confirm": False}

    def get_query_session_scope(self):
        return SimpleNamespace(
            read_only_ready=True,
            broker_id="9999",
            investor_id="demo",
            trading_day="20260923",
            connection_generation=7,
        )

    def get_front_binding_state(self):
        return {
            "configured_front": self.front,
            "registered_front": self.front,
            "connection_confirmed_front": self.front,
            "connected": True,
            "native_api_current": True,
            "bound_identity_current": True,
            "connection_generation": 7,
        }

    def get_request_counts(self):
        return dict(self.counts)

    def _query(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return name

    def query_account_result(self, **kwargs):
        return self._query("account", **kwargs)

    def query_positions_result(self, **kwargs):
        return self._query("positions", **kwargs)

    def query_orders_result(self, **kwargs):
        return self._query("orders", **kwargs)

    def query_trades_result(self, **kwargs):
        return self._query("trades", **kwargs)

    def query_instruments_result(self, **kwargs):
        return self._query("instruments", **kwargs)

    def query_instrument_margin_rate_result(self, instrument_id, **kwargs):
        return self._query("margin_rate", instrument_id=instrument_id, **kwargs)

    def query_instrument_commission_rate_result(self, instrument_id, **kwargs):
        return self._query("commission_rate", instrument_id=instrument_id, **kwargs)


class _FakeMdClient:
    instances = []
    behavior = "ready"

    def __init__(self, front, broker_id, user_id, password) -> None:
        assert (broker_id, user_id, password) == (
            "9999",
            "demo",
            SECRET_VALUES["password"],
        )
        self.front = front
        self.broker_id = broker_id
        self.user_id = user_id
        self.calls = []
        self.stopped = 0
        self._state_lock = threading.RLock()
        self._connected = False
        self._loggedin = False
        self.connection_generation = 12
        self._thread = None
        type(self).instances.append(self)

    def subscribe(self, instruments) -> None:
        self.calls.append(("subscribe", list(instruments)))

    def start(self, *, block: bool) -> None:
        assert block is False
        self.calls.append(("start", block))
        with self._state_lock:
            self._connected = True
            self._loggedin = type(self).behavior != "no_login"
        if type(self).behavior != "no_login":
            self.on_login(
                SimpleNamespace(
                    BrokerID=self.broker_id,
                    UserID=self.user_id,
                    TradingDay="20260923",
                )
            )
        if type(self).behavior not in {"no_ack", "no_login"}:
            instrument = "rb2610" if type(self).behavior == "wrong_instrument_ack" else "IF2612"
            error_id = 7 if type(self).behavior == "rejected_ack" else 0
            self.on_subscribe(
                SimpleNamespace(InstrumentID=instrument),
                SimpleNamespace(ErrorID=error_id),
            )
        if type(self).behavior in {"ready", "join_pending", "join_on_stop"}:
            self.on_tick(
                SimpleNamespace(
                    InstrumentID="IF2612", ExchangeID="CFFEX", LastPrice=3500.0, Volume=1
                )
            )
        if type(self).behavior in {"join_pending", "join_on_stop"}:
            self.join_release = threading.Event()
            self._thread = threading.Thread(target=self.join_release.wait, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self.calls.append(("stop",))
        self.stopped += 1
        if type(self).behavior == "join_on_stop":
            self.join_release.set()

    def stop_and_wait(self, *, timeout: float) -> _FakeNativeStopReceipt:
        self.stop()
        join_thread = self._thread
        if join_thread is not None:
            join_thread.join(timeout)
        thread_alive = bool(join_thread is not None and join_thread.is_alive())
        return _FakeNativeStopReceipt(
            connection_generation=self.connection_generation,
            join_required=join_thread is not None,
            join_completed=join_thread is not None and not thread_alive,
            native_released=not thread_alive,
            thread_alive=thread_alive,
            timed_out=thread_alive,
        )


class _FakeCertificateBuilder:
    def __init__(self, client, *, instrument_id, exchange_id, hedge_flag) -> None:
        assert isinstance(client, _FakeClient)
        assert (instrument_id, exchange_id, hedge_flag) == ("IF2612", "CFFEX", "1")
        self.names = []

    def add(self, result) -> None:
        self.names.append(result)

    def finish(self):
        assert tuple(self.names) == QUERY_NAMES
        query_digests = tuple(
            (name, hashlib.sha256(name.encode("ascii")).hexdigest()) for name in self.names
        )
        certificate_sha256 = hashlib.sha256(b"fake-native-certificate").hexdigest()
        public = {
            "schema": "ctp_native_query_certificate.v5",
            "complete": True,
            "atomic_snapshot": False,
            "execution_authorized": False,
            "query_digest": certificate_sha256,
            "certificate_sha256": certificate_sha256,
            "queries": [
                {
                    "request_type": name,
                    "records_sha256": digest,
                    "rate_exchange_scope": "exact" if name in ("margin_rate", "commission_rate") else None,
                }
                for name, digest in query_digests
            ],
        }
        return SimpleNamespace(
            query_digests=query_digests,
            certificate_sha256=certificate_sha256,
            as_public_dict=lambda: public,
        )


def _components():
    return _FakeClient, _FakeCertificateBuilder


@pytest.fixture(autouse=True)
def _use_private_fake_sdk_components(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch private seams; strict-origin behavior has dedicated coverage."""

    monkeypatch.setattr(readonly_runtime, "_default_sdk_components", _components)
    monkeypatch.setattr(readonly_runtime, "_MD_TICK_OBSERVATION_SECONDS", 0.005)

    def approved_fake_artifact(*, td_front: str, md_front: str) -> None:
        assert td_front.startswith("tcp://")
        assert md_front.startswith("tcp://")

    monkeypatch.setattr(
        readonly_runtime,
        "verify_ctp_sdk_artifact_provenance_for_fronts",
        approved_fake_artifact,
    )

    _FakeClient.instances.clear()
    _MD_CLIENT_LOADS.clear()
    _FakeMdClient.instances.clear()
    _FakeMdClient.behavior = "ready"

    def load_fake_md_client_type():
        _MD_CLIENT_LOADS.append(True)
        assert _FakeClient.instances, "the seven-query TraderClient pass must run first"
        trader = _FakeClient.instances[-1]
        assert len(trader.calls) == len(QUERY_NAMES)
        assert trader.stopped == 1, "the TraderClient must close before MdClient import"
        return _FakeMdClient

    monkeypatch.setattr(
        readonly_runtime, "_load_installed_md_client_type", load_fake_md_client_type
    )

    @contextmanager
    def installed_context(capability_modules):
        assert capability_modules == ("bt_api_base", "bt_api_ctp")
        yield

    monkeypatch.setattr(
        readonly_runtime,
        "trusted_installed_capability_import_context",
        installed_context,
    )


def _track_config_credentials(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    original = readonly_runtime.resolve_runtime_credentials

    def resolve(effective, registry, scope):
        calls.append(scope.secrets_ref)
        return original(effective, registry, scope)

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", resolve)


def _open(inputs, **changes):
    values = {
        "effective": inputs["effective"],
        "registry": inputs["registry"],
        "admission_registration": inputs["admission"],
        "credential_scope": inputs["scope"],
    }
    values.update(changes)
    return open_ctp_simnow_readonly_runtime(**values)


def _assert_secret_redacted(value: object) -> None:
    rendered = str(value)
    assert SECRET_VALUES["password"] not in rendered
    assert SECRET_VALUES["auth_code"] not in rendered


def test_public_composition_entry_has_no_caller_controlled_sdk_loader() -> None:
    parameters = inspect.signature(open_ctp_simnow_readonly_runtime).parameters

    assert "sdk_components_loader" not in parameters
    assert tuple(parameters) == (
        "effective",
        "registry",
        "admission_registration",
        "credential_scope",
        "connect_timeout",
        "query_timeout",
        "selected_config_index",
    )


def test_composition_uses_sealed_admission_then_credential_seal_then_zero_write_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    store_calls = []
    _FakeClient.instances.clear()
    _track_config_credentials(monkeypatch, store_calls)

    result = _open(inputs)

    assert store_calls == ["config_yaml"]
    assert len(_FakeClient.instances) == 1
    client = _FakeClient.instances[0]
    assert client.started is True
    assert client.stopped == 1
    assert [name for name, _ in client.calls] == list(QUERY_NAMES)
    assert client.counts == dict.fromkeys(WRITE_KEYS, 0)
    assert _MD_CLIENT_LOADS == [True]
    assert len(_FakeMdClient.instances) == 1
    md_client = _FakeMdClient.instances[0]
    assert md_client.calls == [
        ("subscribe", ["IF2612"]),
        ("start", False),
        ("stop",),
    ]
    assert md_client.stopped == 1
    assert result.credentials_resolved is True
    assert result.provider_connected is False
    assert result.account_identity_verified is False
    assert result.preflight_authorized is False
    assert result.execution_authorized is False
    assert result.external_writes_authorized is False
    assert result.order_submission_authorized is False
    assert result.cancellation_authorized is False
    assert result.settlement_authorized is False
    assert result.arming_authorized is False
    assert result.external_write_requests == 0
    assert result.observation.environment == "simnow"
    assert result.observation.native_certificate_provenance == "UNVERIFIED_DIGEST_ONLY"
    assert result.market_data_observation.instrument_id == "IF2612"
    assert (
        result.market_data_observation.md_front_sha256
        == hashlib.sha256(inputs["admission"].md_front.encode("utf-8")).hexdigest()
    )
    assert result.market_data_observation.market_login_ready is True
    assert result.market_data_observation.subscription_acknowledged is True
    assert result.market_data_observation.first_tick_observed is True
    assert result.market_data_observation.tick_observation_count == 1
    assert result.market_data_observation.tick_binding is not None
    assert result.market_data_observation.tick_binding.exchange_id == "CFFEX"
    assert result.market_data_observation.probe_session_closed is True
    assert result.market_data_observation.client_stop_returned is True
    assert result.market_data_observation.native_join_pending is False
    assert result.market_data_trading_writes == 0
    assert result.market_data_observation.trading_writes == 0
    assert result.market_data_observation.settlement_writes == 0
    public = result.as_public_dict()
    assert "credentials" not in public
    _assert_secret_redacted(public)
    _assert_secret_redacted(repr(result))
    assert ACCOUNT_FINGERPRINT not in repr(result)
    with pytest.raises(TypeError, match="not account"):
        bool(result)


def test_composition_uses_exact_selected_nonfirst_pair_from_sealed_candidates(
    tmp_path: Path,
) -> None:
    alternate_pair = ("tcp://192.0.2.72:42102", "tcp://192.0.2.71:42101")
    configured_pairs = ((MD_FRONT, TD_FRONT), alternate_pair)
    inputs = _inputs(
        tmp_path / "runtime",
        front_pairs=configured_pairs,
        selected_pair=alternate_pair,
    )

    result = _open(inputs, selected_config_index=1)

    assert _FakeClient.instances[0].front == alternate_pair[1]
    assert _FakeMdClient.instances[0].front == alternate_pair[0]
    assert (
        result.market_data_observation.md_front_sha256
        == hashlib.sha256(alternate_pair[0].encode("utf-8")).hexdigest()
    )
    public = result.as_public_dict()
    assert "front_selection_audit" not in public
    audit = result.as_front_selection_audit_dict()
    assert audit["schema_version"] == 1
    assert audit["selected_config_index"] == 1
    assert audit["candidate_count"] == 2
    assert len(audit["selected_front_pair_sha256"]) == 64
    assert alternate_pair[0] not in str(audit)
    assert alternate_pair[1] not in str(audit)


@pytest.mark.parametrize("selected_config_index", (True, -1, 2, 8))
def test_invalid_selected_config_index_rejects_before_credentials_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected_config_index: object,
) -> None:
    configured_pairs = (
        (MD_FRONT, TD_FRONT),
        ("tcp://192.0.2.82:42202", "tcp://192.0.2.81:42201"),
    )
    inputs = _inputs(tmp_path / "runtime", front_pairs=configured_pairs)
    credential_reads = []

    def reject_if_called(*args, **kwargs):
        del args, kwargs
        credential_reads.append(True)
        raise AssertionError("invalid selected index must reject before credentials")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", reject_if_called)
    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs, selected_config_index=selected_config_index)

    assert caught.value.reason == "configured_front_selection_invalid"
    assert credential_reads == []
    assert _FakeClient.instances == []
    assert _FakeMdClient.instances == []


def test_selected_config_index_must_identify_the_admitted_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_pairs = (
        (MD_FRONT, TD_FRONT),
        ("tcp://192.0.2.82:42202", "tcp://192.0.2.81:42201"),
    )
    inputs = _inputs(
        tmp_path / "runtime",
        front_pairs=configured_pairs,
        selected_pair=configured_pairs[1],
    )
    credential_reads = []

    def reject_if_called(*args, **kwargs):
        del args, kwargs
        credential_reads.append(True)
        raise AssertionError("mismatched selected pair must reject before credentials")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", reject_if_called)
    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs, selected_config_index=0)

    assert caught.value.reason == "configured_front_selection_mismatch"
    assert credential_reads == []
    assert _FakeClient.instances == []
    assert _FakeMdClient.instances == []


def test_unconfigured_admission_pair_rejects_before_credentials_or_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_pairs = (
        (MD_FRONT, TD_FRONT),
        ("tcp://192.0.2.82:42202", "tcp://192.0.2.81:42201"),
    )
    inputs = _inputs(tmp_path / "runtime", front_pairs=configured_pairs)
    outsider = replace(
        inputs["admission"],
        td_front="tcp://192.0.2.91:42301",
        md_front="tcp://192.0.2.92:42302",
    )
    credential_reads = []

    def reject_if_called(*args, **kwargs):
        del args, kwargs
        credential_reads.append(True)
        raise AssertionError("unconfigured pair must reject before credential access")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", reject_if_called)
    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs, admission_registration=outsider)

    assert caught.value.reason == "credential_scope_mismatch"
    assert credential_reads == []
    assert _FakeClient.instances == []
    assert _FakeMdClient.instances == []


@pytest.mark.parametrize(
    ("behavior", "expected_reason"),
    (
        ("no_login", "market_login_timeout"),
        ("no_ack", "subscription_ack_timeout"),
        ("rejected_ack", "market_subscription_rejected"),
        ("wrong_instrument_ack", "subscription_ack_timeout"),
    ),
)
def test_market_login_and_exact_subscription_are_required(
    tmp_path: Path,
    behavior: str,
    expected_reason: str,
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    _FakeMdClient.behavior = behavior

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs, connect_timeout=0.02)

    assert caught.value.reason == expected_reason
    assert _MD_CLIENT_LOADS == [True]


def test_private_preflight_rejects_ack_without_matching_tick(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path / "runtime")
    _FakeMdClient.behavior = "no_tick"

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs, connect_timeout=0.02)

    assert caught.value.reason == "market_tick_not_observed"
    assert _FakeMdClient.instances[-1].stopped == 1
    assert _FakeClient.instances[-1].stopped == 1
    assert _FakeClient.instances[-1].counts == dict.fromkeys(WRITE_KEYS, 0)
    assert _FakeMdClient.instances[-1].stopped == 1
    assert _FakeMdClient.instances[-1].calls[-1] == ("stop",)
    _assert_secret_redacted(caught.value)


def test_native_join_pending_fails_preflight_and_keeps_lease_after_join_exits(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    _FakeMdClient.behavior = "join_pending"

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs)

    assert caught.value.reason == "market_client_stop_failed"
    client = _FakeMdClient.instances[-1]
    assert client.stopped == 1
    assert client._thread is not None and client._thread.is_alive()
    client.join_release.set()
    client._thread.join(1.0)
    account_key = market_readonly._account_lock_key(ACCOUNT_FINGERPRINT)
    process_lock = market_readonly._PROCESS_LOCKS[account_key]
    assert not client._thread.is_alive()
    assert process_lock.locked() is True


def test_join_that_finishes_within_bounded_close_grace_allows_preflight(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    _FakeMdClient.behavior = "join_on_stop"

    result = _open(inputs, connect_timeout=1.0)

    assert result.market_data_observation.market_path_ready is True
    assert result.market_data_observation.client_stop_returned is True
    assert result.market_data_observation.native_join_pending is False
    assert _FakeMdClient.instances[-1]._thread is not None
    assert not _FakeMdClient.instances[-1]._thread.is_alive()


def test_credential_seal_is_rechecked_for_each_sdk_credential_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    store_calls = []
    seal_calls = []
    _track_config_credentials(monkeypatch, store_calls)
    original = readonly_runtime.require_resolved_runtime_credentials_seal

    def tracking_seal(*args, **kwargs):
        seal_calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        readonly_runtime, "require_resolved_runtime_credentials_seal", tracking_seal
    )

    result = _open(inputs)

    assert result.execution_authorized is False
    # One composition gate, five TraderClient fields, and three MdClient
    # fields. Each native client access revalidates the same credential seal.
    assert len(seal_calls) == 1 + len(CTP_AUTHENTICATION_CREDENTIAL_KEYS) + 3
    assert store_calls == ["config_yaml"]


def test_registration_mutation_between_credential_reads_rejects_before_sdk_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    store_calls = []
    seal_calls = 0
    _FakeClient.instances.clear()
    _track_config_credentials(monkeypatch, store_calls)
    original = readonly_runtime.require_resolved_runtime_credentials_seal

    def mutate_registration_after_first_sdk_credential(*args, **kwargs):
        nonlocal seal_calls
        result = original(*args, **kwargs)
        seal_calls += 1
        # Call 1 is the composition gate.  Call 2 validates broker_id; mutate
        # afterward so the next SDK credential read must rebind the current
        # registration before it can return user_id.
        if seal_calls == 2:
            object.__setattr__(
                inputs["registration"],
                "allowed_secrets_refs",
                ("runtime_secrets",),
            )
        return result

    monkeypatch.setattr(
        readonly_runtime,
        "require_resolved_runtime_credentials_seal",
        mutate_registration_after_first_sdk_credential,
    )

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs)

    assert caught.value.reason == "read_only_observation_rejected"
    assert seal_calls == 2
    assert store_calls == ["config_yaml"]
    assert _FakeClient.instances == []
    _assert_secret_redacted(caught.value)


def test_invalid_admission_is_rejected_before_secret_or_sdk_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    object.__setattr__(inputs["registration"], "allowed_parameter_keys", ("unexpected",))
    secret_touched = False
    sdk_touched = False

    def unexpected_secret(*args, **kwargs):
        del args, kwargs
        nonlocal secret_touched
        secret_touched = True
        raise AssertionError("credentials must not be resolved")

    def unexpected_sdk():
        nonlocal sdk_touched
        sdk_touched = True
        raise AssertionError("SDK must not load")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", unexpected_secret)

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        monkeypatch.setattr(readonly_runtime, "_default_sdk_components", unexpected_sdk)
        _open(inputs)

    assert caught.value.reason == "runtime_admission_rejected"
    assert secret_touched is False
    assert sdk_touched is False
    assert _MD_CLIENT_LOADS == []


def test_mutated_sealed_config_rejects_before_credentials_or_md_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    object.__setattr__(inputs["effective"].config.ctp_simnow, "md_front", "tcp://127.0.0.1:19191")
    secret_touched = False

    def unexpected_secret(*args, **kwargs):
        del args, kwargs
        nonlocal secret_touched
        secret_touched = True
        raise AssertionError("a mutated sealed config must not read credentials")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", unexpected_secret)

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs)

    assert caught.value.reason == "runtime_admission_rejected"
    assert secret_touched is False
    assert _MD_CLIENT_LOADS == []


def test_ctp_scope_mismatch_is_rejected_before_secret_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    mismatched_scope = replace(inputs["scope"], account_fingerprint_sha256="a" * 64)
    secret_touched = False

    def unexpected_secret(*args, **kwargs):
        del args, kwargs
        nonlocal secret_touched
        secret_touched = True
        raise AssertionError("credentials must not be resolved")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", unexpected_secret)

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs, credential_scope=mismatched_scope)

    assert caught.value.reason == "credential_scope_mismatch"
    assert secret_touched is False


def test_forged_resolution_is_rejected_before_factory_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    forged = ResolvedRuntimeCredentials(
        scope=inputs["scope"],
        source="config_yaml",
        _values=dict(SECRET_VALUES),
    )
    factory_touched = False

    def forged_resolver(*args, **kwargs):
        del args, kwargs
        return forged

    def unexpected_factory(*args, **kwargs):
        del args, kwargs
        nonlocal factory_touched
        factory_touched = True
        raise AssertionError("factory must not be constructed")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", forged_resolver)
    monkeypatch.setattr(readonly_runtime, "CtpSdkReadOnlySessionFactory", unexpected_factory)

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs)

    assert caught.value.reason == "credential_resolution_rejected"
    assert factory_touched is False
    _assert_secret_redacted(caught.value)


def test_installed_capability_origin_fence_is_entered_before_credential_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    events = []
    _FakeClient.instances.clear()

    original_resolver = readonly_runtime.resolve_runtime_credentials

    def resolve_credentials(effective, registry, scope):
        events.append("credential-resolution")
        return original_resolver(effective, registry, scope)

    @contextmanager
    def trusted_context(capability_modules):
        assert capability_modules == ("bt_api_base", "bt_api_ctp")
        events.append("context-enter")
        yield
        events.append("context-exit")

    def verified_artifact(*, td_front: str, md_front: str) -> None:
        assert td_front == inputs["admission"].td_front
        assert md_front == inputs["admission"].md_front
        events.append("artifact-provenance")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", resolve_credentials)
    monkeypatch.setattr(
        readonly_runtime,
        "trusted_installed_capability_import_context",
        trusted_context,
    )
    monkeypatch.setattr(
        readonly_runtime,
        "verify_ctp_sdk_artifact_provenance_for_fronts",
        verified_artifact,
    )
    original_md_loader = readonly_runtime._load_installed_md_client_type

    def load_market_client():
        events.append("market-client-import")
        return original_md_loader()

    monkeypatch.setattr(
        readonly_runtime,
        "_load_installed_md_client_type",
        load_market_client,
    )

    result = _open(inputs)

    assert result.execution_authorized is False
    assert events[0:3] == [
        "context-enter",
        "artifact-provenance",
        "credential-resolution",
    ]
    assert events[-2:] == ["market-client-import", "context-exit"]
    assert events[-1] == "context-exit"


def test_missing_code_owned_sdk_pin_is_rejected_before_secret_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    secret_touched = False
    monkeypatch.setattr(ctp_artifact_provenance, "CTP_SDK_ARTIFACT_PINS", {})

    def unexpected_secret(*args, **kwargs):
        del args, kwargs
        nonlocal secret_touched
        secret_touched = True
        raise AssertionError("credentials must not be resolved without reviewed SDK pins")

    monkeypatch.setattr(
        readonly_runtime,
        "verify_ctp_sdk_artifact_provenance_for_fronts",
        ctp_artifact_provenance.verify_ctp_sdk_artifact_provenance_for_fronts,
    )
    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", unexpected_secret)

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs)

    assert caught.value.reason == "capability_provenance_rejected"
    assert secret_touched is False
    assert _MD_CLIENT_LOADS == []
    assert ctp_artifact_provenance.CTP_SDK_ARTIFACT_PINS == {}
    _assert_secret_redacted(caught.value)


def test_installed_capability_origin_rejection_precedes_secret_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    secret_touched = False
    _FakeClient.instances.clear()

    def unexpected_secret(*args, **kwargs):
        del args, kwargs
        nonlocal secret_touched
        secret_touched = True
        raise AssertionError("credentials must not be resolved")

    @contextmanager
    def rejected_context(capability_modules):
        assert capability_modules == ("bt_api_base", "bt_api_ctp")
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            SECRET_VALUES["password"],
            reason="capability_origin_mismatch",
        )
        yield

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", unexpected_secret)
    monkeypatch.setattr(
        readonly_runtime,
        "trusted_installed_capability_import_context",
        rejected_context,
    )

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs)

    assert caught.value.reason == "capability_origin_rejected"
    assert secret_touched is False
    assert _FakeClient.instances == []
    _assert_secret_redacted(caught.value)


def test_absolute_pythonpath_capability_is_rejected_before_secret_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    purelib = tmp_path / "interpreter" / "site-packages"
    injected_root = tmp_path / "absolute-pythonpath"
    purelib.mkdir(parents=True)
    _write_installed_base_package(purelib)
    injected_package = _write_capability_package(injected_root, "injected")
    sentinel = tmp_path / "injected-capability-executed"
    (injected_package / "__init__.py").write_text(
        "from pathlib import Path\n"
        "Path({0!r}).write_text('executed', encoding='utf-8')\n".format(str(sentinel)),
        encoding="utf-8",
    )
    _use_strict_installed_capability_context(monkeypatch, purelib)
    monkeypatch.setattr(sys, "path", [str(injected_root)])
    secret_touched = False
    _FakeClient.instances.clear()

    def unexpected_secret(*args, **kwargs):
        del args, kwargs
        nonlocal secret_touched
        secret_touched = True
        raise AssertionError("credentials must not be resolved")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", unexpected_secret)

    with _isolated_capability_modules(), pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        _open(inputs)

    assert caught.value.reason == "capability_origin_rejected"
    assert secret_touched is False
    assert _FakeClient.instances == []
    assert not sentinel.exists()


def test_cached_source_capability_is_rejected_before_secret_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    purelib = tmp_path / "interpreter" / "site-packages"
    source_root = tmp_path / "checked-out-source"
    _write_installed_base_package(purelib)
    _write_capability_package(purelib, "installed")
    _write_capability_package(source_root, "cached-source")
    _use_strict_installed_capability_context(monkeypatch, purelib)
    monkeypatch.setattr(sys, "path", [str(source_root), str(purelib)])
    secret_touched = False
    _FakeClient.instances.clear()

    def unexpected_secret(*args, **kwargs):
        del args, kwargs
        nonlocal secret_touched
        secret_touched = True
        raise AssertionError("credentials must not be resolved")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", unexpected_secret)

    with _isolated_capability_modules():
        cached = importlib.import_module("bt_api_ctp")
        assert cached.STATUS == "cached-source"

        with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
            _open(inputs)

    assert caught.value.reason == "capability_origin_rejected"
    assert secret_touched is False
    assert _FakeClient.instances == []


def test_sdk_error_is_redacted_and_client_is_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "runtime")
    store_calls = []
    _FakeClient.instances.clear()
    _FakeClient.fail_start = True
    _track_config_credentials(monkeypatch, store_calls)
    try:
        with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
            _open(inputs)
    finally:
        _FakeClient.fail_start = False

    assert caught.value.reason == "read_only_observation_rejected"
    assert store_calls == ["config_yaml"]
    assert len(_FakeClient.instances) == 1
    assert _FakeClient.instances[0].stopped == 1
    _assert_secret_redacted(caught.value)


def test_composition_import_does_not_load_a_ctp_sdk_or_provider_module() -> None:
    script = """
import sys
import backtrader_runtime.ctp_simnow_readonly_runtime
assert not any(name == item or name.startswith(item + '.') for item in ('bt_api', 'bt_api_py', 'bt_api_ctp') for name in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
