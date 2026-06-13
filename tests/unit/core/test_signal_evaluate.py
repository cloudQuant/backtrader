#!/usr/bin/env python
"""Branch-level tests for SignalStrategy._evaluate_signals (R2-S6 scaffold).

``_evaluate_signals`` is a pure function: given the ``_signals`` dict (keyed by
the SIGNAL_* constants) plus the ``_longexit``/``_shortexit`` flags, it returns
the 10-tuple of decision booleans. The existing end-to-end test
(test_signal.py) only exercises SIGNAL_LONG, so this module covers every signal
type / inversion / "any" variant and the exit-invalidation logic, locking in
behavior before/after the helper extraction.
"""

import collections

import backtrader as bt
from backtrader.signal import (
    SIGNAL_LONG,
    SIGNAL_LONG_ANY,
    SIGNAL_LONG_INV,
    SIGNAL_LONGEXIT,
    SIGNAL_LONGEXIT_ANY,
    SIGNAL_LONGEXIT_INV,
    SIGNAL_LONGSHORT,
    SIGNAL_SHORT,
    SIGNAL_SHORT_ANY,
    SIGNAL_SHORT_INV,
    SIGNAL_SHORTEXIT,
    SIGNAL_SHORTEXIT_ANY,
    SIGNAL_SHORTEXIT_INV,
)


class _FakeSignalStrategy:
    """Minimal stand-in exposing just what _evaluate_signals reads.

    We bind the real unbound method so we test the actual implementation
    without constructing a full Cerebro/Strategy graph.
    """

    _evaluate_signals = bt.SignalStrategy._evaluate_signals
    _all_pos = staticmethod(bt.SignalStrategy._all_pos)
    _all_neg = staticmethod(bt.SignalStrategy._all_neg)
    _all_any = staticmethod(bt.SignalStrategy._all_any)

    def __init__(self, signals=None, longexit=False, shortexit=False):
        """Populate the fake ``_signals`` dict and the exit flags.

        Args:
            signals: Optional mapping of SIGNAL_* key to the list of
                values that ``_evaluate_signals`` will inspect.
            longexit: When ``True``, suppresses the implicit long
                reversal / long leave logic, mimicking a user-set
                explicit long exit.
            shortexit: When ``True``, suppresses the implicit short
                reversal / short leave logic.
        """
        # _signals is a defaultdict(list) in the real strategy; empty key -> [].
        self._signals = collections.defaultdict(list)
        if signals:
            for key, value in signals.items():
                self._signals[key] = value
        self._longexit = longexit
        self._shortexit = shortexit


# Result tuple index map for readability
(
    LS_LONG,
    LS_SHORT,
    L_ENTER,
    S_ENTER,
    L_EXIT,
    S_EXIT,
    L_REV,
    S_REV,
    L_LEAVE,
    S_LEAVE,
) = range(10)


def _eval(signals=None, longexit=False, shortexit=False):
    """Run the real ``_evaluate_signals`` against a fake strategy.

    Args:
        signals: Optional mapping of SIGNAL_* key to value list.
        longexit: Forwarded to the fake strategy.
        shortexit: Forwarded to the fake strategy.

    Returns:
        tuple: The 10-tuple of decision booleans produced by
        :meth:`SignalStrategy._evaluate_signals`.
    """
    obj = _FakeSignalStrategy(signals=signals, longexit=longexit, shortexit=shortexit)
    return obj._evaluate_signals()


def test_no_signals_all_false():
    """Empty signal input produces all-False decision tuple."""
    res = _eval()
    # With everything empty, nosig=[[0.0]] -> >0 False, <0 False, truthy False
    assert res == (False, False, False, False, False, False, False, False, False, False)


def test_longshort_positive_sets_ls_long():
    """Positive ``SIGNAL_LONGSHORT`` value flips the ``ls_long`` flag only."""
    res = _eval({SIGNAL_LONGSHORT: [[1.0]]})
    assert res[LS_LONG] is True
    assert res[LS_SHORT] is False


def test_longshort_negative_sets_ls_short():
    """Negative ``SIGNAL_LONGSHORT`` value flips the ``ls_short`` flag only."""
    res = _eval({SIGNAL_LONGSHORT: [[-1.0]]})
    assert res[LS_SHORT] is True
    assert res[LS_LONG] is False


def test_long_entry_direct():
    """Direct ``SIGNAL_LONG`` value sets ``L_ENTER`` and the implicit ``S_REV``."""
    res = _eval({SIGNAL_LONG: [[1.0]]})
    assert res[L_ENTER] is True
    # Long entry with no shortexit -> short reversal flag set
    assert res[S_REV] is True


def test_long_entry_inverted():
    """``SIGNAL_LONG_INV`` flips polarity: negative value triggers ``L_ENTER``."""
    # SIGNAL_LONG_INV triggers long entry when value < 0
    res = _eval({SIGNAL_LONG_INV: [[-1.0]]})
    assert res[L_ENTER] is True


