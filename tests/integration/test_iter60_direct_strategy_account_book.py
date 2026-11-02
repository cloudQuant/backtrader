"""Iteration 60, step 60.07: direct-mode strategy books on the shared contract.

End to end without a Gateway or service session: two strategies share one
account and one instrument in a local execution store; the store is
reconciled locally, projected by the SDK direct reader into the same
``StrategyAccountBookSnapshot`` the service path returns, and consumed by the
Backtrader direct view and the existing strategy-scoped Sizer.
"""

from __future__ import annotations

import time
from decimal import Decimal
from types import SimpleNamespace

import pytest

bt_api_execution = pytest.importorskip("bt_api_execution")
pytest.importorskip("bt_api_py.direct_strategy_account_book")

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from bt_api_execution import (  # noqa: E402
    AllocationOwnerKind,
    CancelObservation,
    CurrencyAmount,
    ExecutionAccountBookService,
    ExecutionAccountSnapshot,
    ExecutionAllocationBaseline,
    ExecutionOwnerScope,
    ExecutionScope,
    ExecutionScopeDirectory,
    ExecutionState,
    ExternalActivitySnapshot,
    PositionFact,
    ProviderObservation,
    SqliteExecutionStore,
    StrategyCloseCapacityGate,
)
from bt_api_execution.service_order_entry import (  # noqa: E402
    SUBMIT_OPERATION,
    ExecutionOrderEntryService,
)
from bt_api_py.direct_strategy_account_book import DirectStrategyAccountBookReader  # noqa: E402

from backtrader.service.service_strategy_account_book import (  # noqa: E402
    DirectStrategyAccountBookView,
    ServiceStrategyAccountBookError,
)
from backtrader.sizers import StrategyAccountBookPercentSizer  # noqa: E402

_ACCOUNT = "account-direct"
_INSTRUMENT = "PAPER:SIM:SA2701"
_DOMAIN = "paper:direct"


class _Provider:
    def submit(self, intent):
        return ProviderObservation.accepted(intent.intent_id, f"provider-{intent.intent_id}")

    def cancel(self, intent):  # pragma: no cover - no cancels in these scenarios
        return CancelObservation.accepted(
            intent.cancel_id, intent.target_intent_id, intent.provider_order_id
        )


