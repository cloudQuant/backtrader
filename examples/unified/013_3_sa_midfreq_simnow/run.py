#!/usr/bin/env python
"""Unified entry for offline replay and SDK-composed SimNow operation.

The direct CTP helper has been removed. Live observation requires an explicit
host-owned ManagedRuntimeBinding and routes configuration through bt_api_py.
The strategy Feed remains unavailable until the SDK provides a qualified
market clock. --allow-write alone grants no write permission.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
CHECKOUT_ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DRILL_SESSIONS = (("00:00", "23:59"),)
EXIT_PASS, EXIT_FAIL, EXIT_BLOCKED, EXIT_UNKNOWN = 0, 1, 2, 3


class LiveRejected(RuntimeError):
    """Bounded live-path rejection carrying a reason and value-free details."""

    def __init__(self, reason: str, details: Optional[Mapping[str, Any]] = None, exit_code: int = EXIT_BLOCKED):
        super().__init__(reason)
        self.reason = str(reason)
        self.details = dict(details or {})
        self.exit_code = int(exit_code)


def _json_print(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _ensure_dev_sdk_path(*, strict: bool = False) -> None:
    """Prefer the selected bt_api_py source checkout without importing a provider."""

    root = Path(os.environ.get("BT_API_PY_ROOT") or "D:/bt_api_py").expanduser()
    for extra in reversed((root, root / "bt_api" / "bt_api_base" / "src")):
        if not extra.is_dir():
            continue
        text = str(extra)
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)
    if not strict:
        return

    import importlib.util

    root = root.resolve()
    for module_name in ("bt_api_py", "bt_api_base"):
        loaded = sys.modules.get(module_name)
        origin = getattr(loaded, "__file__", None) if loaded is not None else None
        if origin is None:
            try:
                spec = importlib.util.find_spec(module_name)
            except (ImportError, ValueError):
                spec = None
            origin = getattr(spec, "origin", None)
        try:
            Path(str(origin)).resolve().relative_to(root)
        except (TypeError, ValueError, OSError):
            raise LiveRejected(
                "managed_runtime_sdk_source_unavailable",
                {"module": module_name},
            ) from None


def _load_config() -> Tuple[Dict[str, Any], Dict[str, Any], Path]:
    """Load the full config and a sanitized view for the frozen legacy validator.

    The frozen legacy validator forbids any key containing credential-like
    substrings anywhere in its input.  The iteration-42 sections name credential
    environment variables, so the validator only ever sees the sanitized view;
    the new sections are validated separately by ``_new_section_errors``.
    """
    import yaml

    import legacy_runner

    path = legacy_runner.DEFAULT_CONFIG
    if not path.is_file():
        raise legacy_runner.RunnerConfigurationError(f"config does not exist: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise legacy_runner.RunnerConfigurationError("config root must be a mapping")
    legacy = {key: deepcopy(value) for key, value in raw.items() if key not in NEW_SECTIONS}
    legacy_runner.validate_config(legacy)
    return raw, legacy, path.resolve()


def _new_section_errors(config: Mapping[str, Any]) -> list:
    errors = []
    if int(config.get("schema_version") or 0) != 2:
        errors.append("schema_version_must_be_2")
    if str(config.get("venue") or "") != "simnow":
        errors.append("venue_must_be_simnow")
    credentials = config.get("credentials")
    if not isinstance(credentials, Mapping) or not credentials:
        errors.append("credentials_section_missing")
    else:
        for key, value in credentials.items():
            if not key.endswith("_env") or not isinstance(value, str) or not value.strip():
                errors.append(f"credential_name_invalid:{key}")
    live_contract = config.get("live_contract")
    if not isinstance(live_contract, Mapping) or not live_contract.get("instrument"):
        errors.append("live_contract_instrument_missing")
    if not isinstance(live_contract, Mapping) or not live_contract.get("exchange"):
        errors.append("live_contract_exchange_missing")
    pairs = ((config.get("fronts") or {}) or {}).get("pairs")
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 8:
        errors.append("fronts_pairs_must_be_1_to_8")
    else:
        for index, item in enumerate(pairs):
            if not isinstance(item, Mapping) or not item.get("td_env") or not item.get("md_env"):
                errors.append(f"front_pair_invalid:{index}")
    policy = config.get("policy")
    if not isinstance(policy, Mapping) or policy.get("allow_write") is not False:
        errors.append("policy_allow_write_must_default_false")
    timeouts = config.get("timeouts")
    if not isinstance(timeouts, Mapping):
        errors.append("timeouts_section_missing")
    return errors


# --------------------------------------------------------------------------- dry
import entry_tier  # noqa: E402  (folder-local copy of examples/_support/entry_tier.py)


def run_dry(tier_evidence: Optional[Mapping[str, Any]] = None) -> int:
    try:
        config, _legacy, config_path = _load_config()
    except Exception as exc:
        _json_print({"status": "REJECTED", "mode": "dry", "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    errors = _new_section_errors(config)
    credentials = dict(config.get("credentials") or {})
    report = {
        "entry_tier": dict(tier_evidence or {}),
        "write_grant_result": "not_applicable_offline_tier",
        "status": "DRY",
        "mode": "dry",
        "config_path": config_path.name,
        "strategy_id": "example.013_3.sa_midfreq_simnow",
        "credential_env_names": sorted(str(name) for name in credentials.values()),
        "front_pair_count": len(((config.get("fronts") or {}) or {}).get("pairs") or []),
        "network": 0,
        "provider_sessions": 0,
        "errors": errors,
    }
    if errors:
        report["status"] = "REJECTED"
        _json_print(report)
        return EXIT_BLOCKED
    _json_print(report)
    return EXIT_PASS


# ------------------------------------------------------------------------ replay
def run_replay(
    scenario: Optional[str],
    evidence_dir: Optional[Path],
    tier_evidence: Optional[Mapping[str, Any]] = None,
) -> int:
    import legacy_runner

    try:
        config, legacy_config, _ = _load_config()
    except Exception as exc:
        _json_print({"status": "REJECTED", "mode": "replay", "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    replay_config = deepcopy(legacy_config)
    replay_config["mode"] = "replay"
    try:
        legacy_runner.validate_config(replay_config)
    except Exception as exc:
        _json_print({"status": "REJECTED", "mode": "replay", "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_BLOCKED
    chosen_scenario = str(
        scenario or ((config.get("replay") or {}) or {}).get("scenario") or "no_signal"
    )
    run_id = f"replay-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    output_directory = Path(evidence_dir) if evidence_dir else (HERE / "evidence" / run_id)
    # The legacy replay runner claims a fresh directory itself; only the
    # parent must exist.
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = legacy_runner.run_replay(
            replay_config,
            output_directory=output_directory,
            scenario=chosen_scenario,
            retention_root=None,
        )
    except Exception as exc:
        _json_print(
            {
                "status": "REJECTED",
                "mode": "replay",
                "run_id": run_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return EXIT_FAIL
    orders = report.get("orders") or []
    writes = report.get("sdk_write_requests")
    ok = not orders and writes == 0
    summary = {
        "entry_tier": dict(tier_evidence or {}),
        "write_grant_result": "not_applicable_offline_tier",
        "status": "LOCAL_REPLAY_PASS" if ok else "REPLAY_WRITE_DETECTED",
        "mode": "replay",
        "run_id": run_id,
        "scenario": chosen_scenario,
        "evidence_directory": str(output_directory),
        "orders": len(orders),
        "sdk_write_requests": writes,
        "external_request_counts": {"network": 0, "order_write": 0},
        "boundary": "SYNTHETIC_REPLAY_ONLY_NOT_MARKET_OR_PROFITABILITY_EVIDENCE",
    }
    _json_print(summary)
    return EXIT_PASS if ok else EXIT_FAIL


# -------------------------------------------------------------------------- live

def _run_service_observation(args, config=None, tier_evidence=None) -> int:
    """Reject the removed Iteration 53 service runtime before config or I/O."""
    _json_print(
        {
            "status": "BLOCKED",
            "mode": "live",
            "backend": "service",
            "reason": "BACKTRADER_RUNTIME_CAPABILITY_UNAVAILABLE",
            "provider_configuration": "not_read",
            "provider_runtime": "not_started",
        }
    )
    return EXIT_BLOCKED



# ------------------------------------------------------------------ live observe
def _provider_runtime_module():
    """Load this example's small bt_api_py adapter."""

    import importlib.util

    module_name = "_bt_013_3_sa_midfreq_simnow_provider_runtime"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    try:
        spec = importlib.util.spec_from_file_location(
            module_name, HERE / "provider_runtime.py"
        )
        if spec is None or spec.loader is None:
            raise ImportError
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(module_name, None)
        raise LiveRejected("managed_runtime_sdk_unavailable") from None


