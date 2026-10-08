"""Source fakes for the R24 R7 cleanup capsule and its pinned result producer.

Most cases isolate held-map and cleanup mutations. Integration cases use the
actual R23 hold producer and exact R23 root-release callback with fake CUV2
API/CLI leaves; the adapter-chain case runs R14.supervise/finally with only the
terminal R10 supervisor replaced by a fake.
"""

from __future__ import annotations

import ast
import dataclasses
import contextlib
import hashlib
import json
import ntpath
import sys
import threading
import time
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import FunctionType, MethodType, ModuleType, SimpleNamespace

import pytest

pytest_plugins = (
    "tests.unit.runtime.test_iteration41_okx_m01_r33_root_reason_class_r23_source_fake",
)

from scripts import iteration41_okx_m01_r33_no_session_cleanup_r24_r7 as r24r7
from scripts import iteration41_okx_m01_r33_parent_adapter_transport_r14_r1 as r14
from scripts import iteration41_okx_m01_r33_root_reason_class_r23_r1 as r23_producer
from tests.unit.runtime import test_iteration41_okx_m01_r33_parent_adapter_transport_r14_r1 as r14_tests


R24R7_REFERENCE_ROOT = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-m01-r33-r24-no-session-cleanup-r7-2026-10-08/references"
)

_REAL_VERIFY_LOADED_MODULE = r24r7._verify_loaded_module
_REAL_VERIFY_CLASS_SOURCE = r24r7._verify_class_source
_REAL_VERIFY_FUNCTION_SOURCE = r24r7._verify_function_source
_REAL_VERIFY_RUNTIME_SOURCES = r24r7._verify_runtime_sources


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _key(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(value))


def _production_parent_maps(driver_source, pub, software, canonical, addition, r16_result):
    """Execute only the pinned R23 driver's exact parent-map construction AST."""

    filename = r24r7.R23_DRIVER_RELATIVE_PATH
    tree = ast.parse(driver_source.decode("utf-8"), filename=filename)
    key_function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "key"
    )
    driver_try = next(
        node
        for node in tree.body
        if isinstance(node, ast.Try)
        and any(
            isinstance(child, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "pub_parent" for target in child.targets)
            for child in node.body
        )
    )
    wanted_lines = (397, 399, 402, 403, 404, 425, 426)
    selected = [node for node in driver_try.body if node.lineno in wanted_lines]
    assert tuple(node.lineno for node in selected) == wanted_lines
    assert tuple(type(node) for node in selected) == (
        ast.Assign,
        ast.For,
        ast.Assign,
        ast.Assert,
        ast.Assign,
        ast.Assign,
        ast.Assert,
    )
    namespace = {
        "ntpath": ntpath,
        "pub": pub,
        "soft": software,
        "expected": canonical,
        "hold_addition": addition,
        "r16_result": r16_result,
    }
    module = ast.Module(body=[key_function, *selected], type_ignores=[])
    ast.fix_missing_locations(module)
    code = compile(module, filename, "exec", dont_inherit=True)
    exec(code, namespace)
    return namespace["pub_parent"], namespace["expected_parent"]


@pytest.fixture(scope="module")
def actual_r23_adapter_result(prepared_r23):
    """Use the production R31→R23 preparation and adapter chain with fake leaves."""
    return r23_producer.construct_parent_adapter(
        prepared_r23,
        adapter_kwargs={
            "scope_authenticator": lambda *_args: True,
            "clock": time.monotonic,
            "sleeper": time.sleep,
        },
    )


class _Scope:
    def __init__(self):
        self.exit_calls = 0
        self.raise_on_exit = False
        self.on_exit = None

    def __exit__(self, _exc_type, _exc, _tb):
        self.exit_calls += 1
        if self.on_exit is not None:
            self.on_exit()
        if self.raise_on_exit:
            raise RuntimeError("synthetic exit refusal")
        return False


@dataclasses.dataclass(frozen=True)
class _PrivateArtifactDirectory:
    path: Path
    device: int
    inode: int
    operation_deadline: object = None


@dataclasses.dataclass(frozen=True)
class _FakeR6ParentDiagnosticResult:
    schema: str
    status: str
    reason: str
    cleanup_reason: str
    child_returncode: object
    capture_complete: bool
    cleanup_complete: bool
    scope_released: bool
    scope_retained: bool
    stdout_bytes: object
    stderr_bytes: object
    child_phase: dict


