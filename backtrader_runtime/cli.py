"""The deliberately small configuration-first ``bt-runtime`` CLI skeleton."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence, TextIO

from .config import load_runtime_config
from .evidence_bundle import collect_iteration41_evidence
from .errors import CONFIG_SCHEMA_UNSUPPORTED, PRESET_POLICY_VIOLATION, RuntimeConfigError
from .policy import get_preset_policy, preset_names
from .registry import (
    RuntimeRegistry,
    bootstrap_runtime_config,
    bootstrap_runtime_set,
    default_runtime_registry,
    select_bootstrap_preset,
    validate_runtime_config,
)


_OVERRIDE_ENVIRONMENT_NAMES = (
    "BT_RUNTIME_MODE",
    "BT_RUNTIME_PRESET",
    "BACKTRADER_RUNTIME_MODE",
    "BACKTRADER_RUNTIME_PRESET",
)
_DISALLOWED_RUN_ARGUMENTS = ("--mode", "--preset", "--config", "--runtime-mode", "--runtime-preset")
_REPORT_SUMMARY_FIELDS = (
    "status",
    "admission_status",
    "hft_status",
    "candidate_id",
    "scenario",
    "actual_fills",
    "external_network_requests",
    "external_write_requests",
    "external_request_counts",
    "evidence_boundary",
)
_RUNTIME_REPORT_FIELDS = (
    "scope",
    "evidence_boundary",
    "allows_network",
    "allows_external_writes",
    "allows_production_writes",
)
_DOCTOR_LIVE_SAFE_RELOAD_REASONS = frozenset(
    (
        "approval_receipt_missing",
        "environment_override_not_allowed",
        "parameter_not_registered",
        "required_capability_not_declared",
        "secrets_ref_not_registered",
    )
)
_CTP_SIMNOW_PREFLIGHT_SUPERVISOR_REASON = "ctp_simnow_preflight_supervisor_required"
_CTP_SIMNOW_PREFLIGHT_SUPERVISOR_ACTION = "preflight_requires_process_supervisor"
_CTP_SIMNOW_PREFLIGHT_SUPERVISOR_NOTE = (
    "ordinary bt-runtime preflight is disabled until native CTP startup and shutdown run under a "
    "hard process supervisor; use doctor for offline config validation. This rejection happens "
    "before credentials, SDK import, or provider/network I/O"
)


class _ParserError(Exception):
    pass


class _RuntimeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ParserError(message)


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser without importing runtime capabilities."""

    parser = _RuntimeArgumentParser(
        prog="bt-runtime",
        description="Configuration-first Backtrader runtime launcher",
    )
    commands = parser.add_subparsers(dest="command")
    commands.required = True

    bootstrap = commands.add_parser(
        "bootstrap", help="atomically create safe schema-v4 config files"
    )
    bootstrap_target = bootstrap.add_mutually_exclusive_group(required=True)
    bootstrap_target.add_argument("--strategy-dir", type=Path)
    bootstrap_target.add_argument(
        "--runtime-set",
        help="reviewed code-owned runtime set to bootstrap; never a filesystem manifest path",
    )
    bootstrap.add_argument(
        "--preset",
        default=None,
        choices=preset_names(),
        help="optional reviewed preset; defaults to this runtime's safest registered preset",
    )

    for command_name, command_help in (
        (
            "prepare-ctp-config",
            "prepare the protected shared CTP config.yaml from explicit private source files",
        ),
        ("prepare-ctp-simnow-config", "legacy alias for prepare-ctp-config"),
    ):
        prepare_ctp = commands.add_parser(command_name, help=command_help)
        prepare_ctp.add_argument(
            "--source-env",
            type=Path,
            help=(
                "absolute owner-only .env path; may combine with one YAML. If it supplies TD/MD "
                "fields alongside YAML front_pairs, both must exactly match one listed candidate"
            ),
        )
        prepare_ctp.add_argument(
            "--source-yaml",
            type=Path,
            help=(
                "absolute owner-only YAML path with a canonical ctp mapping (or legacy "
                "ctp_simnow mapping); direct md_front/td_front fields or explicit front_pairs; "
                "never auto-discovered"
            ),
        )
        prepare_ctp.add_argument(
            "--source-collector-yaml",
            type=Path,
            help="absolute path to an owner-only collector YAML with a ctp mapping; requires a second source for instrument/exchange/HedgeFlag",
        )
        prepare_ctp.add_argument(
            "--runtime-id",
            choices=sorted(_ctp_private_readonly_runtime_ids()),
            default=None,
            help=(
                "select one reviewed private CTP config target; defaults to the existing "
                "013_3 target"
            ),
        )

    commands.add_parser(
        "collect-evidence",
        help="collect code-owned local Iteration 41 metadata without runtime, provider, or network I/O",
    )

    for name, help_text in (
        ("validate", "validate config and its sealed runtime policy without provider I/O"),
        ("doctor", "print redacted offline configuration diagnostics"),
        (
            "check-ctp-fronts",
            "probe configured CTP MD/TD TCP fronts from a sealed private sandbox config",
        ),
        ("run", "validate, then dispatch the runtime's code-owned entrypoint"),
        (
            "preflight",
            "private read-only preflight where available; registered 007/013_3 CTP routes are disabled pending a bounded supervisor",
        ),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--strategy-dir", required=True, type=Path)
        if name == "run":
            command.add_argument(
                "--confirm-live",
                action="store_true",
                help="confirm an already-approved live contract; never changes its mode",
            )
            command.add_argument(
                "--full-report",
                action="store_true",
                help="emit the complete local runner report after safe dispatch",
            )
    return parser


def _write_payload(stream: TextIO, payload: dict) -> None:
    stream.write(json.dumps(payload, default=str, ensure_ascii=True, sort_keys=True) + "\n")


def _write_error(stream: TextIO, error: RuntimeConfigError) -> None:
    _write_payload(stream, error.as_dict())


def _profile_dispatch_unavailable() -> RuntimeConfigError:
    return RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        "profile-scoped runtime dispatch is not enabled",
        field_path="runtime.preset",
        reason="profile_dispatch_unavailable",
    )


def dispatch_registered_runtime(
    effective: object, registry: RuntimeRegistry
) -> Mapping[str, object]:
    """Import dispatch only after ``run`` passes the offline policy gates.

    Keeping this import here lets ``bootstrap``, ``validate``, and ``doctor``
    remain in the configuration-only surface.  The wrapper retains the module
    attribute used by reviewed programmatic callers while avoiding a runner
    import merely to render offline diagnostics.
    """

    from .runner import dispatch_registered_runtime as dispatch

    return dispatch(effective, registry)