def _managed_runtime_preflight_reason(
    *,
    runtime_binding: object,
    access_mode: str,
    authorization_source: object | None,
    operator_grant: object | None,
) -> Optional[str]:
    if runtime_binding is None:
        return "MANAGED_RUNTIME_BINDING_UNAVAILABLE"
    try:
        _ensure_dev_sdk_path(strict=True)
        runtime_adapter = _provider_runtime_module()
        runtime_adapter.validate_runtime_inputs(
            runtime_binding=runtime_binding,
            access_mode=access_mode,
            authorization_source=authorization_source,
            operator_grant=operator_grant,
        )
    except LiveRejected as exc:
        return exc.reason
    except Exception as exc:
        adapter = locals().get("runtime_adapter")
        if adapter is not None and isinstance(exc, adapter.SimNowRuntimeError):
            return exc.code
        return "MANAGED_RUNTIME_INPUT_UNAVAILABLE"
    return None


def _persist_live_summary(args, summary: Dict[str, Any], result_code: int) -> int:
    output_directory = (
        Path(args.evidence_dir)
        if getattr(args, "evidence_dir", None)
        else HERE / "evidence" / str(summary["run_id"])
    )
    summary["evidence_directory"] = str(output_directory)
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        (output_directory / "run.json").write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str),
            encoding="utf-8",
        )
    except OSError:
        summary["evidence_write"] = "failed"
        if result_code == EXIT_PASS:
            result_code = EXIT_UNKNOWN
    _json_print(summary)
    return result_code


