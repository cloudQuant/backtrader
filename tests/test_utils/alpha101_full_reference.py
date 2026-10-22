"""Independent matrix oracle for the frozen Alpha101 source formulas.

This module intentionally has no Backtrader imports.  It reads the preserved
paper-formula catalog as *test input*, parses its expression text, and evaluates
that text with scalar/matrix routines owned here.  It is suitable for checking
the production native tree; it must never become a production formula compiler.

Matrices are row-major ``time x asset`` sequences.  ``frames`` may be either
``{field: matrix}`` or ``{asset: {field: series}}`` / a mapping of asset names
to dataframe-like objects.  Classification matrices named ``sector``,
``industry`` and ``subindustry`` are treated as already-projected point-in-time
values on the exact research grid: this module never fills or shifts them.
"""

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "research" / "alpha101_dependencies.json"
)
with _CATALOG_PATH.open("r", encoding="utf-8") as _catalog_file:
    _CATALOG = json.load(_catalog_file)

if _CATALOG.get("profile_id") != "alpha101-v1":
    raise RuntimeError("Alpha101 reference requires the alpha101-v1 formula catalog")

_FORMULAS = {int(item["id"]): item for item in _CATALOG["formulas"]}
if tuple(sorted(_FORMULAS)) != tuple(range(1, 102)):
    raise RuntimeError("Alpha101 formula catalog must contain ids 1 through 101 exactly once")
for _entry in _FORMULAS.values():
    _source_bytes = _entry["source_formula"].encode("utf-8")
    if hashlib.sha256(_source_bytes).hexdigest() != _entry["source_formula_sha256"]:
        raise RuntimeError(
            "Alpha%d source formula digest does not match its catalog pin" % _entry["id"]
        )

_TOKEN = re.compile(
    r"\s*(?:(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|"
    r"(?P<name>[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*)|"
    r"(?P<op>\|\||==|<=|>=|[()+\-*/^<>,?:]))"
)
_CATEGORY_PREFIX = "indclass."


class FormulaError(ValueError):
    """Malformed, unsupported, or structurally invalid Alpha101 reference input."""


def formula_ids() -> Tuple[int, ...]:
    """Return the fixed 1..101 paper-formula ids."""
    return tuple(sorted(_FORMULAS))


def formula_source(alpha_id: int) -> str:
    """Return the exact normalized Appendix A source text for one formula."""
    return _entry(alpha_id)["source_formula"]


def formula_group(alpha_id: int) -> str:
    """Return the catalog research group (TS, CS, or industry)."""
    return _entry(alpha_id)["group"]


def formula_metadata(alpha_id: int) -> Mapping[str, Any]:
    """Return a defensive copy of the static, non-executable source metadata."""
    return json.loads(json.dumps(_entry(alpha_id)))


def _entry(alpha_id: int) -> Mapping[str, Any]:
    if isinstance(alpha_id, bool) or not isinstance(alpha_id, int) or alpha_id not in _FORMULAS:
        raise FormulaError("alpha_id must be an integer from 1 through 101")
    return _FORMULAS[alpha_id]


def _tokens(source: str) -> List[Tuple[str, str]]:
    result: List[Tuple[str, str]] = []
    offset = 0
    while offset < len(source):
        if not source[offset:].strip():
            break
        match = _TOKEN.match(source, offset)
        if match is None:
            raise FormulaError("unsupported formula token at offset %d" % offset)
        kind = (
            "number"
            if match.group("number") is not None
            else ("name" if match.group("name") is not None else "op")
        )
        result.append((kind, match.group(kind)))
        offset = match.end()
    result.append(("eof", ""))
    return result


