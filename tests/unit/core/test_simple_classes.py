"""Tests for Simple Classes Refactoring (Day 36-38).

This module tests the refactored simple classes including:
- Timer class refactoring
- Sizer class refactoring
- Filter related class refactoring

All classes have been migrated from MetaParams to ParameterizedBase system.
"""

import os
import sys
from datetime import datetime, timedelta

import pytest

import backtrader as bt
from backtrader.filters.session import SessionFiller, SessionFilter, SessionFilterSimple
from backtrader.flt import Filter
from backtrader.parameters import ParameterDescriptor, ParameterizedBase
from backtrader.sizer import Sizer
from backtrader.sizers.fixedsize import FixedReverser, FixedSize, FixedSizeTarget
from backtrader.sizers.percents_sizer import (
    AllInSizer,
    AllInSizerInt,
    PercentSizer,
    PercentSizerInt,
)


class TestSizerRefactoring:
    """Test suite for refactored Sizer classes.

    This test class validates that all Sizer classes have been successfully
    migrated from the MetaParams metaclass system to the ParameterizedBase
    mixin pattern. It tests parameter access, modification, validation, and
    inheritance across various sizer implementations.

    Tested sizers include:
    - FixedSize: Fixed stake size sizer
    - PercentSizer: Percentage-based sizer
    - AllInSizer: 100% allocation sizer
    - PercentSizerInt: Integer-returning percent sizer
    - AllInSizerInt: Integer-returning 100% sizer
    - FixedReverser: Position reversing sizer
    - FixedSizeTarget: Target position sizer
    """

    def test_fixed_size_sizer(self):
        """Test FixedSize sizer with new parameter system.

        Validates that:
        - Parameters can be accessed via get_param()
        - Parameters can be modified via set_param()
        - Validation rejects invalid values (negative stakes)

        Raises:
            AssertionError: If parameter operations fail unexpectedly
            ValueError: Expected when setting invalid stake value
        """
        # Create FixedSize sizer with custom parameters
        sizer = FixedSize(stake=10, tranches=2)

        # Test parameter access - verify initialization values
        assert sizer.get_param("stake") == 10
        assert sizer.get_param("tranches") == 2

        # Test parameter modification - verify parameters can be updated
        sizer.set_param("stake", 20)
        assert sizer.get_param("stake") == 20

        # Test parameter validation - negative stakes should be rejected
        with pytest.raises(ValueError):
            sizer.set_param("stake", -5)  # Should fail validation

    def test_percent_sizer(self):
        """Test PercentSizer with new parameter system.

        Validates that:
        - PercentSizer parameters are accessible
        - Validation rejects percentages > 100%
        - Validation rejects negative percentages

        Raises:
            AssertionError: If parameter operations fail unexpectedly
            ValueError: Expected when setting invalid percent values
        """
        # Create PercentSizer with custom parameters
        sizer = PercentSizer(percents=30, retint=True)

        # Test parameter access - verify initialization values
        assert sizer.get_param("percents") == 30
        assert sizer.get_param("retint") == True

        # Test parameter validation - percentages must be between 0 and 100
        with pytest.raises(ValueError):
            sizer.set_param("percents", 150)  # Should fail validation (>100)

        with pytest.raises(ValueError):
            sizer.set_param("percents", -10)  # Should fail validation (<0)

    def test_all_in_sizer(self):
        """Test AllInSizer inheritance from PercentSizer.

        Validates that AllInSizer properly inherits from PercentSizer
        with the default 100% allocation parameter override.

        Raises:
            AssertionError: If inherited parameters are not set correctly
        """
        # Create AllInSizer - should override percents to 100%
        sizer = AllInSizer()

        # Should inherit from PercentSizer with default 100% allocation
        assert sizer.get_param("percents") == 100
        assert sizer.get_param("retint") == False

    def test_percent_sizer_int(self):
        """Test PercentSizerInt default parameters.

        Validates that PercentSizerInt properly inherits from PercentSizer
        with the retint=True parameter override for integer return values.

        Raises:
            AssertionError: If retint parameter is not True by default
        """
        # Create PercentSizerInt - should have retint=True by default
        sizer = PercentSizerInt()

        # Should have retint=True by default for integer returns
        assert sizer.get_param("retint") == True
        assert sizer.get_param("percents") == 20  # Default from parent

    def test_all_in_sizer_int(self):
        """Test AllInSizerInt combination of overrides.

        Validates that AllInSizerInt combines both the 100% allocation
        from AllInSizer and the integer return behavior from PercentSizerInt.

        Raises:
            AssertionError: If both overrides are not applied correctly
        """
        # Create AllInSizerInt - combines both overrides
        sizer = AllInSizerInt()

        # Should have both 100% allocation and integer return behavior
        assert sizer.get_param("percents") == 100
        assert sizer.get_param("retint") == True

    def test_fixed_reverser(self):
        """Test FixedReverser sizer parameter system.

        Validates that FixedReverser properly implements the parameter
        system for position reversing logic.

        Raises:
            AssertionError: If parameter operations fail
        """
        # Create FixedReverser with custom stake parameter
        sizer = FixedReverser(stake=5)

        # Verify initial parameter value
        assert sizer.get_param("stake") == 5

        # Test parameter modification - verify stake can be updated
        sizer.set_param("stake", 10)
        assert sizer.get_param("stake") == 10

    def test_fixed_size_target(self):
        """Test FixedSizeTarget sizer parameter system.

        Validates that FixedSizeTarget properly implements the parameter
        system for target position sizing logic.

        Raises:
            AssertionError: If parameter operations fail
        """
        # Create FixedSizeTarget with custom parameters
        sizer = FixedSizeTarget(stake=15, tranches=3)

        # Verify initial parameter values
        assert sizer.get_param("stake") == 15
        assert sizer.get_param("tranches") == 3


