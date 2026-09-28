import inspect, json, sys
sys.path.insert(0, r'D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927\src')
from bt_api_execution.ctp_single_worker_candidate import CtpManagedSingleWorkerCandidate

method = CtpManagedSingleWorkerCandidate.stage_prepared_dispatch
signature = str(inspect.signature(method))
result = {"signature": signature, "kwargs": ["cancel_target_projection", "action_identity"]}
try:
    method(None, object(), action_identity=object())
except TypeError as error:
    result["action_identity_call"] = "REJECTED"
    result["error"] = str(error)
else:
    raise SystemExit("unexpectedly accepted action_identity")
for module in ("bt_api_ctp", "bt_api_py", "ctp", "ctypes"):
    result[module + "_loaded"] = module in sys.modules
if any(result[module + "_loaded"] for module in ("bt_api_ctp", "bt_api_py", "ctp", "ctypes")):
    raise SystemExit("unexpected native/provider module loaded")
print(json.dumps(result, sort_keys=True))
