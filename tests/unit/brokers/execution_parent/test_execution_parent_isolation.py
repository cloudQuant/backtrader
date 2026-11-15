"""The projection boundary has no order, network, account or credential path.

Source/AST checks, a clean-subprocess import, a socket guard and read-only fake
ports prove the module never reaches a direct order path, a provider client or
the SDK.  This is UNIT evidence for the module boundary only.
"""

import ast
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

import backtrader
import backtrader.brokers
from backtrader.brokers import _execution_parent_projection as module
from backtrader.brokers._execution_parent_projection import CODES

from ._support import Ports, child, fill, make_order, projection, status

WORKSPACE = Path(__file__).resolve().parents[4]
ALLOWED_IMPORTS = {
    "__future__",
    "hashlib",
    "json",
    "math",
    "re",
    "threading",
    "collections.abc",
    "dataclasses",
    "decimal",
    "types",
    "..order",
    "..position",
}
FORBIDDEN_CALLS = {
    "make_order",
    "cancel_order",
    "submit",
    "notify",
    "urlopen",
    "request",
    "open",
    "exec",
    "eval",
    "__import__",
}
FORBIDDEN_TEXT = (
    "password",
    "secret",
    "api_key",
    "private_key",
    "credential",
    "environ",
    "getenv",
)


def _source():
    return Path(module.__file__).read_text(encoding="utf-8")


def _call_name(node):
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_module_imports_only_framework_and_standard_library():
    tree = ast.parse(_source())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add("." * node.level + (node.module or ""))
    assert imports <= ALLOWED_IMPORTS, imports - ALLOWED_IMPORTS
    assert not [name for name in imports if "bt_api" in name]


def test_module_never_calls_an_order_or_network_writer():
    tree = ast.parse(_source())
    called = {_call_name(node) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert called & FORBIDDEN_CALLS == set(), called & FORBIDDEN_CALLS


def test_module_has_no_credential_or_environment_access():
    tree = ast.parse(_source())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]
    names = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name)]
    names += [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
    text = " ".join(literals + names).lower()
    found = [token for token in FORBIDDEN_TEXT if token in text]
    assert found == []


def test_module_does_not_introduce_a_metaclass():
    tree = ast.parse(_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            assert not any(keyword.arg == "metaclass" for keyword in node.keywords)


def test_clean_interpreter_import_loads_no_sdk_or_provider_module():
    script = (
        "import sys\n"
        "import backtrader.brokers._execution_parent_projection as m\n"
        "bad = sorted(name for name in sys.modules if name.startswith('bt_api'))\n"
        "assert not bad, bad\n"
        "assert m.SCHEMA == 'execution.parent_projection/v1'\n"
        "print('ISOLATED')\n"
    )
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(WORKSPACE))
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(WORKSPACE),
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "ISOLATED" in result.stdout


def test_projection_makes_no_network_call(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("the projection must not open a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    _order, binding = make_order()
    ports = Ports(
        {"req-1": binding},
        statuses={"req-1": status("ACCEPTED", children=(child("c1", "SENT"),))},
        fills={"req-1": (fill("f1", quantity="1"),)},
    )
    result = projection(ports).project("req-1")
    assert result.refused is False
    assert ports.write_calls == []


def test_projection_reads_only_through_declared_ports():
    _order, binding = make_order()
    ports = Ports({"req-1": binding}, statuses={"req-1": status("ACCEPTED")})
    projection(ports).project("req-1")
    assert ports.write_calls == []
    assert {name for name, _key in ports.reads} <= {
        "binding",
        "status",
        "fills",
        "cancel",
        "completion",
    }


def test_public_broker_surface_is_unchanged():
    assert hasattr(backtrader.brokers, "BackBroker")
    assert hasattr(backtrader.brokers, "BtApiBroker")
    assert not hasattr(backtrader.brokers, "ExecutionParentProjection")
    assert module.__name__.endswith("._execution_parent_projection")
    assert "ExecutionParentProjection" in module.__all__


def test_every_published_code_is_finite_text():
    assert CODES and all(isinstance(code, str) and code for code in CODES)
    assert all(code == code.strip() and len(code) <= 64 for code in CODES)


def test_emitted_reasons_are_always_in_the_finite_code_set():
    _order, binding = make_order()
    scenarios = [
        (status("ACCEPTED"), ()),
        (status("UNKNOWN"), ()),
        (status("REGISTERING", frozen=True), ()),
        (status("ACCEPTED", children=(child("c1", "UNKNOWN"),)), ()),
        (status("REJECTED"), ()),
    ]
    seen = set()
    for fact, fills in scenarios:
        ports = Ports({"req-1": binding}, statuses={"req-1": fact}, fills={"req-1": fills})
        result = projection(ports).project("req-1")
        if result.code is not None:
            seen.add(result.code)
        if result.parent_fact is not None and result.parent_fact.reason_code is not None:
            seen.add(result.parent_fact.reason_code)
        for notification in result.notifications:
            if notification.reason_code is not None:
                seen.add(notification.reason_code)
    assert seen <= CODES
    assert "EXECUTION_PARENT_UNKNOWN" in seen
    assert "EXECUTION_PARENT_FROZEN" in seen
    assert "EXECUTION_CHILD_UNKNOWN" in seen
    assert "EXECUTION_REMOTE_REJECTED" in seen


def test_framework_instance_is_created_without_touching_the_strategy():
    _order, binding = make_order()
    strategy = object()
    ports = Ports({"req-1": binding}, statuses={"req-1": status("ACCEPTED")})
    result = projection(ports).project("req-1")
    assert result.parent_fact.bt_ref == binding["bt_ref"]
    assert not hasattr(strategy, "orders")
    with pytest.raises(AttributeError):
        strategy.orders
