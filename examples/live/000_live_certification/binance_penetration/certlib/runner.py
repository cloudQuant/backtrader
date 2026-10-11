"""Uniform case entry used by every `cases/<ID>/run.py`.

Usage (from a case directory):

    python run.py                 # dry self-check: config + credential names
    python run.py --live --allow-write
    python run.py --live --allow-dangerous
    python run.py --live --transport gateway_zmq --monitor

Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.
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


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="run.py", description="Run one certification case.")
    parser.add_argument("--live", action="store_true", help="execute against the demo account")
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


def _env_names(config: dict) -> list:
    section = config.get("credentials", {})
    names = [section.get("api_key_env"), section.get("secret_env"), section.get("passphrase_env")]
    return [name for name in names if name]


def _optional_env_names(config: dict) -> list:
    """Names loaded when present but not required to run (e.g. restricted keys)."""
    section = config.get("credentials", {})
    required = set(_env_names(config))
    names = [section.get("restricted_api_key_env"), section.get("restricted_secret_env")]
    return [name for name in names if name and name not in required]


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
    """Best-effort compensating cancel for orders still marked open."""
    open_entries = [entry for entry in ctx.tracked_orders if entry.get("state") == "open"]
    if not open_entries:
        return
    if getattr(client, "frozen", False):
        result_facts["cleanup_skipped_frozen"] = [entry["order_id"] for entry in open_entries]
        return
    cleanup = []
    for entry in open_entries:
        item = {"order_id": entry["order_id"], "symbol": entry["symbol"]}
        try:
            reply = client.cancel_order(entry["symbol"], order_id=entry["order_id"])
            item["status"] = reply.get("status", "CANCEL_SENT")
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        cleanup.append(item)
    result_facts["cleanup"] = cleanup


def main_case(argv=None):
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    import sys as _sys

    run_file = Path(_sys.argv[0]).resolve()
    case_dir = run_file.parent
    case_id = case_dir.name
    venue = case_dir.parents[1].name.removesuffix("_penetration")

    config_path = Path(args.config) if args.config else case_dir / "config.yaml"
    config = _load_yaml(config_path)
    if config.get("case_id") != case_id:
        print(json.dumps({"case": case_id, "status": "BLOCKED", "reason": "config_case_id_mismatch"}))
        return 2

    strategy, risk = _load_strategy(case_dir, case_id)
    topology = _topology(config, args)
    env_names = _env_names(config)
    optional_names = [n for n in _optional_env_names(config) if n not in env_names]
    env_values, env_missing = envfile.load_env(env_names + optional_names)
    required_missing = [name for name in env_missing if name in env_names]

    plan = {
        "case": case_id,
        "venue": venue,
        "risk": risk,
        "live": bool(args.live),
        "topology": topology,
        "scenario": config.get("scenario", {}),
        "env_keys": env_names,
        "env_keys_missing": required_missing,
        "env_keys_optional_missing": [n for n in env_missing if n in optional_names],
    }

    if not args.live:
        plan["status"] = "DRY"
        print(json.dumps(plan, indent=2, ensure_ascii=False, default=str))
        return 0 if not required_missing else 2

    if required_missing:
        print(json.dumps({**plan, "status": "BLOCKED", "reason": "credential_env_missing"}))
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
        # Internal only: optional credentials (e.g. a restricted-permission key)
        # stay available to strategies without being serialized into evidence.
        ctx._env_values = dict(env_values)
        connect_fact = client.connect()
        ctx.log(f"connected {connect_fact['host']} offset_ms={connect_fact['time_offset_ms']}")
        result = strategy.run(ctx)
        if not isinstance(result, context.CaseResult):
            result = context.CaseResult(case_id, "FAIL", "strategy_returned_invalid_result")
    except Exception as exc:
        result = context.CaseResult(case_id, "FAIL", f"exception:{type(exc).__name__}", {"error": str(exc)[:500]})
    finally:
        if client is not None and result is not None:
            facts = result.facts if isinstance(result.facts, dict) else {}
            if client.frozen and result.status == "PASS":
                result = context.CaseResult(case_id, "UNKNOWN", "client_frozen_after_write", facts)
            try:
                _cleanup_tracked_orders(client, ctx, facts)
            except Exception as exc:
                facts["cleanup_error"] = f"{type(exc).__name__}: {exc}"
            try:
                client.close()
            except Exception:
                pass

    finished = context.utc_now()
    evidence = context.build_evidence(
        venue=venue, case_id=case_id, case_dir=case_dir, config=config, topology=topology, live=True,
        result=result, client=client, ctx=ctx, started_utc=started, finished_utc=finished,
        env_names_present=[n for n in env_names if n not in env_missing], env_names_missing=env_missing,
        grants={"allow_write": bool(args.allow_write), "allow_dangerous": bool(args.allow_dangerous)},
    )
    evidence_path = context.write_evidence(Path(args.evidence_dir) if args.evidence_dir else case_dir / "evidence", evidence)

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
