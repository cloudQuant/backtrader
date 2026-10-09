"""Production-loaded, source-fake checks for C01 RootV17 ownership APIs."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import sys
import tempfile
from types import FunctionType, MappingProxyType, ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT_REL = "backtrader_runtime/certification_simnow_c01_root_v17.py"
CUSTODY_REL = "backtrader_runtime/certification_simnow_c01_root_custody_v17.py"
HANDOFF_REL = "backtrader_runtime/certification_simnow_c01_rootseal_custody_v1.py"
VALIDATOR_REL = "examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py"
PROTOCOL_REL = "backtrader_runtime/certification_simnow_c01_v3_protocol.py"
WORKER_REL = "backtrader_runtime/certification_simnow_c01_native_v4.py"
V19_REL = "backtrader_runtime/certification_simnow_c01_native_td_read_v19.py"
V20_REL = "backtrader_runtime/certification_simnow_c01_native_td_read_v20.py"
SUPERVISOR_REL = "backtrader_runtime/certification_simnow_c01_v4_supervisor.py"
WRAPPER_REL = "scripts/run_simnow_c01_native_td_read_v20_root_activation_r1.py"
FRONT_REL = "backtrader_runtime/certification_simnow_c01_front_transport_v14.py"
RUNNER_REL = "examples/000_live_certification/simnow_penetration/cases/C01/run_v20.py"
OWNER_REL = "backtrader_runtime/certification_simnow_c01_v7_owner.py"
V20_HELPERS = {
    "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py": "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1",
    "backtrader_runtime/certification_simnow_c01_v3_contract.py": "backtrader_runtime.certification_simnow_c01_v3_contract",
    "backtrader_runtime/certification_roundtrip_private.py": "backtrader_runtime.certification_roundtrip_private",
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": "backtrader_runtime.certification_binance_roundtrip_r3_cli",
    "backtrader_runtime/ctp_front_pair_probe.py": "backtrader_runtime.ctp_front_pair_probe",
    "scripts/ctp_000_render_config.py": "scripts.ctp_000_render_config",
    "scripts/ctp_000_paired_front_selector.py": "scripts.ctp_000_paired_front_selector",
    "scripts/ctp_000_front_handoff.py": "scripts.ctp_000_front_handoff",
    "scripts/ctp_i13_i15_outer_watchdog.py": "scripts.ctp_i13_i15_outer_watchdog",
    "scripts/ctp_i13_i15_windows_job_backend.py": "scripts.ctp_i13_i15_windows_job_backend",
}

_SOURCE = {
    VALIDATOR_REL: b"class C01ValidatedContent: pass\n",
    PROTOCOL_REL: b"""\
class C01PairBindingRef:
    def __init__(self, value): self.value = dict(value)
    def to_dict(self): return dict(self.value)
class C01PairBinding:
    def __init__(self, value): self.value = dict(value)
    def to_receipt_ref(self): return C01PairBindingRef(self.value)
class C01CandidateValidation: pass
class C01WorkerReceipt: pass
""",
    WORKER_REL: b"def project_order_economics(value): return value\n",
    V19_REL: b"class _C01V19Admission: pass\n",
    V20_REL: b"""\
class _C01V20Admission:
    def __init__(self, bindings):
        self.bindings = bindings
        self.configured_front_pair_count = 5
class C01NativeTdReadV20Result:
    def __init__(self):
        self.status = 'PASS'
        self.reason = 'read_only_candidate_complete'
        self.profile = 'C01_NATIVE_TD_READ_V20'
        self.case_id = 'C01'
        self.writes = 0
        self.admission_failure_stage = 'none'
        self.admission_failure_class = 'none'
        self.post_worker_failure_stage = 'none'
        self.post_worker_failure_code = 'none'
""",
    SUPERVISOR_REL: b"class C01SupervisorResult:\n    def __init__(self, worker_receipt): self.worker_receipt = worker_receipt\n",
    WRAPPER_REL: b"""\
