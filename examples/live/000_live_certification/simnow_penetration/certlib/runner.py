"""Uniform case entry used by every SimNow `cases/<ID>/run.py`.

Usage (from a case directory):

    python run.py                 # dry self-check: config + credential names
    python run.py --live --allow-write
    python run.py --live --allow-dangerous

Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.  Live runs require a
CPython 3.11 interpreter (C:/anaconda3/python.exe) and the dev bt_api_ctp
source tree (BT_API_PY_ROOT, default D:/bt_api_py).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from . import context, envfile, make_client

RISK_LEVEL = {"READ": 0, "WRITE": 1, "DANGEROUS": 2}
EXIT_CODES = {"PASS": 0, "FAIL": 1, "BLOCKED": 2, "UNKNOWN": 3}
_UNKNOWN_REASONS = {
    "order_outcome_unknown",
    "order_status_timeout",
    "query_incomplete:orders",
    "login_not_ready",
}


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="run.py", description="Run one certification case.")
    parser.add_argument("--live", action="store_true", help="execute against the SimNow account")
    parser.add_argument("--allow-write", action="store_true", help="grant write actions (orders)")
    parser.add_argument("--allow-dangerous", action="store_true", help="grant dangerous actions")
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--transport", choices=("direct", "gateway_zmq"), default=None)
    parser.add_argument("--execution", action="store_true", default=None)
    parser.add_argument("--risk", action="store_true", default=None)
    parser.add_argument("--monitor", action="store_true", default=None)
    return parser.parse_args(argv)


def _load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover - actionable message
        raise SystemExit("PyYAML is required to read config.yaml (install pyyaml)") from exc
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_strategy(case_dir: Path, case_id: str):
    path = case_dir / f"{case_id}_strategy.py"
    spec = importlib.util.spec_from_file_location(f"{case_id}_strategy", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load strategy module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    strategy_cls = getattr(module, f"{case_id}Strategy", None)
    if strategy_cls is None:
        raise SystemExit(f"module {path.name} does not define class {case_id}Strategy")
    strategy = strategy_cls()
    risk = getattr(strategy, "RISK", None) or getattr(module, "RISK", None) or "READ"
    return strategy, str(risk)


def _section_env_names(section, suffix="_env"):
    if not isinstance(section, dict):
        return []
    names = []
    for key, value in section.items():
        if key.endswith(suffix) and isinstance(value, str) and value:
            names.append(value)
    return names


def _required_env_names(config: dict) -> list:
    return _section_env_names(config.get("credentials", {}))


def _optional_env_names(config: dict) -> list:
    names = _section_env_names(config.get("contract", {}))
    for pair in (config.get("fronts", {}) or {}).get("pairs", []) or []:
        for key in ("td_env", "md_env"):
            value = pair.get(key)
            if isinstance(value, str) and value:
                names.append(value)
    return names


def _topology(config: dict, args) -> dict:
    base = dict(config.get("topology", {}) or {})
    effective = {
        "transport": args.transport or base.get("transport", "direct"),
        "execution": base.get("execution", False),
        "risk": base.get("risk", False),
        "monitor": base.get("monitor", False),
    }
    for flag in ("execution", "risk", "monitor"):
        override = getattr(args, flag, None)
        if override:
            effective[flag] = True
    return effective


def _cleanup_tracked_orders(client, ctx, result_facts):
    """Best-effort compensating cancel for orders whose terminal state is open/unknown."""
    entries = {}
    for entry in ctx.tracked_orders:
        if entry.get("state") == "open":
            entries[str(entry["order_id"])] = {
                "instrument": entry["symbol"],
                "exchange_id": entry.get("exchange_id", ""),
                "order_sys_id": entry.get("order_sys_id", ""),
            }
    if hasattr(client, "pending_orders"):
        for order_ref, info in client.pending_orders().items():
            entries.setdefault(
                str(order_ref),
                {
                    "instrument": info.get("instrument_id", ""),
                    "exchange_id": info.get("exchange_id", ""),
                    "order_sys_id": info.get("order_sys_id", ""),
                },
            )
    if not entries:
        return
    if getattr(client, "_capability", None) is None:
        result_facts["cleanup_skipped_unarmed"] = sorted(entries)
        return
    cleanup = []
    for order_ref, info in entries.items():
        item = {"order_ref": order_ref, "instrument": info["instrument"]}
        try:
            reply = client.cancel_order(
                instrument_id=info["instrument"],
                exchange_id=info["exchange_id"],
                order_ref=order_ref,
                order_sys_id=info["order_sys_id"],
            )
            item["submit_code"] = reply.get("submit_code")
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"[:160]
        cleanup.append(item)
    result_facts["cleanup"] = cleanup


def main_case(argv=None):
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    run_file = Path(sys.argv[0]).resolve()
    case_dir = run_file.parent
    case_id = case_dir.name
    venue = "simnow"

    config_path = Path(args.config) if args.config else case_dir / "config.yaml"
    config = _load_yaml(config_path)
    if config.get("case_id") != case_id:
        print(json.dumps({"case": case_id, "status": "BLOCKED", "reason": "config_case_id_mismatch"}))
        return 2

    strategy, risk = _load_strategy(case_dir, case_id)
    topology = _topology(config, args)
    required = _required_env_names(config)
    optional = [name for name in _optional_env_names(config) if name not in required]
    env_values, env_missing = envfile.load_env(required + optional)
    required_missing = [name for name in env_missing if name in required]

    plan = {
        "case": case_id,
        "venue": venue,
        "risk": risk,
        "live": bool(args.live),
        "topology": topology,
        "scenario": config.get("scenario", {}),
        "env_keys": required + optional,
        "env_keys_missing": env_missing,
    }

    if not args.live:
        plan["status"] = "DRY"
        print(json.dumps(plan, indent=2, ensure_ascii=False, default=str))
        return 0 if not required_missing else 2

    if required_missing:
        print(json.dumps({**plan, "status": "BLOCKED", "reason": "credential_env_missing"}))
        return 2
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 11):
        print(json.dumps({**plan, "status": "BLOCKED", "reason": "cpython_311_required"}))
        return 2
    if RISK_LEVEL.get(risk, 0) >= 1 and not args.allow_write:
        print(json.dumps({**plan, "status": "BLOCKED", "reason": "write_grant_required"}))
        return 2
    if RISK_LEVEL.get(risk, 0) >= 2 and not args.allow_dangerous:
        print(json.dumps({**plan, "status": "BLOCKED", "reason": "dangerous_grant_required"}))
        return 2

    client = None
    result = None
    started = context.utc_now()
    ctx = None
    try:
        client = make_client(config, env_values, topology)
        evidence_dir = Path(args.evidence_dir) if args.evidence_dir else case_dir / "evidence"
        ctx = context.CaseContext(
            venue=venue, case_id=case_id, config=config, topology=topology,
            client=client, evidence_dir=evidence_dir, live=True,
        )
        contract = config.get("contract", {})
        ctx.contract = {
            "instrument": env_values.get(contract.get("instrument_env", ""), ""),
            "exchange": env_values.get(contract.get("exchange_env", ""), ""),
            "hedge_flag": env_values.get(contract.get("hedge_flag_env", ""), "") or "1",
        }
        # Internal only: strategies may build a second session (disconnect/
        # recovery cases).  Never serialized into evidence.
        ctx._env_values = dict(env_values)
        connect_fact = client.connect()
        ctx.log(
            f"logged in trading_day={connect_fact['trading_day']} "
            f"generation={connect_fact['connection_generation']} pair_index={client.pair.index}"
        )
        result = strategy.run(ctx)
        if not isinstance(result, context.CaseResult):
            result = context.CaseResult(case_id, "FAIL", "strategy_returned_invalid_result")
    except Exception as exc:
        reason = getattr(exc, "reason", None) or f"exception:{type(exc).__name__}"
        facts = dict(getattr(exc, "facts", {}) or {})
        facts.setdefault("error", str(exc)[:300])
        status = "UNKNOWN" if reason in _UNKNOWN_REASONS else "FAIL"
        result = context.CaseResult(case_id, status, str(reason), facts)
    finally:
        if client is not None and result is not None:
            facts = result.facts if isinstance(result.facts, dict) else {}
            try:
                _cleanup_tracked_orders(client, ctx, facts)
            except Exception as exc:
                facts["cleanup_error"] = f"{type(exc).__name__}: {exc}"[:200]
            try:
                close_facts = client.close()
                facts["native_stop"] = close_facts
            except Exception as exc:
                facts["close_error"] = f"{type(exc).__name__}: {exc}"[:200]

    finished = context.utc_now()
    evidence = context.build_evidence(
        venue=venue, case_id=case_id, case_dir=case_dir, config=config, topology=topology, live=True,
        result=result, client=client, ctx=ctx, started_utc=started, finished_utc=finished,
        env_names_present=[n for n in required + optional if n not in env_missing],
        env_names_missing=env_missing,
        grants={"allow_write": bool(args.allow_write), "allow_dangerous": bool(args.allow_dangerous)},
    )
    if client is not None:
        evidence["front_selection"] = getattr(client, "front_selection", [])
        evidence["contract"] = getattr(ctx, "contract", {}) if ctx is not None else {}
    evidence_path = context.write_evidence(
        Path(args.evidence_dir) if args.evidence_dir else case_dir / "evidence", evidence
    )

    summary = {
        "case": case_id,
        "venue": venue,
        "status": result.status,
        "reason": result.reason,
        "evidence": str(evidence_path),
        "facts": result.facts,
    }
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return EXIT_CODES.get(result.status, 3)
