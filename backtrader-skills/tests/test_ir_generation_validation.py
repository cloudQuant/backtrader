from __future__ import annotations

from pathlib import Path

from backtrader_skills.canonical import canonical_hash
from backtrader_skills.generation import render_strategy
from backtrader_skills.ir import (
    ARCHETYPES,
    OUTPUT_PROFILES,
    default_strategy_spec,
    validate_strategy_spec,
)
from backtrader_skills.validation import validate_python

DATASET_ID = "ds_" + "a" * 64


def test_seven_archetypes_two_profiles_share_typed_ir() -> None:
    for archetype in ARCHETYPES:
        rendered = {}
        ir_hashes = {}
        for profile in OUTPUT_PROFILES:
            feed_count = 2 if archetype in {"multi_asset_allocation", "pairs_spread"} else 1
            spec = default_strategy_spec(archetype, profile, DATASET_ID, feed_count=feed_count)
            ir_hashes[profile] = canonical_hash(spec["ir"])
            rendered[profile] = render_strategy(spec)
            assert rendered[profile].files
            source = next(
                file.content.decode()
                for file in rendered[profile].files
                if file.relative_path.endswith(".py")
            )
            assert "class GeneratedStrategy(bt.Strategy):" in source
            assert "super().__init__()" not in source
        assert ir_hashes["single_test"] == ir_hashes["python_bundle"]


def test_common_input_aliases_export_only_canonical_fields() -> None:
    base = default_strategy_spec("single_data_indicator", "single_test", DATASET_ID)
    aliased = {
        **base,
        "version": base["spec_version"],
        "strategy_name": base["name"],
        "strategy_slug": base["slug"],
        "archetype_id": "single_data",
        "output": "test",
        "dataset": {"id": DATASET_ID},
        "data_feeds": base["feeds"],
        "params": base["parameters"],
    }
    for field in (
        "spec_version",
        "name",
        "slug",
        "archetype",
        "output_profile",
        "dataset_id",
        "feeds",
        "parameters",
        "spec_hash",
    ):
        aliased.pop(field, None)
    canonical = validate_strategy_spec(aliased)
    assert canonical["spec_version"] == "strategy-spec-v1"
    assert canonical["archetype"] == "single_data_indicator"
    assert canonical["output_profile"] == "single_test"
    assert canonical["dataset_id"] == DATASET_ID
    assert (
        not {
            "version",
            "strategy_name",
            "strategy_slug",
            "archetype_id",
            "output",
            "dataset",
            "data_feeds",
            "params",
        }
        & canonical.keys()
    )


def _validate_source(tmp_path: Path, source: str, *, generated_only: bool = False) -> dict:
    path = tmp_path / "candidate.py"
    path.write_text(source, encoding="utf-8")
    return validate_python(path, generated_only=generated_only)


def test_validator_classifies_fork_initialization_contracts(tmp_path) -> None:
    direct = _validate_source(
        tmp_path,
        "import backtrader as bt\nclass S(bt.Strategy):\n"
        "    def __init__(self):\n        self.value = 1\n",
    )
    assert direct["status"] == "passed"
    redundant = _validate_source(
        tmp_path,
        "import backtrader as bt\nclass S(bt.Strategy):\n"
        "    def __init__(self):\n        super().__init__()\n",
    )
    assert any(
        item["code"] == "BT_DIRECT_STRATEGY_SUPER_REDUNDANT" for item in redundant["diagnostics"]
    )
    custom_parent = _validate_source(
        tmp_path,
        "class Parent:\n    pass\nclass S(Parent):\n"
        "    def __init__(self):\n        self.p.value = 1\n",
    )
    assert any(
        item["code"] == "BT_COOPERATIVE_INIT_REQUIRED" for item in custom_parent["diagnostics"]
    )
    indicator = _validate_source(
        tmp_path,
        "import backtrader as bt\nclass I(bt.Indicator):\n"
        "    def __init__(self):\n        self.lines.out = self.data\n",
    )
    assert any(item["code"] == "BT_COOPERATIVE_INIT_REQUIRED" for item in indicator["diagnostics"])


def test_validator_rejects_dynamic_execution_and_lookahead(tmp_path) -> None:
    report = _validate_source(
        tmp_path,
        "import backtrader as bt\nclass S(bt.Strategy):\n"
        "    def next(self):\n        eval('1')\n        print(self.data.close[1])\n",
    )
    codes = {item["code"] for item in report["diagnostics"]}
    assert {"SEC_DYNAMIC_EXECUTION", "BT_LOOKAHEAD_POSITIVE_INDEX"} <= codes


def test_validator_rejects_controller_import_and_filesystem_access(tmp_path) -> None:
    controller_escape = _validate_source(
        tmp_path,
        "import backtrader as bt\n"
        "from backtrader_skills.runner import subprocess\n"
        "class S(bt.Strategy):\n"
        "    backtrader_skills_generated = True\n"
        "    def next(self):\n"
        "        subprocess.run(['echo', 'unsafe'])\n",
        generated_only=True,
    )
    filesystem_escape = _validate_source(
        tmp_path,
        "import backtrader as bt\n"
        "from pathlib import Path\n"
        "class S(bt.Strategy):\n"
        "    backtrader_skills_generated = True\n"
        "    def next(self):\n"
        "        Path('/etc/passwd').read_text()\n",
        generated_only=True,
    )
    network_escape = _validate_source(
        tmp_path,
        "import backtrader as bt\n"
        "import socket\n"
        "class S(bt.Strategy):\n"
        "    backtrader_skills_generated = True\n"
        "    def next(self):\n"
        "        socket.create_connection(('example.com', 80))\n",
        generated_only=True,
    )
    assert controller_escape["status"] == "failed"
    assert filesystem_escape["status"] == "failed"
    assert network_escape["status"] == "failed"
    assert any(
        item["code"] == "SEC_IMPORT_NOT_ALLOWLISTED" for item in controller_escape["diagnostics"]
    )
    assert any(
        item["code"] == "SEC_IMPORT_NOT_ALLOWLISTED" for item in filesystem_escape["diagnostics"]
    )
    assert any(item["code"] == "SEC_FORBIDDEN_IMPORT" for item in network_escape["diagnostics"])
