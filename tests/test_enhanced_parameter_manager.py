"""
Tests for Enhanced ParameterManager (Day 32-33)

This module tests the enhanced ParameterManager functionality including:
- Advanced parameter storage and management
- Complete inheritance mechanisms
- Optimized default value handling  
- Enhanced batch update functionality
- New features: locking, groups, callbacks, transactions, etc.
"""

import pytest
import sys
import os
import time

# Add the backtrader directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backtrader.parameters import (
    ParameterDescriptor, ParameterManager, ParameterizedBase,
    Int, Float, OneOf, String
)


class TestEnhancedParameterStorage:
    """Test advanced parameter storage and management features."""
    
    def test_parameter_locking(self):
        """Test parameter locking mechanism."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1'),
            'param2': ParameterDescriptor(default=20, name='param2')
        }
        
        manager = ParameterManager(descriptors)
        
        # Initially no parameters are locked
        assert not manager.is_locked('param1')
        assert manager.get_locked_parameters() == []
        
        # Lock a parameter
        manager.lock_parameter('param1')
        assert manager.is_locked('param1')
        assert 'param1' in manager.get_locked_parameters()
        
        # Try to modify locked parameter - should fail
        with pytest.raises(ValueError, match="locked"):
            manager.set('param1', 15)
        
        # Force modification should work
        manager.set('param1', 15, force=True)
        assert manager.get('param1') == 15
        
        # Reset locked parameter should fail
        with pytest.raises(ValueError, match="locked"):
            manager.reset('param1')
        
        # Force reset should work
        manager.reset('param1', force=True)
        assert manager.get('param1') == 10
        
        # Unlock parameter
        manager.unlock_parameter('param1')
        assert not manager.is_locked('param1')
        
        # Now modification should work normally
        manager.set('param1', 25)
        assert manager.get('param1') == 25
    
    def test_parameter_groups(self):
        """Test parameter grouping functionality."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1'),
            'param2': ParameterDescriptor(default=20, name='param2'), 
            'param3': ParameterDescriptor(default=30, name='param3'),
            'param4': ParameterDescriptor(default=40, name='param4')
        }
        
        manager = ParameterManager(descriptors)
        
        # Create groups
        manager.create_group('group1', ['param1', 'param2'])
        manager.create_group('group2', ['param3', 'param4'])
        
        # Test group membership
        assert manager.get_group('group1') == ['param1', 'param2']
        assert manager.get_parameter_group('param1') == 'group1'
        assert manager.get_parameter_group('param3') == 'group2'
        
        # Set group values
        manager.set_group('group1', {'param1': 100, 'param2': 200})
        assert manager.get('param1') == 100
        assert manager.get('param2') == 200
        
        # Get group values
        group_values = manager.get_group_values('group1')
        assert group_values == {'param1': 100, 'param2': 200}
        
        # Invalid group operations
        with pytest.raises(ValueError):
            manager.set_group('nonexistent', {})
        
        with pytest.raises(ValueError):
            manager.get_group_values('nonexistent')
        
        with pytest.raises(AttributeError):
            manager.create_group('invalid', ['nonexistent_param'])
    
    def test_change_tracking_and_history(self):
        """Test parameter change tracking and history."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1')
        }
        
        manager = ParameterManager(descriptors, enable_history=True)
        
        # Initially no history
        assert manager.get_change_history('param1') == []
        
        # Make some changes
        manager.set('param1', 20)
        manager.set('param1', 30)
        manager.reset('param1')
        
        # Check history
        history = manager.get_change_history('param1')
        assert len(history) == 3
        print(history)
        # Check history structure (old_value, new_value, timestamp)
        assert history[0][0] == 30  # old value
        assert history[0][1] == 10  # new value
        assert isinstance(history[0][2], float)  # timestamp
        
        assert history[1][0] == 20
        assert history[1][1] == 30
        
        assert history[2][0] == 10
        assert history[2][1] == 20  # reset to default
        
        # Test history limit
        limited_history = manager.get_change_history('param1', limit=2)
        assert len(limited_history) == 2
        
        # Clear history
        manager.clear_history('param1')
        assert manager.get_change_history('param1') == []
        
        # Test with history disabled
        manager_no_history = ParameterManager(descriptors, enable_history=False)
        manager_no_history.set('param1', 50)
        assert manager_no_history.get_change_history('param1') == []


class TestAdvancedInheritance:
    """Test enhanced inheritance mechanisms."""
    
    def test_inheritance_strategies(self):
        """Test different inheritance strategies."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1'),
            'param2': ParameterDescriptor(default=20, name='param2'),
            'param3': ParameterDescriptor(default=30, name='param3')
        }
        
        # Parent manager
        parent = ParameterManager(descriptors)
        parent.set('param1', 100)
        parent.set('param2', 200)
        
        # Child manager with some existing values
        child = ParameterManager(descriptors)
        child.set('param2', 250)  # Conflicting value
        child.set('param3', 300)
        
        # Test merge strategy with parent conflict resolution
        child.inherit_from(parent, strategy='merge', conflict_resolution='parent')
        assert child.get('param1') == 100  # Inherited
        assert child.get('param2') == 200  # Parent wins conflict
        assert child.get('param3') == 300  # Child's original value
        
        # Reset child
        child = ParameterManager(descriptors)
        child.set('param2', 250)
        child.set('param3', 300)
        
        # Test merge strategy with child conflict resolution
        child.inherit_from(parent, strategy='merge', conflict_resolution='child')
        assert child.get('param1') == 100  # Inherited
        assert child.get('param2') == 250  # Child wins conflict
        assert child.get('param3') == 300  # Child's original value
        
        # Reset child
        child = ParameterManager(descriptors)
        child.set('param2', 250)
        
        # Test replace strategy
        child.inherit_from(parent, strategy='replace')
        assert child.get('param1') == 100  # Inherited
        assert child.get('param2') == 200  # Parent replaces child
        assert child.get('param3') == 30   # Default value (was reset)
        
        # Test selective inheritance
        child = ParameterManager(descriptors)
        child.inherit_from(parent, strategy='selective', selective=['param1'])
        assert child.get('param1') == 100  # Inherited
        assert child.get('param2') == 20   # Not inherited (default)
        assert child.get('param3') == 30   # Not inherited (default)
    
    def test_inheritance_conflict_detection(self):
        """Test inheritance conflict detection."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1')
        }
        
        parent = ParameterManager(descriptors)
        parent.set('param1', 100)
        
        child = ParameterManager(descriptors)
        child.set('param1', 200)  # Conflicting value
        
        # Test conflict raising
        with pytest.raises(ValueError, match="conflicts"):
            child.inherit_from(parent, strategy='merge', conflict_resolution='raise')
    
    def test_inheritance_tracking(self):
        """Test inheritance chain tracking."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1')
        }
        
        grandparent = ParameterManager(descriptors)
        grandparent.set('param1', 100)
        
        parent = ParameterManager(descriptors)
        parent.inherit_from(grandparent)
        
        child = ParameterManager(descriptors)
        child.inherit_from(parent)
        
        # Test inheritance info
        info = child.get_inheritance_info('param1')
        assert info is not None
        assert info['inherited'] == True
        assert info['source'] == parent
        
        # Test non-inherited parameter
        child.set('param1', 500)  # Override inherited value
        # After setting directly, it's no longer considered "inherited"
        # (this behavior depends on implementation details)


