"""Synthetic sealed callback records through SDK -> guarded Gateway ledger."""

import json

import pytest
from bt_api_base.direct_cancel_protocol import PreparedCancelRequest
from bt_api_base.direct_write_protocol import NativeOrderIdentity
from bt_api_ctp.gateway_cancel_source import cancel_attempt_key, source_tags_digest
from bt_api_ctp.gateway_return_buffer import CtpGatewayReturnBuffer
from bt_api_gateway.direct_cancel_journal import GatewayDirectCancelJournal

from bt_api_py.ctp_gateway_return_ingestion import CtpGatewayReturnIngestionError
from bt_api_py.direct_write import project_direct_strong_identity_keys
from tests.integration.test_iter63_ctp_gateway_return_ingestion import (
    DAY,
    INSTRUMENT,
    _fact_count,
)

pytest_plugins = ("tests.integration.test_iter63_ctp_gateway_return_ingestion",)

TAGS = ("source", "client", "api", "spi", 1, 1)
SOURCE = "ctp-query-source-v1:" + "a" * 64
SOURCE_BINDING = {
    "schema": "ctp-cancel-source-v1",
    "source_ref": SOURCE,
    "source_tags_digest": source_tags_digest(TAGS),
    "login_request_id": 1,
}


def make_buffer():
    return CtpGatewayReturnBuffer(broker_id="9999", investor_id="account")


def create_original(journal):
    original = journal.reserve(
        "strategy-a",
        "key-a",
        "principal-a",
        {"symbol": "rb2701", "side": "buy", "offset": "open", "quantity": "2"},
    )
    target = NativeOrderIdentity(
        "CTP___FUTURE",
        "000000000001",
        {
            "trading_day": DAY,
            "order_ref": "000000000001",
            "front_id": 7,
            "session_id": 19,
            "exchange_id": "SHFE",
        },
        None,
    )
    wire = {
        "exchange_name": target.exchange_name,
        "client_order_id": target.client_order_id,
        "session_generation": None,
        "fields_json": json.dumps(dict(target.fields), sort_keys=True, separators=(",", ":")),
    }
    journal.begin_dispatch(
        "strategy-a",
        "key-a",
        original.reservation_id,
        original.digest,
        "principal-a",
        original.version,
        wire,
        project_direct_strong_identity_keys(target, day_scoped_ids=True),
    )
    return original


def create_cancel(journal, original, operation, number, *, legacy=False, dispatch=None):
    target = NativeOrderIdentity(
        "CTP___FUTURE",
        "000000000001",
        {
            "trading_day": DAY,
            "order_ref": "000000000001",
            "front_id": 7,
            "session_id": 19,
            "exchange_id": "SHFE",
        },
        None,
    )
    fields = {
        "BrokerID": "9999",
        "InvestorID": "account",
        "InstrumentID": "rb2701",
        "ExchangeID": "SHFE",
        "ActionFlag": "0",
        "RequestID": number,
        "OrderActionRef": number,
        "OrderRef": "000000000001",
        "FrontID": 7,
        "SessionID": 19,
        "OrderSysID": "",
        "DispatchFrontID": 7,
        "DispatchSessionID": 19,
    }
    key = cancel_attempt_key(
        broker="9999",
        investor="account",
        day=DAY,
        front=7,
        session=19,
        request_id=number,
        action_ref=number,
        source_binding=SOURCE_BINDING,
    )
    prepared = PreparedCancelRequest(
        "prep-" + operation,
        target,
        "rb2701",
        DAY,
        1,
        fields,
        (key,),
        None if legacy else SOURCE_BINDING,
    )
    cancel = GatewayDirectCancelJournal(journal)
    row = cancel.request(
        "strategy-a",
        operation,
        "principal-a",
        "key-a",
        original.reservation_id,
        original.digest,
        target_identity=target,
        symbol="rb2701",
    )
    attempt = (
        cancel.begin_dispatch("strategy-a", operation, "principal-a", row.version, prepared).record
        if dispatch is None
        else dispatch(row, prepared)
    )
    return attempt, fields


def append_error(buffer, fields, *, kind="action_response", code=7, **changes):
    row = {k: v for k, v in fields.items() if not k.startswith("Dispatch")}
    row.update(changes)
    number = fields["RequestID"]
    assert buffer._append(
        kind=kind,
        row=row,
        source_ref=SOURCE,
        source_tags=TAGS,
        connection_generation=1,
        reception_trading_day=DAY,
        front_id=7,
        session_id=19,
        request_id=number if kind == "action_response" else None,
        is_last=True if kind == "action_response" else None,
        error_code=code,
        login_request_id=1,
    )


def assert_offered(buffer, record):
    if not buffer._contains_record(record):
        raise RuntimeError("stale ticket")


def test_two_cancel_errors_same_order_same_code_remain_distinct_and_replay(system):
    ingestor, _, _, _, journal, ledger = system
    original = create_original(journal)
    first, f1 = create_cancel(journal, original, "cancel-one", 11)
    second, f2 = create_cancel(journal, original, "cancel-two", 12)
    buffer = make_buffer()
    append_error(buffer, f1)
    append_error(buffer, f1, kind="action_error")
    append_error(buffer, f2, kind="action_error")
    batch = buffer.offer()
    assert ingestor.ingest_callbacks(batch, assert_current=lambda r: assert_offered(buffer, r)) == 3
    assert ingestor.ingest_callbacks(batch, assert_current=lambda r: assert_offered(buffer, r)) == 3
    events = ledger.read_events("strategy-a", after_sequence=0, limit=10)
    assert len(events) == 2
    assert [
        (e.cancel_attribution.operation_id, e.cancel_attribution.attempt_id) for e in events
    ] == [
        (first.operation_id, first.attempt_id),
        (second.operation_id, second.attempt_id),
    ]
    assert events[0].fact_digest != events[1].fact_digest
    assert ledger.position("strategy-a", INSTRUMENT) is None
    assert journal.get("strategy-a", "key-a", "principal-a").status == "DISPATCHING"
    buffer.ack(batch)


