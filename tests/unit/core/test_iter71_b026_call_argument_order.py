"""The public data registration and filter hooks preserve expanded arguments."""

from __future__ import annotations

from types import SimpleNamespace

import backtrader as bt
from backtrader.feed import AbstractDataBase


def _input_feeds():
    return (
        bt.feeds.GenericCSVData(dataname="first.csv"),
        bt.feeds.GenericCSVData(dataname="second.csv"),
    )


def test_chaindata_keeps_feed_order_and_explicit_name():
    cerebro = bt.Cerebro(stdstats=False)
    feeds = _input_feeds()

    chained = cerebro.chaindata(*feeds, name="combined")

    assert chained._args == feeds
    assert chained._dataname == "combined"
    assert chained._name == "combined"
    assert cerebro.datas == [chained]


def test_rolloverdata_keeps_feed_order_and_forwards_keywords():
    cerebro = bt.Cerebro(stdstats=False)
    feeds = _input_feeds()
    checkdate = lambda _data, _date: True

    rolled = cerebro.rolloverdata(
        *feeds,
        name="continuous",
        checkdate=checkdate,
    )

    assert rolled._rolls == feeds
    assert rolled._dataname == "continuous"
    assert rolled._name == "continuous"
    assert rolled.p.checkdate is checkdate
    assert cerebro.datas == [rolled]


def test_feed_check_preserves_dynamic_filter_positional_and_keyword_arguments():
    marker = object()
    received = []

    class Filter:
        def check(self, data, *args, **kwargs):
            received.append((data, args, kwargs))

    filter_instance = Filter()
    feed = SimpleNamespace(
        _filters=[(filter_instance, ("filter-arg", 17), {"mode": "custom"})]
    )

    AbstractDataBase._check(feed, forcedata=marker)

    assert received == [
        (feed, ("filter-arg", 17), {"_forcedata": marker, "mode": "custom"})
    ]
