#!/usr/bin/env python



import backtrader as bt

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))



def test_store(main=False):
    """Test store base class exists"""
    # Verify store base class exists
    assert hasattr(bt, "Store")

    if main:
        # print('Store base test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_store(main=True)
