"""Build and verify the Iteration 46 installed Alpha101 candidate wheel.

This script is intentionally a one-shot Root tool.  It archives only the
selected committed package/build inputs, builds without dependency resolution,
installs that exact wheel into the caller-selected existing environment, and
prepares a separate external test tree.  It never invokes pytest.
"""

from __future__ import annotations

import argparse
import ast
import base64
import csv
import hashlib
from email.parser import BytesParser
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple
import zipfile


SOURCE_ROOT = Path(__file__).resolve().parents[1]
FICORE_WHEEL = Path(
    "D:/temp/iteration45-fincore-wheel-d7f65460/dist/" "fincore-0.5.1.dev0-py3-none-any.whl"
)
FINCORE_SOURCE_COMMIT = "d7f65460c4f885e979d8543ddb15cc8f3c892742"
FINCORE_VERSION = "0.5.1.dev0"
FINCORE_WHEEL_SHA256 = "fbd05395b193ee6510a97c54947c1c3d079f03ca3bd4d9677583519df783d607"
ARCHIVE_PATHS = (
    "backtrader",
    "backtrader_runtime",
    "setup.py",
    "pyproject.toml",
    "README.md",
    "LICENSE",
)
PACKAGE_PREFIXES = ("backtrader/", "backtrader_runtime/")
TEST_COPY_PATHS = (
    "tests/integration/test_alpha101_native_installed.py",
    "tests/test_utils/alpha101_full_reference.py",
    "tests/test_utils/alpha101_native_harness.py",
    "tests/unit/test_factor_research_representatives.py",
    "backtrader/research/alpha101_dependencies.json",
)
TEST_PACKAGE_MARKERS = (
    "tests/__init__.py",
    "tests/integration/__init__.py",
    "tests/test_utils/__init__.py",
    "tests/unit/__init__.py",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    log_path: Path,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    rendered = subprocess.list2cmdline(list(command))
    print("$ %s" % rendered, flush=True)
    completed = subprocess.run(
        list(command),
        cwd=str(cwd),
        env=dict(env),
        check=False,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = completed.stdout or "" if capture else ""
    if capture:
        log_path.write_text(output, encoding="utf-8")
        if output:
            print(output, end="" if output.endswith("\n") else "\n", flush=True)
    if completed.returncode:
        raise RuntimeError(
            "command exited with status %d (see %s)" % (completed.returncode, log_path)
        )
    return completed


def _command_environment(output_root: Path) -> Dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    for key in tuple(env):
        if key.upper().startswith("PIP_"):
            env.pop(key, None)
    temp_root = output_root / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
            "TMPDIR": str(temp_root),
        }
    )
    return env


def _checked_commit(commit: str, env: Mapping[str, str], cwd: Path) -> str:
    if not COMMIT_RE.fullmatch(commit):
        raise ValueError("--commit must be an exact full 40-character lowercase commit hash")
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "%s^{commit}" % commit],
        cwd=str(cwd),
        env=dict(env),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="ascii",
    )
    resolved = result.stdout.strip()
    if resolved != commit:
        raise ValueError("Git resolved the requested commit to a different object")
    return resolved


