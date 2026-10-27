"""Source-fake tests for the public CTP all-visible futures snapshot adapter."""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from backtrader.feeds import futures_ctp_snapshot as adapter
from backtrader.feeds.futures_main_contract import (
    CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
    ExchangeTradingCalendar,
    ExchangeTradingDay,
    ProductKey,
    select_main_contracts,
)


UTC = timezone.utc
NOW = datetime(2026, 10, 23, 16, 0, tzinfo=UTC)
TRADING_DAY = date(2026, 10, 23)
PRODUCT = ProductKey("DCE", "M")


@pytest.fixture(scope="module")
def query_result_type():
    from tests.test_utils.optional_sdk import optional_sdk

    return optional_sdk("bt_api_ctp.query").QueryResult


def _catalog_row(
    instrument_id="M2611",
    *,
    product_id="m",
    exchange_id="DCE",
    product_class="1",
    is_trading=1,
    expiry="20261116",
):
    return {
        "InstrumentID": instrument_id,
        "instrument_id": instrument_id,
        "ExchangeID": exchange_id,
        "exchange_id": exchange_id,
        "ProductID": product_id,
        "product_id": product_id,
        "ProductClass": product_class,
        "product_class": product_class,
        "IsTrading": is_trading,
        "is_trading": bool(is_trading),
        "ExpireDate": expiry,
        "expiry_date": expiry,
    }


def _quote_row(
    instrument_id="M2611",
    *,
    exchange_id="DCE",
    trading_day="20261023",
    open_interest=1000,
    volume=1,
    action_day="20261023",
    update_time="09:00:00",
    update_millisec=250,
):
    return {
        "InstrumentID": instrument_id,
        "instrument_id": instrument_id,
        "ExchangeID": exchange_id,
        "exchange_id": exchange_id,
        "TradingDay": trading_day,
        "trading_day": trading_day,
        "OpenInterest": open_interest,
        "open_interest": open_interest,
        "Volume": volume,
        "volume": volume,
        "ActionDay": action_day,
        "action_day": action_day,
        "UpdateTime": update_time,
        "update_time": update_time,
        "UpdateMillisec": update_millisec,
        "update_millisec": update_millisec,
    }


def _query_result(
    query_result_type,
    request_type,
    request_id,
    records,
    *,
    generation=7,
    started_at=NOW - timedelta(seconds=5),
    completed_at=NOW - timedelta(seconds=1),
    complete=True,
    is_last_seen=True,
    timed_out=False,
    unsupported=False,
    error_code=None,
    error_message="",
    late_callback_count=0,
    submit_code=0,
):
    return query_result_type(
        request_type=request_type,
        request_id=request_id,
        connection_generation=generation,
        account_fingerprint="fixture-account-fingerprint",
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        is_last_seen=is_last_seen,
        error_code=error_code,
        error_message=error_message,
        timed_out=timed_out,
        complete=complete,
        records=tuple(records),
        late_callback_count=late_callback_count,
        unsupported=unsupported,
        submit_code=submit_code,
    )


def _session(*, generation=7, trading_day="20261023", ready=True):
    return {
        "connected": ready,
        "read_only_ready": ready,
        "connection_generation": generation,
        "trading_day": trading_day,
    }


class FakeCtpLiveFeed:
    """Fake only the source edge; QueryResult and Backtrader DTOs stay real."""

    def __init__(
        self,
        catalog_result,
        quote_result,
        *,
        session_states=None,
        catalog_delay=0.0,
    ):
        self.catalog_result = catalog_result
        self.quote_result = quote_result
        self.session_states = list(session_states or (_session(), _session()))
        self.session_calls = 0
        self.catalog_delay = catalog_delay
        self.catalog_kwargs = None
        self.quote_kwargs = None

    def get_session_state(self):
        index = min(self.session_calls, len(self.session_states) - 1)
        self.session_calls += 1
        return dict(self.session_states[index])

    def query_instruments_result(self, **kwargs):
        self.catalog_kwargs = dict(kwargs)
        if self.catalog_delay:
            time.sleep(self.catalog_delay)
        return self.catalog_result

    def query_depth_market_data_result(self, **kwargs):
        self.quote_kwargs = dict(kwargs)
        return self.quote_result


