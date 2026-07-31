"""Unified command-line interface used by all three skills and root scripts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .canonical import load_json
from .catalog import build_snapshot, load_snapshot, search_snapshot
from .compare import compare_metrics
from .data import DataRegistry
from .doctor import run_doctor
from .drafts import DraftManager
from .errors import ContractError, SkillsError
from .installer import SkillInstaller
from .ir import ARCHETYPES, OUTPUT_PROFILES, default_strategy_spec, validate_strategy_spec
from .repair import preview_repair, preview_spec_repair
from .resources import resource_path
from .runner import ControlledRunner
from .runtime import RuntimePaths
from .state import TokenStore
from .validation import validate_python


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True))


def _json_file(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise ContractError(f"{path} must contain a JSON object")
    return value


def _expected_hashes(items: list[str]) -> dict[str, str]:
    result = {}
    for item in items:
        if "=" not in item:
            raise argparse.ArgumentTypeError("--expected-hash must use PATH=SHA256")
        path, digest = item.split("=", maxsplit=1)
        result[path] = digest
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backtrader-skills")
    parser.add_argument("--target", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")

    data = commands.add_parser("data")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    root_add = data_commands.add_parser("root-add")
    root_add.add_argument("--directory", type=Path, required=True)
    root_add.add_argument("--root-id")
    inspect = data_commands.add_parser("inspect")
    inspect.add_argument("--feed-spec", type=Path, required=True)
    inspect.add_argument("--sample-limit", type=int, default=20)
    register = data_commands.add_parser("register")
    register.add_argument("--spec", type=Path, required=True)
    preview = data_commands.add_parser("preview")
    preview.add_argument("--dataset-id", required=True)
    preview.add_argument("--rows", type=int, default=5)
    verify = data_commands.add_parser("verify")
    verify.add_argument("--dataset-id", required=True)

    catalog = commands.add_parser("catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_commands.add_parser("check")
    search = catalog_commands.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--archetype", choices=ARCHETYPES)
    search.add_argument("--limit", type=int, default=3)
    build = catalog_commands.add_parser("build")
    build.add_argument("--functional-root", type=Path, required=True)
    build.add_argument("--package-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--allow-count-drift", action="store_true")

    spec = commands.add_parser("spec")
    spec_commands = spec.add_subparsers(dest="spec_command", required=True)
    scaffold = spec_commands.add_parser("scaffold")
    scaffold.add_argument("--archetype", choices=ARCHETYPES, required=True)
    scaffold.add_argument("--output-profile", choices=OUTPUT_PROFILES, required=True)
    scaffold.add_argument("--dataset-id", required=True)
    scaffold.add_argument("--feed-count", type=int, default=1)
    scaffold.add_argument("--custom-line", action="append", default=[])
    validate_spec = spec_commands.add_parser("validate")
    validate_spec.add_argument("--spec", type=Path, required=True)

    render = commands.add_parser("render")
    render_commands = render.add_subparsers(dest="render_command", required=True)
    render_preview = render_commands.add_parser("preview")
    render_preview.add_argument("--spec", type=Path, required=True)
    render_preview.add_argument("--expected-hash", action="append", default=[])
    render_validate = render_commands.add_parser("validate")
    render_validate.add_argument("--draft-id", required=True)
    render_apply = render_commands.add_parser("apply")
    render_apply.add_argument("--draft-id", required=True)
    render_apply.add_argument("--token-id", required=True)

    approval = commands.add_parser("approval")
    approval_commands = approval.add_subparsers(dest="approval_command", required=True)
    for operation in ("show", "approve", "revoke"):
        operation_parser = approval_commands.add_parser(operation)
        operation_parser.add_argument("--token-id", required=True)

    review = commands.add_parser("review")
    review.add_argument("--file", type=Path, required=True)
    review.add_argument("--allow-third-party", action="store_true")

    run = commands.add_parser("run")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    run_prepare = run_commands.add_parser("prepare")
    run_prepare.add_argument("--candidate", type=Path, required=True)
    run_prepare.add_argument("--dataset-id", required=True)
    run_prepare.add_argument("--timeout", type=int, default=120)
    run_execute = run_commands.add_parser("execute")
    run_execute.add_argument("--run-id", required=True)
    run_execute.add_argument("--token-id", required=True)

    compare = commands.add_parser("compare")
    compare.add_argument("--left", type=Path, required=True)
    compare.add_argument("--right", type=Path, required=True)

    repair = commands.add_parser("repair")
    repair_source = repair.add_mutually_exclusive_group(required=True)
    repair_source.add_argument("--draft-id")
    repair_source.add_argument("--spec", type=Path)
    repair.add_argument("--validation-report", type=Path)

    install = commands.add_parser("install")
    install_commands = install.add_subparsers(dest="install_command", required=True)
    install_preview = install_commands.add_parser("preview")
    install_preview.add_argument(
        "--host", choices=("claude", "codex", "opencode", "openclaw"), required=True
    )
    install_apply = install_commands.add_parser("apply")
    install_apply.add_argument("--plan-id", required=True)
    install_apply.add_argument("--token-id", required=True)
    uninstall_preview = install_commands.add_parser("uninstall-preview")
    uninstall_preview.add_argument(
        "--host", choices=("claude", "codex", "opencode", "openclaw"), required=True
    )
    uninstall_apply = install_commands.add_parser("uninstall-apply")
    uninstall_apply.add_argument("--plan-id", required=True)
    uninstall_apply.add_argument("--token-id", required=True)
    return parser


def dispatch(args: argparse.Namespace) -> Any:
    paths = RuntimePaths(args.target)
    if args.command == "doctor":
        return run_doctor(paths.target)
    if args.command == "data":
        registry = DataRegistry(paths)
        if args.data_command == "root-add":
            return registry.add_root(args.directory, root_id=args.root_id)
        if args.data_command == "inspect":
            return registry.inspect(_json_file(args.feed_spec), sample_limit=args.sample_limit)
        if args.data_command == "register":
            return registry.register(_json_file(args.spec))
        if args.data_command == "preview":
            return registry.preview(args.dataset_id, rows=args.rows)
        return registry.verify_manifest(registry.get_manifest(args.dataset_id, verify=False))
    if args.command == "catalog":
        snapshot = resource_path("snapshots", "catalog-v1.jsonl")
        if args.catalog_command == "check":
            header, entries = load_snapshot(snapshot)
            return {"header": header, "entries_verified": len(entries)}
        if args.catalog_command == "search":
            return search_snapshot(snapshot, args.query, archetype=args.archetype, limit=args.limit)
        return build_snapshot(
            args.functional_root,
            args.package_root,
            args.output,
            require_expected_counts=not args.allow_count_drift,
        )
    if args.command == "spec":
        if args.spec_command == "scaffold":
            return default_strategy_spec(
                args.archetype,
                args.output_profile,
                args.dataset_id,
                feed_count=args.feed_count,
                custom_lines=args.custom_line,
            )
        return validate_strategy_spec(_json_file(args.spec))
    if args.command == "render":
        manager = DraftManager(paths)
        if args.render_command == "preview":
            return manager.preview(
                _json_file(args.spec),
                expected_hashes=_expected_hashes(args.expected_hash),
            )
        if args.render_command == "validate":
            return manager.validate(args.draft_id)
        return manager.apply(args.draft_id, args.token_id)
    if args.command == "approval":
        store = TokenStore(paths)
        if args.approval_command == "show":
            return store.get(args.token_id)
        if args.approval_command == "approve":
            return store.approve(args.token_id)
        return store.revoke(args.token_id)
    if args.command == "review":
        return validate_python(args.file.resolve(), generated_only=not args.allow_third_party)
    if args.command == "run":
        runner = ControlledRunner(paths)
        if args.run_command == "prepare":
            return runner.prepare(
                args.candidate.resolve(), args.dataset_id, timeout_seconds=args.timeout
            )
        return runner.execute(args.run_id, args.token_id)
    if args.command == "compare":
        left = _json_file(args.left)
        right = _json_file(args.right)
        left_metrics = left.get("metrics", left)
        right_metrics = right.get("metrics", right)
        return compare_metrics(left_metrics, right_metrics)
    if args.command == "repair":
        if args.draft_id:
            return preview_repair(paths, args.draft_id)
        if args.validation_report is None:
            raise ValueError("--spec repair also requires --validation-report")
        if args.spec is None:
            raise AssertionError("repair parser requires --draft-id or --spec")
        return preview_spec_repair(
            paths,
            _json_file(args.spec),
            _json_file(args.validation_report),
        )
    if args.command == "install":
        installer = SkillInstaller(paths)
        if args.install_command == "preview":
            return installer.preview_install(args.host)
        if args.install_command == "apply":
            return installer.apply_install(args.plan_id, args.token_id)
        if args.install_command == "uninstall-preview":
            return installer.preview_uninstall(args.host)
        return installer.apply_uninstall(args.plan_id, args.token_id)
    raise AssertionError("unreachable command")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
    except SkillsError as error:
        _emit(
            {
                "status": "error",
                "code": error.code,
                "message": str(error),
                "details": error.details,
            }
        )
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _emit(
            {
                "status": "error",
                "code": "INPUT_OR_IO_ERROR",
                "message": str(error),
            }
        )
        return 2
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
