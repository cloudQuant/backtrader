"""Fake-only frame contracts plus service-free Windows named-pipe smoke tests."""

from __future__ import annotations

import ctypes
import json
import os
import struct
import sys
import time
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ctp_i13_i15_worker_output_channel as output_channel
from scripts import ctp_i13_i15_outer_watchdog as watchdog
from scripts import ctp_i13_i15_windows_job_backend as windows_job


REQUEST_ID = "a" * 32
NONCE = "b" * 32


def _worker_output(pad: str = "") -> bytes:
    return json.dumps(
        {"observation": {"pad": pad}, "schema": output_channel.WORKER_SCHEMA},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _outer_result(*, state="exited", reason="launcher_exited_job_empty", exit_code=0):
    return watchdog.OuterWatchdogResult(
        state=state,
        reason=reason,
        evidence=watchdog.OuterProcessEvidence(
            process_created=True,
            job_assignment_observed=True,
            launcher_resumed=True,
            launcher_exit_observed=True,
            launcher_exit_code=exit_code,
            launcher_termination_requested=False,
            launcher_termination_call_succeeded=None,
            job_termination_requested=False,
            job_termination_call_succeeded=None,
            job_empty_observed=True,
            containment="verified",
            controls_retained=False,
            retention_token=None,
        ),
    )


def _readable_channel(result, *, close=None):
    channel = object.__new__(output_channel.WorkerOutputChannel)
    channel._supervision_request_id = REQUEST_ID
    channel._supervision_result = result
    channel._worker_pid = 12
    channel._worker_handle = 10
    channel._worker_creation_time = (0, 13)
    channel._supervision_worker_identity = (12, 10, (0, 13))
    channel._peer_pid = 12
    channel._peer_handle = 11
    channel._closed = False
    channel._close_attempted = False
    channel._close_deadline_missed = False
    channel._deadline_monotonic = None
    channel._failure = None
    channel._eof = True
    channel._frame_message = output_channel._encode_frame(
        _worker_output(), request_id=REQUEST_ID, nonce=NONCE
    )
    channel._supervision_poll_count = 1
    channel._kernel32 = SimpleNamespace(WaitForSingleObject=lambda *_args: 0)
    close_callback = close or (lambda: True)
    channel.close = lambda **_kwargs: close_callback()
    return channel


def test_frame_is_one_canonical_ascii_big_endian_record():
    raw = _worker_output()
    framed = output_channel._encode_frame(raw, request_id=REQUEST_ID, nonce=NONCE)
    size = struct.unpack(">I", framed[:4])[0]

    assert size == len(framed) - 4
    assert size <= output_channel.MAX_FRAME_BYTES
    assert output_channel._decode_frame(
        framed, request_id=REQUEST_ID, nonce=NONCE
    ) == raw


def test_bounded_transport_does_not_choose_a_stage_payload_schema():
    payload = b'{"request_id":"' + REQUEST_ID.encode("ascii") + b'","schema":"fixed-stage-owned"}'
    frame = struct.pack(">I", len(payload)) + payload
    assert output_channel._validate_bounded_frame(frame) == frame


def test_worker_channel_requires_distinct_canonical_service_and_owner_sids(monkeypatch):
    monkeypatch.setattr(
        output_channel,
        "_load_kernel32",
        lambda: pytest.fail("SID policy must reject before opening Windows handles"),
    )
    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        output_channel.create_worker_output_channel(
            service_sid="S-1-5-18", client_sid="S-1-5-18"
        )
    assert caught.value.reason == "worker_output_identity_collision"

    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        output_channel.create_worker_output_channel(
            service_sid="S-01-5-18", client_sid="S-1-5-19"
        )
    assert caught.value.reason == "worker_output_identity_invalid"


def test_service_stage_factory_has_no_client_sid_override(monkeypatch):
    observed = {}

    def capture_channel(**kwargs):
        observed.update(kwargs)
        return "service-stage-channel"

    monkeypatch.setattr(output_channel, "_create_bounded_output_channel", capture_channel)
    result = output_channel.create_service_stage_output_channel(service_sid="S-1-5-80-17")
    assert result == "service-stage-channel"
    assert observed == {"service_sid": "S-1-5-80-17", "client_sid": None}


def test_output_watchdog_wrapper_always_polls_bound_channel(monkeypatch):
    channel = object.__new__(output_channel.WorkerOutputChannel)
    poll_calls = []

    def poll_abort_reason():
        poll_calls.append(True)

    channel.poll_abort_reason = poll_abort_reason
    channel._worker_pid = 12
    channel._worker_handle = 13
    channel._worker_creation_time = (0, 14)
    channel._supervision_result = None
    channel._supervision_request_id = None
    observed = {}

    def fake_run_outer_watchdog(
        command,
        *,
        backend,
        deadline_monotonic,
        stop_deadline_monotonic,
        abort_requested,
        after_resume,
    ):
        observed["abort_requested"] = abort_requested
        observed["after_resume"] = after_resume
        assert abort_requested() is None
        assert abort_requested() is None
        return _outer_result()

    monkeypatch.setattr(watchdog, "run_outer_watchdog", fake_run_outer_watchdog)
    result = output_channel.run_child_with_output_channel(
        channel,
        command="fixed-command",
        backend="fixed-backend",
        request_id=REQUEST_ID,
        deadline_monotonic=10.0,
        stop_deadline_monotonic=9.0,
    )
    assert result is channel._supervision_result
    assert observed["abort_requested"] == poll_abort_reason
    assert observed["after_resume"] is None
    assert len(poll_calls) == 2


def test_after_resume_failure_result_cannot_reach_frame_reader(monkeypatch):
    channel = _readable_channel(_outer_result())
    channel._supervision_result = None
    channel._supervision_request_id = None
    channel._supervision_worker_identity = None
    callback_calls = []

    def after_resume():
        callback_calls.append(True)
        return "token_bootstrap_send_failed"

    def failed_watchdog(
        _command,
        *,
        abort_requested,
        after_resume,
        **_kwargs,
    ):
        assert abort_requested == channel.poll_abort_reason
        assert after_resume() == "token_bootstrap_send_failed"
        return _outer_result(
            state="unknown", reason="token_bootstrap_send_failed"
        )

    monkeypatch.setattr(watchdog, "run_outer_watchdog", failed_watchdog)
    result = output_channel.run_child_with_output_channel(
        channel,
        command="fixed-command",
        backend="fixed-backend",
        request_id=REQUEST_ID,
        deadline_monotonic=10.0,
        after_resume=after_resume,
    )
    assert result is channel._supervision_result
    assert callback_calls == [True]
    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        channel.read_frame_after_job_empty(
            request_id=REQUEST_ID,
            outer_result=result,
            deadline_monotonic=10.0,
        )
    assert caught.value.reason == "worker_output_job_empty_unverified"


def test_expired_after_resume_result_cannot_reach_frame_reader(monkeypatch):
    channel = _readable_channel(_outer_result())
    channel._supervision_result = None
    channel._supervision_request_id = None
    channel._supervision_worker_identity = None
    expired = _outer_result(state="timed_out", reason="outer_deadline_exceeded")

    def expired_watchdog(
        _command,
        *,
        abort_requested,
        after_resume,
        **_kwargs,
    ):
        assert abort_requested == channel.poll_abort_reason
        assert after_resume() is None
        return expired

    monkeypatch.setattr(watchdog, "run_outer_watchdog", expired_watchdog)
    result = output_channel.run_child_with_output_channel(
        channel,
        command="fixed-command",
        backend="fixed-backend",
        request_id=REQUEST_ID,
        deadline_monotonic=10.0,
        after_resume=lambda: None,
    )
    assert result is channel._supervision_result
    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        channel.read_frame_after_job_empty(
            request_id=REQUEST_ID,
            outer_result=result,
            deadline_monotonic=10.0,
        )
    assert caught.value.reason == "worker_output_job_empty_unverified"


def test_output_frame_is_not_published_without_supervision_poll_or_job_cleanup():
    completed = _outer_result()
    channel = _readable_channel(completed)
    channel._supervision_poll_count = 0
    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        channel.read_frame_after_job_empty(
            request_id=REQUEST_ID,
            outer_result=completed,
            deadline_monotonic=10.0,
        )
    assert caught.value.reason == "worker_output_drain_unobserved"

    unknown = _outer_result(state="unknown", reason="control_release_unconfirmed")
    channel = _readable_channel(unknown)
    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        channel.read_frame_after_job_empty(
            request_id=REQUEST_ID,
            outer_result=unknown,
            deadline_monotonic=10.0,
        )
    assert caught.value.reason == "worker_output_job_empty_unverified"


def test_output_frame_is_not_published_when_channel_close_is_unconfirmed(monkeypatch):
    channel = _readable_channel(_outer_result(), close=lambda: False)
    monkeypatch.setattr(output_channel, "_process_id", lambda _kernel32, _handle: 12)
    monkeypatch.setattr(
        output_channel,
        "_process_creation_time",
        lambda _kernel32, _handle: (0, 13),
    )

    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        channel.read_frame_after_job_empty(
            request_id=REQUEST_ID,
            outer_result=channel._supervision_result,
            deadline_monotonic=10.0,
        )
    assert caught.value.reason == "worker_output_channel_close_unconfirmed"


def test_extra_pipe_bytes_fail_closed_after_one_complete_frame():
    channel = object.__new__(output_channel.WorkerOutputChannel)
    channel._connected = True
    channel._eof = False
    channel._frame_message = b"one-complete-frame"
    channel._pipe_handle = 7

    def peek(_handle, _buffer, _buffer_size, _read, available, total):
        available._obj.value = 1
        total._obj.value = 1
        return 1

    channel._kernel32 = SimpleNamespace(PeekNamedPipe=peek)
    channel._poll_eof_or_extra()
    assert channel._failure == "worker_output_extra_frame"


def test_duck_typed_outer_result_cannot_publish_a_frame(monkeypatch):
    authentic_shape = _outer_result()
    fake = SimpleNamespace(
        state=authentic_shape.state,
        reason=authentic_shape.reason,
        evidence=authentic_shape.evidence,
    )
    channel = _readable_channel(fake)
    monkeypatch.setattr(output_channel, "_process_id", lambda _kernel32, _handle: 12)
    monkeypatch.setattr(
        output_channel,
        "_process_creation_time",
        lambda _kernel32, _handle: (0, 13),
    )
    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        channel.read_frame_after_job_empty(
            request_id=REQUEST_ID,
            outer_result=fake,
            deadline_monotonic=10.0,
        )
    assert caught.value.reason == "worker_output_job_empty_unverified"


def test_outer_result_must_be_exact_object_from_same_request_run():
    completed = _outer_result()
    channel = _readable_channel(completed)
    same_shape_other_run = _outer_result()
    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        channel.read_frame_after_job_empty(
            request_id=REQUEST_ID,
            outer_result=same_shape_other_run,
            deadline_monotonic=10.0,
        )
    assert caught.value.reason == "worker_output_job_empty_unverified"

    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        channel.read_frame_after_job_empty(
            request_id="c" * 32,
            outer_result=completed,
            deadline_monotonic=10.0,
        )
    assert caught.value.reason == "worker_output_job_empty_unverified"

    channel._worker_handle = 99
    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        channel.read_frame_after_job_empty(
            request_id=REQUEST_ID,
            outer_result=completed,
            deadline_monotonic=10.0,
        )
    assert caught.value.reason == "worker_output_job_empty_unverified"


def test_bound_worker_must_be_signaled_even_with_completed_watchdog_result(monkeypatch):
    channel = _readable_channel(_outer_result())
    channel._kernel32 = SimpleNamespace(WaitForSingleObject=lambda *_args: 0x102)
    monkeypatch.setattr(output_channel, "_process_id", lambda _kernel32, _handle: 12)
    monkeypatch.setattr(
        output_channel,
        "_process_creation_time",
        lambda _kernel32, _handle: (0, 13),
    )
    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        channel.read_frame_after_job_empty(
            request_id=REQUEST_ID,
            outer_result=channel._supervision_result,
            deadline_monotonic=10.0,
        )
    assert caught.value.reason == "worker_output_process_exit_unobserved"


def test_generic_frame_read_accepts_clean_exit_code_two_for_fixed_role_parser(monkeypatch):
    result = _outer_result(exit_code=2)
    deadline = time.monotonic() + 10.0
    channel = _readable_channel(result)
    channel._supervision_result = None
    channel._supervision_request_id = None
    channel._supervision_worker_identity = None
    monkeypatch.setattr(watchdog, "run_outer_watchdog", lambda *_args, **_kwargs: result)
    supervised_result = output_channel.run_child_with_output_channel(
        channel,
        command="fixed-command",
        backend="fixed-backend",
        request_id=REQUEST_ID,
        deadline_monotonic=deadline,
    )
    assert supervised_result is result
    monkeypatch.setattr(output_channel, "_process_id", lambda _kernel32, _handle: 12)
    monkeypatch.setattr(
        output_channel,
        "_process_creation_time",
        lambda _kernel32, _handle: (0, 13),
    )

    frame = channel.read_frame_after_job_empty(
        request_id=REQUEST_ID,
        outer_result=supervised_result,
        deadline_monotonic=deadline,
    )

    envelope = output_channel._parse_canonical_object(
        frame, reason="worker_output_frame_invalid"
    )
    assert envelope["request_id"] == REQUEST_ID
    assert envelope["receipt_nonce"] == NONCE
    assert envelope["schema"] == output_channel.FRAME_SCHEMA


def test_constructor_closes_pipe_and_pending_accept_after_accept_failure(monkeypatch):
    class ApiFunction:
        def __init__(self, result):
            self.result = result
            self.calls = []

        def __call__(self, *args):
            self.calls.append(args)
            return self.result

    cancel_io = ApiFunction(1)
    close_handle = ApiFunction(1)
    wait = ApiFunction(output_channel._WAIT_OBJECT_0)
    kernel32 = SimpleNamespace(
        CancelIoEx=cancel_io,
        CloseHandle=close_handle,
        WaitForSingleObject=wait,
    )
    monkeypatch.setattr(output_channel, "_load_kernel32", lambda: kernel32)
    monkeypatch.setattr(
        output_channel._BoundedOutputChannel, "_load_winapi", lambda _self: object()
    )
    monkeypatch.setattr(output_channel._BoundedOutputChannel, "_current_pid", lambda _self: 42)

    def create_pipe(channel):
        channel._pipe_handle = 99

    def begin_accept(channel):
        class CompletedOverlapped:
            event = 101

            @staticmethod
            def GetOverlappedResult(_wait):
                raise _Win32Error(output_channel._ERROR_OPERATION_ABORTED)

        channel._connect_overlapped = CompletedOverlapped()
        raise output_channel.WorkerOutputChannelError("worker_output_pipe_accept_failed")

    monkeypatch.setattr(output_channel._BoundedOutputChannel, "_create_server_pipe", create_pipe)
    monkeypatch.setattr(output_channel._BoundedOutputChannel, "_begin_accept", begin_accept)

    with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
        output_channel.WorkerOutputChannel(
            service_sid="S-1-5-18",
            client_sid="S-1-5-19",
            nonce=NONCE,
        )

    assert caught.value.reason == "worker_output_pipe_accept_failed"
    assert len(cancel_io.calls) == 1
    assert len(close_handle.calls) == 1
    assert output_channel._FAILED_CONSTRUCTOR_CHANNELS == []


def _pending_close_channel(overlapped, *, kernel32, pending_attribute="_connect_overlapped"):
    channel = object.__new__(output_channel._BoundedOutputChannel)
    channel._kernel32 = kernel32
    channel._pipe_handle = 90
    channel._security_descriptor_handle = None
    channel._connect_overlapped = None
    channel._read_overlapped = None
    setattr(channel, pending_attribute, overlapped)
    channel._peer_handle = None
    channel._worker_handle = None
    channel._closed = False
    channel._close_attempted = False
    channel._close_deadline_missed = False
    channel._deadline_monotonic = None
    return channel


class _Win32Error(OSError):
    def __init__(self, code):
        super().__init__(code, "fake overlapped result")
        self.winerror = code


@pytest.mark.parametrize("pending_attribute", ["_connect_overlapped", "_read_overlapped"])
def test_close_waits_for_delayed_cancellation_completion_before_handle_release(
    pending_attribute,
):
    class DelayedCompletion:
        event = 101

        def __init__(self):
            self.pending = True
            self.polls = 0

        def GetOverlappedResult(self, _wait):
            self.polls += 1
            if self.pending:
                raise _Win32Error(output_channel._ERROR_IO_INCOMPLETE)
            raise _Win32Error(output_channel._ERROR_OPERATION_ABORTED)

    clock = [0.0]
    overlap = DelayedCompletion()
    call_order = []

    class ApiFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    def wait(_event, timeout_ms):
        assert timeout_ms > 0
        call_order.append("wait")
        clock[0] += 0.1
        if clock[0] >= 0.3:
            overlap.pending = False
            return output_channel._WAIT_OBJECT_0
        return output_channel._WAIT_TIMEOUT

    def close(handle):
        assert overlap.pending is False
        call_order.append(("close", int(handle.value)))
        return 1

    kernel32 = SimpleNamespace(
        CancelIoEx=ApiFunction(lambda *_args: call_order.append("cancel") or 1),
        CloseHandle=ApiFunction(close),
        WaitForSingleObject=ApiFunction(wait),
    )
    channel = _pending_close_channel(
        overlap, kernel32=kernel32, pending_attribute=pending_attribute
    )

    assert channel.close(deadline_monotonic=1.0, monotonic=lambda: clock[0]) is True
    assert overlap.polls >= 4
    assert call_order[0] == "cancel"
    assert call_order[-1] == ("close", 90)
    assert getattr(channel, pending_attribute) is None
    assert channel._pipe_handle is None
    assert channel._closed is True
    assert channel not in output_channel._RETAINED_UNRESOLVED_CHANNELS


@pytest.mark.parametrize("cancel_error", [None, 1168, 5])
@pytest.mark.parametrize("pending_attribute", ["_connect_overlapped", "_read_overlapped"])
def test_close_retains_pending_overlapped_and_handles_when_completion_never_arrives(
    monkeypatch, cancel_error, pending_attribute
):
    class NeverCompletes:
        event = 102
        completed = False

        def GetOverlappedResult(self, _wait):
            if self.completed:
                raise _Win32Error(output_channel._ERROR_OPERATION_ABORTED)
            raise _Win32Error(output_channel._ERROR_IO_INCOMPLETE)

    clock = [0.0]
    overlap = NeverCompletes()
    close_calls = []
    observed_cancel_errors = []

    class ApiFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    def cancel(*_args):
        if cancel_error is not None:
            return 0
        return 1

    def fake_winerror(_kernel):
        observed_cancel_errors.append(cancel_error)
        return cancel_error or 0

    monkeypatch.setattr(output_channel, "_winerror", fake_winerror)

    def wait(_event, timeout_ms):
        assert timeout_ms > 0
        clock[0] = 2.0
        return output_channel._WAIT_TIMEOUT

    kernel32 = SimpleNamespace(
        CancelIoEx=ApiFunction(cancel),
        CloseHandle=ApiFunction(lambda handle: close_calls.append(int(handle.value)) or 1),
        WaitForSingleObject=ApiFunction(wait),
    )
    channel = _pending_close_channel(
        overlap, kernel32=kernel32, pending_attribute=pending_attribute
    )

    try:
        assert channel.close(deadline_monotonic=2.0, monotonic=lambda: clock[0]) is False
        assert getattr(channel, pending_attribute) is overlap
        assert channel._pipe_handle == 90
        assert channel._closed is False
        assert close_calls == []
        assert any(retained is channel for retained in output_channel._RETAINED_UNRESOLVED_CHANNELS)
        assert observed_cancel_errors == ([] if cancel_error is None else [cancel_error])
        overlap.completed = True
        assert channel.close(deadline_monotonic=4.0, monotonic=lambda: clock[0]) is False
        assert close_calls == []
    finally:
        output_channel._release_retained_channel(channel)


def test_close_retains_channel_when_overlapped_query_error_is_not_a_known_completion():
    class UncertainCompletion:
        event = 103

        def GetOverlappedResult(self, _wait):
            raise _Win32Error(6)  # ERROR_INVALID_HANDLE is not completion evidence.

    close_calls = []

    class ApiFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    kernel32 = SimpleNamespace(
        CancelIoEx=ApiFunction(lambda *_args: 1),
        CloseHandle=ApiFunction(lambda handle: close_calls.append(int(handle.value)) or 1),
        WaitForSingleObject=ApiFunction(lambda *_args: output_channel._WAIT_OBJECT_0),
    )
    channel = _pending_close_channel(UncertainCompletion(), kernel32=kernel32)

    try:
        assert channel.close(deadline_monotonic=1.0, monotonic=lambda: 0.0) is False
        assert channel._connect_overlapped is not None
        assert channel._pipe_handle == 90
        assert close_calls == []
        assert any(retained is channel for retained in output_channel._RETAINED_UNRESOLVED_CHANNELS)
    finally:
        output_channel._release_retained_channel(channel)


def test_close_cannot_replace_the_deadline_bound_by_the_outer_run():
    class CompletedOverlapped:
        event = 104

        def GetOverlappedResult(self, _wait):
            raise _Win32Error(output_channel._ERROR_OPERATION_ABORTED)

    close_calls = []

    class ApiFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    kernel32 = SimpleNamespace(
        CancelIoEx=ApiFunction(lambda *_args: 1),
        CloseHandle=ApiFunction(lambda handle: close_calls.append(int(handle.value)) or 1),
        WaitForSingleObject=ApiFunction(lambda *_args: output_channel._WAIT_OBJECT_0),
    )
    channel = _pending_close_channel(CompletedOverlapped(), kernel32=kernel32)
    channel._deadline_monotonic = 1.0

    try:
        assert channel.close(deadline_monotonic=5.0, monotonic=lambda: 0.0) is False
        assert channel._connect_overlapped is not None
        assert channel._pipe_handle == 90
        assert close_calls == []
        assert any(retained is channel for retained in output_channel._RETAINED_UNRESOLVED_CHANNELS)
    finally:
        output_channel._release_retained_channel(channel)


def test_frame_is_not_published_when_native_handle_close_returns_after_deadline(
    monkeypatch,
):
    clock = [0.0]
    closed_handles = []

    class ApiFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    def close(handle):
        closed_handles.append(int(handle.value))
        clock[0] = 2.0
        return 1

    channel = _readable_channel(_outer_result())
    del channel.close
    channel._kernel32 = SimpleNamespace(
        CancelIoEx=ApiFunction(lambda *_args: 1),
        CloseHandle=ApiFunction(close),
        WaitForSingleObject=ApiFunction(lambda *_args: output_channel._WAIT_OBJECT_0),
    )
    channel._pipe_handle = 90
    channel._security_descriptor_handle = None
    channel._connect_overlapped = None
    channel._read_overlapped = None

    monkeypatch.setattr(output_channel, "_process_id", lambda _kernel32, _handle: 12)
    monkeypatch.setattr(
        output_channel,
        "_process_creation_time",
        lambda _kernel32, _handle: (0, 13),
    )

    try:
        with pytest.raises(output_channel.WorkerOutputChannelError) as caught:
            channel.read_frame_after_job_empty(
                request_id=REQUEST_ID,
                outer_result=channel._supervision_result,
                deadline_monotonic=1.0,
                monotonic=lambda: clock[0],
            )
        assert caught.value.reason == "worker_output_channel_close_unconfirmed"
        assert closed_handles == [11]
        assert channel._worker_handle == 10
        assert channel._pipe_handle == 90
        assert any(retained is channel for retained in output_channel._RETAINED_UNRESOLVED_CHANNELS)
    finally:
        output_channel._release_retained_channel(channel)


@pytest.mark.parametrize(
    ("request_id", "nonce"),
    [("c" * 32, NONCE), (REQUEST_ID, "d" * 32)],
)
def test_frame_rejects_stale_request_or_nonce(request_id, nonce):
    framed = output_channel._encode_frame(
        _worker_output(), request_id=REQUEST_ID, nonce=NONCE
    )

    with pytest.raises(output_channel.WorkerOutputChannelError):
        output_channel._decode_frame(framed, request_id=request_id, nonce=nonce)


def test_frame_rejects_trailing_bytes_duplicate_keys_and_cap_plus_one():
    framed = output_channel._encode_frame(
        _worker_output(), request_id=REQUEST_ID, nonce=NONCE
    )
    with pytest.raises(output_channel.WorkerOutputChannelError):
        output_channel._decode_frame(
            framed + b"extra", request_id=REQUEST_ID, nonce=NONCE
        )
    with pytest.raises(output_channel.WorkerOutputChannelError):
        output_channel._decode_frame(
            framed[:-1], request_id=REQUEST_ID, nonce=NONCE
        )

    duplicate = b'{"observation":{},"schema":"x","schema":"y"}'
    with pytest.raises(output_channel.WorkerOutputChannelError):
        output_channel._encode_frame(duplicate, request_id=REQUEST_ID, nonce=NONCE)

    cap_plus_one = struct.pack(">I", output_channel.MAX_FRAME_BYTES + 1) + b"x" * (
        output_channel.MAX_FRAME_BYTES + 1
    )
    with pytest.raises(output_channel.WorkerOutputChannelError):
        output_channel._decode_frame(
            cap_plus_one, request_id=REQUEST_ID, nonce=NONCE
        )


def test_short_kernel_buffer_uses_larger_pending_read_for_bounded_drain():
    assert output_channel._PIPE_BUFFER_BYTES == 4096
    assert output_channel._PIPE_BUFFER_BYTES < output_channel.MAX_FRAME_BYTES
    assert output_channel._READ_BUFFER_BYTES == (
        output_channel.MAX_FRAME_BYTES + output_channel.FRAME_LENGTH_BYTES + 1
    )


def test_raw_worker_output_has_separate_63_kibibyte_limit():
    target = output_channel.MAX_WORKER_OUTPUT_BYTES
    marker = b'"pad":""'
    base = _worker_output()
    marker_at = base.index(marker)
    prefix = base[: marker_at + len(b'"pad":"')]
    suffix = b'"' + base[marker_at + len(marker) :]
    exact = prefix + b"x" * (target - len(prefix) - len(suffix)) + suffix
    assert len(exact) == target
    output_channel._encode_frame(exact, request_id=REQUEST_ID, nonce=NONCE)

    too_large = (
        prefix
        + b"x" * (target + 1 - len(prefix) - len(suffix))
        + suffix
    )
    with pytest.raises(output_channel.WorkerOutputChannelError):
        output_channel._encode_frame(
            too_large, request_id=REQUEST_ID, nonce=NONCE
        )


def _current_user_sid() -> str:
    if os.name != "nt":
        pytest.skip("Windows token APIs required for named-pipe smoke")
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("User", SidAndAttributes)]

    process_token = wintypes.HANDLE()
    open_token = advapi32.OpenProcessToken
    open_token.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    open_token.restype = wintypes.BOOL
    get_process = kernel32.GetCurrentProcess
    get_process.argtypes = []
    get_process.restype = wintypes.HANDLE
    if not open_token(get_process(), 0x0008, ctypes.byref(process_token)):
        raise OSError(ctypes.get_last_error(), "OpenProcessToken failed")
    sid_text = wintypes.LPWSTR()
    try:
        needed = wintypes.DWORD()
        get_information = advapi32.GetTokenInformation
        get_information.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_information.restype = wintypes.BOOL
        buffer = ctypes.create_string_buffer(1024)
        if not get_information(
            process_token, 1, buffer, len(buffer), ctypes.byref(needed)
        ):
            raise OSError(ctypes.get_last_error(), "GetTokenInformation failed")
        user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        convert = advapi32.ConvertSidToStringSidW
        convert.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
        convert.restype = wintypes.BOOL
        if not convert(user.User.Sid, ctypes.byref(sid_text)):
            raise OSError(ctypes.get_last_error(), "ConvertSidToStringSidW failed")
        return str(sid_text.value)
    finally:
        if sid_text:
            kernel32.LocalFree(ctypes.cast(sid_text, wintypes.HLOCAL))
        kernel32.CloseHandle(process_token)


