"""Iteration 52 direct paper entry: one bounded Binance Demo round trip.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_RUNTIME_SRC = Path(os.environ.get("BT_API_RUNTIME_SRC", "D:/bt_api_py/bt_api/bt_api_runtime/runtime/src"))
DEFAULT_CONTRACT_SRC = Path(os.environ.get("BT_API_CONTRACT_SRC", "D:/bt_api_py/bt_api/bt_api_runtime/contracts/src"))
DEFAULT_SDK_SRC = Path(os.environ.get("BT_API_PY_SRC", "D:/bt_api_py"))


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


def _load_credentials(path: Path, names: tuple[str, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            if key in names:
                values[key] = value.strip().strip("'\"")
    for name in names:
        if not values.get(name):
            values[name] = os.environ.get(name, "")
    missing = [name for name in names if not values.get(name)]
    if missing:
        raise RuntimeError("missing credential variables: " + ", ".join(missing))
    return {name: values[name] for name in names}


def _profile(plan, params: dict, order_journal: str | None = None):
    from bt_api_runtime.direct_backtrader import DirectProviderProfile

    symbol = str(params["symbol"])
    extra_store = (("order_journal", order_journal),) if order_journal else ()
    return DirectProviderProfile(
        provider_ref=plan.references.provider,
        endpoint_ref=plan.references.endpoint,
        account_ref=plan.references.account,
        credential_ref=plan.references.credential,
        scope_ref=plan.references.scope,
        sdk_route_key="BINANCE___SWAP",
        environment="demo",
        account_currency="USDT",
        symbols=(symbol,),
        credential_fields=(
            ("public_key", str(params["credential_public_key_env"])),
            ("private_key", str(params["credential_private_key_env"])),
        ),
        api_region=None,
        position_mode="dual_side",
        require_account_risk=True,
        account_maximum_loss_bps="50",
        account_risk_max_age_seconds="30",
        supports_write=True,
        data_timeframe="ticks",
        readiness_quantity=1.0,
        extra_store_config=extra_store,
    )


def _with_ledger_venues(profile, credentials: dict, venues: tuple[str, ...]):
    import dataclasses

    exchange = profile.exchange_kwargs(credentials)
    required = {profile.sdk_route_key: profile.environment}
    if "OKX" in venues:
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


def _grant(plan, profile, params: dict, run_id: str, seconds: int):
    from bt_api_runtime.direct_backtrader import DirectWriteGrant

    expires = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return DirectWriteGrant(
        run_id=run_id,
        mode=plan.mode.value,
        provider_ref=profile.provider_ref,
        environment=profile.environment,
        symbols=profile.symbols,
        expires_at_utc=expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        max_order_count=int(params["max_orders"]),
        max_order_notional=float(params["max_notional_usdt"]),
        allow_live_write=False,
    )


def _strategy_params(params: dict) -> dict:
    return {
        "notional_usdt": float(params["notional_usdt"]),
        "step_size": float(params["step_size"]),
        "tick_size": float(params["tick_size"]),
        "offset_bps": float(params["offset_bps"]),
        "cancel_after_seconds": float(params["cancel_after_seconds"]),
        "hard_timeout_seconds": float(params["hard_timeout_seconds"]),
    }


def _write_evidence(payload: dict) -> Path:
    evidence_dir = HERE / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = evidence_dir / f"{stamp}_052_binance_demo_roundtrip_{payload['status']}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _summary(payload: dict) -> dict:
    report = payload.get("report") or {}
    facts = report.get("strategy_facts") or {}
    return {
        "status": payload["status"],
        "reason": payload.get("reason"),
        "phase": facts.get("phase"),
        "open_status": (facts.get("open_order") or {}).get("status"),
        "close_status": (facts.get("close_order") or {}).get("status"),
        "cancel_requested": facts.get("cancel_requested"),
        "run_id": report.get("run_id"),
        "evidence": payload.get("evidence_path"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(HERE / "config.yaml"))
    parser.add_argument("--dry", action="store_true", help="offline validation only")
    parser.add_argument("--live", action="store_true", help="select the live channel")
    parser.add_argument("--allow-write", action="store_true", help="explicit write grant")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument(
        "--order-journal",
        default=None,
        help="reuse one existing account execution journal (required when the "
        "account is already bound to it)",
    )
    parser.add_argument(
        "--ledger-venues",
        default="BINANCE",
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
        print(json.dumps(_summary(payload), sort_keys=True))
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
        _write_evidence(payload)
        print(json.dumps(_summary(payload), sort_keys=True))
        return 2
    if not isinstance(plan, ValidatedRunConfigV2):
        payload = {"status": "BLOCKED", "reason": "schema_v2_required", "entry_tier": tier_evidence}
        print(json.dumps(_summary(payload), sort_keys=True))
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
        print(json.dumps(_summary(payload), sort_keys=True))
        return 0

    if not args.allow_write:
        payload = {"status": "BLOCKED", "reason": "write_not_authorized", "entry_tier": tier_evidence}
        _write_evidence(payload)
        print(json.dumps(_summary(payload), sort_keys=True))
        return 2

    profile = _profile(plan, params, args.order_journal)
    ledger_venues = tuple(
        item.strip().upper() for item in str(args.ledger_venues).split(",") if item.strip()
    )
    credential_names = tuple(name for _, name in profile.credential_fields)
    if "OKX" in ledger_venues:
        credential_names += ("OKX_DEMO_API_KEY", "OKX_DEMO_SECRET", "OKX_DEMO_PASSPHRASE")
    try:
        credentials = _load_credentials(Path(args.env_file), credential_names)
    except Exception as exc:  # noqa: BLE001
        payload = {"status": "BLOCKED", "reason": "credentials_unavailable", "entry_tier": tier_evidence}
        _write_evidence(payload)
        print(json.dumps(_summary(payload), sort_keys=True))
        return 2
    if ledger_venues != ("BINANCE",):
        profile = _with_ledger_venues(profile, credentials, ledger_venues)

    from bt_api_runtime.direct_backtrader import (
        DirectBacktraderSession,
        DirectCredentials,
        DirectSessionError,
    )

    run_id = "i52-binance-demo-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    grant = _grant(plan, profile, params, run_id, args.grant_seconds)
    session = DirectBacktraderSession(
        plan=plan,
        profile=profile,
        run_id=run_id,
        credentials=DirectCredentials(credentials),
        strategy_id="iteration52-binance-demo-roundtrip",
        grant=grant,
    )
    if args.preflight_only:
        try:
            readiness = session.preflight()
            payload = {
                "status": "COMPLETED",
                "reason": "preflight_ok",
                "entry_tier": tier_evidence,
                "credential_env_names": list(credential_names),
                "readiness": readiness,
                "config_sha256": session.config_sha256(),
            }
        except DirectSessionError as exc:
            payload = {
                "status": "BLOCKED",
                "reason": exc.code,
                "entry_tier": tier_evidence,
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
                "credential_env_names": list(credential_names),
            }
        finally:
            session.close()
        evidence = _write_evidence(payload)
        payload["evidence_path"] = str(evidence.relative_to(REPO_ROOT))
        print(json.dumps(_summary(payload), sort_keys=True))
        return 0 if payload["status"] == "COMPLETED" else 2

    from binance_demo_roundtrip_strategy import BinanceDemoRoundTripStrategy

    report = session.run(
        BinanceDemoRoundTripStrategy,
        strategy_params=_strategy_params(params),
        seconds=args.session_seconds,
        initialize_risk_baseline=bool(args.initialize_risk_baseline),
    )
    phase = (report.strategy_facts or {}).get("phase")
    if report.status == "COMPLETED" and phase in ("canceled", "closed"):
        status = "PASS"
        reason = "round_trip_" + str(phase)
    elif report.status == "COMPLETED" and phase in (
        "waiting",
        "submitted",
        "resting",
        "partially_filled",
        "filled",
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
        "credential_env_names": list(credential_names),
        "report": report.to_json(),
    }
    evidence = _write_evidence(payload)
    payload["evidence_path"] = str(evidence.relative_to(REPO_ROOT))
    print(json.dumps(_summary(payload), sort_keys=True))
    return {"PASS": 0, "FAILED": 1, "BLOCKED": 2, "UNKNOWN": 3}[status]


if __name__ == "__main__":
    raise SystemExit(main())
