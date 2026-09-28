"""Typed managed CTP Store composition tests; all ports are local fakes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Optional

import pytest

from backtrader.order import OrderBase
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from backtrader.stores.managed_execution import (
    CtpManagedCancelDispatch,
    CtpManagedExecutionProjection,
    CtpManagedOrderDispatch,
    CtpManagedProjectionState,
    ManagedExecutionAdapterError,
    require_ctp_managed_execution_projection,
)
from backtrader_runtime.managed_execution import (
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


# Prior Store-local CTP fakes are retained as migration rows, not authority.
_LEGACY_CTP_STORE_CASES = (
    ('test_managed_ctp_submission_projects_typed_identity_to_sdk_only', 'local fake adapter projects typed submit identity through the SDK queue', 'future external Actor migration', 'An authenticated actor accepts the exact signed submit intent, atomically claims its durable identity, and returns a typed receipt bound to account, epoch, and request digest; caller/provider IDs remain rejected.'),
    ('test_managed_ctp_rejects_generic_adapter_and_never_uses_legacy_write', 'generic local adapter used to reach adapter-type validation before writes', 'current fail-closed assertion; future external Actor adapter contract', 'A configured external Actor endpoint is authenticated and versioned; only its typed submit/cancel API is reachable, while generic adapters and legacy dispatch callbacks reject before side effects.'),
    ('test_managed_ctp_placeholder_is_a_local_rejection_before_queueing', 'local placeholder used to reject at submit after Store creation', 'current earlier fail-closed assertion', 'Without external Actor readiness, Store construction or admission remains unavailable; an actor-authenticated explicit local rejection may be surfaced only after trusted actor validation.'),
    ('test_fake_ctp_projection_adapter_submit_cancel_and_restart_are_queue_only', 'fake submit/cancel projection and in-memory restart replay', 'future external Actor and durable recovery migration', 'After restart, the actor reads the same durable account ledger and returns the existing submit/cancel disposition for the exact intent without re-enqueue; no in-memory reader or caller seed supplies history.'),
    ('test_fake_ctp_cancel_accepts_a_recovered_binding_without_framework_ref', 'fake recovered cancel mapping without a framework ref', 'future external Actor and durable recovery migration', 'Actor obtains and validates a durable same-account order binding, then authorizes cancel identity from that binding; no caller/framework reference can substitute for the ledger row.'),
    ('test_fake_ctp_adapter_does_not_claim_at_most_once_without_durable_reservation', 'fake reader demonstrates duplicate queues absent durable reserve', 'future external Actor durable-reservation migration', 'Concurrent/restarted attempts for one scoped intent yield exactly one durable actor claim; UNKNOWN retains the claim and never causes local redispatch.'),
    ('test_fake_ctp_projection_failures_freeze_and_surface_unknown_without_fallback[missing_projection]', 'submit missing projection yields UNKNOWN and freezes', 'future external Actor receipt/projection migration', 'An authenticated actor receipt must resolve to a matching durable submit projection; absent projection remains UNKNOWN, fences the intent, and cannot invoke local SDK fallback.'),
    ('test_fake_ctp_projection_failures_freeze_and_surface_unknown_without_fallback[receipt_mismatch]', 'submit receipt mismatch yields UNKNOWN and freezes', 'future external Actor receipt/projection migration', 'The actor receipt and durable projection must bind the same command ID, account, epoch, intent, and digest; any mismatch is UNKNOWN and fenced.'),
    ('test_fake_ctp_projection_failures_freeze_and_surface_unknown_without_fallback[reader_error]', 'submit projection read failure yields UNKNOWN and freezes', 'future external Actor receipt/projection migration', 'Actor ledger unavailability after a possible dispatch is UNKNOWN; retain durable claim and query through the authenticated actor, never retry through local SDK.'),
    ('test_fake_ctp_cancel_projection_failures_freeze_and_surface_unknown[missing_projection]', 'cancel missing projection yields UNKNOWN and freezes', 'future external Actor receipt/projection migration', 'A cancel dispatch without a matching durable actor projection remains UNKNOWN and frozen; retry requires actor-owned reconciliation evidence.'),
    ('test_fake_ctp_cancel_projection_failures_freeze_and_surface_unknown[receipt_mismatch]', 'cancel receipt mismatch yields UNKNOWN and freezes', 'future external Actor receipt/projection migration', 'Cancel receipt and actor projection must match exact cancel ID, target order, account, epoch, and digest; mismatch is UNKNOWN with no fallback.'),
    ('test_managed_ctp_rejects_caller_owned_provider_identifiers_before_adapter', 'caller native identifier must reject before local adapter', 'current earlier fail-closed assertion; retain identity rule in future Actor contract', 'Caller-supplied OrderRef/ActionRef/client IDs are rejected before actor dispatch; the authenticated actor allocates and durably binds provider identifiers.'),
    ('test_managed_ctp_rejects_untyped_adapter_projection_without_direct_fallback', 'untyped fake receipt must not trigger direct fallback', 'future external Actor typed-receipt migration', 'Only a versioned authenticated actor receipt with exact operation/context/identity/digest is accepted; malformed or unknown responses fence the command and never trigger direct fallback.'),
    ('test_managed_ctp_real_queue_fails_before_second_orderref_allocator[queue]', 'queued submit receipt must stop a second local OrderRef allocator', 'future external Actor/ledger integration', 'One actor-owned durable allocator supplies OrderRef exactly once across crash/restart; local Store/SDK ledgers cannot allocate a second reference.'),
    ('test_managed_ctp_real_queue_fails_before_second_orderref_allocator[unknown_classification]', 'unknown submit classification must stop a second allocator', 'future external Actor/ledger integration', 'An unclassified actor/queue response keeps the single allocation claim UNKNOWN and blocks every allocator/retry until trusted reconciliation.'),
    ('test_managed_ctp_order_request_refuses_a_second_orderref_allocator', 'Store request path rejects second OrderRef source', 'current earlier fail-closed assertion; retain allocator invariant in future Actor contract', 'The request builder consumes the actor-reserved typed OrderRef without allocating another; a pure model check must still require the identity fields.'),
    ('test_managed_ctp_cancel_projects_durable_cancel_id_without_native_ids', 'fake cancel projects durable cancel ID without native IDs', 'future external Actor durable cancel migration', 'The actor derives/claims a stable cancel ID from the durable target binding and intent; native IDs are supplied only by actor-owned ledger evidence.'),
    ('test_managed_ctp_cancel_rejects_missing_native_order_ref_before_queueing', 'missing native order ref must not queue cancel', 'current earlier fail-closed assertion; retain validation in future Actor contract', 'If the actor cannot prove the durable native order binding, cancel rejects before provider dispatch and records no guessed identifier.'),
    ('test_managed_ctp_cancel_uses_the_typed_adapter_dispatch_callback', 'typed local adapter receives cancel callback', 'future external Actor dispatch migration', 'Store sends only a typed cancel command to the authenticated actor; no caller callback can directly reach a local SDK write method.'),
    ('test_managed_ctp_orderref_from_sdk_ledger_is_not_reused_as_second_authority', 'SDK OrderRef ledger cannot substitute for single durable outbox', 'future external Actor and shared-ledger migration', 'The actor-owned shared durable outbox is the sole allocator/recovery authority; SDK-local OrderRef history is evidence only and cannot authorize a second dispatch.'),
    ('test_real_store_queue_receipts_classify_submit_and_recovered_cancel_as_unknown', 'actual Store queue receipt classification for submit and recovered cancel', 'future external Actor receipt integration', 'Local enqueue receipt remains non-authorizing UNKNOWN; actor reconciliation must bind the same durable account command and provider observation before changing state.'),
)


class _FailClosedAdapterProbe:
    def __init__(self):
        self.calls = []

    def submit_order(self, *args, **kwargs):
        self.calls.append(("submit", args, kwargs))
        raise AssertionError("local CTP adapter was invoked before external Actor admission")

    def cancel_order(self, *args, **kwargs):
        self.calls.append(("cancel", args, kwargs))
        raise AssertionError("local CTP adapter was invoked before external Actor admission")


class _FailClosedCredentialProbe:
    def __init__(self):
        self.reads = []

    def __bool__(self):
        self.reads.append("bool")
        raise AssertionError("credential was touched before CTP route closure")

    def __str__(self):
        self.reads.append("str")
        raise AssertionError("credential was touched before CTP route closure")


class _RouteEnvironmentProbe:
    def __init__(self, delegate):
        self.delegate = delegate
        self.reads = []

    def get(self, key, default=None):
        if key in {"BT_STORE_PROVIDER", "BT_GATEWAY_EXCHANGE_TYPE"}:
            self.reads.append(key)
        return self.delegate.get(key, default)


@pytest.mark.parametrize(
    ("legacy_case", "former_local_expectation", "disposition", "future_actor_contract"),
    _LEGACY_CTP_STORE_CASES,
    ids=[case[0] for case in _LEGACY_CTP_STORE_CASES],
)
def test_legacy_ctp_store_composition_is_now_explicitly_fail_closed(
    monkeypatch, legacy_case, former_local_expectation, disposition, future_actor_contract
):
    """Each legacy local-CTP composition case now proves the admission boundary."""
    from backtrader.stores import btapistore as store_module

    api = _Api()
    adapter = _FailClosedAdapterProbe()
    credential = _FailClosedCredentialProbe()
    environment = _RouteEnvironmentProbe(store_module.os.environ)
    monkeypatch.setattr(store_module, "os", SimpleNamespace(environ=environment))
    resolver_calls = []

    def forbidden(*args, **kwargs):
        resolver_calls.append((args, kwargs))
        raise AssertionError("local resolver/client reached before CTP actor gate")

    monkeypatch.setattr(BtApiStore, "_resolve_provider", forbidden)
    monkeypatch.setattr(BtApiStore, "_apply_env_gateway_overrides", forbidden)
    monkeypatch.setattr(BtApiStore, "_create_forwarding_client", forbidden)
    monkeypatch.setattr(store_module, "_resolve_bt_api_client", forbidden)

    with pytest.raises(BtApiStoreError, match="external account actor unavailable"):
        BtApiStore(
            provider="btapi",
            api=api,
            config={
                "exchange_kwargs": {"CTP": {}},
                "execution_config": {
                    "market_data_only": False,
                    "strategy_id": "strategy",
                },
                "execution_authorization_secret": credential,
            },
            managed_execution_adapter=adapter,
            autostart=True,
        )

    assert legacy_case.startswith("test_")
    assert former_local_expectation
    assert disposition
    assert future_actor_contract
    assert environment.reads == []
    assert credential.reads == []
    assert adapter.calls == []
    assert resolver_calls == []
    assert api.submissions == []
    assert api.cancellations == []
    assert api.async_submissions == []
    assert api.async_cancellations == []
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










