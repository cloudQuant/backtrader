#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)


from . import GenericCSVData


class MT4CSVData(GenericCSVData):
    """
    Parses a `Metatrader4 <https://www.metaquotes.net/en/metatrader4>`_ History
    center CSV exported file.

    Specific parameters (or specific meaning):

      - ``dataname``: The filename to parse or a file-like object

      - Uses GenericCSVData and simply modifies the params
    """
    # MT4数据的这个类，继承了CSV类，仅仅只是修改了参数
    params = (
        ('dtformat', '%Y.%m.%d'),
        ('tmformat', '%H:%M'),
        ('datetime', 0),
        ('time',  1),
        ('open',  2),
        ('high',  3),
        ('low',   4),
        ('close', 5),
        ('volume', 6),
        ('openinterest', -1),
    )
