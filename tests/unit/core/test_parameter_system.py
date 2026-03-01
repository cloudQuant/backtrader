"""Tests for the new Parameter System.

This module tests the ParameterDescriptor implementation and related
functionality to ensure all requirements from Day 29-31 are met.
"""

import os
import sys

import backtrader as bt
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
    """Test suite for the ParameterDescriptor class functionality.

    This test class verifies that ParameterDescriptor correctly implements:
    - Basic descriptor get/set operations with type checking
    - Automatic type conversion and validation
    - Custom value validation using validator functions
    - Python 3.6+ __set_name__ protocol support
    - Integration with ParameterizedBase class

    The ParameterDescriptor is the core component of the new parameter system
    that provides declarative parameter definition with type safety and validation.
    """

    def test_basic_descriptor_functionality(self):
        """Test basic descriptor get/set operations.

        This test verifies that:
        1. Parameters are initialized with their default values
        2. Parameter values can be read and modified
        3. Parameter values are accessible through direct attribute access
        4. Parameter values are accessible through params and p accessors
        5. All access methods return consistent values

        Raises:
            AssertionError: If any of the basic descriptor operations fail.
        """

        # Create a simple parameterized class
        class TestClass(ParameterizedBase):
            """Test helper class for basic descriptor functionality.

            Attributes:
                period: An integer parameter representing a time period (default: 14).
                factor: A float parameter representing a scaling factor (default: 1.0).
            """
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
        """Test automatic type checking and conversion.

        This test verifies that:
        1. Parameters automatically convert values to their declared types
        2. String representations of numbers are converted to numeric types
        3. Converted values maintain their correct type
        4. Invalid type conversions raise TypeError

        Raises:
            AssertionError: If type checking or conversion fails.
        """

        class TestClass(ParameterizedBase):
            """Test helper class for type checking mechanism.

            Attributes:
                int_param: An integer parameter for testing type conversion.
                float_param: A float parameter for testing type conversion.
                str_param: A string parameter for testing type conversion.
            """
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
        """Test custom value validation.

        This test verifies that:
        1. Custom validator functions work correctly
        2. OneOf validator restricts values to specified choices
        3. Float validator enforces min/max range constraints
        4. Invalid values raise ValueError
        5. Valid values are accepted and stored

        Raises:
            AssertionError: If value validation logic fails.
        """

        class TestClass(ParameterizedBase):
            """Test helper class for value validation mechanism.

            Attributes:
                positive_int: A positive integer parameter with custom validator.
                choice_param: A string parameter restricted to specific choices.
                range_float: A float parameter with min/max range validation.
            """
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
        """Test Python 3.6+ __set_name__ functionality.

        This test verifies that:
        1. The __set_name__ protocol is properly implemented
        2. Descriptor names are correctly set when defined in a class
        3. The internal attribute name uses the _param_ prefix convention
        4. Descriptors are properly computed and registered

        The __set_name__ protocol is used in Python 3.6+ to automatically
        set descriptor names when they are assigned as class attributes.

        Raises:
            AssertionError: If __set_name__ functionality fails.
        """

        class TestClass(ParameterizedBase):
            """Test helper class for __set_name__ protocol validation.

            Attributes:
                my_param: A parameter to test automatic name assignment.
            """
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
    """Test suite for the ParameterManager class functionality.

    This test class verifies that ParameterManager correctly implements:
    - Parameter storage and retrieval with default values
    - Parameter inheritance between parent and child managers
    - Batch operations for updating multiple parameters
    - Dictionary export functionality via to_dict()

    The ParameterManager is responsible for storing parameter values and
    managing the inheritance hierarchy between classes in the parameter system.
    """

    def test_parameter_storage_and_retrieval(self):
        """Test basic parameter storage and retrieval.

        This test verifies that:
        1. Parameters are initialized with their default values from descriptors
        2. Parameter values can be retrieved using get() method
        3. Parameter values can be updated using set() method
        4. Updated values persist correctly

        Raises:
            AssertionError: If parameter storage or retrieval fails.
        """
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
        """Test parameter inheritance between managers.

        This test verifies that:
        1. Child managers can inherit values from parent managers
        2. Only parameters defined in child's descriptors are inherited
        3. Parameters not in child's descriptors are not inherited
        4. Child's own parameters remain independent

        Raises:
            AssertionError: If parameter inheritance logic fails.
        """
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
        """Test batch parameter operations.

        This test verifies that:
        1. Multiple parameters can be updated using update() with a dictionary
        2. Parameters not included in update retain their values
        3. All parameters can be exported using to_dict()
        4. Exported dictionary contains all current parameter values

        Raises:
            AssertionError: If batch operations fail.
        """
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
    """Test suite for the ParameterizedBase class functionality.

    This test class verifies that ParameterizedBase correctly implements:
    - Creation of parameterized classes with various parameter types
    - Parameter inheritance between base and derived classes
    - Backward compatibility with legacy parameter access patterns
    - Support for params and p accessors (obj.params, obj.p)

    ParameterizedBase is the foundation class that provides parameter
    management capabilities to all backtrader components including
    strategies, indicators, analyzers, and observers.
    """

    def test_class_creation_with_parameters(self):
        """Test creating parameterized classes.

        This test verifies that:
        1. Parameterized classes can be created with various parameter types
        2. Default values are correctly assigned
        3. Parameters can be overridden at initialization time
        4. Different parameter types (int, float, str) are handled correctly

        Raises:
            AssertionError: If class creation or parameter initialization fails.
        """

        class MyClass(ParameterizedBase):
            """Test helper class for parameterized class creation.

            Attributes:
                period: An integer period parameter (default: 14).
                factor: A float scaling factor parameter (default: 1.0).
                name: A string name parameter (default: "test").
            """
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
        """Test parameter inheritance between classes.

        This test verifies that:
        1. Derived classes inherit parameters from base classes
        2. Derived classes can add new parameters
        3. Derived classes can override base class parameters
        4. Overridden parameters use derived class defaults

        Raises:
            AssertionError: If parameter inheritance between classes fails.
        """

        class BaseClass(ParameterizedBase):
            """Base test class for inheritance testing.

            Attributes:
                base_param: An integer parameter unique to the base class.
                shared_param: A string parameter that will be overridden in derived class.
            """
            base_param = ParameterDescriptor(default=100, type_=int)
            shared_param = ParameterDescriptor(default="base", type_=str)

        class DerivedClass(BaseClass):
            """Derived test class for inheritance testing.

            Attributes:
                derived_param: An integer parameter unique to the derived class.
                shared_param: A string parameter overriding the base class value.
            """
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
        """Test backward compatibility with old parameter interface.

        This test verifies that:
        1. obj.params interface works for accessing parameters
        2. obj.p shorthand interface works for accessing parameters
        3. Parameters can be modified through params/p interfaces
        4. Modifications are reflected in direct attribute access
        5. Legacy methods _getitems(), _getkeys(), _getvalues() work correctly

        These interfaces ensure compatibility with existing backtrader code
        that uses the old parameter system.

        Raises:
            AssertionError: If backward compatibility interfaces fail.
        """

        class TestClass(ParameterizedBase):
            """Test helper class for backward compatibility interface testing.

            Attributes:
                period: An integer period parameter (default: 14).
                factor: A float scaling factor parameter (default: 1.0).
            """
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
    """Test suite for the validator helper functions.

    This test class verifies that validator helpers correctly implement:
    - Int validator for integer type and range validation
    - Float validator for float type and range validation
    - OneOf validator for restricting values to a set of choices
    - String validator for string type and length validation

    Validator helpers are callable objects that validate parameter values
    and raise ValueError if validation fails. They can be used as
    validator arguments when defining ParameterDescriptor instances.
    """

    def test_int_validator(self):
        """Test Int validator function.

        This test verifies that:
        1. Int validator accepts integer values and returns True
        2. Int validator rejects non-integer values and returns False
        3. Int validator with min_val/max_val enforces range constraints
        4. Values outside the specified range are rejected

        Raises:
            AssertionError: If Int validator logic fails.
        """
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
        """Test Float validator function.

        This test verifies that:
        1. Float validator accepts float values and returns True
        2. Float validator accepts integer values (as valid floats) and returns True
        3. Float validator rejects non-numeric values and returns False
        4. Float validator with min_val/max_val enforces range constraints

        Raises:
            AssertionError: If Float validator logic fails.
        """
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
        """Test OneOf validator function.

        This test verifies that:
        1. OneOf validator accepts values from the allowed set
        2. OneOf validator rejects values not in the allowed set
        3. OneOf works with string choices
        4. OneOf works with numeric choices

        Raises:
            AssertionError: If OneOf validator logic fails.
        """
        validator = OneOf("A", "B", "C")
        assert validator("A") == True
        assert validator("B") == True
        assert validator("D") == False

        # Test with numbers
        num_validator = OneOf(1, 2, 3)
        assert num_validator(2) == True
        assert num_validator(4) == False

    def test_string_validator(self):
        """Test String validator function.

        This test verifies that:
        1. String validator accepts string values and returns True
        2. String validator rejects non-string values and returns False
        3. String validator with min_length/max_length enforces length constraints
        4. Values outside the specified length range are rejected

        Raises:
            AssertionError: If String validator logic fails.
        """
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
    """Test suite for complex usage scenarios.

    This test class validates that the parameter system handles:
    - Multiple inheritance with parameters from multiple parent classes
    - Parameter validation during object initialization
    - Parameter introspection and metadata extraction
    - Edge cases and advanced usage patterns

    These tests ensure the parameter system is robust enough to handle
    real-world usage scenarios in backtrader applications.
    """

    def test_multiple_inheritance_with_parameters(self):
        """Test multiple inheritance scenarios.

        This test verifies that:
        1. Multiple inheritance from ParameterizedBase classes works correctly
        2. Parameters from all parent classes are inherited
        3. Child class parameters are properly integrated
        4. Method Resolution Order (MRO) is maintained

        Raises:
            AssertionError: If multiple inheritance with parameters fails.
        """

        class Mixin1(ParameterizedBase):
            """First mixin class for multiple inheritance testing.

            Attributes:
                param1: An integer parameter from the first mixin.
            """
            param1 = ParameterDescriptor(default=1, type_=int)

        class Mixin2(ParameterizedBase):
            """Second mixin class for multiple inheritance testing.

            Attributes:
                param2: An integer parameter from the second mixin.
            """
            param2 = ParameterDescriptor(default=2, type_=int)

        class Combined(Mixin1, Mixin2):
            """Combined class inheriting from multiple mixins.

            This class tests that parameters from all parent classes are
            properly inherited and integrated.

            Attributes:
                param3: An integer parameter unique to the combined class.
            """
            param3 = ParameterDescriptor(default=3, type_=int)

        obj = Combined()
        assert obj.param1 == 1
        assert obj.param2 == 2
        assert obj.param3 == 3

    def test_parameter_validation_on_initialization(self):
        """Test that parameters are validated during initialization.

        This test verifies that:
        1. Valid parameters passed during initialization are accepted
        2. Invalid parameters raise ValueError during initialization
        3. Validation occurs before the object is fully constructed
        4. Custom validators are applied during initialization

        Raises:
            AssertionError: If parameter validation during initialization fails.
        """

        class TestClass(ParameterizedBase):
            """Test helper class for initialization validation testing.

            Attributes:
                positive_param: A positive integer parameter with validation.
            """
            positive_param = ParameterDescriptor(default=1, type_=int, validator=lambda x: x > 0)

        # Valid initialization
        obj1 = TestClass(positive_param=5)
        assert obj1.positive_param == 5

        # Invalid initialization should raise error
        with pytest.raises(ValueError):
            obj2 = TestClass(positive_param=-1)

    def test_parameter_info_and_introspection(self):
        """Test parameter introspection capabilities.

        This test verifies that:
        1. get_param_info() returns a dictionary of all parameter metadata
        2. Parameter info includes name, type, default value, and validator status
        3. Parameter info includes documentation strings
        4. All parameters defined in the class are included in the info

        The get_param_info() method is used for documentation generation,
        UI display, and runtime introspection of parameter configurations.

        Raises:
            AssertionError: If parameter introspection fails.
        """

        class TestClass(ParameterizedBase):
            """Test helper class for parameter introspection testing.

            Attributes:
                int_param: An integer parameter with range validation and documentation.
                str_param: A string parameter with documentation.
            """
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
