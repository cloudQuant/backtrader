import _imp
import ctypes
import importlib.machinery
import importlib.util
import socket
import sitecustomize
from types import ModuleType

checks = []
for label, call in (
    ("import", lambda: sitecustomize.ProviderImportBlocker().find_spec("bt_api_ctp")),
    ("create_dynamic", lambda: _imp.create_dynamic(importlib.util.spec_from_file_location("_ctp", r"Z:\missing\_ctp.pyd"))),
    ("extension_loader", lambda: importlib.machinery.ExtensionFileLoader("_ctp", r"Z:\missing\_ctp.pyd").exec_module(ModuleType("_ctp"))),
    ("dlopen", lambda: ctypes.CDLL("nonexistent_thosttraderapi_se.dll")),
    ("dns", lambda: socket.getaddrinfo("198.51.100.1", 80)),
):
    try:
        call()
    except (ImportError, OSError, RuntimeError):
        checks.append(label)
    else:
        raise SystemExit("guard failed: " + label)
print("BLOCKED=" + ",".join(checks))
