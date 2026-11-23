"""Single explicit composition root for Backtrader live Direct and Gateway modes.

Implements the frozen contracts of Iteration 62 Split (D62S-01 through D62S-09):
- Explicit immutable ``mode`` (``direct`` | ``gateway``) evaluated before any
  network I/O or external client construction (R62S-01, R62S-02).
- Strictly separated Direct and Gateway rejection key matrices without false
  positives on legitimate Gateway ``direct.*`` / ``*.direct_write`` protocol names.
- Immutable ``LiveRunBinding`` with an unforgeable per-composition token shared
  across Store, Feed, and Broker to forbid cross-mode / cross-account mixing.
- ``GatewayReadinessProof`` neutral validation contract for five-component
  deployment readiness without opening Monitor or Runtime RPC ports in strategy
  processes (D62S-02, D62S-03, D62S-04, D62S-05).
- ``ProcessModeFence`` enforcing single-process single-mode isolation (D62S-09a).

This module deliberately maintains zero direct imports of optional SDK service
packages (``bt_api_gateway``, ``bt_api_risk``, ``bt_api_execution``,
``bt_api_monitor``, ``bt_api_runtime``, ``bt_api_transport_zmq``).
"""

from __future__ import annotations

import math
import re
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, Optional, Tuple

from ._btapi_errors import LegacyGatewayMigrationRequiredError, LiveCompositionError

__all__ = [
    "DIRECT_FORBIDDEN_GATEWAY_KEYS",
    "DIRECT_FORBIDDEN_HYBRID_ROUTING_KEYS",
    "DIRECT_FORBIDDEN_LEGACY_EXECUTION_KEYS",
    "DIRECT_FORBIDDEN_SERVICE_PASSTHROUGH_KEYS",
    "FORBIDDEN_DIRECT_SUBPACKAGES",
    "FORBIDDEN_GATEWAY_PROVIDER_MODULES",
    "GATEWAY_FORBIDDEN_DIRECT_KEYS",
    "GATEWAY_FORBIDDEN_HYBRID_KEYS",
    "LIVE_MODES",
    "SUPPORTED_GATEWAY_EXCHANGE_PREFIXES",
    "GatewayReadinessProof",
    "LiveRunBinding",
    "ProcessModeFence",
    "create_direct_store",
    "create_gateway_store",
    "create_live_store",
    "detect_forbidden_live_modules",
    "parse_gateway_readiness_proof",
    "validate_gateway_readiness_proof",
    "validate_live_config",
    "verify_run_binding",
]