def dispatch_registered_ctp_simnow_readonly_preflight(
    effective: object, registry: RuntimeRegistry
) -> object:
    """Import the CTP composition only after the CLI policy gates succeed."""

    from .ctp_simnow_operator import (
        dispatch_registered_ctp_simnow_readonly_preflight as dispatch,
    )

    return dispatch(effective, registry)


def dispatch_registered_ctp_front_check(effective: object, registry: RuntimeRegistry) -> object:
    """Import the credential-free front diagnostic after offline policy gates."""

    from .ctp_configured_front_check import check_configured_ctp_fronts

    return check_configured_ctp_fronts(effective, registry)


def _ctp_private_readonly_runtime_ids() -> frozenset:
    """Return the exact registered CTP private read-only runtime identities."""

    from .inventory import (
        ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
        ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    )

    return frozenset(
        (
            ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
            ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
        )
    )


def _doctor_write_boundary(
    *, allows_external_writes: bool, allows_hypothetical_fills: bool, blocked: bool = False
) -> tuple:
    """Return the operator-facing write and PnL boundaries for one policy."""

    if blocked:
        return (
            "blocked_before_external_writes",
            "not_started_provider_reconciliation_required",
        )
    if allows_external_writes:
        return "managed_preflight_and_approval_required", "provider_reconciliation_required"
    if allows_hypothetical_fills:
        return "zero_external_writes_local_simulation", "local_hypothetical_only"
    return "zero_external_writes", "not_applicable_without_external_fills"


def _doctor_destination(order_route: object, account_access: object) -> str:
    """Name a route in terms an operator can distinguish without loading it."""

    if account_access == "sandbox_private_read":
        return "sandbox_private_account_read"
    if not order_route:
        return "local_runtime"
    if account_access == "fake_provider":
        return "offline_fake_provider_managed_execution"
    if order_route == "managed_execution" and account_access:
        return "managed_execution:{0}".format(account_access)
    return str(order_route)


def _doctor_operator_summary(
    *,
    mode: str,
    preset: str,
    environment: str,
    order_route: object,
    account_access: object,
    allows_external_writes: bool,
    allows_hypothetical_fills: bool,
    required_capabilities: Sequence[str],
    requires_approval: bool,
    blocked: bool = False,
    profile_dispatch_available: bool = True,
    profile_dispatch_unavailable_reason: Optional[str] = None,
) -> dict:
    """Build a redacted operator summary from already-resolved policy data."""

    write_boundary, pnl_source = _doctor_write_boundary(
        allows_external_writes=allows_external_writes,
        allows_hypothetical_fills=allows_hypothetical_fills,
        blocked=blocked or not profile_dispatch_available,
    )
    summary = {
        "mode": mode,
        "preset": preset,
        "destination": (
            _doctor_destination(order_route, account_access)
            if profile_dispatch_available
            else "profile_dispatch_unavailable"
        ),
        "environment": environment,
        "write_boundary": write_boundary,
        "pnl_source": pnl_source,
        "required_capabilities": list(required_capabilities),
        "requires_approval": requires_approval,
    }
    if not profile_dispatch_available:
        summary["profile_dispatch_available"] = False
    if profile_dispatch_unavailable_reason is not None:
        summary["profile_dispatch_unavailable_reason"] = profile_dispatch_unavailable_reason
    if blocked or not profile_dispatch_available:
        summary["admission_status"] = "blocked"
    return summary


def _ctp_private_operator_actions(
    *,
    strategy_dir: Path,
    mode: str,
    preset: str,
    profile_dispatch_available: bool,
    profile_dispatch_unavailable_reason: Optional[str],
    unavailable_live_profile_note: str = "The registered 013_3 production profile is unavailable.",
) -> dict:
    """Give registered private CTP operators a redacted action/status matrix.

    The matrix reports only code-owned route status and the requested
    mode/preset. It deliberately does not copy private CTP fields, configured
    front addresses, or credential material from the sealed config.
    """

    live_requested = mode == "live" and preset == "managed_live_direct"
    dispatch_reason = profile_dispatch_unavailable_reason or "profile_dispatch_unavailable"
    return {
        "mode": mode,
        "preset": preset,
        "doctor": {"status": "offline"},
        "check-ctp-fronts": (
            {
                "status": "tcp_only",
                "command": [
                    "bt-runtime",
                    "check-ctp-fronts",
                    "--strategy-dir",
                    str(strategy_dir),
                ],
                "note": (
                    "credential-free TCP reachability only; it does not test login or authorize "
                    "trading"
                ),
            }
            if mode == "simulation" and preset == "sandbox"
            else {"status": "unavailable", "reason": "ctp_front_check_profile_required"}
        ),
        "preflight": {
            "status": "disabled",
            "reason": (
                _CTP_SIMNOW_PREFLIGHT_SUPERVISOR_REASON
                if mode == "simulation" and preset == "sandbox"
                else "managed_live_direct_profile_unavailable"
            ),
        },
        "run": (
            {"status": "available"}
            if profile_dispatch_available
            else {"status": "unavailable", "reason": dispatch_reason}
        ),
        "live": {
            "status": "unavailable",
            "reason": "managed_live_direct_profile_unavailable",
            "requested": live_requested,
            "authorization": "not_granted",
            "note": (
                "The config requests live/managed_live_direct; that request does not authorize "
                "production trading."
                if live_requested
                else unavailable_live_profile_note
            ),
        },
    }


