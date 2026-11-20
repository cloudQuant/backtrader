"""Timeframe names accept both omitted and explicitly unset compression."""

import pytest

from backtrader.dataseries import TimeFrame


@pytest.mark.parametrize("timeframe", [TimeFrame.Minutes, TimeFrame.Days, TimeFrame.NoTimeFrame])
def test_default_compression_matches_explicit_one(timeframe):
    assert TimeFrame.getname(timeframe) == TimeFrame.getname(timeframe, 1)
    assert TimeFrame.getname(timeframe, None) == TimeFrame.getname(timeframe, 1)


def test_compressed_timeframe_remains_plural():
    assert TimeFrame.getname(TimeFrame.Days, 2) == "Days"
