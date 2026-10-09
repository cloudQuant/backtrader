"""Root-only focused source QA for the retained M01 CU close helper.

This driver runs five public source-fake tests: the three exact close-helper
tests and the two frozen R4 production-binder tests.  The R4 test executes
only the AST prefix before its ROOT_RESULT/actual-run tail, using synthetic
CU/API leaves.  This driver never calls close_original_scope or the metadata
caller.  It reads no software payload, protected metadata, credential, or
capture and makes no native, network, SDK, or child-process call.

Root must independently verify the original host's complete 33-public/3-
software held source/code/global state and the normal-close review-scope
preconditions before any later close action.  This QA result is not that
precondition and grants no host-exit permission.  This successor projects a
pytest internal error to bounded exception categories, pinned source labels,
function/line, phase, and profile failure counts.  At the existing exact
source-code rejection, it also records finite code metadata and equality
booleans against the pinned compiled candidates.  Code matching uses recursive
typed structural comparison of all exposed CPython code fields; marshaled bytes
are diagnostic only.  Nested code constants are compared by the code-object
comparator itself, with in-memory nested-bytecode and nested-constant tamper
checks.  It stores no exception text, frame locals, code constants, raw paths,
or raw output.
"""

from __future__ import annotations

import ast
import ctypes
import hashlib
import importlib.abc
import io
import json
import marshal
import os
from pathlib import Path
import stat
import struct
import sys
import types
import warnings
from contextlib import redirect_stderr, redirect_stdout


ROOT = Path("D:/source_code/backtrader")
EXPECTED_HEAD = "902d55daa397d601a947141b6a87eb1ca1df4d0a"
PRECHECK_JSON = ".codex-tmp/okx_m01_metadata_r3_root_external_precheck_20261009.json"
PRECHECK_JSON_PIN = (9141, "042ea15ed9a72fcaabb6a0679f8f06dd0ab5e8ef4ebf12ffc79337d70d6953fe")
PRECHECK_SOURCE = ".codex-tmp/okx_m01_metadata_r3_root_external_precheck_20261009.py"
PRECHECK_SOURCE_PIN = (4434, "b409b3165368aac8f88921155f79147038309273abf9fc8dd89c8e92a0a5beb5")

R3_CALLER = ".codex-tmp/okx_m01_protected_rebind_r3_root_actual_candidate_20261009.py"
R3_CALLER_PIN = (55093, "f80890de30021dc9751a439a247c0549afca7303fb13f8f8bb27019e6c193fd6")
CLOSE_HELPER = ".codex-tmp/okx_m01_r3_normal_cu_close_helper_20261009.py"
CLOSE_HELPER_PIN = (16328, "9169878e73d5fd261a311f1e574b8a38ac3417fd456efcccbb5d47d01edd3295")
CLOSE_TEST = "tests/unit/scripts/test_iteration41_okx_m01_r3_normal_cu_close_source_fake.py"
CLOSE_TEST_PIN = (2279, "099ae916b70b5e779e865b931b058fa650accf2b35aeae2df8a77d1d3908baee")
R4_CALLER = ".codex-tmp/okx_m01_protected_rebind_r4_root_actual_candidate_20261009.py"
R4_CALLER_PIN = (61618, "5efc4f8c02ed09c24cb319fdd2099e719b1772a3a4e0c162fa051edc9427c305")
R4_TEST = "tests/unit/scripts/test_iteration41_okx_m01_v3_protected_rebind_r4_source_fake.py"
R4_TEST_PIN = (10085, "b493fe80b895aa5a153ee8fd37e6c1636cf79029b836a4b9b27e585aa781e2f0")
R4_REVIEW = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-okx-m01-v3-protected-rebind-r4-repr-binding-review-correction-r1-2026-10-09/"
    "review.md"
)
R4_REVIEW_PIN = (3436, "ddb7674e8869312e414f4e1fe090f5b8ea226e00062d05566f83a933b0809e74")

QA_SITE = Path("D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages")
MAX_PUBLIC_BYTES = 2 * 1024 * 1024
RESULT = ROOT / ".codex-tmp/okx_m01_r3_normal_cu_close_root_source_qa_r9_20261009.json"
BASE_TEMP = ROOT / ".codex-tmp/pytest_okx_m01_r3_normal_cu_close_root_source_qa_r9_20261009"
LOG_FILE = ROOT / ".codex-tmp/okx_m01_r3_normal_cu_close_root_source_qa_r9_20261009.log"
DEPLOYMENT = "D:/temp/iteration41-okx-m01-v3-deployment"
SOFTWARE_FILES = (
    "C:/anaconda3/python.exe",
    "C:/anaconda3/python311.dll",
    "D:/temp/iteration41-root-public-custody-v2.py",
)

FIXED_INPUTS = {
    PRECHECK_JSON: PRECHECK_JSON_PIN,
    PRECHECK_SOURCE: PRECHECK_SOURCE_PIN,
    R3_CALLER: R3_CALLER_PIN,
    CLOSE_HELPER: CLOSE_HELPER_PIN,
    CLOSE_TEST: CLOSE_TEST_PIN,
    R4_CALLER: R4_CALLER_PIN,
    R4_TEST: R4_TEST_PIN,
    R4_REVIEW: R4_REVIEW_PIN,
}

