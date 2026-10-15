"""Contract checks for explicitly bound strategy account-book projections."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backtrader.stores.service_strategy_account_book import (
    STRATEGY_ACCOUNT_BOOKS_OPERATION,
    ServiceStrategyAccountBookError,
    ServiceStrategyAccountBookView,
)

_ACCOUNT = "account.synthetic"
_STRATEGY = "strategy.synthetic"
_INSTRUMENT = "BTC-USDT"


def _reply(*, complete=True, owner_ref=_STRATEGY, view="OWNER_BOOK", books=None):
    return {
        "ok": True,
        "code": "OK",
        "result": {
            "view": view,
            "owner_kind": "STRATEGY",
            "owner_ref": owner_ref,
            "coverage": {
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
        },
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


def test_explicit_strategy_view_returns_auditable_net_quantity_without_cost_basis():
    view, runtime = _view()

    snapshot = view.snapshot()
    position = view.getposition(_INSTRUMENT)

    assert snapshot.strategy_ref == _STRATEGY
    assert snapshot.account_ref == _ACCOUNT
    assert snapshot.scope_directory_revision == "owners-r1"
    assert snapshot.journal_generation == "journal-r1"
    assert (snapshot.baseline_execution_cursor, snapshot.current_execution_cursor) == (2, 4)
    assert snapshot.positions == {_INSTRUMENT: Decimal("1.25")}
    assert snapshot.fees_since_baseline == {"USDT": Decimal("0.04")}
    assert position.size == pytest.approx(1.25)
    assert position.price is None
    assert runtime.calls == [
        ("broker.order_query", STRATEGY_ACCOUNT_BOOKS_OPERATION, {}, "strategy-query-r1"),
        ("broker.order_query", STRATEGY_ACCOUNT_BOOKS_OPERATION, {}, "strategy-query-r1"),
    ]


def test_complete_owner_view_treats_an_omitted_instrument_as_flat():
    reply = _reply(
        books=[
            {
                "owner_kind": "STRATEGY",
                "owner_ref": _STRATEGY,
                "current_positions": [],
                "fees_since_baseline": [],
            }
        ]
    )
    view, _runtime = _view(reply)

    position = view.getposition(_INSTRUMENT)

    assert position.size == 0.0
    assert position.price == 0.0


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (_reply(complete=False), "STRATEGY_BOOK_COVERAGE_INCOMPLETE"),
        (_reply(owner_ref="strategy.other"), "OWNER_BINDING_MISMATCH"),
        (_reply(view="ACCOUNT"), "OWNER_BINDING_MISMATCH"),
        (
            _reply(
                books=[
                    {"owner_kind": "STRATEGY", "owner_ref": _STRATEGY,
                     "current_positions": [], "fees_since_baseline": []},
                    {"owner_kind": "STRATEGY", "owner_ref": _STRATEGY,
                     "current_positions": [], "fees_since_baseline": []},
                ]
            ),
            "OWNER_BOOK_AMBIGUOUS",
        ),
    ],
)
def test_non_owner_or_incomplete_service_projection_is_rejected(reply, code):
    view, _runtime = _view(reply)

    with pytest.raises(ServiceStrategyAccountBookError) as error:
        view.snapshot()

    assert error.value.code == code


def test_strategy_cash_and_value_are_explicitly_unavailable_without_rpc():
    view, runtime = _view()

    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_CASH_UNAVAILABLE"):
        view.getcash()
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_VALUE_UNAVAILABLE"):
        view.getvalue()

    assert runtime.calls == []
