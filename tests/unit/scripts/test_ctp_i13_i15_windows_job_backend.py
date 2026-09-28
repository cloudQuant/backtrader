"""Offline, inert tests for the unregistered Windows Job backend seam."""

import ctypes
import gc
import json
import os
import subprocess
import sys
import time
import weakref
from ctypes import wintypes
from pathlib import Path

import pytest

from scripts import ctp_i13_i15_outer_watchdog as watchdog
from scripts import ctp_i13_i15_windows_job_backend as windows_job


class FakeKernel32:
    """Small injected kernel32 surface; never creates an operating-system process."""

    def __init__(self):
        self.events = []
        self.active = 0
        self.active_after_create = None
        self.process_signaled = False
        self.process_exit_code = 0
        self.raise_on_set_job = None
        self.set_job_success = True
        self.initialize_success = True
        self.update_success = True
        self.query_success = True
        self.create_result = True
        self.as_user_create_result = None
        self.raise_after_process_info = None
        self.thread_only_after_process_info = False
        self.fail_close_once = set()
        self.close_failures_used = set()
        self.never_drain = False
        self.resume_previous_count = 1
        self.job_handle = 101
        self.process_handle = 202
        self.thread_handle = 303
        self.create_args = None
        self.attribute_list_pointer = None
        self.job_array_pointer = None
        self.output_handle_array_pointer = None
        self.inherited_handle_values = None
        self.job_limit_flags = None
        self.after_attribute_update = None

    def CreateJobObjectW(self, _attributes, _name):
        self.events.append("create_job")
        return self.job_handle

    def SetInformationJobObject(self, _job, _kind, info_pointer, _size):
        info = ctypes.cast(
            info_pointer,
            ctypes.POINTER(windows_job._JOBOBJECT_EXTENDED_LIMIT_INFORMATION),
        ).contents
        self.job_limit_flags = int(info.BasicLimitInformation.LimitFlags)
        self.events.append("set_job_limits")
        if self.raise_on_set_job is not None:
            raise self.raise_on_set_job
        return self.set_job_success

    def InitializeProcThreadAttributeList(
        self, attribute_list, _count, _flags, required_size_pointer
    ):
        self.events.append("initialize_attributes")
        required = ctypes.cast(
            required_size_pointer, ctypes.POINTER(ctypes.c_size_t)
        )
        if not attribute_list:
            required.contents.value = 128
            return False
        return self.initialize_success

    def UpdateProcThreadAttribute(
        self,
        attribute_list,
        _flags,
        attribute,
        value_pointer,
        value_size,
        _previous_value,
        _return_size,
    ):
        self.events.append("update_attributes")
        self.attribute_list_pointer = attribute_list
        if attribute == windows_job._PROC_THREAD_ATTRIBUTE_JOB_LIST:
            self.job_array_pointer = value_pointer
        elif attribute == windows_job._PROC_THREAD_ATTRIBUTE_HANDLE_LIST:
            self.output_handle_array_pointer = value_pointer
            count = int(value_size) // ctypes.sizeof(wintypes.HANDLE)
            self.inherited_handle_values = tuple(
                int(value)
                for value in ctypes.cast(
                    value_pointer, ctypes.POINTER(wintypes.HANDLE * count)
                ).contents
            )
        else:
            raise AssertionError("unexpected process attribute")
        if self.after_attribute_update is not None:
            self.after_attribute_update()
        return self.update_success

    def CreateProcessW(
        self,
        app_name,
        command_line,
        _process_attributes,
        _thread_attributes,
        inherit_handles,
        creation_flags,
        environment,
        cwd,
        startup_pointer,
        process_info_pointer,
    ):
        self.events.append("create_process")
        startup = ctypes.cast(
            startup_pointer, ctypes.POINTER(windows_job._STARTUPINFOEXW)
        ).contents
        self.create_args = {
            "app_name": app_name,
            "command_line": command_line,
            "inherit_handles": inherit_handles,
            "creation_flags": creation_flags,
            "environment": environment,
            "cwd": cwd,
            "startup_cb": int(startup.StartupInfo.cb),
            "attribute_list": startup.lpAttributeList,
            "stdin_handle": int(startup.StartupInfo.hStdInput or 0),
            "stdout_handle": int(startup.StartupInfo.hStdOutput or 0),
            "stderr_handle": int(startup.StartupInfo.hStdError or 0),
            "startup_flags": int(startup.StartupInfo.dwFlags),
        }
        assert ctypes.cast(startup.lpAttributeList, ctypes.c_void_p).value == (
            ctypes.cast(self.attribute_list_pointer, ctypes.c_void_p).value
        )
        process_info = ctypes.cast(
            process_info_pointer, ctypes.POINTER(windows_job._PROCESS_INFORMATION)
        ).contents
        if self.raise_after_process_info is not None:
            process_info.hThread = self.thread_handle
            if not self.thread_only_after_process_info:
                process_info.hProcess = self.process_handle
            self.active = 1
            raise self.raise_after_process_info
        if self.create_result:
            process_info.hProcess = self.process_handle
            process_info.hThread = self.thread_handle
            process_info.dwProcessId = 505
            self.active = (
                1 if self.active_after_create is None else self.active_after_create
            )
        elif self.thread_only_after_process_info:
            process_info.hThread = self.thread_handle
            process_info.dwProcessId = 505
            self.active = 1
        return self.create_result

    def CreateProcessAsUserW(self, token_handle, *args):
        self.events.append("create_process_as_user")
        self.owner_token_handle = int(token_handle)
        if self.as_user_create_result is False:
            return False
        return self.CreateProcessW(*args)

    def DeleteProcThreadAttributeList(self, _attribute_list):
        self.events.append("delete_attributes")

    def ResumeThread(self, _thread):
        self.events.append("resume_thread")
        if self.resume_previous_count == 1 and not self.never_drain:
            self.process_signaled = True
            self.active = 0
        return self.resume_previous_count

    def WaitForSingleObject(self, _process, _milliseconds):
        self.events.append("wait_process")
        return (
            windows_job._WAIT_OBJECT_0
            if self.process_signaled
            else windows_job._WAIT_TIMEOUT
        )

    def GetExitCodeProcess(self, _process, exit_code_pointer):
        ctypes.cast(exit_code_pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = (
            self.process_exit_code
        )
        return True

    def QueryInformationJobObject(
        self, _job, _kind, info_pointer, _info_size, _return_size
    ):
        self.events.append("query_job")
        if not self.query_success:
            return False
        info = ctypes.cast(
            info_pointer,
            ctypes.POINTER(windows_job._JOBOBJECT_BASIC_ACCOUNTING_INFORMATION),
        ).contents
        info.ActiveProcesses = self.active
        return True

    def TerminateJobObject(self, _job, _exit_code):
        self.events.append("terminate_job")
        if not self.never_drain:
            self.active = 0
            self.process_signaled = True
        return True

    def TerminateProcess(self, _process, _exit_code):
        self.events.append("terminate_process")
        if not self.never_drain:
            self.active = 0
            self.process_signaled = True
        return True

    def CloseHandle(self, handle):
        normalized = int(handle)
        self.events.append(("close_handle", normalized))
        if (
            normalized in self.fail_close_once
            and normalized not in self.close_failures_used
        ):
            self.close_failures_used.add(normalized)
            return False
        return True


def _command():
    return watchdog.FixedOuterCommand(
        [os.path.abspath(sys.executable), "-I", "-c", "pass"],
        os.getcwd(),
        {"PATH": os.path.dirname(os.path.abspath(sys.executable))},
    )


def test_atomic_create_and_release_uses_job_list_and_kill_on_close():
    kernel = FakeKernel32()
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    session = backend.create_suspended_in_job(
        _command(), deadline_monotonic=time.monotonic() + 5.0
    )

    assert session.job_assignment_observed is True
    assert kernel.job_limit_flags == windows_job._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert kernel.create_args["app_name"] == os.path.abspath(sys.executable)
    assert isinstance(kernel.create_args["command_line"], ctypes.Array)
    assert kernel.create_args["inherit_handles"] is False
    assert kernel.create_args["creation_flags"] & windows_job._CREATE_SUSPENDED
    assert kernel.create_args["creation_flags"] & windows_job._EXTENDED_STARTUPINFO_PRESENT
    assert not kernel.create_args["creation_flags"] & 0x01000000  # BREAKAWAY_OK
    assert kernel.events.index("update_attributes") < kernel.events.index("create_process")
    assert kernel.events.index("create_process") < kernel.events.index("delete_attributes")
    assert ctypes.cast(
        kernel.job_array_pointer, ctypes.POINTER(wintypes.HANDLE * 1)
    ).contents[0] == kernel.job_handle

    assert session.resume_launcher() is True
    assert session.poll_launcher_exit_code() == 0
    assert session.poll_job_empty() is True
    assert session.release_controls() is True
    assert [event for event in kernel.events if isinstance(event, tuple)] == [
        ("close_handle", kernel.thread_handle),
        ("close_handle", kernel.process_handle),
        ("close_handle", kernel.job_handle),
    ]


def test_authenticated_owner_token_uses_as_user_with_atomic_job_membership():
    kernel = FakeKernel32()
    owner_token = 0x456
    backend = windows_job.WindowsJobBackend(
        kernel32=kernel,
        advapi32=kernel,
        primary_token_handle=owner_token,
    )

    session = backend.create_suspended_in_job(
        _command(), deadline_monotonic=time.monotonic() + 5.0
    )

    assert kernel.owner_token_handle == owner_token
    assert kernel.events.index("update_attributes") < kernel.events.index(
        "create_process_as_user"
    )
    assert kernel.events.index("create_process_as_user") < kernel.events.index(
        "delete_attributes"
    )
    assert kernel.create_args["creation_flags"] & windows_job._CREATE_SUSPENDED
    assert kernel.create_args["creation_flags"] & windows_job._EXTENDED_STARTUPINFO_PRESENT
    assert session.job_assignment_observed is True
    assert session.resume_launcher() is True
    assert session.poll_launcher_exit_code() == 0
    assert session.poll_job_empty() is True
    assert session.release_controls() is True


def test_owner_token_no_inheritance_binds_suspended_in_job_process_before_resume():
    kernel = FakeKernel32()
    bound = []

    def bind_worker(pid, process_handle):
        kernel.events.append("bind_worker_pid")
        bound.append((pid, process_handle))
        return True

    backend = windows_job.WindowsJobBackend(
        kernel32=kernel,
        advapi32=kernel,
        primary_token_handle=0x456,
        no_inherited_handles=True,
        process_created_callback=bind_worker,
    )

    session = backend.create_suspended_in_job(
        _command(), deadline_monotonic=time.monotonic() + 5.0
    )

    assert bound == [(505, kernel.process_handle)]
    assert kernel.owner_token_handle == 0x456
    assert kernel.create_args["inherit_handles"] is False
    assert kernel.create_args["startup_flags"] & windows_job._STARTF_USESTDHANDLES == 0
    assert kernel.create_args["stdin_handle"] == 0
    assert kernel.create_args["stdout_handle"] == 0
    assert kernel.create_args["stderr_handle"] == 0
    assert kernel.output_handle_array_pointer is None
    assert kernel.events.count("update_attributes") == 1
    assert kernel.events.index("create_process_as_user") < kernel.events.index(
        "bind_worker_pid"
    )
    assert session.job_assignment_observed is True
    assert session.resume_launcher() is True
    assert kernel.events.index("bind_worker_pid") < kernel.events.index("resume_thread")
    assert session.poll_launcher_exit_code() == 0
    assert session.poll_job_empty() is True
    assert session.release_controls() is True


def test_owner_token_worker_binding_failure_keeps_suspended_session_unresumable():
    kernel = FakeKernel32()
    backend = windows_job.WindowsJobBackend(
        kernel32=kernel,
        advapi32=kernel,
        primary_token_handle=0x456,
        no_inherited_handles=True,
        process_created_callback=lambda _pid, _process: False,
    )

    session = backend.create_suspended_in_job(
        _command(), deadline_monotonic=time.monotonic() + 5.0
    )

    assert session.job_assignment_observed is None
    assert session.resume_launcher() is False
    assert "resume_thread" not in kernel.events
    assert session.terminate_job() is True
    assert session.poll_launcher_exit_code() == 0
    assert session.poll_job_empty() is True
    assert session.release_controls() is True


def test_no_inherited_handles_rejects_stdio_and_requires_owner_token_for_binding():
    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        windows_job.WindowsJobBackend(
            kernel32=FakeKernel32(),
            no_inherited_handles=True,
            inherited_stdout_handle=404,
        )
    assert captured.value.reason == "no_inherited_handles_conflict"

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        windows_job.WindowsJobBackend(
            kernel32=FakeKernel32(),
            process_created_callback=lambda _pid, _process: True,
        )
    assert captured.value.reason == "suspended_process_binding_invalid"


def test_owner_token_worker_has_only_job_and_result_stdio_handles_before_resume():
    kernel = FakeKernel32()
    backend = windows_job.WindowsJobBackend(
        kernel32=kernel,
        advapi32=kernel,
        primary_token_handle=0x456,
        inherited_stdin_handle=0x801,
        inherited_stdout_handle=0x802,
        inherited_stderr_handle=0x801,
    )

    session = backend.create_suspended_in_job(
        _command(), deadline_monotonic=time.monotonic() + 5.0
    )

    assert kernel.owner_token_handle == 0x456
    assert kernel.inherited_handle_values == (0x801, 0x802)
    assert kernel.create_args["stdin_handle"] == 0x801
    assert kernel.create_args["stdout_handle"] == 0x802
    assert kernel.create_args["stderr_handle"] == 0x801
    assert kernel.events.index("update_attributes") < kernel.events.index(
        "create_process_as_user"
    )
    assert session.job_assignment_observed is True
    assert session.resume_launcher() is True
    assert kernel.events.index("create_process_as_user") < kernel.events.index(
        "resume_thread"
    )
    assert session.poll_launcher_exit_code() == 0
    assert session.poll_job_empty() is True
    assert session.release_controls() is True


def test_worker_output_and_safe_nul_stdio_handles_are_allowlisted_exactly():
    kernel = FakeKernel32()
    backend = windows_job.WindowsJobBackend(
        kernel32=kernel,
        inherited_stdin_handle=405,
        inherited_stdout_handle=404,
        inherited_stderr_handle=405,
    )

    session = backend.create_suspended_in_job(
        _command(), deadline_monotonic=time.monotonic() + 5.0
    )

    assert kernel.create_args["inherit_handles"] is True
    assert kernel.create_args["startup_flags"] & windows_job._STARTF_USESTDHANDLES
    assert kernel.create_args["stdin_handle"] == 405
    assert kernel.create_args["stdout_handle"] == 404
    assert kernel.create_args["stderr_handle"] == 405
    assert tuple(
        ctypes.cast(
            kernel.output_handle_array_pointer, ctypes.POINTER(wintypes.HANDLE * 2)
        ).contents[:]
    ) == (405, 404)
    assert session.job_assignment_observed is True
    assert kernel.events.count("update_attributes") == 2
    assert session.resume_launcher() is True
    assert session.poll_launcher_exit_code() == 0
    assert session.poll_job_empty() is True
    assert session.release_controls() is True


def test_partial_worker_stdio_handle_binding_rejects():
    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        windows_job.WindowsJobBackend(
            kernel32=FakeKernel32(),
            inherited_stdout_handle=404,
        )

    assert captured.value.reason == "inherited_stdio_handles_invalid"


def test_worker_stdio_handle_allowlist_separates_input_output_and_error():
    kernel = FakeKernel32()
    backend = windows_job.WindowsJobBackend(
        kernel32=kernel,
        inherited_stdin_handle=401,
        inherited_stdout_handle=402,
        inherited_stderr_handle=403,
    )

    session = backend.create_suspended_in_job(
        _command(), deadline_monotonic=time.monotonic() + 5.0
    )

    assert kernel.create_args["stdin_handle"] == 401
    assert kernel.create_args["stdout_handle"] == 402
    assert kernel.create_args["stderr_handle"] == 403
    assert tuple(
        ctypes.cast(
            kernel.output_handle_array_pointer, ctypes.POINTER(wintypes.HANDLE * 3)
        ).contents[:]
    ) == (401, 402, 403)
    assert session.resume_launcher() is True
    assert session.poll_launcher_exit_code() == 0
    assert session.poll_job_empty() is True
    assert session.release_controls() is True


def test_invalid_owner_token_handle_rejects_without_service_token_fallback():
    kernel = FakeKernel32()

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        windows_job.WindowsJobBackend(
            kernel32=kernel,
            advapi32=kernel,
            primary_token_handle=True,
        )

    assert captured.value.reason == "primary_token_invalid"
    assert "create_process" not in kernel.events
    assert "create_process_as_user" not in kernel.events


def test_owner_token_privilege_failure_never_falls_back_to_service_token():
    kernel = FakeKernel32()
    kernel.as_user_create_result = False
    backend = windows_job.WindowsJobBackend(
        kernel32=kernel,
        advapi32=kernel,
        primary_token_handle=0x456,
    )

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        backend.create_suspended_in_job(
            _command(), deadline_monotonic=time.monotonic() + 5.0
        )

    assert captured.value.reason.startswith("owner_token_process_create_failed_")
    assert "create_process_as_user" in kernel.events
    assert "create_process" not in kernel.events


def test_unsupported_job_list_fails_closed_before_process_creation():
    kernel = FakeKernel32()
    kernel.update_success = False
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        backend.create_suspended_in_job(
            _command(), deadline_monotonic=time.monotonic() + 5.0
        )

    assert isinstance(captured.value, watchdog.OuterBackendCreationError)
    assert captured.value.reason == "job_list_attribute_unavailable"
    assert captured.value.retention_token is None
    assert "create_process" not in kernel.events
    assert ("close_handle", kernel.job_handle) in kernel.events


def test_expired_attribute_setup_never_creates_launcher(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(windows_job, "_monotonic", lambda: now[0])
    kernel = FakeKernel32()
    kernel.after_attribute_update = lambda: now.__setitem__(0, 10.0)
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        backend.create_suspended_in_job(_command(), deadline_monotonic=10.0)

    assert captured.value.reason == "outer_deadline_expired"
    assert "update_attributes" in kernel.events
    assert "create_process" not in kernel.events
    assert "delete_attributes" in kernel.events
    assert ("close_handle", kernel.job_handle) in kernel.events


def test_unexpected_job_member_count_is_unknown_and_launcher_stays_suspended():
    kernel = FakeKernel32()
    kernel.active_after_create = 2
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    session = backend.create_suspended_in_job(
        _command(), deadline_monotonic=time.monotonic() + 5.0
    )

    assert session.job_assignment_observed is None
    assert session.resume_launcher() is False
    assert "resume_thread" not in kernel.events
    assert session.terminate_launcher_process() is True
    assert session.poll_launcher_exit_code() == 0
    assert session.poll_job_empty() is True
    assert session.release_controls() is True


def test_watchdog_terminates_job_and_suspended_launcher_when_assignment_is_unknown():
    kernel = FakeKernel32()
    kernel.active_after_create = 2
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=time.monotonic() + 5.0,
    )

    assert result.state == "unknown"
    assert result.reason == "job_assignment_unconfirmed"
    assert result.evidence.job_assignment_observed is None
    assert result.evidence.launcher_resumed is False
    assert result.evidence.job_termination_requested is True
    assert result.evidence.job_termination_call_succeeded is True
    assert result.evidence.launcher_termination_requested is True
    assert result.evidence.launcher_termination_call_succeeded is True
    assert result.evidence.launcher_exit_observed is True
    assert result.evidence.job_empty_observed is True
    assert result.evidence.controls_retained is False
    assert "resume_thread" not in kernel.events
    assert "terminate_job" in kernel.events
    assert "terminate_process" in kernel.events


def test_setup_close_failure_returns_token_for_orphan_job():
    kernel = FakeKernel32()
    kernel.set_job_success = False
    kernel.fail_close_once.add(kernel.job_handle)
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        backend.create_suspended_in_job(
            _command(), deadline_monotonic=time.monotonic() + 5.0
        )

    token = captured.value.retention_token
    assert isinstance(token, str) and token.startswith("outerjob-")
    assert token in backend.retained_tokens()
    resolution = backend.resolve_retained_controls(token, timeout_seconds=0.0)
    assert resolution.controls_released is True
    assert resolution.job_empty_observed is True
    assert token not in backend.retained_tokens()


def test_base_exception_during_job_setup_closes_or_escrows_before_return():
    kernel = FakeKernel32()
    kernel.raise_on_set_job = KeyboardInterrupt()
    kernel.fail_close_once.add(kernel.job_handle)
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        backend.create_suspended_in_job(
            _command(), deadline_monotonic=time.monotonic() + 5.0
        )

    token = captured.value.retention_token
    assert isinstance(token, str)
    assert captured.value.reason == "job_kill_on_close_setup_failed"
    assert token in backend.retained_tokens()
    assert "create_process" not in kernel.events
    assert backend.resolve_retained_controls(token, timeout_seconds=0.0).controls_released


def test_ambiguous_create_is_terminated_and_escrowed_with_creation_token():
    kernel = FakeKernel32()
    kernel.raise_after_process_info = RuntimeError("injected native seam failure")
    kernel.fail_close_once.add(kernel.process_handle)
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        backend.create_suspended_in_job(
            _command(), deadline_monotonic=time.monotonic() + 5.0
        )

    error = captured.value
    assert isinstance(error, watchdog.OuterBackendCreationError)
    assert error.reason == "atomic_job_process_create_outcome_unknown"
    assert error.retention_token in backend.retained_tokens()
    assert "terminate_job" in kernel.events
    assert "terminate_process" in kernel.events
    resolution = backend.resolve_retained_controls(error.retention_token, timeout_seconds=0.0)
    assert resolution.controls_released is True


def test_thread_only_partial_output_is_escrowed_without_closing_native_handles():
    kernel = FakeKernel32()
    kernel.raise_after_process_info = RuntimeError("partial CreateProcessW output")
    kernel.thread_only_after_process_info = True
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        backend.create_suspended_in_job(
            _command(), deadline_monotonic=time.monotonic() + 5.0
        )

    token = captured.value.retention_token
    assert isinstance(token, str)
    assert captured.value.reason == "atomic_job_process_create_outcome_unknown"
    assert token in backend.retained_tokens()
    retained = windows_job._CUSTODIAN._retained_sessions[token]
    assert retained._process_handle is None
    assert retained._thread_handle == kernel.thread_handle
    assert retained._job_handle == kernel.job_handle
    assert retained._attribute_list is not None
    assert retained._job_handle_array is not None
    assert not any(
        event == ("close_handle", kernel.thread_handle)
        or event == ("close_handle", kernel.job_handle)
        for event in kernel.events
    )
    assert "resume_thread" not in kernel.events

    unresolved = backend.resolve_retained_controls(token, timeout_seconds=0.0)
    assert unresolved.state == "unknown"
    assert unresolved.controls_released is False
    assert token in backend.retained_tokens()
    # Simulate process-owner shutdown so this negative test leaves no fake
    # handles or custodian entry behind for later tests.
    retained._close_for_host_exit()
    retained._custodian.forget_session(retained)


def test_false_create_result_with_thread_only_output_is_escrowed():
    kernel = FakeKernel32()
    kernel.create_result = False
    kernel.thread_only_after_process_info = True
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        backend.create_suspended_in_job(
            _command(), deadline_monotonic=time.monotonic() + 5.0
        )

    token = captured.value.retention_token
    assert isinstance(token, str)
    assert captured.value.reason == "atomic_job_process_create_failed"
    assert token in backend.retained_tokens()
    retained = windows_job._CUSTODIAN._retained_sessions[token]
    assert retained._process_handle is None
    assert retained._thread_handle == kernel.thread_handle
    assert retained._job_handle == kernel.job_handle
    assert not any(
        event == ("close_handle", kernel.thread_handle)
        or event == ("close_handle", kernel.job_handle)
        for event in kernel.events
    )
    assert "resume_thread" not in kernel.events

    unresolved = backend.resolve_retained_controls(token, timeout_seconds=0.0)
    assert unresolved.state == "unknown"
    assert unresolved.controls_released is False
    assert token in backend.retained_tokens()
    retained._close_for_host_exit()
    retained._custodian.forget_session(retained)


def test_runner_token_survives_backend_and_result_collection():
    kernel = FakeKernel32()
    kernel.fail_close_once.add(kernel.process_handle)
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=time.monotonic() + 5.0,
    )

    assert result.state == "unknown"
    assert result.evidence.controls_retained is True
    token = result.evidence.retention_token
    assert isinstance(token, str) and token in backend.retained_tokens()
    retained_session = windows_job._CUSTODIAN._retained_sessions[token]
    session_ref = weakref.ref(retained_session)
    del retained_session
    del result
    del backend
    gc.collect()
    assert session_ref() is not None

    resolver = windows_job.WindowsJobBackend(kernel32=kernel)
    resolution = resolver.resolve_retained_controls(token, timeout_seconds=0.0)
    assert resolution.controls_released is True
    assert token not in resolver.retained_tokens()
    assert session_ref() is None


