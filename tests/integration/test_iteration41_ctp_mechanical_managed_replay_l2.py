"""L2 acceptance for the isolated P1-B mechanical fake-provider runtime.

The subprocess starts with public ``bt-runtime bootstrap`` and ``run`` calls.
It exercises the existing MechanicalCycle through real Cerebro/Broker/Store
objects and local SDK journals, while a socket guard proves that the fixture
never reaches CTP, SimNow, or any other network destination.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


from tests.test_utils.iteration41_source_roots import (
    iteration41_child_pythonpath,
    iteration41_source_paths,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _require_sdk_sources() -> tuple[str, ...]:
    return iteration41_source_paths("parent", "base", "execution", "risk", "monitor")


def test_cli_runs_registered_p1b_mechanical_l2_through_fake_provider_only() -> None:
    _sdk_sources = _require_sdk_sources()
    script = textwrap.dedent(
        """
        import io
        import json
        import socket
        import sys
        import tempfile
        from pathlib import Path

        connection_attempts = []
        original_socket = socket.socket

        class DeniedSocket(original_socket):
            def connect(self, *args, **kwargs):
                connection_attempts.append((args, kwargs))
                raise AssertionError("P1-B managed replay must never open a socket")

            def connect_ex(self, *args, **kwargs):
                connection_attempts.append((args, kwargs))
                raise AssertionError("P1-B managed replay must never open a socket")

        socket.socket = DeniedSocket

        from backtrader_runtime.cli import main
        from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES
        from backtrader_runtime.registry import RegisteredRuntime, RuntimeRegistry

        strategy_id = "example.ctp_options_simnow.mechanical_managed_replay_l2"
        runtime_id = "example.ctp_options_simnow.mechanical_managed_replay_l2"
        runner_module = "examples.ctp_options_simnow_managed_replay_runtime"

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            managed_dir = root / "managed"
            ordinary_dir = root / "ordinary"
            managed_dir.mkdir()
            ordinary_dir.mkdir()
            registry = RuntimeRegistry((
                RegisteredRuntime(
                    runtime_dir=managed_dir,
                    runtime_id=runtime_id,
                    strategy_id=strategy_id,
                    allowed_presets=("replay",),
                    available_capabilities=MANAGED_WRITE_CAPABILITIES,
                    offline_managed_execution=True,
                    runner_module=runner_module,
                ),
                RegisteredRuntime(
                    runtime_dir=ordinary_dir,
                    runtime_id="fixture.iteration41.p1b-ordinary-replay",
                    strategy_id=strategy_id,
                    allowed_presets=("replay",),
                    runner_module=runner_module,
                ),
            ))

            # An ordinary replay cannot import the framework or optional SDK
            # route just by pointing at this code-owned runner module.
            assert main(
                ["bootstrap", "--strategy-dir", str(ordinary_dir)],
                registry=registry,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            ) == 0
            ordinary_stderr = io.StringIO()
            assert main(
                ["run", "--strategy-dir", str(ordinary_dir)],
                registry=registry,
                stdout=io.StringIO(),
                stderr=ordinary_stderr,
            ) == 2
            assert json.loads(ordinary_stderr.getvalue())["reason"] == (
                "offline_managed_registration_required"
            )
            assert "backtrader" not in sys.modules
            assert "bt_api_py.runtime_plugins" not in sys.modules

            bootstrap_stdout = io.StringIO()
            assert main(
                ["bootstrap", "--strategy-dir", str(managed_dir)],
                registry=registry,
                stdout=bootstrap_stdout,
                stderr=io.StringIO(),
            ) == 0
            bootstrap = json.loads(bootstrap_stdout.getvalue())
            assert bootstrap["mode"] == "simulation"
            assert bootstrap["preset"] == "replay"
            assert (managed_dir / "config.yaml").is_file()

            run_stdout = io.StringIO()
            run_stderr = io.StringIO()
            assert main(
                ["run", "--strategy-dir", str(managed_dir), "--full-report"],
                registry=registry,
                stdout=run_stdout,
                stderr=run_stderr,
            ) == 0, run_stderr.getvalue()
            payload = json.loads(run_stdout.getvalue())
            report = payload["report"]["result"]
            assert payload["runner_dispatch"] == "code_owned"
            assert payload["order_route"] == "managed_execution"
            assert payload["account_access"] == "fake_provider"
            assert payload["required_capabilities"] == ["execution", "risk", "monitor"]
            assert report["status"] == "LOCAL_CTP_MECHANICAL_MANAGED_FAKE_PROVIDER_L2_PASS"
            assert report["admission_status"] == "NOT_CTP_OR_SIMNOW_ADMITTED"
            assert report["provider_submissions"] == 9
            assert report["provider_cancellations"] == 1
            assert report["monitor_events"] >= 9
            assert report["metadata_bound_child_intents"] == 6
            assert len(report["fake_instrument_metadata_digests"]) == 3
            assert all(
                len(digest) == 64
                for digest in report["fake_instrument_metadata_digests"].values()
            )
            assert report["external_network_requests"] == 0
            assert report["external_write_requests"] == 0
            assert report["actual_fills"] == 0
            assert report["synthetic_callback_fills"] == 6
            assert report["sdk_confirmed_fills"] == 0
            assert report["runtime_config"]["evidence_boundary"] == (
                "FAKE_PROVIDER_L2_ONLY_NOT_CTP_SIMNOW_OR_REAL_TRADING_EVIDENCE"
            )

            cancel_stage = report["stages"]["cancel_and_separate_clean_cycle"]
            cancelled = cancel_stage["cancel_requires_recovery"]
            recovered = cancel_stage["separate_clean_cycle_compensation"]
            assert cancelled["state"] == "RECOVERY_REQUIRED"
            assert "CANCEL_REQUESTED" in cancelled["journal_statuses"]
            assert recovered["state"] == "CLOSED_FLAT"
            assert recovered["journal_statuses"].count("ORDER_SUBMITTED") == 6
            assert recovered["journal_statuses"].count("NATIVE_FILL_CONFIRMED") == 6
            assert len(set(recovered["child_intent_hashes"])) == 6
            children = cancel_stage["separate_clean_cycle_children"]
            assert [child["instrument"] for child in children] == [
                "DCE.M2401",
                "DCE.M2401-C-2500",
                "DCE.M2401-P-2500",
                "DCE.M2401",
                "DCE.M2401-C-2500",
                "DCE.M2401-P-2500",
            ]
            assert [child["offset"] for child in children] == ["open"] * 3 + ["close"] * 3
            assert all(child["metadata_bound"] is True for child in children)
            assert len({child["intent_id"] for child in children}) == 6
            assert report["stages"]["provider_rejected"]["rejected"]["state"] == "RECOVERY_REQUIRED"
            assert report["stages"]["unknown"]["unknown"]["state"] == "RECOVERY_REQUIRED"
            restart_block = report["stages"]["blocked_after_restart"]
            assert restart_block["blocked_after_restart"]["state"] == "RECOVERY_REQUIRED"
            assert restart_block["framework_status"] == "rejected"
            assert restart_block["managed_rejection"] == "managed_execution_blocked"
            assert restart_block["provider_dispatch_prevented"] is True
            assert restart_block["managed_block_reason"] == "admission_gate_error"
            assert restart_block["blocked_dispatch_attempts"] == 0
            assert restart_block["unknown_dispatch_attempts"] == 1
            assert restart_block["unknown_still_requires_review"] is True
            assert restart_block["durable_unknown_freeze"] == (
                "dispatch-inflight:p1b.unknown.entry:open:0"
            )

            # The P1-B label names its source mechanics only.  This local L2
            # fixture must not load a CTP adapter/session as an import side
            # effect of composing the generic execution/risk/monitor stack.
            assert not any(
                module_name == "bt_api_ctp" or module_name.startswith("bt_api_ctp.")
                for module_name in sys.modules
            )

        assert connection_attempts == []
        print(json.dumps({"provider_submissions": 9, "network_attempts": 0}))
        """
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = iteration41_child_pythonpath(_sdk_sources)
    environment["BT_API_PY_LIGHT_IMPORT"] = "1"

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"provider_submissions": 9, "network_attempts": 0}
