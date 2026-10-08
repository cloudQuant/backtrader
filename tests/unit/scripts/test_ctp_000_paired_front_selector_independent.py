"""Independent transport-only checks; every socket is inert or forbidden."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import ctp_000_paired_front_selector as selector
from tests.unit.scripts.test_ctp_000_paired_front_selector import document


def test_all_eight_pairs_stop_connecting_at_global_deadline():
    elapsed = [0.0]
    calls = []

    def connect(host, port, timeout):
        assert elapsed[0] < 30
        calls.append((host, port, timeout))
        elapsed[0] += timeout
        raise TimeoutError("inert failure")

    result = selector.observe_document(document(8), connector=connect, clock=lambda: elapsed[0])
    assert len(calls) == 30
    assert len(result["pairs"]) == 8
    assert result["deadline_observed_exceeded"]
    assert result["selected_config_index"] is None
    assert all(
        row["md"]["sample_count"] == row["td"]["sample_count"] == 3 for row in result["pairs"]
    )


@pytest.mark.parametrize("expire_during", ["create", "settimeout"])
def test_actual_socket_boundary_rechecks_expiry(monkeypatch, expire_during):
    probe = selector._probe_module()
    elapsed = [0.0]
    effects = []
    closed = []

    class InertSocket:
        def __init__(self, *args):
            if expire_during == "create":
                elapsed[0] = 30.0

        def settimeout(self, timeout):
            assert 0 < timeout <= 1
            if expire_during == "settimeout":
                elapsed[0] = 30.0

        def connect(self, address):
            effects.append(address)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(probe.socket, "socket", InertSocket)
    result = selector.observe_document(document(1), clock=lambda: elapsed[0])
    assert effects == []
    assert closed == [True]
    assert result["deadline_observed_exceeded"]
    assert result["selected_config_index"] is None


_ISOLATED_CLI = r"""
import json, pathlib, runpy, socket, sys
script, projection, mode = sys.argv[1:]
effects = []
violations = []
def audit(event, args):
    forbidden = event.startswith("socket.") or event == "subprocess.Popen"
    if event == "import":
        forbidden |= args[0].startswith(("bt_api", "dotenv"))
        if mode != "probe":
            forbidden |= args[0].startswith("backtrader_runtime")
    if event == "open" and isinstance(args[0], str):
        name = pathlib.Path(args[0]).name.lower()
        forbidden |= name.endswith((".yaml", ".yml")) or name.startswith(".env")
    if forbidden:
        violations.append(event)
        raise RuntimeError("forbidden offline operation")
sys.addaudithook(audit)
class InertSocket:
    def __init__(self, *args):
        assert mode == "probe"
    def settimeout(self, timeout):
        assert 0 < timeout <= 1
    def connect(self, address):
        assert address[0].startswith("192.0.2.")
        effects.append(address)
    def close(self):
        pass
socket.socket = InertSocket
sys.argv = [script, "--check" if mode == "check" else "--probe", "--pairs-json", projection]
if mode == "probe":
    sys.argv.append("--confirm-transport-only")
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as error:
    code = error.code
assert violations == [], violations
assert len(effects) == (12 if mode == "probe" else 0), len(effects)
assert not any(name.startswith("bt_api") for name in sys.modules)
sys.exit(code)
"""


@pytest.mark.parametrize("mode", ["check", "unconfirmed", "probe"])
def test_fresh_isolated_real_cli_with_inert_socket_only(tmp_path, mode):
    projection = tmp_path / "public-pairs.json"
    if mode != "unconfirmed":
        projection.write_text(json.dumps(document(2)), encoding="utf-8")
    script = Path(selector.__file__).resolve()
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", _ISOLATED_CLI, str(script), str(projection), mode],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=tmp_path,
    )
    assert completed.returncode == (2 if mode == "unconfirmed" else 0), completed.stderr
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert "192.0.2." not in completed.stdout and "tcp://" not in completed.stdout
    assert result["execution_authority"] == "NONE"
    assert result["ctp_gate_status"] == "NO_WRITE / LIVE_NO_GO"
    if mode == "unconfirmed":
        assert result["reason"] == "explicit_transport_probe_confirmation_required"
    else:
        assert result["tcp_probe_started"] is (mode == "probe")
        assert result["registered_runtime_dispatched"] is False
        assert result["provider_login_started"] is False
        assert result["trading_writes"] == 0
