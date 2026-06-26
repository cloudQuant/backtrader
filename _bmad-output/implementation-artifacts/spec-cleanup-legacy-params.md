---
title: 'Cleanup Legacy Params'
type: 'refactor'
created: '2026-06-13'
status: 'done'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/_internal/_project/planning/project-context.md'
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** The explicit metaclasses are gone, but the parameter layer still creates dynamic empty parameter objects and maintains a separate legacy parameter path in `metabase.py`. This keeps broad metaprogramming behavior alive in a high-risk initialization path.

**Approach:** Keep public Backtrader compatibility (`self.p.foo`, `self.params.foo`, `_gettuple()`, `_getkwargs()`) while replacing dynamic per-instance empty parameter classes with the shared `parameters.ParameterManager` and `ParameterAccessor` implementation. Do not rewrite the Lines/LineIterator lifecycle in this iteration.

## Boundaries & Constraints

**Always:** Preserve public strategy, indicator, feed, store, and plotting parameter access. Keep `cls.params._gettuple()` and instance `self.p._getkwargs()` working for compatibility.

**Ask First:** Any change that would remove `ParamsMixin`, change `LineSeries` inheritance, remove dynamic Lines classes, or break original Backtrader-compatible `params = (...)` declarations.

**Never:** Reintroduce a metaclass, remove the line alias DSL, or collapse indicator registration into this iteration.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Legacy params instance | `params = (("period", 14),)` and object created with `period=20` | `obj.p.period == 20`, `obj.params.period == 20`, `_getkwargs()` includes `period` | Unknown parameter access remains compatible and returns default/`None` |
| Class params API | Existing code calls `DataCls.params._gettuple()` | Returns legacy tuple of `(name, default)` pairs in declaration order | No dynamic empty class required |
| No params fallback | Legacy class has no declared params | `self.p` exists and accepts attribute-style assignment | No `type("ParamsInstance", ...)` allocation |

</frozen-after-approval>

## Code Map

- `backtrader/parameters.py` -- modern parameter manager/accessor; add legacy schema factory here.
- `backtrader/metabase.py` -- old `ParamsMixin` and class param derivation; route instances through the modern accessor.
- `backtrader/strategy.py` -- manual strategy parameter initialization still creates dynamic fallback instances.
- `backtrader/store.py` -- store parameter helper uses dynamic empty `Params`.
- `backtrader/bokeh/app.py` -- Bokeh app parameter helper uses dynamic empty `Params`.
- `tests/unit/core/` -- parameter-system coverage.

## Tasks & Acceptance

**Execution:**
- [x] `backtrader/parameters.py` -- add a reusable legacy params schema/accessor backed by `ParameterManager`.
- [x] `backtrader/metabase.py` -- return the schema from legacy param derivation and remove dynamic `ParamsInstance` fallbacks.
- [x] `backtrader/strategy.py`, `backtrader/store.py`, `backtrader/bokeh/app.py` -- replace dynamic empty parameter objects with the shared factory.
- [x] `tests/unit/core/` -- add focused coverage for legacy accessor behavior and dynamic fallback removal.

**Acceptance Criteria:**
- Given a legacy `params` tuple, when an instance is initialized with overrides, then `.p`, `.params`, `_getitems()`, and `_getkwargs()` expose the expected values.
- Given class-level legacy params APIs, when `_gettuple()` is called, then declaration order and inherited defaults remain intact.
- Given the production package, when scanning for `type("ParamsInstance"` or `type("Params"` dynamic empty object creation, then no such runtime parameter fallback remains outside unrelated dynamic class generation.

## Design Notes

This iteration deliberately does not remove all broad metaprogramming. Lines and indicator class generation are core DSL compatibility points. The useful improvement here is to make old and new parameter instances share one runtime representation.

## Verification

**Commands:**
- `python -m py_compile backtrader/parameters.py backtrader/metabase.py backtrader/strategy.py backtrader/store.py backtrader/bokeh/app.py tests/unit/core/test_parameter_system.py` -- passed.
- `pytest tests/unit/core/test_parameter_system.py tests/unit/indicators -q` -- passed, 113 tests.
- `pytest tests/unit/core/test_parameterized_base.py tests/integration/test_improved_examples.py tests/integration/test_plot_plotly.py tests/integration/test_reports_module.py tests/unit/core/test_simple_classes.py tests/unit/core/test_param_manager.py tests/unit/core/test_cerebro.py tests/unit/feeds/test_yahoo_edge_cases.py tests/unit/analyzers/test_analyzer_drawdown.py tests/unit/analyzers/test_analyzer_annualreturn.py tests/functional/strategies/advanced/test_51_optimization.py tests/unit/core/test_parameter_performance.py -q` -- passed, 106 tests.
- `pip install -U .` -- passed.
- `pytest tests -n 4` -- passed, 3054 tests, 1 skipped.
- `rg -n "type\(\s*[\"']ParamsInstance|type\(\s*[\"']Params[\"']|class ParamClass|ParamsWrapper|_reconstruct_param_class" backtrader -g '*.py'` -- no matches.
