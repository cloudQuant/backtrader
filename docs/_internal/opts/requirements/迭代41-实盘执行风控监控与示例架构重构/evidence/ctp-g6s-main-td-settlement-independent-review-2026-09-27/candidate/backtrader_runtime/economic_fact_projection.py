"""Replay immutable execution outbox snapshots into the optional monitor model.

This adapter is deliberately pull-only. It is not called from an order submit
path, does not query the current execution record to enrich historical events,
and does not calculate account equity, fills, slippage, or latency. Replaying a
page is safe because the monitor event identity is derived from the persisted
execution event identity and sequence.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple, Optional


class EconomicFactProjectionError(RuntimeError):
    """A durable execution event could not be projected without guessing."""


class EconomicFactProjectionBatch(NamedTuple):
    """Summary of one bounded source page and its idempotent monitor appends."""

    first_sequence: Optional[int]
    last_sequence: int
    scanned: int
    published: int
    skipped_without_fill: int
    may_have_more: bool


_PROJECTABLE_EVENT_TYPES = frozenset(
    {"provider_observation", "reconciled_observation", "provider_commission_evidence"}
)
_FILL_STATES = frozenset({"PARTIALLY_FILLED", "FILLED", "CANCELLED"})
_MAX_PROJECTION_PAGE = 500


def pump_execution_quality(
    execution_store: Any,
    monitor_read_model: Any,
    scope: Any,
    *,
    after_sequence: int = 0,
    limit: int = 100,
) -> EconomicFactProjectionBatch:
    """Append one page of cumulative quality snapshots to the monitor outbox.

    ``execution_store`` must expose the SDK's bounded ``read_outbox`` and
    immutable ``get_intent`` readers. ``monitor_read_model`` must expose
    ``append_execution_quality``. Neither package is imported at module import
    time; the execution DTO is loaded only when this optional adapter runs.

    The returned sequence is a caller-managed replay cursor, not an ACK. A
    caller that loses it can replay earlier pages: monitor event IDs are stable
    for a durable execution event. Each row is an ORDER_CUMULATIVE snapshot;
    consumers select the latest sequence per intent and never add snapshots.
    """

    if type(after_sequence) is not int or after_sequence < 0:
        raise EconomicFactProjectionError("after_sequence must be a nonnegative exact integer")
    if type(limit) is not int or not 1 <= limit <= _MAX_PROJECTION_PAGE:
        raise EconomicFactProjectionError("limit is outside the bounded projection page")
    if scope is None or not isinstance(getattr(scope, "key", None), str):
        raise EconomicFactProjectionError("an exact execution scope is required")
    read_outbox = getattr(execution_store, "read_outbox", None)
    get_intent = getattr(execution_store, "get_intent", None)
    append_quality = getattr(monitor_read_model, "append_execution_quality", None)
    if not callable(read_outbox) or not callable(get_intent) or not callable(append_quality):
        raise EconomicFactProjectionError("execution and monitor read ports are required")

    try:
        from bt_api_execution import ExecutionQualityRecord
    except ImportError as error:
        raise EconomicFactProjectionError(
            "the optional bt_api_execution DTO package is unavailable"
        ) from error

    try:
        events = read_outbox(after_sequence=after_sequence, limit=limit, scope=scope)
    except Exception as error:
        raise EconomicFactProjectionError("unable to read execution outbox page") from error
    if not isinstance(events, (tuple, list)) or len(events) > limit:
        raise EconomicFactProjectionError("execution outbox returned an invalid page")

    first_sequence: Optional[int] = None
    last_sequence = after_sequence
    published = 0
    skipped_without_fill = 0
    previous_sequence = after_sequence
    for event in events:
        sequence = getattr(event, "sequence", None)
        if type(sequence) is not int or sequence <= previous_sequence:
            raise EconomicFactProjectionError("execution outbox sequence is not strictly ordered")
        previous_sequence = sequence
        if first_sequence is None:
            first_sequence = sequence
        last_sequence = sequence
        if getattr(event, "scope_key", None) != scope.key:
            raise EconomicFactProjectionError("execution event escaped the requested scope")
        if getattr(event, "event_type", None) not in _PROJECTABLE_EVENT_TYPES:
            continue
        source = _event_mapping_value(getattr(event, "payload", None), "source")
        if source not in {"provider", "reconcile"}:
            raise EconomicFactProjectionError("execution event source is missing or unsupported")
        state = getattr(getattr(event, "state", None), "value", getattr(event, "state", None))
        payload = getattr(event, "payload", None)
        quantity = _decimal_or_none(
            _event_mapping_value(payload, "filled_quantity"), "filled_quantity"
        )
        if quantity is None or quantity == 0:
            skipped_without_fill += 1
            continue
        if quantity < 0:
            raise EconomicFactProjectionError("execution event has a negative cumulative quantity")
        if state not in _FILL_STATES:
            raise EconomicFactProjectionError("non-fill execution event carries a nonzero quantity")

        average_price = _decimal_or_none(
            _event_mapping_value(payload, "average_price"), "average_price"
        )
        if average_price is not None and average_price <= 0:
            raise EconomicFactProjectionError("execution event has an invalid cumulative VWAP")
        cumulative_fee = _decimal_or_none(
            _event_mapping_value(payload, "cumulative_commission"), "cumulative_commission"
        )
        provider_order_id = _event_mapping_value(payload, "provider_order_id")
        if provider_order_id is not None and not isinstance(provider_order_id, str):
            raise EconomicFactProjectionError("execution event has an invalid provider order ID")
        event_id = getattr(event, "event_id", None)
        if not isinstance(event_id, str) or not event_id:
            raise EconomicFactProjectionError("execution event has no durable identity")
        created_at_ns = getattr(event, "created_at_ns", None)
        if type(created_at_ns) is not int or created_at_ns <= 0:
            raise EconomicFactProjectionError("execution event has no valid local commit timestamp")
        journal_id = getattr(event, "journal_incarnation_id", None)
        if journal_id is not None and (
            not isinstance(journal_id, str)
            or len(journal_id) != 32
            or any(character not in "0123456789abcdef" for character in journal_id)
        ):
            raise EconomicFactProjectionError("execution event has invalid journal lineage")

        intent_id = getattr(event, "intent_id", None)
        if not isinstance(intent_id, str) or not intent_id:
            raise EconomicFactProjectionError("execution event has no intent identity")
        try:
            intent = get_intent(intent_id, scope=scope)
        except Exception as error:
            raise EconomicFactProjectionError(
                "unable to read immutable execution intent"
            ) from error
        if intent is None or getattr(intent, "scope", None) != scope:
            raise EconomicFactProjectionError("execution intent does not match event scope")
        if getattr(intent, "intent_id", None) != intent_id:
            raise EconomicFactProjectionError("execution intent does not match event identity")

        event_ref = "execution-event-" + hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        sequence_ref = "execution-sequence-" + str(sequence)
        refs = (event_ref, sequence_ref)
        field_completeness = {"native_quantity": "PARTIAL"}
        field_coverage_ns = {"native_quantity": (created_at_ns, created_at_ns)}
        field_source_refs = {"native_quantity": refs}
        if average_price is not None:
            field_completeness["vwap"] = "PARTIAL"
            field_coverage_ns["vwap"] = (created_at_ns, created_at_ns)
            field_source_refs["vwap"] = refs
        if cumulative_fee is not None:
            field_completeness["fee"] = "PARTIAL"
            field_coverage_ns["fee"] = (created_at_ns, created_at_ns)
            field_source_refs["fee"] = refs

        identity_kind = "EXECUTION_JOURNAL" if journal_id is not None else None
        side = getattr(getattr(intent, "side", None), "value", getattr(intent, "side", None))
        try:
            fact = ExecutionQualityRecord(
                intent_id=intent_id,
                as_of_ns=created_at_ns,
                source="execution_journal.outbox_snapshot",
                completeness="INCOMPLETE",
                scope=scope,
                generation_kind=identity_kind,
                generation=journal_id,
                epoch=1 if journal_id is not None else None,
                currency=None,
                fee_currency=None,
                signal_id=getattr(intent, "signal_id", None),
                child_id=None,
                order_id=provider_order_id,
                trade_id=None,
                side=side,
                native_quantity=quantity,
                native_quantity_basis="ORDER_CUMULATIVE",
                vwap=average_price,
                vwap_basis="ORDER_CUMULATIVE" if average_price is not None else None,
                fee=cumulative_fee,
                fee_basis="ORDER_CUMULATIVE" if cumulative_fee is not None else None,
                field_completeness=field_completeness,
                field_coverage_ns=field_coverage_ns,
                field_source_refs=field_source_refs,
            )
            wire = fact.to_wire()
        except Exception as error:
            raise EconomicFactProjectionError(
                "execution quality DTO rejected source evidence"
            ) from error

        monitor_event_id = (
            "ef2-"
            + hashlib.sha256(
                ("execution_quality.v2:" + event_id + ":" + str(sequence)).encode("utf-8")
            ).hexdigest()
        )
        try:
            append_quality(monitor_event_id, wire, created_at_ns / 1_000_000_000.0)
        except Exception as error:
            raise EconomicFactProjectionError("unable to append quality fact to monitor") from error
        published += 1

    return EconomicFactProjectionBatch(
        first_sequence=first_sequence,
        last_sequence=last_sequence,
        scanned=len(events),
        published=published,
        skipped_without_fill=skipped_without_fill,
        may_have_more=len(events) == limit,
    )


def _event_mapping_value(value: Any, key: str) -> Any:
    if not hasattr(value, "get"):
        raise EconomicFactProjectionError("execution event payload is not a mapping")
    return value.get(key)


def _decimal_or_none(value: Any, name: str) -> Optional[Decimal]:
    if value is None:
        return None
    if type(value) is bool or isinstance(value, float):
        raise EconomicFactProjectionError("execution event has invalid " + name)
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise EconomicFactProjectionError("execution event has invalid " + name) from error
    if not parsed.is_finite():
        raise EconomicFactProjectionError("execution event has nonfinite " + name)
    return parsed


__all__ = [
    "EconomicFactProjectionBatch",
    "EconomicFactProjectionError",
    "pump_execution_quality",
]
