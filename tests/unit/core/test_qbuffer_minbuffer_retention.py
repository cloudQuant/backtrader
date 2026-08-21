"""Regression tests for QBuffer retention of self-referential indicator lines.

Background
----------
``LineBuffer.qbuffer`` sizes the ring buffer from the **line's own** ``_minperiod``::

    self.maxlen = max(1, self._minperiod)          # linebuffer.py:329

but a line's ``_minperiod`` only ever leaves 1 if the indicator calls
``addminperiod()`` or ``line.updateminperiod()``. Many indicators never call either,
so their *object* ``_minperiod`` may be 40 while every *line* is still 1.

Under ``exactbars > 0`` (QBuffer mode) that produced ``maxlen == 1``. Any indicator
that reads its own previous output -- ``self.lines.x[-1]``, which every cumulative or
stateful indicator does -- then read a slot that had already been overwritten and got
NaN back. No exception: the values were silently wrong. ``HeikinAshi`` for instance
returned NaN for ``ha_open`` on every bar after the first, which in turn made
``max(high, nan, ha_close)`` collapse ``ha_high``/``ha_low`` onto the raw high/low.

The fix (``lineiterator.py``, in ``LineIterator.qbuffer``) asks each line to retain
enough history for the owning object's lookback, with a floor of 2 for the ``[-1]``
self-reference::

    line.minbuffer(max(2, self._minperiod))

Why ``minbuffer`` and not ``addminperiod``/``updateminperiod``
--------------------------------------------------------------
``_minperiod`` is a *semantic* claim ("no valid value before bar N") that downstream
indicators use to derive their own minperiod. Buffer retention is a separate concern.
Measured on ``HeikinAshi``:

* ``addminperiod(2)`` -- fixes exactbars but **drops an output bar** (60 -> 59).
* ``updateminperiod(2)`` -- fixes exactbars, output unchanged, but **leaks**: a
  downstream ``SMA(ha_close, period=5)`` had its minperiod pushed from 5 to 6.
* ``minbuffer(2)`` -- fixes exactbars, output unchanged, no leak. Chosen.

``minbuffer`` only grows ``maxlen`` in QBuffer mode and returns immediately otherwise
(``linebuffer.py:355-356``), so it cannot affect the default execution path at all.

These tests are companions to ``test_lineroot_bool_numpy.py``, which covers the other
``exactbars`` defect (``numpy.bool_`` escaping ``__bool__``).
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import numpy as np
import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators as btind
from backtrader import lineiterator

# ============================================================================
# Helpers
# ============================================================================

# Indicators that read their own line(s) recursively and therefore need at least
# two retained slots. Each was verified to produce wrong values before the fix.
SELF_REFERENTIAL = [
    ("HeikinAshi", lambda s: btind.HeikinAshi(s.data)),
    ("Accum", lambda s: btind.Accum(s.data.volume)),
    ("KST", lambda s: btind.KST(s.data.close)),
    ("TrixSignal", lambda s: btind.TrixSignal(s.data.close)),
    ("PPO", lambda s: btind.PPO(s.data.close)),
    ("SuperTrendIndicator", lambda s: btind.SuperTrendIndicator(s.data)),
    ("SupertrendIndicator", lambda s: btind.SupertrendIndicator(s.data)),
    ("AdaptiveSuperTrendIndicator", lambda s: btind.AdaptiveSuperTrendIndicator(s.data)),
    ("AccumulationDistributionLine", lambda s: btind.AccumulationDistributionLine(s.data)),
]

# Indicators already correct before the fix (they call addminperiod, so their lines
# carried a real minperiod). Included to prove the fix changes nothing for them.
ALREADY_CORRECT = [
    ("MACD", lambda s: btind.MACD(s.data.close)),
    ("SMA", lambda s: btind.SMA(s.data.close, period=20)),
    ("EMA", lambda s: btind.EMA(s.data.close, period=20)),
    ("ATR", lambda s: btind.ATR(s.data, period=14)),
    ("ParabolicSAR", lambda s: btind.ParabolicSAR(s.data)),
    ("BollingerBands", lambda s: btind.BollingerBands(s.data.close)),
    ("Ichimoku", lambda s: btind.Ichimoku(s.data)),
    ("SuperTrendBandsIndicator", lambda s: btind.SuperTrendBandsIndicator(s.data)),
]


def make_feed(num_bars=60, seed=7):
    """Build a deterministic OHLCV feed."""
    index = pd.date_range("2020-01-01", periods=num_bars, freq="D")
    rng = np.random.RandomState(seed)
    close = pd.Series(np.cumsum(rng.randn(num_bars)) * 2 + 100, index=index)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.concat([open_, close], axis=1).max(axis=1) + np.abs(rng.randn(num_bars))
    low = pd.concat([open_, close], axis=1).min(axis=1) - np.abs(rng.randn(num_bars))
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.randint(100, 9999, num_bars).astype(float),
            "openinterest": 0.0,
        },
        index=index,
    )
    return bt.feeds.PandasData(dataname=frame)


def run_indicator(make_indicator, **cerebro_kwargs):
    """Run one indicator and return (rows, introspection) for its lines."""
    rows = []
    info = {}

    class _Strategy(bt.Strategy):
        def __init__(self):
            self.ind = make_indicator(self)

        def next(self):
            rows.append(tuple(float(line[0]) for line in self.ind.lines))

        def stop(self):
            info["object_minperiod"] = self.ind._minperiod
            info["line_minperiods"] = [line._minperiod for line in self.ind.lines]
            info["line_maxlens"] = [getattr(line, "maxlen", None) for line in self.ind.lines]

    cerebro = bt.Cerebro(stdstats=False, **cerebro_kwargs)
    cerebro.adddata(make_feed())
    cerebro.addstrategy(_Strategy)
    cerebro.run()
    return rows, info


def count_mismatches(left, right):
    """Count differing cells between two row lists, treating NaN == NaN."""
    if len(left) != len(right):
        return [("length", len(left), len(right))]
    bad = []
    for bar, (row_l, row_r) in enumerate(zip(left, right)):
        for idx, (lhs, rhs) in enumerate(zip(row_l, row_r)):
            nan_l, nan_r = lhs != lhs, rhs != rhs
            if nan_l != nan_r:
                bad.append((bar, idx, lhs, rhs))
            elif not nan_l and abs(lhs - rhs) > 1e-9 * max(1.0, abs(lhs), abs(rhs)):
                bad.append((bar, idx, lhs, rhs))
    return bad


@pytest.fixture
def unfixed_qbuffer():
    """Restore the pre-fix ``LineIterator.qbuffer`` so the bug can be observed.

    Nothing else in the suite exercises ``exactbars > 0``, so without this a test
    asserting "values agree" would still pass if the fix were reverted.
    """
    original = lineiterator.LineIterator.qbuffer

    def legacy_qbuffer(self, savemem=0):
        # Verbatim pre-fix body: no minbuffer() call.
        if savemem:
            for line in self.lines:
                line.qbuffer()
        for obj in self._lineiterators[self.IndType]:
            obj.qbuffer(savemem=1)
        for data in self.datas:
            data.minbuffer(self._minperiod)

    lineiterator.LineIterator.qbuffer = legacy_qbuffer
    try:
        yield
    finally:
        lineiterator.LineIterator.qbuffer = original


# ============================================================================
# The mechanism
# ============================================================================


def test_line_minperiod_can_lag_behind_object_minperiod():
    """Document the root cause: lines do not inherit the object's minperiod.

    This asymmetry is what made ``qbuffer`` under-size the ring buffer.
    """
    _, info = run_indicator(lambda s: btind.KST(s.data.close), runonce=False, preload=True)

    assert info["object_minperiod"] > 1, "KST should need substantial warmup"
    assert info["line_minperiods"] == [1, 1], (
        "KST never calls addminperiod/updateminperiod, so its lines stay at 1 -- "
        "this is precisely why qbuffer used to compute maxlen == 1"
    )


def test_minbuffer_is_a_noop_outside_qbuffer_mode():
    """``minbuffer`` cannot affect the default path, which is why it is safe here."""
    from backtrader.linebuffer import LineBuffer

    buffer = LineBuffer()
    assert buffer.mode != LineBuffer.QBuffer

    buffer.minbuffer(64)

    assert buffer.mode != LineBuffer.QBuffer, "minbuffer must not switch storage mode"
    assert buffer._minperiod == 1, "minbuffer must never touch _minperiod"


@pytest.mark.parametrize("name, factory", SELF_REFERENTIAL, ids=[n for n, _ in SELF_REFERENTIAL])
def test_retention_covers_lookback_after_fix(name, factory):
    """Every self-referential line must retain at least 2 bars under exactbars."""
    _, info = run_indicator(factory, exactbars=1)

    for idx, maxlen in enumerate(info["line_maxlens"]):
        assert maxlen is not None, f"{name} line {idx} is not in QBuffer mode"
        assert maxlen >= 2, f"{name} line {idx} retains only {maxlen} bar(s)"


@pytest.mark.parametrize("name, factory", SELF_REFERENTIAL, ids=[n for n, _ in SELF_REFERENTIAL])
def test_fix_does_not_raise_line_minperiod(name, factory):
    """The fix must grow retention only -- never the semantic ``_minperiod``.

    Guards against regressing to ``updateminperiod``, which over-delays consumers.
    """
    _, baseline = run_indicator(factory, runonce=False, preload=True)
    _, queued = run_indicator(factory, exactbars=1)

    assert queued["line_minperiods"] == baseline["line_minperiods"], (
        f"{name}: exactbars changed line minperiods from "
        f"{baseline['line_minperiods']} to {queued['line_minperiods']}"
    )
    assert queued["object_minperiod"] == baseline["object_minperiod"]


# ============================================================================
# Reproduction: the bug must actually occur without the fix
# ============================================================================


@pytest.mark.parametrize("name, factory", SELF_REFERENTIAL, ids=[n for n, _ in SELF_REFERENTIAL])
def test_bug_reproduces_without_fix(unfixed_qbuffer, name, factory):
    """Without the fix, exactbars silently changes these indicators' values."""
    baseline, _ = run_indicator(factory, runonce=False, preload=True)
    queued, info = run_indicator(factory, exactbars=1)

    assert min(info["line_maxlens"]) == 1, (
        f"{name}: expected the pre-fix body to leave maxlen == 1 " f"(got {info['line_maxlens']})"
    )
    assert count_mismatches(
        baseline, queued
    ), f"{name}: expected exactbars to corrupt values without the fix"


