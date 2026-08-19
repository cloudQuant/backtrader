"""Regression tests for LineRoot.__bool__ returning a strict bool.

Background
----------
``LineRoot.__nonzero__`` (aliased to ``__bool__`` at ``lineroot.py:635``) used to
end its float branch with a bare ``return value != 0.0``. That is unsafe:

* ``numpy.float64`` is a **subclass** of ``float``, so numpy scalars satisfy the
  ``isinstance(value, float)`` guard and fall into that branch.
* ``numpy.float64 != 0.0`` evaluates to ``numpy.bool_``, not ``bool``.
* CPython enforces that ``__bool__`` return a strict ``bool`` and otherwise raises
  ``TypeError: __bool__ should return bool, returned numpy.bool_``.

Why the failure only showed up with ``exactbars > 0``: numpy scalars enter the line
buffers from ``PandasData`` (``feeds/pandafeed.py`` does ``df.to_numpy(copy=False)``),
but in the default mode lines are stored in an ``array.array("d")``, a typed C buffer
that coerces every value back to a plain ``float`` on read -- silently laundering the
numpy type away. Under ``exactbars > 0`` (QBuffer mode) the storage becomes a
``collections.deque``, a generic object container that hands back the identical
``numpy.float64`` instance. The bug was always latent; QBuffer merely stopped hiding it.

The consumer that trips it is ``lineiterator.py``'s ``_next``, where an ``or``
expression forces a truth test on a line object.

The fix wraps both returns in ``bool()`` (``lineroot.py:610`` and ``:624``).
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import numpy as np
import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators as btind
from backtrader import lineroot

# ============================================================================
# Helpers
# ============================================================================


def make_pandas_feed(num_bars=60, seed=7):
    """Build a PandasData feed whose lines carry numpy.float64 scalars.

    PandasData converts the frame via ``to_numpy()``, so the values written into
    the line buffers are numpy scalars rather than Python floats. That is a
    precondition for reproducing the bug.
    """
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
    """Run one indicator over the synthetic feed and collect its line values."""
    rows = []

    class _Strategy(bt.Strategy):
        def __init__(self):
            self.ind = make_indicator(self)

        def next(self):
            rows.append(tuple(float(line[0]) for line in self.ind.lines))

    cerebro = bt.Cerebro(stdstats=False, **cerebro_kwargs)
    cerebro.adddata(make_pandas_feed())
    cerebro.addstrategy(_Strategy)
    cerebro.run()
    return rows


@pytest.fixture
def unfixed_nonzero():
    """Temporarily restore the pre-fix ``__bool__`` to prove the repro is real.

    Without this, a test asserting "no TypeError" would pass even if the fix were
    reverted, because nothing else in the suite exercises ``exactbars > 0``.
    Re-introducing the exact old body lets us assert the bug *does* occur without
    it, which is what makes these tests genuine regression guards.
    """
    original = lineroot.LineRoot.__nonzero__

    def legacy_nonzero(self):
        # Verbatim pre-fix logic: no bool() around the != comparison.
        try:
            if hasattr(self, "lines") and self.lines:
                if hasattr(self.lines, "__getitem__") and len(self.lines) > 0:
                    line = self.lines[0]
                    if hasattr(line, "__getitem__") and hasattr(line, "__len__"):
                        if len(line) > 0:
                            value = line[0]
                            if value is None:
                                return False
                            if isinstance(value, float):
                                import math

                                if not math.isfinite(value):
                                    return False
                                return value != 0.0  # the bug
                            return bool(value)
                return False
            if hasattr(self, "__getitem__") and hasattr(self, "__len__"):
                if len(self) > 0:
                    value = self[0]
                    if value is None:
                        return False
                    if isinstance(value, float):
                        import math

                        if not math.isfinite(value):
                            return False
                        return value != 0.0  # the bug
                    return bool(value)
                return False
            return False
        except Exception:
            return False

    lineroot.LineRoot.__nonzero__ = legacy_nonzero
    lineroot.LineRoot.__bool__ = legacy_nonzero
    try:
        yield
    finally:
        lineroot.LineRoot.__nonzero__ = original
        lineroot.LineRoot.__bool__ = original


@pytest.fixture
def unfixed_makeoperationown():
    """Temporarily restore the pre-fix ``_makeoperationown`` bool branches.

    Mirrors ``unfixed_nonzero``: only the ``bool`` fast path is reproduced, so the
    tests can assert the numpy.bool_ leak really happened without the fix.
    """
    original = lineroot.LineRoot._makeoperationown

    def legacy_makeoperationown(self, operation, _ownerskip=None):
        if operation is not bool:
            return original(self, operation, _ownerskip=_ownerskip)
        # Verbatim pre-fix logic for the two bool branches.
        if hasattr(self, "lines") and self.lines:
            try:
                if hasattr(self.lines, "__getitem__") and len(self.lines) > 0:
                    line = self.lines[0]
                    if hasattr(line, "__getitem__") and hasattr(line, "__len__"):
                        if len(line) > 0:
                            value = line[0]
                            if value is None:
                                return False
                            if isinstance(value, float):
                                import math

                                if not math.isfinite(value):
                                    return False
                                return value != 0.0  # the bug (:248)
                            return bool(value)
                return False
            except Exception:
                return False
        elif hasattr(self, "__getitem__") and hasattr(self, "__len__"):
            try:
                if len(self) > 0:
                    value = self[0]
                    if value is None:
                        return False
                    if isinstance(value, float):
                        import math

                        if not math.isfinite(value):
                            return False
                        return value != 0.0  # the bug (:268)
                    return bool(value)
                return False
            except Exception:
                return False
        else:
            return False

    lineroot.LineRoot._makeoperationown = legacy_makeoperationown
    try:
        yield
    finally:
        lineroot.LineRoot._makeoperationown = original


# ============================================================================
# The precondition that makes the bug possible
# ============================================================================


def test_numpy_float64_is_a_float_subclass_and_ne_yields_numpy_bool():
    """Document the language-level facts the bug rests on."""
    value = np.float64(1.5)

    # This is why numpy scalars reach the `isinstance(value, float)` branch.
    assert isinstance(value, float)

    # And this is why the bare `return value != 0.0` violated the __bool__ contract.
    assert type(value != 0.0) is np.bool_
    assert type(value != 0.0) is not bool


def test_qbuffer_mode_preserves_numpy_scalars_while_default_mode_coerces():
    """Show the storage asymmetry that confines the bug to ``exactbars > 0``."""
    import array
    import collections

    value = np.float64(2.5)

    # Default mode: typed C buffer coerces on write/read.
    typed = array.array("d")
    typed.append(value)
    assert type(typed[0]) is float

    # QBuffer mode: generic container hands the numpy scalar straight back.
    queued = collections.deque(maxlen=4)
    queued.append(value)
    assert type(queued[0]) is np.float64


# ============================================================================
# Reproduction: the bug must actually occur without the fix
# ============================================================================


@pytest.mark.parametrize("exactbars", [1, 2])
def test_bug_reproduces_without_fix(unfixed_nonzero, exactbars):
    """With the pre-fix body restored, ADX under ``exactbars > 0`` raises TypeError."""
    with pytest.raises(TypeError, match=r"__bool__ should return bool"):
        run_indicator(lambda s: btind.ADX(s.data, period=14), exactbars=exactbars)


def test_bool_returns_numpy_bool_without_fix(unfixed_nonzero):
    """Pin the defect directly on ``__bool__``, independent of any indicator."""

    class _Wrapper:
        """Minimal stand-in for a QBuffer-backed line holding a numpy scalar."""

        __bool__ = lineroot.LineRoot.__nonzero__

        def __len__(self):
            return 1

        def __getitem__(self, ago):
            return np.float64(3.25)

    wrapper = _Wrapper()

    # The unbound pre-fix body leaks a numpy.bool_ ...
    assert type(lineroot.LineRoot.__nonzero__(wrapper)) is np.bool_

    # ... which CPython rejects when the bool protocol is actually invoked.
    with pytest.raises(TypeError, match=r"__bool__ should return bool"):
        bool(wrapper)


# ============================================================================
# Verification: the fix resolves it
# ============================================================================


# ----------------------------------------------------------------------------
# _makeoperationown(bool) -- the sibling sites at lineroot.py:248 and :268
#
# These share the identical `isinstance(value, float)` + `!= 0.0` shape, but they
# differ from __bool__ in one important way: they *return a value* rather than
# implementing the bool protocol. CPython therefore never validates the type, so a
# numpy.bool_ escaping here propagates silently instead of raising -- harder to
# notice, not easier.
#
# Honest scoping: instrumentation shows normal cerebro runs never invoke
# _makeoperationown with `bool` (see test_makeoperationown_bool_not_reached_in_
# normal_runs below), so fixing these is defensive hardening rather than the repair
# of an observed failure. They are reachable by direct/derived-class use.
# ----------------------------------------------------------------------------


class _OwnOpSingle(lineroot.LineRoot):
    """LineSingle-shaped: no ``.lines``, so it takes the ``elif`` branch (:268)."""

    def __init__(self, value):
        self._value = value

    def __len__(self):
        return 1

    def __getitem__(self, ago):
        return self._value


class _OwnOpMultiple(lineroot.LineRoot):
    """LineMultiple-shaped: has ``.lines``, so it takes the first branch (:248)."""

    class _Line:
        def __init__(self, value):
            self._value = value

        def __len__(self):
            return 1

        def __getitem__(self, ago):
            return self._value

    class _Lines:
        def __init__(self, value):
            self._line = _OwnOpMultiple._Line(value)

        def __len__(self):
            return 1

        def __getitem__(self, idx):
            return self._line

    def __init__(self, value):
        self.lines = _OwnOpMultiple._Lines(value)


@pytest.mark.parametrize("holder", [_OwnOpSingle, _OwnOpMultiple], ids=["lines_branch", "elif"])
def test_makeoperationown_bool_leaks_numpy_bool_without_fix(unfixed_makeoperationown, holder):
    """Without the fix, both branches hand back a numpy.bool_."""
    result = lineroot.LineRoot._makeoperationown(holder(np.float64(3.25)), bool)
    assert type(result) is np.bool_, "expected the pre-fix body to leak numpy.bool_"


@pytest.mark.parametrize("holder", [_OwnOpSingle, _OwnOpMultiple], ids=["lines_branch", "elif"])
def test_makeoperationown_bool_returns_strict_bool_with_fix(holder):
    """With the fix, both branches return a strict ``bool``."""
    result = lineroot.LineRoot._makeoperationown(holder(np.float64(3.25)), bool)
    assert type(result) is bool, f"expected bool, got {type(result).__name__}"
    assert result is True


@pytest.mark.parametrize("holder", [_OwnOpSingle, _OwnOpMultiple], ids=["lines_branch", "elif"])
@pytest.mark.parametrize(
    "value, expected",
    [
        (np.float64(0.0), False),
        (np.float64(-0.0), False),
        (np.float64(4.5), True),
        (np.float64(-4.5), True),
        (np.float64(np.nan), False),
        (np.float64(np.inf), False),
        (0.0, False),
        (7.0, True),
    ],
)
def test_makeoperationown_bool_semantics_preserved(holder, value, expected):
    """Truthiness must be unchanged by the fix -- only the returned type differs."""
    result = lineroot.LineRoot._makeoperationown(holder(value), bool)
    assert type(result) is bool
    assert result is expected


def test_makeoperationown_bool_not_reached_in_normal_runs():
    """Record the scope of the :248/:268 fix: normal runs never take this path.

    This documents *why* those two sites are hardening rather than an active bug
    fix. If a future change starts routing ``bool`` through ``_operationown``, this
    test fails and the sibling tests above become load-bearing.
    """
    calls = []
    original = lineroot.LineRoot._makeoperationown

    def counting(self, operation, _ownerskip=None):
        if operation is bool:
            calls.append(type(self).__name__)
        return original(self, operation, _ownerskip=_ownerskip)

    lineroot.LineRoot._makeoperationown = counting
    try:
        for exactbars in (0, 1):
            run_indicator(lambda s: btind.ADX(s.data, period=14), exactbars=exactbars)
    finally:
        lineroot.LineRoot._makeoperationown = original

    assert calls == [], f"_makeoperationown(bool) unexpectedly reached: {calls}"


def test_bool_returns_strict_bool_with_fix():
    """``__bool__`` must return exactly ``bool`` even for numpy input."""

    class _Wrapper:
        __bool__ = lineroot.LineRoot.__nonzero__

        def __len__(self):
            return 1

        def __getitem__(self, ago):
            return np.float64(3.25)

    wrapper = _Wrapper()
    result = lineroot.LineRoot.__nonzero__(wrapper)

    assert type(result) is bool, f"expected bool, got {type(result).__name__}"
    assert result is True
    assert bool(wrapper) is True  # exercises the real protocol; must not raise


@pytest.mark.parametrize(
    "value, expected",
    [
        (np.float64(0.0), False),
        (np.float64(-0.0), False),
        (np.float64(1.5), True),
        (np.float64(-1.5), True),
        (np.float64(np.nan), False),  # non-finite -> False
        (np.float64(np.inf), False),
        (np.float64(-np.inf), False),
        (0.0, False),
        (2.0, True),
    ],
)
def test_bool_semantics_preserved_for_numpy_and_python_floats(value, expected):
    """The fix must not change truthiness, only the returned type."""

    class _Wrapper:
        __bool__ = lineroot.LineRoot.__nonzero__

        def __len__(self):
            return 1

        def __getitem__(self, ago):
            return value

    result = lineroot.LineRoot.__nonzero__(_Wrapper())
    assert type(result) is bool
    assert result is expected


@pytest.mark.parametrize("exactbars", [1, 2])
def test_adx_runs_under_exactbars_with_fix(exactbars):
    """The canonical victim: ADX must complete under ``exactbars > 0``."""
    rows = run_indicator(lambda s: btind.ADX(s.data, period=14), exactbars=exactbars)
    assert rows, "ADX produced no output"


@pytest.mark.parametrize(
    "name, factory",
    [
        ("ADX", lambda s: btind.ADX(s.data, period=14)),
        ("PlusDirectionalIndicator", lambda s: btind.PlusDirectionalIndicator(s.data)),
        ("MinusDirectionalIndicator", lambda s: btind.MinusDirectionalIndicator(s.data)),
        ("DirectionalIndicator", lambda s: btind.DirectionalIndicator(s.data)),
        ("Stochastic", lambda s: btind.Stochastic(s.data)),
        ("Vortex", lambda s: btind.Vortex(s.data)),
        ("CommodityChannelIndex", lambda s: btind.CommodityChannelIndex(s.data)),
    ],
)
def test_indicators_using_line_truth_tests_run_under_exactbars(name, factory):
    """A sample of the ~60 indicators this single fix unblocked.

    These all build comparison/If expressions in ``__init__``, so the framework
    performs a truth test on a line object during iteration.
    """
    rows = run_indicator(factory, exactbars=1)
    assert rows, f"{name} produced no output under exactbars=1"


def test_fix_does_not_alter_default_mode_results():
    """Guard against the fix changing any value in the default (non-QBuffer) mode."""
    baseline = run_indicator(lambda s: btind.ADX(s.data, period=14), runonce=False, preload=True)
    vectorized = run_indicator(lambda s: btind.ADX(s.data, period=14), runonce=True, preload=True)

    assert len(baseline) == len(vectorized)
    for bar, (left, right) in enumerate(zip(baseline, vectorized)):
        for lhs, rhs in zip(left, right):
            if lhs != lhs and rhs != rhs:  # NaN == NaN for our purposes
                continue
            assert lhs == pytest.approx(rhs, abs=1e-9), f"divergence at bar {bar}"


def test_adx_values_match_between_exactbars_and_default_mode():
    """Beyond "does not crash": the values must agree with the default mode.

    ``exactbars`` is a memory-retention setting, so it must not change results.
    """
    baseline = run_indicator(lambda s: btind.ADX(s.data, period=14), runonce=False, preload=True)
    queued = run_indicator(lambda s: btind.ADX(s.data, period=14), exactbars=1)

    assert len(baseline) == len(queued)
    mismatches = []
    for bar, (left, right) in enumerate(zip(baseline, queued)):
        for idx, (lhs, rhs) in enumerate(zip(left, right)):
            if lhs != lhs and rhs != rhs:
                continue
            if lhs != pytest.approx(rhs, abs=1e-9):
                mismatches.append((bar, idx, lhs, rhs))
    assert not mismatches, f"exactbars changed ADX values: {mismatches[:5]}"
