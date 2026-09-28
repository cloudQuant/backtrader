import importlib.abc
import ipaddress
import json
import os
import socket
import sys
log_path=os.environ.get("QA_GUARD_LOG")
def record(kind,value):
    if log_path:
        with open(log_path,"a",encoding="utf-8") as stream:
            stream.write(json.dumps({"kind":kind,"value":value},sort_keys=True)+"\n")
forbidden=("_ctp","bt_api_ctp","bt_api_py","ctp")
class BlockForbidden(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==item or fullname.startswith(item+".") for item in forbidden):
            record("forbidden_import",fullname)
            raise ImportError("QA-only forbidden CTP import blocked")
        return None
sys.meta_path.insert(0,BlockForbidden())
def is_loopback_address(address):
    if not isinstance(address,tuple) or not address:
        return False
    host=address[0]
    if not isinstance(host,str):
        return False
    if host.lower()=="localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%",1)[0]).is_loopback
    except ValueError:
        return False
_original_connect=socket.socket.connect
_original_connect_ex=socket.socket.connect_ex
_original_create_connection=socket.create_connection
_original_getaddrinfo=socket.getaddrinfo
def guarded_connect(self,address):
    if is_loopback_address(address):
        return _original_connect(self,address)
    record("external_network_call","socket.connect")
    raise AssertionError("QA-only external network operation blocked")
def guarded_connect_ex(self,address):
    if is_loopback_address(address):
        return _original_connect_ex(self,address)
    record("external_network_call","socket.connect_ex")
    raise AssertionError("QA-only external network operation blocked")
def guarded_create_connection(address,*args,**kwargs):
    if is_loopback_address(address):
        return _original_create_connection(address,*args,**kwargs)
    record("external_network_call","socket.create_connection")
    raise AssertionError("QA-only external network operation blocked")
def guarded_getaddrinfo(host,*args,**kwargs):
    if isinstance(host,str) and host.lower()=="localhost":
        return _original_getaddrinfo(host,*args,**kwargs)
    try:
        if isinstance(host,str) and ipaddress.ip_address(host.split("%",1)[0]).is_loopback:
            return _original_getaddrinfo(host,*args,**kwargs)
    except ValueError:
        pass
    record("external_network_call","socket.getaddrinfo")
    raise AssertionError("QA-only external name resolution blocked")
socket.socket.connect=guarded_connect
socket.socket.connect_ex=guarded_connect_ex
socket.create_connection=guarded_create_connection
socket.getaddrinfo=guarded_getaddrinfo