import importlib.abc
import json
import os
import socket
import sys

log_path = os.environ.get("QA_GUARD_LOG")
def record(kind, value):
    if log_path:
        with open(log_path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"kind": kind, "value": value}, sort_keys=True) + "\n")

forbidden = ("_ctp", "bt_api_ctp", "bt_api_py", "ctp")
class BlockForbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == item or fullname.startswith(item + ".") for item in forbidden):
            record("forbidden_import", fullname)
            raise ImportError("QA-only forbidden CTP import blocked")
        return None
sys.meta_path.insert(0, BlockForbidden())

def block_network(*args, **kwargs):
    record("network_call", "socket")
    raise AssertionError("QA-only network operation blocked")
socket.create_connection = block_network
socket.getaddrinfo = block_network
socket.socket.connect = block_network
socket.socket.connect_ex = block_network