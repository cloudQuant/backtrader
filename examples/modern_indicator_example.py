"""
Modern Indicator Example using new parameter system

This example demonstrates how to create indicators using the modern
parameter system instead of metaclasses, providing better IDE support
and clearer code.
"""

import sys
import os

# Add backtrader to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import backtrader as bt
from backtrader.parameters import ParameterDescriptor, Int, Float, Bool
from backtrader.lineseries import ModernLineSeries


class ModernSimpleMovingAverage(ModernLineSeries):
    """
    Modern SMA indicator using the new parameter system.
    
    This indicator demonstrates:
    - Modern parameter validation
    - Type hints and documentation
    - Clear error messages
    - IDE-friendly development
    """
    
    # Define lines
    lines = ('sma',)
    
    # Modern parameter definitions with validation
    period = ParameterDescriptor(
        default=30,
        type_=int,
        validator=Int(min_val=1, max_val=1000),
        doc="Number of periods for the moving average",
        name='period'
    )
    
    # Plotting configuration
    plotinfo = dict(plot=True, subplot=False, plotname='Modern SMA')
    plotlines = dict(sma=dict(color='blue', linestyle='-', linewidth=1.5))
    
    def __init__(self, data=None, **kwargs):
        # Initialize parent first
        super().__init__(**kwargs)
        
        # Set data if provided
        if data is not None:
            self.data = data
            self.datas = [data]
        
        # Calculate simple moving average
        if hasattr(self, 'data'):
            self.lines.sma = bt.indicators.SimpleMovingAverage(
                self.data.close, 
                period=self.p.period
            )
    
    def next(self):
        # Optional: custom logic on each bar
        pass


class ModernRSI(ModernLineSeries):
    """
    Modern RSI indicator with enhanced parameter validation.
    """
    
    lines = ('rsi',)
    
    # Parameters with comprehensive validation
    period = ParameterDescriptor(
        default=14,
        type_=int,
        validator=Int(min_val=2, max_val=100),
        doc="Period for RSI calculation",
        name='period'
    )
    
    upperband = ParameterDescriptor(
        default=70.0,
        type_=float,
        validator=Float(min_val=50.0, max_val=100.0),
        doc="Upper overbought threshold",
        name='upperband'
    )
    
    lowerband = ParameterDescriptor(
        default=30.0,
        type_=float,
        validator=Float(min_val=0.0, max_val=50.0),
        doc="Lower oversold threshold", 
        name='lowerband'
    )
    
    safe_mode = ParameterDescriptor(
        default=True,
        type_=bool,
        validator=Bool(),
        doc="Use safe division to avoid division by zero",
        name='safe_mode'
    )
    
    # Plotting configuration
    plotinfo = dict(
        plot=True,
        subplot=True,
        plotname='Modern RSI',
        plotyhlines=[30, 70],
        plotyticks=[30, 50, 70]
    )
    
    plotlines = dict(
        rsi=dict(color='purple', linewidth=1.0)
    )
    
    def __init__(self, data=None, **kwargs):
        # Initialize parent first
        super().__init__(**kwargs)
        
        # Set data if provided
        if data is not None:
            self.data = data
            self.datas = [data]
        
        # Use built-in RSI or implement custom logic
        if hasattr(self, 'data'):
            self.lines.rsi = bt.indicators.RSI(
                self.data.close,
                period=self.p.period,
                upperband=self.p.upperband,
                lowerband=self.p.lowerband,
                safediv=self.p.safe_mode
            )


class ModernBollingerBands(ModernLineSeries):
    """
    Modern Bollinger Bands indicator with multiple lines.
    """
    
    lines = ('mid', 'top', 'bot')
    
    # Parameters
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=2, max_val=200),
        doc="Period for moving average",
        name='period'
    )
    
    devfactor = ParameterDescriptor(
        default=2.0,
        type_=float,
        validator=Float(min_val=0.1, max_val=10.0),
        doc="Standard deviation factor",
        name='devfactor'
    )
    
    # Plotting configuration
    plotinfo = dict(plot=True, subplot=False, plotname='Modern Bollinger Bands')
    plotlines = dict(
        mid=dict(color='blue', linestyle='-'),
        top=dict(color='red', linestyle='--'),
        bot=dict(color='green', linestyle='--')
    )
    
    def __init__(self, data=None, **kwargs):
        # Initialize parent first
        super().__init__(**kwargs)
        
        # Set data if provided
        if data is not None:
            self.data = data
            self.datas = [data]
        
        # Use built-in Bollinger Bands
        if hasattr(self, 'data'):
            bb = bt.indicators.BollingerBands(
                self.data.close,
                period=self.p.period,
                devfactor=self.p.devfactor
            )
            
            self.lines.mid = bb.lines.mid
            self.lines.top = bb.lines.top  
            self.lines.bot = bb.lines.bot


