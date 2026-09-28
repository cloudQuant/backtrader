"""SDK-free regression tests for mandatory native query row scope."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backtrader_runtime.ctp_simulation_execution import CtpSimulationExecutionError
from backtrader_runtime.ctp_simulation_query_evidence import (
    CtpTraderClientQueryEvidenceVerifier,
)


BROKER_ID = "9999"
INVESTOR_ID = "offline-user"
TRADING_DAY = "20260923"


@pytest.mark.parametrize("query_kind", ("orders", "trades", "positions"))
def test_native_query_row_scope_accepts_complete_native_fields(query_kind: str) -> None:
    scope = SimpleNamespace(
        broker_id=BROKER_ID,
        investor_id=INVESTOR_ID,
        trading_day=TRADING_DAY,
    )
    native_row = {
        "BrokerID": BROKER_ID,
        "InvestorID": INVESTOR_ID,
        "TradingDay": TRADING_DAY,
    }

    CtpTraderClientQueryEvidenceVerifier._validate_row_scope(
        native_row, scope, query_kind=query_kind
    )


@pytest.mark.parametrize(
    "query_kind,missing_field",
    tuple(
        (query_kind, field)
        for query_kind in ("orders", "trades", "positions")
        for field in ("BrokerID", "InvestorID", "TradingDay")
    ),
)
def test_native_query_row_scope_rejects_each_missing_identity_field(
    query_kind: str,
    missing_field: str,
) -> None:
    scope = SimpleNamespace(
        broker_id=BROKER_ID,
        investor_id=INVESTOR_ID,
        trading_day=TRADING_DAY,
    )
    native_row = {
        "BrokerID": BROKER_ID,
        "InvestorID": INVESTOR_ID,
        "TradingDay": TRADING_DAY,
    }
    del native_row[missing_field]

    with pytest.raises(CtpSimulationExecutionError) as exc_info:
        CtpTraderClientQueryEvidenceVerifier._validate_row_scope(
            native_row, scope, query_kind=query_kind
        )

    assert exc_info.value.reason == "native_query_row_scope_mismatch"


def test_native_query_row_scope_rejects_explicitly_empty_identity_field() -> None:
    scope = SimpleNamespace(
        broker_id=BROKER_ID,
        investor_id=INVESTOR_ID,
        trading_day=TRADING_DAY,
    )
    native_row = {
        "BrokerID": BROKER_ID,
        "InvestorID": INVESTOR_ID,
        "TradingDay": "",
    }

    with pytest.raises(CtpSimulationExecutionError) as exc_info:
        CtpTraderClientQueryEvidenceVerifier._validate_row_scope(
            native_row, scope, query_kind="positions"
        )

    assert exc_info.value.reason == "native_query_row_scope_mismatch"


def test_native_query_row_scope_rejects_unmapped_native_query_kind() -> None:
    scope = SimpleNamespace(
        broker_id=BROKER_ID,
        investor_id=INVESTOR_ID,
        trading_day=TRADING_DAY,
    )
    with pytest.raises(CtpSimulationExecutionError) as exc_info:
        CtpTraderClientQueryEvidenceVerifier._validate_row_scope(
            {"BrokerID": BROKER_ID}, scope, query_kind="settlement_confirmation"
        )
    assert exc_info.value.reason == "native_query_row_scope_kind_unsupported"
