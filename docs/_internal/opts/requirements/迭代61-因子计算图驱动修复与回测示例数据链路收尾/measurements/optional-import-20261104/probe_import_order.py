import os, subprocess, sys

code = r"""
import importlib, importlib.abc, importlib.util, sys
order, *roots = sys.argv[1:]
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if any(fullname == root or fullname.startswith(root + ".") for root in roots):
   raise ModuleNotFoundError("blocked optional dependency: " + fullname)
  return None
sys.meta_path.insert(0, Block())
if order == "strategy-first":
 module=importlib.import_module("backtrader.strategies.factor_strategy")
 research=importlib.import_module("backtrader.research")
else:
 research=importlib.import_module("backtrader.research")
 module=importlib.import_module("backtrader.strategies.factor_strategy")
strategies=importlib.import_module("backtrader.strategies")
assert module.FactorStrategy.__module__ == "backtrader.strategies.factor_strategy"
assert not hasattr(research,"FactorStrategy")
assert not hasattr(strategies,"FactorStrategy")
assert importlib.util.find_spec("backtrader.research.factor_strategy") is None
try:
 importlib.import_module("backtrader.research.factor_strategy")
except ModuleNotFoundError as exc:
 assert exc.name == "backtrader.research.factor_strategy"
else:
 raise AssertionError("legacy module unexpectedly importable")
for root in roots:
 assert not any(name == root or name.startswith(root + ".") for name in sys.modules)
print("ok", order, ",".join(roots) or "available", module.__file__)
"""
for light in (False, True):
 for order in ("research-first", "strategy-first"):
  for roots in ((), ("pandas",), ("fincore",), ("pandas", "fincore")):
   env=os.environ.copy()
   if light: env["BACKTRADER_LIGHT_IMPORT"]="1"
   else: env.pop("BACKTRADER_LIGHT_IMPORT",None)
   result=subprocess.run([sys.executable,"-c",code,order,*roots], env=env, capture_output=True, text=True, timeout=30)
   print("light="+str(light),"blocked="+str(roots),"status="+str(result.returncode),result.stdout.strip(),flush=True)
   if result.returncode:
    print(result.stderr,flush=True)
    raise SystemExit(result.returncode)