def test_heikinashi_ha_open_is_all_nan_without_fix(unfixed_qbuffer):
    """Pin the concrete symptom: the recursive line degrades to NaN."""
    rows, _ = run_indicator(lambda s: btind.HeikinAshi(s.data), exactbars=1)

    # ha_open is lines[0]; bar 0 is seeded, every later bar reads ha_open[-1].
    later_ha_open = [row[0] for row in rows[1:]]
    assert later_ha_open, "expected more than one bar of output"
    assert all(
        value != value for value in later_ha_open
    ), "expected every post-seed ha_open to be NaN without the fix"


# ============================================================================
# Verification: the fix resolves it
# ============================================================================


@pytest.mark.parametrize("name, factory", SELF_REFERENTIAL, ids=[n for n, _ in SELF_REFERENTIAL])
@pytest.mark.parametrize("exactbars", [1, 2])
def test_exactbars_matches_default_mode_after_fix(name, factory, exactbars):
    """``exactbars`` is a memory setting: results must be identical to the default."""
    baseline, _ = run_indicator(factory, runonce=False, preload=True)
    queued, _ = run_indicator(factory, exactbars=exactbars)

    mismatches = count_mismatches(baseline, queued)
    assert not mismatches, (
        f"{name}: exactbars={exactbars} changed {len(mismatches)} cell(s); "
        f"first few: {mismatches[:5]}"
    )


