#!/usr/bin/env python

import sys
sys.path.insert(0, '.')

from backtrader.parameters import ParameterDescriptor, ParameterManager

# Test inheritance strategies exactly like the test
descriptors = {
    'param1': ParameterDescriptor(default=10, name='param1'),
    'param2': ParameterDescriptor(default=20, name='param2'),
    'param3': ParameterDescriptor(default=30, name='param3')
}

# Parent manager
parent = ParameterManager(descriptors)
parent.set('param1', 100)
parent.set('param2', 200)
print("Parent state:")
print(f"  param1: {parent.get('param1')} (in _values: {'param1' in parent._values})")
print(f"  param2: {parent.get('param2')} (in _values: {'param2' in parent._values})")
print(f"  param3: {parent.get('param3')} (in _values: {'param3' in parent._values})")

# Child manager with some existing values (first test)
child = ParameterManager(descriptors)
child.set('param2', 250)  # Conflicting value
child.set('param3', 300)
print("\nChild state before inheritance (test 1 - parent resolution):")
print(f"  param1: {child.get('param1')} (in _values: {'param1' in child._values})")
print(f"  param2: {child.get('param2')} (in _values: {'param2' in child._values})")
print(f"  param3: {child.get('param3')} (in _values: {'param3' in child._values})")

# Test merge strategy with parent conflict resolution
print("\nInheriting with merge strategy, parent conflict resolution...")
child.inherit_from(parent, strategy='merge', conflict_resolution='parent')

print("\nChild state after inheritance (test 1):")
print(f"  param1: {child.get('param1')} (in _values: {'param1' in child._values}) - Expected: 100")
print(f"  param2: {child.get('param2')} (in _values: {'param2' in child._values}) - Expected: 200")
print(f"  param3: {child.get('param3')} (in _values: {'param3' in child._values}) - Expected: 300")

# Reset child (second test)
child = ParameterManager(descriptors)
child.set('param2', 250)
child.set('param3', 300)
print("\n\nChild state before inheritance (test 2 - child resolution):")
print(f"  param1: {child.get('param1')} (in _values: {'param1' in child._values})")
print(f"  param2: {child.get('param2')} (in _values: {'param2' in child._values})")
print(f"  param3: {child.get('param3')} (in _values: {'param3' in child._values})")

# Test merge strategy with child conflict resolution
print("\nInheriting with merge strategy, child conflict resolution...")
child.inherit_from(parent, strategy='merge', conflict_resolution='child')

print("\nChild state after inheritance (test 2):")
print(f"  param1: {child.get('param1')} (in _values: {'param1' in child._values}) - Expected: 100")
print(f"  param2: {child.get('param2')} (in _values: {'param2' in child._values}) - Expected: 250")
print(f"  param3: {child.get('param3')} (in _values: {'param3' in child._values}) - Expected: 300") 