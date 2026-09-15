#!/usr/bin/env python
"""Iteration-29 phase-2 treatment: broad ``except Exception`` blocks whose
body has NO logger call (multi-statement fallback bodies skipped by phase 1).

Rules (informed by the phase-1 protocol-probe lesson):
- exempt files (own defensive code with nosec notes)  -> skip
- body contains a Raise                              -> logger.error(..., exc_info=True)
- core line-system / construction files              -> logger.debug(...)   (may be
  high-frequency probe fallbacks; debug avoids error.log flooding)
- everything else (external IO, feeds, brokers, ...)  -> logger.warning(...)

Insertion: at the top of the handler body at the first statement's
indentation, back-to-front by line number. Control flow untouched.

Usage: python treat_broad_excepts.py   (operates on the fixed file list below)
"""

import ast
import re
import sys

LOGGER_LEVELS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}

EXEMPT = {"backtrader/utils/log_message.py"}

CORE = {
    "backtrader/linebuffer.py",
    "backtrader/lineiterator.py",
    "backtrader/lineseries.py",
    "backtrader/lineroot.py",
    "backtrader/metabase.py",
    "backtrader/parameters.py",
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


def catches_broad(handler):
    if handler.type is None:
        return True
    def visit(node):
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            return [node.attr]
        if isinstance(node, ast.Tuple):
            out = []
            for e in node.elts:
                out += visit(e)
            return out
        return []
    return any(t in ("Exception", "BaseException") for t in visit(handler.type))


def type_names(handler):
    if handler.type is None:
        return "bare"
    def visit(node):
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            return [node.attr]
        if isinstance(node, ast.Tuple):
            out = []
            for e in node.elts:
                out += visit(e)
            return out
        return []
    return ",".join(visit(handler.type))


def treat(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    stem = re.sub(r"\.py$", "", path.split("/")[-1])

    inserts = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not catches_broad(node) or has_logger_call(node):
            continue
        body = node.body
        if not body:
            continue
        types = type_names(node)
        line = node.lineno
        first = body[0]
        ind = " " * first.col_offset
        has_raise = any(isinstance(s, ast.Raise) for s in body)
        if has_raise:
            text = f'{ind}logger.error("{stem}:{line} exception before re-raise ({types})", exc_info=True)'
        elif path in CORE:
            text = f'{ind}logger.debug("{stem}:{line} fallback on {types}")'
        else:
            text = f'{ind}logger.warning("{stem}:{line} fallback on {types}")'
        inserts.append((first.lineno, text))

    lines = src.split("\n")
    for line_no, text in sorted(inserts, reverse=True):
        lines.insert(line_no - 1, text)

    open(path, "w", encoding="utf-8").write("\n".join(lines))
    return len(inserts)


if __name__ == "__main__":
    total = 0
    for path in sys.argv[1:]:
        if path in EXEMPT:
            print(f"SKIP (exempt): {path}")
            continue
        n = treat(path)
        print(f"{path}: inserted {n}")
        total += n
    print(f"TOTAL inserted: {total}")
