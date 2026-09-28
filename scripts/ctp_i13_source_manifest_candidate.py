"""Build a non-authorizing manifest snapshot for the current dirty I13 tree.

This writes only the explicitly named candidate artifact under ``artifacts``.
It never writes the runtime manifest path or either code-owned pin.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import zlib
from pathlib import Path, PurePosixPath
from typing import Mapping, Union


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1
MANIFEST_RELATIVE_PATH = PurePosixPath("backtrader_runtime/ctp_i13_source_manifest.json")
FIXED_READONLY_WORKER_PATH = PurePosixPath("scripts/ctp_i13_i15_readonly_preflight_worker.py")
FIXED_READONLY_BOOTSTRAP_PATH = PurePosixPath(
    "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"
)
FIXED_READONLY_REQUEST_COORDINATOR_PATH = PurePosixPath(
    "scripts/ctp_i13_i15_readonly_request_coordinator.py"
)
FIXED_READONLY_RECEIPT_WRITER_PATH = PurePosixPath(
    "scripts/ctp_i13_i15_readonly_receipt_writer.py"
)
FIXED_READONLY_TOKEN_BOOTSTRAP_PATH = PurePosixPath(
    "scripts/ctp_i13_i15_readonly_token_bootstrap.py"
)
FIXED_READONLY_SERVICE_ROLE_PATHS = (
    FIXED_READONLY_REQUEST_COORDINATOR_PATH,
    FIXED_READONLY_RECEIPT_WRITER_PATH,
    FIXED_READONLY_TOKEN_BOOTSTRAP_PATH,
)
FIXED_WORKER_DEPENDENCY_HELPER_PATH = PurePosixPath(
    "backtrader_runtime/ctp_i13_worker_dependency_seal.py"
)
BOOTSTRAP_EMBEDDED_SUPPORT_PATHS = (
    PurePosixPath("scripts/ctp_i13_i15_guardian_deployment_anchor.py"),
    PurePosixPath("scripts/ctp_i13_i15_parent_launcher.py"),
    PurePosixPath("scripts/ctp_i13_i15_runtime_closure.py"),
    PurePosixPath("scripts/ctp_i13_i15_outer_watchdog.py"),
    PurePosixPath("scripts/ctp_i13_i15_worker_output_channel.py"),
    PurePosixPath("scripts/ctp_i13_i15_windows_job_backend.py"),
)
PIN_PATHS = frozenset(
    {
        "backtrader_runtime/ctp_i13_source_identity_pin.py",
        "backtrader_runtime/ctp_i15_source_identity_pin.py",
    }
)
REQUIRED_PATHS = frozenset(
    {
        "backtrader_runtime/__init__.py",
        "backtrader_runtime/inventory.py",
        "backtrader_runtime/ctp_i13_md_oneshot_supervisor.py",
        FIXED_WORKER_DEPENDENCY_HELPER_PATH.as_posix(),
        FIXED_READONLY_WORKER_PATH.as_posix(),
        FIXED_READONLY_BOOTSTRAP_PATH.as_posix(),
        *(path.as_posix() for path in FIXED_READONLY_SERVICE_ROLE_PATHS),
    }
)
CANDIDATE_OUTPUT = Path("artifacts/ctp_i13_source_manifest.current_dirty_tree_candidate.json")
BOOTSTRAP_OUTPUT = Path(*FIXED_READONLY_BOOTSTRAP_PATH.parts)
_REPARSE_POINT = 0x400
_MAX_SOURCE_FILES = 256
_MAX_BOOTSTRAP_BYTES = 256 * 1024
_MAX_EMBEDDED_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_EMBEDDED_SOURCE_BUNDLE_BYTES = 4 * 1024 * 1024


class SourceManifestCandidateError(ValueError):
    """A redacted, fail-closed candidate-manifest construction error."""


def _is_reparse_point(file_stat: os.stat_result) -> bool:
    return stat.S_ISLNK(file_stat.st_mode) or bool(
        getattr(file_stat, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _checked_absolute_directory(path: Union[Path, str]) -> Path:
    """Resolve lexically and reject reparse points in every root component."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    try:
        for part in absolute.parts[1:]:
            current = current / part
            current_stat = os.lstat(current)
            if _is_reparse_point(current_stat) or not stat.S_ISDIR(current_stat.st_mode):
                raise SourceManifestCandidateError("candidate_source_root_invalid")
    except SourceManifestCandidateError:
        raise
    except OSError as exc:
        raise SourceManifestCandidateError("candidate_source_root_invalid") from exc
    return absolute


def discover_i13_source_files(source_root: Union[Path, str]) -> tuple[str, ...]:
    """Return runtime sources plus exact readonly worker/bootstrap/role data, except pins."""

    root = _checked_absolute_directory(source_root)
    package_root = root / "backtrader_runtime"
    try:
        package_stat = os.lstat(package_root)
    except OSError as exc:
        raise SourceManifestCandidateError("source_tree_unavailable") from exc
    if _is_reparse_point(package_stat) or not stat.S_ISDIR(package_stat.st_mode):
        raise SourceManifestCandidateError("source_tree_invalid")

    python_paths: set[str] = set()

    def on_walk_error(_error: OSError) -> None:
        raise SourceManifestCandidateError("source_tree_unavailable")

    for current_text, directory_names, file_names in os.walk(
        package_root, topdown=True, followlinks=False, onerror=on_walk_error
    ):
        current = Path(current_text)
        kept_directories = []
        for directory_name in directory_names:
            directory = current / directory_name
            try:
                directory_stat = os.lstat(directory)
            except OSError as exc:
                raise SourceManifestCandidateError("source_tree_unavailable") from exc
            if _is_reparse_point(directory_stat) or not stat.S_ISDIR(directory_stat.st_mode):
                raise SourceManifestCandidateError("source_tree_invalid")
            kept_directories.append(directory_name)
        directory_names[:] = kept_directories

        for file_name in file_names:
            source_path = current / file_name
            try:
                source_stat = os.lstat(source_path)
            except OSError as exc:
                raise SourceManifestCandidateError("source_tree_unavailable") from exc
            if _is_reparse_point(source_stat):
                raise SourceManifestCandidateError("source_tree_invalid")
            if not file_name.endswith(".py"):
                continue
            if not stat.S_ISREG(source_stat.st_mode):
                raise SourceManifestCandidateError("source_file_invalid")
            relative = source_path.relative_to(root).as_posix()
            python_paths.add(relative)

    for fixed_path in (
        FIXED_READONLY_WORKER_PATH,
        FIXED_READONLY_BOOTSTRAP_PATH,
        *FIXED_READONLY_SERVICE_ROLE_PATHS,
    ):
        fixed_directory = root / fixed_path.parts[0]
        fixed_file = root.joinpath(*fixed_path.parts)
        try:
            directory_stat = os.lstat(fixed_directory)
            file_stat = os.lstat(fixed_file)
        except OSError as exc:
            raise SourceManifestCandidateError("source_inventory_incomplete") from exc
        if _is_reparse_point(directory_stat) or not stat.S_ISDIR(directory_stat.st_mode):
            raise SourceManifestCandidateError("source_tree_invalid")
        if _is_reparse_point(file_stat) or not stat.S_ISREG(file_stat.st_mode):
            raise SourceManifestCandidateError("source_file_invalid")
        python_paths.add(fixed_path.as_posix())

    paths = python_paths - PIN_PATHS
    if (
        not REQUIRED_PATHS.issubset(paths)
        or not PIN_PATHS.issubset(python_paths)
        or not 1 <= len(paths) <= _MAX_SOURCE_FILES
    ):
        raise SourceManifestCandidateError("source_inventory_incomplete")
    return tuple(sorted(paths))


