"""Normal CUv2 source close for consumed R4 host 77310; no Gate retry or host exit."""
import contextlib
import builtins
import hashlib
import inspect
import json
from pathlib import Path
import sys
import types


ROOT = Path("D:/source_code/backtrader")
DRIVER_REL = ".codex-tmp/okx_m01_r7_r4_root_actual_r2_20261009.py"
DRIVER_PIN = (19235, "3520ea0515e2f1fef8e4e70c4e495436cce13d60c1062977c1a22c7c44590f01")
CALLER_REL = "scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r4.py"
CALLER_PIN = (76931, "c081b85b553c3600b3949d1da33d4449b047fa5668d1b7e3ab9426388cf30451")
CALLER_TEST_REL = "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r4_source_fake.py"
CALLER_TEST_PIN = (40982, "d4a42fecb701c3e371798a22db59a3060036d96adb07abaefb2d8669cc2e9741")
CUV2_SNAPSHOT_REL = "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
CUV2_PIN = (2344, "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246")
OBSERVATION_REL = "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-r7-five-module-root-gate-actual-r4-2026-10-09/observation.json"
OBSERVATION_PIN = (3565, "504539719ebc67350de6f1c1bfc2ba3da8b9709c4de668aec149f1dbc39ac689")
MANIFEST_PIN = (12994, "8a84e0bb29e2aabf3338078b66e3e44ef13428b3c334c505300cbf1334486e12")
REVIEW_PIN = (2981, "61887b6d14b5f93ef9ea2a3f8f901cf437916bd9dd9a1ee3e716e4f36f580fbe")
EXPECTED_HEAD = "716ca992dd8a05d7d997d25cd667f212eae5bb1c"
EXPECTED_CU_PATH = Path("D:/temp/iteration41-root-public-custody-v2.py")
ATTESTATION_SCHEMA = "iteration41.okx.m01.r7.r4.source-close-outside-git.v1"
CLOSE_SCHEMA = "iteration41.okx.m01.r7.r4.root-source-close.v1"
RECORD_KEY = "SOURCE_SCOPE_CLOSE_R4_ROOT_RECORD"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _pinned(path, pin):
    raw = Path(path).read_bytes()
    if len(raw) != pin[0] or _sha(raw) != pin[1]:
        raise RuntimeError("public_pin_changed")
    return raw


def _pin_map_digest(public_pins, software_pins):
    value = {
        "public": sorted((str(path), str(pin)) for path, pin in public_pins.items()),
        "software": sorted((str(path), str(pin)) for path, pin in software_pins.items()),
    }
    return _sha(_canonical(value))


def _check_outside_git_attestation(path, nonce_hash, pin_map_sha, pins):
    if Path(path).is_symlink():
        raise RuntimeError("outside_git_attestation_reparse_point")
    raw = Path(path).read_bytes()
    if not 1 <= len(raw) <= 16384:
        raise RuntimeError("outside_git_attestation_size_invalid")
    try:
        value = json.loads(raw)
    except Exception:
        raise RuntimeError("outside_git_attestation_json_invalid") from None
    expected_keys = {
        "schema", "phase", "observer", "host_id", "repo_root", "root_nonce_sha256",
        "git", "commands", "source_pins", "held_pin_map_sha256",
    }
    if type(value) is not dict or set(value) != expected_keys or raw != _canonical(value):
        raise RuntimeError("outside_git_attestation_shape_invalid")
    expected_git = {"branch": "dev", "head": EXPECTED_HEAD, "index_empty": True}
    if (
        type(value["schema"]) is not str
        or type(value["phase"]) is not str
        or type(value["observer"]) is not str
        or type(value["host_id"]) is not int
        or type(value["repo_root"]) is not str
        or type(value["root_nonce_sha256"]) is not str
        or type(value["git"]) is not dict
        or type(value["git"].get("branch")) is not str
        or type(value["git"].get("head")) is not str
        or type(value["git"].get("index_empty")) is not bool
        or type(value["commands"]) is not list
        or type(value["source_pins"]) is not list
        or type(value["held_pin_map_sha256"]) is not str
        or any(type(item) is not str for item in value["commands"])
        or any(
            type(row) is not dict
            or set(row) != {"name", "path", "bytes", "sha256"}
            or type(row["name"]) is not str
            or type(row["path"]) is not str
            or type(row["bytes"]) is not int
            or type(row["sha256"]) is not str
            for row in value["source_pins"]
        )
    ):
        raise RuntimeError("outside_git_attestation_types_invalid")
    if (
        value["schema"] != ATTESTATION_SCHEMA
        or value["phase"] != "before_source_close"
        or value["observer"] != "root_outside_host"
        or value["host_id"] != 77310
        or value["repo_root"] != str(ROOT)
        or value["root_nonce_sha256"] != nonce_hash
        or value["git"] != expected_git
        or value["commands"] != [
            "git branch --show-current",
            "git rev-parse HEAD",
            "git diff --cached --name-only",
        ]
        or value["source_pins"] != pins
        or value["held_pin_map_sha256"] != pin_map_sha
    ):
        raise RuntimeError("outside_git_attestation_binding_invalid")
    return _sha(raw), len(raw)


