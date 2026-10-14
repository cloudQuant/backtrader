"""Offline behavior for the service-backed managed execution adapter."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backtrader.stores.service_execution_adapter import (
    ServiceExecutionAdapter,
    ServiceExecutionAdapterError,
)


class _FakeClient:
    """Duck-typed stand-in for the SDK execution client."""

    def __init__(
        self,
        *,
        submit_view: Any = None,
        submit_error: BaseException | None = None,
        cancel_view: Any = None,
        cancel_error: BaseException | None = None,
    ) -> None:
        self.submit_view = submit_view
        self.submit_error = submit_error
        self.cancel_view = cancel_view
        self.cancel_error = cancel_error
        self.submitted: list[dict[str, Any]] = []
        self.cancelled: list[dict[str, Any]] = []

    def submit(self, **kwargs: Any) -> Any:
        self.submitted.append(kwargs)
        if self.submit_error is not None:
            raise self.submit_error
        return self.submit_view

    def cancel(self, **kwargs: Any) -> Any:
        self.cancelled.append(kwargs)
        if self.cancel_error is not None:
            raise self.cancel_error
        return self.cancel_view


class _StubError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _StubOrder:
    def __init__(
        self,
        *,
        exectype: Any,
        size: Any = 2,
        price: Any = 101.0,
        is_buy: bool = True,
        info: dict[str, Any] | None = None,
        data_name: str = "BTC-USDT",
        ref: int = 7,
    ) -> None:
        self.exectype = exectype
        self.created = SimpleNamespace(size=size, price=price)
        self.size = size
        self.info = dict(info or {})
        self.data = SimpleNamespace(_name=data_name)
        self.ref = ref
        self._is_buy = is_buy

    def isbuy(self) -> bool:
        return self._is_buy


def _managed_info(**overrides: Any) -> dict[str, Any]:
    info = {
        "managed_intent_id": "intent-1",
        "managed_signal_id": "signal-1",
        "managed_instrument": "BTC-USDT",
        "managed_position_effect": "OPEN",
        "managed_metadata_version": "metadata-v1",
        "reduce_only": False,
    }
    info.update(overrides)
    return info


def _legacy_dispatch(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("the legacy dispatcher must never be used by this adapter")


def _view(**overrides: Any) -> Any:
    view = {
        "state": "ACKED",
        "intent_id": "intent-1",
        "provider_order_id": "provider-order-1",
        "dispatch_attempts": 1,
    }
    view.update(overrides)
    return SimpleNamespace(**view)


def _limit_order(**overrides: Any) -> _StubOrder:
    from backtrader.order import Order

    arguments = {"exectype": Order.Limit, "info": _managed_info()}
    arguments.update(overrides)
    return _StubOrder(**arguments)


def test_adapter_requires_a_submit_and_cancel_capable_client() -> None:
    with pytest.raises(ServiceExecutionAdapterError, match="requires submit"):
        ServiceExecutionAdapter(object())
    with pytest.raises(ServiceExecutionAdapterError, match="requires cancel"):
        ServiceExecutionAdapter(SimpleNamespace(submit=lambda **_: None))
    with pytest.raises(ServiceExecutionAdapterError, match="invalid metadata_version"):
        ServiceExecutionAdapter(_FakeClient(), metadata_version="  ")


def test_accepted_intent_projects_the_provider_identity() -> None:
    client = _FakeClient(submit_view=_view())
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert response["status"] == "accepted"
    assert response["external_order_id"] == "provider-order-1"
    assert response["managed_intent_id"] == "intent-1"
    assert response["service_execution_state"] == "ACKED"
    assert response["data_name"] == "BTC-USDT"
    assert client.submitted == [
        {
            "intent_id": "intent-1",
            "signal_id": "signal-1",
            "instrument": "BTC-USDT",
            "side": "BUY",
            "position_effect": "OPEN",
            "order_type": "LIMIT",
            "quantity": 2,
            "price": 101.0,
            "reduce_only": False,
            "metadata_version": "metadata-v1",
            "tags": {"framework_order_ref": "backtrader-order-7"},
        }
    ]


def test_market_order_is_projected_without_a_price() -> None:
    from backtrader.order import Order

    client = _FakeClient(submit_view=_view())
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(exectype=Order.Market), _legacy_dispatch)

    assert response["status"] == "accepted"
    assert client.submitted[0]["order_type"] == "MARKET"
    assert client.submitted[0]["price"] is None


def test_unsupported_execution_type_is_rejected_without_a_service_call() -> None:
    from backtrader.order import Order

    client = _FakeClient(submit_view=_view())
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(exectype=Order.Stop), _legacy_dispatch)

    assert response["status"] == "rejected"
    assert response["error_code"] == "managed_order_content_unsupported"
    assert client.submitted == []


def test_missing_managed_metadata_is_rejected_without_a_service_call() -> None:
    client = _FakeClient(submit_view=_view())
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(
        _limit_order(info={"managed_intent_id": "intent-1"}), _legacy_dispatch
    )

    assert response["status"] == "rejected"
    assert response["error_code"] == "managed_order_metadata_missing"
    assert client.submitted == []


def test_close_position_effect_forces_reduce_only() -> None:
    client = _FakeClient(submit_view=_view())
    adapter = ServiceExecutionAdapter(client)

    adapter.submit_order(
        _limit_order(info=_managed_info(managed_position_effect="CLOSE", reduce_only=False)),
        _legacy_dispatch,
    )

    assert client.submitted[0]["position_effect"] == "CLOSE"
    assert client.submitted[0]["reduce_only"] is True


def test_sell_order_reports_the_sell_side_and_absolute_quantity() -> None:
    client = _FakeClient(submit_view=_view())
    adapter = ServiceExecutionAdapter(client)

    adapter.submit_order(_limit_order(size=-3, is_buy=False), _legacy_dispatch)

    assert client.submitted[0]["side"] == "SELL"
    assert client.submitted[0]["quantity"] == 3


def test_unknown_durable_state_stays_nonterminal() -> None:
    client = _FakeClient(submit_view=_view(state="UNKNOWN", provider_order_id=None))
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert response["status"] == "pending"
    assert response["execution_unknown"] is True
    assert "external_order_id" not in response
    assert response["error_code"] == "service_execution_outcome_unknown"


def test_rejected_durable_state_rejects_the_framework_order() -> None:
    client = _FakeClient(submit_view=_view(state="REJECTED", provider_order_id=None))
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert response["status"] == "rejected"
    assert response["error_code"] == "service_execution_rejected"


def test_unknown_service_outcome_is_not_turned_into_a_local_failure() -> None:
    client = _FakeClient(submit_error=_StubError("BUSINESS_OUTCOME_UNKNOWN"))
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert response["status"] == "pending"
    assert response["execution_unknown"] is True
    assert response["error_code"] == "BUSINESS_OUTCOME_UNKNOWN"
    assert len(client.submitted) == 1


def test_transport_unknown_is_not_retried_and_stays_visible() -> None:
    client = _FakeClient(submit_error=_StubError("TRANSPORT_OUTCOME_UNKNOWN"))
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert response["status"] == "pending"
    assert response["execution_unknown"] is True
    assert len(client.submitted) == 1


def test_definitive_service_failure_rejects_with_the_service_code() -> None:
    client = _FakeClient(submit_error=_StubError("INTENT_CONFLICT"))
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert response["status"] == "rejected"
    assert response["error_code"] == "INTENT_CONFLICT"
    assert response["managed_intent_id"] == "intent-1"


def test_unexpected_error_is_reported_as_an_unknown_outcome() -> None:
    client = _FakeClient(submit_error=RuntimeError("synthetic transport failure"))
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert response["status"] == "pending"
    assert response["execution_unknown"] is True
    assert response["error_code"] == "service_execution_request_failed"


def test_cancel_acknowledgement_stays_nonterminal() -> None:
    client = _FakeClient(
        cancel_view=SimpleNamespace(
            state="ACKED",
            cancel_id="cancel-1",
            target_intent_id="intent-1",
            provider_order_id="provider-order-1",
        )
    )
    adapter = ServiceExecutionAdapter(client)
    order = _limit_order(
        info=_managed_info(
            managed_cancel_intent_id="cancel-1", external_order_id="provider-order-1"
        )
    )

    response = adapter.cancel_order(order, "BTC-USDT", _legacy_dispatch)

    assert response["status"] == "cancel_requested"
    assert response["managed_execution_cancel_pending"] is True
    assert response["managed_execution_cancel_reconciliation_required"] is True
    assert client.cancelled == [
        {
            "cancel_id": "cancel-1",
            "target_intent_id": "intent-1",
            "provider_order_id": "provider-order-1",
            "metadata_version": "metadata-v1",
        }
    ]


def test_confirmed_cancellation_is_terminal() -> None:
    client = _FakeClient(
        cancel_view=SimpleNamespace(
            state="CANCELLED",
            cancel_id="cancel-1",
            target_intent_id="intent-1",
            provider_order_id="provider-order-1",
        )
    )
    adapter = ServiceExecutionAdapter(client)
    order = _limit_order(
        info=_managed_info(
            managed_cancel_intent_id="cancel-1", external_order_id="provider-order-1"
        )
    )

    response = adapter.cancel_order(order, "BTC-USDT", _legacy_dispatch)

    assert response["status"] == "cancelled"
    assert "managed_execution_cancel_pending" not in response


def test_cancel_without_provider_identity_is_rejected_without_a_service_call() -> None:
    client = _FakeClient()
    adapter = ServiceExecutionAdapter(client)
    order = _limit_order(info=_managed_info(managed_cancel_intent_id="cancel-1"))

    response = adapter.cancel_order(order, "BTC-USDT", _legacy_dispatch)

    assert response["status"] == "rejected"
    assert response["error_code"] == "managed_cancel_provider_identity_missing"
    assert client.cancelled == []


def test_cancel_without_managed_identity_is_rejected_without_a_service_call() -> None:
    client = _FakeClient()
    adapter = ServiceExecutionAdapter(client)

    response = adapter.cancel_order(_limit_order(info={}), "BTC-USDT", _legacy_dispatch)

    assert response["status"] == "rejected"
    assert response["error_code"] == "managed_cancel_metadata_missing"
    assert client.cancelled == []


def test_cancel_unknown_outcome_stays_reconcilable() -> None:
    client = _FakeClient(cancel_error=_StubError("BUSINESS_OUTCOME_UNKNOWN"))
    adapter = ServiceExecutionAdapter(client)
    order = _limit_order(
        info=_managed_info(
            managed_cancel_intent_id="cancel-1", external_order_id="provider-order-1"
        )
    )

    response = adapter.cancel_order(order, "BTC-USDT", _legacy_dispatch)

    assert response["status"] == "pending"
    assert response["execution_unknown"] is True
    assert response["managed_execution_cancel_pending"] is True
    assert len(client.cancelled) == 1


# -- through the real Store and Broker --------------------------------------


def _broker_stack(adapter):
    from tests.unit.brokers.test_btapibroker_managed_execution_projection import (
        _ResponseProvider,
        _make_started_stack,
    )

    provider = _ResponseProvider([])
    return _make_started_stack(None, provider, managed_execution_adapter=adapter), provider


def _managed_broker_info() -> dict[str, Any]:
    return {
        "managed_order_type": "LIMIT",
        "managed_intent_id": "intent-1",
        "managed_signal_id": "signal.intent-1",
        "managed_instrument": "BTC-USDT",
        "managed_position_effect": "OPEN",
        "managed_metadata_version": "fixture.metadata.v1",
        "managed_instrument_metadata_digest": "a" * 64,
        "offset": "open",
        "reduce_only": False,
    }


def test_broker_projects_an_accepted_service_intent_without_a_legacy_write() -> None:
    import backtrader as bt

    client = _FakeClient(submit_view=_view())
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), provider = _broker_stack(adapter)
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )

        # The broker accepts the framework order; the provider identity and
        # every later state come from the service record.
        assert order.status == bt.Order.Accepted
        assert order.alive() is True
        assert order.info.get("external_order_id") == "provider-order-1"
        assert order.info.get("execution_unknown", False) is False
        assert client.submitted[0]["intent_id"] == "intent-1"
        # The legacy provider dispatch must stay untouched.
        assert provider.submitted_orders == []
    finally:
        store.stop()


def test_broker_keeps_an_unknown_service_outcome_nonterminal() -> None:
    import backtrader as bt

    client = _FakeClient(submit_view=_view(state="UNKNOWN", provider_order_id=None))
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), provider = _broker_stack(adapter)
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )

        assert order.status == bt.Order.Accepted
        assert order.alive() is True
        assert order.info.get("execution_unknown") is True
        assert order.executed.size == pytest.approx(0.0)
        assert provider.submitted_orders == []
    finally:
        store.stop()


def test_cancel_identity_follows_the_framework_convention_when_absent() -> None:
    client = _FakeClient(
        cancel_view=SimpleNamespace(
            state="ACKED",
            cancel_id="cancel.intent-1",
            target_intent_id="intent-1",
            provider_order_id="provider-order-1",
        )
    )
    adapter = ServiceExecutionAdapter(client)
    order = _limit_order(info=_managed_info(external_order_id="provider-order-1"))

    response = adapter.cancel_order(order, "BTC-USDT", _legacy_dispatch)

    assert response["status"] == "cancel_requested"
    assert client.cancelled[0]["cancel_id"] == "cancel.intent-1"


def test_broker_cancel_routes_through_the_service_adapter() -> None:
    import backtrader as bt

    client = _FakeClient(
        submit_view=_view(),
        cancel_view=SimpleNamespace(
            state="ACKED",
            cancel_id="cancel.intent-1",
            target_intent_id="intent-1",
            provider_order_id="provider-order-1",
        ),
    )
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), provider = _broker_stack(adapter)
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        assert order.info.get("external_order_id") == "provider-order-1"

        broker.cancel(order)

        assert client.cancelled == [
            {
                "cancel_id": "cancel.intent-1",
                "target_intent_id": "intent-1",
                "provider_order_id": "provider-order-1",
                "metadata_version": "fixture.metadata.v1",
            }
        ]
        # An acknowledged cancellation is not a terminal framework state: the
        # broker keeps the order open and asks for reconciliation.
        assert order.alive() is True
        assert order.info.get("managed_execution_cancel_reconciliation_required") is True
        assert provider.cancelled_orders == []
        assert provider.submitted_orders == []
    finally:
        store.stop()


def test_broker_cancel_unknown_outcome_stays_reconcilable() -> None:
    import backtrader as bt

    client = _FakeClient(
        submit_view=_view(),
        cancel_error=_StubError("BUSINESS_OUTCOME_UNKNOWN"),
    )
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), provider = _broker_stack(adapter)
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        broker.cancel(order)

        assert order.alive() is True
        assert order.info.get("execution_unknown") is True
        assert provider.cancelled_orders == []
    finally:
        store.stop()