def _read_stable_source(source_root: Path, relative_path: str) -> bytes:
    source_path = source_root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        current = source_root
        for part in PurePosixPath(relative_path).parts[:-1]:
            current = current / part
            parent_stat = os.lstat(current)
            if _is_reparse_point(parent_stat) or not stat.S_ISDIR(parent_stat.st_mode):
                raise SourceManifestCandidateError("source_path_invalid")
        before = os.lstat(source_path)
        if _is_reparse_point(before) or not stat.S_ISREG(before.st_mode):
            raise SourceManifestCandidateError("source_file_invalid")
        content = source_path.read_bytes()
        after = os.lstat(source_path)
    except SourceManifestCandidateError:
        raise
    except OSError as exc:
        raise SourceManifestCandidateError("source_file_unavailable") from exc
    if (
        _is_reparse_point(after)
        or not stat.S_ISREG(after.st_mode)
        or (before.st_dev, before.st_ino, before.st_size)
        != (after.st_dev, after.st_ino, after.st_size)
        or len(content) != after.st_size
    ):
        raise SourceManifestCandidateError("source_file_changed_during_read")
    return content


def _bootstrap_runner_source() -> bytes:
    """Return the thin fixed runner appended after the captured importer source."""

    return r'''
# This generated tail is part of the fixed, hash-bound bootstrap artifact.
_READONLY_BOOTSTRAP_BINDING_ENV = "BT_I13_READONLY_BOOTSTRAP_BINDING"
_READONLY_BOOTSTRAP_BINDING_SCHEMA = "ctp_i13_i15_readonly_preflight_bootstrap_binding.v3"
_READONLY_BOOTSTRAP_SUPPORT_SCHEMA = 2
_READONLY_BOOTSTRAP_SUPPORT_B85 = "__SUPPORT_B85__"
_READONLY_BOOTSTRAP_SUPPORT_SHA256 = "__SUPPORT_SHA256__"
_READONLY_BOOTSTRAP_SUPPORT_PATHS = (
    "scripts/ctp_i13_i15_guardian_deployment_anchor.py",
    "scripts/ctp_i13_i15_parent_launcher.py",
    "scripts/ctp_i13_i15_runtime_closure.py",
    "scripts/ctp_i13_i15_outer_watchdog.py",
    "scripts/ctp_i13_i15_worker_output_channel.py",
    "scripts/ctp_i13_i15_windows_job_backend.py",
)
_READONLY_BOOTSTRAP_MAX_SUPPORT_BYTES = 4 * 1024 * 1024
_READONLY_BOOTSTRAP_MAX_WORKER_OUTPUT_BYTES = 63 * 1024
_READONLY_BOOTSTRAP_ZERO_SHA256 = "0" * 64


def _readonly_bootstrap_fail(reason):
    sys.stderr.write("readonly_preflight_rejected:" + reason + "\n")
    sys.stderr.flush()
    return 78


def _readonly_bootstrap_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _readonly_bootstrap_digest(value):
    return (
        type(value) is str
        and len(value) == 64
        and value != _READONLY_BOOTSTRAP_ZERO_SHA256
        and all(char in "0123456789abcdef" for char in value)
    )


def _readonly_bootstrap_binding():
    expected_env_names = {
        "path",
        "systemroot",
        "windir",
        _READONLY_BOOTSTRAP_BINDING_ENV.casefold(),
    }
    folded_env = {}
    for name, value in os.environ.items():
        folded = name.casefold()
        if folded in folded_env:
            raise ValueError("environment")
        folded_env[folded] = value
    if set(folded_env) != expected_env_names:
        raise ValueError("environment")
    raw_text = folded_env[_READONLY_BOOTSTRAP_BINDING_ENV.casefold()]
    if type(raw_text) is not str or not raw_text or len(raw_text) > 4096:
        raise ValueError("binding_size")
    raw = raw_text.encode("ascii", "strict")
    wire_binding = json.loads(raw.decode("ascii"), object_pairs_hook=_readonly_bootstrap_pairs)
    if type(wire_binding) is not dict:
        raise ValueError("binding_fields")
    worker_schema = "ctp_i13_i15_readonly_preflight_bootstrap_binding.v3"
    receipt_schema = "ctp_i13_i15_readonly_receipt_writer_binding.v1"
    if wire_binding.get("schema") == worker_schema:
        expected_keys = {
            "schema",
            "deployment_descriptor_sha256",
            "source_manifest_sha256",
            "i13_pin_sha256",
            "i15_pin_sha256",
            "bootstrap_sha256",
            "worker_sha256",
            "dependency_manifest_sha256",
            "runtime_manifest_sha256",
            "python_sha256",
            "deadline_monotonic_ns",
            "request_id",
            "worker_output",
        }
        if set(wire_binding) != expected_keys:
            raise ValueError("binding_fields")
        binding = dict(wire_binding)
        binding["_readonly_role"] = "worker"
        binding["_readonly_role_binding"] = wire_binding
    elif wire_binding.get("schema") == receipt_schema:
        expected_keys = {
            "schema",
            "request_id",
            "deadline_monotonic_ns",
            "deployment",
            "work_result",
            "coordinator_job",
            "receipt_output_channel",
        }
        if set(wire_binding) != expected_keys:
            raise ValueError("binding_fields")
        deployment = wire_binding["deployment"]
        deployment_keys = {
            "descriptor_sha256",
            "source_manifest_sha256",
            "runtime_manifest_sha256",
            "dependency_manifest_sha256",
            "python_sha256",
            "i13_pin_sha256",
            "i15_pin_sha256",
            "bootstrap_sha256",
            "worker_sha256",
            "coordinator_sha256",
            "receipt_writer_sha256",
            "token_bootstrap_sha256",
        }
        if type(deployment) is not dict or set(deployment) != deployment_keys:
            raise ValueError("deployment_binding")
        channel = wire_binding["receipt_output_channel"]
        if type(channel) is not dict or set(channel) != {"nonce", "server_pid"}:
            raise ValueError("receipt_output_binding")
        binding = {
            "schema": wire_binding["schema"],
            "_readonly_role": "receipt_writer",
            "_readonly_role_binding": wire_binding,
            "deployment_descriptor_sha256": deployment["descriptor_sha256"],
            "source_manifest_sha256": deployment["source_manifest_sha256"],
            "i13_pin_sha256": deployment["i13_pin_sha256"],
            "i15_pin_sha256": deployment["i15_pin_sha256"],
            "bootstrap_sha256": deployment["bootstrap_sha256"],
            "worker_sha256": deployment["worker_sha256"],
            "dependency_manifest_sha256": deployment["dependency_manifest_sha256"],
            "runtime_manifest_sha256": deployment["runtime_manifest_sha256"],
            "python_sha256": deployment["python_sha256"],
            "deadline_monotonic_ns": wire_binding["deadline_monotonic_ns"],
            "request_id": wire_binding["request_id"],
            "receipt_output_channel": channel,
            "_deployment": deployment,
        }
        if any(not _readonly_bootstrap_digest(value) for value in deployment.values()):
            raise ValueError("deployment_digest")
        if (
            type(channel["nonce"]) is not str
            or len(channel["nonce"]) != 32
            or channel["nonce"] == "0" * 32
            or any(char not in "0123456789abcdef" for char in channel["nonce"])
            or type(channel["server_pid"]) is not int
            or channel["server_pid"] <= 0
            or channel["server_pid"] > 0xFFFFFFFF
        ):
            raise ValueError("receipt_output_binding")
    else:
        raise ValueError("binding_schema")
    # Compare canonical wire bytes before adding private in-process aliases.
    canonical_wire = json.dumps(
        wire_binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    if canonical_wire.encode("ascii") != raw:
        raise ValueError("binding_canonical")
    if binding["_readonly_role"] == "worker":
        if binding["schema"] != _READONLY_BOOTSTRAP_BINDING_SCHEMA:
            raise ValueError("binding_canonical")
        for name in expected_keys - {"schema", "deadline_monotonic_ns", "request_id", "worker_output"}:
            if not _readonly_bootstrap_digest(binding[name]):
                raise ValueError("binding_digest")
    else:
        for name in (
            "deployment_descriptor_sha256",
            "source_manifest_sha256",
            "i13_pin_sha256",
            "i15_pin_sha256",
            "bootstrap_sha256",
            "worker_sha256",
            "dependency_manifest_sha256",
            "runtime_manifest_sha256",
            "python_sha256",
        ):
            if not _readonly_bootstrap_digest(binding[name]):
                raise ValueError("binding_digest")
    request_id = binding["request_id"]
    if (
        type(request_id) is not str
        or len(request_id) != 32
        or request_id == "0" * 32
        or any(char not in "0123456789abcdef" for char in request_id)
    ):
        raise ValueError("request_id")
    if binding["_readonly_role"] == "worker":
        worker_output = binding["worker_output"]
        if type(worker_output) is not dict or set(worker_output) != {"nonce", "server_pid"}:
            raise ValueError("worker_output_binding")
        nonce = worker_output["nonce"]
        server_pid = worker_output["server_pid"]
        if (
            type(nonce) is not str
            or len(nonce) != 32
            or nonce == "0" * 32
            or any(char not in "0123456789abcdef" for char in nonce)
            or type(server_pid) is not int
            or server_pid <= 0
            or server_pid > 0xFFFFFFFF
        ):
            raise ValueError("worker_output_binding")
    deadline = binding["deadline_monotonic_ns"]
    if type(deadline) is not int or deadline <= 0 or time.monotonic_ns() >= deadline:
        raise ValueError("deadline")
    return binding, folded_env


def _readonly_bootstrap_support():
    try:
        compressed = base64.b85decode(_READONLY_BOOTSTRAP_SUPPORT_B85.encode("ascii"))
        raw = zlib.decompress(compressed)
    except BaseException:
        raise ValueError("embedded_support_encoding") from None
    if (
        not raw
        or len(raw) > _READONLY_BOOTSTRAP_MAX_SUPPORT_BYTES
        or hashlib.sha256(raw).hexdigest() != _READONLY_BOOTSTRAP_SUPPORT_SHA256
    ):
        raise ValueError("embedded_support_digest")
    if type(raw) is not bytes or len(raw) < 4:
        raise ValueError("embedded_support_schema")
    header_size = int.from_bytes(raw[:4], "big", signed=False)
    if header_size <= 0 or header_size > 64 * 1024 or 4 + header_size > len(raw):
        raise ValueError("embedded_support_schema")
    try:
        value = json.loads(
            raw[4 : 4 + header_size].decode("ascii", "strict"),
            object_pairs_hook=_readonly_bootstrap_pairs,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise ValueError("embedded_support_schema") from None
    if (
        type(value) is not dict
        or set(value) != {"schema", "files"}
        or value["schema"] != _READONLY_BOOTSTRAP_SUPPORT_SCHEMA
    ):
        raise ValueError("embedded_support_schema")
    rows = value["files"]
    if type(rows) is not list or len(rows) != len(_READONLY_BOOTSTRAP_SUPPORT_PATHS):
        raise ValueError("embedded_support_files")
    sources = {}
    digests = {}
    cursor = 4 + header_size
    for expected_path, row in zip(_READONLY_BOOTSTRAP_SUPPORT_PATHS, rows):
        if type(row) is not dict or set(row) != {"path", "sha256", "size"}:
            raise ValueError("embedded_support_row")
        size = row["size"]
        if (
            row["path"] != expected_path
            or not _readonly_bootstrap_digest(row["sha256"])
            or type(size) is not int
            or size <= 0
            or size > _READONLY_BOOTSTRAP_MAX_SUPPORT_BYTES
            or cursor + size > len(raw)
        ):
            raise ValueError("embedded_support_binding")
        source = raw[cursor : cursor + size]
        cursor += size
        if hashlib.sha256(source).hexdigest() != row["sha256"]:
            raise ValueError("embedded_support_source_digest")
        source.decode("utf-8", "strict")
        sources[expected_path] = source
        digests[expected_path] = row["sha256"]
    if cursor != len(raw):
        raise ValueError("embedded_support_trailing_bytes")
    return sources, digests


def _readonly_bootstrap_exec_support(sources, relative_path, name):
    source = sources[relative_path]
    namespace = {"__name__": name, "__file__": "<fixed-embedded-source>"}
    exec(compile(source, "<fixed-embedded-source>", "exec", dont_inherit=True), namespace)
    return namespace


def _readonly_bootstrap_exec_support_modules(sources, digests, finder):
    fixed_paths = (
        "scripts/ctp_i13_i15_outer_watchdog.py",
        "scripts/ctp_i13_i15_worker_output_channel.py",
        "scripts/ctp_i13_i15_windows_job_backend.py",
    )
    if (
        any(name == "scripts" or name.startswith("scripts.") for name in sys.modules)
        or type(finder) is not SealedSourceFinder
    ):
        raise ValueError("bootstrap_support_import_state_invalid")
    package = type(sys)("scripts")
    finder._begin_fixed_bootstrap_support_package(
        package, capability=_FIXED_BOOTSTRAP_SUPPORT_REGISTRATION_TOKEN
    )
    modules = {}
    for relative_path in fixed_paths:
        module = finder._load_fixed_bootstrap_support_module(
            relative_path,
            sources[relative_path],
            expected_sha256=digests[relative_path],
            capability=_FIXED_BOOTSTRAP_SUPPORT_REGISTRATION_TOKEN,
        )
        modules[relative_path] = module
    return modules


def _readonly_bootstrap_architecture():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_process = kernel32.GetCurrentProcess
    get_process.argtypes = []
    get_process.restype = ctypes.c_void_p
    query_arch = getattr(kernel32, "IsWow64Process2", None)
    if query_arch is None:
        raise ValueError("architecture_unavailable")
    query_arch.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(ctypes.c_ushort)]
    query_arch.restype = ctypes.c_int
    process_machine = ctypes.c_ushort()
    native_machine = ctypes.c_ushort()
    if not query_arch(
        get_process(), ctypes.byref(process_machine), ctypes.byref(native_machine)
    ):
        raise ValueError("architecture_unavailable")
    machine = process_machine.value or native_machine.value
    if machine == 0x8664:
        return "AMD64"
    if machine == 0xAA64:
        return "ARM64"
    if machine == 0x014C:
        return "x86"
    return "unknown"


def _readonly_bootstrap_token_sid():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    token = ctypes.c_void_p()
    open_token = advapi32.OpenProcessToken
    open_token.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    open_token.restype = ctypes.c_int
    get_process = kernel32.GetCurrentProcess
    get_process.argtypes = []
    get_process.restype = ctypes.c_void_p
    if not open_token(get_process(), 0x0008, ctypes.byref(token)):
        raise ValueError("token_unavailable")
    try:
        get_info = advapi32.GetTokenInformation
        get_info.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        get_info.restype = ctypes.c_int
        required = ctypes.c_uint32()
        get_info(token, 1, None, 0, ctypes.byref(required))
        if required.value <= 0 or required.value > 65536:
            raise ValueError("token_unavailable")
        buffer = ctypes.create_string_buffer(required.value)
        if not get_info(token, 1, buffer, required.value, ctypes.byref(required)):
            raise ValueError("token_unavailable")
        class _SidAndAttributes(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]
        user = _SidAndAttributes.from_buffer(buffer)
        if not user.Sid:
            raise ValueError("token_unavailable")
        sid_text = ctypes.c_wchar_p()
        convert = advapi32.ConvertSidToStringSidW
        convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        convert.restype = ctypes.c_int
        if not convert(user.Sid, ctypes.byref(sid_text)):
            raise ValueError("token_unavailable")
        try:
            value = sid_text.value
            if type(value) is not str or not value:
                raise ValueError("token_unavailable")
            return value
        finally:
            local_free = kernel32.LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            local_free(ctypes.cast(sid_text, ctypes.c_void_p))
    finally:
        close = kernel32.CloseHandle
        close.argtypes = [ctypes.c_void_p]
        close.restype = ctypes.c_int
        close(token)


def _readonly_bootstrap_retain_paths(anchor_ns, root, files, directories):
    root = anchor_ns["_canonical_windows_path"](root, "runtime_root_invalid")
    if type(files) not in (tuple, list) or type(directories) not in (tuple, list):
        raise ValueError("runtime_path_set_invalid")
    protected_type = anchor_ns["_ProtectedWindowsPaths"]
    protected = protected_type(frozenset({anchor_ns["_SYSTEM_SID"], anchor_ns["_ADMINISTRATORS_SID"]}))
    try:
        protected.add_paths(
            (root,),
            directory_paths=frozenset({root}),
            listable_directory_paths=frozenset({root}),
        )
        for relative in directories:
            if type(relative) is not str or "\\" in relative:
                raise ValueError("runtime_path_set_invalid")
            if relative == "":
                continue
            relative_path = PurePosixPath(relative)
            if (
                relative_path.as_posix() != relative
                or relative_path.is_absolute()
                or any(part in {"", ".", ".."} for part in relative_path.parts)
            ):
                raise ValueError("runtime_path_set_invalid")
            path = ntpath.join(root, *relative.split("/"))
            protected.add_paths(
                (path,),
                directory_paths=frozenset({path}),
                listable_directory_paths=frozenset({path}),
            )
        for relative in files:
            if type(relative) is not str or not relative or "\\" in relative:
                raise ValueError("runtime_path_set_invalid")
            relative_path = PurePosixPath(relative)
            if (
                relative_path.as_posix() != relative
                or relative_path.is_absolute()
                or any(part in {"", ".", ".."} for part in relative_path.parts)
            ):
                raise ValueError("runtime_path_set_invalid")
            path = ntpath.join(root, *relative.split("/"))
            protected.add_paths((path,))
        return anchor_ns["_RetainedDependencyPaths"](root, protected)
    except BaseException:
        try:
            protected.close()
        except BaseException:
            pass
        raise


def _readonly_bootstrap_run_receipt_writer(
    binding,
    *,
    raw_binding,
    anchor_ns,
    descriptor,
    parent_facts,
    source_seal,
    source_finder,
    dependency_seal,
    runtime_seal,
    anchor_paths,
    support_modules,
):
    """Run only the sealed receipt-writer role with a fixed protected root."""

    if (
        binding.get("_readonly_role") != "receipt_writer"
        or type(raw_binding) is not dict
        or raw_binding.get("schema") != "ctp_i13_i15_readonly_receipt_writer_binding.v1"
        or type(source_finder) is not SealedSourceFinder
        or source_finder._seal is not source_seal
        or source_finder._runtime_closure is not runtime_seal
        or source_finder._dependency_finder is None
    ):
        raise ValueError("receipt_writer_runtime_unavailable")

    role_module = None
    receipt_paths = None
    runtime = None
    try:
        role_module = _open_fixed_readonly_role_module(
            source_seal, source_finder, "receipt_writer"
        )
        parsed_binding = role_module.parse_receipt_writer_binding(raw_binding)
        if (
            parsed_binding.request_id != binding["request_id"]
            or parsed_binding.deadline_monotonic_ns != binding["deadline_monotonic_ns"]
            or dict(parsed_binding.deployment) != binding["_deployment"]
        ):
            raise ValueError("receipt_writer_binding_mismatch")

        expected_deployment = {
            "descriptor_sha256": descriptor.descriptor_sha256,
            "source_manifest_sha256": source_seal.manifest_sha256,
            "runtime_manifest_sha256": runtime_seal.manifest_sha256,
            "dependency_manifest_sha256": dependency_seal.manifest_sha256,
            "python_sha256": descriptor.python_sha256,
            "i13_pin_sha256": parent_facts.candidates["i13_md"]["pin_sha256"],
            "i15_pin_sha256": parent_facts.candidates["i15_td"]["pin_sha256"],
            "bootstrap_sha256": source_seal.files.get(
                "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"
            ),
            "worker_sha256": source_seal.files.get(
                "scripts/ctp_i13_i15_readonly_preflight_worker.py"
            ),
            "coordinator_sha256": source_seal.files.get(
                "scripts/ctp_i13_i15_readonly_request_coordinator.py"
            ),
            "receipt_writer_sha256": source_seal.files.get(
                "scripts/ctp_i13_i15_readonly_receipt_writer.py"
            ),
            "token_bootstrap_sha256": source_seal.files.get(
                "scripts/ctp_i13_i15_readonly_token_bootstrap.py"
            ),
        }
        if any(type(value) is not str or not _readonly_bootstrap_digest(value) for value in expected_deployment.values()):
            raise ValueError("receipt_writer_deployment_incomplete")
        if dict(parsed_binding.deployment) != expected_deployment:
            raise ValueError("receipt_writer_deployment_mismatch")

        support_path = "scripts/ctp_i13_i15_worker_output_channel.py"
        output_channel_module = support_modules.get(support_path)
        if (
            output_channel_module is None
            or not source_finder._owns_fixed_bootstrap_support(
                "scripts.ctp_i13_i15_worker_output_channel", output_channel_module
            )
            or sys.modules.get("scripts.ctp_i13_i15_worker_output_channel")
            is not output_channel_module
        ):
            raise ValueError("receipt_writer_output_channel_unavailable")

        now_ns = time.monotonic_ns()
        if type(now_ns) is not int or now_ns >= parsed_binding.deadline_monotonic_ns:
            raise ValueError("deadline")

        program_data = anchor_ns["_program_data_path"]()
        fixed_root, _descriptor_path, _auth_key_path, _dependency_path, _runtime_path, receipt_root = (
            anchor_ns["_fixed_paths"](program_data)
        )
        expected_fixed_root = ntpath.join(
            program_data, *anchor_ns["FIXED_PROGRAMDATA_RELATIVE"].parts
        )
        if ntpath.normcase(ntpath.normpath(fixed_root)) != ntpath.normcase(
            ntpath.normpath(expected_fixed_root)
        ):
            raise ValueError("receipt_root_binding")

        integrity_sids = frozenset(
            {anchor_ns["_SYSTEM_SID"], anchor_ns["_ADMINISTRATORS_SID"]}
        )
        receipt_paths = anchor_ns["_ProtectedWindowsPaths"](integrity_sids)
        receipt_paths.add_paths(
            (receipt_root,),
            directory_paths=frozenset({receipt_root}),
            writable_paths=frozenset({receipt_root}),
            writer_sids_by_path={
                receipt_root: frozenset(
                    {
                        anchor_ns["_SYSTEM_SID"],
                        anchor_ns["_ADMINISTRATORS_SID"],
                        descriptor.service_sid,
                    }
                )
            },
        )
        if time.monotonic_ns() >= parsed_binding.deadline_monotonic_ns:
            raise ValueError("deadline")

        class _FixedReceiptWriterRuntime:
            __slots__ = (
                "_created",
                "_creation_started",
                "_execution_close_attempted",
                "_execution_close_errors",
                "_output_started",
                "_closed",
            )

            def __init__(self):
                self._created = False
                self._creation_started = False
                self._execution_close_attempted = False
                self._execution_close_errors = ()
                self._output_started = False
                self._closed = False

            def _check_deadline(self):
                now = time.monotonic_ns()
                if type(now) is not int or now < 0 or now >= parsed_binding.deadline_monotonic_ns:
                    raise ValueError("deadline")

            def _verify_current(self):
                self._check_deadline()
                if self._execution_close_attempted:
                    raise ValueError("execution_leases_already_closed")
                _require_clean_after_install(source_seal, finder=source_finder)
                source_seal.source_lease.verify_current()
                dependency_seal.verify_current()
                runtime_seal.verify_current()
                anchor_paths.verify_current()
                receipt_paths.verify_current()
                descriptor_raw = anchor_paths.read_file(
                    ntpath.join(
                        program_data,
                        *anchor_ns["FIXED_PROGRAMDATA_RELATIVE"].parts,
                        anchor_ns["FIXED_DESCRIPTOR_NAME"],
                    ),
                    max_bytes=anchor_ns["_MAX_DESCRIPTOR_BYTES"],
                )
                if hashlib.sha256(descriptor_raw).hexdigest() != descriptor.descriptor_sha256:
                    raise ValueError("deployment_changed")
                _require_clean_after_install(source_seal, finder=source_finder)
                self._check_deadline()

            def monotonic_ns(self):
                return time.monotonic_ns()

            def verify_deployment(self, deployment):
                if (
                    self._closed
                    or self._execution_close_attempted
                    or dict(deployment) != expected_deployment
                ):
                    raise ValueError("deployment_binding_mismatch")
                self._verify_current()

            def close_execution(self):
                if self._closed or self._execution_close_attempted:
                    raise ValueError("execution_close_reentry")
                self._execution_close_attempted = True
                errors = []
                if source_finder._runtime_closure is runtime_seal:
                    try:
                        source_finder.detach_runtime_closure(runtime_seal)
                    except Exception:
                        errors.append("runtime_closure_detach_failed")
                if source_finder._dependency_finder is not None:
                    dependency_finder_value = source_finder._dependency_finder
                    try:
                        source_finder.detach_dependency_finder(dependency_finder_value)
                    except Exception:
                        errors.append("dependency_finder_detach_failed")
                for name, close in (
                    ("runtime_closure_close_failed", runtime_seal.close),
                    ("dependency_seal_close_failed", dependency_seal.close),
                    ("source_seal_close_failed", source_seal.close),
                    ("anchor_paths_close_failed", anchor_paths.close),
                ):
                    try:
                        close()
                    except Exception:
                        errors.append(name)
                self._execution_close_errors = tuple(errors)
                self._check_deadline()
                if errors:
                    raise ValueError("deployment_execution_lease_close_failed")

            def persist_fixed_receipt(self, request_id, raw):
                if (
                    self._closed
                    or self._creation_started
                    or not self._execution_close_attempted
                    or request_id != parsed_binding.request_id
                    or type(raw) is not bytes
                    or not raw
                    or len(raw) > 64 * 1024
                ):
                    raise ValueError("receipt_write_binding_invalid")
                self._creation_started = True
                self._check_deadline()
                if dict(parsed_binding.deployment) != expected_deployment:
                    raise ValueError("deployment_binding_mismatch")
                receipt_paths.verify_current()
                created_path = receipt_paths.create_new_receipt(
                    receipt_root, parsed_binding.request_id, raw
                )
                target_path = ntpath.join(receipt_root, parsed_binding.request_id + ".json")
                if ntpath.normcase(ntpath.normpath(created_path)) != ntpath.normcase(
                    ntpath.normpath(target_path)
                ):
                    raise ValueError("receipt_target_mismatch")
                self._check_deadline()
                receipt_paths.add_paths((target_path,))
                readback = receipt_paths.read_file(target_path, max_bytes=64 * 1024)
                if readback != raw:
                    raise ValueError("receipt_readback_mismatch")
                self._check_deadline()
                self._created = True

            def write_supervisor_output(self, binding_value, output):
                if (
                    self._closed
                    or self._output_started
                    or not self._execution_close_attempted
                ):
                    raise ValueError("receipt_output_reentry")
                if (
                    type(binding_value) is not type(parsed_binding)
                    or binding_value != parsed_binding
                ):
                    raise ValueError("receipt_output_binding_mismatch")
                self._output_started = True
                self._check_deadline()
                receipt_paths.verify_current()
                self._check_deadline()
                nonce = parsed_binding.receipt_output_channel["nonce"]
                server_pid = parsed_binding.receipt_output_channel["server_pid"]
                frame_body = role_module.encode_receipt_writer_frame(
                    dict(output), request_id=parsed_binding.request_id, nonce=nonce
                )
                if type(frame_body) is not bytes or not frame_body or len(frame_body) > 64 * 1024:
                    raise ValueError("receipt_output_frame_size_invalid")
                frame = len(frame_body).to_bytes(4, "big", signed=False) + frame_body
                output_channel_module._write_bounded_frame(
                    frame,
                    nonce=nonce,
                    expected_server_pid=server_pid,
                    deadline_monotonic_ns=parsed_binding.deadline_monotonic_ns,
                )

            def close(self):
                if self._closed:
                    return
                self._closed = True
                errors = []
                try:
                    receipt_paths.close()
                except BaseException:
                    errors.append("receipt_path_close_failed")
                try:
                    source_finder._end_fixed_role_module("receipt_writer", role_module)
                except BaseException:
                    errors.append("receipt_role_unload_failed")
                if errors:
                    raise ValueError(";".join(errors))

        runtime = _FixedReceiptWriterRuntime()
        result = role_module.main(raw_binding, runtime)
        if type(result) is not int or result not in {0, 2}:
            raise ValueError("receipt_writer_result_invalid")
        return result
    finally:
        if runtime is not None:
            runtime.close()
        else:
            cleanup_error = None
            if receipt_paths is not None:
                try:
                    receipt_paths.close()
                except BaseException:
                    cleanup_error = True
            if role_module is not None:
                try:
                    source_finder._end_fixed_role_module("receipt_writer", role_module)
                except BaseException:
                    cleanup_error = True
            if cleanup_error:
                raise ValueError("receipt_writer_cleanup_failed")


def _readonly_bootstrap_detach_runtime_closure(source_finder, expected_seal):
    active = source_finder._runtime_closure
    if active is None:
        return
    if active is not expected_seal:
        raise ValueError("runtime_closure_replaced")
    source_finder.detach_runtime_closure(expected_seal)


def _readonly_bootstrap_detach_dependency_finder(source_finder, expected_finder):
    active = source_finder._dependency_finder
    if active is None:
        return
    if active is not expected_finder:
        raise ValueError("dependency_finder_replaced")
    source_finder.detach_dependency_finder(expected_finder)


def _readonly_bootstrap_run():
    stage = "binding"
    anchor_paths = None
    source_seal = None
    source_finder = None
    dependency_seal = None
    dependency_finder = None
    runtime_seal = None
    support_modules = None
    result = 78
    try:
        binding, env = _readonly_bootstrap_binding()
        if len(sys.argv) != 1:
            raise ValueError("argv")
        script_path = ntpath.normcase(ntpath.normpath(os.path.abspath(__file__)))
        bootstrap_relative = "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"
        source_root = ntpath.dirname(ntpath.dirname(script_path))
        if not ntpath.isabs(source_root) or ":" not in source_root[:3]:
            raise ValueError("source_root")
        if script_path != ntpath.normcase(ntpath.normpath(ntpath.join(source_root, bootstrap_relative))):
            raise ValueError("bootstrap_path")
        if ntpath.normcase(ntpath.normpath(env["path"])) != ntpath.normcase(
            ntpath.normpath(ntpath.dirname(sys.executable))
        ):
            raise ValueError("process_path")
        if not env["systemroot"] or env["systemroot"] != env["windir"]:
            raise ValueError("system_root")
        if type(sys.argv[0]) is not str or ntpath.normcase(ntpath.normpath(os.path.abspath(sys.argv[0]))) != script_path:
            raise ValueError("argv")
        if time.monotonic_ns() >= binding["deadline_monotonic_ns"]:
            raise ValueError("deadline")

        stage = "embedded_source"
        sources, support_sha256s = _readonly_bootstrap_support()
        anchor_ns = _readonly_bootstrap_exec_support(
            sources,
            "scripts/ctp_i13_i15_guardian_deployment_anchor.py",
            "_i13_fixed_deployment_anchor",
        )
        parent_ns = _readonly_bootstrap_exec_support(
            sources,
            "scripts/ctp_i13_i15_parent_launcher.py",
            "_i13_fixed_parent_launcher",
        )
        runtime_ns = _readonly_bootstrap_exec_support(
            sources,
            "scripts/ctp_i13_i15_runtime_closure.py",
            "_i13_fixed_runtime_closure",
        )
        stage = "deployment_descriptor"
        program_data = anchor_ns["_program_data_path"]()
        fixed_root = ntpath.join(program_data, *anchor_ns["FIXED_PROGRAMDATA_RELATIVE"].parts)
        descriptor_path = ntpath.join(fixed_root, anchor_ns["FIXED_DESCRIPTOR_NAME"])
        dependency_path = ntpath.join(fixed_root, anchor_ns["FIXED_DEPENDENCY_MANIFEST_NAME"])
        runtime_path = ntpath.join(fixed_root, anchor_ns["FIXED_RUNTIME_MANIFEST_NAME"])
        integrity_sids = frozenset({anchor_ns["_SYSTEM_SID"], anchor_ns["_ADMINISTRATORS_SID"]})
        anchor_paths = anchor_ns["_ProtectedWindowsPaths"](integrity_sids)
        anchor_paths.add_paths((descriptor_path, dependency_path, runtime_path))
        descriptor_raw = anchor_paths.read_file(
            descriptor_path, max_bytes=anchor_ns["_MAX_DESCRIPTOR_BYTES"]
        )
        descriptor = anchor_ns["_parse_deployment_descriptor"](
            descriptor_raw,
            expected_sha256=anchor_ns["GUARDIAN_DEPLOYMENT_DESCRIPTOR_SHA256"],
            expected_worker_dependency_sha256=anchor_ns["WORKER_DEPENDENCY_MANIFEST_SHA256"],
            expected_runtime_manifest_sha256=anchor_ns["RUNTIME_MANIFEST_SHA256"],
        )
        anchor_paths.verify_current()
        if (
            descriptor.descriptor_sha256 != binding["deployment_descriptor_sha256"]
            or descriptor.source_manifest_sha256 != binding["source_manifest_sha256"]
            or descriptor.worker_dependency_manifest_sha256 != binding["dependency_manifest_sha256"]
            or descriptor.runtime_manifest_sha256 != binding["runtime_manifest_sha256"]
            or descriptor.python_sha256 != binding["python_sha256"]
            or descriptor.worker_sha256 != binding["worker_sha256"]
            or ntpath.normcase(descriptor.source_root) != ntpath.normcase(source_root)
            or _readonly_bootstrap_token_sid()
            != (
                descriptor.service_sid
                if binding["_readonly_role"] == "receipt_writer"
                else descriptor.client_sid
            )
        ):
            raise ValueError("deployment_binding")

        stage = "parent_descriptor"
        parent_descriptor = parent_ns["ExternallyPinnedDescriptor"](
            raw_bytes=descriptor.parent_trust_raw,
            sha256=descriptor.parent_trust_sha256,
            external_anchor_id="ctp-i13-i15-guardian-deployment-v2",
        )
        parent_facts = parent_ns["parse_trust_descriptor"](parent_descriptor)
        if (
            ntpath.normcase(parent_facts.source_root) != ntpath.normcase(source_root)
            or ntpath.normcase(parent_facts.python_executable)
            != ntpath.normcase(descriptor.python_executable)
            or parent_facts.python_sha256 != descriptor.python_sha256
            or parent_facts.python_version != descriptor.python_version
            or parent_facts.python_architecture != descriptor.python_architecture
            or parent_facts.candidates["i13_md"]["manifest_sha256"]
            != descriptor.source_manifest_sha256
            or parent_facts.candidates["i13_md"]["pin_sha256"] != binding["i13_pin_sha256"]
            or parent_facts.candidates["i15_td"]["pin_sha256"] != binding["i15_pin_sha256"]
        ):
            raise ValueError("parent_binding")
        actual_version = ".".join(str(part) for part in sys.version_info[:3])
        actual_architecture = _readonly_bootstrap_architecture()
        plan = parent_ns["preflight_parent_launch"](
            parent_descriptor,
            candidate="i13_md",
            captured_launcher_bytes=sources["scripts/ctp_i13_i15_parent_launcher.py"],
            actual_executable=os.path.abspath(sys.executable),
            actual_version=actual_version,
            actual_architecture=actual_architecture,
            actual_sys_path=tuple(sys.path),
        )
        if (
            ntpath.normcase(plan.source_root) != ntpath.normcase(source_root)
            or plan.manifest_sha256 != binding["source_manifest_sha256"]
            or plan.python_sha256 != binding["python_sha256"]
        ):
            raise ValueError("parent_plan")
        expected_pycache_prefix = ntpath.join(
            parent_facts.python_home, "disabled-bytecode-cache"
        )
        if (
            not ntpath.isabs(expected_pycache_prefix)
            or ntpath.normcase(ntpath.normpath(sys.pycache_prefix))
            != ntpath.normcase(ntpath.normpath(expected_pycache_prefix))
            or os.path.exists(expected_pycache_prefix)
        ):
            raise ValueError("pycache_prefix_binding")

        stage = "source_seal"
        source_seal = seal_candidate_source_tree(
            "i13_md",
            source_root,
            expected_manifest_sha256=plan.manifest_sha256,
            expected_pin_sha256s=dict(plan.pin_source_sha256s),
            stdlib_paths=plan.stdlib_paths,
        )
        if (
            source_seal.files.get(bootstrap_relative) != binding["bootstrap_sha256"]
            or source_seal.files.get("scripts/ctp_i13_i15_readonly_preflight_worker.py")
            != binding["worker_sha256"]
            or source_seal.source_lease.read_source(
                bootstrap_relative, expected_sha256=binding["bootstrap_sha256"]
            )
            != open(__file__, "rb").read()
        ):
            raise ValueError("bootstrap_source_binding")
        if binding["_readonly_role"] == "receipt_writer":
            role_source_digests = {
                "scripts/ctp_i13_i15_readonly_request_coordinator.py": binding[
                    "_deployment"
                ]["coordinator_sha256"],
                "scripts/ctp_i13_i15_readonly_receipt_writer.py": binding[
                    "_deployment"
                ]["receipt_writer_sha256"],
                "scripts/ctp_i13_i15_readonly_token_bootstrap.py": binding[
                    "_deployment"
                ]["token_bootstrap_sha256"],
            }
            if any(source_seal.files.get(path) != digest for path, digest in role_source_digests.items()):
                raise ValueError("receipt_writer_role_source_binding")
        source_finder = install_sealed_source_finder(source_seal)

        stage = "dependency_seal"
        from backtrader_runtime import ctp_i13_worker_dependency_seal as dependency_api

        dependency_raw = dependency_api.read_fixed_worker_dependency_manifest(
            lambda: anchor_paths.read_file(dependency_path, max_bytes=1024 * 1024),
            expected_sha256=binding["dependency_manifest_sha256"],
        )
        dependency_root = ntpath.join(
            ntpath.dirname(ntpath.dirname(os.path.abspath(sys.executable))),
            "Lib",
            "site-packages",
        )
        if ntpath.normcase(dependency_root) != ntpath.normcase(
            ntpath.join(parent_facts.venv_root, "Lib", "site-packages")
        ):
            raise ValueError("dependency_root")
        dependency_seal = dependency_api.seal_worker_dependencies(
            dependency_raw,
            expected_manifest_sha256=binding["dependency_manifest_sha256"],
            python_executable=sys.executable,
            retain_paths=lambda files, directories: _readonly_bootstrap_retain_paths(
                anchor_ns, dependency_root, files, directories
            ),
        )
        if dependency_seal.manifest_sha256 != binding["dependency_manifest_sha256"]:
            raise ValueError("dependency_manifest_binding")
        dependency_finder = dependency_api.install_worker_dependency_finder(dependency_seal)

        stage = "runtime_seal"
        runtime_raw = anchor_paths.read_file(runtime_path, max_bytes=4 * 1024 * 1024)
        if hashlib.sha256(runtime_raw).hexdigest() != binding["runtime_manifest_sha256"]:
            raise ValueError("runtime_manifest_digest")
        descriptor_facts = {
            "python_executable": parent_facts.python_executable,
            "python_sha256": parent_facts.python_sha256,
            "python_version": parent_facts.python_version,
            "python_architecture": parent_facts.python_architecture,
            "python_home": parent_facts.python_home,
            "venv_root": parent_facts.venv_root,
            "pyvenv_cfg_sha256": parent_facts.pyvenv_cfg_sha256,
            "stdlib_paths": parent_facts.stdlib_paths,
        }
        process_facts = runtime_ns["capture_runtime_process_facts"]()
        runtime_seal = runtime_ns["seal_runtime_closure"](
            runtime_raw,
            expected_manifest_sha256=binding["runtime_manifest_sha256"],
            descriptor_facts=descriptor_facts,
            process_facts=process_facts,
            dependency_seal=dependency_seal,
            retain_paths=lambda root_kind, files, directories: _readonly_bootstrap_retain_paths(
                anchor_ns,
                parent_facts.python_home if root_kind == "base" else parent_facts.venv_root,
                files,
                directories,
            ),
        )
        source_finder.attach_runtime_closure(runtime_seal)
        source_seal.source_lease.verify_current()
        dependency_seal.verify_current()
        runtime_seal.verify_current()
        anchor_paths.verify_current()
        if time.monotonic_ns() >= binding["deadline_monotonic_ns"]:
            raise ValueError("deadline")

        stage = "embedded_process_support"
        support_modules = _readonly_bootstrap_exec_support_modules(
            sources, support_sha256s, source_finder
        )
        if binding["_readonly_role"] == "receipt_writer":
            stage = "receipt_writer"
            result = _readonly_bootstrap_run_receipt_writer(
                binding,
                raw_binding=binding["_readonly_role_binding"],
                anchor_ns=anchor_ns,
                descriptor=descriptor,
                parent_facts=parent_facts,
                source_seal=source_seal,
                source_finder=source_finder,
                dependency_seal=dependency_seal,
                runtime_seal=runtime_seal,
                anchor_paths=anchor_paths,
                support_modules=support_modules,
            )
        elif binding["_readonly_role"] == "worker":
            output_channel_module = support_modules[
                "scripts/ctp_i13_i15_worker_output_channel.py"
            ]

            stage = "worker_source"
            worker_relative = "scripts/ctp_i13_i15_readonly_preflight_worker.py"
            worker_source = source_seal.source_lease.read_source(
                worker_relative, expected_sha256=binding["worker_sha256"]
            )
            worker_namespace = {
                "__name__": "_i13_fixed_readonly_preflight_worker",
                "__file__": ntpath.join(source_root, *worker_relative.split("/")),
            }
            exec(compile(worker_source, worker_namespace["__file__"], "exec", dont_inherit=True), worker_namespace)
            stage = "worker_run"
            class _BoundedWorkerOutput:
                __slots__ = ("_data",)

                def __init__(self):
                    self._data = bytearray()

                def write(self, text):
                    if type(text) is not str:
                        raise TypeError("worker_stdout_type")
                    encoded = text.encode("ascii", "strict")
                    if len(self._data) + len(encoded) > _READONLY_BOOTSTRAP_MAX_WORKER_OUTPUT_BYTES:
                        raise ValueError("worker_stdout_limit")
                    self._data.extend(encoded)
                    return len(text)

                def flush(self):
                    return None

                @property
                def encoding(self):
                    return "ascii"

                @property
                def errors(self):
                    return "strict"

                def isatty(self):
                    return False

                def writable(self):
                    return True

                def getvalue(self):
                    return bytes(self._data)

            worker_output_buffer = _BoundedWorkerOutput()
            original_stdout = sys.stdout
            sys.stdout = worker_output_buffer
            try:
                worker_result = worker_namespace["main"]()
                if sys.stdout is not worker_output_buffer:
                    raise ValueError("worker_stdout_replaced")
                worker_output_raw = worker_output_buffer.getvalue()
            finally:
                sys.stdout = original_stdout
            if type(worker_result) is not int or worker_result != 0:
                raise ValueError("worker_result")
            stage = "worker_output_channel"
            output_channel_module.write_worker_output_frame(
                worker_output_raw,
                request_id=binding["request_id"],
                nonce=binding["worker_output"]["nonce"],
                expected_server_pid=binding["worker_output"]["server_pid"],
                deadline_monotonic_ns=binding["deadline_monotonic_ns"],
            )
            result = worker_result
        else:
            raise ValueError("readonly_role_runtime_unavailable")
    except BaseException:
        result = _readonly_bootstrap_fail(stage)
    finally:
        cleanup_failed = False
        if runtime_seal is not None and source_finder is not None:
            try:
                _readonly_bootstrap_detach_runtime_closure(source_finder, runtime_seal)
            except BaseException:
                cleanup_failed = True
        if runtime_seal is not None:
            try:
                runtime_seal.close()
            except BaseException:
                cleanup_failed = True
        if dependency_finder is not None and source_finder is not None:
            try:
                _readonly_bootstrap_detach_dependency_finder(
                    source_finder, dependency_finder
                )
            except BaseException:
                cleanup_failed = True
        if dependency_seal is not None:
            try:
                dependency_seal.close()
            except BaseException:
                cleanup_failed = True
        if source_seal is not None:
            try:
                source_seal.close()
            except BaseException:
                cleanup_failed = True
        if anchor_paths is not None:
            try:
                anchor_paths.close()
            except BaseException:
                cleanup_failed = True
        if cleanup_failed:
            result = _readonly_bootstrap_fail("lease_cleanup")
    return result


raise SystemExit(_readonly_bootstrap_run())
'''.lstrip().encode("ascii")


