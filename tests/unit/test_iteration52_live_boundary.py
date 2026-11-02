"""Live-boundary contract for the iteration-52 provider example (52-F06/F20).

The example ships a production-bound template whose references, credentials
and write capability are disjoint from the Demo paper template.  Running it
must stop at authorization / credential resolution, before any provider
transport or write.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "unified" / "052_provider_demo_roundtrip"
PAPER_CONFIG = EXAMPLE / "config.yaml"
LIVE_CONFIG = EXAMPLE / "config.live.yaml"

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11), reason="iteration-52 live entries require Python 3.11"
)


def _config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _run(*args: str, env_file: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "run.py", "--config", "config.live.yaml", *args, "--env-file", str(env_file)],
        cwd=str(EXAMPLE),
        capture_output=True,
        text=True,
        timeout=180,
    )


def _payload(result: subprocess.CompletedProcess) -> dict:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, result.stderr
    return json.loads(lines[-1])


def test_live_template_is_disjoint_from_the_paper_template():
    paper = _config(PAPER_CONFIG)
    live = _config(LIVE_CONFIG)
    assert (paper["mode"], paper["environment"]) == ("paper", "paper")
    assert (live["mode"], live["environment"]) == ("live", "live")
    for field in ("provider", "endpoint", "account", "credential", "scope"):
        assert paper["references"][field] != live["references"][field]
    assert "orders.paper.write" in paper["requested_capabilities"]
    assert "orders.live.write" in live["requested_capabilities"]
    assert (
        live["strategy_parameters"]["credential_public_key_env"]
        != paper["strategy_parameters"]["credential_public_key_env"]
    )
    assert (
        live["strategy_parameters"]["credential_private_key_env"]
        != paper["strategy_parameters"]["credential_private_key_env"]
    )
