from pathlib import Path

from backtrader_agent.canonical import hash_object
from backtrader_agent.cli import build_parser, dispatch
from backtrader_agent.contracts import StrategySpec
from backtrader_agent.scaffold import ArtifactRenderer
from backtrader_agent.sessions import SessionStore

from helpers import dump_json, strategy_spec


def _call(*arguments: str):
    return dispatch(build_parser().parse_args(list(arguments)))


def _metrics(final_value: float = 100000.0) -> dict:
    return {
        "bar_num": 40,
        "buy_count": 1,
        "sell_count": 1,
        "win_count": 0,
        "loss_count": 0,
        "trade_num": 0,
        "final_value": final_value,
        "sharpe_ratio": None,
        "annual_return": None,
        "max_drawdown": 0.0,
        "return_rate": 0.0,
    }


def _write_run(state: Path, run_id: str, metrics: dict) -> None:
    root = state / "runs" / run_id
    root.mkdir(parents=True)
    core = {
        "schema_version": "run-result-v1",
        "run_id": run_id,
        "status": "passed",
        "metrics": metrics,
        "diagnostics": [],
        "artifacts": [],
        "extensions": {"backtrader_agent": {"mode": "runonce"}},
    }
    dump_json(root / "run-result.json", {**core, "result_hash": hash_object(core)})
    (root / "report.md").write_text("# immutable report\n", encoding="utf-8")
    (root / "report.html").write_text("<h1>immutable report</h1>\n", encoding="utf-8")


def test_compare_and_report_use_only_private_hash_verified_run_ids(tmp_path: Path) -> None:
    state = tmp_path / "state"
    left_id = "run-" + "a" * 20
    right_id = "run-" + "b" * 20
    _write_run(state, left_id, _metrics())
    _write_run(state, right_id, _metrics())
    common = ("--state-root", str(state))

    comparison = _call(
        *common,
        "compare",
        "--left-run-id",
        left_id,
        "--right-run-id",
        right_id,
    )
    assert comparison["status"] == "passed"
    viewed = _call(*common, "report", "--run-id", left_id, "--format", "markdown")
    assert viewed["content"] == "# immutable report\n"
    assert len(viewed["sha256"]) == 64


def test_catalog_refresh_uses_read_only_registered_roots(tmp_path: Path) -> None:
    state = tmp_path / "state"
    functional = tmp_path / "functional"
    packages = tmp_path / "packages"
    (functional / "trend").mkdir(parents=True)
    (packages / "trend" / "alpha").mkdir(parents=True)
    (functional / "trend" / "test_alpha.py").write_text("class Alpha: pass\n", encoding="utf-8")
    package = packages / "trend" / "alpha"
    (package / "strategy_alpha.py").write_text("class Alpha: pass\n", encoding="utf-8")
    (package / "config.yaml").write_text("name: alpha\n", encoding="utf-8")
    (package / "run.py").write_text("print('alpha')\n", encoding="utf-8")
    common = ("--state-root", str(state))
    for root_id, path in (("functional", functional), ("packages", packages)):
        _call(
            *common,
            "roots",
            "register",
            "--id",
            root_id,
            "--path",
            str(path),
            "--kind",
            "dataset",
        )

    refreshed = _call(
        *common,
        "catalog",
        "refresh",
        "--functional-root-id",
        "functional",
        "--package-root-id",
        "packages",
        "--allow-count-drift",
    )
    assert refreshed["counts"] == {
        "functional_tests": 1,
        "strategy_packages": 1,
        "mapped": 1,
    }
    assert (state / "catalog" / "source-attached.jsonl").is_file()


def test_failed_session_repair_revises_spec_and_rerenders_owned_draft(tmp_path: Path) -> None:
    state = tmp_path / "state"
    session_id = "repair-1"
    dataset_id = "ds_" + "d" * 64
    dataset = {
        "schema_version": "dataset-manifest-v1",
        "dataset_id": dataset_id,
        "manifest_hash": "e" * 64,
    }
    original = StrategySpec.from_dict(strategy_spec(dataset_id))
    artifact = ArtifactRenderer(state).render(session_id, original, dataset)
    sessions = SessionStore(state)
    sessions.create(session_id)
    transitions = (
        ("DATA_READY", "dataset-register", {"dataset_manifest_hash": dataset["manifest_hash"]}),
        ("SPEC_DRAFT", "spec-draft", {"spec_hash": original.spec_hash}),
        ("SPEC_APPROVED", "spec-approve", {"approved_spec_hash": original.spec_hash}),
        ("SOURCES_SELECTED", "sources-select", {}),
        ("DRAFT_READY", "draft-render", {"artifact_hash": artifact["artifact_hash"]}),
        ("VALIDATED", "strategy-validate", {"validation_hash": "1" * 64}),
        ("APPLY_PREPARED", "change-prepare", {"change_manifest_hash": "2" * 64}),
        ("APPLIED", "change-apply", {"applied_artifact_hash": "3" * 64}),
        ("RUN_APPROVED", "run-approve", {"run_approval_id": "approval-test"}),
        ("RUNNING", "controlled-run-start", {"run_id": "run-" + "4" * 20}),
        ("FAILED", "controlled-run-failed", {"failed_run_id": "run-" + "4" * 20}),
    )
    for state_name, action, effects in transitions:
        sessions.transition(
            session_id,
            state_name,
            action,
            {"fixture": hash_object({"state": state_name})},
            effect_references=effects,
        )

    revised = strategy_spec(dataset_id)
    revised["parameters"]["fast_period"]["default"] = 6
    failure = {
        "schema_version": "run-result-v1",
        "run_id": "run-" + "4" * 20,
        "status": "failed",
        "diagnostics": [
            {
                "code": "BTAG-RUN-FIXTURE",
                "severity": "error",
                "message": "fixture failure",
            }
        ],
    }
    spec_path = dump_json(tmp_path / "revised-spec.json", revised)
    dataset_path = dump_json(tmp_path / "dataset.json", dataset)
    failure_path = dump_json(tmp_path / "failure.json", failure)
    result = _call(
        "--state-root",
        str(state),
        "repair",
        "--session-id",
        session_id,
        "--spec",
        str(spec_path),
        "--dataset-manifest",
        str(dataset_path),
        "--failure-report",
        str(failure_path),
    )

    assert result["repair"]["old_approvals_reusable"] is False
    assert result["repair"]["previous_spec_hash"] == original.spec_hash
    assert result["repair"]["revised_spec_hash"] != original.spec_hash
    assert sessions.load(session_id)["state"] == "DRAFT_READY"
