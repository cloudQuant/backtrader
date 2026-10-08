"""Additive owner-held entry for the frozen Optional16 R27/R28 source chain.

This entry is deliberately closed by default. It is a source-fake candidate;
the held bytes and map rows establish neither Windows isolation nor provider,
account, SDK, native, or Optional16 acceptance.

R2 adds one exact source transform to R15's worker closure check: ordinary
public rows still require their exact held bytes, while opaque rows are
accepted only through the sealed R5 snapshot's ``assert_held_or_bytes`` API.
Opaque artifacts remain hash/metadata-only and are never read by this entry.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import json
import ntpath
import os
from pathlib import Path
import sys
import threading
import time
import types
from types import MappingProxyType


ROOT = Path(r"D:\source_code\backtrader")
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
ROOT_ACTUAL_ENABLED = False
ROOT_ENTRY_SOURCE_SHA256: str | None = None
ENTRY_SCHEMA = "iteration41.optional16.r33.root-held-entry.r2"
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_ROWS = 8192
_HEX = frozenset("0123456789abcdef")
_WORKER_SEAL = object()
_SOURCEFAKE_TEST_TOKEN = object()
_RETAINED: list[tuple[object, ...]] = []

R27_INVOKE_REL = Path("scripts/iteration41_optional16_r33_root_held_invoke_r27.py")
R27_INVOKE_SHA256 = "ea0a4f9ec5978508b854fe457dd1cfc3c0e9c41b7b23b89ec461bfed4d798339"
R27_WHOLE_REL = Path("scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py")
R27_WHOLE_SHA256 = "bfdd7bc9530b9ded9722ec86c1c184f36de3fb6337fb6688cbe15fa0f77f2876"
R27_TEST_REL = Path("tests/unit/scripts/test_iteration41_optional16_r33_activation_r27_source_fake.py")
R27_TEST_SHA256 = "d1794b07e9f742dc7ee893bf31194ca16729542d6936a303bc05b1ed55f4039f"
R28_R5_REL = Path("scripts/iteration41_optional16_r33_root_held_invoke_r28_r5.py")
R28_R5_SHA256 = "710452c8358887faa152cd2c6d11333ccf8ecb18fbe64d511ce86eb8f112c99c"
R2_GLUE_REL = Path("scripts/iteration41_optional16_r33_root_held_glue_r15.py")
R2_GLUE_SHA256 = "f9c9a5332a9d2456db8179d7a7e63103269c16feb2712a2b039479d97fe2dd98"
R19_DRIVER_REL = Path("scripts/iteration41_optional16_r33_root_driver_r19.py")
R19_DRIVER_SHA256 = "d7cd9a173e44510e8e2df8fbf68ff5420e495b5a7dd82c589bd1cbef3351c890"
CUV2_SOURCE_PATH = Path(r"D:\temp\iteration41-root-public-custody-v2.py")
CUV2_SOURCE_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
R19_BINDING_HELPER_REL = Path("scripts/iteration41_optional16_r33_deadline_r19_binding.py")
R19_BINDING_HELPER_SHA256 = "1774b2776c9c03c0e10574fda4f58093f3c2947d902d78c2d41bac9d4c47ba58"
R18_BINDING_HELPER_REL = Path("scripts/iteration41_optional16_r33_deadline_r18_binding.py")
R18_BINDING_HELPER_SHA256 = "5977009ff0d6bfafb98f5e9eace3e49cd9e49a15c760237ff5cee4d0f9c2fb43"
R17_BINDING_HELPER_REL = Path("scripts/iteration41_optional16_r33_deadline_r17_binding.py")
R17_BINDING_HELPER_SHA256 = "f4526bd40433fb74fe0c3d360c863d07e5613924a9bba243611026c058b442bd"
R16_BINDING_HELPER_REL = Path("scripts/iteration41_optional16_r33_deadline_r15_root_binding_r1.py")
R16_BINDING_HELPER_SHA256 = "5b30bb4a1516fcc632362a8be9073b4dfbdaafe8476b8d73c5b300ca05433a75"
R25_PUBLIC_MAP_REL = Path(
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iter41-zmq-r6-map-r3-20261007/source/p/r25-public-path-pins.json"
)
R25_PUBLIC_MAP_SHA256 = "5264b763bac6aac5d70fcbaa4e7cea423544ce90cd367e5e34da55c1680b9899"
V3_REL = Path("scripts/iteration41_root_held_source_scope_v3.py")
V3_SHA256 = "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677"
V4_REL = Path("scripts/iteration41_root_held_source_scope_v4.py")
V4_SHA256 = "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830"
R2_PREDECESSOR_REL = Path("scripts/iteration41_optional16_r33_root_held_invoke_r28_r2.py")
R2_PREDECESSOR_SHA256 = "fea25e15d535e7cd47d0637e060d464cbc982e8cdedfc2a1b620d166118cb213"
PROFILER_CACHE_SNAPSHOT_INDEX_REL = Path(
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-optional16-public-profiler-cache-opaque-snapshot-r1-2026-10-08/index.json"
)
PROFILER_CACHE_SNAPSHOT_INDEX_SHA256 = "9916da11d480bfbaee1a5c741240abe186b3a0ec920e7ba75a2e3580e43aecf0"
PROFILER_CACHE_SNAPSHOT_SCHEMA = "iteration41.optional16.public-profiler-cache-opaque-snapshot.r1"
PROFILER_CACHE_SNAPSHOT_ROLE = "ROOT_SNAPSHOTTED_FIXED_STDLIB_CACHE_OPAQUE_BYTES"
PROFILER_CACHE_OPAQUE_ROWS = (
    (
        r"C:\anaconda3\Lib\__pycache__\cProfile.cpython-311.pyc",
        "9d9a26a0e0aefd28a28dcd09bf97fd66072f8d537d18431f609485e16fb206b3",
        9056,
        PROFILER_CACHE_SNAPSHOT_ROLE,
    ),
    (
        r"C:\anaconda3\Lib\__pycache__\profile.cpython-311.pyc",
        "97408337b11e2c3b44bfb68c6e1f5e84de2536d4185049fec7038ecefc22a346",
        23934,
        PROFILER_CACHE_SNAPSHOT_ROLE,
    ),
    (
        r"C:\anaconda3\Lib\__pycache__\pstats.cpython-311.pyc",
        "8e66b028e50b31e7fbc7de63fcfe77025304aeb63b84e085ce13db784dca77ad",
        41851,
        PROFILER_CACHE_SNAPSHOT_ROLE,
    ),
)
PROFILER_STDLIB_SNAPSHOT_INDEX_REL = Path(
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-optional16-public-profiler-stdlib-opaque-snapshot-r1-2026-10-08/index.json"
)
PROFILER_STDLIB_SNAPSHOT_INDEX_SHA256 = "b6c355a4f3b5befe33f9fe0cc5880dfcbde711879d546c876c9b48d2013b1dec"
PROFILER_STDLIB_SNAPSHOT_SCHEMA = "iteration41.optional16.profiler_stdlib_opaque_snapshot.v1"
PROFILER_STDLIB_SNAPSHOT_CLASSIFICATION = "ROOT_PRODUCED_PUBLIC_OPAQUE_BYTES_NOT_RUNTIME_ACCEPTANCE"
PROFILER_STDLIB_SNAPSHOT_ROLE = "HASH_SIZE_TRANSPORT_ONLY_NO_PARSE_IMPORT_EXECUTE"
PROFILER_STDLIB_OPAQUE_ROWS = (
    (
        r"C:\anaconda3\Lib\cProfile.py",
        "0a97cf92d0e3efd2e08c2f9b0f0fb8e52a2b26978550804d8e59435201f3fa84",
        6346,
        PROFILER_STDLIB_SNAPSHOT_ROLE,
    ),
    (
        r"C:\anaconda3\Lib\profile.py",
        "4d87bdc8b85bf0a9bdee3e9d975a8a1a0c7360cb264fb68c4c48a102e718e3a3",
        22883,
        PROFILER_STDLIB_SNAPSHOT_ROLE,
    ),
    (
        r"C:\anaconda3\Lib\pstats.py",
        "d62d1e6a626ebd92187419bfe075a76997cce26fe99dd4520786d4a82b6ff10c",
        29356,
        PROFILER_STDLIB_SNAPSHOT_ROLE,
    ),
)


class RootHeldEntryError(RuntimeError):
    """Closed error labels only; no path values or source bytes are attached."""


def _need(condition: object, code: str) -> None:
    if not condition:
        raise RootHeldEntryError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in _HEX for ch in value)


def _path_key(path: str | os.PathLike[str]) -> str:
    value = os.fspath(path)
    _need(type(value) is str and value and "\x00" not in value, "path_text_invalid")
    _need(ntpath.isabs(value), "path_absolute_required")
    return ntpath.normcase(ntpath.normpath(value))


def _metadata_opaque_descriptor(path, digest, size, role):
    """Match only a complete, fixed public-index descriptor."""
    key = _path_key(path)
    for descriptor_path, expected_digest, expected_size, expected_role in (
        *PROFILER_CACHE_OPAQUE_ROWS,
        *PROFILER_STDLIB_OPAQUE_ROWS,
    ):
        if key == _path_key(descriptor_path):
            _need(
                (digest, size, role) == (expected_digest, expected_size, expected_role),
                "profiler_opaque_descriptor_mismatch",
            )
            return True
    return False


def _metadata_opaque_row(path, digest):
    """Return the fixed descriptor for an exact path and digest, if present."""
    key = _path_key(path)
    for descriptor_path, expected_digest, size, role in (
        *PROFILER_CACHE_OPAQUE_ROWS,
        *PROFILER_STDLIB_OPAQUE_ROWS,
    ):
        if key == _path_key(descriptor_path):
            _need(digest == expected_digest, "profiler_opaque_digest_mismatch")
            _need(_metadata_opaque_descriptor(path, digest, size, role),
                  "profiler_opaque_descriptor_mismatch")
            return size, role
    return None


def _is_opaque_pin(path, digest, category, max_bytes=None):
    suffix = Path(os.fspath(path)).suffix.casefold()
    if suffix == ".py":
        if category != "software":
            return False
        descriptor = _metadata_opaque_row(path, digest)
        _need(descriptor is not None, "unindexed_opaque_python_source")
        _need(
            type(max_bytes) is int and max_bytes >= descriptor[0],
            "profiler_opaque_size_limit_invalid",
        )
        return True
    if suffix == ".pyc":
        descriptor = _metadata_opaque_row(path, digest)
        _need(descriptor is not None, "unindexed_opaque_python_cache")
        _need(
            type(max_bytes) is int and max_bytes >= descriptor[0],
            "profiler_opaque_size_limit_invalid",
        )
        return True
    if category == "software":
        return True
    return suffix in {".whl", ".dll", ".exe", ".pyd"}


def _bounded_repo_source(relative: Path, digest: str, maximum: int = MAX_SOURCE_BYTES) -> tuple[Path, bytes]:
    path = ROOT / relative
    _need(path.is_absolute() and path == ROOT / relative, "repo_source_path_invalid")
    try:
        resolved_root = ROOT.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        _need(resolved_path.is_relative_to(resolved_root), "repo_source_escaped_root")
        with path.open("rb") as stream:
            raw = stream.read(maximum + 1)
    except RootHeldEntryError:
        raise
    except BaseException:
        raise RootHeldEntryError("repo_source_unavailable") from None
    _need(type(raw) is bytes and len(raw) <= maximum, "repo_source_size_invalid")
    _need(_valid_sha(digest) and _sha(raw) == digest, "repo_source_pin_mismatch")
    return path, raw


def _row_limit(path: str | os.PathLike[str], *, software: bool = False) -> int:
    suffix = Path(os.fspath(path)).suffix.casefold()
    if suffix == ".whl":
        return 32 * 1024 * 1024
    if suffix == ".pyc":
        return 16 * 1024 * 1024
    if suffix in {".dll", ".pyd"}:
        return 128 * 1024 * 1024
    return 64 * 1024 * 1024


def _normalize_pins(value: object, code: str) -> dict[str, str]:
    _need(type(value) is dict, code)
    result: dict[str, str] = {}
    for path, digest in value.items():
        _need(type(path) is str or isinstance(path, Path), code)
        _need(_valid_sha(digest), code)
        key = _path_key(path)
        prior = result.get(key)
        _need(prior is None or prior == digest, "pin_path_conflict")
        result[key] = digest
    return result


def _binding_rows(pins: dict[str, str], *, category: str, prefix: str):
    _need(category in {"public", "software", "support"}, "binding_category_invalid")
    rows = []
    for key, digest in sorted(pins.items()):
        _need(_valid_sha(digest), "binding_digest_invalid")
        rows.append(
            {
                "logical_origin": prefix + "/" + key,
                "physical_path": key,
                "sha256": digest,
                "max_bytes": _row_limit(key, software=category == "software"),
                "category": category,
            }
        )
    return rows


def _merge_pins(*maps: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for mapping in maps:
        for key, digest in mapping.items():
            prior = merged.get(key)
            _need(prior is None or prior == digest, "pin_map_conflict")
            merged[key] = digest
    return merged


def _load_module(raw: bytes, path: Path, name: str) -> types.ModuleType:
    _need(type(raw) is bytes and len(raw) <= MAX_SOURCE_BYTES, "module_source_invalid")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    module.__verified_source_sha256__ = _sha(raw)
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    return module


def _register_verified_module_alias(module: types.ModuleType, digest: str) -> None:
    """Register one verified outer module alias without replacing warm state."""
    name = getattr(module, "__name__", None)
    _need(
        type(module) is types.ModuleType
        and type(name) is str
        and name
        and getattr(module, "__verified_source_sha256__", None) == digest
        and getattr(getattr(module, "__spec__", None), "origin", None)
        == getattr(module, "__file__", None),
        "module_alias_registration_source_invalid",
    )
    prior = sys.modules.get(name)
    _need(prior is None or prior is module, "module_alias_registration_collision")
    if prior is None:
        sys.modules[name] = module


class _OwnerReader:
    """Owner-thread adapter over exact V4 rows; opaque bytes never escape."""

    __slots__ = ("_scope", "_rows", "_sealed")

    def __init__(self, scope, rows: dict[str, tuple[str, str, int]]):
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_rows", MappingProxyType(dict(rows)))
        object.__setattr__(self, "_sealed", _WORKER_SEAL)

    def __setattr__(self, name, value):
        raise AttributeError("owner_reader_immutable")

    def read_pin(self, path, digest):
        _need(self._sealed is _WORKER_SEAL, "owner_reader_seal_invalid")
        key = _path_key(path)
        row = self._rows.get(key)
        _need(row is not None and row[0] == digest, "owner_reader_unbound_pin")
        category, maximum = row[1], row[2]
        if _is_opaque_pin(key, digest, category, maximum):
            self._scope.verify_pin(key, digest)
            return None
        return self._scope.read_held(key, digest, maximum)

class _RootHeldWorkerScope:
    __slots__ = ("_view", "_entered", "_release_requested")

    def __init__(self, view):
        self._view = view
        self._entered = False
        self._release_requested = False

    def __enter__(self):
        _need(self._view._sealed is _WORKER_SEAL and not self._entered, "worker_scope_state_invalid")
        self._entered = True
        return self._view.private, self._view.cli, dict(self._view.raw_held)

    def __exit__(self, exc_type, _exc, _traceback):
        _need(self._view._sealed is _WORKER_SEAL and self._entered, "worker_scope_state_invalid")
        if exc_type is None:
            self._release_requested = True
        return False


class RootHeldWorkerSnapshot:
    """Immutable R5 worker view; V4 methods stay on their owner thread."""

    __slots__ = (
        "schema", "public_pins", "support_pins", "software_pins", "public_bytes", "opaque_pins",
        "raw_held", "private", "cli", "profiler_rows", "metrics", "_sealed",
        "_scope_identity", "_worker_scope_created",
    )

    def __init__(
        self,
        scope,
        public_pins,
        support_pins,
        software_pins,
        public_bytes,
        opaque_pins,
        profiler_rows,
        metrics,
    ):
        object.__setattr__(self, "schema", ENTRY_SCHEMA + ".worker-snapshot.v1")
        object.__setattr__(self, "public_pins", MappingProxyType(dict(public_pins)))
        object.__setattr__(self, "support_pins", MappingProxyType(dict(support_pins)))
        object.__setattr__(self, "software_pins", MappingProxyType(dict(software_pins)))
        object.__setattr__(self, "public_bytes", MappingProxyType(dict(public_bytes)))
        object.__setattr__(self, "opaque_pins", MappingProxyType(dict(opaque_pins)))
        object.__setattr__(self, "raw_held", MappingProxyType(dict(public_bytes)))
        object.__setattr__(self, "private", scope.private)
        object.__setattr__(self, "cli", scope.cli)
        object.__setattr__(self, "profiler_rows", MappingProxyType(dict(profiler_rows)))
        object.__setattr__(self, "metrics", MappingProxyType(dict(metrics)))
        object.__setattr__(self, "_sealed", _WORKER_SEAL)
        object.__setattr__(self, "_scope_identity", id(scope))
        object.__setattr__(self, "_worker_scope_created", False)

    def __setattr__(self, name, value):
        raise AttributeError("worker_snapshot_immutable")

    def _assert_sealed(self):
        _need(self._sealed is _WORKER_SEAL, "worker_snapshot_seal_invalid")
        _need(type(self.public_pins) is MappingProxyType, "worker_snapshot_public_map_invalid")
        _need(type(self.support_pins) is MappingProxyType, "worker_snapshot_support_map_invalid")
        _need(type(self.software_pins) is MappingProxyType, "worker_snapshot_software_map_invalid")
        _need(type(self.public_bytes) is MappingProxyType, "worker_snapshot_bytes_map_invalid")
        _need(type(self.opaque_pins) is MappingProxyType, "worker_snapshot_opaque_map_invalid")

    def read_pin(self, path, digest):
        self._assert_sealed()
        key = _path_key(path)
        expected = self.public_pins.get(key)
        if expected is None:
            expected = self.support_pins.get(key)
        if expected is not None:
            _need(expected == digest, "worker_public_pin_mismatch")
            raw = self.public_bytes.get(key)
            if raw is not None:
                _need(type(raw) is bytes and _sha(raw) == digest, "worker_public_bytes_mismatch")
                return raw
            _need(self.opaque_pins.get(key) == digest, "worker_public_opaque_proof_missing")
            return None
        expected = self.software_pins.get(key)
        _need(expected is not None and expected == digest, "worker_pin_not_in_snapshot")
        _need(self.opaque_pins.get(key) == digest, "worker_software_proof_missing")
        return None

    def read_fixed(self, path, digest):
        raw = self.read_pin(path, digest)
        _need(type(raw) is bytes, "worker_fixed_opaque_read_rejected")
        return raw

    def assert_held_or_bytes(self, path, digest, held):
        self._assert_sealed()
        key = _path_key(path)
        expected = self.public_pins.get(key)
        if expected is not None:
            _need(expected == digest, "worker_held_public_pin_mismatch")
            raw = self.public_bytes.get(key)
            if raw is None:
                _need(self.opaque_pins.get(key) == digest, "worker_public_opaque_proof_missing")
                _need(key not in held, "worker_opaque_bytes_unexpected")
                return True
            _need(type(raw) is bytes and _sha(raw) == digest, "worker_public_bytes_mismatch")
            _need(held.get(key) == raw, "worker_held_public_bytes_mismatch")
            return True
        _need(self.software_pins.get(key) == digest, "worker_held_pin_missing")
        _need(self.opaque_pins.get(key) == digest and key not in held, "worker_software_proof_missing")
        return True

    def profiler_row(self, name):
        self._assert_sealed()
        row = self.profiler_rows.get(name)
        _need(type(row) is dict and row.get("module") == name, "worker_profiler_row_missing")
        return dict(row)

    def worker_scope(self, public_pins, software_pins):
        self._assert_sealed()
        _need(_normalize_pins(public_pins, "worker_expected_public_invalid") == dict(self.public_pins),
              "worker_expected_public_map_mismatch")
        _need(_normalize_pins(software_pins, "worker_expected_software_invalid") == dict(self.software_pins),
              "worker_expected_software_map_mismatch")
        _need(self._worker_scope_created is False, "worker_scope_reentry_rejected")
        object.__setattr__(self, "_worker_scope_created", True)
        return _RootHeldWorkerScope(self)


def _install_worker_r27_loader(helper, invoke, raw, view):
    reference = helper._reference_module(raw, helper.R27_INVOKE, invoke.__name__)
    reference_loader = reference.__dict__.get("_load_declarations")
    _need(type(reference_loader) is types.FunctionType, "worker_loader_reference_missing")
    loader = types.FunctionType(
        reference_loader.__code__,
        invoke.__dict__,
        reference_loader.__name__,
        reference_loader.__defaults__,
        reference_loader.__closure__,
    )
    loader.__kwdefaults__ = reference_loader.__kwdefaults__
    loader.__annotations__ = dict(reference_loader.__annotations__)
    loader.__dict__.update(reference_loader.__dict__)
    _need(helper._function_matches_reference(loader, reference_loader, actual_module=invoke),
          "worker_loader_source_binding_invalid")
    audit: list[str] = []

    def exact_worker_loader(raw_source: bytes, path: Path, name: str):
        reused = name in sys.modules
        result = helper._verified_load(loader, raw_source, path, name, view.read_pin)
        if reused:
            audit.append(name)
        return result

    exact_worker_loader.__name__ = "_r5_worker_exact_loader"
    exact_worker_loader.__qualname__ = "_r5_worker_exact_loader"
    invoke._load_declarations = exact_worker_loader
    helper._advance_module_contract(
        invoke,
        {"_load_declarations": exact_worker_loader},
        stage="r5_owner_held_worker_source_reader",
    )
    invoke.__r5_worker_loader_audit__ = audit


def _transform_deferred_scope(helper, invoke, raw, view):
    try:
        tree = ast.parse(raw.decode("utf-8", "strict"))
    except (UnicodeError, SyntaxError):
        raise RootHeldEntryError("r27_scope_source_parse_failed") from None
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_DeferredScope"]
    _need(len(classes) == 1, "r27_scope_class_anchor_invalid")
    changed = 0
    for method in classes[0].body:
        if not isinstance(method, ast.FunctionDef) or method.name not in {"__enter__", "__exit__"}:
            continue
        anchors = []
        for node in ast.walk(method):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "_sha":
                continue
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Call):
                continue
            inner = node.args[0]
            if not isinstance(inner.func, ast.Name) or inner.func.id != "_held_bytes" or len(inner.args) != 2:
                continue
            if (
                isinstance(inner.args[0], ast.Attribute)
                and isinstance(inner.args[0].value, ast.Name)
                and inner.args[0].value.id == "self"
                and inner.args[0].attr == "held"
                and isinstance(inner.args[1], ast.Name)
                and inner.args[1].id == "path"
            ):
                anchors.append(node)
        _need(len(anchors) == 1, "r27_scope_digest_anchor_invalid")
        comparison = None
        parent_map = {}
        for parent in ast.walk(method):
            for child in ast.iter_child_nodes(parent):
                parent_map[child] = parent
        call = anchors[0]
        parent = parent_map.get(call)
        if isinstance(parent, ast.Compare) and len(parent.ops) == 1 and isinstance(parent.ops[0], ast.Eq):
            comparison = parent
        _need(comparison is not None, "r27_scope_digest_compare_invalid")
        replacement = ast.Call(
            func=ast.Name(id="_R5_WORKER_ASSERT_HELD", ctx=ast.Load()),
            args=[
                ast.Name(id="path", ctx=ast.Load()),
                ast.Name(id="digest", ctx=ast.Load()),
                ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr="held",
                    ctx=ast.Load(),
                ),
            ],
            keywords=[],
        )
        comparison.left = replacement
        comparison.comparators = [ast.Constant(True)]
        changed += 1
    _need(changed == 2, "r27_scope_transform_count_invalid")
    ast.fix_missing_locations(tree)
    module = ast.Module(body=[classes[0]], type_ignores=[])
    code = compile(module, str(invoke.__file__), "exec", dont_inherit=True)
    scratch = dict(invoke.__dict__)
    exec(code, scratch, scratch)
    transformed = scratch.get("_DeferredScope")
    _need(type(transformed) is type and transformed.__name__ == "_DeferredScope", "r27_scope_transform_invalid")
    for method_name in ("__init__", "__enter__", "__exit__"):
        prior = getattr(transformed, method_name, None)
        _need(
            type(prior) is types.FunctionType
            and prior.__globals__ is scratch,
            "r27_scope_method_source_invalid",
        )
        rebound = types.FunctionType(
            prior.__code__,
            invoke.__dict__,
            prior.__name__,
            prior.__defaults__,
            prior.__closure__,
        )
        rebound.__module__ = prior.__module__
        rebound.__qualname__ = prior.__qualname__
        rebound.__kwdefaults__ = prior.__kwdefaults__
        rebound.__annotations__ = dict(prior.__annotations__)
        rebound.__dict__.update(prior.__dict__)
        setattr(transformed, method_name, rebound)
        _need(
            getattr(transformed, method_name) is rebound
            and rebound.__globals__ is invoke.__dict__
            and rebound.__code__ is prior.__code__,
            "r27_scope_method_global_binding_invalid",
        )
    assert_held = view.assert_held_or_bytes
    worker_scope = view.worker_scope
    read_pin = view.read_pin
    invoke._DeferredScope = transformed
    invoke._R5_WORKER_ASSERT_HELD = assert_held
    invoke._R5_WORKER_SCOPE = worker_scope
    invoke._R5_WORKER_READ_PIN = read_pin
    helper._accept_module_namespace_stage(
        invoke,
        {
            "_DeferredScope": transformed,
            "_R5_WORKER_ASSERT_HELD": assert_held,
            "_R5_WORKER_SCOPE": worker_scope,
            "_R5_WORKER_READ_PIN": read_pin,
        },
        stage="r5_opaque_public_pin_worker_view",
    )


def _transform_r28_worker_installer(helper, raw, view):
    _need(
        type(raw) is bytes
        and _sha(raw) == R28_R5_SHA256
        and helper.__dict__.get("__r5_source_bytes__") is raw,
        "r28_worker_installer_source_unbound",
    )
    reference = helper._reference_module(raw, Path(str(helper.__file__)), helper.__name__)
    original_installer = helper.__dict__.get("install_full_hold_adaptation")
    reference_installer = reference.__dict__.get("install_full_hold_adaptation")
    _need(
        type(original_installer) is types.FunctionType
        and type(reference_installer) is types.FunctionType
        and helper._function_reference_issue(
            original_installer,
            reference_installer,
            actual_module=helper,
        ) is None,
        "r28_worker_installer_original_source_invalid",
    )
    try:
        tree = ast.parse(raw.decode("utf-8", "strict"))
    except (UnicodeError, SyntaxError):
        raise RootHeldEntryError("r28_source_parse_failed") from None
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "install_full_hold_adaptation"]
    _need(len(functions) == 1, "r28_worker_installer_anchor_invalid")
    installer = functions[0]
    worker_functions = [node for node in ast.walk(installer) if isinstance(node, ast.FunctionDef)]
    full_holds = [node for node in worker_functions if node.name == "full_hold"]
    readers = [node for node in worker_functions if node.name == "public_read_pin"]
    _need(len(full_holds) == 1 and len(readers) == 1, "r28_worker_inner_function_shape_invalid")

    full_hold = full_holds[0]
    body = list(full_hold.body)
    branch_index = None
    for index, node in enumerate(body):
        if isinstance(node, ast.If) and "source_fake_mode" in ast.dump(node.test):
            _need(branch_index is None, "r28_fake_scope_branch_duplicate")
            branch_index = index
    _need(branch_index is not None and branch_index > 0, "r28_fake_scope_branch_missing")
    prior = body[branch_index - 1]
    _need(
        isinstance(prior, ast.Assign)
        and len(prior.targets) == 1
        and isinstance(prior.targets[0], ast.Name)
        and prior.targets[0].id == "fake_factory",
        "r28_fake_scope_factory_anchor_invalid",
    )
    scope_assignment = ast.Assign(
        targets=[ast.Name(id="raw_scope", ctx=ast.Store())],
        value=ast.Call(
            func=ast.Name(id="_ROOT_HELD_WORKER_SCOPE", ctx=ast.Load()),
            args=[ast.Name(id="full", ctx=ast.Load()), ast.Subscript(
                value=ast.Name(id="active_context", ctx=ast.Load()),
                slice=ast.Constant("expected_software"),
                ctx=ast.Load(),
            )],
            keywords=[],
        ),
    )
    full_hold.body[branch_index - 1 : branch_index + 1] = [scope_assignment]

    reader = readers[0]
    reader.body = [
        ast.Expr(
            value=ast.Call(
                func=ast.Name(id="_need", ctx=ast.Load()),
                args=[
                    ast.Compare(
                        left=ast.Call(
                            func=ast.Name(id="type", ctx=ast.Load()),
                            args=[ast.Name(id="_ROOT_HELD_WORKER_READ_PIN", ctx=ast.Load())],
                            keywords=[],
                        ),
                        ops=[ast.Is()],
                        comparators=[ast.Name(id="_ROOT_HELD_WORKER_READ_PIN_TYPE", ctx=ast.Load())],
                    ),
                    ast.Constant("root_worker_snapshot_invalid"),
                ],
                keywords=[],
            )
        ),
        ast.Return(
            value=ast.Call(
                func=ast.Name(id="_ROOT_HELD_WORKER_READ_PIN", ctx=ast.Load()),
                args=[ast.Name(id="path", ctx=ast.Load()), ast.Name(id="digest", ctx=ast.Load())],
                keywords=[],
            )
        ),
    ]
    ast.fix_missing_locations(tree)
    module = ast.Module(body=[installer], type_ignores=[])
    scratch = helper.__dict__
    compiled = compile(module, str(helper.__file__), "exec", dont_inherit=True)
    exec(compiled, scratch, scratch)
    helper._ROOT_HELD_WORKER_SCOPE = view.worker_scope
    helper._ROOT_HELD_WORKER_READ_PIN = view.read_pin
    helper._ROOT_HELD_WORKER_READ_PIN_TYPE = types.MethodType
    installed = helper.__dict__.get("install_full_hold_adaptation")
    _need(
        type(installed) is types.FunctionType
        and installed.__globals__ is helper.__dict__
        and installed.__name__ == "install_full_hold_adaptation"
        and installed.__code__.co_filename == str(helper.__file__)
        and installed.__code__.co_argcount == reference_installer.__code__.co_argcount
        and installed.__code__.co_kwonlyargcount == reference_installer.__code__.co_kwonlyargcount
        and installed.__code__.co_freevars == reference_installer.__code__.co_freevars
        and installed.__defaults__ == reference_installer.__defaults__
        and installed.__kwdefaults__ == reference_installer.__kwdefaults__
        and type(helper._ROOT_HELD_WORKER_SCOPE) is types.MethodType
        and helper._ROOT_HELD_WORKER_SCOPE.__self__ is view
        and helper._ROOT_HELD_WORKER_SCOPE.__func__ is RootHeldWorkerSnapshot.worker_scope
        and type(helper._ROOT_HELD_WORKER_READ_PIN) is types.MethodType
        and helper._ROOT_HELD_WORKER_READ_PIN.__self__ is view
        and helper._ROOT_HELD_WORKER_READ_PIN.__func__ is RootHeldWorkerSnapshot.read_pin,
        "r28_worker_installer_binding_invalid",
    )
    return {
        "source_sha256": R28_R5_SHA256,
        "changed_full_hold_scope_sites": 1,
        "changed_reader_sites": 1,
        "source_fake_mode_consumed": False,
        "worker_snapshot_type": "RootHeldWorkerSnapshot",
    }


def _transform_r2_profiler_consumer(helper, invoke, r2, raw, profiler_rows, callback, baseline):
    _need(type(raw) is bytes and _sha(raw) == R2_GLUE_SHA256, "r2_profiler_source_pin_invalid")
    try:
        tree = ast.parse(raw.decode("utf-8", "strict"))
    except (UnicodeError, SyntaxError):
        raise RootHeldEntryError("r2_profiler_source_parse_failed") from None
    mains = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"]
    _need(len(mains) == 1, "r2_profiler_main_anchor_invalid")
    main = mains[0]

    # R15's original closure predicate hashes every path through _held_bytes.
    # That is correct for ordinary source rows and incompatible with the
    # worker's intentionally opaque profiler cache rows. Replace exactly that
    # one expression with the sealed snapshot assertion already installed by
    # _transform_deferred_scope; do not read or synthesize opaque bytes.
    closure_anchors = []
    for node in ast.walk(main):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "all"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.GeneratorExp)
            and not node.keywords
        ):
            continue
        generator = node.args[0]
        if len(generator.generators) != 1:
            continue
        clause = generator.generators[0]
        target = clause.target
        iterator = clause.iter
        element = generator.elt
        if (
            isinstance(target, ast.Tuple)
            and len(target.elts) == 2
            and all(isinstance(item, ast.Name) for item in target.elts)
            and [item.id for item in target.elts] == ["p", "h"]
            and isinstance(iterator, ast.Call)
            and isinstance(iterator.func, ast.Attribute)
            and isinstance(iterator.func.value, ast.Name)
            and iterator.func.value.id == "inner_pins"
            and iterator.func.attr == "items"
            and not iterator.args
            and not iterator.keywords
            and isinstance(element, ast.Compare)
            and len(element.ops) == 1
            and isinstance(element.ops[0], ast.Eq)
            and len(element.comparators) == 1
            and isinstance(element.left, ast.Call)
            and isinstance(element.left.func, ast.Name)
            and element.left.func.id == "sha"
            and len(element.left.args) == 1
            and not element.left.keywords
            and isinstance(element.left.args[0], ast.Call)
            and isinstance(element.left.args[0].func, ast.Name)
            and element.left.args[0].func.id == "_held_bytes"
            and len(element.left.args[0].args) == 2
            and not element.left.args[0].keywords
            and isinstance(element.left.args[0].args[0], ast.Name)
            and element.left.args[0].args[0].id == "held"
            and isinstance(element.left.args[0].args[1], ast.Name)
            and element.left.args[0].args[1].id == "p"
            and isinstance(element.comparators[0], ast.Name)
            and element.comparators[0].id == "h"
        ):
            closure_anchors.append((node, generator))
    _need(len(closure_anchors) == 1, "r2_inner_closure_anchor_invalid")
    _closure_call, closure_generator = closure_anchors[0]
    closure_generator.elt = ast.Call(
        func=ast.Attribute(
            value=ast.Name(id="ROOT_R27_INVOKE", ctx=ast.Load()),
            attr="_R5_WORKER_ASSERT_HELD",
            ctx=ast.Load(),
        ),
        args=[
            ast.Name(id="p", ctx=ast.Load()),
            ast.Name(id="h", ctx=ast.Load()),
            ast.Name(id="held", ctx=ast.Load()),
        ],
        keywords=[],
    )

    review_anchors = []
    for node in ast.walk(main):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Attribute)
            and isinstance(node.targets[0].value, ast.Name)
            and node.targets[0].value.id == "active"
            and node.targets[0].attr == "ROOT_DRIVER_REVIEW_PINS"
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "dict"
            and len(node.value.args) == 1
            and isinstance(node.value.args[0], ast.Name)
            and node.value.args[0].id == "ROOT_REVIEW_PINS"
            and not node.value.keywords
        ):
            review_anchors.append(node)
    _need(len(review_anchors) == 1, "r2_profiler_review_projection_anchor_invalid")
    target = review_anchors[0]
    target.value = ast.Call(
        func=ast.Name(id="_r28_project_r19_review_pins", ctx=ast.Load()),
        args=[
            target.value,
            ast.Name(id="ROOT_REVIEW_README_SHA", ctx=ast.Load()),
            ast.Name(id="REVIEW", ctx=ast.Load()),
        ],
        keywords=[],
    )

    call_anchors = []
    for node in ast.walk(main):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        func = node.func
        if not (
            isinstance(func.value, ast.Name)
            and func.value.id == "proof"
            and func.attr == "verify_module_cache"
            and len(node.args) == 3
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "name"
        ):
            continue
        call_anchors.append(node)
    _need(len(call_anchors) == 1, "r2_profiler_cache_call_anchor_invalid")
    parent_map = {}
    for parent in ast.walk(main):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent
    statement = parent_map.get(call_anchors[0])
    _need(
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "row",
        "r2_profiler_row_assignment_invalid",
    )
    statement.value = ast.Subscript(
        value=ast.Name(id="ROOT_HELD_WORKER_VIEW", ctx=ast.Load()),
        slice=ast.Name(id="name", ctx=ast.Load()),
        ctx=ast.Load(),
    )
    ledger = ast.Expr(
        value=ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="ROOT_R27_INVOKE", ctx=ast.Load()),
                attr="_record_profiler_verification",
                ctx=ast.Load(),
            ),
            args=[
                ast.Name(id="name", ctx=ast.Load()),
                ast.Name(id="row", ctx=ast.Load()),
            ],
            keywords=[],
        )
    )
    statement_lists = []
    for parent in ast.walk(main):
        for _field_name, value in ast.iter_fields(parent):
            if type(value) is list and any(node is statement for node in value):
                statement_lists.append(value)
    _need(len(statement_lists) == 1, "r2_profiler_statement_owner_invalid")
    statement_list = statement_lists[0]
    statement_indexes = [index for index, node in enumerate(statement_list) if node is statement]
    _need(len(statement_indexes) == 1, "r2_profiler_statement_index_invalid")
    statement_list[statement_indexes[0] : statement_indexes[0] + 1] = [statement, ledger]
    ast.fix_missing_locations(tree)
    compiled = compile(tree, str(r2.__file__), "exec", dont_inherit=True)
    scratch: dict[str, object] = {"__builtins__": r2.__dict__["__builtins__"]}
    exec(compiled, scratch, scratch)
    transformed_main = scratch.get("main")
    _need(type(transformed_main) is types.FunctionType, "r2_profiler_transform_function_invalid")
    original = r2.main
    code = transformed_main.__code__
    old_schema = invoke._R2_PARENT_SCHEMA_V1
    new_schema = invoke._R5_PARENT_SCHEMA_V1
    indexes = [i for i, item in enumerate(code.co_consts) if type(item) is str and item == old_schema]
    _need(len(indexes) == 1, "r2_profiler_parent_schema_anchor_invalid")
    constants = list(code.co_consts)
    constants[indexes[0]] = new_schema
    code = code.replace(co_consts=tuple(constants))
    main_proxy = types.FunctionType(code, r2.__dict__, original.__name__, original.__defaults__, original.__closure__)
    main_proxy.__module__ = original.__module__
    main_proxy.__qualname__ = original.__qualname__
    main_proxy.__kwdefaults__ = original.__kwdefaults__
    main_proxy.__annotations__ = dict(original.__annotations__)
    main_proxy.__dict__.update(original.__dict__)
    r2.ROOT_HELD_WORKER_VIEW = profiler_rows
    r2.ROOT_R27_INVOKE = invoke
    r2.main = main_proxy
    _validate_r2_worker_projection(
        invoke,
        r2,
        baseline,
        main=main_proxy,
        rows=profiler_rows,
        callback=callback,
    )
    helper._advance_module_contract(
        r2,
        {"main": main_proxy},
        stage="r5_exact_profiler_result_projection",
        namespace_bindings={
            "ROOT_HELD_WORKER_VIEW": profiler_rows,
            "ROOT_R27_INVOKE": invoke,
        },
    )
    helper._assert_module_contract(r2)
    return {
        "source_sha256": R2_GLUE_SHA256,
        "review_projection_anchors": 1,
        "profiler_call_anchors": 1,
        "opaque_pin_predicate_anchors": 1,
        "opaque_bytes_read": False,
        "changed_validator_count": 0,
        "cache_bytes_returned_to_worker": False,
    }


def _transform_r2_cold_projection(raw: bytes, path: Path, reader: _OwnerReader, globals_from: dict[str, object]):
    _need(type(raw) is bytes and _sha(raw) == R2_GLUE_SHA256, "r2_cold_source_pin_invalid")
    try:
        tree = ast.parse(raw.decode("utf-8", "strict"))
    except (UnicodeError, SyntaxError):
        raise RootHeldEntryError("r2_cold_source_parse_failed") from None
    mains = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"]
    _need(len(mains) == 1, "r2_cold_main_anchor_invalid")
    assignments = []
    for node in ast.walk(mains[0]):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if (
            isinstance(target, ast.Name)
            and target.id == "cu"
            and isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "load"
            and len(value.args) == 3
            and isinstance(value.args[0], ast.Call)
            and isinstance(value.args[0].func, ast.Name)
            and value.args[0].func.id == "read_pin"
            and isinstance(value.args[1], ast.Name)
            and value.args[1].id == "CU"
        ):
            assignments.append(node)
    _need(len(assignments) == 1, "r2_cold_scope_boundary_anchor_invalid")
    return_node = ast.Return(
        value=ast.Tuple(
            elts=[ast.Name(id="pins", ctx=ast.Load()), ast.Name(id="software", ctx=ast.Load())],
            ctx=ast.Load(),
        )
    )
    target = assignments[0]
    parent_map = {}
    for parent in ast.walk(mains[0]):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent
    statement = parent_map.get(target)
    # The source-pinned `cu = load(read_pin(...))` assignment must remain a
    # direct statement in this exact `main` function. The parent map points
    # from a statement to its containing FunctionDef (not back to itself).
    _need(statement is mains[0], "r2_cold_scope_boundary_not_main_statement")
    mains[0].body = [return_node if node is target else node for node in mains[0].body]
    ast.fix_missing_locations(tree)
    module_raw = compile(tree, str(path), "exec", dont_inherit=True)
    module = _load_module(raw, path, "_r5_owner_cold_projection_source")
    exec(module_raw, module.__dict__, module.__dict__)
    module.read_pin = reader.read_pin
    module.sys = types.SimpleNamespace(
        flags=sys.flags,
        dont_write_bytecode=sys.dont_write_bytecode,
        version_info=sys.version_info,
        implementation=sys.implementation,
        platform=sys.platform,
        argv=[str(path)],
        modules={},
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    for name, value in globals_from.items():
        setattr(module, name, value)
    original_argv = sys.argv
    try:
        sys.argv = [str(path)]
        output = module.main()
    finally:
        sys.argv = original_argv
    _need(type(output) is tuple and len(output) == 2, "r2_cold_projection_result_invalid")
    return output


def _parse_root_public_map(raw: bytes) -> dict[str, str]:
    _need(type(raw) is bytes and _sha(raw) == R25_PUBLIC_MAP_SHA256, "r25_public_map_pin_invalid")
    try:
        document = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise RootHeldEntryError("r25_public_map_json_invalid") from None
    rows = document.get("public_paths_sha256") if type(document) is dict else None
    _need(
        type(document) is dict
        and document.get("schema") == "iteration41.optional16.r25.public-pins.v1"
        and document.get("root_enabled") is False
        and document.get("sdk_imported") is False
        and document.get("installed_record_read") is False
        and document.get("private_inputs_read") is False
        and document.get("provider_requests") is False
        and type(rows) is dict
        and len(rows) == 379,
        "r25_public_map_shape_invalid",
    )
    return _normalize_pins(rows, "r25_public_map_rows_invalid")


def _payload_artifact_pins(payload: dict[str, object], invoke) -> dict[str, str]:
    invoke_bind = payload.get("invoke")
    driver_bind = payload.get("driver")
    _need(type(invoke_bind) is dict and type(driver_bind) is dict, "payload_binding_shape_invalid")
    _need(
        _path_key(invoke_bind.get("path", "")) == _path_key(invoke.ROOT_SELF_PATH)
        and invoke_bind.get("sha256") == R27_INVOKE_SHA256
        and _path_key(invoke_bind.get("test_path", "")) == _path_key(invoke.ROOT_TEST_PATH)
        and invoke_bind.get("test_sha256") == R27_TEST_SHA256,
        "payload_invoke_binding_invalid",
    )
    _need(
        _path_key(driver_bind.get("path", "")) == _path_key(invoke.DRIVER)
        and driver_bind.get("sha256") == R19_DRIVER_SHA256,
        "payload_driver_binding_invalid",
    )
    pins: dict[str, str] = {}
    for branch in (invoke_bind, driver_bind):
        for path_field, sha_field in (("path", "sha256"), ("test_path", "test_sha256")):
            path = branch.get(path_field)
            digest = branch.get(sha_field)
            if path is not None:
                key = _path_key(path)
                _need(_valid_sha(digest), "payload_artifact_digest_invalid")
                pins[key] = digest
        for folder_field, pin_field in (("packet_dir", "packet_pins"), ("review_dir", "review_pins")):
            folder = branch.get(folder_field)
            values = branch.get(pin_field)
            _need(type(folder) is str and type(values) is dict, "payload_artifact_map_invalid")
            _need(_path_key(folder).startswith(_path_key(ROOT)), "payload_artifact_outside_root")
            for name, digest in values.items():
                _need(type(name) is str and ".." not in Path(name).parts and _valid_sha(digest),
                      "payload_artifact_row_invalid")
                pins[_path_key(Path(folder) / name)] = digest

    # The bound R19 driver packet carries the complete declared R16–R19
    # source closure. Add those exact member pins to bootstrap so the frozen
    # R27 binder can verify its production source_files mapping using the
    # owner scope, rather than a one-off filesystem fallback.
    driver_folder = Path(driver_bind["packet_dir"])
    driver_packet_pins = driver_bind["packet_pins"]
    source_pins_digest = driver_packet_pins.get("source-pins.json")
    _need(_valid_sha(source_pins_digest), "payload_r19_source_pins_digest_missing")
    source_pins_path = driver_folder / "source-pins.json"
    source_pins_key = _path_key(source_pins_path)
    _need(source_pins_key in pins and pins[source_pins_key] == source_pins_digest,
          "payload_r19_source_pins_not_bound")
    source_pins_raw = _bounded_repo_source(
        Path(os.path.relpath(source_pins_path, ROOT)), source_pins_digest, MAX_METADATA_BYTES
    )[1]
    source_members = _source_member_pins(source_pins_raw)
    for path, digest in source_members.items():
        prior = pins.get(path)
        _need(prior is None or prior == digest, "payload_source_member_pin_conflict")
        pins[path] = digest
    return pins


def _source_member_pins(raw: bytes) -> dict[str, str]:
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_METADATA_BYTES,
          "r19_source_pins_bytes_invalid")
    try:
        document = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise RootHeldEntryError("r19_source_pins_json_invalid") from None
    members = document.get("member_sha256") if type(document) is dict else None
    _need(
        type(document) is dict
        and document.get("schema") == "iteration41.optional16.r33.deadline-r19.source-pins.v1"
        and type(members) is dict
        and 0 < len(members) <= MAX_ROWS,
        "r19_source_pins_shape_invalid",
    )
    result = {}
    for relative, digest in members.items():
        _need(
            type(relative) is str
            and relative
            and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts
            and _valid_sha(digest),
            "r19_source_member_row_invalid",
        )
        path = _path_key(ROOT / Path(relative))
        _need(path.startswith(_path_key(ROOT) + os.sep.casefold()),
              "r19_source_member_outside_root")
        result[path] = digest
    _need(len(result) == len(members), "r19_source_member_duplicate_path")
    return result


def _predecessor_packet_review_pins() -> dict[str, str]:
    """Read fixed R16–R18 packet/review declarations from pinned R19 code."""
    raw = _bounded_repo_source(R19_BINDING_HELPER_REL, R19_BINDING_HELPER_SHA256)[1]
    module = _load_module(
        raw, ROOT / R19_BINDING_HELPER_REL, "_r5_fixed_r19_artifact_declarations"
    )
    result = {}
    evidence_key = _path_key(EVIDENCE)
    for stage in (16, 17, 18):
        for folder_name, pins_name in (
            (f"R{stage}_PACKET", f"R{stage}_PACKET_PINS"),
            (f"R{stage}_REVIEW", f"R{stage}_REVIEW_PINS"),
        ):
            folder = getattr(module, folder_name, None)
            pins = getattr(module, pins_name, None)
            _need(isinstance(folder, Path) and type(pins) is dict,
                  "r19_predecessor_artifact_metadata_invalid")
            folder_key = _path_key(folder)
            _need(folder_key.startswith(evidence_key + os.sep.casefold()),
                  "r19_predecessor_artifact_outside_evidence")
            for name, digest in pins.items():
                _need(
                    type(name) is str
                    and name
                    and not Path(name).is_absolute()
                    and ".." not in Path(name).parts
                    and _valid_sha(digest),
                    "r19_predecessor_artifact_pin_invalid",
                )
                key = _path_key(folder / name)
                prior = result.get(key)
                _need(prior is None or prior == digest,
                      "r19_predecessor_artifact_pin_conflict")
                result[key] = digest
    return result


def _r19_map_builder_support_pins() -> dict[str, str]:
    """Pin the one R19 source-index input needed before its full map exists."""
    raw = _bounded_repo_source(R19_DRIVER_REL, R19_DRIVER_SHA256)[1]
    module = _load_module(raw, ROOT / R19_DRIVER_REL, "_r5_fixed_r19_map_builder_inputs")
    packet = getattr(module, "R31_PACKET", None)
    packet_pins = getattr(module, "R31_PACKET_PINS", None)
    _need(
        type(module) is types.ModuleType
        and getattr(module, "__verified_source_sha256__", None) == R19_DRIVER_SHA256
        and isinstance(packet, Path)
        and type(packet_pins) is dict
        and "source-index.json" in packet_pins
        and _valid_sha(packet_pins["source-index.json"]),
        "r19_map_builder_input_declaration_invalid",
    )
    packet_key = _path_key(packet)
    _need(
        packet_key.startswith(_path_key(EVIDENCE) + os.sep.casefold())
        and packet.name.casefold().startswith("iteration41-optional16-r31-"),
        "r19_map_builder_input_context_invalid",
    )
    return {_path_key(packet / "source-index.json"): packet_pins["source-index.json"]}


def _scope_bindings(scope, expected: dict[str, str], categories: dict[str, str]):
    manifest = {_path_key(path): digest for path, digest in scope.manifest().items()}
    rows = {}
    for key, digest in expected.items():
        _need(manifest.get(key) == digest, "scope_expected_row_not_held")
        logical = scope.logical_bindings()
        matching = [row for origin, row in logical.items() if _path_key(row["physical_path"]) == key]
        _need(len(matching) == 1, "scope_expected_binding_ambiguous")
        category = matching[0]["category"]
        _need(category == categories.get(key, "public"), "scope_expected_category_mismatch")
        maximum = matching[0]["max_bytes"]
        rows[key] = (digest, category, maximum)
    return rows


def _validate_indexed_profiler_software(software, rows):
    indexed = set()
    for path, digest, size, role in PROFILER_STDLIB_OPAQUE_ROWS:
        _need(
            _metadata_opaque_descriptor(path, digest, size, role),
            "profiler_stdlib_descriptor_invalid",
        )
        key = _path_key(path)
        _need(software.get(key) == digest, "profiler_stdlib_software_pin_mismatch")
        row = rows.get(key)
        _need(
            row is not None
            and row[0] == digest
            and row[1] == "software"
            and row[2] >= size,
            "profiler_stdlib_software_row_mismatch",
        )
        indexed.add(key)
    software_python = {
        key for key in software if Path(key).suffix.casefold() == ".py"
    }
    _need(software_python == indexed, "profiler_software_python_set_mismatch")


def _make_snapshot(scope, worker_public, support_public, software, rows, profiler_rows, metrics):
    _validate_indexed_profiler_software(software, rows)
    public_bytes = {}
    opaque = {}
    combined_public = dict(worker_public)
    for key, digest in support_public.items():
        _need(key not in combined_public, "worker_support_map_overlap")
        combined_public[key] = digest
    for key, digest in sorted(combined_public.items()):
        category = rows[key][1]
        is_opaque = _is_opaque_pin(key, digest, category, rows[key][2])
        if is_opaque:
            scope.verify_pin(key, digest)
            opaque[key] = digest
        else:
            raw = scope.read_held(key, digest, rows[key][2])
            _need(type(raw) is bytes and _sha(raw) == digest, "snapshot_public_bytes_invalid")
            public_bytes[key] = raw
    for key, digest in software.items():
        row = rows.get(key)
        _need(row is not None and row[0] == digest, "snapshot_software_row_missing")
        _need(_is_opaque_pin(key, digest, row[1], row[2]), "snapshot_software_pin_not_opaque")
        scope.verify_pin(key, digest)
        opaque[key] = digest
    _need(
        set(public_bytes) | set(opaque) == set(combined_public) | set(software),
        "snapshot_row_closure_invalid",
    )
    return RootHeldWorkerSnapshot(
        scope,
        worker_public,
        support_public,
        software,
        public_bytes,
        opaque,
        profiler_rows,
        metrics,
    )


def _load_v4_module():
    path, raw = _bounded_repo_source(V4_REL, V4_SHA256, 256 * 1024)
    module = _load_module(raw, path, "_iteration41_optional16_r33_entry_v4")
    _need(module.__dict__.get("ROOT_HELD_SCOPE_V4_ENABLED") is False, "v4_default_changed")
    return module, raw


def helper_source_bytes(helper) -> bytes:
    raw = helper.__dict__.get("__r5_source_bytes__")
    _need(type(raw) is bytes and _sha(raw) == R28_R5_SHA256, "r28_helper_source_binding_missing")
    return raw


def _transform_r28_active_main_attestation(helper, raw: bytes) -> dict[str, object]:
    """Keep R28's main-wrapper check source-bound when production main is used.

    R28's frozen attester only recognizes the sourcefake callback branch. R27
    uses the original pinned driver main when no test callback is installed.
    This deterministic two-anchor AST successor accepts that exact compiled
    main reference while preserving the callback branch and all wrapper checks.
    """
    _need(
        type(raw) is bytes
        and _sha(raw) == R28_R5_SHA256
        and type(helper) is types.ModuleType
        and helper.__dict__.get("__r5_source_bytes__") is raw,
        "r28_main_attestation_source_unbound",
    )
    path = Path(helper.__file__)
    _need(
        helper.__verified_source_sha256__ == R28_R5_SHA256
        and helper.__spec__.origin == str(path)
        and helper.__file__ == str(path),
        "r28_main_attestation_origin_invalid",
    )
    reference = helper._reference_module(raw, path, helper.__name__)
    original = helper.__dict__.get("_attest_r27_active_driver_stage")
    reference_original = reference.__dict__.get("_attest_r27_active_driver_stage")
    _need(
        helper._function_matches_reference(original, reference_original, actual_module=helper),
        "r28_main_attestation_original_function_invalid",
    )
    try:
        tree = ast.parse(raw.decode("utf-8", "strict"))
    except (UnicodeError, SyntaxError):
        raise RootHeldEntryError("r28_main_attestation_source_parse_failed") from None
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_attest_r27_active_driver_stage"
    ]
    _need(len(functions) == 1, "r28_main_attestation_function_anchor_invalid")
    function = functions[0]
    main_source_anchors = [
        node for node in function.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "driver_main"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "active_context"
        and node.value.func.attr == "get"
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Constant)
        and node.value.args[0].value == "fake_active_main"
        and not node.value.keywords
    ]
    main_wrapper_anchors = [
        node for node in function.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "main_wrapper"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "getattr"
        and len(node.value.args) == 3
        and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id == "module"
        and isinstance(node.value.args[1], ast.Constant)
        and node.value.args[1].value == "main"
        and not node.value.keywords
    ]
    _need(len(main_source_anchors) == 1 and len(main_wrapper_anchors) == 1,
          "r28_main_attestation_closure_anchor_invalid")
    _need(function.body.index(main_source_anchors[0]) < function.body.index(main_wrapper_anchors[0]),
          "r28_main_attestation_anchor_order_invalid")
    main_cell_driver = ast.Subscript(
        value=ast.Call(
            func=ast.Name(id="_cell_map", ctx=ast.Load()),
            args=[ast.Name(id="main_wrapper", ctx=ast.Load())],
            keywords=[],
        ),
        slice=ast.Constant(value="driver_main"),
        ctx=ast.Load(),
    )
    prior_main_function = ast.Subscript(
        value=ast.Subscript(
            value=ast.Name(id="prior", ctx=ast.Load()),
            slice=ast.Constant(value="main"),
            ctx=ast.Load(),
        ),
        slice=ast.Constant(value="function"),
        ctx=ast.Load(),
    )
    bind_original_main = ast.If(
        test=ast.Compare(
            left=ast.Name(id="driver_main", ctx=ast.Load()),
            ops=[ast.Is()],
            comparators=[ast.Constant(value=None)],
        ),
        body=[
            ast.Assign(
                targets=[ast.Name(id="driver_main", ctx=ast.Store())],
                value=main_cell_driver,
            ),
            ast.Expr(
                value=ast.Call(
                    func=ast.Name(id="_need", ctx=ast.Load()),
                    args=[
                        ast.Call(
                            func=ast.Name(id="_function_matches_reference", ctx=ast.Load()),
                            args=[ast.Name(id="driver_main", ctx=ast.Load()), prior_main_function],
                            keywords=[
                                ast.keyword(
                                    arg="actual_module",
                                    value=ast.Name(id="module", ctx=ast.Load()),
                                )
                            ],
                        ),
                        ast.Constant(value="r27_original_main_source_invalid"),
                    ],
                    keywords=[],
                )
            ),
        ],
        orelse=[],
    )
    function.body.insert(function.body.index(main_wrapper_anchors[0]) + 1, bind_original_main)
    ast.fix_missing_locations(tree)
    probe = types.ModuleType(helper.__name__)
    probe.__file__ = str(path)
    probe.__package__ = ""
    probe.__cached__ = None
    probe.__loader__ = None
    probe.__spec__ = importlib.machinery.ModuleSpec(helper.__name__, loader=None, origin=str(path))
    probe.__dict__["__builtins__"] = dict(helper.__dict__["__builtins__"])
    try:
        exec(compile(tree, str(path), "exec", dont_inherit=True), probe.__dict__, probe.__dict__)
    except BaseException:
        raise RootHeldEntryError("r28_main_attestation_transform_compile_failed") from None
    transformed_reference = probe.__dict__.get("_attest_r27_active_driver_stage")
    transformed = types.FunctionType(
        transformed_reference.__code__,
        helper.__dict__,
        transformed_reference.__name__,
        transformed_reference.__defaults__,
        transformed_reference.__closure__,
    )
    transformed.__module__ = helper.__name__
    transformed.__qualname__ = transformed_reference.__qualname__
    transformed.__kwdefaults__ = transformed_reference.__kwdefaults__
    transformed.__annotations__ = dict(transformed_reference.__annotations__)
    transformed.__dict__.update(transformed_reference.__dict__)
    _need(
        helper._function_matches_reference(
            transformed, transformed_reference, actual_module=helper
        ),
        "r28_main_attestation_transform_function_invalid",
    )
    helper.__dict__["_attest_r27_active_driver_stage"] = transformed
    return {
        "source_sha256": R28_R5_SHA256,
        "function": "_attest_r27_active_driver_stage",
        "exact_ast_anchors": 2,
        "production_main_binding": "verified_original_r19_main_function",
        "sourcefake_callback_branch_preserved": True,
        "transformed_code_fingerprint": helper._code_fingerprint(transformed.__code__),
    }


def scope_public_manifest(scope):
    return scope.manifest()


class _ScopeReader:
    __slots__ = (
        "_scope",
        "_v4",
        "_rows",
        "_artifact_aliases",
        "_owner_thread",
        "_worker_thread",
        "_worker_view",
    )

    def __init__(self, scope, v4):
        self._scope = scope
        self._v4 = v4
        self._rows = {}
        self._artifact_aliases = {}
        self._owner_thread = threading.current_thread()
        self._worker_thread = None
        self._worker_view = None
        self._refresh()

    @property
    def v4(self):
        return self._v4

    @property
    def rows(self):
        return MappingProxyType(dict(self._rows))

    def _refresh(self):
        _need(threading.current_thread() is self._owner_thread, "source_scope_refresh_owner_mismatch")
        manifest = {_path_key(path): digest for path, digest in self._scope.manifest().items()}
        bindings = self._scope.logical_bindings()
        rows = {}
        for row in bindings.values():
            key = _path_key(row["physical_path"])
            digest = row["sha256"]
            if digest is None:
                # Software digest=None is not allowed in this production closure.
                raise RootHeldEntryError("unmeasured_software_row_rejected")
            _need(manifest.get(key) == digest, "scope_manifest_binding_mismatch")
            prior = rows.get(key)
            current = (digest, row["category"], row["max_bytes"])
            _need(prior is None or prior == current, "scope_binding_alias_conflict")
            rows[key] = current
        self._rows = rows

    def bind_worker_snapshot(self, view, thread):
        """Bind one immutable snapshot to the sole worker before it starts."""
        _need(threading.current_thread() is self._owner_thread, "source_scope_bind_owner_mismatch")
        _need(self._worker_thread is None and self._worker_view is None, "source_scope_worker_rebind")
        _need(type(view) is RootHeldWorkerSnapshot, "source_scope_worker_view_type")
        view._assert_sealed()
        _need(type(thread) is threading.Thread, "source_scope_worker_thread_type")
        _need(thread.ident is None and thread.is_alive() is False, "source_scope_worker_already_started")
        _need(thread.name == "optional16-r33-root-held-entry-r1", "source_scope_worker_thread_name")
        self._worker_view = view
        self._worker_thread = thread

    def _worker_view_for_call(self):
        current = threading.current_thread()
        if current is self._owner_thread:
            return None
        if current is self._worker_thread and self._worker_view is not None:
            self._worker_view._assert_sealed()
            return self._worker_view
        raise RootHeldEntryError("source_scope_owner_mismatch")

    def read_pin(self, path, digest):
        worker_view = self._worker_view_for_call()
        if worker_view is not None:
            return worker_view.read_pin(path, digest)
        key = _path_key(path)
        row = self._rows.get(key)
        _need(row is not None and row[0] == digest, "owner_scope_pin_unbound")
        category, maximum = row[1], row[2]
        if _is_opaque_pin(key, digest, category, maximum):
            self._scope.verify_pin(key, digest)
            return None
        return self._scope.read_held(key, digest, maximum)

    def read_artifact(self, path):
        """One-argument reader required by the pinned R27/R28 artifact APIs."""
        worker_view = self._worker_view_for_call()
        key = _path_key(path)
        row = self._rows.get(key)
        source_key = key
        if row is None:
            alias = self._artifact_aliases.get(key)
            _need(alias is not None, "owner_artifact_unheld")
            source_key, digest = alias
            row = self._rows.get(source_key)
            _need(row is not None and row[0] == digest, "owner_artifact_alias_unheld")
        digest, category, maximum = row
        _need(category != "software", "owner_artifact_opaque")
        if worker_view is not None:
            return worker_view.read_pin(source_key, digest)
        raw = self._scope.read_held(source_key, digest, maximum)
        _need(type(raw) is bytes and _sha(raw) == digest, "owner_artifact_bytes_invalid")
        return raw

    def bind_sourcefake_active_driver_alias(self, invoke):
        """Map only the fixed R27 active-driver label to its public source copy."""
        _need(
            type(invoke) is types.ModuleType
            and getattr(invoke, "__verified_source_sha256__", None) == R27_INVOKE_SHA256
            and getattr(invoke, "DRIVER_ACTIVE_PATH", None) is not None
            and _path_key(getattr(invoke, "DRIVER", ""))
            == _path_key(ROOT / R19_DRIVER_REL),
            "sourcefake_active_driver_alias_source_invalid",
        )
        origin = _path_key(invoke.DRIVER_ACTIVE_PATH)
        physical = _path_key(ROOT / R19_DRIVER_REL)
        digest = R19_DRIVER_SHA256
        target = self._rows.get(physical)
        _need(target is not None and target[0] == digest and target[1] == "public",
              "sourcefake_active_driver_snapshot_unheld")
        prior = self._artifact_aliases.get(origin)
        _need(prior is None or prior == (physical, digest),
              "sourcefake_active_driver_alias_conflict")
        self._artifact_aliases[origin] = (physical, digest)


def _make_bootstrap_bindings(public_rows, payload_rows, support_rows):
    merged = {}
    for mapping, category, prefix in (
        (public_rows, "public", "r25-public"),
        (payload_rows, "public", "r27-payload"),
        (support_rows, "public", "r5-support"),
    ):
        for key, digest in mapping.items():
            prior = merged.get(key)
            _need(prior is None or prior[0] == digest, "bootstrap_pin_conflict")
            merged[key] = (digest, category, prefix)
    rows = []
    for key, (digest, category, prefix) in sorted(merged.items()):
        rows.append(
            {
                "logical_origin": prefix + "/" + key,
                "physical_path": key,
                "sha256": digest,
                "max_bytes": _row_limit(key),
                "category": category,
            }
        )
    return rows


def _support_pins(v4=None):
    relatives = {
        V3_REL: V3_SHA256,
        V4_REL: V4_SHA256,
        R27_INVOKE_REL: R27_INVOKE_SHA256,
        R27_WHOLE_REL: R27_WHOLE_SHA256,
        R27_TEST_REL: R27_TEST_SHA256,
        R28_R5_REL: R28_R5_SHA256,
        R2_GLUE_REL: R2_GLUE_SHA256,
        R19_DRIVER_REL: R19_DRIVER_SHA256,
        R2_PREDECESSOR_REL: R2_PREDECESSOR_SHA256,
        R19_BINDING_HELPER_REL: R19_BINDING_HELPER_SHA256,
        R18_BINDING_HELPER_REL: R18_BINDING_HELPER_SHA256,
        R17_BINDING_HELPER_REL: R17_BINDING_HELPER_SHA256,
        R16_BINDING_HELPER_REL: R16_BINDING_HELPER_SHA256,
    }
    pins = {}
    for relative, digest in relatives.items():
        path, raw = _bounded_repo_source(relative, digest)
        pins[_path_key(path)] = digest
    if ROOT_ENTRY_SOURCE_SHA256 is not None:
        entry_relative = Path(os.path.relpath(Path(__file__), ROOT))
        entry_path, _entry_raw = _bounded_repo_source(entry_relative, ROOT_ENTRY_SOURCE_SHA256)
        pins[_path_key(entry_path)] = ROOT_ENTRY_SOURCE_SHA256
    if v4 is not None:
        _need(
            type(v4) is types.ModuleType
            and getattr(v4, "__verified_source_sha256__", None) == V4_SHA256
            and Path(v4.__file__) == ROOT / V4_REL,
            "v4_support_module_unpinned",
        )
        for path_name, digest_name in (
            ("R2_MODULE_REL", "R2_MODULE_SHA256"),
            ("PROFILER_PROOF_REL", "PROFILER_PROOF_SHA256"),
        ):
            path = getattr(v4, path_name, None)
            digest = getattr(v4, digest_name, None)
            _need(isinstance(path, Path) and _valid_sha(digest), "v4_support_pin_invalid")
            key = _path_key(path)
            prior = pins.get(key)
            _need(prior is None or prior == digest, "v4_support_pin_conflict")
            pins[key] = digest
    for key, digest in _predecessor_packet_review_pins().items():
        prior = pins.get(key)
        _need(prior is None or prior == digest, "r19_predecessor_support_pin_conflict")
        pins[key] = digest
    for key, digest in _r19_map_builder_support_pins().items():
        prior = pins.get(key)
        _need(prior is None or prior == digest, "r19_map_builder_support_pin_conflict")
        pins[key] = digest
    return pins


def _load_helper(reader):
    path = ROOT / R28_R5_REL
    raw = reader.read_pin(path, R28_R5_SHA256)
    _need(type(raw) is bytes, "r28_helper_bytes_missing")
    helper = _load_module(raw, path, "_iteration41_optional16_r33_entry_r28_r5")
    _need(
        getattr(helper, "__verified_source_sha256__", None) == R28_R5_SHA256
        and getattr(helper, "__file__", None) == str(path)
        and getattr(getattr(helper, "__spec__", None), "origin", None) == str(path),
        "r28_helper_load_origin_invalid",
    )
    helper.__r5_source_bytes__ = raw
    _need(_sha(raw) == R28_R5_SHA256, "r28_helper_hash_mismatch")
    return helper


def _sourcefake_image_check(_image, _private):
    """A fixed test-only leaf; this function never observes an image."""
    return None


def _sourcefake_cuv2_module_factory(name, path, raw, compiled):
    """Allow declaration of the pinned public CUV2 source without its Win32 entry."""
    _need(
        type(name) is str
        and name == "_root_r32_r2_enclosing_custody"
        and _path_key(path) == _path_key(CUV2_SOURCE_PATH)
        and type(raw) is bytes
        and _sha(raw) == CUV2_SOURCE_SHA256
        and type(compiled) is types.ModuleType
        and compiled.__name__ == name
        and getattr(compiled, "__verified_source_sha256__", None) == CUV2_SOURCE_SHA256
        and _path_key(getattr(compiled, "__file__", "")) == _path_key(CUV2_SOURCE_PATH),
        "sourcefake_cuv2_declaration_invalid",
    )
    return compiled


def _sourcefake_profiler_must_not_run(*_args, **_kwargs):
    raise RootHeldEntryError("sourcefake_profiler_gate_refused")


def _nested_source_code(function, name):
    _need(type(function) is types.FunctionType, "r27_nested_source_parent_invalid")
    matches = [
        value
        for value in function.__code__.co_consts
        if type(value) is types.CodeType and value.co_name == name
    ]
    _need(len(matches) == 1, "r27_nested_source_code_ambiguous")
    return matches[0]


def _closure_values(function):
    _need(type(function) is types.FunctionType, "r27_adapter_function_invalid")
    names = function.__code__.co_freevars
    cells = function.__closure__ or ()
    _need(len(names) == len(cells), "r27_adapter_closure_shape_invalid")
    result = {}
    for name, cell in zip(names, cells):
        try:
            result[name] = cell.cell_contents
        except ValueError:
            raise RootHeldEntryError("r27_adapter_empty_closure_cell") from None
    return result


def _validate_r27_r2_adaptation(invoke, r2, context, original_install, before):
    """Bind only the exact function/global mutations made by pinned R27."""
    _need(type(r2) is types.ModuleType, "r27_adapted_r2_module_invalid")
    _need(set(r2.__dict__) == set(before), "r27_adapted_r2_global_set_changed")
    allowed = {"need", "load", "save_new", "main"}
    for name, value in before.items():
        if name in allowed:
            continue
        _need(r2.__dict__.get(name) is value, "r27_adapted_r2_global_changed")

    wrapper_specs = (
        (
            "need",
            invoke._wrap_r2_need,
            "observed",
            {"context": context, "original": before["need"]},
            ("root_public_contract",),
        ),
        (
            "load",
            original_install,
            "adapted_load",
            {
                "context": context,
                "original_load": before["load"],
                "r2": r2,
                "r2_codes": context.get("diagnostic_source_codes"),
            },
            None,
        ),
        (
            "save_new",
            original_install,
            "adapted_save",
            {"context": context, "original_save": before["save_new"], "r2": r2},
            None,
        ),
    )
    for attr, owner, nested_name, expected_closure, defaults in wrapper_specs:
        function = getattr(r2, attr, None)
        expected_code = _nested_source_code(owner, nested_name)
        _need(
            type(function) is types.FunctionType
            and function.__code__ is expected_code
            and function.__globals__ is invoke.__dict__
            and function.__name__ == nested_name
            and function.__defaults__ == defaults
            and function.__kwdefaults__ is None
            and function.__annotations__ == {},
            "r27_adapted_r2_function_source_changed",
        )
        closure = _closure_values(function)
        _need(set(closure) == set(expected_closure), "r27_adapted_r2_closure_names_changed")
        _need(
            all(closure[name] is value for name, value in expected_closure.items()),
            "r27_adapted_r2_closure_binding_changed",
        )

    original_main = before.get("main")
    _need(type(original_main) is types.FunctionType, "r27_r2_main_baseline_invalid")
    code = original_main.__code__
    old_schema = invoke._R2_PARENT_SCHEMA_V1
    new_schema = invoke._R5_PARENT_SCHEMA_V1
    matches = [index for index, value in enumerate(code.co_consts) if type(value) is str and value == old_schema]
    _need(len(matches) == 1, "r27_r2_schema_source_anchor_invalid")
    constants = list(code.co_consts)
    constants[matches[0]] = new_schema
    expected_code = code.replace(co_consts=tuple(constants))
    _need(
        r2.main is original_main and r2.main.__code__ == expected_code,
        "r27_r2_schema_adaptation_changed",
    )


def _validate_r2_worker_projection(invoke, r2, before, *, main, rows, callback):
    additions = {"ROOT_HELD_WORKER_VIEW", "ROOT_R27_INVOKE"}
    _need(set(r2.__dict__) == set(before) | additions, "r2_worker_projection_global_set_changed")
    for name, value in before.items():
        if name == "main":
            continue
        _need(r2.__dict__.get(name) is value, "r2_worker_projection_source_global_changed")
    _need(
        r2.need is before["need"]
        and r2.load is before["load"]
        and r2.save_new is before["save_new"]
        and r2.main is main
        and type(main) is types.FunctionType
        and main.__globals__ is r2.__dict__
        and main.__defaults__ == before["main"].__defaults__
        and main.__kwdefaults__ == before["main"].__kwdefaults__
        and main.__code__.co_freevars == before["main"].__code__.co_freevars
        and r2.ROOT_HELD_WORKER_VIEW is rows
        and r2.ROOT_R27_INVOKE is invoke
        and invoke._record_profiler_verification is callback,
        "r2_worker_projection_binding_invalid",
    )


def _install_sourcefake_diagnostic_observer(helper, invoke, context):
    original = invoke.__dict__.get("_diagnostic_payload")
    _need(type(original) is types.FunctionType, "sourcefake_diagnostic_original_invalid")

    def observe(active_context, error):
        if active_context is context:
            label = invoke._exception_type_label(active_context, error)
            if type(label) is str and label.isascii() and label.isidentifier() and len(label) <= 64:
                active_context["sourcefake_exception_class"] = label
            if type(error) is NameError:
                value = getattr(error, "name", None)
                if type(value) is str and value.isascii() and value.isidentifier() and len(value) <= 96:
                    active_context["sourcefake_exception_name"] = value
            else:
                classes = active_context.get("diagnostic_exception_types")
                args = getattr(error, "args", ())
                if (
                    type(classes) is dict
                    and type(error) in classes
                    and type(args) is tuple
                    and len(args) == 1
                    and type(args[0]) is str
                    and args[0].isascii()
                    and args[0].replace("_", "").isalnum()
                    and len(args[0]) <= 96
                ):
                    active_context["sourcefake_exception_code"] = args[0]
        return original(active_context, error)

    wrapped = types.FunctionType(
        observe.__code__,
        invoke.__dict__,
        "_r5_sourcefake_diagnostic_observer",
        observe.__defaults__,
        observe.__closure__,
    )
    wrapped.__module__ = invoke.__name__
    wrapped.__qualname__ = "_r5_sourcefake_diagnostic_observer"
    wrapped.__annotations__ = {}
    invoke._diagnostic_payload = wrapped
    helper._advance_module_contract(
        invoke,
        {"_diagnostic_payload": wrapped},
        stage="r5_sourcefake_bounded_error_classification",
    )


def _execute_with_scope(
    scope,
    v4,
    payload_raw: bytes,
    *,
    require_production: bool,
    _sourcefake_token=None,
):
    _need(type(payload_raw) is bytes and 0 < len(payload_raw) <= MAX_METADATA_BYTES, "payload_bytes_invalid")
    try:
        payload = json.loads(payload_raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise RootHeldEntryError("payload_json_invalid") from None
    _need(type(payload) is dict, "payload_shape_invalid")
    _need(type(scope) is v4.RootHeldScopeV4 and scope.state == "OPEN", "scope_type_or_state_invalid")
    if require_production:
        _need(scope.test_only is False, "test_scope_rejected_for_production")
    reader = _ScopeReader(scope, v4)
    helper = _load_helper(reader)
    main_attestation_transform = _transform_r28_active_main_attestation(
        helper, helper_source_bytes(helper)
    )
    root_public_raw = reader.read_pin(ROOT / R25_PUBLIC_MAP_REL, R25_PUBLIC_MAP_SHA256)
    _need(type(root_public_raw) is bytes, "r25_public_map_bytes_unavailable")
    base = _parse_root_public_map(root_public_raw)
    payload_artifacts = _payload_artifact_pins(payload, _load_module(
        reader.read_pin(ROOT / R27_INVOKE_REL, R27_INVOKE_SHA256),
        ROOT / R27_INVOKE_REL,
        "_r5_payload_shape_invoke",
    ))
    # The source map JSON is read through its V4 handle; all 379 declarations
    # are then resolved from that exact metadata before any worker is created.
    base_rows = _binding_rows(base, category="public", prefix="r25-public")
    already = {_path_key(path): digest for path, digest in scope.manifest().items()}
    pending = [row for row in base_rows if already.get(_path_key(row["physical_path"])) != row["sha256"]]
    if pending:
        scope.resolve_and_hold(pending)
    reader._refresh()
    _need(reader.read_pin(ROOT / R25_PUBLIC_MAP_REL, R25_PUBLIC_MAP_SHA256) == root_public_raw,
          "r25_public_map_handle_changed")
    
    invoke_raw = reader.read_pin(ROOT / R27_INVOKE_REL, R27_INVOKE_SHA256)
    _need(type(invoke_raw) is bytes, "r27_invoke_source_unavailable")
    invoke = _load_module(invoke_raw, ROOT / R27_INVOKE_REL, "_r28_r5_root_held_invoke")
    helper._verify_loaded_module(invoke, invoke_raw, ROOT / R27_INVOKE_REL, invoke.__name__)
    _register_verified_module_alias(invoke, R27_INVOKE_SHA256)
    if _sourcefake_token is not None:
        reader.bind_sourcefake_active_driver_alias(invoke)
    whole_raw = reader.read_pin(ROOT / R27_WHOLE_REL, R27_WHOLE_SHA256)
    _need(type(whole_raw) is bytes, "r27_whole_source_unavailable")
    whole = _load_module(whole_raw, ROOT / R27_WHOLE_REL, "_r28_r5_root_held_whole")
    helper._verify_loaded_module(whole, whole_raw, ROOT / R27_WHOLE_REL, whole.__name__)
    deadline = payload.get("parent_deadline_monotonic")
    _need(type(deadline) is float and time.monotonic() < deadline, "payload_deadline_invalid")
    _need(payload == helper.build_child_payload(invoke, whole, deadline), "payload_not_parent_derived")
    payload_artifacts = _payload_artifact_pins(payload, invoke)
    missing_artifacts = {
        key: digest
        for key, digest in payload_artifacts.items()
        if {_path_key(p): h for p, h in scope.manifest().items()}.get(key) != digest
    }
    if missing_artifacts:
        scope.resolve_and_hold(_binding_rows(missing_artifacts, category="public", prefix="payload-artifact"))
        reader._refresh()

    driver_bind = payload["driver"]
    source_pins_path = Path(driver_bind["packet_dir"]) / "source-pins.json"
    source_pins_digest = driver_bind["packet_pins"]["source-pins.json"]
    held_source_pins = reader.read_pin(source_pins_path, source_pins_digest)
    _need(type(held_source_pins) is bytes, "r19_source_pins_handle_unavailable")
    held_source_members = _source_member_pins(held_source_pins)
    _need(
        all(payload_artifacts.get(path) == digest for path, digest in held_source_members.items()),
        "r19_source_members_not_in_payload_binding",
    )

    binding_rows = _scope_bindings(
        scope,
        _merge_pins(base, payload_artifacts, _support_pins(v4)),
        {key: "public" for key in _merge_pins(base, payload_artifacts, _support_pins(v4))},
    )
    # The owner-only R25/R19 source reader is already bound to one V4 scope.
    derivation = helper.derive_pinned_r19_active_map(
        payload,
        source_reader=reader.read_pin,
        artifact_reader=reader.read_artifact,
    )
    binding, active, software, aliases, derivation = helper.bind_child_activation_with_production_map(
        invoke,
        payload,
        derivation=derivation,
        active_pins=derivation.pins,
        active_software_pins=derivation.software,
        active_aliases=derivation.aliases,
        artifact_reader=reader.read_artifact,
        source_reader=reader.read_pin,
    )
    _need(binding.get("activation_enabled") is True, "r27_child_binding_not_enabled")
    active = _normalize_pins(active, "r27_bound_active_map_invalid")
    software = _normalize_pins(software, "r27_bound_software_map_invalid")
    _need(active == _normalize_pins(derivation.pins, "r19_derived_active_map_invalid"),
          "r27_bound_active_map_not_exact")
    _need(software == _normalize_pins(derivation.software, "r19_derived_software_map_invalid"),
          "r27_bound_software_map_not_exact")
    _need(aliases == derivation.aliases == 19, "r27_bound_alias_count_invalid")
    _need(len(active) == 575 and len(software) == 5, "r27_bound_map_sizes_invalid")

    # Inactive R19 production source derives the base cold map. R15's exact
    # `main` prefix then derives the 515-row base request before CUV2 custody.
    r19_raw = reader.read_pin(ROOT / R19_DRIVER_REL, R19_DRIVER_SHA256)
    _need(type(r19_raw) is bytes, "r19_source_unavailable")
    inactive = _load_module(r19_raw, ROOT / R19_DRIVER_REL, "_r5_owner_r19_inert_map")
    helper._verify_loaded_module(inactive, r19_raw, ROOT / R19_DRIVER_REL, inactive.__name__)
    inactive._read_pin = reader.read_pin
    cold_base, cold_software, cold_aliases = inactive._expected_pins()
    _need(type(cold_base) is dict and type(cold_software) is dict, "r19_inert_map_invalid")
    _need(type(cold_aliases) is int and cold_aliases >= 0, "r19_inert_alias_count_shape_invalid")
    cold_base_norm = _normalize_pins(cold_base, "r19_cold_public_map_invalid")
    cold_soft_norm = _normalize_pins(cold_software, "r19_cold_software_map_invalid")
    _need(cold_soft_norm == _normalize_pins(software, "active_software_map_invalid"),
          "r19_cold_software_binding_changed")
    current_manifest = {_path_key(path): digest for path, digest in scope.manifest().items()}
    pending_cold = {key: digest for key, digest in cold_base_norm.items() if current_manifest.get(key) != digest}
    pending_soft = {key: digest for key, digest in cold_soft_norm.items() if current_manifest.get(key) != digest}
    if pending_cold:
        scope.resolve_and_hold(_binding_rows(pending_cold, category="public", prefix="r19-cold"))
    if pending_soft:
        scope.resolve_and_hold(_binding_rows(pending_soft, category="software", prefix="r19-cold-software"))
    reader._refresh()

    r2_raw = reader.read_pin(ROOT / R2_GLUE_REL, R2_GLUE_SHA256)
    _need(type(r2_raw) is bytes, "r15_glue_source_unavailable")
    r2_globals = {
        "SOURCE": invoke.DRIVER,
        "SOURCE_SHA": invoke.DRIVER_SHA256,
        "ACTIVE_SOURCE": invoke._driver_active_path(),
        "TEST": invoke.DRIVER_TEST,
        "TEST_SHA": invoke.DRIVER_TEST_SHA256,
        "PACKET": invoke.DRIVER_PACKET,
        "PACKET_PINS": {name: invoke.DRIVER_PACKET_PINS[name] for name in invoke._PACKET_REQUIRED},
        "REVIEW": invoke.DRIVER_REVIEW,
        "ROOT_REVIEW_PINS": {
            name: invoke.DRIVER_REVIEW_PINS[name] for name in invoke._R2_REVIEW_MAP_REQUIRED
        },
        "ROOT_REVIEW_README_SHA": invoke.DRIVER_REVIEW_PINS["README.md"],
        "ROOT_ACTUAL_ENABLED": True,
        "ROOT_REVIEW_READY": True,
        "_ROOT_SELF_SHA256": R2_GLUE_SHA256,
        "CONTROL": invoke.ROOT_CONTROL,
        "OUT": invoke.ROOT_OUTPUT,
        "APPLICATION_WAIT_SECONDS": invoke.OUTER_WAIT_SECONDS,
        "PARENT_DEADLINE_MONOTONIC": invoke.PARENT_DEADLINE_MONOTONIC,
        "PARENT_DEADLINE_DOMAIN": invoke.PARENT_DEADLINE_DOMAIN,
        "INERT_PIN_COUNT": invoke.R2_INERT_DRIVER_PIN_COUNT,
        "ACTIVE_PIN_COUNT": invoke.ACTIVE_DRIVER_PUBLIC_PATH_COUNT,
        "ACTIVE_ALIAS_COUNT": invoke.ACTIVE_DRIVER_ALIAS_COUNT,
    }
    cold_515, cold_software_actual = _transform_r2_cold_projection(
        r2_raw, ROOT / R2_GLUE_REL, reader, r2_globals
    )
    cold_norm = _normalize_pins(cold_515, "r2_cold_map_invalid")
    cold_soft_actual = _normalize_pins(cold_software_actual, "r2_cold_software_invalid")
    _need(cold_soft_actual == cold_soft_norm, "r2_cold_software_differs_from_r19")

    outer = _normalize_pins(invoke._extra_pins("actual"), "r27_outer_pin_map_invalid")
    cold_with_outer = dict(cold_norm)
    for key, digest in outer.items():
        prior = cold_with_outer.get(key)
        _need(prior is None or prior == digest, "r2_outer_map_conflict")
        cold_with_outer[key] = digest
    full, metrics = helper.build_full_hold_map(
        cold_with_outer,
        active,
        outer,
        cold_soft_actual,
        software,
        active_aliases=aliases,
    )
    full = _normalize_pins(full, "full_public_map_invalid")
    software = _normalize_pins(software, "full_software_map_invalid")
    _need(type(metrics) is dict, "full_hold_metrics_invalid")
    expected_full = dict(active)
    for key, digest in cold_with_outer.items():
        prior = expected_full.get(key)
        _need(prior is None or prior == digest, "active_outer_pin_conflict")
        expected_full[key] = digest
    _need(full == expected_full, "full_hold_map_not_active_outer_union")
    _need(
        len(cold_norm) == 515
        and len(outer) == 14
        and len(set(cold_norm) & set(outer)) == 11
        and len(cold_with_outer) == 518
        and len(full) == 582
        and len(set(active) - set(cold_with_outer)) == 64
        and len(set(cold_with_outer) - set(active)) == 7,
        "source_derived_map_metrics_invalid",
    )
    _need(metrics.get("cold_request_paths") == len(cold_with_outer), "cold_request_metric_mismatch")
    _need(metrics.get("validated_active_paths") == len(active), "active_map_metric_mismatch")
    _need(metrics.get("active_missing_from_cold") == len(set(active) - set(cold_with_outer)),
          "active_difference_metric_mismatch")
    _need(metrics.get("outer_only_paths") == len(set(cold_with_outer) - set(active)),
          "outer_difference_metric_mismatch")

    full_union = _merge_pins(full, payload_artifacts, _support_pins(v4))
    manifest = {_path_key(path): digest for path, digest in scope.manifest().items()}
    need_public = {key: digest for key, digest in full_union.items() if manifest.get(key) != digest}
    need_software = {key: digest for key, digest in software.items() if manifest.get(key) != digest}
    if need_public:
        scope.resolve_and_hold(_binding_rows(need_public, category="public", prefix="r5-full-public"))
    if need_software:
        scope.resolve_and_hold(_binding_rows(need_software, category="software", prefix="r5-full-software"))
    reader._refresh()
    rows = _scope_bindings(scope, full_union, {key: "public" for key in full_union})
    rows.update(_scope_bindings(scope, software, {key: "software" for key in software}))
    _need(set(rows) == set(full_union) | set(software), "held_row_manifest_not_full_union")
    _need(all(rows[key][0] == digest for key, digest in full_union.items()),
          "held_public_manifest_digest_mismatch")
    _need(all(rows[key][0] == digest for key, digest in software.items()),
          "held_software_manifest_digest_mismatch")

    if _sourcefake_token is _SOURCEFAKE_TEST_TOKEN:
        _need(scope.test_only is True, "sourcefake_profiler_scope_not_fake")
        # The agent-side sourcefake run is allowed to verify the full source
        # map and reach this boundary. It must not invoke the opaque .pyc
        # proof consumer or synthesize its acceptance result.
        _sourcefake_profiler_must_not_run()

    # Owner-only V4 verification runs before worker creation. Only fixed
    # metadata rows and success booleans leave the V4 cache consumer.
    v4_r2_raw = reader.read_pin(v4.R2_MODULE_REL, v4.R2_MODULE_SHA256)
    proof_raw = reader.read_pin(v4.PROFILER_PROOF_REL, v4.PROFILER_PROOF_SHA256)
    _need(type(v4_r2_raw) is bytes and type(proof_raw) is bytes, "v4_profiler_source_missing")
    v4_r2 = _load_module(v4_r2_raw, Path(str(v4.R2_MODULE_REL)), v4.R2_MODULE_NAME)
    proof = _load_module(proof_raw, Path(str(v4.PROFILER_PROOF_REL)), v4.PROFILER_PROOF_MODULE_NAME)
    profiler_rows = {
        name: scope.verify_profiler_module_cache(proof, v4_r2, name)
        for name in sorted(v4.PROFILER_SOURCE_PINS)
    }
    _need(set(profiler_rows) == set(v4.PROFILER_SOURCE_PINS), "v4_profiler_result_set_invalid")
    profiler_projection = MappingProxyType(
        {name: MappingProxyType(dict(row)) for name, row in profiler_rows.items()}
    )
    support_public = {key: digest for key, digest in full_union.items() if key not in full}
    view = _make_snapshot(scope, full, support_public, software, rows, profiler_rows, metrics)
    _need(dict(view.public_pins) == full, "worker_view_public_map_not_exact")
    _need(dict(view.support_pins) == support_public, "worker_view_support_map_not_exact")
    _need(dict(view.software_pins) == software, "worker_view_software_map_not_exact")

    _transform_deferred_scope(helper, invoke, invoke_raw, view)
    _transform_r28_worker_installer(helper, helper_source_bytes(helper), view)
    helper.install_full_hold_adaptation(invoke, context := {"mode": "actual"})
    context["r28_active_main_attestation_transform"] = main_attestation_transform
    review_required = helper.derive_review_required_paths(invoke)
    _need(
        type(review_required) is set
        and len(review_required) == 64
        and review_required <= set(full_union),
        "source_derived_review_required_set_invalid",
    )
    context["review_required_paths"] = review_required
    if _sourcefake_token is not None:
        _need(
            _sourcefake_token is _SOURCEFAKE_TEST_TOKEN
            and require_production is False
            and scope.test_only is True,
            "sourcefake_worker_token_invalid",
        )
        # `run()` has no route to this test-only branch and requires a
        # production V4 scope. The worker still traverses the frozen actual
        # dispatcher; only fixed image/profiler bottom leaves are fake.
        context["source_fake_mode"] = True
        context["source_fake_cu_module_factory"] = _sourcefake_cuv2_module_factory
        context["fake_image_check"] = _sourcefake_image_check
        context["fake_profiler_verifier"] = _sourcefake_profiler_must_not_run
        context["diagnostic_exception_types"] = {
            RootHeldEntryError: "RootHeldEntryError",
            helper.SourceContractError: "SourceContractError",
            AttributeError: "AttributeError",
            AssertionError: "AssertionError",
            IndexError: "IndexError",
            NameError: "NameError",
            StopIteration: "StopIteration",
        }
    helper._install_module_global_binding(
        invoke,
        "_read_fixed",
        view.read_fixed,
        stage="r5_owner_held_worker_fixed_reader",
    )
    _install_worker_r27_loader(helper, invoke, invoke_raw, view)
    if _sourcefake_token is _SOURCEFAKE_TEST_TOKEN:
        _install_sourcefake_diagnostic_observer(helper, invoke, context)

    original_install = invoke._install_adaptation
    transform_profiler_consumer = _transform_r2_profiler_consumer

    def install_with_profiler_view(r2, active_context):
        before = dict(r2.__dict__)
        derivation = active_context.get("r19_derivation")
        bound_record = helper._bound_invoke_record(invoke, derivation)
        active_rows = dict(bound_record.get("active_rows", ()))
        software_rows = dict(bound_record.get("software_rows", ()))
        aliases = bound_record.get("aliases")
        invoke._need(
            active_rows == dict(derivation.pins)
            and software_rows == dict(derivation.software)
            and type(aliases) is int
            and aliases == derivation.aliases,
            "r27_active_map_context_binding_changed",
        )
        active_context["validated_active_pins"] = active_rows
        active_context["validated_active_software"] = software_rows
        active_context["validated_active_aliases"] = aliases

        def record_profiler_verification(active_context, name, row):
            invoke._need(
                type(active_context) is dict
                and type(name) is str
                and type(profiler_projection.get(name)) is type(profiler_projection)
                and row is profiler_projection.get(name),
                "root_profiler_projection_unbound",
            )
            count = active_context.get("profiler_cache_verify_count")
            expected_count = active_context.get("profiler_cache_expected_count")
            invoke._need(
                type(count) is int
                and type(expected_count) is int
                and expected_count == len(profiler_projection)
                and 0 <= count < expected_count,
                "root_profiler_projection_count_invalid",
            )
            active_context["profiler_cache_verify_count"] = count + 1
            invoke._set_diagnostic_phase(active_context, "profiler_cache_verify")
            if count + 1 == expected_count:
                invoke._set_diagnostic_phase(active_context, "profiler_cache_verified")

        record_code = types.FunctionType(
            record_profiler_verification.__code__,
            invoke.__dict__,
            "_record_profiler_verification",
            record_profiler_verification.__defaults__,
            record_profiler_verification.__closure__,
        )
        record_code.__module__ = invoke.__name__
        record_code.__qualname__ = "_record_profiler_verification"
        record_code.__kwdefaults__ = record_profiler_verification.__kwdefaults__
        record_code.__annotations__ = dict(record_profiler_verification.__annotations__)
        callback = types.MethodType(record_code, active_context)
        invoke._record_profiler_verification = callback

        wrapper = types.FunctionType(
            install_with_profiler_view.__code__,
            invoke.__dict__,
            install_with_profiler_view.__name__,
            install_with_profiler_view.__defaults__,
            install_with_profiler_view.__closure__,
        )
        wrapper.__module__ = invoke.__name__
        wrapper.__qualname__ = install_with_profiler_view.__qualname__
        wrapper.__kwdefaults__ = install_with_profiler_view.__kwdefaults__
        wrapper.__annotations__ = dict(install_with_profiler_view.__annotations__)
        wrapper.__dict__.update(install_with_profiler_view.__dict__)
        invoke._install_adaptation = wrapper
        _need(
            invoke._record_profiler_verification is callback,
            "root_profiler_callback_module_binding_invalid",
        )
        helper._advance_module_contract(
            invoke,
            {"_install_adaptation": wrapper},
            stage="r5_owner_profiler_result_projection",
        )
        original_install(r2, active_context)
        helper._assert_module_contract(r2)
        worker_baseline = dict(r2.__dict__)
        transform_profiler_consumer(
            helper,
            invoke,
            r2,
            active_context.get("r2_raw"),
            profiler_projection,
            callback,
            worker_baseline,
        )

    invoke._install_adaptation = install_with_profiler_view

    thread_result: dict[str, object] = {
        "code": None,
        "error_type": None,
        "error_key": None,
        "joined": False,
    }

    def worker():
        try:
            thread_result["code"] = invoke._r2_main("actual", context)
            if _sourcefake_token is _SOURCEFAKE_TEST_TOKEN:
                for name in (
                    "sourcefake_exception_class",
                    "sourcefake_exception_name",
                    "sourcefake_exception_code",
                ):
                    value = context.get(name)
                    if type(value) is str and value.isascii() and value.replace("_", "").isalnum() and len(value) <= 96:
                        thread_result[name] = value
        except BaseException as error:
            thread_result["error_type"] = type(error).__name__
            if type(error) is KeyError and len(error.args) == 1:
                value = error.args[0]
                if type(value) is str and value.isascii() and value.isidentifier() and len(value) <= 64:
                    thread_result["error_key"] = value
            if _sourcefake_token is _SOURCEFAKE_TEST_TOKEN and type(error) is AttributeError:
                value = getattr(error, "name", None)
                if type(value) is str and value.isascii() and value.isidentifier() and len(value) <= 64:
                    thread_result["sourcefake_error_attribute"] = value
            if _sourcefake_token is _SOURCEFAKE_TEST_TOKEN and type(error) is NameError:
                value = getattr(error, "name", None)
                if type(value) is str and value.isascii() and value.isidentifier() and len(value) <= 64:
                    thread_result["sourcefake_error_name"] = value
            source_error_type = helper.__dict__.get("SourceContractError")
            if (
                _sourcefake_token is _SOURCEFAKE_TEST_TOKEN
                and type(source_error_type) is type
                and type(error) is source_error_type
                and len(error.args) == 1
            ):
                value = error.args[0]
                if (
                    type(value) is str
                    and value.isascii()
                    and value.replace("_", "").isalnum()
                    and len(value) <= 96
                ):
                    thread_result["sourcefake_error_code"] = value
            if (
                _sourcefake_token is _SOURCEFAKE_TEST_TOKEN
                and type(error) is RootHeldEntryError
                and len(error.args) == 1
            ):
                value = error.args[0]
                if (
                    type(value) is str
                    and value.isascii()
                    and value.replace("_", "").isalnum()
                    and len(value) <= 96
                ):
                    thread_result["sourcefake_entry_error_code"] = value

    deadline = payload.get("parent_deadline_monotonic")
    _need(type(deadline) is float, "worker_deadline_invalid")
    timeout = max(0.0, min(100.0, deadline - time.monotonic()))
    thread = threading.Thread(target=worker, name="optional16-r33-root-held-entry-r1", daemon=True)
    reader.bind_worker_snapshot(view, thread)
    retained = (scope, view, invoke, helper, context, thread, thread_result, reader)
    thread.start()
    thread.join(timeout)
    thread_result["joined"] = not thread.is_alive()
    if thread.is_alive():
        _RETAINED.append(retained)
        scope.release(2, False)
        return {
            "schema": ENTRY_SCHEMA,
            "status": "WORKER_UNJOINED_RETAINED",
            "worker_joined": False,
            "scope_released": False,
            "strict_cases_passed": 0,
            "case_pass": False,
            "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        }
    code = thread_result.get("code")
    clean = type(code) is int and code == 0 and context.get("clean") is True and not thread_result.get("error_type")
    observed_phase = context.get("diagnostic_phase")
    if type(observed_phase) is not str or observed_phase not in invoke._DIAGNOSTIC_PHASES:
        observed_phase = "UNOBSERVED"
    if clean:
        released = scope.release(code, True)
        if released:
            return {
                "schema": ENTRY_SCHEMA,
                "status": "WORKER_CLEAN_POSTVERIFIED",
                "worker_joined": True,
                "scope_released": True,
                "strict_cases_passed": 0,
                "case_pass": False,
                "acceptance": "NOT_ACCEPTED_OPTIONAL16",
            }
    scope.release(2 if type(code) is not int else code, False)
    _RETAINED.append(retained)
    return {
        "schema": ENTRY_SCHEMA,
        "status": "WORKER_UNCERTAIN_RETAINED",
        "worker_joined": True,
        "worker_exit_code": code if type(code) is int else None,
        "worker_error_type": thread_result.get("error_type"),
        "worker_error_key": thread_result.get("error_key"),
        "sourcefake_error_attribute": thread_result.get("sourcefake_error_attribute"),
        "sourcefake_error_name": thread_result.get("sourcefake_error_name"),
        "sourcefake_error_code": thread_result.get("sourcefake_error_code"),
        "sourcefake_entry_error_code": thread_result.get("sourcefake_entry_error_code"),
        "sourcefake_exception_class": thread_result.get("sourcefake_exception_class"),
        "sourcefake_exception_name": thread_result.get("sourcefake_exception_name"),
        "sourcefake_exception_code": thread_result.get("sourcefake_exception_code"),
        "worker_phase": observed_phase,
        "scope_released": False,
        "strict_cases_passed": 0,
        "case_pass": False,
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
    }


def _bootstrap_scope(v4, payload_raw: bytes):
    try:
        payload = json.loads(payload_raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise RootHeldEntryError("payload_json_invalid") from None
    _need(type(payload) is dict, "payload_shape_invalid")
    public_path, public_raw = _bounded_repo_source(R25_PUBLIC_MAP_REL, R25_PUBLIC_MAP_SHA256, MAX_METADATA_BYTES)
    public = _parse_root_public_map(public_raw)
    payload_probe = _load_module(
        _bounded_repo_source(R27_INVOKE_REL, R27_INVOKE_SHA256)[1],
        ROOT / R27_INVOKE_REL,
        "_r5_bootstrap_invoke_shape",
    )
    payload_pins = _payload_artifact_pins(payload, payload_probe)
    support = _support_pins(v4)
    public[_path_key(public_path)] = R25_PUBLIC_MAP_SHA256
    pins = _merge_pins(public, payload_pins, support)
    scope = v4.RootHeldScopeV4(_binding_rows(pins, category="public", prefix="r5-entry-bootstrap"), enabled=True)
    scope.__enter__()
    _need(scope.test_only is False, "production_sourcefake_scope_rejected")
    return scope


def run(payload_raw: bytes):
    """Run only after Root fills the external source-packet pin and enable slot."""
    _need(ROOT_ACTUAL_ENABLED is True, "root_entry_activation_closed")
    _need(_valid_sha(ROOT_ENTRY_SOURCE_SHA256), "root_entry_source_pin_unset")
    entry_path = Path(__file__)
    entry_raw = _bounded_repo_source(Path(os.path.relpath(entry_path, ROOT)), ROOT_ENTRY_SOURCE_SHA256)[1]
    _need(_sha(entry_raw) == ROOT_ENTRY_SOURCE_SHA256, "root_entry_source_changed")
    v4, _v4_raw = _load_v4_module()
    scope = _bootstrap_scope(v4, payload_raw)
    try:
        return _execute_with_scope(scope, v4, payload_raw, require_production=True)
    except BaseException:
        scope.release(2, False)
        _RETAINED.append((scope, payload_raw, v4))
        raise


__all__ = (
    "ENTRY_SCHEMA",
    "ROOT_ACTUAL_ENABLED",
    "ROOT_ENTRY_SOURCE_SHA256",
    "RootHeldEntryError",
    "RootHeldWorkerSnapshot",
    "run",
)
