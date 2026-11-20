"""Keep the PR fast gate small without dropping full CI coverage."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "test.yml"


def _workflow():
    return yaml.load(_WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _event_matrix_values(expression):
    match = re.fullmatch(
        r"\$\{\{\s*fromJSON\(github\.event_name == 'pull_request' && "
        r"'(.+?)' \|\| '(.+?)'\)\s*\}\}",
        expression,
    )
    assert match is not None
    return json.loads(match.group(1)), json.loads(match.group(2))


def _run_text(job):
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def test_pr_matrix_is_one_ubuntu_python_311_cell_and_other_events_keep_all_18():
    workflow = _workflow()
    matrix = workflow["jobs"]["test"]["strategy"]["matrix"]

    pr_os, other_os = _event_matrix_values(matrix["os"])
    pr_python, other_python = _event_matrix_values(matrix["python-version"])

    assert pr_os == ["ubuntu-latest"]
    assert pr_python == ["3.11"]
    assert other_os == ["ubuntu-latest", "macos-latest", "windows-latest"]
    assert other_python == ["3.8", "3.9", "3.10", "3.11", "3.12", "3.13"]
    assert len(other_os) * len(other_python) == 18
    assert set(workflow["on"]) >= {"push", "pull_request", "schedule", "workflow_dispatch"}

    commands = _run_text(workflow["jobs"]["test"])
    assert 'pytest tests/ -m "not slow and not performance"' in commands
    assert 'pytest tests/ -m "not performance"' in commands


def test_required_summaries_and_sdk_wheel_security_gates_are_preserved():
    workflow = _workflow()
    jobs = workflow["jobs"]

    assert jobs["test-summary"]["name"] == "Test Summary"
    assert jobs["test-summary"]["needs"] == [
        "test",
        "cpython38-core-compatibility",
        "sdk",
        "performance",
        "wheel-consumer",
    ]
    assert "coverage" not in jobs["test-summary"]["needs"]
    assert jobs["tiered-validation-summary"]["name"] == "Tiered Validation"
    assert "[ \"$TARGET_RESULT\" = 'skipped' ]" in _run_text(
        jobs["tiered-validation-summary"]
    )

    assert "if" not in jobs["sdk"]
    assert "requirements-ci-sdk.txt" in _run_text(jobs["sdk"])
    assert "python -m pytest tests -m 'not performance'" in _run_text(jobs["sdk"])
    assert "if" not in jobs["wheel-consumer"]
    assert "verify_release_wheel.py" in _run_text(jobs["wheel-consumer"])
    assert "bandit -r backtrader -ll -q" in _run_text(jobs["lint"])

    for branch in ("dev", "development", "master"):
        ruleset = json.loads(
            (_REPO_ROOT / ".github" / "governance" / "rulesets" / f"{branch}.json")
            .read_text(encoding="utf-8")
        )
        checks = next(
            rule["parameters"]["required_status_checks"]
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        assert {check["context"] for check in checks} >= {
            "Lint",
            "Test Summary",
            "PR Governance",
            "Tiered Validation",
        }


def test_performance_marked_tests_only_run_in_the_serial_performance_job():
    workflow = _workflow()
    jobs = workflow["jobs"]

    for job_name in ("test", "sdk", "coverage"):
        assert "not performance" in _run_text(jobs[job_name])

    strategy_job = jobs["branch-specific-validation"]
    strategy_step = next(
        step
        for step in strategy_job["steps"]
        if step.get("name") == "Run development R2/R3 strategy regression gate"
    )
    assert strategy_step["env"]["PYTEST_ADDOPTS"] == "-m not performance"
    assert 'pytest tests/ -m "not performance" -n auto' in _run_text(strategy_job)

    coverage = jobs["coverage"]
    assert coverage["if"] == (
        "github.event_name == 'schedule' || "
        "github.event_name == 'workflow_dispatch'"
    )
    assert "coverage" not in jobs["test-summary"]["needs"]

    performance_job = jobs["performance"]
    assert "make test-performance BT_CONDA_PYTHON=python" in _run_text(performance_job)
    makefile = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "pytest tests -m performance --timeout=$(BT_TEST_TIMEOUT) -n 0 -q" in makefile