class _Parser:
    """Small Pratt parser for the operator and punctuation set in Appendix A."""

    _PRECEDENCE = {
        "||": 1,
        "<": 2,
        "==": 2,
        "<=": 2,
        ">": 2,
        ">=": 2,
        "+": 3,
        "-": 3,
        "*": 4,
        "/": 4,
        "^": 6,
    }

    def __init__(self, source: str) -> None:
        self._tokens = _tokens(source)
        self._position = 0

    def _peek(self) -> Tuple[str, str]:
        return self._tokens[self._position]

    def _take(self) -> Tuple[str, str]:
        token = self._peek()
        self._position += 1
        return token

    def _expect(self, value: str) -> None:
        token = self._take()
        if token[1] != value:
            raise FormulaError("expected %r, got %r" % (value, token[1]))

    def parse(self) -> Tuple[Any, ...]:
        tree = self._expression(0)
        if self._peek()[0] != "eof":
            raise FormulaError("unexpected trailing formula token %r" % self._peek()[1])
        return tree

    def _expression(self, minimum: int) -> Tuple[Any, ...]:
        kind, value = self._take()
        if kind == "number":
            left: Tuple[Any, ...] = ("number", float(value))
        elif kind == "name":
            if self._peek()[1] == "(":
                self._take()
                arguments: List[Tuple[Any, ...]] = []
                if self._peek()[1] != ")":
                    while True:
                        arguments.append(self._expression(0))
                        if self._peek()[1] != ",":
                            break
                        self._take()
                self._expect(")")
                left = ("call", value.lower(), tuple(arguments))
            else:
                left = ("name", value.lower())
        elif value == "(":
            left = self._expression(0)
            self._expect(")")
        elif value in ("+", "-"):
            # Exponentiation binds more tightly than a leading unary sign.
            left = ("unary", value, self._expression(5))
        else:
            raise FormulaError("unexpected formula token %r" % value)

        while True:
            kind, operator = self._peek()
            if operator == "?" and minimum <= 0:
                self._take()
                yes = self._expression(0)
                self._expect(":")
                no = self._expression(0)
                left = ("ternary", left, yes, no)
                continue
            precedence = self._PRECEDENCE.get(operator)
            if kind != "op" or precedence is None or precedence < minimum:
                break
            self._take()
            # '^' is right-associative; all other binary operators are left.
            right_minimum = precedence if operator == "^" else precedence + 1
            right = self._expression(right_minimum)
            left = ("binary", operator, left, right)
        return left


def _parse(alpha_id: int) -> Tuple[Any, ...]:
    return _Parser(formula_source(alpha_id)).parse()


def _as_sequence(value: Any) -> Any:
    if hasattr(value, "to_numpy"):
        value = value.to_numpy()
    if hasattr(value, "tolist"):
        value = value.tolist()
    return value


def _is_matrix(value: Any) -> bool:
    value = _as_sequence(value)
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and isinstance(_as_sequence(value[0]), (list, tuple))
    )


def _vector(value: Any) -> List[Any]:
    value = _as_sequence(value)
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value)


def _normalize_frames(frames: Any) -> Tuple[Dict[str, List[List[Any]]], Tuple[Any, ...]]:
    if not isinstance(frames, Mapping) or not frames:
        raise FormulaError("frames must be a nonempty mapping of field or asset matrices")
    known_fields = {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
        "dollar_volume",
        "cap",
        "returns",
        "adv5",
        "adv10",
        "adv15",
        "adv20",
        "adv30",
        "adv40",
        "adv50",
        "adv60",
        "adv81",
        "adv120",
        "adv150",
        "adv180",
        "sector",
        "industry",
        "subindustry",
    }
    normalized_keys = {str(key).lower() for key in frames}
    field_oriented = normalized_keys.issubset(known_fields) and any(
        _is_matrix(value) for value in frames.values()
    )
    result: Dict[str, List[List[Any]]] = {}
    assets: Tuple[Any, ...]
    if field_oriented:
        assets = tuple(range(len(_as_sequence(next(iter(frames.values()))[0]))))
        for field, raw in frames.items():
            rows = _as_sequence(raw)
            if not isinstance(rows, (list, tuple)) or not rows:
                raise FormulaError("field %s must be a nonempty time x asset matrix" % field)
            result[str(field).lower()] = [list(_as_sequence(row)) for row in rows]
    else:
        assets = tuple(frames)
        asset_tables = []
        for asset, raw in frames.items():
            if hasattr(raw, "columns") and hasattr(raw, "__getitem__"):
                table = {str(column).lower(): _vector(raw[column]) for column in raw.columns}
            elif isinstance(raw, Mapping):
                table = {str(field).lower(): _vector(values) for field, values in raw.items()}
            else:
                raise FormulaError("asset %r must map fields to one-dimensional series" % (asset,))
            asset_tables.append(table)
        fields = set.intersection(*(set(table) for table in asset_tables))
        if not fields:
            raise FormulaError("asset frames have no common input fields")
        row_counts = {len(table[field]) for table in asset_tables for field in fields}
        if len(row_counts) != 1 or not row_counts or next(iter(row_counts)) == 0:
            raise FormulaError("asset frames must have equal nonzero time lengths")
        rows_count = next(iter(row_counts))
        for field in fields:
            result[field] = [
                [table[field][row] for table in asset_tables] for row in range(rows_count)
            ]

    if not result:
        raise FormulaError("frames contain no matrices")
    dimensions = set()
    for field, rows in result.items():
        if not rows:
            raise FormulaError("field %s has no time rows" % field)
        if any(not isinstance(row, (list, tuple)) for row in rows):
            raise FormulaError("field %s must be a rectangular time x asset matrix" % field)
        widths = {len(row) for row in rows}
        if len(widths) != 1:
            raise FormulaError("field %s must be a rectangular time x asset matrix" % field)
        width = next(iter(widths))
        if width == 0:
            raise FormulaError("field %s has no asset columns" % field)
        dimensions.add((len(rows), width))
    if len(dimensions) != 1:
        raise FormulaError("all input matrices must have the same time x asset shape")
    time_count, asset_count = next(iter(dimensions))
    if len(assets) != asset_count:
        assets = tuple(range(asset_count))
    return result, assets


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    try:
        return bool(value != value)
    except Exception:
        return False


