"""Fresh-process source-origin check with SDK imports denied."""

from __future__ import annotations

import importlib.abc
import sys


class _RejectCtpSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "bt_api_ctp" or fullname.startswith("bt_api_ctp."):
            raise AssertionError("optional CTP SDK import attempted")
        return None


sys.meta_path.insert(0, _RejectCtpSdk())
import backtrader_runtime.ctp_simnow_td_trading_readiness as readiness

candidate_root = r"D:\temp\iteration41-g6s-main-td-settlement-candidate-20260927"
expected = candidate_root + r"\backtrader_runtime\ctp_simnow_td_trading_readiness.py"
assert readiness.__file__ == expected, readiness.__file__
assert not any(name == "bt_api_ctp" or name.startswith("bt_api_ctp.") for name in sys.modules)
print("python=" + sys.version.split()[0])
print("readiness_origin=" + readiness.__file__)
print("sdk_modules_loaded=0")
