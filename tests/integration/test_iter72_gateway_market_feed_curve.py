"""Backtrader Feed observation over the committed synthetic CURVE MD fixture.

The scenario runs in a clean interpreter so the SDK's ``tests`` package is
loaded before Backtrader's repository test package.  It binds the real
GatewayMarketAdapter, SDK subscription client, and tick projector; the Store
facade below supplies only the small adapter contract needed for this
cross-repository integration check.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time


_SDK_COMMIT = "896549b2"
_SDK_HELPER_PATH = "tests/integration/test_iter63_ctp_gateway_joint_service.py"
_SDK_HELPER_BLOB = "180af2915b9377e326e5da500397a0758842e9aa"
_SDK_ROOT_COMMIT = "3ee43c9cbd7235c6bfbb9fd28a0d5a4deda708a1"
_SDK_PACKAGE_COMMITS = {
    "bt_api/bt_api_base": "c350f9f7f0e09e78a0d3b1a1b88d119a4552529e",
    "bt_api/bt_api_ctp": "e6f17cc91ce6a61a0f2efc6f0a38a3b58423674d",
    "bt_api/bt_api_gateway": "c369ee94a30455e86b7de60deafc1a0db469fb16",
    "bt_api/bt_api_runtime": "8a24429d8e13c99c825f940017f0fcba4276c7da",
    "bt_api/bt_api_transport_zmq": "dc3f429cf5a0ec33aabec1e3b534589a17b5add6",
}
_SDK_ROOT_SOURCE_BLOBS = {
    "bt_api_py/clock_verification.py": "5841cd5956401a12bc62ec0f684d37bf320c748f",
    "bt_api_py/gateway_market_projection.py": "2a4b3db1039e85cec381fb08711ea7f7e093d434",
    "bt_api_py/gateway_strategy_market.py": "179b63f5d01891c5ff932a4b15f7f2d91927278b",
    "bt_api_py/order_correlation_issuer.py": "bdbec50976cf248fd819f1246b841f32a6b72057",
    "bt_api_py/_win32_security.py": "a5127f7ce96fa612fc88f62fdfded6c675875b62",
    "bt_api_py/service_runtime.py": "88a80cbf2d62fea2a5211a72396bea6d1abccab1",
}
_SDK_PACKAGE_SOURCE_BLOBS = {
    "bt_api/bt_api_base": {
        "src/bt_api_base/service_protocol.py": "e1a0b0f7dad1bed0d27dd53a4274921a2a550099",
        "src/bt_api_base/gateway_direct_protocol.py": "945712d5f1c1bc8f6cb129f8090960472273f184",
        "src/bt_api_base/market_protocol.py": "aeaa17029a29255f7e4562149d71f121c162214a",
        "src/bt_api_base/market_tick_protocol.py": "af17e6228dc748fc749c69ac767d252983a5526e",
    },
    "bt_api/bt_api_gateway": {
        "src/bt_api_gateway/direct_command_journal.py": "c065aad9c4be25b53323d60bbb395c2b72ad2c38",
        "src/bt_api_gateway/market_hub.py": "6bd75b19f0c8358802053a0775a9b5a4def47a66",
    },
    "bt_api/bt_api_ctp": {
        "tests/test_market_provider.py": "dfd238f6511422127643290ea7f98c5392192ed4",
    },
}
_SDK_FIXTURE_TRANSITIVE_BLOBS = {
    "tests/integration/test_iter63_gateway_direct_service.py":
        "278d22e322590abf69c3269b90f19ce12df09d64",
    "tests/integration/test_service_account_instrument_metadata.py":
        "f1b0e5a90aa8c8b8a46a1b423e5d6535e96e824f",
    "tests/unit/test_iter63_gateway_direct_client.py":
        "c270fe4809255aac23fa778cfef3fc8c990ea955",
    "tests/integration/test_iter63_gateway_cancel_rpc.py":
        "0988d44399aa1224964c4b04cb52043f2cffb337",
    "tests/integration/test_iter63_gateway_direct_dispatch.py":
        "519e3ca2be5b4f35692ba616c37a54795726ea4c",
    "tests/iter63_prepared_support.py":
        "f614fe42b0e127c34f312cd8dfc2842693b252ce",
    "tests/unit/test_iter63_gateway_direct_service.py":
        "f6f27184b5da7c39aedf5dbc50d9cddb9ea5f4bb",
}
_BT_SOURCE_COMMIT = "32f55c0010a8882f05dc8aa237a288d48c3666d5"
_BT_SOURCE_BLOBS = {
    "backtrader/feeds/btapifeed.py": "b0febb8d85fe80557054fc2473a912aac5a79e4c",
    "backtrader/feeds/_market_source_port.py": "cbffca17ff316b26b744ea5fd543f0eafb139aa9",
    "backtrader/service/gateway_market_adapter.py": "39fc8e4a6de37cc43977a89232034c4a3f729c5f",
}
_RESULT_PREFIX = "ITER72_BT_GATEWAY_MARKET_FEED_RESULT="
_DIAGNOSTIC_PREFIX = "ITER72_SDK_SPAWN_DIAGNOSTIC="
_CANONICAL_PYTHON = Path("C:/anaconda3/python.exe")


def _install_runner_windows_platform_version_probe():
    """Avoid platform._syscmd_ver's shell call inside an owned runner only."""
    if os.name != "nt" or not hasattr(sys, "getwindowsversion"):
        return None

    import platform

    version = sys.getwindowsversion()
    platform_version = tuple(version.platform_version or version[:3])
    version_text = ".".join(str(part) for part in platform_version)
    platform._syscmd_ver = lambda *_args, **_kwargs: (
        "Microsoft Windows", "", version_text
    )
    return platform_version


_RUNNER_BOOTSTRAP = r'''import os, sys
if sys.stdin.buffer.read(1) != b"\x01":
    raise SystemExit("ITER72_RUNNER_START_TOKEN_MISSING")
if os.name == "nt" and hasattr(sys, "getwindowsversion"):
    import platform
    version = sys.getwindowsversion()
    platform_version = tuple(version.platform_version or version[:3])
    version_text = ".".join(str(part) for part in platform_version)
    platform._syscmd_ver = lambda *_args, **_kwargs: ("Microsoft Windows", "", version_text)
    rendered_platform_version = platform_version
else:
    rendered_platform_version = None
script = os.path.abspath(sys.argv[1])
arguments = sys.argv[2:]
sys.argv = [script, *arguments]
sys.path[0] = os.path.dirname(script)
print("phase=runner_bootstrap_ready", flush=True)
main = sys.modules["__main__"]
main.__file__ = script
main.__spec__ = None
with open(script, "rb") as stream:
    source = stream.read()
exec(compile(source, script, "exec"), main.__dict__)
'''

