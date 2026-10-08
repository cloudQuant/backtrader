"""Synthetic source-fake contracts for the full C01 content validator.

The fixture calls the pinned public V4 capture, snapshot, receipt, and V3
protocol producers. Its native/API leaves are synthetic; it never starts a
provider, child process, SDK client, or network connection.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import time
import types

import pytest

from backtrader_runtime import certification_simnow_c01_native_v4 as worker
from backtrader_runtime import certification_simnow_c01_v3_protocol as protocol


SUITE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "000_live_certification"
    / "simnow_penetration"
)
_VALIDATOR_PATH = SUITE_ROOT / "common" / "c01_root_ledger_v1.py"
_VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "_simnow_c01_root_ledger_v1_test_module", _VALIDATOR_PATH
)
assert _VALIDATOR_SPEC is not None and _VALIDATOR_SPEC.loader is not None
_VALIDATOR_MODULE = importlib.util.module_from_spec(_VALIDATOR_SPEC)
sys.modules[_VALIDATOR_SPEC.name] = _VALIDATOR_MODULE
_VALIDATOR_SPEC.loader.exec_module(_VALIDATOR_MODULE)
AUTHORITY = _VALIDATOR_MODULE.AUTHORITY
CONTENT_STATUS = _VALIDATOR_MODULE.CONTENT_STATUS
C01LedgerContentError = _VALIDATOR_MODULE.C01LedgerContentError
validate_c01_ledger_content_v1 = _VALIDATOR_MODULE.validate_c01_ledger_content_v1


ACCOUNT_SCOPE = "a" * 64
CREDENTIAL_BINDING = "b" * 64
WORKER_SHA256 = hashlib.sha256(Path(worker.__file__).read_bytes()).hexdigest()
WORKER_MODULE_SHA256 = WORKER_SHA256
PROTOCOL_SHA256 = hashlib.sha256(Path(protocol.__file__).read_bytes()).hexdigest()
BROKER_ID = "9999"
USER_ID = "synthetic-user"
TRADING_DAY = "20261002"
CLIENT_INSTANCE_ID = "c" * 32


def _synthetic_stop_receipt():
    receipt_type = type(
        "CtpNativeStopReceipt",
        (),
        {"__module__": "bt_api_ctp.ctp.client"},
    )
    receipt = receipt_type()
    receipt.complete = True
    receipt.join_required = False
    receipt.join_completed = True
    receipt.native_released = True
    receipt.thread_alive = False
    receipt.timed_out = False
    return receipt


def _credentials():
    return {
        "broker_id": BROKER_ID,
        "user_id": USER_ID,
        "password": "synthetic-password",
        "app_id": "synthetic-app",
        "auth_code": "synthetic-auth-code",
        "product_info": "synthetic-product",
    }


def _funds_row():
    row = {
        "BrokerID": BROKER_ID,
        "AccountID": USER_ID,
        "CurrencyID": "CNY",
        "BizType": "1",
        "TradingDay": TRADING_DAY,
    }
    row.update(dict.fromkeys(worker._ACCOUNT_DECIMAL_MEASURES, "0"))
    row.update({"SettlementID": "1", "Available": "80000", "Balance": "100000"})
    return row


def _position_row():
    row = {
        "BrokerID": BROKER_ID,
        "InvestorID": USER_ID,
        "ExchangeID": "CFFEX",
        "InstrumentID": "IF2610",
        "PosiDirection": "2",
        "HedgeFlag": "1",
        "PositionDate": "1",
        "TradingDay": TRADING_DAY,
        "InvestUnitID": "",
        "reserve1": "",
    }
    row.update(dict.fromkeys(worker._POSITION_DECIMAL_MEASURES, "0"))
    row["Position"] = "1"
    return row


def _synthetic_query_result(family, request, rows, client, protocol_module):
    now = datetime.now(timezone.utc)
    request_time = datetime.fromisoformat(request["issued_at_utc"].replace("Z", "+00:00"))
    started_at = max(request_time + timedelta(microseconds=1), now - timedelta(milliseconds=5))
    completed_at = max(started_at + timedelta(microseconds=1), now)
    started_monotonic = request["issued_monotonic_ns"] / 1_000_000_000.0 + 0.000001
    completed_monotonic = max(started_monotonic + 0.000001, time.monotonic())
    request_types = {"orders": "orders", "positions": "positions", "funds": "account"}
    filter_names = (
        ("BrokerID", "ExchangeID", "InstrumentID", "InvestorID", "OrderSysID")
        if family == "orders"
        else ("BrokerID", "InvestorID")
    )
    request_filters = {
        "BrokerID": BROKER_ID,
        "ExchangeID": "",
        "InstrumentID": "",
        "InvestorID": USER_ID,
        "OrderSysID": "",
    }
    source_digest = protocol_module.canonical_sdk_query_records_sha256(list(rows))
    query_module = types.ModuleType("bt_api_ctp.query")
    query_module._QUERY_SOURCE_SEAL = object()
    issuer = object()
    client._query_evidence_issuer = issuer
    source_type = type("_QuerySource", (), {"__module__": "bt_api_ctp.query"})
    source = source_type()
    source._seal = query_module._QUERY_SOURCE_SEAL
    source.issuer = issuer
    source.request_type = request_types[family]
    source.request_id = request["request_id"]
    source.account_fingerprint = "synthetic-fingerprint"
    source.connection_generation = client._connection_generation
    source.trading_day = TRADING_DAY
    source.broker_id = BROKER_ID
    source.investor_id = USER_ID
    source.request_filters = tuple((name, request_filters[name]) for name in filter_names)
    source.explicit_request_filters = ()
    source.started_at_utc = started_at
    source.completed_at_utc = completed_at
    source.started_monotonic = started_monotonic
    source.completed_monotonic = completed_monotonic
    source.clock_domain_id = "python.time.monotonic"
    source.records_sha256 = source_digest
    source.trusted_expires_at_utc = completed_at + timedelta(seconds=35)
    source.trusted_expires_monotonic = completed_monotonic + 35.0

    result_type = type("QueryResult", (), {"__module__": "bt_api_ctp.query"})
    result = result_type()
    result.request_type = request_types[family]
    result.request_id = request["request_id"]
    result.connection_generation = client._connection_generation
    result.complete = True
    result.is_last_seen = True
    result.timed_out = False
    result.unsupported = False
    result.error_code = None
    result.submit_code = 0
    result.records = tuple(dict(row) for row in rows)
    result.late_callback_count = 0
    result.account_fingerprint = "synthetic-fingerprint"
    result.started_at_utc = started_at
    result.completed_at_utc = completed_at
    result.error_message = ""
    result.evidence_complete = True
    result.query_source = source
    return worker._query_result_summary(
        family,
        result,
        request["request_id"],
        client._connection_generation,
        0,
        protocol=protocol_module,
        query_module=query_module,
        client=client,
        expected_broker_id=BROKER_ID,
        expected_user_id=USER_ID,
        expected_trading_day=TRADING_DAY,
        callback_rows=list(rows),
    )


def _source_produced_bundle():
    credentials = _credentials()
    capture = worker.C01NativeCapture(ACCOUNT_SCOPE, CREDENTIAL_BINDING)
    capture.instance_id = CLIENT_INSTANCE_ID
    capture.client_generation = 1
    capture.arrival_generation = 1
    capture._credentials = credentials
    capture.bind_snapshotter(lambda row: dict(row) if isinstance(row, dict) else vars(row))
    client = types.SimpleNamespace(
        _native_api_generation=1,
        _connection_generation=1,
        _native_api=None,
        _thread=None,
        _join_active=False,
        _native_init_started=False,
        _last_stop_join_required=False,
        _last_stop_native_released=True,
    )
    capture.bind_client(client)

    auth_fields = {
        "BrokerID": BROKER_ID,
        "UserID": USER_ID,
        "AppID": credentials["app_id"],
        "AuthCode": credentials["auth_code"],
    }
    capture.native_request(
        "ReqAuthenticate",
        101,
        lambda: (
            capture.response_callback(
                "OnRspAuthenticate", 101, types.SimpleNamespace(ErrorID=0), True, None
            ),
            0,
        )[1],
        native_field=auth_fields,
        credentials=credentials,
    )
    time.sleep(0.002)
    login_fields = {
        "BrokerID": BROKER_ID,
        "UserID": USER_ID,
        "Password": credentials["password"],
    }
    login_row = types.SimpleNamespace(
        BrokerID=BROKER_ID,
        UserID=USER_ID,
        FrontID=8,
        SessionID=9001,
        TradingDay=TRADING_DAY,
    )
    capture.native_request(
        "ReqUserLogin",
        102,
        lambda: (
            capture.response_callback(
                "OnRspUserLogin",
                102,
                types.SimpleNamespace(ErrorID=0),
                True,
                login_row,
                login_field=True,
            ),
            0,
        )[1],
        native_field=login_fields,
        credentials=credentials,
    )

    artifacts = {}
    snapshots = []
    for phase in ("baseline", "final"):
        capture.set_phase(phase)
        for family, method, callback_name, request_id in (
            ("orders", "ReqQryOrder", "OnRspQryOrder", 201 if phase == "baseline" else 204),
            (
                "positions",
                "ReqQryInvestorPosition",
                "OnRspQryInvestorPosition",
                202 if phase == "baseline" else 205,
            ),
            (
                "funds",
                "ReqQryTradingAccount",
                "OnRspQryTradingAccount",
                203 if phase == "baseline" else 206,
            ),
        ):
            native_field = {"BrokerID": BROKER_ID, "InvestorID": USER_ID}
            row = _funds_row() if family == "funds" else None

            def invoke_query(
                cb=callback_name,
                rid=request_id,
                item=row,
                multi=(phase == "baseline" and family == "orders"),
            ):
                if multi:
                    capture.response_callback(
                        cb, rid, types.SimpleNamespace(ErrorID=0), False, None
                    )
                capture.response_callback(cb, rid, types.SimpleNamespace(ErrorID=0), True, item)
                return 0

            capture.native_request(
                method,
                request_id,
                invoke_query,
                native_field=native_field,
                credentials=credentials,
            )
            request = capture.requests_by_id[request_id]
            rows = [row] if row is not None else []
            request["sdk_query_result"] = _synthetic_query_result(
                family, request, rows, client, protocol
            )
        _document, artifact = worker._private_snapshot(
            protocol, capture, phase, 8, "9001", TRADING_DAY
        )
        artifacts[artifact["summary"]["artifact_ref"]] = artifact["bytes"]
        snapshots.append({"summary": artifact["summary"]})

    pair = protocol.C01PairBinding(
        selected_index=0,
        selection_sha256="d" * 64,
        md_front_sha256="e" * 64,
        td_front_sha256="f" * 64,
        td_front="tcp://192.0.2.2:10002",
        selected_at_utc="2026-10-02T01:02:03Z",
    )
    launch = types.SimpleNamespace(
        pair_binding=pair,
        run_nonce="1" * 32,
        parent_pid=os.getpid() + 1000,
        account_scope_sha256=ACCOUNT_SCOPE,
        credential_binding_sha256=CREDENTIAL_BINDING,
    )
    stopped_api = object()
    client._c01_no_join_api = stopped_api
    client._last_stopped_native_api = stopped_api
    client._last_stop_native_released = True
    assert capture._failure is None, capture._failure
    previous_worker_pin = getattr(
        sys.modules["__main__"], "__c01_verified_worker_source_sha256__", None
    )
    sys.modules["__main__"].__c01_verified_worker_source_sha256__ = WORKER_SHA256
    try:
        payload = worker._build_worker_receipt(
            protocol,
            launch,
            credentials,
            capture,
            client,
            snapshots,
            _synthetic_stop_receipt(),
        )
    finally:
        if previous_worker_pin is None:
            delattr(sys.modules["__main__"], "__c01_verified_worker_source_sha256__")
        else:
            sys.modules["__main__"].__c01_verified_worker_source_sha256__ = previous_worker_pin
    receipt = protocol.parse_worker_frame(protocol.encode_worker_frame(payload))
    return {
        "worker": receipt.to_dict(),
        "artifacts": artifacts,
        "pair": pair.to_dict(),
        "worker_sha256": WORKER_SHA256,
    }


@pytest.fixture(scope="module")
def bundle():
    return _source_produced_bundle()


def _validate(
    bundle,
    worker_payload=None,
    artifacts=None,
    *,
    protocol_module=protocol,
    worker_module=worker,
):
    return validate_c01_ledger_content_v1(
        bundle["worker"] if worker_payload is None else worker_payload,
        bundle["artifacts"] if artifacts is None else artifacts,
        protocol_module=protocol_module,
        worker_module=worker_module,
        expected_worker_source_sha256=bundle["worker_sha256"],
        expected_protocol_source_sha256=PROTOCOL_SHA256,
        expected_worker_module_source_sha256=WORKER_MODULE_SHA256,
        expected_pair_binding=bundle["pair"],
        expected_account_scope_sha256=ACCOUNT_SCOPE,
        expected_credential_binding_sha256=CREDENTIAL_BINDING,
    )


def _copy_worker(bundle):
    return json.loads(json.dumps(bundle["worker"]))


def _snapshot_doc(raw):
    return json.loads(raw.decode("utf-8"))


def _canonical_snapshot(document):
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _replace_projection_in_both_phases(bundle, projection_name, projection_value):
    worker_payload = _copy_worker(bundle)
    artifacts = dict(bundle["artifacts"])
    digest_key = {
        "open_order_refs": "open_order_refs_sha256",
        "order_economics": "order_economics_sha256",
        "positions": "positions_sha256",
        "funds": "funds_sha256",
    }[projection_name]
    for index, phase in enumerate(("baseline", "final")):
        artifact_ref = "snapshots/" + phase + ".json"
        document = _snapshot_doc(artifacts[artifact_ref])
        document["projections"][projection_name] = projection_value
        raw = _canonical_snapshot(document)
        artifacts[artifact_ref] = raw
        worker_payload["snapshots"][index][digest_key] = protocol.canonical_value_sha256(
            projection_value
        )
        worker_payload["snapshots"][index]["artifact_sha256"] = hashlib.sha256(raw).hexdigest()
    return worker_payload, artifacts


def test_pinned_v4_producer_v3_receipt_and_full_six_query_bundle_are_content_only(bundle):
    result = _validate(bundle)

    assert result.request_count == 8
    assert result.auth_login_callback_count == 2
    assert result.query_request_count == 6
    assert result.query_callback_count == 7
    assert result.snapshot_count == 2
    assert result.activity_callback_count == 0
    assert result.write_invocation_count == 0
    assert result.native_close_complete is True
    assert result.native_released is True
    assert result.native_thread_alive is False
    assert result.native_timed_out is False
    assert result.provider_source_sequence == 0
    assert result.authority == AUTHORITY == "NONE"
    assert result.status == CONTENT_STATUS == "CONTENT_VALIDATED_ONLY"
    assert result.certification_pass is False
    assert result.source_authenticity_verified is False
    assert len(result.requests) == 8
    assert len(result.callbacks) == 9
    assert len(result.query_receipts) == 6
    assert len(result._snapshot_facts) == 2
    assert [item.phase for item in result._snapshot_facts] == ["baseline", "final"]
    assert [item.family for item in result._snapshot_facts[0].queries] == [
        "orders",
        "positions",
        "funds",
    ]
    rendered = repr(result) + repr(result._snapshot_facts) + repr(result.query_receipts)
    assert "synthetic-user" not in rendered
    assert ACCOUNT_SCOPE not in rendered
    assert CREDENTIAL_BINDING not in rendered
    summary = result.safe_summary()
    assert set(summary) == {
        "schema",
        "status",
        "authority",
        "certification_pass",
        "source_authenticity_verified",
        "provider_source_sequence",
        "request_count",
        "auth_login_callback_count",
        "query_request_count",
        "query_callback_count",
        "snapshot_count",
        "activity_callback_count",
        "write_invocation_count",
        "native_close_complete",
        "native_released",
        "native_thread_alive",
        "native_timed_out",
    }
    assert not any("sha256" in key or "account" in key or "credential" in key for key in summary)


def test_module_dependencies_require_the_fixed_module_interfaces(bundle):
    with pytest.raises(C01LedgerContentError, match="source_module_invalid"):
        _validate(bundle, protocol_module=object())


def test_duplicate_request_id_is_not_hidden_by_grouping(bundle):
    payload = _copy_worker(bundle)
    payload["requests"][3]["request_id"] = payload["requests"][2]["request_id"]

    with pytest.raises(C01LedgerContentError):
        _validate(bundle, payload)


def test_extra_duplicate_callback_is_rejected_even_with_matching_request_key(bundle):
    payload = _copy_worker(bundle)
    payload["callbacks"].append(dict(payload["callbacks"][-1]))

    with pytest.raises(C01LedgerContentError):
        _validate(bundle, payload)


def test_query_terminal_callback_must_be_last_in_its_full_group(bundle):
    payload = _copy_worker(bundle)
    callbacks = [
        item
        for item in payload["callbacks"]
        if (item["kind"], item["phase"], item["family"]) == ("query", "baseline", "orders")
    ]
    assert len(callbacks) == 2
    callbacks[0]["is_last"] = True

    with pytest.raises(C01LedgerContentError, match="query_callback_terminal_order_invalid"):
        _validate(bundle, payload)


def test_local_callback_sequence_must_be_unique_and_after_request(bundle):
    payload = _copy_worker(bundle)
    callback = next(item for item in payload["callbacks"] if item["kind"] == "login")
    login_request = next(item for item in payload["requests"] if item["kind"] == "login")
    callback["local_sequence"] = login_request["local_sequence"]

    with pytest.raises(C01LedgerContentError):
        _validate(bundle, payload)


def test_query_receipt_rejects_boolean_alias_for_native_request_id(bundle):
    payload = _copy_worker(bundle)
    payload["requests"][2]["sdk_query_result"]["request_id"] = True

    with pytest.raises(C01LedgerContentError):
        _validate(bundle, payload)


def test_authentication_cannot_supply_login_identity_fields(bundle):
    payload = _copy_worker(bundle)
    auth = next(item for item in payload["callbacks"] if item["kind"] == "authenticate")
    auth["front_id"] = 8

    with pytest.raises(C01LedgerContentError):
        _validate(bundle, payload)


def test_private_snapshot_callback_multiset_must_exactly_match_worker_callbacks(bundle):
    artifacts = dict(bundle["artifacts"])
    document = _snapshot_doc(artifacts["snapshots/baseline.json"])
    callbacks = document["queries"]["orders"]["callbacks"]
    callbacks.append(dict(callbacks[-1]))
    artifacts["snapshots/baseline.json"] = _canonical_snapshot(document)
    payload = _copy_worker(bundle)
    payload["snapshots"][0]["artifact_sha256"] = hashlib.sha256(
        artifacts["snapshots/baseline.json"]
    ).hexdigest()

    with pytest.raises(C01LedgerContentError):
        _validate(bundle, payload, artifacts)


def test_native_write_and_release_failures_remain_content_blockers(bundle):
    for mutate in (
        lambda payload: payload["write_counters"].__setitem__("ReqOrderAction", 1),
        lambda payload: payload["native_close"].__setitem__("native_released", False),
    ):
        payload = _copy_worker(bundle)
        mutate(payload)
        with pytest.raises(C01LedgerContentError):
            _validate(bundle, payload)


def test_query_rows_are_recomputed_from_held_private_bytes(bundle):
    artifacts = dict(bundle["artifacts"])
    document = _snapshot_doc(artifacts["snapshots/final.json"])
    row = document["queries"]["funds"]["callbacks"][0]["row"]
    row["Available"] = "80001"
    artifacts["snapshots/final.json"] = _canonical_snapshot(document)
    payload = _copy_worker(bundle)
    payload["snapshots"][1]["artifact_sha256"] = hashlib.sha256(
        artifacts["snapshots/final.json"]
    ).hexdigest()

    with pytest.raises(C01LedgerContentError):
        _validate(bundle, payload, artifacts)


def test_v3_parser_rejects_malformed_projection_with_matching_summary_digests(bundle):
    payload, artifacts = _replace_projection_in_both_phases(bundle, "positions", "malformed")
    for phase in ("baseline", "final"):
        with pytest.raises(protocol.C01ProtocolError, match="private_snapshot_positions_invalid"):
            protocol.parse_private_snapshot_artifact(artifacts["snapshots/" + phase + ".json"])

    with pytest.raises(C01LedgerContentError, match="snapshot_protocol_invalid"):
        _validate(bundle, payload, artifacts)


def test_projection_must_match_query_rows_even_when_v3_projection_shape_is_valid(bundle):
    phantom_positions = worker.project_gross_positions(
        [_position_row()],
        expected_broker_id=BROKER_ID,
        expected_user_id=USER_ID,
        trading_day=TRADING_DAY,
    )
    payload, artifacts = _replace_projection_in_both_phases(bundle, "positions", phantom_positions)
    for phase in ("baseline", "final"):
        protocol.parse_private_snapshot_artifact(artifacts["snapshots/" + phase + ".json"])

    with pytest.raises(C01LedgerContentError, match="snapshot_projection_rows_mismatch"):
        _validate(bundle, payload, artifacts)
