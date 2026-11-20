"""Regression coverage for order validity normalization and expiry."""

import datetime

import pandas as pd
import pytz
import pytest

import backtrader as bt
from backtrader.utils.dateintern import TIME_MAX, date2num


class _ValidityStrategy(bt.Strategy):
    params = (("valid", None),)

    def __init__(self):
        self.order = None
        self.created_valid = None
        self.statuses = []

    def next(self):
        if self.order is None:
            self.order = self.buy(
                size=1,
                exectype=bt.Order.Limit,
                price=float(self.data.close[0]) - 100.0,
                valid=self.p.valid,
            )
            self.created_valid = self.order.valid

    def notify_order(self, order):
        if self.order is not None and order.ref == self.order.ref:
            self.statuses.append(
                (order.getstatusname(), self.data.datetime.datetime(0), order.valid)
            )


def _run_order(
    valid,
    timestamps,
    timezone="America/New_York",
    timeframe=bt.TimeFrame.Days,
):
    index = pd.DatetimeIndex(timestamps)
    frame = pd.DataFrame(
        {
            "open": [100.0] * len(index),
            "high": [101.0] * len(index),
            "low": [99.0] * len(index),
            "close": [100.0] * len(index),
            "volume": [100.0] * len(index),
            "openinterest": [0.0] * len(index),
        },
        index=index,
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(
        bt.feeds.PandasData(dataname=frame, tz=timezone, timeframe=timeframe)
    )
    cerebro.addstrategy(_ValidityStrategy, valid=valid)
    return cerebro.run()[0]


def _new_york_datetimes(*values):
    timezone = pytz.timezone("America/New_York")
    return [timezone.localize(datetime.datetime(*value)) for value in values]


@pytest.mark.parametrize("valid", [0, 0.0, bt.Order.DAY])
def test_zero_and_day_validity_expire_at_local_calendar_day_end(valid):
    bars = _new_york_datetimes(
        (2024, 3, 10, 23, 0),
        (2024, 3, 10, 23, 59, 59, 500000),
        (2024, 3, 11, 0),
    )

    strategy = _run_order(valid, bars, timeframe=bt.TimeFrame.Seconds)

    expected_end = pytz.timezone("America/New_York").localize(
        datetime.datetime.combine(datetime.date(2024, 3, 10), TIME_MAX)
    )
    assert strategy.created_valid == pytest.approx(date2num(expected_end))
    assert not any(
        status == "Expired" and timestamp.date() == datetime.date(2024, 3, 10)
        for status, timestamp, _ in strategy.statuses
    )
    expired_at = next(
        timestamp for status, timestamp, _ in strategy.statuses if status == "Expired"
    )
    assert expired_at == datetime.datetime(2024, 3, 11, 0)


def test_nonzero_float_remains_an_absolute_matplotlib_date_number():
    bars = _new_york_datetimes(
        (2024, 3, 8, 15),
        (2024, 3, 11, 15),
        (2024, 3, 12, 15),
        (2024, 3, 13, 15),
    )
    valid_until = date2num(bars[2])

    strategy = _run_order(valid_until, bars)

    assert strategy.created_valid == valid_until
    assert [
        status for status, _, _ in strategy.statuses if status == "Expired"
    ] == ["Expired"]
    expired_at = next(
        timestamp
        for status, timestamp, _ in strategy.statuses
        if status == "Expired"
    )
    assert expired_at == datetime.datetime(2024, 3, 13, 15)


def test_timedelta_days_keep_local_wall_time_across_dst():
    bars = _new_york_datetimes(
        (2024, 3, 9, 15),
        (2024, 3, 10, 15),
        (2024, 3, 11, 15),
    )

    strategy = _run_order(datetime.timedelta(days=1), bars)

    expected_valid = date2num(bars[1])
    assert strategy.created_valid == pytest.approx(expected_valid)
    assert (
        "Expired",
        datetime.datetime(2024, 3, 11, 15),
        strategy.created_valid,
    ) in strategy.statuses


def test_none_validity_remains_good_till_canceled():
    bars = _new_york_datetimes(
        (2024, 3, 8, 15),
        (2024, 3, 11, 15),
        (2024, 3, 12, 15),
    )

    strategy = _run_order(None, bars)

    assert strategy.created_valid is None
    assert not any(status == "Expired" for status, _, _ in strategy.statuses)


@pytest.mark.parametrize("valid", [False, "", []])
def test_falsy_non_numeric_validity_is_not_treated_as_day_order(valid):
    bars = _new_york_datetimes(
        (2024, 3, 8, 15),
        (2024, 3, 11, 15),
    )

    strategy = _run_order(valid, bars)

    assert type(strategy.created_valid) is type(valid)
    assert strategy.created_valid == valid
    assert not any(status == "Expired" for status, _, _ in strategy.statuses)


def test_datetime_validity_keeps_existing_timezone_conversion():
    bars = _new_york_datetimes(
        (2024, 3, 8, 15),
        (2024, 3, 11, 15),
        (2024, 3, 12, 15),
    )
    valid_until = datetime.datetime(2024, 3, 11, 16)

    strategy = _run_order(valid_until, bars)

    expected_valid = date2num(
        pytz.timezone("America/New_York").localize(valid_until)
    )
    assert strategy.created_valid == pytest.approx(expected_valid)
    assert not any(
        status == "Expired"
        for status, timestamp, _ in strategy.statuses
        if timestamp < datetime.datetime(2024, 3, 12, 15)
    )
    assert any(status == "Expired" for status, _, _ in strategy.statuses)


def test_date_validity_keeps_existing_absolute_date_conversion():
    bars = [
        datetime.datetime(2024, 3, 8, 15),
        datetime.datetime(2024, 3, 11, 15),
        datetime.datetime(2024, 3, 12, 15),
    ]
    valid_until = datetime.date(2024, 3, 11)

    strategy = _run_order(valid_until, bars, timezone=None)

    assert strategy.created_valid == date2num(valid_until)
    assert any(status == "Expired" for status, _, _ in strategy.statuses)


def test_date_validity_uses_feed_timezone_local_midnight():
    bars = _new_york_datetimes(
        (2024, 3, 8, 15),
        (2024, 3, 11, 15),
        (2024, 3, 12, 15),
    )
    valid_until = datetime.date(2024, 3, 11)

    strategy = _run_order(valid_until, bars)

    local_midnight = pytz.timezone("America/New_York").localize(
        datetime.datetime.combine(valid_until, datetime.time.min)
    )
    assert strategy.created_valid == pytest.approx(date2num(local_midnight))
    assert any(status == "Expired" for status, _, _ in strategy.statuses)
