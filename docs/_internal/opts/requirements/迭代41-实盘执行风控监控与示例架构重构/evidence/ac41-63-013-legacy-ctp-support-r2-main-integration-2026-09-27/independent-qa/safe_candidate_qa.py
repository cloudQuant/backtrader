from __future__ import annotations

import builtins
import ctypes
import hashlib
import http.client
import importlib.abc
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from urllib import request as urllib_request

QA = Path(__file__).resolve().parent
REPO = Path(r'D:\source_code\backtrader')
FOCUSED = QA / 'test_partition4_r2_failclosed_and_inert_import.py'
UNIT = QA / 'tests' / 'unit' / 'test_ctp_pair_examples.py'
SAFE_CONFIGS = {
    str((QA / 'examples' / '013_1_midfreq_cross_arbitrage' / 'config.yaml').resolve()).casefold(),
    str((QA / 'examples' / '013_2_highfreq_calendar_arbitrage' / 'config.yaml').resolve()).casefold(),
}
state = {
    'optional_import_attempts': [],
    'native_loader_attempts': [],
    'network_attempts': [],
    'env_reads': [],
    'forbidden_config_reads': [],
    'allowed_sample_config_reads': [],
    'credential_env_reads': [],
    'store_constructor_attempts': [],
    'synthetic_replay_store_constructions': [],
    'broker_constructor_attempts': [],
    'direct_no_fake_dotenv_imports': [],
}

def sensitive_env_key(key):
    name = os.fsdecode(os.fspath(key)).upper()
    return (
        name.startswith(("CTP_", "SIMNOW_", "BT_API_", "BTAPI_"))
        or any(tag in name for tag in ("PASSWORD", "PASSWD", "AUTH_CODE", "API_KEY", "SECRET", "CREDENTIAL", "ACCESS_TOKEN", "SESSION_TOKEN"))
    )


class GuardedEnviron:
    """Environment view that hides credential keys and rejects direct reads."""
    def __init__(self, source):
        self._source = source
    def __getitem__(self, key):
        if sensitive_env_key(key):
            state["credential_env_reads"].append(os.fsdecode(os.fspath(key)))
            raise AssertionError("credential environment read blocked")
        return self._source[key]
    def get(self, key, default=None):
        if sensitive_env_key(key):
            state["credential_env_reads"].append(os.fsdecode(os.fspath(key)))
            return default
        try:
            return self._source[key]
        except KeyError:
            return default
    def __contains__(self, key):
        if sensitive_env_key(key):
            state["credential_env_reads"].append(os.fsdecode(os.fspath(key)))
            return False
        return key in self._source
    def __iter__(self):
        return (key for key in self._source if not sensitive_env_key(key))
    def __len__(self):
        return sum(1 for _ in self.__iter__())
    def __setitem__(self, key, value):
        if sensitive_env_key(key):
            raise AssertionError("credential environment mutation blocked")
        self._source[key] = value
    def __delitem__(self, key):
        if sensitive_env_key(key):
            raise AssertionError("credential environment mutation blocked")
        del self._source[key]
    def copy(self):
        return {key: self._source[key] for key in self}
    def setdefault(self, key, default=None):
        if sensitive_env_key(key):
            state["credential_env_reads"].append(os.fsdecode(os.fspath(key)))
            raise AssertionError("credential environment access blocked")
        return self._source.setdefault(key, default)
    def update(self, *args, **kwargs):
        values = dict(*args, **kwargs)
        for key, value in values.items():
            self[key] = value
    def pop(self, key, default=...):
        if sensitive_env_key(key):
            state["credential_env_reads"].append(os.fsdecode(os.fspath(key)))
            if default is ...:
                raise KeyError(key)
            return default
        if default is ...:
            return self._source.pop(key)
        return self._source.pop(key, default)


_raw_environ = os.environ
_raw_environ["TRADE_LOGGER_CONSOLE"] = "0"
os.environ = GuardedEnviron(_raw_environ)
def guarded_getenv(key, default=None):
    return os.environ.get(key, default)
os.getenv = guarded_getenv



def forbidden_module(name: str) -> bool:
    top = name.split('.', 1)[0].casefold()
    return (
        top == 'dotenv'
        or top in {
            'bt_api_py', 'bt_api_ctp', 'bt_api_execution',
            'thosttraderapi', 'thostmduserapi', 'thostftdctraderapi',
            'thostftdcmdapi', 'ctpapi', 'vnpy_ctp',
        }
        or top.startswith(('thost', 'cthost'))
    )


class OptionalImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if forbidden_module(fullname):
            state['optional_import_attempts'].append(fullname)
            raise ImportError('blocked by fresh isolated candidate QA')
        return None


