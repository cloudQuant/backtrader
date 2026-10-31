"""Read-only allocation forwarding must not start an SDK or touch balances."""

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from backtrader_runtime.managed_execution import (
    ManagedExecutionBindingError,
    ManagedExecutionBridge,
)


@dataclass(frozen=True)
class _Snapshot:
    scope: object
    strategy_id: str
    available_notional: Decimal = Decimal("600")


def _read_path(*, snapshot_scope=None, snapshot_strategy="strategy-a"):
    scope = ("fixture", "account-a", "simulation")
    snapshot = _Snapshot(scope if snapshot_scope is None else snapshot_scope, snapshot_strategy)
    reads = []

    def read(account_scope, strategy_id):
        reads.append((account_scope, strategy_id))
        return snapshot

    bridge = object.__new__(ManagedExecutionBridge)
    bridge.runtime = SimpleNamespace(
        scope=SimpleNamespace(strategy_id="strategy-a"),
        risk_scope=scope,
        risk_gate=SimpleNamespace(get_strategy_allocation=read),
    )
    store = object.__new__(BtApiStore)
    store._managed_execution_adapter = bridge
    # Using uninitialized objects intentionally makes provider/balance access
    # fail: a read must only visit the explicitly attached local risk reader.
    broker = object.__new__(BtApiBroker)
    broker.store = store
    return broker, bridge, snapshot, reads


def test_allocation_read_forwards_exact_scope_and_preserves_immutable_snapshot():
    broker, bridge, snapshot, reads = _read_path()
    assert broker.get_strategy_allocation("strategy-a") is snapshot
    assert reads == [(bridge.runtime.risk_scope, "strategy-a")]
    with pytest.raises(AttributeError):
        snapshot.available_notional = Decimal("10000")


@pytest.mark.parametrize("strategy_id", ["strategy-b", "", None, True])
def test_other_strategy_rejects_before_read(strategy_id):
    broker, _, _, reads = _read_path()
    with pytest.raises(ManagedExecutionBindingError, match="strategy"):
        broker.get_strategy_allocation(strategy_id)
    assert reads == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"snapshot_scope": ("fixture", "account-b", "simulation")},
        {"snapshot_strategy": "strategy-b"},
    ],
)
def test_mismatched_reader_result_rejects(kwargs):
    broker, _, _, reads = _read_path(**kwargs)
    with pytest.raises(ManagedExecutionBindingError, match="snapshot"):
        broker.get_strategy_allocation("strategy-a")
    assert len(reads) == 1


def test_missing_risk_reader_rejects_without_cash_fallback():
    broker, bridge, _, reads = _read_path()
    bridge.runtime.risk_gate = None
    with pytest.raises(ManagedExecutionBindingError, match="unavailable"):
        broker.get_strategy_allocation("strategy-a")
    assert reads == []


def test_unmanaged_store_rejects_without_starting_sdk():
    store = object.__new__(BtApiStore)
    store._managed_execution_adapter = None
    with pytest.raises(BtApiStoreError, match="unavailable"):
        store.get_strategy_allocation("strategy-a")


def test_broker_without_allocation_port_rejects_without_balance_refresh():
    broker = object.__new__(BtApiBroker)
    broker.store = SimpleNamespace()
    with pytest.raises(ValueError, match="unavailable"):
        broker.get_strategy_allocation("strategy-a")
