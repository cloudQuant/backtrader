"""Root-only one-shot invocation wrapper for the accepted OKX close helper.

This wrapper runs only inside the original R3 host namespace. It opens a
second, source-pinned public custody scope, verifies the frozen source maps,
binds this wrapper and the fixed R2 close helper, then delegates normal close
to that helper. It never exits the host or performs metadata, provider,
account, process, network, or native operations.
"""

from __future__ import annotations

import hashlib
import json
import contextlib
import inspect
from pathlib import Path
import sys
import types


ROOT = Path("D:/source_code/backtrader")
CALLER_RELATIVE = ".codex-tmp/okx_m01_protected_rebind_r3_root_actual_candidate_20261009.py"
CALLER_PATH = ROOT / CALLER_RELATIVE
CALLER_SIZE = 55093
CALLER_SHA256 = "f80890de30021dc9751a439a247c0549afca7303fb13f8f8bb27019e6c193fd6"
CU_PATH = Path("D:/temp/iteration41-root-public-custody-v2.py")
CU_NAME = "_root_public_custody_v2"
CU_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
MAP_RELATIVE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09/source-map.json"
)
MAP_SIZE = 2877
MAP_SHA256 = "07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3"
HELPER_RELATIVE = ".codex-tmp/okx_m01_r3_normal_cu_close_helper_r2_20261009.py"
HELPER_PATH = ROOT / HELPER_RELATIVE
HELPER_NAME = "_okx_m01_r3_normal_cu_close_helper_r2_root_20261009"
HELPER_SIZE = 19399
HELPER_SHA256 = "01a51406d2b54abb116b70e93111e741beaa8f3ada54f15e3b5c67c684c59072"
WRAPPER_RELATIVE = ".codex-tmp/okx_m01_r3_normal_cu_close_root_actual_r2_20261009.py"
WRAPPER_PATH = ROOT / WRAPPER_RELATIVE
WRAPPER_NAME = "_okx_m01_r3_normal_cu_close_root_actual_r2_20261009"
PUBLIC_LIMIT = 2 * 1024 * 1024

SOURCE_PATHS = frozenset(
    {
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/__init__.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/issuer.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/entry.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/__init__.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/current_types.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py",
        "examples/000_live_certification/okx_penetration/_certification/m01_private_monitor_v2.py",
        "examples/000_live_certification/okx_penetration/_certification/__init__.py",
        "examples/000_live_certification/okx_penetration/_certification/models.py",
        "examples/000_live_certification/okx_penetration/_certification/cases.py",
        "examples/000_live_certification/okx_penetration/_certification/config.py",
        "examples/000_live_certification/okx_penetration/_certification/evidence.py",
        "examples/000_live_certification/okx_penetration/_certification/fixed_owner_routes.py",
        "examples/000_live_certification/okx_penetration/_certification/runner.py",
        "examples/000_live_certification/okx_penetration/cases/M01/M01_strategy.py",
        "examples/000_live_certification/okx_penetration/cases/M01/run.py",
        "backtrader_runtime/certification_roundtrip_private.py",
    }
)

