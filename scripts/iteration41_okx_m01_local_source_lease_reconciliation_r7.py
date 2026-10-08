"""Typed GateR1 context and CUv2 source-lease reconciliation (source-only)."""

from __future__ import annotations

import ast
import contextlib
from dataclasses import dataclass
import hashlib
import inspect
import json
import ntpath
from pathlib import Path
import re
import threading
from types import FunctionType, ModuleType
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"

CUV2_RELATIVE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
)
CUV2_SOURCE_BYTES = 2344
CUV2_SOURCE_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
CUV2_RUNTIME_ORIGIN = "D:/temp/iteration41-root-public-custody-v2.py"
CUV2_RUNTIME_MODULE_NAME = "_root_m01_local_cuv2_oct9"
ROOT_RUNNER_RELATIVE = ".codex-tmp/okx_m01_local_lifecycle_root_actual_20261009.py"

GATE_RELATIVE = "scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r1.py"
GATE_SOURCE_BYTES = 35502
GATE_SOURCE_SHA256 = "2faa317a695c4cc5418f0d01f59bcbd92b32303101d7dd54d982082868f1bc5f"
READER_RELATIVE = (
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py"
)
READER_SOURCE_BYTES = 63711
READER_SOURCE_SHA256 = "b350e0d0110a3c87f6fc44a841b9df12e229eff2efac1060d66b598c17cbc734"
SUPERVISOR_RELATIVE = (
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py"
)
SUPERVISOR_SOURCE_BYTES = 71188
SUPERVISOR_SOURCE_SHA256 = "188b929b4e74b6e16a54d21093b6d52a7471849b161b2777945561e6d8d62e82"
WORKER_RELATIVE = (
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py"
)
WORKER_SOURCE_BYTES = 60000
WORKER_SOURCE_SHA256 = "aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41"

_PUBLIC_SOURCE_PINS = {
    "backtrader_runtime/certification_roundtrip_private.py": "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd",
    "examples/000_live_certification/okx_penetration/_certification/__init__.py": "a55f2a221bc45d1b840c15ca9ec8e5f46579e011728ec9e7c3b0748eacc7f7dc",
    "examples/000_live_certification/okx_penetration/_certification/cases.py": "0e0d7618846975db37551222f3c902ceee2b975f4be0b8236dcf021508492762",
    "examples/000_live_certification/okx_penetration/_certification/config.py": "3b5141a3c903e8c7eb0388d2907906c06c54ac41657e32fb9f11360e7efdeae3",
    "examples/000_live_certification/okx_penetration/_certification/evidence.py": "05916efcd52a49fbd6303d315e17b8f57a3f411b3557872250e899636ffb9217",
    "examples/000_live_certification/okx_penetration/_certification/fixed_owner_routes.py": "fe22dfca3b902c0b04855acd89f947d5d8de72a2475090ea92179eb415dad401",
    "examples/000_live_certification/okx_penetration/_certification/m01_private_monitor_v2.py": "1c319502dcec4da91a7166ad1a532e4610319ca837ac93f2391f21fda87ae1db",
    "examples/000_live_certification/okx_penetration/_certification/models.py": "f6db3e492fb8681bb156a577515b73e9966142e447f9d857ad4ec8a024389362",
    "examples/000_live_certification/okx_penetration/_certification/runner.py": "b25dbccd2ea745433d1f646d217c98d970207a6e861f9da45b9c0d40a0b340e5",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/__init__.py": "d7cbd961ed06466f6bd2388d44a5951f92b0bb9f61d930cc9d26ec21be8d1a5c",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/current_types.py": "cd896051b0580195baa569989622c18fec594afc3772e7ea4af9e4cf226778ea",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py": "188b929b4e74b6e16a54d21093b6d52a7471849b161b2777945561e6d8d62e82",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py": "aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/__init__.py": "ae66c18bb4d289dd2e09e9ac637af8a6ef017f4f6cc5edec4a23ee23d7e560e6",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py": "b350e0d0110a3c87f6fc44a841b9df12e229eff2efac1060d66b598c17cbc734",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/entry.py": "a5ac85ff1b4c19a542abff56e728696eedee3959e5e7e4df8d6ac7cec0332575",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/issuer.py": "afdfb863dc8917ef07dbf844183b6216df578a85d3477dda1c32c9226cdb9ad8",
    "examples/000_live_certification/okx_penetration/cases/M01/M01_strategy.py": "2ce73442c1e1ed0be95b3065e5434fb95b16d2b6026ed86e20b07a8e6ba97afc",
    "examples/000_live_certification/okx_penetration/cases/M01/run.py": "95db64019fb4f7e6124e15ead558b2686c70c8987d2b4ec941467e269ff0fc92",
    "tests/unit/live_certification/test_okx_m01_readonly_monitor_v3.py": "9d66d25310f5ee1b29943b222854e2a9d9b8ba48adcfe9848037f7afcb297a0d",
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-reason-preservation-r2-selected-source-qa-r4-2026-10-09/source-index.json": "abc6e49afab4fad7d44dc70474cfc993e212e71c56270b7d065374da63da9bc8",
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-reason-preservation-r2-selected-source-qa-r4-2026-10-09/source-map.json": "db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3",
    GATE_RELATIVE: "2faa317a695c4cc5418f0d01f59bcbd92b32303101d7dd54d982082868f1bc5f",
    "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r1.py": "380320a9585564911b3b0ffb078c15dd84159a8ea7a5266ab87e7e5f4b7e290b",
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-root-helper-lifecycle-gate-independent-review-r1-2026-10-09/README.md": "569930510fae09a7c3a6f6242b89dc78b8ec1c56a34f278e5e46dfa797e5b638",
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76",
    ".codex-tmp/okx_m01_local_lifecycle_root_actual_20261009.py": "3ae21d1e8540686016205e7383f7d6d55c0466b25b8ebb8e29982337e239e897",
}
_SOFTWARE_SOURCE_PINS = {
    "C:/anaconda3/python.exe": "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642",
    "C:/anaconda3/python311.dll": "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00",
    str(Path(CUV2_RUNTIME_ORIGIN)): CUV2_SOURCE_SHA256,
}

OBSERVATION_RELATIVE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-okx-m01-local-lifecycle-root-actual-r1-2026-10-09/observation.json"
)
OBSERVATION_BYTES = 2014
OBSERVATION_SHA256 = "56a26581507f900067b02d9c01aceb4a58dc2166774df76bc339de87230f7621"
RETAINED_FACTS_RELATIVE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-okx-m01-local-lifecycle-root-actual-r1-2026-10-09/retained-facts.json"
)
RETAINED_FACTS_BYTES = 349
RETAINED_FACTS_SHA256 = "47e2b39dda3bf773fbe881d51079a16750d361c672f560ceeb8f898515976021"

_SAFE_CODE = re.compile(r"[a-z0-9_]{1,64}\Z")
_RETAINED_CONTEXTS: list["_RetainedReferences"] = []
_LOCK = threading.RLock()
_SUPERVISOR_FUNCTIONS = (
    "_winapi",
    "_new_pipe_state",
    "_create_suspended",
    "_drain",
    "_write_all",
    "_wait_process",
    "_process_exit_code",
    "_active_count",
    "_assign_control_to_job",
    "_resume_control",
    "_terminate_control",
    "_close_handle",
    "_new_job",
    "_new_pipe",
    "_environment_block",
    "_worker_bootstrap",
    "_hold_runtime_files",
    "_hold_and_verify_runtime_file",
    "_canonical_win32_path",
)
_PRIVATE_RELATIVE = "backtrader_runtime/certification_roundtrip_private.py"
_PRIVATE_SOURCE_BYTES = 17537
_PRIVATE_SOURCE_SHA256 = _PUBLIC_SOURCE_PINS[_PRIVATE_RELATIVE]
_CLI_RELATIVE = "backtrader_runtime/certification_binance_roundtrip_r3_cli.py"
_CLI_SOURCE_BYTES = 33887
_CLI_SOURCE_SHA256 = _PUBLIC_SOURCE_PINS[_CLI_RELATIVE]
_CUSTODY_FUNCTIONS = {
    "_root_public_custody_private": ("_api", "_path"),
    "_root_public_custody_cli": ("_require", "_locked_file_identity"),
}


