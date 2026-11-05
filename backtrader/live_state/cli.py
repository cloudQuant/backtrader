"""Operator CLI: ``python -m backtrader.live_state <command> ...``.

Commands (all print one JSON document to stdout)::

    init    <strategy_dir> [--exchange E --account-hash H [--route R]]
    show    <strategy_dir> [--audit-limit N]
    rebind  <strategy_dir> --mode move|new_instance --operator NAME --reason TEXT
    resolve <strategy_dir> <marker_id> --conclusion C --operator NAME --evidence REF [...]

Exit status: 0 success, 1 ``LiveStateError`` (JSON carries the finite
``error`` code), 2 usage error.  Output never contains credentials; account
hashes are shown as a 12-character prefix.  ``show`` does not touch the run
lock.  Tip: ``BACKTRADER_LIGHT_IMPORT=1`` shortens the backtrader import.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Optional

from .atomic import LiveStateError
from .audit import read_audit
from .identity import initialize_identity, load_identity, rebind_identity
from .pending import MANUAL_CONCLUSIONS, PendingCommandStore
from .sequence import SequenceAllocator
from .snapshot import PositionSnapshotStore
from .waiting import WaitingOrderStore

__all__ = ("build_summary", "main")

_PREFIX = 12


def _error(exc: Exception) -> dict:
    return {"error": getattr(exc, "code", "live_state_error"), "detail": getattr(exc, "detail", "")}


def _redact_binding(binding: Optional[dict]) -> Optional[dict]:
    if binding is None:
        return None
    out = {key: value for key, value in binding.items() if key != "account_hash"}
    out["account_hash_prefix"] = binding["account_hash"][:_PREFIX]
    return out


def _identity_view(identity) -> dict:
    data = identity.to_dict()
    data["account_binding"] = _redact_binding(data["account_binding"])
    return data


def _marker_view(marker: dict) -> dict:
    keys = (
        "marker_id",
        "status",
        "operation",
        "local_seq",
        "bt_ref",
        "exchange_name",
        "symbol",
        "client_order_id",
        "native_identity",
        "target_identity",
        "trading_day",
        "session_generation",
        "committed_at_utc",
        "updated_at_utc",
        "facts",
    )
    return {key: marker[key] for key in keys}


def _waiting_view(order: dict) -> dict:
    keys = (
        "waiting_id",
        "status",
        "local_seq",
        "bt_ref",
        "exchange_name",
        "symbol",
        "side",
        "size",
        "exectype",
        "price",
        "offset",
        "valid_intent",
        "target_session",
        "created_at_utc",
    )
    return {key: order[key] for key in keys}


def _section(fn) -> Any:
    try:
        return fn()
    except (LiveStateError, OSError) as exc:
        return _error(exc)


def build_summary(strategy_dir: Any, *, check_host_path: bool = True, audit_limit: int = 5):
    """Secret-free JSON-ready overview of one strategy directory."""
    identity = load_identity(strategy_dir, check_host_path=False)
    root = identity.strategy_dir
    host_check = {"ok": True, "code": None}
    try:
        load_identity(strategy_dir, check_host_path=True)
    except LiveStateError as exc:
        host_check = {"ok": False, "code": exc.code}
    if check_host_path and not host_check["ok"]:
        raise LiveStateError(host_check["code"])
    from ._common import StatePaths

    current = StatePaths(strategy_dir).strategy_dir
    uuid = identity.strategy_uuid
    pending = PendingCommandStore(current, uuid)
    waiting = WaitingOrderStore(current, uuid)

    def _pending():
        active = pending.active()
        return {
            "active": [_marker_view(m) for m in active],
            "unknown_count": sum(1 for m in active if m["status"] == "UNKNOWN"),
        }

    def _snapshot():
        snap = PositionSnapshotStore(current).read()
        if snap is None:
            return None
        return {
            "mode": snap["mode"],
            "strategy_uuid": snap["strategy_uuid"],
            "account_hash_prefix": (snap["account_hash"] or "")[:_PREFIX] or None,
            "exchange_name": snap["exchange_name"],
            "trading_day": snap["trading_day"],
            "updated_at_utc": snap["updated_at_utc"],
            "instrument_count": len(snap["positions"]),
            "local_seq_high": snap["local_seq_high"],
        }

    def _audit():
        records = read_audit(current, limit=audit_limit)
        return [
            {key: rec.get(key) for key in ("ts_utc", "event", "operator", "marker_id", "mode")}
            for rec in records
        ]

    return {
        "strategy_dir": current,
        "stored_strategy_dir": root,
        "identity": _identity_view(identity),
        "identity_check": host_check,
        "sequence": _section(lambda: SequenceAllocator(current, uuid).read()),
        "pending": _section(_pending),
        "waiting_orders": _section(lambda: [_waiting_view(o) for o in waiting.active()]),
        "snapshot": _section(_snapshot),
        "audit_tail": _section(_audit),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backtrader.live_state",
        description="Inspect and administer backtrader live strategy state directories.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    p_init = sub.add_parser("init", help="explicit first initialization")
    p_init.add_argument("strategy_dir")
    p_init.add_argument("--exchange")
    p_init.add_argument("--account-hash", dest="account_hash")
    p_init.add_argument("--route")

    p_show = sub.add_parser("show", help="print identity, sequence, markers, waiting orders")
    p_show.add_argument("strategy_dir")
    p_show.add_argument("--audit-limit", dest="audit_limit", type=int, default=5)

    p_rebind = sub.add_parser("rebind", help="answer a host/path identity mismatch")
    p_rebind.add_argument("strategy_dir")
    p_rebind.add_argument("--mode", required=True, choices=("move", "new_instance"))
    p_rebind.add_argument("--operator", required=True)
    p_rebind.add_argument("--reason", required=True)

    p_resolve = sub.add_parser("resolve", help="manually resolve one UNKNOWN marker")
    p_resolve.add_argument("strategy_dir")
    p_resolve.add_argument("marker_id")
    p_resolve.add_argument("--conclusion", required=True, choices=sorted(MANUAL_CONCLUSIONS))
    p_resolve.add_argument("--operator", required=True)
    p_resolve.add_argument("--evidence", required=True, action="append")
    return parser


def _run(args: argparse.Namespace) -> dict:
    if args.command == "init":
        binding = None
        given = [args.exchange, args.account_hash, args.route]
        if any(value is not None for value in given):
            if args.exchange is None or args.account_hash is None:
                raise LiveStateError("account_binding_invalid", "exchange_and_account_hash")
            binding = {"exchange": args.exchange, "account_hash": args.account_hash}
            if args.route is not None:
                binding["route"] = args.route
        identity = initialize_identity(args.strategy_dir, account_binding=binding)
        return {"ok": True, "identity": _identity_view(identity)}
    if args.command == "show":
        if args.audit_limit < 0:
            raise LiveStateError("live_state_error", "audit_limit")
        summary = build_summary(
            args.strategy_dir, check_host_path=False, audit_limit=args.audit_limit
        )
        return dict(summary, ok=True)
    if args.command == "rebind":
        identity = rebind_identity(
            args.strategy_dir, mode=args.mode, operator=args.operator, reason=args.reason
        )
        return {"ok": True, "identity": _identity_view(identity)}
    identity = load_identity(args.strategy_dir, check_host_path=True)
    store = PendingCommandStore(args.strategy_dir, identity.strategy_uuid)
    marker = store.resolve_manually(
        args.marker_id,
        operator=args.operator,
        conclusion=args.conclusion,
        evidence=args.evidence,
    )
    return {"ok": True, "marker": _marker_view(marker), "resolution": marker["resolution"]}


def main(argv: Optional[List[str]] = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        result = _run(args)
        code = 0
    except LiveStateError as exc:
        result = dict(_error(exc), ok=False)
        code = 1
    except OSError as exc:
        result = {"ok": False, "error": "live_state_error", "detail": type(exc).__name__}
        code = 1
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return code
