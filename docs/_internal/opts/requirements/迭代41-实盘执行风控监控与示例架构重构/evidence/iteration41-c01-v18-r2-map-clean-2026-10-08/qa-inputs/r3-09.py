"""Fake-only acceptance of the isolated C01 contract and private artifacts."""
from __future__ import annotations

import hashlib
import json
import pytest

from backtrader_runtime.certification_simnow_c01_v2_contract import (
    _projection_order_economics,
    _projection_order_refs,
    validate_c01_candidate,
)
from backtrader_runtime.certification_simnow_c01_v2_protocol import (
    ACCOUNT_DIAGNOSTIC_FIELD_SOURCES,
    ACCOUNT_DIMENSION_FIELDS,
    ACCOUNT_ECONOMICS_SCHEMA,
    ACCOUNT_NUMERIC_MEASURES,
    C01PairBinding,
    C01ProcessLifecycleReceipt,
    C01ProtocolError,
    ORDER_DECIMAL_MEASURES,
    ORDER_ECONOMICS_SCHEMA,
    ORDER_IDENTITY_INTEGER_FIELDS,
    ORDER_IDENTITY_TEXT_FIELDS,
    ORDER_INTEGER_MEASURES,
    ORDER_TEXT_MEASURES,
    POSITION_BUCKET_DIMENSIONS,
    POSITION_BUCKET_SCHEMA,
    canonical_sdk_query_records_sha256,
    canonical_value_sha256,
    compute_account_scope_sha256,
    encode_private_snapshot_artifact,
    encode_worker_frame,
    parse_worker_frame,
    parse_private_snapshot_artifact,
    sha256_bytes,
)

_BROKER_ID = "9999"
_USER_ID = "fake-user"
_ACCOUNT_SCOPE_SHA256 = compute_account_scope_sha256(_BROKER_ID, _USER_ID)
_CREDENTIAL_BINDING_SHA256 = "7" * 64
_WORKER_SHA256 = "9" * 64
_TRADING_DAY = "20261002"


def _sdk_query_summary(family, request_id, records=()):
    request_type = "account" if family == "funds" else family
    record_digest = canonical_sdk_query_records_sha256(records)
    started = "2026-10-02T01:02:03+00:00"
    completed = "2026-10-02T01:02:04+00:00"
    filters = (
        [
            ["BrokerID", _BROKER_ID],
            ["ExchangeID", ""],
            ["InstrumentID", ""],
            ["InvestorID", _USER_ID],
            ["OrderSysID", ""],
        ]
        if family == "orders"
        else [["BrokerID", _BROKER_ID], ["InvestorID", _USER_ID]]
    )
    source = {
        "source_type": "bt_api_ctp.query._QuerySource",
        "seal_valid": True,
        "issuer_is_client_query_lane": True,
        "request_type": request_type,
        "request_id": request_id,
        "account_fingerprint": "synthetic-account-fingerprint",
        "connection_generation": 1,
        "trading_day": _TRADING_DAY,
        "broker_id": _BROKER_ID,
        "investor_id": _USER_ID,
        "request_filters": filters,
        "explicit_request_filters": [],
        "started_at_utc": started,
        "completed_at_utc": completed,
        "started_monotonic_hex": float(10.0 + request_id).hex(),
        "completed_monotonic_hex": float(11.0 + request_id).hex(),
        "clock_domain_id": "python.time.monotonic",
        "records_sha256": record_digest,
        "trusted_expires_at_utc": "2026-10-02T01:02:39+00:00",
        "trusted_expires_monotonic_hex": float(46.0 + request_id).hex(),
    }
    return {
        "result_type": "bt_api_ctp.query.QueryResult",
        "request_type": request_type,
        "request_id": request_id,
        "connection_generation": 1,
        "complete": True,
        "evidence_complete": True,
        "is_last_seen": True,
        "timed_out": False,
        "unsupported": False,
        "error_code": None,
        "account_fingerprint": "synthetic-account-fingerprint",
        "started_at_utc": started,
        "completed_at_utc": completed,
        "error_message": "",
        "submit_code": 0,
        "record_count": len(records),
        "late_callback_count": 0,
        "error_semantics": "SDK_QUERY_NULL_ERROR_CODE_NO_FAILURE",
        "records_sha256": record_digest,
        "callback_records_sha256": record_digest,
        "query_source": source,
    }


