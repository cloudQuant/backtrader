"""Execute R7 once in the original Root owner, after pinned public readback."""
from pathlib import Path
import hashlib
import sys
import types

assert type(original_namespace) is dict
assert '_r7_cleanup_owner_attempt_used' not in original_namespace
root_path = Path('D:/source_code/backtrader/.codex-tmp/m01-r24-r7-cleanup-root-oct9-r1.py')
root_stat = root_path.lstat()
assert root_path.is_file() and not root_path.is_symlink()
assert not (getattr(root_stat, 'st_file_attributes', 0) & 0x400)
assert root_stat.st_size == 16338
with root_path.open('rb') as stream:
    root_bytes = stream.read(16339)
assert len(root_bytes) == 16338
assert hashlib.sha256(root_bytes).hexdigest() == '684e44ba497052c68ed0e1a3352d0018c871f61e5be1afc6f29940e1c5dd20eb'
module_name = '_iteration41_m01_r7_root_owner_orchestrator'
assert module_name not in sys.modules
root_module = types.ModuleType(module_name)
root_module.__file__ = str(root_path)
sys.modules[module_name] = root_module
exec(compile(root_bytes, str(root_path), 'exec', dont_inherit=True), root_module.__dict__)
readback_hash = '0b35003e80f6b13d4caba21d675f51e43aca984c845377f62e462bb1e221157e'
readback = root_module.json.loads(root_module._read(root_module.OUT / 'readback.json', readback_hash))
assert readback['schema'] == 'iteration41.m01.cleanup.r24.r7.root-public-readback.v1'
assert readback['cleanup_invoked'] is False and readback['activation_invoked'] is False
assert readback['candidate_pins_sha256'] == root_module.PINS_SHA
assert readback['independent_review_sha256'] == root_module.REVIEW_SHA
assert readback['public_files_verified'] == root_module.PUBLIC_FILE_COUNT == len(readback['source_pins'])
assert readback['closure_source_paths_verified'] == 45 and readback['snapshot_members_verified'] == 45
original_namespace['_r7_cleanup_owner_attempt_used'] = True
cleanup_complete, observation_hash = root_module.run_actual(original_namespace, readback['source_pins'], readback_hash)
