"""Bounded parser and explicit catalog join for CFFEX daily quote CSV.

The exchange's dated ``fzjy/mrhq`` file includes futures and options. This
adapter keeps ordinary futures rows and preserves their source contract IDs;
callers still join them to an independently observed CTP instrument catalog.
The CSV has no report-date field, so ``trading_day`` is the exact date used in
the exchange URL, not an inferred publication timestamp.

``available_at`` is the local time at which this process finished retrieving
the entire response. The adapter does not claim the exchange's first
publication time or backdate historical downloads.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Optional, Tuple


CFFEX_EOD_SOURCE_ID = "cffex-public-daily-quote-csv-v1"
CFFEX_EOD_URL_TEMPLATE = "http://www.cffex.com.cn/fzjy/mrhq/{year_month}/{day}/{trading_day}_1.csv"
CFFEX_EOD_MAX_BYTES = 2 * 1024 * 1024
CFFEX_EOD_TIMEOUT_SECONDS = 10.0
_MAX_TIMEOUT_SECONDS = 60.0
_HEADER = (
    "合约代码",
    "今开盘",
    "最高价",
    "最低价",
    "成交量",
    "成交金额",
    "持仓量",
    "持仓变化",
    "今收盘",
    "今结算",
    "前结算",
    "涨跌1",
    "涨跌2",
    "Delta",
)
_FUTURES_ID_RE = re.compile(r"^([A-Z]{1,3})([0-9]{4})$")
_OPTION_ID_RE = re.compile(r"^[A-Z]{1,3}[0-9]{4}-[CP]-[0-9]+(?:\.[0-9]+)?$")
_UNSIGNED_INTEGER_RE = re.compile(r"^[0-9]+$")
_SIGNED_INTEGER_RE = re.compile(r"^[+-]?[0-9]+$")
_SUMMARY_LABELS = ("小计", "合计")


class CffexEodError(ValueError):
    """Stable parser/fetch error code without payload contents."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects before urllib creates or sends the redirected request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CffexEodError("REDIRECT_REJECTED")


