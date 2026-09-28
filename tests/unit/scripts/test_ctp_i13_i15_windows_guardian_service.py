"""Synthetic AF_PIPE tests for the prestarted inert guardian service."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Optional, Tuple
import uuid

import pytest

from scripts import ctp_i13_i15_parent_launcher as parent_launcher
from scripts import ctp_i13_i15_windows_guardian_service as guardian_service


def _descriptor(repo_root: Path, receipt_root: Path, address: str, auth_key: bytes) -> bytes:
    files = {
        relative: hashlib.sha256(repo_root.joinpath(*relative.split("/")).read_bytes()).hexdigest()
        for relative in parent_launcher._INERT_GUARDIAN_FILES
    }
    executable = Path(sys.executable).resolve()
    value = {
        "schema": parent_launcher._INERT_GUARDIAN_SCHEMA,
        "source_root": str(repo_root),
        "receipt_root": str(receipt_root),
        "pipe_address": address,
        "service_authkey_sha256": hashlib.sha256(auth_key).hexdigest(),
        "python": {
            "executable": str(executable),
            "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "version": platform.python_version(),
            "architecture": platform.machine(),
        },
        "parent_launcher_sha256": hashlib.sha256(
            (repo_root / "scripts" / "ctp_i13_i15_parent_launcher.py").read_bytes()
        ).hexdigest(),
        "files": files,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _bounded_output_tail(value: object) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if type(value) is not str:
        return ""
    return value[-2048:]


def _wait_for_file(
    path: Path,
    process: subprocess.Popen,
    timeout: float = 10.0,
    *,
    phase_path: Optional[Path] = None,
    extra_phase_paths: Tuple[Path, ...] = (),
) -> None:
    deadline = time.monotonic() + timeout
    previous_contents = None
    while time.monotonic() < deadline:
        try:
            contents = path.read_bytes()
        except OSError:
            contents = b""
        if contents and contents == previous_contents:
            return
        previous_contents = contents
        if process.poll() is not None and not path.exists():
            break
        time.sleep(0.02)
    try:
        stdout, stderr = process.communicate(timeout=0.05)
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.output, error.stderr
    phases = []
    for index, diagnostic_path in enumerate(
        (() if phase_path is None else (phase_path,)) + extra_phase_paths, start=1
    ):
        try:
            contents = diagnostic_path.read_text(encoding="ascii")[-8192:]
        except OSError:
            contents = "<phase log unavailable>"
        phases.append("phase_log_{0}={1!r}".format(index, contents))
    pytest.fail(
        "expected stable marker {0}; process_pid={1} alive={2} exit_code={3}; "
        "stdout_tail={4!r} stderr_tail={5!r} phases={6!r}".format(
            path.name,
            process.pid,
            process.poll() is None,
            process.poll(),
            _bounded_output_tail(stdout),
            _bounded_output_tail(stderr),
            " ".join(phases),
        )
    )


@pytest.mark.parametrize(
    ("mode", "expect_receipt"),
    [("request", False), ("response", True), ("deadline", True), ("identity", False)],
)
@pytest.mark.skipif(
    os.name != "nt" or sys.getwindowsversion().major < 10 or sys.getwindowsversion().build < 14393,
    reason="the integration contract requires Windows AF_PIPE and Job lists",
)
def test_prestarted_service_survives_owner_death_during_ipc(
    tmp_path: Path, mode: str, expect_receipt: bool
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    receipt_root = tmp_path / "service-output"
    receipt_root.mkdir()
    address = rf"\\.\pipe\backtrader-ctp-i13-i15-{uuid.uuid4().hex}"
    auth_key = os.urandom(32)
    descriptor_raw = _descriptor(repo_root, receipt_root, address, auth_key)
    descriptor_path = tmp_path / "guardian-descriptor.json"
    descriptor_path.write_bytes(descriptor_raw)
    descriptor_pin = hashlib.sha256(descriptor_raw).hexdigest()
    ready_path = tmp_path / "service-ready.json"
    service_status_path = tmp_path / "service-status.txt"
    response_wait_path = tmp_path / "service-before-response"
    owner_ipc_stage_path = tmp_path / "owner-before-send"
    release_service_path = tmp_path / "release-service-response"
    service_phase_path = tmp_path / "service-phases.jsonl"
    service_script = tmp_path / "prestarted_service.py"
    service_script.write_text(
        "\n".join(
            [
                "import json, os, sys, time",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(repo_root)!r})",
                "from scripts import ctp_i13_i15_windows_guardian_service as service_module",
                "serve_one_inert_request = service_module.serve_one_inert_request",
                "args = sys.argv[1:]",
                "address, key_hex, executable, executable_hash, receipt_root, ready_path, status_path, response_path, release_path, mode, phase_path = args",
                "def mark(phase):",
                "    with Path(phase_path).open('a', encoding='ascii') as stream:",
                "        stream.write(json.dumps({'phase': phase, 'monotonic_ns': time.monotonic_ns(), 'pid': os.getpid()}, separators=(',', ':')) + '\\n')",
                "        stream.flush()",
                "mark('service_started')",
                "original_accept = service_module._RestrictedPipeListener.accept",
                "def traced_accept(listener):",
                "    mark('pipe_accept_started')",
                "    try: connection = original_accept(listener)",
                "    except BaseException:",
                "        mark('pipe_accept_failed')",
                "        raise",
                "    mark('pipe_accept_returned')",
                "    return connection",
                "service_module._RestrictedPipeListener.accept = traced_accept",
                "original_decode = service_module._decode_request",
                "def traced_decode(raw, *, now):",
                "    mark('request_decode_started')",
                "    try: value = original_decode(raw, now=now)",
                "    except BaseException:",
                "        mark('request_decode_failed')",
                "        raise",
                "    mark('request_decode_returned')",
                "    return value",
                "service_module._decode_request = traced_decode",
                "def ready(address, pid):",
                "    mark('service_ready_callback')",
                "    Path(ready_path).write_text(json.dumps({'address': address, 'pid': pid}), encoding='ascii')",
                "def before_response():",
                "    mark('service_before_response')",
                "    if mode not in ('response', 'deadline'): return",
                "    Path(response_path).write_text('ready', encoding='ascii')",
                "    end = time.monotonic() + 20.0",
                "    while not Path(release_path).exists() and time.monotonic() < end:",
                "        time.sleep(0.02)",
                "mark('serve_call_started')",
                "result = serve_one_inert_request(",
                "    address=address, auth_key=bytes.fromhex(key_hex),",
                "    python_executable=executable, python_sha256=executable_hash,",
                "    receipt_root=receipt_root, ready=ready, before_response=before_response,",
                "    accept_timeout_seconds=30.0,",
                ")",
                "mark('serve_call_returned')",
                "Path(status_path).write_text(result, encoding='ascii')",
            ]
        ),
        encoding="utf-8",
    )
    python_executable = str(Path(sys.executable).resolve())
    python_hash = hashlib.sha256(Path(python_executable).read_bytes()).hexdigest()
    service = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(service_script),
            address,
            auth_key.hex(),
            python_executable,
            python_hash,
            str(receipt_root),
            str(ready_path),
            str(service_status_path),
            str(response_wait_path),
            str(release_service_path),
            mode,
            str(service_phase_path),
        ],
        cwd=str(repo_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    owner_path = tmp_path / "owner.py"
    owner_result_path = tmp_path / "owner-result.json"
    owner_pid_path = tmp_path / "owner-pid.txt"
    owner_phase_path = tmp_path / "owner-phases.jsonl"
    owner_path.write_text(
        "\n".join(
            [
                "import json, os, platform, sys, time",
                "from pathlib import Path",
                "owner_phase_path = sys.argv[-1]",
                "def mark(phase):",
                "    with Path(owner_phase_path).open('a', encoding='ascii') as stream:",
                "        stream.write(json.dumps({'phase': phase, 'monotonic_ns': time.monotonic_ns(), 'pid': os.getpid()}, separators=(',', ':')) + '\\n')",
                "        stream.flush()",
                "mark('owner_started')",
                f"sys.path.insert(0, {str(repo_root)!r})",
                "from scripts import ctp_i13_i15_parent_launcher as launcher",
                "from scripts.ctp_i13_i15_windows_guardian_service import request_over_pipe",
                "mark('owner_modules_imported')",
                "args = sys.argv[1:]",
                "mode, descriptor_path, descriptor_pin, auth_key_hex, service_pid, stage_path, result_path, owner_pid_path, owner_phase_path = args",
                "mark('owner_pid_write_started')",
                "Path(owner_pid_path).write_text(str(os.getpid()), encoding='ascii')",
                "mark('descriptor_read_started')",
                "raw = Path(descriptor_path).read_bytes()",
                "mark('descriptor_read_completed')",
                "trusted = launcher.ExternallyPinnedDescriptor(raw, descriptor_pin, 'fake-service-test')",
                "def before_send():",
                "    mark('ipc_before_send')",
                "    if mode != 'request': return",
                "    Path(stage_path).write_text('connected', encoding='ascii')",
                "    time.sleep(30.0)",
                "def requester(**kwargs):",
                "    mark('ipc_request_started')",
                "    kwargs['before_send'] = before_send",
                "    try: return request_over_pipe(**kwargs)",
                "    finally: mark('ipc_request_finished')",
                "now = time.monotonic()",
                "expected_service_pid = int(service_pid) + (1 if mode == 'identity' else 0)",
                "mark('request_inert_guardian_entered')",
                "result = launcher.request_inert_guardian(",
                "    trusted, captured_launcher_bytes=Path("
                + repr(str(repo_root / "scripts" / "ctp_i13_i15_parent_launcher.py"))
                + ").read_bytes(),",
                "    actual_executable=sys.executable, actual_version=platform.python_version(),",
                "    actual_architecture=platform.machine(), child_seconds=30.0,",
                "    stop_deadline_monotonic=now + 5.0, deadline_monotonic=now + 8.0,",
                "    service_pid=expected_service_pid, service_auth_key=bytes.fromhex(auth_key_hex),",
                "    request_id='0123456789abcdef0123456789abcdef', ipc_requester=requester,",
                "    monotonic=time.monotonic,",
                ")",
                "mark('request_inert_guardian_returned')",
                "Path(result_path).write_text(json.dumps({'state': result.state, 'reason': result.reason}), encoding='ascii')",
                "mark('owner_result_written')",
            ]
        ),
        encoding="utf-8",
    )
    owner = None
    owner_handle = None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    try:
        _wait_for_file(ready_path, service, phase_path=service_phase_path)
        service_pid = json.loads(ready_path.read_text(encoding="ascii"))["pid"]
        assert type(service_pid) is int and service_pid > 0
        owner = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(owner_path),
                mode,
                str(descriptor_path),
                descriptor_pin,
                auth_key.hex(),
                str(service_pid),
                str(owner_ipc_stage_path),
                str(owner_result_path),
                str(owner_pid_path),
                str(owner_phase_path),
            ],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for_file(owner_pid_path, owner, phase_path=owner_phase_path)
        owner_pid = int(owner_pid_path.read_text(encoding="ascii"))
        owner_handle = kernel32.OpenProcess(0x00100000 | 0x0001, False, owner_pid)
        assert owner_handle
        if mode == "request":
            _wait_for_file(owner_ipc_stage_path, owner, phase_path=owner_phase_path)
        elif mode == "identity":
            _wait_for_file(
                owner_result_path,
                owner,
                phase_path=owner_phase_path,
                extra_phase_paths=(service_phase_path,),
            )
            owner.wait(timeout=2.0)
            owner_result = json.loads(owner_result_path.read_text(encoding="ascii"))
            assert owner_result["state"] == "unknown"
        else:
            _wait_for_file(
                response_wait_path,
                owner,
                timeout=12.0,
                phase_path=owner_phase_path,
                extra_phase_paths=(service_phase_path,),
            )
        if mode == "deadline":
            _wait_for_file(owner_result_path, owner, timeout=10.0, phase_path=owner_phase_path)
            owner.wait(timeout=2.0)
            owner_result = json.loads(owner_result_path.read_text(encoding="ascii"))
            assert owner_result == {"state": "unknown", "reason": "ipc_deadline_exceeded"}
            assert service.poll() is None, "guardian service stopped with parent IPC timeout"
            release_service_path.write_text("release", encoding="ascii")
        elif mode in ("request", "response"):
            assert kernel32.TerminateProcess(owner_handle, 0xEE13)
            assert kernel32.WaitForSingleObject(owner_handle, 5_000) == 0
            owner.wait(timeout=5.0)
        if mode == "response":
            assert service.poll() is None, "prestarted service exited with the request owner"
            release_service_path.write_text("release", encoding="ascii")
        service.wait(timeout=12.0)
        assert service_status_path.exists()
        if expect_receipt:
            receipt_path = receipt_root / "guardian-receipt.json"
            assert receipt_path.exists()
            receipt = json.loads(receipt_path.read_text(encoding="ascii"))
            assert receipt["service_pid"] == service_pid
            assert receipt["job_empty_observed"] is True
            assert receipt["containment"] == "verified"
            assert (
                service_status_path.read_text(encoding="ascii")
                == "owner_disconnected_after_cleanup"
            )
        else:
            assert not (receipt_root / "guardian-receipt.json").exists()
            if mode == "identity":
                assert service_status_path.read_text(encoding="ascii") == "service_accept_failed"
            else:
                assert (
                    service_status_path.read_text(encoding="ascii")
                    == "request_incomplete_or_owner_disconnected"
                )
    finally:
        if owner is not None and owner.poll() is None:
            if owner_handle and kernel32.WaitForSingleObject(owner_handle, 0) == 0x00000102:
                kernel32.TerminateProcess(owner_handle, 0xEE13)
                kernel32.WaitForSingleObject(owner_handle, 5_000)
            if owner.poll() is None:
                owner.kill()
            owner.wait(timeout=5.0)
        if service.poll() is None:
            release_service_path.write_text("release", encoding="ascii")
            service.kill()
            service.wait(timeout=5.0)
        if owner_handle:
            kernel32.CloseHandle(owner_handle)


@pytest.mark.skipif(
    os.name != "nt" or sys.getwindowsversion().major < 10 or sys.getwindowsversion().build < 14393,
    reason="the integration contract requires Windows AF_PIPE and Job lists",
)
def test_service_deadline_does_not_interrupt_blocked_backend_but_process_death_closes_job(
    tmp_path: Path,
) -> None:
    """Prove the IPC deadline is not a hard service deadline when a backend call blocks."""

    import ctypes
    from ctypes import wintypes

    repo_root = Path(__file__).resolve().parents[3]
    receipt_root = tmp_path / "service-output"
    receipt_root.mkdir()
    address = rf"\\.\pipe\backtrader-ctp-i13-i15-{uuid.uuid4().hex}"
    auth_key = os.urandom(32)
    descriptor_raw = _descriptor(repo_root, receipt_root, address, auth_key)
    descriptor_path = tmp_path / "guardian-descriptor.json"
    descriptor_path.write_bytes(descriptor_raw)
    descriptor_pin = hashlib.sha256(descriptor_raw).hexdigest()
    ready_path = tmp_path / "service-ready.json"
    service_status_path = tmp_path / "service-status.txt"
    child_active_path = tmp_path / "inert-child-active.json"
    service_phase_path = tmp_path / "service-phases.jsonl"
    owner_phase_path = tmp_path / "owner-phases.jsonl"
    service_script = tmp_path / "blocked_backend_service.py"
    service_script.write_text(
        "\n".join(
            [
                "import ctypes, json, os, sys, time",
                "from ctypes import wintypes",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(repo_root)!r})",
                "from scripts import ctp_i13_i15_windows_guardian_service as service_module",
                "serve_one_inert_request = service_module.serve_one_inert_request",
                "from scripts.ctp_i13_i15_windows_job_backend import WindowsJobBackend",
                "address, key_hex, executable, executable_hash, receipt_root, ready_path, status_path, child_active_path, phase_path = sys.argv[1:]",
                "def mark(phase):",
                "    with Path(phase_path).open('a', encoding='ascii') as stream:",
                "        stream.write(json.dumps({'phase': phase, 'monotonic_ns': time.monotonic_ns(), 'pid': os.getpid()}, separators=(',', ':')) + '\\n')",
                "        stream.flush()",
                "mark('service_started')",
                "original_accept = service_module._RestrictedPipeListener.accept",
                "def traced_accept(listener):",
                "    mark('pipe_accept_started')",
                "    try: connection = original_accept(listener)",
                "    except BaseException:",
                "        mark('pipe_accept_failed')",
                "        raise",
                "    mark('pipe_accept_returned')",
                "    return connection",
                "service_module._RestrictedPipeListener.accept = traced_accept",
                "original_decode = service_module._decode_request",
                "def traced_decode(raw, *, now):",
                "    mark('request_decode_started')",
                "    try: value = original_decode(raw, now=now)",
                "    except BaseException:",
                "        mark('request_decode_failed')",
                "        raise",
                "    mark('request_decode_returned')",
                "    return value",
                "service_module._decode_request = traced_decode",
                "def ready(address, pid):",
                "    mark('service_ready_callback')",
                "    Path(ready_path).write_text(json.dumps({'address': address, 'pid': pid}), encoding='ascii')",
                "def backend_factory():",
                "    mark('backend_factory_called')",
                "    backend = WindowsJobBackend()",
                "    create = backend.create_suspended_in_job",
                "    def create_blocked(command, *, deadline_monotonic):",
                "        mark('job_create_started')",
                "        session = create(command, deadline_monotonic=deadline_monotonic)",
                "        mark('job_create_returned')",
                "        resume = session.resume_launcher",
                "        def resume_then_block():",
                "            mark('launcher_resume_started')",
                "            resumed = resume()",
                "            mark('launcher_resume_returned')",
                "            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)",
                "            get_process_id = kernel32.GetProcessId",
                "            get_process_id.argtypes = [wintypes.HANDLE]",
                "            get_process_id.restype = wintypes.DWORD",
                "            child_pid = int(get_process_id(wintypes.HANDLE(session._process_handle)))",
                "            Path(child_active_path).write_text(json.dumps({'service_pid': os.getpid(), 'child_pid': child_pid}), encoding='ascii')",
                "            mark('child_active_marker_written')",
                "            end = time.monotonic() + 120.0",
                "            mark('backend_block_started')",
                "            while time.monotonic() < end:",
                "                time.sleep(0.02)",
                "            return resumed",
                "        session.resume_launcher = resume_then_block",
                "        return session",
                "    backend.create_suspended_in_job = create_blocked",
                "    return backend",
                "mark('serve_call_started')",
                "result = serve_one_inert_request(",
                "    address=address, auth_key=bytes.fromhex(key_hex),",
                "    python_executable=executable, python_sha256=executable_hash,",
                "    receipt_root=receipt_root, ready=ready, backend_factory=backend_factory,",
                "    accept_timeout_seconds=30.0,",
                ")",
                "mark('serve_call_returned')",
                "Path(status_path).write_text(result, encoding='ascii')",
            ]
        ),
        encoding="utf-8",
    )
    owner_script = tmp_path / "deadline_owner.py"
    owner_result_path = tmp_path / "owner-result.json"
    owner_script.write_text(
        "\n".join(
            [
                "import json, os, platform, sys, time",
                "from pathlib import Path",
                "owner_phase_path = sys.argv[-1]",
                "def mark(phase):",
                "    with Path(owner_phase_path).open('a', encoding='ascii') as stream:",
                "        stream.write(json.dumps({'phase': phase, 'monotonic_ns': time.monotonic_ns(), 'pid': os.getpid()}, separators=(',', ':')) + '\\n')",
                "        stream.flush()",
                "mark('owner_started')",
                f"sys.path.insert(0, {str(repo_root)!r})",
                "from scripts import ctp_i13_i15_parent_launcher as launcher",
                "from scripts.ctp_i13_i15_windows_guardian_service import request_over_pipe",
                "mark('owner_modules_imported')",
                "descriptor_path, descriptor_pin, auth_key_hex, service_pid, result_path, owner_phase_path = sys.argv[1:]",
                "mark('descriptor_read_started')",
                "raw = Path(descriptor_path).read_bytes()",
                "mark('descriptor_read_completed')",
                "trusted = launcher.ExternallyPinnedDescriptor(raw, descriptor_pin, 'fake-service-death-test')",
                "now = time.monotonic()",
                "mark('inert_guardian_request_started')",
                "def requester(**kwargs):",
                "    mark('ipc_request_started')",
                "    try: return request_over_pipe(**kwargs)",
                "    finally: mark('ipc_request_finished')",
                "result = launcher.request_inert_guardian(",
                "    trusted, captured_launcher_bytes=Path("
                + repr(str(repo_root / "scripts" / "ctp_i13_i15_parent_launcher.py"))
                + ").read_bytes(),",
                "    actual_executable=sys.executable, actual_version=platform.python_version(),",
                "    actual_architecture=platform.machine(), child_seconds=30.0,",
                "    stop_deadline_monotonic=now + 5.0, deadline_monotonic=now + 8.0,",
                "    service_pid=int(service_pid), service_auth_key=bytes.fromhex(auth_key_hex),",
                "    request_id='fedcba9876543210fedcba9876543210', ipc_requester=requester,",
                "    monotonic=time.monotonic,",
                ")",
                "mark('inert_guardian_request_finished')",
                "Path(result_path).write_text(json.dumps({'state': result.state, 'reason': result.reason}), encoding='ascii')",
                "mark('owner_result_written')",
            ]
        ),
        encoding="utf-8",
    )

    python_executable = str(Path(sys.executable).resolve())
    python_hash = hashlib.sha256(Path(python_executable).read_bytes()).hexdigest()
    service = None
    owner = None
    guardian_handle = None
    child_handle = None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    synchronize = 0x00100000
    process_terminate = 0x0001
    try:
        service = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(service_script),
                address,
                auth_key.hex(),
                python_executable,
                python_hash,
                str(receipt_root),
                str(ready_path),
                str(service_status_path),
                str(child_active_path),
                str(service_phase_path),
            ],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for_file(ready_path, service, phase_path=service_phase_path)
        service_pid = json.loads(ready_path.read_text(encoding="ascii"))["pid"]
        owner = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(owner_script),
                str(descriptor_path),
                descriptor_pin,
                auth_key.hex(),
                str(service_pid),
                str(owner_result_path),
                str(owner_phase_path),
            ],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for_file(
            child_active_path,
            service,
            timeout=12.0,
            phase_path=service_phase_path,
            extra_phase_paths=(owner_phase_path,),
        )
        child_facts = json.loads(child_active_path.read_text(encoding="ascii"))
        assert child_facts["service_pid"] == service_pid
        child_pid = child_facts["child_pid"]
        guardian_handle = kernel32.OpenProcess(synchronize | process_terminate, False, service_pid)
        child_handle = kernel32.OpenProcess(synchronize, False, child_pid)
        assert guardian_handle and child_handle
        assert kernel32.WaitForSingleObject(child_handle, 0) == wait_timeout

        _wait_for_file(owner_result_path, owner, timeout=12.0, phase_path=owner_phase_path)
        owner.wait(timeout=5.0)
        owner_result = json.loads(owner_result_path.read_text(encoding="ascii"))
        assert owner_result == {"state": "unknown", "reason": "ipc_deadline_exceeded"}
        assert kernel32.WaitForSingleObject(guardian_handle, 0) == wait_timeout
        assert kernel32.WaitForSingleObject(child_handle, 0) == wait_timeout
        assert not (receipt_root / "guardian-receipt.json").exists()

        assert kernel32.TerminateProcess(guardian_handle, 0xEE13)
        assert kernel32.WaitForSingleObject(guardian_handle, 10_000) == wait_object_0
        assert kernel32.WaitForSingleObject(child_handle, 10_000) == wait_object_0
        service.wait(timeout=5.0)
        assert not (receipt_root / "guardian-receipt.json").exists()
    finally:
        if owner is not None and owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5.0)
        if guardian_handle and kernel32.WaitForSingleObject(guardian_handle, 0) == wait_timeout:
            kernel32.TerminateProcess(guardian_handle, 0xEE13)
            kernel32.WaitForSingleObject(guardian_handle, 10_000)
        elif service is not None and service.poll() is None:
            service.kill()
        if child_handle and kernel32.WaitForSingleObject(child_handle, 0) == wait_timeout:
            kernel32.TerminateProcess(child_handle, 0xEE13)
            kernel32.WaitForSingleObject(child_handle, 10_000)
        if service is not None and service.poll() is None:
            service.wait(timeout=5.0)
        if child_handle:
            kernel32.CloseHandle(child_handle)
        if guardian_handle:
            kernel32.CloseHandle(guardian_handle)


def test_service_request_rejects_extra_command_or_path_fields() -> None:
    now = time.monotonic()
    request = {
        "schema": guardian_service.REQUEST_SCHEMA,
        "operation": "sleep_probe",
        "request_id": "0123456789abcdef0123456789abcdef",
        "child_seconds": 1,
        "stop_deadline_monotonic": now + 5,
        "deadline_monotonic": now + 8,
        "command": [sys.executable],
        "receipt_path": "C:\\arbitrary\\path",
    }
    raw = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("ascii")
    with pytest.raises(guardian_service.GuardianServiceError, match="request_fields_invalid"):
        guardian_service._decode_request(raw, now=now)


class _FakeNativeFunction:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


def _fake_pipe_token_apis(
    *,
    source_sid="S-1-5-21-77",
    duplicate_ok=True,
    revert_ok=True,
    impersonate_raise_after_switch=False,
):
    import ctypes
    from types import SimpleNamespace

    events = []
    closed = []

    def open_thread_token(_thread, desired_access, _open_as_self, output):
        events.append(("open_thread_token", desired_access))
        ctypes.cast(output, ctypes.POINTER(guardian_service.wintypes.HANDLE)).contents.value = 101
        return True

    def duplicate_token(source, desired_access, _attributes, impersonation, token_type, output):
        events.append(
            ("duplicate_token", int(source.value), desired_access, impersonation, token_type)
        )
        if duplicate_ok:
            ctypes.cast(
                output, ctypes.POINTER(guardian_service.wintypes.HANDLE)
            ).contents.value = 202
        return duplicate_ok

    kernel32 = SimpleNamespace(
        GetCurrentThread=_FakeNativeFunction(lambda: 303),
        CloseHandle=_FakeNativeFunction(lambda handle: closed.append(int(handle.value)) or True),
    )

    def impersonate_named_pipe_client(_handle):
        events.append("impersonate")
        if impersonate_raise_after_switch:
            events.append("impersonation_side_effect")
            raise KeyboardInterrupt("simulated wrapper interruption")
        return True

    advapi32 = SimpleNamespace(
        ImpersonateNamedPipeClient=_FakeNativeFunction(impersonate_named_pipe_client),
        OpenThreadToken=_FakeNativeFunction(open_thread_token),
        DuplicateTokenEx=_FakeNativeFunction(duplicate_token),
        RevertToSelf=_FakeNativeFunction(lambda: events.append("revert") or revert_ok),
    )
    return kernel32, advapi32, events, closed


def test_pipe_client_token_is_duplicated_primary_and_reverted_before_return(monkeypatch):
    sid = "S-1-5-21-77"
    kernel32, advapi32, events, closed = _fake_pipe_token_apis(source_sid=sid)
    monkeypatch.setattr(guardian_service.os, "name", "nt")
    monkeypatch.setattr(guardian_service, "_pipe_token_apis", lambda: (kernel32, advapi32))
    monkeypatch.setattr(guardian_service, "_client_pid_from_pipe", lambda _handle: 456)
    monkeypatch.setattr(
        guardian_service, "_token_user_sid", lambda handle: sid if handle in (101, 202) else ""
    )

    token = guardian_service._authenticated_pipe_client_primary_token(12, expected_client_sid=sid)

    assert token.handle == 202
    assert token.client_sid == sid
    assert token.client_pid == 456
    assert events[0] == "impersonate"
    assert events[-1] == "revert"
    open_event = next(item for item in events if item[0] == "open_thread_token")
    assert open_event == (
        "open_thread_token",
        guardian_service._TOKEN_QUERY | guardian_service._TOKEN_DUPLICATE,
    )
    duplicate_event = next(item for item in events if item[0] == "duplicate_token")
    assert duplicate_event == (
        "duplicate_token",
        101,
        guardian_service._TOKEN_QUERY
        | guardian_service._TOKEN_ASSIGN_PRIMARY,
        guardian_service._SECURITY_IMPERSONATION,
        guardian_service._TOKEN_PRIMARY,
    )
    assert closed == [101]
    close_results = iter((False, True))
    kernel32.CloseHandle.callback = lambda handle: (
        closed.append(int(handle.value)) or next(close_results)
    )
    assert token.close() is False
    assert token._closed is False
    assert token.close() is True
    assert token._closed is True
    assert closed == [101, 202, 202]


def test_coordinator_owner_token_capture_adds_only_fixed_session_adjust_right(monkeypatch):
    sid = "S-1-5-21-77"
    kernel32, advapi32, events, _closed = _fake_pipe_token_apis(source_sid=sid)
    monkeypatch.setattr(guardian_service.os, "name", "nt")
    monkeypatch.setattr(guardian_service, "_pipe_token_apis", lambda: (kernel32, advapi32))
    monkeypatch.setattr(guardian_service, "_client_pid_from_pipe", lambda _handle: 456)
    monkeypatch.setattr(guardian_service, "_token_user_sid", lambda _handle: sid)

    token = guardian_service._authenticated_pipe_client_primary_token(
        12, expected_client_sid=sid, include_session_adjustment=True
    )
    try:
        duplicate_event = next(item for item in events if item[0] == "duplicate_token")
        assert duplicate_event[2] == (
            guardian_service._TOKEN_QUERY
            | guardian_service._TOKEN_ASSIGN_PRIMARY
            | guardian_service._TOKEN_ADJUST_SESSIONID
        )
    finally:
        assert token.close()
    assert token._closed is True


@pytest.mark.parametrize(
    ("source_sid", "duplicate_ok", "revert_ok", "reason"),
    [
        ("S-1-5-21-other", True, True, "pipe_client_identity_mismatch"),
        ("S-1-5-21-77", False, True, "pipe_client_primary_token_unavailable"),
    ],
)
def test_pipe_client_token_capture_fails_closed_and_closes_handles(
    monkeypatch, source_sid, duplicate_ok, revert_ok, reason
):
    expected_sid = "S-1-5-21-77"
    kernel32, advapi32, events, closed = _fake_pipe_token_apis(
        source_sid=source_sid, duplicate_ok=duplicate_ok, revert_ok=revert_ok
    )
    monkeypatch.setattr(guardian_service.os, "name", "nt")
    monkeypatch.setattr(guardian_service, "_pipe_token_apis", lambda: (kernel32, advapi32))
    monkeypatch.setattr(guardian_service, "_client_pid_from_pipe", lambda _handle: 456)
    monkeypatch.setattr(
        guardian_service,
        "_token_user_sid",
        lambda handle: source_sid if handle == 101 else expected_sid if handle == 202 else "",
    )

    with pytest.raises(guardian_service.GuardianServiceError, match=reason):
        guardian_service._authenticated_pipe_client_primary_token(
            12, expected_client_sid=expected_sid
        )

    assert events[-1] == "revert"
    assert 101 in closed
    if duplicate_ok and source_sid == expected_sid:
        assert 202 in closed


def test_pipe_client_token_revert_failure_fails_stops_before_handle_cleanup(monkeypatch):
    expected_sid = "S-1-5-21-77"
    kernel32, advapi32, events, closed = _fake_pipe_token_apis(
        source_sid=expected_sid, revert_ok=False
    )
    fatal_events = []

    class FatalExit(BaseException):
        pass

    def fail_stop():
        fatal_events.append("fail-stop")
        raise FatalExit()

    monkeypatch.setattr(guardian_service.os, "name", "nt")
    monkeypatch.setattr(guardian_service, "_pipe_token_apis", lambda: (kernel32, advapi32))
    monkeypatch.setattr(guardian_service, "_client_pid_from_pipe", lambda _handle: 456)
    monkeypatch.setattr(
        guardian_service,
        "_token_user_sid",
        lambda handle: expected_sid if handle in (101, 202) else "",
    )
    monkeypatch.setattr(
        guardian_service, "_fail_stop_service_process_after_revert_failure", fail_stop
    )

    with pytest.raises(FatalExit):
        guardian_service._authenticated_pipe_client_primary_token(
            12, expected_client_sid=expected_sid
        )

    assert events[-1] == "revert"
    assert fatal_events == ["fail-stop"]
    # The real process terminates at the failed revert boundary; Python must
    # not continue token-handle cleanup under the uncertain client identity.
    assert closed == []


@pytest.mark.parametrize("revert_result", [False, "raise"])
def test_legacy_pipe_sid_revert_failure_is_process_fatal(monkeypatch, revert_result):
    """Legacy callers cannot catch a failed revert and reuse the service thread."""

    from types import SimpleNamespace

    events = []
    closed = []

    def open_thread_token(_thread, _access, _open_as_self, output):
        guardian_service.ctypes.cast(
            output, guardian_service.ctypes.POINTER(guardian_service.wintypes.HANDLE)
        ).contents.value = 101
        return True

    def revert():
        events.append("revert")
        if revert_result == "raise":
            raise KeyboardInterrupt("simulated RevertToSelf wrapper interruption")
        return bool(revert_result)

    kernel32 = SimpleNamespace(
        GetCurrentThread=_FakeNativeFunction(lambda: 303),
        CloseHandle=_FakeNativeFunction(lambda handle: closed.append(int(handle.value)) or True),
    )
    advapi32 = SimpleNamespace(
        ImpersonateNamedPipeClient=_FakeNativeFunction(
            lambda _handle: events.append("impersonate") or True
        ),
        OpenThreadToken=_FakeNativeFunction(open_thread_token),
        RevertToSelf=_FakeNativeFunction(revert),
    )

    class FatalExit(BaseException):
        pass

    def fail_stop():
        events.append("fail-stop")
        raise FatalExit()

    monkeypatch.setattr(guardian_service.os, "name", "nt")
    monkeypatch.setattr(
        guardian_service.ctypes,
        "WinDLL",
        lambda name, **_kwargs: kernel32 if name == "kernel32" else advapi32,
    )
    monkeypatch.setattr(guardian_service, "_token_user_sid", lambda _handle: "S-1-5-21-77")
    monkeypatch.setattr(
        guardian_service, "_fail_stop_service_process_after_revert_failure", fail_stop
    )

    with pytest.raises(FatalExit):
        guardian_service._impersonated_pipe_client_sid(12)

    assert events == ["impersonate", "revert", "fail-stop"]
    assert closed == [101]


def test_pipe_token_reverts_when_impersonation_wrapper_raises_after_side_effect(monkeypatch):
    sid = "S-1-5-21-77"
    kernel32, advapi32, events, closed = _fake_pipe_token_apis(
        source_sid=sid, impersonate_raise_after_switch=True
    )
    monkeypatch.setattr(guardian_service.os, "name", "nt")
    monkeypatch.setattr(guardian_service, "_pipe_token_apis", lambda: (kernel32, advapi32))
    monkeypatch.setattr(guardian_service, "_client_pid_from_pipe", lambda _handle: 456)

    with pytest.raises(KeyboardInterrupt, match="simulated wrapper interruption"):
        guardian_service._authenticated_pipe_client_primary_token(12, expected_client_sid=sid)

    assert events == ["impersonate", "impersonation_side_effect", "revert"]
    assert closed == []


def test_pipe_client_sid_reverts_even_when_token_close_raises(monkeypatch):
    """A token-handle cleanup exception must not strand service impersonation."""

    from types import SimpleNamespace

    events = []

    def open_thread_token(_thread, _access, _open_as_self, output):
        guardian_service.ctypes.cast(
            output, guardian_service.ctypes.POINTER(guardian_service.wintypes.HANDLE)
        ).contents.value = 101
        return True

    def close_handle(_handle):
        events.append("close-token")
        raise KeyboardInterrupt("simulated close interruption")

    kernel32 = SimpleNamespace(
        GetCurrentThread=_FakeNativeFunction(lambda: 303),
        CloseHandle=_FakeNativeFunction(close_handle),
    )
    advapi32 = SimpleNamespace(
        ImpersonateNamedPipeClient=_FakeNativeFunction(
            lambda _handle: events.append("impersonate") or True
        ),
        OpenThreadToken=_FakeNativeFunction(open_thread_token),
        RevertToSelf=_FakeNativeFunction(lambda: events.append("revert") or True),
    )
    monkeypatch.setattr(guardian_service.os, "name", "nt")
    monkeypatch.setattr(
        guardian_service.ctypes,
        "WinDLL",
        lambda name, **_kwargs: kernel32 if name == "kernel32" else advapi32,
    )
    monkeypatch.setattr(guardian_service, "_token_user_sid", lambda _handle: "S-1-5-21-77")

    with pytest.raises(
        guardian_service.GuardianServiceError, match="pipe_client_token_close_failed"
    ):
        guardian_service._impersonated_pipe_client_sid(12)

    assert events == ["impersonate", "close-token", "revert"]


def test_authenticated_primary_token_close_is_retryable_after_baseexception():
    """A wrapper interruption does not discard ownership of the token handle."""

    from types import SimpleNamespace

    attempts = []

    def close_handle(handle):
        attempts.append(handle.value)
        if len(attempts) == 1:
            raise KeyboardInterrupt("synthetic close interruption")
        return True

    token = guardian_service._AuthenticatedPipeClientToken(
        handle=17,
        client_sid="S-1-5-21-77",
        client_pid=88,
        _kernel32=SimpleNamespace(CloseHandle=close_handle),
    )

    assert token.close() is False
    assert token._closed is False
    assert token.close() is True
    assert token._closed is True
    assert attempts == [17, 17]


@pytest.mark.skipif(os.name != "nt", reason="requires a local anonymous Windows pipe")
def test_real_worker_stdio_pipe_is_nonblocking_and_cap_plus_one_bounded():
    service_sid = guardian_service._current_user_sid()
    kernel32 = guardian_service.ctypes.WinDLL("kernel32", use_last_error=True)

    read_handle, write_handle, null_handle = guardian_service._create_worker_stdio_handles(
        service_sid=service_sid
    )
    output = guardian_service._BoundedWorkerOutput(read_handle, max_bytes=3)
    overflow = None

    def write_bytes(payload):
        native = guardian_service.ctypes.create_string_buffer(payload)
        written = guardian_service.wintypes.DWORD()
        function = kernel32.WriteFile
        function.argtypes = [
            guardian_service.wintypes.HANDLE,
            guardian_service.wintypes.LPVOID,
            guardian_service.wintypes.DWORD,
            guardian_service.ctypes.POINTER(guardian_service.wintypes.DWORD),
            guardian_service.wintypes.LPVOID,
        ]
        function.restype = guardian_service.wintypes.BOOL
        assert function(
            guardian_service.wintypes.HANDLE(write_handle),
            native,
            len(payload),
            guardian_service.ctypes.byref(written),
            None,
        )
        assert written.value == len(payload)

    try:
        assert guardian_service._native_handle_value(null_handle) > 0
        write_bytes(b"abc")
        assert output.poll_abort_reason() is None
        assert len(output._buffer) == 3
        assert output.poll_abort_reason() is None
        assert kernel32.CloseHandle(guardian_service.wintypes.HANDLE(write_handle))
        write_handle = 0
        assert output.read_after_job_empty(deadline_monotonic=time.monotonic() + 2.0) == b"abc"
        assert output.close() is True
        assert kernel32.CloseHandle(guardian_service.wintypes.HANDLE(null_handle))
        null_handle = 0

        overflow_read, overflow_write, overflow_null = (
            guardian_service._create_worker_stdio_handles(service_sid=service_sid)
        )
        overflow = guardian_service._BoundedWorkerOutput(overflow_read, max_bytes=3)
        write_handle = overflow_write
        null_handle = overflow_null
        write_bytes(b"abcd")
        assert overflow.poll_abort_reason() == "worker_output_limit_exceeded"
        assert len(overflow._buffer) == 4
        assert overflow.close() is True
    finally:
        if overflow is not None:
            overflow.close()
        if write_handle:
            kernel32.CloseHandle(guardian_service.wintypes.HANDLE(write_handle))
        if null_handle:
            kernel32.CloseHandle(guardian_service.wintypes.HANDLE(null_handle))


def test_readonly_worker_output_requires_exact_redacted_fact_shapes():
    """Unknown nested worker fields cannot enter the receipt projection."""

    account = dict.fromkeys(guardian_service._READONLY_ACCOUNT_FACT_FIELDS)
    account.update(
        {
            "account_scope": "redacted",
            "account_acceptance_established": False,
            "approval_required": False,
            "read_only_route_admitted": True,
            "session_connected": True,
            "provider_preflight_started": True,
            "external_write_requests": 0,
            "connection_generation": 1,
            "effective_config_digest": "2" * 64,
            "environment": "simnow",
            "exchange_id": "DCE",
            "hedge_flag": "1",
            "instrument_id": "i2601",
            "native_certificate_provenance": "LOCAL_ONLY",
            "native_certificate_sha256": None,
            "provider": "ctp",
            "registration_digest": "3" * 64,
            "runtime_id": "example.013_3.sa_midfreq_simnow.ctp_private",
            "sdk_profile": "config_front_pair",
            "strategy_id": "example.013_3.sa_midfreq_simnow",
            "trading_day": "20260926",
            "arming_authorized": False,
            "cancellation_authorized": False,
            "execution_authorized": False,
            "external_writes_authorized": False,
            "order_submission_authorized": False,
            "settlement_authorized": False,
            "query_snapshot": {
                "identity": {
                    "account_scope": "redacted",
                    "connection_generation": 1,
                    "environment": "simnow",
                    "provider": "ctp",
                    "trading_day": "20260926",
                },
                "query_digests": [
                    [name, "4" * 64] for name in sorted(guardian_service._READONLY_QUERY_NAMES)
                ],
                "snapshot_sha256": "0" * 64,
            },
        }
    )
    snapshot = account["query_snapshot"]
    snapshot_payload = {
        "identity": snapshot["identity"],
        "query_digests": snapshot["query_digests"],
    }
    snapshot["snapshot_sha256"] = hashlib.sha256(
        json.dumps(
            snapshot_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    market = dict.fromkeys(guardian_service._READONLY_MARKET_FACT_FIELDS)
    market.update(
        {
            "client_stop_returned": True,
            "connection_generation": 1,
            "account_probe_lock_scope": "cooperating_probe_invocations_only",
            "account_scope_bound": True,
            "exchange_id": "DCE",
            "first_tick_observed": True,
            "instrument_id": "i2601",
            "market_login_ready": True,
            "market_path_ready": True,
            "md_front_sha256": "1" * 64,
            "native_join_pending": False,
            "order_submission_authorized": False,
            "probe_session_closed": True,
            "subscription_acknowledged": True,
            "settlement_writes": 0,
            "tick_binding": {
                "account_bound": True,
                "connection_generation": 1,
                "exchange_id": "DCE",
                "instrument_id": "i2601",
                "md_front_sha256": "1" * 64,
            },
            "tick_observation_count": 1,
            "trading_writes": 0,
        }
    )
    top = {
        "credentials_resolved": True,
        "provider_connected": False,
        "account_identity_verified": False,
        "preflight_authorized": False,
        "execution_authorized": False,
        "external_writes_authorized": False,
        "order_submission_authorized": False,
        "cancellation_authorized": False,
        "settlement_authorized": False,
        "arming_authorized": False,
        "external_write_requests": 0,
        "market_data_trading_writes": 0,
        "read_only_observation": account,
        "market_data_observation": market,
    }

    def encode(observation):
        return json.dumps(
            {"schema": guardian_service.READONLY_WORKER_SCHEMA, "observation": observation},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")

    assert guardian_service._decode_readonly_worker_output(encode(top)) == top
    account["unexpected"] = "should-not-enter-receipt"
    with pytest.raises(
        guardian_service.GuardianServiceError, match="worker_observation_facts_invalid"
    ):
        guardian_service._decode_readonly_worker_output(encode(top))

    account.pop("unexpected")
    account["query_snapshot"]["query_digests"][0] = ["password", "synthetic-secret-marker"]
    with pytest.raises(
        guardian_service.GuardianServiceError, match="worker_observation_facts_invalid"
    ):
        guardian_service._decode_readonly_worker_output(encode(top))

    account["query_snapshot"]["query_digests"] = [
        [name, "4" * 64] for name in sorted(guardian_service._READONLY_QUERY_NAMES)
    ]
    account["query_snapshot"]["snapshot_sha256"] = "not-a-digest"
    with pytest.raises(
        guardian_service.GuardianServiceError, match="worker_observation_facts_invalid"
    ):
        guardian_service._decode_readonly_worker_output(encode(top))

    account["query_snapshot"]["snapshot_sha256"] = "0" * 64
    with pytest.raises(
        guardian_service.GuardianServiceError, match="worker_observation_facts_invalid"
    ):
        guardian_service._decode_readonly_worker_output(encode(top))

    snapshot_payload = {
        "identity": account["query_snapshot"]["identity"],
        "query_digests": account["query_snapshot"]["query_digests"],
    }
    account["query_snapshot"]["snapshot_sha256"] = hashlib.sha256(
        json.dumps(
            snapshot_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    account["runtime_id"] = "synthetic-secret-marker"
    with pytest.raises(
        guardian_service.GuardianServiceError, match="worker_observation_facts_invalid"
    ):
        guardian_service._decode_readonly_worker_output(encode(top))

    account["runtime_id"] = "example.013_3.sa_midfreq_simnow.ctp_private"
    account["hedge_flag"] = "synthetic-secret-marker"
    with pytest.raises(
        guardian_service.GuardianServiceError, match="worker_observation_facts_invalid"
    ):
        guardian_service._decode_readonly_worker_output(encode(top))


@pytest.mark.skipif(os.name != "nt", reason="CreateNamedPipe argument test requires Windows")
def test_restricted_listener_passes_remote_rejection_in_pipe_mode(monkeypatch) -> None:
    """Pin PIPE_REJECT_REMOTE_CLIENTS to CreateNamedPipe's dwPipeMode slot."""

    import ctypes
    from types import SimpleNamespace

    calls = []
    attributes = ctypes.create_string_buffer(1)
    security_descriptor = ctypes.c_void_p(1)

    class FakeWinAPI:
        PIPE_ACCESS_DUPLEX = 0x00000003
        FILE_FLAG_OVERLAPPED = 0x40000000
        FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
        PIPE_TYPE_MESSAGE = 0x00000004
        PIPE_READMODE_MESSAGE = 0x00000002
        PIPE_WAIT = 0x00000000
        PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
        NMPWAIT_WAIT_FOREVER = 0xFFFFFFFF

        @staticmethod
        def CreateNamedPipe(*args):
            calls.append(args)
            return 123

    class FakeKernel32:
        @staticmethod
        def LocalFree(value):
            return None

    listener = object.__new__(guardian_service._RestrictedPipeListener)
    listener._winapi = FakeWinAPI
    listener._connection_module = SimpleNamespace(BUFSIZE=8192)
    listener._address = r"\\.\pipe\test"
    monkeypatch.setattr(
        guardian_service,
        "_create_pipe_security_attributes",
        lambda **_kwargs: (attributes, security_descriptor),
    )
    listener._service_sid = "S-1-5-21-7"
    listener._expected_client_sid = listener._service_sid
    monkeypatch.setattr(guardian_service.ctypes, "WinDLL", lambda *args, **kwargs: FakeKernel32)

    assert listener._new_handle(first=True) == 123
    assert len(calls) == 1
    assert calls[0][2] & FakeWinAPI.PIPE_REJECT_REMOTE_CLIENTS
    assert (calls[0][1] & FakeWinAPI.PIPE_REJECT_REMOTE_CLIENTS) == 0
    assert calls[0][3] == 2


