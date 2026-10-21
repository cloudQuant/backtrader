"""Known-answer contracts for the native alpha101-v1 research operators."""

import math
from fractions import Fraction

import pandas as pd
import pytest

import backtrader as bt
import backtrader.research.operators as operator_module
from backtrader.linebuffer import LineBuffer
from backtrader.research.operators import (
    Abs,
    Add,
    CrossSectionalRank,
    CrossSectionalScale,
    DecayLinear,
    Delay,
    Delta,
    Divide,
    EqualTo,
    GreaterEqual,
    GreaterThan,
    IndNeutralize,
    LessEqual,
    LessThan,
    Log,
    LogicalAnd,
    LogicalNot,
    LogicalOr,
    Maximum,
    Minimum,
    Multiply,
    Negate,
    NotEqualTo,
    OperatorInputError,
    OperatorReason,
    Power,
    RollingCorrelation,
    RollingCovariance,
    RollingMean,
    RollingProduct,
    RollingStd,
    RollingSum,
    Sign,
    SignedPower,
    Sqrt,
    Subtract,
    TsArgMax,
    TsArgMin,
    TsMax,
    TsMin,
    TsRank,
    Where,
    _read_value,
)

_ALPHA101_OPERATOR_CLASSES = {
    "Abs",
    "Add",
    "CrossSectionalRank",
    "CrossSectionalScale",
    "DecayLinear",
    "Delay",
    "Delta",
    "Divide",
    "EqualTo",
    "IndNeutralize",
    "LessThan",
    "Log",
    "LogicalOr",
    "Maximum",
    "Minimum",
    "Multiply",
    "Negate",
    "Power",
    "RollingCorrelation",
    "RollingCovariance",
    "RollingProduct",
    "RollingStd",
    "RollingSum",
    "Sign",
    "SignedPower",
    "Subtract",
    "TsArgMax",
    "TsArgMin",
    "TsMax",
    "TsMin",
    "TsRank",
    "Where",
}


class _PanelData(bt.feeds.PandasData):
    lines = ("sector", "industry", "subindustry", "member")
    params = (
        ("sector", "sector"),
        ("industry", "industry"),
        ("subindustry", "subindustry"),
        ("member", "member"),
    )


def _frame(closes, *, opens=None, sectors=None, industries=None, subindustries=None, members=None):
    count = len(closes)
    index = pd.date_range("2020-01-01", periods=count, freq="D")
    opens = list(opens if opens is not None else closes)
    sectors = list(sectors if sectors is not None else [1.0] * count)
    industries = list(industries if industries is not None else [1.0] * count)
    subindustries = list(subindustries if subindustries is not None else [1.0] * count)
    members = list(members if members is not None else [1.0] * count)
    return pd.DataFrame(
        {
            "open": opens,
            "high": [value + 1 if math.isfinite(value) else value for value in closes],
            "low": [value - 1 if math.isfinite(value) else value for value in closes],
            "close": list(closes),
            "volume": [100.0] * count,
            "openinterest": [0.0] * count,
            "sector": sectors,
            "industry": industries,
            "subindustry": subindustries,
            "member": members,
        },
        index=index,
    )


def _run(strategy, frames, *, runonce=True):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for name, frame in frames:
        cerebro.adddata(_PanelData(dataname=frame), name=name)
    cerebro.addstrategy(strategy)
    return cerebro.run()[0]


class _ScalarProbe(bt.Strategy):
    """Collect a broad scalar-node surface from one real Backtrader clock."""

    def __init__(self):
        data = self.data
        self.delay = Delay(data.close, period=1.9)
        self.delta = Delta(data.close, period=1.9)
        self.total = RollingSum(data.close, period=3.9)
        self.product = RollingProduct(data.close, period=3.9)
        self.mean = RollingMean(data.close, period=3.9)
        self.std = RollingStd(data.close, period=3.9)
        self.minimum = TsMin(data.close, period=3.9)
        self.maximum = TsMax(data.close, period=3.9)
        self.argmin = TsArgMin(data.close, period=3.9)
        self.argmax = TsArgMax(data.close, period=3.9)
        self.rank = TsRank(data.close, period=3.9)
        self.decay = DecayLinear(data.close, period=3.9)
        self.x = self.data.close
        self.y = self.data.open
        self.covariance = RollingCovariance(self.x, self.y, period=3.9)
        self.correlation = RollingCorrelation(self.x, self.y, period=3.9)
        self.add = Add(self.x, self.y)
        self.subtract = Subtract(self.x, self.y)
        self.multiply = Multiply(self.x, self.y)
        self.divide = Divide(self.x, self.y)
        self.minimum_pair = Minimum(self.x, self.y)
        self.maximum_pair = Maximum(self.x, self.y)
        self.power = Power(self.x, 2.0)
        self.signed_power = SignedPower(self.x, 2.0)
        self.absolute = Abs(self.x)
        self.sign = Sign(self.x)
        self.log = Log(self.x)
        self.sqrt = Sqrt(self.x)
        self.negate = Negate(self.x)
        self.less = LessThan(self.x, self.y)
        self.less_equal = LessEqual(self.x, self.y)
        self.greater = GreaterThan(self.x, self.y)
        self.greater_equal = GreaterEqual(self.x, self.y)
        self.equal = EqualTo(self.x, self.y)
        self.not_equal = NotEqualTo(self.x, self.y)
        self.logical_and = LogicalAnd(self.less.value, self.greater.value)
        self.logical_or = LogicalOr(self.less.value, self.greater.value)
        self.logical_not = LogicalNot(self.less.value)
        self.where = Where(self.less.value, self.x, self.y)
        self.rows = []

    def next(self):
        names = (
            "delay",
            "delta",
            "total",
            "product",
            "mean",
            "std",
            "minimum",
            "maximum",
            "argmin",
            "argmax",
            "rank",
            "decay",
            "covariance",
            "correlation",
            "add",
            "subtract",
            "multiply",
            "divide",
            "minimum_pair",
            "maximum_pair",
            "power",
            "signed_power",
            "absolute",
            "sign",
            "log",
            "sqrt",
            "negate",
            "less",
            "less_equal",
            "greater",
            "greater_equal",
            "equal",
            "not_equal",
            "logical_and",
            "logical_or",
            "logical_not",
            "where",
        )
        self.rows.append(
            {
                name: (getattr(self, name).value[0], int(getattr(self, name).reason[0]))
                for name in names
            }
        )

    def prenext(self):
        self.next()

    def nextstart(self):
        self.next()


