#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from ..comminfo import CommInfoBase


class CommInfo(CommInfoBase):
    pass  # clone of CommissionInfo but with xx% instead of 0.xx


class CommInfo_Futures(CommInfoBase):
    params = (
        ('stocklike', False),
    )


class CommInfo_Futures_Perc(CommInfo_Futures):
    params = (
        ('commtype', CommInfoBase.COMM_PERC),
    )


class CommInfo_Futures_Fixed(CommInfo_Futures):
    params = (
        ('commtype', CommInfoBase.COMM_FIXED),
    )


class CommInfo_Stocks(CommInfoBase):
    params = (
        ('stocklike', True),
    )


class CommInfo_Stocks_Perc(CommInfo_Stocks):
    params = (
        ('commtype', CommInfoBase.COMM_PERC),
    )


class CommInfo_Stocks_Fixed(CommInfo_Stocks):
    params = (
        ('commtype', CommInfoBase.COMM_FIXED),
    )