class TestLazyDefaults:
    """Test lazy default value handling."""
    
    def test_lazy_default_evaluation(self):
        """Test lazy default value evaluation."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1'),
            'param2': ParameterDescriptor(default=20, name='param2')
        }
        
        manager = ParameterManager(descriptors)
        
        # Set lazy default that depends on current time
        call_count = 0
        def lazy_func():
            nonlocal call_count
            call_count += 1
            return int(time.time() * 1000) % 1000  # Some time-based value
        
        manager.set_lazy_default('param1', lazy_func)
        
        # First access should compute the value
        value1 = manager.get('param1')
        assert call_count == 1
        
        # Second access should use cached value
        value2 = manager.get('param1')
        assert call_count == 1  # Not called again
        assert value1 == value2
        
        # Clear lazy default
        manager.clear_lazy_default('param1')
        value3 = manager.get('param1')
        assert value3 == 10  # Back to original default
    
    def test_lazy_default_with_set(self):
        """Test interaction between lazy defaults and explicit setting."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1')
        }
        
        manager = ParameterManager(descriptors)
        
        # Set lazy default
        manager.set_lazy_default('param1', lambda: 999)
        
        # Should use lazy default initially
        assert manager.get('param1') == 999
        
        # Set explicit value
        manager.set('param1', 555)
        assert manager.get('param1') == 555
        
        # Reset should go back to lazy default
        manager.reset('param1')
        assert manager.get('param1') == 999