def _blocked_live_doctor_diagnostic(
    error: RuntimeConfigError,
    strategy_dir: Path,
    registry: RuntimeRegistry,
) -> Optional[dict]:
    """Explain a statically valid but unapproved live policy without probing it.

    The normal resolver deliberately fails before any live runtime dispatch.
    Doctor still has enough information in the strict local config and sealed
    registry to say *what is blocked*.  This helper must stay local: it reads
    no secret, imports no runner, and never starts provider preflight.
    """

    ctp_profile_unavailable_error = error.reason == "managed_live_direct_profile_unavailable"
    if error.reason not in _DOCTOR_LIVE_SAFE_RELOAD_REASONS and not ctp_profile_unavailable_error:
        return None
    try:
        config = load_runtime_config(strategy_dir, registry=registry)
        registration = registry.require_runtime_dir(config.strategy_dir)
    except RuntimeConfigError:
        return None
    policy = get_preset_policy(config.preset)
    profile = registration.profile_for(config.mode, config.preset)
    if config.mode != "live" or policy is None or config.strategy_id != registration.strategy_id:
        return None
    from .inventory import (
        ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
        ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    )

    ctp_private_live_unavailable = (
        registration.runtime_id
        in (ITERATION41_007_CTP_PRIVATE_RUNTIME_ID, ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID)
        and config.preset == "managed_live_direct"
        and profile is None
        and error.reason == "managed_live_direct_profile_unavailable"
        and any(
            item.mode == "live"
            and item.preset == "managed_live_direct"
            and item.reason == "managed_live_direct_profile_unavailable"
            for item in registration.unavailable_mode_profiles
        )
    )
    if ctp_profile_unavailable_error and not ctp_private_live_unavailable:
        return None
    if not ctp_private_live_unavailable and (
        (registration.profiles and profile is None)
        or (not registration.profiles and config.preset not in registration.allowed_presets)
    ):
        return None
    if ctp_private_live_unavailable:
        next_actions = _next_actions_for_error(error, strategy_dir, registry=registry)
        unavailable_live_profile_note = (
            "The registered 007 CTP live profile is unavailable."
            if registration.runtime_id == ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
            else "The registered 013_3 production profile is unavailable."
        )
        return {
            "offline": True,
            "provider_preflight_started": False,
            "operator_summary": _doctor_operator_summary(
                mode=config.mode,
                preset=config.preset,
                environment=policy.environment,
                order_route=policy.order_route,
                account_access=policy.account_access,
                allows_external_writes=policy.allows_external_writes,
                allows_hypothetical_fills=policy.allows_hypothetical_fills,
                required_capabilities=policy.required_capabilities,
                requires_approval=policy.requires_approval,
                blocked=True,
                profile_dispatch_available=False,
                profile_dispatch_unavailable_reason="managed_live_direct_profile_unavailable",
            ),
            "blockers": [_error_blocker(error)],
            "next_actions": next_actions,
            "profile_dispatch_available": False,
            "profile_dispatch_unavailable_reason": "managed_live_direct_profile_unavailable",
            "operator_actions": _ctp_private_operator_actions(
                strategy_dir=strategy_dir,
                mode=config.mode,
                preset=config.preset,
                profile_dispatch_available=False,
                profile_dispatch_unavailable_reason="managed_live_direct_profile_unavailable",
                unavailable_live_profile_note=unavailable_live_profile_note,
            ),
        }
    policy_values = registration if profile is None else profile

    related_errors = [error]
    if policy.requires_approval and policy_values.approval_receipt_digest is None:
        related_errors.append(
            RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the registered write-capable profile has no trusted approval receipt",
                field_path="runtime.preset",
                reason="approval_receipt_missing",
            )
        )
    missing_capabilities = tuple(
        capability
        for capability in policy.required_capabilities
        if capability not in policy_values.available_capabilities
    )
    if missing_capabilities:
        related_errors.append(
            RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the registered profile lacks a required managed capability",
                field_path="runtime.preset",
                reason="required_capability_not_declared",
            )
        )

    blockers = []
    next_actions = []
    profile_dispatch_available = profile is None
    if not profile_dispatch_available:
        next_actions.append(
            {
                "action": "review_profile_dispatch",
                "field_path": "runtime.preset",
                "note": "profile validation is offline; profile-scoped dispatch is not enabled",
            }
        )
    live_action = {
        "action": "review_live_contract",
        "note": (
            "live remains blocked. A reviewed deployment must bind the required "
            "capabilities and a trusted approval receipt; live confirmation cannot "
            "bypass this block."
        ),
    }
    for related_error in related_errors:
        blocker = _error_blocker(related_error)
        if blocker not in blockers:
            blockers.append(blocker)
        if related_error.reason in (
            "approval_receipt_missing",
            "required_capability_not_declared",
        ):
            if live_action not in next_actions:
                next_actions.append(live_action)
            continue
        for action in _next_actions_for_error(related_error, strategy_dir, registry=registry):
            if action not in next_actions:
                next_actions.append(action)

    return {
        "offline": True,
        "provider_preflight_started": False,
        "operator_summary": _doctor_operator_summary(
            mode=config.mode,
            preset=config.preset,
            environment=policy.environment,
            order_route=policy.order_route,
            account_access=policy.account_access,
            allows_external_writes=policy.allows_external_writes,
            allows_hypothetical_fills=policy.allows_hypothetical_fills,
            required_capabilities=policy.required_capabilities,
            requires_approval=policy.requires_approval,
            blocked=True,
            profile_dispatch_available=profile_dispatch_available,
            profile_dispatch_unavailable_reason=(
                None if profile_dispatch_available else "profile_dispatch_unavailable"
            ),
        ),
        "blockers": blockers,
        "next_actions": next_actions,
        "profile_dispatch_available": profile_dispatch_available,
        "profile_dispatch_unavailable_reason": (
            None if profile_dispatch_available else "profile_dispatch_unavailable"
        ),
    }


def _error_blocker(error: RuntimeConfigError) -> dict:
    """Project a safe error into the compact diagnostic blocker vocabulary."""

    return {
        "field_path": error.field_path or "config.yaml",
        "reason": error.reason or "runtime_validation_failed",
        "message": error.message,
    }