def test_heikinashi_produces_real_values_after_fix():
    """The counterpart to the all-NaN reproduction above."""
    rows, _ = run_indicator(lambda s: btind.HeikinAshi(s.data), exactbars=1)

    later_ha_open = [row[0] for row in rows[1:]]
    assert later_ha_open
    assert all(value == value for value in later_ha_open), "ha_open still contains NaN"


def test_heikinashi_high_low_not_collapsed_onto_raw_bars():
    """A NaN ha_open used to make max()/min() silently fall back to the raw high/low.

    Verifying only ha_open would miss this knock-on corruption.
    """
    rows, _ = run_indicator(lambda s: btind.HeikinAshi(s.data), exactbars=1)
    baseline, _ = run_indicator(lambda s: btind.HeikinAshi(s.data), runonce=False, preload=True)

    # lines are (ha_open, ha_high, ha_low, ha_close)
    assert not count_mismatches([r[1:3] for r in baseline], [r[1:3] for r in rows])


@pytest.mark.parametrize("name, factory", ALREADY_CORRECT, ids=[n for n, _ in ALREADY_CORRECT])
def test_previously_correct_indicators_are_unchanged(name, factory):
    """Regression guard: indicators that already worked must be untouched."""
    baseline, _ = run_indicator(factory, runonce=False, preload=True)
    queued, _ = run_indicator(factory, exactbars=1)

    mismatches = count_mismatches(baseline, queued)
    assert not mismatches, f"{name}: fix perturbed a previously correct indicator: {mismatches[:5]}"


