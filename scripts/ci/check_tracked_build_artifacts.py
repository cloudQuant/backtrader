"""Reject tracked Python build artifacts while allowing archived CI evidence."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# These are archived iteration 51 evidence payloads, not package build output.
# Keep the exceptions path-exact so similarly named artifacts remain rejected.
_ALLOWED_EVIDENCE_PATHS = frozenset(
    {
        "docs/_internal/opts/requirements/迭代51-因子流批一体与Alpha003-SimNow实盘示例/"
        "evidence/capacity87-corrected-rss-20261027/build/completion.json",
        "docs/_internal/opts/requirements/迭代51-因子流批一体与Alpha003-SimNow实盘示例/"
        "evidence/capacity87-corrected-rss-20261027/build/launch.json",
        "docs/_internal/opts/requirements/迭代51-因子流批一体与Alpha003-SimNow实盘示例/"
        "evidence/capacity87-corrected-rss-20261027/build/result.json",
    }
)

_BUILD_ARTIFACT_PATH = re.compile(r"(?:^|/)(?:build|dist)(?:/|$)|(?:^|/)[^/]+\.egg-info(?:/|$)")


def find_tracked_build_artifacts(paths: Iterable[str]) -> List[str]:
    """Return every tracked build artifact except the exact evidence payloads."""
    violations = []
    for path in paths:
        if path not in _ALLOWED_EVIDENCE_PATHS and _BUILD_ARTIFACT_PATH.search(path):
            violations.append(path)
    return violations


def read_tracked_paths(repository_root: Path = REPOSITORY_ROOT) -> List[str]:
    """Read Git's tracked path list without quoting or line-splitting paths."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(repository_root),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def main() -> int:
    try:
        tracked_paths = read_tracked_paths()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            "Could not inspect tracked files for build artifacts: " f"{exc}",
            file=sys.stderr,
        )
        return 2

    violations = find_tracked_build_artifacts(tracked_paths)
    if violations:
        print("Tracked build artifacts are not allowed:")
        print("\n".join(violations))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
