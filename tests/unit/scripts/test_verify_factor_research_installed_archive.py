"""Git-archive source selection for installed factor verification."""

import importlib.util
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_factor_research_installed.py"
SPEC = importlib.util.spec_from_file_location("verify_factor_research_installed", SCRIPT)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_archive_paths_follow_historical_and_current_runtime_package_layouts(tmp_path):
    repo = tmp_path / "backtrader"
    repo.mkdir()
    _git(repo, "init")

    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Archive Fixture"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "archive-fixture@example.invalid"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    (repo / "setup.py").write_text("# synthetic package source\n", encoding="utf-8")
    runtime_root = repo / "backtrader_runtime"
    runtime_root.mkdir()
    (runtime_root / "legacy.py").write_text("# historical runtime payload\n", encoding="utf-8")
    historical_commit = _commit(repo, "historical runtime package")

    historical_paths = VERIFIER._archive_paths_for_commit(
        repo, historical_commit, "backtrader", factor_mode_pair=True
    )
    assert historical_paths == VERIFIER._archive_paths("backtrader", factor_mode_pair=True)
    assert "backtrader_runtime" in historical_paths

    (runtime_root / "legacy.py").unlink()
    runtime_root.rmdir()
    current_commit = _commit(repo, "retire runtime package")
    current_paths = VERIFIER._archive_paths_for_commit(
        repo, current_commit, "backtrader", factor_mode_pair=True
    )
    expected_current_paths = tuple(
        path
        for path in VERIFIER._archive_paths("backtrader", factor_mode_pair=True)
        if path != "backtrader_runtime"
    )

    assert current_paths == expected_current_paths
    assert set(VERIFIER._FACTOR_MODE_PAIR_ARCHIVE_PATHS).issubset(current_paths)
    assert "backtrader_runtime/" in VERIFIER._PACKAGE_ROOTS
