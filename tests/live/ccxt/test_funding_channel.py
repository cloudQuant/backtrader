"""Unit tests for backtrader/channels/funding.py - FundingRateChannel."""

import json
import pytest
from backtrader.channels.funding import FundingRateChannel
from backtrader.events import FundingEvent


def _write_csv(path, rows, header='timestamp,rate,mark_price,next_funding_time,predicted_rate'):
    with open(str(path), 'w') as f:
        f.write(header + '\n')
        for row in rows:
            f.write(row + '\n')


def _write_jsonl(path, records):
    with open(str(path), 'w') as f:
        for rec in records:
            f.write(json.dumps(rec) + '\n')


class TestFundingRateChannel:
    """Test suite for FundingRateChannel class."""

    def test_basic_creation(self):
        """Test basic FundingRateChannel instantiation and attributes.

        Verifies that a FundingRateChannel can be created with a symbol
        and that its basic attributes are set correctly.
        """
        ch = FundingRateChannel(symbol='BTC/USDT')
        assert ch.symbol == 'BTC/USDT'
        assert ch.channel_type == 'funding'

    def test_load_csv(self, tmp_path):
        """Test loading funding rate data from a CSV file.

        Args:
            tmp_path: Pytest fixture providing a temporary directory.

        Verifies that FundingRateChannel can parse CSV files with all
        columns (timestamp, rate, mark_price, next_funding_time, predicted_rate)
        and correctly create FundingEvent objects.
        """
        csv_file = tmp_path / 'funding.csv'
        _write_csv(str(csv_file), [
            '100.0,0.0001,50000.0,200.0,0.00012',
            '200.0,-0.0002,50100.0,300.0,0.0001',
        ])

        ch = FundingRateChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())

        assert len(events) == 2
        assert events[0].timestamp == 100.0
        assert events[0].rate == 0.0001
        assert events[0].mark_price == 50000.0
        assert events[0].next_funding_time == 200.0
        assert events[0].predicted_rate == 0.00012
        assert events[1].rate == -0.0002

    def test_load_csv_minimal(self, tmp_path):
        """Test loading CSV with minimal required columns only.

        Args:
            tmp_path: Pytest fixture providing a temporary directory.

        Verifies that optional columns (next_funding_time, predicted_rate)
        default to 0.0 when not provided in the CSV data.
        """
        csv_file = tmp_path / 'funding_min.csv'
        _write_csv(str(csv_file), [
            '100.0,0.0001,50000.0,,',
        ])

        ch = FundingRateChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())

        assert len(events) == 1
        assert events[0].next_funding_time == 0.0
        assert events[0].predicted_rate == 0.0

    def test_load_csv_missing_column(self, tmp_path):
        """Test that CSV with missing required columns raises ValueError.

        Args:
            tmp_path: Pytest fixture providing a temporary directory.

        Verifies that attempting to load a CSV without the required
        'mark_price' column results in a ValueError.
        """
        csv_file = tmp_path / 'bad.csv'
        with open(str(csv_file), 'w') as f:
            f.write('timestamp,rate\n100.0,0.0001\n')

        ch = FundingRateChannel(symbol='BTC/USDT', dataname=str(csv_file))
        with pytest.raises(ValueError, match="Missing required columns"):
            list(ch.load())

    def test_load_jsonl(self, tmp_path):
        """Test loading funding rate data from a JSONL file.

        Args:
            tmp_path: Pytest fixture providing a temporary directory.

        Verifies that FundingRateChannel can parse JSONL files where each
        line is a JSON object, handling both complete and partial records.
        """
        jsonl_file = tmp_path / 'funding.jsonl'
        _write_jsonl(str(jsonl_file), [
            {'timestamp': 100.0, 'rate': 0.0001, 'mark_price': 50000.0,
             'next_funding_time': 200.0, 'predicted_rate': 0.00012},
            {'timestamp': 200.0, 'rate': -0.0002, 'mark_price': 50100.0},
        ])

        ch = FundingRateChannel(symbol='BTC/USDT', dataname=str(jsonl_file))
        events = list(ch.load())

        assert len(events) == 2
        assert events[0].rate == 0.0001
        assert events[1].next_funding_time == 0.0

    def test_push_valid(self):
        """Test pushing a valid FundingEvent to the channel.

        Verifies that a valid FundingEvent can be successfully pushed
        to the channel and the event count is incremented.
        """
        ch = FundingRateChannel(symbol='BTC/USDT')
        fe = FundingEvent(
            timestamp=100.0, symbol='BTC/USDT',
            rate=0.0001, mark_price=50000.0, next_funding_time=200.0,
        )
        assert ch.push(fe) is True
        assert ch.event_count == 1

    def test_push_invalid(self):
        """Test pushing an invalid FundingEvent to the channel.

        Verifies that an invalid FundingEvent (e.g., with mark_price=0)
        is rejected by the channel and push() returns False.
        """
        ch = FundingRateChannel(symbol='BTC/USDT')
        fe = FundingEvent(
            timestamp=100.0, symbol='BTC/USDT',
            rate=0.0001, mark_price=0.0,  # invalid
        )
        assert ch.push(fe) is False

    def test_load_no_dataname(self):
        """Test that loading without dataname raises ValueError.

        Verifies that calling load() on a FundingRateChannel without
        a dataname configured results in a ValueError.
        """
        ch = FundingRateChannel(symbol='BTC/USDT')
        with pytest.raises(ValueError, match="dataname"):
            list(ch.load())

    def test_repr(self):
        """Test the string representation of FundingRateChannel.

        Verifies that the __repr__ method includes the class name
        and symbol information.
        """
        ch = FundingRateChannel(symbol='BTC/USDT', dataname='test.csv')
        r = repr(ch)
        assert 'FundingRateChannel' in r
        assert 'BTC/USDT' in r

    def test_default_asset_type(self, tmp_path):
        """Test that funding rate events default to 'swap' asset type.

        Args:
            tmp_path: Pytest fixture providing a temporary directory.

        Verifies that FundingEvent objects created from CSV data
        have their asset_type field set to 'swap' by default.
        """
        csv_file = tmp_path / 'funding.csv'
        _write_csv(str(csv_file), [
            '100.0,0.0001,50000.0,200.0,0.0',
        ])
        ch = FundingRateChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())
        assert events[0].asset_type == 'swap'

    def test_load_invalid_row_skipped(self, tmp_path):
        """Test that invalid CSV rows are skipped during loading.

        Args:
            tmp_path: Pytest fixture providing a temporary directory.

        Verifies that when a CSV file contains malformed rows,
        they are silently skipped and only valid rows are loaded.
        """
        csv_file = tmp_path / 'mixed.csv'
        _write_csv(str(csv_file), [
            '100.0,0.0001,50000.0,200.0,0.0',
            'bad,0.0001,50000.0,200.0,0.0',
            '300.0,0.0001,50000.0,400.0,0.0',
        ])
        ch = FundingRateChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())
        assert len(events) == 2