def run_live_observe(
    args,
    *,
    runtime_binding=None,
    authorization_source=None,
    operator_grant=None,
) -> int:
    """Read neutral account-session state through the SDK; do not start Strategy.

    This example has no verified Backtrader Feed clock binding for the selected
    provider stream, so it reports that strategy capability as unavailable.
    """

    if getattr(args, "backend", "direct") == "service":
        return _run_service_observation(args)

    if runtime_binding is None:
        _json_print(
            {
                "status": "BLOCKED",
                "mode": "live",
                "reason": "MANAGED_RUNTIME_BINDING_UNAVAILABLE",
                "provider_configuration": "not_read",
                "provider_runtime": "not_started",
                "strategy": "NOT_RUN",
            }
        )
        return EXIT_BLOCKED
    if sys.version_info[:2] != (3, 11):
        _json_print(
            {
                "status": "BLOCKED",
                "mode": "live",
                "reason": "live_tier_requires_python_3_11",
                "current": f"{sys.version_info.major}.{sys.version_info.minor}",
                "provider_configuration": "not_read",
            }
        )
        return EXIT_BLOCKED

    decision = getattr(args, "tier_decision", None)
    run_id = (
        f"observe-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    summary: Dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_id,
        "example_id": "013_3_sa_midfreq_simnow",
        "mode": "live",
        "channel": "observe",
        "status": "BLOCKED",
        "entry_tier": decision.as_evidence() if decision is not None else {},
        "write_grant_result": "not_requested_read_only",
        "provider_route": "CTP___FUTURE",
        "provider_configuration": "pending",
        "provider_runtime": "not_started",
        "strategy": "NOT_RUN",
        "market_feed": "UNAVAILABLE",
        "reason": "MANAGED_RUNTIME_OBSERVATION_UNAVAILABLE",
    }
    composition = None
    result_code = EXIT_BLOCKED
    adapter = None
    try:
        input_reason = _managed_runtime_preflight_reason(
            runtime_binding=runtime_binding,
            access_mode="read_only",
            authorization_source=authorization_source,
            operator_grant=operator_grant,
        )
        if input_reason is not None:
            summary["reason"] = input_reason
            summary["provider_configuration"] = "not_read"
            return _persist_live_summary(args, summary, EXIT_BLOCKED)

        adapter = _provider_runtime_module()
        configuration, composition = adapter.compose_provider_runtime(
            config_path=HERE / "config.yaml",
            credential_env_file=CHECKOUT_ROOT / ".env",
            runtime_binding=runtime_binding,
            access_mode="read_only",
        )
        del configuration
        summary["provider_configuration"] = "selected"
        summary["provider_runtime"] = "composed_read_only"

        from backtrader.stores import BtApiStore
        from bt_api_py.facade_protocol import AccountSessionSnapshot

        store = BtApiStore(api=composition.api, provider="btapi", autostart=False)
        snapshot = store.account_session_snapshot("CTP___FUTURE")
        if type(snapshot) is not AccountSessionSnapshot:
            raise LiveRejected("account_session_projection_invalid")
        summary["account_session"] = {
            "available": snapshot.available,
            "connected": snapshot.connected,
            "authenticated": snapshot.authenticated,
            "trading_enabled": snapshot.trading_enabled,
            "settlement_status": snapshot.settlement_status,
            "blocker_count": len(snapshot.blockers),
        }
        summary["reason"] = "MARKET_TICK_CLOCK_UNAVAILABLE"
    except LiveRejected as exc:
        summary["reason"] = exc.reason
    except Exception as exc:
        if adapter is not None and isinstance(exc, adapter.SimNowRuntimeError):
            summary["reason"] = exc.code
        else:
            summary["reason"] = "MANAGED_RUNTIME_OBSERVATION_FAILED"
    finally:
        if composition is not None:
            try:
                composition.close()
                summary["runtime_close"] = "closed"
            except Exception:
                summary["runtime_close"] = "uncertain"
                summary["status"] = "UNKNOWN"
                summary["reason"] = "MANAGED_RUNTIME_CLOSE_FAILED"
                result_code = EXIT_UNKNOWN
    return _persist_live_summary(args, summary, result_code)


