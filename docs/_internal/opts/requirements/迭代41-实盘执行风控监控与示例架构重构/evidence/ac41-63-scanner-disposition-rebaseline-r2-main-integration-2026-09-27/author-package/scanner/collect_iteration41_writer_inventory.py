"""Collect a reviewable static candidate inventory for Iteration 41 writers.

The collector deliberately does not execute example code, import providers, or
infer that a syntax hit is a reachable external order.  Its purpose is to make
the remaining review surface explicit before a route is admitted.  Dynamic
imports and subprocess launch points are reported separately because a static
AST scan cannot prove their eventual target.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = "iteration41.live-execution-inventory.v1"
SURFACE_BASELINE_SCHEMA_VERSION = "iteration41.writer-inventory-surface-baseline.v1"
SURFACE_BASELINE_PATH = Path(__file__).with_name("iteration41_writer_inventory_scope.json")
GENERATED_EXAMPLE_DIRECTORY_NAMES = frozenset(("__pycache__",))
GENERATED_EXAMPLE_PATHS = frozenset(("examples/logs",))
PRIVATE_RUNTIME_STATE_PATH = "examples/013_3_sa_midfreq_simnow/runtime-ctp-private/state"
DEFAULT_SCOPE_PATHS = (
    "backtrader_runtime",
    "backtrader/stores",
    "backtrader/brokers",
    "examples/007_ctp",
    "examples/010_live_examples",
    "examples/013_1_midfreq_cross_arbitrage",
    "examples/013_2_highfreq_calendar_arbitrage",
    "examples/013_3_sa_midfreq_simnow",
    "examples/014_1_ctp_options_lowfreq",
    "examples/014_2_ctp_options_midfreq",
    "examples/015_ctp_options_highfreq",
    "examples/sample.py",
    "ctp_options_simnow_approval_issuer.py",
    "ctp_options_simnow_live_runner.py",
    "ctp_options_simnow_mechanical_cycle.py",
    "ctp_options_simnow_mechanical_operator.py",
    "ctp_options_simnow_operator.py",
    "examples/ctp_options_simnow_managed_replay_runtime.py",
)
HISTORICAL_CTP_CANDIDATE_SCOPES = (
    {
        "path": "examples/014_1_ctp_options_lowfreq",
        "classification": "HISTORICAL_CTP_SOURCE_ENTRYPOINTS_FENCED",
        "boundary": (
            "Direct legacy entrypoints are config-first/replay-only and retained writer names "
            "reject; static source candidates remain review-required."
        ),
        "verification_tests": ["tests/unit/runtime/test_iteration41_legacy_014_gate.py"],
    },
    {
        "path": "examples/014_2_ctp_options_midfreq",
        "classification": "HISTORICAL_CTP_SOURCE_ENTRYPOINTS_FENCED",
        "boundary": (
            "Direct legacy entrypoints are config-first/replay-only and retained writer names "
            "reject; static source candidates remain review-required."
        ),
        "verification_tests": ["tests/unit/runtime/test_iteration41_legacy_014_gate.py"],
    },
    {
        "path": "examples/015_ctp_options_highfreq",
        "classification": "HISTORICAL_CTP_SOURCE_REPLAY_ONLY",
        "boundary": (
            "The retained run.py rejects shadow, SimNow, and production before replay/session "
            "setup; simnow_launcher dispatches through the fixed Iteration 41 replay runtime. "
            "These facts do not make the historical source an admitted route."
        ),
        "verification_tests": [
            "tests/unit/test_iteration41_ctp_options_highfreq_runtime.py",
            "tests/unit/test_ctp_options_highfreq_example.py",
        ],
    },
)
WRITER_METHODS = frozenset(
    (
        "submit_order",
        "submit_order_insert",
        "place_order",
        "cancel_order",
        "cancel_order_ref",
        "cancel_all",
        "cancel_all_orders",
        "batch_cancel",
        "buy",
        "sell",
        "close",
    )
)
_DYNAMIC_QUALIFIED_CALLS = frozenset(
    (
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
        "subprocess.run",
        "os.system",
        "os.popen",
        "importlib.import_module",
        "builtins.__import__",
    )
)
_DYNAMIC_BARE_CALLS = frozenset(("__import__", "eval", "exec"))


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _qualified_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return "{0}.{1}".format(prefix, node.attr) if prefix else node.attr
    return None


class _CandidateVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.writer_candidates: List[Dict[str, object]] = []
        self.dynamic_candidates: List[Dict[str, object]] = []
        self._class_stack: List[str] = []
        self._function_stack: List[str] = []
        self._writer_alias_scopes: list[dict[str, tuple[str, ...]]] = []
        self._callable_alias_scopes: list[dict[str, bool]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_stack.append(node.name)
        self._writer_alias_scopes.append({})
        self._callable_alias_scopes.append({})
        self.generic_visit(node)
        self._callable_alias_scopes.pop()
        self._writer_alias_scopes.pop()
        self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function_stack.append(node.name)
        self._writer_alias_scopes.append({})
        self._callable_alias_scopes.append({})
        self.generic_visit(node)
        self._callable_alias_scopes.pop()
        self._writer_alias_scopes.pop()
        self._function_stack.pop()

    @staticmethod
    def _target_names(target: ast.AST) -> tuple[str, ...]:
        if isinstance(target, ast.Name):
            return (target.id,)
        if isinstance(target, (ast.Tuple, ast.List)):
            return tuple(
                name
                for item in target.elts
                for name in _CandidateVisitor._target_names(item)
            )
        return ()

    def _lookup_writer_alias(self, name: str) -> tuple[str, ...]:
        for scope in reversed(self._writer_alias_scopes):
            if name in scope:
                return scope[name]
        return ()

    def _lookup_callable_alias(self, name: str) -> bool:
        return any(name in scope for scope in reversed(self._callable_alias_scopes))

    def _is_callable_alias_source(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return self._lookup_callable_alias(node.id)
        if (
            isinstance(node, ast.Call)
            and _qualified_name(node.func) == "getattr"
            and len(node.args) >= 2
            and not (
                isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            )
        ):
            return True
        if isinstance(node, ast.IfExp):
            return self._is_callable_alias_source(node.body) or self._is_callable_alias_source(
                node.orelse
            )
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return any(self._is_callable_alias_source(item) for item in node.elts)
        return False

    def _referenced_writer_methods(self, node: ast.AST) -> tuple[str, ...]:
        """Resolve simple local aliases to public writer methods conservatively."""
        if isinstance(node, ast.Attribute):
            return (node.attr,) if node.attr in WRITER_METHODS else ()
        if isinstance(node, ast.Name):
            return self._lookup_writer_alias(node.id)
        if isinstance(node, ast.Call) and _qualified_name(node.func) == "getattr":
            if (
                len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and node.args[1].value in WRITER_METHODS
            ):
                return (node.args[1].value,)
            return ()
        if isinstance(node, ast.IfExp):
            return tuple(
                sorted(
                    set(self._referenced_writer_methods(node.body))
                    | set(self._referenced_writer_methods(node.orelse))
                )
            )
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return tuple(
                sorted(
                    {
                        method
                        for item in node.elts
                        for method in self._referenced_writer_methods(item)
                    }
                )
            )
        return ()

    def _remember_writer_alias(self, targets: Iterable[ast.AST], value: ast.AST) -> None:
        if not self._writer_alias_scopes:
            return
        target_names = tuple(
            name for target in targets for name in self._target_names(target)
        )
        if not target_names:
            return
        if self._is_callable_alias_source(value):
            callable_scope = self._callable_alias_scopes[-1]
            for name in target_names:
                callable_scope[name] = True
        methods = self._referenced_writer_methods(value)
        if methods:
            scope = self._writer_alias_scopes[-1]
            for name in target_names:
                scope[name] = tuple(sorted(set(scope.get(name, ())) | set(methods)))

    def visit_Assign(self, node: ast.Assign) -> None:
        self._remember_writer_alias(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._remember_writer_alias((node.target,), node.value)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._remember_writer_alias((node.target,), node.value)
        self.generic_visit(node)

    def _location(self, node: ast.AST) -> Dict[str, object]:
        return {
            "path": self.relative_path,
            "line": getattr(node, "lineno", None),
            "column": getattr(node, "col_offset", None),
            "class_name": self._class_stack[-1] if self._class_stack else None,
            "function_name": self._function_stack[-1] if self._function_stack else None,
        }

    def visit_Call(self, node: ast.Call) -> None:
        qualified_name = _qualified_name(node.func)
        terminal_name = None
        if isinstance(node.func, ast.Attribute):
            terminal_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            terminal_name = node.func.id

        if terminal_name in WRITER_METHODS:
            candidate = self._location(node)
            candidate.update(
                {
                    "kind": "writer_call_candidate",
                    "call": qualified_name or terminal_name,
                    "method": terminal_name,
                    "review_status": "REVIEW_REQUIRED",
                }
            )
            self.writer_candidates.append(candidate)

        is_writer_reflection = (
            terminal_name == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value in WRITER_METHODS
        )
        is_dynamic_attribute_forwarder = (
            terminal_name == "getattr"
            and bool(self._function_stack)
            and self._function_stack[-1] == "__getattr__"
            and len(node.args) >= 2
            and not (
                isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            )
        )
        is_dynamic = (
            qualified_name in _DYNAMIC_QUALIFIED_CALLS
            or terminal_name in _DYNAMIC_BARE_CALLS
            or is_writer_reflection
            or is_dynamic_attribute_forwarder
        )
        if is_dynamic:
            candidate = self._location(node)
            candidate.update(
                {
                    "kind": "dynamic_execution_candidate",
                    "call": qualified_name or terminal_name,
                    "dynamic_reason": (
                        "writer_reflection"
                        if is_writer_reflection
                        else "dynamic_attribute_forwarder"
                        if is_dynamic_attribute_forwarder
                        else "dynamic_execution"
                    ),
                    "review_status": "REVIEW_REQUIRED",
                }
            )
            self.dynamic_candidates.append(candidate)

        if isinstance(node.func, ast.Name) and terminal_name not in WRITER_METHODS:
            alias_methods = self._lookup_writer_alias(node.func.id)
            for method in alias_methods:
                candidate = self._location(node)
                candidate.update(
                    {
                        "kind": "writer_call_candidate",
                        "call": node.func.id,
                        "method": method,
                        "dynamic_reason": "writer_alias_dispatch",
                        "review_status": "REVIEW_REQUIRED",
                    }
                )
                self.writer_candidates.append(candidate)
            if not alias_methods and self._lookup_callable_alias(node.func.id):
                candidate = self._location(node)
                candidate.update(
                    {
                        "kind": "dynamic_execution_candidate",
                        "call": node.func.id,
                        "dynamic_reason": "indirect_callable_alias",
                        "review_status": "REVIEW_REQUIRED",
                    }
                )
                self.dynamic_candidates.append(candidate)

        self.generic_visit(node)


def _iter_source_files(root: Path, includes: Iterable[str]) -> Iterable[Path]:
    resolved_root = root.resolve()
    seen = set()
    for include in includes:
        candidate = (resolved_root / include).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            raise ValueError(
                "inventory scope must stay below source root: {0}".format(include)
            ) from None
        if not candidate.exists():
            continue
        paths = candidate.rglob("*.py") if candidate.is_dir() else (candidate,)
        for path in paths:
            if not path.is_file() or path in seen:
                continue
            relative_path = _relative_path(resolved_root, path)
            if relative_path == PRIVATE_RUNTIME_STATE_PATH or relative_path.startswith(
                PRIVATE_RUNTIME_STATE_PATH + "/"
            ):
                continue
            if any(
                relative_path == generated_path
                or relative_path.startswith(generated_path + "/")
                for generated_path in GENERATED_EXAMPLE_PATHS
            ) or any(
                part in GENERATED_EXAMPLE_DIRECTORY_NAMES for part in Path(relative_path).parts
            ):
                continue
            seen.add(path)
            yield path


def _default_scope_paths(root: Path) -> Tuple[str, ...]:
    """Add the complete examples tree and every root-level Python script."""

    root_scripts = tuple(
        path.name for path in sorted(root.glob("*.py"), key=lambda item: item.name)
    )
    return DEFAULT_SCOPE_PATHS + ("examples",) + root_scripts


def _load_surface_baseline(path: Path = SURFACE_BASELINE_PATH) -> Dict[str, Dict[str, str]]:
    """Load the reviewed source-path baseline without importing repository code."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("inventory surface baseline unavailable or invalid") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SURFACE_BASELINE_SCHEMA_VERSION
    ):
        raise ValueError("inventory surface baseline schema invalid")
    entries = payload.get("paths")
    if not isinstance(entries, list):
        raise ValueError("inventory surface baseline paths invalid")

    baseline: Dict[str, Dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("inventory surface baseline entry invalid")
        path_value = entry.get("path")
        kind = entry.get("kind")
        classification = entry.get("classification")
        if not all(
            isinstance(value, str) and value
            for value in (path_value, kind, classification)
        ):
            raise ValueError("inventory surface baseline entry fields invalid")
        if path_value in baseline:
            raise ValueError("inventory surface baseline path duplicated")
        baseline[path_value] = {"kind": kind, "classification": classification}
    return baseline


def _discover_surface_paths(root: Path) -> List[Dict[str, str]]:
    """Discover every examples subdirectory and root Python script.

    Python bytecode cache directories are listed with an explicit generated
    classification and are not traversed.  Their presence is machine-created
    and must not make the source-path baseline unstable.
    """

    resolved_root = root.resolve()
    examples_root = resolved_root / "examples"
    paths: List[Dict[str, str]] = []
    if examples_root.is_dir():
        for current, directory_names, _ in os.walk(str(examples_root), topdown=True):
            directory_names.sort()
            retained_names = []
            current_path = Path(current)
            for directory_name in directory_names:
                directory = current_path / directory_name
                relative = _relative_path(resolved_root, directory)
                if directory_name in GENERATED_EXAMPLE_DIRECTORY_NAMES:
                    paths.append(
                        {
                            "path": relative,
                            "kind": "example_directory",
                            "classification": "GENERATED_PYTHON_CACHE",
                        }
                    )
                    continue
                if relative in GENERATED_EXAMPLE_PATHS:
                    paths.append(
                        {
                            "path": relative,
                            "kind": "example_directory",
                            "classification": "GENERATED_RUNTIME_OUTPUT",
                        }
                    )
                    continue
                if relative == PRIVATE_RUNTIME_STATE_PATH:
                    paths.append(
                        {
                            "path": relative,
                            "kind": "example_directory",
                            "classification": "PRIVATE_RUNTIME_STATE_OMITTED",
                        }
                    )
                    continue
                paths.append(
                    {
                        "path": relative,
                        "kind": "example_directory",
                    }
                )
                # Do not traverse a symlinked directory.  It remains visible
                # as a path candidate and will be UNCLASSIFIED unless reviewed.
                if directory.is_symlink():
                    continue
                retained_names.append(directory_name)
            directory_names[:] = retained_names

    for script in sorted(resolved_root.glob("*.py"), key=lambda item: item.name):
        paths.append(
            {
                "path": _relative_path(resolved_root, script),
                "kind": "repository_root_python_script",
            }
        )
    paths.sort(key=lambda item: (item["path"], item["kind"]))
    return paths


def classify_repository_surface(
    root: Path, baseline: Optional[Dict[str, Dict[str, str]]] = None
) -> Dict[str, object]:
    """Mark newly discovered source paths UNCLASSIFIED against a controlled baseline.

    These classifications describe scan coverage only.  They never classify a
    writer as safe, reachable, unavailable, or authorized.
    """

    reviewed_baseline = baseline if baseline is not None else _load_surface_baseline()
    discovered = _discover_surface_paths(root)
    classified_paths: List[Dict[str, str]] = []
    unclassified_paths: List[Dict[str, str]] = []
    discovered_path_names = set()
    for discovered_path in discovered:
        path_value = discovered_path["path"]
        discovered_path_names.add(path_value)
        automatic_classification = discovered_path.get("classification")
        expected = reviewed_baseline.get(path_value)
        if automatic_classification:
            classification = automatic_classification
        elif expected is not None and expected.get("kind") == discovered_path["kind"]:
            classification = expected["classification"]
        else:
            classification = "UNCLASSIFIED"
        record = dict(discovered_path)
        record["classification"] = classification
        if classification == "UNCLASSIFIED":
            record["candidate_kind"] = "unclassified_source_path"
            record["review_status"] = "REVIEW_REQUIRED"
            unclassified_paths.append(record)
        classified_paths.append(record)

    missing_baseline_paths = sorted(set(reviewed_baseline) - discovered_path_names)
    return {
        "schema_version": SURFACE_BASELINE_SCHEMA_VERSION,
        "status": (
            "UNCLASSIFIED_PATHS_PRESENT" if unclassified_paths else "BASELINE_CLASSIFIED"
        ),
        "classification_scope": "STATIC_SOURCE_PATH_COVERAGE_ONLY",
        "paths": classified_paths,
        "unclassified_paths": unclassified_paths,
        "missing_baseline_paths": missing_baseline_paths,
        "counts": {
            "discovered_paths": len(discovered),
            "unclassified_paths": len(unclassified_paths),
            "missing_baseline_paths": len(missing_baseline_paths),
        },
        "limitations": [
            "Path classification records source-scan coverage only; it is not a writer disposition or route authorization.",
            "The AST scan does not establish reachability or prove runtime writer closure.",
            "New examples directories and repository-root Python scripts remain UNCLASSIFIED until the controlled baseline is reviewed and updated.",
            "Generated examples/logs and __pycache__ paths are classified as generated output; the private CTP runtime state subtree is summarized without scanning or enumerating its contents.",
        ],
    }


def collect_inventory(
    root: Path, includes: Optional[Iterable[str]] = None
) -> Dict[str, object]:
    """Return static writer and dynamic-execution candidates for reviewed paths."""

    resolved_root = root.resolve()
    complete_default_scope = includes is None
    effective_includes = (
        _default_scope_paths(resolved_root)
        if complete_default_scope
        else tuple(includes)
    )
    writer_candidates: List[Dict[str, object]] = []
    dynamic_candidates: List[Dict[str, object]] = []
    parse_errors: List[Dict[str, object]] = []
    files_scanned: List[str] = []

    for source_path in sorted(_iter_source_files(resolved_root, effective_includes)):
        relative_path = _relative_path(resolved_root, source_path)
        files_scanned.append(relative_path)
        try:
            source = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_path))
        except (OSError, UnicodeError, SyntaxError) as error:
            parse_errors.append(
                {
                    "path": relative_path,
                    "error_type": type(error).__name__,
                    "line": getattr(error, "lineno", None),
                }
            )
            continue
        visitor = _CandidateVisitor(relative_path)
        visitor.visit(tree)
        writer_candidates.extend(visitor.writer_candidates)
        dynamic_candidates.extend(visitor.dynamic_candidates)

    writer_candidates.sort(
        key=lambda item: (str(item["path"]), int(item["line"] or 0), str(item["call"]))
    )
    dynamic_candidates.sort(
        key=lambda item: (str(item["path"]), int(item["line"] or 0), str(item["call"]))
    )
    parse_errors.sort(key=lambda item: str(item["path"]))
    historical_ctp_candidate_scopes = [
        dict(scope)
        for scope in HISTORICAL_CTP_CANDIDATE_SCOPES
        if any(scanned_path.startswith(str(scope["path"]) + "/") for scanned_path in files_scanned)
    ]
    if complete_default_scope:
        source_path_coverage = classify_repository_surface(resolved_root)
    else:
        source_path_coverage = {
            "schema_version": SURFACE_BASELINE_SCHEMA_VERSION,
            "status": "CUSTOM_SCOPE_NOT_CLASSIFIED",
            "classification_scope": "STATIC_SOURCE_PATH_COVERAGE_ONLY",
            "paths": [],
            "unclassified_paths": [],
            "missing_baseline_paths": [],
            "counts": {
                "discovered_paths": 0,
                "unclassified_paths": 0,
                "missing_baseline_paths": 0,
            },
            "limitations": [
                "Explicit --include/custom API scope is intentionally partial and does not load the repository-wide source-path baseline."
            ],
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "CANDIDATE_DISCOVERY_ONLY",
        # Keep generated evidence portable and free of machine-specific paths.
        "source_root": ".",
        "scope_paths": list(effective_includes),
        "files_scanned": files_scanned,
        "source_path_coverage": source_path_coverage,
        "historical_ctp_candidate_scopes": historical_ctp_candidate_scopes,
        "writer_candidates": writer_candidates,
        "dynamic_execution_candidates": dynamic_candidates,
        "parse_errors": parse_errors,
        "counts": {
            "files_scanned": len(files_scanned),
            "writer_candidates": len(writer_candidates),
            "dynamic_execution_candidates": len(dynamic_candidates),
            "parse_errors": len(parse_errors),
        },
        "limitations": [
            "AST candidates do not prove reachability, provider I/O, or a permitted route.",
            "A static scan cannot prove that dynamically computed imports, subprocess commands, or reflection are complete.",
            "Every candidate remains REVIEW_REQUIRED until its separate disposition record has an owner, route, test node, and trace/evidence disposition; an AST record is not fake/real trace proof.",
            "The serialized source_root is a relative dot marker; the host-specific absolute path is intentionally omitted.",
            "Historical CTP scope labels document separate entrypoint boundaries only; they do not prove candidate reachability or authorize a runtime route.",
            "This collector never imports strategies, providers, SDK capability packages, or Backtrader runtime code.",
        ],
    }


def _write_json_atomically(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".iteration41-inventory-", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="collect Iteration 41 static writer candidates without importing runtime code"
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        help=(
            "relative file or directory to scan; repeatable; omitted means the Iteration 41 "
            "scope plus all examples and repository-root Python scripts"
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    includes: Optional[Tuple[str, ...]] = tuple(args.include) if args.include else None
    try:
        payload = collect_inventory(args.source_root, includes)
    except ValueError as error:
        print(json.dumps({"status": "REJECTED", "reason": str(error)}, ensure_ascii=False))
        return 2
    payload["generated_at"] = _datetime.datetime.now(_datetime.timezone.utc).isoformat()
    _write_json_atomically(args.output, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "source_path_coverage_status": payload["source_path_coverage"]["status"],
                "output": str(args.output),
                "counts": payload["counts"],
                "unclassified_paths": payload["source_path_coverage"]["counts"][
                    "unclassified_paths"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in CI.
    raise SystemExit(main())