def _safe_extract_git_archive(archive_bytes: bytes, destination: Path) -> Tuple[str, ...]:
    allowed_roots = {"backtrader", "backtrader_runtime"}
    allowed_files = {"setup.py", "pyproject.toml", "README.md", "LICENSE"}
    extracted = []
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
        for member in archive.getmembers():
            name = member.name.rstrip("/") if member.isdir() else member.name
            posix = PurePosixPath(name)
            if (
                not name
                or "\\" in name
                or posix.is_absolute()
                or any(part in ("", ".", "..") or ":" in part for part in name.split("/"))
            ):
                raise ValueError("unsafe Git archive path: %r" % name)
            if posix.parts[0] not in (allowed_roots | allowed_files):
                raise ValueError("unexpected Git archive path: %r" % name)
            if len(posix.parts) == 1 and posix.parts[0] in allowed_roots:
                if not member.isdir():
                    raise ValueError("selected package root is not a directory: %r" % name)
            elif len(posix.parts) == 1 and posix.parts[0] in allowed_files:
                if not member.isfile():
                    raise ValueError("selected root input is not a regular file: %r" % name)
            elif posix.parts[0] in allowed_roots:
                if not (member.isdir() or member.isfile()):
                    raise ValueError("non-regular package archive member: %r" % name)
            else:
                raise ValueError("unexpected Git archive member shape: %r" % name)

            target = destination.joinpath(*posix.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("Git archive file has no readable payload: %r" % name)
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                extracted.append(name)
    required = {"setup.py", "pyproject.toml", "README.md", "LICENSE"}
    absent = required - set(extracted)
    if absent:
        raise ValueError("Git archive omitted selected inputs: %s" % sorted(absent))
    if not (destination / "backtrader" / "__init__.py").is_file():
        raise ValueError("Git archive has no Backtrader package initializer")
    if not (destination / "backtrader_runtime" / "__init__.py").is_file():
        raise ValueError("Git archive has no Backtrader Runtime package initializer")
    return tuple(sorted(extracted))


def _git_archive(commit: str, destination: Path, env: Mapping[str, str]) -> Tuple[str, ...]:
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", commit, *ARCHIVE_PATHS],
        cwd=str(SOURCE_ROOT),
        env=dict(env),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    archive_path = destination.parent / "backtrader-source.tar"
    archive_path.write_bytes(result.stdout)
    files = _safe_extract_git_archive(result.stdout, destination)
    return files


def _wheel_metadata(
    archive: zipfile.ZipFile, names: Sequence[str], expected_name: str
) -> Mapping[str, str]:
    metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
    if len(metadata_names) != 1:
        raise ValueError("wheel must contain exactly one dist-info/METADATA")
    from email.parser import BytesParser

    metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
    name = str(metadata.get("Name", ""))
    version = str(metadata.get("Version", ""))
    if name.casefold().replace("_", "-") != expected_name.casefold().replace("_", "-"):
        raise ValueError("wheel metadata names %r, expected %r" % (name, expected_name))
    if not version:
        raise ValueError("wheel metadata has no Version")
    return {"name": name, "version": version, "metadata_path": metadata_names[0]}


def _verify_wheel_record(wheel_path: Path) -> Mapping[str, Any]:
    with zipfile.ZipFile(wheel_path, "r") as archive:
        infos = archive.infolist()
        infos = [info for info in infos if not info.is_dir()]
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("wheel contains duplicate member names")
        if any(
            PurePosixPath(name).is_absolute()
            or "\\" in name
            or any(part in ("", ".", "..") for part in name.split("/"))
            for name in names
        ):
            raise ValueError("wheel contains an unsafe member path")
        record_names = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(record_names) != 1:
            raise ValueError("wheel must contain exactly one dist-info/RECORD")
        record_name = record_names[0]
        rows = csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"), newline=""))
        checked = set()
        for row in rows:
            if len(row) != 3:
                raise ValueError("wheel RECORD has a malformed row")
            member_name, digest_field, size_field = row
            if member_name in checked or member_name not in names:
                raise ValueError("wheel RECORD has duplicate or unknown member %r" % member_name)
            checked.add(member_name)
            payload = archive.read(member_name)
            if member_name == record_name:
                if digest_field or size_field:
                    raise ValueError("RECORD must leave its own hash and size blank")
                continue
            algorithm, separator, encoded_digest = digest_field.partition("=")
            if separator != "=" or algorithm != "sha256" or not encoded_digest:
                raise ValueError("wheel RECORD member has no supported SHA-256")
            expected_digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            expected_digest = expected_digest.rstrip(b"=").decode("ascii")
            if encoded_digest != expected_digest or size_field != str(len(payload)):
                raise ValueError("wheel RECORD check failed for %s" % member_name)
        if checked != set(names):
            raise ValueError("wheel RECORD does not cover every wheel member")
        metadata = _wheel_metadata(
            archive, names, "backtrader" if wheel_path.name.startswith("backtrader-") else "fincore"
        )
        return {
            "wheel": str(wheel_path.resolve()),
            "wheel_sha256": _sha256_file(wheel_path),
            "member_count": len(names),
            "record_member_count": len(checked),
            "record_path": record_name,
            "distribution": metadata,
            "members": tuple(names),
            "package_payloads": tuple(name for name in names if name.startswith(PACKAGE_PREFIXES)),
        }


def _verify_package_payloads_against_archive(
    wheel_path: Path, source_root: Path, archive_files: Sequence[str]
) -> Tuple[str, ...]:
    with zipfile.ZipFile(wheel_path, "r") as archive:
        package_names = tuple(
            sorted(
                info.filename
                for info in archive.infolist()
                if not info.is_dir() and info.filename.startswith(PACKAGE_PREFIXES)
            )
        )
        if not package_names:
            raise ValueError("Backtrader wheel contains no package payload")
        archived_python = {
            name
            for name in archive_files
            if name.startswith(PACKAGE_PREFIXES) and name.endswith(".py")
        }
        wheel_python = {name for name in package_names if name.endswith(".py")}
        if wheel_python != archived_python:
            raise ValueError(
                "wheel Python package membership differs from the selected commit "
                "(missing=%s, extra=%s)"
                % (
                    sorted(archived_python - wheel_python),
                    sorted(wheel_python - archived_python),
                )
            )
        for name in package_names:
            source_path = source_root.joinpath(*PurePosixPath(name).parts)
            if not source_path.is_file():
                raise ValueError("wheel payload has no selected-commit source: %s" % name)
            wheel_bytes = archive.read(name)
            source_bytes = source_path.read_bytes()
            if wheel_bytes != source_bytes:
                raise ValueError("wheel payload differs from selected-commit source: %s" % name)
        python_payloads = tuple(name for name in package_names if name.endswith(".py"))
        expected_catalog = "backtrader/research/alpha101_dependencies.json"
        if expected_catalog not in package_names:
            raise ValueError("wheel omitted the public Alpha101 dependency catalog")
        return python_payloads


def _verify_explicit_package_data(wheel_path: Path, setup_path: Path) -> Tuple[str, ...]:
    """Require every literal setup.py package_data file in the built wheel."""
    tree = ast.parse(setup_path.read_text(encoding="utf-8"), filename=str(setup_path))
    setup_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "setup")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "setup")
        )
    ]
    package_data_nodes = [
        keyword.value
        for node in setup_calls
        for keyword in node.keywords
        if keyword.arg == "package_data"
    ]
    if len(package_data_nodes) != 1 or not isinstance(package_data_nodes[0], ast.Dict):
        raise ValueError("selected setup.py must declare one literal package_data mapping")

    expected = []
    mapping = package_data_nodes[0]
    for package_node, files_node in zip(mapping.keys, mapping.values):
        if not isinstance(package_node, ast.Constant) or not isinstance(package_node.value, str):
            raise ValueError("setup.py package_data contains a nonliteral package name")
        if not isinstance(files_node, (ast.List, ast.Tuple)):
            raise ValueError("setup.py package_data values must be literal file lists")
        for file_node in files_node.elts:
            if not isinstance(file_node, ast.Constant) or not isinstance(file_node.value, str):
                raise ValueError("setup.py package_data contains a nonliteral file path")
            item = file_node.value
            item_path = PurePosixPath(item)
            if (
                not item
                or "\\" in item
                or item_path.is_absolute()
                or any(part in ("", ".", "..") for part in item.split("/"))
                or any(token in item for token in ("*", "?", "[", "]"))
            ):
                raise ValueError(
                    "setup.py package_data path is not an exact relative file: %r" % item
                )
            expected.append("%s/%s" % (package_node.value, item_path.as_posix()))

    with zipfile.ZipFile(wheel_path, "r") as archive:
        wheel_names = set(archive.namelist())
        for relative in expected:
            source_file = setup_path.parent.joinpath(*PurePosixPath(relative).parts)
            if not source_file.is_file():
                raise ValueError("setup.py package_data source file is absent: %s" % relative)
            if relative not in wheel_names:
                raise ValueError("wheel omitted setup.py package_data file: %s" % relative)
            if archive.read(relative) != source_file.read_bytes():
                raise ValueError("wheel package_data differs from selected source: %s" % relative)
    return tuple(sorted(expected))


