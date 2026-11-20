"""A temporarily empty feed must remain in the chain until EOF."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from backtrader.feeds.chainer import Chainer


def test_not_ready_does_not_advance_to_next_feed():
    start = datetime(2025, 1, 1)
    first = Mock()
    first.next.side_effect = [None, True, False]
    first.datetime = SimpleNamespace(datetime=lambda: start)
    first.size.return_value = 1
    first.lines = [[123.0]]
    second = Mock()
    second.next.return_value = True
    second.datetime = SimpleNamespace(datetime=lambda: start + timedelta(days=1))
    second.size.return_value = 1
    second.lines = [[456.0]]
    chain = Chainer()
    chain._d = first
    chain._ds = [second]
    chain._lastdt = datetime.min
    chain.lines[0].forward()

    assert chain._load() is None
    assert chain._d is first
    second.next.assert_not_called()
    assert chain._load() is True
    assert chain._d is first
    assert chain.lines[0][0] == 123.0
    assert chain._load() is True
    assert chain._d is second
    assert chain.lines[0][0] == 456.0
    second.next.assert_called_once()
