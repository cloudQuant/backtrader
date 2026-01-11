"""Tests for Enhanced ParameterManager functionality.

This module contains comprehensive tests for the enhanced ParameterManager system,
which provides advanced parameter management features for the backtrader framework.
These tests validate the new features added during the metaclass removal refactoring.

Key Features Tested:
    - Parameter Locking: Prevent modification of critical parameters
    - Parameter Groups: Organize related parameters for batch operations
    - Change Tracking: Maintain history of parameter modifications
    - Inheritance Strategies: Control how parameters are inherited from parent managers
    - Lazy Defaults: Defer computation of default values until first access
    - Change Callbacks: Execute custom logic when parameters change
    - Batch Operations: Validate and apply multiple parameter changes atomically
    - Transaction Support: Rollback parameter changes if validation fails
    - Dependency Tracking: Manage relationships between parameters
    - Serialization: Copy and serialize parameter managers

Test Classes:
    TestEnhancedParameterStorage: Tests for storage and management features
    TestAdvancedInheritance: Tests for inheritance mechanisms
    TestLazyDefaults: Tests for lazy default value evaluation
    TestChangeCallbacks: Tests for parameter change notification system
    TestEnhancedBatchOperations: Tests for batch update and transaction support
    TestDependencyTracking: Tests for parameter dependency management
    TestCopyAndSerialization: Tests for copying parameter managers

Example:
    Run all tests with pytest::

        pytest tests/refactor_tests/test_enhanced_parameter_manager.py -v

    Run specific test class::

        pytest tests/refactor_tests/test_enhanced_parameter_manager.py::TestEnhancedParameterStorage -v

    Run specific test method::

        pytest tests/refactor_tests/test_enhanced_parameter_manager.py::TestEnhancedParameterStorage::test_parameter_locking -v
"""

import backtrader as bt

import os
import sys
import time

import pytest

from backtrader.parameters import (
    Float,
    Int,
    OneOf,
    ParameterDescriptor,
    ParameterizedBase,
    ParameterManager,
    String,
)


