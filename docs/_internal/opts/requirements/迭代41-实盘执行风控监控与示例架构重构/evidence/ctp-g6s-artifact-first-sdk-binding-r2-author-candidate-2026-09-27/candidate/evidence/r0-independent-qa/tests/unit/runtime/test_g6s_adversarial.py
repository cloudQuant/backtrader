from __future__ import annotations

import hashlib
import importlib
import importlib.machinery
import inspect
import sys
import types
import zipfile
from pathlib import Path

import pytest

import backtrader_runtime.ctp_sdk_artifact_binding as binding
import backtrader_runtime.ctp_simnow_td_trading_readiness as readiness
from test_ctp_sdk_artifact_binding import (
    _CERT_MODULE,
    _DIST,
    _build_fake_distribution,
    _clear_sdk_modules,
    _use_standard_import_chain,
)


def _set_artifact_context(monkeypatch, root: Path):
    root.mkdir(parents=True, exist_ok=True)
    policy = _build_fake_distribution(root)
    monkeypatch.setattr(sys, "path", [str(root)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _use_standard_import_chain(monkeypatch)
    monkeypatch.setattr(binding, "_CODE_OWNED_ARTIFACT_POLICY", policy)
    return policy


def test_nested_sys_modules_contamination_rejected_before_distribution_scan(tmp_path, monkeypatch):
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    policy = _set_artifact_context(monkeypatch, root)
    contaminated = types.ModuleType(_CERT_MODULE)
    monkeypatch.setitem(sys.modules, _CERT_MODULE, contaminated)
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._discover_synthetic_distribution_for_tests(policy)
    assert raised.value.reason == "sdk_artifact_check_after_import"


def test_valid_zip_path_is_rejected_as_non_directory_import_root(tmp_path, monkeypatch):
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    policy = _set_artifact_context(monkeypatch, root)
    archive = tmp_path / "shadow.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("bt_api_ctp/__init__.py", "raise RuntimeError('must not execute')\n")
    monkeypatch.setattr(sys, "path", [str(root), str(archive)])
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._discover_synthetic_distribution_for_tests(policy)
    assert raised.value.reason == "sdk_artifact_non_directory_import_path"


def test_native_extension_bytes_mismatch_rejected_without_extension_execution(tmp_path, monkeypatch):
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    policy = _build_fake_distribution(root)
    relative = policy.extension_paths[0]
    extension = root.joinpath(*relative.split("/"))
    artifact = binding.VerifiedCtpSdkArtifact(
        distribution_root=str(root),
        package_root=str(root / "bt_api_ctp"),
        dist_info_root=str(root / "bt_api_ctp-2.4.0+fake.dist-info"),
        version=policy.version,
        record_sha256=policy.record_sha256,
        source_manifest_sha256=policy.source_manifest_sha256,
        file_sha256=tuple(sorted(policy.files.items())),
        module_origins=(),
        extension_paths=(binding._absolute(str(extension)),),
    )
    fullname = "bt_api_ctp.ctp._ctp"
    loader = importlib.machinery.ExtensionFileLoader(fullname, str(extension))
    spec = importlib.machinery.ModuleSpec(fullname, loader, origin=str(extension))
    inert = types.ModuleType(fullname)
    inert.__spec__ = spec
    inert.__file__ = str(extension)
    monkeypatch.setitem(sys.modules, fullname, inert)
    extension.write_bytes(extension.read_bytes() + b"tampered")
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._verify_loaded_native_extension(artifact)
    assert raised.value.reason == "sdk_artifact_native_module_hash_mismatch"
    assert sys.modules[fullname] is inert


def test_preflight_detects_source_change_before_any_sdk_import(tmp_path, monkeypatch):
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    policy = _set_artifact_context(monkeypatch, root)
    target = root / "bt_api_ctp/containers/ctp/ctp_native_query_certificate.py"
    target.write_bytes(target.read_bytes() + b"# invalid before gate\n")
    imports = []
    original = importlib.import_module

    def tracked(name, package=None):
        imports.append(name)
        return original(name, package)

    monkeypatch.setattr(binding.importlib, "import_module", tracked)
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._load_code_owned_settlement_verifier()
    assert raised.value.reason == "sdk_artifact_record_file_mismatch"
    assert imports == []
    assert not any(name == _DIST or name.startswith(_DIST + ".") for name in sys.modules)


def test_file_swap_between_hash_scan_and_import_executes_before_late_rejection(tmp_path, monkeypatch):
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    _set_artifact_context(monkeypatch, root)
    target = root / "bt_api_ctp/containers/ctp/ctp_native_query_certificate.py"
    marker = tmp_path / "untrusted-source-executed.txt"
    malicious = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
        "class CtpSettlementConfirmationEvidence: pass\n"
        "class CtpSettlementConfirmationEvidenceBuilder:\n"
        "    def __init__(self, client): self.client = client\n"
        "    def build(self, result): return CtpSettlementConfirmationEvidence()\n"
    ).encode("utf-8")
    original = importlib.import_module
    swapped = False

    def replace_at_import(name, package=None):
        nonlocal swapped
        if name == _CERT_MODULE and not swapped:
            target.write_bytes(malicious)
            swapped = True
        return original(name, package)

    monkeypatch.setattr(binding.importlib, "import_module", replace_at_import)
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        binding._load_code_owned_settlement_verifier()
    assert swapped is True
    assert marker.read_text(encoding="utf-8") == "ran"
    assert raised.value.reason == "sdk_artifact_loaded_module_hash_mismatch"


def test_post_gate_import_environment_mutation_is_not_rechecked(tmp_path, monkeypatch):
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    _set_artifact_context(monkeypatch, root)
    verifier = binding._load_code_owned_settlement_verifier()
    monkeypatch.setattr(sys, "path", [])
    monkeypatch.setattr(sys, "meta_path", [object()])
    monkeypatch.setattr(sys, "path_hooks", [lambda path: object()])
    verifier.assert_current()


def test_loaded_module_object_replacement_is_rejected(tmp_path, monkeypatch):
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    _set_artifact_context(monkeypatch, root)
    verifier = binding._load_code_owned_settlement_verifier()
    replacement = types.ModuleType(_CERT_MODULE)
    monkeypatch.setitem(sys.modules, _CERT_MODULE, replacement)
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        verifier.verify_current(object(), object())
    assert raised.value.reason == "sdk_artifact_module_identity_changed"


def test_loaded_evidence_class_replacement_is_rejected(tmp_path, monkeypatch):
    _clear_sdk_modules(monkeypatch)
    root = tmp_path / "site-packages"
    _set_artifact_context(monkeypatch, root)
    verifier = binding._load_code_owned_settlement_verifier()
    module = sys.modules[_CERT_MODULE]
    module.CtpSettlementConfirmationEvidence = type(
        "CtpSettlementConfirmationEvidence", (), {"__module__": _CERT_MODULE}
    )
    with pytest.raises(binding.CtpSdkArtifactBindingError) as raised:
        verifier.verify_current(object(), object())
    assert raised.value.reason == "sdk_artifact_evidence_type_identity_changed"


def test_public_preclient_gate_has_no_policy_or_root_argument():
    assert tuple(inspect.signature(readiness.require_trusted_ctp_sdk_artifact_before_client).parameters) == ()
    with pytest.raises(TypeError):
        readiness.require_trusted_ctp_sdk_artifact_before_client(policy=object())