SUPPORT_PINS = {
    MAP_RELATIVE: (MAP_SIZE, MAP_SHA256),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-root-helper-lifecycle-integration-r1-independent-review-r1-2026-10-09-oct7f/README.md": (
        3820,
        "c09eb8be009567b70d50a063e042ef7d75af8ce8d2368fd568bdb4b82e38263b",
    ),
    "tests/unit/scripts/test_iteration41_okx_m01_reader_lifecycle_integration_r1.py": (
        9809,
        "21d43a5e8d1c517c2ffaa147c96f58343fb188432d4fae47717a5b68b6ec040d",
    ),
    "scripts/iteration41_okx_m01_v3_protected_rebind_r2.py": (
        28418,
        "0baa2191b8d5b99b42e7a13ddc217f0d90291db8279b20f74a3d92c676649810",
    ),
    "tests/unit/scripts/test_iteration41_okx_m01_v3_protected_rebind_r2.py": (
        23557,
        "4268d340cae45dbcf7574c38f98f2546df78f9a7ff82049f0baecad2904b5eea",
    ),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-r2-source-candidate-r1-2026-10-09/README.md": (
        4183,
        "f474779d3dda9b88568fc35a6cc2faccff9765fbed9ef23783a0f6fc9b94ca37",
    ),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-r2-source-candidate-r1-2026-10-09/candidate-pins.json": (
        2165,
        "dad69ff22275926d824b895a60b59995ecd7e8659f223c88d852cb01a6394043",
    ),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-r2-require-binding-independent-review-r1-2026-10-09/review.md": (
        1834,
        "fe530a9e8323a5ee492c1d7b1fc80028423df70ad5fd032143ce1790c965f2d4",
    ),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-r2-dev-delivery-proposal-r1-2026-10-09/root-source-qa.py": (
        7952,
        "54540781820cab39cdfd3ce2f62b7fc2be4688bffec5a72e0fa7881a411fe583",
    ),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-r2-dev-delivery-proposal-r1-2026-10-09/root-source-qa-result.json": (
        6751,
        "e08ca3aac8f6479117c0066b741ad557ff4d24cfb9da556785a6eaa3af7d1744",
    ),
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-r2-dev-delivery-proposal-r1-2026-10-09/delivery-manifest.json": (
        6340,
        "2d0c87fdcfe2a0a06cfb1617655fb87bb047ba66d1e0089af37b2a247efdeb7a",
    ),
    ".codex-tmp/okx_m01_rebind_r2_root_postcommit_20261009.json": (
        2416,
        "3a13f0f612e63d543ee47cc140e1d6f72db98814f59f56b258a4bca96b4fc55c",
    ),
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": (
        33887,
        "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76",
    ),
}

SOFTWARE_PINS = {
    "C:/anaconda3/python.exe": "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642",
    "C:/anaconda3/python311.dll": "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00",
    str(CU_PATH): CU_SHA256,
}
_attempted_original_scopes = []
_retained = []


