"""Faithful fake-OS coverage for the Root-only M01 V3 metadata rebinder."""

from __future__ import annotations

import ctypes as C
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from ctypes import wintypes as W

import pytest


ROOT = Path(__file__).resolve().parents[3]
VENUE = ROOT / "examples" / "000_live_certification" / "okx_penetration"
for _path in (str(VENUE),):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from _m01_readonly_monitor_v3 import current_reader  # noqa: E402
from backtrader_runtime import certification_roundtrip_private  # noqa: E402


_HELPER_PATH = ROOT / "scripts" / "iteration41_okx_m01_v3_protected_rebind_r1.py"
_REVIEW_DIR = (
    ROOT
    / "docs"
    / "_internal"
    / "opts"
    / "requirements"
    / "迭代41-实盘执行风控监控与示例架构重构"
    / "evidence"
    / "iteration41-okx-m01-reason-preservation-independent-review-r2-2026-10-09"
)
_SPEC = importlib.util.spec_from_file_location("m01_v3_rebind_r1", _HELPER_PATH)
rebind = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(rebind)
_PRODUCTION_OLD_MAP_SHA256 = rebind.OLD_SOURCE_MAP_SHA256


def _canonical(value):
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def _source_map():
    pins = {}
    for relative in current_reader.SOURCE_MAP_RELATIVES:
        raw = (ROOT / Path(relative)).read_bytes()
        pins[relative] = hashlib.sha256(raw).hexdigest()
    return _canonical({"schema": current_reader.SOURCE_MAP_SCHEMA, "source_pins": pins})


def _old_documents():
    pins = dict.fromkeys(current_reader.SOURCE_MAP_RELATIVES, "a" * 64)
    source_map_raw = _canonical({"schema": current_reader.SOURCE_MAP_SCHEMA, "source_pins": pins})
    admission_raw = _canonical(
        {
            "schema": current_reader.ADMISSION_SCHEMA,
            "status": "ADMITTED_SOURCE_PIN",
            "profile": current_reader.PROFILE,
            "source_map_sha256": hashlib.sha256(source_map_raw).hexdigest(),
            "review_ref": rebind.OLD_REVIEW_REF,
        }
    )
    return admission_raw, source_map_raw


def _reviewed_test_raw():
    return (ROOT / "tests/unit/live_certification/test_okx_m01_readonly_monitor_v3.py").read_bytes()


@pytest.fixture(autouse=True)
def _synthetic_old_map_pin(monkeypatch):
    """Permit only the synthetic in-memory old map used by these fake-OS tests."""
    _admission, old_map = _old_documents()
    monkeypatch.setattr(rebind, "OLD_SOURCE_MAP_SHA256", hashlib.sha256(old_map).hexdigest())


class _FakeHandle:
    def __init__(self, path, entry, access, share):
        self.path = path
        self.entry = entry
        self.access = access
        self.share = share
        self.cursor = 0
        self.closed = False


