"""Typed managed CTP Store composition tests; all ports are local fakes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Optional

import pytest

from backtrader.order import OrderBase
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError, ManagedCtpHandoffError
from backtrader.stores.managed_execution import (
    CtpManagedCancelDispatch,
    CtpManagedExecutionProjection,
    CtpManagedOrderDispatch,
    CtpManagedProjectionState,
    ManagedExecutionAdapterError,
    require_ctp_managed_execution_projection,
)
from backtrader_runtime.managed_execution import (
    CtpManagedExecutionAdapterPlaceholder,
    ManagedExecutionBindingError,
    _managed_runtime_order_id,
    classify_ctp_queue_receipt,
    strict_limit_intent_from_order,
)


RUNTIME_ORDER_ID = "bt-managed-v1:" + ("a" * 64)


class _Api:
    exchange_kwargs = {"CTP": {}}

    def __init__(self) -> None:
        self.submissions = []
        self.cancellations = []
        self.async_submissions = []
        self.async_cancellations = []
        self.reservations = []
        self.binding_reads = 0

    def poll_event(self):
        return None

    def submit_order(self, payload):
        self.submissions.append(payload)
        return {"status": "accepted", "id": "legacy.order"}

    def cancel_order(self, order_ref, *, dataname=None):
        self.cancellations.append((order_ref, dataname))
        return {"status": "accepted", "id": str(order_ref)}

    async def async_make_order(self, venue, request, *, normalized=True):
        self.async_submissions.append((venue, request, normalized))
        return {"status": "accepted", "id": "native.submit"}

    async def async_cancel_order(self, venue, request, *, normalized=True):
        self.async_cancellations.append((venue, request, normalized))
        return {"status": "accepted", "id": "native.cancel"}

    def get_runtime_order_bindings(self, venue, *, unresolved_only=False):
        self.binding_reads += 1
        return []

    def new_runtime_order_binding(
        self,
        venue,
        *,
        symbol,
        account_id,
        runtime_order_id,
        managed_intent_id=None,
        budget_capability=None,
        recovery_action=False,
    ):
        self.reservations.append(
            {
                "venue": venue,
                "symbol": symbol,
                "account_id": account_id,
                "runtime_order_id": runtime_order_id,
                "managed_intent_id": managed_intent_id,
            }
        )
        return {
            "client_order_id": "000000000123",
            "runtime_order_id": runtime_order_id,
            "managed_intent_id": managed_intent_id,
        }


class _Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class _OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class _PositionEffect(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSE_TODAY = "CLOSE_TODAY"
    CLOSE_YESTERDAY = "CLOSE_YESTERDAY"


class _ManagedOrderIntent:
    @staticmethod
    def limit(**kwargs):
        return SimpleNamespace(**kwargs)


class _RuntimeExecution:
    Side = _Side
    PositionEffect = _PositionEffect
    OrderIntent = _ManagedOrderIntent


class _FakeManagedRuntime:
    execution = _RuntimeExecution

    def __init__(self):
        self.scope = SimpleNamespace(
            provider="CTP",
            strategy_id="strategy",
            environment="sandbox",
            key="scope:" + ("c" * 64),
        )


class _FakeCtpProjectionAdapter:
    """Test-only adapter for local dispatch fakes.

    Its lookup and dispatch calls are not an atomic reserve operation and do
    not claim at-most-once behavior. The fixture must never be used to infer a
    production writer or crash-recovery contract.
    """

    ctp_managed_execution_version = 1

    def __init__(self, runtime, *, reader, freeze, hedge_flag):
        self.runtime = runtime
        self.reader = reader
        self.freeze = freeze
        self.hedge_flag = hedge_flag

    @staticmethod
    def _info(order, name):
        info = getattr(order, "info", None)
        getter = getattr(info, "get", None)
        return getter(name) if callable(getter) else None

    def _identity(self, order, *, cancel=False):
        intent_id = self._info(order, "managed_intent_id")
        if (
            not isinstance(intent_id, str)
            or not intent_id
            or intent_id != intent_id.strip()
        ):
            raise ManagedExecutionBindingError("managed intent identity is invalid")
        runtime_order_id = _managed_runtime_order_id(self.runtime.scope, intent_id)
        if cancel:
            cancel_id = self._info(order, "managed_cancel_intent_id") or (
                "cancel." + intent_id
            )
            identity = CtpManagedCancelDispatch(
                managed_intent_id=intent_id,
                runtime_order_id=runtime_order_id,
                managed_cancel_intent_id=cancel_id,
            )
        else:
            identity = CtpManagedOrderDispatch(
                order=order,
                managed_intent_id=intent_id,
                runtime_order_id=runtime_order_id,
                hedge_flag=self.hedge_flag,
            )
            strict_limit_intent_from_order(order, self.runtime)
        declared_runtime_id = self._info(order, "runtime_order_id")
        if declared_runtime_id not in (None, "", runtime_order_id):
            raise ManagedExecutionBindingError("managed runtime order identity mismatch")
        return identity

    def _unknown(self, operation, identity, queue_receipt, reason, cause=None):
        error = ManagedExecutionBindingError(
            "managed CTP durable projection is unavailable; outcome is UNKNOWN"
        )
        error.code = "managed_ctp_projection_unknown"
        error.execution_unknown = True
        error.managed_execution_state = "UNKNOWN"
        error.managed_projection_pending = True
        error.managed_unknown = True
        try:
            self.freeze(operation, identity, queue_receipt, reason)
        except Exception as freeze_error:
            error.code = "managed_ctp_projection_unknown_freeze_failed"
            raise error from freeze_error
        if cause is not None:
            raise error from cause
        raise error

    def _read(self, operation, identity, queue_receipt, *, order=None, required):
        try:
            projection = self.reader(operation, identity, queue_receipt)
            if projection is None:
                if not required:
                    return None
                raise ManagedExecutionAdapterError("durable projection is missing")
            if type(projection) is not CtpManagedExecutionProjection:
                raise ManagedExecutionAdapterError("durable projection is untyped")
            require_ctp_managed_execution_projection(
                projection,
                operation=operation,
                managed_intent_id=identity.managed_intent_id,
                runtime_order_id=identity.runtime_order_id,
                managed_cancel_intent_id=getattr(
                    identity, "managed_cancel_intent_id", None
                ),
                local_queue_receipt=queue_receipt,
            )
            if queue_receipt is not None:
                classification = classify_ctp_queue_receipt(
                    queue_receipt,
                    operation=operation,
                    expected_bt_order_ref=(
                        None
                        if operation == "cancel"
                        and queue_receipt.get("bt_order_ref") is None
                        else getattr(order, "ref", None)
                    ),
                    expected_client_order_id=self._info(order, "client_order_id"),
                )
                if classification.queued and projection.state not in (
                    CtpManagedProjectionState.PENDING,
                    CtpManagedProjectionState.UNKNOWN,
                ):
                    raise ManagedExecutionAdapterError(
                        "queued receipt cannot become a local rejection"
                    )
                if not classification.queued and projection.state is not (
                    CtpManagedProjectionState.LOCAL_REJECTED
                ):
                    raise ManagedExecutionAdapterError(
                        "rejected queue lacks durable local rejection evidence"
                    )
        except Exception as error:
            self._unknown(
                operation,
                identity,
                queue_receipt,
                "durable_projection_or_receipt_validation_failed",
                error,
            )
        if projection.state is CtpManagedProjectionState.UNKNOWN:
            try:
                self.freeze(
                    operation, identity, queue_receipt, "durable_projection_is_unknown"
                )
            except Exception as error:
                self._unknown(
                    operation,
                    identity,
                    queue_receipt,
                    "durable_unknown_projection_freeze_failed",
                    error,
                )
        return projection

    def submit_order(self, order, sdk_dispatch):
        try:
            identity = self._identity(order)
        except Exception as error:
            if getattr(error, "managed_unknown", False):
                raise
            self._unknown("submit", None, None, "identity_invalid", error)
        existing = self._read("submit", identity, None, required=False)
        if existing is not None:
            return existing
        try:
            receipt = sdk_dispatch(identity)
        except Exception as error:
            self._unknown("submit", identity, None, "fake_dispatch_failed", error)
        return self._read("submit", identity, receipt, order=order, required=True)

    def cancel_order(self, order_or_ref, dataname, sdk_dispatch):
        try:
            identity = self._identity(order_or_ref, cancel=True)
        except Exception as error:
            if getattr(error, "managed_unknown", False):
                raise
            self._unknown("cancel", None, None, "identity_invalid", error)
        existing = self._read("cancel", identity, None, required=False)
        if existing is not None:
            return existing
        try:
            receipt = sdk_dispatch(identity)
        except Exception as error:
            self._unknown("cancel", identity, None, "fake_dispatch_failed", error)
        return self._read("cancel", identity, receipt, order=order_or_ref, required=True)


@dataclass
class _OrderRequest:
    symbol: str
    account_id: str
    client_order_id: str
    side: _Side
    order_type: _OrderType
    quantity: object
    price: object
    quantity_unit: str
    time_in_force: str
    reduce_only: bool
    runtime_order_id: Optional[str] = None
    managed_intent_id: Optional[str] = None
    hedge_flag: Optional[str] = None
    position_side: Optional[str] = None
    position_id: Optional[str] = None
    offset: Optional[str] = None
    exchange_id: Optional[str] = None
    position_mode: Optional[str] = None
    execution_cycle_id: Optional[str] = None
    execution_role: Optional[str] = None
    strategy_identity_sha256: Optional[str] = None


@dataclass
class _CancelOrderRequest:
    symbol: str
    account_id: str
    runtime_order_id: str
    managed_cancel_intent_id: str
    runtime_action_id: Optional[str] = None
    client_order_id: Optional[str] = None
    order_id: Optional[str] = None
    order_ref: Optional[str] = None


class _AuthorizedFakeRuntime:
    ctp_managed_execution_version = 1

    def __init__(self, *, malformed_submit=False, projection_state=CtpManagedProjectionState.PENDING):
        self.malformed_submit = malformed_submit
        self.projection_state = projection_state
        self.submit_dispatches = []
        self.cancel_dispatches = []
        self.submit_queue_receipts = []
        self.cancel_queue_receipts = []

    def _projection(self, operation, identity, receipt):
        self_state = self.projection_state
        error_code = None
        if receipt.get("queued") is False:
            self_state = CtpManagedProjectionState.LOCAL_REJECTED
            error_code = receipt.get("error_code") or "command_queue_rejected"
        return CtpManagedExecutionProjection(
            operation=operation,
            state=self_state,
            durable_projection_id="outbox:" + operation + ":" + identity.managed_intent_id,
            managed_intent_id=identity.managed_intent_id,
            runtime_order_id=identity.runtime_order_id,
            managed_cancel_intent_id=(
                identity.managed_cancel_intent_id
                if operation == "cancel"
                else None
            ),
            local_queue_receipt_id=receipt.get("receipt_id"),
            error_code=error_code,
        )

    def submit_order(self, order, sdk_dispatch):
        if self.malformed_submit:
            return sdk_dispatch({"managed_intent_id": "intent-1"})
        command = CtpManagedOrderDispatch(
            order=order,
            managed_intent_id="intent-1",
            runtime_order_id=RUNTIME_ORDER_ID,
            hedge_flag="2",
        )
        result = sdk_dispatch(command)
        self.submit_dispatches.append(command)
        self.submit_queue_receipts.append(result)
        return self._projection("submit", command, result)

    def cancel_order(self, order_or_ref, dataname, sdk_dispatch):
        command = CtpManagedCancelDispatch(
            managed_intent_id="intent-1",
            runtime_order_id=RUNTIME_ORDER_ID,
            managed_cancel_intent_id="cancel.intent-1",
        )
        result = sdk_dispatch(command)
        self.cancel_dispatches.append((command, dataname))
        self.cancel_queue_receipts.append(result)
        return self._projection("cancel", command, result)


def _queue_receipt(operation, *, bt_order_ref=7, client_order_id="000000000123", queued=True):
    result = {
        "kind": "command_receipt",
        "command": operation,
        "receipt_id": ("a" if operation == "submit" else "b") * 32,
        "bt_order_ref": bt_order_ref,
        "client_order_id": client_order_id,
        "status": "submitted" if queued else "rejected",
        "queued": queued,
        "priority": "cancel" if operation == "cancel" else "open",
        "queue_depth": 1 if queued else 0,
    }
    if not queued:
        result.update(
            error_code="command_queue_full",
            error_msg="SDK command queue cannot safely accept this command",
        )
    return result


class _FakeDurableProjectionReader:
    """In-memory projection fixture reused across adapter reconstruction.

    This is not process-durable storage. Its freeze list records test behavior;
    it is not an account-wide execution fence.
    """

    def __init__(self):
        self.rows = {}
        self.freezes = []
        self.fail_reads = False

    @staticmethod
    def _key(operation, identity):
        return (
            operation,
            identity.managed_intent_id,
            identity.runtime_order_id,
            getattr(identity, "managed_cancel_intent_id", None),
        )

    def persist(self, operation, identity, receipt, state=CtpManagedProjectionState.PENDING):
        cancel_id = getattr(identity, "managed_cancel_intent_id", None)
        error_code = receipt.get("error_code") if receipt.get("queued") is False else None
        self.rows[self._key(operation, identity)] = CtpManagedExecutionProjection(
            operation=operation,
            state=(
                CtpManagedProjectionState.LOCAL_REJECTED
                if receipt.get("queued") is False
                else state
            ),
            durable_projection_id=(
                "outbox:" + operation + ":" + identity.managed_intent_id
            ),
            managed_intent_id=identity.managed_intent_id,
            runtime_order_id=identity.runtime_order_id,
            managed_cancel_intent_id=cancel_id,
            local_queue_receipt_id=receipt["receipt_id"],
            error_code=error_code,
        )

    def read(self, operation, identity, queue_receipt):
        if self.fail_reads:
            raise OSError("fake durable reader failure")
        return self.rows.get(self._key(operation, identity))

    def freeze(self, operation, identity, queue_receipt, reason):
        self.freezes.append((operation, identity, queue_receipt, reason))


def _store(adapter=None):
    api = _Api()
    store = BtApiStore(
        provider="btapi",
        api=api,
        config={
            "exchange_kwargs": {"CTP": {}},
            "execution_config": {"market_data_only": False, "strategy_id": "strategy"},
        },
        managed_execution_adapter=adapter,
    )
    store._sdk_exchanges = {"CTP": {}}
    store._sdk_command_types.update(
        OrderRequest=_OrderRequest,
        CancelOrderRequest=_CancelOrderRequest,
        OrderType=_OrderType,
        Side=_Side,
    )
    store._sdk_account_id = lambda venue, supplied=None: "account"
    store._validate_managed_ctp_identity_scope = lambda venue, account_id: None
    return store, api


def _order(*, info=None):
    managed_info = {
        "managed_intent_id": "intent-1",
        "managed_order_type": "LIMIT",
        "managed_signal_id": "signal-1",
        "managed_instrument": "rb",
        "managed_position_effect": "OPEN",
        "managed_metadata_version": "metadata.v1",
        "managed_instrument_metadata_digest": "a" * 64,
        "offset": "open",
        "reduce_only": False,
    }
    managed_info.update(info or {})
    return SimpleNamespace(
        ref=7,
        info=managed_info,
        data=SimpleNamespace(_name="rb"),
        isbuy=lambda: True,
        issell=lambda: False,
        size=1,
        price=3500,
        created=SimpleNamespace(price=3500),
        pricelimit=None,
        valid=None,
        tradeid=0,
        exectype=OrderBase.Limit,
    )


def test_managed_ctp_submission_projects_typed_identity_to_sdk_only():
    adapter = _AuthorizedFakeRuntime()
    store, api = _store(adapter)
    dispatched = []

    def enqueue(order, *, ctp_managed_identity=None):
        dispatched.append((order, ctp_managed_identity))
        return _queue_receipt("submit")

    store._enqueue_order_command = enqueue

    result = store.submit_order(_order())

    assert result["kind"] == "managed_execution_projection"
    assert result["state"] == "PENDING"
    assert result["local_queue_receipt_id"] == "a" * 32
    assert len(dispatched) == 1
    assert dispatched[0][1].managed_intent_id == "intent-1"
    assert dispatched[0][1].hedge_flag == "2"
    assert api.submissions == []


def test_managed_ctp_rejects_generic_adapter_and_never_uses_legacy_write():
    class GenericAdapter:
        def __init__(self):
            self.called = False

        def submit_order(self, order, dispatch):
            self.called = True
            return dispatch(order)

    adapter = GenericAdapter()
    api = _Api()

    with pytest.raises(BtApiStoreError, match="typed runtime adapter"):
        BtApiStore(
            provider="btapi",
            api=api,
            config={
                "exchange_kwargs": {"CTP": {}},
                "execution_config": {"market_data_only": False, "strategy_id": "strategy"},
            },
            managed_execution_adapter=adapter,
        )

    assert adapter.called is False
    assert api.submissions == []


def test_managed_ctp_placeholder_is_a_local_rejection_before_queueing():
    adapter = CtpManagedExecutionAdapterPlaceholder(runtime=object())
    store, api = _store(adapter)

    with pytest.raises(
        ManagedExecutionBindingError,
        match="MANAGED_CTP_WRITE_COMPOSITION_UNAVAILABLE",
    ) as raised:
        store.submit_order(_order())

    assert raised.value.managed_local_reject is True
    assert raised.value.definite_reject is True
    assert not store._command_heap
    assert api.submissions == []
    assert api.cancellations == []
    assert api.async_submissions == []
    assert api.async_cancellations == []


def test_fake_ctp_projection_adapter_submit_cancel_and_restart_are_queue_only():
    reader = _FakeDurableProjectionReader()
    runtime = _FakeManagedRuntime()
    adapter = _FakeCtpProjectionAdapter(
        runtime,
        reader=reader.read,
        freeze=reader.freeze,
        hedge_flag="2",
    )
    store, api = _store(adapter)
    submit_calls = []
    cancel_calls = []

    def queue_submit(order, *, ctp_managed_identity=None):
        assert type(ctp_managed_identity) is CtpManagedOrderDispatch
        submit_calls.append(ctp_managed_identity)
        order.info["client_order_id"] = "000000000123"
        order.info["runtime_order_id"] = ctp_managed_identity.runtime_order_id
        receipt = _queue_receipt("submit", bt_order_ref=order.ref)
        reader.persist("submit", ctp_managed_identity, receipt)
        return receipt

    def queue_cancel(identity, dataname):
        assert type(identity) is CtpManagedCancelDispatch
        assert dataname == "rb"
        cancel_calls.append(identity)
        receipt = _queue_receipt("cancel")
        reader.persist("cancel", identity, receipt)
        return receipt

    store._enqueue_order_command = queue_submit
    store._enqueue_ctp_managed_cancel = queue_cancel
    order = _order()

    submitted = store.submit_order(order)
    cancelled = store.cancel_order(order)

    assert submitted["kind"] == cancelled["kind"] == "managed_execution_projection"
    assert submitted["state"] == cancelled["state"] == "PENDING"
    assert submitted["operation"] == "submit"
    assert cancelled["operation"] == "cancel"
    assert submitted["local_queue_receipt_id"] == "a" * 32
    assert cancelled["local_queue_receipt_id"] == "b" * 32
    assert len(submit_calls) == len(cancel_calls) == 1
    assert api.submissions == api.cancellations == []
    assert api.async_submissions == api.async_cancellations == []

    # A new adapter and Store recover the durable rows before asking either
    # queue callback to run again. The framework ref may change after restart.
    restarted_adapter = _FakeCtpProjectionAdapter(
        _FakeManagedRuntime(),
        reader=reader.read,
        freeze=reader.freeze,
        hedge_flag="2",
    )
    restarted_store, restarted_api = _store(restarted_adapter)

    def unexpected_submit(*_args, **_kwargs):
        raise AssertionError("recovered submit was queued again")

    def unexpected_cancel(*_args, **_kwargs):
        raise AssertionError("recovered cancel was queued again")

    restarted_store._enqueue_order_command = unexpected_submit
    restarted_store._enqueue_ctp_managed_cancel = unexpected_cancel
    replay_order = _order()
    replay_order.ref = 9001

    replayed_submit = restarted_store.submit_order(replay_order)
    replayed_cancel = restarted_store.cancel_order(replay_order)

    assert replayed_submit["state"] == replayed_cancel["state"] == "PENDING"
    assert replayed_submit["runtime_order_id"] == submitted["runtime_order_id"]
    assert replayed_cancel["managed_cancel_intent_id"] == cancelled[
        "managed_cancel_intent_id"
    ]
    assert len(submit_calls) == len(cancel_calls) == 1
    assert restarted_api.submissions == restarted_api.cancellations == []


def test_fake_ctp_cancel_accepts_a_recovered_binding_without_framework_ref():
    reader = _FakeDurableProjectionReader()
    runtime = _FakeManagedRuntime()
    adapter = _FakeCtpProjectionAdapter(
        runtime,
        reader=reader.read,
        freeze=reader.freeze,
        hedge_flag="2",
    )
    store, api = _store(adapter)
    order = _order(
        info={
            "client_order_id": "000000000123",
            "runtime_order_id": _managed_runtime_order_id(runtime.scope, "intent-1"),
        }
    )
    order.ref = 9001
    queued = []

    def queue_cancel(identity, _dataname):
        queued.append(identity)
        receipt = _queue_receipt("cancel", bt_order_ref=None)
        reader.persist("cancel", identity, receipt)
        return receipt

    store._enqueue_ctp_managed_cancel = queue_cancel

    result = store.cancel_order(order)

    assert result["state"] == "PENDING"
    assert len(queued) == 1
    assert api.cancellations == api.async_cancellations == []


def test_fake_ctp_adapter_does_not_claim_at_most_once_without_durable_reservation():
    reader = _FakeDurableProjectionReader()
    adapter = _FakeCtpProjectionAdapter(
        _FakeManagedRuntime(),
        reader=reader.read,
        freeze=reader.freeze,
        hedge_flag="2",
    )
    store, api = _store(adapter)
    queued = []

    def queue_without_persisting(order, *, ctp_managed_identity=None):
        queued.append(ctp_managed_identity)
        order.info["client_order_id"] = "000000000123"
        order.info["runtime_order_id"] = ctp_managed_identity.runtime_order_id
        return _queue_receipt("submit", bt_order_ref=order.ref)

    store._enqueue_order_command = queue_without_persisting
    for _ in range(2):
        with pytest.raises(ManagedCtpHandoffError) as raised:
            store.submit_order(_order())
        assert raised.value.managed_execution_state == "UNKNOWN"

    assert len(queued) == 2
    assert len(reader.freezes) == 2
    assert api.submissions == api.cancellations == []
    assert api.async_submissions == api.async_cancellations == []


@pytest.mark.parametrize("failure", ("missing_projection", "receipt_mismatch", "reader_error"))
def test_fake_ctp_projection_failures_freeze_and_surface_unknown_without_fallback(failure):
    reader = _FakeDurableProjectionReader()
    adapter = _FakeCtpProjectionAdapter(
        _FakeManagedRuntime(),
        reader=reader.read,
        freeze=reader.freeze,
        hedge_flag="2",
    )
    store, api = _store(adapter)
    queued = []

    def queue_submit(order, *, ctp_managed_identity=None):
        queued.append(ctp_managed_identity)
        order.info["client_order_id"] = "000000000123"
        order.info["runtime_order_id"] = ctp_managed_identity.runtime_order_id
        receipt = _queue_receipt(
            "submit",
            bt_order_ref=order.ref,
            client_order_id=(
                "000000000999" if failure == "receipt_mismatch" else "000000000123"
            ),
        )
        if failure == "receipt_mismatch":
            reader.persist("submit", ctp_managed_identity, receipt)
        return receipt

    store._enqueue_order_command = queue_submit
    if failure == "reader_error":
        reader.fail_reads = True

    with pytest.raises(ManagedCtpHandoffError) as raised:
        store.submit_order(_order())

    assert raised.value.managed_execution_state == "UNKNOWN"
    assert raised.value.execution_unknown is True
    assert reader.freezes
    assert reader.freezes[0][0] == "submit"
    assert len(queued) == (0 if failure == "reader_error" else 1)
    assert api.submissions == api.cancellations == []
    assert api.async_submissions == api.async_cancellations == []


@pytest.mark.parametrize("failure", ("missing_projection", "receipt_mismatch"))
def test_fake_ctp_cancel_projection_failures_freeze_and_surface_unknown(failure):
    reader = _FakeDurableProjectionReader()
    runtime = _FakeManagedRuntime()
    adapter = _FakeCtpProjectionAdapter(
        runtime,
        reader=reader.read,
        freeze=reader.freeze,
        hedge_flag="2",
    )
    store, api = _store(adapter)
    order = _order(
        info={
            "client_order_id": "000000000123",
            "runtime_order_id": _managed_runtime_order_id(runtime.scope, "intent-1"),
        }
    )
    queued = []

    def queue_cancel(identity, _dataname):
        queued.append(identity)
        receipt = _queue_receipt(
            "cancel",
            client_order_id=(
                "000000000999" if failure == "receipt_mismatch" else "000000000123"
            ),
        )
        if failure == "receipt_mismatch":
            reader.persist("cancel", identity, receipt)
        return receipt

    store._enqueue_ctp_managed_cancel = queue_cancel

    with pytest.raises(ManagedCtpHandoffError) as raised:
        store.cancel_order(order)

    assert raised.value.managed_execution_state == "UNKNOWN"
    assert raised.value.execution_unknown is True
    assert reader.freezes
    assert reader.freezes[0][0] == "cancel"
    assert len(queued) == 1
    assert api.submissions == api.cancellations == []
    assert api.async_submissions == api.async_cancellations == []


def test_managed_ctp_rejects_caller_owned_provider_identifiers_before_adapter():
    adapter = _AuthorizedFakeRuntime()
    store, api = _store(adapter)

    with pytest.raises(BtApiStoreError, match="caller-supplied"):
        store.submit_order(_order(info={"managed_intent_id": "intent-1", "client_order_id": "77"}))

    assert adapter.submit_dispatches == []
    assert api.submissions == []


def test_managed_ctp_rejects_untyped_adapter_projection_without_direct_fallback():
    adapter = _AuthorizedFakeRuntime(malformed_submit=True)
    store, api = _store(adapter)

    with pytest.raises(ManagedCtpHandoffError) as raised:
        store.submit_order(_order())

    assert raised.value.managed_execution_state == "UNKNOWN"
    assert raised.value.managed_projection_pending is True
    assert api.submissions == []


@pytest.mark.parametrize("response_kind", ("queue", "unknown_classification"))
def test_managed_ctp_real_queue_fails_before_second_orderref_allocator(
    response_kind,
):
    class RawQueueRuntime(_AuthorizedFakeRuntime):
        def submit_order(self, order, sdk_dispatch):
            command = CtpManagedOrderDispatch(
                order=order,
                managed_intent_id="intent-1",
                runtime_order_id=RUNTIME_ORDER_ID,
                hedge_flag="2",
            )
            receipt = sdk_dispatch(command)
            self.submit_queue_receipts.append(receipt)
            if response_kind == "queue":
                return receipt
            return classify_ctp_queue_receipt(
                receipt,
                operation="submit",
                expected_bt_order_ref=7,
                expected_client_order_id="000000000123",
            )

    adapter = RawQueueRuntime()
    store, api = _store(adapter)
    store._sdk_exchange = lambda _symbol: "CTP"
    store._ensure_api_ready = lambda: api
    store._require_async_sdk_commands = lambda: None
    store._start_command_worker = lambda: None

    with pytest.raises(BtApiStoreError, match="single execution outbox") as raised:
        store.submit_order(_order())

    assert raised.value.managed_local_reject is True
    assert raised.value.definite_reject is True
    assert adapter.submit_queue_receipts == []
    assert store._command_heap == []
    assert api.submissions == []
    assert api.cancellations == []
    assert api.async_submissions == []
    assert api.async_cancellations == []


def test_managed_ctp_order_request_refuses_a_second_orderref_allocator():
    adapter = _AuthorizedFakeRuntime()
    store, api = _store(adapter)
    payload = {
        "symbol": "rb",
        "bt_order_ref": 7,
        "side": "buy",
        "size": 1,
        "price": 3500,
        "order_type": "limit",
        "runtime_order_id": RUNTIME_ORDER_ID,
        "managed_intent_id": "intent-1",
        "hedge_flag": "2",
    }

    with pytest.raises(BtApiStoreError, match="single execution outbox"):
        store._sdk_order_request("CTP", payload)

    assert api.reservations == []
    assert api.binding_reads == 0


def test_managed_ctp_order_request_rejects_sdk_model_without_identity_fields():
    class OldOrderRequest:
        def __init__(self, symbol, runtime_order_id):
            self.symbol = symbol
            self.runtime_order_id = runtime_order_id

    with pytest.raises(BtApiStoreError, match="lacks managed CTP identity fields"):
        BtApiStore._require_sdk_request_model_fields(
            OldOrderRequest,
            ("managed_intent_id", "runtime_order_id", "hedge_flag"),
            "OrderRequest",
        )


def test_managed_ctp_cancel_projects_durable_cancel_id_without_native_ids():
    adapter = _AuthorizedFakeRuntime()
    store, api = _store(adapter)
    binding = {
        "symbol": "rb",
        "exchange_name": "CTP",
        "account_id": "account",
        "runtime_order_id": RUNTIME_ORDER_ID,
        "managed_intent_id": "intent-1",
        "bt_order_ref": 7,
        "client_order_id": "000000000123",
    }
    store._sdk_runtime_refs[("CTP", RUNTIME_ORDER_ID)] = binding
    queued = []
    store._ensure_api_ready = lambda: api
    store._require_async_sdk_commands = lambda: None
    store._start_command_worker = lambda: None
    store._enqueue_sdk_command = lambda command, *, priority_name: queued.append(
        (command, priority_name)
    ) or _queue_receipt("cancel")

    command = CtpManagedCancelDispatch(
        managed_intent_id="intent-1",
        runtime_order_id=RUNTIME_ORDER_ID,
        managed_cancel_intent_id="cancel.intent-1",
    )
    with pytest.raises(BtApiStoreError, match="single execution outbox"):
        store._enqueue_ctp_managed_cancel(command, "rb")

    assert queued == []
    assert api.cancellations == []


def test_managed_ctp_cancel_rejects_missing_native_order_ref_before_queueing():
    adapter = _AuthorizedFakeRuntime()
    store, api = _store(adapter)
    store._sdk_runtime_refs[("CTP", RUNTIME_ORDER_ID)] = {
        "symbol": "rb",
        "exchange_name": "CTP",
        "account_id": "account",
        "runtime_order_id": RUNTIME_ORDER_ID,
        "managed_intent_id": "intent-1",
        "bt_order_ref": 7,
    }
    queued = []
    store._enqueue_sdk_command = lambda command, *, priority_name: queued.append(command)

    with pytest.raises(BtApiStoreError, match="single execution outbox"):
        store._enqueue_ctp_managed_cancel(
            CtpManagedCancelDispatch(
                managed_intent_id="intent-1",
                runtime_order_id=RUNTIME_ORDER_ID,
                managed_cancel_intent_id="cancel.intent-1",
            ),
            "rb",
        )

    assert queued == []
    assert api.cancellations == []


def test_managed_ctp_cancel_uses_the_typed_adapter_dispatch_callback():
    adapter = _AuthorizedFakeRuntime()
    store, api = _store(adapter)
    dispatched = []
    store._enqueue_ctp_managed_cancel = lambda identity, dataname: dispatched.append(
        (identity, dataname)
    ) or _queue_receipt("cancel")

    result = store.cancel_order(_order())

    assert result["kind"] == "managed_execution_projection"
    assert result["state"] == "PENDING"
    assert result["operation"] == "cancel"
    assert len(dispatched) == 1
    assert dispatched[0][0].managed_cancel_intent_id == "cancel.intent-1"
    assert dispatched[0][1] == "rb"
    assert api.cancellations == []


def test_managed_ctp_orderref_from_sdk_ledger_is_not_reused_as_second_authority():
    """A separate bt_api_py OrderRef ledger cannot satisfy the shared outbox port."""

    scope = SimpleNamespace(
        provider="CTP",
        strategy_id="strategy",
        environment="sandbox",
        key="scope:" + ("b" * 64),
    )
    intent_id = "intent.e2e"
    runtime_order_id = _managed_runtime_order_id(scope, intent_id)

    class FakeComposedRuntime(_AuthorizedFakeRuntime):
        def submit_order(self, order, sdk_dispatch):
            identity = CtpManagedOrderDispatch(
                order=order,
                managed_intent_id=intent_id,
                runtime_order_id=runtime_order_id,
                hedge_flag="2",
            )
            receipt = sdk_dispatch(identity)
            return self._projection("submit", identity, receipt)

        def cancel_order(self, order_or_ref, dataname, sdk_dispatch):
            identity = CtpManagedCancelDispatch(
                managed_intent_id=intent_id,
                runtime_order_id=runtime_order_id,
                managed_cancel_intent_id="cancel.intent.e2e",
            )
            receipt = sdk_dispatch(identity)
            return self._projection("cancel", identity, receipt)

    adapter = FakeComposedRuntime()
    store, api = _store(adapter)
    order = _order(info={"managed_intent_id": intent_id})
    caller_order_info = dict(order.info)
    with pytest.raises(BtApiStoreError, match="single execution outbox"):
        store.submit_order(order)

    assert adapter.submit_dispatches == []
    assert store._sdk_runtime_refs == {}
    assert store._sdk_client_refs == {}
    assert "client_order_id" not in caller_order_info
    assert "runtime_order_id" not in caller_order_info
    assert "client_order_id" not in order.info
    assert "runtime_order_id" not in order.info
    assert api.reservations == []
    assert api.binding_reads == 0
    assert api.submissions == []
    assert api.cancellations == []


def test_real_store_queue_receipts_classify_submit_and_recovered_cancel_as_unknown():
    """Use the Store's actual queue envelope, with only local fake ports."""

    adapter = _AuthorizedFakeRuntime()
    store, api = _store(adapter)
    store._sdk_exchange = lambda _symbol: "CTP"
    store._ensure_api_ready = lambda: api
    store._require_async_sdk_commands = lambda: None
    # The queue itself is exercised, but its background dispatcher must stay
    # stopped so this integration test cannot reach an SDK/provider method.
    store._start_command_worker = lambda: None

    order = _order()
    with pytest.raises(BtApiStoreError, match="single execution outbox"):
        store.submit_order(order)

    assert adapter.submit_queue_receipts == []
    assert adapter.cancel_queue_receipts == []
    assert store._command_heap == []
    assert api.submissions == []
    assert api.cancellations == []