def test_unresolved_job_remains_unknown_until_empty_is_observed():
    kernel = FakeKernel32()
    kernel.raise_after_process_info = RuntimeError("injected native seam failure")
    kernel.never_drain = True
    backend = windows_job.WindowsJobBackend(kernel32=kernel)

    with pytest.raises(windows_job.WindowsJobBackendError) as captured:
        backend.create_suspended_in_job(
            _command(), deadline_monotonic=time.monotonic() + 5.0
        )

    token = captured.value.retention_token
    assert isinstance(token, str)
    unresolved = backend.resolve_retained_controls(token, timeout_seconds=0.0)
    assert unresolved.state == "unknown"
    assert unresolved.job_empty_observed is False
    assert unresolved.controls_released is False

    kernel.active = 0
    kernel.process_signaled = True
    resolved = backend.resolve_retained_controls(token, timeout_seconds=0.0)
    assert resolved.state == "resolved"
    assert resolved.process_exit_observed is True
    assert resolved.job_empty_observed is True
    assert resolved.controls_released is True


@pytest.mark.skipif(
    os.name != "nt"
    or sys.getwindowsversion().major < 10
    or sys.getwindowsversion().build < 14393,
    reason="PROC_THREAD_ATTRIBUTE_JOB_LIST needs Windows 10 / Server 2016 or newer",
)
def test_windows_inert_python_child_runs_inside_job():
    command = watchdog.FixedOuterCommand(
        [os.path.abspath(sys.executable), "-I", "-c", "pass"],
        os.getcwd(),
        {
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
            "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
        },
    )
    backend = windows_job.WindowsJobBackend()
    result = watchdog.run_outer_watchdog(
        command,
        backend=backend,
        deadline_monotonic=time.monotonic() + 10.0,
    )

    assert result.evidence.job_assignment_observed is True
    assert result.evidence.launcher_exit_observed is True
    assert result.evidence.launcher_exit_code == 0
    if result.state == "exited":
        assert result.reason == "launcher_exited_job_empty"
        assert result.evidence.job_termination_requested is False
        assert result.evidence.job_termination_call_succeeded is None
    else:
        assert result.state == "failed"
        assert result.reason == "descendant_or_job_state_unconfirmed"
        assert result.evidence.job_termination_requested is True
        assert result.evidence.job_termination_call_succeeded is True
    assert result.evidence.job_empty_observed is True
    assert result.evidence.containment == "verified"
    assert result.evidence.controls_retained is False


