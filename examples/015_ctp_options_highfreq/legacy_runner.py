#!/usr/bin/env python
"""Run the self-contained Iteration 25 CTP-options tick replay.

``replay`` consumes only the fixture beside this file through Backtrader's
channel mode, ``Event``/``TickEvent`` and ``TickBroker``.  It opens no socket,
submits no broker order, creates no actual fill and emits no PnL.  Other modes
are intentionally rejected before a session can be built.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import backtrader as bt
import yaml
from backtrader.brokers.tickbroker import TickBroker
from backtrader.channel import Event, EventPriority
from backtrader.events import BarEvent, TickEvent
from backtrader.feeds import ClockMapping, CtpCohortNow
from backtrader.stores.btapistore import BtApiStore

try:
    from .ctp_options_highfreq_strategy import CtpOptionsHighfreqStrategy, canonical_sha256
except ImportError:  # Direct execution through this directory's run.py.
    from ctp_options_highfreq_strategy import CtpOptionsHighfreqStrategy, canonical_sha256


HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "config.yaml"
FIXTURE_SCHEMA = "iter25.ctp-options-tick-fixture.v1"
CONFIG_SCHEMA = "ctp-options-candidate.v1"
_ISO_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
FROZEN_FEED_UPPER_BOUNDS_MS = {
    "max_quote_age_ms": 250.0,
    "max_cross_leg_skew_ms": 100.0,
    "max_source_age_upper_ms": 250.0,
    "max_source_skew_upper_ms": 100.0,
    "max_source_clock_error_ms": 5.0,
}
FROZEN_TIMING_MS = {
    "leg_timeout_ms": 1_000,
    "unhedged_timeout_ms": 3_000,
    "maximum_holding_timeout_ms": 60_000,
    "idle_interval_ms": 50,
}
MODES = frozenset({"replay", "shadow", "simnow", "production"})
REPLAY_PURPOSES = frozenset({"formula"})
_CREDENTIAL_TOKENS = ("password", "secret", "token", "auth_code", "api_key", "credential")
_ADAPTER_SCOPED_WRITE_EVIDENCE_BOUNDARY = (
    "NOT_PROVEN: the adapter membrane and market_data_only Broker only observe "
    "adapter-routed attempts; they cannot attest raw external provider writes."
)
_INJECTED_STORE_WRITE_EVIDENCE_BOUNDARY = (
    "NOT_PROVEN: public BtApiStore lifecycle and market-data-only state do not attest "
    "raw external provider writes."
)
_BTAPI_STORE_TYPE = BtApiStore

# Frozen SimNow environment table.  Only these three keys may appear in
# ``config.yaml`` or in the selection env override.  The SDK profile names and
# their front pairs stay owned by ``bt_api_ctp``; this example never invents an
# endpoint and never infers a route from geography or the process public IP.
ENVIRONMENT_SELECTION_ENV = "ITER30_SIMNOW_PROFILE"
DEFAULT_ENVIRONMENT = "simnow_first_group1"
ENVIRONMENT_PROFILES: dict[str, dict[str, Any]] = {
    "simnow_first_group1": {
        "family": "set1",
        "market_alignment": "actual_market_hours",
        "sdk_profile": "set1_group1",
        "fallback_sdk_profile": "set1_group1_vpn",
    },
    "simnow_first_group2": {
        "family": "set1",
        "market_alignment": "actual_market_hours",
        "sdk_profile": "set1_group2",
        "fallback_sdk_profile": None,
    },
    "simnow_second_7x24": {
        "family": "set2",
        "market_alignment": "engineering_only",
        "sdk_profile": "set2_7x24_4000x",
        "fallback_sdk_profile": None,
    },
}
_SDK_PROFILE_FAMILIES = {
    "set1_group1": "set1",
    "set1_group1_vpn": "set1",
    "set1_group2": "set1",
    "set2_7x24": "set2",
    "set2_7x24_4000x": "set2",
    "set2_7x24_vpn": "set2",
}

# Iteration 30 artifact governance: record which ``backtrader`` produced a
# report, and refuse to start a live session against a snapshot this example
# was not built from.  The hash covers only the dependency files the
# observation actually relies on, so it stays cheap and reproducible.
BACKTRADER_ARTIFACT_TARGET = HERE.parent.parent / "backtrader"
BACKTRADER_DEPENDENCY_FILES = (
    "version.py",
    "strategy.py",
    "channel.py",
    "feeds/btapifeed.py",
    "feeds/ctpcohort.py",
    "stores/btapistore.py",
)


def runtime_artifact_evidence(*, module_path: str | None = None) -> dict[str, Any]:
    """Describe the loaded ``backtrader`` and hash its observed dependencies.

    ``module_path`` overrides the reported provenance path for diagnostics; the
    dependency digest always reflects the modules that are actually loaded.
    """

    # Evidence is consumed across Windows and POSIX validation hosts.  Keep
    # filesystem operations on native ``Path`` instances below, but serialize
    # paths in one stable, platform-neutral representation.
    loaded_path = Path(str(getattr(bt, "__file__", "") or "")).as_posix()
    reported_path = Path(str(module_path or loaded_path)).as_posix()
    install_kind = "unknown"
    if reported_path:
        try:
            Path(reported_path).resolve().relative_to(BACKTRADER_ARTIFACT_TARGET.resolve())
            install_kind = "workspace_source"
        except (OSError, ValueError):
            install_kind = "external_artifact"
    loaded_root = Path(loaded_path).parent if loaded_path else BACKTRADER_ARTIFACT_TARGET
    digest = hashlib.sha256()
    for relative in BACKTRADER_DEPENDENCY_FILES:
        digest.update(relative.encode("utf-8"))
        try:
            digest.update((loaded_root / relative).read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return {
        "module_path": reported_path,
        "loaded_module_path": loaded_path,
        "version": str(getattr(bt, "__version__", "") or ""),
        "install_kind": install_kind,
        "target_workspace_root": BACKTRADER_ARTIFACT_TARGET.as_posix(),
        "dependency_files": list(BACKTRADER_DEPENDENCY_FILES),
        "dependency_sha256": digest.hexdigest(),
    }


def require_target_backtrader_artifact(
    *, module_path: str | None = None, allow_external: bool = False
) -> dict[str, Any]:
    """Fail closed unless the loaded artifact is this workspace's source tree."""

    evidence = runtime_artifact_evidence(module_path=module_path)
    if evidence["install_kind"] != "workspace_source" and not allow_external:
        raise RunnerConfigurationError(
            "BACKTRADER_ARTIFACT_MISMATCH: the loaded backtrader is "
            f"{evidence['install_kind']} at {evidence['module_path']}; "
            "install this checkout (pip install -e) or opt into a diagnostic run"
        )
    return evidence


@dataclass(frozen=True)
class EnvironmentSelection:
    """One resolved SimNow environment, including its fallback evidence."""

    requested_profile: str
    family: str
    market_alignment: str
    sdk_profile: str
    fallback_sdk_profile: str | None
    attempted_profile: str
    actual_profile: str
    td_front: str | None
    md_front: str | None
    readiness: str
    reason: str

    @property
    def allowed_sdk_profiles(self) -> tuple[str, ...]:
        names = [self.sdk_profile]
        if self.fallback_sdk_profile:
            names.append(self.fallback_sdk_profile)
        return tuple(names)

    @property
    def clock_domain_id(self) -> str:
        """Return the derived clock domain; it never names another environment."""

        return f"iter30-{self.actual_profile}-monotonic-v1"

    @property
    def mapping_source(self) -> str:
        """Return the derived clock-mapping source for this actual profile."""

        return f"iter30-{self.actual_profile}-launcher-anchor"

    def as_evidence(self) -> dict[str, Any]:
        """Return the auditable subset written into reports and bindings."""

        return {
            "requested_environment_profile": self.requested_profile,
            "environment_family": self.family,
            "market_alignment": self.market_alignment,
            "attempted_profile": self.attempted_profile,
            "actual_environment_profile": self.actual_profile,
            "selection_readiness": self.readiness,
            "selection_reason": self.reason,
            "clock_domain_id": self.clock_domain_id,
            "mapping_source": self.mapping_source,
        }


def classify_sdk_profile(profile: Any) -> str:
    """Classify one SDK profile name into its frozen SimNow family, or ``""``."""

    name = str(profile or "").strip().lower()
    if name in _SDK_PROFILE_FAMILIES:
        return _SDK_PROFILE_FAMILIES[name]
    for family in ("set1", "set2"):
        if name.startswith(f"{family}_"):
            return family
    return ""


def _sdk_environment_resolver(
    *,
    family: str,
    sdk_profile: str,
    fallback_sdk_profile: str | None,
    timeout: float = 4.0,
) -> Mapping[str, Any]:
    """Probe the frozen SDK pairs for one family; never infers a route."""

    from bt_api_ctp.ctp_env_selector import select_reachable_ctp_environment

    selection = select_reachable_ctp_environment(
        env=family,
        profile=sdk_profile,
        front_probe_timeout=timeout,
    )
    return {
        "actual_profile": selection.profile,
        "td_front": selection.td_front,
        "md_front": selection.md_front,
        "readiness": selection.readiness,
        "reason": selection.reason,
    }


def environment_profile_key(config: Mapping[str, Any], *, override: str | None = None) -> str:
    """Resolve the requested frozen environment key from config or the override."""

    requested = override if override is not None else os.environ.get(ENVIRONMENT_SELECTION_ENV)
    if requested is None or not str(requested).strip():
        key = str(config.get("environment") or DEFAULT_ENVIRONMENT).strip()
        if key not in ENVIRONMENT_PROFILES:
            raise RunnerConfigurationError(
                f"SIMNOW_PROFILE_UNSELECTED: {key!r} is not a frozen environment key"
            )
        return key
    key = str(requested).strip()
    if key not in ENVIRONMENT_PROFILES:
        raise RunnerConfigurationError(
            f"SIMNOW_PROFILE_OVERRIDE_REJECTED: {key!r} is not a frozen environment key"
        )
    return key


def environment_selection_from_profile(profile_key: str) -> EnvironmentSelection:
    """Build the offline selection for one frozen key without any probe."""

    key = str(profile_key or "").strip()
    if key not in ENVIRONMENT_PROFILES:
        raise RunnerConfigurationError(
            f"SIMNOW_PROFILE_UNSELECTED: {key!r} is not a frozen environment key"
        )
    profile = ENVIRONMENT_PROFILES[key]
    return EnvironmentSelection(
        requested_profile=key,
        family=profile["family"],
        market_alignment=profile["market_alignment"],
        sdk_profile=profile["sdk_profile"],
        fallback_sdk_profile=profile["fallback_sdk_profile"],
        attempted_profile=profile["sdk_profile"],
        actual_profile=profile["sdk_profile"],
        td_front=None,
        md_front=None,
        readiness="not_probed",
        reason="offline_frozen_selection",
    )


def select_environment(
    config: Mapping[str, Any],
    *,
    resolver: Callable[..., Mapping[str, Any]] | None = None,
    requested: str | None = None,
    timeout: float = 4.0,
) -> EnvironmentSelection:
    """Probe the requested family and freeze exactly one reachable pair."""

    key = environment_profile_key(config, override=requested)
    profile = ENVIRONMENT_PROFILES[key]
    if resolver is None:

        def resolve(**kwargs: Any) -> Mapping[str, Any]:
            return _sdk_environment_resolver(**kwargs, timeout=timeout)

    else:
        resolve = resolver
    try:
        resolved = resolve(
            family=profile["family"],
            sdk_profile=profile["sdk_profile"],
            fallback_sdk_profile=profile["fallback_sdk_profile"],
        )
    except RuntimeError as exc:
        raise RunnerConfigurationError(
            f"CTP_SESSION_PROFILE_UNAVAILABLE: no reachable CTP front pair for {key}: {exc}"
        ) from None
    actual = str(resolved.get("actual_profile") or "").strip()
    allowed = tuple(
        name
        for name in (profile["sdk_profile"], profile["fallback_sdk_profile"])
        if name is not None
    )
    if actual not in allowed or classify_sdk_profile(actual) != profile["family"]:
        raise RunnerConfigurationError(
            "CTP_SESSION_PROFILE_REQUIRED: the resolved profile is outside the requested family"
        )
    return EnvironmentSelection(
        requested_profile=key,
        family=profile["family"],
        market_alignment=profile["market_alignment"],
        sdk_profile=profile["sdk_profile"],
        fallback_sdk_profile=profile["fallback_sdk_profile"],
        attempted_profile=profile["sdk_profile"],
        actual_profile=actual,
        td_front=str(resolved.get("td_front") or "").strip() or None,
        md_front=str(resolved.get("md_front") or "").strip() or None,
        readiness=str(resolved.get("readiness") or "").strip() or "unknown",
        reason=str(resolved.get("reason") or "").strip() or "unknown",
    )