def _numeric_matrix(matrix: Sequence[Sequence[Any]], name: str) -> List[List[float]]:
    result: List[List[float]] = []
    for row in matrix:
        converted = []
        for raw in row:
            if _missing(raw):
                converted.append(math.nan)
                continue
            if isinstance(raw, bool):
                raise FormulaError("numeric field %s contains a boolean" % name)
            try:
                value = float(raw)
            except (TypeError, ValueError, OverflowError) as exc:
                raise FormulaError("numeric field %s contains a nonnumeric value" % name) from exc
            if math.isinf(value):
                raise FormulaError("numeric field %s contains infinity" % name)
            converted.append(value)
        result.append(converted)
    return result


def _groups_matrix(groups: Any, rows: int, columns: int, assets: Sequence[Any]) -> List[List[Any]]:
    if groups is None:
        return [["market"] * columns for _ in range(rows)]
    if isinstance(groups, Mapping):
        try:
            values = [groups[asset] for asset in assets]
        except KeyError as exc:
            raise FormulaError("research groups must cover every asset") from exc
        raw = values
    else:
        raw = _as_sequence(groups)
    if _is_matrix(raw):
        matrix = [list(_as_sequence(row)) for row in raw]
        if len(matrix) != rows or any(len(row) != columns for row in matrix):
            raise FormulaError("time-varying research groups must match the input matrix")
    else:
        values = list(raw)
        if len(values) != columns:
            raise FormulaError("research groups must have one key per asset")
        matrix = [values[:] for _ in range(rows)]
    if any(_missing(value) for row in matrix for value in row):
        raise FormulaError("unknown research group state is not allowed")
    return matrix


def _membership_matrix(members: Any, rows: int, columns: int) -> List[List[bool]]:
    if members is None:
        return [[True] * columns for _ in range(rows)]
    raw = _as_sequence(members)
    if not isinstance(raw, (list, tuple)) or len(raw) != rows:
        raise FormulaError("formula_universe must be a time x asset boolean matrix")
    result: List[List[bool]] = []
    for row in raw:
        values = _as_sequence(row)
        if not isinstance(values, (list, tuple)) or len(values) != columns:
            raise FormulaError("formula_universe must match the input matrix shape")
        converted = []
        for value in values:
            if isinstance(value, bool):
                converted.append(value)
            elif (
                isinstance(value, (int, float)) and not isinstance(value, bool) and value in (0, 1)
            ):
                converted.append(bool(value))
            else:
                raise FormulaError("unknown/non-boolean formula_universe state is not allowed")
        result.append(converted)
    return result


def _finite(value: float) -> bool:
    return math.isfinite(value)


def _safe(function: Any, *values: float) -> float:
    try:
        result = float(function(*values))
    except (ArithmeticError, OverflowError, ValueError):
        return math.nan
    return result if _finite(result) else math.nan


def _pointwise(function: Any, *matrices: Sequence[Sequence[float]]) -> List[List[float]]:
    matrix_arguments = [value for value in matrices if isinstance(value, (list, tuple))]
    if not matrix_arguments:
        return _safe(function, *matrices)
    rows, columns = len(matrix_arguments[0]), len(matrix_arguments[0][0])
    expanded = [
        value if isinstance(value, (list, tuple)) else _constant_matrix(float(value), rows, columns)
        for value in matrices
    ]
    output = [[math.nan] * columns for _ in range(rows)]
    for row in range(rows):
        for column in range(columns):
            values = [matrix[row][column] for matrix in expanded]
            if all(_finite(value) for value in values):
                output[row][column] = _safe(function, *values)
    return output


def _constant_matrix(value: float, rows: int, columns: int) -> List[List[float]]:
    return [[value] * columns for _ in range(rows)]


def _logical_or(left: Any, right: Any, rows: int, columns: int) -> List[List[float]]:
    left_matrix = (
        left if isinstance(left, (list, tuple)) else _constant_matrix(float(left), rows, columns)
    )
    right_matrix = (
        right if isinstance(right, (list, tuple)) else _constant_matrix(float(right), rows, columns)
    )
    output = [[math.nan] * columns for _ in range(rows)]
    for row in range(rows):
        for column in range(columns):
            x, y = left_matrix[row][column], right_matrix[row][column]
            if _finite(x) and x not in (0.0, 1.0):
                raise FormulaError("logical operands must be 0/1/unknown values")
            if _finite(y) and y not in (0.0, 1.0):
                raise FormulaError("logical operands must be 0/1/unknown values")
            if (math.isfinite(x) and x == 1.0) or (math.isfinite(y) and y == 1.0):
                output[row][column] = 1.0
            elif math.isfinite(x) and math.isfinite(y):
                output[row][column] = 0.0
    return output


