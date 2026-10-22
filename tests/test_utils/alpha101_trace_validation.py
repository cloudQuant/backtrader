"""Causal, AST-backed validation for the native Alpha101 operator graph.

The paper catalog is parsed independently from production. Native node inputs
are reconstructed from the explicit operator graph, then the reference walks
the source AST in postorder. A production node replaces the reference value
for downstream calculations only after its own output passes its local check.
This makes discrete rank and branch checks exact on validated production
float64 inputs while preserving an independent source of expected values.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from backtrader.research import operators
from tests.test_utils.alpha101_full_reference import (
    _Context,
    _parse,
    formula_metadata,
    formula_source,
    history_h,
)
from tests.test_utils.alpha101_native_harness import oracle_frames, presence_matrix

_BINARY_OPERATORS = {
    operators.Add: "+",
    operators.Subtract: "-",
    operators.Multiply: "*",
    operators.Divide: "/",
    operators.Power: "^",
    operators.LessThan: "<",
    operators.LessEqual: "<=",
    operators.GreaterThan: ">",
    operators.GreaterEqual: ">=",
    operators.EqualTo: "==",
    operators.LogicalOr: "||",
}
_CALL_OPERATORS = {
    operators.Abs: "abs",
    operators.Log: "log",
    operators.Sign: "sign",
    operators.SignedPower: "signedpower",
    operators.RollingSum: "sum",
    operators.RollingProduct: "product",
    operators.RollingStd: "stddev",
    operators.TsMin: "ts_min",
    operators.TsMax: "ts_max",
    operators.TsArgMin: "ts_argmin",
    operators.TsArgMax: "ts_argmax",
    operators.TsRank: "ts_rank",
    operators.DecayLinear: "decay_linear",
    operators.RollingCorrelation: "correlation",
    operators.RollingCovariance: "covariance",
}
_FIELD_NAME = re.compile(r"^(?P<name>.+)_(?P<index>\d+)$")
_RETURNS_NODE = re.compile(r"^(?:close_)?returns_(?P<index>\d+)$")


def _literal(value: Any) -> Tuple[Any, ...]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AssertionError("native graph contains a non-numeric scalar operand")
    return ("number", float(value))


def _fold_constants(node: Tuple[Any, ...]) -> Tuple[Any, ...]:
    """Fold only literal arithmetic, as native declarations do at import time."""
    kind = node[0]
    if kind == "number" or kind == "name":
        return node
    if kind == "unary":
        child = _fold_constants(node[2])
        if child[0] == "number":
            value = float(child[1])
            return _literal(value if node[1] == "+" else -value)
        return ("unary", node[1], child)
    if kind == "binary":
        left, right = _fold_constants(node[2]), _fold_constants(node[3])
        if left[0] == right[0] == "number" and node[1] in ("+", "-", "*", "/", "^"):
            try:
                value = {
                    "+": lambda: float(left[1]) + float(right[1]),
                    "-": lambda: float(left[1]) - float(right[1]),
                    "*": lambda: float(left[1]) * float(right[1]),
                    "/": lambda: float(left[1]) / float(right[1]),
                    "^": lambda: math.pow(float(left[1]), float(right[1])),
                }[node[1]]()
            except (ArithmeticError, ValueError):
                pass
            else:
                return _literal(value)
        if left[0] == "number" and right[0] != "number" and node[1] in ("<", "<=", ">", ">="):
            left, right = right, left
            operator = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}[node[1]]
            return ("binary", operator, left, right)
        if node[1] in ("+", "*", "==", "||") and repr(left) > repr(right):
            left, right = right, left
        return ("binary", node[1], left, right)
    if kind == "ternary":
        return ("ternary",) + tuple(_fold_constants(child) for child in node[1:])
    if kind == "call":
        name = node[1]
        arguments = tuple(_fold_constants(child) for child in node[2])
        # The paper catalog permits min/max(value, window) as aliases for
        # rolling extrema; native graphs name those operators TsMin/TsMax.
        if name == "min" and len(arguments) == 2 and arguments[1][0] == "number":
            name = "ts_min"
        elif name == "max" and len(arguments) == 2 and arguments[1][0] == "number":
            name = "ts_max"
        return ("call", name, arguments)
    raise AssertionError("unknown catalog AST node %r" % (node,))


def _postorder(tree: Tuple[Any, ...]) -> Iterable[Tuple[Any, ...]]:
    seen = set()

    def visit(node: Tuple[Any, ...]):
        if node in seen:
            return
        kind = node[0]
        if kind == "unary":
            children = (node[2],)
        elif kind == "binary":
            children = (node[2], node[3])
        elif kind == "ternary":
            children = node[1:]
        elif kind == "call":
            children = node[2]
        else:
            children = ()
        for child in children:
            yield from visit(child)
        seen.add(node)
        yield node

    yield from visit(tree)


def _operator_period(node: Any) -> float:
    params = getattr(node, "p", None)
    value = getattr(params, "period", getattr(node, "_period", None))
    if value is None:
        raise AssertionError("rolling node %s has no period" % type(node).__name__)
    return float(value)


def _operator_expression(node: Any, asset_index: int, line_expression: Any) -> Tuple[Any, ...]:
    if isinstance(node, operators._PanelOperator):
        inputs = tuple(line_expression(line, index) for index, line in enumerate(node._values))
        if not inputs or any(value != inputs[0] for value in inputs[1:]):
            raise AssertionError("panel operator receives structurally different asset inputs")
        source = inputs[0]
        if isinstance(node, operators.CrossSectionalRank):
            return ("call", "rank", (source,))
        if isinstance(node, operators.CrossSectionalScale):
            return ("call", "scale", (source,))
        if isinstance(node, operators.IndNeutralize):
            level = str(node.p.level).lower()
            return (
                "call",
                "indneutralize",
                (source, ("name", "indclass." + level)),
            )
        raise AssertionError("unmapped panel operator %s" % type(node).__name__)

    operands = tuple(
        (
            line_expression(value, asset_index)
            if not isinstance(value, (int, float)) or isinstance(value, bool)
            else _literal(value)
        )
        for value in node._operand_args
    )
    for operator_type, symbol in _BINARY_OPERATORS.items():
        if isinstance(node, operator_type):
            return ("binary", symbol, operands[0], operands[1])
    if isinstance(node, operators.Where):
        return ("ternary", operands[0], operands[1], operands[2])
    if isinstance(node, operators.Delay):
        name = "delta" if isinstance(node, operators.Delta) else "delay"
        return ("call", name, (operands[0], _literal(_operator_period(node))))
    if isinstance(node, operators.Minimum):
        return ("call", "min", operands)
    if isinstance(node, operators.Maximum):
        return ("call", "max", operands)
    if isinstance(node, operators.Negate):
        return ("unary", "-", operands[0])
    for operator_type, name in _CALL_OPERATORS.items():
        if isinstance(node, operator_type):
            if name in (
                "sum",
                "product",
                "stddev",
                "ts_min",
                "ts_max",
                "ts_argmin",
                "ts_argmax",
                "ts_rank",
                "decay_linear",
            ):
                operands = (operands[0], _literal(_operator_period(node)))
            elif name in ("correlation", "covariance"):
                operands = (operands[0], operands[1], _literal(_operator_period(node)))
            return ("call", name, operands)
    raise AssertionError("unmapped scalar operator %s" % type(node).__name__)


def _exact_discrete_ast(node: Tuple[Any, ...]) -> bool:
    kind = node[0]
    if kind == "ternary":
        return True
    if kind == "binary":
        return node[1] in ("<", ">", "<=", ">=", "==", "||")
    if kind == "call":
        return node[1] in (
            "rank",
            "ts_rank",
            "ts_argmax",
            "ts_argmin",
            "ts_min",
            "ts_max",
            "delay",
            "min",
            "max",
        )
    return False


def _compare_matrices(
    actual: Sequence[Sequence[float]],
    expected: Any,
    *,
    exact: bool,
    label: str,
) -> Tuple[bool, str]:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        expected = [[float(expected)] * len(row) for row in actual]
    if len(actual) != len(expected):
        return False, "%s row count %d != %d" % (label, len(actual), len(expected))
    for row_index, (actual_row, expected_row) in enumerate(zip(actual, expected)):
        if len(actual_row) != len(expected_row):
            return False, "%s asset count differs at row %d" % (label, row_index)
        for asset_index, (got, wanted) in enumerate(zip(actual_row, expected_row)):
            got, wanted = float(got), float(wanted)
            location = "row %d asset %d" % (row_index, asset_index)
            if math.isnan(wanted):
                if not math.isnan(got):
                    return False, "%s %s: expected NaN, got %.17g" % (label, location, got)
                continue
            if not math.isfinite(wanted):
                return False, "%s %s: reference is non-finite %.17g" % (label, location, wanted)
            if not math.isfinite(got):
                return False, "%s %s: expected %.17g, got %r" % (label, location, wanted, got)
            if exact:
                if got != wanted:
                    return False, "%s %s: exact %.17g != %.17g" % (label, location, got, wanted)
            else:
                tolerance = 1e-12 + 1e-10 * abs(wanted)
                if abs(got - wanted) > tolerance:
                    return (
                        False,
                        "%s %s: %.17g != %.17g (tolerance %.3g)"
                        % (
                            label,
                            location,
                            got,
                            wanted,
                            tolerance,
                        ),
                    )
    return True, ""


def _array(line: Any, rows: int) -> List[float]:
    values = [float(value) for value in line.array]
    if len(values) != rows:
        raise AssertionError("line has %d slots; expected %d grid rows" % (len(values), rows))
    return values


def _matrix_from_lines(lines: Sequence[Any], rows: int) -> List[List[float]]:
    columns = [_array(line, rows) for line in lines]
    return [[columns[column][row] for column in range(len(columns))] for row in range(rows)]


def _factor_asset_names(factor: Any) -> Tuple[str, ...]:
    targets = tuple(getattr(factor, "target_datas", ()))
    if not targets:
        targets = tuple(getattr(factor, "_factor_target_datas", ()))
    runtime = getattr(factor, "_factor_runtime", {})
    by_id = runtime.get("asset_by_data_id", {}) if isinstance(runtime, Mapping) else {}
    names = tuple(str(by_id.get(id(target), getattr(target, "_name", ""))) for target in targets)
    if not names or any(not name for name in names) or len(names) != len(set(names)):
        raise AssertionError("factor graph does not have unique real target asset identities")
    return names


def _pair_field_aliases(
    factor: Any, asset_names: Sequence[str]
) -> Dict[int, Tuple[str, frozenset]]:
    aliases: Dict[int, Tuple[str, set]] = {}
    for name, lines in factor._field_line_cache.items():
        if len(lines) != len(asset_names):
            raise AssertionError("field %s has an inconsistent target count" % name)
        for asset_index, line in enumerate(lines):
            entry = aliases.setdefault(id(line), (str(name).lower(), set()))
            if entry[0] != str(name).lower():
                raise AssertionError("one input line is bound to multiple formula fields")
            entry[1].add(asset_index)
    return {line_id: (name, frozenset(indices)) for line_id, (name, indices) in aliases.items()}


def _pair_line_operands(node: Any) -> Tuple[Any, ...]:
    operands = getattr(node, "_operand_args", None)
    if operands is None:
        operands = tuple(getattr(node, "datas", ()))
    return tuple(operand for operand in operands if operators._is_line_operand(operand))


def _pair_scalar_target_index(node: Any, factor: Any, asset_names: Sequence[str]) -> int:
    targets = tuple(getattr(factor, "target_datas", ())) or tuple(factor._factor_target_datas)
    value_line = getattr(getattr(node, "lines", None), "value", None)
    marker = getattr(value_line, "_factor_research_target", None)
    if marker is not None:
        for index, target in enumerate(targets):
            if marker is target:
                return index
        raise AssertionError("scalar graph output targets an undeclared feed")

    line_operands = _pair_line_operands(node)
    if not line_operands:
        raise AssertionError(
            "cannot infer constant-only scalar operator target without consumer traversal"
        )
    candidates = []
    for index, target in enumerate(targets):
        relations = [operators._line_target_relation(line, target) for line in line_operands]
        if relations and all(relation is True for relation in relations):
            candidates.append(index)
    if len(candidates) != 1:
        raise AssertionError(
            "scalar graph node %s has ambiguous target identity across %r"
            % (type(node).__name__, tuple(asset_names[index] for index in candidates))
        )
    return candidates[0]


def _line_reason(line: Any, node: Any = None) -> Any:
    reason = getattr(line, "_factor_research_reason_line", None)
    if reason is not None:
        return reason
    reason = getattr(getattr(node, "lines", None), "reason", None)
    if reason is not None:
        return reason
    return None


def _operator_type_name(node: Any) -> str:
    node_type = type(node)
    return "%s.%s" % (node_type.__module__, node_type.__qualname__)


def _pair_float_token(value: float) -> bytes:
    value = float(value)
    if math.isnan(value):
        return b"N;"
    if math.isinf(value):
        raise AssertionError("factor graph contains infinity")
    # Numeric exactness treats the two IEEE zero signs as equal, matching the
    # matrix comparator used by the independent trace validator.
    return ("0;" if value == 0.0 else value.hex() + ";").encode("ascii")


def _matrix_sha256(matrix: Sequence[Sequence[float]]) -> str:
    digest = hashlib.sha256()
    digest.update(("%d,%d;" % (len(matrix), len(matrix[0]) if matrix else 0)).encode("ascii"))
    for row in matrix:
        for value in row:
            digest.update(_pair_float_token(value))
    return digest.hexdigest()


def _matrix_cell_counts(matrix: Sequence[Sequence[float]]) -> Dict[str, int]:
    values = [float(value) for row in matrix for value in row]
    if any(math.isinf(value) for value in values):
        raise AssertionError("factor graph contains infinity")
    return {
        "cells": len(values),
        "finite_cells": sum(math.isfinite(value) for value in values),
        "nan_cells": sum(math.isnan(value) for value in values),
    }


def _factor_graph_pair_records(factor: Any, alpha_id: int) -> Dict[str, Any]:
    if getattr(factor, "alpha_id", None) != alpha_id:
        raise AssertionError("factor graph identity does not match Alpha%d" % alpha_id)
    targets = tuple(getattr(factor, "target_datas", ())) or tuple(factor._factor_target_datas)
    asset_names = _factor_asset_names(factor)
    target_order = tuple(_factor_asset_names_for_output(factor, target) for target in targets)
    grid = tuple(getattr(factor, "_factor_grid", None) or factor._factor_call_times)
    call_times = tuple(factor._factor_call_times)
    if not grid or call_times != grid:
        raise AssertionError("factor graph grid and actual call-time identities differ")
    rows = len(grid)
    aliases = _pair_field_aliases(factor, asset_names)
    node_items = tuple(getattr(factor, "_nodes", {}).values())
    if not node_items:
        raise AssertionError("factor graph has no registered operator nodes")
    registered_nodes = {id(node): node for node in node_items}
    traversed_nodes: Dict[int, Any] = {}
    node_target_indices: Dict[int, set] = defaultdict(set)
    active = set()
    cache: Dict[Tuple[int, int], Tuple[Any, ...]] = {}

    def line_expression(line: Any, asset_index: int) -> Tuple[Any, ...]:
        cache_key = (id(line), asset_index)
        if cache_key in cache:
            return cache[cache_key]
        alias = aliases.get(id(line))
        if alias is not None:
            name, bound_indices = alias
            if asset_index not in bound_indices and len(bound_indices) != len(asset_names):
                raise AssertionError(
                    "Alpha%d asset %s consumes %s bound to another target"
                    % (alpha_id, asset_names[asset_index], name)
                )
            expression = ("name", name)
            cache[cache_key] = expression
            return expression

        owner = getattr(getattr(line, "_owner", None), "_owner_ref", None)
        if owner is None:
            raise AssertionError(
                "Alpha%d graph input at asset %s is not a declared field or operator output"
                % (alpha_id, asset_names[asset_index])
            )
        traversed_nodes[id(owner)] = owner
        node_target_indices[id(owner)].add(asset_index)
        marker = getattr(line, "_factor_research_target", None)
        if marker is not None:
            target_indices = {id(target): index for index, target in enumerate(targets)}
            marked_index = target_indices.get(id(marker))
            if marked_index is None:
                raise AssertionError(
                    "Alpha%d graph line marker targets an undeclared feed" % alpha_id
                )
            if marked_index != asset_index:
                raise AssertionError(
                    "Alpha%d operator output for asset %s is wired into asset %s"
                    % (alpha_id, asset_names[marked_index], asset_names[asset_index])
                )
        owner_key = (id(owner), asset_index)
        if owner_key in active:
            raise AssertionError("Alpha%d graph has a cycle" % alpha_id)
        active.add(owner_key)
        expression = _operator_expression(owner, asset_index, line_expression)
        active.remove(owner_key)
        expression = _fold_constants(expression)
        cache[cache_key] = expression
        return expression

    def static_input(value: Any, asset_index: int) -> Tuple[Any, ...]:
        if operators._is_line_operand(value):
            owner = getattr(getattr(value, "_owner", None), "_owner_ref", None)
            present = getattr(owner, "_present", None)
            if present is not None:
                if operators._line_target_relation(value, targets[asset_index]) is not True:
                    raise AssertionError("panel membership input is bound to another target asset")
                return ("real_bar_presence", tuple(bool(item) for item in present))
            return line_expression(value, asset_index)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _literal(value)
        return ("static", type(value).__module__, type(value).__qualname__, repr(value))

    def panel_expression(node: Any) -> Tuple[Tuple[Any, ...], Tuple[Any, ...]]:
        inputs = tuple(line_expression(line, index) for index, line in enumerate(node._values))
        if not inputs or any(value != inputs[0] for value in inputs[1:]):
            raise AssertionError("panel operator receives structurally different asset inputs")
        if isinstance(node, operators.CrossSectionalRank):
            expression = ("call", "rank", (inputs[0],))
        elif isinstance(node, operators.CrossSectionalScale):
            expression = ("call", "scale", (inputs[0],))
        elif isinstance(node, operators.IndNeutralize):
            expression = ("call", "indneutralize", (inputs[0],))
        else:
            raise AssertionError("unmapped panel operator %s" % type(node).__name__)

        members = getattr(node, "_members", (None,) * len(asset_names))
        groups = getattr(node, "_groups", None) or (None,) * len(asset_names)
        if len(members) != len(asset_names) or len(groups) != len(asset_names):
            raise AssertionError(
                "panel node membership/group inputs have inconsistent target counts"
            )
        target_specs = []
        for index, asset_name in enumerate(asset_names):
            member_ast = (
                static_input(members[index], index) if members[index] is not None else ("none",)
            )
            group_ast = (
                static_input(groups[index], index) if groups[index] is not None else ("none",)
            )
            target_specs.append((asset_name, member_ast, group_ast))
        parameters = []
        if isinstance(node, operators.CrossSectionalScale):
            parameters.append(("a", float(node.p.a)))
        if isinstance(node, operators.IndNeutralize):
            parameters.append(("level", str(node.p.level).lower()))
            parameters.append(
                (
                    "classification_inputs",
                    tuple(sorted((name, group) for name, _, group in target_specs)),
                )
            )
        if isinstance(node, operators.CrossSectionalRank):
            parameters.append(
                ("groups", tuple(sorted((name, group) for name, _, group in target_specs)))
            )
        parameters.append(
            ("members", tuple(sorted((name, member) for name, member, _ in target_specs)))
        )
        return _fold_constants(expression), tuple(parameters)

    root = tuple(
        _fold_constants(line_expression(line, index))
        for index, line in enumerate(factor._result_lines)
    )

    def node_record(
        node: Any,
    ) -> Tuple[Tuple[Any, ...], str, Tuple[str, ...], Tuple[Any, ...], list, Any]:
        operator_type = _operator_type_name(node)
        if isinstance(node, operators._PanelOperator):
            expression, parameters = panel_expression(node)
            output_names = tuple(
                _factor_asset_names_for_output(factor, data)
                for data in getattr(node, "_factor_target_datas", ())
            )
            if set(output_names) != set(asset_names) or len(output_names) != len(asset_names):
                raise AssertionError("panel node target assets differ from the bound factor")
            if output_names != target_order:
                raise AssertionError(
                    "panel node target output order differs from factor target order"
                )
            target_by_name = dict(zip(output_names, node._factor_target_datas))
            target = tuple(sorted(asset_names))
            values = _matrix_from_lines(
                [node.outputs[target_by_name[name]].value for name in target], rows
            )
            reasons = _matrix_from_lines(
                [node.outputs[target_by_name[name]].reason for name in target], rows
            )
            return expression, operator_type, target, parameters, values, reasons

        line_operands = _pair_line_operands(node)
        target_indices = node_target_indices.get(id(node), set())
        if line_operands:
            asset_index = _pair_scalar_target_index(node, factor, asset_names)
            if target_indices and target_indices != {asset_index}:
                raise AssertionError(
                    "scalar operator node %s is consumed by assets inconsistent with its inputs: %r"
                    % (
                        type(node).__name__,
                        tuple(asset_names[index] for index in sorted(target_indices)),
                    )
                )
        else:
            if len(target_indices) != 1:
                raise AssertionError(
                    "constant-only scalar operator node %s has ambiguous or missing consumer asset identity: %r"
                    % (
                        type(node).__name__,
                        tuple(asset_names[index] for index in sorted(target_indices)),
                    )
                )
            asset_index = next(iter(target_indices))
        expression = _fold_constants(_operator_expression(node, asset_index, line_expression))
        value_line = getattr(getattr(node, "lines", None), "value", None)
        if value_line is None:
            raise AssertionError("scalar graph node %s has no value output line" % operator_type)
        values = [[value] for value in _array(value_line, rows)]
        reason_line = _line_reason(value_line, node)
        if reason_line is None:
            raise AssertionError("scalar graph node %s has no reason output line" % operator_type)
        reasons = [[value] for value in _array(reason_line, rows)]
        return expression, operator_type, (asset_names[asset_index],), (), values, reasons

    for owner_id, owner in traversed_nodes.items():
        if owner_id not in registered_nodes and not _pair_line_operands(owner):
            raise AssertionError(
                "reachable constant-only operator node %s is absent from factor._nodes"
                % type(owner).__name__
            )
    grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = defaultdict(list)
    for node in node_items:
        expression, operator_type, target, parameters, values, reasons = node_record(node)
        signature = (expression, operator_type, target, parameters)
        value_counts = _matrix_cell_counts(values)
        reason_counts = None if reasons is None else _matrix_cell_counts(reasons)
        value_digest = _matrix_sha256(values)
        reason_digest = None if reasons is None else _matrix_sha256(reasons)
        grouped[signature].append(
            {
                "values": values,
                "reasons": reasons,
                "value_digest": value_digest,
                "reason_digest": reason_digest,
                "value_counts": value_counts,
                "reason_counts": reason_counts,
            }
        )

    results = {}
    if len(factor._result_lines) != len(asset_names):
        raise AssertionError("factor result line count differs from target asset count")
    result_by_asset = dict(zip(asset_names, factor._result_lines))
    for asset in sorted(asset_names):
        values = [[value] for value in _array(result_by_asset[asset], rows)]
        results[asset] = values
    return {
        "assets": tuple(sorted(asset_names)),
        "target_order": target_order,
        "grid": grid,
        "root": root,
        "nodes": grouped,
        "node_count": len(node_items),
        "results": results,
    }


def _factor_asset_names_for_output(factor: Any, data: Any) -> str:
    runtime = getattr(factor, "_factor_runtime", {})
    by_id = runtime.get("asset_by_data_id", {}) if isinstance(runtime, Mapping) else {}
    name = str(by_id.get(id(data), getattr(data, "_name", "")))
    if not name:
        raise AssertionError("panel node output has no real target asset identity")
    return name


def compare_factor_graphs(left_factor: Any, right_factor: Any, alpha_id: int) -> Dict[str, Any]:
    """Compare complete native/build operator graphs by semantic node identity.

    The factors must be fully executed instances of the same Alpha101 formula.
    Nodes are matched as a multiset keyed by canonical input AST, concrete
    operator type, and actual target asset identity. Diagnostic dictionary
    keys and insertion order are deliberately ignored. Every node value and
    reason array, plus the final per-asset result lines, is compared exactly
    with matching NaN masks; missing reasons and infinities are rejected.
    """
    failures: List[str] = []
    try:
        left = _factor_graph_pair_records(left_factor, alpha_id)
    except Exception as exc:
        left = None
        failures.append("left graph invalid: %s" % exc)
    try:
        right = _factor_graph_pair_records(right_factor, alpha_id)
    except Exception as exc:
        right = None
        failures.append("right graph invalid: %s" % exc)
    report: Dict[str, Any] = {
        "alpha_id": alpha_id,
        "equal": False,
        "failures": failures,
        "node_count_left": 0 if left is None else left["node_count"],
        "node_count_right": 0 if right is None else right["node_count"],
        "matched_node_count": 0,
        "matched_nodes": [],
        "node_value_cells": 0,
        "node_reason_cells": 0,
        "node_value_sha256": None,
        "node_reason_sha256": None,
        "result_output_cells": 0,
        "result_output_sha256": None,
        "grid_rows": 0,
        "assets": [],
        "target_order_left": [],
        "target_order_right": [],
    }
    if left is None or right is None:
        return report
    if left["assets"] != right["assets"]:
        failures.append(
            "target asset identities differ: %r != %r" % (left["assets"], right["assets"])
        )
    else:
        report["assets"] = list(left["assets"])
    report["target_order_left"] = list(left["target_order"])
    report["target_order_right"] = list(right["target_order"])
    if left["target_order"] != right["target_order"]:
        failures.append("declared target asset output order differs")
    if left["grid"] != right["grid"]:
        failures.append("factor grid identities differ")
    else:
        report["grid_rows"] = len(left["grid"])
    if left["root"] != right["root"]:
        failures.append("canonical factor result AST differs")

    left_nodes, right_nodes = left["nodes"], right["nodes"]
    signatures = sorted(set(left_nodes) | set(right_nodes), key=repr)
    value_digest = hashlib.sha256()
    reason_digest = hashlib.sha256()
    for signature in signatures:
        record_key = lambda record: (record["value_digest"], record["reason_digest"] or "")
        left_records = sorted(left_nodes.get(signature, ()), key=record_key)
        right_records = sorted(right_nodes.get(signature, ()), key=record_key)
        signature_label = json.dumps(signature, default=repr, separators=(",", ":"))
        if len(left_records) != len(right_records):
            failures.append(
                "node multiplicity differs for %s: %d != %d"
                % (signature_label, len(left_records), len(right_records))
            )
        for duplicate_index, (left_record, right_record) in enumerate(
            zip(left_records, right_records)
        ):
            label = "%s duplicate %d" % (signature_label, duplicate_index)
            values_equal, value_error = _compare_matrices(
                left_record["values"], right_record["values"], exact=True, label=label + " values"
            )
            if not values_equal:
                failures.append(value_error)
            left_reasons, right_reasons = left_record["reasons"], right_record["reasons"]
            if left_reasons is None or right_reasons is None:
                failures.append(label + " reason-line availability differs or is missing")
            else:
                reasons_equal, reason_error = _compare_matrices(
                    left_reasons, right_reasons, exact=True, label=label + " reasons"
                )
                if not reasons_equal:
                    failures.append(reason_error)
                report["node_reason_cells"] += left_record["reason_counts"]["cells"]
                reason_digest.update(left_record["reason_digest"].encode("ascii"))
            report["matched_node_count"] += 1
            report["node_value_cells"] += left_record["value_counts"]["cells"]
            value_digest.update(left_record["value_digest"].encode("ascii"))
            report["matched_nodes"].append(
                {
                    "ast": signature[0],
                    "operator_type": signature[1],
                    "target_assets": list(signature[2]),
                    "semantic_parameters": signature[3],
                    "duplicate_index": duplicate_index,
                    "value_cells": left_record["value_counts"]["cells"],
                    "reason_cells": (
                        0
                        if left_record["reason_counts"] is None
                        else left_record["reason_counts"]["cells"]
                    ),
                    "value_sha256": left_record["value_digest"],
                    "reason_sha256": left_record["reason_digest"],
                }
            )
    report["node_value_sha256"] = value_digest.hexdigest()
    report["node_reason_sha256"] = reason_digest.hexdigest()

    output_digest = hashlib.sha256()
    if set(left["results"]) != set(right["results"]):
        failures.append("final result target asset identities differ")
    else:
        for asset in sorted(left["results"]):
            matrix_left, matrix_right = left["results"][asset], right["results"][asset]
            equal, error = _compare_matrices(
                matrix_left, matrix_right, exact=True, label="result[%s]" % asset
            )
            if not equal:
                failures.append(error)
            counts = _matrix_cell_counts(matrix_left)
            report["result_output_cells"] += counts["cells"]
            output_digest.update(_matrix_sha256(matrix_left).encode("ascii"))
    report["result_output_sha256"] = output_digest.hexdigest()
    report["equal"] = not failures
    return report


def _field_lines(factor: Any) -> Dict[int, Tuple[str, int]]:
    result: Dict[int, Tuple[str, int]] = {}
    for name, lines in factor._field_line_cache.items():
        for index, line in enumerate(lines):
            result[id(line)] = (str(name).lower(), index)
    for key, node in factor._nodes.items():
        match = _RETURNS_NODE.match(str(key))
        if match:
            result[id(node.lines.value)] = ("returns", int(match.group("index")))
    return result


def _production_graph(
    factor: Any, alpha_id: int
) -> Tuple[Tuple[Any, ...], Dict[Tuple[Any, ...], List[List[List[float]]]]]:
    rows = len(factor._factor_call_times)
    aliases = _field_lines(factor)
    active = set()
    canonical_cache: Dict[Tuple[int, int], Tuple[Any, ...]] = {}

    def line_expression(line: Any, asset_index: int) -> Tuple[Any, ...]:
        cache_key = (id(line), asset_index)
        if cache_key in canonical_cache:
            return canonical_cache[cache_key]
        alias = aliases.get(id(line))
        if alias is not None:
            name, bound_index = alias
            if bound_index != asset_index:
                raise AssertionError(
                    "Alpha%d asset %d consumes %s from asset %d"
                    % (alpha_id, asset_index, name, bound_index)
                )
            expression = ("name", name)
            canonical_cache[cache_key] = expression
            return expression

        owner = getattr(getattr(line, "_owner", None), "_owner_ref", None)
        if owner is None:
            raise AssertionError(
                "Alpha%d graph input at asset %d is not a declared field or operator output"
                % (alpha_id, asset_index)
            )
        marker = getattr(line, "_factor_research_target", None)
        if marker is not None:
            target_indices = {
                id(target): index
                for index, target in enumerate(getattr(owner, "_factor_target_datas", ()))
            }
            marked_index = target_indices.get(id(marker))
            if marked_index is not None and marked_index != asset_index:
                raise AssertionError(
                    "Alpha%d panel output for asset %d is wired into asset %d"
                    % (alpha_id, marked_index, asset_index)
                )
        owner_key = (id(owner), asset_index)
        if owner_key in active:
            raise AssertionError("Alpha%d graph has a cycle" % alpha_id)
        active.add(owner_key)
        expression = _operator_expression(owner, asset_index, line_expression)
        active.remove(owner_key)
        expression = _fold_constants(expression)
        canonical_cache[cache_key] = expression
        return expression

    def expression_for_node(key: str, node: Any) -> Tuple[Any, ...]:
        if _RETURNS_NODE.match(key):
            return ("name", "returns")
        if isinstance(node, operators._PanelOperator):
            return _fold_constants(_operator_expression(node, 0, line_expression))
        match = _FIELD_NAME.match(key)
        if match is None:
            raise AssertionError("scalar node key %r lacks a target index" % key)
        return _fold_constants(
            _operator_expression(node, int(match.group("index")), line_expression)
        )

    root = tuple(
        _fold_constants(line_expression(line, index))
        for index, line in enumerate(factor._result_lines)
    )
    production: Dict[Tuple[Any, ...], List[List[List[float]]]] = defaultdict(list)
    scalar_groups: Dict[Tuple[Any, ...], List[Dict[int, List[float]]]] = defaultdict(list)
    for key, node in factor._nodes.items():
        expression = expression_for_node(str(key), node)
        if isinstance(node, operators._PanelOperator):
            outputs = [node.outputs[data].value for data in factor.datas]
            matrix = _matrix_from_lines(outputs, rows)
            production[expression].append(matrix)
        else:
            match = _FIELD_NAME.match(str(key))
            if match is None:
                raise AssertionError("scalar node key %r lacks a target index" % key)
            asset_index = int(match.group("index"))
            values = _array(node.lines.value, rows)
            groups = scalar_groups[expression]
            for group in groups:
                if asset_index not in group:
                    group[asset_index] = values
                    break
                if all(
                    (math.isnan(left) and math.isnan(right)) or left == right
                    for left, right in zip(group[asset_index], values)
                ):
                    break
            else:
                groups.append({asset_index: values})
    for expression, groups in scalar_groups.items():
        for group in groups:
            matrix = [[math.nan] * len(factor.datas) for _ in range(rows)]
            for asset_index, values in group.items():
                for row, value in enumerate(values):
                    matrix[row][asset_index] = value
            production[expression].append(matrix)
    expected_root = _fold_constants(_parse(alpha_id))
    if any(expression != expected_root for expression in root):
        raise AssertionError(
            "Alpha%d production graph does not match catalog AST: %r != %r"
            % (alpha_id, root, expected_root)
        )
    return expected_root, production


def _actual_field_matrix(factor: Any, alias: str, rows: int, columns: int) -> List[List[float]]:
    lines = factor._field_line_cache[alias]
    if len(lines) != columns:
        raise AssertionError("field %s has the wrong target count" % alias)
    return _matrix_from_lines(lines, rows)


def _physical_input_fields(factor: Any, alpha_id: int) -> Tuple[str, ...]:
    """Resolve declared formula inputs to their physical feed columns.

    This reads the frozen catalog and the factor's declared feed bindings. It
    does not call FactorStrategy's collector-window implementation.
    """
    fields = {
        "close" if str(alias).lower() == "returns" else str(alias).lower()
        for alias in formula_metadata(alpha_id).get("direct_market_fields", ())
    }
    bindings = factor._factor_runtime.get("field_bindings", {})
    for raw_alias in getattr(factor.__class__, "formula_fields", ()):
        alias = str(raw_alias).lower()
        if alias == "returns":
            fields.add("close")
            continue
        binding = bindings.get(alias)
        if isinstance(binding, Mapping):
            derivation = binding.get("derive")
            if derivation == "adv":
                sources = (binding.get("source"),)
            elif derivation == "vwap_volume":
                sources = (binding.get("vwap"), binding.get("volume"))
            else:
                sources = (binding.get("source"),)
        elif isinstance(binding, str):
            sources = (binding,)
        else:
            sources = (alias,)
        for source in sources:
            if not isinstance(source, str) or not source:
                continue
            if source.startswith("feed:"):
                parts = source.split(":")
                if len(parts) == 3:
                    fields.add(parts[2].lower())
            else:
                fields.add(source.lower())
    return tuple(sorted(fields))


def _physical_value_is_usable(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    try:
        if bool(value != value):
            return False
    except (TypeError, ValueError):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _collector_expected_matrix(
    factor: Any,
    alpha_id: int,
    frames: Mapping[str, Any],
    assets: Sequence[str],
    grid: Sequence[Any],
    expected: Sequence[Sequence[float]],
) -> List[List[float]]:
    """Apply the collector's documented presence/input window independently."""
    rows, columns = len(grid), len(assets)
    presence = presence_matrix(frames, grid)
    fields = _physical_input_fields(factor, alpha_id)
    lookback = history_h(alpha_id)
    invalid_prefixes: List[List[int]] = []
    for column, asset in enumerate(assets):
        frame = frames[asset]
        field_values = {}
        for field in fields:
            if field in frame.columns:
                field_values[field] = frame[field].reindex(grid).tolist()
            else:
                field_values[field] = [None] * rows
        prefix = [0]
        for row in range(rows):
            invalid = not presence[row][column]
            if not invalid:
                invalid = any(
                    not _physical_value_is_usable(field_values[field][row]) for field in fields
                )
            prefix.append(prefix[-1] + int(invalid))
        invalid_prefixes.append(prefix)

    masked = [[float(value) for value in row] for row in expected]
    for row in range(rows):
        start = max(0, row - lookback)
        for column in range(columns):
            complete = presence[row][column] and (
                invalid_prefixes[column][row + 1] - invalid_prefixes[column][start] == 0
            )
            if not complete:
                masked[row][column] = math.nan
    return masked