class ReconciliationError(ValueError):
    """Finite source-lease reconciliation rejection."""

    def __init__(self, code: str):
        self.code = code if type(code) is str and _SAFE_CODE.fullmatch(code) else "rejected"
        super().__init__(self.code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ReconciliationError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path_key(value: Any) -> str:
    return ntpath.normcase(ntpath.normpath(str(value))).replace("\\", "/")


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except Exception:
        raise ReconciliationError("finite_observation_invalid") from None


def _postcheck(callback) -> bool:
    try:
        return bool(callback())
    except Exception:
        return False


def _gate_registry_identity_matches(
    gate_module: ModuleType,
    gate_context: Any,
    gate_context_registry: Any,
    reader_module: ModuleType,
    supervisor_module: ModuleType,
    registry_snapshot: tuple[int, ...],
    retained_entries: tuple[Any, ...],
) -> bool:
    if (
        type(gate_context_registry) is not list
        or gate_module.__dict__.get("_ORPHANED_GATE_CONTEXTS") is not gate_context_registry
        or tuple(id(item) for item in gate_context_registry) != registry_snapshot
        or len(gate_context_registry) != 1
        or len(retained_entries) != 1
    ):
        return False
    entry = gate_context_registry[0]
    return (
        entry is retained_entries[0]
        and type(entry) is tuple
        and len(entry) == 10
        and entry[0] is gate_context
        and entry[1] is reader_module
        and entry[2] is supervisor_module
        and entry[9] is supervisor_module.__dict__.get("_ORPHANED_RUNTIME_HANDLE_SETS")
    )


def _gate_projection_matches_snapshot(
    *,
    gate_module: ModuleType,
    gate_context: Any,
    gate_observation: Any,
    gate_context_registry: Any,
    reader_module: ModuleType,
    supervisor_module: ModuleType,
    gate_source: bytes,
    expected: bytes | None,
) -> bool:
    if expected is None:
        return False
    try:
        return (
            _project_gate_context(
                gate_module=gate_module,
                gate_context=gate_context,
                gate_observation=gate_observation,
                gate_context_registry=gate_context_registry,
                reader_module=reader_module,
                supervisor_module=supervisor_module,
                gate_source=gate_source,
            )
            == expected
        )
    except Exception:
        return False


def _scope_raw_byte_bindings_unchanged(
    raw_bytes: Any, snapshot: tuple[tuple[str, bytes], ...]
) -> bool:
    return (
        type(raw_bytes) is dict
        and all(type(key) is str and type(value) is bytes for key, value in raw_bytes.items())
        and len(raw_bytes) == len(snapshot)
        and all(raw_bytes.get(key) is raw for key, raw in snapshot)
    )


def _load_finite_pair(evidence_bytes: tuple[bytes, bytes]) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(type(evidence_bytes) is tuple and len(evidence_bytes) == 2, "evidence_pair_invalid")
    observation_raw, retained_raw = evidence_bytes
    _require(
        type(observation_raw) is bytes
        and len(observation_raw) == OBSERVATION_BYTES
        and _sha(observation_raw) == OBSERVATION_SHA256
        and type(retained_raw) is bytes
        and len(retained_raw) == RETAINED_FACTS_BYTES
        and _sha(retained_raw) == RETAINED_FACTS_SHA256,
        "failure_evidence_pin_mismatch",
    )
    try:
        observation = json.loads(observation_raw.decode("utf-8"))
        retained = json.loads(retained_raw.decode("utf-8"))
    except Exception:
        raise ReconciliationError("failure_evidence_invalid") from None
    _require(type(observation) is dict and type(retained) is dict, "failure_evidence_invalid")
    gate_result = observation.get("gate_result")
    _require(
        observation.get("schema") == "iteration41.okx.m01.local-lifecycle.root_actual.v1"
        and observation.get("status") == "BLOCKED"
        and observation.get("reason") == "root_local_check_blocked"
        and observation.get("gate_invocations") == 1
        and observation.get("outer_normal_postverify_and_close") is False
        and observation.get("gate_retained_context_count") == 1
        and observation.get("runtime_orphan_count") == 0
        and observation.get("host_exit_permitted") is False
        and observation.get("protected_deployment_read") is False
        and observation.get("provider_call") is False
        and observation.get("formal_m01_pass_count") == 0
        and observation.get("executed_source_verified") is True
        and observation.get("pre_function_global_binding_verified") is True
        and observation.get("post_function_global_binding_verified") is True
        and observation.get("public_pin_count") == 27
        and observation.get("software_pin_count") == 3
        and type(gate_result) is dict,
        "failure_observation_mismatch",
    )
    _require(
        gate_result.get("schema") == "iteration41.okx.m01.root-helper-lifecycle-gate.v1"
        and gate_result.get("status") == "LIFECYCLE_BLOCKED"
        and gate_result.get("phase") == "stdout_drain"
        and gate_result.get("process_wait_succeeded") is True
        and gate_result.get("cleanup_wait_succeeded") is True
        and gate_result.get("cleanup_wait_attempted") is True
        and gate_result.get("process_reaped_after_cleanup") is True
        and gate_result.get("process_exit_code_present") is True
        and gate_result.get("process_exit_code_zero") is True
        and gate_result.get("job_zero_after_exit") is False
        and gate_result.get("termination_requested") is True
        and gate_result.get("termination_succeeded") is True
        and gate_result.get("win32_api") == "ReadFile"
        and gate_result.get("winerror") == 109
        and gate_result.get("stdout_matches_fixed") is False
        and gate_result.get("stderr_empty") is False
        and gate_result.get("stdout_eof") is True
        and gate_result.get("stderr_eof") is True
        and gate_result.get("stdout_read_done") is True
        and gate_result.get("stderr_read_done") is True
        and gate_result.get("stdout_thread_joined") is True
        and gate_result.get("stderr_thread_joined") is True
        and gate_result.get("all_observed_handles_closed") is True
        and gate_result.get("handle_close_calls") == 11
        and gate_result.get("handle_close_failures") == 0
        and gate_result.get("retained_context") is True
        and gate_result.get("runtime_registry_empty_after") is True
        and gate_result.get("production_acceptance") is False,
        "gate_failure_facts_mismatch",
    )
    _require(
        retained.get("schema") == "iteration41.okx.m01.local-lifecycle.retained-facts.v1"
        and retained.get("gate_context_retained") is True
        and retained.get("outer_scope_retained") is True
        and retained.get("job_counts") == [1, 1, 1]
        and retained.get("wait_results") == [True, True, True]
        and retained.get("handle_close_failures") == 0
        and retained.get("drain_threads_alive") == 0
        and retained.get("source_bindings_unchanged") is True
        and retained.get("no_new_invocation") is True
        and retained.get("private_capture_read") is False,
        "retained_facts_mismatch",
    )
    return observation, retained


def _finite_gate_projection(value: Any) -> bytes:
    _require(type(value) is dict, "gate_projection_type_invalid")
    _require(
        all(
            type(key) is str and (item is None or type(item) in (bool, int, str))
            for key, item in value.items()
        ),
        "gate_projection_shape_invalid",
    )
    return _json_bytes(value)


def _project_gate_context(
    *,
    gate_module: ModuleType,
    gate_context: Any,
    gate_observation: Any,
    gate_context_registry: Any,
    reader_module: ModuleType,
    supervisor_module: ModuleType,
    gate_source: bytes,
) -> bytes:
    """Call only the source-verified, finite GateR1 result projection."""
    _require(type(gate_module) is ModuleType, "gate_module_type_invalid")
    _require(type(gate_context_registry) is list, "gate_context_registry_mismatch")
    observation_class = gate_module.__dict__.get("_Observation")
    _require(
        type(observation_class) is type
        and observation_class.__module__ == gate_module.__name__
        and observation_class.__qualname__ == "_Observation"
        and type(gate_context) is observation_class,
        "gate_context_type_mismatch",
    )
    _require(
        gate_context.reader is reader_module and gate_context.supervisor is supervisor_module,
        "gate_context_module_binding_mismatch",
    )
    _require(
        gate_module.__dict__.get("_ORPHANED_GATE_CONTEXTS") is gate_context_registry
        and len(gate_context_registry) == 1,
        "gate_context_registry_mismatch",
    )
    entry = gate_context_registry[0]
    _require(
        type(entry) is tuple
        and len(entry) == 10
        and entry[0] is gate_context
        and entry[1] is reader_module
        and entry[2] is supervisor_module
        and entry[9] is supervisor_module.__dict__.get("_ORPHANED_RUNTIME_HANDLE_SETS"),
        "gate_context_entry_mismatch",
    )
    expected_path = (ROOT / GATE_RELATIVE).resolve(strict=True)
    _require(
        type(gate_source) is bytes
        and len(gate_source) == GATE_SOURCE_BYTES
        and _sha(gate_source) == GATE_SOURCE_SHA256
        and Path(gate_module.__file__).resolve(strict=True) == expected_path,
        "gate_context_source_pin_mismatch",
    )
    _, source_code = _code_index(gate_source, str(expected_path))
    result_function = vars(observation_class).get("result")
    expected_code = source_code.get("_Observation.result")
    _require(
        type(result_function) is FunctionType
        and result_function.__globals__ is gate_module.__dict__
        and result_function.__module__ == gate_module.__name__
        and result_function.__qualname__ == "_Observation.result"
        and result_function.__code__.co_filename == str(expected_path)
        and result_function.__code__ == expected_code
        and result_function.__defaults__ is None
        and result_function.__kwdefaults__ is None
        and result_function.__closure__ is None,
        "gate_result_function_binding_mismatch",
    )
    computed = result_function(gate_context)
    computed_bytes = _finite_gate_projection(computed)
    reported_bytes = _finite_gate_projection(gate_observation)
    _require(computed_bytes == reported_bytes, "gate_context_projection_mismatch")
    return computed_bytes


def _code_index(raw: bytes, filename: str) -> tuple[Any, dict[str, Any]]:
    try:
        root_code = compile(raw, filename, "exec", dont_inherit=True)
    except Exception:
        raise ReconciliationError("module_source_compile_failed") from None
    result: dict[str, Any] = {}
    code_type = type(root_code)
    pending = [root_code]
    while pending:
        code = pending.pop()
        qualname = getattr(code, "co_qualname", code.co_name)
        if type(qualname) is str:
            result[qualname] = code
        pending.extend(value for value in code.co_consts if isinstance(value, code_type))
    return root_code, result


def _source_function_names(raw: bytes) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except Exception:
        raise ReconciliationError("module_source_parse_failed") from None
    functions: list[str] = []
    classes: list[str] = []

    def visit(nodes: list[ast.stmt], prefix: str = "") -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(f"{prefix}.{node.name}" if prefix else node.name)
            elif isinstance(node, ast.ClassDef):
                qualname = f"{prefix}.{node.name}" if prefix else node.name
                classes.append(qualname)
                visit(node.body, qualname)

    visit(tree.body)
    return tuple(functions), tuple(classes)


def _source_function_descriptor_kinds(raw: bytes) -> dict[str, str]:
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except Exception:
        raise ReconciliationError("module_source_parse_failed") from None
    result: dict[str, str] = {}

    def decorator_name(value: ast.expr) -> tuple[str | None, str | None]:
        if isinstance(value, ast.Name):
            return value.id, None
        if isinstance(value, ast.Attribute):
            return value.attr, value.attr
        if isinstance(value, ast.Call):
            return decorator_name(value.func)
        return None, None

    def kind_for(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        names = tuple(decorator_name(item) for item in node.decorator_list)
        if any(
            name == "property" or attribute in {"getter", "setter", "deleter"}
            for name, attribute in names
        ):
            return "property"
        if any(name == "staticmethod" for name, _attribute in names):
            return "staticmethod"
        if any(name == "classmethod" for name, _attribute in names):
            return "classmethod"
        return "function"

    def visit(nodes: list[ast.stmt], prefix: str = "") -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}.{node.name}" if prefix else node.name
                _require(qualname not in result, "module_source_function_name_collision")
                result[qualname] = kind_for(node)
            elif isinstance(node, ast.ClassDef):
                qualname = f"{prefix}.{node.name}" if prefix else node.name
                visit(node.body, qualname)

    visit(tree.body)
    return result


def _source_contextmanager_names(raw: bytes) -> frozenset[str]:
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except Exception:
        raise ReconciliationError("module_source_parse_failed") from None

    imported_names = {"contextmanager"}
    contextlib_modules = {"contextlib"}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "contextlib":
            for alias in node.names:
                if alias.name == "contextmanager":
                    imported_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "contextlib":
                    contextlib_modules.add(alias.asname or alias.name)

    def is_contextmanager_decorator(value: ast.expr) -> bool:
        if isinstance(value, ast.Call):
            return is_contextmanager_decorator(value.func)
        if isinstance(value, ast.Name):
            return value.id in imported_names
        if isinstance(value, ast.Attribute):
            return (
                value.attr == "contextmanager"
                and isinstance(value.value, ast.Name)
                and value.value.id in contextlib_modules
            )
        return False

    result: set[str] = set()

    def visit(nodes: list[ast.stmt], prefix: str = "") -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(is_contextmanager_decorator(item) for item in node.decorator_list):
                    result.add(f"{prefix}.{node.name}" if prefix else node.name)
            elif isinstance(node, ast.ClassDef):
                qualname = f"{prefix}.{node.name}" if prefix else node.name
                visit(node.body, qualname)

    visit(tree.body)
    return frozenset(result)


def _source_descriptor_matches(module: ModuleType, qualname: str, expected_kind: str) -> bool:
    parts = qualname.split(".")
    owner: Any = module
    for part in parts[:-1]:
        namespace = module.__dict__ if type(owner) is ModuleType else vars(owner)
        owner = namespace.get(part)
        if owner is None:
            return False
    namespace = module.__dict__ if type(owner) is ModuleType else vars(owner)
    descriptor = namespace.get(parts[-1])
    expected_types = {
        "function": FunctionType,
        "property": property,
        "staticmethod": staticmethod,
        "classmethod": classmethod,
    }
    return type(descriptor) is expected_types.get(expected_kind)


def _resolve_source_function(module: ModuleType, qualname: str) -> tuple[Any, Any]:
    parts = qualname.split(".")
    owner: Any = module
    for part in parts[:-1]:
        namespace = module.__dict__ if type(owner) is ModuleType else vars(owner)
        owner = namespace.get(part)
        if owner is None:
            return None, None
    namespace = module.__dict__ if type(owner) is ModuleType else vars(owner)
    value = namespace.get(parts[-1])
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    elif isinstance(value, property):
        value = value.fget
    if type(value) is FunctionType and hasattr(value, "__wrapped__"):
        return value, value.__wrapped__
    return value, value


def _same_closure_cells(left: FunctionType, right: FunctionType) -> bool:
    left_cells = left.__closure__ or ()
    right_cells = right.__closure__ or ()
    if len(left_cells) != len(right_cells):
        return False
    for left_cell, right_cell in zip(left_cells, right_cells):
        try:
            left_value = left_cell.cell_contents
            right_value = right_cell.cell_contents
        except ValueError:
            return False
        if left_value is not right_value:
            return False
    return True


def _contextmanager_wrapper_matches(wrapper: Any, function: Any) -> bool:
    if type(wrapper) is not FunctionType or type(function) is not FunctionType:
        return False
    try:
        expected = contextlib.contextmanager(function)
    except Exception:
        return False
    return (
        wrapper.__code__ == expected.__code__
        and wrapper.__globals__ is expected.__globals__
        and wrapper.__module__ == expected.__module__
        and wrapper.__name__ == expected.__name__
        and wrapper.__qualname__ == expected.__qualname__
        and wrapper.__defaults__ is expected.__defaults__
        and wrapper.__kwdefaults__ is expected.__kwdefaults__
        and getattr(wrapper, "__wrapped__", None) is function
        and _same_closure_cells(wrapper, expected)
    )


def _safe_value_snapshot(value: Any, depth: int = 0) -> Any:
    if value is None or type(value) in (bool, int, str, bytes):
        return ("value", type(value), value)
    if type(value) is float:
        return ("float", value.hex())
    if depth >= 16:
        return ("identity", id(value))
    if type(value) is tuple:
        return ("tuple", tuple(_safe_value_snapshot(item, depth + 1) for item in value))
    if type(value) is list:
        return ("list", tuple(_safe_value_snapshot(item, depth + 1) for item in value))
    if type(value) is dict:
        return (
            "dict",
            tuple(
                (_safe_value_snapshot(key, depth + 1), _safe_value_snapshot(item, depth + 1))
                for key, item in value.items()
            ),
        )
    if type(value) in (set, frozenset):
        items = [_safe_value_snapshot(item, depth + 1) for item in value]
        return (type(value).__name__, tuple(sorted(items, key=repr)))
    return ("identity", id(value))


def _function_closure_snapshot(function: FunctionType) -> tuple[Any, ...]:
    snapshot = []
    for cell in function.__closure__ or ():
        try:
            value = cell.cell_contents
        except ValueError:
            snapshot.append((id(cell), "empty"))
        else:
            snapshot.append((id(cell), id(value), _safe_value_snapshot(value)))
    return tuple(snapshot)


def _function_binding_snapshot(function: FunctionType) -> tuple[Any, ...]:
    wrapped = getattr(function, "__wrapped__", None)
    return (
        id(function.__code__),
        id(function.__globals__),
        id(function.__defaults__) if function.__defaults__ is not None else None,
        _safe_value_snapshot(function.__defaults__),
        id(function.__kwdefaults__) if function.__kwdefaults__ is not None else None,
        _safe_value_snapshot(function.__kwdefaults__),
        function.__module__,
        function.__name__,
        function.__qualname__,
        function.__doc__,
        id(wrapped) if wrapped is not None else None,
        _safe_value_snapshot(function.__dict__),
        _safe_value_snapshot(function.__annotations__),
        _function_closure_snapshot(function),
    )


def _verify_all_source_functions(
    module: ModuleType,
    raw: bytes,
    source_code: dict[str, Any],
    expected_path: Path | str,
) -> tuple[tuple[str, Any, Any, Any], ...]:
    function_names, class_names = _source_function_names(raw)
    descriptor_kinds = _source_function_descriptor_kinds(raw)
    contextmanager_names = _source_contextmanager_names(raw)
    for qualname in class_names:
        owner: Any = module
        parts = qualname.split(".")
        for index, part in enumerate(parts):
            namespace = module.__dict__ if type(owner) is ModuleType else vars(owner)
            owner = namespace.get(part)
            _require(
                isinstance(owner, type)
                and owner.__module__ == module.__name__
                and owner.__qualname__ == ".".join(parts[: index + 1]),
                "module_class_binding_mismatch",
            )
    bindings = []
    for qualname in function_names:
        _require(
            _source_descriptor_matches(module, qualname, descriptor_kinds[qualname]),
            "module_source_descriptor_mismatch",
        )
        wrapper, function = _resolve_source_function(module, qualname)
        expected_code = source_code.get(qualname)
        _require(
            type(function) is FunctionType
            and function.__globals__ is module.__dict__
            and function.__module__ == module.__name__
            and expected_code is not None
            and function.__code__ == expected_code
            and _path_key(function.__code__.co_filename) == _path_key(expected_path),
            "module_source_function_binding_mismatch",
        )
        if wrapper is not function:
            _require(
                type(wrapper) is FunctionType
                and getattr(wrapper, "__wrapped__", None) is function
                and wrapper.__module__ == module.__name__,
                "module_source_wrapper_binding_mismatch",
            )
        if qualname in contextmanager_names:
            _require(
                _contextmanager_wrapper_matches(wrapper, function),
                "module_contextmanager_wrapper_binding_mismatch",
            )
        bindings.append((qualname, wrapper, function, function.__code__))
    return tuple(bindings)


def _verify_module(
    module: ModuleType,
    raw: bytes,
    relative: str,
    expected_size: int,
    expected_sha: str,
    code_names: tuple[str, ...],
    *,
    expected_origin: str | None = None,
) -> Path | str:
    _require(type(module) is ModuleType, "module_type_mismatch")
    if expected_origin is None:
        expected_path: Path | str = (ROOT / relative).resolve(strict=True)
        try:
            origin: Path | str = Path(module.__file__).resolve(strict=True)
        except Exception:
            raise ReconciliationError("module_origin_unavailable") from None
        origin_matches = origin == expected_path
    else:
        expected_path = expected_origin
        try:
            origin_matches = _path_key(module.__file__) == _path_key(expected_origin)
        except Exception:
            origin_matches = False
    _require(
        origin_matches
        and type(raw) is bytes
        and len(raw) == expected_size
        and _sha(raw) == expected_sha,
        "module_source_pin_mismatch",
    )
    compile_filename = module.__file__ if expected_origin is not None else str(expected_path)
    _expected_module_code, source_code = _code_index(raw, compile_filename)
    for name in code_names:
        function = getattr(module, name, None)
        code = getattr(function, "__code__", None)
        expected_code = source_code.get(name)
        _require(
            type(function) is FunctionType
            and _path_key(code.co_filename) == _path_key(expected_path)
            and function.__globals__ is module.__dict__
            and expected_code is not None
            and code == expected_code,
            "module_function_binding_mismatch",
        )
    _verify_all_source_functions(module, raw, source_code, expected_path)
    return expected_path


def _module_dict_identity(module: ModuleType) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((name, id(value)) for name, value in module.__dict__.items()))


