#!/usr/bin/env python
# Debug script for Strategy parameter handling

import sys
sys.path.append('tests/original_tests')
import testcommon
import backtrader as bt

def debug_strategy_params():
    print("Testing TestStrategy parameter handling...")
    
    test_strategy = testcommon.TestStrategy
    print(f"TestStrategy class: {test_strategy}")
    print(f"TestStrategy MRO: {test_strategy.__mro__}")
    
    # Check if class has params
    if hasattr(test_strategy, 'params'):
        print(f"TestStrategy.params: {test_strategy.params}")
        print(f"TestStrategy.params type: {type(test_strategy.params)}")
        
    if hasattr(test_strategy, '_params'):
        print(f"TestStrategy._params: {test_strategy._params}")
        print(f"TestStrategy._params type: {type(test_strategy._params)}")
        
        params_cls = test_strategy._params
        if hasattr(params_cls, '_getpairs'):
            pairs = params_cls._getpairs()
            print(f"Parameter pairs: {pairs}")
            print(f"Parameter names: {list(pairs.keys())}")
            
            # Check if 'main' is in parameters
            if 'main' in pairs:
                print("'main' is a valid parameter!")
            else:
                print("'main' is NOT a valid parameter!")
    
    # Test the parameter separation logic like in ParamsMixin
    kwargs = {'main': False, 'chkind': 'test', 'unknown_param': 'value'}
    print(f"\nTest kwargs: {kwargs}")
    
    if hasattr(test_strategy, '_params'):
        params_cls = test_strategy._params
        param_names = set()
        
        if hasattr(params_cls, '_getpairs'):
            param_names.update(params_cls._getpairs().keys())
        elif hasattr(params_cls, '_gettuple'):
            param_names.update(key for key, value in params_cls._gettuple())
        
        print(f"Parameter names from class: {param_names}")
        
        param_kwargs = {}
        non_param_kwargs = {}
        for key, value in kwargs.items():
            if key in param_names:
                param_kwargs[key] = value
                print(f"  Parameter: {key} = {value}")
            else:
                non_param_kwargs[key] = value
                print(f"  Non-parameter: {key} = {value}")
        
        print(f"param_kwargs: {param_kwargs}")
        print(f"non_param_kwargs: {non_param_kwargs}")

if __name__ == "__main__":
    debug_strategy_params() 