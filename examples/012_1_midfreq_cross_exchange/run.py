"""Run the independent mid-frequency OKX/Binance perpetual strategy."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from typing import Mapping, Optional


def _load_repo_backtrader_package(script_file=None):
    """Load this checkout's Backtrader package without mixing installations."""

    repo_root = Path(__file__ if script_file is None else script_file).resolve().parents[2]
    package_root = (repo_root / "backtrader").resolve()
    package_init = package_root / "__init__.py"
    existing = sys.modules.get("backtrader")
    if existing is not None:
        try:
            existing_file = Path(existing.__file__).resolve()
            existing_paths = {
                Path(location).resolve() for location in getattr(existing, "__path__", ())
            }
        except (AttributeError, OSError, RuntimeError, TypeError):
            existing_file = None
            existing_paths = set()
        if existing_file != package_init.resolve() or package_root not in existing_paths:
            raise ImportError("backtrader is already loaded from a different checkout")
        return existing

    if any(name.startswith("backtrader.") for name in sys.modules):
        raise ImportError("backtrader submodules are already loaded without their package")
    if not package_init.is_file():
        raise ImportError("the checkout's backtrader package is unavailable")
    spec = importlib.util.spec_from_file_location(
        "backtrader",
        package_init,
        submodule_search_locations=[str(package_root)],
    )
    if spec is None or spec.loader is None:
        raise ImportError("the checkout's backtrader package cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules["backtrader"] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        for name in tuple(sys.modules):
            if name == "backtrader" or name.startswith("backtrader."):
                sys.modules.pop(name, None)
        raise
    return module


_load_repo_backtrader_package()

# These imports intentionally follow the checkout-local loader so direct-script
# execution cannot resolve Backtrader modules from an unrelated installation.
import backtrader as bt  # noqa: E402
from backtrader.brokers.hft.exchange import SimpleExchangeModel  # noqa: E402
from backtrader.brokers.mixbroker import MixBroker  # noqa: E402
from backtrader.comminfo import ComminfoFuturesPercent  # noqa: E402
from backtrader.stores.btapistore import BtApiStore  # noqa: E402
from bt_api_py import (  # noqa: E402
    CrossVenueLeg as InstrumentRule,
    FeeSchedule,
    FundingSnapshot,
    InstrumentSpec,
    coerce_funding_snapshot,
    decimal_value,
)

if __package__:
    from .strategy_candidate_approval import (
        APPROVAL_PUBLIC_KEY_SHA256,
        DemoApprovalVerificationError,
        collect_runtime_source_provenance,
        serialize_private_json_report,
        verify_demo_approval,
        write_private_json_report,
    )
else:
    from strategy_candidate_approval import (
        APPROVAL_PUBLIC_KEY_SHA256,
        DemoApprovalVerificationError,
        collect_runtime_source_provenance,
        serialize_private_json_report,
        verify_demo_approval,
        write_private_json_report,
    )
import yaml  # noqa: E402

if __package__:
    from .strategy import BasisModelQualification, BookState, CrossExchangeArbitrageStrategy
    from .strategy import MidFrequencyEngine, qualify_basis_model
    from .strategy import MidFrequencyRisk, VENUE_SYMBOLS, qualification_contract_sha256
else:
    from strategy import BasisModelQualification, BookState, CrossExchangeArbitrageStrategy
    from strategy import MidFrequencyEngine, qualify_basis_model
    from strategy import MidFrequencyRisk, VENUE_SYMBOLS, qualification_contract_sha256


HERE = Path(__file__).resolve().parent
# Self-contained working copy: the manifest, trust root and admission policy
# live beside this runner. Demo execution remains bound to the repository
# canonical manifest, including the explicit rejected-candidate override.
MANIFEST_PATH = HERE / "strategy-candidate-manifest.json"
DEMO_APPROVAL_TRUST_ROOT = HERE / "demo-approval-trust-root.pem"
REPO_CANONICAL_MANIFEST = HERE.parent / "strategy-candidate-manifest.json"
DEMO_APPROVAL_PUBLIC_KEY_SHA256 = APPROVAL_PUBLIC_KEY_SHA256
DEFAULT_CONFIG = HERE / "config.yaml"
QUALIFICATION_PATH = HERE / "qualification-v3.json"
STRATEGY_ID = "012_1_midfreq_cross_exchange"
EXCHANGES = {"okx": "OKX___SWAP", "binance": "BINANCE___SWAP"}
SCENARIOS = ("profitable", "loss", "no_edge", "partial", "unknown", "gap")
MODES = ("replay", "shadow", "paper-live", "demo")
MIDFREQ_ORDERBOOK_QUEUE_CAPACITY = 64
OPERATOR_DEMO_MANIFEST_STATUS = "RESEARCH_REJECTED_OPERATOR_DEMO_SIMULATION_ONLY"
OPERATOR_DEMO_CONDITION = "OPERATOR_ACK_REQUIRED_DEMO_SIMULATION_ONLY"
OPERATOR_PAPER_LIVE_CONDITION = "PROHIBITED_RESEARCH_REJECTED_NEW_CANDIDATE_REQUIRED"
OPERATOR_DEMO_MAX_ORDER_COUNT = 8
OPERATOR_DEMO_MAX_LEASE_SECONDS = Decimal("900")
# Only stable, locally-defined drop codes may appear in a shadow diagnostic.
# Unknown values are summarized as OTHER so vendor payloads cannot leak.
SHADOW_SAFE_DROP_REASON_CODES = frozenset(
    {
        "causal_provenance_missing_or_invalid",
        "duplicate_sequence",
        "invalid_orderbook_snapshot",
        "orderbook_dispatch_disabled",
        "orderbook_invalid_top_of_book",
        "orderbook_missing_top_of_book",
        "sequence_out_of_order",
        "store_orderbook_queue_overflow",
        "strategy_dispatch_failed",
        "strategy_dispatch_unavailable",
    }
)
# One initial read plus at most two retries; total backoff is capped at 0.2s.
STARTUP_EVIDENCE_MAX_ATTEMPTS = 3
STARTUP_EVIDENCE_RETRY_DELAY_SECONDS = 0.1
OKX_API_REGIONS = frozenset({"global", "eea", "us", "tr"})
CONSERVATIVE_TAKER_FEE = Decimal("0.0006")
FORMULA_FIXTURE_WALL_CLOCK = Decimal("2000000000")
BOUNDED_ONE_SHOT_PROBE_CAPABILITY = "run_bounded_read_only_metadata_probe"
PAPER_RISK_LEDGER_PATH = (
    Path.home() / ".bt_api_py" / "paper-ledgers" / "okx-binance-perpetual-usdt.account-risk.json"
)


class RunnerConfigurationError(ValueError):
    """Raised when runner configuration or admission inputs are invalid."""


class _TransientDemoReadinessEvidence(RunnerConfigurationError):
    """Internal marker for bounded retries of incomplete startup evidence."""


class DemoApprovalError(RunnerConfigurationError):
    """Raised when demo admission or its bounded approval lease is invalid."""


class RunnerSourceBindingError(RunnerConfigurationError):
    """The executed runner cannot be trusted to match its candidate binding."""


class ShadowOneShotProbeCapabilityError(RunnerConfigurationError):
    """The SDK cannot prove a bounded, lifecycle-owned metadata probe."""


def mode_policy(mode):
    """Return the capability flags that scope what a mode may do.

    Replay and shadow forbid fills, only demo may write through the SDK,
    and only paper-live reports hypothetical fills.  An unknown mode is
    rejected as a configuration error.
    """
    if mode not in MODES:
        raise RunnerConfigurationError(f"unsupported mode: {mode}")
    return {
        "network": mode != "replay",
        "sdk_writes": mode == "demo",
        "hypothetical_fills": mode == "paper-live",
        "fills_forbidden": mode in {"replay", "shadow"},
    }


def _canonical_hash(value) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_canonical_json_default,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_json_default(value):
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


BUSINESS_SUMMARY_VOLATILE_FIELDS = frozenset(
    {
        "business_summary",
        "business_summary_hash",
        # The generic observer envelope carries a per-run id, lifecycle
        # timestamps and callback telemetry.  Operators still receive it in
        # the complete report, but it is not an input to replay economics.
        "trade_logger",
    }
)


def business_summary(report: Mapping[str, object]) -> dict[str, object]:
    """Return the deterministic business projection of a runner report.

    ``TradeLogger`` is intentionally retained in the complete output for
    operational diagnostics.  Its lifecycle metadata is not deterministic
    across otherwise equivalent replays, so the projection omits it.
    """

    if not isinstance(report, Mapping):
        raise RunnerConfigurationError("report must be a mapping")
    return {
        key: value for key, value in report.items() if key not in BUSINESS_SUMMARY_VOLATILE_FIELDS
    }


def business_summary_hash(report: Mapping[str, object]) -> str:
    """Hash the deterministic business projection, excluding observer telemetry."""

    return _canonical_hash(business_summary(report))


def _attach_business_summary(report: dict[str, object]) -> None:
    """Attach an inspectable projection and its hash after report finalization."""

    projection = business_summary(report)
    report["business_summary"] = projection
    report["business_summary_hash"] = _canonical_hash(projection)


def _file_sha256(path: Path, label: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise RunnerConfigurationError(f"{label} is unavailable") from exc


def load_config(path: Path = DEFAULT_CONFIG):
    """Load and validate the candidate-bound YAML configuration.

    Rejects unknown or missing top-level fields, wrong schema versions,
    venues other than the configured perpetual contracts, and invalid
    OKX API regions.  Returns the parsed mapping with a normalized
    ``okx_api_region`` entry.
    """
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    required = {
        "schema_version",
        "strategy_id",
        "venues",
        "observation",
        "funding",
        "strategy_params",
    }
    if set(config) - (required | {"mode", "run_timeout_seconds", "okx_api_region"}):
        raise RunnerConfigurationError("configuration contains unknown top-level fields")
    if not required.issubset(config) or config["strategy_id"] != STRATEGY_ID:
        raise RunnerConfigurationError("configuration does not describe this strategy")
    if config.get("schema_version") != 2:
        raise RunnerConfigurationError("configuration schema_version must be 2")
    if "mode" in config:
        mode_policy(config["mode"])
    if config["venues"] != VENUE_SYMBOLS:
        raise RunnerConfigurationError("only the configured perpetual contracts are supported")
    api_region = config.get("okx_api_region", "global")
    if not isinstance(api_region, str) or api_region not in OKX_API_REGIONS:
        raise RunnerConfigurationError("okx_api_region must be global, eea, us or tr")
    config["okx_api_region"] = api_region
    return config


def load_candidate(manifest_path: Path = MANIFEST_PATH):
    """Load this strategy's candidate row and verify its content-addressed binding.

    Requires exactly one matching candidate whose fingerprint, runner,
    strategy and config file hashes match the manifest, and whose content
    paths stay inside the example directory.  Returns the manifest, the
    candidate row and the resolved manifest path; any mismatch fails
    closed before execution.
    """
    path = Path(manifest_path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    matches = [
        row for row in manifest.get("candidates", []) if row.get("strategy_id") == STRATEGY_ID
    ]
    if len(matches) != 1:
        raise RunnerConfigurationError("manifest must contain exactly one strategy candidate")
    candidate = matches[0]
    payload = {
        key: value
        for key, value in candidate.items()
        if key not in {"candidate_sha256", "demo_approval"}
    }
    if candidate.get("candidate_sha256") != _canonical_hash(payload):
        raise RunnerConfigurationError("candidate fingerprint does not match manifest content")
    resolved = (path.parent / candidate["resolved_example_path"]).resolve()
    entrypoint = (resolved / candidate["entrypoint"]).resolve()
    strategy_path = (resolved / candidate["strategy_module"]).resolve()
    config_path = (resolved / "config.yaml").resolve()
    if resolved != HERE or entrypoint != Path(__file__).resolve():
        raise RunnerConfigurationError("manifest resolves to a different example")
    if strategy_path.parent != resolved or config_path.parent != resolved:
        raise RunnerConfigurationError("manifest content paths escape the example directory")
    if _file_sha256(entrypoint, "runner source") != candidate.get("runner_sha256"):
        raise RunnerSourceBindingError("runner source fingerprint mismatch")
    if _file_sha256(strategy_path, "strategy source") != candidate.get("strategy_sha256"):
        raise RunnerConfigurationError("strategy source fingerprint mismatch")
    if _file_sha256(config_path, "candidate config") != candidate.get("config_sha256"):
        raise RunnerConfigurationError("candidate config fingerprint mismatch")
    return manifest, candidate, path


def _validate_network_admission(
    manifest, candidate, mode, preflight, config, allow_rejected_demo_simulation=False
):
    """Apply the manifest and config mode contract before any Store is created."""

    if allow_rejected_demo_simulation and mode != "demo":
        raise RunnerConfigurationError(
            "rejected-candidate simulation acknowledgement is only valid for demo mode"
        )
    if preflight and mode != "demo":
        raise RunnerConfigurationError("preflight is only valid for demo mode")
    manifest_status = manifest.get("manifest_status")
    if not isinstance(manifest_status, str) or not manifest_status.strip():
        raise RunnerConfigurationError("manifest_status is missing")
    configured_mode = config.get("mode")
    if configured_mode is not None and configured_mode != mode:
        raise RunnerConfigurationError("configuration mode does not match the requested mode")
    allowed_modes = candidate.get("allowed_modes")
    conditional_modes = candidate.get("conditional_modes")
    if (
        not isinstance(allowed_modes, list)
        or any(not isinstance(item, str) or item not in MODES for item in allowed_modes)
        or len(set(allowed_modes)) != len(allowed_modes)
    ):
        raise RunnerConfigurationError("candidate allowed_modes is invalid")
    if not isinstance(conditional_modes, Mapping) or any(
        key not in MODES or not isinstance(value, str) or not value
        for key, value in conditional_modes.items()
    ):
        raise RunnerConfigurationError("candidate conditional_modes is invalid")

    if preflight:
        return {
            "manifest_status": manifest_status,
            "candidate_mode_status": conditional_modes.get("demo", "NOT_DECLARED"),
            "research_status": candidate.get("research_status"),
            "execution_admitted": False,
            "preflight_only": True,
            "operator_override": False,
        }

    operator_override = False
    if allow_rejected_demo_simulation:
        operator_override = (
            mode == "demo"
            and manifest_status == OPERATOR_DEMO_MANIFEST_STATUS
            and candidate.get("research_status") == "RESEARCH_REJECTED"
            and set(allowed_modes) == {"replay", "shadow", "demo"}
            and conditional_modes
            == {
                "paper-live": OPERATOR_PAPER_LIVE_CONDITION,
                "demo": OPERATOR_DEMO_CONDITION,
            }
        )
        if not operator_override:
            raise DemoApprovalError(
                "operator acknowledgement requires the explicit rejected-candidate demo-simulation manifest"
            )

    error_cls = DemoApprovalError if mode == "demo" else RunnerConfigurationError
    if (
        mode in {"paper-live", "demo"}
        and candidate.get("research_status") != "PASS"
        and not operator_override
    ):
        raise error_cls(f"{mode} requires a PASS research candidate")
    if mode not in allowed_modes:
        condition = conditional_modes.get(mode, "NOT_ALLOWED")
        raise error_cls(f"candidate mode {mode} is not admitted: {condition}")
    condition = conditional_modes.get(mode)
    if condition is not None and condition.upper().startswith("PROHIBITED"):
        raise error_cls(f"candidate mode {mode} is prohibited: {condition}")
    if mode == "paper-live" and manifest_status not in {
        "PAPER_LIVE_APPROVED",
        "DEMO_APPROVED",
    }:
        raise RunnerConfigurationError("manifest_status does not authorize paper-live execution")
    if mode == "demo" and manifest_status != "DEMO_APPROVED" and not operator_override:
        raise DemoApprovalError("manifest_status does not authorize demo execution")
    admission = {
        "manifest_status": manifest_status,
        "candidate_mode_status": condition or "ALLOWED",
        "research_status": candidate.get("research_status"),
        "execution_admitted": True,
        "preflight_only": False,
        "operator_override": operator_override,
    }
    shadow_diagnostic_manifest = (
        mode == "shadow"
        and not preflight
        and candidate.get("strategy_id") == STRATEGY_ID
        and manifest_status == OPERATOR_DEMO_MANIFEST_STATUS
        and candidate.get("research_status") == "RESEARCH_REJECTED"
        and set(allowed_modes) == {"replay", "shadow", "demo"}
        and conditional_modes
        == {
            "paper-live": OPERATOR_PAPER_LIVE_CONDITION,
            "demo": OPERATOR_DEMO_CONDITION,
        }
    )
    if shadow_diagnostic_manifest:
        admission["read_only_calibration_contract_diagnostic"] = {
            "admission_status": "ADMITTED_READ_ONLY_DIAGNOSTIC",
            "execution_mode": "shadow",
            "scope": "ORDERBOOK_HEALTH_ONLY_ZERO_WRITE",
            "model_admission": "SKIPPED",
            "calibration_contract_compatibility": "NOT_EVALUATED",
            "research_status": "RESEARCH_REJECTED",
            "oos_or_demo_approval": False,
            "research_qualification": False,
            "operator_demo_authorization": False,
            "paper_live_authorization": False,
            "execution_enabled": False,
            "sdk_writes_forbidden": True,
            "fills_forbidden": True,
            "profitability_claim": "NONE_READ_ONLY_SHADOW_DIAGNOSTIC",
        }
    return admission


def _operator_demo_calibration_contract_mismatch_enabled(mode, admission):
    """Allow the calibration mismatch only on the explicitly admitted rejected demo path."""

    return bool(
        mode == "demo"
        and isinstance(admission, Mapping)
        and admission.get("operator_override") is True
        and admission.get("research_status") == "RESEARCH_REJECTED"
    )


def _shadow_read_only_calibration_contract_diagnostic_enabled(mode, admission):
    """Recognize only the exact rejected-candidate, zero-write shadow admission."""

    if not isinstance(admission, Mapping):
        return False
    evidence = admission.get("read_only_calibration_contract_diagnostic")
    return bool(
        mode == "shadow"
        and admission.get("execution_admitted") is True
        and admission.get("preflight_only") is False
        and admission.get("operator_override") is False
        and admission.get("manifest_status") == OPERATOR_DEMO_MANIFEST_STATUS
        and admission.get("research_status") == "RESEARCH_REJECTED"
        and isinstance(evidence, Mapping)
        and evidence.get("admission_status") == "ADMITTED_READ_ONLY_DIAGNOSTIC"
        and evidence.get("execution_mode") == "shadow"
        and evidence.get("scope") == "ORDERBOOK_HEALTH_ONLY_ZERO_WRITE"
        and evidence.get("model_admission") == "SKIPPED"
        and evidence.get("calibration_contract_compatibility") == "NOT_EVALUATED"
        and evidence.get("research_status") == "RESEARCH_REJECTED"
        and evidence.get("oos_or_demo_approval") is False
        and evidence.get("research_qualification") is False
        and evidence.get("operator_demo_authorization") is False
        and evidence.get("paper_live_authorization") is False
        and evidence.get("execution_enabled") is False
        and evidence.get("sdk_writes_forbidden") is True
        and evidence.get("fills_forbidden") is True
        and evidence.get("profitability_claim") == "NONE_READ_ONLY_SHADOW_DIAGNOSTIC"
    )


def _read_only_shadow_calibration_diagnostic_evidence():
    """Describe the deliberately skipped model admission without a research claim."""

    return {
        "status": "READ_ONLY_SHADOW_CALIBRATION_CONTRACT_DIAGNOSTIC",
        "artifact_verification": "NOT_RUN",
        "reason": "MODEL_ADMISSION_SKIPPED_FOR_ORDERBOOK_HEALTH_DIAGNOSTIC",
        "qualification_scope": "ORDERBOOK_HEALTH_ONLY_ZERO_WRITE",
        "calibration_contract_compatibility": "NOT_EVALUATED",
        "oos_or_demo_approval": False,
        "research_qualification": False,
        "operator_demo_authorization": False,
        "paper_live_authorization": False,
        "sdk_writes_forbidden": True,
        "fills_forbidden": True,
        "profitability_claim": "NONE_READ_ONLY_SHADOW_DIAGNOSTIC",
    }


def _shadow_orderbook_stream_health_summary(stream_health):
    """Project only bounded, non-sensitive Store orderbook counters for shadow reports."""

    def safe_count(value):
        return value if type(value) is int and value >= 0 else None

    def safe_reason(value):
        if not isinstance(value, str) or not value:
            return None
        return value if value in SHADOW_SAFE_DROP_REASON_CODES else "OTHER"

    if not isinstance(stream_health, Mapping):
        return {"status": "UNAVAILABLE", "by_symbol": {}}

    by_symbol = {}
    complete = True
    for symbol in sorted(VENUE_SYMBOLS.values()):
        row = stream_health.get(symbol)
        if not isinstance(row, Mapping):
            complete = False
            by_symbol[symbol] = {
                "orderbook_ingress": None,
                "orderbook_coalesced": None,
                "orderbook_dropped": None,
                "orderbook_delivered": None,
                "orderbook_inflight": None,
                "orderbook_queue_depth": None,
                "stale": None,
                "orderbook_conservation": None,
                "latest_drop_reason": None,
            }
            continue
        last_drop_reason = row.get("last_drop_reason")
        if not last_drop_reason:
            drop_records = row.get("market_drop_records")
            if isinstance(drop_records, list) and drop_records:
                latest = drop_records[-1]
                if isinstance(latest, Mapping):
                    last_drop_reason = latest.get("reason")
        by_symbol[symbol] = {
            "orderbook_ingress": safe_count(row.get("book_ingress")),
            "orderbook_coalesced": safe_count(row.get("book_coalesced")),
            "orderbook_dropped": safe_count(row.get("book_dropped")),
            "orderbook_delivered": safe_count(row.get("book_strategy_delivered")),
            "orderbook_inflight": safe_count(row.get("book_feed_inflight")),
            "orderbook_queue_depth": safe_count(row.get("book_queue_depth")),
            "stale": row.get("stale") if type(row.get("stale")) is bool else None,
            "orderbook_conservation": (
                row.get("book_conservation")
                if type(row.get("book_conservation")) is bool
                else None
            ),
            "latest_drop_reason": safe_reason(last_drop_reason),
        }
    return {"status": "AVAILABLE" if complete else "INCOMPLETE", "by_symbol": by_symbol}


def _bounded_requested_duration(duration, config):
    requested = decimal_value(duration, "duration")
    configured = decimal_value(config.get("run_timeout_seconds"), "run_timeout_seconds")
    if requested <= 0 or configured <= 0:
        raise RunnerConfigurationError("duration bounds must be finite and positive")
    if requested > configured:
        raise RunnerConfigurationError("duration exceeds the candidate-bound run timeout")
    return requested


def _approval_lease(receipt, requested_duration, risk, shutdown_seconds, now=None):
    constraints = receipt.get("constraints")
    if not isinstance(constraints, Mapping):
        raise DemoApprovalError("demo approval constraints are missing")
    maximum_duration = decimal_value(
        constraints.get("maximum_duration_seconds"), "approval maximum duration"
    )
    maximum_quantity = decimal_value(
        constraints.get("maximum_quantity_base"), "approval maximum quantity"
    )
    maximum_order_count = constraints.get("maximum_order_count")
    if (
        maximum_duration <= 0
        or maximum_quantity <= 0
        or type(maximum_order_count) is not int
        or maximum_order_count <= 0
    ):
        raise DemoApprovalError("demo approval constraints are invalid")
    if requested_duration > maximum_duration:
        raise DemoApprovalError("duration exceeds the signed demo approval limit")
    if risk.quantity_base > maximum_quantity:
        raise DemoApprovalError("quantity exceeds the signed demo approval limit")
    expires_raw = receipt.get("expires_at")
    try:
        expires_at = datetime.fromisoformat(str(expires_raw)[:-1] + "+00:00")
    except (TypeError, ValueError) as exc:
        raise DemoApprovalError("demo approval expiry is invalid") from exc
    if not isinstance(expires_raw, str) or not expires_raw.endswith("Z"):
        raise DemoApprovalError("demo approval expiry is invalid")
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        raise DemoApprovalError("demo approval clock must be timezone-aware")
    remaining = decimal_value(
        (expires_at - checked_at.astimezone(timezone.utc)).total_seconds(),
        "approval remaining duration",
    )
    if requested_duration > remaining or remaining <= shutdown_seconds:
        raise DemoApprovalError("demo approval expires before the requested run can shut down")
    return {
        "expires_at": expires_raw,
        "maximum_duration_seconds": str(maximum_duration),
        "maximum_order_count": maximum_order_count,
        "maximum_quantity_base": str(maximum_quantity),
        "remaining_seconds_at_check": str(remaining),
    }


def _operator_demo_lease(requested_duration, risk, shutdown_seconds, config, now=None):
    """Create a one-run local lease bounded by config, risk, and a short TTL."""

    requested = decimal_value(requested_duration, "duration")
    configured = decimal_value(config.get("run_timeout_seconds"), "run_timeout_seconds")
    shutdown = decimal_value(shutdown_seconds, "shutdown_buffer_seconds")
    maximum_quantity = decimal_value(risk.quantity_base, "maximum operator demo quantity")
    if requested <= 0 or configured <= 0 or shutdown <= 0 or maximum_quantity <= 0:
        raise DemoApprovalError("operator demo lease bounds must be finite and positive")
    if requested > configured:
        raise DemoApprovalError("duration exceeds the candidate-bound run timeout")
    lease_duration = requested + shutdown
    if lease_duration > OPERATOR_DEMO_MAX_LEASE_SECONDS:
        raise DemoApprovalError("operator demo lease exceeds the short-lived lease limit")
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        raise DemoApprovalError("operator demo lease clock must be timezone-aware")
    expires_at = checked_at.astimezone(timezone.utc) + timedelta(seconds=float(lease_duration))
    return {
        "expires_at": expires_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "maximum_duration_seconds": str(requested),
        "maximum_order_count": OPERATOR_DEMO_MAX_ORDER_COUNT,
        "maximum_quantity_base": str(maximum_quantity),
        "remaining_seconds_at_check": str(lease_duration),
        "lease_type": "OPERATOR_ACKNOWLEDGED_LOCAL_DEMO_SIMULATION",
        "signed_receipt_verified": False,
    }


def require_demo_approval(candidate, manifest_path: Path):
    """Verify the signed demo approval receipt against the pinned trust root.

    Collects runtime source provenance and delegates to the shared
    approval verifier; verification failures are re-raised as
    ``DemoApprovalError`` so demo admission stays fail-closed.
    """
    try:
        runtime_source = collect_runtime_source_provenance()
        return verify_demo_approval(
            candidate=candidate,
            manifest_path=manifest_path,
            canonical_manifest_path=REPO_CANONICAL_MANIFEST,
            trust_root_path=DEMO_APPROVAL_TRUST_ROOT,
            expected_strategy_id=STRATEGY_ID,
            runtime_source=runtime_source,
            expected_public_key_sha256=DEMO_APPROVAL_PUBLIC_KEY_SHA256,
        )
    except DemoApprovalVerificationError as exc:
        raise DemoApprovalError(str(exc)) from exc


def risk_from_config(config) -> MidFrequencyRisk:
    """Build the risk parameters from config, rejecting unknown fields."""
    allowed = set(asdict(MidFrequencyRisk()))
    params = dict(config["strategy_params"])
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise RunnerConfigurationError("unknown strategy parameters: " + ", ".join(unknown))
    return MidFrequencyRisk(**params)


def funding_settings_from_config(config):
    """Validate and return the funding ledger refresh settings as Decimals.

    Requires exactly the configured fields with ``0 < refresh < max_age``
    and a positive exit window; a missing or inconsistent funding
    configuration fails closed.
    """
    values = config.get("funding")
    allowed = {
        "refresh_interval_seconds",
        "max_age_seconds",
        "exit_window_seconds",
    }
    if not isinstance(values, Mapping) or set(values) != allowed:
        raise RunnerConfigurationError("funding configuration fields are incomplete or unknown")
    refresh = decimal_value(values["refresh_interval_seconds"], "funding_refresh_interval")
    max_age = decimal_value(values["max_age_seconds"], "funding_max_age")
    exit_window = decimal_value(values["exit_window_seconds"], "funding_exit_window")
    if not 0 < refresh < max_age or exit_window <= 0:
        raise RunnerConfigurationError("funding refresh, age, or exit window is invalid")
    return {
        "refresh_interval_seconds": refresh,
        "max_age_seconds": max_age,
        "exit_window_seconds": exit_window,
    }


def required_observation_duration(config, risk: MidFrequencyRisk) -> Decimal:
    """Validate the observation block and return the minimum run duration.

    The requirement is the statistical window plus the risk maximum
    holding time plus the shutdown buffer, in seconds.  The exact field
    set, positive durations and the boolean settlement flag are enforced
    before the value is returned.
    """
    observation = config["observation"]
    allowed = {
        "minimum_statistical_seconds",
        "shutdown_buffer_seconds",
        "require_funding_settlement",
    }
    if not isinstance(observation, Mapping) or set(observation) != allowed:
        raise RunnerConfigurationError("observation configuration fields are incomplete or unknown")
    try:
        statistical = decimal_value(observation["minimum_statistical_seconds"])
        shutdown = decimal_value(observation["shutdown_buffer_seconds"])
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise RunnerConfigurationError("observation durations are invalid") from exc
    if statistical <= 0 or shutdown < 0:
        raise RunnerConfigurationError("observation durations are invalid")
    if type(observation["require_funding_settlement"]) is not bool:
        raise RunnerConfigurationError("require_funding_settlement must be a boolean")
    return statistical + risk.maximum_holding_seconds + shutdown


def validate_duration(
    duration,
    config,
    risk,
    *,
    next_funding_times=(),
    active_observation_seconds=None,
):
    """Enforce the duration gate and return its report fields.

    The duration must cover the required observation window and, when
    ``require_funding_settlement`` is set, the active horizon must reach
    the next funding settlement on every venue with a refresh margin to
    spare.  Returns the gate summary recorded in the run report.
    """
    value = decimal_value(duration, "duration")
    required = required_observation_duration(config, risk)
    if value < required:
        raise RunnerConfigurationError(
            f"duration {value}s is below required observation duration {required}s"
        )
    funding_required = config["observation"]["require_funding_settlement"]
    future = [decimal_value(item) for item in next_funding_times if item is not None]
    now = decimal_value(time.time())
    active_horizon = (
        value
        if active_observation_seconds is None
        else decimal_value(active_observation_seconds, "active_observation_seconds")
    )
    if active_horizon <= 0 or active_horizon > value:
        raise RunnerConfigurationError("active observation duration is invalid")
    settlement_margin = decimal_value(
        config["funding"]["refresh_interval_seconds"],
        "funding_settlement_observation_margin",
    )
    funding_cutoff = now + active_horizon - settlement_margin
    if funding_required and (len(future) != len(VENUE_SYMBOLS) or max(future) >= funding_cutoff):
        raise RunnerConfigurationError("duration does not cover a required funding settlement")
    return {
        "requested_seconds": str(value),
        "required_seconds": str(required),
        "maximum_holding_seconds": str(risk.maximum_holding_seconds),
        "funding_horizon_seconds": str(active_horizon),
        "funding_observation_margin_seconds": str(settlement_margin),
        "funding_validation": "IN_SCOPE" if funding_required else "NOT_RUN",
    }


def replay_rules() -> Mapping[str, InstrumentRule]:
    """Return the conservative per-venue instrument rules for replay fixtures."""
    return {
        "okx": InstrumentRule(
            multiplier=Decimal("0.01"),
            quantity_step=Decimal("0.01"),
            minimum_quantity=Decimal("0.01"),
            minimum_notional=Decimal(0),
            price_tick=Decimal("0.1"),
            taker_fee=CONSERVATIVE_TAKER_FEE,
        ),
        "binance": InstrumentRule(
            multiplier=Decimal(1),
            quantity_step=Decimal("0.001"),
            minimum_quantity=Decimal("0.001"),
            minimum_notional=Decimal("50"),
            price_tick=Decimal("0.1"),
            taker_fee=CONSERVATIVE_TAKER_FEE,
        ),
    }


def _book(
    venue,
    bid,
    ask,
    timestamp,
    sequence,
    *,
    previous=None,
    snapshot_or_delta="snapshot",
    continuity_status="snapshot",
    recovery=False,
):
    depth = ((decimal_value(bid), Decimal("0.04")), (decimal_value(bid) - 1, Decimal("0.04")))
    asks = ((decimal_value(ask), Decimal("0.04")), (decimal_value(ask) + 1, Decimal("0.04")))
    return BookState(
        venue=venue,
        bids=depth,
        asks=asks,
        exchange_time=decimal_value(timestamp),
        receive_time=decimal_value(timestamp),
        sequence=sequence,
        previous_sequence=previous,
        snapshot_or_delta=snapshot_or_delta,
        continuity_status=continuity_status,
        recovery_snapshot=recovery,
    )


def replay_events(scenario, risk: MidFrequencyRisk):
    """Yield synthetic per-venue order books for a deterministic replay scenario.

    Eligible scenarios widen the Binance quotes once the qualification
    sample count is met, and ``gap`` injects a sequence break so
    continuity rejection can be exercised.  Everything else is emitted
    with monotonic per-venue sequences.
    """
    if scenario not in SCENARIOS:
        raise RunnerConfigurationError("unsupported replay scenario")
    sequence = {"okx": 0, "binance": 0}
    count = risk.minimum_samples + 8
    for index in range(count):
        timestamp = Decimal(index)
        wide = (
            scenario in {"profitable", "loss", "partial", "unknown"}
            and index >= risk.minimum_samples
        )
        oscillation = Decimal((index % 5) - 2) / Decimal(2)
        binance_bid = Decimal("60400") if wide else Decimal("60000") + oscillation
        binance_ask = binance_bid + Decimal(1)
        for venue, bid, ask in (
            ("okx", Decimal("59999"), Decimal("60000")),
            ("binance", binance_bid, binance_ask),
        ):
            previous = sequence[venue] or None
            sequence[venue] += 1
            if scenario == "gap" and index == risk.minimum_samples and venue == "binance":
                sequence[venue] += 1
                yield _book(
                    venue,
                    bid,
                    ask,
                    timestamp,
                    sequence[venue],
                    previous=previous - 1,
                    snapshot_or_delta="delta",
                    continuity_status="gap",
                )
                continue
            yield _book(
                venue,
                bid,
                ask,
                timestamp,
                sequence[venue],
                previous=previous,
            )


def _metric_report(gross: Decimal, costs: Decimal, trades: int):
    net = gross - costs
    losses = min(net, Decimal(0))
    return {
        "gross_pnl": str(gross),
        "total_cost": str(costs),
        "net_pnl": str(net),
        "maximum_drawdown": str(abs(losses)),
        "return_drawdown_ratio": None if losses == 0 else str(net / abs(losses)),
        "win_rate": str(Decimal(1) if trades and net > 0 else Decimal(0)),
        "expectancy_per_trade": str(net / trades if trades else Decimal(0)),
        "trade_count": trades,
        "cost_to_gross_ratio": None if gross == 0 else str(costs / abs(gross)),
        "latency_ms": {"p50": 0, "p95": 0, "p99": 0, "samples": trades},
        "markouts_quote": {"10": [], "50": [], "100": [], "500": []},
        "unhedged_duration_seconds": {"p50": 0, "p95": 0, "p99": 0, "max": 0},
    }


def _formula_fixture_metrics():
    """Return explicit non-execution metrics for deterministic formula fixtures."""
    return {
        "gross_pnl": None,
        "total_cost": None,
        "net_pnl": None,
        "maximum_drawdown": None,
        "return_drawdown_ratio": None,
        "win_rate": None,
        "expectancy_per_trade": None,
        "trade_count": 0,
        "cost_to_gross_ratio": None,
        "latency_ms": {"p50": None, "p95": None, "p99": None, "samples": 0},
        "markouts_quote": {"10": [], "50": [], "100": [], "500": []},
        "unhedged_duration_seconds": {
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        },
    }


def _formula_fixture_qualification(rules, risk: MidFrequencyRisk):
    """Build fully bound per-direction qualifications for formula checks only."""

    sample_count = max(risk.minimum_qualification_samples + 60, 180)
    innovations = (
        Decimal("1"),
        Decimal("-0.7"),
        Decimal("0.2"),
        Decimal("-0.4"),
        Decimal("0.8"),
        Decimal("-0.2"),
    )
    value = Decimal(0)
    samples = []
    for index in range(sample_count):
        value = Decimal("0.45") * value + innovations[index % len(innovations)]
        samples.append(value)
    # Formula replay is a deterministic fixture.  Its qualification window
    # must therefore use the same synthetic wall clock as the engine rather
    # than the process clock captured at each invocation.
    now = FORMULA_FIXTURE_WALL_CLOCK
    result = {}
    for buy_venue, sell_venue in (("okx", "binance"), ("binance", "okx")):
        result[(buy_venue, sell_venue)] = qualify_basis_model(
            samples,
            sample_interval_seconds=Decimal(1),
            maximum_half_life_seconds=risk.maximum_half_life_seconds,
            valid_from_epoch=now - 1,
            valid_until_epoch=now + 3600,
            buy_venue=buy_venue,
            sell_venue=sell_venue,
            minimum_samples=risk.minimum_qualification_samples,
            source_data_sha256="0" * 64,
            provenance="synthetic formula fixture; excluded from research evidence",
            qualification_contract_sha256=qualification_contract_sha256(
                rules, risk, buy_venue, sell_venue
            ),
        )
    return result


def run_replay(
    scenario="profitable",
    config_path: Path = DEFAULT_CONFIG,
    manifest_path: Path = MANIFEST_PATH,
):
    """Run the offline formula-fixture check for a replay scenario.

    Verifies the config binding to the selected candidate, then drives
    the mid-frequency engine over synthetic books on a fixed wall clock.
    The returned report's status flips to ``FORMULA_CHECK_FAIL`` when a
    fixture branch misbehaves (no-edge intent, undetected sequence gap,
    or a mishandled unknown execution).  No orders are submitted and no
    network access occurs.
    """
    config = load_config(config_path)
    _, candidate, _ = load_candidate(manifest_path)
    if _file_sha256(config_path, "run config") != candidate["config_sha256"]:
        raise RunnerConfigurationError("run config is not bound to the selected candidate")
    risk = risk_from_config(config)
    rules = replay_rules()
    fixture_qualification = _formula_fixture_qualification(rules, risk)
    engine = MidFrequencyEngine(
        rules,
        risk,
        fixture_qualification,
        wall_clock=lambda: FORMULA_FIXTURE_WALL_CLOCK,
    )
    intent = None
    for book in replay_events(scenario, risk):
        engine.update_book(book)
        if book.venue != "binance":
            continue
        decision = engine.evaluate(book.receive_time)
        if decision is not None and intent is None:
            intent = decision
            if scenario == "unknown":
                engine.reject("unknown_execution")
    final_state = "FORMULA_UNKNOWN_BRANCH" if scenario == "unknown" else "NO_EXECUTION"
    report = {
        "status": "FORMULA_CHECK_PASS",
        "strategy_id": STRATEGY_ID,
        "mode": "replay",
        "scenario": scenario,
        "evidence_level": "R0_FORMULA_FIXTURE",
        "research_status": candidate["research_status"],
        "candidate_sha256": candidate["candidate_sha256"],
        "config_sha256": candidate["config_sha256"],
        "normalized_config_sha256": _canonical_hash(config),
        "strategy_sha256": candidate["strategy_sha256"],
        "configuration": config,
        "orders_submitted": 0,
        "fills": 0,
        "execution_status": "NOT_RUN",
        "partial_fill_ratio": None,
        "unknown_execution": False,
        "synthetic_branch": scenario,
        "final_state": final_state,
        "cost_breakdown": intent.cost.as_dict() if intent else None,
        "fee_source": dict.fromkeys(VENUE_SYMBOLS, "conservative_bound"),
        "fee_rate_per_fill": {venue: str(rule.taker_fee) for venue, rule in engine.rules.items()},
        "reject_reasons": dict(engine.reject_reasons),
        "engine": engine.snapshot(),
        "profitability_claim": "NONE_SYNTHETIC_FIXTURE_ONLY",
    }
    report.update(_formula_fixture_metrics())
    if scenario == "no_edge" and intent is not None:
        report["status"] = "FORMULA_CHECK_FAIL"
    if scenario == "gap" and not engine.reject_reasons["sequence_gap"]:
        report["status"] = "FORMULA_CHECK_FAIL"
    if scenario == "unknown" and final_state != "FORMULA_UNKNOWN_BRANCH":
        report["status"] = "FORMULA_CHECK_FAIL"
    _attach_business_summary(report)
    return report


def _load_demo_credentials(path: Path):
    from dotenv import dotenv_values

    names = (
        "OKX_DEMO_API_KEY",
        "OKX_DEMO_SECRET",
        "OKX_DEMO_PASSPHRASE",
        "BINANCE_DEMO_API_KEY",
        "BINANCE_DEMO_SECRET",
    )
    values = dotenv_values(path) if path.is_file() else {}
    result = {name: os.environ.get(name) or values.get(name) or "" for name in names}
    missing = [name for name, value in result.items() if not str(value).strip()]
    if missing:
        raise RunnerConfigurationError("missing demo credential variables: " + ", ".join(missing))
    return result


def _exchange_kwargs(mode, credentials=None, okx_api_region="global"):
    environment = "demo" if mode == "demo" else "production"
    result = {exchange: {"environment": environment} for exchange in EXCHANGES.values()}
    if okx_api_region not in OKX_API_REGIONS:
        raise RunnerConfigurationError("okx_api_region must be global, eea, us or tr")
    if environment == "demo" and okx_api_region == "tr":
        raise RunnerConfigurationError("OKX TR demo endpoints are not verified")
    result[EXCHANGES["okx"]]["api_region"] = okx_api_region
    if credentials:
        result[EXCHANGES["okx"]].update(
            public_key=credentials["OKX_DEMO_API_KEY"],
            private_key=credentials["OKX_DEMO_SECRET"],
            passphrase=credentials["OKX_DEMO_PASSPHRASE"],
        )
        result[EXCHANGES["binance"]].update(
            public_key=credentials["BINANCE_DEMO_API_KEY"],
            private_key=credentials["BINANCE_DEMO_SECRET"],
        )
    return result


def build_store(
    mode,
    env_file=HERE / ".env",
    risk=None,
    funding_settings=None,
    okx_api_region="global",
):
    """Build the ``BtApiStore`` for a network mode.

    Demo mode loads credentials, requires account risk and demo
    environments, and rejects the unverified OKX TR demo endpoints;
    shadow and paper-live stay read-only against production.  Funding
    ledger refresh bounds come from the candidate settings.
    """
    credentials = _load_demo_credentials(Path(env_file)) if mode == "demo" else None
    risk = risk or MidFrequencyRisk()
    funding_settings = funding_settings or {
        "refresh_interval_seconds": Decimal("5"),
        "max_age_seconds": Decimal("30"),
        "exit_window_seconds": Decimal("10"),
    }
    execution = {
        "market_data_only": mode != "demo",
        "account_currency": "USDT",
        "required_environments": {
            EXCHANGES[v]: "demo" if mode == "demo" else "production" for v in VENUE_SYMBOLS
        },
        "strategy_id": STRATEGY_ID,
        "account_maximum_loss_bps": str(risk.account_maximum_loss_bps),
    }
    return BtApiStore(
        provider="btapi",
        backend="direct",
        config={
            "exchange_kwargs": _exchange_kwargs(mode, credentials, okx_api_region),
            "symbol_routes": {VENUE_SYMBOLS[v]: EXCHANGES[v] for v in VENUE_SYMBOLS},
            **execution,
            "require_account_risk": mode == "demo",
            # Keep a bounded direct-feed backlog and coalesce complete market
            # snapshots before Store queueing; this is transport handling only,
            # not local order matching or fill simulation.
            "book_queue_size": MIDFREQ_ORDERBOOK_QUEUE_CAPACITY,
            "coalesce_market_snapshots": ("orderbook",),
            "funding_refresh_interval_seconds": str(funding_settings["refresh_interval_seconds"]),
            "funding_max_age_seconds": str(funding_settings["max_age_seconds"]),
        },
    )


def _require_typed_contract(value, expected_type, label):
    if not isinstance(value, expected_type):
        raise RunnerConfigurationError(f"{label} must be a public SDK contract")
    if value.available is not True:
        raise RunnerConfigurationError(f"{label} is unavailable")
    if value.freshness.stale:
        raise RunnerConfigurationError(f"{label} is stale")
    return value


def _rules_from_store(store, mode):
    if mode not in {"shadow", "paper-live", "demo"}:
        raise RunnerConfigurationError("instrument rules require a network mode")
    rules = {}
    fee_sources = {}
    for venue, symbol in VENUE_SYMBOLS.items():
        label = f"{venue} InstrumentSpec"
        instrument = _require_typed_contract(
            store.get_typed_instrument_spec(symbol), InstrumentSpec, label
        )
        if mode == "demo":
            fee_label = f"{venue} account FeeSchedule"
            fees = _require_typed_contract(
                store.get_typed_fee_schedule(symbol), FeeSchedule, fee_label
            )
            if not fees.account_id or fees.taker_rate is None:
                raise RunnerConfigurationError(f"{fee_label} is incomplete")
            fee = fees
            fee_sources[venue] = f"account_fee_schedule:{fees.source}"
        else:
            fee = CONSERVATIVE_TAKER_FEE
            fee_sources[venue] = "conservative_bound"
        try:
            rules[venue] = InstrumentRule.from_sdk_contracts(instrument, fee)
        except ValueError as exc:
            raise RunnerConfigurationError(f"{label} contains an unsafe value") from exc
    return rules, fee_sources


def _require_bounded_one_shot_probe(store):
    """Require the SDK-owned operation that bounds its full read-only lifecycle.

    ``BtApiStore`` currently exposes individual synchronous metadata reads but
    no timeout/cancellation contract for them.  A runner-side thread timeout
    could leave an active Store behind, so a zero-duration probe is admitted
    only through this atomic, SDK-owned capability.
    """

    probe = getattr(store, BOUNDED_ONE_SHOT_PROBE_CAPABILITY, None)
    if not callable(probe):
        raise ShadowOneShotProbeCapabilityError(
            "shadow one-shot requires an SDK bounded read-only metadata probe"
        )
    return probe


def _finite_shutdown_timeout_seconds(shutdown_seconds):
    """Convert a validated Decimal shutdown buffer to a finite Store timeout."""

    try:
        timeout_seconds = float(shutdown_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RunnerConfigurationError(
            "shutdown buffer is not a finite representable timeout"
        ) from exc
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise RunnerConfigurationError("shutdown buffer is not a finite representable timeout")
    return timeout_seconds


def _bounded_one_shot_metadata_probe(probe, timeout_seconds):
    """Collect a bounded, post-shutdown public metadata snapshot from the SDK."""

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise RunnerConfigurationError("shutdown buffer is not a finite representable timeout")
    result = probe(
        datanames=tuple(VENUE_SYMBOLS.values()),
        timeout_seconds=timeout_seconds,
    )
    required = {"instrument_specs", "funding_snapshots", "store_health"}
    if not isinstance(result, Mapping) or not required.issubset(result):
        raise RunnerConfigurationError("bounded one-shot metadata probe result is incomplete")
    if not isinstance(result["instrument_specs"], Mapping):
        raise RunnerConfigurationError("bounded one-shot instrument snapshot is invalid")
    if not isinstance(result["funding_snapshots"], Mapping):
        raise RunnerConfigurationError("bounded one-shot funding snapshot is invalid")
    if not isinstance(result["store_health"], Mapping):
        raise RunnerConfigurationError("bounded one-shot shutdown evidence is invalid")
    if not _store_shutdown_proven(result["store_health"]):
        raise RunnerConfigurationError("bounded one-shot shutdown evidence is not proven")
    return result


def _rules_from_one_shot_metadata_probe(metadata):
    """Build read-only conservative rules from the bounded SDK snapshot."""

    instrument_specs = metadata["instrument_specs"]
    rules = {}
    fee_sources = {}
    for venue, symbol in VENUE_SYMBOLS.items():
        label = f"{venue} InstrumentSpec"
        instrument = _require_typed_contract(instrument_specs.get(symbol), InstrumentSpec, label)
        try:
            rules[venue] = InstrumentRule.from_sdk_contracts(instrument, CONSERVATIVE_TAKER_FEE)
        except ValueError as exc:
            raise RunnerConfigurationError(f"{label} contains an unsafe value") from exc
        fee_sources[venue] = "conservative_bound"
    return rules, fee_sources


def _funding_from_one_shot_metadata_probe(metadata):
    """Validate funding snapshots returned by the bounded SDK probe."""

    snapshots = metadata["funding_snapshots"]
    result = {}
    for venue, symbol in VENUE_SYMBOLS.items():
        label = f"{venue} public FundingSnapshot"
        snapshot = _require_typed_contract(snapshots.get(symbol), FundingSnapshot, label)
        try:
            snapshot = coerce_funding_snapshot(
                snapshot,
                now_epoch=decimal_value(time.time(), "funding_now"),
                expected_exchange_name=EXCHANGES[venue],
                expected_symbol=symbol,
            )
        except ValueError as exc:
            raise RunnerConfigurationError(f"{label} is invalid: {exc}") from exc
        assert snapshot.rate is not None
        assert snapshot.settlement_interval_seconds is not None
        result[venue] = (
            snapshot.rate,
            snapshot.next_funding_epoch,
            Decimal(snapshot.settlement_interval_seconds),
            snapshot.source,
        )
    return result


def _load_model_qualification(
    candidate,
    rules,
    risk,
    config_path=DEFAULT_CONFIG,
    allow_operator_demo_calibration_contract_mismatch=False,
):
    """Load the immutable, direction-bound calibration artifact for live observation."""

    if not isinstance(allow_operator_demo_calibration_contract_mismatch, bool):
        raise RunnerConfigurationError("operator demo calibration override must be a boolean")
    if allow_operator_demo_calibration_contract_mismatch and (
        candidate.get("strategy_id") != STRATEGY_ID
        or candidate.get("research_status") != "RESEARCH_REJECTED"
    ):
        raise RunnerConfigurationError("calibration contract override is rejected-candidate only")
    binding = candidate.get("qualification_artifact")
    if not isinstance(binding, Mapping):
        raise RunnerConfigurationError("candidate qualification artifact binding is missing")
    if binding.get("role") != "calibration_training_only":
        raise RunnerConfigurationError("candidate qualification artifact role is invalid")
    relative_path = binding.get("path")
    expected_hash = binding.get("sha256")
    if not isinstance(relative_path, str) or not expected_hash:
        raise RunnerConfigurationError("candidate qualification artifact path/hash is missing")
    artifact_path = (HERE / relative_path).resolve()
    if HERE.resolve() not in artifact_path.parents:
        raise RunnerConfigurationError(
            "qualification artifact must stay under the example directory"
        )
    if _file_sha256(artifact_path, "qualification artifact") != expected_hash:
        raise RunnerConfigurationError("qualification artifact fingerprint mismatch")
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise RunnerConfigurationError("qualification artifact is unavailable or invalid") from exc
    if (
        payload.get("schema_version") != 3
        or payload.get("status") != "CALIBRATION_ONLY_MODEL_QUALIFIED"
        or payload.get("source_role") != "legacy_calibration_training_only"
        or payload.get("oos_or_demo_approval") is not False
    ):
        raise RunnerConfigurationError("qualification artifact has an invalid evidence role")
    artifact_config_sha256 = payload.get("config_sha256")
    if not (
        isinstance(artifact_config_sha256, str)
        and len(artifact_config_sha256) == 64
        and all(char in "0123456789abcdef" for char in artifact_config_sha256)
    ):
        raise RunnerConfigurationError("qualification artifact config fingerprint is invalid")
    config_sha256_matches = artifact_config_sha256 == _file_sha256(
        config_path, "qualification config"
    )
    if not config_sha256_matches and not allow_operator_demo_calibration_contract_mismatch:
        raise RunnerConfigurationError("qualification artifact is not bound to this config")
    serialized_rules = {
        venue: {key: str(value) for key, value in asdict(rule).items()}
        for venue, rule in rules.items()
    }
    artifact_rules = payload.get("rules")
    if not isinstance(artifact_rules, Mapping) or set(artifact_rules) != set(serialized_rules):
        raise RunnerConfigurationError("qualification artifact venue rules schema is invalid")
    for venue, expected_rule in serialized_rules.items():
        artifact_rule = artifact_rules.get(venue)
        if (
            not isinstance(artifact_rule, Mapping)
            or set(artifact_rule) != set(expected_rule)
            or any(not isinstance(value, str) for value in artifact_rule.values())
        ):
            raise RunnerConfigurationError("qualification artifact venue rules schema is invalid")
    rules_match = artifact_rules == serialized_rules
    if not rules_match and not allow_operator_demo_calibration_contract_mismatch:
        raise RunnerConfigurationError("qualification artifact is not bound to current venue rules")
    raw_artifacts = payload.get("artifacts")
    if not isinstance(raw_artifacts, Mapping) or set(raw_artifacts) != {
        "okx->binance",
        "binance->okx",
    }:
        raise RunnerConfigurationError("qualification artifact must bind both directions")
    result = {}
    contract_mismatch_directions = []
    now_epoch = Decimal(str(time.time()))
    for direction_name, raw_artifact in raw_artifacts.items():
        if not isinstance(raw_artifact, Mapping):
            raise RunnerConfigurationError("qualification direction is not a typed mapping")
        try:
            artifact = BasisModelQualification(**raw_artifact)
        except (TypeError, ValueError) as exc:
            raise RunnerConfigurationError("qualification direction is invalid") from exc
        buy_venue, sell_venue = direction_name.split("->", 1)
        expected_contract = qualification_contract_sha256(
            rules,
            risk,
            buy_venue,
            sell_venue,
        )
        contract_mismatch = artifact.qualification_contract_sha256 != expected_contract
        if allow_operator_demo_calibration_contract_mismatch and (
            artifact.qualification_contract_sha256 is None
        ):
            raise RunnerConfigurationError(
                f"qualification direction {direction_name} has no contract fingerprint"
            )
        reason = artifact.rejection_at(
            now_epoch,
            minimum_samples=risk.minimum_qualification_samples,
            maximum_half_life_seconds=risk.maximum_half_life_seconds,
            expected_contract_sha256=expected_contract,
            expected_direction=(buy_venue, sell_venue),
            allow_contract_mismatch=(
                allow_operator_demo_calibration_contract_mismatch and contract_mismatch
            ),
        )
        if reason is not None:
            raise RunnerConfigurationError(
                f"qualification direction {direction_name} rejected: {reason}"
            )
        if contract_mismatch:
            contract_mismatch_directions.append(direction_name)
        result[direction_name] = artifact
    contract_mismatch_directions.sort()
    has_contract_mismatch = bool(
        not config_sha256_matches or not rules_match or contract_mismatch_directions
    )
    evidence = {
        "path": str(artifact_path),
        "sha256": expected_hash,
        "status": (
            "OPERATOR_DEMO_CALIBRATION_CONTRACT_MISMATCH"
            if allow_operator_demo_calibration_contract_mismatch and has_contract_mismatch
            else payload["status"]
        ),
        "source_data_sha256": payload.get("source_data_sha256"),
        "source_role": payload["source_role"],
        "oos_or_demo_approval": False,
        "qualification_scope": "CALIBRATION_TRAINING_ONLY",
        "research_qualification": False,
        "config_sha256_matches": config_sha256_matches,
        "rules_match": rules_match,
        "qualification_contract_mismatch_directions": contract_mismatch_directions,
        "operator_demo_contract_override": allow_operator_demo_calibration_contract_mismatch,
    }
    return result, evidence


def _funding_from_store(store):
    result = {}
    for venue, symbol in VENUE_SYMBOLS.items():
        label = f"{venue} public FundingSnapshot"
        snapshot = _require_typed_contract(
            store.get_typed_funding_snapshot(symbol), FundingSnapshot, label
        )
        try:
            snapshot = coerce_funding_snapshot(
                snapshot,
                now_epoch=decimal_value(time.time(), "funding_now"),
                expected_exchange_name=EXCHANGES[venue],
                expected_symbol=symbol,
            )
        except ValueError as exc:
            raise RunnerConfigurationError(f"{label} is invalid: {exc}") from exc
        assert snapshot.rate is not None
        assert snapshot.settlement_interval_seconds is not None
        result[venue] = (
            snapshot.rate,
            snapshot.next_funding_epoch,
            Decimal(snapshot.settlement_interval_seconds),
            snapshot.source,
        )
    return result


def _cached_funding_provider(store, max_age_seconds):
    def provider():
        return {
            venue: store.get_cached_funding_snapshot(
                symbol,
                max_age_seconds=float(max_age_seconds),
            )
            for venue, symbol in VENUE_SYMBOLS.items()
        }

    return provider


def _readiness_attempt(
    store,
    rules,
    risk,
    *,
    initialize_account_risk_baseline,
    baseline_initialization_state,
):
    venues = {}
    for venue, symbol in VENUE_SYMBOLS.items():
        environment = store.get_environment_info(symbol)
        account = store.get_account_config(symbol)
        quantity_native = rules[venue].base_to_native(risk.quantity_base)
        readiness = store.get_order_readiness(
            symbol,
            quantity_native,
            position_mode="dual_side",
        )
        if environment.get("environment") != "demo" or account.get("position_mode") != "dual_side":
            raise RunnerConfigurationError(
                f"{venue} demo environment or dual-side mode is not ready"
            )
        if account.get("can_trade") is not True:
            raise RunnerConfigurationError(f"{venue} demo account cannot trade")
        if not isinstance(readiness, Mapping) or readiness.get("ready") is not True:
            if (
                isinstance(readiness, Mapping)
                and readiness.get("ready") is False
                and readiness.get("definite_failure") is not True
            ):
                raise _TransientDemoReadinessEvidence(
                    f"{venue} order readiness is false"
                )
            raise RunnerConfigurationError(f"{venue} order readiness is false")
        venues[venue] = {
            "environment": environment,
            "position_mode": account.get("position_mode"),
            "can_trade": account.get("can_trade"),
            "ready": readiness.get("ready"),
        }

    account_risk = store.get_account_risk_snapshot()
    reconcile = store.get_reconcile_snapshot()
    if not isinstance(reconcile, Mapping):
        raise _TransientDemoReadinessEvidence("demo reconciliation evidence is incomplete")
    execution_summary = reconcile.get("execution_summary")
    baseline_initialized = bool(
        isinstance(account_risk, Mapping)
        and account_risk.get("baseline_equity") is None
        and account_risk.get("loss_limit_breached") is False
        and "baseline_missing" in (account_risk.get("blocked_reasons") or ())
    )
    if baseline_initialized:
        if isinstance(reconcile, Mapping) and (
            reconcile.get("positions") or reconcile.get("open_orders")
        ):
            raise RunnerConfigurationError("demo account must be flat with no open orders")
        if not _reconcile_snapshot_ready_for_baseline(reconcile):
            raise _TransientDemoReadinessEvidence(
                "demo reconciliation evidence is incomplete"
            )
        if initialize_account_risk_baseline:
            if baseline_initialization_state["attempted"]:
                raise _TransientDemoReadinessEvidence(
                    "demo account-risk baseline is not proven"
                )
            baseline_initialization_state["attempted"] = True
            store.initialize_account_risk_baseline()
            reconcile = store.get_reconcile_snapshot()
            if not isinstance(reconcile, Mapping):
                raise _TransientDemoReadinessEvidence(
                    "post-baseline reconciliation evidence is incomplete"
                )
            execution_summary = reconcile.get("execution_summary")
            account_risk = store.get_account_risk_snapshot()
        elif baseline_initialization_state["attempted"]:
            raise _TransientDemoReadinessEvidence(
                "demo account-risk baseline is not proven"
            )
        else:
            raise RunnerConfigurationError("demo account-risk baseline is not proven")
    else:
        if not _reconcile_snapshot_proven(reconcile):
            if isinstance(reconcile, Mapping) and (
                reconcile.get("positions") or reconcile.get("open_orders")
            ):
                raise RunnerConfigurationError("demo account must be flat with no open orders")
            raise _TransientDemoReadinessEvidence(
                "demo reconciliation evidence is incomplete"
            )
        if not _execution_summary_proven(execution_summary):
            raise _TransientDemoReadinessEvidence(
                "demo execution journal is not proven clean"
            )
        if reconcile.get("positions") or reconcile.get("open_orders"):
            raise RunnerConfigurationError("demo account must be flat with no open orders")
    if not _reconcile_snapshot_proven(reconcile):
        if isinstance(reconcile, Mapping) and (
            reconcile.get("positions") or reconcile.get("open_orders")
        ):
            raise RunnerConfigurationError("demo account must be flat with no open orders")
        raise _TransientDemoReadinessEvidence(
            "post-baseline reconciliation evidence is incomplete"
        )
    if not _execution_summary_proven(execution_summary):
        raise _TransientDemoReadinessEvidence(
            "post-baseline execution journal is not proven clean"
        )
    if not _account_risk_proven(account_risk, execution_summary):
        if isinstance(account_risk, Mapping) and (
            account_risk.get("loss_limit_breached") is True
            or (
                account_risk.get("trading_blocked") is True
                and account_risk.get("evidence_complete") is True
                and not account_risk.get("evidence_errors")
            )
        ):
            raise RunnerConfigurationError("demo account-risk baseline is not proven")
        raise _TransientDemoReadinessEvidence("demo account-risk baseline is not proven")
    if reconcile.get("positions") or reconcile.get("open_orders"):
        raise RunnerConfigurationError("demo account must be flat with no open orders")
    return {
        "status": "PASS",
        "venues": venues,
        "positions": reconcile.get("positions"),
        "open_orders": reconcile.get("open_orders"),
        "reconcile_snapshot": reconcile,
        "execution_summary": execution_summary,
        "account_risk_snapshot": account_risk,
        "exchange_operations": "READ_ONLY",
        "local_persistence": {
            "account_risk_baseline_initialized": (
                baseline_initialized or baseline_initialization_state["attempted"]
            ),
            "may_write_local_execution_ledger": (
                baseline_initialized or baseline_initialization_state["attempted"]
            ),
        },
    }


def _readiness(store, rules, risk, *, initialize_account_risk_baseline=True):
    """Retry only incomplete startup evidence, with no more than one baseline write."""
    baseline_initialization_state = {"attempted": False}
    last_transient_error = None
    for attempt in range(STARTUP_EVIDENCE_MAX_ATTEMPTS):
        try:
            return _readiness_attempt(
                store,
                rules,
                risk,
                initialize_account_risk_baseline=initialize_account_risk_baseline,
                baseline_initialization_state=baseline_initialization_state,
            )
        except _TransientDemoReadinessEvidence as exc:
            last_transient_error = exc
            if attempt + 1 < STARTUP_EVIDENCE_MAX_ATTEMPTS:
                time.sleep(STARTUP_EVIDENCE_RETRY_DELAY_SECONDS)
    if last_transient_error is not None:
        raise RunnerConfigurationError(str(last_transient_error)) from None
    raise RunnerConfigurationError("demo readiness evidence is incomplete")


def _store_shutdown_proven(health):
    return bool(
        isinstance(health, Mapping)
        and health.get("shutdown_state") == "PASS"
        and int(health.get("queue_depth", 0) or 0) == 0
        and not health.get("inflight")
        and not health.get("worker_alive")
        and not health.get("close_thread_alive")
        and health.get("broker_update_conservation") is True
        and not health.get("last_error_code")
    )


def _preflight_readiness_complete(readiness):
    return bool(
        isinstance(readiness, Mapping)
        and readiness.get("status") == "PASS"
        and set(readiness.get("venues") or ()) == set(VENUE_SYMBOLS)
    )


def _preflight_readiness_summary(readiness):
    """Keep proof booleans while excluding account, balance, and order payloads."""

    if not isinstance(readiness, Mapping):
        return {"status": "INCOMPLETE", "venues": {}}
    raw_venues = readiness.get("venues")
    raw_venues = raw_venues if isinstance(raw_venues, Mapping) else {}
    venues = {}
    for venue in VENUE_SYMBOLS:
        row = raw_venues.get(venue)
        if not isinstance(row, Mapping):
            continue
        environment = row.get("environment")
        environment = environment if isinstance(environment, Mapping) else {}
        api_region = environment.get("api_region")
        venues[venue] = {
            "environment": (
                environment.get("environment")
                if environment.get("environment") in {"demo", "production"}
                else "UNKNOWN"
            ),
            "simulated": environment.get("simulated") is True,
            "verified": environment.get("verified") is True,
            "api_region": api_region if api_region in OKX_API_REGIONS else None,
            "position_mode": (
                row.get("position_mode")
                if row.get("position_mode") in {"dual_side", "net"}
                else "UNKNOWN"
            ),
            "can_trade": row.get("can_trade") is True,
            "ready": row.get("ready") is True,
        }
    reconcile = readiness.get("reconcile_snapshot")
    execution = readiness.get("execution_summary")
    account_risk = readiness.get("account_risk_snapshot")
    local = readiness.get("local_persistence")
    local = local if isinstance(local, Mapping) else {}
    positions = readiness.get("positions")
    open_orders = readiness.get("open_orders")
    return {
        "status": readiness.get("status") if readiness.get("status") == "PASS" else "INCOMPLETE",
        "venues": venues,
        "position_count": len(positions) if isinstance(positions, (list, tuple)) else None,
        "open_order_count": len(open_orders) if isinstance(open_orders, (list, tuple)) else None,
        "reconciliation_proven": _reconcile_snapshot_proven(reconcile),
        "execution_summary_proven": _execution_summary_proven(execution),
        "account_risk_proven": _account_risk_proven(account_risk, execution),
        "exchange_operations": (
            "READ_ONLY" if readiness.get("exchange_operations") == "READ_ONLY" else "UNKNOWN"
        ),
        "local_persistence": {
            "account_risk_baseline_initialized": (
                local.get("account_risk_baseline_initialized") is True
            ),
            "may_write_local_execution_ledger": (
                local.get("may_write_local_execution_ledger") is True
            ),
        },
    }


def _execution_summary_proven(summary):
    collections = (list, tuple, set, frozenset)
    if not isinstance(summary, Mapping):
        return False
    try:
        active_orders = summary["active_orders"]
        generation = int(summary.get("generation", summary.get("session_generation", 0)) or 0)
        fencing_epoch = int(summary.get("fencing_epoch", 0) or 0)
        as_of_monotonic_ns = int(summary.get("as_of_monotonic_ns", 0) or 0)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return bool(
        not isinstance(active_orders, bool)
        and isinstance(active_orders, int)
        and active_orders == 0
        and generation > 0
        and fencing_epoch > 0
        and as_of_monotonic_ns > 0
        and summary.get("session_enabled") is True
        and _is_sha256(summary.get("identity_binding_sha256"))
        and summary.get("evidence_complete") is True
        and summary.get("trading_blocked") is False
        and isinstance(summary.get("unknown_ids"), collections)
        and not summary["unknown_ids"]
        and isinstance(summary.get("fee_unresolved_orders"), collections)
        and not summary["fee_unresolved_orders"]
        and isinstance(summary.get("funding_unresolved_orders", ()), collections)
        and not summary.get("funding_unresolved_orders", ())
        and not summary.get("evidence_errors")
        and not summary.get("error_code")
    )


def _is_sha256(value):
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _reconcile_snapshot_proven(snapshot):
    if not isinstance(snapshot, Mapping):
        return False
    configured = set(snapshot.get("configured_venues") or ())
    reconciled = set(snapshot.get("reconciled_venues") or ())
    summary = snapshot.get("execution_summary")
    return bool(
        configured == reconciled == set(VENUE_SYMBOLS)
        and isinstance(snapshot.get("positions"), list)
        and isinstance(snapshot.get("open_orders"), list)
        and snapshot.get("evidence_complete") is True
        and not snapshot.get("evidence_errors")
        and _execution_summary_proven(summary)
        and snapshot.get("identity_binding_sha256") == summary.get("identity_binding_sha256")
    )


def _reconcile_snapshot_ready_for_baseline(snapshot):
    """Accept only the expected risk-baseline latch during first startup."""

    if not isinstance(snapshot, Mapping):
        return False
    configured = set(snapshot.get("configured_venues") or ())
    reconciled = set(snapshot.get("reconciled_venues") or ())
    summary = snapshot.get("execution_summary")
    if not isinstance(summary, Mapping):
        return False
    relaxed_summary = dict(summary)
    if relaxed_summary.get("evidence_errors") != ["account_risk_baseline_required"]:
        return False
    relaxed_summary["evidence_errors"] = []
    relaxed_summary["trading_blocked"] = False
    return bool(
        configured == reconciled == set(VENUE_SYMBOLS)
        and isinstance(snapshot.get("positions"), list)
        and isinstance(snapshot.get("open_orders"), list)
        and snapshot.get("evidence_complete") is True
        and not snapshot.get("evidence_errors")
        and _execution_summary_proven(relaxed_summary)
        and snapshot.get("identity_binding_sha256") == summary.get("identity_binding_sha256")
    )


def _account_risk_proven(snapshot, execution_summary):
    if not isinstance(snapshot, Mapping) or not isinstance(execution_summary, Mapping):
        return False
    try:
        generation = snapshot["generation"]
        fencing_epoch = snapshot["fencing_epoch"]
        as_of_monotonic_ns = snapshot["as_of_monotonic_ns"]
        owner_pid = snapshot["owner_pid"]
        clock_domain_id = snapshot["clock_domain_id"]
        baseline = decimal_value(snapshot["baseline_equity"], "baseline_equity")
        current = decimal_value(snapshot["current_equity"], "current_equity")
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False
    current_pid = os.getpid()
    now_monotonic_ns = time.monotonic_ns()
    return bool(
        not any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (
                generation,
                fencing_epoch,
                as_of_monotonic_ns,
                owner_pid,
            )
        )
        and generation > 0
        and fencing_epoch == execution_summary.get("fencing_epoch")
        and 0 < as_of_monotonic_ns <= now_monotonic_ns
        and owner_pid == current_pid
        and clock_domain_id == f"process:{current_pid}:monotonic"
        and baseline > 0
        and current.is_finite()
        and set(snapshot.get("configured_venues") or ()) == set(VENUE_SYMBOLS)
        and snapshot.get("durable") is True
        and snapshot.get("trading_blocked") is False
        and snapshot.get("evidence_complete") is True
        and not snapshot.get("evidence_errors")
        and not snapshot.get("error_code")
        and _is_sha256(snapshot.get("identity_binding_sha256"))
        and snapshot.get("identity_binding_sha256")
        == execution_summary.get("identity_binding_sha256")
    )


def _paper_flatness(broker):
    positions = {}
    flat = not list(broker.get_orders_open())
    for venue, symbol in VENUE_SYMBOLS.items():
        long_position = getattr(broker, "long_positions", {}).get(symbol)
        short_position = getattr(broker, "short_positions", {}).get(symbol)
        long_size = decimal_value(getattr(long_position, "size", 0) or 0)
        short_size = decimal_value(getattr(short_position, "size", 0) or 0)
        positions[venue] = {"long": str(long_size), "short": str(short_size)}
        flat = flat and long_size == 0 and short_size == 0
    return {"flat": flat, "positions": positions, "open_orders": len(broker.get_orders_open())}


def _trade_logger_report(strategy):
    """Return the frozen generic report and its frozen candidate extension."""

    trade_logger = getattr(getattr(strategy, "stats", None), "trade_logger", None)
    final_report = getattr(trade_logger, "final_report", None)
    generic_report = final_report() if callable(final_report) else None
    if not isinstance(generic_report, Mapping) or generic_report.get("finalized") is not True:
        raise RunnerConfigurationError("TradeLogger final report is unavailable")

    generic_report = dict(generic_report)
    extensions = generic_report.get("extensions", {})
    domain_context = extensions.get("cross_venue") if isinstance(extensions, Mapping) else None
    if not isinstance(domain_context, Mapping) or not domain_context:
        raise RunnerConfigurationError("TradeLogger final report is missing cross_venue evidence")
    return generic_report, dict(domain_context)


def _post_run_reconciliation_revision(
    frozen_context: Mapping[str, object],
    reconciled_context: Mapping[str, object],
    reconcile_snapshot: Optional[Mapping[str, object]],
    execution_summary: Optional[Mapping[str, object]],
) -> dict[str, object]:
    """Bind a post-stop reconciliation to the frozen Observer evidence.

    The generic ``TradeLogger`` report is deliberately immutable after its
    ``stop`` lifecycle.  A remote reconciliation may only complete after that
    point, so it is emitted as a separately hash-bound revision instead of
    silently replacing the frozen ``extensions.cross_venue`` value.
    """

    if not isinstance(frozen_context, Mapping) or not frozen_context:
        raise RunnerConfigurationError("frozen cross_venue evidence is unavailable")
    if not isinstance(reconciled_context, Mapping) or not reconciled_context:
        raise RunnerConfigurationError("reconciled cross_venue evidence is unavailable")
    if reconcile_snapshot is not None and not isinstance(reconcile_snapshot, Mapping):
        raise RunnerConfigurationError("post-run reconcile snapshot is invalid")
    if execution_summary is not None and not isinstance(execution_summary, Mapping):
        raise RunnerConfigurationError("post-run execution summary is invalid")

    frozen = dict(frozen_context)
    reconciled = dict(reconciled_context)
    revision = {
        "schema_version": 1,
        "revision_type": "post_run_reconciliation",
        "status": "APPLIED_AFTER_TRADE_LOGGER_FINALIZATION",
        "frozen_trade_logger_extension": frozen,
        "frozen_trade_logger_extension_sha256": _canonical_hash(frozen),
        "reconciled_cross_venue_extension": reconciled,
        "reconciled_cross_venue_extension_sha256": _canonical_hash(reconciled),
        "reconciliation_required_before": frozen.get("reconciliation_required") is True,
        "remote_flat_proven_after": reconciled.get("remote_flat_proven") is True,
        "outcome": (
            "REMOTE_FLAT_PROVEN"
            if reconciled.get("remote_flat_proven") is True
            else "REMOTE_FLAT_NOT_PROVEN"
        ),
        "reconcile_snapshot_sha256": (
            _canonical_hash(dict(reconcile_snapshot)) if reconcile_snapshot is not None else None
        ),
        "execution_summary_sha256": (
            _canonical_hash(dict(execution_summary)) if execution_summary is not None else None
        ),
    }
    revision["revision_sha256"] = _canonical_hash(revision)
    return revision


def _realized_metrics(strategy_report):
    rows = strategy_report.get("execution_economics", ())
    if not isinstance(rows, (list, tuple)):
        return _formula_fixture_metrics(), False
    parsed = []
    try:
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError
            parsed.append(
                (
                    decimal_value(row["gross_pnl"], "gross_pnl"),
                    decimal_value(row["realized_net"], "realized_net"),
                )
            )
    except (KeyError, TypeError, ValueError):
        return _formula_fixture_metrics(), False
    gross = sum((row[0] for row in parsed), Decimal(0))
    nets = [row[1] for row in parsed]
    net = sum(nets, Decimal(0))
    costs = gross - net
    running = Decimal(0)
    peak = Decimal(0)
    maximum_drawdown = Decimal(0)
    for value in nets:
        running += value
        peak = max(peak, running)
        maximum_drawdown = max(maximum_drawdown, peak - running)
    trades = len(parsed)
    metrics = {
        "gross_pnl": str(gross),
        "total_cost": str(costs),
        "net_pnl": str(net),
        "maximum_drawdown": str(maximum_drawdown),
        "return_drawdown_ratio": (None if maximum_drawdown == 0 else str(net / maximum_drawdown)),
        "win_rate": str(Decimal(sum(value > 0 for value in nets)) / trades) if trades else "0",
        "expectancy_per_trade": str(net / trades) if trades else "0",
        "trade_count": trades,
        "cost_to_gross_ratio": None if gross == 0 else str(costs / abs(gross)),
        "latency_ms": {"p50": None, "p95": None, "p99": None, "samples": 0},
        "markouts_quote": strategy_report.get(
            "markouts_quote", {"10": [], "50": [], "100": [], "500": []}
        ),
        "unhedged_duration_seconds": {
            "p50": None,
            "p95": None,
            "p99": None,
            "max": strategy_report.get("unhedged_duration_max"),
        },
    }
    fills = int(strategy_report.get("confirmed_fill_events", 0) or 0)
    return metrics, fills == 0 or bool(parsed)


def _funding_economics_proven(strategy_report):
    rows = strategy_report.get("execution_economics")
    if not isinstance(rows, (list, tuple)) or not rows:
        return False
    allowed = {
        "actual_ledger",
        "no_settlement_expected",
        "no_settlement_expected_failed_cycle",
    }
    try:
        return all(
            row.get("funding_evidence_status") in allowed
            and decimal_value(row["signed_funding_cashflow"], "signed_funding_cashflow").is_finite()
            for row in rows
            if isinstance(row, Mapping)
        ) and all(isinstance(row, Mapping) for row in rows)
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False


def _approval_lease_status_proven(status, approval_lease):
    if not isinstance(status, Mapping) or not isinstance(approval_lease, Mapping):
        return False
    maximum = approval_lease.get("maximum_order_count")
    count = status.get("operation_count")
    return bool(
        status.get("enabled") is True
        and status.get("expires_at_utc") == approval_lease.get("expires_at")
        and type(maximum) is int
        and status.get("maximum_order_count") == maximum
        and type(count) is int
        and 0 <= count <= maximum
    )


def _demo_broker_kwargs(approval_lease, shutdown_seconds):
    if not isinstance(approval_lease, Mapping):
        raise DemoApprovalError("demo broker requires a verified approval lease")
    expires_at = approval_lease.get("expires_at")
    maximum_order_count = approval_lease.get("maximum_order_count")
    if (
        not isinstance(expires_at, str)
        or not expires_at.endswith("Z")
        or type(maximum_order_count) is not int
        or maximum_order_count <= 0
    ):
        raise DemoApprovalError("demo broker approval lease is invalid")
    return {
        "position_mode": "dual_side",
        "position_sync_policy": "startup",
        "position_audit_interval": 10.0,
        "shutdown_timeout": float(shutdown_seconds),
        "approval_expires_at_utc": expires_at,
        "approval_max_order_count": maximum_order_count,
    }


def _safe_exception_type(exc):
    name = type(exc).__name__
    if (
        not name
        or len(name) > 80
        or not name[0].isalpha()
        or any(not (char.isascii() and (char.isalnum() or char == "_")) for char in name)
    ):
        return "Exception"
    return name


def _safe_exchange_error_code(exc):
    for attribute in ("error_code", "code", "status_code"):
        try:
            value = getattr(exc, attribute, None)
        except Exception:
            continue
        if type(value) is int and 0 < value <= 999999:
            return str(value)
        if isinstance(value, str) and value.isascii() and value.isdigit() and 1 <= len(value) <= 6:
            return value
    return None


def _safe_preflight_failure_code(exc):
    """Map known local validation failures without exposing provider text."""

    message = str(exc)
    known = {
        "demo reconciliation evidence is incomplete": "RECONCILIATION_INCOMPLETE",
        "demo execution journal is not proven clean": "EXECUTION_JOURNAL_NOT_CLEAN",
        "demo account must be flat with no open orders": "ACCOUNT_NOT_FLAT",
        "post-baseline reconciliation evidence is incomplete": (
            "POST_BASELINE_RECONCILIATION_INCOMPLETE"
        ),
        "post-baseline execution journal is not proven clean": (
            "POST_BASELINE_EXECUTION_JOURNAL_NOT_CLEAN"
        ),
        "demo account-risk baseline is not proven": "ACCOUNT_RISK_BASELINE_NOT_PROVEN",
    }
    for venue in VENUE_SYMBOLS:
        upper = venue.upper()
        known[f"{venue} demo environment or dual-side mode is not ready"] = (
            f"{upper}_ENVIRONMENT_OR_POSITION_MODE_NOT_READY"
        )
        known[f"{venue} demo account cannot trade"] = f"{upper}_CANNOT_TRADE"
        known[f"{venue} order readiness is false"] = f"{upper}_ORDER_NOT_READY"
    return known.get(message, "PREFLIGHT_OPERATION_FAILED")


def _preflight_failure_report(candidate, config, admission, stage, exc):
    """Return an auditable failure without serializing vendor exception contents."""

    return {
        "status": "PREFLIGHT_FAILED_PENDING_SHUTDOWN",
        "mode": "demo",
        "orders_submitted": 0,
        "fills": 0,
        "execution_status": "NOT_RUN",
        "candidate_sha256": candidate["candidate_sha256"],
        "config_sha256": candidate["config_sha256"],
        "normalized_config_sha256": _canonical_hash(config),
        "strategy_sha256": candidate["strategy_sha256"],
        "admission": admission,
        "readiness": {
            "status": "FAIL",
            "venues": {},
            "exchange_operations": "READ_ONLY_ATTEMPTED",
            "local_persistence": {"status": "UNKNOWN_DUE_TO_FAILURE"},
        },
        "preflight_failure": {
            "failure_code": _safe_preflight_failure_code(exc),
            "stage": stage,
            "exception_type": _safe_exception_type(exc),
            "exchange_error_code": _safe_exchange_error_code(exc),
            "detail": "REDACTED",
        },
        "profitability_claim": "NONE_PREFLIGHT_ONLY",
    }


def _safe_shadow_failure_code(exc):
    """Classify a shadow failure without evaluating an untrusted error message."""

    if isinstance(exc, RunnerSourceBindingError):
        return "RUNNER_SOURCE_BINDING_REJECTED"
    if isinstance(exc, ShadowOneShotProbeCapabilityError):
        return "SHADOW_ONE_SHOT_BOUNDED_PROBE_UNAVAILABLE"
    if isinstance(exc, RunnerConfigurationError):
        return "SHADOW_RUNNER_CONFIGURATION_ERROR"
    return "SHADOW_OPERATION_FAILED"


def _shadow_observed_execution_fields(observed_execution, *, execution_started=False):
    """Return report-safe local counters when a shadow invariant trips late."""

    if observed_execution is None:
        if execution_started:
            return {
                "orders_submitted": None,
                "fills": None,
                "execution_status": "UNEXPECTED_EXECUTION_EVIDENCE_INCOMPLETE",
                "shadow_execution_anomaly": {
                    "observed": True,
                    "execution_started": True,
                    "evidence_complete": False,
                },
            }
        return {
            "orders_submitted": 0,
            "fills": 0,
            "execution_status": "NOT_RUN",
        }
    if not isinstance(observed_execution, Mapping):
        return {
            "orders_submitted": None,
            "fills": None,
            "execution_status": "UNEXPECTED_EXECUTION_EVIDENCE_INCOMPLETE",
            "shadow_execution_anomaly": {
                "observed": True,
                "evidence_complete": False,
            },
        }
    submitted = observed_execution.get("orders_submitted")
    fills = observed_execution.get("fills")
    broker_value_change = observed_execution.get("broker_value_change")
    if type(submitted) is not int or submitted < 0 or type(fills) is not int or fills < 0:
        return {
            "orders_submitted": None,
            "fills": None,
            "execution_status": "UNEXPECTED_EXECUTION_EVIDENCE_INCOMPLETE",
            "shadow_execution_anomaly": {
                "observed": True,
                "evidence_complete": False,
            },
        }
    try:
        normalized_value_change = str(
            decimal_value(broker_value_change, "shadow_broker_value_change")
        )
    except (TypeError, ValueError, ArithmeticError):
        return {
            "orders_submitted": submitted,
            "fills": fills,
            "execution_status": "UNEXPECTED_EXECUTION_EVIDENCE_INCOMPLETE",
            "shadow_execution_anomaly": {
                "observed": True,
                "evidence_complete": False,
            },
        }
    if submitted == 0 and fills == 0 and decimal_value(normalized_value_change) == 0:
        return {
            "orders_submitted": 0,
            "fills": 0,
            "execution_status": "NOT_RUN",
        }
    return {
        "orders_submitted": submitted,
        "fills": fills,
        "execution_status": "UNEXPECTED_EXECUTION_OBSERVED",
        "broker_value_change": normalized_value_change,
        "shadow_execution_anomaly": {
            "observed": True,
            "orders_submitted": submitted,
            "fills": fills,
            "broker_value_change": normalized_value_change,
        },
    }


def _shadow_failure_report(
    candidate,
    config,
    admission,
    stage,
    exc,
    observed_execution=None,
    execution_started=False,
    read_only_calibration_diagnostic=False,
):
    """Return a minimal terminal shadow report with no vendor payloads."""

    report = {
        "status": "SHADOW_FAILED_PENDING_SHUTDOWN",
        "mode": "shadow",
        "evidence_level": "R2_SHADOW_FAILURE",
        "candidate_sha256": candidate["candidate_sha256"],
        "config_sha256": candidate["config_sha256"],
        "normalized_config_sha256": _canonical_hash(config),
        "strategy_sha256": candidate["strategy_sha256"],
        "admission": admission,
        "shadow_failure": {
            "failure_code": _safe_shadow_failure_code(exc),
            "stage": stage,
            "exception_type": _safe_exception_type(exc),
            "exchange_error_code": _safe_exchange_error_code(exc),
            "detail": "REDACTED",
        },
        "profitability_claim": (
            "NONE_READ_ONLY_SHADOW_DIAGNOSTIC"
            if read_only_calibration_diagnostic
            else "NONE_SHADOW_FAILURE"
        ),
    }
    report.update(
        _shadow_observed_execution_fields(
            observed_execution,
            execution_started=execution_started,
        )
    )
    if isinstance(exc, ShadowOneShotProbeCapabilityError):
        report["one_shot_probe"] = {
            "status": "UNAVAILABLE",
            "capability": BOUNDED_ONE_SHOT_PROBE_CAPABILITY,
            "lifecycle": "SDK_OWNED",
        }
    if read_only_calibration_diagnostic:
        report["read_only_calibration_contract_diagnostic"] = admission.get(
            "read_only_calibration_contract_diagnostic"
        )
        report["qualification"] = _read_only_shadow_calibration_diagnostic_evidence()
    return report


def _shadow_cli_failure_report(config, exc):
    """Return a redacted terminal report when setup fails before a candidate is available."""

    if isinstance(exc, RunnerSourceBindingError):
        return {
            "status": "SHADOW_FAILED",
            "mode": "shadow",
            "evidence_level": "R0_PROVENANCE_REJECTION",
            "orders_submitted": 0,
            "fills": 0,
            "execution_status": "NOT_RUN",
            "provenance_status": "RUNNER_SOURCE_BINDING_REJECTED",
            "candidate_status": "UNTRUSTED",
            "admission_status": "NOT_EVALUATED",
            "configuration_status": (
                "LOADED_UNBOUND" if isinstance(config, Mapping) else "NOT_LOADED"
            ),
            "store_health": _preflight_store_health_summary(None),
            "store_stop_proven": False,
            "shadow_failure": {
                "failure_code": "RUNNER_SOURCE_BINDING_REJECTED",
                "stage": "runner_setup",
                "exception_type": "RunnerSourceBindingError",
                "exchange_error_code": None,
                "detail": "REDACTED",
            },
            "profitability_claim": "NONE_SHADOW_FAILURE",
        }
    report = {
        "status": "SHADOW_FAILED",
        "mode": "shadow",
        "evidence_level": "R2_SHADOW_FAILURE",
        "orders_submitted": 0,
        "fills": 0,
        "execution_status": "NOT_RUN",
        "normalized_config_sha256": (
            _canonical_hash(config) if isinstance(config, Mapping) else None
        ),
        "configuration_status": "LOADED" if isinstance(config, Mapping) else "NOT_LOADED",
        "store_health": _preflight_store_health_summary(None),
        "store_stop_proven": False,
        "shadow_failure": {
            "failure_code": _safe_shadow_failure_code(exc),
            "stage": "runner_setup",
            "exception_type": _safe_exception_type(exc),
            "exchange_error_code": _safe_exchange_error_code(exc),
            "detail": "REDACTED",
        },
        "profitability_claim": "NONE_SHADOW_FAILURE",
    }
    _attach_business_summary(report)
    return report


def _preflight_store_health_summary(health):
    """Expose shutdown proof fields while dropping diagnostic/account payloads."""

    if not isinstance(health, Mapping):
        return {
            "shutdown_state": "UNKNOWN",
            "queue_depth": None,
            "inflight_count": None,
            "worker_alive": None,
            "close_thread_alive": None,
            "broker_update_conservation": False,
            "last_error_present": None,
        }
    shutdown_state = health.get("shutdown_state")
    if shutdown_state not in {"PASS", "FAIL", "INCOMPLETE"}:
        shutdown_state = "UNKNOWN"
    queue_depth = health.get("queue_depth")
    if type(queue_depth) is not int or queue_depth < 0:
        queue_depth = None
    inflight = health.get("inflight")
    if type(inflight) is int and inflight >= 0:
        inflight_count = inflight
    elif isinstance(inflight, (Mapping, list, tuple, set, frozenset)):
        inflight_count = len(inflight)
    elif inflight is None:
        inflight_count = 0
    else:
        inflight_count = None
    return {
        "shutdown_state": shutdown_state,
        "queue_depth": queue_depth,
        "inflight_count": inflight_count,
        "worker_alive": health.get("worker_alive") is True,
        "close_thread_alive": health.get("close_thread_alive") is True,
        "broker_update_conservation": health.get("broker_update_conservation") is True,
        "last_error_present": bool(health.get("last_error_code")),
    }


def run_network(
    mode,
    duration,
    config_path=DEFAULT_CONFIG,
    env_file=HERE / ".env",
    preflight=False,
    manifest_path=MANIFEST_PATH,
    allow_rejected_demo_simulation=False,
    demo_execution_smoke=False,
):
    """Run a shadow, paper-live or demo session against the live venues.

    Applies manifest and config admission governance before any Store
    exists. Demo either verifies the signed approval lease or creates a
    bounded local lease after explicit rejected-candidate acknowledgement.
    Duration 0 admits
    only a bounded read-only shadow metadata probe.  Execution modes
    require the qualification artifact (and, for paper-live/demo, the
    account risk ledger); any missing prerequisite fails closed into the
    returned report.
    """
    if mode not in {"shadow", "paper-live", "demo"}:
        raise RunnerConfigurationError("network mode is invalid")
    if demo_execution_smoke:
        if mode != "demo":
            raise RunnerConfigurationError("demo execution smoke is only valid with demo mode")
        if preflight:
            raise RunnerConfigurationError("demo execution smoke is not valid during preflight")
        if not allow_rejected_demo_simulation:
            raise DemoApprovalError(
                "demo execution smoke requires --allow-rejected-demo-simulation"
            )
    # Demo stays repository-bound: only the canonical manifest satisfies the
    # signed receipt contract, so a copied folder fails closed here.
    if mode == "demo":
        canonical = REPO_CANONICAL_MANIFEST.resolve()
        if not canonical.is_file() or Path(manifest_path).resolve() != canonical:
            raise DemoApprovalError("demo requires the repository-canonical manifest path")
    config = load_config(config_path)
    manifest, candidate, resolved_manifest_path = load_candidate(manifest_path)
    if _file_sha256(config_path, "run config") != candidate["config_sha256"]:
        raise RunnerConfigurationError("run config is not bound to the selected candidate")
    admission = _validate_network_admission(
        manifest,
        candidate,
        mode,
        preflight,
        config,
        allow_rejected_demo_simulation=allow_rejected_demo_simulation,
    )
    if demo_execution_smoke:
        if candidate.get("strategy_id") != STRATEGY_ID:
            raise DemoApprovalError("demo execution smoke is limited to this 012_1 candidate")
        if admission.get("operator_override") is not True:
            raise DemoApprovalError(
                "demo execution smoke requires the rejected-candidate operator override"
            )
        admission["mechanical_demo_smoke_requested"] = True
        admission["execution_scope"] = "MECHANICAL_DEMO_SMOKE_NOT_RESEARCH"
    operator_demo_contract_mismatch = _operator_demo_calibration_contract_mismatch_enabled(
        mode, admission
    )
    risk = risk_from_config(config)
    funding_settings = funding_settings_from_config(config)
    mode_policy(mode)
    required_observation_duration(config, risk)
    requested_duration = decimal_value(duration, "duration")
    one_shot = requested_duration == 0
    if one_shot:
        if mode != "shadow":
            raise RunnerConfigurationError("duration 0 is only valid for shadow mode")
    else:
        requested_duration = _bounded_requested_duration(requested_duration, config)
    shutdown_seconds = decimal_value(
        config["observation"]["shutdown_buffer_seconds"], "shutdown_buffer_seconds"
    )
    if one_shot and shutdown_seconds <= 0:
        raise RunnerConfigurationError("duration 0 requires a positive shutdown buffer")
    shutdown_timeout_seconds = _finite_shutdown_timeout_seconds(shutdown_seconds)
    active_seconds = Decimal(0) if one_shot else requested_duration - shutdown_seconds
    if not one_shot and active_seconds <= 0:
        raise RunnerConfigurationError("duration does not leave a positive active window")
    shadow_calibration_diagnostic_admitted = (
        _shadow_read_only_calibration_contract_diagnostic_enabled(mode, admission)
    )
    shadow_calibration_diagnostic_active = (
        shadow_calibration_diagnostic_admitted and not one_shot
    )
    if shadow_calibration_diagnostic_admitted:
        diagnostic_admission = admission["read_only_calibration_contract_diagnostic"]
        diagnostic_admission["application_status"] = (
            "MODEL_ADMISSION_SKIPPED_FOR_ORDERBOOK_HEALTH_ONLY"
            if shadow_calibration_diagnostic_active
            else "NOT_APPLIED_METADATA_ONLY_ONE_SHOT"
        )
    approval_lease = None
    if mode == "demo" and not preflight:
        if not admission["operator_override"]:
            receipt = require_demo_approval(candidate, resolved_manifest_path)
            approval_lease = _approval_lease(
                receipt,
                requested_duration,
                risk,
                shutdown_seconds,
            )
    store = None
    report = None
    store_health = None
    preflight_stage = "store_build"
    one_shot_sdk_shutdown_proven = False
    shadow_execution_started = False
    shadow_observed_execution = None
    try:
        store = build_store(
            mode,
            env_file,
            risk,
            funding_settings,
            okx_api_region=config["okx_api_region"],
        )
        if one_shot:
            preflight_stage = "bounded_read_only_metadata_probe"
            probe = _require_bounded_one_shot_probe(store)
            # A failed or malformed SDK probe may have acquired Store resources,
            # so keep runner shutdown ownership until its complete result proves
            # that the SDK already stopped them.
            one_shot_metadata = _bounded_one_shot_metadata_probe(probe, shutdown_timeout_seconds)
            store_health = one_shot_metadata["store_health"]
            one_shot_sdk_shutdown_proven = True
            rules, fee_sources = _rules_from_one_shot_metadata_probe(one_shot_metadata)
            funding_contracts = _funding_from_one_shot_metadata_probe(one_shot_metadata)
        else:
            preflight_stage = "store_start"
            store.start()
            preflight_stage = "instrument_and_fee_metadata"
            rules, fee_sources = _rules_from_store(store, mode)
            preflight_stage = "funding_metadata"
            funding_contracts = _funding_from_store(store)
        rules = {
            venue: replace(rule, funding_interval_seconds=funding_contracts[venue][2])
            for venue, rule in rules.items()
        }
        funding_sources = {venue: values[3] for venue, values in funding_contracts.items()}
        if one_shot:
            duration_gate = {
                "requested_seconds": "0",
                "status": "NOT_RUN_ONE_SHOT",
                "reason": "NO_WAIT_READ_ONLY_METADATA_PROBE",
            }
        else:
            duration_gate = validate_duration(
                requested_duration,
                config,
                risk,
                next_funding_times=[value[1] for value in funding_contracts.values()],
                active_observation_seconds=active_seconds,
            )
            duration_gate.update(
                active_observation_seconds=str(active_seconds),
                shutdown_buffer_seconds=str(shutdown_seconds),
            )
        preflight_report = None
        if mode == "demo" and preflight:
            preflight_stage = "readiness"
            preflight_report = _readiness(
                store,
                rules,
                risk,
                initialize_account_risk_baseline=False,
            )
        preflight_stage = "complete"
        if preflight:
            report = {
                "status": "PREFLIGHT_PENDING_SHUTDOWN",
                "mode": mode,
                "orders_submitted": 0,
                "fills": 0,
                "execution_status": "NOT_RUN",
                "candidate_sha256": candidate["candidate_sha256"],
                "config_sha256": candidate["config_sha256"],
                "normalized_config_sha256": _canonical_hash(config),
                "strategy_sha256": candidate["strategy_sha256"],
                "admission": admission,
                "duration_gate": duration_gate,
                "fee_source": fee_sources,
                "funding_source": funding_sources,
                "fee_rate_per_fill": {venue: str(rule.taker_fee) for venue, rule in rules.items()},
                "readiness": _preflight_readiness_summary(preflight_report),
                "profitability_claim": "NONE_PREFLIGHT_ONLY",
            }
        elif one_shot:
            report = {
                "status": "SHADOW_ONE_SHOT_PENDING_SHUTDOWN_PROOF",
                "mode": "shadow",
                "evidence_level": "R0_BOUNDED_READ_ONLY_METADATA_PROBE",
                "research_status": candidate["research_status"],
                "candidate_sha256": candidate["candidate_sha256"],
                "config_sha256": candidate["config_sha256"],
                "normalized_config_sha256": _canonical_hash(config),
                "strategy_sha256": candidate["strategy_sha256"],
                "admission": admission,
                "duration_gate": duration_gate,
                "one_shot_probe": {
                    "status": "SDK_BOUNDED_PROBE_COMPLETED",
                    "capability": BOUNDED_ONE_SHOT_PROBE_CAPABILITY,
                    "lifecycle": "SDK_OWNED",
                    "timeout_seconds": str(shutdown_seconds),
                },
                "qualification_artifact_verification": {
                    "status": "NOT_RUN",
                    "reason": "METADATA_PROBE_ONLY",
                },
                "orders_submitted": 0,
                "fills": 0,
                "execution_status": "NOT_RUN",
                "fee_source": fee_sources,
                "funding_source": funding_sources,
                "fee_rate_per_fill": {venue: str(rule.taker_fee) for venue, rule in rules.items()},
                "profitability_claim": "NONE_ONE_SHOT_READ_ONLY",
            }
        else:
            if shadow_calibration_diagnostic_active:
                # Shadow diagnostics observe the existing Store/Feed/Strategy
                # path but deliberately do not consume a research artifact.
                qualifications = {}
                qualification_evidence = (
                    _read_only_shadow_calibration_diagnostic_evidence()
                )
            else:
                qualifications, qualification_evidence = _load_model_qualification(
                    candidate,
                    rules,
                    risk,
                    config_path,
                    allow_operator_demo_calibration_contract_mismatch=(
                        operator_demo_contract_mismatch
                    ),
                )
            if operator_demo_contract_mismatch:
                admission["calibration_contract_override"] = {
                    key: qualification_evidence[key]
                    for key in (
                        "status",
                        "qualification_scope",
                        "oos_or_demo_approval",
                        "research_qualification",
                        "config_sha256_matches",
                        "rules_match",
                        "qualification_contract_mismatch_directions",
                    )
                }
            if mode == "demo":
                preflight_stage = "readiness"
                # This verifies dual-side demo readiness, flatness and the
                # authoritative risk baseline only after admission and
                # qualification.  A missing baseline is initialized once by
                # the Store before the broker can expose callback-safe cache.
                _readiness(store, rules, risk)
                if operator_demo_contract_mismatch:
                    approval_lease = _operator_demo_lease(
                        requested_duration,
                        risk,
                        shutdown_seconds,
                        config,
                    )
                broker = store.getbroker(**_demo_broker_kwargs(approval_lease, shutdown_seconds))
            else:
                broker_kwargs = {
                    "cash": 2000,
                    "position_mode": "dual_side",
                    "exchange_model": SimpleExchangeModel(),
                }
                if mode == "paper-live":
                    broker_kwargs.update(
                        account_risk_ledger_path=PAPER_RISK_LEDGER_PATH,
                        account_risk_venues=tuple(VENUE_SYMBOLS),
                    )
                broker = MixBroker(**broker_kwargs)
            for venue, rule in rules.items():
                broker.addcommissioninfo(
                    ComminfoFuturesPercent(
                        commission=float(rule.taker_fee), mult=float(rule.multiplier), margin=1
                    ),
                    name=VENUE_SYMBOLS[venue],
                )
            initial_value = decimal_value(broker.getvalue(), "initial_broker_value")
            cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
            cerebro.setbroker(broker)
            cerebro.addobserver(
                bt.observers.TradeLogger,
                obsname="trade_logger",
                log_dir=str(HERE / "reports" / "trade_logger"),
                log_positions=False,
                log_indicators=False,
                log_ticks=False,
                log_bars=False,
                log_value=False,
                log_position_snapshot=False,
            )
            for symbol in VENUE_SYMBOLS.values():
                cerebro.adddata(
                    store.getdata(
                        dataname=symbol,
                        timeframe=bt.TimeFrame.Ticks,
                        orderbook_as_ticks=True,
                        backfill_start=False,
                        qcheck=0.01,
                    ),
                    name=symbol,
                )
            cerebro.addstrategy(
                CrossExchangeArbitrageStrategy,
                rules=rules,
                risk=risk,
                model_qualification=qualifications,
                funding_snapshot_provider=_cached_funding_provider(
                    store, funding_settings["max_age_seconds"]
                ),
                funding_exchange_routes=EXCHANGES,
                funding_max_age_seconds=funding_settings["max_age_seconds"],
                funding_exit_window_seconds=funding_settings["exit_window_seconds"],
                execution_enabled=mode != "shadow",
                shadow=mode == "shadow",
                demo_execution_smoke=bool(demo_execution_smoke),
                **(
                    {"allow_operator_demo_calibration_contract_mismatch": True}
                    if operator_demo_contract_mismatch
                    else {}
                ),
            )
            if approval_lease is not None:
                expires_at = datetime.fromisoformat(approval_lease["expires_at"][:-1] + "+00:00")
                lease_active_seconds = (
                    decimal_value(
                        (expires_at - datetime.now(timezone.utc)).total_seconds(),
                        "approval active duration",
                    )
                    - shutdown_seconds
                )
                if lease_active_seconds < active_seconds:
                    raise DemoApprovalError(
                        "demo approval no longer covers the requested active window"
                    )
            timer = threading.Timer(float(active_seconds), cerebro.runstop)
            timer.daemon = True
            timer.start()
            try:
                if mode == "shadow":
                    shadow_execution_started = True
                strategy = cerebro.run()[0]
            finally:
                timer.cancel()
            trade_logger_report, strategy_report = _trade_logger_report(strategy)
            effective_strategy_report = strategy_report
            final_value = decimal_value(broker.getvalue(), "final_broker_value")
            broker_value_change = final_value - initial_value
            submitted = int(strategy_report.get("submitted_order_count", 0) or 0)
            fills = int(strategy_report.get("confirmed_fill_events", 0) or 0)
            if mode == "shadow":
                shadow_observed_execution = {
                    "orders_submitted": submitted,
                    "fills": fills,
                    "broker_value_change": str(broker_value_change),
                }
            if mode == "shadow" and (submitted or fills or broker_value_change != 0):
                raise RunnerConfigurationError("shadow mode produced an order, fill, or PnL")

            shutdown_state = None
            reconcile_snapshot = None
            execution_summary = None
            account_risk_snapshot = None
            approval_lease_status = None
            paper_flatness = None
            post_run_reconciliation = None
            if mode == "demo":
                shutdown_state = broker.get_shutdown_state()
                reconcile_snapshot = broker.get_last_reconcile_result()
                execution_summary = broker.get_execution_summary()
                approval_lease_status = broker.get_approval_lease_status()
                if strategy_report.get("reconciliation_required"):
                    strategy.confirm_remote_flat(
                        reconcile_snapshot,
                        execution_summary=execution_summary,
                    )
                    effective_strategy_report = dict(strategy.trade_logger_context())
                    post_run_reconciliation = _post_run_reconciliation_revision(
                        strategy_report,
                        effective_strategy_report,
                        reconcile_snapshot,
                        execution_summary,
                    )
                account_risk_snapshot = broker.get_account_risk_snapshot()
            elif mode == "paper-live":
                paper_flatness = _paper_flatness(broker)
                account_risk_snapshot = broker.get_account_risk_snapshot()

            metrics, economics_complete = _realized_metrics(effective_strategy_report)
            strategy_assessment_evidence = {
                "source": (
                    "post_run_reconciliation.reconciled_cross_venue_extension"
                    if post_run_reconciliation is not None
                    else "trade_logger.extensions.cross_venue"
                ),
                "cross_venue_sha256": _canonical_hash(effective_strategy_report),
            }
            report = {
                "status": "NETWORK_RUN_PENDING_SHUTDOWN_PROOF",
                "mode": mode,
                "evidence_level": (
                    "R2_SHADOW" if mode == "shadow" else "R3_DEMO" if mode == "demo" else "R1_PAPER"
                ),
                "research_status": candidate["research_status"],
                "candidate_sha256": candidate["candidate_sha256"],
                "config_sha256": candidate["config_sha256"],
                "normalized_config_sha256": _canonical_hash(config),
                "strategy_sha256": candidate["strategy_sha256"],
                "admission": admission,
                "approval_lease": approval_lease,
                "configuration": config,
                "duration_gate": duration_gate,
                "orders_submitted": submitted,
                "fills": fills,
                "partial_fill_ratio": None,
                "execution_status": "NOT_RUN" if mode == "shadow" else "EXECUTION_OBSERVED",
                "execution_economics_complete": economics_complete,
                "broker_value_change": str(broker_value_change),
                "cost_breakdown": effective_strategy_report.get("cost_breakdowns", []),
                "fee_source": fee_sources,
                "funding_source": funding_sources,
                "fee_rate_per_fill": {venue: str(rule.taker_fee) for venue, rule in rules.items()},
                "qualification": qualification_evidence,
                "reject_reasons": effective_strategy_report.get("reject_reasons", {}),
                "strategy": strategy_report,
                "strategy_assessment_evidence": strategy_assessment_evidence,
                "trade_logger": trade_logger_report,
                "post_run_reconciliation": post_run_reconciliation,
                "broker_shutdown": shutdown_state,
                "reconcile_snapshot": reconcile_snapshot,
                "execution_summary": execution_summary,
                "account_risk_snapshot": account_risk_snapshot,
                "approval_lease_status": approval_lease_status,
                "paper_flatness": paper_flatness,
                "profitability_claim": (
                    "NONE_MECHANICAL_DEMO_SMOKE_NOT_RESEARCH"
                    if demo_execution_smoke
                    else (
                        "NONE_READ_ONLY_SHADOW_DIAGNOSTIC"
                        if shadow_calibration_diagnostic_active
                        else "NONE_OBSERVATIONAL_ONLY"
                    )
                ),
            }
            if shadow_calibration_diagnostic_active:
                report["read_only_calibration_contract_diagnostic"] = admission.get(
                    "read_only_calibration_contract_diagnostic"
                )
            report.update(metrics)
            if demo_execution_smoke:
                report["mechanical_demo_smoke_requested"] = True
                report["execution_claim_scope"] = "MECHANICAL_DEMO_SMOKE_NOT_RESEARCH"
                report["mechanical_demo_smoke"] = {
                    "semantics": "MECHANICAL_DEMO_SMOKE_NOT_RESEARCH",
                    "state": effective_strategy_report.get(
                        "mechanical_demo_smoke_state", "UNKNOWN"
                    ),
                    "opening_order_count": int(
                        effective_strategy_report.get(
                            "mechanical_demo_smoke_opening_order_count", 0
                        )
                        or 0
                    ),
                    "opening_orders": effective_strategy_report.get(
                        "mechanical_demo_smoke_opening_orders", []
                    ),
                    "quantity_base": effective_strategy_report.get(
                        "mechanical_demo_smoke_quantity_base"
                    ),
                    "alpha_intent_history_used": False,
                    "profitability_claim": "NONE_MECHANICAL_DEMO_SMOKE_NOT_RESEARCH",
                }
    except Exception as exc:
        if preflight:
            report = _preflight_failure_report(candidate, config, admission, preflight_stage, exc)
        elif mode == "shadow":
            report = _shadow_failure_report(
                candidate,
                config,
                admission,
                preflight_stage,
                exc,
                observed_execution=shadow_observed_execution,
                execution_started=shadow_execution_started,
                read_only_calibration_diagnostic=shadow_calibration_diagnostic_active,
            )
        else:
            raise
    finally:
        if shadow_calibration_diagnostic_active and store is not None and report is not None:
            try:
                stream_health = store.get_stream_health()
            except Exception:
                stream_health = None
            report["shadow_orderbook_stream_health"] = (
                _shadow_orderbook_stream_health_summary(stream_health)
            )
        if one_shot_sdk_shutdown_proven:
            if store_health is None:
                store_health = {"shutdown_state": "UNKNOWN"}
        elif store is None:
            store_health = {"shutdown_state": "NOT_STARTED"}
        else:
            try:
                store_health = store.stop(timeout=shutdown_timeout_seconds)
            except Exception as exc:
                store_health = {
                    "shutdown_state": "FAIL",
                    "error_type": type(exc).__name__,
                }

    store_stop_proven = _store_shutdown_proven(store_health)
    report["store_health"] = (
        _preflight_store_health_summary(store_health)
        if preflight or mode == "shadow"
        else store_health
    )
    report["store_stop_proven"] = store_stop_proven
    if preflight:
        readiness_complete = _preflight_readiness_complete(report.get("readiness"))
        report["readiness_complete"] = readiness_complete
        if report.get("preflight_failure"):
            report["status"] = "PREFLIGHT_FAILED"
        else:
            report["status"] = (
                "PREFLIGHT_PASS"
                if store_stop_proven and readiness_complete
                else "PREFLIGHT_INCOMPLETE"
            )
        _attach_business_summary(report)
        return report
    if mode == "shadow":
        if report.get("shadow_failure"):
            report["status"] = "SHADOW_FAILED"
        elif one_shot:
            report["status"] = "SHADOW_ONE_SHOT_COMPLETE" if store_stop_proven else "INCOMPLETE"
        else:
            report["status"] = "SHADOW_PASS" if store_stop_proven else "INCOMPLETE"
    elif mode == "paper-live":
        risk_snapshot = report.get("account_risk_snapshot") or {}
        paper_safe = bool(
            store_stop_proven
            and (report.get("paper_flatness") or {}).get("flat") is True
            and risk_snapshot.get("evidence_complete") is True
            and risk_snapshot.get("durable") is True
            and report.get("execution_economics_complete") is True
            and not effective_strategy_report.get("reconciliation_required")
            and not effective_strategy_report.get("unknown_execution")
        )
        report["status"] = "PAPER_OBSERVATION_PASS" if paper_safe else "INCOMPLETE"
    else:
        shutdown_safe = (report.get("broker_shutdown") or {}).get("status") == "PASS"
        summary_safe = _execution_summary_proven(report.get("execution_summary"))
        risk_snapshot = report.get("account_risk_snapshot") or {}
        funding_safe = _funding_economics_proven(effective_strategy_report)
        lease_safe = _approval_lease_status_proven(
            report.get("approval_lease_status"),
            report.get("approval_lease"),
        )
        strategy_safe = bool(
            not effective_strategy_report.get("reconciliation_required")
            and not effective_strategy_report.get("unknown_execution")
            and (
                report["fills"] == 0 or effective_strategy_report.get("remote_flat_proven") is True
            )
        )
        demo_safe = bool(
            store_stop_proven
            and shutdown_safe
            and summary_safe
            and strategy_safe
            and report.get("execution_economics_complete") is True
            and report["fills"] > 0
            and funding_safe
            and risk_snapshot.get("evidence_complete") is True
            and risk_snapshot.get("durable") is True
            and lease_safe
        )
        if demo_execution_smoke:
            report["status"] = (
                "MECHANICAL_DEMO_SMOKE_PASS"
                if demo_safe
                else "MECHANICAL_DEMO_SMOKE_INCOMPLETE"
            )
        else:
            report["status"] = (
                "DEMO_EXECUTION_PASS"
                if demo_safe
                else ("INCOMPLETE_INSUFFICIENT_SAMPLE" if report["fills"] == 0 else "INCOMPLETE")
            )
    _attach_business_summary(report)
    return report


def build_parser():
    """Build the CLI argument parser for the runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, default="replay")
    parser.add_argument("--scenario", choices=SCENARIOS, default="profitable")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument(
        "--duration",
        type=float,
        help="seconds to observe; 0 runs a read-only shadow metadata one-shot",
    )
    parser.add_argument("--env-file", type=Path, default=HERE / ".env")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument(
        "--allow-rejected-demo-simulation",
        action="store_true",
        help="explicitly authorize the bounded demo-only path for this rejected candidate",
    )
    parser.add_argument(
        "--demo-execution-smoke",
        action="store_true",
        help=(
            "request one risk-bounded, mechanical 012_1 demo pair; requires demo mode and "
            "--allow-rejected-demo-simulation and is not research evidence"
        ),
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv=None):
    """Execute the CLI: dispatch to replay or network mode and emit the report.

    Writes the private JSON report to disk, prints it, and returns 0 only
    for passing statuses.  Shadow-mode failures are converted into a
    failure report instead of an exception; other modes re-raise.
    """
    args = build_parser().parse_args(argv)
    config = None
    try:
        config = load_config(args.config)
        duration = (
            args.duration
            if args.duration is not None
            else float(config.get("run_timeout_seconds", 0))
        )
        if not math.isfinite(duration) or duration < 0:
            raise RunnerConfigurationError("duration must be finite and non-negative")
        if args.preflight and args.mode != "demo":
            raise RunnerConfigurationError("--preflight is only valid with --mode demo")
        if args.allow_rejected_demo_simulation and args.mode != "demo":
            raise RunnerConfigurationError(
                "--allow-rejected-demo-simulation is only valid with --mode demo"
            )
        if args.demo_execution_smoke and args.mode != "demo":
            raise RunnerConfigurationError("--demo-execution-smoke is only valid with --mode demo")
        if args.demo_execution_smoke and args.preflight:
            raise RunnerConfigurationError("--demo-execution-smoke cannot be combined with --preflight")
        if args.demo_execution_smoke and not args.allow_rejected_demo_simulation:
            raise DemoApprovalError(
                "--demo-execution-smoke requires --allow-rejected-demo-simulation"
            )
        # Demo must use the repository-canonical manifest; the other modes use
        # this folder's self-contained copy unless the operator overrides it.
        manifest_path = (
            args.manifest
            if args.manifest is not None
            else (REPO_CANONICAL_MANIFEST if args.mode == "demo" else MANIFEST_PATH)
        )
        report = (
            run_replay(args.scenario, args.config, manifest_path)
            if args.mode == "replay"
            else run_network(
                args.mode,
                duration,
                args.config,
                args.env_file,
                args.preflight,
                manifest_path,
                args.allow_rejected_demo_simulation,
                args.demo_execution_smoke,
            )
        )
    except Exception as exc:
        if args.mode != "shadow":
            raise
        report = _shadow_cli_failure_report(config, exc)
    output = args.output or HERE / "reports" / f"{args.mode}-{args.scenario}.json"
    write_private_json_report(output, report)
    print(serialize_private_json_report(report))
    return (
        0
        if report["status"]
        in {
            "FORMULA_CHECK_PASS",
            "SHADOW_PASS",
            "PAPER_OBSERVATION_PASS",
            "DEMO_EXECUTION_PASS",
            "MECHANICAL_DEMO_SMOKE_PASS",
            "PREFLIGHT_PASS",
        }
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_CONFIG",
    "DEMO_APPROVAL_TRUST_ROOT",
    "DEMO_APPROVAL_PUBLIC_KEY_SHA256",
    "DemoApprovalError",
    "MANIFEST_PATH",
    "MODES",
    "RunnerConfigurationError",
    "business_summary",
    "business_summary_hash",
    "load_candidate",
    "load_config",
    "require_demo_approval",
    "required_observation_duration",
    "risk_from_config",
    "run_network",
    "run_replay",
    "validate_duration",
]
