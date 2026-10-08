"""Draft guarded Root QA harness for the frozen Binance TH01 forceOrders R9 focus.

This script runs only the designated source-fake test in a fresh isolated QA
process. It does not invoke the account runner or any real worker/provider path.
Root review is required before execution.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from uuid import uuid4


ROOT = Path("D:/source_code/backtrader").resolve()
PYTHON = Path("D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe")
SITE = Path("D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages")
RESULT = ROOT / ".codex-tmp/binance_force_orders_transport_r9_root_source_qa_20261009.json"
QA = Path("D:/bwqf" + uuid4().hex[:8])

PINS = {
    "examples/000_live_certification/binance_penetration/_certification/th01_force_orders_transport_r9.py": {
        "bytes": 73002,
        "sha256": "c937a07671a6df7991fb29e131d895c0eca21644d28140542fab7c8b0db1b944",
    },
    "tests/unit/live_certification/test_binance_th01_force_orders_transport_r9.py": {
        "bytes": 40454,
        "sha256": "90a2e9acd17ddcf2996ffb99d300c706d415afab420a940237e441f70375183f",
    },
    "scripts/iteration41_binance_th01_root_account_window_call_r1.py": {
        "bytes": 132886,
        "sha256": "ba0360ecc5ed99b37196e3d077e25a78cd771facec8e224ab1371635cf9be021",
    },
    "examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py": {
        "bytes": 92566,
        "sha256": "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f",
    },
    "examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py": {
        "bytes": 62664,
        "sha256": "4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63",
    },
    "scripts/iteration41_binance_th01_account_window_candidate_r2.py": {
        "bytes": 11391,
        "sha256": "698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6",
    },
    # R8 remains a historical HOLD snapshot; the R9 harness must not replace it.
    "examples/000_live_certification/binance_penetration/_certification/th01_force_orders_transport_r8.py": {
        "bytes": 72884,
        "sha256": "e59d594578d7594932fcdeda43e05175b95922c42fca2d7783350e598fbbafee",
    },
    "tests/unit/live_certification/test_binance_th01_force_orders_transport_r8.py": {
        "bytes": 34739,
        "sha256": "b8f6d1900a8b2f1e8372e0193bb79e835fe28624edb82dab7451ad3ef71023b6",
    },
}

R9_EXTENSION = "examples/000_live_certification/binance_penetration/_certification/th01_force_orders_transport_r9.py"
R9_TEST = "tests/unit/live_certification/test_binance_th01_force_orders_transport_r9.py"
ROOT_WRAPPER = "scripts/iteration41_binance_th01_root_account_window_call_r1.py"
OWNER = "examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py"
CANDIDATE = "examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py"
DRIVER = "scripts/iteration41_binance_th01_account_window_candidate_r2.py"
R9_SELF_PIN = "baa9a92fe71258528291a4748af0b811cdc0cece40f3ac80859c6a54d1801f63"
EXPECTED_GUARD_SELFCHECKS = [
    "windows_chr92_path_normalization",
    "private_env_config_capture_and_opaque_binary_paths",
    "native_import_path",
    "SDK_import",
    "network_connect_and_dns",
    "ctypes_loader",
    "subprocess_and_process_start",
    "multiprocessing_and_WinAPI_Pipe_creation",
]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(*arguments: str) -> bytes:
    return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, check=True).stdout


def verify_pin(relative: str, expected: dict[str, object]) -> dict[str, object]:
    path = ROOT / relative
    info = path.lstat()
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
    ):
        raise RuntimeError(f"source_shape_invalid:{relative}")
    raw = path.read_bytes()
    observed = {"bytes": len(raw), "sha256": sha256(raw)}
    if observed != expected:
        raise RuntimeError(f"source_pin_mismatch:{relative}")
    return {"path": relative, **observed}


def run_git_preflight() -> str:
    if git("branch", "--show-current").strip() != b"dev":
        raise RuntimeError("expected_dev_branch")
    if git("diff", "--cached", "--name-only", "-z"):
        raise RuntimeError("staging_index_not_empty")
    return git("rev-parse", "HEAD").strip().decode("ascii")


if Path.cwd().resolve() != ROOT:
    raise RuntimeError("unexpected_repository_root")
if not PYTHON.is_file() or not SITE.is_dir():
    raise RuntimeError("designated_qa_venv_unavailable")
if RESULT.exists():
    raise RuntimeError("result_path_already_exists")

parent = run_git_preflight()
pre_pins = {relative: verify_pin(relative, expected) for relative, expected in PINS.items()}

QA.mkdir(exist_ok=False)
(QA / "pytest.ini").write_text("[pytest]\n", encoding="ascii")
arguments = [
    str(ROOT / R9_TEST),
    "-q",
    "--tb=short",
    "-c",
    str(QA / "pytest.ini"),
    "--confcutdir=" + str(ROOT / "tests/unit/live_certification"),
    "-p",
    "no:asyncio",
    "-p",
    "no:cacheprovider",
    "--basetemp=" + str(QA / "pytest-basetemp"),
]

runner = r"""import ctypes, ctypes.util, dataclasses, decimal, hashlib, hmac
import http.client, importlib, importlib.util, json, multiprocessing
import multiprocessing.connection, multiprocessing.context, multiprocessing.process
import os, pathlib, re, socket, sqlite3, ssl, stat, subprocess, sys, time, types, _winapi
import urllib.parse, uuid