def _command(root: Path, code: str) -> watchdog.FixedOuterCommand:
    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
    assert system_root
    # A Windows venv's python.exe may be a launcher that starts a second
    # process.  The channel intentionally binds the exact process handle
    # created by the Job backend, so use the base interpreter for this smoke.
    base_executable = Path(sys.base_prefix) / "python.exe"
    executable = base_executable if base_executable.is_file() else Path(sys.executable)
    return watchdog.FixedOuterCommand(
        [str(executable), "-I", "-S", "-B", "-c", code],
        str(root),
        {
            "PATH": str(executable.parent),
            "SYSTEMROOT": system_root,
            "WINDIR": system_root,
        },
    )


@pytest.mark.skipif(os.name != "nt", reason="requires real local Windows named pipes")
def test_windows_job_child_roundtrips_one_nonce_frame_without_inherited_handles():
    root = Path(__file__).resolve().parents[3]
    client_sid = _current_user_sid()
    service_sid = "S-1-5-18"
    if service_sid == client_sid:
        service_sid = "S-1-5-19"
    channel = output_channel.create_worker_output_channel(
        service_sid=service_sid, client_sid=client_sid
    )
    binding = dict(channel.bootstrap_binding)
    request_id = "e" * 32
    base_worker_bytes = _worker_output()
    pad_count = output_channel.MAX_WORKER_OUTPUT_BYTES - len(base_worker_bytes)
    worker_bytes = _worker_output("x" * pad_count)
    assert len(worker_bytes) == output_channel.MAX_WORKER_OUTPUT_BYTES
    deadline = time.monotonic() + 15.0
    deadline_ns = int(deadline * 1_000_000_000)
    output_expression = (
        "json.dumps({'observation': {'pad': 'x' * %d}, 'schema': %r}, "
        "sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')"
        % (pad_count, output_channel.WORKER_SCHEMA)
    )
    code = (
        "import sys, json; sys.path.insert(0, {!r}); "
        "from scripts.ctp_i13_i15_worker_output_channel import write_worker_output_frame; "
        "write_worker_output_frame({}, request_id={!r}, nonce={!r}, "
        "expected_server_pid={!r}, deadline_monotonic_ns={!r})"
    ).format(
        str(root),
        output_expression,
        request_id,
        binding["nonce"],
        binding["server_pid"],
        deadline_ns,
    )
    backend = windows_job.WindowsJobBackend(
        no_inherited_handles=True,
        process_created_callback=channel.bind_suspended_worker,
    )
    try:
        result = output_channel.run_child_with_output_channel(
            channel,
            _command(root, code),
            backend=backend,
            request_id=request_id,
            deadline_monotonic=deadline,
            stop_deadline_monotonic=deadline - 2.0,
        )
        assert result.state == "exited", (result.state, result.reason, result.evidence)
        assert result.reason == "launcher_exited_job_empty"
        frame = channel.read_frame_after_job_empty(
            request_id=request_id,
            outer_result=result,
            deadline_monotonic=deadline,
        )
        assert output_channel._decode_frame_payload(
            frame, request_id=request_id, nonce=binding["nonce"]
        ) == worker_bytes
        assert channel._active_supervision_poll_count > 0
        assert channel._frame_completed_while_worker_alive is True
    finally:
        assert channel.close()