class _FakeWin32API:
    """Faithful callable Win32 leaves backing the production adapter with bytes in memory."""

    def __init__(self, old_admission, old_map, *, fail=None):
        self.entries = {}
        self.next_id = 1
        self.handles = {}
        self.next_handle = 100
        self.events = []
        self.fail = fail
        self.fail_used = False
        self.sid = "S-1-5-21-fake-owner"
        for directory in reversed(rebind._DEPLOYMENT.parents):
            if directory not in self.entries:
                self._directory(directory, owner_only=directory == rebind._DEPLOYMENT)
        self._directory(rebind._DEPLOYMENT, owner_only=True)
        self._file(rebind._DEPLOYMENT_PATHS["deployment.json"], old_admission)
        self._file(rebind._DEPLOYMENT_PATHS["source-map.json"], old_map)
        self.kernel = SimpleNamespace()
        self.kernel.ReadFile = lambda *args: self.ReadFile(*args)
        self.kernel.SetFilePointerEx = lambda *args: self.SetFilePointerEx(*args)
        self.kernel.SetEndOfFile = lambda *args: self.SetEndOfFile(*args)

    def _entry(self, *, directory, data=b"", owner_only):
        result = {
            "directory": directory,
            "data": data,
            "owner_only": owner_only,
            "identity": self.next_id,
            "reparse": False,
            "links": 1,
        }
        self.next_id += 1
        return result

    def _directory(self, path, *, owner_only):
        self.entries[path] = self._entry(directory=True, owner_only=owner_only)

    def _file(self, path, data, *, owner_only=True):
        self.entries[path] = self._entry(directory=False, data=data, owner_only=owner_only)

    def _fault(self, phase, path):
        if self.fail == (phase, path) and not self.fail_used:
            self.fail_used = True
            return True
        return False

    @staticmethod
    def _set_out(pointer, value, ctype):
        C.cast(pointer, C.POINTER(ctype)).contents.value = value

    def _handle(self, handle):
        value = self.handles.get(handle)
        if value is None or value.closed:
            raise rebind.RebindError("protected_io_failed")
        return value

    def current_sid(self):
        self.events.append(("sid",))
        return self.sid

    def descriptor(self, sid, *, directory):
        assert sid == self.sid
        value = C.c_byte(1 if directory else 2)
        self.events.append(("descriptor", directory, sid))
        return _DescriptorContext(value)

    def CreateFileW(self, raw_path, access, share, security, creation, flags, template):
        path = Path(raw_path)
        directory = bool(flags & rebind._FILE_FLAG_BACKUP_SEMANTICS)
        self.events.append(("CreateFileW", path, access, share, creation, flags))
        if self._fault("open", path):
            return rebind._INVALID_HANDLE
        if flags & rebind._FILE_FLAG_OPEN_REPARSE_POINT == 0 or template is not None:
            return rebind._INVALID_HANDLE
        if creation == rebind._CREATE_NEW:
            expected_access = (
                rebind._GENERIC_READ
                | rebind._GENERIC_WRITE
                | rebind._READ_CONTROL
                | rebind._READ_ATTRIBUTES
            )
            if (
                path in self.entries
                or directory
                or access != expected_access
                or share != 0
                or security is None
                or flags != rebind._FILE_FLAGS
            ):
                return rebind._INVALID_HANDLE
            self._file(path, b"", owner_only=True)
            self.events.append(("create_new", path, access, share, "owner-only"))
        elif creation == rebind._OPEN_EXISTING:
            entry = self.entries.get(path)
            if entry is None or entry["directory"] is not directory:
                return rebind._INVALID_HANDLE
            if directory:
                expected_access = rebind._READ_CONTROL | rebind._READ_ATTRIBUTES
                expected_share = 3
                expected_flags = rebind._DIR_FLAGS
            else:
                expected_access = (
                    rebind._GENERIC_READ
                    | rebind._GENERIC_WRITE
                    | rebind._READ_CONTROL
                    | rebind._READ_ATTRIBUTES
                )
                expected_share = rebind._FILE_SHARE_READ
                expected_flags = rebind._FILE_FLAGS
            if access != expected_access or share != expected_share or flags != expected_flags:
                return rebind._INVALID_HANDLE
        else:
            return rebind._INVALID_HANDLE
        handle = self.next_handle
        self.next_handle += 1
        self.handles[handle] = _FakeHandle(path, self.entries[path], access, share)
        self.events.append(("open", path, directory, access, share))
        return handle

    def CreateDirectoryW(self, raw_path, security):
        path = Path(raw_path)
        self.events.append(("CreateDirectoryW", path))
        if self._fault("mkdir", path) or security is None or path in self.entries:
            return False
        self._directory(path, owner_only=True)
        return True

    def info(self, handle, *, directory):
        handle = self._handle(handle)
        if (
            handle.entry["directory"] is not directory
            or handle.entry["reparse"]
            or (not directory and handle.entry["links"] != 1)
            or handle.access & rebind._READ_CONTROL == 0
            or handle.access & rebind._READ_ATTRIBUTES == 0
        ):
            raise rebind.RebindError("protected_path_invalid")
        return 71, handle.entry["identity"]

    def verify_acl(self, handle, sid, *, directory=False):
        handle = self._handle(handle)
        if self._fault("acl", handle.path) or sid != self.sid:
            raise rebind.RebindError("protected_io_failed")
        if handle.entry["owner_only"] is not True:
            raise rebind.RebindError("protected_io_failed")
        if handle.entry["directory"] is not directory:
            raise rebind.RebindError("protected_io_failed")
        if handle.access & rebind._READ_CONTROL == 0:
            raise rebind.RebindError("protected_io_failed")
        self.events.append(("acl", handle.path, directory))

    def ReadFile(self, raw_handle, buffer, size, count_pointer, overlapped):
        handle = self._handle(raw_handle)
        self.events.append(("read_same_handle", handle.path, size))
        if (
            handle.access & rebind._GENERIC_READ == 0
            or self._fault("read", handle.path)
            or (
                self.fail == ("readback", handle.path)
                and handle.entry["data"] != _old_documents()[1]
            )
            or overlapped is not None
        ):
            return False
        payload = handle.entry["data"][handle.cursor : handle.cursor + size]
        if payload:
            C.memmove(buffer, payload, len(payload))
        handle.cursor += len(payload)
        self._set_out(count_pointer, len(payload), W.DWORD)
        return True

    def SetFilePointerEx(self, raw_handle, distance, result_pointer, move_method):
        handle = self._handle(raw_handle)
        if move_method != 0 or distance < 0:
            return False
        handle.cursor = distance
        self._set_out(result_pointer, handle.cursor, C.c_longlong)
        self.events.append(("seek", handle.path, handle.cursor))
        return True

    def WriteFile(self, raw_handle, buffer, size, count_pointer, overlapped):
        handle = self._handle(raw_handle)
        self.events.append(("write", handle.path, size))
        if handle.access & rebind._GENERIC_WRITE == 0 or overlapped is not None:
            return False
        payload = C.string_at(buffer, size)
        if self._fault("write", handle.path):
            partial = payload[: max(1, len(payload) // 2)]
            self._put(handle, partial)
            self._set_out(count_pointer, len(partial), W.DWORD)
            return False
        self._put(handle, payload)
        self._set_out(count_pointer, len(payload), W.DWORD)
        return True

    @staticmethod
    def _put(handle, payload):
        data = bytearray(handle.entry["data"])
        end = handle.cursor + len(payload)
        if handle.cursor > len(data):
            data.extend(b"\0" * (handle.cursor - len(data)))
        if end > len(data):
            data.extend(b"\0" * (end - len(data)))
        data[handle.cursor : end] = payload
        handle.entry["data"] = bytes(data)
        handle.cursor = end

    def SetEndOfFile(self, raw_handle):
        handle = self._handle(raw_handle)
        if handle.access & rebind._GENERIC_WRITE == 0:
            return False
        data = bytearray(handle.entry["data"])
        del data[handle.cursor :]
        handle.entry["data"] = bytes(data)
        self.events.append(("truncate", handle.path, handle.cursor))
        return not self._fault("truncate", handle.path)

    def FlushFileBuffers(self, raw_handle):
        handle = self._handle(raw_handle)
        if handle.access & rebind._GENERIC_WRITE == 0:
            return False
        self.events.append(("flush", handle.path))
        return not self._fault("flush", handle.path)

    def CloseHandle(self, raw_handle):
        handle = self._handle(raw_handle)
        if self._fault("close", handle.path):
            return False
        handle.closed = True
        return True

    def active_handles(self):
        return tuple(handle for handle in self.handles.values() if not handle.closed)


class _DescriptorContext:
    def __init__(self, descriptor):
        self.descriptor = descriptor

    def __enter__(self):
        return self.descriptor

    def __exit__(self, *_):
        return False


class _FakeProtectedOS:
    """Runs the production Win32 adapter against injectable in-memory leaves."""

    def __init__(self, old_admission, old_map, *, fail=None):
        self.api = _FakeWin32API(old_admission, old_map, fail=fail)
        fake_private = SimpleNamespace(_api=lambda: self.api)
        self.adapter = rebind._Win32Leaves(fake_private)

    @property
    def entries(self):
        return self.api.entries

    @property
    def events(self):
        return self.api.events

    def exists(self, path):
        return path in self.api.entries

    def active_handles(self):
        return self.api.active_handles()

    def __getattr__(self, name):
        return getattr(self.adapter, name)


def _invoke(fake, held_map):
    return rebind.rebind_fixed_deployment(
        held_source_map_raw=held_map,
        source_review_ref=rebind.REVIEW_REF,
        held_review_json_raw=(_REVIEW_DIR / "review.json").read_bytes(),
        held_review_readme_raw=(_REVIEW_DIR / "README.md").read_bytes(),
        held_reviewed_test_raw=_reviewed_test_raw(),
        reader_module=current_reader,
        private_module=certification_roundtrip_private,
        io=fake,
    )


def test_fixed_rebind_preserves_old_bytes_and_updates_only_the_two_documents():
    old_admission, old_map = _old_documents()
    fake = _FakeProtectedOS(old_admission, old_map)
    held_map = _source_map()
    original_file_identity = {
        path: (fake.entries[path]["identity"], fake.entries[path]["owner_only"])
        for path in rebind._DEPLOYMENT_PATHS.values()
    }

    result = _invoke(fake, held_map)

    assert result == {
        "status": "SOURCE_FAKE_REBOUND",
        "backup_created": True,
        "source_map_updated": True,
        "deployment_updated": True,
        "readback_verified": True,
        "handles_released": True,
    }
    backup = rebind._DEPLOYMENT / rebind.BACKUP_CHILD
    assert fake.entries[backup / "deployment.json"]["data"] == old_admission
    assert fake.entries[backup / "source-map.json"]["data"] == old_map
    assert all(fake.entries[backup / name]["owner_only"] for name in rebind.BACKUP_NAMES)
    assert fake.entries[rebind._DEPLOYMENT_PATHS["source-map.json"]]["data"] == held_map
    assert {
        path: (fake.entries[path]["identity"], fake.entries[path]["owner_only"])
        for path in rebind._DEPLOYMENT_PATHS.values()
    } == original_file_identity
    final_admission = current_reader._strict(
        fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"], 64 * 1024
    )
    assert final_admission["review_ref"] == rebind.REVIEW_REF
    assert final_admission["source_map_sha256"] == hashlib.sha256(held_map).hexdigest()
    assert not fake.active_handles()
    file_opens = [event for event in fake.events if event[0] == "open" and not event[2]]
    assert all(event[4] == rebind._FILE_SHARE_READ for event in file_opens[:2])
    create_events = [event for event in fake.events if event[0] == "create_new"]
    expected_backup_access = (
        rebind._GENERIC_READ
        | rebind._GENERIC_WRITE
        | rebind._READ_CONTROL
        | rebind._READ_ATTRIBUTES
    )
    assert len(create_events) == 2
    assert all(
        event[2] == expected_backup_access and event[3] == 0 and event[4] == "owner-only"
        for event in create_events
    )


def test_partial_source_map_write_keeps_all_handles_and_reports_finite_state():
    old_admission, old_map = _old_documents()
    map_path = rebind._DEPLOYMENT_PATHS["source-map.json"]
    fake = _FakeProtectedOS(old_admission, old_map, fail=("write", map_path))
    held_map = _source_map()

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, held_map)

    assert caught.value.code == "protected_write_uncertain"
    assert caught.value.state == {
        "backup_created": True,
        "source_map_updated": False,
        "deployment_updated": False,
        "readback_verified": False,
        "handles_released": False,
    }
    assert fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"] == old_admission
    assert len(fake.active_handles()) > 0
    assert rebind._ORPHANED_CONTEXTS[-1][0] is fake
    rebind._ORPHANED_CONTEXTS.pop()


def test_flush_failure_after_source_map_write_retains_the_uncertain_handle_set():
    old_admission, old_map = _old_documents()
    map_path = rebind._DEPLOYMENT_PATHS["source-map.json"]
    fake = _FakeProtectedOS(old_admission, old_map, fail=("flush", map_path))
    held_map = _source_map()

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, held_map)

    assert caught.value.code == "protected_write_uncertain"
    assert caught.value.state["source_map_updated"] is False
    assert fake.entries[map_path]["data"] == held_map
    assert fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"] == old_admission
    assert len(fake.active_handles()) > 0
    assert rebind._ORPHANED_CONTEXTS[-1][0] is fake
    rebind._ORPHANED_CONTEXTS.pop()


