"""Import-free AST and artifact validation for candidate strategies."""

import ast
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from .canonical import canonical_json_bytes, hash_object, sha256_bytes
from .errors import AgentError
from .scaffold import load_product_artifact_record
from .sessions import SessionStore
from .tokens import TokenAuthority

ALLOWED_IMPORT_ALIASES = {
    "backtrader": {None, "bt"},
    "json": {None},
    "math": {None},
    "os": {None},
    "csv": {None},
    "datetime": {None},
    "pandas": {None, "pd"},
}
ALLOWED_FROM_IMPORTS = {
    "backtrader": {"Cerebro", "Indicator", "Order", "Strategy", "TimeFrame"},
    "datetime": {"date", "datetime", "time", "timedelta", "timezone"},
}
LOCAL_STRATEGY_RE = re.compile(r"^strategy_[a-z][a-z0-9_]{1,63}$")
ALLOWED_LOCAL_IMPORTS = {"GeneratedStrategy"}
DENIED_DYNAMIC_CALLS = {"exec", "eval", "compile", "__import__"}
DENIED_FILESYSTEM_CALLS = {"open"}
DENIED_REFLECTION_CALLS = {
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
}
SAFE_ENVIRONMENT_KEYS = {
    "BACKTRADER_AGENT_DATASETS_JSON",
    "BACKTRADER_AGENT_MODE",
}
ALLOWED_BACKTRADER_TOP_LEVEL = {
    "Cerebro",
    "Indicator",
    "Order",
    "Strategy",
    "TimeFrame",
    "analyzers",
    "date2num",
    "feeds",
    "ind",
    "indicators",
    "num2date",
}
ALLOWED_BACKTRADER_FEEDS = {
    "BacktraderCSVData",
    "GenericCSVData",
    "PandasData",
    "YahooFinanceCSVData",
}
ALLOWED_BACKTRADER_ANALYZERS = {
    "AnnualReturn",
    "DrawDown",
    "PeriodStats",
    "Returns",
    "SQN",
    "SharpeRatio",
    "TimeDrawDown",
    "TradeAnalyzer",
    "Transactions",
    "VWR",
}
ALLOWED_PANDAS_CAPABILITIES = {"read_csv"}
LIVE_MARKERS = {
    "CCXTStore",
    "IBStore",
    "OandaStore",
    "VCStore",
    "MetaQuotesStore",
    "LiveBroker",
}
ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/])")


def _diagnostic(
    code: str,
    message: str,
    filename: str,
    node: Optional[ast.AST] = None,
    *,
    hint: Optional[str] = None,
) -> Dict[str, Any]:
    value: Dict[str, Any] = {
        "code": code,
        "severity": "error",
        "message": message,
        "path": PurePosixPath(filename).as_posix(),
    }
    if node is not None:
        value["line"] = int(getattr(node, "lineno", 1))
        value["column"] = int(getattr(node, "col_offset", 0))
    if hint:
        value["hint"] = hint
    return value


def _attribute_path(node: ast.AST) -> Optional[Tuple[str, ...]]:
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    return tuple([current.id] + list(reversed(parts)))


