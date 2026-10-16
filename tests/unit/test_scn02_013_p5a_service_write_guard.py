from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest


_RUNNERS = (
    "examples.unified.013_1_midfreq_cross_arbitrage.run",
    "examples.unified.013_2_highfreq_calendar_arbitrage.run",
    "examples.unified.013_3_sa_midfreq_simnow.run",
)


@pytest.mark.parametrize("module_name", _RUNNERS)
def test_p5a_service_write_request_is_refused_before_config_or_provider_io(
    module_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    """The service reader cannot become the P5A writer by adding a CLI grant."""

    runner = importlib.import_module(module_name)
    attempted: list[str] = []

    def forbidden(label: str):
        def record(*_args: Any, **_kwargs: Any) -> None:
            attempted.append(label)

        return record

    # The public main() guard is required to reject before reading case
    # configuration, preparing SDK imports, or dispatching either live handler.
    for name in (
        "_load_config",
        "_ensure_dev_sdk_path",
        "_load_env",
        "run_live",
        "run_live_observe",
    ):
        if hasattr(runner, name):
            monkeypatch.setattr(runner, name, forbidden(name))

    missing_config = tmp_path / "must-not-be-read.json"
    result = runner.main(
        [
            "--live",
            "--backend",
            "service",
            "--allow-write",
            "--service-config",
            str(missing_config),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert result == runner.EXIT_BLOCKED
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "service_write_backend_unsupported"
    assert payload["write_grant_result"] == "rejected_before_provider_io"
    assert attempted == []
    assert not missing_config.exists()
    assert captured.err == ""

