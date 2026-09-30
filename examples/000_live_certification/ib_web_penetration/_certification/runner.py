"""Fail-closed v2 live certification runner; no offline or mock execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .backends import Backend, create_backend
from .cases import CASES
from .config import Config, Environment, Grants
from .evidence import EvidenceWriter
from .models import (
    Action,
    ActionPlan,
    Attestation,
    Binding,
    CaseResult,
    CertificationError,
    CleanupReport,
    InstrumentSpec,
    MarketReference,
    Observation,
    OperationEvidence,
    PlannedOperation,
    Receipt,
    Reconciliation,
    Risk,
    StateSnapshot,
    Status,
    UnsupportedCaseError,
)

_REMOTE = ("provider", "exchange", "broker", "gateway", "remote_log")
UTC = timezone.utc
_THRESHOLD = {"TH01": 5, "TH02": 2, "TH03": 10, "TH04": 3, "TH05": 3, "TH06": 2}
_REJECTION = {"E01": "funds", "E02": "position", "E03": "market_state"}
_VALIDATION = {"V01": "invalid_instrument", "V02": "invalid_price_tick", "V03": "oversized_order"}
_PROOF: dict[str, tuple[str, ...]] = {
    "B01": ("orders", "batch_cancel_id", "partial_fill_count"),
    "B02": ("orders", "batch_cancel_id"),
    "C01": ("account_id", "auth_session_id", "login_session_id", "authenticated"),
    "E01": (
        "source_request_id",
        "rejection_code",
        "rejection_category",
        "provider_reason",
        "classification_rule_id",
    ),
    "E02": (
        "source_request_id",
        "rejection_code",
        "rejection_category",
        "provider_reason",
        "classification_rule_id",
    ),
    "E03": (
        "source_request_id",
        "rejection_code",
        "rejection_category",
        "provider_reason",
        "classification_rule_id",
    ),
    "EM01": (
        "external_ref",
        "operator_ref",
        "external_authorization_id",
        "restriction_id",
        "restoration_ref",
        "restriction_restored",
        "write_guard_active",
    ),
    "EM02": (
        "external_ref",
        "operator_ref",
        "external_authorization_id",
        "strategy_id",
        "pause_state",
        "write_guard_active",
    ),
    "EM03": (
        "external_ref",
        "operator_ref",
        "external_authorization_id",
        "session_id",
        "disconnect_state",
        "release_event_id",
        "write_guard_active",
    ),
    "L01": (
        "external_ref",
        "trace_id",
        "order_ref",
        "trade_id",
        "submission_log_id",
        "execution_log_id",
        "submission_log",
        "execution_log",
    ),
    "L02": (
        "connection_session_id",
        "readiness_session_id",
        "connection_log_id",
        "readiness_log_id",
    ),
    "L03": ("external_ref", "trace_id", "metric", "digest", "normalized_record"),
    "L04": ("source_request_id", "validation_rule", "rejection_code", "dispatch_absent"),
    "M01": (
        "connection_session_id",
        "readiness_session_id",
        "connection_event_id",
        "readiness_event_id",
    ),
    "M02": (
        "external_ref",
        "operator_ref",
        "external_authorization_id",
        "old_session_id",
        "disconnect_event_id",
        "disconnect_generation",
        "native_disconnect",
    ),
    "M03": (
        "external_ref",
        "operator_ref",
        "external_authorization_id",
        "old_session_id",
        "new_session_id",
        "disconnect_event_id",
        "recovery_event_id",
        "disconnect_generation",
        "recovery_generation",
        "native_disconnect",
        "auth_success",
        "login_success",
        "subscription_restored",
    ),
    "M04": ("order_id", "submit_monitor_id", "submit_count", "provider_order_status"),
    "M05": (
        "order_id",
        "submit_monitor_id",
        "cancel_monitor_id",
        "submit_count",
        "cancel_count",
        "provider_order_status",
    ),
    "O01": (
        "order_ids",
        "request_ids",
        "repetition_count",
        "monitor_event_id",
        "terminal_order_ids",
    ),
    "O02": (
        "order_ids",
        "request_ids",
        "position_id",
        "repetition_count",
        "monitor_event_id",
        "terminal_order_ids",
    ),
    "O03": (
        "order_id",
        "request_ids",
        "cancel_attempt_count",
        "monitor_event_id",
        "terminal_status",
    ),
    "T01": ("order_id", "accepted", "terminal_status", "cancel_request_id"),
    "T02": ("position_id", "close_order_id", "accepted", "closed_quantity", "terminal_status"),
    "T03": ("order_id", "accepted", "terminal_status", "cancel_request_id"),
    "TH01": ("threshold_value", "config_snapshot_id"),
    "TH02": (
        "threshold_value",
        "config_snapshot_id",
        "baseline_count",
        "observed_count",
        "warning_id",
        "warning_count",
        "request_ids",
    ),
    "TH03": ("threshold_value", "config_snapshot_id"),
    "TH04": (
        "threshold_value",
        "config_snapshot_id",
        "baseline_count",
        "observed_count",
        "warning_id",
        "warning_count",
        "request_ids",
    ),
    "TH05": ("threshold_value", "config_snapshot_id", "window_seconds"),
    "TH06": (
        "threshold_value",
        "config_snapshot_id",
        "baseline_count",
        "observed_count",
        "warning_id",
        "warning_count",
        "request_ids",
    ),
    "V01": (
        "source_request_id",
        "validation_type",
        "validation_rule",
        "rule_snapshot_id",
        "rejection_code",
        "dispatch_absent",
    ),
    "V02": (
        "source_request_id",
        "validation_type",
        "validation_rule",
        "rule_snapshot_id",
        "rejection_code",
        "dispatch_absent",
    ),
    "V03": (
        "source_request_id",
        "validation_type",
        "validation_rule",
        "rule_snapshot_id",
        "rejection_code",
        "dispatch_absent",
    ),
}


def case_proof_fields(case_id: str) -> tuple[str, ...]:
    """Return the immutable evidence-field contract for a case entry point."""
    try:
        return _PROOF[case_id]
    except KeyError as exc:
        raise CertificationError("unknown live certification case") from exc


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CertificationError("provider timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CertificationError("provider timestamp lacks timezone")
    return parsed.astimezone(UTC)


def _remote(source: str) -> bool:
    return source in _REMOTE or source.startswith(tuple(f"{x}:" for x in _REMOTE))


def _fresh(value: str, seconds: int) -> bool:
    return datetime.now(UTC) - timedelta(seconds=seconds) <= _utc(value) <= datetime.now(UTC)


def _channel(attestation: Attestation, instance: str, channel: str, role: str) -> bool:
    return any(
        (c.instance, c.channel, c.role) == (instance, channel, role) for c in attestation.channels
    )


def _authorize(config: Config, grants: Grants, risk: Risk, environment: Environment) -> None:
    config.policy.authorize(risk, environment, grants)
    if risk == Risk.READ:
        return
    level = "DANGEROUS" if risk == Risk.DANGEROUS else "WRITE"
    if environment.kind == "production":
        level = "PRODUCTION_" + level
    expected = f"{config.venue}:{environment.name}:{level}"
    dangerous_level = "PRODUCTION_DANGEROUS" if environment.kind == "production" else "DANGEROUS"
    dangerous = f"{config.venue}:{environment.name}:{dangerous_level}"
    if grants.confirm != expected and not (risk == Risk.WRITE and grants.confirm == dangerous):
        raise CertificationError(f"write confirmation must exactly equal {expected}")


def _attest(config: Config, account: str, att: Attestation) -> Binding:
    binding = Binding(config.venue, config.environment.name, config.environment.kind, account)
    if (
        att.binding != binding
        or att.contract_version != 2
        or not _remote(att.source)
        or not _fresh(att.observed_at, 60)
    ):
        raise CertificationError("v2 live account/environment attestation mismatch")
    if (
        any(
            att.payload.get(k) != v
            for k, v in {
                "provider_venue": binding.venue,
                "provider_environment_kind": binding.environment_kind,
                "provider_account_id": binding.account_ref,
            }.items()
        )
        or not att.payload.get("provider_environment_id")
        or not att.provider_session_id
        or att.payload.get("close_semantics") != "local_transport_only"
    ):
        raise CertificationError("attestation lacks provider-bound identity")
    roles = {c.role for c in att.channels}
    if not {"command_response", "independent_event", "query", "state_snapshot"} <= roles:
        raise UnsupportedCaseError("v2 trusted channel registry incomplete")
    return binding


def _instrument(
    config: Config, binding: Binding, spec: InstrumentSpec, symbol: str, att: Attestation
) -> None:
    if (
        spec.binding != binding
        or spec.symbol != symbol
        or not _remote(spec.source)
        or not _fresh(spec.observed_at, 60)
        or not _channel(att, spec.source_instance, spec.source_channel, "query")
    ):
        raise CertificationError("instrument specification is unbound or stale")
    if spec.product_type not in {"spot", "linear", "inverse", "fx_lot", "linear_quote_multiplier"}:
        raise UnsupportedCaseError("unsupported instrument product type")
    if spec.product_type == "spot":
        valid = (
            spec.quantity_unit == spec.base_currency
            and spec.contract_value_currency == spec.base_currency
            and spec.quote_currency == config.policy.notional_currency
            and spec.contract_value == 1
        )
    elif spec.product_type in {"linear", "fx_lot"}:
        valid = (
            spec.quantity_unit == ("lots" if spec.product_type == "fx_lot" else "contracts")
            and spec.contract_value_currency == spec.base_currency
            and spec.quote_currency == config.policy.notional_currency
        )
    elif spec.product_type == "linear_quote_multiplier":
        valid = (
            spec.quantity_unit == "contracts"
            and spec.contract_value_currency
            == spec.quote_currency
            == config.policy.notional_currency
        )
    else:
        valid = (
            spec.quantity_unit == "contracts"
            and spec.contract_value_currency
            == spec.quote_currency
            == config.policy.notional_currency
        )
    if not valid:
        raise UnsupportedCaseError("instrument units/currency cannot be safely valued")


def _notional(
    spec: InstrumentSpec, quantity: Decimal, limit: Decimal, reference: Decimal
) -> Decimal:
    if spec.product_type == "spot":
        return quantity * max(limit, reference)
    if spec.product_type in {"linear", "fx_lot"}:
        return quantity * spec.contract_value * max(limit, reference)
    return quantity * spec.contract_value


def _reference(
    config: Config,
    binding: Binding,
    symbol: str,
    limit: Decimal,
    ref: MarketReference,
    att: Attestation,
) -> None:
    if (
        ref.binding != binding
        or ref.symbol != symbol
        or not _remote(ref.source)
        or not _fresh(ref.observed_at, 30)
        or not _channel(att, ref.source_instance, ref.source_channel, "query")
    ):
        raise CertificationError("provider reference price is unbound or stale")
    if abs(limit - ref.price) / ref.price * 10000 > config.policy.max_price_deviation_bps:
        raise CertificationError("limit price exceeds configured deviation")


def _plan(
    case_id: str,
    params: dict[str, object],
    spec: InstrumentSpec | None,
    ref: MarketReference | None,
    currency: str,
) -> ActionPlan:
    ops: list[PlannedOperation] = []
    symbol = str(params["symbol"]) if "symbol" in params else None
    quantity = Decimal(str(params.get("quantity", 0)))
    price = Decimal(str(params.get("price", 0)))
    position = str(params["position_id"]) if "position_id" in params else None
    reducing = params.get("reduce_only") is True

    def add(phase: str, kind: str, *, client: str | None = None, target: str | None = None) -> None:
        ops.append(
            PlannedOperation(
                uuid4().hex,
                phase,
                kind,
                client,
                target,
                symbol,
                str(params["side"]) if kind == "submit" else None,
                quantity if kind == "submit" else Decimal(0),
                price if kind == "submit" else Decimal(0),
                "limit" if kind == "submit" else None,
                position if kind == "submit" else None,
                reducing if kind == "submit" else False,
                spec.spec_id if spec and kind == "submit" else None,
            )
        )

    if CASES[case_id].risk == Risk.READ:
        add("execute", "read")
    elif case_id in {"T03", "O03"}:
        for _ in range(int(params.get("repeat_count", 1))):
            add("execute", "cancel", target=str(params["remote_id"]))
        add("cleanup", "cancel", target=str(params["remote_id"]))
    elif case_id in {"TH04", "B01", "B02", "O01", "O02", "T01", "M05"}:
        count = (
            2
            if case_id == "TH04"
            else int(params.get("order_count", params.get("repeat_count", 1)))
        )
        for _ in range(count):
            client = f"cert-{uuid4().hex}"
            add("execute", "submit", client=client)
            add("execute", "cancel", client=client)
            add("cleanup", "cancel", client=client)
    else:
        count = int(params.get("order_count", params.get("repeat_count", 1)))
        for _ in range(count):
            client = f"cert-{uuid4().hex}"
            add("execute", "submit", client=client)
            add("cleanup", "cancel", client=client)
    submits = [o for o in ops if o.kind == "submit"]
    total = (
        sum((_notional(spec, o.quantity, o.price, ref.price) for o in submits), Decimal(0))
        if spec and ref
        else Decimal(0)
    )
    return ActionPlan(
        tuple(ops), len(submits), sum((o.quantity for o in submits), Decimal(0)), total, currency
    )


def _validate_operation(
    action: Action, planned: PlannedOperation, actual: OperationEvidence, att: Attestation
) -> None:
    if (actual.operation_id, actual.phase, actual.kind) != (
        planned.operation_id,
        planned.phase,
        planned.kind,
    ):
        raise CertificationError("operation evidence does not match immutable plan")
    if (
        actual.client_order_id,
        actual.target_order_id,
        actual.symbol,
        actual.side,
        actual.quantity,
        actual.price,
        actual.order_type,
        actual.position_id,
        actual.reduce_only,
        actual.instrument_spec_id,
    ) != (
        planned.client_order_id,
        planned.target_order_id,
        planned.symbol,
        planned.side,
        planned.quantity,
        planned.price,
        planned.order_type,
        planned.position_id,
        planned.reduce_only,
        planned.instrument_spec_id,
    ):
        raise CertificationError("operation parameters differ from authorized plan")
    if not _channel(att, actual.source_instance, actual.source_channel, "command_response"):
        raise CertificationError("operation source is not an attested command channel")
    if _utc(actual.occurred_at) > _utc(actual.observed_at) or _utc(
        actual.observed_at
    ) > datetime.now(UTC):
        raise CertificationError("operation timestamps invalid")
    if planned.kind == "read" and (
        actual.provider_order_id or actual.target_order_id or actual.quantity or actual.price
    ):
        raise CertificationError("read operation has economic effects")
    if planned.kind == "read" and not actual.accepted:
        raise CertificationError("read operation was not accepted")
    if planned.kind == "submit" and not actual.accepted and actual.provider_order_id:
        raise CertificationError("rejected submit unexpectedly created an order")
    if planned.kind == "submit" and actual.accepted and not actual.provider_order_id:
        raise CertificationError("accepted submit lacks provider order id")
    if planned.kind == "cancel" and actual.accepted and not actual.provider_order_id:
        raise CertificationError("accepted cancel lacks the provider order id it affected")


def _accepted_orders(operations: tuple[OperationEvidence, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for operation in operations:
        if operation.kind != "submit" or not operation.accepted:
            continue
        if not operation.client_order_id or not operation.provider_order_id:
            raise CertificationError("accepted submit lacks client/provider order identity")
        if operation.client_order_id in result or operation.provider_order_id in result.values():
            raise CertificationError("accepted submit order identities are not unique")
        result[operation.client_order_id] = operation.provider_order_id
    return result


def _validate_cancel_targets(
    action: Action,
    operations: tuple[OperationEvidence, ...],
    accepted_orders: dict[str, str],
) -> None:
    for operation in operations:
        if operation.kind != "cancel":
            continue
        expected = operation.target_order_id
        if expected is None and operation.client_order_id is not None:
            expected = accepted_orders.get(operation.client_order_id)
        if expected is None:
            if operation.accepted or operation.provider_order_id is not None:
                raise CertificationError("cancel acted without a resolved authorized order")
            continue
        if operation.provider_order_id != expected:
            raise CertificationError("cancel targeted an order outside the immutable plan")

    cancels = [operation for operation in operations if operation.kind == "cancel"]
    if action.case_id in {"B01", "B02", "M05", "O01", "O02", "T01", "TH04"} and (
        not cancels or any(not operation.accepted for operation in cancels)
    ):
        raise CertificationError("case requires every planned execute cancel to be accepted")
    if action.case_id == "T03" and (len(cancels) != 1 or not cancels[0].accepted):
        raise CertificationError("T03 requires one accepted cancel of the referenced order")
    if action.case_id == "O03" and not any(operation.accepted for operation in cancels):
        raise CertificationError("O03 never obtained an accepted cancel")


def _validate_operations(
    action: Action,
    actual: tuple[OperationEvidence, ...],
    phase: str,
    att: Attestation,
    dispatch: datetime,
) -> tuple[str, ...]:
    expected = {o.operation_id: o for o in action.plan.operations if o.phase == phase}
    if len(actual) != len(expected) or {o.operation_id for o in actual} != set(expected):
        raise CertificationError(f"{phase} operation evidence must map one-to-one to plan")
    request_ids = [o.provider_request_id for o in actual]
    if len(set(request_ids)) != len(request_ids):
        raise CertificationError("provider request IDs are not unique")
    for item in actual:
        _validate_operation(action, expected[item.operation_id], item, att)
        if _utc(item.occurred_at) < dispatch or _utc(item.observed_at) < dispatch:
            raise CertificationError("operation evidence predates dispatch")
    return tuple(
        o.provider_order_id
        for o in actual
        if o.kind == "submit" and o.accepted and o.provider_order_id
    )


def _validate_receipt(
    action: Action, receipt: Receipt, att: Attestation, dispatch: datetime
) -> tuple[str, ...]:
    if receipt.binding != action.binding or (
        receipt.correlation_id,
        receipt.client_id,
        receipt.action,
    ) != (action.correlation_id, action.client_id, action.name):
        raise CertificationError("receipt binding/identity mismatch")
    if (
        not receipt.accepted
        or not _remote(receipt.source)
        or not _channel(att, receipt.source_instance, receipt.source_channel, "command_response")
    ):
        raise CertificationError("receipt lacks trusted provider acceptance")
    if (
        _utc(receipt.occurred_at) < dispatch
        or not dispatch <= _utc(receipt.observed_at) <= datetime.now(UTC)
        or _utc(receipt.occurred_at) > _utc(receipt.observed_at)
    ):
        raise CertificationError("receipt outside current dispatch window")
    created = _validate_operations(action, receipt.operations, "execute", att, dispatch)
    accepted_orders = _accepted_orders(receipt.operations)
    if (
        len(set(created)) != len(created)
        or set(created) != set(receipt.created_order_ids)
        or len(created) != len(receipt.created_order_ids)
    ):
        raise CertificationError("created order IDs differ from accepted submit operations")
    if action.risk == Risk.READ and (created or any(o.kind != "read" for o in receipt.operations)):
        raise CertificationError("observe-only case performed a write")
    required_submits = {
        "B01",
        "B02",
        "M04",
        "M05",
        "O01",
        "O02",
        "T01",
        "T02",
        "TH02",
        "TH04",
        "TH06",
    }
    submits = [operation for operation in receipt.operations if operation.kind == "submit"]
    if action.case_id in required_submits and (
        len(submits) != action.plan.order_count
        or any(not operation.accepted for operation in submits)
        or len(created) != action.plan.order_count
    ):
        raise CertificationError("case requires every planned submit to create its own order")
    _validate_cancel_targets(action, receipt.operations, accepted_orders)
    return created


def _validate_reconciliation(action: Action, reconciliation: Reconciliation) -> Receipt:
    if (
        reconciliation.binding != action.binding
        or reconciliation.correlation_id != action.correlation_id
        or reconciliation.client_id != action.client_id
        or reconciliation.provider_state != "found"
        or not _remote(reconciliation.source)
        or reconciliation.receipt is None
    ):
        raise CertificationError("uncertain execute could not be reconciled")
    _utc(reconciliation.observed_at)
    return reconciliation.receipt


def _proof(action: Action, event: Observation, att: Attestation, created: tuple[str, ...]) -> bool:
    p = event.payload
    case = action.case_id
    if any(p.get(field) in (None, "", [], {}) for field in _PROOF[case]):
        return False
    for key in (
        "external_ref",
        "source_request_id",
        "operator_ref",
        "source_session_id",
        "new_session_id",
        "config_snapshot_id",
        "restoration_ref",
    ):
        if key in action.params and p.get(key) != action.params[key]:
            return False
    if case in _REJECTION and (
        p.get("rejection_category") != _REJECTION[case]
        or p.get("rejection_code") != action.params["reason_code"]
    ):
        return False
    if case in _VALIDATION and (
        p.get("validation_type") != _VALIDATION[case]
        or p.get("dispatch_absent") is not True
        or p.get("validation_rule") != action.params["rule_ref"]
    ):
        return False
    if case in _THRESHOLD:
        if (
            p.get("threshold_value") != action.params["expected_threshold"]
            or p.get("config_snapshot_id") != action.params["config_snapshot_id"]
        ):
            return False
        if case == "TH05" and p.get("window_seconds") != 60:
            return False
        if case in {"TH02", "TH04", "TH06"} and (
            p.get("baseline_count") != action.params["baseline_count"]
            or p.get("warning_count") != 1
            or p.get("observed_count", -1) < action.params["expected_threshold"]
        ):
            return False
    if case in {"C01", "M01", "L02"}:
        session = att.provider_session_id
        if action.params["source_session_id"] != session:
            return False
        if case == "C01" and not (
            p.get("authenticated") is True
            and p.get("account_id") == action.binding.account_ref
            and p.get("auth_session_id") == p.get("login_session_id") == session
        ):
            return False
        if (
            case != "C01"
            and not p.get("connection_session_id") == p.get("readiness_session_id") == session
        ):
            return False
    if (
        case in {"M02", "M03", "EM03"}
        and p.get("old_session_id", p.get("session_id")) != action.params["source_session_id"]
    ):
        return False
    if (
        case in {"M02", "M03"}
        and p.get("external_authorization_id") != action.params["authorization_ref"]
    ):
        return False
    if case == "M03" and not (
        p.get("new_session_id") == action.params["new_session_id"]
        and p.get("new_session_id") == att.provider_session_id
        and p.get("new_session_id") != p.get("old_session_id")
        and p.get("recovery_generation", 0) > p.get("disconnect_generation", 0)
        and p.get("disconnect_event_id") != p.get("recovery_event_id")
        and p.get("auth_success") is True
        and p.get("login_success") is True
        and p.get("subscription_restored") is True
    ):
        return False
    if case in {"M02", "M03"} and p.get("native_disconnect") is not True:
        return False
    if case.startswith("EM") and (
        p.get("write_guard_active") is not True
        or p.get("external_authorization_id") != action.params["authorization_ref"]
    ):
        return False
    if case == "EM01" and not (
        p.get("restriction_id") == action.params["restriction_ref"]
        and p.get("restoration_ref") == action.params["restoration_ref"]
        and p.get("restriction_restored") is True
    ):
        return False
    if case == "EM02" and (
        p.get("strategy_id") != action.params["strategy_ref"] or p.get("pause_state") != "paused"
    ):
        return False
    if case == "EM03" and (
        p.get("disconnect_state") != "disconnected"
        or p.get("release_event_id") == event.provider_event_id
    ):
        return False
    if case == "L01" and not (
        p.get("trace_id") == action.params["trace_ref"]
        and p.get("order_ref") == action.params["order_ref"]
        and p.get("trade_id") == action.params["trade_ref"]
    ):
        return False
    if case == "L03":
        normalized = p.get("normalized_record")
        if (
            p.get("trace_id") != action.params["trace_ref"]
            or not isinstance(normalized, dict)
            or normalized.get("trace_id") != p.get("trace_id")
            or normalized.get("metric") != p.get("metric")
            or re.fullmatch(r"[0-9a-fA-F]{64}", str(p.get("digest"))) is None
        ):
            return False
        canonical = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if (
            p.get("digest_algorithm") != "sha256"
            or hashlib.sha256(canonical.encode()).hexdigest() != str(p["digest"]).lower()
        ):
            return False
    if case == "L04" and (
        p.get("dispatch_absent") is not True
        or p.get("validation_rule") != action.params["rule_ref"]
    ):
        return False
    if case in {"T03", "O03"} and p.get("order_id") != action.params["remote_id"]:
        return False
    if case in {"T01", "T02", "T03"} and p.get("accepted") is not True:
        return False
    if case in {"T01", "T03"} and p.get("terminal_status") != "cancelled":
        return False
    if case == "T02" and (
        p.get("terminal_status") != "filled"
        or Decimal(str(p.get("closed_quantity", 0))) != action.plan.total_quantity
    ):
        return False
    if case == "M05" and (
        p.get("provider_order_status") != "cancelled" or p.get("cancel_count", 0) < 1
    ):
        return False
    if case == "M04" and p.get("submit_count", 0) < 1:
        return False
    if case in {"T02", "O02"} and p.get("position_id") != action.params["position_id"]:
        return False
    if case in {"B01", "B02"}:
        orders = p["orders"]
        if (
            not isinstance(orders, list)
            or len(orders) != action.plan.order_count
            or {v.get("order_id") for v in orders if isinstance(v, dict)} != set(created)
        ):
            return False
        for order in orders:
            try:
                if order["terminal_status"] != "cancelled" or Decimal(
                    str(order["requested_quantity"])
                ) != Decimal(str(order["filled_quantity"])) + Decimal(
                    str(order["remaining_quantity"])
                ):
                    return False
            except (KeyError, ValueError):
                return False
        if case == "B01":
            partial_count = sum(
                0 < Decimal(str(v["filled_quantity"])) < Decimal(str(v["requested_quantity"]))
                for v in orders
            )
            if (
                type(p.get("partial_fill_count")) is not int
                or p["partial_fill_count"] != partial_count
                or partial_count < 2
            ):
                return False
        if case == "B02" and any(Decimal(str(v["filled_quantity"])) != 0 for v in orders):
            return False
    if case in {"O01", "O02"} and (
        set(p["order_ids"]) != set(created)
        or set(p["terminal_order_ids"]) != set(created)
        or p["repetition_count"] != action.params["repeat_count"]
    ):
        return False
    return not (
        case == "O03"
        and (
            p["cancel_attempt_count"] != action.params["repeat_count"]
            or p["terminal_status"] != "cancelled"
        )
    )


def _observe(
    action: Action,
    receipt: Receipt,
    att: Attestation,
    events: list[Observation],
    created: tuple[str, ...],
    dispatch: datetime,
) -> None:
    seen_events: set[str] = set()
    covered_ops: set[str] = set()
    covered_orders: set[str] = set()
    planned_execute = {o.operation_id for o in action.plan.operations if o.phase == "execute"}
    operation_by_id = {o.operation_id: o for o in receipt.operations}
    aggregate_cases = {"B01", "B02", "O01", "O02", "TH02", "TH04", "TH06"}
    if action.case_id in {"TH02", "TH04", "TH06"} and len(events) != 1:
        raise CertificationError("threshold trigger requires exactly one aggregate warning event")
    for event in events:
        if event.binding != action.binding or (
            event.correlation_id,
            event.client_id,
            event.kind,
        ) != (action.correlation_id, action.client_id, CASES[action.case_id].event):
            raise CertificationError("observation identity mismatch")
        if (
            not _remote(event.source)
            or not _channel(att, event.source_instance, event.source_channel, "independent_event")
            or (event.source_instance, event.source_channel)
            == (receipt.source_instance, receipt.source_channel)
        ):
            raise CertificationError("event is not from an independent attested channel")
        if (
            event.evidence_window_id != action.evidence_window_id
            or event.provider_event_id in seen_events
            or _utc(event.occurred_at) > _utc(event.observed_at)
        ):
            raise CertificationError("event window/identity invalid or replayed")
        if not dispatch <= _utc(event.observed_at) <= datetime.now(UTC):
            raise CertificationError("event was not observed during this dispatch")
        if action.risk != Risk.READ and _utc(event.occurred_at) < dispatch:
            raise CertificationError("write event predates dispatch")
        if action.risk == Risk.READ:
            start, end = event.payload.get("window_start"), event.payload.get("window_end")
            if (
                not isinstance(start, str)
                or not isinstance(end, str)
                or not _utc(start) <= _utc(event.occurred_at) <= _utc(end)
            ):
                raise CertificationError("external event lacks bounded occurrence window")
        if not set(event.operation_ids) <= planned_execute or not set(
            event.provider_order_ids
        ) <= set(created) | {str(action.params.get("remote_id", ""))}:
            raise CertificationError("event references unplanned operation or order")
        mapped_orders = {
            operation_by_id[operation_id].provider_order_id
            for operation_id in event.operation_ids
            if operation_by_id[operation_id].provider_order_id is not None
        }
        if set(event.provider_order_ids) != mapped_orders:
            raise CertificationError("event operation/order identities do not correspond")
        expected_requests = {
            operation_by_id[operation_id].provider_request_id
            for operation_id in event.operation_ids
        }
        request_refs = event.payload.get("provider_request_ids")
        if (
            not isinstance(request_refs, list)
            or set(request_refs) != expected_requests
            or len(request_refs) != len(expected_requests)
        ):
            raise CertificationError("event request IDs do not match covered planned operations")
        if event.payload.get("provider_response_id") != receipt.provider_response_id:
            raise CertificationError("event provider response reference mismatch")
        if not _proof(action, event, att, created):
            raise CertificationError("case proof is missing or inconsistent")
        seen_events.add(event.provider_event_id)
        covered_ops.update(event.operation_ids)
        if len(event.provider_order_ids) > 1 and (
            action.case_id not in aggregate_cases
            or set(event.provider_order_ids) != set(created)
            or set(event.operation_ids) != planned_execute
        ):
            raise CertificationError("aggregate event lacks complete per-operation/order proof")
        covered_orders.update(event.provider_order_ids)
    if not events or covered_ops != planned_execute or not set(created) <= covered_orders:
        raise CertificationError("not every operation/order has independent event evidence")
    _cross_case_evidence(action, receipt, events, created)


def _cross_case_evidence(
    action: Action, receipt: Receipt, events: list[Observation], created: tuple[str, ...]
) -> None:
    """Relate case summaries to actual provider request/order identities, never names alone."""
    case = action.case_id
    payloads = [event.payload for event in events]
    submits = [o for o in receipt.operations if o.kind == "submit"]
    cancels = [o for o in receipt.operations if o.kind == "cancel"]
    submit_requests = {o.provider_request_id for o in submits}
    cancel_requests = {o.provider_request_id for o in cancels}
    if case in {"O01", "O02"} and any(
        set(p["request_ids"]) != submit_requests or set(p["order_ids"]) != set(created)
        for p in payloads
    ):
        raise CertificationError("repeated-order proof does not match submit requests")
    if case == "O03" and any(set(p["request_ids"]) != cancel_requests for p in payloads):
        raise CertificationError("repeated-cancel proof does not match cancel requests")
    if case in {"T01", "T03"} and any(
        p["cancel_request_id"] not in cancel_requests for p in payloads
    ):
        raise CertificationError("cancel proof lacks the planned cancel request")
    if case == "T01" and any(p["order_id"] not in created for p in payloads):
        raise CertificationError("T01 proof references a different order")
    if case == "T02" and any(p["close_order_id"] not in created for p in payloads):
        raise CertificationError("T02 proof references a different close order")
    if case in {"M04", "M05"} and any(
        p["order_id"] not in created or p["submit_count"] != len(submits) for p in payloads
    ):
        raise CertificationError("monitor proof submit/order counts mismatch")
    if case == "M05" and any(p["cancel_count"] != len(cancels) for p in payloads):
        raise CertificationError("monitor proof cancel count mismatch")
    if case in {"B01", "B02"}:
        by_order = {o.provider_order_id: o for o in submits}
        cancel_by_order = {o.provider_order_id: o for o in cancels}
        for proof in payloads:
            for order in proof["orders"]:
                order_id = order["order_id"]
                if (
                    order_id not in by_order
                    or order_id not in cancel_by_order
                    or order.get("cancel_request_id")
                    != cancel_by_order[order_id].provider_request_id
                    or Decimal(str(order["requested_quantity"])) != by_order[order_id].quantity
                ):
                    raise CertificationError("batch order quantities/cancel IDs mismatch")
    if case in {"TH02", "TH04", "TH06"}:
        increments = len(receipt.operations) if case == "TH04" else len(submits)
        expected_requests = (
            {operation.provider_request_id for operation in receipt.operations}
            if case == "TH04"
            else submit_requests
        )
        if any(
            p["observed_count"] != action.params["baseline_count"] + increments
            or not isinstance(p.get("request_ids"), list)
            or set(p["request_ids"]) != expected_requests
            or len(p["request_ids"]) != len(expected_requests)
            for p in payloads
        ):
            raise CertificationError(
                "threshold count/request IDs differ from actual planned operations"
            )


def _snapshot(action: Action, snap: StateSnapshot, att: Attestation, phase: str) -> None:
    if (
        snap.binding != action.binding
        or snap.correlation_id != action.correlation_id
        or snap.phase != phase
        or snap.scope != "account_full"
        or not snap.complete
        or not snap.pagination_complete
    ):
        raise CertificationError("snapshot scope, pagination or binding incomplete")
    if (
        not _remote(snap.source)
        or not _channel(att, snap.source_instance, snap.source_channel, "state_snapshot")
        or not _fresh(snap.observed_at, 120)
    ):
        raise CertificationError("snapshot source is not attested or fresh")
    for values, key in (
        (snap.orders, "order_id"),
        (snap.positions, "position_id"),
        (snap.balances, "currency"),
        (snap.fills, "fill_id"),
        (snap.ledger, "entry_id"),
    ):
        ids = [getattr(value, key) for value in values]
        if len(ids) != len(set(ids)):
            raise CertificationError("snapshot contains duplicate rows")
    for order in snap.orders:
        if (
            order.requested <= 0
            or order.filled < 0
            or order.remaining < 0
            or order.price < 0
            or (order.order_type == "limit" and order.price <= 0)
            or order.requested != order.filled + order.remaining
            or order.side not in {"buy", "sell"}
            or order.status
            not in {"open", "partially_filled", "cancelled", "filled", "rejected", "expired"}
        ):
            raise CertificationError("snapshot order quantity equation failed")


def _pre_execute_target(action: Action, baseline: StateSnapshot) -> None:
    """Prove externally existing targets before writing the durable intent."""
    planned_clients = {
        operation.client_order_id
        for operation in action.plan.operations
        if operation.kind == "submit" and operation.client_order_id is not None
    }
    if planned_clients & {order.client_order_id for order in baseline.orders}:
        raise CertificationError("runner client order ID already exists in baseline")
    if action.case_id in {"T02", "O02"}:
        matching = [p for p in baseline.positions if p.position_id == action.params["position_id"]]
        if baseline.snapshot_id != action.params["position_snapshot_id"] or len(matching) != 1:
            raise CertificationError("referenced pre-existing position is absent")
        position = matching[0]
        if position.symbol != action.params["symbol"] or position.quantity == 0:
            raise CertificationError("referenced position symbol/quantity mismatch")
        expected_side = "sell" if position.quantity > 0 else "buy"
        if action.params["side"] != expected_side:
            raise CertificationError("close side would not reduce the referenced signed position")
        if action.plan.total_quantity > abs(position.quantity):
            raise CertificationError("close plan exceeds pre-existing position")
        if any(o.kind == "submit" and not o.reduce_only for o in action.plan.operations):
            raise CertificationError("close plan is not reduce-only")
    if action.case_id in {"T03", "O03"}:
        matching = [o for o in baseline.orders if o.order_id == action.params["remote_id"]]
        if baseline.snapshot_id != action.params["order_snapshot_id"] or len(matching) != 1:
            raise CertificationError("referenced pre-existing order is absent")
        order = matching[0]
        if order.symbol != action.params["symbol"] or order.status not in {
            "open",
            "partially_filled",
        }:
            raise CertificationError("referenced order is not matching and open")


def _reconcile_state(
    action: Action,
    baseline: StateSnapshot,
    before: StateSnapshot,
    after: StateSnapshot,
    created: tuple[str, ...],
    spec: InstrumentSpec | None,
    receipt: Receipt | None,
    report: CleanupReport | None,
) -> None:
    if len({baseline.snapshot_id, before.snapshot_id, after.snapshot_id}) != 3 or not _utc(
        baseline.observed_at
    ) < _utc(before.observed_at) < _utc(after.observed_at):
        raise CertificationError("state snapshots are not ordered and distinct")
    start_orders = {o.order_id: o for o in baseline.orders}
    mid_orders = {o.order_id: o for o in before.orders}
    end_orders = {o.order_id: o for o in after.orders}
    touched = set(created)
    if action.case_id in {"T03", "O03"}:
        touched.add(str(action.params["remote_id"]))
        if (
            str(action.params["remote_id"]) not in start_orders
            or baseline.snapshot_id != action.params["order_snapshot_id"]
        ):
            raise CertificationError("target order is not proven by pre-existing snapshot")
        target = start_orders[str(action.params["remote_id"])]
        if target.symbol != action.params["symbol"] or target.status not in {
            "open",
            "partially_filled",
        }:
            raise CertificationError("target order is not a matching open order")
    if not touched <= set(end_orders):
        raise CertificationError("final snapshot omits touched orders")
    if (
        len(
            {baseline.control_state_digest, before.control_state_digest, after.control_state_digest}
        )
        != 1
    ):
        raise CertificationError("control/session/policy state changed during certification")
    if action.risk == Risk.READ:
        def state(s: StateSnapshot) -> tuple[object, ...]:
            return (s.orders, s.positions, s.balances, s.fills, s.ledger)

        if state(baseline) != state(before) or state(before) != state(after):
            raise CertificationError("observe-only case changed account state")
    if not set(start_orders) <= set(mid_orders) or set(mid_orders) != set(end_orders):
        raise CertificationError("order scope changed outside execute phase")
    if set(mid_orders) - set(start_orders) != set(created):
        raise CertificationError("created orders do not match execute snapshot")
    if any(mid_orders[k] != v for k, v in start_orders.items() if k not in touched):
        raise CertificationError("execute altered an unrelated order")
    if any(end_orders[k] != v for k, v in mid_orders.items() if k not in touched):
        raise CertificationError("cleanup altered an unrelated order")
    if (before.fills, before.ledger, before.positions, before.balances) != (
        after.fills,
        after.ledger,
        after.positions,
        after.balances,
    ):
        raise CertificationError("cleanup caused an economic effect beyond authorized cancels")
    accepted_cleanup = {
        o.provider_order_id for o in (report.operations if report else ()) if o.accepted
    }
    for order_id in touched:
        old = mid_orders[order_id]
        new = end_orders[order_id]
        if old != new and not (
            order_id in accepted_cleanup
            and old.status in {"open", "partially_filled"}
            and new.status == "cancelled"
            and (old.requested, old.filled, old.remaining)
            == (new.requested, new.filled, new.remaining)
        ):
            raise CertificationError(
                "cleanup changed an order without an authorized accepted cancel"
            )
    for order_id in touched:
        order = end_orders[order_id]
        if order.status not in {"cancelled", "filled", "rejected", "expired"}:
            raise CertificationError("touched order is not terminal")
        if (
            action.case_id in {"B01", "B02", "O01", "O02", "O03", "T01", "T03", "M05"}
            and order.status != "cancelled"
        ):
            raise CertificationError("case requires provider-confirmed cancellation")
        if action.case_id == "T02" and order.status != "filled":
            raise CertificationError("T02 close order is not filled")
        if order.symbol != action.params.get("symbol"):
            raise CertificationError("touched order instrument mismatch")
    if action.case_id == "B01" and sum(
        0 < end_orders[order_id].filled < end_orders[order_id].requested for order_id in created
    ) < 2:
        raise CertificationError("B01 lacks two provider-confirmed partial fills")
    if action.case_id == "B02" and any(end_orders[order_id].filled for order_id in created):
        raise CertificationError("B02 orders must all remain unfilled")
    baseline_fills = {f.fill_id: f for f in baseline.fills}
    after_fills = {f.fill_id: f for f in after.fills}
    if not set(baseline_fills) <= set(after_fills) or any(
        after_fills[k] != v for k, v in baseline_fills.items()
    ):
        raise CertificationError("fill history is not append-only")
    new_fills = [f for k, f in after_fills.items() if k not in baseline_fills]
    if any(f.order_id not in touched for f in new_fills):
        raise CertificationError("concurrent or unrelated fills prevent reconciliation")
    if receipt is not None:
        submit_by_order = {
            o.provider_order_id: o
            for o in receipt.operations
            if o.kind == "submit" and o.accepted
        }
    else:
        planned_by_client = {
            operation.client_order_id: operation
            for operation in action.plan.operations
            if operation.phase == "execute"
            and operation.kind == "submit"
            and operation.client_order_id is not None
        }
        submit_by_order = {
            order_id: planned_by_client[mid_orders[order_id].client_order_id]
            for order_id in created
            if mid_orders[order_id].client_order_id in planned_by_client
        }
    for order_id in created:
        operation = submit_by_order.get(order_id)
        order = end_orders[order_id]
        if (
            operation is None
            or order.client_order_id != operation.client_order_id
            or order.symbol != operation.symbol
            or order.side != operation.side
            or order.price != operation.price
            or order.order_type != operation.order_type
            or order.position_id != operation.position_id
            or order.reduce_only != operation.reduce_only
            or order.instrument_spec_id != operation.instrument_spec_id
            or order.requested != operation.quantity
        ):
            raise CertificationError("order state differs from accepted planned submit")
    for order_id in touched:
        previous_filled = start_orders[order_id].filled if order_id in start_orders else Decimal(0)
        if end_orders[order_id].filled - previous_filled != sum(
            (f.quantity for f in new_fills if f.order_id == order_id), Decimal(0)
        ):
            raise CertificationError("order filled quantity differs from deduplicated fills")
    for fill in new_fills:
        operation = submit_by_order.get(fill.order_id)
        if fill.order_id in created and (
            operation is None
            or fill.side != operation.side
            or fill.symbol != operation.symbol
            or (fill.side == "buy" and fill.price > operation.price)
            or (fill.side == "sell" and fill.price < operation.price)
        ):
            raise CertificationError("fill side/symbol/price differs from authorized order")
    base_ledger = {e.entry_id: e for e in baseline.ledger}
    end_ledger = {e.entry_id: e for e in after.ledger}
    if not set(base_ledger) <= set(end_ledger) or any(
        end_ledger[k] != v for k, v in base_ledger.items()
    ):
        raise CertificationError("ledger history is not append-only")
    new_entries = [e for k, e in end_ledger.items() if k not in base_ledger]
    if any(e.fill_id not in {f.fill_id for f in new_fills} for e in new_entries):
        raise CertificationError("unattributed balance movement")
    expected_by_fill: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for fill in new_fills:
        if spec is None or fill.symbol != spec.symbol or fill.fee < 0:
            raise CertificationError("fill has unsupported instrument or fee")
        amounts = expected_by_fill[fill.fill_id]
        amounts[spec.base_currency] += fill.base_delta
        amounts[spec.quote_currency] += fill.quote_delta
        amounts[spec.settlement_currency] += fill.settlement_delta
        amounts[fill.fee_currency] -= fill.fee
    actual_by_fill: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for entry in new_entries:
        assert entry.fill_id is not None
        actual_by_fill[entry.fill_id][entry.currency] += entry.delta
    if {k: {c: n for c, n in v.items() if n} for k, v in expected_by_fill.items()} != {
        k: {c: n for c, n in v.items() if n} for k, v in actual_by_fill.items()
    }:
        raise CertificationError("deduplicated fill/ledger equation failed")
    before_balances = {b.currency: b.total for b in baseline.balances}
    after_balances = {b.currency: b.total for b in after.balances}
    ledger_by_currency: dict[str, Decimal] = defaultdict(Decimal)
    for entry in new_entries:
        ledger_by_currency[entry.currency] += entry.delta
    if set(before_balances) != set(after_balances) or any(
        after_balances[c] - before_balances[c] != ledger_by_currency[c] for c in before_balances
    ):
        raise CertificationError("account balances cannot be independently reconciled")
    before_positions = {p.position_id: p.quantity for p in baseline.positions}
    after_positions = {p.position_id: p.quantity for p in after.positions}
    position_deltas: dict[str, Decimal] = defaultdict(Decimal)
    for fill in new_fills:
        if fill.position_delta and not fill.position_id:
            raise CertificationError("position-changing fill lacks position identity")
        if fill.position_id:
            position_deltas[fill.position_id] += fill.position_delta
    for position_id in set(before_positions) | set(after_positions) | set(position_deltas):
        if (
            after_positions.get(position_id, Decimal(0))
            - before_positions.get(position_id, Decimal(0))
            != position_deltas[position_id]
        ):
            raise CertificationError("position delta cannot be independently reconciled")
    if action.case_id == "O01" and new_fills:
        raise CertificationError("O01 repeated orders must cancel without fills")
    if action.case_id == "O02" and (new_fills or before_positions != after_positions):
        raise CertificationError("O02 may not reduce or otherwise change the existing position")
    if action.case_id == "T02":
        position_id = str(action.params["position_id"])
        initial = before_positions.get(position_id)
        final = after_positions.get(position_id, Decimal(0))
        expected_delta = (
            -action.plan.total_quantity
            if initial is not None and initial > 0
            else action.plan.total_quantity
        )
        if (
            initial in (None, 0)
            or baseline.snapshot_id != action.params["position_snapshot_id"]
            or position_deltas[position_id] != expected_delta
            or final != initial + expected_delta
            or (final != 0 and (final > 0) != (initial > 0))
        ):
            raise CertificationError("pre-existing position reduction not proven")


def _cleanup(
    action: Action,
    receipt: Receipt | None,
    report: CleanupReport,
    att: Attestation,
    dispatch: datetime,
    authorized_orders: dict[str, str],
    authorized_external_order_ids: tuple[str, ...],
) -> None:
    if (
        report.binding != action.binding
        or (report.correlation_id, report.client_id) != (action.correlation_id, action.client_id)
        or not _remote(report.source)
    ):
        raise CertificationError("cleanup binding/identity mismatch")
    if not dispatch <= _utc(report.observed_at) <= datetime.now(UTC):
        raise CertificationError("cleanup timestamp invalid")
    _validate_operations(action, report.operations, "cleanup", att, dispatch)
    accepted_orders = dict(authorized_orders)
    planned_clients = {
        operation.client_order_id
        for operation in action.plan.operations
        if operation.phase == "cleanup" and operation.client_order_id is not None
    }
    planned_external = {
        operation.target_order_id
        for operation in action.plan.operations
        if operation.phase == "cleanup" and operation.target_order_id is not None
    }
    if (
        set(accepted_orders) != planned_clients
        or len(set(accepted_orders.values())) != len(accepted_orders)
        or set(authorized_external_order_ids) != planned_external
        or len(set(authorized_external_order_ids)) != len(authorized_external_order_ids)
    ):
        raise CertificationError("cleanup authorization differs from immutable plan")
    for operation in report.operations:
        if operation.target_order_id is not None:
            if (
                operation.target_order_id not in authorized_external_order_ids
                or operation.provider_order_id != operation.target_order_id
            ):
                raise CertificationError("cleanup targeted an unauthorized pre-existing order")
            continue
        expected = accepted_orders.get(operation.client_order_id or "")
        if expected is None and (operation.accepted or operation.provider_order_id is not None):
            raise CertificationError("cleanup acted without a case-owned accepted submit")
        if expected is not None and operation.provider_order_id != expected:
            raise CertificationError("cleanup order ID differs from accepted submit mapping")
    if receipt is not None and {o.provider_request_id for o in receipt.operations} & {
        o.provider_request_id for o in report.operations
    }:
        raise CertificationError("cleanup reused an execute request id")
    if any(o.kind != "cancel" for o in report.operations):
        raise CertificationError("cleanup may only cancel reserved order targets")


def _narrow_cleanup_action(
    action: Action,
    authorized_orders: dict[str, str],
    authorized_external_order_ids: tuple[str, ...],
) -> Action:
    """Expose only prevalidated cancel slots and targets to the cleanup backend."""
    all_cleanup = [operation for operation in action.plan.operations if operation.phase == "cleanup"]
    planned_clients = {
        operation.client_order_id for operation in all_cleanup if operation.client_order_id
    }
    planned_external = {
        operation.target_order_id for operation in all_cleanup if operation.target_order_id
    }
    if set(authorized_orders) - planned_clients or set(
        authorized_external_order_ids
    ) - planned_external:
        raise CertificationError("cleanup allowlist is outside the immutable plan")
    operations = tuple(
        operation
        for operation in all_cleanup
        if (
            operation.client_order_id in authorized_orders
            or operation.target_order_id in authorized_external_order_ids
        )
    )
    cleanup_plan = ActionPlan(
        operations,
        0,
        Decimal(0),
        Decimal(0),
        action.plan.notional_currency,
    )
    return replace(action, plan=cleanup_plan)


def _recover_owned_orders(
    action: Action, baseline: StateSnapshot, before: StateSnapshot
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Recover runner-owned IDs and report, but do not hide, parameter mismatches.

    Ownership and conformance are deliberately separate: a new order carrying a
    unique runner-generated client ID is safe to cancel even when the provider
    created it with parameters that differ from the immutable plan.  Such a
    mismatch still makes the certification fail.
    """
    planned = {
        operation.client_order_id: operation
        for operation in action.plan.operations
        if operation.phase == "execute"
        and operation.kind == "submit"
        and operation.client_order_id is not None
    }
    baseline_clients = {order.client_order_id for order in baseline.orders}
    if set(planned) & baseline_clients:
        raise CertificationError("planned client order ID already existed in baseline")
    matches = [order for order in before.orders if order.client_order_id in planned]
    if len({order.client_order_id for order in matches}) != len(matches):
        raise CertificationError("uncertain execute client order ID is ambiguous")
    recovered: dict[str, str] = {}
    mismatched: list[str] = []
    baseline_order_ids = {order.order_id for order in baseline.orders}
    for order in matches:
        operation = planned[order.client_order_id]
        if order.order_id in baseline_order_ids:
            raise CertificationError("recovered provider order ID existed in baseline")
        recovered[order.client_order_id] = order.order_id
        if (
            order.symbol != operation.symbol
            or order.side != operation.side
            or order.price != operation.price
            or order.order_type != operation.order_type
            or order.position_id != operation.position_id
            or order.reduce_only != operation.reduce_only
            or order.instrument_spec_id != operation.instrument_spec_id
            or order.requested != operation.quantity
        ):
            mismatched.append(order.client_order_id)
    return recovered, tuple(mismatched)


