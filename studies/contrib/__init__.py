#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt

from .import fractal as fractal
for name in fractal.__all__:
    setattr(bt.studies, name, getattr(fractal, name))
