"""Offline tests for the non-authorizing I13 source-manifest candidate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import types
import uuid
import ast
import base64
import zlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script_module(module_name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("test script module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


candidate_builder = _load_script_module(
    "_i13_source_manifest_candidate_test_builder",
    REPO_ROOT / "scripts" / "ctp_i13_source_manifest_candidate.py",
)
parent_launcher = _load_script_module(
    "_i13_source_manifest_candidate_test_launcher",
    REPO_ROOT / "scripts" / "ctp_i13_i15_parent_launcher.py",
)


def _load_runtime_identity() -> tuple[types.ModuleType, str]:
    """Load the identity source under a fake package, bypassing runtime init."""

    package_name = "_i13_source_identity_test_" + uuid.uuid4().hex
    package = types.ModuleType(package_name)
    package.__path__ = [str(REPO_ROOT / "backtrader_runtime")]
    sys.modules[package_name] = package
    module_name = package_name + ".ctp_i13_source_identity"
    module = _load_script_module(
        module_name, REPO_ROOT / "backtrader_runtime" / "ctp_i13_source_identity.py"
    )
    return module, package_name


def _remove_runtime_identity(package_name: str) -> None:
    for module_name in tuple(sys.modules):
        if module_name == package_name or module_name.startswith(package_name + "."):
            sys.modules.pop(module_name, None)


def _fake_runtime_tree(root: Path) -> Path:
    package = root / "backtrader_runtime"
    files = {
        "__init__.py": b"# fake runtime package\n",
        "inventory.py": b"RUNTIME_REGISTRY = ()\n",
        "ctp_i13_md_oneshot_supervisor.py": b"DIAGNOSTIC_ONLY = True\n",
        "ctp_i13_source_identity.py": b"IDENTITY_SOURCE = True\n",
        "ctp_i13_worker_dependency_seal.py": b"DEPENDENCY_SEAL_SOURCE = True\n",
        "nested/fake_module.py": b"VALUE = 'offline'\n",
        "ctp_i13_source_identity_pin.py": b"I13_SOURCE_MANIFEST_SHA256 = '0' * 64\n",
        "ctp_i15_source_identity_pin.py": b"I15_REVIEWED_SOURCE_MANIFEST_SHA256 = None\n",
    }
    for relative, content in files.items():
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    worker_path = root.joinpath(*candidate_builder.FIXED_READONLY_WORKER_PATH.parts)
    worker_path.parent.mkdir(parents=True, exist_ok=True)
    worker_path.write_bytes(b"WORKER_SOURCE = 'fixed-readonly-worker'\n")
    bootstrap_path = root.joinpath(*candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.parts)
    bootstrap_path.write_bytes(b"BOOTSTRAP_SOURCE = 'fixed-readonly-bootstrap'\n")
    for path, label in zip(
        candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS,
        ("coordinator", "receipt-writer", "token-bootstrap"),
    ):
        service_path = root.joinpath(*path.parts)
        service_path.write_bytes(f"SERVICE_ROLE = '{label}'\n".encode("ascii"))
    support_sources = {
        "scripts/ctp_i13_i15_sealed_import.py": b"SEALED_IMPORT_SOURCE = True\n",
        "scripts/ctp_i13_i15_guardian_deployment_anchor.py": b"ANCHOR_SOURCE = True\n",
        "scripts/ctp_i13_i15_parent_launcher.py": b"PARENT_SOURCE = True\n",
        "scripts/ctp_i13_i15_runtime_closure.py": b"RUNTIME_CLOSURE_SOURCE = True\n",
        "scripts/ctp_i13_i15_outer_watchdog.py": b"class OuterBackendCreationError(Exception): pass\n",
        "scripts/ctp_i13_i15_worker_output_channel.py": b"OUTPUT_CHANNEL_SOURCE = True\n",
        "scripts/ctp_i13_i15_windows_job_backend.py": (
            b"from scripts.ctp_i13_i15_outer_watchdog import OuterBackendCreationError\n"
            b"BACKEND_SOURCE = True\n"
        ),
    }
    for relative, content in support_sources.items():
        target = root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


def _embedded_support(artifact: bytes) -> tuple[bytes, dict[str, object]]:
    module = ast.parse(artifact.decode("ascii"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_READONLY_BOOTSTRAP_SUPPORT_B85"
            for target in node.targets
        )
    )
    encoded = ast.literal_eval(assignment.value)
    support_start = artifact.index(b"_READONLY_BOOTSTRAP_SUPPORT_SHA256 = ")
    support_line = artifact[support_start : artifact.index(b"\n", support_start)]
    support_sha256 = support_line.split(b'"')[1].decode("ascii")
    raw = zlib.decompress(base64.b85decode(encoded.encode("ascii")))
    assert hashlib.sha256(raw).hexdigest() == support_sha256
    header_size = int.from_bytes(raw[:4], "big")
    header = json.loads(raw[4 : 4 + header_size].decode("ascii"))
    assert header["schema"] == 2
    source_offset = 4 + header_size
    files = {}
    for row in header["files"]:
        size = row["size"]
        source = raw[source_offset : source_offset + size]
        source_offset += size
        assert hashlib.sha256(source).hexdigest() == row["sha256"]
        files[row["path"]] = source
    assert source_offset == len(raw)
    return raw, files


def test_bootstrap_artifact_is_deterministic_and_binds_exact_embedded_support(
    tmp_path: Path,
) -> None:
    root = _fake_runtime_tree(tmp_path)

    artifact = candidate_builder.build_readonly_preflight_bootstrap(root)
    repeated = candidate_builder.build_readonly_preflight_bootstrap(root)

    assert artifact == repeated
    assert len(artifact) <= candidate_builder._MAX_BOOTSTRAP_BYTES
    assert artifact.startswith(
        (root / "scripts" / "ctp_i13_i15_sealed_import.py").read_bytes().rstrip() + b"\n\n"
    )
    compile(artifact, "<test-bootstrap>", "exec")
    _raw, embedded = _embedded_support(artifact)
    assert list(embedded) == [
        path.as_posix() for path in candidate_builder.BOOTSTRAP_EMBEDDED_SUPPORT_PATHS
    ]
    for relative, source in embedded.items():
        assert source == root.joinpath(*relative.split("/")).read_bytes()
    assert b"ctp_i13_i15_readonly_preflight_bootstrap_binding.v3" in artifact
    assert b"runtime_manifest_sha256" in artifact
    assert b"worker_output" in artifact and b"request_id" in artifact


def test_bootstrap_embeds_frozen_overlapped_io_worker_channel_without_import_fallback() -> None:
    channel_relative = "scripts/ctp_i13_i15_worker_output_channel.py"
    frozen_r5_baseline_sha256 = "c32dbe7c850e07fde6a3e57f5b29ca45803cfa5b8f3bea103d5e0582b4656222"
    frozen_candidate_sha256 = "4f9ff31428cdfd9d62acc8118ae4bb00bc09cc0e5883fb07c6b1daea85f41178"
    frozen_manifest_sha256 = "074235d2ff29afb6256ef385f29f5c6b7a9e84be8eacbb3bc3fb4fbaa472668c"
    frozen_manifest_relative = (
        "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/"
        "evidence/iteration41-g1-overlapped-io-custody-main-2026-09-28/"
        "candidate/FROZEN-MANIFEST.json"
    )
    watchdog_relative = "scripts/ctp_i13_i15_outer_watchdog.py"
    backend_relative = "scripts/ctp_i13_i15_windows_job_backend.py"
    frozen_watchdog_sha256 = "f738f5deac1e7e5a7db101b72343677bb299f49451a8325cf1defe1305799a79"
    frozen_backend_sha256 = "c1e83f7075f48fa16f5db862d0ef95aec1eed2e8551464c9e990dbb3ecd324fd"
    channel_path = REPO_ROOT.joinpath(*channel_relative.split("/"))
    channel_source = channel_path.read_bytes()
    frozen_manifest_raw = REPO_ROOT.joinpath(*frozen_manifest_relative.split("/")).read_bytes()
    assert hashlib.sha256(frozen_manifest_raw).hexdigest() == frozen_manifest_sha256
    frozen_manifest = json.loads(frozen_manifest_raw)
    channel_manifest = frozen_manifest["file_hashes"][channel_relative]
    assert channel_manifest["baseline_sha256"] == frozen_r5_baseline_sha256
    assert channel_manifest["candidate_sha256"] == frozen_candidate_sha256
    assert channel_manifest["identical"] is False
    watchdog_source = REPO_ROOT.joinpath(*watchdog_relative.split("/")).read_bytes()
    backend_source = REPO_ROOT.joinpath(*backend_relative.split("/")).read_bytes()

    assert hashlib.sha256(channel_source).hexdigest() == frozen_candidate_sha256
    assert hashlib.sha256(watchdog_source).hexdigest() == frozen_watchdog_sha256
    assert hashlib.sha256(backend_source).hexdigest() == frozen_backend_sha256
    artifact = candidate_builder.build_readonly_preflight_bootstrap(REPO_ROOT)
    module = ast.parse(artifact.decode("ascii"))
    _raw, support = _embedded_support(artifact)
    embedded_source = support[channel_relative]
    assert embedded_source == channel_source
    assert hashlib.sha256(embedded_source).hexdigest() == frozen_candidate_sha256
    assert support[watchdog_relative] == watchdog_source
    assert support[backend_relative] == backend_source

    run = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_readonly_bootstrap_run"
    )
    channel_loader = next(
        node
        for node in ast.walk(run)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_readonly_bootstrap_exec_support_modules"
        and any(isinstance(target, ast.Name) and target.id == "support_modules" for target in node.targets)
    )
    loader_call = channel_loader.value
    assert isinstance(loader_call.func, ast.Name)
    assert loader_call.func.id == "_readonly_bootstrap_exec_support_modules"
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "output_channel_module"
        and node.func.attr == "write_worker_output_frame"
        for node in ast.walk(run)
    )
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any(
            (alias.name if isinstance(node, ast.Import) else node.module or "").startswith(
                "scripts.ctp_i13_i15_worker_output_channel"
            )
            for alias in (node.names if isinstance(node, ast.Import) else [None])
        )
        for node in ast.walk(module)
    )


def test_generated_bootstrap_captures_live_runtime_facts_from_embedded_helper() -> None:
    artifact = candidate_builder.build_readonly_preflight_bootstrap(REPO_ROOT)
    module = ast.parse(artifact.decode("ascii"))
    run = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_readonly_bootstrap_run"
    )
    assignment = next(
        node
        for node in ast.walk(run)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "process_facts" for target in node.targets
        )
    )
    call = assignment.value
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Subscript)
    assert isinstance(call.func.value, ast.Name)
    assert call.func.value.id == "runtime_ns"
    assert ast.literal_eval(call.func.slice) == "capture_runtime_process_facts"
    assert not call.args and not call.keywords


def test_actual_isolated_cpython_reports_fixed_cache_prefix_and_source_origins() -> None:
    if sys.platform != "win32" or sys.version_info[:3] != (3, 11, 5):
        pytest.skip("actual process smoke targets the pinned Windows CPython 3.11.5")

    base_home = Path(sys.base_prefix)
    cache_prefix = base_home / "disabled-bytecode-cache"
    assert not os.path.lexists(cache_prefix)
    probe = r"""
