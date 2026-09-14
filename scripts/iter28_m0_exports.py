"""M0 baseline: star exports, API signatures, descriptors, object identity.

Run in a fresh process for each mode:
    python scripts/iter28_m0_exports.py default
    python scripts/iter28_m0_exports.py light
"""
import json
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "default"

if mode == "light":
    import os

    os.environ["BACKTRADER_LIGHT_IMPORT"] = "1"

# Actual star-import semantics (not dir()).
ns = {}
exec("from backtrader.cerebro import *", ns)
cerebro_star = sorted(k for k in ns if not k.startswith("_"))

# Root namespace object identity checks.
import backtrader as bt
import backtrader.cerebro as cerebro_mod

root_ns = sorted(k for k in vars(bt) if not k.startswith("_"))

report = {
    "mode": mode,
    "cerebro_star": cerebro_star,
    "root_namespace": root_ns,
    "identity": {
        "bt_Cerebro_is_module_Cerebro": bt.Cerebro is cerebro_mod.Cerebro,
        "cerebro_module": cerebro_mod.Cerebro.__module__,
        "cerebro_qualname": cerebro_mod.Cerebro.__qualname__,
        "optreturn_module": cerebro_mod.OptReturn.__module__,
        "optreturn_qualname": cerebro_mod.OptReturn.__qualname__,
        "bt_feeds_is_cerebro_feeds": getattr(bt, "feeds", None) is getattr(cerebro_mod, "feeds", None),
        "bt_Strategy_is_cerebro_Strategy": getattr(bt, "Strategy", None)
        is getattr(cerebro_mod, "Strategy", None),
        "bt_Timer_is_cerebro_Timer": getattr(bt, "Timer", None) is getattr(cerebro_mod, "Timer", None),
        "cerebro_file": cerebro_mod.__file__,
    },
    # Class-level API surface of Cerebro (signatures + decorators).
    "cerebro_api": {},
    "descriptors": {},
}

import inspect

for name, obj in sorted(vars(cerebro_mod.Cerebro).items()):
    if name.startswith("__") and name not in ("__init__", "__call__", "__getstate__", "__setstate__"):
        continue
    entry = {"kind": type(obj).__name__}
    try:
        if isinstance(obj, (staticmethod, classmethod)):
            fn = obj.__func__
            entry["decorator"] = type(obj).__name__
            entry["signature"] = str(inspect.signature(fn))
            entry["module"] = getattr(fn, "__module__", None)
        elif callable(obj):
            entry["signature"] = str(inspect.signature(obj))
            entry["module"] = getattr(obj, "__module__", None)
        elif isinstance(obj, property):
            entry["fget_module"] = getattr(obj.fget, "__module__", None)
    except (ValueError, TypeError):
        entry["signature"] = "<unavailable>"
    report["cerebro_api"][name] = entry

# Parameter descriptors: default/type/doc per key, in declared order.
from backtrader.parameters import ParameterDescriptor

for pname, pobj in vars(cerebro_mod.Cerebro).items():
    if isinstance(pobj, ParameterDescriptor):
        report["descriptors"][pname] = {
            "default": repr(pobj.default),
            "type": getattr(pobj.type_, "__name__", None) if pobj.type_ else None,
            "doc": pobj.doc,
        }

print(json.dumps(report, indent=1, sort_keys=True))