@pytest.mark.skipif(
    os.name != "nt"
    or sys.getwindowsversion().major < 10
    or sys.getwindowsversion().build < 14393,
    reason="PROC_THREAD_ATTRIBUTE_JOB_LIST needs Windows 10 / Server 2016 or newer",
)
def test_windows_p14_false_terminate_keeps_inert_job_unknown_and_custodied(tmp_path):
    """A false TerminateJobObject observation must not upgrade real Job cleanup."""

    class FalseTerminateKernel32:
        """Forward real Win32 calls but inject FALSE at the P14 return boundary."""

        def __init__(self, delegate):
            self.delegate = delegate
            self.terminate_calls = 0

        def __getattr__(self, name):
            return getattr(self.delegate, name)

        def TerminateJobObject(self, _job, _exit_code):
            self.terminate_calls += 1
            return False

    marker = tmp_path / "inert-child-started.txt"
    child_code = (
        "from pathlib import Path; import time; "
        f"Path({str(marker)!r}).write_text('started', encoding='ascii'); "
        "time.sleep(60)"
    )
    executable = os.path.abspath(sys.executable)
    command = watchdog.FixedOuterCommand(
        [executable, "-I", "-S", "-B", "-c", child_code],
        str(tmp_path),
        {
            "PATH": os.path.dirname(executable),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
            "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
        },
    )
    kernel = FalseTerminateKernel32(windows_job._load_kernel32())
    backend = windows_job.WindowsJobBackend(kernel32=kernel)
    started = time.monotonic()
    deadline = started + 1.5

    result = watchdog.run_outer_watchdog(
        command,
        backend=backend,
        stop_deadline_monotonic=deadline,
        deadline_monotonic=deadline,
        abort_requested=lambda: (
            "p14_inert_child_started" if marker.exists() else None
        ),
        monotonic=time.monotonic,
    )

    assert marker.exists()
    assert kernel.terminate_calls >= 1
    assert result.state == "unknown"
    assert result.evidence.job_termination_requested is True
    assert result.evidence.job_termination_call_succeeded is False
    assert result.evidence.launcher_exit_observed is not True
    assert result.evidence.job_empty_observed is False
    assert result.evidence.containment == "unknown"
    assert result.evidence.controls_retained is True
    token = result.evidence.retention_token
    assert isinstance(token, str)
    assert token in backend.retained_tokens()

    # Test-owned cleanup uses the real API after the negative assertion; the
    # candidate must keep the unresolved Job controls until this is observed.
    session = windows_job._CUSTODIAN._retained_sessions[token]
    assert session._job_handle is not None
    assert kernel.delegate.TerminateJobObject(session._job_handle, 0xEE13)
    resolution = windows_job.WindowsJobBackend().resolve_retained_controls(
        token, timeout_seconds=3.0
    )
    assert resolution.state == "resolved"
    assert resolution.process_exit_observed is True
    assert resolution.job_empty_observed is True
    assert resolution.controls_released is True
    assert token not in backend.retained_tokens()