class _PanelProbe(bt.Strategy):
    def __init__(self):
        feeds = tuple(self.datas)
        values = tuple(data.close for data in feeds)
        memberships = tuple(data.member for data in feeds)
        self.rank = CrossSectionalRank.bind(*feeds, values=values, members=memberships)
        self.scale = CrossSectionalScale.bind(*feeds, values=values, members=memberships)
        self.neutral = IndNeutralize.bind(
            *feeds,
            values=values,
            members=memberships,
            groups=tuple(data.industry for data in feeds),
            level="industry",
        )
        self.neutral_default_group = IndNeutralize.bind(
            *feeds,
            values=values,
            members=memberships,
            level="sector",
        )
        self.rows = []

    def next(self):
        self.rows.append(
            {
                data._name: {
                    "rank": self.rank.outputs[data].value[0],
                    "rank_reason": int(self.rank.outputs[data].reason[0]),
                    "scale": self.scale.outputs[data].value[0],
                    "neutral": self.neutral.outputs[data].value[0],
                    "neutral_reason": int(self.neutral.outputs[data].reason[0]),
                    "neutral_default_group": self.neutral_default_group.outputs[data].value[0],
                }
                for data in self.datas
            }
        )


class _PanelOutputChainProbe(bt.Strategy):
    """Exercise target-aligned panel outputs consumed by scalar siblings."""

    def __init__(self):
        feeds = tuple(self.datas)
        members = tuple(data.member for data in feeds)
        self.base = CrossSectionalRank.bind(
            *feeds, values=tuple(data.close for data in feeds), members=members
        )
        offsets = (10.0, 0.0, -1.0)
        shifted = tuple(
            Add(self.base.outputs[data].value, offsets[index]).value
            for index, data in enumerate(feeds)
        )
        self.final = CrossSectionalRank.bind(*feeds, values=shifted, members=members)
        self.rows = []

    def next(self):
        self.rows.append(
            {
                data._name: {
                    "base": self.base.outputs[data].value[0],
                    "base_reason": int(self.base.outputs[data].reason[0]),
                    "final": self.final.outputs[data].value[0],
                    "final_reason": int(self.final.outputs[data].reason[0]),
                }
                for data in self.datas
            }
        )


class _NestedPanelOutputProbe(bt.Strategy):
    """Feed one panel node's lines directly into a second panel node."""

    def __init__(self):
        feeds = tuple(self.datas)
        self.neutral = IndNeutralize.bind(
            *feeds,
            values=tuple(data.close for data in feeds),
            groups=tuple(data.industry for data in feeds),
            level="industry",
        )
        self.rank = CrossSectionalRank.bind(
            *feeds,
            values=tuple(self.neutral.outputs[data].value for data in feeds),
        )
        self.rows = []

    def next(self):
        self.rows.append(
            {
                data._name: (
                    self.neutral.outputs[data].value[0],
                    self.rank.outputs[data].value[0],
                    int(self.neutral.outputs[data].reason[0]),
                    int(self.rank.outputs[data].reason[0]),
                )
                for data in self.datas
            }
        )


class _SharedScalarDagPanelProbe(bt.Strategy):
    """Resolve target provenance through scalar DAG branches with shared inputs."""

    def __init__(self):
        feeds = tuple(self.datas)
        ratios = []
        for data in feeds:
            shared = Add(data.close, data.open).value
            numerator = Multiply(shared, data.close).value
            denominator = Subtract(shared, data.high).value
            ratios.append(Divide(numerator, denominator).value)
        self.neutral = IndNeutralize.bind(
            *feeds,
            values=tuple(ratios),
            groups=tuple(data.industry for data in feeds),
            level="industry",
        )
        self.rows = []

    def next(self):
        self.rows.append({data._name: self.neutral.outputs[data].value[0] for data in self.datas})


