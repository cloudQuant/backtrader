"""Focused fake and Windows checks for the isolated anchor candidate."""

import ctypes
import json
import ntpath
import os
import struct
import tempfile
from types import SimpleNamespace

import pytest

from backtrader.notifications import _windows_anchor

USER_SID = "S-1-5-21-11-22-33-1001"
FULL = 0x001F01FF


class FakeAnchorApi:
    def __init__(
        self,
        *,
        existing_reparse=False,
        target_exists=False,
        owner_sid=USER_SID,
        initial_acl=None,
        persistent_acls=True,
    ):
        self.token_sid_calls = 0
        self.descriptor = object()
        self.directories = []
        self.existing_reparse = existing_reparse
        self.target_exists = target_exists
        self.owner_sid = owner_sid
        self.initial_acl = initial_acl
        self.persistent_acls = persistent_acls
        self.link_count = 1
        self.reparse_opened = False
        self.secured = False
        self.events = []
        self.writes = []
        self.closed = []
        self.deleted = []
        self.kernel32 = SimpleNamespace(GetDriveTypeW=lambda _root: 3)

    def token_user_sid(self):
        self.token_sid_calls += 1
        return USER_SID

    def security_descriptor(self, sid):
        assert sid == USER_SID
        return self.descriptor

    def free_security_descriptor(self, descriptor):
        assert descriptor is self.descriptor

    def open_root(self, drive):
        assert drive == "C:"
        return "root"

    def volume_supports_persistent_acls(self, drive):
        assert drive == "C:"
        return self.persistent_acls

    def open_or_create_directory(self, parent, name, *, is_final, token_sid, descriptor):
        assert token_sid == USER_SID
        assert descriptor is self.descriptor
        handle = "dir-" + name
        self.directories.append((parent, name, is_final, handle))
        return handle, True

    def open_relative_update_file(self, parent, name):
        if self.existing_reparse and not self.reparse_opened:
            self.reparse_opened = True
            return "reparse-target"
        if not self.target_exists:
            raise OSError(0xC0000034, "missing")
        return "existing-target"

    def attributes(self, handle):
        self.events.append(("attributes", handle))
        if handle == "reparse-target":
            _windows_anchor._reject_reparse(_windows_anchor._FILE_ATTRIBUTE_REPARSE_POINT)
        return 0

    def identity(self, handle):
        return (1, 2, 3, self.link_count)

    def acl(self, handle):
        assert handle in ("new-file", "existing-target")
        self.events.append(("acl", handle))
        if handle == "new-file" or self.secured:
            self.secured = True
            return USER_SID, True, ((0, 0, FULL, USER_SID),)
        entries = self.initial_acl or ((0, 0, FULL, "S-1-1-0"),)
        return self.owner_sid, False, entries

    def set_owner_only_acl(self, handle, descriptor):
        assert descriptor is self.descriptor
        assert handle in ("new-file", "existing-target")
        self.events.append(("secure", handle))
        self.secured = True

    def create_relative_file(self, parent, name, descriptor):
        assert parent == "dir-private"
        assert descriptor is self.descriptor
        if self.target_exists:
            raise OSError(_windows_anchor._STATUS_COLLISION, "already exists")
        self.target_exists = True
        return "new-file"

    def truncate_and_write(self, handle, payload):
        assert handle in ("new-file", "existing-target")
        assert self.secured, "content write happened before owner-only ACL verification"
        self.events.append(("write", handle))
        self.writes.append(payload)

    def mark_for_delete(self, handle):
        self.deleted.append(handle)

    def close(self, handle):
        self.closed.append(handle)


def test_owner_acl_policy_uses_exact_token_user_and_rejects_inheritance():
    valid = ((0, 0, FULL, USER_SID),)
    _windows_anchor._validate_owner_only_acl(USER_SID, USER_SID, True, valid)
    with pytest.raises(OSError):
        _windows_anchor._validate_owner_only_acl("S-1-5-18", USER_SID, True, valid)
    with pytest.raises(OSError):
        _windows_anchor._validate_owner_only_acl(USER_SID, USER_SID, False, valid)
    with pytest.raises(OSError):
        _windows_anchor._validate_owner_only_acl(
            USER_SID, USER_SID, True, valid + ((0, 0, FULL, "S-1-1-0"),)
        )