import asyncio, json, logging, os, sys
expected_prefix = sys.argv[1]
base_home = sys.base_prefix
expected_path = (
    os.path.join(base_home, 'python311.zip'),
    os.path.join(base_home, 'DLLs'),
    os.path.join(base_home, 'Lib'),
    base_home,
)
assert tuple(sys.version_info[:3]) == (3, 11, 5)
assert sys.flags.isolated == 1
assert sys.flags.no_site == 1
assert sys.dont_write_bytecode is True
assert sys.prefix == base_home == sys.base_prefix
assert sys.pycache_prefix == expected_prefix
assert tuple(os.path.normcase(os.path.normpath(p)) for p in sys.path) == tuple(
    os.path.normcase(os.path.normpath(p)) for p in expected_path
)
origins = {
    name: module.__file__
    for name, module in (("asyncio", asyncio), ("json", json), ("logging", logging))
}
for origin in origins.values():
    assert os.path.commonpath((os.path.normcase(origin), os.path.normcase(os.path.join(base_home, 'Lib')))) == os.path.normcase(os.path.join(base_home, 'Lib'))
print(json.dumps({"version": list(sys.version_info[:3]), "flags": [sys.flags.isolated, sys.flags.no_site, sys.dont_write_bytecode], "prefix": sys.prefix, "base_prefix": sys.base_prefix, "pycache_prefix": sys.pycache_prefix, "sys_path": list(sys.path), "source_origins": origins}, sort_keys=True, separators=(",", ":")))
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix=" + os.fspath(cache_prefix),
            "-c",
            probe,
            os.fspath(cache_prefix),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    facts = json.loads(completed.stdout)
    assert facts["version"] == [3, 11, 5]
    assert facts["flags"] == [1, 1, True]
    assert facts["pycache_prefix"] == os.fspath(cache_prefix)
    assert facts["sys_path"] == [
        os.path.join(base_home, "python311.zip"),
        os.path.join(base_home, "DLLs"),
        os.path.join(base_home, "Lib"),
        os.fspath(base_home),
    ]
    assert facts["source_origins"] == {
        "asyncio": os.path.join(base_home, "Lib", "asyncio", "__init__.py"),
        "json": os.path.join(base_home, "Lib", "json", "__init__.py"),
        "logging": os.path.join(base_home, "Lib", "logging", "__init__.py"),
    }
    assert not os.path.lexists(cache_prefix)