def _window(value: float, *, allow_zero: bool = False) -> int:
    if not _finite(value):
        raise FormulaError("window must be a finite number")
    result = math.floor(value)
    minimum = 0 if allow_zero else 1
    if result < minimum:
        raise FormulaError("floor(window) must be >= %d" % minimum)
    return result


def _shift(source: Sequence[Sequence[float]], period: int) -> List[List[float]]:
    rows, columns = len(source), len(source[0])
    return [
        [source[row - period][column] if row >= period else math.nan for column in range(columns)]
        for row in range(rows)
    ]


def _rolling(source: Sequence[Sequence[float]], period: int, function: Any) -> List[List[float]]:
    rows, columns = len(source), len(source[0])
    output = [[math.nan] * columns for _ in range(rows)]
    for row in range(period - 1, rows):
        start = row - period + 1
        for column in range(columns):
            values = [source[position][column] for position in range(start, row + 1)]
            if all(_finite(value) for value in values):
                output[row][column] = _safe(function, values)
    return output


def _rank(values: Sequence[float]) -> List[float]:
    count = len(values)
    if not count:
        return []
    order = sorted(range(count), key=lambda index: values[index])
    result = [math.nan] * count
    start = 0
    while start < count:
        end = start + 1
        while end < count and values[order[end]] == values[order[start]]:
            end += 1
        # Average one-based rank divided by finite group population.
        rank_value = ((start + 1) + end) / 2.0 / count
        for offset in range(start, end):
            result[order[offset]] = rank_value
        start = end
    return result


def _cs(
    source: Sequence[Sequence[float]], context: "_Context", scale: bool = False
) -> List[List[float]]:
    rows, columns = len(source), len(source[0])
    output = [[math.nan] * columns for _ in range(rows)]
    for row in range(rows):
        partitions: Dict[Any, List[int]] = {}
        for column, value in enumerate(source[row]):
            if context.members[row][column] and _finite(value):
                partitions.setdefault(context.groups[row][column], []).append(column)
        for positions in partitions.values():
            values = [source[row][column] for column in positions]
            if scale:
                magnitude = max(abs(value) for value in values)
                if magnitude == 0.0:
                    continue
                denominator = math.fsum(abs(value / magnitude) for value in values)
                for column, value in zip(positions, values):
                    output[row][column] = _safe(
                        lambda x, magnitude=magnitude, denominator=denominator: (
                            (x / magnitude) / denominator
                        ),
                        value,
                    )
            else:
                ranks = _rank(values)
                for column, value in zip(positions, ranks):
                    output[row][column] = value
    return output


def _neutralize(
    source: Sequence[Sequence[float]], categories: Sequence[Sequence[Any]], context: "_Context"
) -> List[List[float]]:
    rows, columns = len(source), len(source[0])
    output = [[math.nan] * columns for _ in range(rows)]
    for row in range(rows):
        partitions: Dict[Any, List[int]] = {}
        for column, value in enumerate(source[row]):
            category = categories[row][column]
            if context.members[row][column] and _finite(value) and not _missing(category):
                partitions.setdefault(category, []).append(column)
        for positions in partitions.values():
            mean = _mean([source[row][column] for column in positions])
            for column in positions:
                output[row][column] = _safe(
                    lambda value, mean=mean: value - mean, source[row][column]
                )
    return output


def _rolling_rank(source: Sequence[Sequence[float]], period: int) -> List[List[float]]:
    rows, columns = len(source), len(source[0])
    output = [[math.nan] * columns for _ in range(rows)]
    for row in range(period - 1, rows):
        start = row - period + 1
        for column in range(columns):
            values = [source[position][column] for position in range(start, row + 1)]
            if all(_finite(value) for value in values):
                output[row][column] = _rank(values)[-1]
    return output


def _arg_position(values: Sequence[float], maximum: bool) -> float:
    target = max(values) if maximum else min(values)
    # The source operator chooses the earliest slot when values tie.
    return float(next(index + 1 for index, value in enumerate(values) if value == target))


def _decay(values: Sequence[float]) -> float:
    denominator = len(values) * (len(values) + 1) / 2.0
    scale = max((abs(value) for value in values), default=0.0)
    if scale == 0.0:
        return 0.0
    normalized = math.fsum(
        (value / scale) * ((index + 1) / denominator) for index, value in enumerate(values)
    )
    return scale * normalized


