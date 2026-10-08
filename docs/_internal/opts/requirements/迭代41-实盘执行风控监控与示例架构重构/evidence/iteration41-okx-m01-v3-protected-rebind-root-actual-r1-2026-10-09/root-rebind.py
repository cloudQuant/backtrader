"""Root-only metadata update and admission/release; no account operation."""
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import stat
import sys
import types

ROOT = Path('D:/source_code/backtrader')
VENUE = ROOT / 'examples/000_live_certification/okx_penetration'
E_REL = 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/'
P = E_REL + 'iteration41-okx-m01-v3-reason-preservation-r2-selected-source-qa-r4-2026-10-09/'
R = E_REL + 'iteration41-okx-m01-reason-preservation-independent-review-r2-2026-10-09/'
Q = E_REL + 'iteration41-okx-m01-v3-protected-rebind-independent-review-r1-2026-10-09/'
OUT = ROOT / E_REL / 'iteration41-okx-m01-v3-protected-rebind-root-actual-r1-2026-10-09'
CU = Path('D:/temp/iteration41-root-public-custody-v2.py')
CU_SHA = 'e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246'
HELPER = 'scripts/iteration41_okx_m01_v3_protected_rebind_r1.py'
TEST = 'tests/unit/live_certification/test_okx_m01_readonly_monitor_v3.py'
MAP_SHA = 'db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3'
SUPPORT = {
    P + 'source-index.json': 'abc6e49afab4fad7d44dc70474cfc993e212e71c56270b7d065374da63da9bc8',
    P + 'source-map.json': MAP_SHA,
    R + 'review.json': '38caf05f18e8c70997ac7fecc5acac510103b2feffa40976d1ce8166ac213ce7',
    R + 'README.md': '14d1cfe8c329b4a6a1655b9f7f697521b094f96def482fa54feef8a423168e01',
    Q + 'review.json': 'f19e6086d9473a3914dce13809b43d38a82693322005298371ac9dd8cb6227de',
    Q + 'README.md': 'e09d4daa948088b5fb95032eadcd78e46135c439189e946475e26e01adc8d412',
    HELPER: '772157d54079f3e0900caee75e9be78632084b32a729b15abaee4529e010a296',
    'tests/unit/scripts/test_iteration41_okx_m01_v3_protected_rebind_r1.py': '4880f722fb9cbaf7cba09d0917a3b6b40f9095fffc1c89abcdfb2ce536e61c46',
    'backtrader_runtime/certification_binance_roundtrip_r3_cli.py': '62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76',
}
SOFTWARE = {
    'C:/anaconda3/python.exe': 'c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642',
    'C:/anaconda3/python311.dll': '162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00',
    str(CU): CU_SHA,
}
ROOT_METADATA_STATE = {'scope': None, 'held': None, 'reader': None, 'helper': None, 'admission': None}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def public_bytes(path, pin):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)
    assert 0 < info.st_size <= 10 * 1024 * 1024
    with path.open('rb') as stream:
        raw = stream.read(info.st_size + 1)
    assert len(raw) == info.st_size and sha(raw) == pin
    return raw

def load_held(raw, path, name):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    return module

def code_objects(code, result):
    result.setdefault(code.co_qualname, []).append(code)
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            code_objects(value, result)

def bind_module(module, raw):
    path = str(Path(module.__file__).resolve())
    expected = {}
    code_objects(compile(raw, path, 'exec', dont_inherit=True), expected)
    bindings = []
    owners = [(module, vars(module))]
    for value in tuple(vars(module).values()):
        if isinstance(value, type) and value.__module__ == module.__name__:
            owners.append((value, vars(value)))
    for owner, namespace in owners:
        for key, value in tuple(namespace.items()):
            if isinstance(value, (staticmethod, classmethod)):
                value = value.__func__
            if isinstance(value, types.FunctionType) and value.__module__ == module.__name__:
                unwrapped = inspect.unwrap(value)
                assert unwrapped.__globals__ is module.__dict__
                if unwrapped.__code__.co_filename == path:
                    assert unwrapped.__code__ in expected.get(unwrapped.__code__.co_qualname, [])
                bindings.append((owner, key, value, unwrapped.__code__))
    assert bindings
    constants = {key: repr(value) for key, value in vars(module).items() if key.isupper() and key not in {'_ADMISSIONS', '_CONSUMED_ADMISSIONS', '_CURRENT_READ_EVIDENCE', '_ORPHANED_SOURCE_ADMISSIONS', '_ORPHANED_CONTEXTS'}}
    return module, bindings, constants

