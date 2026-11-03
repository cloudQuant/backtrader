"""Managed execution adapter backed by the SDK service execution client.

``BtApiStore`` accepts one deliberate ``managed_execution_adapter`` port.  This
adapter fills that port with the authenticated execution service: the store
keeps its order projection and the service keeps the durable intent, admission
and provider dispatch.  The adapter is a borrowed facade over an injected SDK
client; it never starts a thread, never registers, and never calls the private
SDK dispatcher, because a missing journal, permit or provider fact must not
become an accidental direct write.

Managed order identity is read from the framework metadata the broker already
publishes (``managed_intent_id``, ``managed_signal_id``, ``managed_instrument``,
``managed_position_effect``, ``managed_metadata_version``).  A response is
always one of three shapes the broker already understands: an accepted
projection carrying the provider order identity, a nonterminal unknown
projection, or a structured rejection.  An uncertain submit outcome stays
visible as an unreconciled order; a failed durable read raises a typed error so
the broker can preserve that order and the caller can back off.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from ._service_execution_recovery import (
    ServiceExecutionAdapterError as ServiceExecutionAdapterError,
    ServiceExecutionReadError as ServiceExecutionReadError,
    ServiceExecutionRecoveryMixin,
    _data_name,
    _order_recovery_binding,
    _recovery_error_code,
    _reference,
)


#: Durable states whose provider order identity is confirmed, mapped onto the
#: status vocabulary the Broker already normalizes.
_ACCEPTED_STATES = {
    "ACKED": "accepted",
    "PARTIALLY_FILLED": "partial",
    "FILLED": "completed",
}

#: States that also carry provider fill facts worth projecting.
_FILLED_STATES = frozenset({"PARTIALLY_FILLED", "FILLED"})

#: Durable states that end the framework order locally.
_REJECTED_STATES = frozenset({"REJECTED", "BLOCKED"})

_DEFAULT_METADATA_VERSION = "backtrader.service-execution.v1"


class ServiceExecutionAdapter(ServiceExecutionRecoveryMixin):
    """Project framework orders onto one authenticated execution service."""

    #: The service owns provider dispatch; the store must not treat this
    #: adapter as a local provider fill projection.
    managed_provider_projection_enabled = False

    def __init__(
        self,
        client: Any,
        *,
        metadata_version: str = _DEFAULT_METADATA_VERSION,
        order_ref_factory: Optional[Callable[[Any], str]] = None,
        recovery_flow: Any = None,
        require_recovery_baseline: bool = False,
        recovery_event_version: int = 1,
    ) -> None:
        if not callable(getattr(client, "submit", None)):
            raise ServiceExecutionAdapterError("service execution adapter requires submit")
        if not callable(getattr(client, "cancel", None)):
            raise ServiceExecutionAdapterError("service execution adapter requires cancel")
        if type(metadata_version) is not str or not metadata_version.strip():
            raise ServiceExecutionAdapterError("invalid metadata_version")
        if order_ref_factory is not None and not callable(order_ref_factory):
            raise ServiceExecutionAdapterError("invalid order_ref_factory")
        recovery_manifest_type = None
        recovery_owner_projection_type = None
        recovery_owner_projection_validator = None
        recovery_position_ref_type = None
        if recovery_flow is not None:
            if not callable(getattr(client, "build_submit_payload", None)):
                raise ServiceExecutionAdapterError(
                    "service recovery requires the SDK submit payload builder"
                )
            try:
                from bt_api_py.service_recovery import (
                    ServiceRecoveryManifest,
                    ServiceRecoveryOwnerProjectionV1,
                    StrategyPositionRefV1,
                    is_service_recovery_owner_record,
                    recovery_flow_is_usable,
                )
            except ImportError as error:
                raise ServiceExecutionAdapterError(
                    "service recovery SDK unavailable"
                ) from error
            if not recovery_flow_is_usable(recovery_flow):
                raise ServiceExecutionAdapterError("invalid recovery flow")
            recovery_manifest_type = ServiceRecoveryManifest
            recovery_owner_projection_type = ServiceRecoveryOwnerProjectionV1
            recovery_owner_projection_validator = is_service_recovery_owner_record
            recovery_position_ref_type = StrategyPositionRefV1
        try:
            from bt_api_py.service_execution_workflow import (
                ServiceExecutionCancelRequestV1,
                ServiceExecutionOutcomeV1,
                ServiceExecutionSubmitRequestV1,
                ServiceExecutionWorkflow,
            )
        except ImportError as error:
            raise ServiceExecutionAdapterError(
                "service execution workflow SDK unavailable"
            ) from error
        if type(recovery_event_version) is not int or recovery_event_version not in {1, 2}:
            raise ServiceExecutionAdapterError("invalid recovery event version")
        if recovery_event_version == 2 and (
            recovery_flow is None or not require_recovery_baseline
        ):
            raise ServiceExecutionAdapterError(
                "recovery event version requires a durable owner baseline"
            )

        self._client = client
        self._workflow = ServiceExecutionWorkflow(
            client,
            recovery_flow,
            recovery_event_version=recovery_event_version,
        )
        self._workflow_submit_request_type = ServiceExecutionSubmitRequestV1
        self._workflow_cancel_request_type = ServiceExecutionCancelRequestV1
        self._workflow_outcome_type = ServiceExecutionOutcomeV1
        self._metadata_version = metadata_version
        self._order_ref_factory = order_ref_factory
        self._recovery_flow = recovery_flow
        self._recovery_manifest_type = recovery_manifest_type
        self._recovery_owner_projection_type = recovery_owner_projection_type
        self._recovery_owner_projection_validator = recovery_owner_projection_validator
        self._recovery_position_ref_type = recovery_position_ref_type
        self._require_recovery_baseline = bool(require_recovery_baseline)
        self._recovery_event_version = recovery_event_version
        self._recovery_intent_context_resolver: Optional[Callable[[Any], Any]] = None
        #: Intent identities this adapter instance already returned to the
        #: framework.  A durable record proves a provider dispatch; it is not
        #: permission to mutate the current in-memory Broker twice.
        self._returned_intents: set[str] = set()
        #: Last durable revision projected per intent, so a repeated refresh
        #: of an unchanged record is reported as a replay.
        self._projected_revisions: dict[str, Any] = {}
        #: Intents for which this adapter has actually seen a durable record.
        self._known_record_intents: set[str] = set()

    # -- submission ---------------------------------------------------------

    def submit_order(self, order: Any, sdk_dispatch: Any) -> Mapping[str, Any]:
        """Submit one framework order through the execution service.

        ``sdk_dispatch`` is accepted only to satisfy the Store port.  It is
        never invoked: routing a service-managed order through the direct
        provider path would bypass the durable intent and its admission.
        """

        del sdk_dispatch
        identity = _managed_identity(order, self._metadata_version)
        if identity is None:
            return _rejection(
                "managed_order_metadata_missing",
                "Managed order metadata is incomplete; the intent was not routed.",
                order=order,
            )
        content = _order_content(order)
        if content is None:
            return _rejection(
                "managed_order_content_unsupported",
                "Order type or size cannot be expressed as a managed intent.",
                order=order,
                intent_id=identity["intent_id"],
            )
        if (
            self._recovery_flow is not None
            and self._recovery_event_version == 2
            and content["order_type"] != "MARKET"
        ):
            return _rejection(
                "service_execution_recovery_v2_requires_market_order",
                "Managed-paper recovery V2 accepts only MARKET/FOK intents.",
                order=order,
                intent_id=identity["intent_id"],
            )

        time_in_force = _time_in_force_of(
            order,
            default=(
                "FOK"
                if self._recovery_flow is not None
                and self._recovery_event_version == 2
                else "GTC"
            ),
        )
        if time_in_force is None:
            return _rejection(
                "managed_order_time_in_force_unsupported",
                "Time in force must be one of GTC, IOC, FOK, or DAY.",
                order=order,
                intent_id=identity["intent_id"],
            )
        if (
            self._recovery_flow is not None
            and self._recovery_event_version == 2
            and time_in_force != "FOK"
        ):
            return _rejection(
                "service_execution_recovery_v2_requires_market_order",
                "Managed-paper recovery V2 accepts only MARKET/FOK intents.",
                order=order,
                intent_id=identity["intent_id"],
            )

        tags = _tags(order, self._order_ref_factory)
        recovery_binding = None
        strategy_position_owner_payload = None
        local_position_key_ref = None
        intent_context = None
        if self._recovery_flow is not None:
            namespace_error = self._validate_recovery_order_scope(order)
            if namespace_error is not None:
                return _rejection(
                    namespace_error,
                    "The order owner does not match the explicit recovery namespace.",
                    order=order,
                    intent_id=identity["intent_id"],
                )
            if self._recovery_flow.namespace is None:
                return _rejection(
                    "service_execution_recovery_not_bound",
                    "The managed session did not bind an authenticated recovery scope.",
                    order=order,
                    intent_id=identity["intent_id"],
                )
            recovery_binding = _order_recovery_binding(order)
            if recovery_binding is None:
                return _rejection(
                    "service_execution_recovery_binding_missing",
                    "Recovery requires a stable data name and integer trade id.",
                    order=order,
                    intent_id=identity["intent_id"],
                )
            if self._recovery_event_version == 2:
                try:
                    needs_context = self._workflow.requires_intent_context(
                        identity["intent_id"]
                    )
                except Exception as error:  # noqa: BLE001 - recovery read fails closed
                    return _rejection(
                        _error_code(error),
                        "The durable recovery context could not be verified.",
                        order=order,
                        intent_id=identity["intent_id"],
                    )
                if needs_context:
                    resolver = self._recovery_intent_context_resolver
                    if not callable(resolver):
                        return _rejection(
                            "service_execution_recovery_intent_context_unavailable",
                            "The framework could not capture neutral recovery facts.",
                            order=order,
                            intent_id=identity["intent_id"],
                        )
                    try:
                        resolved_context = resolver(order)
                    except Exception as error:  # noqa: BLE001 - context is a local precondition
                        code = _recovery_error_code(error)
                        return _rejection(
                            f"service_execution_{code.lower()}",
                            "The framework could not capture neutral recovery facts.",
                            order=order,
                            intent_id=identity["intent_id"],
                        )
                    if not isinstance(resolved_context, Mapping):
                        return _rejection(
                            "service_execution_recovery_intent_context_unavailable",
                            "The framework could not capture neutral recovery facts.",
                            order=order,
                            intent_id=identity["intent_id"],
                        )
                    intent_context = deepcopy(dict(resolved_context))
                try:
                    (
                        recovery_binding,
                        strategy_position_owner_payload,
                        local_position_key_ref,
                    ) = self._strategy_position_binding_for_order(
                        order, identity["intent_id"]
                    )
                except Exception as error:  # noqa: BLE001 - identity mapping is a precondition
                    return _rejection(
                        _recovery_error_code(error),
                        "The Strategy-local position identity could not be verified.",
                        order=order,
                        intent_id=identity["intent_id"],
                    )
                self._attach_strategy_position_ref(
                    order,
                    local_position_key_ref,
                    recovery_binding.get("strategy_position_ref"),
                )

        request = self._workflow_submit_request_type(
            intent_id=identity["intent_id"],
            signal_id=identity["signal_id"],
            instrument=identity["instrument"],
            side=content["side"],
            position_effect=identity["position_effect"],
            order_type=content["order_type"],
            quantity=content["quantity"],
            price=content["price"],
            time_in_force=time_in_force,
            reduce_only=identity["reduce_only"],
            metadata_version=identity["metadata_version"],
            deadline_ns=None,
            tags=tags,
            recovery_binding=recovery_binding,
            strategy_position_owner_payload=strategy_position_owner_payload,
            intent_context=intent_context,
        )
        try:
            outcome = self._workflow.submit(request)
        except Exception as error:  # noqa: BLE001 - dispatch certainty is unavailable
            return _unknown_submission_projection(
                _error_code(error), order=order, intent_id=identity["intent_id"]
            )
        if type(outcome) is not self._workflow_outcome_type:
            return _unknown_submission_projection(
                "service_execution_workflow_outcome_invalid",
                order=order,
                intent_id=identity["intent_id"],
            )
        if self._recovery_flow is not None and self._recovery_event_version == 2:
            try:
                self._attach_strategy_position_ref(
                    order, local_position_key_ref, outcome.strategy_position_ref
                )
            except Exception:
                return _unknown_submission_projection(
                    "recovery_strategy_position_ref_invalid",
                    order=order,
                    intent_id=identity["intent_id"],
                )
        if outcome.disposition == "RESTORE":
            prior_state = outcome.recovery_state
            result = {
                "kind": "service_execution_recovery_restore",
                "intent_id": identity["intent_id"],
                "submit_fingerprint": prior_state.submit_fingerprint,
                "order_state": prior_state,
            }
            position_ref = outcome.strategy_position_ref
            if position_ref is not None:
                result["strategy_position_ref"] = position_ref.value
            return result
        if outcome.disposition == "REJECTED":
            if outcome.stage == "PREPARE":
                message = "The durable intent manifest rejected this request."
            else:
                message = "The execution service did not accept the intent."
            return _rejection(
                outcome.code or "service_execution_request_failed",
                message,
                order=order,
                intent_id=identity["intent_id"],
            )
        if outcome.disposition == "UNKNOWN":
            return _unknown_submission_projection(
                outcome.code or "service_execution_request_failed",
                order=order,
                intent_id=identity["intent_id"],
                strategy_position_ref=(
                    outcome.strategy_position_ref.value
                    if outcome.strategy_position_ref is not None
                    else None
                ),
            )
        view = outcome.record
        if self._recovery_flow is not None:
            # A submit reply is acceptance evidence only in recovery mode. A
            # replayed FILLED record must never become a second Backtrader
            # fill; only the durable snapshot/event receipt path may project it.
            return _recovery_submission_projection(
                view,
                data_name=_data_name(order),
                intent_id=identity["intent_id"],
                strategy_position_ref=(
                    outcome.strategy_position_ref.value
                    if outcome.strategy_position_ref is not None
                    else None
                ),
            )
        intent_id = identity["intent_id"]
        replayed = intent_id in self._returned_intents
        self._returned_intents.add(intent_id)
        self._projected_revisions[intent_id] = getattr(view, "updated_at_ns", None)
        if view is not None:
            self._known_record_intents.add(intent_id)
        return _submission_projection(view, data_name=_data_name(order), replayed=replayed)

    # -- refresh ------------------------------------------------------------

    def refresh_projection(self, intent_id: str) -> Mapping[str, Any]:
        """Project the current durable record for one intent.

        This performs no provider dispatch: it only asks the service what the
        journal already holds.  An unchanged revision is reported as a replay
        so the framework cannot book the same state twice. Failed reads raise
        a typed error so the Broker can preserve order state and the scheduler
        can back off instead of treating an authorization failure as a rejection.
        """

        if not _reference(intent_id):
            raise ServiceExecutionAdapterError("invalid intent id")
        if self._recovery_flow is not None:
            # Per-record query responses do not carry the pinned global event
            # cursor and cannot safely advance the crash-recovery boundary.
            raise ServiceExecutionReadError("recovery_event_stream_required")
        try:
            view = self._workflow.query(intent_id)
        except Exception as error:  # noqa: BLE001 - converted to a finite read diagnostic
            code = (
                "service_execution_read_timeout"
                if isinstance(error, TimeoutError)
                else _error_code(error)
            )
            raise ServiceExecutionReadError(code) from None
        if view is None:
            if intent_id in self._known_record_intents:
                raise ServiceExecutionReadError("service_execution_record_missing")
            return {
                "kind": "service_execution_record",
                "managed_intent_id": intent_id,
                "status": "pending",
                "execution_unknown": True,
                "error_code": "service_execution_record_missing",
                "error_msg": "The service holds no durable record for this intent.",
            }
        self._known_record_intents.add(intent_id)
        revision = getattr(view, "updated_at_ns", None)
        replayed = revision is not None and self._projected_revisions.get(intent_id) == revision
        self._projected_revisions[intent_id] = revision
        return _submission_projection(view, data_name=None, replayed=replayed)

    # -- cancellation -------------------------------------------------------

    def cancel_order(
        self,
        order_or_ref: Any,
        dataname: Optional[str],
        sdk_dispatch: Any,
    ) -> Mapping[str, Any]:
        """Cancel one order whose provider identity the journal evidenced."""

        del sdk_dispatch
        info = _order_info(order_or_ref)
        target_intent_id = info.get("managed_intent_id")
        if not _reference(target_intent_id):
            return _rejection(
                "managed_cancel_metadata_missing",
                "Cancellation requires the managed intent identifier.",
                data_name=dataname,
            )
        # One durable identity per cancellation attempt.  An explicit
        # identifier wins; otherwise the framework convention derives a stable
        # one from the intent, so re-cancelling the same intent is idempotent
        # instead of creating a second cancellation record.
        declared_cancel_id = info.get("managed_cancel_intent_id")
        cancel_id = (
            declared_cancel_id if _reference(declared_cancel_id) else f"cancel.{target_intent_id}"
        )
        provider_order_id = info.get("external_order_id")
        if not _reference(provider_order_id):
            return _rejection(
                "managed_cancel_provider_identity_missing",
                "Cancellation requires the provider order identity confirmed by the service.",
                data_name=dataname,
                intent_id=target_intent_id,
            )

        metadata_version = _metadata_version_of(info, self._metadata_version)
        if self._recovery_flow is not None:
            namespace_error = self._validate_recovery_order_scope(order_or_ref)
            if namespace_error is not None:
                return _rejection(
                    namespace_error,
                    "The order owner does not match the explicit recovery namespace.",
                    data_name=dataname,
                    intent_id=target_intent_id,
                )
            if self._recovery_flow.namespace is None:
                return _rejection(
                    "service_execution_recovery_not_bound",
                    "The managed session did not bind an authenticated recovery scope.",
                    data_name=dataname,
                    intent_id=target_intent_id,
                )
        cancel_fields = {
            "cancel_id": cancel_id,
            "target_intent_id": target_intent_id,
            "provider_order_id": provider_order_id,
            "metadata_version": metadata_version,
        }
        managed_instrument = info.get("managed_instrument")
        if _instrument(managed_instrument):
            # Typed cancel (iteration 60 R2-B): names the order's instrument
            # key under a multi-instrument command binding, also after restart.
            cancel_fields["instrument"] = managed_instrument
        request = self._workflow_cancel_request_type(**cancel_fields)
        try:
            outcome = self._workflow.cancel(request)
        except Exception as error:  # noqa: BLE001 - dispatch certainty is unavailable
            return _unknown_cancel_projection(
                _error_code(error), data_name=dataname, cancel_id=cancel_id
            )
        if type(outcome) is not self._workflow_outcome_type:
            return _unknown_cancel_projection(
                "service_execution_workflow_outcome_invalid",
                data_name=dataname,
                cancel_id=cancel_id,
            )
        if outcome.disposition == "REJECTED":
            if outcome.stage == "PREPARE":
                message = "The durable cancellation manifest rejected this request."
            else:
                message = "The execution service did not accept the cancellation."
            return _rejection(
                outcome.code or "service_execution_request_failed",
                message,
                data_name=dataname,
                intent_id=target_intent_id,
            )
        if outcome.disposition == "UNKNOWN":
            return _unknown_cancel_projection(
                outcome.code or "service_execution_request_failed",
                data_name=dataname,
                cancel_id=cancel_id,
            )
        if outcome.disposition != "RECORD":
            return _unknown_cancel_projection(
                "service_execution_workflow_outcome_invalid",
                data_name=dataname,
                cancel_id=cancel_id,
            )
        view = outcome.record
        if self._recovery_flow is not None:
            return _recovery_cancellation_projection(
                view, data_name=dataname, cancel_id=cancel_id, intent_id=target_intent_id
            )
        return _cancellation_projection(view, dataname)

    def _validate_recovery_order_scope(self, order: Any) -> Optional[str]:
        flow = self._recovery_flow
        namespace = getattr(flow, "namespace", None) if flow is not None else None
        if namespace is None:
            return None
        owner = getattr(order, "owner", None)
        params = getattr(owner, "p", None)
        if (
            getattr(params, "strategy_ref", None) != namespace.strategy_ref
            or getattr(params, "account_ref", None) != namespace.account_ref
        ):
            return "service_execution_recovery_scope_mismatch"
        return None


# -- identity and content ---------------------------------------------------


def _managed_identity(order: Any, default_metadata_version: str) -> Optional[dict[str, Any]]:
    info = _order_info(order)
    intent_id = info.get("managed_intent_id")
    signal_id = info.get("managed_signal_id")
    instrument = info.get("managed_instrument")
    position_effect = info.get("managed_position_effect")
    if not (_reference(intent_id) and _reference(signal_id)):
        return None
    if not (_instrument(instrument) and position_effect in _POSITION_EFFECTS):
        return None
    return {
        "intent_id": intent_id,
        "signal_id": signal_id,
        "instrument": instrument,
        "position_effect": position_effect,
        "reduce_only": bool(info.get("reduce_only", False)) or position_effect != "OPEN",
        "metadata_version": _metadata_version_of(info, default_metadata_version),
    }


def _order_content(order: Any) -> Optional[dict[str, Any]]:
    exectype = getattr(order, "exectype", None)
    created = getattr(order, "created", None)
    raw_size = getattr(created, "size", None)
    if raw_size is None:
        raw_size = getattr(order, "size", None)
    try:
        size = Decimal(str(raw_size))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not size.is_finite() or size == 0:
        return None
    quantity = abs(size)
    side = "BUY" if _is_buy(order, size) else "SELL"

    limit, market = _execution_types()
    if exectype == limit:
        raw_price = getattr(created, "price", None)
        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if not price.is_finite() or price <= 0:
            return None
        return {
            "side": side,
            "order_type": "LIMIT",
            "quantity": quantity,
            "price": price,
        }
    if exectype == market:
        return {"side": side, "order_type": "MARKET", "quantity": quantity, "price": None}
    # Stop, stop-limit, trailing and bracket orders are not silently downgraded.
    return None


def _execution_types() -> tuple[Any, Any]:
    from backtrader.order import Order

    return Order.Limit, Order.Market


def _is_buy(order: Any, size: Decimal) -> bool:
    isbuy = getattr(order, "isbuy", None)
    if callable(isbuy):
        return bool(isbuy())
    return size > 0


def _tags(order: Any, order_ref_factory: Optional[Callable[[Any], str]]) -> dict[str, str]:
    """Return the stable tags for one intent.

    The framework order reference is deliberately *not* sent by default: it is
    a per-object counter, so including it would make the same logical intent
    look like different content and the service would refuse it as a conflict
    instead of returning the durable record.  A deployment that has its own
    stable reference scheme may inject ``order_ref_factory`` to publish it.
    """

    if order_ref_factory is None:
        return {}
    candidate = order_ref_factory(order)
    return {"framework_order_ref": candidate} if _reference(candidate) else {}


# -- projections ------------------------------------------------------------


def _submission_projection(
    view: Any, *, data_name: Optional[str], replayed: bool = False
) -> Mapping[str, Any]:
    state = _state_of(view)
    projection = {
        "kind": "service_execution_record",
        "managed_intent_id": _view_text(view, "intent_id"),
        "service_execution_state": state,
        "service_dispatch_attempts": getattr(view, "dispatch_attempts", None),
        # The durable revision lets a caller suppress a repeat projection.
        "service_record_revision": getattr(view, "updated_at_ns", None),
        "data_name": data_name,
    }
    if state in _ACCEPTED_STATES:
        provider_order_id = _view_text(view, "provider_order_id")
        if provider_order_id is not None:
            projection["external_order_id"] = provider_order_id
        status = _ACCEPTED_STATES[state]
        if state in _FILLED_STATES:
            filled = _decimal_text(getattr(view, "filled_quantity", None))
            price = _decimal_text(getattr(view, "average_price", None))
            if filled is not None and price is not None:
                projection["status"] = status
                projection["filled"] = filled
                projection["price"] = price
                # These are cumulative durable snapshots. The Broker uses
                # avg_price to derive an incremental price from a changed
                # cumulative quantity instead of treating the new average as
                # the price of the entire increment.
                projection["avg_price"] = price
                commission = _decimal_text(getattr(view, "cumulative_commission", None))
                if commission is not None:
                    projection["cumulative_commission"] = commission
                return _mark_replay(projection, state) if replayed else projection
            # A fill the framework cannot size or price exactly must not be
            # reported as one; the order stays accepted and the caller
            # reconciles the record instead of booking a guessed fill.
            projection["status"] = "accepted"
            projection["service_execution_fill_unprojected"] = True
            return _mark_replay(projection, state) if replayed else projection
        projection["status"] = status
        return _mark_replay(projection, state) if replayed else projection
    if state == "UNKNOWN":
        projection.update(
            {
                "status": "pending",
                "execution_unknown": True,
                "error_code": "service_execution_outcome_unknown",
                "error_msg": (
                    "The execution service could not prove the provider outcome; "
                    "reconcile the original intent before resubmitting."
                ),
            }
        )
        return projection
    if state == "CANCELLED":
        # A cancelled order record is terminal for the framework order; any
        # late fill is reconciled from the same durable record.
        projection["status"] = "cancelled"
        return _mark_replay(projection, state) if replayed else projection
    projection.update(
        {
            "status": "rejected",
            "error_code": f"service_execution_{state.lower()}",
            "error_msg": f"Execution service recorded state {state} for this intent.",
        }
    )
    return _mark_replay(projection, state) if replayed else projection


def _recovery_submission_projection(
    view: Any,
    *,
    data_name: Optional[str],
    intent_id: str,
    strategy_position_ref: Optional[str] = None,
) -> Mapping[str, Any]:
    """Represent submit acknowledgement without projecting durable order state."""
    from bt_api_py.service_recovery import is_strategy_position_ref

    projection = {
        "kind": "service_execution_record",
        "managed_intent_id": intent_id,
        "status": "pending",
        "execution_unknown": True,
        "service_execution_state": _state_of(view),
        "service_dispatch_attempts": getattr(view, "dispatch_attempts", None),
        "service_record_revision": getattr(view, "updated_at_ns", None),
        "service_execution_recovery_required": True,
        "data_name": data_name,
        "error_code": "service_execution_recovery_event_required",
        "error_msg": (
            "Submit acceptance was recorded; order state and fills require the durable recovery stream."
        ),
    }
    if strategy_position_ref is not None:
        if not is_strategy_position_ref(strategy_position_ref):
            raise ServiceExecutionReadError("recovery_strategy_position_ref_invalid")
        projection["strategy_position_ref"] = strategy_position_ref
    return projection


def _recovery_cancellation_projection(
    view: Any, *, data_name: Optional[str], cancel_id: str, intent_id: str
) -> Mapping[str, Any]:
    """Represent cancel submission without projecting a terminal cancel state."""

    return {
        "kind": "service_execution_record",
        "managed_cancel_intent_id": cancel_id,
        "managed_intent_id": intent_id,
        "status": "cancel_requested",
        "managed_execution_cancel_pending": True,
        "managed_execution_cancel_reconciliation_required": True,
        "service_execution_recovery_required": True,
        "data_name": data_name,
        "error_code": "service_execution_recovery_event_required",
        "error_msg": (
            "Cancel acceptance was recorded; terminal state requires the durable recovery stream."
        ),
    }


def _mark_replay(projection: dict[str, Any], state: str) -> dict[str, Any]:
    """Mark a durable record this adapter already returned to the framework.

    A durable record proves a provider dispatch, not permission to mutate the
    current in-memory Broker a second time.  The Broker's dedicated replay
    guard turns this into a precise rejection unless an audited recovery
    receipt is available.
    """

    projection["managed_execution_replayed"] = True
    projection["managed_execution_state"] = state
    return projection


def _cancellation_projection(view: Any, dataname: Optional[str]) -> Mapping[str, Any]:
    state = _state_of(view)
    projection = {
        "kind": "service_execution_record",
        "managed_cancel_intent_id": _view_text(view, "cancel_id"),
        "managed_intent_id": _view_text(view, "target_intent_id"),
        "service_execution_cancel_state": state,
        "data_name": dataname,
    }
    provider_order_id = _view_text(view, "provider_order_id")
    if provider_order_id is not None:
        projection["external_order_id"] = provider_order_id
    if state == "ACKED":
        # An acknowledged cancellation is not a terminal framework state: a
        # late fill or a separately reconciled terminal update may still arrive.
        projection.update(
            {
                "status": "cancel_requested",
                "managed_execution_cancel_pending": True,
                "managed_execution_cancel_reconciliation_required": True,
            }
        )
        return projection
    if state == "CANCELLED":
        projection["status"] = "cancelled"
        return projection
    if state == "UNKNOWN":
        projection.update(
            {
                "status": "pending",
                "execution_unknown": True,
                "managed_execution_cancel_pending": True,
                "managed_execution_cancel_reconciliation_required": True,
                "error_code": "service_execution_cancel_outcome_unknown",
                "error_msg": (
                    "The execution service could not prove the cancellation outcome; "
                    "reconcile the original cancellation before retrying."
                ),
            }
        )
        return projection
    projection.update(
        {
            "status": "rejected",
            "error_code": f"service_execution_cancel_{state.lower()}",
            "error_msg": f"Execution service recorded cancellation state {state}.",
        }
    )
    return projection


def _unknown_submission_projection(
    code: str,
    *,
    order: Any,
    intent_id: str,
    strategy_position_ref: Optional[str] = None,
) -> Mapping[str, Any]:
    from bt_api_py.service_recovery import is_strategy_position_ref
    projection = {
        "kind": "service_execution_record",
        "managed_intent_id": intent_id,
        "service_execution_state": "UNKNOWN",
        "status": "pending",
        "execution_unknown": True,
        "error_code": code,
        "error_msg": (
            "The execution request outcome is unknown; reconcile the original "
            "intent instead of resubmitting it."
        ),
        "data_name": _data_name(order),
    }
    if strategy_position_ref is not None and is_strategy_position_ref(
        strategy_position_ref
    ):
        projection["strategy_position_ref"] = strategy_position_ref
    return projection


def _unknown_cancel_projection(
    code: str, *, data_name: Optional[str], cancel_id: str
) -> Mapping[str, Any]:
    return {
        "kind": "service_execution_record",
        "managed_cancel_intent_id": cancel_id,
        "service_execution_cancel_state": "UNKNOWN",
        "status": "pending",
        "execution_unknown": True,
        "managed_execution_cancel_pending": True,
        "managed_execution_cancel_reconciliation_required": True,
        "error_code": code,
        "error_msg": "The cancellation outcome is unknown; reconcile before retrying.",
        "data_name": data_name,
    }


def _rejection(
    code: str,
    message: str,
    *,
    order: Any = None,
    data_name: Optional[str] = None,
    intent_id: Optional[str] = None,
) -> Mapping[str, Any]:
    projection: dict[str, Any] = {
        "status": "rejected",
        "error_code": code,
        "error_msg": message,
    }
    if order is not None:
        projection["data_name"] = _data_name(order)
    elif data_name is not None:
        projection["data_name"] = data_name
    if intent_id is not None:
        projection["managed_intent_id"] = intent_id
    return projection


# -- small helpers ----------------------------------------------------------


def _order_info(order: Any) -> Mapping[str, Any]:
    info = getattr(order, "info", None)
    if isinstance(info, Mapping):
        return info
    getter = getattr(info, "get", None)
    if callable(getter):
        return {key: getter(key) for key in _MANAGED_INFO_KEYS}
    return {}


_MANAGED_INFO_KEYS = (
    "managed_intent_id",
    "managed_signal_id",
    "managed_instrument",
    "managed_position_effect",
    "managed_metadata_version",
    "time_in_force",
    "managed_cancel_intent_id",
    "external_order_id",
    "reduce_only",
)


_TIME_IN_FORCE_VALUES = frozenset({"GTC", "IOC", "FOK", "DAY"})


def _time_in_force_of(order: Any, *, default: str) -> Optional[str]:
    """Return the explicitly requested wire TIF, or the session default.

    The default stays GTC for ordinary sessions. A managed paper recovery V2
    session passes FOK as its default, while any explicit order-level value is
    preserved and validated before journaling or service submission.
    """

    value = _order_info(order).get("time_in_force")
    if value is None:
        return default
    value = getattr(value, "value", value)
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if normalized not in _TIME_IN_FORCE_VALUES:
        return None
    return normalized


def _metadata_version_of(info: Mapping[str, Any], default: str) -> str:
    value = info.get("managed_metadata_version")
    return value if _reference(value) else default


def _decimal_text(value: Any) -> Optional[str]:
    """Return an exact decimal text, or None when the value is unusable."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return format(number, "f") if number.is_finite() else None


def _state_of(view: Any) -> str:
    state = getattr(view, "state", None)
    return state if isinstance(state, str) else "UNKNOWN"


def _view_text(view: Any, attribute: str) -> Optional[str]:
    value = getattr(view, attribute, None)
    return value if _reference(value) else None


def _error_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code and code.isascii():
        return code
    return "service_execution_request_failed"


_POSITION_EFFECTS = frozenset({"OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"})


def _instrument(value: Any) -> bool:
    from bt_api_py.service_execution import is_service_execution_instrument

    return is_service_execution_instrument(value)


__all__ = [
    "ServiceExecutionAdapter",
    "ServiceExecutionAdapterError",
    "ServiceExecutionReadError",
]
