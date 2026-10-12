"""Repository-wide self-containment contract for ``examples/<folder>``.

Every example folder must run after being copied out of the repository, so it
may import only the standard library, installed distributions, and modules that
live inside that same folder. The two repository framework packages are named
explicitly, separately from installed-package origin checks. Importing ``examples.*`` (the examples root),
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
import pkgutil
import site
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
NON_EXAMPLE_DIRS = frozenset({"logs", "output", "state", "_support", "data"})
# Iteration 43 groups examples by kind.  A category directory is a container,
# never an example: treating it as one would silently accept imports that cross
# between two examples that merely share a category.
CATEGORY_DIRS = frozenset({"backtest", "live", "unified"})
# ``sys.stdlib_module_names`` lists names for every supported platform. The
# fallback scan only sees the current platform, while examples import these
# process-lock modules conditionally for Windows and POSIX respectively.
PLATFORM_STDLIB_MODULES = frozenset({"fcntl", "msvcrt"})


def _stdlib_module_names() -> set[str]:
    """Return top-level stdlib modules on Python versions 3.8 and newer.

    ``sys.stdlib_module_names`` was added in Python 3.10.  On 3.8/3.9, scan
    the interpreter's standard-library and extension-module directories
    without traversing site-packages.
    """

    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return set(names)

    discovered = set(sys.builtin_module_names)
    paths = {
        sysconfig.get_path("stdlib"),
        sysconfig.get_path("platstdlib"),
        sysconfig.get_config_var("DESTSHARED"),
    }
    for path in sorted(path for path in paths if path):
        discovered.update(name for _finder, name, _ispkg in pkgutil.iter_modules([path]))
    return discovered | PLATFORM_STDLIB_MODULES


STDLIB = _stdlib_module_names()

# These packages are declared by their owning example folders but are not
# present in every source-QA environment. Keep exceptions scoped to those
# example leaves so they cannot hide imports in other examples.
OPTIONAL_EXAMPLE_MODULES = {
    "017_fnn_embedding": frozenset({"torch"}),
    # The cross-exchange demonstrations explicitly require the separately
    # maintained SDK package even for their offline/replay support code.
    "012_1_midfreq_cross_exchange": frozenset({"bt_api_py"}),
    "012_2_event_driven_cross_exchange": frozenset({"bt_api_py"}),
}

# Optional16 imports SDK packages lazily at these concrete optional-component
# boundaries. The transport implementation has a stdlib fallback; the
# components module only imports each SDK when its corresponding mount is on.
OPTIONAL_IMPORTS_BY_FILE = {
    "live/000_live_certification/optional16/components.py": frozenset(
        {"bt_api_execution", "bt_api_monitor", "bt_api_risk"}
    ),
    "live/000_live_certification/optional16/gateway_server.py": frozenset(
        {"bt_api_transport_zmq"}
    ),
}

# Backtrader and its configuration-first runtime are the framework packages
# supplied by this repository. They are allowed as project dependencies, but
# are deliberately not reported by _is_installed when find_spec resolves them
# back into this checkout.
PROJECT_FRAMEWORK_MODULES = frozenset({"backtrader", "backtrader_runtime"})
FORBIDDEN_TOP_LEVEL_MODULES = frozenset({"examples", "tests"})

# This module is in the standard library from Python 3.9 onward. The 013_3
# example catches ImportError and falls back to the declared core dependency
# pytz on Python 3.8, so only that folder may use the compatibility import.
COMPATIBILITY_STDLIB_MODULES = {
    "013_3_sa_midfreq_simnow": frozenset({"zoneinfo"}),
}

# Byte-identical copies of shared support code, keyed by the canonical source.
VENDORED_COPIES = {
    EXAMPLES
    / "unified"
    / "013_1_midfreq_cross_arbitrage"
    / "ctp_example_support.py": (EXAMPLES / "_support" / "ctp_legacy_example_support.py"),
    EXAMPLES
    / "unified"
    / "013_2_highfreq_calendar_arbitrage"
    / "ctp_example_support.py": (EXAMPLES / "_support" / "ctp_legacy_example_support.py"),
    EXAMPLES
    / "unified"
    / "013_1_midfreq_cross_arbitrage"
    / "simnow_direct.py": (EXAMPLES / "unified" / "013_3_sa_midfreq_simnow" / "simnow_direct.py"),
    EXAMPLES
    / "unified"
    / "013_2_highfreq_calendar_arbitrage"
    / "simnow_direct.py": (EXAMPLES / "unified" / "013_3_sa_midfreq_simnow" / "simnow_direct.py"),
    EXAMPLES
    / "unified"
    / "014_1_ctp_options_lowfreq"
    / "simnow_direct.py": (EXAMPLES / "unified" / "013_3_sa_midfreq_simnow" / "simnow_direct.py"),
    EXAMPLES
    / "unified"
    / "012_1_midfreq_cross_exchange"
    / "strategy_candidate_approval.py": (EXAMPLES / "_support" / "strategy_candidate_approval.py"),
    EXAMPLES
    / "unified"
    / "012_2_event_driven_cross_exchange"
    / "strategy_candidate_approval.py": (EXAMPLES / "_support" / "strategy_candidate_approval.py"),
    EXAMPLES
    / "unified"
    / "012_1_midfreq_cross_exchange"
    / "demo-approval-trust-root.pem": (EXAMPLES / "_support" / "demo-approval-trust-root.pem"),
    EXAMPLES
    / "unified"
    / "012_2_event_driven_cross_exchange"
    / "demo-approval-trust-root.pem": (EXAMPLES / "_support" / "demo-approval-trust-root.pem"),
    # Iteration 43 tier resolver: one canonical helper plus one copy per unified
    # example.  Registered by discovery below so a newly added example copy is
    # guarded without editing this table.
}

for _tier_copy in sorted((EXAMPLES / "unified").glob("*/entry_tier.py")):
    VENDORED_COPIES[_tier_copy] = EXAMPLES / "_support" / "entry_tier.py"

# Iteration 43 R7: a leaf that carries a small fixture ships a byte-identical copy
# of the repository original, discovered here so a new folder-local fixture is
# guarded without editing this table.  Generated fixtures with no repository
# original (for example 002's synthesised order books) are the leaf's own product
# and stay outside this comparison.
for _data_copy in sorted(EXAMPLES.rglob("data/*")):
    if not _data_copy.is_file() or _data_copy.parent.parent == EXAMPLES:
        continue
    for _candidate in (ROOT / "tests" / "datas" / _data_copy.name, EXAMPLES / "data" / _data_copy.name):
        if _candidate.is_file():
            VENDORED_COPIES[_data_copy] = _candidate
            break


LOCAL_MANIFEST_REFRESH_SCRIPT = ROOT / "scripts" / "refresh_cross_exchange_local_manifests.py"


def _is_example_leaf(path: Path) -> bool:
    return (
        path.is_dir()
        and not path.name.startswith(("__", "."))
        and path.name not in NON_EXAMPLE_DIRS
        and any(path.rglob("*.py"))
    )


def _example_folders() -> list[Path]:
    """Every leaf example directory, at ``examples/<name>`` or ``examples/<category>/<name>``."""

    folders: list[Path] = []
    for path in EXAMPLES.iterdir():
        if path.name in CATEGORY_DIRS and path.is_dir():
            folders.extend(child for child in path.iterdir() if _is_example_leaf(child))
        elif _is_example_leaf(path):
            folders.append(path)
    return sorted(folders)


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
    """Return whether a module resolves to an installed site-package origin.

    ``find_spec`` also finds modules in this checkout, sibling development
    checkouts, editable installs, and namespace packages. None of those facts
    alone means the dependency will exist when an example folder is copied.
    """

    if name in STDLIB:
        return True
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError, ModuleNotFoundError):  # pragma: no cover - defensive
        return False
    origin = getattr(spec, "origin", None)
    if not isinstance(origin, str) or not origin or origin in {"built-in", "frozen"}:
        # Namespace packages have search locations but no concrete installed
        # payload, so they do not satisfy this copied-folder contract.
        return False
    try:
        source = Path(origin).resolve()
    except (OSError, RuntimeError, ValueError):  # pragma: no cover - defensive
        return False
    if _is_within(source, ROOT):
        return False

    roots = set()
    configured = sysconfig.get_paths()
    for key in ("purelib", "platlib"):
        value = configured.get(key)
        if value:
            roots.add(Path(value))
    try:
        roots.update(Path(value) for value in site.getsitepackages() if value)
        user_site = site.getusersitepackages()
        if user_site:
            roots.add(Path(user_site))
    except (AttributeError, OSError, TypeError):  # pragma: no cover - platform-specific
        pass
    return any(_is_within(source, root) for root in roots)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


@pytest.mark.parametrize("folder", _example_folders(), ids=lambda path: path.name)
def test_example_folder_is_self_contained(folder: Path) -> None:
    assert _example_import_violations(folder) == []


def _example_import_violations(folder: Path) -> list[str]:
    """Return imports that are neither local, installed, nor declared compatible."""

    local = _local_modules(folder)
    optional = OPTIONAL_EXAMPLE_MODULES.get(folder.name, frozenset())
    compatibility_stdlib = COMPATIBILITY_STDLIB_MODULES.get(folder.name, frozenset())
    violations = []
    for path in sorted(folder.rglob("*.py")):
        path_optional = OPTIONAL_IMPORTS_BY_FILE.get(
            path.relative_to(EXAMPLES).as_posix(), frozenset()
        )
        for name in sorted(_imported_top_levels(path)):
            if name in FORBIDDEN_TOP_LEVEL_MODULES:
                violations.append(f"{path.relative_to(EXAMPLES).as_posix()} imports {name!r}")
                continue
            if (
                name in local
                or name in optional
                or name in path_optional
                or name in PROJECT_FRAMEWORK_MODULES
                or name in compatibility_stdlib
                or _is_installed(name)
            ):
                continue
            violations.append(f"{path.relative_to(EXAMPLES).as_posix()} imports {name!r}")
    return violations


def test_zoneinfo_compatibility_import_is_folder_scoped(tmp_path: Path, monkeypatch) -> None:
    """The Python 3.8 fallback must not excuse a missing import elsewhere."""

    original_is_installed = _is_installed
    compatibility_folder = EXAMPLES / "unified" / "013_3_sa_midfreq_simnow"
    monkeypatch.setattr(
        sys.modules[__name__],
        "_is_installed",
        lambda name: False if name == "zoneinfo" else original_is_installed(name),
    )
    assert _example_import_violations(compatibility_folder) == []

    folder = tmp_path / "unrelated_example"
    folder.mkdir()
    (folder / "example.py").write_text("import zoneinfo\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "EXAMPLES", tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "_is_installed", lambda _name: False)

    assert _example_import_violations(folder) == ["unrelated_example/example.py imports 'zoneinfo'"]


def test_category_directory_is_not_treated_as_one_example(tmp_path: Path, monkeypatch) -> None:
    """Two sibling leaves in one category must not accept each other's modules."""

    category = tmp_path / "backtest"
    (category / "first").mkdir(parents=True)
    (category / "second").mkdir()
    (category / "first" / "entry.py").write_text("import second_helper\n", encoding="utf-8")
    (category / "second" / "second_helper.py").write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(sys.modules[__name__], "EXAMPLES", tmp_path)
    assert _example_folders() == [category / "first", category / "second"]

    entry = category / "first" / "entry.py"
    violations = _example_import_violations(category / "first")
    assert violations == [f"{entry.relative_to(tmp_path).as_posix()} imports 'second_helper'"]


