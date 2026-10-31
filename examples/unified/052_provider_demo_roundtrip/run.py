"""Iteration 52 direct paper entry: one bounded provider Demo round trip.

``--dry`` validates the unified configuration without credentials, network or
provider imports.  ``--live`` selects the configured live channel and still
requires ``--allow-write`` plus a bounded grant before any provider write.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import paper_common

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
# ``--private-config`` default; only the SIMNOW live branch consumes it.
DEFAULT_PRIVATE_CONFIG = (
    HERE.parent / "013_3_sa_midfreq_simnow" / "runtime-ctp-private" / "config.yaml"
)
DEFAULT_RUNTIME_SRC = Path(os.environ.get("BT_API_RUNTIME_SRC", "D:/bt_api_py/bt_api/bt_api_runtime/runtime/src"))
DEFAULT_CONTRACT_SRC = Path(os.environ.get("BT_API_CONTRACT_SRC", "D:/bt_api_py/bt_api/bt_api_runtime/contracts/src"))
DEFAULT_SDK_SRC = Path(os.environ.get("BT_API_PY_SRC", "D:/bt_api_py"))
if str(HERE) not in sys.path:
    # simnow_paper / provider_demo_roundtrip_strategy are folder-local modules.
    sys.path.insert(0, str(HERE))


_VENUES = {
    "BINANCE": {
        "sdk_route_key": "BINANCE___SWAP",
        "account_currency": "USDT",
        "credential_fields": (
            ("public_key", "BINANCE_DEMO_API_KEY"),
            ("private_key", "BINANCE_DEMO_SECRET"),
        ),
        "api_region": None,
        "ledger_venues": ("BINANCE", "OKX"),
    },
    "OKX": {
        "sdk_route_key": "OKX___SWAP",
        "account_currency": "USDT",
        "credential_fields": (
            ("public_key", "OKX_DEMO_API_KEY"),
            ("private_key", "OKX_DEMO_SECRET"),
            ("passphrase", "OKX_DEMO_PASSPHRASE"),
        ),
        "api_region": "global",
        "ledger_venues": ("BINANCE", "OKX"),
    },
}
_CREDENTIAL_NAMES = {
    "BINANCE": ("BINANCE_DEMO_API_KEY", "BINANCE_DEMO_SECRET"),
    "OKX": ("OKX_DEMO_API_KEY", "OKX_DEMO_SECRET", "OKX_DEMO_PASSPHRASE"),
}


def _prepend_sources() -> None:
    for path in (REPO_ROOT, DEFAULT_RUNTIME_SRC, DEFAULT_CONTRACT_SRC, DEFAULT_SDK_SRC):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _load_yaml_text(path: Path) -> dict:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config.yaml must contain a mapping")
    return raw


def _venue(params: dict) -> str:
    venue = str(params.get("venue", "BINANCE")).upper()
    if venue == "SIMNOW":
        return "SIMNOW"
    if venue not in _VENUES:
        raise RuntimeError("unsupported_venue")
    return venue


def _profile(plan, params: dict, order_journal: str | None = None):
    from bt_api_runtime.direct_backtrader import DirectProviderProfile

    venue = _venue(params)
    spec = _VENUES[venue]
    symbol = str(params["symbol"])
    extra_store = (("order_journal", order_journal),) if order_journal else ()
    return DirectProviderProfile(
        provider_ref=plan.references.provider,
        endpoint_ref=plan.references.endpoint,
        account_ref=plan.references.account,
        credential_ref=plan.references.credential,
        scope_ref=plan.references.scope,
        sdk_route_key=spec["sdk_route_key"],
        environment="demo",
        account_currency=spec["account_currency"],
        symbols=(symbol,),
        credential_fields=spec["credential_fields"],
        api_region=spec["api_region"],
        position_mode="dual_side",
        require_account_risk=True,
        account_maximum_loss_bps="50",
        account_risk_max_age_seconds="60",
        supports_write=True,
        data_timeframe="ticks",
        readiness_quantity=1.0,
        extra_store_config=extra_store,
    )


def _with_ledger_venues(profile, credentials: dict, venues: tuple[str, ...]):
    import dataclasses

    exchange = profile.exchange_kwargs(credentials)
    required = {profile.sdk_route_key: profile.environment}
    for venue in venues:
        if venue == "BINANCE" and profile.sdk_route_key != "BINANCE___SWAP":
            exchange["BINANCE___SWAP"] = {
                "environment": "demo",
                "public_key": credentials["BINANCE_DEMO_API_KEY"],
                "private_key": credentials["BINANCE_DEMO_SECRET"],
            }
            required["BINANCE___SWAP"] = "demo"
        elif venue == "OKX" and profile.sdk_route_key != "OKX___SWAP":
            exchange["OKX___SWAP"] = {
                "environment": "demo",
                "api_region": "global",
                "public_key": credentials["OKX_DEMO_API_KEY"],
                "private_key": credentials["OKX_DEMO_SECRET"],
                "passphrase": credentials["OKX_DEMO_PASSPHRASE"],
            }
            required["OKX___SWAP"] = "demo"
    extra = profile.extra_store_config + (
        ("exchange_kwargs", exchange),
        ("required_environments", required),
    )
    return dataclasses.replace(profile, extra_store_config=extra)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(HERE / "config.yaml"))
    parser.add_argument("--dry", action="store_true", help="offline validation only")
    parser.add_argument("--live", action="store_true", help="select the live channel")
    parser.add_argument("--allow-write", action="store_true", help="explicit write grant")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument(
        "--private-config",
        default=str(DEFAULT_PRIVATE_CONFIG),
        help="sealed CTP ctp: block used only by the SIMNOW live tier",
    )
    parser.add_argument(
        "--order-journal",
        default=None,
        help="reuse one existing account execution journal (required when the "
        "account is already bound to it)",
    )
    parser.add_argument(
        "--ledger-venues",
        default=None,
        help="comma-separated venues that share the account execution ledger",
    )
    parser.add_argument("--preflight-only", action="store_true", help="account/readiness only; no order")
    parser.add_argument("--grant-seconds", type=int, default=120)
    parser.add_argument("--session-seconds", type=float, default=60.0)
    parser.add_argument("--initialize-risk-baseline", action="store_true", default=True)
    parser.add_argument("--no-risk-baseline", dest="initialize_risk_baseline", action="store_false")
    args = parser.parse_args(argv)

    _prepend_sources()
    from entry_tier import decide, conflict, invalid

    config_path = Path(args.config)
    raw = _load_yaml_text(config_path)
    cli_tier = "dry" if args.dry else ("live" if args.live else None)
    decision = decide(raw, cli_tier)
    tier_evidence = decision.as_evidence()
    if invalid(decision) or conflict(decision):
        payload = {"status": "BLOCKED", "reason": "config_tier_invalid_or_conflict", "entry_tier": tier_evidence}
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2

    from bt_api_run_contract import ValidatedRunConfigV2, parse_config

    try:
        plan = parse_config(config_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - finite code only
        payload = {
            "status": "BLOCKED",
            "reason": "config_invalid:" + type(exc).__name__,
            "entry_tier": tier_evidence,
        }
        paper_common.write_evidence(payload)
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2
    if not isinstance(plan, ValidatedRunConfigV2):
        payload = {"status": "BLOCKED", "reason": "schema_v2_required", "entry_tier": tier_evidence}
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2

    params = plan.strategy_parameters_dict()
    if decision.effective_tier != "live":
        payload = {
            "status": "COMPLETED",
            "reason": "offline_validate_ok",
            "entry_tier": tier_evidence,
            "plan": {
                "mode": plan.mode.value,
                "environment": plan.environment.value,
                "capabilities": list(plan.requested_capabilities),
            },
        }
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 0

    if not args.allow_write:
        payload = {"status": "BLOCKED", "reason": "write_not_authorized", "entry_tier": tier_evidence}
        paper_common.write_evidence(payload)
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2

    venue = _venue(params)
    if venue == "SIMNOW":
        import simnow_runner

        return simnow_runner.run_simnow(plan, params, args, tier_evidence)
    profile = _profile(plan, params, args.order_journal)
    if args.ledger_venues is None:
        ledger_venues = tuple(_VENUES[venue]["ledger_venues"])
    else:
        ledger_venues = tuple(
            item.strip().upper() for item in str(args.ledger_venues).split(",") if item.strip()
        )
    credential_names = tuple(
        dict.fromkeys(
            name
            for item in set(ledger_venues) | {venue}
            for name in _CREDENTIAL_NAMES[item]
        )
    )
    try:
        credentials = paper_common.load_credentials(Path(args.env_file), credential_names)
    except Exception as exc:  # noqa: BLE001
        payload = {
            "status": "BLOCKED",
            "reason": "credentials_unavailable",
            "entry_tier": tier_evidence,
            "venue": venue,
        }
        paper_common.write_evidence(payload)
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2
    profile = _with_ledger_venues(profile, credentials, ledger_venues)

    from bt_api_runtime.direct_backtrader import (
        DirectBacktraderSession,
        DirectCredentials,
        DirectSessionError,
    )

    run_id = (
        "i52-"
        + venue.lower()
        + "-demo-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    grant = paper_common.build_grant(plan, profile, params, run_id, args.grant_seconds)
    session = DirectBacktraderSession(
        plan=plan,
        profile=profile,
        run_id=run_id,
        credentials=DirectCredentials(credentials),
        strategy_id="iteration52-" + venue.lower() + "-demo-roundtrip",
        grant=grant,
    )
    if args.preflight_only:
        try:
            readiness = session.preflight()
            payload = {
                "status": "COMPLETED",
                "reason": "preflight_ok",
                "entry_tier": tier_evidence,
                "venue": venue,
                "credential_env_names": list(credential_names),
                "readiness": readiness,
                "config_sha256": session.config_sha256(),
            }
        except DirectSessionError as exc:
            payload = {
                "status": "BLOCKED",
                "reason": exc.code,
                "entry_tier": tier_evidence,
                "venue": venue,
                "credential_env_names": list(credential_names),
            }
        except Exception as exc:  # noqa: BLE001 - bounded failure codes only
            reason = "preflight_failure:" + type(exc).__name__[:60]
            operation = getattr(exc, "operation", None)
            code = getattr(exc, "code", None)
            if isinstance(operation, str) and operation.isascii() and operation:
                reason += ":" + operation[:60]
            if isinstance(code, str) and code.isascii() and code:
                reason += ":" + code[:80]
            payload = {
                "status": "BLOCKED",
                "reason": reason,
                "entry_tier": tier_evidence,
                "venue": venue,
                "credential_env_names": list(credential_names),
            }
        finally:
            session.close()
        evidence = paper_common.write_evidence(payload)
        payload["evidence_path"] = str(evidence.relative_to(REPO_ROOT))
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 0 if payload["status"] == "COMPLETED" else 2

    from provider_demo_roundtrip_strategy import ProviderDemoRoundTripStrategy

    query_kwargs = dict(profile.extra_store_config).get("exchange_kwargs") or {}
    query_api = None
    if query_kwargs:
        try:
            from bt_api_py import BtApi

            query_api = BtApi(exchange_kwargs=query_kwargs, debug=False)
            session.set_provider_query(
                lambda venue, request: query_api.query_order(venue, request, normalized=True)
            )
        except Exception:  # noqa: BLE001 - recovery is optional, fail closed
            query_api = None
    try:
        report = session.run(
            ProviderDemoRoundTripStrategy,
            strategy_params=paper_common.strategy_params(params),
            seconds=args.session_seconds,
            initialize_risk_baseline=bool(args.initialize_risk_baseline),
        )
    finally:
        if query_api is not None:
            try:
                query_api.close()
            except Exception:
                pass
    phase = (report.strategy_facts or {}).get("phase")
    if report.status == "COMPLETED" and phase in ("canceled", "closed", "closed_verified"):
        status = "PASS"
        reason = "round_trip_" + str(phase)
    elif report.status == "COMPLETED" and phase in (
        "waiting",
        "submitted",
        "resting",
        "partially_filled",
        "filled",
        "awaiting_close",
        "flattening",
    ):
        status = "UNKNOWN"
        reason = "round_trip_incomplete"
    else:
        status = "FAILED"
        reason = report.code if report.status != "COMPLETED" else "round_trip_" + str(phase)
    payload = {
        "status": status,
        "reason": reason,
        "entry_tier": tier_evidence,
        "venue": venue,
        "credential_env_names": list(credential_names),
        "report": report.to_json(),
    }
    evidence = paper_common.write_evidence(payload)
    payload["evidence_path"] = str(evidence.relative_to(REPO_ROOT))
    print(json.dumps(paper_common.summarize(payload), sort_keys=True))
    return {"PASS": 0, "FAILED": 1, "BLOCKED": 2, "UNKNOWN": 3}[status]


if __name__ == "__main__":
    raise SystemExit(main())
