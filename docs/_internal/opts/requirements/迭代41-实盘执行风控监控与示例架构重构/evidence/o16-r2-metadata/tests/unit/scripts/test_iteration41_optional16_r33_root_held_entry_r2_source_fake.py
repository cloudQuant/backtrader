"""Metadata-only contracts for the additive Optional16 root-held entry R2."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "scripts/iteration41_optional16_r33_root_held_entry_r2.py"
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
STDLIB_INDEX = EVIDENCE / "iteration41-optional16-public-profiler-stdlib-opaque-snapshot-r1-2026-10-08/index.json"
CACHE_INDEX = EVIDENCE / "iteration41-optional16-public-profiler-cache-opaque-snapshot-r1-2026-10-08/index.json"


def _load_exact(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("sourcefake_module_spec_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ENTRY = _load_exact("iteration41_optional16_root_held_entry_r2_metadata_test", ENTRY_PATH)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _key(path: str) -> str:
    return ENTRY._path_key(path)


def _read_pinned_json(path: Path, digest: str) -> dict:
    raw = path.read_bytes()
    assert _sha(raw) == digest
    value = json.loads(raw.decode("utf-8", "strict"))
    assert type(value) is dict
    return value


def _fixed_error(code: str, callback) -> None:
    with pytest.raises(ENTRY.RootHeldEntryError) as caught:
        callback()
    assert caught.value.args == (code,)


class _MetadataOnlyScope:
    def __init__(self, held: dict[str, bytes]):
        self.private = object()
        self.cli = object()
        self.held = held
        self.reads: list[tuple[str, str, int]] = []
        self.verifications: list[tuple[str, str]] = []

    def read_held(self, path, digest, maximum):
        key = _key(path)
        self.reads.append((key, digest, maximum))
        return self.held[key]

    def verify_pin(self, path, digest):
        self.verifications.append((_key(path), digest))
        return True


def _snapshot_inputs(ordinary_raw: bytes = b"ordinary public python source\n"):
    ordinary_path = r"C:\fixture\ordinary_public.py"
    ordinary_digest = _sha(ordinary_raw)
    ordinary_key = _key(ordinary_path)
    software = {}
    rows = {ordinary_key: (ordinary_digest, "public", ENTRY.MAX_SOURCE_BYTES)}
    for path, digest, size, _role in ENTRY.PROFILER_STDLIB_OPAQUE_ROWS:
        key = _key(path)
        software[key] = digest
        rows[key] = (digest, "software", ENTRY._row_limit(path))
    scope = _MetadataOnlyScope({ordinary_key: ordinary_raw})
    return scope, ordinary_path, ordinary_digest, software, rows


def test_fixed_indexes_bind_exact_transport_only_profiler_descriptors():
    stdlib = _read_pinned_json(STDLIB_INDEX, ENTRY.PROFILER_STDLIB_SNAPSHOT_INDEX_SHA256)
    assert stdlib["schema"] == ENTRY.PROFILER_STDLIB_SNAPSHOT_SCHEMA
    assert stdlib["classification"] == ENTRY.PROFILER_STDLIB_SNAPSHOT_CLASSIFICATION
    assert stdlib["artifact_executed"] is False
    assert stdlib["private_inputs_read"] is False
    assert stdlib["provider_operations"] == 0
    assert len(stdlib["rows"]) == 3
    indexed_stdlib = tuple(
        (
            row["logical_path"],
            row["sha256"],
            row["size_bytes"],
            row["allowed_review"],
        )
        for row in stdlib["rows"]
    )
    assert indexed_stdlib == ENTRY.PROFILER_STDLIB_OPAQUE_ROWS

    cache = _read_pinned_json(CACHE_INDEX, ENTRY.PROFILER_CACHE_SNAPSHOT_INDEX_SHA256)
    assert cache["schema"] == ENTRY.PROFILER_CACHE_SNAPSHOT_SCHEMA
    assert cache["cache_unmarshaled_or_imported"] is False
    assert cache["private_account_or_capture_inputs_read"] is False
    assert len(cache["snapshot_rows"]) == 3
    indexed_cache = tuple(
        (
            _key(row["source_path_metadata_only"]),
            row["sha256"],
            row["size_bytes"],
            row["role"],
        )
        for row in cache["snapshot_rows"]
    )
    expected_cache = tuple(
        (_key(path), digest, size, role)
        for path, digest, size, role in ENTRY.PROFILER_CACHE_OPAQUE_ROWS
    )
    assert indexed_cache == expected_cache
    for path, digest, size, role in ENTRY.PROFILER_CACHE_OPAQUE_ROWS:
        assert ENTRY._metadata_opaque_descriptor(path, digest, size, role) is True
        assert ENTRY._is_opaque_pin(path, digest, "public", ENTRY._row_limit(path)) is True


def test_snapshot_keeps_only_the_three_indexed_profiler_sources_opaque():
    scope, ordinary_path, ordinary_digest, software, rows = _snapshot_inputs()
    ordinary_key = _key(ordinary_path)
    view = ENTRY._make_snapshot(scope, {ordinary_key: ordinary_digest}, {}, software, rows, {}, {})

    assert set(view.public_bytes) == {ordinary_key}
    assert view.public_bytes[ordinary_key] == b"ordinary public python source\n"
    expected_profiler = {_key(path): digest for path, digest, _size, _role in ENTRY.PROFILER_STDLIB_OPAQUE_ROWS}
    assert dict(view.opaque_pins) == expected_profiler
    assert {key for key, _digest in scope.verifications} == set(expected_profiler)
    assert scope.reads == [(ordinary_key, ordinary_digest, ENTRY.MAX_SOURCE_BYTES)]
    assert view.assert_held_or_bytes(ordinary_key, ordinary_digest, {ordinary_key: view.public_bytes[ordinary_key]})
    for key, digest in expected_profiler.items():
        assert view.assert_held_or_bytes(key, digest, {})


def test_unindexed_or_mismatched_profiler_python_metadata_fails_closed():
    scope, ordinary_path, ordinary_digest, software, rows = _snapshot_inputs()
    first = ENTRY.PROFILER_STDLIB_OPAQUE_ROWS[0]
    path, digest, size, role = first

    _fixed_error(
        "profiler_opaque_descriptor_mismatch",
        lambda: ENTRY._metadata_opaque_descriptor(path, digest, size + 1, role),
    )
    _fixed_error(
        "profiler_opaque_descriptor_mismatch",
        lambda: ENTRY._metadata_opaque_descriptor(path, digest, size, "UNTRUSTED_ROLE"),
    )
    assert ENTRY._is_opaque_pin(r"C:\fixture\ordinary_public.py", "1" * 64, "public", 1000) is False
    _fixed_error(
        "unindexed_opaque_python_cache",
        lambda: ENTRY._is_opaque_pin(r"C:\fixture\unindexed.pyc", "1" * 64, "public", 1000),
    )
    _fixed_error(
        "profiler_stdlib_software_pin_mismatch",
        lambda: ENTRY._make_snapshot(
            scope,
            {_key(ordinary_path): ordinary_digest},
            {},
            {**software, _key(path): "0" * 64},
            rows,
            {},
            {},
        ),
    )

    missing = dict(software)
    del missing[_key(path)]
    _fixed_error(
        "profiler_stdlib_software_pin_mismatch",
        lambda: ENTRY._make_snapshot(
            scope, {_key(ordinary_path): ordinary_digest}, {}, missing, rows, {}, {}
        ),
    )

    unindexed_python = {**software, _key(r"C:\fixture\unindexed.py"): "1" * 64}
    _fixed_error(
        "profiler_software_python_set_mismatch",
        lambda: ENTRY._make_snapshot(
            scope,
            {_key(ordinary_path): ordinary_digest},
            {},
            unindexed_python,
            rows,
            {},
            {},
        ),
    )

    short_limit = dict(rows)
    short_limit[_key(path)] = (digest, "software", size - 1)
    _fixed_error(
        "profiler_stdlib_software_row_mismatch",
        lambda: ENTRY._make_snapshot(
            scope,
            {_key(ordinary_path): ordinary_digest},
            {},
            software,
            short_limit,
            {},
            {},
        ),
    )


def test_ordinary_python_content_mutation_is_still_hashed():
    expected = b"pinned ordinary python source\n"
    actual = b"mutated ordinary python source\n"
    ordinary_path = r"C:\fixture\ordinary_public.py"
    key = _key(ordinary_path)
    digest = _sha(expected)
    scope, _path, _digest, software, rows = _snapshot_inputs(actual)
    rows[key] = (digest, "public", ENTRY.MAX_SOURCE_BYTES)

    _fixed_error(
        "snapshot_public_bytes_invalid",
        lambda: ENTRY._make_snapshot(scope, {key: digest}, {}, software, rows, {}, {}),
    )
    assert scope.reads == [(key, digest, ENTRY.MAX_SOURCE_BYTES)]
    assert scope.verifications == []