@pytest.mark.parametrize(
    ("client_sid", "client_pids", "reason"),
    [
        ("S-1-5-18", (41, 41), "pipe_client_identity_mismatch"),
        ("S-1-5-21-7", (41, 42), "pipe_client_pid_changed"),
    ],
)
def test_restricted_listener_rejects_changed_client_identity(
    monkeypatch, client_sid: str, client_pids: tuple[int, int], reason: str
) -> None:
    """The listener rejects a wrong impersonated SID or a changed pipe PID."""

    from types import SimpleNamespace

    class FakeOverlapped:
        event = object()

        @staticmethod
        def GetOverlappedResult(wait):
            return 0, 0

    class FakeConnection:
        def __init__(self, handle: int) -> None:
            self.handle = handle
            self.closed = False

        def fileno(self) -> int:
            return 73

        def close(self) -> None:
            self.closed = True

    class FakeConnectionModule:
        BUFSIZE = 8192

        def __init__(self) -> None:
            self.connection = FakeConnection(17)
            self.server_challenge_calls = []

        def PipeConnection(self, handle: int):
            assert handle == 17
            return self.connection

        @staticmethod
        def deliver_challenge(connection, auth_key) -> None:
            assert connection is not None
            assert auth_key == b"test-auth-key"

        def answer_challenge(self, connection, auth_key) -> None:
            self.server_challenge_calls.append((connection, auth_key))

    fake_api = SimpleNamespace(
        ERROR_NO_DATA=232,
        ConnectNamedPipe=lambda handle, overlapped: FakeOverlapped(),
        WaitForMultipleObjects=lambda *args: 0,
        CloseHandle=lambda handle: None,
    )
    connection_module = FakeConnectionModule()
    listener = object.__new__(guardian_service._RestrictedPipeListener)
    listener._winapi = fake_api
    listener._connection_module = connection_module
    listener._address = r"\\.\pipe\test"
    listener._auth_key = b"test-auth-key"
    listener._expected_client_sid = "S-1-5-21-7"
    listener._handle_queue = [17]
    listener._closed = False
    listener._new_handle = lambda *, first: 18
    pid_results = iter(client_pids)
    monkeypatch.setattr(guardian_service, "_client_pid_from_pipe", lambda handle: next(pid_results))
    monkeypatch.setattr(
        guardian_service, "_impersonated_pipe_client_sid", lambda handle: client_sid
    )

    with pytest.raises(guardian_service.GuardianServiceError, match=reason):
        listener.accept()

    assert connection_module.connection.closed
    assert connection_module.server_challenge_calls == []
    listener.close()


