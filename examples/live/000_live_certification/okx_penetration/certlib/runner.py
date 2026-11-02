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
_RISK_MISSING = object()


class _RiskMetadataError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _resolve_case_risk(strategy, module) -> str:
    strategy_risk = getattr(strategy, "RISK", _RISK_MISSING)
    module_risk = getattr(module, "RISK", _RISK_MISSING)

    for risk in (strategy_risk, module_risk):
        if risk is not _RISK_MISSING and (type(risk) is not str or risk not in RISK_LEVEL):
            raise _RiskMetadataError("case_risk_invalid")

    if strategy_risk is not _RISK_MISSING and module_risk is not _RISK_MISSING:
        if strategy_risk != module_risk:
            raise _RiskMetadataError("case_risk_conflict")
        return strategy_risk
    if strategy_risk is not _RISK_MISSING:
        return strategy_risk
    if module_risk is not _RISK_MISSING:
        return module_risk
    raise _RiskMetadataError("case_risk_missing")


def _risk_grant_block(risk: str, allow_write: bool, allow_dangerous: bool) -> str | None:
    level = RISK_LEVEL[risk]
    if level >= 1 and not allow_write:
        return "write_grant_required"
    if level >= 2 and not allow_dangerous:
        return "dangerous_grant_required"
    return None


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
    return strategy, _resolve_case_risk(strategy, module)


def _env_names(config: dict) -> list:
    section = config.get("credentials", {})
    names = [section.get("api_key_env"), section.get("secret_env"), section.get("passphrase_env")]
    return [name for name in names if name]


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


def _unsupported_backend(topology: dict) -> tuple[str, str] | None:
    """Return a finite capability block before strategy or credential loading."""
    transport = topology.get("transport", "direct")
    if transport != "direct":
        return "transport_not_implemented", str(transport)
    for flag in ("execution", "risk", "monitor"):
        if topology.get(flag):
            return "component_not_implemented", flag
    return None


def _emit_backend_block(args, config, case_dir, case_id, venue, topology, block):
    reason, target = block
    result = context.CaseResult(
        case_id,
        "BLOCKED",
        reason,
        {
            "requested_backend": target,
            "credential_lookup": "not_attempted",
            "provider_attempted": False,
        },
    )
    evidence = context.build_evidence(
        venue=venue,
        case_id=case_id,
        case_dir=case_dir,
        config=config,
        topology=topology,
        live=bool(args.live),
        result=result,
        client=None,
        ctx=None,
        started_utc=context.utc_now(),
        finished_utc=context.utc_now(),
        env_names_present=[],
        env_names_missing=[],
        grants={
            "allow_write": bool(args.allow_write),
            "allow_dangerous": bool(args.allow_dangerous),
        },
    )
    evidence_path = context.write_evidence(
        Path(args.evidence_dir) if args.evidence_dir else case_dir / "evidence",
        evidence,
    )
    print(
        json.dumps(
            {
                "case": case_id,
                "venue": venue,
                "status": result.status,
                "reason": result.reason,
                "evidence": str(evidence_path),
                "facts": result.facts,
            },
            ensure_ascii=False,
            default=str,
        )
    )
    return EXIT_CODES["BLOCKED"]


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

    topology = _topology(config, args)
    backend_block = _unsupported_backend(topology)
    if backend_block is not None:
        return _emit_backend_block(
            args, config, case_dir, case_id, venue, topology, backend_block
        )

    try:
        strategy, risk = _load_strategy(case_dir, case_id)
    except _RiskMetadataError as exc:
        print(
            json.dumps(
                {
                    "case": case_id,
                    "venue": venue,
                    "status": "BLOCKED",
                    "reason": exc.reason,
                }
            )
        )
        return EXIT_CODES["BLOCKED"]
    env_names = _env_names(config)
    env_values, env_missing = envfile.load_env(env_names)

    plan = {
        "case": case_id,
        "venue": venue,
        "risk": risk,
        "live": bool(args.live),
        "topology": topology,
        "scenario": config.get("scenario", {}),
        "env_keys": env_names,
        "env_keys_missing": env_missing,
    }

    if not args.live:
        plan["status"] = "DRY"
        print(json.dumps(plan, indent=2, ensure_ascii=False, default=str))
        return 0 if not env_missing else 2

    if env_missing:
        print(json.dumps({**plan, "status": "BLOCKED", "reason": "credential_env_missing"}))
        return 2
    grant_block = _risk_grant_block(risk, args.allow_write, args.allow_dangerous)
    if grant_block:
        print(json.dumps({**plan, "status": "BLOCKED", "reason": grant_block}))
        return EXIT_CODES["BLOCKED"]

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