class ModernStrategy(bt.Strategy):
    """
    Modern strategy using the new indicators.
    """
    
    # Strategy parameters using old-style for compatibility
    params = (
        ('sma_period', 20),
        ('rsi_period', 14),
        ('bb_period', 20),
        ('position_size', 0.1),
    )
    
    def __init__(self):
        # Use modern indicators with data and parameter passing
        self.sma = ModernSimpleMovingAverage(
            data=self.data,
            period=self.params.sma_period
        )
        
        self.rsi = ModernRSI(
            data=self.data,
            period=self.params.rsi_period,
            upperband=75.0,
            lowerband=25.0,
            safe_mode=True
        )
        
        self.bb = ModernBollingerBands(
            data=self.data,
            period=self.params.bb_period,
            devfactor=2.5
        )
        
        # Signal generation
        self.buy_signal = bt.indicators.CrossOver(self.data.close, self.sma.sma)
        self.rsi_oversold = self.rsi.rsi < self.rsi.p.lowerband
        self.rsi_overbought = self.rsi.rsi > self.rsi.p.upperband
    
    def next(self):
        if not self.position:
            # Buy signals
            if (self.buy_signal > 0 and 
                self.rsi_oversold and 
                self.data.close <= self.bb.bot):
                
                size = int(self.broker.get_cash() * self.params.position_size / self.data.close[0])
                self.buy(size=size)
                print(f'BUY at {self.data.close[0]:.2f}, RSI: {self.rsi.rsi[0]:.2f}')
        
        else:
            # Sell signals
            if (self.buy_signal < 0 or 
                self.rsi_overbought or
                self.data.close >= self.bb.top):
                
                self.sell()
                print(f'SELL at {self.data.close[0]:.2f}, RSI: {self.rsi.rsi[0]:.2f}')


def run_example():
    """Run the modern indicator example."""
    
    print("Modern Indicator Example")
    print("=" * 50)
    
    # Create cerebro
    cerebro = bt.Cerebro()
    
    # Add strategy
    cerebro.addstrategy(ModernStrategy, 
                       sma_period=25,
                       rsi_period=12,
                       bb_period=18)
    
    # Create sample data
    import pandas as pd
    import numpy as np
    
    # Generate sample OHLCV data
    dates = pd.date_range('2020-01-01', periods=1000, freq='D')
    np.random.seed(42)  # For reproducible results
    
    # Create realistic price data with trends
    base_price = 100
    price_changes = np.random.normal(0.001, 0.02, len(dates))  # 0.1% mean, 2% volatility
    prices = [base_price]
    
    for change in price_changes:
        prices.append(prices[-1] * (1 + change))
    
    prices = np.array(prices[1:])  # Remove initial base price
    
    # Create OHLC data
    highs = prices * (1 + np.abs(np.random.normal(0, 0.01, len(prices))))
    lows = prices * (1 - np.abs(np.random.normal(0, 0.01, len(prices))))
    opens = np.roll(prices, 1)
    opens[0] = base_price
    volumes = np.random.randint(1000, 10000, len(prices))
    
    # Create DataFrame
    df = pd.DataFrame({
        'datetime': dates,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': prices,
        'volume': volumes
    })
    
    df.set_index('datetime', inplace=True)
    
    # Add data to cerebro
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    
    # Set initial cash
    cerebro.broker.setcash(10000.0)
    
    # Add commission
    cerebro.broker.setcommission(commission=0.001)
    
    print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')
    
    # Run backtest
    results = cerebro.run()
    
    print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')
    print(f'Return: {(cerebro.broker.getvalue() / 10000 - 1) * 100:.2f}%')
    
    # Display parameter information
    strategy = results[0]
    
    print("\nModern Indicator Parameters:")
    print("-" * 30)
    
    # Show RSI parameters
    print(f"RSI Period: {strategy.rsi.p.period}")
    print(f"RSI Upper Band: {strategy.rsi.p.upperband}")
    print(f"RSI Lower Band: {strategy.rsi.p.lowerband}")
    print(f"RSI Safe Mode: {strategy.rsi.p.safe_mode}")
    
    # Show Bollinger Bands parameters
    print(f"BB Period: {strategy.bb.p.period}")
    print(f"BB Dev Factor: {strategy.bb.p.devfactor}")
    
    return cerebro, results


if __name__ == '__main__':
    cerebro, results = run_example()
    
    # Optional: Plot results (requires matplotlib)
    try:
        import matplotlib
        matplotlib.use('Agg')  # Use non-GUI backend
        cerebro.plot(style='candlestick', barup='green', bardown='red')
        print("Plot saved (if matplotlib available)")
    except ImportError:
        print("Matplotlib not available - skipping plot")
    except Exception as e:
        print(f"Plotting error: {e}")