@pytest.mark.skipif(
    os.name != "nt" or sys.getwindowsversion().major < 10,
    reason="the request-message identity contract requires Windows named pipes",
)
def test_service_rechecks_client_sid_on_request_message(tmp_path: Path) -> None:
    """Reject a different SID on the request even after a valid HMAC handshake."""

    from multiprocessing import connection as mp_connection

    repo_root = Path(__file__).resolve().parents[3]
    receipt_root = tmp_path / "request-identity-receipt-root"
    receipt_root.mkdir()
    address = rf"\\.\pipe\backtrader-ctp-i13-i15-{uuid.uuid4().hex}"
    auth_key = os.urandom(32)
    ready_path = tmp_path / "request-identity-ready.json"
    status_path = tmp_path / "request-identity-status.txt"
    service_script = tmp_path / "request_identity_service.py"
    service_script.write_text(
        "\n".join(
            [
                "import json, sys",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(repo_root)!r})",
                "import scripts.ctp_i13_i15_windows_guardian_service as service_module",
                "from scripts.ctp_i13_i15_windows_guardian_service import serve_one_inert_request",
                "address, key_hex, executable, executable_hash, receipt_root, ready_path, status_path = sys.argv[1:]",
                "identities = iter((service_module._current_user_sid(), 'S-1-5-18'))",
                "service_module._impersonated_pipe_client_sid = lambda handle: next(identities)",
                "def ready(address, pid): Path(ready_path).write_text(json.dumps({'address': address, 'pid': pid}), encoding='ascii')",
                "result = serve_one_inert_request(address=address, auth_key=bytes.fromhex(key_hex), python_executable=executable, python_sha256=executable_hash, receipt_root=receipt_root, ready=ready, accept_timeout_seconds=8.0)",
                "Path(status_path).write_text(result, encoding='ascii')",
            ]
        ),
        encoding="utf-8",
    )
    python_executable = str(Path(sys.executable).resolve())
    python_hash = hashlib.sha256(Path(python_executable).read_bytes()).hexdigest()
    service = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(service_script),
            address,
            auth_key.hex(),
            python_executable,
            python_hash,
            str(receipt_root),
            str(ready_path),
            str(status_path),
        ],
        cwd=str(repo_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    connection = None
    try:
        _wait_for_file(ready_path, service)
        ready = json.loads(ready_path.read_text(encoding="ascii"))
        assert ready["address"] == address
        connection = mp_connection.Client(address, authkey=auth_key)
        assert guardian_service._server_pid_from_pipe(connection.fileno()) == ready["pid"]
        connection.send_bytes(b"not-json")
        connection.close()
        connection = None

        _wait_for_file(status_path, service, timeout=8.0)
        service.wait(timeout=5.0)
        assert status_path.read_text(encoding="ascii") == "service_request_identity_mismatch"
        assert not (receipt_root / "guardian-receipt.json").exists()
    finally:
        if connection is not None:
            connection.close()
        if service.poll() is None:
            service.kill()
            service.wait(timeout=5.0)


@pytest.mark.skipif(
    os.name != "nt" or sys.getwindowsversion().major < 10,
    reason="the pipe DACL contract requires Windows named pipes",
)
def test_live_pipe_dacl_is_current_user_only_and_unauthenticated_client_is_rejected(
    tmp_path: Path,
) -> None:
    """Read back the live pipe DACL, then disconnect before HMAC completes."""

    import ctypes
    from ctypes import wintypes
    from multiprocessing import connection as mp_connection

    repo_root = Path(__file__).resolve().parents[3]
    receipt_root = tmp_path / "acl-receipt-root"
    receipt_root.mkdir()
    address = rf"\\.\pipe\backtrader-ctp-i13-i15-{uuid.uuid4().hex}"
    auth_key = os.urandom(32)
    ready_path = tmp_path / "acl-service-ready.json"
    status_path = tmp_path / "acl-service-status.txt"
    accept_error_path = tmp_path / "acl-service-accept-error.txt"
    service_script = tmp_path / "acl_service.py"
    service_script.write_text(
        "\n".join(
            [
                "import json, sys",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(repo_root)!r})",
                "from scripts.ctp_i13_i15_windows_guardian_service import serve_one_inert_request",
                "address, key_hex, executable, executable_hash, receipt_root, ready_path, status_path, accept_error_path = sys.argv[1:]",
                "import scripts.ctp_i13_i15_windows_guardian_service as service_module",
                "original_accept = service_module._RestrictedPipeListener.accept",
                "def record_accept_error(listener):",
                "    try: return original_accept(listener)",
                "    except BaseException as error:",
                "        Path(accept_error_path).write_text(type(error).__name__ + ':' + str(getattr(error, 'winerror', '')), encoding='ascii')",
                "        raise",
                "service_module._RestrictedPipeListener.accept = record_accept_error",
                "def ready(address, pid): Path(ready_path).write_text(json.dumps({'address': address, 'pid': pid}), encoding='ascii')",
                "status = serve_one_inert_request(address=address, auth_key=bytes.fromhex(key_hex), python_executable=executable, python_sha256=executable_hash, receipt_root=receipt_root, ready=ready, accept_timeout_seconds=8.0)",
                "Path(status_path).write_text(status, encoding='ascii')",
            ]
        ),
        encoding="utf-8",
    )
    python_executable = str(Path(sys.executable).resolve())
    python_hash = hashlib.sha256(Path(python_executable).read_bytes()).hexdigest()
    service = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(service_script),
            address,
            auth_key.hex(),
            python_executable,
            python_hash,
            str(receipt_root),
            str(ready_path),
            str(status_path),
            str(accept_error_path),
        ],
        cwd=str(repo_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    connection = None
    try:
        _wait_for_file(ready_path, service)
        ready = json.loads(ready_path.read_text(encoding="ascii"))
        assert ready["address"] == address

        try:
            connection = mp_connection.PipeClient(address)
        except OSError:
            deadline = time.monotonic() + 2.0
            while not accept_error_path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            if accept_error_path.exists():
                pytest.fail(
                    "named pipe accept failed: " + accept_error_path.read_text(encoding="ascii")
                )
            raise
        assert guardian_service._server_pid_from_pipe(connection.fileno()) == ready["pid"]

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_security_info = advapi32.GetSecurityInfo
        get_security_info.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.LPVOID),
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.LPVOID),
        ]
        get_security_info.restype = wintypes.DWORD
        convert_to_sddl = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
        convert_to_sddl.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(wintypes.DWORD),
        ]
        convert_to_sddl.restype = wintypes.BOOL
        local_free = kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL
        dacl = wintypes.LPVOID()
        security_descriptor = wintypes.LPVOID()
        status = get_security_info(
            wintypes.HANDLE(connection.fileno()),
            6,  # SE_KERNEL_OBJECT
            0x00000004 | 0x80000000,  # DACL_SECURITY_INFORMATION | PROTECTED_DACL
            None,
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(security_descriptor),
        )
        assert status == 0
        sddl = wintypes.LPWSTR()
        length = wintypes.DWORD()
        try:
            assert convert_to_sddl(
                security_descriptor,
                1,
                0x00000004 | 0x80000000,
                ctypes.byref(sddl),
                ctypes.byref(length),
            )
            actual_sddl = sddl.value
        finally:
            if sddl:
                local_free(wintypes.HLOCAL(ctypes.cast(sddl, wintypes.HLOCAL).value))
            if security_descriptor:
                local_free(wintypes.HLOCAL(security_descriptor.value))

        expected = "D:P(A;;FA;;;{})".format(guardian_service._current_user_sid())
        assert actual_sddl == expected
        assert guardian_service._PIPE_REJECT_REMOTE_CLIENTS == 0x00000008

        # Closing without answering the challenge is a real process-level
        # negative case: the server must reject it before accepting a request.
        connection.close()
        connection = None
        _wait_for_file(status_path, service, timeout=8.0)
        service.wait(timeout=5.0)
        assert status_path.read_text(encoding="ascii") == "service_accept_failed"
        assert not (receipt_root / "guardian-receipt.json").exists()
    finally:
        if connection is not None:
            connection.close()
        if service.poll() is None:
            service.kill()
            service.wait(timeout=5.0)


