"""Root orchestration for one reviewed same-process C01 cleanup attempt."""
from pathlib import Path
from dataclasses import asdict
import hashlib
import importlib.machinery
import json
import os
import stat
import sys
import threading
import types

ROOT = Path('D:/source_code/backtrader')
E = ROOT / 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence'
PACKET = E / 'iteration41-c01-v18-root-prelaunch-cleanup-capsule-r3-2026-10-08'
REVIEW = E / 'iteration41-c01-v18-root-prelaunch-cleanup-capsule-independent-review-r3-2026-10-08-oct7b'
OUT = E / 'iteration41-c01-v18-root-prelaunch-cleanup-r3-root-actual-r1-2026-10-08'
PINS_SHA = 'e9f0ad5851f5601bb250e2386c85b5a249e85a3c5294c5ffa2e7e87df5c3b35e'
HELPER_SHA = 'e2406e6e4fc14f3bf89a5a3de5489ddcb6faf0dee00d874054bc654e176c3bb4'
REVIEW_PINS = {
    'review.json': 'c13f746bc68377a5e6ef8bcb7bf5c9f728b1a953cea9d826c6ddab99684f1b16',
    'review-bundle.zip': '2fe9607a7b41a95c54509ca39d237152e05d967dbe25775a35098eb8a6abdc6d',
    'review-index.json': 'd4c0119138b877d0b7cdb65174ec660204c3845d194e0b8a531d69e9db3d69cb',
    'review-checkpoint.json': 'aa2e61a393865637139fae58c221406a5bbb3976046c3234039a1b6ce6d5dda0',
    'README.md': 'b30e8aa8f991995e59b181226c8b39f1669da886b9253c4531ce78b3f029cb51',
}
_ATTEMPTED = False


def _read(path, digest, size=None):
    path.relative_to(ROOT)
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and not path.is_symlink()
    assert not (getattr(before, 'st_file_attributes', 0) & 0x400)
    assert path.name not in ('.env', 'config.yaml', 'secrets.yaml')
    assert 0 < before.st_size <= 4 * 1024 * 1024
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
    pins = json.loads(_read(PACKET / 'pins.json', PINS_SHA))
    assert pins['packet_id'] == PACKET.name and pins['official_c01_pass_count'] == 0
    assert pins['held_map'] == {'public_source_count': 31, 'software_pin_count': 2, 'total_count': 33}
    rows = {'pins.json': {'sha256': PINS_SHA}}
    rows.update(pins['candidate_files'])
    rows.update(pins['source_references'])
    for name in ('command', 'output'):
        rows[pins['qa'][name]] = {'sha256': pins['qa'][name + '_sha256']}
    assert len(rows) == 9
    public_pins = {}
    for relative, row in rows.items():
        relative_path = Path(relative)
        assert not relative_path.is_absolute() and '..' not in relative_path.parts
        path = PACKET / relative_path
        _read(path, row['sha256'], row.get('bytes'))
        public_pins[path.relative_to(ROOT).as_posix()] = row['sha256']
    assert {p.relative_to(PACKET).as_posix() for p in PACKET.rglob('*') if p.is_file()} == set(rows)
    for name, digest in REVIEW_PINS.items():
        path = REVIEW / name
        _read(path, digest)
        public_pins[path.relative_to(ROOT).as_posix()] = digest
    review = json.loads(_read(REVIEW / 'review.json', REVIEW_PINS['review.json']))
    assert review['verdict'] == 'GO_SOURCE_FAKE_ONLY'
    assert review['candidate_packet']['pins_sha256'] == PINS_SHA
    assert review['candidate_packet']['capsule_sha256'] == HELPER_SHA
    assert review['actual_cleanup_invoked'] is False and review['actual_activation_invoked'] is False
    assert review['private_inputs_read'] is False and review['official_c01_pass_count'] == 0
    OUT.mkdir()
    record = {'schema': 'iteration41.c01.cleanup.r3.root-public-readback.v1',
              'candidate_pins_sha256': PINS_SHA, 'helper_sha256': HELPER_SHA,
              'independent_review_sha256': REVIEW_PINS['review.json'],
              'packet_files_verified': 9, 'review_files_verified': 5,
              'source_pins': public_pins, 'cleanup_invoked': False,
              'activation_invoked': False, 'private_inputs_read': False,
              'official_c01_pass_count': 0}
    digest = _save('readback.json', record)
    print(json.dumps({'status': 'PUBLIC_READBACK_VERIFIED', 'readback_sha256': digest,
                      'packet_files_verified': 9, 'review_files_verified': 5}, sort_keys=True))
    return public_pins, digest


