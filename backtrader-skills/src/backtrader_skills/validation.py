"""Non-executing AST and contract validation with stable diagnostics."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_hash, file_hash

FORBIDDEN_CALLS = {"exec", "eval", "compile", "__import__"}
FORBIDDEN_MODULES = {
    "asyncio.subprocess",
    "ftplib",
    "http.client",
    "httpx",
    "importlib",
    "os",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "telnetlib",
    "urllib",
}
ALLOWED_MODULES = {"backtrader"}
LIVE_COMPONENTS = {"IBStore", "CCXTStore", "OandaStore", "VCStore"}
FRAMEWORK_COMPONENT_NAMES = {
    "Indicator",
    "Analyzer",
    "Observer",
    "DataBase",
    "AbstractDataBase",
    "FeedBase",
}


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    file: str
    line: int
    column: int
    rule: str
    message: str
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "rule": self.rule,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def _diag(
    code: str,
    severity: str,
    path: Path,
    node: ast.AST | None,
    rule: str,
    message: str,
    suggestion: str,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=severity,
        file=path.name,
        line=getattr(node, "lineno", 1),
        column=getattr(node, "col_offset", 0),
        rule=rule,
        message=message,
        suggestion=suggestion,
    )


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _root_module(name: str) -> str:
    return name.split(".", maxsplit=1)[0]


def _is_forbidden_module(name: str) -> bool:
    return any(name == item or name.startswith(f"{item}.") for item in FORBIDDEN_MODULES)


def _is_super_init(node: ast.AST) -> bool:
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    call = node.value
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "__init__":
        return False
    value = call.func.value
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "super"
    )


def _first_executable_statement(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.stmt | None:
    for statement in function.body:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        return statement
    return None


def _uses_framework_state_before_super(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.AST | None:
    for statement in function.body:
        if _is_super_init(statement):
            return None
        for node in ast.walk(statement):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "self" and node.attr in {
                    "p",
                    "params",
                    "lines",
                    "datas",
                    "data",
                    "data0",
                }:
                    return node
    return None


def _strategy_classification(class_node: ast.ClassDef) -> str:
    bases = {_name(base) for base in class_node.bases}
    base_tails = {base.rsplit(".", maxsplit=1)[-1] for base in bases}
    if "Strategy" in base_tails:
        return "direct_strategy"
    if base_tails & FRAMEWORK_COMPONENT_NAMES:
        return "framework_component"
    return "custom_parent"


def validate_python(path: Path, *, generated_only: bool = True) -> dict[str, Any]:
    """Validate a candidate without importing, compiling, or executing it."""

    source = path.read_text(encoding="utf-8")
    diagnostics: list[Diagnostic] = []
    try:
        tree = ast.parse(source, filename=path.name, mode="exec")
    except SyntaxError as error:
        diagnostics.append(
            Diagnostic(
                code="PY_SYNTAX_ERROR",
                severity="error",
                file=path.name,
                line=error.lineno or 1,
                column=error.offset or 0,
                rule="python-syntax",
                message=error.msg,
                suggestion="Fix the syntax before requesting execution approval.",
            )
        )
        return _report(path, diagnostics, strategy_classes=[])
    strategy_classes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for module in modules:
                if _is_forbidden_module(module):
                    diagnostics.append(
                        _diag(
                            "SEC_FORBIDDEN_IMPORT",
                            "error",
                            path,
                            node,
                            "import-allowlist",
                            f"forbidden module import: {module}",
                            "Remove operating-system, process, network, and dynamic-import access.",
                        )
                    )
                elif _root_module(module) not in ALLOWED_MODULES:
                    diagnostics.append(
                        _diag(
                            "SEC_IMPORT_NOT_ALLOWLISTED",
                            "error",
                            path,
                            node,
                            "import-allowlist",
                            f"module is not allowlisted for P0 generated code: {module}",
                            "Generated candidates may import only the top-level backtrader module.",
                        )
                    )
                elif generated_only and (
                    isinstance(node, ast.ImportFrom) or module != "backtrader"
                ):
                    diagnostics.append(
                        _diag(
                            "SEC_IMPORT_FORM_NOT_ALLOWLISTED",
                            "error",
                            path,
                            node,
                            "import-allowlist",
                            f"generated candidates may not import module internals: {module}",
                            "Use `import backtrader as bt`; controller and filesystem modules "
                            "are never available to candidate code.",
                        )
                    )
        if isinstance(node, ast.Call):
            call_name = _name(node.func)
            if call_name.rsplit(".", maxsplit=1)[-1] in FORBIDDEN_CALLS:
                diagnostics.append(
                    _diag(
                        "SEC_DYNAMIC_EXECUTION",
                        "error",
                        path,
                        node,
                        "no-dynamic-execution",
                        f"dynamic execution is forbidden: {call_name}",
                        "Represent logic in StrategySpec Expression/Action/StateRule IR.",
                    )
                )
            if call_name in {"os.system", "os.popen"}:
                diagnostics.append(
                    _diag(
                        "SEC_COMMAND_EXECUTION",
                        "error",
                        path,
                        node,
                        "no-command-execution",
                        f"command execution is forbidden: {call_name}",
                        "Remove command execution from the strategy.",
                    )
                )
            if call_name.rsplit(".", maxsplit=1)[-1] in LIVE_COMPONENTS:
                diagnostics.append(
                    _diag(
                        "BT_LIVE_COMPONENT_FORBIDDEN",
                        "error",
                        path,
                        node,
                        "offline-only",
                        f"live store/broker is forbidden in P0: {call_name}",
                        "Use a registered offline DatasetManifest.",
                    )
                )
        if isinstance(node, ast.Subscript):
            slice_node = node.slice
            positive = (
                isinstance(slice_node, ast.Constant)
                and isinstance(slice_node.value, (int, float))
                and slice_node.value > 0
            )
            line_like = isinstance(node.value, ast.Attribute) and (
                node.value.attr
                in {"open", "high", "low", "close", "volume", "openinterest", "lines"}
                or "_skills_indicators" in _name(node.value)
            )
            if positive and line_like:
                diagnostics.append(
                    _diag(
                        "BT_LOOKAHEAD_POSITIVE_INDEX",
                        "error",
                        path,
                        node,
                        "no-lookahead",
                        "positive line index can read future data",
                        "Use index 0 for the current bar and negative indices for history.",
                    )
                )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if (value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value)) and len(value) > 1:
                diagnostics.append(
                    _diag(
                        "SEC_ABSOLUTE_PATH",
                        "error",
                        path,
                        node,
                        "portable-paths",
                        "absolute paths are forbidden in portable strategy artifacts",
                        "Bind data through an opaque dataset_id.",
                    )
                )
    for class_node in [item for item in tree.body if isinstance(item, ast.ClassDef)]:
        classification = _strategy_classification(class_node)
        init = next(
            (
                item
                for item in class_node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == "__init__"
            ),
            None,
        )
        if classification == "direct_strategy":
            strategy_classes.append(class_node.name)
            if init and any(_is_super_init(item) for item in init.body):
                diagnostics.append(
                    _diag(
                        "BT_DIRECT_STRATEGY_SUPER_REDUNDANT",
                        "warning",
                        path,
                        init,
                        "fork-construction-contract",
                        "direct bt.Strategy subclasses are pre-initialized by this fork",
                        "Omit super().__init__() in a direct bt.Strategy generated template.",
                    )
                )
        elif init is not None:
            first = _first_executable_statement(init)
            if first is None or not _is_super_init(first):
                offending = _uses_framework_state_before_super(init) or init
                diagnostics.append(
                    _diag(
                        "BT_COOPERATIVE_INIT_REQUIRED",
                        "error",
                        path,
                        offending,
                        "fork-construction-contract",
                        f"{classification} __init__ must call super().__init__() first",
                        "Place super().__init__() before accessing params, data, or lines.",
                    )
                )
    if not strategy_classes:
        diagnostics.append(
            _diag(
                "BT_STRATEGY_CLASS_MISSING",
                "error",
                path,
                tree,
                "strategy-entrypoint",
                "no direct bt.Strategy subclass was found",
                "Declare one class that directly subclasses bt.Strategy.",
            )
        )
    if generated_only:
        generated_classes = [
            class_node
            for class_node in tree.body
            if isinstance(class_node, ast.ClassDef)
            and any(
                isinstance(item, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "backtrader_skills_generated"
                    for target in item.targets
                )
                for item in class_node.body
            )
        ]
        if not generated_classes:
            diagnostics.append(
                _diag(
                    "BT_GENERATED_MARKER_MISSING",
                    "error",
                    path,
                    tree,
                    "generated-candidate-only",
                    "P0 execution only accepts product-generated candidates",
                    "Generate the candidate from a validated StrategySpec.",
                )
            )
    return _report(path, diagnostics, strategy_classes=strategy_classes)


def _report(
    path: Path, diagnostics: list[Diagnostic], *, strategy_classes: list[str]
) -> dict[str, Any]:
    errors = sum(item.severity == "error" for item in diagnostics)
    warnings = sum(item.severity == "warning" for item in diagnostics)
    candidate_hash = file_hash(path)
    layers = {
        "specification": "not_applicable",
        "python_ast": "passed" if not errors else "failed",
        "fork_api": (
            "passed"
            if not any(
                item.code.startswith("BT_") and item.severity == "error" for item in diagnostics
            )
            else "failed"
        ),
        "security": (
            "passed"
            if not any(
                item.code.startswith("SEC_") and item.severity == "error" for item in diagnostics
            )
            else "failed"
        ),
        "import_collection": "pending",
        "smoke": "pending",
        "runonce_runnext": "pending",
        "target_test": "pending",
        "baseline": "pending",
        "artifact_integrity": "pending",
    }
    summary = {"errors": errors, "warnings": warnings, "passed": errors == 0}
    report = {
        "schema_version": "validation-report-v1",
        "validation_id": f"val_{candidate_hash[:24]}",
        "artifact_hash": candidate_hash,
        "dataset_id": None,
        "status": "passed" if errors == 0 else "failed",
        "diagnostics": [item.to_dict() for item in diagnostics],
        "evidence": {
            "candidate": {"file": path.name, "sha256": candidate_hash},
            "layers": layers,
            "strategy_classes": strategy_classes,
            "summary": summary,
        },
        "layers": layers,
        "summary": summary,
    }
    report["validation_hash"] = canonical_hash(report)
    return report