def _clean_resource_facts(facts):
    return bool(
        type(facts) is dict
        and facts.get("schema") == "iteration41.okx.m01.root-helper-lifecycle-gate.v6"
        and facts.get("status") == "OUTPUT_MISMATCH"
        and facts.get("phase") == "complete"
        and facts.get("stdout_matches_fixed") is False
        and facts.get("cleanup_confirmed") is True
        and facts.get("process_created") is True
        and facts.get("job_assigned_before_resume") is True
        and facts.get("resumed") is True
        and facts.get("process_wait_succeeded") is True
        and facts.get("process_reaped_after_cleanup") is True
        and facts.get("process_exit_code_zero") is True
        and facts.get("process_exit_code_present") is True
        and facts.get("job_count_observations") == [
            ["job_count_assign", 1], ["job_count_resume", 1],
            ["job_count_after_exit", 1], ["job_count_after_exit", 0],
            ["job_count_after_cleanup", 0],
        ]
        and facts.get("job_zero_after_exit") is True
        and facts.get("job_zero_after_cleanup") is True
        and facts.get("job_nonzero_after_exit") is False
        and facts.get("job_nonzero_after_cleanup") is False
        and facts.get("wait_results") == [True]
        and facts.get("cleanup_wait_attempted") is False
        and facts.get("cleanup_wait_succeeded") is False
        and facts.get("job_count_after_cleanup_observed") is True
        and facts.get("job_count_after_cleanup_error") is None
        and facts.get("job_count_observations_truncated") is False
        and facts.get("all_observed_handles_closed") is True
        and facts.get("handle_close_calls") == 11
        and facts.get("handle_close_failures") == 0
        and facts.get("stdin_close_succeeded") is True
        and facts.get("stdout_eof") is True
        and facts.get("stdout_read_done") is True
        and facts.get("stdout_read_error") is False
        and facts.get("stdout_overflow") is False
        and facts.get("stderr_eof") is True
        and facts.get("stderr_empty") is True
        and facts.get("stderr_read_done") is True
        and facts.get("stderr_read_error") is False
        and facts.get("stderr_overflow") is False
        and facts.get("stdout_thread_joined") is True
        and facts.get("stderr_thread_joined") is True
        and facts.get("runtime_registry_empty_after") is True
        and facts.get("runtime_registry_empty_before") is True
        and facts.get("runtime_registry_unchanged") is True
        and facts.get("reader_retained_contexts_empty_before") is True
        and facts.get("reader_retained_contexts_empty_after") is True
        and facts.get("reader_retained_registry_identity_unchanged") is True
        and facts.get("reader_retained_context_count_after") == 0
        and facts.get("reader_retained_context_count_captured_after") == 0
        and facts.get("source_functions_restored") is True
        and facts.get("module_bindings_unchanged_after") is True
        and facts.get("source_bytes_held") == 5
        and facts.get("reader_source_pinned") is True
        and facts.get("supervisor_source_pinned") is True
        and facts.get("worker_source_pinned") is True
        and facts.get("reader_check_failed") is False
        and facts.get("reader_exception_seen") is False
        and facts.get("retained_context") is False
        and facts.get("error_category") is None
        and facts.get("error_code") is None
        and facts.get("native_failure_phase") is None
        and facts.get("winerror") is None
        and facts.get("termination_requested") is False
        and facts.get("source_fake_only") is False
        and facts.get("production_acceptance") is False
    )


