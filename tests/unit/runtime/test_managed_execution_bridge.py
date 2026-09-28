"""Unit tests for config-bound framework-to-intent projection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from backtrader.order import OrderBase
from backtrader.stores.btapistore import BtApiStore
from backtrader_runtime.managed_execution import (
    ManagedExecutionBindingError,
    ManagedExecutionBridge,
    CtpManagedExecutionAdapterPlaceholder,
    _managed_runtime_order_id,
    bind_managed_execution,
    observation_from_store_response,
    project_record_to_store_response,
    strict_limit_intent_from_order,
)


class _Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class _PositionEffect(Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSE_TODAY = "CLOSE_TODAY"
    CLOSE_YESTERDAY = "CLOSE_YESTERDAY"


class _ExecutionState(Enum):
    ACKED = "ACKED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


@dataclass
class _Intent:
    scope: object
    intent_id: str
    signal_id: str
    instrument: str
    side: _Side
    quantity: Decimal
    price: Decimal
    position_effect: _PositionEffect
    reduce_only: bool
    metadata_version: str
    tags: dict[str, str]


class _OrderIntent:
    @staticmethod
    def limit(**kwargs: Any) -> _Intent:
        return _Intent(**kwargs)


@dataclass
class _ProviderObservation:
    intent_id: str
    state: _ExecutionState
    provider_order_id: Optional[str] = None
    filled_quantity: Decimal = Decimal("0")
    average_price: Optional[Decimal] = None
    reason_code: Optional[str] = None

    @staticmethod
    def accepted(intent_id: str, provider_order_id: str) -> "_ProviderObservation":
        return _ProviderObservation(
            intent_id=intent_id,
            state=_ExecutionState.ACKED,
            provider_order_id=provider_order_id,
        )

    @staticmethod
    def rejected(intent_id: str, reason: str) -> "_ProviderObservation":
        return _ProviderObservation(
            intent_id=intent_id,
            state=_ExecutionState.REJECTED,
            reason_code=reason,
        )


class _Execution:
    Side = _Side
    PositionEffect = _PositionEffect
    OrderIntent = _OrderIntent
    ProviderObservation = _ProviderObservation
    ExecutionState = _ExecutionState


class _FixtureMetadataSnapshot:
    """Minimal immutable-looking live snapshot used by the root bridge tests."""

    @staticmethod
    def instrument_metadata(instrument: str) -> SimpleNamespace:
        if instrument != "fixture/contract":
            raise KeyError(instrument)
        return SimpleNamespace(quantity_unit="contracts")

    @staticmethod
    def instrument_digest(instrument: str) -> str:
        if instrument != "fixture/contract":
            raise KeyError(instrument)
        return "a" * 64


class _Runtime:
    def __init__(self, *, convert_unknown: bool = False) -> None:
        self.execution = _Execution
        self.scope = SimpleNamespace(
            provider="ctp",
            strategy_id="example.runtime",
            environment="production",
            key="scope:" + "c" * 64,
            account_key="account:" + "d" * 64,
        )
        self.contract = SimpleNamespace(
            strategy_id="example.runtime",
            mode="live",
            preset="managed_live_direct",
            environment="production",
            order_route="managed_execution",
            required_capabilities=("execution", "risk", "monitor"),
            effective_digest="a" * 64,
        )
        self.convert_unknown = convert_unknown
        self.intents: list[_Intent] = []
        self.instrument_metadata_snapshot = _FixtureMetadataSnapshot()

    def submit(self, intent: _Intent, dispatch: Any) -> object:
        self.intents.append(intent)
        try:
            dispatch(intent)
        except ManagedExecutionBindingError:
            if not self.convert_unknown:
                raise
            return SimpleNamespace(
                state=SimpleNamespace(value="UNKNOWN"), unknown_reason="bad_evidence"
            )
        return SimpleNamespace(state=SimpleNamespace(value="ACKED"), unknown_reason=None)


class _Order:
    exectype = OrderBase.Limit
    data = SimpleNamespace(_name="fixture/contract")
    created = SimpleNamespace(price=10.25)

    def __init__(self, *, info: Optional[Dict[str, Any]] = None, is_buy: bool = True) -> None:
        self.ref = 41
        self.info = {
            "managed_order_type": "LIMIT",
            "managed_intent_id": "intent.41",
            "managed_signal_id": "signal.41",
            "managed_instrument": "fixture/contract",
            "managed_position_effect": "OPEN",
            "managed_metadata_version": "metadata.1",
            "managed_instrument_metadata_digest": "a" * 64,
            "offset": "open",
            "reduce_only": False,
            **(info or {}),
        }
        self.size = 2 if is_buy else -2
        self.price = 10.25
        self._is_buy = is_buy

    def isbuy(self) -> bool:
        return self._is_buy

    def issell(self) -> bool:
        return not self._is_buy


def test_strict_projection_requires_explicit_stable_metadata_and_maps_limit_order() -> None:
    runtime = _Runtime()
    intent = strict_limit_intent_from_order(_Order(), runtime)

    assert intent.scope is runtime.scope
    assert intent.intent_id == "intent.41"
    assert intent.side is _Side.BUY
    assert intent.quantity == Decimal("2")
    assert intent.price == Decimal("10.25")
    assert intent.position_effect is _PositionEffect.OPEN
    assert intent.reduce_only is False
    assert intent.tags == {
        "instrument_metadata_digest": "a" * 64,
        "quantity_unit": "contracts",
    }


@pytest.mark.parametrize(
    ("effect", "offset", "reduce_only"),
    (
        ("OPEN", "open", False),
        ("CLOSE", "close", True),
        ("CLOSE_TODAY", "close_today", True),
        ("CLOSE_YESTERDAY", "close_yesterday", True),
    ),
)
def test_position_effect_is_bound_to_exact_legacy_offset_and_reduce_only_payload(
    effect: str, offset: str, reduce_only: bool
) -> None:
    intent = strict_limit_intent_from_order(
        _Order(
            info={
                "managed_position_effect": effect,
                "offset": offset,
                "reduce_only": reduce_only,
            }
        ),
        _Runtime(),
    )

    assert intent.position_effect.value == effect
    assert intent.reduce_only is reduce_only


@pytest.mark.parametrize(
    "field",
    (
        "managed_intent_id",
        "managed_signal_id",
        "managed_metadata_version",
        "managed_instrument_metadata_digest",
    ),
)
def test_missing_stable_managed_metadata_blocks_before_runtime_dispatch(field: str) -> None:
    runtime = _Runtime()
    order = _Order(info={field: ""})
    bridge = ManagedExecutionBridge(runtime)

    with pytest.raises(ManagedExecutionBindingError, match=field):
        bridge.submit_order(order, lambda _order: {"status": "accepted", "id": "provider.41"})

    assert runtime.intents == []


def test_bridge_uses_legacy_port_once_only_after_managed_intent_is_constructed() -> None:
    runtime = _Runtime()
    bridge = ManagedExecutionBridge(runtime)
    called: list[object] = []

    response = bridge.submit_order(
        _Order(),
        lambda order: called.append(order) or {"status": "accepted", "id": "provider.41"},
    )

    assert response == {"status": "accepted", "id": "provider.41"}
    assert len(runtime.intents) == 1
    assert len(called) == 1


def test_managed_runtime_order_id_is_stable_scoped_and_independent_of_order_ref() -> None:
    def capture(runtime: _Runtime, *, intent_id: str = "intent.41", order_ref: int = 41) -> str:
        order = _Order(info={"managed_intent_id": intent_id})
        order.ref = order_ref
        captured: list[str] = []
        ManagedExecutionBridge(runtime).submit_order(
            order,
            lambda projected: captured.append(projected.info["runtime_order_id"])
            or {"status": "accepted", "id": "provider.41"},
        )
        return captured[0]

    first = capture(_Runtime())
    recovered = capture(_Runtime(), order_ref=9001)
    different_intent = capture(_Runtime(), intent_id="intent.42")
    other_scope = _Runtime()
    other_scope.scope.key = "scope:" + "d" * 64
    different_scope = capture(other_scope)

    assert first.startswith("bt-managed-v1:")
    assert first == recovered
    assert first != different_intent
    assert first != different_scope


def test_managed_runtime_order_id_cannot_be_overridden_by_order_info() -> None:
    runtime = _Runtime()
    legacy_calls: list[object] = []

    with pytest.raises(ManagedExecutionBindingError, match="runtime_order_id is derived"):
        ManagedExecutionBridge(runtime).submit_order(
            _Order(info={"runtime_order_id": "caller-selected"}),
            lambda order: legacy_calls.append(order)
            or {"status": "accepted", "id": "provider.41"},
        )

    assert runtime.intents == []
    assert legacy_calls == []


@pytest.mark.parametrize(
    ("info", "error"),
    (
        ({"managed_instrument": "substituted/contract"}, "data symbol"),
        ({"offset": "close"}, "position effect.*offset"),
        ({"reduce_only": True}, "position effect.*reduce_only"),
    ),
)
def test_payload_metadata_mismatch_blocks_before_risk_admission_and_legacy_dispatch(
    info: Dict[str, Any], error: str
) -> None:
    runtime = _Runtime()
    bridge = ManagedExecutionBridge(runtime)
    legacy_calls: list[object] = []

    with pytest.raises(ManagedExecutionBindingError, match=error):
        bridge.submit_order(
            _Order(info=info),
            lambda order: legacy_calls.append(order) or {"status": "accepted", "id": "provider.41"},
        )

    assert runtime.intents == []
    assert legacy_calls == []


def test_declared_limit_cannot_admit_an_actual_market_order() -> None:
    runtime = _Runtime()
    order = _Order()
    order.exectype = OrderBase.Market
    legacy_calls: list[object] = []

    with pytest.raises(ManagedExecutionBindingError, match="Order.Limit"):
        ManagedExecutionBridge(runtime).submit_order(
            order,
            lambda dispatched_order: legacy_calls.append(dispatched_order)
            or {"status": "accepted", "id": "provider.41"},
        )

    assert runtime.intents == []
    assert legacy_calls == []


def test_mutable_quantity_unit_cannot_change_live_intent_or_legacy_payload() -> None:
    """Live quantity semantics come exclusively from sealed instrument metadata."""

    runtime = _Runtime()
    bridge = ManagedExecutionBridge(runtime)
    legacy_calls: list[object] = []

    with pytest.raises(ManagedExecutionBindingError, match="quantity_unit"):
        bridge.submit_order(
            _Order(info={"quantity_unit": "base"}),
            lambda order: legacy_calls.append(order) or {"status": "accepted", "id": "provider.41"},
        )

    assert runtime.intents == []
    assert legacy_calls == []


def test_live_intent_cannot_substitute_the_sealed_quantity_unit() -> None:
    runtime = _Runtime()
    legacy_calls: list[object] = []

    def forged_intent(order: _Order, forged_runtime: _Runtime) -> _Intent:
        intent = strict_limit_intent_from_order(order, forged_runtime)
        intent.tags["quantity_unit"] = "base"
        return intent

    with pytest.raises(ManagedExecutionBindingError, match="sealed instrument quantity_unit"):
        ManagedExecutionBridge(runtime, intent_from_order=forged_intent).submit_order(
            _Order(),
            lambda order: legacy_calls.append(order) or {"status": "accepted", "id": "provider.41"},
        )

    assert runtime.intents == []
    assert legacy_calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("instrument", "substituted/contract"),
        ("side", _Side.SELL),
        ("quantity", Decimal("3")),
        ("price", Decimal("11")),
        ("position_effect", _PositionEffect.CLOSE),
        ("reduce_only", True),
    ),
)
def test_risk_intent_cannot_describe_a_different_payload(field: str, value: Any) -> None:
    runtime = _Runtime()

    def forged_intent(order: _Order, forged_runtime: _Runtime) -> _Intent:
        intent = strict_limit_intent_from_order(order, forged_runtime)
        setattr(intent, field, value)
        return intent

    bridge = ManagedExecutionBridge(runtime, intent_from_order=forged_intent)
    legacy_calls: list[object] = []

    with pytest.raises(ManagedExecutionBindingError, match="admitted intent does not match"):
        bridge.submit_order(
            _Order(),
            lambda order: legacy_calls.append(order) or {"status": "accepted", "id": "provider.41"},
        )

    assert runtime.intents == []
    assert legacy_calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("quantity_unit", "base"),
        ("position_side", "short"),
        ("position_id", "position.mutated"),
        ("position_mode", "dual_side"),
        ("exchange_id", "SHFE"),
        ("time_in_force", "IOC"),
        ("client_order_id", "client.mutated"),
        ("front_id", 7),
        ("session_id", 8),
        ("order_ref", "mutated"),
        ("execution_cycle_id", "cycle.mutated"),
        ("execution_role", "exit"),
        ("strategy_identity_sha256", "b" * 64),
    ),
)
def test_execution_shaping_metadata_mutation_after_risk_admission_blocks_dispatch(
    field: str, value: Any
) -> None:
    order = _Order()
    legacy_calls: list[object] = []

    class _MutatingRuntime(_Runtime):
        def submit(self, intent: _Intent, dispatch: Any) -> object:
            self.intents.append(intent)
            order.info[field] = value
            return dispatch(intent)

    runtime = _MutatingRuntime()
    with pytest.raises(ManagedExecutionBindingError):
        ManagedExecutionBridge(runtime).submit_order(
            order,
            lambda dispatched_order: legacy_calls.append(dispatched_order)
            or {"status": "accepted", "id": "provider.41"},
        )

    assert len(runtime.intents) == 1
    assert legacy_calls == []


def test_legacy_dispatch_receives_an_immutable_canonical_provider_projection() -> None:
    """A mutation after the second check cannot alter Store payload facts."""

    runtime = _Runtime()
    order = _Order(
        info={
            "position_side": "long",
            "position_id": "position.41",
            "position_mode": "net",
            "time_in_force": "GTC",
            "front_id": 1,
            "session_id": 2,
            "order_ref": "41",
            "execution_cycle_id": "cycle.41",
            "execution_role": "entry",
            "strategy_identity_sha256": "c" * 64,
        }
    )
    captured: dict[str, Any] = {}

    def legacy_dispatch(dispatched_order: Any) -> dict[str, str]:
        assert dispatched_order is not order
        with pytest.raises(TypeError):
            dispatched_order.info["position_mode"] = "dual_side"
        # This simulates a strategy/observer mutating the original order after
        # the bridge's second verification but before Store serialization.
        order.size = 999
        order.price = 999.0
        order.info.update(
            quantity_unit="base",
            position_side="short",
            position_id="position.mutated",
            position_mode="dual_side",
            time_in_force="IOC",
            front_id=7,
            session_id=8,
            order_ref="mutated",
            execution_cycle_id="cycle.mutated",
            execution_role="exit",
            strategy_identity_sha256="d" * 64,
        )
        payload_store = object.__new__(BtApiStore)
        captured.update(payload_store._order_to_payload(dispatched_order))
        return {"status": "accepted", "id": "provider.41"}

    response = ManagedExecutionBridge(runtime).submit_order(order, legacy_dispatch)

    assert response == {"status": "accepted", "id": "provider.41"}
    assert captured == {
        "symbol": "fixture/contract",
        "data_name": "fixture/contract",
        "bt_order_ref": 41,
        "side": "buy",
        "size": Decimal("2"),
        "price": Decimal("10.25"),
        "order_type": "limit",
        "valid": None,
        "tradeid": 0,
        "offset": "open",
        "position_side": "long",
        "time_in_force": "GTC",
        "reduce_only": False,
        "quantity_unit": "contracts",
        "position_id": "position.41",
        "position_mode": "net",
        "front_id": 1,
        "session_id": 2,
        "order_ref": "41",
        "execution_cycle_id": "cycle.41",
        "execution_role": "entry",
        "strategy_identity_sha256": "c" * 64,
        "runtime_order_id": _managed_runtime_order_id(runtime.scope, "intent.41"),
    }


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("data", SimpleNamespace(_name="substituted/contract"), "data symbol"),
        ("_is_buy", False, "admitted intent does not match Backtrader order side"),
        ("size", 3, "admitted intent does not match Backtrader order quantity"),
        ("price", 11.0, "admitted intent does not match Backtrader order price"),
        ("offset", "close", "position effect.*offset"),
        ("reduce_only", True, "position effect.*reduce_only"),
        ("exectype", OrderBase.Market, "Order.Limit"),
    ),
)
def test_order_mutation_after_risk_admission_blocks_before_legacy_dispatch(
    field: str, value: Any, error: str
) -> None:
    order = _Order()
    legacy_calls: list[object] = []

    class _MutatingRuntime(_Runtime):
        def submit(self, intent: _Intent, dispatch: Any) -> object:
            self.intents.append(intent)
            if field in {"offset", "reduce_only"}:
                order.info[field] = value
            else:
                setattr(order, field, value)
            return dispatch(intent)

    runtime = _MutatingRuntime()
    bridge = ManagedExecutionBridge(runtime)

    with pytest.raises(ManagedExecutionBindingError, match=error):
        bridge.submit_order(
            order,
            lambda dispatched_order: legacy_calls.append(dispatched_order)
            or {"status": "accepted", "id": "provider.41"},
        )

    assert len(runtime.intents) == 1
    assert legacy_calls == []


def test_unconfirmed_provider_response_projects_unknown_and_never_asks_store_to_retry() -> None:
    runtime = _Runtime(convert_unknown=True)
    bridge = ManagedExecutionBridge(runtime)
    called: list[object] = []

    response = bridge.submit_order(
        _Order(),
        lambda order: called.append(order) or {"status": "accepted"},
    )

    assert response["execution_unknown"] is True
    assert response["managed_execution_replayed"] is False
    assert response["managed_execution_state"] == "UNKNOWN"
    assert called == [called[0]]


def test_fill_status_requires_explicit_normalized_fill_evidence() -> None:
    runtime = _Runtime()
    intent = strict_limit_intent_from_order(_Order(), runtime)

    partial = observation_from_store_response(
        runtime,
        intent,
        {
            "status": "partial",
            "id": "provider.41",
            "filled_quantity": "1.5",
            "average_price": "10.20",
            "cumulative_commission": "0.15",
        },
    )
    filled = observation_from_store_response(
        runtime,
        intent,
        {
            "status": "filled",
            "id": "provider.41",
            "filled_quantity": "2",
            "average_price": "10.25",
            "cumulative_commission": "0.20",
        },
    )

    assert partial.state is _ExecutionState.PARTIALLY_FILLED
    assert partial.filled_quantity == Decimal("1.5")
    assert filled.state is _ExecutionState.FILLED
    assert filled.filled_quantity == Decimal("2")
    with pytest.raises(ManagedExecutionBindingError, match="average_price"):
        observation_from_store_response(
            runtime,
            intent,
            {
                "status": "filled",
                "id": "provider.41",
                "filled_quantity": "2",
                "cumulative_commission": "0.20",
            },
        )

    with pytest.raises(ManagedExecutionBindingError, match="cumulative_commission"):
        observation_from_store_response(
            runtime,
            intent,
            {
                "status": "filled",
                "id": "provider.41",
                "filled_quantity": "2",
                "average_price": "10.25",
            },
        )


def test_existing_durable_acceptance_replays_its_provider_identity_without_a_second_dispatch() -> (
    None
):
    record = SimpleNamespace(
        state=SimpleNamespace(value="ACKED"),
        provider_order_id="provider.41",
    )

    response = project_record_to_store_response(record, provider_response=None)

    assert response == {
        "status": "accepted",
        "id": "provider.41",
        "managed_execution_replayed": True,
        "managed_execution_state": "ACKED",
    }


def test_durable_fill_replay_keeps_normalized_progress_evidence() -> None:
    response = project_record_to_store_response(
        SimpleNamespace(
            state=SimpleNamespace(value="PARTIALLY_FILLED"),
            provider_order_id="provider.41",
            filled_quantity=Decimal("1.5"),
            average_price=Decimal("10.20"),
        ),
        provider_response=None,
    )

    assert response == {
        "status": "partial",
        "id": "provider.41",
        "managed_execution_replayed": True,
        "managed_execution_state": "PARTIALLY_FILLED",
        "filled_quantity": "1.5",
        "average_price": "10.20",
    }


def test_store_and_bridge_combined_still_block_bad_intent_before_provider_write() -> None:
    calls: list[object] = []

    class _Api:
        def submit_order(self, payload: object) -> dict[str, object]:
            calls.append(payload)
            return {"status": "accepted", "id": "provider.41"}

    store = BtApiStore(
        provider="btapi",
        api=_Api(),
        managed_execution_adapter=ManagedExecutionBridge(_Runtime()),
    )

    with pytest.raises(ManagedExecutionBindingError, match="managed_intent_id"):
        store.submit_order(_Order(info={"managed_intent_id": ""}))

    assert calls == []


class _AttachStore:
    def __init__(self, *, ctp: bool = False) -> None:
        self.ctp = ctp
        self.adapter = None

    def attach_managed_execution_adapter(self, adapter: object) -> None:
        self.adapter = adapter

    def _is_ctp_session_provider(self) -> bool:
        return self.ctp


class _GatewayRuntime(_Runtime):
    """A gateway-client shape whose Store callback must remain unused."""

    gateway_dispatch = "zmq_gateway_v1"

    def __init__(self) -> None:
        super().__init__()
        self.contract.preset = "managed_live_gateway"
        self.contract.required_capabilities = (
            "execution",
            "risk",
            "monitor",
            "gateway",
            "transport_zmq",
        )

    def submit(self, intent: _Intent, legacy_dispatch: Any) -> object:
        assert callable(legacy_dispatch)
        self.intents.append(intent)
        return SimpleNamespace(
            state=SimpleNamespace(value="ACKED"),
            provider_order_id="gateway.provider.41",
        )


def _managed_effective(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "order_route": "managed_execution",
        "required_capabilities": ("execution", "risk", "monitor"),
        "strategy_id": "example.runtime",
        "mode": "live",
        "preset": "managed_live_direct",
        "policy": SimpleNamespace(environment="production"),
        "effective_digest": "a" * 64,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_binding_requires_resolved_managed_route_and_uses_store_attach_port() -> None:
    store = _AttachStore()
    runtime = _Runtime()
    effective = _managed_effective()

    bridge = bind_managed_execution(store, effective, runtime)

    assert store.adapter is bridge
    with pytest.raises(ManagedExecutionBindingError, match="not a managed"):
        bind_managed_execution(
            _AttachStore(),
            _managed_effective(
                order_route=None,
                required_capabilities=(),
            ),
            runtime,
        )


def test_ctp_binding_uses_typed_placeholder_and_refuses_before_sdk_dispatch() -> None:
    store = _AttachStore(ctp=True)
    runtime = _Runtime()
    adapter = bind_managed_execution(store, _managed_effective(), runtime)
    dispatches: list[object] = []

    assert isinstance(adapter, CtpManagedExecutionAdapterPlaceholder)
    assert store.adapter is adapter
    with pytest.raises(
        ManagedExecutionBindingError,
        match="MANAGED_CTP_WRITE_COMPOSITION_UNAVAILABLE",
    ) as submit_error:
        adapter.submit_order(_Order(), lambda identity: dispatches.append(identity))
    assert submit_error.value.code == "managed_ctp_write_composition_unavailable"
    assert submit_error.value.managed_local_reject is True
    assert submit_error.value.definite_reject is True
    with pytest.raises(
        ManagedExecutionBindingError,
        match="MANAGED_CTP_WRITE_COMPOSITION_UNAVAILABLE",
    ):
        adapter.cancel_order(_Order(), "fixture/contract", lambda identity: dispatches.append(identity))
    assert dispatches == []


def test_ctp_binding_rejects_wrong_provider_or_environment_scope_before_attachment() -> None:
    store = _AttachStore(ctp=True)
    wrong_provider = _Runtime()
    wrong_provider.scope.provider = "binance"
    with pytest.raises(ManagedExecutionBindingError, match="provider scope"):
        bind_managed_execution(store, _managed_effective(), wrong_provider)
    assert store.adapter is None

    wrong_environment = _Runtime()
    wrong_environment.scope.environment = "sandbox"
    with pytest.raises(ManagedExecutionBindingError, match="environment scope"):
        bind_managed_execution(_AttachStore(ctp=True), _managed_effective(), wrong_environment)


def test_binding_rejects_runtime_scope_that_differs_from_the_effective_config() -> None:
    strategy_runtime = _Runtime()
    strategy_runtime.contract.strategy_id = "different.strategy"
    with pytest.raises(ManagedExecutionBindingError, match="strategy scope"):
        bind_managed_execution(
            _AttachStore(),
            _managed_effective(strategy_id="different.strategy"),
            strategy_runtime,
        )

    environment_runtime = _Runtime()
    environment_runtime.contract.environment = "sandbox"
    with pytest.raises(ManagedExecutionBindingError, match="environment scope"):
        bind_managed_execution(
            _AttachStore(),
            _managed_effective(policy=SimpleNamespace(environment="sandbox")),
            environment_runtime,
        )


def test_binding_rejects_an_sdk_store_with_a_different_strategy_namespace() -> None:
    store = _AttachStore()
    store._sdk_mode = True
    store._sdk_execution_config = {"strategy_id": "other.strategy"}

    with pytest.raises(ManagedExecutionBindingError, match="SDK Store execution config"):
        bind_managed_execution(store, _managed_effective(), _Runtime())

    assert store.adapter is None


def test_binding_rejects_a_runtime_contract_from_a_different_effective_config() -> None:
    with pytest.raises(ManagedExecutionBindingError, match="effective_digest"):
        bind_managed_execution(
            _AttachStore(),
            _managed_effective(effective_digest="b" * 64),
            _Runtime(),
        )


def test_binding_rejects_gateway_contract_without_a_sealed_gateway_dispatcher() -> None:
    store = _AttachStore()
    runtime = _Runtime()
    runtime.contract.preset = "managed_live_gateway"
    runtime.contract.required_capabilities = (
        "execution",
        "risk",
        "monitor",
        "gateway",
        "transport_zmq",
    )

    with pytest.raises(ManagedExecutionBindingError, match="sealed ZMQ dispatch"):
        bind_managed_execution(
            store,
            _managed_effective(
                preset="managed_live_gateway",
                required_capabilities=runtime.contract.required_capabilities,
            ),
            runtime,
        )

    assert store.adapter is None


def test_gateway_binding_discards_the_store_legacy_provider_callback() -> None:
    store = _AttachStore()
    runtime = _GatewayRuntime()
    effective = _managed_effective(
        preset="managed_live_gateway",
        required_capabilities=runtime.contract.required_capabilities,
    )
    bridge = bind_managed_execution(store, effective, runtime)
    legacy_calls: list[object] = []

    response = bridge.submit_order(
        _Order(),
        lambda order: legacy_calls.append(order) or {"status": "accepted", "id": "legacy.41"},
    )

    assert store.adapter is bridge
    assert len(runtime.intents) == 1
    assert legacy_calls == []
    assert response == {
        "status": "accepted",
        "id": "gateway.provider.41",
        "managed_execution_replayed": True,
        "managed_execution_state": "ACKED",
    }


def test_gateway_cancellation_cannot_restore_the_store_legacy_provider_callback() -> None:
    """Gateway cancellation stays closed until a sealed cancellation port exists."""

    runtime = _GatewayRuntime()
    bridge = ManagedExecutionBridge(runtime)
    legacy_calls: list[object] = []

    with pytest.raises(
        ManagedExecutionBindingError, match="MANAGED_GATEWAY_CANCEL_NOT_IMPLEMENTED"
    ):
        bridge.cancel_order(
            _Order(),
            None,
            lambda order_ref, dataname: legacy_calls.append((order_ref, dataname)),
        )

    assert legacy_calls == []


def test_gateway_bridge_never_scans_the_direct_cancellation_recovery_journal() -> None:
    """Gateway composition has neither a direct recovery scan nor provider fallback."""

    class _PoisonedJournal:
        def __init__(self) -> None:
            self.scans: list[object] = []

        def list_unknown_cancellations(self, scope: object) -> list[object]:
            self.scans.append(scope)
            raise AssertionError("gateway bridge must not inspect direct cancellation state")

    runtime = _GatewayRuntime()
    journal = _PoisonedJournal()
    # Give the fake a direct-runtime-looking state directory, so the assertion
    # proves the sealed gateway preset itself short-circuits recovery.
    runtime.state_directory = "must-not-be-read"
    runtime.execution_store = journal

    ManagedExecutionBridge(runtime)

    assert journal.scans == []


def test_direct_bridge_recovers_interrupted_cancel_dispatch_before_freeze_scan(
    tmp_path, monkeypatch
) -> None:
    """Startup fences lost callbacks under a new writer lease before admission."""

    import backtrader_runtime.managed_execution as runtime_managed

    events: list[str] = []
    scope = SimpleNamespace(key="scope:" + "e" * 64, account_key="account:" + "e" * 64)
    interrupted = SimpleNamespace(
        scope_key=scope.key,
        cancel_id="cancel.inflight",
        state=SimpleNamespace(value="UNKNOWN"),
    )

    class _ExecutionStore:
        def assert_writer_lease(self, actual_scope, lease):
            assert actual_scope is scope
            assert lease == "writer-lease"

        def list_unresolved_cancellations_for_account(self, actual_scope, *, writer_lease):
            assert actual_scope is scope
            assert writer_lease == "writer-lease"
            events.append("unknown_scan")
            return ((scope, interrupted),)

        def recover_interrupted_cancellations(self, actual_scope, *, writer_lease):
            raise AssertionError("UNKNOWN rows must not be rewritten as interrupted dispatches")

        def get_cancel(self, cancel_id, *, scope):
            assert cancel_id == interrupted.cancel_id
            assert scope is interrupted_scope
            return interrupted

    class _OrderFacade:
        def acquire_writer_lease(self):
            events.append("writer_lease")
            return "writer-lease"

    interrupted_scope = scope
    active_freezes: set[str] = set()

    class _RiskGate:
        def freeze(self, actual_scope, cause_id, reason):
            assert actual_scope == "risk-scope"
            assert cause_id == reason
            active_freezes.add(cause_id)
            events.append("freeze")

        def active_freeze_reasons(self, actual_scope):
            assert actual_scope == "risk-scope"
            return tuple(sorted(active_freezes))

    class _CancellationFacade:
        def __init__(self, store, actual_scope, *, acquire_writer_lease, admission_gate):
            assert store is execution_store
            assert actual_scope is scope
            assert admission_gate is not None
            self.scope = actual_scope
            self._store = store
            self._acquire_writer_lease = acquire_writer_lease

        def recover_interrupted_dispatches(self):
            lease = self._acquire_writer_lease()
            self._store.assert_writer_lease(self.scope, lease)
            events.append("interrupted_recovery")
            return (interrupted,)

    execution_store = _ExecutionStore()
    runtime = SimpleNamespace(
        submit=lambda intent, dispatch: None,
        scope=scope,
        contract=SimpleNamespace(preset="managed_live_direct"),
        state_directory=tmp_path,
        framework_projection_session_id="session-1",
        execution=SimpleNamespace(ManagedCancellationFacade=_CancellationFacade),
        execution_store=execution_store,
        facade=_OrderFacade(),
        risk_gate=_RiskGate(),
        risk_scope="risk-scope",
    )
    monkeypatch.setattr(
        runtime_managed.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            RiskIntent=lambda **kwargs: kwargs,
            IntentAction=SimpleNamespace(CANCEL="CANCEL"),
        )
        if name == "bt_api_risk"
        else __import__(name),
    )

    bridge = ManagedExecutionBridge(runtime)
    try:
        assert events == [
            "writer_lease",
            "interrupted_recovery",
            "writer_lease",
            "unknown_scan",
            "freeze",
        ]
        assert "cancel-outcome-unknown:" + scope.key + ":" + interrupted.cancel_id in active_freezes
    finally:
        bridge.close()


def test_direct_bridge_fails_closed_when_interrupted_cancel_recovery_is_unavailable(
    tmp_path, monkeypatch
) -> None:
    """A composed direct runtime cannot enable cancellation without startup fencing."""

    import backtrader_runtime.managed_execution as runtime_managed

    class _ExecutionStore:
        def assert_writer_lease(self, scope, lease):
            return None

        def list_unknown_cancellations(self, scope):
            raise AssertionError("freeze scan follows interrupted-dispatch recovery")

    class _OrderFacade:
        def acquire_writer_lease(self):
            return "writer-lease"

    class _CancellationFacadeWithoutRecovery:
        def __init__(self, store, scope, *, acquire_writer_lease, admission_gate):
            self.scope = scope

    scope = SimpleNamespace(key="scope:" + "f" * 64)
    runtime = SimpleNamespace(
        submit=lambda intent, dispatch: None,
        scope=scope,
        contract=SimpleNamespace(preset="managed_live_direct"),
        state_directory=tmp_path,
        framework_projection_session_id="session-2",
        execution=SimpleNamespace(
            ManagedCancellationFacade=_CancellationFacadeWithoutRecovery
        ),
        execution_store=_ExecutionStore(),
        facade=_OrderFacade(),
        risk_gate=SimpleNamespace(freeze=lambda *args: None),
        risk_scope="risk-scope",
    )
    monkeypatch.setattr(
        runtime_managed.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            RiskIntent=lambda **kwargs: kwargs,
            IntentAction=SimpleNamespace(CANCEL="CANCEL"),
        )
        if name == "bt_api_risk"
        else __import__(name),
    )

    with pytest.raises(ManagedExecutionBindingError, match="interrupted cancellation recovery"):
        ManagedExecutionBridge(runtime)


def test_direct_bridge_fails_closed_when_account_cancel_scan_is_unavailable(
    tmp_path, monkeypatch
) -> None:
    """An incomplete Store cannot bypass startup's account-wide cancellation fence."""

    import backtrader_runtime.managed_execution as runtime_managed

    runtime = _Runtime()
    runtime.state_directory = tmp_path
    runtime.framework_projection_session_id = "session-missing-account-scan"
    class _ExecutionStoreWithoutAccountScan:
        def assert_writer_lease(self, _scope, _lease):
            return None

        def recover_interrupted_cancellations(self, _scope, *, writer_lease):
            return ()

        def get_cancel(self, _cancel_id, *, scope):
            return None

    class _CancellationFacade:
        def __init__(self, _store, scope, *, acquire_writer_lease, admission_gate):
            self.scope = scope

        def recover_interrupted_dispatches(self):
            return ()

    runtime.execution_store = SimpleNamespace(
        **{
            name: getattr(_ExecutionStoreWithoutAccountScan(), name)
            for name in ("assert_writer_lease", "recover_interrupted_cancellations", "get_cancel")
        }
    )
    runtime.facade = SimpleNamespace(acquire_writer_lease=lambda: "writer-lease")
    runtime.execution = SimpleNamespace(ManagedCancellationFacade=_CancellationFacade)
    runtime.risk_scope = "risk-scope"
    runtime.risk_gate = SimpleNamespace(
        freeze=lambda *_args: None,
        active_freeze_reasons=lambda _scope: (),
    )
    monkeypatch.setattr(
        runtime_managed.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            RiskIntent=lambda **kwargs: kwargs,
            IntentAction=SimpleNamespace(CANCEL="CANCEL"),
        )
        if name == "bt_api_risk"
        else __import__(name),
    )

    with pytest.raises(
        ManagedExecutionBindingError,
        match="account cancellation recovery controls",
    ):
        ManagedExecutionBridge(runtime)


