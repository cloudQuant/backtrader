import ast
from pathlib import Path
p3 = Path(r"D:\temp\ac41-63-store-api-identity-r2-p3-independent-qa-20260927\receipt-r2-final\run_guarded_main_broad.py")
tree = ast.parse(p3.read_text(encoding="utf-8"))
blocked = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "blocked" for t in n.targets))
blocked.extend([
    "tests/unit/stores/test_btapistore_iteration22.py::test_native_ctp_wrapper_rejects_market_before_req_order_insert",
    "tests/unit/stores/test_btapistore_iteration22.py::test_native_ctp_wrapper_defaults_to_read_only_and_rejects_implicit_settlement_write",
])
root = Path(r"D:\source_code\backtrader")
assert len(blocked) == 18 and len(set(blocked)) == 18
for node in blocked:
    file_part, test_part = node.split("::", 1)
    function_name = test_part.split("[", 1)[0]
    source = root / file_part
    mod = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
    fn = next(n for n in mod.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function_name)
    sdk_call = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "optional_sdk" and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "bt_api_ctp.ctp.client" for n in ast.walk(fn))
    print(("OK " if sdk_call else "MISSING ") + node)
    if not sdk_call:
        raise SystemExit(1)