def test_bootstrap_writer_targets_only_the_fixed_source_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fake_runtime_tree(tmp_path)

    output, content = candidate_builder.write_readonly_preflight_bootstrap_candidate(root)

    assert output == root / candidate_builder.BOOTSTRAP_OUTPUT
    assert output.read_bytes() == content
    outside = root.parent / (root.name + "_bootstrap_escape.py")
    monkeypatch.setattr(candidate_builder, "BOOTSTRAP_OUTPUT", outside)
    with pytest.raises(
        candidate_builder.SourceManifestCandidateError,
        match="bootstrap_output_path_invalid",
    ):
        candidate_builder.write_readonly_preflight_bootstrap_candidate(root)
    assert not outside.exists()


def test_candidate_is_canonical_complete_and_accepted_by_both_parsers(
    tmp_path: Path,
) -> None:
    root = _fake_runtime_tree(tmp_path)
    raw = candidate_builder.build_i13_source_manifest(root)
    digest = hashlib.sha256(raw).hexdigest()
    value = json.loads(raw.decode("utf-8"))

    assert set(value) == {"schema", "source_files"}
    assert value["schema"] == 1
    assert list(value["source_files"]) == sorted(value["source_files"])
    assert raw == json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    assert not raw.endswith(b"\n")
    assert set(value["source_files"]) == set(candidate_builder.discover_i13_source_files(root))
    assert candidate_builder.PIN_PATHS.isdisjoint(value["source_files"])

    parsed_by_launcher = parent_launcher._parse_candidate_manifest("i13_md", raw, digest)
    identity, package_name = _load_runtime_identity()
    try:
        parsed_by_runtime = identity.parse_i13_source_manifest(raw)
        identity._verify_i13_source_files(root, parsed_by_runtime)
        full_inventory = (
            identity._runtime_python_inventory(root)
            | {candidate_builder.FIXED_READONLY_WORKER_PATH.as_posix()}
            | {candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.as_posix()}
            | {path.as_posix() for path in candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS}
        )
        leased_directories = identity._source_lease_directories(
            root,
            [
                root.joinpath(*candidate_builder.FIXED_READONLY_WORKER_PATH.parts),
                root.joinpath(*candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.parts),
                *(
                    root.joinpath(*path.parts)
                    for path in candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS
                ),
            ],
        )
    finally:
        _remove_runtime_identity(package_name)

    assert dict(parsed_by_launcher) == value["source_files"]
    assert dict(parsed_by_runtime) == value["source_files"]
    assert full_inventory == set(value["source_files"]) | candidate_builder.PIN_PATHS
    worker_relative = candidate_builder.FIXED_READONLY_WORKER_PATH.as_posix()
    worker_path = root.joinpath(*candidate_builder.FIXED_READONLY_WORKER_PATH.parts)
    bootstrap_relative = candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.as_posix()
    bootstrap_path = root.joinpath(*candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.parts)
    assert (
        value["source_files"][worker_relative]
        == hashlib.sha256(worker_path.read_bytes()).hexdigest()
    )
    assert (
        value["source_files"][bootstrap_relative]
        == hashlib.sha256(bootstrap_path.read_bytes()).hexdigest()
    )
    for service_path in candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS:
        relative = service_path.as_posix()
        path = root.joinpath(*service_path.parts)
        assert value["source_files"][relative] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not any(
        path.startswith("scripts/")
        for path in value["source_files"]
        if path
        not in {
            candidate_builder.FIXED_READONLY_WORKER_PATH.as_posix(),
            candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.as_posix(),
            *(path.as_posix() for path in candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS),
        }
    )
    assert root / "scripts" in leased_directories
    assert root in leased_directories


