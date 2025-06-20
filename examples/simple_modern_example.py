"""
Simple Modern Parameter System Example

This example demonstrates the modern parameter system without the complexity
of full indicator replacement. It shows how to use modern parameter validation
in existing backtrader components.
"""

import sys
import os

# Add backtrader to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import backtrader as bt
from backtrader.parameters import ParameterDescriptor, Int, Float, Bool


class ModernStrategy(bt.Strategy):
    """
    Strategy demonstrating modern parameter system integration.
    
    This shows how to add modern parameter validation to existing
    backtrader strategies.
    """
    
    # Traditional parameters (for compatibility)
    params = (
        ('sma_period', 20),
        ('rsi_period', 14),
        ('position_size', 0.1),
    )
    
    def __init__(self):
        # Add modern parameter validation on top of traditional system
        self._setup_modern_parameters()
        
        # Use traditional indicators with validated parameters
        self.sma = bt.indicators.SimpleMovingAverage(
            self.data.close,
            period=self.validated_sma_period
        )
        
        self.rsi = bt.indicators.RSI(
            self.data.close,
            period=self.validated_rsi_period,
            upperband=70,
            lowerband=30
        )
        
        self.bb = bt.indicators.BollingerBands(
            self.data.close,
            period=self.validated_sma_period,
            devfactor=2.0
        )
        
        # Signal generation
        self.buy_signal = bt.indicators.CrossOver(self.data.close, self.sma)
        self.rsi_oversold = self.rsi < 30
        self.rsi_overbought = self.rsi > 70
    
    def _setup_modern_parameters(self):
        """Set up modern parameter validation."""
        
        # Define modern parameter descriptors for validation
        sma_validator = ParameterDescriptor(
            default=20,
            type_=int,
            validator=Int(min_val=5, max_val=200),
            doc="Period for Simple Moving Average",
            name='sma_period'
        )
        
        rsi_validator = ParameterDescriptor(
            default=14,
            type_=int,
            validator=Int(min_val=2, max_val=100),
            doc="Period for RSI calculation",
            name='rsi_period'
        )
        
        position_validator = ParameterDescriptor(
            default=0.1,
            type_=float,
            validator=Float(min_val=0.01, max_val=1.0),
            doc="Position size as fraction of portfolio",
            name='position_size'
        )
        
        # Validate existing parameters
        try:
            self.validated_sma_period = sma_validator.validate(self.params.sma_period)
            print(f"✓ SMA Period validated: {self.validated_sma_period}")
        except ValueError as e:
            print(f"✗ SMA Period validation failed: {e}")
            self.validated_sma_period = sma_validator.default
        
        try:
            self.validated_rsi_period = rsi_validator.validate(self.params.rsi_period)
            print(f"✓ RSI Period validated: {self.validated_rsi_period}")
        except ValueError as e:
            print(f"✗ RSI Period validation failed: {e}")
            self.validated_rsi_period = rsi_validator.default
        
        try:
            self.validated_position_size = position_validator.validate(self.params.position_size)
            print(f"✓ Position Size validated: {self.validated_position_size}")
        except ValueError as e:
            print(f"✗ Position Size validation failed: {e}")
            self.validated_position_size = position_validator.default
    
    def next(self):
        if not self.position:
            # Buy signals
            if (self.buy_signal > 0 and 
                self.rsi_oversold and 
                self.data.close <= self.bb.lines.bot):
                
                size = int(self.broker.get_cash() * self.validated_position_size / self.data.close[0])
                self.buy(size=size)
                print(f'BUY at {self.data.close[0]:.2f}, RSI: {self.rsi[0]:.2f}')
        
        else:
            # Sell signals
            if (self.buy_signal < 0 or 
                self.rsi_overbought or
                self.data.close >= self.bb.lines.top):
                
                self.sell()
                print(f'SELL at {self.data.close[0]:.2f}, RSI: {self.rsi[0]:.2f}')


def demonstrate_parameter_validation():
    """Demonstrate parameter validation features."""
    
    print("Modern Parameter Validation Demo")
    print("=" * 50)
    
    # Test parameter validation directly
    sma_param = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=5, max_val=200),
        doc="SMA Period",
        name='sma_period'
    )
    
    # Test valid values
    try:
        value = sma_param.validate(50)
        print(f"✓ Valid SMA period validated: {value}")
    except ValueError as e:
        print(f"✗ Failed: {e}")
    
    # Test invalid values
    try:
        value = sma_param.validate(300)  # Too high
        print(f"✗ Should have failed but got: {value}")
    except ValueError as e:
        print(f"✓ Correctly rejected invalid value: {e}")
    
    # Test type validation
    try:
        value = sma_param.validate('invalid')  # Wrong type
        print(f"✗ Should have failed but got: {value}")
    except ValueError as e:
        print(f"✓ Correctly rejected wrong type: {e}")
    
    # Test default value
    print(f"✓ Default value: {sma_param.default}")
    print(f"✓ Parameter documentation: {sma_param.doc}")
    print(f"✓ Parameter name: {sma_param.name}")
    print(f"✓ Parameter type: {sma_param.type_}")


def run_backtest_example():
    """Run a simple backtest example."""
    
    print("\nBacktest Example with Modern Parameters")
    print("=" * 50)
    
    # Create cerebro
    cerebro = bt.Cerebro()
    
    # Test parameter validation by trying different values
    test_strategies = [
        {'sma_period': 25, 'rsi_period': 12, 'position_size': 0.15},  # Valid
        {'sma_period': 5, 'rsi_period': 300, 'position_size': 0.05},   # RSI too high
        {'sma_period': 500, 'rsi_period': 14, 'position_size': 2.0},   # Both invalid
    ]
    
    for i, strategy_params in enumerate(test_strategies):
        print(f"\nTesting Strategy Configuration {i+1}: {strategy_params}")
        
        # Create a new cerebro for each test
        test_cerebro = bt.Cerebro()
        
        # Add strategy with test parameters
        test_cerebro.addstrategy(ModernStrategy, **strategy_params)
        
        # Create simple sample data
        import pandas as pd
        import numpy as np
        
        dates = pd.date_range('2020-01-01', periods=100, freq='D')
        np.random.seed(42)
        
        prices = 100 + np.cumsum(np.random.normal(0, 1, len(dates)))
        df = pd.DataFrame({
            'datetime': dates,
            'open': prices,
            'high': prices * 1.01,
            'low': prices * 0.99,
            'close': prices,
            'volume': 1000
        })
        df.set_index('datetime', inplace=True)
        
        data = bt.feeds.PandasData(dataname=df)
        test_cerebro.adddata(data)
        test_cerebro.broker.setcash(10000.0)
        
        try:
            print(f"  Starting Value: {test_cerebro.broker.getvalue():.2f}")
            results = test_cerebro.run()
            print(f"  Final Value: {test_cerebro.broker.getvalue():.2f}")
            print(f"  ✓ Strategy ran successfully with parameter validation")
        except Exception as e:
            print(f"  ✗ Strategy failed: {e}")


def run_example():
    """Run the complete example."""
    
    # First demonstrate parameter validation
    demonstrate_parameter_validation()
    
    # Then run backtest examples
    run_backtest_example()


if __name__ == '__main__':
    run_example()