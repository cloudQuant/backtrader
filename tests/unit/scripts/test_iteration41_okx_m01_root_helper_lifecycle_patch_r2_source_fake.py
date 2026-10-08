"""Source-fake tests for the additive M01 root-helper lifecycle successor."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
VENUE = ROOT / "examples/000_live_certification/okx_penetration"
PATCH_PATH = ROOT / "scripts/iteration41_okx_m01_root_helper_lifecycle_patch_r2.py"
GATE_TEST_PATH = (
    ROOT / "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r2.py"
)

_PATCH_SPEC = importlib.util.spec_from_file_location("_m01_root_helper_patch_r2_test", PATCH_PATH)
assert _PATCH_SPEC is not None and _PATCH_SPEC.loader is not None
patch_r2 = importlib.util.module_from_spec(_PATCH_SPEC)
_PATCH_SPEC.loader.exec_module(patch_r2)

_GATE_TEST_SPEC = importlib.util.spec_from_file_location(
    "_m01_root_helper_gate_r2_fakes", GATE_TEST_PATH
)
assert _GATE_TEST_SPEC is not None and _GATE_TEST_SPEC.loader is not None
gate_test = importlib.util.module_from_spec(_GATE_TEST_SPEC)
_GATE_TEST_SPEC.loader.exec_module(gate_test)


@pytest.fixture
def pinned_modules(monkeypatch):
    if os.name != "nt":
        pytest.skip("the pinned M01 reader and V2 supervisor are Windows-only")
    monkeypatch.syspath_prepend(str(VENUE))
    reader = importlib.import_module("_m01_readonly_monitor_v3.current_reader")
    return reader, reader.job_supervisor, reader.worker


class _VirtualClock:
    def __init__(self):
        self.offset = 0.0
        self.base = time.monotonic()

    def monotonic(self):
        return self.base + self.offset

    def sleep(self, seconds):
        self.offset += max(0.0, float(seconds))


def _install_fake(monkeypatch, supervisor, kernel):
    monkeypatch.setattr(supervisor.ctypes, "WinDLL", lambda *_a, **_k: kernel, raising=False)
    monkeypatch.setattr(supervisor.ctypes, "get_last_error", kernel.get_last_error, raising=False)
    monkeypatch.setattr(
        supervisor, "_hold_runtime_files", lambda _kernel, _deadline: {"runtime_handles": set()}
    )


def _load_successor(reader):
    function, retained = patch_r2.load_successor_functions(reader)
    function.__globals__["time"] = _VirtualClock()
    return function, retained


def test_transformer_requires_exact_frozen_reader_source(pinned_modules):
    reader, _supervisor, _worker = pinned_modules
    raw = Path(reader.__file__).read_bytes()

    transformed = patch_r2.transform_current_reader_source(raw)

    assert hashlib.sha256(raw).hexdigest() == patch_r2.CURRENT_READER_SHA256
    assert hashlib.sha256(transformed).hexdigest() == patch_r2.SUCCESSOR_SOURCE_SHA256
    assert b"_ROOT_HELPER_RETAINED_CONTEXTS" in transformed
    assert b"_wait_for_job_zero" in transformed
    assert b"process_reaped" in transformed
    assert b"root_helper_process_handle_close" in transformed
    assert b"root_helper_descendant_active" in transformed
    with pytest.raises(patch_r2.PatchError) as raised:
        patch_r2.transform_current_reader_source(raw + b"# changed\n")
    assert raised.value.code == "current_reader_source_pin_mismatch"


def test_successor_releases_root_process_reference_before_job_count(pinned_modules, monkeypatch):
    reader, supervisor, _worker = pinned_modules
    original_reader_helper = reader._run_pinned_root_helper
    kernel = gate_test._FakeKernel(supervisor, root_process_reference=True)
    _install_fake(monkeypatch, supervisor, kernel)
    run_helper, retained = _load_successor(reader)
    wrapper = reader._root_helper_wrapper(gate_test.gate.SYNTHETIC_HELPER)

    result = run_helper(
        wrapper,
        {"SYSTEMROOT": "C:\\Windows", "WINDIR": "C:\\Windows"},
        timeout_seconds=60.0,
    )

    assert result[0] == gate_test.gate.SYNTHETIC_OUTPUT
    assert result[1] == b""
    assert result[2] == 0
    assert kernel.process_handle_closed is True
    assert kernel.terminated is False
    assert (True, True, 0) in kernel.job_count_samples
    assert kernel.job_close_preceding_sample == (True, True, 0)
    assert kernel.job_handle in kernel.closed_handles
    assert retained == []
    assert reader._run_pinned_root_helper is original_reader_helper


def test_successor_terminates_true_descendant_and_preserves_primary_check(
    pinned_modules, monkeypatch
):
    reader, supervisor, _worker = pinned_modules
    kernel = gate_test._FakeKernel(
        supervisor,
        descendant_after_root_close=True,
        clear_descendant_on_terminate=True,
    )
    _install_fake(monkeypatch, supervisor, kernel)
    run_helper, retained = _load_successor(reader)
    wrapper = reader._root_helper_wrapper(gate_test.gate.SYNTHETIC_HELPER)

    with pytest.raises(reader.CurrentReaderError) as raised:
        run_helper(
            wrapper,
            {"SYSTEMROOT": "C:\\Windows", "WINDIR": "C:\\Windows"},
            timeout_seconds=60.0,
        )

    assert raised.value.code == "root_helper_descendant_active"
    assert kernel.process_handle_closed is True
    assert kernel.terminated is True
    assert (True, True, 1) in kernel.job_count_samples
    assert kernel.job_close_preceding_sample == (True, True, 0)
    assert kernel.job_handle in kernel.closed_handles
    assert retained == []


def test_successor_retains_job_and_source_context_if_descendant_survives_termination(
    pinned_modules, monkeypatch
):
    reader, supervisor, _worker = pinned_modules
    kernel = gate_test._FakeKernel(
        supervisor,
        descendant_after_root_close=True,
        clear_descendant_on_terminate=False,
    )
    _install_fake(monkeypatch, supervisor, kernel)
    run_helper, retained = _load_successor(reader)
    wrapper = reader._root_helper_wrapper(gate_test.gate.SYNTHETIC_HELPER)

    with pytest.raises(reader.CurrentReaderError) as raised:
        run_helper(
            wrapper,
            {"SYSTEMROOT": "C:\\Windows", "WINDIR": "C:\\Windows"},
            timeout_seconds=60.0,
        )

    assert raised.value.code == "root_helper_descendant_active"
    assert kernel.process_handle_closed is True
    assert kernel.terminated is True
    assert kernel.job_count_samples[-1] == (True, True, 1)
    assert kernel.job_handle not in kernel.closed_handles
    assert len(retained) == 1
    assert retained[0][0] is kernel
    assert retained[0][1]["job"] == kernel.job_handle


def test_successor_retains_job_after_close_failure_without_masking_reader_error(
    pinned_modules, monkeypatch
):
    reader, supervisor, _worker = pinned_modules
    kernel = gate_test._FakeKernel(
        supervisor,
        fail_job_close=True,
        descendant_after_root_close=True,
        clear_descendant_on_terminate=True,
    )
    _install_fake(monkeypatch, supervisor, kernel)
    run_helper, retained = _load_successor(reader)
    wrapper = reader._root_helper_wrapper(gate_test.gate.SYNTHETIC_HELPER)

    with pytest.raises(reader.CurrentReaderError) as raised:
        run_helper(
            wrapper,
            {"SYSTEMROOT": "C:\\Windows", "WINDIR": "C:\\Windows"},
            timeout_seconds=60.0,
        )

    assert raised.value.code == "root_helper_descendant_active"
    assert kernel.terminated is True
    assert kernel.job_handle not in kernel.closed_handles
    assert kernel.job_close_preceding_sample == (True, True, 0)
    assert len(retained) == 1
    assert retained[0][0] is kernel