def test_source_map_readback_failure_retains_the_uncertain_handle_set():
    old_admission, old_map = _old_documents()
    map_path = rebind._DEPLOYMENT_PATHS["source-map.json"]
    fake = _FakeProtectedOS(old_admission, old_map, fail=("readback", map_path))
    held_map = _source_map()

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, held_map)

    assert caught.value.code == "protected_io_failed"
    assert caught.value.state["source_map_updated"] is False
    assert caught.value.state["deployment_updated"] is False
    assert fake.entries[map_path]["data"] == held_map
    assert fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"] == old_admission
    assert fake.active_handles()
    assert rebind._ORPHANED_CONTEXTS[-1][0] is fake
    rebind._ORPHANED_CONTEXTS.pop()


def test_deployment_write_failure_keeps_source_map_and_old_admission_as_fail_closed_pair():
    old_admission, old_map = _old_documents()
    admission_path = rebind._DEPLOYMENT_PATHS["deployment.json"]
    fake = _FakeProtectedOS(old_admission, old_map, fail=("write", admission_path))
    held_map = _source_map()

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, held_map)

    assert caught.value.code == "protected_write_uncertain"
    assert caught.value.state["source_map_updated"] is True
    assert caught.value.state["deployment_updated"] is False
    assert fake.entries[rebind._DEPLOYMENT_PATHS["source-map.json"]]["data"] == held_map
    assert fake.entries[admission_path]["data"] != old_admission
    assert len(fake.active_handles()) > 0
    assert rebind._ORPHANED_CONTEXTS[-1][0] is fake
    rebind._ORPHANED_CONTEXTS.pop()


