import importlib.abc
import sys

_BLOCKED = ("bt_api_py", "bt_api_ctp", "_ctp")
class _NoNativeSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in _BLOCKED):
            raise ImportError("independent QA blocked real SDK/native import: " + fullname)
        return None
sys.meta_path.insert(0, _NoNativeSdk())
