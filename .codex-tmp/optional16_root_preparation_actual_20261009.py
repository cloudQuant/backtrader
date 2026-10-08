"""Root-only one-shot Optional16 held-source preparation, before activation."""
import hashlib
import inspect
import json
from pathlib import Path
import stat
import sys
import time
import types

ROOT = Path('D:/source_code/backtrader')
E = 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/'
P = E + 'iteration41-optional16-r33-root-preparation-driver-source-fake-r1-2026-10-09/'
REVIEW = E + 'iteration41-optional16-r33-root-preparation-driver-independent-review-r1-2026-10-09/review.json'
DRIVER = 'scripts/iteration41_optional16_r33_root_preparation_driver_r1.py'
OUT = ROOT / E / 'iteration41-optional16-root-preparation-root-actual-r1-2026-10-09'
CU = Path('D:/temp/iteration41-root-public-custody-v2.py')
CU_SHA = 'e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246'
SUPPORT = {
    P + 'source-index.json': '5d9f43ff4c6e28d87f44e551e062b798c8e02c22cafca5f978d920d3938d9afb',
    P + 'README.md': 'ac6d32e0d5ea074b8a6d8f741e49e8312ff8adeda14aa6c21aa16d81adb273a8',
    P + 'checkpoint.json': 'a62ab186aa6ca375d259ac7169ac89ba7f94288891721e8694a9ad39026011b7',
    REVIEW: 'b48e45c950d1bdd65197af01a37db4d5fb2896ef119a265376cda7675f3010c4',
    'backtrader_runtime/certification_roundtrip_private.py': 'b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd',
    'backtrader_runtime/certification_binance_roundtrip_r3_cli.py': '62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76',
}
SOFTWARE = {
    'C:/anaconda3/python.exe': 'c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642',
    'C:/anaconda3/python311.dll': '162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00',
    str(CU): CU_SHA,
}
PREP_STATE = {'outer': None, 'held': None, 'driver': None, 'bindings': []}
PREP_CODES = {}
PREP_EXEC = set()

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def public_bytes(path, digest):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)
    assert 0 < info.st_size <= 10 * 1024 * 1024
    with path.open('rb') as stream:
        raw = stream.read(info.st_size + 1)
    assert len(raw) == info.st_size and sha(raw) == digest
    return raw

def load(raw, path, name):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    return module

def all_codes(code, mapping):
    mapping.setdefault(code.co_qualname, []).append(code)
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            all_codes(value, mapping)

def bind(module, raw):
    origin = str(Path(module.__file__).resolve())
    mapping = {}
    all_codes(compile(raw, origin, 'exec', dont_inherit=True), mapping)
    rows = []
    owners = [module] + [value for value in tuple(vars(module).values())
                        if isinstance(value, type) and value.__module__ == module.__name__]
    for owner in owners:
        for key, value in tuple(vars(owner).items()):
            if isinstance(value, (staticmethod, classmethod)):
                value = value.__func__
            if isinstance(value, types.FunctionType) and value.__module__ == module.__name__:
                function = inspect.unwrap(value)
                assert function.__globals__ is module.__dict__
                if function.__code__.co_filename == origin:
                    assert function.__code__ in mapping.get(function.__code__.co_qualname, [])
                rows.append((owner, key, value, function.__code__))
    return module, rows

def verify(record):
    module, rows = record
    for owner, key, function, code in rows:
        current = vars(owner)[key]
        if isinstance(current, (staticmethod, classmethod)):
            current = current.__func__
        assert current is function and inspect.unwrap(current).__code__ is code
        assert inspect.unwrap(current).__globals__ is module.__dict__

def audit(event, args):
    if event == 'exec':
        code = args[0]
        expected = PREP_CODES.get(code.co_filename)
        if expected is not None:
            assert code == expected, 'root_preparation_executed_source_mismatch'
            PREP_EXEC.add(code.co_filename)
    if event == 'import' and isinstance(args[0], str) and args[0].startswith('bt_api'):
        raise RuntimeError('root_preparation_sdk_denied')
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system', 'os.posix_spawn', '_winapi.CreateProcess'}:
        raise RuntimeError('root_preparation_external_operation_denied')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        value = str(args[0]).replace('\\', '/').lower()
        if value.endswith('/.env') or value.endswith('/config.yaml') or 'private-capture' in value:
            raise RuntimeError('root_preparation_private_input_denied')