def build_live_evidence_layers(
    *,
    binding: Mapping[str, Any],
    expected_symbols: Iterable[str],
    accepted_symbols: Iterable[str],
    tick_counts: Mapping[str, int],
    callback_counts: Mapping[str, int],
    idle_without_trusted_now_count: int,
    clock_violation_count: int,
    clock_rejection_latched: bool,
    confirmed_cohorts: int,
    last_quality_flags: Iterable[str],
    execution_eligible_ticks: int,
    forbidden_write_attempts: Mapping[str, int],
    last_screen: Any,
    ordinary_intent_count: int,
) -> dict[str, dict[str, Any]]:
    """Derive the five live layers from evidence the run actually collected.

    Layers never promote one another: a passing L0/L1 with an unqualified
    upstream leaves L2-L4 ``BLOCKED_BY_UPSTREAM_QUALIFICATION``.  The blocked
    status is deliberately distinct from ``NOT_RUN``: the run reached the layer
    and proved the upstream evidence is missing.
    """

    expected = [str(symbol) for symbol in expected_symbols]
    accepted = [str(symbol) for symbol in accepted_symbols]
    missing = [symbol for symbol in expected if symbol not in accepted]
    flags = [str(flag) for flag in last_quality_flags]

    l0_status = "PASS" if not dict(forbidden_write_attempts) else "FAIL"
    l1_status = "PASS" if not missing else "INCOMPLETE"
    qualified = not flags and int(execution_eligible_ticks) > 0
    blocked_reason = "UPSTREAM_EXECUTION_NOT_ISSUED"

    def blocked(evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "BLOCKED_BY_UPSTREAM_QUALIFICATION",
            "reason": blocked_reason,
            "evidence": evidence,
        }

    qualification_evidence = {
        "last_quality_flags": flags,
        "execution_eligible_ticks": int(execution_eligible_ticks),
        "required_fields": [
            "source_clock_quality",
            "receive_clock_quality",
            "freshness_verified",
            "stale",
            "continuity_status",
            "quality_flags",
            "execution_eligible",
            "volume_complete",
            "volume_quality",
        ],
    }
    cohort_evidence = {
        "confirmed_cohorts": int(confirmed_cohorts),
        "clock_rejection_latched": bool(clock_rejection_latched),
    }
    screen_evidence = {
        "ordinary_intent_count": int(ordinary_intent_count),
        "last_screen": last_screen,
    }
    return {
        "L0_connection_read_only": {
            "status": l0_status,
            "evidence": {
                "actual_environment_profile": binding.get("actual_environment_profile"),
                "profile_family_prefix": binding.get("profile_family_prefix"),
                "connection_generation": binding.get("connection_generation"),
                "trading_day": binding.get("trading_day"),
                "account_fingerprint_sha256": binding.get("account_fingerprint_sha256"),
                "forbidden_write_attempts": dict(forbidden_write_attempts),
            },
        },
        "L1_subscription_and_ticks": {
            "status": l1_status,
            "evidence": {
                "expected_symbols": expected,
                "accepted_symbols": accepted,
                "missing_symbols": missing,
                "tick_counts": {str(k): int(v) for k, v in dict(tick_counts).items()},
                "callback_counts": {str(k): int(v) for k, v in dict(callback_counts).items()},
                "idle_without_trusted_now_count": int(idle_without_trusted_now_count),
                "clock_violation_count": int(clock_violation_count),
                "clock_rejection_latched": bool(clock_rejection_latched),
            },
        },
        "L2_quote_qualification": (
            {"status": "PASS", "reason": "", "evidence": qualification_evidence}
            if qualified
            else blocked(qualification_evidence)
        ),
        "L3_cohort": (
            {"status": "PASS", "reason": "", "evidence": cohort_evidence}
            if qualified and int(confirmed_cohorts) > 0
            else blocked(cohort_evidence)
        ),
        "L4_economic_screen": (
            {"status": "PASS", "reason": "", "evidence": screen_evidence}
            if qualified and last_screen
            else blocked(screen_evidence)
        ),
    }


LIVE_EVIDENCE_LAYER_ORDER = (
    "L0_connection_read_only",
    "L1_subscription_and_ticks",
    "L2_quote_qualification",
    "L3_cohort",
    "L4_economic_screen",
)


def require_session_environment(
    state: Mapping[str, Any],
    *,
    selection: EnvironmentSelection,
    mapping: Any,
    observation_blocked: type[Exception],
) -> dict[str, Any]:
    """Accept any connected session inside the selected family, or fail closed."""

    required_fields = {
        "environment_profile",
        "connected",
        "read_only_ready",
        "execution_gate_armed",
        "account_fingerprint",
        "connection_generation",
    }
    if not required_fields.issubset(state):
        raise observation_blocked(
            "CTP_SESSION_STATE_REQUIRED",
            "public CTP session-state evidence is incomplete",
        )

    actual_profile = state.get("environment_profile")
    if classify_sdk_profile(actual_profile) != selection.family:
        raise observation_blocked(
            "CTP_SESSION_PROFILE_REQUIRED",
            "connected CTP session is not the required environment family",
        )
    if state.get("connected") is not True:
        raise observation_blocked(
            "CTP_SESSION_CONNECTED_REQUIRED",
            "public CTP session-state evidence is not connected",
        )
    if state.get("read_only_ready") is not True:
        raise observation_blocked(
            "CTP_SESSION_READ_ONLY_REQUIRED",
            "public CTP session-state evidence is not read-only ready",
        )
    if state.get("execution_gate_armed") is not False:
        raise observation_blocked(
            "CTP_SESSION_EXECUTION_GATE_REQUIRED",
            "public CTP session-state evidence reports an armed execution gate",
        )
    account_fingerprint = state.get("account_fingerprint")
    if not isinstance(account_fingerprint, str) or not account_fingerprint.strip():
        raise observation_blocked(
            "CTP_SESSION_FINGERPRINT_REQUIRED",
            "public CTP session-state evidence lacks an account fingerprint",
        )
    generation = state.get("connection_generation")
    if (
        type(generation) is not int
        or generation <= 0
        or generation != mapping.connection_generation
    ):
        raise observation_blocked(
            "CTP_SESSION_GENERATION_REQUIRED",
            "public CTP session generation does not match the trusted clock mapping",
        )

    binding = {
        "source": "BtApiStore.get_ctp_session_state",
        "exchange_name": "CTP___FUTURE",
        **selection.as_evidence(),
        # The session-attested profile wins over the requested/attempted one.
        "actual_environment_profile": actual_profile,
        "profile_family_prefix": selection.family,
        "account_fingerprint_sha256": hashlib.sha256(
            account_fingerprint.encode("utf-8")
        ).hexdigest(),
        "read_only_ready": True,
        "execution_gate_armed": False,
        "connection_generation": generation,
        "clock_mapping_id": mapping.mapping_id,
        "clock_mapping_generation": mapping.connection_generation,
    }
    trading_day = state.get("trading_day")
    if isinstance(trading_day, str) and trading_day.strip():
        binding["trading_day"] = trading_day.strip()
    return binding