@pytest.mark.parametrize("name", ("examples", "tests"))
def test_examples_and_tests_imports_cannot_be_masked_by_local_files(
    name: str, tmp_path: Path, monkeypatch
) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / f"{name}.py").write_text("VALUE = 1\n", encoding="utf-8")
    entry = folder / "entry.py"
    entry.write_text(f"import {name}\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "EXAMPLES", tmp_path)
    # This simulates a machine where an unrelated same-named package can be
    # found; repository-only roots remain forbidden regardless of that result.
    monkeypatch.setattr(sys.modules[__name__], "_is_installed", lambda _module: True)
    assert _example_import_violations(folder) == [f"example/entry.py imports '{name}'"]


@pytest.mark.parametrize(
    "origin_kind",
    ("repository", "examples", "tests", "namespace", "editable"),
)
def test_find_spec_is_not_treated_as_an_installed_origin(
    origin_kind: str, tmp_path: Path, monkeypatch
) -> None:
    """Repository and editable source roots cannot masquerade as installed packages."""

    site_packages = tmp_path / "site-packages"
    monkeypatch.setattr(
        sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_packages), "platlib": str(site_packages)},
    )
    monkeypatch.setattr(site, "getsitepackages", lambda: [str(site_packages)])
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(site_packages))

    if origin_kind == "repository":
        origin = ROOT / "backtrader" / "__init__.py"
        spec = type("Spec", (), {"origin": str(origin), "submodule_search_locations": None})()
    elif origin_kind == "examples":
        origin = EXAMPLES / "fixture_package" / "__init__.py"
        spec = type("Spec", (), {"origin": str(origin), "submodule_search_locations": None})()
    elif origin_kind == "tests":
        origin = ROOT / "tests" / "fixture_package.py"
        spec = type("Spec", (), {"origin": str(origin), "submodule_search_locations": None})()
    elif origin_kind == "namespace":
        spec = type(
            "Spec",
            (),
            {"origin": None, "submodule_search_locations": [str(site_packages / "namespace")]},
        )()
    else:
        origin = tmp_path / "editable-source" / "fixture_package.py"
        spec = type("Spec", (), {"origin": str(origin), "submodule_search_locations": None})()

    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: spec)
    assert _is_installed("fixture_package") is False


