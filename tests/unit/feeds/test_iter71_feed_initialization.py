"""Specialized feeds initialize their shared data-feed state offline."""

from datetime import date, datetime, time

import pytest

from backtrader.feeds.blaze import BlazeData
from backtrader.feeds.influxfeed import InfluxDB
from backtrader.feeds.quandl import Quandl
from backtrader.feeds.vchart import VChartData
from backtrader.feeds.yahoo import YahooFinanceData


@pytest.mark.parametrize("feed_class", [BlazeData, InfluxDB, Quandl, VChartData, YahooFinanceData])
def test_feed_base_initialization_and_session_defaults(feed_class):
    data = feed_class(dataname="test", fromdate=date(2025, 1, 1))

    assert data.p.sessionstart == time.min
    assert data.p.sessionend == time(23, 59, 59, 999990)
    assert data.p.fromdate == datetime(2025, 1, 1)
    assert data._env is None
    assert data.close._is_data_feed_line
    data._start_finish()  # Public configuration path; no external service is contacted.
    assert data._started


@pytest.mark.parametrize("feed_class", [BlazeData, InfluxDB, Quandl, VChartData, YahooFinanceData])
def test_explicit_session_times_are_preserved(feed_class):
    data = feed_class(dataname="test", sessionstart=time(9), sessionend=time(16))
    assert data.p.sessionstart == time(9)
    assert data.p.sessionend == time(16)


def test_blaze_starts_and_stops_with_empty_local_source():
    data = BlazeData(dataname=[])
    data._start()
    assert data._started
    assert data.load() is False
    data.stop()


def test_vchart_starts_and_closes_local_file(tmp_path):
    path = tmp_path / "empty.fd"
    path.write_bytes(b"")
    data = VChartData(dataname=str(path))
    data._start()
    stream = data.f
    assert data._started and not stream.closed
    data.stop()
    assert stream.closed
