"""Full caller composition against the pinned CUv2 and R4 sources.

This test uses only public source and fake file/API leaves. It never reads the
opaque executable or DLL sentinels and never accesses D:/temp.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(r"D:\source_code\backtrader")
CALLER_PATH = ROOT / ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_r4_r3.py"
FIXTURE_PATH = ROOT / "tests/unit/scripts/test_iteration41_optional16_preparation_source_reconciliation_r4_source_fake.py"
R3_OBSERVATION = (
    ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构"
    / "evidence/iteration41-optional16-preparation-source-reconciliation-root-actual-r3-2026-10-09/observation.json"
)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    prior = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if prior is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prior
        raise
    return module


def _prior_binding(fixture_helpers, module):
    functions = tuple(
        (name, fixture_helpers._function_state(value))
        for name, value in module.__dict__.items()
        if type(value) is types.FunctionType and value.__module__ == module.__name__
    )
    globals_state = {
        key: fixture_helpers._freeze(value)
        for key, value in module.__dict__.items()
        if key != "_RETAINED"
    }
    return functions, globals_state, module._RETAINED


def _install_full_outer_map(fixture, fixture_helpers):
    """Use the exact production 42-public/3-software map with fake leaves."""
    root_ns, raw_map, frame_locals = fixture_helpers._production_derived_outer_maps(fixture)
    assert len(frame_locals["pins"]) == 42
    assert len(frame_locals["software_pins"]) == 3
    assert len(frame_locals["all_pins"]) == 45
    assert {_key for _key in frame_locals["all_pins"]} == {
        fixture_helpers._path_key(path) for path in raw_map
    }

    old_outer = fixture["outer"]
    assert old_outer.__exit__(None, None, None) is False
    assert old_outer.gen.gi_frame is None

    software_raws = {}
    for software_path in fixture["root_ns"]["SOFTWARE"]:
        matches = [
            raw for path, raw in raw_map.items()
            if fixture_helpers._path_key(path) == fixture_helpers._path_key(software_path)
        ]
        assert len(matches) == 1
        software_raws[software_path] = matches[0]
    opaque_raws = {
        path: raw for path, raw in software_raws.items()
        if fixture_helpers._path_key(path) != fixture_helpers._path_key(fixture["root_ns"]["CU"])
    }
    def build_full_outer():
        events = []
        raw_by_path = {fixture_helpers._path_key(path): raw for path, raw in raw_map.items()}
        fixture_helpers._FakePath.data_by_path = raw_by_path
        api = fixture_helpers._FakeAPI(events)
        cli = fixture_helpers._FakeCLI(events, raw_by_path)
        private = types.SimpleNamespace(_api=lambda: api)
        cuv2_raw = next(
            raw for path, raw in raw_map.items()
            if fixture_helpers._path_key(path) == fixture_helpers._path_key(fixture["root_ns"]["CU"])
        )
        cuv2 = fixture_helpers._source_module(
            fixture_helpers.CU_NAME, fixture_helpers.CU_PATH, cuv2_raw
        )
        cuv2.Path = fixture_helpers._FakePath
        cuv2.ROOT = fixture_helpers._FakePath(ROOT)

        def fake_load(relative, pin, name):
            if relative == cuv2.PRIVATE:
                assert pin == cuv2.PRIVATE_SHA and name == "_root_public_custody_private"
                return private
            if relative == cuv2.CLI:
                assert pin == cuv2.CLI_SHA and name == "_root_public_custody_cli"
                return cli
            raise AssertionError("CUv2 requested an unpinned helper")

        cuv2.load = fake_load
        sys.modules[fixture_helpers.CU_NAME] = cuv2
        outer = cuv2.held_public_sources(frame_locals["pins"], fixture["root_ns"]["SOFTWARE"])
        held = outer.__enter__()
        fixture["root_ns"]["sys"].modules[fixture_helpers.CU_NAME] = cuv2
        return outer, held, cuv2, events, api, cli

    outer, held, cuv2, events, api, cli = _with_fake_opaque_hash_leaf(
        build_full_outer, opaque_raws, fixture["root_ns"]["SOFTWARE"]
    )
    assert len(held[2]) == 45
    assert outer.gen.gi_frame.f_locals["software_pins"] == fixture["root_ns"]["SOFTWARE"]
    assert {_key for _key in frame_locals["all_pins"]} == {
        fixture_helpers._path_key(path) for path in held[2]
    }
    assert len([event for event in events if event[0] == "bounded-read"]) == 45
    assert len([event for event in events if event[0] == "file-open"]) == 45

    fixture["outer"] = outer
    fixture["held"] = held
    fixture["cuv2"] = cuv2
    fixture["outer_events"] = events
    fixture["outer_api"] = api
    fixture["outer_cli"] = cli
    fixture["state"]["outer"] = outer
    fixture["state"]["held"] = held
    fixture["root_ns"]["sys"].modules[fixture_helpers.CU_NAME] = cuv2
    r2_record = fixture["r2_record"]
    r2_record.update({
        "cuv2_globals": outer.gen.gi_frame.f_globals,
        "held": held,
        "outer": outer,
        "outer_frame": outer.gen.gi_frame,
        "outer_gen": outer.gen,
    })
    return raw_map, frame_locals


def _install_original_inner_scope_shape(fixture, fixture_helpers):
    """Give the consumed sourcefake inner scope its pinned 457-row shape."""
    scope = fixture["scope"]
    rows = scope._rows
    assert len(rows) == 2
    raw_by_handle = {row.handle: scope._bytes[row.key] for row in rows.values()}
    identity_by_handle = {row.handle: row.identity for row in rows.values()}
    row_type = fixture["v3"]._HeldRow

    for index in range(455):
        path = ROOT / ".codex-tmp" / f"sourcefake-original-inner-row-{index:03d}.bin"
        key = fixture_helpers._path_key(path)
        logical = f"sourcefake-original-inner-row-{index:03d}"
        raw = f"synthetic public inner source row {index:03d}".encode("ascii")
        digest = hashlib.sha256(raw).hexdigest()
        handle = ("scope-file", logical)
        identity = ("scope-id", logical)
        row = row_type(key, logical, path, digest, 256 * 1024, "public")
        row.handle = handle
        row.identity = identity
        row.size = len(raw)
        rows[key] = row
        scope._logical[logical.casefold()] = key
        scope._bytes[key] = raw
        raw_by_handle[handle] = raw
        identity_by_handle[handle] = identity

    scope._identity = lambda handle, **_kwargs: identity_by_handle[handle]
    scope._file_size = lambda handle: len(raw_by_handle[handle])
    scope._seek_start = lambda _handle: None
    scope._bounded_reader = lambda _api, handle, maximum: (
        raw_by_handle[handle]
        if len(raw_by_handle[handle]) <= maximum
        else (_ for _ in ()).throw(AssertionError("fake source row exceeded read bound"))
    )
    assert len(scope.manifest()) == 457
    assert scope.public_map == scope.manifest()
    assert scope.software_map == {} and scope.support_map == {}


def _with_fake_opaque_hash_leaf(operation, opaque_raws, software_pins):
    """Model opaque payload digests without opening executable or DLL bodies."""
    digests = {opaque_raws[path]: software_pins[path] for path in opaque_raws}
    assert len(digests) == len(opaque_raws) == 2
    original_sha256 = hashlib.sha256

    class FakeDigest:
        def __init__(self, value):
            self.value = value

        def hexdigest(self):
            return self.value

    def fake_sha256(raw, *args, **kwargs):
        digest = digests.get(bytes(raw)) if isinstance(raw, (bytes, bytearray, memoryview)) else None
        if digest is not None:
            return FakeDigest(digest)
        return original_sha256(raw, *args, **kwargs)

    hashlib.sha256 = fake_sha256
    try:
        return operation()
    finally:
        hashlib.sha256 = original_sha256


def _install_fake_review_leaves(caller, fixture_helpers, state):
    """Keep CUv2's pinned generator; substitute only its filesystem leaves."""
    scope = state["review_scope"]
    generator_locals = scope.gen.gi_frame.f_locals
    pins = generator_locals["pins"]
    software_pins = generator_locals["software_pins"]
    assert software_pins == {}

    raw_by_path = {}
    for relative, digest in pins.items():
        path = caller.ROOT / relative
        raw = caller._public_bytes(path, digest)
        raw_by_path[fixture_helpers._path_key(path)] = raw
    fixture_helpers._FakePath.data_by_path = raw_by_path

    events = []
    api = fixture_helpers._FakeAPI(events)
    cli = fixture_helpers._FakeCLI(events, raw_by_path)
    private = types.SimpleNamespace(_api=lambda: api)
    cuv2 = state["cuv2_module"]
    original = (cuv2.Path, cuv2.ROOT, cuv2.load)

    def fake_load(relative, pin, name):
        pinned_cuv2 = state["cuv2_module"]
        if relative == "backtrader_runtime/certification_roundtrip_private.py":
            assert pin == pinned_cuv2.PRIVATE_SHA
            assert name == "_root_public_custody_private"
            return private
        if relative == "backtrader_runtime/certification_binance_roundtrip_r3_cli.py":
            assert pin == pinned_cuv2.CLI_SHA
            assert name == "_root_public_custody_cli"
            return cli
        raise AssertionError("CUv2 requested an unpinned helper")

    fake = (fixture_helpers._FakePath, fixture_helpers._FakePath(caller.ROOT), fake_load)
    state["sourcefake_fs_leaves"] = fake
    state["sourcefake_fs_originals"] = original
    state["sourcefake_fs_events"] = events
    state["sourcefake_fs_raw_by_path"] = raw_by_path
    state["sourcefake_review_pin_keys"] = {
        fixture_helpers._path_key(caller.ROOT / relative) for relative in pins
    }
    state["sourcefake_review_pin_count"] = len(pins)
    cuv2.Path, cuv2.ROOT, cuv2.load = fake
    return cuv2, original, fake