def _function_identity(module: ModuleType, name: str) -> tuple[Any, Any, Any]:
    function = (
        getattr(module.held_public_sources, "__wrapped__")
        if name == "held_public_sources.__wrapped__"
        else getattr(module, name)
    )
    return function, function.__code__, function.__globals__


def _binding_snapshot(
    cuv2_module: ModuleType,
    gate_module: ModuleType,
    reader_module: ModuleType,
    supervisor_module: ModuleType,
    worker_module: ModuleType,
    custody_modules: tuple[ModuleType, ModuleType],
    source_bytes: Mapping[str, bytes],
    scope_raw_bytes: Mapping[str, bytes],
) -> tuple[Any, ...]:
    module_sources = (
        (cuv2_module, source_bytes["cuv2"], CUV2_RUNTIME_ORIGIN),
        (gate_module, source_bytes["gate"], ROOT / GATE_RELATIVE),
        (reader_module, source_bytes["reader"], ROOT / READER_RELATIVE),
        (supervisor_module, source_bytes["supervisor"], ROOT / SUPERVISOR_RELATIVE),
        (worker_module, source_bytes["worker"], ROOT / WORKER_RELATIVE),
        (
            custody_modules[0],
            scope_raw_bytes[_path_key(ROOT / _PRIVATE_RELATIVE)],
            ROOT / _PRIVATE_RELATIVE,
        ),
        (
            custody_modules[1],
            scope_raw_bytes[_path_key(ROOT / _CLI_RELATIVE)],
            ROOT / _CLI_RELATIVE,
        ),
    )
    functions = []
    classes = []
    for module, raw, _path in module_sources:
        function_names, class_names = _source_function_names(raw)
        contextmanager_names = _source_contextmanager_names(raw)
        for qualname in function_names:
            wrapper, function = _resolve_source_function(module, qualname)
            _require(
                type(wrapper) is FunctionType and type(function) is FunctionType,
                "module_source_function_missing",
            )
            functions.append(
                (
                    module,
                    qualname,
                    wrapper,
                    function,
                    _function_binding_snapshot(wrapper),
                    _function_binding_snapshot(function),
                    qualname in contextmanager_names,
                )
            )
        for qualname in class_names:
            cls = _resolve_source_class(module, qualname)
            classes.append((module, qualname, cls, _class_dict_identity(cls)))
    modules = (
        cuv2_module,
        gate_module,
        reader_module,
        supervisor_module,
        worker_module,
        *custody_modules,
    )
    dictionaries = tuple(
        (module, module.__dict__, _module_dict_identity(module)) for module in modules
    )
    return tuple(functions), tuple(classes), dictionaries


