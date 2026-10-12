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


@pytest.mark.parametrize("example_id", ("013_1", "013_2"))
def test_live_entry_persists_front_selection_failure_details(example_id, tmp_path):
    if sys.version_info[:2] != (3, 11):
        pytest.skip("live entries require the reviewed Python 3.11 interpreter")

    directory = ENTRIES[example_id]
    entry = _load_entry(directory, f"entry_{example_id}")

    class SimNowDirectError(RuntimeError):
        def __init__(self, reason, details=None):
            super().__init__(reason)
            self.reason = str(reason)
            self.details = dict(details or {})

    fake = types.ModuleType("simnow_direct")
    fake.SimNowDirectError = SimNowDirectError

    def _reject(*args, **kwargs):
        raise SimNowDirectError("no_front_pair_eligible", DETAILS)

    fake.select_front_pair = _reject

    config, _config_path = entry._load_config()
    credentials = config.get("credentials") or {}
    env = {
        str(credentials[key]): "dummy"
        for key in (
            "broker_id_env",
            "user_id_env",
            "password_env",
            "app_id_env",
            "auth_code_env",
        )
    }

    entry._load_env = lambda: env
    entry._ensure_dev_sdk_path = lambda *, strict=False: None
    entry._resolve_live_contracts = lambda cfg: [("rb2701", "SHFE"), ("rb2705", "SHFE")]

    evidence_dir = tmp_path / "ev"
    args = SimpleNamespace(
        allow_write=True,
        run_seconds=None,
        evidence_dir=str(evidence_dir),
        drill=False,
    )

    saved_modules = {key: sys.modules.get(key) for key in ("simnow_direct", "legacy_runner")}
    sys.modules["simnow_direct"] = fake
    sys.path.insert(0, str(directory))
    try:
        rc = entry.run_live(args)
    finally:
        sys.path.remove(str(directory))
        for key, value in saved_modules.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value

    assert rc == 2  # EXIT_BLOCKED
    payload = json.loads((evidence_dir / "run.json").read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "no_front_pair_eligible"
    assert payload["details"]["samples"] == DETAILS["samples"]
    assert payload["details"]["rejected"][0]["reason"] == "no_whole_pair_connection"


@pytest.mark.parametrize("example_id", sorted(ENTRIES))
def test_every_live_entry_preserves_typed_front_failure_before_generic(example_id):
    tree = ast.parse((ENTRIES[example_id] / "run.py").read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "run_live" in functions, f"{example_id} has no run_live handler"
    function_names = ["run_live"]
    if "run_live_observe" in functions:
        function_names.append("run_live_observe")

    for function_name in function_names:
        assert _has_typed_front_handler(functions[function_name]), (
            f"{example_id}.{function_name} must handle SimNowDirectError before Exception "
            "and preserve its reason/details"
        )


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
