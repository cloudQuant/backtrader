import json, os, sys
from pathlib import Path

if len(sys.argv) < 3:
    raise SystemExit("usage: guarded_pytest.py <environment-json> <junit-xml> <pytest paths...>")
metadata_path = Path(sys.argv[1]).resolve()
junit_path = Path(sys.argv[2]).resolve()
pytest_paths = sys.argv[3:]
root = Path.cwd().resolve()

blocked_root = os.path.normcase(os.path.abspath(r"D:\bt_api_py"))
def is_blocked_path(value):
    try:
        candidate = os.path.normcase(os.path.abspath(value or os.getcwd()))
        return candidate == blocked_root or candidate.startswith(blocked_root + os.sep)
    except (TypeError, OSError):
        return False

before_path = list(sys.path)
removed = [entry for entry in before_path if is_blocked_path(entry)]
sys.path[:] = [entry for entry in before_path if not is_blocked_path(entry)]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
for name in ("BT_API_TEST_SOURCE_ROOTS", "PYTEST_PLUGINS"):
    os.environ.pop(name, None)

import pytest

args = ["-q", "-ra", "--tb=short", "-p", "no:asyncio", f"--junitxml={junit_path}", *pytest_paths]
exit_code = int(pytest.main(args))
loaded_sdk = sorted(name for name in sys.modules if name == "bt_api_py" or name.startswith("bt_api_py.") or name == "_ctp" or name.startswith("_ctp."))
try:
    bt_file = str(Path(sys.modules["backtrader"].__file__).resolve()) if "backtrader" in sys.modules else None
except Exception as exc:
    bt_file = f"<path-error:{type(exc).__name__}>"
meta = {
    "cwd": str(root), "executable": sys.executable, "pytest_file": str(Path(pytest.__file__).resolve()),
    "pytest_args": args, "exit_code": exit_code, "sys_path_before_cleanup": before_path,
    "sdk_paths_removed": removed, "sys_path_after_tests": list(sys.path),
    "bt_api_py_or__ctp_loaded_modules": loaded_sdk, "backtrader_file": bt_file,
    "guard_log": os.environ.get("I41_SDK_IMPORT_GUARD_LOG"),
}
metadata_path.parent.mkdir(parents=True, exist_ok=True)
metadata_path.write_text(json.dumps(meta, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print("I41_GUARD_RESULT=" + json.dumps({"loaded_sdk_modules": loaded_sdk, "backtrader_file": bt_file, "exit_code": exit_code, "sys_path_after_tests": list(sys.path)}, ensure_ascii=True, sort_keys=True))
if loaded_sdk:
    print("ERROR: a prohibited SDK module appeared in sys.modules")
    raise SystemExit(98)
if any(is_blocked_path(p) for p in sys.path):
    print("ERROR: prohibited D:\\bt_api_py path appeared on sys.path")
    raise SystemExit(99)
raise SystemExit(exit_code)