def _rebind_snapshot_query(document, family):
    request = document["queries"][family]["request"]
    callbacks = document["queries"][family]["callbacks"]
    records = tuple(item["row"] for item in callbacks if item["row_present"] is True)
    request["sdk_query_result"] = _sdk_query_summary(family, request["request_id"], records)
    return request["sdk_query_result"]


def _rebind_worker_query(payload, phase, family, sdk_result):
    request = next(
        item
        for item in payload["requests"]
        if item["kind"] == "query" and item["phase"] == phase and item["family"] == family
    )
    request["sdk_query_result"] = sdk_result


def _pair():
    td_front = "tcp://127.0.0.1:41205"
    return C01PairBinding(
        selected_index=3,
        selection_sha256="a" * 64,
        md_front_sha256="b" * 64,
        td_front_sha256=hashlib.sha256(td_front.encode("utf-8")).hexdigest(),
        td_front=td_front,
        selected_at_utc="2026-10-02T01:02:03Z",
    )


def _account_row():
    row = {
        "BrokerID": _BROKER_ID,
        "AccountID": _USER_ID,
        "CurrencyID": "CNY",
        "BizType": "1",
        "TradingDay": _TRADING_DAY,
    }
    row.update(dict.fromkeys(ACCOUNT_NUMERIC_MEASURES, "0"))
    row.update({"SettlementID": "1", "Available": "80000", "Balance": "100000"})
    return row


def _active_order_row(*, limit_price="100.25", volume_traded=1):
    row = {
        "BrokerID": _BROKER_ID,
        "InvestorID": _USER_ID,
        "ExchangeID": "SHFE",
        "InstrumentID": "rb2610",
        "OrderSysID": "sys-1",
        "OrderRef": "100001",
        "TradingDay": _TRADING_DAY,
        "FrontID": 8,
        "SessionID": 9,
        "LimitPrice": limit_price,
        "StopPrice": "0",
        "VolumeTotalOriginal": 2,
        "VolumeTraded": volume_traded,
        "VolumeTotal": 2 - volume_traded,
        "MinVolume": 1,
        "IsAutoSuspend": 0,
        "UserForceClose": 0,
        "Direction": "0",
        "CombOffsetFlag": "0",
        "CombHedgeFlag": "1",
        "OrderPriceType": "2",
        "TimeCondition": "3",
        "VolumeCondition": "1",
        "ContingentCondition": "1",
        "ForceCloseReason": "0",
        "OrderStatus": "1",
        "OrderSubmitStatus": "3",
    }
    return row


def _funds_projection(row):
    measures = {field: row[field] for field in ACCOUNT_NUMERIC_MEASURES}
    return {
        "schema": ACCOUNT_ECONOMICS_SCHEMA,
        "dimensions": {field: row[field] for field in ACCOUNT_DIMENSION_FIELDS},
        "measures": measures,
        "diagnostic_field_sources": dict(ACCOUNT_DIAGNOSTIC_FIELD_SOURCES),
        "diagnostics": {
            alias: measures[source] for alias, source in ACCOUNT_DIAGNOSTIC_FIELD_SOURCES.items()
        },
    }


def _query_artifact(payload, phase, family, account_row):
    request = next(
        item
        for item in payload["requests"]
        if item["kind"] == "query" and item["phase"] == phase and item["family"] == family
    )
    callbacks = []
    for callback in payload["callbacks"]:
        if (
            callback["kind"] == "query"
            and callback["phase"] == phase
            and callback["family"] == family
        ):
            callbacks.append(
                {
                    "callback_name": callback["callback_name"],
                    "request_id": callback["request_id"],
                    "error_id": callback["error_id"],
                    "rsp_info_present": callback["rsp_info_present"],
                    "error_semantics": callback["error_semantics"],
                    "is_last": callback["is_last"],
                    "request_generation": callback["request_generation"],
                    "local_sequence": callback["local_sequence"],
                    "arrived_at_utc": callback["arrived_at_utc"],
                    "arrived_monotonic_ns": callback["arrived_monotonic_ns"],
                    "row_present": callback["row_present"],
                    "row": account_row if family == "funds" else None,
                }
            )
    return {
        "request": {
            field: request[field]
            for field in (
                "method",
                "request_id",
                "request_generation",
                "local_sequence",
                "issued_at_utc",
                "issued_monotonic_ns",
                "return_code",
                "sdk_query_result",
            )
        },
        "callbacks": callbacks,
    }


