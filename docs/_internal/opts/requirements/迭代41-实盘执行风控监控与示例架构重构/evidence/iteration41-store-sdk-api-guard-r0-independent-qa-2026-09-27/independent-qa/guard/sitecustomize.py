import importlib.abc
BLOCKED = ("bt_api_py", "bt_api_ctp", "_ctp")
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in BLOCKED):
            raise RuntimeError("blocked forbidden SDK/native import: " + fullname)
        return None
import sys
sys.meta_path.insert(0, Block())
