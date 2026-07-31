"""Trusted local control plane and stdio entry point."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .errors import ProductError
from .service import BacktraderMCPService
from .settings import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backtrader-mcp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="run the local MCP stdio server")
    subparsers.add_parser(
        "doctor",
        help="diagnose this installation, configured roots, and Backtrader runtimes",
    )
    approval = subparsers.add_parser(
        "approve", help="create a trusted local approval record for a prepared change"
    )
    subject = approval.add_mutually_exclusive_group(required=True)
    subject.add_argument("--change-set")
    subject.add_argument("--run-plan")
    approval.add_argument("--change-token")
    approval.add_argument("--run-token")
    approval.add_argument(
        "--yes",
        action="store_true",
        help="confirm after reviewing the prepared hashes (required without a TTY prompt)",
    )
    subparsers.add_parser("audit-independence", help="verify independent product boundaries")
    subparsers.add_parser("recover", help="run startup recovery and print recovered objects")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "serve":
        from .server import run_stdio

        run_stdio(Settings.from_env())
        return 0
    try:
        settings = Settings.from_env()
        if arguments.command == "doctor":
            from .doctor import doctor_report

            result = doctor_report(settings)
        else:
            service = BacktraderMCPService(settings)
        if arguments.command == "approve":
            if arguments.change_set and not arguments.change_token:
                parser.error("--change-token is required with --change-set")
            if arguments.run_plan and not arguments.run_token:
                parser.error("--run-token is required with --run-plan")
            subject_id = arguments.change_set or arguments.run_plan
            if not arguments.yes:
                if not sys.stdin.isatty():
                    parser.error("--yes is required when stdin is not a TTY")
                answer = input(f"Type the full subject id {subject_id!r} to approve exact hashes: ")
                if answer != subject_id:
                    print("approval cancelled", file=sys.stderr)
                    return 2
            if arguments.change_set:
                result = service.changes.approve_change(
                    arguments.change_set, arguments.change_token
                )
            else:
                result = service.jobs.approve_run_plan(arguments.run_plan, arguments.run_token)
        elif arguments.command == "audit-independence":
            result = service.audit_independence()
        elif arguments.command == "recover":
            result = service.recovery
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status", "passed") != "failed" else 1
    except ProductError as exc:
        print(json.dumps(exc.as_dict(), sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
