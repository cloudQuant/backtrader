"""Backtrader-specific facts for the provider-neutral service recovery port.

The SDK owns recovery persistence and dispatch coordination. This module owns
only the framework facts that must bind a managed order and a later paper fill
to the Backtrader feed, decision bar and commission configuration. It accepts
and returns detached mappings; no Backtrader object crosses the SDK boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


class ServiceRecoveryAttestationError(RuntimeError):
    """Finite validation error for a Backtrader recovery fact mapping."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AttestedServiceRecoveryExecutionContext:
    """Neutral attestation result for immutable submit-time framework facts."""

    facts: Mapping[str, Any]


@dataclass(frozen=True)
class AttestedServiceRecoveryEventContext:
    """Neutral attestation result for a fill bound to its submit-time facts."""

    facts: Mapping[str, Any]
    data_name: str
    instrument: str
    commission_currency: str


class BacktraderServiceRecoveryAttestor:
    """Validate Backtrader-shaped context through a provider-neutral port.

    The object is stateless and safe to register once in an SDK facade. Feed,
    Broker and Order inspection stays in ``BtApiBroker``; this class validates
    only the resulting mapping and its cross-field bindings.
    """

    def attest_intent_context(
        self,
        raw: Mapping[str, Any],
        submit_payload: Mapping[str, Any],
    ) -> AttestedServiceRecoveryExecutionContext:
        if not isinstance(raw, Mapping) or frozenset(raw) != {
            "feed",
            "decision",
            "comminfo",
            "quote_binding",
        }:
            raise ServiceRecoveryAttestationError("INVALID_INTENT_RECOVERY_CONTEXT")
        feed = raw["feed"]
        decision = raw["decision"]
        comminfo = raw["comminfo"]
        quote_binding = raw["quote_binding"]
        if not isinstance(feed, Mapping) or frozenset(feed) != {
            "data_name",
            "instrument",
            "feed_class",
            "feed_name",
            "dataname",
            "timeframe",
            "compression",
            "timezone",
        }:
            raise ServiceRecoveryAttestationError("INVALID_INTENT_RECOVERY_CONTEXT")
        if (
            not _identifier(feed["data_name"])
            or feed["instrument"] != submit_payload["instrument"]
            or not _identifier(feed["instrument"])
            or not _identifier(feed["feed_class"])
            or not _identifier(feed["feed_name"])
            or (feed["dataname"] is not None and not _identifier(feed["dataname"]))
            or type(feed["timeframe"]) is not int
            or feed["timeframe"] < 0
            or type(feed["compression"]) is not int
            or feed["compression"] < 0
            or (feed["timezone"] is not None and not _identifier(feed["timezone"]))
        ):
            raise ServiceRecoveryAttestationError("INVALID_INTENT_RECOVERY_CONTEXT")
        if not isinstance(decision, Mapping) or frozenset(decision) != {
            "bar_index",
            "datetime_hex",
        }:
            raise ServiceRecoveryAttestationError("INVALID_INTENT_RECOVERY_CONTEXT")
        if (
            type(decision["bar_index"]) is not int
            or decision["bar_index"] < 1
            or not _hex_float(decision["datetime_hex"])
        ):
            raise ServiceRecoveryAttestationError("INVALID_INTENT_RECOVERY_CONTEXT")
        if not isinstance(comminfo, Mapping) or frozenset(comminfo) != {
            "class_module",
            "class_name",
            "params",
        }:
            raise ServiceRecoveryAttestationError("INVALID_INTENT_RECOVERY_CONTEXT")
        params = comminfo["params"]
        if (
            not _identifier(comminfo["class_module"])
            or not _identifier(comminfo["class_name"])
            or not isinstance(params, Mapping)
            or frozenset(params)
            != {
                "commission",
                "mult",
                "margin",
                "commtype",
                "stocklike",
                "percabs",
                "interest",
                "interest_long",
                "leverage",
                "automargin",
            }
            or any(type(value) not in (str, bool, int, type(None)) for value in params.values())
        ):
            raise ServiceRecoveryAttestationError("INVALID_INTENT_RECOVERY_CONTEXT")
        if not isinstance(quote_binding, Mapping) or frozenset(quote_binding) != {
            "source_ref",
            "generation",
            "cursor",
            "instrument",
            "as_of_ns",
            "data_name",
            "bar_index",
            "datetime_hex",
        }:
            raise ServiceRecoveryAttestationError("INVALID_INTENT_RECOVERY_CONTEXT")
        if (
            not _identifier(quote_binding["source_ref"])
            or not _identifier(quote_binding["generation"])
            or type(quote_binding["cursor"]) is not int
            or quote_binding["cursor"] < 0
            or not _identifier(quote_binding["instrument"])
            or type(quote_binding["as_of_ns"]) is not int
            or quote_binding["as_of_ns"] <= 0
            or type(quote_binding["bar_index"]) is not int
            or quote_binding["bar_index"] < 1
            or not _hex_float(quote_binding["datetime_hex"])
            or quote_binding["data_name"] != feed["data_name"]
            or quote_binding["instrument"] != feed["instrument"]
            or quote_binding["data_name"] != decision.get("data_name", feed["data_name"])
            or quote_binding["bar_index"] != decision["bar_index"]
            or quote_binding["datetime_hex"] != decision["datetime_hex"]
        ):
            raise ServiceRecoveryAttestationError("INVALID_INTENT_RECOVERY_CONTEXT")
        return AttestedServiceRecoveryExecutionContext(facts=_json_mapping(raw))

    def attest_event_context(
        self,
        raw: Mapping[str, Any],
        manifest: Mapping[str, Any],
        execution_context: Mapping[str, Any],
        paper_fill: Mapping[str, Any],
    ) -> AttestedServiceRecoveryEventContext:
        """Bind the fill mapping to the journaled manifest and original bar."""

        required = {
            "data_name",
            "instrument",
            "bar_index",
            "datetime_hex",
            "comminfo",
            "commission_currency",
            "quote_source_ref",
            "quote_generation",
            "quote_cursor",
            "quote_instrument",
            "quote_as_of_ns",
        }
        if not isinstance(raw, Mapping) or frozenset(raw) != required:
            raise ServiceRecoveryAttestationError("INVALID_RECOVERY_EVENT_CONTEXT")
        if not all(isinstance(value, Mapping) for value in (manifest, execution_context, paper_fill)):
            raise ServiceRecoveryAttestationError("RECOVERY_EVENT_CONTEXT_MISMATCH")
        context = _json_mapping(raw, invalid_code="INVALID_RECOVERY_EVENT_CONTEXT")
        submit = manifest.get("submit_payload")
        binding = manifest.get("recovery_binding")
        feed = execution_context.get("feed")
        decision = execution_context.get("decision")
        comminfo = execution_context.get("comminfo")
        quote_binding = execution_context.get("quote_binding")
        if (
            not isinstance(submit, Mapping)
            or not isinstance(binding, Mapping)
            or not isinstance(feed, Mapping)
            or not isinstance(decision, Mapping)
            or not isinstance(comminfo, Mapping)
            or not isinstance(quote_binding, Mapping)
            or not _identifier(context["data_name"])
            or not _identifier(context["instrument"])
            or type(context["bar_index"]) is not int
            or context["bar_index"] < 1
            or not _hex_float(context["datetime_hex"])
            or not isinstance(context["comminfo"], Mapping)
            or context["commission_currency"] != paper_fill["commission_currency"]
            or not _identifier(context["commission_currency"])
            or not _identifier(context["quote_source_ref"])
            or not _identifier(context["quote_generation"])
            or type(context["quote_cursor"]) is not int
            or context["quote_cursor"] < 0
            or not _identifier(context["quote_instrument"])
            or type(context["quote_as_of_ns"]) is not int
            or context["quote_as_of_ns"] <= 0
            or context["data_name"] != binding.get("data_name")
            or context["data_name"] != feed.get("data_name")
            or context["instrument"] != submit.get("instrument")
            or context["instrument"] != feed.get("instrument")
            or context["instrument"] != context["quote_instrument"]
            or context["bar_index"] != decision.get("bar_index")
            or context["datetime_hex"] != decision.get("datetime_hex")
            or context["comminfo"] != comminfo
            or context["quote_source_ref"] != paper_fill.get("quote_source_ref")
            or context["quote_generation"] != paper_fill.get("quote_generation")
            or context["quote_cursor"] != paper_fill.get("quote_cursor")
            or context["quote_instrument"] != paper_fill.get("quote_instrument")
            or context["quote_source_ref"] != quote_binding.get("source_ref")
            or context["quote_generation"] != quote_binding.get("generation")
            or context["quote_cursor"] != quote_binding.get("cursor")
            or context["quote_instrument"] != quote_binding.get("instrument")
            or context["quote_as_of_ns"] != quote_binding.get("as_of_ns")
            or context["quote_as_of_ns"] > paper_fill.get("match_time_ns", 0)
            or quote_binding.get("data_name") != context["data_name"]
            or quote_binding.get("bar_index") != context["bar_index"]
            or quote_binding.get("datetime_hex") != context["datetime_hex"]
        ):
            raise ServiceRecoveryAttestationError("RECOVERY_EVENT_CONTEXT_MISMATCH")
        return AttestedServiceRecoveryEventContext(
            facts=context,
            data_name=context["data_name"],
            instrument=context["instrument"],
            commission_currency=context["commission_currency"],
        )


