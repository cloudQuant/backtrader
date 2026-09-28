"""End-to-end acceptance for the separately registered offline managed L2 path.

The subprocess enters through the public ``bt-runtime`` CLI function after
bootstrap.  It combines local SDK source packages only after the managed
replay registration resolves, then verifies the real Cerebro/Broker/Store
route against an in-process fake provider.  No live, SimNow, credential, or
network route is present in this fixture.
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


def test_cli_bootstrap_runs_the_registered_managed_fake_provider_l2_and_stays_offline() -> None:
    _sdk_sources = _require_sdk_sources()
    script = textwrap.dedent(
        """
        import io
        import json
        import socket
        import tempfile
        from pathlib import Path

        connection_attempts = []
        original_socket = socket.socket

        class DeniedSocket(original_socket):
            def connect(self, *args, **kwargs):
                connection_attempts.append((args, kwargs))
                raise AssertionError("managed replay L2 must never open a socket")

            def connect_ex(self, *args, **kwargs):
                connection_attempts.append((args, kwargs))
                raise AssertionError("managed replay L2 must never open a socket")

        socket.socket = DeniedSocket

        from backtrader_runtime import RegisteredRuntime, RuntimeRegistry
        from backtrader_runtime.cli import main
        from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES

        strategy_id = "example.013_3.sa_midfreq_simnow"
        runner_module = "examples.013_3_sa_midfreq_simnow.run_managed_replay_runtime"

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            managed_dir = root / "managed"
            normal_dir = root / "normal"
            missing_dir = root / "missing"
            # Bootstrap may create only the mandatory config inside an exact
            # reviewed runtime directory.  It must not create arbitrary
            # runtime directories selected by a caller.
            managed_dir.mkdir()
            normal_dir.mkdir()
            missing_dir.mkdir()
            registry = RuntimeRegistry((
                RegisteredRuntime(
                    runtime_dir=managed_dir,
                    runtime_id="fixture.iteration41.managed-replay",
                    strategy_id=strategy_id,
                    allowed_presets=("replay",),
                    available_capabilities=MANAGED_WRITE_CAPABILITIES,
                    offline_managed_execution=True,
                    runner_module=runner_module,
                ),
                RegisteredRuntime(
                    runtime_dir=normal_dir,
                    runtime_id="fixture.iteration41.normal-replay",
                    strategy_id=strategy_id,
                    allowed_presets=("replay",),
                    runner_module=runner_module,
                ),
                RegisteredRuntime(
                    runtime_dir=missing_dir,
                    runtime_id="fixture.iteration41.missing-managed-replay",
                    strategy_id=strategy_id,
                    allowed_presets=("replay",),
                    available_capabilities=MANAGED_WRITE_CAPABILITIES,
                    offline_managed_execution=True,
                    runner_module=runner_module,
                ),
            ))

            bootstrap_stdout = io.StringIO()
            assert main(
                ["bootstrap", "--strategy-dir", str(managed_dir)],
                registry=registry,
                stdout=bootstrap_stdout,
                stderr=io.StringIO(),
            ) == 0
            bootstrap = json.loads(bootstrap_stdout.getvalue())
            assert bootstrap["preset"] == "replay"
            assert bootstrap["mode"] == "simulation"
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
            assert report["status"] == "LOCAL_MANAGED_FAKE_PROVIDER_L2_PASS"
            assert report["provider_submissions"] == 4
            assert report["provider_cancellations"] == 1
            assert report["monitor_events"] >= 4
            assert len(report["fake_instrument_metadata_digest"]) == 64
            assert report["stages"]["restart_recovery"]["order"] == "Accepted"
            assert report["stages"]["unknown"]["order"] == "Accepted"
            assert report["stages"]["blocked_after_restart"]["order"] == "Rejected"
            assert report["external_network_requests"] == 0
            assert report["external_write_requests"] == 0

            # The ordinary 013_3 replay has no reviewed managed flag.  Even
            # if a code-owned runner module is pointed at this fixture, it
            # rejects before optional capability composition or bridge bind.
            assert main(
                ["bootstrap", "--strategy-dir", str(normal_dir)],
                registry=registry,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            ) == 0
            ordinary_stderr = io.StringIO()
            assert main(
                ["run", "--strategy-dir", str(normal_dir)],
                registry=registry,
                stdout=io.StringIO(),
                stderr=ordinary_stderr,
            ) == 2
            assert (
                json.loads(ordinary_stderr.getvalue())["reason"]
                == "offline_managed_registration_required"
            )

            # A registered directory still needs config.yaml; the runner and
            # optional SDK packages are never reached for this failure.
            missing_stderr = io.StringIO()
            assert main(
                ["run", "--strategy-dir", str(missing_dir)],
                registry=registry,
                stdout=io.StringIO(),
                stderr=missing_stderr,
            ) == 2
            assert json.loads(missing_stderr.getvalue())["reason"] == "missing_config"

        assert connection_attempts == []
        print(json.dumps({"provider_submissions": 4, "network_attempts": 0}))
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
    assert json.loads(completed.stdout) == {"provider_submissions": 4, "network_attempts": 0}
