"""Isolated no-real-SDK import guard for Iteration 41 Store/Runtime tests."""
import importlib.abc
import json
import os
import sys

BLOCKED_ROOT = os.path.normcase(os.path.abspath(r"D:\bt_api_py"))
LOG_PATH = os.environ.get("I41_SDK_IMPORT_GUARD_LOG")

def is_blocked_path(value):
    try:
        candidate = os.path.normcase(os.path.abspath(value or os.getcwd()))
        return candidate == BLOCKED_ROOT or candidate.startswith(BLOCKED_ROOT + os.sep)
    except (TypeError, OSError):
        return False

before_path = list(sys.path)
removed = [entry for entry in before_path if is_blocked_path(entry)]
sys.path[:] = [entry for entry in before_path if not is_blocked_path(entry)]
preloaded = sorted(name for name in sys.modules if name == "bt_api_py" or name.startswith("bt_api_py.") or name == "_ctp" or name.startswith("_ctp."))


def record(event):
    if not LOG_PATH:
        return
    with open(LOG_PATH, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True, ensure_ascii=True) + "\n")


class DenyNativeSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "bt_api_py" or fullname.startswith("bt_api_py.") or fullname == "_ctp" or fullname.startswith("_ctp."):
            record({"kind": "blocked_import_attempt", "module": fullname, "pid": os.getpid(), "executable": sys.executable})
            raise ModuleNotFoundError("real CTP SDK imports are blocked in this isolated integration run", name=fullname)
        return None

sys.meta_path.insert(0, DenyNativeSdk())
record({"kind": "guard_start", "pid": os.getpid(), "executable": sys.executable, "removed_sdk_sys_path": removed, "preloaded_sdk_modules": preloaded, "sys_path_after_guard": list(sys.path)})