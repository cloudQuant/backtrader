"""Fake-only checks for the one-shot retained CU scope close helper."""

from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / ".codex-tmp" / "okx_m01_r3_normal_cu_close_helper_20261009.py"
HELPER_SHA256 = "9169878e73d5fd261a311f1e574b8a38ac3417fd456efcccbb5d47d01edd3295"
HELPER_SIZE = 16328


def _load_helper():
    info = HELPER.lstat()
    assert info.st_size == HELPER_SIZE
    assert info.st_size <= 128 * 1024
    with HELPER.open("rb") as stream:
        raw = stream.read(128 * 1024 + 1)
    assert len(raw) == info.st_size
    assert hashlib.sha256(raw).hexdigest() == HELPER_SHA256
    namespace = {"__name__": "_m01_cu_close_source_fake", "__file__": str(HELPER)}
    exec(compile(raw, str(HELPER), "exec", dont_inherit=True), namespace)
    return namespace


def test_normal_exit_is_one_shot_and_confirms_closed_generator():
    helper = _load_helper()
    events = []

    @contextlib.contextmanager
    def fake_scope():
        yield "synthetic"
        events.append("normal-exit")

    scope = fake_scope()
    assert scope.__enter__() == "synthetic"
    assert helper["_close_once"](scope) == ("closed", True)
    assert events == ["normal-exit"]
    assert helper["_close_once"](scope) == ("already_attempted", False)
    assert events == ["normal-exit"]


def test_close_exception_is_finite_and_cannot_be_retried():
    helper = _load_helper()
    events = []

    @contextlib.contextmanager
    def failing_scope():
        yield "synthetic"
        events.append("close-started")
        raise RuntimeError("must not be surfaced")

    scope = failing_scope()
    assert scope.__enter__() == "synthetic"
    assert helper["_close_once"](scope) == ("close_call_failed", True)
    assert helper["_close_once"](scope) == ("already_attempted", False)
    assert events == ["close-started"]


def test_bad_root_namespace_does_not_attempt_any_scope_close():
    helper = _load_helper()
    result = helper["close_original_scope"]({})
    assert result["status"] == "BLOCKED"
    assert result["phase"] == "root_binding"
    assert result["normal_close_called"] is False
    assert result["host_exit_permitted"] is False
    assert helper["_ATTEMPTED"] == []

