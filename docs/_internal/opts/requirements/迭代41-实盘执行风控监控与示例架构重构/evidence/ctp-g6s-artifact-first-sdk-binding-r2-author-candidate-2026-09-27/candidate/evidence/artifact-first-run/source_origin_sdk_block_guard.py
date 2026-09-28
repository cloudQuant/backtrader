"""Fresh-process origin and default-pin check with SDK imports denied."""

from __future__ import annotations

import importlib.abc
import sys


class _RejectCtpSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "bt_api_ctp" or fullname.startswith("bt_api_ctp."):
            raise AssertionError("optional CTP SDK import attempted")
        return None


sys.meta_path.insert(0, _RejectCtpSdk())
import backtrader_runtime.ctp_sdk_artifact_binding as binding
import backtrader_runtime.ctp_simnow_td_trading_readiness as readiness

candidate_root = r"D:\temp\iteration41-g6s-artifact-first-sdk-binding-candidate-20260927"
assert readiness.__file__ == candidate_root + r"\backtrader_runtime\ctp_simnow_td_trading_readiness.py"
assert binding.__file__ == candidate_root + r"\backtrader_runtime\ctp_sdk_artifact_binding.py"
try:
    readiness.require_trusted_ctp_sdk_artifact_before_client()
except binding.CtpSdkArtifactBindingError as exc:
    assert exc.reason == "sdk_artifact_release_pin_unavailable"
else:
    raise AssertionError("zero-default artifact policy unexpectedly accepted")
assert not any(name == "bt_api_ctp" or name.startswith("bt_api_ctp.") for name in sys.modules)
print("python=" + sys.version.split()[0])
print("readiness_origin=" + readiness.__file__)
print("artifact_binding_origin=" + binding.__file__)
print("code_owned_artifact_pin=unset")
print("sdk_modules_loaded=0")
