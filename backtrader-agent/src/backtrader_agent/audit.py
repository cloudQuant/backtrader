"""Self-contained independence and distribution-asset audit."""

import ast
import json
from pathlib import Path
from typing import Any, Dict, List

from .canonical import sha256_bytes

SCHEMA_NAMES = {
    "strategy-spec-v1.schema.json",
    "dataset-manifest-v1.schema.json",
    "corpus-manifest-v1.schema.json",
    "artifact-manifest-v1.schema.json",
    "validation-report-v1.schema.json",
    "run-manifest-v1.schema.json",
    "run-result-v1.schema.json",
    "agent-session-manifest-v1.schema.json",
}
FORBIDDEN_IMPORT_PREFIXES = {
    "backtrader_mcp",
    "backtrader_skills",
    "fastmcp",
    "mcp",
}
FORBIDDEN_DYNAMIC_CALLS = {"exec", "eval", "compile", "__import__"}


class IndependenceAuditor:
    def __init__(self, product_root: Path) -> None:
        self.product_root = Path(product_root).resolve()

    def audit(self) -> Dict[str, Any]:
        diagnostics: List[Dict[str, str]] = []
        source_root = self.product_root / "src" / "backtrader_agent"
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(self.product_root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            except (OSError, SyntaxError):
                diagnostics.append(
                    {"code": "BTAG-AUDIT-SYNTAX", "path": relative, "message": "source unreadable"}
                )
                continue
            for node in ast.walk(tree):
                imported = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported = alias.name.split(".", 1)[0]
                        if imported in FORBIDDEN_IMPORT_PREFIXES:
                            diagnostics.append(
                                {
                                    "code": "BTAG-AUDIT-SIBLING-IMPORT",
                                    "path": relative,
                                    "message": "forbidden sibling import",
                                }
                            )
                elif isinstance(node, ast.ImportFrom):
                    imported = (node.module or "").split(".", 1)[0]
                    if imported in FORBIDDEN_IMPORT_PREFIXES:
                        diagnostics.append(
                            {
                                "code": "BTAG-AUDIT-SIBLING-IMPORT",
                                "path": relative,
                                "message": "forbidden sibling import",
                            }
                        )
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in FORBIDDEN_DYNAMIC_CALLS:
                        diagnostics.append(
                            {
                                "code": "BTAG-AUDIT-DYNAMIC",
                                "path": relative,
                                "message": "dynamic execution call",
                            }
                        )
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in {"read_text", "read_bytes", "open"}:
                        for argument in node.args:
                            if isinstance(argument, ast.Constant) and isinstance(
                                argument.value, str
                            ):
                                lowered = argument.value.lower()
                                if (
                                    ".agents/skills" in lowered
                                    or "backtrader-mcp" in lowered
                                    or "backtrader-skills" in lowered
                                ):
                                    diagnostics.append(
                                        {
                                            "code": "BTAG-AUDIT-SIBLING-READ",
                                            "path": relative,
                                            "message": "forbidden sibling path read",
                                        }
                                    )
        contracts = source_root / "resources" / "contracts"
        present = {path.name for path in contracts.glob("*.json")}
        missing = sorted(SCHEMA_NAMES - present)
        if missing:
            diagnostics.append(
                {
                    "code": "BTAG-AUDIT-SCHEMAS",
                    "path": "src/backtrader_agent/resources/contracts",
                    "message": "missing schemas: " + ", ".join(missing),
                }
            )
        policy = source_root / "resources" / "policies" / "comparison-profile-v1.json"
        if not policy.is_file():
            diagnostics.append(
                {
                    "code": "BTAG-AUDIT-POLICY",
                    "path": "src/backtrader_agent/resources/policies",
                    "message": "comparison profile is missing",
                }
            )
        distribution_manifest = source_root / "resources" / "distribution-manifest.json"
        if not distribution_manifest.is_file():
            diagnostics.append(
                {
                    "code": "BTAG-AUDIT-DISTRIBUTION",
                    "path": "src/backtrader_agent/resources/distribution-manifest.json",
                    "message": "package distribution manifest is missing",
                }
            )
        else:
            try:
                manifest = json.loads(distribution_manifest.read_text(encoding="utf-8"))
                declared = manifest["files"]
                actual_paths = {
                    path.relative_to(source_root).as_posix()
                    for path in source_root.rglob("*")
                    if path.is_file()
                    and "__pycache__" not in path.parts
                    and path != distribution_manifest
                    and path.suffix != ".pyc"
                }
                if set(declared) != actual_paths:
                    raise ValueError("file set differs")
                for relative, expected_hash in declared.items():
                    if sha256_bytes((source_root / relative).read_bytes()) != expected_hash:
                        raise ValueError("hash differs")
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                diagnostics.append(
                    {
                        "code": "BTAG-AUDIT-DISTRIBUTION",
                        "path": "src/backtrader_agent/resources/distribution-manifest.json",
                        "message": "package distribution manifest does not match payload",
                    }
                )
        return {
            "schema_version": "independence-audit-v1",
            "status": "passed" if not diagnostics else "failed",
            "product_root_hash": self._tree_hash(),
            "checks": {
                "forbidden_imports": (
                    "passed"
                    if not any(item["code"] == "BTAG-AUDIT-SIBLING-IMPORT" for item in diagnostics)
                    else "failed"
                ),
                "forbidden_reads": (
                    "passed"
                    if not any(item["code"] == "BTAG-AUDIT-SIBLING-READ" for item in diagnostics)
                    else "failed"
                ),
                "dynamic_execution": (
                    "passed"
                    if not any(item["code"] == "BTAG-AUDIT-DYNAMIC" for item in diagnostics)
                    else "failed"
                ),
                "packaged_contracts": (
                    "passed"
                    if not any(item["code"] == "BTAG-AUDIT-SCHEMAS" for item in diagnostics)
                    else "failed"
                ),
                "comparison_profile": (
                    "passed"
                    if not any(item["code"] == "BTAG-AUDIT-POLICY" for item in diagnostics)
                    else "failed"
                ),
                "distribution_manifest": (
                    "passed"
                    if not any(item["code"] == "BTAG-AUDIT-DISTRIBUTION" for item in diagnostics)
                    else "failed"
                ),
            },
            "diagnostics": diagnostics,
        }

    def _tree_hash(self) -> str:
        hashes = []
        for path in sorted((self.product_root / "src" / "backtrader_agent").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                hashes.append(
                    f"{path.relative_to(self.product_root).as_posix()}:{sha256_bytes(path.read_bytes())}"
                )
        return sha256_bytes("\n".join(hashes).encode("utf-8"))
