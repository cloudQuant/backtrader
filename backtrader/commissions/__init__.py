#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from ..comminfo import CommInfoBase


class CommInfo(CommInfoBase):
    pass  # clone of CommissionInfo but with xx% instead of 0.xx


class CommInfoFutures(CommInfoBase):
    params = (("stocklike", False),)


class CommInfoFuturesPerc(CommInfoFutures):
    params = (("commtype", CommInfoBase.COMM_PERC),)


class CommInfoFuturesFixed(CommInfoFutures):
    params = (("commtype", CommInfoBase.COMM_FIXED),)


class CommInfoStocks(CommInfoBase):
    params = (("stocklike", True),)


class CommInfoStocksPerc(CommInfoStocks):
    params = (("commtype", CommInfoBase.COMM_PERC),)


class CommInfoStocksFixed(CommInfoStocks):
    params = (("commtype", CommInfoBase.COMM_FIXED),)
