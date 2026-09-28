import atexit
import importlib.abc
import json
import os
import socket
import sys

EVENTS = []
PREFIXES = ("bt_api_ctp", "bt_api_py.ctp", "_ctp", "ctp", "thostmduserapi", "thosttraderapi", "vnpy")
class ProviderImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + ".") for p in PREFIXES):
            EVENTS.append("blocked_provider_import:" + fullname)
            raise ImportError("CTP/native provider import blocked by guarded Store regression")
        return None
sys.meta_path.insert(0, ProviderImportBlocker())
for module in tuple(sys.modules):
    if any(module == p or module.startswith(p + ".") for p in PREFIXES):
        raise RuntimeError("provider/native module loaded before guard: " + module)

def _loopback(address):
    host = address[0] if isinstance(address, tuple) and address else address
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    return str(host).lower() in {"localhost", "127.0.0.1", "::1"}

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_create_connection = socket.create_connection
_original_sendto = socket.socket.sendto

def _connect(self, address):
    if not _loopback(address):
        EVENTS.append("blocked_network:connect")
        raise RuntimeError("non-loopback network disabled")
    return _original_connect(self, address)
def _connect_ex(self, address):
    if not _loopback(address):
        EVENTS.append("blocked_network:connect_ex")
        raise RuntimeError("non-loopback network disabled")
    return _original_connect_ex(self, address)
def _create_connection(address, *args, **kwargs):
    if not _loopback(address):
        EVENTS.append("blocked_network:create_connection")
        raise RuntimeError("non-loopback network disabled")
    return _original_create_connection(address, *args, **kwargs)
def _sendto(self, data, *args):
    address = args[-1]
    if not _loopback(address):
        EVENTS.append("blocked_network:sendto")
        raise RuntimeError("non-loopback network disabled")
    return _original_sendto(self, data, *args)
socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.create_connection = _create_connection
socket.socket.sendto = _sendto

def _write_log():
    directory = os.environ.get("ITER41_GUARD_LOG_DIR")
    if not directory:
        return
    os.makedirs(directory, exist_ok=True)
    loaded = sorted(name for name in sys.modules if any(name == p or name.startswith(p + ".") for p in PREFIXES))
    path = os.path.join(directory, str(os.getpid()) + ".json")
    with open(path, "w", encoding="utf-8") as stream:
        json.dump({"events": EVENTS, "native_modules_loaded": loaded}, stream, sort_keys=True, indent=2)
        stream.write("\n")
atexit.register(_write_log)

# Reject direct CTP extension or DLL loads, even when a caller bypasses imports.
import _imp
import ctypes
import importlib.machinery

def _ctp_native_name(value):
    name = str(value or "").replace("\\", "/").lower()
    return any(part in name for part in ("bt_api_ctp", "_ctp", "thost", "traderapi", "mduserapi", "ctpse"))

_original_exec_module = importlib.machinery.ExtensionFileLoader.exec_module
def _guarded_exec_module(self, module):
    if _ctp_native_name(getattr(self, "path", "")) or _ctp_native_name(getattr(module, "__name__", "")):
        EVENTS.append("blocked_ctp_extension_loader")
        raise ImportError("CTP extension load blocked")
    return _original_exec_module(self, module)
importlib.machinery.ExtensionFileLoader.exec_module = _guarded_exec_module

_original_create_dynamic = _imp.create_dynamic
def _guarded_create_dynamic(spec):
    if _ctp_native_name(getattr(spec, "origin", "")) or _ctp_native_name(getattr(spec, "name", "")):
        EVENTS.append("blocked_ctp_create_dynamic")
        raise ImportError("CTP extension load blocked")
    return _original_create_dynamic(spec)
_imp.create_dynamic = _guarded_create_dynamic

_original_dlopen = ctypes._dlopen
def _guarded_dlopen(name, *args, **kwargs):
    if _ctp_native_name(name):
        EVENTS.append("blocked_ctp_dlopen")
        raise OSError("CTP DLL load blocked")
    return _original_dlopen(name, *args, **kwargs)
ctypes._dlopen = _guarded_dlopen

_original_getaddrinfo = socket.getaddrinfo
_original_gethostbyname = socket.gethostbyname
def _guarded_getaddrinfo(host, *args, **kwargs):
    if host is not None and not _loopback(host):
        EVENTS.append("blocked_dns:getaddrinfo")
        raise RuntimeError("external DNS disabled")
    return _original_getaddrinfo(host, *args, **kwargs)
def _guarded_gethostbyname(host):
    if not _loopback(host):
        EVENTS.append("blocked_dns:gethostbyname")
        raise RuntimeError("external DNS disabled")
    return _original_gethostbyname(host)
socket.getaddrinfo = _guarded_getaddrinfo
socket.gethostbyname = _guarded_gethostbyname
