"""Causal, AST-backed validation for the native Alpha101 operator graph.

The paper catalog is parsed independently from production. Native node inputs
are reconstructed from the explicit operator graph, then the reference walks
the source AST in postorder. A production node replaces the reference value
for downstream calculations only after its own output passes its local check.
This makes discrete rank and branch checks exact on validated production
float64 inputs while preserving an independent source of expected values.
"""

from __future__ import annotations

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
