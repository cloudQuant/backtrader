"""Sourcefake custody reconciliation through the pinned V3 and CUv2 methods.

The fixture uses public Python source plus fake file/API leaves. It contains no
software payloads, profiler caches, private inputs, or actual Root scope.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.machinery
import json
import ntpath
from pathlib import Path, PureWindowsPath
import sys
import threading
import types

import pytest


ROOT = Path(r"D:\source_code\backtrader")
ROOT_RUNNER = ROOT / ".codex-tmp/optional16_root_preparation_actual_20261009.py"
DRIVER_PATH = ROOT / "scripts/iteration41_optional16_r33_root_preparation_driver_r1.py"
CALL_PATH = ROOT / "scripts/iteration41_optional16_r33_root_preparation_call_r1.py"
ENTRY_PATH = ROOT / "scripts/iteration41_optional16_r33_root_held_entry_r2.py"
PREPARATION_PATH = ROOT / "scripts/iteration41_optional16_r33_root_preparation_r1.py"
V3_PATH = ROOT / "scripts/iteration41_root_held_source_scope_v3.py"
V4_PATH = ROOT / "scripts/iteration41_root_held_source_scope_v4.py"
CU_PATH = Path(r"D:\temp\iteration41-root-public-custody-v2.py")
CU_SNAPSHOT_PATH = (
    ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构"
    / "evidence/iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
)
CU_SNAPSHOT_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
HELPER_PATH = ROOT / "scripts/iteration41_optional16_preparation_source_reconciliation_r3.py"
R4_HELPER_PATH = ROOT / "scripts/iteration41_optional16_preparation_source_reconciliation_r4.py"
R1_HELPER_PATH = ROOT / "scripts/iteration41_optional16_preparation_source_reconciliation_r1.py"
R1_HELPER_NAME = "_root_optional16_reconciliation_helper_oct9"
R2_HELPER_PATH = ROOT / "scripts/iteration41_optional16_preparation_source_reconciliation_r2.py"
R2_HELPER_NAME = "_root_optional16_reconciliation_r2_helper_oct9"
R3_HELPER_NAME = "_root_optional16_reconciliation_r3_helper_oct9"
CU_NAME = "_root_optional16_preparation_cuv2_oct9"
DRIVER_NAME = "_root_optional16_preparation_driver_oct9"
CALL_NAME = "_optional16_r33_root_preparation_call_r1"
ENTRY_NAME = "_optional16_r33_root_entry_preparation_driver"
V3_NAME = "_iteration41_root_held_source_scope_v3_pinned_for_v4"
V4_NAME = "_iteration41_optional16_r33_entry_v4"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path) -> bytes:
    raw = path.read_bytes()
    assert type(raw) is bytes and raw
    return raw


def _source_module(name: str, path: Path, raw: bytes, *, exact_loader=False) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    if exact_loader:
        module.__package__ = ""
        module.__loader__ = None
        module.__cached__ = None
        module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
        module.__verified_source_sha256__ = _sha(raw)
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    return module


class _FakePath:
    data_by_path: dict[str, bytes] = {}

    def __init__(self, value):
        self._path = PureWindowsPath(str(value))

    def __str__(self):
        return str(self._path)

    def __hash__(self):
        return hash(_path_key(self))

    def __eq__(self, other):
        try:
            return _path_key(self) == _path_key(other)
        except BaseException:
            return False

    def __truediv__(self, other):
        return _FakePath(self._path / str(other))

    @property
    def parents(self):
        return tuple(_FakePath(value) for value in self._path.parents)

    @property
    def parts(self):
        return self._path.parts

    @property
    def suffix(self):
        return self._path.suffix

    def is_absolute(self):
        return self._path.is_absolute()

    def read_bytes(self):
        return self.data_by_path[_path_key(self)]


def _path_key(value) -> str:
    return ntpath.normcase(ntpath.normpath(str(value).replace("/", "\\")))


class _FakeAPI:
    def __init__(self, events):
        self.events = events

    @contextlib.contextmanager
    def opened(self, path, *, directory, access):
        handle = ("directory", str(path), len(self.events))
        self.events.append(("directory-open", str(path), directory, access))
        try:
            yield handle
        finally:
            self.events.append(("directory-close", str(path)))


class _FakeCLI:
    def __init__(self, events, raw_by_path):
        self.events = events
        self.raw_by_path = raw_by_path
        self.identities = {}

    @contextlib.contextmanager
    def _locked_readonly_file(self, path, _private, _api, *, allow_hardlinks):
        handle = ("file", str(path), len(self.events))
        identity = ("file-id", len(self.identities) + 1)
        self.identities[handle] = identity
        self.events.append(("file-open", str(path), allow_hardlinks))
        try:
            yield handle, identity
        finally:
            self.events.append(("file-close", str(path)))

    def _read_bounded_handle(self, _api, handle, maximum):
        raw = self.raw_by_path[_path_key(handle[1])]
        if len(raw) > maximum:
            raise AssertionError("bounded fake source exceeds reader maximum")
        self.events.append(("bounded-read", handle[1]))
        return raw

    def _locked_file_identity(self, _api, handle, _private, *, allow_hardlinks):
        assert allow_hardlinks is True
        return self.identities[handle]


def _root_namespace(raw: bytes):
    tree = ast.parse(raw.decode("utf-8", "strict"))
    filtered = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PREP_RESULT"
            for target in node.targets
        ):
            continue
        if isinstance(node, ast.If) and ast.unparse(node.test) == "not PREP_RESULT['host_exit_permitted']":
            continue
        filtered.append(node)
    tree.body = filtered
    ast.fix_missing_locations(tree)
    module = types.ModuleType("__main__")
    module_modules = dict(sys.modules)
    module_modules["__main__"] = module
    runtime_sys = types.SimpleNamespace(
        modules=module_modules,
        argv=[".codex-tmp/optional16_root_preparation_actual_20261009.py"],
        flags=types.SimpleNamespace(isolated=1, no_site=1, interactive=1, utf8_mode=1),
        dont_write_bytecode=True,
        version_info=(3, 11, 5),
        executable=r"C:\anaconda3\python.exe",
    )
    exec(compile(tree, str(ROOT_RUNNER), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    module.__dict__["sys"] = runtime_sys
    return module.__dict__


def _outer_manager(raws: dict[str, bytes], software_raws: dict[str, bytes]):
    events = []
    software_keys = {_path_key(path) for path in software_raws}
    public_raws = {
        path: raw for path, raw in raws.items() if _path_key(path) not in software_keys
    }
    combined_raws = dict(public_raws)
    combined_raws.update(software_raws)
    raw_by_path = {_path_key(path): raw for path, raw in combined_raws.items()}
    _FakePath.data_by_path = raw_by_path
    api = _FakeAPI(events)
    cli = _FakeCLI(events, raw_by_path)
    private = types.SimpleNamespace(_api=lambda: api)

    def fake_load(relative, _pin, name):
        if relative == "backtrader_runtime/certification_roundtrip_private.py":
            return private
        if relative == "backtrader_runtime/certification_binance_roundtrip_r3_cli.py":
            return cli
        raise AssertionError("unexpected fake CUv2 helper source")

    cuv2_raw = raws[str(CU_PATH)]
    cuv2 = _source_module(CU_NAME, CU_PATH, cuv2_raw)
    cuv2.Path = _FakePath
    cuv2.ROOT = _FakePath(ROOT)
    cuv2.load = fake_load
    sys.modules[CU_NAME] = cuv2
    pins = {path: _sha(raw) for path, raw in public_raws.items()}
    software_pins = {path: _sha(raw) for path, raw in software_raws.items()}
    outer = cuv2.held_public_sources(pins, software_pins)
    held = outer.__enter__()
    return outer, held, cuv2, events, api, cli


def _sourcefake_scope(v4, v3, v3_raw: bytes, v4_raw: bytes, *, on_read=None):
    private = types.ModuleType("_reconcile_fake_private")
    private._api = lambda: None
    private._Win32 = type("FakeWin32", (), {})
    private._path = Path
    cli = types.ModuleType("_reconcile_fake_cli")
    cli._locked_readonly_file = lambda *_args, **_kwargs: None
    cli._locked_file_identity = lambda *_args, **_kwargs: None
    cli._read_bounded_handle = lambda *_args, **_kwargs: b""
    original = v3._bootstrap_fixed_helpers
    v3._bootstrap_fixed_helpers = lambda: (private, cli, b"", b"", object(), object())
    try:
        scope = v4.RootHeldScopeV4(enabled=True)
    finally:
        v3._bootstrap_fixed_helpers = original

    source_api = object()
    scope._sourcefake_enter(source_api, v3._SOURCE_FAKE_TOKEN)
    raw_by_handle = {}
    identity_by_handle = {}
    for logical, path, raw in (
        ("held-v3", V3_PATH, v3_raw),
        ("held-v4", V4_PATH, v4_raw),
    ):
        key = v3._path_key(path)
        handle = ("scope-file", logical)
        identity = ("scope-id", logical)
        row = v3._HeldRow(key, logical, path, _sha(raw), 256 * 1024, "public")
        row.handle = handle
        row.identity = identity
        row.size = len(raw)
        scope._rows[key] = row
        scope._logical[logical.casefold()] = key
        scope._bytes[key] = raw
        raw_by_handle[handle] = raw
        identity_by_handle[handle] = identity

    reads = []

    def fake_identity(handle, *, directory=False, allow_hardlinks=False):
        assert directory is False and allow_hardlinks is False
        return identity_by_handle[handle]

    def fake_size(handle):
        return len(raw_by_handle[handle])

    def fake_seek(_handle):
        return None

    def fake_read(_api, handle, maximum):
        raw = raw_by_handle[handle]
        assert len(raw) <= maximum
        reads.append(handle)
        if on_read is not None:
            on_read(len(reads))
        return raw

    scope._identity = fake_identity
    scope._file_size = fake_size
    scope._seek_start = fake_seek
    scope._bounded_reader = fake_read
    return scope, reads


def _fixture(request, *, on_read=None):
    tracked_names = (DRIVER_NAME, CALL_NAME, V3_NAME, V4_NAME, CU_NAME, R1_HELPER_NAME,
                     R2_HELPER_NAME, "_optional16_preparation_reconcile_sourcefake_r3",
                     "_optional16_preparation_reconcile_sourcefake_r4",
                     R3_HELPER_NAME)
    prior_modules = {name: sys.modules.get(name) for name in tracked_names}
    for name in tracked_names:
        sys.modules.pop(name, None)

    def restore_modules():
        for name, prior in prior_modules.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior

    request.addfinalizer(restore_modules)
    helper_raw = _read(HELPER_PATH)
    helper = _source_module("_optional16_preparation_reconcile_sourcefake_r3", HELPER_PATH, helper_raw)
    r4_raw = _read(R4_HELPER_PATH)
    r4_helper = _source_module(
        "_optional16_preparation_reconcile_sourcefake_r4", R4_HELPER_PATH, r4_raw
    )
    r1_raw = _read(R1_HELPER_PATH)
    r1_module = _source_module(R1_HELPER_NAME, R1_HELPER_PATH, r1_raw)
    r2_raw = _read(R2_HELPER_PATH)
    r2_module = _source_module(R2_HELPER_NAME, R2_HELPER_PATH, r2_raw)
    driver_raw = _read(DRIVER_PATH)
    call_raw = _read(CALL_PATH)
    entry_raw = _read(ENTRY_PATH)
    prep_raw = _read(PREPARATION_PATH)
    v3_raw = _read(V3_PATH)
    v4_raw = _read(V4_PATH)
    root_raw = _read(ROOT_RUNNER)
    cu_raw = _read(CU_SNAPSHOT_PATH)
    assert _sha(cu_raw) == CU_SNAPSHOT_SHA256
    preloaded_raws = [(_read(ROOT / relative), relative, digest, name)
                      for relative, digest, name in helper.PRELOADED_SOURCES]

    root_ns = _root_namespace(root_raw)
    driver = root_ns["load"](driver_raw, DRIVER_PATH, DRIVER_NAME)
    entry = driver._load_exact_public_module(
        driver.ENTRY_REL, driver.ENTRY_SHA256, entry_raw, ENTRY_NAME
    )
    entry.ROOT_ENTRY_SOURCE_SHA256 = driver.ENTRY_SHA256
    v4, loaded_v4_raw = entry._load_v4_module()
    assert loaded_v4_raw == v4_raw
    v3 = v4._V3_MODULE
    root_ns["sys"].modules[V3_NAME] = v3
    scope, scope_reads = _sourcefake_scope(v4, v3, v3_raw, v4_raw, on_read=on_read)

    call_module = driver._load_exact_public_module(
        driver.CALL_REL, driver.CALL_SHA256, call_raw, CALL_NAME
    )
    module_sources = {"v3": v3_raw, "v4": v4_raw}
    call_record = (scope, v4, module_sources, prep_raw)
    call_module._RETAINED.append(call_record)
    preloaded = tuple(
        driver._load_exact_public_module(Path(relative), digest, raw, name)
        for raw, relative, digest, name in preloaded_raws
    )
    payload_raw = b'{"sourcefake":"consumed-preparation"}'
    attempt = (
        entry, v4, payload_raw, preloaded, scope, call_module, prep_raw, call_raw, v3_raw, v4_raw
    )
    driver._ATTEMPT_STARTED = True
    driver._OWNER_THREAD = threading.get_ident()
    driver._RETAINED_ATTEMPTS.append(attempt)
    bind_record = root_ns["bind"](driver, driver_raw)

    raws = {
        str(ROOT_RUNNER): root_raw,
        str(DRIVER_PATH): driver_raw,
        str(CALL_PATH): call_raw,
        str(ENTRY_PATH): entry_raw,
        str(PREPARATION_PATH): prep_raw,
        str(V3_PATH): v3_raw,
        str(V4_PATH): v4_raw,
        str(CU_PATH): cu_raw,
    }
    for raw, relative, _digest, _name in preloaded_raws:
        raws[str(ROOT / relative)] = raw
    software_raws = {
        r"C:\anaconda3\python.exe": b"synthetic opaque executable row",
        r"C:\anaconda3\python311.dll": b"synthetic opaque DLL row",
        str(CU_PATH): cu_raw,
    }
    outer, held, cuv2, outer_events, _api, _cli = _outer_manager(raws, software_raws)
    state = {"outer": outer, "held": held, "driver": driver, "bindings": [bind_record]}
    receipt = {
        "schema": "iteration41.optional16.r33.root-preparation-driver.r1",
        "status": "BLOCKED_RETAINED",
        "reason_code": "source_binding_or_preparation_failed",
        "scope_state": "OPEN",
        "authority": "NONE",
        "activation": "NOT_ENTERED",
        "control": "NOT_ENTERED",
        "child": "NOT_ENTERED",
        "worker": "NOT_ENTERED",
        "installer": "NOT_ENTERED",
    }
    result = {
        "schema": "iteration41.optional16.preparation.root_actual.v1",
        "status": "BLOCKED",
        "reason": "source_binding_or_preparation_failed",
        "preparation_invocations": 1,
        "retained_attempts": 1,
        "public_outer_pin_count": 42,
        "software_outer_pin_count": 3,
        "outer_normal_postverify_and_close": False,
        "host_exit_permitted": False,
        "activation": False,
        "provider_call": False,
        "formal_optional16_pass_count": 0,
        "receipt": receipt,
    }
    r1_registry = r1_module._RETAINED
    r1_record = {
        "root_namespace": root_ns,
        "root_state": state,
        "root_result": result,
        "phase": "source_binding_blocked",
        "exit_started": False,
    }
    r1_registry.append(r1_record)
    root_ns["sys"].modules[R1_HELPER_NAME] = r1_module
    root_ns["sys"].modules[R2_HELPER_NAME] = r2_module
    root_ns["PREP_STATE"] = state
    root_ns["PREP_RESULT"] = result
    root_ns["PREP_EXEC"].add(str(ROOT / "scripts/iteration41_optional16_r33_root_preparation_driver_r1.py"))
    sys.modules[helper.__name__] = helper
    r2_held_raws = {str(R2_HELPER_PATH): r2_raw}
    r2_held = (object(), object(), r2_held_raws)
    r2_record = {
        "attempt": attempt,
        "call_module": call_module,
        "call_raw": call_raw,
        "call_record": call_record,
        "cuv2_globals": outer.gen.gi_frame.f_globals,
        "driver": driver,
        "entry": entry,
        "exit_started": False,
        "held": held,
        "module_sources": module_sources,
        "outer": outer,
        "outer_frame": outer.gen.gi_frame,
        "outer_gen": outer.gen,
        "phase": "source_binding_blocked",
        "prep_raw": prep_raw,
        "r1_module": r1_module,
        "r1_raw": r1_raw,
        "r1_record": r1_record,
        "r1_registry": r1_registry,
        "result_snapshot": r2_module._snapshot_json(result),
        "root_namespace": root_ns,
        "root_result": result,
        "root_state": state,
        "scope": scope,
        "v3_raw": v3_raw,
        "v4": v4,
        "v4_raw": v4_raw,
    }
    r2_module._RETAINED.append(r2_record)
    # Preserve aliases the real loaders deliberately retain until teardown.
    return {
        "helper": helper, "root_ns": root_ns, "state": state, "result": result,
        "r4_helper": r4_helper,
        "driver": driver, "attempt": attempt, "entry": entry, "v4": v4,
        "v3": v3, "scope": scope, "scope_reads": scope_reads,
        "call": call_module, "call_record": call_record, "outer": outer,
        "held": held, "cuv2": cuv2, "outer_events": outer_events,
        "software_raws": software_raws,
        "r1_module": r1_module, "r1_registry": r1_registry,
        "r1_record": r1_record, "r1_raw": r1_raw,
        "r2_module": r2_module, "r2_registry": r2_module._RETAINED,
        "r2_record": r2_record, "r2_held": r2_held, "r2_raw": r2_raw,
    }


def _freeze(value):
    if type(value) in (str, bytes, int, bool, float, complex, type(None)):
        return (type(value), value)
    if type(value) in (tuple, list):
        return (type(value), tuple(_freeze(item) for item in value))
    if type(value) is dict:
        return (dict, tuple((_freeze(key), _freeze(item)) for key, item in value.items()))
    if type(value) in (set, frozenset):
        return (type(value), frozenset(_freeze(item) for item in value))
    return (type(value), id(value))


def _function_state(function):
    return (
        function, function.__code__, function.__globals__, function.__module__,
        function.__name__, function.__qualname__, _freeze(function.__defaults__),
        _freeze(function.__kwdefaults__), _freeze(function.__annotations__),
        _freeze(function.__dict__), function.__closure__,
        tuple(_freeze(cell.cell_contents) for cell in function.__closure__ or ()),
    )


def _capture_helper(module):
    functions = tuple(
        (name, _function_state(value))
        for name, value in module.__dict__.items()
        if type(value) is types.FunctionType and value.__module__ == module.__name__
    )
    globals_state = {
        key: _freeze(value) for key, value in module.__dict__.items() if key != "_RETAINED"
    }
    return functions, globals_state, module._RETAINED


def _closed_test_scope():
    @contextlib.contextmanager
    def manager():
        yield (None, None, {})

    value = manager()
    value.__enter__()
    assert value.__exit__(None, None, None) is False
    return value


def _prepare_failed_r3_state(fixture):
    raw = _read(HELPER_PATH)
    module = _source_module(R3_HELPER_NAME, HELPER_PATH, raw)
    sys.modules[module.__name__] = module
    fixture["root_ns"]["sys"].modules[module.__name__] = module
    receipt = module.reconcile_retained_preparation_r3(
        fixture["root_ns"], fixture["state"], fixture["result"],
        fixture["r1_module"], fixture["r1_registry"], fixture["r1_raw"],
        fixture["r2_module"], fixture["r2_registry"], fixture["r2_held"],
        fixture["r2_raw"], requested=True, _sourcefake_token=module._SOURCEFAKE_TOKEN,
    )
    assert receipt["status"] == "BLOCKED_RETAINED"
    assert receipt["phase"] == "source_binding"
    assert receipt["reason_code"] == "inner_binding_failed"
    assert fixture["scope"].state == "OPEN"
    assert fixture["outer"].gen.gi_frame is not None
    review_scope = _closed_test_scope()
    held = (None, None, {str(HELPER_PATH): raw})
    state = {
        "review_scope": review_scope,
        "held": held,
        "original_state": fixture["state"],
        "original_result": fixture["result"],
        "original_attempt": fixture["attempt"],
        "original_call_record": fixture["call_record"],
        "original_gen": fixture["outer"].gen,
        "helper": module,
        "binding": _capture_helper(module),
        "original_scope": fixture["scope"],
        "receipt": receipt,
        "observation": {"receipt": receipt},
    }
    fixture["root_ns"]["RECONCILIATION_ROOT_STATE_R3"] = state
    fixture["r3_helper"] = module
    fixture["r3_state"] = state
    fixture["r3_raw"] = raw
    return state


def _install_original_root_audit(fixture):
    root_ns = fixture["root_ns"]
    expected = root_ns["PREP_CODES"]
    expected.clear()
    root_origin = str(ROOT_RUNNER.resolve())
    for path, raw in fixture["held"][2].items():
        path_text = str(path)
        if not path_text.lower().endswith(".py") or _path_key(path_text) == _path_key(root_origin):
            continue
        # Repository paths are resolved as in the original runner. The CUv2
        # fixture uses only its pinned public snapshot bytes and a lexical
        # D:/temp origin; it never reads that path.
        origin = str(Path(path_text).resolve()) if _path_key(path_text).startswith(_path_key(ROOT)) else str(Path(path_text))
        expected[origin] = compile(raw, origin, "exec", dont_inherit=True)
    assert any(_path_key(path) == _path_key(V4_PATH) for path in expected)
    sys.addaudithook(root_ns["audit"])
    return expected


def _run(fixture):
    return fixture["helper"].reconcile_retained_preparation_r3(
        fixture["root_ns"], fixture["state"], fixture["result"],
        fixture["r1_module"], fixture["r1_registry"], fixture["r1_raw"],
        fixture["r2_module"], fixture["r2_registry"], fixture["r2_held"], fixture["r2_raw"],
        requested=True, _sourcefake_token=fixture["helper"]._SOURCEFAKE_TOKEN,
    )


def _production_derived_outer_maps(fixture):
    helper = fixture["helper"]
    root_ns = fixture["root_ns"]
    root_raw = _read(ROOT_RUNNER)
    index_path = ROOT / (root_ns["P"] + "source-index.json")
    index_raw = _read(index_path)
    assert _sha(index_raw) == root_ns["SUPPORT"][root_ns["P"] + "source-index.json"]
    index = json.loads(index_raw)
    rows = index["candidate_sources"] + index["fixed_dependencies"]
    pins = {row["path"]: row["sha256"] for row in rows}
    pins.update(root_ns["SUPPORT"])
    own = ROOT_RUNNER.resolve().relative_to(ROOT).as_posix()
    pins[own] = _sha(root_raw)
    assert len(pins) == 42
    assert pins[helper.ROOT_RUNNER_REL] == helper.ROOT_RUNNER_SHA256

    public_raws = {}
    for relative, digest in pins.items():
        raw = _read(ROOT / relative)
        assert _sha(raw) == digest
        public_raws[str(ROOT / relative)] = raw

    software = root_ns["SOFTWARE"]
    assert software == helper.SOFTWARE
    cu_key = str(root_ns["CU"])
    assert cu_key in software
    assert cu_key == str(Path(helper.CUV2_REL))
    assert cu_key != helper.CUV2_REL
    assert _path_key(cu_key) == _path_key(helper.CUV2_REL)
    # The executable and DLL rows stay opaque sentinels. CUv2 bytes come from
    # the indexed public source snapshot, never the D:/temp file.
    software_raws = {
        "C:/anaconda3/python.exe": b"opaque executable placeholder; never read",
        "C:/anaconda3/python311.dll": b"opaque DLL placeholder; never read",
        cu_key: _read(CU_SNAPSHOT_PATH),
    }
    assert _sha(software_raws[cu_key]) == helper.CUV2_SHA256
    raw_map = dict(public_raws)
    raw_map.update(software_raws)
    expected_keys = {_path_key(ROOT / path) for path in pins}
    expected_keys.update(_path_key(path) for path in software)
    all_pins = {_path_key(ROOT / path): digest for path, digest in pins.items()}
    all_pins.update({_path_key(path): digest for path, digest in software.items()})
    identities = {key: ("fake-file-id", index) for index, key in enumerate(sorted(expected_keys))}
    frame_locals = {
        "pins": pins,
        "software_pins": software,
        "all_pins": all_pins,
        "identities": identities,
    }
    assert {_path_key(path) for path in raw_map} == expected_keys
    return root_ns, raw_map, frame_locals


def test_cuv2_loaded_helper_modules_bind_to_public_sources_without_native_api_use():
    helper_raw = _read(HELPER_PATH)
    helper = _source_module("_optional16_reconcile_helper_source_probe", HELPER_PATH, helper_raw)
    prior = {helper.CU_PRIVATE_NAME: sys.modules.get(helper.CU_PRIVATE_NAME),
             helper.CU_CLI_NAME: sys.modules.get(helper.CU_CLI_NAME)}
    try:
        for relative, name, digest in (
            ("backtrader_runtime/certification_roundtrip_private.py",
             helper.CU_PRIVATE_NAME, helper.CU_PRIVATE_SHA256),
            ("backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
             helper.CU_CLI_NAME, helper.CU_CLI_SHA256),
        ):
            path = ROOT / relative
            raw = _read(path)
            module = types.ModuleType(name)
            module.__file__ = str(path)
            sys.modules[name] = module
            exec(compile(raw, str(path), "exec", dont_inherit=True),
                 module.__dict__, module.__dict__)
            assert hashlib.sha256(raw).hexdigest() == digest
            helper._simple_module_source(module, raw, name, str(path), digest)
            if name == helper.CU_PRIVATE_NAME:
                assert module._API is None
    finally:
        for name, old in prior.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def test_sourcefake_reconciles_actual_v3_and_cuv2_normal_exit_once(request):
    fixture = _fixture(request)
    original = dict(fixture["result"])
    result = _run(fixture)

    assert result["status"] == "ROOT_SOURCE_CUSTODY_CLOSED"
    assert result["inner_release"] is True and result["outer_normal_exit"] is True
    assert result["formal_optional16_pass_count"] == 0
    assert result["authority"] == "NONE" and result["activation"] == "NOT_ENTERED"
    assert result["original_result_mutated"] is False
    assert result["historical_run_assignment_identity_proven"] is False
    assert result["r1_registry_preserved"] is True and result["r1_retry"] == "NOT_ENTERED"
    assert fixture["result"] == original
    assert "__file__" not in fixture["root_ns"]
    assert fixture["r1_module"]._RETAINED is fixture["r1_registry"]
    assert len(fixture["r1_registry"]) == 1
    assert fixture["r1_registry"][0] is fixture["r1_record"]
    assert fixture["r2_module"]._RETAINED is fixture["r2_registry"]
    assert len(fixture["r2_registry"]) == 1
    assert fixture["r2_registry"][0] is fixture["r2_record"]
    assert result["r2_registry_preserved"] is True
    assert result["r2_retry"] == "NOT_ENTERED"
    assert fixture["root_ns"]["sys"].modules[R2_HELPER_NAME] is fixture["r2_module"]
    assert fixture["scope"].state == "CLOSED" and fixture["scope"]._postverified is True
    assert fixture["scope"] not in fixture["v3"]._RETAINED_SCOPES
    assert fixture["outer"].gen.gi_frame is None
    assert sum(event[0] == "file-open" for event in fixture["outer_events"]) == 13
    assert sum(event[0] == "file-close" for event in fixture["outer_events"]) == 13
    assert len(fixture["scope_reads"]) == 4
    second = _run(fixture)
    assert second["status"] == "BLOCKED_ALREADY_USED"
    assert len(fixture["scope_reads"]) == 4


def test_full_outer_map_fixture_matches_frozen_root_construction_and_r3_key(request):
    fixture = _fixture(request)
    root_ns, raw_map, frame_locals = _production_derived_outer_maps(fixture)
    helper = fixture["helper"]

    helper._exact_outer_maps(root_ns, raw_map, frame_locals, sourcefake=True)

    assert len(frame_locals["pins"]) == 42
    assert len(frame_locals["software_pins"]) == 3
    assert len(frame_locals["all_pins"]) == 45
    assert frame_locals["software_pins"] is root_ns["SOFTWARE"]
    assert root_ns["SOFTWARE"] == helper.SOFTWARE
    assert str(root_ns["CU"]) in root_ns["SOFTWARE"]
    assert str(root_ns["CU"]) not in fixture["r2_module"].SOFTWARE
    assert fixture["r2_module"].CUV2_REL in fixture["r2_module"].SOFTWARE
    assert fixture["r2_module"]._key(fixture["r2_module"].CUV2_REL) == _path_key(root_ns["CU"])
    assert fixture["scope"].state == "OPEN"
    assert fixture["scope_reads"] == []


@pytest.mark.parametrize("mutation", ["r2_slash_key", "unrelated_key", "wrong_digest"])
def test_full_outer_map_fixture_rejects_nonproduction_software_map(request, mutation):
    fixture = _fixture(request)
    root_ns, raw_map, frame_locals = _production_derived_outer_maps(fixture)
    software = frame_locals["software_pins"]
    cu_key = str(root_ns["CU"])
    digest = software.pop(cu_key)
    if mutation == "r2_slash_key":
        software[fixture["helper"].CUV2_REL] = digest
    elif mutation == "unrelated_key":
        software["D:/other/unrelated.exe"] = digest
    else:
        software[cu_key] = "0" * 64

    with pytest.raises(fixture["helper"].ReconciliationError):
        fixture["helper"]._exact_outer_maps(root_ns, raw_map, frame_locals, sourcefake=True)
    assert fixture["scope"].state == "OPEN"
    assert fixture["scope_reads"] == []


@pytest.mark.parametrize("mutation", [
    "attempt", "preloaded", "call_tuple", "result_global", "call_global", "v3_alias",
    "source_bytes", "outer_pin_values", "outer_public_raw", "scope_release_shadow",
])
def test_pre_release_binding_mutations_retain_both_open_scopes(request, mutation):
    fixture = _fixture(request)
    if mutation == "attempt":
        fixture["driver"]._RETAINED_ATTEMPTS[0] = (*fixture["attempt"][:1], object(), *fixture["attempt"][2:])
    elif mutation == "preloaded":
        fixture["driver"]._RETAINED_ATTEMPTS[0] = (
            *fixture["attempt"][:3], (object(), *fixture["attempt"][3][1:]),
            *fixture["attempt"][4:]
        )
    elif mutation == "call_tuple":
        fixture["call"]._RETAINED[0] = (*fixture["call_record"][:1], object(), *fixture["call_record"][2:])
    elif mutation == "result_global":
        fixture["root_ns"]["PREP_RESULT"] = dict(fixture["result"])
    elif mutation == "call_global":
        fixture["call"].SCHEMA = "changed"
    elif mutation == "v3_alias":
        fixture["v4"]._V3_MODULE = types.ModuleType(V3_NAME)
    elif mutation == "outer_pin_values":
        pins = fixture["outer"].gen.gi_frame.f_locals["pins"]
        first_path = next(iter(pins))
        pins[first_path] = "0" * 64
    elif mutation == "outer_public_raw":
        raw_map = fixture["held"][2]
        root_key = next(path for path in raw_map if _path_key(path) == _path_key(ROOT_RUNNER))
        changed = bytearray(raw_map[root_key])
        changed[-1] ^= 1
        raw_map[root_key] = bytes(changed)
    elif mutation == "scope_release_shadow":
        fixture["scope"].release = lambda *_args: True
    else:
        changed = bytearray(fixture["attempt"][7])
        changed[-1] ^= 1
        fixture["driver"]._RETAINED_ATTEMPTS[0] = (*fixture["attempt"][:7], bytes(changed), *fixture["attempt"][8:])

    result = _run(fixture)
    assert result["status"] == "BLOCKED_RETAINED"
    assert result["inner_release"] is False and result["outer_normal_exit"] is False
    assert fixture["scope"].state == "OPEN"
    assert fixture["outer"].gen.gi_frame is not None
    assert fixture["scope_reads"] == []


@pytest.mark.parametrize("mutation", ["raw_bytes", "pin_digest"])
def test_software_rows_are_hash_checked_as_opaque_bytes(request, mutation):
    fixture = _fixture(request)
    frame_locals = fixture["outer"].gen.gi_frame.f_locals
    software_pins = frame_locals["software_pins"]
    raw_map = frame_locals["raw_bytes"]
    target = next(path for path in software_pins
                  if path.casefold().endswith("python.exe"))
    if mutation == "raw_bytes":
        raw_key = next(path for path in raw_map if _path_key(path) == _path_key(target))
        raw_map[raw_key] = b"mutated opaque executable row"
    else:
        software_pins[target] = "0" * 64

    result = _run(fixture)
    assert result["status"] == "BLOCKED_RETAINED"
    assert result["phase"] == "source_binding"
    assert fixture["scope"].state == "OPEN"
    assert fixture["scope_reads"] == []
    assert fixture["outer"].gen.gi_frame is not None


@pytest.mark.parametrize("kind", ["code", "globals"])
def test_driver_function_code_and_globals_drift_is_rejected_before_release(request, kind):
    fixture = _fixture(request)

    original = fixture["driver"]._safe_failure_code
    if kind == "code":
        def substituted(*_args, **_kwargs):
            return None
    else:
        substituted = types.FunctionType(original.__code__, {}, original.__name__)
        substituted.__qualname__ = original.__qualname__
        substituted.__module__ = original.__module__
    fixture["driver"]._safe_failure_code = substituted
    result = _run(fixture)
    assert result["status"] == "BLOCKED_RETAINED"
    assert fixture["scope"].state == "OPEN"
    assert fixture["scope_reads"] == []


def test_outer_exit_callback_drift_after_inner_release_does_not_call_exit(request):
    original_exit = contextlib._GeneratorContextManager.__exit__
    changed = []

    def mutate_exit(read_count):
        if read_count == 4:
            contextlib._GeneratorContextManager.__exit__ = substituted_exit
            changed.append(True)

    def substituted_exit(self, exc_type, exc, traceback):
        return original_exit(self, exc_type, exc, traceback)

    fixture = _fixture(request, on_read=mutate_exit)
    try:
        result = _run(fixture)
        assert changed == [True]
        assert result["status"] == "BLOCKED_RETAINED"
        assert result["inner_release"] is True and result["outer_normal_exit"] is False
        assert fixture["scope"].state == "CLOSED"
        assert fixture["outer"].gen.gi_frame is not None
    finally:
        contextlib._GeneratorContextManager.__exit__ = original_exit
        if fixture["outer"].gen.gi_frame is not None:
            assert fixture["outer"].__exit__(None, None, None) is False


def test_outer_generator_replacement_during_last_held_read_blocks_before_exit(request):
    state = {}
    replacement = None

    def suspended_replacement():
        yield "sentinel"

    replacement = suspended_replacement()
    next(replacement)

    def replace_generator(read_count):
        if read_count == 4:
            state["outer"].gen = replacement

    fixture = _fixture(request, on_read=replace_generator)
    state["outer"] = fixture["outer"]
    original_gen = fixture["outer"].gen
    original_frame = original_gen.gi_frame
    result = _run(fixture)

    assert result["status"] == "BLOCKED_RETAINED"
    assert result["phase"] == "inner_poststate"
    assert result["inner_release"] is True and result["outer_normal_exit"] is False
    assert fixture["outer"].gen is replacement
    assert original_gen is fixture["helper"]._RETAINED[0]["outer_gen"]
    assert original_gen.gi_frame is original_frame and original_frame is not None
    assert original_gen.gi_suspended is True

    # Test cleanup uses the already captured standard method against the exact
    # original generator. Production reconciliation does not take this path.
    fixture["outer"].gen = original_gen
    assert fixture["helper"]._RETAINED[0]["outer_exit_method"](None, None, None) is False
    assert original_gen.gi_frame is None
    replacement.close()


def test_outer_generator_replacement_during_binding_keeps_both_scopes_open(request):
    fixture = _fixture(request)
    original_gen = fixture["outer"].gen
    original_frame = original_gen.gi_frame
    original_verify = fixture["helper"]._verify_outer_context

    def replacement_generator():
        yield "sentinel"

    replacement = replacement_generator()
    next(replacement)

    def replace_after_binding(outer, *args, **kwargs):
        verified = original_verify(outer, *args, **kwargs)
        outer.gen = replacement
        return verified

    fixture["helper"]._verify_outer_context = replace_after_binding
    result = _run(fixture)

    assert result["status"] == "BLOCKED_RETAINED"
    assert result["phase"] == "source_binding"
    assert result["inner_release"] is False and result["outer_normal_exit"] is False
    assert fixture["scope"].state == "OPEN"
    assert fixture["scope_reads"] == []
    assert fixture["outer"].gen is replacement
    assert fixture["helper"]._RETAINED[0]["outer_gen"] is original_gen
    assert original_gen.gi_frame is original_frame and original_frame is not None

    fixture["outer"].gen = original_gen
    assert fixture["outer"].__exit__(None, None, None) is False
    replacement.close()


@pytest.mark.parametrize("mutation", [
    "argv", "isolated_flag", "no_site_flag", "interactive_flag", "utf8_flag",
    "bytecode_flag", "version", "executable",
    "module_name", "main_binding", "reinserted_file",
])
def test_missing_file_is_accepted_only_for_exact_interactive_root_origin(request, mutation):
    fixture = _fixture(request)
    root_ns = fixture["root_ns"]
    runtime_sys = root_ns["sys"]
    if mutation == "argv":
        runtime_sys.argv[0] = ".codex-tmp/other.py"
    elif mutation == "isolated_flag":
        runtime_sys.flags.isolated = 0
    elif mutation == "no_site_flag":
        runtime_sys.flags.no_site = 0
    elif mutation == "interactive_flag":
        runtime_sys.flags.interactive = 0
    elif mutation == "utf8_flag":
        runtime_sys.flags.utf8_mode = 0
    elif mutation == "bytecode_flag":
        runtime_sys.dont_write_bytecode = False
    elif mutation == "version":
        runtime_sys.version_info = (3, 12, 0)
    elif mutation == "executable":
        runtime_sys.executable = r"C:\other\python.exe"
    elif mutation == "module_name":
        root_ns["__name__"] = "_unrelated_module"
    elif mutation == "main_binding":
        runtime_sys.modules["__main__"] = types.ModuleType("__main__")
    else:
        root_ns["__file__"] = str(ROOT / "scripts/unrelated.py")

    result = _run(fixture)
    assert result["status"] == "BLOCKED_RETAINED"
    assert result["phase"] == "source_binding"
    assert result["inner_release"] is False and result["outer_normal_exit"] is False
    assert fixture["scope"].state == "OPEN"
    assert fixture["scope_reads"] == []
    assert fixture["outer"].gen.gi_frame is not None


@pytest.mark.parametrize("mutation", [
    "record", "registry", "module_code", "source_bytes",
    "module_alias_replaced", "module_alias_missing",
])
def test_prior_r1_consumed_registry_and_source_mutations_block_without_release(request, mutation):
    fixture = _fixture(request)
    if mutation == "record":
        fixture["r1_record"]["phase"] = "changed"
    elif mutation == "registry":
        fixture["r1_module"]._RETAINED = []
    elif mutation == "module_code":
        fixture["r1_module"]._sha = lambda _raw: "changed"
    elif mutation == "module_alias_replaced":
        fixture["root_ns"]["sys"].modules[R1_HELPER_NAME] = types.ModuleType(R1_HELPER_NAME)
    elif mutation == "module_alias_missing":
        fixture["root_ns"]["sys"].modules.pop(R1_HELPER_NAME)
    else:
        changed = bytearray(fixture["r1_raw"])
        changed[-1] ^= 1
        fixture["r1_raw"] = bytes(changed)

    result = _run(fixture)
    assert result["status"] == "BLOCKED_RETAINED"
    assert result["phase"] == "source_binding"
    assert result["inner_release"] is False and result["outer_normal_exit"] is False
    assert fixture["scope"].state == "OPEN"
    assert fixture["scope_reads"] == []
    assert fixture["outer"].gen.gi_frame is not None


@pytest.mark.parametrize("mutation", [
    "alias_replaced", "alias_missing", "record_phase", "registry", "source_bytes",
])
def test_consumed_r2_module_registry_and_source_mutations_block_before_release(request, mutation):
    fixture = _fixture(request)
    if mutation == "alias_replaced":
        fixture["root_ns"]["sys"].modules[R2_HELPER_NAME] = types.ModuleType(R2_HELPER_NAME)
    elif mutation == "alias_missing":
        fixture["root_ns"]["sys"].modules.pop(R2_HELPER_NAME)
    elif mutation == "record_phase":
        fixture["r2_record"]["phase"] = "changed"
    elif mutation == "registry":
        fixture["r2_module"]._RETAINED = []
    else:
        changed = bytearray(fixture["r2_raw"])
        changed[-1] ^= 1
        fixture["r2_raw"] = bytes(changed)

    result = _run(fixture)
    assert result["status"] == "BLOCKED_RETAINED"
    assert result["phase"] == "source_binding"
    assert result["inner_release"] is False and result["outer_normal_exit"] is False
    assert fixture["scope"].state == "OPEN"
    assert fixture["scope_reads"] == []
    assert fixture["outer"].gen.gi_frame is not None


def test_inner_release_failure_keeps_outer_context_suspended_and_reports_lease_limit(request):
    def fail_on_release_read(read_count):
        if read_count == 3:
            raise OSError("synthetic held-source read failure")

    fixture = _fixture(request, on_read=fail_on_release_read)
    result = _run(fixture)

    assert result["status"] == "BLOCKED_RETAINED"
    assert result["phase"] == "inner_release"
    assert result["physical_file_lease_state"] == "INNER_SCOPE_OPEN_OR_PARTIAL"
    assert result["inner_release"] is False and result["outer_normal_exit"] is False
    assert fixture["scope"].state == "RETAINED"
    assert fixture["outer"].gen.gi_frame is not None


def test_z_original_root_audit_rejects_r3_transform_and_r4_exact_loader_closes_once(request):
    # This is the last test in the focused module because audit hooks cannot be
    # removed. The pytest process exits immediately after the sourcefake focus.
    fixture = _fixture(request)
    expected = _install_original_root_audit(fixture)

    # Reproduce the consumed R3 defect directly: its AST rewrite executes a
    # different code object at the held V4 filename and the original Root hook
    # rejects it before any source scope is released.
    v3_reference = fixture["call"]._make_module(
        V3_NAME, Path("scripts/iteration41_root_held_source_scope_v3.py"),
        fixture["attempt"][8], fixture["call"].V3_SHA256,
    )
    with pytest.raises(fixture["call"].RootPreparationCallError, match="v4_reference_compile_failed"):
        fixture["call"]._v4_reference(v3_reference, fixture["attempt"][9])
    original_v3 = fixture["v3"]
    assert sys.modules[V3_NAME] is original_v3
    assert fixture["root_ns"]["PREP_CODES"] is expected

    r3_state = _prepare_failed_r3_state(fixture)
    assert r3_state["receipt"]["reason_code"] == "inner_binding_failed"
    r3_record = r3_state["helper"]._RETAINED[0]
    assert r3_record["phase"] == "inner_scope_retained"
    assert "v3" not in r3_record and "module_source_reference_verified" not in r3_record

    # A replaced canonical helper alias must fail before R4 reads the inner
    # scope or calls its release API. The source audit remains installed.
    root_modules = fixture["root_ns"]["sys"].modules
    root_modules[R3_HELPER_NAME] = types.ModuleType(R3_HELPER_NAME)
    blocked = fixture["r4_helper"].reconcile_retained_preparation_r4(
        fixture["root_ns"], fixture["state"], fixture["result"], r3_state,
        requested=True, _sourcefake_token=fixture["r4_helper"]._SOURCEFAKE_TOKEN,
    )
    assert blocked["status"] == "BLOCKED_RETAINED"
    assert blocked["phase"] == "source_binding"
    assert fixture["scope"].state == "OPEN" and fixture["scope_reads"] == []
    assert fixture["outer"].gen.gi_frame is not None
    root_modules[R3_HELPER_NAME] = r3_state["helper"]

    # A fresh fake generation exercises the corrected path with a newly
    # authenticated R3 state. R4 compiles V3 independently, temporarily binds
    # that reference at the canonical alias, and feeds the unchanged V4 source
    # through Call R1's production loader under the same Root audit.
    accepted_fixture = _fixture(request)
    accepted_state = _prepare_failed_r3_state(accepted_fixture)
    accepted_r3 = accepted_state["helper"]
    accepted_record = accepted_r3._RETAINED[0]
    accepted_v3 = accepted_fixture["v3"]
    original_result = dict(accepted_fixture["result"])
    r4 = accepted_fixture["r4_helper"]
    result = r4.reconcile_retained_preparation_r4(
        accepted_fixture["root_ns"], accepted_fixture["state"],
        accepted_fixture["result"], accepted_state,
        requested=True, _sourcefake_token=r4._SOURCEFAKE_TOKEN,
    )

    assert result["status"] == "ROOT_SOURCE_CUSTODY_CLOSED"
    assert result["inner_release"] is True and result["outer_normal_exit"] is True
    assert result["r1_registry_preserved"] is True and result["r1_retry"] == "NOT_ENTERED"
    assert result["r2_registry_preserved"] is True and result["r2_retry"] == "NOT_ENTERED"
    assert result["r3_registry_preserved"] is True and result["r3_retry"] == "NOT_ENTERED"
    assert result["historical_run_assignment_identity_proven"] is False
    assert result["authority"] == "NONE" and result["formal_optional16_pass_count"] == 0
    assert accepted_fixture["result"] == original_result
    assert accepted_fixture["scope"].state == "CLOSED"
    assert accepted_fixture["scope"] not in accepted_v3._RETAINED_SCOPES
    assert accepted_fixture["outer"].gen.gi_frame is None
    assert sys.modules[V3_NAME] is accepted_v3
    assert accepted_fixture["root_ns"]["sys"].modules[V3_NAME] is accepted_v3
    assert accepted_fixture["v4"]._V3_MODULE is accepted_v3
    assert accepted_r3._RETAINED is accepted_state["binding"][2]
    assert len(accepted_r3._RETAINED) == 1
    assert accepted_r3._RETAINED[0] is accepted_record
    assert accepted_record["phase"] == "inner_scope_retained"
    assert accepted_record["exit_started"] is False
    assert accepted_fixture["r1_registry"][0] is accepted_fixture["r1_record"]
    assert accepted_fixture["r2_registry"][0] is accepted_fixture["r2_record"]
    assert accepted_fixture["scope_reads"] == [
        ("scope-file", "held-v3"), ("scope-file", "held-v4"),
        ("scope-file", "held-v3"), ("scope-file", "held-v4"),
    ]
    assert accepted_state["review_scope"].gen.gi_frame is None

