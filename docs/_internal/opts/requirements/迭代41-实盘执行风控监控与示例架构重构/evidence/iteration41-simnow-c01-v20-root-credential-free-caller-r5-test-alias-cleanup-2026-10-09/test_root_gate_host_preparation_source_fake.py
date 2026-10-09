"""Pure source-fake checks for Root's V20 gate host preparation code."""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
from types import MappingProxyType, ModuleType

import pytest


PREPARATION_PATH = Path(__file__).with_name("prepare_root_gate_host.py")
_PREPARATION_SPEC = importlib.util.spec_from_file_location(
    "_c01_v20_root_gate_host_preparation_test", PREPARATION_PATH
)
assert _PREPARATION_SPEC is not None and _PREPARATION_SPEC.loader is not None
PREPARATION = importlib.util.module_from_spec(_PREPARATION_SPEC)
_PREPARATION_SPEC.loader.exec_module(PREPARATION)


def _restore_unretained_cuv2_alias(original: object, missing: object, created: object) -> None:
    alias = "_root_public_custody_cli"
    current = sys.modules.get(alias, missing)
    if current is not created or created is None:
        return
    if original is missing:
        sys.modules.pop(alias, None)
    else:
        sys.modules[alias] = original  # type: ignore[assignment]


def test_unretained_host_cleanup_preserves_preexisting_cuv2_alias() -> None:
    alias = "_root_public_custody_cli"
    missing = object()
    original = ModuleType(alias)
    created = ModuleType(alias)
    previous = sys.modules.get(alias, missing)
    sys.modules[alias] = original
    try:
        _restore_unretained_cuv2_alias(original, missing, None)
        assert sys.modules.get(alias) is original

        sys.modules[alias] = created
        _restore_unretained_cuv2_alias(original, missing, created)
        assert sys.modules.get(alias) is original
    finally:
        if previous is missing:
            if sys.modules.get(alias) is original or sys.modules.get(alias) is created:
                sys.modules.pop(alias, None)
        else:
            sys.modules[alias] = previous  # type: ignore[assignment]


def test_exact_source_components_are_pinned_and_precheck_is_bounded() -> None:
    root = PREPARATION.REPOSITORY_ROOT
    for relative, byte_count, digest in (
        (PREPARATION.PRECHECK_RELATIVE, PREPARATION.PRECHECK_BYTES, PREPARATION.PRECHECK_SHA256),
        (PREPARATION.CALLER_RELATIVE, PREPARATION.CALLER_BYTES, PREPARATION.CALLER_SHA256),
    ):
        path = root.joinpath(*relative.split("/"))
        with path.open("rb") as stream:
            raw = stream.read(byte_count + 1)
        assert len(raw) == byte_count
        assert hashlib.sha256(raw).hexdigest() == digest


def test_precheck_driver_snapshot_matches_outer_source_capture() -> None:
    precheck, prepared = PREPARATION._load_precheck(PREPARATION.REPOSITORY_ROOT.resolve(strict=True))
    assert precheck.__dict__["validate_prepared_root_precheck"](prepared) is True
    capture = prepared.driver_module.__dict__["_capture_source_module_objects"]
    observed = capture(prepared.driver_module)
    assert set(observed) == set(prepared.driver_objects)
    assert all(observed[name] is prepared.driver_objects[name] for name in observed)


def test_module_aliases_are_fixed_for_the_driver_and_v20_rows() -> None:
    assert (
        PREPARATION._module_name_for(
            PREPARATION.DRIVER_RELATIVE, PREPARATION.DRIVER_RELATIVE
        )
        == PREPARATION.DRIVER_MODULE_NAME
    )
    assert PREPARATION._module_name_for(
        "backtrader_runtime/certification_simnow_c01_v3_protocol.py",
        PREPARATION.DRIVER_RELATIVE,
    ) == "backtrader_runtime.certification_simnow_c01_v3_protocol"
    assert PREPARATION._module_name_for(
        "examples/000_live_certification/simnow_penetration/cases/C01/run_v20.py",
        PREPARATION.DRIVER_RELATIVE,
    ) == "examples.000_live_certification.simnow_penetration.cases.C01.run_v20"


