"""Root-only one-shot normal close for the retained M01 R3 CU source scope.

This helper reads no files and performs no metadata, admission, provider,
account, subprocess, socket, or Win32 operation. Root must independently hold
and verify the complete 33-public/3-software source closure and the exact
module/function/global baseline before calling ``close_original_scope``.
Successful close does not grant host exit. Any uncertainty retains references.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
from pathlib import Path
import struct
import sys
import types


ROOT = Path("D:/source_code/backtrader")
CALLER_PATH = ROOT / ".codex-tmp/okx_m01_protected_rebind_r3_root_actual_candidate_20261009.py"
CALLER_SHA256 = "f80890de30021dc9751a439a247c0549afca7303fb13f8f8bb27019e6c193fd6"
CALLER_SIZE = 55093
CU_PATH = Path("D:/temp/iteration41-root-public-custody-v2.py")
CU_NAME = "_root_public_custody_v2"
MODULE_NAMES = (
    "_m01_readonly_monitor_v2",
    "_m01_readonly_monitor_v2.current_types",
    "_m01_readonly_monitor_v2.worker",
    "_certification",
    "_certification.m01_private_monitor_v2",
    "_m01_readonly_monitor_v2.job_supervisor",
    "_m01_readonly_monitor_v3",
    "_m01_readonly_monitor_v3.current_reader",
    "_root_okx_m01_metadata_helper_r2",
    "_root_public_custody_private",
    "_root_public_custody_cli",
)
REGISTRIES = (
    ("_root_okx_m01_metadata_helper_r2", "_ORPHANED_CONTEXTS", list),
    ("_m01_readonly_monitor_v3.current_reader", "_ADMISSIONS", dict),
    ("_m01_readonly_monitor_v3.current_reader", "_CONSUMED_ADMISSIONS", set),
    ("_m01_readonly_monitor_v3.current_reader", "_ORPHANED_SOURCE_ADMISSIONS", list),
    ("_m01_readonly_monitor_v3.current_reader", "_CURRENT_READ_EVIDENCE", dict),
    ("_m01_readonly_monitor_v3.current_reader", "_ROOT_HELPER_RETAINED_CONTEXTS", list),
    ("_m01_readonly_monitor_v2.job_supervisor", "_ORPHANED_RUNTIME_HANDLE_SETS", list),
    ("_m01_readonly_monitor_v2.current_types", "_ISSUED", dict),
    ("_m01_readonly_monitor_v2.current_types", "_CONSUMED", set),
)

_ATTEMPTED = []
_RETAINED = []


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _index(code: types.CodeType, result: dict[str, list[types.CodeType]]) -> None:
    result.setdefault(code.co_qualname, []).append(code)
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            _index(value, result)


_CODE_STRUCTURE_FIELDS = (
    "co_argcount",
    "co_posonlyargcount",
    "co_kwonlyargcount",
    "co_nlocals",
    "co_stacksize",
    "co_flags",
    "co_code",
    "co_consts",
    "co_names",
    "co_varnames",
    "co_filename",
    "co_name",
    "co_qualname",
    "co_firstlineno",
    "co_linetable",
    "co_lnotab",
    "co_exceptiontable",
    "co_freevars",
    "co_cellvars",
)


def _constant_structure_equal(left, right, active_pairs=None):
    """Compare code constants without Python's cross-type numeric equality."""
    if type(left) is not type(right):
        return False
    value_type = type(left)
    # CodeType must be dispatched before generic pair tracking: the code
    # comparator owns its recursion and must inspect every exposed field.
    if value_type is types.CodeType:
        return _code_structure_equal(left, right, active_pairs)
    if left is None or left is Ellipsis:
        return True
    if value_type in (bool, int, str, bytes):
        return left == right
    if value_type is float:
        return struct.pack("!d", left) == struct.pack("!d", right)
    if value_type is complex:
        return (
            struct.pack("!d", left.real) == struct.pack("!d", right.real)
            and struct.pack("!d", left.imag) == struct.pack("!d", right.imag)
        )
    if value_type not in (tuple, frozenset):
        return False

    if active_pairs is None:
        active_pairs = set()
    pair = (id(left), id(right))
    if pair in active_pairs:
        return True
    active_pairs.add(pair)
    try:
        if value_type is tuple:
            return len(left) == len(right) and all(
                _constant_structure_equal(a, b, active_pairs) for a, b in zip(left, right)
            )
        if len(left) != len(right):
            return False
        unmatched = list(right)
        for left_item in left:
            for index, right_item in enumerate(unmatched):
                if _constant_structure_equal(left_item, right_item, active_pairs):
                    del unmatched[index]
                    break
            else:
                return False
        return not unmatched
    finally:
        active_pairs.remove(pair)