assert os.name == "nt", "root_source_qa_requires_windows"
sys.path[:0] = [SOURCE_ROOT, SITE_ROOT]
import pytest
import colorama

def norm_path(value):
    if isinstance(value, (bytes, bytearray)):
        value = os.fsdecode(value)
    elif isinstance(value, os.PathLike):
        value = os.fspath(value)
    return str(value).replace(chr(92), "/").casefold()

NATIVE_SUFFIXES = (".dll", ".exe", ".pyd", ".so", ".dylib", ".bin")
SDK_ROOTS = {
    "bt_api", "bt_api_py", "binance", "binance_sdk", "binance_common",
    "python_binance", "ccxt", "xtquant",
}
FORBIDDEN_AUDIT_EVENTS = {
    "subprocess.Popen", "os.system", "os.startfile", "os.posix_spawn",
    "os.spawn", "os.fork", "os.forkpty", "socket.connect",
    "socket.getaddrinfo", "socket.gethostbyname", "ctypes.dlopen",
    "ctypes.dlsym", "_winapi.CreateProcess", "_winapi.CreatePipe",
    "_winapi.CreateNamedPipe", "_winapi.ConnectNamedPipe",
}
BLOCKED_ATTEMPTS = []
SELF_CHECK = True

class GuardViolation(AssertionError):
    pass

def deny(label, *args, **kwargs):
    if not SELF_CHECK:
        BLOCKED_ATTEMPTS.append(label)
    raise GuardViolation("source_qa_guard_denied:" + label)

def denied_path(value):
    value = norm_path(value)
    leaf = value.rsplit("/", 1)[-1]
    suffix = next((item for item in NATIVE_SUFFIXES if value.endswith(item)), "")
    base = norm_path(sys.base_prefix).rstrip("/") + "/"
    always_blocked_binary = suffix in {".dll", ".exe", ".bin"}
    external_native = suffix in {".pyd", ".so", ".dylib"} and not value.startswith(base)
    return (
        leaf == ".env"
        or leaf == "config.yaml"
        or "private-capture" in value
        or "private_capture" in value
        or "/opaque/" in ("/" + value.strip("/") + "/")
        or "/external-software/" in ("/" + value.strip("/") + "/")
        or always_blocked_binary
        or external_native
    )

def audit(event, args):
    if event in FORBIDDEN_AUDIT_EVENTS:
        deny("audit:" + event)
    if event == "import" and args:
        module_name = args[0]
        if isinstance(module_name, str):
            root_name = module_name.partition(".")[0].casefold()
            if root_name in SDK_ROOTS:
                deny("sdk_import:" + root_name)
        if len(args) > 1 and isinstance(args[1], (str, bytes, os.PathLike)):
            if denied_path(args[1]):
                deny("native_or_opaque_import")
    if event in {"open", "os.open"} and args:
        value = args[0]
        if isinstance(value, (str, bytes, os.PathLike)) and denied_path(value):
            deny("private_or_opaque_file_open")

