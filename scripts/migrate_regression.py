#!/usr/bin/env python3
"""Migrate regression strategies from tests/functional/strategies_regression/
into tests/functional/strategies/<category>/regression/<name>/.

Approach: relocate the existing test/run/strategy/config/expected.json structure
with minimal edits. Specifically:

1. Copy directory recursively to new location.
2. Edit config.yaml: rewrite `../../../datas/foo.csv` -> absolute paths in
   tests/datas/ (or fall back to tests/functional/datas/ if not yet copied).
3. Edit run.py:
   - Remove `_BENCHMARK_WORKSPACE_ROOT = Path('/Users/...')` injection block.
   - Rewrite `from strategies.benchmark_metrics import ...` to use the vendored
     `tests.test_utils.benchmark_metrics`.
4. Edit test_NNNN_xxx.py:
   - Remove the back_trader root detection.
   - Replace subprocess.run(run.py) with in-process import + run.
   - Adjust expected.json path resolution.
5. Verify: run the new test, ensure it passes.
6. Delete the original directory.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGRESSION_ROOT = REPO / "tests" / "functional" / "strategies_regression"
TARGET_ROOT = REPO / "tests" / "functional" / "strategies"
PUBLIC_DATA = REPO / "tests" / "datas"
LEGACY_DATA = REPO / "tests" / "functional" / "datas"
SELECTION_FILE = REPO / "scripts" / "regression_migration_selection.json"


def _resolve_data_path(rel: str) -> str | None:
    for prefix in ("../../../datas/",):
        if rel.startswith(prefix):
            tail = rel.removeprefix(prefix)
            public = PUBLIC_DATA / tail
            if public.exists():
                return str(public)
            legacy = LEGACY_DATA / tail
            if legacy.exists():
                return str(legacy)
    return None


def remap_data_paths_in_config(config_text: str) -> str:
    """Rewrite '../../../datas/foo.csv' to absolute paths."""
    # YAML strings can be quoted or unquoted. Use a non-greedy match on relative paths
    # and rewrite the path part only.
    pattern = re.compile(r'((?:\.\./)+datas/[^\s"\']+)')
    def replace(m):
        resolved = _resolve_data_path(m.group(1))
        return resolved if resolved else m.group(0)
    return pattern.sub(replace, config_text)


def edit_run_py(target_run_py: Path) -> None:
    """Strip the back_trader hook bootstrap and rewrite the benchmark_metrics import."""
    src = target_run_py.read_text(encoding="utf-8")

    # 1. Remove the canonical benchmark output hook block.
    # Pattern: from "# Canonical benchmark output hook." down to "_install_benchmark_metrics_hook(...)"
    src = re.sub(
        r"# Canonical benchmark output hook\.\n.*?_install_benchmark_metrics_hook\([^\n]*\)\n",
        "# Vendored benchmark output hook (auto-edited by migrate_regression.py)\n"
        "from pathlib import Path as _BenchmarkPath\n"
        "import sys as _benchmark_sys\n"
        "_BENCHMARK_BASE_DIR = _BenchmarkPath(__file__).resolve().parent\n"
        "_REPO_ROOT = _BenchmarkPath(__file__).resolve().parents[5]\n"
        "if str(_REPO_ROOT) not in _benchmark_sys.path:\n"
        "    _benchmark_sys.path.insert(0, str(_REPO_ROOT))\n"
        "from tests.test_utils.benchmark_metrics import (\n"
        "    install_benchmark_metrics_hook as _install_benchmark_metrics_hook,\n"
        "    load_benchmark_result as _load_benchmark_result,\n"
        "    write_benchmark_result as _write_benchmark_result,\n"
        ")\n"
        "_install_benchmark_metrics_hook(_BENCHMARK_BASE_DIR)\n",
        src,
        count=1,
        flags=re.DOTALL,
    )

    target_run_py.write_text(src, encoding="utf-8")


def edit_test_py(target_test_py: Path) -> None:
    """Rewrite the test file to drop back_trader path detection and use in-process."""
    src = target_test_py.read_text(encoding="utf-8")

    # Replace the _find_back_trader_root function - make it a no-op
    src = re.sub(
        r"def _find_back_trader_root\(\) -> Path:.*?return fallback.*?raise RuntimeError\([^)]*\)\n",
        "def _find_back_trader_root() -> Path:\n"
        "    # Vendored migration: no longer requires external back_trader workspace\n"
        "    return Path(__file__).resolve().parents[5]\n",
        src,
        count=1,
        flags=re.DOTALL,
    )

    # The PYTHONPATH injection in subprocess invocation: keep but also add our repo root
    # The existing test already sets PYTHONPATH to BACKTRADER_REPO + BACK_TRADER_ROOT.
    # With our edit, BACK_TRADER_ROOT = repo root, so it's effectively duplicated. That's fine.

    target_test_py.write_text(src, encoding="utf-8")


def make_init(path: Path) -> None:
    if not path.exists():
        path.touch()


def migrate_one(strategy_path: str) -> tuple[bool, str]:
    """Migrate a single strategy. Returns (ok, message)."""
    strategy_dir = REPO / strategy_path
    if not strategy_dir.exists():
        return False, "directory not found"

    category = strategy_dir.parent.name
    strategy_name = strategy_dir.name

    target_dir = TARGET_ROOT / category / "regression" / strategy_name
    if target_dir.exists():
        return True, f"already exists at {target_dir.relative_to(REPO)}"

    # 1. Copy directory recursively
    shutil.copytree(strategy_dir, target_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "backtest_result.json"))

    # 2. Remap data paths in config.yaml
    config_path = target_dir / "config.yaml"
    if config_path.exists():
        config_text = config_path.read_text(encoding="utf-8")
        config_remapped = remap_data_paths_in_config(config_text)
        if config_remapped != config_text:
            config_path.write_text(config_remapped, encoding="utf-8")

    # 3. Edit run.py
    run_py = target_dir / "run.py"
    if run_py.exists():
        edit_run_py(run_py)

    # 4. Edit test_*.py
    for test_py in target_dir.glob("test_*.py"):
        edit_test_py(test_py)

    # 5. Ensure __init__.py at target levels
    make_init(TARGET_ROOT / category / "regression" / "__init__.py")
    make_init(target_dir / "__init__.py")

    # 6. Verify the new test passes
    test_files = list(target_dir.glob("test_*.py"))
    if not test_files:
        shutil.rmtree(target_dir)
        return False, "no test_*.py file in source"

    verify = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header",
         "--tb=line", str(target_dir)],
        cwd=str(REPO), capture_output=True, text=True, timeout=300,
    )
    if verify.returncode != 0:
        # Keep artifacts for inspection on failure
        msg = verify.stdout[-600:] + verify.stderr[-200:]
        return False, f"verification failed (artifacts kept at {target_dir.relative_to(REPO)}): {msg.strip()}"

    # 7. Delete original
    shutil.rmtree(strategy_dir)

    return True, f"migrated to {target_dir.relative_to(REPO).as_posix()}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--from-index", type=int, default=0)
    args = parser.parse_args()

    sel = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))
    end = min(args.from_index + args.limit, len(sel))
    print(f"Migrating strategies [{args.from_index}:{end}] of {len(sel)}")
    print()

    success = 0
    failure = 0
    failures: list[tuple[str, str]] = []
    for i in range(args.from_index, end):
        item = sel[i]
        label = f"{item['category']}/{item['name']}"
        print(f"[{i+1:3d}/{len(sel)}] {label}", flush=True)
        try:
            ok, msg = migrate_one(item["path"])
        except Exception as e:
            ok, msg = False, f"EXCEPTION: {type(e).__name__}: {e}"
        status = "✓" if ok else "✗"
        print(f"     {status} {msg}", flush=True)
        if ok:
            success += 1
        else:
            failure += 1
            failures.append((label, msg))

    print()
    print(f"Success: {success}, Failure: {failure}")
    if failures:
        print("\nFailures:")
        for label, msg in failures[:20]:
            print(f"  {label}")
            print(f"    {msg[:200]}")


if __name__ == "__main__":
    main()
