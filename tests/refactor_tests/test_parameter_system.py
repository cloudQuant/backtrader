
import backtrader as bt

"""
Tests for the new Parameter System

This module tests the ParameterDescriptor implementation and related
functionality to ensure all requirements from Day 29-31 are met.
"""

import os
import sys

import pytest

from backtrader.parameters import (
    Float,
    Int,
    OneOf,
    ParameterAccessor,
    ParameterDescriptor,
    ParameterizedBase,
    ParameterManager,
    String,
)


class TestParameterDescriptor:
    """Test the ParameterDescriptor class functionality."""

    def test_basic_descriptor_functionality(self):
        """Test basic descriptor get/set operations."""

        # Create a simple parameterized class
        class TestClass(ParameterizedBase):
            period = ParameterDescriptor(default=14, type_=int, doc="Period parameter")
            factor = ParameterDescriptor(default=1.0, type_=float)

        # Test class creation
        obj = TestClass()

        # Test default values
        assert obj.period == 14
        assert obj.factor == 1.0

        # Test setting values
        obj.period = 20
        obj.factor = 2.5
        assert obj.period == 20
        assert obj.factor == 2.5

        # Test parameter access through params
        assert obj.params.period == 20
        assert obj.p.factor == 2.5

    def test_type_checking_mechanism(self):
        """Test automatic type checking and conversion."""

        class TestClass(ParameterizedBase):
            int_param = ParameterDescriptor(default=10, type_=int)
            float_param = ParameterDescriptor(default=1.0, type_=float)
            str_param = ParameterDescriptor(default="test", type_=str)

        obj = TestClass()

        # Test automatic type conversion
        obj.int_param = "15"  # String should convert to int
        assert obj.int_param == 15
        assert isinstance(obj.int_param, int)

        obj.float_param = "2.5"  # String should convert to float
        assert obj.float_param == 2.5
        assert isinstance(obj.float_param, float)

        # Test type validation failure
        with pytest.raises(TypeError):
            obj.int_param = "invalid_int"

    def test_value_validation_mechanism(self):
        """Test custom value validation."""

        class TestClass(ParameterizedBase):
            positive_int = ParameterDescriptor(default=1, type_=int, validator=lambda x: x > 0)
            choice_param = ParameterDescriptor(default="A", validator=OneOf("A", "B", "C"))
            range_float = ParameterDescriptor(
                default=0.5, type_=float, validator=Float(min_val=0.0, max_val=1.0)
            )

        obj = TestClass()

        # Test valid values
        obj.positive_int = 5
        obj.choice_param = "B"
        obj.range_float = 0.8

        assert obj.positive_int == 5
        assert obj.choice_param == "B"
        assert obj.range_float == 0.8

        # Test validation failures
        with pytest.raises(ValueError):
            obj.positive_int = -1

        with pytest.raises(ValueError):
            obj.choice_param = "D"

        with pytest.raises(ValueError):
            obj.range_float = 1.5

    def test_python36_set_name_support(self):
        """Test Python 3.6+ __set_name__ functionality."""

        class TestClass(ParameterizedBase):
            my_param = ParameterDescriptor(default=42)

        # Ensure descriptors are computed
        descriptors = TestClass._compute_parameter_descriptors()

        # Verify that __set_name__ was called and name was set correctly
        assert descriptors["my_param"].name == "my_param"
        assert descriptors["my_param"]._attr_name == "_param_my_param"

        # Test that descriptor is properly registered
        obj = TestClass()
        assert obj.my_param == 42


class TestParameterManager:
    """Test the ParameterManager class functionality."""

    def test_parameter_storage_and_retrieval(self):
        """Test basic parameter storage and retrieval."""
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default="test", name="param2"),
        }

        manager = ParameterManager(descriptors)

        # Test default values
        assert manager.get("param1") == 10
        assert manager.get("param2") == "test"

        # Test setting values
        manager.set("param1", 20)
        manager.set("param2", "new_value")

        assert manager.get("param1") == 20
        assert manager.get("param2") == "new_value"

    def test_parameter_inheritance(self):
        """Test parameter inheritance between managers."""
        descriptors1 = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
        }

        descriptors2 = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param3": ParameterDescriptor(default=30, name="param3"),
        }

        parent = ParameterManager(descriptors1)
        parent.set("param1", 100)
        parent.set("param2", 200)

        child = ParameterManager(descriptors2)
        child.inherit_from(parent)

        # Child should inherit param1 from parent
        assert child.get("param1") == 100
        # Child shouldn't inherit param2 (not in child's descriptors)
        # but get() will return the default value for unknown parameters
        assert child.get("param2", None) is None
        # Child should have its own param3
        assert child.get("param3") == 30

    def test_batch_operations(self):
        """Test batch parameter operations."""
        descriptors = {
            "param1": ParameterDescriptor(default=10, name="param1"),
            "param2": ParameterDescriptor(default=20, name="param2"),
            "param3": ParameterDescriptor(default=30, name="param3"),
        }

        manager = ParameterManager(descriptors)

        # Test batch update with dictionary
        manager.update({"param1": 100, "param2": 200})
        assert manager.get("param1") == 100
        assert manager.get("param2") == 200
        assert manager.get("param3") == 30  # Unchanged

        # Test to_dict
        all_params = manager.to_dict()
        assert all_params["param1"] == 100
        assert all_params["param2"] == 200
        assert all_params["param3"] == 30