def expect_denied(label, action):
    before = len(BLOCKED_ATTEMPTS)
    try:
        action()
    except GuardViolation:
        assert len(BLOCKED_ATTEMPTS) == before, "guard_selfcheck_recorded_as_candidate_attempt"
        return
    raise AssertionError("guard_selfcheck_failed:" + label)

expected_paths = {
    "test": EXPECTED_PATHS["test"],
    "extension": EXPECTED_PATHS["extension"],
    "wrapper": EXPECTED_PATHS["wrapper"],
    "owner": EXPECTED_PATHS["owner"],
    "candidate": EXPECTED_PATHS["candidate"],
    "driver": EXPECTED_PATHS["driver"],
}
assert norm_path("D:" + chr(92) + "private" + chr(92) + ".env") == "d:/private/.env"

# Load stdlib TLS, HTTP, multiprocessing and native stdlib dependencies before
# replacing socket/native entry points. This avoids cold ssl importing after a
# fake socket class/function has been installed.
assert "test_binance_th01_force_orders_transport_r9" not in sys.modules
assert EXPECTED_EXTENSION_MODULE not in sys.modules
assert not any(name.startswith("bt_api") for name in sys.modules)

def deny_process_or_pipe(*args, **kwargs):
    return deny("real_process_or_pipe", *args, **kwargs)

ctypes.WinDLL = lambda *args, **kwargs: deny("ctypes.WinDLL", *args, **kwargs)
ctypes.CDLL = lambda *args, **kwargs: deny("ctypes.CDLL", *args, **kwargs)
ctypes.PyDLL = lambda *args, **kwargs: deny("ctypes.PyDLL", *args, **kwargs)
ctypes.util.find_library = lambda *args, **kwargs: deny("ctypes.find_library", *args, **kwargs)
socket.socket = lambda *args, **kwargs: deny("socket.socket", *args, **kwargs)
socket.create_connection = lambda *args, **kwargs: deny("socket.create_connection", *args, **kwargs)
socket.getaddrinfo = lambda *args, **kwargs: deny("socket.getaddrinfo", *args, **kwargs)
socket.gethostbyname = lambda *args, **kwargs: deny("socket.gethostbyname", *args, **kwargs)
subprocess.Popen = lambda *args, **kwargs: deny("subprocess.Popen", *args, **kwargs)
os.system = lambda *args, **kwargs: deny("os.system", *args, **kwargs)
if hasattr(os, "startfile"):
    os.startfile = lambda *args, **kwargs: deny("os.startfile", *args, **kwargs)
for name in ("posix_spawn", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "fork", "forkpty"):
    if hasattr(os, name):
        setattr(os, name, lambda *args, _name=name, **kwargs: deny("os." + _name, *args, **kwargs))
multiprocessing.process.BaseProcess.start = deny_process_or_pipe
multiprocessing.Pipe = deny_process_or_pipe
multiprocessing.connection.Pipe = deny_process_or_pipe
for name in ("CreateProcess", "CreatePipe", "CreateNamedPipe", "ConnectNamedPipe", "LoadLibrary"):
    if hasattr(_winapi, name):
        setattr(_winapi, name, lambda *args, _name=name, **kwargs: deny("_winapi." + _name, *args, **kwargs))
sys.addaudithook(audit)

# Self-check the Windows backslash normalization and every denial family before
# pytest imports the frozen test, owner, candidate, wrapper, or extension.
for path in (
    "D:" + chr(92) + "private" + chr(92) + ".env",
    "D:/private/config.yaml",
    "D:" + chr(92) + "private-capture.json",
    "C:" + chr(92) + "opaque" + chr(92) + "candidate.dll",
    "C:/opaque/candidate.exe",
    "C:/opaque/candidate.pyd",
    "C:/opaque/candidate.bin",
    "C:/external-software/provider-payload",
):
    expect_denied("open:" + norm_path(path), lambda path=path: sys.audit("open", path, "r", 0))