class TestFilterRefactoring:
    """Test suite for refactored Filter classes.

    This test class validates that all Filter classes have been successfully
    migrated from the MetaParams metaclass system to the ParameterizedBase
    mixin pattern. It tests parameter access, modification, and initialization
    across various filter implementations.

    Tested filters include:
    - Filter: Base filter class
    - SessionFiller: Fills missing session data
    - SessionFilter: Filters data to trading sessions
    - SessionFilterSimple: Simplified session filtering
    """

    def test_base_filter(self):
        """Test base Filter class initialization and attributes.

        Validates that:
        - Filter inherits from ParameterizedBase
        - Filter has _firsttime attribute set to True
        - Filter can be initialized with a data object

        Raises:
            AssertionError: If filter initialization or inheritance fails
        """

        # Mock data object - minimal implementation for testing filter initialization
        class MockData:
            """Mock data object for testing Filter initialization.

            This minimal mock class provides the required data interface
            without needing a full backtrader data feed implementation.
            """

            pass

        # Create filter instance with mock data
        data = MockData()
        filter_obj = Filter(data)

        # Verify inheritance from ParameterizedBase
        assert isinstance(filter_obj, ParameterizedBase)
        assert hasattr(filter_obj, "_firsttime")
        assert filter_obj._firsttime == True

    def test_session_filler_parameters(self):
        """Test SessionFiller parameter system.

        Validates that SessionFiller properly implements the parameter
        system for filling missing session data with configurable
        price, volume, and open interest values.

        Raises:
            AssertionError: If parameter operations fail
        """

        # Mock data object with required attributes for SessionFiller
        class MockData:
            """Mock data object for testing SessionFiller.

            Attributes:
                _timeframe: Time frame for the data (Minutes in this case)
                _compression: Compression factor (1 = no compression)
            """

            _timeframe = bt.TimeFrame.Minutes  # Use actual TimeFrame constant
            _compression = 1

        # Create SessionFiller with custom parameters
        data = MockData()
        filler = SessionFiller(
            data, fill_price=100.0, fill_vol=1000, fill_oi=500, skip_first_fill=False
        )

        # Test parameter access - verify all parameters are set correctly
        assert filler.get_param("fill_price") == 100.0
        assert filler.get_param("fill_vol") == 1000
        assert filler.get_param("fill_oi") == 500
        assert filler.get_param("skip_first_fill") == False

        # Test parameter modification - verify parameters can be updated
        filler.set_param("fill_price", 105.0)
        assert filler.get_param("fill_price") == 105.0

    def test_session_filter_simple(self):
        """Test SessionFilterSimple initialization.

        Validates that SessionFilterSimple properly inherits from
        ParameterizedBase and can be initialized with a data object.

        Raises:
            AssertionError: If inheritance or initialization fails
        """

        # Mock data object for SessionFilterSimple testing
        class MockData:
            """Mock data object for testing SessionFilterSimple.

            This minimal mock provides the required interface without
            needing a full backtrader data feed implementation.
            """

            pass

        # Create SessionFilterSimple and verify inheritance
        data = MockData()
        filter_obj = SessionFilterSimple(data)

        assert isinstance(filter_obj, ParameterizedBase)

    def test_session_filter(self):
        """Test SessionFilter initialization.

        Validates that SessionFilter properly inherits from
        ParameterizedBase and can be initialized with a data object.

        Raises:
            AssertionError: If inheritance or initialization fails
        """

        # Mock data object for SessionFilter testing
        class MockData:
            """Mock data object for testing SessionFilter.

            This minimal mock provides the required interface without
            needing a full backtrader data feed implementation.
            """

            pass

        # Create SessionFilter and verify inheritance
        data = MockData()
        filter_obj = SessionFilter(data)

        assert isinstance(filter_obj, ParameterizedBase)


