"""Iteration 71 regression tests for R71-105, R71-059, R71-063, R71-159, R71-160."""

from __future__ import annotations

import datetime as dt
import json
import logging
import math

import pytest

import backtrader as bt
import backtrader.indicators.basicops as basicops_mod
import backtrader.indicators.deviation as deviation_mod
from backtrader.observers.trade_logger import TradeLogger
from backtrader.utils.autodict import AutoOrderedDict


class _SyntheticFeed(bt.feed.DataBase):
    """Deterministic in-memory feed for real Cerebro parity tests."""

    params = (("input_values", ()), ("raw_close_infinities", False))

    def __init__(self):
        super().__init__()
        self._index = 0

    def _load(self):
        if self._index >= len(self.p.input_values):
            return False

        value = float(self.p.input_values[self._index])
        moment = dt.datetime(2026, 1, 1) + dt.timedelta(minutes=self._index)
        self.lines.datetime[0] = bt.date2num(moment)
        self.lines.open[0] = value
        self.lines.high[0] = value + 1.0 if math.isfinite(value) else value
        self.lines.low[0] = value - 1.0 if math.isfinite(value) else value
        self.lines.close[0] = value
        if self.p.raw_close_infinities and math.isinf(value):
            self.lines.close.array[-1] = value
        self.lines.volume[0] = 10.0 + (self._index % 7)
        self.lines.openinterest[0] = 0.0
        self._index += 1
        return True


def _sample_values(count, *, offset=0.0):
    return [
        offset + ((i * 17) % 37 - 18) * 0.125 + (i % 5) * 0.0001
        for i in range(count)
    ]


def _assert_bit_exact_sequence(actual, expected):
    assert len(actual) == len(expected)
    for idx, (a, e) in enumerate(zip(actual, expected)):
        if math.isnan(e):
            assert math.isnan(a), f"index {idx}: expected NaN, got {a!r}"
        else:
            assert a == e, f"index {idx}: {a!r} != {e!r}"
            if a == 0.0:
                assert math.copysign(1.0, a) == math.copysign(1.0, e), f"index {idx}: zero sign"


# ===========================================================================
# R71-105: TradeLogger._collect_indicators & lazy text formatting
# ===========================================================================


def _reference_collect_indicators(trade_logger):
    """Exact pre-optimization dir()/getattr() algorithm for equivalence checks."""
    indicators = {}
    owner = trade_logger._owner
    if hasattr(owner, "_lineiterators"):
        for item in owner._lineiterators.get(owner.IndType, []):
            _reference_extract(item, indicators)
    for attr_name in dir(owner):
        if attr_name.startswith("_"):
            continue
        try:
            attr = getattr(owner, attr_name)
            if hasattr(attr, "lines") and hasattr(attr, "__len__"):
                _reference_extract(attr, indicators, attr_name)
        except Exception:
            continue
    if hasattr(owner, "get_custom_indicators") and callable(owner.get_custom_indicators):
        custom = owner.get_custom_indicators()
        if isinstance(custom, dict):
            indicators.update(custom)
    return indicators


def _reference_extract(indicator, indicators_dict, prefix=""):
    ind_name = indicator.__class__.__name__
    if prefix:
        ind_name = f"{prefix}_{ind_name}"
    if hasattr(indicator, "lines"):
        try:
            aliases = indicator.lines.getlinealiases()
        except Exception:
            return
        for line_name in aliases:
            try:
                line = getattr(indicator.lines, line_name)
                if len(line) > 0:
                    value = line[0]
                    if value is not None and not (
                        hasattr(value, "__float__") and float(value) != float(value)
                    ):
                        full_name = (
                            f"{ind_name}_{line_name}"
                            if line_name != ind_name.lower()
                            else ind_name
                        )
                        indicators_dict[full_name] = float(value)
            except Exception:
                continue


