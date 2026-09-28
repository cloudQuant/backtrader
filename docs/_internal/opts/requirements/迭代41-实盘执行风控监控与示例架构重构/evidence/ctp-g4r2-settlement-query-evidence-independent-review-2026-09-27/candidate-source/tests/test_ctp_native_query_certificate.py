"""Offline contracts for the digest-only native CTP query certificate."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from types import SimpleNamespace

import pytest

import bt_api_ctp.containers.ctp.ctp_native_query_certificate as certificate_module
import bt_api_ctp.ctp.client as client_module
from bt_api_ctp import CtpNativeQueryCertificateBuilder
from bt_api_ctp.containers.ctp.ctp_native_query_certificate import (
    CtpNativeQueryCertificateError,
)
from bt_api_ctp.ctp.client import TraderClient, _TraderSpi
from bt_api_ctp.query import _QUERY_EVIDENCE_MAX_TTL_SECONDS, QueryResult

BROKER_ID = "certificate-fixture-broker"
INVESTOR_ID = "certificate-fixture-investor"
INSTRUMENT_ID = "IF2609"
EXCHANGE_ID = "CFFEX"
HEDGE_FLAG = "1"


def test_certificate_module_is_in_the_installable_package():
    package_file = files("bt_api_ctp.containers.ctp").joinpath("ctp_native_query_certificate.py")
    assert package_file.is_file()


def offline_client(broker_id=BROKER_ID, investor_id=INVESTOR_ID) -> TraderClient:
    client = TraderClient(
        "tcp://offline.invalid:0",
        broker_id,
        investor_id,
        "",
        auto_settlement_confirm=False,
    )
    client._connected = True
    client._authentication_state = "authenticated"
    client._login_state = "logging_in"
    client._connection_generation = 7
    client._req_id = 30
    client._login_request_id = 30
    client._login_connection_generation = 7
    client._query_interval = 0.0
    _TraderSpi(client).OnRspUserLogin(
        SimpleNamespace(
            BrokerID=client._bound_broker_id,
            UserID=client._bound_user_id,
            TradingDay="20260923",
            FrontID=0,
            SessionID=0,
            MaxOrderRef="",
        ),
        SimpleNamespace(ErrorID=0, ErrorMsg=""),
        30,
        True,
    )
    return client


def request_filters(client: TraderClient, request_type: str, *, instrument_id=INSTRUMENT_ID):
    account = {"BrokerID": BROKER_ID, "InvestorID": INVESTOR_ID}
    if request_type in ("account", "positions"):
        return account
    if request_type in ("orders", "trades"):
        return {
            **account,
            "InstrumentID": "",
            "ExchangeID": "",
            **(
                {"OrderSysID": ""}
                if request_type == "orders"
                else {
                    "TradeID": "",
                    "TradeTimeStart": "",
                    "TradeTimeEnd": "",
                }
            ),
        }
    if request_type == "instruments":
        return {
            "InstrumentID": instrument_id,
            "ExchangeID": EXCHANGE_ID,
            "ProductID": "",
        }
    if request_type == "margin_rate":
        return {
            **account,
            "InstrumentID": instrument_id,
            "ExchangeID": EXCHANGE_ID,
            "HedgeFlag": HEDGE_FLAG,
        }
    if request_type == "commission_rate":
        return {
            **account,
            "InstrumentID": instrument_id,
            "ExchangeID": EXCHANGE_ID,
        }
    raise AssertionError(request_type)


def query_records(request_type: str, *, instrument_id=INSTRUMENT_ID, exchange_id=EXCHANGE_ID):
    if request_type == "instruments":
        return ({"InstrumentID": instrument_id, "ExchangeID": exchange_id},)
    if request_type == "margin_rate":
        return (
            {
                "BrokerID": BROKER_ID,
                "InvestorID": INVESTOR_ID,
                "TradingDay": "20260923",
                "InstrumentID": instrument_id,
                "ExchangeID": exchange_id,
                "HedgeFlag": HEDGE_FLAG,
                "LongMarginRatioByMoney": 0.12,
            },
        )
    if request_type == "commission_rate":
        return (
            {
                "BrokerID": BROKER_ID,
                "InvestorID": INVESTOR_ID,
                "TradingDay": "20260923",
                "InstrumentID": instrument_id,
                "ExchangeID": exchange_id,
                "OpenRatioByMoney": 0.0001,
            },
        )
    if request_type == "account":
        return ({"BrokerID": BROKER_ID, "AccountID": INVESTOR_ID},)
    if request_type == "positions":
        return (
            {
                "BrokerID": BROKER_ID,
                "InvestorID": INVESTOR_ID,
                "TradingDay": "20260923",
            },
        )
    return ()


def issue_query(
    client: TraderClient,
    request_type: str,
    *,
    filters=None,
    records=None,
    late_callback_count=0,
    explicit_filters=None,
    advance_before_terminal=None,
) -> QueryResult:
    rows = query_records(request_type) if records is None else tuple(records)
    if explicit_filters is None:
        explicit_filters = ("HedgeFlag",) if request_type == "margin_rate" else ()
    accumulator = client._new_query_accumulator(
        request_type,
        request_filters=filters if filters is not None else request_filters(client, request_type),
        explicit_request_filters=explicit_filters,
    )
    for row in rows:
        client._handle_query_callback(request_type, row, None, accumulator.request_id, False)
    if advance_before_terminal is not None:
        advance_before_terminal()
    client._handle_query_callback(request_type, None, None, accumulator.request_id, True)
    accumulator.sealed = True
    accumulator.late_callback_count = late_callback_count
    return accumulator.result()


def issue_all(client: TraderClient, *, instrument_id=INSTRUMENT_ID):
    return {
        request_type: issue_query(
            client,
            request_type,
            filters=request_filters(client, request_type, instrument_id=instrument_id),
            records=query_records(request_type, instrument_id=instrument_id),
        )
        for request_type in (
            "account",
            "positions",
            "orders",
            "trades",
            "instruments",
            "margin_rate",
            "commission_rate",
        )
    }


def builder(client: TraderClient) -> CtpNativeQueryCertificateBuilder:
    return CtpNativeQueryCertificateBuilder(
        client,
        instrument_id=INSTRUMENT_ID,
        exchange_id=EXCHANGE_ID,
        hedge_flag=HEDGE_FLAG,
    )


def add_all(certificate_builder, queries):
    for request_type in (
        "account",
        "positions",
        "orders",
        "trades",
        "instruments",
        "margin_rate",
        "commission_rate",
    ):
        certificate_builder.add(queries[request_type])


def patch_monotonic_and_utc_clock(monkeypatch, clock):
    start_monotonic = clock[0]
    start_utc = datetime.now(timezone.utc)

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = start_utc + timedelta(seconds=clock[0] - start_monotonic)
            if tz is None:
                return cls.fromtimestamp(value.timestamp()).replace(tzinfo=None)
            return cls.fromtimestamp(value.timestamp(), tz)

    fake_time = SimpleNamespace(monotonic=lambda: clock[0])
    monkeypatch.setattr(certificate_module, "time", fake_time)
    monkeypatch.setattr(client_module, "time", fake_time)
    monkeypatch.setattr(certificate_module, "datetime", FakeDateTime)
    monkeypatch.setattr(client_module, "datetime", FakeDateTime)


def test_certificate_binds_seven_terminal_reads_and_exposes_only_digests():
    client = offline_client()
    certificate_builder = builder(client)
    add_all(certificate_builder, issue_all(client))

    certificate = certificate_builder.finish()
    public = certificate.as_public_dict()

    assert public["complete"] is True
    assert public["atomic_snapshot"] is False
    assert public["execution_authorized"] is False
    assert public["scope"]["connection_generation"] == 7
    assert public["scope"]["trading_day"] == "20260923"
    assert len(public["queries"]) == 7
    assert len(certificate.query_digest) == 64
    assert certificate.query_digest == certificate.certificate_sha256
    assert certificate.query_digests == tuple(
        (query["request_type"], query["records_sha256"]) for query in public["queries"]
    )
    serialized = str(public)
    for raw_id in (BROKER_ID, INVESTOR_ID, INSTRUMENT_ID, EXCHANGE_ID):
        assert raw_id not in serialized
    assert "LongMarginRatioByMoney" not in serialized

    forged_certificate = replace(certificate)
    with pytest.raises(CtpNativeQueryCertificateError, match="query_certificate_untrusted"):
        forged_certificate.as_public_dict()


def test_empty_instrument_and_rate_queries_are_not_admitted():
    client = offline_client()
    for request_type in ("instruments", "margin_rate", "commission_rate"):
        certificate_builder = builder(client)
        empty_result = issue_query(client, request_type, records=())
        with pytest.raises(CtpNativeQueryCertificateError, match="query_required_rows_missing"):
            certificate_builder.add(empty_result)


def test_default_hedge_filter_cannot_certify_a_scoped_margin_query():
    client = offline_client()
    certificate_builder = builder(client)
    defaulted_hedge = issue_query(
        client,
        "margin_rate",
        explicit_filters=(),
    )

    with pytest.raises(
        CtpNativeQueryCertificateError,
        match="query_filter_hedge_not_explicit",
    ):
        certificate_builder.add(defaulted_hedge)


def test_trader_method_records_explicit_hedge_scope_without_network():
    def native_margin_query(client):
        def query(_field, request_id):
            record = query_records("margin_rate")[0]
            record["BrokerID"] = client._bound_broker_id
            record["InvestorID"] = client._bound_user_id
            client._handle_query_callback(
                "margin_rate",
                record,
                None,
                request_id,
                True,
            )
            return 0

        return query

    default_client = offline_client("9999", "investor01")
    default_client._api = SimpleNamespace(
        ReqQryInstrumentMarginRate=native_margin_query(default_client)
    )
    default_builder = builder(default_client)
    default_result = default_client.query_instrument_margin_rate_result(
        INSTRUMENT_ID,
        exchange_id=EXCHANGE_ID,
    )
    assert default_result.query_source.request_filters[-1] == (
        "InvestorID",
        default_client._bound_user_id,
    )
    assert "HedgeFlag" not in default_result.query_source.explicit_request_filters
    with pytest.raises(
        CtpNativeQueryCertificateError,
        match="query_filter_hedge_not_explicit",
    ):
        default_builder.add(default_result)

    explicit_client = offline_client("9999", "investor01")
    explicit_client._api = SimpleNamespace(
        ReqQryInstrumentMarginRate=native_margin_query(explicit_client)
    )
    explicit_builder = builder(explicit_client)
    explicit_result = explicit_client.query_instrument_margin_rate_result(
        INSTRUMENT_ID,
        exchange_id=EXCHANGE_ID,
        hedge_flag=HEDGE_FLAG,
    )
    assert "HedgeFlag" in explicit_result.query_source.explicit_request_filters
    explicit_builder.add(explicit_result)


def test_unissued_forged_result_is_rejected():
    client = offline_client()
    certificate_builder = builder(client)
    forged = QueryResult(
        request_type="account",
        request_id=1,
        connection_generation=7,
        account_fingerprint=client._account_fingerprint,
        started_at_utc=datetime.now(timezone.utc),
        completed_at_utc=datetime.now(timezone.utc),
        is_last_seen=True,
        error_code=None,
        error_message="",
        timed_out=False,
        complete=True,
        records=(),
    )

    with pytest.raises(CtpNativeQueryCertificateError, match="query_source_untrusted"):
        certificate_builder.add(forged)


def test_generation_change_makes_old_source_stale():
    client = offline_client()
    certificate_builder = builder(client)
    result = issue_query(client, "account")
    client._connection_generation += 1

    with pytest.raises(CtpNativeQueryCertificateError, match="query_session_scope_invalid"):
        certificate_builder.add(result)


def test_duplicate_query_type_and_request_id_are_rejected():
    client = offline_client()
    certificate_builder = builder(client)
    account = issue_query(client, "account")
    positions = issue_query(client, "positions")
    certificate_builder.add(account)
    with pytest.raises(CtpNativeQueryCertificateError, match="query_type_duplicate"):
        certificate_builder.add(account)

    duplicate_id = replace(positions)
    object.__setattr__(duplicate_id, "request_id", account.request_id)
    with pytest.raises(CtpNativeQueryCertificateError, match="query_request_id_duplicate"):
        certificate_builder.add(duplicate_id)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"complete": False}, "query_incomplete"),
        ({"is_last_seen": False}, "query_not_terminal"),
        ({"timed_out": True}, "query_timed_out"),
        ({"late_callback_count": 1}, "query_late_callback"),
        ({"error_code": 7}, "query_error"),
        ({"submit_code": 7}, "query_submit_failed"),
    ],
)
def test_incomplete_error_timeout_and_late_results_fail_closed(changes, error):
    client = offline_client()
    certificate_builder = builder(client)
    result = issue_query(client, "account")
    for name, value in changes.items():
        object.__setattr__(result, name, value)

    with pytest.raises(CtpNativeQueryCertificateError, match=error):
        certificate_builder.add(result)


def test_payload_mutation_and_rate_filter_mismatch_are_rejected():
    client = offline_client()
    certificate_builder = builder(client)
    account = issue_query(client, "account", records=({"Balance": 10.0},))
    account.records[0]["Balance"] = 11.0
    with pytest.raises(CtpNativeQueryCertificateError, match="query_payload_mismatch"):
        certificate_builder.add(account)

    wrong_filter_builder = builder(client)
    wrong_rate = issue_query(
        client,
        "margin_rate",
        filters=request_filters(client, "margin_rate", instrument_id="IF2612"),
        records=query_records("margin_rate", instrument_id="IF2612"),
    )
    with pytest.raises(CtpNativeQueryCertificateError, match="query_filter_instrument_mismatch"):
        wrong_filter_builder.add(wrong_rate)


def test_mismatched_returned_row_scope_is_rejected():
    client = offline_client()
    certificate_builder = builder(client)
    wrong_row = issue_query(
        client,
        "commission_rate",
        records=(
            {
                **query_records("commission_rate")[0],
                "InstrumentID": "IF2612",
            },
        ),
    )

    with pytest.raises(CtpNativeQueryCertificateError, match="query_row_instrument_mismatch"):
        certificate_builder.add(wrong_row)


def test_instrument_query_certifies_exchange_rows_without_claiming_filter_was_applied():
    client = offline_client()
    certificate_builder = builder(client)
    rows = (
        {"InstrumentID": INSTRUMENT_ID, "ExchangeID": EXCHANGE_ID},
        *(
            {"InstrumentID": f"SA_OTHER_{index:03d}", "ExchangeID": EXCHANGE_ID}
            for index in range(82)
        ),
    )
    result = issue_query(client, "instruments", records=rows)
    assert result.query_source.request_filters == (
        ("ExchangeID", EXCHANGE_ID),
        ("InstrumentID", INSTRUMENT_ID),
        ("ProductID", ""),
    )

    certificate_builder.add(result)
    for request_type in (
        "account",
        "positions",
        "orders",
        "trades",
        "margin_rate",
        "commission_rate",
    ):
        certificate_builder.add(issue_query(client, request_type))
    public = certificate_builder.finish().as_public_dict()
    query = next(query for query in public["queries"] if query["request_type"] == "instruments")

    assert public["schema"] == "ctp_native_query_certificate.v4"
    assert query["record_count"] == 83
    assert query["records_sha256"] == result.query_source.records_sha256
    assert query["instrument_row_scope"] == "same_exchange"
    assert query["instrument_filter_application"] == "unverified"
    assert query["target_instrument_match_count"] == 1


def test_instrument_superset_without_target_is_rejected():
    client = offline_client()
    certificate_builder = builder(client)
    result = issue_query(
        client,
        "instruments",
        records=(
            {"InstrumentID": "SA_OTHER_001", "ExchangeID": EXCHANGE_ID},
            {"InstrumentID": "SA_OTHER_002", "ExchangeID": EXCHANGE_ID},
        ),
    )

    with pytest.raises(
        CtpNativeQueryCertificateError,
        match="query_target_instrument_missing",
    ):
        certificate_builder.add(result)


def test_instrument_superset_with_wrong_exchange_row_is_rejected():
    client = offline_client()
    certificate_builder = builder(client)
    result = issue_query(
        client,
        "instruments",
        records=(
            {"InstrumentID": INSTRUMENT_ID, "ExchangeID": EXCHANGE_ID},
            {"InstrumentID": "SA_OTHER_001", "ExchangeID": "SHFE"},
        ),
    )

    with pytest.raises(CtpNativeQueryCertificateError, match="query_row_exchange_mismatch"):
        certificate_builder.add(result)


def test_duplicate_target_instrument_rows_are_rejected():
    client = offline_client()
    certificate_builder = builder(client)
    target = {"InstrumentID": INSTRUMENT_ID, "ExchangeID": EXCHANGE_ID}
    result = issue_query(client, "instruments", records=(target, dict(target)))

    with pytest.raises(
        CtpNativeQueryCertificateError,
        match="query_target_instrument_duplicate",
    ):
        certificate_builder.add(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("BrokerID", "other-broker"),
        ("InvestorID", "other-investor"),
        ("TradingDay", "20260924"),
    ],
)
def test_instrument_superset_scope_mismatch_is_rejected(field, value):
    client = offline_client()
    certificate_builder = builder(client)
    target = {
        "InstrumentID": INSTRUMENT_ID,
        "ExchangeID": EXCHANGE_ID,
        field: value,
    }
    result = issue_query(client, "instruments", records=(target,))

    with pytest.raises(CtpNativeQueryCertificateError, match="query_row_scope_mismatch"):
        certificate_builder.add(result)


def test_instrument_query_partial_result_is_rejected():
    client = offline_client()
    certificate_builder = builder(client)
    result = issue_query(client, "instruments")
    object.__setattr__(result, "complete", False)

    with pytest.raises(CtpNativeQueryCertificateError, match="query_incomplete"):
        certificate_builder.add(result)


def test_instrument_query_expired_result_is_rejected(monkeypatch):
    clock = [100.0]
    patch_monotonic_and_utc_clock(monkeypatch, clock)
    client = offline_client()
    certificate_builder = builder(client)
    result = issue_query(client, "instruments")
    clock[0] += _QUERY_EVIDENCE_MAX_TTL_SECONDS

    with pytest.raises(
        CtpNativeQueryCertificateError,
        match="query_expired_before_capture",
    ):
        certificate_builder.add(result)


def test_account_row_must_match_bound_account_identity():
    client = offline_client()
    certificate_builder = builder(client)
    wrong_row = issue_query(
        client,
        "account",
        records=({"BrokerID": BROKER_ID, "AccountID": "some-other-investor"},),
    )

    with pytest.raises(CtpNativeQueryCertificateError, match="query_account_row_mismatch"):
        certificate_builder.add(wrong_row)


def test_finish_requires_all_seven_and_rechecks_same_client_scope():
    client = offline_client()
    certificate_builder = builder(client)
    certificate_builder.add(issue_query(client, "account"))
    with pytest.raises(CtpNativeQueryCertificateError, match="query_bundle_incomplete"):
        certificate_builder.finish()

    other_builder = builder(client)
    queries = issue_all(client)
    add_all(other_builder, queries)
    client._trading_day = "20260924"
    with pytest.raises(CtpNativeQueryCertificateError, match="query_session_scope_invalid"):
        other_builder.finish()


def test_finish_rejects_evidence_expired_after_add(monkeypatch):
    client = offline_client()
    certificate_builder = builder(client)
    queries = issue_all(client)
    add_all(certificate_builder, queries)
    first_expiry = min(
        result.query_source.trusted_expires_monotonic for result in queries.values()
    )
    monkeypatch.setattr(
        certificate_module,
        "time",
        SimpleNamespace(monotonic=lambda: first_expiry),
    )

    with pytest.raises(
        CtpNativeQueryCertificateError,
        match="query_expired_before_certificate",
    ):
        certificate_builder.finish()


def test_final_scope_read_cannot_cross_expiry_before_certificate_seal(monkeypatch):
    client = offline_client()
    clock = [100.0]
    patch_monotonic_and_utc_clock(monkeypatch, clock)
    certificate_builder = builder(client)
    add_all(certificate_builder, issue_all(client))
    original_get_query_session_scope = client.get_query_session_scope
    scope_reads = 0

    def expire_during_final_scope_read():
        nonlocal scope_reads
        scope = original_get_query_session_scope()
        scope_reads += 1
        if scope_reads == 2:
            clock[0] += _QUERY_EVIDENCE_MAX_TTL_SECONDS
        return scope

    monkeypatch.setattr(client, "get_query_session_scope", expire_during_final_scope_read)
    with pytest.raises(
        CtpNativeQueryCertificateError,
        match="query_expired_before_certificate",
    ):
        certificate_builder.finish()


def test_default_seven_query_cadence_completes_and_preserves_per_read_age(monkeypatch):
    client = offline_client()
    clock = [100.0]
    patch_monotonic_and_utc_clock(monkeypatch, clock)
    certificate_builder = builder(client)
    request_types = (
        "account",
        "positions",
        "orders",
        "trades",
        "instruments",
        "margin_rate",
        "commission_rate",
    )
    first_result = None
    for index, request_type in enumerate(request_types):
        result = issue_query(client, request_type)
        certificate_builder.add(result)
        if first_result is None:
            first_result = result
        if index < len(request_types) - 1:
            # The SDK's default 1.05 second query interval yields 6.3 seconds
            # across the six gaps in this serial seven-query sequence.
            clock[0] += 1.05

    assert first_result is not None
    assert clock[0] - first_result.query_source.completed_monotonic == pytest.approx(6.3)
    certificate = certificate_builder.finish()
    public = certificate.as_public_dict()
    assert public["complete"] is True
    assert public["atomic_snapshot"] is False
    assert public["execution_authorized"] is False
    assert len(public["queries"]) == 7
    for query in public["queries"]:
        completed = datetime.fromisoformat(query["completed_at_utc"])
        expires = datetime.fromisoformat(query["expires_at_utc"])
        assert (expires - completed).total_seconds() == _QUERY_EVIDENCE_MAX_TTL_SECONDS


def test_near_timeout_seven_query_sequence_completes_within_bounded_ttl(monkeypatch):
    client = offline_client()
    clock = [100.0]
    patch_monotonic_and_utc_clock(monkeypatch, clock)
    certificate_builder = builder(client)
    request_types = (
        "account",
        "positions",
        "orders",
        "trades",
        "instruments",
        "margin_rate",
        "commission_rate",
    )
    first_result = None
    for request_type in request_types:
        result = issue_query(
            client,
            request_type,
            advance_before_terminal=lambda: clock.__setitem__(0, clock[0] + 4.999),
        )
        certificate_builder.add(result)
        if first_result is None:
            first_result = result

    assert first_result is not None
    age_at_finish = clock[0] - first_result.query_source.completed_monotonic
    assert age_at_finish == pytest.approx(6 * 4.999)
    assert age_at_finish < _QUERY_EVIDENCE_MAX_TTL_SECONDS
    certificate = certificate_builder.finish()
    assert certificate.as_public_dict()["complete"] is True


def test_sequence_older_than_issuer_ttl_is_rejected_even_when_each_add_is_fresh(
    monkeypatch,
):
    client = offline_client()
    clock = [100.0]
    patch_monotonic_and_utc_clock(monkeypatch, clock)
    certificate_builder = builder(client)
    request_types = (
        "account",
        "positions",
        "orders",
        "trades",
        "instruments",
        "margin_rate",
        "commission_rate",
    )
    first_expiry = None
    for index, request_type in enumerate(request_types):
        result = issue_query(client, request_type)
        certificate_builder.add(result)
        if index == 0:
            first_expiry = result.query_source.trusted_expires_monotonic
        if index < len(request_types) - 1:
            clock[0] += 6.0

    assert first_expiry is not None
    assert clock[0] > first_expiry
    with pytest.raises(
        CtpNativeQueryCertificateError,
        match="query_expired_before_certificate",
    ):
        certificate_builder.finish()


def test_late_callback_after_add_invalidates_certificate_at_finish():
    client = offline_client()
    certificate_builder = builder(client)
    queries = issue_all(client)
    add_all(certificate_builder, queries)
    client._handle_query_callback("account", None, None, queries["account"].request_id, True)
    assert client.get_query_result(queries["account"].request_id).late_callback_count == 1

    with pytest.raises(CtpNativeQueryCertificateError, match="query_late_callback"):
        certificate_builder.finish()


def test_session_change_during_final_readback_blocks_certificate(monkeypatch):
    client = offline_client()
    certificate_builder = builder(client)
    queries = issue_all(client)
    add_all(certificate_builder, queries)
    original_get_query_result = client.get_query_result
    original_get_query_session_scope = client.get_query_session_scope
    changed_scope = offline_client().get_query_session_scope()
    changed = False

    def change_session_after_read(request_id):
        nonlocal changed
        result = original_get_query_result(request_id)
        changed = True
        return result

    def get_scope_after_readback():
        if changed:
            return changed_scope
        return original_get_query_session_scope()

    monkeypatch.setattr(client, "get_query_result", change_session_after_read)
    monkeypatch.setattr(client, "get_query_session_scope", get_scope_after_readback)
    with pytest.raises(CtpNativeQueryCertificateError, match="query_session_changed"):
        certificate_builder.finish()


def test_payload_mutation_after_add_invalidates_certificate_at_finish():
    client = offline_client()
    certificate_builder = builder(client)
    queries = issue_all(client)
    add_all(certificate_builder, queries)
    queries["account"].records[0]["AccountID"] = "changed-after-capture"

    with pytest.raises(CtpNativeQueryCertificateError, match="query_current_result_mismatch"):
        certificate_builder.finish()