def _signed_power(value: float, exponent: float) -> float:
    if value == 0.0:
        if exponent < 0.0:
            raise ValueError("zero to a negative signed power")
        return 0.0
    return math.copysign(math.pow(abs(value), exponent), value)


def _pair_rolling(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
    period: int,
    covariance: bool,
    *,
    snap_correlation_bounds: bool = True,
) -> List[List[float]]:
    """Independent rolling covariance / Pearson correlation over float64 inputs.

    The production operators run float64 (alpha101-v2).  This reference uses
    NumPy's centered dot products by default, i.e. a different implementation
    of the same mathematics. The strict trace profile instead uses exact
    rational arithmetic on the supplied binary64 samples and rounds the final
    result once; it avoids cancellation and is independent of production's
    kernel. Windows containing a non-finite input are skipped, a constant
    window has covariance 0 and correlation NaN.
    """
    if not snap_correlation_bounds:
        # The strict trace profile computes the exact rational covariance of
        # the supplied binary64 samples, then rounds the square root once.
        # This avoids NumPy mean/variance cancellation near a constant window
        # and does not merge nearby correlation values with an epsilon.
        from decimal import Decimal, localcontext
        from fractions import Fraction

        rows, columns = len(left), len(left[0])
        output = [[math.nan] * columns for _ in range(rows)]
        for column in range(columns):
            for row in range(period - 1, rows):
                start = row - period + 1
                raw_x = [float(left[position][column]) for position in range(start, row + 1)]
                raw_y = [float(right[position][column]) for position in range(start, row + 1)]
                if not all(math.isfinite(value) for value in raw_x + raw_y):
                    continue
                xs = [Fraction.from_float(value) for value in raw_x]
                ys = [Fraction.from_float(value) for value in raw_y]
                if len(set(xs)) == 1 or len(set(ys)) == 1:
                    if covariance:
                        output[row][column] = 0.0
                    continue
                mean_x = sum(xs, Fraction(0)) / period
                mean_y = sum(ys, Fraction(0)) / period
                dx = [value - mean_x for value in xs]
                dy = [value - mean_y for value in ys]
                cross = sum((x * y for x, y in zip(dx, dy)), Fraction(0))
                if covariance:
                    output[row][column] = float(cross / period)
                    continue
                variance_x = sum((value * value for value in dx), Fraction(0))
                variance_y = sum((value * value for value in dy), Fraction(0))
                if variance_x == 0 or variance_y == 0:
                    continue
                squared = cross * cross / (variance_x * variance_y)
                with localcontext() as decimal_context:
                    decimal_context.prec = 100
                    magnitude = (Decimal(squared.numerator) / Decimal(squared.denominator)).sqrt()
                if cross < 0:
                    magnitude = -magnitude
                value = float(magnitude)
                if math.isfinite(value) and abs(value) <= 1.0:
                    output[row][column] = value
        return output

    import numpy as np

    rows, columns = len(left), len(left[0])
    output = [[math.nan] * columns for _ in range(rows)]
    for column in range(columns):
        xs = np.asarray([float(left[row][column]) for row in range(rows)], dtype="float64")
        ys = np.asarray([float(right[row][column]) for row in range(rows)], dtype="float64")
        for row in range(period - 1, rows):
            start = row - period + 1
            window_x = xs[start : row + 1]
            window_y = ys[start : row + 1]
            if not (np.isfinite(window_x).all() and np.isfinite(window_y).all()):
                continue
            # An exactly constant window has zero variance.  Centering it in
            # floating point leaves ~1e-17 residuals whose dot product is a
            # meaningless positive number; decide constancy on the raw values.
            if np.all(window_x == window_x[0]) or np.all(window_y == window_y[0]):
                if covariance:
                    output[row][column] = 0.0
                continue
            dx = window_x - window_x.mean()
            dy = window_y - window_y.mean()
            if covariance:
                value = float(np.dot(dx, dy) / period)
                output[row][column] = value if _finite(value) else math.nan
                continue
            variance_x = float(np.dot(dx, dx))
            variance_y = float(np.dot(dy, dy))
            if variance_x <= 0.0 or variance_y <= 0.0:
                continue
            value = float(np.dot(dx, dy) / math.sqrt(variance_x * variance_y))
            # Match the specified float64 contract: ULP-level noise around the
            # correlation bounds is the bound itself, not a distinct value.
            if snap_correlation_bounds:
                snap = 8.0 * 2.220446049250313e-16
                if abs(value) <= snap:
                    value = 0.0
                elif abs(value) >= 1.0 - snap:
                    value = math.copysign(1.0, value)
            if _finite(value) and abs(value) <= 1.0:
                output[row][column] = value
    return output


