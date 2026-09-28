from __future__ import annotations

import builtins
import importlib.abc
import io
import os
from pathlib import Path
import socket
import sys
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

repo = Path(r"D:\source_code\backtrader")
out = Path(r"D:\temp\ac41-63-writer-partition4-candidate-r2-20260927")
test_path = out / "replay-overlay" / "tests" / "unit" / "test_ctp_pair_examples.py"
blocked = []
network = []
env_reads = []

class BlockForbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "dotenv" or fullname.startswith(("bt_api_py", "bt_api_ctp", "bt_api_execution")):
            blocked.append(fullname)
            raise ImportError("blocked by isolated r2 replay QA")
        return None

sys.meta_path.insert(0, BlockForbidden())

def deny_network(*args, **kwargs):
    network.append((args, kwargs))
    raise AssertionError("network blocked during isolated replay regression")

socket.getaddrinfo = deny_network
socket.create_connection = deny_network
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.socket.sendto = deny_network

original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == "bt_api_py" or name.startswith(("bt_api_py.", "bt_api_ctp.", "bt_api_execution.")):
        blocked.append(name)
        raise AssertionError("SDK import blocked during isolated replay regression")
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import

def is_env_path(file):
    try:
        return Path(os.fsdecode(os.fspath(file))).name.casefold() == ".env"
    except (TypeError, ValueError, OSError):
        return False

original_open = builtins.open
original_io_open = io.open
original_os_open = os.open
def guarded_open(original, label):
    def call(file, *args, **kwargs):
        if is_env_path(file):
            env_reads.append((label, os.fsdecode(os.fspath(file))))
            raise AssertionError(".env read blocked during isolated replay regression")
        return original(file, *args, **kwargs)
    return call
builtins.open = guarded_open(original_open, "builtins.open")
io.open = guarded_open(original_io_open, "io.open")
os.open = guarded_open(original_os_open, "os.open")
os.environ["TRADE_LOGGER_CONSOLE"] = "0"
sys.path.insert(0, str(repo))

stdout = StringIO()
stderr = StringIO()
with redirect_stdout(stdout), redirect_stderr(stderr):
    import pytest
    exit_code = int(pytest.main(["-q", str(test_path), "-p", "no:cacheprovider"]))

result = {
    "command": f"python {out / 'run_partition4_r2_replay_regressions.py'}",
    "test_path": str(test_path),
    "pytest_exit_code": exit_code,
    "stdout": stdout.getvalue(),
    "stderr": stderr.getvalue(),
    "blocked_optional_import_attempts": blocked,
    "network_attempts": len(network),
    "env_file_read_attempts": env_reads,
    "main_tree_modified": False,
}
result_path = out / "replay-regression-result.json"
result_path.write_text(__import__("json").dumps(result, indent=2) + "\n", encoding="utf-8")
print(result["stdout"])
if result["stderr"]:
    print(result["stderr"], file=sys.stderr)
print(f"SDK/dotenv attempts={len(blocked)} network attempts={len(network)} .env reads={len(env_reads)}")
print(f"result={result_path}")
raise SystemExit(exit_code if not blocked and not network and not env_reads else 1)
