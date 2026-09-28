"""Versioned, offline artifact-set verifier for the I9 CTP bridge candidate.

This candidate is intentionally not imported by the runtime registry or a
managed CTP composition. It records the exact three-wheel set used by the I9
queue-lease / execution-v0.2 fake-API bridge review and verifies that an
installed environment came from those retained wheel archives. It grants no
provider-session, write, or production authority.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
import re
import stat
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping, Tuple
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from . import ctp_artifact_provenance as _provenance


CTP_I9_CANDIDATE_ARTIFACT_SET_ID = "iteration41-simnow-i9-execution-v1"
CTP_I9_CANDIDATE_ARTIFACT_SET_VERSION = 1

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CtpCandidateArtifactSetError(ValueError):
    """Redacted rejection for this offline candidate artifact set."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("the installed CTP candidate artifact set was rejected")


def _reject(reason: str) -> None:
    raise CtpCandidateArtifactSetError(reason)


@dataclass(frozen=True)
class CtpCandidateArtifact:
    """One exact wheel archive plus its source/evidence identity."""

    distribution: str
    module: str
    version: str
    wheel_filename: str
    wheel_sha256: str
    wheel_record_sha256: str
    source_commit: str | None
    evidence_ref: str

    def __post_init__(self) -> None:
        if (
            type(self.distribution) is not str
            or not self.distribution
            or type(self.module) is not str
            or not re.fullmatch(r"bt_api_[a-z0-9_]+", self.module)
            or type(self.version) is not str
            or not self.version
            or type(self.wheel_filename) is not str
            or Path(self.wheel_filename).name != self.wheel_filename
            or not self.wheel_filename.endswith(".whl")
            or type(self.wheel_sha256) is not str
            or not _SHA256_RE.fullmatch(self.wheel_sha256)
            or type(self.wheel_record_sha256) is not str
            or not _SHA256_RE.fullmatch(self.wheel_record_sha256)
            or (
                self.source_commit is not None
                and not re.fullmatch(r"[0-9a-f]{40}", self.source_commit)
            )
            or type(self.evidence_ref) is not str
            or not self.evidence_ref.endswith(".md")
        ):
            raise ValueError("invalid CTP candidate artifact entry")


# The base artifact is the exact I4-reviewed 0.15.5 wheel. Its independent
# wheel and installed RECORD evidence is retained in the I4 evidence page.
# I9's original combined smoke did not retain PEP 610 provenance for its base
# install, so this manifest deliberately re-tests the combination with an
# explicit archive-backed base install.
_ARTIFACTS = (
    CtpCandidateArtifact(
        distribution="bt_api_base",
        module="bt_api_base",
        version="0.15.5",
        wheel_filename="bt_api_base-0.15.5-py3-none-any.whl",
        wheel_sha256="1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d",
        wheel_record_sha256="db6239c41b62b1f8f88b26160c4ba12a88c02f6d0f7f5b2d22a417be5c495845",
        source_commit=None,
        evidence_ref="ctp-i4-offline-artifact-2026-09-25.md",
    ),
    CtpCandidateArtifact(
        distribution="bt_api_ctp",
        module="bt_api_ctp",
        version="2.0.4+iteration41.i9",
        wheel_filename="bt_api_ctp-2.0.4+iteration41.i9-cp311-cp311-win_amd64.whl",
        wheel_sha256="7148c4cecc8438426f2ddbe1ee0da0e06d6eb5aa0c699ab901f4cf3e42dc6502",
        wheel_record_sha256="d9974746bd0f406a54c4d12870ba17cbd192e8ef152f63ac89c8b5f91d9b06f6",
        source_commit="19349b8abd546aa4f1522fee674611a9a455e36e",
        evidence_ref="ctp-i9-queue-lease-wheel-2026-09-25.md",
    ),
    CtpCandidateArtifact(
        distribution="bt_api_execution",
        module="bt_api_execution",
        version="0.2.0",
        wheel_filename="bt_api_execution-0.2.0-py3-none-any.whl",
        wheel_sha256="352c26db7636868710dbe28ea0583f49db619dd06e3b9c1f258b69fe68e51787",
        wheel_record_sha256="d01ab964f1e2313b1a7614508bd5a5738fbeb23bf412df8346800ac9b58d4d72",
        source_commit="60102bfc493ecc4aa889982d5d8b3a1228e02c92",
        evidence_ref="ctp-execution-v9-unified-offline-review-2026-09-25.md",
    ),
)