def _artifact_bundle(payload):
    artifacts = {}
    docs = {}
    account_row = _account_row()
    for phase in ("baseline", "final"):
        doc = {
            "protocol": "backtrader.simnow.c01.v2",
            "version": 2,
            "case_id": "C01",
            "phase": phase,
            "account_scope_sha256": _ACCOUNT_SCOPE_SHA256,
            "credential_binding_sha256": _CREDENTIAL_BINDING_SHA256,
            "client": {
                "instance_id": "local-client-1",
                "client_generation": 1,
                "arrival_generation": 1,
            },
            "scope": {
                "front_id": 8,
                "session_id": "fake-session",
                "trading_day": _TRADING_DAY,
            },
            "queries": {
                family: _query_artifact(payload, phase, family, account_row)
                for family in ("orders", "positions", "funds")
            },
            "projections": {
                "open_order_refs": [],
                "order_economics": {"schema": ORDER_ECONOMICS_SCHEMA, "rows": []},
                "positions": {
                    "schema": POSITION_BUCKET_SCHEMA,
                    "dimensions": list(POSITION_BUCKET_DIMENSIONS),
                    "buckets": [],
                },
                "funds": _funds_projection(account_row),
            },
        }
        ref = "snapshots/{}.json".format(phase)
        frame = encode_private_snapshot_artifact(doc)
        artifacts[ref] = frame
        docs[phase] = (doc, frame)
    return artifacts, docs


def _bind_active_order_rows(payload, artifacts, rows_by_phase):
    for phase, row in rows_by_phase.items():
        ref = "snapshots/{}.json".format(phase)
        document = json.loads(artifacts[ref])
        callback = document["queries"]["orders"]["callbacks"][0]
        callback["row_present"] = True
        callback["row"] = row
        sdk_result = _rebind_snapshot_query(document, "orders")
        parsed = parse_private_snapshot_artifact(encode_private_snapshot_artifact(document))
        document["projections"]["order_economics"] = _projection_order_economics(
            parsed, _BROKER_ID, _USER_ID
        )
        frame = encode_private_snapshot_artifact(document)
        artifacts[ref] = frame
        _rebind_worker_query(payload, phase, "orders", sdk_result)

        snapshot_index = 0 if phase == "baseline" else 1
        summary = payload["snapshots"][snapshot_index]
        summary["artifact_sha256"] = sha256_bytes(frame)
        summary["order_economics_sha256"] = canonical_value_sha256(
            document["projections"]["order_economics"]
        )
        summary["queries"]["orders"]["row_count"] = 1
        receipt_callback = next(
            item
            for item in payload["callbacks"]
            if item["kind"] == "query" and item["phase"] == phase and item["family"] == "orders"
        )
        receipt_callback["row_present"] = True
    return artifacts


