"""Normal source-context close after the consumed R2 caller stopped before Gate loading."""
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

    state = root_namespace['ROOT_STATE']
    result = root_namespace['ACTUAL_RESULT']
    caller = state['caller']
    cu = state['cu']
    need(root_namespace.get('SOURCE_SCOPE_CLOSE_ROOT_RECORD') is None, 'close_already_started')
    need(result['reason'] == 'cuv2_source_set_mismatch' and result['failure_phase'] == 'source_custody'
         and result['gate_invocations'] == 0 and state['returned'] is True,
         'not_exact_pregate_failure')
    registry = state['retained_registry']
    need(caller._RETAINED_CONTEXTS is registry and len(registry) == 1, 'retained_registry_changed')
    held_row = registry[0]
    need(type(held_row) is tuple and len(held_row) == 16, 'retained_shape_changed')
    need(held_row[0] is cu and held_row[1] is cu.held_public_sources
         and held_row[2] is cu.held_public_sources.__wrapped__, 'original_cu_identity_changed')
    need(held_row[10] is None and held_row[11] == {} and held_row[12] == ()
         and held_row[13] is None and held_row[14] == (), 'gate_or_modules_entered')
    need(not any(name.startswith(('_certification', '_m01_readonly_monitor_v2',
         '_m01_readonly_monitor_v3', '_root_m01_r7_gate_')) for name in sys.modules),
         'runtime_namespace_present')
    before, rows, public_raw, public_pins, caller_raw, cu_raw, software, expected = root_namespace['PRECHECK']
    need(held_row[3] is cu_raw, 'cu_raw_identity_changed')
    root_namespace['verify_caller'](caller, caller_raw, expected, initial=False)
    root_namespace['verify_snapshot'](caller, state['root_binding'])
    root_namespace['check'](root_namespace['git_state']() == before, 'git_changed')
    snapshots = caller._bind_cuv2_method(cu, root_namespace['CU_PATH'], cu_raw, root_namespace['ROOT'])
    need(snapshots[0] is held_row[1] and snapshots[1] is held_row[2], 'cu_binding_changed')
    scope, generator, globals_ref = held_row[8], held_row[5], held_row[6]
    need(type(scope) is contextlib._GeneratorContextManager and scope.gen is generator
         and type(generator) is types.GeneratorType and generator.gi_frame is not None
         and generator.gi_frame.f_globals is cu.__dict__ and globals_ref is cu.__dict__
         and generator.gi_code is held_row[2].__code__, 'original_scope_changed')
    expected_pins = {str(root_namespace['ROOT'] / path): pin for path, pin in public_pins.items()}
    expected_pins.update({str(Path(path)): pin for path, pin in software.items()})
    original_held = held_row[9]
    need(type(original_held) is tuple and len(original_held) == 3 and
         type(original_held[2]) is dict, 'held_tuple_changed')
    raw_map = original_held[2]
    need(set(raw_map) == set(expected_pins) and len(raw_map) == 34, 'held_pins_changed')
    for path, pin in expected_pins.items():
        need(type(raw_map[path]) is bytes and hashlib.sha256(raw_map[path]).hexdigest() == pin,
             'held_pin_changed')
        need(hashlib.sha256(Path(path).read_bytes()).hexdigest() == pin, 'current_pin_changed')
    frame = generator.gi_frame
    locals_ref = frame.f_locals
    need(locals_ref['raw_bytes'] is raw_map and len(locals_ref['identities']) == 34,
         'generator_hold_changed')
    need({str(path): pin for path, pin in locals_ref['all_pins'].items()} == expected_pins,
         'generator_pin_set_changed')
    record = {'schema': 'iteration41.okx.m01.r7.r2.root-source-close.v1',
              'scope': scope, 'generator': generator, 'held': original_held,
              'row': held_row, 'exit_started': False, 'exit_returned': False,
              'normal_close_verified': False}
    root_namespace['SOURCE_SCOPE_CLOSE_ROOT_RECORD'] = record
    record['exit_started'] = True
    exit_result = contextlib._GeneratorContextManager.__exit__(scope, None, None, None)
    record['exit_returned'] = True
    need(exit_result is False and scope.gen is generator and
         inspect.getgeneratorstate(generator) == 'GEN_CLOSED' and generator.gi_frame is None,
         'normal_close_not_proven')
    need(caller._RETAINED_CONTEXTS is registry and registry[0] is held_row,
         'historical_registry_changed')
    root_namespace['verify_caller'](caller, caller_raw, expected, initial=False)
    root_namespace['verify_snapshot'](caller, state['root_binding'])
    need(caller._cuv2_function_bindings_unchanged(cu, held_row[4]), 'cu_function_post_changed')
    need(root_namespace['ACTUAL_RESULT'] is result and result['gate_invocations'] == 0,
         'consumed_result_changed')
    for row in rows:
        need((root_namespace['ROOT'] / row['path']).read_bytes() == public_raw[row['path']],
             'source_post_changed')
    need(root_namespace['git_state']() == before, 'post_git_changed')
    record['normal_close_verified'] = True
    observation = {'schema': record['schema'], 'status': 'SOURCE_SCOPE_NORMAL_CLOSE_RETURNED',
        'public_pins': 31, 'software_pins': 3, 'normal_postverify_and_close': True,
        'generator_closed': True, 'original_reference_and_result_preserved': True,
        'original_caller_invocation_consumed': True, 'gate_invocations': 0,
        'provider_account_acceptance': False, 'formal_m01_pass_count': 0,
        'retained_python_row_preserved': True, 'host_exit_permitted_by_this_receipt': False,
        'software_raw_entries_returned_in_original_held_tuple': 3,
        'original_false_payload_return_flag_superseded_by_this_observation': True}
    output = root_namespace['OUTPUT'] / 'root-source-close-observation.json'
    need(not output.exists(), 'close_output_not_fresh')
    output.write_text(json.dumps(observation, indent=2) + '\n', encoding='utf-8')
    return observation