def test_r71_105_collect_indicators_matches_dir_reference_with_dynamic_attrs(tmp_path):
    class DynamicStrategy(bt.Strategy):
        # Unhashable class attributes must not break descriptor scanning.
        class_dict_attr = {"k": "v"}
        class_list_attr = [1, 2, 3]

        def __init__(self):
            self.sma_fast = bt.indicators.SMA(self.data.close, period=3)
            self.sma_slow = bt.indicators.SMA(self.data.close, period=5)
            self.bb = bt.indicators.BollingerBands(self.data.close, period=5)
            self.temp_ind = self.sma_fast
            self.rebound = None
            self.comparisons = []
            self._tl = None

        @property
        def dynamic_prop(self):
            return self.sma_slow if len(self) % 2 == 0 else self.sma_fast

        def get_custom_indicators(self):
            return {"custom_bar_index": float(len(self))}

        def start(self):
            self._tl = [obs for obs in self.stats.items if isinstance(obs, TradeLogger)][0]

        def next(self):
            bar_n = len(self)
            if bar_n == 8:
                # Dynamically attach a new indicator attribute mid-run.
                self.late_attached = self.sma_slow
            elif bar_n == 12:
                # Rebind an existing None attribute to a multi-line indicator.
                self.rebound = self.bb
            elif bar_n == 16 and hasattr(self, "temp_ind"):
                # Remove an existing indicator attribute mid-run.
                del self.temp_ind

            actual = self._tl._collect_indicators()
            expected = _reference_collect_indicators(self._tl)
            self.comparisons.append((bar_n, list(actual.items()), list(expected.items())))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(_SyntheticFeed(input_values=_sample_values(25, offset=100.0)), name="S0")
    cerebro.addstrategy(DynamicStrategy)
    cerebro.addobserver(
        TradeLogger,
        log_dir=str(tmp_path),
        log_format="json",
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=True,
        log_signals=False,
        log_ticks=False,
        log_bars=False,
        log_system=False,
        log_monitoring=False,
        log_errors=False,
        log_value=False,
        log_position_snapshot=False,
    )
    (strat,) = cerebro.run(runonce=True, preload=True)

    assert len(strat.comparisons) >= 15
    for bar_n, actual_items, expected_items in strat.comparisons:
        assert actual_items == expected_items, f"mismatch at bar {bar_n}"

    # Verify dynamic attribute lifecycle actually reflected in collected keys.
    keys_by_bar = {bar_n: dict(items) for bar_n, items, _ in strat.comparisons}
    assert "late_attached_MovingAverageSimple_sma" not in keys_by_bar[7]
    assert "late_attached_MovingAverageSimple_sma" in keys_by_bar[8]
    assert "rebound_BollingerBands_top" not in keys_by_bar[11]
    assert "rebound_BollingerBands_top" in keys_by_bar[12]
    assert "temp_ind_MovingAverageSimple_sma" in keys_by_bar[15]
    assert "temp_ind_MovingAverageSimple_sma" not in keys_by_bar[16]
    assert "dynamic_prop_MovingAverageSimple_sma" in keys_by_bar[8]
    assert keys_by_bar[8]["custom_bar_index"] == 8.0


def test_r71_105_user_property_overriding_framework_name_is_not_skipped(tmp_path):
    class OverrideFrameworkPropStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=3)
            self.collected = []
            self._tl = None

        @property
        def sizer(self):
            return self.sma

        def start(self):
            self._tl = [obs for obs in self.stats.items if isinstance(obs, TradeLogger)][0]

        def next(self):
            self.collected.append(self._tl._collect_indicators())

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(_SyntheticFeed(input_values=_sample_values(10, offset=50.0)), name="S0")
    cerebro.addstrategy(OverrideFrameworkPropStrategy)
    cerebro.addobserver(
        TradeLogger,
        log_dir=str(tmp_path),
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=False,
        log_signals=False,
        log_ticks=False,
        log_bars=False,
        log_system=False,
        log_monitoring=False,
        log_errors=False,
        log_value=False,
        log_position_snapshot=False,
    )
    (strat,) = cerebro.run(runonce=True, preload=True)
    assert strat.collected
    assert "sizer_MovingAverageSimple_sma" in strat.collected[-1]