def _open_without_redirects(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(_RejectRedirectHandler())
    return opener.open(request, timeout=timeout)


def _trading_day(value: Any) -> date:
    if type(value) is not date:
        raise ValueError("trading_day must be a date, not a datetime")
    try:
        date(value.year, value.month, value.day)
    except ValueError:
        raise ValueError("trading_day must be a valid date") from None
    return value


def cffex_eod_url(trading_day: date) -> str:
    """Return the dated public CFFEX daily quote URL."""

    day = _trading_day(trading_day)
    stamp = day.strftime("%Y%m%d")
    return CFFEX_EOD_URL_TEMPLATE.format(
        year_month=day.strftime("%Y%m"), day=day.strftime("%d"), trading_day=stamp
    )


def _aware_datetime(value: Any, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("{} must be timezone-aware".format(field))
    return value


def _integer(value: str, field: str, *, signed: bool = False) -> int:
    pattern = _SIGNED_INTEGER_RE if signed else _UNSIGNED_INTEGER_RE
    if type(value) is not str or not pattern.fullmatch(value):
        raise CffexEodError("INVALID_" + field.upper())
    return int(value)


@dataclass(frozen=True)
class CffexDailyContractRow:
    """One ordinary futures row, prior to matching a CTP catalog."""

    instrument_id: str
    product_id: str
    volume: int
    open_interest: int
    open_interest_change: int
    source_row_index: int


@dataclass(frozen=True)
class CffexDailySummaryRow:
    """One explicitly recognized total row, never a ranking candidate."""

    label: str
    volume: Optional[int]
    open_interest: Optional[int]
    open_interest_change: Optional[int]
    source_row_index: int


@dataclass(frozen=True)
class CffexDailyReport:
    """Immutable parsed CSV and finite source-row counts."""

    source_id: str
    snapshot_id: str
    source_sha256: str
    trading_day: date
    available_at: datetime
    retrieved_at: datetime
    rows: Tuple[CffexDailyContractRow, ...]
    source_row_count: int
    futures_row_count: int
    option_row_count: int
    summary_rows: Tuple[CffexDailySummaryRow, ...]
    summary_label_counts: Tuple[Tuple[str, int], ...]
    http_last_modified_at: Optional[datetime]
    volume_unit: str = "contracts_single_sided"
    open_interest_unit: str = "contracts_single_sided"


@dataclass(frozen=True)
class CffexCatalogContract:
    """Relevant fields copied from one actual CTP catalog entry."""

    exchange_id: str
    product_id: str
    instrument_id: str
    asset_type: Optional[str]
    is_trading: Optional[bool]
    expiry_date: Optional[date]


@dataclass(frozen=True)
class CffexJoinedRankingRow:
    """A source row joined to the exact provider catalog identifier."""

    exchange_id: str
    product_id: str
    instrument_id: str
    asset_type: Optional[str]
    is_trading: Optional[bool]
    expiry_date: Optional[date]
    source_row: CffexDailyContractRow


@dataclass(frozen=True)
class CffexCatalogJoinReport:
    """Join outcome; empty gaps are evidence, not a completeness assertion."""

    matched_rows: Tuple[CffexJoinedRankingRow, ...]
    unmatched_source_rows: Tuple[CffexDailyContractRow, ...]
    ambiguous_source_matches: Tuple[Tuple[CffexDailyContractRow, Tuple[str, ...]], ...]
    duplicate_source_instrument_ids: Tuple[str, ...]
    duplicate_catalog_instrument_ids: Tuple[str, ...]
    catalog_instrument_ids_without_daily_row: Tuple[str, ...]
    out_of_scope_catalog_instrument_ids: Tuple[str, ...]
    ignored_nonfuture_catalog_instrument_ids: Tuple[str, ...]
    unknown_asset_type_catalog_instrument_ids: Tuple[str, ...]

    @property
    def one_to_one(self) -> bool:
        return not any(
            (
                self.unmatched_source_rows,
                self.ambiguous_source_matches,
                self.duplicate_source_instrument_ids,
                self.duplicate_catalog_instrument_ids,
                self.catalog_instrument_ids_without_daily_row,
                self.unknown_asset_type_catalog_instrument_ids,
            )
        )


def parse_cffex_eod_csv(
    raw_bytes: bytes,
    *,
    trading_day: date,
    retrieved_at: datetime,
    http_last_modified: Optional[str] = None,
    max_bytes: int = CFFEX_EOD_MAX_BYTES,
) -> CffexDailyReport:
    """Parse the observed CFFEX 14-column CP936 daily CSV structure."""

    day = _trading_day(trading_day)
    retrieved = _aware_datetime(retrieved_at, "retrieved_at")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive int")
    if type(raw_bytes) is not bytes:
        raise TypeError("raw_bytes must be bytes")
    if len(raw_bytes) > max_bytes:
        raise CffexEodError("BODY_SIZE_OUT_OF_RANGE")
    if not raw_bytes:
        raise CffexEodError("EMPTY_BODY")

    try:
        text = raw_bytes.decode("gb18030")
    except UnicodeDecodeError:
        raise CffexEodError("INVALID_TEXT_ENCODING") from None
    try:
        csv_rows = tuple(csv.reader(io.StringIO(text, newline="")))
    except csv.Error:
        raise CffexEodError("INVALID_CSV") from None
    if not csv_rows or tuple(csv_rows[0]) != _HEADER:
        raise CffexEodError("UNEXPECTED_HEADER")

    futures_rows = []
    summary_rows = []
    option_count = 0
    source_row_count = 0
    for source_row_index, row in enumerate(csv_rows[1:], start=2):
        if not row or all(not field for field in row):
            continue
        source_row_count += 1
        if len(row) != len(_HEADER):
            raise CffexEodError("INVALID_ROW_WIDTH")
        instrument_id = row[0]
        if not instrument_id or instrument_id != instrument_id.strip():
            raise CffexEodError("INVALID_INSTRUMENT_ID")

        if instrument_id in _SUMMARY_LABELS:
            summary_rows.append(
                CffexDailySummaryRow(
                    label=instrument_id,
                    volume=(None if row[4] == "" else _integer(row[4], "summary_volume")),
                    open_interest=(
                        None if row[6] == "" else _integer(row[6], "summary_open_interest")
                    ),
                    open_interest_change=(
                        None
                        if row[7] == ""
                        else _integer(row[7], "summary_open_interest_change", signed=True)
                    ),
                    source_row_index=source_row_index,
                )
            )
            continue

        match = _FUTURES_ID_RE.fullmatch(instrument_id)
        if match is None:
            if _OPTION_ID_RE.fullmatch(instrument_id) is None:
                raise CffexEodError("UNKNOWN_CONTRACT_ID_SHAPE")
            option_count += 1
            continue
        if not 1 <= int(match.group(2)[-2:]) <= 12:
            raise CffexEodError("INVALID_DELIVERY_MONTH")
        futures_rows.append(
            CffexDailyContractRow(
                instrument_id=instrument_id,
                product_id=match.group(1),
                volume=_integer(row[4], "volume"),
                open_interest=_integer(row[6], "open_interest"),
                open_interest_change=_integer(row[7], "open_interest_change", signed=True),
                source_row_index=source_row_index,
            )
        )
    if not source_row_count:
        raise CffexEodError("NO_DATA_ROWS")

    last_modified_at = None
    if http_last_modified is not None:
        if type(http_last_modified) is not str or not http_last_modified.strip():
            raise CffexEodError("INVALID_LAST_MODIFIED")
        try:
            parsed = parsedate_to_datetime(http_last_modified)
        except (TypeError, ValueError, OverflowError):
            raise CffexEodError("INVALID_LAST_MODIFIED") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise CffexEodError("INVALID_LAST_MODIFIED")
        if parsed.astimezone(timezone.utc) > retrieved.astimezone(timezone.utc):
            raise CffexEodError("LAST_MODIFIED_AFTER_RETRIEVAL")
        last_modified_at = parsed

    digest = hashlib.sha256(raw_bytes).hexdigest()
    day_text = day.strftime("%Y%m%d")
    summary_counts = Counter(row.label for row in summary_rows)
    return CffexDailyReport(
        source_id=CFFEX_EOD_SOURCE_ID,
        snapshot_id="{}:{}".format(day_text, digest[:16]),
        source_sha256=digest,
        trading_day=day,
        available_at=retrieved,
        retrieved_at=retrieved,
        rows=tuple(futures_rows),
        source_row_count=source_row_count,
        futures_row_count=len(futures_rows),
        option_row_count=option_count,
        summary_rows=tuple(summary_rows),
        summary_label_counts=tuple(
            (label, summary_counts[label]) for label in _SUMMARY_LABELS if summary_counts[label]
        ),
        http_last_modified_at=last_modified_at,
    )


def _read_bounded(response: Any, max_bytes: int) -> bytes:
    headers = getattr(response, "headers", None)
    if headers is not None:
        content_length = headers.get("Content-Length")
        if content_length is not None:
            try:
                announced = int(content_length)
            except (TypeError, ValueError):
                raise CffexEodError("INVALID_CONTENT_LENGTH") from None
            if announced < 0:
                raise CffexEodError("INVALID_CONTENT_LENGTH")
            if announced > max_bytes:
                raise CffexEodError("RESPONSE_TOO_LARGE")
    chunks = []
    total = 0
    while total <= max_bytes:
        chunk = response.read(min(65536, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise CffexEodError("RESPONSE_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_cffex_eod(
    trading_day: date,
    *,
    timeout_seconds: float = CFFEX_EOD_TIMEOUT_SECONDS,
    max_bytes: int = CFFEX_EOD_MAX_BYTES,
    opener: Optional[Callable[..., Any]] = None,
    clock: Optional[Callable[[], datetime]] = None,
) -> CffexDailyReport:
    """Fetch one explicit CFFEX daily file; importing this module is offline."""

    day = _trading_day(trading_day)
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > _MAX_TIMEOUT_SECONDS
    ):
        raise ValueError("timeout_seconds must be finite and in (0, 60]")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive int")

    url = cffex_eod_url(day)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
            "User-Agent": "backtrader-futures-eod/1",
        },
        method="GET",
    )
    try:
        response = (
            _open_without_redirects(request, float(timeout_seconds))
            if opener is None
            else opener(request, float(timeout_seconds))
        )
        with response:
            if response.geturl() != url:
                raise CffexEodError("FINAL_URL_MISMATCH")
            raw_bytes = _read_bounded(response, max_bytes)
            last_modified = response.headers.get("Last-Modified")
    except CffexEodError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CffexEodError("FETCH_FAILED") from None

    retrieved_at = datetime.now(timezone.utc) if clock is None else clock()
    return parse_cffex_eod_csv(
        raw_bytes,
        trading_day=day,
        retrieved_at=retrieved_at,
        http_last_modified=last_modified,
        max_bytes=max_bytes,
    )


def join_cffex_report_to_catalog(
    report: CffexDailyReport,
    catalog: Iterable[CffexCatalogContract],
) -> CffexCatalogJoinReport:
    """Match rows to exact CTP IDs and expose every reconciliation gap.

    This join does not claim that the passed CTP catalog is complete. A caller
    constructs selector coverage only after comparing all exact catalog IDs
    with the daily source rows and preserving the gaps below.
    """

    if not isinstance(report, CffexDailyReport):
        raise TypeError("report must be CffexDailyReport")
    entries = tuple(catalog)
    if any(not isinstance(entry, CffexCatalogContract) for entry in entries):
        raise TypeError("catalog must contain CffexCatalogContract entries")
    in_scope = tuple(entry for entry in entries if entry.exchange_id.upper() == "CFFEX")
    outside_scope = tuple(
        entry.instrument_id for entry in entries if entry.exchange_id.upper() != "CFFEX"
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

    source_counts = Counter(row.instrument_id for row in report.rows)
    duplicate_source_ids = tuple(sorted(key for key, count in source_counts.items() if count > 1))
    duplicate_source_set = set(duplicate_source_ids)
    catalog_counts = Counter(entry.instrument_id for entry in futures)
    duplicate_catalog_ids = tuple(sorted(key for key, count in catalog_counts.items() if count > 1))
    duplicate_catalog_set = set(duplicate_catalog_ids)

    matched = []
    unmatched = []
    ambiguous = []
    matched_ids = set()
    for row in report.rows:
        if row.instrument_id in duplicate_source_set:
            unmatched.append(row)
            continue
        candidates = tuple(
            entry
            for entry in futures
            if entry.instrument_id == row.instrument_id
            and entry.product_id.upper() == row.product_id
        )
        if not candidates:
            unmatched.append(row)
            continue
        if len(candidates) > 1 or row.instrument_id in duplicate_catalog_set:
            ambiguous.append((row, tuple(sorted(entry.instrument_id for entry in candidates))))
            continue
        entry = candidates[0]
        matched_ids.add(entry.instrument_id)
        matched.append(
            CffexJoinedRankingRow(
                exchange_id=entry.exchange_id,
                product_id=entry.product_id,
                instrument_id=entry.instrument_id,
                asset_type=entry.asset_type,
                is_trading=entry.is_trading,
                expiry_date=entry.expiry_date,
                source_row=row,
            )
        )

    missing = tuple(
        sorted(entry.instrument_id for entry in futures if entry.instrument_id not in matched_ids)
    )
    return CffexCatalogJoinReport(
        matched_rows=tuple(matched),
        unmatched_source_rows=tuple(unmatched),
        ambiguous_source_matches=tuple(ambiguous),
        duplicate_source_instrument_ids=duplicate_source_ids,
        duplicate_catalog_instrument_ids=duplicate_catalog_ids,
        catalog_instrument_ids_without_daily_row=missing,
        out_of_scope_catalog_instrument_ids=tuple(sorted(outside_scope)),
        ignored_nonfuture_catalog_instrument_ids=tuple(sorted(ignored_nonfutures)),
        unknown_asset_type_catalog_instrument_ids=tuple(sorted(unknown_asset_type)),
    )
