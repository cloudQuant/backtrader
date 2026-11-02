"""60.01-R2: per-package import location, source tree, branch/HEAD and version."""
import importlib, importlib.metadata as md, pathlib, subprocess, sys
PKGS = ["backtrader", "bt_api_py", "bt_api_base", "bt_api_ctp", "bt_api_okx", "bt_api_binance",
        "bt_api_gateway", "bt_api_transport_zmq", "bt_api_execution", "bt_api_risk",
        "bt_api_monitor", "bt_api_runtime", "msgspec", "msgpack", "zmq", "numpy", "pandas"]
DIST = {"backtrader": "back-trader-python", "bt_api_py": "bt-api-py", "zmq": "pyzmq"}
def git(path, *args):
    try:
        return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return ""
print(f"python {sys.version.split()[0]} {sys.executable}")
print("package|import|file|git_toplevel|branch|head|dist_version|requires_python")
for name in PKGS:
    try:
        mod = importlib.import_module(name)
        f = pathlib.Path(mod.__file__).resolve()
        top = git(f.parent, "rev-parse", "--show-toplevel")
        branch = git(f.parent, "branch", "--show-current") or ("detached" if top else "-")
        head = git(f.parent, "rev-parse", "--short", "HEAD") or "-"
        status = "OK"
    except Exception as exc:
        f, top, branch, head, status = "-", "-", "-", "-", type(exc).__name__
    dist = DIST.get(name, name.replace("_", "-"))
    try:
        ver = md.version(dist); req = md.metadata(dist).get("Requires-Python") or "-"
    except Exception:
        try:
            ver = md.version(name); req = md.metadata(name).get("Requires-Python") or "-"
        except Exception:
            ver, req = "-", "-"
    home = str(pathlib.Path.home())
    print("|".join(str(x).replace(home, "~") for x in (name, status, f, top or "-", branch, head, ver, req)))
