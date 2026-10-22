"""Per-formula witnesses that distinguish the frozen Alpha101 oracle from errors.

This is a test-only supplement to the Iteration 46 ledger.  It imports only the
independent matrix oracle, builds the same deterministic 320x6 public fixture,
and compares each paper formula with one targeted, semantically plausible
mutation.  It does not import Backtrader, Alpha101 production nodes, the
representative test module, or the integration harness.

The ledger's per-row validation plans mark all 101 rows PLANNED_NOT_RUN.  Their
boundary plans distinguish structural H, first-window floors, delay/delta
floors, derived returns/ADV history, and PIT levels.  Their common error plans
also distinguish typed missing-input/PIT contract errors from validly shaped
mathematical-domain NaNs and unsupported-formula errors.  This file addresses
only the numeric error-distinction slice: a concrete finite output coordinate
must separate the oracle from a row-specific window, PIT, operator, or formula
structure mutation.  It does not execute the production-side boundary or
error-contract checks.
"""

from __future__ import annotations

import math
import random

import pytest

from tests.test_utils import alpha101_full_reference as oracle


_ROWS = 320
_ASSETS = 6
_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "dollar_volume",
    "cap",
    "sector",
    "industry",
    "subindustry",
)
_PIT_MUTATIONS = {
    # These are the classification-bearing IDs from the ledger's per-formula
    # PIT plan.  Each wrong level is present on the same grid, so the mutant
    # isolates category grouping rather than missing-input behavior.
    48: ("subindustry", "industry"),
    58: ("sector", "industry"),
    59: ("industry", "subindustry"),
    63: ("industry", "subindustry"),
    67: ("sector", "industry"),
    69: ("industry", "sector"),
    70: ("industry", "sector"),
    76: ("sector", "subindustry"),
    79: ("sector", "industry"),
    80: ("industry", "sector"),
    82: ("sector", "subindustry"),
    87: ("industry", "sector"),
    89: ("industry", "sector"),
    90: ("subindustry", "industry"),
    91: ("industry", "subindustry"),
    93: ("industry", "subindustry"),
    97: ("industry", "sector"),
    100: ("subindustry", "industry"),
}

_WINDOW_CALLS = {
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
}
_OFFSET_CALLS = {"delay", "delta"}
_COMPARISONS = {"<", "<=", ">", ">=", "=="}
_TOL_ATOL = 1e-12
_TOL_RTOL = 1e-10
_LEDGER_H = (
    24,
    7,
    9,
    8,
    9,
    9,
    66,
    15,
    5,
    4,
    3,
    1,
    4,
    9,
    4,
    4,
    23,
    9,
    250,
    1,
    19,
    19,
    19,
    199,
    19,
    10,
    6,
    23,
    11,
    19,
    30,
    234,
    0,
    5,
    32,
    199,
    200,
    9,
    250,
    9,
    0,
    0,
    38,
    4,
    24,
    20,
    19,
    251,
    20,
    8,
    20,
    240,
    9,
    0,
    16,
    10,
    30,
    12,
    25,
    9,
    195,
    48,
    238,
    145,
    71,
    15,
    24,
    33,
    30,
    81,
    224,
    55,
    19,
    79,
    60,
    139,
    45,
    62,
    170,
    17,
    77,
    33,
    6,
    33,
    37,
    56,
    108,
    91,
    26,
    45,
    33,
    45,
    120,
    80,
    78,
    100,
    114,
    52,
    84,
    29,
    0,
)


