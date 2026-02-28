"""
Pytest configuration file for Backtrader tests.
Handles cleanup of temp directories to avoid permission issues on Windows.
"""
import os
import shutil
import tempfile
import stat
import glob


def remove_readonly(func, path, excinfo):
    """Error handler for shutil.rmtree to handle read-only files on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def pytest_configure(config):
    """Clean up old pytest temp directories before running tests.
    
    This fixes the PermissionError on Windows when running with pytest-xdist (-n flag).
    
    IMPORTANT: Skip cleanup when running as an xdist worker to avoid deleting
    temp directories that other workers or the controller are actively using.
    """
    # Skip cleanup on xdist workers — only the controller should clean up
    if hasattr(config, 'workerinput'):
        return

    # Get the project root directory
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Clean up old timestamped pytest_tmp directories
    for pattern in ['.pytest_tmp_*', '.pytest_tmp']:
        for path in glob.glob(os.path.join(root_dir, pattern)):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, onerror=remove_readonly)
            except Exception:
                pass
