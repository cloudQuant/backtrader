import builtins
import sys
import types
import pytest

blocked_prefixes = ("bt_api_py", "bt_api_ctp", "bt_api_base", "vnpy", "ctp")
blocked_attempts = []
original_import = builtins.__import__
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked_prefixes):
        blocked_attempts.append(name)
        raise AssertionError("provider/native import blocked in QA runner")
    return original_import(name, globals, locals, fromlist, level)

# Simulate an unrelated earlier Store test having imported a provider module.
# This is inert and deliberately unavailable to attribute-level SDK use.
preloaded = types.ModuleType("bt_api_py")
preloaded.__path__ = []
sys.modules["bt_api_py"] = preloaded
builtins.__import__ = guarded_import
args = [
    "-p", "no:asyncio", "-p", "normalized_guard_plugin", "-q", "--tb=short",
    "tests/unit/runtime/test_local_fake_account_actor_candidate.py",
    "tests/unit/stores/test_btapistore_normalized.py::test_order_conversion_preserves_native_units_and_all_position_fields",
    "tests/unit/stores/test_btapistore_normalized.py::test_ctp_order_ref_session_and_front_are_preserved_for_cancel_without_exchange_id",
    "tests/unit/stores/test_btapistore_normalized.py::test_framework_retains_sdk_trade_source_state_and_canonical_fee_without_interpretation",
    "tests/unit/stores/test_btapistore_normalized.py::test_open_order_identity_supports_native_cancellation_without_local_order",
    "--basetemp", r"D:\temp\iteration41-local-actor-order-context-qa-20260927\basetemp",
    "--junitxml", r"D:\temp\iteration41-local-actor-order-context-qa-20260927\focused.junit.xml",
]
result = pytest.main(args)
builtins.__import__ = original_import
print("PRELOADED_FAKE_MODULE=bt_api_py")
print("BLOCKED_IMPORT_ATTEMPTS=" + repr(blocked_attempts))
if blocked_attempts:
    raise SystemExit(98)
raise SystemExit(result)
