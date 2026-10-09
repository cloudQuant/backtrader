"""Synthetic source-fake tests for the V20 same-call C01 content handoff."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import sys
import types
from types import FunctionType, ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = REPO_ROOT / "backtrader_runtime" / "certification_simnow_c01_rootseal_custody_v1.py"
VALIDATOR_PATH = (
    REPO_ROOT
    / "examples"
    / "000_live_certification"
    / "simnow_penetration"
    / "common"
    / "c01_root_ledger_v1.py"
)
PROTOCOL_PATH = REPO_ROOT / "backtrader_runtime" / "certification_simnow_c01_v3_protocol.py"
WORKER_PATH = REPO_ROOT / "backtrader_runtime" / "certification_simnow_c01_native_v4.py"

ROOT_PATH = "backtrader_runtime/certification_simnow_c01_root_v17.py"
CUSTODY_PATH = "backtrader_runtime/certification_simnow_c01_root_custody_v17.py"
SELF_PATH = "backtrader_runtime/certification_simnow_c01_rootseal_custody_v1.py"
LEDGER_PATH = "examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py"
PROTOCOL_RELPATH = "backtrader_runtime/certification_simnow_c01_v3_protocol.py"
WORKER_RELPATH = "backtrader_runtime/certification_simnow_c01_native_v4.py"


def _load_module(name: str, path: Path, *, source: bytes | None = None) -> ModuleType:
    raw = path.read_bytes() if source is None else source
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
    module.__c01_source_sha256__ = hashlib.sha256(raw).hexdigest()
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    module.__c01_source_sha256__ = hashlib.sha256(raw).hexdigest()
    return module


def _source_objects(module: ModuleType) -> dict[str, object]:
    """Capture module/global/function/code identities used by the exact loader."""

    result: dict[str, object] = {}
    for name, value in tuple(module.__dict__.items()):
        if name.startswith("__") or name == "__c01_source_sha256__":
            continue
        result[name] = value
        if type(value) is FunctionType:
            result[name + ".__code__"] = value.__code__
        elif type(value) is type:
            for method_name, method in tuple(value.__dict__.items()):
                if type(method) is FunctionType:
                    result["{}.{}".format(name, method_name)] = method
                    result["{}.{}.__code__".format(name, method_name)] = method.__code__
                    result["{}.{}.__globals__".format(name, method_name)] = method.__globals__
                elif isinstance(method, (classmethod, staticmethod)):
                    result["{}.{}".format(name, method_name)] = method
                    result["{}.{}.__func__".format(name, method_name)] = method.__func__
                    result["{}.{}.__code__".format(name, method_name)] = method.__func__.__code__
                    result["{}.{}.__globals__".format(name, method_name)] = (
                        method.__func__.__globals__
                    )
                elif isinstance(method, property):
                    result["{}.{}".format(name, method_name)] = method
                    for accessor_name in ("fget", "fset", "fdel"):
                        function = getattr(method, accessor_name)
                        if type(function) is FunctionType:
                            accessor = "{}.{}.{}".format(name, method_name, accessor_name)
                            result[accessor] = function
                            result[accessor + ".__code__"] = function.__code__
                            result[accessor + ".__globals__"] = function.__globals__
    return result


_ROOT_SOURCE = b"""\
class C01Admission:
    def __init__(self, bindings):
        self.bindings = bindings

class C01PairRef:
    def __init__(self, value):
        self.value = dict(value)
    def to_dict(self):
        return dict(self.value)

class C01PairBinding:
    def __init__(self, value):
        self.value = dict(value)
    def to_receipt_ref(self):
        return C01PairRef(self.value)

class C01Process:
    def __init__(self, worker_receipt):
        self.worker_receipt = worker_receipt

class C01Validation:
    pass

class C01NamespaceFreshnessReceipt:
    def __init__(self, generation):
        self.generation = generation

