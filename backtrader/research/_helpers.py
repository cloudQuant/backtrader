"""Shared Indicator/Lines wiring for explicit native Alpha101 formulas."""

from typing import Any, Sequence, Tuple

from .operators import (
    CrossSectionalRank,
    CrossSectionalScale,
    Delay,
    Divide,
    Subtract,
    _LogicalOperatorView,
    _PairedPanelOperator,
)


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


def pair_panel(
    factor: Any,
    name: str,
    operator: Any,
    left: Sequence[Any],
    right: Sequence[Any],
    **kwargs: Any,
) -> Tuple[Any, ...]:
    """Build one physical pair panel and retain one logical view per target.

    This helper deliberately does not attach formula-membership lines. Pair
    operators consume the already computed per-target inputs exactly as their
    scalar equivalents do.
    """
    if not issubclass(operator, _PairedPanelOperator):
        raise TypeError("pair_panel requires a native paired panel operator")
    target_count = len(factor.datas)
    if len(left) != target_count or len(right) != target_count:
        raise RuntimeError("paired-panel inputs do not match the bound feeds")
    node = operator.bind(
        *factor.datas,
        values=tuple(left),
        right_values=tuple(right),
        **kwargs,
    )
    physical_nodes = getattr(factor, "_physical_nodes", None)
    if physical_nodes is None:
        physical_nodes = []
        factor._physical_nodes = physical_nodes
    if not isinstance(physical_nodes, list):
        raise RuntimeError("factor physical-node registry must be a list during construction")
    physical_nodes.append(node)

    views = []
    for index, target in enumerate(factor.datas):
        view = _LogicalOperatorView(
            node,
            index,
            target,
            (node._values[index], node._right_values[index]),
        )
        factor._nodes["%s_%d" % (name, index)] = view
        views.append(view)
    node._logical_views = tuple(views)
    return tuple(view.lines.value for view in views)


def simple_returns(factor: Any, name: str = "returns") -> Tuple[Any, ...]:
    """Build the simple return chain from the native close-field lines."""
    close = factor.field_lines("close")
    prior = per_asset(factor, name + "_prior", Delay, close, period=1)
    change = per_asset(factor, name + "_change", Subtract, close, prior)
    return per_asset(factor, name, Divide, change, prior)
