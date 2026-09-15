"""Tests for the runnable CTP certification suites."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
CTP_ROOT = REPO_ROOT / "examples" / "007_ctp"
HONGYUAN_SUITE = CTP_ROOT / "live_certification" / "hongyuan_penetration"

CERTIFICATION_RUNNERS = (
    CTP_ROOT / "live_certification" / "simnow_penetration" / "run_case.py",
    HONGYUAN_SUITE / "run_case.py",
)


@pytest.mark.parametrize("runner_path", CERTIFICATION_RUNNERS)
def test_certification_suite_lists_all_cases_offline(runner_path):
    """Each suite exposes its 33 cases through the offline ``--list`` entry point."""
    completed = subprocess.run(
        [sys.executable, str(runner_path), "--list"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Available cases:" in completed.stdout
    assert completed.stdout.count(" -> ") == 33


@pytest.mark.parametrize(
    "report_path",
    (
        CTP_ROOT / "live_certification" / "simnow_penetration" / "reports" / "latest" / "summary.json",
        CTP_ROOT / "live_certification" / "hongyuan_penetration" / "reports" / "latest" / "summary.json",
    ),
)
def test_live_certification_reports_are_ignored(report_path):
    """Generated certification evidence must not dirty the dev worktree."""
    completed = subprocess.run(
        ["git", "check-ignore", "--quiet", str(report_path.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT,
        check=False,
    )

    assert completed.returncode == 0


def test_hongyuan_report_generator_derives_paths_from_its_suite():
    """The report generator must follow the moved 007_ctp suite directory."""
    report_script = HONGYUAN_SUITE / "fill_docx_report.py"
    spec = importlib.util.spec_from_file_location("hongyuan_fill_docx_report", report_script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.OUTPUT.parent == HONGYUAN_SUITE
    assert module.RESULTS_ROOT == HONGYUAN_SUITE / "reports" / "latest"