@pytest.mark.parametrize("runonce", [False, True])
def test_ts_operators_use_floor_full_grid_ties_and_population_moments(runonce):
    frame = _frame(
        [2.0, 4.0, 4.0, 1.0, 2.0, float("nan"), 3.0, 3.0, 3.0],
        opens=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
    )
    result = _run(_ScalarProbe, [("asset", frame)], runonce=runonce)

    # The first complete 3-grid window is [2, 4, 4].
    row2 = result.rows[2]
    assert row2["total"] == (10.0, OperatorReason.READY)
    assert row2["product"] == (32.0, OperatorReason.READY)
    assert row2["mean"] == pytest.approx((10.0 / 3.0, OperatorReason.READY))
    assert row2["std"][0] == pytest.approx(math.sqrt(8.0 / 9.0))
    assert row2["minimum"] == (2.0, OperatorReason.READY)
    assert row2["maximum"] == (4.0, OperatorReason.READY)
    assert row2["argmin"] == (1.0, OperatorReason.READY)
    assert row2["argmax"] == (2.0, OperatorReason.READY)  # earliest tied maximum
    assert row2["rank"] == pytest.approx((2.5 / 3.0, OperatorReason.READY))
    assert row2["decay"][0] == pytest.approx((2.0 + 2 * 4.0 + 3 * 4.0) / 6.0)
    assert row2["delay"] == (4.0, OperatorReason.READY)  # floor(1.9) == 1
    assert row2["delta"] == (0.0, OperatorReason.READY)
    assert row2["covariance"][0] == pytest.approx(2.0 / 3.0)
    assert row2["correlation"][0] == pytest.approx(math.sqrt(3.0) / 2.0)

    # The explicit NaN grid slot is not deleted or compressed.  It invalidates
    # windows that include it; validity returns only after three finite rows.
    assert math.isnan(result.rows[5]["rank"][0])
    assert result.rows[5]["rank"][1] == OperatorReason.INCOMPLETE_WINDOW
    assert math.isnan(result.rows[7]["rank"][0])
    assert result.rows[7]["rank"][1] == OperatorReason.INCOMPLETE_WINDOW
    assert math.isnan(result.rows[7]["product"][0])
    assert result.rows[7]["product"][1] == OperatorReason.INCOMPLETE_WINDOW
    assert result.rows[8]["rank"] == pytest.approx((2.0 / 3.0, OperatorReason.READY))
    assert result.rows[8]["product"] == (27.0, OperatorReason.READY)


@pytest.mark.parametrize("runonce", [False, True])
def test_panel_rank_scale_and_pit_industry_neutralization(runonce):
    frames = [
        (
            "A",
            _frame(
                [10.0, 10.0],
                sectors=[1.0, 1.0],
                industries=[1.0, 1.0],
                members=[1.0, 1.0],
            ),
        ),
        (
            "B",
            _frame(
                [20.0, 0.0],
                sectors=[1.0, 1.0],
                industries=[1.0, 2.0],
                members=[1.0, 1.0],
            ),
        ),
        (
            "C",
            _frame(
                [20.0, 30.0],
                sectors=[2.0, 2.0],
                industries=[2.0, 2.0],
                members=[1.0, 0.0],
            ),
        ),
    ]
    result = _run(_PanelProbe, frames, runonce=runonce)

    first = result.rows[0]
    assert first["A"]["rank"] == pytest.approx(1.0 / 3.0)
    assert first["B"]["rank"] == pytest.approx(5.0 / 6.0)
    assert first["C"]["rank"] == pytest.approx(5.0 / 6.0)
    assert first["A"]["scale"] == pytest.approx(0.2)
    assert first["B"]["scale"] == pytest.approx(0.4)
    assert first["C"]["scale"] == pytest.approx(0.4)
    assert first["A"]["neutral"] == -5.0
    assert first["B"]["neutral"] == 5.0
    assert first["C"]["neutral"] == 0.0
    assert first["A"]["neutral_default_group"] == -5.0
    assert first["B"]["neutral_default_group"] == 5.0
    assert first["C"]["neutral_default_group"] == 0.0

    second = result.rows[1]
    assert second["C"]["rank_reason"] == OperatorReason.FORMULA_INELIGIBLE
    assert math.isnan(second["C"]["rank"])
    assert second["A"]["rank"] == pytest.approx(1.0)
    assert second["B"]["rank"] == pytest.approx(0.5)
    # Dynamic PIT industry memberships are read at each grid and do not rewrite
    # the prior output. A/B become singleton groups on the second row.
    assert second["A"]["neutral"] == 0.0
    assert second["B"]["neutral"] == 0.0
    assert first["A"]["neutral"] == -5.0