def test_batch_projection_failure_precedes_all_writes_and_does_not_ack(system):
    ingestor, _, _, _, journal, _ = system
    original = create_original(journal)
    _, fields = create_cancel(journal, original, "one", 11)
    buffer = make_buffer()
    append_error(buffer, fields)
    append_error(buffer, fields, InstrumentID="other")
    batch = buffer.offer()
    with pytest.raises(CtpGatewayReturnIngestionError, match="PROJECTION_FAILED"):
        ingestor.ingest_callbacks(batch, assert_current=lambda r: assert_offered(buffer, r))
    assert _fact_count(journal) == 0
    assert buffer.offer() is batch and buffer.status().record_count == 2


@pytest.mark.parametrize("kind,code", [("action_response", 0), ("insert_response", 1)])
def test_unsupported_success_or_insert_does_not_ack(system, kind, code):
    ingestor, _, _, _, journal, _ = system
    original = create_original(journal)
    _, fields = create_cancel(journal, original, "one", 11)
    buffer = make_buffer()
    append_error(buffer, fields, kind=kind, code=code)
    batch = buffer.offer()
    with pytest.raises(CtpGatewayReturnIngestionError, match="UNSUPPORTED_RETURN"):
        ingestor.ingest_callbacks(batch, assert_current=lambda r: assert_offered(buffer, r))
    assert _fact_count(journal) == 0 and buffer.offer() is batch


def test_stale_source_in_commit_rolls_back_and_keeps_ticket(system):
    ingestor, _, _, _, journal, _ = system
    original = create_original(journal)
    _, fields = create_cancel(journal, original, "one", 11)
    buffer = make_buffer()
    append_error(buffer, fields)
    batch = buffer.offer()
    calls = 0

    def current(record):
        nonlocal calls
        assert_offered(buffer, record)
        calls += 1
        if calls == 3:
            raise RuntimeError("synthetic source change")

    with pytest.raises(CtpGatewayReturnIngestionError, match="SOURCE_STALE") as exc:
        ingestor.ingest_callbacks(batch, assert_current=current)
    assert exc.value.completed_count == 0 and not exc.value.in_flight_may_have_committed
    assert _fact_count(journal) == 0 and buffer.offer() is batch


def test_legacy_prepared_cancel_is_explicitly_unsupported(system):
    ingestor, _, _, _, journal, _ = system
    original = create_original(journal)
    _, fields = create_cancel(journal, original, "legacy", 11, legacy=True)
    buffer = make_buffer()
    append_error(buffer, fields)
    batch = buffer.offer()
    with pytest.raises(CtpGatewayReturnIngestionError, match="UNSUPPORTED_RETURN"):
        ingestor.ingest_callbacks(
            batch, assert_current=lambda record: assert_offered(buffer, record)
        )
    assert _fact_count(journal) == 0 and buffer.offer() is batch


def test_unknown_cancel_request_key_does_not_mutate_or_ack(system):
    ingestor, _, _, _, journal, _ = system
    original = create_original(journal)
    _, fields = create_cancel(journal, original, "one", 11)
    buffer = make_buffer()
    fields = dict(fields, RequestID=12, OrderActionRef=12)
    append_error(buffer, fields)
    batch = buffer.offer()
    with pytest.raises(CtpGatewayReturnIngestionError, match="PROJECTION_FAILED"):
        ingestor.ingest_callbacks(
            batch, assert_current=lambda record: assert_offered(buffer, record)
        )
    assert _fact_count(journal) == 0 and buffer.offer() is batch


def test_lost_second_commit_reports_prefix_then_replay_is_idempotent(system, monkeypatch):
    from bt_api_gateway.direct_execution_journal import GatewayDirectExecutionLedger

    ingestor, _, _, _, journal, ledger = system
    original = create_original(journal)
    _, first = create_cancel(journal, original, "one", 11)
    _, second = create_cancel(journal, original, "two", 12)
    buffer = make_buffer()
    append_error(buffer, first)
    append_error(buffer, second)
    batch = buffer.offer()
    ingest = GatewayDirectExecutionLedger.ingest_cancel_error
    calls = []

    def lose_second_reply(self, *args, **kwargs):
        result = ingest(self, *args, **kwargs)
        calls.append(1)
        if len(calls) == 2:
            raise OSError("synthetic post-commit failure")
        return result

    monkeypatch.setattr(GatewayDirectExecutionLedger, "ingest_cancel_error", lose_second_reply)
    with pytest.raises(CtpGatewayReturnIngestionError, match="INGEST_FAILED") as exc:
        ingestor.ingest_callbacks(
            batch, assert_current=lambda record: assert_offered(buffer, record)
        )
    assert exc.value.completed_count == 1 and exc.value.in_flight_may_have_committed
    assert buffer.offer() is batch and _fact_count(journal) == 2
    monkeypatch.setattr(GatewayDirectExecutionLedger, "ingest_cancel_error", ingest)
    assert (
        ingestor.ingest_callbacks(
            batch, assert_current=lambda record: assert_offered(buffer, record)
        )
        == 2
    )
    assert _fact_count(journal) == 2
    assert len(ledger.read_events("strategy-a", after_sequence=0, limit=10)) == 2