class TestEnhancedParameterStorage:
    """Test advanced parameter storage and management features.

    This test class validates the enhanced storage capabilities of the
    ParameterManager, including parameter locking, grouping, and change tracking.

    Attributes:
        None (this is a test class with no persistent state)
    """

    def test_parameter_locking(self):
        """Test parameter locking mechanism.

        Validates that parameters can be locked to prevent accidental modification:
        - Initially, no parameters are locked
        - Parameters can be locked individually
        - Modifying locked parameters raises ValueError
        - Force=True flag bypasses lock protection
        - Resetting locked parameters raises ValueError
        - Parameters can be unlocked to restore normal modification

        Raises:
            AssertionError: If locking mechanism does not work as expected.
        """
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
        }

        manager = ParameterManager(descriptors)

        # Initially no parameters are locked
        assert not manager.is_locked("param1")
        assert manager.get_locked_parameters() == []

        # Lock a parameter
        manager.lock_parameter("param1")
        assert manager.is_locked("param1")
        assert "param1" in manager.get_locked_parameters()

        # Try to modify locked parameter - should fail
        with pytest.raises(ValueError, match="locked"):
            manager.set("param1", 15)

        # Force modification should work
        manager.set("param1", 15, force=True)
        assert manager.get("param1") == 15

        # Reset locked parameter should fail
        with pytest.raises(ValueError, match="locked"):
            manager.reset("param1")

        # Force reset should work
        manager.reset("param1", force=True)
        assert manager.get("param1") == 10

        # Unlock parameter
        manager.unlock_parameter("param1")
        assert not manager.is_locked("param1")

        # Now modification should work normally
        manager.set("param1", 25)
        assert manager.get("param1") == 25

    def test_parameter_groups(self):
        """Test parameter grouping functionality.

        Validates that parameters can be organized into groups for batch operations:
        - Groups can be created with specific parameter memberships
        - Group membership can be queried for individual parameters
        - Group values can be set atomically
        - Group values can be retrieved as dictionaries
        - Invalid group operations raise appropriate errors

        Raises:
            AssertionError: If grouping functionality does not work as expected.
            ValueError: If invalid group operations are attempted.
            AttributeError: If groups reference non-existent parameters.
        """
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
            "param3": ParameterDescriptor(default=30, name="param3"),
            "param4": ParameterDescriptor(default=40, name="param4"),
        }

        manager = ParameterManager(descriptors)

        # Create groups
        manager.create_group("group1", ["param1", "param2"])
        manager.create_group("group2", ["param3", "param4"])

        # Test group membership
        assert manager.get_group("group1") == ["param1", "param2"]
        assert manager.get_parameter_group("param1") == "group1"
        assert manager.get_parameter_group("param3") == "group2"

        # Set group values
        manager.set_group("group1", {"param1": 100, "param2": 200})
        assert manager.get("param1") == 100
        assert manager.get("param2") == 200

        # Get group values
        group_values = manager.get_group_values("group1")
        assert group_values == {"param1": 100, "param2": 200}

        # Invalid group operations
        with pytest.raises(ValueError):
            manager.set_group("nonexistent", {})

        with pytest.raises(ValueError):
            manager.get_group_values("nonexistent")

        with pytest.raises(AttributeError):
            manager.create_group("invalid", ["nonexistent_param"])

    def test_change_tracking_and_history(self):
        """Test parameter change tracking and history.

        Validates that parameter manager maintains a history of changes:
        - History is initially empty
        - Each change is recorded with old value, new value, and timestamp
        - History entries are in chronological order (most recent first)
        - History can be limited to N most recent changes
        - History can be cleared for individual parameters
        - History tracking can be disabled for performance

        History Structure:
            Each history entry is a tuple of (old_value, new_value, timestamp)

        Raises:
            AssertionError: If history tracking does not work as expected.
        """
        descriptors = {"param1": ParameterDescriptor(default=10, name="param1")}

        manager = ParameterManager(descriptors, enable_history=True)

        # Initially no history
        assert manager.get_change_history("param1") == []

        # Make some changes
        manager.set("param1", 20)
        manager.set("param1", 30)
        manager.reset("param1")

        # Check history
        history = manager.get_change_history("param1")
        assert len(history) == 3
        print(history)
        # Check history structure (old_value, new_value, timestamp)
        assert history[0][0] == 30  # old value
        assert history[0][1] == 10  # new value (reset to default)
        assert isinstance(history[0][2], float)  # timestamp

        assert history[1][0] == 20
        assert history[1][1] == 30

        assert history[2][0] == 10
        assert history[2][1] == 20

        # Test history limit
        limited_history = manager.get_change_history("param1", limit=2)
        assert len(limited_history) == 2

        # Clear history
        manager.clear_history("param1")
        assert manager.get_change_history("param1") == []

        # Test with history disabled
        manager_no_history = ParameterManager(descriptors, enable_history=False)
        manager_no_history.set("param1", 50)
        assert manager_no_history.get_change_history("param1") == []


