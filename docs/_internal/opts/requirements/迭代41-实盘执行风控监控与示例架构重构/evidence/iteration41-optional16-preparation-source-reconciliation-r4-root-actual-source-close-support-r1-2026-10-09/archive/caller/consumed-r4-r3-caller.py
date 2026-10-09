"""Additive R4 Root-only caller for one normal R4 source reconciliation.

After independent review, Root may load this exact file in the original
retained host and call ``run(ORIGINAL_ROOT_NAMESPACE,
expected_caller_sha256=...)`` once. Root custody is installed before the fresh
review scope's ``__enter__`` call. This code never starts or exits a host and
never retries the original preparation.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import inspect
import json
from pathlib import Path
import stat
import sys
import time
import types


ROOT = Path(r"D:\source_code\backtrader")
E = "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
CALLER_REL = ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_r4_r3.py"
CALLER_TEST_REL = ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_r4_fullchain_sourcefake_r3.py"
CALLER_TEST_SHA256 = "18b8df17744b477d84e3e0a291279d39091d5075c5e35cb96ea0956a3b09ba34"
R4_ROOT_KEY = "RECONCILIATION_ROOT_STATE_R4_R4_R3"
SOURCEFAKE_CALLER_TEST_KEY = "_optional16_r4_sourcefake_caller_token"
_SOURCEFAKE_CALLER_TEST_TOKEN = object()

R1_REL = "scripts/iteration41_optional16_preparation_source_reconciliation_r1.py"
R2_REL = "scripts/iteration41_optional16_preparation_source_reconciliation_r2.py"
R3_REL = "scripts/iteration41_optional16_preparation_source_reconciliation_r3.py"
R4_REL = "scripts/iteration41_optional16_preparation_source_reconciliation_r4.py"
R1_SHA = "5277b470a05cf956e29c826c4a8434e7bbd5697d90fb617df6756663cd09e4ba"
R2_SHA = "b3323d01597f180905d9d33ffb86429b7d91104eb950af95544d2a3ac1567efd"
R3_SHA = "769f6af037ee47ae8a0b165f49046cccd0b163f8f3992dd6490ec31ec90332ca"
R4_SHA = "bd5b8adf47edabbdcf5faf475ce11fa0dd6b936ad03c7e4be3cd991a26773760"

R1_NAME = "_root_optional16_reconciliation_helper_oct9"
R2_NAME = "_root_optional16_reconciliation_r2_helper_oct9"
R3_NAME = "_root_optional16_reconciliation_r3_helper_oct9"
R4_NAME = "_root_optional16_preparation_source_reconciliation_r4_actual_r4_r3_oct9"
CU_NAME = "_root_optional16_reconciliation_r4_cuv2_r4_r3_oct9"

R4_QA_REL = ".codex-tmp/optional16_r4_sourcefake_guarded_r2/sourcefake-a037a1075326-6fc0d48af8e846f1970cc64a660b7105.json"
R4_QA_SHA = "cb366f766fdcf0bed400bd892acf82a5395e143c22e63d425d5068cb45814ff7"
R4_QA_BYTES = 68351
R4_TEST_REL = "tests/unit/scripts/test_iteration41_optional16_preparation_source_reconciliation_r4_source_fake.py"
R4_TEST_SHA = "fd6bc283ec1a286d6ea2b315ff2dd904a239777468ed62b71cee532c429ffacd"
R4_REVIEW_REL = E + "iteration41-optional16-preparation-source-reconciliation-r4-independent-review-r1-2026-10-09.md"
R4_REVIEW_SHA = "96e483fe178ad68709f20cfce9eec8b5d0528242880d362c86d201f02ed6d234"

R3_CALLER_REL = ".codex-tmp/optional16_original_source_reconciliation_r3_root_actual_20261009.py"
R3_CALLER_SHA = "81876dd6002cb3b169612f2eebc5830a4d00cc51e787f5762858cfb63f214aa8"
R3_CALLER_BYTES = 14723
R3_OBS_REL = E + "iteration41-optional16-preparation-source-reconciliation-root-actual-r3-2026-10-09/observation.json"
R3_OBS_SHA = "02d28967108c9a58b924210b125aa41cc8079bf3aa689977de4a6972ac624f0e"
R3_OBS_BYTES = 1632

# Pin the two earlier caller drafts, their tests, and their public evidence
# records as immutable review history in this successor's fresh hold.
_HISTORY_PINS = {
    ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009.py":
        ("ecfa150cc5b9eea256102570195250a7b08e6eee25b4bc87525cd6948b15fb6d", 33833),
    ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_sourcefake.py":
        ("872ff206734e4447cbc8b6820d31ba92e0b70f37988bcb2efa2eace7eab6b3f1", 9172),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r4-root-actual-caller-preparation-r1-2026-10-09/README.md":
        ("6abb622a6d66e87f560ba69d0912dabfb81863f29f77de2c40416e981fd205eb", 3387),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r4-root-actual-caller-preparation-r1-2026-10-09/source-index.json":
        ("c1b8a69766bd0a9484b88106372f33a15131dff5c5518ecb76a42d99e9699fb0", 2816),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r4-root-actual-caller-preparation-r1-2026-10-09/sourcefake-report.json":
        ("a16514021f869b40f0440cec4749396d6eb10737e1fd59fff8b1928d9d570cc6", 2942),
    ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_r2.py":
        ("2aee88c60ecf931b2b81803ae6e29b511578346728e3714fec3defd0d5c689b9", 40106),
    ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_r2_sourcefake.py":
        ("0e0a7c3ead20c7d91ada2260001a72974429c8dc6525ff5b1c31ae127b561e73", 18480),
    ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_r3.py":
        ("11d7298ebb070f666b31fc257a39417777344b0d6a1b5e3d5c914bb5e4d77a20", 57530),
    ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_r3_sourcefake.py":
        ("fc281b1d17e0b5245b4a6ac7ffdbaddc14c3af715a984339defad894c79a7290", 26953),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-preparation-source-reconciliation-root-actual-caller-preparation-r2-2026-10-09/README.md":
        ("0067208dc6bd03d502a79e2365e325ce4b960bad4cfeebeafb7009f0a3d37148", 2713),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-preparation-source-reconciliation-root-actual-caller-preparation-r2-2026-10-09/source-index.json":
        ("cc237dbc05c03afa3111d46380b0c322d84eff2086553040919e653712c0297e", 4272),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-preparation-source-reconciliation-root-actual-caller-preparation-r2-2026-10-09/sourcefake-result.json":
        ("ed569c40e4e1a453ec1ea92a111bd95627ae666975b3652afde7253790e18f3f", 1577),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-preparation-source-reconciliation-root-actual-caller-preparation-r2-2026-10-09/sourcefake-run.txt":
        ("8cac1927e27e444f09990dbd36eac8ba097cf25b55b6bfc02d2e3a5aab78253e", 2188),
    ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_r4.py":
        ("4b3eee24e7c7f5f06b18c5f0fd3c75fe067b975496de22b23634cc7fd1772f8e", 58280),
    ".codex-tmp/optional16_r4_root_actual_caller_prepare_20261009_r4_fullchain_sourcefake.py":
        ("03e13fff8b6222faa7c4af10adfc417b54e8549f40a068e75c3c66180f3ab2a4", 20648),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r4-root-actual-caller-preparation-r2-2026-10-09/README.md":
        ("f6b9a3a369fa46448334207f3647df2987c52345fdb2690f900f591d78c85bf4", 2654),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r4-root-actual-caller-preparation-r2-2026-10-09/sourcefake-report.json":
        ("f7437483a3e9211615f821ae12ab5bb6abf728d4c06ff9862661362888ba902b", 3269),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r4-root-actual-caller-preparation-r2-2026-10-09/sourcefake-run.txt":
        ("e91dc60bdd525f3c6a9402df955d3d990d7c61f45790c45e20465b5ada1e2b16", 550),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r4-root-actual-caller-preparation-r2-2026-10-09/source-index.json":
        ("745797ecc05249374d1dd8444d22db1c845e58468cadb7e15d27f67bd81b88ee", 30778),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r4-root-actual-caller-preparation-r2-2026-10-09/independent-review-r1.json":
        ("d67948ddce49d5ab691a472c2be134c924b7c46c7d67dbee2e9b84b30f8d1d06", 4754),
}

CU = Path("D:/temp/iteration41-root-public-custody-v2.py")
CU_SHA = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
R3_SCOPE_PATH = "scripts/iteration41_root_held_source_scope_v3.py"
R4_SCOPE_PATH = "scripts/iteration41_root_held_source_scope_v4.py"

OUT = ROOT / E / "iteration41-optional16-preparation-source-reconciliation-root-actual-r4-r5-2026-10-09"
_MISSING = object()

_R3_RECORD_KEYS = {
    "root_namespace", "root_state", "root_result", "r1_module", "r1_registry",
    "r1_raw", "r2_module", "r2_registry", "r2_held", "r2_raw", "phase",
    "exit_started", "r1_record", "r2_record", "result_snapshot", "driver",
    "attempt", "entry", "v4", "scope", "call_module", "call_record",
    "module_sources", "prep_raw", "call_raw", "v3_raw", "v4_raw", "outer",
    "held", "outer_gen", "outer_frame", "cuv2_globals", "cuv2_module",
    "cuv2_function", "outer_exit_method", "outer_exit_function",
    "outer_exit_code", "outer_exit_globals",
}


class CallerError(RuntimeError):
    """A public finite reason code; exception detail is deliberately omitted."""


def _need(condition: object, code: str) -> None:
    if not condition:
        raise CallerError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _public_bytes(path: Path, digest: str, size: int | None = None) -> bytes:
    info = path.lstat()
    _need(stat.S_ISREG(info.st_mode), "public_input_not_regular")
    _need(not (getattr(info, "st_file_attributes", 0) & 0x400), "public_input_reparse_point")
    _need(0 < info.st_size <= 10 * 1024 * 1024, "public_input_size_out_of_bounds")
    if size is not None:
        _need(info.st_size == size, "public_input_size_changed")
    with path.open("rb") as stream:
        raw = stream.read(info.st_size + 1)
    _need(type(raw) is bytes and len(raw) == info.st_size, "public_input_read_size_changed")
    _need(_sha(raw) == digest, "public_input_hash_changed")
    return raw


def _freeze(value: object) -> object:
    if value is None or type(value) in (str, bytes, bool, int, float, complex):
        return (type(value), value)
    if type(value) in (tuple, list):
        return (type(value), tuple(_freeze(item) for item in value))
    if type(value) is dict:
        return (dict, tuple((_freeze(key), _freeze(item)) for key, item in value.items()))
    if type(value) in (set, frozenset):
        return (type(value), frozenset(_freeze(item) for item in value))
    return (type(value), id(value))


def _function_state(function: types.FunctionType) -> tuple[object, ...]:
    closure = function.__closure__ or ()
    return (
        function, function.__code__, function.__globals__, function.__module__,
        function.__name__, function.__qualname__, _freeze(function.__defaults__),
        _freeze(function.__kwdefaults__), _freeze(function.__annotations__),
        _freeze(function.__dict__), function.__closure__,
        tuple(_freeze(cell.cell_contents) for cell in closure),
    )


def _verify_prior_helper(module: types.ModuleType, binding: tuple[object, ...]) -> None:
    _need(type(binding) is tuple and len(binding) == 3, "prior_helper_binding_shape_invalid")
    functions, globals_state, registry = binding
    _need(type(functions) is tuple and type(globals_state) is dict
          and type(registry) is list and module.__dict__.get("_RETAINED") is registry,
          "prior_helper_binding_invalid")
    current_functions = tuple(
        (name, _function_state(value))
        for name, value in module.__dict__.items()
        if type(value) is types.FunctionType and value.__module__ == module.__name__
    )
    current_globals = {
        key: _freeze(value) for key, value in module.__dict__.items() if key != "_RETAINED"
    }
    _need(current_functions == functions and current_globals == globals_state,
          "prior_helper_binding_changed")


def _consumed_inputs_from_r3_record(record: dict[str, object]) -> dict[str, object]:
    """Return only identity-bound R1/R2 inputs retained by consumed R3."""
    _need(type(record) is dict and set(record) == _R3_RECORD_KEYS,
          "r3_record_shape_invalid")
    r1_module = record.get("r1_module")
    r1_registry = record.get("r1_registry")
    r1_record = record.get("r1_record")
    r1_raw = record.get("r1_raw")
    r2_module = record.get("r2_module")
    r2_registry = record.get("r2_registry")
    r2_record = record.get("r2_record")
    root_state = record.get("root_state")
    r2_held = record.get("r2_held")
    r2_raw = record.get("r2_raw")
    _need(type(r1_module) is types.ModuleType and r1_module.__name__ == R1_NAME
          and type(r1_registry) is list and len(r1_registry) == 1
          and r1_registry[0] is r1_record,
          "r1_consumed_tuple_changed")
    _need(type(r2_module) is types.ModuleType and r2_module.__name__ == R2_NAME
          and type(r2_registry) is list and len(r2_registry) == 1
          and r2_registry[0] is r2_record,
          "r2_consumed_tuple_changed")
    _need(type(r2_held) is tuple and len(r2_held) == 3
          and type(r2_held[2]) is dict and type(r2_raw) is bytes,
          "r2_held_source_tuple_invalid")
    _need(type(root_state) is dict
          and r2_record.get("root_state") is root_state
          and r2_record.get("root_namespace") is record.get("root_namespace")
          and r2_record.get("root_result") is record.get("root_result")
          and record.get("held") is root_state.get("held")
          and r2_record.get("held") is root_state.get("held"),
          "r2_original_outer_hold_identity_changed")
    _need(type(r1_raw) is bytes and r2_record.get("r1_raw") is r1_raw
          and r2_record.get("r1_record") is r1_record
          and r2_record.get("r1_registry") is r1_registry,
          "r1_r2_original_identity_chain_changed")
    r2_source_key = str(ROOT / R2_REL)
    _need(r2_held[2].get(r2_source_key) is r2_raw,
          "r2_raw_not_same_held_byte_object")
    _need(_sha(r1_raw) == R1_SHA and _sha(r2_raw) == R2_SHA,
          "r1_r2_consumed_source_pin_changed")
    return {
        "r1_module": r1_module, "r1_registry": r1_registry,
        "r1_record": r1_record, "r1_raw": r1_raw,
        "r2_module": r2_module, "r2_registry": r2_registry,
        "r2_record": r2_record, "r2_held": r2_held, "r2_raw": r2_raw,
    }


def _prior_context(root_namespace: dict[str, object]) -> dict[str, object]:
    _need(type(root_namespace) is dict and "__file__" not in root_namespace,
          "root_namespace_origin_invalid")
    root_sys = root_namespace.get("sys")
    root_modules = getattr(root_sys, "modules", None)
    _need(type(root_modules) is dict and root_modules is sys.modules,
          "root_sys_modules_identity_invalid")
    _need(R4_ROOT_KEY not in root_namespace,
          "r4_root_state_alias_already_present")
    root_state = root_namespace.get("PREP_STATE")
    original_result = root_namespace.get("PREP_RESULT")
    r3_state = root_namespace.get("RECONCILIATION_ROOT_STATE_R3")
    _need(type(root_state) is dict and type(original_result) is dict
          and type(r3_state) is dict,
          "original_root_state_missing")
    _need(r3_state.get("original_state") is root_state
          and r3_state.get("original_result") is original_result,
          "r3_original_root_reference_changed")
    r3_module = r3_state.get("helper")
    r3_binding = r3_state.get("binding")
    r3_registry = r3_state.get("binding")[2] if type(r3_binding) is tuple and len(r3_binding) == 3 else None
    r3_record = r3_registry[0] if type(r3_registry) is list and len(r3_registry) == 1 else None
    _need(type(r3_module) is types.ModuleType and r3_module.__name__ == R3_NAME
          and type(r3_binding) is tuple and type(r3_registry) is list
          and len(r3_registry) == 1 and type(r3_record) is dict,
          "r3_consumed_binding_invalid")
    _need(root_modules.get(R3_NAME) is r3_module and sys.modules.get(R3_NAME) is r3_module
          and r3_module.__dict__.get("_RETAINED") is r3_registry,
          "r3_helper_alias_changed")
    _verify_prior_helper(r3_module, r3_binding)
    _need(r3_record.get("phase") == "inner_scope_retained"
          and r3_record.get("exit_started") is False
          and "v3" not in r3_record
          and "module_source_reference_verified" not in r3_record,
          "r3_consumed_blocked_stage_changed")
    r3_held = r3_state.get("held")
    _need(type(r3_held) is tuple and len(r3_held) == 3
          and type(r3_held[2]) is dict,
          "r3_review_hold_invalid")
    r3_raw = r3_held[2].get(str(ROOT / R3_REL))
    _need(type(r3_raw) is bytes and _sha(r3_raw) == R3_SHA,
          "r3_source_not_from_held_review_tuple")
    _need(r3_module.__file__ == str(ROOT / R3_REL), "r3_helper_origin_changed")
    _need(r3_state.get("receipt") is r3_state.get("observation", {}).get("receipt")
          and r3_state.get("receipt", {}).get("status") == "BLOCKED_RETAINED"
          and r3_state.get("receipt", {}).get("reason_code") == "inner_binding_failed",
          "r3_consumed_receipt_changed")
    review_scope = r3_state.get("review_scope")
    _need(type(review_scope) is contextlib._GeneratorContextManager
          and inspect.getgeneratorstate(review_scope.gen) == inspect.GEN_CLOSED,
          "r3_review_scope_not_closed")

    prior = _consumed_inputs_from_r3_record(r3_record)
    r1_root_state = root_namespace.get("RECONCILIATION_ROOT_STATE")
    r2_root_state = root_namespace.get("RECONCILIATION_ROOT_STATE_R2")
    _need(type(r1_root_state) is dict and type(r2_root_state) is dict
          and r1_root_state.get("helper") is prior["r1_module"]
          and r1_root_state.get("binding")[2] is prior["r1_registry"]
          and r2_root_state.get("helper") is prior["r2_module"]
          and r2_root_state.get("binding")[2] is prior["r2_registry"]
          and r2_root_state.get("held") is prior["r2_held"],
          "prior_r1_r2_root_alias_changed")
    _need(root_modules.get(R1_NAME) is prior["r1_module"]
          and root_modules.get(R2_NAME) is prior["r2_module"]
          and prior["r1_module"]._RETAINED is prior["r1_registry"]
          and prior["r2_module"]._RETAINED is prior["r2_registry"],
          "prior_r1_r2_module_alias_changed")

    driver = root_state.get("driver")
    outer = root_state.get("outer")
    held = root_state.get("held")
    attempt = r3_record.get("attempt")
    scope = r3_record.get("scope")
    outer_gen = r3_record.get("outer_gen")
    _need(root_namespace.get("PREP_STATE") is root_state
          and root_namespace.get("PREP_RESULT") is original_result
          and r3_record.get("root_namespace") is root_namespace
          and r3_record.get("root_state") is root_state
          and r3_record.get("root_result") is original_result,
          "original_root_reference_changed")
    _need(root_state.get("driver") is driver and root_state.get("outer") is outer
          and root_state.get("held") is held
          and type(attempt) is tuple and len(attempt) == 10
          and attempt[4] is scope and attempt[5]._RETAINED[0] is r3_record.get("call_record")
          and r3_state.get("original_attempt") is attempt
          and r3_state.get("original_call_record") is r3_record.get("call_record")
          and r3_state.get("original_gen") is outer_gen
          and r3_state.get("original_scope") is scope,
          "original_attempt_reference_changed")
    _need(scope.state == "OPEN" and outer.gen is outer_gen
          and outer_gen.gi_frame is r3_record.get("outer_frame")
          and outer_gen.gi_suspended is True,
          "original_custody_state_not_retained")
    _need(len(scope.manifest()) == 457 and scope.public_map == scope.manifest()
          and scope.software_map == {} and scope.support_map == {},
          "original_inner_scope_public_shape_changed")
    root_result_snapshot = _freeze(original_result)
    r3_observation = r3_state.get("observation")
    _need(type(r3_observation) is dict, "r3_observation_invalid")
    observation_raw = _public_bytes(ROOT / R3_OBS_REL, R3_OBS_SHA, R3_OBS_BYTES)
    _need(json.loads(observation_raw.decode("utf-8")) == r3_observation,
          "r3_public_observation_binding_changed")
    return {
        "root_namespace": root_namespace, "root_state": root_state,
        "original_result": original_result, "original_result_snapshot": root_result_snapshot,
        "r3_state": r3_state, "r3_module": r3_module, "r3_binding": r3_binding,
        "r3_registry": r3_registry, "r3_record": r3_record, "r3_held": r3_held,
        "r3_raw": r3_raw, "r3_receipt": r3_state["receipt"],
        "r3_observation": r3_observation, "r3_observation_snapshot": _freeze(r3_observation),
        "review_scope_prior": review_scope, "driver": driver, "outer": outer,
        "held": held, "attempt": attempt, "scope": scope, "outer_gen": outer_gen,
        **prior,
    }


def _check_prior_preserved(context: dict[str, object]) -> dict[str, object]:
    root_namespace = context["root_namespace"]
    root_state = context["root_state"]
    original_result = context["original_result"]
    r3_state = context["r3_state"]
    r3_module = context["r3_module"]
    r3_registry = context["r3_registry"]
    r3_record = context["r3_record"]
    root_modules = root_namespace["sys"].modules
    _need(root_namespace.get("RECONCILIATION_ROOT_STATE_R3") is r3_state
          and r3_state.get("helper") is r3_module
          and r3_state.get("binding") is context["r3_binding"]
          and r3_state.get("held") is context["r3_held"]
          and r3_module._RETAINED is r3_registry
          and len(r3_registry) == 1 and r3_registry[0] is r3_record
          and root_modules.get(R3_NAME) is r3_module and sys.modules.get(R3_NAME) is r3_module,
          "r3_registry_identity_changed_after_call")
    _need(r3_record.get("phase") == "inner_scope_retained"
          and r3_record.get("exit_started") is False
          and r3_state.get("receipt") is context["r3_receipt"]
          and r3_state.get("observation") is context["r3_observation"]
          and _freeze(r3_state.get("observation")) == context["r3_observation_snapshot"],
          "r3_consumed_record_changed_after_call")
    _need(root_namespace.get("PREP_STATE") is root_state
          and root_namespace.get("PREP_RESULT") is original_result
          and _freeze(original_result) == context["original_result_snapshot"],
          "original_root_result_changed_after_call")
    for prefix in ("r1", "r2"):
        module = context[prefix + "_module"]
        registry = context[prefix + "_registry"]
        record = context[prefix + "_record"]
        _need(module._RETAINED is registry and len(registry) == 1
              and registry[0] is record,
              prefix + "_consumed_registry_changed_after_call")
        _need(record.get("phase") == "source_binding_blocked"
              and record.get("exit_started") is False,
              prefix + "_consumed_record_changed_after_call")
    _need(context["r2_held"][2].get(str(ROOT / R2_REL)) is context["r2_raw"],
          "r2_held_raw_identity_changed_after_call")
    scope = context["scope"]
    _need(scope.state in {"OPEN", "RETAINED", "CLOSED"},
          "original_inner_scope_state_uncertain")
    outer_gen = context["outer_gen"]
    return {
        "original_result_unchanged": True,
        "r1_registry_preserved": True,
        "r2_registry_preserved": True,
        "r3_registry_preserved": True,
        "original_inner_scope_state": scope.state,
        "original_outer_generator_closed": outer_gen.gi_frame is None,
    }


def _code_index(code: types.CodeType, result: dict[str, list[types.CodeType]]) -> None:
    result.setdefault(code.co_qualname, []).append(code)
    for value in code.co_consts:
        if type(value) is types.CodeType:
            _code_index(value, result)


def _class_methods_from_ast(node: ast.ClassDef, prefix: str,
                            result: dict[str, set[str]]) -> None:
    qualified = prefix + node.name if prefix else node.name
    methods = result.setdefault(qualified, set())
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.add(child.name)
        elif isinstance(child, ast.ClassDef):
            _class_methods_from_ast(child, qualified + ".", result)


def _compile_expected_source(raw: bytes, origin: Path) -> dict[str, object]:
    _need(type(raw) is bytes and 0 < len(raw) <= 10 * 1024 * 1024,
          "r4_source_raw_invalid")
    compiled = compile(raw, str(origin), "exec", dont_inherit=True)
    code_lists: dict[str, list[types.CodeType]] = {}
    _code_index(compiled, code_lists)
    tree = ast.parse(raw, filename=str(origin))
    functions = frozenset(
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    classes = frozenset(node.name for node in tree.body if isinstance(node, ast.ClassDef))
    class_methods: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            _class_methods_from_ast(node, "", class_methods)
    contextmanager_functions = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "contextmanager":
                contextmanager_functions.add(node.name)
            elif (isinstance(decorator, ast.Attribute)
                  and isinstance(decorator.value, ast.Name)
                  and decorator.value.id == "contextlib"
                  and decorator.attr == "contextmanager"):
                contextmanager_functions.add(node.name)
    return types.MappingProxyType({
        "raw": raw,
        "sha256": _sha(raw),
        "origin": str(origin),
        "code_index": types.MappingProxyType(
            {key: tuple(values) for key, values in code_lists.items()}
        ),
        "function_names": functions,
        "class_names": classes,
        "class_methods": types.MappingProxyType(
            {key: frozenset(values) for key, values in class_methods.items()}
        ),
        "contextmanager_functions": frozenset(contextmanager_functions),
    })


def _check_function_code(function: types.FunctionType, module: types.ModuleType,
                         contract: dict[str, object], expected_qualname: str) -> None:
    code_index = contract["code_index"]
    _need(function.__module__ == module.__name__
          and function.__globals__ is module.__dict__
          and function.__qualname__ == expected_qualname
          and function.__name__ == expected_qualname.rsplit(".", 1)[-1],
          "r4_helper_function_binding_not_source_bound")
    code = function.__code__
    expected_codes = code_index.get(expected_qualname, ())
    _need(code.co_filename == contract["origin"]
          and code.co_qualname == expected_qualname
          and any(code == expected for expected in expected_codes),
          "r4_helper_function_code_not_in_compiled_source")


def _check_source_function(function: object, module: types.ModuleType,
                           contract: dict[str, object], expected_qualname: str) -> None:
    _need(type(function) is types.FunctionType,
          "r4_helper_expected_function_missing")
    wrapped = function.__dict__.get("__wrapped__", _MISSING)
    if wrapped is _MISSING:
        _check_function_code(function, module, contract, expected_qualname)
        return
    _need(expected_qualname in contract["contextmanager_functions"]
          and type(wrapped) is types.FunctionType,
          "r4_helper_decorator_not_source_bound")
    _check_function_code(wrapped, module, contract, expected_qualname)
    _need(module.__dict__.get("contextmanager") is contextlib.contextmanager,
          "r4_contextmanager_decorator_origin_changed")
    expected_wrapper = contextlib.contextmanager(wrapped)
    _need(_function_state(function)[1:] == _function_state(expected_wrapper)[1:],
          "r4_contextmanager_wrapper_not_standard")


def _verify_source_module(module: types.ModuleType, contract: dict[str, object]) -> None:
    raw = contract["raw"]
    _need(type(raw) is bytes and _sha(raw) == contract["sha256"],
          "r4_expected_source_bytes_changed")
    _need(module.__file__ == contract["origin"], "r4_helper_source_origin_changed")
    expected_functions = contract["function_names"]
    actual_functions = {
        name for name, value in module.__dict__.items()
        if type(value) is types.FunctionType and value.__module__ == module.__name__
    }
    _need(actual_functions == expected_functions,
          "r4_helper_top_level_function_set_changed")
    for name in expected_functions:
        _check_source_function(module.__dict__.get(name), module, contract, name)
    expected_classes = contract["class_names"]
    actual_classes = {
        name for name, value in module.__dict__.items()
        if isinstance(value, type) and value.__module__ == module.__name__
    }
    _need(actual_classes == expected_classes, "r4_helper_top_level_class_set_changed")
    for class_name in expected_classes:
        cls = module.__dict__[class_name]
        _need(cls.__module__ == module.__name__ and cls.__qualname__ == class_name,
              "r4_helper_class_source_binding_changed")
        expected_methods = contract["class_methods"].get(class_name, frozenset())
        actual_methods = set()
        for name, member in vars(cls).items():
            functions = []
            if isinstance(member, (staticmethod, classmethod)):
                functions.append(member.__func__)
            elif type(member) is property:
                functions.extend(
                    item for item in (member.fget, member.fset, member.fdel)
                    if item is not None
                )
            elif type(member) is types.FunctionType:
                functions.append(member)
            if functions:
                actual_methods.add(name)
                for function in functions:
                    _check_source_function(function, module, contract,
                                           class_name + "." + name)
        _need(actual_methods == expected_methods,
              "r4_helper_class_method_set_not_source_bound")


def _capture_helper(module: types.ModuleType, raw: bytes, origin: Path,
                    contract: dict[str, object]) -> tuple[object, ...]:
    _need(raw is contract["raw"] and str(origin) == contract["origin"]
          and _sha(raw) == contract["sha256"],
          "r4_helper_raw_not_exact_expected_source")
    _verify_source_module(module, contract)
    functions = tuple(
        (name, _function_state(value))
        for name, value in module.__dict__.items()
        if type(value) is types.FunctionType and value.__module__ == module.__name__
    )
    globals_state = {
        key: _freeze(value) for key, value in module.__dict__.items() if key != "_RETAINED"
    }
    registry = module.__dict__.get("_RETAINED")
    _need(type(registry) is list, "r4_helper_registry_missing")
    return functions, globals_state, registry, contract


def _capture_classes(module: types.ModuleType,
                     contract: dict[str, object]) -> tuple[object, ...]:
    _verify_source_module(module, contract)
    result = []
    for value in tuple(module.__dict__.values()):
        if isinstance(value, type) and value.__module__ == module.__name__:
            members = []
            functions = []
            for key, member in vars(value).items():
                members.append((key, member, _freeze(member)))
                function = member.__func__ if isinstance(member, (staticmethod, classmethod)) else member
                if type(function) is types.FunctionType:
                    functions.append(_function_state(function))
                elif type(member) is property:
                    functions.extend(
                        _function_state(item)
                        for item in (member.fget, member.fset, member.fdel)
                        if item is not None
                    )
            result.append((value, tuple(members), tuple(functions)))
    return tuple(result)


def _verify_class_binding(class_binding: tuple[object, ...]) -> None:
    _need(type(class_binding) is tuple, "r4_helper_class_binding_shape_invalid")
    for cls, members, class_functions in class_binding:
        _need(isinstance(cls, type)
              and type(members) is tuple and type(class_functions) is tuple,
              "r4_helper_class_binding_invalid")
        _need(set(vars(cls)) == {key for key, _member, _frozen in members},
              "r4_helper_class_members_changed")
        for key, member, frozen in members:
            _need(vars(cls)[key] is member and _freeze(member) == frozen,
                  "r4_helper_class_member_changed")
        for state in class_functions:
            _need(type(state) is tuple and len(state) == 12
                  and _function_state(state[0]) == state,
                  "r4_helper_class_function_changed")


def _capture_source_module_binding(module: types.ModuleType,
                                   contract: dict[str, object]) -> tuple[object, ...]:
    _verify_source_module(module, contract)
    functions = tuple(
        (name, _function_state(value))
        for name, value in module.__dict__.items()
        if type(value) is types.FunctionType and value.__module__ == module.__name__
    )
    globals_state = {key: _freeze(value) for key, value in module.__dict__.items()}
    class_binding = _capture_classes(module, contract)
    return functions, globals_state, class_binding


def _verify_source_module_binding(module: types.ModuleType,
                                  binding: tuple[object, ...],
                                  contract: dict[str, object]) -> None:
    _need(type(binding) is tuple and len(binding) == 3,
          "source_module_binding_shape_invalid")
    functions, globals_state, class_binding = binding
    _verify_source_module(module, contract)
    current_functions = tuple(
        (name, _function_state(value))
        for name, value in module.__dict__.items()
        if type(value) is types.FunctionType and value.__module__ == module.__name__
    )
    _need(current_functions == functions, "source_module_function_binding_changed")
    _need(set(module.__dict__) == set(globals_state)
          and all(_freeze(module.__dict__[key]) == value
                  for key, value in globals_state.items()),
          "source_module_global_binding_changed")
    _verify_class_binding(class_binding)


def _verify_cuv2_factory(state: dict[str, object]) -> None:
    module = state["cuv2_module"]
    raw = state["cuv2_raw"]
    contract = state["cuv2_source_contract"]
    held = state["cuv2_outer_held"]
    _need(type(held) is tuple and len(held) == 3 and type(held[2]) is dict
          and held[2].get(str(CU)) is raw,
          "cuv2_raw_not_same_original_held_bytes")
    _need(raw is contract["raw"] and _sha(raw) == contract["sha256"],
          "cuv2_expected_raw_identity_or_hash_changed")
    _need(module.__dict__.get("held_public_sources") is state["cuv2_factory"],
          "cuv2_held_public_sources_binding_changed")
    _verify_source_module_binding(module, state["cuv2_binding"], contract)
    _check_source_function(state["cuv2_factory"], module, contract,
                           "held_public_sources")


def _verify_helper(module: types.ModuleType, binding: tuple[object, ...],
                   class_binding: tuple[object, ...]) -> None:
    _need(type(binding) is tuple and len(binding) == 4,
          "r4_helper_binding_shape_invalid")
    functions, globals_state, registry, contract = binding
    _verify_source_module(module, contract)
    _need(set(module.__dict__) - {"_RETAINED"} == set(globals_state),
          "r4_helper_global_names_changed")
    _need(module._RETAINED is registry, "r4_helper_registry_replaced")
    for key, state in globals_state.items():
        _need(_freeze(module.__dict__[key]) == state, "r4_helper_global_changed")
    for name, state in functions:
        current = module.__dict__.get(name)
        _need(type(current) is types.FunctionType and current is state[0]
              and current.__code__ is state[1] and current.__globals__ is state[2]
              and _function_state(current) == state,
              "r4_helper_function_changed")
    _verify_class_binding(class_binding)


def _verify_root_helper_binding(state: dict[str, object], module: types.ModuleType,
                                binding: tuple[object, ...],
                                class_binding: tuple[object, ...]) -> None:
    held = state.get("held")
    raw = state.get("helper_raw")
    contract = state.get("helper_source_contract")
    _verify_held_r4_raw(state, raw, contract)
    _need(type(binding) is tuple and len(binding) == 4 and binding[3] is contract,
          "r4_helper_expected_source_contract_identity_changed")
    _verify_helper(module, binding, class_binding)


def _verify_held_r4_raw(state: dict[str, object], raw: object,
                        contract: object) -> None:
    held = state.get("held")
    _need(type(held) is tuple and len(held) == 3 and type(held[2]) is dict
          and held[2].get(str(ROOT / R4_REL)) is raw,
          "r4_helper_raw_not_same_fresh_held_bytes")
    _need(type(contract) is type(types.MappingProxyType({}))
          and type(raw) is bytes and raw is contract["raw"]
          and _sha(raw) == contract["sha256"]
          and _sha(raw) == R4_SHA,
          "r4_helper_expected_source_contract_identity_changed")


def _load_exact(raw: bytes, origin: Path, name: str,
                custody: dict[str, object] | None = None,
                custody_key: str = "helper") -> types.ModuleType:
    _need(name not in sys.modules, "r4_helper_alias_already_loaded")
    module = types.ModuleType(name)
    module.__file__ = str(origin)
    if custody is not None:
        custody[custody_key + "_module"] = module
        custody[custody_key + "_alias"] = name
    sys.modules[name] = module
    try:
        exec(compile(raw, str(origin), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    except BaseException:
        # Keep the failed alias in place for custody review; do not silently
        # replace or retry a source module in this host.
        raise
    return module


def _invoke_r4_once(helper: types.ModuleType, context: dict[str, object]) -> dict[str, object]:
    _need(type(helper._RETAINED) is list and not helper._RETAINED,
          "r4_helper_prior_attempt_present")
    test_token = context.get("sourcefake_caller_test_token")
    kwargs: dict[str, object] = {}
    if test_token is _SOURCEFAKE_CALLER_TEST_TOKEN:
        _need(context["root_namespace"].get(SOURCEFAKE_CALLER_TEST_KEY) is test_token,
              "sourcefake_caller_test_token_lost")
        _need(getattr(context["r3_state"].get("original_scope"), "test_only", False) is True,
              "sourcefake_caller_scope_not_test_only")
        # Only the explicitly marked public fixture can request the helper's
        # existing sourcefake branch; Root's normal invocation has no marker.
        kwargs["_sourcefake_token"] = helper._SOURCEFAKE_TOKEN
    return helper.reconcile_retained_preparation_r4(
        context["root_namespace"], context["root_state"], context["original_result"],
        context["r3_state"], requested=True, **kwargs,
    )


def _new_review_attempt(root_namespace: dict[str, object],
                        context: dict[str, object]) -> dict[str, object]:
    """Install Root custody before loading or calling CUv2's scope factory."""
    _need(R4_ROOT_KEY not in root_namespace, "r4_root_state_alias_already_present")
    state: dict[str, object] = {
        "review_scope": None,
        "review_generator": None,
        "held": _MISSING,
        "enter_started": False,
        "enter_returned": False,
        "yielded": False,
        "yield_validated": False,
        "helper_load_started": False,
        "helper_load_failed": False,
        "helper_module": None,
        "helper_alias": None,
        "exit_started": False,
        "exit_returned": False,
        "exit_raised": False,
        "exit_attempt_count": 0,
        "normal_postverify": False,
        "custody_status": "ENTER_NOT_STARTED",
        "original_state": context["root_state"],
        "original_result": context["original_result"],
        "original_result_snapshot": context["original_result_snapshot"],
        "r3_state": context["r3_state"],
        "helper": None,
        "binding": None,
        "class_binding": None,
        "helper_raw": None,
        "helper_source_contract": None,
        "cuv2_module": None,
        "cuv2_raw": None,
        "cuv2_source_contract": None,
        "cuv2_outer_held": None,
        "cuv2_factory": None,
        "cuv2_binding": None,
        "cuv2_factory_called": False,
        "cuv2_factory_pre_use_verified": False,
        "cuv2_factory_post_call_verified": False,
        "receipt": None,
        "observation": None,
    }
    # Install before loading the CUv2 helper or invoking its scope factory.
    # Any later failure keeps all acquired source and scope references in Root.
    root_namespace[R4_ROOT_KEY] = state
    state["root_state_installed_before_enter"] = True
    return state