def test_candidate_covers_new_sources_but_excludes_pin_contents(tmp_path: Path) -> None:
    root = _fake_runtime_tree(tmp_path)
    first = candidate_builder.build_i13_source_manifest(root)
    package = root / "backtrader_runtime"
    (package / "new_diagnostic_helper.py").write_bytes(b"HELPER = True\n")
    second = candidate_builder.build_i13_source_manifest(root)
    (package / "ctp_i13_source_identity_pin.py").write_bytes(
        b"I13_SOURCE_MANIFEST_SHA256 = 'changed-but-still-unpinned'\n"
    )
    third = candidate_builder.build_i13_source_manifest(root)

    assert first != second
    assert second == third
    assert "backtrader_runtime/new_diagnostic_helper.py" in json.loads(second)["source_files"]
    assert (
        candidate_builder.FIXED_READONLY_WORKER_PATH.as_posix()
        in json.loads(second)["source_files"]
    )


def test_candidate_writer_uses_only_a_labelled_non_runtime_path(tmp_path: Path) -> None:
    root = _fake_runtime_tree(tmp_path)
    output = root / "artifacts" / candidate_builder.CANDIDATE_OUTPUT.name

    written_path, raw = candidate_builder.write_current_dirty_tree_candidate(root)

    assert written_path == output
    assert output.read_bytes() == raw
    assert output != root / candidate_builder.MANIFEST_RELATIVE_PATH