def _payload():
    requests = []
    callbacks = []
    sequence = 0
    request_id = 500
    query_summaries = {"baseline": {}, "final": {}}

    def request(kind, phase, family, method):
        nonlocal sequence, request_id
        sequence += 1
        request_id += 1
        row = {
            "kind": kind,
            "phase": phase,
            "family": family,
            "method": method,
            "request_id": request_id,
            "request_generation": len(requests) + 1,
            "local_sequence": sequence,
            "issued_at_utc": "2026-10-02T01:02:03.{:06d}Z".format(sequence),
            "issued_monotonic_ns": sequence * 1_000_000,
            "return_code": 0,
            "sdk_query_result": None,
            "receipt_origin": "local_native_invocation",
            "account_scope_sha256": _ACCOUNT_SCOPE_SHA256,
            "credential_binding_sha256": _CREDENTIAL_BINDING_SHA256,
        }
        requests.append(row)
        return row

    def callback(call, name, *, row_present=None, front_id=None, session_id=None, trading_day=None):
        nonlocal sequence
        sequence += 1
        row = {
            "kind": call["kind"],
            "phase": call["phase"],
            "family": call["family"],
            "callback_name": name,
            "request_id": call["request_id"],
            "error_id": 0,
            "rsp_info_present": True,
            "error_semantics": "RSP_INFO_ERROR_ID_PRESENT",
            "is_last": True,
            "request_generation": call["request_generation"],
            "client_instance_id": "local-client-1",
            "client_generation": 1,
            "arrival_generation": 1,
            "local_sequence": sequence,
            "arrived_at_utc": "2026-10-02T01:02:03.{:06d}Z".format(sequence),
            "arrived_monotonic_ns": sequence * 1_000_000,
            "row_present": row_present,
            "front_id": front_id,
            "session_id": session_id,
            "trading_day": trading_day,
            "account_scope_sha256": _ACCOUNT_SCOPE_SHA256,
            "credential_binding_sha256": _CREDENTIAL_BINDING_SHA256,
        }
        callbacks.append(row)
        return row

    auth = request("authenticate", None, None, "ReqAuthenticate")
    callback(auth, "OnRspAuthenticate")
    login = request("login", None, None, "ReqUserLogin")
    callback(
        login,
        "OnRspUserLogin",
        front_id=8,
        session_id="fake-session",
        trading_day=_TRADING_DAY,
    )
    for phase in ("baseline", "final"):
        for family, method, callback_name in (
            ("orders", "ReqQryOrder", "OnRspQryOrder"),
            ("positions", "ReqQryInvestorPosition", "OnRspQryInvestorPosition"),
            ("funds", "ReqQryTradingAccount", "OnRspQryTradingAccount"),
        ):
            call = request("query", phase, family, method)
            cb = callback(call, callback_name, row_present=(family == "funds"))
            records = (_account_row(),) if family == "funds" else ()
            call["sdk_query_result"] = _sdk_query_summary(family, call["request_id"], records)
            query_summaries[phase][family] = {
                "request_id": call["request_id"],
                "callback_count": 1,
                "row_count": 1 if family == "funds" else 0,
                "first_sequence": cb["local_sequence"],
                "terminal_sequence": cb["local_sequence"],
            }

    payload = {
        "protocol": "backtrader.simnow.c01.v2",
        "message_type": "worker_receipt",
        "version": 2,
        "case_id": "C01",
        "run_nonce": "f" * 32,
        "parent_pid": 200,
        "worker_pid": 201,
        "worker_source_sha256": _WORKER_SHA256,
        "pair_binding": _pair().to_dict(),
        "account_scope_sha256": _ACCOUNT_SCOPE_SHA256,
        "credential_binding_sha256": _CREDENTIAL_BINDING_SHA256,
        "client": {
            "instance_id": "local-client-1",
            "client_generation": 1,
            "arrival_generation": 1,
        },
        "requests": requests,
        "callbacks": callbacks,
        "snapshots": [],
        "write_counters": {"ReqOrderInsert": 0, "ReqOrderAction": 0},
        "native_close": {
            "receipt_type": "CtpNativeStopReceipt",
            "lifecycle_mode": "NO_JOIN_RELEASE_RETURNED",
            "join_required": False,
            "join_completed": True,
            "native_released": True,
            "thread_alive": False,
            "timed_out": False,
        },
        "terminal_state": "normal",
    }
    artifacts, docs = _artifact_bundle(payload)
    for phase in ("baseline", "final"):
        doc, frame = docs[phase]
        payload["snapshots"].append(
            {
                "phase": phase,
                "artifact_ref": "snapshots/{}.json".format(phase),
                "artifact_sha256": sha256_bytes(frame),
                "client_instance_id": "local-client-1",
                "client_generation": 1,
                "arrival_generation": 1,
                "session_id": "fake-session",
                "trading_day": _TRADING_DAY,
                "queries": query_summaries[phase],
                "open_order_refs_sha256": canonical_value_sha256(
                    doc["projections"]["open_order_refs"]
                ),
                "order_economics_sha256": canonical_value_sha256(
                    doc["projections"]["order_economics"]
                ),
                "positions_sha256": canonical_value_sha256(doc["projections"]["positions"]),
                "funds_sha256": canonical_value_sha256(doc["projections"]["funds"]),
                "account_scope_sha256": _ACCOUNT_SCOPE_SHA256,
                "credential_binding_sha256": _CREDENTIAL_BINDING_SHA256,
            }
        )
    return payload


