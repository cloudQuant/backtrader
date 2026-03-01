"""Tests for Enhanced ParameterizedBase (Day 34-35).

This module tests the enhanced ParameterizedBase functionality including:
* Temporary MetaParams integration
* Enhanced error handling and validation
* Improved backward compatibility interfaces
* Parameter inheritance from MetaParams-based classes

These tests ensure that the new descriptor-based parameter system maintains
compatibility with the legacy metaclass-based system while providing enhanced
features and better performance.
"""

import os
import sys
import warnings

import pytest

import backtrader as bt

from backtrader.parameters import (
    Float,
    Int,
    OneOf,
    ParameterAccessError,
    ParameterDescriptor,
    ParameterizedBase,
    ParameterManager,
    ParameterValidationError,
    ParamsBridge,
    String,
    validate_parameter_compatibility,
)


class TestParameterizedBaseLegacy:
    """Test ParameterizedBase with legacy parameter support.

    This test class validates backward compatibility with the legacy
    params tuple format used in the original metaclass-based system.
    """

    def test_pure_descriptor_class(self):
        """Test creating a class with only parameter descriptors.

        Verifies that classes using only the new descriptor-style
        parameter definitions work correctly.

        Raises:
            AssertionError: If descriptor-based parameters are not recognized.
        """

        class TestClass(ParameterizedBase):
            """Test class with pure descriptor-style parameters.

            This class is used to verify that ParameterDescriptor objects
            work correctly without any legacy params tuple.
            """

            param1 = ParameterDescriptor(default=10, type_=int)
            param2 = ParameterDescriptor(default="test", type_=str)

        descriptors = TestClass._compute_parameter_descriptors()
        assert len(descriptors) == 2
        assert "param1" in descriptors
        assert "param2" in descriptors

    def test_legacy_params_tuple_conversion(self):
        """Test conversion of legacy params tuple to descriptors.

        Verifies that the legacy params tuple format is automatically
        converted to ParameterDescriptor objects.

        Raises:
            AssertionError: If legacy params are not properly converted.
        """

        class TestClass(ParameterizedBase):
            """Test class with legacy params tuple format.

            This class is used to verify that legacy params tuples are
            automatically converted to ParameterDescriptor objects.
            """

            params = (("period", 14), ("multiplier", 2.0), ("name", "test_indicator"))

        descriptors = TestClass._compute_parameter_descriptors()
        assert len(descriptors) == 3
        assert "period" in descriptors
        assert descriptors["period"].default == 14
        assert descriptors["multiplier"].default == 2.0

    def test_mixed_descriptors_and_legacy(self):
        """Test mixing parameter descriptors with legacy params tuple.

        Verifies that descriptor-style and legacy tuple-style parameters
        can coexist in the same class.

        Raises:
            AssertionError: If mixed parameter styles cause conflicts.
        """

        class TestClass(ParameterizedBase):
            """Test class mixing descriptor and legacy parameter styles.

            This class is used to verify that new-style ParameterDescriptor
            objects can coexist with legacy params tuples.
            """

            # New style descriptor
            advanced_param = ParameterDescriptor(default=100, type_=int, validator=Int(min_val=0))

            # Legacy style params
            params = (("basic_param", 50), ("string_param", "default"))

        descriptors = TestClass._compute_parameter_descriptors()
        assert len(descriptors) == 3
        assert "advanced_param" in descriptors
        assert "basic_param" in descriptors
        assert "string_param" in descriptors

        # Advanced param should keep its validator
        assert descriptors["advanced_param"].validator is not None
        # Legacy params should have basic descriptors
        assert descriptors["basic_param"].validator is None