LIVE_MODES: FrozenSet[str] = frozenset({"direct", "gateway"})
POSITION_MODES: FrozenSet[str] = frozenset({"net", "dual_side"})
SUPPORTED_GATEWAY_EXCHANGE_PREFIXES: Tuple[str, ...] = ("CTP___",)

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CALENDAR_FIELDS: Tuple[str, ...] = ("route", "venue", "kind", "product", "contract")
_VALID_QUANTITY_UNITS: FrozenSet[str] = frozenset({"base", "contracts", "lots", "native"})
_VALID_TIF_GATEWAY: FrozenSet[str] = frozenset({"GFD", "DAY", "GTC", "IOC", "FOK"})
_VALID_FEED_TIMEFRAMES: FrozenSet[str] = frozenset({"ticks", "seconds", "minutes", "days"})
_VALID_LOG_LEVELS: FrozenSet[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_VALID_COMPONENT_STATES: FrozenSet[str] = frozenset(
    {"READY", "DEGRADED", "UNAVAILABLE", "UNREACHABLE", "AUTH_FAILED", "INCOMPATIBLE"}
)

# Direct mode forbidden key families (contracts/config_schema_v1.md)
DIRECT_FORBIDDEN_GATEWAY_KEYS: FrozenSet[str] = frozenset(
    {
        "gateway",
        "gateway_strategy",
        "gateway_resource_provider",
        "gateway_resource_files",
        "gateway_host",
        "gateway_security_profiles",
        "gateway_run_lock",
        "gateway_readiness_proof",
    }
)
DIRECT_FORBIDDEN_HYBRID_ROUTING_KEYS: FrozenSet[str] = frozenset(
    {
        "service_client_config",
        "gateway_client_config",
        "execution_parent_port",
        "execution_order_routing",
    }
)
DIRECT_FORBIDDEN_SERVICE_PASSTHROUGH_KEYS: FrozenSet[str] = frozenset(
    {
        "market_runtime_factory",
        "forwarding_config",
        "transport_mode",
    }
)
# Mirrors bt_api_py.direct_api_assembly.DIRECT_EXECUTION_CONFIG_KEYS minus market_data_only,
# plus legacy managed execution / journal keys retired by D65-11 / D62S-07.
DIRECT_FORBIDDEN_LEGACY_EXECUTION_KEYS: FrozenSet[str] = frozenset(
    {
        "execution_config",
        "managed_execution_adapter",
        "execution_authorization",
        "settlement_authorization",
        "order_journal",
        "require_order_journal",
        "order_poll_interval",
        "account_currency",
        "account_currencies",
        "account_ids",
        "required_environments",
        "strategy_id",
        "strategy_identity_sha256",
        "account_maximum_loss_bps",
        "account_risk_max_age_seconds",
        "event_batch_handoff",
    }
)

# Gateway mode forbidden key families (contracts/config_schema_v1.md)
GATEWAY_FORBIDDEN_DIRECT_KEYS: FrozenSet[str] = frozenset(
    {
        "exchange_kwargs",
        "write_admission",
        "direct",
        "ctp",
        "api",
        "api_cls",
        "api_kwargs",
        "market_clock_verification",
        "waiting_orders",
        "direct_facts_timeout",
        "direct_funds_refresh_interval",
        "direct_position_audit_interval",
    }
)
GATEWAY_FORBIDDEN_HYBRID_KEYS: FrozenSet[str] = frozenset(
    {
        "gateway",
        "service_client_config",
        "gateway_client_config",
        "execution_parent_port",
        "execution_order_routing",
        "market_runtime_factory",
        "forwarding_config",
        "transport_mode",
        "managed_execution_adapter",
        "execution_authorization",
        "settlement_authorization",
        "execution_config",
        "event_batch_handoff",
    }
)

# Module isolation probes (S-02 / S-03)
FORBIDDEN_DIRECT_SUBPACKAGES: Tuple[str, ...] = (
    "bt_api_gateway",
    "bt_api_risk",
    "bt_api_execution",
    "bt_api_monitor",
    "bt_api_runtime",
    "bt_api_transport_zmq",
)
FORBIDDEN_GATEWAY_PROVIDER_MODULES: Tuple[str, ...] = (
    "bt_api_ctp.direct_write_provider",
    "bt_api_ctp.ctp_trader_api",
    "bt_api_okx.direct_write_provider",
    "bt_api_binance.direct_write_provider",
)


def _snapshot_mapping(value: Any, *, depth: int = 0) -> Any:
    """Materialize an immutable plain-dict/list snapshot to prevent lazy Mapping TOCTOU."""
    if depth > 12:
        raise LiveCompositionError("MODE_CONFLICT", detail="configuration_nesting_exceeded")
    if isinstance(value, Mapping):
        return {k: _snapshot_mapping(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_snapshot_mapping(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_snapshot_mapping(item, depth=depth + 1) for item in value)
    return value


def _is_nonempty_trimmed_str(value: Any) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


@dataclass(frozen=True)
class LiveRunBinding:
    """Immutable runtime identity binding shared across Store, Feed, and Broker."""

    mode: str
    position_mode: str = "net"
    market_data_only: bool = False
    account_scope: Optional[str] = None
    strategy_scope: Optional[str] = None
    route: Optional[str] = None
    session_generation: int = 1
    binding_token: object = field(default_factory=object, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.mode) is not str or self.mode not in LIVE_MODES:
            raise LiveCompositionError("MODE_INVALID", detail="binding_mode")
        if type(self.position_mode) is not str or self.position_mode not in POSITION_MODES:
            raise LiveCompositionError("MODE_CONFLICT", detail="position_mode_invalid")
        if type(self.market_data_only) is not bool:
            raise LiveCompositionError("MODE_CONFLICT", detail="market_data_only_not_bool")
        if type(self.session_generation) is not int or self.session_generation < 1:
            raise LiveCompositionError("MODE_CONFLICT", detail="session_generation_invalid")

    def matches(self, other: Any) -> bool:
        """Return True iff *other* is the exact same composition-root run binding."""
        if not isinstance(other, LiveRunBinding):
            return False
        return (
            self.binding_token is other.binding_token
            and self.mode == other.mode
            and self.position_mode == other.position_mode
            and self.market_data_only == other.market_data_only
            and self.account_scope == other.account_scope
            and self.strategy_scope == other.strategy_scope
            and self.route == other.route
            and self.session_generation == other.session_generation
        )


def verify_run_binding(expected: LiveRunBinding, actual: Any) -> None:
    """Fail closed if an attached Store/Feed/Broker binding differs from *expected*."""
    if not isinstance(expected, LiveRunBinding) or not expected.matches(actual):
        raise LiveCompositionError("RUN_BINDING_MISMATCH")


@dataclass(frozen=True)
class GatewayReadinessProof:
    """Neutral Gateway-issued five-component readiness snapshot (contracts/readiness_and_auth_proof_v1.md)."""

    schema_version: int
    proof_generation: int
    issued_at_ns: int
    expires_at_ns: int
    gateway_service_id: str
    gateway_instance_id: str
    gateway_scope_ref: str
    account_scope: str
    strategy_scope: str
    route: str
    strategy_principal_has_submit: bool
    strategy_principal_has_reserve: bool
    delegated_cancel_enabled: bool
    risk_required: bool
    risk_service_ref: str
    risk_protocol_version: str
    risk_state: str
    execution_required: bool
    execution_service_ref: str
    execution_protocol_version: str
    execution_state: str
    execution_direct_path_disabled: bool
    monitor_required: bool
    monitor_service_ref: str
    monitor_protocol_version: str
    last_acked_heartbeat_age_ms: Optional[int]
    monitor_stop_new_active: bool
    runtime_supervision_expected: bool
    runtime_service_ref: str
    registered_run_id: Optional[str]


def parse_gateway_readiness_proof(raw: Any) -> GatewayReadinessProof:
    """Convert a mapping or existing GatewayReadinessProof into a validated DTO."""
    if isinstance(raw, GatewayReadinessProof):
        return raw
    if not isinstance(raw, Mapping):
        raise LiveCompositionError(
            "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="proof_not_mapping"
        )
    try:
        return GatewayReadinessProof(
            schema_version=raw["schema_version"],
            proof_generation=raw["proof_generation"],
            issued_at_ns=raw["issued_at_ns"],
            expires_at_ns=raw["expires_at_ns"],
            gateway_service_id=raw["gateway_service_id"],
            gateway_instance_id=raw["gateway_instance_id"],
            gateway_scope_ref=raw["gateway_scope_ref"],
            account_scope=raw["account_scope"],
            strategy_scope=raw["strategy_scope"],
            route=raw["route"],
            strategy_principal_has_submit=raw["strategy_principal_has_submit"],
            strategy_principal_has_reserve=raw["strategy_principal_has_reserve"],
            delegated_cancel_enabled=raw["delegated_cancel_enabled"],
            risk_required=raw["risk_required"],
            risk_service_ref=raw["risk_service_ref"],
            risk_protocol_version=raw["risk_protocol_version"],
            risk_state=raw["risk_state"],
            execution_required=raw["execution_required"],
            execution_service_ref=raw["execution_service_ref"],
            execution_protocol_version=raw["execution_protocol_version"],
            execution_state=raw["execution_state"],
            execution_direct_path_disabled=raw["execution_direct_path_disabled"],
            monitor_required=raw["monitor_required"],
            monitor_service_ref=raw["monitor_service_ref"],
            monitor_protocol_version=raw["monitor_protocol_version"],
            last_acked_heartbeat_age_ms=raw.get("last_acked_heartbeat_age_ms"),
            monitor_stop_new_active=raw["monitor_stop_new_active"],
            runtime_supervision_expected=raw["runtime_supervision_expected"],
            runtime_service_ref=raw["runtime_service_ref"],
            registered_run_id=raw.get("registered_run_id"),
        )
    except KeyError as exc:
        raise LiveCompositionError(
            "GATEWAY_READINESS_COMPONENT_NOT_READY",
            detail=f"missing_{exc.args[0]}",
        ) from None


def validate_gateway_readiness_proof(
    proof: Any,
    *,
    expected_binding: Optional[LiveRunBinding] = None,
    expected_run_id: Optional[str] = None,
    now_ns: Optional[int] = None,
    require_ready_for_write: bool = True,
) -> GatewayReadinessProof:
    """Validate a GatewayReadinessProof with finite error classification (R62S-05, R62S-06).

    Distinguishes unreachable, authentication failure, confirmed version
    incompatibility, principal bypass unsafety, and component not-ready states.
    """
    parsed = parse_gateway_readiness_proof(proof)
    if type(parsed.schema_version) is not int or parsed.schema_version != 1:
        raise LiveCompositionError(
            "GATEWAY_READINESS_VERSION_INCOMPATIBLE", detail="proof_schema_version"
        )
    if (
        type(parsed.proof_generation) is not int
        or parsed.proof_generation < 1
        or type(parsed.issued_at_ns) is not int
        or parsed.issued_at_ns <= 0
        or type(parsed.expires_at_ns) is not int
        or parsed.expires_at_ns <= parsed.issued_at_ns
    ):
        raise LiveCompositionError(
            "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="proof_timestamps_invalid"
        )
    current_ns = time.time_ns() if now_ns is None else now_ns
    if current_ns >= parsed.expires_at_ns:
        raise LiveCompositionError("GATEWAY_READINESS_UNREACHABLE", detail="proof_expired")

    text_fields = (
        ("gateway_service_id", parsed.gateway_service_id),
        ("gateway_instance_id", parsed.gateway_instance_id),
        ("gateway_scope_ref", parsed.gateway_scope_ref),
        ("account_scope", parsed.account_scope),
        ("strategy_scope", parsed.strategy_scope),
        ("route", parsed.route),
        ("risk_service_ref", parsed.risk_service_ref),
        ("risk_protocol_version", parsed.risk_protocol_version),
        ("execution_service_ref", parsed.execution_service_ref),
        ("execution_protocol_version", parsed.execution_protocol_version),
        ("monitor_service_ref", parsed.monitor_service_ref),
        ("monitor_protocol_version", parsed.monitor_protocol_version),
        ("runtime_service_ref", parsed.runtime_service_ref),
    )
    for field_name, field_value in text_fields:
        if not _is_nonempty_trimmed_str(field_value):
            raise LiveCompositionError(
                "GATEWAY_READINESS_COMPONENT_NOT_READY", detail=f"invalid_{field_name}"
            )

    if not any(parsed.route.startswith(prefix) for prefix in SUPPORTED_GATEWAY_EXCHANGE_PREFIXES):
        raise LiveCompositionError("GATEWAY_VENUE_UNSUPPORTED", detail=parsed.route)

    # Check explicit component states BEFORE generic readiness so version
    # incompatibility, auth failure, and unreachability are never disguised.
    for comp_name, comp_state in (
        ("risk", parsed.risk_state),
        ("execution", parsed.execution_state),
    ):
        if comp_state not in _VALID_COMPONENT_STATES:
            raise LiveCompositionError(
                "GATEWAY_READINESS_COMPONENT_NOT_READY", detail=f"{comp_name}_state_invalid"
            )
        if comp_state == "INCOMPATIBLE":
            raise LiveCompositionError(
                "GATEWAY_READINESS_VERSION_INCOMPATIBLE", detail=f"{comp_name}_incompatible"
            )
        if comp_state == "AUTH_FAILED":
            raise LiveCompositionError(
                "GATEWAY_READINESS_AUTH_FAILED", detail=f"{comp_name}_auth_failed"
            )
        if comp_state == "UNREACHABLE":
            raise LiveCompositionError(
                "GATEWAY_READINESS_UNREACHABLE", detail=f"{comp_name}_unreachable"
            )

    # D62S-03: server-side non-bypassable invariant
    if (
        parsed.strategy_principal_has_submit is not False
        or parsed.strategy_principal_has_reserve is not False
    ):
        raise LiveCompositionError("GATEWAY_PRINCIPAL_BYPASS_UNSAFE")
    if parsed.delegated_cancel_enabled is not True:
        raise LiveCompositionError(
            "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="delegated_cancel_disabled"
        )

    # D62S-02 / D62S-04 / D62S-05 invariants
    if parsed.risk_required is not True:
        raise LiveCompositionError("GATEWAY_RISK_REQUIRED")
    if parsed.execution_required is not True:
        raise LiveCompositionError("GATEWAY_EXECUTION_REQUIRED")
    if parsed.execution_direct_path_disabled is not True:
        raise LiveCompositionError("GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN")
    if parsed.monitor_required is not True:
        raise LiveCompositionError(
            "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="monitor_required_false"
        )
    if parsed.runtime_supervision_expected is not True:
        raise LiveCompositionError(
            "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="runtime_supervision_false"
        )
    if type(parsed.monitor_stop_new_active) is not bool:
        raise LiveCompositionError(
            "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="monitor_stop_new_invalid"
        )
    if parsed.last_acked_heartbeat_age_ms is not None and (
        type(parsed.last_acked_heartbeat_age_ms) is not int
        or parsed.last_acked_heartbeat_age_ms < 0
    ):
        raise LiveCompositionError(
            "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="heartbeat_age_invalid"
        )

    if expected_binding is not None:
        if expected_binding.mode != "gateway":
            raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="non_gateway_binding")
        if (
            expected_binding.account_scope is not None
            and parsed.account_scope != expected_binding.account_scope
        ) or (
            expected_binding.strategy_scope is not None
            and parsed.strategy_scope != expected_binding.strategy_scope
        ) or (
            expected_binding.route is not None and parsed.route != expected_binding.route
        ):
            raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="proof_scope_mismatch")

    if expected_run_id is not None:
        if not _is_nonempty_trimmed_str(parsed.registered_run_id) or (
            parsed.registered_run_id != expected_run_id
        ):
            raise LiveCompositionError(
                "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="runtime_run_id_mismatch"
            )

    if require_ready_for_write:
        if parsed.risk_state != "READY":
            raise LiveCompositionError(
                "GATEWAY_READINESS_COMPONENT_NOT_READY", detail=f"risk_{parsed.risk_state}"
            )
        if parsed.execution_state != "READY":
            raise LiveCompositionError(
                "GATEWAY_READINESS_COMPONENT_NOT_READY",
                detail=f"execution_{parsed.execution_state}",
            )
    return parsed


class ProcessModeFence:
    """Single-process single-mode fence implementing D62S-09a."""

    _lock = threading.Lock()
    _active_mode: Optional[str] = None

    @classmethod
    def claim(cls, mode: str) -> str:
        """Bind this OS process to *mode* or reject cross-mode composition."""
        if type(mode) is not str or mode not in LIVE_MODES:
            raise LiveCompositionError("MODE_INVALID")
        with cls._lock:
            if cls._active_mode is None:
                cls._active_mode = mode
                return mode
            if cls._active_mode != mode:
                raise LiveCompositionError(
                    "PROCESS_MODE_CONFLICT",
                    detail=f"active={cls._active_mode},requested={mode}",
                )
            return cls._active_mode

    @classmethod
    def current(cls) -> Optional[str]:
        with cls._lock:
            return cls._active_mode

    @classmethod
    def _reset_for_tests(cls) -> None:
        """Reset fence state strictly for isolated unit-test teardown."""
        with cls._lock:
            cls._active_mode = None


def detect_forbidden_live_modules(
    mode: str,
    *,
    loaded_modules: Optional[Iterable[str]] = None,
) -> Tuple[str, ...]:
    """Return any loaded module names forbidden in *mode* (S-02 / S-03 module probe)."""
    if mode not in LIVE_MODES:
        raise LiveCompositionError("MODE_INVALID")
    names = tuple(sys.modules.keys()) if loaded_modules is None else tuple(loaded_modules)
    found = []
    if mode == "direct":
        for name in names:
            for prefix in FORBIDDEN_DIRECT_SUBPACKAGES:
                if name == prefix or name.startswith(prefix + "."):
                    found.append(name)
                    break
    else:
        for name in names:
            for prefix in FORBIDDEN_GATEWAY_PROVIDER_MODULES:
                if name == prefix or name.startswith(prefix + "."):
                    found.append(name)
                    break
    return tuple(sorted(set(found)))


def _validate_explicit_mode(snapshot: Mapping[str, Any]) -> str:
    if "mode" not in snapshot or snapshot["mode"] is None:
        raise LiveCompositionError("MODE_REQUIRED")
    mode = snapshot["mode"]
    if type(mode) is not str or mode not in LIVE_MODES:
        raise LiveCompositionError("MODE_INVALID")
    return mode


def _reject_direct_forbidden_keys(
    snapshot: Mapping[str, Any], extra: Mapping[str, Any]
) -> None:
    combined = dict(snapshot)
    combined.update(extra)
    provider_val = combined.get("provider")
    if isinstance(provider_val, str) and provider_val.strip().lower() == "forwarding":
        raise LegacyGatewayMigrationRequiredError(f"provider={provider_val!r}")
    if (
        combined.get("provider") == "local_replay"
        or combined.get("replay_market_tick_port") is not None
    ):
        raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="local_replay")
    backend = combined.get("backend")
    if backend is not None and str(backend).strip().lower() in {"gateway", "forwarding"}:
        raise LegacyGatewayMigrationRequiredError(f"backend={backend!r}")
    if "risk" in combined:
        raise LiveCompositionError("risk_requires_gateway")
    if "execution" in combined:
        raise LiveCompositionError("MODE_CONFLICT", detail="top_level_execution")
    for key in sorted(DIRECT_FORBIDDEN_GATEWAY_KEYS):
        if key in combined and combined[key] is not None:
            raise LiveCompositionError("MODE_CONFLICT", detail=key)
    for key in sorted(DIRECT_FORBIDDEN_HYBRID_ROUTING_KEYS):
        if key in combined and combined[key] is not None:
            raise LiveCompositionError("LEGACY_HYBRID_ROUTING_RETIRED", detail=key)
    for key in sorted(DIRECT_FORBIDDEN_SERVICE_PASSTHROUGH_KEYS):
        if key in combined and combined[key] is not None:
            raise LiveCompositionError("DIRECT_SERVICE_KEY_FORBIDDEN", detail=key)
    for key in sorted(DIRECT_FORBIDDEN_LEGACY_EXECUTION_KEYS):
        if key in combined and combined[key] is not None:
            if key == "event_batch_handoff" and combined[key] is False:
                continue
            raise LiveCompositionError("LEGACY_EXECUTION_PATH_RETIRED", detail=key)
    # Also inspect nested api_kwargs if provided in config
    nested_api_kwargs = combined.get("api_kwargs")
    if isinstance(nested_api_kwargs, Mapping):
        _reject_direct_forbidden_keys(nested_api_kwargs, {})


