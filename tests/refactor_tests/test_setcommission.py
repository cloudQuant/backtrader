#!/usr/bin/env python

import backtrader as bt
import os
import sys

import testcommon



def test_setcommission_behavior():
    """Test the behavior of the setcommission method.

    This function tests the setcommission method of the broker to ensure
    commission parameters are correctly set and applied to trades.
    """
    print("=== Testing setcommission method ===")

    cerebro = bt.Cerebro()
    data = testcommon.getdata(0)
    cerebro.adddata(data)

    class TestStrategy(bt.Strategy):
        params = (("stocklike", False),)

        def __init__(self):
            pass

        def start(self):
            print(f"Broker cash before start: {self.broker.getcash()}")
            print(f"CommInfo type before start: {type(self.broker.getcommissioninfo(self.data)).__name__}")

            # Get default CommInfo
            default_comminfo = self.broker.getcommissioninfo(self.data)
            print(f"Default CommInfo parameters:")
            try:
                print(f"  commission: {default_comminfo.get_param('commission')}")
                print(f"  mult: {default_comminfo.get_param('mult')}")
                print(f"  margin: {default_comminfo.get_param('margin')}")
                print(f"  stocklike: {default_comminfo.get_param('stocklike')}")
                print(f"  _stocklike: {default_comminfo._stocklike}")
                print(f"  _commtype: {default_comminfo._commtype}")
            except Exception as e:
                print(f"  Failed to get default parameters: {e}")
                # Try original method
                try:
                    print(f"  p.commission: {default_comminfo.p.commission}")
                    print(f"  p.mult: {default_comminfo.p.mult}")
                    print(f"  p.margin: {default_comminfo.p.margin}")
                    print(f"  p.stocklike: {default_comminfo.p.stocklike}")
                except Exception as e2:
                    print(f"  Original parameter access also failed: {e2}")

            # Set custom commission
            print(f"\nCalling setcommission(commission=2.0, mult=10.0, margin=1000.0)...")
            if not self.p.stocklike:
                self.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)

            print(f"Broker cash after setting: {self.broker.getcash()}")
            print(f"CommInfo type after setting: {type(self.broker.getcommissioninfo(self.data)).__name__}")

            # Get CommInfo after setting
            new_comminfo = self.broker.getcommissioninfo(self.data)
            print(f"New CommInfo parameters:")
            try:
                print(f"  commission: {new_comminfo.get_param('commission')}")
                print(f"  mult: {new_comminfo.get_param('mult')}")
                print(f"  margin: {new_comminfo.get_param('margin')}")
                print(f"  stocklike: {new_comminfo.get_param('stocklike')}")
                print(f"  _stocklike: {new_comminfo._stocklike}")
                print(f"  _commtype: {new_comminfo._commtype}")
            except Exception as e:
                print(f"  Failed to get new parameters: {e}")
                # Try original method
                try:
                    print(f"  p.commission: {new_comminfo.p.commission}")
                    print(f"  p.mult: {new_comminfo.p.mult}")
                    print(f"  p.margin: {new_comminfo.p.margin}")
                    print(f"  p.stocklike: {new_comminfo.p.stocklike}")
                except Exception as e2:
                    print(f"  Original parameter access also failed: {e2}")

            # Test key methods
            test_price = 100.0
            test_size = 1
            print(f"\nTesting key methods (price={test_price}, size={test_size}):")
            print(f"  getcommission(): {new_comminfo.getcommission(test_size, test_price)}")
            print(f"  get_margin(): {new_comminfo.get_margin(test_price)}")
            print(f"  getoperationcost(): {new_comminfo.getoperationcost(test_size, test_price)}")

        def next(self):
            pass  # Avoid running the entire strategy

        def stop(self):
            print("Strategy ended")

    cerebro.addstrategy(TestStrategy)
    result = cerebro.run()
    print(f"Run completed")


if __name__ == "__main__":
    test_setcommission_behavior()
