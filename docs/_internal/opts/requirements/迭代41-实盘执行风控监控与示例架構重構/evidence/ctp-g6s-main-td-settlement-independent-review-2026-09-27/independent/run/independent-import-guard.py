"""Independent fresh-process import guard for G6-S candidate source."""
import importlib.abc
import sys

class RejectSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "bt_api_ctp" or fullname.startswith("bt_api_ctp."):
            raise AssertionError("optional CTP SDK import attempted")
        return None

sys.meta_path.insert(0, RejectSdk())
import backtrader_runtime.ctp_simnow_td_trading_readiness as readiness
expected = r"D:\temp\iteration41-g6s-main-td-settlement-independent-qa-20260927\backtrader_runtime\ctp_simnow_td_trading_readiness.py"
assert readiness.__file__ == expected, readiness.__file__
assert not any(name == "bt_api_ctp" or name.startswith("bt_api_ctp.") for name in sys.modules)
print("readiness_origin=" + readiness.__file__)
print("sdk_modules_loaded=0")