def _validate_gateway_calendar_exclusivity(snapshot: Mapping[str, Any]) -> None:
    calendars = snapshot.get("calendars")
    if isinstance(calendars, Mapping) and "feed_scope" in calendars:
        raise LiveCompositionError("CALENDAR_SCOPE_CONFLICT", detail="calendars.feed_scope")
    feed = snapshot.get("feed")
    if isinstance(feed, Mapping) and any("calendar_" + f in feed for f in _CALENDAR_FIELDS):
        raise LiveCompositionError("CALENDAR_SCOPE_CONFLICT", detail="feed.calendar_*")
    contracts = snapshot.get("contracts")
    if isinstance(contracts, Mapping):
        for symbol, row in contracts.items():
            if isinstance(row, Mapping) and any("calendar_" + f in row for f in _CALENDAR_FIELDS):
                raise LiveCompositionError(
                    "CALENDAR_SCOPE_CONFLICT", detail=f"contracts.{symbol}.calendar_*"
                )


def _reject_gateway_forbidden_keys(
    snapshot: Mapping[str, Any], extra: Mapping[str, Any]
) -> None:
    combined = dict(snapshot)
    combined.update(extra)
    provider_val = combined.get("provider")
    if isinstance(provider_val, str) and provider_val.strip().lower() == "forwarding":
        raise LegacyGatewayMigrationRequiredError(f"provider={provider_val!r}")
    if (
        combined.get("provider") == "local_replay"
        or combined.get("replay_market_tick_port") is not None
    ):
        raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="local_replay")
    backend = combined.get("backend")
    if backend is not None and str(backend).strip() != "":
        if str(backend).strip().lower() in {"gateway", "forwarding"}:
            raise LegacyGatewayMigrationRequiredError(f"backend={backend!r}")
        raise LiveCompositionError("GATEWAY_CONFIGURATION_CONFLICT", detail="backend")
    if "risk" in combined:
        raise LiveCompositionError("GATEWAY_CONFIGURATION_CONFLICT", detail="top_level_risk")
    if "execution" in combined:
        raise LiveCompositionError("GATEWAY_CONFIGURATION_CONFLICT", detail="top_level_execution")
    for key in sorted(GATEWAY_FORBIDDEN_DIRECT_KEYS):
        if key in combined and combined[key] is not None:
            if key == "api_kwargs" and not combined[key]:
                continue
            raise LiveCompositionError("GATEWAY_CONFIGURATION_CONFLICT", detail=key)
    for key in sorted(GATEWAY_FORBIDDEN_HYBRID_KEYS):
        if key in combined and combined[key] is not None:
            if key == "event_batch_handoff" and combined[key] is False:
                continue
            raise LiveCompositionError("GATEWAY_CONFIGURATION_CONFLICT", detail=key)
    broker_cfg = combined.get("broker")
    if isinstance(broker_cfg, Mapping):
        for direct_only in (
            "waiting_orders",
            "direct_facts_timeout",
            "direct_funds_refresh_interval",
            "direct_position_audit_interval",
        ):
            if direct_only in broker_cfg:
                raise LiveCompositionError("GATEWAY_CONFIGURATION_CONFLICT", detail=direct_only)