def test_directory_acl_accepts_owner_inheritance_flags_but_no_external_ace():
    inherited_owner = ((0, 0x1 | 0x2, FULL, USER_SID),)
    _windows_anchor._validate_owner_only_directory_acl(USER_SID, USER_SID, True, inherited_owner)
    with pytest.raises(OSError):
        _windows_anchor._validate_owner_only_directory_acl(
            USER_SID, USER_SID, False, inherited_owner
        )
    with pytest.raises(OSError):
        _windows_anchor._validate_owner_only_directory_acl(
            USER_SID, USER_SID, True, inherited_owner + ((0, 0, FULL, "S-1-1-0"),)
        )


def test_existing_file_policy_rejects_external_aces_before_acl_mutation():
    _windows_anchor._validate_repairable_owner_acl(
        USER_SID, USER_SID, ((0, 0x1 | 0x2, FULL, USER_SID),)
    )
    with pytest.raises(OSError):
        _windows_anchor._validate_repairable_owner_acl(
            USER_SID, USER_SID, ((0, 0, 0x1, "S-1-1-0"),)
        )


def test_existing_ancestor_policy_rejects_untrusted_directory_mutation():
    _windows_anchor._validate_safe_ancestor_acl(
        "S-1-5-18", USER_SID, ((0, 0, 0x001200A9, "S-1-1-0"),)
    )
    with pytest.raises(OSError):
        _windows_anchor._validate_safe_ancestor_acl(
            USER_SID, USER_SID, ((0, 0, _windows_anchor._FILE_ADD_FILE, "S-1-1-0"),)
        )
    with pytest.raises(OSError):
        _windows_anchor._validate_safe_ancestor_acl(USER_SID, USER_SID, ((1, 0, 0, "S-1-1-0"),))
    with pytest.raises(OSError):
        _windows_anchor._validate_safe_ancestor_acl(
            USER_SID,
            USER_SID,
            ((0, 0, _windows_anchor._FILE_WRITE_ATTRIBUTES, "S-1-1-0"),),
        )


def test_existing_ancestor_owner_rights_maps_only_to_verified_owner():
    owner_rights = ((0, 0x1 | 0x2, FULL, _windows_anchor._OWNER_RIGHTS_SID),)
    _windows_anchor._validate_safe_ancestor_acl(USER_SID, USER_SID, owner_rights)
    with pytest.raises(OSError):
        _windows_anchor._validate_safe_ancestor_acl("S-1-1-0", USER_SID, owner_rights)
    with pytest.raises(OSError):
        _windows_anchor._validate_safe_ancestor_acl(
            USER_SID, USER_SID, ((0, 0x1 | 0x2, FULL, "S-1-3-0"),)
        )


def test_fake_windows_rejects_fixed_volume_without_persistent_acls():
    fake = FakeAnchorApi(persistent_acls=False)
    with pytest.raises(OSError, match="persistent ACL"):
        _windows_anchor.persist_anchor(
            r"C:\sandbox\private\anchor.json", {"token": "synthetic"}, api=fake
        )
    assert fake.directories == []
    assert fake.writes == []


def test_fake_windows_persistence_uses_token_sid_and_handle_relative_update():
    fake = FakeAnchorApi()
    result = _windows_anchor.persist_anchor(
        r"C:\sandbox\private\anchor.json",
        {"bot_token": "synthetic-only", "to_user_id": "user"},
        api=fake,
    )
    assert result == r"C:\sandbox\private\anchor.json"
    assert fake.token_sid_calls == 1
    assert [(parent, name, final) for parent, name, final, _handle in fake.directories] == [
        ("root", "sandbox", False),
        ("dir-sandbox", "private", True),
    ]
    assert json.loads(fake.writes[0].decode("utf-8")) == {
        "bot_token": "synthetic-only",
        "to_user_id": "user",
    }
    assert len(fake.writes) == 1
    assert fake.events.index(("acl", "new-file")) < fake.events.index(("write", "new-file"))
    assert not any(event == ("secure", "new-file") for event in fake.events)
    assert "new-file" in fake.closed


