"""Tests for Parameter Inheritance (Day 39-41).

This module comprehensively tests the parameter inheritance functionality including:
* Multi-level inheritance testing
* Parameter override testing
* Edge case testing

All tests validate the behavior of the parameter system in complex inheritance
scenarios to ensure proper parameter propagation, overriding, and accessibility
through class hierarchies.
"""

import os
import sys
from typing import Any

import pytest

import backtrader as bt

from backtrader.parameters import (
    Float,
    Int,
    OneOf,
    ParameterDescriptor,
    ParameterizedBase,
    ParameterManager,
    ParameterValidationError,
    String,
)


class TestMultiLevelInheritance:
    """Test multi-level parameter inheritance scenarios.

    This test class validates that parameters are correctly inherited and
    accessible through various inheritance chain depths and patterns.
    """

    def test_single_level_inheritance(self):
        """Test basic single-level inheritance.

        Creates a base class with parameters and a child class that adds
        additional parameters. Verifies that the child class has access to
        both inherited and own parameters.
        """

        class BaseClass(ParameterizedBase):
            """Base class with two parameters for testing single-level inheritance.

            Attributes:
                param1: First integer parameter with default value 10.
                param2: String parameter with default value "base".
            """
            param1 = ParameterDescriptor(default=10, type_=int, doc="Base parameter 1")
            param2 = ParameterDescriptor(default="base", type_=str, doc="Base parameter 2")

        class ChildClass(BaseClass):
            """Child class that adds a third parameter to the base class.

            Inherits param1 and param2 from BaseClass and adds param3.

            Attributes:
                param3: Float parameter with default value 20.0.
            """
            param3 = ParameterDescriptor(default=20.0, type_=float, doc="Child parameter 3")

        # Test base class
        base_obj = BaseClass()
        assert base_obj.get_param("param1") == 10
        assert base_obj.get_param("param2") == "base"

        # Test child class inherits base parameters
        child_obj = ChildClass()
        assert child_obj.get_param("param1") == 10  # Inherited
        assert child_obj.get_param("param2") == "base"  # Inherited
        assert child_obj.get_param("param3") == 20.0  # Own parameter

        # Test parameter lists
        base_params = set(base_obj._param_manager.keys())
        child_params = set(child_obj._param_manager.keys())

        assert base_params == {"param1", "param2"}
        assert child_params == {"param1", "param2", "param3"}
        assert base_params.issubset(child_params)

    def test_two_level_inheritance(self):
        """Test two-level inheritance chain.

        Creates a grandparent -> parent -> child inheritance chain and verifies:
        * All parameters from all levels are accessible
        * Parameters overridden in intermediate classes use the override value
        * The complete parameter list includes all unique parameters

        Raises:
            AssertionError: If parameters are not properly inherited or overridden.
        """

        class GrandparentClass(ParameterizedBase):
            """Grandparent class at the top of the inheritance chain.

            Attributes:
                grandparent_param: Integer parameter unique to grandparent level.
                shared_param: String parameter that will be overridden by child classes.
            """
            grandparent_param = ParameterDescriptor(
                default=1, type_=int, doc="Grandparent parameter"
            )
            shared_param = ParameterDescriptor(
                default="grandparent", type_=str, doc="Shared parameter"
            )

        class ParentClass(GrandparentClass):
            """Parent class that inherits from and overrides grandparent parameters.

            Attributes:
                parent_param: Integer parameter unique to parent level.
                shared_param: Overrides the grandparent's shared_param.
            """
            parent_param = ParameterDescriptor(default=2, type_=int, doc="Parent parameter")
            shared_param = ParameterDescriptor(
                default="parent", type_=str, doc="Parent overrides shared"
            )

        class ChildClass(ParentClass):
            """Child class at the bottom of the inheritance chain.

            Attributes:
                child_param: Integer parameter unique to child level.
            """
            child_param = ParameterDescriptor(default=3, type_=int, doc="Child parameter")

        child_obj = ChildClass()

        # Test all parameters are accessible
        assert child_obj.get_param("grandparent_param") == 1
        assert child_obj.get_param("parent_param") == 2
        assert child_obj.get_param("child_param") == 3

        # Test parameter override works
        assert child_obj.get_param("shared_param") == "parent"  # Parent overrides grandparent

        # Test complete parameter list
        all_params = set(child_obj._param_manager.keys())
        expected_params = {"grandparent_param", "parent_param", "child_param", "shared_param"}
        assert all_params == expected_params

    def test_three_level_inheritance(self):
        """Test three-level inheritance chain.

        Creates a 4-level inheritance chain where a parameter is overridden
        at multiple levels. Verifies that the final override value is used
        and all unique parameters are accessible.

        Raises:
            AssertionError: If parameter count or override values are incorrect.
        """

        class Level1(ParameterizedBase):
            """First level in the 4-level inheritance chain.

            Attributes:
                level1_param: Unique integer parameter for level 1.
                cascade_param: String parameter overridden at multiple levels.
            """
            level1_param = ParameterDescriptor(default=1, type_=int)
            cascade_param = ParameterDescriptor(default="level1", type_=str)

        class Level2(Level1):
            """Second level in the inheritance chain.

            Attributes:
                level2_param: Unique integer parameter for level 2.
                cascade_param: Overrides level1's cascade_param.
            """
            level2_param = ParameterDescriptor(default=2, type_=int)
            cascade_param = ParameterDescriptor(default="level2", type_=str)

        class Level3(Level2):
            """Third level in the inheritance chain.

            Attributes:
                level3_param: Unique integer parameter for level 3.
                cascade_param: Overrides level2's cascade_param (final override).
            """
            level3_param = ParameterDescriptor(default=3, type_=int)
            cascade_param = ParameterDescriptor(default="level3", type_=str)

        class Level4(Level3):
            """Fourth and final level in the inheritance chain.

            Attributes:
                level4_param: Unique integer parameter for level 4.
            """
            level4_param = ParameterDescriptor(default=4, type_=int)

        obj = Level4()

        # Test all levels are accessible
        assert obj.get_param("level1_param") == 1
        assert obj.get_param("level2_param") == 2
        assert obj.get_param("level3_param") == 3
        assert obj.get_param("level4_param") == 4

        # Test final override wins
        assert obj.get_param("cascade_param") == "level3"  # Level3 is the final override

        # Test parameter count
        assert len(obj._param_manager.keys()) == 5  # 4 unique + 1 overridden

    def test_diamond_inheritance(self):
        """Test diamond inheritance pattern.

        Tests the classic diamond inheritance pattern where two classes inherit
        from a common base and are then both inherited by a final class. Verifies
        proper Method Resolution Order (MRO) behavior for parameter conflicts.

        Diamond structure:
                    Base
                   /    \
                Left    Right
                   \    /
                  Diamond

        Raises:
            AssertionError: If MRO resolution or parameter inheritance fails.
        """

        class Base(ParameterizedBase):
            """Base class at the top of the diamond inheritance pattern.

            Attributes:
                base_param: String parameter unique to the base class.
                shared_param: String parameter overridden by both Left and Right.
            """
            base_param = ParameterDescriptor(default="base", type_=str)
            shared_param = ParameterDescriptor(default="base_shared", type_=str)

        class Left(Base):
            """Left branch of the diamond inheritance pattern.

            Attributes:
                left_param: String parameter unique to the left branch.
                shared_param: Overrides base's shared_param (should win in MRO).
            """
            left_param = ParameterDescriptor(default="left", type_=str)
            shared_param = ParameterDescriptor(default="left_shared", type_=str)

        class Right(Base):
            """Right branch of the diamond inheritance pattern.

            Attributes:
                right_param: String parameter unique to the right branch.
                shared_param: Overrides base's shared_param (loses in MRO to Left).
            """
            right_param = ParameterDescriptor(default="right", type_=str)
            shared_param = ParameterDescriptor(default="right_shared", type_=str)

        class Diamond(Left, Right):
            """Bottom class that completes the diamond pattern.

            Attributes:
                diamond_param: String parameter unique to the diamond class.
            """
            diamond_param = ParameterDescriptor(default="diamond", type_=str)

        obj = Diamond()

        # Test all parameters are accessible
        assert obj.get_param("base_param") == "base"
        assert obj.get_param("left_param") == "left"
        assert obj.get_param("right_param") == "right"
        assert obj.get_param("diamond_param") == "diamond"

        # Test MRO resolution (Left should win due to MRO)
        assert obj.get_param("shared_param") == "left_shared"

        # Test parameter count
        all_params = set(obj._param_manager.keys())
        expected_params = {
            "base_param",
            "left_param",
            "right_param",
            "diamond_param",
            "shared_param",
        }
        assert all_params == expected_params


