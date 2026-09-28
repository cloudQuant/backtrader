import importlib.abc
class _DenyCtp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "_ctp" or fullname.startswith("_ctp.") or fullname == "bt_api_ctp" or fullname.startswith("bt_api_ctp."):
            raise RuntimeError("QA_IMPORT_GUARD_BLOCKED:" + fullname)
        return None
import sys
sys.meta_path.insert(0, _DenyCtp())