def verify_binding(record):
    module, bindings, constants = record
    for owner, key, function, code in bindings:
        current = vars(owner)[key]
        if isinstance(current, (staticmethod, classmethod)):
            current = current.__func__
        assert current is function and inspect.unwrap(current).__code__ is code
        assert inspect.unwrap(current).__globals__ is module.__dict__
    assert all(repr(vars(module)[key]) == value for key, value in constants.items())

def safe_code(error):
    value = getattr(error, 'code', None)
    return value if type(value) is str and re.fullmatch(r'[a-z0-9_]{1,64}', value) else 'root_metadata_operation_failed'

def audit(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'socket.connect', 'socket.getaddrinfo'}:
        raise RuntimeError('metadata_account_process_network_forbidden')
    if event == 'import' and isinstance(args[0], str) and args[0].startswith('bt_api'):
        raise RuntimeError('metadata_sdk_forbidden')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        value = str(args[0]).replace('\\', '/').lower()
        if value.endswith('/.env') or value.endswith('/config.yaml') or 'private-capture' in value:
            raise RuntimeError('metadata_credentials_private_capture_forbidden')

def run():
    assert sys.version_info[:3] == (3, 11, 5)
    assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode and sys.flags.interactive
    index = json.loads(public_bytes(ROOT / (P + 'source-index.json'), SUPPORT[P + 'source-index.json']))
    assert len(index['rows']) == 20
    pins = {row['path']: row['sha256'] for row in index['rows']}
    pins.update(SUPPORT)
    own_relative = Path(__file__).resolve().relative_to(ROOT).as_posix()
    pins[own_relative] = sha(Path(__file__).read_bytes())
    for relative, pin in pins.items():
        public_bytes(ROOT / relative, pin)
    review = json.loads(public_bytes(ROOT / (Q + 'review.json'), SUPPORT[Q + 'review.json']))
    assert review['decision'] == 'GO_ROOT_PROTECTED_METADATA_ONLY'
    backup = Path('D:/temp/iteration41-okx-m01-v3-deployment/r2-20261009-preservation')
    assert not os.path.lexists(backup)
    for path in reversed(backup.parent.parents):
        info = path.lstat()
        assert stat.S_ISDIR(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)
    info = backup.parent.lstat()
    assert stat.S_ISDIR(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)
    cu = load_held(public_bytes(CU, CU_SHA), CU, '_root_m01_metadata_cuv2_oct9')
    OUT.mkdir(exist_ok=False)
    sys.addaudithook(audit)
    result = {'schema': 'iteration41.okx.m01.root_metadata_rebind.v1', 'scope': 'PROTECTED_METADATA_ADMISSION_RELEASE_ONLY', 'status': 'BLOCKED', 'reason': None, 'runtime_source_count': 19, 'outer_public_pin_count': len(pins), 'outer_software_pin_count': 3, 'backup_fresh_before_call': True, 'fixed_ancestry_metadata_verified': True, 'metadata_invoked': False, 'metadata_rebound': False, 'metadata_handles_released': False, 'reader_function_global_binding_verified': False, 'admission_returned': False, 'admission_map_matches_public': False, 'admission_released': False, 'outer_normal_postverify_and_close': False, 'retained_metadata_contexts': None, 'retained_admissions': None, 'orphaned_source_admissions': None, 'orphaned_runtime_handle_sets': None, 'credentials_read': False, 'account_provider_call': False, 'c01_helper_invoked': False, 'websocket_started': False, 'formal_m01_pass_count': 0, 'host_exit_permitted': False}
    records = []
    try:
        scope = cu.held_public_sources(pins, SOFTWARE)
        ROOT_METADATA_STATE['scope'] = scope
        held = scope.__enter__()
        ROOT_METADATA_STATE['held'] = held
        private, cli, raw = held
        sys.path.insert(0, str(VENUE))
        entry = importlib.import_module('_m01_readonly_monitor_v3.entry')
        entry._verify_preimports()
        reader = importlib.import_module('_m01_readonly_monitor_v3.current_reader')
        helper = load_held(raw[str(ROOT / HELPER)], ROOT / HELPER, '_root_m01_metadata_helper_oct9')
        ROOT_METADATA_STATE.update(reader=reader, helper=helper)
        for module, relative in [(reader, 'examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py'), (helper, HELPER), (private, 'backtrader_runtime/certification_roundtrip_private.py')]:
            records.append(bind_module(module, raw[str(ROOT / relative)]))
        result['reader_function_global_binding_verified'] = True
        result['metadata_invoked'] = True
        rebound = helper.rebind_fixed_deployment(held_source_map_raw=raw[str(ROOT / (P + 'source-map.json'))], source_review_ref='iteration41-okx-m01-source-owned-v3-review-r2', held_review_json_raw=raw[str(ROOT / (R + 'review.json'))], held_review_readme_raw=raw[str(ROOT / (R + 'README.md'))], held_reviewed_test_raw=raw[str(ROOT / TEST)], reader_module=reader, private_module=private)
        assert rebound['status'] == 'REBOUND' and all(rebound[key] is True for key in helper._STATE_KEYS)
        result['metadata_rebound'] = True
        result['metadata_handles_released'] = True
        token = reader.admit_source()
        ROOT_METADATA_STATE['admission'] = token
        assert type(token) is reader.SourceAdmission
        result['admission_returned'] = True
        result['admission_map_matches_public'] = token.source_map_sha256 == MAP_SHA
        assert result['admission_map_matches_public']
        reader.release_admission(token)
        assert token.leases._closed and not token.leases.files
        ROOT_METADATA_STATE['admission'] = None
        result['admission_released'] = True
    except BaseException as error:
        result['reason'] = safe_code(error)
    reader, helper = ROOT_METADATA_STATE['reader'], ROOT_METADATA_STATE['helper']
    if helper is not None:
        result['retained_metadata_contexts'] = len(helper._ORPHANED_CONTEXTS)
    if reader is not None:
        result['retained_admissions'] = len(reader._ADMISSIONS)
        result['orphaned_source_admissions'] = len(reader._ORPHANED_SOURCE_ADMISSIONS)
        result['orphaned_runtime_handle_sets'] = len(reader.job_supervisor._ORPHANED_RUNTIME_HANDLE_SETS)
    clean = all(result[key] == 0 for key in ['retained_metadata_contexts', 'retained_admissions', 'orphaned_source_admissions', 'orphaned_runtime_handle_sets']) and ROOT_METADATA_STATE['admission'] is None
    if clean and ROOT_METADATA_STATE['held'] is not None:
        try:
            for record in records:
                verify_binding(record)
            ROOT_METADATA_STATE['scope'].__exit__(None, None, None)
            result['outer_normal_postverify_and_close'] = True
            ROOT_METADATA_STATE['scope'] = ROOT_METADATA_STATE['held'] = None
        except BaseException as error:
            result['reason'] = safe_code(error)
            clean = False
    result['host_exit_permitted'] = clean and result['outer_normal_postverify_and_close']
    if result['metadata_rebound'] and result['admission_released'] and result['host_exit_permitted']:
        result['status'], result['reason'] = 'METADATA_REBOUND_ADMISSION_VERIFIED', None
    with (OUT / 'observation.json').open('xb') as stream:
        stream.write((json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii'))
    print(json.dumps(result, sort_keys=True), flush=True)
    return result

ROOT_METADATA_RESULT = run()
if not ROOT_METADATA_RESULT['host_exit_permitted']:
    print('ROOT_METADATA_CONTEXT_RETAINED', flush=True)
