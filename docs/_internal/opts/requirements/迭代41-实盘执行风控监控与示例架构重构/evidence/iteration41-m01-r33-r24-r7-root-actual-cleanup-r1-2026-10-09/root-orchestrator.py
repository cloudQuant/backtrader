"""Root orchestration for one reviewed R7 same-process M01 no-session cleanup."""
from pathlib import Path
import ast
import hashlib
import importlib.machinery
import io
import json
import os
import stat
import sys
import threading
import types
import zipfile

ROOT = Path('D:/source_code/backtrader')
E = ROOT / 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence'
PACKET = E / 'iteration41-m01-r33-r24-r7-cleanup-source-fake-r1-2026-10-09'
SNAPSHOT = E / 'iteration41-m01-r33-r24-r7-source-snapshot-r1-2026-10-09'
OUT = E / 'iteration41-m01-r33-r24-r7-root-actual-cleanup-r1-2026-10-09'
HELPER_REL = 'scripts/iteration41_okx_m01_r33_no_session_cleanup_r24_r7.py'
HELPER_SHA = 'c28c7480aac89c03acf72e6d646685e58a19f133ad218ef7642322ea448b8c98'
TEST_REL = 'tests/unit/runtime/test_iteration41_okx_m01_r33_no_session_cleanup_r24_r7_source_fake.py'
TEST_SHA = 'd893f95098cf435829490a9c971d2bb2f06fb6c8b8bfc0a4c00d44c35e0f7493'
PINS_SHA = '859ae68b3f0d5da8e639563abd90fd774f415195493cc993a3d91244b5caff96'
REVIEW_DIR = E / 'iteration41-m01-r33-r24-no-session-cleanup-independent-review-r7-r1-2026-10-09'
REVIEW = REVIEW_DIR / 'review.json'
REVIEW_SHA = '0b43b714ab5e6d85a8eb73d4af9db9c001e115ec8f8e1c66b37a979ca5bcc49b'
REVIEW_README_SHA = '54f8a6370ec9e7e45817041a6028dae0a31d0e0b1ca8c4629a7705937f932987'
PUBLIC_FILE_COUNT = 54
_ATTEMPTED = False

def _read(path, digest, size=None):
    path.relative_to(ROOT)
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and not path.is_symlink()
    assert not (getattr(before, 'st_file_attributes', 0) & 0x400)
    assert path.name not in ('.env', 'config.yaml', 'secrets.yaml')
    assert 0 < before.st_size <= 1024 * 1024
    with path.open('rb') as stream:
        raw = stream.read(before.st_size + 1)
    after = path.stat()
    assert len(raw) == before.st_size and (size is None or len(raw) == size)
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    assert hashlib.sha256(raw).hexdigest() == digest
    return raw


