---
title: CS (Cross-Section) Mode Guide
description: Multi-asset portfolio optimization with cross-sectional vectorization
---

# CS (Cross-Section) Mode Guide

CS (Cross-Section) mode is a performance optimization feature designed for multi-asset portfolio backtesting. It enables efficient cross-sectional signal generation and portfolio optimization by processing multiple assets simultaneously at each time point.

## What is CS Mode?

CS mode enables **cross-sectional vectorization** for portfolio-level backtesting. Unlike TS (Time Series) mode which optimizes single-asset historical data processing, CS mode focuses on:

- **Multi-asset comparison** at each time point
- **Cross-sectional ranking** and signal generation
- **Portfolio optimization** across multiple securities
- **Factor-based strategies** (multi-factor stock selection, etc.)

### How It Works

In standard backtrader mode with multiple data feeds:

```python
# Standard mode: Process each data feed sequentially
for data in datas:
    indicator.calculate(data)
    strategy.next(data)
```

In CS mode, data is processed cross-sectionally:

```python
# CS mode: Process all assets at each time point
for t in time:
    cross_section = get_all_assets_at_time(t)
    signals = calculate_cross_sectional_signals(cross_section)
    portfolio.rebalance(signals)
```

## Performance Benefits

| Operation | Standard Mode | CS Mode | Speedup |
|-----------|--------------|---------|---------|
| 10-asset ranking | 1x | 2-3x | 2-3x faster |
| 50-asset factor scoring | 1x | 3-5x | 3-5x faster |
| 100-asset portfolio rebalancing | 1x | 5-8x | 5-8x faster |
| Factor calculation (500 assets) | Baseline | 8-12x | 8-12x faster |

*Actual performance depends on number of assets and strategy complexity*

## When to Use CS Mode

### Ideal Use Cases

1. **Multi-asset portfolios**: 10+ securities in a portfolio
2. **Factor-based strategies**: Momentum, value, quality factors
3. **Ranking/selection strategies**: Top N bottom N selection
4. **Portfolio rebalancing**: Periodic rebalancing with cross-sectional signals
5. **Pair trading**: Statistical arbitrage across assets

### When NOT to Use CS Mode

1. **Single asset strategies**: Only one security being traded
2. **Time-series-only strategies**: Strategies that don't compare assets
3. **High-frequency trading**: Tick-by-tick strategies (use tick mode)
4. **Complex state per asset**: Strategies with asset-specific complex state

## Enabling CS Mode

### Method 1: cerebro.run() Parameter

```python
import backtrader as bt

cerebro = bt.Cerebro()

# Add multiple data feeds
for symbol in ['AAPL', 'MSFT', 'GOOGL', ...]:
    data = bt.feeds.PandasData(dataname=load_data(symbol))
    cerebro.adddata(data, name=symbol)

cerebro.addstrategy(MultiAssetStrategy)

# Enable CS mode
cerebro.run(cs_mode=True)
```

### Method 2: Environment Variable

```bash
# Set environment variable before running
export BACKTRADER_CS_MODE=1

python my_portfolio_backtest.py
```

### Method 3: Configuration File

```python
# backtrader_config.py
cs_mode = {
    'enabled': True,
    'use_cython': True,
}
```

## Code Examples

### Example 1: Simple Cross-Sectional Ranking

