"""Fail closed on optional CTP SDK imports and network access during isolated QA."""
import builtins
import importlib.abc
import json
import os
import socket
import sys
import threading

_log_path = os.environ.get("G1_SUPERVISOR_QA_GUARD_LOG")
_lock = threading.Lock()
_blocked_roots = {
    "bt_api_py", "bt_api_base", "bt_api_ctp", "bt_api_execution",
    "thosttrader", "_ctp", "ctpbee", "ctp_api",
}

def _record(kind, detail):
    if not _log_path:
        return
    with _lock:
        with open(_log_path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"kind": kind, "detail": str(detail)}, sort_keys=True) + "\n")

class _BlockSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in _blocked_roots:
            _record("sdk_import_blocked", fullname)
            raise ModuleNotFoundError("optional SDK is disabled during inert QA")
        return None

sys.meta_path.insert(0, _BlockSdk())
_original_import = builtins.__import__
def _guarded_import(name, *args, **kwargs):
    if name.split(".", 1)[0] in _blocked_roots:
        _record("sdk_import_blocked", name)
        raise ModuleNotFoundError("optional SDK is disabled during inert QA")
    return _original_import(name, *args, **kwargs)
builtins.__import__ = _guarded_import

def _block_network(kind):
    def blocked(*args, **kwargs):
        _record("network_blocked", kind)
        raise AssertionError("network access is blocked during inert QA")
    return blocked

for _name in ("getaddrinfo", "create_connection"):
    setattr(socket, _name, _block_network("socket." + _name))
for _name in ("connect", "connect_ex", "sendto"):
    setattr(socket.socket, _name, _block_network("socket.socket." + _name))