def _positive_fixture() -> dict[str, list[list[float]]]:
    """Recreate the shared 45/46 deterministic positive fixture as matrices.

    The data recipe matches ``test_factor_research_representatives._frames``:
    six fixed bases, independent per-field seeded streams, independent VWAP,
    derived dollar volume, and point-in-time category matrices.  Recreating
    that small recipe here keeps this independent test free of the old test
    module's production imports.
    """

    per_field: dict[str, list[list[float]]] = {name: [] for name in _FIELDS}
    bases = (2.20, 2.24, 2.28, 2.32, 2.36, 2.40)
    noise_streams = [
        (
            random.Random(45_101 + asset),
            random.Random(45_201 + asset),
            random.Random(45_301 + asset),
            random.Random(45_401 + asset),
        )
        for asset in range(_ASSETS)
    ]
    for t in range(_ROWS):
        row_values = {name: [] for name in _FIELDS}
        for asset, base in enumerate(bases):
            close_noise, open_noise, volume_noise, vwap_noise = noise_streams[asset]
            close = base + 0.0003 * t + close_noise.uniform(-0.35, 0.35)
            open_ = close + open_noise.uniform(-0.29, 0.29)
            high = max(open_, close) + 0.28 + 0.015 * math.cos(0.11 * t + asset)
            low = min(open_, close) - 0.20 - 0.012 * math.sin(0.13 * t + asset)
            volume = 4200.0 + 130.0 * asset + volume_noise.uniform(-850.0, 850.0)
            vwap = base + 0.0004 * t + vwap_noise.uniform(-0.36, 0.36)
            sector = 0.0 if asset < 4 else 1.0
            if asset == 0 and t >= 205:
                sector = 9.0
            row_values["open"].append(open_)
            row_values["high"].append(high)
            row_values["low"].append(low)
            row_values["close"].append(close)
            row_values["volume"].append(volume)
            row_values["vwap"].append(vwap)
            row_values["dollar_volume"].append(vwap * volume)
            row_values["cap"].append(1_000_000.0 * (asset + 1) + 230.0 * t * (asset + 2))
            row_values["sector"].append(sector)
            row_values["industry"].append(float((0, 0, 0, 1, 2, 2)[asset]))
            row_values["subindustry"].append(float((0, 1, 1, 2, 3, 4)[asset]))
        for name in _FIELDS:
            per_field[name].append(row_values[name])
    return per_field


def _rewrite_first(node, predicate, replacement):
    """Return (tree, changed-node) after the first preorder AST rewrite."""

    if predicate(node):
        return replacement(node), node
    kind = node[0]
    if kind == "unary":
        child, changed = _rewrite_first(node[2], predicate, replacement)
        return ((kind, node[1], child), changed) if changed is not None else (node, None)
    if kind == "binary":
        left, changed = _rewrite_first(node[2], predicate, replacement)
        if changed is not None:
            return (kind, node[1], left, node[3]), changed
        right, changed = _rewrite_first(node[3], predicate, replacement)
        return ((kind, node[1], node[2], right), changed) if changed is not None else (node, None)
    if kind == "ternary":
        for index in (1, 2, 3):
            child, changed = _rewrite_first(node[index], predicate, replacement)
            if changed is not None:
                values = list(node)
                values[index] = child
                return tuple(values), changed
        return node, None
    if kind == "call":
        for index, argument in enumerate(node[2]):
            child, changed = _rewrite_first(argument, predicate, replacement)
            if changed is not None:
                arguments = list(node[2])
                arguments[index] = child
                return (kind, node[1], tuple(arguments)), changed
    return node, None


def _is_numeric(node):
    return node[0] == "number"


def _window_mutant(tree):
    def eligible(node):
        if node[0] != "call":
            return False
        name, args = node[1], node[2]
        if name in _OFFSET_CALLS:
            return len(args) == 2 and _is_numeric(args[1])
        if name in _WINDOW_CALLS:
            return bool(args) and _is_numeric(args[-1])
        if name in ("min", "max"):
            return len(args) == 2 and _is_numeric(args[1])
        return False

    def mutate(node):
        name, args = node[1], list(node[2])
        position = 1 if name in _OFFSET_CALLS else len(args) - 1
        old = float(args[position][1])
        new = float(math.ceil(old)) if old != math.floor(old) else old + 1.0
        args[position] = ("number", new)
        return ("call", name, tuple(args))

    changed_tree, original = _rewrite_first(tree, eligible, mutate)
    if original is None:
        return None
    old = float(original[2][1 if original[1] in _OFFSET_CALLS else -1][1])
    rounded = "ceil" if old != math.floor(old) else "plus-one"
    return changed_tree, "first-window-%s:%s" % (rounded, original[1])


def _pit_mutant(tree, source_level, target_level):
    target_name = "indclass." + source_level

    def eligible(node):
        return node[0] == "name" and node[1] == target_name

    changed_tree, original = _rewrite_first(
        tree, eligible, lambda _node: ("name", "indclass." + target_level)
    )
    if original is None:
        return None
    return changed_tree, "IndNeutralize-level:%s->%s" % (source_level, target_level)