def test_fake_windows_persistence_rejects_external_acl_before_update():
    fake = FakeAnchorApi(target_exists=True)
    with pytest.raises(OSError):
        _windows_anchor.persist_anchor(
            r"C:\sandbox\private\anchor.json", {"token": "synthetic"}, api=fake
        )
    assert fake.writes == []
    assert not any(event[0] == "secure" for event in fake.events)


def test_fake_windows_persistence_repairs_owner_only_dacl_without_write_owner():
    fake = FakeAnchorApi(target_exists=True, initial_acl=((0, 0x1 | 0x2, FULL, USER_SID),))
    _windows_anchor.persist_anchor(
        r"C:\sandbox\private\anchor.json", {"token": "synthetic"}, api=fake
    )
    assert fake.events.index(("secure", "existing-target")) < fake.events.index(
        ("write", "existing-target")
    )
    assert json.loads(fake.writes[0].decode("utf-8")) == {"token": "synthetic"}


def test_fake_windows_persistence_rejects_foreign_owner_and_hardlink_before_write():
    foreign = FakeAnchorApi(target_exists=True, owner_sid="S-1-5-18")
    with pytest.raises(OSError, match="not owned"):
        _windows_anchor.persist_anchor(
            r"C:\sandbox\private\anchor.json", {"token": "synthetic"}, api=foreign
        )
    assert foreign.writes == []
    assert not any(event[0] == "secure" for event in foreign.events)

    linked = FakeAnchorApi(target_exists=True)
    linked.link_count = 2
    with pytest.raises(OSError):
        _windows_anchor.persist_anchor(
            r"C:\sandbox\private\anchor.json", {"token": "synthetic"}, api=linked
        )
    assert linked.writes == []
    assert not any(event[0] == "secure" for event in linked.events)


def test_fake_windows_persistence_rejects_reparse_target_before_writing():
    fake = FakeAnchorApi(existing_reparse=True)
    with pytest.raises(OSError, match="reparse point"):
        _windows_anchor.persist_anchor(
            r"C:\sandbox\private\anchor.json", {"bot_token": "synthetic"}, api=fake
        )
    assert fake.writes == []
    assert not any(event[0] == "secure" for event in fake.events)
    assert "reparse-target" in fake.closed


