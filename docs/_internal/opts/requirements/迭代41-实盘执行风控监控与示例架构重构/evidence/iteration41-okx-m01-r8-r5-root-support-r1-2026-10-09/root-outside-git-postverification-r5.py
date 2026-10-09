import hashlib
import json
from pathlib import Path, PurePosixPath
import runpy

root = Path('D:/source_code/backtrader')
evidence = root / 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence'
def pinned(path, size, digest):
    raw = path.read_bytes()
    assert len(raw) == size and hashlib.sha256(raw).hexdigest() == digest
    return raw
result_raw = pinned(root / '.codex-tmp/okx_m01_r7_r5_root_actual_20261009.json', 6305, 'c3e3f36358dabe335039f19dfe9b62ea23b42823d2b86f883ec9c150a6b19dc2')
value = json.loads(result_raw)
assert value['caller_scope_clean'] is True
assert value['root_host_exit_permitted'] is False and value['root_host_exit_state'] == 'PENDING_OUTSIDE_HOST_GIT_POSTVERIFY'
assert value['root_caller_source_bindings_pre_post_verified'] is True and value['source_bytes_pre_post_unchanged'] is True
actual = value['result']
assert actual['status'] == 'LOCAL_SYNTHETIC_CHILD' and actual['gate_invocations'] == 1
assert actual['scope_exit_confirmed'] is True and actual['outer_normal_postverify_and_close'] is True
assert actual['source_count'] == 34 and actual['public_source_count'] == 31 and actual['software_source_count'] == 3
assert actual['software_pins_verified_by_cuv2'] is True and actual['source_pre_post_bindings_verified'] is True
assert actual['host_exit_permitted'] is True and actual['private_inputs_read'] is False and actual['account_provider_operations'] is False
assert actual['retained_python_references'] is False
for key in ('retained_gate_context_count', 'retained_runtime_registry_count', 'retained_reader_context_count', 'caller_retained_reference_count', 'formal_m01_pass_count'):
    assert actual[key] == 0
gate = actual['gate_result']
for key in ('cleanup_confirmed', 'job_zero_after_exit', 'job_zero_after_cleanup', 'all_observed_handles_closed', 'stdout_eof', 'stderr_eof', 'stdout_thread_joined', 'stderr_thread_joined', 'stdout_matches_fixed', 'stderr_empty', 'process_exit_code_zero', 'source_functions_restored', 'runtime_registry_empty_after', 'reader_retained_contexts_empty_after', 'module_bindings_unchanged_after'):
    assert gate[key] is True
assert gate['handle_close_calls'] == 11 and gate['handle_close_failures'] == 0
assert gate['wait_results'] == [True] and gate['cleanup_wait_attempted'] is False
assert gate['job_count_observations'][-1] == ['job_count_after_cleanup', 0]
manifest_raw = pinned(evidence / 'iteration41-okx-m01-r7-five-module-root-gate-preparation-r4-2026-10-09/candidate-pins.json', 8232, '7afb872549da80766d1b3959bb0162e44776046f6be895a573c60c544e89dc6c')
manifest = json.loads(manifest_raw)
assert len(manifest['public_pins']) == 31
for row in manifest['public_pins']:
    relative = PurePosixPath(row['path'])
    assert not relative.is_absolute() and '..' not in relative.parts and row['bytes'] <= 2097152
    pinned(root.joinpath(*relative.parts), row['bytes'], row['sha256'])
pinned(root / '.codex-tmp/okx_m01_r8_r5_root_driver_r2_20261009.py', 29420, 'ddee4f2eb6058c61b0c2ef69964d33fdca82a85ead733e272d391f6f41d3d369')
utility = root / '.codex-tmp/stage_okx_m01_r4_source_close_support_r2_20261009.py'
pinned(utility, 9946, '392f98b9deb86251d3d23fde0a1927c321debae903a7ba789223e14be855b035')
git = runpy.run_path(str(utility), run_name='root_outside_git_utilities')['git']
observed = {'branch':git('branch', '--show-current').decode().strip(), 'head':git('rev-parse', 'HEAD').decode().strip(), 'index_empty':git('diff', '--cached', '--name-only', '-z') == b''}
assert observed == value['git_pre_call'] == {'branch':'dev', 'head':'e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b', 'index_empty':True}
post = {'status':'OUTSIDE_HOST_GIT_POSTVERIFIED', 'git_pre_post_equal':True, 'git':observed, 'root_receipt_sha256':hashlib.sha256(result_raw).hexdigest(), 'public_pins_verified':31, 'driver_pin_verified':True, 'host_id':39102, 'host_state_checked_by_this_tool':False, 'normal_host_exit_pending_live_binding_check':True, 'formal_m01_pass_count':0, 'account_provider_acceptance':False}
output = evidence / 'iteration41-okx-m01-r7-five-module-root-gate-actual-r5-2026-10-09/root-outside-git-postverification.json'
output.open('x', encoding='utf-8').write(json.dumps(post, sort_keys=True, indent=2)+'\n')
print(json.dumps(post))
