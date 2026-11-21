"""Contrib class inventory and narrowly scoped execution-mode checks.

Run the inventory with ``python -m tests.unit.indicators.test_iter71_contrib_coverage_audit``.
References are syntactic leads, not proof that a pytest node exercises a class.
Only the parametrized test below claims full-array mode parity for its named inputs;
it checks equality of declared minperiod, not its correctness against an oracle.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import math
from pathlib import Path

import backtrader as bt
import pytest

ROOT = Path(__file__).resolve().parents[3]
CONTRIB = ROOT / "backtrader" / "indicators" / "contrib"
TESTS = ROOT / "tests" / "unit" / "indicators"


def _refs(tree):
    """Syntactic name/attribute and exact string references; no semantic inference."""
    refs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            refs.setdefault(node.id, set()).add("name")
        elif isinstance(node, ast.Attribute):
            refs.setdefault(node.attr, set()).add("attribute")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            refs.setdefault(node.value, set()).add("string")
        elif isinstance(node, ast.alias):
            refs.setdefault(node.name.rsplit(".", 1)[-1], set()).add("import")
            if node.asname:
                refs.setdefault(node.asname, set()).add("import_alias")
    return refs


def inventory():
    tests = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.resolve() == Path(__file__).resolve():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        refs = _refs(tree)
        nodes = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                nodes.append((node.name, _refs(node)))
        tests.append((path.name, refs, nodes))

    rows = []
    for path in sorted(CONTRIB.glob("*.py")):
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        try:
            module = importlib.import_module("backtrader.indicators.contrib." + path.stem)
            import_error = None
        except ImportError as exc:
            module = None
            import_error = type(exc).__name__
        declarations = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        classes = {n.name for n in declarations}
        for node in declarations:
            obj = getattr(module, node.name, None) if module else None
            indicator = inspect.isclass(obj) and issubclass(obj, bt.Indicator)
            attrs = sorted({n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute) and n.attr in {"open", "high", "low", "close", "volume", "openinterest", "data0", "data1", "data2"}})
            references = []
            for filename, all_refs, nodes in tests:
                if node.name not in all_refs:
                    continue
                references.append({"file": filename, "kinds": sorted(all_refs[node.name]),
                                   "test_nodes": [name for name, refs in nodes if node.name in refs]})
            rows.append({"module": path.stem, "name": node.name,
                         "kind": "unresolved_import" if module is None else ("indicator" if indicator else "non_indicator_or_unresolved"),
                         "import_error_type": import_error,
                         "abstract_by_inspect": bool(inspect.isclass(obj) and inspect.isabstract(obj)),
                         "runtime_defined_here": bool(module and inspect.isclass(obj) and obj.__module__ == module.__name__),
                         "bases_source": [ast.get_source_segment(source, base) for base in node.bases],
                         "direct_input_hints_only": attrs,
                         "exported": node.name in getattr(module, "__all__", ()),
                         "same_object_module_exports": [name for name in getattr(module, "__all__", ())
                                                        if getattr(module, name, None) is obj],
                         "references": references})
        # Simple module-level assignment aliases; other dynamic aliases are not inferred.
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Name):
                continue
            if node.value.id not in classes:
                continue
            for target in node.targets:
                if module and isinstance(target, ast.Name) and getattr(module, target.id, None) is getattr(module, node.value.id, object()):
                    rows.append({"module": path.stem, "name": target.id, "kind": "assignment_alias", "alias_of": node.value.id})
    return rows


def test_inventory_classifies_all_source_declarations():
    rows = inventory()
    declarations = [row for row in rows if row["kind"] != "assignment_alias"]
    assert declarations
    assert all(row["runtime_defined_here"] for row in declarations if row["kind"] != "unresolved_import"), [
        (row["module"], row["name"]) for row in declarations
        if row["kind"] != "unresolved_import" and not row["runtime_defined_here"]
    ]


def _frame():
    pd = pytest.importorskip("pandas")
    count = 350
    close = [100 + i * .13 + (i * 7 % 13) * .47 + math.sin(i * .3) * 2.2 for i in range(count)]
    opens = [v - math.sin(i * .57) * 1.4 for i, v in enumerate(close)]
    return pd.DataFrame({"open": opens, "high": [max(a, b) + 1 + i % 3 * .2 for i, (a, b) in enumerate(zip(opens, close))],
                         "low": [min(a, b) - .9 - i % 4 * .1 for i, (a, b) in enumerate(zip(opens, close))],
                         "close": close, "volume": [1000 + i % 11 for i in range(count)]},
                        index=pd.date_range("2020-01-01", periods=count))


def _run(cls, runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = cls(self.data0)
        def stop(self):
            self.result = (self.indicator._minperiod,
                {alias: list(line.array) for alias, line in zip(self.indicator.lines.getlinealiases(), self.indicator.lines)})
    c = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=_frame()))
    c.addstrategy(Probe)
    return c.run()[0].result


def _compare(cls):
    period_next, lines_next = _run(cls, False)
    period_once, lines_once = _run(cls, True)
    assert period_next == period_once
    assert 1 <= period_next <= 350
    assert lines_next and lines_next.keys() == lines_once.keys()
    assert any(math.isfinite(v) for line in lines_next.values() for v in line[period_next - 1:])
    for alias, step in lines_next.items():
        batch = lines_once[alias]
        assert len(step) == len(batch) == 350, alias
        for index, (a, b) in enumerate(zip(step, batch)):
            if math.isnan(a):
                assert math.isnan(b), (alias, index, a, b)
            else:
                assert b == pytest.approx(a, rel=1e-12, abs=1e-12), (alias, index, a, b)


@pytest.mark.parametrize("module,name", [
    ("color_x_derivative", "ColorXDerivative"),
    ("jma_slope_indicator", "JMASlopeIndicator"),
])
def test_named_finite_ohlcv_complete_line_parity(module, name):
    cls = getattr(pytest.importorskip("backtrader.indicators.contrib." + module), name)
    _compare(cls)


if __name__ == "__main__":
    print(json.dumps(inventory(), ensure_ascii=False, indent=2))