def _attach_review_scope(state: dict[str, object], review_scope: object) -> None:
    _need(type(review_scope) is contextlib._GeneratorContextManager,
          "r4_review_scope_object_invalid")
    _need(state.get("review_scope") is None and state.get("enter_started") is False,
          "r4_review_scope_already_attached")
    state["review_scope"] = review_scope
    state["review_generator"] = review_scope.gen


def _enter_review_scope(state: dict[str, object]) -> object:
    scope = state["review_scope"]
    _need(type(scope) is contextlib._GeneratorContextManager,
          "r4_review_scope_not_root_retained")
    state["enter_started"] = True
    state["custody_status"] = "ENTER_STARTED"
    try:
        held = scope.__enter__()
    except BaseException:
        state["enter_raised"] = True
        state["custody_status"] = "ENTER_UNCERTAIN_CUSTODY_RETAINED"
        raise
    # Record every returned value, including None, before validating its shape.
    state["enter_returned"] = True
    state["yielded"] = True
    state["held"] = held
    state["custody_status"] = "YIELDED_UNVALIDATED_CUSTODY_RETAINED"
    return held


def _load_after_review_enter(state: dict[str, object], held: object,
                             loader: object) -> object:
    _need(state.get("enter_returned") is True and state.get("yielded") is True
          and state.get("held") is held,
          "r4_review_enter_not_confirmed")
    _need(type(held) is tuple and len(held) == 3 and type(held[2]) is dict,
          "r4_review_hold_shape_invalid")
    state["yield_validated"] = True
    state["helper_load_started"] = True
    state["custody_status"] = "HELPER_LOAD_STARTED_CUSTODY_RETAINED"
    try:
        helper = loader(held, state)
    except BaseException:
        state["helper_load_failed"] = True
        state["custody_status"] = "HELPER_LOAD_UNCERTAIN_CUSTODY_RETAINED"
        raise
    state["helper_module"] = helper
    state["custody_status"] = "HELPER_LOADED_CUSTODY_RETAINED"
    return helper


