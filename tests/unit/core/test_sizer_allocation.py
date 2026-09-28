"""Optional source/installed SDK integration for advisory allocation sizing."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.sizers import NotionalAllocationSizer
from backtrader.stores.btapistore import BtApiStore
from backtrader_runtime.managed_execution import ManagedExecutionBridge


@pytest.fixture
def sizing_path(tmp_path):
    pytest.importorskip("bt_api_risk.allocation_sizing", exc_type=ImportError)
    from bt_api_risk import AccountScope, DurableRiskGate, RiskPolicy
    from bt_api_risk.core.instrument import InstrumentRiskMetadata, InstrumentRiskRegistry

    scope = AccountScope("fixture", "account-a", "simulation")
    gate = DurableRiskGate(
        tmp_path / "risk.sqlite",
        RiskPolicy(
            "policy-a", Decimal("1000"), 20, require_strategy_allocation=True, notional_unit="CNY"
        ),
        clock=lambda: 1.0,
    )
    gate.set_strategy_allocation(scope, "strategy-a", "r1", max_notional=Decimal("600"))
    registry = InstrumentRiskRegistry(
        [
            InstrumentRiskMetadata(
                "FUTURE",
                "v1",
                1,
                100,
                Decimal("1"),
                Decimal("1"),
                Decimal("1"),
                Decimal("10000"),
                valuation_unit="CNY",
            )
        ]
    )
    bridge = object.__new__(ManagedExecutionBridge)
    bridge.runtime = SimpleNamespace(
        scope=SimpleNamespace(strategy_id="strategy-a"), risk_scope=scope, risk_gate=gate
    )
    store = object.__new__(BtApiStore)
    store._managed_execution_adapter = bridge
    broker = object.__new__(BtApiBroker)
    broker.store = store
    sizer = NotionalAllocationSizer(
        strategy_id="strategy-a",
        instrument="FUTURE",
        registry=registry,
        limit_price=lambda data, isbuy: Decimal("100"),
        clock_ns=lambda: 2,
    )
    sizer.set(SimpleNamespace(), broker)
    return sizer, gate, scope


def test_real_local_gate_to_broker_sizer_uses_current_reserved_budget(sizing_path):
    from bt_api_risk import IntentAction, RiskIntent

    sizer, gate, scope = sizing_path
    data = SimpleNamespace(_name="FUTURE")
    assert sizer.getsizing(data, True) == 6
    gate.reserve(
        RiskIntent(
            "i1",
            scope,
            IntentAction.INCREASE,
            Decimal("100"),
            strategy_id="strategy-a",
            allocation_version="r1",
            notional_unit="CNY",
        )
    )
    assert sizer.getsizing(data, True) == 5


def test_suggestion_does_not_authorize_an_over_budget_custom_size(sizing_path):
    from bt_api_risk import IntentAction, RiskDeniedError, RiskIntent

    sizer, gate, scope = sizing_path
    assert sizer.getsizing(SimpleNamespace(_name="FUTURE"), True) == 6
    with pytest.raises(RiskDeniedError) as rejected:
        gate.reserve(
            RiskIntent(
                "i2",
                scope,
                IntentAction.INCREASE,
                Decimal("700"),
                strategy_id="strategy-a",
                allocation_version="r1",
                notional_unit="CNY",
            )
        )
    assert rejected.value.code == "STRATEGY_ALLOCATION_EXHAUSTED"


def test_data_identity_mismatch_rejects_before_sizing(sizing_path):
    sizer, _, _ = sizing_path
    with pytest.raises(ValueError, match="data feed"):
        sizer.getsizing(SimpleNamespace(_name="OTHER"), True)


def test_expired_instrument_metadata_rejects(sizing_path):
    from bt_api_risk import RiskDeniedError

    sizer, _, _ = sizing_path
    sizer.set_param("clock_ns", lambda: 101)
    with pytest.raises(RiskDeniedError):
        sizer.getsizing(SimpleNamespace(_name="FUTURE"), True)