def _resolve_source_class(module: ModuleType, qualname: str) -> type:
    owner: Any = module
    for part in qualname.split("."):
        namespace = module.__dict__ if type(owner) is ModuleType else vars(owner)
        owner = namespace.get(part)
    return owner


def _class_dict_identity(value: Any) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, type):
        return ()
    return tuple(sorted((name, id(item)) for name, item in vars(value).items()))


def _bindings_unchanged(snapshot: tuple[Any, ...]) -> bool:
    functions, classes, dictionaries = snapshot
    for (
        module,
        qualname,
        wrapper,
        function,
        wrapper_snapshot,
        function_snapshot,
        is_contextmanager,
    ) in functions:
        current_wrapper, current_function = _resolve_source_function(module, qualname)
        if (
            current_wrapper is not wrapper
            or current_function is not function
            or function.__globals__ is not module.__dict__
            or _function_binding_snapshot(current_wrapper) != wrapper_snapshot
            or _function_binding_snapshot(current_function) != function_snapshot
            or (
                is_contextmanager
                and not _contextmanager_wrapper_matches(current_wrapper, current_function)
            )
        ):
            return False
    for module, qualname, cls, values in classes:
        if (
            _resolve_source_class(module, qualname) is not cls
            or _class_dict_identity(cls) != values
        ):
            return False
    for module, namespace, values in dictionaries:
        if module.__dict__ is not namespace or _module_dict_identity(module) != values:
            return False
    return True


