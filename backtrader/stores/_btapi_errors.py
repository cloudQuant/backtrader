"""Errors for the Backtrader unified SDK Store and its bridges."""

from __future__ import annotations

from typing import Dict, Optional


class BtApiStoreError(Exception):
    """Base error for btapi store failures."""


LIVE_COMPOSITION_MIGRATION_HINTS: Dict[str, str] = {
    "MODE_REQUIRED": (
        "Explicitly declare mode='direct' or mode='gateway' in configuration; "
        "implicit presence-based mode selection is disabled on the composition root."
    ),
    "MODE_INVALID": "mode must be exactly 'direct' or 'gateway' (hybrid/placeholder modes are rejected).",
    "MODE_CONFLICT": "Do not mix Direct and Gateway configuration keys in the same configuration.",
    "PROCESS_MODE_CONFLICT": (
        "Single-process single-mode boundary (D62S-09a): run Direct and Gateway "
        "in separate OS processes."
    ),
    "DIRECT_SERVICE_KEY_FORBIDDEN": (
        "Direct mode forbids service passthrough keys (market_runtime_factory, "
        "forwarding_config, transport_mode); migrate to Gateway mode for service market hubs."
    ),
    "LEGACY_HYBRID_ROUTING_RETIRED": (
        "Direct+Execution hybrid routing is retired (D62S-07); export any legacy "
        "state/execution_routing.sqlite via live_state CLI and migrate empty-position to Gateway."
    ),
    "LEGACY_EXECUTION_PATH_RETIRED": (
        "Legacy execution_config / ServiceExecutionSession / ManagedExecutionAdapter paths are "
        "retired (D65-11/D62S-07); use Iteration 62 Direct write_admission + live_state or Gateway."
    ),
    "risk_requires_gateway": "Risk microservice selection is only allowed in Gateway mode.",
    "GATEWAY_CONFIGURATION_CONFLICT": (
        "Gateway mode forbids Direct provider keys (exchange_kwargs, write_admission, "
        "direct, ctp, api, api_cls, api_kwargs, backend)."
    ),
    "GATEWAY_RISK_REQUIRED": (
        "Strict Gateway mode requires a non-'none' Risk binding (D62S-04)."
    ),
    "GATEWAY_EXECUTION_REQUIRED": (
        "Strict Gateway mode requires a non-'none' Execution binding (D62S-05)."
    ),
    "GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN": (
        "Strict Gateway mode routes all orders through Execution (D62S-05 A2); "
        "DIRECT_PATH bypass is forbidden."
    ),
    "GATEWAY_VENUE_UNSUPPORTED": (
        "Gateway mode currently supports CTP routes only (D63-10/D62S-08c); "
        "use Direct mode for OKX/Binance."
    ),
    "CALENDAR_SCOPE_CONFLICT": (
        "Gateway mode must use gateway_strategy.calendar_settings and forbids local "
        "calendars.feed_scope or feed/contract calendar_* overrides."
    ),
    "RUN_BINDING_MISMATCH": (
        "Store, Feed, and Broker must share the exact immutable LiveRunBinding created "
        "by the same composition root."
    ),
    "GATEWAY_READINESS_UNREACHABLE": (
        "Gateway readiness endpoint is unreachable or timed out; failing closed without Direct fallback."
    ),
    "GATEWAY_READINESS_AUTH_FAILED": (
        "Gateway readiness authentication failed; verify CURVE keys and registered principal."
    ),
    "GATEWAY_READINESS_VERSION_INCOMPATIBLE": (
        "Confirmed protocol version incompatibility with one or more Gateway services (D68-02)."
    ),
    "GATEWAY_READINESS_COMPONENT_NOT_READY": (
        "Five-component deployment readiness incomplete (verify Risk, Execution, Monitor "
        "monitor_required=true, and Runtime --run-id supervision)."
    ),
    "GATEWAY_PRINCIPAL_BYPASS_UNSAFE": (
        "Strategy principal still holds Gateway SUBMIT/RESERVE (D62S-03); revoke direct submit "
        "rights on Gateway server so only authorized Risk proxy principal can submit."
    ),
    "LIVE_STATE_MODE_MISMATCH": (
        "Strategy directory state/identity.json is bound to a different mode; cross-mode "
        "directory reuse is forbidden (R62S-11)."
    ),
    "LEGACY_EXECUTION_ROUTING_DB_UNEXPORTED": (
        "Legacy state/execution_routing.sqlite contains unresolved records; run "
        "export-legacy-execution-routing and obtain project/account owner written approval (D62S-07b)."
    ),
    "NON_LIVE_TOOL_CONFLICT": (
        "ServiceReadProxy and local_replay are standalone non-live tools (D62S-08a) "
        "and cannot enter the live composition root."
    ),
}


class LiveCompositionError(BtApiStoreError):
    """Finite, value-free configuration/composition rejection with migration hint."""

    definite_reject = True

    def __init__(self, code: str, *, detail: Optional[str] = None) -> None:
        if type(code) is not str or not code or not code.isascii():
            raise ValueError("LiveCompositionError code must be a non-empty ASCII string")
        self.code = code
        self.migration_hint = LIVE_COMPOSITION_MIGRATION_HINTS.get(
            code,
            "Review the Direct/Gateway dual-mode configuration schema before retrying.",
        )
        msg = f"{code}: {self.migration_hint}"
        if detail:
            msg = f"{code} ({detail}): {self.migration_hint}"
        super().__init__(msg)


class LegacyGatewayMigrationRequiredError(BtApiStoreError):
    """An old Store gateway/forwarding entry point requires offline migration."""

    code = "MIGRATION_REVIEW_REQUIRED"

    def __init__(self, target: str) -> None:
        self.target = str(target)
        super().__init__(
            f"BtApiStore legacy entry point {self.target!r} is retired "
            f"({self.code}); use bt_api_py.service_runtime.ServiceClientRuntime with a typed "
            "ServiceMarketClient, ServiceAccountClient, or ServiceExecutionClient. "
            "For managed Backtrader execution, configure "
            "backtrader.service.service_execution_session.ServiceExecutionSession(...) "
            "and then call .run(cerebro). "
            "Keep a matching historical release when no service binding exists."
        )


class _ApprovalLeaseRejected(BtApiStoreError):
    """Definite local rejection raised before an SDK write crosses its lease."""

    definite_reject = True

    def __init__(self, code: str):
        """Record the rejection code carried by this error.

        Args:
            code: Stable machine-readable rejection reason.
        """
        self.code = code
        super().__init__(code)


class BtApiMissingDependencyError(ImportError, BtApiStoreError):
    """Raised when bt_api_py is required but unavailable."""


class BtApiProviderNotImplementedError(NotImplementedError, BtApiStoreError):
    """Raised when a provider is intentionally left as a placeholder."""


