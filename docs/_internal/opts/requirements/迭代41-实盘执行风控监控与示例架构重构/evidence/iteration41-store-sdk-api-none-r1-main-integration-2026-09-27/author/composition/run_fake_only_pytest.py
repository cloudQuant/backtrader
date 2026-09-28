import importlib.abc
import os
import socket
import sys

import pytest

sys.path.insert(0, os.getcwd())

BLOCKED_IMPORT_PREFIXES = (
    "bt_api_py",
    "bt_api_ctp",
    "thostmduserapi",
    "thosttraderapi",
    "vnpy",
)
blocked_import_attempts = []
network_attempts = []


class _OptionalSdkNativeImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(
            fullname == prefix or fullname.startswith(prefix + ".")
            for prefix in BLOCKED_IMPORT_PREFIXES
        ):
            blocked_import_attempts.append(fullname)
            raise ImportError("optional SDK/native import blocked by fake-only QA tripwire")
        return None


def _block_network(*args, **kwargs):
    network_attempts.append("socket")
    raise AssertionError("network use blocked by fake-only QA tripwire")


sys.meta_path.insert(0, _OptionalSdkNativeImportBlocker())
socket.socket.connect = _block_network
socket.create_connection = _block_network

preloaded = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in BLOCKED_IMPORT_PREFIXES)
)
if preloaded:
    print(f"OPTIONAL_IMPORT_PRELOADED={preloaded!r}")
    raise SystemExit(2)

result = pytest.main(
    [
        "-q",
        "--junitxml=D:\\temp\\iteration41-store-sdk-api-guard-only-20260927\\r1-p4-fake-only-guarded.junit.xml",
        "tests/unit/test_sdk_api_none_mechanical_fallback_composition.py",
        "tests/unit/test_ctp_options_simnow_mechanical_api_boundary.py",
        "tests/unit/stores/test_btapistore_sdk_api_none.py",
    ]
)
print(f"OPTIONAL_IMPORT_GUARD={blocked_import_attempts!r}")
print(f"NETWORK_GUARD={network_attempts!r}")
if blocked_import_attempts or network_attempts:
    raise SystemExit(1)
raise SystemExit(int(result))
