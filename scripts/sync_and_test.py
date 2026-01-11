#!/usr/bin/env python
"""Sync test files to master branch and run tests on both branches.

This script automates the process of syncing a test file from the current
branch to both master and origin branches, running tests on each, and
comparing results. It handles git branch switching, file copying, test
execution, and log management.

Core improvements:
1. No git commit needed - directly copies file content between branches
2. Uses PYTHONPATH to ensure tests run against current working directory code
   instead of pip-installed version
3. Automatically backs up and restores modified files
4. Executes pip install after branch switches to update environment

Example:
    >>> python sync_and_test.py tests/strategies/test_120_data_replay_macd.py

The script will:
1. Save current branch and test file content
2. Switch to master, copy test file, run test
3. Switch to origin, copy test file, run test
4. Switch back to original branch and restore files
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def get_git_root():
    """Get git repository root directory.

    Uses 'git rev-parse --show-toplevel' to find the repository root.
    Falls back to current working directory if git command fails.

    Returns:
        str: Absolute path to git repository root directory.

    Example:
        >>> root = get_git_root()
        >>> print(root)
        /Users/user/project
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return os.getcwd()


def get_git_branch():
    """Get current git branch name.

    Attempts to get branch name using 'git branch --show-toplevel'.
    Falls back to 'git rev-parse --abbrev-ref HEAD' if first command fails.
    Returns 'unknown' if both commands fail.

    Returns:
        str: Current branch name, or 'unknown' if detection fails.

    Example:
        >>> branch = get_git_branch()
        >>> print(branch)
        development
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True
        )
        branch = result.stdout.strip()
        if not branch:
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


def switch_branch(branch_name):
    """Switch git branch, using force to ignore uncommitted changes.

    Switches to the specified branch using 'git checkout --force' which
    discards local changes. After switching, runs 'pip install -U .' to
    update the environment with the new branch's code.

    Args:
        branch_name (str): Name of branch to switch to.

    Returns:
        bool: True if branch switch succeeded, False otherwise.

    Example:
        >>> success = switch_branch("master")
        >>> if success:
        ...     print("Switched to master")
    """
    print(f"\n{'='*60}")
    print(f"Switching to branch: {branch_name}")
    print(f"{'='*60}")

    try:
        # Use git checkout --force to force switch, ignoring working directory changes
        result = subprocess.run(
            ["git", "checkout", "--force", branch_name],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"Successfully switched to branch: {branch_name}")

        # After switching branch, execute pip install -U . to install current branch code
        print(f"Executing pip install -U . to install current branch code...")
        install_result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "."],
            capture_output=True,
            text=True,
            cwd=get_git_root()
        )
        if install_result.returncode == 0:
            print(f"pip install successful")
        else:
            print(f"pip install failed: {install_result.stderr}")

        return True
    except subprocess.CalledProcessError as e:
        print(f"Operation failed: {e.stderr if e.stderr else str(e)}")
        return False


def run_test_with_pythonpath(script_path, branch_name, log_dir="logs"):
    """Run tests using PYTHONPATH, ensuring current working directory code is used.

    Sets PYTHONPATH to git root to ensure tests import from the current
    working directory instead of any pip-installed version. Captures output
    to log files with timestamps.

    Args:
        script_path (str): Path to test script to run.
        branch_name (str): Branch name used for log filename.
        log_dir (str, optional): Directory for log files. Defaults to "logs".

    Returns:
        tuple: (return_code, log_path) where:
            - return_code (int): Exit code from test execution (0=success)
            - log_path (str): Path to log file with test output

    Example:
        >>> code, log = run_test_with_pythonpath("test_file.py", "master")
        >>> if code == 0:
        ...     print("Test passed")
    """
    git_root = get_git_root()

    # Create log directory if it doesn't exist
    log_dir_path = os.path.join(git_root, log_dir)
    if not os.path.exists(log_dir_path):
        os.makedirs(log_dir_path)

    # Generate unique log filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_name = os.path.splitext(os.path.basename(script_path))[0]
    log_filename = f"{script_name}_{branch_name}_{timestamp}.log"
    log_path = os.path.join(log_dir_path, log_filename)

    # Clean up old logs for same branch to avoid clutter
    import glob
    pattern = os.path.join(log_dir_path, f"{script_name}_{branch_name}_*.log")
    for old_log in glob.glob(pattern):
        try:
            os.remove(old_log)
            print(f"  Deleted old log: {os.path.basename(old_log)}")
        except Exception:
            pass

    print(f"\n{'='*60}")
    print(f"Running test: {script_path}")
    print(f"Branch: {branch_name}")
    print(f"Log: {log_path}")
    print(f"PYTHONPATH: {git_root}")
    print(f"{'='*60}\n")

    # Set environment variables to control Python execution
    env = os.environ.copy()
    env["PYTHONPATH"] = git_root  # Import from working directory, not pip install
    env["PYTHONUNBUFFERED"] = "1"  # Disable output buffering for real-time logs
    env["PYTHONIOENCODING"] = "utf-8"  # Ensure UTF-8 encoding

    # Open log file and write header
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"{'='*60}\n")
        log_file.write(f"Test script: {script_path}\n")
        log_file.write(f"Git branch: {branch_name}\n")
        log_file.write(f"PYTHONPATH: {git_root}\n")
        log_file.write(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.write(f"{'='*60}\n\n")
        log_file.flush()

        try:
            # Run test script with unbuffered output
            process = subprocess.Popen(
                [sys.executable, "-u", script_path],  # -u for unbuffered output
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Combine stderr with stdout
                text=True,
                encoding="utf-8",
                errors="replace",  # Handle encoding errors gracefully
                bufsize=0,
                env=env,
                cwd=git_root
            )

            # Real-time output to console and log file
            output, _ = process.communicate()
            print(output, end="")
            log_file.write(output)
            log_file.flush()

            return_code = process.returncode

            # Write completion information to log
            end_msg = f"\n{'='*60}\n"
            end_msg += f"Test completed\n"
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


def sync_and_test(test_file_path):
    """Sync test file to master branch and run tests on both branches.

    Process:
    1. Save current branch name and test file content
    2. Switch to master branch
    3. Copy test file to master
    4. Run test on master
    5. Switch to origin branch
    6. Copy test file to origin
    7. Run test on origin
    8. Switch back to original branch and restore files

    Args:
        test_file_path (str): Path to test file (relative or absolute).

    Returns:
        bool: True if process completed successfully, False otherwise.

    Example:
        >>> success = sync_and_test("tests/strategies/test_my_strategy.py")
        >>> if success:
        ...     print("Sync and test completed")
    """
    git_root = get_git_root()
    original_branch = get_git_branch()

    print(f"{'='*60}")
    print(f"Sync and test: {test_file_path}")
    print(f"Current branch: {original_branch}")
    print(f"Git root: {git_root}")
    print(f"{'='*60}")

    # Get absolute and relative paths of test file
    if os.path.isabs(test_file_path):
        abs_test_path = test_file_path
        rel_test_path = os.path.relpath(test_file_path, git_root)
    else:
        abs_test_path = os.path.join(git_root, test_file_path)
        rel_test_path = test_file_path

    # Check if file exists
    if not os.path.exists(abs_test_path):
        print(f"Error: Test file does not exist: {abs_test_path}")
        return False

    # Read test file content into memory (avoids git commit)
    print(f"\nReading test file content...")
    with open(abs_test_path, 'rb') as f:
        test_file_content = f.read()
    print(f"  File size: {len(test_file_content)} bytes")

    # Also save all modified files on current branch (for restoration after branch switches)
    modified_files = {}
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
            cwd=git_root
        )
        for rel_path in result.stdout.strip().split('\n'):
            if rel_path:
                full_path = os.path.join(git_root, rel_path)
                if os.path.exists(full_path):
                    with open(full_path, 'rb') as f:
                        modified_files[rel_path] = f.read()
                    print(f"  Backed up modified file: {rel_path}")
    except Exception as e:
        print(f"  Error backing up modified files: {e}")

    master_log = None
    origin_log = None

    try:
        # ========== Test on master branch ==========
        print("\n" + "="*60)
        print("Step 1: Run test on master branch")
        print("="*60)

        if not switch_branch("master"):
            print("Cannot switch to master branch")
            return False

        # Copy test file to master (direct file write, no git commit)
        target_path = os.path.join(git_root, rel_test_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'wb') as f:
            f.write(test_file_content)
        print(f"Copied test file to master: {rel_test_path}")

        # Run test on master branch
        return_code1, master_log = run_test_with_pythonpath(target_path, "master")
        print(f"Master branch test completed, return code: {return_code1}")

        # ========== Test on origin branch ==========
        print("\n" + "="*60)
        print("Step 2: Run test on origin branch")
        print("="*60)

        if not switch_branch("origin"):
            print("Cannot switch to origin branch")
            switch_branch(original_branch)
            return False

        # Copy test file to origin (direct file write, no git commit)
        target_path = os.path.join(git_root, rel_test_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'wb') as f:
            f.write(test_file_content)
        print(f"Copied test file to origin: {rel_test_path}")

        # Run test on origin branch
        return_code2, origin_log = run_test_with_pythonpath(target_path, "origin")
        print(f"Origin branch test completed, return code: {return_code2}")

        # ========== Output result summary ==========
        print("\n" + "="*60)
        print("Test completed! Log files:")
        print("="*60)
        if master_log:
            print(f"  Master: {master_log}")
        if origin_log:
            print(f"  Origin: {origin_log}")

        print("\nResult comparison:")
        print(f"  Master return code: {return_code1} {'PASS' if return_code1 == 0 else 'FAIL'}")
        print(f"  Origin return code: {return_code2} {'PASS' if return_code2 == 0 else 'FAIL'}")

        return True

    finally:
        # ========== Restore original state ==========
        print(f"\n{'='*60}")
        print(f"Restoring original state, switching back to branch: {original_branch}")
        print(f"{'='*60}")

        # Always try to switch back to original branch, even if errors occurred
        if not switch_branch(original_branch):
            print("Warning: Failed to switch back to original branch!")

        # Restore all modified files that were backed up
        for rel_path, content in modified_files.items():
            try:
                full_path = os.path.join(git_root, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'wb') as f:
                    f.write(content)
                print(f"  Restored: {rel_path}")
            except Exception as e:
                print(f"  Restore failed {rel_path}: {e}")

        print("\nCompleted!")


def main():
    """Main entry point for sync and test script.

    Parses command line arguments and initiates the sync and test process.
    Uses argparse to provide helpful usage information and examples.

    Returns:
        None

    Example:
        >>> # From command line
        >>> $ python sync_and_test.py tests/strategies/test_my_strategy.py
    """
    parser = argparse.ArgumentParser(
        description="Sync test file to master branch and run tests on both branches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Core improvements:
  - No git commit needed to sync - directly copy file content
  - Use PYTHONPATH to run tests - ensures using current working directory code
  - Automatically backup and restore modified files

Example:
    python sync_and_test.py tests/strategies/test_120_data_replay_macd.py
        """
    )

    parser.add_argument(
        "test_file",
        help="Path to test file to sync and test"
    )

    args = parser.parse_args()

    sync_and_test(args.test_file)


if __name__ == "__main__":
    main()