expect_denied("sdk_import", lambda: sys.audit("import", "bt_api.source_qa_probe", None))
expect_denied(
    "native_import_path",
    lambda: sys.audit("import", "opaque_native_source_qa_probe", "C:/opaque/candidate.pyd"),
)
expect_denied("network_connect", lambda: sys.audit("socket.connect", None, None))
expect_denied("network_dns", lambda: sys.audit("socket.getaddrinfo", "source-qa.invalid", None, None, None, None))
expect_denied("socket_constructor", lambda: socket.socket())
expect_denied("ctypes_loader", lambda: ctypes.WinDLL("C:/opaque/blocked.dll"))
expect_denied("subprocess", lambda: subprocess.Popen(["blocked.exe"]))
expect_denied("process_start", lambda: multiprocessing.process.BaseProcess.start(object()))
expect_denied("multiprocessing_pipe", lambda: multiprocessing.Pipe())
expect_denied("connection_pipe", lambda: multiprocessing.connection.Pipe())
if hasattr(_winapi, "CreatePipe"):
    expect_denied("winapi_pipe", lambda: _winapi.CreatePipe())
if hasattr(_winapi, "CreateProcess"):
    expect_denied("winapi_process", lambda: _winapi.CreateProcess())
for event in sorted(FORBIDDEN_AUDIT_EVENTS):
    expect_denied("audit:" + event, lambda event=event: sys.audit(event, None))
assert socket.socket.__name__ == "<lambda>"
assert multiprocessing.process.BaseProcess.start is deny_process_or_pipe
SELF_CHECK = False
BLOCKED_ATTEMPTS.clear()

class Origins:
    def __init__(self):
        self.test_module = None
        self.owners = []
        self.problems = []
        self.facts = {}

    @staticmethod
    def module_path(module):
        value = getattr(module, "__file__", None)
        return str(pathlib.Path(value).resolve()) if isinstance(value, (str, os.PathLike)) else None

    def pytest_collection_finish(self, session):
        matches = [
            module for module in tuple(sys.modules.values())
            if isinstance(module, types.ModuleType)
            and self.module_path(module) == expected_paths["test"]
        ]
        if len(matches) != 1:
            self.problems.append("test_module_origin_count")
            return
        self.test_module = matches[0]
        original = getattr(self.test_module, "_load_owner", None)
        if not callable(original):
            self.problems.append("owner_loader_missing")
            return
        reviewer = self
        def capture_owner(*args, **kwargs):
            owner = original(*args, **kwargs)
            reviewer.owners.append(owner)
            return owner
        self.test_module._load_owner = capture_owner

    def pytest_sessionfinish(self, session, exitstatus):
        if self.test_module is None:
            self.problems.append("test_module_not_captured")
            return
        test_module = self.test_module
        extension = getattr(test_module, "extension", None)
        if self.module_path(test_module) != expected_paths["test"]:
            self.problems.append("test_module_origin_mismatch")
        if (
            not isinstance(extension, types.ModuleType)
            or self.module_path(extension) != expected_paths["extension"]
            or getattr(extension, "__name__", None) != EXPECTED_EXTENSION_MODULE
            or getattr(extension, "_EXTENSION_SELF_PIN", None) != EXPECTED_SELF_PIN
        ):
            self.problems.append("extension_module_origin_or_pin_mismatch")
        wrappers = list(getattr(test_module, "_ROOT_WRAPPERS_BY_OWNER_ID", {}).values())
        if not wrappers:
            self.problems.append("root_wrapper_module_missing")
        wrapper_rows = []
        for wrapper in wrappers:
            spec = getattr(wrapper, "__spec__", None)
            if (
                self.module_path(wrapper) != expected_paths["wrapper"]
                or spec is None
                or str(pathlib.Path(spec.origin).resolve()) != expected_paths["wrapper"]
                or getattr(wrapper, "__th01_held_source_sha256__", None) != EXPECTED_PINS["wrapper"]["sha256"]
                or getattr(wrapper, "__loader__", None) is not spec.loader
            ):
                self.problems.append("root_wrapper_module_origin_mismatch")
            wrapper_rows.append({"name": wrapper.__name__, "path": self.module_path(wrapper)})
        owner_rows = []
        candidate_rows = []
        for owner in self.owners:
            if (
                not isinstance(owner, types.ModuleType)
                or str(pathlib.Path(getattr(owner, "OWNER_PATH", "")).resolve()) != expected_paths["owner"]
                or str(pathlib.Path(getattr(owner, "__th01_verified_owner_source_path__", "")).resolve()) != expected_paths["owner"]
                or getattr(owner, "__th01_verified_owner_source_sha256__", None) != EXPECTED_PINS["owner"]["sha256"]
                or self.module_path(owner) != expected_paths["driver"]
            ):
                self.problems.append("owner_source_origin_or_pin_mismatch")
                continue
            owner_rows.append({
                "name": owner.__name__,
                "runtime_file": self.module_path(owner),
                "verified_source_path": str(pathlib.Path(owner.__th01_verified_owner_source_path__).resolve()),
            })
            candidate = getattr(owner, "_CANDIDATE_MODULE", None)
            if (
                not isinstance(candidate, types.ModuleType)
                or self.module_path(candidate) != expected_paths["candidate"]
                or getattr(candidate, "__th01_verified_candidate_source_sha256__", None) != EXPECTED_PINS["candidate"]["sha256"]
            ):
                self.problems.append("candidate_module_origin_or_pin_mismatch")
            else:
                candidate_rows.append({"name": candidate.__name__, "path": self.module_path(candidate)})
        if not self.owners:
            self.problems.append("no_owner_instances_observed")
        sdk_loaded = sorted(
            name for name in sys.modules
            if name.partition(".")[0].casefold() in SDK_ROOTS
        )
        if sdk_loaded:
            self.problems.append("sdk_module_loaded")
        if str(pathlib.Path(pytest.__file__).resolve()).casefold().startswith(str(pathlib.Path(SITE_ROOT).resolve()).casefold()) is False:
            self.problems.append("pytest_origin_outside_qa_venv")
        self.facts = {
            "test": {"path": self.module_path(test_module)},
            "extension": {"path": self.module_path(extension)},
            "root_wrapper_instances": wrapper_rows,
            "owner_instances": owner_rows,
            "candidate_instances": candidate_rows,
            "pytest": {"path": str(pathlib.Path(pytest.__file__).resolve())},
            "sdk_modules_loaded": sdk_loaded,
        }

