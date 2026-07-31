"""Typed command-line interface for deterministic agent actions."""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .audit import IndependenceAuditor
from .canonical import hash_object, sha256_bytes
from .catalog import SnapshotCatalog
from .changes import ChangeManager
from .contracts import StrategySpec
from .data import DatasetService
from .doctor import diagnose
from .engines import inspect_engine
from .errors import AgentError
from .installer import AdapterInstaller
from .repair import RepairWorkflow
from .report import compare_metrics, normalize_metrics
from .roots import RootRegistry
from .runner import ControlledRunner
from .scaffold import ArtifactRenderer
from .sessions import SessionStore
from .tokens import TokenAuthority
from .validator import StrategyValidator


def _json_file(path: str) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AgentError("BTAG-CLI-JSON", "input JSON must be an object")
    return value


def _emit(value: Dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _state(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "state_root", ".backtrader-agent")).resolve()


def _runtime(args: argparse.Namespace):
    state = _state(args)
    roots = RootRegistry(state)
    authority = TokenAuthority(state)
    return state, roots, authority


RUN_ID_RE = re.compile(r"^run-[0-9a-f]{20}$")


def _state_run_result(state: Path, run_id: str) -> Dict[str, Any]:
    if not RUN_ID_RE.fullmatch(run_id):
        raise AgentError("BTAG-RUN-ID", "run ID is malformed")
    path = state / "runs" / run_id / "run-result.json"
    if not path.is_file():
        raise AgentError("BTAG-RUN-UNKNOWN", "run result does not exist")
    result = _json_file(str(path))
    if result.get("schema_version") != "run-result-v1":
        raise AgentError("BTAG-RUN-RESULT", "run result schema is invalid")
    expected = result.get("result_hash")
    portable = {key: value for key, value in result.items() if key != "result_hash"}
    if expected != hash_object(portable):
        raise AgentError("BTAG-RUN-RESULT", "run result hash is invalid")
    result["metrics"] = normalize_metrics(result.get("metrics", {}))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backtrader-agent",
        description="Independent deterministic Backtrader agent runtime",
    )
    parser.add_argument("--state-root", default=".backtrader-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="diagnose environment and packaged capabilities")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub.add_parser("payload", help="return packaged product-owned agent instructions")

    roots = sub.add_parser("roots", help="manage opaque controlled roots")
    roots_sub = roots.add_subparsers(dest="roots_command", required=True)
    root_register = roots_sub.add_parser("register")
    root_register.add_argument("--id", required=True)
    root_register.add_argument("--path", required=True)
    root_register.add_argument(
        "--kind", choices=["workspace", "dataset", "engine", "runtime"], required=True
    )
    root_register.add_argument("--writable", action="store_true")
    roots_sub.add_parser("list")

    engine = sub.add_parser("engine", help="inspect a registered Backtrader runtime")
    engine.add_argument("--root-id", required=True)

    data = sub.add_parser("data", help="inspect, register, or preview offline data")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    inspect_data = data_sub.add_parser("inspect")
    inspect_data.add_argument("--spec", required=True, help="DataSpec JSON")
    register_data = data_sub.add_parser("register")
    register_data.add_argument("--spec", required=True, help="DataSpec JSON")
    register_data.add_argument("--session-id", required=True)
    preview = data_sub.add_parser("preview")
    preview.add_argument("--dataset-id", required=True)
    preview.add_argument("--rows", type=int, default=5)

    spec = sub.add_parser("spec", help="validate StrategySpec")
    spec.add_argument("--file", required=True)
    spec.add_argument("--session-id", required=True)
    spec.add_argument("--approve", action="store_true", required=True)

    catalog = sub.add_parser("catalog", help="search or inspect packaged snapshot")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    search = catalog_sub.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--archetype")
    search.add_argument("--profile", choices=["single_test", "python_bundle"])
    search.add_argument("--top-k", type=int, default=5)
    inspect = catalog_sub.add_parser("inspect")
    inspect.add_argument("--entry-id", required=True)
    refresh = catalog_sub.add_parser("refresh")
    refresh.add_argument("--functional-root-id", required=True)
    refresh.add_argument("--package-root-id", required=True)
    refresh.add_argument("--allow-count-drift", action="store_true")

    draft = sub.add_parser("draft", help="render a product-owned scaffold")
    draft.add_argument("--session-id", required=True)
    draft.add_argument("--spec", required=True)
    draft.add_argument("--dataset-manifest", required=True)

    validate = sub.add_parser("validate", help="AST/security validate a draft artifact")
    validate.add_argument("--artifact-manifest", required=True)
    validate.add_argument("--draft-root", required=True)
    validate.add_argument("--session-id", required=True)
    validate.add_argument("--dataset-hash", required=True)
    engine_binding = validate.add_mutually_exclusive_group(required=True)
    engine_binding.add_argument("--engine-root-id")
    engine_binding.add_argument("--engine-hash")
    validate.add_argument("--environment-hash", required=True)

    approval = sub.add_parser("approval", help="request and locally grant one-time actions")
    approval_sub = approval.add_subparsers(dest="approval_command", required=True)
    approval_request = approval_sub.add_parser("request")
    approval_request.add_argument("--kind", choices=["change", "run"], required=True)
    approval_request.add_argument("--subject-hash", required=True)
    approval_request.add_argument("--bindings", required=True, help="JSON object")
    approval_grant = approval_sub.add_parser("grant")
    approval_grant.add_argument("--request-id", required=True)
    approval_grant.add_argument("--approver", required=True)
    approval_grant.add_argument("--confirm", action="store_true", required=True)

    changes = sub.add_parser("changes", help="prepare or apply a confined change set")
    change_sub = changes.add_subparsers(dest="change_command", required=True)
    prepare = change_sub.add_parser("prepare")
    prepare.add_argument("--session-id", required=True)
    prepare.add_argument("--draft-root", required=True)
    prepare.add_argument("--files", required=True, help="JSON array of source/target entries")
    prepare.add_argument("--target-root-id", required=True)
    prepare.add_argument("--validation-token", required=True)
    apply_action = change_sub.add_parser("apply")
    apply_action.add_argument("--manifest", required=True)
    apply_action.add_argument("--change-token", required=True)
    apply_action.add_argument("--idempotency-key", required=True)

    run = sub.add_parser("run", help="execute a fixed controlled child-process profile")
    run.add_argument("--applied-artifact", required=True)
    run.add_argument("--dataset-manifest", required=True)
    run.add_argument("--validation-token", required=True)
    run.add_argument("--run-token", required=True)
    run.add_argument("--mode", choices=["runonce", "runnext"], required=True)
    run.add_argument("--idempotency-key", required=True)
    run.add_argument("--timeout", type=int, default=120)

    run_subject = sub.add_parser(
        "run-subject", help="compute the exact hash that a run approval must bind"
    )
    run_subject.add_argument("--applied-artifact", required=True)
    run_subject.add_argument("--dataset-manifest", required=True)
    run_subject.add_argument("--validation-token", required=True)
    run_subject.add_argument("--mode", choices=["runonce", "runnext"], required=True)

    compare = sub.add_parser("compare", help="compare two immutable local RunResult objects")
    compare.add_argument("--left-run-id", required=True)
    compare.add_argument("--right-run-id", required=True)

    report = sub.add_parser("report", help="read an immutable local run report")
    report.add_argument("--run-id", required=True)
    report.add_argument("--format", choices=["json", "markdown", "html"], default="markdown")

    repair = sub.add_parser(
        "repair",
        help="revise StrategySpec and deterministically re-render a failed owned draft",
    )
    repair.add_argument("--session-id", required=True)
    repair.add_argument("--spec", required=True)
    repair.add_argument("--dataset-manifest", required=True)
    repair.add_argument("--failure-report", required=True)

    session = sub.add_parser("session", help="create, inspect, recover, cancel, or archive")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    for name in ("create", "status", "recover", "cancel", "archive"):
        action = session_sub.add_parser(name)
        action.add_argument("--session-id", required=True)

    install = sub.add_parser("install", help="preview/apply a native host adapter")
    install.add_argument("--target", required=True)
    install.add_argument(
        "--host", choices=["claude", "codex", "opencode", "openclaw"], required=True
    )
    mode = install.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--uninstall", action="store_true")

    audit = sub.add_parser("audit-independence", help="verify no sibling product dependency")
    audit.add_argument("--product-root", default=str(Path(__file__).resolve().parents[2]))
    return parser


def dispatch(args: argparse.Namespace) -> Dict[str, Any]:
    if args.command == "doctor":
        return diagnose()
    if args.command == "payload":
        payload_path = Path(__file__).resolve().parent / "resources" / "agent-payload.md"
        content = payload_path.read_text(encoding="utf-8")
        return {
            "schema_version": "agent-payload-v1",
            "payload": content,
            "sha256": sha256_bytes(content.encode("utf-8")),
        }
    state, roots, authority = _runtime(args)
    if args.command == "roots":
        if args.roots_command == "register":
            return roots.register(args.id, Path(args.path), writable=args.writable, kind=args.kind)
        return {"roots": roots.list()}
    if args.command == "engine":
        return inspect_engine(roots, args.root_id)
    if args.command == "data":
        service = DatasetService(roots, state)
        if args.data_command == "inspect":
            value = service.inspect(_json_file(args.spec))
            value.pop("_canonical_feeds", None)
            return value
        if args.data_command == "register":
            value = service.register(_json_file(args.spec))
            SessionStore(state).transition(
                args.session_id,
                "DATA_READY",
                "dataset-register",
                {"dataset": value["manifest_hash"]},
                effect_references={
                    "dataset_id": value["dataset_id"],
                    "dataset_manifest_hash": value["manifest_hash"],
                },
            )
            return value
        return service.preview(args.dataset_id, rows=args.rows)
    if args.command == "spec":
        specification = StrategySpec.from_dict(_json_file(args.file))
        sessions = SessionStore(state)
        sessions.transition(
            args.session_id,
            "SPEC_DRAFT",
            "spec-draft",
            {"spec": specification.spec_hash},
            effect_references={"spec_hash": specification.spec_hash},
        )
        sessions.transition(
            args.session_id,
            "SPEC_APPROVED",
            "spec-approve",
            {"spec": specification.spec_hash},
            effect_references={"approved_spec_hash": specification.spec_hash},
        )
        return specification.to_dict()
    if args.command == "catalog":
        catalog = SnapshotCatalog()
        if args.catalog_command == "search":
            return {
                "results": catalog.search(
                    args.query,
                    archetype=args.archetype,
                    profile=args.profile,
                    top_k=args.top_k,
                )
            }
        if args.catalog_command == "inspect":
            return catalog.inspect(args.entry_id)
        functional = roots.get_record(args.functional_root_id)
        packages = roots.get_record(args.package_root_id)
        if functional["writable"] or packages["writable"]:
            raise AgentError(
                "BTAG-CATALOG-ROOT",
                "source-attached catalog roots must be registered read-only",
            )
        output = state / "catalog" / "source-attached.jsonl"
        return SnapshotCatalog.refresh_source_attached(
            Path(functional["path"]),
            Path(packages["path"]),
            output,
            require_verified_counts=not args.allow_count_drift,
        )
    if args.command == "draft":
        specification = StrategySpec.from_dict(_json_file(args.spec))
        value = ArtifactRenderer(state).render(
            args.session_id, specification, _json_file(args.dataset_manifest)
        )
        sessions = SessionStore(state)
        sessions.transition(
            args.session_id,
            "SOURCES_SELECTED",
            "sources-select",
            {"catalog": "package-snapshot-v1"},
        )
        sessions.transition(
            args.session_id,
            "DRAFT_READY",
            "draft-render",
            {"artifact": value["artifact_hash"]},
            effect_references={"artifact_hash": value["artifact_hash"]},
        )
        return value
    if args.command == "validate":
        artifact = _json_file(args.artifact_manifest)
        artifact["_draft_path"] = str(Path(args.draft_root).resolve())
        if args.engine_root_id:
            engine = inspect_engine(roots, args.engine_root_id)
            engine_bindings = {
                "engine_hash": engine["engine_hash"],
                "engine_root_id": args.engine_root_id,
            }
        else:
            engine_bindings = {"engine_hash": args.engine_hash}
        value = StrategyValidator(authority).validate_artifact(
            artifact,
            bindings={
                "dataset_hash": args.dataset_hash,
                "environment_hash": args.environment_hash,
                **engine_bindings,
            },
            approval="validator",
            session_id=args.session_id,
        )
        SessionStore(state).transition(
            args.session_id,
            "VALIDATED" if value["status"] == "passed" else "NEEDS_REVALIDATION",
            "strategy-validate",
            {"validation": value["validation_hash"]},
            effect_references=(
                {
                    "artifact_record_hash": value["validation_token"]["bindings"][
                        "artifact_record_hash"
                    ],
                    "validation_hash": value["validation_hash"],
                    "validation_token_hash": hash_object(value["validation_token"]),
                    "validation_token_id": value["validation_token"]["token_id"],
                }
                if value["status"] == "passed"
                else {"validation_hash": value["validation_hash"]}
            ),
        )
        return value
    if args.command == "approval":
        if args.approval_command == "grant":
            return authority.grant_approval(
                args.request_id,
                approver=args.approver,
                confirmed=args.confirm,
            )
        bindings = json.loads(args.bindings)
        if not isinstance(bindings, dict):
            raise AgentError("BTAG-CLI-BINDINGS", "token bindings must be a JSON object")
        return authority.prepare_approval(
            args.kind,
            args.subject_hash,
            {str(key): str(value) for key, value in bindings.items()},
        )
    if args.command == "changes":
        manager = ChangeManager(roots, state, authority)
        if args.change_command == "prepare":
            files = json.loads(args.files)
            if not isinstance(files, list):
                raise AgentError("BTAG-CLI-CHANGES", "files must be a JSON array")
            return manager.prepare(
                session_id=args.session_id,
                draft_root=Path(args.draft_root),
                files=files,
                target_root_id=args.target_root_id,
                validation_token=_json_file(args.validation_token),
            )
        manifest = _json_file(args.manifest)
        return manager.apply(
            manifest,
            _json_file(args.change_token),
            idempotency_key=args.idempotency_key,
        )
    if args.command == "run":
        return ControlledRunner(roots, state, authority).run(
            _json_file(args.applied_artifact),
            _json_file(args.dataset_manifest),
            _json_file(args.validation_token),
            _json_file(args.run_token),
            mode=args.mode,
            idempotency_key=args.idempotency_key,
            timeout_seconds=args.timeout,
        )
    if args.command == "run-subject":
        subject = ControlledRunner.compute_run_subject(
            _json_file(args.applied_artifact),
            _json_file(args.dataset_manifest),
            _json_file(args.validation_token),
            mode=args.mode,
        )
        return {"schema_version": "run-subject-v1", "subject_hash": subject}
    if args.command == "compare":
        left = _state_run_result(state, args.left_run_id)
        right = _state_run_result(state, args.right_run_id)
        comparison = compare_metrics(left["metrics"], right["metrics"])
        return {
            **comparison,
            "left_run_id": args.left_run_id,
            "right_run_id": args.right_run_id,
        }
    if args.command == "report":
        result = _state_run_result(state, args.run_id)
        if args.format == "json":
            return result
        suffix = "md" if args.format == "markdown" else "html"
        report_path = state / "runs" / args.run_id / f"report.{suffix}"
        if not report_path.is_file():
            raise AgentError("BTAG-REPORT-MISSING", "requested immutable report does not exist")
        content = report_path.read_text(encoding="utf-8")
        return {
            "schema_version": "report-view-v1",
            "run_id": args.run_id,
            "format": args.format,
            "sha256": sha256_bytes(content.encode("utf-8")),
            "content": content,
        }
    if args.command == "repair":
        return RepairWorkflow(state).rerender(
            args.session_id,
            _json_file(args.spec),
            _json_file(args.dataset_manifest),
            _json_file(args.failure_report),
        )
    if args.command == "session":
        sessions = SessionStore(state)
        if args.session_command == "create":
            return sessions.create(args.session_id)
        if args.session_command == "status":
            return sessions.load(args.session_id)
        if args.session_command == "recover":
            return sessions.recover(args.session_id)
        if args.session_command == "cancel":
            return sessions.cancel(args.session_id)
        return sessions.archive(args.session_id)
    if args.command == "install":
        installer = AdapterInstaller()
        if args.uninstall:
            return installer.uninstall(Path(args.target), args.host, apply=True)
        return installer.install(Path(args.target), args.host, apply=args.apply)
    if args.command == "audit-independence":
        return IndependenceAuditor(Path(args.product_root)).audit()
    raise AgentError("BTAG-CLI-COMMAND", "unknown command")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
    except AgentError as exc:
        _emit({"status": "failed", "diagnostic": exc.as_dict()})
        return 2
    except (OSError, ValueError, json.JSONDecodeError):
        _emit(
            {
                "status": "failed",
                "diagnostic": {
                    "code": "BTAG-CLI-INPUT",
                    "severity": "error",
                    "message": "input could not be read or parsed",
                },
            }
        )
        return 2
    _emit(result)
    return 0
