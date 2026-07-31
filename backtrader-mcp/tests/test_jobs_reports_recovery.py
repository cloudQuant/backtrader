from __future__ import annotations

import time

import pytest

from backtrader_mcp.contracts import ARCHETYPES
from backtrader_mcp.service import BacktraderMCPService
from backtrader_mcp.util import utc_now

from conftest import canonical_spec


def _wait(service, job_id: str, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.get_run_status(job_id)
        if status["state"] in {
            "CANCELLED",
            "SUCCEEDED",
            "FAILED",
            "TIMED_OUT",
            "ORPHANED",
        }:
            return status
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not become terminal")


@pytest.mark.parametrize("archetype", sorted(ARCHETYPES))
@pytest.mark.parametrize("profile", ["python_bundle", "single_test"])
def test_distinct_run_approval_fixed_profile_and_report(
    registered_dataset,
    archetype: str,
    profile: str,
):
    service, dataset = registered_dataset
    spec = canonical_spec(dataset["dataset_id"], archetype, profile)
    validated_spec = service.validate_strategy_spec(spec)
    assert validated_spec["status"] == "passed"
    draft = service.create_strategy_draft(spec)
    validation = service.validate_strategy_draft(draft["draft_id"], draft["revision"])
    plan = service.prepare_strategy_run(
        draft["draft_id"],
        validation["validation_token"],
        dataset["dataset_id"],
        "default",
        20,
        "fixed_tests",
        f"prepare-{archetype}-{profile}",
    )
    approval = service.jobs.approve_run_plan(plan["run_plan_id"], plan["run_token"])
    started = service.start_strategy_run(
        plan["run_plan_id"],
        plan["run_token"],
        approval["approval_id"],
        f"start-{archetype}-{profile}",
    )
    status = _wait(service, started["job_id"])
    assert status["state"] == "SUCCEEDED", status.get("error")
    result = service.get_run_result(started["job_id"])
    assert result["schema_version"] == "run-result-v1"
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
    parity = result["extensions"]["runonce_runnext_comparison"]
    assert parity["status"] == "matched", parity
    rendered = service.render_strategy_report(started["job_id"])
    assert "Canonical metrics" in rendered["content"]
    comparison = service.compare_strategy_runs(started["job_id"], started["job_id"])
    assert comparison["status"] == "matched"


def test_cancel_and_restart_recovery(service_env):
    service, _, _ = service_env
    queued = {
        "job_id": "job_" + "1" * 32,
        "state": "QUEUED",
        "worker_pid": None,
        "child_pid": None,
        "created_at": utc_now(),
    }
    service.state.put("job", queued["job_id"], queued)
    cancelled = service.cancel_strategy_run(queued["job_id"], "cancel-1")
    assert cancelled["state"] == "CANCELLED"
    orphan = {
        "job_id": "job_" + "2" * 32,
        "state": "RUNNING",
        "worker_pid": 99999999,
        "child_pid": None,
        "created_at": utc_now(),
    }
    service.state.put("job", orphan["job_id"], orphan)
    recovered = BacktraderMCPService(service.settings)
    assert orphan["job_id"] in recovered.recovery["jobs"]
    assert recovered.get_run_status(orphan["job_id"])["state"] == "ORPHANED"
