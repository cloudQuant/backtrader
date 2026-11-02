"""Focused tests for the bounded official CFFEX daily CSV source."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.request import Request

import pytest

from backtrader.feeds.futures_eod_cffex import (
    CFFEX_EOD_MAX_BYTES,
    CffexCatalogContract,
    CffexEodError,
    _open_without_redirects,
    cffex_eod_url,
    fetch_cffex_eod,
    join_cffex_report_to_catalog,
    parse_cffex_eod_csv,
)


TRADING_DAY = date(2026, 10, 23)
RETRIEVED_AT = datetime(2026, 10, 24, 2, 37, 59, tzinfo=timezone.utc)
LAST_MODIFIED = "Fri, 23 Oct 2026 08:03:01 GMT"
HEADER = (
    "合约代码,今开盘,最高价,最低价,成交量,成交金额,持仓量,持仓变化,"
    "今收盘,今结算,前结算,涨跌1,涨跌2,Delta\n"
)
ACTUAL_SAMPLE_ROWS = (
    "HO2611-C-2450,226.6,288.8,223.4,21,53.642,12,1,288.8,288.2,257.2,31.6,31,0.9370\n"
    "IC2611,6540,6811.4,6388,55053,7237216.7,61020,2863,6782,6762.4,6667.4,114.6,95,--\n"
    "IF2611,3962,4090,3926.6,41226,4954597.146,53577,353,4080.2,4072.2,4014.8,65.4,57.4,--\n"
)
ACTUAL_SUMMARY_ROW = "小计,,,,53522,25675.906,84171,591,,,,,,--\n"


def _payload(rows=None):
    body = ACTUAL_SAMPLE_ROWS + ACTUAL_SUMMARY_ROW if rows is None else rows
    return (HEADER + body).encode("gb18030")


def _parse(raw=None, *, retrieved_at=RETRIEVED_AT, last_modified=LAST_MODIFIED):
    return parse_cffex_eod_csv(
        _payload() if raw is None else raw,
        trading_day=TRADING_DAY,
        retrieved_at=retrieved_at,
        http_last_modified=last_modified,
    )


def _catalog(
    instrument_id,
    product_id,
    *,
    exchange_id="CFFEX",
    asset_type="future",
    is_trading=True,
    expiry_date=date(2026, 11, 20),
):
    return CffexCatalogContract(
        exchange_id=exchange_id,
        product_id=product_id,
        instrument_id=instrument_id,
        asset_type=asset_type,
        is_trading=is_trading,
        expiry_date=expiry_date,
    )


def test_official_url_uses_the_dated_contract_report_path():
    assert cffex_eod_url(TRADING_DAY) == (
        "http://www.cffex.com.cn/fzjy/mrhq/202610/23/20261023_1.csv"
    )
    with pytest.raises(ValueError, match="date, not a datetime"):
        cffex_eod_url(datetime(2026, 10, 23))


def test_parser_preserves_actual_ids_and_observed_availability():
    raw = _payload()
    report = _parse(raw)

    assert report.trading_day == TRADING_DAY
    assert report.available_at == RETRIEVED_AT
    assert report.retrieved_at == RETRIEVED_AT
    assert report.http_last_modified_at == datetime(2026, 10, 23, 8, 3, 1, tzinfo=timezone.utc)
    assert report.available_at > report.http_last_modified_at
    assert report.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert report.snapshot_id == "20261023:" + report.source_sha256[:16]
    assert report.source_row_count == 4
    assert report.futures_row_count == 2
    assert report.option_row_count == 1
    assert report.summary_label_counts == (("小计", 1),)
    assert report.summary_rows[0].volume == 53522
    assert report.summary_rows[0].open_interest == 84171
    assert [(row.instrument_id, row.product_id) for row in report.rows] == [
        ("IC2611", "IC"),
        ("IF2611", "IF"),
    ]
    assert (report.rows[0].volume, report.rows[0].open_interest) == (55053, 61020)
    assert report.rows[0].open_interest_change == 2863
    assert report.volume_unit == "contracts_single_sided"
    assert report.open_interest_unit == "contracts_single_sided"


def test_parser_rejects_unrecognized_headers_rows_ids_and_numbers():
    cases = [
        (_payload().replace("今开盘".encode("gb18030"), b"bad", 1), "UNEXPECTED_HEADER"),
        (_payload("IC2611,1,2\n"), "INVALID_ROW_WIDTH"),
        (_payload(ACTUAL_SAMPLE_ROWS.replace("IC2611", "IC8888", 1)), "INVALID_DELIVERY_MONTH"),
        (_payload(ACTUAL_SAMPLE_ROWS.replace("IC2611", "IC26X1", 1)), "UNKNOWN_CONTRACT_ID_SHAPE"),
        (_payload(ACTUAL_SAMPLE_ROWS.replace(",55053,", ",true,", 1)), "INVALID_VOLUME"),
        (_payload(ACTUAL_SAMPLE_ROWS.replace(",61020,", ",-1,", 1)), "INVALID_OPEN_INTEREST"),
        (_payload(ACTUAL_SAMPLE_ROWS.replace(",2863,", ",+x,", 1)), "INVALID_OPEN_INTEREST_CHANGE"),
        (
            _payload(ACTUAL_SAMPLE_ROWS.replace("HO2611-C-2450", "UNKNOWN", 1)),
            "UNKNOWN_CONTRACT_ID_SHAPE",
        ),
    ]
    for raw, code in cases:
        with pytest.raises(CffexEodError) as caught:
            _parse(raw)
        assert caught.value.code == code


def test_parser_rejects_naive_time_and_oversized_body():
    with pytest.raises(ValueError, match="timezone-aware"):
        _parse(retrieved_at=datetime(2026, 10, 24, 2, 37, 59))
    with pytest.raises(CffexEodError) as caught:
        parse_cffex_eod_csv(
            b" " * (CFFEX_EOD_MAX_BYTES + 1),
            trading_day=TRADING_DAY,
            retrieved_at=RETRIEVED_AT,
        )
    assert caught.value.code == "BODY_SIZE_OUT_OF_RANGE"


def test_parser_rejects_last_modified_after_observed_retrieval():
    with pytest.raises(CffexEodError) as caught:
        _parse(last_modified="Sat, 24 Oct 2026 02:38:00 GMT")
    assert caught.value.code == "LAST_MODIFIED_AFTER_RETRIEVAL"


def test_join_uses_exact_catalog_ids_and_exposes_reconciliation_gaps():
    report = _parse()
    joined = join_cffex_report_to_catalog(
        report,
        [
            _catalog("IC2611", "IC"),
            _catalog("IF2611", "IF", is_trading=False),
            _catalog("IC2703", "IC"),
            _catalog("HO2611-C-2450", "HO", asset_type="option"),
            _catalog("TL2612", "TL", asset_type=None),
            _catalog("cu2611", "cu", exchange_id="SHFE"),
        ],
    )

    assert [row.instrument_id for row in joined.matched_rows] == ["IC2611", "IF2611"]
    assert joined.matched_rows[0].source_row.instrument_id == "IC2611"
    assert joined.matched_rows[1].is_trading is False
    assert joined.unmatched_source_rows == ()
    assert joined.catalog_instrument_ids_without_daily_row == ("IC2703",)
    assert joined.ignored_nonfuture_catalog_instrument_ids == ("HO2611-C-2450",)
    assert joined.unknown_asset_type_catalog_instrument_ids == ("TL2612",)
    assert joined.out_of_scope_catalog_instrument_ids == ("cu2611",)
    assert not joined.one_to_one


def test_join_reports_mismatched_duplicate_and_ambiguous_ids():
    report = _parse()
    joined = join_cffex_report_to_catalog(
        report,
        [
            _catalog("ic2611", "IC"),
            _catalog("IF2611", "IF"),
            _catalog("IF2611", "IF"),
        ],
    )
    assert joined.duplicate_catalog_instrument_ids == ("IF2611",)
    assert joined.unmatched_source_rows == (report.rows[0],)
    assert len(joined.ambiguous_source_matches) == 1
    assert joined.ambiguous_source_matches[0][0] == report.rows[1]
    assert joined.ambiguous_source_matches[0][1] == ("IF2611", "IF2611")
    assert joined.catalog_instrument_ids_without_daily_row == (
        "IF2611",
        "IF2611",
        "ic2611",
    )

    duplicate_source = _parse(
        _payload(ACTUAL_SAMPLE_ROWS + ACTUAL_SAMPLE_ROWS.splitlines(keepends=True)[1])
    )
    duplicate_join = join_cffex_report_to_catalog(
        duplicate_source,
        [_catalog("IC2611", "IC"), _catalog("IF2611", "IF")],
    )
    assert duplicate_join.duplicate_source_instrument_ids == ("IC2611",)
    assert all(row.instrument_id != "IC2611" for row in duplicate_join.matched_rows)


class _FakeResponse:
    def __init__(self, body, url, *, headers=None):
        self.body = body
        self.url = url
        self.headers = headers or {"Content-Length": str(len(body)), "Last-Modified": LAST_MODIFIED}
        self.offset = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.closed = True

    def geturl(self):
        return self.url

    def read(self, count):
        block = self.body[self.offset : self.offset + count]
        self.offset += len(block)
        return block


def test_fetch_is_opt_in_bounded_and_stamps_observed_retrieval():
    body = _payload()
    response = _FakeResponse(body, cffex_eod_url(TRADING_DAY))
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return response

    report = fetch_cffex_eod(
        TRADING_DAY,
        timeout_seconds=3.0,
        max_bytes=4096,
        opener=opener,
        clock=lambda: RETRIEVED_AT,
    )
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == cffex_eod_url(TRADING_DAY)
    assert request.get_method() == "GET"
    assert request.get_header("Accept").startswith("text/csv")
    assert timeout == 3.0
    assert response.closed
    assert report.available_at == RETRIEVED_AT
    assert report.retrieved_at == RETRIEVED_AT


def test_fetch_rejects_oversize_invalid_timeout_and_unexpected_final_url():
    response = _FakeResponse(_payload(), cffex_eod_url(TRADING_DAY))
    with pytest.raises(CffexEodError) as too_large:
        fetch_cffex_eod(
            TRADING_DAY,
            max_bytes=8,
            opener=lambda *_args: response,
            clock=lambda: RETRIEVED_AT,
        )
    assert too_large.value.code == "RESPONSE_TOO_LARGE"

    with pytest.raises(ValueError, match="timeout_seconds"):
        fetch_cffex_eod(
            TRADING_DAY,
            timeout_seconds=float("inf"),
            opener=lambda *_args: None,
        )

    wrong_url = _FakeResponse(_payload(), "https://example.invalid/redirected.csv")
    with pytest.raises(CffexEodError) as final_url:
        fetch_cffex_eod(
            TRADING_DAY,
            opener=lambda *_args: wrong_url,
            clock=lambda: RETRIEVED_AT,
        )
    assert final_url.value.code == "FINAL_URL_MISMATCH"


def test_real_urllib_redirect_handler_blocks_before_second_request():
    state = {"redirected_request_count": 0}

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()
                return
            state["redirected_request_count"] += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"should not be requested")

        def log_message(self, _format, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = "http://127.0.0.1:{}/start".format(server.server_port)
        with pytest.raises(CffexEodError) as caught:
            _open_without_redirects(Request(url), timeout=2.0)
        assert caught.value.code == "REDIRECT_REJECTED"
        assert state["redirected_request_count"] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
