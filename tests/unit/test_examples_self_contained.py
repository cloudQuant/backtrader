"""Repository-wide self-containment contract for ``examples/<folder>``.

Every example folder must run after being copied out of the repository, so it
may import only the standard library, installed distributions, and modules that
live inside that same folder.  Importing ``examples.*`` (the examples root),
a sibling example folder, or ``tests.*`` is a violation.

Shared *code* is kept local by byte-identical copies; the drift guard below fails
the moment either side changes.  The 012_x candidates additionally carry a
folder-local admission manifest, which
``scripts/refresh_cross_exchange_local_manifests.py --check`` keeps in sync with
that folder's own sources.

Data fixtures are deliberately *not* covered: some examples legitimately read a
large repository fixture (for example ``tests/datas/bond_merged_all_data.csv``),
and duplicating those files into every folder is worse than the shared read.
This contract therefore proves code independence only; a copied folder may still
need the repository's data files at run time.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
STDLIB = set(sys.stdlib_module_names)
NON_EXAMPLE_DIRS = frozenset({"logs", "output", "state"})

# Byte-identical copies of shared support code, keyed by the canonical source.
VENDORED_COPIES = {
    EXAMPLES
    / "013_1_midfreq_cross_arbitrage"
    / "ctp_example_support.py": (EXAMPLES / "007_ctp" / "ctp_example_support.py"),
    EXAMPLES
    / "013_2_highfreq_calendar_arbitrage"
    / "ctp_example_support.py": (EXAMPLES / "007_ctp" / "ctp_example_support.py"),
    EXAMPLES
    / "010_live_examples"
    / "fake_btapi.py": (ROOT / "tests" / "fixtures" / "fake_btapi.py"),
    EXAMPLES
    / "012_1_midfreq_cross_exchange"
    / "strategy_candidate_approval.py": (EXAMPLES / "strategy_candidate_approval.py"),
    EXAMPLES
    / "012_2_event_driven_cross_exchange"
    / "strategy_candidate_approval.py": (EXAMPLES / "strategy_candidate_approval.py"),
    EXAMPLES
    / "012_1_midfreq_cross_exchange"
    / "demo-approval-trust-root.pem": (EXAMPLES / "demo-approval-trust-root.pem"),
    EXAMPLES
    / "012_2_event_driven_cross_exchange"
    / "demo-approval-trust-root.pem": (EXAMPLES / "demo-approval-trust-root.pem"),
}


LOCAL_MANIFEST_REFRESH_SCRIPT = ROOT / "scripts" / "refresh_cross_exchange_local_manifests.py"


def _example_folders() -> list[Path]:
    """Every directory under ``examples/`` that ships runnable Python."""

    return sorted(
        path
        for path in EXAMPLES.iterdir()
        if path.is_dir()
        and not path.name.startswith(("__", "."))
        and path.name not in NON_EXAMPLE_DIRS
        and any(path.rglob("*.py"))
    )


def _local_modules(folder: Path) -> set[str]:
    names = {path.stem for path in folder.rglob("*.py")}
    for child in folder.rglob("*"):
        if child.is_dir() and (child / "__init__.py").exists():
            names.add(child.name)
    return names


def _imported_top_levels(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - a broken example is its own failure
        pytest.fail(f"{path} is not valid Python: {exc}")
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.add(node.module.split(".")[0])
    return names


def _is_installed(name: str) -> bool:
    if name in STDLIB or name in {"backtrader", "bt_api_py", "bt_api_ctp"}:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # pragma: no cover - defensive
        return False


@pytest.mark.parametrize("folder", _example_folders(), ids=lambda path: path.name)
def test_example_folder_is_self_contained(folder: Path) -> None:
    local = _local_modules(folder)
    violations = []
    for path in sorted(folder.rglob("*.py")):
        for name in sorted(_imported_top_levels(path)):
            if name in local or _is_installed(name):
                continue
            violations.append(f"{path.relative_to(EXAMPLES)} imports {name!r}")
    assert violations == []


@pytest.mark.parametrize("copy", sorted(VENDORED_COPIES), ids=lambda path: path.name)
def test_vendored_support_copy_matches_its_canonical_source(copy: Path) -> None:
    canonical = VENDORED_COPIES[copy]
    assert canonical.is_file(), f"canonical source {canonical} is missing"
    assert copy.read_bytes() == canonical.read_bytes()


def test_local_admission_manifests_are_current() -> None:
    """The 012_x folder manifests must match their own sources."""

    result = subprocess.run(
        [sys.executable, str(LOCAL_MANIFEST_REFRESH_SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
