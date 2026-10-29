"""Collect one bounded, read-only CTP futures directory/quote snapshot.

The empty-filter queries describe the contracts and current depth rows visible
through the connected CTP front, account and trading day.  They do not prove
an exchange-wide universe.  This module is deliberately only a source adapter:
main-contract eligibility and ranking stay in :mod:`futures_main_contract`.

Importing this module does not import the optional CTP SDK.  The SDK is loaded
only when :func:`collect_ctp_futures_snapshot` is called with an injected live
feed.  ``UpdateTime`` and ``ActionDay`` are retained as source fields only;
query completion time is not represented as a market-data receive time.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional, Tuple


_DEFAULT_MAX_COLLECTION_SECONDS = 300.0
_DEFAULT_MAX_SNAPSHOT_AGE_SECONDS = 300.0
_MAX_CONFIGURED_SECONDS = 3600.0
_MAX_QUERY_DIAGNOSTIC_RECORD_COUNT = 20_000
# One product query plus one instrument and one depth receipt per visible
# class-1 product (2 * 256 + 1) when the staged per-product depth layout is used.
_MAX_QUERY_DIAGNOSTIC_OBSERVATIONS = 513
_MAX_PRODUCT_QUERY_HARD_SECONDS = 30.0
_MAX_QUERY_IDLE_SECONDS = 5.0
_QUERY_COMPLETION_ORIGINS = frozenset(
    {
        "unknown",
        "query_response",
        "response_error",
        "front_disconnected",
        "client_stop",
        "local_cancel",
        "submit_exception",
        "submit_rejected",
        "timeout",
        "deadline",
        "success",
        "local_preflight",
        "record_limit",
    }
)
_DAY_FORMAT = "%Y%m%d"
_SOURCE_PREFIX_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


@dataclass(frozen=True)
class CtpFuturesSnapshotQueryObservation:
    """Bounded facts about one public query call, without request or row data."""

    stage: str
    entered: bool
    returned: bool
    elapsed_seconds: Optional[float]
    prior_stage_complete: Optional[bool]
    result_type_matches: Optional[bool]
    request_type_matches: Optional[bool]
    generation_matches: Optional[bool]
    request_id_positive: Optional[bool]
    timed_out: Optional[bool]
    complete: Optional[bool]
    is_last_seen: Optional[bool]
    unsupported: Optional[bool]
    late_callbacks_reported: Optional[bool]
    late_callback_count_valid: Optional[bool]
    record_count: Optional[int]
    record_count_capped: Optional[bool]
    error_code_present: Optional[bool]
    error_code_valid: Optional[bool]
    error_code_nonzero: Optional[bool]
    error_message_present: Optional[bool]
    error_message_valid: Optional[bool]
    submit_category: str
    error_category: str
    first_completion_origin: Optional[str] = "unknown"
    completion_origin: Optional[str] = "unknown"
    requested_record_limit: Optional[int] = None
    record_limit_observed: Optional[int] = None
    record_limit_matches: Optional[bool] = None
    record_limit_exceeded: Optional[bool] = None
    request_filters_match: Optional[bool] = None
    classified_future_product_count: Optional[int] = None
    classified_excluded_product_count: Optional[int] = None


class CtpFuturesSnapshotError(RuntimeError):
    """A stable, value-free reason that a CTP source snapshot was refused."""

    def __init__(self, code: str, query_observations: tuple = ()) -> None:
        self.code = code
        observations = query_observations
        if (
            type(observations) is not tuple
            or len(observations) > _MAX_QUERY_DIAGNOSTIC_OBSERVATIONS
            or any(type(item) is not CtpFuturesSnapshotQueryObservation for item in observations)
        ):
            observations = ()
        self.query_observations = observations
        super().__init__(code)


def _fail(code: str, query_observations: tuple = ()) -> None:
    raise CtpFuturesSnapshotError(code, query_observations)


def _query_observation(
    *,
    stage: str,
    entered: bool,
    returned: bool,
    started_monotonic: float,
    returned_monotonic: float,
    prior_stage_complete: Optional[bool],
    result: Any,
    query_type: type,
    expected_request_type: str,
    expected_generation: int,
    expected_record_limit: Optional[int] = None,
    expected_request_filters: Optional[tuple] = None,
) -> CtpFuturesSnapshotQueryObservation:
    elapsed = returned_monotonic - started_monotonic
    elapsed_seconds = None
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
        elapsed_seconds = float(elapsed)
    result_type_matches = None
    request_type_matches = None
    generation_matches = None
    request_id_positive = None
    timed_out = complete = is_last_seen = unsupported = None
    late_callbacks_reported = late_callback_count_valid = None
    record_count = None
    record_count_capped = None
    actual_record_count = None
    record_limit = record_limit_matches = record_limit_exceeded = None
    request_filters_match = None
    error_code_present = error_code_valid = error_code_nonzero = None
    error_message_present = error_message_valid = None
    submit_category = "unavailable"
    error_category = "unavailable"
    first_completion_origin = completion_origin = "unknown"

    # Only inspect the SDK's exact public result type. Subclasses and malformed
    # objects remain subject to the existing validator but do not contribute
    # diagnostic fields that could invoke caller-defined attribute behavior.
    if returned:
        result_type_matches = type(result) is query_type
        if result_type_matches:
            first_origin = getattr(result, "first_completion_origin", "unknown")
            completion = getattr(result, "completion_origin", "unknown")
            first_completion_origin = (
                first_origin
                if type(first_origin) is str and first_origin in _QUERY_COMPLETION_ORIGINS
                else None
            )
            completion_origin = (
                completion
                if type(completion) is str and completion in _QUERY_COMPLETION_ORIGINS
                else None
            )
            request_type = result.request_type
            request_type_matches = (
                request_type == expected_request_type if type(request_type) is str else False
            )
            generation = result.connection_generation
            generation_matches = (
                generation == expected_generation
                if type(generation) is int and generation > 0
                else False
            )
            request_id = result.request_id
            request_id_positive = type(request_id) is int and request_id > 0

            for name in ("timed_out", "complete", "is_last_seen", "unsupported"):
                value = getattr(result, name)
                if type(value) is bool:
                    if name == "timed_out":
                        timed_out = value
                    elif name == "complete":
                        complete = value
                    elif name == "is_last_seen":
                        is_last_seen = value
                    else:
                        unsupported = value

            records = result.records
            if type(records) is tuple:
                actual_record_count = len(records)
                record_count = min(actual_record_count, _MAX_QUERY_DIAGNOSTIC_RECORD_COUNT)
                record_count_capped = actual_record_count > _MAX_QUERY_DIAGNOSTIC_RECORD_COUNT

            observed_limit = getattr(result, "record_limit", None)
            if type(observed_limit) is int:
                record_limit = observed_limit
                if expected_record_limit is not None:
                    record_limit_matches = observed_limit == expected_record_limit
            observed_exceeded = getattr(result, "record_limit_exceeded", None)
            if type(observed_exceeded) is bool:
                record_limit_exceeded = observed_exceeded or (
                    expected_record_limit is not None
                    and actual_record_count is not None
                    and actual_record_count > expected_record_limit
                )
            if expected_request_filters is not None:
                request_filters_match = (
                    _request_filter_pairs(result) == expected_request_filters
                )

            late_callback_count = result.late_callback_count
            late_callback_count_valid = (
                type(late_callback_count) is int and late_callback_count >= 0
            )
            late_callbacks_reported = (
                late_callback_count > 0 if late_callback_count_valid else None
            )

            submit_code = result.submit_code
            if submit_code is None:
                submit_category = "not_observed"
            elif type(submit_code) is int and submit_code == 0:
                submit_category = "accepted"
            elif type(submit_code) is int:
                submit_category = "rejected"
            else:
                submit_category = "invalid"

            error_code = result.error_code
            error_message = result.error_message
            error_code_present = error_code is not None
            error_code_valid = error_code is None or type(error_code) is int
            if error_code_valid:
                error_code_nonzero = error_code is not None and error_code != 0
            error_message_valid = type(error_message) is str
            error_message_present = error_message != "" if error_message_valid else None
            boolean_fields_valid = all(
                type(getattr(result, name)) is bool
                for name in ("timed_out", "complete", "is_last_seen", "unsupported")
            )
            invalid_facts = (
                type(request_type) is not str
                or type(generation) is not int
                or generation <= 0
                or type(request_id) is not int
                or request_id <= 0
                or not boolean_fields_valid
                or type(records) is not tuple
                or not late_callback_count_valid
                or not error_code_valid
                or not error_message_valid
                or (result.submit_code is not None and type(result.submit_code) is not int)
            )
            if invalid_facts:
                error_category = "invalid"
            elif timed_out is True:
                error_category = "timeout"
            elif record_limit_exceeded is True or completion == "record_limit":
                error_category = "record_limit"
            elif record_limit_matches is False or request_filters_match is False:
                error_category = "scope_mismatch"
            elif unsupported is True:
                error_category = "unsupported"
            elif error_code_nonzero is True:
                error_category = "query_error"
            elif submit_category == "rejected":
                error_category = "submission_error"
            elif error_message:
                error_category = "query_error"
            elif complete is False or is_last_seen is False:
                error_category = "incomplete"
            elif late_callbacks_reported is True:
                error_category = "late_callbacks"
            else:
                error_category = "none"

    return CtpFuturesSnapshotQueryObservation(
        stage=stage,
        entered=entered,
        returned=returned,
        elapsed_seconds=elapsed_seconds,
        prior_stage_complete=prior_stage_complete,
        result_type_matches=result_type_matches,
        request_type_matches=request_type_matches,
        generation_matches=generation_matches,
        request_id_positive=request_id_positive,
        timed_out=timed_out,
        complete=complete,
        is_last_seen=is_last_seen,
        unsupported=unsupported,
        late_callbacks_reported=late_callbacks_reported,
        late_callback_count_valid=late_callback_count_valid,
        record_count=record_count,
        record_count_capped=record_count_capped,
        requested_record_limit=expected_record_limit,
        record_limit_observed=record_limit,
        record_limit_matches=record_limit_matches,
        record_limit_exceeded=record_limit_exceeded,
        request_filters_match=request_filters_match,
        error_code_present=error_code_present,
        error_code_valid=error_code_valid,
        error_code_nonzero=error_code_nonzero,
        error_message_present=error_message_present,
        error_message_valid=error_message_valid,
        submit_category=submit_category,
        error_category=error_category,
        first_completion_origin=first_completion_origin,
        completion_origin=completion_origin,
    )


def _duration(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(name + "_INVALID")
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number > _MAX_CONFIGURED_SECONDS:
        _fail(name + "_INVALID")
    return number


def _now_utc() -> datetime:
    """Clock seam kept private so tests can control evidence-time fixtures."""

    return datetime.now(timezone.utc)


def _aware_utc(value: Any, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _fail(code)
    return value.astimezone(timezone.utc)


def _trading_day(value: Any, code: str) -> date:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        _fail(code)
    try:
        return datetime.strptime(value, _DAY_FORMAT).date()
    except ValueError:
        _fail(code)


def _mapping_row(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(code)
    if any(type(key) is not str for key in value):
        _fail(code)
    return value


def _same_field_value(left: Any, right: Any) -> bool:
    left_empty = (
        left is None or (type(left) is str and left == "") or (type(left) is bytes and left == b"")
    )
    right_empty = (
        right is None
        or (type(right) is str and right == "")
        or (type(right) is bytes and right == b"")
    )
    if left_empty and right_empty:
        return True
    if type(left) is type(right):
        return left == right
    if type(left) is int and type(right) is str and str(left) == right:
        return True
    if type(right) is int and type(left) is str and str(right) == left:
        return True
    if isinstance(left, bytes) and type(right) is str:
        try:
            return left.decode("utf-8") == right
        except UnicodeDecodeError:
            return False
    if type(left) is str and isinstance(right, bytes):
        try:
            return left == right.decode("utf-8")
        except UnicodeDecodeError:
            return False
    return False


def _field(
    row: Mapping[str, Any],
    native_name: str,
    normalized_name: str,
    *,
    missing_code: str,
    required: bool = True,
) -> Any:
    native_present = native_name in row
    normalized_present = normalized_name in row
    if native_present and normalized_present:
        if not _same_field_value(row[native_name], row[normalized_name]):
            _fail("ROW_FIELD_CONFLICT")
    if native_present:
        value = row[native_name]
    elif normalized_present:
        value = row[normalized_name]
    else:
        if required:
            _fail(missing_code)
        return None
    if (
        value is None
        or (type(value) is str and value == "")
        or (type(value) is bytes and value == b"")
    ):
        if required:
            _fail(missing_code)
        return None
    return value


def _ctp_text(value: Any, code: str, *, required: bool = True) -> Optional[str]:
    """Decode CTP's ASCII identifier/date/time fields without replacement."""

    if value is None:
        if required:
            _fail(code)
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            _fail(code)
    elif type(value) is not str:
        _fail(code)
    if not value:
        if required:
            _fail(code)
        return None
    if value != value.strip() or "\x00" in value:
        _fail(code)
    return value