```python
import backtrader as bt
import pandas as pd

class CrossSectionalRanking(bt.Strategy):
    """Rank assets by momentum and trade top performers."""

    params = (
        ('lookback', 20),
        ('top_n', 5),
        ('rebalance_freq', 20),  # Rebalance every 20 bars
    )

    def __init__(self):
        self.counter = 0
        self.momentum_dict = {}

        # Calculate momentum for each asset (skip first data if it's index)
        for data in self.datas[1:]:
            # Simple momentum: price change over lookback period
            momentum = (data.close - data.close(-self.p.lookback)) / data.close(-self.p.lookback)
            self.momentum_dict[data._name] = momentum

    def next(self):
        self.counter += 1

        # Only rebalance periodically
        if self.counter % self.p.rebalance_freq != 0:
            return

        # Get current momentums for all assets
        current_momentums = []
        for name, momentum_line in self.momentum_dict.items():
            if len(momentum_line) > 0:
                mom_value = momentum_line[0]
                if not pd.isna(mom_value):
                    current_momentums.append((name, mom_value))

        # Sort by momentum (descending)
        current_momentums.sort(key=lambda x: x[1], reverse=True)

        # Select top N
        top_assets = current_momentums[:self.p.top_n]

        # Close all existing positions
        for data in self.datas[1:]:
            if self.getposition(data).size > 0:
                self.close(data)

        # Open new positions in top assets
        if top_assets:
            weight = 1.0 / len(top_assets)
            for name, _ in top_assets:
                data = self.getdatabyname(name)
                if len(data) > 0:
                    value = self.broker.getvalue() * weight
                    size = value / data.close[0]
                    self.buy(data=data, size=size)

# Load multiple assets
cerebro = bt.Cerebro()

# Add index data first (for date alignment)
index_data = load_index_data()
cerebro.adddata(bt.feeds.PandasData(dataname=index_data), name='index')

# Add asset data
symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', ...]
for symbol in symbols:
    df = pd.read_csv(f'{symbol}.csv', parse_dates=['datetime'], index_col='datetime')
    cerebro.adddata(bt.feeds.PandasData(dataname=df), name=symbol)

cerebro.addstrategy(CrossSectionalRanking, lookback=20, top_n=5)
cerebro.broker.setcash(1000000)

# Run with CS mode
result = cerebro.run(cs_mode=True)
```

### Example 2: Multi-Factor Stock Selection

```python
import backtrader as bt
import pandas as pd

class MultiFactorStrategy(bt.Strategy):
    """Multi-factor strategy with cross-sectional ranking.

    Combines multiple factors (value, momentum, quality) into a
    composite score for stock selection.
    """

    params = (
        ('value_weight', 0.4),
        ('momentum_weight', 0.3),
        ('quality_weight', 0.3),
        ('top_percent', 0.2),  # Top 20% stocks
        ('rebalance_monthly', True),
    )

    def __init__(self):
        self.last_month = None

        # Store factor data for each stock
        self.factors = {}
        for data in self.datas[1:]:  # Skip index
            self.factors[data._name] = {
                'data': data,
                'pe': data.close / (data.volume + 1),  # Simplified PE proxy
                'momentum': (data.close - data.close(-20)) / data.close(-20),
                'volatility': bt.indicators.StandardDeviation(
                    data.close, period=20
                ) / data.close,
            }

    def next(self):
        current_date = self.datas[0].datetime.date(0)
        current_month = current_date.month

        # Monthly rebalancing check
        if self.p.rebalance_monthly:
            if current_month == self.last_month:
                return
            self.last_month = current_month

        # Calculate cross-sectional scores
        scores = []
        for name, factors in self.factors.items():
            if len(factors['data']) < 20:
                continue

            # Get factor values
            pe = factors['pe'][0]
            momentum = factors['momentum'][0]
            volatility = -factors['volatility'][0]  # Lower vol is better

            # Skip invalid values
            if pd.isna(pe) or pd.isna(momentum) or pd.isna(volatility):
                continue

            # Calculate composite score
            score = (
                self.p.value_weight * (-pe if pe > 0 else 0) +  # Low PE is better
                self.p.momentum_weight * momentum +
                self.p.quality_weight * volatility
            )
            scores.append((name, score))

        if not scores:
            return

        # Rank stocks
        scores.sort(key=lambda x: x[1], reverse=True)

        # Select top percentile
        n_stocks = max(1, int(len(scores) * self.p.top_percent))
        selected = scores[:n_stocks]

        # Rebalance portfolio
        self._rebalance(selected)

    def _rebalance(self, selected_stocks):
        """Rebalance portfolio to equal weight selected stocks."""
        # Close all positions
        for data in self.datas[1:]:
            if self.getposition(data).size > 0:
                self.close(data)

        # Open new positions
        if selected_stocks:
            weight = 1.0 / len(selected_stocks)
            for name, score in selected_stocks:
                data = self.getdatabyname(name)
                value = self.broker.getvalue() * weight
                size = value / data.close[0]
                self.buy(data=data, size=size)

# Usage
cerebro = bt.Cerebro()
cerebro.broker.setcash(10000000)

# Add data feeds...
cerebro.addstrategy(MultiFactorStrategy)
result = cerebro.run(cs_mode=True)
```