def _constant_string(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _backtrader_path_allowed(path: Tuple[str, ...]) -> bool:
    if len(path) < 2 or path[1] not in ALLOWED_BACKTRADER_TOP_LEVEL:
        return False
    if path[1] in {"ind", "indicators"}:
        if len(path) == 2:
            return True
        return len(path) <= 3 and all(not part.startswith("_") for part in path[2:])
    if path[1] == "feeds":
        if len(path) == 2:
            return True
        return len(path) == 3 and path[2] in ALLOWED_BACKTRADER_FEEDS
    if path[1] == "analyzers":
        if len(path) == 2:
            return True
        return len(path) == 3 and path[2] in ALLOWED_BACKTRADER_ANALYZERS
    return len(path) == 2


def _is_direct_strategy_base(base: ast.expr) -> bool:
    if isinstance(base, ast.Name):
        return base.id in {"Strategy", "GeneratedStrategy"}
    if isinstance(base, ast.Attribute) and base.attr == "Strategy":
        return isinstance(base.value, ast.Name) and base.value.id in {"bt", "backtrader"}
    return False


def _calls_super_init(function: ast.FunctionDef) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "__init__":
            continue
        owner = node.func.value
        if isinstance(owner, ast.Call) and isinstance(owner.func, ast.Name):
            if owner.func.id == "super":
                return True
    return False


class StrategyValidator:
    """Validates source bytes without importing or executing candidate code."""

    def __init__(self, authority: Optional[TokenAuthority] = None) -> None:
        self.authority = authority

    def validate_source(self, source: str, filename: str) -> List[Dict[str, Any]]:
        try:
            tree = ast.parse(source, filename=filename, mode="exec")
        except SyntaxError as exc:
            return [
                {
                    "code": "BTAG-AST-SYNTAX",
                    "severity": "error",
                    "message": "candidate contains invalid Python syntax",
                    "path": PurePosixPath(filename).as_posix(),
                    "line": int(exc.lineno or 1),
                    "column": int(exc.offset or 0),
                }
            ]
        diagnostics: List[Dict[str, Any]] = []
        parents = {
            child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
        }
        strategy_classes = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    aliases = ALLOWED_IMPORT_ALIASES.get(alias.name)
                    if aliases is None or alias.asname not in aliases:
                        diagnostics.append(
                            _diagnostic(
                                "BTAG-SEC-IMPORT",
                                "module import or alias is not capability-allowlisted",
                                filename,
                                node,
                            )
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported_names = {alias.name for alias in node.names}
                has_alias = any(alias.asname is not None for alias in node.names)
                if module == "os":
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-FROM-IMPORT",
                            "from-import from os is forbidden",
                            filename,
                            node,
                        )
                    )
                elif LOCAL_STRATEGY_RE.fullmatch(module):
                    if (
                        has_alias
                        or "*" in imported_names
                        or not imported_names.issubset(ALLOWED_LOCAL_IMPORTS)
                    ):
                        diagnostics.append(
                            _diagnostic(
                                "BTAG-SEC-LOCAL-IMPORT",
                                "local strategy import may expose only GeneratedStrategy",
                                filename,
                                node,
                            )
                        )
                elif (
                    module not in ALLOWED_FROM_IMPORTS
                    or has_alias
                    or "*" in imported_names
                    or not imported_names.issubset(ALLOWED_FROM_IMPORTS.get(module, set()))
                ):
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-IMPORT",
                            "from-import is not capability-allowlisted",
                            filename,
                            node,
                        )
                    )
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else None
                if name in DENIED_DYNAMIC_CALLS:
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-DYNAMIC",
                            "dynamic code execution is forbidden",
                            filename,
                            node,
                        )
                    )
                if name in DENIED_FILESYSTEM_CALLS:
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-FILESYSTEM",
                            "candidate filesystem access is forbidden",
                            filename,
                            node,
                        )
                    )
                if name in DENIED_REFLECTION_CALLS:
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-REFLECTION",
                            "reflective capability lookup is forbidden",
                            filename,
                            node,
                        )
                    )
                path = _attribute_path(node.func)
                if path == ("os", "environ", "get"):
                    key = _constant_string(node.args[0]) if node.args else None
                    if key not in SAFE_ENVIRONMENT_KEYS:
                        diagnostics.append(
                            _diagnostic(
                                "BTAG-SEC-ENVIRONMENT",
                                "environment key is not capability-allowlisted",
                                filename,
                                node,
                            )
                        )
                if isinstance(node.func, ast.Name) and node.func.id in LIVE_MARKERS:
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-LIVE",
                            "live broker or store APIs are forbidden",
                            filename,
                            node,
                        )
                    )
                if isinstance(node.func, ast.Attribute) and node.func.attr in LIVE_MARKERS:
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-LIVE",
                            "live broker or store APIs are forbidden",
                            filename,
                            node,
                        )
                    )
            elif isinstance(node, ast.Attribute):
                path = _attribute_path(node)
                if node.attr.startswith("__"):
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-REFLECTION",
                            "dunder attribute access is forbidden",
                            filename,
                            node,
                        )
                    )
                if path and path[0] == "os":
                    if path == ("os", "environ"):
                        parent = parents.get(node)
                        if isinstance(parent, ast.Subscript):
                            key_node = parent.slice
                            if isinstance(key_node, ast.Index):
                                key_node = key_node.value
                            key = _constant_string(key_node)
                            if key not in SAFE_ENVIRONMENT_KEYS:
                                diagnostics.append(
                                    _diagnostic(
                                        "BTAG-SEC-ENVIRONMENT",
                                        "environment key is not capability-allowlisted",
                                        filename,
                                        parent,
                                    )
                                )
                        elif not (
                            isinstance(parent, ast.Attribute)
                            and parent.attr == "get"
                            and isinstance(parents.get(parent), ast.Call)
                        ):
                            diagnostics.append(
                                _diagnostic(
                                    "BTAG-SEC-ENVIRONMENT",
                                    "environment mapping cannot be transferred",
                                    filename,
                                    node,
                                )
                            )
                    elif path != ("os", "environ", "get"):
                        diagnostics.append(
                            _diagnostic(
                                "BTAG-SEC-CAPABILITY",
                                "os capability is not allowlisted",
                                filename,
                                node,
                            )
                        )
                if path and path[0] in {"pd", "pandas"}:
                    if len(path) != 2 or path[1] not in ALLOWED_PANDAS_CAPABILITIES:
                        diagnostics.append(
                            _diagnostic(
                                "BTAG-SEC-CAPABILITY",
                                "Pandas capability is not allowlisted",
                                filename,
                                node,
                            )
                        )
                if path and path[0] in {"bt", "backtrader"}:
                    if not _backtrader_path_allowed(path):
                        diagnostics.append(
                            _diagnostic(
                                "BTAG-SEC-CAPABILITY",
                                "Backtrader capability is not allowlisted",
                                filename,
                                node,
                            )
                        )
            elif isinstance(node, ast.Name):
                if node.id in DENIED_DYNAMIC_CALLS:
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-DYNAMIC",
                            "dynamic code capability cannot be transferred",
                            filename,
                            node,
                        )
                    )
                if node.id in DENIED_FILESYSTEM_CALLS:
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-FILESYSTEM",
                            "filesystem capability cannot be transferred",
                            filename,
                            node,
                        )
                    )
                if node.id in DENIED_REFLECTION_CALLS:
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-REFLECTION",
                            "reflective capability cannot be transferred",
                            filename,
                            node,
                        )
                    )
                if node.id == "__builtins__":
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-REFLECTION",
                            "builtins namespace access is forbidden",
                            filename,
                            node,
                        )
                    )
                if node.id == "os":
                    parent = parents.get(node)
                    if not (
                        isinstance(parent, ast.Attribute)
                        and parent.value is node
                        and parent.attr == "environ"
                    ):
                        diagnostics.append(
                            _diagnostic(
                                "BTAG-SEC-CAPABILITY",
                                "os module object cannot be transferred",
                                filename,
                                node,
                            )
                        )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if (
                    ABSOLUTE_PATH_RE.match(value)
                    or ".." in PurePosixPath(value.replace("\\", "/")).parts
                ):
                    diagnostics.append(
                        _diagnostic(
                            "BTAG-SEC-PATH",
                            "absolute or parent-traversing path literal is forbidden",
                            filename,
                            node,
                        )
                    )
            elif isinstance(node, ast.ClassDef):
                direct = any(_is_direct_strategy_base(base) for base in node.bases)
                if direct:
                    strategy_classes += 1
                init_method = next(
                    (
                        item
                        for item in node.body
                        if isinstance(item, ast.FunctionDef) and item.name == "__init__"
                    ),
                    None,
                )
                # Current dev intentionally initializes direct bt.Strategy subclasses
                # before their user __init__. Only cooperative custom parents need super.
                if init_method is not None and not direct:
                    looks_like_strategy = node.name.endswith("Strategy")
                    if looks_like_strategy and not _calls_super_init(init_method):
                        diagnostics.append(
                            _diagnostic(
                                "BTAG-VAL-COOPERATIVE-INIT",
                                "custom Strategy parent initialization must follow its MRO",
                                filename,
                                init_method,
                                hint="call super().__init__() when a custom parent or mixin owns initialization",
                            )
                        )
        if filename.startswith(("strategy_", "test_")):
            if strategy_classes == 0:
                diagnostics.append(
                    _diagnostic(
                        "BTAG-VAL-STRATEGY",
                        "candidate must define a direct bt.Strategy subclass",
                        filename,
                    )
                )
        diagnostics.sort(
            key=lambda item: (
                item["path"],
                item.get("line", 0),
                item.get("column", 0),
                item["code"],
            )
        )
        return diagnostics

    def validate_artifact(
        self,
        artifact: Dict[str, Any],
        *,
        bindings: Optional[Dict[str, str]] = None,
        approval: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        draft_path_raw = artifact.get("_draft_path")
        if not isinstance(draft_path_raw, str):
            raise AgentError("BTAG-ARTIFACT-DRAFT", "private draft location is missing")
        draft_path = Path(draft_path_raw).resolve(strict=True)
        portable = {
            key: value
            for key, value in artifact.items()
            if not key.startswith("_") and key != "artifact_hash"
        }
        public_artifact = {key: value for key, value in artifact.items() if not key.startswith("_")}
        if hash_object(portable) != artifact.get("artifact_hash"):
            raise AgentError("BTAG-ARTIFACT-HASH", "artifact manifest hash is invalid")
        product_record: Optional[Dict[str, Any]] = None
        if self.authority is not None:
            if not isinstance(session_id, str):
                raise AgentError(
                    "BTAG-PROVENANCE-SESSION",
                    "session ID is required for executable artifact validation",
                )
            product_record = load_product_artifact_record(
                self.authority.state_root,
                session_id,
                artifact["artifact_hash"],
                self.authority,
            )
            expected_draft = (
                self.authority.state_root / product_record["draft_relative_path"]
            ).resolve(strict=True)
            extension = artifact.get("extensions", {}).get("backtrader_agent", {})
            manifest_path = expected_draft / "artifact-manifest.json"
            session = SessionStore(self.authority.state_root).load(session_id)
            if (
                draft_path != expected_draft
                or not manifest_path.is_file()
                or manifest_path.is_symlink()
                or sha256_bytes(manifest_path.read_bytes()) != product_record["manifest_sha256"]
                or manifest_path.read_bytes() != canonical_json_bytes(public_artifact) + b"\n"
                or extension.get("generated_by") != "backtrader-agent"
                or extension.get("renderer_version") != "scaffold-v1"
                or extension.get("session_id") != session_id
                or extension.get("dataset_manifest_hash") != product_record["dataset_manifest_hash"]
                or product_record["spec_hash"] != artifact.get("spec_hash")
                or product_record["dataset_id"] != artifact.get("dataset_id")
                or session.get("state") != "DRAFT_READY"
                or session.get("artifacts", {}).get("artifact_hash")
                != artifact.get("artifact_hash")
                or session.get("artifacts", {}).get("approved_spec_hash")
                != artifact.get("spec_hash")
                or session.get("artifacts", {}).get("dataset_id") != artifact.get("dataset_id")
                or session.get("artifacts", {}).get("dataset_manifest_hash")
                != product_record["dataset_manifest_hash"]
            ):
                raise AgentError(
                    "BTAG-PROVENANCE-BINDING",
                    "artifact provenance does not match its product session and private draft",
                )
        diagnostics: List[Dict[str, Any]] = []
        total_size = 0
        for file_entry in artifact.get("files", []):
            relative = file_entry.get("path", "")
            candidate_path = draft_path / relative
            try:
                resolved = candidate_path.resolve(strict=True)
                resolved.relative_to(draft_path)
            except (OSError, ValueError) as exc:
                raise AgentError("BTAG-ARTIFACT-PATH", "artifact file escapes its draft") from exc
            if not resolved.is_file() or resolved.is_symlink():
                raise AgentError("BTAG-ARTIFACT-TYPE", "artifact member must be a regular file")
            data = resolved.read_bytes()
            total_size += len(data)
            if sha256_bytes(data) != file_entry.get("sha256"):
                raise AgentError("BTAG-ARTIFACT-FILE-HASH", "artifact member hash is invalid")
            if relative.endswith(".py"):
                try:
                    source = data.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise AgentError(
                        "BTAG-ARTIFACT-ENCODING", "Python candidate must be UTF-8"
                    ) from exc
                diagnostics.extend(self.validate_source(source, relative))
        if len(artifact.get("files", [])) > 8 or total_size > 512 * 1024:
            diagnostics.append(
                _diagnostic(
                    "BTAG-ARTIFACT-QUOTA",
                    "artifact exceeds file count or byte quota",
                    "artifact-manifest.json",
                )
            )
        status = "passed" if not diagnostics else "failed"
        report: Dict[str, Any] = {
            "schema_version": "validation-report-v1",
            "validation_id": f"validation-{artifact['artifact_hash'][:20]}",
            "artifact_hash": artifact["artifact_hash"],
            "dataset_id": artifact["dataset_id"],
            "evidence": {
                "manifest": "passed",
                "hashes": "passed",
                "ast": status,
                "security": status,
                "current_fork": status,
            },
            "diagnostics": diagnostics,
            "status": status,
        }
        report["validation_hash"] = hash_object(report)
        if status == "passed" and self.authority is not None:
            if bindings is None or approval is None or product_record is None:
                raise AgentError(
                    "BTAG-VALIDATION-TOKEN",
                    "bindings and validator approval are required to issue a token",
                )
            token_bindings = dict(bindings)
            expected_dataset_hash = product_record["dataset_manifest_hash"]
            if token_bindings.get("dataset_hash") != expected_dataset_hash:
                raise AgentError(
                    "BTAG-VALIDATION-DATASET",
                    "validation dataset binding does not match the rendered artifact",
                )
            token_bindings.update(
                {
                    "artifact_record_hash": product_record["record_hash"],
                    "dataset_id": product_record["dataset_id"],
                    "session_id": product_record["session_id"],
                    "spec_hash": product_record["spec_hash"],
                    "validation_hash": report["validation_hash"],
                }
            )
            report["validation_token"] = self.authority.issue(
                "validation",
                artifact["artifact_hash"],
                token_bindings,
                approval=approval,
            )
        return report