def test_direct_bridge_defers_only_writer_contention_and_blocks_until_recovery(
    tmp_path, monkeypatch
) -> None:
    """A competing account writer blocks dispatch until restart fencing succeeds."""

    import backtrader_runtime.managed_execution as runtime_managed

    events: list[str] = []
    lease_available = {"value": False}
    runtime = _Runtime()
    runtime.state_directory = tmp_path
    runtime.framework_projection_session_id = "session-deferred-recovery"

    class _WriterLeaseUnavailable(RuntimeError):
        code = "writer_lease_unavailable"

    class _ExecutionStore:
        def assert_writer_lease(self, actual_scope, lease):
            assert actual_scope is runtime.scope
            assert lease == "writer-lease"
            events.append("assert_lease")

        def list_unresolved_cancellations_for_account(self, actual_scope, *, writer_lease):
            assert actual_scope is runtime.scope
            assert writer_lease == "writer-lease"
            events.append("unknown_scan")
            return ()

        def recover_interrupted_cancellations(self, actual_scope, *, writer_lease):
            assert actual_scope is runtime.scope
            assert writer_lease == "writer-lease"
            events.append("account_dispatch_recovery")
            return ()

        def get_cancel(self, cancel_id, *, scope):
            raise AssertionError("empty account scan must not read a cancellation")

    class _OrderFacade:
        def acquire_writer_lease(self):
            events.append("writer_lease")
            if not lease_available["value"]:
                raise _WriterLeaseUnavailable("writer lease is held by another active runtime")
            return "writer-lease"

    class _CancellationFacade:
        def __init__(self, store, actual_scope, *, acquire_writer_lease, admission_gate):
            assert store is execution_store
            assert actual_scope is runtime.scope
            assert admission_gate is not None
            self.scope = actual_scope
            self._store = store
            self._acquire_writer_lease = acquire_writer_lease

        def recover_interrupted_dispatches(self):
            events.append("recovery_attempt")
            lease = self._acquire_writer_lease()
            self._store.assert_writer_lease(self.scope, lease)
            events.append("recovery_complete")
            return ()

    execution_store = _ExecutionStore()
    runtime.execution_store = execution_store
    runtime.facade = _OrderFacade()
    runtime.risk_gate = SimpleNamespace(
        freeze=lambda *args: None,
        active_freeze_reasons=lambda _scope: (),
    )
    runtime.risk_scope = "risk-scope"
    runtime.execution = SimpleNamespace(
        ManagedCancellationFacade=_CancellationFacade,
        Side=_Side,
        PositionEffect=_PositionEffect,
        OrderIntent=_OrderIntent,
        ProviderObservation=_ProviderObservation,
        ExecutionState=_ExecutionState,
    )
    monkeypatch.setattr(
        runtime_managed.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            RiskIntent=lambda **kwargs: kwargs,
            IntentAction=SimpleNamespace(CANCEL="CANCEL"),
        )
        if name == "bt_api_risk"
        else __import__(name),
    )

    bridge = ManagedExecutionBridge(runtime)
    provider_calls: list[object] = []
    try:
        assert bridge._interrupted_cancellation_recovery_pending is True
        with pytest.raises(
            ManagedExecutionBindingError,
            match="interrupted cancellation recovery failed",
        ):
            bridge.submit_order(_Order(), lambda order: provider_calls.append(order))
        assert runtime.intents == []
        assert provider_calls == []

        lease_available["value"] = True
        response = bridge.submit_order(
            _Order(),
            lambda order: provider_calls.append(order)
            or {"status": "accepted", "id": "provider.41"},
        )
        assert bridge._interrupted_cancellation_recovery_pending is False
        assert response["id"] == "provider.41"
        assert len(provider_calls) == 1
        assert events.index("recovery_complete") < max(
            index for index, event in enumerate(events) if event == "unknown_scan"
        )
    finally:
        bridge.close()
