- --

title: Analyzers
description: Strategy performance analysis

- --

# Analyzers

Analyzers calculate performance metrics for your strategies. Use them to evaluate strategy effectiveness.

## Basic Usage

```python
cerebro = bt.Cerebro()

# Add analyzer

cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')

# Run backtest

strats = cerebro.run()

# Get analyzer results

strat = strats[0]
sharpe = strat.analyzers.sharpe.get_analysis()
print(f'Sharpe Ratio: {sharpe["sharperatio"]:.3f}')

```bash

## Available Analyzers

### Return Analysis

```python

# Returns (basic return metrics)

cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

# Annual Return

cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annual_return')

# Log Returns (Rolling)

cerebro.addanalyzer(bt.analyzers.LogReturnsRolling, _name='log_returns')

```bash

### Risk Metrics

```python

# Sharpe Ratio

cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')

# Calmar Ratio

cerebro.addanalyzer(bt.analyzers.Calmar, _name='calmar')

# SQN (System Quality Number)

cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')

```bash

### Drawdown Analysis

```python

# Drawdown analyzer

cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

# Get results

drawdown = strat.analyzers.drawdown.get_analysis()
print(f'Max Drawdown: {drawdown["max"]["drawdown"]:.2%}')
print(f'Max Drawdown Money: {drawdown["max"]["moneydown"]:.2f}')
print(f'Max Drawdown Duration: {drawdown["max"]["len"]} days')

```bash

### Trade Analysis

```python

# Trade Analyzer

cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

# Get results

trades = strat.analyzers.trades.get_analysis()
print(f'Total trades: {trades["total"]["total"]}')
print(f'Win rate: {trades["won"]["total"] / trades["total"]["total"]:.2%}')
print(f'Avg win: {trades["won"]["pnl"]["average"]:.2f}')
print(f'Avg loss: {trades["lost"]["pnl"]["average"]:.2f}')

```bash

### Position Analysis

```python

# Positions Analyzer

cerebro.addanalyzer(bt.analyzers.Positions, _name='positions')

# Get results

positions = strat.analyzers.positions.get_analysis()
print(f'Total positions: {len(positions)}')

```bash

### Transactions Analysis

```python

# Transactions Analyzer

cerebro.addanalyzer(bt.analyzers.Transactions, _name='transactions')

# Get results

transactions = strat.analyzers.transactions.get_analysis()
print(f'Total transactions: {len(transactions)}')

```bash

### Period Statistics

```python

# Period Statistics (monthly, yearly, etc.)

cerebro.addanalyzer(bt.analyzers.PeriodStats, _name='period_stats')

# Get results

stats = strat.analyzers.period_stats.get_analysis()

```bash

### Time Return Analysis

```python

# Time Return (returns by time period)

cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='time_return')

# Get results

time_return = strat.analyzers.time_return.get_analysis()

```bash

### VWR (Volume Weighted Return)

```python

# Volume Weighted Return

cerebro.addanalyzer(bt.analyzers.VWR, _name='vwr')

# Get results

vwr = strat.analyzers.vwr.get_analysis()

```bash

### PyFolio Integration

```python

# PyFolio integration for advanced analysis

cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')

# Get results

pyfolio = strat.analyzers.pyfolio.get_analysis()

# Generate pyfolio tearsheet

returns, positions, transactions, gross_lev = pyfolio

```bash

## Complete Example

```python
import backtrader as bt
import datetime

class TestStrategy(bt.Strategy):
    pass

# Create cerebro

cerebro = bt.Cerebro()

# Add strategy

cerebro.addstrategy(TestStrategy)

# Add data

data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime.datetime(2023, 1, 1),
    todate=datetime.datetime(2023, 12, 31)
)
cerebro.adddata(data)

# Add analyzers

cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annual_return')

# Set broker

cerebro.broker.setcash(10000)
cerebro.broker.setcommission(0.001)

# Run

strats = cerebro.run()
strat = strats[0]

# Print results

print('-' *50)
print('ANALYSIS RESULTS')
print('-'*50)

# Returns

returns = strat.analyzers.returns.get_analysis()
print(f'Total return: {returns["rtot"]:.2%}')
print(f'average return: {returns["ravg"]:.2%}')

# Sharpe Ratio

sharpe = strat.analyzers.sharpe.get_analysis()
print(f'Sharpe Ratio: {sharpe["sharperatio"]:.3f}')

# Drawdown

drawdown = strat.analyzers.drawdown.get_analysis()
print(f'Max Drawdown: {drawdown["max"]["drawdown"]:.2%}')
print(f'Max Drawdown Duration: {drawdown["max"]["len"]} days')

# Trades

trades = strat.analyzers.trades.get_analysis()
print(f'Total trades: {trades["total"]["total"]}')
if trades["total"]["total"] > 0:
    print(f'Win rate: {trades["won"]["total"] / trades["total"]["total"]:.2%}')

# Annual Return

annual_return = strat.analyzers.annual_return.get_analysis()
print(f'Annual Return: {annual_return.get("rnorm", 0):.2%}')

print('-'* 50)
print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')

```bash

## Analyzer Output Format

Most analyzers return a dictionary with analysis results:

```python
analyzer = strat.analyzers.name.get_analysis()

# Common access patterns

for key, value in analyzer.items():
    print(f'{key}: {value}')

```bash

## Custom Analyzer

Create your own analyzer:

```python
class CustomAnalyzer(bt.Analyzer):
    """
    Custom analyzer example.
    """

    def __init__(self):
        super().__init__()
        self.trades = []
        self.start_cash = None

    def start(self):
        self.start_cash = self.strategy.broker.getcash()

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trades.append({
                'pnl': trade.pnl,
                'pnlnet': trade.pnlnet,
                'commission': trade.commission,
            })

    def get_analysis(self):
        return {
            'start_cash': self.start_cash,
            'total_trades': len(self.trades),
            'total_pnl': sum(t['pnl'] for t in self.trades),
            'total_commission': sum(t['commission'] for t in self.trades),
        }

```bash

## Next Steps

- [Observers](observers.md) - Monitor strategy behavior
- [Plotting](plotting.md) - Visualize results