if __name__ in {"__main__", "__mp_main__"}:
    _install_runner_windows_platform_version_probe()


def _git_output(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, timeout=20, text=True,
        encoding="ascii", errors="strict",
    ).strip()


def _git_tree_blob(repo: Path, revision: str, path: str) -> str:
    return _git_output(repo, "rev-parse", f"{revision}:{path}")


def _git_worktree_blob(repo: Path, path: str) -> str:
    """Hash checkout bytes through the path's clean filter (for clean CRLF files)."""
    return _git_output(repo, "hash-object", "--path", path, path)


def _git_blob_for_bytes(source: bytes) -> str:
    header = b"blob " + str(len(source)).encode("ascii") + b"\0"
    return hashlib.sha1(header + source).hexdigest()


def _verify_source_boundary(sdk_root: Path, bt_root: Path) -> dict:
    """Fail closed unless every selected SDK/BT source boundary is exact."""
    sdk_root = sdk_root.resolve()
    bt_root = bt_root.resolve()
    if _git_output(sdk_root, "rev-parse", "HEAD") != _SDK_ROOT_COMMIT:
        raise RuntimeError("SDK_ROOT_COMMIT_MISMATCH")
    for path, expected in _SDK_ROOT_SOURCE_BLOBS.items():
        if _git_tree_blob(sdk_root, _SDK_ROOT_COMMIT, path) != expected:
            raise RuntimeError("SDK_ROOT_SOURCE_BLOB_BOUNDARY_MISMATCH")
        if _git_worktree_blob(sdk_root, path) != expected:
            raise RuntimeError("SDK_ROOT_SOURCE_WORKTREE_BLOB_MISMATCH")

    package_rows = {}
    for package_path, expected_commit in _SDK_PACKAGE_COMMITS.items():
        if _git_tree_blob(sdk_root, _SDK_ROOT_COMMIT, package_path) != expected_commit:
            raise RuntimeError("SDK_PACKAGE_GITLINK_MISMATCH")
        package_root = sdk_root / package_path
        if _git_output(package_root, "rev-parse", "HEAD") != expected_commit:
            raise RuntimeError("SDK_PACKAGE_COMMIT_MISMATCH")
        if _git_output(
            package_root, "status", "--porcelain", "--untracked-files=all"
        ):
            raise RuntimeError("SDK_PACKAGE_SOURCE_DIRTY")
        package_rows[package_path] = expected_commit
        for relative_path, expected_blob in _SDK_PACKAGE_SOURCE_BLOBS.get(
            package_path, {}
        ).items():
            if _git_tree_blob(package_root, expected_commit, relative_path) != expected_blob:
                raise RuntimeError("SDK_PACKAGE_SOURCE_BLOB_BOUNDARY_MISMATCH")

    fixture_rows = {_SDK_HELPER_PATH: _SDK_HELPER_BLOB}
    fixture_rows.update(_SDK_FIXTURE_TRANSITIVE_BLOBS)
    for relative_path, expected_blob in fixture_rows.items():
        source = subprocess.check_output(
            ["git", "show", f"{_SDK_COMMIT}:{relative_path}"],
            cwd=sdk_root, timeout=20,
        )
        if _git_blob_for_bytes(source) != expected_blob:
            raise RuntimeError("SDK_FIXTURE_TRANSITIVE_BLOB_MISMATCH")

    for path, expected in _BT_SOURCE_BLOBS.items():
        if _git_tree_blob(bt_root, _BT_SOURCE_COMMIT, path) != expected:
            raise RuntimeError("BACKTRADER_SOURCE_BLOB_BOUNDARY_MISMATCH")
        if _git_worktree_blob(bt_root, path) != expected:
            raise RuntimeError("BACKTRADER_SOURCE_WORKTREE_BLOB_MISMATCH")
    return {
        "backtrader_source_commit": _BT_SOURCE_COMMIT,
        "backtrader_source_blobs": dict(sorted(_BT_SOURCE_BLOBS.items())),
        "sdk_fixture_commit": _SDK_COMMIT,
        "sdk_fixture_blobs": dict(sorted(fixture_rows.items())),
        "sdk_package_commits": dict(sorted(package_rows.items())),
        "sdk_root_commit": _SDK_ROOT_COMMIT,
        "sdk_root_source_blobs": dict(sorted(_SDK_ROOT_SOURCE_BLOBS.items())),
        "sdk_package_source_blobs": {
            name: dict(sorted(rows.items()))
            for name, rows in sorted(_SDK_PACKAGE_SOURCE_BLOBS.items())
        },
    }