class TestParameterCompatibility:
    """Test suite for backward compatibility and parameter system integration.

    This test class validates that:
    - All refactored classes properly inherit from ParameterizedBase
    - Parameter descriptors are correctly defined on classes
    - Parameter validation works as expected
    - Default parameter values are properly set
    """

    def test_parameter_inheritance_chain(self):
        """Test that all refactored classes properly inherit from ParameterizedBase.

        Validates the complete inheritance chain for all refactored classes
        to ensure proper migration from MetaParams to ParameterizedBase.

        Raises:
            AssertionError: If any class doesn't inherit from ParameterizedBase
        """
        # Complete list of refactored classes to verify
        classes_to_test = [
            FixedSize,
            PercentSizer,
            AllInSizer,
            Filter,
            SessionFiller,
            SessionFilter,
            SessionFilterSimple,
        ]

        # Verify each class properly inherits from ParameterizedBase
        for cls in classes_to_test:
            # Check class hierarchy - ensures migration from metaclass system
            assert issubclass(
                cls, ParameterizedBase
            ), f"{cls.__name__} should inherit from ParameterizedBase"

    def test_parameter_descriptor_presence(self):
        """Test that parameter descriptors are properly defined.

        Validates that parameters are defined as ParameterDescriptor instances
        on the class level, enabling proper attribute-style access and validation.

        Raises:
            AssertionError: If parameters are not properly defined as descriptors
        """
        # Test FixedSize parameters - verify descriptor implementation
        assert hasattr(FixedSize, "stake")
        assert isinstance(FixedSize.stake, ParameterDescriptor)
        assert hasattr(FixedSize, "tranches")
        assert isinstance(FixedSize.tranches, ParameterDescriptor)

        # Test PercentSizer parameters - verify descriptor implementation
        assert hasattr(PercentSizer, "percents")
        assert isinstance(PercentSizer.percents, ParameterDescriptor)
        assert hasattr(PercentSizer, "retint")
        assert isinstance(PercentSizer.retint, ParameterDescriptor)

        # Test SessionFiller parameters - verify descriptor implementation
        assert hasattr(SessionFiller, "fill_price")
        assert isinstance(SessionFiller.fill_price, ParameterDescriptor)
        assert hasattr(SessionFiller, "fill_vol")
        assert isinstance(SessionFiller.fill_vol, ParameterDescriptor)

    def test_parameter_validation_integration(self):
        """Test that parameter validation works correctly in refactored classes.

        Validates that parameter validation rules are properly enforced,
        including minimum and maximum value constraints.

        Raises:
            AssertionError: If validation doesn't work as expected
            ValueError: Expected when setting invalid parameter values
        """
        # Test FixedSize validation - minimum stake validation
        sizer = FixedSize()
        with pytest.raises(ValueError):
            sizer.set_param("stake", 0)  # Should fail minimum validation

        # Test PercentSizer validation - maximum percentage validation
        percent_sizer = PercentSizer()
        with pytest.raises(ValueError):
            percent_sizer.set_param("percents", 150)  # Should fail maximum validation

    def test_parameter_defaults(self):
        """Test that default parameter values are correctly set.

        Validates that all parameter defaults are properly initialized
        according to the class definitions, including inheritance overrides.

        Raises:
            AssertionError: If default values don't match expectations
        """
        # Test FixedSize defaults - verify default stake and tranches
        sizer = FixedSize()
        assert sizer.get_param("stake") == 1
        assert sizer.get_param("tranches") == 1

        # Test PercentSizer defaults - verify default percentage and return type
        percent_sizer = PercentSizer()
        assert percent_sizer.get_param("percents") == 20
        assert percent_sizer.get_param("retint") == False

        # Test AllInSizer override - verifies parameter inheritance with override
        all_in = AllInSizer()
        assert all_in.get_param("percents") == 100