@pytest.mark.skipif(os.name != "nt", reason="requires real local Windows named pipes")
def test_windows_named_pipe_rejects_frame_from_wrong_job_peer_pid():
    root = Path(__file__).resolve().parents[3]
    client_sid = _current_user_sid()
    service_sid = "S-1-5-18"
    if service_sid == client_sid:
        service_sid = "S-1-5-19"
    channel = output_channel.create_worker_output_channel(
        service_sid=service_sid, client_sid=client_sid
    )
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    current_handle = open_process(
        0x00100000 | 0x00001000, False, os.getpid()
    )
    current_process_handle = output_channel._handle_value(current_handle)
    request_id = "f" * 32
    worker_bytes = _worker_output()
    deadline = time.monotonic() + 15.0
    deadline_ns = int(deadline * 1_000_000_000)
    binding = dict(channel.bootstrap_binding)
    code = (
        "import sys; sys.path.insert(0, {!r}); "
        "from scripts.ctp_i13_i15_worker_output_channel import write_worker_output_frame; "
        "write_worker_output_frame({!r}, request_id={!r}, nonce={!r}, "
        "expected_server_pid={!r}, deadline_monotonic_ns={!r})"
    ).format(
        str(root),
        worker_bytes,
        request_id,
        binding["nonce"],
        binding["server_pid"],
        deadline_ns,
    )

    def bind_wrong_process(_worker_pid, _worker_handle):
        return channel.bind_suspended_worker(os.getpid(), current_process_handle)

    backend = windows_job.WindowsJobBackend(
        no_inherited_handles=True,
        process_created_callback=bind_wrong_process,
    )
    try:
        result = output_channel.run_child_with_output_channel(
            channel,
            _command(root, code),
            backend=backend,
            request_id=request_id,
            deadline_monotonic=deadline,
            stop_deadline_monotonic=deadline - 2.0,
        )
        assert result.state != "exited"
        assert result.reason == "worker_output_peer_pid_mismatch", result.reason
        with pytest.raises(output_channel.WorkerOutputChannelError):
            channel.read_after_job_empty(
                request_id=request_id,
                outer_result=result,
                deadline_monotonic=deadline,
            )
    finally:
        assert channel.close()
        kernel32.CloseHandle(wintypes.HANDLE(current_process_handle))
