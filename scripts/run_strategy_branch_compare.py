#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DYNAMIC_LOG_KEYS = {
    "event_time",
    "log_time",
    "run_id",
}

DEFAULT_BRANCHES = ["current", "master"]
LOG_FILE_NAMES = {
    "bar.log",
    "error.log",
    "indicator.log",
    "monitor.log",
    "order.log",
    "position.log",
    "signal.log",
    "system.log",
    "tick.log",
    "trade.log",
    "value.log",
    "current_position.yaml",
}


@dataclass
class BranchRunResult:
    label: str
    branch: str
    root: str
    run_file: str
    output_dir: str
    install_returncode: int | None = None
    run_returncode: int | None = None
    install_seconds: float | None = None
    run_seconds: float | None = None
    result_json: str | None = None
    result_hash: str | None = None
    copied_logs: list[str] = field(default_factory=list)
    normalized_log_hashes: dict[str, str] = field(default_factory=dict)
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install and run one strategy run.py across current/dev/master-like branches, "
            "collecting backtest_result.json and TradeLogger logs for comparison."
        )
    )
    parser.add_argument(
        "target",
        help="Strategy run.py, strategy directory, or strategy implementation file whose sibling run.py should be executed.",
    )
    parser.add_argument(
        "--branch",
        dest="branches",
        action="append",
        help=(
            "Branch/ref to run. Use 'current' for the current working tree including uncommitted changes. "
            "Can be repeated. Default: current and master."
        ),
    )
    parser.add_argument("--timeout", type=int, default=300, help="Timeout for run.py in seconds.")
    parser.add_argument("--install-timeout", type=int, default=300, help="Timeout for pip install -U . in seconds.")
    parser.add_argument("--skip-install", action="store_true", help="Skip pip install -U .; useful for smoke testing the script itself.")
    parser.add_argument("--no-restore-install", action="store_true", help="Do not reinstall the current working tree after branch runs.")
    parser.add_argument("--no-copy-target-to-worktree", action="store_true", help="Do not copy the current strategy directory into temporary worktrees.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without installing or running.")
    parser.add_argument("--keep-worktrees", action="store_true", help="Keep temporary git worktrees after completion.")
    parser.add_argument("--keep-result", action="store_true", help="Do not restore/remove backtest_result.json after running in the current worktree.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used for pip install and run.py.")
    parser.add_argument(
        "--output-root",
        default="logs/branch_strategy_compare",
        help="Directory in the main repo where reports and copied logs are written.",
    )
    parser.add_argument(
        "--worktree-root",
        default=".branch_compare_worktrees",
        help="Directory in the main repo where temporary worktrees are created.",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        help="Extra environment variable KEY=VALUE passed to run.py. Can be repeated.",
    )
    parser.add_argument(
        "--run-arg",
        action="append",
        default=[],
        help="Extra argument passed to run.py. Can be repeated.",
    )
    return parser.parse_args()


def run_command(
    cmd: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> tuple[int, str, float]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", time.perf_counter() - started
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        output += f"\n[TIMEOUT] command exceeded {timeout}s\n"
        return 124, output, time.perf_counter() - started


def repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "backtrader").is_dir():
            return parent
    raise RuntimeError("Cannot find repository root")


def git_stdout(root: Path, args: list[str], timeout: int = 60) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def safe_name(value: str) -> str:
    cleaned = []
    for char in value:
        if char.isalnum() or char in {"-", "_", "."}:
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "".join(cleaned).strip("_") or "unnamed"


def resolve_target(root: Path, target_text: str) -> tuple[Path, Path]:
    target = Path(target_text)
    if not target.is_absolute():
        direct = root / target
        if direct.exists():
            target = direct
        else:
            regression_child = root / "tests/functional/strategies_regression" / target
            if regression_child.exists():
                target = regression_child
    target = target.resolve()
    if not target.exists():
        raise FileNotFoundError(target)
    if target.is_file() and target.name == "run.py":
        run_py = target
    elif target.is_dir():
        run_py = target / "run.py"
    elif target.is_file():
        run_py = target.parent / "run.py"
    else:
        raise ValueError(f"Unsupported target: {target}")
    if not run_py.exists():
        raise FileNotFoundError(f"Cannot find sibling run.py for target: {target}")
    try:
        run_rel = run_py.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Target must be inside repo root {root}: {run_py}") from exc
    return run_py, run_rel