def _save(name, value):
    raw = (json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
    with (OUT / name).open('xb') as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def readback():
    rows = {}
    def add(path, digest, size=None):
        raw = _read(path, digest, size)
        key = path.relative_to(ROOT).as_posix()
        if key in rows:
            assert rows[key] == digest
        else:
            rows[key] = digest
        return raw
    pins_raw = add(PACKET / 'pins.json', PINS_SHA, 17854)
    pins = json.loads(pins_raw)
    assert pins['schema'] == 'iteration41.m01.r24.r7.source-fake-pins.v1'
    assert pins['status'] == 'SOURCE_FAKE_ONLY_NOT_ACTUAL_CLEANUP_ACCEPTANCE'
    assert pins['helper']['path'] == HELPER_REL and pins['helper']['sha256'] == HELPER_SHA and pins['helper']['bytes'] == 74333
    assert pins['test']['path'] == TEST_REL and pins['test']['sha256'] == TEST_SHA and pins['test']['bytes'] == 60800
    assert len(pins['runtime_source_pins']) == 19 and len(pins['pytest_import_closure']) == 45
    for row in [pins['helper'], pins['test'], pins['cuv2_public_source'], *pins['runtime_source_pins'], *pins['pytest_import_closure']]:
        relative = Path(row['path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        add(ROOT / relative, row['sha256'], row['bytes'])
    assert len(rows) == 46
    for name,digest,size in [
        ('README.md','655b117d8aafecd446e4af161eae5c2b00160390ad1e03c1d48d344a3f1bd28a',2734),
        ('qa-command.txt','fe3fc3350862f7b10a09729722c02be11a54fb6703b45bc8e2c3ad0f53b72561',560),
        ('qa-result.txt','bfeedff69a1f5c55153d10090f96ae06f3b44b8434c016022bb3270b64b7ccc0',117)]:
        add(PACKET / name,digest,size)
    zipraw = add(SNAPSHOT / 'public-source-snapshot.zip','8ddd496369c59bcdced7dfd5e4208e34b3a0c75317f55d3e5b1d01e75603d173',290389)
    snapshot = json.loads(add(SNAPSHOT / 'snapshot-map.json','7df2d30a963d43e201da8c229155532d5f72b0747c3a18261af3c2604a0e1f11',12247))
    add(SNAPSHOT / 'README.md','a4821a6d6841ca3350269efe205d2b303042505732de3e5ae4313a7de9936288',1100)
    assert snapshot['upstream_manifest']['sha256'] == PINS_SHA
    assert snapshot['source_count'] == 45 and snapshot['sources'] == pins['pytest_import_closure']
    with zipfile.ZipFile(io.BytesIO(zipraw)) as archive:
        expected = {'sources/' + row['path']: row for row in snapshot['sources']}
        assert len(archive.infolist()) == 45 and set(archive.namelist()) == set(expected)
        for name,row in expected.items():
            info=archive.getinfo(name)
            assert info.file_size==row['bytes'] and 0<info.file_size<1024*1024
            raw=archive.read(name)
            assert len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
    review = json.loads(add(REVIEW, REVIEW_SHA, 4275))
    add(REVIEW_DIR / 'README.md', REVIEW_README_SHA, 1985)
    assert len(rows) == PUBLIC_FILE_COUNT
    assert review['schema'] == 'iteration41.m01.r24.r7.independent-review.v1'
    assert review['decision'] == 'GO_SOURCE_FAKE_ONLY' and review['actual_status'] == 'ACTUAL_HOLD'
    for role in ('helper','test'):
        assert review['candidate'][role] == {key:pins[role][key] for key in ('path','bytes','sha256')}
    for row in review['frozen_author_packet']['files']:
        assert rows[(PACKET / row['path']).relative_to(ROOT).as_posix()] == row['sha256']
    verified = review['independently_verified_inputs']
    assert verified['runtime_source_pin_count']==19 and verified['runtime_source_pin_mismatches']==0
    assert verified['closure_path_count']==45 and verified['closure_pin_mismatches']==0
    assert verified['source_snapshot']['member_count']==45 and verified['source_snapshot']['member_pin_mismatches']==0
    independent_qa = review['independent_qa']
    assert independent_qa['result']=='28 passed, 0 failed, 0 skipped' and independent_qa['exit_code']==0
    helper_raw=_read(ROOT / HELPER_REL,HELPER_SHA,74333)
    tree=ast.parse(helper_raw)
    assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='RUNTIME_SOURCE_PINS' for t in n.targets))
    driver_path=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='R23_DRIVER_RELATIVE_PATH' for t in n.targets))
    runtime={driver_path if isinstance(k,ast.Name) else ast.literal_eval(k): ast.literal_eval(v) for k,v in zip(assignment.value.keys,assignment.value.values)}
    assert runtime=={row['path']:row['sha256'] for row in pins['runtime_source_pins']}
    OUT.mkdir()
    record={'schema':'iteration41.m01.cleanup.r24.r7.root-public-readback.v1','candidate_pins_sha256':PINS_SHA,'helper_sha256':HELPER_SHA,
            'independent_review_sha256':REVIEW_SHA,'public_files_verified':len(rows),'source_pins':rows,
            'closure_source_paths_verified':45,'snapshot_members_verified':45,'runtime_source_paths_verified':19,
            'cleanup_invoked':False,'activation_invoked':False,'private_inputs_read':False,'strict_cases_passed':0,
            'evidence_level':'PUBLIC_SOURCE_READBACK_BEFORE_ACTUAL','independent_source_fake_focus':independent_qa,
            'clean_relocated_source_qa_claimed':False,'planned_scope':'original_fixed_root_no_session_cleanup_only'}
    digest=_save('readback.json',record)
    print(json.dumps({'status':'PUBLIC_READBACK_VERIFIED','readback_sha256':digest,'public_files_verified':len(rows)},sort_keys=True),flush=True)
    return rows,digest