def build_readonly_preflight_bootstrap(source_root: Union[Path, str]) -> bytes:
    """Assemble the one fixed direct-execution child bootstrap deterministically."""

    root = _checked_absolute_directory(source_root)
    sealer_path = PurePosixPath("scripts/ctp_i13_i15_sealed_import.py")
    sealer = _read_stable_source(root, sealer_path.as_posix())
    sources = []
    source_bytes = []
    for relative in BOOTSTRAP_EMBEDDED_SUPPORT_PATHS:
        source = _read_stable_source(root, relative.as_posix())
        if len(source) > _MAX_EMBEDDED_SOURCE_BYTES:
            raise SourceManifestCandidateError("bootstrap_embedded_source_size_invalid")
        try:
            source.decode("utf-8", "strict")
            compile(source, "<fixed-bootstrap-support>", "exec", dont_inherit=True)
        except (UnicodeError, SyntaxError, ValueError):
            raise SourceManifestCandidateError("bootstrap_embedded_source_invalid") from None
        sources.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(source).hexdigest(),
                "size": len(source),
            }
        )
        source_bytes.append(source)
    header = json.dumps(
        {"schema": 2, "files": sources},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    if not 0 < len(header) <= 64 * 1024:
        raise SourceManifestCandidateError("bootstrap_support_header_invalid")
    payload = len(header).to_bytes(4, "big", signed=False) + header + b"".join(source_bytes)
    if len(payload) > _MAX_EMBEDDED_SOURCE_BUNDLE_BYTES:
        raise SourceManifestCandidateError("bootstrap_support_bundle_too_large")
    compressed = zlib.compress(payload, level=9)
    support_b85 = base64.b85encode(compressed).decode("ascii")
    support_lines = "\n".join(
        "    " + repr(support_b85[index : index + 100])
        for index in range(0, len(support_b85), 100)
    )
    support_sha256 = hashlib.sha256(payload).hexdigest()
    runner = _bootstrap_runner_source().decode("ascii").replace(
        '"__SUPPORT_B85__"', "(\n" + support_lines + "\n)"
    ).replace("__SUPPORT_SHA256__", support_sha256)
    artifact = sealer.rstrip() + b"\n\n" + runner.encode("ascii")
    if len(artifact) > _MAX_BOOTSTRAP_BYTES:
        raise SourceManifestCandidateError("bootstrap_artifact_size_invalid")
    try:
        compile(artifact, "<fixed-readonly-preflight-bootstrap>", "exec", dont_inherit=True)
    except (SyntaxError, ValueError):
        raise SourceManifestCandidateError("bootstrap_artifact_invalid") from None
    return artifact


def write_readonly_preflight_bootstrap_candidate(
    source_root: Union[Path, str],
) -> tuple[Path, bytes]:
    """Atomically write only the exact fixed child bootstrap candidate path."""

    relative = Path(*FIXED_READONLY_BOOTSTRAP_PATH.parts)
    if relative != BOOTSTRAP_OUTPUT or relative.is_absolute():
        raise SourceManifestCandidateError("bootstrap_output_path_invalid")
    root = _checked_absolute_directory(source_root)
    output = root.joinpath(*relative.parts)
    try:
        parent_stat = os.lstat(output.parent)
    except OSError as exc:
        raise SourceManifestCandidateError("bootstrap_output_directory_invalid") from exc
    if _is_reparse_point(parent_stat) or not stat.S_ISDIR(parent_stat.st_mode):
        raise SourceManifestCandidateError("bootstrap_output_directory_invalid")
    try:
        current_stat = os.lstat(output)
    except FileNotFoundError:
        current_stat = None
    except OSError as exc:
        raise SourceManifestCandidateError("bootstrap_output_unavailable") from exc
    if current_stat is not None and (
        _is_reparse_point(current_stat) or not stat.S_ISREG(current_stat.st_mode)
    ):
        raise SourceManifestCandidateError("bootstrap_output_invalid")
    content = build_readonly_preflight_bootstrap(root)
    try:
        import tempfile

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".ctp_i13_readonly_bootstrap.", suffix=".tmp", dir=str(output.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_stat = os.lstat(temporary)
            if _is_reparse_point(temporary_stat) or not stat.S_ISREG(temporary_stat.st_mode):
                raise SourceManifestCandidateError("bootstrap_output_invalid")
            os.replace(temporary, output)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    except SourceManifestCandidateError:
        raise
    except OSError as exc:
        raise SourceManifestCandidateError("bootstrap_output_unavailable") from exc
    return output, content


def build_i13_source_manifest(source_root: Union[Path, str]) -> bytes:
    """Render exact loader-schema bytes; these bytes are only a candidate."""

    root = _checked_absolute_directory(source_root)
    files: Mapping[str, str] = {
        relative: hashlib.sha256(_read_stable_source(root, relative)).hexdigest()
        for relative in discover_i13_source_files(root)
    }
    value = {"schema": SCHEMA, "source_files": files}
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def write_current_dirty_tree_candidate(
    source_root: Union[Path, str],
) -> tuple[Path, bytes]:
    """Write the labelled candidate artifact without touching runtime pins."""

    # Keep the actual destination fixed in this function. ``CANDIDATE_OUTPUT``
    # remains a public descriptive constant, but callers can reassign module
    # globals, so it must be checked before it is used for any filesystem path.
    fixed_relative_parts = (
        "artifacts",
        "ctp_i13_source_manifest.current_dirty_tree_candidate.json",
    )
    fixed_relative_path = Path(*fixed_relative_parts)
    if (
        fixed_relative_path != CANDIDATE_OUTPUT
        or CANDIDATE_OUTPUT.is_absolute()
        or CANDIDATE_OUTPUT.parts != fixed_relative_parts
    ):
        raise SourceManifestCandidateError("candidate_output_path_invalid")

    root = _checked_absolute_directory(source_root)
    output = Path(
        os.path.normcase(os.path.abspath(os.fspath(root.joinpath(*CANDIDATE_OUTPUT.parts))))
    )
    expected_output = Path(
        os.path.normcase(os.path.abspath(os.fspath(root.joinpath(*fixed_relative_parts))))
    )
    if output != expected_output:
        raise SourceManifestCandidateError("candidate_output_path_invalid")

    try:
        root_stat = os.lstat(root)
        if _is_reparse_point(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
            raise SourceManifestCandidateError("candidate_source_root_invalid")
        try:
            parent_stat = os.lstat(output.parent)
        except FileNotFoundError:
            os.mkdir(output.parent)
            parent_stat = os.lstat(output.parent)
        if _is_reparse_point(parent_stat) or not stat.S_ISDIR(parent_stat.st_mode):
            raise SourceManifestCandidateError("candidate_output_directory_invalid")

        content = build_i13_source_manifest(root)
        try:
            output_stat = os.lstat(output)
        except FileNotFoundError:
            output_stat = None
        if output_stat is not None:
            if _is_reparse_point(output_stat) or not stat.S_ISREG(output_stat.st_mode):
                raise SourceManifestCandidateError("candidate_output_invalid")
            if output.read_bytes() != content:
                raise SourceManifestCandidateError("candidate_output_already_exists")
        else:
            with output.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
    except SourceManifestCandidateError:
        raise
    except OSError as exc:
        raise SourceManifestCandidateError("candidate_output_unavailable") from exc
    return output, content


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write the deterministic fixed child-bootstrap candidate and a non-authorizing "
            "current-dirty-tree I13 source manifest under artifacts/. Runtime manifests and "
            "code pins are untouched."
        )
    )
    parser.add_argument(
        "--write-current-dirty-tree-candidate",
        action="store_true",
        help="write the explicitly labelled candidate artifact",
    )
    arguments = parser.parse_args()
    if not arguments.write_current_dirty_tree_candidate:
        parser.error("--write-current-dirty-tree-candidate is required")
    try:
        bootstrap_path, bootstrap_content = write_readonly_preflight_bootstrap_candidate(ROOT)
        output, content = write_current_dirty_tree_candidate(ROOT)
    except SourceManifestCandidateError as exc:
        parser.error(str(exc))
    source_file_count = len(json.loads(content)["source_files"])
    print(
        f"candidate_manifest_sha256={hashlib.sha256(content).hexdigest()} "
        f"source_files={source_file_count} path={output} "
        f"bootstrap_sha256={hashlib.sha256(bootstrap_content).hexdigest()} "
        f"bootstrap_path={bootstrap_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
