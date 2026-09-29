"""Fake-only integration tests for the unregistered I9 callback composition."""

from __future__ import annotations

import base64
import importlib
import importlib.metadata
import math
import queue
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtrader_runtime.ctp_i9_account_session_candidate import (
    CtpI9AccountSessionCandidate,
    CtpI9AccountSessionCandidateError,
    CtpI9NativeLifecycleSupervisor,
    _claimed_native_payload,
    _candidate_package_version,
    _trusted_candidate_types,
)


class _BoundedAbort(BaseException):
    """A catchable stand-in for process-control exceptions in bounded fake paths."""


class _FakeCtpNativeField:
    """Tiny SWIG-boundary stand-in with exact CTP scalar types and int range."""

    _TEXT_FIELDS = frozenset(
        {
            "BrokerID",
            "InvestorID",
            "UserID",
            "InstrumentID",
            "OrderRef",
            "Direction",
            "CombOffsetFlag",
            "CombHedgeFlag",
            "OrderPriceType",
            "TimeCondition",
            "ExchangeID",
            "OrderSysID",
            "ActionFlag",
            "TradingDay",
            "OrderStatus",
            "OrderSubmitStatus",
            "TradeID",
            "TradeDate",
            "TradeTime",
            "OffsetFlag",
            "HedgeFlag",
            "TradeSource",
        }
    )
    _INTEGER_FIELDS = frozenset(
        {
            "VolumeTotalOriginal",
            "FrontID",
            "SessionID",
            "VolumeChange",
            "RequestID",
            "OrderActionRef",
            "NotifySequence",
            "SequenceNo",
            "BrokerOrderSeq",
            "VolumeTraded",
            "VolumeTotal",
            "Volume",
        }
    )
    _FLOAT_FIELDS = frozenset({"LimitPrice", "Price"})
    _INT_MAX = 2_147_483_647

    def __init__(self, **values):
        for name, value in values.items():
            setattr(self, name, value)

    def __setattr__(self, name, value):
        if name in self._TEXT_FIELDS:
            if type(value) is not str:
                raise TypeError("fake CTP text setter requires exact str")
        elif name in self._INTEGER_FIELDS:
            if type(value) is not int:
                raise TypeError("fake CTP integer setter requires exact int")
            if value < 0 or value > self._INT_MAX:
                raise ValueError("fake CTP integer setter is outside signed int range")
            if name in {"RequestID", "OrderActionRef", "FrontID", "SessionID"} and value == 0:
                raise ValueError("fake CTP identity integer must be positive")
        elif name in self._FLOAT_FIELDS:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise TypeError("fake CTP floating setter requires a finite scalar")
        else:
            raise AttributeError("fake CTP field is not in the reviewed setter inventory")
        object.__setattr__(self, name, value)


@pytest.mark.parametrize(
    ("field_name", "value", "error_type"),
    [
        ("OrderActionRef", "23", TypeError),
        ("OrderActionRef", True, TypeError),
        ("OrderActionRef", 0, ValueError),
        ("OrderActionRef", 2_147_483_648, ValueError),
        ("RequestID", False, TypeError),
        ("RequestID", -1, ValueError),
        ("RequestID", 2_147_483_648, ValueError),
    ],
)
def test_fake_native_integer_fields_reject_coercion_and_out_of_range(field_name, value, error_type):
    field = _FakeCtpNativeField()
    with pytest.raises(error_type):
        setattr(field, field_name, value)


class _UnusedAuthorityVerifier:
    def verify_action(self, *_args, **_kwargs):
        raise AssertionError("start-only test must not claim a dispatch")


class _FakeLifecycleSupervisor(CtpI9NativeLifecycleSupervisor):
    def __init__(self):
        self.starts = []
        self.stops = []

    def start_client(self, client):
        self.starts.append(client)
        client.start()

    def stop_client(self, client):
        self.stops.append(client)
        client.stop()


class _FakeTraderApi:
    def __init__(self):
        self.spi = None
        self.join_started = False
        self.calls = []
        self.order_insert_result = 0
        self.order_action_result = 0
        self.insert_callback_timing = "before"
        self.insert_exception = False
        self.insert_base_exception = None
        self.pending_callback = None
        self.after_routeable_callback = None
        self.order_action_calls = []
        self.order_action_field_request_ids = []

    def RegisterSpi(self, spi):
        self.spi = spi

    def SubscribePrivateTopic(self, _topic):
        return None

    def SubscribePublicTopic(self, _topic):
        return None

    def RegisterFront(self, _front):
        return None

    def Init(self):
        self.spi.OnFrontConnected()

    def Join(self):
        self.join_started = True
        return 0

    def Release(self):
        self.calls.append("Release")

    def ReqAuthenticate(self, field, request_id):
        self.calls.append(("ReqAuthenticate", request_id))
        self.spi.OnRspAuthenticate(
            SimpleNamespace(BrokerID=field.BrokerID, UserID=field.UserID),
            SimpleNamespace(ErrorID=0, ErrorMsg=""),
            request_id,
            True,
        )
        return 0

    def ReqUserLogin(self, field, request_id):
        self.calls.append(("ReqUserLogin", request_id))
        self.spi.OnRspUserLogin(
            SimpleNamespace(
                BrokerID=field.BrokerID,
                UserID=field.UserID,
                TradingDay="20260926",
                FrontID=7,
                SessionID=19,
                MaxOrderRef="17",
            ),
            SimpleNamespace(ErrorID=0, ErrorMsg=""),
            request_id,
            True,
        )
        return 0

    def _emit_order_insert(self, field, request_id):
        values = dict(vars(field))
        values["RequestID"] = request_id
        self.spi.OnRspOrderInsert(
            SimpleNamespace(**values),
            SimpleNamespace(ErrorID=0, ErrorMsg=""),
            request_id,
            True,
        )
        if self.after_routeable_callback is not None:
            self.after_routeable_callback("OnRspOrderInsert")

    def ReqOrderInsert(self, field, request_id):
        self.calls.append(("ReqOrderInsert", field.OrderRef, request_id))
        if self.insert_callback_timing == "before":
            self._emit_order_insert(field, request_id)
        elif self.insert_callback_timing == "after":
            self.pending_callback = lambda: self._emit_order_insert(field, request_id)
        if self.insert_exception:
            raise RuntimeError("fake-only native exception text")
        if self.insert_base_exception is not None:
            raise self.insert_base_exception
        return self.order_insert_result

    def ReqOrderAction(self, field, request_id):
        self.calls.append(("ReqOrderAction", field.OrderRef, request_id))
        self.order_action_calls.append((request_id, field.OrderActionRef))
        self.order_action_field_request_ids.append(field.RequestID)
        self.spi.OnRspOrderAction(
            SimpleNamespace(**vars(field)),
            SimpleNamespace(ErrorID=0, ErrorMsg=""),
            request_id,
            True,
        )
        if self.after_routeable_callback is not None:
            self.after_routeable_callback("OnRspOrderAction")
        return self.order_action_result


class _FakeTraderApiFactory:
    instances = []

    @classmethod
    def CreateFtdcTraderApi(cls, _flow_path):
        api = _FakeTraderApi()
        cls.instances.append(api)
        return api


def _candidate_types_or_skip():
    types = _trusted_candidate_types()
    if types is None:
        pytest.skip("reviewed local execution and CTP source candidates are unavailable")
    return types


@pytest.mark.parametrize("package_name", ["bt_api_execution", "bt_api_ctp"])
def test_candidate_package_version_reads_installed_wheel_record(package_name):
    try:
        module = importlib.import_module(package_name)
        distribution = importlib.metadata.distribution(package_name)
        expected_path = Path(
            distribution.locate_file(package_name + "/__init__.py")
        ).resolve(strict=True)
        actual_path = Path(module.__file__).resolve(strict=True)
    except (ImportError, importlib.metadata.PackageNotFoundError, OSError):
        pytest.skip("installed wheel package is unavailable")
    if actual_path != expected_path:
        pytest.skip("package import resolves to a source checkout, not the installed wheel")
    assert _candidate_package_version(package_name, module) == distribution.version


def test_candidate_package_version_rejects_same_name_shadow(tmp_path):
    shadow_init = tmp_path / "shadow" / "bt_api_execution" / "__init__.py"
    shadow_init.parent.mkdir(parents=True)
    shadow_init.write_text("__version__ = '0.2.0'\n", encoding="utf-8")
    shadow = SimpleNamespace(
        __name__="bt_api_execution",
        __file__=str(shadow_init),
        __spec__=SimpleNamespace(origin=str(shadow_init)),
    )
    assert _candidate_package_version("bt_api_execution", shadow) is None


class _FakeWheelRecordEntry:
    def __init__(self, hash_value):
        self.hash = SimpleNamespace(mode="sha256", value=hash_value)

    def as_posix(self):
        return "bt_api_execution/__init__.py"

    def __str__(self):
        return self.as_posix()


def test_candidate_package_version_rejects_record_hash_mismatch(tmp_path, monkeypatch):
    root = tmp_path / "site-packages"
    package_init = root / "bt_api_execution" / "__init__.py"
    package_init.parent.mkdir(parents=True)
    package_init.write_text("__version__ = '0.2.0'\n", encoding="utf-8")
    entry = _FakeWheelRecordEntry("0" * 43)

    class Distribution:
        version = "0.2.0"
        files = (entry,)

        @staticmethod
        def locate_file(relative):
            return root / str(relative)

    monkeypatch.setattr(importlib.metadata, "distribution", lambda _name: Distribution())
    installed_lookalike = SimpleNamespace(
        __name__="bt_api_execution",
        __file__=str(package_init),
        __spec__=SimpleNamespace(origin=str(package_init)),
    )
    assert _candidate_package_version("bt_api_execution", installed_lookalike) is None


