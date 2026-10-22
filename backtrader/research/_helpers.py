"""Shared Indicator/Lines wiring for explicit native Alpha101 formulas."""

from typing import Any, Sequence, Tuple

from .operators import CrossSectionalRank, CrossSectionalScale, Delay, Divide, Subtract


def per_asset(
    factor: Any, name: str, operator: Any, *series: Sequence[Any], **kwargs: Any
) -> Tuple[Any, ...]:
    """Build a scalar operator independently for every bound target feed."""
    if any(len(items) != len(factor.datas) for items in series):
        raise RuntimeError("per-asset operator inputs do not match the bound feeds")
    results = []
    for index, operands in enumerate(zip(*series)):
        node = operator(*operands, **kwargs)
        factor._nodes["%s_%d" % (name, index)] = node
        results.append(node.lines.value)
    return tuple(results)


def panel(
    factor: Any, name: str, operator: Any, values: Sequence[Any], **kwargs: Any
) -> Tuple[Any, ...]:
    """Build one native panel operator using ordinary feed-bar presence."""
    if len(values) != len(factor.datas):
        raise RuntimeError("cross-sectional operator inputs do not match the bound feeds")
    panel_kwargs = dict(kwargs)
    panel_kwargs.setdefault("members", factor.formula_members)
    if operator in (CrossSectionalRank, CrossSectionalScale):
        panel_kwargs.setdefault("groups", factor.research_groups)
    node = operator.bind(*factor.datas, values=tuple(values), **panel_kwargs)
    factor._nodes[name] = node
    return tuple(node.outputs[data].value for data in factor.datas)


def simple_returns(factor: Any, name: str = "returns") -> Tuple[Any, ...]:
    """Build the simple return chain from the native close-field lines."""
    close = factor.field_lines("close")
    prior = per_asset(factor, name + "_prior", Delay, close, period=1)
    change = per_asset(factor, name + "_change", Subtract, close, prior)
    return per_asset(factor, name, Divide, change, prior)
