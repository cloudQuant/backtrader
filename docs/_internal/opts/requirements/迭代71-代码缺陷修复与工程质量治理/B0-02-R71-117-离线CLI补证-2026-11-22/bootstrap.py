import os,sys,runpy
root=os.path.dirname(os.path.abspath(__file__))
revision=sys.argv[1]
sys.path.insert(0,os.path.join(root,revision))
blocked=[]
def audit(event,args):
 if event in ("socket.connect","socket.bind","socket.getaddrinfo","subprocess.Popen","os.system"):
  blocked.append(event);raise RuntimeError("forbidden_network_or_process")
 if event=="open" and args and isinstance(args[0],(str,bytes,os.PathLike)):
  path=os.path.normcase(os.path.abspath(os.fsdecode(args[0])))
  allowed=(os.path.normcase(root),os.path.normcase(sys.base_prefix),os.path.normcase(os.path.abspath("C:/Windows/System32")))
  if not any(path==x or path.startswith(x+os.sep) for x in allowed):
   blocked.append("open_outside_public_roots");raise RuntimeError("outside_public_roots")
  name=os.path.basename(path).lower()
  if name==".env" or name.startswith(".env.") or name in ("config.yaml","config.yml","credentials.json"):
   blocked.append("private_input");raise RuntimeError("private_input")
sys.addaudithook(audit)
sys.argv=["backtrader.btrun.btrun","--data","bars.csv","--format","btcsv","--nostdstats","--writer","csv=True"]
try: runpy.run_module("backtrader.btrun.btrun",run_name="__main__")
finally: print("PUBLIC_BLOCKED_CATEGORIES",repr(blocked),flush=True)