@pytest.mark.parametrize("runonce", [False, True])
def test_panel_outputs_keep_per_target_alignment_through_scalar_and_nan_rows(runonce):
    result = _run(
        _PanelOutputChainProbe,
        [
            ("A", _frame([1.0, 10.0, 5.0], members=[1.0, 1.0, 1.0])),
            ("B", _frame([3.0, 2.0, float("nan")], members=[1.0, 1.0, 1.0])),
            ("C", _frame([2.0, 4.0, 1.0], members=[1.0, 0.0, 1.0])),
        ],
        runonce=runonce,
    )

    first, second, third = result.rows
    assert [first[name]["base"] for name in ("A", "B", "C")] == pytest.approx(
        [1.0 / 3.0, 1.0, 2.0 / 3.0]
    )
    assert [first[name]["final"] for name in ("A", "B", "C")] == pytest.approx(
        [1.0, 2.0 / 3.0, 1.0 / 3.0]
    )

    # Membership changes at the middle grid: the excluded output stays NaN
    # through the scalar child and remains excluded from the next panel.
    assert second["C"]["base_reason"] == OperatorReason.FORMULA_INELIGIBLE
    assert math.isnan(second["C"]["final"])
    assert second["C"]["final_reason"] == OperatorReason.FORMULA_INELIGIBLE
    assert second["A"]["final"] == 1.0
    assert second["B"]["final"] == 0.5

    # A source NaN is preserved at its original grid and does not shift a
    # neighboring asset's value or compress the cross-sectional population.
    assert math.isnan(third["B"]["base"])
    assert third["B"]["base_reason"] == OperatorReason.NONFINITE_INPUT
    assert math.isnan(third["B"]["final"])
    assert third["B"]["final_reason"] == OperatorReason.NONFINITE_INPUT
    assert third["A"]["final"] == 1.0
    assert third["C"]["final"] == 0.5


@pytest.mark.parametrize("runonce", [False, True])
def test_pointwise_arithmetic_preserves_upstream_unknown_reason(runonce):
    class UnknownProbe(bt.Strategy):
        def __init__(self):
            comparison = LessThan(self.data.close, self.data.open)
            self.comparison = comparison
            self.scaled = Multiply(comparison.lines.value, -1.0)
            self.rows = []

        def next(self):
            self.rows.append(
                (
                    (self.comparison.value[0], int(self.comparison.reason[0])),
                    (self.scaled.value[0], int(self.scaled.reason[0])),
                )
            )

        def prenext(self):
            self.next()

        def nextstart(self):
            self.next()

    result = _run(
        UnknownProbe,
        [
            (
                "asset",
                _frame([1.0, float("nan"), 3.0], opens=[2.0, 2.0, 2.0]),
            )
        ],
        runonce=runonce,
    )
    assert result.rows[0] == (
        (1.0, OperatorReason.READY),
        (-1.0, OperatorReason.READY),
    )
    assert math.isnan(result.rows[1][0][0])
    assert result.rows[1][0][1] == OperatorReason.UNKNOWN
    assert math.isnan(result.rows[1][1][0])
    assert result.rows[1][1][1] == OperatorReason.UNKNOWN


@pytest.mark.parametrize("runonce", [False, True])
def test_ind_neutralize_outputs_retain_target_identity_for_next_panel(runonce):
    result = _run(
        _NestedPanelOutputProbe,
        [
            ("A", _frame([1.0, 4.0], industries=[1.0, 1.0])),
            ("B", _frame([3.0, 2.0], industries=[1.0, 1.0])),
            ("C", _frame([9.0, 1.0], industries=[2.0, 2.0])),
        ],
        runonce=runonce,
    )
    assert [result.rows[0][name][0] for name in ("A", "B", "C")] == [-1.0, 1.0, 0.0]
    assert [result.rows[0][name][1] for name in ("A", "B", "C")] == pytest.approx(
        [1.0 / 3.0, 1.0, 2.0 / 3.0]
    )
    assert [result.rows[1][name][0] for name in ("A", "B", "C")] == [1.0, -1.0, 0.0]
    assert [result.rows[1][name][1] for name in ("A", "B", "C")] == pytest.approx(
        [1.0, 1.0 / 3.0, 2.0 / 3.0]
    )
    assert all(
        reason == OperatorReason.READY
        for row in result.rows
        for name in ("A", "B", "C")
        for reason in row[name][2:]
    )


@pytest.mark.parametrize("runonce", [False, True])
def test_panel_target_resolution_handles_shared_scalar_dag_dependencies(runonce):
    result = _run(
        _SharedScalarDagPanelProbe,
        [
            (
                "A",
                _frame([10.0, 12.0], opens=[2.0, 3.0], industries=[1.0, 1.0]),
            ),
            (
                "B",
                _frame([20.0, 18.0], opens=[4.0, 5.0], industries=[1.0, 1.0]),
            ),
            (
                "C",
                _frame([30.0, 27.0], opens=[6.0, 7.0], industries=[1.0, 1.0]),
            ),
        ],
        runonce=runonce,
    )
    raw = [
        [(close + opening) * close / (opening - 1.0) for close, opening in row]
        for row in (
            ((10.0, 2.0), (20.0, 4.0), (30.0, 6.0)),
            ((12.0, 3.0), (18.0, 5.0), (27.0, 7.0)),
        )
    ]
    for observed, expected_raw in zip(result.rows, raw):
        mean = sum(expected_raw) / len(expected_raw)
        assert [observed[name] for name in ("A", "B", "C")] == pytest.approx(
            [value - mean for value in expected_raw]
        )


