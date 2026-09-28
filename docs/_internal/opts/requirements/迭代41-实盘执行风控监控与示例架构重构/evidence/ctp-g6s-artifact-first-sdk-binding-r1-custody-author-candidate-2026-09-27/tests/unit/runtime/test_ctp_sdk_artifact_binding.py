"""Fake installed-artifact tests; the CTP extension is never loaded."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import importlib._bootstrap_external
import importlib.machinery
import os
import shutil
import sys
import tempfile
import types
import zipimport
from pathlib import Path
from typing import Any

import pytest

import backtrader_runtime.ctp_sdk_artifact_binding as binding
import backtrader_runtime.ctp_simnow_td_trading_readiness as readiness

_DIST = "bt_api_ctp"
_VERSION = "2.4.0+fake"
_SOURCE_MANIFEST = "a" * 64
_CERT_MODULE = "bt_api_ctp.containers.ctp.ctp_native_query_certificate"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record_hash(raw: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(
        hashlib.sha256(raw).digest()
    ).decode().rstrip("=")


def _write(root: Path, relative: str, raw: bytes) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


@pytest.fixture
def secure_install_root(monkeypatch: pytest.MonkeyPatch) -> Any:
    parent = Path(os.environ["USERPROFILE"]) / "Temp"
    if not parent.is_dir():
        pytest.skip("protected per-user Temp directory is unavailable")
    root = Path(tempfile.mkdtemp(prefix="iter41-sdk-fake-", dir=parent))
    yield root
    _clear_sdk_modules(monkeypatch)
    shutil.rmtree(root, ignore_errors=True)


def _build_fake_distribution(
    root: Path, *, evidence_source: bytes = b""
) -> binding.CtpSdkArtifactPolicy:
    if not evidence_source:
        evidence_source = (
            b"class CtpSettlementConfirmationEvidence:\n"
            b"    pass\n"
            b"class CtpSettlementConfirmationEvidenceBuilder:\n"
            b"    def __init__(self, client): self.client = client\n"
            b"    def build(self, result): return CtpSettlementConfirmationEvidence()\n"
        )
    package_files = {
        "bt_api_ctp/__init__.py": b"\n",
        "bt_api_ctp/containers/__init__.py": b"\n",
        "bt_api_ctp/containers/ctp/__init__.py": b"\n",
        "bt_api_ctp/containers/ctp/ctp_native_query_certificate.py": evidence_source,
        "bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd": b"not a native image; inert fixture bytes",
    }
    for relative, raw in package_files.items():
        _write(root, relative, raw)

    dist_info = root / "bt_api_ctp-2.4.0+fake.dist-info"
    metadata_raw = b"Metadata-Version: 2.1\nName: bt_api_ctp\nVersion: 2.4.0+fake\n\n"
    (dist_info / "METADATA").parent.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_bytes(metadata_raw)
    record_relative = "bt_api_ctp-2.4.0+fake.dist-info/RECORD"
    rows = [
        [relative, _record_hash(raw), str(len(raw))]
        for relative, raw in sorted(package_files.items())
    ]
    rows.append(
        [
            "bt_api_ctp-2.4.0+fake.dist-info/METADATA",
            _record_hash(metadata_raw),
            str(len(metadata_raw)),
        ]
    )
    rows.append([record_relative, "", ""])
    record_path = root.joinpath(*record_relative.split("/"))
    with record_path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerows(rows)
    record_raw = record_path.read_bytes()
    return binding.CtpSdkArtifactPolicy(
        distribution_name=_DIST,
        version=_VERSION,
        record_sha256=_sha(record_raw),
        source_manifest_sha256=_SOURCE_MANIFEST,
        files={relative: _sha(raw) for relative, raw in package_files.items()},
        module_files={
            "bt_api_ctp": "bt_api_ctp/__init__.py",
            "bt_api_ctp.containers": "bt_api_ctp/containers/__init__.py",
            "bt_api_ctp.containers.ctp": "bt_api_ctp/containers/ctp/__init__.py",
            _CERT_MODULE: "bt_api_ctp/containers/ctp/ctp_native_query_certificate.py",
        },
        extension_paths=("bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd",),
    )


def _clear_sdk_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = binding._CODE_OWNED_VERIFIER_CACHE
    importer = binding._CODE_OWNED_IMPORTER
    if importer is not None:
        importer.close_after_failure()
    if verifier is not None and verifier._artifact.custody is not None:
        verifier._artifact.custody.close()
    monkeypatch.setattr(binding, "_CODE_OWNED_VERIFIER_CACHE", None)
    monkeypatch.setattr(binding, "_CODE_OWNED_IMPORTER", None)
    for name in tuple(sys.modules):
        if name == _DIST or name.startswith(_DIST + "."):
            monkeypatch.delitem(sys.modules, name, raising=False)


def _use_standard_import_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "meta_path",
        [
            importlib.machinery.BuiltinImporter,
            importlib.machinery.FrozenImporter,
            importlib.machinery.PathFinder,
        ],
    )
    monkeypatch.setattr(
        sys,
        "path_hooks",
        [
            zipimport.zipimporter,
            importlib._bootstrap_external.FileFinder.path_hook(
                *importlib._bootstrap_external._get_supported_file_loaders()
            ),
        ],
    )
    monkeypatch.setattr(sys, "path_importer_cache", {})


def test_production_gate_has_no_default_artifact_pin_and_touches_no_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    monkeypatch.setattr(binding, "_CODE_OWNED_ARTIFACT_POLICY", None)

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        readiness.require_trusted_ctp_sdk_artifact_before_client()

    assert raised.value.reason == "sdk_artifact_release_pin_unavailable"
    assert not any(
        name == _DIST or name.startswith(_DIST + ".") for name in sys.modules
    )


def test_public_readiness_cannot_accept_caller_verifier_or_touch_client_without_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(binding, "_CODE_OWNED_ARTIFACT_POLICY", None)
    monkeypatch.setattr(binding, "_CODE_OWNED_VERIFIER_CACHE", None)

    class NeverTouch:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"client touched before artifact pin: {name}")

    with pytest.raises(readiness.CtpSimNowTdTradingReadinessError) as raised:
        readiness.verify_ctp_simnow_td_trading_readiness(
            NeverTouch(),
            object(),
            object(),
            native_readiness=object(),
        )
    assert raised.value.reason == "sdk_artifact_preclient_gate_required"
    assert raised.value.close_state == "not_started"
    with pytest.raises(TypeError):
        readiness.verify_ctp_simnow_td_trading_readiness(
            NeverTouch(),
            object(),
            object(),
            native_readiness=object(),
            settlement_evidence_verifier=object(),  # type: ignore[call-arg]
        )


def test_exact_fake_install_binds_record_module_origin_and_evidence_class(
    secure_install_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = secure_install_root
    policy = _build_fake_distribution(root)
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    monkeypatch.setattr(binding, "_CODE_OWNED_ARTIFACT_POLICY", policy)

    verifier = binding._load_code_owned_settlement_verifier()
    module = sys.modules[_CERT_MODULE]
    evidence = verifier.verify_current(object(), object())

    assert type(evidence) is module.CtpSettlementConfirmationEvidence
    assert verifier.evidence_type is module.CtpSettlementConfirmationEvidence
    assert binding._absolute(module.__spec__.origin) == binding._absolute(
        str(root / "bt_api_ctp/containers/ctp/ctp_native_query_certificate.py")
    )
    assert type(module.__spec__.loader).__name__ == "_RetainedSourceLoader"
    assert binding._CODE_OWNED_VERIFIER_CACHE._artifact.custody is not None
    assert verifier.source_manifest_sha256 == _SOURCE_MANIFEST


def test_preclient_binding_rechecks_source_bytes_before_readiness(
    secure_install_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = secure_install_root
    policy = _build_fake_distribution(root)
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    monkeypatch.setattr(binding, "_CODE_OWNED_ARTIFACT_POLICY", policy)

    assert readiness.require_trusted_ctp_sdk_artifact_before_client() is None
    source = root / "bt_api_ctp/containers/ctp/ctp_native_query_certificate.py"
    with pytest.raises(PermissionError):
        source.write_bytes(source.read_bytes() + b"# changed after preclient seal\n")
    assert (
        binding._get_preclient_code_owned_verifier()
        is binding._CODE_OWNED_VERIFIER_CACHE
    )


@pytest.mark.parametrize("field", ["path", "meta_path", "path_hooks", "importer_cache"])
def test_import_environment_mutation_rejects_cached_artifact_before_use(
    secure_install_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = secure_install_root
    policy = _build_fake_distribution(root)
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    monkeypatch.setattr(binding, "_CODE_OWNED_ARTIFACT_POLICY", policy)

    readiness.require_trusted_ctp_sdk_artifact_before_client()
    if field == "path":
        monkeypatch.setattr(sys, "path", [str(root), str(root / "untrusted-shadow")])
    elif field == "meta_path":
        monkeypatch.setattr(sys, "meta_path", [object()])
    elif field == "path_hooks":
        monkeypatch.setattr(sys, "path_hooks", [])
    else:
        monkeypatch.setattr(sys, "path_importer_cache", {})
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._get_preclient_code_owned_verifier()
    assert raised.value.reason == "sdk_artifact_import_environment_changed"


def test_sys_modules_replacement_rejects_cached_artifact_before_use(
    secure_install_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = secure_install_root
    policy = _build_fake_distribution(root)
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    monkeypatch.setattr(binding, "_CODE_OWNED_ARTIFACT_POLICY", policy)

    readiness.require_trusted_ctp_sdk_artifact_before_client()
    monkeypatch.setitem(sys.modules, _DIST, type("SpoofedPackage", (), {})())
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._get_preclient_code_owned_verifier()
    assert raised.value.reason == "sdk_artifact_sys_modules_spoof"


def test_swap_after_hash_scan_but_before_custody_never_imports_marker(
    secure_install_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = secure_install_root
    policy = _build_fake_distribution(root)
    source = root / "bt_api_ctp/containers/ctp/ctp_native_query_certificate.py"
    replacement = root / "swap-before-custody.py"
    marker = root / "pre-custody-marker.txt"
    replacement.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='ascii')\n",
        encoding="utf-8",
    )
    original_acquire = binding._acquire_windows_artifact_custody
    race: list[str] = []

    def replace_before_acquire(**kwargs: object) -> object:
        os.replace(replacement, source)
        race.append("replacement-installed-before-custody")
        return original_acquire(**kwargs)

    monkeypatch.setattr(
        binding, "_acquire_windows_artifact_custody", replace_before_acquire
    )
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    monkeypatch.setattr(binding, "_CODE_OWNED_ARTIFACT_POLICY", policy)

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        readiness.require_trusted_ctp_sdk_artifact_before_client()
    assert race == ["replacement-installed-before-custody"]
    assert raised.value.reason == "sdk_artifact_custody_acquire_failed"
    assert not marker.exists()
    assert not any(
        name == _DIST or name.startswith(_DIST + ".") for name in sys.modules
    )


def test_source_swap_after_custody_cannot_execute_replacement_marker(
    secure_install_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = secure_install_root
    policy = _build_fake_distribution(root)
    source = root / "bt_api_ctp/containers/ctp/ctp_native_query_certificate.py"
    replacement = root / "swap.py"
    marker = root / "malicious-marker.txt"
    replacement.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='ascii')\n",
        encoding="utf-8",
    )
    attacks: list[str] = []
    original_install = binding._PinnedSdkImporter.install

    def install_then_replace(importer: object) -> None:
        original_install(importer)
        try:
            os.replace(replacement, source)
            attacks.append("replace_succeeded")
        except OSError as error:
            attacks.append(f"blocked:{getattr(error, 'winerror', None)}")

    monkeypatch.setattr(binding._PinnedSdkImporter, "install", install_then_replace)
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    monkeypatch.setattr(binding, "_CODE_OWNED_ARTIFACT_POLICY", policy)

    readiness.require_trusted_ctp_sdk_artifact_before_client()
    assert attacks and attacks[0].startswith("blocked:")
    assert not marker.exists()
    assert source.read_bytes() == policy_source_bytes(policy, source, root)


def policy_source_bytes(
    policy: binding.CtpSdkArtifactPolicy, source: Path, root: Path
) -> bytes:
    relative = source.relative_to(root).as_posix()
    expected = dict(policy.files)[relative]
    raw = source.read_bytes()
    assert _sha(raw) == expected
    return raw


def test_unpinned_new_package_module_added_after_scan_never_executes(
    secure_install_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = secure_install_root
    evidence_source = b"import bt_api_ctp.injected\n" + (
        b"class CtpSettlementConfirmationEvidence:\n"
        b"    pass\n"
        b"class CtpSettlementConfirmationEvidenceBuilder:\n"
        b"    def __init__(self, client): self.client = client\n"
        b"    def build(self, result): return CtpSettlementConfirmationEvidence()\n"
    )
    policy = _build_fake_distribution(root, evidence_source=evidence_source)
    injected = root / "bt_api_ctp/injected.py"
    marker = root / "injected-marker.txt"
    original_install = binding._PinnedSdkImporter.install

    def install_then_add_module(importer: object) -> None:
        original_install(importer)
        injected.write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='ascii')\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(binding._PinnedSdkImporter, "install", install_then_add_module)
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    monkeypatch.setattr(binding, "_CODE_OWNED_ARTIFACT_POLICY", policy)

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        readiness.require_trusted_ctp_sdk_artifact_before_client()
    assert raised.value.reason == "sdk_artifact_unpinned_module_import"
    assert not marker.exists()


def test_same_name_and_module_spoof_is_rejected_by_exact_class_identity() -> None:
    class TrustedEvidence:
        pass

    SpoofedEvidence = type(
        "CtpSettlementConfirmationEvidence",
        (),
        {"__module__": _CERT_MODULE},
    )

    assert SpoofedEvidence.__name__ == "CtpSettlementConfirmationEvidence"
    assert SpoofedEvidence.__module__ == _CERT_MODULE
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._require_exact_evidence_type(SpoofedEvidence(), TrustedEvidence)
    assert raised.value.reason == "sdk_artifact_evidence_type_identity_mismatch"


def test_modified_source_bytes_fail_record_validation_before_sdk_import(
    tmp_path: Path,
) -> None:
    root = tmp_path / "site-packages"
    root.mkdir()
    policy = _build_fake_distribution(root)
    target = root / "bt_api_ctp/containers/ctp/ctp_native_query_certificate.py"
    target.write_bytes(target.read_bytes() + b"# modified\n")

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._validate_synthetic_distribution_for_tests(
            distribution_root=str(root),
            package_root=str(root / "bt_api_ctp"),
            dist_info_root=str(root / "bt_api_ctp-2.4.0+fake.dist-info"),
            policy=policy,
        )
    assert raised.value.reason == "sdk_artifact_record_file_mismatch"


def test_duplicate_installed_distribution_roots_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    first = tmp_path / "first"
    first.mkdir()
    policy = _build_fake_distribution(first)
    second = tmp_path / "second"
    shutil.copytree(first, second)
    monkeypatch.setattr(sys, "path", [str(first), str(second)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._discover_synthetic_distribution_for_tests(policy)
    assert raised.value.reason == "sdk_artifact_installation_not_unique"


def test_empty_path_entry_cannot_hide_a_second_import_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    root.mkdir()
    policy = _build_fake_distribution(root)
    monkeypatch.setattr(sys, "path", [str(root), ""])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._discover_synthetic_distribution_for_tests(policy)
    assert raised.value.reason == "sdk_artifact_path_entry_invalid"


def test_existing_archive_path_cannot_hide_a_second_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    root.mkdir()
    policy = _build_fake_distribution(root)
    archive = tmp_path / "shadow.zip"
    archive.write_bytes(b"inert archive placeholder")
    monkeypatch.setattr(sys, "path", [str(root), str(archive)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._discover_synthetic_distribution_for_tests(policy)
    assert raised.value.reason == "sdk_artifact_non_directory_import_path"


def test_nonstandard_path_hook_is_rejected_before_install_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    root.mkdir()
    policy = _build_fake_distribution(root)
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    monkeypatch.setattr(sys, "path_hooks", [lambda _path: object()])

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._discover_synthetic_distribution_for_tests(policy)
    assert raised.value.reason == "sdk_artifact_path_hooks_modified"


def test_cached_custom_finder_is_rejected_before_install_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    root.mkdir()
    policy = _build_fake_distribution(root)
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    monkeypatch.setattr(sys, "path_importer_cache", {str(root): object()})

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._discover_synthetic_distribution_for_tests(policy)
    assert raised.value.reason == "sdk_artifact_cached_importer_modified"


def test_bytecode_cache_cannot_shadow_verified_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "site-packages"
    root.mkdir()
    policy = _build_fake_distribution(root)
    pycache = root / "bt_api_ctp/__pycache__"
    pycache.mkdir()
    (pycache / "__init__.cpython-311.pyc").write_bytes(b"forged pyc marker")
    monkeypatch.setattr(sys, "dont_write_bytecode", True)

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._validate_synthetic_distribution_for_tests(
            distribution_root=str(root),
            package_root=str(root / "bt_api_ctp"),
            dist_info_root=str(root / "bt_api_ctp-2.4.0+fake.dist-info"),
            policy=policy,
        )
    assert raised.value.reason == "sdk_artifact_bytecode_cache_present"


def test_sdk_already_imported_means_artifact_check_was_too_late(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "site-packages"
    root.mkdir()
    policy = _build_fake_distribution(root)
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    fake = importlib.util.module_from_spec(
        importlib.machinery.ModuleSpec(_DIST, loader=None, is_package=True)
    )
    monkeypatch.setitem(sys.modules, _DIST, fake)

    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._discover_synthetic_distribution_for_tests(policy)
    assert raised.value.reason == "sdk_artifact_check_after_import"


def test_native_extension_origin_and_digest_can_be_checked_without_loading_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "site-packages"
    root.mkdir()
    policy = _build_fake_distribution(root)
    extension_relative = policy.extension_paths[0]
    extension_path = root.joinpath(*extension_relative.split("/"))
    artifact = binding.VerifiedCtpSdkArtifact(
        distribution_root=str(root),
        package_root=str(root / "bt_api_ctp"),
        dist_info_root=str(root / "bt_api_ctp-2.4.0+fake.dist-info"),
        version=policy.version,
        record_sha256=policy.record_sha256,
        source_manifest_sha256=policy.source_manifest_sha256,
        file_sha256=tuple(sorted(policy.files.items())),
        module_origins=(),
        extension_paths=(binding._absolute(str(extension_path)),),
    )
    fullname = "bt_api_ctp.ctp._ctp"
    loader = importlib.machinery.ExtensionFileLoader(fullname, str(extension_path))
    spec = importlib.machinery.ModuleSpec(fullname, loader, origin=str(extension_path))
    inert_module = types.ModuleType(fullname)
    inert_module.__spec__ = spec
    inert_module.__file__ = str(extension_path)
    monkeypatch.setitem(sys.modules, fullname, inert_module)

    binding._verify_loaded_native_extension(artifact)
    assert fullname in sys.modules  # inert object; loader.exec_module was never called
    assert inert_module.__file__ == str(extension_path)

    inert_module.__file__ = str(root / "outside.pyd")
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._verify_loaded_native_extension(artifact)
    assert raised.value.reason == "sdk_artifact_native_module_origin_mismatch"