def _verify_source_bindings(
    *,
    cuv2_module: ModuleType,
    gate_module: ModuleType,
    reader_module: ModuleType,
    supervisor_module: ModuleType,
    worker_module: ModuleType,
    source_bytes: Mapping[str, bytes],
    custody_modules: tuple[ModuleType, ModuleType],
    scope_raw_bytes: Mapping[str, bytes],
) -> tuple[Any, ...]:
    _require(type(source_bytes) is dict, "source_bytes_invalid")
    _require(
        set(source_bytes) == {"cuv2", "gate", "reader", "supervisor", "worker"},
        "source_bytes_shape_invalid",
    )
    _verify_module(
        cuv2_module,
        source_bytes["cuv2"],
        CUV2_RELATIVE,
        CUV2_SOURCE_BYTES,
        CUV2_SOURCE_SHA256,
        ("check", "sha", "load"),
        expected_origin=CUV2_RUNTIME_ORIGIN,
    )
    gate_path = _verify_module(
        gate_module,
        source_bytes["gate"],
        GATE_RELATIVE,
        GATE_SOURCE_BYTES,
        GATE_SOURCE_SHA256,
        ("run_fixed_synthetic_probe",),
    )
    reader_path = _verify_module(
        reader_module,
        source_bytes["reader"],
        READER_RELATIVE,
        READER_SOURCE_BYTES,
        READER_SOURCE_SHA256,
        ("_root_helper_wrapper", "_run_pinned_root_helper"),
    )
    supervisor_path = _verify_module(
        supervisor_module,
        source_bytes["supervisor"],
        SUPERVISOR_RELATIVE,
        SUPERVISOR_SOURCE_BYTES,
        SUPERVISOR_SOURCE_SHA256,
        _SUPERVISOR_FUNCTIONS,
    )
    _verify_module(
        worker_module,
        source_bytes["worker"],
        WORKER_RELATIVE,
        WORKER_SOURCE_BYTES,
        WORKER_SOURCE_SHA256,
        (),
    )
    _require(
        type(custody_modules) is tuple
        and len(custody_modules) == 2
        and all(type(module) is ModuleType for module in custody_modules)
        and type(scope_raw_bytes) is dict
        and all(type(path) is str and type(raw) is bytes for path, raw in scope_raw_bytes.items()),
        "custody_source_binding_inputs_invalid",
    )
    normalized_scope_raw = {_path_key(path): raw for path, raw in scope_raw_bytes.items()}
    private_module, cli_module = custody_modules
    private_raw = normalized_scope_raw.get(_path_key(ROOT / _PRIVATE_RELATIVE))
    cli_raw = normalized_scope_raw.get(_path_key(ROOT / _CLI_RELATIVE))
    _verify_module(
        private_module,
        private_raw,
        _PRIVATE_RELATIVE,
        _PRIVATE_SOURCE_BYTES,
        _PRIVATE_SOURCE_SHA256,
        _CUSTODY_FUNCTIONS["_root_public_custody_private"],
    )
    _verify_module(
        cli_module,
        cli_raw,
        _CLI_RELATIVE,
        _CLI_SOURCE_BYTES,
        _CLI_SOURCE_SHA256,
        _CUSTODY_FUNCTIONS["_root_public_custody_cli"],
    )
    _require(
        private_module.__name__ == "_root_public_custody_private"
        and cli_module.__name__ == "_root_public_custody_cli"
        and Path(private_module.__file__).resolve(strict=True)
        == (ROOT / _PRIVATE_RELATIVE).resolve(strict=True)
        and Path(cli_module.__file__).resolve(strict=True)
        == (ROOT / _CLI_RELATIVE).resolve(strict=True),
        "custody_module_origin_mismatch",
    )
    _require(
        reader_module.__name__ == "_m01_readonly_monitor_v3.current_reader"
        and supervisor_module.__name__ == "_m01_readonly_monitor_v2.job_supervisor"
        and worker_module.__name__ == "_m01_readonly_monitor_v2.worker"
        and reader_module.job_supervisor is supervisor_module
        and reader_module.worker is worker_module
        and supervisor_module.worker is worker_module,
        "production_module_relationship_mismatch",
    )
    _require(
        cuv2_module.__name__ == CUV2_RUNTIME_MODULE_NAME
        and gate_module.__name__ == "_root_m01_local_lifecycle_gate_oct9",
        "root_module_name_mismatch",
    )
    cuv2_callable = getattr(cuv2_module, "held_public_sources", None)
    cuv2_generator = getattr(cuv2_callable, "__wrapped__", None)
    _require(
        type(cuv2_callable) is FunctionType
        and type(cuv2_generator) is FunctionType
        and cuv2_generator.__globals__ is cuv2_module.__dict__
        and _path_key(cuv2_generator.__code__.co_filename) == _path_key(CUV2_RUNTIME_ORIGIN),
        "cuv2_generator_binding_mismatch",
    )
    try:
        cuv2_code = compile(
            source_bytes["cuv2"], str(cuv2_module.__file__), "exec", dont_inherit=True
        )
        expected_generator_code = next(
            value
            for value in cuv2_code.co_consts
            if inspect.iscode(value) and value.co_name == "held_public_sources"
        )
    except Exception:
        raise ReconciliationError("cuv2_generator_source_unavailable") from None
    _require(
        cuv2_generator.__code__ == expected_generator_code,
        "cuv2_generator_source_mismatch",
    )
    _require(
        gate_path == (ROOT / GATE_RELATIVE).resolve(strict=True)
        and reader_path == (ROOT / READER_RELATIVE).resolve(strict=True)
        and supervisor_path == (ROOT / SUPERVISOR_RELATIVE).resolve(strict=True),
        "source_path_binding_mismatch",
    )
    return _binding_snapshot(
        cuv2_module,
        gate_module,
        reader_module,
        supervisor_module,
        worker_module,
        custody_modules,
        source_bytes,
        normalized_scope_raw,
    )


