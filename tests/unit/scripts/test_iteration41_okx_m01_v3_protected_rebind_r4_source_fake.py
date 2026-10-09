"""Source-only reproduction for the Root caller's production module binder.

This test loads the pinned public module sources through the caller's own
``load_held`` function, binds the complete module closure, and uses only a
synthetic CU module plus an uncalled in-memory private Win32 API object.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[3]
CALLER = ROOT / ".codex-tmp" / "okx_m01_protected_rebind_r4_root_actual_candidate_20261009.py"
CALLER_SHA256 = "5efc4f8c02ed09c24cb319fdd2099e719b1772a3a4e0c162fa051edc9427c305"
CALLER_SIZE = 61618
MAP_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09/source-map.json"
)
MAP_SHA256 = "07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3"
MAP_SIZE = 2877
MAX_PUBLIC_BYTES = 2 * 1024 * 1024

SUPPORT_SOURCE_PINS = {
    "scripts/iteration41_okx_m01_v3_protected_rebind_r2.py": (
        28418,
        "0baa2191b8d5b99b42e7a13ddc217f0d90291db8279b20f74a3d92c676649810",
    ),
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": (
        33887,
        "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76",
    ),
}

PUBLIC_MODULES = (
    (
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/__init__.py",
        "_m01_readonly_monitor_v2",
        True,
    ),
    (
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/current_types.py",
        "_m01_readonly_monitor_v2.current_types",
        False,
    ),
    (
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py",
        "_m01_readonly_monitor_v2.worker",
        False,
    ),
    (
        "examples/000_live_certification/okx_penetration/_certification/__init__.py",
        "_certification",
        True,
    ),
    (
        "examples/000_live_certification/okx_penetration/_certification/m01_private_monitor_v2.py",
        "_certification.m01_private_monitor_v2",
        False,
    ),
    (
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py",
        "_m01_readonly_monitor_v2.job_supervisor",
        False,
    ),
    (
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/__init__.py",
        "_m01_readonly_monitor_v3",
        True,
    ),
    (
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py",
        "_m01_readonly_monitor_v3.current_reader",
        False,
    ),
    (
        "scripts/iteration41_okx_m01_v3_protected_rebind_r2.py",
        "_root_okx_m01_metadata_helper_r2",
        False,
    ),
    (
        "backtrader_runtime/certification_roundtrip_private.py",
        "_root_public_custody_private",
        False,
    ),
    (
        "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
        "_root_public_custody_cli",
        False,
    ),
)


def _read_bounded(path: Path, *, expected_size: int | None = None, expected_sha256: str | None = None):
    info = path.lstat()
    assert info.st_size > 0 and info.st_size <= MAX_PUBLIC_BYTES
    assert path.is_file()
    with path.open("rb") as stream:
        raw = stream.read(MAX_PUBLIC_BYTES + 1)
    assert len(raw) == info.st_size
    assert len(raw) <= MAX_PUBLIC_BYTES
    if expected_size is not None:
        assert len(raw) == expected_size
    if expected_sha256 is not None:
        assert hashlib.sha256(raw).hexdigest() == expected_sha256
    return raw


def _caller_module():
    raw = _read_bounded(CALLER, expected_size=CALLER_SIZE, expected_sha256=CALLER_SHA256)
    tree = ast.parse(raw.decode("utf-8", errors="strict"), filename=str(CALLER))
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ROOT_RESULT" for target in node.targets
        ):
            break
        body.append(node)
    else:
        raise AssertionError("caller execution tail boundary missing")
    namespace = {"__name__": "_m01_rebind_r4_test_caller", "__file__": str(CALLER)}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(CALLER), "exec"), namespace)
    return types.SimpleNamespace(**namespace)


def _module_names():
    names = {name for _, name, _ in PUBLIC_MODULES}
    names.update({"_root_okx_m01_metadata_helper_r2", "_root_public_custody_private", "_root_public_custody_cli"})
    names.update({name.rpartition(".")[0] for name in tuple(names) if "." in name})
    names.add("_root_public_custody_v2")
    return names


def _load_composition(gate, tmp_path):
    map_raw = _read_bounded(ROOT / MAP_RELATIVE, expected_size=MAP_SIZE, expected_sha256=MAP_SHA256)
    map_doc = gate._source_map_doc(map_raw)
    assert set(map_doc["source_pins"]) == set(gate.SOURCE_MAP_EXPECTED_PATHS)

    loaded = {}
    source_raws = {}
    for relative, name, is_package in PUBLIC_MODULES:
        if relative in map_doc["source_pins"]:
            digest = map_doc["source_pins"][relative]
            raw = _read_bounded(ROOT / relative, expected_sha256=digest)
        else:
            size, digest = SUPPORT_SOURCE_PINS[relative]
            raw = _read_bounded(ROOT / relative, expected_size=size, expected_sha256=digest)
        source_raws[relative] = raw
        path = ROOT / relative
        if is_package:
            loaded[name] = gate.load_held(raw, path, name, is_package=True)
        else:
            loaded[name] = gate.load_held(raw, path, name)
        parent_name, _, leaf = name.rpartition(".")
        if parent_name:
            setattr(loaded[parent_name], leaf, loaded[name])

    # The exact private helper source is loaded, but no private API method is
    # called. This in-memory instance stands in for the CU-provided API object.
    private = loaded["_root_public_custody_private"]
    private._API = object.__new__(private._Win32)

    # The CU module is deliberately synthetic and lives only in pytest's temp
    # directory. It carries no source reads, handles, imports, or OS operations.
    fake_cu_path = tmp_path / "synthetic_cu.py"
    fake_cu_raw = b"def held_public_sources(*_args):\n    return None\n"
    fake_cu_path.write_bytes(fake_cu_raw)
    cu = gate.load_held(fake_cu_raw, fake_cu_path, "_root_public_custody_v2")

    source_path_by_module = {
        name: ROOT / relative for relative, name, _ in PUBLIC_MODULES
    }
    source_path_by_module["_root_public_custody_v2"] = fake_cu_path
    raw_by_module = {
        name: source_raws[relative] for relative, name, _ in PUBLIC_MODULES
    }
    raw_by_module["_root_public_custody_v2"] = fake_cu_raw
    loaded["_root_public_custody_v2"] = cu
    return loaded, raw_by_module, source_path_by_module


@pytest.fixture
def production_loaded_composition(tmp_path):
    names = _module_names()
    previous = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules.pop(name, None)
    try:
        gate = _caller_module()
        loaded, raw_by_module, paths = _load_composition(gate, tmp_path)
        yield gate, loaded, raw_by_module, paths
    finally:
        for name in names:
            sys.modules.pop(name, None)
        for name, value in previous.items():
            if value is not None:
                sys.modules[name] = value


def test_exact_production_binder_accepts_full_public_module_closure(production_loaded_composition):
    gate, loaded, raw_by_module, paths = production_loaded_composition
    order = (
        "_root_public_custody_v2",
        "_m01_readonly_monitor_v2",
        "_m01_readonly_monitor_v2.current_types",
        "_m01_readonly_monitor_v2.worker",
        "_certification",
        "_certification.m01_private_monitor_v2",
        "_m01_readonly_monitor_v2.job_supervisor",
        "_m01_readonly_monitor_v3",
        "_m01_readonly_monitor_v3.current_reader",
        "_root_okx_m01_metadata_helper_r2",
        "_root_public_custody_private",
        "_root_public_custody_cli",
    )
    records = []
    for name in order:
        expected_name = name
        records.append(
            gate.bind_module(
                loaded[name],
                raw_by_module[name],
                paths[name],
                expected_name,
            )
        )
    for record in records:
        gate.verify_binding(record)
    gate._verify_private_api(loaded["_root_public_custody_private"])

    worker = loaded["_m01_readonly_monitor_v2.worker"]
    wrapped_repr = worker.SocketCloseObservation.__repr__
    assert type(wrapped_repr) is types.FunctionType
    assert type(wrapped_repr.__wrapped__) is types.FunctionType
    assert wrapped_repr.__wrapped__.__qualname__ == "__create_fn__.<locals>.__repr__"


def test_generated_repr_code_is_bound_to_dataclass_fields_and_wrapper(
    production_loaded_composition,
):
    gate, loaded, raw_by_module, paths = production_loaded_composition
    worker = loaded["_m01_readonly_monitor_v2.worker"]

    # The forged code has the same module globals and the same generated-style
    # qualname/filename, but it is neither dataclasses' field-derived repr nor
    # the exact recursive_repr wrapper. It must fail closed.
    namespace = {}
    exec(
        compile("def fake(self):\n    return 'forged'\n", "<string>", "exec"),
        worker.__dict__,
        namespace,
    )
    forged = namespace["fake"]
    forged.__module__ = worker.__name__
    forged.__qualname__ = "__create_fn__.<locals>.__repr__"
    worker.SocketCloseObservation.__repr__ = forged

    with pytest.raises(gate.RootCallError) as caught:
        gate.bind_module(
            worker,
            raw_by_module["_m01_readonly_monitor_v2.worker"],
            paths["_m01_readonly_monitor_v2.worker"],
            "_m01_readonly_monitor_v2.worker",
        )
    assert caught.value.code == "root_source_binding_failed"