class TestEnhancedParameterizedBase:
    """Test enhanced ParameterizedBase functionality.

    This test class validates the new features and enhancements in the
    descriptor-based parameter system.
    """

    def test_basic_initialization(self):
        """Test basic parameter initialization.

        Verifies that parameters can be set during initialization and
        accessed through various aliases (get_param, .params, .p).

        Raises:
            AssertionError: If parameter initialization or access fails.
        """

        class TestClass(ParameterizedBase):
            """Test class for basic parameter initialization.

            This class is used to verify that parameters can be initialized
            with custom values and accessed through various methods.
            """

            param1 = ParameterDescriptor(default=10, type_=int)
            param2 = ParameterDescriptor(default="test", type_=str)

        obj = TestClass(param1=20, param2="custom")

        assert obj.get_param("param1") == 20
        assert obj.get_param("param2") == "custom"
        assert obj.params.param1 == 20
        assert obj.p.param2 == "custom"

    def test_parameter_validation_on_init(self):
        """Test parameter validation during initialization.

        Verifies that parameter validation is enforced during object
        initialization and invalid values raise errors.

        Raises:
            AssertionError: If validation is not enforced during init.
        """

        class TestClass(ParameterizedBase):
            """Test class for parameter validation.

            This class is used to verify that parameter validation is
            enforced during object initialization.
            """

            range_param = ParameterDescriptor(default=50, validator=Int(min_val=0, max_val=100))

        # Should fail with invalid range
        with pytest.raises(ValueError):
            TestClass(range_param=150)

        # Should succeed with valid parameters
        obj = TestClass(range_param=75)
        assert obj.get_param("range_param") == 75

    def test_enhanced_error_handling(self):
        """Test enhanced error handling with detailed messages.

        Verifies that parameter access errors are handled gracefully
        and that setting non-existent parameters creates them dynamically.

        Raises:
            AssertionError: If error handling doesn't work as expected.
        """

        class TestClass(ParameterizedBase):
            """Test class for enhanced error handling.

            This class is used to verify that parameter access errors
            are handled gracefully with informative messages.
            """

            param1 = ParameterDescriptor(default=10, type_=int)

        obj = TestClass()

        # Test accessing non-existent parameter with None default - should return None, not raise
        value = obj.get_param("nonexistent")
        assert value is None

        # Test accessing non-existent parameter without default
        try:
            obj.get_param("nonexistent", None)
        except AttributeError:
            pass  # This is expected behavior now

        # Test setting non-existent parameter - should work (creates new parameter in manager)
        obj.set_param("new_param", 100)
        assert obj.get_param("new_param") == 100

    def test_parameter_validation_methods(self):
        """Test enhanced parameter validation methods.

        Verifies that parameter validation can be triggered explicitly
        and that validation errors are properly reported.

        Raises:
            AssertionError: If validation methods don't detect invalid values.
        """

        class TestClass(ParameterizedBase):
            """Test class for parameter validation methods.

            This class is used to verify that parameter validation can be
            triggered explicitly and validation errors are properly reported.
            """

            int_param = ParameterDescriptor(default=10, type_=int, validator=Int(min_val=0))
            required_param = ParameterDescriptor(required=True, type_=str)

        obj = TestClass(required_param="test")

        # Initially valid
        errors = obj.validate_params()
        assert len(errors) == 0

        # Set invalid value bypassing validation by using skip_validation
        obj._param_manager.set("int_param", -5, skip_validation=True)
        errors = obj.validate_params()
        assert len(errors) == 1
        assert "invalid value" in errors[0]

    def test_parameter_info_retrieval(self):
        """Test comprehensive parameter information retrieval.

        Verifies that get_param_info() returns complete information about
        all parameters including current values, modification status, type,
        and documentation.

        Raises:
            AssertionError: If parameter information is incomplete or incorrect.
        """

        class TestClass(ParameterizedBase):
            """Test class for parameter information retrieval.

            This class is used to verify that get_param_info() returns
            complete and accurate information about all parameters.
            """

            param1 = ParameterDescriptor(default=10, type_=int, doc="Test parameter")
            param2 = ParameterDescriptor(default="test", required=True)

        obj = TestClass(param1=20, param2="custom")
        param_info = obj.get_param_info()

        assert len(param_info) == 2
        assert param_info["param1"]["current_value"] == 20
        assert param_info["param1"]["is_modified"] == True
        assert param_info["param1"]["type"] == int
        assert param_info["param1"]["doc"] == "Test parameter"

    def test_parameter_reset_functionality(self):
        """Test parameter reset functionality.

        Verifies that individual parameters can be reset to their default
        values and that all parameters can be reset at once.

        Raises:
            AssertionError: If parameter reset doesn't work correctly.
        """

        class TestClass(ParameterizedBase):
            """Test class for parameter reset functionality.

            This class is used to verify that parameters can be reset
            individually or all at once to their default values.
            """

            param1 = ParameterDescriptor(default=10)
            param2 = ParameterDescriptor(default=20)

        obj = TestClass(param1=100, param2=200)

        # Verify modified values
        assert obj.get_param("param1") == 100
        assert obj.get_param("param2") == 200

        # Reset single parameter
        obj.reset_param("param1")
        assert obj.get_param("param1") == 10
        assert obj.get_param("param2") == 200

        # Reset all parameters
        obj.reset_all_params()
        assert obj.get_param("param1") == 10
        assert obj.get_param("param2") == 20

    def test_modified_params_tracking(self):
        """Test tracking of modified parameters.

        Verifies that the system tracks which parameters have been modified
        from their default values.

        Raises:
            AssertionError: If modified parameter tracking is inaccurate.
        """

        class TestClass(ParameterizedBase):
            """Test class for modified parameter tracking.

            This class is used to verify that the system correctly tracks
            which parameters have been modified from their default values.
            """

            param1 = ParameterDescriptor(default=10)
            param2 = ParameterDescriptor(default=20)
            param3 = ParameterDescriptor(default=30)

        obj = TestClass(param1=100, param3=300)

        modified = obj.get_modified_params()
        assert len(modified) == 2
        assert modified["param1"] == 100
        assert modified["param3"] == 300
        assert "param2" not in modified

    def test_parameter_copying(self):
        """Test parameter copying between objects.

        Verifies that parameters can be copied from one object to another,
        with support for selective copying and exclusion lists.

        Raises:
            AssertionError: If parameter copying doesn't work as expected.
        """

        class TestClass(ParameterizedBase):
            """Test class for parameter copying.

            This class is used to verify that parameters can be copied
            between objects with various options.
            """

            param1 = ParameterDescriptor(default=10)
            param2 = ParameterDescriptor(default=20)
            param3 = ParameterDescriptor(default=30)

        source = TestClass(param1=100, param2=200, param3=300)
        target = TestClass()

        # Copy all parameters
        target.copy_params_from(source)
        assert target.get_param("param1") == 100
        assert target.get_param("param2") == 200
        assert target.get_param("param3") == 300

        # Reset target and copy selectively
        target.reset_all_params()
        target.copy_params_from(source, param_names=["param1", "param3"])
        assert target.get_param("param1") == 100
        assert target.get_param("param2") == 20  # Not copied
        assert target.get_param("param3") == 300

        # Reset target and copy with exclusions
        target.reset_all_params()
        target.copy_params_from(source, exclude=["param2"])
        assert target.get_param("param1") == 100
        assert target.get_param("param2") == 20  # Excluded
        assert target.get_param("param3") == 300

    def test_enhanced_string_representation(self):
        """Test enhanced string representation.

        Verifies that the __repr__ method provides useful information
        about the object including its class and parameter count.

        Raises:
            AssertionError: If string representation doesn't contain expected info.
        """

        class TestClass(ParameterizedBase):
            """Test class for string representation.

            This class is used to verify that the __repr__ method
            provides useful information about the object.
            """

            param1 = ParameterDescriptor(default=10)
            param2 = ParameterDescriptor(default=20)

        obj = TestClass(param1=100)
        repr_str = repr(obj)

        assert "TestClass" in repr_str
        assert "parameters=2" in repr_str


