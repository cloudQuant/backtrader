"""Pure contract checks for the unregistered SimNow C01 read-only candidate.

The validator checks a fixed TD authentication/login plus baseline/final query
receipt.  A structurally valid receipt is only eligible for a later protected
custody/native-evidence admission.  This module has no PASS state and performs
no filesystem, SDK, provider, process, or network operations.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from datetime import datetime
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Tuple

from backtrader_runtime.certification_simnow_c01_v2_protocol import (
    ACCOUNT_DIAGNOSTIC_FIELD_SOURCES,
    ACCOUNT_DIMENSION_FIELDS,
    ACCOUNT_ECONOMICS_SCHEMA,
    ACCOUNT_INTEGER_MEASURES,
    ACCOUNT_NONNEGATIVE_MEASURES,
    ACCOUNT_NUMERIC_MEASURES,
    C01CandidateValidation,
    C01PairBinding,
    C01ProcessLifecycleReceipt,
    C01PrivateSnapshot,
    C01ProtocolError,
    C01WorkerReceipt,
    KNOWN_CTP_EXCHANGES,
    ORDER_DECIMAL_MEASURES,
    ORDER_ECONOMICS_SCHEMA,
    ORDER_IDENTITY_INTEGER_FIELDS,
    ORDER_IDENTITY_TEXT_FIELDS,
    ORDER_INTEGER_MEASURES,
    ORDER_TEXT_MEASURES,
    POSITION_INTEGER_MEASURES,
    POSITION_NONNEGATIVE_MEASURES,
    POSITION_NUMERIC_MEASURES,
    POSITION_TEXT_MEASURES,
    RSP_INFO_ABSENT,
    RSP_INFO_ERROR_ID_PRESENT,
    SDK_QUERY_NULL_ERROR_CODE_NO_FAILURE,
    SDK_QUERY_RESULT_TYPE,
    canonical_decimal_text,
    canonical_json_bytes,
    canonical_value_sha256,
    compute_account_scope_sha256,
    encode_worker_frame,
    parse_worker_frame,
    parse_private_snapshot_artifact,
    sha256_bytes,
)


_REQUEST_PLAN = (
    ("authenticate", None, None, "ReqAuthenticate"),
    ("login", None, None, "ReqUserLogin"),
    ("query", "baseline", "orders", "ReqQryOrder"),
    ("query", "baseline", "positions", "ReqQryInvestorPosition"),
    ("query", "baseline", "funds", "ReqQryTradingAccount"),
    ("query", "final", "orders", "ReqQryOrder"),
    ("query", "final", "positions", "ReqQryInvestorPosition"),
    ("query", "final", "funds", "ReqQryTradingAccount"),
)
_CALLBACK_BY_FAMILY = {
    "orders": "OnRspQryOrder",
    "positions": "OnRspQryInvestorPosition",
    "funds": "OnRspQryTradingAccount",
}
_PROTECTED_ADMISSION_REQUIRED = "protected_actor_must_admit_source_native_and_artifact_custody"
_ARTIFACT_REFS = {
    "baseline": "snapshots/baseline.json",
    "final": "snapshots/final.json",
}
_ORDER_STATUS_ACTIVE = frozenset({"1", "3", "a", "b", "c"})
_ORDER_STATUS_KNOWN = _ORDER_STATUS_ACTIVE | frozenset({"0", "2", "4", "5"})
_POSITION_DIMENSION_FIELDS = (
    ("ExchangeID", "exchange_id"),
    ("InstrumentID", "instrument_id"),
    ("PosiDirection", "position_direction"),
    ("HedgeFlag", "hedge_flag"),
    ("PositionDate", "position_date"),
)
_KNOWN_EXCHANGES = KNOWN_CTP_EXCHANGES
_POSITION_NUMERIC_MEASURES = POSITION_NUMERIC_MEASURES
_POSITION_TEXT_MEASURES = POSITION_TEXT_MEASURES
_POSITION_INTEGER_MEASURES = POSITION_INTEGER_MEASURES
_POSITION_NONNEGATIVE_MEASURES = POSITION_NONNEGATIVE_MEASURES


def _is_int(value: Any, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _parse_utc(value: Any) -> Optional[int]:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        body = value[:-1]
        base, fraction_marker, fraction = body.partition(".")
        if fraction_marker and (not fraction.isdigit() or not 1 <= len(fraction) <= 9):
            return None
        parsed = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
        delta = parsed - datetime(1970, 1, 1)
        seconds = delta.days * 86400 + delta.seconds
        nanos = int(fraction.ljust(9, "0")) if fraction_marker else 0
        return seconds * 1_000_000_000 + nanos
    except ValueError:
        return None


def _json_scalar_text(value: Any) -> Optional[str]:
    if type(value) is str:
        return value
    if type(value) is int:
        return str(value)
    if type(value) is float:
        return str(value)
    return None


def _native_integer(value: Any) -> Optional[int]:
    if type(value) is int:
        number = value
    elif type(value) is str and value and len(value) <= 128:
        try:
            number = int(value)
        except (ValueError, OverflowError):
            return None
        if str(number) != value:
            return None
    else:
        return None
    return number if abs(number) < 10**30 else None


def _native_text(value: Any) -> Optional[str]:
    text = _json_scalar_text(value)
    if (
        text is None
        or len(text) > 128
        or text != text.strip()
        or any(unicodedata.category(char) == "Cc" for char in text)
    ):
        return None
    return text


def _order_text(value: Any, *, allow_empty: bool = False) -> Optional[str]:
    if (
        type(value) is not str
        or (not allow_empty and not value)
        or len(value) > 128
        or value != value.strip()
        or any(unicodedata.category(char) == "Cc" for char in value)
    ):
        return None
    return value


def _artifact_rows(snapshot: C01PrivateSnapshot, family: str) -> List[Mapping[str, Any]]:
    callbacks = snapshot.payload["queries"][family]["callbacks"]
    return [callback["row"] for callback in callbacks if callback["row_present"] is True]


def _projection_order_refs(
    snapshot: C01PrivateSnapshot, expected_broker_id: str, expected_user_id: str
) -> List[Dict[str, Any]]:
    refs: Dict[bytes, Dict[str, Any]] = {}
    for row in _artifact_rows(snapshot, "orders"):
        if (
            not _valid_private_text(row.get("BrokerID"))
            or not _valid_private_text(row.get("InvestorID"))
            or row.get("BrokerID") != expected_broker_id
            or row.get("InvestorID") != expected_user_id
        ):
            raise ValueError("order_query_row_account_identity_mismatch")
        status = _order_text(row.get("OrderStatus"))
        if status not in _ORDER_STATUS_KNOWN:
            raise ValueError("order_status_unrecognized")
        total = _native_integer(row.get("VolumeTotalOriginal"))
        traded = _native_integer(row.get("VolumeTraded"))
        if total is None or traded is None or min(total, traded) < 0 or traded > total:
            raise ValueError("order_quantity_unprojectable")
        remaining = total - traded
        if status not in _ORDER_STATUS_ACTIVE or remaining <= 0:
            continue
        exchange_id = _order_text(row.get("ExchangeID"), allow_empty=True)
        order_sys_id = _order_text(row.get("OrderSysID"), allow_empty=True)
        if exchange_id and order_sys_id:
            ref = {
                "kind": "ctp_order_sys_id",
                "exchange_id": exchange_id,
                "order_sys_id": order_sys_id,
            }
        else:
            order_ref = _order_text(row.get("OrderRef"), allow_empty=True)
            front_id = _native_integer(row.get("FrontID"))
            session_id = _native_integer(row.get("SessionID"))
            if not order_ref or front_id is None or session_id is None:
                raise ValueError("open_order_identity_unavailable")
            ref = {
                "kind": "ctp_front_session_order_ref",
                "front_id": front_id,
                "session_id": session_id,
                "order_ref": order_ref,
            }
        token = canonical_json_bytes(ref)
        if token in refs:
            raise ValueError("active_order_identity_duplicated")
        refs[token] = ref
    return [refs[key] for key in sorted(refs)]


def _projection_order_economics(
    snapshot: C01PrivateSnapshot,
    expected_broker_id: str,
    expected_user_id: str,
) -> Dict[str, Any]:
    """Recompute full active-order economics from the private native rows.

    The identity projection is retained separately as a diagnostic. This
    second projection binds order side, price, fill and remaining quantities,
    conditions, and native status so unchanged IDs cannot hide an economic
    change between the baseline and final queries.
    """

    projected_rows: List[Dict[str, Any]] = []
    identity_tokens = set()
    identity_text_allow_empty = {"ExchangeID", "OrderSysID", "OrderRef"}
    for row in _artifact_rows(snapshot, "orders"):
        if (
            not _valid_private_text(row.get("BrokerID"))
            or not _valid_private_text(row.get("InvestorID"))
            or row.get("BrokerID") != expected_broker_id
            or row.get("InvestorID") != expected_user_id
        ):
            raise ValueError("order_query_row_account_identity_mismatch")

        status = _order_text(row.get("OrderStatus"))
        if status not in _ORDER_STATUS_KNOWN:
            raise ValueError("order_status_unrecognized")
        total_original = _native_integer(row.get("VolumeTotalOriginal"))
        volume_traded = _native_integer(row.get("VolumeTraded"))
        if (
            total_original is None
            or volume_traded is None
            or min(total_original, volume_traded) < 0
            or volume_traded > total_original
        ):
            raise ValueError("order_quantity_unprojectable")
        if status not in _ORDER_STATUS_ACTIVE or total_original == volume_traded:
            continue

        identity: Dict[str, Any] = {}
        for field in ORDER_IDENTITY_TEXT_FIELDS:
            value = _order_text(row.get(field), allow_empty=field in identity_text_allow_empty)
            if value is None:
                raise ValueError("active_order_identity_unavailable")
            identity[field] = value
        if (
            identity["BrokerID"] != expected_broker_id
            or identity["InvestorID"] != expected_user_id
            or identity["TradingDay"] != snapshot.payload["scope"]["trading_day"]
        ):
            raise ValueError("active_order_identity_scope_mismatch")
        for field in ORDER_IDENTITY_INTEGER_FIELDS:
            value = _native_integer(row.get(field))
            if value is None or value < 0:
                raise ValueError("active_order_identity_integer_unavailable")
            identity[field] = value
        if not (
            (identity["ExchangeID"] and identity["OrderSysID"])
            or (identity["OrderRef"] and identity["FrontID"] > 0 and identity["SessionID"] > 0)
        ):
            raise ValueError("active_order_identity_unavailable")

        measures: Dict[str, Any] = {}
        for field in ORDER_DECIMAL_MEASURES:
            try:
                measures[field] = canonical_decimal_text(row[field])
            except (KeyError, C01ProtocolError):
                raise ValueError("active_order_decimal_measure_invalid") from None
        for field in ORDER_INTEGER_MEASURES:
            value = _native_integer(row.get(field))
            if value is None or value < 0:
                raise ValueError("active_order_integer_measure_invalid")
            measures[field] = value
        for field in ORDER_TEXT_MEASURES:
            value = _order_text(row.get(field))
            if value is None:
                raise ValueError("active_order_text_measure_invalid")
            measures[field] = value
        if measures["OrderStatus"] != status:
            raise ValueError("active_order_status_mismatch")

        identity_token = canonical_json_bytes(identity)
        if identity_token in identity_tokens:
            raise ValueError("active_order_identity_duplicated")
        identity_tokens.add(identity_token)
        projected_rows.append({"identity": identity, "measures": measures})

    projected_rows.sort(key=canonical_json_bytes)
    return {"schema": ORDER_ECONOMICS_SCHEMA, "rows": projected_rows}


def _projection_gross_positions(
    snapshot: C01PrivateSnapshot, expected_broker_id: str, expected_user_id: str
) -> Dict[Tuple[str, ...], Tuple[Decimal, List[Dict[str, str]]]]:
    buckets: Dict[Tuple[str, ...], Tuple[Decimal, List[Dict[str, str]]]] = {}
    with localcontext() as context:
        context.prec = 512
        for row in _artifact_rows(snapshot, "positions"):
            dimensions = []
            for source, _ in _POSITION_DIMENSION_FIELDS:
                value = row.get(source)
                if type(value) is not str or not value:
                    raise ValueError("position_dimension_unavailable")
                dimensions.append(value)
            if dimensions[2] not in {"1", "2", "3"}:
                raise ValueError("position_direction_unrecognized")
            if dimensions[3] not in {"1", "2", "3"}:
                raise ValueError("position_hedge_flag_unrecognized")
            if dimensions[4] not in {"1", "2"}:
                raise ValueError("position_date_unrecognized")
            if dimensions[0] not in _KNOWN_EXCHANGES:
                raise ValueError("position_exchange_unrecognized")
            trading_day = row.get("TradingDay")
            if trading_day != snapshot.payload["scope"]["trading_day"]:
                raise ValueError("position_trading_day_mismatch")
            broker_id = row.get("BrokerID")
            investor_id = row.get("InvestorID")
            if (
                not _valid_private_text(broker_id)
                or not _valid_private_text(investor_id)
                or broker_id != expected_broker_id
                or investor_id != expected_user_id
            ):
                raise ValueError("position_account_identity_mismatch")
            measures: Dict[str, str] = {}
            for field in _POSITION_NUMERIC_MEASURES:
                if field not in row:
                    raise ValueError("position_measure_missing")
                try:
                    value_text = canonical_decimal_text(row[field])
                    value = Decimal(value_text)
                except (C01ProtocolError, InvalidOperation):
                    raise ValueError("position_measure_invalid") from None
                if field in _POSITION_NONNEGATIVE_MEASURES and value < 0:
                    raise ValueError("position_measure_negative")
                if field in _POSITION_INTEGER_MEASURES and value != value.to_integral_value():
                    raise ValueError("position_measure_fractional")
                measures[field] = value_text
            for field in _POSITION_TEXT_MEASURES:
                if field not in row or not _valid_position_text(
                    row[field], allow_empty=field in {"InvestUnitID", "reserve1"}
                ):
                    raise ValueError("position_text_measure_invalid")
                measures[field] = row[field]
            if measures["TradingDay"] != snapshot.payload["scope"]["trading_day"]:
                raise ValueError("position_measure_trading_day_mismatch")
            raw_quantity = row.get("Position")
            try:
                quantity_text = canonical_decimal_text(raw_quantity)
                quantity = Decimal(quantity_text)
            except (C01ProtocolError, InvalidOperation):
                raise ValueError("position_quantity_invalid") from None
            if quantity < 0 or quantity != quantity.to_integral_value():
                raise ValueError("position_quantity_invalid")
            key = tuple(dimensions)
            current_quantity, current_rows = buckets.get(key, (Decimal(0), []))
            current_rows.append(measures)
            buckets[key] = (current_quantity + quantity, current_rows)
    for key, (quantity, rows) in buckets.items():
        rows.sort(key=canonical_json_bytes)
    return buckets


def _valid_private_text(value: Any) -> bool:
    return (
        type(value) is str
        and bool(value)
        and len(value) <= 128
        and value == value.strip()
        and not any(unicodedata.category(char) == "Cc" for char in value)
    )


def _valid_position_text(value: Any, *, allow_empty: bool) -> bool:
    return (
        type(value) is str
        and (allow_empty or bool(value))
        and len(value) <= 128
        and value == value.strip()
        and not any(unicodedata.category(char) == "Cc" for char in value)
    )


def _projection_funds(
    snapshot: C01PrivateSnapshot, expected_broker_id: str, expected_user_id: str
) -> Dict[str, Any]:
    rows = _artifact_rows(snapshot, "funds")
    if len(rows) != 1:
        raise ValueError("account_snapshot_row_count_invalid")
    row = rows[0]
    dimensions: Dict[str, str] = {}
    for field in ACCOUNT_DIMENSION_FIELDS:
        if not _valid_private_text(row.get(field)):
            raise ValueError("account_snapshot_dimension_unavailable")
        dimensions[field] = row[field]
    if (
        dimensions["BrokerID"] != expected_broker_id
        or dimensions["AccountID"] != expected_user_id
        or dimensions["TradingDay"] != snapshot.payload["scope"]["trading_day"]
    ):
        raise ValueError("account_snapshot_identity_mismatch")
    measures: Dict[str, str] = {}
    for field in ACCOUNT_NUMERIC_MEASURES:
        if field not in row:
            raise ValueError("account_snapshot_measure_missing")
        try:
            rendered = canonical_decimal_text(row[field])
            number = Decimal(rendered)
        except (C01ProtocolError, InvalidOperation):
            raise ValueError("account_snapshot_measure_invalid") from None
        if field in ACCOUNT_NONNEGATIVE_MEASURES and number < 0:
            raise ValueError("account_snapshot_measure_negative")
        if field in ACCOUNT_INTEGER_MEASURES and number != number.to_integral_value():
            raise ValueError("account_snapshot_measure_fractional")
        measures[field] = rendered
    diagnostics = {
        name: measures[source] for name, source in ACCOUNT_DIAGNOSTIC_FIELD_SOURCES.items()
    }
    return {
        "schema": ACCOUNT_ECONOMICS_SCHEMA,
        "dimensions": dimensions,
        "measures": measures,
        "diagnostic_field_sources": dict(ACCOUNT_DIAGNOSTIC_FIELD_SOURCES),
        "diagnostics": diagnostics,
    }


def _check_process_receipt(
    receipt: C01ProcessLifecycleReceipt,
    worker: Mapping[str, Any],
    reasons: List[str],
) -> None:
    if not isinstance(receipt, C01ProcessLifecycleReceipt):
        reasons.append("parent_process_receipt_missing_or_wrong_type")
        return
    bool_fields = (
        "assigned_before_resume",
        "stdin_fully_sent",
        "stdout_eof",
        "stderr_eof",
        "process_exit_observed",
        "handles_closed",
        "timed_out",
        "forced_kill",
    )
    if any(type(getattr(receipt, field)) is not bool for field in bool_fields):
        reasons.append("parent_process_receipt_boolean_invalid")
        return
    if receipt.status != "BLOCKED":
        reasons.append("parent_process_receipt_must_remain_blocked")
    if receipt.run_nonce != worker.get("run_nonce"):
        reasons.append("parent_worker_nonce_mismatch")
    if receipt.parent_pid != worker.get("parent_pid"):
        reasons.append("parent_worker_parent_pid_mismatch")
    if receipt.worker_pid != worker.get("worker_pid"):
        reasons.append("parent_worker_pid_mismatch")
    if receipt.worker_source_sha256 != worker.get("worker_source_sha256"):
        reasons.append("parent_worker_source_hash_mismatch")
    if receipt.containment != "windows_job":
        reasons.append("windows_job_containment_not_observed")
    if not receipt.assigned_before_resume:
        reasons.append("job_assignment_before_resume_not_observed")
    if not receipt.stdin_fully_sent:
        reasons.append("launch_packet_not_fully_sent")
    if not receipt.stdout_eof or not receipt.stderr_eof:
        reasons.append("child_pipes_not_drained_to_eof")
    if not receipt.process_exit_observed or receipt.process_exit_code != 0:
        reasons.append("normal_child_exit_not_observed")
    if not _is_int(receipt.job_active_count, 0) or receipt.job_active_count != 0:
        reasons.append("job_not_observed_empty")
    if not receipt.handles_closed:
        reasons.append("parent_handles_not_closed")
    if receipt.timed_out:
        reasons.append("worker_timed_out")
    if receipt.forced_kill:
        reasons.append("worker_required_forced_kill")
    if (
        not isinstance(receipt.reason, str)
        or len(receipt.reason) > 96
        or (
            receipt.reason
            and not all(
                char.islower() or char.isdigit() or char in "_:-" for char in receipt.reason
            )
        )
    ):
        reasons.append("parent_process_reason_invalid")


def _validate_worker_semantics(
    worker: Mapping[str, Any],
    reasons: List[str],
) -> Tuple[int, int, int]:
    requests = worker.get("requests")
    callbacks = worker.get("callbacks")
    snapshots = worker.get("snapshots")
    if not isinstance(requests, (list, tuple)) or len(requests) != len(_REQUEST_PLAN):
        reasons.append("fixed_c01_request_plan_missing")
        return 0, 0, 0
    if not isinstance(callbacks, (list, tuple)):
        reasons.append("native_callbacks_missing")
        return len(requests), 0, 0
    if not isinstance(snapshots, (list, tuple)) or len(snapshots) != 2:
        reasons.append("baseline_and_final_snapshots_required")
        return len(requests), 0, 0

    request_by_key: Dict[Tuple[str, Optional[str], Optional[str]], Mapping[str, Any]] = {}
    request_ids = []
    request_generations = []
    request_sequences = []
    for index, (request, expected) in enumerate(zip(requests, _REQUEST_PLAN)):
        if not isinstance(request, Mapping):
            reasons.append("request_receipt_invalid")
            continue
        actual = (
            request.get("kind"),
            request.get("phase"),
            request.get("family"),
            request.get("method"),
        )
        if actual != expected:
            reasons.append("fixed_c01_request_order_or_scope_invalid")
        if request.get("receipt_origin") != "local_native_invocation":
            reasons.append("native_invocation_receipt_missing")
        if request.get("return_code") != 0 or isinstance(request.get("return_code"), bool):
            reasons.append("native_invocation_return_code_not_zero")
        request_id = request.get("request_id")
        if not _is_int(request_id, 1):
            reasons.append("native_request_id_invalid")
        else:
            request_ids.append(request_id)
        generation = request.get("request_generation")
        if not _is_int(generation, 1):
            reasons.append("request_generation_invalid")
        else:
            request_generations.append(generation)
        sequence = request.get("local_sequence")
        if not _is_int(sequence, 1):
            reasons.append("request_sequence_invalid")
        else:
            request_sequences.append(sequence)
        if _parse_utc(request.get("issued_at_utc")) is None:
            reasons.append("request_local_time_invalid")
        if not _is_int(request.get("issued_monotonic_ns"), 1):
            reasons.append("request_monotonic_time_invalid")
        key = (request.get("kind"), request.get("phase"), request.get("family"))
        if key in request_by_key:
            reasons.append("duplicate_native_invocation_receipt")
        request_by_key[key] = request
    if len(request_ids) != 8 or len(set(request_ids)) != 8:
        reasons.append("all_eight_native_request_ids_must_be_distinct")
    if len(request_generations) != 8 or len(set(request_generations)) != 8:
        reasons.append("all_eight_request_generations_must_be_distinct")
    if len(request_sequences) != 8 or len(set(request_sequences)) != 8:
        reasons.append("request_sequences_must_be_unique")
    elif request_sequences != sorted(request_sequences):
        reasons.append("native_invocation_order_invalid")

    client = worker.get("client")
    if not isinstance(client, Mapping):
        reasons.append("client_generation_missing")
        client_id = None
        client_generation = None
        arrival_generation = None
    else:
        client_id = client.get("instance_id")
        client_generation = client.get("client_generation")
        arrival_generation = client.get("arrival_generation")
        if not isinstance(client_id, str) or not client_id:
            reasons.append("client_instance_id_invalid")
        if not _is_int(client_generation, 1) or not _is_int(arrival_generation, 1):
            reasons.append("client_or_arrival_generation_invalid")

    by_request: Dict[Tuple[str, Optional[str], Optional[str]], List[Mapping[str, Any]]] = {}
    callback_sequences = []
    callback_monotonic = []
    for callback in callbacks:
        if not isinstance(callback, Mapping):
            reasons.append("callback_observation_invalid")
            continue
        kind = callback.get("kind")
        if kind in ("order_activity", "trade_activity"):
            reasons.append("native_order_or_trade_activity_observed")
            continue
        key = (kind, callback.get("phase"), callback.get("family"))
        by_request.setdefault(key, []).append(callback)
        if callback.get("client_instance_id") != client_id:
            reasons.append("callback_client_instance_mismatch")
        if callback.get("client_generation") != client_generation:
            reasons.append("callback_client_generation_mismatch")
        if callback.get("arrival_generation") != arrival_generation:
            reasons.append("callback_arrival_generation_mismatch")
        sequence = callback.get("local_sequence")
        if not _is_int(sequence, 1):
            reasons.append("callback_local_sequence_invalid")
        else:
            callback_sequences.append(sequence)
        monotonic = callback.get("arrived_monotonic_ns")
        if not _is_int(monotonic, 1):
            reasons.append("callback_monotonic_time_invalid")
        else:
            callback_monotonic.append(monotonic)
        if _parse_utc(callback.get("arrived_at_utc")) is None:
            reasons.append("callback_local_time_invalid")

    if len(callback_sequences) != len(callbacks) - sum(
        1
        for callback in callbacks
        if isinstance(callback, Mapping)
        and callback.get("kind") in ("order_activity", "trade_activity")
    ):
        reasons.append("callback_sequence_missing")
    all_sequences = []
    all_utc = []
    all_events = []
    for request in requests:
        if isinstance(request, Mapping):
            all_events.append((request.get("local_sequence"), request.get("issued_monotonic_ns")))
            all_utc.append(
                (request.get("local_sequence"), _parse_utc(request.get("issued_at_utc")))
            )
    for callback in callbacks:
        if isinstance(callback, Mapping):
            all_events.append(
                (callback.get("local_sequence"), callback.get("arrived_monotonic_ns"))
            )
            all_utc.append(
                (callback.get("local_sequence"), _parse_utc(callback.get("arrived_at_utc")))
            )
    if any(not _is_int(seq, 1) for seq, _ in all_events):
        reasons.append("local_event_sequence_invalid")
    else:
        all_sequences = [seq for seq, _ in all_events]
        if len(set(all_sequences)) != len(all_sequences):
            reasons.append("local_event_sequence_reused")
    if any(not _is_int(value, 1) for _, value in all_events):
        reasons.append("local_event_monotonic_invalid")
    else:
        ordered = sorted(all_events, key=lambda item: item[0])
        if any(left[1] > right[1] for left, right in zip(ordered, ordered[1:])):
            reasons.append("local_monotonic_order_contradiction")
        callback_order = [
            item.get("local_sequence") for item in callbacks if isinstance(item, Mapping)
        ]
        if all(_is_int(value, 1) for value in callback_order) and callback_order != sorted(
            callback_order
        ):
            reasons.append("native_callback_arrival_order_invalid")
        sorted_utc = sorted(all_utc, key=lambda item: item[0])
        if all(value is not None for _, value in sorted_utc) and any(
            left[1] > right[1] for left, right in zip(sorted_utc, sorted_utc[1:])
        ):
            reasons.append("local_utc_order_contradiction")

    def one_callback(kind: str, expected_name: str) -> Optional[Mapping[str, Any]]:
        items = by_request.get((kind, None, None), [])
        if len(items) != 1:
            reasons.append("exactly_one_" + kind + "_callback_required")
            return None
        callback = items[0]
        if callback.get("callback_name") != expected_name:
            reasons.append(kind + "_callback_name_invalid")
        if (
            callback.get("rsp_info_present") is not True
            or type(callback.get("error_id")) is not int
            or callback.get("error_id") != 0
            or callback.get("error_semantics") != RSP_INFO_ERROR_ID_PRESENT
        ):
            reasons.append(kind + "_callback_error_id_not_zero")
        if callback.get("is_last") is not True:
            reasons.append(kind + "_callback_not_terminal")
        return callback

    auth_callback = one_callback("authenticate", "OnRspAuthenticate")
    login_callback = one_callback("login", "OnRspUserLogin")
    query_observations: Dict[Tuple[str, str], Tuple[int, int, int, int]] = {}
    query_callback_count = 0
    last_baseline_sequence = 0
    first_final_sequence = None
    last_query_terminal_by_plan = 0
    for phase in ("baseline", "final"):
        for family in ("orders", "positions", "funds"):
            key = ("query", phase, family)
            request = request_by_key.get(key)
            callbacks_for_query = by_request.get(key, [])
            if request is None or not callbacks_for_query:
                reasons.append(phase + "_" + family + "_query_response_missing")
                continue
            query_callback_count += len(callbacks_for_query)
            request_id = request.get("request_id")
            request_generation = request.get("request_generation")
            if (
                last_query_terminal_by_plan
                and _is_int(request.get("local_sequence"), 1)
                and request["local_sequence"] <= last_query_terminal_by_plan
            ):
                reasons.append(phase + "_" + family + "_request_overlapped_prior_query")
            for index, callback in enumerate(callbacks_for_query):
                if callback.get("callback_name") != _CALLBACK_BY_FAMILY[family]:
                    reasons.append(phase + "_" + family + "_query_callback_name_invalid")
                if callback.get("request_id") != request_id:
                    reasons.append(phase + "_" + family + "_query_request_id_mismatch")
                if callback.get("request_generation") != request_generation:
                    reasons.append(phase + "_" + family + "_query_generation_mismatch")
                present = callback.get("rsp_info_present")
                error_id = callback.get("error_id")
                semantics = callback.get("error_semantics")
                if present is True:
                    if type(error_id) is not int or error_id != 0:
                        reasons.append(phase + "_" + family + "_query_error_id_not_zero")
                    if semantics != RSP_INFO_ERROR_ID_PRESENT:
                        reasons.append(phase + "_" + family + "_query_error_semantics_invalid")
                elif present is False:
                    if error_id is not None or semantics != RSP_INFO_ABSENT:
                        reasons.append(phase + "_" + family + "_query_absent_rsp_info_invalid")
                else:
                    reasons.append(phase + "_" + family + "_query_rsp_info_presence_invalid")
                if callback.get("is_last") is not (index == len(callbacks_for_query) - 1):
                    reasons.append(phase + "_" + family + "_query_terminal_order_invalid")
            if callbacks_for_query:
                first_sequence = callbacks_for_query[0].get("local_sequence")
                terminal_sequence = callbacks_for_query[-1].get("local_sequence")
                row_count = sum(
                    1 for item in callbacks_for_query if item.get("row_present") is True
                )
                query_observations[(phase, family)] = (
                    request_id,
                    len(callbacks_for_query),
                    row_count,
                    terminal_sequence,
                )
                if phase == "baseline" and _is_int(terminal_sequence, 1):
                    last_baseline_sequence = max(last_baseline_sequence, terminal_sequence)
                if phase == "final" and _is_int(first_sequence, 1):
                    first_final_sequence = (
                        first_sequence
                        if first_final_sequence is None
                        else min(first_final_sequence, first_sequence)
                    )
                if _is_int(terminal_sequence, 1):
                    last_query_terminal_by_plan = terminal_sequence
                if family == "funds" and row_count != 1:
                    reasons.append(phase + "_account_query_must_return_one_account_row")
                result = request.get("sdk_query_result")
                expected_request_type = "account" if family == "funds" else family
                if not isinstance(result, Mapping):
                    reasons.append(phase + "_" + family + "_sdk_query_result_missing")
                else:
                    if result.get("result_type") != SDK_QUERY_RESULT_TYPE:
                        reasons.append(phase + "_" + family + "_sdk_query_result_type_invalid")
                    if result.get("request_type") != expected_request_type:
                        reasons.append(phase + "_" + family + "_sdk_query_request_type_mismatch")
                    if result.get("request_id") != request_id:
                        reasons.append(phase + "_" + family + "_sdk_query_request_id_mismatch")
                    if result.get("connection_generation") != arrival_generation:
                        reasons.append(phase + "_" + family + "_sdk_query_generation_mismatch")
                    if result.get("complete") is not True or result.get("is_last_seen") is not True:
                        reasons.append(phase + "_" + family + "_sdk_query_incomplete")
                    if (
                        result.get("timed_out") is not False
                        or result.get("unsupported") is not False
                    ):
                        reasons.append(
                            phase + "_" + family + "_sdk_query_not_supported_or_timed_out"
                        )
                    if result.get("error_code") is not None:
                        reasons.append(phase + "_" + family + "_sdk_query_error_code_not_null")
                    if result.get("error_semantics") != SDK_QUERY_NULL_ERROR_CODE_NO_FAILURE:
                        reasons.append(phase + "_" + family + "_sdk_query_null_semantics_invalid")
                    if result.get("submit_code") != 0 or type(result.get("submit_code")) is not int:
                        reasons.append(phase + "_" + family + "_sdk_query_submit_code_invalid")
                    if result.get("record_count") != row_count:
                        reasons.append(phase + "_" + family + "_sdk_query_record_count_mismatch")
                    if (
                        result.get("late_callback_count") != 0
                        or type(result.get("late_callback_count")) is not int
                    ):
                        reasons.append(phase + "_" + family + "_sdk_query_late_callbacks")
                if request.get("return_code") != 0 or type(request.get("return_code")) is not int:
                    reasons.append(phase + "_" + family + "_native_submit_code_invalid")
            if not _is_int(request.get("local_sequence"), 1) or any(
                not _is_int(item.get("local_sequence"), 1) for item in callbacks_for_query
            ):
                continue
            if request["local_sequence"] >= callbacks_for_query[0]["local_sequence"]:
                reasons.append(phase + "_" + family + "_query_callback_precedes_invocation")
            if any(
                left["local_sequence"] >= right["local_sequence"]
                for left, right in zip(callbacks_for_query, callbacks_for_query[1:])
            ):
                reasons.append(phase + "_" + family + "_query_callback_order_invalid")
    if first_final_sequence is not None and last_baseline_sequence >= first_final_sequence:
        reasons.append("final_queries_must_follow_complete_baseline_queries")

    auth_request = request_by_key.get(("authenticate", None, None))
    login_request = request_by_key.get(("login", None, None))
    if auth_callback is not None and auth_request is not None:
        if auth_callback.get("request_id") != auth_request.get("request_id"):
            reasons.append("authentication_callback_not_bound_to_invocation")
        if auth_callback.get("request_generation") != auth_request.get("request_generation"):
            reasons.append("authentication_callback_generation_mismatch")
        if auth_request.get("local_sequence", 0) >= auth_callback.get("local_sequence", 0):
            reasons.append("authentication_callback_precedes_invocation")
    if login_callback is not None and login_request is not None:
        if login_callback.get("request_id") != login_request.get("request_id"):
            reasons.append("login_callback_not_bound_to_invocation")
        if login_callback.get("request_generation") != login_request.get("request_generation"):
            reasons.append("login_callback_generation_mismatch")
        if login_request.get("local_sequence", 0) >= login_callback.get("local_sequence", 0):
            reasons.append("login_callback_precedes_invocation")
    if auth_callback is not None and login_request is not None:
        if auth_callback.get("local_sequence", 0) >= login_request.get("local_sequence", 0):
            reasons.append("login_invocation_must_follow_authentication_callback")
    if login_callback is not None:
        login_seq = login_callback.get("local_sequence", 0)
        first_baseline_request = request_by_key.get(("query", "baseline", "orders"), {})
        if login_seq >= first_baseline_request.get("local_sequence", 0):
            reasons.append("baseline_queries_must_follow_login_callback")

    snapshots_by_phase = {
        snapshot.get("phase"): snapshot for snapshot in snapshots if isinstance(snapshot, Mapping)
    }
    if set(snapshots_by_phase) != {"baseline", "final"}:
        reasons.append("snapshot_phases_invalid")
    if login_callback is not None:
        login_session = login_callback.get("session_id")
        login_trading_day = login_callback.get("trading_day")
        for phase in ("baseline", "final"):
            snapshot = snapshots_by_phase.get(phase)
            if snapshot is None:
                continue
            if (
                snapshot.get("session_id") != login_session
                or snapshot.get("trading_day") != login_trading_day
            ):
                reasons.append(phase + "_snapshot_scope_must_match_login_callback")
    for phase in ("baseline", "final"):
        snapshot = snapshots_by_phase.get(phase)
        if snapshot is None:
            continue
        if snapshot.get("client_instance_id") != client_id:
            reasons.append(phase + "_snapshot_client_mismatch")
        if snapshot.get("client_generation") != client_generation:
            reasons.append(phase + "_snapshot_client_generation_mismatch")
        if snapshot.get("arrival_generation") != arrival_generation:
            reasons.append(phase + "_snapshot_arrival_generation_mismatch")
        queries = snapshot.get("queries")
        if not isinstance(queries, Mapping):
            reasons.append(phase + "_snapshot_query_receipts_missing")
            continue
        for family in ("orders", "positions", "funds"):
            query = queries.get(family)
            observed = query_observations.get((phase, family))
            if not isinstance(query, Mapping) or observed is None:
                reasons.append(phase + "_" + family + "_snapshot_query_receipt_missing")
                continue
            request_id, callback_count, row_count, terminal_sequence = observed
            callback_group = by_request.get(("query", phase, family), [])
            expected_first = callback_group[0].get("local_sequence") if callback_group else None
            expected_terminal = callback_group[-1].get("local_sequence") if callback_group else None
            if query.get("request_id") != request_id:
                reasons.append(phase + "_" + family + "_snapshot_request_id_mismatch")
            if query.get("callback_count") != callback_count:
                reasons.append(phase + "_" + family + "_snapshot_callback_count_mismatch")
            if query.get("row_count") != row_count:
                reasons.append(phase + "_" + family + "_snapshot_row_count_mismatch")
            if (
                query.get("first_sequence") != expected_first
                or query.get("terminal_sequence") != expected_terminal
            ):
                reasons.append(phase + "_" + family + "_snapshot_callback_range_mismatch")
    baseline = snapshots_by_phase.get("baseline")
    final = snapshots_by_phase.get("final")
    if baseline is not None and final is not None:
        for field in (
            "open_order_refs_sha256",
            "order_economics_sha256",
            "positions_sha256",
            "funds_sha256",
        ):
            if baseline.get(field) != final.get(field):
                reasons.append("baseline_final_" + field + "_changed")

    write_counters = worker.get("write_counters")
    if not isinstance(write_counters, Mapping) or any(
        write_counters.get(name) != 0 or isinstance(write_counters.get(name), bool)
        for name in ("ReqOrderInsert", "ReqOrderAction")
    ):
        reasons.append("order_or_cancel_method_was_attempted")
    native_close = worker.get("native_close")
    if not isinstance(native_close, Mapping):
        reasons.append("native_close_receipt_missing")
    else:
        if native_close.get("receipt_type") != "CtpNativeStopReceipt":
            reasons.append("source_native_close_receipt_type_mismatch")
        if native_close.get("lifecycle_mode") != "NO_JOIN_RELEASE_RETURNED":
            reasons.append("native_lifecycle_mode_invalid")
        if native_close.get("join_required") is not False:
            reasons.append("native_join_must_be_disabled_for_v2_profile")
        if native_close.get("join_completed") is not True:
            reasons.append("native_join_not_completed")
        if native_close.get("native_released") is not True:
            reasons.append("native_release_not_proven")
        if native_close.get("thread_alive") is not False:
            reasons.append("native_thread_still_alive_or_unknown")
        if native_close.get("timed_out") is not False:
            reasons.append("native_close_timed_out_or_unknown")

    return len(requests), query_callback_count, len(snapshots)


def _validate_private_snapshot_artifacts(
    artifacts: Optional[Mapping[str, bytes]],
    worker: Mapping[str, Any],
    reasons: List[str],
    *,
    expected_broker_id: Optional[str],
    expected_user_id: Optional[str],
    expected_account_scope_sha256: Optional[str],
) -> int:
    """Verify root-supplied bytes without opening files or asserting custody."""

    if not _valid_private_text(expected_broker_id) or not _valid_private_text(expected_user_id):
        reasons.append("expected_private_account_identity_missing")
        return 0
    try:
        computed_scope_sha256 = compute_account_scope_sha256(expected_broker_id, expected_user_id)
    except C01ProtocolError:
        reasons.append("expected_private_account_scope_invalid")
        return 0
    if computed_scope_sha256 != expected_account_scope_sha256:
        reasons.append("expected_private_account_scope_hash_mismatch")
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(_ARTIFACT_REFS.values()):
        reasons.append("private_snapshot_artifacts_missing_or_unexpected")
        return 0
    summaries = worker.get("snapshots")
    requests = worker.get("requests")
    callbacks = worker.get("callbacks")
    if not isinstance(summaries, (list, tuple)) or not isinstance(requests, (list, tuple)):
        reasons.append("private_snapshot_receipt_context_missing")
        return 0
    if not isinstance(callbacks, (list, tuple)):
        reasons.append("private_snapshot_callback_context_missing")
        return 0
    summary_by_phase = {
        summary.get("phase"): summary for summary in summaries if isinstance(summary, Mapping)
    }
    request_by_key = {
        (request.get("phase"), request.get("family")): request
        for request in requests
        if isinstance(request, Mapping) and request.get("kind") == "query"
    }
    login_callbacks = [
        callback
        for callback in callbacks
        if isinstance(callback, Mapping) and callback.get("kind") == "login"
    ]
    if len(login_callbacks) != 1:
        reasons.append("private_snapshot_login_context_missing")
        return 0
    login = login_callbacks[0]
    worker_client = worker.get("client")
    if not isinstance(worker_client, Mapping):
        reasons.append("private_snapshot_worker_client_missing")
        return 0

    checked = 0
    account_fingerprint_by_phase = {}
    for phase in ("baseline", "final"):
        ref = _ARTIFACT_REFS[phase]
        raw = artifacts.get(ref)
        summary = summary_by_phase.get(phase)
        try:
            if not isinstance(raw, bytes) or summary is None:
                raise ValueError("artifact_input_missing")
            snapshot = parse_private_snapshot_artifact(raw)
            document = snapshot.to_dict()
        except (C01ProtocolError, TypeError, ValueError):
            reasons.append(phase + "_private_snapshot_invalid")
            continue
        if summary.get("artifact_ref") != ref or sha256_bytes(raw) != summary.get(
            "artifact_sha256"
        ):
            reasons.append(phase + "_private_snapshot_artifact_hash_or_ref_mismatch")
        if snapshot.phase != phase or document["phase"] != summary.get("phase"):
            reasons.append(phase + "_private_snapshot_phase_mismatch")
        if document.get("account_scope_sha256") != worker.get("account_scope_sha256"):
            reasons.append(phase + "_private_snapshot_account_scope_mismatch")
        if document.get("account_scope_sha256") != expected_account_scope_sha256:
            reasons.append(phase + "_private_snapshot_private_account_scope_mismatch")
        if document.get("credential_binding_sha256") != worker.get("credential_binding_sha256"):
            reasons.append(phase + "_private_snapshot_credential_binding_mismatch")
        if document.get("client") != {
            "instance_id": worker_client.get("instance_id"),
            "client_generation": worker_client.get("client_generation"),
            "arrival_generation": worker_client.get("arrival_generation"),
        }:
            reasons.append(phase + "_private_snapshot_client_mismatch")
        scope = document.get("scope", {})
        if (
            scope.get("front_id") != login.get("front_id")
            or scope.get("session_id") != login.get("session_id")
            or scope.get("trading_day") != login.get("trading_day")
            or summary.get("session_id") != scope.get("session_id")
            or summary.get("trading_day") != scope.get("trading_day")
        ):
            reasons.append(phase + "_private_snapshot_scope_mismatch")

        query_fingerprints = set()
        for family in ("orders", "positions", "funds"):
            sdk_result = document["queries"][family]["request"].get("sdk_query_result")
            source = sdk_result.get("query_source") if isinstance(sdk_result, Mapping) else None
            if not isinstance(source, Mapping):
                reasons.append(phase + "_" + family + "_query_source_missing")
                continue
            if (
                source.get("broker_id") != expected_broker_id
                or source.get("investor_id") != expected_user_id
            ):
                reasons.append(phase + "_" + family + "_query_source_account_mismatch")
            if source.get("trading_day") != scope.get("trading_day"):
                reasons.append(phase + "_" + family + "_query_source_trading_day_mismatch")
            if sdk_result.get("account_fingerprint") != source.get("account_fingerprint"):
                reasons.append(phase + "_" + family + "_query_source_fingerprint_mismatch")
            if isinstance(source.get("account_fingerprint"), str):
                query_fingerprints.add(source["account_fingerprint"])
        if len(query_fingerprints) != 1:
            reasons.append(phase + "_query_source_fingerprint_inconsistent")
        else:
            account_fingerprint_by_phase[phase] = next(iter(query_fingerprints))

        projection = document.get("projections", {})
        for field, receipt_field in (
            ("open_order_refs", "open_order_refs_sha256"),
            ("order_economics", "order_economics_sha256"),
            ("positions", "positions_sha256"),
            ("funds", "funds_sha256"),
        ):
            try:
                digest = canonical_value_sha256(projection[field])
            except (KeyError, C01ProtocolError, TypeError, ValueError):
                reasons.append(phase + "_private_snapshot_" + field + "_projection_invalid")
            else:
                if digest != summary.get(receipt_field):
                    reasons.append(phase + "_private_snapshot_" + field + "_digest_mismatch")

        for family in ("orders", "positions", "funds"):
            query = document["queries"][family]
            request = query["request"]
            receipt_request = request_by_key.get((phase, family))
            if not isinstance(receipt_request, Mapping):
                reasons.append(phase + "_" + family + "_private_snapshot_request_missing")
                continue
            if any(
                request.get(field) != receipt_request.get(field)
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
            ):
                reasons.append(phase + "_" + family + "_private_snapshot_request_mismatch")
            matching_callbacks = [
                callback
                for callback in callbacks
                if isinstance(callback, Mapping)
                and callback.get("kind") == "query"
                and callback.get("phase") == phase
                and callback.get("family") == family
            ]
            artifact_callbacks = query["callbacks"]
            if len(matching_callbacks) != len(artifact_callbacks):
                reasons.append(phase + "_" + family + "_private_snapshot_callback_count_mismatch")
                continue
            for callback_index, (artifact_callback, receipt_callback) in enumerate(
                zip(artifact_callbacks, matching_callbacks)
            ):
                if any(
                    artifact_callback.get(artifact_field) != receipt_callback.get(receipt_field)
                    for artifact_field, receipt_field in (
                        ("callback_name", "callback_name"),
                        ("request_id", "request_id"),
                        ("error_id", "error_id"),
                        ("rsp_info_present", "rsp_info_present"),
                        ("error_semantics", "error_semantics"),
                        ("is_last", "is_last"),
                        ("request_generation", "request_generation"),
                        ("local_sequence", "local_sequence"),
                        ("arrived_at_utc", "arrived_at_utc"),
                        ("arrived_monotonic_ns", "arrived_monotonic_ns"),
                        ("row_present", "row_present"),
                    )
                ):
                    reasons.append(
                        phase
                        + "_"
                        + family
                        + "_private_snapshot_callback_{}_mismatch".format(callback_index)
                    )
                    break

            summary_query = summary.get("queries", {}).get(family, {})
            if (
                summary_query.get("request_id") != request.get("request_id")
                or summary_query.get("callback_count") != len(artifact_callbacks)
                or summary_query.get("row_count")
                != sum(1 for item in artifact_callbacks if item.get("row_present") is True)
                or summary_query.get("first_sequence")
                != artifact_callbacks[0].get("local_sequence")
                or summary_query.get("terminal_sequence")
                != artifact_callbacks[-1].get("local_sequence")
            ):
                reasons.append(phase + "_" + family + "_private_snapshot_summary_mismatch")

        try:
            expected_orders = _projection_order_refs(snapshot, expected_broker_id, expected_user_id)
            expected_order_economics = _projection_order_economics(
                snapshot, expected_broker_id, expected_user_id
            )
            expected_funds = _projection_funds(snapshot, expected_broker_id, expected_user_id)
            expected_positions = _projection_gross_positions(
                snapshot, expected_broker_id, expected_user_id
            )
            reported_positions = {
                (
                    bucket["exchange_id"],
                    bucket["instrument_id"],
                    bucket["position_direction"],
                    bucket["hedge_flag"],
                    bucket["position_date"],
                ): (Decimal(bucket["quantity"]), bucket["rows"])
                for bucket in projection["positions"]["buckets"]
            }
            if expected_orders != projection["open_order_refs"]:
                reasons.append(phase + "_private_snapshot_open_order_projection_mismatch")
            if expected_order_economics != projection["order_economics"]:
                reasons.append(phase + "_private_snapshot_order_economics_projection_mismatch")
            if expected_funds != projection["funds"]:
                reasons.append(phase + "_private_snapshot_funds_projection_mismatch")
            if expected_positions != reported_positions:
                reasons.append(phase + "_private_snapshot_gross_positions_mismatch")
        except (C01ProtocolError, KeyError, TypeError, ValueError, InvalidOperation):
            reasons.append(phase + "_private_snapshot_projection_not_recomputable")
        checked += 1
    if (
        len(account_fingerprint_by_phase) == 2
        and account_fingerprint_by_phase["baseline"] != account_fingerprint_by_phase["final"]
    ):
        reasons.append("baseline_final_query_source_fingerprint_mismatch")
    return checked


def validate_c01_candidate(
    worker_receipt: C01WorkerReceipt,
    process_receipt: C01ProcessLifecycleReceipt,
    *,
    expected_pair_binding: C01PairBinding,
    expected_worker_source_sha256: str,
    expected_account_scope_sha256: str,
    expected_credential_binding_sha256: str,
    private_snapshot_artifacts: Optional[Mapping[str, bytes]] = None,
    expected_broker_id: Optional[str] = None,
    expected_user_id: Optional[str] = None,
) -> C01CandidateValidation:
    """Return structural eligibility while keeping the result permanently BLOCKED.

    The protected actor must independently verify source custody, SDK/native
    identity, and the private snapshot artifacts before any real case decision.
    """

    reasons: List[str] = []
    if not isinstance(worker_receipt, C01WorkerReceipt):
        return C01CandidateValidation(
            eligible_for_protected_admission=False,
            status="BLOCKED",
            reasons=("worker_receipt_missing_or_wrong_type",),
            checked_request_count=0,
            checked_query_callback_count=0,
            checked_snapshot_count=0,
        )
    try:
        # Re-encode and parse so a hand-constructed wrapper cannot bypass the
        # strict, bounded wire schema checked by the supervisor.
        parsed = parse_worker_frame(encode_worker_frame(worker_receipt.to_dict()))
    except (C01ProtocolError, TypeError, ValueError):
        return C01CandidateValidation(
            eligible_for_protected_admission=False,
            status="BLOCKED",
            reasons=("worker_receipt_protocol_invalid",),
            checked_request_count=0,
            checked_query_callback_count=0,
            checked_snapshot_count=0,
        )
    worker = parsed.to_dict()
    if not isinstance(expected_pair_binding, C01PairBinding):
        reasons.append("expected_pair_binding_missing")
    elif worker.get("pair_binding") != expected_pair_binding.to_dict():
        reasons.append("worker_pair_binding_mismatch")
    if (
        not isinstance(expected_worker_source_sha256, str)
        or worker.get("worker_source_sha256") != expected_worker_source_sha256
    ):
        reasons.append("worker_source_pin_mismatch")
    if worker.get("account_scope_sha256") != expected_account_scope_sha256:
        reasons.append("worker_account_scope_binding_mismatch")
    if worker.get("credential_binding_sha256") != expected_credential_binding_sha256:
        reasons.append("worker_credential_binding_mismatch")
    request_count, query_callback_count, snapshot_count = _validate_worker_semantics(
        worker, reasons
    )
    checked_artifact_count = _validate_private_snapshot_artifacts(
        private_snapshot_artifacts,
        worker,
        reasons,
        expected_broker_id=expected_broker_id,
        expected_user_id=expected_user_id,
        expected_account_scope_sha256=expected_account_scope_sha256,
    )
    _check_process_receipt(process_receipt, worker, reasons)
    eligible = not reasons
    if eligible:
        reasons.append(_PROTECTED_ADMISSION_REQUIRED)
    return C01CandidateValidation(
        eligible_for_protected_admission=eligible,
        status="BLOCKED",
        reasons=tuple(reasons),
        checked_request_count=request_count,
        checked_query_callback_count=query_callback_count,
        checked_snapshot_count=min(snapshot_count, checked_artifact_count),
    )
