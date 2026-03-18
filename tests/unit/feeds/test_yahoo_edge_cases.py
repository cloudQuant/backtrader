"""Regression tests for Yahoo Finance feed edge cases."""

from datetime import time
from unittest.mock import MagicMock


def _make_yahoo_feed(adjclose=False, adjvolume=False):
    """Create a minimal YahooFinanceCSVData instance for unit testing."""
    from backtrader.feeds.yahoo import YahooFinanceCSVData

    feed = object.__new__(YahooFinanceCSVData)
    feed.params = feed.p = MagicMock()
    feed.p.swapcloses = False
    feed.p.adjclose = adjclose
    feed.p.adjvolume = adjvolume
    feed.p.round = False
    feed.p.roundvolume = 0
    feed.p.sessionend = time(23, 59, 59)
    feed.lines = MagicMock()
    return feed


def test_yahoo_adjfactor_zero_adjustedclose():
    """Regression: YahooFinanceCSVData._loadline must not crash with
    ZeroDivisionError when adjustedclose is 0.0.

    Before the fix, ``adjfactor = c / adjustedclose`` would raise
    ZeroDivisionError.  The fix falls back to adjfactor=1.0 (no adjustment).
    """
    feed = _make_yahoo_feed(adjclose=False)

    # Token list: date, open, high, low, close, adjclose(=0), volume
    linetokens = ["2024-01-03", "100.0", "105.0", "99.0", "102.0", "0.0", "1000"]

    # Should NOT raise ZeroDivisionError
    result = feed._loadline(linetokens)
    assert result is True

    # Verify prices were set (adjfactor=1.0 means no adjustment)
    feed.lines.open.__setitem__.assert_called()
    feed.lines.close.__setitem__.assert_called()


def test_yahoo_adjfactor_normal():
    """Verify normal adjfactor calculation still works correctly."""
    feed = _make_yahoo_feed(adjclose=True, adjvolume=True)

    # close=100, adjustedclose=50 → adjfactor=2.0
    linetokens = ["2024-01-03", "200.0", "210.0", "190.0", "100.0", "50.0", "1000"]

    result = feed._loadline(linetokens)
    assert result is True

    # With adjclose=True, close should be set to adjustedclose (50.0)
    close_calls = feed.lines.close.__setitem__.call_args_list
    assert any(call[0][1] == 50.0 for call in close_calls), (
        f"Expected close=50.0 (adjustedclose), got calls: {close_calls}"
    )
