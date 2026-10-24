"""Bounded parser and explicit CTP-catalog join for SHFE/INE daily rankings.

The adapter reads the exchange's public ``kxYYYYMMDD.dat`` report only when
``fetch_shfe_eod`` is called. Importing this module performs no network I/O.
The response contains no CTP ``InstrumentID``; callers must join its product
group and delivery month to a separately held, current CTP contract catalog.
The join preserves the catalog's exact IDs and reports gaps and ambiguities.

This module does not claim the exchange's publication time. ``available_at``
is the time this process finished retrieving the complete response, so an
archived report is never backdated as point-in-time evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple


SHFE_EOD_SOURCE_ID = "shfe-ine-public-daily-kx-v1"
SHFE_EOD_URL_TEMPLATE = (
    "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx{trading_day}.dat"
)
SHFE_INE_EXCHANGE_IDS = ("SHFE", "INE")
SHFE_EOD_MAX_BYTES = 2 * 1024 * 1024
SHFE_EOD_TIMEOUT_SECONDS = 10.0
_MAX_TIMEOUT_SECONDS = 60.0
_CHINA_STANDARD_TIME = timezone(timedelta(hours=8), "China Standard Time")
_DATE_RE = re.compile(r"^[0-9]{8}$")
_UPDATE_RE = re.compile(r"^([0-9]{8}) ([0-9]{2}:[0-9]{2}:[0-9]{2})$")
_MONTH_RE = re.compile(r"^[0-9]{4}$")
_UNSIGNED_INTEGER_RE = re.compile(r"^[0-9]+$")
_SIGNED_INTEGER_RE = re.compile(r"^[+-]?[0-9]+$")


class ShfeEodError(ValueError):
    """Stable, non-payload-bearing error from parsing or fetching a report."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects before urllib constructs or sends the next request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ShfeEodError("REDIRECT_REJECTED")