def _process():
    return C01ProcessLifecycleReceipt(
        run_nonce="f" * 32,
        parent_pid=200,
        worker_pid=201,
        worker_source_sha256=_WORKER_SHA256,
        assigned_before_resume=True,
        stdin_fully_sent=True,
        stdout_eof=True,
        stderr_eof=True,
        process_exit_observed=True,
        process_exit_code=0,
        job_active_count=0,
        handles_closed=True,
        timed_out=False,
        forced_kill=False,
        containment="windows_job",
        reason="normal_exit",
        status="BLOCKED",
    )


def _validate(payload=None, process=None, *, pair=None, worker_sha=None, artifacts=None):
    payload = _payload() if payload is None else payload
    if artifacts is None:
        artifacts, _ = _artifact_bundle(payload)
    worker = parse_worker_frame(encode_worker_frame(payload))
    return validate_c01_candidate(
        worker,
        _process() if process is None else process,
        expected_pair_binding=_pair() if pair is None else pair,
        expected_worker_source_sha256=_WORKER_SHA256 if worker_sha is None else worker_sha,
        expected_account_scope_sha256=_ACCOUNT_SCOPE_SHA256,
        expected_credential_binding_sha256=_CREDENTIAL_BINDING_SHA256,
        private_snapshot_artifacts=artifacts,
        expected_broker_id=_BROKER_ID,
        expected_user_id=_USER_ID,
    )


def test_complete_fake_receipt_is_structurally_eligible_but_never_passes():
    result = _validate()

    assert result.eligible_for_protected_admission is True
    assert result.status == "BLOCKED"
    assert result.reasons == ("protected_actor_must_admit_source_native_and_artifact_custody",)


def test_query_source_identity_must_match_root_private_account_scope():
    payload = _payload()
    artifacts, _ = _artifact_bundle(payload)
    document = json.loads(artifacts["snapshots/baseline.json"])
    for family in ("orders", "positions", "funds"):
        sdk_result = document["queries"][family]["request"]["sdk_query_result"]
        source = sdk_result["query_source"]
        source["broker_id"] = "8888"
        source["request_filters"][0][1] = "8888"
        _rebind_worker_query(payload, "baseline", family, sdk_result)
    frame = encode_private_snapshot_artifact(document)
    artifacts["snapshots/baseline.json"] = frame
    payload["snapshots"][0]["artifact_sha256"] = sha256_bytes(frame)

    result = _validate(payload, artifacts=artifacts)

    assert result.eligible_for_protected_admission is False
    assert "baseline_orders_query_source_account_mismatch" in result.reasons
    assert result.checked_request_count == 8
    assert result.checked_query_callback_count == 6
    assert result.checked_snapshot_count == 2


def test_absent_query_callback_info_keeps_raw_none_without_rewriting_query_semantics():
    payload = _payload()
    payload["callbacks"][2]["error_id"] = None
    payload["callbacks"][2]["rsp_info_present"] = False
    payload["callbacks"][2]["error_semantics"] = "RSP_INFO_ABSENT"
    artifacts, _ = _artifact_bundle(payload)
    for summary, phase in zip(payload["snapshots"], ("baseline", "final")):
        summary["artifact_sha256"] = sha256_bytes(artifacts["snapshots/{}.json".format(phase)])

    result = _validate(payload, artifacts=artifacts)

    assert result.eligible_for_protected_admission is True
    assert result.status == "BLOCKED"
    assert result.reasons == ("protected_actor_must_admit_source_native_and_artifact_custody",)


def test_absent_query_rsp_info_cannot_be_rewritten_as_error_id_zero():
    payload = _payload()
    payload["callbacks"][2]["rsp_info_present"] = False
    payload["callbacks"][2]["error_semantics"] = "RSP_INFO_ABSENT"

    with pytest.raises(C01ProtocolError, match="callback_absent_rsp_info_mismatch"):
        _validate(payload)


