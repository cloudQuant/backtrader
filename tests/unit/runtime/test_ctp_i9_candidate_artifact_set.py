"""Offline contracts for the versioned I9 CTP bridge artifact set."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import sys
import zipfile
from importlib.machinery import ModuleSpec
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from types import ModuleType

import pytest

from backtrader_runtime import ctp_i9_candidate_artifact_set as candidate


def test_i9_artifact_set_manifest_pins_the_reviewed_wheel_trio() -> None:
    assert candidate.CTP_I9_CANDIDATE_ARTIFACT_SET_ID == "iteration41-simnow-i9-execution-v1"
    assert candidate.CTP_I9_CANDIDATE_ARTIFACT_SET_VERSION == 1
    assert [
        (
            item.distribution,
            item.version,
            item.wheel_sha256,
            item.wheel_record_sha256,
            item.source_commit,
        )
        for item in candidate.CTP_I9_CANDIDATE_ARTIFACTS
    ] == [
        (
            "bt_api_base",
            "0.15.5",
            "1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d",
            "db6239c41b62b1f8f88b26160c4ba12a88c02f6d0f7f5b2d22a417be5c495845",
            None,
        ),
        (
            "bt_api_ctp",
            "2.0.4+iteration41.i9",
            "7148c4cecc8438426f2ddbe1ee0da0e06d6eb5aa0c699ab901f4cf3e42dc6502",
            "d9974746bd0f406a54c4d12870ba17cbd192e8ef152f63ac89c8b5f91d9b06f6",
            "19349b8abd546aa4f1522fee674611a9a455e36e",
        ),
        (
            "bt_api_execution",
            "0.2.0",
            "352c26db7636868710dbe28ea0583f49db619dd06e3b9c1f258b69fe68e51787",
            "d01ab964f1e2313b1a7614508bd5a5738fbeb23bf412df8346800ac9b58d4d72",
            "60102bfc493ecc4aa889982d5d8b3a1228e02c92",
        ),
    ]
    assert candidate._manifest_sha256() == candidate.CTP_I9_CANDIDATE_ARTIFACT_SET_SHA256


def test_exact_wheel_install_passes_and_source_import_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, distribution, install_root = _build_installed_fixture(tmp_path)
    _install_fixture_import_context(artifact, distribution, install_root, monkeypatch)

    candidate._verify_one_artifact(artifact)

    source_root = tmp_path / "checkout" / artifact.module
    source_root.mkdir(parents=True)
    (source_root / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        candidate.importlib.util,
        "find_spec",
        lambda module: SimpleNamespace(
            origin=str(source_root / "__init__.py"),
            submodule_search_locations=[str(source_root)],
        ),
    )

    with pytest.raises(candidate.CtpCandidateArtifactSetError) as error:
        candidate._verify_one_artifact(artifact)
    assert error.value.reason == "artifact_import_rejected"


def test_editable_source_origin_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, distribution, install_root = _build_installed_fixture(tmp_path)
    _install_fixture_import_context(artifact, distribution, install_root, monkeypatch)
    distribution.direct_url = json.dumps(
        {"url": (tmp_path / "checkout").as_uri(), "dir_info": {"editable": True}}
    )

    with pytest.raises(candidate.CtpCandidateArtifactSetError) as error:
        candidate._verify_one_artifact(artifact)
    assert error.value.reason == "artifact_origin_not_wheel"


def test_mixed_wheel_digest_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact, distribution, install_root = _build_installed_fixture(tmp_path)
    _install_fixture_import_context(artifact, distribution, install_root, monkeypatch)
    direct_url = json.loads(distribution.direct_url)
    direct_url["archive_info"]["hash"] = "sha256=" + "0" * 64
    direct_url["archive_info"]["hashes"]["sha256"] = "0" * 64
    distribution.direct_url = json.dumps(direct_url)

    with pytest.raises(candidate.CtpCandidateArtifactSetError) as error:
        candidate._verify_one_artifact(artifact)
    assert error.value.reason == "artifact_origin_hash_mismatch"


@pytest.mark.parametrize("loaded_name", ["bt_api_base", "bt_api_ctp.injected"])
def test_public_verifier_rejects_preloaded_module_with_forged_spec_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loaded_name: str
) -> None:
    module_root = loaded_name.split(".", 1)[0]
    trusted_origin = tmp_path / "site-packages" / module_root / "__init__.py"
    untrusted_origin = tmp_path / "checkout" / "src" / module_root / "__init__.py"
    trusted_origin.parent.mkdir(parents=True)
    trusted_origin.write_text("VALUE = 'site-packages'\n", encoding="utf-8")
    untrusted_origin.parent.mkdir(parents=True)
    untrusted_origin.write_text("VALUE = 'checkout'\n", encoding="utf-8")
    fake_module = ModuleType(loaded_name)
    fake_module.__file__ = str(untrusted_origin)
    fake_module.__spec__ = ModuleSpec(loaded_name, loader=None, origin=str(trusted_origin))
    monkeypatch.setitem(sys.modules, loaded_name, fake_module)
    monkeypatch.setattr(
        candidate.importlib.metadata,
        "distribution",
        lambda name: pytest.fail("must reject preloaded target before metadata lookup"),
    )

    with pytest.raises(candidate.CtpCandidateArtifactSetError) as error:
        candidate.verify_ctp_i9_candidate_artifact_set()

    assert error.value.reason == "artifact_import_preloaded"


def _build_installed_fixture(tmp_path: Path):
    module = "bt_api_fixture"
    version = "1.0"
    dist_info = "bt_api_fixture-1.0.dist-info"
    metadata_path = dist_info + "/METADATA"
    wheel_path = tmp_path / "wheelhouse" / "bt_api_fixture-1.0-py3-none-any.whl"
    wheel_path.parent.mkdir()
    payload = {
        module + "/__init__.py": b"VALUE = 1\n",
        metadata_path: b"Metadata-Version: 2.1\nName: bt_api_fixture\nVersion: 1.0\n",
        dist_info
        + "/WHEEL": b"Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    wheel_record_path = dist_info + "/RECORD"
    wheel_record = _record_bytes(payload, wheel_record_path)
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, contents in payload.items():
            archive.writestr(relative, contents)
        archive.writestr(wheel_record_path, wheel_record)

    wheel_sha256 = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    artifact = candidate.CtpCandidateArtifact(
        distribution=module,
        module=module,
        version=version,
        wheel_filename=wheel_path.name,
        wheel_sha256=wheel_sha256,
        wheel_record_sha256=hashlib.sha256(wheel_record).hexdigest(),
        source_commit=None,
        evidence_ref="fixture.md",
    )

    install_root = tmp_path / "site-packages"
    installed_files = dict(payload)
    installed_files[dist_info + "/INSTALLER"] = b"pip\n"
    installed_files[dist_info + "/REQUESTED"] = b""
    direct_url = {
        "archive_info": {
            "hash": "sha256=" + wheel_sha256,
            "hashes": {"sha256": wheel_sha256},
        },
        "url": wheel_path.as_uri(),
    }
    installed_files[dist_info + "/direct_url.json"] = json.dumps(
        direct_url, separators=(",", ":")
    ).encode("utf-8")
    for relative, contents in installed_files.items():
        destination = install_root.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contents)
    installed_files[wheel_record_path] = _record_bytes(installed_files, wheel_record_path)
    record_file = install_root.joinpath(*PurePosixPath(wheel_record_path).parts)
    record_file.write_bytes(installed_files[wheel_record_path])

    class FixtureDistribution:
        metadata = {"Name": module, "Version": version}

        def __init__(self) -> None:
            self.files = tuple(PurePosixPath(relative) for relative in installed_files)
            self.direct_url = installed_files[dist_info + "/direct_url.json"].decode("utf-8")

        def locate_file(self, path: str) -> Path:
            return install_root / path

        def read_text(self, filename: str):
            if filename == "direct_url.json":
                return self.direct_url
            return None

    return artifact, FixtureDistribution(), install_root


def _install_fixture_import_context(
    artifact: candidate.CtpCandidateArtifact,
    distribution,
    install_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = install_root / artifact.module
    monkeypatch.setattr(
        candidate.importlib.metadata,
        "distribution",
        lambda name: distribution if name == artifact.distribution else None,
    )
    monkeypatch.setattr(
        candidate._provenance, "_interpreter_install_roots", lambda: (install_root,)
    )
    monkeypatch.setattr(
        candidate.importlib.util,
        "find_spec",
        lambda module: SimpleNamespace(
            origin=str(package_root / "__init__.py"),
            submodule_search_locations=[str(package_root)],
        ),
    )


def _record_bytes(members: dict[str, bytes], record_path: str) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for relative, contents in members.items():
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).decode("ascii").rstrip("=")
        )
        writer.writerow((relative, "sha256=" + digest, str(len(contents))))
    writer.writerow((record_path, "", ""))
    return output.getvalue().encode("utf-8")