def test_site_packages_origin_is_installed(tmp_path: Path, monkeypatch) -> None:
    site_packages = tmp_path / "site-packages"
    origin = site_packages / "fixture_package" / "__init__.py"
    spec = type("Spec", (), {"origin": str(origin), "submodule_search_locations": None})()
    monkeypatch.setattr(
        sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_packages), "platlib": str(site_packages)},
    )
    monkeypatch.setattr(site, "getsitepackages", lambda: [str(site_packages)])
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(site_packages))
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: spec)
    assert _is_installed("fixture_package") is True


@pytest.mark.parametrize("name", ("backtrader", "bt_api_py"))
def test_repository_and_editable_framework_sources_are_not_installed(
    name: str, tmp_path: Path, monkeypatch
) -> None:
    origin = (
        ROOT / "backtrader" / "__init__.py"
        if name == "backtrader"
        else tmp_path / "editable-source" / "bt_api_py" / "__init__.py"
    )
    spec = type("Spec", (), {"origin": str(origin), "submodule_search_locations": None})()
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: spec)
    assert _is_installed(name) is False


def test_optional16_sdk_import_allowlist_tracks_actual_lazy_boundaries(
    tmp_path: Path, monkeypatch
) -> None:
    """Only the component and transport fallback files may need these SDK packages."""

    monkeypatch.setattr(sys.modules[__name__], "EXAMPLES", tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "_is_installed", lambda _name: False)
    for relative, source in (
        (
            "live/000_live_certification/optional16/components.py",
            "import bt_api_execution\nimport bt_api_risk\nimport bt_api_monitor\n",
        ),
        (
            "live/000_live_certification/optional16/gateway_server.py",
            "import bt_api_transport_zmq\n",
        ),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        assert _example_import_violations(path.parent.parent) == []

    unrelated = tmp_path / "live" / "000_live_certification" / "optional16" / "unrelated.py"
    unrelated.write_text("import bt_api_risk\n", encoding="utf-8")
    assert _example_import_violations(unrelated.parent.parent) == [
        "live/000_live_certification/optional16/unrelated.py imports 'bt_api_risk'"
    ]


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
