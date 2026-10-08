"""Source-fake integration for the canonical M01 R2 reader successor.

The old R2 source archive is an immutable fixture for the frozen source-close
tests. Its relocated imports are used only as source-fake inputs and never as
evidence of the deployed runtime origin.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
VENUE = ROOT / "examples/000_live_certification/okx_penetration"
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
OLD_PACKET = (
    EVIDENCE / "iteration41-okx-m01-v3-reason-preservation-r2-selected-source-qa-r4-2026-10-09"
)
OLD_SOURCE_ZIP = OLD_PACKET / "source.zip"
OLD_SOURCE_ZIP_SHA256 = "fb319aa4b066a839dc8681d2ac30897374bece35d90bf29d6c26b28c40b7ee35"
OLD_SOURCE_MAP_SHA256 = "db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3"
OLD_READER_SHA256 = "b350e0d0110a3c87f6fc44a841b9df12e229eff2efac1060d66b598c17cbc734"
NEW_READER_SHA256 = "5a8fd479c999279d9efde625cac1938d794201f04e1beaa6f3663b267d7a7ebc"
NEW_ENTRY_SHA256 = "e0613b66fa54d5ea155da263d1e901e8ada78adf7d83a7e1c8dc5430ea440d1e"
NEW_RUN_SHA256 = "d498e32fcb573781a3eec25eff4c7ba98bfe2c8d4d94f9e5a9b078ab4074641e"
NEW_MAP_SHA256 = "07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3"
NEW_MAP_PATH = (
    EVIDENCE
    / "iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09"
    / "source-map.json"
)
READER_RELATIVE = (
    "examples/000_live_certification/okx_penetration/" "_m01_readonly_monitor_v3/current_reader.py"
)
ENTRY_RELATIVE = (
    "examples/000_live_certification/okx_penetration/" "_m01_readonly_monitor_v3/entry.py"
)
RUN_RELATIVE = "examples/000_live_certification/okx_penetration/cases/M01/run.py"
READER_MEMBER = READER_RELATIVE
_MODULE_PREFIXES = (
    "_certification",
    "_m01_readonly_monitor_v2",
    "_m01_readonly_monitor_v3",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bounded_read(path: Path, maximum: int) -> bytes:
    size = path.stat().st_size
    assert 0 <= size <= maximum
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    assert len(raw) == size and len(raw) <= maximum
    return raw


def _source_map_keys(reader_source: bytes) -> set[str]:
    tree = ast.parse(reader_source.decode("utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "SOURCE_MAP_RELATIVES"
            for target in node.targets
        ):
            continue
        assert isinstance(node.value, ast.Call)
        assert isinstance(node.value.func, ast.Name) and node.value.func.id == "frozenset"
        return set(ast.literal_eval(node.value.args[0]))
    raise AssertionError("reader_source_map_relatives_missing")


def _load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _write_archive_tree(raw: bytes, destination: Path) -> dict[str, bytes]:
    assert _sha(raw) == OLD_SOURCE_ZIP_SHA256
    extracted = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        assert len(names) == 20 and len(set(names)) == len(names)
        for name in names:
            member = PurePosixPath(name)
            assert not member.is_absolute() and all(
                part not in ("", ".", "..") for part in member.parts
            )
            assert "\\" not in name and ":" not in name
            data = archive.read(name)
            assert len(data) <= 10 * 1024 * 1024
            target = destination.joinpath(*member.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            extracted[name] = data
    assert READER_MEMBER in extracted
    assert len(extracted[READER_MEMBER]) == 63711
    assert _sha(extracted[READER_MEMBER]) == OLD_READER_SHA256
    return extracted


def test_current_map_and_fixed_entry_chain_bind_the_transformed_reader():
    source_map_raw = _bounded_read(NEW_MAP_PATH, 256 * 1024)
    assert len(source_map_raw) == 2877
    assert _sha(source_map_raw) == NEW_MAP_SHA256
    source_map = json.loads(source_map_raw.decode("ascii"))
    canonical = json.dumps(
        source_map, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    assert source_map_raw == canonical + b"\n"
    pins = source_map["source_pins"]

    reader_raw = _bounded_read(ROOT / READER_RELATIVE, 256 * 1024)
    entry_raw = _bounded_read(ROOT / ENTRY_RELATIVE, 64 * 1024)
    run_raw = _bounded_read(ROOT / RUN_RELATIVE, 64 * 1024)
    assert _sha(reader_raw) == NEW_READER_SHA256
    assert _sha(entry_raw) == NEW_ENTRY_SHA256
    assert _sha(run_raw) == NEW_RUN_SHA256
    assert set(pins) == _source_map_keys(reader_raw)
    assert len(pins) == 19
    assert pins[READER_RELATIVE] == NEW_READER_SHA256
    assert pins[ENTRY_RELATIVE] == NEW_ENTRY_SHA256
    assert pins[RUN_RELATIVE] == NEW_RUN_SHA256
    for relative, digest in pins.items():
        assert _sha(_bounded_read(ROOT / relative, 2 * 1024 * 1024)) == digest

    old_map_raw = _bounded_read(OLD_PACKET / "source-map.json", 256 * 1024)
    assert _sha(old_map_raw) == OLD_SOURCE_MAP_SHA256
    old_pins = json.loads(old_map_raw.decode("ascii"))["source_pins"]
    assert set(old_pins) == set(pins)
    changed = {path for path in pins if old_pins[path] != pins[path]}
    assert changed == {READER_RELATIVE, ENTRY_RELATIVE, RUN_RELATIVE}
    assert NEW_READER_SHA256.encode("ascii") in entry_raw
    assert NEW_ENTRY_SHA256.encode("ascii") in run_raw


def test_archived_r2_reader_still_satisfies_frozen_source_close_binding(tmp_path, monkeypatch):
    archive_raw = _bounded_read(OLD_SOURCE_ZIP, 2 * 1024 * 1024)
    source_root = tmp_path / "historical-r2-source"
    archived = _write_archive_tree(archive_raw, source_root)

    reconciliation_path = (
        ROOT / "scripts/iteration41_okx_m01_local_source_lease_reconciliation_r7.py"
    )
    reconciliation = _load_module_from_path(
        "_m01_source_close_historical_fixture_r8", reconciliation_path
    )
    monkeypatch.setattr(reconciliation, "ROOT", source_root)

    previous = {
        name: module
        for name, module in sys.modules.items()
        if any(name == prefix or name.startswith(prefix + ".") for prefix in _MODULE_PREFIXES)
    }
    for name in tuple(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in _MODULE_PREFIXES):
            del sys.modules[name]
    archive_venue = source_root / "examples/000_live_certification/okx_penetration"
    monkeypatch.syspath_prepend(str(archive_venue))
    monkeypatch.syspath_prepend(str(source_root))
    importlib.invalidate_caches()
    try:
        reader = importlib.import_module("_m01_readonly_monitor_v3.current_reader")
        assert _sha(archived[READER_MEMBER]) == reconciliation.READER_SOURCE_SHA256
        assert reconciliation._verify_module(
            reader,
            archived[READER_MEMBER],
            reconciliation.READER_RELATIVE,
            reconciliation.READER_SOURCE_BYTES,
            reconciliation.READER_SOURCE_SHA256,
            ("_root_helper_wrapper", "_run_pinned_root_helper"),
        ) == (source_root / reconciliation.READER_RELATIVE).resolve(strict=True)
    finally:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in _MODULE_PREFIXES):
                del sys.modules[name]
        sys.modules.update(previous)


def test_archived_reader_transform_and_v2_supervised_gate_remain_fake_only(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("the source-bound M01 lifecycle gate is Windows-only")

    archive_raw = _bounded_read(OLD_SOURCE_ZIP, 2 * 1024 * 1024)
    historical_root = tmp_path / "historical-r2-source"
    _write_archive_tree(archive_raw, historical_root)
    historical_venue = historical_root / "examples/000_live_certification/okx_penetration"

    r7_test_path = (
        ROOT / "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r7.py"
    )
    r7_test = _load_module_from_path("_m01_lifecycle_gate_r7_historical_fixture_r8", r7_test_path)
    monkeypatch.setattr(r7_test, "VENUE", historical_venue)
    fixture_generator = r7_test.patched_source_modules.__wrapped__(tmp_path, monkeypatch)
    modules = next(fixture_generator)
    try:
        reader, supervisor, worker = modules
        kernel = r7_test.fake_leaves._FakeKernel(supervisor)
        monkeypatch.setattr(
            supervisor.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel, raising=False
        )
        monkeypatch.setattr(
            supervisor.ctypes, "get_last_error", kernel.get_last_error, raising=False
        )
        monkeypatch.setattr(
            supervisor,
            "_hold_runtime_files",
            lambda _kernel, _deadline: {"runtime_handles": set()},
        )
        r7_test.test_gate_runs_exact_transformed_reader_module_through_v2_fake_leaves(
            modules, kernel, monkeypatch
        )
        assert (
            hashlib.sha256(_bounded_read(ROOT / READER_RELATIVE, 256 * 1024)).hexdigest()
            == NEW_READER_SHA256
        )
    finally:
        fixture_generator.close()
