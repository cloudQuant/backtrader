"""Build the R2 source manifest and freeze receipt from this isolated tree."""

from __future__ import annotations

import difflib
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
R1_ROOT = Path(
    r"D:\temp\iteration41-g6s-artifact-first-sdk-binding-candidate-20260927-r1"
)
R1_ARCHIVE = Path(
    r"D:\temp\iteration41-g6s-artifact-first-sdk-binding-candidate-20260927-r1.zip"
)
R1_ARCHIVE_SHA256 = "d5aa16bec66c7618f58b1039f87c7a774ec9958a848cbd29a94e7527887e84f0"
R1_MANIFEST_SHA256 = "4cda34fadd2c73efb999a0411657eb625b30caa2adce5a0e56ef7527a90f8080"
R1_MANIFEST = ROOT / "evidence" / "r1-parent" / "candidate-source-manifest.json"
R1_RECEIPT = ROOT / "evidence" / "r1-parent" / "freeze-receipt.json"
MANIFEST = ROOT / "candidate-source-manifest.json"
RECEIPT = ROOT / "freeze-receipt.json"
DIFF_PATH = ROOT / "evidence" / "r2-loader-identity" / "source-diff-from-r1.patch"

CHANGED_PATHS = (
    "backtrader_runtime/ctp_sdk_artifact_binding.py",
    "tests/unit/runtime/test_ctp_sdk_artifact_binding.py",
)
PYTEST_LOG = ROOT / "evidence" / "r2-loader-identity" / "pytest-focus.stdout.txt"
JUNIT = ROOT / "evidence" / "r2-loader-identity" / "pytest-focus.junit.xml"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def file_row(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def included(path: Path) -> bool:
    if path in {MANIFEST, RECEIPT}:
        return False
    return path.is_file() and not any(
        part in {"__pycache__", ".pytest_cache", ".ruff_cache"}
        for part in path.parts
    )


def build_source_delta() -> dict[str, dict[str, object]]:
    chunks: list[str] = []
    rows: dict[str, dict[str, object]] = {}
    for relative in CHANGED_PATHS:
        base = R1_ROOT / relative
        candidate = ROOT / relative
        base_text = base.read_text(encoding="utf-8").splitlines(keepends=True)
        candidate_text = candidate.read_text(encoding="utf-8").splitlines(
            keepends=True
        )
        chunks.extend(
            difflib.unified_diff(
                base_text,
                candidate_text,
                fromfile=f"r1/{relative}",
                tofile=f"r2/{relative}",
            )
        )
        rows[relative] = {
            "r1_sha256": sha256_file(base),
            "r2_sha256": sha256_file(candidate),
            "r2_size": candidate.stat().st_size,
        }
    DIFF_PATH.write_text("".join(chunks), encoding="utf-8", newline="\n")
    return rows


def main() -> None:
    if sha256_file(R1_ARCHIVE) != R1_ARCHIVE_SHA256:
        raise SystemExit("R1 archive hash mismatch")
    if sha256_file(R1_MANIFEST) != R1_MANIFEST_SHA256:
        raise SystemExit("R1 manifest hash mismatch")
    r1_manifest_data = json.loads(R1_MANIFEST.read_text(encoding="utf-8"))
    if r1_manifest_data.get("payload_file_count") != 141:
        raise SystemExit("R1 payload count mismatch")

    source_delta = build_source_delta()
    payload_files = [
        file_row(path)
        for path in sorted(ROOT.rglob("*"))
        if included(path)
    ]
    log_hashes = {
        path.name: sha256_file(path)
        for path in sorted((ROOT / "evidence" / "r2-loader-identity").glob("*"))
        if path.is_file()
    }
    changed_map = {
        path: {
            "size": (ROOT / path).stat().st_size,
            "sha256": sha256_file(ROOT / path),
        }
        for path in (*CHANGED_PATHS, "README.md")
    }
    manifest = {
        "schema": "iteration41.g6s.artifact_first_sdk_binding.r2_manifest.v1",
        "classification": "AUTHOR_CANDIDATE / NO_G4 / NO_G6-S",
        "candidate_root": str(ROOT),
        "base": {
            "r1_root": str(R1_ROOT),
            "r1_archive_path": str(R1_ARCHIVE),
            "r1_archive_sha256": R1_ARCHIVE_SHA256,
            "r1_manifest_sha256": R1_MANIFEST_SHA256,
            "r1_manifest_copy": "evidence/r1-parent/candidate-source-manifest.json",
            "r1_receipt_copy": "evidence/r1-parent/freeze-receipt.json",
            "r1_payload_file_count": 141,
        },
        "candidate_changes": {
            "files": changed_map,
            "source_delta": source_delta,
            "patch_path": DIFF_PATH.relative_to(ROOT).as_posix(),
            "patch_sha256": sha256_file(DIFF_PATH),
            "summary": [
                "Capture the importlib module, util/machinery modules, ModuleSpec/module_from_spec, standard finder classes and finder method descriptors, and ExtensionFileLoader class/method descriptors used by the gate.",
                "Recheck these exact identities on every cached-artifact validation and immediately after retained native-extension bytes are hashed, before invoking the captured extension exec descriptor.",
                "Bind the exact per-module ModuleSpec, loader, name, and native origin before loader execution; check extension delegate type/name/path before delegate create/exec.",
                "Adversarial fake tests replace ExtensionFileLoader after the gate and during retained .pyd hash read, and mutate ModuleSpec, module_from_spec, and PathFinder.find_spec; all reject before a replacement hook is called.",
            ],
        },
        "verification": {
            "python_executable": r"C:\anaconda3\python.exe",
            "python_version": "3.11.5",
            "cwd": str(ROOT),
            "environment": {
                "PYTHONPATH": str(ROOT),
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            "pytest": {
                "command": "python -m pytest --noconftest tests\\unit\\runtime\\test_ctp_sdk_artifact_binding.py tests\\unit\\runtime\\test_ctp_windows_artifact_custody.py tests\\unit\\runtime\\test_ctp_simnow_td_trading_readiness.py -q --tb=short --junitxml=evidence\\r2-loader-identity\\pytest-focus.junit.xml",
                "result": "52 passed, 0 skipped, exit 0",
                "stdout_path": "evidence/r2-loader-identity/pytest-focus.stdout.txt",
                "stdout_sha256": sha256_file(PYTEST_LOG),
                "junit_path": "evidence/r2-loader-identity/pytest-focus.junit.xml",
                "junit_sha256": sha256_file(JUNIT),
            },
            "static_checks": {
                "ruff_check": "passed for both changed Python files",
                "ruff_check_log_sha256": sha256_file(
                    ROOT / "evidence/r2-loader-identity/ruff-check.stdout.txt"
                ),
                "ruff_format": "passed for both changed Python files",
                "ruff_format_log_sha256": sha256_file(
                    ROOT / "evidence/r2-loader-identity/ruff-format.stdout.txt"
                ),
                "compile": "compile() passed for both changed Python files; no bytecode emitted",
                "compile_log_sha256": sha256_file(
                    ROOT / "evidence/r2-loader-identity/compile.stdout.txt"
                ),
            },
            "fresh_import_guard": {
                "result": "both candidate modules imported from R2; code-owned artifact policy is None; zero bt_api_ctp modules loaded",
                "stdout_path": "evidence/r2-loader-identity/fresh-import-guard.stdout.txt",
                "stdout_sha256": sha256_file(
                    ROOT / "evidence/r2-loader-identity/fresh-import-guard.stdout.txt"
                ),
            },
            "pre_fix_run": {
                "disposition": "preserved as exploratory and superseded; sys.modules spoof failed with a later identity-change reason; final importer-context fence now rejects first",
                "path": "evidence/r2-loader-identity/pre-fix-run.txt",
                "sha256": sha256_file(
                    ROOT / "evidence/r2-loader-identity/pre-fix-run.txt"
                ),
            },
            "diagnostic_files_sha256": log_hashes,
            "cpython_loader_basis": {
                "interpreter": r"C:\anaconda3\python.exe CPython 3.11.5",
                "stdlib_source": r"C:\anaconda3\Lib\importlib\_bootstrap_external.py",
                "excerpt_path": "evidence/r2-loader-identity/cpython-extension-loader-source.txt",
                "excerpt_sha256": sha256_file(
                    ROOT / "evidence/r2-loader-identity/cpython-extension-loader-source.txt"
                ),
                "finding": "ExtensionFileLoader accepts name/path and calls _imp.create_dynamic(spec) and _imp.exec_dynamic(module); no retained-handle argument is exposed.",
            },
        },
        "limitations": [
            "No real SDK/native module import or execution; the .pyd fixture bytes are inert.",
            "CPython's standard ExtensionFileLoader remains path-based. R2 checks loader identity but cannot prove the OS image loader consumed the retained custody handle.",
            "Same-process Python checks are not a security boundary against hostile code that can mutate interpreter internals or call native APIs directly.",
            "No approved installed wheel, release signature, protected deployment trust root, or code-owned artifact pin; default policy remains None.",
            "No provider, network, credentials, or private configuration access; main repository/default route unchanged.",
        ],
        "acceptance": {
            "G4": False,
            "G6S": False,
            "default_artifact_policy": None,
            "production_route_changed": False,
            "native_loaded_or_called": False,
            "provider_or_network_called": False,
            "credentials_or_private_config_read": False,
            "main_repository_modified": False,
            "sdk_candidate_modified": False,
        },
        "payload_file_count": len(payload_files),
        "payload_files": payload_files,
    }
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_sha = sha256_file(MANIFEST)
    receipt = {
        "schema": "iteration41.g6s.artifact_first_sdk_binding.r2_freeze_receipt.v1",
        "status": "AUTHOR_CANDIDATE / NO_G4 / NO_G6-S",
        "manifest_path": MANIFEST.name,
        "manifest_sha256": manifest_sha,
        "candidate_root": str(ROOT),
        "r1_manifest_sha256": R1_MANIFEST_SHA256,
        "payload_file_count": len(payload_files),
        "pytest_result": "52 passed, 0 skipped, exit 0",
        "main_repository_modified": False,
        "default_route_or_pin_changed": False,
        "native_loaded_or_called": False,
        "provider_or_network_called": False,
        "credentials_or_private_config_read": False,
        "G4_accepted": False,
        "G6S_accepted": False,
        "blocking_residual": "CPython ExtensionFileLoader remains path-based; no same-handle OS image-load proof, external artifact pin, or deployment trust root.",
    }
    RECEIPT.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "manifest_sha256": manifest_sha,
                "receipt_sha256": sha256_file(RECEIPT),
                "payload_file_count": len(payload_files),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
