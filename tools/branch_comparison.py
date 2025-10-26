#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

"""
Branch comparison runner for 需求09.md

Functions:
- Compare performance between two branches with specific environments and test sets
- Capture all terminal output into a single log file
- Summarize key metrics (duration, pass/fail) into a JSON sidecar

Default behavior matches 需求09.md:
  1) On remove-metaprogramming branch, use current (base) env:
     - pip install -U .
     - pytest tests/add_tests tests/base_functions tests/original_tests -n 12
  2) Switch to master branch, use conda env py313:
     - pytest tests -n 12
  3) Append outputs to the same log file and write a summary JSON

Usage examples (PowerShell):
  python tools/branch_comparison.py
  python tools/branch_comparison.py --log logs/req09_compare.log --workers 12

Notes:
- Requires git and pytest in relevant environments. Will attempt to fall back if conda is unavailable.
- Restores original branch and working directory on completion or error.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_command(cmd, cwd=None, env=None, log_fp=None, echo=True, check=True):
    """Run a command, stream output to stdout and optionally to a log file.

    Returns: (returncode, duration_seconds)
    """
    start = time.time()
    if echo:
        print(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        if log_fp is not None:
            log_fp.write(line)
    proc.wait()
    duration = time.time() - start
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    return proc.returncode, duration


def git_current_branch() -> str:
    out = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT)
    return out.decode().strip()


def git_current_commit() -> str:
    out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT)
    return out.decode().strip()


def git_is_dirty() -> bool:
    out = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT)
    return bool(out.decode().strip())


def git_stash_push(message: str) -> bool:
    try:
        subprocess.check_call(["git", "stash", "push", "-u", "-m", message], cwd=REPO_ROOT)
        return True
    except subprocess.CalledProcessError:
        return False


def git_stash_pop() -> bool:
    try:
        subprocess.check_call(["git", "stash", "pop"], cwd=REPO_ROOT)
        return True
    except subprocess.CalledProcessError:
        return False


@contextlib.contextmanager
def switched_branch(target_branch: str):
    """Temporarily checkout a branch, then restore the original branch."""
    original_branch = git_current_branch()
    original_commit = git_current_commit()
    stashed = False
    try:
        if target_branch:
            subprocess.check_call(["git", "fetch", "--all"], cwd=REPO_ROOT)
            # Auto-stash local changes to allow clean checkout
            if git_is_dirty():
                msg = f"branch_comparison_auto_{int(time.time())}"
                print(f"Working tree dirty; stashing local changes: {msg}")
                stashed = git_stash_push(msg)
            subprocess.check_call(["git", "checkout", target_branch], cwd=REPO_ROOT)
        yield
    finally:
        # Attempt to restore original state
        try:
            subprocess.check_call(["git", "checkout", original_branch], cwd=REPO_ROOT)
            # Ensure we are back to the same commit if detached.
            if original_branch == "HEAD":
                subprocess.check_call(["git", "checkout", original_commit], cwd=REPO_ROOT)
            # Restore stashed changes if we created a stash
            if stashed:
                ok = git_stash_pop()
                if not ok:
                    print("Warning: failed to auto-apply stashed changes. Manual recovery may be needed (git stash list).")
        except Exception as e:  # noqa: BLE001
            print(f"Warning: failed to restore original branch: {e}")


def which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def conda_run(env_name: str, args: list[str]) -> list[str]:
    """Build a conda run command if conda exists; otherwise return the raw args."""
    if which("conda"):
        return ["conda", "run", "-n", env_name, *args]
    return args


def ensure_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix:  # file path
        path.parent.mkdir(parents=True, exist_ok=True)
    else:  # directory path
        path.mkdir(parents=True, exist_ok=True)


def add_worktree(branch: str, worktree_path: Path):
    """Create or update a git worktree for the given branch at worktree_path."""
    worktree_path = worktree_path.resolve()
    # Remove existing directory if present (not a worktree)
    if worktree_path.exists() and not (worktree_path / ".git").exists():
        shutil.rmtree(worktree_path, ignore_errors=True)
    # Ensure parent exists
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    # Add the worktree
    subprocess.check_call(["git", "worktree", "add", "--force", str(worktree_path), branch], cwd=REPO_ROOT)


def remove_worktree(worktree_path: Path):
    worktree_path = worktree_path.resolve()
    try:
        subprocess.check_call(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=REPO_ROOT)
    except subprocess.CalledProcessError:
        # Fallback: hard delete directory
        shutil.rmtree(worktree_path, ignore_errors=True)


def parse_pytest_summary_from_log(log_text: str) -> dict:
    """Extract a minimal summary from pytest output."""
    summary = {
        "collected": None,
        "passed": None,
        "failed": None,
        "skipped": None,
        "xfailed": None,
        "xpassed": None,
        "warnings": None,
        "errors": None,
        "duration_seconds": None,
    }
    # Best-effort regex-free parsing for common lines
    for line in log_text.splitlines():
        s = line.strip()
        if s.startswith("collected "):
            try:
                parts = s.split()
                summary["collected"] = int(parts[1])
            except Exception:
                pass
        if s.lower().startswith("== ") and (" in " in s) and (" seconds ==" in s.lower() or "s ==" in s.lower()):
            # Example: "== 88 passed, 2 skipped in 12.34s =="
            # We capture counts and duration loosely
            try:
                left, right = s.strip("=").split(" in ")
                duration_token = right.strip("=").strip()
                if duration_token.endswith("s"):
                    duration_token = duration_token[:-1]
                summary["duration_seconds"] = float(duration_token)
                # Parse counts
                items = [t.strip() for t in left.split(",")]
                for item in items:
                    if "passed" in item:
                        summary["passed"] = int(item.split()[0])
                    elif "failed" in item:
                        summary["failed"] = int(item.split()[0])
                    elif "skipped" in item:
                        summary["skipped"] = int(item.split()[0])
                    elif "xfailed" in item:
                        summary["xfailed"] = int(item.split()[0])
                    elif "xpassed" in item:
                        summary["xpassed"] = int(item.split()[0])
                    elif "warnings" in item:
                        summary["warnings"] = int(item.split()[0])
                    elif "errors" in item:
                        summary["errors"] = int(item.split()[0])
            except Exception:
                pass
    return summary


def main():
    parser = argparse.ArgumentParser(description="Branch comparison runner for 需求09.md")
    parser.add_argument("--branch-a", default="remove-metaprogramming", help="Branch A (base env)")
    parser.add_argument("--branch-b", default="master", help="Branch B (conda env)")
    parser.add_argument("--conda-env", default="py313", help="Conda env name for Branch B")
    parser.add_argument("--workers", type=int, default=12, help="pytest -n workers")
    parser.add_argument(
        "--log",
        default=str(REPO_ROOT / "logs" / "req09_compare.log"),
        help="Path to combined log file",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip 'pip install -U .' step on branch A",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print planned commands without executing",
    )
    args = parser.parse_args()

    log_path = Path(args.log)
    ensure_dir(log_path)

    a_tests = [
        str(REPO_ROOT / "tests" / "add_tests"),
        str(REPO_ROOT / "tests" / "base_functions"),
        str(REPO_ROOT / "tests" / "original_tests"),
    ]
    b_tests = ["tests"]  # Will be resolved relative to worktree

    summary = {
        "python": sys.version,
        "platform": sys.platform,
        "workers": args.workers,
        "branch_a": {
            "name": args.branch_a,
            "env": "base",
            "commit": None,
            "duration_seconds": None,
            "pytest": {},
        },
        "branch_b": {
            "name": args.branch_b,
            "env": args.conda_env,
            "commit": None,
            "duration_seconds": None,
            "pytest": {},
        },
    }

    with open(log_path, "a", encoding="utf-8", newline="\n") as log_fp:
        log_fp.write("\n" + "=" * 80 + "\n")
        log_fp.write(time.strftime("[%Y-%m-%d %H:%M:%S] Branch comparison start\n"))
        log_fp.write("=" * 80 + "\n")

        # Branch A: remove-metaprogramming on base env
        with switched_branch(args.branch_a):
            commit_a = git_current_commit()
            summary["branch_a"]["commit"] = commit_a
            header = f"[Branch A] {args.branch_a} @ {commit_a} (base env)\n"
            print(header)
            log_fp.write(header)

            if not args.skip_install:
                install_cmd = [sys.executable, "-m", "pip", "install", "-U", "."]
                if args.dry_run:
                    print("DRY-RUN:", " ".join(install_cmd))
                    log_fp.write("DRY-RUN: " + " ".join(install_cmd) + "\n")
                else:
                    run_command(install_cmd, cwd=str(REPO_ROOT), log_fp=log_fp)

            # pytest branch A
            pytest_cmd_a = [
                sys.executable,
                "-m",
                "pytest",
                *a_tests,
                "-n",
                str(args.workers),
            ]
            if args.dry_run:
                print("DRY-RUN:", " ".join(pytest_cmd_a))
                log_fp.write("DRY-RUN: " + " ".join(pytest_cmd_a) + "\n")
                a_duration = 0.0
            else:
                _, a_duration = run_command(pytest_cmd_a, cwd=str(REPO_ROOT), log_fp=log_fp, check=False)
            summary["branch_a"]["duration_seconds"] = a_duration

        # Branch B: run tests on a separate git worktree for the branch using conda env
        worktrees_root = REPO_ROOT / ".worktrees"
        worktree_dir = worktrees_root / f"{args.branch_b}_compare_{int(time.time())}"
        if not args.dry_run:
            # Prepare worktree
            print(f"Creating worktree for {args.branch_b} at {worktree_dir}")
            add_worktree(args.branch_b, worktree_dir)
            # Resolve commit in worktree
            commit_b = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree_dir).decode().strip()
            summary["branch_b"]["commit"] = commit_b
        else:
            commit_b = "DRYRUN"
            summary["branch_b"]["commit"] = commit_b
        header = f"[Branch B] {args.branch_b} @ {commit_b} (conda env: {args.conda_env})\n"
        print(header)
        log_fp.write(header)

        # Ensure required tooling and package are installed in target env
        install_cmds = [
            conda_run(args.conda_env, [
                "python", "-m", "pip", "install", "-U",
                "-r", "requirements.txt",
                "pytest", "pytest-xdist", "pytest-html", "pytest-metadata",
                "empyrical-reloaded"
            ]),
            conda_run(args.conda_env, [
                "python", "-m", "pip", "install", "-U", "."
            ]),
        ]

        pytest_cmd_b = conda_run(args.conda_env, [
            "python",
            "-m",
            "pytest",
            *b_tests,
            "-n",
            str(args.workers),
        ])
        if args.dry_run:
            print("DRY-RUN:", " ".join(pytest_cmd_b))
            log_fp.write("DRY-RUN: " + " ".join(pytest_cmd_b) + "\n")
            b_duration = 0.0
        else:
            try:
                # Install dependencies within the worktree cwd
                for cmd in install_cmds:
                    run_command(cmd, cwd=str(worktree_dir), log_fp=log_fp, check=False)
                # Run pytest rooted at worktree so it imports the correct code
                _, b_duration = run_command(pytest_cmd_b, cwd=str(worktree_dir), log_fp=log_fp, check=False)
            finally:
                # Clean up worktree directory
                remove_worktree(worktree_dir)
        summary["branch_b"]["duration_seconds"] = b_duration

        # Parse pytest summaries from the appended log content
        try:
            log_text = Path(log_path).read_text(encoding="utf-8")
            # Rough heuristics: parse last two occurrences
            parsed = parse_pytest_summary_from_log(log_text)
            # Non-attributed parse; keep it under a neutral key
            summary["last_pytest_summary"] = parsed
        except Exception as e:  # noqa: BLE001
            print(f"Warning: failed to parse pytest summary from log: {e}")

    # Write sidecar JSON summary
    json_path = log_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(summary, jf, indent=2, ensure_ascii=False)
    print(f"Summary JSON written to: {json_path}")

    # Minimal CLI summary
    print("=" * 80)
    print("Branch comparison finished")
    print(
        f"A: {summary['branch_a']['name']} @ {summary['branch_a']['commit']} took {summary['branch_a']['duration_seconds']:.2f}s"
    )
    print(
        f"B: {summary['branch_b']['name']} @ {summary['branch_b']['commit']} took {summary['branch_b']['duration_seconds']:.2f}s"
    )
    print("=" * 80)


if __name__ == "__main__":
    sys.exit(main() or 0)


