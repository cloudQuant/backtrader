"""A synthetic live registration cannot dispatch on confirmation alone."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from backtrader_runtime.cli import main
from backtrader_runtime.config import load_runtime_config
from backtrader_runtime.errors import RuntimeConfigError
from backtrader_runtime.policy import CAPABILITY_EXECUTION, CAPABILITY_MONITOR, CAPABILITY_RISK
from backtrader_runtime.registry import RegisteredRuntime, RuntimeRegistry, resolve_runtime_config
from backtrader_runtime.runner import dispatch_registered_runtime


def _live_registry(runtime_dir: Path) -> RuntimeRegistry:
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "config.yaml").write_text(
        """config_schema_version: 4
strategy:
  id: iteration41.ctp.live_guard
runtime:
  mode: live
  preset: managed_live_direct
parameters: {}
secrets_ref: runtime_secrets
""",
        encoding="utf-8",
    )
    return RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                runtime_id="iteration41.ctp.live-guard",
                strategy_id="iteration41.ctp.live_guard",
                allowed_presets=("managed_live_direct",),
                allowed_secrets_refs=("runtime_secrets",),
                available_capabilities=(
                    CAPABILITY_EXECUTION,
                    CAPABILITY_RISK,
                    CAPABILITY_MONITOR,
                ),
                approval_receipt_digest="a" * 64,
                runner_module="iteration41_fake_live_runner",
            ),
        ),
        registry_id="test.live-dispatch-guard",
    )


def test_synthetic_live_registration_and_confirmation_cannot_import_a_runner(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "live"
    registry = _live_registry(runtime_dir)
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )

    with pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(effective, registry)
    assert caught.value.reason == "live_execution_admission_required"

    stdout, stderr = io.StringIO(), io.StringIO()
    status = main(
        ["run", "--strategy-dir", str(runtime_dir), "--confirm-live"],
        registry=registry,
        stdout=stdout,
        stderr=stderr,
    )
    assert status == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["reason"] == "live_execution_admission_required"