def test_panel_known_answer_average_rank_scale_and_industry_mean():
    frames = [
        ("A", _frame([10.0], industries=[7.0])),
        ("B", _frame([20.0], industries=[7.0])),
        ("C", _frame([20.0], industries=[8.0])),
        ("D", _frame([40.0], industries=[9.0])),
    ]
    result = _run(_PanelProbe, frames)
    row = result.rows[0]
    assert [row[name]["rank"] for name in ("A", "B", "C", "D")] == pytest.approx(
        [0.25, 0.625, 0.625, 1.0]
    )
    assert [row[name]["scale"] for name in ("A", "B", "C", "D")] == pytest.approx(
        [1.0 / 9.0, 2.0 / 9.0, 2.0 / 9.0, 4.0 / 9.0]
    )
    assert [row[name]["neutral"] for name in ("A", "B", "C", "D")] == pytest.approx(
        [-5.0, 5.0, 0.0, 0.0]
    )

    neutral = _run(
        _PanelProbe,
        [
            ("A", _frame([1.0], industries=[7.0])),
            ("B", _frame([3.0], industries=[7.0])),
            ("C", _frame([8.0], industries=[8.0])),
        ],
    ).rows[0]
    assert [neutral[name]["neutral"] for name in ("A", "B", "C")] == pytest.approx([-1.0, 1.0, 0.0])


@pytest.mark.parametrize("runonce", [False, True])
def test_cross_sectional_operators_partition_by_static_research_group(runonce):
    class GroupProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            values = tuple(data.close for data in feeds)
            groups = ("us", "us", "asia")
            self.rank = CrossSectionalRank.bind(*feeds, values=values, groups=groups)
            self.scale = CrossSectionalScale.bind(*feeds, values=values, groups=groups)
            self.rows = []

        def next(self):
            self.rows.append(
                {
                    data._name: (
                        self.rank.outputs[data].value[0],
                        self.scale.outputs[data].value[0],
                    )
                    for data in self.datas
                }
            )

    result = _run(
        GroupProbe,
        [
            ("A", _frame([1.0])),
            ("B", _frame([3.0])),
            ("C", _frame([100.0])),
        ],
        runonce=runonce,
    )
    row = result.rows[0]
    assert row["A"] == pytest.approx((0.5, 0.25))
    assert row["B"] == pytest.approx((1.0, 0.75))
    assert row["C"] == pytest.approx((1.0, 1.0))


def test_cross_sectional_scale_requires_finite_positive_a():
    class InvalidScaleProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            values = tuple(data.close for data in feeds)
            for scale in (0.0, -1.0, True, float("inf")):
                with pytest.raises(ValueError, match="finite positive"):
                    CrossSectionalScale.bind(*feeds, values=values, a=scale)

    _run(InvalidScaleProbe, [("asset", _frame([1.0]))])


@pytest.mark.parametrize("runonce", [False, True])
def test_unknown_formula_membership_is_rejected(runonce):
    class UnknownMembershipProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            self.rank = CrossSectionalRank.bind(
                *feeds,
                values=tuple(data.close for data in feeds),
                members=tuple(data.member for data in feeds),
            )

        def next(self):
            self.rank.outputs[self.datas[0]].value[0]

    with pytest.raises(OperatorInputError, match="membership is unknown"):
        _run(
            UnknownMembershipProbe,
            [
                ("A", _frame([1.0], members=[1.0])),
                ("B", _frame([2.0], members=[float("nan")])),
            ],
            runonce=runonce,
        )


@pytest.mark.parametrize("runonce", [False, True])
def test_empty_universe_zero_scale_and_unknown_pit_category_reasons(runonce):
    class PanelBoundaryProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            values = tuple(data.close for data in feeds)
            members = tuple(data.member for data in feeds)
            groups = tuple(data.industry for data in feeds)
            self.rank = CrossSectionalRank.bind(*feeds, values=values, members=members)
            self.scale = CrossSectionalScale.bind(*feeds, values=values, members=members)
            self.neutral = IndNeutralize.bind(
                *feeds, values=values, groups=groups, level="industry"
            )
            self.rows = []

        def next(self):
            self.rows.append(
                {
                    data._name: (
                        self.rank.outputs[data].value[0],
                        int(self.rank.outputs[data].reason[0]),
                        self.scale.outputs[data].value[0],
                        int(self.scale.outputs[data].reason[0]),
                        self.neutral.outputs[data].value[0],
                        int(self.neutral.outputs[data].reason[0]),
                    )
                    for data in self.datas
                }
            )

    empty = _run(
        PanelBoundaryProbe,
        [
            ("A", _frame([1.0], members=[0.0])),
            ("B", _frame([2.0], members=[0.0])),
        ],
        runonce=runonce,
    ).rows[0]
    for asset in ("A", "B"):
        assert math.isnan(empty[asset][0])
        assert empty[asset][1] == OperatorReason.FORMULA_INELIGIBLE
        assert math.isnan(empty[asset][2])
        assert empty[asset][3] == OperatorReason.FORMULA_INELIGIBLE

    zero = _run(
        PanelBoundaryProbe,
        [
            ("A", _frame([0.0], industries=[1.0])),
            ("B", _frame([0.0], industries=[1.0])),
        ],
        runonce=runonce,
    ).rows[0]
    assert zero["A"][0] == pytest.approx(0.75)
    assert zero["B"][0] == pytest.approx(0.75)
    for asset in ("A", "B"):
        assert math.isnan(zero[asset][2])
        assert zero[asset][3] == OperatorReason.DOMAIN_ERROR

    unknown_classification = _run(
        PanelBoundaryProbe,
        [
            ("A", _frame([1.0], industries=[float("nan")])),
            ("B", _frame([3.0], industries=[7.0])),
        ],
        runonce=runonce,
    ).rows[0]
    assert math.isnan(unknown_classification["A"][4])
    assert unknown_classification["A"][5] == OperatorReason.UNKNOWN_CLASSIFICATION
    assert unknown_classification["B"][4] == 0.0
    assert unknown_classification["B"][5] == OperatorReason.READY


