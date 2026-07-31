from __future__ import annotations

from pathlib import Path

from backtrader_skills.acceptance import (
    REPAIR_PROFILES,
    _data_profile_gate,
    _register_acceptance_profiles,
    _write_structured_failure,
)
from backtrader_skills.data import ADAPTERS, DataRegistry
from backtrader_skills.drafts import DraftManager
from backtrader_skills.ir import ARCHETYPES, default_strategy_spec
from backtrader_skills.repair import preview_spec_repair
from backtrader_skills.runtime import RuntimePaths

from .helpers import isolated_target


def test_acceptance_profiles_cover_distinct_data_semantics(tmp_path: Path) -> None:
    target = isolated_target(tmp_path)
    data_root = tmp_path / "acceptance-data"
    data_root.mkdir()
    registry = DataRegistry(RuntimePaths(target))
    registry.add_root(data_root, root_id="acceptance")

    profiles = _register_acceptance_profiles(registry, data_root)
    gate = _data_profile_gate(profiles)

    assert set(profiles) == set(ARCHETYPES)
    assert gate["passed"] is True
    assert set(gate["observed_adapters"]) == ADAPTERS
    assert len(gate["dataset_ids"]) == len(ARCHETYPES)

    multi_asset = profiles["multi_asset_allocation"]["evidence"]["feeds"]
    assert len(multi_asset) == 2
    assert len({feed["normalized_sha256"] for feed in multi_asset}) == 2

    pairs = profiles["pairs_spread"]["evidence"]["feeds"]
    assert len(pairs) == 2
    assert len({feed["normalized_sha256"] for feed in pairs}) == 2

    timeframe = profiles["multi_timeframe"]["evidence"]["feeds"]
    assert {feed["modal_interval_seconds"] for feed in timeframe} == {60}
    assert timeframe[1]["resample"] == {"timeframe": "minutes", "compression": 5}

    ml = profiles["precomputed_ml"]
    assert ml["evidence"]["feeds"][0]["custom_lines"] == ["signal"]
    preview = registry.preview(ml["manifest"]["dataset_id"], rows=5)
    assert "signal" in preview["feeds"][0]["sample"][0]


def test_acceptance_repair_starts_from_structured_failure_and_revalidates(
    tmp_path: Path,
) -> None:
    target = isolated_target(tmp_path)
    data_root = tmp_path / "acceptance-data"
    data_root.mkdir()
    paths = RuntimePaths(target)
    registry = DataRegistry(paths)
    registry.add_root(data_root, root_id="acceptance")
    profiles = _register_acceptance_profiles(registry, data_root)

    archetype = "multi_timeframe"
    output_profile = REPAIR_PROFILES[archetype]
    dataset = profiles[archetype]["manifest"]
    failure = _write_structured_failure(tmp_path / "broken.py", archetype)
    spec = default_strategy_spec(
        archetype,
        output_profile,
        dataset["dataset_id"],
        feed_count=len(dataset["feeds"]),
    )

    repair = preview_spec_repair(paths, spec, failure)
    validation = DraftManager(paths).validate(repair["new_draft"]["draft_id"])

    assert failure["status"] == "failed"
    assert "BT_LOOKAHEAD_POSITIVE_INDEX" in {item["code"] for item in failure["diagnostics"]}
    assert repair["method"] == "typed-ir-revision-and-rerender"
    assert repair["source_validation_hash"] == failure["validation_hash"]
    assert validation["validation_report"]["status"] == "passed"
    assert validation["approval_token"] is not None