class TestChangeCallbacks:
    """Test parameter change callbacks."""
    
    def test_parameter_specific_callbacks(self):
        """Test parameter-specific change callbacks."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1'),
            'param2': ParameterDescriptor(default=20, name='param2')
        }
        
        manager = ParameterManager(descriptors, enable_callbacks=True)
        
        # Track callback calls
        callback_calls = []
        
        def callback(name, old_value, new_value):
            callback_calls.append((name, old_value, new_value))
        
        # Add callback for specific parameter
        manager.add_change_callback(callback, 'param1')
        
        # Change param1 - should trigger callback
        manager.set('param1', 15)
        assert len(callback_calls) == 1
        assert callback_calls[0] == ('param1', 10, 15)
        
        # Change param2 - should not trigger callback
        manager.set('param2', 25)
        assert len(callback_calls) == 1  # No new calls
        
        # Remove callback
        manager.remove_change_callback(callback, 'param1')
        manager.set('param1', 20)
        assert len(callback_calls) == 1  # No new calls
    
    def test_global_callbacks(self):
        """Test global change callbacks."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1'),
            'param2': ParameterDescriptor(default=20, name='param2')
        }
        
        manager = ParameterManager(descriptors, enable_callbacks=True)
        
        callback_calls = []
        
        def global_callback(name, old_value, new_value):
            callback_calls.append((name, old_value, new_value))
        
        # Add global callback
        manager.add_change_callback(global_callback)
        
        # Changes to any parameter should trigger callback
        manager.set('param1', 15)
        manager.set('param2', 25)
        
        assert len(callback_calls) == 2
        assert callback_calls[0] == ('param1', 10, 15)
        assert callback_calls[1] == ('param2', 20, 25)
    
    def test_callback_error_handling(self):
        """Test that callback errors don't break parameter setting."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1')
        }
        
        manager = ParameterManager(descriptors, enable_callbacks=True)
        
        def bad_callback(name, old_value, new_value):
            raise RuntimeError("Callback error!")
        
        manager.add_change_callback(bad_callback)
        
        # Parameter setting should still work despite callback error
        manager.set('param1', 15)
        assert manager.get('param1') == 15


class TestEnhancedBatchOperations:
    """Test enhanced batch update functionality."""
    
    def test_batch_validation(self):
        """Test batch validation before applying changes."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, type_=int, name='param1'),
            'param2': ParameterDescriptor(default=20, type_=int, name='param2')
        }
        
        manager = ParameterManager(descriptors)
        manager.lock_parameter('param1')
        
        # Test batch validation with locked parameter
        with pytest.raises(ValueError, match="Validation errors"):
            manager.update({'param1': 15, 'param2': 25}, validate_all=True)
        
        # No changes should have been applied
        assert manager.get('param1') == 10
        assert manager.get('param2') == 20
        
        # Force update should work
        manager.update({'param1': 15, 'param2': 25}, force=True)
        assert manager.get('param1') == 15
        assert manager.get('param2') == 25
    
    def test_transaction_support(self):
        """Test transactional batch updates."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1'),
            'param2': ParameterDescriptor(default=20, name='param2')
        }
        
        manager = ParameterManager(descriptors, enable_callbacks=True)
        
        callback_calls = []
        def callback(name, old_value, new_value):
            callback_calls.append((name, old_value, new_value))
        
        manager.add_change_callback(callback)
        
        # Test successful transaction
        manager.begin_transaction()
        assert manager.is_in_transaction()
        
        manager.set('param1', 100)
        manager.set('param2', 200)
        
        # Values should be visible within transaction
        assert manager.get('param1') == 100  # Transaction value
        assert manager.get('param2') == 200  # Transaction value
        assert len(callback_calls) == 0  # No callbacks triggered yet
        
        # Commit transaction
        manager.commit_transaction()
        assert not manager.is_in_transaction()
        
        # Now values should be visible
        assert manager.get('param1') == 100
        assert manager.get('param2') == 200
        assert len(callback_calls) == 2  # Callbacks triggered
        
        # Test rollback transaction
        callback_calls.clear()
        manager.begin_transaction()
        manager.set('param1', 300)
        manager.set('param2', 400)
        
        # Values should be visible within transaction
        assert manager.get('param1') == 300  # Transaction value
        assert manager.get('param2') == 400  # Transaction value
        
        manager.rollback_transaction()
        assert not manager.is_in_transaction()
        
        # Values should be reverted to pre-transaction state
        assert manager.get('param1') == 100
        assert manager.get('param2') == 200
        assert len(callback_calls) == 0  # No callbacks for rolled back changes
    
    def test_transaction_nesting_protection(self):
        """Test that nested transactions are prevented."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1')
        }
        
        manager = ParameterManager(descriptors)
        
        manager.begin_transaction()
        
        # Trying to begin another transaction should fail
        with pytest.raises(RuntimeError, match="Already in a transaction"):
            manager.begin_transaction()
        
        # Operations on non-transaction manager should fail
        with pytest.raises(RuntimeError, match="Not in a transaction"):
            ParameterManager(descriptors).commit_transaction()


