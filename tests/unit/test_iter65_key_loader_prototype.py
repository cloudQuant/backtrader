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


def test_non_posix_guard_is_fail_closed_with_module_local_stub(loader, monkeypatch, tmp_path):
    # Replace only this module's os reference; never mutate shared os.name.
    monkeypatch.setattr(loader, "os", SimpleNamespace(name="nt"))
    with pytest.raises(RuntimeError, match="^KEY_PLATFORM_UNSUPPORTED$"):
        loader._open_key(tmp_path / "unopened", private=True)


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