@pytest.mark.skipif(os.name != "nt", reason="native Windows handle and DACL contract")
def test_native_windows_anchor_acl_update_old_handle_and_reparse_rejection():
    api = _windows_anchor._WindowsAnchorApi()
    token_sid = api.token_user_sid()
    descriptor = api.security_descriptor(token_sid)
    root = candidate_handle = None
    temp_handles = []
    private_handle = junction_handle = old_handle = current_handle = unsafe_handle = None
    attribute_directory = attribute_handle = None
    weak_descriptor = directory_descriptor = owner_only_descriptor = attribute_descriptor = None
    candidate_path = os.path.abspath(os.environ.get("USERPROFILE") or tempfile.gettempdir())
    drive, tail = ntpath.splitdrive(candidate_path)
    if not drive or not tail.startswith("\\"):
        raise AssertionError("Windows temp directory must be an absolute drive-letter path")
    probe_name = "native-anchor-" + os.urandom(8).hex()
    unsafe_name = "unsafe-parent-" + os.urandom(8).hex()
    junction_name = "junction-" + os.urandom(8).hex()
    old_handle = None
    try:
        assert api.volume_supports_persistent_acls(drive)
        root = api.open_root(drive)
        directory_options = (
            _windows_anchor._FILE_DIRECTORY_FILE
            | _windows_anchor._FILE_SYNCHRONOUS_IO_NONALERT
            | _windows_anchor._FILE_OPEN_REPARSE_POINT
        )
        parent = root
        for component in (part for part in tail.split("\\") if part):
            parent, _created = api.open_or_create_directory(
                parent,
                component,
                is_final=False,
                token_sid=token_sid,
                descriptor=descriptor,
            )
            temp_handles.append(parent)
        candidate_handle = parent

        directory_descriptor = ctypes.c_void_p()
        directory_sddl = "O:{0}D:P(A;OICI;FA;;;{0})".format(token_sid)
        if not api.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            directory_sddl, 1, ctypes.byref(directory_descriptor), None
        ):
            raise OSError(ctypes.get_last_error(), "could not build inheritable owner-only DACL")
        private_handle, created = api.open_or_create_directory(
            candidate_handle,
            probe_name,
            is_final=True,
            token_sid=token_sid,
            descriptor=directory_descriptor,
        )
        assert created is True
        owner, protected, entries = api.acl(private_handle)
        _windows_anchor._validate_owner_only_directory_acl(owner, token_sid, protected, entries)
        existing_directory, created = api.open_or_create_directory(
            candidate_handle,
            probe_name,
            is_final=True,
            token_sid=token_sid,
            descriptor=descriptor,
        )
        assert created is False
        try:
            owner, protected, entries = api.acl(existing_directory)
            _windows_anchor._validate_owner_only_directory_acl(owner, token_sid, protected, entries)
        finally:
            api.close(existing_directory)

        # A same-owner legacy file with an external ACE is refused before its
        # ACL or content changes; a previously opened reader keeps its access.
        weak_descriptor = ctypes.c_void_p()
        weak_sddl = "O:{0}D:P(A;;FA;;;{0})(A;;FA;;;WD)".format(token_sid)
        if not api.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            weak_sddl, 1, ctypes.byref(weak_descriptor), None
        ):
            raise OSError(ctypes.get_last_error(), "could not build test DACL")
        unsafe_handle = api._relative(
            candidate_handle,
            unsafe_name,
            _windows_anchor._FILE_LIST_DIRECTORY
            | _windows_anchor._FILE_TRAVERSE
            | _windows_anchor._FILE_ADD_FILE
            | _windows_anchor._FILE_READ_ATTRIBUTES
            | _windows_anchor._READ_CONTROL
            | _windows_anchor._DELETE
            | _windows_anchor._SYNCHRONIZE,
            _windows_anchor._FILE_CREATE,
            directory_options,
            security_descriptor=weak_descriptor,
        )
        unsafe_target = os.path.join(candidate_path, unsafe_name, "must-not-write.json")
        with pytest.raises(OSError):
            _windows_anchor.persist_anchor(unsafe_target, {"token": "synthetic"})
        assert not os.path.exists(unsafe_target)

        # FILE_WRITE_ATTRIBUTES alone permits an FSCTL_SET_REPARSE_POINT on
        # this handle. The same ACE on a path ancestor must therefore fail policy.
        attribute_descriptor = ctypes.c_void_p()
        attribute_sddl = "O:{0}D:P(A;;FA;;;{0})(A;;0x100;;;WD)".format(token_sid)
        if not api.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            attribute_sddl, 1, ctypes.byref(attribute_descriptor), None
        ):
            raise OSError(ctypes.get_last_error(), "could not build write-attributes test DACL")
        attribute_name = "reparse-capable-" + os.urandom(8).hex()
        attribute_directory = api._relative(
            candidate_handle,
            attribute_name,
            _windows_anchor._FILE_LIST_DIRECTORY
            | _windows_anchor._FILE_TRAVERSE
            | _windows_anchor._FILE_READ_ATTRIBUTES
            | _windows_anchor._READ_CONTROL
            | _windows_anchor._DELETE
            | _windows_anchor._SYNCHRONIZE,
            _windows_anchor._FILE_CREATE,
            directory_options,
            security_descriptor=attribute_descriptor,
        )
        attribute_owner, _protected, attribute_entries = api.acl(attribute_directory)
        with pytest.raises(OSError):
            _windows_anchor._validate_safe_ancestor_acl(
                attribute_owner, token_sid, attribute_entries
            )
        attribute_target = os.path.join(candidate_path, attribute_name, "must-not-write.json")
        with pytest.raises(OSError):
            _windows_anchor.persist_anchor(attribute_target, {"token": "synthetic"})
        assert not os.path.exists(attribute_target)
        attribute_handle = api._relative(
            candidate_handle,
            attribute_name,
            _windows_anchor._FILE_WRITE_ATTRIBUTES
            | _windows_anchor._FILE_READ_ATTRIBUTES
            | _windows_anchor._SYNCHRONIZE,
            _windows_anchor._FILE_OPEN,
            directory_options,
        )
        _set_junction(api, attribute_handle, candidate_path)
        with pytest.raises(OSError, match="reparse point"):
            api.attributes(attribute_handle)
        _delete_junction(api, attribute_handle)
        api.close(attribute_handle)
        attribute_handle = None
        api.mark_for_delete(attribute_directory)
        api.close(attribute_directory)
        attribute_directory = None
        weak_file = api._relative(
            private_handle,
            "legacy-external.json",
            0x2
            | _windows_anchor._FILE_READ_ATTRIBUTES
            | _windows_anchor._READ_CONTROL
            | _windows_anchor._DELETE
            | _windows_anchor._SYNCHRONIZE,
            _windows_anchor._FILE_CREATE,
            _windows_anchor._FILE_NON_DIRECTORY_FILE
            | _windows_anchor._FILE_SYNCHRONOUS_IO_NONALERT
            | _windows_anchor._FILE_OPEN_REPARSE_POINT,
            security_descriptor=weak_descriptor,
        )
        broad_bytes = b'{"legacy":"external-read-risk"}'
        api.write_and_flush(weak_file, broad_bytes)
        api.close(weak_file)
        weak_probe = api.open_relative_file(private_handle, "legacy-external.json")
        old_broad_handle = api.open_relative_read_file(private_handle, "legacy-external.json")
        try:
            legacy_owner, legacy_protected, legacy_entries = api.acl(weak_probe)
            assert legacy_owner == token_sid
            assert legacy_protected
            assert len(legacy_entries) == 2
            with pytest.raises(OSError):
                _windows_anchor.persist_anchor(
                    os.path.join(candidate_path, probe_name, "legacy-external.json"),
                    {"legacy": "must-not-change"},
                )
            assert api.acl(weak_probe) == (legacy_owner, legacy_protected, legacy_entries)
            assert api.read_handle_bytes(old_broad_handle) == broad_bytes
        finally:
            api.close(old_broad_handle)
            api.close(weak_probe)

        # An existing owner-only DACL with OI|CI can be protected without
        # requesting WRITE_OWNER; external ACEs above are never tightened.
        owner_only_descriptor = ctypes.c_void_p()
        owner_only_sddl = "O:{0}D:(A;OICI;FA;;;{0})".format(token_sid)
        if not api.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            owner_only_sddl, 1, ctypes.byref(owner_only_descriptor), None
        ):
            raise OSError(ctypes.get_last_error(), "could not build owner-only legacy DACL")
        owner_only_file = api._relative(
            private_handle,
            "legacy-owner.json",
            0x2
            | _windows_anchor._FILE_READ_ATTRIBUTES
            | _windows_anchor._READ_CONTROL
            | _windows_anchor._DELETE
            | _windows_anchor._SYNCHRONIZE,
            _windows_anchor._FILE_CREATE,
            _windows_anchor._FILE_NON_DIRECTORY_FILE
            | _windows_anchor._FILE_SYNCHRONOUS_IO_NONALERT
            | _windows_anchor._FILE_OPEN_REPARSE_POINT,
            security_descriptor=owner_only_descriptor,
        )
        api.write_and_flush(owner_only_file, b'{"legacy":true}')
        api.close(owner_only_file)
        _windows_anchor._write_in_directory(
            api,
            private_handle,
            "legacy-owner.json",
            token_sid,
            descriptor,
            b'{"legacy":false}',
        )
        legacy_verified = api.open_relative_read_file(private_handle, "legacy-owner.json")
        try:
            legacy_owner, legacy_protected, legacy_entries = api.acl(legacy_verified)
            _windows_anchor._validate_owner_only_acl(
                legacy_owner, token_sid, legacy_protected, legacy_entries
            )
            assert api.read_handle_bytes(legacy_verified) == b'{"legacy":false}'
        finally:
            api.close(legacy_verified)
        legacy_delete = api._relative(
            private_handle,
            "legacy-external.json",
            _windows_anchor._DELETE
            | _windows_anchor._FILE_READ_ATTRIBUTES
            | _windows_anchor._READ_CONTROL
            | _windows_anchor._SYNCHRONIZE,
            _windows_anchor._FILE_OPEN,
            _windows_anchor._FILE_NON_DIRECTORY_FILE
            | _windows_anchor._FILE_SYNCHRONOUS_IO_NONALERT
            | _windows_anchor._FILE_OPEN_REPARSE_POINT,
        )
        api.mark_for_delete(legacy_delete)
        api.close(legacy_delete)

        _windows_anchor._write_in_directory(
            api, private_handle, "anchor.json", token_sid, descriptor, b'{"token":"old"}'
        )
        old_handle = api.open_relative_read_file(private_handle, "anchor.json")
        old_bytes = api.read_handle_bytes(old_handle)
        old_identity = api.identity(old_handle)
        _windows_anchor._write_in_directory(
            api, private_handle, "anchor.json", token_sid, descriptor, b'{"token":"new"}'
        )
        api.seek_start(old_handle)
        updated_through_old_handle = api.read_handle_bytes(old_handle)
        assert api.identity(old_handle)[:3] == old_identity[:3]
        assert json.loads(old_bytes.decode("utf-8")) == {"token": "old"}
        assert json.loads(updated_through_old_handle.decode("utf-8")) == {"token": "new"}
        current_handle = api.open_relative_read_file(private_handle, "anchor.json")
        try:
            assert json.loads(api.read_handle_bytes(current_handle).decode("utf-8")) == {
                "token": "new"
            }
        finally:
            api.close(current_handle)
            current_handle = None

        # Build a real junction by handle, then prove OPEN_REPARSE_POINT
        # returns the link object and the handle metadata gate rejects it.
        junction_handle = api._relative(
            candidate_handle,
            junction_name,
            _windows_anchor._FILE_READ_ATTRIBUTES
            | _windows_anchor._READ_CONTROL
            | _windows_anchor._DELETE
            | _windows_anchor._FILE_WRITE_ATTRIBUTES
            | _windows_anchor._SYNCHRONIZE,
            _windows_anchor._FILE_CREATE,
            directory_options,
            security_descriptor=descriptor,
        )
        _set_junction(api, junction_handle, candidate_path)
        opened_junction = api._relative(
            candidate_handle,
            junction_name,
            _windows_anchor._FILE_READ_ATTRIBUTES
            | _windows_anchor._READ_CONTROL
            | _windows_anchor._DELETE
            | _windows_anchor._FILE_WRITE_ATTRIBUTES
            | _windows_anchor._SYNCHRONIZE,
            _windows_anchor._FILE_OPEN,
            directory_options,
        )
        try:
            with pytest.raises(OSError, match="reparse point"):
                api.attributes(opened_junction)
            with pytest.raises(OSError, match="reparse point"):
                _windows_anchor._write_in_directory(
                    api,
                    candidate_handle,
                    junction_name,
                    token_sid,
                    descriptor,
                    b'{"token":"must-not-write"}',
                )
            assert not os.path.exists(os.path.join(candidate_path, "must-not-write"))
        finally:
            _delete_junction(api, opened_junction)
            api.mark_for_delete(opened_junction)
            api.close(opened_junction)
        api.close(junction_handle)
        junction_handle = None

        for cleanup_name in ("anchor.json", "legacy-owner.json"):
            current_handle = api._relative(
                private_handle,
                cleanup_name,
                _windows_anchor._DELETE
                | _windows_anchor._FILE_READ_ATTRIBUTES
                | _windows_anchor._READ_CONTROL
                | _windows_anchor._SYNCHRONIZE,
                _windows_anchor._FILE_OPEN,
                _windows_anchor._FILE_NON_DIRECTORY_FILE
                | _windows_anchor._FILE_SYNCHRONOUS_IO_NONALERT
                | _windows_anchor._FILE_OPEN_REPARSE_POINT,
            )
            api.mark_for_delete(current_handle)
            api.close(current_handle)
            current_handle = None
        api.close(old_handle)
        old_handle = None
        api.mark_for_delete(private_handle)
        api.close(private_handle)
        private_handle = None
    finally:
        if old_handle is not None:
            api.close(old_handle)
        if current_handle is not None:
            api.close(current_handle)
        if junction_handle is not None:
            try:
                _delete_junction(api, junction_handle)
                api.mark_for_delete(junction_handle)
            except OSError:
                pass
            api.close(junction_handle)
        if private_handle is not None:
            for cleanup_name in ("anchor.json", "legacy-external.json", "legacy-owner.json"):
                try:
                    cleanup_handle = api._relative(
                        private_handle,
                        cleanup_name,
                        _windows_anchor._DELETE
                        | _windows_anchor._FILE_READ_ATTRIBUTES
                        | _windows_anchor._READ_CONTROL
                        | _windows_anchor._SYNCHRONIZE,
                        _windows_anchor._FILE_OPEN,
                        _windows_anchor._FILE_NON_DIRECTORY_FILE
                        | _windows_anchor._FILE_SYNCHRONOUS_IO_NONALERT
                        | _windows_anchor._FILE_OPEN_REPARSE_POINT,
                    )
                except OSError:
                    continue
                try:
                    api.mark_for_delete(cleanup_handle)
                except OSError:
                    pass
                api.close(cleanup_handle)
            try:
                api.mark_for_delete(private_handle)
            except OSError:
                pass
            api.close(private_handle)
        if unsafe_handle is not None:
            try:
                api.mark_for_delete(unsafe_handle)
            except OSError:
                pass
            api.close(unsafe_handle)
        if attribute_handle is not None:
            try:
                _delete_junction(api, attribute_handle)
            except OSError:
                pass
            api.close(attribute_handle)
        if attribute_directory is not None:
            try:
                api.mark_for_delete(attribute_directory)
            except OSError:
                pass
            api.close(attribute_directory)
        for handle in reversed(temp_handles):
            api.close(handle)
        if root is not None:
            api.close(root)
        if weak_descriptor:
            api.free_security_descriptor(weak_descriptor)
        if owner_only_descriptor:
            api.free_security_descriptor(owner_only_descriptor)
        if attribute_descriptor:
            api.free_security_descriptor(attribute_descriptor)
        if directory_descriptor:
            api.free_security_descriptor(directory_descriptor)
        api.free_security_descriptor(descriptor)