def test_fixed_readonly_command_uses_only_the_sealed_bootstrap(monkeypatch):
    """The child command is fixed and the env binding only repeats anchor facts."""

    from types import SimpleNamespace

    bootstrap = b"# synthetic pinned bootstrap\n"
    bootstrap_sha = hashlib.sha256(bootstrap).hexdigest()
    dependency_root = r"C:\Program Files\Python311\Lib\site-packages"
    calls = []
    dependency_seal = SimpleNamespace(
        manifest_sha256="7" * 64,
        dependency_root=dependency_root,
        verify_current=lambda: calls.append("dependency_verify"),
        close=lambda: None,
    )
    anchor = SimpleNamespace(
        source_root=r"C:\ProgramData\Backtrader\Iteration41\source",
        source_manifest_sha256="1" * 64,
        descriptor_sha256="2" * 64,
        python_executable=r"C:\Python311\python.exe",
        python_sha256="3" * 64,
        i13_pin_sha256="4" * 64,
        i15_pin_sha256="5" * 64,
        worker_sha256="6" * 64,
        worker_dependency_manifest_sha256="7" * 64,
        runtime_manifest_sha256="8" * 64,
        dependency_root=dependency_root,
        dependency_seal=dependency_seal,
        pycache_prefix=r"C:\Python311\disabled-bytecode-cache",
        bootstrap_relative_path=("scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"),
        bootstrap_sha256=bootstrap_sha,
        read_bootstrap_source=lambda: bootstrap,
        verify_current=lambda: calls.append("source_verify"),
        verify_dependencies_current=lambda: calls.append("anchor_dependency_verify"),
    )
    monkeypatch.setattr(guardian_service, "_windows_system_root", lambda: r"C:\Windows")

    command = guardian_service._fixed_readonly_worker_command(anchor, deadline_monotonic=123.456789)

    assert command.argv == (
        r"C:\Python311\python.exe",
        "-I",
        "-S",
        "-B",
        "-X",
        r"pycache_prefix=C:\Python311\disabled-bytecode-cache",
        r"C:\ProgramData\Backtrader\Iteration41\source\scripts\ctp_i13_i15_readonly_preflight_bootstrap.py",
    )
    assert "-c" not in command.argv
    assert set(command.env) == {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        guardian_service.READONLY_BOOTSTRAP_BINDING_ENV,
    }
    binding = json.loads(command.env[guardian_service.READONLY_BOOTSTRAP_BINDING_ENV])
    assert set(binding) == {
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
    }
    assert binding["schema"] == guardian_service.READONLY_BOOTSTRAP_BINDING_SCHEMA
    assert binding["deadline_monotonic_ns"] == 123456789000
    assert all("path" not in key and "root" not in key for key in binding)
    assert calls == ["source_verify"]