def _validate_strict_gateway_section(snapshot: Mapping[str, Any]) -> None:
    gw = snapshot.get("gateway_strategy")
    if not isinstance(gw, Mapping):
        raise LiveCompositionError("GATEWAY_CONFIGURATION_CONFLICT", detail="gateway_strategy")

    exchange_name = gw.get("exchange_name")
    if _is_nonempty_trimmed_str(exchange_name):
        if not any(
            exchange_name.startswith(prefix) for prefix in SUPPORTED_GATEWAY_EXCHANGE_PREFIXES
        ):
            raise LiveCompositionError("GATEWAY_VENUE_UNSUPPORTED", detail=exchange_name)

    # D62S-04: risk is mandatory and cannot be "none"
    if "risk" not in gw or gw["risk"] is None:
        raise LiveCompositionError("GATEWAY_RISK_REQUIRED", detail="risk_missing")
    if type(gw["risk"]) is str and gw["risk"] == "none":
        raise LiveCompositionError("GATEWAY_RISK_REQUIRED", detail="risk_none_forbidden")
    if not isinstance(gw["risk"], Mapping):
        raise LiveCompositionError("GATEWAY_RISK_REQUIRED", detail="risk_not_mapping")

    # D62S-05 (Scheme A2): execution is mandatory, cannot be "none", and forbids DIRECT_PATH bypass
    if "execution" not in gw or gw["execution"] is None:
        raise LiveCompositionError("GATEWAY_EXECUTION_REQUIRED", detail="execution_missing")
    if type(gw["execution"]) is str and gw["execution"] == "none":
        raise LiveCompositionError(
            "GATEWAY_EXECUTION_REQUIRED", detail="execution_none_forbidden"
        )
    if not isinstance(gw["execution"], Mapping):
        raise LiveCompositionError("GATEWAY_EXECUTION_REQUIRED", detail="execution_not_mapping")

    execution_sec = gw["execution"]
    routing = execution_sec.get("routing")
    if isinstance(routing, Mapping):
        if routing.get("allow_direct_path") is True or routing.get("unmatched_policy") == "DIRECT_PATH":
            raise LiveCompositionError("GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN")

    # D62S-03: requested_operations for strategy principal must never include direct.reserve/dispatch
    req_ops = gw.get("requested_operations")
    if isinstance(req_ops, (list, tuple, set, frozenset)):
        if "direct.reserve" in req_ops or "direct.dispatch" in req_ops:
            raise LiveCompositionError(
                "GATEWAY_PRINCIPAL_BYPASS_UNSAFE", detail="requested_direct_submit"
            )

    _validate_gateway_calendar_exclusivity(snapshot)