def _feed(query_result_type, *, catalog_rows=None, quote_rows=None, **kwargs):
    catalog = _query_result(
        query_result_type,
        "instruments",
        101,
        tuple(catalog_rows if catalog_rows is not None else (_catalog_row(),)),
    )
    quotes = _query_result(
        query_result_type,
        "depth_market_data",
        102,
        tuple(quote_rows if quote_rows is not None else (_quote_row(),)),
    )
    return FakeCtpLiveFeed(catalog, quotes, **kwargs)


def _fixed_collector_clock(monkeypatch):
    monkeypatch.setattr(adapter, "_now_utc", lambda: NOW)


def _selector_calendar():
    start = date(2026, 10, 1)
    through = date(2027, 1, 15)
    days = []
    current = start
    while current <= through:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return ExchangeTradingCalendar(
        exchange_id="DCE",
        source_id="fixture.exchange-calendar",
        version="fixture-1",
        available_at=NOW - timedelta(days=40),
        retrieved_at=NOW - timedelta(days=1),
        coverage_start=start,
        coverage_through=through,
        trading_days=tuple(days),
        complete=True,
    )


def test_module_import_keeps_optional_ctp_sdk_lazy():
    code = (
        "import sys; "
        "import backtrader.feeds.futures_ctp_snapshot; "
        "assert 'bt_api_ctp' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_collects_complete_visible_catalog_and_quote_rows_without_ranking(
    monkeypatch, query_result_type
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(
        query_result_type,
        catalog_rows=(
            _catalog_row("m2611"),
            _catalog_row(
                "M2612",
                expiry="20261215",
            ),
            _catalog_row(
                "M2611-C-3000",
                product_class="2",
                expiry="20261116",
            ),
        ),
        quote_rows=(
            _quote_row("m2611", update_time="08:30:00"),
            _quote_row("M2612", open_interest=500, volume=800),
            _quote_row("M2611-C-3000", open_interest=80, volume=90),
        ),
    )

    snapshot = adapter.collect_ctp_futures_snapshot(feed)

    assert snapshot.session_trading_day_before == TRADING_DAY
    assert snapshot.session_trading_day_after == TRADING_DAY
    assert snapshot.session_generation_before == 7
    assert snapshot.session_generation_after == 7
    assert len(snapshot.catalog_records) == 3
    assert [row.instrument_id for row in snapshot.catalog_records] == [
        "m2611",
        "M2612",
        "M2611-C-3000",
    ]
    assert [row.asset_type for row in snapshot.catalog_records] == [
        "future",
        "future",
        "option",
    ]
    assert len(snapshot.quote_records) == 3
    assert snapshot.quote_records[0].update_time == "08:30:00"
    assert snapshot.quote_source.completed_at == NOW - timedelta(seconds=1)
    assert snapshot.quote_source.record_count == 3
    assert snapshot.catalog_source.record_count == 3
    assert len(snapshot.catalog_source.source_sha256) == 64
    assert len(snapshot.quote_source.source_sha256) == 64
    assert snapshot.catalog_source.source_kind == "instruments"
    assert snapshot.quote_source.source_kind == "depth_market_data"
    assert snapshot.catalog_source.source_id == "bt_api_ctp.CtpLiveFeed.query_instruments_result"
    assert snapshot.quote_source.source_id == (
        "bt_api_ctp.CtpLiveFeed.query_depth_market_data_result"
    )
    assert feed.session_calls == 2
    assert feed.catalog_kwargs["instrument_id"] == ""
    assert feed.catalog_kwargs["exchange_id"] == ""
    assert feed.catalog_kwargs["product_id"] == ""
    assert feed.catalog_kwargs["max_duration"] > 0
    assert feed.quote_kwargs["instrument_id"] == ""
    assert feed.quote_kwargs["exchange_id"] == ""
    assert feed.quote_kwargs["timeout"] > 0
    assert set(feed.catalog_kwargs).issubset(
        {"instrument_id", "exchange_id", "product_id", "timeout", "max_duration"}
    )
    assert set(feed.quote_kwargs).issubset({"instrument_id", "exchange_id", "timeout"})


def test_collector_accepts_a_valid_descriptive_source_prefix(monkeypatch, query_result_type):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)

    snapshot = adapter.collect_ctp_futures_snapshot(
        feed,
        source_prefix="backtrader.stores.CtpClientWrapper.bt_api_ctp.TraderClient",
    )

    assert snapshot.catalog_source.source_id == (
        "backtrader.stores.CtpClientWrapper.bt_api_ctp.TraderClient.query_instruments_result"
    )
    assert snapshot.quote_source.source_id == (
        "backtrader.stores.CtpClientWrapper.bt_api_ctp.TraderClient.query_depth_market_data_result"
    )