def test_long_entry_any():
    """``SIGNAL_LONG_ANY`` fires on any truthy value, ignoring sign."""
    # SIGNAL_LONG_ANY triggers on any truthy value
    res = _eval({SIGNAL_LONG_ANY: [[0.5]]})
    assert res[L_ENTER] is True


def test_short_entry_direct():
    """Direct ``SIGNAL_SHORT`` value sets ``S_ENTER`` and the implicit ``L_REV``."""
    res = _eval({SIGNAL_SHORT: [[-1.0]]})
    assert res[S_ENTER] is True
    # Short entry with no longexit -> long reversal flag set
    assert res[L_REV] is True


def test_short_entry_inverted():
    """``SIGNAL_SHORT_INV`` flips polarity: positive value triggers ``S_ENTER``."""
    res = _eval({SIGNAL_SHORT_INV: [[1.0]]})
    assert res[S_ENTER] is True


def test_short_entry_any():
    """``SIGNAL_SHORT_ANY`` fires on any truthy value, ignoring sign."""
    res = _eval({SIGNAL_SHORT_ANY: [[0.3]]})
    assert res[S_ENTER] is True


def test_long_exit_variants():
    """``SIGNAL_LONGEXIT`` (and INV / ANY) set ``L_EXIT`` from any polarity."""
    assert _eval({SIGNAL_LONGEXIT: [[-1.0]]})[L_EXIT] is True
    assert _eval({SIGNAL_LONGEXIT_INV: [[1.0]]})[L_EXIT] is True
    assert _eval({SIGNAL_LONGEXIT_ANY: [[1.0]]})[L_EXIT] is True


def test_short_exit_variants():
    """``SIGNAL_SHORTEXIT`` (and INV / ANY) set ``S_EXIT`` from any polarity."""
    assert _eval({SIGNAL_SHORTEXIT: [[1.0]]})[S_EXIT] is True
    assert _eval({SIGNAL_SHORTEXIT_INV: [[-1.0]]})[S_EXIT] is True
    assert _eval({SIGNAL_SHORTEXIT_ANY: [[1.0]]})[S_EXIT] is True


def test_reversal_suppressed_by_explicit_exit():
    """When ``_longexit`` is set, a short entry must not set ``L_REV``."""
    # When a longexit signal collection exists, l_rev must be suppressed even
    # if a short entry fires.
    res = _eval({SIGNAL_SHORT: [[-1.0]]}, longexit=True)
    assert res[S_ENTER] is True
    assert res[L_REV] is False  # suppressed because _longexit is True


def test_reversal_suppressed_short_side():
    """When ``_shortexit`` is set, a long entry must not set ``S_REV``."""
    res = _eval({SIGNAL_LONG: [[1.0]]}, shortexit=True)
    assert res[L_ENTER] is True
    assert res[S_REV] is False


def test_long_leave_suppressed_when_longexit_present():
    """``L_LEAVE`` (opposite-signal exit) must be off when ``_longexit`` is set."""
    # l_leave (opposite-signal exit) must be disabled when _longexit is set.
    res = _eval({SIGNAL_LONG: [[-1.0]]}, longexit=True)
    assert res[L_LEAVE] is False


def test_long_leave_active_without_longexit():
    """Without ``_longexit``, a negative ``SIGNAL_LONG`` triggers ``L_LEAVE``."""
    # Without _longexit, a negative SIGNAL_LONG sets l_leave (leave the long).
    res = _eval({SIGNAL_LONG: [[-1.0]]}, longexit=False)
    assert res[L_LEAVE] is True


def test_short_leave_suppressed_when_shortexit_present():
    """``S_LEAVE`` must be off when ``_shortexit`` is set."""
    res = _eval({SIGNAL_SHORT: [[1.0]]}, shortexit=True)
    assert res[S_LEAVE] is False


def test_short_leave_active_without_shortexit():
    """Without ``_shortexit``, a positive ``SIGNAL_SHORT`` triggers ``S_LEAVE``."""
    res = _eval({SIGNAL_SHORT: [[1.0]]}, shortexit=False)
    assert res[S_LEAVE] is True


def test_all_helpers_empty_use_nosig():
    """``_all_pos`` / ``_all_neg`` / ``_all_any`` fall back to ``nosig`` when empty.

    When the signal list is empty the helper is expected to consult
    ``nosig`` (defaulting to ``[[0.0]]``), so all three return
    ``False``. When the list contains a positive / negative /
    truthy value the corresponding helper returns ``True``.
    """
    # The three static helpers fall back to nosig when the signal list is empty.
    nosig = [[0.0]]
    assert bt.SignalStrategy._all_pos([], nosig) is False
    assert bt.SignalStrategy._all_neg([], nosig) is False
    assert bt.SignalStrategy._all_any([], nosig) is False
    assert bt.SignalStrategy._all_pos([[1.0]], nosig) is True
    assert bt.SignalStrategy._all_neg([[-1.0]], nosig) is True
    assert bt.SignalStrategy._all_any([[2.0]], nosig) is True