def _verify_loaded_source_bindings(sdk_root: Path, bt_root: Path) -> dict:
    """Bind every imported SDK/Backtrader source module to its pinned tree."""
    sdk_root = sdk_root.resolve()
    bt_root = bt_root.resolve()
    fixture_rows = {_SDK_HELPER_PATH: _SDK_HELPER_BLOB}
    fixture_rows.update(_SDK_FIXTURE_TRANSITIVE_BLOBS)
    rows = {}
    for module_name, module in tuple(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if not isinstance(origin, str) or not origin.endswith(".py"):
            continue
        source_path = Path(origin).resolve()
        try:
            relative_to_sdk = source_path.relative_to(sdk_root).as_posix()
        except ValueError:
            relative_to_sdk = None
        try:
            relative_to_bt = source_path.relative_to(bt_root).as_posix()
        except ValueError:
            relative_to_bt = None

        if relative_to_sdk is not None:
            if relative_to_sdk.startswith("tests/"):
                expected = fixture_rows.get(relative_to_sdk)
                if relative_to_sdk == _SDK_HELPER_PATH:
                    if module_name != "tests.integration.test_iter63_ctp_gateway_joint_service":
                        raise RuntimeError("SDK_FIXTURE_MODULE_NAME_MISMATCH")
                    rows[module_name] = expected
                    continue  # Its exact bytes were executed from the pinned git-show buffer.
                if expected is None and relative_to_sdk.endswith("__init__.py"):
                    expected = _git_tree_blob(sdk_root, _SDK_ROOT_COMMIT, relative_to_sdk)
                if expected is None:
                    raise RuntimeError("UNPINNED_SDK_TEST_MODULE")
                actual = _git_worktree_blob(sdk_root, relative_to_sdk)
                if actual != expected:
                    raise RuntimeError("SDK_TEST_MODULE_BLOB_MISMATCH")
                rows[module_name] = actual
                continue

            if relative_to_sdk.startswith("bt_api_py/"):
                expected = _git_tree_blob(sdk_root, _SDK_ROOT_COMMIT, relative_to_sdk)
                actual = _git_worktree_blob(sdk_root, relative_to_sdk)
                if actual != expected:
                    raise RuntimeError("SDK_ROOT_LOADED_MODULE_BLOB_MISMATCH")
                rows[module_name] = actual
                continue

            if relative_to_sdk.startswith("bt_api/"):
                package_path, _, package_relative = relative_to_sdk.partition("/")
                package_name, _, package_relative = package_relative.partition("/")
                package_path = f"bt_api/{package_name}"
                package_commit = _SDK_PACKAGE_COMMITS.get(package_path)
                if package_commit is None or not package_relative:
                    raise RuntimeError("UNPINNED_SDK_PACKAGE_MODULE")
                package_root = sdk_root / package_path
                expected = _git_tree_blob(package_root, package_commit, package_relative)
                actual = _git_worktree_blob(package_root, package_relative)
                if actual != expected:
                    raise RuntimeError("SDK_PACKAGE_LOADED_MODULE_BLOB_MISMATCH")
                rows[module_name] = actual
                continue

        if relative_to_bt is not None and relative_to_bt.startswith("backtrader/"):
            expected = _git_tree_blob(bt_root, _BT_SOURCE_COMMIT, relative_to_bt)
            actual = _git_worktree_blob(bt_root, relative_to_bt)
            if actual != expected:
                raise RuntimeError("BACKTRADER_LOADED_MODULE_BLOB_MISMATCH")
            rows[module_name] = actual

    return dict(sorted(rows.items()))


class _WindowsJobOwner:
    """Own exactly one runner process tree; closing the job reaps descendants."""

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class _BasicAccountingInformation(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        self._ExtendedLimitInformation = _ExtendedLimitInformation
        self._BasicAccountingInformation = _BasicAccountingInformation
        self._kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD
        ]
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
            wintypes.LPDWORD,
        ]
        self._kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self.handle = self._kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            self._raise_last_error("CreateJobObjectW")
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel32.SetInformationJobObject(
            self.handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            self.close()
            self._raise_last_error("SetInformationJobObject")

    def _raise_last_error(self, operation):
        code = self._ctypes.get_last_error()
        raise OSError(code, f"{operation} failed")

    def assign_pid(self, pid):
        process = self._kernel32.OpenProcess(
            self._PROCESS_SET_QUOTA | self._PROCESS_TERMINATE, False, int(pid)
        )
        if not process:
            self._raise_last_error("OpenProcess")
        try:
            if not self._kernel32.AssignProcessToJobObject(self.handle, process):
                self._raise_last_error("AssignProcessToJobObject")
        finally:
            self._kernel32.CloseHandle(process)

    def active_processes(self):
        info = self._BasicAccountingInformation()
        returned = self._wintypes.DWORD()
        if not self._kernel32.QueryInformationJobObject(
            self.handle,
            self._JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            self._ctypes.byref(info),
            self._ctypes.sizeof(info),
            self._ctypes.byref(returned),
        ):
            self._raise_last_error("QueryInformationJobObject")
        return int(info.ActiveProcesses)

    def close(self):
        handle, self.handle = self.handle, None
        if handle:
            if not self._kernel32.CloseHandle(handle):
                self._raise_last_error("CloseHandle(job)")


def _run_owned_runner(command, *, cwd: Path, env: dict, stdout, timeout: float):
    """Launch behind a start gate, then assign and bound its exact process tree."""
    command = [str(part) for part in command]
    job = _WindowsJobOwner() if os.name == "nt" else None
    process = None
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=subprocess.STDOUT,
        )
        if job is not None:
            try:
                job.assign_pid(process.pid)
            except BaseException:
                process.kill()
                process.wait(timeout=10)
                raise
        assert process.stdin is not None
        process.stdin.write(b"\x01")
        process.stdin.close()
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if job is not None:
                job.close()
                job = None
            else:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            raise

        if job is not None:
            active = job.active_processes()
            if active:
                job.close()
                job = None
                raise AssertionError(f"RUNNER_JOB_RETAINED_CHILDREN:{active}")
        return subprocess.CompletedProcess(command, return_code)
    finally:
        if process is not None and process.poll() is None:
            if job is not None:
                job.close()
                job = None
            else:
                process.kill()
            process.wait(timeout=10)
        if job is not None:
            job.close()


def _sdk_repo_root() -> Path:
    configured = os.environ.get("BT_API_PY_ROOT")
    return Path(configured) if configured else Path("D:/bt_api_py")


def _sdk_import_roots(sdk_root: Path):
    return [
        sdk_root,
        sdk_root / "tests",
        *(sdk_root / package / "src" for package in _SDK_PACKAGE_COMMITS),
    ]


def _add_sdk_paths(sdk_root: Path) -> None:
    """Install only source roots fixed by this integration boundary."""
    roots = _sdk_import_roots(sdk_root)
    for root in reversed(roots):
        value = str(root.resolve())
        if value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)


def _load_committed_sdk_fixture(sdk_root: Path, *, progress=None):
    """Load the exact accepted SDK test helper, ignoring its dirty checkout copy."""
    import types

    _add_sdk_paths(sdk_root)
    if progress is not None:
        progress("fixture_git_show_started")
    source = subprocess.check_output(
        ["git", "show", f"{_SDK_COMMIT}:{_SDK_HELPER_PATH}"],
        cwd=sdk_root,
        timeout=20,
    )
    if progress is not None:
        progress("fixture_git_show_completed", source_bytes=len(source))
    blob = _git_blob_for_bytes(source)
    if blob != _SDK_HELPER_BLOB:
        raise RuntimeError("PINNED_SDK_FIXTURE_BLOB_MISMATCH")
    if progress is not None:
        progress("fixture_blob_verified", fixture_blob=blob)

    module_name = "tests.integration.test_iter63_ctp_gateway_joint_service"
    module = sys.modules.get(module_name)
    if module is not None:
        return module
    module = types.ModuleType(module_name)
    module.__file__ = str(sdk_root / _SDK_HELPER_PATH)
    module.__package__ = "tests.integration"
    sys.modules[module_name] = module
    try:
        if progress is not None:
            progress("fixture_exec_started")
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        if progress is not None:
            progress("fixture_exec_completed", fixture_blob=blob)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _gateway_process_target(sdk_root_text, *args):
    """Spawn target that re-loads the pinned helper in the fresh child process."""
    print("phase=gateway_child_started", flush=True)
    _install_runner_windows_platform_version_probe()
    sdk_root = Path(sdk_root_text)
    bt_root = Path(__file__).resolve().parents[2]
    print("phase=gateway_child_source_boundary_started", flush=True)
    _verify_source_boundary(sdk_root, bt_root)
    print("phase=gateway_child_source_boundary_verified", flush=True)

    def progress(phase, **_facts):
        print(f"phase=gateway_child_{phase}", flush=True)

    print("phase=gateway_child_fixture_load_started", flush=True)
    fixture = _load_committed_sdk_fixture(sdk_root, progress=progress)
    print("phase=gateway_child_fixture_loaded", flush=True)
    print("phase=gateway_child_loaded_source_bindings_started", flush=True)
    _verify_loaded_source_bindings(sdk_root, bt_root)
    print("phase=gateway_child_loaded_source_bindings_verified", flush=True)
    restore_synthetic_quote = _install_gateway_child_synthetic_quote_fixture(sdk_root)
    print("phase=gateway_child_synthetic_quote_fixture_bound", flush=True)
    print("phase=gateway_child_entry_started", flush=True)
    try:
        fixture._gateway(*args)
    finally:
        restore_synthetic_quote()
        print("phase=gateway_child_synthetic_quote_fixture_restored", flush=True)


