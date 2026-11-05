import json
import os

import pytest

from backtrader.live_state import (
    ERROR_CODES,
    FileLock,
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateLocked,
    atomic_write_json,
    atomic_write_text,
    read_json,
)
from backtrader.live_state import atomic as atomic_module

from ._helpers import temp_files


def test_atomic_write_replaces_content_and_leaves_no_temp_files(tmp_path):
    target = tmp_path / "state.json"
    for value in range(5):
        atomic_write_json(target, {"b": value, "a": "é"})
    assert read_json(target) == {"a": "é", "b": 4}
    text = target.read_text(encoding="utf-8")
    assert text.index('"a"') < text.index('"b"')  # sorted keys
    assert "é" in text  # ensure_ascii=False
    assert temp_files(tmp_path) == []


def test_atomic_write_fsyncs_file_before_replace(tmp_path, monkeypatch):
    events = []
    real_fsync = os.fsync
    real_replace = os.replace

    def fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    def replace(src, dst):
        events.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(atomic_module.os, "fsync", fsync)
    monkeypatch.setattr(atomic_module.os, "replace", replace)
    atomic_write_text(tmp_path / "f.txt", "x")
    assert events.index("fsync") < events.index("replace")


def test_failed_replace_keeps_old_content_and_removes_temp(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"v": 1})

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(atomic_module.os, "replace", broken_replace)
    with pytest.raises(OSError):
        atomic_write_json(target, {"v": 2})
    assert read_json(target) == {"v": 1}
    assert temp_files(tmp_path) == []


def test_atomic_write_rejects_nan(tmp_path):
    with pytest.raises(ValueError):
        atomic_write_json(tmp_path / "x.json", {"v": float("nan")})
    assert not (tmp_path / "x.json").exists()


@pytest.mark.parametrize(
    "content,reason",
    [
        (b"", "empty_file"),
        (b"{not json", "json_parse_error"),
        (b'{"a": 1, "a": 2}', "duplicate_key"),
        (b'{"a": NaN}', "json_parse_error"),
        (b"\xff\xfe", "utf8_decode_error"),
    ],
)
def test_read_json_reports_corruption(tmp_path, content, reason):
    target = tmp_path / "bad.json"
    target.write_bytes(content)
    with pytest.raises(LiveStateCorrupt) as info:
        read_json(target)
    assert info.value.code == "state_corrupt"
    assert info.value.reason == reason


def test_read_json_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_json(tmp_path / "missing.json")


def test_file_lock_excludes_second_holder_in_same_process(tmp_path):
    path = tmp_path / "x.lock"
    first = FileLock(path)
    second = FileLock(path, timeout=0.05)
    with first:
        assert first.held
        assert second.try_acquire() is False
        with pytest.raises(LiveStateLocked) as info:
            second.acquire()
        assert info.value.code == "state_locked"
    assert second.try_acquire() is True
    second.release()
    assert not second.held


def test_file_lock_is_not_reentrant(tmp_path):
    lock = FileLock(tmp_path / "x.lock")
    assert lock.try_acquire()
    try:
        with pytest.raises(LiveStateError) as info:
            lock.try_acquire()
        assert info.value.code == "lock_reentry"
    finally:
        lock.release()


def test_error_codes_are_finite():
    assert LiveStateError("not_a_registered_code").code == "live_state_error"
    assert LiveStateIdentityMismatch("account_binding_mismatch").code == "account_binding_mismatch"
    assert LiveStateIdentityMismatch("free text").code == "identity_mismatch"
    for code in ("state_corrupt", "state_locked", "state_not_initialized", "marker_not_unknown"):
        assert code in ERROR_CODES


def test_errors_survive_pickling():
    import pickle

    for error in (
        LiveStateError("marker_not_found", "x"),
        LiveStateCorrupt("/a/b.json", "duplicate_key"),
        LiveStateLocked("/a/run.lock"),
        LiveStateIdentityMismatch("hostname_mismatch"),
    ):
        clone = pickle.loads(pickle.dumps(error))
        assert type(clone) is type(error)
        assert clone.code == error.code
        assert str(clone) == str(error)


def test_dumps_is_strict_json(tmp_path):
    target = tmp_path / "x.json"
    atomic_write_json(target, {"k": [1, 2]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": [1, 2]}