def test_fixed_readonly_command_rejects_unsealed_dependency_binding(monkeypatch):
    """No caller-constructed root/hash can substitute for a retained seal."""

    from types import SimpleNamespace

    bootstrap = b"fixed"
    digest = hashlib.sha256(bootstrap).hexdigest()
    anchor = SimpleNamespace(
        source_root=r"C:\trusted\source",
        source_manifest_sha256="1" * 64,
        descriptor_sha256="2" * 64,
        python_executable=r"C:\Python311\python.exe",
        python_sha256="3" * 64,
        i13_pin_sha256="4" * 64,
        i15_pin_sha256="5" * 64,
        worker_sha256="6" * 64,
        worker_dependency_manifest_sha256="7" * 64,
        runtime_manifest_sha256="8" * 64,
        dependency_root=r"C:\Python311\Lib\site-packages",
        dependency_seal=None,
        pycache_prefix=r"C:\Python311\disabled-bytecode-cache",
        bootstrap_relative_path=guardian_service._FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH,
        bootstrap_sha256=digest,
        read_bootstrap_source=lambda: bootstrap,
        verify_current=lambda: None,
        verify_dependencies_current=lambda: None,
    )
    monkeypatch.setattr(guardian_service, "_windows_system_root", lambda: r"C:\Windows")

    with pytest.raises(
        guardian_service.GuardianServiceError,
        match="readonly_bootstrap_binding_invalid",
    ):
        guardian_service._fixed_readonly_worker_command(anchor, deadline_monotonic=123.0)


def test_fixed_readonly_command_has_a_hard_bootstrap_source_size_cap(monkeypatch):
    """The deterministic sealer artifact may be large but remains bounded."""

    from types import SimpleNamespace

    bootstrap = b"x" * (256 * 1024 + 1)
    dependency_root = r"C:\Python311\Lib\site-packages"
    digest = hashlib.sha256(bootstrap).hexdigest()
    anchor = SimpleNamespace(
        source_root=r"C:\trusted\source",
        source_manifest_sha256="1" * 64,
        descriptor_sha256="2" * 64,
        python_executable=r"C:\Python311\python.exe",
        python_sha256="3" * 64,
        i13_pin_sha256="4" * 64,
        i15_pin_sha256="5" * 64,
        worker_sha256="6" * 64,
        worker_dependency_manifest_sha256="7" * 64,
        runtime_manifest_sha256="8" * 64,
        dependency_root=dependency_root,
        pycache_prefix=r"C:\Python311\disabled-bytecode-cache",
        dependency_seal=SimpleNamespace(
            manifest_sha256="7" * 64,
            dependency_root=dependency_root,
            verify_current=lambda: None,
            close=lambda: None,
        ),
        bootstrap_relative_path=guardian_service._FIXED_READONLY_BOOTSTRAP_RELATIVE_PATH,
        bootstrap_sha256=digest,
        read_bootstrap_source=lambda: bootstrap,
        verify_current=lambda: None,
    )
    monkeypatch.setattr(guardian_service, "_windows_system_root", lambda: r"C:\Windows")

    with pytest.raises(
        guardian_service.GuardianServiceError,
        match="readonly_bootstrap_source_size_invalid",
    ):
        guardian_service._fixed_readonly_worker_command(anchor, deadline_monotonic=123.0)


def test_readonly_service_identity_is_fixed_name_and_enabled_token_group():
    service_sid = "S-1-5-80-1-2-3-4-5"

    assert (
        guardian_service._validate_fixed_service_sid(
            guardian_service.FIXED_READONLY_SERVICE_NAME, service_sid
        )
        == service_sid
    )
    with pytest.raises(guardian_service.GuardianServiceError, match="service_sid_binding_invalid"):
        guardian_service._validate_fixed_service_sid("CallerSelectedService", service_sid)
    with pytest.raises(guardian_service.GuardianServiceError, match="service_sid_binding_invalid"):
        guardian_service._validate_fixed_service_sid(
            guardian_service.FIXED_READONLY_SERVICE_NAME, "S-1-5-21-1-2-3-4"
        )

    assert guardian_service._has_enabled_service_sid(
        ((service_sid, guardian_service._SE_GROUP_ENABLED),),
        service_name=guardian_service.FIXED_READONLY_SERVICE_NAME,
        service_sid=service_sid,
    )
    assert not guardian_service._has_enabled_service_sid(
        ((service_sid, 0),),
        service_name=guardian_service.FIXED_READONLY_SERVICE_NAME,
        service_sid=service_sid,
    )
    assert not guardian_service._has_enabled_service_sid(
        (
            (
                service_sid,
                guardian_service._SE_GROUP_ENABLED | guardian_service._SE_GROUP_USE_FOR_DENY_ONLY,
            ),
        ),
        service_name=guardian_service.FIXED_READONLY_SERVICE_NAME,
        service_sid=service_sid,
    )
    assert not guardian_service._has_enabled_service_sid(
        (
            (service_sid, guardian_service._SE_GROUP_ENABLED),
            (service_sid, guardian_service._SE_GROUP_ENABLED),
        ),
        service_name=guardian_service.FIXED_READONLY_SERVICE_NAME,
        service_sid=service_sid,
    )


def test_readonly_pipe_dacl_and_client_access_exclude_create_pipe_instance(monkeypatch):
    service_sid = "S-1-5-80-1-2-3-4-5"
    client_sid = "S-1-5-21-11-22-33-44"
    monkeypatch.setattr(
        guardian_service,
        "_service_sid_from_name",
        lambda service_name: (
            service_sid
            if service_name == guardian_service.FIXED_READONLY_SERVICE_NAME
            else pytest.fail("service name was not fixed")
        ),
    )

    mask = guardian_service._readonly_pipe_client_access_mask()
    sddl = guardian_service._readonly_pipe_sddl(service_sid=service_sid, client_sid=client_sid)

    assert mask == 0x00120183
    assert mask & guardian_service._FILE_APPEND_DATA == 0
    assert mask & guardian_service._GENERIC_WRITE == 0
    assert "(A;;GA;;;{})".format(service_sid) in sddl
    assert "(A;;0x00120183;;;{})".format(client_sid) in sddl
    assert "(A;;GA;;;{})".format(client_sid) not in sddl

    with pytest.raises(guardian_service.GuardianServiceError, match="service_sid_binding_mismatch"):
        monkeypatch.setattr(guardian_service, "_service_sid_from_name", lambda _name: service_sid)
        guardian_service._readonly_pipe_sddl(
            service_sid="S-1-5-80-5-4-3-2-1", client_sid=client_sid
        )


@pytest.mark.parametrize(
    ("service_type", "current_state", "process_id", "expected_pid", "accepted"),
    [
        (0x10, 4, 812, 812, True),
        (0x20, 4, 812, 812, False),
        (0x10, 1, 812, 812, False),
        (0x10, 4, 813, 812, False),
    ],
)
def test_fixed_scm_identity_requires_running_own_process_pid(
    service_type, current_state, process_id, expected_pid, accepted
):
    verify = guardian_service._validate_fixed_scm_status
    values = {
        "service_name": guardian_service.FIXED_READONLY_SERVICE_NAME,
        "service_type": service_type,
        "current_state": current_state,
        "process_id": process_id,
        "expected_pid": expected_pid,
    }
    if accepted:
        verify(**values)
    else:
        with pytest.raises(
            guardian_service.GuardianServiceError, match="service_scm_identity_mismatch"
        ):
            verify(**values)