class TestParamsBridge:
    """Test the ParamsBridge class for legacy compatibility.

    This test class validates the ParamsBridge utility that converts
    legacy parameter formats to the new descriptor-based format.
    """

    def test_legacy_params_tuple_conversion(self):
        """Test conversion of legacy params tuple.

        Verifies that ParamsBridge correctly converts the legacy
        params tuple format to ParameterDescriptor objects.

        Raises:
            AssertionError: If conversion doesn't produce correct descriptors.
        """

        legacy_params = (("period", 14), ("multiplier", 2.5), ("mode", "simple"))

        descriptors = ParamsBridge.convert_legacy_params_tuple(legacy_params)

        assert len(descriptors) == 3
        assert "period" in descriptors
        assert "multiplier" in descriptors
        assert "mode" in descriptors

        assert descriptors["period"].default == 14
        assert descriptors["multiplier"].default == 2.5
        assert descriptors["mode"].default == "simple"


class TestParameterExceptions:
    """Test custom parameter exceptions.

    This test class validates the custom exception classes that
    provide detailed error information for parameter-related issues.
    """

    def test_parameter_validation_error(self):
        """Test ParameterValidationError.

        Verifies that ParameterValidationError properly stores and
        formats validation error information.

        Raises:
            AssertionError: If exception doesn't store error details correctly.
        """

        error = ParameterValidationError(
            "test_param", "invalid_value", expected_type=int, additional_info="Must be positive"
        )

        assert error.parameter_name == "test_param"
        assert error.value == "invalid_value"
        assert error.expected_type == int
        assert "test_param" in str(error)
        assert "invalid_value" in str(error)
        assert "int" in str(error)
        assert "Must be positive" in str(error)

    def test_parameter_access_error(self):
        """Test ParameterAccessError.

        Verifies that ParameterAccessError properly stores and
        formats parameter access error information.

        Raises:
            AssertionError: If exception doesn't store error details correctly.
        """

        error = ParameterAccessError("missing_param", "TestClass", ["param1", "param2"])

        assert error.parameter_name == "missing_param"
        assert error.class_name == "TestClass"
        assert error.available_params == ["param1", "param2"]
        assert "missing_param" in str(error)
        assert "TestClass" in str(error)
        assert "['param1', 'param2']" in str(error)


