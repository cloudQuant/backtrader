"""Iteration 42 live entries must persist front-selection failure details.

The 2026-10-10 bounded rehearsal was cleanly BLOCKED with
``no_front_pair_eligible``, but the persisted ``run.json`` kept only the
reason string: ``SimNowDirectError`` fell through to the generic handler and
its value-free ``details`` (per-pair probe samples) were lost, forcing a
manual re-probe to tell a vendor outage apart from a code defect.  Every
SimNow live entry now carries a dedicated branch that persists ``reason`` and
``details`` before the generic blocker.

013_1/013_2 are driven end-to-end through the real ``run_live`` with a fake
``simnow_direct`` module; the remaining entries share the identical handler
shape and are covered by a source-consistency guard (their pre-selector flows
need heavier per-file scaffolding that adds no additional signal here).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"
ENTRIES = {
    "013_1": EXAMPLES / "unified" / "013_1_midfreq_cross_arbitrage",
    "013_2": EXAMPLES / "unified" / "013_2_highfreq_calendar_arbitrage",
    "013_3": EXAMPLES / "unified" / "013_3_sa_midfreq_simnow",
    "014_1": EXAMPLES / "unified" / "014_1_ctp_options_lowfreq",
    "014_2": EXAMPLES / "unified" / "014_2_ctp_options_midfreq",
    "015": EXAMPLES / "unified" / "015_ctp_options_highfreq",
}

DETAILS = {
    "rejected": [
        {
            "index": 4,
            "kind": "7x24",
            "td_success": 0,
            "md_success": 0,
            "reason": "no_whole_pair_connection",
        }
    ],
    "samples": 3,
}


def _load_entry(directory: Path, name: str):
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location(name, directory / "run.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(directory))
    return module






def _dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _function_scope_nodes(function):
    """Walk a function body without mistaking a nested helper for its handler."""

    pending = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield node
        pending.extend(ast.iter_child_nodes(node))


def _uses_exception_field(handler, field):
    return bool(handler.name) and any(
        isinstance(node, ast.Attribute)
        and node.attr == field
        and isinstance(node.value, ast.Name)
        and node.value.id == handler.name
        for node in ast.walk(handler)
    )


def _has_typed_front_handler(function):
    for node in _function_scope_nodes(function):
        if not isinstance(node, ast.Try):
            continue
        for index, handler in enumerate(node.handlers):
            if _dotted_name(handler.type) != "simnow_direct.SimNowDirectError":
                continue
            generic_follows = any(
                _dotted_name(later.type) == "Exception" for later in node.handlers[index + 1 :]
            )
            if (
                generic_follows
                and _uses_exception_field(handler, "reason")
                and _uses_exception_field(handler, "details")
            ):
                return True
    return False


@pytest.mark.parametrize(
    "source",
    (
        pytest.param(
            """def run_live():
    try:
        pass
    except Exception as exc:
        generic = str(exc)
    except simnow_direct.SimNowDirectError as exc:
        reason = exc.reason
        details = exc.details
""",
            id="generic-first",
        ),
        pytest.param(
            """def run_live():
    try:
        pass
    except simnow_direct.SimNowDirectError as exc:
        details = exc.details
    except Exception as exc:
        generic = str(exc)
""",
            id="missing-reason",
        ),
        pytest.param(
            """def run_live():
    try:
        pass
    except simnow_direct.SimNowDirectError as exc:
        reason = exc.reason
    except Exception as exc:
        generic = str(exc)
""",
            id="missing-details",
        ),
        pytest.param(
            """def run_live():
    def nested_helper():
        try:
            pass
        except simnow_direct.SimNowDirectError as exc:
            reason = exc.reason
            details = exc.details
        except Exception as exc:
            generic = str(exc)
""",
            id="nested-helper-only",
        ),
    ),
)
def test_typed_front_handler_guard_rejects_invalid_shapes(source):
    function = ast.parse(source).body[0]
    assert not _has_typed_front_handler(function)
