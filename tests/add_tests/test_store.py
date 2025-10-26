#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backtrader as bt


def test_store(main=False):
    """Test store base class exists"""
    # Verify store base class exists
    assert hasattr(bt, 'Store')
    
    if main:
        # print('Store base test passed')  # Removed for performance
        pass


if __name__ == '__main__':
    test_store(main=True)