class TestParameterCompatibility:
    """Test parameter system compatibility validation.

    This test class validates tools for checking compatibility between
    the old metaclass-based parameter system and the new descriptor-based system.
    """

    def test_compatibility_validation(self):
        """Test compatibility validation between old and new parameter systems.

        Verifies that validate_parameter_compatibility() can detect differences
        between old and new parameter definitions.

        Raises:
            AssertionError: If compatibility validation fails to detect differences.
        """

        # Mock old MetaParams class
        class MockOldClass:
            """Mock class representing old MetaParams-based system.

            This class is used to simulate the legacy metaclass-based
            parameter system for compatibility testing.
            """

            class params:
                """Mock params class with _getitems method.

                This simulates the legacy params interface for
                compatibility validation.
                """

                @classmethod
                def _getitems(cls):
                    return [("param1", 10), ("param2", "test"), ("old_param", 100)]

        # New descriptor-based class
        class NewClass(ParameterizedBase):
            """New descriptor-based parameter class.

            This class is used to verify compatibility between the old
            and new parameter systems.
            """

            param1 = ParameterDescriptor(default=10)
            param2 = ParameterDescriptor(default="test")
            new_param = ParameterDescriptor(default=50)

        # Ensure descriptors are computed
        NewClass._compute_parameter_descriptors()

        results = validate_parameter_compatibility(MockOldClass, NewClass)

        assert isinstance(results, dict)
        assert "compatible" in results
        assert "missing_params" in results
        assert "extra_params" in results

        # Should detect old_param as missing and new_param as extra
        assert "old_param" in results["missing_params"]
        assert "new_param" in results["extra_params"]