def parse_extra_env(items: list[str]) -> dict[str, str]:
    extra: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--env must be KEY=VALUE, got: {item}")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError(f"--env key cannot be empty: {item}")
        extra[key] = value
    return extra


def build_env(root: Path, branch_label: str, output_dir: Path, extra_env: dict[str, str], main_root: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = [str(root)]
    sibling_back_trader = root.parent / "back_trader"
    if sibling_back_trader.exists():
        pythonpath.append(str(sibling_back_trader))
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["MPLBACKEND"] = "Agg"
    env["BT_BRANCH_COMPARE"] = "1"
    env["BT_BRANCH_COMPARE_BRANCH"] = branch_label
    env["BT_BRANCH_COMPARE_OUTPUT_DIR"] = str(output_dir)
    env["BT_TRADE_LOG_DIR"] = str(output_dir / "trade_logger")
    env["BT_TRADELOGGER_LOG_DIR"] = str(output_dir / "trade_logger")
    env["TRADE_LOG_DIR"] = str(output_dir / "trade_logger")
    if main_root is not None:
        # Used by branch-compare runners to resolve repo-relative test fixtures
        # (e.g. tests/datas/XAUUSD_M15.csv) consistently across worktrees.
        env["BT_BRANCH_COMPARE_DATA_ROOT"] = str(main_root)
    env.update(extra_env)
    return env


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): normalize_json_value(val)
            for key, val in value.items()
            if str(key) not in DYNAMIC_LOG_KEYS
        }
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    return value


def normalized_log_bytes(path: Path) -> bytes:
    output = [json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) for item in normalized_log_items(path)]
    return ("\n".join(output) + ("\n" if output else "")).encode("utf-8")


def normalized_log_items(path: Path) -> list[Any]:
    output: list[Any] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            output.append(stripped)
            continue
        output.append(normalize_json_value(parsed))
    return output


def file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def snapshot_candidate_files(paths: list[Path]) -> dict[Path, tuple[int, int]]:
    snapshot: dict[Path, tuple[int, int]] = {}
    for base in paths:
        if not base.exists():
            continue
        if base.is_file():
            snapshot[base] = file_signature(base)
            continue
        for file_path in base.rglob("*"):
            if file_path.is_file():
                snapshot[file_path] = file_signature(file_path)
    return snapshot


def collect_changed_files(paths: list[Path], before: dict[Path, tuple[int, int]], output_dir: Path) -> list[Path]:
    changed: list[Path] = []
    trade_logger_dir = output_dir / "trade_logger"
    for base in paths:
        if not base.exists():
            continue
        candidates = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for file_path in candidates:
            if is_relative_to(file_path, output_dir) and not is_relative_to(file_path, trade_logger_dir):
                continue
            if file_path.name not in LOG_FILE_NAMES and file_path.suffix not in {".log", ".json", ".yaml", ".yml"}:
                continue
            sig = file_signature(file_path)
            if before.get(file_path) != sig:
                changed.append(file_path)
    return sorted(set(changed))


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def stable_log_key(file_path: Path, source_root: Path, strategy_dir: Path, output_dir: Path) -> Path:
    trade_logger_dir = output_dir / "trade_logger"
    bases = [
        (trade_logger_dir, Path("trade_logger")),
        (strategy_dir / "logs", Path("strategy_logs")),
        (strategy_dir / "log", Path("strategy_log")),
        (strategy_dir / "trade_logs", Path("strategy_trade_logs")),
        (strategy_dir / "trade_logger_logs", Path("strategy_trade_logger_logs")),
        (source_root / "logs", Path("repo_logs")),
        (strategy_dir, Path("strategy_dir")),
        (source_root, Path("repo")),
    ]
    for base, prefix in bases:
        try:
            return prefix / file_path.relative_to(base)
        except ValueError:
            continue
    return Path("external") / file_path.name


def copy_changed_logs(changed_files: list[Path], source_root: Path, strategy_dir: Path, output_dir: Path) -> list[str]:
    copied: list[str] = []
    logs_dir = output_dir / "collected_logs"
    for file_path in changed_files:
        rel = stable_log_key(file_path, source_root, strategy_dir, output_dir)
        dest = logs_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest)
        copied.append(str(rel))
    return sorted(copied)