@pytest.mark.skipif(
    os.name != "nt"
    or sys.getwindowsversion().major < 10
    or sys.getwindowsversion().build < 14393,
    reason="PROC_THREAD_ATTRIBUTE_JOB_LIST needs Windows 10 / Server 2016 or newer",
)
def test_windows_restart_ticket_cannot_recover_process_local_job_custody(tmp_path):
    """A fresh supervisor must reject an opaque token it cannot actually own."""

    repo_root = Path(__file__).resolve().parents[3]
    executable = str(Path(sys.executable).resolve())
    ticket_path = tmp_path / "inert-job-ticket.json"
    marker_path = tmp_path / "inert-child-started.txt"
    supervisor_script = tmp_path / "job_owner_supervisor.py"
    supervisor_script.write_text(
        "\n".join(
            [
                "import ctypes, json, os, sys, time",
                "from ctypes import wintypes",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(repo_root)!r})",
                "from scripts import ctp_i13_i15_outer_watchdog as watchdog",
                "from scripts import ctp_i13_i15_windows_job_backend as job_backend",
                "repo_root, ticket_path, marker_path, workdir, executable = sys.argv[1:]",
                "marker = Path(marker_path)",
                "child_code = (",
                "    'from pathlib import Path; import time; '",
                "    + f\"Path({str(marker)!r}).write_text('started', encoding='ascii'); \"",
                "    + 'time.sleep(120)'",
                ")",
                "command = watchdog.FixedOuterCommand(",
                "    [executable, '-I', '-S', '-B', '-c', child_code],",
                "    workdir,",
                "    {'PATH': str(Path(executable).parent), 'SYSTEMROOT': os.environ.get('SYSTEMROOT', r'C:\\Windows'), 'WINDIR': os.environ.get('WINDIR', r'C:\\Windows')},",
                ")",
                "backend = job_backend.WindowsJobBackend()",
                "session = backend.create_suspended_in_job(command, deadline_monotonic=time.monotonic() + 30.0)",
                "if session.resume_launcher() is not True:",
                "    raise RuntimeError('inert_child_resume_failed')",
                "kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)",
                "kernel32.GetProcessId.argtypes = [wintypes.HANDLE]",
                "kernel32.GetProcessId.restype = wintypes.DWORD",
                "child_pid = int(kernel32.GetProcessId(wintypes.HANDLE(session._process_handle)))",
                "token = backend.retain_controls(session)",
                "if type(token) is not str:",
                "    raise RuntimeError('inert_job_custody_token_unavailable')",
                "deadline = time.monotonic() + 10.0",
                "while not marker.exists() and time.monotonic() < deadline:",
                "    time.sleep(0.01)",
                "if not marker.exists():",
                "    raise RuntimeError('inert_child_start_unobserved')",
                "Path(ticket_path).write_text(json.dumps({'schema': 'inert_job_custody_probe.v1', 'retention_token': token, 'child_pid': child_pid}, sort_keys=True), encoding='ascii')",
                "while True:",
                "    time.sleep(1.0)",
            ]
        ),
        encoding="utf-8",
    )
    recovery_script = tmp_path / "recover_job_ticket.py"
    recovery_script.write_text(
        "\n".join(
            [
                "import json, sys",
                "from pathlib import Path",
                "sys.path.insert(0, sys.argv[1])",
                "from scripts.ctp_i13_i15_windows_job_backend import WindowsJobBackend",
                "ticket = json.loads(Path(sys.argv[2]).read_text(encoding='ascii'))",
                "result = WindowsJobBackend().resolve_retained_controls(ticket['retention_token'], timeout_seconds=0.0)",
                "print(json.dumps({'state': result.state, 'reason': result.reason, 'process_exit_observed': result.process_exit_observed, 'job_empty_observed': result.job_empty_observed, 'controls_released': result.controls_released}, sort_keys=True))",
            ]
        ),
        encoding="utf-8",
    )

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
    supervisor = None
    child_handle = None
    try:
        supervisor = subprocess.Popen(
            [
                executable,
                "-I",
                "-S",
                "-B",
                str(supervisor_script),
                str(repo_root),
                str(ticket_path),
                str(marker_path),
                str(tmp_path),
                executable,
            ],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        wait_deadline = time.monotonic() + 15.0
        while not ticket_path.exists() and time.monotonic() < wait_deadline:
            if supervisor.poll() is not None:
                stdout, stderr = supervisor.communicate(timeout=2.0)
                pytest.fail(
                    "ticket owner exited before writing ticket: "
                    f"exit={supervisor.returncode} stdout={stdout!r} stderr={stderr!r}"
                )
            time.sleep(0.02)
        assert ticket_path.exists(), "ticket owner did not publish inert custody ticket"
        ticket = json.loads(ticket_path.read_text(encoding="ascii"))
        assert ticket["schema"] == "inert_job_custody_probe.v1"
        assert marker_path.exists()
        child_handle = kernel32.OpenProcess(
            synchronize | process_terminate, False, int(ticket["child_pid"])
        )
        assert child_handle
        assert kernel32.WaitForSingleObject(child_handle, 0) == wait_timeout

        # This emulates abrupt loss of the process that owns both Job/process
        # handles. KILL_ON_JOB_CLOSE should terminate the inert child; restart
        # can read the ticket but cannot reconstruct the process-local custody.
        supervisor.kill()
        supervisor.communicate(timeout=5.0)
        assert kernel32.WaitForSingleObject(child_handle, 10_000) == wait_object_0

        recovered = subprocess.run(
            [
                executable,
                "-I",
                "-S",
                "-B",
                str(recovery_script),
                str(repo_root),
                str(ticket_path),
            ],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10.0,
            check=False,
        )
        assert recovered.returncode == 0, recovered.stderr
        recovery = json.loads(recovered.stdout)
        assert recovery == {
            "state": "unknown",
            "reason": "retention_token_unknown",
            "process_exit_observed": None,
            "job_empty_observed": None,
            "controls_released": False,
        }
    finally:
        if supervisor is not None and supervisor.poll() is None:
            supervisor.kill()
            supervisor.communicate(timeout=5.0)
        if child_handle:
            if kernel32.WaitForSingleObject(child_handle, 0) == wait_timeout:
                kernel32.TerminateProcess(child_handle, 0xEE13)
                kernel32.WaitForSingleObject(child_handle, 10_000)
            kernel32.CloseHandle(child_handle)