def _validate_common_product_sections(snapshot: Mapping[str, Any], *, mode: str) -> None:
    """Product-level config validation lifted from gateway_client_runner.py:98-191 (T-041)."""
    broker_cfg = snapshot.get("broker")
    if broker_cfg is not None:
        if not isinstance(broker_cfg, Mapping):
            raise LiveCompositionError("MODE_CONFLICT", detail="broker_not_mapping")
        pos_mode = broker_cfg.get("position_mode", "net")
        if type(pos_mode) is not str or pos_mode not in POSITION_MODES:
            raise LiveCompositionError("MODE_CONFLICT", detail="position_mode_invalid")
        mdo = broker_cfg.get("market_data_only", False)
        if type(mdo) is not bool:
            raise LiveCompositionError("MODE_CONFLICT", detail="market_data_only_invalid")

    if "run_timeout_seconds" in snapshot:
        timeout = snapshot["run_timeout_seconds"]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
            raise LiveCompositionError("MODE_CONFLICT", detail="run_timeout_seconds_invalid")

    feed = snapshot.get("feed")
    if feed is not None:
        if not isinstance(feed, Mapping):
            raise LiveCompositionError("MODE_CONFLICT", detail="feed_not_mapping")
        if "timeframe" in feed and feed["timeframe"] not in _VALID_FEED_TIMEFRAMES:
            raise LiveCompositionError("MODE_CONFLICT", detail="feed_timeframe_invalid")
        if "compression" in feed and (
            type(feed["compression"]) is not int or feed["compression"] <= 0
        ):
            raise LiveCompositionError("MODE_CONFLICT", detail="feed_compression_invalid")
        if "backfill_start" in feed and type(feed["backfill_start"]) is not bool:
            raise LiveCompositionError("MODE_CONFLICT", detail="feed_backfill_start_invalid")
        if mode == "gateway" and feed.get("backfill_start") is True:
            raise LiveCompositionError(
                "GATEWAY_CONFIGURATION_CONFLICT", detail="gateway_backfill_unsupported"
            )
        for age_key in ("event_time_max_age", "receive_time_max_age"):
            if age_key in feed:
                num = feed[age_key]
                if type(num) not in (int, float) or not math.isfinite(num) or num <= 0:
                    raise LiveCompositionError("MODE_CONFLICT", detail=f"feed_{age_key}_invalid")

    symbols = snapshot.get("symbols")
    contracts = snapshot.get("contracts")
    if symbols is not None or contracts is not None:
        if (
            type(symbols) is not list
            or not symbols
            or len(set(symbols)) != len(symbols)
            or any(not _is_nonempty_trimmed_str(sym) for sym in symbols)
            or not isinstance(contracts, Mapping)
            or any(sym not in contracts for sym in symbols)
        ):
            raise LiveCompositionError("MODE_CONFLICT", detail="contracts_symbols_invalid")
        for sym in symbols:
            row = contracts[sym]
            if not isinstance(row, Mapping):
                raise LiveCompositionError("MODE_CONFLICT", detail=f"contract_{sym}_invalid")
            if "price_tick" in row:
                pt = row["price_tick"]
                if type(pt) not in (int, float) or not math.isfinite(pt) or pt <= 0:
                    raise LiveCompositionError("MODE_CONFLICT", detail=f"price_tick_{sym}")
            if "multiplier" in row:
                mult = row["multiplier"]
                if type(mult) not in (int, float) or not math.isfinite(mult) or mult <= 0:
                    raise LiveCompositionError("MODE_CONFLICT", detail=f"multiplier_{sym}")
            if mode == "gateway":
                if "quantity_unit" in row and row["quantity_unit"] not in _VALID_QUANTITY_UNITS:
                    raise LiveCompositionError("GATEWAY_CONFIGURATION_CONFLICT", detail="quantity_unit")
                if "time_in_force" in row and row["time_in_force"] not in _VALID_TIF_GATEWAY:
                    raise LiveCompositionError("GATEWAY_CONFIGURATION_CONFLICT", detail="time_in_force")

    if mode == "gateway" and "gateway_resource_provider" in snapshot:
        rp = snapshot["gateway_resource_provider"]
        if type(rp) is not str or not _REF_RE.fullmatch(rp):
            raise LiveCompositionError(
                "GATEWAY_CONFIGURATION_CONFLICT", detail="gateway_resource_provider"
            )

    logging_cfg = snapshot.get("logging")
    if logging_cfg is not None:
        if not isinstance(logging_cfg, Mapping):
            raise LiveCompositionError("MODE_CONFLICT", detail="logging_not_mapping")
        for lv_key in ("level", "other_level"):
            if lv_key in logging_cfg:
                lv = logging_cfg[lv_key]
                if type(lv) is not str or lv.upper() not in _VALID_LOG_LEVELS:
                    raise LiveCompositionError("MODE_CONFLICT", detail=f"logging_{lv_key}")


