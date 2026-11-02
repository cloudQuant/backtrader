"""Backtrader-owned factor execution coordination.

Provider query and execution remain SDK responsibilities. The package exposes
only Backtrader facts, local journal projection and coordinator contracts.
"""

from importlib import import_module as _import_module


_EXPORTS = {
    "ExecutionOrderSnapshot": "factor_execution",
    "ExecutionPositionSnapshot": "factor_execution",
    "FactorExecutionCoordinator": "factor_execution",
    "FactorExecutionDecisionScope": "factor_execution",
    "FactorExecutionError": "factor_execution",
    "execution_order_snapshot": "factor_execution",
    "execution_position_snapshot": "factor_execution",
    "FactorExecutionFacts": "factor_execution_facts",
    "FactorExecutionFactsError": "factor_execution_facts",
    "FactorExecutionTarget": "factor_execution_facts",
    "FactorLocalOrder": "factor_execution_facts",
    "FactorLocalPosition": "factor_execution_facts",
    "FactorOrderCorrelation": "factor_execution_facts",
    "collect_local_bt_facts": "factor_execution_facts",
}

__all__ = tuple(_EXPORTS)


def __getattr__(name):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    module = _import_module("." + module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
