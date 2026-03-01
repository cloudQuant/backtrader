"""Line Operations Test Cases

Tests vector operations (addition, subtraction, multiplication, division) between backtrader indicators.
Uses randomly generated data with a fixed seed to ensure reproducibility.

Test cases:
1. MACD EMA indicator calculation (ema1 - ema2, dif - dea, * 2)
2. Keltner Channel indicator calculation ((high + low + close) / 3, middle_line + atr * mult)
3. TimeLine + SMA indicator calculation
4. Highest/Lowest indicator calculation
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import random
import math

import backtrader as bt


# ============================================================================
# Helper function: Generate random OHLCV data
# ============================================================================
def generate_random_ohlcv_data(num_bars=100, seed=42):
    """Generate random OHLCV data

    Args:
        num_bars: Number of bars to generate
        seed: Random seed to ensure reproducibility

    Returns:
        list of dict: List of OHLCV data
    """
    random.seed(seed)
    
    data = []
    base_price = 100.0
    base_date = datetime.datetime(2020, 1, 1, 9, 0, 0)
    
    for i in range(num_bars):
        # Generate random price changes
        change = random.uniform(-2, 2)
        base_price = max(50, base_price + change)  # Ensure price doesn't get too low

        # Generate OHLC
        open_price = base_price + random.uniform(-1, 1)
        high_price = max(open_price, base_price) + random.uniform(0, 2)
        low_price = min(open_price, base_price) - random.uniform(0, 2)
        close_price = base_price + random.uniform(-1, 1)

        # Ensure high >= open, close and low <= open, close
        high_price = max(high_price, open_price, close_price)
        low_price = min(low_price, open_price, close_price)
        
        volume = random.randint(1000, 10000)
        
        dt = base_date + datetime.timedelta(minutes=i)
        
        data.append({
            'datetime': dt,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume,
            'openinterest': 0
        })
    
    return data


class RandomDataFeed(bt.feeds.DataBase):
    """Custom data feed using randomly generated OHLCV data.

    This data feed extends bt.feeds.DataBase to provide test data from a
    pre-generated list of OHLCV bars. It supports all standard data fields
    including datetime, open, high, low, close, volume, and openinterest.

    Attributes:
        _data_list: List of dictionaries containing OHLCV data for each bar.
        _idx: Current index in the data list being processed.

    Parameters:
        data_list: List of dictionaries with keys: datetime, open, high, low,
            close, volume, openinterest. If None, defaults to empty list.
    """

    params = (
        ('data_list', None),
    )

    def __init__(self):
        """Initialize the RandomDataFeed.

        Sets up internal data storage and initializes the parent DataBase class.
        The data_list parameter is accessed from self.p.data_list.
        """
        super(RandomDataFeed, self).__init__()
        self._data_list = self.p.data_list or []
        self._idx = 0

    def start(self):
        """Start the data feed and reset the data index.

        Called by cerebro when starting the backtest. Resets the index to 0
        so data streaming begins from the first bar.
        """
        super(RandomDataFeed, self).start()
        self._idx = 0

    def _load(self):
        """Load the next bar of data.

        This method is called by backtrader to fetch the next bar of data.
        It populates the data lines (datetime, open, high, low, close, volume,
        openinterest) from the current position in the data list.

        Returns:
            bool: True if a bar was successfully loaded, False if end of data
                has been reached (when index exceeds data list length).
        """
        if self._idx >= len(self._data_list):
            return False

        bar = self._data_list[self._idx]
        self.lines.datetime[0] = bt.date2num(bar['datetime'])
        self.lines.open[0] = bar['open']
        self.lines.high[0] = bar['high']
        self.lines.low[0] = bar['low']
        self.lines.close[0] = bar['close']
        self.lines.volume[0] = bar['volume']
        self.lines.openinterest[0] = bar['openinterest']

        self._idx += 1
        return True


# ============================================================================
# Test case 1: MACD EMA indicator calculation
# ============================================================================
class MacdEmaTestStrategy(bt.Strategy):
    """Test MACD EMA indicator vector operations.

    This strategy tests line arithmetic operations between indicators:
    - Subtraction: ema_1 - ema_2 (indicator minus indicator)
    - Subtraction: dif - dea (indicator minus indicator)
    - Multiplication: (dif - dea) * 2 (indicator times constant)

    The MACD (Moving Average Convergence Divergence) is calculated as:
    1. Fast EMA (ema_1) with period_me1
    2. Slow EMA (ema_2) with period_me2
    3. DIF (Difference) = ema_1 - ema_2
    4. DEA (Difference EMA) = EMA of DIF with period_dif
    5. MACD = (DIF - DEA) * 2

    Attributes:
        bar_num: Counter for number of bars processed in next().
        recorded_values: List of dictionaries containing indicator values for
            each valid bar (after warmup period).
        ema_1: Fast exponential moving average indicator.
        ema_2: Slow exponential moving average indicator.
        dif: Difference between fast and slow EMAs (line operation).
        dea: EMA of the DIF line.
        macd: MACD histogram calculated as (dif - dea) * 2.

    Parameters:
        period_me1: Period for fast EMA (default: 10).
        period_me2: Period for slow EMA (default: 20).
        period_dif: Period for DIF EMA (default: 9).
    """

    params = (
        ("period_me1", 10),
        ("period_me2", 20),
        ("period_dif", 9),
    )

    def __init__(self):
        """Initialize the MACD EMA test strategy.

        Creates indicators using vector arithmetic operations to test
        line-to-line and line-to-scalar operations.
        """
        self.bar_num = 0
        self.recorded_values = []

        # MACD indicator calculation
        self.ema_1 = bt.indicators.ExponentialMovingAverage(
            self.datas[0].close, period=self.p.period_me1
        )
        self.ema_2 = bt.indicators.ExponentialMovingAverage(
            self.datas[0].close, period=self.p.period_me2
        )
        self.dif = self.ema_1 - self.ema_2
        self.dea = bt.indicators.ExponentialMovingAverage(
            self.dif, period=self.p.period_dif
        )
        self.macd = (self.dif - self.dea) * 2

    def next(self):
        """Process each bar and record indicator values.

        Called for each bar after indicator warmup period. Records the
        values of all MACD-related indicators if they are valid (not NaN).

        Skips recording during the initial warmup period when indicators
        are still calculating and returning NaN values.
        """
        self.bar_num += 1

        # Record indicator values (skip NaN values during warmup period)
        ema1_val = self.ema_1[0]
        ema2_val = self.ema_2[0]
        dif_val = self.dif[0]
        dea_val = self.dea[0]
        macd_val = self.macd[0]

        # Check if value is valid
        def is_valid(v):
            return v is not None and not (isinstance(v, float) and math.isnan(v))

        if is_valid(ema1_val) and is_valid(ema2_val) and is_valid(dif_val):
            self.recorded_values.append({
                'bar_num': self.bar_num,
                'close': self.datas[0].close[0],
                'ema_1': round(ema1_val, 6),
                'ema_2': round(ema2_val, 6),
                'dif': round(dif_val, 6),
                'dea': round(dea_val, 6) if is_valid(dea_val) else None,
                'macd': round(macd_val, 6) if is_valid(macd_val) else None,
            })


# ============================================================================
# Test case 2: Keltner Channel indicator calculation
# ============================================================================
class KeltnerTestStrategy(bt.Strategy):
    """Test Keltner Channel indicator vector operations.

    This strategy tests line arithmetic operations for Keltner Channel calculation:
    - Addition and division: (high + low + close) / 3 (multiple lines added and
      divided by constant)
    - Addition: middle_line + atr * mult (indicator plus indicator times constant)
    - Subtraction: middle_line - atr * mult (indicator minus indicator times constant)

    The Keltner Channel is calculated as:
    1. Middle price = (high + low + close) / 3
    2. Middle line = SMA of middle price
    3. ATR = Average True Range
    4. Upper line = middle_line + atr * atr_multi
    5. Lower line = middle_line - atr * atr_multi

    Attributes:
        bar_num: Counter for number of bars processed in next().
        recorded_values: List of dictionaries containing indicator values for
            each valid bar (after warmup period).
        middle_price: Calculated typical price (high + low + close) / 3.
        middle_line: SMA of the middle price.
        atr: Average True Range indicator.
        upper_line: Upper Keltner Channel band.
        lower_line: Lower Keltner Channel band.

    Parameters:
        avg_period: Period for SMA and ATR calculations (default: 20).
        atr_multi: Multiplier for ATR bands (default: 2).
    """

    params = (
        ("avg_period", 20),
        ("atr_multi", 2),
    )

    def __init__(self):
        """Initialize the Keltner Channel test strategy.

        Creates Keltner Channel indicators using vector arithmetic operations
        to test line-to-line and line-to-scalar operations.
        """
        self.bar_num = 0
        self.recorded_values = []

        # Keltner Channel indicator calculation
        self.middle_price = (
            self.datas[0].high + self.datas[0].low + self.datas[0].close
        ) / 3
        self.middle_line = bt.indicators.SMA(
            self.middle_price, period=self.p.avg_period
        )
        self.atr = bt.indicators.AverageTrueRange(
            self.datas[0], period=self.p.avg_period
        )
        self.upper_line = self.middle_line + self.atr * self.p.atr_multi
        self.lower_line = self.middle_line - self.atr * self.p.atr_multi

    def next(self):
        """Process each bar and record indicator values.

        Called for each bar after indicator warmup period. Records the
        values of all Keltner Channel indicators if they are valid (not NaN).
        """
        self.bar_num += 1

        def is_valid(v):
            return v is not None and not (isinstance(v, float) and math.isnan(v))

        middle_price_val = self.middle_price[0]
        middle_line_val = self.middle_line[0]
        atr_val = self.atr[0]
        upper_val = self.upper_line[0]
        lower_val = self.lower_line[0]

        if is_valid(middle_line_val) and is_valid(atr_val):
            self.recorded_values.append({
                'bar_num': self.bar_num,
                'middle_price': round(middle_price_val, 6),
                'middle_line': round(middle_line_val, 6),
                'atr': round(atr_val, 6),
                'upper_line': round(upper_val, 6),
                'lower_line': round(lower_val, 6),
            })


# ============================================================================
# Test case 3: TimeLine + SMA indicator calculation
# ============================================================================
class TimeLine(bt.Indicator):
    """Time-weighted average price indicator.

    This custom indicator calculates a cumulative running average of close
    prices from the beginning of the data feed. It serves as a test case
    for combining custom indicators with standard backtrader indicators.

    The indicator maintains a running sum and count of all prices seen
    so far, updating the average with each new bar.

    Attributes:
        lines.day_avg_price: Output line containing the cumulative average price.
        price_sum: Running sum of all close prices.
        price_count: Count of bars processed.

    Note:
        This indicator implements both next() (bar-by-bar) and once()
        (vectorized) calculation modes for testing both execution paths.
    """
    lines = ('day_avg_price',)

    def __init__(self):
        """Initialize the TimeLine indicator.

        Sets up the running sum and count for calculating cumulative average.
        """
        self.price_sum = 0.0
        self.price_count = 0

    def next(self):
        """Calculate the cumulative average for the current bar.

        Updates the running sum and count, then calculates the average.
        This is called for each bar in bar-by-bar execution mode.
        """
        self.price_count += 1
        self.price_sum += self.data.close[0]
        self.lines.day_avg_price[0] = self.price_sum / self.price_count
        self.current_datetime = bt.num2date(self.data.datetime[0])
        self.current_hour = self.current_datetime.hour
        self.current_minute = self.current_datetime.minute
        day_end_hour, day_end_minute, _ = self.p.day_end_time
        if self.current_hour == day_end_hour and self.current_minute == day_end_minute:
            self.day_close_price_list = []

    def once(self, start, end):
        """Vectorized calculation for runonce mode.

        Calculates all cumulative averages in a batch for improved performance.
        This is called when cerebro runs with runonce=True.

        Args:
            start: Starting index for calculation (typically 0).
            end: Ending index for calculation (length of data).
        """
        close_array = self.data.close.array
        dst = self.lines.day_avg_price.array

        # Ensure destination array is sized
        while len(dst) < end:
            dst.append(0.0)

        # Calculate running average for each bar
        price_sum = 0.0
        for i in range(min(end, len(close_array))):
            price_sum += close_array[i]
            dst[i] = price_sum / (i + 1)


class TimeLineSmaTestStrategy(bt.Strategy):
    """Test TimeLine + SMA indicator combination.

    This strategy tests combining a custom indicator (TimeLine) with a
    standard backtrader indicator (SMA). It verifies that custom indicators
    work correctly when used alongside built-in indicators.

    Attributes:
        bar_num: Counter for number of bars processed in next().
        recorded_values: List of dictionaries containing indicator values for
            each valid bar (after warmup period).
        day_avg_price: Custom TimeLine indicator (cumulative average).
        ma_value: Simple Moving Average of close prices.

    Parameters:
        ma_period: Period for SMA calculation (default: 20).
    """
    params = (
        ("ma_period", 20),
    )

    def __init__(self):
        """Initialize the TimeLine + SMA test strategy.

        Creates both custom TimeLine indicator and standard SMA indicator
        to test interoperability between custom and built-in indicators.
        """
        self.bar_num = 0
        self.recorded_values = []

        self.day_avg_price = TimeLine(self.datas[0])
        self.ma_value = bt.indicators.SMA(
            self.datas[0].close, period=self.p.ma_period
        )

    def next(self):
        """Process each bar and record indicator values.

        Called for each bar after indicator warmup period. Records the
        values of both TimeLine and SMA indicators if they are valid (not NaN).
        """
        self.bar_num += 1

        def is_valid(v):
            return v is not None and not (isinstance(v, float) and math.isnan(v))

        avg_price_val = self.day_avg_price[0]
        ma_val = self.ma_value[0]

        if is_valid(avg_price_val) and is_valid(ma_val):
            self.recorded_values.append({
                'bar_num': self.bar_num,
                'close': round(self.datas[0].close[0], 6),
                'day_avg_price': round(avg_price_val, 6),
                'ma_value': round(ma_val, 6),
            })


# ============================================================================
# Test case 4: Highest/Lowest indicator calculation
# ============================================================================
class HighestLowestTestStrategy(bt.Strategy):
    """Test Highest/Lowest indicator calculation.

    This strategy tests the Highest and Lowest indicators, which track
    the maximum and minimum values over a rolling window. These are
    commonly used for breakout strategies and support/resistance levels.

    Attributes:
        bar_num: Counter for number of bars processed in next().
        recorded_values: List of dictionaries containing indicator values for
            each valid bar (after warmup period).
        highest_high: Highest indicator tracking maximum high prices.
        lowest_low: Lowest indicator tracking minimum low prices.

    Parameters:
        period: Rolling window period for Highest/Lowest calculation (default: 20).
    """
    params = (
        ("period", 20),
    )

    def __init__(self):
        """Initialize the Highest/Lowest test strategy.

        Creates Highest and Lowest indicators to test rolling window
        maximum and minimum calculations.
        """
        self.bar_num = 0
        self.recorded_values = []

        self.highest_high = bt.indicators.Highest(
            self.datas[0].high, period=self.p.period
        )
        self.lowest_low = bt.indicators.Lowest(
            self.datas[0].low, period=self.p.period
        )

    def next(self):
        """Process each bar and record indicator values.

        Called for each bar after indicator warmup period. Records the
        values of Highest and Lowest indicators if they are valid (not NaN).
        """
        self.bar_num += 1

        def is_valid(v):
            return v is not None and not (isinstance(v, float) and math.isnan(v))

        highest_val = self.highest_high[0]
        lowest_val = self.lowest_low[0]

        if is_valid(highest_val) and is_valid(lowest_val):
            self.recorded_values.append({
                'bar_num': self.bar_num,
                'high': round(self.datas[0].high[0], 6),
                'low': round(self.datas[0].low[0], 6),
                'highest_high': round(highest_val, 6),
                'lowest_low': round(lowest_val, 6),
            })


# ============================================================================
# Test functions
# ============================================================================

def run_strategy(strategy_class, num_bars=100, seed=42, **kwargs):
    """Run a strategy with randomly generated data and return the strategy instance.

    Helper function that creates a cerebro instance, generates random OHLCV data,
    adds the specified strategy, runs the backtest, and returns the strategy
    instance for validation.

    Args:
        strategy_class: The strategy class to instantiate and run.
        num_bars: Number of bars to generate (default: 100).
        seed: Random seed for reproducibility (default: 42).
        **kwargs: Additional keyword arguments to pass to the strategy.

    Returns:
        bt.Strategy: The strategy instance after backtest completion.
    """
    cerebro = bt.Cerebro()

    # Generate random data
    data_list = generate_random_ohlcv_data(num_bars=num_bars, seed=seed)
    data = RandomDataFeed(data_list=data_list)
    cerebro.adddata(data)

    # Add strategy
    cerebro.addstrategy(strategy_class, **kwargs)

    # Run
    results = cerebro.run()
    return results[0]


def test_macd_ema_line_operations():
    """Test MACD EMA indicator vector operations.

    Validates that indicator arithmetic operations (subtraction, multiplication)
    produce correct results by comparing against known baseline values.

    The test verifies:
    - Bar count matches expected value
    - First recorded indicator values match expected
    - Last recorded indicator values match expected

    Raises:
        AssertionError: If any indicator values don't match expected baseline.
    """
    strategy = run_strategy(MacdEmaTestStrategy, num_bars=100, seed=42)

    # Verify bar count (actual bars entering next() will be less than 100 due to indicator warmup period)
    assert strategy.bar_num > 0, f"Expected positive bar count, got {strategy.bar_num}"
    print(f"Total bars processed in next(): {strategy.bar_num}")

    # Verify recorded values exist
    assert len(strategy.recorded_values) > 0, "No valid indicator values recorded"

    # Expected values (from master version) - verify key indicator values for specific bars
    EXPECTED_BAR_NUM = 73
    EXPECTED_FIRST_RECORD = {
        'bar_num': 1, 'ema_1': 103.716294, 'ema_2': 102.189275,
        'dif': 1.527019, 'dea': 0.819102, 'macd': 1.415833
    }
    EXPECTED_LAST_RECORD = {
        'bar_num': 73, 'ema_1': 102.306701, 'ema_2': 101.658218,
        'dif': 0.648483, 'dea': 0.388373, 'macd': 0.520219
    }

    # Get actual records
    first_valid = strategy.recorded_values[0] if strategy.recorded_values else None
    last_valid = strategy.recorded_values[-1] if strategy.recorded_values else None

    print(f"First valid record: {first_valid}")
    print(f"Last valid record: {last_valid}")
    print(f"Total valid records: {len(strategy.recorded_values)}")

    # Verify bar count
    assert strategy.bar_num == EXPECTED_BAR_NUM, \
        f"Bar count mismatch: expected {EXPECTED_BAR_NUM}, got {strategy.bar_num}"

    # Verify ema_1 value of first record
    if first_valid:
        assert abs(first_valid['ema_1'] - EXPECTED_FIRST_RECORD['ema_1']) < 1e-4, \
            f"First ema_1 mismatch: expected {EXPECTED_FIRST_RECORD['ema_1']}, got {first_valid['ema_1']}"
        assert abs(first_valid['ema_2'] - EXPECTED_FIRST_RECORD['ema_2']) < 1e-4, \
            f"First ema_2 mismatch: expected {EXPECTED_FIRST_RECORD['ema_2']}, got {first_valid['ema_2']}"
        assert abs(first_valid['dif'] - EXPECTED_FIRST_RECORD['dif']) < 1e-4, \
            f"First dif mismatch: expected {EXPECTED_FIRST_RECORD['dif']}, got {first_valid['dif']}"

    # Verify all indicator values of last record
    if last_valid:
        assert abs(last_valid['ema_1'] - EXPECTED_LAST_RECORD['ema_1']) < 1e-4, \
            f"Last ema_1 mismatch: expected {EXPECTED_LAST_RECORD['ema_1']}, got {last_valid['ema_1']}"
        assert abs(last_valid['ema_2'] - EXPECTED_LAST_RECORD['ema_2']) < 1e-4, \
            f"Last ema_2 mismatch: expected {EXPECTED_LAST_RECORD['ema_2']}, got {last_valid['ema_2']}"
        assert abs(last_valid['dif'] - EXPECTED_LAST_RECORD['dif']) < 1e-4, \
            f"Last dif mismatch: expected {EXPECTED_LAST_RECORD['dif']}, got {last_valid['dif']}"
        if last_valid['dea'] is not None and EXPECTED_LAST_RECORD['dea'] is not None:
            assert abs(last_valid['dea'] - EXPECTED_LAST_RECORD['dea']) < 1e-4, \
                f"Last dea mismatch: expected {EXPECTED_LAST_RECORD['dea']}, got {last_valid['dea']}"
        if last_valid['macd'] is not None and EXPECTED_LAST_RECORD['macd'] is not None:
            assert abs(last_valid['macd'] - EXPECTED_LAST_RECORD['macd']) < 1e-4, \
                f"Last macd mismatch: expected {EXPECTED_LAST_RECORD['macd']}, got {last_valid['macd']}"


def test_keltner_line_operations():
    """Test Keltner Channel indicator vector operations.

    Validates that Keltner Channel calculations involving addition, subtraction,
    and division of data lines and indicators produce correct results.

    The test verifies:
    - Bar count matches expected value
    - First recorded indicator values match expected
    - Last recorded indicator values match expected

    Raises:
        AssertionError: If any indicator values don't match expected baseline.
    """
    strategy = run_strategy(KeltnerTestStrategy, num_bars=100, seed=42)

    # Verify bar count (actual bars entering next() will be less than 100 due to indicator warmup period)
    assert strategy.bar_num > 0, f"Expected positive bar count, got {strategy.bar_num}"
    print(f"Total bars processed in next(): {strategy.bar_num}")

    # Verify recorded values exist
    assert len(strategy.recorded_values) > 0, "No valid indicator values recorded"

    # Expected values (from master version)
    EXPECTED_BAR_NUM = 80
    EXPECTED_FIRST_RECORD = {
        'bar_num': 1, 'middle_price': 102.743291, 'middle_line': 99.783775,
        'atr': 3.04598, 'upper_line': 105.875734, 'lower_line': 93.691816
    }
    EXPECTED_LAST_RECORD = {
        'bar_num': 80, 'middle_price': 104.871328, 'middle_line': 101.915361,
        'atr': 2.951128, 'upper_line': 107.817617, 'lower_line': 96.013105
    }

    # Get actual records
    first_valid = strategy.recorded_values[0] if strategy.recorded_values else None
    last_valid = strategy.recorded_values[-1] if strategy.recorded_values else None

    print(f"First valid record: {first_valid}")
    print(f"Last valid record: {last_valid}")
    print(f"Total valid records: {len(strategy.recorded_values)}")

    # Verify bar count
    assert strategy.bar_num == EXPECTED_BAR_NUM, \
        f"Bar count mismatch: expected {EXPECTED_BAR_NUM}, got {strategy.bar_num}"

    # Verify indicator values of first and last records
    if first_valid:
        assert abs(first_valid['middle_line'] - EXPECTED_FIRST_RECORD['middle_line']) < 1e-4, \
            f"First middle_line mismatch: expected {EXPECTED_FIRST_RECORD['middle_line']}, got {first_valid['middle_line']}"
        assert abs(first_valid['upper_line'] - EXPECTED_FIRST_RECORD['upper_line']) < 1e-4, \
            f"First upper_line mismatch: expected {EXPECTED_FIRST_RECORD['upper_line']}, got {first_valid['upper_line']}"
        assert abs(first_valid['lower_line'] - EXPECTED_FIRST_RECORD['lower_line']) < 1e-4, \
            f"First lower_line mismatch: expected {EXPECTED_FIRST_RECORD['lower_line']}, got {first_valid['lower_line']}"

    if last_valid:
        assert abs(last_valid['middle_line'] - EXPECTED_LAST_RECORD['middle_line']) < 1e-4, \
            f"Last middle_line mismatch: expected {EXPECTED_LAST_RECORD['middle_line']}, got {last_valid['middle_line']}"
        assert abs(last_valid['upper_line'] - EXPECTED_LAST_RECORD['upper_line']) < 1e-4, \
            f"Last upper_line mismatch: expected {EXPECTED_LAST_RECORD['upper_line']}, got {last_valid['upper_line']}"
        assert abs(last_valid['lower_line'] - EXPECTED_LAST_RECORD['lower_line']) < 1e-4, \
            f"Last lower_line mismatch: expected {EXPECTED_LAST_RECORD['lower_line']}, got {last_valid['lower_line']}"


def test_timeline_sma_line_operations():
    """Test TimeLine + SMA indicator combination.

    Validates that custom indicators (TimeLine) work correctly when combined
    with standard backtrader indicators (SMA).

    The test verifies:
    - Bar count matches expected value
    - First recorded indicator values match expected
    - Last recorded indicator values match expected

    Raises:
        AssertionError: If any indicator values don't match expected baseline.
    """
    strategy = run_strategy(TimeLineSmaTestStrategy, num_bars=100, seed=42)

    # Verify bar count (actual bars entering next() will be less than 100 due to indicator warmup period)
    assert strategy.bar_num > 0, f"Expected positive bar count, got {strategy.bar_num}"
    print(f"Total bars processed in next(): {strategy.bar_num}")

    # Verify recorded values exist
    assert len(strategy.recorded_values) > 0, "No valid indicator values recorded"

    # Expected values (from master version)
    EXPECTED_BAR_NUM = 81
    EXPECTED_FIRST_RECORD = {
        'bar_num': 1, 'close': 100.964345, 'day_avg_price': 99.517016, 'ma_value': 99.517016
    }
    EXPECTED_LAST_RECORD = {
        'bar_num': 81, 'close': 104.674652, 'day_avg_price': 100.662885, 'ma_value': 101.992377
    }

    # Get actual records
    first_valid = strategy.recorded_values[0] if strategy.recorded_values else None
    last_valid = strategy.recorded_values[-1] if strategy.recorded_values else None

    print(f"First valid record: {first_valid}")
    print(f"Last valid record: {last_valid}")
    print(f"Total valid records: {len(strategy.recorded_values)}")

    # Verify bar count
    assert strategy.bar_num == EXPECTED_BAR_NUM, \
        f"Bar count mismatch: expected {EXPECTED_BAR_NUM}, got {strategy.bar_num}"

    # Verify first and last records
    if first_valid:
        assert abs(first_valid['day_avg_price'] - EXPECTED_FIRST_RECORD['day_avg_price']) < 1e-4, \
            f"First day_avg_price mismatch: expected {EXPECTED_FIRST_RECORD['day_avg_price']}, got {first_valid['day_avg_price']}"
        assert abs(first_valid['ma_value'] - EXPECTED_FIRST_RECORD['ma_value']) < 1e-4, \
            f"First ma_value mismatch: expected {EXPECTED_FIRST_RECORD['ma_value']}, got {first_valid['ma_value']}"

    if last_valid:
        assert abs(last_valid['day_avg_price'] - EXPECTED_LAST_RECORD['day_avg_price']) < 1e-4, \
            f"Last day_avg_price mismatch: expected {EXPECTED_LAST_RECORD['day_avg_price']}, got {last_valid['day_avg_price']}"
        assert abs(last_valid['ma_value'] - EXPECTED_LAST_RECORD['ma_value']) < 1e-4, \
            f"Last ma_value mismatch: expected {EXPECTED_LAST_RECORD['ma_value']}, got {last_valid['ma_value']}"


def test_highest_lowest_line_operations():
    """Test Highest/Lowest indicator calculation.

    Validates that rolling window maximum and minimum indicators (Highest,
    Lowest) produce correct results.

    The test verifies:
    - Bar count matches expected value
    - First recorded indicator values match expected
    - Last recorded indicator values match expected

    Raises:
        AssertionError: If any indicator values don't match expected baseline.
    """
    strategy = run_strategy(HighestLowestTestStrategy, num_bars=100, seed=42)

    # Verify bar count (actual bars entering next() will be less than 100 due to indicator warmup period)
    assert strategy.bar_num > 0, f"Expected positive bar count, got {strategy.bar_num}"
    print(f"Total bars processed in next(): {strategy.bar_num}")

    # Verify recorded values exist
    assert len(strategy.recorded_values) > 0, "No valid indicator values recorded"

    # Expected values (from master version)
    EXPECTED_BAR_NUM = 81
    EXPECTED_FIRST_RECORD = {
        'bar_num': 1, 'high': 102.885526, 'low': 100.605869,
        'highest_high': 102.885526, 'lowest_low': 95.794978
    }
    EXPECTED_LAST_RECORD = {
        'bar_num': 81, 'high': 106.508498, 'low': 103.430834,
        'highest_high': 106.609724, 'lowest_low': 95.691099
    }

    # Get actual records
    first_valid = strategy.recorded_values[0] if strategy.recorded_values else None
    last_valid = strategy.recorded_values[-1] if strategy.recorded_values else None

    print(f"First valid record: {first_valid}")
    print(f"Last valid record: {last_valid}")
    print(f"Total valid records: {len(strategy.recorded_values)}")

    # Verify bar count
    assert strategy.bar_num == EXPECTED_BAR_NUM, \
        f"Bar count mismatch: expected {EXPECTED_BAR_NUM}, got {strategy.bar_num}"

    # Verify first and last records
    if first_valid:
        assert abs(first_valid['highest_high'] - EXPECTED_FIRST_RECORD['highest_high']) < 1e-4, \
            f"First highest_high mismatch: expected {EXPECTED_FIRST_RECORD['highest_high']}, got {first_valid['highest_high']}"
        assert abs(first_valid['lowest_low'] - EXPECTED_FIRST_RECORD['lowest_low']) < 1e-4, \
            f"First lowest_low mismatch: expected {EXPECTED_FIRST_RECORD['lowest_low']}, got {first_valid['lowest_low']}"

    if last_valid:
        assert abs(last_valid['highest_high'] - EXPECTED_LAST_RECORD['highest_high']) < 1e-4, \
            f"Last highest_high mismatch: expected {EXPECTED_LAST_RECORD['highest_high']}, got {last_valid['highest_high']}"
        assert abs(last_valid['lowest_low'] - EXPECTED_LAST_RECORD['lowest_low']) < 1e-4, \
            f"Last lowest_low mismatch: expected {EXPECTED_LAST_RECORD['lowest_low']}, got {last_valid['lowest_low']}"


def collect_baseline_values():
    """Collect baseline values from the master branch.

    This function runs all test strategies and prints the expected values
    for the first and last recorded bars. These values should be used as
    the baseline for comparison in the test functions.

    Usage:
        1. Switch to master branch: git checkout master
        2. Install master version: pip install -U .
        3. Run: python tests/add_tests/test_line_operations.py --collect-baseline
        4. Copy the output values to corresponding test functions

    The function outputs:
        - Total bar count for each strategy
        - First valid record values
        - Last valid record values
    """
    print("=" * 80)
    print("COLLECTING BASELINE VALUES FROM MASTER BRANCH")
    print("=" * 80)
    
    # MACD EMA Test
    print("\n### MACD EMA Test ###")
    strategy = run_strategy(MacdEmaTestStrategy, num_bars=100, seed=42)
    print(f"EXPECTED_BAR_NUM = {strategy.bar_num}")
    if strategy.recorded_values:
        first = strategy.recorded_values[0]
        last = strategy.recorded_values[-1]
        print(f"EXPECTED_FIRST_RECORD = {first}")
        print(f"EXPECTED_LAST_RECORD = {last}")
    
    # Keltner Test
    print("\n### Keltner Channel Test ###")
    strategy = run_strategy(KeltnerTestStrategy, num_bars=100, seed=42)
    print(f"EXPECTED_BAR_NUM = {strategy.bar_num}")
    if strategy.recorded_values:
        first = strategy.recorded_values[0]
        last = strategy.recorded_values[-1]
        print(f"EXPECTED_FIRST_RECORD = {first}")
        print(f"EXPECTED_LAST_RECORD = {last}")
    
    # TimeLine SMA Test
    print("\n### TimeLine + SMA Test ###")
    strategy = run_strategy(TimeLineSmaTestStrategy, num_bars=100, seed=42)
    print(f"EXPECTED_BAR_NUM = {strategy.bar_num}")
    if strategy.recorded_values:
        first = strategy.recorded_values[0]
        last = strategy.recorded_values[-1]
        print(f"EXPECTED_FIRST_RECORD = {first}")
        print(f"EXPECTED_LAST_RECORD = {last}")
    
    # Highest/Lowest Test
    print("\n### Highest/Lowest Test ###")
    strategy = run_strategy(HighestLowestTestStrategy, num_bars=100, seed=42)
    print(f"EXPECTED_BAR_NUM = {strategy.bar_num}")
    if strategy.recorded_values:
        first = strategy.recorded_values[0]
        last = strategy.recorded_values[-1]
        print(f"EXPECTED_FIRST_RECORD = {first}")
        print(f"EXPECTED_LAST_RECORD = {last}")
    
    print("\n" + "=" * 80)
    print("Baseline collection complete. Copy these values to the test functions.")
    print("=" * 80)


def test_run():
    """pytest entry point - Run all line operations tests.

    This function serves as the main test runner when executed via pytest.
    It runs all four line operation tests in sequence:
    1. MACD EMA test
    2. Keltner Channel test
    3. TimeLine + SMA test
    4. Highest/Lowest test

    Raises:
        AssertionError: If any test fails.
    """
    test_macd_ema_line_operations()
    test_keltner_line_operations()
    test_timeline_sma_line_operations()
    test_highest_lowest_line_operations()


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--collect-baseline':
        collect_baseline_values()
        sys.exit(0)
    
    print("=" * 60)
    print("Running MACD EMA Line Operations Test")
    print("=" * 60)
    test_macd_ema_line_operations()
    
    print("\n" + "=" * 60)
    print("Running Keltner Channel Line Operations Test")
    print("=" * 60)
    test_keltner_line_operations()
    
    print("\n" + "=" * 60)
    print("Running TimeLine + SMA Line Operations Test")
    print("=" * 60)
    test_timeline_sma_line_operations()
    
    print("\n" + "=" * 60)
    print("Running Highest/Lowest Line Operations Test")
    print("=" * 60)
    test_highest_lowest_line_operations()
    
    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)