def test_pre_mutation_acquisition_failure_closes_handles_and_leaves_metadata_untouched():
    old_admission, old_map = _old_documents()
    map_path = rebind._DEPLOYMENT_PATHS["source-map.json"]
    fake = _FakeProtectedOS(old_admission, old_map, fail=("open", map_path))

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, _source_map())

    assert caught.value.code == "protected_io_failed"
    assert caught.value.state["source_map_updated"] is False
    assert not fake.active_handles()
    assert fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"] == old_admission
    assert fake.entries[rebind._DEPLOYMENT_PATHS["source-map.json"]]["data"] == old_map


def test_owner_acl_readback_failure_closes_handles_before_any_metadata_write():
    old_admission, old_map = _old_documents()
    map_path = rebind._DEPLOYMENT_PATHS["source-map.json"]
    fake = _FakeProtectedOS(old_admission, old_map, fail=("acl", map_path))

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, _source_map())

    assert caught.value.code == "protected_io_failed"
    assert not fake.active_handles()
    assert fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"] == old_admission
    assert fake.entries[map_path]["data"] == old_map


def test_unverified_backup_write_retains_handles_without_metadata_mutation():
    old_admission, old_map = _old_documents()
    backup_file = rebind._DEPLOYMENT / rebind.BACKUP_CHILD / "deployment.json"
    fake = _FakeProtectedOS(old_admission, old_map, fail=("read", backup_file))

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, _source_map())

    assert caught.value.code == "protected_write_uncertain"
    assert caught.value.state["backup_created"] is True
    assert caught.value.state["source_map_updated"] is False
    assert fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"] == old_admission
    assert fake.entries[rebind._DEPLOYMENT_PATHS["source-map.json"]]["data"] == old_map
    assert fake.active_handles()
    assert rebind._ORPHANED_CONTEXTS[-1][0] is fake
    rebind._ORPHANED_CONTEXTS.pop()


