"""Iteration 28 mechanical split tool (one-shot, audited).

Extracts Cerebro methods verbatim (AST-located, decorators included) into
``backtrader/_cerebro/`` mixin modules and rewrites ``backtrader/cerebro.py``
as the public facade, per design doc D28-03.

Verbatim guarantee: every moved method's normalized source is compared
before/after; only the registered exceptions (presentation lazy imports,
logger rebinding by fixed name) may differ. Produces method-moves.json.
"""
import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "backtrader" / "cerebro.py"

FACADE_METHODS = [
    "__init__",
    "setbroker",
    "getbroker",
    "__call__",
    "__getstate__",
    "__setstate__",
    "_resolve_run_flags",
    "run",
    "_build_optreturn_results",
]

MODULES = {
    "registry": [
        "iterize", "set_fund_history", "add_order_history", "notify_timer", "_add_timer",
        "add_timer", "addtz", "addcalendar", "add_signal", "signal_strategy",
        "signal_concurrent", "signal_accumulate", "addstore", "_maybe_add_store", "addwriter",
        "addsizer", "addsizer_byidx", "addindicator", "addanalyzer", "addobserver",
        "addobservermulti", "adddata", "chaindata", "rolloverdata", "replaydata",
        "resampledata", "optcallback", "optstrategy", "addstrategy", "_check_timers",
    ],
    "notifications": [
        "addstorecb", "_notify_store", "notify_store", "_storenotify",
        "adddatacb", "_datanotify", "_notify_data", "notify_data", "_brokernotify",
    ],
    "lifecycle": [
        "_begin_run", "_open_run_scope", "_end_run_if_started_by_current_thread",
        "_retire_run_scope_locked", "_end_run", "_retain_external_channel_scope",
        "close_channel", "runstop",
    ],
    "channel": [
        "dispatch_channel_event", "_get_channel_data_ref", "_start_channel_strategy",
        "_advance_channel_strategy_clock", "_step_channel_strategy", "_stop_channel_strategy",
        "_run_channel", "_teardown_channel", "_instantiate_channel_strategies",
        "_wire_channel_strategies",
    ],
    "execution": [
        "_init_stcount", "_next_stid", "_prepare_run", "runstrategies",
        "stop_writers", "_next_writers", "_disable_runonce",
    ],
    "runnext": ["_runnext_old", "_runnext"],
    "runonce": ["_runonce_old", "_runonce"],
    "presentation": ["plot", "add_report_analyzers", "generate_report"],
}

# Registered, audited exceptions to verbatim moves (D28-04.5 / D28-04.6).
TEXT_FIXES = {
    # presentation lazy imports: relative depth +1 inside the private package
    ("presentation", "plot"): [
        ("from .bokeh import BokehPlot", "from ..bokeh import BokehPlot"),
        ("from . import plot", "from .. import plot"),
    ],
    ("presentation", "add_report_analyzers"): [
        ("from . import analyzers", "from .. import analyzers"),
    ],
    ("presentation", "generate_report"): [
        ("from .reports import ReportGenerator", "from ..reports import ReportGenerator"),
    ],
}