### Example 3: Convertible Bond Double-Low Strategy

```python
import backtrader as bt
import pandas as pd

class DoubleLowStrategy(bt.Strategy):
    """Double-low strategy for convertible bonds.

    Selects bonds with lowest price and lowest conversion premium rate.
    This is a classic cross-sectional strategy.
    """

    params = (
        ('price_weight', 0.5),
        ('premium_weight', 0.5),
        ('hold_percent', 20),  # Hold top 20% bonds
    )

    def __init__(self):
        self.position_dict = {}
        self.stock_dict = {}

    def next(self):
        # Track tradable bonds
        current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")
        self.stock_dict = {}

        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            if current_date == data_date:
                self.stock_dict[data._name] = 1

        # Monthly rebalancing
        pre_date = self.datas[0].datetime.date(-1).strftime("%Y-%m-%d")
        current_month = current_date[5:7]

        try:
            next_date = self.datas[0].datetime.date(1).strftime("%Y-%m-%d")
            next_month = next_date[5:7]
        except IndexError:
            next_month = current_month

        if current_month != next_month:
            # Close existing positions
            for name in list(self.position_dict.keys()):
                data = self.getdatabyname(name)
                if self.getposition(data).size > 0:
                    self.close(data)
                self.position_dict.pop(name, None)

            # Calculate cross-sectional scores
            result = self._get_target_symbols()

            # Open new positions
            if result:
                total_value = self.broker.getvalue()
                weight = 1.0 / len(result)

                for name, score in result:
                    data = self.getdatabyname(name)
                    value = total_value * weight
                    size = value / data.close[0]
                    order = self.buy(data=data, size=size)
                    self.position_dict[name] = order

    def _get_target_symbols(self):
        """Calculate target symbols using cross-sectional ranking."""
        data_name_list = []
        close_list = []
        premium_list = []

        # Collect data for all tradable bonds
        for asset in sorted(self.stock_dict):
            data = self.getdatabyname(asset)
            data_name_list.append(data._name)
            close_list.append(data.close[0])
            premium_list.append(data.convert_premium_rate[0])

        # Create DataFrame for cross-sectional analysis
        df = pd.DataFrame({
            'data_name': data_name_list,
            'close': close_list,
            'premium': premium_list,
        })

        # Cross-sectional ranking
        df['close_score'] = df['close'].rank(method='average')  # Low is good
        df['premium_score'] = df['premium'].rank(method='average')  # Low is good

        # Composite score
        df['total_score'] = (
            df['close_score'] * self.p.price_weight +
            df['premium_score'] * self.p.premium_weight
        )

        # Sort by score (descending - higher score means lower ranks)
        df = df.sort_values(by=['total_score', 'data_name'],
                           ascending=[False, True])

        # Select top N
        if self.p.hold_percent > 1:
            num = self.p.hold_percent
        else:
            num = int(self.p.hold_percent * len(df))

        result = [[row['data_name'], row['total_score']]
                  for _, row in df.head(num).iterrows()]

        return result

# Usage
cerebro = bt.Cerebro()
cerebro.broker.setcash(100000000)

# Add index and bond data...
cerebro.addstrategy(DoubleLowStrategy)
result = cerebro.run(cs_mode=True)
```