class _DirectAccount:
    """A direct-mode account coordinator: one store, strategies A and B."""

    def __init__(self, path) -> None:
        self.store = SqliteExecutionStore(path)
        self.scopes = {
            n: ExecutionScope("PAPER", "simulation", _ACCOUNT, f"strategy-{n}", "20261102")
            for n in ("a", "b")
        }
        self.wires = {
            n: WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=f"strategy-{n}")
            for n in ("a", "b")
        }
        self.service = ExecutionOrderEntryService(
            self.store,
            {self.wires[n]: self.scopes[n] for n in ("a", "b")},
            _Provider(),
            admission_gate=StrategyCloseCapacityGate(self.store),
        )
        self.start_ns = time.time_ns()

    def buy_filled(self, name, intent_id, quantity):
        reply = self.service.handle(
            SUBMIT_OPERATION,
            principal_ref="direct-client",
            identity=WireIdentity(WireRole.STRATEGY_CLIENT, "direct-client", f"strategy-{name}"),
            scope=self.wires[name],
            arguments={
                "intent_id": intent_id,
                "signal_id": f"signal-{intent_id}",
                "instrument": _INSTRUMENT,
                "side": "BUY",
                "position_effect": "OPEN",
                "order_type": "LIMIT",
                "quantity": quantity,
                "price": "1500",
                "time_in_force": "GTC",
                "reduce_only": False,
                "metadata_version": "metadata-v1",
                "deadline_ns": None,
                "tags": {},
            },
        )
        assert reply["ok"] is True, reply
        self.service._facade_pair(self.scopes[name])[0].reconcile(
            ProviderObservation(
                intent_id,
                ExecutionState.FILLED,
                provider_order_id=f"provider-{intent_id}",
                filled_quantity=Decimal(quantity),
                average_price=Decimal("1500"),
                cumulative_commission=Decimal("1"),
                cumulative_commission_currency="CNY",
            )
        )

    def reconcile(self, *, with_allocation=True):
        generation = str(self.store.journal_source_identity()["generation"])
        directory = ExecutionScopeDirectory(
            account_key=self.scopes["a"].account_key,
            source="trusted-owner-registry",
            source_ref="registry-1",
            revision="owner-revision-1",
            covers_from_ns=self.start_ns,
            as_of_ns=self.start_ns + 3_600_000_000_000,
            scopes=tuple(
                ExecutionOwnerScope(
                    self.scopes[n], AllocationOwnerKind.STRATEGY, f"strategy-{n}", self.wires[n]
                )
                for n in ("a", "b")
            ),
        )
        baseline = ExecutionAccountSnapshot(
            account_key=directory.account_key,
            source="synthetic-provider",
            source_ref="baseline",
            generation="session-1",
            journal_generation=generation,
            as_of_ns=self.start_ns,
            execution_cursor=0,
            position_mode="NET",
            positions=(),
            cumulative_fees=(),
            fee_coverage_start_ns=self.start_ns - 1,
        )
        _rows, _first, head, _high = self.store.execution_outbox_bounds()
        now = max(time.time_ns(), self.start_ns + 1)
        current = ExecutionAccountSnapshot(
            account_key=directory.account_key,
            source=baseline.source,
            source_ref="current",
            generation=baseline.generation,
            journal_generation=generation,
            as_of_ns=now,
            execution_cursor=head or 0,
            position_mode="NET",
            positions=(PositionFact(_INSTRUMENT, Decimal("5")),),
            cumulative_fees=(CurrencyAmount("CNY", Decimal("2")),),
            fee_coverage_start_ns=baseline.fee_coverage_start_ns,
        )
        allocation = ExecutionAllocationBaseline(
            account_key=directory.account_key,
            source="trusted-virtual-position-ledger",
            source_ref="allocation-zero",
            revision="allocation-revision-1",
            scope_directory_revision=directory.revision,
            provider_generation=baseline.generation,
            journal_generation=generation,
            as_of_ns=baseline.as_of_ns,
            execution_cursor=0,
            positions=(),
        )
        activity = ExternalActivitySnapshot(
            account_key=directory.account_key,
            source="synthetic-trade-feed",
            source_ref="window",
            generation=baseline.generation,
            coverage_start_ns=baseline.as_of_ns,
            coverage_end_ns=now,
            fills=(),
            orders=(),
        )
        return ExecutionAccountBookService(self.store).reconcile(
            directory,
            baseline,
            current,
            allocation_baseline=allocation if with_allocation else None,
            external_activity=activity,
        )

    def reader(self, name, **kwargs):
        return DirectStrategyAccountBookReader(
            lambda: self.reconcile(**kwargs),
            strategy_ref=f"strategy-{name}",
            account_ref=_ACCOUNT,
        )

    def close(self):
        for scope in self.scopes.values():
            self.service._facade_pair(scope)[0].close()
        self.store.close()


class _Data:
    _name = _INSTRUMENT

    class _Close:
        def __getitem__(self, index):
            return 1500.0

    close = _Close()


@pytest.fixture
def account(tmp_path):
    item = _DirectAccount(tmp_path / "direct.sqlite3")
    item.buy_filled("a", "a-open", "2")
    item.buy_filled("b", "b-open", "3")
    try:
        yield item
    finally:
        item.close()


def test_direct_views_project_each_strategys_own_position(account):
    view_a = DirectStrategyAccountBookView(account.reader("a"))
    view_b = DirectStrategyAccountBookView(account.reader("b"))
    assert view_a.getposition(_Data()).size == 2.0
    assert view_b.getposition(_Data()).size == 3.0
    snapshot = view_a.snapshot()
    assert snapshot.strategy_ref == "strategy-a"
    assert snapshot.positions == {_INSTRUMENT: Decimal("2")}
    assert snapshot.fees_since_baseline == {"CNY": Decimal("1")}


def test_direct_cash_and_value_fail_closed_without_financial_projection(account):
    view = DirectStrategyAccountBookView(account.reader("a"))
    with pytest.raises(ServiceStrategyAccountBookError) as info:
        view.getcash(currency="CNY")
    assert info.value.code == "STRATEGY_FINANCIAL_UNAVAILABLE"
    with pytest.raises(ServiceStrategyAccountBookError) as info:
        view.getvalue()
    assert info.value.code == "STRATEGY_VALUE_UNAVAILABLE"


def test_incomplete_local_reconciliation_fails_closed(account):
    view = DirectStrategyAccountBookView(account.reader("a", with_allocation=False))
    with pytest.raises(ServiceStrategyAccountBookError) as info:
        view.getposition(_Data())
    assert info.value.code == "STRATEGY_BOOK_COVERAGE_INCOMPLETE"