class _Category:
    def __init__(self, level: str) -> None:
        self.level = level


class _Context:
    def __init__(
        self,
        frames: Any,
        formula_universe: Any = None,
        groups: Any = None,
        *,
        snap_correlation_bounds: bool = True,
    ) -> None:
        self.raw, self.assets = _normalize_frames(frames)
        shape = next(iter(self.raw.values()))
        self.rows, self.columns = len(shape), len(shape[0])
        self.members = _membership_matrix(formula_universe, self.rows, self.columns)
        self.groups = _groups_matrix(groups, self.rows, self.columns, self.assets)
        self.snap_correlation_bounds = bool(snap_correlation_bounds)
        self.matrices: Dict[str, List[List[float]]] = {}
        self.memo: Dict[Tuple[Any, ...], Any] = {}

    def field(self, name: str) -> List[List[float]]:
        if name in self.matrices:
            return self.matrices[name]
        if name == "returns":
            close = self.field("close")
            prior = _shift(close, 1)
            matrix = _pointwise(
                lambda current, previous: (current - previous) / previous, close, prior
            )
        elif name.startswith("adv") and name[3:].isdigit() and name not in self.raw:
            window = int(name[3:])
            matrix = _rolling(self.field("dollar_volume"), _window(float(window)), _mean)
        else:
            if name not in self.raw:
                raise FormulaError("formula input field %r is absent" % name)
            matrix = _numeric_matrix(self.raw[name], name)
        self.matrices[name] = matrix
        return matrix

    def evaluate(self, node: Tuple[Any, ...]) -> Any:
        if node in self.memo:
            return self.memo[node]
        kind = node[0]
        if kind == "number":
            value: Any = node[1]
        elif kind == "name":
            name = node[1]
            if name.startswith(_CATEGORY_PREFIX):
                level = name[len(_CATEGORY_PREFIX) :]
                if level not in ("sector", "industry", "subindustry"):
                    raise FormulaError("unsupported classification level %r" % level)
                if level not in self.raw:
                    raise FormulaError("PIT classification matrix %r is required" % level)
                value = _normalize_category_matrix(self.raw[level], level, self.rows, self.columns)
            else:
                value = self.field(name)
        elif kind == "unary":
            source = self.evaluate(node[2])
            value = _pointwise((lambda x: x) if node[1] == "+" else (lambda x: -x), source)
        elif kind == "binary":
            value = self._binary(node[1], self.evaluate(node[2]), self.evaluate(node[3]))
        elif kind == "ternary":
            condition = self.evaluate(node[1])
            yes = self.evaluate(node[2])
            no = self.evaluate(node[3])
            value = self._where(condition, yes, no)
        elif kind == "call":
            value = self._call(node[1], node[2])
        else:
            raise FormulaError("unknown parsed node %r" % (kind,))
        self.memo[node] = value
        return value

    def _binary(self, operator: str, left: Any, right: Any) -> Any:
        if operator == "||":
            # Kleene OR: a known true operand determines the result even if
            # the other side is unknown; two known false operands yield false.
            return _logical_or(left, right, self.rows, self.columns)
        functions = {
            "+": lambda x, y: x + y,
            "-": lambda x, y: x - y,
            "*": lambda x, y: x * y,
            "/": lambda x, y: x / y,
            "^": math.pow,
            "<": lambda x, y: float(x < y),
            ">": lambda x, y: float(x > y),
            "<=": lambda x, y: float(x <= y),
            ">=": lambda x, y: float(x >= y),
            "==": lambda x, y: float(x == y),
        }
        try:
            function = functions[operator]
        except KeyError as exc:
            raise FormulaError("unsupported binary operator %r" % operator) from exc
        return _pointwise(function, left, right)

    def _where(
        self,
        condition: Sequence[Sequence[float]],
        yes: Sequence[Sequence[float]],
        no: Sequence[Sequence[float]],
    ) -> List[List[float]]:
        if not isinstance(condition, (list, tuple)):
            condition = _constant_matrix(float(condition), self.rows, self.columns)
        if not isinstance(yes, (list, tuple)):
            yes = _constant_matrix(float(yes), self.rows, self.columns)
        if not isinstance(no, (list, tuple)):
            no = _constant_matrix(float(no), self.rows, self.columns)
        output = [[math.nan] * self.columns for _ in range(self.rows)]
        for row in range(self.rows):
            for column in range(self.columns):
                test = condition[row][column]
                if not _finite(test):
                    continue
                if test not in (0.0, 1.0):
                    raise FormulaError("where condition must be 0/1/unknown")
                selected = yes if test == 1.0 else no
                value = selected[row][column]
                if _finite(value):
                    output[row][column] = value
        return output

    def _call(self, name: str, argument_nodes: Sequence[Tuple[Any, ...]]) -> Any:
        arguments = [self.evaluate(argument) for argument in argument_nodes]
        if name in ("rank",):
            return _cs(arguments[0], self)
        if name == "scale":
            return _cs(arguments[0], self, scale=True)
        if name == "indneutralize":
            if len(arguments) != 2 or not isinstance(arguments[1], list):
                raise FormulaError("IndNeutralize requires values and an IndClass level")
            return _neutralize(arguments[0], arguments[1], self)
        if name in ("abs", "log", "sign"):
            function = {
                "abs": abs,
                "log": math.log,
                "sign": lambda value: 1.0 if value > 0 else (-1.0 if value < 0 else 0.0),
            }[name]
            return _pointwise(function, arguments[0])
        if name == "signedpower":
            return _pointwise(_signed_power, arguments[0], arguments[1])
        if name in (
            "sum",
            "product",
            "stddev",
            "decay_linear",
            "ts_rank",
            "ts_min",
            "ts_max",
            "ts_argmax",
            "ts_argmin",
            "delay",
            "delta",
        ):
            source = arguments[0]
            if name == "delay":
                return _shift(source, _window(arguments[1], allow_zero=True))
            if name == "delta":
                period = _window(arguments[1])
                return _pointwise(lambda x, prior: x - prior, source, _shift(source, period))
            period = _window(arguments[1])
            if name == "sum":
                return _rolling(source, period, _sum)
            if name == "product":
                return _rolling(source, period, math.prod)
            if name == "stddev":
                return _rolling(source, period, _std)
            if name == "decay_linear":
                return _rolling(source, period, _decay)
            if name == "ts_rank":
                return _rolling_rank(source, period)
            if name == "ts_min":
                return _rolling(source, period, min)
            if name == "ts_max":
                return _rolling(source, period, max)
            if name == "ts_argmax":
                return _rolling(source, period, lambda values: _arg_position(values, True))
            if name == "ts_argmin":
                return _rolling(source, period, lambda values: _arg_position(values, False))
        if name in ("correlation", "covariance"):
            return _pair_rolling(
                arguments[0],
                arguments[1],
                _window(arguments[2]),
                covariance=name == "covariance",
                snap_correlation_bounds=self.snap_correlation_bounds,
            )
        if name in ("min", "max"):
            if len(arguments) != 2:
                raise FormulaError("min/max require two arguments")
            if argument_nodes[1][0] == "number":
                period = _window(arguments[1])
                return _rolling(arguments[0], period, min if name == "min" else max)
            function = min if name == "min" else max
            return _pointwise(function, arguments[0], arguments[1])
        raise FormulaError("unsupported function %r" % name)