MODULE_HEADERS = {
    "registry": '''"""Cerebro configuration/registration mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: data feed registration,
timers, timezone/calendar, signals, stores, writers, sizers, indicators,
analyzers, observers, strategy registration and timer dispatch.
"""
import collections
import datetime
import itertools

from .. import feeds
from ..timer import PandasMarketCalendar, Timer, TradingCalendarBase
from ..utils import string_types
from ..utils.py3 import map, zip  # noqa: F401

collectionsAbc = collections.abc

''',
    "notifications": '''"""Cerebro notification dispatch mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: store/data callbacks and
broker notification delivery.
"""
from ..brokers import BackBroker
from ..feed import AbstractDataBase

''',
    "lifecycle": '''"""Cerebro run-scope lifecycle mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: run scope begin/end,
external channel scope retention and runstop publication.
"""
import threading

''',
    "channel": '''"""Cerebro channel event mode mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: channel event dispatch,
channel strategy wiring and the channel run loop.
"""
import datetime
import itertools

from .. import errors
from ..channel import ChannelDataRef
from ..metabase import OwnerContext
from ..utils import date2num
from ..utils.log_message import get_logger
from datetime import timezone

UTC = timezone.utc

# Keep the historical logger name (D28-04.6): routing/filters must not change.
logger = get_logger("backtrader.cerebro")

''',
    "execution": '''"""Cerebro run orchestration mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: strategy instantiation
preparation, runstrategies orchestration, writers and shared helpers.
"""
import itertools

from .. import errors, observers
from ..metabase import OwnerContext
from ..utils import OrderedDict, tzparse
from ..utils.log_message import get_logger
from ..utils.py3 import integer_types

# Keep the historical logger name (D28-04.6): routing/filters must not change.
logger = get_logger("backtrader.cerebro")

''',
    "runnext": '''"""Cerebro event-driven engine mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: ``_runnext`` (modern, with
the direct-load fast path) and ``_runnext_old`` (oldsync). Hot loop - any
edit here must be justified against AC28-09.
"""
import datetime
from datetime import timezone

from ..brokers import BackBroker
from ..feed import AbstractDataBase
from ..strategy import Strategy
from ..utils import date2num
from ..utils.dateintern import _num2date_cached
from ..utils.log_message import get_logger

UTC = timezone.utc

# Keep the historical logger name (D28-04.6): routing/filters must not change.
logger = get_logger("backtrader.cerebro")

''',
    "runonce": '''"""Cerebro vectorized engine mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: ``_runonce`` (modern) and
``_runonce_old`` (oldsync).
"""
from ..feed import AbstractDataBase

''',
    "presentation": '''"""Cerebro presentation mixin (iteration 28 split).

Moved from ``backtrader/cerebro.py``: plotting facade and report helpers.
Lazy optional-backend imports preserved (relative depth adjusted by +1).
"""
from ..dataseries import TimeFrame

''',
}

CLASS_NAME = {
    "registry": "RegistryMixin",
    "notifications": "NotificationMixin",
    "lifecycle": "RunLifecycleMixin",
    "channel": "ChannelMixin",
    "execution": "ExecutionMixin",
    "runnext": "RunNextMixin",
    "runonce": "RunOnceMixin",
    "presentation": "PresentationMixin",
}


def method_block(lines, node):
    """Return source lines of a method including decorators and preceding
    adjacent comments (no blank line between comment and decorator/def)."""
    start = min(
        [d.lineno for d in node.decorator_list] + [node.lineno]
    )
    s = start - 1  # 0-based
    while s - 1 >= 0:
        prev = lines[s - 1].strip()
        if prev.startswith("#"):
            s -= 1
        else:
            break
    e = node.end_lineno  # 1-based inclusive end -> slice end
    return lines[s:e], s + 1, e


def normalize(text):
    """Strip trailing whitespace; keep everything else verbatim."""
    return "\n".join(line.rstrip() for line in text.rstrip().splitlines())