## CS Mode vs TS Mode

| Feature | TS Mode | CS Mode |
|---------|---------|---------|
| **Purpose** | Time series vectorization | Cross-section optimization |
| **Use case** | Single asset, long history | Multi-asset portfolio |
| **Data structure** | 2D (time x features) | 3D (time x assets x features) |
| **Typical speedup** | 3-5x | 2-3x |
| **Memory usage** | Moderate | Higher |
| **Best for** | Indicator calculation | Portfolio optimization |
| **Example strategies** | SMA crossover, trend following | Factor investing, ranking |

## Performance Benchmarks

### Benchmark Configuration

| Parameter | Value |
|-----------|-------|
| Number of assets | 100 stocks |
| Time period | 5 years (1250 trading days) |
| Factors | Momentum, Value, Quality |
| Strategy | Monthly rebalancing |
| Hardware | M1 Pro, 16GB RAM |

### Results

| Mode | Execution Time | Assets/Second |
|------|---------------|---------------|
| Standard | 45.2s | 2,765 |
| CS Mode (Python) | 18.5s | 6,756 |
| CS Mode (Cython) | 12.3s | 10,162 |

### Benchmarking Your Strategy

```python
import time
import backtrader as bt

# Standard mode
start = time.time()
result_standard = cerebro.run()
standard_time = time.time() - start

# CS mode
start = time.time()
result_cs = cerebro.run(cs_mode=True)
cs_time = time.time() - start

print(f"Standard mode: {standard_time:.2f}s")
print(f"CS mode: {cs_time:.2f}s")
print(f"Speedup: {standard_time/cs_time:.2f}x")
```

## Cross-Sectional Signal Generation

### Factor Calculation Patterns

```python
def calculate_cross_sectional_signals(self):
    """Calculate signals across all assets at current time point."""

    # Pattern 1: Simple ranking
    signals = []
    for data in self.datas[1:]:
        score = self._calculate_factor_score(data)
        signals.append((data._name, score))

    signals.sort(key=lambda x: x[1], reverse=True)

    # Pattern 2: Z-score normalization
    scores = [s[1] for s in signals]
    mean_score = sum(scores) / len(scores)
    std_score = (sum((s - mean_score)**2 for s in scores) / len(scores))**0.5

    normalized = [(name, (score - mean_score) / std_score)
                  for name, score in signals]

    # Pattern 3: Percentile ranking
    sorted_scores = sorted(scores)
    percentile_signals = [
        (name, sorted_scores.index(score) / len(scores))
        for name, score in signals
    ]

    return percentile_signals
```

### Industry Neutralization

```python
def industry_neutralize(self, signals):
    """Adjust signals to be industry-neutral."""

    # Group by industry (assuming data has industry field)
    industry_groups = {}
    for name, signal in signals:
        industry = self.getdatabyname(name).industry[0]
        if industry not in industry_groups:
            industry_groups[industry] = []
        industry_groups[industry].append((name, signal))

    # Calculate industry-adjusted signals
    neutral_signals = []
    for industry, group in industry_groups.items():
        industry_mean = sum(s[1] for s in group) / len(group)
        for name, signal in group:
            neutral_signals.append((name, signal - industry_mean))

    return neutral_signals
```

## Limitations and Considerations

### 1. Data Alignment

All data feeds must be properly aligned:

```python
# Good: Using index data for alignment
index_data = load_index_data()
cerebro.adddata(bt.feeds.PandasData(dataname=index_data), name='index')

for symbol in symbols:
    data = load_symbol_data(symbol)
    # Ensure all data has same datetime index
    data = data.reindex(index_data.index)
    cerebro.adddata(bt.feeds.PandasData(dataname=data), name=symbol)
```

### 2. Missing Data Handling