def test_candidate_writer_rejects_mutated_relative_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fake_runtime_tree(tmp_path)
    monkeypatch.setattr(candidate_builder, "CANDIDATE_OUTPUT", Path("../escaped.json"))

    with pytest.raises(
        candidate_builder.SourceManifestCandidateError,
        match="candidate_output_path_invalid",
    ):
        candidate_builder.write_current_dirty_tree_candidate(root)

    assert not (root.parent / "escaped.json").exists()
    assert not (root / "artifacts").exists()


def test_candidate_writer_rejects_mutated_absolute_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fake_runtime_tree(tmp_path)
    outside = root.parent / (root.name + "_escaped.json")
    monkeypatch.setattr(candidate_builder, "CANDIDATE_OUTPUT", outside)

    with pytest.raises(
        candidate_builder.SourceManifestCandidateError,
        match="candidate_output_path_invalid",
    ):
        candidate_builder.write_current_dirty_tree_candidate(root)

    assert not outside.exists()
    assert not (root / "artifacts").exists()


def test_candidate_writer_rejects_reparse_artifacts_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fake_runtime_tree(tmp_path)
    artifacts = root / "artifacts"
    artifacts.mkdir()
    original_lstat = os.lstat

    def report_reparse(path: object, *args: object, **kwargs: object) -> object:
        if Path(path) == artifacts:
            return types.SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o755,
                st_file_attributes=0x400,
            )
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(candidate_builder.os, "lstat", report_reparse)

    with pytest.raises(
        candidate_builder.SourceManifestCandidateError,
        match="candidate_output_directory_invalid",
    ):
        candidate_builder.write_current_dirty_tree_candidate(root)

    assert not (artifacts / candidate_builder.CANDIDATE_OUTPUT.name).exists()