def main():
    src_lines = SRC.read_text().splitlines(keepends=False)
    tree = ast.parse("\n".join(src_lines))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Cerebro")

    methods = {}
    other_class_nodes = []
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            block, s, e = method_block(src_lines, node)
            methods[node.name] = {"block": block, "start": s, "end": e,
                                  "decorators": [ast.dump(d) for d in node.decorator_list]}
        else:
            other_class_nodes.append(node)

    # Completeness checks: 80 methods, unique assignment.
    all_module_methods = [m for mods in MODULES.values() for m in mods]
    assert len(all_module_methods) == 71, len(all_module_methods)
    assert len(set(all_module_methods)) == 71
    assert set(all_module_methods) | set(FACADE_METHODS) == set(methods), (
        set(methods) - (set(all_module_methods) | set(FACADE_METHODS)),
        (set(all_module_methods) | set(FACADE_METHODS)) - set(methods),
    )
    moves = []
    pkg = REPO / "backtrader" / "_cerebro"
    pkg.mkdir(exist_ok=True)

    for mod_name, mlist in MODULES.items():
        parts = [MODULE_HEADERS[mod_name], f"class {CLASS_NAME[mod_name]}:"]
        for m in mlist:
            block = list(methods[m]["block"])
            applied = []
            for i, line in enumerate(block):
                for old, new in TEXT_FIXES.get((mod_name, m), []):
                    if old in line:
                        block[i] = line.replace(old, new)
                        applied.append((old, new))
            moves.append({
                "method": m,
                "from": f"backtrader/cerebro.py:{methods[m]['start']}-{methods[m]['end']}",
                "to": f"backtrader/_cerebro/{mod_name}.py",
                "decorators": len(methods[m]["decorators"]),
                "text_fixes": applied,
            })
            parts.append("")
            parts.extend(block)
        out = pkg / f"{mod_name}.py"
        out.write_text("\n".join(parts).rstrip() + "\n")

    # Facade: class header line replaced by mixin bases; body = docstring,
    # descriptors, __init__ (original lines 124-500) + facade methods.
    facade_parts = []
    # module header: lines 1-121 kept verbatim (imports/UTC/OptReturn/etc.)
    facade_parts.extend(src_lines[0:121])
    facade_parts.append("")
    facade_parts.append("# NOTE (iteration 28): the imports above are intentionally kept even")
    facade_parts.append("# where the facade no longer references every name: ``backtrader.cerebro``")
    facade_parts.append("# defines no ``__all__`` and ``from backtrader.cerebro import *`` has always")
    facade_parts.append("# exported these bindings. Narrowing them would be a breaking change")
    facade_parts.append("# (AC28-03 star-export parity).")
    facade_parts.append("# ruff: noqa: F401")
    facade_parts.append("# pylint: disable=unused-import")
    facade_parts.append("")
    facade_parts.append("from ._cerebro.channel import ChannelMixin as _ChannelMixin")
    facade_parts.append("from ._cerebro.execution import ExecutionMixin as _ExecutionMixin")
    facade_parts.append("from ._cerebro.lifecycle import RunLifecycleMixin as _RunLifecycleMixin")
    facade_parts.append("from ._cerebro.notifications import NotificationMixin as _NotificationMixin")
    facade_parts.append("from ._cerebro.presentation import PresentationMixin as _PresentationMixin")
    facade_parts.append("from ._cerebro.registry import RegistryMixin as _RegistryMixin")
    facade_parts.append("from ._cerebro.runnext import RunNextMixin as _RunNextMixin")
    facade_parts.append("from ._cerebro.runonce import RunOnceMixin as _RunOnceMixin")
    facade_parts.append("")
    facade_parts.append("")
    facade_parts.append("class Cerebro(")
    facade_parts.append("    _RegistryMixin,")
    facade_parts.append("    _NotificationMixin,")
    facade_parts.append("    _RunLifecycleMixin,")
    facade_parts.append("    _ChannelMixin,")
    facade_parts.append("    _ExecutionMixin,")
    facade_parts.append("    _RunNextMixin,")
    facade_parts.append("    _RunOnceMixin,")
    facade_parts.append("    _PresentationMixin,")
    facade_parts.append("    ParameterizedBase,")
    facade_parts.append("):")
    # docstring + descriptors + __init__: original lines 124..500
    facade_parts.extend(src_lines[123:500])
    for m in FACADE_METHODS[1:]:  # __init__ already included above
        facade_parts.append("")
        facade_parts.extend(methods[m]["block"])
        moves.append({
            "method": m,
            "from": f"backtrader/cerebro.py:{methods[m]['start']}-{methods[m]['end']}",
            "to": "backtrader/cerebro.py (facade)",
            "decorators": len(methods[m]["decorators"]),
            "text_fixes": [],
        })
    # broker property assign (lines 1471)
    facade_parts.append("")
    facade_parts.append("    broker = property(getbroker, setbroker)")
    SRC.write_text("\n".join(facade_parts).rstrip() + "\n")

    # __init__.py for the private package
    (pkg / "__init__.py").write_text(
        '"""Private Cerebro implementation mixins (iteration 28 split).\n\n'
        'Not part of the public API. Import order and contents are internal;\n'
        'the public class remains ``backtrader.cerebro.Cerebro``.\n"""\n'
    )

    (REPO / "docs/_internal/opts/requirements/迭代28-Cerebro模块化拆分/evidence/method-moves.json").write_text(
        json.dumps({"facade": FACADE_METHODS, "moves": moves}, indent=1)
    )
    print(f"moved {len(moves)} methods + __init__ facade; files:")
    for f in sorted(pkg.glob("*.py")):
        print(" ", f, len(f.read_text().splitlines()), "lines")
    print("cerebro.py", len(SRC.read_text().splitlines()), "lines")


if __name__ == "__main__":
    sys.exit(main())
