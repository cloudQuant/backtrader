"""Unit tests for backtrader/channels/orderbook.py - OrderBookChannel."""

import json
import pytest
from backtrader.channels.orderbook import OrderBookChannel
from backtrader.events import OrderBookSnapshot


import csv as _csv

def _write_ob_csv(path, rows, fieldnames=('timestamp', 'bids', 'asks', 'symbol')):
    """Write OB CSV with proper quoting for JSON fields."""
    with open(str(path), 'w', newline='') as f:
        writer = _csv.DictWriter(f, fieldnames=fieldnames, quoting=_csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_ob_jsonl(path, records):
    with open(str(path), 'w') as f:
        for rec in records:
            f.write(json.dumps(rec) + '\n')


class TestOrderBookChannel:
    """Test suite for OrderBookChannel class."""

    def test_basic_creation(self):
        """Test basic OrderBookChannel instantiation with default parameters.

        Verifies that an OrderBookChannel can be created with a symbol and
        that default attributes are set correctly.

        Args:
            self: Test instance.

        Returns:
            None
        """
        ch = OrderBookChannel(symbol='BTC/USDT')
        assert ch.symbol == 'BTC/USDT'
        assert ch.channel_type == 'orderbook'
        assert ch.depth == 20

    def test_load_csv(self, tmp_path):
        """Test loading order book events from a CSV file.

        Creates a CSV file with order book snapshot data and verifies that
        OrderBookChannel can correctly parse and load the events.

        Args:
            self: Test instance.
            tmp_path: Pytest fixture providing a temporary directory path.

        Returns:
            None
        """
        csv_file = tmp_path / 'ob.csv'
        bids = json.dumps([[50000, 1.0], [49999, 2.0]])
        asks = json.dumps([[50001, 1.5], [50002, 2.5]])
        _write_ob_csv(str(csv_file), [
            {'timestamp': '100.0', 'bids': bids, 'asks': asks, 'symbol': 'BTC/USDT'},
            {'timestamp': '100.1', 'bids': bids, 'asks': asks, 'symbol': 'BTC/USDT'},
        ])

        ch = OrderBookChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())

        assert len(events) == 2
        assert events[0].timestamp == 100.0
        assert events[0].bids == [(50000, 1.0), (49999, 2.0)]
        assert events[0].asks == [(50001, 1.5), (50002, 2.5)]
        assert events[0].best_bid == 50000
        assert events[0].best_ask == 50001

    def test_load_csv_missing_column(self, tmp_path):
        """Test that loading CSV with missing required columns raises ValueError.

        Args:
            self: Test instance.
            tmp_path: Pytest fixture providing a temporary directory path.

        Returns:
            None

        Raises:
            AssertionError: If ValueError is not raised with expected message.
        """
        csv_file = tmp_path / 'bad_ob.csv'
        _write_ob_csv(str(csv_file), [
            {'timestamp': '100.0', 'bids': '[[50000,1.0]]'},
        ], fieldnames=('timestamp', 'bids'))

        ch = OrderBookChannel(symbol='BTC/USDT', dataname=str(csv_file))
        with pytest.raises(ValueError, match="Missing required columns"):
            list(ch.load())

    def test_load_jsonl(self, tmp_path):
        """Test loading order book events from a JSONL file.

        Creates a JSONL file with order book snapshot data and verifies that
        OrderBookChannel can correctly parse and load the events.

        Args:
            self: Test instance.
            tmp_path: Pytest fixture providing a temporary directory path.

        Returns:
            None
        """
        jsonl_file = tmp_path / 'ob.jsonl'
        _write_ob_jsonl(str(jsonl_file), [
            {
                'timestamp': 100.0,
                'symbol': 'BTC/USDT',
                'bids': [[50000, 1.0], [49999, 2.0]],
                'asks': [[50001, 1.5], [50002, 2.5]],
            },
            {
                'timestamp': 100.1,
                'symbol': 'BTC/USDT',
                'bids': [[50010, 1.0]],
                'asks': [[50011, 1.5]],
            },
        ])

        ch = OrderBookChannel(symbol='BTC/USDT', dataname=str(jsonl_file))
        events = list(ch.load())

        assert len(events) == 2
        assert events[0].bids == [(50000, 1.0), (49999, 2.0)]
        assert events[1].bids == [(50010, 1.0)]

    def test_depth_truncation(self, tmp_path):
        """Test that order book depth is properly truncated to specified limit.

        Creates a JSONL file with order book data containing more levels than
        the specified depth and verifies truncation occurs.

        Args:
            self: Test instance.
            tmp_path: Pytest fixture providing a temporary directory path.

        Returns:
            None
        """
        jsonl_file = tmp_path / 'deep_ob.jsonl'
        bids = [[50000 - i, 1.0] for i in range(30)]
        asks = [[50001 + i, 1.0] for i in range(30)]
        _write_ob_jsonl(str(jsonl_file), [
            {'timestamp': 100.0, 'bids': bids, 'asks': asks},
        ])

        ch = OrderBookChannel(symbol='BTC/USDT', dataname=str(jsonl_file), depth=5)
        events = list(ch.load())

        assert len(events[0].bids) == 5
        assert len(events[0].asks) == 5

    def test_push_valid_ob(self):
        """Test pushing a valid OrderBookSnapshot to the channel.

        Args:
            self: Test instance.

        Returns:
            None
        """
        ch = OrderBookChannel(symbol='BTC/USDT')
        ob = OrderBookSnapshot(
            timestamp=100.0, symbol='BTC/USDT',
            bids=[(50000, 1.0)], asks=[(50001, 1.0)],
        )
        assert ch.push(ob) is True
        assert ch.event_count == 1

    def test_push_invalid_ob(self):
        """Test that pushing an invalid OrderBookSnapshot returns False.

        Args:
            self: Test instance.

        Returns:
            None
        """
        ch = OrderBookChannel(symbol='BTC/USDT')
        ob = OrderBookSnapshot(
            timestamp=100.0, symbol='BTC/USDT',
            bids=[], asks=[],
        )
        assert ch.push(ob) is False

    def test_load_no_dataname(self):
        """Test that loading without a dataname raises ValueError.

        Args:
            self: Test instance.

        Returns:
            None

        Raises:
            AssertionError: If ValueError is not raised with expected message.
        """
        ch = OrderBookChannel(symbol='BTC/USDT')
        with pytest.raises(ValueError, match="dataname"):
            list(ch.load())

    def test_repr(self):
        """Test the string representation of OrderBookChannel.

        Args:
            self: Test instance.

        Returns:
            None
        """
        ch = OrderBookChannel(symbol='BTC/USDT', dataname='test.csv', depth=10)
        r = repr(ch)
        assert 'OrderBookChannel' in r
        assert 'BTC/USDT' in r
        assert '10' in r

    def test_load_invalid_json_skipped(self, tmp_path):
        """Test that rows with invalid JSON in CSV are skipped during load.

        Creates a CSV file with one row containing invalid JSON and verifies
        that only valid rows are loaded.

        Args:
            self: Test instance.
            tmp_path: Pytest fixture providing a temporary directory path.

        Returns:
            None
        """
        csv_file = tmp_path / 'bad_json_ob.csv'
        bids_good = json.dumps([[50000, 1.0]])
        asks_good = json.dumps([[50001, 1.0]])
        _write_ob_csv(str(csv_file), [
            {'timestamp': '100.0', 'bids': bids_good, 'asks': asks_good, 'symbol': 'BTC/USDT'},
            {'timestamp': '100.1', 'bids': 'NOT_JSON', 'asks': asks_good, 'symbol': 'BTC/USDT'},
            {'timestamp': '100.2', 'bids': bids_good, 'asks': asks_good, 'symbol': 'BTC/USDT'},
        ])

        ch = OrderBookChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())
        assert len(events) == 2