class C01CandidatePending:
    def __init__(self, scope):
        self._scope = scope
        self._nonce = scope.nonce

class C01RootInvocationScope:
    pass

    @classmethod
    def identity_name(cls):
        return cls.__name__

    @property
    def source_marker(self):
        return "source-bound"

_FRAME_WRITER_FACTORY = object()

class C01RootContentFrameWriter:
    def __init__(self, scope, stream):
        self._scope = scope
        self._stream = stream
        self._nonce = scope.nonce
        self._used = False
        self._factory = _FRAME_WRITER_FACTORY

def verify_namespace_freshness_receipt(scope, receipt):
    return type(scope) is C01RootInvocationScope and type(receipt) is C01NamespaceFreshnessReceipt and receipt.generation == scope.namespace_generation

def validate_c01_candidate_refs(scope, refs):
    return (type(refs) is tuple and len(refs) == 5 and type(refs[0]) is C01Admission and type(refs[1]) is C01PairBinding and type(refs[2]) is C01Process and type(refs[3]) is C01Validation and type(refs[4]) is dict and type(refs[2].worker_receipt) is scope.protocol.C01WorkerReceipt)

def c01_pair_binding_ref_dict(scope, pair_binding):
    return C01PairBinding.to_receipt_ref(pair_binding).to_dict()

def write_c01_root_content_frame(scope, frame_bytes, writer_capability):
    seal = scope.root_content_seal
    if (type(writer_capability) is not C01RootContentFrameWriter or writer_capability._scope is not scope or writer_capability._nonce is not scope.nonce or writer_capability._used is not False or type(writer_capability._stream) is not __import__('io').FileIO or type(frame_bytes) is not bytes or seal is None or seal._frame is not frame_bytes or seal._used is not False):
        raise ValueError('writer_invalid')
    writer_capability._used = True
    seal._used = True
    scope.content_frame_sent = True
    scope.consumed = True
    written = writer_capability._stream.write(frame_bytes)
    if type(written) is not int or written != len(frame_bytes):
        raise OSError('short_write')
    writer_capability._stream.flush()
"""

_CUSTODY_SOURCE = b"""\
class C01RootContentCustodyReceipt:
    def __init__(self, scope, pending, stage):
        self.scope = scope
        self.pending = pending
        self.candidate_refs = stage.candidate_refs
        self.validated_content = stage.validated_content
        self.namespace_freshness_receipt = scope.namespace_freshness_receipt
        self.consumed = False

def validate_c01_root_content_custody_receipt(receipt, scope, pending, stage):
    return (type(receipt) is C01RootContentCustodyReceipt and receipt.scope is scope and receipt.pending is pending and receipt.candidate_refs is stage.candidate_refs and receipt.validated_content is stage.validated_content and receipt.namespace_freshness_receipt is scope.namespace_freshness_receipt and receipt.consumed is False)
