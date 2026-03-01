"""Unit tests for backtrader/channels/tick.py - TickChannel."""

import os
import tempfile

import pytest
from backtrader.channels.tick import TickChannel
from backtrader.events import TickEvent


def _write_csv(path, rows, header='timestamp,price,volume,direction,trade_id,symbol'):
    with open(path, 'w') as f:
        f.write(header + '\n')
        for row in rows:
            f.write(row + '\n')


class TestTickChannel:
    """Test suite for TickChannel class."""

    def test_basic_creation(self):
        """Test basic TickChannel instantiation with symbol parameter.

        Verifies that a TickChannel can be created with a symbol and that
        the symbol and channel_type attributes are correctly set.
        """
        ch = TickChannel(symbol='BTC/USDT')
        assert ch.symbol == 'BTC/USDT'
        assert ch.channel_type == 'tick'

    def test_load_csv(self, tmp_path):
        """Test loading tick data from a CSV file.

        Verifies that TickChannel can correctly parse CSV data with all
        standard columns (timestamp, price, volume, direction, trade_id, symbol)
        and create TickEvent objects with proper attribute values.

        Args:
            tmp_path: Pytest fixture providing a temporary directory path.
        """
        csv_file = tmp_path / 'ticks.csv'
        _write_csv(str(csv_file), [
            '100.0,50000.5,1.234,buy,T1,BTC/USDT',
            '100.1,50001.0,0.567,sell,T2,BTC/USDT',
            '100.2,50000.0,2.0,buy,T3,BTC/USDT',
        ])

        ch = TickChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())

        assert len(events) == 3
        assert events[0].timestamp == 100.0
        assert events[0].price == 50000.5
        assert events[0].volume == 1.234
        assert events[0].direction == 'buy'
        assert events[0].trade_id == 'T1'
        assert events[1].direction == 'sell'
        assert events[2].price == 50000.0

    def test_load_csv_minimal_columns(self, tmp_path):
        """Test loading CSV with optional columns set to empty values.

        Verifies that TickChannel correctly handles CSV files where optional
        columns like bid_price and ask_price are present but empty.

        Args:
            tmp_path: Pytest fixture providing a temporary directory path.
        """
        csv_file = tmp_path / 'ticks_min.csv'
        _write_csv(str(csv_file), [
            '100.0,50000,1.0,buy,,,',
            '100.1,50001,0.5,sell,,,',
        ], header='timestamp,price,volume,direction,trade_id,bid_price,ask_price')

        ch = TickChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())

        assert len(events) == 2
        assert events[0].bid_price is None
        assert events[0].ask_price is None

    def test_load_csv_missing_required_column(self, tmp_path):
        """Test loading CSV with missing required columns raises ValueError.

        Verifies that TickChannel properly validates CSV structure and raises
        an error when required columns (like 'direction') are missing.

        Args:
            tmp_path: Pytest fixture providing a temporary directory path.
        """
        csv_file = tmp_path / 'bad.csv'
        _write_csv(str(csv_file), [
            '100.0,50000,1.0',
        ], header='timestamp,price,volume')

        ch = TickChannel(symbol='BTC/USDT', dataname=str(csv_file))
        with pytest.raises(ValueError, match="Missing required columns"):
            list(ch.load())

    def test_load_csv_invalid_row_skipped(self, tmp_path):
        """Test that invalid CSV rows are skipped during loading.

        Verifies that TickChannel gracefully handles rows with invalid data
        (e.g., non-numeric timestamp) by skipping them while continuing to
        process valid rows.

        Args:
            tmp_path: Pytest fixture providing a temporary directory path.
        """
        csv_file = tmp_path / 'mixed.csv'
        _write_csv(str(csv_file), [
            '100.0,50000,1.0,buy,T1,BTC/USDT',
            'bad_ts,50000,1.0,buy,T2,BTC/USDT',
            '100.2,50000,1.0,buy,T3,BTC/USDT',
        ])

        ch = TickChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())

        assert len(events) == 2
        assert events[0].trade_id == 'T1'
        assert events[1].trade_id == 'T3'

    def test_load_no_dataname(self):
        """Test that loading without a dataname raises ValueError.

        Verifies that TickChannel.load() raises an appropriate error when
        no dataname (file path) has been provided to the channel.
        """
        ch = TickChannel(symbol='BTC/USDT')
        with pytest.raises(ValueError, match="dataname"):
            list(ch.load())

    def test_push_and_validate(self):
        """Test pushing a valid tick event to the channel.

        Verifies that TickChannel.push() successfully accepts a valid
        TickEvent and increments the internal event counter.
        """
        ch = TickChannel(symbol='BTC/USDT')
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        assert ch.push(tick) is True
        assert ch.event_count == 1

    def test_push_invalid_tick(self):
        """Test that pushing an invalid tick event is rejected.

        Verifies that TickChannel.push() returns False when given a
        TickEvent with invalid data (e.g., negative price).
        """
        ch = TickChannel(symbol='BTC/USDT')
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=-1.0, volume=1.0, direction='buy')
        assert ch.push(tick) is False

    def test_price_change_warning(self):
        """Test that large price changes are accepted with warning.

        Verifies that TickChannel accepts ticks with price changes exceeding
        the configured threshold. The tick should still be pushed successfully
        even when the price change percentage is significant.

        Note: This test verifies the tick is accepted; actual warning logging
        is a side effect not directly asserted here.
        """
        ch = TickChannel(symbol='BTC/USDT', price_change_threshold=0.05)
        t1 = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        t2 = TickEvent(timestamp=101.0, symbol='BTC/USDT', price=60000, volume=1.0, direction='buy')

        ch.push(t1)
        # Second tick has >5% price change, should still be accepted but with warning
        result = ch.push(t2)
        assert result is True

    def test_load_gzip_csv(self, tmp_path):
        """Test loading tick data from a gzip-compressed CSV file.

        Verifies that TickChannel can automatically detect and decompress
        gzip-compressed CSV files (.gz extension) and parse the tick data.

        Args:
            tmp_path: Pytest fixture providing a temporary directory path.
        """
        import gzip
        csv_file = tmp_path / 'ticks.csv.gz'
        content = 'timestamp,price,volume,direction\n100.0,50000,1.0,buy\n100.1,50001,0.5,sell\n'
        with gzip.open(str(csv_file), 'wt', encoding='utf-8') as f:
            f.write(content)

        ch = TickChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())

        assert len(events) == 2
        assert events[0].price == 50000.0
        assert events[1].direction == 'sell'

    def test_repr(self):
        """Test the string representation of TickChannel.

        Verifies that the __repr__ method returns a string containing
        the class name and symbol for easy debugging and logging.
        """
        ch = TickChannel(symbol='BTC/USDT', dataname='test.csv')
        r = repr(ch)
        assert 'TickChannel' in r
        assert 'BTC/USDT' in r

    def test_symbol_from_csv(self, tmp_path):
        """Test that symbol from CSV row takes precedence over channel symbol.

        Verifies that when a CSV file contains a symbol column, the value
        from the CSV row overrides the symbol specified in TickChannel
        constructor.

        Args:
            tmp_path: Pytest fixture providing a temporary directory path.
        """
        csv_file = tmp_path / 'ticks.csv'
        _write_csv(str(csv_file), [
            '100.0,50000,1.0,buy,T1,ETH/USDT',
        ])

        ch = TickChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())
        # Symbol from CSV row takes precedence
        assert events[0].symbol == 'ETH/USDT'

    def test_default_symbol_from_channel(self, tmp_path):
        """Test that channel symbol is used when CSV has no symbol column.

        Verifies that TickChannel falls back to using the symbol provided
        in the constructor when the CSV file does not contain a symbol column.

        Args:
            tmp_path: Pytest fixture providing a temporary directory path.
        """
        csv_file = tmp_path / 'ticks.csv'
        # CSV without symbol column
        with open(str(csv_file), 'w') as f:
            f.write('timestamp,price,volume,direction\n')
            f.write('100.0,50000,1.0,buy\n')

        ch = TickChannel(symbol='BTC/USDT', dataname=str(csv_file))
        events = list(ch.load())
        # Should use channel's symbol
        assert events[0].symbol == 'BTC/USDT'