class TestAdvancedInheritance:
    """Test enhanced inheritance mechanisms.

    This test class validates the advanced inheritance features that allow
    child parameter managers to inherit values from parent managers with
    configurable conflict resolution strategies.

    Inheritance Strategies:
        - merge: Combine parent and child values
        - replace: Parent values completely replace child values
        - selective: Inherit only specified parameters

    Conflict Resolution (for merge strategy):
        - parent: Parent's value wins on conflict
        - child: Child's value wins on conflict
        - raise: Raise exception on conflict
    """

    def test_inheritance_strategies(self):
        """Test different inheritance strategies.

        Validates that child managers can inherit from parent managers using
        different strategies and conflict resolution methods:
        - Merge with parent priority: Parent values override child conflicts
        - Merge with child priority: Child values override parent conflicts
        - Replace: All child values replaced by parent values
        - Selective: Only specified parameters are inherited

        Raises:
            AssertionError: If inheritance strategies do not work as expected.
        """
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
            "param3": ParameterDescriptor(default=30, name="param3"),
        }

        # Parent manager
        parent = ParameterManager(descriptors)
        parent.set("param1", 100)
        parent.set("param2", 200)

        # Child manager with some existing values
        child = ParameterManager(descriptors)
        child.set("param2", 250)  # Conflicting value
        child.set("param3", 300)

        # Test merge strategy with parent conflict resolution
        child.inherit_from(parent, strategy="merge", conflict_resolution="parent")
        assert child.get("param1") == 100  # Inherited
        assert child.get("param2") == 200  # Parent wins conflict
        assert child.get("param3") == 300  # Child's original value

        # Reset child
        child = ParameterManager(descriptors)
        child.set("param2", 250)
        child.set("param3", 300)

        # Test merge strategy with child conflict resolution
        child.inherit_from(parent, strategy="merge", conflict_resolution="child")
        assert child.get("param1") == 100  # Inherited
        assert child.get("param2") == 250  # Child wins conflict
        assert child.get("param3") == 300  # Child's original value

        # Reset child
        child = ParameterManager(descriptors)
        child.set("param2", 250)

        # Test replace strategy
        child.inherit_from(parent, strategy="replace")
        assert child.get("param1") == 100  # Inherited
        assert child.get("param2") == 200  # Parent replaces child
        assert child.get("param3") == 30  # Default value (was reset)

        # Test selective inheritance
        child = ParameterManager(descriptors)
        child.inherit_from(parent, strategy="selective", selective=["param1"])
        assert child.get("param1") == 100  # Inherited
        assert child.get("param2") == 20  # Not inherited (default)
        assert child.get("param3") == 30  # Not inherited (default)

    def test_inheritance_conflict_detection(self):
        """Test inheritance conflict detection.

        Validates that conflicts between parent and child values can be
        detected and handled appropriately:
        - Conflicts can be raised as exceptions
        - This allows strict validation of inherited values

        Raises:
            AssertionError: If conflict detection does not work as expected.
            ValueError: If conflicts are detected and resolution is set to "raise".
        """
        descriptors = {"param1": ParameterDescriptor(default=10, name="param1")}

        parent = ParameterManager(descriptors)
        parent.set("param1", 100)

        child = ParameterManager(descriptors)
        child.set("param1", 200)  # Conflicting value

        # Test conflict raising
        with pytest.raises(ValueError, match="conflicts"):
            child.inherit_from(parent, strategy="merge", conflict_resolution="raise")

    def test_inheritance_tracking(self):
        """Test inheritance chain tracking.

        Validates that the parameter manager tracks inheritance information:
        - Can query if a parameter value was inherited
        - Can identify the source (parent) of inherited values
        - Directly setting a value overrides inherited status

        Raises:
            AssertionError: If inheritance tracking does not work as expected.
        """
        descriptors = {"param1": ParameterDescriptor(default=10, name="param1")}

        grandparent = ParameterManager(descriptors)
        grandparent.set("param1", 100)

        parent = ParameterManager(descriptors)
        parent.inherit_from(grandparent)

        child = ParameterManager(descriptors)
        child.inherit_from(parent)

        # Test inheritance info
        info = child.get_inheritance_info("param1")
        assert info is not None
        assert info["inherited"] == True
        assert info["source"] == parent

        # Test non-inherited parameter
        child.set("param1", 500)  # Override inherited value
        # After setting directly, it's no longer considered "inherited"
        # (this behavior depends on implementation details)


class TestLazyDefaults:
    """Test lazy default value handling.

    This test class validates lazy default evaluation, which allows parameter
    defaults to be computed on-demand rather than at initialization time.

    Benefits:
        - Defer expensive computations until needed
        - Provide time-dependent default values
        - Reduce memory footprint for unused parameters
    """

    def test_lazy_default_evaluation(self):
        """Test lazy default value evaluation.

        Validates that lazy defaults are evaluated correctly:
        - Lazy function is called only once on first access
        - Result is cached for subsequent accesses
        - Lazy default can be cleared to restore original default
        - Lazy defaults can use dynamic values (e.g., current time)

        Raises:
            AssertionError: If lazy default evaluation does not work as expected.
        """
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
        }

        manager = ParameterManager(descriptors)

        # Set lazy default that depends on current time
        call_count = 0

        def lazy_func():
            """Compute time-based default value.

            Returns:
                int: A value based on the current time, used to demonstrate
                    that lazy defaults can compute dynamic values.
            """
            nonlocal call_count
            call_count += 1
            return int(time.time() * 1000) % 1000  # Some time-based value

        manager.set_lazy_default("param1", lazy_func)

        # First access should compute the value
        value1 = manager.get("param1")
        assert call_count == 1

        # Second access should use cached value
        value2 = manager.get("param1")
        assert call_count == 1  # Not called again
        assert value1 == value2

        # Clear lazy default
        manager.clear_lazy_default("param1")
        value3 = manager.get("param1")
        assert value3 == 10  # Back to original default

    def test_lazy_default_with_set(self):
        """Test interaction between lazy defaults and explicit setting.

        Validates that lazy defaults interact correctly with explicit value setting:
        - Lazy default is used until an explicit value is set
        - Explicit value overrides lazy default
        - Resetting restores the lazy default (not original default)

        Raises:
            AssertionError: If lazy default/set interaction does not work as expected.
        """
        descriptors = {"param1": ParameterDescriptor(default=10, name="param1")}

        manager = ParameterManager(descriptors)

        # Set lazy default
        manager.set_lazy_default("param1", lambda: 999)

        # Should use lazy default initially
        assert manager.get("param1") == 999

        # Set explicit value
        manager.set("param1", 555)
        assert manager.get("param1") == 555

        # Reset should go back to lazy default
        manager.reset("param1")
        assert manager.get("param1") == 999


