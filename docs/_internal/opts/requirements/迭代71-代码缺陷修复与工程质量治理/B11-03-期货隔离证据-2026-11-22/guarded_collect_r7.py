import os, sys, pathlib, threading, _thread
root = pathlib.Path(__file__).resolve().parent
bt = root / "bt"
sdk = root / "sdk"
base = root / "base" / "src"
tmp = root / "tmp"
sysroot = os.environ.get("SystemRoot", "C:\\Windows")
prefix = pathlib.Path(sys.base_prefix)
env = {
 "SystemRoot": sysroot, "WINDIR": sysroot,
 "PATH": os.pathsep.join([str(prefix), str(prefix / "Library" / "bin"), str(pathlib.Path(sysroot) / "System32")]),
 "TEMP": str(tmp), "TMP": str(tmp), "PYTEST_DISABLE_PLUGIN_AUTOLOAD":"1",
 "BT_SKIP_PYTEST_TMP_CLEANUP":"1",
}
os.environ.clear(); os.environ.update(env)
stdlib = prefix / "Lib"
dlls = prefix / "DLLs"
site = stdlib / "site-packages"
allowed_roots = tuple(os.path.normcase(os.path.realpath(str(x))) for x in (root, stdlib, dlls, pathlib.Path(sysroot) / "System32"))
write_root = os.path.normcase(os.path.realpath(str(root)))
denials = {}
blocked_events = {}
blocked_stacks = []
def reject(category):
 denials[category] = denials.get(category, 0) + 1
 raise PermissionError("isolation guard: " + category)
def allowed(path, write=False):
 if isinstance(path, int): return True
 try:
  raw = os.fsdecode(path)
 except (TypeError, ValueError):
  return False
 canonical = os.path.normcase(os.path.realpath(raw))
 parts = pathlib.PureWindowsPath(canonical).parts
 if any(part.lower() in (".env","config.yaml","config.yml","credentials","secrets",".codex") for part in parts):
  return False
 targets=(write_root,) if write else allowed_roots
 for parent in targets:
  try:
   if os.path.commonpath([canonical, parent]) == parent: return True
  except ValueError:pass
 return False
def audit(event, args):
 if event.startswith("socket.") or event in ("subprocess.Popen","os.system","os.exec","os.spawn","_winapi.CreateProcess","ctypes.dlopen"):
  blocked_events[event] = blocked_events.get(event, 0) + 1
  if event == "socket.__new__":
   frame = sys._getframe(1); stack = []
   while frame is not None and len(stack) < 12:
    stack.append(str(frame.f_globals.get("__name__", "?"))+":"+frame.f_code.co_name)
    frame=frame.f_back
   blocked_stacks.append(stack)
  reject("external_operation")
 if event == "open":
  path = args[0]
  mode = args[1] if len(args)>1 else None
  flags = args[2] if len(args)>2 else 0
  write = isinstance(mode,str) and any(c in mode for c in "wax+")
  if isinstance(flags,int):
   write = write or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
  if not allowed(path,write):reject("file_write" if write else "file_read")
 if event in ("os.listdir","os.scandir") and args and args[0] is not None and not allowed(args[0]):
  reject("directory_read")
 if event in ("os.remove","os.rmdir","os.mkdir","os.chdir","os.rename","os.replace","os.link","os.symlink"):
  paths=args[:2] if event in ("os.rename","os.replace","os.link","os.symlink") else args[:1]
  if any(not allowed(path,True) for path in paths):reject("filesystem_mutation")
sys.addaudithook(audit)
def no_thread(*args,**kwargs): reject("thread_start")
threading.Thread.start=no_thread
_thread.start_new_thread=no_thread
checks=[]
def expect_denial(name,call):
 before=sum(denials.values())
 try:call()
 except PermissionError:
  if sum(denials.values())!=before+1:raise RuntimeError("selfcheck counter mismatch")
  checks.append(name);return
 raise RuntimeError("guard selfcheck failed: "+name)
expect_denial("private_read",lambda:open("C:/Users/yunji/.codex/futures_guard_nonexistent","rb"))
expect_denial("outside_write",lambda:open("D:/temp/futures_guard_nonexistent","wb"))
expect_denial("network",lambda:sys.audit("socket.connect",None,("127.0.0.1",1)))
expect_denial("process",lambda:sys.audit("subprocess.Popen","denied",[],None,None))
expect_denial("native_load",lambda:sys.audit("ctypes.dlopen","denied"))
expect_denial("thread",lambda:threading.Thread(target=lambda:None).start())
print("GUARD_SELFCHECKS",len(checks),flush=True)
denials.clear(); blocked_events.clear(); blocked_stacks.clear()
sys.path[:0]=[str(bt),str(sdk),str(base),str(site)]
import socket
socket.gethostname = lambda: "synthetic-futures-audit"
import pytest
import types, importlib.machinery
parent = types.ModuleType("backtrader")
parent.__file__ = str(bt/"backtrader"/"__init__.py")
parent.__path__ = [str(bt/"backtrader")]
parent.__package__ = "backtrader"
parent.__spec__ = importlib.machinery.ModuleSpec("backtrader", loader=None, is_package=True)
parent.__spec__.submodule_search_locations = parent.__path__
sys.modules["backtrader"] = parent
print("PARENT_NAMESPACE", "SOURCE_SHELL_INITIALIZER_NOT_EXECUTED", flush=True)
files=[
 "test_futures_sessions.py","test_futures_selection_io.py","test_futures_rollover_plan.py",
 "test_futures_main_contract.py","test_futures_expected_calendar.py","test_futures_calendar_evidence_roundtrip.py",
 "test_iter72_futures_type_and_export_fixes.py",
]
paths=[str(bt/"tests"/"unit"/"feeds"/name) for name in files]
result=pytest.main(["--collect-only","-q","-p","no:cacheprovider","-p","no:capture","--log-file",str(tmp/"pytest.log"),"--confcutdir",str(root),"--rootdir",str(root),*paths])
for name,expected in (("backtrader",bt),("bt_api_py",sdk),("bt_api_base",base)):
 module=sys.modules.get(name)
 actual=pathlib.Path(getattr(module,"__file__","")).resolve() if module is not None else None
 valid=actual is not None and os.path.commonpath([str(actual),str(expected)])==str(expected)
 print("ORIGIN",name,("PINNED_SOURCE_SHELL" if name=="backtrader" else "PINNED") if valid else "MISSING_OR_UNPINNED",flush=True)
 if not valid:result=2
modules = [(name,module) for name,module in sys.modules.items() if name.startswith("backtrader.futures")]
all_pinned = bool(modules) and all(
 pathlib.Path(getattr(module,"__file__","")).resolve().is_relative_to(bt.resolve())
 for name,module in modules
)
print("FUTURES_MODULE_ORIGINS",len(modules),"PINNED" if all_pinned else "INVALID",flush=True)
if not all_pinned:result=2
print("GUARD_CANDIDATE_DENIALS",denials,"EVENTS",blocked_events,"STACKS",blocked_stacks,flush=True)
print("PYTEST_EXIT",int(result),flush=True)
if denials:result=2
raise SystemExit(int(result))



