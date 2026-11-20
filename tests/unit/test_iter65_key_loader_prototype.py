"""65.01 baseline for the 007 key loader; these observations are not the target policy.

The iteration 65 plan calls for POSIX 0600 and no ``~`` expansion; the 007
example currently accepts other owner-only modes and expands ``~``. Windows ACL
behavior is not tested here. All files contain synthetic data and no service,
account, real key, credentials, or network is used.
"""

import importlib.util
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest


WORKTREE = Path(__file__).resolve().parents[2]
LOADER_PATH = WORKTREE / "examples/live/007_ctp/gateway_local_resources.py"


@pytest.fixture(scope="module")
def loader():
    spec = importlib.util.spec_from_file_location("iter65_gateway_local_resources", LOADER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def synthetic_key(tmp_path):
    if os.name != "posix" or not all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY", "geteuid")):
        pytest.skip("007 loader requires POSIX no-follow and effective-user support")
    # Resolve the pytest directory once so parent symlinks in the system temp
    # path are not inadvertently presented as part of the test target.
    directory = tmp_path.resolve()
    path = directory / "synthetic-key"
    path.write_bytes(b"0" * 40)  # valid Z85 encoding of 32 zero bytes, never a real key
    if path.stat().st_uid != os.geteuid():
        pytest.skip("temporary file is not owned by the current effective user")
    return path


@pytest.mark.parametrize("mode", [0o600, 0o400, 0o700], ids=["0600", "0400", "0700"])
def test_private_loader_currently_accepts_readable_owner_only_modes(loader, synthetic_key, mode):
    synthetic_key.chmod(mode)
    if stat.S_IMODE(synthetic_key.stat().st_mode) != mode or not os.access(synthetic_key, os.R_OK):
        pytest.skip("filesystem does not preserve this readable POSIX mode")
    contents = loader._open_key(synthetic_key, private=True)
    assert len(contents) == 40
    assert all(value == ord("0") for value in contents)


@pytest.mark.parametrize("mode", [0o640, 0o660], ids=["0640", "0660"])
def test_private_loader_rejects_group_permissions(loader, synthetic_key, mode):
    synthetic_key.chmod(mode)
    if stat.S_IMODE(synthetic_key.stat().st_mode) != mode:
        pytest.skip("filesystem does not preserve this POSIX mode")
    with pytest.raises(RuntimeError, match="^KEY_FILE_UNTRUSTED$"):
        loader._open_key(synthetic_key, private=True)


@pytest.mark.parametrize("link_type", ["symbolic", "hard"])
def test_private_loader_rejects_linked_files(loader, synthetic_key, link_type):
    synthetic_key.chmod(0o600)
    link = synthetic_key.parent / (link_type + "-link")
    try:
        if link_type == "symbolic":
            link.symlink_to(synthetic_key)
        else:
            os.link(synthetic_key, link)
    except (NotImplementedError, OSError):
        pytest.skip(f"filesystem cannot create {link_type} links")
    with pytest.raises(RuntimeError, match="^KEY_FILE_UNTRUSTED$"):
        loader._open_key(link, private=True)


def test_windows_branch_is_fail_closed_for_missing_key(loader, monkeypatch, tmp_path):
    # Windows now uses the hardened read_bounded_windows parity path.  A
    # missing/unprotected key must still fail closed (never a platform error,
    # never a fabricated value). Stub only this module's os reference.
    monkeypatch.setattr(loader, "os", SimpleNamespace(name="nt"))
    with pytest.raises(RuntimeError, match="^KEY_FILE_UNAVAILABLE$"):
        loader._open_key(tmp_path / "unopened", private=True)


def test_windows_reader_rejects_unprotected_key(tmp_path):
    """Windows parity refuses a group/world-readable key (owner-only required)."""
    if os.name != "nt":
        pytest.skip("Windows key-reader vector")
    from bt_api_py._win32_security import Win32SecurityUnavailable, read_bounded_windows

    key = tmp_path / "loose-key"
    key.write_bytes(b"0" * 40)
    with pytest.raises(Win32SecurityUnavailable):
        read_bounded_windows(key, 64, protected=True)


def test_existing_profile_validation_expands_tilde_with_synthetic_home(loader, monkeypatch, tmp_path):
    if os.name != "posix":
        pytest.skip("this vector controls POSIX HOME expansion, not Windows user-profile expansion")
    home = tmp_path / "synthetic-home"
    monkeypatch.setenv("HOME", str(home))
    config = SimpleNamespace(
        client_config=SimpleNamespace(communication={"profiles": {"local": {"security_profile_ref": "synthetic"}}}),
        risk_selection=None,
    )
    raw = {"synthetic": {
        "server_public_key_file": "~/server",
        "client_public_key_file": "~/client",
        "client_secret_key_file": "~/secret",
    }}
    paths = loader.validate_security_file_config(config, raw, tmp_path / "strategy")
    assert paths == {"synthetic": [home / "server", home / "client", home / "secret"]}


def _win_set_dacl(path: Path, *extra_grants: str) -> None:
    """Apply an explicit protected DACL (owner Full + optional extra icacls grants)."""
    import subprocess
    from bt_api_py._win32_security import current_user_sid

    sid = current_user_sid()
    cmd = ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(F)"]
    for grant in extra_grants:
        cmd.extend(["/grant:r", grant])
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows real-DACL key loader vector")
def test_windows_owner_only_and_privileged_dacl_accepted_for_private_and_public(loader, tmp_path):
    key = tmp_path.resolve() / "owner-only.key"
    key.write_bytes(b"0" * 40 + b"\n")
    _win_set_dacl(key)
    assert loader._open_key(key, private=True) == b"0" * 40
    assert loader._open_key(key, private=False) == b"0" * 40

    # Owner + SYSTEM + Built-in Administrators (Windows equivalent of root) must remain accepted.
    _win_set_dacl(key, "*S-1-5-18:(F)", "*S-1-5-32-544:(F)")
    assert loader._open_key(key, private=True) == b"0" * 40
    assert loader._open_key(key, private=False) == b"0" * 40


@pytest.mark.skipif(os.name != "nt", reason="Windows real-DACL private vs public parity vector")
def test_windows_private_key_rejects_other_read_while_public_key_allows_it(loader, tmp_path):
    key = tmp_path.resolve() / "auth-users-read.key"
    key.write_bytes(b"0" * 40)
    # Authenticated Users (S-1-5-11) has read-only access (no write): POSIX 0o644 parity.
    _win_set_dacl(key, "*S-1-5-11:(R)")
    assert loader._open_key(key, private=False) == b"0" * 40
    with pytest.raises(RuntimeError, match="^KEY_FILE_UNTRUSTED$"):
        loader._open_key(key, private=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows real-DACL write-rejection vector")
@pytest.mark.parametrize("private", [True, False])
def test_windows_key_rejects_other_write_for_both_private_and_public(loader, tmp_path, private):
    key = tmp_path.resolve() / f"other-write-{private}.key"
    key.write_bytes(b"0" * 40)
    _win_set_dacl(key, "*S-1-5-11:(M)")
    with pytest.raises(RuntimeError, match="^KEY_FILE_UNTRUSTED$"):
        loader._open_key(key, private=private)


@pytest.mark.skipif(os.name != "nt", reason="Windows Z85 validation vector")
@pytest.mark.parametrize("payload", [b"0" * 10, b" " * 40, b"\x00" * 40])
def test_windows_invalid_z85_raises_uniform_format_error(loader, tmp_path, payload):
    key = tmp_path.resolve() / "bad-z85.key"
    key.write_bytes(payload)
    _win_set_dacl(key)
    with pytest.raises(RuntimeError, match="^KEY_FORMAT_INVALID$"):
        loader._open_key(key, private=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows narrow-exception vector")
def test_windows_open_key_does_not_swallow_programming_error(loader, monkeypatch, tmp_path):
    import bt_api_py._win32_security as win32_sec

    key = tmp_path.resolve() / "prog-err.key"
    key.write_bytes(b"0" * 40)
    _win_set_dacl(key)
    monkeypatch.setattr(
        win32_sec,
        "read_bounded_windows",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AttributeError("synthetic_bug")),
    )
    with pytest.raises(AttributeError, match="synthetic_bug"):
        loader._open_key(key, private=False)


def test_z85_decode_helper_unifies_error_codes_and_missing_zmq(loader, monkeypatch):
    import builtins

    assert loader._decode_z85_key(b"0" * 40 + b"\r\n") == b"0" * 40
    with pytest.raises(RuntimeError, match="^KEY_FORMAT_INVALID$"):
        loader._decode_z85_key(b" " * 40)
    with pytest.raises(RuntimeError, match="^KEY_FORMAT_INVALID$"):
        loader._decode_z85_key(b"0" * 39)

    real_import = builtins.__import__

    def block_zmq(name, *args, **kwargs):
        if name == "zmq.utils" or name.startswith("zmq"):
            raise ImportError("no zmq")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_zmq)
    with pytest.raises(RuntimeError, match="^KEY_PLATFORM_UNSUPPORTED$"):
        loader._decode_z85_key(b"0" * 40)
