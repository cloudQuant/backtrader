"""Focused Windows tests for config path leases held through a native action."""

import ctypes
import os
import struct
import threading
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

import backtrader_runtime.ctp_config_action_linearization as config_lease_module
from backtrader_runtime.ctp_config_action_linearization import (
    ConfigActionLinearizationError,
    ConfigPathReadLease,
    acquire_config_path_read_lease,
)


@pytest.mark.parametrize("drive_type", [0, 1, 2, 4, 5, 6])
def test_fake_winapi_rejects_every_non_fixed_drive_type(drive_type):
    fake_kernel32 = SimpleNamespace(GetDriveTypeW=lambda root: drive_type)
    with pytest.raises(
        ConfigActionLinearizationError,
        match="config_action_lease_fixed_local_drive_required",
    ):
        config_lease_module._require_fixed_local_drive(fake_kernel32, "R:" + chr(92))


def test_fake_winapi_accepts_fixed_drive_type():
    seen_roots = []
    fake_kernel32 = SimpleNamespace(GetDriveTypeW=lambda root: seen_roots.append(root) or 3)
    config_lease_module._require_fixed_local_drive(fake_kernel32, "C:" + chr(92))
    assert seen_roots == ["C:" + chr(92)]


def test_read_lease_close_retains_failed_handle_and_can_retry(monkeypatch):
    close_results = {3: [False, True], 2: [True], 1: [True]}
    close_calls = []

    def close_handle(handle):
        close_calls.append(handle)
        return close_results[handle].pop(0)

    fake_kernel32 = SimpleNamespace(CloseHandle=close_handle)
    monkeypatch.setattr(config_lease_module.ctypes, "get_last_error", lambda: 5, raising=False)
    lease = ConfigPathReadLease(fake_kernel32, Path("config.yaml"), [1, 2, 3], 3)

    with pytest.raises(
        ConfigActionLinearizationError,
        match="config_action_lease_close_failed: winerrors=\[5\]",
    ):
        lease.close()

    assert close_calls == [3, 2, 1]
    assert lease._handles == [3]
    with pytest.raises(ConfigActionLinearizationError, match="config_action_lease_closed"):
        lease.read_bytes()

    lease.close()
    lease.close()
    assert close_calls == [3, 2, 1, 3]
    assert lease._handles == []
    assert lease._close_complete
    assert not hasattr(lease, "execute_action")