def _finish_review_attempt(state: dict[str, object]) -> bool:
    """Close once only after __enter__ returned; retain custody on uncertainty."""
    if state.get("enter_returned") is not True:
        state["normal_postverify"] = False
        state["custody_status"] = "ENTER_NOT_CONFIRMED_CUSTODY_RETAINED"
        return False
    if state.get("exit_started") is True:
        return state.get("normal_postverify") is True
    scope = state["review_scope"]
    state["exit_started"] = True
    state["exit_attempt_count"] = state.get("exit_attempt_count", 0) + 1
    state["custody_status"] = "EXIT_STARTED_CUSTODY_RETAINED"
    try:
        result = scope.__exit__(None, None, None)
    except BaseException:
        state["exit_raised"] = True
        state["normal_postverify"] = False
        state["custody_status"] = "EXIT_UNCERTAIN_CUSTODY_RETAINED"
        return False
    state["exit_returned"] = True
    generator = state["review_generator"]
    try:
        normal = result is False and getattr(generator, "gi_frame", object()) is None
    except BaseException:
        normal = False
    state["normal_postverify"] = normal
    state["custody_status"] = (
        "CLOSED_NORMAL_POSTVERIFIED" if normal
        else "EXIT_RETURNED_UNVERIFIED_CUSTODY_RETAINED"
    )
    return normal


