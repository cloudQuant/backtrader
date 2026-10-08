"""Narrow R5 snapshot and bridge contracts for the Optional16 entry R2."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "scripts/iteration41_optional16_r33_root_held_entry_r2.py"
BRIDGE_PATH = ROOT / "scripts/iteration41_optional16_r33_root_held_child_bridge_r2.py"


def _load_exact(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("sourcefake_module_spec_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ENTRY = _load_exact("iteration41_optional16_root_held_entry_r2_snapshot_test", ENTRY_PATH)
BRIDGE = _load_exact("iteration41_optional16_root_held_bridge_r2_snapshot_test", BRIDGE_PATH)
ENTRY.ROOT = ROOT
ENTRY.EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
BRIDGE.ROOT = ROOT


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _key(path: str | Path) -> str:
    return ENTRY._path_key(path)


def _assert_error(code: str, callback) -> None:
    with pytest.raises(ENTRY.RootHeldEntryError) as caught:
        callback()
    assert caught.value.args == (code,)


def _view():
    source_path, source_digest, _size, _role = ENTRY.PROFILER_STDLIB_OPAQUE_ROWS[0]
    source_key = _key(source_path)
    ordinary_path = r"C:\fixture\ordinary_public.py"
    ordinary_key = _key(ordinary_path)
    ordinary_raw = b"ordinary public source bytes\n"
    ordinary_digest = _sha(ordinary_raw)
    scope = types.SimpleNamespace(private=object(), cli=object())
    view = ENTRY.RootHeldWorkerSnapshot(
        scope,
        {ordinary_key: ordinary_digest},
        {},
        {source_key: source_digest},
        {ordinary_key: ordinary_raw},
        {source_key: source_digest},
        {},
        {},
    )
    return view, source_key, source_digest, ordinary_key, ordinary_digest, ordinary_raw


def test_r5_snapshot_accepts_exact_opaque_metadata_and_ordinary_held_bytes():
    view, source_key, source_digest, ordinary_key, ordinary_digest, ordinary_raw = _view()
    held = {ordinary_key: ordinary_raw}

    assert view.assert_held_or_bytes(source_key, source_digest, held) is True
    assert view.assert_held_or_bytes(ordinary_key, ordinary_digest, held) is True


def test_r5_snapshot_rejects_bad_or_missing_opaque_membership_and_mutated_source():
    view, source_key, source_digest, ordinary_key, ordinary_digest, ordinary_raw = _view()
    held = {ordinary_key: ordinary_raw}

    _assert_error(
        "worker_held_pin_missing",
        lambda: view.assert_held_or_bytes(source_key, "0" * 64, held),
    )
    missing = ENTRY.RootHeldWorkerSnapshot(
        types.SimpleNamespace(private=object(), cli=object()),
        dict(view.public_pins),
        {},
        dict(view.software_pins),
        dict(view.public_bytes),
        {},
        {},
        {},
    )
    _assert_error(
        "worker_software_proof_missing",
        lambda: missing.assert_held_or_bytes(source_key, source_digest, held),
    )
    _assert_error(
        "worker_software_proof_missing",
        lambda: view.assert_held_or_bytes(source_key, source_digest, {**held, source_key: object()}),
    )
    _assert_error(
        "worker_held_public_bytes_mismatch",
        lambda: view.assert_held_or_bytes(
            ordinary_key, ordinary_digest, {ordinary_key: b"mutated public source\n"}
        ),
    )


def test_bridge_transform_binds_only_the_exact_entry_source():
    entry_raw = ENTRY_PATH.read_bytes()
    assert _sha(entry_raw) == BRIDGE.ENTRY_SHA256
    transformed, receipt = BRIDGE.transform_entry_source(entry_raw)

    assert _sha(transformed) == receipt["transformed_sha256"]
    assert receipt["source_sha256"] == BRIDGE.ENTRY_SHA256
    assert receipt["schema"] == "iteration41.optional16.r33.root-held-entry-bridge-transform.r2"
    assert receipt == {
        "schema": "iteration41.optional16.r33.root-held-entry-bridge-transform.r2",
        "source_sha256": BRIDGE.ENTRY_SHA256,
        "transformed_sha256": _sha(transformed),
        "sourcefake_anchor_count": 1,
        "payload_binding_anchor_count": 1,
        "production_alias_method_count": 1,
    }
    compile(transformed, str(ENTRY_PATH), "exec", dont_inherit=True)


def test_pinned_r15_closure_transform_routes_each_pin_through_r5_snapshot_api():
    glue_path = ROOT / ENTRY.R2_GLUE_REL
    glue_raw = glue_path.read_bytes()
    assert _sha(glue_raw) == ENTRY.R2_GLUE_SHA256
    glue_tree = ast.parse(glue_raw.decode("utf-8", "strict"))
    mains = [node for node in glue_tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"]
    assert len(mains) == 1

    original_closures = []
    for node in ast.walk(mains[0]):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "all"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.GeneratorExp)
        ):
            continue
        generator = node.args[0]
        if not (
            len(generator.generators) == 1
            and isinstance(generator.generators[0].target, ast.Tuple)
            and len(generator.generators[0].target.elts) == 2
            and all(isinstance(item, ast.Name) for item in generator.generators[0].target.elts)
            and [item.id for item in generator.generators[0].target.elts if isinstance(item, ast.Name)] == ["p", "h"]
            and isinstance(generator.generators[0].iter, ast.Call)
            and isinstance(generator.generators[0].iter.func, ast.Attribute)
            and isinstance(generator.generators[0].iter.func.value, ast.Name)
            and generator.generators[0].iter.func.value.id == "inner_pins"
            and generator.generators[0].iter.func.attr == "items"
            and isinstance(generator.elt, ast.Compare)
            and isinstance(generator.elt.left, ast.Call)
            and isinstance(generator.elt.left.func, ast.Name)
            and generator.elt.left.func.id == "sha"
            and isinstance(generator.elt.left.args[0], ast.Call)
            and isinstance(generator.elt.left.args[0].func, ast.Name)
            and generator.elt.left.args[0].func.id == "_held_bytes"
            and len(generator.elt.left.args[0].args) == 2
            and all(isinstance(item, ast.Name) for item in generator.elt.left.args[0].args)
            and [item.id for item in generator.elt.left.args[0].args] == ["held", "p"]
            and len(generator.elt.ops) == 1
            and isinstance(generator.elt.ops[0], ast.Eq)
            and len(generator.elt.comparators) == 1
            and isinstance(generator.elt.comparators[0], ast.Name)
            and generator.elt.comparators[0].id == "h"
        ):
            continue
        original_closures.append(generator)
    assert len(original_closures) == 1

    entry_tree = ast.parse(ENTRY_PATH.read_text(encoding="utf-8"))
    transformer = [
        node for node in entry_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_transform_r2_profiler_consumer"
    ]
    assert len(transformer) == 1
    replacements = []
    for node in ast.walk(transformer[0]):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Attribute)
            and isinstance(node.targets[0].value, ast.Name)
            and node.targets[0].value.id == "closure_generator"
            and node.targets[0].attr == "elt"
        ):
            replacements.append(node)
    assert len(replacements) == 1
    expected_call = ast.parse(
        "ast.Call(func=ast.Attribute(value=ast.Name(id='ROOT_R27_INVOKE', ctx=ast.Load()), "
        "attr='_R5_WORKER_ASSERT_HELD', ctx=ast.Load()), "
        "args=[ast.Name(id='p', ctx=ast.Load()), ast.Name(id='h', ctx=ast.Load()), "
        "ast.Name(id='held', ctx=ast.Load())], keywords=[])"
    ).body[0].value
    assert ast.dump(replacements[0].value, include_attributes=False) == ast.dump(
        expected_call, include_attributes=False
    )

    view, source_key, source_digest, ordinary_key, ordinary_digest, ordinary_raw = _view()
    held = {ordinary_key: ordinary_raw}
    inner_pins = {ordinary_key: ordinary_digest, source_key: source_digest}
    assert all(view.assert_held_or_bytes(path, digest, held) for path, digest in inner_pins.items())
