"""Small expression adapter that builds ordinary research operator nodes.

Expressions are scoped to one bound :class:`FactorIndicator` instance.  They
retain the target feed associated with each real Backtrader line and only
construct the existing scalar and panel operators; calculation and scheduling
remain in Cerebro's normal indicator tree.
"""

from __future__ import annotations

import numbers
from typing import Any, Dict, Optional, Sequence, Tuple, Type

from . import operators


class _FactorExpression:
    """A target-associated set of real lines for one build context."""

    __slots__ = ("_context", "_context_token", "_targets", "_target_ids", "_lines", "_label")
    __hash__ = None

    def __init__(
        self,
        context: "_ExpressionContext",
        targets: Sequence[Any],
        lines: Sequence[Any],
        *,
        label: Optional[str] = None,
    ) -> None:
        target_tuple = tuple(targets)
        line_tuple = tuple(lines)
        if len(target_tuple) != len(context.targets) or len(line_tuple) != len(target_tuple):
            raise TypeError("expression must contain one line for every factor target")
        if any(actual is not expected for actual, expected in zip(target_tuple, context.targets)):
            raise TypeError("expression targets do not match the bound factor targets")
        if any(not hasattr(line, "array") for line in line_tuple):
            raise TypeError("expression values must be Backtrader lines")
        self._context = context
        self._context_token = context._token
        self._targets = target_tuple
        self._target_ids = tuple(id(target) for target in target_tuple)
        self._lines = line_tuple
        self._label = label

    def _line_for(self, target: Any) -> Any:
        index = self._context._target_index_by_id.get(id(target))
        if index is None or self._targets[index] is not target:
            raise TypeError("expression has no line for this factor target")
        return self._lines[index]

    def _binary(self, kind: Type[Any], other: Any, *, reverse: bool = False) -> "_FactorExpression":
        left, right = (other, self) if reverse else (self, other)
        return self._context.binary(kind, left, right)

    def __add__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.Add, other)

    def __radd__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.Add, other, reverse=True)

    def __sub__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.Subtract, other)

    def __rsub__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.Subtract, other, reverse=True)

    def __mul__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.Multiply, other)

    def __rmul__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.Multiply, other, reverse=True)

    def __truediv__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.Divide, other)

    def __rtruediv__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.Divide, other, reverse=True)

    def __pow__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.Power, other)

    def __rpow__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.Power, other, reverse=True)

    def __neg__(self) -> "_FactorExpression":
        return self._context.unary(operators.Negate, self)

    def __pos__(self) -> "_FactorExpression":
        return self

    def __lt__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.LessThan, other)

    def __le__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.LessEqual, other)

    def __gt__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.GreaterThan, other)

    def __ge__(self, other: Any) -> "_FactorExpression":
        return self._binary(operators.GreaterEqual, other)

    def __eq__(self, other: Any) -> "_FactorExpression":  # type: ignore[override]
        return self._binary(operators.EqualTo, other)

    def __ne__(self, other: Any) -> "_FactorExpression":  # type: ignore[override]
        return self._binary(operators.NotEqualTo, other)

    def __bool__(self) -> bool:
        raise TypeError("factor expressions cannot be converted to bool; use ctx.where()")

    def __repr__(self) -> str:
        return "<factor expression %s>" % (self._label or "operator")


