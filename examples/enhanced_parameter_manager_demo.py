#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Enhanced ParameterManager Demonstration (Day 32-33)

This example demonstrates the enhanced ParameterManager functionality implemented
for Day 32-33 of the backtrader metaprogramming removal project.

New Features Demonstrated:
- Parameter locking mechanism
- Parameter grouping
- Change tracking and history
- Advanced inheritance with conflict resolution
- Lazy default value evaluation
- Change callbacks and notifications
- Transactional batch updates
- Dependency tracking between parameters
"""

import sys
import os
import time

# Add backtrader to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backtrader.parameters import (
    ParameterDescriptor, ParameterManager, ParameterizedBase,
    Int, Float, OneOf, String
)


def demonstrate_parameter_locking():
    """Demonstrate parameter locking functionality."""
    print("=== Parameter Locking Demo ===")
    
    descriptors = {
        'critical_param': ParameterDescriptor(default=100, name='critical_param'),
        'normal_param': ParameterDescriptor(default=200, name='normal_param')
    }
    
    manager = ParameterManager(descriptors)
    
    # Normal operation
    manager.set('critical_param', 150)
    print(f"✓ Set critical_param to {manager.get('critical_param')}")
    
    # Lock the critical parameter
    manager.lock_parameter('critical_param')
    print(f"🔒 Locked critical_param")
    
    # Try to modify locked parameter
    try:
        manager.set('critical_param', 300)
    except ValueError as e:
        print(f"✗ Cannot modify locked parameter: {e}")
    
    # Force modification
    manager.set('critical_param', 300, force=True)
    print(f"✓ Force modification succeeded: {manager.get('critical_param')}")
    
    # Unlock and modify normally
    manager.unlock_parameter('critical_param')
    manager.set('critical_param', 250)
    print(f"✓ After unlock, set to {manager.get('critical_param')}")
    
    print()


def demonstrate_parameter_groups():
    """Demonstrate parameter grouping functionality."""
    print("=== Parameter Groups Demo ===")
    
    descriptors = {
        'fast_period': ParameterDescriptor(default=12, name='fast_period'),
        'slow_period': ParameterDescriptor(default=26, name='slow_period'),
        'signal_period': ParameterDescriptor(default=9, name='signal_period'),
        'upper_band': ParameterDescriptor(default=2.0, name='upper_band'),
        'lower_band': ParameterDescriptor(default=-2.0, name='lower_band')
    }
    
    manager = ParameterManager(descriptors)
    
    # Create logical groups
    manager.create_group('MACD', ['fast_period', 'slow_period', 'signal_period'])
    manager.create_group('Bollinger', ['upper_band', 'lower_band'])
    
    print("Created parameter groups:")
    print(f"  MACD group: {manager.get_group('MACD')}")
    print(f"  Bollinger group: {manager.get_group('Bollinger')}")
    
    # Set group values at once
    manager.set_group('MACD', {
        'fast_period': 15,
        'slow_period': 30,
        'signal_period': 10
    })
    
    print("\nAfter setting MACD group values:")
    macd_values = manager.get_group_values('MACD')
    for param, value in macd_values.items():
        print(f"  {param}: {value}")
    
    # Check individual parameter group membership
    print(f"\nfast_period belongs to group: {manager.get_parameter_group('fast_period')}")
    
    print()


def demonstrate_change_tracking():
    """Demonstrate change tracking and history."""
    print("=== Change Tracking & History Demo ===")
    
    descriptors = {
        'tracked_param': ParameterDescriptor(default=10, name='tracked_param')
    }
    
    manager = ParameterManager(descriptors, enable_history=True)
    
    # Make several changes
    print("Making parameter changes...")
    manager.set('tracked_param', 20)
    time.sleep(0.1)  # Small delay for different timestamps
    manager.set('tracked_param', 30)
    time.sleep(0.1)
    manager.set('tracked_param', 25)
    time.sleep(0.1)
    manager.reset('tracked_param')  # Back to default
    
    # View change history
    history = manager.get_change_history('tracked_param')
    print(f"\nChange history for tracked_param ({len(history)} changes):")
    for i, (old_val, new_val, timestamp) in enumerate(history):
        print(f"  {i+1}. {old_val} → {new_val} (at {time.ctime(timestamp)})")
    
    # Clear history
    manager.clear_history('tracked_param')
    print(f"\nAfter clearing history: {len(manager.get_change_history('tracked_param'))} changes")
    
    print()


def demonstrate_advanced_inheritance():
    """Demonstrate advanced inheritance mechanisms."""
    print("=== Advanced Inheritance Demo ===")
    
    descriptors = {
        'param1': ParameterDescriptor(default=10, name='param1'),
        'param2': ParameterDescriptor(default=20, name='param2'),
        'param3': ParameterDescriptor(default=30, name='param3')
    }
    
    # Parent configurations
    base_config = ParameterManager(descriptors)
    base_config.set('param1', 100)
    base_config.set('param2', 200)
    
    # Child configuration with conflicts
    custom_config = ParameterManager(descriptors)
    custom_config.set('param2', 250)  # Conflict!
    custom_config.set('param3', 350)
    
    print("Base config:", dict(base_config.items()))
    print("Custom config:", dict(custom_config.items()))
    
    # Test different inheritance strategies
    
    # Strategy 1: Parent wins conflicts
    child1 = ParameterManager(descriptors)
    child1.set('param2', 999)  # This will be overridden
    child1.inherit_from(base_config, strategy='merge', conflict_resolution='parent')
    print("\nAfter inheritance (parent wins conflicts):")
    print("  child1:", dict(child1.items()))
    
    # Strategy 2: Child wins conflicts  
    child2 = ParameterManager(descriptors)
    child2.set('param2', 999)  # This will be kept
    child2.inherit_from(base_config, strategy='merge', conflict_resolution='child')
    print("  child2:", dict(child2.items()))
    
    # Strategy 3: Selective inheritance
    child3 = ParameterManager(descriptors)
    child3.inherit_from(base_config, strategy='selective', selective=['param1'])
    print("  child3 (selective):", dict(child3.items()))
    
    # Test inheritance tracking
    info = child1.get_inheritance_info('param1')
    if info:
        print(f"\nInheritance info for param1: inherited={info['inherited']}")
    
    print()


def demonstrate_lazy_defaults():
    """Demonstrate lazy default value evaluation."""
    print("=== Lazy Defaults Demo ===")
    
    descriptors = {
        'timestamp': ParameterDescriptor(default=0, name='timestamp'),
        'computed_value': ParameterDescriptor(default=0, name='computed_value')
    }
    
    manager = ParameterManager(descriptors)
    
    # Set lazy default that computes current timestamp
    def current_timestamp():
        timestamp = int(time.time())
        print(f"  🔄 Computing timestamp: {timestamp}")
        return timestamp
    
    manager.set_lazy_default('timestamp', current_timestamp)
    
    print("First access to timestamp:")
    value1 = manager.get('timestamp')
    print(f"  Got: {value1}")
    
    print("Second access to timestamp (should use cached value):")
    value2 = manager.get('timestamp')
    print(f"  Got: {value2} (same as before)")
    
    # Set explicit value
    manager.set('timestamp', 1234567890)
    print(f"After explicit set: {manager.get('timestamp')}")
    
    # Reset to lazy default
    manager.reset('timestamp')
    print(f"After reset: {manager.get('timestamp')} (back to lazy default)")
    
    print()


def demonstrate_change_callbacks():
    """Demonstrate parameter change callbacks."""
    print("=== Change Callbacks Demo ===")
    
    descriptors = {
        'monitored_param': ParameterDescriptor(default=100, name='monitored_param'),
        'other_param': ParameterDescriptor(default=200, name='other_param')
    }
    
    manager = ParameterManager(descriptors, enable_callbacks=True)
    
    # Global callback for all parameters
    global_changes = []
    def global_callback(name, old_value, new_value):
        global_changes.append(f"Global: {name} changed from {old_value} to {new_value}")
    
    manager.add_change_callback(global_callback)
    
    # Specific callback for one parameter
    specific_changes = []
    def specific_callback(name, old_value, new_value):
        specific_changes.append(f"Specific: {name} changed from {old_value} to {new_value}")
    
    manager.add_change_callback(specific_callback, 'monitored_param')
    
    # Make changes
    print("Making parameter changes...")
    manager.set('monitored_param', 150)  # Should trigger both callbacks
    manager.set('other_param', 300)      # Should trigger only global callback
    
    print("\nCallback results:")
    print("Global callbacks:")
    for change in global_changes:
        print(f"  {change}")
    
    print("Specific callbacks:")
    for change in specific_changes:
        print(f"  {change}")
    
    print()


def demonstrate_transactions():
    """Demonstrate transactional batch updates."""
    print("=== Transactions Demo ===")
    
    descriptors = {
        'param1': ParameterDescriptor(default=10, name='param1'),
        'param2': ParameterDescriptor(default=20, name='param2'),
        'param3': ParameterDescriptor(default=30, name='param3')
    }
    
    manager = ParameterManager(descriptors, enable_callbacks=True)
    
    # Add callback to track when changes are applied
    applied_changes = []
    def change_callback(name, old_value, new_value):
        applied_changes.append(f"{name}: {old_value} → {new_value}")
    
    manager.add_change_callback(change_callback)
    
    print("Initial values:", dict(manager.items()))
    
    # Successful transaction
    print("\nStarting transaction...")
    manager.begin_transaction()
    
    manager.set('param1', 100)
    manager.set('param2', 200)
    manager.set('param3', 300)
    
    print("Values during transaction:", dict(manager.items()))
    print(f"Callbacks triggered so far: {len(applied_changes)}")
    
    print("Committing transaction...")
    manager.commit_transaction()
    
    print("Values after commit:", dict(manager.items()))
    print(f"Callbacks triggered after commit: {len(applied_changes)}")
    for change in applied_changes:
        print(f"  {change}")
    
    # Rollback transaction
    applied_changes.clear()
    print("\nStarting rollback transaction...")
    manager.begin_transaction()
    
    manager.set('param1', 999)
    manager.set('param2', 888)
    
    print("Values during rollback transaction:", dict(manager.items()))
    
    print("Rolling back transaction...")
    manager.rollback_transaction()
    
    print("Values after rollback:", dict(manager.items()))
    print(f"Callbacks triggered after rollback: {len(applied_changes)}")
    
    print()


def demonstrate_dependencies():
    """Demonstrate parameter dependency tracking."""
    print("=== Dependency Tracking Demo ===")
    
    descriptors = {
        'base_value': ParameterDescriptor(default=100, name='base_value'),
        'multiplier': ParameterDescriptor(default=2, name='multiplier'),
        'calculated_result': ParameterDescriptor(default=0, name='calculated_result')
    }
    
    manager = ParameterManager(descriptors)
    
    # Set up dependencies
    manager.add_dependency('base_value', 'calculated_result')
    manager.add_dependency('multiplier', 'calculated_result')
    
    print("Dependency relationships:")
    print(f"  base_value dependencies: {manager.get_dependencies('base_value')}")
    print(f"  multiplier dependencies: {manager.get_dependencies('multiplier')}")
    print(f"  calculated_result depends on: {manager.get_dependents('calculated_result')}")
    
    # In a real implementation, you might automatically recalculate
    # dependent parameters when their dependencies change
    
    # Remove a dependency
    manager.remove_dependency('multiplier', 'calculated_result')
    print(f"\nAfter removing dependency:")
    print(f"  multiplier dependencies: {manager.get_dependencies('multiplier')}")
    
    print()


if __name__ == '__main__':
    print("Enhanced ParameterManager Demonstration (Day 32-33)")
    print("=" * 60)
    print()
    
    demonstrate_parameter_locking()
    demonstrate_parameter_groups()
    demonstrate_change_tracking()
    demonstrate_advanced_inheritance()
    demonstrate_lazy_defaults()
    demonstrate_change_callbacks()
    demonstrate_transactions()
    demonstrate_dependencies()
    
    print("=" * 60)
    print("✓ All enhanced features demonstrated successfully!")
    print()
    print("Summary of Day 32-33 enhancements:")
    print("  ✓ Parameter locking for critical parameters")
    print("  ✓ Parameter grouping for logical organization")
    print("  ✓ Change tracking and history with timestamps")
    print("  ✓ Advanced inheritance with conflict resolution")
    print("  ✓ Lazy default value evaluation and caching")
    print("  ✓ Change callbacks and notification system")
    print("  ✓ Transactional batch updates with rollback")
    print("  ✓ Parameter dependency tracking and management") 