sys.meta_path.insert(0, OptionalImportBlocker())
_original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if forbidden_module(name):
        state['optional_import_attempts'].append(name)
        raise AssertionError(f'forbidden SDK/dotenv/native import: {name}')
    return _original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import


def file_text(path):
    try:
        return os.fsdecode(os.fspath(path))
    except (TypeError, ValueError, OSError):
        return ''


def guarded_open(original, label):
    def call(file, *args, **kwargs):
        value = file_text(file)
        leaf = os.path.basename(value).casefold()
        norm = os.path.abspath(value).casefold() if value else ''
        if leaf == '.env' or leaf.startswith('.env.'):
            state['env_reads'].append((label, value))
            raise AssertionError(f'.env read blocked: {value}')
        if 'runtime-ctp-private' in norm.replace('\\', '/'):
            state['forbidden_config_reads'].append((label, value))
            raise AssertionError(f'private CTP config read blocked: {value}')
        if leaf in {'config.yaml', 'config.yml', 'config.json', 'ctp.yaml', 'ctp.yml', 'ctp.json'}:
            if norm not in SAFE_CONFIGS:
                state['forbidden_config_reads'].append((label, value))
                raise AssertionError(f'non-fixture config read blocked: {value}')
            state['allowed_sample_config_reads'].append((label, value))
        return original(file, *args, **kwargs)
    return call


_original_open = builtins.open
_original_io_open = io.open
_original_os_open = os.open
builtins.open = guarded_open(_original_open, 'builtins.open')
io.open = guarded_open(_original_io_open, 'io.open')
os.open = guarded_open(_original_os_open, 'os.open')


def deny_network(*args, **kwargs):
    state['network_attempts'].append((args, kwargs))
    raise AssertionError('network call blocked by fresh isolated candidate QA')


_socket_methods = {
    'getaddrinfo': socket.getaddrinfo,
    'create_connection': socket.create_connection,
    'connect': socket.socket.connect,
    'connect_ex': socket.socket.connect_ex,
    'send': socket.socket.send,
    'sendall': socket.socket.sendall,
    'sendto': socket.socket.sendto,
}
socket.getaddrinfo = deny_network
socket.create_connection = deny_network
for _name in ('connect', 'connect_ex', 'send', 'sendall', 'sendto'):
    setattr(socket.socket, _name, deny_network)
_original_urlopen = urllib_request.urlopen
urllib_request.urlopen = deny_network
_original_http_connect = http.client.HTTPConnection.connect
_original_https_connect = http.client.HTTPSConnection.connect
http.client.HTTPConnection.connect = deny_network
http.client.HTTPSConnection.connect = deny_network

# Trap only CTP/native dynamic library loads; ordinary Python extension modules
# used by the offline framework/test environment remain available.
for _loader_name in ('CDLL', 'PyDLL', 'WinDLL'):
    if not hasattr(ctypes, _loader_name):
        continue
    _original_loader = getattr(ctypes, _loader_name)
    def _loader_guard(name, *args, _original=_original_loader, **kwargs):
        text = os.fsdecode(os.fspath(name)).casefold()
        if any(tag in text for tag in ('ctp', 'thost', 'traderapi', 'mduserapi')):
            state['native_loader_attempts'].append(text)
            raise AssertionError(f'CTP/native library load blocked: {text}')
        return _original(name, *args, **kwargs)
    setattr(ctypes, _loader_name, _loader_guard)

sys.path.insert(0, str(REPO))
os.environ['TRADE_LOGGER_CONSOLE'] = '0'

# Arm constructor traps on the Python wrapper classes. Importing these classes
# is needed by the compatibility modules, but no CTP Store/Broker may be made.
from backtrader.stores.btapistore import BtApiStore
from backtrader.brokers.btapibroker import BtApiBroker
_original_store_init = BtApiStore.__init__
_original_broker_init = BtApiBroker.__init__
def deny_store_init(self, *args, **kwargs):
    api = kwargs.get('api')
    module_name = type(api).__module__ if api is not None else ''
    api_module = sys.modules.get(module_name)
    module_path = Path(getattr(api_module, '__file__', '')).resolve() if api_module and getattr(api_module, '__file__', None) else None
    is_replay_client = (
        kwargs.get('provider') == 'ctp'
        and type(api).__name__ == 'ReplayClient'
        and module_name in {'ex013_1_run', 'ex013_2_run'}
        and module_path is not None
        and module_path.is_relative_to(QA / 'examples')
    )
    if is_replay_client:
        write_methods = {'submit_order_insert', 'submit_order_action', 'ReqOrderInsert', 'ReqOrderAction', 'insert_order', 'send_order', 'buy', 'sell', 'cancel'}
        present = write_methods.intersection(vars(type(api)))
        if present:
            state['store_constructor_attempts'].append(('ReplayClient exposes writer method', sorted(present)))
            raise AssertionError('synthetic replay client exposed a writer method')
        state['synthetic_replay_store_constructions'].append({
            'provider': kwargs.get('provider'),
            'api_type': type(api).__name__,
            'api_module': module_name,
            'api_source': str(module_path),
        })
        return _original_store_init(self, *args, **kwargs)
    state['store_constructor_attempts'].append((args, kwargs))
    raise AssertionError('non-ReplayClient BtApiStore construction blocked')
