"""Strategy valuation requires a coherent financial and position cut."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import runpy

import pytest

from bt_api_base.account_book_protocol import (
    StrategyAccountBookSnapshot,
    StrategyFinancialLedgerCut,
    StrategyFinancialWatermark,
    StrategyPositionCost,
    parse_strategy_account_book_reply,
)
from backtrader.service.service_strategy_account_book import (
    ServiceStrategyAccountBookError,
    value_strategy_book,
)


ACCOUNT = "account-test"
INSTRUMENT = "BTC-USDT"


def _direct_snapshot():
    cut = StrategyFinancialLedgerCut(
        account_key=ACCOUNT,
        owner_directory_revision="strategy-ledger.v2",
        captured_at_ns=100,
        watermarks=(
            StrategyFinancialWatermark("execution_outbox", ACCOUNT, "generation-1", 4, 90),
            StrategyFinancialWatermark("account_facts", "position-source", "generation-1", 3, 90),
            StrategyFinancialWatermark("account_activity", ACCOUNT, "generation-1", 2, 90),
        ),
    )
    return StrategyAccountBookSnapshot(
        strategy_ref="strategy-a",
        account_ref=ACCOUNT,
        scope_directory_revision="strategy-ledger.v2",
        journal_generation="generation-1",
        baseline_execution_cursor=0,
        current_execution_cursor=4,
        positions={INSTRUMENT: Decimal("2")},
        fees_since_baseline={},
        cash_by_currency={"USDT": Decimal("100")},
        position_costs={
            INSTRUMENT: StrategyPositionCost(
                quantity=Decimal("2"),
                cost_basis=Decimal("20"),
                cost_currency="USDT",
                product_model="spot",
                metadata_version="instrument-terms.v1:spot:USDT:1",
                average_cost=Decimal("10"),
            )
        },
        financial_available=True,
        cost_basis_complete=True,
        financial_error_code="",
        financial_source="strategy-ledger.v2:strategy_cash_spot.v1",
        financial_freshness="RECONCILED_IN_SNAPSHOT",
        financial_cut_relationship="SAME_TRANSACTION",
        financial_ledger_cut=cut,
        account_key=ACCOUNT,
    )


def _value(snapshot):
    # Synthetic marks exercise the arithmetic only; they do not establish
    # provider provenance or authorize live trading.
    return value_strategy_book(
        snapshot,
        marks={INSTRUMENT: Decimal("12")},
        multipliers={INSTRUMENT: Decimal("1")},
    )


def test_direct_same_transaction_cut_is_valued():
    value = _value(_direct_snapshot())
    assert value.equity == Decimal("124")
    assert value.values[INSTRUMENT] == Decimal("24")


@pytest.mark.parametrize(
    "changes",
    [
        {"financial_cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT"},
        {"financial_freshness": "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED"},
        {"account_key": "another-account"},
        {"scope_directory_revision": "another-directory"},
        {"journal_generation": "another-generation"},
        {"current_execution_cursor": 5},
    ],
)
def test_direct_cut_mismatches_do_not_value(changes):
    snapshot = replace(_direct_snapshot(), **changes)
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_FINANCIAL_CUT_UNVERIFIED"):
        _value(snapshot)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_ref": "another-account"},
        {"generation": "another-generation"},
        {"cursor": 3},
    ],
)
def test_execution_watermark_mismatches_do_not_value(changes):
    snapshot = _direct_snapshot()
    cut = snapshot.financial_ledger_cut
    execution = replace(cut.watermarks[0], **changes)
    mismatched = replace(cut, watermarks=(execution, *cut.watermarks[1:]))
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_FINANCIAL_CUT_UNVERIFIED"):
        _value(replace(snapshot, financial_ledger_cut=mismatched))


def test_service_independent_cut_is_not_upgraded_by_matching_costs_and_terms():
    fixtures = runpy.run_path(str(Path(__file__).with_name("test_service_strategy_account_book.py")))
    financial = fixtures["_financial_projection"]()
    financial["books"][0]["positions"][0]["metadata_version"] = (
        "instrument-terms.v1:spot:USDT:1"
    )
    reply = fixtures["_reply"](financial=financial)
    snapshot = parse_strategy_account_book_reply(
        reply, strategy_ref="strategy.synthetic", account_ref="account.synthetic"
    )
    assert snapshot.position_costs[INSTRUMENT].metadata_version == (
        "instrument-terms.v1:spot:USDT:1"
    )
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_FINANCIAL_CUT_UNVERIFIED"):
        _value(snapshot)


def test_service_independent_cut_does_not_become_equity_when_flat():
    fixtures = runpy.run_path(str(Path(__file__).with_name("test_service_strategy_account_book.py")))
    financial = fixtures["_financial_projection"](cost_positions=[])
    books = [{"owner_kind": "STRATEGY", "owner_ref": "strategy.synthetic",
              "current_positions": [], "fees_since_baseline": []}]
    reply = fixtures["_reply"](financial=financial, books=books)
    snapshot = parse_strategy_account_book_reply(
        reply, strategy_ref="strategy.synthetic", account_ref="account.synthetic"
    )
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_FINANCIAL_CUT_UNVERIFIED"):
        _value(snapshot)