@dataclass(frozen=True)
class CtpCandidateArtifactSetReceipt:
    """Value-free result of verifying all three wheel origins and payloads."""

    manifest_id: str
    manifest_version: int
    manifest_sha256: str
    verified_distributions: Tuple[str, ...]


CTP_I9_CANDIDATE_ARTIFACTS: Tuple[CtpCandidateArtifact, ...] = _ARTIFACTS


def _manifest_sha256() -> str:
    payload = [
        {
            "distribution": item.distribution,
            "module": item.module,
            "version": item.version,
            "wheel_filename": item.wheel_filename,
            "wheel_sha256": item.wheel_sha256,
            "wheel_record_sha256": item.wheel_record_sha256,
            "source_commit": item.source_commit,
            "evidence_ref": item.evidence_ref,
        }
        for item in CTP_I9_CANDIDATE_ARTIFACTS
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


CTP_I9_CANDIDATE_ARTIFACT_SET_SHA256 = _manifest_sha256()


def _normalized_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "_", value).lower()


def _require_unloaded_packages(module_names: Tuple[str, ...]) -> None:
    """Require import roots to be absent before consulting find_spec metadata."""

    loaded = tuple(sys.modules)
    for module_name in module_names:
        if any(name == module_name or name.startswith(module_name + ".") for name in loaded):
            _reject("artifact_import_preloaded")


def _safe_relative_path(value: object) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        _reject("artifact_record_invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in ("", ".", "..") or ":" in part for part in path.parts)
    ):
        _reject("artifact_record_invalid")
    return path.as_posix()