def run_live(
    args,
    *,
    runtime_binding=None,
    authorization_source=None,
    operator_grant=None,
) -> int:
    """Keep writing unavailable until this example has a qualified SDK Feed."""

    if getattr(args, "backend", "direct") == "service":
        _json_print(
            {
                "status": "BLOCKED",
                "reason": "service_write_backend_unsupported",
                "write_grant_result": "rejected_before_provider_io",
            }
        )
        return EXIT_BLOCKED
    input_reason = _managed_runtime_preflight_reason(
        runtime_binding=runtime_binding,
        access_mode="managed_execution",
        authorization_source=authorization_source,
        operator_grant=operator_grant,
    )
    if input_reason is not None:
        _json_print(
            {
                "status": "BLOCKED",
                "mode": "live",
                "reason": input_reason,
                "provider_configuration": "not_read",
                "provider_runtime": "not_started",
                "write_grant_result": "not_verified",
                "strategy": "NOT_RUN",
            }
        )
        return EXIT_BLOCKED
    _json_print(
        {
            "status": "BLOCKED",
            "mode": "live",
            "reason": "MARKET_TICK_CLOCK_UNAVAILABLE",
            "provider_configuration": "not_read",
            "provider_runtime": "not_started",
            "write_grant_result": "not_verified",
            "execution_authorization": "not_consumed",
            "strategy": "NOT_RUN",
            "market_feed": "UNAVAILABLE",
        }
    )
    return EXIT_BLOCKED

