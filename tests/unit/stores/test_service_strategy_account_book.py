"""Contract checks for explicitly bound strategy account-book projections."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bt_api_py.service_account_book_client import STRATEGY_ACCOUNT_BOOKS_OPERATION

from backtrader.service.service_strategy_account_book import (
    ServiceStrategyAccountBookError,
    ServiceStrategyAccountBookView,
)

_ACCOUNT = "account.synthetic"
_ACCOUNT_KEY = "execution-account-a"
_STRATEGY = "strategy.synthetic"
_INSTRUMENT = "BTC-USDT"


def _reply(*, complete=True, owner_ref=_STRATEGY, view="OWNER_BOOK", books=None, financial=None):
    result = {
        "view": view,
        "owner_kind": "STRATEGY",
        "owner_ref": owner_ref,
        "coverage": {
            "account_key": _ACCOUNT_KEY,
            "complete": complete,
            "scope_directory_revision": "owners-r1",
            "journal_generation": "journal-r1",
            "baseline_execution_cursor": 2,
            "current_execution_cursor": 4,
        },
        "books": books
        if books is not None
        else [
            {
                "owner_kind": "STRATEGY",
                "owner_ref": _STRATEGY,
                "current_positions": [{"instrument": _INSTRUMENT, "net_quantity": "1.25"}],
                "fees_since_baseline": [{"currency": "USDT", "amount": "0.04"}],
            }
        ],
    }
    if financial is not None:
        result["financial"] = financial
    return {
        "ok": True,
        "code": "OK",
        "result": result,
    }


def _financial_projection(
    *,
    owner_ref=_STRATEGY,
    account_key=_ACCOUNT_KEY,
    available=True,
    complete=True,
    cost_basis_complete=True,
    quantity="1.25",
    cost_basis="125000",
    cost_currency="USDT",
    cash=None,
    fees=None,
    cost_positions=None,
    journal_generation="journal-r1",
    execution_cursor=4,
):
    if not available:
        return {
            "available": False,
            "code": "PERSISTED_PROJECTION_UNAVAILABLE",
            "freshness": "NOT_ESTABLISHED",
            "cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
        }
    ledger_cut = {
        "account_key": account_key,
        "owner_directory_revision": "financial-owners-r1",
        "captured_at_ns": 400,
        "watermarks": [
            {
                "source_kind": "execution_outbox",
                "source_ref": "sqlite-execution-outbox",
                "generation": journal_generation,
                "cursor": execution_cursor,
                "as_of_ns": 300,
            },
            {
                "source_kind": "account_facts",
                "source_ref": "provider-facts-source",
                "generation": "provider-facts-r1",
                "cursor": 4,
                "as_of_ns": 300,
            },
            {
                "source_kind": "account_activity",
                "source_ref": "provider-activity-source",
                "generation": "provider-activity-r1",
                "cursor": 2,
                "as_of_ns": 300,
            },
        ],
    }
    return {
        "available": True,
        "source": "PERSISTED_EXECUTION_FINANCIAL_PROJECTION",
        "freshness": "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED",
        "cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
        "complete": complete,
        "ledger_cut": ledger_cut,
        "view": "OWNER_BOOK",
        "owner_kind": "STRATEGY",
        "owner_ref": owner_ref,
        "books": [
            {
                "owner": {
                    "kind": "STRATEGY",
                    "owner_ref": owner_ref,
                    "execution_scope_key": "scope-strategy-a",
                },
                "ledger_cut": ledger_cut,
                "cash": cash if cash is not None else [{"currency": "USDT", "amount": "1000"}],
                "positions": cost_positions
                if cost_positions is not None
                else [
                    {
                        "instrument": _INSTRUMENT,
                        "quantity": quantity,
                        "cost_basis": cost_basis,
                        "cost_currency": cost_currency,
                        "cost_method": "AVERAGE_COST",
                        "product_model": "SPOT",
                        "metadata_version": "synthetic-spot-v1",
                    }
                ],
                "cumulative_fees": (
                    fees if fees is not None else [{"currency": "USDT", "amount": "0.25"}]
                ),
                "cost_basis_complete": cost_basis_complete,
            }
        ],
    }


class _Runtime:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def call(self, mount, operation, arguments, *, scope_ref):
        self.calls.append((mount, operation, dict(arguments), scope_ref))
        return self.reply


def _view(reply=None):
    runtime = _Runtime(_reply() if reply is None else reply)
    view = ServiceStrategyAccountBookView(
        runtime,
        mount="broker.order_query",
        scope_ref="strategy-query-r1",
        strategy_ref=_STRATEGY,
        account_ref=_ACCOUNT,
    )
    return view, runtime