class TestParameterizedBase:
    """Test the ParameterizedBase class functionality."""

    def test_class_creation_with_parameters(self):
        """Test creating parameterized classes."""

        class MyClass(ParameterizedBase):
            period = ParameterDescriptor(default=14, type_=int)
            factor = ParameterDescriptor(default=1.0, type_=float)
            name = ParameterDescriptor(default="test", type_=str)

        # Test default initialization
        obj1 = MyClass()
        assert obj1.period == 14
        assert obj1.factor == 1.0
        assert obj1.name == "test"

        # Test initialization with parameters
        obj2 = MyClass(period=21, factor=2.0, name="custom")
        assert obj2.period == 21
        assert obj2.factor == 2.0
        assert obj2.name == "custom"

    def test_parameter_inheritance_in_classes(self):
        """Test parameter inheritance between classes."""

        class BaseClass(ParameterizedBase):
            base_param = ParameterDescriptor(default=100, type_=int)
            shared_param = ParameterDescriptor(default="base", type_=str)

        class DerivedClass(BaseClass):
            derived_param = ParameterDescriptor(default=200, type_=int)
            shared_param = ParameterDescriptor(default="derived", type_=str)  # Override

        obj = DerivedClass()

        # Should have base parameter
        assert obj.base_param == 100
        # Should have derived parameter
        assert obj.derived_param == 200
        # Should use overridden value
        assert obj.shared_param == "derived"

    def test_backward_compatibility_interface(self):
        """Test backward compatibility with old parameter interface."""

        class TestClass(ParameterizedBase):
            period = ParameterDescriptor(default=14, type_=int)
            factor = ParameterDescriptor(default=1.0, type_=float)

        obj = TestClass(period=21, factor=2.5)

        # Test obj.params interface
        assert obj.params.period == 21
        assert obj.params.factor == 2.5

        # Test obj.p interface (short alias)
        assert obj.p.period == 21
        assert obj.p.factor == 2.5

        # Test setting through params
        obj.params.period = 30
        obj.p.factor = 3.0

        assert obj.period == 30
        assert obj.factor == 3.0

        # Test backward compatibility methods
        items = list(obj.params._getitems())
        assert len(items) == 2
        assert ("period", 30) in items
        assert ("factor", 3.0) in items

        keys = obj.params._getkeys()
        assert "period" in keys
        assert "factor" in keys

        values = obj.params._getvalues()
        assert 30 in values
        assert 3.0 in values


class TestValidatorHelpers:
    """Test the validator helper functions."""

    def test_int_validator(self):
        """Test Int validator function."""
        # Basic int validation
        validator = Int()
        assert validator(10) == True
        assert validator(10.5) == False
        assert validator("10") == False

        # Range validation
        range_validator = Int(min_val=0, max_val=100)
        assert range_validator(50) == True
        assert range_validator(-1) == False
        assert range_validator(101) == False

    def test_float_validator(self):
        """Test Float validator function."""
        # Basic float validation
        validator = Float()
        assert validator(10.5) == True
        assert validator(10) == True  # int should be accepted
        assert validator("10.5") == False

        # Range validation
        range_validator = Float(min_val=0.0, max_val=1.0)
        assert range_validator(0.5) == True
        assert range_validator(-0.1) == False
        assert range_validator(1.1) == False

    def test_oneof_validator(self):
        """Test OneOf validator function."""
        validator = OneOf("A", "B", "C")
        assert validator("A") == True
        assert validator("B") == True
        assert validator("D") == False

        # Test with numbers
        num_validator = OneOf(1, 2, 3)
        assert num_validator(2) == True
        assert num_validator(4) == False

    def test_string_validator(self):
        """Test String validator function."""
        # Basic string validation
        validator = String()
        assert validator("test") == True
        assert validator(123) == False

        # Length validation
        length_validator = String(min_length=3, max_length=10)
        assert length_validator("hello") == True
        assert length_validator("hi") == False  # Too short
        assert length_validator("this_is_too_long") == False  # Too long


class TestComplexScenarios:
    """Test complex usage scenarios."""

    def test_multiple_inheritance_with_parameters(self):
        """Test multiple inheritance scenarios."""

        class Mixin1(ParameterizedBase):
            param1 = ParameterDescriptor(default=1, type_=int)

        class Mixin2(ParameterizedBase):
            param2 = ParameterDescriptor(default=2, type_=int)

        class Combined(Mixin1, Mixin2):
            param3 = ParameterDescriptor(default=3, type_=int)

        obj = Combined()
        assert obj.param1 == 1
        assert obj.param2 == 2
        assert obj.param3 == 3

    def test_parameter_validation_on_initialization(self):
        """Test that parameters are validated during initialization."""

        class TestClass(ParameterizedBase):
            positive_param = ParameterDescriptor(default=1, type_=int, validator=lambda x: x > 0)

        # Valid initialization
        obj1 = TestClass(positive_param=5)
        assert obj1.positive_param == 5

        # Invalid initialization should raise error
        with pytest.raises(ValueError):
            obj2 = TestClass(positive_param=-1)

    def test_parameter_info_and_introspection(self):
        """Test parameter introspection capabilities."""

        class TestClass(ParameterizedBase):
            int_param = ParameterDescriptor(
                default=10, type_=int, validator=Int(min_val=0), doc="An integer parameter"
            )
            str_param = ParameterDescriptor(default="test", type_=str, doc="A string parameter")

        obj = TestClass()
        param_info = obj.get_param_info()

        assert "int_param" in param_info
        assert "str_param" in param_info

        int_info = param_info["int_param"]
        assert int_info["name"] == "int_param"
        assert int_info["type"] == int
        assert int_info["default_value"] == 10
        assert int_info["has_validator"] == True
        assert int_info["doc"] == "An integer parameter"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__])