def _code_structure_equal(left, right, active_pairs=None):
    """Compare every exposed CPython code field and typed nested constant."""
    if type(left) is not types.CodeType or type(right) is not types.CodeType:
        return False
    if active_pairs is None:
        active_pairs = set()
    pair = (id(left), id(right))
    if pair in active_pairs:
        return True
    active_pairs.add(pair)
    try:
        for field in _CODE_STRUCTURE_FIELDS:
            try:
                left_value = getattr(left, field)
                right_value = getattr(right, field)
            except AttributeError:
                return False
            if not _constant_structure_equal(left_value, right_value, active_pairs):
                return False
        return True
    finally:
        active_pairs.remove(pair)


def _function_is_source_bound(namespace: dict, name: str, expected_codes) -> bool:
    function = namespace.get(name)
    matches = expected_codes.get(name, ())
    return (
        type(function) is types.FunctionType
        and function.__globals__ is namespace
        and function.__module__ == namespace.get("__name__")
        and function.__qualname__ == name
        and len(matches) == 1
        and _code_structure_equal(function.__code__, matches[0])
    )


def _snapshot_result(result: dict):
    if type(result) is not dict:
        raise ValueError
    items = []
    for key, value in result.items():
        if type(key) is not str or type(value) not in (str, int, bool, type(None)):
            raise ValueError
        items.append((key, type(value), value))
    return tuple(sorted(items))


def _snapshot_state(state: dict):
    if type(state) is not dict or any(type(key) is not str for key in state):
        raise ValueError
    identities = tuple((key, id(value)) for key, value in state.items())
    primitives = tuple(
        sorted(
            (key, type(value), value)
            for key, value in state.items()
            if type(value) in (str, int, bool, type(None))
        )
    )
    return identities, primitives


def _registry_snapshot(modules: dict[str, types.ModuleType]):
    snapshot = []
    for module_name, attribute, expected_type in REGISTRIES:
        module = modules.get(module_name)
        if type(module) is not types.ModuleType:
            raise ValueError
        value = vars(module).get(attribute)
        if type(value) is not expected_type or len(value) != 0:
            raise ValueError
        snapshot.append((module, attribute, expected_type, value, id(value)))
    return tuple(snapshot)


def _registries_unchanged(snapshot) -> bool:
    return all(
        vars(module).get(attribute) is value
        and id(value) == identity
        and type(value) is expected_type
        and len(value) == 0
        for module, attribute, expected_type, value, identity in snapshot
    )


def _close_once(scope):
    if any(previous is scope for previous in _ATTEMPTED):
        return "already_attempted", False
    _ATTEMPTED.append(scope)
    try:
        outcome = scope.__exit__(None, None, None)
    except BaseException:
        return "close_call_failed", True
    if outcome is not False:
        return "close_result_unexpected", True
    try:
        generator = scope.gen
        if (
            type(generator) is not types.GeneratorType
            or inspect.getgeneratorstate(generator) != inspect.GEN_CLOSED
            or generator.gi_frame is not None
        ):
            return "close_state_unconfirmed", True
    except BaseException:
        return "close_state_unconfirmed", True
    return "closed", True


def _report(status: str, phase: str, reason: str, called: bool, retained: bool):
    return {
        "schema": "iteration41.okx.m01.retained_cu_normal_close.v1",
        "status": status,
        "phase": phase,
        "reason": reason,
        "normal_close_called": called,
        "normal_close_confirmed": status == "CU_SCOPE_NORMAL_CLOSE_CONFIRMED",
        "uncertainty_references_retained": retained,
        "host_exit_permitted": False,
        "metadata_helper_invoked": False,
        "metadata_rebound": False,
        "fresh_source_admission_released": False,
        "credentials_read": False,
        "provider_call": False,
        "account_call": False,
        "formal_m01_pass_count": 0,
    }


