#!/usr/bin/env python3
"""Generate non-authorizing review evidence for a candidate CTP SDK release.

This tool reads only explicitly named wheel files and a small, fixed set of
SDK source metadata files. It never imports the SDK, reads credentials, or
contacts a provider. Its output is evidence for independent review; it does not
approve an artifact or modify ``CTP_SDK_ARTIFACT_PINS``.
"""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import unquote, urlsplit


EXPECTED_DISTRIBUTIONS = {
    "bt_api_base": "bt_api_base",
    "bt_api_ctp": "bt_api_ctp",
}
FRONT_BINDING_MODES = ("legacy_profile", "explicit_front_pair")
_SIGNATURE_FILES = {"RECORD.jws", "RECORD.p7s"}
_PUBLIC_CONFIGURATION_MEMBERS = {"bt_api_ctp/configs/ctp.yaml"}
_EXPECTED_CTP_WINDOWS_EXTENSION = "bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd"
_CONFIGURATION_SUFFIXES = {".cfg", ".ini", ".json", ".toml", ".yaml", ".yml"}
_SENSITIVE_NAME_PARTS = (
    "credential",
    "password",
    "private_key",
    "private-key",
    "secret",
    "token",
)


class EvidenceError(ValueError):
    """Candidate material is incomplete or inconsistent."""

    def __init__(self, message: str, reason_code: str = "candidate_artifact_invalid") -> None:
        super().__init__(message)
        self.status = "rejected"
        self.reason_code = reason_code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalise_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "_", value).lower()


def _check_wheel_filename(filename: str, distribution: str, version: str) -> None:
    if not filename.endswith(".whl"):
        raise EvidenceError("candidate artifact filename is not a wheel")
    parts = filename[:-4].split("-")
    if len(parts) not in (5, 6):
        raise EvidenceError("candidate wheel filename is invalid")
    if parts[0] != _normalise_distribution(distribution) or parts[1] != version:
        raise EvidenceError("candidate wheel filename does not match its metadata")
    if any(not part for part in parts[2:]):
        raise EvidenceError("candidate wheel filename is invalid")
    if len(parts) == 6 and not re.fullmatch(r"[0-9][A-Za-z0-9_]*", parts[2]):
        raise EvidenceError("candidate wheel build tag is invalid")


def _wheel_tags(filename: str) -> Set[Tuple[str, str, str]]:
    """Return the expanded compatibility tags from a validated wheel name."""

    parts = filename[:-4].split("-")
    python_tag, abi_tag, platform_tag = parts[-3:]
    return {
        (python, abi, platform)
        for python in python_tag.split(".")
        for abi in abi_tag.split(".")
        for platform in platform_tag.split(".")
    }


def _check_ctp_windows_native_extension(
    filename: str, module: str, file_names: Sequence[str], archive: zipfile.ZipFile
) -> str:
    """Reject malformed native payloads in the supported Windows CTP wheel."""

    if module != "bt_api_ctp":
        return "not_applicable"
    tags = _wheel_tags(filename)
    is_windows_amd64 = any(platform == "win_amd64" for _, _, platform in tags)
    if not is_windows_amd64:
        return "not_required"
    expected_tag = ("cp311", "cp311", "win_amd64")
    if expected_tag not in tags:
        raise EvidenceError(
            "CTP Windows wheel must target CPython 3.11 win_amd64",
            reason_code="ctp_windows_wheel_tag_unsupported",
        )

    extensions = [name for name in file_names if name.lower().endswith(".pyd")]
    if extensions != [_EXPECTED_CTP_WINDOWS_EXTENSION]:
        raise EvidenceError(
            "CTP CPython 3.11 Windows wheel must contain exactly one expected native extension",
            reason_code="ctp_windows_native_extension_missing_or_ambiguous",
        )
    try:
        image = archive.read(_EXPECTED_CTP_WINDOWS_EXTENSION)
    except (KeyError, OSError) as exc:
        raise EvidenceError(
            "CTP Windows native extension is unreadable",
            reason_code="ctp_windows_native_extension_unreadable",
        ) from exc
    if not _has_plausible_amd64_pe_header(image):
        raise EvidenceError(
            "CTP Windows native extension has an invalid AMD64 PE header",
            reason_code="ctp_windows_native_extension_invalid_pe",
        )
    return "verified"