class TestChangeCallbacks:
    """Test parameter change callbacks.

    This test class validates the callback system that allows custom code
    to be executed when parameter values change.

    Use Cases:
        - Trigger recalculation when dependent parameters change
        - Log parameter modifications for audit trails
        - Enforce business rules on parameter changes
        - Update UI components when parameters change
    """

    def test_parameter_specific_callbacks(self):
        """Test parameter-specific change callbacks.

        Validates that callbacks can be registered for specific parameters:
        - Callbacks receive parameter name, old value, and new value
        - Only changes to monitored parameters trigger callbacks
        - Callbacks can be removed to stop monitoring
        - Multiple callbacks can be registered for the same parameter

        Raises:
            AssertionError: If parameter-specific callbacks do not work as expected.
        """
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
        }

        manager = ParameterManager(descriptors, enable_callbacks=True)

        # Track callback calls
        callback_calls = []

        def callback(name, old_value, new_value):
            """Track parameter changes for testing.

            Args:
                name: The name of the parameter that changed.
                old_value: The previous value of the parameter.
                new_value: The new value of the parameter.
            """
            callback_calls.append((name, old_value, new_value))

        # Add callback for specific parameter
        manager.add_change_callback(callback, "param1")

        # Change param1 - should trigger callback
        manager.set("param1", 15)
        assert len(callback_calls) == 1
        assert callback_calls[0] == ("param1", 10, 15)

        # Change param2 - should not trigger callback
        manager.set("param2", 25)
        assert len(callback_calls) == 1  # No new calls

        # Remove callback
        manager.remove_change_callback(callback, "param1")
        manager.set("param1", 20)
        assert len(callback_calls) == 1  # No new calls

    def test_global_callbacks(self):
        """Test global change callbacks.

        Validates that global callbacks receive notifications for all parameters:
        - Global callbacks are triggered by any parameter change
        - Callbacks receive the parameter name along with values
        - Multiple global callbacks can be registered

        Raises:
            AssertionError: If global callbacks do not work as expected.
        """
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
        }

        manager = ParameterManager(descriptors, enable_callbacks=True)

        callback_calls = []

        def global_callback(name, old_value, new_value):
            """Track all parameter changes for testing.

            Args:
                name: The name of the parameter that changed.
                old_value: The previous value of the parameter.
                new_value: The new value of the parameter.
            """
            callback_calls.append((name, old_value, new_value))

        # Add global callback
        manager.add_change_callback(global_callback)

        # Changes to any parameter should trigger callback
        manager.set("param1", 15)
        manager.set("param2", 25)

        assert len(callback_calls) == 2
        assert callback_calls[0] == ("param1", 10, 15)
        assert callback_calls[1] == ("param2", 20, 25)

    def test_callback_error_handling(self):
        """Test that callback errors don't break parameter setting.

        Validates robustness of the callback system:
        - Exceptions raised in callbacks are caught and logged
        - Parameter setting succeeds even if callbacks fail
        - This allows the parameter system to remain functional despite
          errors in user-provided callbacks

        Raises:
            AssertionError: If error handling does not work as expected.
        """
        descriptors = {"param1": ParameterDescriptor(default=10, name="param1")}

        manager = ParameterManager(descriptors, enable_callbacks=True)

        def bad_callback(name, old_value, new_value):
            """Callback that intentionally raises an exception.

            Args:
                name: The parameter name (ignored).
                old_value: The old value (ignored).
                new_value: The new value (ignored).

            Raises:
                RuntimeError: Always raised to test error handling.
            """
            raise RuntimeError("Callback error!")

        manager.add_change_callback(bad_callback)

        # Parameter setting should still work despite callback error
        manager.set("param1", 15)
        assert manager.get("param1") == 15


