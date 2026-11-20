"""Keep long-running GitHub Actions jobs bounded at the job level."""

from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "test.yml"


def test_matrix_coverage_and_wheel_jobs_have_one_hour_timeouts():
    workflow = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    required_timeouts = {
        "test": 60,
        "coverage": 60,
        "wheel-consumer": 60,
    }
    actual_timeouts = {
        name: jobs[name].get("timeout-minutes") for name in required_timeouts
    }

    assert actual_timeouts == required_timeouts