def test_r71_105_slots_only_owner_and_broken_property_fallback(bt_caplog):
    class FakeLine:
        def __len__(self):
            return 1

        def __getitem__(self, idx):
            return 42.5

    class FakeLines:
        def getlinealiases(self):
            return ("val",)

        val = FakeLine()

    class FakeInd:
        lines = FakeLines()

        def __len__(self):
            return 1

    class SlotsOwner:
        __slots__ = ("ind",)

        def __init__(self):
            self.ind = FakeInd()

        @property
        def broken(self):
            raise RuntimeError("boom")

    tl = object.__new__(TradeLogger)
    tl._owner = SlotsOwner()

    with bt_caplog.at_level(logging.DEBUG):
        result = tl._collect_indicators()

    assert result == {"ind_FakeInd_val": 42.5}
    assert any("Failed to read indicator attr" in r.message for r in bt_caplog.records)


def test_r71_105_indicator_log_json_and_text_formats(tmp_path):
    class TwoIndStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=2)
            self.bb = bt.indicators.BollingerBands(self.data.close, period=3)
            self._tl = None

        def start(self):
            self._tl = [obs for obs in self.stats.items if isinstance(obs, TradeLogger)][0]

        def next(self):
            self._tl.p.log_format = "json" if len(self) % 2 == 1 else "text"

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(_SyntheticFeed(input_values=[10.0, 11.0, 12.0, 13.0, 14.0, 15.0]), name="S0")
    cerebro.addstrategy(TwoIndStrategy)
    cerebro.addobserver(
        TradeLogger,
        log_dir=str(tmp_path),
        log_format="json",
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=True,
        log_signals=False,
        log_ticks=False,
        log_bars=False,
        log_system=False,
        log_monitoring=False,
        log_errors=False,
        log_value=False,
        log_position_snapshot=False,
    )
    cerebro.run(runonce=False, preload=False)

    lines = (tmp_path / "indicator.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6  # observer runs on all 6 bars; next() toggles format on bars 3..6
    rec2 = json.loads(lines[2])
    assert "sma_MovingAverageSimple_sma" in rec2
    assert "bb_BollingerBands_mid" in rec2
    assert " | INDICATOR | " in lines[3]
    assert "sma_MovingAverageSimple_sma=" in lines[3]
    assert "bb_BollingerBands_mid=" in lines[3]
    rec4 = json.loads(lines[4])
    assert "bb_BollingerBands_mid" in rec4
    assert " | INDICATOR | " in lines[5]


# ===========================================================================
# R71-059: AutoOrderedDict arithmetic contracts
# ===========================================================================


def test_r71_059_binary_arithmetic_same_type_and_missing_keys():
    a = AutoOrderedDict()
    a["x"] = 10
    a["y"] = 20.0

    b = AutoOrderedDict()
    b["y"] = 4.0
    b["z"] = 5

    added = a + b
    assert isinstance(added, AutoOrderedDict)
    assert list(added.keys()) == ["x", "y", "z"]
    assert added["x"] == 10
    assert added["y"] == 24.0
    assert added["z"] == 5
    # Originals remain unchanged.
    assert list(a.keys()) == ["x", "y"] and a["y"] == 20.0
    assert list(b.keys()) == ["y", "z"] and b["y"] == 4.0

    subbed = a - b
    assert list(subbed.keys()) == ["x", "y", "z"]
    assert subbed["x"] == 10
    assert subbed["y"] == 16.0
    assert subbed["z"] == -5

    multiplied = a * b
    assert list(multiplied.keys()) == ["x", "y", "z"]
    assert multiplied["x"] == 0
    assert multiplied["y"] == 80.0
    assert multiplied["z"] == 0

    # True division: missing left key yields 0.0; missing right key raises ZeroDivisionError.
    left = AutoOrderedDict()
    left["y"] = 20.0
    right = AutoOrderedDict()
    right["y"] = 4.0
    right["z"] = 5.0
    divided = left / right
    assert divided["y"] == 5.0
    assert divided["z"] == 0.0

    with pytest.raises(ZeroDivisionError):
        _ = a / b


def test_r71_059_inplace_same_type_mutates_in_place_and_is_atomic_on_error():
    a = AutoOrderedDict()
    a["x"] = 10
    a["y"] = 20
    alias = a

    b = AutoOrderedDict()
    b["y"] = 5
    b["z"] = 3

    a += b
    assert a is alias
    assert list(a.keys()) == ["x", "y", "z"]
    assert a["x"] == 10 and a["y"] == 25 and a["z"] == 3

    a -= b
    assert a is alias
    assert a["x"] == 10 and a["y"] == 20 and a["z"] == 0

    a *= b
    assert a is alias
    assert a["x"] == 0 and a["y"] == 100 and a["z"] == 0

    # Self-addition must work without reading cleared state.
    c = AutoOrderedDict()
    c["v"] = 7
    c += c
    assert c["v"] == 14

    # In-place division works for matching non-zero keys.
    d1 = AutoOrderedDict()
    d1["a"] = 12.0
    d1["b"] = 9.0
    d2 = AutoOrderedDict()
    d2["a"] = 3.0
    d2["b"] = 3.0
    d1 /= d2
    assert d1["a"] == 4.0 and d1["b"] == 3.0

    # Fail-closed atomicity: error mid-operation leaves target unmodified.
    d3 = AutoOrderedDict()
    d3["ok"] = 10.0
    d3["boom"] = 5.0
    d4 = AutoOrderedDict()
    d4["ok"] = 2.0
    d4["boom"] = 0.0
    with pytest.raises(ZeroDivisionError):
        d3 /= d4
    assert d3["ok"] == 10.0 and d3["boom"] == 5.0


def test_r71_059_nested_autoordereddict_arithmetic_and_isolation():
    d1 = AutoOrderedDict()
    d1["pnl"]["gross"] = 100.0
    d1["pnl"]["net"] = 90.0
    d1["only1"]["count"] = 3

    d2 = AutoOrderedDict()
    d2["pnl"]["gross"] = 50.0
    d2["pnl"]["fees"] = 5.0
    d2["only2"]["count"] = 4

    s = d1 + d2
    assert s["pnl"]["gross"] == 150.0
    assert s["pnl"]["net"] == 90.0
    assert s["pnl"]["fees"] == 5.0
    assert s["only1"]["count"] == 3
    assert s["only2"]["count"] == 4

    # Mutating the result must not alias d1 or d2 nested dicts.
    s["only1"]["count"] = 999
    s["only2"]["count"] = 888
    assert d1["only1"]["count"] == 3
    assert d2["only2"]["count"] == 4

    diff = d1 - d2
    assert diff["pnl"]["gross"] == 50.0
    assert diff["pnl"]["fees"] == -5.0
    assert diff["only1"]["count"] == 3
    assert diff["only2"]["count"] == -4

    prod = d1 * d2
    assert prod["pnl"]["gross"] == 5000.0
    assert prod["pnl"]["net"] == 0.0
    assert prod["only1"]["count"] == 0
    assert prod["only2"]["count"] == 0

    # Structural mismatch (nested dict vs scalar) fails closed with TypeError.
    bad = AutoOrderedDict()
    bad["pnl"] = 10.0
    with pytest.raises(TypeError):
        _ = d1 + bad


def test_r71_059_scalar_coercion_and_unsupported_types_return_not_implemented():
    # Empty AutoOrderedDict preserves auto-initialization scalar contract (TradeAnalyzer).
    d = AutoOrderedDict()
    d["count"] += 5
    d["loss"] -= 3
    d["streak"] *= 7
    d["ratio"] /= 2.0
    d["label"] += "ok"
    assert d["count"] == 5
    assert d["loss"] == -3
    assert d["streak"] == 0
    assert d["ratio"] == 0.0
    assert d["label"] == "ok"

    # ZeroDivisionError on empty placeholder must propagate (not become TypeError).
    empty = AutoOrderedDict()
    with pytest.raises(ZeroDivisionError):
        empty /= 0

    # Non-empty AutoOrderedDict rejects scalar in-place ops instead of discarding entries.
    populated = AutoOrderedDict()
    populated["a"] = 10
    assert populated.__iadd__(5) is NotImplemented
    assert populated.__isub__(5) is NotImplemented
    assert populated.__imul__(5) is NotImplemented
    assert populated.__itruediv__(5) is NotImplemented
    with pytest.raises(TypeError):
        populated += 5
    assert populated["a"] == 10

    # Binary ops return NotImplemented for all non-AutoOrderedDict types.
    for other in (5, 2.5, "str", {"a": 1}, None, object()):
        assert populated.__add__(other) is NotImplemented
        assert populated.__sub__(other) is NotImplemented
        assert populated.__mul__(other) is NotImplemented
        assert populated.__truediv__(other) is NotImplemented
        with pytest.raises(TypeError):
            _ = populated + other

    # Unsupported types on empty placeholder also return NotImplemented / raise TypeError.
    e = AutoOrderedDict()
    assert e.__iadd__(None) is NotImplemented
    assert e.__iadd__(object()) is NotImplemented
    assert e.__isub__("abc") is NotImplemented
    with pytest.raises(TypeError):
        e += object()

    # Closed AutoOrderedDicts still work in binary ops without triggering __missing__.
    c1 = AutoOrderedDict()
    c1["k"] = 2
    c1._close()
    c2 = AutoOrderedDict()
    c2["k"] = 3
    c2["m"] = 4
    c2._close()
    combined = c1 + c2
    assert combined["k"] == 5 and combined["m"] == 4


# ===========================================================================
# R71-159: basicops SumN / AnyN / AllN runonce parity & boundaries
# ===========================================================================


def _run_indicator(values, indicator_cls, *, period, runonce, exactbars=0, raw_inf=False, **kwargs):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = indicator_cls(self.data.close, period=period, **kwargs)
            self.recorded = []

        def _rec(self):
            self.recorded.append(float(self.ind[0]))

        def prenext(self):
            self._rec()

        def nextstart(self):
            self._rec()

        def next(self):
            self._rec()

        def stop(self):
            self.raw_array = list(self.ind.lines[0].array)

    cerebro = bt.Cerebro(
        stdstats=False,
        runonce=runonce,
        preload=not exactbars,
        exactbars=exactbars,
    )
    cerebro.adddata(
        _SyntheticFeed(input_values=values, raw_close_infinities=raw_inf), name="SYNTH"
    )
    cerebro.addstrategy(Probe)
    (strat,) = cerebro.run()
    return strat


@pytest.mark.parametrize("period", (1, 15, 31, 32, 48, 64, 128))
@pytest.mark.parametrize("offset", (0.0, 1e8), ids=("near-zero", "large-offset"))
def test_r71_159_sumn_runonce_matches_runnext_and_fsum_oracle(period, offset):
    values = _sample_values(320, offset=offset)
    expected = [
        float("nan") if i < period - 1 else math.fsum(values[i - period + 1 : i + 1])
        for i in range(len(values))
    ]

    runnext = _run_indicator(values, bt.indicators.SumN, period=period, runonce=False).raw_array
    runonce = _run_indicator(values, bt.indicators.SumN, period=period, runonce=True).raw_array

    _assert_bit_exact_sequence(runnext, expected)
    _assert_bit_exact_sequence(runonce, expected)
    _assert_bit_exact_sequence(runonce, runnext)


@pytest.mark.parametrize("period", (32, 64))
def test_r71_159_sumn_catastrophic_cancellation_and_nan_recovery(period):
    values = ([1e16, 1.0, -1e16, 0.125, -0.125, 1e-16, -1e-16, 3.0] * 30)[:240]
    values[70] = float("nan")
    values[160] = float("nan")

    expected = [
        float("nan") if i < period - 1 else math.fsum(values[i - period + 1 : i + 1])
        for i in range(len(values))
    ]
    runnext = _run_indicator(values, bt.indicators.SumN, period=period, runonce=False).raw_array
    runonce = _run_indicator(values, bt.indicators.SumN, period=period, runonce=True).raw_array

    _assert_bit_exact_sequence(runonce, expected)
    _assert_bit_exact_sequence(runonce, runnext)
    # Verify finite recovery after NaN exits the window.
    assert math.isfinite(runonce[70 + period])
    assert math.isfinite(runonce[160 + period])


def test_r71_159_sumn_upstream_warmup_nan_chunks_qbuffer_and_subclass_fallback():
    values = _sample_values(220, offset=50.0)

    # Upstream SMA produces 14 leading NaN bars.
    class UpstreamProbe(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=15)
            self.sumn = bt.indicators.SumN(self.sma, period=32)

        def stop(self):
            self.result = list(self.sumn.lines[0].array)

    def run_upstream(runonce):
        c = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
        c.adddata(_SyntheticFeed(input_values=values))
        c.addstrategy(UpstreamProbe)
        return c.run()[0].result

    _assert_bit_exact_sequence(run_upstream(True), run_upstream(False))

    # Arbitrary chunked once() calls match a single full pass bit-for-bit.
    full = _run_indicator(values, bt.indicators.SumN, period=32, runonce=True).raw_array
    strat = _run_indicator(values, bt.indicators.SumN, period=32, runonce=False)
    dst = strat.ind.lines[0].array
    for i in range(len(dst)):
        dst[i] = float("nan")
    for start, end in ((0, 10), (10, 31), (31, 32), (32, 100), (100, len(values))):
        strat.ind.once(start, end)
    _assert_bit_exact_sequence(list(dst), full)

    # QBuffer (exactbars=1) parity.
    q_strat = _run_indicator(values, bt.indicators.SumN, period=32, runonce=False, exactbars=1)
    _assert_bit_exact_sequence(q_strat.recorded, full)

    # Subclass and monkeypatched module global must not qualify for SumN fast path.
    calls = []

    def tracking_fsum(window):
        calls.append(len(window))
        return math.fsum(window)

    class CustomSumN(bt.indicators.SumN):
        func = staticmethod(tracking_fsum)

    sub_strat = _run_indicator(values[:90], CustomSumN, period=32, runonce=True)
    assert len(calls) >= 90 - 31
    _assert_bit_exact_sequence(sub_strat.raw_array, full[:90])

    # Raw array infinities (+inf, -inf -> ValueError -> nan) & recovery.
    inf_vals = _sample_values(140, offset=10.0)
    inf_vals[40] = float("inf")
    inf_vals[45] = float("-inf")
    inf_strat = _run_indicator(
        inf_vals, bt.indicators.SumN, period=32, runonce=True, raw_inf=True
    )
    assert math.isinf(inf_strat.raw_array[40])
    assert math.isnan(inf_strat.raw_array[45])
    assert math.isfinite(inf_strat.raw_array[45 + 32])


def test_r71_159_sumn_monkeypatch_cannot_requalify_subclass(monkeypatch):
    calls = []

    class SubSumN(bt.indicators.SumN):
        def __init__(self):
            super().__init__()

    orig_fsum = math.fsum

    def spy_fsum(w):
        calls.append(len(w))
        return orig_fsum(w)

    SubSumN.func = staticmethod(spy_fsum)
    monkeypatch.setattr(basicops_mod, "SumN", SubSumN)

    values = _sample_values(80, offset=10.0)
    _run_indicator(values, SubSumN, period=32, runonce=True)
    assert len(calls) >= 80 - 31


@pytest.mark.parametrize("ind_cls", (bt.indicators.AnyN, bt.indicators.AllN))
@pytest.mark.parametrize("period", (5, 32, 64))
def test_r71_159_anyn_alln_runonce_matches_runnext_with_special_floats(ind_cls, period):
    values = [0.0] * 140
    for idx in (0, 35, 36, 70, 100, 101, 102):
        values[idx] = 1.0
    values[10] = -0.0
    values[50] = float("nan")
    if ind_cls is bt.indicators.AllN:
        for idx in range(70, 140):
            values[idx] = 2.0
        values[95] = -0.0
        values[120] = float("nan")

    runnext = _run_indicator(values, ind_cls, period=period, runonce=False).raw_array
    runonce = _run_indicator(values, ind_cls, period=period, runonce=True).raw_array
    _assert_bit_exact_sequence(runonce, runnext)


# ===========================================================================
# R71-160: SMA & StandardDeviation rolling exact sums parity & boundaries
# ===========================================================================


@pytest.mark.parametrize("period", (1, 15, 16, 31, 32, 64, 128))
@pytest.mark.parametrize("offset", (0.0, 1e8), ids=("near-zero", "large-offset"))
def test_r71_160_sma_runonce_matches_runnext_and_fsum_oracle(period, offset):
    values = _sample_values(320, offset=offset)
    expected = [
        float("nan") if i < period - 1 else math.fsum(values[i - period + 1 : i + 1]) / period
        for i in range(len(values))
    ]

    runnext = _run_indicator(values, bt.indicators.SMA, period=period, runonce=False).raw_array
    runonce = _run_indicator(values, bt.indicators.SMA, period=period, runonce=True).raw_array

    _assert_bit_exact_sequence(runnext, expected)
    _assert_bit_exact_sequence(runonce, expected)
    _assert_bit_exact_sequence(runonce, runnext)


@pytest.mark.parametrize("period", (16, 32, 64))
def test_r71_160_sma_cancellation_nan_recovery_chunks_and_short_data(period):
    values = ([1e16, 1.0, -1e16, 0.125, -0.125, 1e-16, -1e-16, 3.0] * 30)[:240]
    values[65] = float("nan")
    values[150] = float("nan")

    expected = [
        float("nan") if i < period - 1 else math.fsum(values[i - period + 1 : i + 1]) / period
        for i in range(len(values))
    ]
    runnext = _run_indicator(values, bt.indicators.SMA, period=period, runonce=False).raw_array
    runonce = _run_indicator(values, bt.indicators.SMA, period=period, runonce=True).raw_array

    _assert_bit_exact_sequence(runonce, expected)
    _assert_bit_exact_sequence(runonce, runnext)
    assert math.isfinite(runonce[65 + period])
    assert math.isfinite(runonce[150 + period])

    # Chunked once() calls match full pass bit-for-bit.
    strat = _run_indicator(values, bt.indicators.SMA, period=period, runonce=False)
    dst = strat.ind.lines[0].array
    for i in range(len(dst)):
        dst[i] = float("nan")
    for start, end in ((0, 5), (5, period - 1), (period - 1, period + 2), (period + 2, len(values))):
        strat.ind.once(start, end)
    _assert_bit_exact_sequence(list(dst), expected)

    # Short data (len < period) stays all NaN in both modes.
    short_vals = _sample_values(max(1, period - 3), offset=10.0)
    short_once = _run_indicator(short_vals, bt.indicators.SMA, period=period, runonce=True).raw_array
    short_next = _run_indicator(short_vals, bt.indicators.SMA, period=period, runonce=False).raw_array
    assert all(math.isnan(v) for v in short_once)
    assert all(math.isnan(v) for v in short_next)


def test_r71_160_sma_upstream_indicator_inf_and_overflow_fallback():
    values = _sample_values(220, offset=50.0)

    class NestedSMA(bt.Strategy):
        def __init__(self):
            self.inner = bt.indicators.SMA(self.data.close, period=15)
            self.outer = bt.indicators.SMA(self.inner, period=40)

        def stop(self):
            self.result = list(self.outer.lines[0].array)

    def run_nested(runonce):
        c = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
        c.adddata(_SyntheticFeed(input_values=values))
        c.addstrategy(NestedSMA)
        return c.run()[0].result

    _assert_bit_exact_sequence(run_nested(True), run_nested(False))

    # Raw array with +inf, -inf, and nan inside the same window yields NaN cleanly.
    mixed = _sample_values(120, offset=10.0)
    mixed[40] = float("inf")
    mixed[42] = float("-inf")
    mixed[44] = float("nan")
    mixed_strat = _run_indicator(
        mixed, bt.indicators.SMA, period=32, runonce=True, raw_inf=True
    )
    assert math.isnan(mixed_strat.raw_array[44])
    assert math.isfinite(mixed_strat.raw_array[44 + 32])

    # Finite overflow propagates OverflowError consistently in both modes.
    ovf = [1e308] * 80
    for mode in (False, True):
        with pytest.raises(OverflowError):
            _run_indicator(ovf, bt.indicators.SMA, period=32, runonce=mode)
        with pytest.raises(OverflowError):
            _run_indicator(ovf, bt.indicators.SumN, period=32, runonce=mode)


@pytest.mark.parametrize("period", (8, 15, 16, 20, 32, 48, 64, 128))
@pytest.mark.parametrize("offset", (0.0, 1e8), ids=("near-zero", "large-offset"))
@pytest.mark.parametrize("safepow", (True, False), ids=("safepow", "nosafepow"))
def test_r71_160_stddev_default_and_medium_periods_exact_parity(period, offset, safepow):
    values = _sample_values(300, offset=offset)

    runnext = _run_indicator(
        values, bt.indicators.StandardDeviation, period=period, runonce=False, safepow=safepow
    ).raw_array
    runonce = _run_indicator(
        values, bt.indicators.StandardDeviation, period=period, runonce=True, safepow=safepow
    ).raw_array

    _assert_bit_exact_sequence(runonce, runnext)


def test_r71_160_stddev_period20_cancellation_nan_recovery_upstream_and_subclass():
    # Catastrophic cancellation + multiple interior NaN gaps at default period=20.
    values = ([1e16, 1.0, -1e16, 1.0] * 40) + _sample_values(100, offset=100.0)
    values[50] = float("nan")
    values[140] = float("nan")

    runnext = _run_indicator(
        values, bt.indicators.StandardDeviation, period=20, runonce=False
    ).raw_array
    runonce = _run_indicator(
        values, bt.indicators.StandardDeviation, period=20, runonce=True
    ).raw_array
    _assert_bit_exact_sequence(runonce, runnext)
    assert math.isfinite(runonce[50 + 20])
    assert math.isfinite(runonce[140 + 20])

    # Upstream SMA leading NaN warmup feeding StandardDeviation(period=20).
    class UpstreamStdDev(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=15)
            self.sd = bt.indicators.StandardDeviation(self.sma, period=20)

        def stop(self):
            self.result = list(self.sd.lines[0].array)

    def run_up(runonce):
        c = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
        c.adddata(_SyntheticFeed(input_values=_sample_values(160, offset=50.0)))
        c.addstrategy(UpstreamStdDev)
        return c.run()[0].result

    _assert_bit_exact_sequence(run_up(True), run_up(False))

    # Subclass overriding _finish at period=20 must stay on original per-window path.
    class CountingStdDev(deviation_mod.StandardDeviation):
        def __init__(self):
            self.calls = 0
            super().__init__()

        def _finish(self, meansq, mean):
            self.calls += 1
            return super()._finish(meansq, mean)

    sub_strat = _run_indicator(_sample_values(80), CountingStdDev, period=20, runonce=True)
    assert sub_strat.ind.calls >= 80 - 19
    ref = _run_indicator(_sample_values(80), bt.indicators.StandardDeviation, period=20, runonce=False)
    _assert_bit_exact_sequence(sub_strat.raw_array, ref.raw_array)