def test_candidate_package_version_accepts_matching_wheel_record(tmp_path, monkeypatch):
    root = tmp_path / "site-packages"
    package_init = root / "bt_api_execution" / "__init__.py"
    package_init.parent.mkdir(parents=True)
    package_init.write_text("__version__ = '0.2.0'\n", encoding="utf-8")
    digest = base64.urlsafe_b64encode(sha256(package_init.read_bytes()).digest()).decode("ascii")
    entry = _FakeWheelRecordEntry(digest.rstrip("="))

    class Distribution:
        version = "0.2.0"
        files = (entry,)

        @staticmethod
        def locate_file(relative):
            return root / str(relative)

    monkeypatch.setattr(importlib.metadata, "distribution", lambda _name: Distribution())
    installed = SimpleNamespace(
        __name__="bt_api_execution",
        __file__=str(package_init),
        __spec__=SimpleNamespace(origin=str(package_init)),
    )
    assert _candidate_package_version("bt_api_execution", installed) == "0.2.0"


def _fake_native_call_admission(_owner, _binding, _verified):
    """Explicit fake-only admission hook for direct candidate dispatch tests."""


def test_optional_logical_request_id_must_match_the_store_binding():
    _candidate_types_or_skip()
    from bt_api_execution.contracts import canonical_json, payload_sha256

    class FakeBinding:
        def __init__(
            self, logical_payload, native_request_id, *, operation="SUBMIT", action_ref=None
        ):
            logical_json = canonical_json(logical_payload)
            logical_digest = payload_sha256(logical_payload)
            native_payload = dict(logical_payload)
            if operation == "CANCEL":
                native_payload["OrderActionRef"] = action_ref
            self.operation = operation
            self.request_payload_json = logical_json
            self.request_payload_sha256 = logical_digest
            self.native_request_payload_json = canonical_json(native_payload)
            self.native_request_payload_sha256 = payload_sha256(native_payload)
            self.native_request_id = native_request_id
            self.native_action_ref = action_ref

        def to_payload(self):
            return {
                "binding_type": "ctp_managed_native_call_binding.v2",
                "operation": self.operation,
                "request_payload_json": self.request_payload_json,
                "request_payload_sha256": self.request_payload_sha256,
                "native_request_payload_json": self.native_request_payload_json,
                "native_request_payload_sha256": self.native_request_payload_sha256,
                "native_request_id": self.native_request_id,
                "native_action_ref": self.native_action_ref,
            }

    matched = FakeBinding({"InstrumentID": "rb2710", "RequestID": 53}, 53)
    assert dict(_claimed_native_payload(matched, FakeBinding)) == {
        "InstrumentID": "rb2710",
        "RequestID": 53,
    }
    absent = FakeBinding({"InstrumentID": "rb2710"}, 53)
    assert dict(_claimed_native_payload(absent, FakeBinding)) == {"InstrumentID": "rb2710"}
    cancel_matched = FakeBinding(
        {"InstrumentID": "rb2710", "RequestID": 53},
        53,
        operation="CANCEL",
        action_ref=1,
    )
    assert dict(_claimed_native_payload(cancel_matched, FakeBinding)) == {
        "InstrumentID": "rb2710",
        "RequestID": 53,
        "OrderActionRef": 1,
    }
    for invalid_request_id in (54, True, "53", None):
        invalid = FakeBinding({"InstrumentID": "rb2710", "RequestID": invalid_request_id}, 53)
        with pytest.raises(CtpI9AccountSessionCandidateError):
            _claimed_native_payload(invalid, FakeBinding)


def test_owner_precedes_client_construction_and_fake_login_binds_same_store(tmp_path, monkeypatch):
    types = _candidate_types_or_skip()
    execution_scope, store_type = types[:2]
    worker_module = importlib.import_module("bt_api_execution.ctp_single_worker_candidate")
    client_module = importlib.import_module("bt_api_ctp.ctp.client")

    class _Authority:
        def verify_action(self, *_args, **_kwargs):
            raise AssertionError("no dispatch expected")

    scope = execution_scope(
        "CTP",
        "simulation",
        "acct.i9.session.composition",
        "strategy.session.composition",
        "20260926",
    )
    store = store_type(tmp_path / "ctp-i9-session.sqlite3")
    lease = store.acquire_or_renew_lease(scope, "fake-session-composition-owner")
    worker = worker_module.CtpManagedSingleWorkerCandidate(store, scope, lease, _Authority())
    supervisor = _FakeLifecycleSupervisor()

    monkeypatch.setattr(client_module, "_check_native_module", lambda: None)
    monkeypatch.setattr(client_module, "_flow_dir", lambda _name: "fake-flow")
    monkeypatch.setattr(client_module, "_register_ctp_native_api", lambda _api: None)
    monkeypatch.setattr(client_module, "CThostFtdcTraderApi", _FakeTraderApiFactory)
    _FakeTraderApiFactory.instances = []
    factory_observations = []

    def client_factory():
        owners = store._connection.execute(
            "SELECT owner_state FROM ctp_dispatch_callback_session_owners WHERE account_key = ?",
            (scope.account_key,),
        ).fetchall()
        factory_observations.append(tuple(row[0] for row in owners))
        return client_module.TraderClient(
            "tcp://127.0.0.1:1", "9999", "fake-user", "fake-test-value"
        )

    candidate = CtpI9AccountSessionCandidate(
        scope=scope,
        store=store,
        writer_lease=lease,
        worker=worker,
        client_factory=client_factory,
        lifecycle_supervisor=supervisor,
        native_field_factory=lambda _operation, _payload: None,
        callback_verifier=object(),
        trade_fact_verifier=object(),
    )
    try:
        client = candidate.start()
        assert factory_observations == [("PREPARED",)]
        assert supervisor.starts == [client]
        assert client._callback_ingress.phase == "ACTIVE"
        assert (
            candidate.active_session
            is store._active_ctp_callback_sessions[candidate.owner_handle.owner_intent_id]
        )
        assert candidate.active_session.owner_intent_id == candidate.owner_handle.owner_intent_id
        callback_names = tuple(
            row[0]
            for row in store._connection.execute(
                "SELECT callback_name FROM ctp_dispatch_callback_ingress "
                "WHERE owner_intent_id = ? ORDER BY source_sequence",
                (candidate.owner_handle.owner_intent_id,),
            ).fetchall()
        )
        assert callback_names == (
            "OnFrontConnected",
            "OnRspAuthenticate",
            "OnRspUserLogin",
        )
        api = _FakeTraderApiFactory.instances[-1]
        assert api.join_started
        assert api.calls == [("ReqAuthenticate", 1), ("ReqUserLogin", 2)]
    finally:
        candidate.stop()
        store.close()
    assert supervisor.stops


