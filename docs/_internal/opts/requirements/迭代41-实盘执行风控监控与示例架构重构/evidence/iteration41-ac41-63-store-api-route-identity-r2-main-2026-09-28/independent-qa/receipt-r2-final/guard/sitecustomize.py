import atexit
import json
import os
import socket
import sys
import types

_events = ["fake_optional_sdk_stub:bt_api_py"]
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection

def _is_loopback(address):
    host = address[0] if isinstance(address, tuple) and address else address
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    return str(host).lower() in {"localhost", "127.0.0.1", "::1"}

def _guarded_socket_connect(self, address):
    if _is_loopback(address):
        _events.append("local_loopback_only:" + repr(address))
        return _real_connect(self, address)
    _events.append("blocked_network:socket.connect:" + repr(address))
    raise RuntimeError("non-loopback network disabled in independent fake-only QA")

def _guarded_socket_connect_ex(self, address):
    if _is_loopback(address):
        _events.append("local_loopback_only:" + repr(address))
        return _real_connect_ex(self, address)
    _events.append("blocked_network:socket.connect_ex:" + repr(address))
    raise RuntimeError("non-loopback network disabled in independent fake-only QA")

def _guarded_create_connection(address, *args, **kwargs):
    if _is_loopback(address):
        _events.append("local_loopback_only:" + repr(address))
        return _real_create_connection(address, *args, **kwargs)
    _events.append("blocked_network:create_connection:" + repr(address))
    raise RuntimeError("non-loopback network disabled in independent fake-only QA")

socket.socket.connect = _guarded_socket_connect
socket.socket.connect_ex = _guarded_socket_connect_ex
socket.create_connection = _guarded_create_connection

_blocked_prefixes = (
    "bt_api_ctp", "thostmduserapi", "thosttraderapi", "vnpy", "ctp",
)
class _ProviderImportBlocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "bt_api_py":
            return None
        if any(fullname == p or fullname.startswith(p + ".") for p in _blocked_prefixes):
            _events.append("blocked_provider_import:" + fullname)
            raise ImportError("provider/native import blocked by fake-only QA")
        if fullname.startswith("bt_api_py."):
            _events.append("blocked_provider_import:" + fullname)
            raise ImportError("provider import blocked by fake-only QA")
        return None

sys.meta_path.insert(0, _ProviderImportBlocker())
_fake = types.ModuleType("bt_api_py")
class CtpExecutionApprovalCapability:
    pass
_fake.CtpExecutionApprovalCapability = CtpExecutionApprovalCapability
sys.modules["bt_api_py"] = _fake

def _write_guard_log():
    path = os.environ.get("ITER41_GUARD_LOG")
    if path:
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"events": _events}, stream, sort_keys=True, indent=2)
            stream.write("\n")

atexit.register(_write_guard_log)