def close_original_scope(original_globals: dict):
    """Normally close the original CU scope once; never exit the host.

    The root caller's ``__file__`` may be absent in CPython's interactive
    namespace. Root must verify the current R4 full-source binding and the new
    review-scope postverify separately before calling this function.
    """
    phase = "root_binding"
    references = [original_globals]
    called = False
    try:
        if type(original_globals) is not dict:
            raise ValueError
        state = original_globals.get("ROOT_STATE")
        result = original_globals.get("ROOT_RESULT")
        references.extend((state, result))
        if type(state) is not dict or type(result) is not dict:
            raise ValueError
        raw = state.get("raw")
        if type(raw) is not dict:
            raise ValueError
        caller_raw = raw.get(str(CALLER_PATH))
        if type(caller_raw) is not bytes or len(caller_raw) != CALLER_SIZE or _sha(caller_raw) != CALLER_SHA256:
            raise ValueError
        expected_codes: dict[str, list[types.CodeType]] = {}
        _index(compile(caller_raw, str(CALLER_PATH), "exec", dont_inherit=True), expected_codes)
        for name in ("run", "bind_module", "verify_binding"):
            if not _function_is_source_bound(original_globals, name, expected_codes):
                raise ValueError
        if "__file__" in original_globals and original_globals["__file__"] != str(CALLER_PATH):
            raise ValueError
        if not (
            result.get("schema") == "iteration41.okx.m01.root_protected_metadata_rebind_r3.v1"
            and result.get("status") == "BLOCKED"
            and result.get("reason") == "root_source_binding_failed"
            and result.get("public_pin_count") == 33
            and result.get("software_pin_count") == 3
            and result.get("source_map_sha256_matches") is True
            and result.get("cu_source_code_globals_verified") is True
            and result.get("metadata_helper_invoked") is False
            and result.get("metadata_helper_invocations") == 0
            and result.get("metadata_backup_created") is False
            and result.get("metadata_source_map_updated") is False
            and result.get("metadata_deployment_updated") is False
            and result.get("metadata_readback_verified") is False
            and result.get("metadata_handles_released") is False
            and result.get("metadata_rebound") is False
            and result.get("metadata_write_or_close_uncertain") is False
            and result.get("fresh_source_admission_returned") is False
            and result.get("fresh_source_admission_map_matches") is False
            and result.get("fresh_source_admission_released") is False
            and result.get("credentials_read") is False
            and result.get("provider_call") is False
            and result.get("account_call") is False
            and result.get("c01_helper_invoked") is False
            and result.get("websocket_started") is False
            and result.get("formal_m01_pass_count") == 0
            and result.get("host_exit_permitted") is False
        ):
            raise ValueError
        if (
            state.get("admission") is not None
            or state.get("admission_private_binding") is not None
            or state.get("bindings_complete") is not False
            or state.get("registry_snapshot_complete") is not False
        ):
            raise ValueError

        modules = state.get("modules")
        if type(modules) is not tuple or len(modules) != len(MODULE_NAMES):
            raise ValueError
        module_map = {}
        for module, expected_name in zip(modules, MODULE_NAMES):
            if type(module) is not types.ModuleType or module.__name__ != expected_name:
                raise ValueError
            if sys.modules.get(expected_name) is not module:
                raise ValueError
            module_map[expected_name] = module
        v2 = module_map["_m01_readonly_monitor_v2"]
        current_types = module_map["_m01_readonly_monitor_v2.current_types"]
        worker = module_map["_m01_readonly_monitor_v2.worker"]
        contract = module_map["_certification.m01_private_monitor_v2"]
        supervisor = module_map["_m01_readonly_monitor_v2.job_supervisor"]
        v3 = module_map["_m01_readonly_monitor_v3"]
        reader = module_map["_m01_readonly_monitor_v3.current_reader"]
        if not (
            v2.current_types is current_types
            and v2.worker is worker
            and v2.job_supervisor is supervisor
            and module_map["_certification"].m01_private_monitor_v2 is contract
            and supervisor.worker is worker
            and supervisor.current_types is current_types
            and supervisor.contract is contract
            and v3.current_reader is reader
            and reader.current_types is current_types
            and reader.worker is worker
            and reader.job_supervisor is supervisor
        ):
            raise ValueError
        module_links_before = tuple(
            id(value)
            for value in (
                v2.current_types,
                v2.worker,
                v2.job_supervisor,
                module_map["_certification"].m01_private_monitor_v2,
                supervisor.worker,
                supervisor.current_types,
                supervisor.contract,
                v3.current_reader,
                reader.current_types,
                reader.worker,
                reader.job_supervisor,
            )
        )
        cu = state.get("cu")
        if (
            type(cu) is not types.ModuleType
            or cu.__name__ != CU_NAME
            or sys.modules.get(CU_NAME) is not cu
        ):
            raise ValueError
        references.extend((*modules, cu, raw))

        private = module_map["_root_public_custody_private"]
        api = vars(private).get("_API")
        api_type = vars(private).get("_Win32")
        if api is None or type(api) is not api_type or type(api_type) is not type:
            raise ValueError

        records = state.get("bindings")
        if type(records) is not tuple:
            raise ValueError
        cu_records = [record for record in records if type(record) is tuple and len(record) == 7 and record[0] is cu]
        if len(cu_records) != 1:
            raise ValueError
        cu_record = cu_records[0]
        if (
            cu_record[1] != CU_NAME
            or type(cu_record[2]) is not type(CU_PATH)
            or cu_record[2].resolve(strict=True) != CU_PATH.resolve(strict=True)
            or type(cu.__file__) is not str
            or Path(cu.__file__).resolve(strict=True) != CU_PATH.resolve(strict=True)
        ):
            raise ValueError
        verify = original_globals["verify_binding"]
        verify(cu_record)
        scope = state.get("scope")
        held = state.get("held")
        generator_entries = [
            item
            for item in cu_record[3]
            if type(item) is tuple and len(item) == 5 and item[0] is cu and item[1] == "held_public_sources"
        ]
        if len(generator_entries) != 1:
            raise ValueError
        generator_function = getattr(generator_entries[0][3], "__wrapped__", None)
        if (
            type(scope) is not contextlib._GeneratorContextManager
            or type(getattr(scope, "gen", None)) is not types.GeneratorType
            or inspect.getgeneratorstate(scope.gen) != inspect.GEN_SUSPENDED
            or type(generator_function) is not types.FunctionType
            or scope.gen.gi_code is not generator_function.__code__
            or scope.gen.gi_frame is None
            or scope.gen.gi_frame.f_globals is not cu.__dict__
            or scope.gen.gi_frame.f_code is not generator_function.__code__
            or type(held) is not tuple
            or len(held) != 3
            or held[0] is not private
            or held[1] is not module_map["_root_public_custody_cli"]
            or held[2] is not raw
        ):
            raise ValueError
        references.extend((scope, held, cu_record, api))

        registries = _registry_snapshot(module_map)
        references.append(registries)
        state_before = _snapshot_state(state)
        result_before = _snapshot_result(result)
        file_before = ("__file__" in original_globals, original_globals.get("__file__"))

        phase = "normal_close"
        close_status, called = _close_once(scope)
        if close_status != "closed":
            _RETAINED.append(tuple(references))
            return _report("BLOCKED", phase, close_status, called, True)

        phase = "normal_postverify"
        verify(cu_record)
        if not (
            scope.gen.gi_frame is None
            and inspect.getgeneratorstate(scope.gen) == inspect.GEN_CLOSED
            and vars(private).get("_API") is api
            and vars(private).get("_Win32") is api_type
            and type(api) is api_type
            and _registries_unchanged(registries)
            and all(sys.modules.get(name) is module for name, module in module_map.items())
            and tuple(
                id(value)
                for value in (
                    v2.current_types,
                    v2.worker,
                    v2.job_supervisor,
                    module_map["_certification"].m01_private_monitor_v2,
                    supervisor.worker,
                    supervisor.current_types,
                    supervisor.contract,
                    v3.current_reader,
                    reader.current_types,
                    reader.worker,
                    reader.job_supervisor,
                )
            )
            == module_links_before
            and _snapshot_state(state) == state_before
            and _snapshot_result(result) == result_before
            and ("__file__" in original_globals, original_globals.get("__file__")) == file_before
        ):
            raise ValueError
        report = _report("CU_SCOPE_NORMAL_CLOSE_CONFIRMED", "complete", "none", True, False)
        report["original_result_unchanged"] = True
        report["all_retained_registries_empty"] = True
        return report
    except BaseException:
        _RETAINED.append(tuple(references))
        return _report("BLOCKED", phase, "source_or_close_state_unconfirmed", called, True)

