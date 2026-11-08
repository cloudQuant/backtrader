"""Best-effort test process guard: block network except explicit loopback and block CTP native."""
import importlib.abc
import importlib.machinery
import ipaddress
import os
import socket
import sys


def _local_host(host):
    if host in ('localhost', '127.0.0.1', '::1'):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def _socket_address(address):
    if isinstance(address, tuple) and address and not _local_host(address[0]):
        raise PermissionError('R19_OFFLINE_NON_LOOPBACK_BLOCKED')


def _zmq_endpoint(endpoint):
    if type(endpoint) is bytes:
        endpoint = endpoint.decode('ascii')
    if type(endpoint) is not str:
        raise PermissionError('R19_OFFLINE_INVALID_ENDPOINT')
    if endpoint.startswith(('inproc://', 'ipc://')):
        return
    if endpoint.startswith('tcp://'):
        authority = endpoint[6:]
        host = authority[1:authority.index(']')] if authority.startswith('[') and ']' in authority else authority.rsplit(':', 1)[0]
        if _local_host(host):
            return
    raise PermissionError('R19_OFFLINE_NON_LOOPBACK_BLOCKED')


class GuardedCTPLoader(importlib.abc.Loader):
    """Patch native factories immediately when the extension is first loaded."""
    def __init__(self, original):
        self.original = original

    def create_module(self, spec):
        return self.original.create_module(spec)

    def exec_module(self, module):
        self.original.exec_module(module)
        for name in ('CThostFtdcTraderApi_CreateFtdcTraderApi', 'CThostFtdcMdApi_CreateFtdcMdApi'):
            if not callable(getattr(module, name, None)):
                raise RuntimeError('R19_OFFLINE_CTP_NATIVE_FACTORY_GUARD_UNAVAILABLE')
            def deny_factory(*_args, **_kwargs):
                raise PermissionError('R19_OFFLINE_CTP_FACTORY_BLOCKED')
            setattr(module, name, deny_factory)


def _guard_zmq(module):
    socket_type = getattr(module, 'Socket', None)
    if socket_type is None:
        raise RuntimeError('R19_OFFLINE_ZMQ_GUARD_UNAVAILABLE')
    if getattr(socket_type, '_r17_guarded', False):
        return
    for name in ('connect', 'bind'):
        old = getattr(socket_type, name)
        def wrapper(self, address, *args, _old=old, **kwargs):
            _zmq_endpoint(address)
            return _old(self, address, *args, **kwargs)
        setattr(socket_type, name, wrapper)
    socket_type._r17_guarded = True


class GuardedZmqLoader(importlib.abc.Loader):
    def __init__(self, original):
        self.original = original
    def create_module(self, spec):
        return self.original.create_module(spec)
    def exec_module(self, module):
        self.original.exec_module(module)
        _guard_zmq(module)


class LazyZmqGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'zmq':
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        spec.loader = GuardedZmqLoader(spec.loader)
        return spec


class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'bt_api_ctp.ctp._ctp':
            return None
        if os.environ.get('R19_CTP_STRUCTS') != '1':
            raise ImportError('R19_OFFLINE_CTP_NATIVE_BLOCKED')
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            raise ImportError('R19_OFFLINE_CTP_NATIVE_NOT_FOUND')
        from pathlib import Path
        from origin_guard import TARGET, write
        if spec.origin is None or not Path(spec.origin).resolve().is_relative_to(TARGET):
            raise ImportError('R19_OFFLINE_CTP_ORIGIN_OUTSIDE_TARGET')
        write('resolved', {'module': fullname, 'origin': spec.origin})
        spec.loader = GuardedCTPLoader(spec.loader)
        return spec


def install():
    if getattr(socket, '_r11_offline_installed', False):
        return
    sys.meta_path.insert(0, NoNative())
    sys.meta_path.insert(0, LazyZmqGuard())
    if 'zmq' in sys.modules:
        _guard_zmq(sys.modules['zmq'])
    for name in ('connect', 'connect_ex', 'bind'):
        old = getattr(socket.socket, name)
        def wrapper(self, address, _old=old):
            _socket_address(address)
            return _old(self, address)
        setattr(socket.socket, name, wrapper)
    original_sendto = socket.socket.sendto
    def guarded_sendto(self, data, *args):
        if not args:
            raise PermissionError('R19_OFFLINE_INVALID_ENDPOINT')
        _socket_address(args[-1])
        return original_sendto(self, data, *args)
    socket.socket.sendto = guarded_sendto
    if hasattr(socket.socket, 'sendmsg'):
        original_sendmsg = socket.socket.sendmsg
        def guarded_sendmsg(self, buffers, ancdata=(), flags=0, address=None):
            if address is not None:
                _socket_address(address)
                return original_sendmsg(self, buffers, ancdata, flags, address)
            return original_sendmsg(self, buffers, ancdata, flags)
        socket.socket.sendmsg = guarded_sendmsg
    original_dns = socket.getaddrinfo
    def guarded_dns(host, *args, **kwargs):
        if host is not None and not _local_host(host):
            raise PermissionError('R19_OFFLINE_DNS_BLOCKED')
        return original_dns(host, *args, **kwargs)
    socket.getaddrinfo = guarded_dns
    for name in ('gethostbyname', 'gethostbyname_ex', 'gethostbyaddr'):
        old = getattr(socket, name)
        def guarded_lookup(host, _old=old):
            if not _local_host(host):
                raise PermissionError('R19_OFFLINE_DNS_BLOCKED')
            return _old(host)
        setattr(socket, name, guarded_lookup)
    socket._r11_offline_installed = True
