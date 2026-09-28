import importlib.abc
import json
import os
import sys

class _BlockCtpExtension(importlib.abc.MetaPathFinder):
    _blocked = {"bt_api_ctp.ctp._ctp", "_ctp"}

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self._blocked:
            return None
        log_path = os.environ.get("G4_CTP_NATIVE_GUARD_LOG")
        if log_path:
            with open(log_path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps({"module": fullname, "blocked": True}) + "\n")
        raise ModuleNotFoundError(
            "blocked by disposable G4 native import guard", name=fullname
        )

sys.meta_path.insert(0, _BlockCtpExtension())
