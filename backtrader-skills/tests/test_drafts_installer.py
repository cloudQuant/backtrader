from __future__ import annotations

import pytest
import json
import jsonschema

from backtrader_skills.drafts import DraftManager
from backtrader_skills.errors import ApprovalError, ConflictError, IntegrityError
from backtrader_skills.installer import HOST_PATHS, SKILL_NAMES, SkillInstaller
from backtrader_skills.ir import default_strategy_spec
from backtrader_skills.repair import preview_spec_repair
from backtrader_skills.runtime import RuntimePaths
from backtrader_skills.resources import resource_path

from .helpers import isolated_target, register_dataset


def test_draft_requires_separate_approval_and_applies_exact_bytes(tmp_path) -> None:
    target = isolated_target(tmp_path)
    data_root = tmp_path / "data"
    data_root.mkdir()
    dataset = register_dataset(target, data_root)
    spec = default_strategy_spec("single_data_indicator", "python_bundle", dataset["dataset_id"])
    manager = DraftManager(RuntimePaths(target))
    draft = manager.preview(spec)
    validation = manager.validate(draft["draft_id"])
    token = validation["approval_token"]
    assert validation["validation_report"]["status"] == "passed"
    artifact_schema = json.loads(
        resource_path("contracts", "strategy-artifact-manifest-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validation_schema = json.loads(
        resource_path("contracts", "validation-report-v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(draft, artifact_schema)
    jsonschema.validate(validation["validation_report"], validation_schema)
    with pytest.raises(ApprovalError):
        manager.apply(draft["draft_id"], token["token_id"])
    manager.tokens.approve(token["token_id"])
    result = manager.apply(draft["draft_id"], token["token_id"])
    assert len(result["files"]) == 3
    assert all((target / item["path"]).is_file() for item in result["files"])


def test_multi_file_apply_rolls_back_when_second_target_write_fails(tmp_path, monkeypatch) -> None:
    target = isolated_target(tmp_path)
    manager = DraftManager(RuntimePaths(target))
    spec = default_strategy_spec("single_data_indicator", "python_bundle", "ds_" + "a" * 64)
    draft = manager.preview(spec)
    validation = manager.validate(draft["draft_id"])
    token = validation["approval_token"]
    manager.tokens.approve(token["token_id"])
    original = manager._commit_target
    calls = 0

    def fail_second(path, content):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second-file failure")
        original(path, content)

    monkeypatch.setattr(manager, "_commit_target", fail_second)
    with pytest.raises(IntegrityError, match="rolled back"):
        manager.apply(draft["draft_id"], token["token_id"])
    assert calls == 2
    assert all(not (target / entry["path"]).exists() for entry in draft["files"])
    journal = next(
        (target / ".backtrader-skills" / "drafts" / draft["draft_id"] / "transactions").glob(
            "*/journal.json"
        )
    )
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "rolled_back"


def test_repair_revises_typed_ir_and_creates_new_hash_bound_draft(tmp_path) -> None:
    target = isolated_target(tmp_path)
    data_root = tmp_path / "data"
    data_root.mkdir()
    dataset = register_dataset(target, data_root)
    revised = default_strategy_spec("order_risk", "single_test", dataset["dataset_id"])
    evidence = {
        "schema_version": "validation-report-v1",
        "validation_hash": "f" * 64,
        "diagnostics": [
            {
                "code": "BT_LOOKAHEAD_POSITIVE_INDEX",
                "severity": "error",
            }
        ],
    }
    repair = preview_spec_repair(RuntimePaths(target), revised, evidence)
    assert repair["method"] == "typed-ir-revision-and-rerender"
    assert repair["handled_codes"] == ["BT_LOOKAHEAD_POSITIVE_INDEX"]
    assert repair["new_draft"]["spec_hash"] == revised["spec_hash"]


@pytest.mark.parametrize("host", sorted(HOST_PATHS))
def test_four_host_install_and_manifest_uninstall(tmp_path, host) -> None:
    target = isolated_target(tmp_path)
    installer = SkillInstaller(RuntimePaths(target))
    preview = installer.preview_install(host)
    token = preview["approval_token"]
    installer.tokens.approve(token["token_id"])
    installed = installer.apply_install(preview["plan"]["plan_id"], token["token_id"])
    for skill in SKILL_NAMES:
        assert (target / HOST_PATHS[host] / skill / "SKILL.md").is_file()
    with pytest.raises(ConflictError):
        second = installer.preview_install(host)
        installer.tokens.approve(second["approval_token"]["token_id"])
        installer.apply_install(second["plan"]["plan_id"], second["approval_token"]["token_id"])
    modified = target / installed["files"][0]["path"]
    modified.write_text(modified.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")
    uninstall = installer.preview_uninstall(host)
    uninstall_token = uninstall["approval_token"]
    installer.tokens.approve(uninstall_token["token_id"])
    result = installer.apply_uninstall(uninstall["plan"]["plan_id"], uninstall_token["token_id"])
    assert installed["files"][0]["path"] in result["preserved_modified"]
    assert modified.is_file()
