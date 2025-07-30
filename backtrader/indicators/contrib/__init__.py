#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt

from .import vortex as vortex
for name in vortex.__all__:
    setattr(bt.indicators, name, getattr(vortex, name))
