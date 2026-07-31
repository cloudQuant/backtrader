from pathlib import Path

import pytest

from backtrader_agent.catalog import SnapshotCatalog
from backtrader_agent.contracts import StrategySpec
from backtrader_agent.scaffold import ARCHETYPES, PROFILES, ArtifactRenderer
from backtrader_agent.validator import StrategyValidator

from helpers import strategy_spec


def test_all_fourteen_scaffolds_render_and_validate_without_requiring_direct_strategy_super(
    tmp_path: Path,
) -> None:
    renderer = ArtifactRenderer(tmp_path / "state")
    validator = StrategyValidator()
    dataset = {
        "dataset_id": "ds_" + "a" * 64,
        "manifest_hash": "a" * 64,
        "feeds": [
            {"name": "primary", "role": "execution", "columns": {"signal": "signal"}},
            {"name": "secondary", "role": "signal", "columns": {}},
        ],
    }

    for archetype in ARCHETYPES:
        for profile in PROFILES:
            spec = StrategySpec.from_dict(
                strategy_spec("ds_" + "a" * 64, archetype=archetype, profile=profile)
            )
            artifact = renderer.render("session-1", spec, dataset)
            report = validator.validate_artifact(artifact)
            assert report["status"] == "passed", (archetype, profile, report["diagnostics"])
            strategy_file = next(item for item in artifact["files"] if item["role"] == "strategy")
            source = (Path(artifact["_draft_path"]) / strategy_file["path"]).read_text(
                encoding="utf-8"
            )
            assert "class GeneratedStrategy(bt.Strategy)" in source
            assert "super().__init__()" not in source


def test_validator_rejects_dynamic_execution_but_accepts_legacy_style_strategy() -> None:
    validator = StrategyValidator()
    legacy = """
import backtrader as bt
class LegacyStrategy(bt.Strategy):
    params = (("period", 5),)
    def __init__(self):
        self.sma = bt.ind.SMA(self.data.close, period=self.p.period)
"""
    assert validator.validate_source(legacy, "strategy.py") == []

    dangerous = legacy + "\neval('1 + 1')\n"
    diagnostics = validator.validate_source(dangerous, "strategy.py")
    assert any(item["code"] == "BTAG-SEC-DYNAMIC" for item in diagnostics)


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ("import os\nos.execlp('/bin/sh', 'sh')", "BTAG-SEC-CAPABILITY"),
        ("from os import execlp\nexeclp('/bin/sh', 'sh')", "BTAG-SEC-FROM-IMPORT"),
        ("from pathlib import Path\nPath('x').read_text()", "BTAG-SEC-IMPORT"),
        ("open('secret.txt').read()", "BTAG-SEC-FILESYSTEM"),
        ("reader = open\nreader('secret.txt')", "BTAG-SEC-FILESYSTEM"),
        ("getattr(object(), '__class__')", "BTAG-SEC-REFLECTION"),
        ("import socket\nsocket.socket()", "BTAG-SEC-IMPORT"),
        (
            "from strategy_helper import os\nos.execlp('/bin/sh', 'sh')",
            "BTAG-SEC-LOCAL-IMPORT",
        ),
        ("import backtrader_agent\nbacktrader_agent.cli.main()", "BTAG-SEC-IMPORT"),
        ("import backtrader as bt\nbt.os.system('id')", "BTAG-SEC-CAPABILITY"),
        (
            "import os\nvalue = os.environ.get('HOME')",
            "BTAG-SEC-ENVIRONMENT",
        ),
    ],
)
def test_validator_denies_real_capability_escape_vectors(payload: str, expected_code: str) -> None:
    source = (
        "import backtrader as bt\n"
        "class EscapeStrategy(bt.Strategy):\n"
        "    def next(self):\n"
        "        pass\n"
        f"{payload}\n"
    )
    diagnostics = StrategyValidator().validate_source(source, "strategy_escape.py")
    assert any(item["code"] == expected_code for item in diagnostics), diagnostics


def test_snapshot_search_is_deterministic_and_has_provenance() -> None:
    catalog = SnapshotCatalog()
    first = catalog.search("multi timeframe clock", top_k=3)
    second = catalog.search("multi timeframe clock", top_k=3)
    assert first == second
    assert first
    assert all(item["source_hash"] for item in first)
    inspected = catalog.inspect(first[0]["entry_id"])
    assert inspected["source_available"] is False
