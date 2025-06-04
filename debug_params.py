#!/usr/bin/env python
# Debug script to trace parameter passing

import backtrader.feed as feed

def debug_params():
    print("Creating AbstractDataBase with dataname='test.txt'")
    
    # Check parameter class before instantiation
    params_cls = feed.AbstractDataBase._params
    print(f"Parameter class: {params_cls}")
    print(f"Parameter class MRO: {params_cls.__mro__}")
    print(f"Parameter pairs: {params_cls._getpairs()}")
    
    # Test creating parameter instance manually
    print("\n--- Testing parameter instance creation ---")
    try:
        params_instance = params_cls()
        print(f"Created params instance: {params_instance}")
        print(f"Instance type: {type(params_instance)}")
        print(f"Has dataname: {hasattr(params_instance, 'dataname')}")
        print(f"Initial dataname: {getattr(params_instance, 'dataname', 'NOT_FOUND')}")
        
        # Try setting dataname
        setattr(params_instance, 'dataname', 'test.txt')
        print(f"After setting: {getattr(params_instance, 'dataname', 'NOT_FOUND')}")
    except Exception as e:
        print(f"Error creating params instance: {e}")
        import traceback
        traceback.print_exc()
    
    # Test parameter separation logic manually
    kwargs = {'dataname': 'test.txt'}
    param_names = set(params_cls._getpairs().keys())
    print(f"Parameter names: {param_names}")
    
    param_kwargs = {}
    non_param_kwargs = {}
    
    for key, value in kwargs.items():
        if key in param_names:
            param_kwargs[key] = value
            print(f"Parameter kwarg: {key} = {value}")
        else:
            non_param_kwargs[key] = value
            print(f"Non-parameter kwarg: {key} = {value}")
    
    print(f"param_kwargs: {param_kwargs}")
    print(f"non_param_kwargs: {non_param_kwargs}")
    
    # Test manual parameter setting like in ParamsMixin.__init__
    print("\n--- Testing manual parameter setting ---")
    try:
        test_instance = params_cls()
        print(f"Test instance created: {test_instance}")
        print(f"Test instance __dict__ before: {test_instance.__dict__}")
        
        # Set parameters like ParamsMixin does
        for key, value in params_cls._getpairs().items():
            final_value = param_kwargs.get(key, value)
            setattr(test_instance, key, final_value)
            print(f"Set {key} = {final_value}")
        
        print(f"Test instance __dict__ after: {test_instance.__dict__}")
        print(f"Test instance dataname: {getattr(test_instance, 'dataname', 'NOT_FOUND')}")
        
    except Exception as e:
        print(f"Error in manual setting: {e}")
        import traceback
        traceback.print_exc()
    
    # Try to create instance and trace what happens
    try:
        data = feed.AbstractDataBase(dataname='test.txt')
        print(f"Instance created successfully")
        print(f"data.p: {data.p}")
        print(f"data.p type: {type(data.p)}")
        print(f"data.p.__dict__: {data.p.__dict__}")
        print(f"data.p.dataname: {data.p.dataname}")
        print(f"data._params_instance: {getattr(data, '_params_instance', 'NOT_FOUND')}")
    except Exception as e:
        print(f"Error creating instance: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_params() 