def test_dependency_order_loads_exact_imports_before_consumers() -> None:
    paths = tuple(
        sorted(
            set(PREPARATION._LOAD_DEPENDENCIES)
            | {
                dependency
                for dependencies in PREPARATION._LOAD_DEPENDENCIES.values()
                for dependency in dependencies
            }
        )
    )
    ordered = PREPARATION._ordered_paths(paths)
    positions = {path: index for index, path in enumerate(ordered)}
    for path, dependencies in PREPARATION._LOAD_DEPENDENCIES.items():
        assert all(positions[dependency] < positions[path] for dependency in dependencies)


def test_package_shell_does_not_execute_or_search_package_initializers() -> None:
    shell = PREPARATION._make_package_shell("_c01_fake_package_shell")
    assert type(shell) is ModuleType
    assert shell.__package__ == "_c01_fake_package_shell"
    assert shell.__path__ == []
    assert shell.__spec__.submodule_search_locations == []
    assert "__file__" not in shell.__dict__
    assert "_c01_fake_package_shell" not in sys.modules


def test_exact_component_loader_compiles_only_the_supplied_bytes(tmp_path: Path) -> None:
    path = tmp_path / "synthetic_component.py"
    raw = b"SENTINEL = 'compiled from supplied bytes'\n"
    path.write_bytes(raw)
    component = PREPARATION._load_exact_component(
        raw,
        root=tmp_path,
        relative="synthetic_component.py",
        module_name="_c01_synthetic_component",
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    )
    assert component.__dict__["SENTINEL"] == "compiled from supplied bytes"
    assert component.__dict__["__c01_source_sha256__"] == hashlib.sha256(raw).hexdigest()
    assert component.__dict__["__c01_source_bytes__"] == len(raw)
    assert component.__dict__["__spec__"].origin == str(path.resolve())
    assert sys.modules.get("_c01_synthetic_component") is None


def test_cuv2_pin_failure_precedes_precheck_and_any_lease_entry() -> None:
    assert PREPARATION._ROOT_HOSTS == []
    with pytest.raises(PREPARATION.RootPreparationError) as error:
        PREPARATION.prepare_root_gate_host(b"synthetic invalid bytes")
    assert error.value.code == "cuv2_source_pin_invalid"
    assert PREPARATION._ROOT_HOSTS == []


def test_caller_rejects_old_or_unpinned_precheck_before_gate_call() -> None:
    caller = PREPARATION._load_caller(PREPARATION.REPOSITORY_ROOT.resolve(strict=True))
    invoke = caller.__dict__["invoke_root_credential_free_gate"]
    expected_path = caller.__dict__["_expected_precheck_path"]()
    wrong_precheck = {
        "__file__": expected_path,
        "__c01_source_sha256__": "0" * 64,
    }
    with pytest.raises(caller.__dict__["CredentialFreeCallerError"]) as error:
        invoke(wrong_precheck, None, None)
    assert error.value.code == "precheck_source_path_invalid"


def test_alias_preflight_rejects_preexisting_module_without_replacing_it() -> None:
    module_name = "_c01_test_collision_pkg.child"
    package_name = "_c01_test_collision_pkg"
    original = ModuleType(package_name)
    sys.modules[package_name] = original
    try:
        with pytest.raises(PREPARATION.RootPreparationError) as error:
            PREPARATION._preflight_aliases(("_c01_test_collision_pkg/child.py",))
        assert error.value.code == "fixed_module_alias_already_loaded"
        assert sys.modules[package_name] is original
        assert module_name not in sys.modules
    finally:
        if sys.modules.get(package_name) is original:
            sys.modules.pop(package_name)


def test_source_root_comparison_uses_driver_normcase_and_normpath(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PREPARATION.os.path, "normcase", lambda value: value.casefold())
    root = str(PREPARATION.REPOSITORY_ROOT.resolve(strict=True))
    driver_form = os.path.normcase(os.path.normpath(root))
    differently_cased = root.swapcase()
    assert differently_cased != root
    assert PREPARATION._normalized_source_root(differently_cased) == driver_form
    assert PREPARATION._normalized_source_root(root) == driver_form
    with pytest.raises(PREPARATION.RootPreparationError) as error:
        PREPARATION._normalized_source_root("")
    assert error.value.code == "entered_source_root_invalid"