_blocked_categories = []
_profile_failures = []
_helper_namespaces = {}
_r4_namespaces = {}
_test_modules = {}
_module_exec_active = set()
_profile_r4_run_seen = False
_r4_repeated_qualname_bucket_size = 0
_code_comparator_selfcheck_result = None
_profile_observation = {
    "source_label": "none",
    "event": "none",
    "function": "none",
    "line": 0,
}
_function_mismatches = []
_phase = "startup"
_preload_warning_count = 0
_MAX_INTERNAL_ERRORS = 3
_MAX_INTERNAL_SOURCE_LOCATIONS = 16
_MAX_INTERNAL_TRACEBACK_FRAMES = 512
_MAX_CODE_CANDIDATE_COMPARISONS = 16
_PROFILE_FAILURE_CATEGORIES = (
    "function_source_code",
    "module_global_binding",
    "nested_global_binding",
    "function_global_binding",
    "namespace_snapshot",
)
_EXCEPTION_CATEGORIES = (
    (AssertionError, "assertion_error"),
    (AttributeError, "attribute_error"),
    (ImportError, "import_error"),
    (IndexError, "index_error"),
    (KeyError, "key_error"),
    (PermissionError, "permission_error"),
    (OSError, "os_error"),
    (RuntimeError, "runtime_error"),
    (TypeError, "type_error"),
    (ValueError, "value_error"),
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _normal_path(value):
    text = os.fsdecode(value).replace("/", "\\").lower()
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(os.path.normpath(text))


def _safe_code_name(value):
    if (
        type(value) is str
        and 0 < len(value) <= 96
        and all(character.isascii() and (character.isalnum() or character in "_<>.") for character in value)
    ):
        return value
    return "other"


def _internal_source_label(filename):
    labels = (
        (Path(__file__).resolve(), "qa_harness"),
        (ROOT / CLOSE_HELPER, "close_helper"),
        (ROOT / R4_CALLER, "r4_caller"),
        (ROOT / CLOSE_TEST, "close_test"),
        (ROOT / R4_TEST, "r4_test"),
    )
    try:
        actual = _normal_path(filename)
    except (OSError, TypeError, ValueError):
        return None
    for path, label in labels:
        if actual == _normal_path(path):
            return label
    return None


def _loader_category(namespace):
    if type(namespace) is not dict:
        return "invalid_namespace"
    spec = namespace.get("__spec__")
    if spec is None:
        return "no_module_spec"
    loader = getattr(spec, "loader", None)
    if loader is None:
        return "no_loader"
    loader_type = type(loader)
    if (
        loader_type.__module__ == "_frozen_importlib_external"
        and loader_type.__name__ == "SourceFileLoader"
    ):
        return "source_file_loader"
    if (
        loader_type.__module__ == "_pytest.assertion.rewrite"
        and loader_type.__name__ == "AssertionRewritingHook"
    ):
        return "pytest_assertion_rewrite"
    return "other_loader"


def _code_candidate_comparison(actual, expected, ordinal):
    try:
        code_equal = bool(actual == expected)
    except BaseException:
        code_equal = False
    try:
        marshal_equal = marshal.dumps(actual) == marshal.dumps(expected)
    except BaseException:
        marshal_equal = False
    structure_equal = _code_structure_equal(actual, expected)
    return {
        "ordinal": ordinal,
        "expected_flags": int(expected.co_flags),
        "expected_first_line": int(expected.co_firstlineno),
        "identity_equal": actual is expected,
        "code_equal": code_equal,
        "structure_equal": structure_equal,
        "marshal_equal": marshal_equal,
        "bytecode_equal": actual.co_code == expected.co_code,
        "line_table_equal": actual.co_linetable == expected.co_linetable,
        "exception_table_equal": actual.co_exceptiontable == expected.co_exceptiontable,
        "flags_equal": actual.co_flags == expected.co_flags,
        "first_line_equal": actual.co_firstlineno == expected.co_firstlineno,
        "filename_equal": actual.co_filename == expected.co_filename,
        "qualname_equal": actual.co_qualname == expected.co_qualname,
    }


def _record_function_mismatch(namespace, function, code_by_qualname, source_path):
    if _function_mismatches:
        return
    code = function.__code__
    candidates = tuple(code_by_qualname.get(code.co_qualname, ()))
    _function_mismatches.append(
        {
            "source_label": _internal_source_label(source_path) or "unknown_source",
            "function": _safe_code_name(function.__name__),
            "qualname": _safe_code_name(code.co_qualname),
            "code_flags": int(code.co_flags),
            "first_line": int(code.co_firstlineno),
            "bytecode_size": len(code.co_code),
            "line_table_size": len(code.co_linetable),
            "exception_table_size": len(code.co_exceptiontable),
            "indexed_candidate_count": len(candidates),
            "candidate_comparisons": [
                _code_candidate_comparison(code, candidate, ordinal)
                for ordinal, candidate in enumerate(candidates[:_MAX_CODE_CANDIDATE_COMPARISONS])
            ],
            "candidate_comparisons_truncated": len(candidates) > _MAX_CODE_CANDIDATE_COMPARISONS,
            "loader_category": _loader_category(namespace),
            "pytest_assertion_mode": "plain",
            "optimization_level": int(sys.flags.optimize),
            "expected_compile_dont_inherit": True,
            "bytecode_cache_disabled": bool(sys.dont_write_bytecode),
        }
    )


def _profile_failure_counts():
    counts = {category: 0 for category in _PROFILE_FAILURE_CATEGORIES}
    counts["other"] = 0
    for category in _profile_failures:
        if category in counts:
            counts[category] += 1
        else:
            counts["other"] += 1
    return counts


def _internal_error_projection(excinfo):
    try:
        exception = excinfo.value
    except BaseException:
        exception = None
    exception_type = type(exception)
    exception_category = next(
        (label for expected, label in _EXCEPTION_CATEGORIES if exception_type is expected),
        "other",
    )
    locations = []
    traceback_node = getattr(exception, "__traceback__", None)
    frame_count = 0
    while (
        traceback_node is not None
        and frame_count < _MAX_INTERNAL_TRACEBACK_FRAMES
        and len(locations) < _MAX_INTERNAL_SOURCE_LOCATIONS
    ):
        frame_count += 1
        code = traceback_node.tb_frame.f_code
        source_label = _internal_source_label(code.co_filename)
        if source_label is not None:
            locations.append(
                {
                    "source_label": source_label,
                    "function": _safe_code_name(code.co_name),
                    "line": int(traceback_node.tb_lineno),
                }
            )
        traceback_node = traceback_node.tb_next
    return {
        "phase": _phase,
        "exception_category": exception_category,
        "source_locations": locations,
        "profile_failure_counts": _profile_failure_counts(),
        "last_profile_observation": dict(_profile_observation),
        "first_function_source_mismatch": _function_mismatches[0] if _function_mismatches else None,
    }


def _has_reparse_attribute(info):
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _check_public_path(relative):
    path = Path(relative)
    if path.is_absolute() or any(part in ("..", "") for part in path.parts):
        raise ValueError("unsafe_relative_path")
    cursor = ROOT
    root_info = cursor.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or _has_reparse_attribute(root_info):
        raise ValueError("root_identity_invalid")
    for index, part in enumerate(path.parts):
        cursor = cursor / part
        info = cursor.lstat()
        if _has_reparse_attribute(info):
            raise ValueError("reparse_path")
        if index < len(path.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError("non_directory_ancestor")
    if not stat.S_ISREG(info.st_mode) or info.st_size < 0 or info.st_size > MAX_PUBLIC_BYTES:
        raise ValueError("public_file_shape_invalid")
    return cursor, info.st_size


def _read_public(relative, expected=None):
    path, observed_size = _check_public_path(relative)
    if expected is not None and observed_size != expected[0]:
        raise ValueError("public_size_mismatch")
    extended = Path("\\\\?\\" + str(path.absolute()))
    with extended.open("rb") as stream:
        raw = stream.read(MAX_PUBLIC_BYTES + 1)
    if len(raw) != observed_size or len(raw) > MAX_PUBLIC_BYTES:
        raise ValueError("bounded_read_mismatch")
    digest = _sha(raw)
    if expected is not None and digest != expected[1]:
        raise ValueError("public_hash_mismatch")
    return raw


def _read_git_metadata(path, limit=512):
    info = path.lstat()
    if _has_reparse_attribute(info) or not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError("git_metadata_shape_invalid")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) != info.st_size or len(raw) > limit:
        raise ValueError("git_metadata_read_invalid")
    return raw.decode("ascii", errors="strict").strip()


def _git_head_and_branch():
    git_dir = ROOT / ".git"
    info = git_dir.lstat()
    if _has_reparse_attribute(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("git_directory_invalid")
    head = _read_git_metadata(git_dir / "HEAD")
    if head != "ref: refs/heads/dev":
        raise ValueError("branch_mismatch")
    refs = git_dir / "refs"
    heads = refs / "heads"
    branch_ref = heads / "dev"
    for directory in (refs, heads):
        directory_info = directory.lstat()
        if _has_reparse_attribute(directory_info) or not stat.S_ISDIR(directory_info.st_mode):
            raise ValueError("git_ref_directory_invalid")
    commit = _read_git_metadata(branch_ref, 128).lower()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise ValueError("head_shape_invalid")
    return "dev", commit


def _code_index(code, index):
    index.setdefault(code.co_qualname, []).append(code)
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            _code_index(value, index)


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


def _unique_code_match(code_index, code):
    if type(code) is not types.CodeType:
        return None
    matches = [
        candidate
        for candidate in code_index.get(code.co_qualname, ())
        if _code_structure_equal(candidate, code)
    ]
    return matches[0] if len(matches) == 1 else None


def _code_comparator_selfchecks():
    """Exercise structural matching and its fail-closed differences in memory."""
    filename = "<okx-m01-r8-code-comparator-selfcheck>"
    module_code = compile(
        "def text_sample():\n    return 'marker'\n"
        "def integer_sample():\n    return 1\n",
        filename,
        "exec",
        dont_inherit=True,
    )
    functions = [value for value in module_code.co_consts if type(value) is types.CodeType]
    if len(functions) != 2:
        raise ValueError("code_comparator_fixture_invalid")
    text_code = next(code for code in functions if code.co_name == "text_sample")
    integer_code = next(code for code in functions if code.co_name == "integer_sample")
    text_index = {}
    integer_index = {}
    _code_index(text_code, text_index)
    _code_index(integer_code, integer_index)

    nested_module_code = compile(
        "def outer_sample():\n"
        "    def inner_sample():\n"
        "        return 'nested-marker'\n"
        "    return inner_sample\n",
        filename,
        "exec",
        dont_inherit=True,
    )
    outer_code = next(
        value
        for value in nested_module_code.co_consts
        if type(value) is types.CodeType and value.co_name == "outer_sample"
    )
    nested_code = next(value for value in outer_code.co_consts if type(value) is types.CodeType)
    nested_index = {}
    _code_index(outer_code, nested_index)

    text_constants = tuple(
        bytearray(value, "utf-8").decode("utf-8") if type(value) is str else value
        for value in text_code.co_consts
    )
    semantic_clone = text_code.replace(co_consts=text_constants)
    semantic_clone_match = (
        semantic_clone is not text_code
        and _code_structure_equal(text_code, semantic_clone)
        and _unique_code_match(text_index, semantic_clone) is text_code
    )
    try:
        marshal_difference_observed = marshal.dumps(text_code) != marshal.dumps(semantic_clone)
    except BaseException:
        marshal_difference_observed = False

    changed_bytecode = text_code.replace(
        co_code=text_code.co_code[:-1]
        + bytes((text_code.co_code[-1] ^ 1,))
    )
    changed_text_constants = tuple(
        "changed-marker" if type(value) is str and value == "marker" else value
        for value in text_code.co_consts
    )
    changed_text = text_code.replace(co_consts=changed_text_constants)
    integer_constants = tuple(
        True if type(value) is int and value == 1 else value
        for value in integer_code.co_consts
    )
    typed_constant = integer_code.replace(co_consts=integer_constants)
    changed_flags = text_code.replace(co_flags=text_code.co_flags ^ 1)
    changed_nested_bytecode = nested_code.replace(
        co_code=nested_code.co_code[:-1]
        + bytes((nested_code.co_code[-1] ^ 1,))
    )
    nested_bytecode_parent = outer_code.replace(
        co_consts=tuple(
            changed_nested_bytecode if value is nested_code else value
            for value in outer_code.co_consts
        )
    )
    changed_nested_constants = tuple(
        "changed-nested-marker"
        if type(value) is str and value == "nested-marker"
        else value
        for value in nested_code.co_consts
    )
    changed_nested_code = nested_code.replace(co_consts=changed_nested_constants)
    nested_constant_parent = outer_code.replace(
        co_consts=tuple(
            changed_nested_code if value is nested_code else value
            for value in outer_code.co_consts
        )
    )

    bytecode_rejected = not _code_structure_equal(text_code, changed_bytecode)
    value_rejected = not _code_structure_equal(text_code, changed_text)
    typed_constant_rejected = (
        not _code_structure_equal(integer_code, typed_constant)
        and _unique_code_match(integer_index, typed_constant) is None
    )
    flags_rejected = not _code_structure_equal(text_code, changed_flags)
    nested_bytecode_rejected = (
        not _code_structure_equal(outer_code, nested_bytecode_parent)
        and _unique_code_match(nested_index, nested_bytecode_parent) is None
    )
    nested_constant_rejected = (
        not _code_structure_equal(outer_code, nested_constant_parent)
        and _unique_code_match(nested_index, nested_constant_parent) is None
    )

    positive_globals = {"__name__": "synthetic_r8"}
    positive_function = types.FunctionType(text_code, positive_globals, "text_sample")
    positive_globals["text_sample"] = positive_function
    positive_function_accepted = (
        _function_snapshot(positive_globals, text_index, filename).get("text_sample", (None,))[0]
        is positive_function
    )
    foreign_globals = {"__name__": "synthetic_r8"}
    foreign_function = types.FunctionType(text_code, foreign_globals, "text_sample")
    detached_namespace = {"__name__": "synthetic_r8", "text_sample": foreign_function}
    try:
        _function_snapshot(detached_namespace, text_index, filename)
    except ValueError as error:
        foreign_globals_rejected = str(error) == "no_source_functions"
    else:
        foreign_globals_rejected = False

    result = {
        "semantic_clone_accepted": bool(semantic_clone_match),
        "marshal_difference_observed": bool(marshal_difference_observed),
        "changed_bytecode_rejected": bool(bytecode_rejected),
        "changed_value_rejected": bool(value_rejected),
        "typed_bool_int_constant_rejected": bool(typed_constant_rejected),
        "changed_flags_rejected": bool(flags_rejected),
        "nested_bytecode_rejected": bool(nested_bytecode_rejected),
        "nested_constant_rejected": bool(nested_constant_rejected),
        "foreign_globals_rejected": bool(foreign_globals_rejected),
    }
    if not all(
        result[key]
        for key in (
            "semantic_clone_accepted",
            "changed_bytecode_rejected",
            "changed_value_rejected",
            "typed_bool_int_constant_rejected",
            "changed_flags_rejected",
            "nested_bytecode_rejected",
            "nested_constant_rejected",
            "foreign_globals_rejected",
        )
    ):
        raise ValueError("code_comparator_selfcheck_failed")
    return result


def _check_repeated_qualnames(code_index):
    repeated = {name: codes for name, codes in code_index.items() if len(codes) > 1}
    expected_name = "_expected_definitions.<locals>.<genexpr>"
    expected_bucket = repeated.get(expected_name, ())
    if len(expected_bucket) < 3:
        raise ValueError("r4_repeated_qualname_bucket_missing")
    for codes in repeated.values():
        for code in codes:
            if _unique_code_match(code_index, code) is not code:
                raise ValueError("ambiguous_repeated_qualname_code")
    return len(expected_bucket)


def _value_signature(value, seen, mutable_identity_only=False):
    value_type = type(value)
    if value is None or value_type in (str, int, bool, float, bytes):
        return ("value", value_type.__name__, value)
    if value_type in (types.FunctionType, types.BuiltinFunctionType):
        if value_type is types.FunctionType:
            return (
                "function",
                id(value),
                id(value.__code__),
                id(value.__globals__),
                _value_signature(value.__defaults__, seen),
                _value_signature(value.__kwdefaults__, seen),
                value.__module__,
                value.__qualname__,
            )
        return ("builtin_function", id(value))
    if value_type is types.ModuleType or isinstance(value, type):
        return ("identity", value_type.__name__, id(value))
    if value_type in (dict, list, set, tuple, frozenset):
        if mutable_identity_only and value_type in (dict, list, set):
            return ("mutable_identity", value_type.__name__, id(value))
        identity = id(value)
        if identity in seen:
            return ("cycle", value_type.__name__, identity)
        seen.add(identity)
        if value_type is dict:
            items = tuple(
                sorted(
                    ((str(key), _value_signature(item, seen)) for key, item in value.items()),
                    key=lambda pair: pair[0],
                )
            )
        elif value_type in (set, frozenset):
            items = tuple(sorted((_value_signature(item, seen) for item in value), key=repr))
        else:
            items = tuple(_value_signature(item, seen) for item in value)
        seen.remove(identity)
        return (value_type.__name__, identity, items)
    return ("identity", value_type.__name__, id(value))


def _namespace_snapshot(namespace, mutable_identity_names=()):
    if type(namespace) is not dict:
        raise ValueError("namespace_shape_invalid")
    output = []
    for name in sorted(key for key in namespace if key != "__builtins__"):
        value = namespace[name]
        output.append(
            (
                name,
                _value_signature(value, set(), mutable_identity_only=name in mutable_identity_names),
            )
        )
    return tuple(output)


def _function_snapshot(namespace, code_by_qualname, source_path):
    snapshot = {}
    for name, function in tuple(namespace.items()):
        if type(function) is not types.FunctionType or function.__globals__ is not namespace:
            continue
        if function.__module__ != namespace.get("__name__"):
            raise ValueError("function_module_mismatch")
        if function.__code__.co_filename != source_path:
            continue
        if _unique_code_match(code_by_qualname, function.__code__) is None:
            _record_function_mismatch(namespace, function, code_by_qualname, source_path)
            raise ValueError("function_source_mismatch")
        snapshot[name] = (
            function,
            function.__code__,
            function.__globals__,
            function.__defaults__,
            function.__kwdefaults__,
            function.__annotations__,
            _value_signature(function.__defaults__, set()),
            _value_signature(function.__kwdefaults__, set()),
            _value_signature(function.__annotations__, set()),
            function.__module__,
            function.__qualname__,
        )
    if not snapshot:
        raise ValueError("no_source_functions")
    return snapshot


def _functions_unchanged(namespace, snapshot):
    return all(
        namespace.get(name) is function
        and function.__code__ is code
        and function.__globals__ is globals_dict is namespace
        and function.__defaults__ is defaults
        and function.__kwdefaults__ is kwdefaults
        and function.__annotations__ is annotations
        and _value_signature(function.__defaults__, set()) == defaults_signature
        and _value_signature(function.__kwdefaults__, set()) == kwdefaults_signature
        and _value_signature(function.__annotations__, set()) == annotations_signature
        and function.__module__ == module_name
        and function.__qualname__ == qualname
        for name, (
            function,
            code,
            globals_dict,
            defaults,
            kwdefaults,
            annotations,
            defaults_signature,
            kwdefaults_signature,
            annotations_signature,
            module_name,
            qualname,
        ) in snapshot.items()
    )


def _preload_test_runtime():
    global _preload_warning_count
    if os.environ.get("PYTEST_ADDOPTS") or os.environ.get("PYTEST_PLUGINS"):
        raise ValueError("pytest_environment_not_clean")
    sys.path.insert(0, str(QA_SITE))
    sys.path.insert(0, str(ROOT))
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    sys.dont_write_bytecode = True
    with warnings.catch_warnings(record=True) as warning_records:
        warnings.simplefilter("always")
        import pytest
        import colorama
        from _pytest.config import get_config

        config = get_config(["-c", "NUL"])
        config._ensure_unconfigure()

    if not str(Path(pytest.__file__).resolve()).lower().startswith(str(QA_SITE).lower()):
        raise ValueError("pytest_origin_invalid")
    if not str(Path(colorama.__file__).resolve()).lower().startswith(str(QA_SITE).lower()):
        raise ValueError("colorama_origin_invalid")
    _preload_warning_count = len(warning_records)
    return pytest


def _deny_sdk_imports():
    class DenySdk(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            root = fullname.split(".", 1)[0].lower()
            if root == "bt_api_py" or root.startswith("bt_api_") or root in {"okx", "ccxt", "binance"}:
                _blocked_categories.append("sdk_import")
                raise ImportError("sdk_import_denied")
            return None

    sys.meta_path.insert(0, DenySdk())


def _audit(event, args):
    category = None
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = _normal_path(args[0])
        leaf = path.rsplit("\\", 1)[-1]
        if path.startswith(_normal_path(DEPLOYMENT)) or leaf in {".env", "config.yaml", "secrets.yaml"}:
            category = "private_path"
        elif any(path == _normal_path(item) for item in SOFTWARE_FILES):
            category = "software_payload"
        else:
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else None
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            writing = isinstance(mode, str) and any(flag in mode for flag in "wax+")
            if type(flags) is int:
                writing = writing or bool(flags & write_flags)
            elif type(mode) is int:
                # Older audit shapes may expose open flags in the second slot.
                writing = writing or bool(mode & write_flags)
            if writing:
                allowed = (
                    path in {_normal_path(RESULT), _normal_path(LOG_FILE)}
                    or path.startswith(_normal_path(BASE_TEMP) + "\\")
                )
                if not allowed:
                    category = "write_outside_allowlist"
    elif event.startswith("socket."):
        category = "network"
    elif event in {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.fork",
        "os.forkpty",
        "os.spawn",
        "os.startfile",
        "_winapi.CreateProcess",
    }:
        category = "process"
    elif event in {"ctypes.dlopen", "ctypes.dlsym"}:
        category = "native_library"
    elif event in {"os.mkdir", "os.remove", "os.rmdir"} and args:
        path = _normal_path(args[0])
        allowed = path == _normal_path(BASE_TEMP) or path.startswith(_normal_path(BASE_TEMP) + "\\")
        if not allowed:
            category = "write_outside_allowlist"
    elif event in {"os.rename", "os.replace"} and len(args) >= 2:
        source = _normal_path(args[0])
        destination = _normal_path(args[1])
        allowed_source = source == _normal_path(BASE_TEMP) or source.startswith(_normal_path(BASE_TEMP) + "\\")
        allowed_destination = (
            destination == _normal_path(BASE_TEMP)
            or destination.startswith(_normal_path(BASE_TEMP) + "\\")
        )
        if not (allowed_source and allowed_destination):
            category = "write_outside_allowlist"
    elif event == "import" and args and isinstance(args[0], str):
        root = args[0].split(".", 1)[0].lower()
        if root == "bt_api_py" or root.startswith("bt_api_") or root in {"okx", "ccxt", "binance"}:
            category = "sdk_import"
    if category is not None:
        _blocked_categories.append(category)
        raise PermissionError(category)


def _audit_selfchecks():
    probes = (
        ("process", lambda: sys.audit("subprocess.Popen", "synthetic", (), None, {})),
        ("network", lambda: sys.audit("socket.connect", None, None)),
        ("native_library", lambda: sys.audit("ctypes.dlopen", "synthetic", None)),
        (
            "private_path",
            lambda: sys.audit("open", DEPLOYMENT + "/deployment.json", "rb", 0),
        ),
        ("software_payload", lambda: sys.audit("open", SOFTWARE_FILES[0], "rb", 0)),
        (
            "write_outside_allowlist",
            lambda: sys.audit(
                "open",
                str(ROOT / R3_CALLER),
                0o200,
                os.O_WRONLY | os.O_CREAT,
            ),
        ),
    )
    completed = []
    for expected, probe in probes:
        before = len(_blocked_categories)
        try:
            probe()
        except PermissionError:
            pass
        if len(_blocked_categories) != before + 1 or _blocked_categories[-1] != expected:
            raise ValueError("guard_selfcheck_failed")
        completed.append(expected)
    before = len(_blocked_categories)
    try:
        importlib.import_module("bt_api_py")
    except (ImportError, PermissionError):
        pass
    sdk_events = _blocked_categories[before:]
    if not sdk_events or any(value != "sdk_import" for value in sdk_events):
        raise ValueError("sdk_import_guard_selfcheck_failed")
    completed.append("sdk_import")
    return len(completed)


def _make_r4_prefix_index(raw):
    tree = ast.parse(raw.decode("utf-8", errors="strict"), filename=str(ROOT / R4_CALLER))
    body = []
    stopped = False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ROOT_RESULT" for target in node.targets
        ):
            stopped = True
            break
        body.append(node)
    if not stopped or not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run" for node in body):
        raise ValueError("r4_actual_tail_boundary_missing")
    module = ast.Module(body=body, type_ignores=[])
    code = compile(module, str(ROOT / R4_CALLER), "exec")
    index = {}
    _code_index(code, index)
    return index


def _profile(frame, event, arg):
    global _profile_r4_run_seen, _profile_observation
    filename = frame.f_code.co_filename
    if filename not in (str(ROOT / CLOSE_HELPER), str(ROOT / R4_CALLER)):
        return _profile
    _profile_observation = {
        "source_label": "close_helper" if filename == str(ROOT / CLOSE_HELPER) else "r4_caller",
        "event": event if event in {"call", "return", "exception", "c_call", "c_return", "c_exception"} else "other",
        "function": _safe_code_name(frame.f_code.co_name),
        "line": int(frame.f_lineno),
    }
    namespace = frame.f_globals
    if filename == str(ROOT / CLOSE_HELPER):
        code_index = _expected_close_codes
        target = _helper_namespaces
        mutable_names = ("_ATTEMPTED", "_RETAINED")
    else:
        code_index = _expected_r4_codes
        target = _r4_namespaces
        mutable_names = ()
    if _unique_code_match(code_index, frame.f_code) is None:
        _profile_failures.append("function_source_code")
        return _profile

    frame_key = (filename, id(namespace))
    if event == "return" and frame.f_code.co_name == "<module>":
        expected_name = (
            "_m01_cu_close_source_fake"
            if filename == str(ROOT / CLOSE_HELPER)
            else "_m01_rebind_r4_test_caller"
        )
        if (
            type(namespace) is not dict
            or namespace.get("__file__") != filename
            or namespace.get("__name__") != expected_name
        ):
            _profile_failures.append("module_global_binding")
        _module_exec_active.discard(frame_key)
        return _profile
    if event != "call":
        return _profile

    # `exec` of an exact held source prefix can emit a module-frame event.
    # Class bodies and module-level comprehensions run before their names are
    # installed, so admit only exact compiled code under this active frame.
    if frame.f_code.co_name == "<module>":
        expected_name = (
            "_m01_cu_close_source_fake"
            if filename == str(ROOT / CLOSE_HELPER)
            else "_m01_rebind_r4_test_caller"
        )
        if (
            type(namespace) is not dict
            or namespace.get("__file__") != filename
            or namespace.get("__name__") != expected_name
        ):
            _profile_failures.append("module_global_binding")
        else:
            _module_exec_active.add(frame_key)
        return _profile

    function = None
    if frame.f_code.co_qualname == frame.f_code.co_name:
        candidate = namespace.get(frame.f_code.co_name)
        if (
            type(candidate) is types.FunctionType
            and candidate.__code__ is frame.f_code
            and candidate.__globals__ is namespace
        ):
            function = candidate
        elif candidate is None and frame_key in _module_exec_active:
            # Exact class-body code and top-level comprehensions execute while
            # the verified module frame is building the namespace.
            return _profile
    elif "<locals>" not in frame.f_code.co_qualname:
        owner_name, separator, member_name = frame.f_code.co_qualname.rpartition(".")
        owner = namespace.get(owner_name) if separator else None
        if type(owner) is type:
            descriptor = vars(owner).get(member_name)
            if type(descriptor) in (staticmethod, classmethod):
                candidates = (descriptor.__func__,)
            elif type(descriptor) is property:
                candidates = tuple(
                    item
                    for item in (descriptor.fget, descriptor.fset, descriptor.fdel)
                    if item is not None
                )
            elif type(descriptor) is types.FunctionType:
                candidates = (descriptor,)
            else:
                candidates = ()
            function = next(
                (
                    candidate
                    for candidate in candidates
                    if type(candidate) is types.FunctionType
                    and candidate.__code__ is frame.f_code
                    and candidate.__globals__ is namespace
                ),
                None,
            )
    else:
        # Local functions, comprehensions and generators have no stable module
        # attribute. Require their exact compiled code and the already-bound
        # enclosing module globals.
        if not any(held_namespace is namespace for held_namespace, *_ in target.values()):
            _profile_failures.append("nested_global_binding")
            return _profile

    if "<locals>" not in frame.f_code.co_qualname and function is None:
        _profile_failures.append("function_global_binding")
        return _profile
    if filename == str(ROOT / R4_CALLER) and frame.f_code.co_qualname == "run":
        _profile_r4_run_seen = True
    key = id(namespace)
    if key not in target:
        try:
            funcs = _function_snapshot(namespace, code_index, filename)
            globals_snapshot = _namespace_snapshot(namespace, mutable_names)
            target[key] = (namespace, funcs, globals_snapshot, mutable_names)
        except BaseException:
            _profile_failures.append("namespace_snapshot")
    return _profile


def _verify_profile_snapshots():
    namespaces = 0
    for target in (_helper_namespaces, _r4_namespaces):
        for namespace, functions, globals_before, mutable_names in target.values():
            namespaces += 1
            if not _functions_unchanged(namespace, functions):
                return False, namespaces
            if _namespace_snapshot(namespace, mutable_names) != globals_before:
                return False, namespaces
    complete = (
        len(_helper_namespaces) >= 2
        and len(_r4_namespaces) >= 1
        and not _profile_failures
        and not _module_exec_active
        and not _profile_r4_run_seen
    )
    return complete, namespaces


def main():
    global _phase, _expected_close_codes, _expected_r4_codes, _r4_repeated_qualname_bucket_size
    global _code_comparator_selfcheck_result
    if sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 11, 5):
        raise ValueError("interpreter_mismatch")
    if not sys.flags.isolated or not sys.flags.no_site:
        raise ValueError("isolated_interpreter_required")
    if Path.cwd().resolve() != ROOT.resolve():
        raise ValueError("workspace_cwd_mismatch")
    branch, head = _git_head_and_branch()
    if branch != "dev" or head != EXPECTED_HEAD:
        raise ValueError("checkout_head_mismatch")
    if RESULT.exists() or BASE_TEMP.exists() or LOG_FILE.exists():
        raise ValueError("fresh_output_required")

    _phase = "trusted_test_preload"
    pytest = _preload_test_runtime()
    if any(
        name == "bt_api_py"
        or name.startswith("bt_api_py.")
        or name.startswith("bt_api_")
        or name.split(".", 1)[0].lower() in {"okx", "ccxt", "binance"}
        for name in sys.modules
    ):
        raise ValueError("sdk_preloaded")
    _deny_sdk_imports()

    _phase = "public_input_pins"
    raw_inputs = {}
    pins = {}
    for relative, expected in FIXED_INPUTS.items():
        raw = _read_public(relative, expected)
        raw_inputs[relative] = raw
        pins[relative] = {"path": relative, "bytes": len(raw), "sha256": _sha(raw)}

    precheck = json.loads(raw_inputs[PRECHECK_JSON].decode("utf-8", errors="strict"))
    source_rows = precheck.get("public_source_rows")
    caller_pin = precheck.get("caller_pin")
    if (
        type(source_rows) is not list
        or len(source_rows) != 32
        or precheck.get("public_pin_count") != 33
        or precheck.get("head") != "934e30b55c078a42517c1c758a45eacb09a2b740"
        or type(caller_pin) is not dict
        or caller_pin.get("bytes") != R3_CALLER_PIN[0]
        or caller_pin.get("sha256") != R3_CALLER_PIN[1]
        or precheck.get("software_pin_count") != 3
    ):
        raise ValueError("public_closure_manifest_invalid")
    for row in source_rows:
        if type(row) is not dict or type(row.get("path")) is not str:
            raise ValueError("public_row_invalid")
        relative = row["path"]
        expected = (row.get("bytes"), row.get("sha256"))
        if type(expected[0]) is not int or type(expected[1]) is not str:
            raise ValueError("public_row_pin_invalid")
        if relative in pins:
            raise ValueError("duplicate_public_input")
        raw = _read_public(relative, expected)
        raw_inputs[relative] = raw
        pins[relative] = {"path": relative, "bytes": len(raw), "sha256": _sha(raw)}
    caller_raw = _read_public(R3_CALLER, R3_CALLER_PIN)
    raw_inputs[R3_CALLER] = caller_raw
    pins[R3_CALLER] = {"path": R3_CALLER, "bytes": len(caller_raw), "sha256": _sha(caller_raw)}
    if len(pins) != 40:
        raise ValueError("public_input_count_mismatch")

    software_rows = precheck.get("software_rows")
    if type(software_rows) is not list or len(software_rows) != 3:
        raise ValueError("software_descriptor_count_invalid")
    expected_software = {
        "C:/anaconda3/python.exe": (92160, "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642"),
        "C:/anaconda3/python311.dll": (5991424, "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00"),
        "D:\\temp\\iteration41-root-public-custody-v2.py": (2344, "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"),
    }
    if {
        row.get("path"): (row.get("bytes"), row.get("sha256"))
        for row in software_rows
        if type(row) is dict
    } != expected_software:
        raise ValueError("software_descriptors_mismatch")

    close_code = compile(raw_inputs[CLOSE_HELPER], str(ROOT / CLOSE_HELPER), "exec", dont_inherit=True)
    _expected_close_codes = {}
    _code_index(close_code, _expected_close_codes)
    _expected_r4_codes = _make_r4_prefix_index(raw_inputs[R4_CALLER])
    _r4_repeated_qualname_bucket_size = _check_repeated_qualnames(_expected_r4_codes)
    close_test_code = compile(raw_inputs[CLOSE_TEST], str(ROOT / CLOSE_TEST), "exec", dont_inherit=True)
    r4_test_code = compile(raw_inputs[R4_TEST], str(ROOT / R4_TEST), "exec", dont_inherit=True)
    test_source_codes = {CLOSE_TEST: {}, R4_TEST: {}}
    _code_index(close_test_code, test_source_codes[CLOSE_TEST])
    _code_index(r4_test_code, test_source_codes[R4_TEST])
    comparator_selfchecks = _code_comparator_selfchecks()
    _code_comparator_selfcheck_result = comparator_selfchecks

    _phase = "candidate_guards"
    sys.addaudithook(_audit)
    selfchecks = _audit_selfchecks()
    guard_baseline = len(_blocked_categories)

    module_names = (
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
        "_root_public_custody_v2",
    )
    modules_before = {name: sys.modules.get(name) for name in module_names}

    class Recorder:
        def __init__(self):
            self.items = []
            self.outcomes = []
            self.warnings = 0
            self.r4_module_postverify = 0
            self.internal_error_count = 0
            self.internal_errors = []

        def pytest_internalerror(self, excrepr, excinfo):
            # Do not inspect or retain pytest's rendered exception, text, or
            # frame locals.  Project only bounded labels and finite categories.
            self.internal_error_count = min(self.internal_error_count + 1, 100)
            if len(self.internal_errors) < _MAX_INTERNAL_ERRORS:
                self.internal_errors.append(_internal_error_projection(excinfo))

        def pytest_collection_finish(self, session):
            self.items = list(session.items)
            if len(self.items) != 5:
                raise AssertionError("unexpected_test_count")
            allowed = {
                "test_normal_exit_is_one_shot_and_confirms_closed_generator",
                "test_close_exception_is_finite_and_cannot_be_retried",
                "test_bad_root_namespace_does_not_attempt_any_scope_close",
                "test_exact_production_binder_accepts_full_public_module_closure",
                "test_generated_repr_code_is_bound_to_dataclass_fields_and_wrapper",
            }
            if {item.name for item in self.items} != allowed:
                raise AssertionError("unexpected_test_selection")
            modules = {item.module.__file__: item.module for item in self.items}
            expected_modules = {
                str(ROOT / CLOSE_TEST): (CLOSE_TEST, raw_inputs[CLOSE_TEST]),
                str(ROOT / R4_TEST): (R4_TEST, raw_inputs[R4_TEST]),
            }
            for source_path, module in modules.items():
                if source_path not in expected_modules:
                    raise AssertionError("test_source_origin_mismatch")
                relative, raw = expected_modules[source_path]
                if Path(module.__file__).resolve() != (ROOT / relative).resolve():
                    raise AssertionError("test_module_origin_mismatch")
                if (
                    module.__spec__ is None
                    or Path(module.__spec__.origin).resolve() != (ROOT / relative).resolve()
                ):
                    raise AssertionError("test_spec_origin_mismatch")
                if sys.modules.get(module.__name__) is not module:
                    raise AssertionError("test_module_link_mismatch")
                expected_codes = test_source_codes[relative]
                snapshot = _function_snapshot(vars(module), expected_codes, source_path)
                globals_snapshot = _namespace_snapshot(vars(module))
                _test_modules[relative] = (module, snapshot, globals_snapshot)
            if set(_test_modules) != {CLOSE_TEST, R4_TEST}:
                raise AssertionError("test_module_set_mismatch")
            # Exercise the exact test loader under guards to observe the close
            # helper's loaded module globals before any test body runs.
            helper_test = _test_modules[CLOSE_TEST][0]
            probe_namespace = helper_test._load_helper()
            helper_functions = _function_snapshot(
                probe_namespace, _expected_close_codes, str(ROOT / CLOSE_HELPER)
            )
            _helper_namespaces[id(probe_namespace)] = (
                probe_namespace,
                helper_functions,
                _namespace_snapshot(probe_namespace, ("_ATTEMPTED", "_RETAINED")),
                ("_ATTEMPTED", "_RETAINED"),
            )

        def pytest_runtest_logreport(self, report):
            if report.when == "call" or report.failed:
                self.outcomes.append((report.nodeid, report.when, report.outcome))

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_call(self, item):
            outcome = yield
            if (
                item.name == "test_exact_production_binder_accepts_full_public_module_closure"
                and outcome.excinfo is None
            ):
                composition = item.funcargs.get("production_loaded_composition")
                if composition is None:
                    raise AssertionError("r4_composition_missing_after_test")
                gate, loaded, raw_by_module, paths = composition
                order = (
                    "_root_public_custody_v2",
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
                records = [
                    gate.bind_module(loaded[name], raw_by_module[name], paths[name], name)
                    for name in order
                ]
                for binding in records:
                    gate.verify_binding(binding)
                self.r4_module_postverify += 1

        def pytest_warning_recorded(self, warning_message, when, nodeid, location):
            self.warnings += 1

    recorder = Recorder()
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    python_warnings = []
    _phase = "focused_fake_tests"
    sys.setprofile(_profile)
    try:
        with warnings.catch_warnings(record=True) as warning_records:
            warnings.simplefilter("always")
            with redirect_stdout(captured_out), redirect_stderr(captured_err):
                pytest_exit = int(
                    pytest.main(
                        [
                            str(ROOT / CLOSE_TEST),
                            str(ROOT / R4_TEST),
                            "-q",
                            "-c",
                            "NUL",
                            "--confcutdir=" + str(ROOT / "tests/unit/scripts"),
                            "--basetemp=" + str(BASE_TEMP),
                            "--log-file=" + str(LOG_FILE),
                            "--log-file-mode=w",
                            "--log-file-level=WARNING",
                            "--capture=sys",
                            "--noconftest",
                            "--assert=plain",
                            "-W",
                            "error",
                            "-p",
                            "no:cacheprovider",
                            "-p",
                            "no:xdist",
                            "-p",
                            "no:asyncio",
                            "--tb=short",
                        ],
                        plugins=[recorder],
                    )
                )
            python_warnings = list(warning_records)
    finally:
        sys.setprofile(None)

    _phase = "post_run_verification"
    inputs_unchanged = True
    for relative, old in pins.items():
        now = _read_public(relative, (old["bytes"], old["sha256"]))
        if len(now) != old["bytes"] or _sha(now) != old["sha256"]:
            inputs_unchanged = False

    tests_unchanged = True
    for relative, (module, function_snapshot, globals_snapshot) in _test_modules.items():
        source_path = str(ROOT / relative)
        tests_unchanged = tests_unchanged and (
            Path(module.__file__).resolve() == (ROOT / relative).resolve()
            and sys.modules.get(module.__name__) is module
            and _functions_unchanged(vars(module), function_snapshot)
            and _namespace_snapshot(vars(module)) == globals_snapshot
            and all(
                fn.__code__.co_filename == source_path
                for fn, *_ in function_snapshot.values()
            )
        )
    profile_unchanged, profile_namespace_count = _verify_profile_snapshots()
    modules_unchanged = all(sys.modules.get(name) is module for name, module in modules_before.items())
    outcomes = [item for item in recorder.outcomes if item[1] == "call" and item[2] == "passed"]
    candidate_blocked = _blocked_categories[guard_baseline:]
    accepted = (
        pytest_exit == 0
        and len(recorder.items) == 5
        and len(outcomes) == 5
        and _preload_warning_count == 0
        and recorder.warnings == 0
        and len(python_warnings) == 0
        and recorder.r4_module_postverify == 1
        and inputs_unchanged
        and tests_unchanged
        and profile_unchanged
        and _r4_repeated_qualname_bucket_size >= 3
        and LOG_FILE.is_file()
        and modules_unchanged
        and recorder.internal_error_count == 0
        and all(
            comparator_selfchecks[key]
            for key in (
                "semantic_clone_accepted",
                "changed_bytecode_rejected",
                "changed_value_rejected",
                "typed_bool_int_constant_rejected",
                "changed_flags_rejected",
                "nested_bytecode_rejected",
                "nested_constant_rejected",
                "foreign_globals_rejected",
            )
        )
        and not candidate_blocked
    )
    return {
        "schema": "iteration41.okx.m01.retained_cu_close_root_source_qa.v9",
        "status": "SOURCE_FAKE_QA_ONLY" if accepted else "HOLD",
        "checkout_head": head,
        "branch": branch,
        "expected_checkout_head": EXPECTED_HEAD,
        "pytest_exit": pytest_exit,
        "collected": len(recorder.items),
        "passed": len(outcomes),
        "warning_count": recorder.warnings,
        "python_warning_count": len(python_warnings),
        "preload_warning_count": _preload_warning_count,
        "guard_selfchecks": selfchecks,
        "code_comparator_selfchecks": comparator_selfchecks,
        "candidate_blocked_categories": candidate_blocked,
        "public_closure_count": 33,
        "input_count": len(pins),
        "inputs_unchanged": inputs_unchanged,
        "test_source_origins_and_bindings_unchanged": tests_unchanged,
        "helper_and_r4_code_global_bindings_unchanged": profile_unchanged,
        "profile_namespace_count": profile_namespace_count,
        "profile_failure_counts": _profile_failure_counts(),
        "last_profile_observation": dict(_profile_observation),
        "r4_repeated_qualname_bucket_size": _r4_repeated_qualname_bucket_size,
        "source_module_exec_frames_closed": not _module_exec_active,
        "r4_public_module_postverify_count": recorder.r4_module_postverify,
        "r4_actual_run_tail_called": _profile_r4_run_seen,
        "temporary_module_links_unchanged": modules_unchanged,
        "captured_stdout_chars": len(captured_out.getvalue()),
        "captured_stderr_chars": len(captured_err.getvalue()),
        "pytest_log_path": str(LOG_FILE.relative_to(ROOT)).replace("\\", "/"),
        "pytest_log_exists_after": LOG_FILE.is_file(),
        "pytest_internalerror_count": recorder.internal_error_count,
        "pytest_internal_errors": recorder.internal_errors,
        "first_function_source_mismatch": _function_mismatches[0] if _function_mismatches else None,
        "input_pins": list(pins.values()),
        "metadata_helper_invoked": False,
        "retained_host_scope_close_called": False,
        "fake_context_manager_exit_exercised": True,
        "protected_metadata_read": False,
        "credentials_read": False,
        "provider_or_account_call": False,
        "native_or_network_call": False,
        "child_process_call": False,
        "software_payload_read": False,
        "host_exit_permitted": False,
        "formal_m01_pass_count": 0,
    }


def _write_result(record):
    payload = json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    with RESULT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    result = {
        "schema": "iteration41.okx.m01.retained_cu_close_root_source_qa.v9",
        "status": "HOLD",
        "phase": "startup",
        "reason": "source_qa_not_complete",
        "profile_failure_counts": _profile_failure_counts(),
        "last_profile_observation": dict(_profile_observation),
        "pytest_internalerror_count": 0,
        "pytest_internal_errors": [],
        "first_function_source_mismatch": None,
        "code_comparator_selfchecks": None,
        "host_exit_permitted": False,
        "formal_m01_pass_count": 0,
    }
    try:
        result = main()
    except BaseException:
        result["phase"] = _phase
        result["reason"] = "source_qa_failed_closed"
        result["candidate_blocked_categories"] = list(_blocked_categories)
        result["code_comparator_selfchecks"] = _code_comparator_selfcheck_result
    _write_result(result)
    print(
        json.dumps(
            {
                key: result.get(key)
                for key in (
                    "status",
                    "phase",
                    "reason",
                    "checkout_head",
                    "pytest_exit",
                    "collected",
                    "passed",
                    "warning_count",
                    "preload_warning_count",
                    "candidate_blocked_categories",
                    "inputs_unchanged",
                    "test_source_origins_and_bindings_unchanged",
                    "helper_and_r4_code_global_bindings_unchanged",
                    "r4_actual_run_tail_called",
                    "host_exit_permitted",
                )
            },
            sort_keys=True,
        ),
        flush=True,
    )
    raise SystemExit(0 if result.get("status") == "SOURCE_FAKE_QA_ONLY" else 2)
