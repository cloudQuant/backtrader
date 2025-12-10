"""
Tests for Simple Classes Refactoring (Day 36-38)

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

from backtrader import TimeFrame
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
    """Test the refactored Sizer classes."""

    def test_fixed_size_sizer(self):
        """Test FixedSize sizer with new parameter system."""
        sizer = FixedSize(stake=10, tranches=2)

        # Test parameter access
        assert sizer.get_param("stake") == 10
        assert sizer.get_param("tranches") == 2

        # Test parameter modification
        sizer.set_param("stake", 20)
        assert sizer.get_param("stake") == 20

        # Test parameter validation
        with pytest.raises(ValueError):
            sizer.set_param("stake", -5)  # Should fail validation

    def test_percent_sizer(self):
        """Test PercentSizer with new parameter system."""
        sizer = PercentSizer(percents=30, retint=True)

        # Test parameter access
        assert sizer.get_param("percents") == 30
        assert sizer.get_param("retint") == True

        # Test parameter validation
        with pytest.raises(ValueError):
            sizer.set_param("percents", 150)  # Should fail validation (>100)

        with pytest.raises(ValueError):
            sizer.set_param("percents", -10)  # Should fail validation (<0)

    def test_all_in_sizer(self):
        """Test AllInSizer inheritance."""
        sizer = AllInSizer()

        # Should inherit from PercentSizer with default 100%
        assert sizer.get_param("percents") == 100
        assert sizer.get_param("retint") == False

    def test_percent_sizer_int(self):
        """Test PercentSizerInt."""
        sizer = PercentSizerInt()

        # Should have retint=True by default
        assert sizer.get_param("retint") == True
        assert sizer.get_param("percents") == 20  # Default from parent

    def test_all_in_sizer_int(self):
        """Test AllInSizerInt."""
        sizer = AllInSizerInt()

        # Should have both 100% and retint=True
        assert sizer.get_param("percents") == 100
        assert sizer.get_param("retint") == True

    def test_fixed_reverser(self):
        """Test FixedReverser sizer."""
        sizer = FixedReverser(stake=5)

        assert sizer.get_param("stake") == 5

        # Test parameter modification
        sizer.set_param("stake", 10)
        assert sizer.get_param("stake") == 10

    def test_fixed_size_target(self):
        """Test FixedSizeTarget sizer."""
        sizer = FixedSizeTarget(stake=15, tranches=3)

        assert sizer.get_param("stake") == 15
        assert sizer.get_param("tranches") == 3


class TestFilterRefactoring:
    """Test the refactored Filter classes."""

    def test_base_filter(self):
        """Test base Filter class."""

        # Mock data object
        class MockData:
            pass

        data = MockData()
        filter_obj = Filter(data)

        # Test inheritance
        assert isinstance(filter_obj, ParameterizedBase)
        assert hasattr(filter_obj, "_firsttime")
        assert filter_obj._firsttime == True

    def test_session_filler_parameters(self):
        """Test SessionFiller parameter system."""

        # Mock data object with required attributes
        class MockData:
            _timeframe = TimeFrame.Minutes  # Use actual TimeFrame constant
            _compression = 1

        data = MockData()
        filler = SessionFiller(
            data, fill_price=100.0, fill_vol=1000, fill_oi=500, skip_first_fill=False
        )

        # Test parameter access
        assert filler.get_param("fill_price") == 100.0
        assert filler.get_param("fill_vol") == 1000
        assert filler.get_param("fill_oi") == 500
        assert filler.get_param("skip_first_fill") == False

        # Test parameter modification
        filler.set_param("fill_price", 105.0)
        assert filler.get_param("fill_price") == 105.0

    def test_session_filter_simple(self):
        """Test SessionFilterSimple."""

        class MockData:
            pass

        data = MockData()
        filter_obj = SessionFilterSimple(data)

        assert isinstance(filter_obj, ParameterizedBase)

    def test_session_filter(self):
        """Test SessionFilter."""

        class MockData:
            pass

        data = MockData()
        filter_obj = SessionFilter(data)

        assert isinstance(filter_obj, ParameterizedBase)


class TestParameterCompatibility:
    """Test backward compatibility and parameter system integration."""

    def test_parameter_inheritance_chain(self):
        """Test that all refactored classes properly inherit from ParameterizedBase."""
        classes_to_test = [
            FixedSize,
            PercentSizer,
            AllInSizer,
            Filter,
            SessionFiller,
            SessionFilter,
            SessionFilterSimple,
        ]

        for cls in classes_to_test:
            # Check class hierarchy
            assert issubclass(
                cls, ParameterizedBase
            ), f"{cls.__name__} should inherit from ParameterizedBase"

    def test_parameter_descriptor_presence(self):
        """Test that parameter descriptors are properly defined."""
        # Test FixedSize
        assert hasattr(FixedSize, "stake")
        assert isinstance(FixedSize.stake, ParameterDescriptor)
        assert hasattr(FixedSize, "tranches")
        assert isinstance(FixedSize.tranches, ParameterDescriptor)

        # Test PercentSizer
        assert hasattr(PercentSizer, "percents")
        assert isinstance(PercentSizer.percents, ParameterDescriptor)
        assert hasattr(PercentSizer, "retint")
        assert isinstance(PercentSizer.retint, ParameterDescriptor)

        # Test SessionFiller
        assert hasattr(SessionFiller, "fill_price")
        assert isinstance(SessionFiller.fill_price, ParameterDescriptor)
        assert hasattr(SessionFiller, "fill_vol")
        assert isinstance(SessionFiller.fill_vol, ParameterDescriptor)

    def test_parameter_validation_integration(self):
        """Test that parameter validation works correctly in refactored classes."""
        # Test FixedSize validation
        sizer = FixedSize()
        with pytest.raises(ValueError):
            sizer.set_param("stake", 0)  # Should fail minimum validation

        # Test PercentSizer validation
        percent_sizer = PercentSizer()
        with pytest.raises(ValueError):
            percent_sizer.set_param("percents", 150)  # Should fail maximum validation

    def test_parameter_defaults(self):
        """Test that default parameter values are correctly set."""
        # Test FixedSize defaults
        sizer = FixedSize()
        assert sizer.get_param("stake") == 1
        assert sizer.get_param("tranches") == 1

        # Test PercentSizer defaults
        percent_sizer = PercentSizer()
        assert percent_sizer.get_param("percents") == 20
        assert percent_sizer.get_param("retint") == False

        # Test AllInSizer override
        all_in = AllInSizer()
        assert all_in.get_param("percents") == 100


class TestMigrationCompleteness:
    """Test that the migration from MetaParams to ParameterizedBase is complete."""

    def test_no_legacy_params_attributes(self):
        """Test that legacy params tuples have been removed."""
        classes_to_test = [
            FixedSize,
            PercentSizer,
            AllInSizer,
            PercentSizerInt,
            AllInSizerInt,
            FixedReverser,
            FixedSizeTarget,
        ]

        for cls in classes_to_test:
            # Should not have legacy params attribute
            assert not hasattr(
                cls, "params"
            ), f"{cls.__name__} should not have legacy params attribute"

    def test_init_method_compatibility(self):
        """Test that __init__ methods accept **kwargs for parameter passing."""
        # Test that all classes can be instantiated with keyword arguments
        mock_data = type("MockData", (), {"_timeframe": TimeFrame.Minutes, "_compression": 1})()

        # These should not raise exceptions
        FixedSize(stake=5, tranches=2)
        PercentSizer(percents=25, retint=True)
        Filter(mock_data)
        SessionFiller(mock_data, fill_price=100.0)
        SessionFilter(mock_data)
        SessionFilterSimple(mock_data)

    def test_class_documentation_updated(self):
        """Test that class documentation mentions the refactoring."""
        classes_with_updated_docs = [
            FixedSize,
            PercentSizer,
            SessionFiller,
            SessionFilter,
            SessionFilterSimple,
            Filter,
        ]

        for cls in classes_with_updated_docs:
            doc = cls.__doc__
            assert doc is not None, f"{cls.__name__} should have documentation"
            # Check if documentation mentions the refactoring
            assert any(
                keyword in doc.lower()
                for keyword in ["refactor", "day 36-38", "parameterdescriptor", "parameterizedbase"]
            ), f"{cls.__name__} documentation should mention the refactoring"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