def _open_without_redirects(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(_RejectRedirectHandler())
    return opener.open(request, timeout=timeout)


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if value is None and allow_empty:
        return ""
    if type(value) is not str:
        raise ShfeEodError("INVALID_" + field.upper())
    if value != value.strip() or (not allow_empty and not value):
        raise ShfeEodError("INVALID_" + field.upper())
    return value


def _json_object_no_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ShfeEodError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ShfeEodError("INVALID_JSON_NUMBER")


def _parse_report_date(value: Any) -> date:
    if type(value) is not str or not _DATE_RE.fullmatch(value):
        raise ShfeEodError("INVALID_REPORT_DATE")
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        raise ShfeEodError("INVALID_REPORT_DATE") from None


def _parse_update_time(value: Any) -> datetime:
    if type(value) is not str:
        raise ShfeEodError("INVALID_UPDATE_DATE")
    match = _UPDATE_RE.fullmatch(value)
    if match is None:
        raise ShfeEodError("INVALID_UPDATE_DATE")
    try:
        update_day = _parse_report_date(match.group(1))
        local_time = datetime.strptime(match.group(2), "%H:%M:%S").time()
    except ValueError:
        raise ShfeEodError("INVALID_UPDATE_DATE") from None
    return datetime.combine(update_day, local_time, tzinfo=_CHINA_STANDARD_TIME)


def _nonnegative_int(value: Any, field: str) -> int:
    if type(value) is int and value >= 0:
        return value
    if type(value) is str and _UNSIGNED_INTEGER_RE.fullmatch(value):
        return int(value)
    raise ShfeEodError("INVALID_" + field.upper())


def _signed_int(value: Any, field: str) -> int:
    if type(value) is int:
        return value
    if type(value) is str and _SIGNED_INTEGER_RE.fullmatch(value):
        return int(value)
    raise ShfeEodError("INVALID_" + field.upper())


def _is_source_month(value: str) -> bool:
    if not _MONTH_RE.fullmatch(value):
        return False
    return 1 <= int(value[-2:]) <= 12


@dataclass(frozen=True)
class ShfeDailyContractRow:
    """One ordinary futures row as reported by SHFE, before catalog joining."""

    product_group_id: str
    source_product_id: str
    product_class: str
    delivery_month: str
    volume: int
    open_interest: int
    open_interest_change: Optional[int]
    source_row_index: int


@dataclass(frozen=True)
class ShfeDailyReport:
    """Parsed immutable report and finite row-shape counts."""

    source_id: str
    snapshot_id: str
    source_sha256: str
    report_date: date
    reported_update_at: datetime
    available_at: datetime
    retrieved_at: datetime
    rows: Tuple[ShfeDailyContractRow, ...]
    source_row_count: int
    product_summary_row_count: int
    overall_summary_row_count: int
    nonordinary_row_count: int
    nonordinary_class_counts: Tuple[Tuple[str, int], ...]
    product_summary_table_count: int
    volume_unit: str = "contracts_single_sided"
    open_interest_unit: str = "contracts_single_sided"


@dataclass(frozen=True)
class ShfeCatalogContract:
    """Relevant metadata copied from one actual current CTP catalog row.

    ``instrument_id`` is kept exactly as supplied. ``product_id`` is the CTP
    catalog ProductID used to match SHFE's PRODUCTGROUPID case-insensitively;
    the delivery month must also match the exact final four digits.
    """

    exchange_id: str
    product_id: str
    instrument_id: str
    asset_type: Optional[str]
    is_trading: Optional[bool]
    expiry_date: Optional[date]

    def __post_init__(self) -> None:
        for name in ("exchange_id", "product_id", "instrument_id"):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(name + " must be non-empty trimmed text")
        if self.asset_type is not None and type(self.asset_type) is not str:
            raise ValueError("asset_type must be text or None")
        if self.is_trading is not None and type(self.is_trading) is not bool:
            raise ValueError("is_trading must be bool or None")
        if self.expiry_date is not None and type(self.expiry_date) is not date:
            raise ValueError("expiry_date must be date or None")


@dataclass(frozen=True)
class ShfeJoinedRankingRow:
    """A daily source row matched to exactly one actual catalog contract."""

    exchange_id: str
    product_id: str
    instrument_id: str
    asset_type: Optional[str]
    is_trading: Optional[bool]
    expiry_date: Optional[date]
    source_row: ShfeDailyContractRow


@dataclass(frozen=True)
class ShfeAmbiguousSourceMatch:
    source_row: ShfeDailyContractRow
    candidate_instrument_ids: Tuple[str, ...]


@dataclass(frozen=True)
class ShfeCatalogJoinReport:
    """Explicit one-to-one join diagnostics; no completeness is inferred."""

    matched_rows: Tuple[ShfeJoinedRankingRow, ...]
    unmatched_source_rows: Tuple[ShfeDailyContractRow, ...]
    ambiguous_source_matches: Tuple[ShfeAmbiguousSourceMatch, ...]
    duplicate_source_keys: Tuple[Tuple[str, str], ...]
    duplicate_catalog_instrument_ids: Tuple[str, ...]
    catalog_instrument_ids_without_daily_row: Tuple[str, ...]
    out_of_scope_catalog_instrument_ids: Tuple[str, ...]
    ignored_nonfuture_catalog_instrument_ids: Tuple[str, ...]
    unknown_asset_type_catalog_instrument_ids: Tuple[str, ...]

    @property
    def one_to_one(self) -> bool:
        return not (
            self.unmatched_source_rows
            or self.ambiguous_source_matches
            or self.duplicate_source_keys
            or self.duplicate_catalog_instrument_ids
            or self.catalog_instrument_ids_without_daily_row
            or self.unknown_asset_type_catalog_instrument_ids
        )


def shfe_eod_url(trading_day: date) -> str:
    """Return the dated official SHFE/INE daily report URL."""

    if type(trading_day) is not date:
        raise ValueError("trading_day must be a date, not a datetime")
    return SHFE_EOD_URL_TEMPLATE.format(trading_day=trading_day.strftime("%Y%m%d"))


def parse_shfe_eod_json(
    raw_bytes: bytes,
    *,
    retrieved_at: datetime,
    expected_trading_day: Optional[date] = None,
) -> ShfeDailyReport:
    """Parse a captured official report without network or catalog access.

    The raw bytes are hashed before decoding. Rows whose product class is not
    the exchange's ordinary-futures class ``1`` are counted and excluded;
    summary rows without a contract delivery month are counted and excluded.
    """

    if type(raw_bytes) is not bytes:
        raise ShfeEodError("RAW_BODY_MUST_BE_BYTES")
    if not raw_bytes or len(raw_bytes) > SHFE_EOD_MAX_BYTES:
        raise ShfeEodError("BODY_SIZE_OUT_OF_RANGE")
    if not isinstance(retrieved_at, datetime) or retrieved_at.tzinfo is None:
        raise ShfeEodError("RETRIEVED_AT_MUST_BE_AWARE")
    if retrieved_at.utcoffset() is None:
        raise ShfeEodError("RETRIEVED_AT_MUST_BE_AWARE")
    if expected_trading_day is not None and type(expected_trading_day) is not date:
        raise ShfeEodError("EXPECTED_TRADING_DAY_MUST_BE_DATE")
    try:
        decoded = raw_bytes.decode("utf-8-sig", errors="strict")
        document = json.loads(
            decoded,
            object_pairs_hook=_json_object_no_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ShfeEodError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ShfeEodError("INVALID_JSON_BODY") from None
    if type(document) is not dict:
        raise ShfeEodError("INVALID_TOP_LEVEL_SHAPE")

    report_date = _parse_report_date(document.get("report_date"))
    if expected_trading_day is not None and report_date != expected_trading_day:
        raise ShfeEodError("REPORT_DATE_MISMATCH")
    reported_update_at = _parse_update_time(document.get("update_date"))
    retrieved_utc = retrieved_at.astimezone(timezone.utc)
    update_utc = reported_update_at.astimezone(timezone.utc)
    if update_utc > retrieved_utc:
        raise ShfeEodError("SOURCE_UPDATE_AFTER_RETRIEVAL")

    source_rows = document.get("o_curinstrument")
    if type(source_rows) is not list:
        raise ShfeEodError("INVALID_INSTRUMENT_ROWS")
    product_rows = document.get("o_curproduct")
    if type(product_rows) is not list or any(type(row) is not dict for row in product_rows):
        raise ShfeEodError("INVALID_PRODUCT_SUMMARY_ROWS")

    rows = []
    product_summary_count = 0
    overall_summary_count = 0
    nonordinary_counts = Counter()
    for row_index, source_row in enumerate(source_rows):
        if type(source_row) is not dict:
            raise ShfeEodError("INVALID_INSTRUMENT_ROW")
        for required_field in ("PRODUCTGROUPID", "DELIVERYMONTH", "PRODUCTCLASS"):
            if required_field not in source_row or type(source_row[required_field]) is not str:
                raise ShfeEodError("INVALID_" + required_field.lower())
        group_value = source_row["PRODUCTGROUPID"]
        month_value = source_row["DELIVERYMONTH"]
        product_class_value = source_row["PRODUCTCLASS"]
        source_product_value = source_row.get("PRODUCTID", "")
        group = _text(group_value, "product_group_id", allow_empty=True)
        month = _text(month_value, "delivery_month", allow_empty=True)
        product_class = _text(product_class_value, "product_class", allow_empty=True)
        source_product_id = _text(source_product_value, "source_product_id", allow_empty=True)

        if month == "":
            if group and product_class == "1":
                # The observed instrument table uses an empty month on its
                # per-product subtotal rows.
                product_summary_count += 1
                continue
            if not group and not product_class:
                # The observed overall total has empty group, class, and month.
                overall_summary_count += 1
                continue
            raise ShfeEodError("INVALID_SUMMARY_ROW")
        if not _is_source_month(month):
            raise ShfeEodError("INVALID_DELIVERY_MONTH")
        if not group:
            raise ShfeEodError("MISSING_PRODUCT_GROUP")
        if not product_class:
            raise ShfeEodError("INVALID_PRODUCT_CLASS")
        if product_class != "1":
            nonordinary_counts[product_class] += 1
            continue
        if not source_product_id:
            raise ShfeEodError("INVALID_SOURCE_PRODUCT_ID")

        volume = _nonnegative_int(source_row.get("VOLUME"), "volume")
        open_interest = _nonnegative_int(source_row.get("OPENINTEREST"), "open_interest")
        oi_change_value = source_row.get("OPENINTERESTCHG")
        oi_change = (
            None
            if oi_change_value is None or oi_change_value == ""
            else _signed_int(oi_change_value, "open_interest_change")
        )
        rows.append(
            ShfeDailyContractRow(
                product_group_id=group,
                source_product_id=source_product_id,
                product_class=product_class,
                delivery_month=month,
                volume=volume,
                open_interest=open_interest,
                open_interest_change=oi_change,
                source_row_index=row_index,
            )
        )

    digest = hashlib.sha256(raw_bytes).hexdigest()
    snapshot_id = "shfe-kx-{}-{}".format(report_date.strftime("%Y%m%d"), digest[:16])
    return ShfeDailyReport(
        source_id=SHFE_EOD_SOURCE_ID,
        snapshot_id=snapshot_id,
        source_sha256=digest,
        report_date=report_date,
        reported_update_at=reported_update_at,
        available_at=retrieved_at,
        retrieved_at=retrieved_at,
        rows=tuple(rows),
        source_row_count=len(source_rows),
        product_summary_row_count=product_summary_count,
        overall_summary_row_count=overall_summary_count,
        nonordinary_row_count=sum(nonordinary_counts.values()),
        nonordinary_class_counts=tuple(sorted(nonordinary_counts.items())),
        product_summary_table_count=len(product_rows),
    )


def _read_bounded_response(response: Any, max_bytes: int) -> bytes:
    headers = getattr(response, "headers", None)
    content_length = None if headers is None else headers.get("Content-Length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except (TypeError, ValueError):
            raise ShfeEodError("INVALID_CONTENT_LENGTH") from None
        if declared < 0:
            raise ShfeEodError("INVALID_CONTENT_LENGTH")
        if declared > max_bytes:
            raise ShfeEodError("RESPONSE_TOO_LARGE")

    chunks = []
    total = 0
    while total <= max_bytes:
        requested = min(64 * 1024, max_bytes + 1 - total)
        block = response.read(requested)
        if not block:
            break
        if type(block) is not bytes:
            raise ShfeEodError("INVALID_RESPONSE_CHUNK")
        chunks.append(block)
        total += len(block)
        if total > max_bytes:
            raise ShfeEodError("RESPONSE_TOO_LARGE")
    body = b"".join(chunks)
    if not body:
        raise ShfeEodError("EMPTY_RESPONSE")
    if content_length is not None and int(content_length) != len(body):
        raise ShfeEodError("CONTENT_LENGTH_MISMATCH")
    return body


def fetch_shfe_eod(
    trading_day: date,
    *,
    timeout_seconds: float = SHFE_EOD_TIMEOUT_SECONDS,
    max_bytes: int = SHFE_EOD_MAX_BYTES,
    opener: Optional[Callable[..., Any]] = None,
    clock: Optional[Callable[[], datetime]] = None,
) -> ShfeDailyReport:
    """Fetch one dated official report with bounded time and response size.

    This function is opt-in. It uses an unauthenticated public GET and has no
    retry or fallback provider. ``opener`` and ``clock`` exist for deterministic
    tests and caller-owned transport policy.
    """

    url = shfe_eod_url(trading_day)
    if type(timeout_seconds) not in (int, float) or isinstance(timeout_seconds, bool):
        raise ValueError("timeout_seconds must be a positive finite number")
    if timeout_seconds <= 0 or timeout_seconds > _MAX_TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds must be in (0, 60]")
    if type(max_bytes) is not int or max_bytes <= 0 or max_bytes > SHFE_EOD_MAX_BYTES:
        raise ValueError("max_bytes must be in [1, {}]".format(SHFE_EOD_MAX_BYTES))
    if not math.isfinite(float(timeout_seconds)):
        raise ValueError("timeout_seconds must be a positive finite number")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "Backtrader-SHFE-EOD-adapter/1.0",
        },
        method="GET",
    )
    open_url = _open_without_redirects if opener is None else opener
    try:
        response = open_url(request, timeout=float(timeout_seconds))
        with response:
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()
            if status != 200:
                raise ShfeEodError("HTTP_STATUS_NOT_OK")
            final_url = response.geturl() if hasattr(response, "geturl") else url
            if final_url != url:
                raise ShfeEodError("FINAL_URL_MISMATCH")
            raw_bytes = _read_bounded_response(response, max_bytes)
    except ShfeEodError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ShfeEodError("FETCH_FAILED") from None

    retrieved_at = datetime.now(timezone.utc) if clock is None else clock()
    return parse_shfe_eod_json(
        raw_bytes,
        retrieved_at=retrieved_at,
        expected_trading_day=trading_day,
    )


def join_shfe_report_to_catalog(
    report: ShfeDailyReport,
    catalog: Iterable[ShfeCatalogContract],
) -> ShfeCatalogJoinReport:
    """Match ordinary EOD rows to exact SHFE/INE catalog InstrumentIDs.

    The daily endpoint is a combined SHFE/INE source and has no CTP exchange
    or InstrumentID field. Matching therefore uses source product group,
    catalog ProductID, and the exact four-digit delivery month. Rows are
    returned only when precisely one in-scope catalog entry matches. This
    method does not claim the supplied catalog itself is complete.
    """

    entries = tuple(catalog)
    if any(not isinstance(entry, ShfeCatalogContract) for entry in entries):
        raise TypeError("catalog must contain ShfeCatalogContract entries")
    in_scope = tuple(
        entry for entry in entries if entry.exchange_id.upper() in SHFE_INE_EXCHANGE_IDS
    )
    outside_scope = tuple(
        entry.instrument_id
        for entry in entries
        if entry.exchange_id.upper() not in SHFE_INE_EXCHANGE_IDS
    )
    ignored_nonfutures = tuple(
        entry.instrument_id
        for entry in in_scope
        if entry.asset_type is not None and entry.asset_type.casefold() != "future"
    )
    unknown_asset_type = tuple(
        entry.instrument_id for entry in in_scope if entry.asset_type is None
    )
    futures = tuple(
        entry
        for entry in in_scope
        if entry.asset_type is not None and entry.asset_type.casefold() == "future"
    )

    duplicate_catalog_counts = Counter(entry.instrument_id for entry in futures)
    duplicate_catalog_ids = tuple(
        sorted(instrument_id for instrument_id, count in duplicate_catalog_counts.items() if count > 1)
    )
    source_key_counts = Counter(
        (row.product_group_id.casefold(), row.delivery_month) for row in report.rows
    )
    duplicate_source_keys = tuple(
        sorted(key for key, count in source_key_counts.items() if count > 1)
    )
    duplicate_source_key_set = set(duplicate_source_keys)

    matches = []
    unmatched = []
    ambiguous = []
    matched_catalog_ids = set()
    for row in report.rows:
        source_key = (row.product_group_id.casefold(), row.delivery_month)
        if source_key in duplicate_source_key_set:
            unmatched.append(row)
            continue
        candidates = tuple(
            entry
            for entry in futures
            if entry.product_id.casefold() == row.product_group_id.casefold()
            and entry.instrument_id.casefold()
            == (entry.product_id + row.delivery_month).casefold()
        )
        if not candidates:
            unmatched.append(row)
            continue
        if len(candidates) > 1:
            ambiguous.append(
                ShfeAmbiguousSourceMatch(
                    source_row=row,
                    candidate_instrument_ids=tuple(sorted(entry.instrument_id for entry in candidates)),
                )
            )
            continue
        entry = candidates[0]
        matched_catalog_ids.add(entry.instrument_id)
        matches.append(
            ShfeJoinedRankingRow(
                exchange_id=entry.exchange_id,
                product_id=entry.product_id,
                instrument_id=entry.instrument_id,
                asset_type=entry.asset_type,
                is_trading=entry.is_trading,
                expiry_date=entry.expiry_date,
                source_row=row,
            )
        )

    missing_catalog_ids = tuple(
        sorted(entry.instrument_id for entry in futures if entry.instrument_id not in matched_catalog_ids)
    )
    return ShfeCatalogJoinReport(
        matched_rows=tuple(matches),
        unmatched_source_rows=tuple(unmatched),
        ambiguous_source_matches=tuple(ambiguous),
        duplicate_source_keys=duplicate_source_keys,
        duplicate_catalog_instrument_ids=duplicate_catalog_ids,
        catalog_instrument_ids_without_daily_row=missing_catalog_ids,
        out_of_scope_catalog_instrument_ids=tuple(sorted(outside_scope)),
        ignored_nonfuture_catalog_instrument_ids=tuple(sorted(ignored_nonfutures)),
        unknown_asset_type_catalog_instrument_ids=tuple(sorted(unknown_asset_type)),
    )
