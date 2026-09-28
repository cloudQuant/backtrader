import importlib.abc
import json
import os
import socket
import sys

_BLOCKED = ('bt_api_py', 'bt_api_ctp', 'bt_api_execution', 'thosttrader', '_ctp', 'ctpbee', 'ctp_api')
_EVENTS = []
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in _BLOCKED):
            _EVENTS.append({'kind':'blocked_import','name':fullname})
            raise ImportError('QA blocked provider/native import: ' + fullname)
        return None
sys.meta_path.insert(0, _Block())
def _blocked_network(*args, **kwargs):
    _EVENTS.append({'kind':'blocked_network','name':'socket operation'})
    raise AssertionError('QA network guard')
socket.create_connection = _blocked_network
socket.getaddrinfo = _blocked_network
socket.socket.connect = _blocked_network
socket.socket.connect_ex = _blocked_network
socket.socket.sendto = _blocked_network
_path = os.environ.get('MECHANICAL_QA_GUARD_LOG')
if _path:
    import atexit
    atexit.register(lambda: open(_path, 'w', encoding='utf-8').write(json.dumps(_EVENTS, sort_keys=True)))