class RunnerConfigurationError(ValueError):
    """A fail-closed configuration or mode error with no side effect."""


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RunnerConfigurationError(f"{name} must be a mapping")
    return dict(value)


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise RunnerConfigurationError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RunnerConfigurationError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise RunnerConfigurationError(f"{name} must be a finite positive number")
    return number


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise RunnerConfigurationError(f"{name} must be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise RunnerConfigurationError(f"{name} must be a positive integer") from exc
    if number <= 0:
        raise RunnerConfigurationError(f"{name} must be a positive integer")
    if isinstance(value, str) and str(number) != value.strip():
        raise RunnerConfigurationError(f"{name} must be a positive integer")
    return number


def _require_exact_keys(value: Mapping[str, Any], *, name: str, keys: set[str]) -> dict[str, Any]:
    result = _mapping(value, name)
    unknown = sorted(set(result) - keys)
    missing = sorted(keys - set(result))
    if unknown or missing:
        parts = []
        if unknown:
            parts.append(f"unknown={unknown}")
        if missing:
            parts.append(f"missing={missing}")
        raise RunnerConfigurationError(f"{name} keys are invalid ({', '.join(parts)})")
    return result


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(encoded.encode("utf-8"))


def _within_example(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(HERE)
    except ValueError as exc:
        raise RunnerConfigurationError("fixture must remain inside this example directory") from exc
    return resolved


def load_config(path: Path | str = DEFAULT_CONFIG) -> tuple[dict[str, Any], Path]:
    """Load and strictly validate this example's configuration only."""

    config_path = Path(path)
    if not config_path.is_absolute():
        candidate = HERE / config_path
        config_path = candidate if candidate.exists() else config_path.resolve()
    config_path = _within_example(config_path)
    if not config_path.is_file():
        raise RunnerConfigurationError(f"config does not exist: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = _mapping(raw, "config root")
    validate_config(config)
    return config, config_path.resolve()


def validate_config(config: Mapping[str, Any]) -> None:
    """Reject unsafe, ambiguous, or unfrozen candidate settings before runtime."""

    root = _require_exact_keys(
        config,
        name="config root",
        keys={
            "schema_version",
            "candidate_id",
            "mode",
            "purpose",
            "production_enabled",
            "environment",
            "contracts",
            "feed",
            "timing",
            "risk",
            "signal",
            "execution",
            "replay",
        },
    )
    if root["schema_version"] != CONFIG_SCHEMA:
        raise RunnerConfigurationError("unsupported config schema")
    if not isinstance(root["candidate_id"], str) or not root["candidate_id"].strip():
        raise RunnerConfigurationError("candidate_id must be non-empty")
    environment = root["environment"]
    if not isinstance(environment, str) or environment not in ENVIRONMENT_PROFILES:
        raise RunnerConfigurationError("environment must be one frozen SimNow environment key")
    mode = str(root["mode"])
    if mode not in MODES:
        raise RunnerConfigurationError("unsupported mode")
    if not isinstance(root["production_enabled"], bool) or root["production_enabled"]:
        raise RunnerConfigurationError("production_enabled must remain false")

    contracts = _require_exact_keys(
        root["contracts"], name="contracts", keys={"exchange", "future", "call", "put"}
    )
    if contracts["exchange"] not in {"CFFEX", "SHFE", "DCE", "CZCE", "INE", "GFEX"}:
        raise RunnerConfigurationError("contracts.exchange must be an exact CTP exchange ID")
    symbols = tuple(contracts[role] for role in ("future", "call", "put"))
    if len(set(symbols)) != 3 or any(
        not isinstance(symbol, str) or not symbol.strip() for symbol in symbols
    ):
        raise RunnerConfigurationError(
            "contracts must contain three distinct non-empty identifiers"
        )

    feed = _require_exact_keys(
        root["feed"],
        name="feed",
        keys={
            "timeframe",
            "dispatch_ticks",
            "dispatch_bars",
            "max_quote_age_ms",
            "max_cross_leg_skew_ms",
            "max_source_age_upper_ms",
            "max_source_skew_upper_ms",
            "max_source_clock_error_ms",
            "complete_cohort_confirmations",
        },
    )
    if feed["timeframe"] != "ticks" or feed["dispatch_ticks"] is not True:
        raise RunnerConfigurationError("the candidate requires tick dispatch")
    if feed["dispatch_bars"] is not False:
        raise RunnerConfigurationError("bar dispatch is forbidden for this tick-only candidate")
    for key in (
        "max_quote_age_ms",
        "max_cross_leg_skew_ms",
        "max_source_age_upper_ms",
        "max_source_skew_upper_ms",
        "max_source_clock_error_ms",
    ):
        value = _finite(feed[key], f"feed.{key}", positive=True)
        if value > FROZEN_FEED_UPPER_BOUNDS_MS[key]:
            raise RunnerConfigurationError(
                f"feed.{key} exceeds its frozen upper bound "
                f"{FROZEN_FEED_UPPER_BOUNDS_MS[key]:g}ms"
            )
    if (
        _positive_int(feed["complete_cohort_confirmations"], "feed.complete_cohort_confirmations")
        != 2
    ):
        raise RunnerConfigurationError("the candidate requires exactly two complete cohorts")

    timing = _require_exact_keys(
        root["timing"],
        name="timing",
        keys={
            "provider_contract",
            "runtime_provider",
            "synthetic_fixtures_only",
            "leg_timeout_ms",
            "unhedged_timeout_ms",
            "maximum_holding_timeout_ms",
            "idle_interval_ms",
        },
    )
    if timing["provider_contract"] != "explicit_immutable_same_scope_read_model_v1":
        raise RunnerConfigurationError("timing provider contract is frozen")
    if timing["runtime_provider"] != "unavailable":
        raise RunnerConfigurationError("the replay must not configure a runtime timing provider")
    if timing["synthetic_fixtures_only"] is not True:
        raise RunnerConfigurationError("only local synthetic timing fixtures are permitted")
    for key, expected in FROZEN_TIMING_MS.items():
        if _positive_int(timing[key], f"timing.{key}") != expected:
            raise RunnerConfigurationError(f"timing.{key} is frozen at {expected}ms")

    risk = _require_exact_keys(
        root["risk"],
        name="risk",
        keys={
            "capital_cap_cny",
            "working_cny",
            "recovery_reserve_cny",
            "daily_loss_limit_cny",
            "basket_loss_limit_cny",
            "lots_per_leg",
            "max_cycles",
        },
    )
    if (
        _finite(risk["capital_cap_cny"], "risk.capital_cap_cny", positive=True) != 10_000
        or _finite(risk["working_cny"], "risk.working_cny", positive=True) != 8_000
        or _finite(risk["recovery_reserve_cny"], "risk.recovery_reserve_cny", positive=True)
        != 2_000
    ):
        raise RunnerConfigurationError("the 10000/8000/2000 capital contract is frozen")
    if _positive_int(risk["lots_per_leg"], "risk.lots_per_leg") != 1:
        raise RunnerConfigurationError("the candidate requires one lot per leg")
    if _positive_int(risk["max_cycles"], "risk.max_cycles") != 1:
        raise RunnerConfigurationError("the candidate permits one cycle only")
    _finite(risk["daily_loss_limit_cny"], "risk.daily_loss_limit_cny", positive=True)
    _finite(risk["basket_loss_limit_cny"], "risk.basket_loss_limit_cny", positive=True)

    signal = _require_exact_keys(
        root["signal"], name="signal", keys={"entry_buffer_cny", "total_reserve_cny"}
    )
    if _finite(signal["entry_buffer_cny"], "signal.entry_buffer_cny", positive=True) != 20:
        raise RunnerConfigurationError("the initial entry buffer is frozen at 20 CNY")
    _finite(signal["total_reserve_cny"], "signal.total_reserve_cny", positive=True)

    execution = _require_exact_keys(
        root["execution"],
        name="execution",
        keys={
            "order_type",
            "ordinary_requests_per_second",
            "max_daily_write_attempts",
            "max_daily_ordinary_attempts",
            "safety_daily_reserved_attempts",
        },
    )
    if execution["order_type"] != "limit":
        raise RunnerConfigurationError("only limit-order semantics are admissible")
    if _positive_int(execution["ordinary_requests_per_second"], "execution.rate") > 2:
        raise RunnerConfigurationError("ordinary request rate cannot exceed two per second")
    if _positive_int(execution["max_daily_write_attempts"], "execution.max_writes") != 100:
        raise RunnerConfigurationError("daily write budget must remain 100")
    if _positive_int(execution["max_daily_ordinary_attempts"], "execution.max_ordinary") != 80:
        raise RunnerConfigurationError("daily ordinary budget must remain 80")
    if _positive_int(execution["safety_daily_reserved_attempts"], "execution.safety_reserve") != 20:
        raise RunnerConfigurationError("daily safety reserve must remain 20")

    replay = _require_exact_keys(
        root["replay"], name="replay", keys={"fixture", "scenario", "starting_cash"}
    )
    if not isinstance(replay["fixture"], str) or not replay["fixture"].strip():
        raise RunnerConfigurationError("replay.fixture must be a local relative path")
    _within_example(HERE / replay["fixture"])
    starting_cash = _finite(replay["starting_cash"], "replay.starting_cash", positive=True)
    if starting_cash < _finite(risk["capital_cap_cny"], "risk.capital_cap_cny", positive=True):
        raise RunnerConfigurationError("replay.starting_cash must cover the capital cap")

    if any(any(token in key.lower() for token in _CREDENTIAL_TOKENS) for key in _walk_keys(root)):
        raise RunnerConfigurationError("credentials are not permitted in config.yaml")


def effective_config(
    config: Mapping[str, Any], *, mode: str | None = None, purpose: str | None = None
) -> dict[str, Any]:
    """Create the hash-bound config used for one process without env overrides."""

    effective = copy.deepcopy(dict(config))
    if mode is not None:
        effective["mode"] = mode
    if purpose is not None:
        effective["purpose"] = purpose
    validate_config(effective)
    return effective


def load_fixture(config: Mapping[str, Any]) -> tuple[dict[str, Any], Path, str]:
    """Load and schema-check the replay fixture, returning it with its SHA-256."""

    replay = _mapping(config["replay"], "replay")
    fixture_path = _within_example(HERE / str(replay["fixture"]))
    if not fixture_path.is_file():
        raise RunnerConfigurationError("replay fixture does not exist")
    raw_bytes = fixture_path.read_bytes()
    try:
        fixture = _mapping(json.loads(raw_bytes), "fixture root")
    except json.JSONDecodeError as exc:
        raise RunnerConfigurationError("replay fixture is not valid JSON") from exc
    if fixture.get("schema_version") != FIXTURE_SCHEMA:
        raise RunnerConfigurationError("unsupported replay fixture schema")
    return fixture, fixture_path, _sha256_bytes(raw_bytes)


def validate_bundle(fixture: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze a synthetic C/P/F bundle without parsing contract names."""

    bundle = _mapping(fixture.get("bundle"), "fixture.bundle")
    if set(bundle) != {"discount_factor", "strike", "future", "call", "put"}:
        raise RunnerConfigurationError("fixture bundle fields are incomplete")
    legs = {
        role: _mapping(bundle[role], f"fixture.bundle.{role}") for role in ("future", "call", "put")
    }
    expected_kinds = {"future": "future", "call": "call", "put": "put"}
    contracts = _mapping(config["contracts"], "contracts")
    for role, leg in legs.items():
        if leg.get("kind") != expected_kinds[role] or leg.get("symbol") != contracts[role]:
            raise RunnerConfigurationError("fixture leg identity does not match frozen config")
        for field in (
            "symbol",
            "exchange_id",
            "underlying_id",
            "multiplier",
            "tick_size",
            "min_lot",
        ):
            if field not in leg:
                raise RunnerConfigurationError(f"fixture {role} lacks {field}")
        if leg["exchange_id"] != contracts["exchange"]:
            raise RunnerConfigurationError("fixture exchange does not match frozen config")
        if _finite(leg["multiplier"], f"fixture {role}.multiplier", positive=True) <= 0:
            raise RunnerConfigurationError("invalid multiplier")
        if _finite(leg["tick_size"], f"fixture {role}.tick_size", positive=True) <= 0:
            raise RunnerConfigurationError("invalid tick size")
        if _positive_int(leg["min_lot"], f"fixture {role}.min_lot") != 1:
            raise RunnerConfigurationError("fixture must use integer one-lot legs")
    if (
        legs["call"]["underlying_id"] != legs["future"]["symbol"]
        or legs["put"]["underlying_id"] != legs["future"]["symbol"]
    ):
        raise RunnerConfigurationError("option underlying must be the frozen future")
    if legs["call"].get("expiry") != legs["put"].get("expiry"):
        raise RunnerConfigurationError("call and put expiry must match")
    if legs["call"].get("strike") != legs["put"].get("strike") or str(
        legs["call"].get("strike")
    ) != str(bundle["strike"]):
        raise RunnerConfigurationError("call and put strike must match the frozen bundle")
    if len({str(leg["multiplier"]) for leg in legs.values()}) != 1:
        raise RunnerConfigurationError("all three multipliers must match")
    if (
        legs["call"].get("exercise_style") != "european"
        or legs["put"].get("exercise_style") != "european"
    ):
        raise RunnerConfigurationError("only european exercise is admitted to the formula fixture")
    if (
        legs["call"].get("premium_style") != "premium"
        or legs["put"].get("premium_style") != "premium"
    ):
        raise RunnerConfigurationError("only premium-style options are admitted to the fixture")
    _finite(bundle["discount_factor"], "fixture.discount_factor", positive=True)
    _finite(bundle["strike"], "fixture.strike", positive=True)
    evidence = _validate_metadata_evidence(fixture, legs, bundle)
    return {**bundle, "metadata_evidence": evidence}


FIXTURE_EVIDENCE_SCHEMA = "iter30.ctp-instrument-evidence.v1"
_EVIDENCE_LEG_FIELDS = (
    ("multiplier", "multiplier"),
    ("tick_size", "price_tick"),
    ("strike", "strike_price"),
    ("expiry", "expire_date"),
    ("exchange_id", "exchange_id"),
    ("underlying_id", "underlying"),
)
_EVIDENCE_OPTION_TYPES = {"call": "1", "put": "2"}
_SYMBOL_PATTERN = re.compile(r"^(?P<body>[A-Za-z]+\d{3,4})(?P<side>[CP])(?P<strike>\d+)$")


def _symbol_embedded_strike(symbol: Any) -> tuple[str, str]:
    """Return ``(side, strike)`` encoded in a CZCE option symbol, or ``("", "")``."""

    match = _SYMBOL_PATTERN.match(str(symbol or "").strip())
    if match is None:
        return "", ""
    return match.group("side"), match.group("strike")


def _validate_metadata_evidence(
    fixture: Mapping[str, Any],
    legs: Mapping[str, Mapping[str, Any]],
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the frozen contract metadata to a recorded instrument query.

    Iteration 30 (solution α): the fixture's metadata must be traceable to a
    real query, self-consistent, field-identical to the bundle, and part of the
    bundle identity hash -- a swapped or stale evidence block therefore cannot
    silently re-price the candidate.
    """

    evidence = fixture.get("metadata_evidence")
    if not isinstance(evidence, Mapping):
        raise RunnerConfigurationError(
            "FIXTURE_METADATA_EVIDENCE_MISSING: fixture has no metadata evidence block"
        )
    evidence = dict(evidence)
    if evidence.get("schema_version") != FIXTURE_EVIDENCE_SCHEMA:
        raise RunnerConfigurationError(
            "FIXTURE_METADATA_EVIDENCE_MISSING: unsupported metadata evidence schema"
        )
    source = str(evidence.get("source") or "").strip().lower()
    if not source or any(marker in source for marker in ("synthetic", "fixture", "replay")):
        raise RunnerConfigurationError(
            "FIXTURE_METADATA_EVIDENCE_MISSING: metadata evidence is not a real query record"
        )
    captured_at = str(evidence.get("captured_at") or "").strip()
    if not captured_at or not _ISO_UTC_PATTERN.match(captured_at):
        raise RunnerConfigurationError(
            "FIXTURE_METADATA_EVIDENCE_MISSING: metadata evidence lacks a UTC capture time"
        )
    evidence_legs = _mapping(evidence.get("legs"), "fixture.metadata_evidence.legs")
    if set(evidence_legs) != set(legs):
        raise RunnerConfigurationError(
            "FIXTURE_METADATA_EVIDENCE_MISSING: metadata evidence legs are incomplete"
        )
    recorded = str(evidence.get("legs_sha256") or "").strip()
    if recorded != _canonical_hash(evidence_legs):
        raise RunnerConfigurationError(
            "FIXTURE_METADATA_EVIDENCE_TAMPERED: metadata evidence hash does not match its legs"
        )

    for role, leg in legs.items():
        row = _mapping(evidence_legs[role], f"fixture.metadata_evidence.legs.{role}")
        if str(row.get("instrument_id")) != str(leg.get("symbol")):
            raise RunnerConfigurationError(f"FIXTURE_METADATA_MISMATCH:{role}:instrument_id")
        # Self-consistency first: a symbol that encodes a strike must agree with
        # the recorded strike, and its side must agree with the option type.
        side, embedded_strike = _symbol_embedded_strike(leg.get("symbol"))
        if side:
            if str(row.get("strike_price") or "") != embedded_strike:
                raise RunnerConfigurationError(
                    f"FIXTURE_SYMBOL_STRIKE_CONFLICT:{role}:{embedded_strike}"
                )
            expected_type = _EVIDENCE_OPTION_TYPES["call" if side == "C" else "put"]
            if str(row.get("option_type")) != expected_type:
                raise RunnerConfigurationError(f"FIXTURE_OPTION_TYPE_CONFLICT:{role}")
        elif row.get("strike_price") is not None:
            raise RunnerConfigurationError(f"FIXTURE_METADATA_MISMATCH:{role}:strike_price")
        for bundle_field, evidence_field in _EVIDENCE_LEG_FIELDS:
            if role == "future" and bundle_field in {"strike", "underlying_id"}:
                # CTP records the *product* id as UnderlyingInstrID for a
                # future, and a future has no strike; neither is comparable
                # with the option contract identity.
                continue
            recorded_value = row.get(evidence_field)
            if recorded_value is None or str(leg.get(bundle_field)) != str(recorded_value):
                raise RunnerConfigurationError(f"FIXTURE_METADATA_MISMATCH:{role}:{evidence_field}")
    if str(bundle["strike"]) != str(evidence_legs["call"].get("strike_price")):
        raise RunnerConfigurationError("FIXTURE_METADATA_MISMATCH:call:strike_price")
    return evidence


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _make_tick(
    *,
    role: str,
    bundle: Mapping[str, Any],
    quote: Mapping[str, Any],
    source_epoch: float,
    receive_epoch: float,
    receive_monotonic_ns: int,
    sequence: int,
    rules_hash: str,
    trading_day: str,
    source: str,
) -> TickEvent:
    leg = _mapping(bundle[role], f"bundle.{role}")
    tick = TickEvent(
        timestamp=source_epoch,
        symbol=str(leg["symbol"]),
        exchange=str(leg["exchange_id"]),
        asset_type="future" if role == "future" else "option",
        local_time=receive_epoch,
        exchange_time=source_epoch,
        received_wall_time=receive_epoch,
        received_monotonic_ns=receive_monotonic_ns,
        clock_domain_id="iter25-fixture-monotonic-v1",
        sequence=sequence,
        continuity_status="continuous",
        source=source,
        price=float(quote["last"]),
        volume=1.0,
        direction="buy",
        bid_price=float(quote["bid"]),
        ask_price=float(quote["ask"]),
        bid_volume=float(quote["bid_size"]),
        ask_volume=float(quote["ask_size"]),
    )
    tick.schema_version = "ctp.quote.v2"
    tick.volume_semantics = "delta"
    tick.event_time_utc = _iso(source_epoch)
    tick.recv_time_utc = _iso(receive_epoch)
    tick.recv_monotonic_ns = receive_monotonic_ns
    tick.ingest_seq = sequence
    tick.connection_generation = 1
    tick.subscription_epoch = 1
    tick.rules_hash = rules_hash
    tick.source_clock_quality = "verified"
    tick.receive_clock_quality = "verified"
    tick.source_clock_error_ms = 0.0
    tick.receive_clock_error_ms = 0.0
    tick.freshness_verified = True
    tick.trading_day = trading_day
    tick.action_day = trading_day
    tick.cum_volume = float(sequence)
    tick.cumulative_volume = float(sequence)
    tick.delta_volume = 1.0
    tick.open_interest = 1000.0
    tick.lower_limit = 1.0
    tick.upper_limit = 100000.0
    tick.volume_complete = True
    tick.volume_quality = "CONTINUOUS"
    tick.quality_flags = ()
    tick.execution_eligible = True
    tick.event_time_source = "fixture_utc"
    # The public cohort core never substitutes quote receipt time for current
    # time.  This direct replay has no Store/Feed dispatch queue, so its
    # fixture carries explicit deterministic decision-boundary evidence.
    tick.cohort_decision_now_monotonic_ns = receive_monotonic_ns
    tick.cohort_decision_now_epoch = _iso(receive_epoch)
    tick.cohort_decision_now_clock_domain_id = tick.clock_domain_id
    tick.cohort_decision_now_receive_clock_error_ms = 0.0
    tick.cohort_decision_now_receive_clock_quality = "verified"
    tick.cohort_decision_now_freshness_verified = True
    return tick


def _cohort_events(
    fixture: Mapping[str, Any], bundle: Mapping[str, Any], scenario: str
) -> list[Event]:
    base = _finite(fixture.get("start_epoch"), "fixture.start_epoch", positive=True)
    source = str(fixture.get("source") or "local_synthetic_fixture")
    trading_day = str(fixture.get("trading_day") or "")
    if len(trading_day) != 8 or not trading_day.isdigit():
        raise RunnerConfigurationError("fixture trading_day must be YYYYMMDD")
    quotes = _mapping(fixture.get("base_quotes"), "fixture.base_quotes")
    if set(quotes) != {"future", "call", "put"}:
        raise RunnerConfigurationError("fixture must contain three base quotes")
    rules_hash = canonical_sha256(bundle)
    cohort_count = {
        "valid_cohort": 2,
        "insufficient_cohort": 1,
        "duplicate_payload": 2,
        "mixed_trading_day": 2,
        "quality_gap": 2,
        "quality_flag": 2,
        "incomplete_volume": 2,
        "volume_quality_gap": 2,
        "out_of_limit": 2,
        "execution_ineligible": 2,
    }.get(scenario)
    if scenario == "bar_only":
        bar = BarEvent(
            timestamp=base,
            symbol=str(bundle["future"]["symbol"]),
            exchange=str(bundle["future"]["exchange_id"]),
            asset_type="futures",
            local_time=base,
            open=1000.0,
            high=1001.0,
            low=999.0,
            close=1000.0,
            volume=1.0,
            openinterest=1000.0,
        )
        return [
            Event(
                timestamp=bar.timestamp,
                priority=EventPriority.BAR,
                sequence=1,
                channel_type="bar",
                channel_name=bar.symbol,
                data=bar,
            )
        ]
    if scenario == "stale_source":
        cohort_count = 1
    if cohort_count is None:
        raise RunnerConfigurationError(f"unsupported replay scenario: {scenario}")

    events: list[Event] = []
    sequence = 0
    roles = ("future", "call", "put")
    for cohort_index in range(cohort_count):
        cohort_base = base + cohort_index * 0.050
        for role_index, role in enumerate(roles):
            sequence += 1
            source_epoch = cohort_base + role_index * 0.005
            receive_epoch = source_epoch + 0.001
            if scenario == "duplicate_payload" and cohort_index == 1:
                source_epoch = base + role_index * 0.005
            if scenario == "stale_source" and role == "put":
                source_epoch -= 60.0
                receive_epoch = cohort_base + role_index * 0.005 + 0.001
            event_trading_day = trading_day
            if scenario == "mixed_trading_day" and cohort_index == 1 and role == "put":
                event_trading_day = "20260911"
            receive_monotonic_ns = int((1_000_000.0 + receive_epoch - base) * 1_000_000_000)
            tick = _make_tick(
                role=role,
                bundle=bundle,
                quote=_mapping(quotes[role], f"fixture.base_quotes.{role}"),
                source_epoch=source_epoch,
                receive_epoch=receive_epoch,
                receive_monotonic_ns=receive_monotonic_ns,
                sequence=sequence,
                rules_hash=rules_hash,
                trading_day=event_trading_day,
                source=source,
            )
            if scenario == "quality_gap":
                tick.continuity_status = "gap"
            elif scenario == "quality_flag":
                tick.quality_flags = ("CONNECTION_GENERATION_CHANGED",)
            elif scenario == "incomplete_volume":
                tick.volume_complete = False
            elif scenario == "volume_quality_gap":
                tick.volume_quality = "BASELINE"
            elif scenario == "out_of_limit":
                tick.ask_price = float(tick.upper_limit) + 1.0
            elif scenario == "execution_ineligible":
                tick.execution_eligible = False
            events.append(
                Event(
                    # Channel ordering is local receipt order.  TickEvent retains the
                    # exchange/source timestamp so source-freshness is evaluated
                    # separately from the delivery clock.
                    timestamp=receive_epoch,
                    priority=EventPriority.TICK,
                    sequence=sequence,
                    channel_type="tick",
                    channel_name=tick.symbol,
                    data=tick,
                )
            )
    return sorted(events)


def _strategy_params(config: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    feed = _mapping(config["feed"], "feed")
    risk = _mapping(config["risk"], "risk")
    signal = _mapping(config["signal"], "signal")
    symbols = tuple(str(bundle[role]["symbol"]) for role in ("future", "call", "put"))
    return {
        "mode": str(config["mode"]),
        "candidate_id": str(config["candidate_id"]),
        "symbols": symbols,
        "exchange_id": str(bundle["future"]["exchange_id"]),
        "bundle": copy.deepcopy(dict(bundle)),
        "bundle_hash": canonical_sha256(bundle),
        "tick_sizes": {
            str(bundle[role]["symbol"]): float(bundle[role]["tick_size"])
            for role in bundle
            if role in {"future", "call", "put"}
        },
        "lots_per_leg": int(risk["lots_per_leg"]),
        "max_quote_age_ms": float(feed["max_quote_age_ms"]),
        "max_cross_leg_skew_ms": float(feed["max_cross_leg_skew_ms"]),
        "max_source_age_ms": float(feed["max_source_age_upper_ms"]),
        "max_source_skew_ms": float(feed["max_source_skew_upper_ms"]),
        "max_source_clock_error_ms": float(feed["max_source_clock_error_ms"]),
        "complete_cohort_confirmations": int(feed["complete_cohort_confirmations"]),
        "entry_buffer_cny": signal["entry_buffer_cny"],
        "total_reserve_cny": signal["total_reserve_cny"],
    }


class _IdleTick:
    """Minimal tick stand-in for a no-data idle clock poll."""

    recv_monotonic_ns = None
    symbol = ""


class _ObservationTrustedNowProvider:
    """Validate caller-owned CTP time evidence at the Feed dispatch boundary.

    ``BtApiFeed`` intentionally swallows provider exceptions to keep a raw
    malformed quote from crashing its dispatch loop.  This wrapper therefore
    retains the first failure and lets the outer observation boundary reject
    the whole run only after normal, read-only shutdown has completed.
    """

    _SYNTHETIC_MARKERS = ("fixture", "replay", "synthetic")

    def __init__(
        self,
        *,
        provider: Callable[[Any], CtpCohortNow],
        mapping: ClockMapping,
        expected_symbols: tuple[str, ...],
        observation_duration_seconds: float,
        observation_blocked: type[Exception],
    ) -> None:
        """Freeze the validation inputs and clear the retained-failure slot."""

        self._provider = provider
        self._mapping = mapping
        self._expected_symbols = expected_symbols
        self._observation_window_ns = int(math.ceil(observation_duration_seconds * 1_000_000_000.0))
        self._observation_blocked = observation_blocked
        self._failure: Exception | None = None
        self.calls = 0
        self._accepted_symbols: set[str] = set()
        self._initial_coherent_mono_ns: int | None = None

    @property
    def accepted_symbols(self) -> list[str]:
        """List the expected legs that produced at least one trusted time."""

        return [symbol for symbol in self._expected_symbols if symbol in self._accepted_symbols]

    def __call__(self, tick: Any) -> CtpCohortNow:
        """Validate one tick's trusted time; retain the first swallowed failure."""

        self.calls += 1
        try:
            self._validate_tick(tick)
            now = self._provider(tick)
            if not isinstance(now, CtpCohortNow):
                self._reject(
                    "TRUSTED_COHORT_NOW_REQUIRED",
                    "live observation requires CtpCohortNow evidence",
                )
            if now.clock_domain_id != self._mapping.clock_domain_id:
                self._reject(
                    "TRUSTED_COHORT_NOW_DOMAIN",
                    "trusted CTP time must use the live mapping clock domain",
                )
            tick_receive_ns = getattr(tick, "recv_monotonic_ns", None)
            if type(tick_receive_ns) is not int or now.now_monotonic_ns < tick_receive_ns:
                self._reject(
                    "TRUSTED_COHORT_NOW_STALE",
                    "trusted CTP time predates the delivered quote",
                )
            try:
                self._mapping.validate_pair(now.now_epoch, now.now_monotonic_ns / 1_000_000_000.0)
            except (TypeError, ValueError, OverflowError):
                self._reject(
                    "TRUSTED_COHORT_NOW_MAPPING",
                    "trusted CTP time is outside the caller-owned live mapping",
                )
            self._require_observation_window_coverage(now)
            self._accepted_symbols.add(str(tick.symbol))
            return now
        except Exception as error:
            if self._failure is None:
                self._failure = error
            raise

    def require_complete(self) -> None:
        """Turn swallowed Feed validation failures into a terminal run result."""

        if self._failure is not None:
            raise self._failure
        missing = [
            symbol for symbol in self._expected_symbols if symbol not in self._accepted_symbols
        ]
        if missing:
            self._reject(
                "TRUSTED_COHORT_NOW_INCOMPLETE",
                "live observation did not receive trusted CTP time for every configured leg",
            )

    def _require_observation_window_coverage(self, now: CtpCohortNow) -> None:
        """Bind the complete bounded run to its first coherent live time.

        The wall-clock watchdog may remain active while an otherwise live
        source is idle.  A mapping that merely covers already-delivered ticks
        cannot attest that idle part of the requested observation interval.
        The first CTP-coherent time is therefore a conservative trusted origin:
        the mapping must remain valid for the entire requested interval after
        it, including its declared calibration error.
        """

        if self._initial_coherent_mono_ns is not None:
            return
        required_valid_until_ns = (
            now.now_monotonic_ns + self._observation_window_ns + self._mapping.error_bound_ns
        )
        if required_valid_until_ns > self._mapping.valid_until_mono_ns:
            self._reject(
                "LIVE_CLOCK_MAPPING_DURATION_REQUIRED",
                "trusted clock mapping does not cover the full engineering observation window",
            )
        self._initial_coherent_mono_ns = now.now_monotonic_ns

    def idle_now(self) -> CtpCohortNow:
        """Return trusted time for one no-data idle poll, or fail closed.

        Unlike ``__call__`` there is no delivered quote to cross-check, so the
        symbol/staleness checks do not apply.  Domain, mapping coverage and
        window coverage still do; a violation raises and the strategy latches
        it, while a provider that is simply not ready returns ``None``.
        """

        now = self._provider(_IdleTick())
        if now is None:
            return None
        if not isinstance(now, CtpCohortNow):
            self._reject(
                "TRUSTED_COHORT_NOW_REQUIRED",
                "live observation requires CtpCohortNow evidence",
            )
        if now.clock_domain_id != self._mapping.clock_domain_id:
            self._reject(
                "TRUSTED_COHORT_NOW_DOMAIN",
                "trusted CTP time must use the live mapping clock domain",
            )
        try:
            self._mapping.validate_pair(now.now_epoch, now.now_monotonic_ns / 1_000_000_000.0)
        except (TypeError, ValueError, OverflowError):
            self._reject(
                "TRUSTED_COHORT_NOW_MAPPING",
                "trusted CTP time is outside the caller-owned live mapping",
            )
        self._require_observation_window_coverage(now)
        return now

    def _validate_tick(self, tick: Any) -> None:
        if getattr(tick, "schema_version", None) != "ctp.quote.v2":
            self._reject(
                "LIVE_CTP_QUOTE_REQUIRED", "live observation requires strict CTP-v2 quotes"
            )
        if getattr(tick, "clock_domain_id", None) != self._mapping.clock_domain_id:
            self._reject(
                "LIVE_QUOTE_CLOCK_DOMAIN",
                "CTP quote clock domain differs from the caller-owned live mapping",
            )
        if getattr(tick, "connection_generation", None) != self._mapping.connection_generation:
            self._reject(
                "LIVE_QUOTE_GENERATION",
                "CTP quote generation differs from the caller-owned live mapping",
            )
        if getattr(tick, "rules_hash", None) != self._mapping.rules_hash:
            self._reject(
                "LIVE_QUOTE_RULES_HASH",
                "CTP quote rules identity differs from the frozen candidate bundle",
            )
        source_values = (
            str(getattr(tick, "source", "") or "").lower(),
            str(getattr(tick, "event_time_source", "") or "").lower(),
        )
        if any(marker in value for value in source_values for marker in self._SYNTHETIC_MARKERS):
            self._reject(
                "SYNTHETIC_QUOTE_SOURCE",
                "engineering observation rejects replay or synthetic quote provenance",
            )

    def _reject(self, code: str, message: str) -> None:
        raise self._observation_blocked(code, message)


class _ObservationLifecycleProbe(bt.Analyzer):
    """Start the deadline only once the real strategy lifecycle is active."""

    params = (("on_started", None),)

    def start(self) -> None:
        """Invoke the lifecycle callback with the live strategy instance."""

        on_started = self.p.on_started
        if not callable(on_started):
            raise RuntimeError("engineering observation lifecycle callback is unavailable")
        on_started(self.strategy)


def _require_engineering_duration(run_seconds: Any, observation_blocked: type[Exception]) -> float:
    if isinstance(run_seconds, bool):
        raise observation_blocked(
            "ENGINEERING_DURATION", "run_seconds must be a bounded positive number"
        )
    try:
        seconds = float(run_seconds)
    except (TypeError, ValueError) as error:
        raise observation_blocked(
            "ENGINEERING_DURATION", "run_seconds must be a bounded positive number"
        ) from error
    if not math.isfinite(seconds) or not 0.0 < seconds <= 3600.0:
        raise observation_blocked(
            "ENGINEERING_DURATION", "engineering observation must run for at most 3600 seconds"
        )
    return seconds


def _require_live_clock_mapping(
    mapping: Any,
    *,
    bundle_hash: str,
    observation_blocked: type[Exception],
) -> ClockMapping:
    if not isinstance(mapping, ClockMapping):
        raise observation_blocked(
            "LIVE_CLOCK_MAPPING_REQUIRED", "engineering observation requires a live ClockMapping"
        )
    source = str(mapping.source or "").lower()
    if (
        mapping.synthetic is not False
        or mapping.rules_hash != bundle_hash
        or any(marker in source for marker in ("fixture", "replay", "synthetic"))
    ):
        raise observation_blocked(
            "LIVE_CLOCK_MAPPING_REQUIRED",
            "engineering observation requires a non-synthetic candidate-bound ClockMapping",
        )
    return mapping


def _require_feed_clock(feed_clock: Any, observation_blocked: type[Exception]) -> None:
    if not any(
        callable(getattr(feed_clock, name, None))
        for name in ("monotonic_ns", "monotonic_now", "monotonic")
    ):
        raise observation_blocked(
            "LIVE_FEED_CLOCK_REQUIRED",
            "engineering observation requires an injected monotonic feed clock",
        )


_TRANSFER_IDLE_COUNTERS = (
    "queue_depth",
    "inflight",
    "publications_pending",
    "funding_queue_depth",
    "funding_pending",
    "broker_update_queue_depth",
    "broker_update_dropped",
)
_TRANSFER_IDLE_FLAGS = (
    "close_thread_alive",
    "funding_inflight",
    "funding_worker_alive",
    "read_only_metadata_probe_active",
    "restart_blocked_by_worker",
    "restart_blocked_by_close",
    "funding_restart_blocked_by_worker",
    "risk_state_latched",
)
_TRANSFER_REQUIRED_TRUE_FLAGS = ("broker_update_conservation",)


def _read_market_data_only_rejection_count(
    health: Mapping[str, Any], observation_blocked: type[Exception]
) -> int:
    rejected = health.get("rejected_market_data_only")
    if type(rejected) is not int or rejected < 0:
        raise observation_blocked(
            "INJECTED_STORE_HEALTH_UNAVAILABLE",
            "Store market-data-only rejection audit is unavailable",
        )
    return rejected


def _uses_canonical_store_rejection_recorder(store: Any) -> bool:
    """Require the Store-owned aggregate audit implementation, not an override."""

    canonical = getattr(_BTAPI_STORE_TYPE, "record_market_data_only_broker_rejection", None)
    recorder = getattr(store, "record_market_data_only_broker_rejection", None)
    return (
        callable(canonical)
        and callable(recorder)
        and getattr(recorder, "__self__", None) is store
        and getattr(recorder, "__func__", None) is canonical
    )


def _require_injected_store_transfer(
    store: Any, *, ownership: Any, observation_blocked: type[Exception]
) -> int:
    """Accept one connected Store only after its lifecycle is explicitly transferred.

    A CTP operator may use one Store for read-only bundle/session preflight,
    then transfer that same connected Store to the strategy graph.  This
    function deliberately does not unwrap ``store.sdk_api`` or reconstruct a
    Store around it: doing so would create ambiguous client ownership and can
    reconnect or close the live session twice.  A transfer is irrevocable for
    this bounded run; the caller must not reuse or stop the Store afterwards.
    """

    if ownership != "transfer":
        raise observation_blocked(
            "STORE_OWNERSHIP_TRANSFER_REQUIRED",
            "store= requires store_ownership='transfer' before observation may stop it",
        )
    if not isinstance(store, _BTAPI_STORE_TYPE):
        raise observation_blocked(
            "INJECTED_STORE_INTERFACE_REQUIRED",
            "store= must be a real BtApiStore instance",
        )
    if str(getattr(store, "provider", "")).strip().lower() != "btapi":
        raise observation_blocked(
            "INJECTED_STORE_PROVIDER_REQUIRED",
            "store= must use the btapi provider",
        )
    if getattr(store, "is_connected", False) is not True:
        raise observation_blocked(
            "CTP_SESSION_STORE_UNREADY",
            "store= must already be connected before lifecycle transfer",
        )
    if any(
        not callable(getattr(store, name, None))
        for name in (
            "getbroker",
            "getdata",
            "get_command_health",
            "get_ctp_session_state",
            "record_market_data_only_broker_rejection",
            "stop",
        )
    ):
        raise observation_blocked(
            "INJECTED_STORE_INTERFACE_REQUIRED",
            "store= must provide the public BtApiStore observation interface",
        )
    if not _uses_canonical_store_rejection_recorder(store):
        raise observation_blocked(
            "INJECTED_STORE_AUDIT_CONTRACT_REQUIRED",
            "store= must retain the canonical BtApiStore rejected-write aggregate",
        )
    try:
        health = store.get_command_health()
    except Exception as error:
        raise observation_blocked(
            "INJECTED_STORE_HEALTH_UNAVAILABLE",
            "store= command health could not be read before lifecycle transfer",
        ) from error
    if not isinstance(health, Mapping):
        raise observation_blocked(
            "INJECTED_STORE_HEALTH_UNAVAILABLE",
            "store= command health is not a public mapping",
        )
    if health.get("shutdown_state") in {"PASS", "FAIL", "INCOMPLETE"}:
        raise observation_blocked(
            "INJECTED_STORE_TERMINATED",
            "store= has a terminal shutdown state and cannot be transferred",
        )
    for field in _TRANSFER_IDLE_COUNTERS:
        value = health.get(field)
        if type(value) is not int or value != 0:
            raise observation_blocked(
                "INJECTED_STORE_BUSY",
                "store= has queued or in-flight work and cannot be transferred",
            )
    if any(health.get(field) is not False for field in _TRANSFER_IDLE_FLAGS):
        raise observation_blocked(
            "INJECTED_STORE_BUSY",
            "store= has an active worker/probe and cannot be transferred",
        )
    if any(health.get(field) is not True for field in _TRANSFER_REQUIRED_TRUE_FLAGS):
        raise observation_blocked(
            "INJECTED_STORE_BUSY",
            "store= broker updates are not fully reconciled and cannot be transferred",
        )
    if health.get("last_error_code") != "":
        raise observation_blocked(
            "INJECTED_STORE_BUSY",
            "store= has a prior command error and cannot be transferred",
        )
    if health.get("funding_last_refresh_error") is not None:
        raise observation_blocked(
            "INJECTED_STORE_BUSY",
            "store= has a prior funding refresh error and cannot be transferred",
        )
    rejected = _read_market_data_only_rejection_count(health, observation_blocked)
    if rejected != 0:
        raise observation_blocked(
            "ENGINEERING_STORE_WRITE_BASELINE_REQUIRED",
            "store= recorded a market-data-only write rejection before transfer",
        )
    return rejected


def _injected_store_write_guard(
    store: Any,
    *,
    baseline: int,
    ownership: str,
    observation_blocked: type[Exception],
) -> dict[str, Any]:
    """Project the public local write fence for a transferred Store.

    This intentionally reports a local lifecycle boundary rather than claiming
    provider-side execution proof.  The session binding and market-data-only
    Broker shutdown independently establish that this graph did not open its
    order path.
    """

    try:
        health = store.get_command_health()
    except Exception as error:
        raise observation_blocked(
            "INJECTED_STORE_HEALTH_UNAVAILABLE",
            "transferred Store command health could not be read",
        ) from error
    if (
        not isinstance(health, Mapping)
        or health.get("shutdown_state") != "PASS"
        or health.get("accepting_openings") is not False
    ):
        raise observation_blocked(
            "INJECTED_STORE_HEALTH_UNAVAILABLE",
            "transferred Store did not reach a complete shutdown state",
        )
    rejected = _read_market_data_only_rejection_count(health, observation_blocked)
    if rejected < baseline:
        raise observation_blocked(
            "INJECTED_STORE_HEALTH_UNAVAILABLE",
            "transferred Store market-data-only health is invalid",
        )
    rejected_delta = rejected - baseline
    return {
        "source": "BtApiStore.get_command_health",
        "ownership": ownership,
        "forbidden_write_attempts": (
            {"store_market_data_only_rejected": rejected_delta} if rejected_delta else {}
        ),
        "market_data_only": "PROVEN_BY_SESSION_BINDING_AND_BROKER",
        "rejected_market_data_only": {
            "baseline": baseline,
            "final": rejected,
            "delta": rejected_delta,
        },
    }


def _broker_write_guard(broker: Any, observation_blocked: type[Exception]) -> dict[str, Any]:
    getter = getattr(broker, "get_market_data_only_audit", None)
    if not callable(getter):
        raise observation_blocked(
            "BROKER_WRITE_AUDIT_UNAVAILABLE",
            "market-data-only Broker audit is unavailable",
        )
    try:
        audit = getter()
    except Exception as error:
        raise observation_blocked(
            "BROKER_WRITE_AUDIT_UNAVAILABLE",
            "market-data-only Broker audit could not be read",
        ) from error
    fields = ("submit_rejected", "cancel_rejected", "batch_cancel_rejected", "total_rejected")
    if (
        not isinstance(audit, Mapping)
        or any(type(audit.get(field)) is not int or audit[field] < 0 for field in fields)
        or audit["total_rejected"] != sum(audit[field] for field in fields[:-1])
    ):
        raise observation_blocked(
            "BROKER_WRITE_AUDIT_UNAVAILABLE",
            "market-data-only Broker audit is invalid",
        )
    total = audit["total_rejected"]
    return {
        "source": "BtApiBroker.get_market_data_only_audit",
        **{field: audit[field] for field in fields},
        "forbidden_write_attempts": ({"broker_market_data_only_rejected": total} if total else {}),
    }


def _combine_write_guards(
    *guards: Mapping[str, Any], observation_blocked: type[Exception]
) -> dict[str, int]:
    combined: dict[str, int] = {}
    for guard in guards:
        attempts = guard.get("forbidden_write_attempts")
        if not isinstance(attempts, Mapping):
            raise observation_blocked(
                "INJECTED_STORE_HEALTH_UNAVAILABLE",
                "market-data-only write audit is invalid",
            )
        for name, value in attempts.items():
            if type(value) is not int or value <= 0:
                raise observation_blocked(
                    "INJECTED_STORE_HEALTH_UNAVAILABLE",
                    "market-data-only write audit is invalid",
                )
            combined[str(name)] = combined.get(str(name), 0) + value
    return combined


def _observation_shutdown_summary(
    broker: Any, store: Any, observation_blocked: type[Exception]
) -> dict[str, Any]:
    getter = getattr(broker, "get_shutdown_summary", None)
    try:
        summary = getter() if callable(getter) else None
    except Exception as error:
        raise observation_blocked(
            "SHUTDOWN_INCOMPLETE", "market-data-only shutdown evidence could not be read"
        ) from error
    if not isinstance(summary, Mapping):
        raise observation_blocked(
            "SHUTDOWN_INCOMPLETE", "market-data-only shutdown evidence is unavailable"
        )
    if (
        summary.get("status") not in {"OBSERVATION_ONLY", "OBSERVATION_ONLY_NONFLAT"}
        or summary.get("market_data_only") is not True
        or summary.get("cancel_requested") != 0
        or summary.get("close_requested") != 0
        or summary.get("store_shutdown_state") != "PASS"
    ):
        raise observation_blocked(
            "SHUTDOWN_INCOMPLETE", "market-data-only shutdown did not prove a zero-write stop"
        )
    try:
        health = store.get_command_health()
    except Exception as error:
        raise observation_blocked(
            "SHUTDOWN_INCOMPLETE", "Store shutdown health could not be read"
        ) from error
    if not isinstance(health, Mapping) or health.get("shutdown_state") != "PASS":
        raise observation_blocked("SHUTDOWN_INCOMPLETE", "Store shutdown health is not PASS")
    return {
        "status": str(summary["status"]),
        "market_data_only": True,
        "cancel_requested": 0,
        "close_requested": 0,
        "store_shutdown_state": "PASS",
    }


def _unstarted_observation_graph_shutdown_proven(
    *,
    broker: Any | None,
    store: Any | None,
    guarded_api: Any | None,
) -> bool:
    """Prove that a graph which never started could not have written.

    A construction failure can happen after a Store, Broker, or one Feed has
    been created but before Cerebro starts either transport.  The normal
    broker summary is deliberately ``NOT_STARTED`` in that state, so it cannot
    meet the stricter live-session shutdown projection.  It is nevertheless
    safe only when the Store confirms that it never connected and the
    deny-default membrane observed no attempted write.
    """

    if store is None:
        return broker is None
    try:
        health = store.get_command_health()
    except Exception:
        return False
    if not isinstance(health, Mapping) or health.get("shutdown_state") not in {
        "NOT_STARTED",
        "PASS",
    }:
        return False
    if getattr(store, "is_connected", None) is not False:
        return False
    if broker is not None:
        try:
            summary = broker.get_shutdown_summary()
        except Exception:
            return False
        if not isinstance(summary, Mapping) or summary.get("status") != "NOT_STARTED":
            return False
    if guarded_api is not None:
        try:
            audit = guarded_api.audit()
        except Exception:
            return False
        if not isinstance(audit, Mapping) or audit.get("forbidden_write_attempts") != {}:
            return False
    return True


def _force_observation_graph_shutdown(
    *,
    broker: Any | None,
    feeds: Iterable[Any],
    store: Any | None,
    guarded_api: Any | None,
    observation_blocked: type[Exception],
) -> None:
    """Stop every constructed graph component and prove a zero-write teardown.

    This is only used when normal Cerebro cleanup was skipped.  It attempts
    every stop in dependency order even if an earlier stop fails, and a
    shutdown-proof failure intentionally takes precedence over the initiating
    construction or binding exception.
    """

    cleanup_failed = False
    if broker is not None:
        try:
            broker.stop()
        except BaseException:
            cleanup_failed = True
    for feed in feeds:
        try:
            feed.stop()
        except BaseException:
            cleanup_failed = True
    if store is not None:
        try:
            store.stop(timeout=2.0)
        except BaseException:
            cleanup_failed = True
    if cleanup_failed:
        raise observation_blocked(
            "SHUTDOWN_INCOMPLETE",
            "engineering observation could not stop every constructed component",
        )
    if store is None:
        return
    try:
        _observation_shutdown_summary(broker, store, observation_blocked)
    except observation_blocked:
        if not _unstarted_observation_graph_shutdown_proven(
            broker=broker,
            store=store,
            guarded_api=guarded_api,
        ):
            raise


def _require_ctp_session_binding(
    store: Any,
    mapping: ClockMapping,
    observation_blocked: type[Exception],
    selection: EnvironmentSelection,
) -> dict[str, Any]:
    """Bind this run through the owned Store's public CTP read accessor."""

    if store.is_connected is not True:
        raise observation_blocked(
            "CTP_SESSION_STORE_UNREADY",
            "engineering observation requires a connected owned Store before session binding",
        )
    try:
        get_state = getattr(store, "get_ctp_session_state")
    except AttributeError:
        raise observation_blocked(
            "CTP_SESSION_STATE_REQUIRED",
            "public CTP session-state evidence is unavailable",
        ) from None
    if not callable(get_state):
        raise observation_blocked(
            "CTP_SESSION_STATE_REQUIRED",
            "public CTP session-state evidence is unavailable",
        )
    try:
        state = get_state()
    except Exception:
        raise observation_blocked(
            "CTP_SESSION_STATE_REQUIRED",
            "public CTP session-state evidence could not be read",
        ) from None
    if not isinstance(state, Mapping):
        raise observation_blocked(
            "CTP_SESSION_STATE_REQUIRED",
            "public CTP session-state evidence must be a mapping",
        )
    return require_session_environment(
        state,
        selection=selection,
        mapping=mapping,
        observation_blocked=observation_blocked,
    )


def run_engineering_observation(
    config: Mapping[str, Any],
    *,
    api: Any = None,
    store: Any = None,
    store_ownership: str | None = None,
    environment_profile: str,
    run_seconds: float,
    feed_clock: Any,
    clock_mapping: ClockMapping,
    live_now_provider: Callable[[Any], CtpCohortNow],
    environment_selection: EnvironmentSelection | None = None,
) -> dict[str, Any]:
    """Run one bounded, injected, zero-write strategy observation.

    This is deliberately not a CLI mode and does not load credentials.  A
    separately governed CTP owner injects exactly one lifecycle root: an API,
    or a connected Store whose lifecycle it explicitly transfers after a
    read-only preflight.  The Store path never reads ``store.sdk_api`` and
    never creates a second Store.  Successful completion proves only that this
    strategy callback chain observed live-shaped data in a forced
    market-data-only session; it cannot establish G3, G4, profitability, or
    HFT admission.

    ``environment_profile`` names one frozen key of ``ENVIRONMENT_PROFILES``
    and only constrains the session's *family*: any profile inside that family
    (for example the reachable ``set1_group1_vpn`` alternate for the nominal
    ``set1_group1``) is accepted.  A caller that probed reachability may pass
    the resolved ``environment_selection``; otherwise the frozen offline
    selection for that key is used and the report records ``not_probed``.
    """

    try:
        from .engineering_smoke import (
            ENGINEERING_OBSERVATION_G3_STATUS,
            ENGINEERING_OBSERVATION_MAX_SECONDS,
            EngineeringObservationBlocked,
            _ObservationReadOnlyApi,
        )
    except ImportError:  # Direct module loading from this example directory.
        from engineering_smoke import (  # type: ignore[no-redef]
            ENGINEERING_OBSERVATION_G3_STATUS,
            ENGINEERING_OBSERVATION_MAX_SECONDS,
            EngineeringObservationBlocked,
            _ObservationReadOnlyApi,
        )

    selection = environment_selection or environment_selection_from_profile(environment_profile)
    if selection.requested_profile != environment_profile:
        raise EngineeringObservationBlocked(
            "CTP_SESSION_PROFILE_REQUIRED",
            "the injected environment selection does not match environment_profile",
        )

    if api is not None and store is not None:
        raise EngineeringObservationBlocked(
            "ENGINEERING_STORE_INPUT",
            "engineering observation accepts exactly one of api= or store=",
        )
    if api is None and store is None:
        raise EngineeringObservationBlocked(
            "SDK_NOT_INJECTED", "engineering observation requires an explicit API object"
        )
    if store is None and store_ownership is not None:
        raise EngineeringObservationBlocked(
            "ENGINEERING_STORE_INPUT",
            "store_ownership is valid only when store= is supplied",
        )
    seconds = _require_engineering_duration(run_seconds, EngineeringObservationBlocked)
    if seconds > ENGINEERING_OBSERVATION_MAX_SECONDS:
        raise EngineeringObservationBlocked(
            "ENGINEERING_DURATION", "engineering observation must run for at most 3600 seconds"
        )
    if not callable(live_now_provider):
        raise EngineeringObservationBlocked(
            "TRUSTED_COHORT_NOW_REQUIRED",
            "engineering observation requires an injected CtpCohortNow provider",
        )
    _require_feed_clock(feed_clock, EngineeringObservationBlocked)

    effective = effective_config(config, mode="shadow", purpose="observation")
    fixture, _fixture_path, _fixture_hash = load_fixture(effective)
    bundle = validate_bundle(fixture, effective)
    bundle_hash = canonical_sha256(bundle)
    mapping = _require_live_clock_mapping(
        clock_mapping,
        bundle_hash=bundle_hash,
        observation_blocked=EngineeringObservationBlocked,
    )
    symbols = tuple(str(bundle[role]["symbol"]) for role in ("future", "call", "put"))
    trusted_now = _ObservationTrustedNowProvider(
        provider=live_now_provider,
        mapping=mapping,
        expected_symbols=symbols,
        observation_duration_seconds=seconds,
        observation_blocked=EngineeringObservationBlocked,
    )
    injected_store = store
    # This ceiling starts before the native graph exists.  A slow Store,
    # Broker, Feed, or session binding must consume the same one-hour budget
    # as strategy observation; it cannot earn a fresh full hour afterwards.
    started_at = time.monotonic()
    lifecycle_deadline = started_at + ENGINEERING_OBSERVATION_MAX_SECONDS
    lifecycle_started = threading.Event()
    deadline_stop_requested = threading.Event()
    lifecycle_deadline_stop_requested = threading.Event()
    lifecycle_lock = threading.Lock()
    lifecycle_started_at: list[float] = []
    deadline_timer: list[threading.Timer] = []
    lifecycle_deadline_timer: list[threading.Timer] = []
    session_identity: list[dict[str, Any]] = []
    cerebro_ref: list[Any] = []
    guarded_api: Any | None = None
    store: Any | None = None
    broker: Any | None = None
    cerebro: Any | None = None
    feeds: list[Any] = []
    store_write_baseline: int | None = None

    def request_lifecycle_deadline_stop() -> None:
        lifecycle_deadline_stop_requested.set()
        with lifecycle_lock:
            active_cerebro = cerebro_ref[0] if cerebro_ref else None
        if active_cerebro is not None:
            active_cerebro.runstop()

    def lifecycle_expired() -> bool:
        if time.monotonic() >= lifecycle_deadline:
            request_lifecycle_deadline_stop()
        return lifecycle_deadline_stop_requested.is_set()

    def require_lifecycle_budget() -> None:
        if lifecycle_expired():
            raise EngineeringObservationBlocked(
                "OBSERVATION_LIFECYCLE_DURATION_EXCEEDED",
                "engineering observation exhausted its end-to-end 3600-second lifecycle budget",
            )

    def cancel_watchdog(timer: threading.Timer | None) -> EngineeringObservationBlocked | None:
        if timer is None:
            return None
        timer.cancel()
        timer.join(timeout=1.0)
        if timer.is_alive():
            return EngineeringObservationBlocked(
                "WATCHDOG_INCOMPLETE", "engineering observation watchdog did not stop"
            )
        return None

    def start_lifecycle_deadline_watchdog() -> None:
        remaining_seconds = lifecycle_deadline - time.monotonic()
        if remaining_seconds <= 0.0:
            request_lifecycle_deadline_stop()
            return
        timer = threading.Timer(remaining_seconds, request_lifecycle_deadline_stop)
        timer.name = "iter25-engineering-observation-lifecycle-deadline"
        timer.daemon = True
        with lifecycle_lock:
            lifecycle_deadline_timer.append(timer)
        timer.start()

    # It can fire before Cerebro exists.  In that case the event makes every
    # construction checkpoint fail closed before ``run()`` clears its own
    # stop event for a new scope.
    start_lifecycle_deadline_watchdog()
    construction_error: BaseException | None = None
    construction_shutdown_error: EngineeringObservationBlocked | None = None
    try:
        require_lifecycle_budget()
        if injected_store is None:
            guarded_api = _ObservationReadOnlyApi(api)
            store = bt.stores.BtApiStore(
                provider="btapi",
                api=guarded_api,
                config={"execution_config": {"market_data_only": True}},
                autostart=False,
            )
            health = store.get_command_health()
            if not isinstance(health, Mapping):
                raise EngineeringObservationBlocked(
                    "INJECTED_STORE_HEALTH_UNAVAILABLE",
                    "new Store command health is unavailable",
                )
            store_write_baseline = _read_market_data_only_rejection_count(
                health,
                EngineeringObservationBlocked,
            )
            if store_write_baseline != 0:
                raise EngineeringObservationBlocked(
                    "ENGINEERING_STORE_WRITE_BASELINE_REQUIRED",
                    "new Store recorded a market-data-only write rejection",
                )
        else:
            store_write_baseline = _require_injected_store_transfer(
                injected_store,
                ownership=store_ownership,
                observation_blocked=EngineeringObservationBlocked,
            )
            # Ownership transfers immediately before graph construction.  Do
            # not unwrap the Store's managed SDK API or reconstruct a Store
            # from it: both operations can create an ambiguous second client
            # lifecycle around one live CTP session.
            store = injected_store
        require_lifecycle_budget()
        broker = store.getbroker(
            market_data_only=True,
            flatten_on_stop=False,
            force_refresh_queries=False,
            account_refresh_interval=3600.0,
            positions_refresh_interval=3600.0,
            open_orders_refresh_interval=3600.0,
            sdk_preflight=False,
            cash=float(_mapping(effective["replay"], "replay")["starting_cash"]),
        )
        require_lifecycle_budget()
        cerebro = bt.Cerebro(stdstats=False, quicknotify=True, runonce=False)
        with lifecycle_lock:
            cerebro_ref.append(cerebro)
        cerebro.setbroker(broker)
        if os.getenv("TRADE_LOGGER_CONSOLE", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        ):
            # Local-only operational log set: real-time console plus JSON line
            # files under this example's ignored reports/ directory. It adds
            # no external request and never touches the observation contract.
            console_dir = (
                HERE
                / "reports"
                / "trade-logger"
                / datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            cerebro.addobserver(
                bt.observers.TradeLogger,
                obsname="trade_logger",
                log_dir=str(console_dir),
                log_format="json",
                log_to_console=True,
                log_ticks=True,
                log_bars=True,
                log_positions=False,
                log_indicators=False,
                log_value=False,
                log_position_snapshot=False,
            )
        require_lifecycle_budget()
        for symbol, role in zip(symbols, ("future", "call", "put")):
            feed = store.getdata(
                dataname=symbol,
                timeframe=bt.TimeFrame.Ticks,
                compression=1,
                backfill_start=False,
                dispatch_ticks=True,
                dispatch_bars=False,
                qcheck=0.01,
                price_tick=float(bundle[role]["tick_size"]),
                clock=feed_clock,
                ctp_decision_now_provider=trusted_now,
            )
            feeds.append(feed)
            cerebro.adddata(feed, name=feed._dataname)
            require_lifecycle_budget()
        cerebro.addstrategy(CtpOptionsHighfreqStrategy, **_strategy_params(effective, bundle))
        require_lifecycle_budget()
    except BaseException as error:
        construction_error = error
        with lifecycle_lock:
            deadline = deadline_timer[0] if deadline_timer else None
            lifecycle_timer = lifecycle_deadline_timer[0] if lifecycle_deadline_timer else None
        for timer in (deadline, lifecycle_timer):
            watchdog_error = cancel_watchdog(timer)
            if watchdog_error is not None:
                construction_shutdown_error = watchdog_error
        try:
            _force_observation_graph_shutdown(
                broker=broker,
                feeds=feeds,
                store=store,
                guarded_api=guarded_api,
                observation_blocked=EngineeringObservationBlocked,
            )
        except EngineeringObservationBlocked as shutdown_failure:
            construction_shutdown_error = shutdown_failure
        if construction_shutdown_error is not None:
            raise construction_shutdown_error from construction_error
        if isinstance(construction_error, EngineeringObservationBlocked):
            raise construction_error from None
        raise EngineeringObservationBlocked(
            "ENGINEERING_CONSTRUCTION_FAILED",
            "engineering observation could not construct its native graph",
        ) from construction_error

    def request_deadline_stop() -> None:
        deadline_stop_requested.set()
        if cerebro is not None:
            cerebro.runstop()

    def start_deadline_watchdog() -> None:
        """Spend only the remaining end-to-end budget after session binding."""

        lifecycle_budget_exhausted = False
        with lifecycle_lock:
            if lifecycle_started.is_set():
                return
            lifecycle_started_at.append(time.monotonic())
            lifecycle_started.set()
            remaining_seconds = lifecycle_deadline - time.monotonic()
            if remaining_seconds <= 0.0 or lifecycle_deadline_stop_requested.is_set():
                lifecycle_budget_exhausted = True
            else:
                timer = threading.Timer(min(seconds, remaining_seconds), request_deadline_stop)
                timer.name = "iter25-engineering-observation-watchdog"
                timer.daemon = True
                deadline_timer.append(timer)
                timer.start()
        if lifecycle_budget_exhausted:
            request_lifecycle_deadline_stop()

    def bind_session_then_start_deadline(strategy: Any) -> None:
        session_identity.append(
            _require_ctp_session_binding(
                store,
                mapping,
                EngineeringObservationBlocked,
                selection,
            )
        )
        # The observation runner owns the trusted clock, so it hands the same
        # provider to the strategy for no-data idle polls.  Without this seam
        # the live path would count every idle callback as a missing source and
        # never advance its cached cohort evidence.
        strategy.set_cohort_now_provider(trusted_now.idle_now)
        start_deadline_watchdog()

    try:
        cerebro.addanalyzer(_ObservationLifecycleProbe, on_started=bind_session_then_start_deadline)
        require_lifecycle_budget()
    except BaseException as error:
        with lifecycle_lock:
            deadline = deadline_timer[0] if deadline_timer else None
            lifecycle_timer = lifecycle_deadline_timer[0] if lifecycle_deadline_timer else None
        for timer in (deadline, lifecycle_timer):
            watchdog_error = cancel_watchdog(timer)
            if watchdog_error is not None:
                construction_shutdown_error = watchdog_error
        try:
            _force_observation_graph_shutdown(
                broker=broker,
                feeds=feeds,
                store=store,
                guarded_api=guarded_api,
                observation_blocked=EngineeringObservationBlocked,
            )
        except EngineeringObservationBlocked as shutdown_failure:
            construction_shutdown_error = shutdown_failure
        if construction_shutdown_error is not None:
            raise construction_shutdown_error from error
        if isinstance(error, EngineeringObservationBlocked):
            raise error from None
        raise EngineeringObservationBlocked(
            "ENGINEERING_CONSTRUCTION_FAILED",
            "engineering observation could not finish constructing its native graph",
        ) from error

    strategies: list[Any] | None = None
    run_error: BaseException | None = None
    shutdown_error: EngineeringObservationBlocked | None = None
    run_finished_at = started_at
    try:
        strategies = cerebro.run(preload=False, runonce=False)
    except BaseException as error:
        run_error = error
    finally:
        run_finished_at = time.monotonic()
        with lifecycle_lock:
            deadline = deadline_timer[0] if deadline_timer else None
            lifecycle_timer = lifecycle_deadline_timer[0] if lifecycle_deadline_timer else None
        for timer in (deadline, lifecycle_timer):
            watchdog_error = cancel_watchdog(timer)
            if watchdog_error is not None:
                shutdown_error = watchdog_error
        # An error-path summary reader is evidence, not cleanup itself.  Treat
        # a failed read as unproven so the forced graph teardown below still
        # runs; otherwise a getter exception could escape this ``finally`` and
        # bypass Broker, Feed, and Store shutdown altogether.
        try:
            shutdown_getter = getattr(broker, "get_shutdown_summary", None)
            shutdown_before = shutdown_getter() if callable(shutdown_getter) else None
        except BaseException:
            shutdown_before = None
        aborted_before_normal_teardown = run_error is not None and (
            bool(getattr(store, "is_connected", False))
            or not isinstance(shutdown_before, Mapping)
            or shutdown_before.get("status") == "NOT_STARTED"
        )
        if aborted_before_normal_teardown:
            try:
                _force_observation_graph_shutdown(
                    broker=broker,
                    feeds=feeds,
                    store=store,
                    guarded_api=guarded_api,
                    observation_blocked=EngineeringObservationBlocked,
                )
            except EngineeringObservationBlocked as error:
                shutdown_error = error
        if run_error is not None and shutdown_error is None:
            try:
                _observation_shutdown_summary(broker, store, EngineeringObservationBlocked)
            except EngineeringObservationBlocked as error:
                shutdown_error = error
    ended_at = time.monotonic()
    elapsed_seconds = ended_at - started_at
    lifecycle_complete = (
        elapsed_seconds <= ENGINEERING_OBSERVATION_MAX_SECONDS
        and not lifecycle_deadline_stop_requested.is_set()
    )

    if shutdown_error is not None:
        raise shutdown_error
    if not lifecycle_complete:
        raise EngineeringObservationBlocked(
            "OBSERVATION_LIFECYCLE_DURATION_EXCEEDED",
            "engineering observation exceeded its end-to-end 3600-second lifecycle budget",
        )
    if run_error is not None:
        if isinstance(run_error, EngineeringObservationBlocked):
            raise run_error
        raise EngineeringObservationBlocked(
            "ENGINEERING_RUN_FAILED",
            "engineering observation did not complete its native lifecycle",
        ) from run_error
    if not isinstance(strategies, list) or len(strategies) != 1:
        raise EngineeringObservationBlocked(
            "ENGINEERING_STRATEGY_MISSING",
            "engineering observation did not produce one strategy instance",
        )
    strategy = strategies[0]
    if not isinstance(strategy, CtpOptionsHighfreqStrategy):
        raise EngineeringObservationBlocked(
            "ENGINEERING_STRATEGY_TYPE",
            "engineering observation did not run CtpOptionsHighfreqStrategy",
        )
    shutdown = _observation_shutdown_summary(broker, store, EngineeringObservationBlocked)
    trusted_now.require_complete()
    if store_write_baseline is None:
        raise EngineeringObservationBlocked(
            "INJECTED_STORE_HEALTH_UNAVAILABLE",
            "Store write-audit baseline is unavailable",
        )
    membrane_guard = (
        guarded_api.audit() if guarded_api is not None else {"forbidden_write_attempts": {}}
    )
    store_guard = _injected_store_write_guard(
        store,
        baseline=store_write_baseline,
        ownership=("INJECTED_STORE" if injected_store is not None else "ADAPTER_OWNED_STORE"),
        observation_blocked=EngineeringObservationBlocked,
    )
    broker_guard = _broker_write_guard(broker, EngineeringObservationBlocked)
    # The Store-scoped delta already includes every Broker bound to this
    # Store, including this graph's Broker.  Keep the Broker result as an
    # attribution breakdown without counting one rejected callback twice.
    forbidden_write_attempts = _combine_write_guards(
        membrane_guard,
        store_guard,
        observation_blocked=EngineeringObservationBlocked,
    )
    write_guard = {
        **dict(membrane_guard),
        "forbidden_write_attempts": forbidden_write_attempts,
        "store_market_data_only": store_guard,
        "broker_market_data_only": broker_guard,
    }
    write_evidence_boundary = (
        _INJECTED_STORE_WRITE_EVIDENCE_BOUNDARY
        if injected_store is not None
        else _ADAPTER_SCOPED_WRITE_EVIDENCE_BOUNDARY
    )
    if write_guard["forbidden_write_attempts"]:
        raise EngineeringObservationBlocked(
            "FORBIDDEN_WRITE_ATTEMPT", "engineering observation attempted an API write"
        )
    adapter_scoped_write_attempts = sum(write_guard["forbidden_write_attempts"].values())
    strategy_report = strategy.replay_report()
    if strategy_report.get("hft_status") != "NOT_ADMITTED":
        raise EngineeringObservationBlocked(
            "HFT_ADMISSION_STATE_INVALID", "engineering observation cannot alter HFT admission"
        )
    if broker.get_param("market_data_only") is not True:
        raise EngineeringObservationBlocked(
            "MARKET_DATA_ONLY_REQUIRED", "engineering observation broker is not read-only"
        )
    if getattr(store, "_sdk_mode", False) and not store._is_sdk_market_data_only():
        raise EngineeringObservationBlocked(
            "MARKET_DATA_ONLY_REQUIRED", "managed Store is not read-only"
        )
    if not lifecycle_started.is_set() or not lifecycle_started_at:
        raise EngineeringObservationBlocked(
            "ENGINEERING_LIFECYCLE_MISSING",
            "engineering observation did not enter the strategy lifecycle",
        )
    if len(session_identity) != 1:
        raise EngineeringObservationBlocked(
            "CTP_SESSION_STATE_REQUIRED",
            "engineering observation did not bind exactly one connected CTP session",
        )
    if not deadline_stop_requested.is_set():
        raise EngineeringObservationBlocked(
            "ENGINEERING_DURATION_INCOMPLETE",
            "engineering observation ended before its bounded deadline",
        )

    return {
        "schema_version": "iter25.ctp-options-highfreq-engineering-observation.v1",
        "status": "PASS_ENGINEERING_STRATEGY_OBSERVATION",
        "mode": "shadow",
        "purpose": "observation",
        "requested_environment_profile": str(environment_profile),
        "environment_selection": selection.as_evidence(),
        "runtime_artifact": runtime_artifact_evidence(),
        "store_ownership": (
            "INJECTED_STORE_LIFECYCLE_TRANSFERRED"
            if injected_store is not None
            else "ADAPTER_OWNED_STORE_FROM_API"
        ),
        "session_binding": session_identity[0],
        "config_sha256": _canonical_hash(effective),
        "bundle_sha256": bundle_hash,
        "chain": {
            "store": type(store).__name__,
            "feeds": [type(feed).__name__ for feed in feeds],
            "broker": type(broker).__name__,
            "cerebro": type(cerebro).__name__,
            "strategy": type(strategy).__name__,
        },
        "duration": {
            "requested_seconds": seconds,
            "elapsed_seconds": elapsed_seconds,
            "strategy_started": True,
            "active_window_elapsed_seconds": run_finished_at - lifecycle_started_at[0],
            "deadline_stop_requested": deadline_stop_requested.is_set(),
            "lifecycle_deadline_stop_requested": lifecycle_deadline_stop_requested.is_set(),
            "elapsed_within_maximum": lifecycle_complete,
            "maximum_seconds": ENGINEERING_OBSERVATION_MAX_SECONDS,
        },
        "feed_evidence": {
            "clock_mapping_id": mapping.mapping_id,
            "clock_domain": mapping.clock_domain_id,
            "clock_source": mapping.source,
            "synthetic": False,
            "trusted_cohort_now_calls": trusted_now.calls,
            "accepted_symbols": trusted_now.accepted_symbols,
        },
        "strategy": {
            "callback_counts": dict(strategy.callback_counts),
            "ordinary_intent_count": len(strategy._ordinary_intents),
            "idle_without_trusted_now_count": strategy_report["idle_without_trusted_now_count"],
            "clock_violation_count": strategy_report["clock_violation_count"],
            "clock_rejection_latched": strategy_report["clock_rejection_latched"],
            "tick_counts": strategy_report["tick_counts"],
            "execution_eligible_tick_count": strategy_report["execution_eligible_tick_count"],
            "last_quality_flags": strategy_report["last_quality_flags"],
            "confirmed_cohorts": strategy_report["confirmed_cohorts"],
            "hft_status": "NOT_ADMITTED",
            "execution_permission": "NOT_PROVEN",
        },
        "live_evidence_layers": build_live_evidence_layers(
            binding=session_identity[0],
            expected_symbols=symbols,
            accepted_symbols=trusted_now.accepted_symbols,
            tick_counts=strategy_report["tick_counts"],
            callback_counts=strategy.callback_counts,
            idle_without_trusted_now_count=strategy_report["idle_without_trusted_now_count"],
            clock_violation_count=strategy_report["clock_violation_count"],
            clock_rejection_latched=strategy_report["clock_rejection_latched"],
            confirmed_cohorts=strategy_report["confirmed_cohorts"],
            last_quality_flags=strategy_report["last_quality_flags"],
            execution_eligible_ticks=strategy_report["execution_eligible_tick_count"],
            forbidden_write_attempts=forbidden_write_attempts,
            last_screen=strategy_report["last_screen"],
            ordinary_intent_count=len(strategy._ordinary_intents),
        ),
        "write_guard": write_guard,
        "shutdown": shutdown,
        "adapter_scoped_write_attempts": adapter_scoped_write_attempts,
        "external_trade_writes": "NOT_PROVEN",
        "external_trade_writes_basis": write_evidence_boundary,
        "pnl_fields_emitted": False,
        "gates": {
            "G3_first_set_read_only": ENGINEERING_OBSERVATION_G3_STATUS,
            "G3_evaluation": "NOT_APPLICABLE_ENGINEERING_ONLY",
            "G4_simnow_mechanical": "NOT_RUN",
            "HFT_admission": "NOT_ADMITTED",
        },
    }


def business_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    """Exclude process/output paths while retaining deterministic candidate facts."""

    volatile = {"report_path", "manifest_path", "runtime_chain"}
    return {key: value for key, value in report.items() if key not in volatile}


def run_replay(
    config: Mapping[str, Any],
    *,
    scenario: str | None = None,
    output_directory: Path | str | None = None,
    invoke_idle_probe: bool = False,
    invoke_next_probe: bool = False,
) -> dict[str, Any]:
    """Run a deterministic, zero-network and zero-order channel replay."""

    validate_config(config)
    if str(config["mode"]) != "replay":
        raise RunnerConfigurationError("REPLAY_MODE_REQUIRED")
    if str(config["purpose"]) not in REPLAY_PURPOSES:
        raise RunnerConfigurationError("REPLAY_PURPOSE_NOT_IMPLEMENTED_FAIL_CLOSED")
    fixture, fixture_path, fixture_hash = load_fixture(config)
    bundle = validate_bundle(fixture, config)
    chosen_scenario = str(scenario or _mapping(config["replay"], "replay")["scenario"])
    events = _cohort_events(fixture, bundle, chosen_scenario)

    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    broker = TickBroker(cash=float(_mapping(config["replay"], "replay")["starting_cash"]))
    cerebro.setbroker(broker)
    cerebro.addstrategy(CtpOptionsHighfreqStrategy, **_strategy_params(config, bundle))
    strategies = cerebro.run(channel=events)
    strategy = strategies[0]
    if invoke_idle_probe:
        strategy.notify_idle()
    if invoke_next_probe:
        strategy.next()

    report = strategy.replay_report()
    report.update(
        schema_version="iter25.ctp-options-highfreq-replay-report.v1",
        status="LOCAL_REPLAY_PASS",
        scenario=chosen_scenario,
        config_sha256=_canonical_hash(dict(config)),
        fixture_sha256=fixture_hash,
        bundle_sha256=canonical_sha256(bundle),
        fixture_path=str(fixture_path.relative_to(HERE)),
        external_network_requests=0,
        external_write_requests=0,
        simulated_broker_orders=0,
        market_evidence=False,
        profitability_evidence=False,
        runtime_chain={
            "cerebro": f"{type(cerebro).__module__}.{type(cerebro).__name__}",
            "broker": f"{type(broker).__module__}.{type(broker).__name__}",
            "event": f"{Event.__module__}.{Event.__name__}",
            "tick_event": f"{TickEvent.__module__}.{TickEvent.__name__}",
            "strategy": f"{type(strategy).__module__}.{type(strategy).__name__}",
        },
    )
    report["business_summary"] = business_summary(report)
    report["business_summary_hash"] = _canonical_hash(report["business_summary"])
    if output_directory is not None:
        directory = Path(output_directory).resolve()
        directory.mkdir(parents=True, exist_ok=False)
        report_path = directory / "report.json"
        manifest_path = directory / "run_manifest.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "iter25.ctp-options-highfreq-manifest.v1",
                    "mode": "replay",
                    "purpose": str(config["purpose"]),
                    "config_sha256": report["config_sha256"],
                    "fixture_sha256": fixture_hash,
                    "bundle_sha256": report["bundle_sha256"],
                    "external_network_requests": 0,
                    "external_write_requests": 0,
                    "actual_fills": 0,
                    "pnl_fields_emitted": False,
                    "hft_status": "NOT_ADMITTED",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report["report_path"] = str(report_path)
        report["manifest_path"] = str(manifest_path)
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the frozen, replay-only modes."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=sorted(MODES))
    parser.add_argument("--purpose")
    parser.add_argument("--scenario")
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one fail-closed replay and print the JSON report; return exit status."""

    args = build_parser().parse_args(argv)
    try:
        config, _ = load_config(args.config)
        config = effective_config(config, mode=args.mode, purpose=args.purpose)
        mode = str(config["mode"])
        if mode == "production":
            raise RunnerConfigurationError("PRODUCTION_NOT_SUPPORTED")
        if mode == "simnow":
            raise RunnerConfigurationError("SIMNOW_NOT_IMPLEMENTED_FAIL_CLOSED")
        if mode == "shadow":
            raise RunnerConfigurationError("SHADOW_NOT_IMPLEMENTED_NO_NETWORK")
        report = run_replay(
            config,
            scenario=args.scenario,
            output_directory=args.output_dir,
        )
    except (OSError, RunnerConfigurationError, ValueError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
