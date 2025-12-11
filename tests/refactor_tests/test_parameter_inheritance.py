
import backtrader as bt

"""
Tests for Parameter Inheritance (Day 39-41)

This module comprehensively tests the parameter inheritance functionality including:
- Multi-level inheritance testing
- Parameter override testing
- Edge case testing

All tests validate the behavior of the parameter system in complex inheritance scenarios.
"""

import os
import sys
from typing import Any

import pytest

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
    """Test multi-level parameter inheritance scenarios."""

    def test_single_level_inheritance(self):
        """Test basic single-level inheritance."""

        class BaseClass(ParameterizedBase):
            param1 = ParameterDescriptor(default=10, type_=int, doc="Base parameter 1")
            param2 = ParameterDescriptor(default="base", type_=str, doc="Base parameter 2")

        class ChildClass(BaseClass):
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
        """Test two-level inheritance chain."""

        class GrandparentClass(ParameterizedBase):
            grandparent_param = ParameterDescriptor(
                default=1, type_=int, doc="Grandparent parameter"
            )
            shared_param = ParameterDescriptor(
                default="grandparent", type_=str, doc="Shared parameter"
            )

        class ParentClass(GrandparentClass):
            parent_param = ParameterDescriptor(default=2, type_=int, doc="Parent parameter")
            shared_param = ParameterDescriptor(
                default="parent", type_=str, doc="Parent overrides shared"
            )

        class ChildClass(ParentClass):
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
        """Test three-level inheritance chain."""

        class Level1(ParameterizedBase):
            level1_param = ParameterDescriptor(default=1, type_=int)
            cascade_param = ParameterDescriptor(default="level1", type_=str)

        class Level2(Level1):
            level2_param = ParameterDescriptor(default=2, type_=int)
            cascade_param = ParameterDescriptor(default="level2", type_=str)

        class Level3(Level2):
            level3_param = ParameterDescriptor(default=3, type_=int)
            cascade_param = ParameterDescriptor(default="level3", type_=str)

        class Level4(Level3):
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
        """Test diamond inheritance pattern."""

        class Base(ParameterizedBase):
            base_param = ParameterDescriptor(default="base", type_=str)
            shared_param = ParameterDescriptor(default="base_shared", type_=str)

        class Left(Base):
            left_param = ParameterDescriptor(default="left", type_=str)
            shared_param = ParameterDescriptor(default="left_shared", type_=str)

        class Right(Base):
            right_param = ParameterDescriptor(default="right", type_=str)
            shared_param = ParameterDescriptor(default="right_shared", type_=str)

        class Diamond(Left, Right):
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
    """Test parameter override behavior in inheritance."""

    def test_default_value_override(self):
        """Test overriding default values in child classes."""

        class BaseClass(ParameterizedBase):
            number_param = ParameterDescriptor(default=10, type_=int, doc="Base number")
            string_param = ParameterDescriptor(default="base", type_=str, doc="Base string")

        class ChildClass(BaseClass):
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
        """Test changing parameter types in inheritance."""

        class BaseClass(ParameterizedBase):
            flexible_param = ParameterDescriptor(default=10, type_=int, doc="Integer parameter")

        class ChildClass(BaseClass):
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
        """Test overriding validators in inheritance."""

        class BaseClass(ParameterizedBase):
            range_param = ParameterDescriptor(
                default=5, type_=int, validator=Int(min_val=0, max_val=10), doc="Base range 0-10"
            )

        class ChildClass(BaseClass):
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
        """Test documentation inheritance and override."""

        class BaseClass(ParameterizedBase):
            documented_param = ParameterDescriptor(default="base", doc="Base documentation")

        class ChildClass(BaseClass):
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
        """Test partial parameter property overrides."""

        class BaseClass(ParameterizedBase):
            complex_param = ParameterDescriptor(
                default=10,
                type_=int,
                validator=Int(min_val=0, max_val=20),
                doc="Complex parameter with all properties",
            )

        class ChildClass(BaseClass):
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
    """Test edge cases and boundary conditions in parameter inheritance."""

    def test_empty_base_class(self):
        """Test inheritance from class with no parameters."""

        class EmptyBase(ParameterizedBase):
            pass

        class ChildWithParams(EmptyBase):
            child_param = ParameterDescriptor(default=42, type_=int)

        obj = ChildWithParams()

        assert obj.get_param("child_param") == 42
        assert len(obj._param_manager.keys()) == 1

    def test_empty_child_class(self):
        """Test child class with no additional parameters."""

        class BaseWithParams(ParameterizedBase):
            base_param = ParameterDescriptor(default="base", type_=str)

        class EmptyChild(BaseWithParams):
            pass

        obj = EmptyChild()

        assert obj.get_param("base_param") == "base"
        assert len(obj._param_manager.keys()) == 1

    def test_multiple_inheritance_same_parameter(self):
        """Test multiple inheritance with same parameter names."""

        class Mixin1(ParameterizedBase):
            common_param = ParameterDescriptor(default="mixin1", type_=str)
            mixin1_param = ParameterDescriptor(default=1, type_=int)

        class Mixin2(ParameterizedBase):
            common_param = ParameterDescriptor(default="mixin2", type_=str)
            mixin2_param = ParameterDescriptor(default=2, type_=int)

        class Combined(Mixin1, Mixin2):
            combined_param = ParameterDescriptor(default="combined", type_=str)

        obj = Combined()

        # First mixin should win (MRO order)
        assert obj.get_param("common_param") == "mixin1"
        assert obj.get_param("mixin1_param") == 1
        assert obj.get_param("mixin2_param") == 2
        assert obj.get_param("combined_param") == "combined"

    def test_parameter_name_conflicts(self):
        """Test handling of parameter name conflicts."""

        class Base(ParameterizedBase):
            conflict_param = ParameterDescriptor(default="base", type_=str, doc="Base version")

        class Child(Base):
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
        """Test inheritance behavior with initialization parameters."""

        class BaseClass(ParameterizedBase):
            base_param = ParameterDescriptor(default=10, type_=int)
            shared_param = ParameterDescriptor(default="base", type_=str)

        class ChildClass(BaseClass):
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
        """Test that parameter descriptors maintain identity through inheritance."""

        class BaseClass(ParameterizedBase):
            base_param = ParameterDescriptor(default="base", type_=str)

        class ChildClass(BaseClass):
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
        """Test performance with complex inheritance chains."""

        # Create a 5-level inheritance chain
        class Level0(ParameterizedBase):
            param0 = ParameterDescriptor(default=0, type_=int)

        class Level1(Level0):
            param1 = ParameterDescriptor(default=1, type_=int)

        class Level2(Level1):
            param2 = ParameterDescriptor(default=2, type_=int)

        class Level3(Level2):
            param3 = ParameterDescriptor(default=3, type_=int)

        class Level4(Level3):
            param4 = ParameterDescriptor(default=4, type_=int)

        class Level5(Level4):
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
    """Test inheritance with advanced parameter manager features."""

    def test_inheritance_with_parameter_locking(self):
        """Test parameter locking behavior in inheritance."""

        class BaseClass(ParameterizedBase):
            lockable_param = ParameterDescriptor(default=10, type_=int)

        class ChildClass(BaseClass):
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
        """Test parameter grouping behavior in inheritance."""

        class BaseClass(ParameterizedBase):
            base_param1 = ParameterDescriptor(default=1, type_=int)
            base_param2 = ParameterDescriptor(default=2, type_=int)

        class ChildClass(BaseClass):
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
        """Test change tracking behavior in inheritance."""

        class BaseClass(ParameterizedBase):
            tracked_param = ParameterDescriptor(default="base", type_=str)

        class ChildClass(BaseClass):
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
    pytest.main([__file__, "-v"])
