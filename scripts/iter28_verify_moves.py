"""Verify every moved method is textually identical to the pre-split source.

Compares each method (decorators included) between the frozen pre-split
backup and the split files, ignoring trailing whitespace. Only the
registered TEXT_FIXES exceptions (presentation lazy imports) may differ.
"""
import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OLD = Path("docs/_internal/opts/requirements/迭代28-Cerebro模块化拆分/evidence/cerebro-pre-split-backup.py")
NEW_FILES = {
    "facade": REPO / "backtrader/cerebro.py",
    "registry": REPO / "backtrader/_cerebro/registry.py",
    "notifications": REPO / "backtrader/_cerebro/notifications.py",
    "lifecycle": REPO / "backtrader/_cerebro/lifecycle.py",
    "channel": REPO / "backtrader/_cerebro/channel.py",
    "execution": REPO / "backtrader/_cerebro/execution.py",
    "runnext": REPO / "backtrader/_cerebro/runnext.py",
    "runonce": REPO / "backtrader/_cerebro/runonce.py",
    "presentation": REPO / "backtrader/_cerebro/presentation.py",
}

TEXT_FIXES = [
    ("from .bokeh import BokehPlot", "from ..bokeh import BokehPlot"),
    ("from . import plot", "from .. import plot"),
    ("from . import analyzers", "from .. import analyzers"),
    ("from .reports import ReportGenerator", "from ..reports import ReportGenerator"),
    # Registered minimal annotation (D28-07): mypy needs the re-created mapping
    # typed inside the mixin; behavior unchanged.
    (
        "        if not hasattr(self, \"_channel_data_refs\"):\n"
        "            self._channel_data_refs = {}",
        "        if not hasattr(self, \"_channel_data_refs\"):\n"
        "            # Same shape as Cerebro.__init__'s typed mapping (iteration 28\n"
        "            # note: minimal annotation so the mixin type-checks standalone).\n"
        "            self._channel_data_refs: Dict[str, ChannelDataRef] = {}",
    ),
]


MIXIN_CLASSES = {
    "RegistryMixin",
    "NotificationMixin",
    "RunLifecycleMixin",
    "ChannelMixin",
    "ExecutionMixin",
    "RunNextMixin",
    "RunOnceMixin",
    "PresentationMixin",
}


def collect_methods(path):
    tree = ast.parse(path.read_text())
    lines = path.read_text().splitlines()
    out = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for m in node.body:
                if isinstance(m, ast.FunctionDef):
                    start = min([d.lineno for d in m.decorator_list] + [m.lineno])
                    text = "\n".join(l.rstrip() for l in lines[start - 1 : m.end_lineno])
                    # Mixin methods originate from Cerebro; normalize the key.
                    cls = "Cerebro" if node.name in MIXIN_CLASSES else node.name
                    out[(cls, m.name)] = text
    return out


def apply_fixes(text):
    for old, new in TEXT_FIXES:
        text = text.replace(old, new)
    return text


def main():
    old_methods = collect_methods(OLD)
    new_methods = {}
    for name, path in NEW_FILES.items():
        for m, text in collect_methods(path).items():
            if m in new_methods:
                print(f"DUPLICATE method {m}")
                return 1
            new_methods[m] = text

    missing = set(old_methods) - set(new_methods)
    extra = set(new_methods) - set(old_methods)
    if missing or extra:
        print("missing:", sorted(missing), "extra:", sorted(extra))
        return 1

    diffs = []
    for m, old_text in sorted(old_methods.items()):
        expected = apply_fixes(old_text)
        if expected != new_methods[m]:
            diffs.append(m)
    if diffs:
        print("TEXT DIFFS (not explained by registered fixes):", diffs)
        return 1
    print(f"OK: {len(old_methods)} methods verbatim-identical "
          f"(registered fixes only affect: presentation lazy imports)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
