"""Regression suite for Iteration 71 Research / Factor / Alpha101 items.

Covers:
- R71-111: Exact binary64 zero verification policy and dense-candidate performance
  for ``RollingCovariance`` and ``RollingCorrelation`` (including Alpha015 ties).
- R71-114: Fail-closed flat O(V) topology fast validation in ``FactorStrategy``.
- R71-116: Alpha101 duplicate-node reuse (including Alpha036), multi-group
  dual-mode parity, and the ``Multiply(x, 1.0)`` catalog AST / trace contract.
"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
import math
import random
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

import backtrader as bt
from backtrader.lineiterator import LineIterator
from backtrader.research import (
    FactorIndicator,
    FactorSink,
    FactorSpec,
    ResearchSpec,
    align_to_grid,
    operators,
)
from backtrader.research.alpha101.alpha015 import Alpha015Native
from backtrader.research.alpha101.alpha056 import Alpha056Native
from backtrader.research.operators import (
    CrossSectionalRank,
    OperatorReason,
    RollingCorrelation,
    RollingCovariance,
    Subtract,
    _correlation_window_result,
    _exact_binary_covariance_is_zero,
)
from backtrader.strategies.factor_strategy import FactorStrategy
from tests.test_utils.alpha101_native_harness import make_positive_fixture, run_native_batch
from tests.test_utils.alpha101_trace_validation import (
    _FIELD_NAME,
    _RETURNS_NODE,
    _field_lines,
    _fold_constants,
    _logical_view_for_owner,
    _operator_expression,
    _validated_pair_panel_views,
    compare_factor_graphs,
    validate_factor_trace,
)


# ---------------------------------------------------------------------------
# R71-111: Exact binary64 zero verification & Alpha015 tie preservation
# ---------------------------------------------------------------------------


def _fraction_covariance_is_zero(left, right) -> bool:
    xs = [Fraction.from_float(float(v)) for v in left]
    ys = [Fraction.from_float(float(v)) for v in right]
    n = len(xs)
    return n * sum((x * y for x, y in zip(xs, ys)), Fraction(0)) == sum(xs, Fraction(0)) * sum(
        ys, Fraction(0)
    )


def test_r71_111_exact_binary_covariance_is_zero_matches_fraction_oracle():
    eps = sys.float_info.epsilon
    subnormal = math.nextafter(0.0, 1.0)
    exact_zero_3 = (
        [2.6666666666666665, 0.3333333333333333, 0.0],
        [1.6666666666666667, 0.6666666666666666, 2.3333333333333335],
    )
    adversarial = [
        ([1.0], [2.0]),
        ([1.0, 1.0], [2.0, 3.0]),
        ([1.0, 2.0], [3.0, 4.0]),
        exact_zero_3,
        (
            [0.0, 3.3333333333333335, 1.3333333333333333],
            [3.3333333333333335, 3.0, 0.6666666666666666],
        ),
        (
            [math.ldexp(v, 400) for v in exact_zero_3[0]],
            [math.ldexp(v, -400) for v in exact_zero_3[1]],
        ),
        (
            [math.ldexp(v, -400) for v in exact_zero_3[0]],
            [math.ldexp(v, 400) for v in exact_zero_3[1]],
        ),
        ([-1.0, 0.0, 1.0], [1.0, -2.0, 1.0 + eps]),
        ([-1.0, 0.0, 1.0], [1.0, -2.0, 1.0 - eps]),
        (
            [math.ldexp(v, 400) for v in (-1.0, 0.0, 1.0)],
            [math.ldexp(v, -400) for v in (1.0, -2.0, 1.0 + eps)],
        ),
        ([subnormal, 2.0 * subnormal, 3.0 * subnormal], [1.0, 0.0, 1.0]),
        ([subnormal, 2.0 * subnormal, 3.0 * subnormal], [1.0, 0.0, 1.0 + eps]),
        ([1e200, 0.0, -1e200], [1e-200, 2e-200, 1e-200]),
        ([1e308, -1e308, 0.0], [1e-308, 1e-308, -2e-308]),
        ([-0.0, 0.0, -0.0], [1.0, 2.0, 3.0]),
        (exact_zero_3[0] * 4, exact_zero_3[1] * 4),
    ]
    rng = random.Random(20261121)
    for _ in range(400):
        n = rng.choice((2, 3, 4, 5, 10))
        adversarial.append(
            (
                [rng.uniform(-50.0, 50.0) for _ in range(n)],
                [rng.uniform(-50.0, 50.0) for _ in range(n)],
            )
        )

    for left, right in adversarial:
        assert _exact_binary_covariance_is_zero(left, right) is _fraction_covariance_is_zero(
            left, right
        ), (left, right)


def test_r71_111_alpha015_exact_zero_correlations_restore_half_tie_ranks():
    # Five-asset Alpha015 fixture where high ranks on assets 0 and 1 form exact
    # binary64 midpoints ([0.4, 0.5, 0.6] and [0.6, 0.5, 0.4]) against symmetric
    # volume ranks ([0.2, 1.0, 0.2] and [1.0, 0.2, 1.0]), yielding exact binary64
    # zero correlation for both assets. With 1 negative and 2 positive peers,
    # their tied rank(correlation) must be strictly 0.5 (never split to 0.4/0.6).
    high_rows = [
        (2.0, 3.0, 1.0, 4.0, 5.0),  # ranks: (0.4, 0.6, 0.2, 0.8, 1.0)
        (2.0, 2.0, 1.0, 5.0, 4.0),  # ranks: (0.5, 0.5, 0.2, 1.0, 0.8)
        (3.0, 2.0, 4.0, 1.0, 5.0),  # ranks: (0.6, 0.4, 0.8, 0.2, 1.0)
        (2.0, 3.0, 1.0, 4.0, 5.0),
        (2.0, 2.0, 1.0, 5.0, 4.0),
    ]
    volume_rows = [
        (1.0, 5.0, 4.0, 2.0, 3.0),  # ranks: (0.2, 1.0, 0.8, 0.4, 0.6)
        (5.0, 1.0, 3.0, 4.0, 2.0),  # ranks: (1.0, 0.2, 0.6, 0.8, 0.4)
        (1.0, 5.0, 2.0, 3.0, 4.0),  # ranks: (0.2, 1.0, 0.4, 0.6, 0.8)
        (1.0, 5.0, 4.0, 2.0, 3.0),
        (5.0, 1.0, 3.0, 4.0, 2.0),
    ]

    # Verify exact binary64 zero covariance on assets 0 and 1 before running Cerebro.
    assert _fraction_covariance_is_zero([0.4, 0.5, 0.6], [0.2, 1.0, 0.2])
    assert _fraction_covariance_is_zero([0.6, 0.5, 0.4], [1.0, 0.2, 1.0])

    index = pd.date_range("2025-04-01 16:00", periods=5, tz="UTC", name="close_time")
    frames = {
        f"a{asset}": pd.DataFrame(
            {
                "open": [high_rows[bar][asset] for bar in range(5)],
                "high": [high_rows[bar][asset] for bar in range(5)],
                "low": [high_rows[bar][asset] for bar in range(5)],
                "close": [high_rows[bar][asset] for bar in range(5)],
                "volume": [volume_rows[bar][asset] for bar in range(5)],
            },
            index=index,
        )
        for asset in range(5)
    }

    results = {}
    for runonce in (False, True):
        research = ResearchSpec(
            grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index),
            start=index[0],
            end=index[-1],
            targets=tuple(frames),
            groups=dict.fromkeys(frames, "g0"),
            source_timezone="UTC",
            snapshot_id="r71-111-alpha015-tie",
            price_basis="test",
            calendar_id="test",
            frequency="1day",
        )
        cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
        for name, frame in frames.items():
            cerebro.adddata(align_to_grid(frame, research, name).feed, name=name)
        cerebro.addstrategy(
            FactorStrategy,
            research=research,
            factors={
                "alpha15": FactorSpec(
                    name="alpha15",
                    indicator=Alpha015Native,
                    panel_line="factor",
                    field_bindings={
                        "high": "feed:target:high",
                        "volume": "feed:target:volume",
                    },
                    mode="native",
                )
            },
        )
        strategy = cerebro.run(runonce=runonce)[0]
        factor = strategy.factor_instances["alpha15"]
        # Bar index 2 is the first complete 3-bar correlation window.
        corrs_bar2 = tuple(
            float(factor._nodes[f"rank_correlation3_{asset}"].lines.value.array[2])
            for asset in range(5)
        )
        rank_node = factor._nodes["rank_correlation"]
        ranks_bar2 = tuple(
            float(rank_node.outputs[data].value.array[2]) for data in factor.datas
        )
        assert corrs_bar2[0] == 0.0
        assert corrs_bar2[1] == 0.0
        assert corrs_bar2[2] < 0.0
        assert corrs_bar2[3] > 0.0
        assert corrs_bar2[4] > 0.0
        # Exact tie at sorted positions 2 & 3 out of 5 -> strictly 0.5, 0.5 (never 0.4/0.6).
        assert ranks_bar2[0] == 0.5
        assert ranks_bar2[1] == 0.5
        results[runonce] = strategy.get_panel().factors

    pd.testing.assert_frame_equal(results[False], results[True], check_exact=True)


def test_r71_111_covariance_and_correlation_full_series_runonce_runnext_parity():
    eps = sys.float_info.epsilon
    exact_zero = (
        [2.6666666666666665, 0.3333333333333333, 0.0],
        [1.6666666666666667, 0.6666666666666666, 2.3333333333333335],
    )
    n_bars = 24
    index = pd.date_range("2025-05-01", periods=n_bars, freq="D")

    def _df(left, right):
        return pd.DataFrame(
            {
                "open": right,
                "high": left,
                "low": left,
                "close": left,
                "volume": [1.0] * n_bars,
                "openinterest": [0.0] * n_bars,
            },
            index=index,
        )

    feeds_data = [
        (
            "exact_zero",
            _df(
                [exact_zero[0][i % 3] for i in range(n_bars)],
                [exact_zero[1][i % 3] for i in range(n_bars)],
            ),
        ),
        (
            "scaled_zero",
            _df(
                [math.ldexp(exact_zero[0][i % 3], 400) for i in range(n_bars)],
                [math.ldexp(exact_zero[1][i % 3], -400) for i in range(n_bars)],
            ),
        ),
        (
            "tiny_pos",
            _df(
                [(-1.0, 0.0, 1.0)[i % 3] for i in range(n_bars)],
                [(1.0, -2.0, 1.0 + 4.0 * eps)[i % 3] for i in range(n_bars)],
            ),
        ),
        (
            "tiny_neg",
            _df(
                [(-1.0, 0.0, 1.0)[i % 3] for i in range(n_bars)],
                [(1.0, -2.0, 1.0 - 4.0 * eps)[i % 3] for i in range(n_bars)],
            ),
        ),
        (
            "constant",
            _df([5.0] * n_bars, [float(i) for i in range(n_bars)]),
        ),
        (
            "normal",
            _df(
                [10.0 + math.sin(i * 0.4) for i in range(n_bars)],
                [20.0 + math.cos(i * 0.3) for i in range(n_bars)],
            ),
        ),
    ]

    class PairParityProbe(bt.Strategy):
        def __init__(self):
            self.covs = tuple(RollingCovariance(d.close, d.open, period=3) for d in self.datas)
            self.corrs = tuple(RollingCorrelation(d.close, d.open, period=3) for d in self.datas)
            self.history = []

        def _record(self):
            self.history.append(
                (
                    tuple((n.value[0], int(n.reason[0])) for n in self.covs),
                    tuple((n.value[0], int(n.reason[0])) for n in self.corrs),
                )
            )

        prenext = _record
        nextstart = _record
        next = _record

    runs = {}
    for runonce in (False, True):
        cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
        for name, df in feeds_data:
            cerebro.adddata(bt.feeds.PandasData(dataname=df), name=name)
        cerebro.addstrategy(PairParityProbe)
        runs[runonce] = cerebro.run(runonce=runonce)[0].history

    assert len(runs[False]) == len(runs[True]) == n_bars
    for bar, (row_next, row_once) in enumerate(zip(runs[False], runs[True])):
        for op_idx in (0, 1):
            for feed_idx, ((v_next, r_next), (v_once, r_once)) in enumerate(
                zip(row_next[op_idx], row_once[op_idx])
            ):
                assert r_next == r_once, (bar, op_idx, feed_idx)
                if math.isnan(v_next):
                    assert math.isnan(v_once), (bar, op_idx, feed_idx)
                else:
                    assert v_next == v_once, (bar, op_idx, feed_idx, v_next, v_once)

        # From bar 2 onward, verify exact zero snap vs preserved tiny nonzero signs.
        if bar >= 2:
            cov_row, corr_row = row_once
            assert cov_row[0] == (0.0, OperatorReason.READY)
            assert cov_row[1] == (0.0, OperatorReason.READY)
            assert corr_row[0] == (0.0, OperatorReason.READY)
            assert corr_row[1] == (0.0, OperatorReason.READY)
            assert cov_row[2][0] > 0.0 and corr_row[2][0] > 0.0
            assert cov_row[3][0] < 0.0 and corr_row[3][0] < 0.0
            assert cov_row[4] == (0.0, OperatorReason.READY)
            assert math.isnan(corr_row[4][0]) and corr_row[4][1] == OperatorReason.DOMAIN_ERROR


def test_r71_111_near_zero_policy_documented():
    for obj in (
        _exact_binary_covariance_is_zero,
        RollingCovariance,
        _correlation_window_result,
        RollingCorrelation,
    ):
        doc = obj.__doc__ or ""
        assert "binary64" in doc
        assert "zero" in doc.lower()


# ---------------------------------------------------------------------------
# R71-114: Fail-closed flat O(V) topology fast validation in FactorStrategy
# ---------------------------------------------------------------------------


class _LeafFactor(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.close_line = self.field_lines("close")[0]

    def next(self):
        self.outputs[self.target_datas[0]].factor[0] = self.close_line[0]


class _CompositeFactor(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.left = _LeafFactor.bind(*self.target_datas)
        self.right = _LeafFactor.bind(*self.target_datas)

    def next(self):
        data = self.target_datas[0]
        self.outputs[data].factor[0] = (
            self.left.outputs[data].factor[0] + self.right.outputs[data].factor[0]
        )


class _ProbeSink(FactorSink):
    def __init__(self):
        self.points = []
        self.finalized = False
        self.closed = False

    def on_point(self, *args):
        self.points.append(args)

    def finalize(self, context):
        self.finalized = True
        return {"count": len(self.points)}

    def close(self):
        self.closed = True


def _build_r71_114_cerebro(
    *,
    runonce: bool,
    strategy_cls: type = FactorStrategy,
    sink: FactorSink | None = None,
    stdstats: bool = False,
    periods: int = 8,
):
    index = pd.date_range("2025-06-01 16:00", periods=periods, tz="UTC", name="close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("A",),
        groups={"A": "x"},
        source_timezone="UTC",
        snapshot_id="r71-114-validation",
        price_basis="test",
        calendar_id="test",
        frequency="1day",
    )
    values = [10.0 + i for i in range(periods)]
    frame = pd.DataFrame(
        dict.fromkeys(("open", "high", "low", "close", "volume"), values),
        index=index,
    )
    cerebro = bt.Cerebro(stdstats=stdstats, runonce=runonce)
    cerebro.adddata(align_to_grid(frame, research, "A").feed, name="A")
    cerebro.addstrategy(
        strategy_cls,
        research=research,
        factors={
            "f": FactorSpec(
                name="f",
                indicator=_CompositeFactor,
                panel_line="factor",
                field_bindings={"close": "feed:target:close"},
                mode="native",
            )
        },
        sink=sink,
    )
    return cerebro


@pytest.mark.parametrize("stdstats", [False, True], ids=["no_stdstats", "with_stdstats"])
@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_r71_114_steady_run_uses_full_validation_per_bar(monkeypatch, runonce, stdstats):
    counts = {"full": 0, "fast_hit": 0, "fast_miss": 0}
    orig_full = FactorStrategy._validate_research_ownership
    orig_fast = FactorStrategy._check_factor_validation_fast_plan

    def tracked_full(self):
        counts["full"] += 1
        return orig_full(self)

    def tracked_fast(self, plan):
        ok = orig_fast(self, plan)
        counts["fast_hit" if ok else "fast_miss"] += 1
        return ok

    monkeypatch.setattr(FactorStrategy, "_validate_research_ownership", tracked_full)
    monkeypatch.setattr(FactorStrategy, "_check_factor_validation_fast_plan", tracked_fast)

    periods = 10
    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, sink=sink, stdstats=stdstats, periods=periods
    )
    (strategy,) = cerebro.run(runonce=runonce)

    assert len(sink.points) == periods
    assert sink.finalized and sink.closed
    assert strategy._factor_validation_fast_plan is None
    # The full validator runs post-start, on each bar, and at stop().
    assert counts["full"] == periods + 2
    assert counts["fast_hit"] == 0
    assert counts["fast_miss"] == 0


def test_r71_114_full_validation_exception_clears_scratch_and_releases_lock(monkeypatch):
    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(runonce=False, sink=sink, periods=3)
    (strategy,) = cerebro.run(runonce=False)

    strategy._factor_validation_child_counts[1] = 1
    strategy._factor_validation_host_counts[2] = 1
    strategy._factor_validation_observed[3] = 1
    strategy._factor_validation_visited.add(4)
    strategy._factor_validation_pending.append(object())
    root = strategy._factor_instances_by_name["f"][0]
    monkeypatch.setitem(strategy._factor_validation_graphs, id(root), ((), ()))
    with pytest.raises(RuntimeError, match="factor graph changed"):
        strategy._validate_research_ownership()
    assert not strategy._factor_validation_child_counts
    assert not strategy._factor_validation_host_counts
    assert not strategy._factor_validation_observed
    assert not strategy._factor_validation_visited
    assert not strategy._factor_validation_pending
    assert strategy._factor_validation_lock.acquire(blocking=False)
    strategy._factor_validation_lock.release()


@pytest.mark.parametrize("runonce", [False, True])
def test_r71_114_full_validation_preserves_lazy_strategy_iteration(runonce):
    observations = []

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor != 1:
                return super()._collect_grid_point()
            cerebro = self.cerebro
            root = self._factor_instances_by_name["f"][0]
            original = cerebro.runningstrats
            rogue = SimpleNamespace(_lineiterators={LineIterator.IndType: [root]})

            class Strategies:
                def __iter__(self):
                    yield rogue
                    observations.append("advanced past rogue")
                    raise ValueError("later iterator failure")

            cerebro.runningstrats = Strategies()
            try:
                return super()._collect_grid_point()
            finally:
                cerebro.runningstrats = original

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    with pytest.raises(RuntimeError, match="multiple scheduling paths"):
        cerebro.run(runonce=runonce)
    assert observations == []
    assert len(sink.points) == 1
    assert sink.closed and not sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
def test_r71_114_full_validation_clears_original_scratch_reference(monkeypatch, runonce):
    class ScratchIndicator(bt.Indicator):
        lines = ("value",)

        @property
        def __class__(self):
            state = object.__getattribute__(self, "__dict__")
            if state.get("armed", False):
                strategy = state["strategy"]
                strategy._factor_validation_child_counts[999999] = 42
                strategy._factor_validation_child_counts = {}
            return type(self)

        def next(self):
            self.lines.value[0] = 0.0

    original_init = _CompositeFactor.__init__

    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        node = ScratchIndicator(self.datas[0])
        children = node._owner._lineiterators[node._ltype]
        children.pop(next(i for i, child in enumerate(children) if child is node))
        node._owner = self.left
        self.left._lineiterators[node._ltype].append(node)
        self.scratch_node = node

    monkeypatch.setattr(_CompositeFactor, "__init__", initialize)
    observations = []

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                node = self._factor_instances_by_name["f"][0].scratch_node
                state = object.__getattribute__(node, "__dict__")
                original = self._factor_validation_child_counts
                state.update(strategy=self, armed=True)
                try:
                    self._validate_research_ownership()
                finally:
                    state["armed"] = False
                observations.append((not original, self._factor_validation_child_counts is not original))
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    cerebro.run(runonce=runonce)
    assert observations == [(True, True)]
    assert len(sink.points) == 4
    assert sink.closed and sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
def test_r71_114_default_does_not_call_extracted_full_override(runonce):
    class OverridingStrategy(FactorStrategy):
        def _validate_research_ownership_full(self):
            raise AssertionError("experimental method must not be looked up")

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=OverridingStrategy, sink=sink, periods=4
    )
    cerebro.run(runonce=runonce)
    assert len(sink.points) == 4
    assert sink.closed and sink.finalized


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize(
    "mutation_kind,expected_error",
    [
        ("owner_change", "factor graph changed"),
        ("child_replacement", "factor graph changed"),
        ("extra_edge_on_leaf", "factor graph changed"),
        ("extra_bucket_on_leaf", "factor graph changed"),
        ("defaultdict_key_swap_on_leaf", "factor graph changed"),
        ("node_class_change", "factor graph changed"),
        ("factor_graphs_tamper", "factor graph changed"),
        ("factor_instances_tamper", "missing from its owner graph"),
    ],
)
def test_r71_114_full_validation_rejects_live_mutations_after_first_bar(
    runonce, mutation_kind, expected_error
):
    class _FakeOther(bt.Indicator):
        lines = ("factor",)

    class _MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                assert self._factor_validation_fast_plan is None
                root = self._factor_instances_by_name["f"][0]
                if mutation_kind == "owner_change":
                    root.left._owner = self
                elif mutation_kind == "child_replacement":
                    root._lineiterators[LineIterator.IndType][0] = root.right
                elif mutation_kind == "extra_edge_on_leaf":
                    root.left._lineiterators[LineIterator.IndType].append(root.right)
                elif mutation_kind == "extra_bucket_on_leaf":
                    root.left._lineiterators[99] = [root.right]
                elif mutation_kind == "defaultdict_key_swap_on_leaf":
                    # Replace ObsType bucket (if present) with key 99 on defaultdict.
                    root.left._lineiterators.pop(LineIterator.ObsType, None)
                    root.left._lineiterators[99] = [root.right]
                elif mutation_kind == "node_class_change":
                    root.left.__class__ = _FakeOther
                elif mutation_kind == "factor_graphs_tamper":
                    self._factor_graphs[id(root)] = ((), ())
                elif mutation_kind == "factor_instances_tamper":
                    self._factor_instances_by_name["f"] = ()
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(runonce=runonce, strategy_cls=_MutatingStrategy, sink=sink)
    with pytest.raises(RuntimeError, match=expected_error):
        cerebro.run(runonce=runonce)
    assert len(sink.points) == 1
    assert not sink.finalized
    assert sink.closed


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("hijack_mode", ["sibling_strategy_append", "inject_new_strategy"])
def test_r71_114_full_validation_rejects_late_cross_strategy_hijack(runonce, hijack_mode):
    class _SiblingHijacker(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.datas[0], period=2)
            self.bars = 0

        def _maybe_hijack(self):
            self.bars += 1
            if self.bars == 1:
                first = self.cerebro.runningstrats[0]
                victim = first._factor_instances_by_name["f"][0].left
                if hijack_mode == "sibling_strategy_append":
                    self.sma.getindicators().append(victim)
                else:
                    fake_strat = type(
                        "_InjectedStrat",
                        (),
                        {
                            "_lineiterators": {LineIterator.IndType: [victim]},
                            "_next": lambda self: None,
                            "_oncepost": lambda self, dt: None,
                            "_stop": lambda self: None,
                        },
                    )()
                    self.cerebro.runningstrats.append(fake_strat)

        prenext = _maybe_hijack
        nextstart = _maybe_hijack
        next = _maybe_hijack

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(runonce=runonce, sink=sink)
    cerebro.addstrategy(_SiblingHijacker)
    with pytest.raises(RuntimeError, match="multiple scheduling paths"):
        cerebro.run(runonce=runonce)
    assert len(sink.points) == 1
    assert not sink.finalized
    assert sink.closed


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_r71_114_valid_child_reordering_remains_accepted(monkeypatch, runonce):
    counts = {"full": 0, "fast_hit": 0, "fast_miss": 0}
    orig_full = FactorStrategy._validate_research_ownership
    orig_fast = FactorStrategy._check_factor_validation_fast_plan

    def tracked_full(self):
        counts["full"] += 1
        return orig_full(self)

    def tracked_fast(self, plan):
        ok = orig_fast(self, plan)
        counts["fast_hit" if ok else "fast_miss"] += 1
        return ok

    monkeypatch.setattr(FactorStrategy, "_validate_research_ownership", tracked_full)
    monkeypatch.setattr(FactorStrategy, "_check_factor_validation_fast_plan", tracked_fast)

    class _ReorderAfterFirstBar(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                root = self._factor_instances_by_name["f"][0]
                root._lineiterators[LineIterator.IndType].reverse()
            super()._collect_grid_point()

    periods = 6
    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=_ReorderAfterFirstBar, sink=sink, periods=periods
    )
    cerebro.run(runonce=runonce)

    assert len(sink.points) == periods
    assert sink.finalized and sink.closed
    assert counts["full"] == periods + 2
    assert counts["fast_miss"] == 0
    assert counts["fast_hit"] == 0


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_r71_114_clock_change_does_not_change_ownership_contract(monkeypatch, runonce):
    counts = {"full": 0, "fast_miss": 0}
    orig_full = FactorStrategy._validate_research_ownership
    orig_fast = FactorStrategy._check_factor_validation_fast_plan

    def tracked_full(self):
        counts["full"] += 1
        return orig_full(self)

    def tracked_fast(self, plan):
        ok = orig_fast(self, plan)
        if not ok:
            counts["fast_miss"] += 1
        return ok

    monkeypatch.setattr(FactorStrategy, "_validate_research_ownership", tracked_full)
    monkeypatch.setattr(FactorStrategy, "_check_factor_validation_fast_plan", tracked_fast)

    class _DummyClock:
        def __init__(self, target):
            self._target = target

        def __len__(self):
            return len(self._target)

    class _ClockChangeAfterFirstBar(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                root = self._factor_instances_by_name["f"][0]
                root.left._clock = _DummyClock(root.left._clock)
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=_ClockChangeAfterFirstBar, sink=sink, periods=4
    )
    cerebro.run(runonce=runonce)
    # The ownership validator does not inspect a clock; separate clock
    # contracts retain responsibility for checking it.
    assert counts["fast_miss"] == 0
    assert counts["full"] == 6


# ---------------------------------------------------------------------------
# R71-116: Alpha101 node deduplication, multi-group parity & Multiply(*, 1.0)
# ---------------------------------------------------------------------------


def _duplicate_node_expressions(factor):
    targets = tuple(getattr(factor, "target_datas", ())) or tuple(factor._factor_target_datas)
    aliases = _field_lines(factor)
    physical_views = _validated_pair_panel_views(factor, targets)
    cache = {}

    def line_expr(line, idx):
        key = (id(line), idx)
        if key in cache:
            return cache[key]
        alias = aliases.get(id(line))
        if alias is not None:
            cache[key] = ("name", alias[0])
            return cache[key]
        owner = getattr(getattr(line, "_owner", None), "_owner_ref", None)
        logical = _logical_view_for_owner(owner, idx, physical_views)
        expr = _fold_constants(_operator_expression(logical, idx, line_expr))
        cache[key] = expr
        return expr

    by_expr = defaultdict(list)
    for key, node in factor._nodes.items():
        skey = str(key)
        if _RETURNS_NODE.match(skey):
            expr = ("name", "returns")
            match = _FIELD_NAME.match(skey)
            idx = int(match.group("index")) if match else 0
        elif isinstance(node, operators._PanelOperator):
            expr = _fold_constants(_operator_expression(node, 0, line_expr))
            idx = -1
        else:
            match = _FIELD_NAME.match(skey)
            idx = int(match.group("index"))
            expr = _fold_constants(_operator_expression(node, idx, line_expr))
        by_expr[(idx, expr)].append(skey)
    return {k: v for k, v in by_expr.items() if len(v) > 1}


def _multi_group_missing_fixture():
    frames = {asset: frame.copy() for asset, frame in make_positive_fixture(320).items()}
    grid = tuple(next(iter(frames.values())).index)
    frames["asset-1"] = frames["asset-1"].drop(index=grid[160])
    frames["asset-3"].loc[grid[80], "open"] = math.nan
    frames["asset-4"].loc[grid[-4], "close"] = math.nan
    # Give group_b a shared subindustry so Alpha100's double subindustry
    # neutralization + scale produces finite non-degenerate values in both groups.
    frames["asset-5"]["subindustry"] = frames["asset-4"]["subindustry"]
    assets = tuple(frames)
    groups = {asset: ("group_a" if idx < 3 else "group_b") for idx, asset in enumerate(assets)}
    return frames, grid, groups


def test_r71_116_alpha036_reuses_close_minus_open_across_modes_and_runonce():
    frames, grid, _groups = _multi_group_missing_fixture()
    assets = tuple(frames)
    panels = {}

    for runonce in (False, True):
        by_mode = {}
        for mode in ("native", "build"):
            strategy = run_native_batch(frames, (36,), runonce=runonce, factor_mode=mode)
            factor = strategy.factor_instances["alpha36"]
            by_mode[mode] = factor
            assert _duplicate_node_expressions(factor) == {}
            subtracts = [n for n in factor._nodes.values() if isinstance(n, Subtract)]
            # Alpha036 has 4 distinct Subtract subexpressions per asset:
            # simple_returns diff, (close - open), (open - close), and
            # (mean_close_200 - open) — reduced from 5 before reuse.
            assert len(subtracts) == 4 * len(assets)
            report = validate_factor_trace(
                factor, 36, frames, assets, grid, strategy=strategy
            )
            assert report["failures"] == [], "\n".join(report["failures"])
        pair = compare_factor_graphs(by_mode["native"], by_mode["build"], 36)
        assert pair["equal"], pair["failures"]
        panels[runonce] = strategy.get_panel().factors

    pd.testing.assert_frame_equal(panels[False], panels[True], check_exact=True)


def test_r71_116_reused_and_multiply_one_alphas_multi_group_and_dual_mode_parity():
    frames, grid, groups = _multi_group_missing_fixture()
    reused_ids = (36, 46, 49, 51, 62)
    multiply_one_ids = (56, 57, 60, 100)
    all_ids = reused_ids + multiply_one_ids

    panels_by_runonce = {}
    for runonce in (False, True):
        strategies = {}
        for mode in ("native", "build"):
            strategy = run_native_batch(
                frames, all_ids, runonce=runonce, factor_mode=mode, groups=groups
            )
            strategies[mode] = strategy
            for alpha_id in all_ids:
                grouped = strategy.factor_instances[f"alpha{alpha_id}"]
                assert set(grouped.group_instances) == {"group_a", "group_b"}
                for group_name, factor in grouped.group_instances.items():
                    group_assets = tuple(
                        asset for asset, g in groups.items() if g == group_name
                    )
                    group_frames = {asset: frames[asset] for asset in group_assets}
                    assert _duplicate_node_expressions(factor) == {}, (
                        alpha_id,
                        mode,
                        group_name,
                    )
                    report = validate_factor_trace(
                        factor,
                        alpha_id,
                        group_frames,
                        group_assets,
                        grid,
                        strategy=strategy,
                    )
                    assert report["failures"] == [], (
                        f"Alpha{alpha_id} mode={mode} group={group_name}: "
                        + "\n".join(report["failures"])
                    )
        for alpha_id in all_ids:
            left_grouped = strategies["native"].factor_instances[f"alpha{alpha_id}"]
            right_grouped = strategies["build"].factor_instances[f"alpha{alpha_id}"]
            for group_name in ("group_a", "group_b"):
                pair = compare_factor_graphs(
                    left_grouped.group_instances[group_name],
                    right_grouped.group_instances[group_name],
                    alpha_id,
                )
                assert pair["equal"], (alpha_id, group_name, pair["failures"])
        panels_by_runonce[runonce] = strategies["native"].get_panel().factors

    pd.testing.assert_frame_equal(
        panels_by_runonce[False], panels_by_runonce[True], check_exact=True
    )


def test_r71_116_multiply_one_is_required_by_catalog_ast_trace_contract():
    frames = make_positive_fixture(320)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)

    # Confirm all four Appendix A `(0 - (1 * ...))` alphas retain Multiply(..., 1.0)
    # and pass strict AST trace validation.
    multiply_one_ids = (56, 57, 60, 100)
    strategy = run_native_batch(frames, multiply_one_ids, runonce=True, factor_mode="native")
    for alpha_id in multiply_one_ids:
        factor = strategy.factor_instances[f"alpha{alpha_id}"]
        mul_one_nodes = [
            node
            for node in factor._nodes.values()
            if isinstance(node, operators.Multiply)
            and any(
                not isinstance(arg, bool) and isinstance(arg, (int, float)) and float(arg) == 1.0
                for arg in node._operand_args
            )
        ]
        assert len(mul_one_nodes) == len(assets), f"Alpha{alpha_id} must retain * 1.0 node"
        report = validate_factor_trace(factor, alpha_id, frames, assets, grid, strategy=strategy)
        assert report["failures"] == [], "\n".join(report["failures"])

    # Prove concretely that dropping Multiply(x, 1.0) breaks the catalog AST contract.
    class _Alpha056WithoutMultiplyOne(Alpha056Native):
        def __init__(self):
            FactorIndicator.__init__(self)
            self._nodes = {}
            from backtrader.research._helpers import panel, per_asset, simple_returns

            returns = simple_returns(self, "returns")
            long_sum = per_asset(self, "sum_returns10", operators.RollingSum, returns, period=10)
            inner_sum = per_asset(self, "sum_returns2", operators.RollingSum, returns, period=2)
            nested_sum = per_asset(self, "sum_of_sum3", operators.RollingSum, inner_sum, period=3)
            ratio = per_asset(self, "sum_ratio", operators.Divide, long_sum, nested_sum)
            ranked_ratio = panel(self, "rank_sum_ratio", CrossSectionalRank, ratio)
            return_cap = per_asset(
                self, "return_times_cap", operators.Multiply, returns, self.field_lines("cap")
            )
            ranked_return_cap = panel(self, "rank_return_cap", CrossSectionalRank, return_cap)
            product = per_asset(
                self, "rank_product", operators.Multiply, ranked_ratio, ranked_return_cap
            )
            # Intentionally omit `* 1.0`:
            self._result_lines = per_asset(
                self, "zero_minus", Subtract, (0.0,) * len(self.datas), product
            )
            self.addminperiod(self.lookback_h + 1)

    bad_strategy = run_native_batch(
        frames,
        (56,),
        runonce=True,
        factor_mode="native",
        alpha_classes={56: _Alpha056WithoutMultiplyOne},
    )
    bad_factor = bad_strategy.factor_instances["alpha56"]
    with pytest.raises(AssertionError, match="production graph does not match catalog AST"):
        validate_factor_trace(bad_factor, 56, frames, assets, grid, strategy=bad_strategy)
