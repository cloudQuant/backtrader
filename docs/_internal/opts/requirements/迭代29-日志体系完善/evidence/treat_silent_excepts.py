#!/usr/bin/env python
"""One-shot treatment tool for iteration 29 M3: insert logging into silent
except blocks (pass/continue/raise without any logger call) listed by the M0
catalog. AST-located, back-to-front insertion, control flow untouched.

Rules (D29-05):
- raise            -> logger.error("<stem>:<line> re-raising <types>", exc_info=True)
- pass/continue    -> narrow probe types -> logger.debug(...)
                    -> anything else     -> logger.warning(...)

Usage: python treat_silent_excepts.py <file1> <file2> ...
"""

import ast
import re
import sys

LOGGER_LEVELS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}
NARROW = {
    "KeyError", "AttributeError", "IndexError", "TypeError", "ValueError",
    "UnicodeDecodeError", "OverflowError", "InvalidOperation", "StopIteration",
}


def has_logger_call(handler):
    for sub in ast.walk(ast.Module(body=handler.body, type_ignores=[])):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if (
                isinstance(sub.func.value, ast.Name)
                and sub.func.value.id == "logger"
                and sub.func.attr in LOGGER_LEVELS
            ):
                return True
    return False


def caught_names(handler):
    names = []
    def visit(node):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                visit(elt)
    if handler.type is not None:
        visit(handler.type)
    return names


def target_stmt(handler):
    """First pass/continue/raise statement of the handler body."""
    for stmt in handler.body:
        if isinstance(stmt, (ast.Pass, ast.Continue, ast.Raise)):
            return stmt
    return None


def treat(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    stem = re.sub(r"\.py$", "", path.split("/")[-1])

    inserts = []  # (lineno, col, line_text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if has_logger_call(node):
            continue
        stmt = target_stmt(node)
        if stmt is None or isinstance(stmt, ast.Pass) and not node.body:
            continue
        if not isinstance(stmt, (ast.Pass, ast.Continue, ast.Raise)):
            continue
        # body beyond the single target statement has real handling -> skip
        if len(node.body) > 1:
            continue
        types = ",".join(caught_names(node)) or "bare"
        ind = " " * stmt.col_offset
        line = stmt.lineno
        if isinstance(stmt, ast.Raise):
            text = f'{ind}logger.error("{stem}:{line} re-raising {types}", exc_info=True)'
        elif types.split(",")[0] in NARROW:
            text = f'{ind}logger.debug("{stem}:{line} ignored {types}")'
        else:
            text = f'{ind}logger.warning("{stem}:{line} suppressed {types}")'
        inserts.append((line, col if (col := stmt.col_offset) is not None else 0, text))

    lines = src.split("\n")
    for line_no, _col, text in sorted(inserts, reverse=True):
        lines.insert(line_no - 1, text)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{path}: inserted {len(inserts)} log lines")
    return len(inserts)


if __name__ == "__main__":
    total = sum(treat(p) for p in sys.argv[1:])
    print(f"TOTAL inserted: {total}")