def test_hardlinked_existing_metadata_is_rejected_and_released():
    old_admission, old_map = _old_documents()
    fake = _FakeProtectedOS(old_admission, old_map)
    map_path = rebind._DEPLOYMENT_PATHS["source-map.json"]
    fake.entries[map_path]["links"] = 2

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, _source_map())

    assert caught.value.code == "protected_path_invalid"
    assert not fake.active_handles()
    assert fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"] == old_admission
    assert fake.entries[map_path]["data"] == old_map


def test_backup_name_is_never_overwritten():
    old_admission, old_map = _old_documents()
    fake = _FakeProtectedOS(old_admission, old_map)
    occupied = rebind._DEPLOYMENT / rebind.BACKUP_CHILD
    fake.api._directory(occupied, owner_only=True)

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, _source_map())

    assert caught.value.code == "backup_name_in_use"
    assert caught.value.state["backup_created"] is False
    assert not fake.active_handles()
    assert fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"] == old_admission
    assert fake.entries[rebind._DEPLOYMENT_PATHS["source-map.json"]]["data"] == old_map


def test_production_old_map_pin_rejects_synthetic_r1_bytes(monkeypatch):
    old_admission, old_map = _old_documents()
    fake = _FakeProtectedOS(old_admission, old_map)
    monkeypatch.setattr(rebind, "OLD_SOURCE_MAP_SHA256", _PRODUCTION_OLD_MAP_SHA256)

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, _source_map())

    assert caught.value.code == "old_metadata_invalid"
    assert not fake.active_handles()
    assert fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"] == old_admission
    assert fake.entries[rebind._DEPLOYMENT_PATHS["source-map.json"]]["data"] == old_map


