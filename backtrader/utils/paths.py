#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Checkout-relative path helpers for examples, tests and local tools.

``find_project_root`` answers one question only: which project directory holds
the ``backtrader`` package a caller belongs to. By default the caller is the
script that started the process, so an example resolves to the checkout its own
``run.py`` lives in. It walks the filesystem upwards, requires a project marker
beside the package, and never consults the current working directory or
``sys.path``, so neither an installed site-packages copy nor a second checkout
can answer for the one the caller lives in.

``data_path`` and ``read_data_from_csv`` address data inside that root, so an
example reads the repository fixture instead of keeping its own copy.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_MARKER = Path("backtrader") / "__init__.py"

# A checkout root is the directory that *holds* the package, not any directory
# that happens to contain a ``backtrader`` folder: an installed copy under
# site-packages has no project files beside it.
_PROJECT_MARKERS = (Path("pyproject.toml"), Path("setup.py"), Path(".git"))


def _is_project_root(candidate: Path) -> bool:
    if not (candidate / _PACKAGE_MARKER).is_file():
        return False
    return any((candidate / marker).exists() for marker in _PROJECT_MARKERS)


def _running_script():
    """Return the entrypoint script path, or None outside a script run."""

    main = sys.modules.get("__main__")
    argv = sys.argv or [""]
    for value in (getattr(main, "__file__", None), argv[0]):
        if value and value != "-c" and Path(value).suffix == ".py":
            return Path(value)
    return None


def find_project_root(start=None):
    """Return the absolute project root that contains a ``backtrader`` package.

    Args:
        start: File or directory to search from. Defaults to the running script,
            which pins the answer to the checkout that script lives in
            regardless of which ``backtrader`` was imported. Falls back to this
            module when there is no script entrypoint (REPL, notebook, pytest).

    Returns:
        Path: the nearest ancestor of ``start`` that holds both
        ``backtrader/__init__.py`` and a project marker file.

    Raises:
        RuntimeError: if no ancestor is such a project root, e.g. when the caller
            was copied out of a checkout or only an installed package is visible.
    """

    origin = Path(start) if start is not None else (_running_script() or Path(__file__))
    origin = origin.resolve()
    for candidate in (origin, *origin.parents):
        if _is_project_root(candidate):
            return candidate

    raise RuntimeError("no project root containing %s found above %s" % (_PACKAGE_MARKER, origin))


def data_path(relative_path, root=None):
    """Return the absolute path of a file or directory inside the project root.

    Args:
        relative_path: Path inside the project root, such as
            ``tests/datas/2006-day-001.txt``. Absolute paths are rejected.
        root: Project root to resolve against. Defaults to ``find_project_root()``;
            callers that already computed it pass it in to skip the walk.

    Returns:
        Path: the resolved location, which is guaranteed to exist.

    Raises:
        ValueError: if ``relative_path`` is absolute or resolves outside ``root``.
        FileNotFoundError: if the resolved location does not exist.
    """

    base = find_project_root() if root is None else Path(root).resolve()
    supplied = Path(relative_path).expanduser()
    if supplied.is_absolute():
        raise ValueError("expected a root-relative path, got %s" % supplied)

    path = (base / supplied).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ValueError("path escapes the project root %s: %s" % (base, relative_path)) from exc

    if not path.exists():
        raise FileNotFoundError("data path not found: %s (project root: %s)" % (path, base))

    return path


def read_data_from_csv(relative_path, root=None, **read_csv_kwargs):
    """Read a CSV addressed relative to the project root into a DataFrame.

    Args:
        relative_path: Path inside the project root, such as
            ``tests/datas/113013.csv``. Absolute paths are rejected.
        root: Project root to resolve against. Defaults to ``find_project_root()``.
        **read_csv_kwargs: Forwarded to ``pandas.read_csv`` (``sep``, ``encoding``,
            ``dtype``, ``parse_dates``, ``usecols``, ...). Nothing is guessed.

    Returns:
        pandas.DataFrame with the raw file contents, unparsed and unsorted.

    Raises:
        ValueError: if ``relative_path`` is absolute or resolves outside ``root``.
        FileNotFoundError: if the resolved file does not exist.
    """

    import pandas as pd

    path = data_path(relative_path, root=root)
    if not path.is_file():
        raise FileNotFoundError("data file not found: %s" % path)

    return pd.read_csv(path, **read_csv_kwargs)
