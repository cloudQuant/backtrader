from __future__ import annotations
import ast
import importlib.util
import os
import sys
from pathlib import Path
import pytest

if __name__ == "__main__":
    if "sitecustomize" not in sys.modules or not hasattr(sys.modules["sitecustomize"], "ProviderImportBlocker"):
        raise SystemExit("guard missing")
    origin = Path(importlib.util.find_spec("bt_api_py").origin).resolve()
    expected = Path(r"D:\bt_api_py\bt_api_py\__init__.py").resolve()
    if origin != expected:
        raise SystemExit(f"bt_api_py source origin changed: {origin}")
    source = Path(r"D:\temp\ac41-63-store-api-identity-r2-p3-independent-qa-20260927\receipt-r2-final\run_guarded_main_broad.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    blocked = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "blocked" for t in node.targets):
            blocked = ast.literal_eval(node.value)
            break
    if blocked is not None:
        blocked.extend([
            "tests/unit/stores/test_btapistore_iteration22.py::test_native_ctp_wrapper_rejects_market_before_req_order_insert",
            "tests/unit/stores/test_btapistore_iteration22.py::test_native_ctp_wrapper_defaults_to_read_only_and_rejects_implicit_settlement_write",
        ])
    if blocked is None or len(blocked) != 18:
        raise SystemExit("exact CTP-import deselection list unavailable")
    repo = Path(r"D:\source_code\backtrader")
    args = ["-p", "no:asyncio", "-p", "no:cacheprovider", "-q", "--tb=short"]
    for nodeid in blocked:
        args.extend(["--deselect", nodeid])
    args.extend([
        "--junitxml", os.environ["ITER41_JUNIT"],
        str(repo / "tests/unit/stores"),
        str(repo / "tests/test_ctp_generic_sdk_queue_failclose.py"),
        str(repo / "tests/unit/stores/test_btapistore_api_route_identity.py"),
    ])
    print("CTP_IMPORT_NODE_DESELECTIONS=18", flush=True)
    print("BT_API_PY_ORIGIN=" + str(origin), flush=True)
    raise SystemExit(pytest.main(args))