def test_order_or_trade_notification_blocks_the_no_activity_case():
    payload = _payload()
    payload["callbacks"].append(
        {
            "kind": "order_activity",
            "phase": None,
            "family": None,
            "callback_name": "OnRtnOrder",
            "request_id": None,
            "error_id": None,
            "rsp_info_present": None,
            "error_semantics": None,
            "is_last": None,
            "request_generation": None,
            "client_instance_id": "local-client-1",
            "client_generation": 1,
            "arrival_generation": 1,
            "local_sequence": 17,
            "arrived_at_utc": "2026-10-02T01:02:03.000017Z",
            "arrived_monotonic_ns": 17_000_000,
            "row_present": None,
            "front_id": None,
            "session_id": None,
            "trading_day": None,
            "account_scope_sha256": _ACCOUNT_SCOPE_SHA256,
            "credential_binding_sha256": _CREDENTIAL_BINDING_SHA256,
        }
    )

    result = _validate(payload)

    assert result.eligible_for_protected_admission is False
    assert "native_order_or_trade_activity_observed" in result.reasons


def test_position_or_full_funds_projection_change_blocks_c01():
    payload = _payload()
    payload["snapshots"][1]["funds_sha256"] = "4" * 64

    result = _validate(payload)

    assert result.eligible_for_protected_admission is False
    assert "baseline_final_funds_sha256_changed" in result.reasons


def test_forged_or_unbound_private_artifact_blocks_candidate():
    payload = _payload()
    artifacts, _ = _artifact_bundle(payload)
    document = json.loads(artifacts["snapshots/final.json"])
    document["projections"]["funds"]["measures"]["Commission"] = "3"
    artifacts["snapshots/final.json"] = encode_private_snapshot_artifact(document)

    result = _validate(payload, artifacts=artifacts)

    assert result.eligible_for_protected_admission is False
    assert "final_private_snapshot_artifact_hash_or_ref_mismatch" in result.reasons
    assert "final_private_snapshot_funds_digest_mismatch" in result.reasons
    assert "final_private_snapshot_funds_projection_mismatch" in result.reasons


def test_non_alias_account_economic_field_change_blocks_stable_snapshot():
    payload = _payload()
    artifacts, _ = _artifact_bundle(payload)
    baseline = json.loads(artifacts["snapshots/baseline.json"])
    row = baseline["queries"]["funds"]["callbacks"][0]["row"]
    row["Commission"] = "3"
    sdk_result = _rebind_snapshot_query(baseline, "funds")
    _rebind_worker_query(payload, "baseline", "funds", sdk_result)
    baseline["projections"]["funds"]["measures"]["Commission"] = "3"
    frame = encode_private_snapshot_artifact(baseline)
    artifacts["snapshots/baseline.json"] = frame
    payload["snapshots"][0]["artifact_sha256"] = sha256_bytes(frame)
    payload["snapshots"][0]["funds_sha256"] = canonical_value_sha256(
        baseline["projections"]["funds"]
    )

    result = _validate(payload, artifacts=artifacts)

    assert result.eligible_for_protected_admission is False
    assert "baseline_final_funds_sha256_changed" in result.reasons


def test_account_scope_ids_are_recomputed_and_funds_account_id_is_bound():
    payload = _payload()
    artifacts, _ = _artifact_bundle(payload)
    document = json.loads(artifacts["snapshots/final.json"])
    row = document["queries"]["funds"]["callbacks"][0]["row"]
    row["AccountID"] = "different-account"
    sdk_result = _rebind_snapshot_query(document, "funds")
    _rebind_worker_query(payload, "final", "funds", sdk_result)
    frame = encode_private_snapshot_artifact(document)
    artifacts["snapshots/final.json"] = frame
    payload["snapshots"][1]["artifact_sha256"] = sha256_bytes(frame)

    result = _validate(payload, artifacts=artifacts)

    assert result.eligible_for_protected_admission is False
    assert "final_private_snapshot_projection_not_recomputable" in result.reasons