class RootCloseError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in {"root_binding", "public_scope", "source_binding", "normal_close", "postverify"} else "root_binding"
        super().__init__(self.code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _report(status="BLOCKED", phase="root_binding", reason="source_or_close_state_unconfirmed", **facts):
    result = {
        "schema": "iteration41.okx.m01.r3_normal_close_root_invocation_r2.v1",
        "status": status,
        "phase": phase,
        "reason": reason,
        "helper_sha256": HELPER_SHA256,
        "original_public_pin_count": 33,
        "original_software_pin_count": 3,
        "review_public_pin_count": 35,
        "review_software_pin_count": 3,
        "review_scope_entered": False,
        "review_scope_normal_close_confirmed": False,
        "helper_source_bound": False,
        "original_caller_source_bound": False,
        "normal_close_invocation_count": 0,
        "original_scope_normal_close_confirmed": False,
        "original_result_unchanged": False,
        "original_maps_and_state_preserved": False,
        "actual_retained_host_close": False,
        "host_exit_permitted": False,
        "metadata_or_admission_call": False,
        "provider_call": False,
        "account_call": False,
        "formal_m01_pass_count": 0,
    }
    result.update(facts)
    return result


def _expected_result(result):
    return (
        type(result) is dict
        and result.get("schema") == "iteration41.okx.m01.root_protected_metadata_rebind_r3.v1"
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
    )


def _helper_report_is_success(result):
    return (
        type(result) is dict
        and result.get("schema") == "iteration41.okx.m01.retained_cu_normal_close.v1"
        and result.get("status") == "CU_SCOPE_NORMAL_CLOSE_CONFIRMED"
        and result.get("phase") == "complete"
        and result.get("reason") == "none"
        and result.get("normal_close_called") is True
        and result.get("normal_close_confirmed") is True
        and result.get("uncertainty_references_retained") is False
        and result.get("host_exit_permitted") is False
        and result.get("metadata_helper_invoked") is False
        and result.get("metadata_rebound") is False
        and result.get("fresh_source_admission_released") is False
        and result.get("credentials_read") is False
        and result.get("provider_call") is False
        and result.get("account_call") is False
        and result.get("formal_m01_pass_count") == 0
        and result.get("original_result_unchanged") is True
        and result.get("all_retained_registries_empty") is True
    )


def _expected_public_pins(original_globals, original_raw):
    if type(original_globals) is not dict or type(original_raw) is not dict:
        raise RootCloseError("root_binding")
    caller_raw = original_raw.get(str(CALLER_PATH))
    if type(caller_raw) is not bytes or len(caller_raw) != CALLER_SIZE or _sha(caller_raw) != CALLER_SHA256:
        raise RootCloseError("source_binding")
    map_raw = original_raw.get(str(ROOT / MAP_RELATIVE))
    if type(map_raw) is not bytes or len(map_raw) != MAP_SIZE or _sha(map_raw) != MAP_SHA256:
        raise RootCloseError("public_scope")
    try:
        map_doc = json.loads(map_raw.decode("utf-8", errors="strict"))
        source_pins = map_doc["source_pins"]
        canonical = (json.dumps(map_doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
    except BaseException:
        raise RootCloseError("public_scope") from None
    if (
        type(map_doc) is not dict
        or set(map_doc) != {"schema", "source_pins"}
        or map_doc.get("schema") != "iteration41.okx.m01.case-source-map.v3"
        or type(source_pins) is not dict
        or set(source_pins) != SOURCE_PATHS
        or map_raw != canonical
    ):
        raise RootCloseError("public_scope")
    pins = dict(source_pins)
    if any(type(path) is not str or type(digest) is not str or len(digest) != 64 for path, digest in pins.items()):
        raise RootCloseError("public_scope")
    if pins.keys() & SUPPORT_PINS.keys():
        raise RootCloseError("public_scope")
    pins.update({path: digest for path, (_, digest) in SUPPORT_PINS.items()})
    caller_relative = CALLER_PATH.relative_to(ROOT).as_posix()
    if caller_relative in pins:
        raise RootCloseError("public_scope")
    pins[caller_relative] = CALLER_SHA256
    if len(pins) != 33:
        raise RootCloseError("public_scope")
    for relative, (size, digest) in SUPPORT_PINS.items():
        value = original_raw.get(str(ROOT / Path(relative)))
        if type(value) is not bytes or len(value) != size or _sha(value) != digest:
            raise RootCloseError("public_scope")
    for relative, digest in pins.items():
        value = original_raw.get(str(ROOT / Path(relative)))
        if type(value) is not bytes or len(value) > PUBLIC_LIMIT or _sha(value) != digest:
            raise RootCloseError("public_scope")
    return pins


def _result_snapshot(result):
    if type(result) is not dict or any(type(key) is not str for key in result):
        raise RootCloseError("root_binding")
    if any(type(value) not in (str, int, bool, type(None)) for value in result.values()):
        raise RootCloseError("root_binding")
    return tuple(sorted((key, type(value), value) for key, value in result.items()))


def _state_snapshot(state):
    if type(state) is not dict or any(type(key) is not str for key in state):
        raise RootCloseError("root_binding")
    identities = tuple((key, id(value)) for key, value in state.items())
    primitives = tuple(sorted((key, type(value), value) for key, value in state.items() if type(value) in (str, int, bool, type(None))))
    return identities, primitives


def _module_map(state):
    names = (
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
    modules = state.get("modules")
    if type(modules) is not tuple or len(modules) != len(names):
        raise RootCloseError("root_binding")
    if any(type(module) is not types.ModuleType or module.__name__ != name or sys.modules.get(name) is not module for module, name in zip(modules, names)):
        raise RootCloseError("root_binding")
    found = dict(zip(names, modules))
    v2, current_types, worker = found[names[0]], found[names[1]], found[names[2]]
    cert, contract, supervisor = found[names[3]], found[names[4]], found[names[5]]
    v3, reader = found[names[6]], found[names[7]]
    if not (
        v2.current_types is current_types
        and v2.worker is worker
        and v2.job_supervisor is supervisor
        and cert.m01_private_monitor_v2 is contract
        and supervisor.worker is worker
        and supervisor.current_types is current_types
        and supervisor.contract is contract
        and v3.current_reader is reader
        and reader.current_types is current_types
        and reader.worker is worker
        and reader.job_supervisor is supervisor
    ):
        raise RootCloseError("root_binding")
    return names, modules


def _verify_original_scope(original_globals, state, raw):
    scope = state.get("scope")
    held = state.get("held")
    cu = state.get("cu")
    if (
        type(scope) is not contextlib._GeneratorContextManager
        or type(getattr(scope, "gen", None)) is not types.GeneratorType
        or inspect.getgeneratorstate(scope.gen) != inspect.GEN_SUSPENDED
        or type(cu) is not types.ModuleType
        or cu.__name__ != CU_NAME
        or sys.modules.get(CU_NAME) is not cu
        or type(held) is not tuple
        or len(held) != 3
        or held[0] is not state.get("private")
        or held[1] is not state.get("cli_module")
        or held[2] is not raw
        or scope.gen.gi_frame is None
        or scope.gen.gi_frame.f_globals is not cu.__dict__
    ):
        raise RootCloseError("root_binding")
    bindings = state.get("bindings")
    records = [record for record in bindings if type(record) is tuple and len(record) == 7 and record[0] is cu] if type(bindings) is tuple else []
    if len(records) != 1:
        raise RootCloseError("root_binding")
    record = records[0]
    entries = [item for item in record[3] if type(item) is tuple and len(item) == 5 and item[0] is cu and item[1] == "held_public_sources"]
    if len(entries) != 1:
        raise RootCloseError("root_binding")
    generator_function = getattr(entries[0][3], "__wrapped__", None)
    if (
        type(generator_function) is not types.FunctionType
        or scope.gen.gi_code is not generator_function.__code__
        or scope.gen.gi_frame.f_code is not generator_function.__code__
    ):
        raise RootCloseError("root_binding")
    return scope, held, cu, record, generator_function


def invoke(original_globals, wrapper_module, wrapper_raw, wrapper_size, wrapper_sha256):
    """Verify the reviewed scope and invoke the fixed R2 close helper once."""
    phase = "root_binding"
    review_scope = None
    review_held = None
    review_raw = None
    helper_module = None
    original_scope = None
    review_scope_verified = False
    state = result = raw = software = None
    state_before = result_before = raw_before = software_before = None
    called = False
    report = _report()
    try:
        phase = "wrapper_binding"
        if (
            type(wrapper_module) is not types.ModuleType
            or wrapper_module.__name__ != WRAPPER_NAME
            or sys.modules.get(WRAPPER_NAME) is not wrapper_module
            or type(wrapper_module.__file__) is not str
            or wrapper_module.__file__ != str(WRAPPER_PATH)
            or HELPER_NAME in sys.modules
            or type(wrapper_raw) is not bytes
            or type(wrapper_size) is not int
            or wrapper_size != len(wrapper_raw)
            or _sha(wrapper_raw) != wrapper_sha256
            or type(_attempted_original_scopes) is not list
            or _attempted_original_scopes
            or type(_retained) is not list
            or _retained
        ):
            raise RootCloseError("source_binding")
        if wrapper_size <= 0 or len(wrapper_sha256) != 64:
            raise RootCloseError("source_binding")
        caller = original_globals
        if type(caller) is not dict:
            raise RootCloseError("root_binding")
        phase = "original_result_binding"
        state = caller.get("ROOT_STATE")
        result = caller.get("ROOT_RESULT")
        if type(state) is not dict or not _expected_result(result):
            raise RootCloseError("root_binding")
        raw = state.get("raw")
        phase = "original_public_pins"
        pins = _expected_public_pins(caller, raw)
        phase = "original_software_map"
        software = caller.get("SOFTWARE")
        if (
            type(software) is not dict
            or caller.get("SOFTWARE") is not software
            or len(software) != 3
            or software != SOFTWARE_PINS
        ):
            raise RootCloseError("public_scope")
        software_before = tuple(sorted(software.items()))
        phase = "original_scope_binding"
        original_scope, original_held, cu, cu_record, generator_function = _verify_original_scope(caller, state, raw)
        if any(previous is original_scope for previous in _attempted_original_scopes):
            raise RootCloseError("normal_close")
        software_keys = {str(Path(path)) for path in software}
        original_public_keys = {str(ROOT / Path(path)) for path in pins}
        phase = "original_raw_keyset"
        if set(raw) != original_public_keys | software_keys or any(type(raw[key]) is not bytes for key in software_keys):
            raise RootCloseError("public_scope")
        phase = "original_module_graph"
        names, modules = _module_map(state)
        phase = "original_caller_constants"
        if caller.get("ROOT") != ROOT:
            raise RootCloseError("root_binding")
        if caller.get("CU") != CU_PATH or caller.get("CU_SHA256") != CU_SHA256 or caller.get("MAP_RELATIVE") != MAP_RELATIVE or caller.get("MAP_SHA256") != MAP_SHA256 or caller.get("MAP_SIZE") != MAP_SIZE or caller.get("SUPPORT_PINS") != SUPPORT_PINS:
            raise RootCloseError("root_binding")
        if caller.get("SOURCE_MAP_EXPECTED_PATHS") != SOURCE_PATHS:
            raise RootCloseError("root_binding")
        if (
            state.get("private") is not original_held[0]
            or state.get("cli_module") is not original_held[1]
            or state.get("private") is not modules[9]
            or state.get("cli_module") is not modules[10]
            or state.get("reader") is not modules[7]
            or state.get("helper") is not modules[8]
            or state.get("admission") is not None
            or state.get("admission_private_binding") is not None
            or state.get("bindings_complete") is not False
            or state.get("registry_snapshot_complete") is not False
        ):
            raise RootCloseError("root_binding")
        phase = "original_state_projection"
        state_before = _state_snapshot(state)
        result_before = _result_snapshot(result)
        raw_before = tuple((key, id(value)) for key, value in raw.items())

        wrapper_path = WRAPPER_PATH
        wrapper_key = WRAPPER_RELATIVE
        helper_key = HELPER_RELATIVE
        review_pins = dict(pins)
        if helper_key in review_pins or wrapper_key in review_pins:
            raise RootCloseError("public_scope")
        review_pins[helper_key] = HELPER_SHA256
        review_pins[wrapper_key] = wrapper_sha256
        if len(review_pins) != 35:
            raise RootCloseError("public_scope")

        phase = "review_scope_acquire"
        review_scope = cu.held_public_sources(review_pins, software)
        review_held = review_scope.__enter__()
        report.update(review_scope_entered=True)
        if (
            type(review_scope) is not contextlib._GeneratorContextManager
            or type(getattr(review_scope, "gen", None)) is not types.GeneratorType
            or inspect.getgeneratorstate(review_scope.gen) != inspect.GEN_SUSPENDED
            or review_scope.gen.gi_frame is None
            or review_scope.gen.gi_frame.f_globals is not cu.__dict__
            or review_scope.gen.gi_code is not generator_function.__code__
            or review_scope is original_scope
            or review_scope.gen is original_scope.gen
            or type(review_held) is not tuple
            or len(review_held) != 3
            or type(review_held[0]) is not types.ModuleType
            or type(review_held[1]) is not types.ModuleType
            or type(review_held[2]) is not dict
        ):
            raise RootCloseError("public_scope")
        review_raw = review_held[2]
        software_keys = {str(Path(path)) for path in software}
        expected_keys = {str(ROOT / Path(path)) for path in review_pins} | software_keys
        if set(review_raw) != expected_keys:
            raise RootCloseError("public_scope")
        for relative, digest in review_pins.items():
            value = review_raw.get(str(ROOT / Path(relative)))
            if type(value) is not bytes or len(value) > PUBLIC_LIMIT or _sha(value) != digest:
                raise RootCloseError("public_scope")
        if any(type(review_raw[key]) is not bytes for key in software_keys):
            raise RootCloseError("public_scope")
        review_scope_verified = True
        report["review_public_inputs_verified"] = True
        report["review_software_keys_present"] = len(software_keys) == 3

        # Bind the exact empty registry objects before the only original close.
        registry_snapshot = None

        phase = "source_binding"
        if WRAPPER_NAME not in sys.modules:
            raise RootCloseError("source_binding")
        helper_raw = review_raw[str(ROOT / Path(HELPER_RELATIVE))]
        if len(helper_raw) != HELPER_SIZE or _sha(helper_raw) != HELPER_SHA256:
            raise RootCloseError("source_binding")
        if HELPER_NAME in sys.modules:
            raise RootCloseError("source_binding")
        helper_module = types.ModuleType(HELPER_NAME)
        helper_module.__file__ = str(HELPER_PATH)
        helper_module.__package__ = ""
        helper_module.__cached__ = None
        sys.modules[HELPER_NAME] = helper_module
        try:
            exec(compile(helper_raw, str(HELPER_PATH), "exec", dont_inherit=True), helper_module.__dict__)
        except BaseException:
            sys.modules.pop(HELPER_NAME, None)
            helper_module = None
            raise RootCloseError("source_binding") from None

        phase = "helper_source_binding"
        helper_expected = {}
        helper_module._index(compile(helper_raw, str(HELPER_PATH), "exec", dont_inherit=True), helper_expected)
        for name in (
            "_index",
            "_constant_structure_equal",
            "_code_structure_equal",
            "_function_is_source_bound",
            "_snapshot_result",
            "_snapshot_state",
            "_registry_snapshot",
            "_registries_unchanged",
            "_close_once",
            "_report",
            "close_original_scope",
        ):
            if not helper_module._function_is_source_bound(helper_module.__dict__, name, helper_expected):
                raise RootCloseError("source_binding")

        phase = "wrapper_source_binding"
        wrapper_expected = {}
        helper_module._index(compile(wrapper_raw, str(wrapper_path), "exec", dont_inherit=True), wrapper_expected)
        for name in (
            "_sha",
            "_report",
            "_expected_result",
            "_helper_report_is_success",
            "_expected_public_pins",
            "_result_snapshot",
            "_state_snapshot",
            "_module_map",
            "_verify_original_scope",
            "invoke",
        ):
            if not helper_module._function_is_source_bound(wrapper_module.__dict__, name, wrapper_expected):
                raise RootCloseError("source_binding")
        error_init = wrapper_module.RootCloseError.__init__
        error_init_candidates = wrapper_expected.get("RootCloseError.__init__", ())
        if (
            type(error_init) is not types.FunctionType
            or error_init.__globals__ is not wrapper_module.__dict__
            or error_init.__module__ != WRAPPER_NAME
            or error_init.__qualname__ != "RootCloseError.__init__"
            or len(error_init_candidates) != 1
            or not helper_module._code_structure_equal(error_init.__code__, error_init_candidates[0])
        ):
            raise RootCloseError("source_binding")

        phase = "caller_source_binding"
        caller_raw = raw[str(CALLER_PATH)]
        caller_expected = {}
        helper_module._index(compile(caller_raw, str(CALLER_PATH), "exec", dont_inherit=True), caller_expected)
        for name in ("run", "bind_module", "verify_binding", "load_held", "_source_map_doc"):
            if not helper_module._function_is_source_bound(caller, name, caller_expected):
                raise RootCloseError("source_binding")
        binder = caller.get("bind_module")
        verifier = caller.get("verify_binding")
        if not all(callable(value) for value in (binder, verifier)):
            raise RootCloseError("source_binding")
        phase = "source_binding_records"
        wrapper_binding = binder(wrapper_module, wrapper_raw, wrapper_path, WRAPPER_NAME)
        verifier(wrapper_binding)
        helper_binding = binder(helper_module, helper_raw, HELPER_PATH, HELPER_NAME)
        verifier(helper_binding)
        helper_globals_before = tuple((key, id(value)) for key, value in vars(helper_module).items())
        phase = "helper_contract_binding"
        if (
            helper_module.CALLER_PATH != CALLER_PATH
            or helper_module.CALLER_SIZE != CALLER_SIZE
            or helper_module.CALLER_SHA256 != CALLER_SHA256
            or helper_module.CU_PATH != CU_PATH
            or helper_module.CU_NAME != CU_NAME
            or helper_module.close_original_scope.__globals__ is not helper_module.__dict__
        ):
            raise RootCloseError("source_binding")
        verify_cu = verifier(cu_record)
        if verify_cu is not None:
            raise RootCloseError("source_binding")
        phase = "registry_binding"
        registry_snapshot = helper_module._registry_snapshot(dict(zip(names, modules)))
        if not helper_module._registries_unchanged(registry_snapshot):
            raise RootCloseError("root_binding")
        private_api = vars(modules[9]).get("_API")
        private_api_type = vars(modules[9]).get("_Win32")
        if private_api is None or type(private_api) is not private_api_type or type(private_api_type) is not type:
            raise RootCloseError("root_binding")
        report.update(helper_source_bound=True, original_caller_source_bound=True)
        _attempted_original_scopes.append(original_scope)

        phase = "normal_close"
        called = True
        close_report = helper_module.close_original_scope(caller)
        report["normal_close_invocation_count"] = 1
        if type(close_report) is not dict:
            raise RootCloseError("normal_close")
        report["helper_report"] = close_report
        if not _helper_report_is_success(close_report):
            raise RootCloseError("normal_close")

        phase = "cu_binding_postverify"
        verifier(cu_record)
        phase = "wrapper_binding_postverify"
        verifier(wrapper_binding)
        phase = "helper_binding_postverify"
        phase = "original_scope_postverify"
        if (
            caller.get("ROOT_STATE") is not state
            or caller.get("ROOT_RESULT") is not result
            or _state_snapshot(state) != state_before
            or _result_snapshot(result) != result_before
            or state.get("raw") is not raw
            or not _expected_result(result)
            or any(sys.modules.get(name) is not module for name, module in zip(names, modules))
            or not helper_module._registries_unchanged(registry_snapshot)
            or sys.modules.get(HELPER_NAME) is not helper_module
            or tuple((key, id(value)) for key, value in vars(helper_module).items()) != helper_globals_before
            or helper_module._ATTEMPTED != [original_scope]
            or helper_module._RETAINED
            or any(
                not helper_module._function_is_source_bound(helper_module.__dict__, name, helper_expected)
                for name in (
                    "_index",
                    "_constant_structure_equal",
                    "_code_structure_equal",
                    "_function_is_source_bound",
                    "_snapshot_result",
                    "_snapshot_state",
                    "_registry_snapshot",
                    "_registries_unchanged",
                    "_close_once",
                    "_report",
                    "close_original_scope",
                )
            )
        ):
            raise RootCloseError("postverify")
        if (
            original_scope.gen.gi_frame is not None
            or inspect.getgeneratorstate(original_scope.gen) != inspect.GEN_CLOSED
            or tuple((key, id(value)) for key, value in raw.items()) != raw_before
            or tuple(sorted(software.items())) != software_before
            or helper_module._ATTEMPTED != [original_scope]
            or helper_module._RETAINED
        ):
            raise RootCloseError("postverify")
        phase = "review_scope_close"
        outcome = review_scope.__exit__(None, None, None)
        report["review_scope_normal_close_confirmed"] = (
            outcome is False
            and review_scope.gen.gi_frame is None
            and inspect.getgeneratorstate(review_scope.gen) == inspect.GEN_CLOSED
        )
        if not report["review_scope_normal_close_confirmed"]:
            raise RootCloseError("postverify")
        phase = "review_scope_postverify"
        if (
            caller.get("ROOT_STATE") is not state
            or caller.get("ROOT_RESULT") is not result
            or _state_snapshot(state) != state_before
            or _result_snapshot(result) != result_before
            or tuple((key, id(value)) for key, value in raw.items()) != raw_before
            or tuple(sorted(software.items())) != software_before
            or any(sys.modules.get(name) is not module for name, module in zip(names, modules))
            or not helper_module._registries_unchanged(registry_snapshot)
        ):
            raise RootCloseError("postverify")
        phase = "final_source_postverify"
        if any(
            not helper_module._function_is_source_bound(caller, name, caller_expected)
            for name in ("run", "bind_module", "verify_binding", "load_held", "_source_map_doc")
        ):
            raise RootCloseError("postverify")
        if any(
            not helper_module._function_is_source_bound(wrapper_module.__dict__, name, wrapper_expected)
            for name in (
                "_sha",
                "_report",
                "_expected_result",
                "_helper_report_is_success",
                "_expected_public_pins",
                "_result_snapshot",
                "_state_snapshot",
                "_module_map",
                "_verify_original_scope",
                "invoke",
            )
        ) or not helper_module._code_structure_equal(
            wrapper_module.RootCloseError.__init__.__code__, error_init_candidates[0]
        ):
            raise RootCloseError("postverify")
        verifier(cu_record)
        verifier(wrapper_binding)
        if tuple((key, id(value)) for key, value in vars(helper_module).items()) != helper_globals_before:
            raise RootCloseError("postverify")
        sys.modules.pop(HELPER_NAME, None)
        if HELPER_NAME in sys.modules:
            raise RootCloseError("postverify")
        report.update(
            status="ROOT_REVIEWED_NORMAL_CLOSE_RETURNED",
            phase="complete",
            reason="none",
            original_scope_normal_close_confirmed=True,
            original_result_unchanged=True,
            original_maps_and_state_preserved=True,
        )
        return report
    except BaseException as error:
        code = getattr(error, "code", None)
        if type(code) is not str or code not in {"root_binding", "public_scope", "source_binding", "normal_close", "postverify"}:
            code = "source_or_close_state_unconfirmed"
        report.update(status="BLOCKED", phase=phase, reason=code, normal_close_invocation_count=1 if called else 0)
        if review_scope is not None and not called and review_scope_verified:
            try:
                outcome = review_scope.__exit__(None, None, None)
                report["review_scope_normal_close_confirmed"] = (
                    outcome is False
                    and review_scope.gen.gi_frame is None
                    and inspect.getgeneratorstate(review_scope.gen) == inspect.GEN_CLOSED
                )
            except BaseException:
                report["review_scope_normal_close_confirmed"] = False
        if review_scope is not None and (called or not report["review_scope_normal_close_confirmed"]):
            _RETAINED.append((original_globals, original_scope, review_scope, review_held, review_raw, helper_module, error))
        if helper_module is not None and not called and sys.modules.get(HELPER_NAME) is helper_module:
            sys.modules.pop(HELPER_NAME, None)
        return report