@pytest.mark.parametrize("source_prefix", ("", "not valid", "provider/TraderClient", "a..b"))
def test_collector_rejects_invalid_source_prefix_before_loading_sdk(source_prefix):
    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(object(), source_prefix=source_prefix)

    assert caught.value.code == "SOURCE_PREFIX_INVALID"


def test_public_query_text_bytes_are_decoded_but_raw_rows_stay_digest_source(
    monkeypatch, query_result_type
):
    _fixed_collector_clock(monkeypatch)
    catalog = _catalog_row("m2611")
    catalog.update(
        {
            "InstrumentID": b"m2611",
            "ExchangeID": b"DCE",
            "ProductID": b"m",
            "ProductClass": b"1",
            "ExpireDate": b"20261116",
        }
    )
    quote = _quote_row("m2611")
    quote.update(
        {
            "InstrumentID": b"m2611",
            "ExchangeID": b"DCE",
            "TradingDay": b"20261023",
            "ActionDay": b"20261023",
            "UpdateTime": b"09:00:00",
        }
    )
    feed = _feed(query_result_type, catalog_rows=(catalog,), quote_rows=(quote,))
    catalog_raw_records = feed.catalog_result.records
    quote_raw_records = feed.quote_result.records

    snapshot = adapter.collect_ctp_futures_snapshot(feed)

    catalog_record = snapshot.catalog_records[0]
    quote_record = snapshot.quote_records[0]
    assert (catalog_record.instrument_id, catalog_record.product.exchange_id) == ("m2611", "DCE")
    assert (catalog_record.product.product_id, catalog_record.product_class) == ("M", "1")
    assert catalog_record.expiry_date.isoformat() == "2026-11-16"
    assert (quote_record.instrument_id, quote_record.exchange_id) == ("m2611", "DCE")
    assert quote_record.trading_day == TRADING_DAY
    assert quote_record.action_day == "20261023"
    assert quote_record.update_time == "09:00:00"
    assert snapshot.catalog_source.source_sha256 == adapter._record_digest(catalog_raw_records)
    assert snapshot.quote_source.source_sha256 == adapter._record_digest(quote_raw_records)
    assert catalog_raw_records[0]["InstrumentID"] == b"m2611"
    assert quote_raw_records[0]["TradingDay"] == b"20261023"


@pytest.mark.parametrize(
    ("family", "native_name", "alias_name", "bad_value", "expected_code"),
    [
        (
            "catalog",
            "InstrumentID",
            "instrument_id",
            b"M2611\xff",
            "CATALOG_IDENTITY_INVALID",
        ),
        (
            "quote",
            "InstrumentID",
            "instrument_id",
            b"M2611\xff",
            "QUOTE_IDENTITY_INVALID",
        ),
        (
            "quote",
            "TradingDay",
            "trading_day",
            b"20261023\xff",
            "QUOTE_TRADING_DAY_INVALID",
        ),
        (
            "quote",
            "ActionDay",
            "action_day",
            b"20261023\xff",
            "QUOTE_ACTION_DAY_INVALID",
        ),
        (
            "quote",
            "UpdateTime",
            "update_time",
            b"09:00:00\xff",
            "QUOTE_UPDATE_TIME_INVALID",
        ),
    ],
)
def test_malformed_query_text_bytes_are_rejected(
    monkeypatch,
    query_result_type,
    family,
    native_name,
    alias_name,
    bad_value,
    expected_code,
):
    _fixed_collector_clock(monkeypatch)
    catalog_rows = (_catalog_row(),)
    quote_rows = (_quote_row(),)
    if family == "catalog":
        catalog_rows[0][native_name] = bad_value
        catalog_rows[0][alias_name] = bad_value
    else:
        quote_rows[0][native_name] = bad_value
        quote_rows[0][alias_name] = bad_value
    feed = _feed(query_result_type, catalog_rows=catalog_rows, quote_rows=quote_rows)

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == expected_code


