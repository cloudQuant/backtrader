#!/usr/bin/env python



import backtrader as bt

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))



def test_errors(main=False):
    """Test that error classes exist and can be instantiated"""
    # Test StrategySkipError
    try:
        raise bt.errors.StrategySkipError("Test skip error")
    except bt.errors.StrategySkipError as e:
        if main:
            # print(f'Caught StrategySkipError: {e}')  # Removed for performance
            pass
        assert str(e) == "Test skip error"

    if main:
        # print('Errors test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_errors(main=True)
