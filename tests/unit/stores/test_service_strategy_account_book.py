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


def test_strategy_view_projects_owner_cash_cost_basis_and_cumulative_fees():
    view, runtime = _view(_reply(financial=_financial_projection()))

    snapshot = view.snapshot()
    position = view.getposition(_INSTRUMENT)
    cash = view.getcash(currency="USDT")

    assert snapshot.positions == {_INSTRUMENT: Decimal("1.25")}
    assert snapshot.fees_since_baseline == {"USDT": Decimal("0.04")}
    assert snapshot.financial_available is True
    assert snapshot.cost_basis_complete is True
    assert snapshot.cash_by_currency == {"USDT": Decimal("1000")}
    assert snapshot.cumulative_fees_by_currency == {"USDT": Decimal("0.25")}
    assert snapshot.financial_source == "PERSISTED_EXECUTION_FINANCIAL_PROJECTION"
    assert snapshot.financial_freshness == "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED"
    assert snapshot.financial_cut_relationship == "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT"
    assert snapshot.financial_ledger_cut is not None
    assert snapshot.financial_ledger_cut.account_key == "execution-account-a"
    assert snapshot.financial_ledger_cut.watermarks[0].cursor == 4
    assert snapshot.position_costs[_INSTRUMENT].quantity == Decimal("1.25")
    assert snapshot.position_costs[_INSTRUMENT].cost_basis == Decimal("125000")
    assert snapshot.position_costs[_INSTRUMENT].cost_currency == "USDT"
    assert snapshot.position_costs[_INSTRUMENT].product_model == "SPOT"
    assert snapshot.position_costs[_INSTRUMENT].metadata_version == "synthetic-spot-v1"
    assert snapshot.position_costs[_INSTRUMENT].average_cost == Decimal("100000")
    assert position.size == pytest.approx(1.25)
    assert position.price == pytest.approx(100000.0)
    assert cash == Decimal("1000")
    assert len(runtime.calls) == 3


def test_strategy_cash_requires_explicit_currency_and_reads_only_owner_book():
    view, runtime = _view(_reply(financial=_financial_projection()))

    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_CASH_CURRENCY_REQUIRED"):
        view.getcash()
    assert runtime.calls == []
    assert view.getcash(currency="USDT") == Decimal("1000")
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_CASH_UNAVAILABLE"):
        view.getcash(currency="USD")
    assert len(runtime.calls) == 2


def test_financial_projection_unavailable_keeps_net_position_without_cost_price():
    view, _runtime = _view(_reply(financial=_financial_projection(available=False)))

    position = view.getposition(_INSTRUMENT)

    assert position.size == pytest.approx(1.25)
    assert position.price is None
    with pytest.raises(ServiceStrategyAccountBookError, match="PERSISTED_PROJECTION_UNAVAILABLE"):
        view.getcash(currency="USDT")


def test_incomplete_cost_basis_does_not_create_an_average_price():
    view, _runtime = _view(
        _reply(
            financial=_financial_projection(
                cost_basis_complete=False, cost_basis=None, cost_currency=None
            )
        )
    )

    position = view.getposition(_INSTRUMENT)

    assert position.size == pytest.approx(1.25)
    assert position.price is None


def test_financial_cut_mismatch_is_unavailable_without_changing_legacy_quantity():
    view, _runtime = _view(_reply(financial=_financial_projection(execution_cursor=3)))

    snapshot = view.snapshot()
    position = view.getposition(_INSTRUMENT)

    assert snapshot.financial_available is False
    assert snapshot.financial_error_code == "STRATEGY_FINANCIAL_CUT_MISMATCH"
    assert snapshot.positions[_INSTRUMENT] == Decimal("1.25")
    assert position.size == pytest.approx(1.25)
    assert position.price is None


def test_financial_account_mismatch_is_unavailable_for_same_strategy_and_cursor():
    reply = _reply(financial=_financial_projection(account_key="execution-account-b"))
    view, _runtime = _view(reply)

    snapshot = view.snapshot()

    assert snapshot.strategy_ref == _STRATEGY
    assert snapshot.journal_generation == "journal-r1"
    assert snapshot.current_execution_cursor == 4
    assert snapshot.financial_available is False
    assert snapshot.financial_error_code == "STRATEGY_FINANCIAL_ACCOUNT_MISMATCH"
    assert snapshot.positions[_INSTRUMENT] == Decimal("1.25")
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_FINANCIAL_ACCOUNT_MISMATCH"):
        view.getcash(currency="USDT")


def test_missing_legacy_account_key_disables_only_the_financial_projection():
    reply = _reply(financial=_financial_projection())
    del reply["result"]["coverage"]["account_key"]
    view, _runtime = _view(reply)

    snapshot = view.snapshot()
    position = view.getposition(_INSTRUMENT)

    assert snapshot.financial_available is False
    assert snapshot.financial_error_code == "STRATEGY_FINANCIAL_ACCOUNT_KEY_UNAVAILABLE"
    assert snapshot.positions[_INSTRUMENT] == Decimal("1.25")
    assert position.size == pytest.approx(1.25)
    assert position.price is None


@pytest.mark.parametrize(
    "financial_projection",
    [
        _financial_projection(cost_basis=None, cost_currency=None),
        _financial_projection(cost_positions=[]),
    ],
    ids=("unknown-cost-basis", "missing-owner-cost-row"),
)
def test_incomplete_owner_cost_rows_downgrade_cost_completeness_but_keep_cash(
    financial_projection,
):
    view, _runtime = _view(_reply(financial=financial_projection))

    snapshot = view.snapshot()

    assert snapshot.financial_available is True
    assert snapshot.cost_basis_complete is False
    assert snapshot.cash_by_currency == {"USDT": Decimal("1000")}
    assert view.getposition(_INSTRUMENT).price is None
    assert view.getcash(currency="USDT") == Decimal("1000")


def test_position_cost_quantity_must_match_the_legacy_owner_projection():
    reply = _reply(financial=_financial_projection(quantity="1.5"))
    view, _runtime = _view(reply)

    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_POSITION_COST_MISMATCH"):
        view.getposition(_INSTRUMENT)


def test_owner_book_must_share_its_own_exact_financial_cut():
    reply = _reply(financial=_financial_projection())
    owner_book = reply["result"]["financial"]["books"][0]
    owner_book["ledger_cut"] = {"different": "independent but not the advertised cut"}
    view, _runtime = _view(reply)

    snapshot = view.snapshot()

    assert snapshot.financial_available is False
    assert snapshot.financial_error_code == "STRATEGY_FINANCIAL_CUT_MISMATCH"
    assert snapshot.positions[_INSTRUMENT] == Decimal("1.25")


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
                    {
                        "owner_kind": "STRATEGY",
                        "owner_ref": _STRATEGY,
                        "current_positions": [],
                        "fees_since_baseline": [],
                    },
                    {
                        "owner_kind": "STRATEGY",
                        "owner_ref": _STRATEGY,
                        "current_positions": [],
                        "fees_since_baseline": [],
                    },
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

    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_CASH_CURRENCY_REQUIRED"):
        view.getcash()
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_VALUE_UNAVAILABLE"):
        view.getvalue()

    assert runtime.calls == []
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_FINANCIAL_UNAVAILABLE"):
        view.getcash(currency="USDT")
    assert len(runtime.calls) == 1
