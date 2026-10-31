"""Security regressions for reviewed SDK capability imports."""

from __future__ import annotations

import importlib
import importlib.machinery
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Iterator

import pytest

import backtrader_runtime.capability_imports as capability_imports
from backtrader_runtime.capability_imports import (
    trusted_capability_import_context,
    trusted_installed_capability_import_context,
)
from backtrader_runtime.errors import RuntimeConfigError


def _is_external_capability_module(name: object) -> bool:
    return isinstance(name, str) and name.split(".", 1)[0].startswith("bt_api_")


@contextmanager
def _isolated_capability_modules() -> Iterator[None]:
    """Keep this source-origin test independent of xdist worker SDK residue."""

    saved = {
        module_name: module
        for module_name, module in tuple(sys.modules.items())
        if _is_external_capability_module(module_name)
    }
    for module_name in saved:
        sys.modules.pop(module_name, None)
    try:
        yield
    finally:
        for module_name in tuple(sys.modules):
            if _is_external_capability_module(module_name):
                sys.modules.pop(module_name, None)
        sys.modules.update(saved)


def _top_level_origin(package_directory: Path) -> object:
    initializer = package_directory / "__init__.py"
    initializer.write_text("STATUS = 'trusted'\n", encoding="utf-8")
    return capability_imports._CapabilityOrigin(
        module_name="bt_api_risk",
        search_root=package_directory.parent,
        package_directory=package_directory,
        initializer=initializer,
        package_identity=capability_imports._PathIdentity.directory(package_directory),
        initializer_identity=capability_imports._PathIdentity.regular_file(initializer),
    )


def _namespace_spec(fullname: str, locations: object, loader: object = None) -> object:
    specification = importlib.machinery.ModuleSpec(fullname, loader=loader, is_package=True)
    specification.submodule_search_locations = locations
    return specification


def _write_capability_package(root: Path, name: str, status: str) -> Path:
    package = root / name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "STATUS = {0!r}\n".format(status),
        encoding="utf-8",
    )
    return package


