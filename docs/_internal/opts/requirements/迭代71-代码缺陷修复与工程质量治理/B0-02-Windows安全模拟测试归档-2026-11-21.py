"""In-memory leaves for the archived Windows gateway initializer; no Win32 calls."""
import hashlib
import ntpath
import os
import stat
import sys
import types
from pathlib import Path

import pytest

ARCHIVE = Path(r"C:\Users\yunji\AppData\Local\Temp\iter71_rg_b_0hxe45m2\post")
SOURCE = ARCHIVE / "backtrader/live_state/gateway_initialization.py"
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == "ae36a4d7ce49ff79b0c056682d23008855a67175be0cf24e545d69ef4684330f"
sys.path.insert(0, str(ARCHIVE))
import backtrader.live_state.gateway_initialization as init
assert Path(init.__file__).resolve() == SOURCE.resolve()


class Unavailable(RuntimeError):
    pass


@pytest.mark.parametrize("attack", ["none", "directory", "root_reservation", "state_reservation"])
def test_windows_binding_after_initialize(monkeypatch, attack):
    root = r"R:\synthetic"
    state_dir = ntpath.join(root, "state")
    root_reserve = ntpath.join(root, ".gateway_example_init.reserve")
    state_reserve = ntpath.join(state_dir, "gateway_example_init.reserve")
    nodes = {root: {"kind": "dir", "id": 1}}
    events = []
    handles = {}
    serial = [10]

    def create(path, kind):
        assert path not in nodes
        serial[0] += 1
        nodes[path] = {"kind": kind, "id": serial[0]}
        return stamp(path)

    def stamp(path):
        node = nodes[path]
        mode = stat.S_IFDIR if node["kind"] == "dir" else stat.S_IFREG
        return (1, node["id"], mode, 0, 1, 0, 0, 0)

    def lstat(path, *, follow_symlinks=False):
        assert follow_symlinks is False
        s = stamp(path)
        return types.SimpleNamespace(st_dev=s[0], st_ino=s[1], st_mode=s[2])

    def listdir(path):
        return [ntpath.basename(p) for p in nodes if ntpath.dirname(p) == path]

    def open_nofollow(path, *, share_delete):
        assert share_delete is True and nodes[path]["kind"] == "file"
        fd = 1000 + len(handles)
        handles[fd] = stamp(path)
        events.append(("open_reservation", path))
        return fd, fd

    fake_os = types.SimpleNamespace(
        path=types.SimpleNamespace(join=ntpath.join, lexists=lambda p: p in nodes),
        stat=lstat,
        listdir=listdir,
        close=lambda fd: events.append(("close_fake_fd", fd)),
    )
    sec = types.ModuleType("bt_api_py._win32_security")
    sec.Win32SecurityUnavailable = Unavailable
    sec.is_reparse_point = lambda path: False
    sec.inspect_owner = lambda path, **kwargs: types.SimpleNamespace(is_current_user=True, others_writable=False)
    sec.open_nofollow = open_nofollow
    sec.handle_stamp = lambda handle: handles[handle]
    sdk = types.ModuleType("bt_api_py")
    sdk.__path__ = []
    monkeypatch.setitem(sys.modules, "bt_api_py", sdk)
    monkeypatch.setitem(sys.modules, "bt_api_py._win32_security", sec)
    monkeypatch.setattr(init, "os", fake_os)
    monkeypatch.setattr(init, "_create_exclusive_owner_only_file_windows", lambda path, **kw: create(path, "file"))
    monkeypatch.setattr(init, "_mkdir_owner_only_windows", lambda path: create(path, "dir"))
    monkeypatch.setattr(init, "_flush_dir_windows", lambda path: events.append(("flush", path)))
    monkeypatch.setattr(init, "_write_marker_at", lambda path, uuid: events.append(("marker", path)))

    def initialize(path):
        assert path == root
        events.append(("initialize", path))
        changed = {"directory": state_dir, "root_reservation": root_reserve,
                   "state_reservation": state_reserve}.get(attack)
        if changed:
            nodes[changed]["id"] += 100
        return types.SimpleNamespace(strategy_uuid="synthetic", paths=types.SimpleNamespace(state_dir=state_dir))

    monkeypatch.setattr(init, "StrategyStateDir", types.SimpleNamespace(initialize=initialize))
    monkeypatch.setattr(init, "verify_gateway_preparation", lambda obj: events.append(("verify", obj.strategy_uuid)))
    paths = types.SimpleNamespace(strategy_dir=root, state_dir=state_dir)
    if attack == "none":
        result = init._prepare_gateway_state_windows(paths)
        assert result.strategy_uuid == "synthetic"
        assert ("verify", "synthetic") in events
    else:
        code = "STATE_SETUP_DIRECTORY_CHANGED" if attack == "directory" else "STATE_SETUP_RESERVATION_CHANGED"
        with pytest.raises(RuntimeError, match="^" + code + "$"):
            init._prepare_gateway_state_windows(paths)
        assert ("initialize", root) in events
        assert not any(event[0] in {"marker", "verify"} for event in events)
        assert any(event == ("open_reservation", root_reserve) for event in events)
        assert any(event == ("open_reservation", state_reserve) for event in events)