@pytest.mark.skipif(os.name != "nt", reason="requires a Windows absolute path")
def test_acquire_rejects_remote_drive_before_ntfs_probe(tmp_path, monkeypatch):
    fake_kernel32 = SimpleNamespace(
        GetDriveTypeW=lambda root: 4,
        GetVolumeInformationW=lambda *args: pytest.fail(
            "remote drive must be rejected before the NTFS probe"
        ),
    )
    monkeypatch.setattr(config_lease_module, "_win_api", lambda: fake_kernel32)
    with pytest.raises(
        ConfigActionLinearizationError,
        match="config_action_lease_fixed_local_drive_required",
    ):
        acquire_config_path_read_lease(tmp_path / "config.yaml")


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file sharing and reparse APIs")
def test_windows_ntfs_lease_blocks_config_mutations_during_action():
    """Exercise writes, replaces, renames and reparse changes during a fake action."""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    device_io_control = kernel32.DeviceIoControl
    device_io_control.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    device_io_control.restype = ctypes.c_int

    invalid_handle = ctypes.c_void_p(-1).value
    file_write_attributes = 0x00000100
    file_share_read = 0x00000001
    open_existing = 3
    file_flag_backup_semantics = 0x02000000
    fsctl_set_reparse_point = 0x000900A4
    io_reparse_tag_mount_point = 0xA0000003
    io_reparse_tag_symlink = 0xA000000C

    def open_attributes(path, *, is_directory):
        flags = file_flag_backup_semantics if is_directory else 0
        handle = create_file(
            str(path),
            file_write_attributes,
            file_share_read,
            None,
            open_existing,
            flags,
            None,
        )
        if handle == invalid_handle or handle is None:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def set_reparse_point(handle, tag, target):
        target_text = str(target)
        substitute = ("\\??\\" + target_text).encode("utf-16-le")
        printable = target_text.encode("utf-16-le")
        path_buffer = substitute + b"\0\0" + printable + b"\0\0"
        if tag == io_reparse_tag_mount_point:
            body = struct.pack(
                "<HHHH", 0, len(substitute), len(substitute) + 2, len(printable)
            ) + path_buffer
        elif tag == io_reparse_tag_symlink:
            body = struct.pack(
                "<HHHHI", 0, len(substitute), len(substitute) + 2, len(printable), 0
            ) + path_buffer
        else:  # pragma: no cover - test helper only handles these two standard tags
            raise AssertionError("unexpected reparse tag")
        reparse_data = struct.pack("<IHH", tag, len(body), 0) + body
        reparse_input = ctypes.create_string_buffer(reparse_data)
        returned = ctypes.c_uint32()
        success = device_io_control(
            handle,
            fsctl_set_reparse_point,
            reparse_input,
            len(reparse_data),
            None,
            0,
            ctypes.byref(returned),
            None,
        )
        return bool(success), ctypes.get_last_error()

    with TemporaryDirectory(prefix="bt-config-linearization-") as temporary:
        temp_root = Path(temporary)
        config_root = temp_root / "checked-root"
        runtime_dir = config_root / "runtime"
        target_root = temp_root / "retarget"
        runtime_dir.mkdir(parents=True)
        (target_root / "runtime").mkdir(parents=True)
        config_path = runtime_dir / "config.yaml"
        replacement_path = temp_root / "replacement.yaml"
        config_path.write_bytes(b"source: sealed\n")
        replacement_path.write_bytes(b"source: replacement\n")
        (target_root / "runtime" / "config.yaml").write_bytes(b"source: retargeted\n")

        action_entered = threading.Event()
        allow_action_to_finish = threading.Event()
        action_result = []
        action_errors = []

        def native_action_window():
            try:
                with acquire_config_path_read_lease(config_path) as lease:
                    assert lease.read_bytes() == b"source: sealed\n"
                    action_entered.set()
                    if not allow_action_to_finish.wait(5):
                        raise AssertionError("test did not release the native action")
                    action_result.append(
                        (lease.read_bytes(), config_path.read_bytes())
                    )
            except Exception as exc:  # surfaced in the test-owning thread
                action_errors.append(exc)

        action_thread = threading.Thread(target=native_action_window)
        action_thread.start()
        attr_handles = []
        try:
            if not action_entered.wait(5):
                action_thread.join(1)
                pytest.fail("lease acquisition failed before action: {!r}".format(action_errors))

            # The OS permits FILE_WRITE_ATTRIBUTES handles despite the lease's
            # share mode. Exercise the actual standard reparse operations too.
            config_attributes = open_attributes(config_path, is_directory=False)
            attr_handles.append(config_attributes)

            with pytest.raises(OSError):
                config_path.write_text("source: direct-write\n", encoding="utf-8")
            with pytest.raises(OSError):
                os.replace(replacement_path, config_path)
            with pytest.raises(OSError):
                os.rename(config_path, temp_root / "config-renamed.yaml")
            with pytest.raises(OSError):
                config_path.unlink()
            with pytest.raises(OSError):
                os.rename(runtime_dir, temp_root / "runtime-moved")
            with pytest.raises(OSError):
                os.rename(config_root, temp_root / "checked-root-moved")
            moved_temp_root = temp_root.parent / (temp_root.name + "-moved")
            with pytest.raises(OSError):
                os.rename(temp_root, moved_temp_root)

            # Attribute handles can be opened even while the lease is held.
            # Try setting a mount-point reparse tag on every occupied path
            # directory; NTFS must reject each with ERROR_DIR_NOT_EMPTY.
            for directory in (runtime_dir, config_root, temp_root):
                directory_attributes = open_attributes(directory, is_directory=True)
                attr_handles.append(directory_attributes)
                mount_succeeded, mount_error = set_reparse_point(
                    directory_attributes, io_reparse_tag_mount_point, target_root
                )
                assert not mount_succeeded
                assert mount_error == 145  # NTFS: ERROR_DIR_NOT_EMPTY

            symlink_succeeded, symlink_error = set_reparse_point(
                config_attributes,
                io_reparse_tag_symlink,
                target_root / "runtime" / "config.yaml",
            )
            assert not symlink_succeeded
            assert symlink_error == 1314  # this token lacks SeCreateSymbolicLinkPrivilege

            # The unrelated same-volume sibling remains available while the
            # config action is held.
            siblings = (
                runtime_dir / "journal-sibling.sqlite",
                config_root / "runtime-sibling.sqlite",
                temp_root / "volume-sibling.sqlite",
            )
            for sibling in siblings:
                sibling.write_bytes(b"sibling works")
                assert sibling.stat().st_dev == config_path.stat().st_dev
                assert sibling.read_bytes() == b"sibling works"
        finally:
            allow_action_to_finish.set()
            action_thread.join(5)
            for handle in reversed(attr_handles):
                close_handle(handle)

        assert not action_thread.is_alive()
        assert not action_errors
        assert action_result == [
            (b"source: sealed\n", b"source: sealed\n")
        ]