import io
import os
_C01_V20_FRAME_CHANNEL_FACTORY = object()
class C01V20FrameChannelReceipt:
    __slots__ = ('scope', 'channel', 'stream', 'nonce', 'used', 'direction', 'process_id', '_factory')
    def __init__(self, scope, stream, *, _factory=None):
        if _factory is not _C01_V20_FRAME_CHANNEL_FACTORY: raise ValueError('factory')
        self.scope = scope
        self.channel = stream
        self.stream = stream
        self.nonce = object()
        self.used = False
        self.direction = 'child_to_root'
        self.process_id = os.getpid()
        self._factory = _C01_V20_FRAME_CHANNEL_FACTORY
    def consume_root_frame_writer(self, scope):
        if (self._factory is not _C01_V20_FRAME_CHANNEL_FACTORY or self.used
            or self.scope is not scope or self.process_id != os.getpid()
            or self.direction != 'child_to_root' or self.channel is not self.stream
            or type(self.stream) is not io.FileIO or self.stream.closed
            or not self.stream.writable() or scope.active is not True
            or scope.issuer_returned is not True or scope.pending is None
            or scope.root_content_stage is None or scope.root_content_seal is None
            or scope.consumed is not False):
            raise ValueError('invalid')
        self.used = True
        return self.stream
