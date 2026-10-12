#!/usr/bin/env python
"""012_2 standard entry — dry self-check / offline replay / dual-venue demo smoke.

Usage::

    python run.py                                  # dry: config + credential env NAMES only
    python run.py --replay [--scenario SCENARIO]   # offline formula fixture (0 network, 0 writes)
    python run.py --live --allow-write --mechanical-smoke [--run-seconds N]
        # bounded OKX+Binance DEMO mechanical pair; technical pen-test only,
        # never research/profitability evidence (candidate stays RESEARCH_REJECTED,
        # HFT evidence level HFT_FAILED is unchanged)

Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.  Evidence is written under
``evidence/<run_id>/`` (git-ignored).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
CHECKOUT_ROOT = HERE.parents[2]

EXIT_PASS, EXIT_FAIL, EXIT_BLOCKED, EXIT_UNKNOWN = 0, 1, 2, 3
EVIDENCE_DIR = HERE / "evidence"
ENTRY_KEYS = ("tier", "venue", "credentials", "policy", "timeouts", "evidence_boundary")
ENTRY_CREDENTIAL_KEYS = (
    "okx_api_key_env",
    "okx_secret_env",
    "okx_passphrase_env",
    "binance_api_key_env",
    "binance_secret_env",
)
ENTRY_POLICY_KEYS = ("max_actions", "max_order_notional_usdt", "max_round_trips")
ENTRY_TIMEOUT_KEYS = ("run_seconds", "stop_seconds")


def _load_legacy():
    """Return the folder-local legacy engine (package import or direct script)."""
    if __package__:
        from . import legacy_runner
    else:
        import legacy_runner
    return legacy_runner


def _json_print(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _load_raw_config() -> Dict[str, Any]:
    import yaml

    with (HERE / "config.yaml").open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")
    return raw


def _entry_errors(raw: Mapping[str, Any]) -> list:
    errors = []
    entry = raw.get("entry")
    if not isinstance(entry, Mapping):
        return ["entry_section_missing"]
    if any(key not in ENTRY_KEYS for key in entry):
        errors.append("entry_unknown_key")
    venues = entry.get("venue")
    if not isinstance(venues, list) or sorted(str(v) for v in venues) != ["binance", "okx"]:
        errors.append("entry_venue_must_be_okx_and_binance")
    credentials = entry.get("credentials")
    if not isinstance(credentials, Mapping) or not credentials:
        errors.append("entry_credentials_missing")
    else:
        if any(key not in ENTRY_CREDENTIAL_KEYS for key in credentials):
            errors.append("entry_credentials_unknown_key")
        for key, value in credentials.items():
            if not str(key).endswith("_env") or not isinstance(value, str) or not value.strip():
                errors.append("entry_credential_name_invalid")
    policy = entry.get("policy")
    if not isinstance(policy, Mapping):
        errors.append("entry_policy_missing")
    else:
        if any(key not in ENTRY_POLICY_KEYS for key in policy):
            errors.append("entry_policy_unknown_key")
        for name in ("max_actions", "max_round_trips"):
            if int(policy.get(name, 0) or 0) <= 0:
                errors.append(f"entry_policy_{name}_invalid")
    timeouts = entry.get("timeouts")
    if not isinstance(timeouts, Mapping):
        errors.append("entry_timeouts_missing")
    else:
        if any(key not in ENTRY_TIMEOUT_KEYS for key in timeouts):
            errors.append("entry_timeouts_unknown_key")
        for name in ("run_seconds", "stop_seconds"):
            try:
                if float(timeouts.get(name, 0) or 0) <= 0:
                    errors.append(f"entry_timeouts_{name}_invalid")
            except (TypeError, ValueError):
                errors.append(f"entry_timeouts_{name}_invalid")
    return errors


# Resolve the folder-local helper for both package imports and direct script execution.
if __package__:
    from . import entry_tier  # noqa: E402
else:
    import entry_tier  # noqa: E402


def run_dry(tier_evidence: Optional[Mapping[str, Any]] = None) -> int:
    legacy_runner = _load_legacy()

    errors: list = []
    credential_names: list = []
    try:
        legacy_runner.load_config(legacy_runner.DEFAULT_CONFIG)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    raw: Dict[str, Any] = {}
    try:
        raw = _load_raw_config()
        errors.extend(_entry_errors(raw))
        credential_names = sorted(
            str(name) for name in ((raw.get("entry") or {}).get("credentials") or {}).values()
        )
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    report = {
        "entry_tier": dict(tier_evidence or {}),
        "write_grant_result": "not_applicable_offline_tier",
        "status": "DRY" if not errors else "REJECTED",
        "mode": "dry",
        "strategy_id": "012_2_event_driven_cross_exchange",
        "credential_env_names": credential_names,
        "network": 0,
        "provider_sessions": 0,
        "errors": errors,
    }
    _json_print(report)
    return EXIT_PASS if not errors else EXIT_BLOCKED


def run_replay(
    scenario: Optional[str],
    evidence_dir: Optional[Path],
    tier_evidence: Optional[Mapping[str, Any]] = None,
) -> int:
    legacy_runner = _load_legacy()

    chosen = str(scenario or "profitable")
    run_id = (
        f"replay-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    output_directory = Path(evidence_dir) if evidence_dir else (EVIDENCE_DIR / run_id)
    output_directory.mkdir(parents=True, exist_ok=True)
    try:
        report = legacy_runner.run_replay(
            scenario=chosen,
            config_path=legacy_runner.DEFAULT_CONFIG,
            manifest_path=legacy_runner.MANIFEST_PATH,
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
        return EXIT_BLOCKED
    (output_directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
        encoding="utf-8",
    )
    ok = report.get("status") == "FORMULA_CHECK_PASS"
    summary = {
        "entry_tier": dict(tier_evidence or {}),
        "write_grant_result": "not_applicable_offline_tier",
        "status": report.get("status"),
        "mode": "replay",
        "run_id": run_id,
        "scenario": chosen,
        "evidence_directory": str(output_directory),
        "external_request_counts": {"network": 0, "order_write": 0},
        "boundary": "R0_FORMULA_FIXTURE_NOT_MARKET_OR_PROFITABILITY_EVIDENCE",
    }
    _json_print(summary)
    return EXIT_PASS if ok else EXIT_FAIL



# ------------------------------------------------------------------ live observe
def run_live_observe(args) -> int:
    """No zero-write observation channel exists here yet.

    This example's live tier is the dual-venue demo acceptance path, and its
    read-only preconditions (account mode, hedge mode, fee and instrument
    metadata) are only exercised inside the admitted write run.  Reporting
    ``live_observation_unavailable`` keeps the capability gap explicit instead of
    letting ``write_consent_missing`` read as if an observation path existed and
    was merely refused.  The write drill's own consent gate below is unchanged.
    """

    decision = getattr(args, "tier_decision", None)
    tier_evidence = decision.as_evidence() if decision is not None else {}
    _json_print(
        {
            "status": "BLOCKED",
            "mode": "live",
            "channel": "observe",
            "reason": "live_observation_unavailable",
            "entry_tier": dict(tier_evidence),
            "write_grant_result": "not_requested",
            "gap": (
                "this example has no standalone zero-write observation path; a read-only "
                "preflight over the same sealed config and demo credentials is the follow-up"
            ),
            "hint": "add --allow-write to run the admitted demo path; nothing was connected or ordered",
        }
    )
    return EXIT_BLOCKED


def run_live(args) -> int:
    legacy_runner = _load_legacy()

    if not args.allow_write:
        _json_print(
            {
                "status": "REJECTED",
                "mode": "live",
                "error": "write_consent_missing",
                "hint": "dual-venue demo acceptance requires an explicit --allow-write grant",
            }
        )
        return EXIT_BLOCKED
    if not args.mechanical_smoke:
        _json_print(
            {
                "status": "REJECTED",
                "mode": "live",
                "error": "mechanical_smoke_required",
                "hint": (
                    "the rejected candidate has no signed demo approval; only the bounded "
                    "mechanical smoke path is available (--mechanical-smoke)"
                ),
            }
        )
        return EXIT_BLOCKED
    # The legacy engine reads the checkout-root .env by path (env_file=);
    # nothing is injected into the process environment, so the SDK's HTTP
    # layer keeps the host's own proxy settings instead of .env proxy hints.
    errors: list = []
    raw: Dict[str, Any] = {}
    try:
        raw = _load_raw_config()
        errors.extend(_entry_errors(raw))
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    if errors:
        _json_print({"status": "REJECTED", "mode": "live", "errors": errors})
        return EXIT_BLOCKED
    entry = raw.get("entry") or {}
    timeouts = dict(entry.get("timeouts") or {})
    runtime_limit = float(raw.get("run_timeout_seconds") or 180)
    run_seconds = float(args.run_seconds or timeouts.get("run_seconds") or runtime_limit)
    run_seconds = min(run_seconds, runtime_limit, 3600.0)
    run_id = (
        f"live-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    output_directory = Path(args.evidence_dir) if args.evidence_dir else (EVIDENCE_DIR / run_id)
    output_directory.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "example_id": "012_2_event_driven_cross_exchange",
        "mode": "live",
        "status": "STARTING",
        "trigger": "mechanical_demo_smoke",
        "boundary": "MECHANICAL_DEMO_SMOKE_NOT_RESEARCH_NOT_PROFITABILITY",
        "venues": sorted(str(v) for v in entry.get("venue") or []),
        "run_seconds": run_seconds,
        "evidence_directory": str(output_directory),
    }

    def _write_summary() -> None:
        try:
            (output_directory / "run.json").write_text(
                json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass

    try:
        # The mechanical smoke runs one bounded, real-priced pair through the
        # event engine while explicitly bypassing the research admission gates
        # (event path models, markout tail, net edge, opportunity lifetime).
        # It stays under the operator-acknowledged rejected-candidate local
        # lease and is labelled MECHANICAL_DEMO_SMOKE_NOT_RESEARCH.
        report = legacy_runner._run_network_impl(
            mode="demo",
            duration=run_seconds,
            config_path=legacy_runner.DEFAULT_CONFIG,
            env_file=CHECKOUT_ROOT / ".env",
            preflight=False,
            manifest_path=legacy_runner.REPO_CANONICAL_MANIFEST,
            allow_rejected_demo_simulation=True,
            mechanical_demo_smoke=True,
        )
    except (legacy_runner.RunnerConfigurationError, legacy_runner.DemoApprovalError) as exc:
        summary.update({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"})
        _write_summary()
        _json_print(summary)
        return EXIT_BLOCKED
    except Exception as exc:
        import traceback

        summary.update(
            {
                "status": "UNKNOWN",
                "reason": f"{type(exc).__name__}: {exc}",
                "traceback_tail": traceback.format_exc(limit=25)[-1600:],
            }
        )
        _write_summary()
        _json_print(summary)
        return EXIT_UNKNOWN
    if not isinstance(report, dict):
        summary.update({"status": "UNKNOWN", "reason": "report_not_a_mapping"})
        _write_summary()
        _json_print(summary)
        return EXIT_UNKNOWN
    (output_directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, default=str, indent=2) + "\n",
        encoding="utf-8",
    )
    status = str(report.get("status") or "")
    summary.update(
        {
            "status": status or "UNKNOWN",
            "report_status": status,
            "fills": report.get("fills"),
            "broker_shutdown": report.get("broker_shutdown"),
        }
    )
    _write_summary()
    _json_print(summary)
    if status in {"DEMO_EXECUTION_PASS", "MECHANICAL_DEMO_SMOKE_PASS"}:
        return EXIT_PASS
    if status.startswith("INCOMPLETE") and int(report.get("fills") or 0) == 0:
        summary["reason"] = "no_fill_in_window"
        _write_summary()
    return EXIT_FAIL


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="offline formula fixture")
    mode.add_argument("--dry", action="store_true", help="force the offline config self-check")
    mode.add_argument("--live", action="store_true", help="dual-venue DEMO mechanical smoke")
    parser.add_argument("--allow-write", action="store_true", help="grant bounded real demo writes")
    parser.add_argument("--mechanical-smoke", action="store_true", help="request one mechanical pair")
    parser.add_argument("--scenario", default=None, help="replay scenario name")
    parser.add_argument("--run-seconds", type=float, default=None, help="bounded run window")
    parser.add_argument("--evidence-dir", default=None)
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(
            json.dumps(
                {
                    "status": "REJECTED",
                    "error": "unknown_arguments_rejected",
                    "unknown_count": len(unknown),
                },
                sort_keys=True,
            )
        )
        return EXIT_BLOCKED
    # ``config.entry.tier`` selects the channel; a mode flag may only keep or
    # lower it, and a malformed declaration is rejected before any provider side
    # effect instead of falling back toward live.
    try:
        tier_config = _load_raw_config()
    except Exception as exc:  # a config that cannot be read is not a live request
        _json_print({"status": "BLOCKED", "reason": f"tier_config_unreadable:{type(exc).__name__}"})
        return EXIT_BLOCKED
    cli_tier = "live" if args.live else "replay" if args.replay else "dry" if args.dry else None
    decision = entry_tier.decide(tier_config, cli_tier, allowed_entry_keys=ENTRY_KEYS)
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
    if "entry" in tier_config:
        try:
            entry_errors = _entry_errors(tier_config)
        except Exception:
            entry_errors = ["entry_configuration_invalid"]
        if entry_errors:
            invalid_decision = entry_tier.TierDecision(
                decision.config_tier, decision.cli_tier, "dry", entry_tier.REASON_INVALID
            )
            _json_print(
                {
                    "status": "BLOCKED",
                    "reason": entry_tier.REASON_INVALID,
                    "entry_tier": invalid_decision.as_evidence(),
                    "write_grant_result": "not_evaluated_tier_unresolved",
                }
            )
            return EXIT_BLOCKED
    args.tier_decision = decision
    if decision.effective_tier == "live":
        # The demo write path keeps its explicit grant; without one the live tier
        # reports the missing observation channel instead of pretending to consent-check.
        return run_live(args) if args.allow_write else run_live_observe(args)
    if decision.effective_tier == "replay":
        return run_replay(
            args.scenario,
            Path(args.evidence_dir) if args.evidence_dir else None,
            decision.as_evidence(),
        )
    return run_dry(decision.as_evidence())


if __name__ == "__main__":
    # Direct CLI execution needs this folder and the checkout on the path; the
    # bootstrap stays inside the main guard by contract.
    for _bootstrap_path in (str(HERE), str(REPO_ROOT)):
        if _bootstrap_path not in sys.path:
            sys.path.insert(0, _bootstrap_path)
    raise SystemExit(main())