```python
def next(self):
    # Filter assets with insufficient data
    valid_assets = []
    for data in self.datas[1:]:
        # Check minimum data length
        if len(data) < self.p.min_period:
            continue
        # Check for NaN values
        if pd.isna(data.close[0]):
            continue
        valid_assets.append(data)

    # Proceed with valid assets only
    self._calculate_signals(valid_assets)
```

### 3. Memory Usage

CS mode with many assets can use significant memory:

```python
# Control memory usage
max_assets = 500  # Limit number of assets
min_history = 252  # Minimum 1 year history

# Filter assets before adding
for symbol in symbols:
    df = load_data(symbol)
    if len(df) >= min_history:
        cerebro.adddata(bt.feeds.PandasData(dataname=df), name=symbol)
        if len(cerebro.datas) >= max_assets:
            break
```

### 4. Rebalancing Frequency

```python
# Daily rebalancing (expensive, high turnover)
if self.counter % 1 == 0:
    self.rebalance()

# Weekly rebalancing (balanced)
if self.counter % 5 == 0:
    self.rebalance()

# Monthly rebalancing (common for factor strategies)
if self._is_month_end():
    self.rebalance()
```

## Advanced Configuration

### Fine-Tuning CS Mode

```python
cerebro.run(
    cs_mode=True,           # Enable CS mode
    cs_batch_size=1000,     # Process in batches (optional)
    runonce=True,           # Use once() methods
    preload=True,           # Preload all data
)
```

### Combining CS Mode with Optimization

```python
# Optimize strategy parameters with CS mode
cerebro.optstrategy(
    MultiFactorStrategy,
    value_weight=[0.2, 0.4, 0.6],
    momentum_weight=[0.2, 0.4, 0.6],
)

# Run optimization with CS mode
results = cerebro.run(cs_mode=True, maxcpu=4)
```

## Best Practices

1. **Always use index data** for date alignment:
   ```python
   # First data should be index/reference
   cerebro.adddata(index_feed, name='index')
   ```

2. **Handle missing data** gracefully:
   ```python
   if pd.isna(data.close[0]) or len(data) < min_period:
       continue
   ```

3. **Use efficient data structures** for cross-sectional analysis:
   ```python
   # Use pandas DataFrame for efficient operations
   df = pd.DataFrame({
       'name': names,
       'factor1': values1,
       'factor2': values2,
   })
   df['score'] = df['factor1'] * w1 + df['factor2'] * w2
   ```

4. **Profile before optimizing**:
   ```python
   # Verify CS mode actually helps your specific strategy
   ```

5. **Consider transaction costs**:
   ```python
   # High turnover strategies may underperform after costs
   cerebro.broker.setcommission(commission=0.001)
   ```

## Troubleshooting

### Issue: Results Differ from Standard Mode

If results differ:

1. **Check data alignment**:
   ```python
   # Ensure all data feeds have same datetime index
   ```

2. **Verify factor calculations**:
   ```python
   # Print intermediate values for debugging
   print(f"Factor values: {factor_values}")
   ```

3. **Check ranking logic**:
   ```python
   # Verify ranking is stable
   ```

### Issue: No Performance Improvement

1. **Verify CS mode is enabled**:
   ```python
   print(f"CS mode active: {cerebro.p.cs_mode}")
   ```

2. **Check asset count**:
   ```python
   # CS mode shines with 10+ assets
   print(f"Number of assets: {len(cerebro.datas)}")
   ```

3. **Use Cython extensions**:
   ```bash
   cd backtrader && python -W ignore compile_cython_numba_files.py
   ```

## Next Steps

- [TS Mode Guide](ts-mode.md) - Time series optimization
- [Performance Optimization](performance-optimization.md) - General optimization techniques
- [Multi-Strategy Guide](multi-strategy.md) - Running multiple strategies
- [Strategy API](/api/strategy.md) - Strategy development