def test_discovered_file_set_matches_runtime_identity_inventory() -> None:
    identity, package_name = _load_runtime_identity()
    try:
        full_inventory = identity._runtime_python_inventory(REPO_ROOT)
    finally:
        _remove_runtime_identity(package_name)

    fixed_paths = {
        candidate_builder.FIXED_READONLY_WORKER_PATH,
        candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH,
        *candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS,
    }
    if not all(REPO_ROOT.joinpath(*path.parts).is_file() for path in fixed_paths):
        with pytest.raises(
            candidate_builder.SourceManifestCandidateError,
            match="source_inventory_incomplete",
        ):
            candidate_builder.discover_i13_source_files(REPO_ROOT)
        return

    assert set(candidate_builder.discover_i13_source_files(REPO_ROOT)) == (
        full_inventory - candidate_builder.PIN_PATHS
        | {
            *(path.as_posix() for path in fixed_paths),
        }
    )


def test_legacy_runtime_only_manifest_remains_valid_but_does_not_pin_worker(
    tmp_path: Path,
) -> None:
    root = _fake_runtime_tree(tmp_path)
    raw = candidate_builder.build_i13_source_manifest(root)
    value = json.loads(raw.decode("utf-8"))
    value["source_files"].pop(candidate_builder.FIXED_READONLY_WORKER_PATH.as_posix())
    value["source_files"].pop(candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.as_posix())
    for path in candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS:
        value["source_files"].pop(path.as_posix())
    legacy_raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    identity, package_name = _load_runtime_identity()
    try:
        parsed = identity.parse_i13_source_manifest(legacy_raw)
        identity._require_i13_source_inventory(root, set(parsed) | candidate_builder.PIN_PATHS)
        leased_directories = identity._source_lease_directories(
            root,
            [root.joinpath(*path.split("/")) for path in parsed],
        )
    finally:
        _remove_runtime_identity(package_name)
    assert candidate_builder.FIXED_READONLY_WORKER_PATH.as_posix() not in parsed
    assert candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.as_posix() not in parsed
    assert not any(
        path.as_posix() in parsed for path in candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS
    )
    assert root / "scripts" not in leased_directories


def test_legacy_bootstrap_manifest_without_service_roles_remains_valid(tmp_path: Path) -> None:
    root = _fake_runtime_tree(tmp_path)
    value = json.loads(candidate_builder.build_i13_source_manifest(root))
    for path in candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS:
        value["source_files"].pop(path.as_posix())
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    identity, package_name = _load_runtime_identity()
    try:
        parsed = identity.parse_i13_source_manifest(raw)
        identity._require_i13_source_inventory(root, set(parsed) | candidate_builder.PIN_PATHS)
    finally:
        _remove_runtime_identity(package_name)
    assert candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.as_posix() in parsed
    assert not any(
        path.as_posix() in parsed for path in candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS
    )