def normalize_hash_copied_logs(output_dir: Path, copied: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rel_text in copied:
        path = output_dir / "collected_logs" / rel_text
        if not path.exists() or path.is_dir():
            continue
        if path.suffix == ".log":
            payload = normalized_log_bytes(path)
        else:
            payload = path.read_bytes()
        hashes[rel_text] = sha256_bytes(payload)
    return hashes


def snapshot_result(result_path: Path) -> bytes | None:
    if result_path.exists():
        return result_path.read_bytes()
    return None


def restore_result(result_path: Path, original: bytes | None) -> None:
    if original is None:
        if result_path.exists():
            result_path.unlink()
        return
    result_path.write_bytes(original)


def create_worktree(main_root: Path, worktree_root: Path, branch: str, label: str) -> Path:
    worktree_root.mkdir(parents=True, exist_ok=True)
    dest = worktree_root / label
    if dest.exists():
        shutil.rmtree(dest)
    cmd = ["git", "worktree", "add", "--detach", str(dest), branch]
    code, output, _seconds = run_command(cmd, cwd=main_root, timeout=120)
    if code != 0:
        raise RuntimeError(f"Failed to create worktree for {branch}:\n{output}")
    return dest


def remove_worktree(main_root: Path, worktree_path: Path) -> None:
    if not worktree_path.exists():
        return
    code, output, _seconds = run_command(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=main_root,
        timeout=120,
    )
    if code != 0:
        shutil.rmtree(worktree_path, ignore_errors=True)


def sync_target_to_worktree(main_root: Path, source_root: Path, run_rel: Path) -> None:
    if source_root == main_root:
        return
    source_dir = main_root / run_rel.parent
    target_dir = source_root / run_rel.parent
    if not source_dir.exists():
        return
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target_dir)
    sync_auxiliary_path(main_root, source_root, Path("tests/functional/datas"))
    sync_auxiliary_path(main_root, source_root, Path("tests/functional/strategies"))
    sync_auxiliary_path(main_root, source_root, Path("tests/datas"))


def sync_auxiliary_path(main_root: Path, source_root: Path, rel_path: Path) -> None:
    source_path = main_root / rel_path
    target_path = source_root / rel_path
    if not source_path.exists() or target_path.exists():
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        target_path.symlink_to(source_path, target_is_directory=source_path.is_dir())
    except OSError:
        if source_path.is_dir():
            shutil.copytree(source_path, target_path, symlinks=True)
        else:
            shutil.copy2(source_path, target_path)


def restore_current_install(main_root: Path, output_root: Path, python_exe: str, install_timeout: int) -> dict[str, Any]:
    env = build_env(main_root, "restore_current", output_root / "restore_current", {})
    code, output, seconds = run_command(
        [python_exe, "-m", "pip", "install", "-U", "."],
        cwd=main_root,
        timeout=install_timeout,
        env=env,
    )
    log_path = output_root / "restore_current_install.log"
    log_path.write_text(output, encoding="utf-8", errors="replace")
    return {
        "returncode": code,
        "seconds": round(seconds, 3),
        "log_path": str(log_path),
    }