"""


def _test_fixture_module() -> ModuleType:
    path = REPO_ROOT / "tests" / "unit" / "live_certification" / "test_simnow_c01_root_ledger_v1.py"
    return _load_module("_c01_rootseal_ledger_test_fixture", path)


@pytest.fixture
def env():
    absent = object()
    module_names = (
        "_c01_rootseal_custody_under_test",
        "backtrader_runtime.certification_simnow_c01_v3_protocol",
        "backtrader_runtime.certification_simnow_c01_native_v4",
        "common.c01_root_ledger_v1",
        "_c01_rootseal_ledger_test_fixture",
        "backtrader_runtime.certification_simnow_c01_root_v17",
        "backtrader_runtime.certification_simnow_c01_root_custody_v17",
    )
    prior_modules = {name: sys.modules.get(name, absent) for name in module_names}
    try:
        helper = _load_module("_c01_rootseal_custody_under_test", HELPER_PATH)
        protocol = _load_module(
            "backtrader_runtime.certification_simnow_c01_v3_protocol", PROTOCOL_PATH
        )
        worker = _load_module(
            "backtrader_runtime.certification_simnow_c01_native_v4", WORKER_PATH
        )
        ledger = _load_module("common.c01_root_ledger_v1", VALIDATOR_PATH)
        fixture = _test_fixture_module()
        bundle = fixture._source_produced_bundle()

        root = _load_module(
            "backtrader_runtime.certification_simnow_c01_root_v17",
            REPO_ROOT / ROOT_PATH,
            source=_ROOT_SOURCE,
        )
        custody = _load_module(
            "backtrader_runtime.certification_simnow_c01_root_custody_v17",
            REPO_ROOT / CUSTODY_PATH,
            source=_CUSTODY_SOURCE,
        )

        protocol_sha = hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest()
        worker_sha = hashlib.sha256(WORKER_PATH.read_bytes()).hexdigest()
        ledger_sha = hashlib.sha256(VALIDATOR_PATH.read_bytes()).hexdigest()
        helper_sha = hashlib.sha256(HELPER_PATH.read_bytes()).hexdigest()
        pins = {
            ROOT_PATH: root.__c01_source_sha256__,
            CUSTODY_PATH: custody.__c01_source_sha256__,
            SELF_PATH: helper_sha,
            LEDGER_PATH: ledger_sha,
            PROTOCOL_RELPATH: protocol_sha,
            WORKER_RELPATH: worker_sha,
        }
        modules = {
            ROOT_PATH: root,
            CUSTODY_PATH: custody,
            SELF_PATH: helper,
            LEDGER_PATH: ledger,
            PROTOCOL_RELPATH: protocol,
            WORKER_RELPATH: worker,
        }
        source_objects = {
            path: _source_objects(module) for path, module in modules.items()
        }

        receipt = protocol.parse_worker_frame(
            protocol.encode_worker_frame(bundle["worker"])
        )
        admission = root.C01Admission(
            {
                "account_scope_sha256": fixture.ACCOUNT_SCOPE,
                "credential_binding_sha256": fixture.CREDENTIAL_BINDING,
            }
        )
        pair = root.C01PairBinding(bundle["pair"])
        process = root.C01Process(receipt)
        validation = root.C01Validation()
        scope = root.C01RootInvocationScope()
        scope.root_module = root
        scope.root_custody_module = custody
        scope.protocol = protocol
        scope.expected_worker_source_sha256 = bundle["worker_sha256"]
        scope.namespace_generation = "rootgen3-sourcefake-generation"
        scope.invocation_id = "1" * 32
        scope.namespace_freshness_receipt = root.C01NamespaceFreshnessReceipt(
            scope.namespace_generation
        )
        scope.verified_source_modules = modules
        scope.verified_source_objects = source_objects
        scope.source_pins = pins
        scope.source_pin_items = tuple(sorted(pins.items()))
        scope.active = True
        scope.consumed = False
        scope.issuer_returned = False
        scope.stage_count = 0
        scope.candidate_refs = None
        scope.root_content_stage = None
        scope.root_content_seal = None
        scope.content_frame_sent = False
        scope.pending = None
        scope.nonce = object()
        refs = (admission, pair, process, validation, bundle["artifacts"])
        scope.candidate_refs = None
        scope._test_refs = refs
        yield types.SimpleNamespace(
            helper=helper,
            root=root,
            custody=custody,
            protocol=protocol,
            worker=worker,
            ledger=ledger,
            source_objects=source_objects,
            source_modules=modules,
            pins=pins,
            fixture=fixture,
            bundle=bundle,
            scope=scope,
            refs=refs,
        )
    finally:
        for name, prior in prior_modules.items():
            if prior is absent:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


def _stage(env):
    admission, pair, process, validation, artifacts = env.refs
    return env.helper.stage_c01_content(
        root_module=env.root,
        custody_module=env.custody,
        scope=env.scope,
        admission=admission,
        pair_binding=pair,
        process=process,
        validation=validation,
        artifacts=artifacts,
        validator_module=env.ledger,
        protocol_module=env.protocol,
        worker_module=env.worker,
    )


def _seal(env, stage):
    scope = env.scope
    scope.issuer_returned = True
    pending = env.root.C01CandidatePending(scope)
    scope.pending = pending
    receipt = env.custody.C01RootContentCustodyReceipt(scope, pending, stage)
    seal = env.helper.mint_c01_root_content_seal(
        root_module=env.root,
        custody_module=env.custody,
        stage=stage,
        pending=pending,
        custody_receipt=receipt,
    )
    return pending, receipt, seal


def _write_frame(env, seal, tmp_path: Path) -> bytes:
    path = tmp_path / "private-frame.bin"
    stream = io.FileIO(path, "wb")
    writer = env.root.C01RootContentFrameWriter(env.scope, stream)
    env.helper.write_c01_root_content_frame(seal, writer)
    stream.close()
    return path.read_bytes()


def test_same_call_content_is_validated_twice_then_handed_off_without_authority(env, tmp_path):
    stage = _stage(env)
    assert stage.validated_content.authority == "NONE"
    assert stage.validated_content.certification_pass is False
    pending, receipt, seal = _seal(env, stage)

    raw = _write_frame(env, seal, tmp_path)
    assert env.scope.content_frame_sent is True
    pipe = io.BytesIO(raw)
    frame = env.helper.read_c01_root_content_frame(pipe)
    summary = frame.safe_summary()
    assert summary["authority"] == "NONE"
    assert summary["content_validated"] is False
    assert summary["certification_pass"] is False
    assert summary["request_count"] == 8
    assert summary["snapshot_count"] == 2
    assert env.fixture.ACCOUNT_SCOPE not in repr(frame)
    assert env.fixture.CREDENTIAL_BINDING not in repr(frame)
    assert env.fixture.ACCOUNT_SCOPE not in repr(summary)
    assert env.fixture.CREDENTIAL_BINDING not in repr(summary)

    content = env.helper.revalidate_c01_root_content_frame(
        frame,
        validator_module=env.ledger,
        protocol_module=env.protocol,
        worker_module=env.worker,
        expected_source_pins=env.pins,
        expected_source_modules={
            LEDGER_PATH: env.ledger,
            PROTOCOL_RELPATH: env.protocol,
            WORKER_RELPATH: env.worker,
        },
        expected_source_objects={
            LEDGER_PATH: env.source_objects[LEDGER_PATH],
            PROTOCOL_RELPATH: env.source_objects[PROTOCOL_RELPATH],
            WORKER_RELPATH: env.source_objects[WORKER_RELPATH],
        },
        expected_invocation_id=env.scope.invocation_id,
        expected_namespace_generation=env.scope.namespace_generation,
        expected_worker_source_sha256=env.scope.expected_worker_source_sha256,
        expected_pair_binding=env.bundle["pair"],
        expected_account_scope_sha256=env.fixture.ACCOUNT_SCOPE,
        expected_credential_binding_sha256=env.fixture.CREDENTIAL_BINDING,
    )
    assert content.authority == "NONE"
    assert content.certification_pass is False
    assert content.request_count == 8
    assert content.query_receipts == stage.validated_content.query_receipts
    assert pending._scope is env.scope
    assert receipt.candidate_refs is stage.candidate_refs

    with pytest.raises(
        env.helper.RootSealCustodyError, match="rootseal_transfer_replayed"
    ), io.FileIO(tmp_path / "replay.bin", "wb") as stream:
        writer = env.root.C01RootContentFrameWriter(env.scope, stream)
        env.helper.write_c01_root_content_frame(seal, writer)


@pytest.mark.parametrize("mutation", ["receipt", "artifact", "source_function", "source_code"])
def test_stage_change_blocks_seal_before_private_frame_transfer(env, mutation):
    stage = _stage(env)
    scope = env.scope
    refs = stage.candidate_refs
    scope.issuer_returned = True
    pending = env.root.C01CandidatePending(scope)
    scope.pending = pending
    receipt = env.custody.C01RootContentCustodyReceipt(scope, pending, stage)

    if mutation == "receipt":
        refs[2].worker_receipt = env.protocol.parse_worker_frame(
            env.protocol.encode_worker_frame(env.bundle["worker"])
        )
    elif mutation == "artifact":
        refs[4]["snapshots/baseline.json"] = bytes(bytearray(refs[4]["snapshots/baseline.json"]))
    elif mutation == "source_function":
        original = env.root.validate_c01_candidate_refs
        env.root.validate_c01_candidate_refs = lambda *_args: True
        with pytest.raises(env.helper.RootSealCustodyError):
            env.helper.mint_c01_root_content_seal(
                root_module=env.root,
                custody_module=env.custody,
                stage=stage,
                pending=pending,
                custody_receipt=receipt,
            )
        env.root.validate_c01_candidate_refs = original
        return
    elif mutation == "source_code":
        scope.verified_source_objects[ROOT_PATH]["validate_c01_candidate_refs.__code__"] = (
            lambda *_args: True
        ).__code__

    with pytest.raises(env.helper.RootSealCustodyError):
        env.helper.mint_c01_root_content_seal(
            root_module=env.root,
            custody_module=env.custody,
            stage=stage,
            pending=pending,
            custody_receipt=receipt,
        )
    assert scope.root_content_seal is None
    assert scope.content_frame_sent is False


@pytest.mark.parametrize(
    "damage",
    ["truncated", "trailing", "header_oversized", "wrong_call", "wrong_generation", "wrong_pair"],
)
def test_parent_rejects_malformed_or_misbinding_private_frame(env, damage, tmp_path):
    stage = _stage(env)
    _, _, seal = _seal(env, stage)
    raw = _write_frame(env, seal, tmp_path)
    if damage == "truncated":
        raw = raw[:-1]
    elif damage == "trailing":
        raw += b"x"
    elif damage == "header_oversized":
        raw = b"C01RSL01" + (2**32 - 1).to_bytes(4, "big") * 5 + raw[28:]
    reader = io.BytesIO(raw)
    if damage in {"truncated", "trailing", "header_oversized"}:
        with pytest.raises(env.helper.RootSealCustodyError):
            env.helper.read_c01_root_content_frame(reader)
        return
    frame = env.helper.read_c01_root_content_frame(reader)
    expected = {
        "expected_source_pins": env.pins,
        "expected_source_modules": {
            LEDGER_PATH: env.ledger,
            PROTOCOL_RELPATH: env.protocol,
            WORKER_RELPATH: env.worker,
        },
        "expected_source_objects": {
            LEDGER_PATH: env.source_objects[LEDGER_PATH],
            PROTOCOL_RELPATH: env.source_objects[PROTOCOL_RELPATH],
            WORKER_RELPATH: env.source_objects[WORKER_RELPATH],
        },
        "expected_invocation_id": env.scope.invocation_id,
        "expected_namespace_generation": env.scope.namespace_generation,
        "expected_worker_source_sha256": env.scope.expected_worker_source_sha256,
        "expected_pair_binding": env.bundle["pair"],
        "expected_account_scope_sha256": env.fixture.ACCOUNT_SCOPE,
        "expected_credential_binding_sha256": env.fixture.CREDENTIAL_BINDING,
    }
    if damage == "wrong_call":
        expected["expected_invocation_id"] = "2" * 32
    elif damage == "wrong_generation":
        expected["expected_namespace_generation"] = "stale-generation"
    elif damage == "wrong_pair":
        expected["expected_pair_binding"] = {"different": "binding"}
    with pytest.raises(env.helper.RootSealCustodyError):
        env.helper.revalidate_c01_root_content_frame(
            frame,
            validator_module=env.ledger,
            protocol_module=env.protocol,
            worker_module=env.worker,
            **expected,
        )


def test_untrusted_shape_receipt_cannot_construct_a_seal_or_frame():
    helper = _load_module("_c01_rootseal_ctor_test", HELPER_PATH)
    with pytest.raises(helper.RootSealCustodyError, match="rootseal_factory_required"):
        helper.C01RootContentSeal(stage=object(), custody_receipt={}, frame=b"shape")
    with pytest.raises(helper.RootSealCustodyError, match="rootseal_factory_required"):
        helper.C01RootContentStage(values={})


def test_held_classmethod_descriptor_function_code_and_globals_are_bound(env):
    assert env.root.C01RootInvocationScope.identity_name() == "C01RootInvocationScope"
    stage = _stage(env)
    assert stage.validated_content.authority == "NONE"


def test_held_classmethod_descriptor_replacement_blocks_before_stage(env):
    descriptor = env.root.C01RootInvocationScope.__dict__["identity_name"]
    env.root.C01RootInvocationScope.identity_name = classmethod(descriptor.__func__)
    with pytest.raises(env.helper.RootSealCustodyError, match="source_global_binding_mismatch"):
        _stage(env)


def test_held_property_accessor_code_and_globals_are_bound(env):
    instance = object.__new__(env.root.C01RootInvocationScope)
    assert instance.source_marker == "source-bound"
    stage = _stage(env)
    assert stage.validated_content.status == "CONTENT_VALIDATED_ONLY"


def test_held_property_descriptor_replacement_blocks_before_stage(env):
    descriptor = env.root.C01RootInvocationScope.__dict__["source_marker"]
    env.root.C01RootInvocationScope.source_marker = property(descriptor.fget)
    with pytest.raises(env.helper.RootSealCustodyError, match="source_global_binding_mismatch"):
        _stage(env)


def test_custom_metaclass_source_objects_resolve_without_getattribute(env):
    module = ModuleType("_rootseal_custom_metaclass_fixture")
    module.__file__ = "D:/source_code/backtrader/custom_metaclass_fixture.py"
    module.__c01_source_sha256__ = "a" * 64
    exec(
        "class _FixtureMeta(type):\n"
        "    def __getattribute__(cls, name):\n"
        "        if name == '__dict__':\n"
        "            raise AssertionError('metaclass hook must not run')\n"
        "        return super().__getattribute__(name)\n"
        "class CustomSourceClass(metaclass=_FixtureMeta):\n"
        "    def pinned_method(self):\n"
        "        return 'source-bound'\n",
        module.__dict__,
    )
    source_class = module.__dict__["CustomSourceClass"]
    class_namespace = type.__getattribute__(source_class, "__dict__")
    method = class_namespace["pinned_method"]
    objects = {
        "CustomSourceClass": source_class,
        "CustomSourceClass.pinned_method": method,
        "CustomSourceClass.pinned_method.__code__": method.__code__,
        "CustomSourceClass.pinned_method.__globals__": method.__globals__,
    }
    env.helper._validate_pinned_module(
        module,
        path="custom_metaclass_fixture.py",
        expected_pin="a" * 64,
        expected_module=module,
        expected_objects=objects,
        required_types=("CustomSourceClass",),
        required_methods=(("CustomSourceClass", "pinned_method"),),
    )
    assert env.helper._resolve_source_object(
        module, "CustomSourceClass.pinned_method.__code__"
    ) is method.__code__
    module.__dict__["CustomSourceClass"].pinned_method = lambda self: "replaced"
    with pytest.raises(env.helper.RootSealCustodyError, match="source_global_binding_mismatch"):
        env.helper._validate_pinned_module(
            module,
            path="custom_metaclass_fixture.py",
            expected_pin="a" * 64,
            expected_module=module,
            expected_objects=objects,
            required_types=("CustomSourceClass",),
            required_methods=(("CustomSourceClass", "pinned_method"),),
        )
