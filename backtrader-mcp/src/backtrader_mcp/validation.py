"""Static validation without importing or executing candidate code."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

STRATEGY_IMPORTS = {"backtrader", "datetime", "math"}
HARNESS_IMPORTS = STRATEGY_IMPORTS | {"json", "os", "pathlib"}
BLOCKED_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "dir",
    "eval",
    "exec",
    "getattr",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
}
BLOCKED_ATTRIBUTES = {
    "chmod",
    "chown",
    "execv",
    "execve",
    "execl",
    "execlp",
    "execle",
    "execlpe",
    "execvp",
    "execvpe",
    "fork",
    "forkpty",
    "kill",
    "killpg",
    "popen",
    "read_bytes",
    "read_text",
    "remove",
    "rename",
    "replace",
    "rmdir",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "system",
    "unlink",
}
FILESYSTEM_ATTRIBUTES = {
    "absolute",
    "exists",
    "glob",
    "iterdir",
    "listdir",
    "lstat",
    "mkdir",
    "open",
    "read_bytes",
    "read_text",
    "resolve",
    "rglob",
    "stat",
    "touch",
    "walk",
    "write_bytes",
    "write_text",
}
SENSITIVE_ATTRIBUTE_SEGMENTS = {
    "_os",
    "os",
    "pathlib",
    "shutil",
    "socket",
    "subprocess",
    "sys",
}
RUNNER_ENVIRONMENT_KEYS = {
    "BACKTRADER_MCP_DATASET",
    "BACKTRADER_MCP_DATASETS_JSON",
    "BACKTRADER_MCP_FEEDS_JSON",
    "BACKTRADER_MCP_RESULT",
    "BACKTRADER_MCP_RUN_MODE",
}
LIVE_MARKERS = {
    "CCXTStore",
    "CTPStore",
    "IBStore",
    "OandaStore",
    "VCBroker",
    "getbroker",
    "setbroker",
}
FRAMEWORK_SELF_MEMBERS = {"p", "params", "lines", "data", "data0", "datas", "_owner"}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    path: str
    line: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "file": self.path,
            "line": self.line,
            "column": 0,
            "rule": self.code,
            "message": self.message,
            "suggestion": "",
        }


@dataclass
class _BindingScope:
    """Lexical capabilities visible while visiting one Python scope."""

    kind: str
    parent: _BindingScope | None = None
    facts: _ScopeFacts | None = None
    bound_names: set[str] = field(default_factory=set)
    module_aliases: dict[str, str] = field(default_factory=dict)
    safe_result_paths: set[str] = field(default_factory=set)
    environment_aliases: set[str] = field(default_factory=set)


@dataclass
class _ScopeFacts:
    """Whole-scope binding facts used for Python's late-bound closures."""

    kind: str
    parent: _ScopeFacts | None = None
    binding_counts: dict[str, int] = field(default_factory=dict)
    assigned_values: dict[str, list[ast.AST]] = field(default_factory=dict)
    imported_modules: dict[str, list[str]] = field(default_factory=dict)
    stable_module_aliases: dict[str, str] = field(default_factory=dict)
    stable_safe_result_paths: set[str] = field(default_factory=set)

    def bind(
        self,
        name: str,
        *,
        value: ast.AST | None = None,
        module: str | None = None,
    ) -> None:
        self.binding_counts[name] = self.binding_counts.get(name, 0) + 1
        if value is not None:
            self.assigned_values.setdefault(name, []).append(value)
        if module is not None:
            self.imported_modules.setdefault(name, []).append(module)


def _target_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [name for item in node.elts for name in _target_names(item)]
    return []