def run_branch(
    *,
    main_root: Path,
    source_root: Path,
    branch: str,
    label: str,
    run_rel: Path,
    output_dir: Path,
    python_exe: str,
    timeout: int,
    install_timeout: int,
    skip_install: bool,
    dry_run: bool,
    keep_result: bool,
    copy_target_to_worktree: bool,
    extra_env: dict[str, str],
    run_args: list[str],
) -> BranchRunResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = BranchRunResult(
        label=label,
        branch=branch,
        root=str(source_root),
        run_file=str(source_root / run_rel),
        output_dir=str(output_dir),
    )
    run_file = source_root / run_rel
    strategy_dir = run_file.parent
    result_path = strategy_dir / "backtest_result.json"
    if dry_run:
        (output_dir / "plan.txt").write_text(
            (
                f"branch={branch}\n"
                f"root={source_root}\n"
                f"run_file={run_file}\n"
                f"install={'no' if skip_install else 'yes'}\n"
                f"copy_target_to_worktree={'yes' if copy_target_to_worktree and source_root != main_root else 'no'}\n"
            ),
            encoding="utf-8",
        )
        return result
    if copy_target_to_worktree:
        sync_target_to_worktree(main_root, source_root, run_rel)
    if not run_file.exists():
        result.error = f"run.py not found in branch {branch}: {run_file}"
        return result
    env = build_env(source_root, label, output_dir, extra_env, main_root=main_root)
    log_candidates = [
        output_dir / "trade_logger",
        source_root / "logs",
        strategy_dir / "logs",
        strategy_dir / "log",
        strategy_dir / "trade_logs",
        strategy_dir / "trade_logger_logs",
    ]
    before_logs = snapshot_candidate_files(log_candidates)
    original_result = snapshot_result(result_path)
    try:
        if not skip_install:
            install_code, install_output, install_seconds = run_command(
                [python_exe, "-m", "pip", "install", "-U", "."],
                cwd=source_root,
                timeout=install_timeout,
                env=env,
            )
            result.install_returncode = install_code
            result.install_seconds = round(install_seconds, 3)
            (output_dir / "install.log").write_text(install_output, encoding="utf-8", errors="replace")
            if install_code != 0:
                result.error = f"pip install failed with return code {install_code}"
                return result
        else:
            result.install_returncode = None
        run_code, run_output, run_seconds = run_command(
            [python_exe, "-u", run_file.name, *run_args],
            cwd=strategy_dir,
            timeout=timeout,
            env=env,
        )
        result.run_returncode = run_code
        result.run_seconds = round(run_seconds, 3)
        (output_dir / "run.log").write_text(run_output, encoding="utf-8", errors="replace")
        if result_path.exists():
            copied_result = output_dir / "backtest_result.json"
            shutil.copy2(result_path, copied_result)
            result.result_json = str(copied_result)
            result.result_hash = sha256_bytes(copied_result.read_bytes())
        if run_code != 0:
            result.error = f"run.py failed with return code {run_code}"
        changed = collect_changed_files(log_candidates, before_logs, output_dir)
        result.copied_logs = copy_changed_logs(changed, source_root, strategy_dir, output_dir)
        result.normalized_log_hashes = normalize_hash_copied_logs(output_dir, result.copied_logs)
        return result
    finally:
        if source_root == main_root and not keep_result:
            restore_result(result_path, original_result)


def compare_results(results: list[BranchRunResult]) -> dict[str, Any]:
    successful = [item for item in results if not item.error and item.run_returncode in {0, None}]
    result_hashes = {item.label: item.result_hash for item in results if item.result_hash}
    comparison_ready = len(result_hashes) == len(results) and len(result_hashes) > 0
    all_log_names = sorted({name for item in results for name in item.normalized_log_hashes})
    log_comparison: dict[str, Any] = {}
    for log_name in all_log_names:
        hashes = {
            item.label: item.normalized_log_hashes.get(log_name)
            for item in results
            if log_name in item.normalized_log_hashes
        }
        log_comparison[log_name] = {
            "hashes": hashes,
            "all_equal": len(set(hashes.values())) <= 1 and len(hashes) == len(results),
            "missing_in": [item.label for item in results if log_name not in item.normalized_log_hashes],
        }
        if not log_comparison[log_name]["all_equal"]:
            log_comparison[log_name]["first_diff"] = first_log_diff(results, log_name)
    return {
        "result_hashes": result_hashes,
        "comparison_ready": comparison_ready,
        "result_all_equal": (len(set(result_hashes.values())) <= 1 and len(result_hashes) == len(results)) if comparison_ready else None,
        "log_comparison": log_comparison,
        "success_count": len(successful),
    }


def first_log_diff(results: list[BranchRunResult], log_name: str) -> dict[str, Any]:
    available = [item for item in results if log_name in item.normalized_log_hashes]
    if len(available) < 2:
        return {"reason": "missing_log"}
    baseline = available[0]
    baseline_path = Path(baseline.output_dir) / "collected_logs" / log_name
    baseline_items = normalized_log_items(baseline_path)
    comparisons: dict[str, Any] = {}
    for item in available[1:]:
        path = Path(item.output_dir) / "collected_logs" / log_name
        items = normalized_log_items(path)
        max_len = max(len(baseline_items), len(items))
        for idx in range(max_len):
            left = baseline_items[idx] if idx < len(baseline_items) else None
            right = items[idx] if idx < len(items) else None
            if left == right:
                continue
            diff: dict[str, Any] = {
                "baseline": baseline.label,
                "compare": item.label,
                "line": idx + 1,
            }
            if isinstance(left, dict) and isinstance(right, dict):
                field_diff = {}
                for key in sorted(set(left) | set(right)):
                    if left.get(key) != right.get(key):
                        field_diff[key] = {
                            baseline.label: left.get(key),
                            item.label: right.get(key),
                        }
                diff["field_diff"] = field_diff
                diff["field_count"] = len(field_diff)
            else:
                diff["baseline_value"] = left
                diff["compare_value"] = right
            comparisons[item.label] = diff
            break
        else:
            comparisons[item.label] = {"baseline": baseline.label, "compare": item.label, "reason": "no_row_diff"}
    return comparisons


