#!/usr/bin/env python
import backtrader as bt

print("Creating Cerebro...")
cerebro = bt.Cerebro()

print(f"Cerebro instance: {cerebro}")
print(f"Cerebro has _broker attr: {hasattr(cerebro, '_broker')}")
print(f"Cerebro._broker: {cerebro._broker}")
print(f"Cerebro.broker (property): {cerebro.broker}")

if cerebro.broker:
    value = cerebro.broker.getvalue()
    print(f"Broker getvalue() returns: {value}")
    print(f"Type of value: {type(value)}")
    print(f"Broker._value: {cerebro.broker._value}")
    print(f"Broker._cash: {cerebro.broker._cash}")
    print(f"Broker.startingcash: {cerebro.broker.startingcash}")
    
    # Check if _value is None
    if value is None:
        print("ERROR: getvalue() returned None!")
        print("Checking broker initialization...")
        print(f"Has _cash attr: {hasattr(cerebro.broker, '_cash')}")
        print(f"Has _value attr: {hasattr(cerebro.broker, '_value')}")
    else:
        print(f"Broker value formatted: {value:.2f}")
else:
    print("ERROR: Broker is None!")
