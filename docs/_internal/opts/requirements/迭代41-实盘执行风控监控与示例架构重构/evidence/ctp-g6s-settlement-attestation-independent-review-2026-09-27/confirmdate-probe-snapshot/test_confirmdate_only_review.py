import pytest

from settlement_attestation import SettlementAttestationError
from test_settlement_attestation import (
    BROKER, DAY, INVESTOR, _attest, _query, _scope, _session,
)


def _native_shaped_query(scope, current, *, request_filters=True):
    row = {"BrokerID": BROKER, "InvestorID": INVESTOR, "ConfirmDate": DAY}
    query = _query(scope, current, records=(row,))
    assert "TradingDay" not in query.records[0]
    assert query.records[0]["ConfirmDate"] == current.trading_day
    if not request_filters:
        from dataclasses import replace

        query = replace(query, source=replace(query.source, request_filters=()))
    return query


def test_confirmdate_only_native_shaped_row_attests_in_fake_positive_control():
    scope = _scope()
    current = _session(scope)
    query = _native_shaped_query(scope, current)
    result = _attest(query=query, scope=scope, current=current)
    assert result.settlement_confirmation_observed is True
    assert result.query_terminal_provenance_verified is True
    assert result.settlement_confirm_write_calls == 0
    assert result.order_insert_write_calls == 0
    assert result.order_action_write_calls == 0


def test_confirmdate_only_correct_looking_row_without_request_filters_rejects_zero_writes():
    scope = _scope()
    current = _session(scope)
    query = _native_shaped_query(scope, current, request_filters=False)
    assert query.records == ({"BrokerID": BROKER, "InvestorID": INVESTOR, "ConfirmDate": DAY},)
    with pytest.raises(SettlementAttestationError):
        _attest(query=query, scope=scope, current=current)
    counts = dict(query.request_counts_after)
    assert counts["query_settlement_confirmation"] == 1
    assert counts["settlement_confirm"] == 0
    assert counts["order_insert"] == 0
    assert counts["order_action"] == 0