def _next_actions_for_error(
    error: RuntimeConfigError,
    strategy_dir: Optional[Path],
    *,
    registry: Optional[RuntimeRegistry] = None,
    rejected_arguments: Sequence[str] = (),
) -> list:
    """Return one safe, operator-actionable response to a rejection.

    The action never supplies an alternate mode, preset, secret, route, or
    runner.  It either points to the only safe bootstrap command or tells the
    operator which reviewed record needs attention.  Keeping this mapping in
    the CLI means ``bootstrap``, ``validate``, ``doctor``, and failed ``run``
    share one vocabulary without importing a runtime.
    """

    reason = error.reason or ""
    if reason == _CTP_SIMNOW_PREFLIGHT_SUPERVISOR_REASON:
        return [
            {
                "action": _CTP_SIMNOW_PREFLIGHT_SUPERVISOR_ACTION,
                "field_path": error.field_path or "command",
                "note": _CTP_SIMNOW_PREFLIGHT_SUPERVISOR_NOTE,
            }
        ]
    if reason in ("provider_dependency_version_unreviewed", "provider_dependency_unavailable"):
        return [
            {
                "action": "install_reviewed_public_shadow_dependencies",
                "field_path": error.field_path or "runtime.dependencies",
                "note": (
                    "from the Backtrader repository root, install the reviewed public OKX "
                    "shadow dependency pair in the same Python environment as bt-runtime; "
                    "this does not grant account or order access"
                ),
                "command": ["python", "-m", "pip", "install", "-e", ".[okx-public-shadow]"],
            }
        ]
    if reason in (
        "public_market_startup_incomplete",
        "public_market_read_failed",
        "public_market_observation_empty",
        "provider_shutdown_incomplete",
        "provider_hard_timeout",
        "provider_hard_timeout_loop_unavailable",
    ):
        return [
            {
                "action": "inspect_public_market_session",
                "field_path": error.field_path or "runtime.runner",
                "note": (
                    "the bounded public-market run did not complete; inspect provider/network "
                    "availability and the reviewed dependency pair before retrying this same config"
                ),
            }
        ]
    if reason == "ctp_private_source_incomplete":
        return [
            {
                "action": "complete_explicit_ctp_source",
                "field_path": error.field_path or "ctp",
                "note": (
                    error.message
                    + "; fill these names in the explicitly selected local .env or YAML source, "
                    "then rerun prepare-ctp-config. No config was written"
                ),
            }
        ]
    if reason.startswith("private_source_"):
        return [
            {
                "action": "protect_explicit_source",
                "field_path": "source",
                "note": (
                    "restrict the explicitly named local .env or YAML source to the current user "
                    "(Windows protected owner-only ACL or POSIX owner-only permissions), then "
                    "rerun the same command. The source content is not read before this check"
                ),
            }
        ]
    if reason.startswith("private_target_"):
        return [
            {
                "action": "repair_private_target",
                "field_path": error.field_path or "config.yaml",
                "note": (
                    "check the reserved runtime-ctp-private directory and its current-user "
                    "ownership; the helper will restrict its permissions only after all source "
                    "fields pass validation"
                ),
            }
        ]
    if reason.startswith(("source_", "private_config_")):
        return [
            {
                "action": "review_private_config_source",
                "field_path": error.field_path or "source",
                "note": (
                    "check the explicitly selected local source syntax and required schema fields; "
                    "the helper never interpolates values, selects endpoints, or overwrites config.yaml"
                ),
            }
        ]
    if reason == "missing_config" and strategy_dir is not None:
        if registry is not None:
            try:
                from .ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding

                registration = registry.require_runtime_dir(strategy_dir)
                binding = registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
                if type(binding) is CtpSimNowConfigReadOnlyBinding:
                    return [
                        {
                            "action": "prepare_ctp_private_config",
                            "field_path": "config.yaml",
                            "note": (
                                "prepare the single protected, Git-ignored runtime-ctp-private/config.yaml "
                                "with the canonical top-level ctp mapping, using one or two "
                                "explicit owner-only local sources that together contain either a "
                                "direct md_front/td_front pair or an explicit front_pairs list, plus "
                                "instrument_id, exchange_id, hedge_flag and all five CTP "
                                "authentication fields. Overlapping fields must agree. The setup "
                                "command does not read process environment variables, infer endpoints, "
                                "or authorize provider access; the registered route remains "
                                "simulation/sandbox read-only. Bootstrap cannot create this private "
                                "configuration, and changing mode/preset alone does not register a "
                                "production route"
                            ),
                            "command_examples": [
                                [
                                    "bt-runtime",
                                    "prepare-ctp-config",
                                    "--source-env",
                                    "<absolute-local-path>",
                                ],
                                [
                                    "bt-runtime",
                                    "prepare-ctp-config",
                                    "--source-yaml",
                                    "<absolute-local-path>",
                                ],
                                [
                                    "bt-runtime",
                                    "prepare-ctp-config",
                                    "--source-collector-yaml",
                                    "<absolute-owner-only-collector-yaml>",
                                    "--source-yaml",
                                    "<absolute-owner-only-contract-scope-yaml>",
                                ],
                            ],
                        }
                    ]
            except RuntimeConfigError:
                pass
        return [
            {
                "action": "bootstrap",
                "command": ["bt-runtime", "bootstrap", "--strategy-dir", str(strategy_dir)],
                "note": "creates only the reviewed safe config; it never overwrites an existing file",
            }
        ]
    if reason == "ctp_simnow_preflight_front_policy_required":
        return [
            {
                "action": "review_registration",
                "field_path": "runtime.preset",
                "note": (
                    "replace the legacy static SimNow profile binding with a reviewed config-driven "
                    "front-pair policy"
                ),
            }
        ]
    if reason in (
        "ctp_simnow_preflight_route_unregistered",
        "runtime_not_registered",
        "invalid_runtime_directory",
        "runtime_directory_unavailable",
        "runtime_set_not_registered",
        "registry_not_trusted",
    ):
        return [
            {
                "action": "review_registration",
                "field_path": error.field_path or "strategy_dir",
                "note": (
                    "use a reviewed registered runtime or runtime set; the CLI never discovers "
                    "a route from the current directory, an environment variable, or AI output"
                ),
            }
        ]
    if reason in ("config_exists", "existing_config_differs"):
        action = {
            "action": "review_existing_config",
            "field_path": "config.yaml",
            "note": "the existing file is preserved; inspect it with offline doctor before any reviewed edit",
        }
        if strategy_dir is not None:
            action["command"] = ["bt-runtime", "doctor", "--strategy-dir", str(strategy_dir)]
        return [action]
    if reason in (
        "inline_secret",
        "invalid_secrets_ref",
        "secrets_not_allowed_for_preset",
        "secrets_ref_not_registered",
        "offline_managed_execution_forbids_secrets",
    ):
        return [
            {
                "action": "review_secret_reference",
                "field_path": error.field_path or "secrets_ref",
                "note": (
                    "ordinary runtimes use only a reviewed opaque secret reference; the "
                    "CTP SimNow simulation/sandbox private config_yaml profile is a separate "
                    "strictly validated local exception. Review this runtime's registered "
                    "secret source, then run doctor again"
                ),
            }
        ]
    if reason == "ctp_simnow_private_config_required":
        return [
            {
                "action": "prepare_ctp_private_config",
                "field_path": "config.yaml",
                "note": (
                    "bootstrap cannot create CTP account and front fields; see "
                    "examples/013_3_sa_midfreq_simnow/runtime-ctp-private/README.md for the "
                    "source schema, then run bt-runtime prepare-ctp-config with an explicit "
                    "owner-only source to create the protected, Git-ignored config.yaml"
                ),
            }
        ]
    if reason.startswith(("private_config_", "config_yaml_windows_")):
        return [
            {
                "action": "protect_ctp_private_config",
                "field_path": "config.yaml",
                "note": (
                    "keep the private config untracked; restrict the runtime "
                    "directory and config file to the current user and trusted system "
                    "administrators, then run doctor again"
                ),
            }
        ]
    if reason in (
        "ctp_simnow_preflight_front_rejected",
        "ctp_simnow_preflight_front_probe_rejected",
    ):
        return [
            {
                "action": "check_configured_ctp_fronts",
                "field_path": "ctp.front_pairs",
                "note": (
                    "check the exact MD/TD addresses in config.yaml and their network "
                    "reachability; only configured pairs can be selected"
                ),
            }
        ]
    if reason in (
        "ctp_simnow_preflight_capability_origin_rejected",
        "ctp_simnow_preflight_capability_provenance_rejected",
    ):
        return [
            {
                "action": "install_reviewed_ctp_sdk_wheels",
                "field_path": "runtime.capabilities",
                "note": (
                    "install the independently reviewed and code-pinned bt_api_base and "
                    "bt_api_ctp wheels in this Python environment; editable or source "
                    "installs cannot pass private-account preflight"
                ),
            }
        ]
    if reason == "managed_live_direct_profile_unavailable":
        return [
            {
                "action": "review_live_enablement",
                "field_path": "runtime.preset",
                "note": (
                    "this same protected config.yaml is the future input to one shared CTP execution runner for simulation and live mode, "
                    "shared-runner live dispatch and production-specific admission are not enabled, and editing mode or parameters alone does not enable trading; "
                    "keep the zero-write sandbox profile until the reviewed live route is available"
                ),
            }
        ]
    if (
        reason == "profile_dispatch_unavailable"
        and registry is not None
        and strategy_dir is not None
    ):
        try:
            registration = registry.require_runtime_dir(strategy_dir)
            from .ctp_sandbox_readonly_admission import (
                require_ctp_sandbox_profile_registration,
            )

            require_ctp_sandbox_profile_registration(registration, registry)
        except Exception:
            pass
        else:
            return [
                {
                    "action": "preflight",
                    "command": [
                        "bt-runtime",
                        "preflight",
                        "--strategy-dir",
                        str(strategy_dir),
                    ],
                    "note": (
                        "this profile has no run entrypoint for strategy execution; the exact CTP "
                        "read-only preflight remains available and grants no write authority"
                    ),
                }
            ]
    if reason in (
        "unsupported_mode",
        "unsupported_preset",
        "mode_preset_mismatch",
        "preset_not_registered",
        "strategy_id_not_registered",
        "parameter_not_registered",
        "runtime_control_field_not_allowed",
        "environment_interpolation_not_allowed",
    ):
        return [
            {
                "action": "review_configuration",
                "field_path": error.field_path or "config.yaml",
                "note": (
                    "make this field match the reviewed registration instead of passing an override, "
                    "then run doctor again"
                ),
            }
        ]
    if reason == "environment_override_not_allowed":
        return [
            {
                "action": "remove_environment_override",
                "field_path": error.field_path or "environment",
                "note": (
                    "remove this variable; environment values cannot choose mode or preset. "
                    "The reviewed config.yaml remains authoritative"
                ),
            }
        ]
    if reason == "cli_override_not_allowed":
        action = {
            "action": "remove_cli_override",
            "field_path": error.field_path or "argv",
            "note": (
                "remove mode, preset, config, or runtime override flags; they cannot change the "
                "reviewed config.yaml"
            ),
        }
        if rejected_arguments:
            action["rejected_arguments"] = list(rejected_arguments)
        return [action]
    if reason == "cli_argument_not_allowed":
        return [
            {
                "action": "use_explicit_registered_runtime",
                "field_path": error.field_path or "argv",
                "note": (
                    "provide one supported command and its explicit --strategy-dir; the CLI never "
                    "uses CWD, arbitrary config paths, or AI-produced arguments as a runtime"
                ),
            }
        ]
    if reason in (
        "approval_receipt_missing",
        "required_capability_not_declared",
        "live_confirmation_required",
        "live_confirmation_not_applicable",
    ):
        return [
            {
                "action": "review_live_contract",
                "field_path": error.field_path or "runtime.preset",
                "note": (
                    "live remains blocked until a reviewed deployment binds the required capabilities "
                    "and trusted approval; confirmation cannot change mode, account, or scope"
                ),
            }
        ]
    if reason in (
        "runner_not_registered",
        "runner_entrypoint_invalid",
        "runner_report_invalid",
        "ctp_simnow_preflight_route_unregistered",
    ):
        if reason == "runner_not_registered" and strategy_dir is not None and registry is not None:
            try:
                registration = registry.require_runtime_dir(strategy_dir)
                _require_config_driven_ctp_binding(registry, registration.runtime_id)
            except RuntimeConfigError:
                pass
            else:
                return [
                    {
                        "action": "preflight",
                        "field_path": error.field_path or "runner",
                        "command": [
                            "bt-runtime",
                            "preflight",
                            "--strategy-dir",
                            str(strategy_dir),
                        ],
                        "note": (
                            "this registered CTP private-read runtime has no run entrypoint; use "
                            "preflight for its bounded read-only checks, which grant no write authority"
                        ),
                    }
                ]
        return [
            {
                "action": "review_registration",
                "field_path": error.field_path or "runner",
                "note": (
                    "a code-owned registered route is required; no path, module, scope, or "
                    "plugin override is accepted"
                ),
            }
        ]
    if reason == "capability_dependency_missing":
        action = {
            "action": "install_runtime_dependency",
            "field_path": error.field_path or "runtime.capabilities",
            "note": (
                "install the reviewed local SDK package that provides this capability in the same "
                "Python environment used by bt-runtime, then rerun the registered runtime"
            ),
        }
        if strategy_dir is not None:
            action["command"] = [
                "bt-runtime",
                "run",
                "--strategy-dir",
                str(strategy_dir),
            ]
        return [action]
    return [
        {
            "action": "review_configuration",
            "field_path": error.field_path or "config.yaml",
            "note": "correct the reported field in the registered local config, then run doctor again",
        }
    ]


