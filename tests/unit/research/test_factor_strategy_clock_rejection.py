"""The offline collector rejects live/replay clocks before engine iteration."""

import pytest

import backtrader as bt
from backtrader.errors import ResearchConfigError
from tests.unit import test_factor_research_binding_clock as fixture


@pytest.mark.parametrize("clock", ["cerebro_live", "live_feed", "replay", "resample"])
def test_offline_factor_strategy_rejects_unsupported_clock_before_iteration(clock, monkeypatch):
    research, frames, _ = fixture._fixture()
    cerebro = bt.Cerebro(live=clock == "cerebro_live", stdstats=False)
    for name, frame in frames.items():
        if clock == "live_feed":
            feed = fixture._LivePandasData(dataname=frame)
        else:
            feed = fixture._aligned_feed(frame, research, name)
        if clock == "replay":
            cerebro.replaydata(feed, name=name, timeframe=bt.TimeFrame.Weeks)
        elif clock == "resample":
            cerebro.resampledata(feed, name=name, timeframe=bt.TimeFrame.Weeks)
        else:
            cerebro.adddata(feed, name=name)
    fixture._add_strategy(cerebro, research)
    writes = fixture._count_broker_writes(cerebro, monkeypatch)
    fixture._stop_before_clock_iteration(cerebro, monkeypatch)

    with pytest.raises(ResearchConfigError) as caught:
        cerebro.run()

    assert caught.value.code == "UNSUPPORTED_CLOCK"
    assert writes == {"submit": 0, "cancel": 0}
