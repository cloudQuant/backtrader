#!/usr/bin/env python
"""Scan the backtrader package and emit logging-baseline catalogs (iteration 29 M0).

Produces three JSON catalogs under --out:

- excepts.json       every ``except`` block: location, caught types, disposition
                     (pass / continue / raise / logger-call / other), whether a
                     logger call exists inside the handler body
- logger-calls.json  ``logger.<level>(...)`` and known logging helper calls:
                     location, level
- prints.json        every ``print(...)`` call: location, exempt flag
                     (bokeh/plot visualization paths are exempt per FR29-08)

Usage:
    python scripts/scan_logging_baseline.py --out <dir>

The catalogs are regenerable at any time; they are the M0 frozen baseline for
except/logger/print treatment records (see docs/_internal/opts/requirements/
迭代29-日志体系完善/).
"""

import argparse
import ast
import json
import os
import sys
from datetime import datetime, timezone

PACKAGE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtrader"
)

LOGGER_LEVELS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}
THROTTLED_LEVELS = {"throttled_warning": "warning", "throttled_error": "error"}

# Visualization/interactive paths: prints here are console UX, not engine logs.
EXEMPT_PRINT_PREFIXES = ("bokeh", "plot")


def relpath(path):
    return os.path.relpath(path, os.path.dirname(PACKAGE_ROOT)).replace(os.sep, "/")


def caught_names(handler):
    if handler.type is None:
        return []
    names = []

    def visit(node):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                visit(elt)

    visit(handler.type)
    return names


def first_effective(node):
    """Yield statements of a body, descending into lone ``if``/``try`` wrappers."""
    for stmt in node:
        yield stmt
        if isinstance(stmt, (ast.If, ast.Try)):
            try:
                yield from first_effective(stmt.body)
            except AttributeError:
                pass


def logging_call_level(node):
    """Recognize only the logger and helper spellings used by this package.

    _safe_log requires a literal supported level. Arbitrary similarly named
    methods and dynamic levels are not evidence of a known logging call.
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute):
        if (
            isinstance(func.value, ast.Name)
            and func.value.id == "logger"
            and func.attr in LOGGER_LEVELS
        ):
            return func.attr
    elif isinstance(func, ast.Name):
        if func.id in THROTTLED_LEVELS:
            return THROTTLED_LEVELS[func.id]
        if func.id == "_safe_log" and node.args:
            level = node.args[0]
            if isinstance(level, ast.Constant) and isinstance(level.value, str):
                if level.value in LOGGER_LEVELS:
                    return level.value
    return None


def has_logger_call(body_nodes):
    return any(
        logging_call_level(sub) is not None
        for sub in ast.walk(ast.Module(body=body_nodes, type_ignores=[]))
    )


def classify_disposition(handler):
    """Classify the primary disposition of an except body (heuristic, AST-level)."""
    body = handler.body
    if has_logger_call(body):
        return "logged"
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            return "pass"
        if isinstance(stmt, ast.Continue):
            return "continue"
        if isinstance(stmt, ast.Raise):
            return "raise"
    if not body:
        return "empty"
    return "other"


def scan_file(path):
    excepts, logcalls, prints = [], [], []
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=path)
    rel = relpath(path)

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            excepts.append(
                {
                    "file": rel,
                    "line": node.lineno,
                    "types": caught_names(node),
                    "bare": node.type is None,
                    "disposition": classify_disposition(node),
                    "logged": has_logger_call(node.body),
                }
            )
        elif isinstance(node, ast.Call):
            func = node.func
            level = logging_call_level(node)
            if level is not None:
                logcalls.append({"file": rel, "line": node.lineno, "level": level})
            if isinstance(func, ast.Name) and func.id == "print":
                exempt = rel.startswith(EXEMPT_PRINT_PREFIXES) or rel.startswith(
                    tuple(f"backtrader/{p}" for p in EXEMPT_PRINT_PREFIXES)
                )
                prints.append({"file": rel, "line": node.lineno, "exempt": exempt})

    return excepts, logcalls, prints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="output directory for JSON catalogs")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    all_excepts, all_logcalls, all_prints = [], [], []
    files_scanned = 0

    for root, dirs, files in os.walk(PACKAGE_ROOT):
        dirs.sort()
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            try:
                excepts, logcalls, prints = scan_file(path)
            except SyntaxError as exc:
                print(f"SYNTAX ERROR in {path}: {exc}", file=sys.stderr)
                return 1
            all_excepts.extend(excepts)
            all_logcalls.extend(logcalls)
            all_prints.extend(prints)
            files_scanned += 1

    summary = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "package_root": PACKAGE_ROOT,
        "files_scanned": files_scanned,
        "except_total": len(all_excepts),
        "except_by_disposition": {},
        "logger_calls_total": len(all_logcalls),
        "logger_calls_by_level": {},
        "print_total": len(all_prints),
        "print_exempt": sum(1 for p in all_prints if p["exempt"]),
    }
    for item in all_excepts:
        summary["except_by_disposition"][item["disposition"]] = (
            summary["except_by_disposition"].get(item["disposition"], 0) + 1
        )
    for item in all_logcalls:
        summary["logger_calls_by_level"][item["level"]] = (
            summary["logger_calls_by_level"].get(item["level"], 0) + 1
        )

    for filename, data in (
        ("excepts.json", all_excepts),
        ("logger-calls.json", all_logcalls),
        ("prints.json", all_prints),
    ):
        with open(os.path.join(args.out, filename), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
