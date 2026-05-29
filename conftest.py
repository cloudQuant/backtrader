"""
Pytest configuration file for Backtrader tests.

Handles:
1. Cleanup of temp directories to avoid permission issues on Windows.
2. Optional switch to make `import backtrader` resolve to the installed
   site-packages copy instead of the local repository copy.

Default behaviour
-----------------
Running ``pytest`` from the repository root resolves ``import backtrader``
to the local repository's ``backtrader/`` directory (because Python places
the cwd at the front of ``sys.path``). This is what you want during
development.

Forcing the installed copy
--------------------------
Sometimes you want to run the test suite against the installed package
(for example, smoke-testing a wheel that was just installed). Either:

- Set the environment variable ``BACKTRADER_USE_INSTALLED=1``, or
- Pass ``--use-installed-backtrader`` on the pytest command line.

When activated, the local ``backtrader/`` directory is removed from
``sys.path`` BEFORE pytest collects any test, so the first ``import
backtrader`` resolves to ``site-packages/backtrader``.

Note: in either case, the test code itself does not change. The active
package is reported once at session start so you can confirm the source.
"""
from __future__ import annotations

import glob
import os
import shutil
import stat
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent
_LOCAL_BACKTRADER = _REPO_ROOT / "backtrader"


def remove_readonly(func, path, excinfo):
    """Error handler for shutil.rmtree to handle read-only files on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _should_use_installed(config) -> bool:
    """Return True if the user asked us to resolve backtrader from site-packages."""
    if os.environ.get("BACKTRADER_USE_INSTALLED", "").strip() in {"1", "true", "TRUE", "yes"}:
        return True
    return bool(getattr(config.option, "use_installed_backtrader", False))


def _strip_local_backtrader_from_path() -> list[str]:
    """Remove every sys.path entry that would shadow the installed backtrader.

    Returns the list of paths that were removed (for diagnostic logging).
    """
    repo_root_str = str(_REPO_ROOT)
    removed: list[str] = []
    new_path = []
    for entry in sys.path:
        # Treat the empty string as "current directory" — pytest inserts it
        # when invoked from the repo root.
        normalized = os.path.realpath(entry) if entry else os.path.realpath(os.getcwd())
        if normalized == os.path.realpath(repo_root_str):
            removed.append(entry)
            continue
        new_path.append(entry)
    sys.path[:] = new_path

    # Also evict any half-imported repo-local backtrader from sys.modules so
    # the next ``import backtrader`` performs a fresh resolution.
    for name in list(sys.modules):
        module = sys.modules.get(name)
        if module is None:
            continue
        module_file = getattr(module, "__file__", None) or ""
        if module_file.startswith(str(_LOCAL_BACKTRADER)):
            sys.modules.pop(name, None)
    return removed


def pytest_addoption(parser):
    parser.addoption(
        "--use-installed-backtrader",
        action="store_true",
        default=False,
        help="Resolve `import backtrader` against the installed site-packages "
             "copy instead of the local repository copy. Equivalent to "
             "BACKTRADER_USE_INSTALLED=1.",
    )


def pytest_configure(config):
    """Clean up old pytest temp directories and optionally pin backtrader resolution.

    IMPORTANT: Skip cleanup when running as an xdist worker to avoid deleting
    temp directories that other workers or the controller are actively using.
    """
    if _should_use_installed(config):
        removed = _strip_local_backtrader_from_path()
        # Confirm the resolution by importing once now and recording the path
        # for later display once the terminal reporter is ready.
        try:
            import importlib

            backtrader = importlib.import_module("backtrader")
            origin = getattr(backtrader, "__file__", "<unknown>")
        except Exception as exc:  # pragma: no cover - diagnostic only
            origin = f"<failed: {exc!r}>"
        config._backtrader_resolution_msg = (
            f"[backtrader] forced installed copy. removed paths={removed!r} "
            f"resolved __file__={origin}"
        )

    # Skip cleanup on xdist workers — only the controller should clean up
    if hasattr(config, "workerinput"):
        return

    root_dir = str(_REPO_ROOT)
    for pattern in [".pytest_tmp_*", ".pytest_tmp"]:
        for path in glob.glob(os.path.join(root_dir, pattern)):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, onerror=remove_readonly)
            except Exception:
                pass


def pytest_report_header(config):
    """Show which backtrader copy is being used at session start."""
    msg = getattr(config, "_backtrader_resolution_msg", None)
    if msg:
        return msg
    try:
        import backtrader

        return f"backtrader: {getattr(backtrader, '__file__', '<unknown>')}"
    except Exception:
        return None
