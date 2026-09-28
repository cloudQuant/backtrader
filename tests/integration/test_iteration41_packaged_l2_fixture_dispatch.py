"""Exercise the exact packaged Iteration 41 fake-provider L2 registrations.

This is deliberately a local source-SDK test.  It proves that the Backtrader
package-owned fixture registry, immutable package ``config.yaml`` files, and
trusted private runner loader can dispatch the two offline fake-provider
routes.  It does not prove an external capability wheelhouse or an isolated
consumer release: the SDK capability packages still come from an explicitly
provided local source checkout.
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


def test_packaged_l2_fixtures_dispatch_through_the_fixed_private_loader() -> None:
    """Both package-owned registrations stay offline and avoid source wrappers."""

    _sdk_sources = _require_sdk_sources()
    script = textwrap.dedent(
        """
        import io
        import json
        import socket
        import sys

        attempts = []
        original_socket = socket.socket

        class DeniedSocket(original_socket):
            def connect(self, *args, **kwargs):
                attempts.append((args, kwargs))
                raise AssertionError("packaged L2 fixture must not open a socket")

            def connect_ex(self, *args, **kwargs):
                attempts.append((args, kwargs))
                raise AssertionError("packaged L2 fixture must not open a socket")

        socket.socket = DeniedSocket

        from backtrader_runtime.cli import main
        from backtrader_runtime.inventory import iteration41_l2_fixture_registry

        registry = iteration41_l2_fixture_registry()
        reports = {}
        for registration in registry.registrations:
            stdout, stderr = io.StringIO(), io.StringIO()
            assert main(
                ["run", "--strategy-dir", str(registration.runtime_dir), "--full-report"],
                registry=registry,
                stdout=stdout,
                stderr=stderr,
            ) == 0, stderr.getvalue()
            payload = json.loads(stdout.getvalue())
            report = payload["report"]["result"]
            assert payload["runner_dispatch"] == "code_owned"
            assert payload["order_route"] == "managed_execution"
            assert payload["account_access"] == "fake_provider"
            assert report["external_network_requests"] == 0
            assert report["external_write_requests"] == 0
            reports[registration.runtime_id] = report["status"]

        assert not any(
            name == "examples.013_3_sa_midfreq_simnow.run_managed_replay_runtime"
            or name == "examples.ctp_options_simnow_managed_replay_runtime"
            for name in sys.modules
        )
        assert attempts == []
        print(json.dumps(reports, sort_keys=True))
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
    assert json.loads(completed.stdout) == {
        "example.013_3.sa_midfreq_simnow.managed_replay_l2": "LOCAL_MANAGED_FAKE_PROVIDER_L2_PASS",
        "example.ctp_options_simnow.mechanical_managed_replay_l2": (
            "LOCAL_CTP_MECHANICAL_MANAGED_FAKE_PROVIDER_L2_PASS"
        ),
    }