def test_real_query_results_flow_through_collector_into_equal_weight_selector(
    monkeypatch, query_result_type
):
    _fixed_collector_clock(monkeypatch)
    catalog_rows = (
        _catalog_row("M2611", expiry="20261116"),
        _catalog_row("M2612", expiry="20261215"),
        _catalog_row("M2701", is_trading=0, expiry="20270115"),
        _catalog_row(
            "M2611-C-3000",
            product_class="2",
            expiry="20261116",
        ),
    )
    quote_rows = (
        _quote_row("M2611", open_interest=1000, volume=1),
        _quote_row("M2612", open_interest=500, volume=800),
        _quote_row("M2611-C-3000", open_interest=80, volume=90),
    )
    feed = _feed(query_result_type, catalog_rows=catalog_rows, quote_rows=quote_rows)

    snapshot = adapter.collect_ctp_futures_snapshot(feed)
    manifest = select_main_contracts(
        snapshot,
        (PRODUCT,),
        (ExchangeTradingDay("DCE", TRADING_DAY),),
        (_selector_calendar(),),
        decision_at=NOW,
        policy=CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
    )

    assert manifest.status == "READY", manifest.blockers
    assert manifest.selected_mapping() == ((PRODUCT, "M2612"),)
    assert (
        next(row for row in manifest.candidates if row.instrument_id == "M2612").ranking_score
        == "650.0"
    )
    assert (
        next(row for row in manifest.candidates if row.instrument_id == "M2611").ranking_score
        == "500.5"
    )
    assert (
        next(row for row in manifest.candidates if row.instrument_id == "M2611-C-3000").reason
        == "NOT_ORDINARY_FUTURE"
    )
    projection = manifest.to_dict()
    assert projection["policy"]["score_formula"] == "0.5 * open_interest + 0.5 * volume"
    assert projection["query_snapshot"]["catalog_source"]["record_count"] == 4
    assert projection["query_snapshot"]["quote_source"]["record_count"] == 3


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"complete": False}, "QUERY_INCOMPLETE"),
        ({"is_last_seen": False}, "QUERY_TERMINAL_PACKET_MISSING"),
        ({"timed_out": True}, "QUERY_TIMED_OUT"),
        ({"unsupported": True}, "QUERY_UNSUPPORTED"),
        ({"timed_out": 1}, "QUERY_BOOLEAN_STATE_INVALID"),
        ({"unsupported": 1}, "QUERY_BOOLEAN_STATE_INVALID"),
        ({"error_code": 42}, "QUERY_ERROR"),
        ({"late_callback_count": 1}, "QUERY_LATE_CALLBACKS"),
        ({"submit_code": 7}, "QUERY_SUBMISSION_FAILED"),
    ],
)
def test_incomplete_or_failed_query_facts_have_distinct_refusal_codes(
    monkeypatch, query_result_type, changes, expected_code
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)
    feed.catalog_result = _query_result(
        query_result_type,
        "instruments",
        101,
        (_catalog_row(),),
        **changes,
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == expected_code
    assert feed.quote_kwargs is None
    observations = caught.value.query_observations
    assert len(observations) == 1
    observation = observations[0]
    assert observation.stage == "catalog"
    assert observation.entered is True
    assert observation.returned is True
    assert observation.prior_stage_complete is None
    assert observation.result_type_matches is True
    assert observation.request_type_matches is True
    assert observation.generation_matches is True
    assert observation.request_id_positive is True
    assert observation.record_count == 1
    assert observation.record_count_capped is False
    assert observation.error_code_valid is True
    assert observation.error_message_valid is True
    assert observation.late_callback_count_valid is True
    if expected_code == "QUERY_TIMED_OUT":
        assert observation.timed_out is True
        assert observation.error_category == "timeout"
    elif expected_code == "QUERY_TERMINAL_PACKET_MISSING":
        assert observation.is_last_seen is False
        assert observation.error_category == "incomplete"
    elif expected_code == "QUERY_INCOMPLETE":
        assert observation.complete is False
        assert observation.error_category == "incomplete"
    elif expected_code == "QUERY_UNSUPPORTED":
        assert observation.unsupported is True
        assert observation.error_category == "unsupported"
    elif expected_code == "QUERY_BOOLEAN_STATE_INVALID":
        assert observation.timed_out is None or observation.unsupported is None
        assert observation.error_category == "invalid"
    elif expected_code == "QUERY_LATE_CALLBACKS":
        assert observation.late_callbacks_reported is True
        assert observation.error_category == "late_callbacks"
    elif expected_code == "QUERY_SUBMISSION_FAILED":
        assert observation.submit_category == "rejected"
        assert observation.error_category == "submission_error"


@pytest.mark.parametrize(
    ("submit_code", "expected_category"),
    [(None, "not_observed"), (0, "accepted")],
)
def test_catalog_submit_observation_distinguishes_missing_from_zero(
    monkeypatch, query_result_type, submit_code, expected_category
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)
    feed.catalog_result = _query_result(
        query_result_type,
        "instruments",
        101,
        (_catalog_row(),),
        submit_code=submit_code,
    )
    feed.quote_result = _query_result(
        query_result_type,
        "depth_market_data",
        102,
        (),
        timed_out=True,
        complete=False,
        is_last_seen=False,
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    catalog = caught.value.query_observations[0]
    assert catalog.stage == "catalog"
    assert catalog.submit_category == expected_category
    assert catalog.error_category == "none"


@pytest.mark.parametrize(
    ("changes", "expected_category"),
    [
        (
            {
                "timed_out": True,
                "unsupported": True,
                "error_code": 7,
                "submit_code": 7,
                "complete": False,
                "late_callback_count": 1,
            },
            "timeout",
        ),
        (
            {
                "unsupported": True,
                "error_code": 7,
                "submit_code": 7,
                "complete": False,
                "late_callback_count": 1,
            },
            "unsupported",
        ),
        (
            {
                "error_code": 7,
                "submit_code": 7,
                "complete": False,
                "late_callback_count": 1,
            },
            "provider_error",
        ),
        (
            {"submit_code": 7, "complete": False, "late_callback_count": 1},
            "submission_error",
        ),
        (
            {
                "submit_code": 7,
                "error_message": "synthetic-provider-message",
                "complete": False,
                "late_callback_count": 1,
            },
            "submission_error",
        ),
        ({"complete": False, "late_callback_count": 1}, "incomplete"),
        ({"late_callback_count": 1}, "late_callbacks"),
    ],
)
def test_query_diagnostic_error_category_preserves_refusal_priority(
    monkeypatch, query_result_type, changes, expected_category
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)
    feed.catalog_result = _query_result(
        query_result_type,
        "instruments",
        101,
        (_catalog_row(),),
        **changes,
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert feed.catalog_kwargs is not None
    assert feed.quote_kwargs is None
    # The bounded collector DTO follows timeout/provider/submission/completion
    # refusal priority without exposing any underlying error text.
    assert caught.value.query_observations[0].error_category == expected_category


def test_depth_timeout_retains_successful_catalog_and_nonterminal_row_count(
    monkeypatch, query_result_type
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)
    feed.quote_result = _query_result(
        query_result_type,
        "depth_market_data",
        102,
        (_quote_row(), _quote_row("M2612")),
        timed_out=True,
        complete=False,
        is_last_seen=False,
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == "QUERY_TIMED_OUT"
    assert feed.quote_kwargs is not None
    catalog, depth = caught.value.query_observations
    assert (catalog.stage, catalog.entered, catalog.returned) == ("catalog", True, True)
    assert catalog.prior_stage_complete is None
    assert catalog.complete is True and catalog.is_last_seen is True
    assert depth.stage == "depth"
    assert depth.prior_stage_complete is True
    assert depth.result_type_matches is True
    assert depth.request_type_matches is True
    assert depth.generation_matches is True
    assert depth.request_id_positive is True
    assert depth.timed_out is True
    assert depth.complete is False
    assert depth.is_last_seen is False
    assert depth.record_count == 2
    assert depth.late_callbacks_reported is False
    assert depth.error_category == "timeout"


def test_query_generation_must_match_the_current_session(monkeypatch, query_result_type):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)
    feed.catalog_result = _query_result(
        query_result_type,
        "instruments",
        101,
        (_catalog_row(),),
        generation=8,
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == "QUERY_GENERATION_MISMATCH"
    observation = caught.value.query_observations[0]
    assert observation.result_type_matches is True
    assert observation.request_type_matches is True
    assert observation.generation_matches is False
    assert observation.request_id_positive is True
    assert observation.error_category == "none"


def test_wrong_result_type_is_recorded_without_inspecting_the_object(
    monkeypatch, query_result_type
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)
    feed.catalog_result = object()

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == "QUERY_RESULT_TYPE_INVALID"
    assert feed.quote_kwargs is None
    observation = caught.value.query_observations[0]
    assert observation.result_type_matches is False
    assert observation.request_type_matches is None
    assert observation.generation_matches is None
    assert observation.request_id_positive is None
    assert observation.record_count is None
    assert observation.submit_category == "unavailable"
    assert observation.error_category == "unavailable"


def test_request_type_mismatch_is_reported_without_exposing_request_id(
    monkeypatch, query_result_type
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)
    feed.catalog_result = _query_result(
        query_result_type,
        "private-request-name",
        101,
        (_catalog_row(),),
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == "QUERY_REQUEST_TYPE_MISMATCH"
    observation = caught.value.query_observations[0]
    assert observation.result_type_matches is True
    assert observation.request_type_matches is False
    assert observation.generation_matches is True
    assert observation.request_id_positive is True
    assert "private-request-name" not in repr(observation)
    assert not hasattr(observation, "request_id")


def test_query_error_text_is_reduced_to_presence_and_category(monkeypatch, query_result_type):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)
    feed.catalog_result = _query_result(
        query_result_type,
        "instruments",
        101,
        (_catalog_row(),),
        error_message="private-provider-payload",
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == "QUERY_ERROR_MESSAGE"
    assert str(caught.value) == "QUERY_ERROR_MESSAGE"
    assert "private-provider-payload" not in repr(caught.value.query_observations)
    observation = caught.value.query_observations[0]
    assert observation.error_message_valid is True
    assert observation.error_message_present is True
    assert observation.error_category == "provider_error"


@pytest.mark.parametrize(
    ("second_session", "expected_code"),
    [
        (_session(generation=8), "SESSION_CHANGED_DURING_COLLECTION"),
        (_session(trading_day="20261026"), "SESSION_CHANGED_DURING_COLLECTION"),
    ],
)
def test_session_generation_and_trading_day_must_remain_stable(
    monkeypatch, query_result_type, second_session, expected_code
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(
        query_result_type,
        session_states=(_session(), second_session),
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == expected_code
    assert feed.session_calls == 2


@pytest.mark.parametrize(
    ("completed_at", "expected_code"),
    [
        (NOW + timedelta(seconds=1), "QUERY_TIME_IN_FUTURE"),
        (NOW - timedelta(seconds=301), "SNAPSHOT_TOO_OLD"),
    ],
)
def test_future_and_stale_query_completion_are_distinct(
    monkeypatch, query_result_type, completed_at, expected_code
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)
    feed.quote_result = _query_result(
        query_result_type,
        "depth_market_data",
        102,
        (_quote_row(),),
        started_at=completed_at - timedelta(seconds=1),
        completed_at=completed_at,
    )

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(
            feed,
            max_collection_seconds=360.0 if expected_code == "SNAPSHOT_TOO_OLD" else 300.0,
            max_snapshot_age_seconds=0.5 if expected_code == "SNAPSHOT_TOO_OLD" else 300.0,
        )

    assert caught.value.code == expected_code


def test_total_collection_budget_is_enforced_after_public_query_returns(
    monkeypatch, query_result_type
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type, catalog_delay=0.02)

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed, max_collection_seconds=0.005)

    assert caught.value.code == "COLLECTION_TIMEOUT"
    assert feed.quote_kwargs is None
    assert feed.catalog_kwargs["timeout"] <= 0.005
    assert feed.catalog_kwargs["max_duration"] <= 0.005
    assert len(caught.value.query_observations) == 1
    assert caught.value.query_observations[0].stage == "catalog"
    assert caught.value.query_observations[0].returned is True


@pytest.mark.parametrize(
    ("endpoint", "expected_code"),
    [
        ("query_instruments_result", "CATALOG_QUERY_CALL_FAILED"),
        ("query_depth_market_data_result", "QUOTE_QUERY_CALL_FAILED"),
    ],
)
def test_public_query_call_exceptions_have_finite_refusal_codes(
    monkeypatch, query_result_type, endpoint, expected_code
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type)
    calls = []

    def fail_query(**kwargs):
        calls.append(dict(kwargs))
        raise RuntimeError("private-provider-payload")

    monkeypatch.setattr(feed, endpoint, fail_query)
    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == expected_code
    assert str(caught.value) == expected_code
    assert "private-provider-payload" not in str(caught.value)
    assert len(calls) == 1
    observation = caught.value.query_observations[-1]
    assert observation.returned is False
    assert observation.result_type_matches is None
    assert observation.request_type_matches is None
    assert observation.generation_matches is None
    assert observation.elapsed_seconds is None or observation.elapsed_seconds >= 0
    assert observation.submit_category == "unavailable"
    assert observation.error_category == "unavailable"
    if endpoint == "query_instruments_result":
        assert len(caught.value.query_observations) == 1
        assert observation.stage == "catalog"
        assert observation.prior_stage_complete is None
        assert feed.quote_kwargs is None
    else:
        assert len(caught.value.query_observations) == 2
        assert observation.stage == "depth"
        assert observation.prior_stage_complete is True
        assert feed.catalog_kwargs is not None


@pytest.mark.parametrize(
    ("catalog_row", "expected_code"),
    [
        ({"InstrumentID": "M2611"}, "CATALOG_EXCHANGE_ID_MISSING"),
        (
            {**_catalog_row(), "instrument_id": "M2612"},
            "CATALOG_FIELD_CONFLICT",
        ),
    ],
)
def test_missing_and_conflicting_catalog_identity_are_not_normalized_away(
    monkeypatch, query_result_type, catalog_row, expected_code
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(query_result_type, catalog_rows=(catalog_row,))

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == expected_code


def test_current_depth_row_missing_trading_day_is_refused(monkeypatch, query_result_type):
    _fixed_collector_clock(monkeypatch)
    row = _quote_row()
    row.pop("TradingDay")
    row.pop("trading_day")
    feed = _feed(query_result_type, quote_rows=(row,))

    with pytest.raises(adapter.CtpFuturesSnapshotError) as caught:
        adapter.collect_ctp_futures_snapshot(feed)

    assert caught.value.code == "QUOTE_TRADING_DAY_MISSING"


@pytest.mark.parametrize(
    ("quote_rows", "expected_blocker"),
    [
        ((_quote_row("M2611"),), "QUOTE_ROW_MISSING_FOR_CANDIDATE"),
        (
            (
                _quote_row("M2611"),
                _quote_row("M2612"),
                _quote_row("M2612"),
            ),
            "DUPLICATE_QUOTE_ROW",
        ),
        (
            (
                _quote_row("M2611"),
                _quote_row("M2612", trading_day="20261026"),
            ),
            "QUOTE_TRADING_DAY_MISMATCH",
        ),
        (
            (
                _quote_row("M2611"),
                _quote_row("M2612"),
                _quote_row("RB2611", exchange_id="SHFE"),
            ),
            "QUOTE_ID_NOT_IN_CATALOG",
        ),
    ],
)
def test_selector_fails_closed_on_missing_conflicting_or_cross_day_quote_rows(
    monkeypatch, query_result_type, quote_rows, expected_blocker
):
    _fixed_collector_clock(monkeypatch)
    feed = _feed(
        query_result_type,
        catalog_rows=(
            _catalog_row("M2611"),
            _catalog_row("M2612", expiry="20261215"),
        ),
        quote_rows=quote_rows,
    )
    snapshot = adapter.collect_ctp_futures_snapshot(feed)
    manifest = select_main_contracts(
        snapshot,
        (PRODUCT,),
        (ExchangeTradingDay("DCE", TRADING_DAY),),
        (_selector_calendar(),),
        decision_at=NOW,
        policy=CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
    )

    assert manifest.status == "BLOCKED"
    assert expected_blocker in manifest.blockers
    assert len(snapshot.quote_records) == len(quote_rows)