def _copy_committed_test_tree(
    commit: str, qa_root: Path, env: Mapping[str, str]
) -> Tuple[Mapping[str, str], Mapping[str, str]]:
    copied: Dict[str, str] = {}
    generated_markers: Dict[str, str] = {}
    for relative in TEST_COPY_PATHS:
        result = subprocess.run(
            ["git", "show", "%s:%s" % (commit, relative)],
            cwd=str(SOURCE_ROOT),
            env=dict(env),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        payload = result.stdout
        destination = qa_root.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        copied[relative] = _sha256_bytes(payload)
    for marker in TEST_PACKAGE_MARKERS:
        destination = qa_root.joinpath(*PurePosixPath(marker).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"")
        generated_markers[marker] = _sha256_bytes(b"")
    if (qa_root / "backtrader" / "__init__.py").exists():
        raise ValueError("external QA tree must not contain backtrader/__init__.py")
    if (qa_root / "backtrader" / "research" / "__init__.py").exists():
        raise ValueError("external QA tree must not turn the catalog into a shadow package")
    return copied, generated_markers


def _installed_verifier_source() -> str:
    return r"""
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

if os.environ.get("PYTHONPATH"):
    raise SystemExit("PYTHONPATH must be unset for installed verification")

def origin(module):
    value = getattr(module, "__file__", None)
    if not isinstance(value, str) or not value:
        raise SystemExit("module has no file origin: " + module.__name__)
    path = Path(value).resolve()
    relative = path.relative_to(Path(sys.prefix).resolve())
    if not any(part.casefold() in ("site-packages", "dist-packages") for part in relative.parts):
        raise SystemExit("module origin is outside site-packages: " + module.__name__)
    return str(path)

backtrader = importlib.import_module("backtrader")
alpha101 = importlib.import_module("backtrader.research.alpha101")
fincore = importlib.import_module("fincore")
fincore_research = importlib.import_module("fincore.factor_analysis.research")
modules = (
    "backtrader.research.factor_strategy",
    "backtrader.research.fincore_adapter",
    "backtrader.research.alpha101.promoted",
    "backtrader.research.alpha101.batch_a",
    "backtrader.research.alpha101.batch_b",
    "backtrader.research.alpha101.batch_c",
    "backtrader.research.alpha101.batch_d",
    "backtrader.research.alpha101.batch_e",
)
module_origins = {"backtrader": origin(backtrader), "backtrader.research.alpha101": origin(alpha101)}
module_origins["fincore"] = origin(fincore)
module_origins["fincore.factor_analysis.research"] = origin(fincore_research)
for name in modules:
    module = importlib.import_module(name)
    module_origins[name] = origin(module)
ids = tuple(alpha101.list_alphas())
if ids != tuple(range(1, 102)):
    raise SystemExit("installed native registry does not cover Alpha001..Alpha101")
class_origins = {}
for alpha_id in ids:
    factor = alpha101.get_alpha(alpha_id)
    module = importlib.import_module(factor.__module__)
    class_origins[str(alpha_id)] = {
        "module": factor.__module__,
        "origin": origin(module),
    }
backtrader_version = importlib.metadata.version("backtrader")
fincore_version = importlib.metadata.version("fincore")
distribution = importlib.metadata.distribution("backtrader")
site_root = Path(distribution.locate_file("")).resolve()
site_root.relative_to(Path(sys.prefix).resolve())
print("__ALPHA101_INSTALL_VERIFY__" + json.dumps({
    "python": sys.version,
    "sys_prefix": str(Path(sys.prefix).resolve()),
    "site_root": str(site_root),
    "backtrader_version": backtrader_version,
    "fincore_version": fincore_version,
    "module_origins": module_origins,
    "class_origins": class_origins,
}, sort_keys=True))
"""


def _verify_installed_wheel_members(
    wheel_path: Path,
    site_root: Path,
    package_prefixes: Sequence[str],
    distribution_label: str,
) -> Tuple[str, ...]:
    """Compare wheel members with site-packages and verify their installed RECORD rows.

    pip may rewrite RECORD and add installer metadata or bytecode, so the wheel's
    RECORD file is excluded from byte equality. Every other wheel member must be
    present byte-for-byte and have a matching hash and size in installed RECORD.
    """
    with zipfile.ZipFile(wheel_path, "r") as archive:
        names = tuple(name for name in archive.namelist() if not name.endswith("/"))
        record_names = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(record_names) != 1:
            raise ValueError("%s wheel must contain exactly one RECORD" % distribution_label)
        record_name = record_names[0]
        dist_info_prefix = record_name.split("/", 1)[0] + "/"
        unexpected = [
            name
            for name in names
            if name != record_name
            and not name.startswith(tuple(package_prefixes))
            and not name.startswith(dist_info_prefix)
        ]
        if unexpected:
            raise ValueError(
                "%s wheel has members outside package and dist-info paths: %s"
                % (distribution_label, sorted(unexpected))
            )

        installed_record_path = site_root.joinpath(*PurePosixPath(record_name).parts)
        if not installed_record_path.is_file():
            raise ValueError("installed %s RECORD is missing" % distribution_label)
        with installed_record_path.open("r", encoding="utf-8", newline="") as source:
            rows = csv.reader(source)
            installed_rows: Dict[str, Tuple[str, str]] = {}
            for row in rows:
                if len(row) != 3:
                    raise ValueError("installed %s RECORD has a malformed row" % distribution_label)
                member_name, digest_field, size_field = row
                if member_name in installed_rows:
                    raise ValueError(
                        "installed %s RECORD has duplicate member %s"
                        % (distribution_label, member_name)
                    )
                installed_rows[member_name] = (digest_field, size_field)

        self_row = installed_rows.get(record_name)
        if self_row != ("", ""):
            raise ValueError(
                "installed %s RECORD must leave its own hash and size blank" % distribution_label
            )

        for relative in names:
            if relative == record_name:
                continue
            installed_path = site_root.joinpath(*PurePosixPath(relative).parts)
            if not installed_path.is_file():
                raise ValueError(
                    "installed %s wheel member is missing: %s" % (distribution_label, relative)
                )
            installed_bytes = installed_path.read_bytes()
            if installed_bytes != archive.read(relative):
                raise ValueError(
                    "installed %s payload differs from the wheel: %s"
                    % (distribution_label, relative)
                )
            digest_field, size_field = installed_rows.get(relative, (None, None))
            expected_digest = base64.urlsafe_b64encode(hashlib.sha256(installed_bytes).digest())
            expected_digest = expected_digest.rstrip(b"=").decode("ascii")
            if digest_field != "sha256=" + expected_digest or size_field != str(
                len(installed_bytes)
            ):
                raise ValueError(
                    "installed %s RECORD hash or size does not match payload: %s"
                    % (distribution_label, relative)
                )
        wheel_python_names = {
            name
            for name in names
            if name.startswith(tuple(package_prefixes)) and name.endswith(".py")
        }
        installed_python_names = set()
        for package_prefix in package_prefixes:
            package_root = site_root.joinpath(*PurePosixPath(package_prefix.rstrip("/")).parts)
            if not package_root.is_dir():
                raise ValueError(
                    "installed %s package directory is missing: %s"
                    % (distribution_label, package_prefix)
                )
            for path in package_root.rglob("*.py"):
                if path.is_file() and "__pycache__" not in path.parts:
                    installed_python_names.add(path.relative_to(site_root).as_posix())
        if installed_python_names != wheel_python_names:
            raise ValueError(
                "installed %s Python file set differs from its wheel "
                "(missing=%s, extra=%s)"
                % (
                    distribution_label,
                    sorted(wheel_python_names - installed_python_names),
                    sorted(installed_python_names - wheel_python_names),
                )
            )
        return names


def _verify_installed_payloads(
    python: Path,
    wheel_path: Path,
    fincore_wheel_path: Path,
    output_root: Path,
    env: Mapping[str, str],
) -> Mapping[str, Any]:
    completed = _run(
        [str(python), "-c", _installed_verifier_source()],
        cwd=output_root,
        env=env,
        log_path=output_root / "installed-verification.log",
    )
    marker = "__ALPHA101_INSTALL_VERIFY__"
    records = [
        line[len(marker) :]
        for line in (completed.stdout or "").splitlines()
        if line.startswith(marker)
    ]
    if len(records) != 1:
        raise ValueError("installed verifier did not emit exactly one finite JSON record")
    result = json.loads(records[0])
    site_root = Path(result["site_root"]).resolve()
    if not site_root.is_relative_to(Path(result["sys_prefix"]).resolve()):
        raise ValueError("installed distribution root is outside the active interpreter")
    backtrader_members = set(
        _verify_installed_wheel_members(wheel_path, site_root, PACKAGE_PREFIXES, "Backtrader")
    )
    backtrader_package_names = {
        name for name in backtrader_members if name.startswith(PACKAGE_PREFIXES)
    }
    for module_name, module_origin in result["module_origins"].items():
        if module_name.startswith("fincore"):
            continue
        origin = Path(module_origin).resolve()
        relative = origin.relative_to(site_root).as_posix()
        if relative not in backtrader_package_names:
            raise ValueError(
                "module %s origin is not a Backtrader wheel package payload" % module_name
            )
    for alpha_id, item in result["class_origins"].items():
        origin = Path(item["origin"]).resolve()
        relative = origin.relative_to(site_root).as_posix()
        if relative not in backtrader_package_names:
            raise ValueError("Alpha%s module origin is not a wheel package payload" % alpha_id)
        if not relative.startswith(PACKAGE_PREFIXES[0]):
            raise ValueError("Alpha%s is not installed from the Backtrader package" % alpha_id)
    fincore_members = set(
        _verify_installed_wheel_members(fincore_wheel_path, site_root, ("fincore/",), "fincore")
    )
    fincore_package_names = {name for name in fincore_members if name.startswith("fincore/")}
    for module_name in ("fincore", "fincore.factor_analysis.research"):
        origin = Path(result["module_origins"][module_name]).resolve()
        relative = origin.relative_to(site_root).as_posix()
        if relative not in fincore_package_names:
            raise ValueError(
                "module %s origin is not a payload of the accepted fincore wheel" % module_name
            )
    if len(result["class_origins"]) != 101:
        raise ValueError("installed-origin proof did not cover all 101 registry classes")
    return result


def _validate_output_path(path: Path) -> Path:
    output_root = path.expanduser().resolve(strict=False)
    temp_root = Path("D:/temp").resolve(strict=False)
    try:
        relative = output_root.relative_to(temp_root)
    except ValueError as exc:
        raise ValueError("--output-root must be below D:/temp") from exc
    if len(relative.parts) != 1 or not relative.parts[0].startswith("iteration46-wheel-"):
        raise ValueError("--output-root must be D:/temp/iteration46-wheel-<short>")
    suffix = relative.parts[0][len("iteration46-wheel-") :]
    if not re.fullmatch(r"[A-Za-z0-9-]+", suffix):
        raise ValueError(
            "--output-root suffix must contain only ASCII letters, digits, and hyphens"
        )
    if output_root.exists():
        raise FileExistsError("--output-root must be fresh and absent: %s" % output_root)
    return output_root


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ps_literal(value: str) -> str:
    """Return a PowerShell single-quoted string with embedded quotes doubled."""
    return "'" + value.replace("'", "''") + "'"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit", required=True, help="full 40-character committed Backtrader SHA"
    )
    parser.add_argument(
        "--output-root", required=True, help="fresh D:/temp/iteration46-wheel-<short>"
    )
    parser.add_argument(
        "--python", required=True, help="existing isolated acceptance venv python.exe"
    )
    args = parser.parse_args(argv)

    output_root = _validate_output_path(Path(args.output_root))
    python = Path(args.python).expanduser().resolve()
    if not python.is_file():
        raise FileNotFoundError("selected acceptance interpreter does not exist: %s" % python)
    if not FICORE_WHEEL.is_file() or FICORE_WHEEL.name != "fincore-0.5.1.dev0-py3-none-any.whl":
        raise FileNotFoundError("the accepted fincore wheel is missing at its pinned path")

    output_root.mkdir(parents=True, exist_ok=False)
    env = _command_environment(output_root)
    commit = _checked_commit(args.commit, env, SOURCE_ROOT)
    source_root = output_root / "source"
    source_root.mkdir()
    archive_files = _git_archive(commit, source_root, env)
    (output_root / "git-archive-files.json").write_text(
        json.dumps(list(archive_files), indent=2) + "\n", encoding="utf-8"
    )

    dist_root = output_root / "dist"
    dist_root.mkdir()
    _run(
        [
            str(python),
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(dist_root),
            str(source_root),
        ],
        cwd=output_root,
        env=env,
        log_path=output_root / "wheel-build.log",
    )
    wheels = tuple(sorted(dist_root.glob("*.whl")))
    if len(wheels) != 1 or not wheels[0].name.startswith("backtrader-"):
        raise ValueError("expected exactly one backtrader wheel from the selected commit")
    backtrader_wheel = wheels[0]
    backtrader_record = _verify_wheel_record(backtrader_wheel)
    if backtrader_record["distribution"]["name"].casefold() != "backtrader":
        raise ValueError("built wheel metadata is not for Backtrader")
    wheel_python_payloads = _verify_package_payloads_against_archive(
        backtrader_wheel, source_root, archive_files
    )
    package_data_payloads = _verify_explicit_package_data(
        backtrader_wheel, source_root / "setup.py"
    )

    fincore_record = _verify_wheel_record(FICORE_WHEEL)
    if fincore_record["distribution"]["version"] != FINCORE_VERSION:
        raise ValueError("accepted fincore wheel metadata version changed")
    if fincore_record["wheel_sha256"] != FINCORE_WHEEL_SHA256:
        raise ValueError("accepted fincore wheel SHA-256 differs from its frozen pin")

    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            str(FICORE_WHEEL),
        ],
        cwd=output_root,
        env=env,
        log_path=output_root / "fincore-wheel-install.log",
    )

    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            str(backtrader_wheel),
        ],
        cwd=output_root,
        env=env,
        log_path=output_root / "wheel-install.log",
    )
    _run(
        [str(python), "-m", "pip", "check"],
        cwd=output_root,
        env=env,
        log_path=output_root / "pip-check.log",
    )
    installed = _verify_installed_payloads(python, backtrader_wheel, FICORE_WHEEL, output_root, env)
    if installed["fincore_version"] != FINCORE_VERSION:
        raise ValueError("the selected venv does not contain the accepted fincore version")
    if installed["backtrader_version"] != backtrader_record["distribution"]["version"]:
        raise ValueError("installed Backtrader metadata differs from the built wheel")

    qa_root = output_root / "external-qa"
    qa_root.mkdir()
    copied_sources, generated_markers = _copy_committed_test_tree(commit, qa_root, env)
    provenance_path = qa_root / "alpha101-native-provenance.json"
    provenance = {
        "schema": "iteration46-installed-alpha101-provenance-v1",
        "backtrader": {
            "source_commit": commit,
            "version": backtrader_record["distribution"]["version"],
            "wheel_path": str(backtrader_wheel.resolve()),
            "wheel_sha256": backtrader_record["wheel_sha256"],
        },
        "fincore": {
            "source_commit": FINCORE_SOURCE_COMMIT,
            "version": FINCORE_VERSION,
            "wheel_path": str(FICORE_WHEEL.resolve()),
            "wheel_sha256": fincore_record["wheel_sha256"],
        },
    }
    _write_json(provenance_path, provenance)
    if (qa_root / "backtrader" / "research" / "alpha101_dependencies.json").read_bytes() != (
        source_root / "backtrader" / "research" / "alpha101_dependencies.json"
    ).read_bytes():
        raise ValueError("external QA catalog differs from the selected commit archive")

    report = {
        "schema": "iteration46-installed-alpha101-wheel-preparation-v1",
        "source_commit": commit,
        "source_archive_file_count": len(archive_files),
        "source_archive_sha256": _sha256_file(output_root / "backtrader-source.tar"),
        "backtrader_wheel": backtrader_record,
        "backtrader_wheel_python_payload_count": len(wheel_python_payloads),
        "backtrader_setup_package_data_payloads": list(package_data_payloads),
        "fincore_wheel": fincore_record,
        "installed": installed,
        "pip_check_log": str((output_root / "pip-check.log").resolve()),
        "external_qa_root": str(qa_root.resolve()),
        "copied_test_inputs_sha256": copied_sources,
        "generated_empty_test_markers_sha256": generated_markers,
        "provenance_manifest": str(provenance_path.resolve()),
        "pytest_executed": False,
    }
    _write_json(output_root / "build-acceptance.json", report)
    pytest_basetemp = output_root / "pytest-basetemp"
    command = (
        "Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue\n"
        "Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue\n"
        "$env:BT_ALPHA101_NATIVE_INSTALLED_ACCEPTANCE = '1'\n"
        "$env:BT_ALPHA101_NATIVE_PROVENANCE_JSON = %s\n"
        "& %s -m pytest -q --basetemp %s tests/integration/test_alpha101_native_installed.py"
        % (
            _ps_literal(str(provenance_path.resolve())),
            _ps_literal(str(python)),
            _ps_literal(str(pytest_basetemp.resolve())),
        )
    )
    (output_root / "run-installed-acceptance.ps1").write_text(
        "$ErrorActionPreference = 'Stop'\nSet-Location %s\n%s\n"
        % (_ps_literal(str(qa_root.resolve())), command),
        encoding="utf-8",
    )
    print("Prepared external installed acceptance at %s" % qa_root.resolve())
    print(
        "No pytest command was run.  Root may execute %s after reviewing the build record."
        % (output_root / "run-installed-acceptance.ps1")
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("ERROR: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        raise SystemExit(2)