def run():
    assert sys.version_info[:3] == (3, 11, 5)
    assert Path(sys.executable).resolve() == Path('C:/anaconda3/python.exe').resolve()
    assert sys.flags.isolated and sys.flags.no_site and sys.flags.interactive and sys.dont_write_bytecode
    assert not any(name.startswith(('_iteration41_root_held', '_root_held_source', '_optional16')) for name in sys.modules)
    index = json.loads(public_bytes(ROOT / (P + 'source-index.json'), SUPPORT[P + 'source-index.json']))
    rows = index['candidate_sources'] + index['fixed_dependencies']
    assert len(rows) == 35
    pins = {row['path']: row['sha256'] for row in rows}
    pins.update(SUPPORT)
    own = Path(__file__).resolve().relative_to(ROOT).as_posix()
    pins[own] = sha(Path(__file__).read_bytes())
    for path, digest in pins.items():
        public_bytes(ROOT / path, digest)
    for path, digest in SOFTWARE.items():
        public_bytes(Path(path), digest)
    cu = load(public_bytes(CU, CU_SHA), CU, '_root_optional16_preparation_cuv2_oct9')
    OUT.mkdir(exist_ok=False)
    result = {'schema': 'iteration41.optional16.preparation.root_actual.v1',
              'status': 'BLOCKED', 'reason': None, 'preparation_invocations': 0, 'receipt': None,
              'public_outer_pin_count': len(pins), 'software_outer_pin_count': len(SOFTWARE),
              'driver_source_and_function_bindings_verified': False,
              'executed_fixed_driver_source_verified': False, 'retained_attempts': None,
              'outer_normal_postverify_and_close': False, 'host_exit_permitted': False,
              'formal_optional16_pass_count': 0, 'provider_call': False, 'activation': False}
    started = time.monotonic()
    try:
        outer = cu.held_public_sources(pins, SOFTWARE)
        PREP_STATE['outer'] = outer
        held = outer.__enter__()
        PREP_STATE['held'] = held
        raw = held[2]
        for path, source in raw.items():
            if path.endswith('.py') and path != str(Path(__file__).resolve()):
                origin = str(Path(path).resolve())
                PREP_CODES[origin] = compile(source, origin, 'exec', dont_inherit=True)
        sys.addaudithook(audit)
        driver = load(raw[str(ROOT / DRIVER)], ROOT / DRIVER, '_root_optional16_preparation_driver_oct9')
        PREP_STATE['driver'] = driver
        record = bind(driver, raw[str(ROOT / DRIVER)])
        PREP_STATE['bindings'].append(record)
        verify(record)
        assert driver._ATTEMPT_STARTED is False and not driver._RETAINED_ATTEMPTS
        result['preparation_invocations'] = 1
        receipt = driver.prepare_root_held_source_gate(requested=True)
        assert type(receipt) is dict
        assert all(type(value) in (bool, str, int, type(None)) for value in receipt.values())
        result['receipt'] = receipt
        verify(record)
        result['driver_source_and_function_bindings_verified'] = True
        result['executed_fixed_driver_source_verified'] = str(ROOT / DRIVER) in PREP_EXEC
        result['retained_attempts'] = len(driver._RETAINED_ATTEMPTS)
        if receipt['status'] == 'PREPARATION_VERIFIED_NO_AUTHORITY':
            assert receipt['scope_state'] == 'CLOSED' and receipt['authority'] == 'NONE'
            assert type(receipt['public_rows']) is int and receipt['public_rows'] == 582
            assert type(receipt['software_rows']) is int and receipt['software_rows'] == 5
            assert type(receipt['profiler_modules']) is int and receipt['profiler_modules'] == 3
            assert receipt['boundary'] == 'before_r5_worker_installer'
            assert result['retained_attempts'] == 0
            outer.__exit__(None, None, None)
            PREP_STATE['outer'] = PREP_STATE['held'] = None
            result['outer_normal_postverify_and_close'] = True
            result['host_exit_permitted'] = True
            result['status'] = receipt['status']
        else:
            result['reason'] = receipt['reason_code']
    except BaseException:
        result['reason'] = 'root_preparation_check_blocked'
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    with (OUT / 'observation.json').open('xb') as stream:
        stream.write((json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii'))
    print(json.dumps(result, sort_keys=True), flush=True)
    return result

PREP_RESULT = run()
if not PREP_RESULT['host_exit_permitted']:
    print('ROOT_PREPARATION_CONTEXT_RETAINED', flush=True)
