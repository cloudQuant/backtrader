#!/usr/bin/env python
"""
Run test files and display output in terminal while saving to log file.
Log filename includes current git branch name.

Usage:
    python run_test_with_log.py <test_script> [--both]

Args:
    test_script: Path to the test script
    --both: Run tests on both master and origin branches
            If not specified, run only on current branch

Example:
    # Run only on current branch
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py

    # Run on both branches
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py --both

    # Run on master and origin branches
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py --both
"""

import argparse
import glob
import os
import subprocess
import sys
from datetime import datetime


def get_git_branch():
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, check=True
        )
        branch = result.stdout.strip()
        if not branch:
            # If no branch name, try to get HEAD description
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            branch = result.stdout.strip()
        return branch if branch else "unknown"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def git_stash():
    """Stash uncommitted changes."""
    try:
        # Check if there are changes to stash
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True
        )
        if result.stdout.strip():
            print("Found uncommitted changes, executing git stash...")
            result = subprocess.run(
                ["git", "stash", "push", "-m", "auto-stash-by-run_test_with_log"],
                capture_output=True,
                text=True,
                check=True
            )
            print("Stash successful")
            return True
        else:
            print("No changes to stash")
            return False
    except subprocess.CalledProcessError as e:
        print(f"Stash failed: {e.stderr}")
        return False


def git_stash_pop():
    """Restore stashed changes."""
    try:
        # Check if there is a stash
        result = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True,
            text=True,
            check=True
        )
        if "auto-stash-by-run_test_with_log" in result.stdout:
            print("Restoring stashed changes...")
            # Use stash apply instead of pop, so if it fails, stash won't be deleted
            result = subprocess.run(
                ["git", "stash", "apply", "stash@{0}"],
                capture_output=True,
                text=True,
                check=False  # Don't auto-raise exception, we check ourselves
            )
            if result.returncode != 0:
                print(f"Warning: Conflict or error occurred while restoring stash")
                print(f"stderr: {result.stderr}")
                print(f"stdout: {result.stdout}")
                print("Please manually resolve conflicts and run: git stash drop")
                return False

            # Delete stash after successful apply
            result = subprocess.run(
                ["git", "stash", "drop", "stash@{0}"],
                capture_output=True,
                text=True,
                check=True
            )
            print("Restore successful")
            return True
        else:
            print("Warning: No auto-stashed changes found")
            return False
    except subprocess.CalledProcessError as e:
        print(f"Failed to restore stash: {e.stderr}")
        return False
    except Exception as e:
        print(f"Exception occurred while restoring stash: {e}")
        return False


def switch_branch(branch_name):
    """Switch to specified git branch."""
    print(f"\n{'='*60}")
    print(f"Switching to branch: {branch_name}")
    print(f"{'='*60}\n")

    try:
        result = subprocess.run(
            ["git", "checkout", branch_name],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"Successfully switched to branch: {branch_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to switch branch: {e.stderr}")
        return False


def pip_install():
    """Execute pip install -U . to install current branch code."""
    print(f"\n{'='*60}")
    print("Executing pip install -U . to install current code...")
    print(f"{'='*60}\n")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "."],
            capture_output=True,
            text=True,
            check=True
        )
        print("pip install successful")
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"pip install failed: {e.stderr}")
        return False


def cleanup_old_logs(script_path, branch_name, log_dir="logs"):
    """Clean up old log files for current branch.

    Args:
        script_path: Script path, used to generate log filename pattern
        branch_name: Git branch name
        log_dir: Log directory
    """
    if not os.path.exists(log_dir):
        return

    script_name = os.path.splitext(os.path.basename(script_path))[0]
    # Match pattern: {script_name}_{branch_name}_*.log
    pattern = os.path.join(log_dir, f"{script_name}_{branch_name}_*.log")

    # Find all matching old log files
    old_logs = glob.glob(pattern)

    if old_logs:
        print(f"Cleaning up {len(old_logs)} old log files...")
        for log_file in old_logs:
            try:
                os.remove(log_file)
                print(f"  Deleted: {os.path.basename(log_file)}")
            except Exception as e:
                print(f"  Failed to delete {os.path.basename(log_file)}: {e}")
        print()