def _set_junction(api, handle, target):
    substitute = ("\\??\\" + target).encode("utf-16-le")
    printed = target.encode("utf-16-le")
    body = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(printed))
    body += substitute + b"\x00\x00" + printed + b"\x00\x00"
    payload = struct.pack("<IHH", 0xA0000003, len(body), 0) + body
    buffer = ctypes.create_string_buffer(payload)
    returned = ctypes.c_ulong()
    device_io = api.kernel32.DeviceIoControl
    device_io.argtypes = (
        _windows_anchor.wintypes.HANDLE,
        _windows_anchor.wintypes.DWORD,
        ctypes.c_void_p,
        _windows_anchor.wintypes.DWORD,
        ctypes.c_void_p,
        _windows_anchor.wintypes.DWORD,
        ctypes.POINTER(_windows_anchor.wintypes.DWORD),
        ctypes.c_void_p,
    )
    device_io.restype = _windows_anchor.wintypes.BOOL
    if not device_io(
        _windows_anchor._as_handle(handle),
        0x000900A4,  # FSCTL_SET_REPARSE_POINT
        buffer,
        len(payload),
        None,
        0,
        ctypes.byref(returned),
        None,
    ):
        raise OSError(ctypes.get_last_error(), "could not create test junction")


def _delete_junction(api, handle):
    payload = struct.pack("<IHH", 0xA0000003, 0, 0)
    buffer = ctypes.create_string_buffer(payload)
    returned = ctypes.c_ulong()
    device_io = api.kernel32.DeviceIoControl
    if not device_io(
        _windows_anchor._as_handle(handle),
        0x000900AC,  # FSCTL_DELETE_REPARSE_POINT
        buffer,
        len(payload),
        None,
        0,
        ctypes.byref(returned),
        None,
    ):
        raise OSError(ctypes.get_last_error(), "could not clear test junction")