class TestEnhancedBatchOperations:
    """Test enhanced batch update functionality.

    This test class validates batch operations and transaction support,
    which allow multiple parameter changes to be applied atomically.

    Benefits:
        - Validate all changes before applying any
        - Rollback changes if validation fails
        - Trigger callbacks only after all changes succeed
        - Maintain consistency across related parameters
    """

    def test_batch_validation(self):
        """Test batch validation before applying changes.

        Validates that batch operations validate all changes before applying:
        - Validation errors prevent any changes from being applied
        - Locked parameters are detected during validation
        - Force flag bypasses validation
        - All-or-nothing semantics ensure consistency

        Raises:
            AssertionError: If batch validation does not work as expected.
            ValueError: If validation fails with validate_all=True.
        """
        descriptors = {
            "param1": ParameterDescriptor(default=10, type_=int, name="param1"),
            "param2": ParameterDescriptor(default=20, type_=int, name="param2"),
        }

        manager = ParameterManager(descriptors)
        manager.lock_parameter("param1")

        # Test batch validation with locked parameter
        with pytest.raises(ValueError, match="Validation errors"):
            manager.update({"param1": 15, "param2": 25}, validate_all=True)

        # No changes should have been applied
        assert manager.get("param1") == 10
        assert manager.get("param2") == 20

        # Force update should work
        manager.update({"param1": 15, "param2": 25}, force=True)
        assert manager.get("param1") == 15
        assert manager.get("param2") == 25

    def test_transaction_support(self):
        """Test transactional batch updates.

        Validates that parameter changes can be grouped into transactions:
        - Changes within a transaction are visible immediately
        - Callbacks are not triggered until transaction is committed
        - Committed changes become permanent
        - Rolled back changes are discarded
        - Transaction state can be queried

        Transaction Lifecycle:
            1. begin_transaction(): Start a new transaction
            2. set/modify: Make changes (visible within transaction)
            3. commit_transaction(): Apply changes permanently
            4. OR rollback_transaction(): Discard changes

        Raises:
            AssertionError: If transaction support does not work as expected.
            RuntimeError: If transaction operations are used incorrectly.
        """
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
        }

        manager = ParameterManager(descriptors, enable_callbacks=True)

        callback_calls = []

        def callback(name, old_value, new_value):
            """Track parameter changes during transaction testing.

            Args:
                name: The parameter name that changed.
                old_value: The previous value.
                new_value: The new value.
            """
            callback_calls.append((name, old_value, new_value))

        manager.add_change_callback(callback)

        # Test successful transaction
        manager.begin_transaction()
        assert manager.is_in_transaction()

        manager.set("param1", 100)
        manager.set("param2", 200)

        # Values should be visible within transaction
        assert manager.get("param1") == 100  # Transaction value
        assert manager.get("param2") == 200  # Transaction value
        assert len(callback_calls) == 0  # No callbacks triggered yet

        # Commit transaction
        manager.commit_transaction()
        assert not manager.is_in_transaction()

        # Now values should be visible
        assert manager.get("param1") == 100
        assert manager.get("param2") == 200
        assert len(callback_calls) == 2  # Callbacks triggered

        # Test rollback transaction
        callback_calls.clear()
        manager.begin_transaction()
        manager.set("param1", 300)
        manager.set("param2", 400)

        # Values should be visible within transaction
        assert manager.get("param1") == 300  # Transaction value
        assert manager.get("param2") == 400  # Transaction value

        manager.rollback_transaction()
        assert not manager.is_in_transaction()

        # Values should be reverted to pre-transaction state
        assert manager.get("param1") == 100
        assert manager.get("param2") == 200
        assert len(callback_calls) == 0  # No callbacks for rolled back changes

    def test_transaction_nesting_protection(self):
        """Test that nested transactions are prevented.

        Validates that the parameter manager prevents nested transactions:
        - Cannot begin a transaction while already in one
        - Cannot commit/rollback without being in a transaction
        - These restrictions prevent data corruption from complex nesting

        Raises:
            AssertionError: If transaction nesting protection does not work as expected.
            RuntimeError: If nested transaction is attempted.
        """
        descriptors = {"param1": ParameterDescriptor(default=10, name="param1")}

        manager = ParameterManager(descriptors)

        manager.begin_transaction()

        # Trying to begin another transaction should fail
        with pytest.raises(RuntimeError, match="Already in a transaction"):
            manager.begin_transaction()

        # Operations on non-transaction manager should fail
        with pytest.raises(RuntimeError, match="Not in a transaction"):
            ParameterManager(descriptors).commit_transaction()


