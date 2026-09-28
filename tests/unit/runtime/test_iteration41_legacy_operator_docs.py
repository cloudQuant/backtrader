"""Keep old live-example operator instructions aligned with the v4 CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from backtrader_runtime.cli import build_parser


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("example", ("007_ctp", "010_live_examples"))
def test_legacy_example_docs_use_bootstrap_and_offline_doctor(example: str) -> None:
    readme = (REPOSITORY_ROOT / "examples" / example / "README.md").read_text(
        encoding="utf-8"
    )
    runtime_dir = "examples/{0}/runtime".format(example)
    commands = (
        "bt-runtime bootstrap --strategy-dir " + runtime_dir,
        "bt-runtime doctor --strategy-dir " + runtime_dir,
        "bt-runtime run --strategy-dir " + runtime_dir,
    )

    assert readme.index(commands[0]) < readme.index(commands[2])
    assert "is for review and is not a manual setup step" in readme
    assert "doctor` performs no provider or network I/O" in readme
    assert "Copy the reviewed `runtime/config.example.yaml`" not in readme

    parser = build_parser()
    for command in commands:
        arguments = parser.parse_args(command.split()[1:])
        assert arguments.strategy_dir == Path(runtime_dir)