def test_downstream_consumer_minperiod_not_inflated():
    """The decisive difference from ``updateminperiod``.

    A consumer of a fixed indicator's line must keep its own natural minperiod;
    an SMA of period 5 needs 5 bars, not 6.
    """
    captured = {}

    class _Strategy(bt.Strategy):
        def __init__(self):
            self.ha = btind.HeikinAshi(self.data)
            self.sma = btind.SMA(self.ha.lines.ha_close, period=5)

        def stop(self):
            captured["sma_minperiod"] = self.sma._minperiod

    for kwargs in ({"runonce": False, "preload": True}, {"exactbars": 1}):
        cerebro = bt.Cerebro(stdstats=False, **kwargs)
        cerebro.adddata(make_feed())
        cerebro.addstrategy(_Strategy)
        cerebro.run()
        assert captured["sma_minperiod"] == 5, (
            f"SMA(period=5) minperiod became {captured['sma_minperiod']} with {kwargs}; "
            "retention must not leak into minperiod semantics"
        )


def test_default_mode_results_are_untouched_by_the_fix():
    """Compare fixed vs pre-fix code in the DEFAULT mode: must be bit-identical.

    ``minbuffer`` returns early outside QBuffer mode, so the non-exactbars path
    cannot change. This asserts that directly rather than assuming it.
    """

    def collect():
        return (
            run_indicator(lambda s: btind.HeikinAshi(s.data), runonce=False, preload=True)[0],
            run_indicator(lambda s: btind.HeikinAshi(s.data), runonce=True, preload=True)[0],
        )

    # Capture the real (fixed) implementation BEFORE swapping anything in, so the
    # comparison is genuinely fixed-vs-legacy rather than legacy-vs-legacy.
    fixed_impl = lineiterator.LineIterator.qbuffer
    fixed_next, fixed_once = collect()

    def legacy_qbuffer(self, savemem=0):
        if savemem:
            for line in self.lines:
                line.qbuffer()
        for obj in self._lineiterators[self.IndType]:
            obj.qbuffer(savemem=1)
        for data in self.datas:
            data.minbuffer(self._minperiod)

    lineiterator.LineIterator.qbuffer = legacy_qbuffer
    try:
        assert lineiterator.LineIterator.qbuffer is not fixed_impl, "swap did not take effect"
        legacy_next, legacy_once = collect()
    finally:
        lineiterator.LineIterator.qbuffer = fixed_impl

    assert not count_mismatches(legacy_next, fixed_next)
    assert not count_mismatches(legacy_once, fixed_once)