def _sha256_record_value(raw: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode(
        "ascii"
    ).rstrip("=")


def _validate_record_rows(
    raw: bytes,
    *,
    expected_self_path: str,
    expected_members: Mapping[str, bytes] | None = None,
    allow_unhashed_pyc: bool = False,
) -> Mapping[str, Tuple[str, str]]:
    try:
        rows = tuple(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error):
        _reject("artifact_record_invalid")
    if not rows:
        _reject("artifact_record_invalid")

    recorded: dict[str, Tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3:
            _reject("artifact_record_invalid")
        relative = _safe_relative_path(row[0])
        if relative in recorded:
            _reject("artifact_record_invalid")
        if relative == expected_self_path or (
            allow_unhashed_pyc and relative.endswith(".pyc") and "/__pycache__/" in relative
        ):
            if row[1] or row[2]:
                _reject("artifact_record_invalid")
        else:
            if not row[1].startswith("sha256=") or not row[2].isdecimal():
                _reject("artifact_record_invalid")
        recorded[relative] = (row[1], row[2])

        if expected_members is not None and relative != expected_self_path:
            member = expected_members.get(relative)
            if member is None:
                _reject("artifact_wheel_record_mismatch")
            if len(member) != int(row[2]) or _sha256_record_value(member) != row[1]:
                _reject("artifact_wheel_record_mismatch")

    if sum(relative == expected_self_path for relative in recorded) != 1:
        _reject("artifact_record_invalid")
    if expected_members is not None:
        expected_paths = set(expected_members) | {expected_self_path}
        if set(recorded) != expected_paths:
            _reject("artifact_wheel_record_mismatch")
    return MappingProxyType(recorded)


def _read_wheel(artifact: CtpCandidateArtifact, wheel_path: Path) -> Mapping[str, bytes]:
    try:
        result = os.lstat(str(wheel_path))
    except OSError:
        _reject("artifact_wheel_unavailable")
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        stat.S_ISLNK(result.st_mode)
        or bool(getattr(result, "st_file_attributes", 0) & reparse_point)
        or not stat.S_ISREG(result.st_mode)
    ):
        _reject("artifact_wheel_invalid")
    try:
        raw_wheel = wheel_path.read_bytes()
    except OSError:
        _reject("artifact_wheel_unavailable")
    if hashlib.sha256(raw_wheel).hexdigest() != artifact.wheel_sha256:
        _reject("artifact_wheel_hash_mismatch")

    try:
        with zipfile.ZipFile(io.BytesIO(raw_wheel)) as archive:
            infos = tuple(archive.infolist())
            files = tuple(info for info in infos if not info.is_dir())
            member_names = tuple(info.filename for info in files)
            if len(set(member_names)) != len(member_names):
                _reject("artifact_wheel_invalid")
            if any("\\" in name or _safe_relative_path(name) != name for name in member_names):
                _reject("artifact_wheel_invalid")
            for info in files:
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    _reject("artifact_wheel_invalid")
            record_paths = [name for name in member_names if name.endswith(".dist-info/RECORD")]
            metadata_paths = [name for name in member_names if name.endswith(".dist-info/METADATA")]
            if len(record_paths) != 1 or len(metadata_paths) != 1:
                _reject("artifact_wheel_invalid")
            record_path = record_paths[0]
            wheel_record = archive.read(record_path)
            if hashlib.sha256(wheel_record).hexdigest() != artifact.wheel_record_sha256:
                _reject("artifact_wheel_record_hash_mismatch")
            metadata_text = archive.read(metadata_paths[0]).decode("utf-8")
            headers = {}
            for line in metadata_text.splitlines():
                if ": " in line:
                    key, value = line.split(": ", 1)
                    if key in ("Name", "Version"):
                        headers[key] = value
            if (
                _normalized_distribution_name(headers.get("Name", ""))
                != _normalized_distribution_name(artifact.distribution)
                or headers.get("Version") != artifact.version
            ):
                _reject("artifact_wheel_identity_mismatch")
            members = {info.filename: archive.read(info.filename) for info in files}
    except CtpCandidateArtifactSetError:
        raise
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile, RuntimeError, ValueError):
        _reject("artifact_wheel_invalid")

    payload = {name: contents for name, contents in members.items() if name != record_path}
    _validate_record_rows(wheel_record, expected_self_path=record_path, expected_members=payload)
    return MappingProxyType(members)


def _direct_wheel_path(artifact: CtpCandidateArtifact, direct_url: object) -> Path:
    if type(direct_url) is not dict or "dir_info" in direct_url:
        _reject("artifact_origin_not_wheel")
    archive_info = direct_url.get("archive_info")
    url = direct_url.get("url")
    if type(archive_info) is not dict or type(url) is not str:
        _reject("artifact_origin_not_wheel")
    expected_hash = "sha256=" + artifact.wheel_sha256
    archive_hash = archive_info.get("hash")
    archive_hashes = archive_info.get("hashes")
    if (
        (archive_hash is not None and archive_hash != expected_hash)
        or (archive_hashes is not None and archive_hashes != {"sha256": artifact.wheel_sha256})
        or (archive_hash is None and archive_hashes is None)
    ):
        _reject("artifact_origin_hash_mismatch")
    try:
        parsed = urlsplit(url)
        wheel_name = PurePosixPath(unquote(parsed.path)).name
        wheel_path = Path(url2pathname(unquote(parsed.path)))
    except (TypeError, ValueError, OSError):
        _reject("artifact_origin_invalid")
    if (
        parsed.scheme != "file"
        or parsed.netloc not in ("", "localhost")
        or parsed.query
        or parsed.fragment
        or wheel_name != artifact.wheel_filename
    ):
        _reject("artifact_origin_invalid")
    return wheel_path


