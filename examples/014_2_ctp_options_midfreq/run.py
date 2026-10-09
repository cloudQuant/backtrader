#!/usr/bin/env python
"""014_2 standard entry — dry self-check / offline replay / SimNow live tier.

Usage (Python 3.11 for any future live tier; dry/replay need only the core):

    python run.py                          # dry: config + live-readiness report (no network)
    python run.py --replay [--scenario S]  # offline frozen-fixture replay (0 network, 0 writes)
    python run.py --live --allow-write     # live tier: evidence-backed BLOCKED (see below)

Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.

Live tier status: this example shares the C/P/F strict live contracts (feed-
sealed ``BarEvidence`` + run-scoped ``ClockMapping`` + candidate/rules/domain
scoping) and its real contract mapping is still the local ``F_LOCAL`` fixture.
The write-capable adapter is **not integrated yet**, so ``--live`` fails
closed with the exact integration requirements instead of silently degrading
to the raw-line replay contract.  Offline replay and the read-only
engineering seams (``legacy_runner``) remain unchanged.
"""

from __future__ import annotations

import argparse
import datetime
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

HERE = Path(__file__).resolve().parent

EXIT_PASS, EXIT_FAIL, EXIT_BLOCKED, EXIT_UNKNOWN = 0, 1, 2, 3
STRATEGY_ID = "ctp_options_midfreq"

LIVE_INTEGRATION_REQUIREMENTS = (
    "feed-sealed closed-bar evidence provider per leg (BarEvidence with clock_mapping, "
    "candidate_id, rules_hash and clock_domain bound to the frozen store event)",
    "run-scoped non-synthetic ClockMapping + clock_provider covering the whole live window",
    "real contract mapping (the replay fixture's F_LOCAL legs must be replaced by verified "
    "SA/FG future + call + put contracts and strikes)",
    "RegisteredSimStore three-leg arm templates with per-leg preflight identity",
    "strategy live params: require_feed_bar_evidence=True, bar_evidence_clock_mode='live', "
    "bar_evidence_clock_domain=<run domain>, clock_provider=<calibrated provider>",
    "one-shot engineering drill trigger (natural entry needs a full warmup window)",
)
LIVE_FLIP_PATH = (
    "assemble the strict live adapter round: real contract mapping + ctp cohort/evidence path + "
    "caller clock mapping + registered-sim write bridge + drill trigger, then re-run dry/--replay "
    "and a bounded drill live acceptance in a SimNow session"
)
REQUIRED_LIVE_ENV_NAMES = ("CTP_BROKER_ID", "CTP_USER_ID", "CTP_PASSWORD", "CTP_APP_ID", "CTP_AUTH_CODE")


def _load_legacy():
    """Return the folder-local legacy engine (package import or direct script)."""
    if __package__:
        from . import legacy_runner
    else:
        import legacy_runner
    return legacy_runner


def _json_print(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _candidate_summary(config: Mapping[str, Any]) -> Dict[str, Any]:
    candidate = config.get("candidate") or {}
    if not isinstance(candidate, Mapping):
        return {}
    return {
        str(key): value
        for key, value in candidate.items()
        if isinstance(value, (str, int, float, bool))
    }


def run_dry() -> int:
    legacy = _load_legacy()

    errors: list = []
    config: Dict[str, Any] = {}
    try:
        config = legacy.load_config()
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    report = {
        "status": "DRY" if not errors else "REJECTED",
        "mode": "dry",
        "strategy_id": STRATEGY_ID,
        "candidate": _candidate_summary(config),
        "live_tier": {
            "status": "BLOCKED_PENDING_LIVE_ADAPTER",
            "reason": "live_adapter_not_integrated",
            "integration_requirements": list(LIVE_INTEGRATION_REQUIREMENTS),
            "required_env_names": list(REQUIRED_LIVE_ENV_NAMES),
        },
        "network": 0,
        "provider_sessions": 0,
        "errors": errors,
    }
    _json_print(report)
    return EXIT_PASS if not errors else EXIT_BLOCKED


def run_replay(scenario: Optional[str], evidence_dir: Optional[Path]) -> int:
    legacy = _load_legacy()

    chosen = str(scenario or "")
    run_id = (
        f"replay-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    output_directory = Path(evidence_dir) if evidence_dir else (HERE / "evidence" / run_id)
    output_directory.mkdir(parents=True, exist_ok=True)
    try:
        config = legacy.load_config()
        report = legacy.run_replay(config, scenario=(chosen or None))
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
    status = str(report.get("status") or "")
    ok = status == "LOCAL_REPLAY_PASS"
    summary = {
        "status": status or "UNKNOWN",
        "mode": "replay",
        "run_id": run_id,
        "scenario": chosen or (config.get("replay") or {}).get("scenario"),
        "evidence_directory": str(output_directory),
        "external_request_counts": {"network": 0, "order_write": 0},
        "boundary": "SYNTHETIC_REPLAY_ONLY_NOT_MARKET_OR_PROFITABILITY_EVIDENCE",
    }
    _json_print(summary)
    return EXIT_PASS if ok else EXIT_FAIL


def run_live(args) -> int:
    if not args.allow_write:
        _json_print(
            {
                "status": "REJECTED",
                "mode": "live",
                "error": "write_consent_missing",
                "hint": "live C/P/F acceptance would require an explicit --allow-write grant",
            }
        )
        return EXIT_BLOCKED
    _json_print(
        {
            "status": "BLOCKED",
            "mode": "live",
            "strategy_id": STRATEGY_ID,
            "reason": "live_adapter_not_integrated",
            "integration_requirements": list(LIVE_INTEGRATION_REQUIREMENTS),
            "flip_path": LIVE_FLIP_PATH,
            "external_request_counts": {"network": 0, "order_write": 0},
            "boundary": (
                "NO_PROVIDER_SESSION_NO_WRITE: the strict feed-sealed evidence adapter is not "
                "integrated; this entry never degrades to the raw-line replay contract live"
            ),
        }
    )
    return EXIT_BLOCKED


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="offline frozen-fixture replay")
    mode.add_argument("--live", action="store_true", help="live tier (currently evidence-backed BLOCKED)")
    parser.add_argument("--allow-write", action="store_true", help="grant bounded real write actions")
    parser.add_argument("--allow-dangerous", action="store_true", help="reserved; no dangerous action exists")
    parser.add_argument("--scenario", default=None, help="replay scenario name")
    parser.add_argument("--evidence-dir", default=None)
    # ``parse_known_args`` keeps unknown values out of any echoed error text.
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        _json_print(
            {
                "status": "REJECTED",
                "error": "unknown_arguments_rejected",
                "unknown_count": len(unknown),
            }
        )
        return EXIT_BLOCKED
    if args.allow_dangerous:
        _json_print({"status": "REJECTED", "error": "no_dangerous_actions_defined"})
        return EXIT_BLOCKED
    if args.live:
        return run_live(args)
    if args.replay:
        return run_replay(args.scenario, Path(args.evidence_dir) if args.evidence_dir else None)
    return run_dry()


if __name__ == "__main__":
    # Script execution keeps this directory importable; the entry imports the
    # legacy engine lazily inside its functions only.
    raise SystemExit(main())
