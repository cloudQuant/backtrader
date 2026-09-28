"""Offline smoke selection must not read private or shadow runtime configs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.ci import smoke_iteration41_registered_offline as smoke


def test_offline_smoke_skips_registered_private_read_and_shadow_before_config_load(
    monkeypatch, capsys
):
    registry = smoke.iteration41_runtime_registry()
    private_registration = smoke.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION
    private_007_registration = smoke.ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION
    shadow_registration = smoke.ITERATION41_010_OKX_SHADOW_REGISTRATION

    loaded = []
    dispatched = []

    def fake_load_runtime_config(runtime_dir, *, registry):
        runtime_path = Path(runtime_dir)
        loaded.append(runtime_path)
        registration = registry.require_runtime_dir(runtime_path)
        preset = registration.allowed_presets[0]
        mode = "backtest" if preset == "local_backtest" else "simulation"
        return SimpleNamespace(mode=mode, preset=preset, secrets_ref="none")

    def fake_run(command, **kwargs):
        dispatched.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(smoke, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.setattr(smoke, "load_runtime_config", fake_load_runtime_config)
    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    assert smoke.main() == 0

    eligible = tuple(
        registration
        for registration in registry.registrations
        if registration.allowed_presets in (("replay",), ("local_backtest",))
    )
    eligible_paths = {registration.runtime_dir for registration in eligible}
    assert set(loaded) == eligible_paths
    assert private_registration.runtime_dir not in loaded
    assert private_007_registration.runtime_dir not in loaded
    assert shadow_registration.runtime_dir not in loaded
    assert len(dispatched) == len(eligible)
    report = capsys.readouterr().out
    assert "{0}: SKIP_PRIVATE_READ_ONLY".format(private_registration.runtime_id) in report
    assert "{0}: SKIP_PRIVATE_READ_ONLY".format(private_007_registration.runtime_id) in report
    assert "{0}: SKIP_SHADOW".format(shadow_registration.runtime_id) in report
    assert "offline smoke: 14 passed, 0 failed, 14 selected, 3 skipped" in report
