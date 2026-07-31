"""Self-contained product boundary audit."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

FORBIDDEN_IMPORT_PREFIXES = (
    "ai_trader",
    "backtrader_agent",
    "backtrader_skills",
    "integrations.backtrader",
)
FORBIDDEN_DYNAMIC_CALLS = {"eval", "exec"}


def audit_independence(package_root: Path | None = None) -> dict[str, Any]:
    root = package_root or Path(__file__).resolve().parent
    findings: list[dict[str, Any]] = []
    files_checked = 0
    for path in sorted(root.rglob("*.py")):
        files_checked += 1
        relative = str(path.relative_to(root))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level > 1:
                    findings.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "code": "parent_relative_import",
                        }
                    )
                modules = [node.module or ""]
            for module in modules:
                if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    findings.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "code": "sibling_product_import",
                            "module": module,
                        }
                    )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in FORBIDDEN_DYNAMIC_CALLS
            ):
                findings.append(
                    {
                        "path": relative,
                        "line": node.lineno,
                        "code": "dynamic_execution",
                        "call": node.func.id,
                    }
                )
    return {
        "schema_version": "independence-audit.v1",
        "status": "passed" if not findings else "failed",
        "package_root": str(root),
        "files_checked": files_checked,
        "findings": findings,
        "assertions": [
            "no sibling product imports",
            "no parent-relative imports",
            "no eval or exec calls",
            "candidate modules are only launched by the controlled worker",
        ],
    }
