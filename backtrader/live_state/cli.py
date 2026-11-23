"""Operator CLI: ``python -m backtrader.live_state <command> ...``.

Commands (all print one JSON document to stdout)::

    init    <strategy_dir> [--exchange E --account-hash H [--route R]]
    gateway-init <strategy_dir>
    show    <strategy_dir> [--audit-limit N]
    rebind  <strategy_dir> --mode move|new_instance --operator NAME --reason TEXT
    resolve <strategy_dir> <marker_id> --conclusion C --operator NAME --evidence REF [...]
    waiting-migrate  <strategy_dir> --operator NAME --reason TEXT
    waiting-recover  <strategy_dir> --operator NAME --reason TEXT
    waiting-rollback <strategy_dir> --operator NAME --reason TEXT
    waiting-clear    <strategy_dir> <waiting_id> --operator NAME --reason TEXT
                     --evidence REF [...] --calendar-ref R --trading-day D
                     --window-start ISO --window-end ISO

``waiting-clear`` is an operator-only pause release, not a trading
authorization: it needs current calendar evidence that matches the order's
original target, never changes the status or target, and never dispatches,
retries or re-sends anything.  ``waiting-rollback`` verifies the recorded
backup digest and refuses when anything changed after the upgrade.

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
    view = {key: order[key] for key in keys}
    # Make the calendar binding and any recorded refusal explicit (D67-15/17).
    facts = order.get("facts") or {}
    view["calendar_ref"] = order["target_session"].get("calendar_ref")
    view["calendar_disposition"] = facts.get("calendar_disposition")
    view["pause_notification_status"] = facts.get("pause_notification_status")
    view["pause_notification_at_utc"] = facts.get("pause_notification_at_utc")
    cleared = facts.get("calendar_pause_cleared")
    view["pause_cleared_at_utc"] = (cleared or {}).get("cleared_at_utc")
    return view


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
            {
                key: rec.get(key)
                for key in (
                    "ts_utc",
                    "event",
                    "operator",
                    "marker_id",
                    "mode",
                    "waiting_id",
                    "backup_sha256",
                    "outcome",
                )
            }
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
        "waiting_migration": _section(waiting.migration_status),
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

    p_gateway_init = sub.add_parser("gateway-init", help="prepare a fresh local Gateway identity")
    p_gateway_init.add_argument("strategy_dir")

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

    for name, help_text in (
        ("waiting-migrate", "back up and upgrade a version-1 waiting-orders file"),
        ("waiting-recover", "converge an interrupted waiting-orders migration"),
        ("waiting-rollback", "restore a verified pre-migration waiting-orders file"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("strategy_dir")
        command.add_argument("--operator", required=True)
        command.add_argument("--reason", required=True)

    p_clear = sub.add_parser(
        "waiting-clear", help="clear a recorded waiting-order calendar pause after proof"
    )
    p_clear.add_argument("strategy_dir")
    p_clear.add_argument("waiting_id")
    p_clear.add_argument("--operator", required=True)
    p_clear.add_argument("--reason", required=True)
    p_clear.add_argument("--evidence", required=True, action="append")
    p_clear.add_argument("--calendar-ref", dest="calendar_ref", required=True)
    p_clear.add_argument("--trading-day", dest="trading_day", required=True)
    p_clear.add_argument("--window-start", dest="window_start", required=True)
    p_clear.add_argument("--window-end", dest="window_end", required=True)

    p_export = sub.add_parser(
        "export-legacy-execution-routing",
        help="read-only JSON export of retired path 5 state/execution_routing.sqlite (never mutates DB)",
    )
    p_export.add_argument("strategy_dir")
    p_export.add_argument("--output", default=None)
    p_export.add_argument("--operator", default=None)
    p_export.add_argument("--reason", default=None)
    p_export.add_argument("--approval-ref", dest="approval_ref", default=None)
    return parser


def _run(args: argparse.Namespace) -> dict:
    if args.command == "gateway-init":
        from .gateway_initialization import prepare_gateway_state

        state = prepare_gateway_state(args.strategy_dir)
        return {"ok": True, "code": "GATEWAY_LOCAL_STATE_INITIALIZED",
                "strategy_uuid": state.strategy_uuid}
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
    if args.command.startswith("waiting-") and args.command != "waiting-clear":
        identity = load_identity(args.strategy_dir, check_host_path=True)
        store = WaitingOrderStore(args.strategy_dir, identity.strategy_uuid)
        action = {
            "waiting-migrate": store.migrate,
            "waiting-recover": store.recover_migration,
            "waiting-rollback": store.rollback_migration,
        }[args.command]
        return dict(
            action(operator=args.operator, reason=args.reason),
            ok=True,
        )
    if args.command == "export-legacy-execution-routing":
        from .legacy_export import export_legacy_execution_routing

        exported = export_legacy_execution_routing(
            args.strategy_dir,
            output_path=args.output,
            operator=args.operator,
            reason=args.reason,
            approval_ref=args.approval_ref,
        )
        return dict(exported, ok=True)
    if args.command == "waiting-clear":
        identity = load_identity(args.strategy_dir, check_host_path=True)
        store = WaitingOrderStore(args.strategy_dir, identity.strategy_uuid)
        cleared = store.clear_calendar_pause(
            args.waiting_id,
            operator=args.operator,
            reason=args.reason,
            evidence=args.evidence,
            calendar_ref=args.calendar_ref,
            trading_day=args.trading_day,
            continuous_start_utc=args.window_start,
            session_end_utc=args.window_end,
        )
        return {
            "ok": True,
            "clear": cleared,
            "waiting": _waiting_view(store.get(args.waiting_id)),
        }
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
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "gateway-init" and (
        len(argv) != 2 or argv[1].startswith("-")
    ):
        sys.stdout.write(json.dumps({"ok": False, "code": "GATEWAY_LOCAL_STATE_INITIALIZATION_FAILED"},
                                    separators=(",", ":")) + "\n")
        return 2
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    if args.command == "gateway-init":
        try:
            result = _run(args)
            code = 0
        except Exception:
            result = {"ok": False, "code": "GATEWAY_LOCAL_STATE_INITIALIZATION_FAILED"}
            code = 1
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
        return code
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