def _receipt_owned_orders(
    action: Action, baseline: StateSnapshot, receipt: Receipt
) -> dict[str, str]:
    """Extract only planned, new provider IDs from an already validated receipt."""
    planned_clients = {
        operation.client_order_id
        for operation in action.plan.operations
        if operation.phase == "execute"
        and operation.kind == "submit"
        and operation.client_order_id is not None
    }
    recovered = _accepted_orders(receipt.operations)
    if set(recovered) - planned_clients or set(recovered.values()) & {
        order.order_id for order in baseline.orders
    }:
        raise CertificationError("receipt cleanup ownership is outside the immutable plan")
    return recovered


def _run_one(
    action: Action,
    backend: Backend,
    att: Attestation,
    spec: InstrumentSpec | None,
    evidence: EvidenceWriter,
) -> CaseResult:
    receipt: Receipt | None = None
    observations: list[Observation] = []
    baseline: StateSnapshot | None = None
    before: StateSnapshot | None = None
    after: StateSnapshot | None = None
    report: CleanupReport | None = None
    created: tuple[str, ...] = ()
    dispatch: datetime | None = None
    dispatch_attempted = False
    receipt_valid = False
    result = CaseResult(action.case_id, Status.FAILED, "live case incomplete")
    try:
        baseline = deepcopy(backend.snapshot(deepcopy(action), "baseline"))
        _snapshot(action, baseline, att, "baseline")
        if _utc(baseline.observed_at) < _utc(att.observed_at):
            raise CertificationError("baseline snapshot predates attestation")
        evidence.append("baseline", asdict(baseline), durable=True)
        _pre_execute_target(action, baseline)
        if (
            action.case_id in {"T02", "O02"}
            and baseline.snapshot_id != action.params["position_snapshot_id"]
        ):
            raise CertificationError("position snapshot reference mismatch")
        if (
            action.case_id in {"T03", "O03"}
            and baseline.snapshot_id != action.params["order_snapshot_id"]
        ):
            raise CertificationError("order snapshot reference mismatch")
        dispatch = datetime.now(UTC)
        evidence.append("intent", asdict(action), durable=True)
        dispatch_attempted = True
        try:
            receipt = deepcopy(backend.execute(deepcopy(action)))
        except Exception as exc:
            evidence.append(
                "execute_uncertain",
                {"case_id": action.case_id, "error_type": type(exc).__name__},
                durable=True,
            )
            try:
                reconciliation = deepcopy(
                    backend.reconcile(deepcopy(action), timeout_seconds=30)
                )
                evidence.append("reconcile", asdict(reconciliation), durable=True)
                receipt = _validate_reconciliation(action, reconciliation)
            except Exception as reconcile_exc:
                raise CertificationError(
                    "execute outcome remains uncertain after reconciliation"
                ) from reconcile_exc
        created = _validate_receipt(action, receipt, att, dispatch)
        receipt_valid = True
        evidence.append("receipt", asdict(receipt), durable=True)
        observations = deepcopy(
            backend.observe(deepcopy(action), deepcopy(receipt), timeout_seconds=30)
        )
        for event in observations:
            evidence.append("observation", asdict(event))
        _observe(action, receipt, att, observations, created, dispatch)
        result = CaseResult(
            action.case_id,
            Status.PASS,
            "provider operations and independent events verified",
            1,
            len(observations),
        )
    except UnsupportedCaseError:
        result = CaseResult(
            action.case_id,
            Status.BLOCKED,
            "v2 provider capability unsupported",
            int(receipt is not None),
            len(observations),
        )
    except Exception as exc:
        result = CaseResult(
            action.case_id,
            Status.FAILED,
            f"live evidence failed ({type(exc).__name__})",
            int(receipt is not None),
            len(observations),
        )
    finally:
        if baseline is not None and dispatch_attempted:
            cleanup_error: Exception | None = None
            before_valid = False
            cleanup_valid = False
            after_valid = False
            authorized_orders: dict[str, str] = {}
            snapshot_orders: dict[str, str] = {}
            receipt_orders: dict[str, str] = {}
            parameter_mismatches: tuple[str, ...] = ()
            authorized_external_order_ids = tuple(
                operation.target_order_id
                for operation in action.plan.operations
                if operation.phase == "cleanup" and operation.target_order_id is not None
            )
            try:
                assert dispatch is not None
                before = deepcopy(backend.snapshot(deepcopy(action), "before_cleanup"))
                _snapshot(action, before, att, "before_cleanup")
                if _utc(before.observed_at) < dispatch or (
                    observations
                    and _utc(before.observed_at)
                    < max(_utc(v.observed_at) for v in observations)
                ):
                    raise CertificationError(
                        "before-cleanup snapshot predates dispatch or observations"
                    )
                evidence.append("before_cleanup", asdict(before), durable=True)
                before_valid = True
            except Exception as exc:
                cleanup_error = exc
                evidence.append(
                    "before_cleanup_failed",
                    {"case_id": action.case_id, "error_type": type(exc).__name__},
                    durable=True,
                )
            if receipt_valid:
                assert receipt is not None
                try:
                    receipt_orders = _receipt_owned_orders(action, baseline, receipt)
                except Exception as exc:
                    cleanup_error = cleanup_error or exc
                    evidence.append(
                        "cleanup_receipt_ownership_failed",
                        {"case_id": action.case_id, "error_type": type(exc).__name__},
                        durable=True,
                    )
            if before_valid:
                assert before is not None
                try:
                    snapshot_orders, parameter_mismatches = _recover_owned_orders(
                        action, baseline, before
                    )
                except Exception as exc:
                    cleanup_error = cleanup_error or exc
                    evidence.append(
                        "cleanup_snapshot_ownership_failed",
                        {"case_id": action.case_id, "error_type": type(exc).__name__},
                        durable=True,
                    )
            # A validated receipt is a safe fallback when a complete account
            # snapshot is unavailable or lags.  A complete snapshot wins a
            # provider-ID conflict because it represents current remote state.
            authorized_orders = dict(receipt_orders)
            authorized_orders.update(snapshot_orders)
            if not receipt_valid:
                created = tuple(snapshot_orders.values())
            conflicts = tuple(
                sorted(
                    client_id
                    for client_id in set(receipt_orders) & set(snapshot_orders)
                    if receipt_orders[client_id] != snapshot_orders[client_id]
                )
            )
            missing_from_snapshot = (
                tuple(sorted(set(receipt_orders) - set(snapshot_orders)))
                if before_valid
                else ()
            )
            missing_from_receipt = (
                tuple(sorted(set(snapshot_orders) - set(receipt_orders)))
                if receipt_valid
                else ()
            )
            consistency_failed = bool(
                before_valid
                and (
                    parameter_mismatches
                    or conflicts
                    or missing_from_snapshot
                    or missing_from_receipt
                )
            )
            try:
                evidence.append(
                    "cleanup_authorization",
                    {
                        "case_id": action.case_id,
                        "receipt_valid": receipt_valid,
                        "before_snapshot_valid": before_valid,
                        "client_order_ids": list(authorized_orders),
                        "provider_order_ids": list(authorized_orders.values()),
                        "external_order_ids": list(authorized_external_order_ids),
                        "parameter_mismatches": list(parameter_mismatches),
                        "provider_id_conflicts": list(conflicts),
                        "missing_from_snapshot": list(missing_from_snapshot),
                        "missing_from_receipt": list(missing_from_receipt),
                    },
                    durable=True,
                )
            except Exception as exc:
                cleanup_error = cleanup_error or exc
            if consistency_failed:
                mismatch_error = CertificationError(
                    "snapshot ownership or order parameters differ from validated execution"
                )
                cleanup_error = cleanup_error or mismatch_error
                try:
                    evidence.append(
                        "cleanup_ownership_mismatch",
                        {
                            "case_id": action.case_id,
                            "parameter_mismatches": list(parameter_mismatches),
                            "provider_id_conflicts": list(conflicts),
                            "missing_from_snapshot": list(missing_from_snapshot),
                            "missing_from_receipt": list(missing_from_receipt),
                        },
                        durable=True,
                    )
                except Exception as exc:
                    cleanup_error = cleanup_error or exc
            cleanup_dispatch = datetime.now(UTC)
            validated_receipt = receipt if receipt_valid else None
            try:
                cleanup_action = _narrow_cleanup_action(
                    action,
                    authorized_orders,
                    authorized_external_order_ids,
                )
                report = deepcopy(
                    backend.cleanup(
                        deepcopy(cleanup_action),
                        deepcopy(authorized_orders),
                        deepcopy(authorized_external_order_ids),
                    )
                )
                evidence.append("cleanup", asdict(report), durable=True)
                _cleanup(
                    cleanup_action,
                    validated_receipt,
                    report,
                    att,
                    cleanup_dispatch,
                    authorized_orders,
                    authorized_external_order_ids,
                )
                cleanup_valid = True
            except Exception as exc:
                cleanup_error = cleanup_error or exc
                evidence.append(
                    "cleanup_failed",
                    {"case_id": action.case_id, "error_type": type(exc).__name__},
                    durable=True,
                )
            try:
                after = deepcopy(backend.snapshot(deepcopy(action), "after_cleanup"))
                _snapshot(action, after, att, "after_cleanup")
                if report is not None and _utc(after.observed_at) < _utc(report.observed_at):
                    raise CertificationError("after-cleanup snapshot predates cleanup report")
                evidence.append("after_cleanup", asdict(after), durable=True)
                after_valid = True
            except Exception as exc:
                cleanup_error = cleanup_error or exc
                evidence.append(
                    "after_cleanup_failed",
                    {"case_id": action.case_id, "error_type": type(exc).__name__},
                    durable=True,
                )
            if before_valid and cleanup_valid and after_valid:
                assert before is not None and after is not None and report is not None
                try:
                    _reconcile_state(
                        action,
                        baseline,
                        before,
                        after,
                        created,
                        spec,
                        validated_receipt,
                        report,
                    )
                except Exception as exc:
                    cleanup_error = cleanup_error or exc
                    evidence.append(
                        "state_reconciliation_failed",
                        {"case_id": action.case_id, "error_type": type(exc).__name__},
                        durable=True,
                    )
            if cleanup_error is not None:
                result = CaseResult(
                    action.case_id,
                    Status.FAILED,
                    f"cleanup or state reconciliation failed ({type(cleanup_error).__name__})",
                    int(receipt is not None),
                    len(observations),
                )
    return result