""",
}
_SOURCE[FRONT_REL] = b"def source_fake_binding(): return None\n"
_SOURCE[RUNNER_REL] = b"def invoke_v20_issuer(issuer, scope, owner, helpers): return issuer\n"
_SOURCE.update(
    {
        relative: b"def source_fake_binding(): return None\n"
        for relative in V20_HELPERS
    }
)
_SOURCE[OWNER_REL] = b"def _now_utc(): return '2026-10-09T00:00:00Z'\n"
WRAPPER_SOURCE = _SOURCE[WRAPPER_REL]


def _load_source_module(name: str, relative: str, source: bytes) -> ModuleType:
    path = REPO_ROOT.joinpath(*relative.split("/"))
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
    prior = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(compile(source, str(path), "exec", dont_inherit=True), module.__dict__)
    finally:
        if prior is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prior
    module.__c01_source_sha256__ = hashlib.sha256(source).hexdigest()
    return module


def _load_actual_module(name: str, relative: str) -> tuple[ModuleType, bytes]:
    path = REPO_ROOT.joinpath(*relative.split("/"))
    source = path.read_bytes()
    return _load_source_module(name, relative, source), source


def _environment():
    root, root_bytes = _load_actual_module(
        "backtrader_runtime.certification_simnow_c01_root_v17", ROOT_REL
    )
    custody, custody_bytes = _load_actual_module(
        "backtrader_runtime.certification_simnow_c01_root_custody_v17", CUSTODY_REL
    )
    handoff, handoff_bytes = _load_actual_module(
        "backtrader_runtime.certification_simnow_c01_rootseal_custody_v1", HANDOFF_REL
    )
    names = {
        VALIDATOR_REL: "common.c01_root_ledger_v1",
        PROTOCOL_REL: "backtrader_runtime.certification_simnow_c01_v3_protocol",
        WORKER_REL: "backtrader_runtime.certification_simnow_c01_native_v4",
        V19_REL: "backtrader_runtime.certification_simnow_c01_native_td_read_v19",
        V20_REL: "backtrader_runtime.certification_simnow_c01_native_td_read_v20",
        SUPERVISOR_REL: "backtrader_runtime.certification_simnow_c01_v4_supervisor",
        WRAPPER_REL: "scripts.run_simnow_c01_native_td_read_v20_root_activation_r1",
        FRONT_REL: "backtrader_runtime.certification_simnow_c01_front_transport_v14",
        RUNNER_REL: "examples.000_live_certification.simnow_penetration.cases.C01.run_v20",
        OWNER_REL: "backtrader_runtime._c01_native_td_read_v7_owner",
        **V20_HELPERS,
    }
    source_by_path = {
        ROOT_REL: root_bytes,
        CUSTODY_REL: custody_bytes,
        HANDOFF_REL: handoff_bytes,
        **_SOURCE,
    }
    modules = {
        ROOT_REL: root,
        CUSTODY_REL: custody,
        HANDOFF_REL: handoff,
    }
    for relative, name in names.items():
        modules[relative] = _load_source_module(name, relative, source_by_path[relative])
    root._FIXED_SOURCE_PINS = MappingProxyType({})
    scope = root.create_c01_root_invocation_scope(root, modules, source_by_path)
    return root, custody, handoff, modules, source_by_path, scope


def _load_production_closure(monkeypatch, *, validate=True, create_scope=True):
    import ctypes

    path_names = {
        ROOT_REL: "backtrader_runtime.certification_simnow_c01_root_v17",
        CUSTODY_REL: "backtrader_runtime.certification_simnow_c01_root_custody_v17",
        HANDOFF_REL: "backtrader_runtime.certification_simnow_c01_rootseal_custody_v1",
        VALIDATOR_REL: "common.c01_root_ledger_v1",
        PROTOCOL_REL: "backtrader_runtime.certification_simnow_c01_v3_protocol",
        WORKER_REL: "backtrader_runtime.certification_simnow_c01_native_v4",
        V19_REL: "backtrader_runtime.certification_simnow_c01_native_td_read_v19",
        V20_REL: "backtrader_runtime.certification_simnow_c01_native_td_read_v20",
        SUPERVISOR_REL: "backtrader_runtime.certification_simnow_c01_v4_supervisor",
        FRONT_REL: "backtrader_runtime.certification_simnow_c01_front_transport_v14",
        RUNNER_REL: "examples.000_live_certification.simnow_penetration.cases.C01.run_v20",
        OWNER_REL: "backtrader_runtime._c01_native_td_read_v7_owner",
        **V20_HELPERS,
    }
    path_names["backtrader_runtime/certification_simnow_c01_v3_contract.py"] = (
        "backtrader_runtime.certification_simnow_c01_v3_contract"
    )
    path_names["backtrader_runtime/certification_roundtrip_private.py"] = (
        "backtrader_runtime.certification_roundtrip_private"
    )
    path_names["backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py"] = (
        "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1"
    )
    path_names["scripts/run_simnow_c01_native_td_read_v20_root_activation_r1.py"] = (
        "scripts.run_simnow_c01_native_td_read_v20_root_activation_r1"
    )

    package_paths = {
        "backtrader_runtime": REPO_ROOT / "backtrader_runtime",
        "scripts": REPO_ROOT / "scripts",
        "examples": REPO_ROOT / "examples",
        "examples.000_live_certification": REPO_ROOT / "examples" / "000_live_certification",
        "examples.000_live_certification.simnow_penetration": (
            REPO_ROOT / "examples" / "000_live_certification" / "simnow_penetration"
        ),
        "examples.000_live_certification.simnow_penetration.cases": (
            REPO_ROOT / "examples" / "000_live_certification" / "simnow_penetration" / "cases"
        ),
        "examples.000_live_certification.simnow_penetration.cases.C01": (
            REPO_ROOT
            / "examples"
            / "000_live_certification"
            / "simnow_penetration"
            / "cases"
            / "C01"
        ),
        "common": REPO_ROOT
        / "examples"
        / "000_live_certification"
        / "simnow_penetration"
        / "common",
    }
    absent = object()
    saved = {}
    packages = {}
    modules = {}
    source_by_path = {}
    original_windll = getattr(ctypes, "WinDLL", None)

    def deny_winapi(*_args, **_kwargs):
        raise AssertionError("WinAPI calls are forbidden in this source-fake test")

    if original_windll is not None:
        monkeypatch.setattr(ctypes, "WinDLL", deny_winapi)
    for package_name, package_path in package_paths.items():
        saved[package_name] = sys.modules.get(package_name, absent)
        package = ModuleType(package_name)
        package.__package__ = package_name
        package.__path__ = [str(package_path)]
        packages[package_name] = package
        sys.modules[package_name] = package

    def load(relative, name):
        path = REPO_ROOT.joinpath(*relative.split("/"))
        if path.exists():
            source = path.read_bytes()
        else:
            source = WRAPPER_SOURCE
        module = ModuleType(name)
        module.__file__ = str(path)
        module.__package__ = name.rpartition(".")[0]
        previous = sys.modules.get(name, absent)
        saved[name] = previous
        sys.modules[name] = module
        if "." in name:
            parent_name, child_name = name.rsplit(".", 1)
            setattr(sys.modules[parent_name], child_name, module)
        exec(compile(source, str(path), "exec", dont_inherit=True), module.__dict__)
        module.__c01_source_sha256__ = hashlib.sha256(source).hexdigest()
        modules[relative] = module
        source_by_path[relative] = source
        return module

    load(ROOT_REL, path_names[ROOT_REL])
    # Load import dependencies first; all modules are registered only during
    # this source execution window, then removed from sys.modules below.
    ordered = [
        PROTOCOL_REL,
        "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py",
        "backtrader_runtime/certification_simnow_c01_v3_contract.py",
        SUPERVISOR_REL,
        WORKER_REL,
        VALIDATOR_REL,
        V19_REL,
        FRONT_REL,
        V20_REL,
        OWNER_REL,
        "backtrader_runtime/certification_roundtrip_private.py",
        "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
        "backtrader_runtime/ctp_front_pair_probe.py",
        "scripts/ctp_000_render_config.py",
        "scripts/ctp_000_paired_front_selector.py",
        "scripts/ctp_000_front_handoff.py",
        "scripts/ctp_i13_i15_outer_watchdog.py",
        "scripts/ctp_i13_i15_windows_job_backend.py",
        RUNNER_REL,
        HANDOFF_REL,
        CUSTODY_REL,
        WRAPPER_REL,
    ]
    try:
        for relative in ordered:
            load(relative, path_names[relative])
        root = modules[ROOT_REL]
        validate_function = root._validate_function_source
        if validate:
            invalid_functions = tuple(
                relative
                for relative, module in modules.items()
                if not root._validate_module_functions(
                    module, relative, source_by_path[relative]
                )
            )
            assert invalid_functions == (), invalid_functions
        root._validate_function_source = validate_function
        root._FIXED_SOURCE_PINS = MappingProxyType({})
        scope = None
        if create_scope:
            scope = root.create_c01_root_invocation_scope(
                root, modules, source_by_path
            )
            assert root.verify_namespace_freshness_receipt(
                scope, scope.namespace_freshness_receipt
            ) is True
        return root, modules, source_by_path, scope
    finally:
        for name in reversed(tuple(saved)):
            previous = saved[name]
            if previous is absent:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _candidate(root, modules):
    protocol = modules[PROTOCOL_REL]
    worker_receipt = protocol.C01WorkerReceipt()
    admission = modules[V20_REL]._C01V20Admission(
        MappingProxyType(
            {
                "account_scope_sha256": "a" * 64,
                "credential_binding_sha256": "b" * 64,
            }
        )
    )
    pair = protocol.C01PairBinding(
        {
            "selected_index": 0,
            "selection_sha256": "c" * 64,
            "md_front_sha256": "d" * 64,
            "td_front_sha256": "e" * 64,
            "selected_at_utc": "2026-10-09T00:00:00Z",
        }
    )
    process = modules[SUPERVISOR_REL].C01SupervisorResult(worker_receipt)
    validation = protocol.C01CandidateValidation()
    artifacts = {
        "snapshots/baseline.json": b"{}",
        "snapshots/final.json": b"{}",
    }
    return admission, pair, process, validation, artifacts


def test_root_v17_derives_immutable_pins_and_captures_functions_and_code_without_sys_modules():
    root, _custody, _handoff, modules, source_by_path, scope = _environment()

    assert type(scope.source_pins) is MappingProxyType
    assert scope.source_pin_items == tuple(sorted(scope.source_pins.items()))
    assert scope.source_pins[ROOT_REL] == hashlib.sha256(source_by_path[ROOT_REL]).hexdigest()
    assert scope.verified_source_modules[ROOT_REL] is root
    assert scope.verified_source_objects[ROOT_REL]["c01_pair_binding_ref_dict"] is root.c01_pair_binding_ref_dict
    assert (
        scope.verified_source_objects[ROOT_REL]["c01_pair_binding_ref_dict.__code__"]
        is root.c01_pair_binding_ref_dict.__code__
    )
    assert (
        scope.verified_source_objects[PROTOCOL_REL]["C01PairBinding.to_receipt_ref"]
        is modules[PROTOCOL_REL].C01PairBinding.__dict__["to_receipt_ref"]
    )
    assert (
        scope.verified_source_objects[PROTOCOL_REL]["C01PairBinding.to_receipt_ref.__code__"]
        is modules[PROTOCOL_REL].C01PairBinding.to_receipt_ref.__code__
    )
    assert (
        scope.verified_source_objects[PROTOCOL_REL]["C01PairBinding.to_receipt_ref.__globals__"]
        is modules[PROTOCOL_REL].__dict__
    )
    assert scope.verified_source_modules[OWNER_REL].__dict__["_now_utc"] is scope.verified_source_objects[
        OWNER_REL
    ]["_now_utc"]
    assert all(sys.modules.get(module.__name__) is not module for module in modules.values())
    assert root.verify_namespace_freshness_receipt(
        scope, scope.namespace_freshness_receipt
    ) is True

    with pytest.raises(TypeError):
        scope.source_pins[ROOT_REL] = "0" * 64


def test_fixed_frozen_source_and_public_validator_test_pins_match(monkeypatch):
    root, _modules, _source_by_path, _scope = _load_production_closure(monkeypatch)
    accepted_test = "tests/unit/live_certification/test_simnow_c01_root_ledger_v1.py"
    for relative, expected in root._FIXED_SOURCE_PINS.items():
        assert hashlib.sha256(REPO_ROOT.joinpath(*relative.split("/")).read_bytes()).hexdigest() == expected
    assert hashlib.sha256(REPO_ROOT.joinpath(*accepted_test.split("/")).read_bytes()).hexdigest() == (
        "a4f4d643fc3ca12c6e162e418312ec5b97291effaebefbf6f55573ef593fc88d"
    )


def test_actual_parent_and_child_source_closure_compiles_and_retains_exact_objects(monkeypatch):
    root, modules, source_by_path, _scope = _load_production_closure(monkeypatch)
    parent_paths = {
        "scripts/iteration41_simnow_c01_v20_root_actual_driver_r1.py": (
            "_c01_v20_root_actual_driver"
        ),
        "backtrader_runtime/certification_simnow_c01_root_formal_adjudicator_v1.py": (
            "backtrader_runtime.certification_simnow_c01_root_formal_adjudicator_v1"
        ),
        "examples/000_live_certification/simnow_penetration/common/c01_root_completion_v1.py": (
            "common.c01_root_completion_v1"
        ),
    }
    for relative, name in parent_paths.items():
        modules[relative], source_by_path[relative] = _load_actual_module(name, relative)

    module_map = MappingProxyType(dict(modules))
    object_map = MappingProxyType(
        {
            relative: MappingProxyType(root._capture_module_objects(module))
            for relative, module in modules.items()
        }
    )
    bytes_map = MappingProxyType(dict(source_by_path))
    pins = MappingProxyType(
        {
            relative: hashlib.sha256(raw).hexdigest()
            for relative, raw in source_by_path.items()
        }
    )

    assert set(root._REQUIRED_ROOT_SCOPE_PATHS).issubset(module_map)
    assert len(root._REQUIRED_ROOT_SCOPE_PATHS) == 23
    assert len(root._REQUIRED_PARENT_MODULE_PATHS) == 26
    assert root._parent_source_closure_is_current(module_map, object_map, pins, bytes_map)

    extra_path = "backtrader_runtime/unpinned_extra_source_fake.py"
    extra_name = "backtrader_runtime.unpinned_extra_source_fake"
    extra_bytes = b"def source_fake_binding(): return None\n"
    extra_module = _load_source_module(extra_name, extra_path, extra_bytes)
    extra_module.__c01_source_sha256__ = hashlib.sha256(extra_bytes).hexdigest()
    extra_modules = dict(module_map)
    extra_modules[extra_path] = extra_module
    extra_objects = dict(object_map)
    extra_objects[extra_path] = MappingProxyType(root._capture_module_objects(extra_module))
    extra_bytes_map = dict(bytes_map)
    extra_bytes_map[extra_path] = extra_bytes
    extra_pins = dict(pins)
    extra_pins[extra_path] = hashlib.sha256(extra_bytes).hexdigest()
    assert root._parent_source_closure_is_current(
        MappingProxyType(extra_modules),
        MappingProxyType(extra_objects),
        MappingProxyType(extra_pins),
        MappingProxyType(extra_bytes_map),
    ) is False

    bytes_only_path = "backtrader_runtime/nonmodule_probe_fake.py"
    bytes_only = dict(bytes_map)
    pins_only = dict(pins)
    raw_only = b"def unlisted_bytes_only(): return None\n"
    bytes_only[bytes_only_path] = raw_only
    pins_only[bytes_only_path] = hashlib.sha256(raw_only).hexdigest()
    assert root._parent_source_closure_is_current(
        module_map,
        object_map,
        MappingProxyType(pins_only),
        MappingProxyType(bytes_only),
    ) is False


def test_source_class_module_tamper_cannot_skip_member_validation(monkeypatch):
    root, modules, source_by_path, _scope = _load_production_closure(
        monkeypatch, validate=False, create_scope=False
    )
    supervisor = modules[SUPERVISOR_REL]
    owner = supervisor.C01StageIntent
    owner.__module__ = "tampered.source.class"
    namespace = {"__name__": supervisor.__name__}
    exec(
        compile("def __init__(self, *args, **kwargs): return None\n", "<tampered>", "exec"),
        namespace,
        namespace,
    )
    replacement = namespace["__init__"]
    replacement.__module__ = supervisor.__name__
    replacement.__qualname__ = "C01StageIntent.__init__"
    owner.__init__ = replacement

    assert root._validate_module_functions(
        supervisor, SUPERVISOR_REL, source_by_path[SUPERVISOR_REL]
    ) is False
    with pytest.raises(root.C01RootV17Error, match="source_code_binding_invalid"):
        root.create_c01_root_invocation_scope(root, modules, source_by_path)


def test_dataclass_string_filename_cannot_authorize_replaced_init(monkeypatch):
    root, modules, source_by_path, _scope = _load_production_closure(
        monkeypatch, validate=False, create_scope=False
    )
    supervisor = modules[SUPERVISOR_REL]
    owner = supervisor.C01StageIntent
    original = owner.__init__
    missing = object()
    previous_global = supervisor.__dict__.get("__init__", missing)
    code = compile("def __init__(self, *args, **kwargs): return None\n", "<string>", "exec")

    try:
        for namespace in ({"__name__": supervisor.__name__}, supervisor.__dict__):
            exec(code, namespace, namespace)
            replacement = namespace["__init__"]
            replacement.__module__ = supervisor.__name__
            replacement.__qualname__ = "C01StageIntent.__init__"
            replacement.__defaults__ = original.__defaults__
            replacement.__kwdefaults__ = original.__kwdefaults__
            replacement.__annotations__ = dict(original.__annotations__)
            owner.__init__ = replacement

            assert replacement.__code__.co_filename == "<string>"
            assert root._validate_module_functions(
                supervisor, SUPERVISOR_REL, source_by_path[SUPERVISOR_REL]
            ) is False
            with pytest.raises(root.C01RootV17Error, match="source_code_binding_invalid"):
                root.create_c01_root_invocation_scope(root, modules, source_by_path)
            owner.__init__ = original
    finally:
        owner.__init__ = original
        if previous_global is missing:
            supervisor.__dict__.pop("__init__", None)
        else:
            supervisor.__dict__["__init__"] = previous_global


def test_function_only_module_name_is_bound_into_namespace_freshness(monkeypatch):
    root, modules, source_by_path, scope = _load_production_closure(monkeypatch)
    module = modules[RUNNER_REL]
    old_name = module.__name__
    assert not any(
        isinstance(value, type) and value.__module__ == old_name
        for value in module.__dict__.values()
    )
    functions = tuple(
        value
        for value in module.__dict__.values()
        if isinstance(value, FunctionType) and value.__module__ == old_name
    )
    old_function_modules = tuple(value.__module__ for value in functions)
    try:
        module.__name__ = "tampered.function.only.module"
        for function in functions:
            function.__module__ = module.__name__
        assert root.verify_namespace_freshness_receipt(
            scope, scope.namespace_freshness_receipt
        ) is False
    finally:
        module.__name__ = old_name
        for function, old_function_module in zip(functions, old_function_modules):
            function.__module__ = old_function_module
    assert root.verify_namespace_freshness_receipt(
        scope, scope.namespace_freshness_receipt
    ) is True


def test_root_v17_candidate_projection_and_pending_result_are_exact_and_one_use():
    root, _custody, _handoff, modules, _source_by_path, scope = _environment()
    refs = _candidate(root, modules)

    assert root.validate_c01_candidate_refs(scope, refs) is True
    pair_ref = root.c01_pair_binding_ref_dict(scope, refs[1])
    assert pair_ref == refs[1].to_receipt_ref().to_dict()
    assert "td_front" not in pair_ref

    scope.candidate_refs = refs
    scope.stage_count = 1
    scope.root_content_stage = object()
    pending = root.issue_c01_candidate_pending_result(
        scope, modules[V20_REL].C01NativeTdReadV20Result()
    )
    assert type(pending) is root.C01CandidatePendingRootAdmission
    assert pending.status == "BLOCKED"
    assert pending.to_dict()["case_receipt_authority"] == "none"
    assert pending._scope is scope and pending._refs is refs
    with pytest.raises(ValueError, match="pending_candidate_unavailable"):
        root.issue_c01_candidate_pending_result(
            scope, modules[V20_REL].C01NativeTdReadV20Result()
        )


def test_root_v17_rejects_rebound_source_function_and_stale_module_map():
    root, _custody, _handoff, modules, _source_by_path, scope = _environment()
    original = modules[PROTOCOL_REL].C01PairBinding.to_receipt_ref

    def replacement(self):
        return self

    modules[PROTOCOL_REL].C01PairBinding.to_receipt_ref = replacement
    try:
        assert root.verify_namespace_freshness_receipt(
            scope, scope.namespace_freshness_receipt
        ) is False
    finally:
        modules[PROTOCOL_REL].C01PairBinding.to_receipt_ref = original
    assert root.verify_namespace_freshness_receipt(
        scope, scope.namespace_freshness_receipt
    ) is True

    scope.verified_source_modules = dict(scope.verified_source_modules)
    assert root.verify_namespace_freshness_receipt(
        scope, scope.namespace_freshness_receipt
    ) is False


def test_custody_v17_receipt_is_factory_only_and_binds_scope_pending_and_stage():
    root, custody, handoff, modules, _source_by_path, scope = _environment()
    refs = _candidate(root, modules)
    scope.candidate_refs = refs
    scope.stage_count = 1
    content = object()
    stage = handoff.C01RootContentStage(
        values={"scope": scope, "candidate_refs": refs, "validated_content": content},
        _factory=handoff._STAGE_FACTORY,
    )
    scope.root_content_stage = stage
    scope.validated_content = content
    pending = root.issue_c01_candidate_pending_result(
        scope, modules[V20_REL].C01NativeTdReadV20Result()
    )

    with pytest.raises(ValueError, match="custody_receipt_factory_required"):
        custody.C01RootContentCustodyReceipt(scope, pending, stage, object())

    evidence = refs[2]
    receipt = custody.issue_c01_root_content_custody_receipt(
        scope, pending, stage, evidence
    )
    assert type(receipt) is custody.C01RootContentCustodyReceipt
    assert receipt.scope is scope
    assert receipt.pending is pending
    assert receipt.candidate_refs is refs
    assert receipt.validated_content is content
    assert receipt.namespace_freshness_receipt is scope.namespace_freshness_receipt
    assert receipt.custody_evidence is evidence
    assert custody.validate_c01_root_content_custody_receipt(
        receipt, scope, pending, stage
    ) is True

    receipt.validated_content = object()
    assert custody.validate_c01_root_content_custody_receipt(
        receipt, scope, pending, stage
    ) is False


def test_root_writer_consumes_exact_wrapper_channel_and_writes_once():
    root, custody, handoff, modules, _source_by_path, scope = _environment()
    refs = _candidate(root, modules)
    scope.candidate_refs = refs
    scope.stage_count = 1
    content = object()
    stage = handoff.C01RootContentStage(
        values={"scope": scope, "candidate_refs": refs, "validated_content": content},
        _factory=handoff._STAGE_FACTORY,
    )
    scope.root_content_stage = stage
    scope.validated_content = content
    pending = root.issue_c01_candidate_pending_result(
        scope, modules[V20_REL].C01NativeTdReadV20Result()
    )
    custody_receipt = custody.issue_c01_root_content_custody_receipt(
        scope, pending, stage, refs[2]
    )
    frame_bytes = b"source-fake-frame"
    seal = handoff.C01RootContentSeal(
        stage=stage,
        custody_receipt=custody_receipt,
        frame=frame_bytes,
        _factory=handoff._SEAL_FACTORY,
    )
    scope.root_content_seal = seal
    wrapper = modules[WRAPPER_REL]

    with tempfile.TemporaryFile(mode="w+b") as file_obj:
        stream = file_obj.raw
        receipt = wrapper.C01V20FrameChannelReceipt(
            scope,
            stream,
            _factory=wrapper._C01_V20_FRAME_CHANNEL_FACTORY,
        )
        writer = root.create_c01_root_content_frame_writer(scope, receipt)
        assert receipt.used is True
        assert writer._scope is scope and writer._stream is stream
        assert writer._channel_receipt is receipt

        root.write_c01_root_content_frame(scope, frame_bytes, writer)
        stream.seek(0)
        assert stream.read() == frame_bytes
        assert writer._used is True
        assert seal._used is True
        assert scope.content_frame_sent is True
        assert scope.consumed is True
        with pytest.raises(ValueError, match="frame_writer_binding_invalid"):
            root.write_c01_root_content_frame(scope, frame_bytes, writer)