@pytest.mark.parametrize("runonce", [False, True])
def test_pointwise_math_boolean_truth_table_and_where_branch_isolation(runonce):
    # One row per case allows real Indicator nodes to exercise 0, NaN and
    # unselected branch behavior without using their own output as expected.
    rows = [
        (2.0, 3.0),
        (0.0, 0.0),
        (float("nan"), 1.0),
        (-4.0, 2.0),
    ]

    class Probe(bt.Strategy):
        def __init__(self):
            x, y = self.data.close, self.data.open
            self.less = LessThan(x, y)
            self.greater = GreaterThan(x, y)
            known_false = LessThan(y, y)
            known_true = EqualTo(y, y)
            self.and_ = LogicalAnd(self.less.value, known_false.value)
            self.or_ = LogicalOr(self.less.value, known_true.value)
            self.not_ = LogicalNot(self.less.value)
            # For row 0 the condition is true, so the zero denominator in the
            # unselected right branch must not invalidate the selected x value.
            zero = Subtract(y, y)
            self.quotient = Divide(1.0, zero)
            self.where = Where(self.less.value, x, self.quotient.value)
            self.boolean_add = Add(self.less.value, 1.0)
            self.boolean_sum = RollingSum(self.less.value, period=2)
            self.boolean_decay = DecayLinear(self.less.value, period=2)
            self.power = Power(x, 2.0)
            self.fractional_power = Power(x, 0.5)
            self.constant_power = Power(0.0, 0.0)
            self.zero_negative_signed = SignedPower(0.0, -1.0)
            self.add_constant = Add(x, 0.001)
            self.signed = SignedPower(x, 0.5)
            self.add = Add(x, y)
            self.sub = Subtract(x, y)
            self.mul = Multiply(x, y)
            self.div = Divide(x, y)
            self.min = Minimum(x, y)
            self.max = Maximum(x, y)
            self.abs = Abs(x)
            self.sign = Sign(x)
            self.log = Log(x)
            self.sqrt = Sqrt(x)
            self.negate = Negate(x)
            self.less_equal = LessEqual(x, y)
            self.greater_equal = GreaterEqual(x, y)
            self.equal = EqualTo(x, y)
            self.not_equal = NotEqualTo(x, y)
            self.rows = []

        def next(self):
            nodes = (
                self.less,
                self.greater,
                self.and_,
                self.or_,
                self.not_,
                self.quotient,
                self.where,
                self.boolean_add,
                self.boolean_sum,
                self.boolean_decay,
                self.power,
                self.fractional_power,
                self.constant_power,
                self.zero_negative_signed,
                self.add_constant,
                self.signed,
                self.add,
                self.sub,
                self.mul,
                self.div,
                self.min,
                self.max,
                self.abs,
                self.sign,
                self.log,
                self.sqrt,
                self.negate,
                self.less_equal,
                self.greater_equal,
                self.equal,
                self.not_equal,
            )
            self.rows.append([(node.value[0], int(node.reason[0])) for node in nodes])

        def prenext(self):
            self.next()

        def nextstart(self):
            self.next()

    frame = _frame([item[0] for item in rows], opens=[item[1] for item in rows])
    result = _run(Probe, [("asset", frame)], runonce=runonce)
    first = result.rows[0]
    assert first[0] == (1.0, OperatorReason.READY)
    assert first[1] == (0.0, OperatorReason.READY)
    assert first[2] == (0.0, OperatorReason.READY)  # true AND false
    assert first[3] == (1.0, OperatorReason.READY)  # true OR true
    assert first[4] == (0.0, OperatorReason.READY)
    assert math.isnan(first[5][0]) and first[5][1] == OperatorReason.DOMAIN_ERROR
    assert first[6] == (2.0, OperatorReason.READY)
    assert first[7] == (2.0, OperatorReason.READY)  # true maps to 1 before arithmetic
    assert math.isnan(first[8][0]) and first[8][1] == OperatorReason.NOT_READY
    assert math.isnan(first[9][0]) and first[9][1] == OperatorReason.NOT_READY
    assert first[10] == (4.0, OperatorReason.READY)
    assert first[11] == pytest.approx((math.sqrt(2.0), OperatorReason.READY))
    assert first[12] == (1.0, OperatorReason.READY)
    assert first[13][1] == OperatorReason.DOMAIN_ERROR
    assert first[14] == pytest.approx((2.001, OperatorReason.READY))
    assert first[15] == pytest.approx((math.sqrt(2.0), OperatorReason.READY))
    assert first[16] == (5.0, OperatorReason.READY)
    assert first[17] == (-1.0, OperatorReason.READY)
    assert first[18] == (6.0, OperatorReason.READY)
    assert first[19][0] == pytest.approx(2.0 / 3.0)
    assert first[20] == (2.0, OperatorReason.READY)
    assert first[21] == (3.0, OperatorReason.READY)
    assert first[22] == (2.0, OperatorReason.READY)
    assert first[23] == (1.0, OperatorReason.READY)
    assert first[24][0] == pytest.approx(math.log(2.0))
    assert first[25][0] == pytest.approx(math.sqrt(2.0))
    assert first[26] == (-2.0, OperatorReason.READY)
    assert first[27:] == [
        (1.0, OperatorReason.READY),
        (0.0, OperatorReason.READY),
        (0.0, OperatorReason.READY),
        (1.0, OperatorReason.READY),
    ]

    zero = result.rows[1]
    assert zero[5][1] == OperatorReason.DOMAIN_ERROR
    assert zero[7] == (1.0, OperatorReason.READY)  # false maps to 0 before arithmetic
    assert zero[8] == (1.0, OperatorReason.READY)  # rolling sum of [true, false]
    assert zero[9] == pytest.approx((1.0 / 3.0, OperatorReason.READY))
    assert zero[11] == (0.0, OperatorReason.READY)  # ordinary 0**0.5
    assert zero[12] == (1.0, OperatorReason.READY)  # ordinary 0**0
    assert zero[13][1] == OperatorReason.DOMAIN_ERROR  # signed 0**-1
    assert zero[14] == pytest.approx((0.001, OperatorReason.READY))
    assert zero[15] == (0.0, OperatorReason.READY)
    assert zero[24][1] == OperatorReason.DOMAIN_ERROR  # log(0)
    assert zero[25] == (0.0, OperatorReason.READY)
    assert zero[27:] == [
        (1.0, OperatorReason.READY),
        (1.0, OperatorReason.READY),
        (1.0, OperatorReason.READY),
        (0.0, OperatorReason.READY),
    ]

    missing = result.rows[2]
    assert math.isnan(missing[0][0]) and missing[0][1] == OperatorReason.UNKNOWN
    assert missing[2] == (0.0, OperatorReason.READY)  # unknown AND false
    assert missing[3] == (1.0, OperatorReason.READY)  # unknown OR true
    assert math.isnan(missing[6][0]) and missing[6][1] == OperatorReason.UNKNOWN
    assert all(
        math.isnan(value) and reason == OperatorReason.UNKNOWN for value, reason in missing[27:]
    )
    assert math.isnan(missing[7][0]) and missing[7][1] == OperatorReason.UNKNOWN
    assert math.isnan(missing[8][0]) and missing[8][1] == OperatorReason.INCOMPLETE_WINDOW
    assert math.isnan(missing[9][0]) and missing[9][1] == OperatorReason.INCOMPLETE_WINDOW

    negative_base = result.rows[3]
    assert negative_base[10][1] == OperatorReason.READY  # (-4)**2
    assert negative_base[11][1] == OperatorReason.DOMAIN_ERROR  # ordinary negative fractional power
    assert negative_base[15] == (-2.0, OperatorReason.READY)  # signed power keeps the sign
    assert negative_base[24][1] == OperatorReason.DOMAIN_ERROR
    assert negative_base[25][1] == OperatorReason.DOMAIN_ERROR
    assert negative_base[27:] == [
        (1.0, OperatorReason.READY),
        (0.0, OperatorReason.READY),
        (0.0, OperatorReason.READY),
        (1.0, OperatorReason.READY),
    ]