def run_actual(namespace, public_pins, readback_sha256):
    global _ATTEMPTED
    assert not _ATTEMPTED
    _ATTEMPTED = True
    assert sys.flags.optimize == 0 and tuple(sys.version_info[:3]) == (3, 11, 5)
    assert type(namespace) is dict and type(namespace['KEEPALIVE']) is list
    assert len(namespace['KEEPALIVE']) == 3
    assert namespace['auth_called'] is True and namespace['auth_succeeded'] is False
    assert namespace['release_called'] is False and namespace['release_succeeded'] is False
    main_bytes_identity_bound = namespace['main_scope'].gen.gi_frame.f_locals.get('raw_bytes') is namespace['held']
    extra_bytes_identity_bound = namespace['extra_scope'].gen.gi_frame.f_locals.get('raw_bytes') is namespace['extra_held']
    assert main_bytes_identity_bound and extra_bytes_identity_bound
    original_public = json.dumps(namespace['record'], sort_keys=True, separators=(',', ':')).encode('ascii')
    original_result_object = namespace['result']
    result_fields = ('schema', 'status', 'reason', 'cleanup_reason', 'child_returncode',
                     'capture_complete', 'cleanup_complete', 'scope_released', 'scope_retained',
                     'stdout_bytes', 'stderr_bytes')
    original_result_fields = tuple(getattr(original_result_object, field) for field in result_fields)
    original_child_phase = json.dumps(original_result_object.child_phase, sort_keys=True, separators=(',', ':'))
    original_summary = json.dumps(namespace['summary'], sort_keys=True, separators=(',', ':'))
    cu = namespace['cu']
    ctx = cu.held_public_sources(public_pins, {})
    receipt = None
    failure = None
    failure_code = None
    failure_phase = None
    public_scope_closed = False
    public_scope_postverified = False
    original_scope_generators_closed = False
    registry_remaining = None
    late_refs_remaining = None
    try:
        with ctx as (_, _, held):
            assert type(held) is dict and len(held) == PUBLIC_FILE_COUNT
            helper_path = ROOT / HELPER_REL
            helper_raw = held[str(helper_path)]
            assert hashlib.sha256(helper_raw).hexdigest() == HELPER_SHA
            name = '_iteration41_m01_cleanup_r24_r7_root'
            assert name not in sys.modules
            module = types.ModuleType(name)
            module.__file__ = str(helper_path)
            module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(helper_path))
            sys.modules[name] = module
            exec(compile(helper_raw, str(helper_path), 'exec', dont_inherit=True), module.__dict__)
            scopes = (namespace['main_scope'], namespace['extra_scope'])
            root_r2 = namespace['r19_adapter_result'].adapter._r8_adapter._r5._base._inner
            registry = root_r2._r32._DEFAULT_RETENTION_REGISTRY
            main_bytes_identity_bound = namespace['main_scope'].gen.gi_frame.f_locals.get('raw_bytes') is namespace['held']
            extra_bytes_identity_bound = namespace['extra_scope'].gen.gi_frame.f_locals.get('raw_bytes') is namespace['extra_held']
            assert main_bytes_identity_bound and extra_bytes_identity_bound
            typed_receipt = module.close_rejected_no_session_scope(
                namespace, expected_owner_pid=os.getpid(),
                expected_owner_thread=threading.get_ident(), capsule_sha256=HELPER_SHA)
            assert type(typed_receipt) is module.NoSessionCleanupReceipt
            receipt = typed_receipt.consume()
            original_scope_generators_closed = all(s.gen.gi_frame is None for s in scopes)
            registry_remaining = len(registry._entries)
            late_refs_remaining = len(root_r2._retained_late)
            del scopes, typed_receipt, registry, root_r2
        public_scope_postverified = True
        public_scope_closed = ctx.gen.gi_frame is None
    except BaseException as error:
        failure = ('capsule_blocked' if type(error) is getattr(
            locals().get('module'), 'NoSessionCleanupBlocked', None) else 'unexpected_exception')
        if type(error) is getattr(locals().get('module'), 'NoSessionCleanupBlocked', None):
            if type(error.code) is str and error.code in module._FAILURE_CODES:
                failure_code = error.code
            if type(error.phase_ordinal) is int and error.phase_ordinal in tuple(range(10, 131, 10)):
                failure_phase = error.phase_ordinal
        public_scope_closed = ctx.gen.gi_frame is None
    original_record_unchanged = original_public == json.dumps(namespace['record'], sort_keys=True, separators=(',', ':')).encode('ascii')
    result_identity_unchanged = namespace['result'] is original_result_object
    result_fields_unchanged = tuple(getattr(namespace['result'], field) for field in result_fields) == original_result_fields
    child_phase_unchanged = json.dumps(namespace['result'].child_phase, sort_keys=True, separators=(',', ':')) == original_child_phase
    summary_unchanged = json.dumps(namespace['summary'], sort_keys=True, separators=(',', ':')) == original_summary
    unchanged = original_record_unchanged and result_identity_unchanged and result_fields_unchanged and child_phase_unchanged and summary_unchanged
    references = ('extra_lease', 'main_lease', 'source_scope', 'extra_scope', 'extra_held', 'main_scope', 'held')
    complete = (type(receipt) is dict and receipt.get('main_scope_postverified_closed') is True
                and receipt.get('extra_scope_postverified_closed') is True
                and receipt.get('r32_registry_entry_removed') is True
                and receipt.get('root_scope_references_dropped') is True
                and receipt.get('verifier_phase_ordinal') == 130
                and original_scope_generators_closed and public_scope_closed and public_scope_postverified
                and len(namespace['KEEPALIVE']) == 1 and namespace['KEEPALIVE'][0] is namespace['r23_adapter_result'] and registry_remaining == 0
                and late_refs_remaining == 0 and all(k not in namespace for k in references) and unchanged)
    record = {'schema': 'iteration41.m01.cleanup.r24.r7.root-actual.v1',
              'status': 'CLEANUP_ACCEPTED' if complete else 'CLEANUP_UNACCEPTED',
              'readback_sha256': readback_sha256, 'candidate_pins_sha256': PINS_SHA,
              'independent_review_sha256': REVIEW_SHA,
              'owner_pid': os.getpid(), 'owner_thread': threading.get_ident(),
              'receipt': receipt, 'failure_category': failure, 'failure_code': failure_code, 'failure_phase_ordinal': failure_phase,
              'public_review_scope_closed': public_scope_closed,
              'public_review_scope_postverified': public_scope_postverified,
              'original_scope_generators_closed': original_scope_generators_closed,
              'remaining_keepalive_count': len(namespace['KEEPALIVE']),
              'remaining_keepalive_is_r23_result_only': len(namespace['KEEPALIVE']) == 1 and namespace['KEEPALIVE'][0] is namespace['r23_adapter_result'],
              'retained_root_scope_refs_count': sum(k in namespace for k in references),
              'retained_registry_entries_count': registry_remaining,
              'retained_late_refs_count': late_refs_remaining,
              'original_result_unchanged': unchanged,
              'original_record_unchanged': original_record_unchanged,
              'original_result_identity_unchanged': result_identity_unchanged,
              'original_result_fixed_fields_unchanged': result_fields_unchanged,
              'original_result_child_phase_unchanged': child_phase_unchanged,
              'original_summary_unchanged': summary_unchanged, 'new_activation_calls': 0,
              'main_cuv2_bytes_identity_bound': main_bytes_identity_bound,
              'extra_cuv2_bytes_identity_bound': extra_bytes_identity_bound,
              'late_private_capture_read': False, 'strict_cases_passed': 0}
    digest = _save('observation.json', record)
    print(json.dumps({'status': record['status'], 'observation_sha256': digest,
                      'failure_category': failure, 'failure_code': failure_code, 'failure_phase_ordinal': failure_phase,
                      'remaining_keepalive_count': record['remaining_keepalive_count'],
                      'retained_root_scope_refs_count': record['retained_root_scope_refs_count'],
                      'retained_registry_entries_count': registry_remaining,
                      'original_scope_generators_closed': original_scope_generators_closed}, sort_keys=True), flush=True)
    return complete, digest