def main() -> int:
    args = parse_args()
    main_root = repo_root()
    branches = args.branches or DEFAULT_BRANCHES
    extra_env = parse_extra_env(args.env)
    run_py, run_rel = resolve_target(main_root, args.target)
    current_branch = git_stdout(main_root, ["branch", "--show-current"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    strategy_label = safe_name(str(run_rel.parent))
    output_root = (main_root / args.output_root).resolve() if not Path(args.output_root).is_absolute() else Path(args.output_root)
    run_output_root = output_root / f"{timestamp}__{strategy_label}"
    worktree_root = (main_root / args.worktree_root).resolve() if not Path(args.worktree_root).is_absolute() else Path(args.worktree_root)
    run_output_root.mkdir(parents=True, exist_ok=True)

    print(f"repo_root: {main_root}", flush=True)
    print(f"current_branch: {current_branch}", flush=True)
    print(f"target_run_py: {run_py}", flush=True)
    print(f"branches: {branches}", flush=True)
    print(f"output: {run_output_root}", flush=True)

    results: list[BranchRunResult] = []
    created_worktrees: list[Path] = []
    restore_install_result: dict[str, Any] | None = None
    try:
        for branch in branches:
            if branch == "current":
                label = safe_name(f"current__{current_branch or 'detached'}")
                source_root = main_root
            else:
                label = safe_name(branch)
                if args.dry_run:
                    source_root = worktree_root / f"{timestamp}__{label}"
                else:
                    source_root = create_worktree(main_root, worktree_root, branch, f"{timestamp}__{label}")
                    created_worktrees.append(source_root)
            print(f"\n=== running {branch} ({label}) ===", flush=True)
            branch_result = run_branch(
                main_root=main_root,
                source_root=source_root,
                branch=branch,
                label=label,
                run_rel=run_rel,
                output_dir=run_output_root / label,
                python_exe=args.python,
                timeout=args.timeout,
                install_timeout=args.install_timeout,
                skip_install=args.skip_install,
                dry_run=args.dry_run,
                keep_result=args.keep_result,
                copy_target_to_worktree=not args.no_copy_target_to_worktree,
                extra_env=extra_env,
                run_args=args.run_arg,
            )
            results.append(branch_result)
            print(
                f"branch={branch} install_rc={branch_result.install_returncode} "
                f"run_rc={branch_result.run_returncode} result_hash={branch_result.result_hash} "
                f"logs={len(branch_result.copied_logs)} error={branch_result.error}",
                flush=True,
            )
    finally:
        if not args.keep_worktrees:
            for worktree in created_worktrees:
                remove_worktree(main_root, worktree)
        if not args.skip_install and not args.dry_run and not args.no_restore_install:
            print("\n=== restoring current install ===", flush=True)
            restore_install_result = restore_current_install(main_root, run_output_root, args.python, args.install_timeout)
            print(
                f"restore_install_rc={restore_install_result['returncode']} "
                f"seconds={restore_install_result['seconds']}",
                flush=True,
            )

    comparison = compare_results(results)
    report = {
        "repo_root": str(main_root),
        "current_branch": current_branch,
        "target": str(run_py),
        "run_rel": str(run_rel),
        "branches": branches,
        "output_root": str(run_output_root),
        "dry_run": args.dry_run,
        "skip_install": args.skip_install,
        "restore_install": restore_install_result,
        "results": [item.__dict__ for item in results],
        "comparison": comparison,
    }
    report_path = run_output_root / "branch_compare_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nREPORT {report_path}", flush=True)
    result_all_equal = comparison["result_all_equal"]
    print(f"RESULT_ALL_EQUAL {result_all_equal if result_all_equal is not None else 'N/A'}", flush=True)
    differing_logs = [name for name, item in comparison["log_comparison"].items() if not item["all_equal"]]
    print(f"DIFFERING_LOG_FILES {len(differing_logs)}", flush=True)
    for name in differing_logs[:30]:
        print(f"DIFF_LOG {name}", flush=True)
    failed = [item for item in results if item.error or item.run_returncode not in {0, None} or item.install_returncode not in {0, None}]
    if restore_install_result and restore_install_result["returncode"] != 0:
        failed.append(BranchRunResult(label="restore_current", branch="current", root=str(main_root), run_file=str(run_py), output_dir=str(run_output_root), error="restore install failed"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
