"""Offline tests for the isolated, non-authorizing I11 attempt latch."""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtrader_runtime import ctp_i11_attempt_latch as latch_module


def test_i11_latch_has_a_distinct_fixed_read_only_identity() -> None:
    path_parameter = inspect.signature(latch_module.PersistentI11OneShotAttemptLatch).parameters[
        "path"
    ]

    assert path_parameter.default is inspect.Parameter.empty
    assert latch_module.I11_SDK_SOURCE_COMMIT == "a6253a58b1ebca11f58c8836fbed757d0daf7582"
    assert (
        latch_module.I11_REUSED_I10_WHEEL_SHA256
        == "e81bd7fcba8f0aaf823af9efcca565622a55842ed3bce970994f483f4f3188c4"
    )
    assert latch_module.I11_LATCH_CONTENT == b"i11-readonly-md-attempted-v1\n"
    assert latch_module.I11_LATCH_PATH.name == "i11-readonly-md-supervisor-no-retry.latch"
    assert latch_module.I11_READ_ONLY is True
    assert latch_module.I11_ORDER_SUBMISSION_AUTHORIZED is False
    assert latch_module.I11_TRADING_CAPABILITIES == ()
    assert not hasattr(latch_module, "main")
    assert not hasattr(latch_module, "supervise_i11_child")
    assert not hasattr(latch_module, "_run_child_entry")


def test_i11_latch_is_one_shot_and_does_not_read_or_change_other_markers(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    _protect_test_directory(state)
    marker_paths = {
        "i8": state / "i8-readonly-md-supervisor-no-retry.latch",
        "i9": state / "i9-readonly-md-supervisor-no-retry.latch",
        "i10": state / "i10-readonly-md-supervisor-no-retry.latch",
    }
    marker_contents = {
        name: f"synthetic-{name}-marker-must-remain-untouched\n".encode("ascii")
        for name in marker_paths
    }
    for name, path in marker_paths.items():
        path.write_bytes(marker_contents[name])
    i11_path = state / latch_module.I11_LATCH_PATH.name

    first = latch_module.PersistentI11OneShotAttemptLatch(i11_path)
    assert first.begin_attempt() is True
    assert first.is_tripped() is False
    assert i11_path.read_bytes() == latch_module.I11_LATCH_CONTENT
    for name, path in marker_paths.items():
        assert path.read_bytes() == marker_contents[name]

    restarted = latch_module.PersistentI11OneShotAttemptLatch(i11_path)
    assert restarted.is_tripped() is True
    assert restarted.begin_attempt() is False
    for name, path in marker_paths.items():
        assert path.read_bytes() == marker_contents[name]


def test_constructing_i11_latch_does_not_touch_its_explicit_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_io(*_args: object, **_kwargs: object) -> object:
        pytest.fail("latch construction performed filesystem I/O")

    monkeypatch.setattr(os, "lstat", _unexpected_io)
    monkeypatch.setattr(os, "open", _unexpected_io)

    latch = latch_module.PersistentI11OneShotAttemptLatch(latch_module.I11_LATCH_PATH)

    assert latch._path == latch_module.I11_LATCH_PATH


def test_fresh_process_imports_i11_without_credential_or_filesystem_access() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    code = f"""
import builtins
import os
import sys
from pathlib import Path

sys.path.insert(0, {str(repo_root)!r})
import backtrader_runtime

blocked = []
def deny_file_io(name):
    def fail(*args, **kwargs):
        blocked.append(name)
        raise AssertionError("unexpected filesystem API: " + name)
    return fail

os.open = deny_file_io("os.open")
os.lstat = deny_file_io("os.lstat")
builtins.open = deny_file_io("builtins.open")
Path.open = deny_file_io("Path.open")

import backtrader_runtime.ctp_i11_attempt_latch as latch_module
import backtrader_runtime.ctp_i11_oneshot_md_diagnostic

latch = latch_module.PersistentI11OneShotAttemptLatch(
    Path(r"D:\\synthetic-i11-state\\attempt.latch")
)
assert latch._path.name == "attempt.latch"
assert blocked == []
assert "backtrader_runtime.ctp_i8_oneshot_md_diagnostic" not in sys.modules
assert "backtrader_runtime.credential_resolver" not in sys.modules
assert not any(
    name == "bt_api_base"
    or name.startswith("bt_api_base.")
    or name == "bt_api_ctp"
    or name.startswith("bt_api_ctp.")
    for name in sys.modules
)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, f"fresh I11 import probe failed: {result.stderr[-800:]}"


def test_i11_latch_rejects_invalid_ancestor_path(tmp_path: Path) -> None:
    not_a_directory = tmp_path / "not-a-directory"
    not_a_directory.write_text("synthetic", encoding="utf-8")
    latch = latch_module.PersistentI11OneShotAttemptLatch(not_a_directory / "attempt.latch")

    with pytest.raises(OSError, match="latch_ancestor_invalid"):
        latch.begin_attempt()


def test_alias_of_canonical_i11_marker_still_checks_registered_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backtrader_runtime import ctp_i8_oneshot_md_diagnostic as i8

    canonical = tmp_path / "state" / "attempt.latch"
    alias = tmp_path / "state" / ".." / "state" / "attempt.latch"
    monkeypatch.setattr(latch_module, "I11_LATCH_PATH", canonical)
    checked = []

    class FakeRegistry:
        def require_runtime_dir(self, runtime_dir: Path) -> object:
            checked.append(("registration", runtime_dir))
            return SimpleNamespace(runtime_id=latch_module.ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID)

        def verified_runtime_directory(self, registration: object) -> object:
            checked.append(("directory", registration))
            return nullcontext()

    monkeypatch.setattr(latch_module, "iteration41_runtime_registry", FakeRegistry)
    monkeypatch.setattr(
        i8._PersistentI8NoRetryLatch,
        "_verify_ancestor_chain",
        lambda self: checked.append(("ancestor_scan", self._path)),
    )

    latch_module.PersistentI11OneShotAttemptLatch(alias)._verify_ancestor_chain()

    assert [kind for kind, _ in checked] == [
        "registration",
        "directory",
        "ancestor_scan",
    ]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits are not portable on Windows")
def test_i11_latch_rejects_a_directory_with_broad_permissions(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    state.chmod(0o755)
    latch = latch_module.PersistentI11OneShotAttemptLatch(state / "attempt.latch")

    with pytest.raises(OSError, match="latch_directory_not_private"):
        latch.begin_attempt()


@pytest.mark.skipif(os.name != "nt", reason="Windows metadata ACL path is Windows-only")
def test_i11_latch_fails_closed_when_windows_directory_access_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backtrader_runtime import credential_resolver

    state = tmp_path / "state"
    _protect_test_directory(state)
    marker = state / "attempt.latch"

    def _deny_directory_access(_path: Path, *, is_directory: bool) -> int:
        assert is_directory is True
        raise OSError("latch_directory_not_private")

    monkeypatch.setattr(
        credential_resolver, "_open_windows_metadata_handle", _deny_directory_access
    )
    latch = latch_module.PersistentI11OneShotAttemptLatch(marker)

    with pytest.raises(OSError, match="latch_directory_not_private"):
        latch.begin_attempt()

    assert not marker.exists()


def _protect_test_directory(path: Path) -> None:
    path.mkdir()
    if os.name == "nt":
        from backtrader_runtime.ctp_private_config_setup import (
            _protect_target_directory,
            _verified_target_directory,
        )

        with _verified_target_directory(path) as descriptor:
            _protect_target_directory(descriptor)
    else:
        path.chmod(0o700)