def _fresh(monkeypatch):
    """Make a same-call synthetic namespace with exact identities and map counts."""

    root = r24r7._repo_root()
    driver_path = (root / Path(*r24r7.R23_DRIVER_RELATIVE_PATH.split("/"))).resolve()
    r23_map_driver_source = r24r7._read_fixed_public_source(
        root,
        r24r7.R23_DRIVER_RELATIVE_PATH,
        r24r7.RUNTIME_SOURCE_PINS[r24r7.R23_DRIVER_RELATIVE_PATH],
    )
    cu_path = "D:/temp/iteration41-root-public-custody-v2.py"
    cu_module_name = "_root_m01_r12_r2_cu"
    cu_source = r24r7._read_fixed_public_source(
        root,
        r24r7.CUV2_PUBLIC_SOURCE_RELATIVE_PATH,
        r24r7.CUV2_PUBLIC_SOURCE_SHA256,
    )
    assert _sha(cu_source) == r24r7.CUV2_PUBLIC_SOURCE_SHA256
    driver_lines = [""] * 500
    driver_lines[0] = "from pathlib import Path"
    driver_lines[1] = f"CU=Path({cu_path!r})"
    driver_lines[2] = f"CU_SHA={_sha(cu_source)!r}"
    driver_lines[4] = "def load(raw, path, name):"
    driver_lines[5] = "    return None"
    driver_lines[6] = f"cu=load(b'',CU,{cu_module_name!r})"
    driver_lines[433] = "def authenticate(scope, binding, remaining):"
    driver_lines[434] = "    return False"
    driver_lines[476] = "def release(scope, remaining):"
    driver_lines[477] = "    global release_called, main_retained, main_postverified"
    driver_lines[478] = "    global extra_retained, extra_postverified, release_succeeded"
    driver_lines[479] = "    assert scope is source_scope and remaining == 5.0"
    driver_lines[480] = "    release_called = True"
    driver_lines[481] = "    cu.Path = _fake_cuv2_path"
    driver_lines[482] = "    try:"
    driver_lines[483] = "        main_scope.__exit__(None, None, None)"
    driver_lines[484] = "        main_retained = False"
    driver_lines[485] = "        main_postverified = True"
    driver_lines[486] = "        extra_scope.__exit__(None, None, None)"
    driver_lines[487] = "        extra_retained = False"
    driver_lines[488] = "        extra_postverified = True"
    driver_lines[489] = "        release_succeeded = True"
    driver_lines[490] = "        return True"
    driver_lines[491] = "    finally:"
    driver_lines[492] = "        cu.Path = _actual_cuv2_path"
    driver_source = "\n".join(driver_lines).encode("utf-8")
    r13_path = (root / Path(*r24r7.R13_SOURCE_RELATIVE_PATH.split("/"))).resolve()
    r13_raw = b"r13-public-source"
    monkeypatch.setitem(r24r7.RUNTIME_SOURCE_PINS, r24r7.R13_SOURCE_RELATIVE_PATH, _sha(r13_raw))

    monkeypatch.setattr(
        r24r7,
        "_verify_runtime_sources",
        lambda namespace, pin: (
            root,
            {
                "public_fixture": pin,
                r24r7.R24R7_RELATIVE_PATH: pin,
                r24r7.CUV2_PUBLIC_SOURCE_RELATIVE_PATH: r24r7.CUV2_PUBLIC_SOURCE_SHA256,
            },
            driver_source,
        ),
    )
    monkeypatch.setattr(r24r7, "_verify_loaded_modules", lambda _namespace, _root: None)
    monkeypatch.setattr(r24r7, "_verify_loaded_module", lambda *_args: None)
    monkeypatch.setattr(r24r7, "_verify_class_source", lambda *_args: None)
    monkeypatch.setattr(r24r7, "_verify_function_source", lambda *_args: None)

    owner_thread = threading.get_ident()
    registry = SimpleNamespace(_lock=threading.Lock(), _entries=[])
    r32 = SimpleNamespace(
        ParentEnvelopeResult=type("_ParentEnvelopeResult", (), {}),
        RESULT_SCHEMA="fixture.r32.v1",
        PARENT_CLEANUP_SECONDS=5.0,
        StrongRetentionRegistry=type(registry),
        _DEFAULT_RETENTION_REGISTRY=registry,
    )
    r2_module_name = "_r24_fake_r2"
    r2_module = ModuleType(r2_module_name)
    r2_module.__file__ = str(root / "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r2.py")
    exec(
        "class M01WindowsParentAdapter:\n    def __init__(self):\n        pass\n",
        r2_module.__dict__,
    )
    r2_module.ROOT_REAL_ADAPTER_ENABLED = False
    r2_adapter = r2_module.M01WindowsParentAdapter()
    r2_adapter._r32 = r32
    r2_adapter.fake_leaves = False
    r2_adapter.native = None
    r2_adapter.process_factory = None
    r2_adapter._scope_authenticated = False
    r2_adapter._retained_late = []
    r2_adapter._owner_thread = owner_thread
    r2_adapter._r2_module = r2_module
    r2_adapter._r2_source = (root / "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r2.py").read_bytes()

    r4_module_name = "_r24_fake_r4"
    r4_module = ModuleType(r4_module_name)
    r4_module.__file__ = str(root / "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r4.py")
    exec(
        "class M01WindowsParentAdapter:\n    def __init__(self):\n        pass\n"
        "def _load_private_r2():\n    pass\n",
        r4_module.__dict__,
    )
    r4_module.R2_SOURCE_SHA256 = r24r7.RUNTIME_SOURCE_PINS[
        "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r2.py"
    ]
    r4_type = r4_module.M01WindowsParentAdapter
    r4_adapter = r4_type()
    r4_adapter._inner = r2_adapter
    r4_adapter._r2_module = r2_module
    r4_adapter._r2_source = r2_adapter._r2_source
    r4_adapter._owner_thread = owner_thread
    r4_adapter._supervising = False
    r4_adapter._scope_callback_verified = False
    r5_module_name = "_r24_fake_r5"
    r5_module = ModuleType(r5_module_name)
    r5_module.__file__ = str(root / "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r5.py")
    exec(
        "class M01WindowsParentAdapter:\n    def __init__(self):\n        pass\n"
        "def _load_pinned_r4():\n    pass\n",
        r5_module.__dict__,
    )
    r5_type = r5_module.M01WindowsParentAdapter
    r5_adapter = r5_type()
    r5_adapter._base = r4_adapter
    r5_adapter._inner = r2_adapter
    r5_adapter._r2_module = r2_module
    r5_adapter._owner_thread = owner_thread
    r5_adapter._target_observation_attempted = False
    r5_module._R4 = r4_module
    r5_module.R4_SOURCE_SHA256 = r24r7.RUNTIME_SOURCE_PINS[
        "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r4.py"
    ]
    r6_module = ModuleType("_r24_fake_r6")
    r6_module.__file__ = str(root / "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r6.py")
    exec("def _load_pinned_r5():\n    pass\n", r6_module.__dict__)
    _FakeR6ParentDiagnosticResult.__module__ = r6_module.__name__
    _FakeR6ParentDiagnosticResult.__name__ = "M01ParentDiagnosticResult"
    _FakeR6ParentDiagnosticResult.__qualname__ = "M01ParentDiagnosticResult"
    r6_module.M01ParentDiagnosticResult = _FakeR6ParentDiagnosticResult
    r6_module.R5_SOURCE_SHA256 = r24r7.RUNTIME_SOURCE_PINS[
        "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r5.py"
    ]
    r6_module._R5 = r5_module
    r8_module = ModuleType("_r24_fake_r8")
    r8_module.__file__ = str(root / "scripts/iteration41_okx_m01_r33_outer_route_phase_observer_r8_r1.py")
    exec(
        "class M01WindowsParentAdapter:\n"
        "    def __init__(self):\n        pass\n"
        "    def _project_r7_parent_result(self, result):\n"
        "        return _R6.M01ParentDiagnosticResult(\n"
        "            schema=result.schema, status=result.status, reason=result.reason,\n"
        "            cleanup_reason=result.cleanup_reason, child_returncode=result.child_returncode,\n"
        "            capture_complete=result.capture_complete, cleanup_complete=result.cleanup_complete,\n"
        "            scope_released=result.scope_released, scope_retained=result.scope_retained,\n"
        "            stdout_bytes=None, stderr_bytes=None,\n"
        "            child_phase={'authority': False, 'strict_cases_passed': 0},\n"
        "        )\n",
        r8_module.__dict__,
    )
    r8_module._R6 = r6_module
    r8_adapter = r8_module.M01WindowsParentAdapter()
    r8_adapter._r5 = r5_adapter

    r14_name = "scripts.iteration41_okx_m01_r33_parent_adapter_transport_r14_r1"
    r14_fake = ModuleType(r14_name)
    r14_fake.__file__ = str(root / "scripts/iteration41_okx_m01_r33_parent_adapter_transport_r14_r1.py")

    class _R14Adapter:
        def __init__(self):
            self._r8_adapter = r8_adapter
            self._used_lock = threading.Lock()
            self._used = True

    _R14Adapter.__module__ = r14_name
    r14_fake.M01WindowsParentAdapter = _R14Adapter
    exec(
        "def _check(value, code):\n"
        "    if not value:\n"
        "        raise RuntimeError(code)\n",
        r14_fake.__dict__,
    )
    r14 = r14_fake
    r14_adapter = _R14Adapter()

    r19_result_type = type("_R19Result", (), {})
    r20_result_type = type("_R20Result", (), {})
    r21_result_type = type("_R21Result", (), {})
    r22_result_type = type("_R22Result", (), {})
    r23_result_type = type("_R23Result", (), {})

    r19_result = r19_result_type()
    r19_result.adapter = r14_adapter
    r20_result = r20_result_type()
    r20_result.r19_adapter_result = r19_result
    r20_result.adapter = r14_adapter
    r21_result = r21_result_type()
    r21_result.r20_adapter_result = r20_result
    r21_result.adapter = r14_adapter
    r22_result = r22_result_type()
    r22_result.r21_adapter_result = r21_result
    r22_result.adapter = r14_adapter

    class _R23Adapter:
        def __init__(self):
            self._base_adapter = r14_adapter
            self._used_lock = threading.Lock()
            self._used = True

        @staticmethod
        def summarize_result(value):
            return {
                "schema": value.schema,
                "status": value.status,
                "reason": value.reason,
                "cleanup_reason": value.cleanup_reason,
                "child_returncode": value.child_returncode,
                "capture_complete": value.capture_complete,
                "cleanup_complete": value.cleanup_complete,
                "scope_released": value.scope_released,
                "scope_retained": value.scope_retained,
                "stdout_bytes": value.stdout_bytes,
                "stderr_bytes": value.stderr_bytes,
                "authority": False,
                "strict_cases_passed": 0,
                "child_phase": dict(value.child_phase),
            }

    r23_adapter = _R23Adapter()
    r23 = SimpleNamespace(
        R23ParentAdapterResult=r23_result_type,
        R23ParentAdapter=_R23Adapter,
        _PATCH_LOCK=threading.Lock(),
        _PATCH_OWNER_THREAD=None,
        _ORIGINAL_PARENT_PROJECTION=object(),
        verify_root_hold=lambda _value: True,
        verify_parent_adapter_result=lambda _value: True,
    )
    r23._R12 = SimpleNamespace(_parent_projection=r23._ORIGINAL_PARENT_PROJECTION)
    r22 = SimpleNamespace(
        R22ParentAdapterResult=r22_result_type,
        verify_parent_adapter_result=lambda _value: True,
    )
    r21 = SimpleNamespace(
        R21ParentAdapterResult=r21_result_type,
        verify_parent_adapter_result=lambda _value: True,
    )
    r20 = SimpleNamespace(
        R20ParentAdapterResult=r20_result_type,
        verify_parent_adapter_result=lambda _value: True,
    )
    r19 = SimpleNamespace(
        R19ParentAdapterResult=r19_result_type,
        verify_parent_adapter_result=lambda _value: True,
    )
    r17 = SimpleNamespace(verify_hold_addition=lambda _value: True)

    r23_result = r23_result_type()
    r23_result.r22_adapter_result = r22_result
    r23_result.adapter = r23_adapter
    r23_result.hold_addition_sha256 = ""
    r23_adapter_result = r23_result

    private_path = SimpleNamespace(PrivateArtifactDirectory=_PrivateArtifactDirectory)
    control_path = "C:/control"
    deploy_path = "C:/deploy"
    control = _PrivateArtifactDirectory(Path(control_path), 1, 11)
    deploy = _PrivateArtifactDirectory(Path(deploy_path), 1, 12)
    r23_path = "C:/source/r23.py"
    r23_raw = b"r23-public-source"
    r13_path_key = _key(str(r13_path))
    r13_module = ModuleType(r24r7.R13_MODULE_NAME)
    r13_module.__file__ = str(r13_path)
    r13_module.__spec__ = ModuleSpec(
        r24r7.R13_MODULE_NAME, loader=None, origin=str(r13_path)
    )
    r14._R13 = r13_module
    monkeypatch.setitem(sys.modules, r24r7.R13_MODULE_NAME, r13_module)
    r16_path = "C:/source/r16.py"
    r16_raw = b"r16-public-source"
    plan_path = "C:/control/plan.json"
    plan_raw = b"{\"schema\":\"plan\"}"

    pub = {}
    software = {}
    held = {}
    for index in range(117):
        path = f"C:/public/{index}.py"
        raw = f"public-{index}".encode()
        pub[_key(path)] = _sha(raw)
        held[_key(path)] = raw
    pub[_key(plan_path)] = _sha(plan_raw)
    held[_key(plan_path)] = plan_raw
    for index in range(36):
        path = f"C:/software/{index}.py"
        raw = f"software-{index}".encode()
        software[_key(path)] = _sha(raw)
        held[_key(path)] = raw
    canonical = {**pub, **software}

    sidecar_path = "C:/source/r9-sidecar.bin"
    sidecar_raw = b"r9-sidecar-source"
    composer_path = "C:/source/r10-composer.py"
    composer_raw = b"r10-composer-source"
    r23_result.prepared_hold = SimpleNamespace(
        prepared_r13=SimpleNamespace(
            r10_prepared=SimpleNamespace(
                r9_prepared=SimpleNamespace(
                    sidecar_path=sidecar_path,
                    sidecar_sha256=_sha(sidecar_raw),
                    sidecar_size_bytes=len(sidecar_raw),
                    r8_bootstrap_bytes=sidecar_raw,
                ),
                composer_path=composer_path,
                composer_bytes=composer_raw,
                composer_sha256=_sha(composer_raw),
            )
        )
    )
    addition = {
        "canonical_child_map_count": 154,
        "entries": {
            sidecar_path: {
                "sha256": _sha(sidecar_raw),
                "size_bytes": len(sidecar_raw),
                "role": "r9_r8_bootstrap_sidecar",
            },
            composer_path: {
                "sha256": _sha(composer_raw),
                "size_bytes": len(composer_raw),
                "role": "r10_public_source_composer",
            },
            r23_path: {
                "sha256": _sha(r23_raw),
                "size_bytes": len(r23_raw),
                "role": "r23_helper",
                "origin": "repository_source:r23.py",
            },
            str(r13_path): {
                "sha256": _sha(r13_raw),
                "size_bytes": len(r13_raw),
                "role": "r13_helper",
                "origin": "repository_source:r13.py",
            },
        },
    }
    addition_raws = {
        _key(sidecar_path): sidecar_raw,
        _key(composer_path): composer_raw,
        _key(r23_path): r23_raw,
        r13_path_key: r13_raw,
    }
    for index in range(31):
        path = f"C:/source/addition-{index}.py"
        raw = f"addition-{index}".encode()
        normalized = _key(path)
        addition["entries"][path] = {
            "sha256": _sha(raw),
            "size_bytes": len(raw),
            "role": f"support_{index}",
            "origin": f"repository_source:support_{index}.py",
        }
        addition_raws[normalized] = raw
    snapshot = json.dumps(addition, sort_keys=True, separators=(",", ":")).encode("ascii")
    r23_result.hold_addition = addition
    r23_result.hold_addition_sha256 = _sha(snapshot)
    r16_result = SimpleNamespace(
        r16_helper_path=r16_path,
        r16_helper_bytes=r16_raw,
        r16_helper_sha256=_sha(r16_raw),
    )
    assert len(addition["entries"]) == 35
    pub_parent, expected_parent = _production_parent_maps(
        r23_map_driver_source, pub, software, canonical, addition, r16_result
    )
    for path, row in addition["entries"].items():
        normalized = _key(path)
        raw = addition_raws[normalized]
        held[normalized] = raw
    held[_key(r16_path)] = r16_raw
    extra = {
        _key(r23_path): _sha(r23_raw),
        _key(r16_path): _sha(r16_raw),
        r13_path_key: _sha(r13_raw),
        _key(cu_path): _sha(cu_source),
    }
    extra_held = {
        _key(r23_path): r23_raw,
        _key(r16_path): r16_raw,
        r13_path_key: r13_raw,
        _key(cu_path): cu_source,
    }
    for index in range(295):
        path = f"C:/extra/{index}.py"
        raw = f"extra-{index}".encode()
        extra[_key(path)] = _sha(raw)
        extra_held[_key(path)] = raw

    all_fake_files = dict(extra_held)
    all_fake_files.update(held)
    fake_path_calls = []

    class _FakeCuv2Path:
        def __init__(self, value):
            fake_path_calls.append(value)
            self._path = Path(value)

        def __hash__(self):
            return hash(self._path)

        def __eq__(self, other):
            other_path = other._path if type(other) is _FakeCuv2Path else other
            return isinstance(other_path, Path) and _key(str(self._path)) == _key(str(other_path))

        def __str__(self):
            return str(self._path)

        def read_bytes(self):
            return all_fake_files[_key(str(self._path))]

    class _FakeAPI:
        @contextlib.contextmanager
        def opened(self, _path, **_kwargs):
            yield object()

    class _FakeCLI:
        def __init__(self):
            self.fail_at_identity_call = None
            self.identity_trigger = None
            self.identity_calls = 0
            self.on_identity = None

        @contextlib.contextmanager
        def _locked_readonly_file(self, path, _private, _api, *, allow_hardlinks):
            assert allow_hardlinks is True
            key = _key(str(path))
            raw = all_fake_files[key]
            handle = SimpleNamespace(raw=raw, identity=(key, len(raw), _sha(raw)))
            yield handle, handle.identity

        @staticmethod
        def _read_bounded_handle(_api, handle, maximum):
            assert len(handle.raw) <= maximum
            return handle.raw

        def _locked_file_identity(self, _api, handle, _private, *, allow_hardlinks):
            assert allow_hardlinks is True
            self.identity_calls += 1
            if self.identity_calls == self.identity_trigger and self.on_identity is not None:
                self.on_identity()
            if self.identity_calls == self.fail_at_identity_call:
                return "changed-identity"
            return handle.identity

    fake_api = _FakeAPI()
    fake_private = SimpleNamespace(_api=lambda: fake_api)
    fake_cli = _FakeCLI()
    cu_module = ModuleType(cu_module_name)
    cu_module.__file__ = str(Path(cu_path))
    cu_module.__spec__ = ModuleSpec(cu_module_name, loader=None, origin=str(Path(cu_path)))
    exec(compile(cu_source, str(Path(cu_path)), "exec", dont_inherit=True), cu_module.__dict__)
    cu_module.load = lambda _relative, _pin, name: (
        fake_private if name == "_root_public_custody_private" else fake_cli
    )
    monkeypatch.setitem(sys.modules, cu_module_name, cu_module)
    extra_scope = cu_module.held_public_sources(extra, {})
    main_scope = cu_module.held_public_sources(pub_parent, software)
    mp, mc, extra_mp, extra_mc = fake_private, fake_cli, fake_private, fake_cli
    original_extra_held = extra_held
    original_held = held
    actual_extra_mp, actual_extra_mc, actual_extra_held = extra_scope.__enter__()
    actual_mp, actual_mc, actual_held = main_scope.__enter__()
    assert (actual_extra_mp, actual_extra_mc) == (extra_mp, extra_mc)
    assert (actual_mp, actual_mc) == (mp, mc)
    assert actual_extra_held == original_extra_held
    assert actual_held == original_held
    extra_mp, extra_mc, extra_held = actual_extra_mp, actual_extra_mc, actual_extra_held
    mp, mc, held = actual_mp, actual_mc, actual_held
    source_scope = (extra_scope, extra_held, main_scope, held)
    prepared = SimpleNamespace(transform_binding={"plan_sha256": _sha(plan_raw)})
    prepared_r13 = SimpleNamespace(binding={"plan_sha256": _sha(plan_raw)})
    root_namespace = {"control_dir": control_path, "deployment_dir": deploy_path, "plan_path": plan_path}
    r15 = SimpleNamespace(_canonical_json=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii"))
    r23_prepared_hold = object()
    r17_result = object()
    class _Registry:
        def __init__(self):
            self._lock = threading.Lock()
            self._entries = []

    registry = _Registry()
    r32.StrongRetentionRegistry = _Registry
    r32._DEFAULT_RETENTION_REGISTRY = registry
    cleanup_state = {"clean": False, "reason": "session_unavailable"}
    registry_entry = (source_scope, r2_adapter, None, cleanup_state, None)
    registry._entries.append(registry_entry)

    result = r32.ParentEnvelopeResult()
    result.schema = r32.RESULT_SCHEMA
    result.status = "CLEANUP_UNCERTAIN"
    result.reason = "source_scope_unverified"
    result.cleanup_reason = "session_unavailable"
    result.child_returncode = None
    result.stdout = b""
    result.stderr = b""
    result.capture_complete = False
    result.cleanup_complete = False
    result.scope_released = False
    result.scope_retained = True
    result = r8_adapter._project_r7_parent_result(result)
    summary = r23_adapter.summarize_result(result)

    cli = object()
    extra_lease = [extra_scope, private_path, cli, extra_held]
    main_lease = [main_scope, mp, mc, held, prepared]
    keepalive = [extra_lease, r23_result, main_lease]
    namespace = {
        "__file__": str(driver_path),
        "CU": Path(cu_path),
        "cu": cu_module,
        "fake_cli": fake_cli,
        "_actual_cuv2_path": Path,
        "_fake_cuv2_path": _FakeCuv2Path,
        "fake_path_calls": fake_path_calls,
        "all_fake_files": all_fake_files,
        "sys": sys,
        "r14": r14,
        "a": r13_module,
        "r17": r17,
        "r19": r19,
        "r20": r20,
        "r21": r21,
        "r22": r22,
        "r23": r23,
        "r23_prepared_hold": r23_prepared_hold,
        "r23_adapter_result": r23_result,
        "r22_adapter_result": r22_result,
        "r21_adapter_result": r21_result,
        "r20_adapter_result": r20_result,
        "r19_adapter_result": r19_result,
        "r17_result": r17_result,
        "r16_result": r16_result,
        "r15": r15,
        "r32": r32,
        "r2_adapter": r2_adapter,
        "adapter": r23_adapter,
        "result": result,
        "summary": summary,
        "phase": "actual_parent_returned",
        "parent_started": True,
        "parent_call_returned": True,
        "plan_created": True,
        "root_phase_seconds": {"plan_contract_source_slice": 0.1, "actual_parent_supervise": 0.1},
        "auth_called": True,
        "auth_succeeded": False,
        "release_called": False,
        "release_succeeded": False,
        "main_entered": True,
        "extra_entered": True,
        "main_retained": True,
        "extra_retained": True,
        "main_postverified": False,
        "extra_postverified": False,
        "source_scope": source_scope,
        "extra_scope": extra_scope,
        "extra_held": extra_held,
        "main_scope": main_scope,
        "held": held,
        "extra_lease": extra_lease,
        "main_lease": main_lease,
        "KEEPALIVE": keepalive,
        "private": private_path,
        "cli": cli,
        "mp": mp,
        "mc": mc,
        "prepared": prepared,
        "prepared_r13": prepared_r13,
        "draft": {"plan_bytes": plan_raw},
        "active_source_map": {"plan_sha256": _sha(plan_raw)},
        "ns": root_namespace,
        "control": control,
        "deploy": deploy,
        "pub": pub,
        "soft": software,
        "expected": canonical,
        "pub_parent": pub_parent,
        "expected_parent": expected_parent,
        "extra": extra,
        "held": held,
        "extra_held": extra_held,
        "hold_addition": addition,
        "hold_addition_snapshot": snapshot,
    }

    exec(compile(driver_source, str(driver_path), "exec", dont_inherit=True), namespace)
    namespace["cu"] = cu_module
    return namespace, registry, r2_adapter


def _call(namespace, *, capsule_sha256=None):
    if capsule_sha256 is None:
        if r24r7._verify_runtime_sources is _REAL_VERIFY_RUNTIME_SOURCES:
            helper_path = r24r7._repo_root() / Path(*r24r7.R24R7_RELATIVE_PATH.split("/"))
            capsule_sha256 = _sha(helper_path.read_bytes())
        else:
            capsule_sha256 = "a" * 64
    return r24r7.close_rejected_no_session_scope(
        namespace,
        expected_owner_pid=__import__("os").getpid(),
        expected_owner_thread=threading.get_ident(),
        capsule_sha256=capsule_sha256,
    )


def _bind_pinned_root_callbacks(namespace):
    """Create only the pinned callback function objects; do not execute Root."""
    root = r24r7._repo_root()
    driver_path = (root / Path(*r24r7.R23_DRIVER_RELATIVE_PATH.split("/"))).resolve()
    driver_raw = r24r7._read_fixed_public_source(
        root,
        r24r7.R23_DRIVER_RELATIVE_PATH,
        r24r7.RUNTIME_SOURCE_PINS[r24r7.R23_DRIVER_RELATIVE_PATH],
    )
    module_code = compile(driver_raw, str(driver_path), "exec", dont_inherit=True)
    code_objects = tuple(r24r7._nested_code_objects(module_code))
    expected = {"load": 95, "authenticate": 434, "release": 477}
    for name, first_line in expected.items():
        matches = [
            code
            for code in code_objects
            if code.co_name == name and code.co_firstlineno == first_line
        ]
        assert len(matches) == 1
        namespace[name] = FunctionType(matches[0], namespace, name)
    return driver_raw


def _install_actual_pinned_adapter_chain(namespace, monkeypatch, tmp_path):
    _prepared_r13, prepared_r14, _held = r14_tests._fixture(tmp_path)
    auth_calls = []

    def authenticate(*args):
        auth_calls.append(args)
        return False

    adapter = r14.M01WindowsParentAdapter(
        prepared_r14,
        scope_authenticator=authenticate,
        fake_leaves=False,
        native=None,
        process_factory=None,
        launcher_module=None,
        image_module=None,
        clock=time.monotonic,
        sleeper=time.sleep,
    )
    r8_adapter = adapter._r8_adapter
    r5_adapter = r8_adapter._r5
    r4_adapter = r5_adapter._base
    r2_adapter = r4_adapter._inner
    r32 = r2_adapter._r32
    r32_path = "scripts/iteration41_okx_m01_r32_external_parent_budget_r1.py"
    registry = r32.StrongRetentionRegistry()
    monkeypatch.setattr(r32, "_DEFAULT_RETENTION_REGISTRY", registry)
    source_scope = namespace["source_scope"]
    registry._entries.append(
        (
            source_scope,
            r2_adapter,
            None,
            {"clean": False, "reason": "session_unavailable"},
            None,
        )
    )
    raw_result = r32.ParentEnvelopeResult(
        schema=r32.RESULT_SCHEMA,
        status="CLEANUP_UNCERTAIN",
        reason="source_scope_unverified",
        cleanup_reason="session_unavailable",
        child_returncode=None,
        stdout=b"",
        stderr=b"",
        capture_complete=False,
        cleanup_complete=False,
        scope_released=False,
        scope_retained=True,
    )
    terminal_r10 = adapter._r12._r11._r10
    assert "supervise" not in vars(terminal_r10)
    captured_projectors = []

    def fake_terminal_supervise(received_scope, release_callback, **kwargs):
        assert received_scope is source_scope
        assert release_callback is namespace["release"]
        assert kwargs == {"remaining": 5.0}
        # R14's real temporary projector is installed at this point. Calling
        # it sends this exact synthetic envelope through the pinned R13/R8/R6
        # projection chain without entering the supervisor or any I/O leaf.
        temporary_projector = vars(r8_adapter)["_project_r7_parent_result"]
        assert type(temporary_projector) is FunctionType
        closure_values = dict(
            zip(
                temporary_projector.__code__.co_freevars,
                (cell.cell_contents for cell in temporary_projector.__closure__),
            )
        )
        previous = closure_values["previous"]
        assert type(previous) is MethodType
        assert previous.__self__ is r8_adapter
        assert previous.__func__ is type(r8_adapter).__dict__["_project_r7_parent_result"]
        captured_projectors.append(previous)
        return temporary_projector(raw_result)

    terminal_r10.supervise = fake_terminal_supervise
    try:
        result = adapter.supervise(source_scope, namespace["release"], remaining=5.0)
    finally:
        del terminal_r10.supervise
    assert adapter._used is True and adapter._used_lock.locked() is False
    assert "_project_r7_parent_result" in vars(r8_adapter)
    restored = vars(r8_adapter)["_project_r7_parent_result"]
    assert type(restored) is MethodType
    assert len(captured_projectors) == 1 and restored is captured_projectors[0]
    assert restored.__self__ is r8_adapter
    assert restored.__func__ is type(r8_adapter).__dict__["_project_r7_parent_result"]
    assert "supervise" not in vars(terminal_r10)
    r6_module = type(r8_adapter).__init__.__globals__["_R6"]
    assert type(result) is r6_module.M01ParentDiagnosticResult
    assert result.stdout_bytes is None and result.stderr_bytes is None
    namespace["r14"] = r14
    namespace["a"] = r14._R13
    monkeypatch.setitem(sys.modules, r24r7.R13_MODULE_NAME, r14._R13)
    root = r24r7._repo_root()
    r13_path = root / Path(*r24r7.R13_SOURCE_RELATIVE_PATH.split("/"))
    r13_key = _key(str(r13_path))
    r13_raw = r13_path.read_bytes()
    r13_sha256 = _sha(r13_raw)
    monkeypatch.setitem(r24r7.RUNTIME_SOURCE_PINS, r24r7.R13_SOURCE_RELATIVE_PATH, r13_sha256)
    for mapping_name in ("held", "extra_held"):
        namespace[mapping_name][r13_key] = r13_raw
    for mapping_name in ("extra", "pub_parent", "expected_parent"):
        namespace[mapping_name][r13_key] = r13_sha256
    addition = namespace["hold_addition"]
    r13_rows = [path for path in addition["entries"] if _key(path) == r13_key]
    assert len(r13_rows) == 1
    addition["entries"][r13_rows[0]].update(
        {"sha256": r13_sha256, "size_bytes": len(r13_raw)}
    )
    snapshot = json.dumps(addition, sort_keys=True, separators=(",", ":")).encode("ascii")
    namespace["hold_addition_snapshot"] = snapshot
    namespace["r23_adapter_result"].hold_addition_sha256 = _sha(snapshot)
    namespace["r19_adapter_result"].adapter = adapter
    namespace["r20_adapter_result"].adapter = adapter
    namespace["r21_adapter_result"].adapter = adapter
    namespace["r22_adapter_result"].adapter = adapter
    namespace["adapter"]._base_adapter = adapter
    namespace["r2_adapter"] = r2_adapter
    namespace["r32"] = r32
    namespace["result"] = result
    namespace["summary"] = namespace["adapter"].summarize_result(result)
    return adapter, r8_adapter, r5_adapter, r4_adapter, r2_adapter, r32, registry, auth_calls


def test_no_session_capsule_closes_exact_scopes_and_receipt_is_one_use(monkeypatch):
    namespace, registry, _r2 = _fresh(monkeypatch)

    receipt = _call(namespace)

    assert type(receipt) is r24r7.NoSessionCleanupReceipt
    fields = receipt.consume()
    assert fields["status"] == "SOURCE_SCOPES_CLOSED_AFTER_AUTH_REJECTION"
    assert fields["original_parent_reason"] == "source_scope_unverified"
    assert fields["session_created"] is False
    assert fields["worker_created"] is False
    assert fields["child_returncode_observed"] is False
    assert fields["main_scope_postverified_closed"] is True
    assert fields["extra_scope_postverified_closed"] is True
    assert fields["r32_registry_entry_removed"] is True
    assert fields["root_scope_references_dropped"] is True
    assert fields["authority"] is False and fields["case_pass"] is False
    assert fields["verifier_phase_ordinal"] == 130
    assert r24r7.R24R7_RELATIVE_PATH in fields["source_pins"]
    with pytest.raises(AttributeError):
        receipt._payload_bytes = b"changed"
    assert registry._entries == []
    assert namespace["KEEPALIVE"] == [namespace["r23_adapter_result"]]
    assert all(name not in namespace for name in ("source_scope", "held", "extra_held", "main_scope", "extra_scope"))
    with pytest.raises(r24r7.NoSessionCleanupBlocked) as error:
        receipt.consume()
    assert error.value.code == "capsule_receipt_reused"


def test_actual_pinned_r14_r8_r5_r4_r2_loader_chain_closes_fake_scopes_without_modules_alias(
    monkeypatch, tmp_path
):
    namespace, _fake_registry, _fake_r2 = _fresh(monkeypatch)
    monkeypatch.setattr(r24r7, "_verify_runtime_sources", _REAL_VERIFY_RUNTIME_SOURCES)
    monkeypatch.setattr(r24r7, "_verify_loaded_module", _REAL_VERIFY_LOADED_MODULE)
    monkeypatch.setattr(r24r7, "_verify_class_source", _REAL_VERIFY_CLASS_SOURCE)
    monkeypatch.setattr(r24r7, "_verify_function_source", _REAL_VERIFY_FUNCTION_SOURCE)
    (
        adapter,
        r8_adapter,
        r5_adapter,
        r4_adapter,
        r2_adapter,
        r32,
        registry,
        auth_calls,
    ) = _install_actual_pinned_adapter_chain(namespace, monkeypatch, tmp_path)

    r8_globals = type(r8_adapter).__init__.__globals__
    r6_module = r8_globals["_R6"]
    r5_module = r6_module._R5
    r5_name = type(r5_adapter).__module__
    assert type(r5_module) is ModuleType
    assert vars(r5_module) is type(r5_adapter).__init__.__globals__
    assert r5_name == vars(r5_module)["__name__"]
    assert sys.modules.get(r5_name) is not r5_module
    assert type(r4_adapter) is r5_module._R4.M01WindowsParentAdapter
    assert type(r2_adapter) is r4_adapter._r2_module.M01WindowsParentAdapter
    assert r2_adapter.fake_leaves is False and r2_adapter.native is None
    assert r2_adapter.process_factory is None
    assert auth_calls == []
    actual_result = namespace["result"]
    assert type(actual_result) is r6_module.M01ParentDiagnosticResult
    assert actual_result.status == "CLEANUP_UNCERTAIN"
    assert actual_result.reason == "source_scope_unverified"
    assert actual_result.cleanup_reason == "session_unavailable"
    assert actual_result.child_returncode is None
    assert actual_result.capture_complete is False and actual_result.cleanup_complete is False
    assert actual_result.scope_released is False and actual_result.scope_retained is True
    assert actual_result.stdout_bytes is None and actual_result.stderr_bytes is None
    assert namespace["main_scope"].gen.gi_frame.f_locals["raw_bytes"] is namespace["held"]
    assert namespace["extra_scope"].gen.gi_frame.f_locals["raw_bytes"] is namespace["extra_held"]
    restored_projector = vars(r8_adapter)["_project_r7_parent_result"]
    assert type(restored_projector) is MethodType
    assert restored_projector.__self__ is r8_adapter
    assert restored_projector.__func__ is type(r8_adapter).__dict__["_project_r7_parent_result"]
    r24r7._validate_adapter_chain(namespace, threading.get_ident())
    # Use the exact Root callback code for every subsequent capsule call,
    # including the rejected-result negatives below.
    _bind_pinned_root_callbacks(namespace)

    r14_module = namespace["r14"]
    original_r13_module = r14_module._R13
    try:
        r14_module._R13 = ModuleType("_r24_wrong_r13")
        with pytest.raises(r24r7.NoSessionCleanupBlocked) as wrong_r13_binding:
            r24r7._validate_adapter_chain(namespace, threading.get_ident())
        assert wrong_r13_binding.value.code == "capsule_source_pin"
    finally:
        r14_module._R13 = original_r13_module

    r14_type = type(adapter)
    original_r14_supervise = r14_type.supervise
    try:
        r14_type.supervise = lambda self, *_args, **_kwargs: None
        with pytest.raises(r24r7.NoSessionCleanupBlocked) as changed_r14_code:
            r24r7._validate_adapter_chain(namespace, threading.get_ident())
        assert changed_r14_code.value.code == "capsule_source_pin"
    finally:
        r14_type.supervise = original_r14_supervise

    original_projector = r8_adapter._project_r7_parent_result
    r8_adapter._project_r7_parent_result = lambda _raw: actual_result
    try:
        with pytest.raises(r24r7.NoSessionCleanupBlocked) as overridden_projection:
            r24r7._validate_adapter_chain(namespace, threading.get_ident())
        assert overridden_projection.value.code == "capsule_adapter_chain"
    finally:
        r8_adapter._project_r7_parent_result = original_projector
    assert vars(r8_adapter)["_project_r7_parent_result"] is original_projector

    namespace["result"] = r32.ParentEnvelopeResult(
        schema=r32.RESULT_SCHEMA,
        status="CLEANUP_UNCERTAIN",
        reason="source_scope_unverified",
        cleanup_reason="session_unavailable",
        child_returncode=None,
        stdout=b"",
        stderr=b"",
        capture_complete=False,
        cleanup_complete=False,
        scope_released=False,
        scope_retained=True,
    )
    namespace["summary"] = {}
    with pytest.raises(r24r7.NoSessionCleanupBlocked) as raw_result_rejected:
        _call(namespace)
    assert raw_result_rejected.value.code == "capsule_result_not_no_session"
    assert namespace["release_called"] is False and registry._entries
    namespace["result"] = actual_result
    namespace["summary"] = adapter.summarize_result(actual_result)

    namespace["result"] = dataclasses.replace(actual_result, child_returncode=0)
    namespace["summary"] = adapter.summarize_result(namespace["result"])
    with pytest.raises(r24r7.NoSessionCleanupBlocked) as changed_result:
        _call(namespace)
    assert changed_result.value.code == "capsule_result_not_no_session"
    assert namespace["release_called"] is False and registry._entries
    namespace["result"] = actual_result
    namespace["summary"] = adapter.summarize_result(actual_result)

    r5_init = type(r5_adapter).__dict__["__init__"]
    original_r5_init_code = r5_init.__code__
    try:
        r6_module._R5 = None
        with pytest.raises(r24r7.NoSessionCleanupBlocked) as missing_r5:
            r24r7._validate_adapter_chain(namespace, threading.get_ident())
        assert missing_r5.value.code == "capsule_source_pin"
    finally:
        r6_module._R5 = r5_module

    try:
        r5_init.__code__ = type(r5_adapter).summarize_result.__code__
        with pytest.raises(r24r7.NoSessionCleanupBlocked) as changed_r5_code:
            r24r7._validate_adapter_chain(namespace, threading.get_ident())
        assert changed_r5_code.value.code == "capsule_source_pin"
    finally:
        r5_init.__code__ = original_r5_init_code

    r4_module = r5_module._R4
    original_r2_module = r4_adapter._r2_module
    try:
        r5_module._R4 = ModuleType("_r24_wrong_r4")
        with pytest.raises(r24r7.NoSessionCleanupBlocked) as changed_r4_module:
            r24r7._validate_adapter_chain(namespace, threading.get_ident())
        assert changed_r4_module.value.code == "capsule_source_pin"
    finally:
        r5_module._R4 = r4_module

    try:
        r4_adapter._r2_module = ModuleType("_r24_wrong_r2")
        with pytest.raises(r24r7.NoSessionCleanupBlocked) as changed_r2_module:
            r24r7._validate_adapter_chain(namespace, threading.get_ident())
        assert changed_r2_module.value.code == "capsule_adapter_chain"
    finally:
        r4_adapter._r2_module = original_r2_module

    try:
        r6_module._R5 = None
        with pytest.raises(r24r7.NoSessionCleanupBlocked) as missing_r5_at_capsule_entry:
            _call(namespace)
        assert missing_r5_at_capsule_entry.value.code == "capsule_source_pin"
        assert missing_r5_at_capsule_entry.value.phase_ordinal == 70
        assert namespace["release_called"] is False
        assert namespace["main_retained"] is True
        assert namespace["extra_retained"] is True
        assert registry._entries
    finally:
        r6_module._R5 = r5_module

    # The pinned release() performs the real CUV2 generator exits; only the
    # private API/CLI leaves inside those pinned generators are fake.
    assert namespace["release"].__globals__ is namespace
    assert namespace["release"].__globals__["cu"] is namespace["cu"]
    assert namespace["main_scope"].gen.gi_frame.f_globals is namespace["cu"].__dict__
    namespace["fake_path_calls"].clear()
    namespace["fake_source_reads"] = []
    r24_path = r24r7._repo_root() / Path(*r24r7.R24R7_RELATIVE_PATH.split("/"))
    callback_path_state = []
    release_code = namespace["release"].__code__

    def capture_release_path_state(frame, event, _arg):
        if event == "line" and frame.f_code is release_code and frame.f_lineno == 482:
            generator_globals = namespace["main_scope"].gen.gi_frame.f_globals
            callback_path_state.append(
                (
                    frame.f_globals.get("cu") is namespace["cu"],
                    namespace["cu"].Path is Path,
                    generator_globals is namespace["cu"].__dict__,
                    generator_globals.get("Path") is Path,
                )
            )
        return capture_release_path_state

    previous_trace = sys.gettrace()
    path_type = type(namespace["CU"])
    original_read_bytes = path_type.read_bytes

    def read_held_source_bytes(path):
        key = _key(str(path))
        raw = namespace["all_fake_files"].get(key)
        if type(raw) is bytes:
            namespace["fake_source_reads"].append(key)
            return raw
        return original_read_bytes(path)

    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(path_type, "read_bytes", read_held_source_bytes)
            sys.settrace(capture_release_path_state)
            try:
                receipt = _call(namespace, capsule_sha256=_sha(r24_path.read_bytes()))
            except r24r7.NoSessionCleanupBlocked:
                assert callback_path_state == [(True, True, True, True)]
                raise
    finally:
        sys.settrace(previous_trace)
    assert callback_path_state == [(True, True, True, True)]
    assert namespace["fake_source_reads"]

    fields = receipt.consume()
    assert fields["status"] == "SOURCE_SCOPES_CLOSED_AFTER_AUTH_REJECTION"
    assert fields["case_pass"] is False and fields["authority"] is False
    assert fields["main_scope_postverified_closed"] is True
    assert fields["extra_scope_postverified_closed"] is True
    assert registry._entries == []
    assert namespace["KEEPALIVE"] == [namespace["r23_adapter_result"]]
    assert namespace["main_retained"] is False
    assert namespace["extra_retained"] is False
    assert namespace["main_postverified"] is True
    assert namespace["extra_postverified"] is True
    assert adapter._used is True and r32.PARENT_CLEANUP_SECONDS == 5.0


@pytest.mark.parametrize(
    "mutate,expected_code",
    [
        (lambda ns, _registry, _r2: ns.__setitem__("auth_called", False), "capsule_same_call_required"),
        (
            lambda ns, _registry, _r2: setattr(
                ns["release"],
                "__code__",
                ns["authenticate"].__code__.replace(
                    co_filename=ns["__file__"], co_firstlineno=477
                ),
            ),
            "capsule_same_call_required",
        ),
        (
            lambda ns, _registry, _r2: setattr(ns["extra_scope"], "__exit__", lambda *_args: True),
            "capsule_scope_binding",
        ),
        (
            lambda ns, _registry, _r2: object.__setattr__(
                ns["result"], "child_returncode", 0
            ),
            "capsule_result_not_no_session",
        ),
        (lambda ns, _registry, _r2: ns["held"].pop(next(iter(ns["held"]))), "capsule_source_maps"),
        (
            lambda ns, _registry, _r2: ns["pub_parent"].pop(next(iter(ns["pub_parent"]))),
            "capsule_source_maps",
        ),
        (
            lambda ns, _registry, _r2: ns["extra_held"].__setitem__(
                _key(str(r24r7._repo_root() / Path(*r24r7.R13_SOURCE_RELATIVE_PATH.split("/")))),
                b"changed-r13-source",
            ),
            "capsule_source_pin",
        ),
        (lambda ns, _registry, r2: setattr(r2, "native", object()), "capsule_adapter_chain"),
        (lambda _ns, registry, _r2: registry._entries.__setitem__(0, (object(), object(), None, {}, None)), "capsule_registry_binding"),
        (lambda _ns, registry, _r2: setattr(registry, "_lock", SimpleNamespace()), "capsule_registry_binding"),
        (
            lambda ns, _registry, _r2: setattr(ns["r32"], "PARENT_CLEANUP_SECONDS", 30.0),
            "capsule_registry_binding",
        ),
        (lambda _ns, _registry, r2: setattr(r2, "_retained_late", type("EmptyEqual", (list,), {"__eq__": lambda self, _other: True})()), "capsule_adapter_chain"),
    ],
)
def test_capsule_rejects_tampered_no_session_facts_before_release(monkeypatch, mutate, expected_code):
    namespace, registry, r2 = _fresh(monkeypatch)
    mutate(namespace, registry, r2)

    with pytest.raises(r24r7.NoSessionCleanupBlocked) as error:
        _call(namespace)

    assert error.value.code == expected_code
    assert namespace["release_called"] is False
    assert namespace["main_retained"] is True
    assert namespace["extra_retained"] is True
    assert registry._entries


def test_partial_normal_exit_keeps_registry_and_live_scope_references(monkeypatch):
    namespace, registry, _r2 = _fresh(monkeypatch)
    namespace["fake_cli"].fail_at_identity_call = len(namespace["held"]) + 1

    with pytest.raises(r24r7.NoSessionCleanupBlocked) as error:
        _call(namespace)

    assert error.value.code == "capsule_scope_release_failed"
    assert registry._entries
    assert namespace["main_retained"] is False
    assert namespace["extra_retained"] is True
    assert "source_scope" in namespace and "held" in namespace
    assert namespace["KEEPALIVE"][0] is namespace["extra_lease"]


@pytest.mark.parametrize("held_name", ["held", "extra_held"])
def test_cuv2_suspended_raw_map_identity_is_required_before_cleanup(monkeypatch, held_name):
    namespace, registry, _r2 = _fresh(monkeypatch)
    namespace[held_name] = {}

    with pytest.raises(r24r7.NoSessionCleanupBlocked) as error:
        _call(namespace)

    assert error.value.code == "capsule_scope_binding"
    assert error.value.phase_ordinal == 50
    assert namespace["release_called"] is False
    assert namespace["main_retained"] is True
    assert namespace["extra_retained"] is True
    assert registry._entries


def test_registry_contention_after_scope_exit_keeps_registry_and_root_refs(monkeypatch):
    namespace, registry, _r2 = _fresh(monkeypatch)
    namespace["fake_cli"].identity_trigger = len(namespace["held"]) + 1
    namespace["fake_cli"].on_identity = registry._lock.acquire

    with pytest.raises(r24r7.NoSessionCleanupBlocked) as error:
        _call(namespace)

    assert error.value.code == "capsule_registry_close_failed"
    assert registry._entries
    assert namespace["source_scope"] is registry._entries[0][0]
    assert namespace["extra_lease"] in namespace["KEEPALIVE"]
    assert namespace["main_lease"] in namespace["KEEPALIVE"]
    registry._lock.release()


def test_failed_first_scope_close_retains_both_original_scopes(monkeypatch):
    namespace, registry, _r2 = _fresh(monkeypatch)
    namespace["fake_cli"].fail_at_identity_call = 1

    with pytest.raises(r24r7.NoSessionCleanupBlocked) as error:
        _call(namespace)

    assert error.value.code == "capsule_scope_release_failed"
    assert namespace["main_retained"] is True
    assert namespace["extra_retained"] is True
    assert registry._entries[0][0] is namespace["source_scope"]
    assert namespace["extra_lease"] in namespace["KEEPALIVE"]
    assert namespace["main_lease"] in namespace["KEEPALIVE"]


def test_validator_replacement_of_release_is_rejected_after_validation(monkeypatch):
    namespace, registry, _r2 = _fresh(monkeypatch)

    def replace_release(_value):
        namespace["release"] = lambda *_args: True
        return True

    namespace["r23"].verify_root_hold = replace_release
    with pytest.raises(r24r7.NoSessionCleanupBlocked) as error:
        _call(namespace)

    assert error.value.code == "capsule_same_call_required"
    assert namespace["release_called"] is False
    assert namespace["main_retained"] is True
    assert namespace["extra_retained"] is True
    assert registry._entries


def test_public_pin_reader_checks_bounded_file_identity(tmp_path):
    raw = b"public source fixture"
    (tmp_path / "source.py").write_bytes(raw)

    assert r24r7._read_fixed_public_source(tmp_path, "source.py", _sha(raw)) == raw
    with pytest.raises(r24r7.NoSessionCleanupBlocked) as error:
        r24r7._read_fixed_public_source(tmp_path, "source.py", "0" * 64)
    assert error.value.code == "capsule_source_pin"


def test_pinned_r23_parent_map_builder_produces_exact_r6_closure_and_rejects_soft_collision(
    monkeypatch,
):
    namespace, _registry, _r2 = _fresh(monkeypatch)

    assert len(namespace["pub"]) == 118
    assert len(namespace["soft"]) == 36
    assert len(namespace["expected"]) == 154
    assert len(namespace["pub_parent"]) == 154
    assert len(namespace["expected_parent"]) == 190
    assert len(namespace["held"]) == 190
    assert len(namespace["extra"]) == 299
    assert len(namespace["extra_held"]) == 299
    assert r24r7._hash_map(namespace["held"]) == {
        **{_key(path): digest for path, digest in namespace["pub_parent"].items()},
        **{_key(path): digest for path, digest in namespace["soft"].items()},
    }
    r24r7._validate_maps(namespace)

    colliding_addition = dict(namespace["hold_addition"])
    entries = dict(colliding_addition["entries"])
    original_path = next(iter(entries))
    moved_row = entries.pop(original_path)
    entries[next(iter(namespace["soft"]))] = moved_row
    colliding_addition["entries"] = entries
    driver_raw = r24r7._read_fixed_public_source(
        r24r7._repo_root(),
        r24r7.R23_DRIVER_RELATIVE_PATH,
        r24r7.RUNTIME_SOURCE_PINS[r24r7.R23_DRIVER_RELATIVE_PATH],
    )
    with pytest.raises(AssertionError):
        _production_parent_maps(
            driver_raw,
            namespace["pub"],
            namespace["soft"],
            namespace["expected"],
            colliding_addition,
            namespace["r16_result"],
        )


def test_actual_r23_hold_producer_emits_only_the_two_bound_originless_rows(
    actual_r23_adapter_result,
):
    result = actual_r23_adapter_result
    assert r23_producer.verify_parent_adapter_result(result)
    entries = result.hold_addition["entries"]
    assert len(entries) == 36

    prepared_r13 = result.prepared_hold.prepared_r13
    r10_prepared = prepared_r13.r10_prepared
    r9_prepared = r10_prepared.r9_prepared
    expected = {
        _key(r9_prepared.sidecar_path): (
            r9_prepared.sidecar_path,
            {
                "sha256": r9_prepared.sidecar_sha256,
                "size_bytes": r9_prepared.sidecar_size_bytes,
                "role": "r9_r8_bootstrap_sidecar",
            },
            r9_prepared.r8_bootstrap_bytes,
        ),
        _key(r10_prepared.composer_path): (
            r10_prepared.composer_path,
            {
                "sha256": r10_prepared.composer_sha256,
                "size_bytes": len(r10_prepared.composer_bytes),
                "role": "r10_public_source_composer",
            },
            r10_prepared.composer_bytes,
        ),
    }
    observed_originless = {
        _key(path): (path, row)
        for path, row in entries.items()
        if type(row) is dict and set(row) == {"sha256", "size_bytes", "role"}
    }
    assert set(observed_originless) == set(expected)
    assert {
        key: (path, row, expected[key][2]) for key, (path, row) in observed_originless.items()
    } == expected
    assert all(
        type(row) is dict
        and set(row) == {"sha256", "size_bytes", "role", "origin"}
        and type(row["origin"]) is str
        and row["origin"]
        for path, row in entries.items()
        if _key(path) not in expected
    )
    assert r24r7._originless_producer_rows({"r23_adapter_result": result}) == expected


@pytest.mark.parametrize("tamper", ["add_origin", "wrong_role", "wrong_hash", "wrong_size"])
def test_originless_rows_reject_nonproducer_shapes(monkeypatch, tamper):
    namespace, _registry, _r2 = _fresh(monkeypatch)
    path = next(
        path
        for path, row in namespace["hold_addition"]["entries"].items()
        if "origin" not in row
    )
    row = namespace["hold_addition"]["entries"][path]
    if tamper == "add_origin":
        row["origin"] = "repository_source:unexpected"
    elif tamper == "wrong_role":
        row["role"] = "r10_unexpected_role"
    elif tamper == "wrong_hash":
        row["sha256"] = "0" * 64
    else:
        row["size_bytes"] += 1
    snapshot = json.dumps(
        namespace["hold_addition"], sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    namespace["hold_addition_snapshot"] = snapshot
    namespace["r23_adapter_result"].hold_addition_sha256 = _sha(snapshot)

    with pytest.raises(r24r7.NoSessionCleanupBlocked) as error:
        r24r7._validate_maps(namespace)

    assert error.value.code == "capsule_source_maps"


def test_runtime_source_pins_match_frozen_r23_literals_and_public_bytes():
    root = r24r7._repo_root()
    driver_raw = r24r7._read_fixed_public_source(
        root,
        r24r7.R23_DRIVER_RELATIVE_PATH,
        r24r7.RUNTIME_SOURCE_PINS[r24r7.R23_DRIVER_RELATIVE_PATH],
    )
    tree = ast.parse(driver_raw.decode("utf-8"), filename=r24r7.R23_DRIVER_RELATIVE_PATH)
    assignments = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                assignments[target.id] = node.value

    driver_pin_pairs = {}
    for name, value_node in assignments.items():
        if not name.endswith("_SHA"):
            continue
        source_name = name[:-4]
        source_node = assignments.get(source_name)
        if not isinstance(source_node, ast.BinOp) or not isinstance(source_node.op, ast.Div):
            continue
        if not isinstance(source_node.left, ast.Name) or source_node.left.id != "ROOT":
            continue
        if not isinstance(source_node.right, ast.Constant) or type(source_node.right.value) is not str:
            continue
        pin = ast.literal_eval(value_node)
        driver_pin_pairs[source_node.right.value] = pin

    expected_driver_sources = {
        "scripts/iteration41_okx_m01_r33_active_outer_activation_r13_r1.py",
        "scripts/iteration41_okx_m01_r33_parent_adapter_transport_r14_r1.py",
        "scripts/iteration41_okx_m01_r33_final_output_hold_r15_r1.py",
        "scripts/iteration41_okx_m01_r33_final_output_hold_r16_r1.py",
        "scripts/iteration41_okx_m01_r33_source_map_gate_r17_r1.py",
        "scripts/iteration41_okx_m01_r33_parent_adapter_constructor_r18_r1.py",
        "scripts/iteration41_okx_m01_r33_child_source_scope_r19_r1.py",
        "scripts/iteration41_okx_m01_r33_child_entry_path_r20_r1.py",
        "scripts/iteration41_okx_m01_r33_child_main_map_r21_r1.py",
        "scripts/iteration41_okx_m01_r33_root_prepare_r22_r1.py",
        "scripts/iteration41_okx_m01_r33_root_reason_class_r23_r1.py",
    }
    assert expected_driver_sources <= driver_pin_pairs.keys()
    cu_path, cu_sha256, cu_module_name = r24r7._driver_cuv2_binding(driver_raw)
    assert cu_path == "D:/temp/iteration41-root-public-custody-v2.py"
    assert cu_sha256 == r24r7.CUV2_PUBLIC_SOURCE_SHA256
    assert cu_module_name == "_root_m01_r12_r2_cu"
    cuv2_source = r24r7._read_fixed_public_source(
        root,
        r24r7.CUV2_PUBLIC_SOURCE_RELATIVE_PATH,
        r24r7.CUV2_PUBLIC_SOURCE_SHA256,
    )
    assert _sha(cuv2_source) == r24r7.CUV2_PUBLIC_SOURCE_SHA256
    for relative_path, expected_sha256 in driver_pin_pairs.items():
        if relative_path in r24r7.RUNTIME_SOURCE_PINS:
            assert r24r7.RUNTIME_SOURCE_PINS[relative_path] == expected_sha256

    assert len(r24r7.RUNTIME_SOURCE_PINS) == 19
    for relative_path, expected_sha256 in r24r7.RUNTIME_SOURCE_PINS.items():
        raw = r24r7._read_fixed_public_source(root, relative_path, expected_sha256)
        assert _sha(raw) == expected_sha256

