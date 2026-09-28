from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(r"D:\source_code\backtrader")
ROOT = Path(r"D:\temp\ac41-63-007-run-timeout-failclose-candidate-2026-09-28")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from backtrader_runtime.legacy import legacy_direct_execution_error  # noqa: F401

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
        return ["fake-strategy-result"]
    def runstop(self):
        self.runstop_calls += 1


def load_support(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.threading = SimpleNamespace(Timer=FakeTimer)
    return module

# Import only the retained support module; do not import a provider or SDK.
pre = load_support("_007_support_preimage", ROOT / "preimage" / "ctp_example_support.py")
post = load_support("_007_support_postimage", ROOT / "postimage" / "ctp_example_support.py")
assert "bt_api_py" not in sys.modules

network_attempts = []
def deny_network(*_args, **_kwargs):
    network_attempts.append("socket")
    raise AssertionError("network is forbidden in this fake-only probe")

original_socket = socket.socket
original_create_connection = socket.create_connection
socket.socket = deny_network
socket.create_connection = deny_network
try:
    # Frozen preimage demonstrates that the helper calls a supplied Cerebro.run()
    # and constructs/starts/cancels its timer; all collaborators are fake.
    FakeTimer.calls.clear()
    pre_cerebro = FakeCerebro()
    pre_result = pre.run_cerebro_with_timeout(pre_cerebro, timeout_seconds=0.01)
    pre_timer_calls = [call[0] for call in FakeTimer.calls]
    assert pre_result == ["fake-strategy-result"]
    assert pre_cerebro.run_calls == 1
    assert pre_cerebro.runstop_calls == 0
    assert pre_timer_calls == ["construct", "start", "cancel"]

    # Candidate must reject before creating a timer or touching Cerebro.run.
    FakeTimer.calls.clear()
    post_cerebro = FakeCerebro()
    try:
        post.run_cerebro_with_timeout(post_cerebro, timeout_seconds=0.01)
    except Exception as exc:
        from backtrader_runtime.errors import RuntimeConfigError, PRESET_POLICY_VIOLATION
        assert isinstance(exc, RuntimeConfigError), type(exc).__name__
        assert exc.code == PRESET_POLICY_VIOLATION
        assert exc.reason == "legacy_direct_execution_not_supported"
    else:
        raise AssertionError("candidate helper did not fail closed")
    assert post_cerebro.run_calls == 0
    assert post_cerebro.runstop_calls == 0
    assert FakeTimer.calls == []
finally:
    socket.socket = original_socket
    socket.create_connection = original_create_connection

assert network_attempts == []
assert "bt_api_py" not in sys.modules
print({
    "preimage_result": pre_result,
    "preimage_run_calls": pre_cerebro.run_calls,
    "preimage_timer_calls": pre_timer_calls,
    "candidate_error": "legacy_direct_execution_not_supported",
    "candidate_run_calls": post_cerebro.run_calls,
    "candidate_timer_calls": len(FakeTimer.calls),
    "sdk_imported": "bt_api_py" in sys.modules,
    "network_attempts": network_attempts,
})