def _operator_error_payload(
    error: RuntimeConfigError,
    *,
    command: Optional[str],
    strategy_dir: Optional[Path],
    registry: RuntimeRegistry,
    additional_errors: Sequence[RuntimeConfigError] = (),
    rejected_arguments: Sequence[str] = (),
    dispatch_started: bool = False,
) -> dict:
    """Add offline next steps to every CLI rejection without loosening a gate.

    A primary loader/policy error remains the top-level stable error.  When
    independently observable environment override attempts are also present,
    they are returned together as blockers so an operator can clear them in one
    pass.  The strict loader intentionally remains first-error for malformed
    YAML because parsing arbitrary invalid source twice would risk exposing or
    normalising untrusted configuration text.
    """

    payload = error.as_dict()
    blocked_live = None
    if command == "doctor" and strategy_dir is not None:
        blocked_live = _blocked_live_doctor_diagnostic(error, strategy_dir, registry)
    if blocked_live is None:
        # These dependency/origin errors are raised before a client is
        # constructed. Other dispatch failures may have crossed the I/O
        # boundary, so the CLI must not label them offline by default.
        provider_io_may_have_started = dispatch_started and error.reason not in (
            "capability_dependency_missing",
            "provider_dependency_version_unreviewed",
            "provider_dependency_unavailable",
            "provider_origin_untrusted",
            "strategy_callback_dependency_unavailable",
            "strategy_callback_initialization_failed",
            # The config-driven CTP binding can reject malformed front
            # selection before any transport probe or provider access. A
            # failed TCP probe is not offline and is intentionally omitted.
            "ctp_simnow_preflight_front_rejected",
        )
        diagnostic = {
            "offline": not provider_io_may_have_started,
            "provider_preflight_started": provider_io_may_have_started and command == "preflight",
            "next_actions": _next_actions_for_error(
                error,
                strategy_dir,
                registry=registry,
                rejected_arguments=rejected_arguments,
            ),
        }
        if provider_io_may_have_started:
            diagnostic["provider_io_may_have_started"] = True
    else:
        diagnostic = blocked_live

    if additional_errors:
        blockers = diagnostic.get("blockers")
        if blockers is None:
            blockers = [_error_blocker(error)]
            diagnostic["blockers"] = blockers
        existing = {(item.get("field_path"), item.get("reason")) for item in blockers}
        actions = diagnostic["next_actions"]
        for additional in additional_errors:
            blocker = _error_blocker(additional)
            key = (blocker["field_path"], blocker["reason"])
            if key in existing:
                continue
            blockers.append(blocker)
            actions.extend(_next_actions_for_error(additional, strategy_dir, registry=registry))
            existing.add(key)

    payload["diagnostic"] = diagnostic
    return payload


