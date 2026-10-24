"""Focused tests for the bounded SHFE/INE daily ranking source adapter."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.request import Request

import pytest

from backtrader.feeds.futures_eod_shfe import (
    SHFE_EOD_MAX_BYTES,
    ShfeCatalogContract,
    ShfeEodError,
    _open_without_redirects,
    fetch_shfe_eod,
    join_shfe_report_to_catalog,
    parse_shfe_eod_json,
    shfe_eod_url,
)


REPORT_DAY = date(2026, 10, 21)
RETRIEVED_AT = datetime(2026, 10, 21, 7, 26, 4, tzinfo=timezone.utc)


def _contract_row(
    product_group="cu",
    delivery_month="2611",
    *,
    product_id="cu_f",
    product_class="1",
    volume=66085,
    open_interest=147002,
    open_interest_change=-14051,
):
    return {
        "PRODUCTGROUPID": product_group,
        "PRODUCTID": product_id,
        "PRODUCTCLASS": product_class,
        "DELIVERYMONTH": delivery_month,
        "VOLUME": volume,
        "OPENINTEREST": open_interest,
        "OPENINTERESTCHG": open_interest_change,
    }


def _subtotal_row(product_group="cu"):
    return {
        "PRODUCTGROUPID": product_group,
        "PRODUCTID": product_group + "_f",
        "PRODUCTCLASS": "1",
        "DELIVERYMONTH": "",
        "VOLUME": 123,
        "OPENINTEREST": 456,
        "OPENINTERESTCHG": 7,
    }


def _payload(rows=None, product_rows=None):
    document = {
        "report_date": "20261021",
        "update_date": "20261021 15:26:03",
        "o_curinstrument": rows
        if rows is not None
        else [
            _contract_row(),
            _contract_row(delivery_month="2701", volume=100, open_interest=200),
            _subtotal_row(),
            _contract_row(
                delivery_month="2611",
                product_class="6",
                volume="",
                open_interest="",
                open_interest_change="",
            ),
            {
                "PRODUCTGROUPID": "",
                "PRODUCTID": "",
                "PRODUCTCLASS": "",
                "DELIVERYMONTH": "",
            },
        ],
        "o_curproduct": product_rows if product_rows is not None else [{"PRODUCTGROUPID": "cu"}],
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def _parse(raw=None, retrieved_at=RETRIEVED_AT):
    return parse_shfe_eod_json(
        _payload() if raw is None else raw,
        retrieved_at=retrieved_at,
        expected_trading_day=REPORT_DAY,
    )


def _catalog(
    instrument_id,
    *,
    exchange_id="SHFE",
    product_id="cu",
    asset_type="future",
    is_trading=True,
    expiry_date=date(2026, 11, 16),
):
    return ShfeCatalogContract(
        exchange_id=exchange_id,
        product_id=product_id,
        instrument_id=instrument_id,
        asset_type=asset_type,
        is_trading=is_trading,
        expiry_date=expiry_date,
    )


def test_official_url_uses_the_dated_kx_path_without_cache_parameters():
    assert shfe_eod_url(REPORT_DAY) == (
        "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20261021.dat"
    )
    with pytest.raises(ValueError, match="date, not a datetime"):
        shfe_eod_url(datetime(2026, 10, 21))


def test_parser_keeps_only_ordinary_contract_rows_and_counts_report_totals():
    raw = _payload()
    report = _parse(raw)

    assert report.report_date == REPORT_DAY
    assert report.reported_update_at.isoformat() == "2026-10-21T15:26:03+08:00"
    assert report.available_at == RETRIEVED_AT
    assert report.retrieved_at == RETRIEVED_AT
    assert report.available_at >= report.reported_update_at
    assert report.source_sha256 == sha256(raw).hexdigest()
    assert report.snapshot_id.endswith(report.source_sha256[:16])
    assert report.source_row_count == 5
    assert report.product_summary_row_count == 1
    assert report.overall_summary_row_count == 1
    assert report.nonordinary_row_count == 1
    assert report.nonordinary_class_counts == (("6", 1),)
    assert report.product_summary_table_count == 1
    assert [(row.product_group_id, row.delivery_month) for row in report.rows] == [
        ("cu", "2611"),
        ("cu", "2701"),
    ]
    assert (report.rows[0].open_interest, report.rows[0].volume) == (147002, 66085)
    assert report.rows[0].open_interest_change == -14051
    assert report.open_interest_unit == "contracts_single_sided"
    assert report.volume_unit == "contracts_single_sided"


def test_parser_rejects_report_date_and_future_source_update():
    with pytest.raises(ShfeEodError) as mismatch:
        parse_shfe_eod_json(
            _payload().replace(b"20261021", b"20261020", 1),
            retrieved_at=RETRIEVED_AT,
            expected_trading_day=REPORT_DAY,
        )
    assert mismatch.value.code == "REPORT_DATE_MISMATCH"

    with pytest.raises(ShfeEodError) as early:
        _parse(retrieved_at=datetime(2026, 10, 21, 7, 26, 2, tzinfo=timezone.utc))
    assert early.value.code == "SOURCE_UPDATE_AFTER_RETRIEVAL"


@pytest.mark.parametrize(
    "raw,expected_code",
    [
        (b"not json", "INVALID_JSON_BODY"),
        (b'{"report_date":"20261021","report_date":"20261021"}', "DUPLICATE_JSON_KEY"),
        (_payload().replace(b'"VOLUME":66085', b'"VOLUME":true'), "INVALID_VOLUME"),
        (_payload().replace(b'"DELIVERYMONTH":"2611"', b'"DELIVERYMONTH":"2613"'), "INVALID_DELIVERY_MONTH"),
        (_payload().replace(b'"DELIVERYMONTH":"2611"', b'"DELIVERYMONTH":"26X1"'), "INVALID_DELIVERY_MONTH"),
        (_payload().replace(b'"DELIVERYMONTH":"2611"', b'"DELIVERYMONTH":"2026-11"'), "INVALID_DELIVERY_MONTH"),
    ],
)
def test_parser_rejects_malformed_payloads(raw, expected_code):
    with pytest.raises(ShfeEodError) as caught:
        _parse(raw)
    assert caught.value.code == expected_code


def test_parser_rejects_oversized_body_before_json_decode():
    with pytest.raises(ShfeEodError) as caught:
        parse_shfe_eod_json(
            b" " * (SHFE_EOD_MAX_BYTES + 1),
            retrieved_at=RETRIEVED_AT,
        )
    assert caught.value.code == "BODY_SIZE_OUT_OF_RANGE"


def test_join_preserves_exact_catalog_ids_and_reports_missing_scope_rows():
    report = _parse()
    result = join_shfe_report_to_catalog(
        report,
        [
            _catalog("Cu2611", product_id="CU"),
            _catalog("cu2701", is_trading=False),
            _catalog("cu2711"),
            _catalog("cu2611", exchange_id="DCE"),
            _catalog("cu2611C80000", asset_type="option"),
            _catalog("cu2609", asset_type=None),
        ],
    )

    assert [row.instrument_id for row in result.matched_rows] == ["Cu2611", "cu2701"]
    assert result.matched_rows[0].product_id == "CU"
    assert result.matched_rows[0].source_row.source_product_id == "cu_f"
    assert result.matched_rows[1].is_trading is False
    assert result.unmatched_source_rows == ()
    assert result.catalog_instrument_ids_without_daily_row == ("cu2711",)
    assert result.out_of_scope_catalog_instrument_ids == ("cu2611",)
    assert result.ignored_nonfuture_catalog_instrument_ids == ("cu2611C80000",)
    assert result.unknown_asset_type_catalog_instrument_ids == ("cu2609",)
    assert not result.one_to_one


def test_join_exposes_missing_and_ambiguous_catalog_matches():
    report = _parse()
    ambiguous = join_shfe_report_to_catalog(
        report,
        [
            _catalog("cu2611", exchange_id="SHFE"),
            _catalog("cu2611", exchange_id="INE"),
        ],
    )
    assert len(ambiguous.ambiguous_source_matches) == 1
    assert ambiguous.ambiguous_source_matches[0].candidate_instrument_ids == (
        "cu2611",
        "cu2611",
    )
    assert ambiguous.catalog_instrument_ids_without_daily_row == ("cu2611", "cu2611")

    missing = join_shfe_report_to_catalog(report, [_catalog("ag2611", product_id="ag")])
    assert len(missing.unmatched_source_rows) == 2
    assert missing.catalog_instrument_ids_without_daily_row == ("ag2611",)


def test_join_does_not_choose_between_duplicate_source_rows_or_catalog_ids():
    duplicated_source = _parse(_payload(rows=[_contract_row(), _contract_row()]))
    source_result = join_shfe_report_to_catalog(duplicated_source, [_catalog("cu2611")])
    assert source_result.duplicate_source_keys == (("cu", "2611"),)
    assert source_result.matched_rows == ()
    assert len(source_result.unmatched_source_rows) == 2

    duplicate_catalog = join_shfe_report_to_catalog(
        _parse(), [_catalog("cu2611"), _catalog("cu2611")]
    )
    assert duplicate_catalog.duplicate_catalog_instrument_ids == ("cu2611",)
    assert len(duplicate_catalog.ambiguous_source_matches) == 1


class _FakeResponse:
    def __init__(self, body, url, *, status=200, headers=None):
        self.body = body
        self.url = url
        self.status = status
        self.headers = headers or {"Content-Length": str(len(body))}
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


def test_fetch_is_opt_in_bounded_and_sets_available_at_to_observed_retrieval():
    body = _payload()
    response = _FakeResponse(body, shfe_eod_url(REPORT_DAY))
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return response

    report = fetch_shfe_eod(
        REPORT_DAY,
        timeout_seconds=3.5,
        max_bytes=4096,
        opener=opener,
        clock=lambda: RETRIEVED_AT,
    )

    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == shfe_eod_url(REPORT_DAY)
    assert request.get_method() == "GET"
    assert request.get_header("Accept") == "application/json"
    assert timeout == 3.5
    assert response.closed
    assert report.available_at == RETRIEVED_AT
    assert report.retrieved_at == RETRIEVED_AT


@pytest.mark.parametrize(
    "kwargs,expected_code",
    [
        ({"max_bytes": 8}, "RESPONSE_TOO_LARGE"),
        ({"timeout_seconds": float("inf")}, "INVALID_ARGUMENT"),
    ],
)
def test_fetch_rejects_oversize_or_invalid_timeout(kwargs, expected_code):
    if expected_code == "INVALID_ARGUMENT":
        with pytest.raises(ValueError):
            fetch_shfe_eod(REPORT_DAY, opener=lambda *_a, **_k: None, **kwargs)
    else:
        response = _FakeResponse(_payload(), shfe_eod_url(REPORT_DAY))
        with pytest.raises(ShfeEodError) as caught:
            fetch_shfe_eod(
                REPORT_DAY,
                opener=lambda *_a, **_k: response,
                clock=lambda: RETRIEVED_AT,
                **kwargs,
            )
        assert caught.value.code == expected_code


def test_fetch_rejects_final_url_and_reported_update_after_retrieval():
    wrong_url = _FakeResponse(_payload(), "https://example.invalid/report.dat")
    with pytest.raises(ShfeEodError) as redirected:
        fetch_shfe_eod(
            REPORT_DAY,
            opener=lambda *_a, **_k: wrong_url,
            clock=lambda: RETRIEVED_AT,
        )
    assert redirected.value.code == "FINAL_URL_MISMATCH"

    correct_url = _FakeResponse(_payload(), shfe_eod_url(REPORT_DAY))
    with pytest.raises(ShfeEodError) as early:
        fetch_shfe_eod(
            REPORT_DAY,
            opener=lambda *_a, **_k: correct_url,
            clock=lambda: datetime(2026, 10, 21, 7, 26, 2, tzinfo=timezone.utc),
        )
    assert early.value.code == "SOURCE_UPDATE_AFTER_RETRIEVAL"


def test_urllib_redirect_handler_blocks_before_sending_redirected_request():
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
        with pytest.raises(ShfeEodError) as redirected:
            _open_without_redirects(Request(url), timeout=2.0)
        assert redirected.value.code == "REDIRECT_REJECTED"
        assert state["redirected_request_count"] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