def deny_broker_init(self, *args, **kwargs):
    state['broker_constructor_attempts'].append((args, kwargs))
    raise AssertionError('BtApiBroker construction blocked')
BtApiStore.__init__ = deny_store_init
BtApiBroker.__init__ = deny_broker_init

# First import each candidate with no fake dotenv module installed. The outer
# import/file guards make a reintroduced import-time dotenv call fail instead
# of silently falling back through a test stub.
if 'dotenv' in sys.modules:
    raise AssertionError('dotenv was already present before inert-import check')
for label, rel in (
    ('013_1_midfreq_cross_arbitrage', 'examples/013_1_midfreq_cross_arbitrage/ctp_example_support.py'),
    ('013_2_highfreq_calendar_arbitrage', 'examples/013_2_highfreq_calendar_arbitrage/ctp_example_support.py'),
):
    module_name = 'direct_inert_candidate_' + label
    module_path = QA / rel
    direct_spec = importlib.util.spec_from_file_location(module_name, module_path)
    direct_module = importlib.util.module_from_spec(direct_spec)
    sys.modules[module_name] = direct_module
    direct_spec.loader.exec_module(direct_module)
    assert callable(direct_module.load_dotenv_if_available)
    state['direct_no_fake_dotenv_imports'].append(str(module_path))
    sys.modules.pop(module_name, None)

# Replay the focused fake tests from the source tree copy. Its own Bomb
# arguments and constructor aliases fail any config/Store/Broker access before
# the reviewed legacy guard raises.
spec = importlib.util.spec_from_file_location('isolated_partition4_focused_tests', FOCUSED)
focused_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = focused_module
spec.loader.exec_module(focused_module)
focused_suite = unittest.defaultTestLoader.loadTestsFromModule(focused_module)
focused_result = unittest.TextTestRunner(verbosity=2).run(focused_suite)
if not focused_result.wasSuccessful():
    raise SystemExit(1)
# The focused test installs a fake legacy module for its AST-only helper run.
sys.modules.pop('backtrader_runtime.legacy', None)
sys.modules.pop('backtrader_runtime', None)

# Replay the requested example pair regression against the freshly patched
# source copy. Only the two copied, checked-in YAML fixtures are allowlisted.
import pytest
pytest_exit = int(pytest.main(['-q', str(UNIT), '-p', 'no:cacheprovider']))

hashes = {}
for rel in (
    'examples/013_1_midfreq_cross_arbitrage/ctp_example_support.py',
    'examples/013_2_highfreq_calendar_arbitrage/ctp_example_support.py',
):
    hashes[rel] = hashlib.sha256((QA / rel).read_bytes()).hexdigest().upper()

summary = {
    'schema': 'ac41-63-partition4-r2-independent-qa.v1',
    'fresh_copy': str(QA),
    'focused_tests': {'run': focused_result.testsRun, 'failures': len(focused_result.failures), 'errors': len(focused_result.errors)},
    'unit_pytest_exit_code': pytest_exit,
    'patched_source_sha256': hashes,
    'guards': {
        'optional_import_attempts': state['optional_import_attempts'],
        'credential_env_read_attempt_count_blocked_to_empty': len(state['credential_env_reads']),
        'credential_env_values_read': False,
        'direct_no_fake_dotenv_imports': state['direct_no_fake_dotenv_imports'],
        'native_loader_attempts': state['native_loader_attempts'],
        'network_attempt_count': len(state['network_attempts']),
        'env_read_attempts': state['env_reads'],
        'forbidden_config_read_attempts': state['forbidden_config_reads'],
        'allowed_synthetic_yaml_reads': state['allowed_sample_config_reads'],
        'BtApiStore_constructor_attempts': len(state['store_constructor_attempts']),
        'allowed_synthetic_ReplayClient_Store_constructions': state['synthetic_replay_store_constructions'],
        'BtApiBroker_constructor_attempts': len(state['broker_constructor_attempts']),
    },
    'main_tree_modified_by_qa': False,
}
report = QA / 'independent-qa-result.json'
report.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, indent=2))

bad = (
    pytest_exit != 0
    or state['optional_import_attempts']
    or state['native_loader_attempts']
    or state['network_attempts']
    or state['env_reads']
    or state['forbidden_config_reads']
    or state['store_constructor_attempts']
    or state['broker_constructor_attempts']
)
raise SystemExit(1 if bad else 0)