def _doctor_error_payload(
    error: RuntimeConfigError, strategy_dir: Path, registry: RuntimeRegistry
) -> dict:
    """Backward-compatible doctor helper for callers outside :func:`main`."""

    return _operator_error_payload(
        error,
        command="doctor",
        strategy_dir=strategy_dir,
        registry=registry,
    )


def _disallowed_run_arguments(argv: Sequence[str]) -> tuple:
    """Return every rejected override flag without retaining user supplied values."""

    if not argv or argv[0] not in (
        "validate",
        "doctor",
        "run",
        "preflight",
        "check-ctp-fronts",
    ):
        return ()
    rejected = []
    for token in argv[1:]:
        for disallowed in _DISALLOWED_RUN_ARGUMENTS:
            if token == disallowed or token.startswith(disallowed + "="):
                if disallowed not in rejected:
                    rejected.append(disallowed)
    return tuple(rejected)


def _contains_disallowed_run_argument(argv: Sequence[str]) -> Optional[str]:
    """Return the first rejected override for compatibility with older callers."""

    rejected = _disallowed_run_arguments(argv)
    return rejected[0] if rejected else None


def _environment_override_errors(environ: Mapping[str, str]) -> tuple:
    """Collect static mode/preset override attempts without applying any of them."""

    errors = []
    for name in _OVERRIDE_ENVIRONMENT_NAMES:
        value = environ.get(name)
        if value:
            errors.append(
                RuntimeConfigError(
                    PRESET_POLICY_VIOLATION,
                    "environment variables cannot override runtime.mode or runtime.preset",
                    field_path="environment.{0}".format(name),
                    reason="environment_override_not_allowed",
                )
            )
    return tuple(errors)


def _reject_environment_overrides(environ: Mapping[str, str]) -> None:
    errors = _environment_override_errors(environ)
    if errors:
        raise errors[0]


def _success_payload(effective: object, status: str, **extra: object) -> dict:
    payload = {"status": status}
    payload.update(effective.as_public_dict())
    payload.update(extra)
    return payload


def _require_config_driven_ctp_binding(registry: RuntimeRegistry, runtime_id: str) -> object:
    """Reject legacy static routes before loading a private CTP config."""

    from .ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding

    binding = registry.require_ctp_simnow_readonly_binding(runtime_id)
    if type(binding) is not CtpSimNowConfigReadOnlyBinding:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "CTP SimNow preflight requires a config-driven exact front-pair binding",
            field_path="runtime.preset",
            reason="ctp_simnow_preflight_front_policy_required",
        )
    return binding