def _source_candidate_fixture(
    tmp_path,
    monkeypatch,
    *,
    start=True,
    environment="simulation",
    authority_verifier=None,
    native_call_admission=None,
):
    types = _candidate_types_or_skip()
    execution_scope, store_type = types[:2]
    from bt_api_execution.contracts import payload_sha256
    from bt_api_execution.ctp_single_worker_candidate import (
        CtpManagedPreparedDispatch,
        CtpManagedSingleWorkerCandidate,
        stable_managed_command_id,
    )
    from bt_api_execution.store import (
        CtpDispatchAuthority,
        CtpOrderRefLegacyMapping,
        CtpOrderRefSeedProof,
        CtpVerifiedCallbackEvidence,
        CtpVerifiedTradeFactEvidence,
    )

    client_module = importlib.import_module("bt_api_ctp.ctp.client")
    scope = execution_scope(
        "CTP", environment, "acct.i9.dispatch.fake", "strategy.i9.dispatch.fake", "20260926"
    )
    store = store_type(tmp_path / "ctp-i9-dispatch.sqlite3")
    lease = store.acquire_or_renew_lease(scope, "fake-i9-dispatch-owner", ttl_ns=60_000_000_000)

    class Authority:
        def verify_action(self, command, *, now_ns):
            return CtpDispatchAuthority(
                authority_type="ctp_dispatch_authority.v1",
                command_binding_sha256=command.authority_binding_sha256,
                approval_use_id=command.approval_use_id,
                approval_digest=command.approval_digest,
                source_digest_sha256=sha256(b"fake source only").hexdigest(),
                verifier_id="fake-i9-authority",
                verified_at_ns=now_ns,
                expires_at_ns=now_ns + 5_000_000_000,
            )

    class CallbackVerifier:
        def verify_callback(self, _command, callback, callback_payload, *, now_ns):
            projection_state = "ACKNOWLEDGED"
            if callback_payload.get("source_callback") == "OnRtnOrder":
                native_fields = callback_payload.get("native_fields", {})
                status = native_fields.get("OrderStatus")
                traded = native_fields.get("VolumeTraded")
                remaining = native_fields.get("VolumeTotal")
                if status == "2" and traded == 2 and remaining == 3:
                    projection_state = "PARTIALLY_FILLED"
                elif status == "5" and traded == 2 and remaining == 3:
                    projection_state = "CANCELLED"
                else:
                    raise AssertionError("fake order callback has an unreviewed status/quantity")
            return CtpVerifiedCallbackEvidence(
                evidence_type="ctp_verified_callback.v1",
                callback_key=callback,
                callback_payload_sha256=payload_sha256(callback_payload),
                projection_state=projection_state,
                source_digest_sha256=sha256(b"fake callback source only").hexdigest(),
                verifier_id="fake-i9-callback-verifier",
                verified_at_ns=now_ns,
                expires_at_ns=now_ns + 5_000_000_000,
            )

    class TradeFactVerifier:
        def verify_trade_fact(self, command, trade_fact, source_event, *, now_ns):
            fields = dict(trade_fact.native_fields)
            assert command.operation == "SUBMIT"
            assert source_event.callback_name == "OnRtnTrade"
            assert fields["Volume"] == 2
            assert fields["OrderRef"] == command.order_ref
            return CtpVerifiedTradeFactEvidence(
                evidence_type="ctp_verified_trade_fact.v2",
                owner_intent_id=source_event.owner_handle.owner_intent_id,
                source_sequence=source_event.source_sequence,
                ingress_record_digest_sha256=source_event.record_digest_sha256,
                event_id=trade_fact.event_id,
                trade_fact_sha256=payload_sha256(trade_fact.to_payload()),
                source_digest_sha256=sha256(b"fake trade source only").hexdigest(),
                verifier_id="fake-i9-trade-verifier",
                verified_at_ns=now_ns,
                expires_at_ns=now_ns + 5_000_000_000,
            )

    class FakeLifecycleSupervisor(_FakeLifecycleSupervisor):
        pass

    monkeypatch.setattr(client_module, "_check_native_module", lambda: None)
    monkeypatch.setattr(client_module, "_flow_dir", lambda _name: "fake-flow")
    monkeypatch.setattr(client_module, "_register_ctp_native_api", lambda _api: None)
    monkeypatch.setattr(client_module, "CThostFtdcTraderApi", _FakeTraderApiFactory)
    _FakeTraderApiFactory.instances = []
    worker = CtpManagedSingleWorkerCandidate(
        store,
        scope,
        lease,
        Authority() if authority_verifier is None else authority_verifier,
    )
    candidate = CtpI9AccountSessionCandidate(
        scope=scope,
        store=store,
        writer_lease=lease,
        worker=worker,
        client_factory=lambda: client_module.TraderClient(
            "tcp://127.0.0.1:1", "9999", "fake-user", "fake-test-value"
        ),
        lifecycle_supervisor=FakeLifecycleSupervisor(),
        native_field_factory=lambda _operation, payload: _FakeCtpNativeField(**payload),
        callback_verifier=CallbackVerifier(),
        trade_fact_verifier=TradeFactVerifier(),
        native_call_admission=native_call_admission,
    )
    if start:
        candidate.start()

    def reserve(intent_id):
        legacy_scope = execution_scope(
            "CTP", environment, scope.account_ref, "strategy.legacy.fake", "20260925"
        )
        sources = (
            ("backtrader_prototype", sha256(b"fake prototype source").hexdigest()),
            ("sdk_jsonl", sha256(b"empty fake sdk source").hexdigest()),
        )
        runtime_id = "bt-managed-v1:" + sha256(intent_id.encode("ascii")).hexdigest()
        mapping = CtpOrderRefLegacyMapping(
            source_name="backtrader_prototype",
            account_key=scope.account_key,
            trading_day="20260925",
            scope_key=legacy_scope.key,
            managed_intent_id="legacy-fake-stable",
            runtime_order_id="bt-managed-v1:" + sha256(b"legacy-fake-stable").hexdigest(),
            order_ref="000000000012",
        )
        proof = CtpOrderRefSeedProof(
            trading_day=scope.trading_day,
            native_max_order_ref="000000000017",
            legacy_ledger_max_order_ref="000000000012",
            legacy_ledger_sha256=payload_sha256(dict(sources)),
            account_key=scope.account_key,
            scope_key=scope.key,
            session_generation_id=candidate.active_session.session_generation_id,
            native_front_id=candidate.active_session.dispatch_front_id,
            native_session_id=candidate.active_session.dispatch_session_id,
            existing_native_order_refs=("000000000016", "000000000017"),
            legacy_source_sha256=sources,
            legacy_mappings=(mapping,),
        )
        reservation = store.seed_ctp_order_ref_and_reserve_identity(
            scope,
            proof,
            intent_id,
            runtime_id,
            writer_lease=lease,
        )
        return reservation

    def session_binding():
        binding = candidate.active_session
        return {
            "binding_type": "ctp_callback_session_binding.v1",
            "owner_intent_id": binding.owner_intent_id,
            "account_key": binding.account_key,
            "scope_key": binding.scope_key,
            "trading_day": binding.trading_day,
            "session_generation_id": binding.session_generation_id,
            "dispatch_front_id": binding.dispatch_front_id,
            "dispatch_session_id": binding.dispatch_session_id,
            "source_tags": {
                "source_instance_id": binding.source_instance_id,
                "native_client_epoch": binding.native_client_epoch,
                "native_api_source_id": binding.native_api_source_id,
                "native_spi_source_id": binding.native_spi_source_id,
                "native_api_generation": binding.native_api_generation,
                "connection_generation": binding.source_connection_generation,
            },
            "source_high_watermark": binding.source_high_watermark,
        }

    def prepared(
        reservation,
        operation="submit",
        *,
        target=None,
        inject_action_ref=False,
        native_request_id=None,
        logical_request_id=None,
        submit_quantity=1,
        managed_cancel_id=None,
    ):
        managed_cancel_id = (
            None
            if operation == "submit"
            else managed_cancel_id or "cancel." + reservation.managed_intent_id
        )
        command_id = stable_managed_command_id(
            operation,
            reservation.managed_intent_id,
            reservation.runtime_order_id,
            managed_cancel_id,
        )
        if operation == "submit":
            request = {
                "BrokerID": "9999",
                "InvestorID": "fake-user",
                "UserID": "fake-user",
                "InstrumentID": "rb2710",
                "OrderRef": reservation.order_ref,
                "Direction": "0",
                "CombOffsetFlag": "0",
                "CombHedgeFlag": "1",
                "OrderPriceType": "2",
                "LimitPrice": 3512.5,
                "VolumeTotalOriginal": submit_quantity,
                "TimeCondition": "3",
                "ExchangeID": "SHFE",
            }
        else:
            request = {
                "BrokerID": "9999",
                "InvestorID": "fake-user",
                "UserID": "fake-user",
                "InstrumentID": "rb2710",
                "OrderRef": reservation.order_ref,
                "ExchangeID": target.projection.exchange_id,
                "OrderSysID": target.projection.order_sys_id,
                "FrontID": target.projection.front_id,
                "SessionID": target.projection.session_id,
                "ActionFlag": "0",
                "LimitPrice": 0,
                "VolumeChange": 0,
            }
            if inject_action_ref:
                request["OrderActionRef"] = 23
        if logical_request_id is not None:
            request["RequestID"] = logical_request_id
        approval_id = "approval-" + sha256(command_id.encode("ascii")).hexdigest()[:24]
        values = {
            "operation": operation,
            "command_id": command_id,
            "managed_intent_id": reservation.managed_intent_id,
            "runtime_order_id": reservation.runtime_order_id,
            "order_ref": reservation.order_ref,
            "request_payload": request,
            "order_ref_reservation": reservation,
            "approval_use_id": approval_id,
            "approval_digest": sha256(("digest-" + approval_id).encode("ascii")).hexdigest(),
            "session_binding": session_binding(),
            "session_generation_id": candidate.active_session.session_generation_id,
            "dispatch_front_id": candidate.active_session.dispatch_front_id,
            "dispatch_session_id": candidate.active_session.dispatch_session_id,
            "native_request_id": (
                int.from_bytes(sha256(command_id.encode()).digest()[:4], "big") % 2_147_483_646 + 1
                if native_request_id is None
                else native_request_id
            ),
            "local_queue_receipt_id": sha256(("receipt-" + command_id).encode()).hexdigest()[:32],
        }
        if operation == "cancel":
            values.update(
                managed_cancel_intent_id=managed_cancel_id,
                cancel_target_exchange_id=target.projection.exchange_id,
                cancel_target_order_sys_id=target.projection.order_sys_id,
                cancel_target_front_id=target.projection.front_id,
                cancel_target_session_id=target.projection.session_id,
            )
        return CtpManagedPreparedDispatch(**values)

    return candidate, store, reserve, prepared, execution_scope