def run_live(
    config: Config, selected: list[str], grants: Grants, evidence_dir: str | Path
) -> tuple[list[CaseResult], Path]:
    """Authorize before credentials/factory; then run only provider-backed cases."""
    if not selected or len(set(selected)) != len(selected) or set(selected) - set(CASES):
        raise CertificationError("case selection must contain unique known IDs")
    # The entire selected enabled write set is authorized before the first secret
    # lookup, backend import, factory invocation, or bridge connection.
    for case_id in selected:
        item = config.cases.get(case_id)
        if item is not None and item.enabled:
            _authorize(config, grants, CASES[case_id].risk, config.environment)
    run_id = f"{config.venue}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:10]}"
    secrets = tuple(
        filter(
            None,
            (
                *(os.environ.get(name, "") for name in config.credentials.values()),
                os.environ.get(config.backend.token_env or "", ""),
                os.environ.get(config.backend.endpoint_env or "", ""),
            ),
        )
    )
    evidence = EvidenceWriter(Path(evidence_dir), run_id, secrets)
    results: list[CaseResult] = []
    backend: Backend | None = None
    att: Attestation | None = None
    binding: Binding | None = None
    blocked_reason = "v2 live attestation unavailable"
    used_actions = 0
    used_notional = Decimal(0)
    used_quantity: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    stop_writes = False
    try:
        evidence.append(
            "run_start",
            {
                "venue": config.venue,
                "environment": asdict(config.environment),
                "case_ids": selected,
            },
        )
        if any((item := config.cases.get(c)) is not None and item.enabled for c in selected):
            try:
                backend = create_backend(config)
                expected_account = os.environ.get(config.credentials["account"], "")
                if not expected_account:
                    raise CertificationError("account environment variable is empty")
                att = backend.attest()
                binding = _attest(config, expected_account, att)
                evidence.append("attestation", asdict(att), durable=True)
                for case_id in selected:
                    item = config.cases.get(case_id)
                    if item is not None and item.enabled:
                        _authorize(
                            config,
                            grants,
                            CASES[case_id].risk,
                            Environment(binding.environment_name, binding.environment_kind),
                        )
            except Exception as exc:
                blocked_reason = f"v2 live attestation failed ({type(exc).__name__})"
                binding = None
                evidence.append("attestation_failed", {"error_type": type(exc).__name__})
        for case_id in selected:
            item = config.cases.get(case_id)
            risk = CASES[case_id].risk
            if item is None or not item.enabled:
                result = CaseResult(case_id, Status.BLOCKED, "case not configured or disabled")
            elif backend is None or binding is None or att is None:
                result = CaseResult(case_id, Status.BLOCKED, blocked_reason)
            elif stop_writes and risk != Risk.READ:
                result = CaseResult(
                    case_id,
                    Status.BLOCKED,
                    "prior write outcome or cleanup uncertain; later writes stopped",
                )
            else:
                try:
                    params = item.params
                    spec: InstrumentSpec | None = None
                    ref: MarketReference | None = None
                    if risk != Risk.READ and "quantity" in params:
                        symbol = str(params["symbol"])
                        spec = backend.instrument_spec(symbol)
                        _instrument(config, binding, spec, symbol, att)
                        evidence.append("instrument_spec", asdict(spec))
                        price = Decimal(str(params["price"]))
                        quantity = Decimal(str(params["quantity"]))
                        if price % spec.price_tick or quantity % spec.quantity_step:
                            raise CertificationError(
                                "order price/quantity violate provider tick/step"
                            )
                        ref = backend.reference_price(symbol)
                        _reference(config, binding, symbol, price, ref, att)
                        evidence.append("reference_price", asdict(ref))
                    plan = _plan(case_id, params, spec, ref, config.policy.notional_currency)
                    if (
                        len(plan.operations) > config.policy.max_actions
                        or used_actions + len(plan.operations) > config.policy.max_total_actions
                    ):
                        raise CertificationError("planned operations exceed action caps")
                    if (
                        plan.total_notional > config.policy.max_notional
                        or used_notional + plan.total_notional > config.policy.max_total_notional
                    ):
                        raise CertificationError("planned notional exceeds policy currency cap")
                    if spec is not None:
                        key = (spec.symbol, spec.quantity_unit)
                        if (
                            plan.total_quantity > config.policy.max_quantity
                            or used_quantity[key] + plan.total_quantity
                            > config.policy.max_total_quantity
                        ):
                            raise CertificationError("planned symbol/unit quantity exceeds cap")
                    action = Action(
                        case_id,
                        CASES[case_id].action,
                        risk,
                        binding,
                        deepcopy(params),
                        uuid4().hex,
                        f"cert-{uuid4().hex}",
                        att.provider_session_id,
                        str(params.get("evidence_window_id", uuid4().hex)),
                        plan,
                    )
                    used_actions += len(plan.operations)
                    used_notional += plan.total_notional
                    if spec is not None:
                        used_quantity[(spec.symbol, spec.quantity_unit)] += plan.total_quantity
                    result = _run_one(action, backend, att, spec, evidence)
                    if risk != Risk.READ and result.status != Status.PASS:
                        stop_writes = True
                except UnsupportedCaseError:
                    result = CaseResult(
                        case_id, Status.BLOCKED, "v2 provider capability unsupported"
                    )
                except CertificationError as exc:
                    result = CaseResult(
                        case_id, Status.BLOCKED, f"preflight blocked ({type(exc).__name__})"
                    )
                except Exception as exc:
                    result = CaseResult(
                        case_id, Status.FAILED, f"preflight failed ({type(exc).__name__})"
                    )
                    if risk != Risk.READ:
                        stop_writes = True
            results.append(result)
    finally:
        if backend is not None:
            try:
                backend.close()
                evidence.append("backend_close", {"completed": True})
            except Exception as exc:
                evidence.append(
                    "backend_close", {"completed": False, "error_type": type(exc).__name__}
                )
                results = [
                    CaseResult(
                        r.case_id,
                        Status.FAILED,
                        "backend close failed",
                        r.receipt_count,
                        r.observation_count,
                    )
                    if r.status == Status.PASS
                    else r
                    for r in results
                ]
        for result in results:
            evidence.append("case_result", asdict(result), durable=True)
        summary = {
            "venue": config.venue,
            "environment": asdict(config.environment),
            "results": [asdict(r) for r in results],
            "counts": {s.value: sum(r.status == s for r in results) for s in Status},
            "planned_budget_used": {
                "actions": used_actions,
                "notional": str(used_notional),
                "notional_currency": config.policy.notional_currency,
                "quantity_by_symbol_unit": {
                    f"{symbol}/{unit}": str(value)
                    for (symbol, unit), value in used_quantity.items()
                },
            },
        }
        try:
            evidence.finish(summary)
        finally:
            evidence.close()
    return results, evidence.summary_path