def _install_root(distribution: importlib.metadata.Distribution) -> Path:
    try:
        root = _provenance._concrete_directory(Path(distribution.locate_file("")))
        allowed = _provenance._interpreter_install_roots()
    except Exception:
        _reject("artifact_install_root_invalid")
    if all(os.path.normcase(str(root)) != os.path.normcase(str(item)) for item in allowed):
        _reject("artifact_install_root_invalid")
    return root


def _verify_installed_record(
    artifact: CtpCandidateArtifact,
    distribution: importlib.metadata.Distribution,
    install_root: Path,
    wheel_members: Mapping[str, bytes],
) -> None:
    files = getattr(distribution, "files", None)
    if not files:
        _reject("artifact_record_invalid")
    try:
        file_entries = tuple(files)
    except (TypeError, ValueError):
        _reject("artifact_record_invalid")
    record_relative = _provenance._record_relative_path(file_entries)
    record_parts = _provenance._relative_record_path(record_relative)
    record_path = install_root.joinpath(*record_parts)
    try:
        record_bytes = _provenance._regular_file(record_path)
    except Exception:
        _reject("artifact_record_invalid")
    installed_records = _validate_record_rows(
        record_bytes,
        expected_self_path=record_relative,
        allow_unhashed_pyc=True,
    )
    recorded_paths = set(installed_records)
    distribution_paths = {str(item) for item in file_entries}
    if recorded_paths != distribution_paths:
        _reject("artifact_record_mismatch")

    pyc_entries = []
    wheel_record_paths = {path for path in wheel_members if path.endswith(".dist-info/RECORD")}
    if len(wheel_record_paths) != 1:
        _reject("artifact_wheel_invalid")
    wheel_record_path = next(iter(wheel_record_paths))
    generated_allowed = {
        record_relative.rsplit("/", 1)[0] + "/direct_url.json",
        record_relative.rsplit("/", 1)[0] + "/INSTALLER",
        record_relative.rsplit("/", 1)[0] + "/REQUESTED",
    }
    extra_paths = recorded_paths - set(wheel_members)
    if not extra_paths.issubset(
        generated_allowed
        | {path for path in extra_paths if "/__pycache__/" in path and path.endswith(".pyc")}
    ):
        _reject("artifact_record_mismatch")
    if not generated_allowed.intersection(extra_paths) or not any(
        path.endswith("/direct_url.json") for path in extra_paths
    ):
        _reject("artifact_origin_not_wheel")

    for relative, (expected_hash, expected_size) in installed_records.items():
        path = install_root.joinpath(*_provenance._relative_record_path(relative))
        if relative == record_relative:
            if expected_hash or expected_size:
                _reject("artifact_record_invalid")
            continue
        if path.suffix == ".pyc":
            if expected_hash or expected_size:
                _provenance._file_digest_matches(path, expected_hash, expected_size)
            elif "__pycache__" in _provenance._relative_record_path(relative):
                pyc_entries.append(path)
            else:
                _reject("artifact_record_invalid")
            continue
        try:
            _provenance._file_digest_matches(path, expected_hash, expected_size)
        except Exception:
            _reject("artifact_file_hash_mismatch")

    # Every wheel member except RECORD must survive pip installation byte for
    # byte. This ties package contents to the exact archive even when the
    # install path changes and the generated direct_url row changes its hash.
    for relative, wheel_bytes in wheel_members.items():
        if relative == wheel_record_path:
            continue
        path = install_root.joinpath(*_provenance._relative_record_path(relative))
        try:
            installed_bytes = _provenance._regular_file(path)
        except Exception:
            _reject("artifact_file_unavailable")
        if installed_bytes != wheel_bytes:
            _reject("artifact_installed_payload_mismatch")

    try:
        package_root = _provenance._concrete_directory(install_root / artifact.module)
    except Exception:
        _reject("artifact_import_rejected")
    for path in pyc_entries:
        try:
            _provenance._validate_pyc_cache(path, package_root, install_root, recorded_paths)
        except Exception:
            _reject("artifact_bytecode_invalid")
    try:
        _provenance._validate_package_inventory(package_root, install_root, recorded_paths)
        _provenance._verify_package_import_root(artifact.module, package_root)
    except Exception:
        _reject("artifact_import_rejected")


