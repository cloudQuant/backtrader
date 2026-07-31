from __future__ import annotations

import json
import jsonschema

from backtrader_skills.drafts import DraftManager
from backtrader_skills.ir import default_strategy_spec
from backtrader_skills.runner import ControlledRunner
from backtrader_skills.runtime import RuntimePaths
from backtrader_skills.resources import resource_path

from .helpers import isolated_target, register_dataset


def test_fixed_child_runner_dual_mode_and_eleven_metrics(tmp_path) -> None:
    target = isolated_target(tmp_path)
    data_root = tmp_path / "data"
    data_root.mkdir()
    dataset = register_dataset(target, data_root)
    spec = default_strategy_spec("single_data_indicator", "python_bundle", dataset["dataset_id"])
    drafts = DraftManager(RuntimePaths(target))
    draft = drafts.preview(spec)
    validated = drafts.validate(draft["draft_id"])
    write_token = validated["approval_token"]
    drafts.tokens.approve(write_token["token_id"])
    applied = drafts.apply(draft["draft_id"], write_token["token_id"])
    candidate = next(
        target / item["path"] for item in applied["files"] if item["path"].endswith("strategy.py")
    )
    runner = ControlledRunner(RuntimePaths(target))
    prepared = runner.prepare(candidate, dataset["dataset_id"], timeout_seconds=120)
    run_manifest_schema = json.loads(
        resource_path("contracts", "run-manifest-v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(prepared["run_manifest"], run_manifest_schema)
    run_token = prepared["approval_token"]
    runner.tokens.approve(run_token["token_id"])
    result = runner.execute(prepared["run_manifest"]["run_id"], run_token["token_id"])
    assert result["status"] == "passed"
    assert result["comparison"]["metrics"]["passed"]
    assert result["comparison"]["events"]["passed"]
    assert len(result["metrics"]) == 11
    run_result_schema = json.loads(
        resource_path("contracts", "run-result-v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(result, run_result_schema)
    assert set(result["metrics"]) == {
        "bar_num",
        "buy_count",
        "sell_count",
        "win_count",
        "loss_count",
        "trade_num",
        "final_value",
        "sharpe_ratio",
        "annual_return",
        "max_drawdown",
        "return_rate",
    }
    run_dir = RuntimePaths(target).runs / result["run_id"]
    assert (run_dir / "run-result.json").is_file()
    assert (run_dir / "report.md").is_file()
