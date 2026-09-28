import atexit, importlib.abc, json, os, socket, sys
_BLOCKED = ('bt_api_py','bt_api_ctp','bt_api_execution_sdk','thosttrader','_thosttrader','ctpbee','ctp_api','_ctp')
_EVENTS = []
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in _BLOCKED):
            _EVENTS.append({'kind':'blocked_import','name':fullname})
            raise ImportError('QA blocked native/provider import: ' + fullname)
sys.meta_path.insert(0, _Block())
_original_connect = socket.socket.connect
_original_socketpair = socket.socketpair
_socketpair_depth = 0
def _blocked_network(*args, **kwargs):
    _EVENTS.append({'kind':'blocked_network','name':'socket operation'})
    raise AssertionError('QA network guard')
def _guarded_connect(sock, address):
    if _socketpair_depth:
        host = address[0] if isinstance(address, tuple) and address else None
        if host in ('127.0.0.1', '::1'):
            return _original_connect(sock, address)
    _EVENTS.append({'kind':'blocked_network','name':'socket.connect'})
    raise AssertionError('QA network guard')
def _local_socketpair(*args, **kwargs):
    global _socketpair_depth
    _socketpair_depth += 1
    try:
        _EVENTS.append({'kind':'local_ipc','name':'asyncio socketpair'})
        return _original_socketpair(*args, **kwargs)
    finally:
        _socketpair_depth -= 1
socket.create_connection = _blocked_network
socket.getaddrinfo = _blocked_network
socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _blocked_network
socket.socket.sendto = _blocked_network
socket.socketpair = _local_socketpair
_path = os.environ.get('V21_NATIVEFLOOR_QA_GUARD_LOG')
if _path:
    atexit.register(lambda: open(_path, 'w', encoding='utf-8').write(json.dumps(_EVENTS, sort_keys=True)))