def _trading_flag(value: Any) -> Optional[bool]:
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    if type(value) is str and value in ("0", "1"):
        return value == "1"
    if type(value) is bytes and value in (b"0", b"1"):
        return value == b"1"
    return None


def _assert_alias_equivalent(row: Mapping[str, Any], native: str, normalized: str) -> None:
    if native not in row or normalized not in row:
        return
    left, right = row[native], row[normalized]
    if native == "IsTrading":
        if _trading_flag(left) is not _trading_flag(right):
            _fail("CATALOG_FIELD_CONFLICT")
        return
    if not _same_field_value(left, right):
        _fail("CATALOG_FIELD_CONFLICT")


def _canonical_value(value: Any) -> Any:
    """Encode public row values without arbitrary ``str``/``repr`` calls."""

    if value is None:
        return {"type": "none"}
    if type(value) is bool:
        return {"type": "bool", "value": value}
    if type(value) is int:
        return {"type": "int", "value": str(value)}
    if type(value) is float:
        return {"type": "float", "value": value.hex()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if type(value) is str:
        return {"type": "str", "value": value}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if type(value) is date:
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            _fail("QUERY_ROW_KEY_UNSUPPORTED")
        return {
            "type": "mapping",
            "value": {key: _canonical_value(value[key]) for key in sorted(value)},
        }
    if type(value) is tuple:
        return {"type": "tuple", "value": [_canonical_value(item) for item in value]}
    if type(value) is list:
        return {"type": "list", "value": [_canonical_value(item) for item in value]}
    _fail("QUERY_ROW_VALUE_UNSUPPORTED")


def _record_digest(records: Tuple[Any, ...]) -> str:
    payload = json.dumps(
        _canonical_value(records),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _request_filter_pairs(result: Any) -> Optional[tuple]:
    source = getattr(result, "query_source", None)
    filters = getattr(source, "request_filters", None)
    if type(filters) is not tuple or any(
        type(pair) is not tuple
        or len(pair) != 2
        or type(pair[0]) is not str
        or type(pair[1]) is not str
        for pair in filters
    ):
        return None
    return filters


def _load_sdk_contract() -> tuple[type, Callable[[Any], Mapping[str, Any]]]:
    try:
        from bt_api_ctp.instrument import normalize_ctp_instrument
        from bt_api_ctp.query import QueryResult
    except ImportError:
        _fail("CTP_SDK_UNAVAILABLE")
    return QueryResult, normalize_ctp_instrument


def _session_facts(feed: Any) -> tuple[date, Any]:
    method = getattr(feed, "get_session_state", None)
    if not callable(method):
        _fail("SESSION_STATE_METHOD_MISSING")
    try:
        state = method()
    except Exception:
        _fail("SESSION_STATE_UNAVAILABLE")
    if not isinstance(state, Mapping):
        _fail("SESSION_STATE_UNAVAILABLE")
    if state.get("connected") is not True or state.get("read_only_ready") is not True:
        _fail("SESSION_NOT_READ_ONLY_READY")
    generation = state.get("connection_generation")
    if type(generation) is not int or generation <= 0:
        _fail("SESSION_GENERATION_UNAVAILABLE")
    day = _trading_day(state.get("trading_day"), "SESSION_TRADING_DAY_UNAVAILABLE")
    return day, generation


def _validate_query_result(
    result: Any,
    *,
    query_type: type,
    expected_request_type: str,
    expected_generation: Any,
    retrieved_at: datetime,
    expected_request_filters: Optional[tuple] = None,
    max_records: Optional[int] = None,
) -> tuple[datetime, datetime, int, str]:
    if not isinstance(result, query_type):
        _fail("QUERY_RESULT_TYPE_INVALID")
    if type(result.request_type) is not str:
        _fail("QUERY_REQUEST_TYPE_INVALID")
    if result.request_type != expected_request_type:
        _fail("QUERY_REQUEST_TYPE_MISMATCH")
    if type(result.timed_out) is not bool or type(result.unsupported) is not bool:
        _fail("QUERY_BOOLEAN_STATE_INVALID")
    if result.timed_out:
        _fail("QUERY_TIMED_OUT")
    if result.unsupported:
        _fail("QUERY_UNSUPPORTED")
    if result.error_code is not None and not (
        type(result.error_code) is int and result.error_code == 0
    ):
        _fail("QUERY_ERROR")
    if result.submit_code is not None and not (
        type(result.submit_code) is int and result.submit_code == 0
    ):
        _fail("QUERY_SUBMISSION_FAILED")
    if type(result.error_message) is not str:
        _fail("QUERY_ERROR_STATE_INVALID")
    if result.error_message:
        _fail("QUERY_ERROR_MESSAGE")
    if type(result.request_id) is not int or result.request_id <= 0:
        _fail("QUERY_REQUEST_ID_INVALID")
    if type(result.connection_generation) is not int or result.connection_generation <= 0:
        _fail("QUERY_GENERATION_INVALID")
    if result.connection_generation != expected_generation:
        _fail("QUERY_GENERATION_MISMATCH")
    if type(result.records) is not tuple:
        _fail("QUERY_RECORDS_NOT_IMMUTABLE")
    if expected_request_filters is not None:
        if _request_filter_pairs(result) != expected_request_filters:
            _fail("QUERY_REQUEST_FILTERS_MISMATCH")
    if max_records is not None:
        if type(max_records) is not int or max_records <= 0:
            _fail("QUERY_RECORD_LIMIT_INVALID")
        if type(getattr(result, "record_limit", None)) is not int:
            _fail("QUERY_RECORD_LIMIT_UNAVAILABLE")
        if result.record_limit != max_records:
            _fail("QUERY_RECORD_LIMIT_MISMATCH")
        if type(getattr(result, "record_limit_exceeded", None)) is not bool:
            _fail("QUERY_RECORD_LIMIT_STATE_INVALID")
        if result.record_limit_exceeded:
            _fail("QUERY_RECORD_LIMIT_EXCEEDED")
        if len(result.records) > max_records:
            _fail("QUERY_RECORD_LIMIT_EXCEEDED")
        if getattr(result, "completion_origin", None) == "record_limit":
            _fail("QUERY_RECORD_LIMIT_EXCEEDED")
    if result.complete is not True:
        _fail("QUERY_INCOMPLETE")
    if result.is_last_seen is not True:
        _fail("QUERY_TERMINAL_PACKET_MISSING")
    if type(result.late_callback_count) is not int or result.late_callback_count != 0:
        _fail("QUERY_LATE_CALLBACKS")
    started_at = _aware_utc(result.started_at_utc, "QUERY_START_TIME_INVALID")
    if result.completed_at_utc is None:
        _fail("QUERY_COMPLETION_TIME_MISSING")
    completed_at = _aware_utc(result.completed_at_utc, "QUERY_COMPLETION_TIME_INVALID")
    if completed_at < started_at:
        _fail("QUERY_TIME_REVERSED")
    if started_at > retrieved_at or completed_at > retrieved_at:
        _fail("QUERY_TIME_IN_FUTURE")
    digest = _record_digest(result.records)
    return started_at, completed_at, result.request_id, digest


def _catalog_records(rows: Tuple[Any, ...], normalize: Callable) -> tuple:
    from backtrader.feeds.futures_main_contract import (
        FuturesContractCatalogRecord,
        ProductKey,
    )

    output = []
    for raw in rows:
        row = _mapping_row(raw, "CATALOG_ROW_INVALID")
        for native, alias in (
            ("InstrumentID", "instrument_id"),
            ("ExchangeID", "exchange_id"),
            ("ProductID", "product_id"),
            ("ProductClass", "product_class"),
            ("IsTrading", "is_trading"),
            ("ExpireDate", "expiry_date"),
        ):
            _assert_alias_equivalent(row, native, alias)
        instrument = _ctp_text(
            _field(
                row,
                "InstrumentID",
                "instrument_id",
                missing_code="CATALOG_INSTRUMENT_ID_MISSING",
            ),
            "CATALOG_IDENTITY_INVALID",
        )
        exchange = _ctp_text(
            _field(
                row,
                "ExchangeID",
                "exchange_id",
                missing_code="CATALOG_EXCHANGE_ID_MISSING",
            ),
            "CATALOG_IDENTITY_INVALID",
        )
        product_id = _ctp_text(
            _field(
                row,
                "ProductID",
                "product_id",
                missing_code="CATALOG_PRODUCT_ID_MISSING",
            ),
            "CATALOG_IDENTITY_INVALID",
        )
        try:
            normalized = normalize(dict(row))
        except Exception:
            _fail("CATALOG_NORMALIZATION_FAILED")
        if not isinstance(normalized, Mapping):
            _fail("CATALOG_NORMALIZATION_FAILED")
        asset_type = normalized.get("asset_type")
        if type(asset_type) is not str:
            asset_type = None
        is_trading = normalized.get("is_trading")
        if is_trading is not None and type(is_trading) is not bool:
            is_trading = None
        expiry_value = _ctp_text(
            _field(
                row,
                "ExpireDate",
                "expiry_date",
                missing_code="CATALOG_EXPIRY_INVALID",
                required=False,
            ),
            "CATALOG_EXPIRY_INVALID",
            required=False,
        )
        expiry_date = None
        if expiry_value not in (None, ""):
            try:
                expiry_date = _trading_day(expiry_value, "CATALOG_EXPIRY_INVALID")
            except CtpFuturesSnapshotError:
                _fail("CATALOG_EXPIRY_INVALID")
        product_class_value = _ctp_text(
            _field(
                row,
                "ProductClass",
                "product_class",
                missing_code="CATALOG_PRODUCT_CLASS_MISSING",
                required=False,
            ),
            "CATALOG_PRODUCT_CLASS_INVALID",
            required=False,
        )
        product_class = normalized.get("product_class")
        if product_class_value is not None:
            normalized_product_class = normalized.get("product_class")
            if type(normalized_product_class) is not str:
                _fail("CATALOG_PRODUCT_CLASS_INVALID")
            if normalized_product_class != product_class_value:
                _fail("CATALOG_PRODUCT_CLASS_MISMATCH")
            product_class = normalized_product_class
        else:
            product_class = None
        output.append(
            FuturesContractCatalogRecord(
                product=ProductKey(exchange, product_id),
                instrument_id=instrument,
                asset_type=asset_type,
                is_trading=is_trading,
                expiry_date=expiry_date,
                product_class=product_class,
            )
        )
    return tuple(output)


def _product_evidence(rows: Tuple[Any, ...]) -> tuple:
    from backtrader.feeds.futures_main_contract import (
        MAX_VISIBLE_CTP_PRODUCTS,
        _CTP_PRODUCT_CLASS_ASSET_TYPE,
        ProductKey,
        QuerySnapshotExcludedProductEvidence,
        QuerySnapshotProductEvidence,
    )

    if not rows:
        _fail("PRODUCT_QUERY_EMPTY")
    if len(rows) > MAX_VISIBLE_CTP_PRODUCTS:
        _fail("PRODUCT_QUERY_RECORD_CAP_EXCEEDED")
    futures = []
    excluded = []
    canonical_to_native = {}
    for raw in rows:
        row = _mapping_row(raw, "PRODUCT_ROW_INVALID")
        for native, alias in (
            ("ExchangeID", "exchange_id"),
            ("ProductID", "product_id"),
            ("ProductClass", "product_class"),
        ):
            if native in row and alias in row and not _same_field_value(row[native], row[alias]):
                _fail("PRODUCT_FIELD_CONFLICT")
        exchange = _ctp_text(
            _field(
                row,
                "ExchangeID",
                "exchange_id",
                missing_code="PRODUCT_EXCHANGE_ID_MISSING",
            ),
            "PRODUCT_EXCHANGE_ID_INVALID",
        )
        product_id = _ctp_text(
            _field(
                row,
                "ProductID",
                "product_id",
                missing_code="PRODUCT_ID_MISSING",
            ),
            "PRODUCT_ID_INVALID",
        )
        product_class = _ctp_text(
            _field(
                row,
                "ProductClass",
                "product_class",
                missing_code="PRODUCT_CLASS_MISSING",
            ),
            "PRODUCT_CLASS_INVALID",
        )
        asset_type = _CTP_PRODUCT_CLASS_ASSET_TYPE.get(product_class)
        if asset_type is None:
            _fail("PRODUCT_CLASS_UNKNOWN")
        product = ProductKey(exchange, product_id)
        native_pair = (exchange, product_id)
        prior = canonical_to_native.get(product)
        if prior is not None:
            if prior[2] != product_class:
                _fail("PRODUCT_CLASS_CONFLICT")
            if prior[:2] != native_pair:
                _fail("PRODUCT_CANONICAL_COLLISION")
            _fail("PRODUCT_DUPLICATE")
        canonical_to_native[product] = (*native_pair, product_class)
        if product_class == "1":
            futures.append(
                QuerySnapshotProductEvidence(
                    product=product,
                    native_exchange_id=exchange,
                    native_product_id=product_id,
                    product_class=product_class,
                )
            )
        else:
            excluded.append(
                QuerySnapshotExcludedProductEvidence(
                    product=product,
                    native_exchange_id=exchange,
                    native_product_id=product_id,
                    product_class=product_class,
                    asset_type=asset_type,
                )
            )
    futures.sort(key=lambda item: (item.product.exchange_id, item.product.product_id))
    excluded.sort(key=lambda item: (item.product.exchange_id, item.product.product_id))
    return tuple(futures), tuple(excluded)


def _query_source_evidence(
    *,
    source_prefix: str,
    method_name: str,
    source_kind: str,
    result: Any,
    generation: int,
    trading_day: date,
    started_at: datetime,
    completed_at: datetime,
    retrieved_at: datetime,
    request_id: int,
    source_sha256: str,
    request_filters: tuple,
    record_limit: int,
    record_count: Optional[int] = None,
) -> Any:
    from backtrader.feeds.futures_main_contract import QuerySnapshotSourceEvidence

    return QuerySnapshotSourceEvidence(
        source_id="{}.{}".format(source_prefix, method_name),
        source_kind=source_kind,
        snapshot_id="ctp-visible-{}:{}:{}:{}:{}".format(
            source_kind,
            generation,
            trading_day.strftime(_DAY_FORMAT),
            request_id,
            source_sha256[:16],
        ),
        source_sha256=source_sha256,
        request_id=request_id,
        connection_generation=generation,
        trading_day=trading_day,
        started_at=started_at,
        completed_at=completed_at,
        retrieved_at=retrieved_at,
        complete=True,
        is_last_seen=True,
        record_count=len(result.records) if record_count is None else record_count,
        request_filters=request_filters,
        record_limit=record_limit,
        record_limit_exceeded=False,
    )


_STAGED_DEPTH_MODES = frozenset({"single_depth", "per_product_depth"})


def _collect_staged_ctp_futures_snapshot(
    feed: Any,
    *,
    max_collection_seconds: float,
    max_snapshot_age_seconds: float,
    source_prefix: str,
    observations: list,
    depth_mode: str = "single_depth",
) -> Any:
    """Collect a bounded all-class product and futures-only query set.

    The local adapter retains only normalized rows and query receipts after
    each request. The SDK also keeps its bounded sealed-query history; the
    all-class product, cumulative futures-instrument, and depth caps bound
    those retained rows. Known non-futures product classes remain explicit in
    the query-set evidence and do not trigger per-product instrument queries.

    ``depth_mode`` selects how current-day depth rows are requested:

    - ``single_depth`` keeps the legacy all-instrument depth query.
    - ``per_product_depth`` issues one depth query per class-1 product using
      that product's native exchange/product IDs. During the night session the
      single all-instrument request can stall on some fronts while the
      per-product prefix-filtered requests complete promptly.
    """
    if depth_mode not in _STAGED_DEPTH_MODES:
        _fail("DEPTH_MODE_INVALID")

    from backtrader.feeds.futures_main_contract import (
        _CTP_PRODUCT_CLASS_ASSET_TYPE,
        MAX_PRODUCT_INSTRUMENT_ROWS,
        MAX_VISIBLE_DEPTH_ROWS,
        MAX_VISIBLE_CTP_PRODUCTS,
        MainContractQuerySnapshot,
        QuerySnapshotSetEvidence,
        query_snapshot_set_digest,
    )

    if (
        type(source_prefix) is not str
        or not source_prefix.isascii()
        or _SOURCE_PREFIX_RE.fullmatch(source_prefix) is None
    ):
        _fail("SOURCE_PREFIX_INVALID")
    collection_limit = _duration(max_collection_seconds, "COLLECTION_LIMIT")
    snapshot_age_limit = _duration(max_snapshot_age_seconds, "SNAPSHOT_AGE_LIMIT")
    query_type, normalize_instrument = _load_sdk_contract()
    query_products = getattr(feed, "query_products_result", None)
    query_instruments = getattr(feed, "query_instruments_result", None)
    query_depth = getattr(feed, "query_depth_market_data_result", None)
    if not all(callable(method) for method in (query_products, query_instruments, query_depth)):
        _fail("PUBLIC_QUERY_METHOD_MISSING")

    started_monotonic = time.monotonic()
    day_before, generation_before = _session_facts(feed)
    deadline = started_monotonic + collection_limit

    def run_query(
        *,
        stage: str,
        method: Callable,
        kwargs: dict,
        request_type: str,
        prior_complete: Optional[bool],
        max_records: int,
        request_filters: tuple,
    ) -> tuple[Any, datetime, datetime, datetime, int, str]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _fail("COLLECTION_TIMEOUT", tuple(observations))
        call_hard_limit = kwargs.pop("_hard_limit")
        hard_limit = min(remaining, call_hard_limit)
        if hard_limit <= 0:
            _fail("COLLECTION_TIMEOUT", tuple(observations))
        idle_limit = min(_MAX_QUERY_IDLE_SECONDS, hard_limit)
        call_kwargs = dict(kwargs)
        call_kwargs.update(
            timeout=idle_limit,
            max_duration=hard_limit,
            deadline_monotonic=deadline,
            max_records=max_records,
        )
        call_started = time.monotonic()
        try:
            result = method(**call_kwargs)
        except Exception:
            call_returned = time.monotonic()
            observations.append(
                _query_observation(
                    stage=stage,
                    entered=True,
                    returned=False,
                    started_monotonic=call_started,
                    returned_monotonic=call_returned,
                    prior_stage_complete=prior_complete,
                    result=None,
                    query_type=query_type,
                    expected_request_type=request_type,
                    expected_generation=generation_before,
                    expected_record_limit=max_records,
                    expected_request_filters=request_filters,
                )
            )
            _fail("{}_QUERY_CALL_FAILED".format(stage.upper()), tuple(observations))
        call_returned = time.monotonic()
        observations.append(
            _query_observation(
                stage=stage,
                entered=True,
                returned=True,
                started_monotonic=call_started,
                returned_monotonic=call_returned,
                prior_stage_complete=prior_complete,
                result=result,
                query_type=query_type,
                expected_request_type=request_type,
                expected_generation=generation_before,
                expected_record_limit=max_records,
                expected_request_filters=request_filters,
            )
        )
        retrieved_at = _aware_utc(_now_utc(), "COLLECTOR_CLOCK_INVALID")
        try:
            started_at, completed_at, request_id, digest = _validate_query_result(
                result,
                query_type=query_type,
                expected_request_type=request_type,
                expected_generation=generation_before,
                retrieved_at=retrieved_at,
                expected_request_filters=request_filters,
                max_records=max_records,
            )
        except CtpFuturesSnapshotError as error:
            _fail(error.code, tuple(observations))
        if time.monotonic() > deadline:
            _fail("COLLECTION_TIMEOUT", tuple(observations))
        return result, started_at, completed_at, retrieved_at, request_id, digest

    product_filters = (
        ("ExchangeID", ""),
        ("ProductClass", ""),
        ("ProductID", ""),
    )
    first_remaining = deadline - time.monotonic()
    product_hard_limit = min(_MAX_PRODUCT_QUERY_HARD_SECONDS, first_remaining / 10.0)
    (
        product_result,
        product_started,
        product_completed,
        product_retrieved,
        product_request_id,
        product_digest,
    ) = run_query(
        stage="products",
        method=query_products,
        kwargs={
            "product_class": "",
            "exchange_id": "",
            "product_id": "",
            "_hard_limit": product_hard_limit,
        },
        request_type="products",
        prior_complete=None,
        max_records=MAX_VISIBLE_CTP_PRODUCTS,
        request_filters=product_filters,
    )
    product_evidence, excluded_product_evidence = _product_evidence(product_result.records)
    observations[-1] = replace(
        observations[-1],
        classified_future_product_count=len(product_evidence),
        classified_excluded_product_count=len(excluded_product_evidence),
    )
    if not product_evidence:
        _fail("PRODUCT_FUTURE_SET_EMPTY", tuple(observations))
    product_source = _query_source_evidence(
        source_prefix=source_prefix,
        method_name="query_products_result",
        source_kind="products",
        result=product_result,
        generation=generation_before,
        trading_day=day_before,
        started_at=product_started,
        completed_at=product_completed,
        retrieved_at=product_retrieved,
        request_id=product_request_id,
        source_sha256=product_digest,
        request_filters=product_filters,
        record_limit=MAX_VISIBLE_CTP_PRODUCTS,
    )
    del product_result

    catalog_records = []
    catalog_ids_by_product = {}
    request_sources = [product_source]
    request_ids = [product_request_id]
    for product_index, product in enumerate(product_evidence):
        remaining_rows = MAX_PRODUCT_INSTRUMENT_ROWS - len(catalog_records)
        if remaining_rows <= 0:
            _fail("INSTRUMENT_RECORD_CAP_EXHAUSTED", tuple(observations))
        remaining = deadline - time.monotonic()
        # Let heterogeneous instrument responses borrow the remaining global
        # budget. The SDK applies this as the request's progressive hard cap
        # while retaining its idle timeout; the absolute collection deadline
        # still limits both this request and every later stage. Re-dividing
        # the remainder equally across pending calls can time out a slow early
        # product even when later products respond quickly enough to finish
        # the complete set within the same global deadline.
        hard_limit = remaining
        instrument_filters = (
            ("ExchangeID", product.native_exchange_id),
            ("InstrumentID", ""),
            ("ProductID", product.native_product_id),
        )
        stage = "instruments_{:03d}".format(product_index + 1)
        (
            instrument_result,
            query_started,
            query_completed,
            query_retrieved,
            request_id,
            digest,
        ) = run_query(
            stage=stage,
            method=query_instruments,
            kwargs={
                "instrument_id": "",
                "exchange_id": product.native_exchange_id,
                "product_id": product.native_product_id,
                "_hard_limit": hard_limit,
            },
            request_type="instruments",
            prior_complete=True,
            max_records=remaining_rows,
            request_filters=instrument_filters,
        )
        raw = None
        for raw in instrument_result.records:
            row = _mapping_row(raw, "CATALOG_ROW_INVALID")
            raw_exchange = _ctp_text(
                _field(
                    row,
                    "ExchangeID",
                    "exchange_id",
                    missing_code="CATALOG_EXCHANGE_ID_MISSING",
                ),
                "CATALOG_IDENTITY_INVALID",
            )
            raw_product = _ctp_text(
                _field(
                    row,
                    "ProductID",
                    "product_id",
                    missing_code="CATALOG_PRODUCT_ID_MISSING",
                ),
                "CATALOG_IDENTITY_INVALID",
            )
            if (
                raw_exchange != product.native_exchange_id
                or raw_product != product.native_product_id
            ):
                _fail("INSTRUMENT_QUERY_ROW_SCOPE_MISMATCH", tuple(observations))
        rows = _catalog_records(instrument_result.records, normalize_instrument)
        if any(record.product != product.product for record in rows):
            _fail("INSTRUMENT_QUERY_ROW_SCOPE_MISMATCH", tuple(observations))
        for record in rows:
            if record.product_class not in _CTP_PRODUCT_CLASS_ASSET_TYPE:
                _fail("CATALOG_PRODUCT_CLASS_UNKNOWN", tuple(observations))
            if record.product_class != product.product_class:
                _fail("INSTRUMENT_PRODUCT_CLASS_MISMATCH", tuple(observations))
        if len(catalog_records) + len(rows) > MAX_PRODUCT_INSTRUMENT_ROWS:
            _fail("INSTRUMENT_RECORD_CAP_EXCEEDED", tuple(observations))
        catalog_records.extend(rows)
        catalog_ids_by_product[product.product] = frozenset(
            record.instrument_id for record in rows
        )
        del raw
        request_sources.append(
            _query_source_evidence(
                source_prefix=source_prefix,
                method_name="query_instruments_result",
                source_kind="instruments",
                result=instrument_result,
                generation=generation_before,
                trading_day=day_before,
                started_at=query_started,
                completed_at=query_completed,
                retrieved_at=query_retrieved,
                request_id=request_id,
                source_sha256=digest,
                request_filters=instrument_filters,
                record_limit=remaining_rows,
            )
        )
        request_ids.append(request_id)
        del instrument_result

    instrument_owner_by_key = {}
    for owner_product, instrument_ids in catalog_ids_by_product.items():
        for instrument_id in instrument_ids:
            instrument_owner_by_key[
                (owner_product.exchange_id, instrument_id)
            ] = owner_product

    if depth_mode == "single_depth":
        depth_filters = (
            ("ExchangeID", ""),
            ("InstrumentID", ""),
            ("ProductClass", "1"),
        )
        depth_remaining = deadline - time.monotonic()
        (
            depth_result,
            depth_started,
            depth_completed,
            depth_retrieved,
            depth_request_id,
            depth_digest,
        ) = run_query(
            stage="depth",
            method=query_depth,
            kwargs={
                "instrument_id": "",
                "exchange_id": "",
                "product_class": "1",
                "_hard_limit": depth_remaining,
            },
            request_type="depth_market_data",
            prior_complete=True,
            max_records=MAX_VISIBLE_DEPTH_ROWS,
            request_filters=depth_filters,
        )
        if depth_request_id in request_ids:
            _fail("QUERY_REQUEST_ID_COLLISION", tuple(observations))
        quote_records = _quote_records(depth_result.records)
        request_sources.append(
            _query_source_evidence(
                source_prefix=source_prefix,
                method_name="query_depth_market_data_result",
                source_kind="depth_market_data",
                result=depth_result,
                generation=generation_before,
                trading_day=day_before,
                started_at=depth_started,
                completed_at=depth_completed,
                retrieved_at=depth_retrieved,
                request_id=depth_request_id,
                source_sha256=depth_digest,
                request_filters=depth_filters,
                record_limit=MAX_VISIBLE_DEPTH_ROWS,
            )
        )
        del depth_result
    else:
        # One depth query per class-1 product. The product ID is passed as the
        # native InstrumentID prefix so the front applies its own product
        # filter; every receipt keeps the exact per-product filters and the
        # cumulative depth cap.
        #
        # CTP treats InstrumentID as a prefix filter. A product ID that is also
        # a prefix of sibling products (CFFEX ``T`` vs ``TF``/``TS``/``TL``,
        # DCE ``j`` vs ``jd``/``jm``) therefore returns those sibling rows too.
        # Rows that the fully-collected catalog attributes to another class-1
        # product are discarded here: that product's own depth query retains
        # them, so the union stays complete and no row is counted twice. A row
        # that belongs to no visible catalog product still blocks the snapshot.
        collected_quotes = []
        for depth_index, product in enumerate(product_evidence):
            remaining_rows = MAX_VISIBLE_DEPTH_ROWS - len(collected_quotes)
            if remaining_rows <= 0:
                _fail("DEPTH_RECORD_CAP_EXHAUSTED", tuple(observations))
            depth_filters = (
                ("ExchangeID", product.native_exchange_id),
                ("InstrumentID", product.native_product_id),
                ("ProductClass", "1"),
            )
            stage = "depth_{:03d}".format(depth_index + 1)
            (
                depth_result,
                depth_started,
                depth_completed,
                depth_retrieved,
                depth_request_id,
                depth_digest,
            ) = run_query(
                stage=stage,
                method=query_depth,
                kwargs={
                    "instrument_id": product.native_product_id,
                    "exchange_id": product.native_exchange_id,
                    "product_class": "1",
                    "_hard_limit": deadline - time.monotonic(),
                },
                request_type="depth_market_data",
                prior_complete=True,
                max_records=remaining_rows,
                request_filters=depth_filters,
            )
            if depth_request_id in request_ids:
                _fail("QUERY_REQUEST_ID_COLLISION", tuple(observations))
            rows = _quote_records(depth_result.records)
            catalog_ids = catalog_ids_by_product.get(product.product, frozenset())
            scoped_rows = []
            for record in rows:
                if record.exchange_id != product.native_exchange_id:
                    _fail("DEPTH_PRODUCT_ROW_SCOPE_MISMATCH", tuple(observations))
                if record.instrument_id in catalog_ids:
                    scoped_rows.append(record)
                    continue
                owner = instrument_owner_by_key.get(
                    (record.exchange_id.upper(), record.instrument_id)
                )
                if owner is None or owner == product.product:
                    _fail("DEPTH_PRODUCT_ROW_SCOPE_MISMATCH", tuple(observations))
                # Prefix spillover from a sibling class-1 product: its own
                # depth query retains this row.
            collected_quotes.extend(scoped_rows)
            request_sources.append(
                _query_source_evidence(
                    source_prefix=source_prefix,
                    method_name="query_depth_market_data_result",
                    source_kind="depth_market_data",
                    result=depth_result,
                    generation=generation_before,
                    trading_day=day_before,
                    started_at=depth_started,
                    completed_at=depth_completed,
                    retrieved_at=depth_retrieved,
                    request_id=depth_request_id,
                    source_sha256=depth_digest,
                    request_filters=depth_filters,
                    record_limit=remaining_rows,
                    record_count=len(scoped_rows),
                )
            )
            request_ids.append(depth_request_id)
            del depth_result
        quote_keys = [(row.exchange_id.upper(), row.instrument_id) for row in collected_quotes]
        if len(quote_keys) != len(set(quote_keys)):
            _fail("QUOTE_ROW_DUPLICATE", tuple(observations))
        quote_records = tuple(collected_quotes)
        del collected_quotes

    day_after, generation_after = _session_facts(feed)
    if day_before != day_after or generation_before != generation_after:
        _fail("SESSION_CHANGED_DURING_COLLECTION", tuple(observations))
    if len(request_ids) != len(set(request_ids)):
        _fail("QUERY_REQUEST_ID_COLLISION", tuple(observations))
    query_sources = tuple(request_sources)
    product_tuple = tuple(product_evidence)
    excluded_product_tuple = tuple(excluded_product_evidence)
    query_set_sha256 = query_snapshot_set_digest(
        product_tuple,
        query_sources,
        excluded_product_tuple,
        request_layout=depth_mode,
    )
    query_set = QuerySnapshotSetEvidence(
        source_id="{}.staged_futures_query_set".format(source_prefix),
        snapshot_id="ctp-visible-futures-set:{}:{}:{}".format(
            generation_before,
            day_before.strftime(_DAY_FORMAT),
            query_set_sha256[:16],
        ),
        source_sha256=query_set_sha256,
        products=product_tuple,
        requests=query_sources,
        excluded_products=excluded_product_tuple,
        request_layout=depth_mode,
    )
    snapshot = MainContractQuerySnapshot(
        catalog_source=None,
        quote_source=None,
        catalog_records=tuple(catalog_records),
        quote_records=quote_records,
        session_trading_day_before=day_before,
        session_trading_day_after=day_after,
        session_generation_before=generation_before,
        session_generation_after=generation_after,
        query_set=query_set,
    )
    if time.monotonic() - started_monotonic > collection_limit:
        _fail("COLLECTION_TIMEOUT", tuple(observations))
    final_retrieved_at = _aware_utc(_now_utc(), "COLLECTOR_CLOCK_INVALID")
    for source in query_sources:
        age = (final_retrieved_at - source.completed_at).total_seconds()
        if age < 0:
            _fail("QUERY_TIME_IN_FUTURE", tuple(observations))
        if age > snapshot_age_limit:
            _fail("SNAPSHOT_TOO_OLD", tuple(observations))
    return snapshot


def _quote_records(rows: Tuple[Any, ...]) -> tuple:
    from backtrader.feeds.futures_main_contract import CurrentDayQuoteRecord

    output = []
    for raw in rows:
        row = _mapping_row(raw, "QUOTE_ROW_INVALID")
        exchange = _ctp_text(
            _field(
                row,
                "ExchangeID",
                "exchange_id",
                missing_code="QUOTE_EXCHANGE_ID_MISSING",
            ),
            "QUOTE_IDENTITY_INVALID",
        )
        instrument = _ctp_text(
            _field(
                row,
                "InstrumentID",
                "instrument_id",
                missing_code="QUOTE_INSTRUMENT_ID_MISSING",
            ),
            "QUOTE_IDENTITY_INVALID",
        )
        day_value = _ctp_text(
            _field(
                row,
                "TradingDay",
                "trading_day",
                missing_code="QUOTE_TRADING_DAY_MISSING",
            ),
            "QUOTE_TRADING_DAY_INVALID",
        )
        day = _trading_day(day_value, "QUOTE_TRADING_DAY_INVALID")
        open_interest = _field(
            row,
            "OpenInterest",
            "open_interest",
            missing_code="QUOTE_OPEN_INTEREST_MISSING",
            required=False,
        )
        volume = _field(
            row,
            "Volume",
            "volume",
            missing_code="QUOTE_VOLUME_MISSING",
            required=False,
        )
        action_day = _ctp_text(
            _field(
                row,
                "ActionDay",
                "action_day",
                missing_code="QUOTE_ACTION_DAY_INVALID",
                required=False,
            ),
            "QUOTE_ACTION_DAY_INVALID",
            required=False,
        )
        update_time = _ctp_text(
            _field(
                row,
                "UpdateTime",
                "update_time",
                missing_code="QUOTE_UPDATE_TIME_INVALID",
                required=False,
            ),
            "QUOTE_UPDATE_TIME_INVALID",
            required=False,
        )
        update_millisec = _field(
            row,
            "UpdateMillisec",
            "update_millisec",
            missing_code="QUOTE_UPDATE_MILLISEC_INVALID",
            required=False,
        )
        if update_millisec is not None and (
            type(update_millisec) is not int or update_millisec < 0
        ):
            _fail("QUOTE_UPDATE_MILLISEC_INVALID")
        output.append(
            CurrentDayQuoteRecord(
                exchange_id=exchange,
                instrument_id=instrument,
                trading_day=day,
                open_interest=open_interest,
                volume=volume,
                action_day=action_day,
                update_time=update_time,
                update_millisec=update_millisec,
            )
        )
    return tuple(output)


def _collect_ctp_futures_snapshot(
    feed: Any,
    *,
    max_collection_seconds: float = _DEFAULT_MAX_COLLECTION_SECONDS,
    max_snapshot_age_seconds: float = _DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    source_prefix: str = "bt_api_ctp.CtpLiveFeed",
    _query_observations: Any,
) -> Any:
    """Collect complete all-visible catalog and current-depth query evidence.

    ``feed`` is an injected ``CtpLiveFeed`` (or a source-faithful test double).
    The two public queries always use empty filters.  The configured duration
    is checked against both the local monotonic span and the SDK's sealed UTC
    request timestamps. SDK timeout arguments are bounded by the remaining
    duration, and both queries receive the same absolute monotonic deadline.
    The collector rejects a result that returns after that deadline, but cannot
    interrupt a native request call that itself blocks beyond the budget.

    Snapshot age is measured from each complete query's ``completed_at_utc``.
    The CTP depth row's UpdateTime is retained only for source audit and is not
    used as a receive time or freshness estimate.
    ``source_prefix`` is descriptive provenance for the public forwarding path;
    it is not an identity or authority proof.
    """

    if (
        type(source_prefix) is not str
        or not source_prefix.isascii()
        or _SOURCE_PREFIX_RE.fullmatch(source_prefix) is None
    ):
        _fail("SOURCE_PREFIX_INVALID")
    collection_limit = _duration(max_collection_seconds, "COLLECTION_LIMIT")
    snapshot_age_limit = _duration(max_snapshot_age_seconds, "SNAPSHOT_AGE_LIMIT")
    query_type, normalize_instrument = _load_sdk_contract()
    query_instruments = getattr(feed, "query_instruments_result", None)
    query_depth = getattr(feed, "query_depth_market_data_result", None)
    if not callable(query_instruments) or not callable(query_depth):
        _fail("PUBLIC_QUERY_METHOD_MISSING")
    get_session_state = getattr(feed, "get_session_state", None)
    if not callable(get_session_state):
        _fail("SESSION_STATE_METHOD_MISSING")

    started_monotonic = time.monotonic()
    day_before, generation_before = _session_facts(feed)
    deadline = started_monotonic + collection_limit

    remaining = min(collection_limit, deadline - time.monotonic())
    if remaining <= 0:
        _fail("COLLECTION_TIMEOUT")
    catalog_call_started = time.monotonic()
    try:
        catalog_result = query_instruments(
            instrument_id="",
            exchange_id="",
            product_id="",
            timeout=remaining,
            max_duration=remaining,
            deadline_monotonic=deadline,
        )
    except Exception:
        catalog_call_returned = time.monotonic()
        _query_observations.append(
            _query_observation(
                stage="catalog",
                entered=True,
                returned=False,
                started_monotonic=catalog_call_started,
                returned_monotonic=catalog_call_returned,
                prior_stage_complete=None,
                result=None,
                query_type=query_type,
                expected_request_type="instruments",
                expected_generation=generation_before,
            )
        )
        _fail("CATALOG_QUERY_CALL_FAILED", tuple(_query_observations))
    catalog_call_returned = time.monotonic()
    catalog_observation = _query_observation(
        stage="catalog",
        entered=True,
        returned=True,
        started_monotonic=catalog_call_started,
        returned_monotonic=catalog_call_returned,
        prior_stage_complete=None,
        result=catalog_result,
        query_type=query_type,
        expected_request_type="instruments",
        expected_generation=generation_before,
    )
    _query_observations.append(catalog_observation)
    catalog_retrieved_at = _aware_utc(_now_utc(), "COLLECTOR_CLOCK_INVALID")
    try:
        (
            catalog_started_at,
            catalog_completed_at,
            catalog_request_id,
            catalog_digest,
        ) = _validate_query_result(
            catalog_result,
            query_type=query_type,
            expected_request_type="instruments",
            expected_generation=generation_before,
            retrieved_at=catalog_retrieved_at,
        )
    except CtpFuturesSnapshotError as error:
        _fail(error.code, tuple(_query_observations))
    if time.monotonic() > deadline:
        _fail("COLLECTION_TIMEOUT", tuple(_query_observations))

    remaining = min(collection_limit, deadline - time.monotonic())
    if remaining <= 0:
        _fail("COLLECTION_TIMEOUT")
    quote_call_started = time.monotonic()
    try:
        quote_result = query_depth(
            instrument_id="",
            exchange_id="",
            timeout=remaining,
            deadline_monotonic=deadline,
        )
    except Exception:
        quote_call_returned = time.monotonic()
        _query_observations.append(
            _query_observation(
                stage="depth",
                entered=True,
                returned=False,
                started_monotonic=quote_call_started,
                returned_monotonic=quote_call_returned,
                prior_stage_complete=True,
                result=None,
                query_type=query_type,
                expected_request_type="depth_market_data",
                expected_generation=generation_before,
            )
        )
        _fail("QUOTE_QUERY_CALL_FAILED", tuple(_query_observations))
    quote_call_returned = time.monotonic()
    quote_observation = _query_observation(
        stage="depth",
        entered=True,
        returned=True,
        started_monotonic=quote_call_started,
        returned_monotonic=quote_call_returned,
        prior_stage_complete=True,
        result=quote_result,
        query_type=query_type,
        expected_request_type="depth_market_data",
        expected_generation=generation_before,
    )
    _query_observations.append(quote_observation)
    quote_retrieved_at = _aware_utc(_now_utc(), "COLLECTOR_CLOCK_INVALID")
    try:
        quote_started_at, quote_completed_at, quote_request_id, quote_digest = (
            _validate_query_result(
                quote_result,
                query_type=query_type,
                expected_request_type="depth_market_data",
                expected_generation=generation_before,
                retrieved_at=quote_retrieved_at,
            )
        )
    except CtpFuturesSnapshotError as error:
        _fail(error.code, tuple(_query_observations))

    day_after, generation_after = _session_facts(feed)
    if day_before != day_after or generation_before != generation_after:
        _fail("SESSION_CHANGED_DURING_COLLECTION")
    if catalog_request_id == quote_request_id:
        _fail("QUERY_REQUEST_ID_COLLISION")
    collection_start = min(catalog_started_at, quote_started_at)
    collection_end = max(catalog_completed_at, quote_completed_at)
    if (collection_end - collection_start).total_seconds() > collection_limit:
        _fail("COLLECTION_SPAN_EXCEEDED")

    catalog_records = _catalog_records(catalog_result.records, normalize_instrument)
    quote_records = _quote_records(quote_result.records)

    from backtrader.feeds.futures_main_contract import (
        MainContractQuerySnapshot,
        QuerySnapshotSourceEvidence,
    )

    catalog_source = QuerySnapshotSourceEvidence(
        source_id=f"{source_prefix}.query_instruments_result",
        source_kind="instruments",
        snapshot_id="ctp-visible-instruments:{}:{}:{}:{}".format(
            generation_before,
            day_before.strftime(_DAY_FORMAT),
            catalog_request_id,
            catalog_digest[:16],
        ),
        source_sha256=catalog_digest,
        request_id=catalog_request_id,
        connection_generation=generation_before,
        trading_day=day_before,
        started_at=catalog_started_at,
        completed_at=catalog_completed_at,
        retrieved_at=catalog_retrieved_at,
        complete=True,
        is_last_seen=True,
        record_count=len(catalog_result.records),
    )
    quote_source = QuerySnapshotSourceEvidence(
        source_id=f"{source_prefix}.query_depth_market_data_result",
        source_kind="depth_market_data",
        snapshot_id="ctp-visible-depth:{}:{}:{}:{}".format(
            generation_before,
            day_before.strftime(_DAY_FORMAT),
            quote_request_id,
            quote_digest[:16],
        ),
        source_sha256=quote_digest,
        request_id=quote_request_id,
        connection_generation=generation_before,
        trading_day=day_before,
        started_at=quote_started_at,
        completed_at=quote_completed_at,
        retrieved_at=quote_retrieved_at,
        complete=True,
        is_last_seen=True,
        record_count=len(quote_result.records),
    )
    snapshot = MainContractQuerySnapshot(
        catalog_source=catalog_source,
        quote_source=quote_source,
        catalog_records=catalog_records,
        quote_records=quote_records,
        session_trading_day_before=day_before,
        session_trading_day_after=day_after,
        session_generation_before=generation_before,
        session_generation_after=generation_after,
    )
    if time.monotonic() - started_monotonic > collection_limit:
        _fail("COLLECTION_TIMEOUT")
    final_retrieved_at = _aware_utc(_now_utc(), "COLLECTOR_CLOCK_INVALID")
    for completed_at in (catalog_completed_at, quote_completed_at):
        age = (final_retrieved_at - completed_at).total_seconds()
        if age < 0:
            _fail("QUERY_TIME_IN_FUTURE")
        if age > snapshot_age_limit:
            _fail("SNAPSHOT_TOO_OLD")
    return snapshot


def collect_ctp_futures_snapshot(
    feed: Any,
    *,
    max_collection_seconds: float = _DEFAULT_MAX_COLLECTION_SECONDS,
    max_snapshot_age_seconds: float = _DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    source_prefix: str = "bt_api_ctp.CtpLiveFeed",
    query_mode: str = "legacy_two_query",
) -> Any:
    """Collect one bounded CTP snapshot using an explicitly selected query mode."""

    observations = []
    try:
        if query_mode == "staged_product_set":
            return _collect_staged_ctp_futures_snapshot(
                feed,
                max_collection_seconds=max_collection_seconds,
                max_snapshot_age_seconds=max_snapshot_age_seconds,
                source_prefix=source_prefix,
                observations=observations,
                depth_mode="single_depth",
            )
        if query_mode == "staged_product_depth":
            return _collect_staged_ctp_futures_snapshot(
                feed,
                max_collection_seconds=max_collection_seconds,
                max_snapshot_age_seconds=max_snapshot_age_seconds,
                source_prefix=source_prefix,
                observations=observations,
                depth_mode="per_product_depth",
            )
        if query_mode != "legacy_two_query":
            _fail("QUERY_MODE_INVALID")
        return _collect_ctp_futures_snapshot(
            feed,
            max_collection_seconds=max_collection_seconds,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
            source_prefix=source_prefix,
            _query_observations=observations,
        )
    except CtpFuturesSnapshotError as error:
        if error.query_observations or not observations:
            raise
        raise CtpFuturesSnapshotError(error.code, tuple(observations)) from None


__all__ = [
    "CtpFuturesSnapshotError",
    "CtpFuturesSnapshotQueryObservation",
    "collect_ctp_futures_snapshot",
]