def test_existing_strategy_sizer_sells_only_the_strategy_owned_position(account):
    view = DirectStrategyAccountBookView(account.reader("a"))
    strategy = SimpleNamespace(
        p=SimpleNamespace(strategy_ref="strategy-a", account_ref=_ACCOUNT),
        account_book=view,
    )
    sizer = StrategyAccountBookPercentSizer(currency="CNY")
    sizer.set(strategy, SimpleNamespace())
    # The account holds 5, strategy A owns 2: selling uses A's 2 only.
    assert sizer.getsizing(_Data(), False) == 2
    # Buying needs strategy cash, which is unavailable: fail closed.
    with pytest.raises(ServiceStrategyAccountBookError):
        sizer.getsizing(_Data(), True)


def test_view_rejects_a_reader_snapshot_for_another_strategy(account):
    reader = account.reader("a")
    original = reader.snapshot

    class _Swapped:
        strategy_ref = "strategy-b"
        account_ref = _ACCOUNT

        def snapshot(self):
            return original()

    view = DirectStrategyAccountBookView(_Swapped())
    with pytest.raises(ServiceStrategyAccountBookError) as info:
        view.snapshot()
    assert info.value.code == "OWNER_BINDING_MISMATCH"


# ---------------------------------------------------------------------------
# BtApiBroker.bind_direct_strategy_account_book on real Strategy instances
# ---------------------------------------------------------------------------

import itertools  # noqa: E402

import backtrader as bt  # noqa: E402
from backtrader.brokers.btapibroker import BtApiBroker  # noqa: E402
from backtrader.metabase import OwnerContext  # noqa: E402


class _IdentifiedStrategy(bt.Strategy):
    params = (("strategy_ref", None), ("account_ref", None))


def _strategies(broker, *identities):
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    with OwnerContext.set_owner(cerebro):
        return [
            _IdentifiedStrategy.__new__(
                _IdentifiedStrategy, strategy_ref=strategy_ref, account_ref=account_ref
            )
            for strategy_ref, account_ref in identities
        ]


def test_btapibroker_is_constructible_without_a_store():
    # Regression: iteration-53 WIP dropped @staticmethod from
    # _parse_approval_expiry, so BtApiBroker() raised TypeError.
    broker = BtApiBroker(store=None)
    assert broker._approval_expires_at_utc is None


def test_broker_binds_each_strategy_to_its_own_direct_book(account):
    broker = BtApiBroker(store=None)
    strategy_a, strategy_b = _strategies(broker, ("strategy-a", _ACCOUNT), ("strategy-b", _ACCOUNT))
    view_a = broker.bind_direct_strategy_account_book(strategy_a, account.reader("a"))
    view_b = broker.bind_direct_strategy_account_book(strategy_b, account.reader("b"))
    assert strategy_a.account_book is view_a and strategy_b.account_book is view_b
    assert strategy_a.account_book.getposition(_Data()).size == 2.0
    assert strategy_b.account_book.getposition(_Data()).size == 3.0
    # Account-level Broker getters keep their meaning; they are not the books.
    assert broker.getcash() == broker._cash


def test_broker_rejects_identity_mismatch_and_double_binding(account):
    broker = BtApiBroker(store=None)
    strategy_a, impostor = _strategies(broker, ("strategy-a", _ACCOUNT), ("strategy-a", _ACCOUNT))
    (strategy_b,) = _strategies(broker, ("strategy-b", _ACCOUNT))
    with pytest.raises(ValueError, match="identity"):
        broker.bind_direct_strategy_account_book(strategy_b, account.reader("a"))
    broker.bind_direct_strategy_account_book(strategy_a, account.reader("a"))
    with pytest.raises(ValueError, match="already has"):
        broker.bind_direct_strategy_account_book(strategy_a, account.reader("a"))
    with pytest.raises(ValueError, match="another strategy"):
        broker.bind_direct_strategy_account_book(impostor, account.reader("a"))


def test_broker_refuses_direct_books_under_a_service_session(account):
    broker = BtApiBroker(store=None)
    (strategy_a,) = _strategies(broker, ("strategy-a", _ACCOUNT))
    broker._service_execution_session = object()
    with pytest.raises(ValueError, match="service session"):
        broker.bind_direct_strategy_account_book(strategy_a, account.reader("a"))