class _ExpressionContext:
    """Build native operator nodes for one bound factor and target group."""

    def __init__(self, factor: Any) -> None:
        self._factor = factor
        self._token = object()
        self.targets = tuple(factor.target_datas)
        self._target_index_by_id = {id(data): index for index, data in enumerate(self.targets)}
        if not self.targets or len(self._target_index_by_id) != len(self.targets):
            raise TypeError("expression builds require unique factor targets")
        self.nodes: Dict[str, Any] = {}
        self._name_counts: Dict[str, int] = {}
        self._closed = False

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("factor build context is closed after build() returns")

    def _close(self) -> None:
        """Prevent expressions retained by user code from adding runtime nodes."""
        self._closed = True

    def __getattr__(self, name: str) -> _FactorExpression:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.field(name)

    def _unique_name(self, base: str) -> str:
        count = self._name_counts.get(base, 0)
        self._name_counts[base] = count + 1
        return base if count == 0 else "%s__%d" % (base, count)

    def _check_expression(self, value: Any, operation: str) -> _FactorExpression:
        self._assert_open()
        if not isinstance(value, _FactorExpression):
            raise TypeError("%s requires factor expression inputs" % operation)
        if (
            value._context is not self
            or value._context_token is not self._token
            or value._target_ids != tuple(id(x) for x in self.targets)
        ):
            raise TypeError("expression belongs to a different factor build context or targets")
        return value

    def _check_operand(self, value: Any, operation: str) -> Any:
        if isinstance(value, _FactorExpression):
            return self._check_expression(value, operation)
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            raise TypeError("%s operands must be expressions or real scalar numbers" % operation)
        return value

    def _line_operand(self, value: Any, target: Any) -> Any:
        return value._line_for(target) if isinstance(value, _FactorExpression) else value

    def _new_expression(
        self, lines: Sequence[Any], *, label: Optional[str] = None
    ) -> _FactorExpression:
        return _FactorExpression(self, self.targets, lines, label=label)

    def field(self, alias: str) -> _FactorExpression:
        """Return one declared, explicitly bound field per target feed."""
        self._assert_open()
        if not isinstance(alias, str) or not alias:
            raise TypeError("factor field name must be a non-empty string")
        declared = tuple(getattr(self._factor.__class__, "formula_fields", ()))
        if alias not in declared:
            from ..errors import ResearchConfigError

            raise ResearchConfigError("factor did not declare formula field %s" % alias)
        lines = tuple(self._factor.field_lines(alias))
        return self._new_expression(lines, label=alias)

    def _mark_target(self, line: Any, target: Any, operands: Sequence[Any]) -> Any:
        sources = tuple(
            operand._line_for(target)
            for operand in operands
            if isinstance(operand, _FactorExpression)
        )
        return self._factor._mark_target_local_line(line, target, sources)

    def _store_scalar_nodes(self, name: str, nodes: Sequence[Any]) -> None:
        unique_name = self._unique_name(name)
        for index, node in enumerate(nodes):
            # The trace validator reconstructs asset identity from this suffix.
            self.nodes["%s_%d" % (unique_name, index)] = node

    def binary(self, kind: Type[Any], left: Any, right: Any) -> _FactorExpression:
        self._assert_open()
        left = self._check_operand(left, "binary operator")
        right = self._check_operand(right, "binary operator")
        nodes = []
        lines = []
        for target in self.targets:
            left_operand = self._line_operand(left, target)
            right_operand = self._line_operand(right, target)
            node = kind(left_operand, right_operand)
            nodes.append(node)
            lines.append(self._mark_target(node.lines.value, target, (left, right)))

        if kind is operators.Multiply and (
            (isinstance(left, numbers.Real) and float(left) == -1.0)
            or (isinstance(right, numbers.Real) and float(right) == -1.0)
        ):
            name = "negate"
        else:
            name = {
                operators.Add: "add",
                operators.Subtract: "subtract",
                operators.Multiply: "multiply",
                operators.Divide: "divide",
                operators.Power: "power",
                operators.LessThan: "less_than",
                operators.LessEqual: "less_equal",
                operators.GreaterThan: "greater_than",
                operators.GreaterEqual: "greater_equal",
                operators.EqualTo: "equal_to",
                operators.NotEqualTo: "not_equal_to",
            }.get(kind, kind.__name__.lower())
        self._store_scalar_nodes(name, nodes)
        return self._new_expression(lines)

    def unary(self, kind: Type[Any], value: Any) -> _FactorExpression:
        self._assert_open()
        expression = self._check_expression(value, "unary operator")
        nodes = []
        lines = []
        for target in self.targets:
            node = kind(expression._line_for(target))
            nodes.append(node)
            lines.append(self._mark_target(node.lines.value, target, (expression,)))
        self._store_scalar_nodes(kind.__name__.lower(), nodes)
        return self._new_expression(lines)

    def rank(self, value: Any) -> _FactorExpression:
        self._assert_open()
        expression = self._check_expression(value, "rank")
        name = "rank_%s" % expression._label if expression._label else "rank"
        node = operators.CrossSectionalRank.bind(
            *self.targets,
            values=tuple(expression._line_for(target) for target in self.targets),
            members=self._factor.formula_members,
            groups=self._factor.research_groups,
        )
        self.nodes[self._unique_name(name)] = node
        lines = tuple(node.outputs[target].value for target in self.targets)
        return self._new_expression(lines, label="rank")

    def correlation(self, left: Any, right: Any, period: Any) -> _FactorExpression:
        self._assert_open()
        left = self._check_expression(left, "correlation")
        right = self._check_expression(right, "correlation")
        nodes = []
        lines = []
        for target in self.targets:
            left_line = left._line_for(target)
            right_line = right._line_for(target)
            node = operators.RollingCorrelation(left_line, right_line, period=period)
            nodes.append(node)
            lines.append(
                self._factor._mark_target_local_line(
                    node.lines.value, target, (left_line, right_line)
                )
            )
        try:
            period_name = str(int(float(period)))
        except (TypeError, ValueError, OverflowError):
            period_name = str(period)
        self._store_scalar_nodes("correlation%s" % period_name, nodes)
        return self._new_expression(lines, label="correlation")

    def where(self, condition: Any, when_true: Any, when_false: Any) -> _FactorExpression:
        self._assert_open()
        condition = self._check_expression(condition, "where condition")
        when_true = self._check_operand(when_true, "where")
        when_false = self._check_operand(when_false, "where")
        nodes = []
        lines = []
        for target in self.targets:
            operands = (condition, when_true, when_false)
            node = operators.Where(
                condition._line_for(target),
                self._line_operand(when_true, target),
                self._line_operand(when_false, target),
            )
            nodes.append(node)
            lines.append(self._mark_target(node.lines.value, target, operands))
        self._store_scalar_nodes("where", nodes)
        return self._new_expression(lines, label="where")

    def result_lines(self, value: Any) -> Tuple[Any, ...]:
        self._assert_open()
        expression = self._check_expression(value, "build result")
        return tuple(expression._line_for(target) for target in self.targets)


__all__ = ("_ExpressionContext",)
