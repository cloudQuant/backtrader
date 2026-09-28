"""Offline contracts for the externally owned CTP shared-session read port."""

from decimal import Decimal

import pytest

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from backtrader.stores.ctp_account_actor_port import (
    CtpQuoteReplyV1,
    CtpQuoteRequestV1,
    CtpReadPortContractError,
    CtpReadQueryKindV1,
    CtpReadQueryReplyV1,
    CtpReadQueryRequestV1,
    CtpReadQueryScopeV1,
    assess_ctp_shared_session_query,
    read_ctp_shared_session_quote,
)


class _FakeSharedSessionReadPort:
    """An in-memory protocol fake; it has no identity or admission authority."""

    def __init__(self, query_reply=None, quote_reply=None):
        self.query_reply = query_reply
        self.quote_reply = quote_reply
        self.calls = []

    def query_read_only(self, request):
        self.calls.append(("query", request))
        return self.query_reply

    def read_quote(self, request):
        self.calls.append(("quote", request))
        return self.quote_reply


class _AttributeTrap:
    def __init__(self):
        self.reads = []

    def __getattr__(self, name):
        self.reads.append(name)
        raise AssertionError("CTP admission read an injected client attribute")


def _position_request():
    return CtpReadQueryRequestV1(
        kind=CtpReadQueryKindV1.POSITIONS,
        correlation_id="r2d-position-1",
        scope=CtpReadQueryScopeV1("CZCE", "SA609", "20260909"),
        timeout_seconds=0.0,
    )


def _quote_request():
    return CtpQuoteRequestV1(
        correlation_id="r2d-quote-1",
        exchange_id="CZCE",
        instrument_id="SA609",
        timeout_seconds=0.0,
    )


def test_one_typed_port_instance_exposes_position_query_and_exact_quote_reads():
    position_request = _position_request()
    quote_request = _quote_request()
    port = _FakeSharedSessionReadPort(
        query_reply=CtpReadQueryReplyV1(
            kind=CtpReadQueryKindV1.POSITIONS,
            correlation_id=position_request.correlation_id,
            complete=True,
            terminal=True,
            timed_out=False,
            error_code=None,
            records=({"InstrumentID": "SA609", "Position": 0},),
        ),
        quote_reply=CtpQuoteReplyV1(
            correlation_id=quote_request.correlation_id,
            exchange_id="CZCE",
            instrument_id="SA609",
            sequence=9,
            observed_at_utc="2026-09-09T01:02:03+00:00",
            bid_price=Decimal("42.0"),
            ask_price=Decimal("42.5"),
            bid_volume=2,
            ask_volume=3,
        ),
    )

    positions = assess_ctp_shared_session_query(port, position_request)
    quote = read_ctp_shared_session_quote(port, quote_request)

    assert positions.complete is True
    assert positions.scope_valid is True
    assert positions.records[0]["InstrumentID"] == "SA609"
    assert not hasattr(positions, "account_fingerprint")
    assert not hasattr(positions, "session_generation")
    assert not hasattr(positions, "read_only_safe")
    with pytest.raises(TypeError):
        positions.records[0]["Position"] = 1
    assert quote.instrument_id == "SA609"
    assert quote.sequence == 9
    assert [(kind, request) for kind, request in port.calls] == [
        ("query", position_request),
        ("quote", quote_request),
    ]
    assert not any(callable(getattr(port, name, None)) for name in ("submit_order", "cancel_order"))


def test_quote_reply_must_echo_exact_scope_and_correlation():
    request = _quote_request()
    port = _FakeSharedSessionReadPort(
        quote_reply=CtpQuoteReplyV1(
            correlation_id=request.correlation_id,
            exchange_id="CZCE",
            instrument_id="SA701",
            sequence=10,
            observed_at_utc="2026-09-09T01:02:03+00:00",
            bid_price=Decimal("42.0"),
            ask_price=Decimal("42.5"),
            bid_volume=2,
            ask_volume=3,
        )
    )

    with pytest.raises(CtpReadPortContractError) as error:
        read_ctp_shared_session_quote(port, request)

    assert error.value.code == "quote_scope_mismatch"
    assert port.calls == [("quote", request)]


def test_typed_port_constructor_rejects_invalid_quote_and_query_shapes():
    with pytest.raises(ValueError, match="surrounding whitespace"):
        CtpReadQueryRequestV1(
            kind=CtpReadQueryKindV1.POSITIONS,
            correlation_id=" padded ",
            scope=CtpReadQueryScopeV1("CZCE", "SA609", "20260909"),
            timeout_seconds=0.0,
        )
    for field in ("correlation_id", "exchange_id", "instrument_id"):
        values = {
            "correlation_id": "quote",
            "exchange_id": "CZCE",
            "instrument_id": "SA609",
            "timeout_seconds": 0.0,
        }
        values[field] = " padded "
        with pytest.raises(ValueError, match="surrounding whitespace"):
            CtpQuoteRequestV1(**values)

    with pytest.raises(ValueError, match="timeout_seconds must be finite and nonnegative"):
        CtpReadQueryRequestV1(
            kind=CtpReadQueryKindV1.POSITIONS,
            correlation_id="position",
            scope=CtpReadQueryScopeV1("CZCE", "SA609", "20260909"),
            timeout_seconds=10**10000,
        )
    with pytest.raises(ValueError, match="timeout_seconds must be finite and nonnegative"):
        CtpQuoteRequestV1(
            correlation_id="quote",
            exchange_id="CZCE",
            instrument_id="SA609",
            timeout_seconds=10**10000,
        )

    with pytest.raises(ValueError, match="positive exact integer"):
        CtpQuoteReplyV1(
            correlation_id="quote",
            exchange_id="CZCE",
            instrument_id="SA609",
            sequence=True,
            observed_at_utc="2026-09-09T01:02:03+00:00",
            bid_price=Decimal("42.0"),
            ask_price=Decimal("42.5"),
            bid_volume=2,
            ask_volume=3,
        )
    with pytest.raises(ValueError, match="records must be a tuple"):
        CtpReadQueryReplyV1(
            kind=CtpReadQueryKindV1.POSITIONS,
            correlation_id="position",
            complete=True,
            terminal=True,
            timed_out=False,
            error_code=None,
            records=[],
        )


def test_read_only_port_cannot_authorize_default_ctp_store_construction(monkeypatch):
    port = _FakeSharedSessionReadPort()
    api = _AttributeTrap()
    resolutions = []

    def forbidden(*_args, **_kwargs):
        resolutions.append("provider-resolution")
        raise AssertionError("provider resolution ran before CTP fail-close")

    monkeypatch.setattr(BtApiStore, "_resolve_provider", forbidden)
    for actor_port in (None, port):
        with pytest.raises(BtApiStoreError, match="external account actor unavailable"):
            BtApiStore(provider="ctp", api=api, account_actor_port=actor_port)

    assert port.calls == []
    assert api.reads == []
    assert resolutions == []