@pytest.mark.parametrize("failure_point", ["adapter", "factory", "supervisor"])
def test_start_failure_commits_durable_poison_and_candidate_is_one_shot(
    tmp_path, monkeypatch, failure_point
):
    candidate, store, _reserve, _prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch, start=False
    )
    factory_calls = []
    if failure_point == "adapter":

        def fail_adapter_registration(*_args, **_kwargs):
            raise RuntimeError("fake adapter construction failure")

        monkeypatch.setattr(
            store, "_register_ctp_callback_session_adapter", fail_adapter_registration
        )
    elif failure_point == "factory":

        def fail_client_factory():
            factory_calls.append(True)
            raise RuntimeError("fake client factory failure")

        candidate._client_factory = fail_client_factory
    else:

        class FailingStartSupervisor(_FakeLifecycleSupervisor):
            def start_client(self, _client):
                raise RuntimeError("fake supervisor start failure")

            def stop_client(self, _client):
                self.stops.append(_client)

        candidate._lifecycle_supervisor = FailingStartSupervisor()

    try:
        with pytest.raises(
            CtpI9AccountSessionCandidateError, match="durable owner state is POISONED"
        ):
            candidate.start()
        owner_row = store._connection.execute(
            "SELECT owner_state, poison_code FROM ctp_dispatch_callback_session_owners "
            "WHERE owner_intent_id = ?",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert tuple(owner_row) == ("POISONED", "candidate_composition_failure")
        assert candidate.durable_owner_state == "POISONED"
        assert candidate._start_attempted is True
        with pytest.raises(CtpI9AccountSessionCandidateError, match="one-shot"):
            candidate.start()
        if failure_point == "adapter":
            assert factory_calls == []
    finally:
        candidate.stop()
        store.close()


def test_poison_commit_failure_reports_durable_unknown_and_stop_does_not_claim_closed(
    tmp_path, monkeypatch
):
    candidate, store, _reserve, _prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch, start=False
    )

    def fail_poison(*_args, **_kwargs):
        raise RuntimeError("fake durable poison failure")

    monkeypatch.setattr(store, "poison_ctp_callback_session_owner", fail_poison)
    candidate._client_factory = lambda: (_ for _ in ()).throw(
        RuntimeError("fake client factory failure")
    )
    try:
        with pytest.raises(
            CtpI9AccountSessionCandidateError,
            match="locally fenced; durable owner state is UNKNOWN",
        ):
            candidate.start()
        owner_row = store._connection.execute(
            "SELECT owner_state FROM ctp_dispatch_callback_session_owners "
            "WHERE owner_intent_id = ?",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert owner_row[0] == "PREPARED"
        assert candidate.durable_owner_state == "UNKNOWN"
        assert candidate._started is False
        with pytest.raises(
            CtpI9AccountSessionCandidateError,
            match="durable owner state is UNKNOWN",
        ):
            candidate.stop()
        assert candidate._stopped is False
    finally:
        store.close()


def test_supervisor_stop_failure_leaves_candidate_open_and_owner_poisoned(tmp_path, monkeypatch):
    candidate, store, _reserve, _prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch
    )

    class FailingStopSupervisor(_FakeLifecycleSupervisor):
        def stop_client(self, _client):
            raise RuntimeError("fake stop failure")

    candidate._lifecycle_supervisor = FailingStopSupervisor()
    try:
        with pytest.raises(
            CtpI9AccountSessionCandidateError,
            match="durable owner state is POISONED",
        ):
            candidate.stop()
        owner_row = store._connection.execute(
            "SELECT owner_state, poison_code FROM ctp_dispatch_callback_session_owners "
            "WHERE owner_intent_id = ?",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert tuple(owner_row) == ("POISONED", "owner_stop")
        assert candidate.durable_owner_state == "POISONED"
        assert candidate._stopped is False
        assert candidate._started is False
    finally:
        store.close()


@pytest.mark.parametrize("failure_point", ["queue_receipt", "queue_publish"])
def test_pre_native_stage_failure_is_store_unknown_and_owner_poisoned(
    tmp_path, monkeypatch, failure_point
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch
    )
    api = _FakeTraderApiFactory.instances[-1]
    reservation = reserve("i9-fake-pre-native-failure")
    prepared = make_prepared(reservation)
    if failure_point == "queue_receipt":

        def fail_queue_receipt(*_args, **_kwargs):
            raise RuntimeError("fake queue receipt failure")

        monkeypatch.setattr(candidate._worker, "record_managed_queue_receipt", fail_queue_receipt)
        expected_unknown_reason = "session_pre_native_failure:queue_receipt_failure"
    else:

        def fail_queue_publish(_command_id):
            raise queue.Full

        monkeypatch.setattr(candidate._queue, "put_nowait", fail_queue_publish)
        expected_unknown_reason = "session_pre_native_failure:queue_publish_failure"
    try:
        with pytest.raises(
            CtpI9AccountSessionCandidateError, match="durable owner state is POISONED"
        ):
            candidate.stage_and_queue(prepared)
        command = store.read_ctp_dispatch_command(candidate._scope, prepared.command_id)
        assert command.status == "UNKNOWN"
        assert command.unknown_reason == expected_unknown_reason
        owner_row = store._connection.execute(
            "SELECT owner_state, poison_code FROM ctp_dispatch_callback_session_owners "
            "WHERE owner_intent_id = ?",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert tuple(owner_row) == ("POISONED", "dispatch_stage_ambiguous")
        assert candidate.durable_owner_state == "POISONED"
        assert not any(
            call[0] in {"ReqOrderInsert", "ReqOrderAction"}
            for call in api.calls
            if isinstance(call, tuple)
        )
    finally:
        candidate.stop()
        store.close()


@pytest.mark.parametrize("claim_boundary", ["before_commit", "after_commit"])
def test_claim_failure_uses_ready_or_claimed_unknown_receipt_path(
    tmp_path, monkeypatch, claim_boundary
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch
    )
    api = _FakeTraderApiFactory.instances[-1]
    reservation = reserve("i9-fake-claim-failure")
    prepared = make_prepared(reservation)
    candidate.stage_and_queue(prepared)
    original_claim = store.claim_ctp_dispatch_command_for_session
    if claim_boundary == "before_commit":

        def fail_before_claim(*_args, **_kwargs):
            raise RuntimeError("fake pre-claim failure")

        monkeypatch.setattr(store, "claim_ctp_dispatch_command_for_session", fail_before_claim)
    else:

        def fail_after_claim(*args, **kwargs):
            original_claim(*args, **kwargs)
            raise RuntimeError("fake post-claim readback failure")

        monkeypatch.setattr(store, "claim_ctp_dispatch_command_for_session", fail_after_claim)
    try:
        if claim_boundary == "before_commit":
            from backtrader_runtime.ctp_i9_account_session_candidate import (
                CtpI9DispatchDeferred,
            )

            deferred = candidate.dispatch_next()
            assert type(deferred) is CtpI9DispatchDeferred
            assert deferred.command_id == prepared.command_id
            command = store.read_ctp_dispatch_command(candidate._scope, prepared.command_id)
            assert command.status == "READY"
            assert candidate.durable_owner_state == "UNOBSERVED"
            assert candidate.client._callback_ingress.poisoned is False
            assert not any(
                isinstance(call, tuple) and call[0] in {"ReqOrderInsert", "ReqOrderAction"}
                for call in api.calls
            )
            monkeypatch.setattr(store, "claim_ctp_dispatch_command_for_session", original_claim)
            assert candidate.dispatch_next().status == "COMPLETED"
            command = store.read_ctp_dispatch_command(candidate._scope, prepared.command_id)
            assert command.status == "COMPLETED"
            assert candidate.durable_owner_state == "UNOBSERVED"
            assert any(
                isinstance(call, tuple) and call[0] == "ReqOrderInsert" for call in api.calls
            )
            return

        with pytest.raises(
            CtpI9AccountSessionCandidateError, match="session-bound Store claim failed"
        ):
            candidate.dispatch_next()
        command = store.read_ctp_dispatch_command(candidate._scope, prepared.command_id)
        assert command.status == "UNKNOWN"
        assert command.unknown_reason == "native_receipt_unknown"
        row = store._connection.execute(
            "SELECT native_call_inflight, completion_echo_json FROM ctp_dispatch_commands "
            "WHERE command_id = ?",
            (prepared.command_id,),
        ).fetchone()
        assert row[0] == 0
        if claim_boundary == "after_commit":
            assert '"outcome":"UNKNOWN"' in row[1]
        owner_row = store._connection.execute(
            "SELECT owner_state, poison_code FROM ctp_dispatch_callback_session_owners "
            "WHERE owner_intent_id = ?",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert tuple(owner_row) == ("POISONED", "dispatch_claim_failure")
        assert candidate.durable_owner_state == "POISONED"
        assert not any(
            call[0] in {"ReqOrderInsert", "ReqOrderAction"}
            for call in api.calls
            if isinstance(call, tuple)
        )
    finally:
        candidate.stop()
        store.close()


def test_ready_claim_failure_with_unavailable_session_readback_fences_without_req(
    tmp_path, monkeypatch
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch
    )
    api = _FakeTraderApiFactory.instances[-1]
    reservation = reserve("i9-fake-claim-readback-unavailable")
    prepared = make_prepared(reservation)
    candidate.stage_and_queue(prepared)

    def fail_before_claim(*_args, **_kwargs):
        raise RuntimeError("fake pre-claim failure")

    def fail_ready_readback(*_args, **_kwargs):
        raise RuntimeError("fake unavailable READY/session readback")

    monkeypatch.setattr(store, "claim_ctp_dispatch_command_for_session", fail_before_claim)
    monkeypatch.setattr(store, "read_ctp_staged_command_for_session", fail_ready_readback)
    try:
        with pytest.raises(
            CtpI9AccountSessionCandidateError, match="session-bound Store claim failed"
        ):
            candidate.dispatch_next()
        command = store.read_ctp_dispatch_command(candidate._scope, prepared.command_id)
        assert command.status == "READY"
        owner_row = store._connection.execute(
            "SELECT owner_state, poison_code FROM ctp_dispatch_callback_session_owners "
            "WHERE owner_intent_id = ?",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert tuple(owner_row) == ("POISONED", "dispatch_claim_failure")
        assert candidate.durable_owner_state == "POISONED"
        assert not any(
            isinstance(call, tuple) and call[0] in {"ReqOrderInsert", "ReqOrderAction"}
            for call in api.calls
        )
    finally:
        candidate.stop()
        store.close()


def test_final_native_admission_rejection_after_claim_commits_unknown_without_req(
    tmp_path, monkeypatch
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch
    )
    api = _FakeTraderApiFactory.instances[-1]
    reservation = reserve("i9-final-native-admission-denied")
    prepared = make_prepared(reservation)
    candidate.stage_and_queue(prepared)
    observed = []

    def reject_final_admission(owner, binding, verified):
        observed.append((owner, binding, verified))
        assert binding is verified
        raise RuntimeError("fake final claimed-action permit expired")

    candidate._native_call_admission = reject_final_admission
    try:
        with pytest.raises(
            CtpI9AccountSessionCandidateError,
            match="native call outcome is unknown; account remains fenced",
        ):
            candidate.dispatch_next()

        assert len(observed) == 1
        command = store.read_ctp_dispatch_command(candidate._scope, prepared.command_id)
        assert command.status == "UNKNOWN"
        assert command.unknown_reason == "native_receipt_unknown"
        assert not any(
            isinstance(call, tuple) and call[0] in {"ReqOrderInsert", "ReqOrderAction"}
            for call in api.calls
        )
        owner_row = store._connection.execute(
            "SELECT owner_state, poison_code FROM ctp_dispatch_callback_session_owners "
            "WHERE owner_intent_id = ?",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert tuple(owner_row) == ("POISONED", "native_call_lease_failure")
    finally:
        candidate.stop()
        store.close()


def _bind_real_action_authority_for_candidate(candidate, prepared, slot):
    """Build a real Ed25519/Store adapter for final-gate integration cases."""

    import time
    from types import SimpleNamespace

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from bt_api_execution.contracts import payload_sha256
    from backtrader_runtime.ctp_managed_action_authority import (
        CtpManagedActionAuthorityAdapter,
        CtpManagedActionPermitV1,
        CtpManagedActionRevocationSnapshot,
        CtpManagedActionScopeV1,
        CtpManagedActionWriterFenceSnapshot,
        CtpPinnedEd25519ActionKey,
        PinnedEd25519CtpActionPermitVerifier,
    )

    scope = candidate._scope
    account_fingerprint = scope.account_key.partition(":")[2]
    action_scope = CtpManagedActionScopeV1(
        provider=scope.provider,
        environment=scope.environment,
        mode="simulation",
        preset="sandbox",
        runtime_id="runtime.fake.ctp",
        strategy_id=scope.strategy_id,
        runtime_registration_digest=sha256(b"fake runtime registration").hexdigest(),
        mode_registration_digest=sha256(b"fake mode registration").hexdigest(),
        config_digest=sha256(b"fake sealed config").hexdigest(),
        effective_digest=sha256(b"fake effective config").hexdigest(),
        profile_digest=None,
        account_fingerprint_sha256=account_fingerprint,
        front_pair_sha256=sha256(b"fake front pair").hexdigest(),
        front_pair_set_sha256=sha256(b"fake front pair set").hexdigest(),
    )
    session_payload = dict(prepared.session_binding)
    logical_payload = dict(prepared.request_payload)
    request_digest = payload_sha256(logical_payload)
    session_digest = payload_sha256(session_payload)
    correlation = SimpleNamespace(
        version=2,
        account_key=scope.account_key,
        scope_key=scope.key,
        trading_day=scope.trading_day,
        operation="SUBMIT",
        command_id=prepared.command_id,
        request_payload_sha256=request_digest,
        reservation_managed_intent_id=prepared.managed_intent_id,
        managed_action_id=prepared.managed_intent_id,
        runtime_order_id=prepared.runtime_order_id,
        order_ref=prepared.order_ref,
        cancel_target_exchange_id=None,
        cancel_target_order_sys_id=None,
        cancel_target_front_id=None,
        cancel_target_session_id=None,
        native_request_id=prepared.native_request_id,
        native_action_ref=None,
        native_request_payload_sha256=request_digest,
        session_generation_id=prepared.session_generation_id,
        dispatch_front_id=prepared.dispatch_front_id,
        dispatch_session_id=prepared.dispatch_session_id,
    )
    command = SimpleNamespace(
        account_key=scope.account_key,
        scope_key=scope.key,
        trading_day=scope.trading_day,
        operation="SUBMIT",
        command_id=prepared.command_id,
        request_payload=logical_payload,
        request_payload_sha256=request_digest,
        reservation_managed_intent_id=prepared.managed_intent_id,
        order_ref=prepared.order_ref,
        cancel_target_order_ref=None,
        cancel_target_exchange_id=None,
        cancel_target_order_sys_id=None,
        cancel_target_front_id=None,
        cancel_target_session_id=None,
        approval_use_id=prepared.approval_use_id,
        approval_digest=prepared.approval_digest,
        session_binding=session_payload,
        session_binding_sha256=session_digest,
        status="READY",
        correlation_key=correlation,
        native_request_payload=logical_payload,
        native_request_payload_sha256=request_digest,
    )
    action_digest = CtpManagedActionAuthorityAdapter._action_digest(command, action_scope)
    now_ns = time.time_ns()
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    signing_values = {
        "permit_id": prepared.approval_use_id,
        "issuer": "issuer.fake.integration",
        "key_id": "key.fake.integration",
        "audience": "ctp-i9-store-claim",
        "environment": action_scope.environment,
        "mode": action_scope.mode,
        "preset": action_scope.preset,
        "scope_sha256": action_scope.digest,
        "action_sha256": action_digest,
        "issued_at_ns": now_ns - 1_000_000,
        "expires_at_ns": now_ns + 4_000_000_000,
        "revocation_epoch": 3,
        "fence_id": "fence.fake.integration",
        "fence_epoch": 7,
        "fence_owner_id": "service.fake.integration",
        "nonce": "nonce.fake.integration",
        "signature_hex": "0" * 128,
    }
    unsigned = CtpManagedActionPermitV1(**signing_values)
    permit = CtpManagedActionPermitV1(
        **dict(signing_values, signature_hex=private_key.sign(unsigned.signed_payload()).hex())
    )

    class ScopeResolver:
        def resolve(self, _command, _execution_scope):
            return action_scope

        def validate_action_context(self, _command, _execution_scope, **_facts):
            return action_scope

        def validate_prepared_action_context(self, *_args, **_kwargs):
            return action_scope

    class PermitSource:
        def read_permit(self, permit_id):
            assert permit_id == permit.permit_id
            return permit

    class RevocationSource:
        def __init__(self):
            self.snapshot = CtpManagedActionRevocationSnapshot(
                permit_id=permit.permit_id,
                key_id=permit.key_id,
                epoch=permit.revocation_epoch,
                revoked=False,
                key_active=True,
                observed_at_ns=now_ns - 1_000_000,
                valid_until_ns=now_ns + 3_000_000_000,
                source_digest_sha256=sha256(b"fake revocation snapshot").hexdigest(),
            )

        def read_revocation(self, _permit):
            return self.snapshot

    class FenceSource:
        def __init__(self):
            self.snapshot = CtpManagedActionWriterFenceSnapshot(
                fence_id=permit.fence_id,
                owner_id=permit.fence_owner_id,
                account_fingerprint_sha256=account_fingerprint,
                environment=action_scope.environment,
                mode=action_scope.mode,
                epoch=permit.fence_epoch,
                observed_at_ns=now_ns - 1_000_000,
                expires_at_ns=now_ns + 3_000_000_000,
                source_digest_sha256=sha256(b"fake writer fence").hexdigest(),
            )

        def read_active_fence(self, _scope):
            return self.snapshot

    class TrustedClock:
        def __init__(self):
            self.value = now_ns
            self.values = []

        def now_ns(self):
            if self.values:
                self.value = self.values.pop(0)
            return self.value

    resolver = ScopeResolver()
    permit_source = PermitSource()
    revocation_source = RevocationSource()
    fence_source = FenceSource()
    clock = TrustedClock()
    key_pin = CtpPinnedEd25519ActionKey(
        issuer=permit.issuer,
        key_id=permit.key_id,
        audience=permit.audience,
        public_key=public_key,
        valid_from_ns=now_ns - 10_000_000_000,
        valid_until_ns=now_ns + 30_000_000_000,
    )
    adapter = CtpManagedActionAuthorityAdapter(
        store=candidate._store,
        scope=scope,
        owner_handle=candidate.owner_handle,
        writer_lease=candidate._writer_lease,
        scope_resolver=resolver,
        permit_source=permit_source,
        signature_verifier=PinnedEd25519CtpActionPermitVerifier((key_pin,)),
        revocation_source=revocation_source,
        fence_source=fence_source,
        trusted_clock=clock,
    )
    slot.bind(adapter)
    return SimpleNamespace(
        adapter=adapter,
        resolver=resolver,
        permit=permit,
        revocation_source=revocation_source,
        fence_source=fence_source,
        clock=clock,
        action_scope=action_scope,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "expired",
        "binding_expiry_cross",
        "revoked",
        "fence_epoch",
        "copied_binding",
        "altered_claimed_row",
    ],
)
def test_real_claimed_authority_recheck_gates_native_req_and_never_reuses_approval(
    tmp_path, monkeypatch, mutation
):
    from dataclasses import replace

    from backtrader_runtime.ctp_managed_account_runtime_candidate import (
        CtpManagedAccountRuntimeCandidate,
        CtpManagedActionAuthorityVerifierSlot,
    )

    slot = CtpManagedActionAuthorityVerifierSlot()
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path,
        monkeypatch,
        environment="simnow",
        authority_verifier=slot,
    )
    api = _FakeTraderApiFactory.instances[-1]
    reservation = reserve("i9-final-authority-" + mutation)
    unsigned_prepared = make_prepared(reservation)
    authority_fixture = _bind_real_action_authority_for_candidate(
        candidate,
        unsigned_prepared,
        slot,
    )
    prepared = replace(unsigned_prepared, approval_digest=authority_fixture.permit.digest)
    candidate.stage_and_queue(prepared)
    stored = store.read_ctp_dispatch_command(candidate._scope, prepared.command_id)
    assert (
        authority_fixture.adapter._action_digest(stored, authority_fixture.action_scope)
        == authority_fixture.permit.action_sha256
    )

    composition = object.__new__(CtpManagedAccountRuntimeCandidate)
    composition._session_candidate = candidate
    composition._execution_scope = candidate._scope
    composition._store = store
    composition._scope_resolver = authority_fixture.resolver
    composition._authority_adapter = authority_fixture.adapter
    composition._trusted_clock = authority_fixture.clock

    def final_admission(owner_handle, binding, verified):
        if mutation == "expired":
            authority_fixture.clock.value = authority_fixture.permit.expires_at_ns + 1
        elif mutation == "binding_expiry_cross":
            before_expiry = binding.expires_at_ns - 100_000
            authority_fixture.clock.values = [
                before_expiry,
                before_expiry,
                before_expiry,
                before_expiry,
                binding.expires_at_ns + 100_000,
            ]
        elif mutation == "revoked":
            authority_fixture.revocation_source.snapshot = replace(
                authority_fixture.revocation_source.snapshot,
                revoked=True,
                source_digest_sha256=sha256(b"revoked after claim").hexdigest(),
            )
        elif mutation == "fence_epoch":
            authority_fixture.fence_source.snapshot = replace(
                authority_fixture.fence_source.snapshot,
                epoch=authority_fixture.permit.fence_epoch + 1,
                source_digest_sha256=sha256(b"fence advanced after claim").hexdigest(),
            )
        elif mutation == "copied_binding":
            binding = replace(binding)
        elif mutation == "altered_claimed_row":
            original_read = store.read_ctp_dispatch_command

            def read_altered_claimed_row(scope, command_id):
                row = original_read(scope, command_id)
                if command_id == prepared.command_id:
                    return replace(
                        row,
                        request_payload=dict(row.request_payload, InstrumentID="cu9999"),
                    )
                return row

            monkeypatch.setattr(store, "read_ctp_dispatch_command", read_altered_claimed_row)
        composition._verify_final_native_call(owner_handle, binding, verified)

    candidate._native_call_admission = final_admission
    try:
        if mutation == "none":
            assert candidate.dispatch_next().status == "COMPLETED"
            assert any(
                isinstance(call, tuple) and call[0] == "ReqOrderInsert" for call in api.calls
            )
        else:
            with pytest.raises(
                CtpI9AccountSessionCandidateError,
                match="native call outcome is unknown; account remains fenced",
            ):
                candidate.dispatch_next()
            assert not any(
                isinstance(call, tuple) and call[0] in {"ReqOrderInsert", "ReqOrderAction"}
                for call in api.calls
            )
            command = store.read_ctp_dispatch_command(candidate._scope, prepared.command_id)
            assert command.status == "UNKNOWN"
            assert command.unknown_reason == "native_receipt_unknown"

        uses = store._connection.execute(
            "SELECT command_id, approval_digest FROM ctp_dispatch_authority_uses "
            "WHERE account_key = ? AND approval_use_id = ?",
            (candidate._scope.account_key, prepared.approval_use_id),
        ).fetchall()
        assert len(uses) == 1
        assert tuple(uses[0]) == (prepared.command_id, authority_fixture.permit.digest)
        assert authority_fixture.permit.digest == prepared.approval_digest
    finally:
        candidate.stop()
        store.close()


@pytest.mark.parametrize("failure_point", ["stage", "claim", "native"])
def test_bounded_base_exception_persists_unknown_poison_and_reraises_original(
    tmp_path, monkeypatch, failure_point
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch
    )
    api = _FakeTraderApiFactory.instances[-1]
    abort = _BoundedAbort("synthetic bounded abort")
    reservation = reserve("i9-fake-base-exception-" + failure_point)
    prepared = make_prepared(reservation)

    if failure_point == "stage":
        original_record = candidate._worker.record_managed_queue_receipt

        def commit_receipt_then_abort(*args, **kwargs):
            original_record(*args, **kwargs)
            raise abort

        monkeypatch.setattr(
            candidate._worker, "record_managed_queue_receipt", commit_receipt_then_abort
        )

        def operation():
            return candidate.stage_and_queue(prepared)

        expected_reason = "session_pre_native_failure:queue_receipt_failure"
    elif failure_point == "claim":
        candidate.stage_and_queue(prepared)
        original_claim = store.claim_ctp_dispatch_command_for_session

        def commit_claim_then_abort(*args, **kwargs):
            original_claim(*args, **kwargs)
            raise abort

        monkeypatch.setattr(
            store, "claim_ctp_dispatch_command_for_session", commit_claim_then_abort
        )
        operation = candidate.dispatch_next
        expected_reason = "native_receipt_unknown"
    else:
        api.insert_base_exception = abort
        candidate.stage_and_queue(prepared)
        operation = candidate.dispatch_next
        expected_reason = "native_receipt_unknown"

    try:
        with pytest.raises(_BoundedAbort) as raised:
            operation()
        assert raised.value is abort
        command = store.read_ctp_dispatch_command(candidate._scope, prepared.command_id)
        assert command.status == "UNKNOWN"
        assert command.unknown_reason == expected_reason
        row = store._connection.execute(
            "SELECT native_call_inflight, completion_echo_json FROM ctp_dispatch_commands "
            "WHERE command_id = ?",
            (prepared.command_id,),
        ).fetchone()
        assert row[0] == 0
        if failure_point != "stage":
            assert '"outcome":"UNKNOWN"' in row[1]
        owner_row = store._connection.execute(
            "SELECT owner_state FROM ctp_dispatch_callback_session_owners "
            "WHERE owner_intent_id = ?",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert owner_row[0] == "POISONED"
        assert candidate.durable_owner_state == "POISONED"
        if failure_point in {"stage", "claim"}:
            assert not any(
                isinstance(call, tuple) and call[0] in {"ReqOrderInsert", "ReqOrderAction"}
                for call in api.calls
            )
        else:
            assert any(
                isinstance(call, tuple) and call[0] == "ReqOrderInsert" for call in api.calls
            )
    finally:
        candidate.stop()
        store.close()


def _fresh_fake_target(
    store,
    scope,
    reservation,
    candidate,
    types,
    *,
    provider_state="OPEN",
    quantity=1,
    traded_quantity=0,
    remaining_quantity=None,
):
    projection_type = types[11]

    class FakeExactQueryVerifier:
        def verify_order_target(self, active_scope, current_reservation, _evidence, *, now_ns):
            assert active_scope == scope
            assert current_reservation == reservation
            session = candidate.active_session
            return projection_type(
                account_key=scope.account_key,
                scope_key=scope.key,
                trading_day=scope.trading_day,
                managed_intent_id=reservation.managed_intent_id,
                runtime_order_id=reservation.runtime_order_id,
                order_ref=reservation.order_ref,
                account_fingerprint_sha256=sha256(b"fake account fingerprint").hexdigest(),
                registration_digest=sha256(b"fake registration").hexdigest(),
                instrument_id="rb2710",
                exchange_id="SHFE",
                session_generation_id=session.session_generation_id,
                connection_generation=session.connection_generation,
                query_front_id=session.dispatch_front_id,
                query_session_id=session.dispatch_session_id,
                query_request_id=(now_ns % 2_147_483_646) + 1,
                query_filters_sha256=sha256(b"fake exact query filters").hexdigest(),
                query_records_sha256=sha256(b"fake query result").hexdigest(),
                source_evidence_sha256=sha256(b"fake query source only").hexdigest(),
                query_record_count=1,
                query_match_count=1,
                query_complete=True,
                query_terminal=True,
                query_timed_out=False,
                query_error_id=0,
                late_callback_count=0,
                order_sys_id="SYS-" + reservation.order_ref,
                front_id=session.dispatch_front_id,
                session_id=session.dispatch_session_id,
                provider_state=provider_state,
                quantity=quantity,
                traded_quantity=traded_quantity,
                remaining_quantity=(
                    quantity - traded_quantity if remaining_quantity is None else remaining_quantity
                ),
                verifier_id="fake-exact-query-verifier",
                verified_at_ns=now_ns,
                expires_at_ns=now_ns + 1_000_000_000,
            )

    return store.issue_ctp_order_target_projection(
        scope,
        reservation.managed_intent_id,
        {"fake_only": True},
        verifier=FakeExactQueryVerifier(),
    )


def test_fake_store_to_sdk_partial_fill_cancel_terminal_order_return_preserves_fills(
    tmp_path, monkeypatch
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch, native_call_admission=_fake_native_call_admission
    )
    scope = candidate._scope
    api = _FakeTraderApiFactory.instances[-1]
    observed_during_req = []

    def observe_before_req_returns(callback_name):
        event = candidate._adapter.read_next_ingress()
        assert event is not None and event.callback_name == callback_name
        # A native callback can enter reentrantly, but the Store router refuses
        # to apply it until the exact local receipt clears native_call_inflight.
        assert store.find_ctp_dispatch_command_for_ingress(event) is None
        observed_during_req.append(callback_name)

    api.after_routeable_callback = observe_before_req_returns
    native_factory_payloads = []
    native_field_factory = candidate._native_field_factory

    def capture_native_payload(operation, payload):
        with pytest.raises(TypeError):
            payload["OrderActionRef"] = 2_147_483_647
        native_factory_payloads.append((operation, dict(payload)))
        return native_field_factory(operation, payload)

    candidate._native_field_factory = capture_native_payload
    try:
        first = reserve("i9-fake-intent-one")
        second = reserve("i9-fake-intent-two")
        prepared_commands = []
        for index, reservation in enumerate((first, second)):
            prepared = make_prepared(
                reservation,
                native_request_id=52 if index == 0 else None,
                logical_request_id=52 if index == 0 else None,
                submit_quantity=5 if index == 0 else 1,
            )
            prepared_commands.append(prepared)
            from bt_api_execution.contracts import payload_sha256

            assert (
                payload_sha256(dict(prepared.session_binding))
                == candidate.active_session.session_binding_sha256
            )
            staged = candidate.stage_and_queue(prepared)
            assert staged.local_queue_receipt_queued is True
            assert staged.native_action_ref is None
            assert dict(staged.native_request_payload) == dict(prepared.request_payload)
            assert staged.request_payload_sha256 == payload_sha256(dict(prepared.request_payload))
            assert staged.native_request_payload_sha256 == payload_sha256(
                dict(prepared.request_payload)
            )
            receipt = candidate.dispatch_next()
            assert receipt.command_id == prepared.command_id
            assert receipt.status == "COMPLETED"
            applied = candidate.apply_pending_ingress()
            assert len(applied) == 1
            assert applied[0].callback_key.correlation_key.command_id == prepared.command_id
            if index == 0:
                api.spi.OnRtnTrade(
                    _FakeCtpNativeField(
                        BrokerID="9999",
                        InvestorID="fake-user",
                        UserID="fake-user",
                        InstrumentID="rb2710",
                        ExchangeID="SHFE",
                        TradeID="TRADE-" + first.order_ref,
                        OrderRef=first.order_ref,
                        OrderSysID="SYS-" + first.order_ref,
                        TradingDay="20260926",
                        Direction="0",
                        OffsetFlag="0",
                        HedgeFlag="1",
                        Price=3512.5,
                        Volume=2,
                        TradeDate="20260926",
                        TradeTime="09:31:00",
                        SequenceNo=1,
                        BrokerOrderSeq=1,
                        TradeSource="0",
                    )
                )
                trade_applied = candidate.apply_pending_ingress()
                assert len(trade_applied) == 1
                assert trade_applied[0].trade_quantity == 2
                assert trade_applied[0].cumulative_trade_quantity == 2

                api.spi.OnRtnOrder(
                    _FakeCtpNativeField(
                        BrokerID="9999",
                        InvestorID="fake-user",
                        UserID="fake-user",
                        InstrumentID="rb2710",
                        ExchangeID="SHFE",
                        OrderRef=first.order_ref,
                        OrderSysID="SYS-" + first.order_ref,
                        RequestID=prepared.native_request_id,
                        FrontID=candidate.active_session.dispatch_front_id,
                        SessionID=candidate.active_session.dispatch_session_id,
                        TradingDay=scope.trading_day,
                        OrderStatus="2",
                        VolumeTraded=2,
                        VolumeTotal=3,
                        NotifySequence=1,
                        SequenceNo=1,
                    )
                )
                partial_applied = candidate.apply_pending_ingress()
                assert len(partial_applied) == 1
                assert partial_applied[0].projection_state == "PARTIALLY_FILLED"

        fresh_target = _fresh_fake_target(
            store,
            scope,
            first,
            candidate,
            _trusted_candidate_types(),
            provider_state="PARTIAL",
            quantity=5,
            traded_quantity=2,
            remaining_quantity=3,
        )
        cancel = make_prepared(
            first,
            "cancel",
            target=fresh_target,
            native_request_id=53,
        )
        assert "OrderActionRef" not in cancel.request_payload
        staged_cancel = candidate.stage_and_queue(cancel, cancel_target=fresh_target)
        assert staged_cancel.operation == "cancel"
        assert type(staged_cancel.native_action_ref) is int
        assert 1 <= staged_cancel.native_action_ref <= 2_147_483_647
        assert staged_cancel.native_action_ref == 1
        assert "OrderActionRef" not in staged_cancel.request_payload
        assert "RequestID" not in cancel.request_payload
        assert "RequestID" not in staged_cancel.native_request_payload
        expected_native_cancel = dict(cancel.request_payload)
        expected_native_cancel["OrderActionRef"] = staged_cancel.native_action_ref
        assert dict(staged_cancel.native_request_payload) == expected_native_cancel
        assert staged_cancel.request_payload_sha256 == payload_sha256(dict(cancel.request_payload))
        assert staged_cancel.native_request_payload_sha256 == payload_sha256(expected_native_cancel)
        assert api.after_routeable_callback is observe_before_req_returns
        cancel_receipt = candidate.dispatch_next()
        assert cancel_receipt.command_id == cancel.command_id
        assert cancel_receipt.status == "COMPLETED"
        cancel_applied = candidate.apply_pending_ingress()
        assert len(cancel_applied) == 1
        cancel_callback_key = cancel_applied[0].callback_key
        assert cancel_callback_key.correlation_key.command_id == cancel.command_id
        assert cancel_callback_key.native_request_id == cancel.native_request_id
        assert cancel_callback_key.native_action_ref == staged_cancel.native_action_ref
        assert cancel.native_request_id == 53
        assert staged_cancel.native_action_ref != cancel.native_request_id
        assert api.order_action_calls == [(53, staged_cancel.native_action_ref)]
        assert api.order_action_field_request_ids == [53]

        api.spi.OnRtnOrder(
            _FakeCtpNativeField(
                BrokerID="9999",
                InvestorID="fake-user",
                UserID="fake-user",
                InstrumentID="rb2710",
                ExchangeID="SHFE",
                OrderRef=first.order_ref,
                OrderSysID="SYS-" + first.order_ref,
                RequestID=prepared_commands[0].native_request_id,
                FrontID=candidate.active_session.dispatch_front_id,
                SessionID=candidate.active_session.dispatch_session_id,
                TradingDay=scope.trading_day,
                OrderStatus="5",
                VolumeTraded=2,
                VolumeTotal=3,
                NotifySequence=2,
                SequenceNo=2,
            )
        )
        terminal_applied = candidate.apply_pending_ingress()
        assert len(terminal_applied) == 1
        assert terminal_applied[0].projection_state == "CANCELLED"
        assert terminal_applied[0].callback_key.correlation_key.command_id == (
            prepared_commands[0].command_id
        )
        submit_projection = store.read_ctp_dispatch_projection(
            scope, prepared_commands[0].command_id
        )
        assert submit_projection.submit_action.order_state.provider_state == "CANCELLED"
        assert submit_projection.submit_action.order_state.terminal is True
        cancel_projection = store.read_ctp_dispatch_projection(scope, cancel.command_id)
        assert cancel_projection.cancel_action.action_state == "ACKNOWLEDGED"
        assert cancel_projection.cancel_action.terminal is False

        trade_row = store._connection.execute(
            "SELECT trade_volume, cumulative_trade_volume FROM ctp_dispatch_trade_fact_ledger "
            "WHERE command_id = ?",
            (prepared_commands[0].command_id,),
        ).fetchone()
        assert tuple(trade_row) == (2, 2)
        cumulative_rows = store._connection.execute(
            "SELECT native_volume_traded, trade_volume_at_prefix, prefix_consistency "
            "FROM ctp_dispatch_order_cumulative_ledger WHERE command_id = ? "
            "ORDER BY source_sequence",
            (prepared_commands[0].command_id,),
        ).fetchall()
        assert [tuple(row) for row in cumulative_rows] == [
            (2, 2, "MATCHED"),
            (2, 2, "MATCHED"),
        ]
        assert (
            dict(prepared_commands[0].request_payload)["VolumeTotalOriginal"]
            - trade_row["cumulative_trade_volume"]
            == 3
        )
        assert dict(staged_cancel.native_request_payload)["VolumeChange"] == 0

        # The store's callback projection has resolved the target order to
        # CANCELLED while the separate cancel-action ACK remains nonterminal.
        # The current candidate permits a later unrelated submit; that is only
        # an observed G5 candidate behavior, not terminal-action authority.
        third = reserve("i9-fake-intent-three")
        third_prepared = make_prepared(third)
        candidate.stage_and_queue(third_prepared)
        assert candidate.dispatch_next().status == "COMPLETED"
        third_applied = candidate.apply_pending_ingress()
        assert len(third_applied) == 1
        assert third_applied[0].callback_key.correlation_key.command_id == (
            third_prepared.command_id
        )
        assert store.read_next_ctp_callback_ingress(candidate.owner_handle) is None

        cancel_replay = make_prepared(
            first,
            "cancel",
            target=fresh_target,
            native_request_id=54,
            managed_cancel_id="cancel.replay-attempt",
        )
        with pytest.raises(CtpI9AccountSessionCandidateError):
            candidate.stage_and_queue(cancel_replay, cancel_target=fresh_target)
        assert api.order_action_calls == [(53, staged_cancel.native_action_ref)]
        assert candidate.durable_owner_state == "POISONED"

        assert [
            call[2] for call in api.calls if isinstance(call, tuple) and call[0] == "ReqOrderInsert"
        ] == [prepared.native_request_id for prepared in prepared_commands] + [
            third_prepared.native_request_id
        ]
        assert prepared_commands[0].request_payload["RequestID"] == 52
        assert "RequestID" not in prepared_commands[1].request_payload
        submit_field_payloads = [
            payload for operation, payload in native_factory_payloads if operation == "SUBMIT"
        ]
        assert submit_field_payloads[0]["RequestID"] == 52
        assert "RequestID" not in submit_field_payloads[1]
        expected_cancel_field = dict(expected_native_cancel)
        expected_cancel_field["RequestID"] = cancel.native_request_id
        assert native_factory_payloads == [
            ("SUBMIT", dict(prepared.request_payload)) for prepared in prepared_commands
        ] + [("CANCEL", expected_cancel_field), ("SUBMIT", dict(third_prepared.request_payload))]

        assert observed_during_req == [
            "OnRspOrderInsert",
            "OnRspOrderInsert",
            "OnRspOrderAction",
            "OnRspOrderInsert",
        ]
        assert [
            call[0] for call in api.calls if call[0] in {"ReqOrderInsert", "ReqOrderAction"}
        ] == ["ReqOrderInsert", "ReqOrderInsert", "ReqOrderAction", "ReqOrderInsert"]
        command_rows = store._connection.execute(
            "SELECT command_id, operation, status, native_call_inflight "
            "FROM ctp_dispatch_commands ORDER BY created_at_ns, command_id"
        ).fetchall()
        statuses = {
            (row["command_id"], row["operation"]): (row["status"], row["native_call_inflight"])
            for row in command_rows
        }
        assert statuses[(prepared_commands[0].command_id, "SUBMIT")] == ("COMPLETED", 0)
        assert statuses[(prepared_commands[1].command_id, "SUBMIT")] == ("COMPLETED", 0)
        assert statuses[(cancel.command_id, "CANCEL")] == ("COMPLETED", 0)
        assert statuses[(third_prepared.command_id, "SUBMIT")] == ("COMPLETED", 0)
    finally:
        candidate.stop()
        store.close()


def test_native_field_factory_action_ref_mismatch_is_unknown_before_req_order_action(
    tmp_path, monkeypatch
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch, native_call_admission=_fake_native_call_admission
    )
    api = _FakeTraderApiFactory.instances[-1]
    try:
        reservation = reserve("i9-fake-action-ref-field-mismatch")
        submit = make_prepared(reservation)
        candidate.stage_and_queue(submit)
        assert candidate.dispatch_next().status == "COMPLETED"
        assert len(candidate.apply_pending_ingress()) == 1

        target = _fresh_fake_target(
            store, candidate._scope, reservation, candidate, _trusted_candidate_types()
        )
        cancel = make_prepared(reservation, "cancel", target=target)
        staged = candidate.stage_and_queue(cancel, cancel_target=target)
        assert type(staged.native_action_ref) is int
        assert staged.native_action_ref != 444

        def mismatched_native_field(_operation, store_payload):
            native_payload = dict(store_payload)
            native_payload["OrderActionRef"] = 444
            return _FakeCtpNativeField(**native_payload)

        candidate._native_field_factory = mismatched_native_field
        with pytest.raises(CtpI9AccountSessionCandidateError):
            candidate.dispatch_next()

        command = store.read_ctp_dispatch_command(candidate._scope, cancel.command_id)
        assert command.status == "UNKNOWN"
        state = store._connection.execute(
            "SELECT native_call_inflight FROM ctp_dispatch_commands WHERE command_id = ?",
            (cancel.command_id,),
        ).fetchone()
        assert state[0] == 0
        owner_row = store._connection.execute(
            "SELECT owner_state FROM ctp_dispatch_callback_session_owners "
            "WHERE owner_intent_id = ?",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert owner_row[0] == "POISONED"
        assert candidate.durable_owner_state == "POISONED"
        assert not any(
            isinstance(call, tuple) and call[0] == "ReqOrderAction" for call in api.calls
        )
        assert api.order_action_calls == []
        callback_rows = store._connection.execute(
            "SELECT COUNT(*) FROM ctp_dispatch_callback_ingress "
            "WHERE owner_intent_id = ? AND callback_name = 'OnRspOrderAction'",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert callback_rows[0] == 0
    finally:
        candidate.stop()
        store.close()


def test_cancel_without_final_native_admission_never_builds_field_or_calls_sdk(
    tmp_path, monkeypatch
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch, native_call_admission=None
    )
    api = _FakeTraderApiFactory.instances[-1]
    try:
        reservation = reserve("i9-cancel-without-final-admission")
        submit = make_prepared(reservation)
        candidate.stage_and_queue(submit)
        assert candidate.dispatch_next().status == "COMPLETED"
        assert len(candidate.apply_pending_ingress()) == 1

        target = _fresh_fake_target(
            store, candidate._scope, reservation, candidate, _trusted_candidate_types()
        )
        cancel = make_prepared(reservation, "cancel", target=target)
        candidate.stage_and_queue(cancel, cancel_target=target)
        factory_calls = []
        original_factory = candidate._native_field_factory

        def observe_native_field_factory(operation, payload):
            factory_calls.append((operation, dict(payload)))
            return original_factory(operation, payload)

        candidate._native_field_factory = observe_native_field_factory
        with pytest.raises(
            CtpI9AccountSessionCandidateError,
            match="native call outcome is unknown; account remains fenced",
        ):
            candidate.dispatch_next()

        command = store.read_ctp_dispatch_command(candidate._scope, cancel.command_id)
        assert command.status == "UNKNOWN"
        assert factory_calls == []
        assert api.order_action_calls == []
        assert not any(
            isinstance(call, tuple) and call[0] == "ReqOrderAction" for call in api.calls
        )
    finally:
        candidate.stop()
        store.close()


def test_cancel_text_action_reference_is_rejected_before_callback_publication(
    tmp_path, monkeypatch
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch
    )
    api = _FakeTraderApiFactory.instances[-1]
    from bt_api_execution.errors import ContractValidationError

    try:
        reservation = reserve("i9-fake-cancel-action-ref-type")
        submit = make_prepared(reservation)
        candidate.stage_and_queue(submit)
        assert candidate.dispatch_next().status == "COMPLETED"
        assert len(candidate.apply_pending_ingress()) == 1

        fresh_target = _fresh_fake_target(
            store, candidate._scope, reservation, candidate, _trusted_candidate_types()
        )
        before = store._connection.execute(
            "SELECT COUNT(*) FROM ctp_dispatch_commands WHERE account_key = ?",
            (candidate._scope.account_key,),
        ).fetchone()[0]
        with pytest.raises(ContractValidationError):
            make_prepared(
                reservation,
                "cancel",
                target=fresh_target,
                inject_action_ref=True,
            )
        after = store._connection.execute(
            "SELECT COUNT(*) FROM ctp_dispatch_commands WHERE account_key = ?",
            (candidate._scope.account_key,),
        ).fetchone()[0]
        assert after == before
        assert not any(
            isinstance(call, tuple) and call[0] == "ReqOrderAction" for call in api.calls
        )
        assert candidate.client._callback_ingress.poisoned is False
        assert candidate._started is True
    finally:
        candidate.stop()
        store.close()


@pytest.mark.parametrize(
    ("return_code", "raises", "callback_timing"),
    [
        (None, False, "none"),
        (False, False, "none"),
        (True, False, "none"),
        (-7, False, "none"),
        (0, True, "none"),
        (None, False, "before"),
        (-7, False, "before"),
    ],
)
def test_native_raw_return_without_typed_no_callback_evidence_is_unknown_and_fenced(
    tmp_path, monkeypatch, return_code, raises, callback_timing
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch
    )
    api = _FakeTraderApiFactory.instances[-1]
    api.order_insert_result = return_code
    api.insert_exception = raises
    api.insert_callback_timing = callback_timing
    try:
        reservation = reserve("i9-fake-ambiguous")
        prepared = make_prepared(reservation)
        candidate.stage_and_queue(prepared)
        with pytest.raises(CtpI9AccountSessionCandidateError, match="outcome is unknown"):
            candidate.dispatch_next()
        command = store.read_ctp_dispatch_command(candidate._scope, prepared.command_id)
        assert command.status == "UNKNOWN"
        command_row = store._connection.execute(
            "SELECT native_call_inflight FROM ctp_dispatch_commands WHERE command_id = ?",
            (prepared.command_id,),
        ).fetchone()
        assert command_row[0] == 0
        projection = store.read_ctp_dispatch_projection(candidate._scope, prepared.command_id)
        assert projection.local_dispatch_outcome == "UNKNOWN"
        owner_row = store._connection.execute(
            "SELECT owner_state FROM ctp_dispatch_callback_session_owners WHERE owner_intent_id = ?",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchone()
        assert owner_row[0] == "POISONED"
        unapplied = store._connection.execute(
            "SELECT event.callback_name FROM ctp_dispatch_callback_ingress AS event "
            "LEFT JOIN ctp_dispatch_callback_ingress_applications AS application "
            "ON application.owner_intent_id = event.owner_intent_id "
            "AND application.source_sequence = event.source_sequence "
            "WHERE event.owner_intent_id = ? AND application.source_sequence IS NULL "
            "ORDER BY event.source_sequence",
            (candidate.owner_handle.owner_intent_id,),
        ).fetchall()
        if callback_timing == "before":
            assert tuple(row[0] for row in unapplied) == ("OnRspOrderInsert",)
        else:
            assert unapplied == []
        assert any(
            row[0] == "ReqOrderInsert" and row[1] == reservation.order_ref for row in api.calls
        )
    finally:
        candidate.stop()
        store.close()


def test_native_callback_after_zero_receipt_is_consumed_from_same_durable_inbox(
    tmp_path, monkeypatch
):
    candidate, store, reserve, make_prepared, _scope_type = _source_candidate_fixture(
        tmp_path, monkeypatch
    )
    api = _FakeTraderApiFactory.instances[-1]
    api.insert_callback_timing = "after"
    try:
        reservation = reserve("i9-fake-late-callback")
        prepared = make_prepared(reservation)
        candidate.stage_and_queue(prepared)
        completed = candidate.dispatch_next()
        assert completed.status == "COMPLETED"
        assert candidate._adapter.read_next_ingress() is None
        assert callable(api.pending_callback)
        api.pending_callback()
        pending = candidate._adapter.read_next_ingress()
        assert pending is not None and pending.callback_name == "OnRspOrderInsert"
        applied = candidate.apply_pending_ingress()
        assert len(applied) == 1
        assert applied[0].callback_key.correlation_key.command_id == prepared.command_id
        assert candidate._adapter.read_next_ingress() is None
    finally:
        candidate.stop()
        store.close()