def run_actual(driver, original_result, public_pins, readback_sha256):
    global _ATTEMPTED
    assert not _ATTEMPTED
    _ATTEMPTED = True
    assert sys.flags.optimize == 0 and tuple(sys.version_info[:3]) == (3, 11, 5)
    assert driver.__name__ == '_iteration41_c01_r4b_root_actual'
    assert type(driver.KEEPALIVE) is list and len(driver.KEEPALIVE) == 1
    assert type(driver.ACTIVATION._ROOT_RETAINED_UNRESOLVED_JOB_REFS) is list
    assert len(driver.ACTIVATION._ROOT_RETAINED_UNRESOLVED_JOB_REFS) == 0
    original_bytes = json.dumps(original_result, sort_keys=True, separators=(',', ':')).encode('ascii')
    cu = sys.modules['_iteration41_root_public_custody_v2']
    ctx = cu.held_public_sources(public_pins, {})
    receipt = None
    failure = None
    public_scope_closed = False
    public_scope_postverified = False
    try:
        with ctx as (_, _, held):
            assert type(held) is dict and len(held) == 14
            helper_path = PACKET / 'root-prelaunch-cleanup-capsule.py'
            helper_raw = held[str(helper_path)]
            assert hashlib.sha256(helper_raw).hexdigest() == HELPER_SHA
            name = '_iteration41_c01_cleanup_r3_root'
            assert name not in sys.modules
            module = types.ModuleType(name)
            module.__file__ = str(helper_path)
            module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(helper_path))
            sys.modules[name] = module
            exec(compile(helper_raw, str(helper_path), 'exec', dont_inherit=True), module.__dict__)
            capsule = module.prepare_prelaunch_cleanup(driver, original_result)
            receipt = asdict(capsule.cleanup_once())
        public_scope_postverified = True
        public_scope_closed = ctx.gen.gi_frame is None
    except BaseException as error:
        # Fixed category only; never emit exception messages or private objects.
        failure = type(error).__name__
        public_scope_closed = ctx.gen.gi_frame is None
    unchanged = original_bytes == json.dumps(original_result, sort_keys=True, separators=(',', ':')).encode('ascii')
    complete = (type(receipt) is dict and receipt.get('normal_cuv2_close_verified') is True
                and receipt.get('exact_retained_tuple_removed') is True
                and receipt.get('original_blocked_result_unchanged') is True
                and public_scope_closed and public_scope_postverified
                and len(driver.KEEPALIVE) == 0 and unchanged)
    record = {'schema': 'iteration41.c01.cleanup.r3.root-actual.v1',
              'status': 'CLEANUP_ACCEPTED' if complete else 'CLEANUP_UNACCEPTED',
              'readback_sha256': readback_sha256, 'candidate_pins_sha256': PINS_SHA,
              'independent_review_sha256': REVIEW_PINS['review.json'],
              'owner_pid': os.getpid(), 'owner_thread': threading.get_ident(),
              'receipt': receipt, 'failure_category': failure,
              'public_review_scope_closed': public_scope_closed,
              'public_review_scope_postverified': public_scope_postverified,
              'retained_driver_refs_count': len(driver.KEEPALIVE),
              'wrapper_retained_job_refs_count': len(driver.ACTIVATION._ROOT_RETAINED_UNRESOLVED_JOB_REFS),
              'original_result_unchanged': unchanged, 'new_activation_calls': 0,
              'late_private_capture_read': False, 'official_c01_pass_count': 0}
    digest = _save('observation.json', record)
    print(json.dumps({'status': record['status'], 'observation_sha256': digest,
                      'retained_driver_refs_count': record['retained_driver_refs_count'],
                      'failure_category': failure, 'receipt': receipt}, sort_keys=True))
    return complete, digest