class TestParameterOverrides:
    """Test parameter override behavior in inheritance.

    Validates how parameters can be overridden in child classes, including
    default values, types, validators, and documentation.
    """

    def test_default_value_override(self):
        """Test overriding default values in child classes.

        Verifies that child classes can override the default values of
        inherited parameters without affecting the base class defaults.

        Raises:
            AssertionError: If default values are not properly overridden.
        """

        class BaseClass(ParameterizedBase):
            """Base class with default values to be overridden by child.

            Attributes:
                number_param: Integer parameter with base default of 10.
                string_param: String parameter with base default of "base".
            """
            number_param = ParameterDescriptor(default=10, type_=int, doc="Base number")
            string_param = ParameterDescriptor(default="base", type_=str, doc="Base string")

        class ChildClass(BaseClass):
            """Child class that overrides base class default values.

            Attributes:
                number_param: Integer parameter with child default of 20.
                string_param: String parameter with child default of "child".
            """
            number_param = ParameterDescriptor(default=20, type_=int, doc="Child number")
            string_param = ParameterDescriptor(default="child", type_=str, doc="Child string")

        base_obj = BaseClass()
        child_obj = ChildClass()

        # Test base defaults
        assert base_obj.get_param("number_param") == 10
        assert base_obj.get_param("string_param") == "base"

        # Test child overrides
        assert child_obj.get_param("number_param") == 20
        assert child_obj.get_param("string_param") == "child"

    def test_type_change_override(self):
        """Test changing parameter types in inheritance.

        Verifies that child classes can change the type of inherited parameters,
        and that the new type validation is enforced.

        Raises:
            AssertionError: If type changes are not properly applied.
        """

        class BaseClass(ParameterizedBase):
            """Base class with an integer parameter.

            Attributes:
                flexible_param: Integer parameter that child will change to float.
            """
            flexible_param = ParameterDescriptor(default=10, type_=int, doc="Integer parameter")

        class ChildClass(BaseClass):
            """Child class that changes parameter type from int to float.

            Attributes:
                flexible_param: Float parameter overriding base's integer parameter.
            """
            flexible_param = ParameterDescriptor(default=10.5, type_=float, doc="Float parameter")

        base_obj = BaseClass()
        child_obj = ChildClass()

        # Test type enforcement
        base_obj.set_param("flexible_param", 15)
        assert base_obj.get_param("flexible_param") == 15

        child_obj.set_param("flexible_param", 15.7)
        assert child_obj.get_param("flexible_param") == 15.7

        # Test type validation
        with pytest.raises(ValueError):
            child_obj.set_param("flexible_param", "not a float")

    def test_validator_override(self):
        """Test overriding validators in inheritance.

        Verifies that child classes can override parameter validators,
        allowing different validation rules for inherited parameters.

        Raises:
            AssertionError: If validator overrides are not properly applied.
        """

        class BaseClass(ParameterizedBase):
            """Base class with a parameter validated for range 0-10.

            Attributes:
                range_param: Integer parameter with base validation range of 0-10.
            """
            range_param = ParameterDescriptor(
                default=5, type_=int, validator=Int(min_val=0, max_val=10), doc="Base range 0-10"
            )

        class ChildClass(BaseClass):
            """Child class that expands validation range to 0-100.

            Attributes:
                range_param: Integer parameter with child validation range of 0-100.
            """
            range_param = ParameterDescriptor(
                default=50,
                type_=int,
                validator=Int(min_val=0, max_val=100),
                doc="Child range 0-100",
            )

        base_obj = BaseClass()
        child_obj = ChildClass()

        # Test base validation
        base_obj.set_param("range_param", 8)
        assert base_obj.get_param("range_param") == 8

        with pytest.raises(ValueError):
            base_obj.set_param("range_param", 15)  # Outside base range

        # Test child validation
        child_obj.set_param("range_param", 75)
        assert child_obj.get_param("range_param") == 75

        with pytest.raises(ValueError):
            child_obj.set_param("range_param", 150)  # Outside child range

    def test_documentation_inheritance(self):
        """Test documentation inheritance and override.

        Verifies that parameter documentation can be overridden in child classes
        and that the documentation is accessible through parameter descriptors.

        Raises:
            AssertionError: If documentation is not properly inherited or overridden.
        """

        class BaseClass(ParameterizedBase):
            """Base class with documented parameter.

            Attributes:
                documented_param: String parameter with base documentation.
            """
            documented_param = ParameterDescriptor(default="base", doc="Base documentation")

        class ChildClass(BaseClass):
            """Child class that overrides parameter documentation.

            Attributes:
                documented_param: String parameter with child documentation.
            """
            documented_param = ParameterDescriptor(
                default="child", doc="Child documentation overrides base"
            )

        base_obj = BaseClass()
        child_obj = ChildClass()

        # Test documentation is accessible through class descriptors
        base_descriptor = base_obj._param_manager._descriptors["documented_param"]
        child_descriptor = child_obj._param_manager._descriptors["documented_param"]

        assert base_descriptor.doc == "Base documentation"
        assert child_descriptor.doc == "Child documentation overrides base"

    def test_partial_override(self):
        """Test partial parameter property overrides.

        Verifies that child classes can override specific properties of a
        parameter (such as default value and validator) while keeping others
        (such as type) consistent.

        Raises:
            AssertionError: If partial overrides are not properly applied.
        """

        class BaseClass(ParameterizedBase):
            """Base class with a complex parameter having all properties.

            Attributes:
                complex_param: Integer parameter with base validation range 0-20.
            """
            complex_param = ParameterDescriptor(
                default=10,
                type_=int,
                validator=Int(min_val=0, max_val=20),
                doc="Complex parameter with all properties",
            )

        class ChildClass(BaseClass):
            """Child class that partially overrides complex parameter properties.

            Attributes:
                complex_param: Integer parameter with child validation range 5-25.
            """
            # Only override default and validator, keep type and doc
            complex_param = ParameterDescriptor(
                default=15,
                type_=int,
                validator=Int(min_val=5, max_val=25),
                doc="Updated documentation",
            )

        base_obj = BaseClass()
        child_obj = ChildClass()

        # Test defaults
        assert base_obj.get_param("complex_param") == 10
        assert child_obj.get_param("complex_param") == 15

        # Test validation ranges
        base_obj.set_param("complex_param", 2)  # Valid for base
        child_obj.set_param("complex_param", 7)  # Valid for child

        with pytest.raises(ValueError):
            child_obj.set_param("complex_param", 2)  # Below child minimum