def test_full_run_uses_pinned_cuv2_and_r4_with_exact_outer_map_and_fake_leaves(request, tmp_path):
    fixture_helpers = _load_module(FIXTURE_PATH, "_optional16_r4_fullchain_fixture_helpers")
    caller = _load_module(CALLER_PATH, "_optional16_r4_fullchain_caller")
    caller_raw = CALLER_PATH.read_bytes()
    caller_sha256 = hashlib.sha256(caller_raw).hexdigest()

    class FinalizerRequest:
        def addfinalizer(self, callback):
            request.addfinalizer(callback)

    fixture = fixture_helpers._fixture(FinalizerRequest())
    exact_raw_map, exact_outer_locals = _install_full_outer_map(fixture, fixture_helpers)
    _install_original_inner_scope_shape(fixture, fixture_helpers)
    root_ns = fixture["root_ns"]
    runtime_sys = root_ns["sys"]
    caller.sys = runtime_sys
    caller.OUT = tmp_path / "optional16-r4-fullchain-sourcefake"
    # The production caller can forward the helper's fake-only token only for
    # this explicitly marked test namespace and test-only retained scope.
    root_ns[caller.SOURCEFAKE_CALLER_TEST_KEY] = caller._SOURCEFAKE_CALLER_TEST_TOKEN
    outer_raw_by_path = {
        fixture_helpers._path_key(path): raw for path, raw in exact_raw_map.items()
    }
    opaque_outer_raws = {}
    for software_path in root_ns["SOFTWARE"]:
        if fixture_helpers._path_key(software_path) == fixture_helpers._path_key(root_ns["CU"]):
            continue
        matches = [
            raw for path, raw in exact_raw_map.items()
            if fixture_helpers._path_key(path) == fixture_helpers._path_key(software_path)
        ]
        assert len(matches) == 1
        opaque_outer_raws[software_path] = matches[0]

    # Root state aliases in the fixture mirror the two consumed reconciliation
    # records and preserve the exact module registries captured by their helpers.
    r1_binding = _prior_binding(fixture_helpers, fixture["r1_module"])
    r2_binding = _prior_binding(fixture_helpers, fixture["r2_module"])
    root_ns["RECONCILIATION_ROOT_STATE"] = {
        "helper": fixture["r1_module"], "binding": r1_binding,
    }
    root_ns["RECONCILIATION_ROOT_STATE_R2"] = {
        "helper": fixture["r2_module"], "binding": r2_binding,
        "held": fixture["r2_held"],
    }
    runtime_sys.modules[caller.R1_NAME] = fixture["r1_module"]
    runtime_sys.modules[caller.R2_NAME] = fixture["r2_module"]
    sys.modules[caller.R1_NAME] = fixture["r1_module"]
    sys.modules[caller.R2_NAME] = fixture["r2_module"]

    # This installs the exact public Root audit used by the consumed R3
    # reproduction. It rejects the AST-rewritten V4 reference and leaves the
    # synthetic original scopes open for the subsequent R4 sourcefake call.
    fixture_helpers._install_original_root_audit(fixture)
    r3_raw = fixture_helpers._read(fixture_helpers.HELPER_PATH)
    r3_module = fixture_helpers._source_module(
        fixture_helpers.R3_HELPER_NAME, fixture_helpers.HELPER_PATH, r3_raw
    )
    sys.modules[r3_module.__name__] = r3_module
    runtime_sys.modules[r3_module.__name__] = r3_module
    # Model the already-consumed R3 state from its pinned observation. This
    # caller test does not retry R3 or close the original synthetic scopes.
    r3_observation = json.loads(R3_OBSERVATION.read_bytes().decode("utf-8"))
    r3_held = (None, None, {str(fixture_helpers.HELPER_PATH): r3_raw})
    r3_record = {
        "root_namespace": root_ns,
        "root_state": fixture["state"],
        "root_result": fixture["result"],
        "r1_module": fixture["r1_module"],
        "r1_registry": fixture["r1_registry"],
        "r1_record": fixture["r1_record"],
        "r1_raw": fixture["r1_raw"],
        "r2_module": fixture["r2_module"],
        "r2_registry": fixture["r2_registry"],
        "r2_record": fixture["r2_record"],
        "r2_held": fixture["r2_held"],
        "r2_raw": fixture["r2_raw"],
        "phase": "inner_scope_retained",
        "exit_started": False,
        "result_snapshot": fixture["r2_module"]._snapshot_json(fixture["result"]),
        "driver": fixture["state"]["driver"],
        "attempt": fixture["attempt"],
        "entry": fixture["entry"],
        "v4": fixture["v4"],
        "scope": fixture["scope"],
        "call_module": fixture["call"],
        "call_record": fixture["call_record"],
        "module_sources": fixture["call_record"][2],
        "prep_raw": fixture["attempt"][6],
        "call_raw": fixture["attempt"][7],
        "v3_raw": fixture["attempt"][8],
        "v4_raw": fixture["attempt"][9],
        "outer": fixture["outer"],
        "held": fixture["held"],
        "outer_gen": fixture["outer"].gen,
        "outer_frame": fixture["outer"].gen.gi_frame,
        "cuv2_globals": fixture["outer"].gen.gi_frame.f_globals,
        "cuv2_module": fixture["cuv2"],
        "cuv2_function": inspect.unwrap(fixture["cuv2"].held_public_sources),
        "outer_exit_method": fixture["outer"].__exit__,
        "outer_exit_function": type(fixture["outer"]).__exit__,
        "outer_exit_code": type(fixture["outer"]).__exit__.__code__,
        "outer_exit_globals": type(fixture["outer"]).__exit__.__globals__,
    }
    r3_module._RETAINED.append(r3_record)
    r3_scope = fixture_helpers._closed_test_scope()
    r3_state = {
        "review_scope": r3_scope,
        "held": r3_held,
        "original_state": fixture["state"],
        "original_result": fixture["result"],
        "original_attempt": fixture["attempt"],
        "original_call_record": fixture["call_record"],
        "original_gen": fixture["outer"].gen,
        "helper": r3_module,
        "binding": fixture_helpers._capture_helper(r3_module),
        "original_scope": fixture["scope"],
        "receipt": r3_observation["receipt"],
        "observation": r3_observation,
    }
    root_ns["RECONCILIATION_ROOT_STATE_R3"] = r3_state
    fixture["r3_helper"] = r3_module
    fixture["r3_state"] = r3_state
    fixture["r3_raw"] = r3_raw
    assert fixture["scope"].state == "OPEN"
    assert len(fixture["scope"].manifest()) == 457
    assert fixture["outer"].gen.gi_frame is not None
    assert fixture["r2_record"]["held"] is fixture["state"]["held"]
    assert fixture["r2_held"] is not fixture["r2_record"]["held"]
    assert root_ns["RECONCILIATION_ROOT_STATE_R2"]["held"] is fixture["r2_held"]
    assert r3_state["receipt"] is r3_state["observation"]["receipt"]
    assert set(r3_state["helper"]._RETAINED[0]) == caller._R3_RECORD_KEYS

    original_enter = caller._enter_review_scope
    original_finish = caller._finish_review_attempt
    original_invoke = caller._invoke_r4_once

    def enter_with_fake_fs(state):
        cuv2, original, fake = _install_fake_review_leaves(caller, fixture_helpers, state)
        review_raw_by_path = dict(fixture_helpers._FakePath.data_by_path)
        combined_raw_by_path = dict(outer_raw_by_path)
        for key, raw in review_raw_by_path.items():
            if key in combined_raw_by_path:
                assert combined_raw_by_path[key] is raw or combined_raw_by_path[key] == raw
            combined_raw_by_path[key] = raw
        fixture_helpers._FakePath.data_by_path = combined_raw_by_path
        try:
            return original_enter(state)
        finally:
            cuv2.Path, cuv2.ROOT, cuv2.load = original

    def finish_with_fake_fs(state):
        cuv2 = state.get("cuv2_module")
        leaves = state.get("sourcefake_fs_leaves")
        if cuv2 is None or leaves is None:
            return original_finish(state)
        original = state["sourcefake_fs_originals"]
        cuv2.Path, cuv2.ROOT, cuv2.load = leaves
        try:
            return original_finish(state)
        finally:
            cuv2.Path, cuv2.ROOT, cuv2.load = original

    caller._enter_review_scope = enter_with_fake_fs
    caller._finish_review_attempt = finish_with_fake_fs
    try:
        outcome = _with_fake_opaque_hash_leaf(
            lambda: caller.run(root_ns, expected_caller_sha256=caller_sha256),
            opaque_outer_raws, root_ns["SOFTWARE"],
        )
    finally:
        caller._enter_review_scope = original_enter
        caller._finish_review_attempt = original_finish

    assert caller.R4_ROOT_KEY in root_ns, outcome
    r4_state = root_ns[caller.R4_ROOT_KEY]
    assert r4_state["held"] is not caller._MISSING, outcome
    review_scope = r4_state["review_scope"]
    review_raw_map = r4_state["held"][2]
    expected_review_keys = r4_state["sourcefake_review_pin_keys"]

    assert len(exact_outer_locals["pins"]) == 42
    assert len(exact_outer_locals["software_pins"]) == 3
    assert len(exact_outer_locals["all_pins"]) == 45
    assert len(exact_raw_map) == 45
    assert outcome["caller_phase"] == "review_scope_normal_exit", outcome
    assert outcome["caller_reason_code"] is None
    assert outcome["r4_api_invocations"] == 1
    assert caller._invoke_r4_once is original_invoke
    assert len(r4_state["helper"]._RETAINED) == 1
    assert r4_state["helper"]._RETAINED[0]["phase"] == "closed"
    assert outcome["r4_status"] == "ROOT_SOURCE_CUSTODY_CLOSED", outcome
    assert outcome["fresh_review_scope_normal_exit"] is True
    assert outcome["review_scope_enter_returned"] is True
    assert outcome["review_scope_normal_postverify"] is True
    assert outcome["cuv2_held_factory_source_bound_before_use"] is True
    assert outcome["cuv2_held_factory_source_bound_after_call"] is True
    assert outcome["r4_helper_source_function_global_class_bindings_verified"] is True
    assert outcome["original_state_result_preserved"] is True
    assert outcome["formal_optional16_pass_count"] == 0
    assert review_scope.gen.gi_frame is None
    assert len(review_raw_map) == r4_state["sourcefake_review_pin_count"]
    assert expected_review_keys == {
        fixture_helpers._path_key(path) for path in review_raw_map
    }
    assert len(r4_state["sourcefake_fs_events"]) > len(review_raw_map)
    assert all(
        fixture_helpers._path_key(event[1]).startswith(fixture_helpers._path_key(ROOT))
        for event in r4_state["sourcefake_fs_events"]
        if event[0] == "file-open"
    )
    caller._verify_cuv2_factory(r4_state)