def _verify_attempt_originals(root_namespace: dict[str, object],
                              state: dict[str, object]) -> bool:
    original_state = state["original_state"]
    original_result = state["original_result"]
    _need(root_namespace.get("PREP_STATE") is original_state
          and root_namespace.get("PREP_RESULT") is original_result
          and _freeze(original_result) == state["original_result_snapshot"],
          "original_root_state_or_result_changed")
    return True


def _review_pins(qa_raw: bytes, own_raw: bytes, own_digest: str,
                 test_raw: bytes) -> tuple[dict[str, str], int]:
    qa = json.loads(qa_raw.decode("utf-8"))
    _need(type(qa) is dict and qa.get("status") == "SOURCEFAKE_QA_PASSED"
          and qa.get("pytest_exit_code") == 0
          and qa.get("passed_call_reports") == 47
          and qa.get("collected_tests") == 47
          and qa.get("input_count") == 51
          and qa.get("original_root_audit_regression_missing") is False
          and qa.get("sourcefake_not_actual_or_formal_acceptance") is True,
          "prior_r4_root_qa_receipt_changed")
    _need(qa.get("private_inputs_read") is False
          and qa.get("external_software_payload_read") is False
          and qa.get("provider_network_native_or_winapi_call") is False,
          "prior_r4_root_qa_scope_invalid")
    metadata = qa.get("metadata")
    _need(type(metadata) is dict
          and metadata.get("outer_public_pin_rows") == 42
          and metadata.get("software_pin_rows") == 3
          and metadata.get("original_root_audit_regression_present") is True
          and metadata.get("historical_run_assignment_identity_proven") is False,
          "prior_r4_root_qa_metadata_changed")
    forbidden = qa.get("forbidden_attempts_observed")
    _need(type(forbidden) is dict and forbidden
          and all(value == 0 for value in forbidden.values()),
          "prior_r4_root_qa_forbidden_count_nonzero")
    pins = qa.get("pins")
    post_pins = qa.get("post_pins")
    _need(type(pins) is dict and type(post_pins) is dict
          and len(pins) == 51 and pins == post_pins,
          "prior_r4_root_qa_pin_closure_changed")
    result: dict[str, str] = {}
    for relative, row in pins.items():
        _need(type(relative) is str and type(row) is dict
              and set(row) == {"bytes", "origin", "sha256"}
              and type(row["bytes"]) is int and type(row["sha256"]) is str,
              "prior_r4_root_qa_pin_row_invalid")
        expected_origin = str((ROOT / relative).resolve())
        _need(row["origin"] == expected_origin, "prior_r4_root_qa_origin_changed")
        result[relative] = row["sha256"]
    required = {
        R4_REL: R4_SHA,
        R4_TEST_REL: R4_TEST_SHA,
        R4_REVIEW_REL: R4_REVIEW_SHA,
    }
    _need(all(result.get(path) == digest for path, digest in required.items()),
          "prior_r4_root_qa_required_input_pin_changed")
    for relative, digest in required.items():
        result[relative] = digest
    fixed = {
        R4_QA_REL: R4_QA_SHA,
        R3_CALLER_REL: R3_CALLER_SHA,
        R3_OBS_REL: R3_OBS_SHA,
        CALLER_REL: own_digest,
        CALLER_TEST_REL: _sha(test_raw),
    }
    _need(_sha(own_raw) == own_digest, "caller_source_pin_changed")
    for relative, digest in fixed.items():
        prior = result.get(relative)
        _need(prior is None or prior == digest, "caller_fixed_source_pin_conflict")
        result[relative] = digest
    for relative, (digest, _size) in _HISTORY_PINS.items():
        prior = result.get(relative)
        _need(prior is None or prior == digest, "caller_history_source_pin_conflict")
        result[relative] = digest
    return result, len(pins)