def _install_gateway_child_synthetic_quote_fixture(sdk_root):
    """Fill only missing required snapshot fields on the frozen synthetic MD leaf.

    Iteration 63's helper emits only last price and volume.  Current Feed data
    quality correctly rejects that incomplete quote, independently of the
    deliberately unverified clock/freshness evidence.  Keep those trade gates
    untouched while making the fake native quote structurally complete.
    """
    ctp_tests = (sdk_root / "bt_api" / "bt_api_ctp" / "tests").resolve()
    ctp_tests_text = str(ctp_tests)
    sys.path.insert(0, ctp_tests_text)
    try:
        import test_market_provider
    finally:
        if not sys.path or sys.path[0] != ctp_tests_text:
            raise RuntimeError("SYNTHETIC_QUOTE_IMPORT_PATH_CHANGED")
        sys.path.pop(0)
    expected_source = ctp_tests / "test_market_provider.py"
    if Path(test_market_provider.__file__).resolve() != expected_source:
        raise RuntimeError("SYNTHETIC_QUOTE_MODULE_ORIGIN_MISMATCH")
    expected_blob = _SDK_PACKAGE_SOURCE_BLOBS["bt_api/bt_api_ctp"][
        "tests/test_market_provider.py"
    ]
    actual_blob = _git_worktree_blob(
        sdk_root / "bt_api" / "bt_api_ctp", "tests/test_market_provider.py"
    )
    if actual_blob != expected_blob:
        raise RuntimeError("SYNTHETIC_QUOTE_MODULE_BLOB_MISMATCH")

    client_type = test_market_provider._SyntheticMdClient
    original_emit_tick = client_type.emit_tick

    def emit_tick(self, **fields):
        payload = dict(fields)
        symbol = payload.get("InstrumentID")
        if symbol in {"IF2612", "IH2612"}:
            last_price = payload.get("LastPrice")
            if (
                type(last_price) not in (int, float)
                or not math.isfinite(float(last_price))
                or float(last_price) <= 0
            ):
                raise ValueError("INVALID_SYNTHETIC_LAST_PRICE")
            price = float(last_price)
            payload.setdefault("BidPrice1", price - 0.2)
            payload.setdefault("AskPrice1", price + 0.2)
            payload.setdefault("BidVolume1", 1)
            payload.setdefault("AskVolume1", 1)
            payload.setdefault("OpenInterest", 1.0)
        return original_emit_tick(self, **payload)

    client_type.emit_tick = emit_tick

    def restore():
        if client_type.emit_tick is not emit_tick:
            raise RuntimeError("SYNTHETIC_QUOTE_FIXTURE_CHANGED")
        client_type.emit_tick = original_emit_tick

    return restore


def _fixture_import_diagnostic_target(sdk_root_text, send_connection):
    """Prove the pinned fixture imports under Windows spawn without starting it."""
    import os

    send_connection.send(("child_entered", os.getpid()))
    _install_runner_windows_platform_version_probe()
    sdk_root = Path(sdk_root_text)
    bt_root = Path(__file__).resolve().parents[2]
    _verify_source_boundary(sdk_root, bt_root)
    fixture = _load_committed_sdk_fixture(sdk_root)
    _verify_loaded_source_bindings(sdk_root, bt_root)
    send_connection.send(("fixture_imported", os.getpid(), _SDK_HELPER_BLOB))
    send_connection.send(("child_completed", os.getpid()))
    send_connection.close()


def _emit_diagnostic(payload):
    print(_DIAGNOSTIC_PREFIX + json.dumps(payload, sort_keys=True), flush=True)


def _run_spawn_diagnostic(sdk_root: Path) -> None:
    import multiprocessing
    import os

    platform_version = _install_runner_windows_platform_version_probe()
    _emit_diagnostic({
        "phase": "runner_started",
        "pid": os.getpid(),
        "platform_version": platform_version,
    })

    def progress(phase, **facts):
        _emit_diagnostic({"phase": phase, "pid": os.getpid(), **facts})

    bt_root = Path(__file__).resolve().parents[2]
    progress("source_boundary_started")
    source_boundary = _verify_source_boundary(sdk_root, bt_root)
    progress("source_boundary_verified", sdk_commit=source_boundary["sdk_root_commit"],
             bt_commit=source_boundary["backtrader_source_commit"])
    progress("fixture_load_started")
    _load_committed_sdk_fixture(sdk_root, progress=progress)
    loaded_sources = _verify_loaded_source_bindings(sdk_root, bt_root)
    progress("fixture_loaded_sources_verified", loaded_module_count=len(loaded_sources))
    _emit_diagnostic({"phase": "parent_fixture_imported", "pid": os.getpid()})
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    child = ctx.Process(
        target=_fixture_import_diagnostic_target,
        args=(str(sdk_root), send),
    )
    child_started = False
    send_closed = False
    expected = ("child_entered", "fixture_imported", "child_completed")
    observed = []
    try:
        progress("spawn_child_starting")
        child.start()
        child_started = True
        send.close()
        send_closed = True
        progress("spawn_child_started", child_pid=child.pid)
        deadline = time.monotonic() + 35.0
        for phase in expected:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not receive.poll(remaining):
                raise AssertionError(
                    f"SPAWN_DIAGNOSTIC_ACK_TIMEOUT:{phase}:exit={child.exitcode}:alive={child.is_alive()}"
                )
            row = receive.recv()
            if row[0] != phase:
                raise AssertionError(f"SPAWN_DIAGNOSTIC_PHASE_MISMATCH:{phase}")
            observed.append(row)
            _emit_diagnostic({"phase": row[0], "pid": row[1],
                              "fixture_blob": row[2] if len(row) > 2 else None})
        child.join(15)
        if child.exitcode != 0 or child.is_alive():
            raise AssertionError(
                f"SPAWN_DIAGNOSTIC_CHILD_NOT_CLOSED:exit={child.exitcode}:alive={child.is_alive()}"
            )
        _emit_diagnostic({"phase": "parent_join_completed", "exit_code": 0,
                          "child_alive": False, "ack_count": len(observed)})
    finally:
        receive.close()
        if not send_closed:
            send.close()
        if child_started:
            if child.is_alive():
                child.join(1)
            if child.is_alive():
                progress("spawn_child_terminate_started", child_pid=child.pid)
                child.terminate()
                child.join(5)
            if child.is_alive():
                raise AssertionError("SPAWN_DIAGNOSTIC_CHILD_CLEANUP_UNCONFIRMED")
            child_pid = child.pid
            child.close()
            progress("spawn_child_handle_closed", child_pid=child_pid)


