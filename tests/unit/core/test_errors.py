#!/usr/bin/env python
"""Test error classes and exception handling in backtrader.

This module tests the error classes provided by the backtrader framework,
ensuring that exceptions can be properly raised, caught, and manipulated.
Error handling is critical for robust strategy development and backtesting.

The main error class tested is:
    StrategySkipError: Used to skip strategy execution during backtesting

Example:
    Run tests directly::

        $ python tests/add_tests/test_errors.py

    Or via pytest::

        $ python -m pytest tests/add_tests/test_errors.py -v
"""

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import backtrader as bt
import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_errors(main=False):
    """Test that error classes exist and can be instantiated.

    This function verifies that the StrategySkipError exception class can be:
        1. Instantiated with a custom error message
        2. Raised and caught properly
        3. Converted to a string matching the original message

    The StrategySkipError is used to signal that a strategy should be skipped
    during backtesting, typically when certain preconditions are not met.

    Args:
        main (bool, optional): If True, print test results for manual inspection.
            Defaults to False.

    Raises:
        AssertionError: If the error message doesn't match the expected value.

    Example:
        >>> test_errors(main=True)
        Errors test passed
    """
    # Test StrategySkipError - verifies exception can be raised with custom message
    try:
        raise bt.errors.StrategySkipError("Test skip error")
    except bt.errors.StrategySkipError as e:
        if main:
            # Optionally print for manual verification (disabled for performance)
            # print(f'Caught StrategySkipError: {e}')
            pass
        # Verify the error message is preserved correctly
        assert str(e) == "Test skip error"

    if main:
        # Optionally print test completion (disabled for performance)
        # print('Errors test passed')
        pass


def test_business_exception_hierarchy():
    """The Sprint 3 category exceptions exist and stay backward compatible.

    DataError / BrokerError / OrderError / ConfigError must all derive from
    BacktraderError (so existing ``except BacktraderError`` keeps working), and
    OrderError must derive from BrokerError. They are exported at both
    ``bt.errors`` and the top-level ``bt`` namespace.
    """
    for name in ("DataError", "BrokerError", "OrderError", "ConfigError"):
        cls = getattr(bt.errors, name)
        assert issubclass(cls, bt.errors.BacktraderError)
        # exported at top level via star import
        assert getattr(bt, name) is cls

    # OrderError is a kind of BrokerError
    assert issubclass(bt.errors.OrderError, bt.errors.BrokerError)

    # legacy classes unchanged
    assert issubclass(bt.errors.StrategySkipError, bt.errors.BacktraderError)

    # instances carry their message and are catchable as the base
    try:
        raise bt.errors.OrderError("bad order size")
    except bt.errors.BrokerError as e:  # caught via the parent category
        assert str(e) == "bad order size"


def test_research_errors_share_core_hierarchy_without_replacing_config_error():
    from backtrader import errors
    from backtrader.errors import (
        DataQualityError,
        DatasetError,
        DependencyError,
        FactorComputationError,
        ResearchConfigError,
        ResearchError,
    )

    import backtrader.research as research

    assert ResearchError.__bases__ == (errors.BacktraderError,)
    assert issubclass(ResearchError, errors.BacktraderError)
    assert errors.ConfigError is not ResearchConfigError
    assert not issubclass(errors.ConfigError, ResearchError)
    assert not issubclass(errors.ConfigError, ValueError)
    assert issubclass(ResearchConfigError, ValueError)
    for name in (
        "ResearchError",
        "ResearchConfigError",
        "DatasetError",
        "DependencyError",
        "DataQualityError",
        "FactorComputationError",
        "FactorComputationContext",
    ):
        assert getattr(bt, name) is getattr(errors, name)
    assert bt.FACTOR_COMPUTATION_FAILED == "FACTOR_COMPUTATION_FAILED"
    assert ResearchConfigError("invalid").code == "INVALID_CONFIG"
    assert (
        FactorComputationError(factor="alpha", asset=None, phase="next").code
        == errors.FACTOR_COMPUTATION_FAILED
    )

    for error_type, builtin_type in (
        (ResearchConfigError, ValueError),
        (DatasetError, ValueError),
        (DependencyError, ImportError),
        (DataQualityError, ValueError),
        (FactorComputationError, RuntimeError),
    ):
        error = (
            error_type(factor="alpha", asset=None, phase="next")
            if error_type is FactorComputationError
            else error_type("research failure")
        )
        with pytest.raises(errors.BacktraderError):
            raise error
        with pytest.raises(builtin_type):
            raise error

    assert research.ConfigError is ResearchConfigError
    assert research.ResearchConfigError is ResearchConfigError
    assert ResearchConfigError.__module__ == "backtrader.errors"
    assert "backtrader.research.errors" not in sys.modules
    assert not (Path(research.__file__).parent / "errors.py").exists()


def test_research_error_report_is_deeply_immutable_and_cause_is_preserved():
    from backtrader.errors import FactorComputationContext, ResearchConfigError

    original = {"nested": {"rows": [{"labels": ["close"]}], "tags": {"pit"}}}
    error = ResearchConfigError("invalid input", code="CUSTOM_CONFIG", report=original)
    original["nested"]["rows"][0]["labels"].append("mutated")

    assert error.code == "CUSTOM_CONFIG"
    assert error.report["nested"]["rows"][0]["labels"] == ("close",)
    assert error.report["nested"]["tags"] == frozenset({"pit"})
    with pytest.raises(TypeError):
        error.report["nested"]["changed"] = True
    with pytest.raises(TypeError):
        error.report["nested"]["rows"][0]["labels"][0] = "changed"

    cause = LookupError("original calculation failure")
    wrapped = FactorComputationContext("alpha").wrap(cause)
    with pytest.raises(type(wrapped)) as caught:
        raise wrapped from cause
    assert caught.value.__cause__ is cause


@pytest.mark.parametrize("light_import", (False, True), ids=("normal", "light"))
def test_fresh_error_import_does_not_load_research_dependencies(light_import):
    repository_root = Path(__file__).resolve().parents[3]
    script = dedent("""\
        import importlib.util
        import sys
        from pathlib import Path

        def has_module(prefix):
            return any(name == prefix or name.startswith(prefix + ".") for name in sys.modules)

        source = Path("backtrader/errors.py")
        spec = importlib.util.spec_from_file_location("_isolated_errors_probe", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert "pandas" not in sys.modules
        assert not has_module("backtrader.research")
        assert not has_module("fincore")

        import backtrader.errors
        assert not has_module("backtrader.research")
        assert not has_module("fincore")
        """)
    environment = os.environ.copy()
    if light_import:
        environment["BACKTRADER_LIGHT_IMPORT"] = "1"
    else:
        environment.pop("BACKTRADER_LIGHT_IMPORT", None)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(repository_root),
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    # Run tests with main=True when executed directly
    test_errors(main=True)