def _panel_factor_matrix(
    strategy: Any, factor: Any, assets: Sequence[str], grid: Sequence[Any]
) -> List[List[float]]:
    panel_factors = strategy.get_panel().factors
    factor_name = factor._factor_runtime.get("factor_name")
    if not factor_name or factor_name not in panel_factors.columns:
        raise AssertionError("factor collector panel is missing its declared factor column")
    result = []
    for point in grid:
        time_key = point.to_pydatetime() if hasattr(point, "to_pydatetime") else point
        row = []
        for asset in assets:
            try:
                value = panel_factors.at[(time_key, asset), factor_name]
            except KeyError:
                value = panel_factors.at[(point, asset), factor_name]
            row.append(float(value))
        result.append(row)
    return result


def validate_factor_trace(
    factor: Any,
    alpha_id: int,
    frames: Mapping[str, Any],
    assets: Sequence[str],
    grid: Sequence[Any],
    *,
    strategy: Any,
) -> Dict[str, Any]:
    """Validate field bindings, AST topology, and every matched native node."""
    if factor.__class__.formula != formula_source(alpha_id):
        raise AssertionError(
            "Alpha%d class formula differs from its independent catalog" % alpha_id
        )
    rows, columns = len(grid), len(assets)
    bound_assets = tuple(getattr(data, "_name", None) for data in factor.datas)
    if bound_assets != tuple(assets):
        raise AssertionError(
            "Alpha%d target order %r differs from reference asset order %r"
            % (alpha_id, bound_assets, tuple(assets))
        )
    matrices = oracle_frames(frames, grid=grid)
    # Membership follows independently projected real-bar presence. A missing
    # bar is not interchangeable with a present row whose value is NaN.
    members = presence_matrix(frames, grid)
    context = _Context(matrices, formula_universe=members, snap_correlation_bounds=False)
    failures: List[str] = []

    for alias in factor._field_line_cache:
        alias = str(alias).lower()
        if alias not in matrices and not (alias.startswith("adv") and alias[3:].isdigit()):
            continue
        actual = _actual_field_matrix(factor, alias, rows, columns)
        expected = context.field(alias)
        ok, message = _compare_matrices(
            actual, expected, exact=False, label="Alpha%d field %s" % (alpha_id, alias)
        )
        if not ok:
            failures.append(message)
        else:
            context.memo[("name", alias)] = actual

    expected_root, production = _production_graph(factor, alpha_id)
    ast_nodes = tuple(_postorder(expected_root))
    for ast_node in ast_nodes:
        if ast_node[0] in ("unary", "binary", "ternary", "call") and not production.get(ast_node):
            failures.append("Alpha%d AST operator has no native node: %r" % (alpha_id, ast_node))
    for ast_node in ast_nodes:
        expected = context.evaluate(ast_node)
        candidates = production.get(ast_node, ())
        if not candidates:
            continue
        exact = _exact_discrete_ast(ast_node)
        candidate_failures = []
        for candidate_index, actual in enumerate(candidates):
            ok, message = _compare_matrices(
                actual,
                expected,
                exact=exact,
                label="Alpha%d node %r copy %d" % (alpha_id, ast_node, candidate_index),
            )
            if not ok:
                candidate_failures.append(message)
        if candidate_failures:
            failures.extend(candidate_failures)
            continue
        first = candidates[0]
        for duplicate in candidates[1:]:
            ok, message = _compare_matrices(
                duplicate,
                first,
                exact=True,
                label="Alpha%d duplicate node %r" % (alpha_id, ast_node),
            )
            if not ok:
                failures.append(message)
        if ast_node != expected_root:
            # Only a locally validated node is allowed to feed the next AST
            # operation. Rank and branch semantics therefore use the actual
            # float64 values already accepted at their input nodes.
            context.memo[ast_node] = first

    expected = context.evaluate(expected_root)
    actual = _matrix_from_lines(factor._result_lines, rows)
    final_exact = _exact_discrete_ast(expected_root)
    ok, message = _compare_matrices(
        actual,
        expected,
        exact=final_exact,
        label="Alpha%d final" % alpha_id,
    )
    if not ok:
        failures.append(message)
    output_lines = [factor.outputs[data].factor for data in factor.datas]
    output_matrix = _matrix_from_lines(output_lines, rows)
    ok, message = _compare_matrices(
        output_matrix,
        actual,
        exact=True,
        label="Alpha%d factor output copy" % alpha_id,
    )
    if not ok:
        failures.append(message)
    panel_actual = _panel_factor_matrix(strategy, factor, assets, grid)
    panel_expected = _collector_expected_matrix(factor, alpha_id, frames, assets, grid, expected)
    ok, message = _compare_matrices(
        panel_actual,
        panel_expected,
        exact=final_exact,
        label="Alpha%d collector panel" % alpha_id,
    )
    if not ok:
        failures.append(message)
    finite_witness = any(math.isfinite(float(value)) for row in expected for value in row)
    if not finite_witness:
        failures.append("Alpha%d has no finite positive-fixture value" % alpha_id)
    return {
        "failures": failures,
        "expected": expected,
        "actual": actual,
        "factor_outputs": output_matrix,
        "panel_expected": panel_expected,
        "panel_actual": panel_actual,
        "matched_nodes": sum(len(production.get(node, ())) for node in ast_nodes),
        "finite_witness": finite_witness,
    }


__all__ = ("_compare_matrices", "_exact_discrete_ast", "validate_factor_trace")
