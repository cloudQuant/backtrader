import json
from pathlib import Path

from backtrader_agent.canonical import hash_object
from backtrader_agent.cli import build_parser, dispatch
from backtrader_agent.contracts import StrategySpec

from helpers import data_spec, dump_json, strategy_spec, write_price_csv


def _call(*arguments: str):
    return dispatch(build_parser().parse_args(list(arguments)))


def test_cli_data_to_run_workflow_is_hash_chained_and_completes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    inputs = tmp_path / "inputs"
    workspace.mkdir()
    inputs.mkdir()
    write_price_csv(inputs / "prices.csv", rows=40)
    state = workspace / ".backtrader-agent"
    common = ("--state-root", str(state))

    _call(
        *common,
        "roots",
        "register",
        "--id",
        "workspace",
        "--path",
        str(workspace),
        "--kind",
        "workspace",
        "--writable",
    )
    _call(
        *common,
        "roots",
        "register",
        "--id",
        "input",
        "--path",
        str(inputs),
        "--kind",
        "dataset",
    )
    _call(*common, "session", "create", "--session-id", "workflow-1")

    data_spec_path = dump_json(tmp_path / "data-spec.json", data_spec())
    dataset = _call(
        *common,
        "data",
        "register",
        "--session-id",
        "workflow-1",
        "--spec",
        str(data_spec_path),
    )
    dataset_path = dump_json(tmp_path / "dataset.json", dataset)

    spec_path = dump_json(
        tmp_path / "strategy-spec.json",
        strategy_spec(dataset["dataset_id"], profile="python_bundle"),
    )
    canonical_spec = _call(
        *common,
        "spec",
        "--session-id",
        "workflow-1",
        "--approve",
        "--file",
        str(spec_path),
    )
    assert StrategySpec.from_dict(canonical_spec).spec_hash == canonical_spec["spec_hash"]
    canonical_spec_path = dump_json(tmp_path / "canonical-spec.json", canonical_spec)
    artifact = _call(
        *common,
        "draft",
        "--session-id",
        "workflow-1",
        "--spec",
        str(canonical_spec_path),
        "--dataset-manifest",
        str(dataset_path),
    )
    artifact_path = Path(artifact["_draft_path"]) / "artifact-manifest.json"
    validation = _call(
        *common,
        "validate",
        "--session-id",
        "workflow-1",
        "--artifact-manifest",
        str(artifact_path),
        "--draft-root",
        artifact["_draft_path"],
        "--dataset-hash",
        dataset["manifest_hash"],
        "--engine-hash",
        "local-engine",
        "--environment-hash",
        "test-environment",
    )
    validation_token_path = dump_json(
        tmp_path / "validation-token.json", validation["validation_token"]
    )
    files = [
        {
            "source": item["path"],
            "target": f"strategies/generated/cli/{item['path']}",
        }
        for item in artifact["files"]
    ]
    prepared = _call(
        *common,
        "changes",
        "prepare",
        "--session-id",
        "workflow-1",
        "--draft-root",
        artifact["_draft_path"],
        "--files",
        json.dumps(files),
        "--target-root-id",
        "workspace",
        "--validation-token",
        str(validation_token_path),
    )
    prepared_path = dump_json(tmp_path / "change-manifest.json", prepared)
    change_request = _call(
        *common,
        "approval",
        "request",
        "--kind",
        "change",
        "--subject-hash",
        prepared["manifest_hash"],
        "--bindings",
        json.dumps(
            {
                "artifact_hash": prepared["artifact_hash"],
                "artifact_record_hash": prepared["artifact_record_hash"],
                "change_manifest_hash": prepared["manifest_hash"],
                "dataset_hash": prepared["dataset_manifest_hash"],
                "dataset_id": prepared["dataset_id"],
                "spec_hash": prepared["spec_hash"],
                "validation_token_hash": prepared["validation_token_hash"],
                "validation_token_id": validation["validation_token"]["token_id"],
                "session_id": "workflow-1",
            }
        ),
    )
    change_grant = _call(
        *common,
        "approval",
        "grant",
        "--request-id",
        change_request["request_id"],
        "--approver",
        "local-user",
        "--confirm",
    )
    change_token_path = dump_json(tmp_path / "change-token.json", change_grant["token"])
    applied = _call(
        *common,
        "changes",
        "apply",
        "--manifest",
        str(prepared_path),
        "--change-token",
        str(change_token_path),
        "--idempotency-key",
        "workflow-apply",
    )
    applied_path = dump_json(tmp_path / "applied.json", applied)

    run_subject = _call(
        *common,
        "run-subject",
        "--applied-artifact",
        str(applied_path),
        "--dataset-manifest",
        str(dataset_path),
        "--validation-token",
        str(validation_token_path),
        "--mode",
        "runonce",
    )
    run_request = _call(
        *common,
        "approval",
        "request",
        "--kind",
        "run",
        "--subject-hash",
        run_subject["subject_hash"],
        "--bindings",
        json.dumps(
            {
                "applied_artifact_hash": applied["applied_artifact_hash"],
                "applied_record_hash": applied["applied_record_hash"],
                "artifact_hash": applied["artifact_hash"],
                "artifact_record_hash": applied["artifact_record_hash"],
                "change_manifest_hash": applied["change_manifest_hash"],
                "validation_token_id": validation["validation_token"]["token_id"],
                "validation_token_hash": hash_object(validation["validation_token"]),
                "dataset_hash": dataset["manifest_hash"],
                "dataset_id": dataset["dataset_id"],
                "mode": "runonce",
                "session_id": "workflow-1",
                "spec_hash": applied["spec_hash"],
            }
        ),
    )
    run_grant = _call(
        *common,
        "approval",
        "grant",
        "--request-id",
        run_request["request_id"],
        "--approver",
        "local-user",
        "--confirm",
    )
    run_token_path = dump_json(tmp_path / "run-token.json", run_grant["token"])
    result = _call(
        *common,
        "run",
        "--applied-artifact",
        str(applied_path),
        "--dataset-manifest",
        str(dataset_path),
        "--validation-token",
        str(validation_token_path),
        "--run-token",
        str(run_token_path),
        "--mode",
        "runonce",
        "--idempotency-key",
        "workflow-run",
        "--timeout",
        "30",
    )
    assert result["status"] == "passed"
    session = _call(*common, "session", "status", "--session-id", "workflow-1")
    assert session["state"] == "COMPLETED"
    assert session["artifacts"]["dataset_manifest_hash"] == dataset["manifest_hash"]
    assert session["artifacts"]["run_result_hash"] == result["result_hash"]
    assert session["approvals"]["apply"] == change_grant["token"]["token_id"]
    assert session["approvals"]["execute"] == run_grant["token"]["token_id"]

    journal_path = state / "sessions/workflow-1/journal.jsonl"
    events = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[-1]["to_state"] == "COMPLETED"
    assert all(
        events[index]["previous_event_hash"] == events[index - 1]["event_hash"]
        for index in range(1, len(events))
    )
