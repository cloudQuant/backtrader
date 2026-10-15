"""Offline behavior for the service-backed managed execution adapter."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from backtrader.stores.service_execution_adapter import (
    ServiceExecutionAdapter,
    ServiceExecutionAdapterError,
    ServiceExecutionReadError,
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
            # A per-object framework reference is not published by default:
            # it would break intent idempotency on a resubmit.
            "tags": {},
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


def test_a_deployment_supplied_stable_reference_is_published_as_a_tag() -> None:
    client = _FakeClient(submit_view=_view())
    adapter = ServiceExecutionAdapter(client, order_ref_factory=lambda order: f"stable-{order.ref}")

    adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert client.submitted[0]["tags"] == {"framework_order_ref": "stable-7"}


def test_an_unstable_or_malformed_reference_is_never_published() -> None:
    client = _FakeClient(submit_view=_view())
    adapter = ServiceExecutionAdapter(client, order_ref_factory=lambda order: " bad ref ")

    adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert client.submitted[0]["tags"] == {}


def test_partial_and_complete_fills_are_projected_with_exact_figures() -> None:
    client = _FakeClient(
        submit_view=_view(
            state="PARTIALLY_FILLED",
            filled_quantity=Decimal("1.5"),
            average_price=Decimal("101.25"),
            cumulative_commission=Decimal("0.02"),
        )
    )
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert response["status"] == "partial"
    assert response["filled"] == "1.5"
    assert response["price"] == "101.25"
    assert response["cumulative_commission"] == "0.02"
    assert response["external_order_id"] == "provider-order-1"

    client.submit_view = _view(
        intent_id="intent-2",
        state="FILLED",
        filled_quantity=Decimal("2"),
        average_price=Decimal("101.5"),
    )
    completed = adapter.submit_order(
        _limit_order(info=_managed_info(managed_intent_id="intent-2")), _legacy_dispatch
    )
    assert completed["status"] == "completed"
    assert completed["filled"] == "2"
    assert completed["price"] == "101.5"


def test_a_fill_without_exact_figures_is_never_booked_as_one() -> None:
    client = _FakeClient(
        submit_view=_view(
            state="PARTIALLY_FILLED", filled_quantity=Decimal("1.5"), average_price=None
        )
    )
    adapter = ServiceExecutionAdapter(client)

    response = adapter.submit_order(_limit_order(), _legacy_dispatch)

    assert response["status"] == "accepted"
    assert response["service_execution_fill_unprojected"] is True
    assert "filled" not in response and "price" not in response


def test_broker_applies_a_completed_service_record_once() -> None:
    import backtrader as bt

    client = _FakeClient(
        submit_view=_view(
            state="FILLED",
            filled_quantity=Decimal("2"),
            average_price=Decimal("101.5"),
        )
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

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(2.0)
        assert order.executed.price == pytest.approx(101.5)
        assert provider.submitted_orders == []

        # A repeated identical intent returns the same durable record and must
        # not book the same fill a second time.
        duplicate = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        assert duplicate.executed.size == pytest.approx(0.0)
        assert len(client.submitted) == 2
    finally:
        store.stop()


def test_broker_applies_a_partial_fill_from_the_service_record() -> None:
    import backtrader as bt

    client = _FakeClient(
        submit_view=_view(
            state="PARTIALLY_FILLED",
            filled_quantity=Decimal("1"),
            average_price=Decimal("101.25"),
        )
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

        assert order.status == bt.Order.Partial
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(101.25)
        assert provider.submitted_orders == []
    finally:
        store.stop()


class _QueryClient(_FakeClient):
    """Fake client whose durable record can be advanced between refreshes."""

    def __init__(self, *, view=None, error=None):
        super().__init__()
        self.view = view
        self.error = error
        self.queries: list[str] = []
        # When set, each query looks like a fresh revision so the adapter's own
        # replay check cannot hide a Broker-level duplicate application.
        self.force_fresh_revision = False

    def query(self, intent_id):
        self.queries.append(intent_id)
        if self.error is not None:
            raise self.error
        if self.force_fresh_revision and self.view is not None:
            self._revision_counter = getattr(self, "_revision_counter", 0) + 1
            return SimpleNamespace(
                **{**vars(self.view), "updated_at_ns": 1000 + self._revision_counter}
            )
        return self.view


class _MultiIntentQueryClient(_FakeClient):
    """Return per-intent submission/read facts for partial-pass coverage."""

    def __init__(self, *, views, failing_intent):
        super().__init__()
        self.views = views
        self.failing_intent = failing_intent
        self.queries: list[str] = []

    def submit(self, **kwargs):
        self.submitted.append(kwargs)
        return _view(intent_id=kwargs["intent_id"], updated_at_ns=5)

    def query(self, intent_id):
        self.queries.append(intent_id)
        if intent_id == self.failing_intent:
            raise _StubError("SCOPE_DENIED")
        return self.views[intent_id]


def test_refresh_projects_the_current_durable_state() -> None:
    client = _QueryClient(
        view=_view(
            state="FILLED",
            filled_quantity=Decimal("2"),
            average_price=Decimal("101.5"),
            updated_at_ns=5,
        )
    )
    adapter = ServiceExecutionAdapter(client)

    projection = adapter.refresh_projection("intent-1")

    assert projection["status"] == "completed"
    assert projection["filled"] == "2"
    assert projection["price"] == "101.5"
    assert projection["managed_intent_id"] == "intent-1"
    assert "managed_execution_replayed" not in projection
    assert client.queries == ["intent-1"]


def test_refreshing_an_unchanged_record_is_a_replay() -> None:
    client = _QueryClient(
        view=_view(
            state="PARTIALLY_FILLED",
            filled_quantity=Decimal("1"),
            average_price=Decimal("101.25"),
            updated_at_ns=5,
        )
    )
    adapter = ServiceExecutionAdapter(client)

    first = adapter.refresh_projection("intent-1")
    second = adapter.refresh_projection("intent-1")

    assert first["status"] == "partial"
    assert "managed_execution_replayed" not in first
    assert second["managed_execution_replayed"] is True
    assert second["managed_execution_state"] == "PARTIALLY_FILLED"


def test_a_new_revision_is_projected_even_after_an_earlier_refresh() -> None:
    client = _QueryClient(view=_view(state="ACKED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)

    assert adapter.refresh_projection("intent-1")["status"] == "accepted"
    client.view = _view(
        state="FILLED",
        filled_quantity=Decimal("2"),
        average_price=Decimal("101.5"),
        updated_at_ns=9,
    )
    advanced = adapter.refresh_projection("intent-1")

    assert advanced["status"] == "completed"
    assert "managed_execution_replayed" not in advanced


def test_refresh_reports_a_cancelled_record_as_terminal() -> None:
    client = _QueryClient(view=_view(state="CANCELLED", provider_order_id="provider-order-1"))
    adapter = ServiceExecutionAdapter(client)

    projection = adapter.refresh_projection("intent-1")

    assert projection["status"] == "cancelled"


def test_refresh_keeps_an_unknown_record_reconcilable() -> None:
    client = _QueryClient(view=_view(state="UNKNOWN", provider_order_id=None))
    adapter = ServiceExecutionAdapter(client)

    projection = adapter.refresh_projection("intent-1")

    assert projection["status"] == "pending"
    assert projection["execution_unknown"] is True


def test_refresh_reports_a_missing_record_as_unknown_not_as_success() -> None:
    client = _QueryClient(view=None)
    adapter = ServiceExecutionAdapter(client)

    projection = adapter.refresh_projection("intent-1")

    assert projection["status"] == "pending"
    assert projection["execution_unknown"] is True
    assert projection["error_code"] == "service_execution_record_missing"


def test_refresh_raises_a_typed_error_for_any_failed_durable_read() -> None:
    client = _QueryClient(error=_StubError("BUSINESS_OUTCOME_UNKNOWN"))
    adapter = ServiceExecutionAdapter(client)

    with pytest.raises(ServiceExecutionReadError) as unknown:
        adapter.refresh_projection("intent-1")
    assert unknown.value.code == "BUSINESS_OUTCOME_UNKNOWN"
    assert unknown.value.applied_refs == ()

    client.error = _StubError("SCOPE_DENIED")
    with pytest.raises(ServiceExecutionReadError) as refused:
        adapter.refresh_projection("intent-1")
    assert refused.value.code == "SCOPE_DENIED"

    client.error = TimeoutError()
    with pytest.raises(ServiceExecutionReadError) as timed_out:
        adapter.refresh_projection("intent-1")
    assert timed_out.value.code == "service_execution_read_timeout"


def test_a_previously_known_record_missing_from_a_successful_read_is_an_error() -> None:
    client = _QueryClient(view=_view(updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)
    client.submit_view = _view(updated_at_ns=5)
    assert adapter.submit_order(_limit_order(), _legacy_dispatch)["status"] == "accepted"

    client.view = None
    with pytest.raises(ServiceExecutionReadError) as missing:
        adapter.refresh_projection("intent-1")
    assert missing.value.code == "service_execution_record_missing"


def test_refresh_requires_a_reference_identifier() -> None:
    adapter = ServiceExecutionAdapter(_QueryClient(view=None))

    with pytest.raises(ServiceExecutionAdapterError, match="invalid intent id"):
        adapter.refresh_projection(" bad ")


def test_a_refresh_never_dispatches_and_never_touches_the_legacy_route() -> None:
    client = _QueryClient(view=_view(state="ACKED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)

    adapter.refresh_projection("intent-1")

    assert client.submitted == []
    assert client.cancelled == []


def test_broker_refresh_applies_a_new_durable_revision_once() -> None:
    import backtrader as bt

    client = _QueryClient(view=_view(state="ACKED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), provider = _broker_stack(adapter)
    try:
        client.submit_view = _view(state="ACKED", updated_at_ns=5)
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        assert order.status == bt.Order.Accepted

        # The service advances the durable record; the refresh projects it.
        client.view = _view(
            state="FILLED",
            filled_quantity=Decimal("2"),
            average_price=Decimal("101.5"),
            updated_at_ns=9,
        )
        applied = broker.refresh_managed_orders()
        assert applied == (order.ref,)
        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(2.0)
        assert order.executed.price == pytest.approx(101.5)

        # The unchanged revision is a replay and must not be booked again.
        assert broker.refresh_managed_orders() == ()
        assert order.executed.size == pytest.approx(2.0)
        assert provider.submitted_orders == []
        assert provider.cancelled_orders == []
    finally:
        store.stop()


def test_broker_refresh_skips_orders_without_a_managed_intent() -> None:
    import backtrader as bt

    client = _QueryClient(view=_view(state="FILLED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), _provider = _broker_stack(adapter)
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        del order.info["managed_intent_id"]

        assert broker.refresh_managed_orders() == ()
        assert client.queries == []
    finally:
        store.stop()


def test_broker_refresh_backoff_preserves_order_and_recovers_same_revision() -> None:
    import backtrader as bt

    from backtrader.stores.service_refresh_loop import ManagedOrderRefreshLoop

    client = _QueryClient(view=_view(state="ACKED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), provider = _broker_stack(adapter)
    clock = [0.0]
    loop = ManagedOrderRefreshLoop(
        broker,
        interval_seconds=1.0,
        max_interval_seconds=8.0,
        monotonic_clock=lambda: clock[0],
    )
    try:
        client.submit_view = _view(state="ACKED", updated_at_ns=5)
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        original_external_id = order.info.get("external_order_id")
        original_executed_size = order.executed.size
        original_executed_price = order.executed.price

        client.error = _StubError("SCOPE_DENIED")
        assert loop.run_once() == ()

        assert order.alive() is True
        assert order.info.get("execution_unknown") is True
        assert order.info.get("service_refresh_error_code") == "SCOPE_DENIED"
        assert order.status == bt.Order.Accepted
        assert order.info.get("external_order_id") == original_external_id
        assert order.executed.size == original_executed_size
        assert order.executed.price == original_executed_price
        assert loop.stats.failures == 1
        assert loop.stats.last_error_code == "SCOPE_DENIED"
        assert loop.stats.current_interval_seconds == pytest.approx(2.0)
        assert len(client.submitted) == 1

        clock[0] = 2.0
        client.error = TimeoutError()
        assert loop.run_once() == ()
        assert order.alive() is True
        assert order.info.get("service_refresh_error_code") == "service_execution_read_timeout"
        assert loop.stats.current_interval_seconds == pytest.approx(4.0)

        # The same durable revision is a replay, but its successful read must
        # clear read uncertainty without applying or booking the order twice.
        clock[0] = 6.0
        client.error = None
        client.view = _view(state="ACKED", updated_at_ns=5)
        assert loop.run_once() == ()
        assert order.status == bt.Order.Accepted
        assert order.alive() is True
        assert order.info.get("execution_unknown") is False
        assert order.info.get("service_refresh_error_code") is None
        assert order.info.get("service_read_unavailable") is False
        assert loop.stats.failures == 2
        assert loop.stats.last_error_code is None
        assert loop.stats.current_interval_seconds == pytest.approx(1.0)
        assert len(client.submitted) == 1
        assert provider.submitted_orders == []
    finally:
        store.stop()


def test_a_successful_unknown_record_stays_business_unknown_without_backoff() -> None:
    import backtrader as bt

    from backtrader.stores.service_refresh_loop import ManagedOrderRefreshLoop

    client = _QueryClient(view=_view(state="ACKED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), provider = _broker_stack(adapter)
    clock = [0.0]
    loop = ManagedOrderRefreshLoop(broker, monotonic_clock=lambda: clock[0])
    try:
        client.submit_view = _view(state="ACKED", updated_at_ns=5)
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        client.error = _StubError("SCOPE_DENIED")
        assert loop.run_once() == ()
        assert order.info.get("service_read_unavailable") is True
        assert loop.stats.current_interval_seconds == pytest.approx(2.0)

        clock[0] = 2.0
        client.error = None
        client.view = _view(state="UNKNOWN", provider_order_id=None, updated_at_ns=9)
        assert loop.run_once() == (order.ref,)
        assert order.status == bt.Order.Accepted
        assert order.alive() is True
        assert order.info.get("execution_unknown") is True
        assert order.info.get("service_refresh_error_code") is None
        assert order.info.get("service_read_unavailable") is False
        assert loop.stats.failures == 1
        assert loop.stats.last_error_code is None
        assert loop.stats.current_interval_seconds == pytest.approx(1.0)
        assert len(client.submitted) == 1
        assert provider.submitted_orders == []
    finally:
        store.stop()


def test_same_partial_revision_recovers_read_failure_without_rebooking_fill() -> None:
    import backtrader as bt

    from backtrader.stores.service_refresh_loop import ManagedOrderRefreshLoop

    partial = _view(
        state="PARTIALLY_FILLED",
        filled_quantity=Decimal("1"),
        average_price=Decimal("100.5"),
        updated_at_ns=8,
    )
    client = _QueryClient(view=_view(state="ACKED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), provider = _broker_stack(adapter)
    clock = [0.0]
    loop = ManagedOrderRefreshLoop(broker, monotonic_clock=lambda: clock[0])
    try:
        client.submit_view = _view(state="ACKED", updated_at_ns=5)
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        client.view = partial
        assert loop.run_once() == (order.ref,)
        assert order.status == bt.Order.Partial
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(100.5)

        clock[0] = 1.0
        client.error = _StubError("SCOPE_DENIED")
        assert loop.run_once() == ()
        assert order.status == bt.Order.Partial
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(100.5)
        assert order.info.get("execution_unknown") is True

        clock[0] = 3.0
        client.error = None
        assert loop.run_once() == ()
        assert order.status == bt.Order.Partial
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(100.5)
        assert order.info.get("execution_unknown") is False
        assert order.info.get("service_refresh_error_code") is None
        assert loop.stats.failures == 1
        assert loop.stats.current_interval_seconds == pytest.approx(1.0)
        assert len(client.submitted) == 1
        assert provider.submitted_orders == []
    finally:
        store.stop()


def test_partial_applied_refs_survive_a_later_read_failure() -> None:
    import backtrader as bt

    from backtrader.stores.service_refresh_loop import ManagedOrderRefreshLoop

    views = {
        f"intent-{index}": _view(
            intent_id=f"intent-{index}",
            state="FILLED",
            filled_quantity=Decimal("2"),
            average_price=Decimal("101.5"),
            updated_at_ns=9,
        )
        for index in (1, 2)
    }
    client = _MultiIntentQueryClient(views=views, failing_intent="intent-3")
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), provider = _broker_stack(adapter)
    clock = [0.0]
    loop = ManagedOrderRefreshLoop(broker, monotonic_clock=lambda: clock[0], limit=3)
    try:
        orders = []
        for index in (1, 2, 3):
            order_info = _managed_broker_info()
            order_info["managed_intent_id"] = f"intent-{index}"
            order_info["managed_signal_id"] = f"signal.intent-{index}"
            orders.append(
                broker.buy(
                    owner=None,
                    data=data,
                    size=2,
                    price=101.0,
                    exectype=bt.Order.Limit,
                    **order_info,
                )
            )

        assert loop.run_once() == ()
        assert client.queries == ["intent-1", "intent-2", "intent-3"]
        assert loop.stats.failures == 1
        assert loop.stats.last_error_code == "SCOPE_DENIED"
        assert loop.stats.applied == 2
        assert loop.stats.last_applied_refs == (orders[0].ref, orders[1].ref)
        assert orders[0].status == bt.Order.Completed
        assert orders[1].status == bt.Order.Completed
        assert orders[2].status == bt.Order.Accepted
        assert orders[2].alive() is True
        assert orders[2].info.get("execution_unknown") is True
        assert orders[2].info.get("service_refresh_error_code") == "SCOPE_DENIED"
        assert len(client.submitted) == 3
        assert provider.submitted_orders == []
    finally:
        store.stop()


def test_successful_cumulative_partial_snapshots_keep_average_fill_price() -> None:
    import backtrader as bt

    client = _QueryClient(view=_view(state="ACKED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), _provider = _broker_stack(adapter)
    try:
        client.submit_view = _view(state="ACKED", updated_at_ns=5)
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )

        client.view = _view(
            state="PARTIALLY_FILLED",
            filled_quantity=Decimal("1"),
            average_price=Decimal("100.5"),
            updated_at_ns=7,
        )
        projection = adapter.refresh_projection("intent-1")
        assert projection["avg_price"] == projection["price"] == "100.5"
        # Use a newer revision for the Broker pass after inspecting the shape.
        client.view = _view(
            state="PARTIALLY_FILLED",
            filled_quantity=Decimal("1"),
            average_price=Decimal("100.5"),
            updated_at_ns=8,
        )
        assert broker.refresh_managed_orders() == (order.ref,)
        assert order.status == bt.Order.Partial
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(100.5)

        client.view = _view(
            state="FILLED",
            filled_quantity=Decimal("2"),
            average_price=Decimal("101.5"),
            updated_at_ns=9,
        )
        assert broker.refresh_managed_orders() == (order.ref,)
        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(2.0)
        assert order.executed.price == pytest.approx(101.5)
    finally:
        store.stop()


def test_refresh_requires_a_managed_adapter_and_a_valid_limit() -> None:
    client = _QueryClient(view=_view(state="ACKED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), _provider = _broker_stack(adapter)
    try:
        with pytest.raises(ValueError, match="positive integer"):
            broker.refresh_managed_orders(limit=0)
        with pytest.raises(ValueError, match="positive integer"):
            broker.refresh_managed_orders(limit="many")

        import backtrader as bt

        client.submit_view = _view(state="ACKED", updated_at_ns=5)
        broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        store._managed_execution_adapter = None
        with pytest.raises(Exception, match="managed execution adapter is not attached"):
            broker.refresh_managed_orders()
    finally:
        store.stop()


def test_refresh_does_not_run_without_an_explicit_call() -> None:
    import backtrader as bt

    client = _QueryClient(view=_view(state="FILLED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), _provider = _broker_stack(adapter)
    try:
        client.submit_view = _view(state="ACKED", updated_at_ns=5)
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )

        assert order.status == bt.Order.Accepted
        assert client.queries == []
    finally:
        store.stop()


def test_the_refresh_loop_drives_a_real_broker_pass() -> None:
    import backtrader as bt

    from backtrader.stores.service_refresh_loop import ManagedOrderRefreshLoop

    client = _QueryClient(view=_view(state="ACKED", updated_at_ns=5))
    adapter = ServiceExecutionAdapter(client)
    (store, data, broker), _provider = _broker_stack(adapter)
    clock = [0.0]
    loop = ManagedOrderRefreshLoop(broker, interval_seconds=2.0, monotonic_clock=lambda: clock[0])
    try:
        client.submit_view = _view(state="ACKED", updated_at_ns=5)
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        assert order.status == bt.Order.Accepted

        assert loop.run_once() == ()
        assert order.status == bt.Order.Accepted

        client.view = _view(
            state="FILLED",
            filled_quantity=Decimal("2"),
            average_price=Decimal("101.5"),
            updated_at_ns=9,
        )
        clock[0] = 2.0
        assert loop.run_once() == (order.ref,)
        assert order.status == bt.Order.Completed

        # Not due yet, and the unchanged revision is skipped when it is.
        assert loop.run_once() == ()
        clock[0] = 4.0
        assert loop.run_once() == ()
        assert loop.stats.applied == 1
        assert loop.stats.failures == 0
    finally:
        store.stop()


class _StaticProjectionAdapter:
    """Duck-typed adapter that always reports the same durable revision.

    It performs no replay marking of its own, so the Broker-level guarantee is
    exercised in isolation: an unchanged durable revision must not be applied
    or notified twice.
    """

    def __init__(self, projection):
        self.projection = dict(projection)
        self.refreshes = 0

    def submit_order(self, order, legacy_dispatch):
        del legacy_dispatch
        return {
            "kind": "service_execution_record",
            "managed_intent_id": order.info.get("managed_intent_id"),
            "service_execution_state": "ACKED",
            "status": "accepted",
            "external_order_id": "provider-order-1",
            "data_name": "BTC-USDT",
        }

    def refresh_projection(self, intent_id):
        self.refreshes += 1
        return dict(self.projection, managed_intent_id=intent_id)


def test_a_repeated_refresh_projection_does_not_notify_twice() -> None:
    import backtrader as bt

    notifications: list[int] = []
    adapter = _StaticProjectionAdapter(
        {
            "kind": "service_execution_record",
            "service_execution_state": "ACKED",
            "service_record_revision": 7,
            "status": "accepted",
            "external_order_id": "provider-order-1",
            "data_name": "BTC-USDT",
        }
    )
    (store, data, broker), _provider = _broker_stack(adapter)
    original_notify = broker.notify

    def _recording_notify(order):
        notifications.append(getattr(order, "ref", None))
        return original_notify(order)

    broker.notify = _recording_notify
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info(),
        )
        notifications.clear()

        first = broker.refresh_managed_orders()
        after_first = len(notifications)
        second = broker.refresh_managed_orders()

        assert first == (order.ref,)
        assert second == ()
        assert adapter.refreshes == 2
        assert len(notifications) == after_first

        # A new durable revision that changes the state is applied again.
        adapter.projection.update(
            {
                "service_record_revision": 8,
                "service_execution_state": "FILLED",
                "status": "completed",
                "filled": "2",
                "price": "101.5",
            }
        )
        assert broker.refresh_managed_orders() == (order.ref,)
        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(2.0)
    finally:
        store.stop()