def _rank_mutant(tree):
    def rank_to_ts(node):
        return node[0] == "call" and node[1] == "rank"

    changed_tree, original = _rewrite_first(
        tree,
        rank_to_ts,
        lambda node: ("call", "ts_rank", (node[2][0], ("number", 3.0))),
    )
    if original is not None:
        return changed_tree, "cross-sectional-rank->ts_rank(3)"

    def ts_to_rank(node):
        return node[0] == "call" and node[1] == "ts_rank"

    changed_tree, original = _rewrite_first(
        tree, ts_to_rank, lambda node: ("call", "rank", (node[2][0],))
    )
    if original is not None:
        return changed_tree, "ts_rank->cross-sectional-rank"
    return None


def _power_mutant(tree):
    def signed_call(node):
        return node[0] == "call" and node[1] == "signedpower" and len(node[2]) == 2

    changed_tree, original = _rewrite_first(
        tree,
        signed_call,
        lambda node: ("binary", "^", node[2][0], node[2][1]),
    )
    if original is not None:
        return changed_tree, "SignedPower->ordinary-power"

    def power(node):
        return node[0] == "binary" and node[1] == "^"

    def bump_exponent(node):
        exponent = node[3]
        if exponent[0] == "number":
            exponent = ("number", float(exponent[1]) + 1.0)
        else:
            exponent = ("binary", "+", exponent, ("number", 1.0))
        return ("binary", "^", node[2], exponent)

    changed_tree, original = _rewrite_first(tree, power, bump_exponent)
    if original is not None:
        return changed_tree, "first-power-exponent-plus-one"
    return None


def _comparison_mutant(tree):
    replacement = {"<": ">=", "<=": ">", ">": "<=", ">=": "<", "==": "<"}

    def eligible(node):
        return node[0] == "binary" and node[1] in _COMPARISONS

    changed_tree, original = _rewrite_first(
        tree,
        eligible,
        lambda node: ("binary", replacement[node[1]], node[2], node[3]),
    )
    if original is None:
        return None
    return changed_tree, "first-condition-comparator:%s->%s" % (
        original[1],
        replacement[original[1]],
    )


def _corr_cov_mutant(tree):
    alternatives = {"correlation": "covariance", "covariance": "correlation"}

    def eligible(node):
        return node[0] == "call" and node[1] in alternatives

    changed_tree, original = _rewrite_first(
        tree,
        eligible,
        lambda node: ("call", alternatives[node[1]], node[2]),
    )
    if original is None:
        return None
    return changed_tree, "%s->%s" % (original[1], alternatives[original[1]])


def _parenthesis_mutant_101(tree):
    # Appendix A formula 101 is (close-open)/((high-low)+.001).  The targeted
    # common grouping error moves .001 outside the denominator.
    if tree[0] != "binary" or tree[1] != "/":
        return None
    denominator = tree[3]
    if denominator[0] != "binary" or denominator[1] != "+":
        return None
    epsilon = denominator[3]
    return (
        ("binary", "+", ("binary", "/", tree[2], denominator[2]), epsilon),
        "denominator-epsilon-parentheses",
    )


def _candidate_mutants(alpha_id, tree):
    if alpha_id in _PIT_MUTATIONS:
        pit = _pit_mutant(tree, *_PIT_MUTATIONS[alpha_id])
        if pit is not None:
            yield pit
    if alpha_id == 101:
        parenthesis = _parenthesis_mutant_101(tree)
        if parenthesis is not None:
            yield parenthesis
    # Pin direct witnesses for correlation/covariance on IDs 6 and 13 instead
    # of representing those formulas only by a generic window mutant.  ID84
    # tries SignedPower versus ordinary Power first; its positive Ts_Rank base
    # makes them observationally equivalent on this fixture, so its recorded
    # witness falls back to the first fractional-window floor mutation.
    if alpha_id in (6, 13):
        corr_cov = _corr_cov_mutant(tree)
        if corr_cov is not None:
            yield corr_cov
    if alpha_id == 84:
        power = _power_mutant(tree)
        if power is not None:
            yield power
    mutant = _window_mutant(tree)
    if mutant is not None:
        yield mutant
    mutant = _comparison_mutant(tree)
    if mutant is not None:
        yield mutant
    mutant = _rank_mutant(tree)
    if mutant is not None:
        yield mutant
    mutant = _corr_cov_mutant(tree)
    if mutant is not None:
        yield mutant
    mutant = _power_mutant(tree)
    if mutant is not None:
        yield mutant