@pytest.mark.skipif(os.name != "nt", reason="requires Windows NTFS reparse APIs")
def test_windows_file_write_attributes_can_set_custom_reparse_tag_under_lease(
    tmp_path,
):
    """Show why a share-mode lease cannot fence arbitrary name-surrogate tags."""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(config_lease_module._ByHandleFileInformation),
    ]
    get_info.restype = ctypes.c_int
    device_io_control = kernel32.DeviceIoControl
    device_io_control.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    device_io_control.restype = ctypes.c_int

    file_write_attributes = 0x00000100
    file_share_read = 0x00000001
    generic_read = 0x80000000
    open_existing = 3
    fsctl_set_reparse_point = 0x000900A4
    fsctl_delete_reparse_point = 0x000900AC
    file_attribute_reparse_point = 0x00000400
    custom_name_surrogate_tag = 0x20001234
    custom_guid = uuid.UUID("c2872fc6-8a6c-4ab6-9e6d-b571a83ef527")

    config_path = tmp_path / "config.yaml"
    config_bytes = b"sealed: true\n"
    config_path.write_bytes(config_bytes)
    action_entered = threading.Event()
    allow_action_to_finish = threading.Event()
    action_result = []
    action_errors = []
    attribute_handle = None
    tag_set = False

    def fake_native_action_window():
        try:
            with acquire_config_path_read_lease(config_path) as lease:
                assert lease.read_bytes() == config_bytes
                action_entered.set()
                if not allow_action_to_finish.wait(5):
                    raise AssertionError("test did not release the native action")
                action_result.append(lease.read_bytes())
        except Exception as exc:  # surfaced in the test-owning thread
            action_errors.append(exc)

    action_thread = threading.Thread(target=fake_native_action_window)
    action_thread.start()
    try:
        assert action_entered.wait(5), repr(action_errors)
        attribute_handle = create_file(
            str(config_path),
            file_write_attributes,
            file_share_read,
            None,
            open_existing,
            0,
            None,
        )
        assert attribute_handle not in (None, ctypes.c_void_p(-1).value)

        data = b"test"
        set_input_data = (
            struct.pack("<IHH", custom_name_surrogate_tag, len(data), 0)
            + custom_guid.bytes_le
            + data
        )
        set_input = ctypes.create_string_buffer(set_input_data)
        bytes_returned = ctypes.c_uint32()
        assert device_io_control(
            attribute_handle,
            fsctl_set_reparse_point,
            set_input,
            len(set_input_data),
            None,
            0,
            ctypes.byref(bytes_returned),
            None,
        ), ctypes.WinError(ctypes.get_last_error())
        tag_set = True

        info = config_lease_module._ByHandleFileInformation()
        assert get_info(attribute_handle, ctypes.byref(info))
        assert info.attributes & file_attribute_reparse_point

        path_handle = create_file(
            str(config_path),
            generic_read,
            file_share_read,
            None,
            open_existing,
            0,
            None,
        )
        if path_handle in (None, ctypes.c_void_p(-1).value):
            # NTFS accepts the tag on the held file handle, then pathname
            # lookup fails because no installed filter handles this custom
            # name-surrogate tag. ERROR_CANT_ACCESS_FILE is returned here.
            assert ctypes.get_last_error() == 1920
        else:
            close_handle(path_handle)

        # The fake native action is already in flight while the exact config
        # pathname becomes a reparse point. Clean the disposable path before
        # releasing the action thread.
        delete_input_data = struct.pack(
            "<IHH", custom_name_surrogate_tag, 0, 0
        ) + custom_guid.bytes_le
        delete_input = ctypes.create_string_buffer(delete_input_data)
        assert device_io_control(
            attribute_handle,
            fsctl_delete_reparse_point,
            delete_input,
            len(delete_input_data),
            None,
            0,
            ctypes.byref(bytes_returned),
            None,
        ), ctypes.WinError(ctypes.get_last_error())
        tag_set = False
    finally:
        allow_action_to_finish.set()
        if tag_set and attribute_handle is not None:
            delete_input_data = struct.pack(
                "<IHH", custom_name_surrogate_tag, 0, 0
            ) + custom_guid.bytes_le
            delete_input = ctypes.create_string_buffer(delete_input_data)
            bytes_returned = ctypes.c_uint32()
            device_io_control(
                attribute_handle,
                fsctl_delete_reparse_point,
                delete_input,
                len(delete_input_data),
                None,
                0,
                ctypes.byref(bytes_returned),
                None,
            )
        if attribute_handle is not None:
            close_handle(attribute_handle)
        action_thread.join(5)

    assert not action_thread.is_alive()
    assert not action_errors
    assert action_result == [config_bytes]


def test_config_action_lease_rejects_non_windows_hosts():
    if os.name == "nt":
        pytest.skip("Windows-specific lease is available on this host")
    with pytest.raises(
        ConfigActionLinearizationError, match="config_action_lease_windows_required"
    ):
        acquire_config_path_read_lease("config.yaml")


@pytest.mark.skipif(os.name != "nt", reason="requires a local Windows NTFS hard link")
def test_config_action_lease_rejects_local_hardlinked_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_bytes(b"sealed: true\n")
    os.link(config_path, tmp_path / "config-alias.yaml")

    with pytest.raises(
        ConfigActionLinearizationError,
        match="config_action_lease_config_hardlink_not_allowed",
    ):
        acquire_config_path_read_lease(config_path)