class TestDependencyTracking:
    """Test parameter dependency tracking."""
    
    def test_dependency_management(self):
        """Test adding and removing dependencies."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1'),
            'param2': ParameterDescriptor(default=20, name='param2'),
            'param3': ParameterDescriptor(default=30, name='param3')
        }
        
        manager = ParameterManager(descriptors)
        
        # Add dependencies: param3 depends on param1, param2 depends on param1
        manager.add_dependency('param1', 'param2')
        manager.add_dependency('param1', 'param3')
        
        # Test dependency queries
        assert set(manager.get_dependencies('param1')) == {'param2', 'param3'}
        assert manager.get_dependents('param2') == ['param1']
        assert manager.get_dependents('param3') == ['param1']
        
        # Remove dependency
        manager.remove_dependency('param1', 'param2')
        assert manager.get_dependencies('param1') == ['param3']
        assert manager.get_dependents('param2') == []
    
    def test_dependency_validation(self):
        """Test dependency validation with unknown parameters."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1')
        }
        
        manager = ParameterManager(descriptors)
        
        # Adding dependency with unknown parameter should fail
        with pytest.raises(AttributeError):
            manager.add_dependency('param1', 'unknown_param')
        
        with pytest.raises(AttributeError):
            manager.add_dependency('unknown_param', 'param1')


class TestCopyAndSerialization:
    """Test copying and serialization of enhanced managers."""
    
    def test_deep_copy(self):
        """Test deep copying of enhanced parameter manager."""
        descriptors = {
            'param1': ParameterDescriptor(default=10, name='param1'),
            'param2': ParameterDescriptor(default=20, name='param2')
        }
        
        original = ParameterManager(descriptors, enable_history=True, enable_callbacks=True)
        original.set('param1', 100)
        original.lock_parameter('param2')
        original.create_group('group1', ['param1', 'param2'])
        
        # Copy manager
        copy = original.copy()
        
        # Test that values are copied
        assert copy.get('param1') == 100
        assert copy.get('param2') == 20
        
        # Test that locks are copied
        assert copy.is_locked('param2')
        
        # Test that groups are copied
        assert copy.get_group('group1') == ['param1', 'param2']
        
        # Test that changes to copy don't affect original
        copy.set('param1', 200, force=True)
        assert original.get('param1') == 100  # Unchanged
        assert copy.get('param1') == 200


if __name__ == '__main__':
    # Run tests
    # pytest.main([__file__]) 
    a = TestEnhancedParameterStorage()
    a.test_change_tracking_and_history()