def test_closed_order_rows_still_require_exact_query_account_identity():
    payload = _payload()
    artifacts, _ = _artifact_bundle(payload)
    document = json.loads(artifacts["snapshots/baseline.json"])
    callback = document["queries"]["orders"]["callbacks"][0]
    callback["row_present"] = True
    callback["row"] = {
        "BrokerID": _BROKER_ID,
        "InvestorID": _USER_ID,
        "OrderStatus": "0",
        "VolumeTotalOriginal": 0,
        "VolumeTraded": 0,
    }
    _rebind_snapshot_query(document, "orders")
    snapshot = parse_private_snapshot_artifact(encode_private_snapshot_artifact(document))

    assert _projection_order_refs(snapshot, _BROKER_ID, _USER_ID) == []

    document["queries"]["orders"]["callbacks"][0]["row"]["InvestorID"] = "other-user"
    _rebind_snapshot_query(document, "orders")
    mismatched = parse_private_snapshot_artifact(encode_private_snapshot_artifact(document))
    with pytest.raises(ValueError, match="order_query_row_account_identity_mismatch"):
        _projection_order_refs(mismatched, _BROKER_ID, _USER_ID)


def test_same_active_order_identity_with_changed_economics_blocks_c01():
    payload = _payload()
    artifacts, _ = _artifact_bundle(payload)
    baseline_order = _active_order_row()
    final_order = _active_order_row(limit_price="100.5", volume_traded=1)
    artifacts = _bind_active_order_rows(
        payload,
        artifacts,
        {"baseline": baseline_order, "final": final_order},
    )

    baseline = parse_private_snapshot_artifact(artifacts["snapshots/baseline.json"])
    final = parse_private_snapshot_artifact(artifacts["snapshots/final.json"])
    baseline_projection = _projection_order_economics(baseline, _BROKER_ID, _USER_ID)
    final_projection = _projection_order_economics(final, _BROKER_ID, _USER_ID)
    assert set(baseline_projection["rows"][0]["identity"]) == set(
        ORDER_IDENTITY_TEXT_FIELDS + ORDER_IDENTITY_INTEGER_FIELDS
    )
    assert set(baseline_projection["rows"][0]["measures"]) == set(
        ORDER_DECIMAL_MEASURES + ORDER_INTEGER_MEASURES + ORDER_TEXT_MEASURES
    )
    assert baseline_projection != final_projection

    result = _validate(payload, artifacts=artifacts)

    assert result.eligible_for_protected_admission is False
    assert "baseline_final_order_economics_sha256_changed" in result.reasons


def test_missing_private_artifacts_prevents_structural_eligibility():
    payload = _payload()
    worker = parse_worker_frame(encode_worker_frame(payload))
    result = validate_c01_candidate(
        worker,
        _process(),
        expected_pair_binding=_pair(),
        expected_worker_source_sha256=_WORKER_SHA256,
        expected_account_scope_sha256=_ACCOUNT_SCOPE_SHA256,
        expected_credential_binding_sha256=_CREDENTIAL_BINDING_SHA256,
        expected_broker_id=_BROKER_ID,
        expected_user_id=_USER_ID,
    )

    assert result.eligible_for_protected_admission is False
    assert result.checked_snapshot_count == 0
    assert "private_snapshot_artifacts_missing_or_unexpected" in result.reasons


def test_incomplete_no_join_release_receipt_is_rejected_at_protocol_boundary():
    payload = _payload()
    payload["native_close"]["join_completed"] = False

    with pytest.raises(C01ProtocolError, match="native_close_no_join_release_incomplete"):
        _validate(payload)


def test_job_nonempty_or_missing_eof_blocks_structural_eligibility():
    process = _process()
    process = C01ProcessLifecycleReceipt(
        **{
            **process.__dict__,
            "stdout_eof": False,
            "job_active_count": 1,
        }
    )

    result = _validate(process=process)

    assert result.eligible_for_protected_admission is False
    assert "child_pipes_not_drained_to_eof" in result.reasons
    assert "job_not_observed_empty" in result.reasons


def test_worker_cannot_rebind_to_another_pair_or_source_hash():
    td_front = "tcp://127.0.0.2:41205"
    pair = C01PairBinding(
        selected_index=2,
        selection_sha256="a" * 64,
        md_front_sha256="b" * 64,
        td_front_sha256=hashlib.sha256(td_front.encode("utf-8")).hexdigest(),
        td_front=td_front,
        selected_at_utc="2026-10-02T01:02:03Z",
    )

    result = _validate(pair=pair, worker_sha="8" * 64)

    assert result.eligible_for_protected_admission is False
    assert "worker_pair_binding_mismatch" in result.reasons
    assert "worker_source_pin_mismatch" in result.reasons