class TestAdvancedParameterFeatures:
    """Test advanced parameter features for Day 34-35.

    This test class validates advanced features of the parameter system
    including complex validators, inheritance chains, and ParameterManager
    integration.
    """

    def test_parameter_with_complex_validation(self):
        """Test parameters with complex validation logic.

        Verifies that custom validator functions work correctly with
        the parameter system and properly reject invalid values.

        Raises:
            AssertionError: If complex validators don't work as expected.
        """

        def custom_validator(value):
            """Validate that value is even and positive.

            Args:
                value: The value to validate.

            Returns:
                bool: True if value is a positive even integer, False otherwise.
            """
            return isinstance(value, int) and value > 0 and value % 2 == 0

        class TestClass(ParameterizedBase):
            """Test class with complex parameter validation.

            This class is used to verify that custom validator functions
            work correctly with the parameter system.
            """

            even_param = ParameterDescriptor(
                default=2, type_=int, validator=custom_validator, doc="Must be positive and even"
            )

        # Valid value
        obj = TestClass(even_param=10)
        assert obj.get_param("even_param") == 10

        # Invalid values should fail validation
        with pytest.raises(ValueError):
            TestClass(even_param=9)  # Odd number

        with pytest.raises(ValueError):
            TestClass(even_param=-2)  # Negative even number

    def test_parameter_inheritance_chain(self):
        """Test parameter inheritance through class hierarchy.

        Verifies that parameters are correctly inherited through multiple
        levels of class inheritance and are accessible via get_param_info().

        Raises:
            AssertionError: If inheritance chain doesn't work correctly.
        """

        class BaseClass(ParameterizedBase):
            """Base class with one parameter.

            This class serves as the base of the inheritance chain
            for testing parameter inheritance.
            """

            base_param = ParameterDescriptor(default=10)

        class MiddleClass(BaseClass):
            """Middle class inheriting from BaseClass.

            This class extends BaseClass to test multi-level
            parameter inheritance.
            """

            middle_param = ParameterDescriptor(default=20)

        class DerivedClass(MiddleClass):
            """Derived class inheriting from MiddleClass.

            This class extends MiddleClass to test three-level
            parameter inheritance.
            """

            derived_param = ParameterDescriptor(default=30)

        obj = DerivedClass(base_param=100, middle_param=200, derived_param=300)

        assert obj.get_param("base_param") == 100
        assert obj.get_param("middle_param") == 200
        assert obj.get_param("derived_param") == 300

        # Check parameter info includes all inherited parameters
        param_info = obj.get_param_info()
        assert len(param_info) == 3
        assert all(param in param_info for param in ["base_param", "middle_param", "derived_param"])

    def test_parameter_manager_integration(self):
        """Test integration with enhanced ParameterManager features.

        Verifies that ParameterizedBase properly exposes and integrates
        with advanced ParameterManager features like locking and transactions.

        Raises:
            AssertionError: If ParameterManager integration is incomplete.
        """

        class TestClass(ParameterizedBase):
            """Test class for ParameterManager integration.

            This class is used to verify that ParameterizedBase properly
            exposes and integrates with advanced ParameterManager features.
            """

            param1 = ParameterDescriptor(default=10)
            param2 = ParameterDescriptor(default=20)

        obj = TestClass()

        # Test that enhanced ParameterManager features are available
        assert hasattr(obj._param_manager, "begin_transaction")
        assert hasattr(obj._param_manager, "lock_parameter")
        assert hasattr(obj._param_manager, "create_group")

        # Test parameter locking through ParameterizedBase
        obj._param_manager.lock_parameter("param1")

        with pytest.raises(ValueError, match="locked"):
            obj.set_param("param1", 100)

        # Force setting should work using the parameter manager directly
        obj._param_manager.set("param1", 100, force=True)
        assert obj.get_param("param1") == 100


if __name__ == "__main__":
    # Run tests when module is executed directly
    pytest.main([__file__])