origins = Origins()
exit_code = int(pytest.main(ARGUMENTS, plugins=[origins]))
summary = {
    "pytest_exit_code": exit_code,
    "origin_problems": origins.problems,
    "module_origins": origins.facts,
    "blocked_attempts": BLOCKED_ATTEMPTS,
    "guard_selfchecks": EXPECTED_GUARD_SELFCHECKS,
    "guards_installed_before_candidate_test_import": True,
}
print("ROOT_SOURCE_QA_SUMMARY:" + json.dumps(summary, sort_keys=True))
if exit_code != 0 or origins.problems or BLOCKED_ATTEMPTS:
    raise SystemExit(2)
"""

expected_paths = {
    "test": str((ROOT / R9_TEST).resolve()),
    "extension": str((ROOT / R9_EXTENSION).resolve()),
    "wrapper": str((ROOT / ROOT_WRAPPER).resolve()),
    "owner": str((ROOT / OWNER).resolve()),
    "candidate": str((ROOT / CANDIDATE).resolve()),
    "driver": str((ROOT / DRIVER).resolve()),
}
expected_extension_module = (
    "examples.000_live_certification.binance_penetration._certification."
    "th01_force_orders_transport_r9"
)
runner_code = (
    "SOURCE_ROOT = "
    + repr(str(ROOT))
    + "\n"
    + "SITE_ROOT = "
    + repr(str(SITE))
    + "\n"
    + "ARGUMENTS = "
    + repr(arguments)
    + "\n"
    + "EXPECTED_PATHS = "
    + repr(expected_paths)
    + "\n"
    + "EXPECTED_PINS = "
    + repr(
        {
            "extension": PINS[R9_EXTENSION],
            "test": PINS[R9_TEST],
            "wrapper": PINS[ROOT_WRAPPER],
            "owner": PINS[OWNER],
            "candidate": PINS[CANDIDATE],
            "driver": PINS[DRIVER],
        }
    )
    + "\n"
    + "EXPECTED_EXTENSION_MODULE = "
    + repr(expected_extension_module)
    + "\n"
    + "EXPECTED_SELF_PIN = "
    + repr(R9_SELF_PIN)
    + "\n"
    + "EXPECTED_GUARD_SELFCHECKS = "
    + repr(EXPECTED_GUARD_SELFCHECKS)
    + "\n"
    + runner
)

# Pass only Windows runtime paths required by Python; credential-bearing or
# provider configuration environment variables are deliberately not inherited.
environment = {
    key: os.environ[key]
    for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP")
    if key in os.environ
}
environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
completed = subprocess.run(
    [str(PYTHON), "-I", "-S", "-B", "-X", "utf8", "-c", runner_code],
    cwd=QA,
    env=environment,
    capture_output=True,
    timeout=120,
)
stdout = completed.stdout.decode("utf-8", errors="replace")
stderr = completed.stderr.decode("utf-8", errors="replace")
summary_line = next(
    (
        line.removeprefix("ROOT_SOURCE_QA_SUMMARY:")
        for line in reversed(stdout.splitlines())
        if line.startswith("ROOT_SOURCE_QA_SUMMARY:")
    ),
    None,
)
runner_summary = json.loads(summary_line) if summary_line else None
test_summary_present = bool(re.search(r"\b20 passed\b", stdout + stderr))
warning_count = len(re.findall(r"(?i)warning", stdout + stderr))

post_pins = {relative: verify_pin(relative, expected) for relative, expected in PINS.items()}
if git("rev-parse", "HEAD").strip().decode("ascii") != parent:
    raise RuntimeError("git_head_changed_during_source_qa")
if git("branch", "--show-current").strip() != b"dev":
    raise RuntimeError("git_branch_changed_during_source_qa")
if git("diff", "--cached", "--name-only", "-z"):
    raise RuntimeError("staging_index_changed_during_source_qa")

result = {
    "schema": "iteration41.binance.th01.force_orders_transport_r9.root_source_qa.v1",
    "evidence_level": "SOURCE_FAKE_COMPONENT_ONLY",
    "branch": "dev",
    "parent": parent,
    "focused_test": R9_TEST,
    "passed": 20 if test_summary_present else 0,
    "exit_code": completed.returncode,
    "warning_count": warning_count,
    "qa_summary": runner_summary,
    "exact_pre_post_pins": {
        relative: {"pre": pre_pins[relative], "post": post_pins[relative]} for relative in PINS
    },
    "module_origins_verified": bool(
        runner_summary
        and not runner_summary["origin_problems"]
        and not runner_summary["blocked_attempts"]
    ),
    "guard_selfchecks_verified": bool(
        runner_summary
        and runner_summary["guards_installed_before_candidate_test_import"]
        and runner_summary["guard_selfchecks"] == EXPECTED_GUARD_SELFCHECKS
    ),
    "private_opaque_external_software_native_sdk_network_real_process_pipe_denial_before_candidate_imports": bool(
        runner_summary
        and runner_summary["guards_installed_before_candidate_test_import"]
        and runner_summary["guard_selfchecks"] == EXPECTED_GUARD_SELFCHECKS
        and not runner_summary["blocked_attempts"]
    ),
    "actual_provider_or_account": False,
    "actual_worker_or_pipe_lifecycle": False,
    "formal_th01_pass": False,
    "staging_index_empty_before_and_after": True,
    "candidate_sources_modified": False,
}

with RESULT.open("x", encoding="ascii") as stream:
    json.dump(result, stream, sort_keys=True)

print(
    json.dumps(
        {
            "harness_result_path": str(RESULT),
            "exit_code": completed.returncode,
            "summary_present": test_summary_present,
            "warning_count": warning_count,
            "module_origins_verified": result["module_origins_verified"],
            "guard_selfchecks_verified": result["guard_selfchecks_verified"],
        },
        sort_keys=True,
    )
)

if (
    completed.returncode != 0
    or not test_summary_present
    or warning_count != 0
    or not result["module_origins_verified"]
    or not result["guard_selfchecks_verified"]
):
    raise SystemExit(2)