class _ScopeFactsBuilder(ast.NodeVisitor):
    """Collect binding counts without confusing nested lexical scopes."""

    def __init__(self, tree: ast.Module):
        module = _ScopeFacts("module")
        self.by_node: dict[int, _ScopeFacts] = {id(tree): module}
        self._stack = [module]

    @property
    def _scope(self) -> _ScopeFacts:
        return self._stack[-1]

    def _bind_target(self, target: ast.AST, value: ast.AST | None = None) -> None:
        names = _target_names(target)
        for name in names:
            self._scope.bind(
                name,
                value=value if isinstance(target, ast.Name) else None,
            )

    def _visit_function_signature(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    ) -> None:
        arguments = node.args
        for expression in [
            *arguments.defaults,
            *(default for default in arguments.kw_defaults if default is not None),
        ]:
            self.visit(expression)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                self.visit(decorator)
            if node.returns is not None:
                self.visit(node.returns)

    def _function_parent(self) -> _ScopeFacts:
        parent = self._scope
        while parent.kind == "class" and parent.parent is not None:
            parent = parent.parent
        return parent

    def _enter_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        facts = _ScopeFacts("function", parent=self._function_parent())
        self.by_node[id(node)] = facts
        self._stack.append(facts)
        arguments = node.args
        for argument in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]:
            facts.bind(argument.arg)
        if arguments.vararg is not None:
            facts.bind(arguments.vararg.arg)
        if arguments.kwarg is not None:
            facts.bind(arguments.kwarg.arg)
        body = (
            node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else [node.body]
        )
        for statement in body:
            self.visit(statement)
        self._stack.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            self._scope.bind(local_name, module=alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            imported = f"{module}.{alias.name}" if module else alias.name
            self._scope.bind(alias.asname or alias.name, module=imported)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._bind_target(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self._bind_target(node.target, node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind_target(node.target, node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        self._bind_target(node.target)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._bind_target(target)

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        self._bind_target(node.target)
        for statement in [*node.body, *node.orelse]:
            self.visit(statement)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._bind_target(item.optional_vars)
        for statement in node.body:
            self.visit(statement)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name is not None:
            self._scope.bind(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        for case in node.cases:
            for pattern in ast.walk(case.pattern):
                if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) and pattern.name:
                    self._scope.bind(pattern.name)
                elif isinstance(pattern, ast.MatchMapping) and pattern.rest:
                    self._scope.bind(pattern.rest)
            if case.guard is not None:
                self.visit(case.guard)
            for statement in case.body:
                self.visit(statement)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope.bind(node.name)
        self._visit_function_signature(node)
        self._enter_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope.bind(node.name)
        self._visit_function_signature(node)
        self._enter_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_function_signature(node)
        self._enter_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.bind(node.name)
        for expression in [*node.decorator_list, *node.bases]:
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)
        facts = _ScopeFacts("class", parent=self._scope)
        self.by_node[id(node)] = facts
        self._stack.append(facts)
        for statement in node.body:
            self.visit(statement)
        self._stack.pop()


def _stable_module_alias(facts: _ScopeFacts, name: str) -> str | None:
    scope: _ScopeFacts | None = facts
    while scope is not None:
        if name in scope.binding_counts:
            return scope.stable_module_aliases.get(name)
        scope = scope.parent
    return None


def _stable_dotted_name(facts: _ScopeFacts, node: ast.AST) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        root = _stable_module_alias(facts, current.id) or current.id
        return ".".join([root, *reversed(parts)])
    return ""


def _is_stable_result_path_constructor(facts: _ScopeFacts, node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or len(node.args) != 1 or node.keywords:
        return False
    if _stable_dotted_name(facts, node.func) != "pathlib.Path":
        return False
    value = node.args[0]
    return (
        isinstance(value, ast.Subscript)
        and _stable_dotted_name(facts, value.value) == "os.environ"
        and isinstance(value.slice, ast.Constant)
        and value.slice.value == "BACKTRADER_MCP_RESULT"
    )


def _build_scope_facts(tree: ast.Module) -> dict[int, _ScopeFacts]:
    builder = _ScopeFactsBuilder(tree)
    builder.visit(tree)
    facts_values = list(builder.by_node.values())
    for facts in facts_values:
        for name, modules in facts.imported_modules.items():
            if facts.binding_counts.get(name) == 1 and len(modules) == 1:
                facts.stable_module_aliases[name] = modules[0]
    for facts in facts_values:
        for name, values in facts.assigned_values.items():
            if (
                facts.binding_counts.get(name) == 1
                and len(values) == 1
                and _is_stable_result_path_constructor(facts, values[0])
            ):
                facts.stable_safe_result_paths.add(name)
    return builder.by_node


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_super_init(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "__init__"
        and isinstance(call.func.value, ast.Call)
        and isinstance(call.func.value.func, ast.Name)
        and call.func.value.func.id == "super"
    )


class StaticValidator(ast.NodeVisitor):
    def __init__(self, path: str, tree: ast.Module):
        self.path = path
        self.findings: list[Finding] = []
        self.classifications: list[dict[str, str]] = []
        filename = PurePosixPath(path).name
        self.harness = filename == "run.py" or filename.startswith("test_")
        self._facts_by_node = _build_scope_facts(tree)
        module_scope = _BindingScope("module", facts=self._facts_by_node[id(tree)])
        self._scope_stack = [module_scope]
        self.allowed_environment_nodes: set[int] = set()
        self.direct_write_attributes = {
            id(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "write_text"
        }

    @property
    def _scope(self) -> _BindingScope:
        return self._scope_stack[-1]

    def _push_scope(self, kind: str, node: ast.AST) -> None:
        parent = self._scope
        if kind in {"function", "comprehension"}:
            # A function/comprehension defined in a class does not close over the
            # class namespace. Skip class scopes so aliases resolve like Python.
            while parent.kind == "class" and parent.parent is not None:
                parent = parent.parent
        self._scope_stack.append(
            _BindingScope(kind, parent=parent, facts=self._facts_by_node.get(id(node)))
        )

    def _pop_scope(self) -> None:
        self._scope_stack.pop()

    def _lookup_binding(self, name: str, capability: str) -> str | bool | None:
        scope: _BindingScope | None = self._scope
        current_scope = True
        while scope is not None:
            if current_scope and name in scope.bound_names:
                values = getattr(scope, capability)
                if isinstance(values, dict):
                    return values.get(name)
                return name in values
            facts = scope.facts
            if facts is not None and name in facts.binding_counts:
                if current_scope:
                    # A later local binding shadows outer scopes, but it is not a
                    # capability before that binding executes.
                    return None
                if capability == "module_aliases":
                    return facts.stable_module_aliases.get(name)
                if capability == "safe_result_paths":
                    return name in facts.stable_safe_result_paths
                return False
            scope = scope.parent
            current_scope = False
        return None

    def _module_alias(self, name: str) -> str | None:
        value = self._lookup_binding(name, "module_aliases")
        return value if isinstance(value, str) else None

    def _is_safe_result_path_name(self, name: str) -> bool:
        return self._lookup_binding(name, "safe_result_paths") is True

    def _is_environment_alias_name(self, name: str) -> bool:
        return self._lookup_binding(name, "environment_aliases") is True

    def _invalidate_binding(self, name: str) -> None:
        """Forget capabilities when any Python binding is overwritten or deleted."""

        self._scope.bound_names.add(name)
        self._scope.safe_result_paths.discard(name)
        self._scope.environment_aliases.discard(name)
        self._scope.module_aliases.pop(name, None)

    def _bind_module_alias(self, name: str, module: str) -> None:
        self._invalidate_binding(name)
        self._scope.module_aliases[name] = module

    def _bind_safe_result_path(self, name: str) -> None:
        self._invalidate_binding(name)
        if self._scope.facts is not None and name in self._scope.facts.stable_safe_result_paths:
            self._scope.safe_result_paths.add(name)

    def _bind_environment_alias(self, name: str) -> None:
        self._invalidate_binding(name)
        self._scope.environment_aliases.add(name)

    def add(self, code: str, message: str, node: ast.AST, severity: str = "error") -> None:
        self.findings.append(
            Finding(code, severity, message, self.path, getattr(node, "lineno", 1))
        )

    def visit_Import(self, node: ast.Import) -> None:
        allowed = HARNESS_IMPORTS if self.harness else STRATEGY_IMPORTS
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            self._invalidate_binding(local_name)
            if alias.name not in allowed:
                self.add("blocked_import", f"import {alias.name} is not allowlisted", node)
                continue
            self._bind_module_alias(local_name, alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            self._invalidate_binding(alias.asname or alias.name)
        if node.level:
            self.add("blocked_import", "relative imports are not allowed", node)
            return
        if self.harness and module == "pathlib":
            if any(alias.name != "Path" for alias in node.names):
                self.add("blocked_import", "only pathlib.Path is allowlisted", node)
            else:
                for alias in node.names:
                    self._bind_module_alias(alias.asname or alias.name, "pathlib.Path")
            return
        local_strategy = self.harness and (
            module == "strategy"
            or (module.startswith("strategy_") and module.replace("_", "").isalnum())
        )
        if local_strategy:
            if any(
                not alias.name[:1].isupper()
                or alias.name.startswith("_")
                or alias.name in {"Subprocess", "Socket", "Path", "OS"}
                for alias in node.names
            ):
                self.add(
                    "blocked_import",
                    "runner may import only a public strategy class from its local module",
                    node,
                )
            return
        if module == "backtrader":
            allowed_members = {
                "Analyzer",
                "Indicator",
                "Observer",
                "Strategy",
                "analyzers",
                "feeds",
                "indicators",
            }
            if any(alias.name not in allowed_members for alias in node.names):
                self.add("blocked_import", "backtrader member is not allowlisted", node)
            return
        if self.harness and module == "backtrader_mcp.feed_runtime":
            if len(node.names) != 1 or node.names[0].name != "run_materialized_backtest":
                self.add(
                    "blocked_import",
                    "runner may import only run_materialized_backtest from the trusted feed runtime",
                    node,
                )
            return
        self.add("blocked_import", f"from {module} import ... is not allowlisted", node)

    def _dotted_name(self, node: ast.AST) -> str:
        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            root = self._module_alias(current.id) or current.id
            return ".".join([root, *reversed(parts)])
        return ""

    def _is_runner_environment_lookup(self, node: ast.AST, key: str) -> bool:
        if not isinstance(node, ast.Subscript):
            return False
        if self._dotted_name(node.value) != "os.environ":
            return False
        return isinstance(node.slice, ast.Constant) and node.slice.value == key

    def _is_environment_expression(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Name)
            and self._is_environment_alias_name(node.id)
            or self._dotted_name(node) in {"os.environ", "os.environb"}
        )

    def _is_safe_result_path_constructor(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call) or len(node.args) != 1 or node.keywords:
            return False
        if self._dotted_name(node.func) != "pathlib.Path":
            return False
        return self._is_runner_environment_lookup(node.args[0], "BACKTRADER_MCP_RESULT")

    def _is_direct_safe_result_write(self, node: ast.AST) -> bool:
        return (
            self.harness
            and isinstance(node, ast.Attribute)
            and id(node) in self.direct_write_attributes
            and node.attr == "write_text"
            and isinstance(node.value, ast.Name)
            and self._is_safe_result_path_name(node.value.id)
        )

    def visit_Assign(self, node: ast.Assign) -> None:
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        safe_constructor = self.harness and self._is_safe_result_path_constructor(node.value)
        environment_alias = self._is_environment_expression(node.value)
        if environment_alias:
            self.add(
                "blocked_environment",
                "runner environment cannot be aliased or passed as a value",
                node,
            )
        self.generic_visit(node)
        if safe_constructor:
            for name in names:
                self._bind_safe_result_path(name)
        if environment_alias:
            for name in names:
                self._bind_environment_alias(name)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        name = node.target.id if isinstance(node.target, ast.Name) else None
        safe_constructor = (
            self.harness
            and node.value is not None
            and self._is_safe_result_path_constructor(node.value)
        )
        environment_alias = node.value is not None and self._is_environment_expression(node.value)
        if environment_alias:
            self.add(
                "blocked_environment",
                "runner environment cannot be aliased or passed as a value",
                node,
            )
        self.generic_visit(node)
        if safe_constructor and name is not None:
            self._bind_safe_result_path(name)
        if environment_alias and name is not None:
            self._bind_environment_alias(name)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        name = node.target.id if isinstance(node.target, ast.Name) else None
        safe_constructor = self.harness and self._is_safe_result_path_constructor(node.value)
        environment_alias = self._is_environment_expression(node.value)
        if environment_alias:
            self.add(
                "blocked_environment",
                "runner environment cannot be aliased or passed as a value",
                node,
            )
        self.generic_visit(node)
        if safe_constructor and name is not None:
            self._bind_safe_result_path(name)
        if environment_alias and name is not None:
            self._bind_environment_alias(name)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and self._is_environment_alias_name(node.target.id):
            self.add("blocked_environment", "runner environment is read-only", node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_environment_expression(node.value):
            self.allowed_environment_nodes.add(id(node.value))
            if not isinstance(node.ctx, ast.Load):
                self.add("blocked_environment", "runner environment is read-only", node)
            key = node.slice.value if isinstance(node.slice, ast.Constant) else None
            if key not in RUNNER_ENVIRONMENT_KEYS:
                self.add(
                    "blocked_environment",
                    "runner may read only its fixed BACKTRADER_MCP environment keys",
                    node,
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        path_callable = self._dotted_name(node.func)
        if path_callable == "pathlib.Path" and not self._is_safe_result_path_constructor(node):
            self.add(
                "blocked_path",
                "Path() is restricted to the fixed result path supplied by the worker",
                node,
            )
        elif path_callable.startswith("pathlib.Path."):
            self.add(
                "blocked_path",
                "Path factories and class methods are outside the fixed result-path capability",
                node,
            )
        if isinstance(node.func, ast.Attribute):
            dotted = self._dotted_name(node.func)
            if self._is_environment_expression(node.func.value):
                self.add(
                    "blocked_environment",
                    "runner environment supports fixed-key subscript reads only",
                    node,
                )
            elif dotted.startswith("os."):
                self.add("blocked_call", f"{dotted}() is not allowlisted", node)
            elif node.func.attr in BLOCKED_ATTRIBUTES:
                self.add("blocked_call", f".{node.func.attr}() is not allowed", node)
            if node.func.attr in FILESYSTEM_ATTRIBUTES:
                if not self._is_direct_safe_result_write(node.func):
                    self.add(
                        "blocked_filesystem",
                        f".{node.func.attr}() is outside the generated-runner capability",
                        node,
                    )
            if node.func.attr in LIVE_MARKERS:
                self.add("live_trading", "live broker/store operations are outside P0", node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in FILESYSTEM_ATTRIBUTES and not self._is_direct_safe_result_write(node):
            self.add(
                "blocked_filesystem",
                f".{node.attr} capability cannot be detached from a trusted object",
                node,
            )
        if node.attr in BLOCKED_ATTRIBUTES:
            self.add(
                "blocked_call",
                f".{node.attr} capability cannot be detached or invoked",
                node,
            )
        if (
            isinstance(node.value, ast.Name)
            and self._is_safe_result_path_name(node.value.id)
            and node.attr != "write_text"
        ):
            self.add(
                "blocked_filesystem",
                "the fixed result path cannot be transformed or inspected",
                node,
            )
        if self._is_environment_expression(node.value):
            self.add(
                "blocked_environment",
                "runner environment supports fixed-key subscript reads only",
                node,
            )
        if (
            self._dotted_name(node) in {"os.environ", "os.environb"}
            and id(node) not in self.allowed_environment_nodes
        ):
            self.add(
                "blocked_environment",
                "runner environment may be used only in a fixed-key subscript read",
                node,
            )
        if isinstance(node.ctx, (ast.Store, ast.Del)) and self._dotted_name(node).startswith("os."):
            self.add("blocked_environment", "runner environment is read-only", node)
        if node.attr.startswith("__"):
            self.add("blocked_attribute", "dunder attribute access is not allowed", node)
        if node.attr in SENSITIVE_ATTRIBUTE_SEGMENTS or node.attr.startswith("_os"):
            self.add(
                "blocked_attribute",
                "process, network, runtime, and filesystem module traversal is not allowed",
                node,
            )
        if node.attr in LIVE_MARKERS:
            self.add("live_trading", "live broker/store references are outside P0", node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._invalidate_binding(node.id)
        elif node.id in BLOCKED_CALLS:
            self.add(
                "blocked_call",
                f"{node.id} capability cannot be detached or invoked",
                node,
            )
        if node.id in {"__builtins__", "__loader__", "__spec__"}:
            self.add("blocked_name", "runtime internals are not available to candidates", node)

    def visit_arguments(self, node: ast.arguments) -> None:
        for argument in [*node.posonlyargs, *node.args, *node.kwonlyargs]:
            self._invalidate_binding(argument.arg)
        if node.vararg is not None:
            self._invalidate_binding(node.vararg.arg)
        if node.kwarg is not None:
            self._invalidate_binding(node.kwarg.arg)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._invalidate_binding(node.name)
        self._push_scope("function", node)
        self.generic_visit(node)
        self._pop_scope()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._invalidate_binding(node.name)
        self._push_scope("function", node)
        self.generic_visit(node)
        self._pop_scope()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._push_scope("function", node)
        self.generic_visit(node)
        self._pop_scope()

    def visit_Global(self, node: ast.Global) -> None:
        self.add(
            "blocked_scope",
            "global capability rebinding is not allowed in generated runners",
            node,
        )

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.add(
            "blocked_scope",
            "nonlocal capability rebinding is not allowed in generated runners",
            node,
        )

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self._invalidate_binding(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self._invalidate_binding(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._invalidate_binding(node.name)
        self.generic_visit(node)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self._invalidate_binding(node.rest)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if (
            isinstance(node.value, str)
            and len(node.value) > 1
            and node.value.startswith("/")
            and not node.value.startswith("//")
        ):
            self.add("absolute_path", "literal absolute paths are not allowed", node)
        if isinstance(node.value, str) and any(
            part == ".." for part in node.value.replace("\\", "/").split("/")
        ):
            self.add("path_traversal", "literal parent path traversal is not allowed", node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._invalidate_binding(node.name)
        bases = {_base_name(base) for base in node.bases}
        if "Strategy" in bases:
            category = "strategy"
        elif bases & {"Indicator", "IndicatorBase", "LineIterator", "Observer", "Analyzer"}:
            category = "cooperative_line_object"
        else:
            category = "ordinary"
        self.classifications.append({"class_name": node.name, "category": category})
        init = next(
            (
                child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name == "__init__"
            ),
            None,
        )
        if init is not None and category == "cooperative_line_object":
            super_lines = [
                child.lineno
                for child in ast.walk(init)
                if isinstance(child, ast.Call) and _is_super_init(child)
            ]
            member_lines = [
                child.lineno
                for child in ast.walk(init)
                if isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Name)
                and child.value.id == "self"
                and child.attr in FRAMEWORK_SELF_MEMBERS
            ]
            if not super_lines:
                self.add(
                    "missing_cooperative_super",
                    "Indicator/line object __init__ must call super().__init__()",
                    init,
                )
            elif member_lines and min(super_lines) > min(member_lines):
                self.add(
                    "late_cooperative_super",
                    "super().__init__() must precede framework member access",
                    init,
                )
        if init is not None and category == "strategy":
            for child in ast.walk(init):
                if isinstance(child, ast.Call) and _is_super_init(child):
                    self.add(
                        "strategy_super",
                        "direct Strategy initialization is engine-managed; verify mixin MRO before "
                        "calling super().__init__()",
                        child,
                        severity="warning",
                    )
        self._push_scope("class", node)
        self.generic_visit(node)
        self._pop_scope()


def validate_sources(files: dict[str, str]) -> dict[str, Any]:
    findings: list[Finding] = []
    classifications: list[dict[str, str]] = []
    for path, content in sorted(files.items()):
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(content, filename=path, mode="exec")
            compile(tree, path, "exec")
        except SyntaxError as exc:
            findings.append(
                Finding(
                    "syntax_error",
                    "error",
                    exc.msg,
                    path,
                    exc.lineno or 1,
                )
            )
            continue
        validator = StaticValidator(path, tree)
        validator.visit(tree)
        findings.extend(validator.findings)
        classifications.extend(
            {"path": path, **classification} for classification in validator.classifications
        )
    rendered = [finding.as_dict() for finding in findings]
    return {
        "status": "failed" if any(item["severity"] == "error" for item in rendered) else "passed",
        "diagnostics": rendered,
        "evidence": {
            "classifications": classifications,
            "checks": [
                "python_syntax",
                "dangerous_imports_and_calls",
                "live_trading_boundary",
                "literal_absolute_paths",
                "object_class_initialization",
            ],
        },
    }