def test_old_admission_must_keep_the_exact_r1_review_reference():
    _old_admission, old_map = _old_documents()
    wrong_admission = _canonical(
        {
            "schema": current_reader.ADMISSION_SCHEMA,
            "status": "ADMITTED_SOURCE_PIN",
            "profile": current_reader.PROFILE,
            "source_map_sha256": hashlib.sha256(old_map).hexdigest(),
            "review_ref": rebind.REVIEW_REF,
        }
    )
    fake = _FakeProtectedOS(wrong_admission, old_map)

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, _source_map())

    assert caught.value.code == "old_metadata_invalid"
    assert not fake.active_handles()
    assert fake.entries[rebind._DEPLOYMENT_PATHS["deployment.json"]]["data"] == wrong_admission
    assert fake.entries[rebind._DEPLOYMENT_PATHS["source-map.json"]]["data"] == old_map


def test_close_uncertainty_retains_context_after_verified_rebind():
    old_admission, old_map = _old_documents()
    fake = _FakeProtectedOS(old_admission, old_map, fail=("close", rebind._DEPLOYMENT))

    with pytest.raises(rebind.RebindError) as caught:
        _invoke(fake, _source_map())

    assert caught.value.code == "protected_close_uncertain"
    assert caught.value.state["source_map_updated"] is True
    assert caught.value.state["deployment_updated"] is True
    assert caught.value.state["readback_verified"] is True
    assert caught.value.state["handles_released"] is False
    assert len(fake.active_handles()) > 0
    assert rebind._ORPHANED_CONTEXTS[-1][0] is fake
    rebind._ORPHANED_CONTEXTS.pop()


def test_review_and_source_map_binding_fail_before_private_os_access():
    old_admission, old_map = _old_documents()
    fake = _FakeProtectedOS(old_admission, old_map)

    with pytest.raises(rebind.RebindError) as caught:
        rebind.rebind_fixed_deployment(
            held_source_map_raw=_source_map(),
            source_review_ref="caller-chosen-review",
            held_review_json_raw=(_REVIEW_DIR / "review.json").read_bytes(),
            held_review_readme_raw=(_REVIEW_DIR / "README.md").read_bytes(),
            held_reviewed_test_raw=_reviewed_test_raw(),
            reader_module=current_reader,
            private_module=certification_roundtrip_private,
            io=fake,
        )

    assert caught.value.code == "review_identity_mismatch"
    assert not fake.events