def _find_finite_witness(expected, mutant, history):
    for time_index in range(history, len(expected)):
        for asset_index, (wanted, wrong) in enumerate(
            zip(expected[time_index], mutant[time_index])
        ):
            if not (math.isfinite(wanted) and math.isfinite(wrong)):
                continue
            if abs(wrong - wanted) > _TOL_ATOL + _TOL_RTOL * abs(wanted):
                return time_index, asset_index
    return None


def _discover_witnesses(frames=None):
    """Compute the deterministic audit record for test authoring/review."""

    matrices = _positive_fixture() if frames is None else frames
    universe = [[True] * _ASSETS for _ in range(_ROWS)]
    groups = ["market"] * _ASSETS
    records = {}
    for alpha_id in oracle.formula_ids():
        tree = oracle._parse(alpha_id)
        context = oracle._Context(matrices, universe, groups)
        expected = context.evaluate(tree)
        history = oracle.history_h(alpha_id, matrices)
        selected = None
        for wrong_tree, mutation_name in _candidate_mutants(alpha_id, tree):
            # Both evaluations share only this invocation's immutable input
            # context.  The oracle's AST memo keys include the whole node, so
            # unchanged subexpressions are reused while the targeted mutant is
            # always recalculated; no result survives to another formula.
            wrong = context.evaluate(wrong_tree)
            coordinate = _find_finite_witness(expected, wrong, history)
            if coordinate is not None:
                selected = (mutation_name, coordinate)
                break
        if selected is None:
            raise AssertionError(
                "Alpha%d has no targeted finite differing coordinate after H=%d"
                % (alpha_id, history)
            )
        mutation_name, coordinate = selected
        records[alpha_id] = (mutation_name, coordinate[0], coordinate[1])
    return records


