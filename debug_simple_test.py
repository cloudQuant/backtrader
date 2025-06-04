#!/usr/bin/env python

import backtrader as bt

# Test just creating a simple data first
print("Creating data...")
try:
    data = bt.feeds.BacktraderCSVData(dataname='tests/original_tests/../datas/2006-day-001.txt')
    print(f"Data created successfully: {data}")
    print(f"Data type: {type(data)}")
    print(f"Data MRO: {type(data).__mro__}")
except Exception as e:
    print(f"Error creating data: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*50 + "\n")

# Test SMA class MRO
print("SMA class information:")
sma_cls = bt.indicators.SMA
print(f"SMA class: {sma_cls}")
print(f"SMA MRO: {sma_cls.__mro__}")

# Check if LineIterator is in the MRO
for i, cls in enumerate(sma_cls.__mro__):
    print(f"  MRO[{i}]: {cls}")
    if hasattr(cls, '__init__'):
        print(f"    -> has __init__")

print("\n" + "="*50 + "\n")

# Test the parameter system more specifically
print("Testing parameter system...")
print(f"Data feed attributes: {dir(data)}")
print(f"Data has lines: {hasattr(data, 'lines')}")
print(f"Data has _getlinealias: {hasattr(data, '_getlinealias')}")
print(f"Data has datetime: {hasattr(data, 'datetime')}")
print(f"Data has _name: {hasattr(data, '_name')}")
if hasattr(data, '_name'):
    print(f"Data._name: {data._name}")
print(f"Data class name: {data.__class__.__name__}")
print(f"Data has 'Data' in class hierarchy: {any('Data' in cls_name for cls_name in [data.__class__.__name__] + [base.__name__ for base in data.__class__.__mro__])}")

try:
    # First create an SMA instance without period to see if default works
    print("Creating SMA with default period...")
    sma_default = bt.indicators.SMA(data)
    print(f"SMA created successfully: {sma_default}")
    print(f"SMA has parameters? {hasattr(sma_default, 'p')}")
    if hasattr(sma_default, 'p'):
        print(f"SMA.p: {sma_default.p}")
        print(f"SMA.p.period: {sma_default.p.period}")
    
except Exception as e:
    print(f"Error in SMA creation with defaults: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*30 + "\n")

# Test creating SMA with actual arguments like the real usage
print("Testing SMA creation with arguments...")
try:
    print("Creating SMA with data and period arguments...")
    sma = bt.indicators.SMA(data, period=25)
    print(f"SMA created successfully: {sma}")
    print(f"SMA type: {type(sma)}")
    
    # Test if self.data and self.p are available
    print(f"SMA.data: {sma.data}")
    print(f"SMA.p.period: {sma.p.period}")
    
except Exception as e:
    print(f"Error in SMA creation: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*50 + "\n")

# Test creating a strategy with an indicator
print("Testing strategy with indicator assignment...")

class TestStrategy(bt.Strategy):
    def __new__(cls, *args, **kwargs):
        print(f"TestStrategy.__new__: cls = {cls}")
        print(f"TestStrategy.__new__: args = {args}")
        print(f"TestStrategy.__new__: kwargs = {kwargs}")
        
        # CRITICAL: Directly call LineIterator.__new__ to bypass inheritance issues
        # This ensures our data processing logic gets the arguments
        from backtrader.lineiterator import LineIterator
        instance = LineIterator.__new__(cls, *args, **kwargs)
        
        print(f"TestStrategy.__new__: created instance = {instance}")
        print(f"TestStrategy.__new__: instance.datas = {getattr(instance, 'datas', 'NOT_SET')}")
        print(f"TestStrategy.__new__: instance._clock = {getattr(instance, '_clock', 'NOT_SET')}")
        return instance
    
    def __init__(self):
        print(f"TestStrategy.__init__: self = {self}")
        print(f"TestStrategy.__init__: type(self) = {type(self)}")
        print(f"TestStrategy.__init__: hasattr(self, '__dict__') = {hasattr(self, '__dict__')}")
        print(f"TestStrategy.__init__: self.datas = {getattr(self, 'datas', 'NOT_SET')}")
        print(f"TestStrategy.__init__: self._clock = {getattr(self, '_clock', 'NOT_SET')}")
        if hasattr(self, '__dict__'):
            print(f"TestStrategy.__init__: self.__dict__ = {self.__dict__}")
        
        print("Creating SMA indicator...")
        sma = bt.indicators.SMA(self.data, period=25)
        print(f"SMA created: {sma}")
        
        print("Assigning sma to self.ind...")
        self.ind = sma
        print(f"Assignment complete. self.ind = {self.ind}")
        
        # Check if the assignment worked
        print(f"hasattr(self, 'ind') = {hasattr(self, 'ind')}")
        if hasattr(self, '__dict__'):
            print(f"'ind' in self.__dict__ = {'ind' in self.__dict__}")
            print(f"self.__dict__.keys() = {list(self.__dict__.keys())}")

try:
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    print("\nRunning cerebro...")
    results = cerebro.run()
    print(f"Results: {results}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc() 