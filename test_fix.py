#!/usr/bin/env python

import sys
import os
sys.path.insert(0, '.')

from backtrader.sizers.percents_sizer import PercentSizer, AllInSizer, PercentSizerInt, AllInSizerInt

print("Testing parameter defaults after fix...")

# Test inheritance chain
print("Inheritance chains:")
print(f"PercentSizer MRO: {[cls.__name__ for cls in PercentSizer.__mro__]}")
print(f"AllInSizer MRO: {[cls.__name__ for cls in AllInSizer.__mro__]}")
print(f"PercentSizerInt MRO: {[cls.__name__ for cls in PercentSizerInt.__mro__]}")
print(f"AllInSizerInt MRO: {[cls.__name__ for cls in AllInSizerInt.__mro__]}")

print("\nParameter descriptors in each class __dict__:")
for cls_name, cls in [("PercentSizer", PercentSizer), ("AllInSizer", AllInSizer), 
                     ("PercentSizerInt", PercentSizerInt), ("AllInSizerInt", AllInSizerInt)]:
    print(f"\n{cls_name}.__dict__ parameter descriptors:")
    for name, value in cls.__dict__.items():
        if hasattr(value, 'default'):  # It's a ParameterDescriptor
            print(f"  {name}: default={value.default}")

print("\nDetailed _parameter_descriptors analysis:")
for cls_name, cls in [("PercentSizer", PercentSizer), ("AllInSizer", AllInSizer), 
                     ("PercentSizerInt", PercentSizerInt), ("AllInSizerInt", AllInSizerInt)]:
    print(f"\n{cls_name}._parameter_descriptors:")
    # Use the lazy-loading method to get computed descriptors
    computed_descriptors = cls._compute_parameter_descriptors()
    if computed_descriptors:
        for param_name, descriptor in computed_descriptors.items():
            print(f"  {param_name}: default={descriptor.default}, id={id(descriptor)}")
            # Check which class this descriptor originally came from
            for check_cls in [PercentSizer, AllInSizer, PercentSizerInt, AllInSizerInt]:
                if hasattr(check_cls, param_name) and id(getattr(check_cls, param_name)) == id(descriptor):
                    print(f"    -> Same as {check_cls.__name__}.{param_name}")
                    break

print("\nDetailed debugging for AllInSizerInt:")
print(f"AllInSizerInt MRO: {[cls.__name__ for cls in AllInSizerInt.__mro__]}")

# Check each class in the MRO for retint parameter
for cls in AllInSizerInt.__mro__:
    if hasattr(cls, '__dict__') and 'retint' in cls.__dict__:
        retint_desc = cls.__dict__['retint']
        if hasattr(retint_desc, 'default'):
            print(f"Found retint in {cls.__name__}: default={retint_desc.default}")

print("\nAllInSizerInt parameter resolution process:")
# Manually trace the _compute_parameter_descriptors logic
inherited_descriptors = {}

# Process base classes in reverse MRO order (excluding cls and object)
for base_cls in reversed(AllInSizerInt.__mro__[1:-1]):  # Skip AllInSizerInt and object
    print(f"Processing base class: {base_cls.__name__}")
    if hasattr(base_cls, '__dict__'):
        for attr_name, attr_value in base_cls.__dict__.items():
            if hasattr(attr_value, 'default'):  # ParameterDescriptor
                if attr_name not in inherited_descriptors:
                    inherited_descriptors[attr_name] = attr_value
                    print(f"  Added {attr_name} from {base_cls.__name__}: default={attr_value.default}")
                else:
                    print(f"  Skipped {attr_name} from {base_cls.__name__} (already have it): default={attr_value.default}")

print(f"\nInherited descriptors: {[(name, desc.default) for name, desc in inherited_descriptors.items()]}")

# Add current class descriptors
current_descriptors = {}
for attr_name, attr_value in AllInSizerInt.__dict__.items():
    if hasattr(attr_value, 'default'):  # ParameterDescriptor
        current_descriptors[attr_name] = attr_value
        print(f"Current class descriptor: {attr_name} = {attr_value.default}")

# Combine
final_descriptors = {}
final_descriptors.update(inherited_descriptors)
final_descriptors.update(current_descriptors)  # These override inherited ones

print(f"Final descriptors: {[(name, desc.default) for name, desc in final_descriptors.items()]}")

# Test instances
print("\n" + "="*50)
print("INSTANCE TESTS:")

# Test PercentSizer
p = PercentSizer()
print(f"PercentSizer percents: {p.get_param('percents')} (expected: 20)")
print(f"PercentSizer retint: {p.get_param('retint')} (expected: False)")

# Test AllInSizer  
a = AllInSizer()
print(f"AllInSizer percents: {a.get_param('percents')} (expected: 100)")
print(f"AllInSizer retint: {a.get_param('retint')} (expected: False)")

# Test PercentSizerInt
pi = PercentSizerInt()
print(f"PercentSizerInt percents: {pi.get_param('percents')} (expected: 20)")
print(f"PercentSizerInt retint: {pi.get_param('retint')} (expected: True)")

# Test AllInSizerInt
ai = AllInSizerInt()
print(f"AllInSizerInt percents: {ai.get_param('percents')} (expected: 100)")
print(f"AllInSizerInt retint: {ai.get_param('retint')} (expected: True)")

print("\nAnalyzing the problem step by step...")
print("Direct class attribute access:")
print(f"PercentSizer.percents.default: {PercentSizer.percents.default}")
print(f"AllInSizer.percents.default: {AllInSizer.percents.default}")
print(f"PercentSizer.retint.default: {PercentSizer.retint.default}")
print(f"PercentSizerInt.retint.default: {PercentSizerInt.retint.default}")

print("\nParameter manager analysis:")
if hasattr(p, '_param_manager'):
    print("PercentSizer instance parameter manager:")
    for name, desc in p._param_manager._descriptors.items():
        print(f"  {name}: default={desc.default}, id={id(desc)}")

print("\nTesting simple inheritance to isolate the problem...")

from backtrader.parameters import ParameterDescriptor, ParameterizedBase

# Clear any existing test classes
import gc
gc.collect()

class TestParent(ParameterizedBase):
    param1 = ParameterDescriptor(default=10, name="param1")
    
class TestChild(TestParent):
    param1 = ParameterDescriptor(default=20, name="param1")  # Override

print(f"\nSimple test:")
print(f"TestParent.param1.default: {TestParent.param1.default}")
print(f"TestChild.param1.default: {TestChild.param1.default}")
print(f"TestParent._parameter_descriptors['param1'].default: {TestParent._compute_parameter_descriptors()['param1'].default}")
print(f"TestChild._parameter_descriptors['param1'].default: {TestChild._compute_parameter_descriptors()['param1'].default}")

test_parent = TestParent()
test_child = TestChild()
print(f"TestParent instance param1: {test_parent.get_param('param1')}")
print(f"TestChild instance param1: {test_child.get_param('param1')}")

# Check if the parent class got corrupted
print(f"After child definition, TestParent.param1.default: {TestParent.param1.default}")
print(f"After child definition, TestParent._parameter_descriptors['param1'].default: {TestParent._compute_parameter_descriptors()['param1'].default}")
print(f"Parent descriptor id: {id(TestParent.param1)}")
print(f"Parent _parameter_descriptors id: {id(TestParent._compute_parameter_descriptors()['param1'])}") 