class TestInheritanceEdgeCases:
    """Test edge cases and boundary conditions in parameter inheritance.

    This test class covers unusual or edge-case scenarios that may occur
    when using parameter inheritance in complex or non-standard ways.
    """

    def test_empty_base_class(self):
        """Test inheritance from class with no parameters.

        Verifies that a child class can add parameters even when the
        base class has no parameters defined.

        Raises:
            AssertionError: If child class parameters are not properly initialized.
        """

        class EmptyBase(ParameterizedBase):
            """Base class with no parameters defined."""

        class ChildWithParams(EmptyBase):
            """Child class that adds parameters to an empty base.

            Attributes:
                child_param: Integer parameter with default value 42.
            """
            child_param = ParameterDescriptor(default=42, type_=int)

        obj = ChildWithParams()

        assert obj.get_param("child_param") == 42
        assert len(obj._param_manager.keys()) == 1

    def test_empty_child_class(self):
        """Test child class with no additional parameters.

        Verifies that a child class with no additional parameters still
        inherits all parameters from its base class.

        Raises:
            AssertionError: If inherited parameters are not accessible.
        """

        class BaseWithParams(ParameterizedBase):
            """Base class with parameters to be inherited.

            Attributes:
                base_param: String parameter with default value "base".
            """
            base_param = ParameterDescriptor(default="base", type_=str)

        class EmptyChild(BaseWithParams):
            """Child class with no additional parameters, inherits from base."""

        obj = EmptyChild()

        assert obj.get_param("base_param") == "base"
        assert len(obj._param_manager.keys()) == 1

    def test_multiple_inheritance_same_parameter(self):
        """Test multiple inheritance with same parameter names.

        Verifies that when multiple parent classes define the same parameter,
        the first one in MRO (Method Resolution Order) takes precedence.

        Raises:
            AssertionError: If MRO-based parameter resolution fails.
        """

        class Mixin1(ParameterizedBase):
            """First mixin class in multiple inheritance chain.

            Attributes:
                common_param: String parameter that conflicts with Mixin2 (should win).
                mixin1_param: Unique integer parameter for Mixin1.
            """
            common_param = ParameterDescriptor(default="mixin1", type_=str)
            mixin1_param = ParameterDescriptor(default=1, type_=int)

        class Mixin2(ParameterizedBase):
            """Second mixin class in multiple inheritance chain.

            Attributes:
                common_param: String parameter that conflicts with Mixin1 (loses).
                mixin2_param: Unique integer parameter for Mixin2.
            """
            common_param = ParameterDescriptor(default="mixin2", type_=str)
            mixin2_param = ParameterDescriptor(default=2, type_=int)

        class Combined(Mixin1, Mixin2):
            """Combined class inheriting from both mixins.

            Attributes:
                combined_param: Unique string parameter for the combined class.
            """
            combined_param = ParameterDescriptor(default="combined", type_=str)

        obj = Combined()

        # First mixin should win (MRO order)
        assert obj.get_param("common_param") == "mixin1"
        assert obj.get_param("mixin1_param") == 1
        assert obj.get_param("mixin2_param") == 2
        assert obj.get_param("combined_param") == "combined"

    def test_parameter_name_conflicts(self):
        """Test handling of parameter name conflicts.

        Verifies that when a child class defines a parameter with the same
        name as a base class parameter, the child version completely overrides
        the base version (no duplicate parameters).

        Raises:
            AssertionError: If parameter conflicts are not properly resolved.
        """

        class Base(ParameterizedBase):
            """Base class with a parameter that will be overridden by child.

            Attributes:
                conflict_param: String parameter with base value that will be overridden.
            """
            conflict_param = ParameterDescriptor(default="base", type_=str, doc="Base version")

        class Child(Base):
            """Child class that completely overrides base's conflict_param.

            Attributes:
                conflict_param: String parameter overriding base's parameter.
            """
            conflict_param = ParameterDescriptor(default="child", type_=str, doc="Child version")
            # This should override the base parameter completely

        obj = Child()

        # Child version should be used
        assert obj.get_param("conflict_param") == "child"

        # There should be only one parameter with this name
        params = list(obj._param_manager.keys())
        conflict_count = sum(1 for p in params if p == "conflict_param")
        assert conflict_count == 1

    def test_inheritance_with_initialization_parameters(self):
        """Test inheritance behavior with initialization parameters.

        Verifies that parameters can be set during object initialization,
        including inherited and overridden parameters.

        Raises:
            AssertionError: If initialization parameters are not properly applied.
        """

        class BaseClass(ParameterizedBase):
            """Base class with parameters for initialization testing.

            Attributes:
                base_param: Integer parameter with default value 10.
                shared_param: String parameter overridden by child with default "base".
            """
            base_param = ParameterDescriptor(default=10, type_=int)
            shared_param = ParameterDescriptor(default="base", type_=str)

        class ChildClass(BaseClass):
            """Child class that overrides shared_param and adds child_param.

            Attributes:
                child_param: Integer parameter with default value 20.
                shared_param: String parameter overriding base's shared_param with default "child".
            """
            child_param = ParameterDescriptor(default=20, type_=int)
            shared_param = ParameterDescriptor(default="child", type_=str)

        # Test initialization with parent parameters
        obj1 = ChildClass(base_param=15, child_param=25)
        assert obj1.get_param("base_param") == 15
        assert obj1.get_param("child_param") == 25
        assert obj1.get_param("shared_param") == "child"  # Default from child

        # Test initialization with overridden parameters
        obj2 = ChildClass(shared_param="init_value")
        assert obj2.get_param("shared_param") == "init_value"
        assert obj2.get_param("base_param") == 10  # Default from base
        assert obj2.get_param("child_param") == 20  # Default from child

    def test_descriptor_identity_inheritance(self):
        """Test that parameter descriptors maintain identity through inheritance.

        Verifies that inherited parameters use the same descriptor object
        with the same properties (default, type, documentation) across
        the inheritance hierarchy.

        Raises:
            AssertionError: If descriptor properties are not preserved.
        """

        class BaseClass(ParameterizedBase):
            """Base class with a parameter to test descriptor identity.

            Attributes:
                base_param: String parameter whose descriptor should be inherited unchanged.
            """
            base_param = ParameterDescriptor(default="base", type_=str)

        class ChildClass(BaseClass):
            """Child class that adds its own parameter.

            Attributes:
                child_param: String parameter unique to the child class.
            """
            child_param = ParameterDescriptor(default="child", type_=str)

        base_obj = BaseClass()
        child_obj = ChildClass()

        # The same descriptor should be used for the same parameter
        base_descriptor = base_obj._param_manager._descriptors["base_param"]
        child_base_descriptor = child_obj._param_manager._descriptors["base_param"]

        # They should have the same properties
        assert base_descriptor.default == child_base_descriptor.default
        assert base_descriptor.type_ == child_base_descriptor.type_
        assert base_descriptor.doc == child_base_descriptor.doc

    def test_complex_inheritance_chain_performance(self):
        """Test performance with complex inheritance chains.

        Creates a 6-level inheritance chain and verifies that parameter
        operations remain efficient. This is a performance sanity check
        to ensure inheritance doesn't introduce significant overhead.

        Raises:
            AssertionError: If operations take longer than expected.
        """

        # Create a 5-level inheritance chain
        class Level0(ParameterizedBase):
            """Level 0 of the performance test chain.

            Attributes:
                param0: Integer parameter with default value 0.
            """
            param0 = ParameterDescriptor(default=0, type_=int)

        class Level1(Level0):
            """Level 1 of the performance test chain.

            Attributes:
                param1: Integer parameter with default value 1.
            """
            param1 = ParameterDescriptor(default=1, type_=int)

        class Level2(Level1):
            """Level 2 of the performance test chain.

            Attributes:
                param2: Integer parameter with default value 2.
            """
            param2 = ParameterDescriptor(default=2, type_=int)

        class Level3(Level2):
            """Level 3 of the performance test chain.

            Attributes:
                param3: Integer parameter with default value 3.
            """
            param3 = ParameterDescriptor(default=3, type_=int)

        class Level4(Level3):
            """Level 4 of the performance test chain.

            Attributes:
                param4: Integer parameter with default value 4.
            """
            param4 = ParameterDescriptor(default=4, type_=int)

        class Level5(Level4):
            """Level 5 of the performance test chain.

            Attributes:
                param5: Integer parameter with default value 5.
            """
            param5 = ParameterDescriptor(default=5, type_=int)

        # This should not take excessive time
        import time

        start_time = time.time()

        obj = Level5()

        # Test all parameters are accessible
        for i in range(6):
            assert obj.get_param(f"param{i}") == i

        # Test parameter operations
        obj.set_param("param0", 100)
        obj.set_param("param5", 500)

        assert obj.get_param("param0") == 100
        assert obj.get_param("param5") == 500

        end_time = time.time()

        # Should complete quickly (less than 1 second for this simple test)
        assert end_time - start_time < 1.0

        # Test all parameters are present
        all_params = list(obj._param_manager.keys())
        assert len(all_params) == 6
        assert all(f"param{i}" in all_params for i in range(6))