def _normalize_category_matrix(
    matrix: Sequence[Sequence[Any]], level: str, rows: int, columns: int
) -> List[List[Any]]:
    values = [_as_sequence(row) for row in _as_sequence(matrix)]
    if len(values) != rows or any(
        not isinstance(row, (list, tuple)) or len(row) != columns for row in values
    ):
        raise FormulaError("PIT classification %s must match the input matrix" % level)
    return [list(row) for row in values]


def _classification_levels(node: Tuple[Any, ...]) -> set:
    """Collect explicit ``IndClass.<level>`` inputs from parsed source text."""
    if node[0] == "name":
        name = node[1]
        return {name[len(_CATEGORY_PREFIX) :]} if name.startswith(_CATEGORY_PREFIX) else set()
    if node[0] == "number":
        return set()
    if node[0] == "unary":
        return _classification_levels(node[2])
    if node[0] == "binary":
        return _classification_levels(node[2]) | _classification_levels(node[3])
    if node[0] == "ternary":
        return (
            _classification_levels(node[1])
            | _classification_levels(node[2])
            | _classification_levels(node[3])
        )
    if node[0] == "call":
        levels = set()
        for argument in node[2]:
            levels.update(_classification_levels(argument))
        return levels
    raise FormulaError("unknown parsed node while locating PIT inputs")


def _sum(values: Sequence[float]) -> float:
    return math.fsum(values)


def _mean(values: Sequence[float]) -> float:
    scale = max((abs(value) for value in values), default=0.0)
    if scale == 0.0:
        return 0.0
    return scale * (math.fsum(value / scale for value in values) / len(values))


def _std(values: Sequence[float]) -> float:
    scale = max((abs(value) for value in values), default=0.0)
    if scale == 0.0:
        return 0.0
    normalized = [value / scale for value in values]
    average = _mean(normalized)
    variance = math.fsum((value - average) ** 2 for value in normalized) / len(values)
    return scale * math.sqrt(variance)


