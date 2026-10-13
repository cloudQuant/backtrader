"""Iteration 43 R6: the three-class layout is a contract, not a convention.

Nothing here runs an example.  These checks pin the *shape* that rounds R1-R7
established, so a later contribution cannot quietly put a live example in
``backtest/``, import ``examples._support`` from a folder that is supposed to be
portable, or drop a new script at the ``examples/`` root.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"

CATEGORIES = ("backtest", "live", "unified")
SUPPORT_DIRS = {"_support", "data", "output", "logs", "__pycache__", "test_results"}
# Registered loose files at the examples root.  New entries need a reason: the
# iteration-43 close-out keeps the root free of unclassified material.
REGISTERED_ROOT_FILES = {
    "README.md",
    "__init__.py",
    # Per-leaf ignore rules are part of the layout contract, so the file itself is registered.
    ".gitignore",
    "strategy-candidate-manifest.json",
    # Pending promotion of three example groups (three files), registered in examples/README.md.
    "cryptohftdata_sma.py",
    "mixed_mode_backtest.py",
    "premium_rate_crossover_strategy.py",
}
CATEGORY_DIRS = set(CATEGORIES)
# Tooling and rebuildable output may live in a hidden directory; the contract is
# that no *example* does, not that the physical tree is absolutely clean.
HIDDEN_DIR_PREFIX = "."


def _leaves(category: str) -> list[Path]:
    base = EXAMPLES / category
    return sorted(path for path in base.iterdir() if path.is_dir() and path.name not in SUPPORT_DIRS)


def test_examples_root_holds_only_categories_support_and_registered_files() -> None:
    offenders: list[str] = []
    for path in sorted(EXAMPLES.iterdir()):
        name = path.name
        if path.is_dir():
            if name not in CATEGORY_DIRS | SUPPORT_DIRS and not name.startswith(HIDDEN_DIR_PREFIX):
                offenders.append(f"directory {name}")
        elif name not in REGISTERED_ROOT_FILES:
            offenders.append(f"file {name}")
    assert not offenders, f"unexpected examples/ root content: {offenders}"


def test_categories_are_populated_and_not_nested() -> None:
    for category in CATEGORIES:
        assert (EXAMPLES / category).is_dir(), category
        assert _leaves(category), f"{category} has no leaf"
    for leaf in _leaves("backtest") + _leaves("unified"):
        assert leaf.parent.name in CATEGORY_DIRS, leaf
        assert not any(child.is_dir() and child.name in CATEGORY_DIRS for child in leaf.iterdir()), leaf
    live_children = _leaves("live")
    assert [path.name for path in live_children] == ["000_live_certification"], live_children


def test_live_suite_keeps_its_internal_topology() -> None:
    """The certification suites moved as a whole: cases and optional16 stay adjacent."""

    suite = EXAMPLES / "live" / "000_live_certification"
    assert (suite / "optional16").is_dir(), "optional16 must not be split out of the suite"
    for venue in ("binance_penetration", "okx_penetration", "simnow_penetration"):
        cases = suite / venue / "cases"
        assert cases.is_dir(), venue
        counted = [path for path in cases.iterdir() if path.is_dir()]
        assert len(counted) == 33, f"{venue}: {len(counted)} case directories, expected 33"


@pytest.mark.parametrize("leaf", [path.name for path in _leaves("unified")])
def test_unified_leaf_with_an_entry_keeps_its_tier_contract(leaf: str) -> None:
    folder = EXAMPLES / "unified" / leaf
    if not (folder / "run.py").is_file():
        pytest.skip(f"{leaf} has no run.py tier entry")
    helper = folder / "entry_tier.py"
    assert helper.is_file(), f"{leaf} cannot resolve its own tier when copied out"
    canonical = EXAMPLES / "_support" / "entry_tier.py"
    assert hashlib.sha256(helper.read_bytes()).hexdigest() == hashlib.sha256(canonical.read_bytes()).hexdigest()
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert "运行层选择（迭代 43）" in readme, f"{leaf} README lacks the tier contract"
    assert "entry_tier" in readme and "`tier`" in readme, f"{leaf} README must separate entry_tier from tier"


def test_no_example_leaf_depends_on_the_repository_support_package() -> None:
    """``examples/_support`` is repository tooling, never a runtime dependency."""

    offenders: list[str] = []
    for category in CATEGORIES:
        for script in (EXAMPLES / category).rglob("*.py"):
            if any(part in SUPPORT_DIRS for part in script.parts):
                continue
            try:
                tree = ast.parse(script.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                module = getattr(node, "module", None) or (node.names[0].name if isinstance(node, ast.Import) else "")
                if module and ("examples._support" in module or module.startswith("examples.")):
                    offenders.append(f"{script.relative_to(ROOT)}: imports {module}")
    assert not offenders, offenders


def test_folder_local_data_copies_have_a_repository_original() -> None:
    """A leaf may carry a fixture only as a copy of a reviewed repository file."""

    for data_file in EXAMPLES.rglob("data/*"):
        if not data_file.is_file() or data_file.parent.parent == EXAMPLES:
            continue
        originals = (ROOT / "tests" / "datas" / data_file.name, EXAMPLES / "data" / data_file.name)
        if not any(original.is_file() for original in originals):
            # 002's synthesised fixtures are generated by the leaf itself.
            assert "002_hft_alignment_demo" in str(data_file), f"{data_file} has no reviewed original"


def test_no_credential_bearing_file_is_tracked_under_examples() -> None:
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "examples"],
        capture_output=True,
        text=True,
    )
    if listing.returncode != 0:
        pytest.skip("git is unavailable in this environment")
    names = [line.rsplit("/", 1)[-1].lower() for line in listing.stdout.splitlines()]
    assert ".env" not in names, "a .env file is tracked under examples/"
    assert not [name for name in names if "secrets" in name], "a secret file is tracked under examples/"