class TestInheritanceWithAdvancedFeatures:
    """Test inheritance with advanced parameter manager features.

    This test class validates that advanced ParameterManager features
    (locking, grouping, change tracking) work correctly with inheritance.
    """

    def test_inheritance_with_parameter_locking(self):
        """Test parameter locking behavior in inheritance.

        Verifies that inherited parameters can be locked and that the
        locking mechanism prevents modification even for inherited parameters.

        Raises:
            AssertionError: If parameter locking fails for inherited parameters.
        """

        class BaseClass(ParameterizedBase):
            """Base class with a parameter that can be locked.

            Attributes:
                lockable_param: Integer parameter that will be locked by the test.
            """
            lockable_param = ParameterDescriptor(default=10, type_=int)

        class ChildClass(BaseClass):
            """Child class with an additional unlocked parameter.

            Attributes:
                child_param: Integer parameter that remains unlocked.
            """
            child_param = ParameterDescriptor(default=20, type_=int)

        obj = ChildClass()

        # Lock a parameter from the base class
        obj._param_manager.lock_parameter("lockable_param")

        # Should not be able to modify locked parameter
        with pytest.raises(ValueError, match="locked"):
            obj.set_param("lockable_param", 15)

        # Should still be able to modify unlocked parameters
        obj.set_param("child_param", 25)
        assert obj.get_param("child_param") == 25

    def test_inheritance_with_parameter_grouping(self):
        """Test parameter grouping behavior in inheritance.

        Verifies that parameters from different inheritance levels can be
        grouped together and that group operations work correctly.

        Raises:
            AssertionError: If parameter grouping fails across inheritance levels.
        """

        class BaseClass(ParameterizedBase):
            """Base class with parameters to be grouped.

            Attributes:
                base_param1: First integer parameter from base class.
                base_param2: Second integer parameter from base class.
            """
            base_param1 = ParameterDescriptor(default=1, type_=int)
            base_param2 = ParameterDescriptor(default=2, type_=int)

        class ChildClass(BaseClass):
            """Child class with additional parameters to be grouped.

            Attributes:
                child_param1: First integer parameter from child class.
                child_param2: Second integer parameter from child class.
            """
            child_param1 = ParameterDescriptor(default=3, type_=int)
            child_param2 = ParameterDescriptor(default=4, type_=int)

        obj = ChildClass()

        # Create groups
        obj._param_manager.create_group("base_group", ["base_param1", "base_param2"])
        obj._param_manager.create_group("child_group", ["child_param1", "child_param2"])

        # Test group operations
        obj._param_manager.set_group("base_group", {"base_param1": 10, "base_param2": 20})

        assert obj.get_param("base_param1") == 10
        assert obj.get_param("base_param2") == 20
        assert obj.get_param("child_param1") == 3  # Unchanged
        assert obj.get_param("child_param2") == 4  # Unchanged

    def test_inheritance_with_change_tracking(self):
        """Test change tracking behavior in inheritance.

        Verifies that the ParameterManager's change tracking feature works
        correctly for both inherited and child-class-defined parameters.

        Raises:
            AssertionError: If change history is not properly recorded.
        """

        class BaseClass(ParameterizedBase):
            """Base class with a parameter for change tracking.

            Attributes:
                tracked_param: String parameter whose changes will be tracked.
            """
            tracked_param = ParameterDescriptor(default="base", type_=str)

        class ChildClass(BaseClass):
            """Child class with an additional parameter for change tracking.

            Attributes:
                child_tracked: String parameter unique to child class for tracking.
            """
            child_tracked = ParameterDescriptor(default="child", type_=str)

        obj = ChildClass()

        # Make some changes
        obj.set_param("tracked_param", "modified_base")
        obj.set_param("child_tracked", "modified_child")
        obj.set_param("tracked_param", "final_base")

        # Check change history for specific parameters
        tracked_history = obj._param_manager.get_change_history("tracked_param")
        child_history = obj._param_manager.get_change_history("child_tracked")

        # Should have recorded changes for both parameters
        assert len(tracked_history) >= 2  # At least 2 changes to tracked_param
        assert len(child_history) >= 1  # At least 1 change to child_tracked

        # Verify the latest values are correct
        assert obj.get_param("tracked_param") == "final_base"
        assert obj.get_param("child_tracked") == "modified_child"


if __name__ == "__main__":
    # Run tests when module is executed directly
    pytest.main([__file__, "-v"])
