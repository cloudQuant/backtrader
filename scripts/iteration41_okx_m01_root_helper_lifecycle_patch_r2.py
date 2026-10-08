"""Exact, in-memory successor patch for the fixed M01 root-helper lifecycle.

This module does not import the venue reader automatically or patch a live
module. Its transformer accepts only the frozen public reader bytes and returns
a new source blob for Root's review. Callers must hold and verify source bytes.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
from pathlib import Path
import textwrap
import time
from typing import Any, Mapping


CURRENT_READER_SHA256 = "b350e0d0110a3c87f6fc44a841b9df12e229eff2efac1060d66b598c17cbc734"
PATCH_SCHEMA = "iteration41.okx.m01.root-helper-lifecycle-source-patch.v2"
SUCCESSOR_SOURCE_SHA256 = "5a8fd479c999279d9efde625cac1938d794201f04e1beaa6f3663b267d7a7ebc"


class PatchError(ValueError):
    def __init__(self, code: str):
        self.code = code if type(code) is str and code.isascii() else "patch_rejected"
        super().__init__(self.code)


def _wait_for_job_zero_r2(kernel: Any, job: int, *, timeout_seconds: float) -> bool:
    """Poll a held Job until its active process count is zero or time expires."""
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        try:
            active = job_supervisor._active_count(kernel, job)
        except Exception:
            raise CurrentReaderError("root_helper_job_count_unavailable") from None
        if type(active) is not int:
            raise CurrentReaderError("root_helper_job_count_invalid")
        if active == 0:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.025, remaining))


def _run_pinned_root_helper_r2(
    wrapper: bytes, environment: Mapping[str, str], *, timeout_seconds: float
) -> tuple[bytes, bytes, int | None, int, dict[str, Any]]:
    """Run exact helper bytes and retain uncertain process/Job ownership."""
    _require(type(timeout_seconds) in (int, float) and 1 <= timeout_seconds <= 360, "root_timeout")
    _require(
        type(wrapper) is bytes and 0 < len(wrapper) <= worker.MAX_LAUNCH_FRAME_BYTES,
        "root_wrapper_size",
    )
    setup_deadline = time.monotonic() + 20.0
    deadline = time.monotonic() + float(timeout_seconds)
    kernel = job_supervisor._winapi()
    control = None
    states = [job_supervisor._new_pipe_state(), job_supervisor._new_pipe_state()]
    threads = []
    result = None
    primary_error = None
    cleanup_complete = False

    try:
        control = job_supervisor._create_suspended(
            kernel,
            environment,
            worker_source_sha256=_sha(wrapper),
            worker_source_size=len(wrapper),
            deadline=setup_deadline,
        )
        for name, state, limit in (
            ("stdout", states[0], MAX_HELPER_OUTPUT_BYTES),
            ("stderr", states[1], MAX_HELPER_OUTPUT_BYTES),
        ):
            thread = threading.Thread(
                target=job_supervisor._drain,
                args=(kernel, control[name], state, limit),
                daemon=True,
                name=f"okx-m01-c01-{name}-drain",
            )
            thread.start()
            threads.append(thread)
        job_supervisor._assign_control_to_job(kernel, control, setup_deadline)
        job_supervisor._resume_control(kernel, control, setup_deadline)
        if not job_supervisor._close_handle(kernel, control["handles"], control["thread"]):
            raise CurrentReaderError("root_helper_thread_handle_close")
        control["thread"] = 0
        frame = len(wrapper).to_bytes(4, "big") + wrapper
        if not job_supervisor._write_all(kernel, control["stdin"], frame, setup_deadline):
            raise CurrentReaderError("root_helper_source_write")
        if not job_supervisor._close_handle(kernel, control["handles"], control["stdin"]):
            raise CurrentReaderError("root_helper_stdin_close")
        control["stdin"] = 0

        remaining = max(0, int((deadline - time.monotonic()) * 1000))
        exited = job_supervisor._wait_process(kernel, control["process"], remaining)
        if not exited:
            raise CurrentReaderError("root_helper_timeout")
        control["process_reaped"] = True
        exit_code = job_supervisor._process_exit_code(kernel, control["process"])
        if exit_code is None:
            raise CurrentReaderError("root_helper_exit_code_unavailable")

        # Windows Job accounting can retain the root process while its parent
        # process handle remains open. Release that reference before querying.
        if not job_supervisor._close_handle(kernel, control["handles"], control["process"]):
            raise CurrentReaderError("root_helper_process_handle_close")
        control["process"] = 0

        job_zero = _wait_for_job_zero_r2(kernel, control["job"], timeout_seconds=2.0)
        control["job_zero_confirmed"] = job_zero
        if not job_zero:
            raise CurrentReaderError("root_helper_descendant_active")

        for thread in threads:
            thread.join(timeout=5.0)
        _require(all(not thread.is_alive() for thread in threads), "root_helper_pipe_join")
        for state in states:
            _require(
                state["eof"] and state["done"] and not state["error"] and not state["overflow"],
                "root_helper_pipe_incomplete",
            )
        stdout, stderr = bytes(states[0]["raw"]), bytes(states[1]["raw"])
        control["root_helper_normal_exit"] = True
        result = (
            stdout,
            stderr,
            exit_code,
            int(control["pid"]),
            {
                "pid": int(control["pid"]),
                "assigned_before_resume": bool(control.get("assigned")),
                "active_count_after_exit": 0,
                "normal_exit": exit_code == 0 and exited,
            },
        )
    except BaseException as exc:
        primary_error = exc
        if control is not None:
            try:
                control["termination_succeeded"] = bool(
                    job_supervisor._terminate_control(kernel, control, 0xEE5A)
                )
            except Exception:
                control["termination_succeeded"] = False

            process = control.get("process")
            process_reaped = bool(control.get("process_reaped"))
            if process and not process_reaped:
                try:
                    process_reaped = job_supervisor._wait_process(kernel, process, 5000)
                except Exception:
                    process_reaped = False
                control["process_reaped"] = process_reaped
            if process and process_reaped:
                try:
                    if job_supervisor._close_handle(kernel, control["handles"], process):
                        control["process"] = 0
                except Exception:
                    pass

            if control.get("process_reaped") and not control.get("process"):
                try:
                    control["job_zero_confirmed"] = _wait_for_job_zero_r2(
                        kernel, control["job"], timeout_seconds=5.0
                    )
                except Exception:
                    control["job_zero_confirmed"] = False
            for thread in threads:
                try:
                    thread.join(timeout=5.0)
                except Exception:
                    pass
    finally:
        if control is None:
            cleanup_complete = True
        else:
            process = control.get("process")
            process_reaped = bool(control.get("process_reaped"))
            if process and not process_reaped:
                try:
                    process_reaped = job_supervisor._wait_process(kernel, process, 0)
                except Exception:
                    process_reaped = False
                control["process_reaped"] = process_reaped
            if process and process_reaped:
                try:
                    if job_supervisor._close_handle(kernel, control["handles"], process):
                        control["process"] = 0
                except Exception:
                    pass

            threads_joined = all(not thread.is_alive() for thread in threads)
            pipes_complete = all(
                state["eof"] and state["done"] and not state["error"] and not state["overflow"]
                for state in states
            )
            retain_context = (
                not control.get("process_reaped")
                or bool(control.get("process"))
                or not control.get("job_zero_confirmed")
                or not threads_joined
                or not pipes_complete
            )
            if not retain_context:
                handles = control.get("handles")
                if type(handles) is not set:
                    retain_context = True
                else:
                    job_value = control.get("job")
                    try:
                        ordered_handles = sorted(
                            tuple(handles),
                            key=lambda handle: (handle == job_value, int(handle)),
                        )
                    except Exception:
                        ordered_handles = []
                        retain_context = True
                    for handle in ordered_handles:
                        try:
                            closed = job_supervisor._close_handle(kernel, handles, handle)
                        except Exception:
                            closed = False
                        if not closed:
                            retain_context = True
                            break
            if retain_context:
                _ROOT_HELPER_RETAINED_CONTEXTS.append(
                    (kernel, control, tuple(threads), tuple(states))
                )
            else:
                cleanup_complete = not control.get("handles")

    if primary_error is not None:
        if isinstance(primary_error, CurrentReaderError):
            raise primary_error
        raise CurrentReaderError("root_helper_lifecycle_failed") from None
    if not cleanup_complete:
        raise CurrentReaderError("root_helper_cleanup_unconfirmed")
    if result is None:
        raise CurrentReaderError("root_helper_lifecycle_failed")
    return result


def _replacement_source() -> str:
    helper = textwrap.dedent(inspect.getsource(_wait_for_job_zero_r2))
    function = textwrap.dedent(inspect.getsource(_run_pinned_root_helper_r2))
    helper = helper.replace("_wait_for_job_zero_r2", "_wait_for_job_zero")
    function = function.replace("_run_pinned_root_helper_r2", "_run_pinned_root_helper")
    function = function.replace("_wait_for_job_zero_r2", "_wait_for_job_zero")
    prefix = "_ROOT_HELPER_RETAINED_CONTEXTS: list[tuple[Any, ...]] = []\n\n"
    return prefix + helper + "\n\n" + function + "\n\n"


def transform_current_reader_source(source: bytes) -> bytes:
    """Return the exact successor source after validating the frozen input pin."""
    if type(source) is not bytes or len(source) > 256 * 1024:
        raise PatchError("source_bytes_invalid")
    if hashlib.sha256(source).hexdigest() != CURRENT_READER_SHA256:
        raise PatchError("current_reader_source_pin_mismatch")
    try:
        text = source.decode("utf-8")
        tree = ast.parse(text)
    except Exception:
        raise PatchError("current_reader_source_invalid") from None
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_pinned_root_helper"
    ]
    if len(matches) != 1:
        raise PatchError("current_reader_function_shape_mismatch")
    lines = text.splitlines(keepends=True)
    target = matches[0]
    start = sum(len(line) for line in lines[: target.lineno - 1])
    end = sum(len(line) for line in lines[: target.end_lineno])
    replacement = _replacement_source()
    transformed = text[:start] + replacement + text[end:]
    try:
        ast.parse(transformed)
    except Exception:
        raise PatchError("successor_source_invalid") from None
    output = transformed.encode("utf-8")
    if hashlib.sha256(output).hexdigest() != SUCCESSOR_SOURCE_SHA256:
        raise PatchError("successor_source_pin_mismatch")
    return output


def load_successor_functions(reader_module: Any) -> tuple[Any, Any]:
    """Compile only the patched helper functions into a copy of held globals.

    This is test support for executing the exact transformed function with fake
    OS leaves. It reads only the pinned public source path and leaves the passed
    reader module unchanged.
    """
    if getattr(reader_module, "__name__", None) != "_m01_readonly_monitor_v3.current_reader":
        raise PatchError("reader_module_name_mismatch")
    source_path = Path(reader_module.__file__).resolve(strict=True)
    raw = source_path.read_bytes()
    transformed = transform_current_reader_source(raw)
    namespace = dict(reader_module.__dict__)
    namespace["_ROOT_HELPER_RETAINED_CONTEXTS"] = []
    try:
        tree = ast.parse(transformed.decode("utf-8"))
        selected = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_wait_for_job_zero", "_run_pinned_root_helper"}
        ]
        code = compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec")
        exec(code, namespace, namespace)
    except Exception:
        raise PatchError("successor_function_load_failed") from None
    return namespace["_run_pinned_root_helper"], namespace["_ROOT_HELPER_RETAINED_CONTEXTS"]