@pytest.mark.parametrize("runonce", [False, True])
def test_constructor_rejects_invalid_windows_and_profile_parameters(runonce):
    class InvalidWindowProbe(bt.Strategy):
        def __init__(self):
            with pytest.raises(ValueError):
                RollingSum(self.data.close, period=0.9)
            with pytest.raises(ValueError):
                Delay(self.data.close, period=-0.1)
            with pytest.raises(ValueError):
                Delta(self.data.close, period=0.9)
            with pytest.raises(ValueError):
                IndNeutralize.bind(self.data, values=(self.data.close,), level="group")

    _run(InvalidWindowProbe, [("asset", _frame([1.0]))], runonce=runonce)


def test_source_infinity_is_rejected_instead_of_becoming_valid_or_nan():
    source = LineBuffer()
    source.forward()
    source.array[0] = float("inf")
    with pytest.raises(OperatorInputError):
        _read_value(source)


@pytest.mark.parametrize("runonce", [False, True])
def test_rolling_product_fractional_window_floors_to_complete_fourteen_grid(runonce):
    class ProductFloorProbe(bt.Strategy):
        def __init__(self):
            self.product = RollingProduct(self.data.close, period=14.9655)
            self.rows = []

        def next(self):
            self.rows.append((self.product.value[0], int(self.product.reason[0])))

        def prenext(self):
            self.next()

        def nextstart(self):
            self.next()

    values = [1.0] * 13 + [2.0, 3.0]
    result = _run(
        ProductFloorProbe,
        [("asset", _frame(values))],
        runonce=runonce,
    )
    assert math.isnan(result.rows[12][0])
    assert result.rows[12][1] == OperatorReason.NOT_READY
    assert result.rows[13] == (2.0, OperatorReason.READY)
    assert result.rows[14] == (6.0, OperatorReason.READY)


def test_alpha101_operator_coverage_maps_to_native_indicator_classes():
    actual = {
        name: getattr(operator_module, name, None)
        for name in _ALPHA101_OPERATOR_CLASSES | {"RollingMean"}
    }
    mapped = {
        name
        for name, candidate in actual.items()
        if isinstance(candidate, type) and issubclass(candidate, bt.Indicator)
    }
    assert mapped == _ALPHA101_OPERATOR_CLASSES | {"RollingMean"}
    assert all(issubclass(actual[name], bt.Indicator) for name in mapped)