# Filled with the frozen results of _discover_witnesses().  Each row is
# (targeted mutation, zero-based time row, zero-based asset column); expected
# and mutant values are recomputed by the test and checked with the same strict
# tolerance used by the later per-cell production/oracle comparison.
_WITNESS_RECORDS = {
    1: ("first-window-plus-one:ts_argmax", 24, 0),
    2: ("first-window-plus-one:correlation", 8, 0),
    3: ("first-window-plus-one:correlation", 10, 0),
    4: ("first-window-plus-one:ts_rank", 9, 0),
    5: ("first-window-plus-one:sum", 13, 3),
    6: ("correlation->covariance", 9, 0),
    7: ("first-condition-comparator:<->>=", 66, 0),
    8: ("first-window-plus-one:sum", 17, 4),
    9: ("first-window-plus-one:ts_min", 206, 0),
    10: ("first-window-plus-one:ts_min", 7, 0),
    11: ("first-window-plus-one:ts_max", 3, 1),
    12: ("first-window-plus-one:delta", 2, 4),
    13: ("covariance->correlation", 4, 1),
    14: ("first-window-plus-one:delta", 9, 0),
    15: ("first-window-plus-one:sum", 5, 0),
    16: ("first-window-plus-one:covariance", 5, 0),
    17: ("first-window-plus-one:ts_rank", 23, 2),
    18: ("first-window-plus-one:stddev", 12, 2),
    19: ("first-window-plus-one:delay", 250, 1),
    20: ("first-window-plus-one:delay", 2, 0),
    21: ("first-condition-comparator:<->>=", 20, 1),
    22: ("first-window-plus-one:delta", 19, 0),
    23: ("first-window-plus-one:sum", 20, 0),
    24: ("first-condition-comparator:<->>=", 199, 0),
    25: ("cross-sectional-rank->ts_rank(3)", 21, 0),
    26: ("first-window-plus-one:ts_max", 11, 3),
    27: ("first-window-plus-one:sum", 14, 2),
    28: ("first-window-plus-one:correlation", 24, 0),
    29: ("first-window-plus-one:min", 11, 5),
    30: ("first-window-plus-one:delay", 19, 1),
    31: ("first-window-plus-one:decay_linear", 32, 0),
    32: ("first-window-plus-one:sum", 234, 0),
    33: ("cross-sectional-rank->ts_rank(3)", 2, 0),
    34: ("first-window-plus-one:stddev", 5, 1),
    35: ("first-window-plus-one:ts_rank", 32, 0),
    36: ("first-window-plus-one:correlation", 199, 2),
    37: ("first-window-plus-one:correlation", 210, 0),
    38: ("first-window-plus-one:ts_rank", 11, 2),
    39: ("first-window-plus-one:delta", 250, 1),
    40: ("first-window-plus-one:stddev", 10, 0),
    41: ("first-power-exponent-plus-one", 0, 0),
    42: ("cross-sectional-rank->ts_rank(3)", 2, 2),
    43: ("first-window-plus-one:ts_rank", 39, 0),
    44: ("first-window-plus-one:correlation", 5, 0),
    45: ("first-window-plus-one:sum", 29, 1),
    46: ("first-condition-comparator:<->>=", 20, 0),
    47: ("first-window-plus-one:sum", 19, 0),
    48: ("IndNeutralize-level:subindustry->industry", 251, 0),
    49: ("first-window-plus-one:delay", 30, 5),
    50: ("first-window-plus-one:ts_max", 9, 1),
    51: ("first-window-plus-one:delay", 22, 5),
    52: ("first-window-plus-one:ts_min", 242, 1),
    53: ("first-window-plus-one:delta", 10, 0),
    54: ("first-power-exponent-plus-one", 0, 0),
    55: ("first-window-plus-one:correlation", 17, 0),
    56: ("first-window-plus-one:sum", 11, 1),
    57: ("first-window-plus-one:decay_linear", 31, 0),
    58: ("IndNeutralize-level:sector->industry", 12, 0),
    59: ("IndNeutralize-level:industry->subindustry", 25, 1),
    60: ("first-window-plus-one:ts_argmax", 10, 0),
    61: ("first-window-ceil:ts_min", 203, 5),
    62: ("first-window-ceil:correlation", 50, 4),
    63: ("IndNeutralize-level:industry->subindustry", 238, 0),
    64: ("first-window-ceil:correlation", 148, 5),
    65: ("first-window-ceil:correlation", 73, 1),
    66: ("first-window-ceil:decay_linear", 15, 3),
    67: ("IndNeutralize-level:sector->industry", 25, 1),
    68: ("first-window-ceil:ts_rank", 230, 2),
    69: ("IndNeutralize-level:industry->sector", 30, 0),
    70: ("IndNeutralize-level:industry->sector", 81, 0),
    71: ("first-window-ceil:ts_rank", 225, 0),
    72: ("first-window-ceil:decay_linear", 56, 1),
    73: ("first-window-ceil:decay_linear", 20, 3),
    74: ("first-window-ceil:correlation", 80, 4),
    75: ("first-window-ceil:correlation", 78, 1),
    76: ("IndNeutralize-level:sector->subindustry", 139, 2),
    77: ("first-window-ceil:decay_linear", 45, 2),
    78: ("first-window-ceil:correlation", 63, 0),
    79: ("IndNeutralize-level:sector->industry", 174, 3),
    80: ("IndNeutralize-level:industry->sector", 17, 1),
    81: ("first-window-ceil:product", 79, 2),
    82: ("IndNeutralize-level:sector->subindustry", 35, 2),
    83: ("first-window-plus-one:delay", 7, 0),
    84: ("first-window-ceil:ts_rank", 34, 1),
    85: ("first-window-ceil:correlation", 39, 1),
    86: ("first-window-ceil:ts_rank", 99, 4),
    87: ("IndNeutralize-level:industry->sector", 108, 1),
    88: ("first-window-ceil:decay_linear", 93, 0),
    89: ("IndNeutralize-level:industry->sector", 26, 0),
    90: ("IndNeutralize-level:subindustry->industry", 45, 2),
    91: ("IndNeutralize-level:industry->subindustry", 37, 1),
    92: ("first-window-ceil:ts_rank", 61, 0),
    93: ("IndNeutralize-level:industry->subindustry", 120, 1),
    94: ("first-window-ceil:ts_min", 92, 3),
    95: ("first-window-ceil:ts_min", 81, 3),
    96: ("first-window-ceil:ts_rank", 108, 2),
    97: ("IndNeutralize-level:industry->sector", 114, 3),
    98: ("first-window-ceil:decay_linear", 53, 4),
    99: ("first-window-ceil:correlation", 86, 4),
    100: ("first-window-plus-one:correlation", 145, 1),
    101: ("denominator-epsilon-parentheses", 0, 0),
}


@pytest.fixture(scope="module")
def _fixture_frames():
    return _positive_fixture()


