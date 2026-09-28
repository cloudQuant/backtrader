"""Temporary source-QA guard: approved source roots, pytest-only fakes, loopback only."""
from __future__ import annotations
import importlib.abc, importlib.machinery, ipaddress, json, os, socket, stat, sys
from pathlib import Path

raw = os.environ.get("BT_API_TEST_SOURCE_ROOTS")
if not raw:
    raise RuntimeError("source origin guard requires BT_API_TEST_SOURCE_ROOTS")
mapping = json.loads(raw)
modules = {"parent":"bt_api_py","base":"bt_api_base","ctp":"bt_api_ctp","execution":"bt_api_execution","risk":"bt_api_risk","monitor":"bt_api_monitor","gateway":"bt_api_gateway","transport_zmq":"bt_api_transport_zmq","agent":"backtrader_agent","skills":"backtrader_skills","mcp":"backtrader_mcp"}
if set(mapping) != set(modules):
    raise RuntimeError("source map must contain exactly the approved eleven package keys")
expected = {modules[k]: Path(v).resolve(strict=True) for k,v in mapping.items()}
fixture_value = os.environ.get("BT_API_TEST_FIXTURE_ROOT")
if not fixture_value:
    raise RuntimeError("source guard requires BT_API_TEST_FIXTURE_ROOT")
fixture_root = Path(fixture_value).resolve(strict=True)
if not fixture_root.is_dir():
    raise RuntimeError("pytest fixture root is not a directory")
log_value = os.environ.get("BT_API_TEST_GUARD_LOG_ROOT")
if not log_value:
    raise RuntimeError("source guard requires BT_API_TEST_GUARD_LOG_ROOT")
log_root = Path(log_value).resolve()
log_root.mkdir(parents=True, exist_ok=True)
log_path = log_root / f"origin-guard-{os.getpid()}.jsonl"
REPARSE = 0x400

def _reparse(p):
    try: st = p.lstat()
    except FileNotFoundError: return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & REPARSE)

def _inside_fixture(path):
    try:
        lexical = Path(os.path.abspath(os.fspath(path)))
        rel = lexical.relative_to(fixture_root)
        Path(path).resolve(strict=False).relative_to(fixture_root)
    except (OSError, ValueError, RuntimeError): return False
    cur = fixture_root
    if _reparse(cur): return False
    for part in rel.parts:
        cur = cur / part
        if _reparse(cur): return False
    return True

def record(kind, **facts):
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"kind":kind,"pid":os.getpid(),**facts},sort_keys=True)+"\n")

def _loopback(host):
    if isinstance(host, bytes):
        try: host = host.decode("ascii")
        except UnicodeDecodeError: return False
    if not isinstance(host, str): return False
    host = host.strip().lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"): return True
    if host.startswith("[") and host.endswith("]"): host = host[1:-1]
    try: ip = ipaddress.ip_address(host)
    except ValueError: return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped.is_loopback
    return ip.is_loopback

def _host(addr): return addr[0] if isinstance(addr, tuple) and addr else addr
def _blocked(call, host):
    record("network-blocked",call=call,host=repr(host)[:160])
    raise RuntimeError("non-loopback network blocked by Iteration 41 QA guard")

class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        leaf=fullname.rsplit(".",1)[-1].lower()
        if leaf in {"_ctp","ctp_wrap"}:
            record("native-import-blocked",fullname=fullname)
            raise ImportError(f"native CTP import blocked: {fullname}")
        top=fullname.split(".",1)[0]; root=expected.get(top)
        if root is None: return None
        spec=importlib.machinery.PathFinder.find_spec(fullname,path)
        if spec is None: return None
        pkg=root/top
        if spec.origin and spec.origin not in {"built-in","frozen"}:
            origin=Path(spec.origin).resolve(strict=True)
            ok=(origin==pkg/"__init__.py" or origin==root/f"{top}.py") if fullname==top else (pkg in origin.parents or origin==pkg/"__init__.py")
            if ok:
                record("source-import",fullname=fullname,origin=str(origin)); return spec
            if _inside_fixture(origin):
                record("synthetic-origin-allowed",fullname=fullname,origin=str(origin)); return spec
            record("origin-rejected",fullname=fullname,origin=str(origin),expected_root=str(root))
            raise ImportError(f"wrong source origin for {fullname}: {origin}; expected under {pkg}")
        if not spec.origin and spec.submodule_search_locations:
            locs=[Path(x).resolve(strict=True) for x in spec.submodule_search_locations]
            if all(pkg in p.parents for p in locs):
                record("source-namespace",fullname=fullname,locations=[str(x) for x in locs]); return spec
        record("origin-rejected",fullname=fullname,origin=spec.origin)
        raise ImportError(f"unverified source origin for {fullname}: {spec!r}")

sys.meta_path.insert(0,Guard())
orig_connect=socket.socket.connect; orig_connect_ex=socket.socket.connect_ex
orig_bind=socket.socket.bind; orig_create=socket.create_connection
orig_addr=socket.getaddrinfo; orig_name=socket.gethostbyname; orig_reverse=socket.gethostbyaddr

def _connect(self,addr):
    if self.family==getattr(socket,"AF_UNIX",object()): return orig_connect(self,addr)
    h=_host(addr)
    if not _loopback(h): return _blocked("socket.connect",h)
    return orig_connect(self,addr)
def _connect_ex(self,addr):
    if self.family==getattr(socket,"AF_UNIX",object()): return orig_connect_ex(self,addr)
    h=_host(addr)
    if not _loopback(h): return _blocked("socket.connect_ex",h)
    return orig_connect_ex(self,addr)
def _bind(self,addr):
    if self.family==getattr(socket,"AF_UNIX",object()): return orig_bind(self,addr)
    h=_host(addr)
    if not _loopback(h): return _blocked("socket.bind",h)
    return orig_bind(self,addr)
def _create(addr,*a,**kw):
    h=_host(addr)
    if not _loopback(h): return _blocked("socket.create_connection",h)
    return orig_create(addr,*a,**kw)
def _addr(host,*a,**kw):
    if not _loopback(host): return _blocked("socket.getaddrinfo",host)
    return orig_addr(host,*a,**kw)
def _name(host):
    if not _loopback(host): return _blocked("socket.gethostbyname",host)
    return orig_name(host)
def _reverse(host):
    if not _loopback(host): return _blocked("socket.gethostbyaddr",host)
    return orig_reverse(host)
socket.socket.connect=_connect; socket.socket.connect_ex=_connect_ex; socket.socket.bind=_bind
socket.create_connection=_create; socket.getaddrinfo=_addr
socket.gethostbyname=_name; socket.gethostbyaddr=_reverse

def audit(event,args):
    if event=="open" and args:
        try: p=Path(os.fspath(args[0]))
        except (TypeError,ValueError,OSError): return
        if p.name.lower()=="config.yaml" and any(x.name.lower()=="runtime-ctp-private" for x in p.parents):
            if _inside_fixture(p):
                record("synthetic-config-allowed",path=str(p.resolve(strict=False))); return
            record("private-config-blocked",path=str(p.resolve(strict=False)))
            raise PermissionError("protected runtime CTP config blocked by source-QA guard")
sys.addaudithook(audit)
record("guard-started",expected={k:str(v) for k,v in expected.items()},fixture_root=str(fixture_root),network_policy="loopback-only")