def _source_pin_rows(root_namespace):
    return [
        {"name": "root_driver", "path": DRIVER_REL, "bytes": DRIVER_PIN[0], "sha256": DRIVER_PIN[1]},
        {"name": "caller", "path": CALLER_REL, "bytes": CALLER_PIN[0], "sha256": CALLER_PIN[1]},
        {"name": "caller_test", "path": CALLER_TEST_REL, "bytes": CALLER_TEST_PIN[0], "sha256": CALLER_TEST_PIN[1]},
        {"name": "cuv2_snapshot", "path": CUV2_SNAPSHOT_REL, "bytes": CUV2_PIN[0], "sha256": CUV2_PIN[1]},
        {"name": "observation", "path": OBSERVATION_REL, "bytes": OBSERVATION_PIN[0], "sha256": OBSERVATION_PIN[1]},
        {"name": "candidate_manifest", "path": "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-r7-five-module-root-gate-preparation-r2-2026-10-09/candidate-pins.json", "bytes": MANIFEST_PIN[0], "sha256": MANIFEST_PIN[1]},
        {"name": "caller_review", "path": root_namespace["R4_REVIEW_RELATIVE"], "bytes": REVIEW_PIN[0], "sha256": REVIEW_PIN[1]},
    ]


def close_source_scope(root_namespace):
    def need(value, code):
        if not value:
            raise RuntimeError(code)

    state = root_namespace["ROOT_STATE"]
    result = root_namespace["ACTUAL_RESULT"]
    caller, cu = state["caller"], state["cu"]
    need(RECORD_KEY not in root_namespace, "close_already_started")
    need(
        result.get("schema") == "iteration41.okx.m01.r7_root_caller.v3"
        and result.get("status") == "BLOCKED"
        and result.get("reason") == "gate_cleanup_not_certain"
        and result.get("failure_phase") == "post_binding_check"
        and result.get("gate_invocations") == 1
        and result.get("source_count") == 34
        and result.get("public_source_count") == 31
        and result.get("software_source_count") == 3
        and result.get("source_pre_post_bindings_verified") is True
        and result.get("required_source_execution_verified") is True
        and result.get("gate_cleanup_facts_verified") is False
        and result.get("outer_normal_postverify_and_close") is False
        and result.get("software_pins_verified_by_cuv2") is True
        and result.get("software_payload_bytes_returned_to_caller") is True
        and result.get("software_payload_bytes_retained_in_caller_state") is True
        and result.get("software_payload_bytes_sha256_rechecked_by_caller") is True
        and result.get("scope_exit_attempted") is False
        and result.get("scope_exit_confirmed") is False
        and result.get("scope_exit_state") == "still_open"
        and result.get("host_exit_permitted") is False
        and result.get("retained_python_references") is True
        and result.get("account_provider_operations") is False
        and result.get("private_inputs_read") is False
        and result.get("formal_m01_pass_count") == 0
        and state["started"] is True
        and state["returned"] is True
        and state["exit_permitted"] is False,
        "not_exact_r4_gate_cleanup_failure",
    )

    before, rows, public_raw, public_pins, caller_raw, cu_raw, software, expected, manifest_raw, review_raw = (
        root_namespace["PRECHECK"]
    )
    root, cu_path = root_namespace["ROOT"], root_namespace["CU_PATH"]
    need(
        root == ROOT
        and cu_path == EXPECTED_CU_PATH
        and before["branch"] == "dev"
        and before["head"] == EXPECTED_HEAD
        and before["index_empty"] is True,
        "fixed_source_or_initial_git_state_changed",
    )
    need(
        len(rows) == len(public_raw) == len(public_pins) == 31
        and set(public_raw) == set(public_pins),
        "public_precheck_map_changed",
    )
    need(
        (len(caller_raw), _sha(caller_raw)) == CALLER_PIN
        and (len(cu_raw), _sha(cu_raw)) == CUV2_PIN
        and (len(review_raw), _sha(review_raw)) == REVIEW_PIN
        and (len(manifest_raw), _sha(manifest_raw)) == MANIFEST_PIN
        and root_namespace["EXPECTED_CALLER"] == CALLER_PIN
        and root_namespace["EXPECTED_CALLER_TEST"] == CALLER_TEST_PIN
        and root_namespace["EXPECTED_CU"] == CUV2_PIN
        and root_namespace["EXPECTED_R4_REVIEW"] == REVIEW_PIN,
        "held_public_source_pin_changed",
    )
    nonce_hash = result.get("root_nonce_sha256")
    need(
        type(state.get("nonce")) is str
        and _sha(state["nonce"].encode("ascii")) == nonce_hash
        and state["precheck"] == {
            "public_count": 31,
            "software_count": 3,
            "held_count": 34,
            "caller_bytes": CALLER_PIN[0],
            "caller_sha256": CALLER_PIN[1],
            "caller_test_sha256": CALLER_TEST_PIN[1],
            "caller_review_sha256": REVIEW_PIN[1],
            "git": before,
        },
        "root_nonce_or_precheck_changed",
    )
    need(
        software
        == {
            "C:/anaconda3/python.exe": "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642",
            "C:/anaconda3/python311.dll": "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00",
            str(cu_path).replace(chr(92), "/"): root_namespace["EXPECTED_CU"][1],
        },
        "software_precheck_map_changed",
    )
    manifest_rows = json.loads(manifest_raw)["public_pins"]
    expected_rows = []
    for source_row in manifest_rows:
        if source_row["path"] == root_namespace["R2_CALLER_RELATIVE"]:
            source_row = dict(source_row)
            source_row.update(
                path=root_namespace["CALLER_RELATIVE"],
                bytes=root_namespace["EXPECTED_CALLER"][0],
                sha256=root_namespace["EXPECTED_CALLER"][1],
            )
        elif source_row["path"] == root_namespace["R2_CALLER_TEST_RELATIVE"]:
            source_row = dict(source_row)
            source_row.update(
                path=root_namespace["CALLER_TEST_RELATIVE"],
                bytes=root_namespace["EXPECTED_CALLER_TEST"][0],
                sha256=root_namespace["EXPECTED_CALLER_TEST"][1],
            )
        expected_rows.append(source_row)
    need(
        rows == expected_rows
        and public_pins == {source_row["path"]: source_row["sha256"] for source_row in rows}
        and all(
            len(public_raw[source_row["path"]]) == source_row["bytes"]
            and hashlib.sha256(public_raw[source_row["path"]]).hexdigest()
            == source_row["sha256"]
            for source_row in rows
        ),
        "public_manifest_binding_changed",
    )

    source_pins = _source_pin_rows(root_namespace)
    for item in source_pins:
        _pinned(root / item["path"], (item["bytes"], item["sha256"]))
    observation_path = root / OBSERVATION_REL
    observation_raw = _pinned(observation_path, OBSERVATION_PIN)
    observation = json.loads(observation_raw)
    need(type(observation) is dict and observation == result, "r4_observation_result_changed")
    need(
        result.get("gate_result", {}).get("status") == "OUTPUT_MISMATCH"
        and result.get("gate_result", {}).get("stdout_matches_fixed") is False
        and _clean_resource_facts(result.get("gate_result"))
        and result.get("gate_cleanup_facts_verified") is False,
        "r4_gate_resource_facts_not_exact",
    )
    output_dir = root_namespace["OUTPUT"]
    need(
        Path(output_dir) == observation_path.parent
        and Path(output_dir).is_dir(),
        "r4_output_directory_changed",
    )
    pre_attestation = Path(output_dir) / "root-git-attestation-before-close.json"
    post_attestation = Path(output_dir) / "root-git-attestation-after-close.json"
    output = Path(output_dir) / "source-close-root.json"
    need(
        pre_attestation.is_file()
        and not pre_attestation.is_symlink()
        and not post_attestation.exists()
        and not output.exists(),
        "source_close_attestation_or_output_not_fresh",
    )
    pin_map_sha = _pin_map_digest(public_pins, software)
    attestation_sha, attestation_size = _check_outside_git_attestation(
        pre_attestation, nonce_hash, pin_map_sha, source_pins
    )

    registry = state["retained_registry"]
    need(
        caller._RETAINED_CONTEXTS is registry
        and len(registry) == 1
        and sys.modules.get(caller.__name__) is caller
        and sys.modules.get(cu.__name__) is cu,
        "retained_registry_or_module_alias_changed",
    )
    row = registry[0]
    need(type(row) is tuple and len(row) == 16, "retained_shape_changed")
    need(
        row[0] is cu
        and Path(cu.__file__) == cu_path
        and Path(cu.__spec__.origin) == cu_path
        and row[1] is cu.held_public_sources
        and row[2] is cu.held_public_sources.__wrapped__
        and row[3] is cu_raw,
        "original_cu_identity_changed",
    )
    gate, modules = row[10], row[11]
    need(
        isinstance(gate, types.ModuleType)
        and type(modules) is dict
        and set(modules) == {"current_types", "contract", "worker", "supervisor", "reader"}
        and type(row[12]) is tuple and len(row[12]) == 5
        and type(row[13]) is tuple and type(row[14]) is tuple,
        "gate_or_modules_retention_shape_changed",
    )

    def verify_root_bindings():
        root_namespace["verify_caller"](caller, caller_raw, expected, initial=False)
        root_namespace["verify_snapshot"](caller, state["root_binding"])
        original = root_namespace["caller_globals"]
        need(
            set(caller.__dict__) == set(original)
            and all(
                caller.__dict__[name] is value
                for name, value in original.items()
                if name != "_INVOCATION_STARTED"
            )
            and caller.__dict__.get("_INVOCATION_STARTED") is True,
            "root_caller_global_identity_changed",
        )

    verify_root_bindings()
    snapshots = caller._bind_cuv2_method(cu, cu_path, cu_raw, root)
    need(snapshots[0] is row[1] and snapshots[1] is row[2], "cu_binding_changed")
    scope, generator, globals_ref = row[8], row[5], row[6]
    need(
        type(scope) is contextlib._GeneratorContextManager
        and type(scope.__exit__) is types.MethodType
        and scope.__exit__.__self__ is scope
        and scope.__exit__.__func__ is contextlib._GeneratorContextManager.__exit__
        and scope.gen is generator
        and type(generator) is types.GeneratorType
        and generator.gi_frame is not None
        and generator.gi_frame.f_globals is cu.__dict__
        and globals_ref is cu.__dict__
        and generator.gi_code is row[2].__code__,
        "original_scope_changed",
    )
    need(
        row[15] == nonce_hash
        and caller._cuv2_function_bindings_unchanged(cu, row[4]) is True,
        "cuv2_function_bindings_changed_before_close",
    )

    expected_public = {str(root / path): pin for path, pin in public_pins.items()}
    expected_software = {str(Path(path)): pin for path, pin in software.items()}
    expected_pins = {**expected_public, **expected_software}
    held = row[9]
    need(
        len(expected_public) == 31
        and len(expected_software) == 3
        and len(expected_pins) == 34
        and type(held) is tuple
        and len(held) == 3
        and type(held[2]) is dict
        and set(held[2]) == set(expected_pins)
        and len(held[2]) == 34
        and type(row[7]) is dict
        and set(row[7]) == set(held[2])
        and all(row[7][key] is value for key, value in held[2].items()),
        "held_pins_changed",
    )
    raw_map = held[2]
    for relative, pin in public_pins.items():
        path = str(root / relative)
        need(
            type(raw_map[path]) is bytes
            and _sha(raw_map[path]) == pin
            and _pinned(Path(path), (len(raw_map[path]), pin)) == raw_map[path],
            "held_or_current_public_pin_changed",
        )
    for relative, raw in public_raw.items():
        need(raw_map[str(root / relative)] == raw, "held_public_bytes_changed")
    locals_ref = generator.gi_frame.f_locals
    need(
        caller._verify_literal_module_globals(cu, cu_raw) is None
        and cu.__dict__.get("__builtins__") is builtins.__dict__
        and cu.__dict__.get("ExitStack") is contextlib.ExitStack
        and cu.__dict__.get("contextmanager") is contextlib.contextmanager
        and cu.__dict__.get("Path") is Path
        and cu.__dict__.get("hashlib") is hashlib
        and cu.__dict__.get("sys") is sys
        and cu.__dict__.get("types") is types,
        "cuv2_literal_or_builtin_binding_changed",
    )
    cu_globals_before = tuple(
        (name, value, caller._safe_value_snapshot(value))
        for name, value in cu.__dict__.items()
    )
    need(
        locals_ref["raw_bytes"] is raw_map
        and type(locals_ref["identities"]) is dict
        and len(locals_ref["identities"]) == 34
        and set(locals_ref["identities"]) == set(expected_pins)
        and {str(path): pin for path, pin in locals_ref["all_pins"].items()} == expected_pins,
        "generator_hold_changed",
    )
    need(
        all(type(raw_map[path]) is bytes for path in expected_software),
        "held_software_entry_shape_changed",
    )

    need(
        caller._snapshots_unchanged(gate, (row[14], *row[12])) is True
        and caller._gate_snapshot_unchanged(row[13]) is True,
        "gate_or_production_binding_changed_before_close",
    )
    module_paths = {}
    module_items = tuple(modules.items())
    for key, module in modules.items():
        spec = caller.MODULE_SPECS[key]
        path = root / spec[1]
        module_paths[key] = path
        need(
            isinstance(module, types.ModuleType)
            and sys.modules.get(module.__name__) is module
            and Path(module.__file__) == path
            and Path(module.__spec__.origin) == path,
            "production_module_origin_or_alias_changed",
        )
        rel = spec[1]
        source = raw_map[str(path)]
        need(
            _sha(source) == public_pins[rel]
            and _pinned(path, (len(source), public_pins[rel])) == source,
            "production_module_source_changed",
        )
    gate_path = root / caller.GATE_RELATIVE
    gate_raw = raw_map[str(gate_path)]
    need(
        Path(gate.__file__) == gate_path
        and Path(gate.__spec__.origin) == gate_path
        and _sha(gate_raw) == public_pins[caller.GATE_RELATIVE]
        and _pinned(gate_path, (len(gate_raw), public_pins[caller.GATE_RELATIVE])) == gate_raw
        and modules["reader"].job_supervisor is modules["supervisor"]
        and modules["reader"].worker is modules["worker"]
        and modules["reader"].current_types is modules["current_types"]
        and modules["supervisor"].worker is modules["worker"]
        and modules["supervisor"].current_types is modules["current_types"]
        and modules["supervisor"].contract is modules["contract"],
        "gate_or_production_composition_changed",
    )
    registry_refs = tuple(
        (module, registry_name, module.__dict__.get(registry_name))
        for module, registry_name in (
        (gate, "_ORPHANED_GATE_CONTEXTS"),
        (modules["supervisor"], "_ORPHANED_RUNTIME_HANDLE_SETS"),
        (modules["reader"], "_ROOT_HELPER_RETAINED_CONTEXTS"),
        )
    )
    need(
        all(type(value) is list and not value for _module, _name, value in registry_refs),
        "gate_or_production_registry_not_empty",
    )

    packet_manifest = root_namespace["PACKET"] / "candidate-pins.json"
    review_path = root / root_namespace["R4_REVIEW_RELATIVE"]
    need(
        root_namespace["read_pinned"](
            packet_manifest, 12994,
            MANIFEST_PIN[1],
        ) == manifest_raw
        and root_namespace["read_pinned"](
            review_path, *REVIEW_PIN
        ) == review_raw,
        "review_packet_pin_changed",
    )
    need(output.parent.is_dir() and not output.exists(), "close_output_not_fresh")

    result_before = json.dumps(result, sort_keys=True, separators=(",", ":"))
    state_before = tuple(state.items())
    record = {
        "schema": CLOSE_SCHEMA,
        "scope": scope,
        "generator": generator,
        "held": held,
        "row": row,
        "result": result,
        "exit_started": False,
        "exit_returned": False,
        "normal_close_verified": False,
    }
    record.update(
        outside_git_pre_attestation_sha256=attestation_sha,
        outside_git_pre_attestation_bytes=attestation_size,
        outside_git_pre_attestation_path=str(pre_attestation),
        gate_cleanup_status="OUTPUT_MISMATCH",
        gate_stdout_matches_fixed=False,
        gate_resources_clean_for_local_process_only=True,
        gate_success=False,
        exit_started=False,
        receipt_written=False,
    )
    root_namespace[RECORD_KEY] = record
    record["exit_started"] = True
    exit_result = contextlib._GeneratorContextManager.__exit__(scope, None, None, None)
    record["exit_returned"] = True
    need(
        exit_result is False
        and scope.gen is generator
        and inspect.getgeneratorstate(generator) == "GEN_CLOSED"
        and generator.gi_frame is None,
        "normal_close_not_proven",
    )

    need(
        caller._RETAINED_CONTEXTS is registry
        and len(registry) == 1
        and registry[0] is row
        and row[8] is scope
        and row[9] is held
        and row[7] is not raw_map
        and set(row[7]) == set(raw_map)
        and all(row[7][key] is value for key, value in raw_map.items()),
        "historical_registry_or_row_changed",
    )
    verify_root_bindings()
    need(
        caller._cuv2_function_bindings_unchanged(cu, row[4])
        and caller._snapshots_unchanged(gate, (row[14], *row[12])) is True
        and caller._gate_snapshot_unchanged(row[13]) is True
        and root_namespace["ACTUAL_RESULT"] is result
        and json.dumps(result, sort_keys=True, separators=(",", ":")) == result_before
        and len(state) == len(state_before)
        and all(state.get(name) is value for name, value in state_before),
        "cuv2_or_original_result_changed",
    )
    need(
        sys.modules.get(caller.__name__) is caller
        and sys.modules.get(cu.__name__) is cu
        and Path(cu.__file__) == cu_path
        and Path(cu.__spec__.origin) == cu_path
        and tuple(modules.items()) == module_items
        and all(
            sys.modules.get(module.__name__) is module
            and Path(module.__file__) == module_paths[key]
            and Path(module.__spec__.origin) == module_paths[key]
            for key, module in module_items
        )
        and sys.modules.get(gate.__name__) is gate
        and Path(gate.__file__) == gate_path
        and Path(gate.__spec__.origin) == gate_path
        and all(
            module.__dict__.get(name) is value and type(value) is list and not value
            for module, name, value in registry_refs
        )
        and caller._bind_cuv2_method(cu, cu_path, cu_raw, root)[0] is row[1],
        "cuv2_module_or_method_postclose_changed",
    )
    need(caller._RETAINED_CONTEXTS is registry and registry[0] is row, "retained_row_changed")
    need(
        set(cu.__dict__) == {name for name, _value, _snapshot in cu_globals_before}
        and all(
            cu.__dict__.get(name) is value
            and caller._safe_value_snapshot(cu.__dict__.get(name)) == snapshot
            for name, value, snapshot in cu_globals_before
        )
        and caller._verify_literal_module_globals(cu, cu_raw) is None,
        "cuv2_global_bindings_changed_during_close",
    )
    for source_row in rows:
        relative = source_row["path"]
        need((root / relative).read_bytes() == public_raw[relative], "public_source_post_changed")
    for relative, pin in public_pins.items():
        path = root / relative
        need(
            _sha(path.read_bytes()) == pin
            and _sha(raw_map[str(path)]) == pin,
            "public_source_post_pin_changed",
        )
    need(
        type(row[7]) is dict
        and set(row[7]) == set(raw_map)
        and all(row[7][key] is value for key, value in raw_map.items()),
        "original_held_map_reference_changed",
    )
    need(
        root_namespace["read_pinned"](
            packet_manifest, 12994,
            MANIFEST_PIN[1],
        ) == manifest_raw
        and root_namespace["read_pinned"](
            review_path, *REVIEW_PIN
        ) == review_raw,
        "postclose_source_changed",
    )

    record["normal_close_verified"] = True
    observation = {
        "schema": record["schema"],
        "status": "SOURCE_SCOPE_NORMAL_CLOSE_RETURNED",
        "caller_failure_reason": "gate_cleanup_not_certain",
        "caller_failure_phase": "post_binding_check",
        "gate_result_status": "OUTPUT_MISMATCH",
        "gate_stdout_matches_fixed": False,
        "gate_resource_cleanup_observations_match": True,
        "gate_success": False,
        "public_pins_rechecked_by_close_helper": 31,
        "software_pins_rechecked_by_close_helper": 0,
        "software_pins_rechecked_by_original_cuv2_normal_exit": 3,
        "held_source_sha256_pins_rechecked_by_close_helper": 31,
        "held_software_bytes_rehashed_by_close_helper": False,
        "software_raw_entries_returned_in_original_held_tuple": 3,
        "normal_postverify_and_close": True,
        "contextmanager_exit_returned_false": True,
        "generator_closed": True,
        "original_reference_and_result_preserved": True,
        "retained_python_row_preserved": True,
        "original_caller_invocation_consumed": True,
        "gate_invocations": 1,
        "production_gate_and_five_modules_retained": True,
        "outside_git_pre_attestation_sha256": attestation_sha,
        "outside_git_post_attestation_required": True,
        "host_exit_permitted_by_original_result": False,
        "provider_account_acceptance": False,
        "private_inputs_read": False,
        "formal_m01_pass_count": 0,
        "host_exit_permitted_by_this_receipt": False,
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(observation, sort_keys=True, separators=(",", ":")) + "\n")
    record["receipt_written"] = True
    return observation