def test_readonly_pipe_client_uses_specific_noncreating_access(monkeypatch):
    from types import SimpleNamespace

    calls = {}

    def wait_named_pipe(address, timeout):
        calls["wait"] = (address, timeout)
        return 1

    def create_file(*args):
        calls["create_file"] = args
        return 712

    def set_mode(handle, mode, _max_collection, _collection_timeout):
        calls["set_mode"] = (handle.value, mode._obj.value)
        return 1

    def close_handle(_handle):
        return 1

    fake_kernel32 = SimpleNamespace(
        WaitNamedPipeW=wait_named_pipe,
        CreateFileW=create_file,
        SetNamedPipeHandleState=set_mode,
        CloseHandle=close_handle,
    )
    for function in vars(fake_kernel32).values():
        function.argtypes = None
        function.restype = None
    monkeypatch.setattr(guardian_service, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(guardian_service.ctypes, "WinDLL", lambda *_a, **_k: fake_kernel32)

    handle = guardian_service._open_readonly_pipe_client_handle(
        r"\\.\pipe\backtrader-ctp-i13-i15-0123456789abcdef0123456789abcdef",
        timeout_ms=321,
    )

    assert handle == 712
    assert calls["wait"][1] == 321
    assert calls["create_file"][1] == 0x00120183
    assert calls["create_file"][1] & guardian_service._FILE_APPEND_DATA == 0
    assert calls["create_file"][1] & guardian_service._GENERIC_WRITE == 0
    assert calls["create_file"][5] == 0x40000000
    assert calls["set_mode"] == (712, 2)


def test_readonly_pipe_server_uses_first_instance_and_remote_rejection(monkeypatch):
    import ctypes
    from types import SimpleNamespace

    service_sid = "S-1-5-80-1-2-3-4-5"
    client_sid = "S-1-5-21-11-22-33-44"
    calls = []
    attributes = guardian_service._SECURITY_ATTRIBUTES(
        ctypes.sizeof(guardian_service._SECURITY_ATTRIBUTES), ctypes.c_void_p(91), False
    )
    descriptor = ctypes.c_void_p(91)

    def create_pipe(*args):
        calls.append(args)
        return 713

    def local_free(_value):
        return None

    fake_kernel32 = SimpleNamespace(CreateNamedPipeW=create_pipe, LocalFree=local_free)
    for function in vars(fake_kernel32).values():
        function.argtypes = None
        function.restype = None
    monkeypatch.setattr(guardian_service, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(guardian_service.ctypes, "WinDLL", lambda *_a, **_k: fake_kernel32)
    monkeypatch.setattr(
        guardian_service,
        "_service_sid_from_name",
        lambda name: (
            service_sid
            if name == guardian_service.FIXED_READONLY_SERVICE_NAME
            else pytest.fail("service name was not fixed")
        ),
    )
    monkeypatch.setattr(
        guardian_service,
        "_create_readonly_pipe_security_attributes",
        lambda **_kwargs: (attributes, descriptor),
    )

    handle = guardian_service._create_readonly_pipe_server_handle(
        r"\\.\pipe\backtrader-ctp-i13-i15-0123456789abcdef0123456789abcdef",
        service_sid=service_sid,
        client_sid=client_sid,
    )

    assert handle == 713
    assert len(calls) == 1
    assert calls[0][1] == 0x00000003 | 0x40000000 | 0x00080000
    assert calls[0][2] == 0x00000004 | 0x00000002 | guardian_service._PIPE_REJECT_REMOTE_CLIENTS
    assert calls[0][3] == 1
    assert calls[0][7]._obj is attributes


def test_retained_server_process_rechecks_pid_creation_and_scm_binding(monkeypatch):
    from types import SimpleNamespace

    service_sid = "S-1-5-80-1-2-3-4-5"
    binding = object.__new__(guardian_service._RetainedReadonlyServerProcess)
    binding.handle = 92
    binding.pid = 812
    binding.creation_filetime = 123456
    binding.service_sid = service_sid
    binding.python_executable = r"C:\Runtime\python.exe"
    binding.executable_lease = SimpleNamespace(verify_current=lambda: None)
    binding._kernel32 = object()
    binding._closed = False
    facts = []
    monkeypatch.setattr(guardian_service, "_server_pid_from_pipe", lambda _handle: 812)
    monkeypatch.setattr(guardian_service, "_process_id_from_handle", lambda _handle: 812)
    monkeypatch.setattr(guardian_service, "_process_is_live", lambda _handle: True)
    monkeypatch.setattr(
        guardian_service,
        "_process_has_service_sid",
        lambda _handle, sid: sid == service_sid,
    )
    monkeypatch.setattr(
        guardian_service, "_process_image_path", lambda _handle: r"c:\runtime\python.exe"
    )
    monkeypatch.setattr(guardian_service, "_query_fixed_scm_status", lambda: (0x10, 4, 812))
    monkeypatch.setattr(
        guardian_service,
        "_validate_fixed_scm_status",
        lambda **kwargs: facts.append(kwargs),
    )
    monkeypatch.setattr(guardian_service, "_process_creation_filetime", lambda _handle: 123456)

    binding.verify(34)

    assert len(facts) == 1
    assert facts[0]["service_name"] == guardian_service.FIXED_READONLY_SERVICE_NAME
    assert facts[0]["expected_pid"] == 812

    monkeypatch.setattr(guardian_service, "_server_pid_from_pipe", lambda _handle: 813)
    with pytest.raises(
        guardian_service.GuardianServiceError, match="service_process_identity_mismatch"
    ):
        binding.verify(34)


def test_readonly_pipe_service_sid_must_match_local_fixed_name(monkeypatch):
    descriptor_sid = "S-1-5-80-1-2-3-4-5"
    monkeypatch.setattr(
        guardian_service,
        "_service_sid_from_name",
        lambda name: (
            descriptor_sid
            if name == "BacktraderCtpReadonlyGuardian"
            else pytest.fail("service name was not fixed")
        ),
    )

    assert guardian_service._bind_service_sid(descriptor_sid) == descriptor_sid
    with pytest.raises(guardian_service.GuardianServiceError, match="service_sid_binding_mismatch"):
        guardian_service._bind_service_sid("S-1-5-80-5-4-3-2-1")


@pytest.mark.skipif(os.name != "nt", reason="real named-pipe API smoke requires Windows")
def test_windows_limited_pipe_client_access_and_server_pid_smoke():
    """Exercise actual CreateFileW rights and server PID lookup on a temp pipe."""

    import ctypes
    from ctypes import wintypes

    address = r"\\.\pipe\backtrader-ctp-i13-i15-{}".format(uuid.uuid4().hex)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    user_sid = guardian_service._current_user_sid()
    convert_sddl = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert_sddl.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert_sddl.restype = wintypes.BOOL
    descriptor = wintypes.LPVOID()
    # Test-only ACL: the current account can create this throwaway pipe; the
    # production builder separately asserts a service-only create right.
    sddl = "D:P(A;;GA;;;{})(A;;0x00120183;;;{})".format(user_sid, user_sid)
    assert convert_sddl(sddl, 1, ctypes.byref(descriptor), None)
    attributes = guardian_service._SECURITY_ATTRIBUTES(
        ctypes.sizeof(guardian_service._SECURITY_ATTRIBUTES), descriptor, False
    )
    create_pipe = kernel32.CreateNamedPipeW
    create_pipe.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(guardian_service._SECURITY_ATTRIBUTES),
    ]
    create_pipe.restype = wintypes.HANDLE
    server_handle = create_pipe(
        address,
        0x00000003 | 0x40000000 | 0x00080000,
        0x00000004 | 0x00000002 | guardian_service._PIPE_REJECT_REMOTE_CLIENTS,
        1,
        guardian_service._MAX_MESSAGE_BYTES,
        guardian_service._MAX_MESSAGE_BYTES,
        0,
        ctypes.byref(attributes),
    )
    kernel32.LocalFree(descriptor)
    server_value = guardian_service._native_handle_value(server_handle)
    assert server_value not in (0, ctypes.c_void_p(-1).value)

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    create_event = kernel32.CreateEventW
    create_event.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    create_event.restype = wintypes.HANDLE
    event = create_event(None, True, False, None)
    assert event
    overlapped = OVERLAPPED()
    overlapped.hEvent = event
    connect = kernel32.ConnectNamedPipe
    connect.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
    connect.restype = wintypes.BOOL
    connect_results = []

    def wait_for_client():
        connected = bool(connect(wintypes.HANDLE(server_value), ctypes.byref(overlapped)))
        error = 0 if connected else ctypes.get_last_error()
        if not connected and error == 997:
            waited = kernel32.WaitForSingleObject(wintypes.HANDLE(event), 5000)
            connect_results.append(waited == 0)
        else:
            connect_results.append(connected)

    import threading

    accept_thread = threading.Thread(target=wait_for_client, daemon=True)
    client_handle = None
    accept_thread.start()
    try:
        client_handle = guardian_service._open_readonly_pipe_client_handle(address, timeout_ms=5000)
        get_server_pid = kernel32.GetNamedPipeServerProcessId
        get_server_pid.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        get_server_pid.restype = wintypes.BOOL
        pid = wintypes.ULONG()
        assert get_server_pid(wintypes.HANDLE(client_handle), ctypes.byref(pid))
        assert int(pid.value) == os.getpid()
        accept_thread.join(5)
        assert not accept_thread.is_alive()
        assert connect_results == [True]
    finally:
        for handle in (client_handle, event, server_value):
            if handle:
                assert kernel32.CloseHandle(wintypes.HANDLE(handle))


@pytest.mark.skipif(os.name != "nt", reason="pinned executable handle test requires Windows")
def test_windows_retained_python_executable_hash_and_identity_smoke():
    executable = Path(sys.executable).resolve()
    expected_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    retained = guardian_service._RetainedPinnedExecutable.open(str(executable), expected_sha)
    try:
        assert retained.file_identity[3] == executable.stat().st_size
        retained.verify_current()
    finally:
        assert retained.close()


@pytest.mark.parametrize(
    ("writer_close_ok", "expected_state"), [(True, "observed"), (False, "unknown")]
)
def test_fixed_readonly_os_route_fake_end_to_end_composition(
    monkeypatch, writer_close_ok: bool, expected_state: str
):
    """Exercise client→OS-token service→Job→receipt wiring without a provider."""

    import queue
    import threading
    from types import SimpleNamespace

    import scripts.ctp_i13_i15_guardian_deployment_anchor as anchor_module

    service_sid = "S-1-5-80-1-2-3-4-5"
    client_sid = "S-1-5-21-11-22-33-44"
    address = r"\\.\pipe\backtrader-ctp-i13-i15-0123456789abcdef0123456789abcdef"
    pipe_ready = threading.Event()
    request_queue = queue.Queue()
    response_queue = queue.Queue()
    events = []
    receipts = []
    request_raw_holder = []
    handle_close_failures = {202} if not writer_close_ok else set()

    class FakeAnchor:
        def __init__(self):
            self.service_sid = service_sid
            self.client_sid = client_sid
            self.pipe_address = address

        def verify_current(self):
            events.append("anchor_verify")

        def verify_dependencies_current(self):
            events.append("dependencies_verify")

        def close_execution_leases(self):
            events.append("execution_leases_close")

        def create_receipt(self, request_id, raw):
            events.append("receipt_create")
            receipts.append((request_id, raw))
            return "retained-receipt-handle"

        def close_receipt_lease(self):
            events.append("receipt_lease_close")

        def close(self):
            events.append("anchor_close")

    class FakeClientBinding:
        def __init__(self):
            self.service_name = guardian_service.FIXED_READONLY_SERVICE_NAME
            self.service_sid = service_sid
            self.client_sid = client_sid
            self.pipe_address = address
            self.python_executable = r"C:\Trusted\python.exe"
            self.python_sha256 = "a" * 64
            self.descriptor_sha256 = "b" * 64

        def verify_current(self):
            events.append("client_binding_verify")

        def close(self):
            events.append("client_binding_close")

    class FakeToken:
        def __init__(self):
            self.handle = 900
            self.client_sid = client_sid
            self.client_pid = 345
            self.closed = False
            self._closed = False

        def close(self):
            if not self.closed:
                self.closed = True
                self._closed = True
                events.append("client_token_close")
            return True

    class FakeServerProcess:
        @classmethod
        def from_pipe(cls, pipe_handle, **kwargs):
            assert pipe_handle == 56
            assert kwargs == {
                "service_sid": service_sid,
                "python_executable": r"C:\Trusted\python.exe",
                "python_sha256": "a" * 64,
            }
            events.append("server_process_bind")
            return cls()

        def verify(self, pipe_handle):
            assert pipe_handle == 56
            events.append("server_process_verify")

        def close(self):
            events.append("server_process_close")
            return True

    class FakeOutput:
        def __init__(self, read_handle, *, max_bytes):
            assert read_handle == 201
            assert max_bytes == guardian_service.READONLY_MAX_OUTPUT_BYTES
            self.closed = False

        def poll_abort_reason(self):
            return None

        def read_after_job_empty(self, *, deadline_monotonic, monotonic):
            assert deadline_monotonic > monotonic()
            events.append("worker_output_read_after_job_empty")
            return b"synthetic-worker-output"

        def close(self):
            self.closed = True
            events.append("worker_output_close")
            return True

    class FakeSession:
        process_created = True
        job_assignment_observed = True

        def resume_launcher(self):
            assert token.closed
            assert "close_202" in events
            assert "close_203" in events
            events.append("worker_resume")
            return True

        def poll_launcher_exit_code(self):
            return 0

        def poll_job_empty(self):
            return True

        def terminate_job(self):
            events.append("job_terminate")
            return True

        def terminate_launcher_process(self):
            return True

        def release_controls(self):
            events.append("job_controls_release")
            return True

    class FakeBackend:
        def __init__(self, **kwargs):
            assert kwargs == {
                "primary_token_handle": 900,
                "inherited_stdin_handle": 203,
                "inherited_stdout_handle": 202,
                "inherited_stderr_handle": 203,
            }
            events.append("backend_bound_authenticated_token_and_stdio")

        def create_suspended_in_job(self, command, *, deadline_monotonic):
            assert type(command) is guardian_service.FixedOuterCommand
            assert deadline_monotonic > time.monotonic()
            events.append("worker_created_suspended_in_job")
            return FakeSession()

        def retain_controls(self, _session):
            return None

    token = FakeToken()
    fake_os = SimpleNamespace(name="nt", getpid=os.getpid)
    monkeypatch.setattr(guardian_service, "os", fake_os)
    monkeypatch.setattr(guardian_service, "_bind_service_sid", lambda sid: sid)
    monkeypatch.setattr(
        guardian_service, "_verify_current_fixed_service_identity", lambda _sid: None
    )
    monkeypatch.setattr(guardian_service, "_load_fixed_deployment_anchor", lambda: FakeAnchor())
    monkeypatch.setattr(guardian_service, "WindowsJobBackend", FakeBackend)
    monkeypatch.setattr(
        anchor_module,
        "load_fixed_guardian_client_binding",
        lambda: FakeClientBinding(),
        raising=False,
    )
    monkeypatch.setattr(guardian_service, "_current_user_sid", lambda: client_sid)
    monkeypatch.setattr(
        guardian_service,
        "_create_readonly_pipe_server_handle",
        lambda *_a, **_k: (pipe_ready.set(), 55)[1],
    )
    monkeypatch.setattr(guardian_service, "_connect_readonly_pipe_server", lambda *_a, **_k: None)
    monkeypatch.setattr(
        guardian_service,
        "_open_readonly_pipe_client_handle",
        lambda *_a, **_k: (pipe_ready.wait(2), 56)[1],
    )
    monkeypatch.setattr(guardian_service, "_RetainedReadonlyServerProcess", FakeServerProcess)
    monkeypatch.setattr(guardian_service, "_client_pid_from_pipe", lambda _handle: 345)
    monkeypatch.setattr(
        guardian_service,
        "_authenticated_pipe_client_primary_token",
        lambda _handle, **kwargs: (
            (events.append("pipe_message_token_captured"), token)[1]
            if kwargs == {"expected_client_sid": client_sid}
            else pytest.fail("token capture did not use the anchor client SID")
        ),
    )
    monkeypatch.setattr(
        guardian_service, "_create_worker_stdio_handles", lambda **_k: (201, 202, 203)
    )
    monkeypatch.setattr(guardian_service, "_BoundedWorkerOutput", FakeOutput)
    monkeypatch.setattr(
        guardian_service,
        "_fixed_readonly_worker_command",
        lambda _anchor, **_kwargs: guardian_service.FixedOuterCommand(
            [sys.executable], os.getcwd(), {}
        ),
    )
    monkeypatch.setattr(
        guardian_service,
        "_decode_readonly_worker_output",
        lambda raw: (events.append("worker_output_validated"), {"synthetic": raw.decode("ascii")})[
            1
        ],
    )

    clean_job = {
        "process_created": True,
        "job_assignment_observed": True,
        "launcher_resumed": True,
        "launcher_exit_observed": True,
        "launcher_exit_code": 0,
        "job_termination_requested": False,
        "job_termination_call_succeeded": None,
        "job_empty_observed": True,
        "containment": "verified",
        "controls_retained": False,
    }

    def run_two_stages(_anchor, *, request_id, owner_token, **kwargs):
        assert kwargs["deadline_monotonic_ns"] == json.loads(
            request_raw_holder[0].decode("ascii")
        )["deadline_monotonic_ns"]
        events.append("two_stage_start")
        assert owner_token.close() is True
        if writer_close_ok:
            raw_receipt = json.dumps(
                {"request_id": request_id, "state": "observed"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            receipts.append((request_id, raw_receipt))
            writer_facts = dict(clean_job)
            state = "observed"
            reason = "readonly_observation_complete"
            digest = hashlib.sha256(raw_receipt).hexdigest()
        else:
            writer_facts = guardian_service._readonly_not_started_worker_facts()
            state = "unknown"
            reason = "receipt_writer_cleanup_unverified"
            digest = None
        return guardian_service._ReadonlyTwoStageOutcome(
            state,
            reason,
            digest,
            dict(clean_job),
            writer_facts,
        )

    monkeypatch.setattr(guardian_service, "_run_readonly_two_stage_request", run_two_stages)
    monkeypatch.setattr(
        guardian_service,
        "_close_readonly_native_handle",
        lambda handle: (
            events.append("close_{}".format(handle)),
            handle not in handle_close_failures,
        )[1],
    )

    def write_message(handle, raw, **_kwargs):
        if handle == 56:
            request_queue.put(raw)
            request_raw_holder.append(raw)
        elif handle == 55:
            response_queue.put(raw)
        else:
            pytest.fail("readonly route wrote to an unexpected pipe handle")

    def read_message(handle, **kwargs):
        deadline = kwargs["deadline_monotonic"]
        remaining = max(0.0, deadline - time.monotonic())
        if handle == 55:
            return request_queue.get(timeout=remaining)
        if handle == 56:
            return response_queue.get(timeout=remaining)
        pytest.fail("readonly route read from an unexpected pipe handle")

    monkeypatch.setattr(guardian_service, "_write_readonly_pipe_message", write_message)
    monkeypatch.setattr(guardian_service, "_read_readonly_pipe_message", read_message)

    service_outcome = {}
    service_thread = threading.Thread(
        target=lambda: service_outcome.setdefault(
            "state", guardian_service.serve_fixed_readonly_preflight_request()
        ),
        daemon=True,
    )
    service_thread.start()
    assert pipe_ready.wait(2)
    response = guardian_service.request_fixed_readonly_preflight(
        hard_deadline_seconds=20, ipc_timeout_seconds=5
    )
    service_thread.join(5)

    assert not service_thread.is_alive()
    assert response.state == "response"
    request = json.loads(request_raw_holder[0].decode("ascii"))
    decoded = guardian_service._decode_readonly_os_response(
        response.response_bytes, request_id=request["request_id"]
    )
    assert decoded["state"] == expected_state, (decoded, service_outcome, events, receipts)
    expected_digest = hashlib.sha256(receipts[0][1]).hexdigest() if receipts else None
    assert decoded["receipt_sha256"] == expected_digest
    assert guardian_service._job_facts_are_clean_success(decoded["coordinator_job"])
    if expected_state == "observed":
        assert guardian_service._job_facts_are_clean_success(decoded["receipt_writer_job"])
    else:
        assert decoded["receipt_writer_job"]["process_created"] is False
    assert service_outcome["state"] == expected_state
    assert "client_token_close" in events
    assert "two_stage_start" in events
    if expected_state != "observed":
        assert receipts == []


def test_readonly_two_stage_launches_writer_only_after_job1_empty(monkeypatch):
    """Use the real watchdog with inert sessions to verify the two-Job order."""

    from types import SimpleNamespace

    import scripts.ctp_i13_i15_readonly_receipt_writer as receipt_writer
    import scripts.ctp_i13_i15_readonly_request_coordinator as coordinator
    import scripts.ctp_i13_i15_worker_output_channel as output_channel

    service_sid = "S-1-5-80-1-2-3-4-5"
    owner_sid = "S-1-5-21-10-20-30-40"
    request_id = "a" * 32
    deadline_ns = time.monotonic_ns() + 60_000_000_000
    events = []

    anchor = SimpleNamespace(service_sid=service_sid, client_sid=owner_sid)
    for name in (
        "descriptor_sha256",
        "source_manifest_sha256",
        "runtime_manifest_sha256",
        "worker_dependency_manifest_sha256",
        "python_sha256",
        "i13_pin_sha256",
        "i15_pin_sha256",
        "bootstrap_sha256",
        "worker_sha256",
        "request_coordinator_sha256",
        "receipt_writer_sha256",
        "token_bootstrap_sha256",
    ):
        setattr(anchor, name, hashlib.sha256(name.encode("ascii")).hexdigest())

    class OwnerToken:
        def __init__(self):
            self._closed = False
            self.client_sid = owner_sid
            self.handle = 991

        def close(self):
            self._closed = True
            events.append("owner_token_closed")
            return True

    owner_token = OwnerToken()

    class TokenServer:
        def __init__(self, **kwargs):
            assert kwargs["owner_token"] is owner_token
            assert kwargs["request_id"] == request_id
            self.binding = {"nonce": "c" * 32, "server_pid": 1234}

        def bind_suspended_coordinator(self, pid, process_handle):
            events.append("token_remote_handle_bound")
            assert pid == process_handle
            return True

        def send_after_resume(self):
            events.append("token_frame_sent")
            assert owner_token._closed

        def close(self):
            events.append("token_server_closed")
            return True

    class Channel:
        def __init__(self, stage, nonce):
            self.stage = stage
            self.bootstrap_binding = {"nonce": nonce, "server_pid": 1234}
            self.result = None
            self.closed = False

        def bind_suspended_worker(self, pid, process_handle):
            assert pid == process_handle
            events.append(self.stage + "_suspended_process_bound")
            return True

        def poll_abort_reason(self):
            return None

        def read_frame_after_job_empty(
            self, *, request_id, outer_result, deadline_monotonic, monotonic
        ):
            assert self.result is outer_result
            assert outer_result.state == "exited"
            assert outer_result.reason == "launcher_exited_job_empty"
            assert outer_result.evidence.job_empty_observed is True
            assert deadline_monotonic > monotonic()
            events.append(self.stage + "_frame_read_after_empty")
            if self.stage == "coordinator":
                observation = {
                    "schema": "ctp_i13_i15_readonly_worker_summary.v1",
                    "identity": {
                        "account_scope": "redacted",
                        "provider": "ctp",
                        "environment": "simnow",
                        "trading_day": "20260927",
                        "connection_generation": 1,
                    },
                    "query_digests": [
                        [name, hashlib.sha256(name.encode("ascii")).hexdigest()]
                        for name in (
                            "account",
                            "commission_rates",
                            "instruments",
                            "margin_rates",
                            "orders",
                            "positions",
                            "trades",
                        )
                    ],
                    "snapshot_sha256": "d" * 64,
                }
                output = {
                    "schema": coordinator.COORDINATOR_OUTPUT_SCHEMA,
                    "request_id": request_id,
                    "state": "observed",
                    "reason": "completed",
                    "worker_observation": observation,
                    "worker_facts": {
                        "process_created": True,
                        "job_assignment_observed": True,
                        "launcher_resumed": True,
                        "launcher_exit_observed": True,
                        "launcher_exit_code": 0,
                        "job_termination_requested": False,
                        "job_termination_call_succeeded": None,
                        "job_empty_observed": True,
                        "containment": "verified",
                        "controls_retained": False,
                    },
                }
                return coordinator.encode_coordinator_frame(
                    output, request_id=request_id, nonce=self.bootstrap_binding["nonce"]
                )
            output = {
                "schema": receipt_writer.RECEIPT_OUTPUT_SCHEMA,
                "request_id": request_id,
                "state": "observed",
                "reason": "completed",
                "receipt_created": True,
                "receipt_sha256": "e" * 64,
            }
            return receipt_writer.encode_receipt_writer_frame(
                output, request_id=request_id, nonce=self.bootstrap_binding["nonce"]
            )

        def close(self):
            self.closed = True
            events.append(self.stage + "_channel_closed")
            return True

    channels = []

    def create_channel(*, service_sid):
        assert service_sid == anchor.service_sid
        stage = "coordinator" if not channels else "writer"
        channel = Channel(stage, "1" * 32 if stage == "coordinator" else "2" * 32)
        channels.append(channel)
        events.append(stage + "_channel_created")
        return channel

    class Session:
        process_created = True
        job_assignment_observed = True

        def __init__(self, stage):
            self.stage = stage
            self.resumed = False

        def resume_launcher(self):
            if self.stage == "coordinator":
                assert owner_token._closed
            else:
                assert "coordinator_job_empty" in events
            self.resumed = True
            events.append(self.stage + "_resumed")
            return True

        def poll_launcher_exit_code(self):
            return 0 if self.resumed else None

        def poll_job_empty(self):
            return True

        def terminate_job(self):
            return True

        def terminate_launcher_process(self):
            return True

        def release_controls(self):
            events.append(self.stage + "_job_empty")
            return True

    class Backend:
        def __init__(self, **kwargs):
            assert kwargs["no_inherited_handles"] is True
            self.process_created_callback = kwargs["process_created_callback"]

        def create_suspended_in_job(self, command, *, deadline_monotonic):
            assert deadline_monotonic > time.monotonic()
            stage = "coordinator" if "request_coordinator_binding" in command.argv[-1] else "writer"
            if stage == "writer":
                assert "coordinator_job_empty" in events
            events.append(stage + "_create_suspended_in_job")
            session = Session(stage)
            pid = 1001 if stage == "coordinator" else 1002
            assert self.process_created_callback(pid, pid) is True
            return session

        def retain_controls(self, _session):
            return None

    def run_with_real_watchdog(
        channel,
        command,
        *,
        backend,
        request_id,
        deadline_monotonic,
        stop_deadline_monotonic=None,
        after_resume=None,
    ):
        result = guardian_service.run_outer_watchdog(
            command,
            backend=backend,
            deadline_monotonic=deadline_monotonic,
            stop_deadline_monotonic=stop_deadline_monotonic,
            abort_requested=channel.poll_abort_reason,
            after_resume=after_resume,
        )
        channel.result = result
        return result

    monkeypatch.setattr(guardian_service, "_OwnerTokenControlServer", TokenServer)
    monkeypatch.setattr(
        guardian_service,
        "_fixed_readonly_service_role_command",
        lambda _anchor, binding, **_kwargs: guardian_service.FixedOuterCommand(
            [sys.executable, binding["schema"]], os.getcwd(), {}
        ),
    )
    monkeypatch.setattr(output_channel, "create_service_stage_output_channel", create_channel)
    monkeypatch.setattr(output_channel, "run_child_with_output_channel", run_with_real_watchdog)

    outcome = guardian_service._run_readonly_two_stage_request(
        anchor,
        request_id=request_id,
        deadline_monotonic_ns=deadline_ns,
        owner_token=owner_token,
        backend_factory=Backend,
    )

    assert outcome.state == "observed"
    assert outcome.reason == "readonly_observation_complete"
    assert outcome.receipt_sha256 == "e" * 64
    assert guardian_service._job_facts_are_clean_success(outcome.coordinator_job)
    assert guardian_service._job_facts_are_clean_success(outcome.receipt_writer_job)
    assert events.index("owner_token_closed") < events.index("coordinator_resumed")
    assert events.index("token_frame_sent") < events.index("coordinator_frame_read_after_empty")
    assert events.index("coordinator_job_empty") < events.index("writer_create_suspended_in_job")
    assert events.index("coordinator_frame_read_after_empty") < events.index("writer_create_suspended_in_job")
    assert events.index("writer_job_empty") < events.index("writer_frame_read_after_empty")


def test_readonly_two_stage_does_not_start_writer_without_job1_cleanup(monkeypatch):
    """A missing coordinator exit/Job-empty fact prevents any Job2 creation."""

    from types import SimpleNamespace

    import scripts.ctp_i13_i15_worker_output_channel as output_channel

    service_sid = "S-1-5-80-1-2-3-4-5"
    owner_sid = "S-1-5-21-10-20-30-40"
    events = []
    created_channels = []

    anchor = SimpleNamespace(service_sid=service_sid, client_sid=owner_sid)
    for name in (
        "descriptor_sha256",
        "source_manifest_sha256",
        "runtime_manifest_sha256",
        "worker_dependency_manifest_sha256",
        "python_sha256",
        "i13_pin_sha256",
        "i15_pin_sha256",
        "bootstrap_sha256",
        "worker_sha256",
        "request_coordinator_sha256",
        "receipt_writer_sha256",
        "token_bootstrap_sha256",
    ):
        setattr(anchor, name, hashlib.sha256(name.encode("ascii")).hexdigest())

    class TokenServer:
        binding = {"nonce": "c" * 32, "server_pid": 1234}

        def __init__(self, **_kwargs):
            pass

        def close(self):
            return True

    class Channel:
        bootstrap_binding = {"nonce": "1" * 32, "server_pid": 1234}

        def close(self):
            return True

    def create_channel(*, service_sid):
        created_channels.append(service_sid)
        return Channel()

    monkeypatch.setattr(guardian_service, "_OwnerTokenControlServer", TokenServer)
    monkeypatch.setattr(
        guardian_service,
        "_fixed_readonly_service_role_command",
        lambda *_args, **_kwargs: guardian_service.FixedOuterCommand(
            [sys.executable, "fixed"], os.getcwd(), {}
        ),
    )
    monkeypatch.setattr(
        guardian_service,
        "_run_fixed_service_role_stage",
        lambda **_kwargs: (_not_started_result(), None, "creation_unknown"),
    )
    monkeypatch.setattr(output_channel, "create_service_stage_output_channel", create_channel)

    class _Owner:
        def __init__(self):
            self._closed = False
            self.client_sid = owner_sid

        def close(self):
            self._closed = True
            events.append("owner_token_closed")
            return True

    def _not_started_result():
        result = guardian_service._not_started_outer_result()
        result.reason = "creation_unknown"
        return result

    outcome = guardian_service._run_readonly_two_stage_request(
        anchor,
        request_id="b" * 32,
        deadline_monotonic_ns=time.monotonic_ns() + 60_000_000_000,
        owner_token=_Owner(),
        backend_factory=lambda **_kwargs: SimpleNamespace(),
    )
    assert outcome.state == "unknown"
    assert outcome.reason == "coordinator_cleanup_unverified", (outcome, events)
    assert len(created_channels) == 1


def _make_two_stage_result_harness(
    monkeypatch, *, writer_mode="clean", writer_close=True, monotonic=None
):
    """Build a typed fake-stage harness for late-stage fail-closed checks."""

    from types import SimpleNamespace

    import scripts.ctp_i13_i15_readonly_receipt_writer as receipt_writer
    import scripts.ctp_i13_i15_readonly_request_coordinator as coordinator
    import scripts.ctp_i13_i15_worker_output_channel as output_channel

    service_sid = "S-1-5-80-1-2-3-4-5"
    owner_sid = "S-1-5-21-10-20-30-40"
    request_id = "c" * 32
    deadline_ns = 20_000_000_000 if monotonic is not None else time.monotonic_ns() + 60_000_000_000
    events = []
    anchor = SimpleNamespace(service_sid=service_sid, client_sid=owner_sid)
    for name in (
        "descriptor_sha256",
        "source_manifest_sha256",
        "runtime_manifest_sha256",
        "worker_dependency_manifest_sha256",
        "python_sha256",
        "i13_pin_sha256",
        "i15_pin_sha256",
        "bootstrap_sha256",
        "worker_sha256",
        "request_coordinator_sha256",
        "receipt_writer_sha256",
        "token_bootstrap_sha256",
    ):
        setattr(anchor, name, hashlib.sha256(name.encode("ascii")).hexdigest())

    class OwnerToken:
        _closed = False
        client_sid = owner_sid

        def close(self):
            self._closed = True
            events.append("owner_token_closed")
            return True

    owner_token = OwnerToken()

    class TokenServer:
        binding = {"nonce": "d" * 32, "server_pid": 1234}

        def __init__(self, **_kwargs):
            pass

        def bind_suspended_coordinator(self, _pid, _process_handle):
            return True

        def send_after_resume(self):
            pass

        def close(self):
            return True

    class Channel:
        def __init__(self, stage):
            self.stage = stage
            self.bootstrap_binding = {
                "nonce": "1" * 32 if stage == "coordinator" else "2" * 32,
                "server_pid": 1234,
            }

        def close(self):
            events.append(self.stage + "_channel_closed")
            return writer_close if self.stage == "writer" else True

    channels = []

    def create_channel(*, service_sid):
        assert service_sid == anchor.service_sid
        stage = "coordinator" if not channels else "writer"
        channel = Channel(stage)
        channels.append(channel)
        events.append(stage + "_channel_created")
        return channel

    def outer_result(*, clean, exit_code=0):
        if clean:
            return SimpleNamespace(
                state="exited",
                reason="launcher_exited_job_empty",
                evidence=SimpleNamespace(
                    process_created=True,
                    job_assignment_observed=True,
                    launcher_resumed=True,
                    launcher_exit_observed=True,
                    launcher_exit_code=exit_code,
                    job_termination_requested=False,
                    job_termination_call_succeeded=None,
                    job_empty_observed=True,
                    containment="verified",
                    controls_retained=False,
                ),
            )
        return SimpleNamespace(
            state="timed_out",
            reason="deadline_expired",
            evidence=SimpleNamespace(
                process_created=True,
                job_assignment_observed=True,
                launcher_resumed=True,
                launcher_exit_observed=False,
                launcher_exit_code=None,
                job_termination_requested=True,
                job_termination_call_succeeded=True,
                job_empty_observed=False,
                containment="unknown",
                controls_retained=True,
            ),
        )

    worker_observation = {
        "schema": "ctp_i13_i15_readonly_worker_summary.v1",
        "identity": {
            "account_scope": "redacted",
            "provider": "ctp",
            "environment": "simnow",
            "trading_day": "20260927",
            "connection_generation": 1,
        },
        "query_digests": [
            [name, hashlib.sha256(name.encode("ascii")).hexdigest()]
            for name in (
                "account",
                "commission_rates",
                "instruments",
                "margin_rates",
                "orders",
                "positions",
                "trades",
            )
        ],
        "snapshot_sha256": "d" * 64,
    }
    coordinator_frame = coordinator.encode_coordinator_frame(
        {
            "schema": coordinator.COORDINATOR_OUTPUT_SCHEMA,
            "request_id": request_id,
            "state": "observed",
            "reason": "completed",
            "worker_observation": worker_observation,
            "worker_facts": {
                "process_created": True,
                "job_assignment_observed": True,
                "launcher_resumed": True,
                "launcher_exit_observed": True,
                "launcher_exit_code": 0,
                "job_termination_requested": False,
                "job_termination_call_succeeded": None,
                "job_empty_observed": True,
                "containment": "verified",
                "controls_retained": False,
            },
        },
        request_id=request_id,
        nonce="1" * 32,
    )
    writer_frame = receipt_writer.encode_receipt_writer_frame(
        {
            "schema": receipt_writer.RECEIPT_OUTPUT_SCHEMA,
            "request_id": request_id,
            "state": "observed",
            "reason": "completed",
            "receipt_created": True,
            "receipt_sha256": "e" * 64,
        },
        request_id=request_id,
        nonce="2" * 32,
    )

    def run_stage(*, channel, **_kwargs):
        events.append(channel.stage + "_stage_started")
        if channel.stage == "coordinator":
            events.append("coordinator_job_empty")
            return outer_result(clean=True), coordinator_frame, None
        if writer_mode == "timed_out":
            return outer_result(clean=False), None, "job_cleanup_unverified"
        events.append("writer_job_empty")
        return outer_result(clean=True), writer_frame, None

    monkeypatch.setattr(guardian_service, "_OwnerTokenControlServer", TokenServer)
    monkeypatch.setattr(
        guardian_service,
        "_fixed_readonly_service_role_command",
        lambda _anchor, binding, **_kwargs: guardian_service.FixedOuterCommand(
            [sys.executable, binding["schema"]], os.getcwd(), {}
        ),
    )
    monkeypatch.setattr(guardian_service, "_run_fixed_service_role_stage", run_stage)
    monkeypatch.setattr(output_channel, "create_service_stage_output_channel", create_channel)

    def run():
        return guardian_service._run_readonly_two_stage_request(
            anchor,
            request_id=request_id,
            deadline_monotonic_ns=deadline_ns,
            owner_token=owner_token,
            backend_factory=lambda **_kwargs: SimpleNamespace(),
            **({"monotonic": monotonic} if monotonic is not None else {}),
        )

    return run, events, channels


def test_readonly_two_stage_job2_cleanup_unknown_never_reports_observed(monkeypatch):
    run, events, _channels = _make_two_stage_result_harness(
        monkeypatch, writer_mode="timed_out"
    )

    outcome = run()
    assert outcome.state == "unknown"
    assert outcome.reason == "receipt_writer_cleanup_unverified", (outcome, events)
    assert guardian_service._job_facts_are_clean_success(outcome.coordinator_job)
    assert outcome.receipt_writer_job["containment"] == "unknown"
    assert "writer_channel_created" in events


def test_readonly_two_stage_deadline_crossing_downgrades_receipt(monkeypatch):
    calls = 0

    def monotonic():
        nonlocal calls
        calls += 1
        return 1.0 if calls < 4 else 21.0

    run, _events, _channels = _make_two_stage_result_harness(
        monkeypatch, monotonic=monotonic
    )

    outcome = run()

    assert outcome.state == "unknown"
    assert outcome.reason == "readonly_deadline_exceeded"
    assert outcome.receipt_sha256 == "e" * 64
    assert guardian_service._job_facts_are_clean_success(outcome.receipt_writer_job)


def test_readonly_two_stage_channel_close_failure_raises_instead_of_success(monkeypatch):
    run, events, _channels = _make_two_stage_result_harness(
        monkeypatch, writer_close=False
    )

    with pytest.raises(guardian_service.GuardianServiceError, match="cleanup_unconfirmed"):
        run()

    assert "writer_channel_closed" in events


def test_fixed_readonly_caller_ipc_timeout_is_distinct_from_service_hard_deadline(monkeypatch):
    """The caller may stop waiting before the request's absolute service deadline."""

    import threading
    from types import SimpleNamespace

    import scripts.ctp_i13_i15_guardian_deployment_anchor as anchor_module

    client_sid = "S-1-5-21-11-22-33-44"
    service_sid = "S-1-5-80-1-2-3-4-5"
    entered_read = threading.Event()
    release_read = threading.Event()
    cleaned = threading.Event()

    class Binding:
        def __init__(self):
            self.service_name = guardian_service.FIXED_READONLY_SERVICE_NAME
            self.service_sid = service_sid
            self.client_sid = client_sid
            self.pipe_address = r"\\.\pipe\backtrader-ctp-i13-i15-0123456789abcdef0123456789abcdef"
            self.python_executable = r"C:\Trusted\python.exe"
            self.python_sha256 = "a" * 64
            self.descriptor_sha256 = "b" * 64

        def verify_current(self):
            return None

        def close(self):
            cleaned.set()

    class ServerProcess:
        @classmethod
        def from_pipe(cls, *_a, **_kwargs):
            return cls()

        def verify(self, _handle):
            return None

        def close(self):
            return True

    monkeypatch.setattr(guardian_service, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(guardian_service, "_bind_service_sid", lambda sid: sid)
    monkeypatch.setattr(guardian_service, "_current_user_sid", lambda: client_sid)
    monkeypatch.setattr(guardian_service, "_open_readonly_pipe_client_handle", lambda *_a, **_k: 56)
    monkeypatch.setattr(guardian_service, "_RetainedReadonlyServerProcess", ServerProcess)
    monkeypatch.setattr(guardian_service, "_write_readonly_pipe_message", lambda *_a, **_k: None)
    monkeypatch.setattr(guardian_service, "_close_readonly_native_handle", lambda _handle: True)
    monkeypatch.setattr(
        anchor_module,
        "load_fixed_guardian_client_binding",
        lambda: Binding(),
        raising=False,
    )

    def delayed_read(_handle, **_kwargs):
        entered_read.set()
        release_read.wait(5)
        raise guardian_service.GuardianServiceError("pipe_peer_disconnected")

    monkeypatch.setattr(guardian_service, "_read_readonly_pipe_message", delayed_read)

    try:
        response = guardian_service.request_fixed_readonly_preflight(
            hard_deadline_seconds=20, ipc_timeout_seconds=1
        )
        assert entered_read.is_set()
        assert response.state == "unknown"
        assert response.reason == "ipc_deadline_exceeded"
        assert response.response_bytes is None
    finally:
        release_read.set()
    assert cleaned.wait(2)


def test_readonly_service_failstops_on_revert_failure_before_receipt_or_response(monkeypatch):
    """A thread with uncertain impersonation may not do later service work."""

    from types import SimpleNamespace

    events = []
    receipts = []
    responses = []
    service_sid = "S-1-5-80-1-2-3-4-5"
    client_sid = "S-1-5-21-11-22-33-44"
    address = r"\\.\pipe\backtrader-ctp-i13-i15-0123456789abcdef0123456789abcdef"
    request_raw = json.dumps(
        {
            "schema": guardian_service.READONLY_OS_REQUEST_SCHEMA,
            "operation": "ctp_readonly_preflight",
            "request_id": "a" * 32,
            "deadline_monotonic_ns": time.monotonic_ns() + 60_000_000_000,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")

    class FakeAnchor:
        def __init__(self):
            self.service_sid = service_sid
            self.client_sid = client_sid
            self.pipe_address = address

        def verify_current(self):
            events.append("anchor_verify")

        def verify_dependencies_current(self):
            events.append("dependencies_verify")

        def close_execution_leases(self):
            events.append("execution_leases_close")

        def create_receipt(self, request_id, raw):
            receipts.append((request_id, raw))
            events.append("receipt_create")

        def close_receipt_lease(self):
            events.append("receipt_lease_close")

        def close(self):
            events.append("anchor_handle_cleanup")

    class FatalExitIntercepted(Exception):
        pass

    monkeypatch.setattr(guardian_service, "os", SimpleNamespace(name="nt", getpid=os.getpid))
    monkeypatch.setattr(guardian_service, "_bind_service_sid", lambda sid: sid)
    monkeypatch.setattr(
        guardian_service, "_verify_current_fixed_service_identity", lambda _sid: None
    )
    monkeypatch.setattr(
        guardian_service,
        "_create_readonly_pipe_server_handle",
        lambda *_args, **_kwargs: 55,
    )
    monkeypatch.setattr(
        guardian_service, "_connect_readonly_pipe_server", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        guardian_service,
        "_read_readonly_pipe_message",
        lambda *_args, **_kwargs: request_raw,
    )
    monkeypatch.setattr(
        guardian_service,
        "_authenticated_pipe_client_primary_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            guardian_service.GuardianServiceThreadFatalError("pipe_client_revert_failed")
        ),
    )

    def close_native_handle(handle):
        events.append("pipe_close_{}".format(handle))
        return True

    def fail_stop():
        events.append("fatal_exit")
        raise FatalExitIntercepted()

    monkeypatch.setattr(guardian_service, "_close_readonly_native_handle", close_native_handle)
    monkeypatch.setattr(
        guardian_service,
        "_write_readonly_pipe_message",
        lambda *_args, **_kwargs: responses.append(True),
    )
    monkeypatch.setattr(
        guardian_service, "_fail_stop_service_process_after_revert_failure", fail_stop
    )

    anchor = FakeAnchor()
    with pytest.raises(FatalExitIntercepted):
        guardian_service._serve_one_readonly_os_request(
            anchor, backend_factory=lambda **_kwargs: pytest.fail("worker must not launch")
        )

    assert events[-1] == "fatal_exit"
    assert "pipe_close_55" not in events
    assert "anchor_handle_cleanup" not in events
    assert "execution_leases_close" not in events
    assert "receipt_create" not in events
    assert "receipt_lease_close" not in events
    assert receipts == []
    assert responses == []