def _history(node: Tuple[Any, ...], frames: Optional[Any] = None) -> int:
    """Structural first-finite zero-based grid index for the formula tree."""
    kind = node[0]
    if kind == "number":
        return 0
    if kind == "name":
        name = node[1]
        if name.startswith(_CATEGORY_PREFIX):
            return 0
        if name == "returns":
            return 1
        if name.startswith("adv") and name[3:].isdigit():
            direct = False
            if frames is not None:
                raw, _ = _normalize_frames(frames)
                direct = name in raw
            return 0 if direct else int(name[3:]) - 1
        return 0
    if kind == "unary":
        return _history(node[2], frames)
    if kind == "binary":
        return max(_history(node[2], frames), _history(node[3], frames))
    if kind == "ternary":
        return max(_history(node[1], frames), _history(node[2], frames), _history(node[3], frames))
    name, args = node[1], node[2]
    child_histories = [_history(argument, frames) for argument in args]
    base = max(child_histories, default=0)
    if name in ("delay", "delta"):
        return _history(args[0], frames) + _window(args[1][1], allow_zero=name == "delay")
    if name in (
        "sum",
        "product",
        "stddev",
        "correlation",
        "covariance",
        "decay_linear",
        "ts_rank",
        "ts_min",
        "ts_max",
        "ts_argmax",
        "ts_argmin",
    ):
        period_node = args[-1]
        period = _window(period_node[1]) if period_node[0] == "number" else 1
        input_history = max(_history(argument, frames) for argument in args[:-1])
        return input_history + period - 1
    if name in ("min", "max") and len(args) == 2 and args[1][0] == "number":
        period = _window(args[1][1])
        return _history(args[0], frames) + period - 1
    return base


def history_h(alpha_id: int, frames: Optional[Any] = None) -> int:
    """Return the independent structural warmup H (zero-based first grid slot).

    ``returns`` contributes one source bar.  If ``advN`` is not supplied as a
    matrix in ``frames``, it is independently derived as the N-grid arithmetic
    mean of ``dollar_volume``; its source lookback is therefore N-1.  Formula
    and rolling-operator windows use ``floor`` exactly as alpha101-v1 does.
    This is a structural bound: missing/domain-invalid data can make an actual
    output become finite later.
    """
    return _history(_parse(alpha_id), frames)


def reference(
    alpha_id: int,
    frames: Any,
    formula_universe: Any = None,
    groups: Any = None,
) -> List[List[float]]:
    """Compute one source formula on plain time-by-asset inputs.

    When omitted, membership uses the catalog's fixed-targets-full-history
    assumption and all assets share one ``market`` research group.  A formula
    whose paper expression names ``IndClass.<level>`` still requires that
    level's explicit PIT-projected category matrix in ``frames``.
    """
    _entry(alpha_id)
    tree = _parse(alpha_id)
    context = _Context(frames, formula_universe=formula_universe, groups=groups)
    for level in _classification_levels(tree):
        if level not in context.raw:
            raise FormulaError(
                "Alpha%d requires explicit PIT %s classifications" % (alpha_id, level)
            )
    result = context.evaluate(tree)
    if not isinstance(result, list) or len(result) != context.rows:
        raise FormulaError("formula did not evaluate to a time x asset matrix")
    return [
        [value if context.members[row][column] else math.nan for column, value in enumerate(values)]
        for row, values in enumerate(result)
    ]


def reference_all(
    frames: Any,
    formula_universe: Any = None,
    groups: Any = None,
) -> Dict[int, List[List[float]]]:
    """Compute all 101 formulas against one immutable-per-call input snapshot.

    Omitted membership/groups have the same fixed-target and single-market
    defaults as :func:`reference`.  Expression results are memoized only inside
    this invocation.  A later call normalizes and reads its inputs again, so
    changing a matrix cannot be hidden by a stale cross-call result cache.
    """
    context = _Context(frames, formula_universe=formula_universe, groups=groups)
    output: Dict[int, List[List[float]]] = {}
    for alpha_id in formula_ids():
        tree = _parse(alpha_id)
        for level in _classification_levels(tree):
            if level not in context.raw:
                raise FormulaError(
                    "Alpha%d requires explicit PIT %s classifications" % (alpha_id, level)
                )
        matrix = context.evaluate(tree)
        output[alpha_id] = [
            [
                value if context.members[row][column] else math.nan
                for column, value in enumerate(values)
            ]
            for row, values in enumerate(matrix)
        ]
        # Keep only field/derived-input snapshots between formulas.  Formula
        # intermediates are memoized within one tree, never retained globally.
        context.memo.clear()
    return output


__all__ = (
    "FormulaError",
    "formula_group",
    "formula_ids",
    "formula_metadata",
    "formula_source",
    "history_h",
    "reference",
    "reference_all",
)
