"""Managed execution adapter backed by the SDK service execution client.

``BtApiStore`` accepts one deliberate ``managed_execution_adapter`` port.  This
adapter fills that port with the authenticated execution service: the store
keeps its order projection and the service keeps the durable intent, admission
and provider dispatch.  The adapter is a borrowed facade over an injected SDK
client; it never starts a thread, never registers, and never calls the private
legacy dispatcher, because a missing journal, permit or provider fact must not
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
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from backtrader.stores.managed_execution import ManagedExecutionAdapterError
from backtrader.stores.service_execution_recovery import (
    ServiceExecutionRecoveryError,
    ServiceExecutionRecoveryJournal,
    ServiceExecutionRecoveryNamespace,
)

#: Codes that prove the service refused the request without touching the
#: provider.  Only these may become a local rejection: an unrecognized code is
#: not evidence that the provider saw nothing, so everything else stays a
#: nonterminal unknown projection that must be reconciled.
_DEFINITIVE_REJECTION_CODES = frozenset(
    {
        "ADMISSION_REQUIRED",
        "CAPACITY",
        "CANCEL_TARGET_UNKNOWN",
        "CAPABILITY_UNAVAILABLE",
        "CLOSED",
        "CONFLICT",
        "DENIED",
        "DUPLICATE_ACTIVE_RUN",
        "INVALID_REPLY",
        "INVALID_REQUEST",
        "INTENT_CONFLICT",
        "NOT_REGISTERED",
        "OWNER_LEASE_UNAVAILABLE",
        "POLICY_REQUIREMENT_UNMET",
        "QUERY_NOT_CONFIGURED",
        "RECORD_MISSING",
        "REQUEST_NOT_SENT",
        "ROLE_NOT_AUTHORIZED",
        "SCOPE_DENIED",
        "STALE_EPOCH",
        "STATE_CONFLICT",
        "STORE_UNAVAILABLE",
        "UNSUPPORTED_OPERATION",
    }
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


class ServiceExecutionAdapterError(ManagedExecutionAdapterError):
    """Finite local diagnostics for an unusable service execution adapter."""


class ServiceExecutionReadError(ServiceExecutionAdapterError):
    """A durable-record read failed and must not change order business state.

    ``applied_refs`` is filled by the Broker when a later read in the same
    refresh pass fails.  The refresh scheduler can then retain accurate apply
    counters while still treating the pass as failed and backing off.
    """

    def __init__(self, code: str, *, applied_refs: tuple[Any, ...] = ()) -> None:
        if (
            type(code) is not str
            or not code
            or len(code) > 64
            or not code.isascii()
            or not all(character.isalnum() or character in "_.-" for character in code)
        ):
            code = "service_execution_read_failed"
        self.code = code
        self.applied_refs = tuple(applied_refs)
        super().__init__(f"Managed service read failed ({code})")


class ServiceExecutionAdapter:
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
        recovery_journal: Optional[ServiceExecutionRecoveryJournal] = None,
    ) -> None:
        if not callable(getattr(client, "submit", None)):
            raise ServiceExecutionAdapterError("service execution adapter requires submit")
        if not callable(getattr(client, "cancel", None)):
            raise ServiceExecutionAdapterError("service execution adapter requires cancel")
        if type(metadata_version) is not str or not metadata_version.strip():
            raise ServiceExecutionAdapterError("invalid metadata_version")
        if order_ref_factory is not None and not callable(order_ref_factory):
            raise ServiceExecutionAdapterError("invalid order_ref_factory")
        if recovery_journal is not None and not all(
            callable(getattr(recovery_journal, name, None))
            for name in ("prepare_intent", "prepare_cancel")
        ):
            raise ServiceExecutionAdapterError("invalid recovery journal")

        self._client = client
        self._metadata_version = metadata_version
        self._order_ref_factory = order_ref_factory
        self._recovery_journal = recovery_journal
        self._recovery_namespace: Optional[ServiceExecutionRecoveryNamespace] = None
        #: Intent identities this adapter instance already returned to the
        #: framework.  A durable record proves a provider dispatch; it is not
        #: permission to mutate the current in-memory Broker twice.
        self._returned_intents: set[str] = set()
        #: Last durable revision projected per intent, so a repeated refresh
        #: of an unchanged record is reported as a replay.
        self._projected_revisions: dict[str, Any] = {}
        #: Intents for which this adapter has actually seen a durable record.
        self._known_record_intents: set[str] = set()

    def bind_recovery_namespace(self, namespace: ServiceExecutionRecoveryNamespace) -> None:
        """Bind recovery to the authenticated writer scope and stable run ID."""

        if (
            self._recovery_journal is None
            or type(namespace) is not ServiceExecutionRecoveryNamespace
        ):
            raise ServiceExecutionAdapterError("recovery_namespace_unavailable")
        if self._recovery_namespace is not None and self._recovery_namespace != namespace:
            raise ServiceExecutionAdapterError("recovery_namespace_already_bound")
        self._recovery_namespace = namespace

    def initialize_recovery(
        self,
        *,
        page_limit: int = 128,
        max_pages: int = 64,
    ) -> Mapping[str, Any]:
        """Install the authenticated restore snapshot and consume its event tail.

        Snapshot rows are stored as restore evidence only.  They do not create
        Backtrader fills or callbacks.  The durable page cursor starts at the
        snapshot cut for a new local run, or remains at its prior committed
        position for a resumed run.
        """

        journal, namespace = self._require_recovery()
        snapshot_reader = getattr(self._client, "query_recovery_snapshot", None)
        if not callable(snapshot_reader):
            raise ServiceExecutionReadError("recovery_snapshot_api_unavailable")
        try:
            snapshot = snapshot_reader()
            snapshot_changed = journal.install_snapshot(namespace, snapshot)
        except ServiceExecutionRecoveryError as error:
            raise ServiceExecutionReadError(f"recovery_{error.code.lower()}") from None
        except Exception as error:  # noqa: BLE001 - service failure must not fall back
            raise self._recovery_read_error(error) from None
        pages_applied = self._consume_recovery_pages(
            page_limit=page_limit,
            max_pages=max_pages,
        )
        cursor = journal.cursor(namespace)
        return {
            "snapshot_changed": snapshot_changed,
            "pages_applied": pages_applied,
            "journal_generation": cursor["journal_generation"],
            "scope_directory_revision": cursor["scope_directory_revision"],
            "event_cursor": cursor["event_cursor"],
        }

    def refresh_recovery_events(
        self,
        *,
        callback: Optional[Callable[[Any], Any]] = None,
        page_limit: int = 128,
        max_pages: int = 64,
        callback_limit: int = 32,
    ) -> Mapping[str, Any]:
        """Read committed event pages and then deliver pending callbacks.

        Each page and the resulting local cursor/projection/receipt/callback
        queue commit atomically before caller code runs. Callback completion is
        at-least-once across interruption; it is not an exactly-once promise.
        """

        journal, namespace = self._require_recovery()
        pages_applied = self._consume_recovery_pages(
            page_limit=page_limit,
            max_pages=max_pages,
        )
        delivered = 0
        if callback is not None:
            try:
                delivered = journal.deliver_pending_callbacks(
                    namespace,
                    callback,
                    limit=callback_limit,
                )
            except ServiceExecutionRecoveryError as error:
                raise ServiceExecutionReadError(f"recovery_{error.code.lower()}") from None
        cursor = journal.cursor(namespace)
        return {
            "pages_applied": pages_applied,
            "callbacks_delivered": delivered,
            "journal_generation": cursor["journal_generation"],
            "scope_directory_revision": cursor["scope_directory_revision"],
            "event_cursor": cursor["event_cursor"],
        }

    def _require_recovery(
        self,
    ) -> tuple[ServiceExecutionRecoveryJournal, ServiceExecutionRecoveryNamespace]:
        journal = self._recovery_journal
        namespace = self._recovery_namespace
        if journal is None or namespace is None:
            raise ServiceExecutionReadError("recovery_namespace_unavailable")
        return journal, namespace

    def _consume_recovery_pages(self, *, page_limit: int, max_pages: int) -> int:
        if type(page_limit) is not int or not 1 <= page_limit <= 128:
            raise ServiceExecutionAdapterError("invalid recovery page limit")
        if type(max_pages) is not int or not 1 <= max_pages <= 1024:
            raise ServiceExecutionAdapterError("invalid recovery page budget")
        journal, namespace = self._require_recovery()
        page_reader = getattr(self._client, "query_recovery_events_after", None)
        if not callable(page_reader):
            raise ServiceExecutionReadError("recovery_events_api_unavailable")
        pages_applied = 0
        for _ in range(max_pages):
            cursor = journal.cursor(namespace)
            generation = cursor["journal_generation"]
            directory_revision = cursor["scope_directory_revision"]
            after_sequence = cursor["event_cursor"]
            if (
                type(generation) is not str
                or not generation
                or type(directory_revision) is not str
                or not directory_revision
                or type(after_sequence) is not int
            ):
                raise ServiceExecutionReadError("recovery_snapshot_required")
            try:
                page = page_reader(
                    after_sequence=after_sequence,
                    expected_journal_generation=generation,
                    expected_directory_revision=directory_revision,
                    limit=page_limit,
                )
                page_changed = journal.apply_events_page(namespace, page)
            except ServiceExecutionRecoveryError as error:
                raise ServiceExecutionReadError(f"recovery_{error.code.lower()}") from None
            except Exception as error:  # noqa: BLE001 - never downgrade to direct calls
                raise self._recovery_read_error(error) from None

            pages_applied += int(page_changed)
            coverage = page.get("coverage") if isinstance(page, Mapping) else None
            if not isinstance(coverage, Mapping) or type(coverage.get("has_more")) is not bool:
                raise ServiceExecutionReadError("recovery_event_page_invalid")
            latest = journal.cursor(namespace)
            if latest["event_cursor"] != coverage.get("scanned_through"):
                raise ServiceExecutionReadError("recovery_event_cursor_mismatch")
            if coverage["has_more"] is False:
                return pages_applied
        raise ServiceExecutionReadError("recovery_page_budget_exhausted")

    @staticmethod
    def _recovery_read_error(error: BaseException) -> ServiceExecutionReadError:
        code = (
            "service_execution_recovery_read_timeout"
            if isinstance(error, TimeoutError)
            else f"service_execution_{_error_code(error)}"
        )
        return ServiceExecutionReadError(code)

    # -- submission ---------------------------------------------------------

    def submit_order(self, order: Any, legacy_dispatch: Any) -> Mapping[str, Any]:
        """Submit one framework order through the execution service.

        ``legacy_dispatch`` is accepted only to satisfy the Store port.  It is
        never invoked: routing a service-managed order through the legacy
        provider path would bypass the durable intent and its admission.
        """

        del legacy_dispatch
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

        tags = _tags(order, self._order_ref_factory)
        if self._recovery_journal is not None:
            namespace_error = self._validate_recovery_order_scope(order)
            if namespace_error is not None:
                return _rejection(
                    namespace_error,
                    "The order owner does not match the explicit recovery namespace.",
                    order=order,
                    intent_id=identity["intent_id"],
                )
            if self._recovery_namespace is None:
                return _rejection(
                    "service_execution_recovery_not_bound",
                    "The managed session did not bind an authenticated recovery scope.",
                    order=order,
                    intent_id=identity["intent_id"],
                )
            submit_payload = _submit_payload(identity, content, tags)
            try:
                # The manifest is durable before the RPC. If the caller loses
                # the reply, the same logical run can retry these exact facts.
                self._recovery_journal.prepare_intent(
                    self._recovery_namespace,
                    intent_id=identity["intent_id"],
                    submit_payload=submit_payload,
                )
            except ServiceExecutionRecoveryError as error:
                return _rejection(
                    f"service_execution_{error.code.lower()}",
                    "The durable intent manifest rejected this request.",
                    order=order,
                    intent_id=identity["intent_id"],
                )
            except Exception:  # noqa: BLE001 - persistence failure must fail closed
                return _rejection(
                    "service_execution_recovery_journal_unavailable",
                    "The durable intent manifest could not be committed.",
                    order=order,
                    intent_id=identity["intent_id"],
                )

        try:
            view = self._client.submit(
                intent_id=identity["intent_id"],
                signal_id=identity["signal_id"],
                instrument=identity["instrument"],
                side=content["side"],
                position_effect=identity["position_effect"],
                order_type=content["order_type"],
                quantity=content["quantity"],
                price=content["price"],
                time_in_force="GTC",
                reduce_only=identity["reduce_only"],
                metadata_version=identity["metadata_version"],
                deadline_ns=None,
                tags=tags,
            )
        except Exception as error:  # noqa: BLE001 - mapped to a finite projection
            return _failure_projection(error, order=order, intent_id=identity["intent_id"])
        if self._recovery_journal is not None:
            # A submit reply is acceptance evidence only in recovery mode. A
            # replayed FILLED record must never become a second Backtrader
            # fill; only the durable snapshot/event receipt path may project it.
            return _recovery_submission_projection(
                view, data_name=_data_name(order), intent_id=identity["intent_id"]
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
        if self._recovery_journal is not None:
            # Per-record query responses do not carry the pinned global event
            # cursor and cannot safely advance the crash-recovery boundary.
            raise ServiceExecutionReadError("recovery_event_stream_required")
        try:
            view = self._client.query(intent_id)
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
        legacy_dispatch: Any,
    ) -> Mapping[str, Any]:
        """Cancel one order whose provider identity the journal evidenced."""

        del legacy_dispatch
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

        if self._recovery_journal is not None:
            namespace_error = self._validate_recovery_order_scope(order_or_ref)
            if namespace_error is not None:
                return _rejection(
                    namespace_error,
                    "The order owner does not match the explicit recovery namespace.",
                    data_name=dataname,
                    intent_id=target_intent_id,
                )
            if self._recovery_namespace is None:
                return _rejection(
                    "service_execution_recovery_not_bound",
                    "The managed session did not bind an authenticated recovery scope.",
                    data_name=dataname,
                    intent_id=target_intent_id,
                )
            try:
                self._recovery_journal.prepare_cancel(
                    self._recovery_namespace,
                    cancel_id=cancel_id,
                    target_intent_id=target_intent_id,
                    provider_order_id=provider_order_id,
                    metadata_version=_metadata_version_of(info, self._metadata_version),
                )
            except ServiceExecutionRecoveryError as error:
                return _rejection(
                    f"service_execution_{error.code.lower()}",
                    "The durable cancellation manifest rejected this request.",
                    data_name=dataname,
                    intent_id=target_intent_id,
                )
            except Exception:  # noqa: BLE001 - persistence failure must fail closed
                return _rejection(
                    "service_execution_recovery_journal_unavailable",
                    "The durable cancellation manifest could not be committed.",
                    data_name=dataname,
                    intent_id=target_intent_id,
                )

        try:
            view = self._client.cancel(
                cancel_id=cancel_id,
                target_intent_id=target_intent_id,
                provider_order_id=provider_order_id,
                metadata_version=_metadata_version_of(info, self._metadata_version),
            )
        except Exception as error:  # noqa: BLE001 - mapped to a finite projection
            return _cancel_failure_projection(error, data_name=dataname, cancel_id=cancel_id)
        if self._recovery_journal is not None:
            return _recovery_cancellation_projection(
                view, data_name=dataname, cancel_id=cancel_id, intent_id=target_intent_id
            )
        return _cancellation_projection(view, dataname)

    def _validate_recovery_order_scope(self, order: Any) -> Optional[str]:
        namespace = self._recovery_namespace
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


def _submit_payload(
    identity: Mapping[str, Any], content: Mapping[str, Any], tags: Mapping[str, str]
) -> dict[str, Any]:
    """Return the exact scope-free OrderIntent payload sent by this adapter."""

    quantity = content["quantity"]
    price = content["price"]
    return {
        "intent_id": identity["intent_id"],
        "signal_id": identity["signal_id"],
        "instrument": identity["instrument"],
        "side": content["side"],
        "position_effect": identity["position_effect"],
        "order_type": content["order_type"],
        "quantity": format(quantity, "f"),
        "price": None if price is None else format(price, "f"),
        "time_in_force": "GTC",
        "reduce_only": identity["reduce_only"],
        "metadata_version": identity["metadata_version"],
        "deadline_ns": None,
        "tags": dict(tags),
    }


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
    view: Any, *, data_name: Optional[str], intent_id: str
) -> Mapping[str, Any]:
    """Represent submit acknowledgement without projecting durable order state."""

    return {
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


def _failure_projection(error: BaseException, *, order: Any, intent_id: str) -> Mapping[str, Any]:
    code = _error_code(error)
    if code not in _DEFINITIVE_REJECTION_CODES:
        return {
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
    return _rejection(
        code,
        "The execution service did not accept the intent.",
        order=order,
        intent_id=intent_id,
    )


def _cancel_failure_projection(
    error: BaseException, *, data_name: Optional[str], cancel_id: str
) -> Mapping[str, Any]:
    code = _error_code(error)
    if code not in _DEFINITIVE_REJECTION_CODES:
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
    return _rejection(
        code,
        "The execution service did not accept the cancellation.",
        data_name=data_name,
    )


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
    "managed_cancel_intent_id",
    "external_order_id",
    "reduce_only",
)


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


def _data_name(order: Any) -> Optional[str]:
    data = getattr(order, "data", None)
    for attribute in ("_name", "dataname", "name"):
        value = getattr(data, attribute, None)
        if isinstance(value, str) and value:
            return value
    return None


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


def _reference(value: Any) -> bool:
    if type(value) is not str or not value or len(value) > 128:
        return False
    if value != value.strip():
        return False
    return all(character.isalnum() or character in "._:-" for character in value)


def _instrument(value: Any) -> bool:
    if type(value) is not str or not 1 <= len(value) <= 192:
        return False
    if not value[0].isascii() or not value[0].isalnum():
        return False
    return all(
        character.isascii() and (character.isalnum() or character in "._:/-") for character in value
    )


__all__ = [
    "ServiceExecutionAdapter",
    "ServiceExecutionAdapterError",
    "ServiceExecutionReadError",
]