def _patch_interpreter_install_root(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> None:
    monkeypatch.setattr(
        capability_imports.sysconfig,
        "get_paths",
        lambda: {"purelib": str(root), "platlib": str(root)},
    )


def test_captured_roots_allow_only_exact_interpreter_site_root_under_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An isolated venv below CWD is valid; arbitrary CWD children stay rejected."""

    cwd = tmp_path / "consumer"
    site_root = cwd / "venv" / "Lib" / "site-packages"
    untrusted_child = cwd / "injected"
    source_root = tmp_path / "reviewed-source"
    site_root.mkdir(parents=True)
    untrusted_child.mkdir(parents=True)
    source_root.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(
        capability_imports.sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_root), "platlib": str(site_root)},
    )
    monkeypatch.setattr(sys, "path", [str(site_root), str(untrusted_child)])

    roots = capability_imports._captured_non_cwd_search_roots(source_root)

    assert capability_imports._absolute_path(site_root) in roots
    assert capability_imports._absolute_path(untrusted_child) not in roots


def test_trusted_context_allows_one_concrete_namespace_child_below_pinned_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A data-only SDK folder without ``__init__.py`` stays on the pinned root."""

    trusted_root = tmp_path / "trusted-sdk"
    package = trusted_root / "bt_api_risk"
    namespace = package / "containers"
    namespace.mkdir(parents=True)
    (package / "__init__.py").write_text("STATUS = 'trusted'\n", encoding="utf-8")
    (namespace / "risk_events.py").write_text(
        "STATUS = 'trusted-namespace-child'\n", encoding="utf-8"
    )

    fake_cwd = tmp_path / "fake-cwd"
    fake_child = fake_cwd / "bt_api_risk" / "containers" / "risk_events.py"
    fake_child.parent.mkdir(parents=True)
    sentinel = tmp_path / "cwd-namespace-child-imported"
    fake_child.write_text(
        "from pathlib import Path\n"
        "Path({0!r}).write_text('imported', encoding='utf-8')\n".format(str(sentinel)),
        encoding="utf-8",
    )
    monkeypatch.chdir(fake_cwd)
    monkeypatch.syspath_prepend(str(fake_cwd))

    with _isolated_capability_modules(), trusted_capability_import_context(
        trusted_root, ("bt_api_risk",)
    ):
        child = importlib.import_module("bt_api_risk.containers.risk_events")
        namespace_module = sys.modules["bt_api_risk.containers"]

        assert child.STATUS == "trusted-namespace-child"
        assert getattr(namespace_module, "__file__", None) is None
        assert tuple(
            capability_imports._absolute_path(path) for path in namespace_module.__path__
        ) == (capability_imports._absolute_path(namespace),)

    assert not sentinel.exists()


def test_namespace_submodule_rejects_multiple_or_outside_paths(tmp_path: Path) -> None:
    """Namespace packages cannot merge paths or escape the pinned top-level package."""

    package = tmp_path / "bt_api_risk"
    package.mkdir()
    origin = _top_level_origin(package)
    namespace = package / "containers"
    namespace.mkdir()
    other_namespace = package / "other"
    other_namespace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    for locations in ((str(namespace), str(other_namespace)), (str(outside),)):
        specification = _namespace_spec("bt_api_risk.containers", locations)
        with pytest.raises(RuntimeConfigError) as caught:
            capability_imports._CapabilityOriginResolver._assert_submodule_specification(
                "bt_api_risk.containers", origin, specification
            )
        assert caught.value.reason == "capability_origin_mismatch"


def test_namespace_submodule_rejects_non_directory_and_executable_or_pseudo_specs(
    tmp_path: Path,
) -> None:
    """Only one real no-code PathFinder namespace spec can pass the narrow gate."""

    package = tmp_path / "bt_api_risk"
    package.mkdir()
    origin = _top_level_origin(package)
    namespace = package / "containers"
    namespace.mkdir()
    not_directory = package / "not-a-directory"
    not_directory.write_text("not a directory\n", encoding="utf-8")

    specifications = (
        _namespace_spec("bt_api_risk.containers", (str(not_directory),)),
        _namespace_spec("bt_api_risk.containers", (str(namespace),), loader=object()),
        SimpleNamespace(
            name="bt_api_risk.containers",
            origin=None,
            loader=None,
            submodule_search_locations=(str(namespace),),
        ),
    )
    for specification in specifications:
        with pytest.raises(RuntimeConfigError) as caught:
            capability_imports._CapabilityOriginResolver._assert_submodule_specification(
                "bt_api_risk.containers", origin, specification
            )
        assert caught.value.reason == "capability_origin_mismatch"


def test_strict_installed_context_loads_registered_capability_from_exact_purelib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    purelib = tmp_path / "interpreter" / "site-packages"
    package = _write_capability_package(purelib, "bt_api_ctp", "installed")
    (package / "ctp_env_selector.py").write_text("PROFILE = 'installed'\n", encoding="utf-8")
    _patch_interpreter_install_root(monkeypatch, purelib)
    monkeypatch.setattr(sys, "path", [])

    with _isolated_capability_modules(), trusted_installed_capability_import_context(
        ("bt_api_ctp",)
    ):
        module = importlib.import_module("bt_api_ctp")
        child = importlib.import_module("bt_api_ctp.ctp_env_selector")

        assert module.STATUS == "installed"
        assert child.PROFILE == "installed"
        assert capability_imports._path_is_within(module.__file__, purelib)


def test_strict_installed_context_allows_parent_sdk_only_when_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    purelib = tmp_path / "interpreter" / "site-packages"
    purelib.mkdir(parents=True)
    _write_capability_package(purelib, "bt_api_base", "base")
    _write_capability_package(purelib, "bt_api_ctp", "ctp")
    parent = _write_capability_package(purelib, "bt_api_py", "parent")
    (parent / "_ctp_execution_authorization.py").write_text(
        "SCHEMA = 'managed-simnow'\n", encoding="utf-8"
    )
    _patch_interpreter_install_root(monkeypatch, purelib)
    monkeypatch.setattr(sys, "path", [])

    with _isolated_capability_modules():
        with trusted_installed_capability_import_context(
            ("bt_api_base", "bt_api_ctp", "bt_api_py")
        ):
            package = importlib.import_module("bt_api_py")
            authorization = importlib.import_module("bt_api_py._ctp_execution_authorization")
            assert package.STATUS == "parent"
            assert authorization.SCHEMA == "managed-simnow"
            assert capability_imports._path_is_within(package.__file__, purelib)

        with pytest.raises(
            RuntimeConfigError
        ) as caught, trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            importlib.import_module("bt_api_py._ctp_execution_authorization")

    assert caught.value.reason == "capability_module_not_registered"


def test_strict_installed_context_rejects_absolute_pythonpath_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    purelib = tmp_path / "interpreter" / "site-packages"
    injected_root = tmp_path / "absolute-pythonpath"
    purelib.mkdir(parents=True)
    package = _write_capability_package(injected_root, "bt_api_ctp", "injected")
    sentinel = tmp_path / "injected-capability-executed"
    (package / "__init__.py").write_text(
        "from pathlib import Path\n"
        "Path({0!r}).write_text('executed', encoding='utf-8')\n".format(str(sentinel)),
        encoding="utf-8",
    )
    _patch_interpreter_install_root(monkeypatch, purelib)
    # This models an absolute PYTHONPATH entry after Python has constructed
    # sys.path.  The strict context must not inspect or import it.
    monkeypatch.setattr(sys, "path", [str(injected_root)])

    with _isolated_capability_modules(), pytest.raises(
        RuntimeConfigError
    ) as caught, trusted_installed_capability_import_context(("bt_api_ctp",)):
        pass

    assert caught.value.reason == "capability_origin_unavailable"
    assert not sentinel.exists()


def test_strict_installed_context_does_not_use_editable_meta_finder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    purelib = tmp_path / "interpreter" / "site-packages"
    editable_root = tmp_path / "editable-source"
    purelib.mkdir(parents=True)
    _write_capability_package(editable_root, "bt_api_ctp", "editable")
    _patch_interpreter_install_root(monkeypatch, purelib)
    monkeypatch.setattr(sys, "path", [])

    class EditableOnlyFinder:
        calls = 0

        @classmethod
        def find_spec(cls, fullname: str, path: object = None, target: object = None) -> object:
            del path, target
            if fullname != "bt_api_ctp":
                return None
            cls.calls += 1
            return importlib.machinery.PathFinder.find_spec(fullname, (str(editable_root),))

    monkeypatch.setattr(sys, "meta_path", [EditableOnlyFinder, *sys.meta_path])

    with _isolated_capability_modules(), pytest.raises(
        RuntimeConfigError
    ) as caught, trusted_installed_capability_import_context(("bt_api_ctp",)):
        pass

    assert caught.value.reason == "capability_origin_unavailable"
    assert EditableOnlyFinder.calls == 0


def test_strict_installed_context_rejects_cached_source_package_outside_install_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    purelib = tmp_path / "interpreter" / "site-packages"
    source_root = tmp_path / "checked-out-source"
    _write_capability_package(purelib, "bt_api_ctp", "installed")
    _write_capability_package(source_root, "bt_api_ctp", "cached-source")
    _patch_interpreter_install_root(monkeypatch, purelib)
    monkeypatch.setattr(sys, "path", [str(source_root)])

    with _isolated_capability_modules():
        cached = importlib.import_module("bt_api_ctp")
        assert cached.STATUS == "cached-source"

        with pytest.raises(
            RuntimeConfigError
        ) as caught, trusted_installed_capability_import_context(("bt_api_ctp",)):
            pass

    assert caught.value.reason == "capability_origin_mismatch"


def test_strict_installed_context_rejects_cached_submodule_outside_install_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    purelib = tmp_path / "interpreter" / "site-packages"
    source_root = tmp_path / "checked-out-source"
    _write_capability_package(purelib, "bt_api_ctp", "installed")
    source_root.mkdir()
    outside_child = source_root / "untrusted_child.py"
    outside_child.write_text("STATUS = 'outside'\n", encoding="utf-8")
    _patch_interpreter_install_root(monkeypatch, purelib)
    monkeypatch.setattr(sys, "path", [])

    with _isolated_capability_modules(), pytest.raises(
        RuntimeConfigError
    ) as caught, trusted_installed_capability_import_context(("bt_api_ctp",)):
        importlib.import_module("bt_api_ctp")
        injected_child = ModuleType("bt_api_ctp.untrusted_child")
        injected_child.__file__ = str(outside_child)
        sys.modules[injected_child.__name__] = injected_child

    assert caught.value.reason == "capability_origin_mismatch"