def _report_projection(report: Mapping[str, object], *, full_report: bool) -> dict:
    """Keep the common ``run`` output short while retaining an explicit detail mode."""

    canonical = json.dumps(
        report, default=str, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if full_report:
        return {"detail": "full", "digest": digest, "result": dict(report)}
    summary = {name: report[name] for name in _REPORT_SUMMARY_FIELDS if name in report}
    runtime_config = report.get("runtime_config")
    if isinstance(runtime_config, Mapping):
        runtime_summary = {
            name: runtime_config[name] for name in _RUNTIME_REPORT_FIELDS if name in runtime_config
        }
        if runtime_summary:
            summary["runtime"] = runtime_summary
    return {"detail": "summary", "digest": digest, "result": summary}


def _doctor_projection(effective: object, strategy_dir: Path, registry: RuntimeRegistry) -> dict:
    """Describe the resolved route in operator language without capability I/O."""

    public = effective.as_public_dict()
    # New operator configs use the canonical shared CTP block.  Keep the
    # legacy SimNow alias visible only for already-loaded compatibility files.
    private_simnow = effective.config.ctp or effective.config.ctp_simnow
    read_only_preflight_available = False
    read_only_preflight_unavailable_reason = None
    from .inventory import (
        ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
        ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    )

    requires_preflight_supervisor = (
        effective.registration.runtime_id
        in (ITERATION41_007_CTP_PRIVATE_RUNTIME_ID, ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID)
        and effective.mode == "simulation"
        and effective.preset == "sandbox"
        and effective.account_access == "sandbox_private_read"
    )
    if (
        effective.mode == "simulation"
        and effective.preset == "sandbox"
        and effective.account_access == "sandbox_private_read"
    ):
        if requires_preflight_supervisor:
            read_only_preflight_unavailable_reason = (
                _CTP_SIMNOW_PREFLIGHT_SUPERVISOR_REASON
            )
        else:
            try:
                if effective.profile is not None:
                    from .ctp_sandbox_readonly_admission import (
                        require_ctp_sandbox_profile_runtime,
                    )

                    require_ctp_sandbox_profile_runtime(effective, registry)
                _require_config_driven_ctp_binding(registry, effective.registration.runtime_id)
            except RuntimeConfigError:
                pass
            except Exception:
                pass
            else:
                read_only_preflight_available = True
    configured_simnow_fronts = None
    if effective.account_access == "sandbox_private_read" and private_simnow is not None:
        # Front addresses are non-secret operator facts. Keep credentials,
        # account identity, and contract selectors out of the diagnostic.
        if private_simnow.md_front is not None and private_simnow.td_front is not None:
            configured_simnow_fronts = {
                "md_front": private_simnow.md_front,
                "td_front": private_simnow.td_front,
            }
        else:
            configured_simnow_fronts = {
                "front_pairs": [
                    {"md_front": pair["md_front"], "td_front": pair["td_front"]}
                    for pair in private_simnow.front_pairs
                ]
            }
    next_action = {
        "action": "run",
        "command": ["bt-runtime", "run", "--strategy-dir", str(strategy_dir)],
        "note": "run repeats schema and sealed-policy validation before any registered runner import",
    }
    if public["requires_live_confirmation"]:
        next_action["command"].append("--confirm-live")
    if requires_preflight_supervisor:
        next_action = {
            "action": _CTP_SIMNOW_PREFLIGHT_SUPERVISOR_ACTION,
            "field_path": "command",
            "note": _CTP_SIMNOW_PREFLIGHT_SUPERVISOR_NOTE,
        }
    elif read_only_preflight_available:
        next_action = {
            "action": "preflight",
            "command": ["bt-runtime", "preflight", "--strategy-dir", str(strategy_dir)],
            "note": (
                "runs the code-bound CTP read-only checks for this sandbox config; "
                "does not enable strategy execution or write authority"
                if effective.profile is not None
                else (
                    "probes only configured MD/TD pairs, then opens bounded TD account "
                    "and MD market-data read-only checks; grants no write authority"
                )
            ),
        }
    elif not public["profile_dispatch_available"]:
        next_action = {
            "action": "review_profile_dispatch",
            "field_path": "runtime.preset",
            "note": "profile validation is offline; profile-scoped dispatch is not enabled",
        }
    elif effective.account_access == "sandbox_private_read":
        try:
            _require_config_driven_ctp_binding(registry, effective.registration.runtime_id)
        except RuntimeConfigError:
            next_action = {
                "action": "review_registration",
                "field_path": "runtime.preset",
                "note": ("register a config-driven CTP front-pair policy before provider access"),
            }
        else:
            next_action = {
                "action": "preflight",
                "command": ["bt-runtime", "preflight", "--strategy-dir", str(strategy_dir)],
                "note": (
                    "probes only configured MD/TD pairs, then opens bounded TD account "
                    "and MD market-data read-only checks; grants no write authority"
                ),
            }
    diagnostic = {
        "offline": True,
        "provider_preflight_started": False,
        "operator_summary": _doctor_operator_summary(
            mode=public["mode"],
            preset=public["preset"],
            environment=public["environment"],
            order_route=public["order_route"],
            account_access=public["account_access"],
            allows_external_writes=bool(public["allows_external_writes"]),
            allows_hypothetical_fills=bool(public["allows_hypothetical_fills"]),
            required_capabilities=public["required_capabilities"],
            requires_approval=bool(public["requires_approval"]),
            profile_dispatch_available=bool(public["profile_dispatch_available"]),
            profile_dispatch_unavailable_reason=public["profile_dispatch_unavailable_reason"],
        ),
        "next_actions": [next_action],
        "profile_dispatch_available": public["profile_dispatch_available"],
        "profile_dispatch_unavailable_reason": public["profile_dispatch_unavailable_reason"],
        "read_only_preflight_dispatch_available": read_only_preflight_available,
        "read_only_preflight_dispatch_unavailable_reason": (
            None
            if read_only_preflight_available
            else (
                read_only_preflight_unavailable_reason
                or ("profile_dispatch_unavailable" if effective.profile is not None else None)
            )
        ),
    }
    if effective.registration.runtime_id in (
        ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
        ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    ):
        diagnostic["operator_actions"] = _ctp_private_operator_actions(
            strategy_dir=strategy_dir,
            mode=public["mode"],
            preset=public["preset"],
            profile_dispatch_available=bool(public["profile_dispatch_available"]),
            profile_dispatch_unavailable_reason=public["profile_dispatch_unavailable_reason"],
            unavailable_live_profile_note=(
                "The registered 007 CTP live profile is unavailable."
                if effective.registration.runtime_id == ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
                else "The registered 013_3 production profile is unavailable."
            ),
        )
    if configured_simnow_fronts is not None:
        diagnostic["configured_simnow_fronts"] = configured_simnow_fronts
    return diagnostic


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    registry: Optional[RuntimeRegistry] = None,
    environ: Optional[Mapping[str, str]] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Run the CLI and return an exit status after safe runtime dispatch.

    ``registry`` injection exists for reviewed application code and unit tests.
    The installed command has no registry/mode/preset/config override flag and
    uses the package's reviewed runtime inventory.  Directories absent from
    that inventory fail closed.
    """

    arguments = list(sys.argv[1:] if argv is None else argv)
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    selected_registry = registry or default_runtime_registry()
    selected_environ = os.environ if environ is None else environ
    environment_errors = _environment_override_errors(selected_environ)

    if arguments and arguments[0] == "prepare-ctp-production-config":
        _write_payload(
            errors,
            _operator_error_payload(
                RuntimeConfigError(
                    CONFIG_SCHEMA_UNSUPPORTED,
                    "Iteration 41 uses the shared config.yaml under "
                    "examples/013_3_sa_midfreq_simnow/runtime-ctp-private; "
                    "the separate production-config command is retired. "
                    "A future live route still requires independent implementation and review.",
                    field_path="command",
                    reason="separate_production_config_not_supported",
                ),
                command=arguments[0],
                strategy_dir=None,
                registry=selected_registry,
            ),
        )
        return 2
    command_uses_runtime_policy = bool(arguments) and arguments[0] in (
        "validate",
        "doctor",
        "run",
        "preflight",
        "check-ctp-fronts",
    )

    disallowed = _disallowed_run_arguments(arguments)
    if disallowed:
        _write_payload(
            errors,
            _operator_error_payload(
                RuntimeConfigError(
                    PRESET_POLICY_VIOLATION,
                    "command-line arguments cannot override runtime.mode or runtime.preset",
                    field_path="argv",
                    reason="cli_override_not_allowed",
                ),
                command=arguments[0] if arguments else None,
                strategy_dir=None,
                registry=selected_registry,
                additional_errors=environment_errors if command_uses_runtime_policy else (),
                rejected_arguments=disallowed,
            ),
        )
        return 2

    parser = build_parser()
    dispatch_started = False
    try:
        args = parser.parse_args(arguments)
    except _ParserError:
        _write_payload(
            errors,
            _operator_error_payload(
                RuntimeConfigError(
                    PRESET_POLICY_VIOLATION,
                    "command-line arguments are not permitted for this runtime command",
                    field_path="argv",
                    reason="cli_argument_not_allowed",
                ),
                command=arguments[0] if arguments else None,
                strategy_dir=None,
                registry=selected_registry,
                additional_errors=environment_errors if command_uses_runtime_policy else (),
            ),
        )
        return 2
    except SystemExit as exc:
        # --help remains conventional; no runtime code has been loaded.
        return int(exc.code)

    try:
        if args.command == "collect-evidence":
            bundle = collect_iteration41_evidence()
            succeeded = bundle["status"] == "PASS"
            _write_payload(output if succeeded else errors, bundle)
            return 0 if succeeded else 2

        if args.command in ("prepare-ctp-config", "prepare-ctp-simnow-config"):
            from .ctp_private_config_setup import (
                prepare_ctp_simnow_config,
                prepare_ctp_simnow_config_sources,
            )

            source_specs = []
            if args.source_env is not None:
                source_specs.append((args.source_env, "env"))
            if args.source_yaml is not None:
                source_specs.append((args.source_yaml, "yaml"))
            if args.source_collector_yaml is not None:
                source_specs.append((args.source_collector_yaml, "collector_yaml"))
            if not source_specs:
                raise RuntimeConfigError(
                    CONFIG_SCHEMA_UNSUPPORTED,
                    "provide an explicit --source-env, --source-yaml, or --source-collector-yaml path",
                    field_path="source",
                    reason="source_required",
                )
            target_kwargs = (
                {"runtime_id": args.runtime_id} if args.runtime_id is not None else {}
            )
            if len(source_specs) == 1:
                source_path, source_format = source_specs[0]
                prepared = prepare_ctp_simnow_config(
                    source_path, source_format=source_format, **target_kwargs
                )
            else:
                prepared = prepare_ctp_simnow_config_sources(source_specs, **target_kwargs)
            _write_payload(output, prepared.as_public_dict())
            return 0

        if args.command == "bootstrap":
            if args.runtime_set is not None:
                if args.preset is not None:
                    raise RuntimeConfigError(
                        PRESET_POLICY_VIOLATION,
                        "batch bootstrap always chooses each runtime's safest reviewed preset",
                        field_path="--preset",
                        reason="batch_bootstrap_preset_not_allowed",
                    )
                batch = bootstrap_runtime_set(args.runtime_set, selected_registry)
                _write_payload(output if batch.succeeded else errors, batch.as_public_dict())
                return 0 if batch.succeeded else 2
            preset = args.preset or select_bootstrap_preset(
                selected_registry.require_runtime_dir(args.strategy_dir)
            )
            config = bootstrap_runtime_config(args.strategy_dir, selected_registry, preset)
            _write_payload(
                output,
                {
                    "status": "bootstrapped",
                    "strategy_id": config.strategy_id,
                    "mode": config.mode,
                    "preset": config.preset,
                    "config_digest": config.config_digest,
                },
            )
            return 0

        if args.command in ("preflight", "check-ctp-fronts"):
            # A CTP private config can contain credentials.  Establish the
            # exact code-owned runtime and its config-driven read-only binding
            # before the config loader can inspect any bytes.
            registration = selected_registry.require_runtime_dir(args.strategy_dir)
            if args.command == "preflight":
                if registration.runtime_id in _ctp_private_readonly_runtime_ids():
                    raise RuntimeConfigError(
                        PRESET_POLICY_VIOLATION,
                        "ordinary CTP private preflight is disabled until native SDK startup "
                        "and shutdown run under a hard process supervisor; no config, "
                        "credentials, SDK, or provider/network access was started",
                        field_path="command",
                        reason=_CTP_SIMNOW_PREFLIGHT_SUPERVISOR_REASON,
                    )
            if args.command == "check-ctp-fronts":
                if registration.runtime_id not in _ctp_private_readonly_runtime_ids():
                    raise RuntimeConfigError(
                        PRESET_POLICY_VIOLATION,
                        "configured CTP front checks are limited to registered private read-only runtimes",
                        field_path="strategy_dir",
                        reason="ctp_front_check_runtime_required",
                    )
            if registration.profiles:
                from .ctp_sandbox_readonly_admission import (
                    CtpSandboxReadOnlyAdmissionError,
                    require_ctp_sandbox_profile_registration,
                )

                try:
                    require_ctp_sandbox_profile_registration(registration, selected_registry)
                except CtpSandboxReadOnlyAdmissionError:
                    raise _profile_dispatch_unavailable() from None
            _require_config_driven_ctp_binding(selected_registry, registration.runtime_id)

        # Once the command's code-owned route is established, schema and
        # registry policy take precedence over environment override diagnostics.
        # A missing config for that registered route reports CONFIG_REQUIRED.
        effective = validate_runtime_config(args.strategy_dir, selected_registry)
        if args.command == "run" and not effective.profile_dispatch_available:
            raise _profile_dispatch_unavailable()
        if args.command == "check-ctp-fronts" and (
            effective.mode != "simulation" or effective.preset != "sandbox"
        ):
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "configured CTP front checks require the sealed simulation/sandbox profile",
                field_path="runtime.preset",
                reason="ctp_front_check_profile_required",
            )
        if environment_errors:
            raise environment_errors[0]

        if args.command == "validate":
            _write_payload(output, _success_payload(effective, "valid"))
            return 0
        if args.command == "doctor":
            _write_payload(
                output,
                _success_payload(
                    effective,
                    "diagnostic",
                    diagnostic=_doctor_projection(effective, args.strategy_dir, selected_registry),
                ),
            )
            return 0

        if args.command == "preflight":
            dispatch_started = True
            observation = dispatch_registered_ctp_simnow_readonly_preflight(
                effective, selected_registry
            )
            _write_payload(
                output,
                _success_payload(
                    effective,
                    "read_only_observation",
                    read_only_preflight_started=True,
                    result=observation.as_public_dict(),
                ),
            )
            return 0

        if args.command == "check-ctp-fronts":
            checked = dispatch_registered_ctp_front_check(effective, selected_registry)
            payload = checked.as_public_dict()
            succeeded = checked.succeeded is True
            _write_payload(output if succeeded else errors, payload)
            return 0 if succeeded else 2

        if effective.requires_live_confirmation and not args.confirm_live:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "live mode requires --confirm-live for this approved effective configuration",
                field_path="--confirm-live",
                reason="live_confirmation_required",
            )
        if args.confirm_live and not effective.requires_live_confirmation:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "--confirm-live cannot upgrade a non-live runtime",
                field_path="--confirm-live",
                reason="live_confirmation_not_applicable",
            )

        dispatch_started = True
        report = dispatch_registered_runtime(effective, selected_registry)
        _write_payload(
            output,
            _success_payload(
                effective,
                "completed",
                started=True,
                runner_dispatch="code_owned",
                report=_report_projection(report, full_report=args.full_report),
            ),
        )
        return 0
    except RuntimeConfigError as error:
        command = getattr(args, "command", None)
        strategy_dir = getattr(args, "strategy_dir", None)
        additional_errors = ()
        if command in ("validate", "doctor", "run", "preflight", "check-ctp-fronts"):
            additional_errors = tuple(item for item in environment_errors if item is not error)
        _write_payload(
            errors,
            _operator_error_payload(
                error,
                command=command,
                strategy_dir=strategy_dir,
                registry=selected_registry,
                additional_errors=additional_errors,
                dispatch_started=dispatch_started,
            ),
        )
        return 2


if __name__ == "__main__":  # pragma: no cover - covered via __main__ entry point
    raise SystemExit(main())