def run_with_logging(script_path, log_dir="logs", branch_name=None):
    """Run specified script and display output in terminal while saving to log file.

    Args:
        script_path: Script path to run
        log_dir: Log file save directory
        branch_name: Specified branch name (auto-fetch if None)

    Returns:
        tuple: (return_code, log_path)
    """
    # Create log directory
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Get git branch name
    if branch_name is None:
        branch_name = get_git_branch()

    # Clean up old log files for current branch
    cleanup_old_logs(script_path, branch_name, log_dir)

    # Generate log filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_name = os.path.splitext(os.path.basename(script_path))[0]
    log_filename = f"{script_name}_{branch_name}_{timestamp}.log"
    log_path = os.path.join(log_dir, log_filename)

    print(f"{'='*60}")
    print(f"Running script: {script_path}")
    print(f"Git branch: {branch_name}")
    print(f"Log file: {log_path}")
    print(f"{'='*60}\n")

    # Open log file
    with open(log_path, "w", encoding="utf-8") as log_file:
        # Write file header
        log_file.write(f"{'='*60}\n")
        log_file.write(f"Running script: {script_path}\n")
        log_file.write(f"Git branch: {branch_name}\n")
        log_file.write(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.write(f"{'='*60}\n\n")
        log_file.flush()

        # Run script
        try:
            # Use Popen + communicate to get complete output
            # Use -u parameter to disable output buffering
            process = subprocess.Popen(
                [sys.executable, "-u", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=0,  # No buffering
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
            )

            # Use communicate to get all output, avoid buffer overflow causing output loss
            output, _ = process.communicate()

            # Output to terminal and log file
            print(output, end="")
            log_file.write(output)
            log_file.flush()

            return_code = process.returncode

            # Write end information
            end_msg = f"\n{'='*60}\n"
            end_msg += f"Script execution completed\n"
            end_msg += f"Exit code: {return_code}\n"
            end_msg += f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            end_msg += f"{'='*60}\n"

            print(end_msg)
            log_file.write(end_msg)

            return return_code, log_path

        except Exception as e:
            error_msg = f"\nExecution error: {str(e)}\n"
            print(error_msg)
            log_file.write(error_msg)
            return 1, log_path


def run_on_both_branches(script_path, log_dir="logs"):
    """Run tests on both master and origin branches, then switch back to original branch.

    Args:
        script_path: Script path to run
        log_dir: Log directory
    """
    original_branch = get_git_branch()
    print(f"Current branch: {original_branch}")

    # First stash uncommitted changes
    stashed = git_stash()

    master_log = None
    origin_log = None

    try:
        # 1. Switch to master branch and run tests
        print("\n" + "="*60)
        print("Step 1: Run tests on master branch")
        print("="*60)

        if not switch_branch("master"):
            print("Cannot switch to master branch, aborting tests")
            return

        if not pip_install():
            print("pip install failed, continuing to run tests...")

        return_code1, master_log = run_with_logging(script_path, log_dir, "master")
        print(f"Master branch test completed, return code: {return_code1}")

        # 2. Switch to origin branch and run tests
        print("\n" + "="*60)
        print("Step 2: Run tests on origin branch")
        print("="*60)

        if not switch_branch("origin"):
            print("Cannot switch to origin branch, aborting tests")
            # Try to switch back to original branch
            switch_branch(original_branch)
            return

        if not pip_install():
            print("pip install failed, continuing to run tests...")

        return_code2, origin_log = run_with_logging(script_path, log_dir, "origin")
        print(f"Origin branch test completed, return code: {return_code2}")

        # 3. Output log file paths
        print("\n" + "="*60)
        print("Tests completed, log files:")
        print("="*60)
        if master_log:
            print(f"  Master: {master_log}")
        if origin_log:
            print(f"  Origin: {origin_log}")

    finally:
        # Switch back to original branch
        print(f"\nSwitching back to original branch: {original_branch}")
        if not switch_branch(original_branch):
            print("Warning: Failed to switch back to original branch, please handle manually!")

        # Reinstall original branch code
        print("\nReinstalling original branch code...")
        if not pip_install():
            print("Warning: pip install failed, please check manually!")

        # Restore stashed changes
        if stashed:
            restore_ok = git_stash_pop()
            if not restore_ok:
                print("\n" + "="*60)
                print("Warning: Stash restore may have failed or is incomplete!")
                print("Please check current working directory status, if necessary manually run:")
                print("  git stash list      # View pending stashes")
                print("  git stash show      # View stash contents")
                print("  git stash apply     # Manually apply stash")
                print("="*60)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Run test files and save output to log file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run only on current branch
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py

    # Run on both branches and compare
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py --both
        """
    )

    parser.add_argument(
        "script_path",
        nargs="?",
        default="tests/strategies/test_02_multi_extend_data.py",
        help="Path to test script to run"
    )

    parser.add_argument(
        "--both",
        action="store_true",
        help="Run tests on both master and origin branches and compare results"
    )

    args = parser.parse_args()

    # Check if script exists
    if not os.path.exists(args.script_path):
        print(f"Error: Script file does not exist: {args.script_path}")
        sys.exit(1)

    if args.both:
        # Run on both branches and compare
        run_on_both_branches(args.script_path)
    else:
        # Run only on current branch
        # First execute pip install
        if not pip_install():
            print("pip install failed, continuing to run tests...")

        return_code, _ = run_with_logging(args.script_path)
        sys.exit(return_code)


if __name__ == "__main__":
    main()
