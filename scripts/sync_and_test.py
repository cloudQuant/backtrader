#!/usr/bin/env python
"""
Sync test files to master branch and run tests on both branches.

Core improvements:
1. No git commit needed to sync files - directly copy file content
2. Use PYTHONPATH to run tests - ensures using current working directory code instead of pip-installed version
3. Automatically run tests on master and origin branches and output logs

Usage:
    python sync_and_test.py <test_file_path>

Example:
    python sync_and_test.py tests/strategies/test_120_data_replay_macd.py
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
    """Get git repository root directory."""
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
    """Get current git branch name."""
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
    """Switch git branch, using --force to ignore uncommitted changes."""
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

    Args:
        script_path: Test script path
        branch_name: Branch name (used for log filename)
        log_dir: Log directory

    Returns:
        tuple: (return_code, log_path)
    """
    git_root = get_git_root()

    # Create log directory
    log_dir_path = os.path.join(git_root, log_dir)
    if not os.path.exists(log_dir_path):
        os.makedirs(log_dir_path)

    # Generate log filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_name = os.path.splitext(os.path.basename(script_path))[0]
    log_filename = f"{script_name}_{branch_name}_{timestamp}.log"
    log_path = os.path.join(log_dir_path, log_filename)

    # Clean up old logs for same branch
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

    # Set environment variable to use current directory code
    env = os.environ.copy()
    env["PYTHONPATH"] = git_root
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    # Open log file
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"{'='*60}\n")
        log_file.write(f"Test script: {script_path}\n")
        log_file.write(f"Git branch: {branch_name}\n")
        log_file.write(f"PYTHONPATH: {git_root}\n")
        log_file.write(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.write(f"{'='*60}\n\n")
        log_file.flush()

        try:
            # Run test script
            process = subprocess.Popen(
                [sys.executable, "-u", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=0,
                env=env,
                cwd=git_root
            )

            # Real-time output and write to log
            output, _ = process.communicate()
            print(output, end="")
            log_file.write(output)
            log_file.flush()

            return_code = process.returncode

            # Write end information
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

    # Read test file content into memory
    print(f"\nReading test file content...")
    with open(abs_test_path, 'rb') as f:
        test_file_content = f.read()
    print(f"  File size: {len(test_file_content)} bytes")

    # Also save all modified files on current branch (for restoration)
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

        # Copy test file to master
        target_path = os.path.join(git_root, rel_test_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'wb') as f:
            f.write(test_file_content)
        print(f"Copied test file to master: {rel_test_path}")

        # Run test
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

        # Copy test file to origin
        target_path = os.path.join(git_root, rel_test_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'wb') as f:
            f.write(test_file_content)
        print(f"Copied test file to origin: {rel_test_path}")

        # Run test
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
        print(f"  Master return code: {return_code1} {'✓ Pass' if return_code1 == 0 else '✗ Fail'}")
        print(f"  Origin return code: {return_code2} {'✓ Pass' if return_code2 == 0 else '✗ Fail'}")

        return True

    finally:
        # ========== Restore original state ==========
        print(f"\n{'='*60}")
        print(f"Restoring original state, switching back to branch: {original_branch}")
        print(f"{'='*60}")

        if not switch_branch(original_branch):
            print("Warning: Failed to switch back to original branch!")

        # Restore modified files
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