def _verify_scope(
    scope: Any,
    cuv2_module: ModuleType,
    scope_value: Any,
    module_source_bytes: Mapping[str, bytes],
) -> tuple[Any, Any]:
    manager_type = getattr(contextlib, "_GeneratorContextManager", None)
    _require(manager_type is not None and type(scope) is manager_type, "cuv2_scope_type_mismatch")
    exit_method = getattr(scope, "__exit__", None)
    _require(
        getattr(exit_method, "__self__", None) is scope
        and getattr(exit_method, "__func__", None) is manager_type.__dict__.get("__exit__"),
        "cuv2_scope_exit_binding_mismatch",
    )
    generator = getattr(scope, "gen", None)
    public_function = getattr(cuv2_module, "held_public_sources", None)
    generator_function = getattr(public_function, "__wrapped__", None)
    _require(
        inspect.isgenerator(generator)
        and inspect.getgeneratorstate(generator) == inspect.GEN_SUSPENDED
        and generator.gi_code is getattr(generator_function, "__code__", None),
        "cuv2_scope_not_active",
    )
    _require(
        type(scope_value) is tuple
        and len(scope_value) == 3
        and type(scope_value[2]) is dict
        and scope_value[0] is not None
        and scope_value[1] is not None,
        "cuv2_scope_yield_invalid",
    )
    frame = generator.gi_frame
    _require(
        frame is not None
        and frame.f_globals is cuv2_module.__dict__
        and frame.f_locals.get("private") is scope_value[0]
        and frame.f_locals.get("cli") is scope_value[1]
        and frame.f_locals.get("raw_bytes") is scope_value[2],
        "cuv2_scope_yield_binding_mismatch",
    )
    _require(
        getattr(scope_value[0], "__name__", None) == "_root_public_custody_private"
        and getattr(scope_value[1], "__name__", None) == "_root_public_custody_cli",
        "cuv2_scope_custody_module_name_mismatch",
    )
    pins = frame.f_locals.get("pins")
    software_pins = frame.f_locals.get("software_pins")
    _require(
        type(pins) is dict
        and all(type(path) is str and type(digest) is str for path, digest in pins.items())
        and pins == _PUBLIC_SOURCE_PINS
        and type(software_pins) is dict
        and all(type(path) is str and type(digest) is str for path, digest in software_pins.items())
        and software_pins == _SOFTWARE_SOURCE_PINS
        and len(pins) == 27
        and len(software_pins) == 3,
        "cuv2_scope_pin_maps_mismatch",
    )
    raw_bytes = scope_value[2]
    _require(
        type(raw_bytes) is dict
        and all(type(path) is str and type(raw) is bytes for path, raw in raw_bytes.items()),
        "cuv2_scope_raw_map_types_mismatch",
    )
    expected_public_hashes = {
        _path_key(ROOT / relative): digest for relative, digest in _PUBLIC_SOURCE_PINS.items()
    }
    expected_software_hashes = {
        _path_key(path): digest for path, digest in _SOFTWARE_SOURCE_PINS.items()
    }
    expected_keys = set(expected_public_hashes) | set(expected_software_hashes)
    normalized_raw = {_path_key(path): raw for path, raw in raw_bytes.items()}
    _require(
        len(raw_bytes) == 30
        and len(normalized_raw) == len(raw_bytes)
        and set(normalized_raw) == expected_keys
        and all(type(normalized_raw[path]) is bytes for path in expected_keys)
        and all(
            _sha(normalized_raw[path]) == expected_public_hashes[path]
            for path in expected_public_hashes
        ),
        "cuv2_scope_raw_map_mismatch",
    )
    runtime_source_key = _path_key(CUV2_RUNTIME_ORIGIN)
    _require(
        _sha(normalized_raw[runtime_source_key]) == CUV2_SOURCE_SHA256
        and expected_software_hashes[runtime_source_key] == CUV2_SOURCE_SHA256,
        "cuv2_scope_runtime_source_mismatch",
    )
    source_locations = {
        "cuv2": CUV2_RUNTIME_ORIGIN,
        "gate": ROOT / GATE_RELATIVE,
        "reader": ROOT / READER_RELATIVE,
        "supervisor": ROOT / SUPERVISOR_RELATIVE,
        "worker": ROOT / WORKER_RELATIVE,
    }
    _require(
        type(module_source_bytes) is dict
        and all(
            type(label) is str and type(raw) is bytes for label, raw in module_source_bytes.items()
        )
        and set(module_source_bytes) == set(source_locations)
        and all(
            type(module_source_bytes[label]) is bytes
            and normalized_raw.get(_path_key(path)) is module_source_bytes[label]
            for label, path in source_locations.items()
        ),
        "cuv2_scope_module_bytes_mismatch",
    )
    return generator, exit_method


def _function_facts(exc: BaseException | None) -> tuple[str | None, str | None]:
    if exc is None:
        return None, None
    if isinstance(exc, ReconciliationError):
        return "precondition", exc.code
    return "scope_exit_exception", "source_scope_exit_failed"


@dataclass(frozen=True)
class _RetainedReferences:
    cuv2_module: Any
    source_scope: Any
    source_scope_exit_method: Any
    source_scope_value: Any
    gate_module: Any
    gate_context: Any
    gate_observation: Any
    gate_context_registry: Any
    gate_context_entries: tuple[Any, ...]
    compiled_modules: tuple[Any, ...]
    custody_modules: tuple[Any, ...]
    public_source_bytes: Any
    failure_evidence: tuple[bytes, ...]
    root_tty_reference: Any
    binding_snapshot: Any
    observation_snapshot: bytes | None
    gate_projection_snapshot: bytes | None
    registry_snapshot: tuple[int, ...]
    runtime_handle_registry: Any
    runtime_registry_snapshot: tuple[int, ...]
    source_bytes_snapshot: tuple[tuple[str, bytes], ...]
    scope_raw_bytes_snapshot: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class ReconciliationReceipt:
    """Finite facts plus strong references that the caller must keep alive."""

    facts: dict[str, bool | str | int | None]
    retained: _RetainedReferences


def _base_facts(status: str, error_category: str | None, error_code: str | None) -> dict:
    return {
        "schema": "iteration41.okx.m01.local-source-lease-reconciliation.v5",
        "status": status,
        "error_category": error_category,
        "error_code": error_code,
        "source_scope_exit_attempted": False,
        "source_scope_exit_method_verified": False,
        "normal_postverify_exit_returned": False,
        "source_scope_generator_closed": False,
        "source_lease_close_state": "preflight_not_attempted",
        "retained_python_references": True,
        "gate_context_typed": False,
        "gate_context_projection_matches": False,
        "gate_context_identity_unchanged": False,
        "gate_observation_unchanged": False,
        "gate_context_registry_unchanged": False,
        "runtime_handle_registry_unchanged": False,
        "compiled_module_bindings_unchanged": False,
        "held_source_byte_bindings_unchanged": False,
        "held_scope_raw_byte_bindings_unchanged": False,
        "public_failure_evidence_unchanged": False,
        "root_tty_reference_held": False,
        "retained_context": True,
    }