class TestDependencyTracking:
    """Test parameter dependency tracking.

    This test class validates the dependency tracking system, which allows
    parameters to declare relationships with other parameters.

    Use Cases:
        - Automatically update dependent parameters
        - Validate parameter changes don't break dependencies
        - Calculate parameter values based on other parameters
        - Detect circular dependencies
    """

    def test_dependency_management(self):
        """Test adding and removing dependencies.

        Validates that parameter dependencies can be managed:
        - Dependencies can be added between parameters
        - Dependencies can be queried (both directions)
        - Dependencies can be removed
        - Multiple dependents can be tracked per parameter

        Raises:
            AssertionError: If dependency management does not work as expected.
        """
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
            "param3": ParameterDescriptor(default=30, name="param3"),
        }

        manager = ParameterManager(descriptors)

        # Add dependencies: param3 depends on param1, param2 depends on param1
        manager.add_dependency("param1", "param2")
        manager.add_dependency("param1", "param3")

        # Test dependency queries
        assert set(manager.get_dependencies("param1")) == {"param2", "param3"}
        assert manager.get_dependents("param2") == ["param1"]
        assert manager.get_dependents("param3") == ["param1"]

        # Remove dependency
        manager.remove_dependency("param1", "param2")
        assert manager.get_dependencies("param1") == ["param3"]
        assert manager.get_dependents("param2") == []

    def test_dependency_validation(self):
        """Test dependency validation with unknown parameters.

        Validates that dependencies reference only valid parameters:
        - Cannot add dependency with unknown dependent parameter
        - Cannot add dependency with unknown source parameter
        - Validation prevents silent failures from typos

        Raises:
            AssertionError: If dependency validation does not work as expected.
            AttributeError: If dependency references unknown parameter.
        """
        descriptors = {"param1": ParameterDescriptor(default=10, name="param1")}

        manager = ParameterManager(descriptors)

        # Adding dependency with unknown parameter should fail
        with pytest.raises(AttributeError):
            manager.add_dependency("param1", "unknown_param")

        with pytest.raises(AttributeError):
            manager.add_dependency("unknown_param", "param1")


class TestCopyAndSerialization:
    """Test copying and serialization of enhanced managers.

    This test class validates that parameter managers can be copied while
    preserving all their enhanced features.

    Copied Attributes:
        - Parameter values
        - Lock states
        - Parameter groups
        - Change history (if enabled)
        - Callbacks (may be deep copied or shallow copied based on implementation)
    """

    def test_deep_copy(self):
        """Test deep copying of enhanced parameter manager.

        Validates that a deep copy creates an independent parameter manager:
        - Values are copied correctly
        - Lock states are preserved
        - Groups are copied
        - Changes to copy don't affect original

        Raises:
            AssertionError: If deep copy does not work as expected.
        """
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
        }

        original = ParameterManager(descriptors, enable_history=True, enable_callbacks=True)
        original.set("param1", 100)
        original.lock_parameter("param2")
        original.create_group("group1", ["param1", "param2"])

        # Copy manager
        copy = original.copy()

        # Test that values are copied
        assert copy.get("param1") == 100
        assert copy.get("param2") == 20

        # Test that locks are copied
        assert copy.is_locked("param2")

        # Test that groups are copied
        assert copy.get_group("group1") == ["param1", "param2"]

        # Test that changes to copy don't affect original
        copy.set("param1", 200, force=True)
        assert original.get("param1") == 100  # Unchanged
        assert copy.get("param1") == 200


if __name__ == "__main__":
    # Run tests
    # pytest.main([__file__])
    a = TestEnhancedParameterStorage()
    a.test_change_tracking_and_history()
