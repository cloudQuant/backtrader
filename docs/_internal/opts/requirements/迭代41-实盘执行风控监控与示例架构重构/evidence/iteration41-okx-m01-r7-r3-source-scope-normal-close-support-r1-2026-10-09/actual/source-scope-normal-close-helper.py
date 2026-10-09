"""Normal source-context close after the consumed R3 caller stopped in source custody."""
import contextlib
import hashlib
import inspect
import json
from pathlib import Path
import sys
import types


def close_source_scope(root_namespace):
    def need(value, code):
        if not value:
            raise RuntimeError(code)

    state = root_namespace["ROOT_STATE"]
    result = root_namespace["ACTUAL_RESULT"]
    caller, cu = state["caller"], state["cu"]
    need(root_namespace.get("SOURCE_SCOPE_CLOSE_R3_ROOT_RECORD") is None, "close_already_started")
    need(
        result.get("schema") == "iteration41.okx.m01.r7_root_caller.v2"
        and result.get("status") == "BLOCKED"
        and result.get("reason") == "cuv2_source_pin_mismatch"
        and result.get("failure_phase") == "source_custody"
        and result.get("gate_invocations") == 0
        and result.get("source_count") == 0
        and result.get("public_source_count") == 0
        and result.get("software_source_count") == 0
        and result.get("software_pins_verified_by_cuv2") is True
        and result.get("software_payload_bytes_returned_to_caller") is True
        and result.get("software_payload_bytes_retained_in_caller_state") is True
        and result.get("software_payload_bytes_sha256_rechecked_by_caller") is False
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
        "not_exact_r3_pregate_failure",
    )

    before, rows, public_raw, public_pins, caller_raw, cu_raw, software, expected, manifest_raw, review_raw = (
        root_namespace["PRECHECK"]
    )
    root, cu_path = root_namespace["ROOT"], root_namespace["CU_PATH"]
    need(
        root == Path("D:/source_code/backtrader")
        and cu_path == Path("D:/temp/iteration41-root-public-custody-v2.py")
        and before["branch"] == "dev"
        and before["head"] == root_namespace["EXPECTED_HEAD"]
        and before["index_empty"] is True,
        "fixed_source_or_git_state_changed",
    )
    need(
        len(rows) == len(public_raw) == len(public_pins) == 31
        and set(public_raw) == set(public_pins),
        "public_precheck_map_changed",
    )
    need(
        (len(caller_raw), hashlib.sha256(caller_raw).hexdigest())
        == root_namespace["EXPECTED_CALLER"]
        and (len(cu_raw), hashlib.sha256(cu_raw).hexdigest())
        == root_namespace["EXPECTED_CU"]
        and (len(review_raw), hashlib.sha256(review_raw).hexdigest())
        == root_namespace["EXPECTED_R3_REVIEW"]
        and (len(manifest_raw), hashlib.sha256(manifest_raw).hexdigest())
        == (12994, "8a84e0bb29e2aabf3338078b66e3e44ef13428b3c334c505300cbf1334486e12"),
        "held_source_pin_changed",
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

    registry = state["retained_registry"]
    need(caller._RETAINED_CONTEXTS is registry and len(registry) == 1, "retained_registry_changed")
    row = registry[0]
    need(type(row) is tuple and len(row) == 16, "retained_shape_changed")
    need(
        row[0] is cu
        and row[1] is cu.held_public_sources
        and row[2] is cu.held_public_sources.__wrapped__
        and row[3] is cu_raw,
        "original_cu_identity_changed",
    )
    need(
        row[10] is None
        and type(row[11]) is dict
        and not row[11]
        and row[12] == ()
        and row[13] is None and row[14] == (),
        "gate_or_modules_entered",
    )
    prefixes = (
        "_certification",
        "_m01_readonly_monitor_v2",
        "_m01_readonly_monitor_v3",
        "_root_m01_r7_gate_",
    )
    need(not any(name.startswith(prefixes) for name in sys.modules), "runtime_namespace_present")

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
    need(root_namespace["git_state"]() == before, "preclose_git_changed")
    snapshots = caller._bind_cuv2_method(cu, cu_path, cu_raw, root)
    need(snapshots[0] is row[1] and snapshots[1] is row[2], "cu_binding_changed")
    scope, generator, globals_ref = row[8], row[5], row[6]
    need(
        type(scope) is contextlib._GeneratorContextManager
        and scope.gen is generator
        and type(generator) is types.GeneratorType
        and generator.gi_frame is not None
        and generator.gi_frame.f_globals is cu.__dict__
        and globals_ref is cu.__dict__
        and generator.gi_code is row[2].__code__,
        "original_scope_changed",
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
        and row[7] == held[2],
        "held_pins_changed",
    )
    raw_map = held[2]
    for path, pin in expected_pins.items():
        need(
            type(raw_map[path]) is bytes
            and hashlib.sha256(raw_map[path]).hexdigest() == pin
            and hashlib.sha256(Path(path).read_bytes()).hexdigest() == pin,
            "held_or_current_pin_changed",
        )
    for relative, raw in public_raw.items():
        need(raw_map[str(root / relative)] == raw, "held_public_bytes_changed")
    locals_ref = generator.gi_frame.f_locals
    need(
        locals_ref["raw_bytes"] is raw_map
        and len(locals_ref["identities"]) == 34
        and {str(path): pin for path, pin in locals_ref["all_pins"].items()} == expected_pins,
        "generator_hold_changed",
    )

    packet_manifest = root_namespace["PACKET"] / "candidate-pins.json"
    review_path = root / root_namespace["R3_REVIEW_RELATIVE"]
    need(
        root_namespace["read_pinned"](
            packet_manifest, 12994,
            "8a84e0bb29e2aabf3338078b66e3e44ef13428b3c334c505300cbf1334486e12",
        ) == manifest_raw
        and root_namespace["read_pinned"](
            review_path, *root_namespace["EXPECTED_R3_REVIEW"]
        ) == review_raw,
        "review_packet_pin_changed",
    )
    output = root_namespace["OUTPUT"] / "root-source-close-observation.json"
    need(output.parent.is_dir() and not output.exists(), "close_output_not_fresh")

    result_before = json.dumps(result, sort_keys=True, separators=(",", ":"))
    state_before = tuple(state.items())
    record = {
        "schema": "iteration41.okx.m01.r7.r3.root-source-close.v1",
        "scope": scope,
        "generator": generator,
        "held": held,
        "row": row,
        "result": result,
        "exit_started": False,
        "exit_returned": False,
        "normal_close_verified": False,
    }
    root_namespace["SOURCE_SCOPE_CLOSE_R3_ROOT_RECORD"] = record
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
        and row[7] == raw_map,
        "historical_registry_or_row_changed",
    )
    verify_root_bindings()
    need(
        caller._cuv2_function_bindings_unchanged(cu, row[4])
        and root_namespace["ACTUAL_RESULT"] is result
        and json.dumps(result, sort_keys=True, separators=(",", ":")) == result_before
        and len(state) == len(state_before)
        and all(state.get(name) is value for name, value in state_before),
        "cuv2_or_original_result_changed",
    )
    need(caller._RETAINED_CONTEXTS is registry and registry[0] is row, "retained_row_changed")
    for source_row in rows:
        relative = source_row["path"]
        need((root / relative).read_bytes() == public_raw[relative], "public_source_post_changed")
    for path, pin in expected_pins.items():
        need(hashlib.sha256(Path(path).read_bytes()).hexdigest() == pin, "source_post_pin_changed")
    need(
        root_namespace["read_pinned"](
            packet_manifest, 12994,
            "8a84e0bb29e2aabf3338078b66e3e44ef13428b3c334c505300cbf1334486e12",
        ) == manifest_raw
        and root_namespace["read_pinned"](
            review_path, *root_namespace["EXPECTED_R3_REVIEW"]
        ) == review_raw
        and root_namespace["git_state"]() == before,
        "postclose_source_or_git_changed",
    )

    record["normal_close_verified"] = True
    observation = {
        "schema": record["schema"],
        "status": "SOURCE_SCOPE_NORMAL_CLOSE_RETURNED",
        "caller_failure_reason": "cuv2_source_pin_mismatch",
        "caller_failure_phase": "source_custody",
        "public_pins_rechecked_by_close_helper": 31,
        "software_pins_rechecked_by_close_helper": 3,
        "held_source_sha256_pins_rechecked_by_close_helper": 34,
        "software_raw_entries_returned_in_original_held_tuple": 3,
        "normal_postverify_and_close": True,
        "generator_closed": True,
        "original_reference_and_result_preserved": True,
        "retained_python_row_preserved": True,
        "original_caller_invocation_consumed": True,
        "gate_invocations": 0,
        "production_gate_or_modules_loaded": False,
        "provider_account_acceptance": False,
        "private_inputs_read": False,
        "formal_m01_pass_count": 0,
        "host_exit_permitted_by_this_receipt": False,
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(observation, indent=2) + "\n")
    return observation