@pytest.mark.parametrize("runonce", [False, True])
def test_large_finite_windows_and_degenerate_window_boundaries(runonce):
    class BoundaryProbe(bt.Strategy):
        def __init__(self):
            x, y = self.data.close, self.data.open
            self.correlation = RollingCorrelation(x, y, period=3.9)
            self.one_correlation = RollingCorrelation(x, y, period=1)
            self.one_covariance = RollingCovariance(x, y, period=1)
            self.one_std = RollingStd(x, period=1)
            self.total = RollingSum(x, period=2)
            self.product = RollingProduct(x, period=2)
            self.mean = RollingMean(x, period=2)
            self.rows = []

        def next(self):
            nodes = (
                self.correlation,
                self.one_correlation,
                self.one_covariance,
                self.one_std,
                self.total,
                self.product,
                self.mean,
            )
            self.rows.append([(node.value[0], int(node.reason[0])) for node in nodes])

        def prenext(self):
            self.next()

        def nextstart(self):
            self.next()

    values = [0.0, 1e153, 2e153, 1e308, 1e308]
    result = _run(
        BoundaryProbe,
        [("asset", _frame(values, opens=values))],
        runonce=runonce,
    )
    assert result.rows[2][0] == pytest.approx((1.0, OperatorReason.READY))
    assert math.isnan(result.rows[0][1][0])
    assert result.rows[0][1][1] == OperatorReason.DOMAIN_ERROR
    assert math.isnan(result.rows[2][1][0])
    assert result.rows[2][1][1] == OperatorReason.DOMAIN_ERROR
    assert result.rows[2][2] == (0.0, OperatorReason.READY)
    assert result.rows[2][3] == (0.0, OperatorReason.READY)
    assert math.isnan(result.rows[4][4][0])
    assert result.rows[4][4][1] == OperatorReason.DOMAIN_ERROR
    assert math.isnan(result.rows[4][5][0])
    assert result.rows[4][5][1] == OperatorReason.DOMAIN_ERROR
    assert result.rows[4][6] == pytest.approx((1e308, OperatorReason.READY))


@pytest.mark.parametrize("runonce", [False, True])
def test_rolling_covariance_rounds_exact_binary64_inputs_without_sign_reversal(runonce):
    left_zero = [0.66666666666666663] * 5
    right_zero = [
        0.66666666666666663,
        0.5,
        0.5,
        0.16666666666666666,
        0.33333333333333331,
    ]
    left_small = [
        0.5,
        0.83333333333333337,
        0.5,
        0.16666666666666666,
        0.33333333333333331,
    ]
    right_small = [
        1.0,
        0.33333333333333331,
        0.33333333333333331,
        0.33333333333333331,
        0.5,
    ]

    class CovarianceProbe(bt.Strategy):
        def __init__(self):
            self.zero = RollingCovariance(self.datas[0].close, self.datas[0].open, period=5)
            self.small = RollingCovariance(self.datas[1].close, self.datas[1].open, period=5)
            self.rows = []

        def next(self):
            self.rows.append(
                (
                    (self.zero.value[0], int(self.zero.reason[0])),
                    (self.small.value[0], int(self.small.reason[0])),
                )
            )

    result = _run(
        CovarianceProbe,
        [
            ("zero", _frame(left_zero, opens=right_zero)),
            ("small", _frame(left_small, opens=right_small)),
        ],
        runonce=runonce,
    )

    def exact_population_covariance(left, right):
        left_exact = [Fraction.from_float(value) for value in left]
        right_exact = [Fraction.from_float(value) for value in right]
        count = len(left_exact)
        sum_products = sum((x * y for x, y in zip(left_exact, right_exact)), Fraction(0))
        return float((count * sum_products - sum(left_exact) * sum(right_exact)) / (count * count))

    expected_zero = exact_population_covariance(left_zero, right_zero)
    expected_small = exact_population_covariance(left_small, right_small)
    assert expected_zero == 0.0
    assert expected_small < 0.0
    assert result.rows[-1][0] == (expected_zero, OperatorReason.READY)
    assert result.rows[-1][1][0] == expected_small
    assert result.rows[-1][1][1] == OperatorReason.READY


@pytest.mark.parametrize("runonce", [False, True])
def test_rolling_product_avoids_intermediate_overflow_when_final_product_is_finite(runonce):
    class ProductProbe(bt.Strategy):
        def __init__(self):
            self.product = RollingProduct(self.data.close, period=4)
            self.rows = []

        def next(self):
            self.rows.append((self.product.value[0], int(self.product.reason[0])))

        def prenext(self):
            self.next()

        def nextstart(self):
            self.next()

    result = _run(
        ProductProbe,
        [("asset", _frame([1e308, 1e308, 1e-308, 1e-308]))],
        runonce=runonce,
    )
    assert math.isnan(result.rows[2][0])
    assert result.rows[2][1] == OperatorReason.NOT_READY
    assert result.rows[3][0] == pytest.approx(1.0, rel=1e-12)
    assert result.rows[3][1] == OperatorReason.READY