class TestMigrationCompleteness:
    """Test suite for migration completeness from MetaParams to ParameterizedBase.

    This test class validates that the refactoring is complete by checking:
    - Legacy params tuples have been removed
    - __init__ methods accept **kwargs for parameter passing
    - Class documentation has been updated to reflect the changes
    """

    def test_no_legacy_params_attributes(self):
        """Test that legacy params tuples have been removed.

        Validates that the old params tuple attribute is no longer present
        on refactored classes, confirming complete migration to the new system.

        Raises:
            AssertionError: If legacy params attribute is found
        """
        # Complete list of sizer classes that should have migrated
        classes_to_test = [
            FixedSize,
            PercentSizer,
            AllInSizer,
            PercentSizerInt,
            AllInSizerInt,
            FixedReverser,
            FixedSizeTarget,
        ]

        # Verify none of the refactored classes have legacy params attribute
        for cls in classes_to_test:
            # Should not have legacy params attribute - confirms migration
            assert not hasattr(
                cls, "params"
            ), f"{cls.__name__} should not have legacy params attribute"

    def test_init_method_compatibility(self):
        """Test that __init__ methods accept **kwargs for parameter passing.

        Validates backward compatibility by ensuring all classes can be
        instantiated with keyword arguments for parameter initialization,
        maintaining the same API as the original metaclass-based system.

        Raises:
            Exception: If any class fails to instantiate with kwargs
        """
        # Create a minimal mock data object with required attributes
        # Using type() to create a lightweight mock class on-the-fly
        mock_data = type("MockData", (), {"_timeframe": bt.TimeFrame.Minutes, "_compression": 1})()

        # Test that all classes can be instantiated with keyword arguments
        # These should not raise exceptions - validates backward compatibility
        FixedSize(stake=5, tranches=2)
        PercentSizer(percents=25, retint=True)
        Filter(mock_data)
        SessionFiller(mock_data, fill_price=100.0)
        SessionFilter(mock_data)
        SessionFilterSimple(mock_data)

    def test_class_documentation_updated(self):
        """Test that class documentation mentions the refactoring.

        Validates that refactored classes have updated documentation
        that mentions the migration from MetaParams to ParameterizedBase,
        helping users understand the architectural changes.

        Raises:
            AssertionError: If class documentation is missing or incomplete
        """
        # Classes that should have updated documentation mentioning the refactoring
        classes_with_updated_docs = [
            FixedSize,
            PercentSizer,
            SessionFiller,
            SessionFilter,
            SessionFilterSimple,
            Filter,
        ]

        # Verify each class has documentation mentioning the refactoring
        for cls in classes_with_updated_docs:
            doc = cls.__doc__
            assert doc is not None, f"{cls.__name__} should have documentation"
            # Check if documentation mentions the refactoring keywords
            assert any(
                keyword in doc.lower()
                for keyword in ["refactor", "day 36-38", "parameterdescriptor", "parameterizedbase"]
            ), f"{cls.__name__} documentation should mention the refactoring"


# Allow running this test file directly for quick validation
# When executed as a script, run pytest with verbose output
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