def _has_plausible_amd64_pe_header(image: bytes) -> bool:
    """Check enough PE structure to reject empty/truncated/non-Windows payloads."""

    if len(image) < 0x40 or image[:2] != b"MZ":
        return False
    pe_offset = int.from_bytes(image[0x3C:0x40], "little")
    # IMAGE_FILE_HEADER follows the four-byte PE signature and is 20 bytes.
    if pe_offset < 0x40 or pe_offset + 24 > len(image):
        return False
    if image[pe_offset : pe_offset + 4] != b"PE\0\0":
        return False
    file_header = image[pe_offset + 4 : pe_offset + 24]
    machine = int.from_bytes(file_header[0:2], "little")
    section_count = int.from_bytes(file_header[2:4], "little")
    optional_header_size = int.from_bytes(file_header[16:18], "little")
    optional_header_start = pe_offset + 24
    section_table_start = optional_header_start + optional_header_size
    # AMD64 PE32+ images have at least the two-byte magic in the optional header.
    if (
        machine != 0x8664
        or not 1 <= section_count <= 96
        or optional_header_size < 2
        or section_table_start > len(image)
        or image[optional_header_start : optional_header_start + 2] != b"\x0b\x02"
    ):
        return False
    return section_table_start + section_count * 40 <= len(image)