class _DispatchSink:
    def __init__(self):
        self.events = []
        self.datas = ()
        self._tradingcal = None

    def dispatch_channel_event(self, event):
        self.events.append(event)


class _GatewayApiFacade:
    def __init__(self, session):
        self._session = session

    def market_subscription(self, _route, name):
        return self._session.market_client.subscription(name)


class _GatewayStoreFacade:
    """Only the attributes GatewayMarketAdapter reads in the Feed path."""

    def __init__(self, config, api):
        self._gateway_strategy_config = config
        self.gateway_strategy_config = config
        self.gateway_api = api
        self.gateway_session_generation = 1
        self._started = True

    def start(self, *, data=None):
        return None


def _drain_statuses(feed):
    return [status for status, _args, _kwargs in feed.get_notifications()]


def _pump_feed(feed, predicate, *, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        feed._load()
        if predicate():
            return
    raise AssertionError("GATEWAY_FEED_EVENT_TIMEOUT")


def _run_synthetic_scenario(sdk_root: Path, temp_root: Path) -> None:
    print("phase=runner_started", flush=True)
    _install_runner_windows_platform_version_probe()
    bt_root = Path(__file__).resolve().parents[2]
    source_boundary = _verify_source_boundary(sdk_root, bt_root)
    print("phase=source_boundary_verified", flush=True)
    _add_sdk_paths(sdk_root)
    def fixture_progress(phase, **_facts):
        print(f"phase={phase}", flush=True)

    fixture = _load_committed_sdk_fixture(sdk_root, progress=fixture_progress)
    print("phase=sdk_fixture_loaded", flush=True)
    bt_root_text = str(bt_root.resolve())
    if bt_root_text in sys.path:
        sys.path.remove(bt_root_text)
    sdk_path_count = len(_sdk_import_roots(sdk_root))
    sys.path.insert(sdk_path_count, bt_root_text)

    import multiprocessing
    import queue
    from types import SimpleNamespace

    import zmq
    from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
    from bt_api_py.order_correlation_issuer import DurableOrderCorrelationIssuer
    from bt_api_py.gateway_strategy_market import (
        GatewayMarketClientSettings,
        GatewayMarketSubscriptionClient,
        GatewayMarketSubscriptionSettings,
    )
    import backtrader as bt
    from backtrader.feeds.btapifeed import BtApiFeed
    print("phase=backtrader_loaded", flush=True)

    temp_root.mkdir(parents=True, exist_ok=True)
    fixture._secure_tmp_path(temp_root)
    (temp_root / "guard").mkdir(exist_ok=True)
    (temp_root / "flow").mkdir(exist_ok=True)
    journal = GatewayDirectCommandJournal.create(
        temp_root / "orders.sqlite", fixture.SCOPE, generation="provisioned"
    )
    issuer = DurableOrderCorrelationIssuer(temp_root / "identity.sqlite")
    issuer_id = issuer.issuer_id
    issuer.close()

    rpc, market_endpoint = fixture._free_endpoint(), fixture._free_endpoint()
    server_keys = zmq.curve_keypair()
    client_keys = (zmq.curve_keypair(), zmq.curve_keypair(), zmq.curve_keypair())
    ctx = multiprocessing.get_context("spawn")
    poll_armed, poll_entered, poll_release = ctx.Event(), ctx.Event(), ctx.Event()
    dequeued = ctx.Value("i", 0)
    maintenance_entered = ctx.Event()
    events, controls = ctx.Queue(), ctx.Queue()
    blocked_poll = (poll_armed, poll_entered, poll_release, dequeued, maintenance_entered)
    gateway = ctx.Process(
        target=_gateway_process_target,
        args=(str(sdk_root), str(temp_root), rpc, market_endpoint, server_keys,
              client_keys, journal.journal_id, issuer_id, events, controls, None, blocked_poll),
    )

    session = None
    feeds = []
    ack_calls = []
    expected_ack_client_ids = {}
    original_accept_resync = GatewayMarketSubscriptionClient.accept_resync
    received_by_feed = {}
    cleanup_errors = []
    try:
        gateway.start()
        print("phase=gateway_started", flush=True)
        # Windows spawn imports and verifies the pinned fixture again in the
        # Gateway child.  Keep that bounded startup outside the recovery SLO;
        # the strict 30-second clock starts only after the MD disconnect below.
        ready = events.get(timeout=60)
        assert ready == ("ready", gateway.pid) and gateway.pid != os.getpid(), ready
        print("phase=gateway_ready", flush=True)

        session = fixture._session(
            fixture.CLIENT_A, client_keys[0], server_keys[0], rpc,
            market_endpoint, journal.journal_id, "IF2612", temp_root,
        )
        session.start(timeout_seconds=10)
        print("phase=session_started", flush=True)
        # The session intentionally exposes its market client, not a mutable
        # copy of constructor settings.  Retain the public subscription
        # contract used to construct the pinned CLIENT_A fixture instead of
        # reaching through session internals.
        subscriptions = {
            "ticks": GatewayMarketSubscriptionSettings(
                fixture._key("IF2612"), require_source_descriptor=True
            ),
            "second_ticks": GatewayMarketSubscriptionSettings(
                fixture._key("IH2612"), require_source_descriptor=True
            ),
        }
        settings = GatewayMarketClientSettings(subscriptions, fixture.MARKET_OPS)
        for name in subscriptions:
            assert session.market_client.subscription(name) is not None
        instruments = {
            item.key.instrument.instrument_id: item.key.instrument
            for item in subscriptions.values()
        }
        config = SimpleNamespace(
            exchange_name="gateway-a",
            market_settings=settings,
            instruments_by_ref=instruments,
            route=session.route,
            peer=fixture.SERVICE,
        )
        store = _GatewayStoreFacade(config, _GatewayApiFacade(session))
        subscription_names = {"IF2612": "ticks", "IH2612": "second_ticks"}

        for symbol in ("IF2612", "IH2612"):
            sink = _DispatchSink()
            feed = BtApiFeed(
                dataname=symbol,
                store=store,
                provider="btapi",
                timeframe=bt.TimeFrame.Ticks,
                backfill_start=False,
                qcheck=0.0,
                price_tick=0.2,
                gateway_clock_verification=None,
            )
            feed._env = sink
            feed._start()
            feeds.append(feed)
            received_by_feed[symbol] = sink.events
            assert (
                feed._gateway_market_adapter._projector._client
                is session.market_client.subscription(subscription_names[symbol])
            )
            expected_ack_client_ids[symbol] = id(
                feed._gateway_market_adapter._projector._client
            )
        assert len(set(expected_ack_client_ids.values())) == 2
        print("phase=feeds_started", flush=True)
        feeds_by_symbol = dict(zip(("IF2612", "IH2612"), feeds))

        def tick_events(symbol):
            return [
                event
                for event in received_by_feed[symbol]
                if hasattr(event.data, "last_price")
            ]

        for symbol, price in (("IF2612", 4120.0), ("IH2612", 4121.0)):
            controls.put(("tick", symbol, price))
            assert events.get(timeout=5) == ("tick", symbol, price)
            feed = feeds_by_symbol[symbol]
            _pump_feed(
                feed,
                lambda symbol=symbol, price=price: (
                    bool(tick_events(symbol))
                    and float(tick_events(symbol)[-1].data.last_price) == price
                ),
            )
            assert float(tick_events(symbol)[-1].data.last_price) == price
            initial_tick = tick_events(symbol)[-1].data
            statuses = _drain_statuses(feed)
            assert feed.LIVE in statuses, (
                symbol,
                statuses,
                getattr(feed, "_laststatus", None),
                getattr(initial_tick, "data_quality", None),
                getattr(initial_tick, "quality_flags", None),
                getattr(initial_tick, "continuity", None),
                getattr(initial_tick, "stale", None),
                getattr(initial_tick, "stale_reason", None),
                getattr(initial_tick, "execution_eligible", None),
                feed._gateway_market_adapter.recovery_reason(),
                getattr(feed, "_continuity_degraded", None),
            )
            assert initial_tick.data_quality == "GOOD"
            assert initial_tick.execution_eligible is False
            assert not {
                "ASK_PRICE_INVALID",
                "ASK_SIZE_INVALID",
                "BID_PRICE_INVALID",
                "BID_SIZE_INVALID",
            } & set(initial_tick.quality_flags)
            assert feed.trade_qualification().ok is False
            adapter = feed._gateway_market_adapter
            assert adapter._projector._source.connection_generation == 1
        loaded_sources_verified = _verify_loaded_source_bindings(sdk_root, bt_root)
        required_loaded_modules = {
            "backtrader.feeds._market_source_port": _BT_SOURCE_BLOBS[
                "backtrader/feeds/_market_source_port.py"
            ],
            "backtrader.feeds.btapifeed": _BT_SOURCE_BLOBS[
                "backtrader/feeds/btapifeed.py"
            ],
            "backtrader.service.gateway_market_adapter": _BT_SOURCE_BLOBS[
                "backtrader/service/gateway_market_adapter.py"
            ],
            "bt_api_py.clock_verification": _SDK_ROOT_SOURCE_BLOBS[
                "bt_api_py/clock_verification.py"
            ],
            "bt_api_py.gateway_market_projection": _SDK_ROOT_SOURCE_BLOBS[
                "bt_api_py/gateway_market_projection.py"
            ],
        }
        assert all(
            loaded_sources_verified.get(module_name) == blob
            for module_name, blob in required_loaded_modules.items()
        )
        print("phase=loaded_source_bindings_verified", flush=True)
        print("phase=old_generation_live", flush=True)

        def observed_accept_resync(self, *, acknowledge_data_loss, timeout_seconds=5.0):
            ack_calls.append((id(self), acknowledge_data_loss))
            return original_accept_resync(
                self,
                acknowledge_data_loss=acknowledge_data_loss,
                timeout_seconds=timeout_seconds,
            )

        GatewayMarketSubscriptionClient.accept_resync = observed_accept_resync
        controls.put("arm_recovery_trace")
        armed = events.get(timeout=5)
        assert armed[0] == "recovery_trace_armed", armed
        poll_armed.set()
        controls.put(("tick", "IF2612", 4123.0))
        assert events.get(timeout=5) == ("tick", "IF2612", 4123.0)
        assert poll_entered.wait(5) and maintenance_entered.wait(5)
        assert dequeued.value == 1
        print("phase=old_poll_held", flush=True)

        controls.put("md_disconnect")
        md_fault = events.get(timeout=5)
        assert md_fault[:3] == ("md_disconnected", 1, 1), md_fault
        print("phase=md_disconnected", flush=True)
        convergence_started = time.monotonic()
        disconnected_event_counts = {
            symbol: len(received_by_feed[symbol]) for symbol in ("IF2612", "IH2612")
        }

        def assert_feed_remains_frozen(symbol):
            feed = feeds_by_symbol[symbol]
            assert len(received_by_feed[symbol]) == disconnected_event_counts[symbol], symbol
            statuses = _drain_statuses(feed)
            assert feed.LIVE not in statuses, (symbol, statuses)
            return statuses

        for symbol in ("IF2612", "IH2612"):
            assert_feed_remains_frozen(symbol)
        old_epochs = {
            symbol: feeds_by_symbol[symbol]._gateway_market_adapter._projector._source.epoch
            for symbol in ("IF2612", "IH2612")
        }

        poll_release.set()
        controls.put(("drive_md_recovery", 1, 1))
        recovered = events.get(timeout=12)
        assert recovered[0] == "md_reconnected", recovered
        new_generation = recovered[3]
        assert new_generation > 1, recovered
        print("phase=md_recovered", flush=True)

        for symbol in ("IF2612", "IH2612"):
            feed = feeds_by_symbol[symbol]
            # The notification is asynchronous.  Poll boundedly until this
            # Feed observes DELAYED, while every poll proves that no downstream
            # event or premature LIVE status escaped.
            _pump_feed(
                feed,
                lambda symbol=symbol, feed=feed: (
                    feed.DELAYED in assert_feed_remains_frozen(symbol)
                ),
                timeout=10.0,
            )
            adapter = feed._gateway_market_adapter
            assert adapter._projector._source.connection_generation == 1
            assert adapter._projector._source.epoch == old_epochs[symbol]
            assert not ack_calls
        print("phase=feeds_delayed", flush=True)

        for symbol in ("IF2612", "IH2612"):
            feed = feeds_by_symbol[symbol]
            # A later bounded poll performs the SDK's explicit
            # acknowledge_data_loss=True resync.  It still has no fresh tick,
            # so each observation must remain frozen and non-LIVE.
            ack_count_before = len(ack_calls)
            adapter = feed._gateway_market_adapter

            def resync_observed(symbol=symbol, adapter=adapter):
                assert_feed_remains_frozen(symbol)
                return (
                    adapter._projector._source.connection_generation
                    == new_generation
                )

            _pump_feed(
                feed,
                resync_observed,
                timeout=10.0,
            )
            assert len(ack_calls) == ack_count_before + 1, (symbol, ack_calls)
            assert ack_calls[-1] == (expected_ack_client_ids[symbol], True), (
                symbol, ack_calls[-1]
            )
            assert adapter._projector._source.connection_generation == new_generation
            assert adapter._projector._source.epoch != old_epochs[symbol]

        assert len(ack_calls) == 2 and len({client for client, _ack in ack_calls}) == 2
        assert all(ack is True for _client, ack in ack_calls), ack_calls
        print("phase=feed_resync_accepted", flush=True)

        post_resync_tick_counts = {
            symbol: len(tick_events(symbol)) for symbol in ("IF2612", "IH2612")
        }
        for symbol, price in (("IF2612", 4124.0), ("IH2612", 4125.0)):
            controls.put(("tick", symbol, price))
            assert events.get(timeout=5) == ("tick", symbol, price)
            feed = feeds_by_symbol[symbol]
            _pump_feed(
                feed,
                lambda symbol=symbol, count=post_resync_tick_counts[symbol], price=price: (
                    len(tick_events(symbol)) > count
                    and float(tick_events(symbol)[-1].data.last_price) == price
                ),
            )
            delivered = tick_events(symbol)[post_resync_tick_counts[symbol]:]
            assert len(delivered) == 1
            assert float(delivered[0].data.last_price) == price
            print(f"phase=fresh_tick_delivered_{symbol}", flush=True)
            adapter = feed._gateway_market_adapter
            raw = delivered[0].data.market_tick_event
            assert raw.data.last_price == price
            assert raw.source.connection_generation == new_generation
            assert raw.cursor.epoch == adapter._projector._source.epoch
            assert feed.LIVE in _drain_statuses(feed)
            # Gateway LIVE reports data continuity only. Without a bound clock,
            # the Feed must remain unqualified for trading.
            assert feed.trade_qualification().ok is False

        convergence_seconds = time.monotonic() - convergence_started
        assert convergence_seconds < 30.0, convergence_seconds
        print(_RESULT_PREFIX + json.dumps({
            "case": "synthetic_curve_gateway_market_feed_epoch_rotation",
            "old_generation": 1,
            "new_generation": new_generation,
            "symbols": ["IF2612", "IH2612"],
            "resync_acknowledgements": len(ack_calls),
            "resync_acknowledgements_by_feed": {
                "IF2612": sum(client == expected_ack_client_ids["IF2612"] for client, _ack in ack_calls),
                "IH2612": sum(client == expected_ack_client_ids["IH2612"] for client, _ack in ack_calls),
            },
            "all_resync_acknowledged_data_loss": all(ack for _client, ack in ack_calls),
            "convergence_seconds": convergence_seconds,
            "no_feed_events_during_disconnect_resync": True,
            "fresh_ticks_only_after_resync": True,
            "feed_live_after_fresh_tick": True,
            "trade_qualification_remains_false": True,
            "source_boundary": {
                **source_boundary,
                "loaded_module_blobs": loaded_sources_verified,
            },
        }, sort_keys=True))
    finally:
        try:
            GatewayMarketSubscriptionClient.accept_resync = original_accept_resync
        except BaseException as error:
            cleanup_errors.append(("resync_hook_restore", type(error).__name__))
        try:
            poll_release.set()
        except BaseException as error:
            cleanup_errors.append(("gateway_poll_release", type(error).__name__))
        for feed in feeds:
            try:
                feed.stop()
            except BaseException as error:
                cleanup_errors.append(("feed_stop", type(error).__name__))
        try:
            if session is not None:
                session.close(timeout_seconds=10)
        except BaseException as error:
            cleanup_errors.append(("session_close", type(error).__name__))
        finally:
            try:
                controls.put("stop")
            except BaseException as error:
                cleanup_errors.append(("gateway_stop_request", type(error).__name__))
            finally:
                remaining = []
                gateway_exitcode = None
                try:
                    if gateway.pid is not None:
                        gateway.join(15)
                        if gateway.is_alive():
                            gateway.terminate()
                            gateway.join(5)
                        if gateway.is_alive():
                            cleanup_errors.append(("gateway_reap", "still_alive"))
                        else:
                            gateway_exitcode = gateway.exitcode
                            gateway.close()
                except BaseException as error:
                    cleanup_errors.append(("gateway_reap", type(error).__name__))
                finally:
                    while True:
                        try:
                            remaining.append(events.get_nowait())
                        except queue.Empty:
                            break
                        except BaseException as error:
                            cleanup_errors.append(("gateway_event_drain", type(error).__name__))
                            break
                if gateway_exitcode is not None and (
                    gateway_exitcode != 0
                    or any(item[0] in {"error", "cleanup_error"} for item in remaining)
                ):
                    cleanup_errors.append(("gateway_exit", str(gateway_exitcode)))
                if gateway_exitcode == 0 and ("closed", 1) not in remaining:
                    cleanup_errors.append(("gateway_close_ack", "missing"))
                if cleanup_errors:
                    raise AssertionError(
                        f"SYNTHETIC_SCENARIO_CLEANUP_FAILED:{cleanup_errors}"
                    )


def _runner_environment():
    names = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _runner_command(python, script: Path, *arguments):
    return [str(python), "-u", "-c", _RUNNER_BOOTSTRAP, str(script), *arguments]


def test_gateway_feed_stays_delayed_until_resync_and_fresh_tick(tmp_path):
    import pytest

    sdk_root = _sdk_repo_root()
    if not (sdk_root / ".git").is_dir():
        pytest.skip("local bt_api_py checkout is required for the synthetic CURVE fixture")
    script = Path(__file__).resolve()
    temp_root = tmp_path / "gateway-market-feed-curve"
    transcript = tmp_path / "gateway-market-feed-curve.log"
    with transcript.open("w", encoding="utf-8", newline="") as output:
        result = _run_owned_runner(
            _runner_command(
                sys.executable, script, "--iter72-synthetic", str(sdk_root), str(temp_root)
            ),
            cwd=tmp_path,
            env=_runner_environment(),
            stdout=output,
            timeout=180,
        )
    runner_output = transcript.read_text(encoding="utf-8")
    assert result.returncode == 0, f"runner output={runner_output}"
    assert runner_output.count(
        "phase=gateway_child_synthetic_quote_fixture_restored"
    ) == 1, runner_output
    rows = [line for line in runner_output.splitlines() if line.startswith(_RESULT_PREFIX)]
    assert len(rows) == 1, runner_output
    summary = json.loads(rows[0][len(_RESULT_PREFIX):])
    expected = {
        "all_resync_acknowledged_data_loss": True,
        "case": "synthetic_curve_gateway_market_feed_epoch_rotation",
        "feed_live_after_fresh_tick": True,
        "fresh_ticks_only_after_resync": True,
        "new_generation": 2,
        "no_feed_events_during_disconnect_resync": True,
        "old_generation": 1,
        "resync_acknowledgements": 2,
        "resync_acknowledgements_by_feed": {"IF2612": 1, "IH2612": 1},
        "symbols": ["IF2612", "IH2612"],
        "trade_qualification_remains_false": True,
    }
    for key, value in expected.items():
        assert summary.get(key) == value, (key, summary)
    assert set(summary) == set(expected) | {
        "convergence_seconds", "source_boundary"
    }
    assert type(summary.get("convergence_seconds")) in (int, float)
    assert 0 <= summary["convergence_seconds"] < 30.0
    boundary = summary.get("source_boundary")
    assert set(boundary) == {
        "backtrader_source_commit", "backtrader_source_blobs", "loaded_module_blobs",
        "sdk_fixture_commit", "sdk_fixture_blobs", "sdk_package_commits",
        "sdk_root_commit", "sdk_root_source_blobs", "sdk_package_source_blobs",
    }
    assert boundary["sdk_root_commit"] == _SDK_ROOT_COMMIT
    assert boundary["sdk_fixture_commit"] == _SDK_COMMIT
    assert boundary["backtrader_source_commit"] == _BT_SOURCE_COMMIT
    assert boundary["sdk_package_commits"] == _SDK_PACKAGE_COMMITS
    assert boundary["sdk_root_source_blobs"] == _SDK_ROOT_SOURCE_BLOBS
    assert boundary["backtrader_source_blobs"] == _BT_SOURCE_BLOBS
    assert boundary["sdk_fixture_blobs"] == {
        _SDK_HELPER_PATH: _SDK_HELPER_BLOB,
        **_SDK_FIXTURE_TRANSITIVE_BLOBS,
    }
    assert boundary["sdk_package_source_blobs"] == _SDK_PACKAGE_SOURCE_BLOBS
    assert boundary["loaded_module_blobs"]
    assert all(type(blob) is str and len(blob) == 40
               for blob in boundary["loaded_module_blobs"].values())


def test_pinned_sdk_fixture_imports_in_windows_spawn_bootstrap():
    import pytest

    sdk_root = _sdk_repo_root()
    if not (sdk_root / ".git").is_dir():
        pytest.skip("local bt_api_py checkout is required for the synthetic CURVE fixture")
    if not _CANONICAL_PYTHON.is_file():
        pytest.skip("canonical Windows Python is unavailable")
    evidence_root = Path(__file__).resolve().parents[2] / ".codex-tmp"
    run_id = f"{time.time_ns()}_{os.getpid()}"
    evidence_dir = evidence_root / f"iter72_gateway_market_spawn_diag_{run_id}"
    evidence_dir.mkdir(parents=True, exist_ok=False)
    transcript = evidence_dir / "runner.log"
    receipt_path = evidence_dir / "result.json"
    receipt = {
        "status": "RUNNING",
        "python_executable": str(_CANONICAL_PYTHON),
        "sdk_root": str(sdk_root),
        "sdk_commit": _SDK_COMMIT,
        "sdk_helper_blob": _SDK_HELPER_BLOB,
        "sdk_root_commit": _SDK_ROOT_COMMIT,
        "sdk_package_commits": _SDK_PACKAGE_COMMITS,
        "backtrader_source_commit": _BT_SOURCE_COMMIT,
        "transcript": str(transcript),
    }
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    try:
        with transcript.open("w", encoding="utf-8", newline="") as output:
            result = _run_owned_runner(
                _runner_command(
                    _CANONICAL_PYTHON, Path(__file__).resolve(),
                    "--iter72-spawn-diagnostic", str(sdk_root),
                ),
                cwd=evidence_dir,
                env=_runner_environment(),
                stdout=output,
                timeout=75,
            )
        runner_output = transcript.read_text(encoding="utf-8")
        rows = [line[len(_DIAGNOSTIC_PREFIX):] for line in runner_output.splitlines()
                if line.startswith(_DIAGNOSTIC_PREFIX)]
        summary = [json.loads(row) for row in rows]
        receipt.update({
            "process_exit_code": result.returncode,
            "markers": summary,
        })
        assert result.returncode == 0, f"diagnostic output={runner_output}"
        assert [item["phase"] for item in summary] == [
            "runner_started", "source_boundary_started", "source_boundary_verified",
            "fixture_load_started", "fixture_git_show_started",
            "fixture_git_show_completed", "fixture_blob_verified", "fixture_exec_started",
            "fixture_exec_completed", "fixture_loaded_sources_verified",
            "parent_fixture_imported", "spawn_child_starting",
            "spawn_child_started", "child_entered", "fixture_imported",
            "child_completed", "parent_join_completed", "spawn_child_handle_closed",
        ]
        assert summary[-2] == {
            "ack_count": 3,
            "child_alive": False,
            "exit_code": 0,
            "phase": "parent_join_completed",
        }
        assert summary[-1]["phase"] == "spawn_child_handle_closed"
        fixture_verified = next(item for item in summary if item["phase"] == "fixture_blob_verified")
        fixture_exec = next(item for item in summary if item["phase"] == "fixture_exec_completed")
        assert fixture_verified["fixture_blob"] == _SDK_HELPER_BLOB
        assert fixture_exec["fixture_blob"] == _SDK_HELPER_BLOB
        assert summary[0]["platform_version"] is not None
        receipt["status"] = "PASS"
    except BaseException as exc:
        receipt["status"] = "FAILED"
        receipt["exception_type"] = type(exc).__name__
        if transcript.exists():
            runner_output = transcript.read_text(encoding="utf-8")
            receipt["markers"] = [
                line[len(_DIAGNOSTIC_PREFIX):]
                for line in runner_output.splitlines()
                if line.startswith(_DIAGNOSTIC_PREFIX)
            ]
        raise
    finally:
        if transcript.exists():
            receipt["transcript_sha256"] = hashlib.sha256(
                transcript.read_bytes()
            ).hexdigest()
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--iter72-synthetic":
    _run_synthetic_scenario(Path(sys.argv[2]), Path(sys.argv[3]))
elif __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--iter72-spawn-diagnostic":
    _run_spawn_diagnostic(Path(sys.argv[2]))
