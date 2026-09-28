"""Fake-only tests for I15's complete source inventory and importer guard."""

from __future__ import annotations

import hashlib
import json
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

from backtrader_runtime.ctp_i15_source_identity import (
    I15_EXCLUDED_SOURCE_PIN_PATHS,
    I15_SOURCE_MANIFEST_RELATIVE_PATH,
    I15_SOURCE_MANIFEST_SCHEMA,
    I15SourceIdentityError,
    discover_i15_source_files,
    render_i15_source_verifier_bootstrap,
    verify_i15_source_identity,
)


def _write_manifest(root: Path) -> str:
    rows = []
    for relative in discover_i15_source_files(root):
        content = root.joinpath(*Path(relative).parts).read_bytes()
        rows.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
    manifest = (
        json.dumps(
            {"files": rows, "schema": I15_SOURCE_MANIFEST_SCHEMA},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    manifest_path = root.joinpath(*Path(I15_SOURCE_MANIFEST_RELATIVE_PATH).parts)
    manifest_path.write_bytes(manifest)
    return hashlib.sha256(manifest).hexdigest()


def _source_tree(root: Path) -> tuple[Path, str]:
    package = root / "backtrader_runtime"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("from . import sealed\n", encoding="utf-8")
    (package / "sealed.py").write_text("VALUE = 'sealed-source'\n", encoding="utf-8")
    (package / "ctp_artifact_provenance.py").write_text(
        "from pathlib import Path\n"
        "def _interpreter_install_roots(): return (Path('/untrusted/base/site-packages'),)\n",
        encoding="utf-8",
    )
    (package / "capability_imports.py").write_text(
        "from pathlib import Path\n"
        "def _interpreter_install_roots(): return frozenset((Path('/untrusted/base/site-packages'),))\n",
        encoding="utf-8",
    )
    (root / "site-packages").mkdir()
    for relative in I15_EXCLUDED_SOURCE_PIN_PATHS:
        pin = root.joinpath(*Path(relative).parts)
        pin.parent.mkdir(parents=True, exist_ok=True)
        pin.write_text("UNSEALED_PIN_TEST_SENTINEL = True\n", encoding="utf-8")
    return root.resolve(), _write_manifest(root)


def test_source_identity_accepts_exact_full_runtime_python_inventory(tmp_path: Path) -> None:
    root, digest = _source_tree(tmp_path)

    binding = verify_i15_source_identity(root, expected_manifest_sha256=digest)

    assert binding.manifest_sha256 == digest
    assert binding.source_count == 4
    assert set(discover_i15_source_files(root)) == {
        "backtrader_runtime/__init__.py",
        "backtrader_runtime/capability_imports.py",
        "backtrader_runtime/ctp_artifact_provenance.py",
        "backtrader_runtime/sealed.py",
    }


def test_source_identity_rejects_content_drift_and_unlisted_new_module(
    tmp_path: Path,
) -> None:
    root, digest = _source_tree(tmp_path)
    (root / "backtrader_runtime" / "sealed.py").write_text("VALUE = 'changed'\n", encoding="utf-8")
    with pytest.raises(I15SourceIdentityError, match="source_file_digest_mismatch"):
        verify_i15_source_identity(root, expected_manifest_sha256=digest)

    (root / "backtrader_runtime" / "sealed.py").write_text(
        "VALUE = 'sealed-source'\n", encoding="utf-8"
    )
    (root / "backtrader_runtime" / "new_dynamic.py").write_text(
        "VALUE = 'unlisted'\n", encoding="utf-8"
    )
    with pytest.raises(I15SourceIdentityError, match="source_manifest_file_set_mismatch"):
        verify_i15_source_identity(root, expected_manifest_sha256=digest)


def test_source_identity_rejects_manifest_tamper_and_runtime_pyc_cache(
    tmp_path: Path,
) -> None:
    root, digest = _source_tree(tmp_path)
    manifest_path = root.joinpath(*Path(I15_SOURCE_MANIFEST_RELATIVE_PATH).parts)
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
    with pytest.raises(I15SourceIdentityError, match="source_manifest_digest_mismatch"):
        verify_i15_source_identity(root, expected_manifest_sha256=digest)

    _write_manifest(root)
    source = root / "backtrader_runtime" / "sealed.py"
    pyc = Path(py_compile.compile(str(source), doraise=True))
    pyc_bytes = bytearray(pyc.read_bytes())
    pyc_bytes[-1] ^= 0x01
    pyc.write_bytes(pyc_bytes)
    with pytest.raises(I15SourceIdentityError, match="source_pyc_cache_invalid"):
        discover_i15_source_files(root)


def test_source_identity_accepts_pyc_only_when_bytecode_matches_source(
    tmp_path: Path,
) -> None:
    root, digest = _source_tree(tmp_path)
    source = root / "backtrader_runtime" / "sealed.py"
    py_compile.compile(str(source), doraise=True)

    binding = verify_i15_source_identity(root, expected_manifest_sha256=digest)

    assert binding.source_count == 4


def test_source_identity_rejects_native_extension_sibling(tmp_path: Path) -> None:
    root, _digest = _source_tree(tmp_path)
    (root / "backtrader_runtime" / "unsealed_native.pyd").write_bytes(b"not-a-real-extension")

    with pytest.raises(I15SourceIdentityError, match="source_native_module_invalid"):
        discover_i15_source_files(root)


def test_inline_bootstrap_blocks_drift_and_unsealed_imports_before_execution(
    tmp_path: Path,
) -> None:
    root, digest = _source_tree(tmp_path)
    cache_prefix = tmp_path / "isolated-cache-prefix"
    bootstrap = render_i15_source_verifier_bootstrap(
        source_root=root,
        expected_manifest_sha256=digest,
        cache_prefix=cache_prefix,
        site_packages_root=root / "site-packages",
    )
    hook_root = root / "site-packages"
    sentinel = root / "site-hook-ran"
    (hook_root / "hostile.pth").write_text("import sitecustomize\n", encoding="utf-8")
    (hook_root / "sitecustomize.py").write_text(
        f"from pathlib import Path; Path({str(sentinel)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    command = (
        bootstrap
        + "\nif not _verify_i15_source_identity(): raise SystemExit(21)\n"
        + "_install_i15_sealed_importer()\n"
        + "if not _i15_add_fixed_install_root() or not _i15_bind_fixed_artifact_install_root(): raise SystemExit(24)\n"
        + "import backtrader_runtime\n"
        + "import backtrader_runtime.sealed as sealed\n"
        + "assert sealed.VALUE == 'sealed-source'\n"
        + "import backtrader_runtime.ctp_artifact_provenance as provenance\n"
        + "import backtrader_runtime.capability_imports as capability_imports\n"
        + "assert provenance._interpreter_install_roots() == (_I15_FIXED_SITE_PACKAGES.resolve(),)\n"
        + "assert capability_imports._interpreter_install_roots() == frozenset((_I15_FIXED_SITE_PACKAGES.resolve(),))\n"
        + "assert _verify_i15_import_origins()\n"
        + "try:\n    import backtrader_runtime.unsealed\n"
        + "except ModuleNotFoundError:\n    pass\n"
        + "else:\n    raise AssertionError('unsealed runtime import succeeded')\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix=" + str(cache_prefix),
            "-c",
            command,
        ],
        cwd=str(root),
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not cache_prefix.exists()
    assert not sentinel.exists()

    (root / "backtrader_runtime" / "sealed.py").write_text(
        "VALUE = 'changed-before-import'\n", encoding="utf-8"
    )
    drift_command = bootstrap + "\nif not _verify_i15_source_identity(): raise SystemExit(22)\n"
    drift_result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix=" + str(cache_prefix),
            "-c",
            drift_command,
        ],
        cwd=str(root),
        capture_output=True,
        check=False,
        text=True,
    )
    assert drift_result.returncode == 22

    cache_prefix.mkdir()
    cached_prefix_result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix=" + str(cache_prefix),
            "-c",
            bootstrap + "\nif not _verify_i15_source_identity(): raise SystemExit(23)\n",
        ],
        cwd=str(root),
        capture_output=True,
        check=False,
        text=True,
    )
    assert cached_prefix_result.returncode == 23