def validate_live_config(
    config: Mapping[str, Any],
    *,
    extra_kwargs: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate and return a clean snapshot of a live Direct or Gateway configuration.

    Runs completely offline before any socket, SDK client, or filesystem state
    mutation occurs. Never mutates the caller's mapping.
    """
    if not isinstance(config, Mapping):
        raise LiveCompositionError("MODE_REQUIRED", detail="config_not_mapping")
    snapshot = _snapshot_mapping(config)
    extra = _snapshot_mapping(extra_kwargs) if extra_kwargs is not None else {}
    if not isinstance(extra, Mapping):
        raise LiveCompositionError("MODE_CONFLICT", detail="extra_kwargs_not_mapping")

    mode = _validate_explicit_mode(snapshot)
    if mode == "direct":
        _reject_direct_forbidden_keys(snapshot, extra)
    else:
        _reject_gateway_forbidden_keys(snapshot, extra)
        _validate_strict_gateway_section(snapshot)

    _validate_common_product_sections(snapshot, mode=mode)
    return dict(snapshot)


def _derive_run_binding(
    snapshot: Mapping[str, Any],
    *,
    mode: str,
    position_mode: Optional[str] = None,
    market_data_only: Optional[bool] = None,
    account_scope: Optional[str] = None,
    strategy_scope: Optional[str] = None,
    route: Optional[str] = None,
) -> LiveRunBinding:
    broker_cfg = snapshot.get("broker") if isinstance(snapshot.get("broker"), Mapping) else {}
    resolved_pos_mode = (
        position_mode
        if position_mode is not None
        else str(broker_cfg.get("position_mode", "net"))
    )
    if market_data_only is not None:
        resolved_mdo = market_data_only
    elif "market_data_only" in broker_cfg:
        resolved_mdo = bool(broker_cfg["market_data_only"])
    elif "market_data_only" in snapshot:
        raw_mdo = snapshot["market_data_only"]
        if type(raw_mdo) is not bool:
            raise LiveCompositionError("MODE_CONFLICT", detail="market_data_only_invalid")
        resolved_mdo = raw_mdo
    else:
        resolved_mdo = False
    resolved_account = account_scope
    resolved_strategy = strategy_scope
    resolved_route = route
    if mode == "gateway":
        gw = snapshot.get("gateway_strategy")
        if isinstance(gw, Mapping):
            if resolved_route is None and _is_nonempty_trimmed_str(gw.get("exchange_name")):
                resolved_route = gw["exchange_name"]
            gw_binding = gw.get("binding")
            if isinstance(gw_binding, Mapping):
                if resolved_account is None and _is_nonempty_trimmed_str(
                    gw_binding.get("account_scope")
                ):
                    resolved_account = gw_binding["account_scope"]
                if resolved_strategy is None and _is_nonempty_trimmed_str(
                    gw_binding.get("strategy_scope")
                ):
                    resolved_strategy = gw_binding["strategy_scope"]
    else:
        ex_kwargs = snapshot.get("exchange_kwargs")
        if resolved_route is None and isinstance(ex_kwargs, Mapping) and len(ex_kwargs) == 1:
            only_route = next(iter(ex_kwargs))
            if _is_nonempty_trimmed_str(only_route):
                resolved_route = only_route
    return LiveRunBinding(
        mode=mode,
        position_mode=resolved_pos_mode,
        market_data_only=resolved_mdo,
        account_scope=resolved_account,
        strategy_scope=resolved_strategy,
        route=resolved_route,
    )


def _is_service_read_proxy_instance(api: Any) -> bool:
    if api is None:
        return False
    cls = type(api)
    if cls.__name__ == "ServiceReadProxy" and (
        cls.__module__.startswith("backtrader.service.")
        or cls.__module__.startswith("bt_api_py.")
    ):
        return True
    try:
        from ..service.service_read_proxy import ServiceReadProxy
    except Exception:
        return False
    return isinstance(api, ServiceReadProxy)


def create_direct_store(
    *,
    config: Optional[Mapping[str, Any]] = None,
    provider: str = "btapi",
    api: Any = None,
    api_cls: Any = None,
    direct_api_factory: Any = None,
    position_mode: Optional[str] = None,
    market_data_only: Optional[bool] = None,
    account_scope: Optional[str] = None,
    strategy_scope: Optional[str] = None,
    route: Optional[str] = None,
    enforce_process_fence: bool = True,
    **store_kwargs: Any,
) -> Any:
    """Compose a strict Direct mode Store via the single composition root."""
    if _is_service_read_proxy_instance(api):
        raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="service_read_proxy")
    if direct_api_factory is not None:
        if api_cls is not None:
            raise LiveCompositionError("MODE_CONFLICT", detail="duplicate_direct_api_factory")
        api_cls = direct_api_factory

    raw_cfg: Dict[str, Any] = dict(config) if config is not None else {}
    if "mode" not in raw_cfg:
        raw_cfg["mode"] = "direct"
    elif raw_cfg["mode"] != "direct":
        raise LiveCompositionError("MODE_CONFLICT", detail="create_direct_store_mode_mismatch")

    extra_for_validation = dict(store_kwargs)
    extra_for_validation["provider"] = provider
    snapshot = validate_live_config(raw_cfg, extra_kwargs=extra_for_validation)
    binding = _derive_run_binding(
        snapshot,
        mode="direct",
        position_mode=position_mode,
        market_data_only=market_data_only,
        account_scope=account_scope,
        strategy_scope=strategy_scope,
        route=route,
    )
    if enforce_process_fence:
        ProcessModeFence.claim("direct")

    store_config = {k: v for k, v in snapshot.items() if k != "mode"}
    from .direct_btapi_store import DirectBtApiStore

    return DirectBtApiStore(
        provider=provider,
        api=api,
        api_cls=api_cls,
        config=store_config,
        run_binding=binding,
        **store_kwargs,
    )


def create_gateway_store(
    *,
    config: Mapping[str, Any],
    gateway_host: Any,
    gateway_security_profiles: Mapping[str, Any],
    gateway_readiness_proof: Any = None,
    gateway_api_factory: Any = None,
    expected_run_id: Optional[str] = None,
    position_mode: Optional[str] = None,
    market_data_only: Optional[bool] = None,
    enforce_process_fence: bool = True,
    **store_kwargs: Any,
) -> Any:
    """Compose a strict Gateway mode Store via the single composition root."""
    if not isinstance(config, Mapping):
        raise LiveCompositionError("MODE_REQUIRED", detail="config_not_mapping")
    raw_cfg: Dict[str, Any] = dict(config)
    if "mode" not in raw_cfg:
        raw_cfg["mode"] = "gateway"
    elif raw_cfg["mode"] != "gateway":
        raise LiveCompositionError("MODE_CONFLICT", detail="create_gateway_store_mode_mismatch")

    raw_proof = gateway_readiness_proof
    if raw_proof is None and "gateway_readiness_proof" in raw_cfg:
        raw_proof = raw_cfg.pop("gateway_readiness_proof")

    snapshot = validate_live_config(raw_cfg, extra_kwargs=store_kwargs)
    binding = _derive_run_binding(
        snapshot,
        mode="gateway",
        position_mode=position_mode,
        market_data_only=market_data_only,
    )
    validated_proof: Optional[GatewayReadinessProof] = None
    if raw_proof is not None:
        validated_proof = validate_gateway_readiness_proof(
            raw_proof,
            expected_binding=binding,
            expected_run_id=expected_run_id,
            require_ready_for_write=not binding.market_data_only,
        )

    if enforce_process_fence:
        ProcessModeFence.claim("gateway")

    store_config = {
        k: v
        for k, v in snapshot.items()
        if k not in {"mode", "market_data_only", "gateway_readiness_proof"}
    }
    from .gateway_btapi_store import GatewayBtApiStore

    return GatewayBtApiStore(
        config=store_config,
        gateway_host=gateway_host,
        gateway_security_profiles=gateway_security_profiles,
        gateway_readiness_proof=validated_proof,
        gateway_api_factory=gateway_api_factory,
        run_binding=binding,
        **store_kwargs,
    )


def create_live_store(
    *,
    config: Mapping[str, Any],
    enforce_process_fence: bool = True,
    **kwargs: Any,
) -> Any:
    """Unified composition-root entry requiring explicit ``config['mode']``."""
    if not isinstance(config, Mapping):
        raise LiveCompositionError("MODE_REQUIRED", detail="config_not_mapping")
    mode = _validate_explicit_mode(config)
    if mode == "direct":
        return create_direct_store(
            config=config,
            enforce_process_fence=enforce_process_fence,
            **kwargs,
        )
    return create_gateway_store(
        config=config,
        enforce_process_fence=enforce_process_fence,
        **kwargs,
    )