def test_service_role_manifest_requires_exact_pair_and_bootstrap_closure(
    tmp_path: Path,
) -> None:
    root = _fake_runtime_tree(tmp_path)
    full = json.loads(candidate_builder.build_i13_source_manifest(root))["source_files"]
    receipt_writer = candidate_builder.FIXED_READONLY_RECEIPT_WRITER_PATH

    incomplete = dict(full)
    incomplete.pop(receipt_writer.as_posix())
    incomplete_raw = json.dumps(
        {"schema": 1, "source_files": incomplete},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    identity, package_name = _load_runtime_identity()
    try:
        parsed = identity.parse_i13_source_manifest(incomplete_raw)
        with pytest.raises(
            identity.I13SourceIdentityError,
            match="source_manifest_service_roles_incomplete",
        ):
            identity._require_i13_source_inventory(root, set(parsed) | candidate_builder.PIN_PATHS)
    finally:
        _remove_runtime_identity(package_name)

    without_helper = dict(full)
    without_helper.pop(candidate_builder.FIXED_WORKER_DEPENDENCY_HELPER_PATH.as_posix())
    without_helper_raw = json.dumps(
        {"schema": 1, "source_files": without_helper},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    identity, package_name = _load_runtime_identity()
    try:
        parsed = identity.parse_i13_source_manifest(without_helper_raw)
        with pytest.raises(
            identity.I13SourceIdentityError,
            match="source_manifest_dependency_helper_unpinned",
        ):
            identity._require_i13_source_inventory(root, set(parsed) | candidate_builder.PIN_PATHS)
    finally:
        _remove_runtime_identity(package_name)


def test_identity_checks_fixed_worker_digest_and_rejects_changed_bytes(
    tmp_path: Path,
) -> None:
    root = _fake_runtime_tree(tmp_path)
    raw = candidate_builder.build_i13_source_manifest(root)
    identity, package_name = _load_runtime_identity()
    try:
        parsed = identity.parse_i13_source_manifest(raw)
        worker = root.joinpath(*candidate_builder.FIXED_READONLY_WORKER_PATH.parts)
        worker.write_bytes(b"changed-worker-bytes\n")
        with pytest.raises(identity.I13SourceIdentityError, match="source_digest_mismatch"):
            identity._verify_i13_source_files(root, parsed)
    finally:
        _remove_runtime_identity(package_name)


def test_manifest_parsers_reject_any_other_scripts_source_path(tmp_path: Path) -> None:
    root = _fake_runtime_tree(tmp_path)
    value = json.loads(candidate_builder.build_i13_source_manifest(root))
    value["source_files"]["scripts/unreviewed.py"] = hashlib.sha256(b"x").hexdigest()
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    with pytest.raises(parent_launcher.ParentLaunchError, match="manifest_path_invalid"):
        parent_launcher._parse_candidate_manifest("i13_md", raw, hashlib.sha256(raw).hexdigest())
    identity, package_name = _load_runtime_identity()
    try:
        with pytest.raises(identity.I13SourceIdentityError, match="source_manifest_path_invalid"):
            identity.parse_i13_source_manifest(raw)
    finally:
        _remove_runtime_identity(package_name)


def test_candidate_rejects_missing_fixed_worker_source(tmp_path: Path) -> None:
    root = _fake_runtime_tree(tmp_path)
    worker = root.joinpath(*candidate_builder.FIXED_READONLY_WORKER_PATH.parts)
    worker.unlink()
    with pytest.raises(
        candidate_builder.SourceManifestCandidateError,
        match="source_inventory_incomplete",
    ):
        candidate_builder.build_i13_source_manifest(root)


def test_candidate_rejects_missing_fixed_bootstrap_source(tmp_path: Path) -> None:
    root = _fake_runtime_tree(tmp_path)
    bootstrap = root.joinpath(*candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.parts)
    bootstrap.unlink()
    with pytest.raises(
        candidate_builder.SourceManifestCandidateError,
        match="source_inventory_incomplete",
    ):
        candidate_builder.build_i13_source_manifest(root)


def test_candidate_rejects_missing_dependency_helper_for_bootstrap(tmp_path: Path) -> None:
    root = _fake_runtime_tree(tmp_path)
    helper = root.joinpath(*candidate_builder.FIXED_WORKER_DEPENDENCY_HELPER_PATH.parts)
    helper.unlink()
    with pytest.raises(
        candidate_builder.SourceManifestCandidateError,
        match="source_inventory_incomplete",
    ):
        candidate_builder.build_i13_source_manifest(root)


def test_worker_only_manifest_is_compatible_but_bootstrap_requires_worker(
    tmp_path: Path,
) -> None:
    root = _fake_runtime_tree(tmp_path)
    value = json.loads(candidate_builder.build_i13_source_manifest(root))
    worker_path = candidate_builder.FIXED_READONLY_WORKER_PATH.as_posix()
    bootstrap_path = candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.as_posix()
    value["source_files"].pop(bootstrap_path)
    for path in candidate_builder.FIXED_READONLY_SERVICE_ROLE_PATHS:
        value["source_files"].pop(path.as_posix())
    worker_only = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    worker_only_digest = hashlib.sha256(worker_only).hexdigest()
    assert worker_path in parent_launcher._parse_candidate_manifest(
        "i13_md", worker_only, worker_only_digest
    )
    identity, package_name = _load_runtime_identity()
    try:
        parsed_worker_only = identity.parse_i13_source_manifest(worker_only)
        identity._require_i13_source_inventory(
            root, set(parsed_worker_only) | candidate_builder.PIN_PATHS
        )
    finally:
        _remove_runtime_identity(package_name)

    helper_missing_value = json.loads(candidate_builder.build_i13_source_manifest(root))
    helper_missing_value["source_files"].pop(
        candidate_builder.FIXED_WORKER_DEPENDENCY_HELPER_PATH.as_posix()
    )
    helper_missing_raw = json.dumps(
        helper_missing_value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    helper_missing_digest = hashlib.sha256(helper_missing_raw).hexdigest()
    with pytest.raises(
        parent_launcher.ParentLaunchError,
        match="readonly_dependency_helper_source_unpinned",
    ):
        parent_launcher._parse_candidate_manifest(
            "i13_md", helper_missing_raw, helper_missing_digest
        )
    identity, package_name = _load_runtime_identity()
    try:
        parsed_helper_missing = identity.parse_i13_source_manifest(helper_missing_raw)
        with pytest.raises(
            identity.I13SourceIdentityError,
            match="source_manifest_dependency_helper_unpinned",
        ):
            identity._require_i13_source_inventory(
                root, set(parsed_helper_missing) | candidate_builder.PIN_PATHS
            )
    finally:
        _remove_runtime_identity(package_name)

    value["source_files"].pop(worker_path)
    value["source_files"][bootstrap_path] = hashlib.sha256(
        root.joinpath(*candidate_builder.FIXED_READONLY_BOOTSTRAP_PATH.parts).read_bytes()
    ).hexdigest()
    bootstrap_without_worker = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    bootstrap_digest = hashlib.sha256(bootstrap_without_worker).hexdigest()
    with pytest.raises(parent_launcher.ParentLaunchError, match="readonly_worker_source_unpinned"):
        parent_launcher._parse_candidate_manifest(
            "i13_md", bootstrap_without_worker, bootstrap_digest
        )
    identity, package_name = _load_runtime_identity()
    try:
        parsed = identity.parse_i13_source_manifest(bootstrap_without_worker)
        with pytest.raises(
            identity.I13SourceIdentityError, match="source_manifest_worker_unpinned"
        ):
            identity._require_i13_source_inventory(root, set(parsed) | candidate_builder.PIN_PATHS)
    finally:
        _remove_runtime_identity(package_name)


def test_parent_launcher_rejects_extra_manifest_fields_and_out_of_scope_paths(
    tmp_path: Path,
) -> None:
    root = _fake_runtime_tree(tmp_path)
    value = json.loads(candidate_builder.build_i13_source_manifest(root))
    value["not_in_schema"] = True
    extra_field = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    with pytest.raises(parent_launcher.ParentLaunchError, match="manifest_invalid"):
        parent_launcher._parse_candidate_manifest(
            "i13_md", extra_field, hashlib.sha256(extra_field).hexdigest()
        )

    value.pop("not_in_schema")
    value["source_files"]["backtrader_runtime/../outside.py"] = hashlib.sha256(
        b"fake-source"
    ).hexdigest()
    invalid_path = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    with pytest.raises(parent_launcher.ParentLaunchError, match="manifest_path_invalid"):
        parent_launcher._parse_candidate_manifest(
            "i13_md", invalid_path, hashlib.sha256(invalid_path).hexdigest()
        )