# -------------------------------------------------------------------------- main
def main(
    argv=None,
    *,
    runtime_binding=None,
    authorization_source=None,
    operator_grant=None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="offline frozen-fixture replay")
    mode.add_argument("--dry", action="store_true", help="force the offline config self-check")
    mode.add_argument("--live", action="store_true", help="use the explicitly bound SDK-managed SimNow runtime")
    parser.add_argument("--backend", choices=("direct", "service"), default="direct")
    parser.add_argument("--service-config", default=None, help="service-only client config for read-only observation")
    parser.add_argument("--service-timeout-ms", type=int, default=2000)
    parser.add_argument("--allow-write", action="store_true", help="request managed writes; requires separate SDK authorization and operator grant")
    parser.add_argument("--allow-dangerous", action="store_true", help="reserved; no dangerous action exists")
    parser.add_argument("--scenario", default=None, help="replay scenario name")
    parser.add_argument("--run-seconds", type=float, default=None, help="live run window override (bounded)")
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--drill", action="store_true", help="engineering drill window instead of natural signals")
    parser.add_argument("--drill-side", choices=("long", "short"), default="long")
    parser.add_argument("--drill-delay-seconds", type=float, default=None)
    parser.add_argument("--drill-window-seconds", type=float, default=None)
    parser.add_argument("--drill-warmup-bars", type=int, default=None)
    # ``parse_known_args`` keeps unknown values out of any echoed error text.
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(
            json.dumps(
                {
                    "entry_tier": {},
                    "write_grant_result": "not_evaluated",
                    "status": "REJECTED",
                    "error": "unknown_arguments_rejected",
                    "unknown_count": len(unknown),
                },
                sort_keys=True,
            )
        )
        return EXIT_BLOCKED
    if args.backend == "service" and args.allow_write:
        _json_print(
            {
                "status": "BLOCKED",
                "reason": "service_write_backend_unsupported",
                "write_grant_result": "rejected_before_provider_io",
            }
        )
        return EXIT_BLOCKED
    if args.service_config and args.backend != "service":
        _json_print({"status": "REJECTED", "reason": "service_config_requires_service_backend"})
        return EXIT_BLOCKED
    if args.backend == "service":
        _json_print(
            {
                "status": "BLOCKED",
                "backend": "service",
                "reason": "BACKTRADER_RUNTIME_CAPABILITY_UNAVAILABLE",
                "provider_configuration": "not_read",
                "provider_runtime": "not_started",
            }
        )
        return EXIT_BLOCKED

    if args.allow_dangerous:
        print(
            json.dumps(
                {
                    "entry_tier": {},
                    "write_grant_result": "not_evaluated",
                    "status": "REJECTED",
                    "error": "no_dangerous_actions_defined",
                }
            )
        )
        return EXIT_BLOCKED

    # A direct run may inspect its entry tier only after the host supplied an
    # exact SDK binding. Explicit offline commands remain independent of it.
    if args.backend == "direct" and not (args.dry or args.replay):
        access_mode = "managed_execution" if args.allow_write else "read_only"
        input_reason = _managed_runtime_preflight_reason(
            runtime_binding=runtime_binding,
            access_mode=access_mode,
            authorization_source=authorization_source,
            operator_grant=operator_grant,
        )
        if input_reason is not None:
            _json_print(
                {
                    "status": "BLOCKED",
                    "reason": input_reason,
                    "provider_configuration": "not_read",
                    "provider_runtime": "not_started",
                    "write_grant_result": (
                        "not_verified" if args.allow_write else "not_requested_read_only"
                    ),
                }
            )
            return EXIT_BLOCKED

    # ``config.entry.tier`` selects the channel; a mode flag may only keep or
    # lower it, and a malformed declaration is rejected before any provider side
    # effect instead of falling back toward live.
    try:
        tier_config = _load_config()[0]
    except Exception as exc:  # a config that cannot be read is not a live request
        _json_print(
            {
                "entry_tier": {},
                "write_grant_result": "not_evaluated",
                "status": "BLOCKED",
                "reason": f"tier_config_unreadable:{type(exc).__name__}",
            }
        )
        return EXIT_BLOCKED
    cli_tier = "live" if args.live else "replay" if args.replay else "dry" if args.dry else None
    decision = entry_tier.decide(tier_config, cli_tier)
    if entry_tier.invalid(decision) or entry_tier.conflict(decision):
        _json_print(
            {
                "status": "BLOCKED",
                "reason": decision.reason,
                "entry_tier": decision.as_evidence(),
                "write_grant_result": "not_evaluated_tier_unresolved",
            }
        )
        return EXIT_BLOCKED
    args.tier_decision = decision
    if decision.effective_tier == "live":
        # The write drill keeps its explicit grant; without a grant the live tier
        # becomes this zero-write observation session instead of refusing to start.
        return run_live(
            args,
            runtime_binding=runtime_binding,
            authorization_source=authorization_source,
            operator_grant=operator_grant,
        ) if args.allow_write else run_live_observe(
            args,
            runtime_binding=runtime_binding,
            authorization_source=authorization_source,
            operator_grant=operator_grant,
        )
    if decision.effective_tier == "replay":
        return run_replay(
            args.scenario,
            Path(args.evidence_dir) if args.evidence_dir else None,
            decision.as_evidence(),
        )
    return run_dry(decision.as_evidence())


if __name__ == "__main__":
    raise SystemExit(main())