def _json_mapping(
    value: Mapping[str, Any], *, invalid_code: str = "INVALID_INTENT_RECOVERY_CONTEXT"
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ServiceRecoveryAttestationError(invalid_code)
    return {key: _json_value(item, invalid_code=invalid_code) for key, item in value.items()}


def _json_value(value: Any, *, invalid_code: str) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        raise ServiceRecoveryAttestationError(invalid_code)
    if isinstance(value, Mapping):
        return _json_mapping(value, invalid_code=invalid_code)
    if type(value) in (list, tuple):
        return [_json_value(item, invalid_code=invalid_code) for item in value]
    raise ServiceRecoveryAttestationError(invalid_code)


def _identifier(value: Any) -> bool:
    return bool(
        type(value) is str
        and 1 <= len(value) <= 192
        and value == value.strip()
        and all(character.isascii() and character.isprintable() for character in value)
    )


def _hex_float(value: Any) -> bool:
    if type(value) is not str or not value or len(value) > 128:
        return False
    try:
        number = float.fromhex(value)
    except (ValueError, OverflowError):
        return False
    return number > 0.0 and number < float("inf")


SERVICE_RECOVERY_ATTESTOR = BacktraderServiceRecoveryAttestor()


__all__ = [
    "AttestedServiceRecoveryEventContext",
    "AttestedServiceRecoveryExecutionContext",
    "BacktraderServiceRecoveryAttestor",
    "SERVICE_RECOVERY_ATTESTOR",
    "ServiceRecoveryAttestationError",
]