def _verify_one_artifact(artifact: CtpCandidateArtifact) -> None:
    # A forged module can pair an untrusted ``__file__`` with a trusted
    # ``__spec__.origin``. Require the package to be genuinely unloaded before
    # ``find_spec`` is consulted by the shared import-root checker.
    _require_unloaded_packages((artifact.module,))
    try:
        distribution = importlib.metadata.distribution(artifact.distribution)
    except importlib.metadata.PackageNotFoundError:
        _reject("artifact_unavailable")
    except Exception:
        _reject("artifact_metadata_invalid")
    metadata = getattr(distribution, "metadata", None)
    name = metadata.get("Name") if metadata is not None else None
    version = metadata.get("Version") if metadata is not None else None
    if (
        type(name) is not str
        or _normalized_distribution_name(name)
        != _normalized_distribution_name(artifact.distribution)
        or type(version) is not str
        or version != artifact.version
    ):
        _reject("artifact_identity_mismatch")
    install_root = _install_root(distribution)
    try:
        direct_url_text = distribution.read_text("direct_url.json")
        direct_url = json.loads(direct_url_text) if direct_url_text is not None else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        _reject("artifact_origin_invalid")
    wheel_path = _direct_wheel_path(artifact, direct_url)
    wheel_members = _read_wheel(artifact, wheel_path)
    _verify_installed_record(artifact, distribution, install_root, wheel_members)


def verify_ctp_i9_candidate_artifact_set() -> CtpCandidateArtifactSetReceipt:
    """Verify the exact I9/base/execution wheel trio in the current interpreter.

    All three distributions must have a PEP 610 archive origin pointing to a
    retained local wheel with the manifest digest, and every installed
    payload member must match that archive. Verification requires the three
    package roots to be absent from ``sys.modules`` at entry and exit. Editable
    installs, source-tree imports, mixed versions, and mixed wheel builds are
    rejected.
    """

    if CTP_I9_CANDIDATE_ARTIFACT_SET_VERSION != 1 or tuple(
        item.distribution for item in CTP_I9_CANDIDATE_ARTIFACTS
    ) != ("bt_api_base", "bt_api_ctp", "bt_api_execution"):
        _reject("artifact_set_manifest_invalid")
    _require_unloaded_packages(tuple(item.module for item in CTP_I9_CANDIDATE_ARTIFACTS))
    for artifact in CTP_I9_CANDIDATE_ARTIFACTS:
        _verify_one_artifact(artifact)
    _require_unloaded_packages(tuple(item.module for item in CTP_I9_CANDIDATE_ARTIFACTS))
    return CtpCandidateArtifactSetReceipt(
        manifest_id=CTP_I9_CANDIDATE_ARTIFACT_SET_ID,
        manifest_version=CTP_I9_CANDIDATE_ARTIFACT_SET_VERSION,
        manifest_sha256=CTP_I9_CANDIDATE_ARTIFACT_SET_SHA256,
        verified_distributions=tuple(item.distribution for item in CTP_I9_CANDIDATE_ARTIFACTS),
    )


__all__ = [
    "CTP_I9_CANDIDATE_ARTIFACTS",
    "CTP_I9_CANDIDATE_ARTIFACT_SET_ID",
    "CTP_I9_CANDIDATE_ARTIFACT_SET_SHA256",
    "CTP_I9_CANDIDATE_ARTIFACT_SET_VERSION",
    "CtpCandidateArtifact",
    "CtpCandidateArtifactSetError",
    "CtpCandidateArtifactSetReceipt",
    "verify_ctp_i9_candidate_artifact_set",
]