def test_inline_bootstrap_rejects_preloaded_runtime_module_before_seal(
    tmp_path: Path,
) -> None:
    root, digest = _source_tree(tmp_path)
    cache_prefix = tmp_path / "cache-prefix"
    bootstrap = render_i15_source_verifier_bootstrap(
        source_root=root,
        expected_manifest_sha256=digest,
        cache_prefix=cache_prefix,
        site_packages_root=root / "site-packages",
    )
    code = (
        bootstrap
        + "\nimport types\n"
        + "sys.modules['backtrader_runtime'] = types.ModuleType('backtrader_runtime')\n"
        + "if _verify_i15_source_identity(): raise SystemExit(25)\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix=" + str(cache_prefix),
            "-c",
            code,
        ],
        cwd=str(root),
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_inline_bootstrap_rejects_preloaded_site_customization_module(
    tmp_path: Path,
) -> None:
    root, digest = _source_tree(tmp_path)
    cache_prefix = tmp_path / "cache-prefix"
    bootstrap = render_i15_source_verifier_bootstrap(
        source_root=root,
        expected_manifest_sha256=digest,
        cache_prefix=cache_prefix,
        site_packages_root=root / "site-packages",
    )
    code = (
        bootstrap
        + "\nimport types\n"
        + "sys.modules['sitecustomize'] = types.ModuleType('sitecustomize')\n"
        + "if _verify_i15_source_identity(): raise SystemExit(26)\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix=" + str(cache_prefix),
            "-c",
            code,
        ],
        cwd=str(root),
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