def _is_link_or_reparse(result: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(result, "st_file_attributes", 0)
    return stat.S_ISLNK(result.st_mode) or bool(attributes & reparse_flag)


def _read_regular(path: Path) -> bytes:
    try:
        result = os.lstat(str(path))
    except OSError as exc:
        raise EvidenceError("evidence file is unavailable") from exc
    if _is_link_or_reparse(result) or not stat.S_ISREG(result.st_mode):
        raise EvidenceError("evidence file is not a regular file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise EvidenceError("evidence file is unavailable") from exc


def _read_regular_under(root: Path, relative: str) -> bytes:
    parts = _safe_relative_path(relative)
    current = root
    for part in parts[:-1]:
        current = current / part
        try:
            result = os.lstat(str(current))
        except OSError as exc:
            raise EvidenceError("installed RECORD path is unavailable") from exc
        if _is_link_or_reparse(result) or not stat.S_ISDIR(result.st_mode):
            raise EvidenceError("installed RECORD path contains a link or non-directory")
    return _read_regular(root.joinpath(*parts))


def _safe_relative_path(value: str) -> Tuple[str, ...]:
    if not value or value.startswith("/") or "\\" in value or "\x00" in value:
        raise EvidenceError("artifact RECORD contains an invalid path")
    parts = value.split("/")
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        raise EvidenceError("artifact RECORD contains an invalid path")
    return tuple(parts)


def _decode_record_digest(value: str) -> bytes:
    if not value.startswith("sha256="):
        raise EvidenceError("artifact RECORD uses an unsupported digest")
    digest_text = value[len("sha256=") :]
    if not digest_text or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
        for character in digest_text
    ):
        raise EvidenceError("artifact RECORD contains an invalid digest")
    padding = "=" * ((4 - len(digest_text) % 4) % 4)
    try:
        digest = base64.urlsafe_b64decode(digest_text + padding)
    except (ValueError, binascii.Error) as exc:
        raise EvidenceError("artifact RECORD contains an invalid digest") from exc
    if len(digest) != hashlib.sha256().digest_size:
        raise EvidenceError("artifact RECORD contains an invalid digest")
    return digest


def _parse_record(record_bytes: bytes) -> List[Tuple[str, str, str]]:
    try:
        rows = list(csv.reader(io.StringIO(record_bytes.decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise EvidenceError("artifact RECORD is invalid") from exc
    if not rows:
        raise EvidenceError("artifact RECORD is empty")
    parsed: List[Tuple[str, str, str]] = []
    seen = set()
    for row in rows:
        if len(row) != 3:
            raise EvidenceError("artifact RECORD is invalid")
        relative = row[0]
        _safe_relative_path(relative)
        if relative in seen:
            raise EvidenceError("artifact RECORD has duplicate paths")
        seen.add(relative)
        parsed.append((relative, row[1], row[2]))
    return parsed


def _check_recorded_content(contents: bytes, digest_field: str, size_field: str) -> None:
    if not size_field.isdecimal() or len(contents) != int(size_field):
        raise EvidenceError("artifact RECORD size does not match its file")
    if hashlib.sha256(contents).digest() != _decode_record_digest(digest_field):
        raise EvidenceError("artifact RECORD digest does not match its file")


def _scan_member_names(file_infos: Sequence[zipfile.ZipInfo]) -> Dict[str, Any]:
    configuration_members = []
    for item in file_infos:
        name = item.filename
        path = PurePosixPath(name)
        lowered_parts = tuple(part.lower() for part in path.parts)
        lowered_name = path.name.lower()
        suffix = path.suffix.lower()
        sensitive_directory = any(
            part in {"secrets", "credentials", "private", ".ssh", ".aws"}
            for part in lowered_parts[:-1]
        )
        sensitive_name = (
            lowered_name.startswith(".env")
            or suffix in {".pem", ".key", ".p12", ".pfx", ".p7b", ".p7c"}
            or any(part in lowered_name for part in _SENSITIVE_NAME_PARTS)
            or sensitive_directory
        )
        if sensitive_name:
            raise EvidenceError("candidate wheel member name matches a private-data pattern")
        is_configuration_data = suffix in _CONFIGURATION_SUFFIXES and (
            lowered_name.startswith("config")
            or any(part in {"config", "configs", "configuration"} for part in lowered_parts[:-1])
        )
        if is_configuration_data:
            if name not in _PUBLIC_CONFIGURATION_MEMBERS:
                raise EvidenceError("candidate wheel contains an unexpected configuration file")
            configuration_members.append(name)
    return {
        "scanned_file_count": sum(not item.is_dir() for item in file_infos),
        "public_configuration_members": sorted(configuration_members),
        "private_or_secret_member_count": 0,
    }


def _source_snapshot_digest(file_hashes: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(file_hashes):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hashes[name].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _wheel_python_source_map(
    archive: zipfile.ZipFile, file_names: Sequence[str], module: str
) -> Dict[str, str]:
    result = {}
    for name in file_names:
        if name.startswith(module + "/") and name.endswith(".py"):
            result[name] = _sha256(archive.read(name))
    return result


def _source_python_source_map(project: Path, module: str) -> Optional[Dict[str, str]]:
    package_root = project / "src" / module
    try:
        result = os.lstat(str(package_root))
    except OSError:
        return None
    if _is_link_or_reparse(result) or not stat.S_ISDIR(result.st_mode):
        return None
    file_hashes = {}
    for directory, child_directories, filenames in os.walk(
        str(package_root), followlinks=False
    ):
        current = Path(directory)
        for name in tuple(child_directories):
            child = current / name
            try:
                child_stat = os.lstat(str(child))
            except OSError:
                return None
            if _is_link_or_reparse(child_stat) or not stat.S_ISDIR(child_stat.st_mode):
                return None
        for name in filenames:
            if not name.endswith(".py"):
                continue
            relative = (current / name).relative_to(package_root).as_posix()
            try:
                contents = _read_regular_under(package_root, relative)
            except EvidenceError:
                return None
            file_hashes[module + "/" + relative] = _sha256(contents)
    return file_hashes


def _read_wheel(path: Path) -> Dict[str, Any]:
    raw = _read_regular(path)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (OSError, zipfile.BadZipFile) as exc:
        raise EvidenceError("candidate wheel is not a valid ZIP archive") from exc

    with archive:
        all_infos = archive.infolist()
        member_names = []
        for item in all_infos:
            relative = item.filename[:-1] if item.is_dir() else item.filename
            _safe_relative_path(relative)
            member_names.append(relative)
            if item.create_system == 3:
                mode = item.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                expected_type = stat.S_IFDIR if item.is_dir() else stat.S_IFREG
                if file_type and file_type != expected_type:
                    raise EvidenceError("candidate wheel contains a non-regular file")
        if len(member_names) != len(set(member_names)):
            raise EvidenceError("candidate wheel contains duplicate paths")
        file_infos = [item for item in all_infos if not item.is_dir()]
        file_names = [item.filename for item in file_infos]
        if len(file_names) != len(set(file_names)):
            raise EvidenceError("candidate wheel contains duplicate paths")
        member_scan = _scan_member_names(all_infos)
        metadata_paths = [name for name in file_names if name.endswith(".dist-info/METADATA")]
        record_paths = [name for name in file_names if name.endswith(".dist-info/RECORD")]
        if len(metadata_paths) != 1 or len(record_paths) != 1:
            raise EvidenceError("candidate wheel must contain one METADATA and RECORD")
        metadata_path = metadata_paths[0]
        record_path = record_paths[0]
        try:
            metadata = BytesParser().parsebytes(archive.read(metadata_path))
            record_bytes = archive.read(record_path)
        except (KeyError, OSError, ValueError) as exc:
            raise EvidenceError("candidate wheel metadata is invalid") from exc
        distribution = metadata.get("Name")
        version = metadata.get("Version")
        module = EXPECTED_DISTRIBUTIONS.get(_normalise_distribution(distribution or ""))
        if module is None or not version:
            raise EvidenceError("wheel must be bt_api_base or bt_api_ctp with a version")
        _check_wheel_filename(path.name, str(distribution), str(version))
        native_extension_integrity = _check_ctp_windows_native_extension(
            path.name, module, file_names, archive
        )
        dist_info_root = metadata_path.split("/", 1)[0]
        if dist_info_root != "{}-{}.dist-info".format(module, version):
            raise EvidenceError("wheel metadata directory does not match its distribution")
        if any(
            name.split("/", 1)[0] not in {module, dist_info_root}
            for name in member_names
        ):
            raise EvidenceError("candidate wheel contains an unexpected archive member")

        rows = _parse_record(record_bytes)
        recorded = set()
        self_rows = 0
        for relative, digest_field, size_field in rows:
            recorded.add(relative)
            if relative == record_path:
                self_rows += 1
                if digest_field or size_field:
                    raise EvidenceError("wheel RECORD self-entry must be empty")
                continue
            if relative not in file_names:
                raise EvidenceError("wheel RECORD refers to a missing archive file")
            try:
                contents = archive.read(relative)
            except (KeyError, OSError) as exc:
                raise EvidenceError("candidate wheel contains an unreadable file") from exc
            _check_recorded_content(contents, digest_field, size_field)
        expected_recorded = set(file_names) - {
            name for name in file_names if PurePosixPath(name).name in _SIGNATURE_FILES
        }
        if self_rows != 1 or recorded != expected_recorded:
            raise EvidenceError("wheel RECORD does not cover the archive exactly")

        selector_path = "bt_api_ctp/ctp_env_selector.py"
        selector_bytes = None
        if module == "bt_api_ctp" and selector_path in file_names:
            selector_bytes = archive.read(selector_path)
        python_source_map = _wheel_python_source_map(archive, file_names, module)
        return {
            "distribution": distribution,
            "module": module,
            "version": version,
            "wheel_filename": path.name,
            "wheel_sha256": _sha256(raw),
            "wheel_record_sha256": _sha256(record_bytes),
            "wheel_record_file_count": len(rows) - 1,
            "requires_python": metadata.get("Requires-Python"),
            "requires_dist": sorted(metadata.get_all("Requires-Dist", [])),
            "selector_sha256": _sha256(selector_bytes) if selector_bytes is not None else None,
            "selector_fronts": (
                _profile_mapping(selector_bytes) if selector_bytes is not None else None
            ),
            "python_source_snapshot_sha256": _source_snapshot_digest(python_source_map),
            "python_source_file_count": len(python_source_map),
            "native_extension_integrity": native_extension_integrity,
            "member_scan": member_scan,
            "_record_path": record_path,
            "_record_bytes": record_bytes,
            "_archive_files": tuple(file_names),
            "_python_source_map": python_source_map,
        }


def _read_installed_record(
    site_root: Path, wheel: Mapping[str, Any]
) -> Dict[str, Any]:
    if not site_root.is_dir() or _is_link_or_reparse(os.lstat(str(site_root))):
        raise EvidenceError("installed site root is invalid")
    candidates = []
    for metadata_path in site_root.glob("*.dist-info/METADATA"):
        try:
            directory_stat = os.lstat(str(metadata_path.parent))
        except OSError:
            continue
        if _is_link_or_reparse(directory_stat) or not stat.S_ISDIR(directory_stat.st_mode):
            continue
        try:
            relative_metadata = metadata_path.relative_to(site_root).as_posix()
            metadata = BytesParser().parsebytes(_read_regular_under(site_root, relative_metadata))
        except EvidenceError:
            continue
        if (
            _normalise_distribution(metadata.get("Name", ""))
            == _normalise_distribution(str(wheel["distribution"]))
            and metadata.get("Version") == wheel["version"]
        ):
            candidates.append(metadata_path.parent)
    if len(candidates) != 1:
        raise EvidenceError("installed candidate distribution is missing or ambiguous")
    dist_info = candidates[0]
    record_path = dist_info / "RECORD"
    record_bytes = _read_regular(record_path)
    rows = _parse_record(record_bytes)
    record_relative = record_path.relative_to(site_root).as_posix()
    recorded = set()
    self_rows = 0
    unhashed_bytecode_count = 0
    unhashed_bytecode_paths = []
    for relative, digest_field, size_field in rows:
        recorded.add(relative)
        path = site_root.joinpath(*_safe_relative_path(relative))
        if relative == record_relative:
            self_rows += 1
            if digest_field or size_field:
                raise EvidenceError("installed RECORD self-entry must be empty")
            continue
        contents = _read_regular_under(site_root, relative)
        if not digest_field and not size_field:
            parts = _safe_relative_path(relative)
            if (
                path.suffix == ".pyc"
                and len(parts) >= 3
                and parts[-2] == "__pycache__"
                and parts[0] == wheel["module"]
            ):
                unhashed_bytecode_count += 1
                unhashed_bytecode_paths.append(relative)
                continue
            raise EvidenceError("installed RECORD has an unhashed non-bytecode file")
        _check_recorded_content(contents, digest_field, size_field)
    if self_rows != 1:
        raise EvidenceError("installed RECORD must contain one empty self-entry")
    for relative in unhashed_bytecode_paths:
        path = site_root.joinpath(*_safe_relative_path(relative))
        try:
            source_path = Path(importlib.util.source_from_cache(str(path)))
            source_relative = source_path.relative_to(site_root).as_posix()
        except (NotImplementedError, OSError, ValueError) as exc:
            raise EvidenceError("installed RECORD has invalid generated bytecode") from exc
        if source_relative not in recorded or not source_relative.startswith(wheel["module"] + "/"):
            raise EvidenceError("installed RECORD bytecode has no recorded package source")
        _read_regular_under(site_root, source_relative)

    direct_url_path = dist_info / "direct_url.json"
    try:
        direct_url = json.loads(
            _read_regular_under(site_root, direct_url_path.relative_to(site_root).as_posix()).decode(
                "utf-8"
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError, EvidenceError) as exc:
        raise EvidenceError("installed direct_url.json is missing or invalid") from exc
    archive_info = direct_url.get("archive_info") if isinstance(direct_url, dict) else None
    url = direct_url.get("url") if isinstance(direct_url, dict) else None
    if not isinstance(archive_info, dict) or not isinstance(url, str):
        raise EvidenceError("installed direct_url.json does not identify a wheel")
    expected_hashes = {"sha256": wheel["wheel_sha256"]}
    archive_hash = archive_info.get("hash")
    archive_hashes = archive_info.get("hashes")
    if archive_hash not in (None, "sha256=" + wheel["wheel_sha256"]):
        raise EvidenceError("installed direct_url.json has a different wheel hash")
    if archive_hashes not in (None, expected_hashes):
        raise EvidenceError("installed direct_url.json has a different wheel hash")
    if archive_hash is None and archive_hashes is None:
        raise EvidenceError("installed direct_url.json has no wheel hash")
    parsed_url = urlsplit(url)
    wheel_name = PurePosixPath(unquote(parsed_url.path)).name
    if (
        parsed_url.scheme != "file"
        or parsed_url.netloc not in ("", "localhost")
        or parsed_url.query
        or parsed_url.fragment
        or wheel_name != wheel["wheel_filename"]
    ):
        raise EvidenceError("installed direct_url.json names a different wheel")

    # Ensure each file carried in the wheel appears in the installed RECORD.
    wheel_dist_info = str(wheel["_record_path"]).rsplit("/", 1)[0]
    installed_prefix = dist_info.name
    for relative in wheel["_archive_files"]:
        if relative == wheel["_record_path"]:
            continue
        parts = relative.split("/", 1)
        installed_relative = (
            installed_prefix + "/" + parts[1]
            if parts[0] == wheel_dist_info
            else relative
        )
        if installed_relative not in recorded:
            raise EvidenceError("installed RECORD omits a wheel file")

    return {
        "installed_record_sha256": _sha256(record_bytes),
        "installed_record_file_count": len(rows) - 1,
        "installed_unhashed_bytecode_count": unhashed_bytecode_count,
        "installed_direct_url_matches_wheel": True,
    }


class _LiteralEvaluator:
    """Evaluate only a small subset of Python literals from trusted source text."""

    def __init__(self) -> None:
        self.names: Dict[str, Any] = {}

    def expression(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.Tuple, ast.List)):
            values = [self.expression(item) for item in node.elts]
            return tuple(values) if isinstance(node, ast.Tuple) else values
        if isinstance(node, ast.Dict):
            return {
                self.expression(key): self.expression(value)
                for key, value in zip(node.keys, node.values)
            }
        if isinstance(node, ast.Name):
            return self.names[node.id]
        if isinstance(node, ast.Subscript):
            return self.expression(node.value)[self.expression(node.slice)]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "MappingProxyType" and len(node.args) == 1:
                value = self.expression(node.args[0])
                if isinstance(value, dict):
                    return value
        raise EvidenceError("front map uses unsupported source expressions")

    def find_assignment(self, source: bytes, name: str) -> Any:
        try:
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise EvidenceError("front map source cannot be parsed") from exc
        for statement in tree.body:
            if isinstance(statement, ast.Assign):
                targets = [target.id for target in statement.targets if isinstance(target, ast.Name)]
                if len(targets) != len(statement.targets):
                    continue
                try:
                    value = self.expression(statement.value)
                except (KeyError, IndexError, TypeError, EvidenceError):
                    continue
                for target in targets:
                    self.names[target] = value
                if name in targets:
                    if not isinstance(value, dict):
                        break
                    return value
        raise EvidenceError("required front map assignment is unavailable")


def _profile_mapping(source: Optional[bytes], assignment: str = "_SIMNOW_PROFILE_FRONTS") -> Dict[str, List[str]]:
    if source is None:
        raise EvidenceError("front map source is missing")
    value = _LiteralEvaluator().find_assignment(source, assignment)
    result: Dict[str, List[str]] = {}
    for name, pair in value.items():
        if (
            not isinstance(name, str)
            or not isinstance(pair, (tuple, list))
            or len(pair) != 2
            or not all(isinstance(front, str) for front in pair)
        ):
            raise EvidenceError("front map has an invalid entry")
        result[name] = [pair[0], pair[1]]
    return dict(sorted(result.items()))


def _has_explicit_front_verifier(source: bytes) -> bool:
    """Check the runtime source still exposes its exact-front artifact gate."""

    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError):
        return False
    verifier = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "verify_ctp_sdk_artifact_provenance_for_fronts"
        ),
        None,
    )
    if verifier is None:
        return False
    called_names = {
        node.func.id
        for node in ast.walk(verifier)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    return {
        "_validate_exact_tcp_front_pair",
        "_verify_pinned_sdk_distributions",
    }.issubset(called_names)


def _project_metadata(path: Path) -> Dict[str, Any]:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef,import-not-found]
        except ImportError:
            return {"available": False, "reason": "toml_reader_unavailable"}
    try:
        contents = tomllib.loads(_read_regular(path).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, EvidenceError):
        return {"available": False, "reason": "project_metadata_invalid"}
    project = contents.get("project")
    if not isinstance(project, dict):
        return {"available": False, "reason": "project_metadata_missing"}
    return {
        "available": True,
        "name": project.get("name"),
        "version": project.get("version"),
        "requires_python": project.get("requires-python"),
        "dependencies": sorted(project.get("dependencies", [])),
        "build_system": contents.get("build-system", {}),
    }


def _git_snapshot(path: Path) -> Dict[str, Any]:
    def run(*arguments: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(path)] + list(arguments),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    head = run("rev-parse", "HEAD")
    status = run("status", "--porcelain=v1", "--untracked-files=all")
    if head is None or status is None:
        return {"available": False}
    changes = status.splitlines()
    return {
        "available": True,
        "head": head,
        "dirty": bool(changes),
        "change_count": len(changes),
    }


def _source_evidence(sdk_root: Path) -> Dict[str, Any]:
    ctp_project = sdk_root / "bt_api" / "bt_api_ctp"
    base_project = sdk_root / "bt_api" / "bt_api_base"
    selector = ctp_project / "src" / "bt_api_ctp" / "ctp_env_selector.py"
    try:
        selector_bytes = _read_regular(selector)
        source_fronts = _profile_mapping(selector_bytes)
    except EvidenceError:
        selector_bytes = None
        source_fronts = None
    package_data = {}
    for name, project in (("bt_api_base", base_project), ("bt_api_ctp", ctp_project)):
        package_data[name] = {
            "project": _project_metadata(project / "pyproject.toml"),
            "git": _git_snapshot(project),
            "python_source_map": _source_python_source_map(project, name),
        }
        package_data[name]["python_source_snapshot_sha256"] = (
            _source_snapshot_digest(package_data[name]["python_source_map"])
            if package_data[name]["python_source_map"] is not None
            else None
        )
        package_data[name]["python_source_file_count"] = (
            len(package_data[name]["python_source_map"])
            if package_data[name]["python_source_map"] is not None
            else None
        )
    return {
        "sdk_root": str(sdk_root.resolve()),
        "sdk_repository": _git_snapshot(sdk_root),
        "packages": package_data,
        "ctp_selector_sha256": _sha256(selector_bytes) if selector_bytes else None,
        "ctp_selector_fronts": source_fronts,
    }


def generate_evidence(
    sdk_root: Path,
    wheel_paths: Sequence[Path],
    installed_site: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    front_binding_mode: str = "legacy_profile",
) -> Dict[str, Any]:
    """Build deterministic candidate evidence without granting approval."""

    if type(front_binding_mode) is not str or front_binding_mode not in FRONT_BINDING_MODES:
        raise EvidenceError("front binding mode is invalid")

    source = _source_evidence(sdk_root)
    wheels = [_read_wheel(path) for path in sorted(wheel_paths, key=lambda item: item.name)]
    modules = [wheel["module"] for wheel in wheels]
    if len(modules) != len(set(modules)):
        raise EvidenceError("only one wheel per SDK distribution may be supplied")
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    runtime_source = _read_regular(
        repo_root / "backtrader_runtime" / "ctp_artifact_provenance.py"
    )
    runtime_fronts = _profile_mapping(runtime_source, "_ALLOWED_SIMNOW_PROFILE_FRONTS")
    explicit_front_verifier_available = _has_explicit_front_verifier(runtime_source)
    ctp_wheel = next((wheel for wheel in wheels if wheel["module"] == "bt_api_ctp"), None)
    candidate_fronts = ctp_wheel["selector_fronts"] if ctp_wheel else source["ctp_selector_fronts"]
    matching_profiles = {}
    differing_profiles = {}
    missing_profiles = []
    if candidate_fronts is not None:
        for profile, approved_pair in runtime_fronts.items():
            candidate_pair = candidate_fronts.get(profile)
            if candidate_pair == approved_pair:
                matching_profiles[profile] = approved_pair
            elif candidate_pair is None:
                missing_profiles.append(profile)
            else:
                differing_profiles[profile] = {
                    "runtime_pair": approved_pair,
                    "candidate_pair": candidate_pair,
                }
    extra_profiles = (
        sorted(set(candidate_fronts) - set(runtime_fronts)) if candidate_fronts else []
    )
    runtime_profile_table_matches = candidate_fronts == runtime_fronts
    runtime_profile_table_gate_applies = front_binding_mode == "legacy_profile"
    runtime_profile_table_gate_satisfied = (
        runtime_profile_table_matches or not runtime_profile_table_gate_applies
    )
    pin_material_scope = (
        "legacy_profile_table_compatible"
        if front_binding_mode == "legacy_profile"
        else "explicit_config_front_pair_artifact_only"
    )

    pin_material: Dict[str, Dict[str, Any]] = {}
    installed_evidence: Dict[str, Any] = {}
    if installed_site is not None:
        for wheel in wheels:
            installed = _read_installed_record(installed_site, wheel)
            installed_evidence[wheel["module"]] = installed
            pin_material[wheel["module"]] = {
                "distribution": wheel["distribution"],
                "module": wheel["module"],
                "version": wheel["version"],
                "wheel_filename": wheel["wheel_filename"],
                "wheel_sha256": wheel["wheel_sha256"],
                "record_sha256": installed["installed_record_sha256"],
            }
    complete_pair = set(modules) == set(EXPECTED_DISTRIBUTIONS.values())
    install_complete = installed_site is not None and len(installed_evidence) == len(wheels)
    source_metadata_matches = {}
    source_python_matches = {}
    source_python_snapshots = {}
    source_python_mismatches = {}
    for wheel in wheels:
        source_project = source["packages"][wheel["module"]]["project"]
        source_metadata_matches[wheel["module"]] = bool(
            source_project.get("available")
            and _normalise_distribution(str(source_project.get("name", "")))
            == _normalise_distribution(str(wheel["distribution"]))
            and source_project.get("version") == wheel["version"]
            and source_project.get("requires_python") == wheel["requires_python"]
        )
        source_python_map = source["packages"][wheel["module"]].get("python_source_map")
        source_python_matches[wheel["module"]] = source_python_map == wheel[
            "_python_source_map"
        ]
        if isinstance(source_python_map, dict):
            wheel_source_map = wheel["_python_source_map"]
            wheel_paths = set(wheel_source_map)
            source_paths = set(source_python_map)
            changed_paths = sorted(
                name
                for name in wheel_paths & source_paths
                if wheel_source_map[name] != source_python_map[name]
            )
            source_python_mismatches[wheel["module"]] = {
                "changed_paths": changed_paths,
                "wheel_only_paths": sorted(wheel_paths - source_paths),
                "source_only_paths": sorted(source_paths - wheel_paths),
                "mismatch_file_count": len(changed_paths)
                + len(wheel_paths - source_paths)
                + len(source_paths - wheel_paths),
            }
        else:
            source_python_mismatches[wheel["module"]] = {
                "changed_paths": [],
                "wheel_only_paths": [],
                "source_only_paths": [],
                "mismatch_file_count": None,
            }
        source_python_snapshots[wheel["module"]] = {
            "wheel_snapshot_sha256": wheel["python_source_snapshot_sha256"],
            "source_snapshot_sha256": source["packages"][wheel["module"]].get(
                "python_source_snapshot_sha256"
            ),
            "wheel_file_count": wheel["python_source_file_count"],
            "source_file_count": source["packages"][wheel["module"]].get(
                "python_source_file_count"
            ),
            "matching": source_python_matches[wheel["module"]],
        }
    source_selector_matches = bool(
        ctp_wheel
        and source.get("ctp_selector_sha256")
        and source["ctp_selector_sha256"] == ctp_wheel["selector_sha256"]
    )
    source_artifact_matches = (
        all(source_metadata_matches.values())
        and all(source_python_matches.values())
        and source_selector_matches
    )
    public_wheels = []
    for wheel in wheels:
        public_wheels.append({key: value for key, value in wheel.items() if not key.startswith("_")})
    git_snapshots = [source["sdk_repository"]] + [
        package["git"] for package in source["packages"].values()
    ]
    source_state_available = all(snapshot.get("available", False) for snapshot in git_snapshots)
    source_dirty = source_state_available and any(
        snapshot.get("dirty", False) for snapshot in git_snapshots
    )
    if not source_state_available:
        pin_material_status = "refused_source_state_unavailable"
    elif source_dirty:
        pin_material_status = "refused_dirty_source"
    elif not source_artifact_matches:
        pin_material_status = "refused_source_artifact_mismatch"
    elif front_binding_mode == "explicit_front_pair" and not explicit_front_verifier_available:
        pin_material_status = "refused_explicit_front_verifier_unavailable"
    elif not runtime_profile_table_gate_satisfied:
        pin_material_status = "refused_runtime_profile_table_mismatch"
    elif not (complete_pair and install_complete):
        pin_material_status = "incomplete"
    else:
        pin_material_status = "ready_for_independent_review_only"
    observed_identities = {
        module: {
            "distribution": wheel["distribution"],
            "version": wheel["version"],
            "wheel_filename": wheel["wheel_filename"],
            "wheel_sha256": wheel["wheel_sha256"],
            "wheel_record_sha256": wheel["wheel_record_sha256"],
            "installed_record_sha256": installed_evidence.get(module, {}).get(
                "installed_record_sha256"
            ),
        }
        for module, wheel in ((wheel["module"], wheel) for wheel in wheels)
    }
    # Candidate pins are emitted only for a clean source checkout and a pair
    # of exact local wheel installations. A dirty artifact remains useful
    # review evidence, but cannot become copy-ready pin material.
    if (
        not source_state_available
        or source_dirty
        or not source_artifact_matches
        or not runtime_profile_table_gate_satisfied
        or (
            front_binding_mode == "explicit_front_pair"
            and not explicit_front_verifier_available
        )
        or not (complete_pair and install_complete)
    ):
        pin_material = {}

    return {
        "schema": "ctp-artifact-review-evidence-v1",
        "authority": "evidence_only_no_approval_or_runtime_authority",
        "independent_release_review_required": True,
        "sdk_source": source,
        "candidate_wheels": public_wheels,
        "installed_artifacts": installed_evidence,
        "source_metadata_matches_wheels": source_metadata_matches,
        "source_python_snapshots": source_python_snapshots,
        "source_python_mismatches": source_python_mismatches,
        "ctp_selector_matches_wheel_source": source_selector_matches,
        "source_artifact_matches": source_artifact_matches,
        "observed_artifact_identities": observed_identities,
        "candidate_pin_material": pin_material,
        "pin_material_status": pin_material_status,
        "front_binding_mode": front_binding_mode,
        "pin_material_scope": pin_material_scope,
        "explicit_front_verifier_available": explicit_front_verifier_available,
        "runtime_reviewed_simnow_profiles": runtime_fronts,
        "candidate_runtime_profile_table_matches": runtime_profile_table_matches,
        "runtime_profile_table_gate_applies": runtime_profile_table_gate_applies,
        "runtime_profile_table_gate_satisfied": runtime_profile_table_gate_satisfied,
        "candidate_runtime_profile_matches": matching_profiles,
        "candidate_runtime_profile_differences": differing_profiles,
        "candidate_missing_runtime_profiles": missing_profiles,
        "candidate_extra_profiles": extra_profiles,
        "catalog_approval": "none",
    }


def _parse_args(arguments: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, action="append", default=[])
    parser.add_argument(
        "--installed-site",
        type=Path,
        help="isolated site-packages containing the exact locally installed wheels",
    )
    parser.add_argument(
        "--front-binding-mode",
        choices=FRONT_BINDING_MODES,
        default="legacy_profile",
        help=(
            "legacy_profile requires the SDK selector map to match the runtime table; "
            "explicit_front_pair emits artifact-only evidence for a runtime that "
            "verifies the sealed pair directly"
        ),
    )
    parser.add_argument("--output", type=Path, help="write JSON evidence to this path")
    return parser.parse_args(arguments)


def main(arguments: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(arguments)
    try:
        evidence = generate_evidence(
            args.sdk_root,
            args.wheel,
            args.installed_site,
            front_binding_mode=args.front_binding_mode,
        )
    except (EvidenceError, OSError) as exc:
        reason_code = getattr(exc, "reason_code", "candidate_artifact_invalid")
        status = getattr(exc, "status", "rejected")
        if reason_code.startswith("ctp_windows_"):
            message = "evidence generation failed [status={} reason={}]: {}".format(
                status, reason_code, exc
            )
        else:
            # Keep the established CLI diagnostic for all pre-existing errors.
            message = "evidence generation failed: {}".format(exc)
        print(message, file=sys.stderr)
        return 2
    output = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