def test_full_preparation_uses_real_driver_lease_binder_and_precheck_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparation = PREPARATION
    assert preparation._ROOT_HOSTS == []
    synthetic_cuv2 = (
        b"import contextlib\n"
        b"from types import ModuleType\n"
        b"def _held_generator(public_pins, software_pins):\n"
        b"    _source_fake_state['enter'] += 1\n"
        b"    driver = _source_fake_driver\n"
        b"    root = driver._source_root_for_driver()\n"
        b"    raw_by_absolute = {}\n"
        b"    for relative in public_pins:\n"
        b"        absolute = driver._absolute_public_path(root, relative)\n"
        b"        raw_by_absolute[absolute] = _source_fake_public_raw[relative]\n"
        b"    for path in software_pins:\n"
        b"        absolute = driver._normalize_absolute_path(path)\n"
        b"        raw_by_absolute[absolute] = _source_fake_software_raw[path]\n"
        b"    private = ModuleType('_root_public_custody_private')\n"
        b"    cli = ModuleType('_root_public_custody_cli')\n"
        b"    yield (private, cli, raw_by_absolute)\n"
        b"    _source_fake_state['normal_exit'] += 1\n"
        b"def held_public_sources(public_pins, software_pins):\n"
        b"    _source_fake_state['manager'] += 1\n"
        b"    return contextlib._GeneratorContextManager("
        b"_held_generator, (public_pins, software_pins), {})\n"
        b"held_public_sources.__wrapped__ = _held_generator\n"
    )
    synthetic_cuv2_sha = hashlib.sha256(synthetic_cuv2).hexdigest()
    monkeypatch.setattr(preparation, "CUV2_SOURCE_BYTES", len(synthetic_cuv2))
    monkeypatch.setattr(preparation, "CUV2_SOURCE_SHA256", synthetic_cuv2_sha)

    state: dict[str, object] = {"load": 0, "manager": 0, "enter": 0, "normal_exit": 0}
    original_load = preparation._load_precheck
    original_cuv2_loader = preparation._cu_v2_module
    original_hosts = tuple(preparation._ROOT_HOSTS)
    alias_missing = object()
    original_cuv2_alias = sys.modules.get("_root_public_custody_cli", alias_missing)
    prepared_holder: dict[str, object] = {}
    cuv2_holder: dict[str, object] = {}
    synthetic_software_raw: dict[str, bytes] = {}

    def load_precheck_once(root_arg: Path):
        state["load"] = int(state["load"]) + 1
        module, original_prepared = original_load(root_arg)
        driver = original_prepared.driver_module
        for index, path in enumerate(original_prepared.software_source_pins):
            synthetic_software_raw[path] = (
                synthetic_cuv2
                if path == preparation.CUV2_SOURCE_PATH
                else f"synthetic-software-row-{index}".encode("ascii")
            )
        software_pins = MappingProxyType(
            {
                path: hashlib.sha256(raw).hexdigest()
                for path, raw in synthetic_software_raw.items()
            }
        )
        # These test-only values let the actual typed driver lease consume a
        # synthetic CUv2 module and synthetic software hashes without reading
        # any software payload. The production driver functions stay intact.
        driver.__dict__["CUV2_SOURCE_BYTES"] = len(synthetic_cuv2)
        driver.__dict__["CUV2_SOURCE_SHA256"] = synthetic_cuv2_sha
        driver_objects = driver.__dict__["capture_c01_v20_driver_objects"](driver)
        prepared = type(original_prepared)(
            driver_module=driver,
            driver_objects=driver_objects,
            public_source_pins=original_prepared.public_source_pins,
            public_source_bytes=original_prepared.public_source_bytes,
            software_source_pins=software_pins,
            summary=dict(original_prepared._summary),
            _factory=module.__dict__["_PRECHECK_FACTORY"],
        )
        assert module.__dict__["validate_prepared_root_precheck"](prepared) is True
        prepared_holder["precheck_module"] = module
        prepared_holder["prepared"] = prepared
        return module, prepared

    def load_synthetic_cuv2(raw: bytes, driver):
        module = original_cuv2_loader(raw, driver)
        cuv2_holder["module"] = module
        prepared = prepared_holder["prepared"]
        module.__dict__.update(
            {
                "_source_fake_driver": driver,
                "_source_fake_public_raw": prepared.public_source_bytes,
                "_source_fake_software_raw": synthetic_software_raw,
                "_source_fake_state": state,
            }
        )
        return module

    monkeypatch.setattr(preparation, "_load_precheck", load_precheck_once)
    monkeypatch.setattr(preparation, "_cu_v2_module", load_synthetic_cuv2)
    host = None
    try:
        host = preparation.prepare_root_gate_host(synthetic_cuv2)
        prepared = prepared_holder["prepared"]
        precheck = prepared_holder["precheck_module"]
        driver = host.driver_module
        assert host.lease is not None
        assert type(host.lease) is driver.__dict__["C01V20OuterSourceLease"]
        assert driver.__dict__["_outer_lease_current"](
            host.lease, require_entered=True
        ) is True
        assert precheck.__dict__["validate_precheck_against_entered_lease"](
            prepared, host.lease
        ) is True
        assert driver.__dict__["_validate_source_module_snapshots"](
            host.lease.source_modules,
            host.lease.source_objects,
            host.lease.source_pins,
            host.lease.held_source_bytes,
        ) is True
        assert host.lease.source_modules[preparation.DRIVER_RELATIVE] is driver
        assert host.lease.source_objects[preparation.DRIVER_RELATIVE] is prepared.driver_objects
        assert sys.modules.get(preparation.DRIVER_MODULE_NAME) is driver
        assert len(host.source_bytes) == len(prepared.public_source_pins) == 26
        assert state == {"load": 1, "manager": 1, "enter": 1, "normal_exit": 0}
        assert host._used is False
        assert host.public_summary()["status"] == "ROOT_GATE_HOST_PREPARED"
        assert host.public_summary()["gate_invoked"] is False
    finally:
        if host is None:
            added_hosts = [
                item
                for item in preparation._ROOT_HOSTS
                if all(item is not old for old in original_hosts)
            ]
            if added_hosts:
                host = added_hosts[-1]
        if host is not None:
            aliases: set[str] = set()
            for relative in host.prepared_precheck.public_source_pins:
                name = preparation._module_name_for(relative, preparation.DRIVER_RELATIVE)
                expected_module = (
                    host.driver_module
                    if relative == preparation.DRIVER_RELATIVE
                    else host.source_modules.get(relative)
                )
                if expected_module is not None and sys.modules.get(name) is expected_module:
                    aliases.add(name)
                aliases.update(preparation._package_names(name))
            for alias in aliases:
                expected_module = host.source_modules.get(alias)
                if alias == preparation.DRIVER_MODULE_NAME:
                    expected_module = host.driver_module
                if expected_module is not None and sys.modules.get(alias) is expected_module:
                    sys.modules.pop(alias, None)
            lease = host.lease
            if (
                lease is not None
                and type(lease) is host.driver_module.__dict__["C01V20OuterSourceLease"]
                and lease.generator.gi_frame is not None
            ):
                close_result = lease.manager_exit(lease.manager, None, None, None)
                assert close_result is False
                assert lease.generator.gi_frame is None
                if (
                    type(lease.keepalive_container_ref) is list
                    and sum(value is lease.keepalive_ref for value in lease.keepalive_container_ref)
                    == 1
                ):
                    lease.keepalive_container_ref.remove(lease.keepalive_ref)
            if sys.modules.get("_root_public_custody_cli") is host.cuv2_module:
                sys.modules.pop("_root_public_custody_cli", None)
            preparation._ROOT_HOSTS[:] = [
                item
                for item in preparation._ROOT_HOSTS
                if any(item is old for old in original_hosts)
            ]
        else:
            _restore_unretained_cuv2_alias(
                original_cuv2_alias,
                alias_missing,
                cuv2_holder.get("module"),
            )