def reconcile_normal_cuv2_source_scope(
    *,
    cuv2_module: ModuleType,
    source_scope: Any,
    source_scope_value: Any,
    gate_module: ModuleType,
    gate_context: Any,
    gate_observation: dict[str, Any],
    gate_context_registry: list[Any],
    reader_module: ModuleType,
    supervisor_module: ModuleType,
    worker_module: ModuleType,
    custody_modules: tuple[Any, ...],
    module_source_bytes: dict[str, bytes],
    failure_evidence: tuple[bytes, bytes],
    root_tty_reference: Any,
) -> ReconciliationReceipt:
    """Postverify and exit only the suspended CUv2 public-source lease scope.

    The source scope must already have yielded normally. Child/Job state is not
    interpreted or changed; all supplied gate, module, evidence, and TTY refs
    are retained before any validation or exit attempt.
    """
    gate_entries = tuple(gate_context_registry) if type(gate_context_registry) is list else ()
    compiled_modules = (gate_module, reader_module, supervisor_module, worker_module)
    registry_ids = tuple(id(item) for item in gate_entries)
    runtime_handle_registry = (
        gate_entries[0][9]
        if gate_entries
        and type(gate_entries[0]) is tuple
        and len(gate_entries[0]) == 10
        and type(gate_entries[0][9]) is list
        else None
    )
    runtime_registry_snapshot = (
        tuple(id(item) for item in runtime_handle_registry)
        if type(runtime_handle_registry) is list
        else ()
    )
    source_bytes_snapshot = (
        tuple(sorted(module_source_bytes.items()))
        if type(module_source_bytes) is dict
        and all(
            type(key) is str and type(value) is bytes for key, value in module_source_bytes.items()
        )
        else ()
    )
    scope_raw_bytes_snapshot = (
        tuple(sorted(source_scope_value[2].items()))
        if type(source_scope_value) is tuple
        and len(source_scope_value) == 3
        and type(source_scope_value[2]) is dict
        and all(
            type(key) is str and type(value) is bytes
            for key, value in source_scope_value[2].items()
        )
        else ()
    )
    try:
        observation_snapshot = _json_bytes(gate_observation)
    except Exception:
        observation_snapshot = None
    gate_projection_snapshot = observation_snapshot if type(gate_observation) is dict else None
    retained = _RetainedReferences(
        cuv2_module=cuv2_module,
        source_scope=source_scope,
        source_scope_exit_method=None,
        source_scope_value=source_scope_value,
        gate_module=gate_module,
        gate_context=gate_context,
        gate_observation=gate_observation,
        gate_context_registry=gate_context_registry,
        gate_context_entries=gate_entries,
        compiled_modules=compiled_modules,
        custody_modules=custody_modules,
        public_source_bytes=module_source_bytes,
        failure_evidence=failure_evidence if type(failure_evidence) is tuple else (),
        root_tty_reference=root_tty_reference,
        binding_snapshot=None,
        observation_snapshot=observation_snapshot,
        gate_projection_snapshot=gate_projection_snapshot,
        registry_snapshot=registry_ids,
        runtime_handle_registry=runtime_handle_registry,
        runtime_registry_snapshot=runtime_registry_snapshot,
        source_bytes_snapshot=source_bytes_snapshot,
        scope_raw_bytes_snapshot=scope_raw_bytes_snapshot,
    )
    with _LOCK:
        existing = next(
            (item for item in _RETAINED_CONTEXTS if item.source_scope is source_scope), None
        )
        if existing is not None:
            facts = _base_facts("SOURCE_SCOPE_ALREADY_ATTEMPTED", None, "scope_already_attempted")
            facts["root_tty_reference_held"] = existing.root_tty_reference is root_tty_reference
            return ReconciliationReceipt(facts=facts, retained=existing)
        _RETAINED_CONTEXTS.append(retained)

    try:
        _require(
            type(custody_modules) is tuple and len(custody_modules) == 2, "custody_modules_invalid"
        )
        _require(
            type(source_scope_value) is tuple
            and len(source_scope_value) == 3
            and source_scope_value[0] is custody_modules[0]
            and source_scope_value[1] is custody_modules[1]
            and type(source_scope_value[2]) is dict,
            "cuv2_scope_value_mismatch",
        )
        _require(root_tty_reference is not None, "root_tty_reference_required")
        _require(type(gate_observation) is dict, "gate_observation_invalid")
        _require(type(gate_context_registry) is list, "gate_context_registry_mismatch")
        _require(
            type(gate_context) is gate_module.__dict__.get("_Observation"),
            "gate_context_type_mismatch",
        )
        _require(
            type(gate_context_registry) is list
            and gate_module.__dict__.get("_ORPHANED_GATE_CONTEXTS") is gate_context_registry
            and len(gate_context_registry) == 1,
            "gate_context_registry_mismatch",
        )
        gate_entry = gate_context_registry[0]
        _require(
            type(gate_entry) is tuple
            and len(gate_entry) == 10
            and gate_entry[0] is gate_context
            and gate_entry[1] is reader_module
            and gate_entry[2] is supervisor_module
            and gate_entry[9] is supervisor_module.__dict__.get("_ORPHANED_RUNTIME_HANDLE_SETS"),
            "gate_context_entry_mismatch",
        )
        observation_doc, _retained_doc = _load_finite_pair(failure_evidence)
        generator, exit_method = _verify_scope(
            source_scope,
            cuv2_module,
            source_scope_value,
            module_source_bytes,
        )
        snapshot = _verify_source_bindings(
            cuv2_module=cuv2_module,
            gate_module=gate_module,
            reader_module=reader_module,
            supervisor_module=supervisor_module,
            worker_module=worker_module,
            source_bytes=module_source_bytes,
            custody_modules=custody_modules,
            scope_raw_bytes=source_scope_value[2],
        )
        gate_projection = _project_gate_context(
            gate_module=gate_module,
            gate_context=gate_context,
            gate_observation=gate_observation,
            gate_context_registry=gate_context_registry,
            reader_module=reader_module,
            supervisor_module=supervisor_module,
            gate_source=module_source_bytes["gate"],
        )
        _require(
            gate_observation.get("retained_context") is True,
            "gate_context_not_retained",
        )
        _require(
            gate_observation.get("status") == "LIFECYCLE_BLOCKED"
            and gate_observation.get("job_zero_after_exit") is False
            and gate_observation.get("production_acceptance") is False,
            "gate_failure_state_mismatch",
        )
        _require(
            gate_projection == _finite_gate_projection(observation_doc["gate_result"]),
            "gate_observation_evidence_mismatch",
        )
        retained = _RetainedReferences(
            cuv2_module=retained.cuv2_module,
            source_scope=retained.source_scope,
            source_scope_exit_method=exit_method,
            source_scope_value=retained.source_scope_value,
            gate_module=retained.gate_module,
            gate_context=retained.gate_context,
            gate_observation=retained.gate_observation,
            gate_context_registry=retained.gate_context_registry,
            gate_context_entries=retained.gate_context_entries,
            compiled_modules=retained.compiled_modules,
            custody_modules=retained.custody_modules,
            public_source_bytes=retained.public_source_bytes,
            failure_evidence=retained.failure_evidence,
            root_tty_reference=retained.root_tty_reference,
            binding_snapshot=snapshot,
            observation_snapshot=retained.observation_snapshot,
            gate_projection_snapshot=gate_projection,
            registry_snapshot=retained.registry_snapshot,
            runtime_handle_registry=retained.runtime_handle_registry,
            runtime_registry_snapshot=retained.runtime_registry_snapshot,
            source_bytes_snapshot=retained.source_bytes_snapshot,
            scope_raw_bytes_snapshot=retained.scope_raw_bytes_snapshot,
        )
        with _LOCK:
            for index, item in enumerate(_RETAINED_CONTEXTS):
                if item.source_scope is source_scope:
                    _RETAINED_CONTEXTS[index] = retained
                    break
    except Exception as exc:
        category, code = _function_facts(exc)
        facts = _base_facts("SOURCE_SCOPE_HELD_PREFLIGHT_REJECTED", category, code)
        facts["root_tty_reference_held"] = retained.root_tty_reference is root_tty_reference
        facts["gate_context_typed"] = _postcheck(
            lambda: type(gate_context) is gate_module.__dict__.get("_Observation")
        )
        return ReconciliationReceipt(facts=facts, retained=retained)

    facts = _base_facts("SOURCE_SCOPE_EXIT_UNCONFIRMED", None, None)
    facts["source_scope_exit_attempted"] = True
    facts["source_scope_exit_method_verified"] = True
    try:
        exit_result = exit_method(None, None, None)
    except Exception as exc:
        category, code = _function_facts(exc)
        facts["error_category"] = category
        facts["error_code"] = code
        facts["status"] = "SOURCE_SCOPE_POSTCHECK_UNCONFIRMED"
        facts["source_scope_generator_closed"] = _postcheck(
            lambda: inspect.getgeneratorstate(generator) == inspect.GEN_CLOSED
        )
        facts["source_lease_close_state"] = (
            "close_uncertain_after_scope_exception"
            if facts["source_scope_generator_closed"]
            else "scope_state_uncertain"
        )
        facts["gate_observation_unchanged"] = _postcheck(
            lambda: retained.observation_snapshot is not None
            and _json_bytes(gate_observation) == retained.observation_snapshot
        )
        facts["gate_context_typed"] = _postcheck(
            lambda: type(gate_context) is gate_module.__dict__.get("_Observation")
        )
        facts["gate_context_identity_unchanged"] = _postcheck(
            lambda: _gate_registry_identity_matches(
                gate_module,
                gate_context,
                gate_context_registry,
                reader_module,
                supervisor_module,
                retained.registry_snapshot,
                retained.gate_context_entries,
            )
        )
        facts["gate_context_projection_matches"] = _postcheck(
            lambda: _bindings_unchanged(snapshot)
            and _gate_projection_matches_snapshot(
                gate_module=gate_module,
                gate_context=gate_context,
                gate_observation=gate_observation,
                gate_context_registry=gate_context_registry,
                reader_module=reader_module,
                supervisor_module=supervisor_module,
                gate_source=module_source_bytes["gate"],
                expected=retained.gate_projection_snapshot,
            )
        )
        facts["gate_context_registry_unchanged"] = facts["gate_context_identity_unchanged"]
        facts["runtime_handle_registry_unchanged"] = _postcheck(
            lambda: retained.runtime_handle_registry
            is supervisor_module.__dict__.get("_ORPHANED_RUNTIME_HANDLE_SETS")
            and type(retained.runtime_handle_registry) is list
            and tuple(id(item) for item in retained.runtime_handle_registry)
            == retained.runtime_registry_snapshot
        )
        facts["compiled_module_bindings_unchanged"] = _postcheck(
            lambda: _bindings_unchanged(snapshot)
        )
        facts["held_source_byte_bindings_unchanged"] = _postcheck(
            lambda: type(module_source_bytes) is dict
            and len(module_source_bytes) == len(retained.source_bytes_snapshot)
            and all(
                module_source_bytes.get(key) is raw for key, raw in retained.source_bytes_snapshot
            )
        )
        facts["held_scope_raw_byte_bindings_unchanged"] = _postcheck(
            lambda: _scope_raw_byte_bindings_unchanged(
                source_scope_value[2], retained.scope_raw_bytes_snapshot
            )
        )
        facts["public_failure_evidence_unchanged"] = _postcheck(
            lambda: type(failure_evidence) is tuple
            and len(failure_evidence) == 2
            and failure_evidence == retained.failure_evidence
            and all(type(item) is bytes for item in failure_evidence)
        )
        facts["root_tty_reference_held"] = retained.root_tty_reference is root_tty_reference
        return ReconciliationReceipt(facts=facts, retained=retained)

    facts["normal_postverify_exit_returned"] = exit_result is False
    facts["source_scope_generator_closed"] = _postcheck(
        lambda: inspect.getgeneratorstate(generator) == inspect.GEN_CLOSED
    )
    facts["source_lease_close_state"] = (
        "closed_after_normal_postverify"
        if exit_result is False and facts["source_scope_generator_closed"]
        else "scope_state_uncertain"
    )
    facts["gate_observation_unchanged"] = _postcheck(
        lambda: retained.observation_snapshot is not None
        and _json_bytes(gate_observation) == retained.observation_snapshot
    )
    facts["gate_context_typed"] = _postcheck(
        lambda: type(gate_context) is gate_module.__dict__.get("_Observation")
    )
    facts["gate_context_identity_unchanged"] = _postcheck(
        lambda: _gate_registry_identity_matches(
            gate_module,
            gate_context,
            gate_context_registry,
            reader_module,
            supervisor_module,
            retained.registry_snapshot,
            retained.gate_context_entries,
        )
    )
    facts["gate_context_projection_matches"] = _postcheck(
        lambda: _bindings_unchanged(snapshot)
        and _gate_projection_matches_snapshot(
            gate_module=gate_module,
            gate_context=gate_context,
            gate_observation=gate_observation,
            gate_context_registry=gate_context_registry,
            reader_module=reader_module,
            supervisor_module=supervisor_module,
            gate_source=module_source_bytes["gate"],
            expected=retained.gate_projection_snapshot,
        )
    )
    facts["gate_context_registry_unchanged"] = facts["gate_context_identity_unchanged"]
    facts["runtime_handle_registry_unchanged"] = _postcheck(
        lambda: retained.runtime_handle_registry
        is supervisor_module.__dict__.get("_ORPHANED_RUNTIME_HANDLE_SETS")
        and type(retained.runtime_handle_registry) is list
        and tuple(id(item) for item in retained.runtime_handle_registry)
        == retained.runtime_registry_snapshot
    )
    facts["compiled_module_bindings_unchanged"] = _postcheck(lambda: _bindings_unchanged(snapshot))
    facts["held_source_byte_bindings_unchanged"] = _postcheck(
        lambda: type(module_source_bytes) is dict
        and len(module_source_bytes) == len(retained.source_bytes_snapshot)
        and all(module_source_bytes.get(key) is raw for key, raw in retained.source_bytes_snapshot)
    )
    facts["held_scope_raw_byte_bindings_unchanged"] = _postcheck(
        lambda: _scope_raw_byte_bindings_unchanged(
            source_scope_value[2], retained.scope_raw_bytes_snapshot
        )
    )
    facts["public_failure_evidence_unchanged"] = _postcheck(
        lambda: type(failure_evidence) is tuple
        and len(failure_evidence) == 2
        and failure_evidence == retained.failure_evidence
        and all(type(item) is bytes for item in failure_evidence)
    )
    facts["root_tty_reference_held"] = retained.root_tty_reference is root_tty_reference
    verified = all(
        facts[name] is True
        for name in (
            "normal_postverify_exit_returned",
            "source_scope_generator_closed",
            "gate_context_typed",
            "gate_context_projection_matches",
            "gate_context_identity_unchanged",
            "gate_observation_unchanged",
            "gate_context_registry_unchanged",
            "runtime_handle_registry_unchanged",
            "compiled_module_bindings_unchanged",
            "held_source_byte_bindings_unchanged",
            "held_scope_raw_byte_bindings_unchanged",
            "public_failure_evidence_unchanged",
            "root_tty_reference_held",
        )
    )
    facts["status"] = (
        "CUV2_SOURCE_SCOPE_NORMAL_EXIT_RETURNED"
        if verified
        else "SOURCE_SCOPE_POSTCHECK_UNCONFIRMED"
    )
    return ReconciliationReceipt(facts=facts, retained=retained)


def retained_context_count() -> int:
    """Return the number of retained reconciliation contexts; never clears them."""
    with _LOCK:
        return len(_RETAINED_CONTEXTS)
