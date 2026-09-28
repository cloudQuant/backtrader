"""Store-level fail-closed routing tests for the Iteration 41 adapter port."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from backtrader.stores.managed_execution import ManagedExecutionAdapterError


class _CountingApi:
    def __init__(self) -> None:
        self.submissions: list[object] = []
        self.cancellations: list[tuple[object, Optional[str]]] = []

    def submit_order(self, payload: object) -> dict[str, object]:
        self.submissions.append(payload)
        return {"status": "accepted", "id": "legacy.order"}

    def cancel_order(
        self, order_ref: object, *, dataname: Optional[str] = None
    ) -> dict[str, object]:
        self.cancellations.append((order_ref, dataname))
        return {"status": "accepted", "id": str(order_ref)}


class _ProjectingAdapter:
    def __init__(self) -> None:
        self.orders: list[object] = []
        self.legacy_dispatch = None

    def submit_order(self, order: object, legacy_dispatch: object) -> dict[str, object]:
        self.orders.append(order)
        self.legacy_dispatch = legacy_dispatch
        return {"status": "accepted", "id": "managed.order"}


class _CancelProjectingAdapter(_ProjectingAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.cancellations: list[tuple[object, Optional[str], object]] = []

    def cancel_order(
        self, order_or_ref: object, dataname: Optional[str], legacy_dispatch: object
    ) -> dict[str, object]:
        self.cancellations.append((order_or_ref, dataname, legacy_dispatch))
        return {"status": "cancelled", "id": "managed.order"}


class _FailingCancelAdapter(_ProjectingAdapter):
    def cancel_order(
        self, order_or_ref: object, dataname: Optional[str], legacy_dispatch: object
    ) -> object:
        raise RuntimeError("managed durable cancellation failed")


class _FailingAdapter:
    def submit_order(self, order: object, legacy_dispatch: object) -> object:
        raise RuntimeError("managed durable admission failed")


class _EmptyProjectionAdapter:
    def submit_order(self, order: object, legacy_dispatch: object) -> object:
        return None


def _order(ref: int = 1) -> object:
    return SimpleNamespace(ref=ref)


def test_store_delegates_to_explicit_managed_adapter_without_direct_provider_write() -> None:
    api = _CountingApi()
    adapter = _ProjectingAdapter()
    store = BtApiStore(provider="btapi", api=api, managed_execution_adapter=adapter)

    response = store.submit_order(_order())

    assert store.managed_execution_active is True
    assert response == {"status": "accepted", "id": "managed.order"}
    assert len(adapter.orders) == 1
    assert callable(adapter.legacy_dispatch)
    assert api.submissions == []


def test_managed_submit_failure_never_retries_through_direct_provider_path() -> None:
    api = _CountingApi()
    store = BtApiStore(provider="btapi", api=api, managed_execution_adapter=_FailingAdapter())

    with pytest.raises(RuntimeError, match="durable admission"):
        store.submit_order(_order())

    assert api.submissions == []


def test_missing_managed_projection_is_rejected_without_direct_provider_write() -> None:
    api = _CountingApi()
    store = BtApiStore(
        provider="btapi", api=api, managed_execution_adapter=_EmptyProjectionAdapter()
    )

    with pytest.raises(BtApiStoreError, match="no submission projection"):
        store.submit_order(_order())

    assert api.submissions == []


def test_managed_cancel_without_explicit_port_is_rejected_without_direct_fallback() -> None:
    api = _CountingApi()
    store = BtApiStore(provider="btapi", api=api, managed_execution_adapter=_ProjectingAdapter())

    with pytest.raises(BtApiStoreError, match="managed_execution_cancel_not_supported"):
        store.cancel_order_ref("managed.order", dataname="fixture")

    assert api.cancellations == []


def test_store_passes_the_full_order_to_the_explicit_managed_cancel_port() -> None:
    api = _CountingApi()
    adapter = _CancelProjectingAdapter()
    store = BtApiStore(provider="btapi", api=api, managed_execution_adapter=adapter)
    order = _order()

    response = store.cancel_order(order)

    assert response == {"status": "cancelled", "id": "managed.order"}
    assert adapter.cancellations and adapter.cancellations[0][0] is order
    assert callable(adapter.cancellations[0][2])
    assert api.cancellations == []


def test_managed_cancel_failure_never_retries_through_direct_provider_path() -> None:
    api = _CountingApi()
    store = BtApiStore(provider="btapi", api=api, managed_execution_adapter=_FailingCancelAdapter())

    with pytest.raises(RuntimeError, match="durable cancellation"):
        store.cancel_order(_order())

    assert api.cancellations == []


def test_store_rejects_an_object_that_is_not_a_managed_adapter() -> None:
    with pytest.raises(ManagedExecutionAdapterError, match="submit_order"):
        BtApiStore(provider="btapi", api=_CountingApi(), managed_execution_adapter=object())
