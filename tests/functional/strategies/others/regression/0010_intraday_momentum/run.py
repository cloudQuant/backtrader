from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
import _local_runner


TEST_DIR = Path(__file__).resolve().parent
RESULT_FILE = TEST_DIR / "backtest_result.json"


def _find_backtrader_repo() -> Path:
    for parent in TEST_DIR.parents:
        if (parent / "backtrader").is_dir() and (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Cannot find backtrader repo root")


def _find_back_trader_root(repo_root: Path) -> Path:
    sibling = repo_root.parent / "back_trader"
    if sibling.is_dir():
        return sibling
    fallback = Path(os.environ.get("BACK_TRADER_ROOT", ""))
    if fallback.is_dir():
        return fallback
    raise RuntimeError("Cannot find back_trader root")


def _find_source_strategy_dir(repo_root: Path, back_trader_root: Path) -> Path:
    rel = TEST_DIR.relative_to(repo_root / "tests" / "functional" / "strategies_regression")
    return back_trader_root / "strategies" / rel


def main() -> None:
    repo_root = _find_backtrader_repo()
    back_trader_root = _find_back_trader_root(repo_root)
    source_dir = _find_source_strategy_dir(repo_root, back_trader_root)
    source_run = source_dir / "run.py"
    source_result = source_dir / "backtest_result.json"
    if not source_run.exists():
        raise FileNotFoundError(f"Missing source run.py: {source_run}")

    env = os.environ.copy()
    pythonpath = [str(repo_root), str(back_trader_root), env.get("PYTHONPATH", "")]
    env["PYTHONPATH"] = os.pathsep.join(item for item in pythonpath if item)

    subprocess.run([sys.executable, str(source_run)], cwd=source_dir, env=env, check=True)
    if not source_result.exists():
        raise FileNotFoundError(f"Source strategy did not write result: {source_result}")
    shutil.copyfile(source_result, RESULT_FILE)


if __name__ == "__main__":
    _local_runner.main()