def run(root_namespace: dict[str, object], *, expected_caller_sha256: str) -> dict[str, object]:
    """Run one source reconciliation call in the original retained Root host."""
    started = time.monotonic()
    phase = "preflight"
    context: dict[str, object] | None = None
    helper: types.ModuleType | None = None
    binding: tuple[object, ...] | None = None
    class_binding: tuple[object, ...] | None = None
    review_scope: object | None = None
    review_held: object | None = None
    retained_state: dict[str, object] | None = None
    review_closed = False
    output_created = False
    helper_binding_pre_verified = False
    helper_binding_post_verified = False
    qa_source_pin_count = None
    receipt: dict[str, object] | None = None
    reason = None
    attempted = False
    preserved: dict[str, object] = {}

    try:
        _need(type(expected_caller_sha256) is str and len(expected_caller_sha256) == 64,
              "caller_expected_pin_invalid")
        own_path = Path(__file__).resolve()
        own_rel = own_path.relative_to(ROOT).as_posix()
        _need(own_rel == CALLER_REL, "caller_origin_changed")
        own_raw = _public_bytes(own_path, expected_caller_sha256)
        _need(sys.version_info[:3] == (3, 11, 5)
              and sys.flags.isolated and sys.flags.no_site and sys.flags.interactive
              and sys.dont_write_bytecode,
              "root_host_runtime_changed")
        context = _prior_context(root_namespace)
        if root_namespace.get(SOURCEFAKE_CALLER_TEST_KEY) is _SOURCEFAKE_CALLER_TEST_TOKEN:
            context["sourcefake_caller_test_token"] = _SOURCEFAKE_CALLER_TEST_TOKEN
        qa_raw = _public_bytes(ROOT / R4_QA_REL, R4_QA_SHA, R4_QA_BYTES)
        test_raw = _public_bytes(ROOT / CALLER_TEST_REL, CALLER_TEST_SHA256)
        pins, sourcefake_pin_count = _review_pins(qa_raw, own_raw, expected_caller_sha256, test_raw)
        qa_source_pin_count = sourcefake_pin_count
        pins[R3_CALLER_REL] = R3_CALLER_SHA
        pins[R3_OBS_REL] = R3_OBS_SHA
        pins[R4_QA_REL] = R4_QA_SHA
        pins[R4_TEST_REL] = R4_TEST_SHA
        pins[R4_REVIEW_REL] = R4_REVIEW_SHA
        qa_rows = json.loads(qa_raw.decode("utf-8"))["pins"]
        for relative, digest in pins.items():
            raw = _public_bytes(ROOT / relative, digest)
            expected = None
            # The prior QA carries exact byte sizes for its 51 inputs.
            if relative in qa_rows:
                expected = qa_rows[relative]["bytes"]
            expected = {
                R4_QA_REL: R4_QA_BYTES,
                R3_CALLER_REL: R3_CALLER_BYTES,
                R3_OBS_REL: R3_OBS_BYTES,
            }.get(relative, expected)
            if relative in _HISTORY_PINS:
                expected = _HISTORY_PINS[relative][1]
            if expected is not None:
                _need(len(raw) == expected, "sourcefake_input_size_changed")
        phase = "cuv2_source_binding"
        original_outer_held = context["held"]
        _need(not OUT.exists(), "r4_output_namespace_not_fresh")
        OUT.mkdir(exist_ok=False)
        output_created = True
        retained_state = _new_review_attempt(root_namespace, context)
        retained_state["cuv2_outer_held"] = original_outer_held
        cu_raw = original_outer_held[2].get(str(CU))
        _need(type(cu_raw) is bytes and cu_raw is original_outer_held[2].get(str(CU))
              and _sha(cu_raw) == CU_SHA,
              "cuv2_bytes_not_from_original_root_hold")
        _need(CU_NAME not in sys.modules, "fresh_cuv2_alias_already_present")
        cu_contract = _compile_expected_source(cu_raw, CU)
        retained_state["cuv2_raw"] = cu_raw
        retained_state["cuv2_source_contract"] = cu_contract
        cu = _load_exact(cu_raw, CU, CU_NAME, custody=retained_state, custody_key="cuv2")
        _need(cu.__file__ == str(CU), "cuv2_alias_origin_changed")
        retained_state["cuv2_module"] = cu
        retained_state["cuv2_binding"] = _capture_source_module_binding(cu, cu_contract)
        retained_state["cuv2_factory"] = cu.__dict__.get("held_public_sources")
        _verify_cuv2_factory(retained_state)
        retained_state["cuv2_factory_pre_use_verified"] = True
        phase = "review_scope_open"
        review_scope = retained_state["cuv2_factory"](pins, {})
        retained_state["cuv2_factory_called"] = True
        _verify_cuv2_factory(retained_state)
        retained_state["cuv2_factory_post_call_verified"] = True
        _attach_review_scope(retained_state, review_scope)
        review_held = _enter_review_scope(retained_state)

        def load_r4_from_held(held: object, custody: dict[str, object]) -> object:
            helper_raw = held[2].get(str(ROOT / R4_REL))
            _need(type(helper_raw) is bytes
                  and helper_raw is held[2].get(str(ROOT / R4_REL))
                  and _sha(helper_raw) == R4_SHA,
                  "r4_helper_not_from_fresh_review_hold")
            _need(R4_NAME not in sys.modules, "fresh_r4_helper_alias_already_present")
            custody["helper_raw"] = helper_raw
            custody["helper_source_contract"] = _compile_expected_source(
                helper_raw, ROOT / R4_REL
            )
            # Preserve the independent source contract and alias before exec.
            return _load_exact(helper_raw, ROOT / R4_REL, R4_NAME, custody=custody)

        phase = "r4_helper_binding"
        helper = _load_after_review_enter(retained_state, review_held, load_r4_from_held)
        _need(helper.__file__ == str(ROOT / R4_REL)
              and helper.__name__ == R4_NAME and type(helper._RETAINED) is list
              and helper._RETAINED == [],
              "r4_helper_loaded_state_invalid")
        root_modules = root_namespace["sys"].modules
        _need(root_modules is sys.modules and root_modules.get(R4_NAME) is helper,
              "r4_helper_root_alias_invalid")
        contract = retained_state["helper_source_contract"]
        helper_raw = retained_state["helper_raw"]
        _verify_held_r4_raw(retained_state, helper_raw, contract)
        binding = _capture_helper(helper, helper_raw, ROOT / R4_REL, contract)
        class_binding = _capture_classes(helper, contract)
        _verify_root_helper_binding(retained_state, helper, binding, class_binding)
        helper_binding_pre_verified = True
        retained_state["held"] = review_held
        retained_state["helper"] = helper
        retained_state["binding"] = binding
        retained_state["class_binding"] = class_binding
        phase = "r4_reconcile_once"
        _need(type(helper._RETAINED) is list and not helper._RETAINED,
              "r4_helper_prior_attempt_present")
        _verify_root_helper_binding(retained_state, helper, binding, class_binding)
        attempted = True
        receipt = _invoke_r4_once(helper, context)
        _need(type(receipt) is dict, "r4_receipt_shape_invalid")
        _need(all(type(value) in (bool, str, int, type(None)) for value in receipt.values()),
              "r4_receipt_not_finite")
        retained_state["receipt"] = receipt
        _verify_root_helper_binding(retained_state, helper, binding, class_binding)
        helper_binding_post_verified = True
        preserved = _check_prior_preserved(context)
        phase = "review_scope_normal_exit"
    except CallerError as exc:
        reason = str(exc)
    except BaseException:
        # Exception text can contain paths or implementation details. Keep only
        # a fixed category and retain the host state.
        reason = "caller_unexpected_exception"
    finally:
        if retained_state is not None:
            try:
                review_closed = _finish_review_attempt(retained_state)
            except BaseException:
                review_closed = False
                retained_state["normal_postverify"] = False
                retained_state["custody_status"] = "EXIT_UNCERTAIN_CUSTODY_RETAINED"
            if not review_closed and reason is None:
                reason = (
                    "review_scope_enter_not_confirmed"
                    if retained_state.get("enter_returned") is not True
                    else "review_scope_normal_exit_unverified"
                )
            try:
                retained_state["original_state_result_preserved"] = (
                    _verify_attempt_originals(root_namespace, retained_state)
                )
            except BaseException:
                retained_state["original_state_result_preserved"] = False
                if reason is None:
                    reason = "original_root_state_or_result_changed"
        if helper is not None and binding is not None and class_binding is not None:
            try:
                _verify_root_helper_binding(retained_state, helper, binding, class_binding)
                helper_binding_post_verified = True
            except BaseException:
                helper_binding_post_verified = False
                if reason is None:
                    reason = "r4_post_binding_exception"

    outcome = {
        "schema": "iteration41.optional16.preparation.source-reconciliation-r4.root-actual.v4",
        "caller_phase": phase,
        "caller_reason_code": reason,
        "receipt": receipt,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "r4_api_invocations": 1 if attempted else 0,
        "r4_helper_source_function_global_class_bindings_verified": (
            helper_binding_pre_verified and helper_binding_post_verified
        ),
        "r4_root_qa_input_pin_count": qa_source_pin_count,
        "fresh_review_scope_normal_exit": review_closed,
        "review_scope_enter_returned": (
            retained_state.get("enter_returned") is True if retained_state is not None else False
        ),
        "review_scope_yielded": (
            retained_state.get("yielded") is True if retained_state is not None else False
        ),
        "review_scope_exit_started": (
            retained_state.get("exit_started") is True if retained_state is not None else False
        ),
        "review_scope_normal_postverify": (
            retained_state.get("normal_postverify") is True if retained_state is not None else False
        ),
        "review_scope_custody_status": (
            retained_state.get("custody_status") if retained_state is not None else "NOT_OPENED"
        ),
        "cuv2_held_factory_source_bound_before_use": (
            retained_state.get("cuv2_factory_pre_use_verified") is True
            if retained_state is not None else False
        ),
        "cuv2_held_factory_source_bound_after_call": (
            retained_state.get("cuv2_factory_post_call_verified") is True
            if retained_state is not None else False
        ),
        "original_state_result_preserved": (
            retained_state.get("original_state_result_preserved") is True
            if retained_state is not None else None
        ),
        "original_result_historical_assignment_identity_proven": False,
        "preparation_retry": False,
        "provider_account_activation": False,
        "formal_optional16_pass_count": 0,
        **preserved,
    }
    if receipt is not None:
        outcome["r4_status"] = receipt.get("status")
        outcome["r4_phase"] = receipt.get("phase")
        outcome["r4_reason_code"] = receipt.get("reason_code")
        outcome["original_inner_release"] = receipt.get("inner_release")
        outcome["original_outer_normal_exit"] = receipt.get("outer_normal_exit")
    _need(type(outcome) is dict, "observation_shape_invalid")
    r4_state = root_namespace.get(R4_ROOT_KEY)
    if type(r4_state) is dict:
        r4_state["observation"] = outcome
    # Only a newly created output directory and its public finite observation
    # are written. A repeat stops at OUT.exists() before opening a new scope.
    if output_created:
        encoded = (json.dumps(outcome, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
        with (OUT / "observation.json").open("xb") as stream:
            stream.write(encoded)
    return outcome


__all__ = ("run", "CallerError", "_consumed_inputs_from_r3_record", "_invoke_r4_once",
           "_new_review_attempt", "_enter_review_scope", "_load_after_review_enter",
           "_finish_review_attempt", "_verify_attempt_originals")
