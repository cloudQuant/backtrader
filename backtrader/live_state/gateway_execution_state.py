"""Durable Gateway observation checkpoint; no broker projection or automatic ACK.

Attribution digests are public correlation labels, not independent verification
of the Gateway's native prepared request or proof of provider authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from bt_api_base.gateway_execution_stream_protocol import (
    GatewayExecutionStreamEvent,
    GatewayExecutionStreamPage,
    GatewayExecutionStreamProgress,
)
from bt_api_py.gateway_direct_client import gateway_intent_from_mapping

from ._common import ensure_no_secret_keys, is_sha256_hex, is_strict_int
from .gateway_pending import _binding_mapping, _cancel_plan, _cancel_record, _record

_MAX_EVENTS = 100_000
_MAX_EVENT_BYTES = 64 * 1024 * 1024
_MAX_PROJECTION_BYTES = 32 * 1024 * 1024
_NOTIFICATIONS = "_gateway_notifications"
_EXECUTION_KEYS = {
    "consumer_ref",
    "epoch",
    "revision",
    "stored_sequence",
    "applied_sequence",
    "acknowledged_sequence",
    "projection",
    "events",
    "receipts",
    "max_events",
    "max_event_bytes",
    "max_projection_bytes",
}


def _digest(value: object) -> bool:
    # The shared regex also accepts a trailing newline; this contract does not.
    return type(value) is str and len(value) == 64 and is_sha256_hex(value)


@dataclass(frozen=True)
class GatewayExecutionCheckpoint:
    consumer_ref: str
    epoch: str | None
    revision: int
    stored_sequence: int
    applied_sequence: int
    acknowledged_sequence: int
    projection: dict | None
    stored_events: int

    @property
    def projection_digest(self) -> str | None:
        """SHA-256 of the complete canonical JSON projection, including the batch."""
        return (
            None
            if self.projection is None
            else hashlib.sha256(_json_bytes(self.projection)).hexdigest()
        )


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    ).encode("utf-8", errors="strict")


def _projection(value: object, limit: int) -> dict:
    seen: set[int] = set()

    def validate(item: object, depth: int) -> None:
        if depth > 16:
            raise ValueError("EXECUTION_PROJECTION_INVALID")
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise ValueError("EXECUTION_PROJECTION_INVALID")
            return
        if type(item) in (dict, list):
            if id(item) in seen:
                raise ValueError("EXECUTION_PROJECTION_ALIAS")
            seen.add(id(item))
            if type(item) is dict:
                if any(type(key) is not str or not key for key in item):
                    raise ValueError("EXECUTION_PROJECTION_INVALID")
                for element in item.values():
                    validate(element, depth + 1)
            else:
                for element in item:
                    validate(element, depth + 1)
            return
        raise ValueError("EXECUTION_PROJECTION_INVALID")

    validate(value, 0)
    if (
        type(value) is not dict
        or set(value) != {"schema_version", "state"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["state"]) is not dict
    ):
        raise ValueError("EXECUTION_PROJECTION_INVALID")
    ensure_no_secret_keys(value, "execution_projection")
    if len(_json_bytes(value)) > limit:
        raise ValueError("EXECUTION_PROJECTION_CAPACITY")
    return copy.deepcopy(value)


def _notification_batch(execution: dict, binding, batch: object) -> None:
    if (
        type(batch) is not dict
        or set(batch) != {"version", "batch_id", "through_sequence", "notifications", "status"}
        or type(batch["version"]) is not int
        or batch["version"] != 1
        or not _digest(batch["batch_id"])
        or batch["status"] not in ("pending", "confirmed")
        or type(batch["status"]) is not str
        or not is_strict_int(batch["through_sequence"], minimum=1)
        or batch["through_sequence"] != execution["applied_sequence"]
        or execution["epoch"] is None
    ):
        raise ValueError("EXECUTION_NOTIFICATION_BATCH_INVALID")
    notifications = batch["notifications"]
    if type(notifications) is not list or not 1 <= len(notifications) <= 4096:
        raise ValueError("EXECUTION_NOTIFICATION_BATCH_INVALID")
    ids = set()
    for item in notifications:
        if (
            type(item) is not dict
            or set(item) != {"notification_id", "kind", "object_key", "payload"}
            or not _digest(item["notification_id"])
            or type(item["kind"]) is not str
            or item["kind"] not in ("order", "trade", "fee")
            or type(item["object_key"]) is not str
            or not item["object_key"]
            or type(item["payload"]) is not dict
        ):
            raise ValueError("EXECUTION_NOTIFICATION_BATCH_INVALID")
        try:
            key = item["object_key"].encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise ValueError("EXECUTION_NOTIFICATION_BATCH_INVALID") from None
        if len(key) > 1024 or any(
            ord(char) < 32 or 127 <= ord(char) <= 159 for char in item["object_key"]
        ):
            raise ValueError("EXECUTION_NOTIFICATION_BATCH_INVALID")
        if item["notification_id"] in ids:
            raise ValueError("EXECUTION_NOTIFICATION_BATCH_INVALID")
        ids.add(item["notification_id"])
    if batch["batch_id"] != _batch_id(execution, binding, batch["through_sequence"], notifications):
        raise ValueError("EXECUTION_NOTIFICATION_BATCH_INVALID")
    if (
        batch["status"] == "pending"
        and execution["acknowledged_sequence"] >= batch["through_sequence"]
    ):
        raise ValueError("EXECUTION_NOTIFICATION_BATCH_INVALID")
    # The only confirmation change expands the canonical JSON status by two bytes.
    # Reserve that space before persisting, and reject older unconfirmable candidates.
    if (
        batch["status"] == "pending"
        and len(_json_bytes(execution["projection"])) + len("confirmed") - len("pending")
        > execution["max_projection_bytes"]
    ):
        raise ValueError("EXECUTION_PROJECTION_CAPACITY")


def _batch_id(execution: dict, binding, through: int, notifications: list) -> str:
    value = {
        "domain": "backtrader.gateway.notifications.v1",
        "binding": _binding_mapping(binding),
        "consumer_ref": execution["consumer_ref"],
        "epoch": execution["epoch"],
        "through_sequence": through,
        "notifications": notifications,
    }
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _batch(execution: dict):
    projection = execution["projection"]
    return None if projection is None else projection["state"].get(_NOTIFICATIONS)


def verify_gateway_trade_attribution(event, record, binding) -> bool:
    """Validate a Gateway journal bridge against this durable command.

    The bridge describes the journal's original-order-to-venue alias match;
    it does not add fields to the native trade observation.
    """
    from bt_api_base.direct_write_protocol import DirectExecutionEventKind
    from bt_api_base.gateway_execution_stream_protocol import GatewayTradeAttribution

    obs = event.observation
    proof = obs.trade_attribution
    if proof is None:
        return False
    if type(proof) is not GatewayTradeAttribution:
        raise ValueError("EXECUTION_TRADE_ATTRIBUTION_MISMATCH")
    proof = GatewayTradeAttribution.from_mapping(proof.to_mapping())
    original = set(proof.original_binding_key_digests)
    strong = set(record.strong_identity_key_digests)
    if (obs.kind is not DirectExecutionEventKind.TRADE
            or record.binding != binding or record.request_key != event.request_key
            or record.native_identity is None
            or event.command_principal != binding.principal
            or event.reservation_id != record.reservation_id
            or event.command_digest != record.digest
            or proof.account_scope != binding.account_scope
            or proof.strategy_scope != binding.strategy_scope
            or proof.fact_digest != event.fact_digest
            or proof.reservation_id != event.reservation_id
            or proof.command_digest != event.command_digest
            or proof.anchor_sequence >= event.sequence
            or proof.venue_key_digest != obs.venue_key_digest
            or proof.venue_key_digest not in obs.identity_key_digests
            or obs.account_scope != binding.account_scope
            or obs.route != record.native_identity.exchange_name
            or not original or not original.issubset(strong)):
        raise ValueError("EXECUTION_TRADE_ATTRIBUTION_MISMATCH")
    return True


def _event(event: GatewayExecutionStreamEvent, state: dict, binding) -> dict:
    if type(event) is not GatewayExecutionStreamEvent:
        raise ValueError("EXECUTION_EVENT_INVALID")
    event = GatewayExecutionStreamEvent.from_mapping(
        event.to_mapping(schema_version=3), schema_version=3
    )
    entry = state["gateway"]["intents"].get(event.request_key)
    delegated = None
    if state["version"] == 7 and entry is not None and entry["record"] is None:
        delegated = state["gateway"]["delegated_commands"].get(event.request_key)
    if delegated is not None:
        return _delegated_event(event, state, binding, entry, delegated)
    if entry is None or entry["record"] is None:
        raise ValueError("EXECUTION_EVENT_ORPHAN")
    intent = gateway_intent_from_mapping(entry["intent"], expected_binding=binding)
    record = _record(entry["record"], binding)
    obs = event.observation
    payload = json.loads(intent.canonical_payload)
    # A caller must first persist the original request's native command record;
    # the RPC route is not an exchange route and cannot establish this binding.
    if record.native_identity is None:
        raise ValueError("GATEWAY_EXECUTION_IDENTITY_REQUIRED")
    verify_gateway_trade_attribution(event, record, binding)
    if (
        event.command_principal != binding.principal
        or event.command_digest != intent.digest
        or event.command_digest != record.digest
        or event.reservation_id != record.reservation_id
        or obs.account_scope != binding.account_scope
        or obs.route != record.native_identity.exchange_name
        or obs.instrument.native_symbol != payload["symbol"]
        or not set(obs.binding_key_digests).issubset(record.strong_identity_key_digests)
    ):
        raise ValueError("EXECUTION_EVENT_BINDING_MISMATCH")
    attribution = event.cancel_attribution
    if attribution is not None:
        attempt = state["gateway"]["cancel_attempts"].get(attribution.operation_id)
        if attempt is None:
            raise ValueError("EXECUTION_CANCEL_ATTRIBUTION_MISMATCH")
        plan = _cancel_plan(attempt["plan"], binding, state["gateway"]["intents"])
        if (
            plan.request_key != event.request_key
            or plan.reservation_id != event.reservation_id
            or plan.digest != event.command_digest
        ):
            raise ValueError("EXECUTION_CANCEL_ATTRIBUTION_MISMATCH")
        if attempt["record"] is not None:
            cancel = _cancel_record(attempt["record"], binding, plan)
            if cancel.attempt_id != attribution.attempt_id:
                raise ValueError("EXECUTION_CANCEL_ATTRIBUTION_MISMATCH")
    return event.to_mapping(schema_version=3)


def _delegated_event(event, state: dict, binding, entry: dict, delegated: dict) -> dict:
    """Bind a return of an order the Risk delegate placed for this strategy (v7).

    The strategy holds no own command record for it: the event is bound by its
    request key (one Backtrader recorded as Risk-routed), the reservation and
    digest of that command and the delegate principal the Gateway reported for
    the key, persisted before any return is accepted. Anything else is refused.
    """
    from .gateway_order_state import _delegated_record

    record = _delegated_record(delegated, event.request_key, state["gateway"]["intents"], binding)
    intent = gateway_intent_from_mapping(entry["intent"], expected_binding=binding)
    obs = event.observation
    payload = json.loads(intent.canonical_payload)
    if record.actor_principal is None:
        raise ValueError("GATEWAY_DELEGATED_ACTOR_REQUIRED")
    if (
        event.command_principal != record.actor_principal
        or event.command_principal == binding.principal
        or event.command_digest != intent.digest
        or event.command_digest != record.digest
        or event.reservation_id != record.reservation_id
        or obs.account_scope != binding.account_scope
        or obs.instrument.native_symbol != payload["symbol"]
    ):
        raise ValueError("EXECUTION_EVENT_BINDING_MISMATCH")
    proof = obs.trade_attribution
    if proof is not None:
        # The alias bridge is checked on every field this strategy can see; the
        # delegate's strong identity keys are not visible to it.
        from bt_api_base.direct_write_protocol import DirectExecutionEventKind
        from bt_api_base.gateway_execution_stream_protocol import GatewayTradeAttribution

        if type(proof) is not GatewayTradeAttribution:
            raise ValueError("EXECUTION_TRADE_ATTRIBUTION_MISMATCH")
        proof = GatewayTradeAttribution.from_mapping(proof.to_mapping())
        if (obs.kind is not DirectExecutionEventKind.TRADE
                or proof.account_scope != binding.account_scope
                or proof.strategy_scope != binding.strategy_scope
                or proof.fact_digest != event.fact_digest
                or proof.reservation_id != event.reservation_id
                or proof.command_digest != event.command_digest
                or proof.anchor_sequence >= event.sequence
                or proof.venue_key_digest != obs.venue_key_digest
                or proof.venue_key_digest not in obs.identity_key_digests):
            raise ValueError("EXECUTION_TRADE_ATTRIBUTION_MISMATCH")
    attribution = event.cancel_attribution
    if attribution is not None:
        from .gateway_order_state import _delegated_cancel_observation, _delegated_cancel_plan

        attempt = state["gateway"]["delegated_cancel_attempts"].get(attribution.operation_id)
        if attempt is None:
            raise ValueError("EXECUTION_CANCEL_ATTRIBUTION_MISMATCH")
        plan = _delegated_cancel_plan(attempt["plan"], state, binding)
        if (plan.request_key != event.request_key or plan.reservation_id != event.reservation_id
                or plan.digest != event.command_digest):
            raise ValueError("EXECUTION_CANCEL_ATTRIBUTION_MISMATCH")
        if attempt["observation"] is not None:
            cancel = _delegated_cancel_observation(attempt["observation"], plan, binding)
            if cancel.attempt_id != attribution.attempt_id:
                raise ValueError("EXECUTION_CANCEL_ATTRIBUTION_MISMATCH")
    return event.to_mapping(schema_version=3)


def _check_event_conflicts(mappings: list[dict]) -> None:
    facts: dict[str, bytes] = {}
    trades: dict[tuple, tuple] = {}
    previous = 0
    for item in mappings:
        event = GatewayExecutionStreamEvent.from_mapping(item, schema_version=3)
        if event.sequence <= previous:
            raise ValueError("EXECUTION_SEQUENCE_CONFLICT")
        previous = event.sequence
        fact_content = dict(item)
        fact_content.pop("sequence")
        encoded = _json_bytes(fact_content)
        if event.fact_digest in facts and facts[event.fact_digest] != encoded:
            raise ValueError("EXECUTION_FACT_CONFLICT")
        facts[event.fact_digest] = encoded
        obs = event.observation
        if obs.trade_metadata_only and obs.trade_key_digest is None:
            raise ValueError("EXECUTION_TRADE_METADATA_WITHOUT_ORIGINAL")
        if obs.trade_key_digest is not None:
            key = (obs.account_scope, obs.route, obs.trade_key_digest)
            if obs.trade_quantity is None or obs.trade_price is None:
                raise ValueError("EXECUTION_TRADE_ECONOMICS_INCOMPLETE")
            identity = (
                event.request_key,
                event.reservation_id,
                event.command_digest,
                event.command_principal,
            )
            economics = (
                tuple(sorted(obs.instrument.to_dict().items())),
                obs.trading_day,
                obs.side,
                obs.offset,
                Decimal(obs.trade_quantity),
                Decimal(obs.trade_price),
                obs.venue_key_digest,
            )
            if key in trades and trades[key][0] != identity:
                raise ValueError("EXECUTION_TRADE_BINDING_CONFLICT")
            if key in trades and trades[key][1] != economics:
                raise ValueError("EXECUTION_TRADE_CONFLICT")
            prior = trades.get(key)
            if obs.trade_metadata_only and prior is None:
                raise ValueError("EXECUTION_TRADE_METADATA_WITHOUT_ORIGINAL")
            known_date = None if prior is None else prior[2]
            if known_date is not None and obs.trade_date is not None:
                if known_date != obs.trade_date:
                    raise ValueError("EXECUTION_TRADE_DATE_CONFLICT")
            elif prior is not None and obs.trade_date is not None and not obs.trade_metadata_only:
                raise ValueError("EXECUTION_TRADE_METADATA_EFFECT_MISMATCH")
            known_time = None if prior is None else prior[3]
            if known_time and obs.trade_time and known_time != obs.trade_time:
                raise ValueError("EXECUTION_TRADE_TIME_CONFLICT")
            trades[key] = (identity, economics, known_date or obs.trade_date,
                           known_time or obs.trade_time)


def validate_execution_state(state: dict, binding) -> None:
    execution = state["gateway"]["execution"]
    if type(execution) is not dict or set(execution) != _EXECUTION_KEYS:
        raise ValueError("EXECUTION_STATE_INVALID")
    for key, maximum in (
        ("max_events", _MAX_EVENTS),
        ("max_event_bytes", _MAX_EVENT_BYTES),
        ("max_projection_bytes", _MAX_PROJECTION_BYTES),
    ):
        if not is_strict_int(execution[key], minimum=1) or execution[key] > maximum:
            raise ValueError("EXECUTION_CAPACITY_INVALID")
    consumer = execution["consumer_ref"]
    if (
        type(consumer) is not str
        or len(consumer) != 70
        or not consumer.startswith("gexec:")
        or any(c not in "0123456789abcdef" for c in consumer[6:])
    ):
        raise ValueError("EXECUTION_CONSUMER_INVALID")
    epoch = execution["epoch"]
    if epoch is not None and (
        type(epoch) is not str
        or len(epoch) != 64
        or any(c not in "0123456789abcdef" for c in epoch)
    ):
        raise ValueError("EXECUTION_EPOCH_INVALID")
    for key in ("revision", "stored_sequence", "applied_sequence", "acknowledged_sequence"):
        if not is_strict_int(execution[key], minimum=0) or execution[key] >= 2**63:
            raise ValueError("EXECUTION_STATE_INVALID")
    if (
        not execution["acknowledged_sequence"]
        <= execution["applied_sequence"]
        <= execution["stored_sequence"]
    ):
        raise ValueError("EXECUTION_WATERMARK_INVALID")
    events = execution["events"]
    if (
        type(events) is not list
        or len(events) > execution["max_events"]
        or sum(len(_json_bytes(item)) for item in events) > execution["max_event_bytes"]
    ):
        raise ValueError("EXECUTION_EVENT_CAPACITY")
    for item in events:
        event = GatewayExecutionStreamEvent.from_mapping(item, schema_version=3)
        if _event(event, state, binding) != item:
            raise ValueError("EXECUTION_EVENT_INVALID")
    _check_event_conflicts(events)
    positions = {item["sequence"]: index for index, item in enumerate(events)}
    sequences = set(positions)
    if execution["stored_sequence"] != (events[-1]["sequence"] if events else 0):
        raise ValueError("EXECUTION_WATERMARK_INVALID")
    if execution["applied_sequence"] and execution["applied_sequence"] not in sequences:
        raise ValueError("EXECUTION_WATERMARK_INVALID")
    if execution["projection"] is not None:
        _projection(execution["projection"], execution["max_projection_bytes"])
        if _NOTIFICATIONS in execution["projection"]["state"]:
            _notification_batch(
                execution, binding, execution["projection"]["state"][_NOTIFICATIONS]
            )
    if (execution["applied_sequence"] == 0) != (execution["projection"] is None):
        raise ValueError("EXECUTION_PROJECTION_INVALID")
    if epoch is None and (
        events or execution["applied_sequence"] or execution["acknowledged_sequence"]
    ):
        raise ValueError("EXECUTION_EPOCH_INVALID")
    receipts = execution["receipts"]
    if type(receipts) is not list or len(receipts) > len(events) + 1:
        raise ValueError("EXECUTION_RECEIPTS_INVALID")
    for receipt in receipts:
        if (
            type(receipt) is not dict
            or set(receipt) != {"after", "digest", "offered", "ack", "has_more", "count"}
            or not is_strict_int(receipt["after"], minimum=0)
            or not is_strict_int(receipt["count"], minimum=0)
            or receipt["count"] > 256
            or type(receipt["digest"]) is not str
            or len(receipt["digest"]) != 64
            or any(c not in "0123456789abcdef" for c in receipt["digest"])
        ):
            raise ValueError("EXECUTION_RECEIPTS_INVALID")
        if receipt["after"] != 0 and receipt["after"] not in sequences:
            raise ValueError("EXECUTION_RECEIPTS_INVALID")
        start = 0 if receipt["after"] == 0 else positions[receipt["after"]] + 1
        selected = events[start : start + receipt["count"]]
        if len(selected) != receipt["count"] or epoch is None:
            raise ValueError("EXECUTION_RECEIPTS_INVALID")
        reconstructed = GatewayExecutionStreamPage(
            binding,
            consumer,
            epoch,
            receipt["offered"],
            receipt["ack"],
            receipt["has_more"],
            tuple(
                GatewayExecutionStreamEvent.from_mapping(item, schema_version=3)
                for item in selected
            ),
        )
        if hashlib.sha256(_json_bytes(reconstructed.to_mapping())).hexdigest() != receipt["digest"]:
            raise ValueError("EXECUTION_RECEIPTS_INVALID")


def upgrade_for_execution(
    cls,
    strategy_dir,
    strategy_uuid,
    binding,
    *,
    consumer_ref,
    max_events,
    max_event_bytes,
    max_projection_bytes,
    lock_timeout,
):
    for value, maximum in (
        (max_events, _MAX_EVENTS),
        (max_event_bytes, _MAX_EVENT_BYTES),
        (max_projection_bytes, _MAX_PROJECTION_BYTES),
    ):
        if not is_strict_int(value, minimum=1) or value > maximum:
            raise ValueError("INVALID_EXECUTION_CAPACITY")
    host = cls(strategy_dir, strategy_uuid, binding, lock_timeout=lock_timeout)
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] == 3:
            state["version"] = 4
            state["gateway"]["execution"] = {
                "consumer_ref": consumer_ref,
                "epoch": None,
                "revision": 0,
                "stored_sequence": 0,
                "applied_sequence": 0,
                "acknowledged_sequence": 0,
                "projection": None,
                "events": [],
                "receipts": [],
                "max_events": max_events,
                "max_event_bytes": max_event_bytes,
                "max_projection_bytes": max_projection_bytes,
            }
            validate_execution_state(state, host._binding)
            host._store._store(state, trim_history=False)
        elif state["version"] in (4, 5, 6, 7):
            execution = state["gateway"]["execution"]
            if (
                execution["consumer_ref"] != consumer_ref
                or execution["max_events"] != max_events
                or execution["max_event_bytes"] != max_event_bytes
                or execution["max_projection_bytes"] != max_projection_bytes
            ):
                raise ValueError("EXECUTION_CONFIGURATION_MISMATCH")
        else:
            raise ValueError("GATEWAY_EXECUTION_UPGRADE_REQUIRED")
    return host


def _load(host):
    state = host._store._load()
    host._check_state(state)
    if state["version"] not in (4, 5, 6, 7):
        raise ValueError("GATEWAY_EXECUTION_UPGRADE_REQUIRED")
    return state, state["gateway"]["execution"]


def _checkpoint(execution) -> GatewayExecutionCheckpoint:
    return GatewayExecutionCheckpoint(
        execution["consumer_ref"],
        execution["epoch"],
        execution["revision"],
        execution["stored_sequence"],
        execution["applied_sequence"],
        execution["acknowledged_sequence"],
        copy.deepcopy(execution["projection"]),
        len(execution["events"]),
    )


def load_checkpoint(host):
    with host._store._lock():
        _, execution = _load(host)
        return _checkpoint(execution)


def ingest_page(host, page, *, expected_revision, after_sequence):
    if type(page) is not GatewayExecutionStreamPage:
        raise ValueError("EXECUTION_PAGE_INVALID")
    if not is_strict_int(expected_revision, minimum=0) or not is_strict_int(
        after_sequence, minimum=0
    ):
        raise ValueError("EXECUTION_CURSOR_INVALID")
    with host._store._lock():
        state, execution = _load(host)
        page = GatewayExecutionStreamPage.from_mapping(
            page.to_mapping(),
            expected_binding=host._binding,
            expected_consumer_ref=execution["consumer_ref"],
        )
        if execution["epoch"] is not None and page.epoch != execution["epoch"]:
            raise ValueError("EXECUTION_EPOCH_MISMATCH")
        if page.acknowledged_sequence > execution["applied_sequence"]:
            raise ValueError("EXECUTION_ACK_AHEAD")
        if execution["epoch"] is None and page.acknowledged_sequence != 0:
            raise ValueError("EXECUTION_ACK_AHEAD")
        mapping = page.to_mapping()
        digest = hashlib.sha256(_json_bytes(mapping)).hexdigest()
        receipt = {
            "after": after_sequence,
            "digest": digest,
            "offered": page.offered_sequence,
            "ack": page.acknowledged_sequence,
            "has_more": page.has_more,
            "count": len(page.events),
        }
        if receipt in execution["receipts"]:
            return _checkpoint(execution)
        if expected_revision != execution["revision"]:
            raise ValueError("EXECUTION_REVISION_CONFLICT")
        if after_sequence != execution["stored_sequence"]:
            raise ValueError("EXECUTION_SEQUENCE_CONFLICT")
        if page.events and page.events[0].sequence <= after_sequence:
            raise ValueError("EXECUTION_SEQUENCE_CONFLICT")
        new = [_event(event, state, host._binding) for event in page.events]
        combined = execution["events"] + new
        if (
            len(combined) > execution["max_events"]
            or sum(len(_json_bytes(item)) for item in combined) > execution["max_event_bytes"]
        ):
            raise ValueError("EXECUTION_EVENT_CAPACITY")
        _check_event_conflicts(combined)
        changed = execution["epoch"] is None or bool(new)
        if changed:
            execution["epoch"] = page.epoch
            execution["events"] = combined
            execution["receipts"].append(receipt)
            if new:
                execution["stored_sequence"] = new[-1]["sequence"]
            execution["revision"] += 1
            host._store._store(state, trim_history=False)
        return _checkpoint(execution)


def ingest_result(host, result, *, expected_revision):
    """Bind a page to its SDK read request; this is not authorization evidence."""
    from bt_api_py.gateway_execution_stream_client import (
        GatewayExecutionReadContext,
        GatewayExecutionStreamClientResult,
    )

    if type(result) is not GatewayExecutionStreamClientResult:
        raise ValueError("EXECUTION_READ_RESULT_INVALID")
    context = result.request_context
    page = result.page
    if (
        result.outcome != "OBSERVED"
        or type(result.outcome) is not str
        or type(context) is not GatewayExecutionReadContext
        or type(page) is not GatewayExecutionStreamPage
        or result.progress is not None
        or result.code is not None
    ):
        raise ValueError("EXECUTION_READ_RESULT_INVALID")
    context = GatewayExecutionReadContext(
        context.binding,
        context.consumer_ref,
        context.after_sequence,
        context.expected_epoch,
        context.limit,
    )
    page = GatewayExecutionStreamPage.from_mapping(
        page.to_mapping(),
        expected_binding=host._binding,
        expected_consumer_ref=context.consumer_ref,
    )
    after = context.after_sequence
    limit = context.limit
    epoch = context.expected_epoch
    if (
        context.binding != host._binding
        or type(context.consumer_ref) is not str
        or not is_strict_int(after, minimum=0)
        or after >= 2**63
        or not is_strict_int(limit, minimum=1)
        or limit > 256
        or (
            epoch is not None
            and (
                type(epoch) is not str
                or len(epoch) != 64
                or any(c not in "0123456789abcdef" for c in epoch)
            )
        )
        or (after > 0 and epoch is None)
        or page.binding != context.binding
        or page.consumer_ref != context.consumer_ref
        or (epoch is not None and page.epoch != epoch)
        or page.offered_sequence < after
        or len(page.events) > limit
        or any(
            event.sequence <= after or event.sequence > page.offered_sequence
            for event in page.events
        )
    ):
        raise ValueError("EXECUTION_READ_CONTEXT_MISMATCH")
    checkpoint = load_checkpoint(host)
    if context.consumer_ref != checkpoint.consumer_ref:
        raise ValueError("EXECUTION_READ_CONTEXT_MISMATCH")
    return ingest_page(host, page, expected_revision=expected_revision, after_sequence=after)


def read_events(host, *, after_sequence, limit):
    if not is_strict_int(limit, minimum=1) or limit > 256:
        raise ValueError("EXECUTION_READ_LIMIT")
    with host._store._lock():
        _, execution = _load(host)
        after = execution["applied_sequence"] if after_sequence is None else after_sequence
        if not is_strict_int(after, minimum=0) or after > execution["stored_sequence"]:
            raise ValueError("EXECUTION_CURSOR_INVALID")
        return tuple(
            GatewayExecutionStreamEvent.from_mapping(copy.deepcopy(item), schema_version=3)
            for item in execution["events"]
            if item["sequence"] > after
        )[:limit]


def commit_projection(
    host, through_sequence, projection, *, expected_revision, expected_applied_sequence
):
    if any(
        not is_strict_int(value, minimum=0)
        for value in (through_sequence, expected_revision, expected_applied_sequence)
    ):
        raise ValueError("EXECUTION_CURSOR_INVALID")
    with host._store._lock():
        state, execution = _load(host)
        projection = _projection(projection, execution["max_projection_bytes"])
        if _NOTIFICATIONS in projection["state"]:
            raise ValueError("EXECUTION_NOTIFICATION_RESERVED")
        if _batch(execution) is not None and _batch(execution)["status"] == "pending":
            raise ValueError("EXECUTION_NOTIFICATION_PENDING")
        if (
            through_sequence == execution["applied_sequence"]
            and execution["projection"] is not None
            and _json_bytes(projection) == _json_bytes(execution["projection"])
        ):
            return _checkpoint(execution)
        if (
            expected_revision != execution["revision"]
            or expected_applied_sequence != execution["applied_sequence"]
        ):
            raise ValueError("EXECUTION_REVISION_CONFLICT")
        if through_sequence <= execution["applied_sequence"] or through_sequence not in {
            item["sequence"] for item in execution["events"]
        }:
            raise ValueError("EXECUTION_APPLIED_CONFLICT")
        execution["applied_sequence"] = through_sequence
        execution["projection"] = projection
        execution["revision"] += 1
        host._store._store(state, trim_history=False)
        return _checkpoint(execution)


def commit_notification_batch(
    host,
    through_sequence,
    projection,
    notifications,
    *,
    expected_revision,
    expected_applied_sequence,
):
    if any(
        not is_strict_int(value, minimum=0)
        for value in (through_sequence, expected_revision, expected_applied_sequence)
    ):
        raise ValueError("EXECUTION_CURSOR_INVALID")
    with host._store._lock():
        state, execution = _load(host)
        projection = _projection(projection, execution["max_projection_bytes"])
        if _NOTIFICATIONS in projection["state"]:
            raise ValueError("EXECUTION_NOTIFICATION_RESERVED")
        # Validate the whole structure before computing its canonical identity.
        candidate = {
            "version": 1,
            "batch_id": "0" * 64,
            "through_sequence": through_sequence,
            "notifications": notifications,
            "status": "pending",
        }
        projection["state"][_NOTIFICATIONS] = candidate
        projection = _projection(projection, execution["max_projection_bytes"])
        candidate = projection["state"][_NOTIFICATIONS]
        current = _batch(execution)
        # A committed identical pending batch is safe to retry after an ambiguous write.
        if through_sequence == execution["applied_sequence"] and current is not None:
            candidate["batch_id"] = _batch_id(
                execution, host._binding, through_sequence, candidate["notifications"]
            )
            if current["status"] == "pending" and _json_bytes(projection) == _json_bytes(
                execution["projection"]
            ):
                return _checkpoint(execution)
        if current is not None and current["status"] == "pending":
            raise ValueError("EXECUTION_NOTIFICATION_PENDING")
        if (
            expected_revision != execution["revision"]
            or expected_applied_sequence != execution["applied_sequence"]
        ):
            raise ValueError("EXECUTION_REVISION_CONFLICT")
        if through_sequence <= execution["applied_sequence"] or through_sequence not in {
            item["sequence"] for item in execution["events"]
        }:
            raise ValueError("EXECUTION_APPLIED_CONFLICT")
        candidate["batch_id"] = _batch_id(
            execution, host._binding, through_sequence, candidate["notifications"]
        )
        execution["applied_sequence"] = through_sequence
        execution["projection"] = projection
        _notification_batch(execution, host._binding, candidate)
        execution["revision"] += 1
        host._store._store(state, trim_history=False)
        return _checkpoint(execution)


def load_notification_batch(host):
    with host._store._lock():
        _, execution = _load(host)
        return copy.deepcopy(_batch(execution))


def confirm_notification_batch(
    host, batch_id, *, expected_revision, expected_applied_sequence, expected_projection_digest
):
    if (
        not _digest(batch_id)
        or not _digest(expected_projection_digest)
        or not is_strict_int(expected_revision, minimum=0)
        or not is_strict_int(expected_applied_sequence, minimum=0)
    ):
        raise ValueError("EXECUTION_NOTIFICATION_CONFIRM_INVALID")
    with host._store._lock():
        state, execution = _load(host)
        batch = _batch(execution)
        if (
            batch is None
            or batch["batch_id"] != batch_id
            or expected_applied_sequence != execution["applied_sequence"]
        ):
            raise ValueError("EXECUTION_NOTIFICATION_CONFIRM_CONFLICT")
        projection = execution["projection"]
        current_digest = hashlib.sha256(_json_bytes(projection)).hexdigest()
        if batch["status"] == "confirmed":
            if expected_revision > execution["revision"]:
                raise ValueError("EXECUTION_REVISION_CONFLICT")
            original = copy.deepcopy(projection)
            original["state"][_NOTIFICATIONS]["status"] = "pending"
            pending_digest = hashlib.sha256(_json_bytes(original)).hexdigest()
            if expected_projection_digest not in (pending_digest, current_digest):
                raise ValueError("EXECUTION_NOTIFICATION_DIGEST_CONFLICT")
            return _checkpoint(execution)
        if expected_revision != execution["revision"]:
            raise ValueError("EXECUTION_REVISION_CONFLICT")
        if expected_projection_digest != current_digest:
            raise ValueError("EXECUTION_NOTIFICATION_DIGEST_CONFLICT")
        batch["status"] = "confirmed"
        execution["revision"] += 1
        host._store._store(state, trim_history=False)
        return _checkpoint(execution)


def record_ack(host, progress):
    if type(progress) is not GatewayExecutionStreamProgress:
        raise ValueError("EXECUTION_PROGRESS_INVALID")
    with host._store._lock():
        state, execution = _load(host)
        progress = GatewayExecutionStreamProgress.from_mapping(
            progress.to_mapping(),
            expected_binding=host._binding,
            expected_consumer_ref=execution["consumer_ref"],
        )
        if execution["epoch"] is None or progress.epoch != execution["epoch"]:
            raise ValueError("EXECUTION_EPOCH_MISMATCH")
        if progress.acknowledged_sequence > execution["applied_sequence"]:
            raise ValueError("EXECUTION_ACK_AHEAD")
        if progress.acknowledged_sequence > execution["acknowledged_sequence"]:
            if _batch(execution) is not None and _batch(execution)["status"] == "pending":
                raise ValueError("EXECUTION_NOTIFICATION_PENDING")
            execution["acknowledged_sequence"] = progress.acknowledged_sequence
            execution["revision"] += 1
            host._store._store(state, trim_history=False)
        return _checkpoint(execution)


def has_unresolved_gateway_execution(state: dict) -> bool:
    """Check watermarks and the explicitly persisted notification batch."""
    if state["version"] not in (4, 5, 6, 7):
        return False
    execution = state["gateway"]["execution"]
    return (
        execution["stored_sequence"] > execution["applied_sequence"]
        or execution["applied_sequence"] > execution["acknowledged_sequence"]
        or (_batch(execution) is not None and _batch(execution)["status"] == "pending")
    )
