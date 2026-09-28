from __future__ import annotations

import builtins
import importlib.util
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

from backtrader_runtime.errors import RuntimeConfigError

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
SDK_PREFIXES = ("bt_api_py", "bt_api_ctp", "bt_api_execution", "thosttrader", "thostmduserapi", "ctpbee", "ctp_api", "_ctp", "vnpy_ctp")
blocked_imports = []
network_calls = []
original_import = builtins.__import__
original_socket = socket.socket
original_create_connection = socket.create_connection

def guarded_import(name, *args, **kwargs):
    if any(name == prefix or name.startswith(prefix + ".") for prefix in SDK_PREFIXES):
        blocked_imports.append(name)
        raise AssertionError("provider/native SDK import blocked")
    return original_import(name, *args, **kwargs)

def deny_network(name):
    def deny(*_args, **_kwargs):
        network_calls.append(name)
        raise AssertionError("network operation blocked")
    return deny

def load_support(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

class FakeTimer:
    calls = []
    def __init__(self, interval, target):
        self.calls.append(("construct", interval, target))
    def start(self):
        self.calls.append(("start",))
    def cancel(self):
        self.calls.append(("cancel",))

class FakeCerebro:
    def __init__(self):
        self.run_calls = 0
        self.runstop_calls = 0
    def run(self):
        self.run_calls += 1
        return ["fake-result"]
    def runstop(self):
        self.runstop_calls += 1

builtins.__import__ = guarded_import
try:
    pre = load_support("_independent_007_pre", ROOT / "scan-pre" / "examples" / "007_ctp" / "ctp_example_support.py")
    post = load_support("_independent_007_post", ROOT / "examples" / "007_ctp" / "ctp_example_support.py")
    socket.socket = deny_network("socket.socket")
    socket.create_connection = deny_network("socket.create_connection")
    assert hasattr(post, "threading")
    assert hasattr(post, "run_cerebro_with_timeout")

    pre.threading = SimpleNamespace(Timer=FakeTimer)
    FakeTimer.calls.clear()
    pre_cerebro = FakeCerebro()
    assert pre.run_cerebro_with_timeout(pre_cerebro, timeout_seconds=0.01) == ["fake-result"]
    assert pre_cerebro.run_calls == 1
    assert pre_cerebro.runstop_calls == 0
    assert [call[0] for call in FakeTimer.calls] == ["construct", "start", "cancel"]
    pre_timer_count = len(FakeTimer.calls)

    post.threading = SimpleNamespace(Timer=FakeTimer)
    FakeTimer.calls.clear()
    post_cerebro = FakeCerebro()
    try:
        post.run_cerebro_with_timeout(post_cerebro, timeout_seconds=object())
    except RuntimeConfigError as exc:
        assert exc.reason == "legacy_direct_execution_not_supported"
    else:
        raise AssertionError("candidate did not fail closed")
    assert post_cerebro.run_calls == 0
    assert post_cerebro.runstop_calls == 0
    assert FakeTimer.calls == []
    assert blocked_imports == []
    assert network_calls == []
    assert "bt_api_py" not in sys.modules
finally:
    builtins.__import__ = original_import
    socket.socket = original_socket
    socket.create_connection = original_create_connection

print({"pre_run": pre_cerebro.run_calls, "pre_runstop": pre_cerebro.runstop_calls, "pre_timer_calls": pre_timer_count})
print({"post_run": post_cerebro.run_calls, "post_runstop": post_cerebro.runstop_calls, "post_timer_calls": len(FakeTimer.calls), "sdk_imports": blocked_imports, "network_calls": network_calls, "bt_api_py_loaded": "bt_api_py" in sys.modules, "module_exports": [hasattr(post, name) for name in ("threading", "run_cerebro_with_timeout")]})
