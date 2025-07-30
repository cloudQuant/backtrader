#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
from backtrader import Position


def check_stocks():
    commission = 0.5
    comm = bt.CommissionInfo(commission=commission)

    price = 10.0
    cash = 10000.0
    size = 100.0

    opcost = comm.getoperationcost(size=size, price=price)
    assert opcost == size * price

    pos = Position(size=size, price=price)
    value = comm.getvalue(pos, price)
    assert value == size * price

    commcost = comm.getcommission(size, price)
    assert commcost == size * price * commission

    newprice = 5.0
    pnl = comm.profitandloss(pos.size, pos.price, newprice)
    assert pnl == pos.size * (newprice - price)

    ca = comm.cashadjust(size, price, newprice)
    assert not ca


def check_futures():
    commission = 0.5
    margin = 10.0
    mult = 10.0
    comm = bt.CommissionInfo(commission=commission, mult=mult, margin=margin)

    price = 10.0
    cash = 10000.0
    size = 100.0

    opcost = comm.getoperationcost(size=size, price=price)
    assert opcost == size * margin

    pos = Position(size=size, price=price)
    value = comm.getvalue(pos, price)
    assert value == size * margin

    commcost = comm.getcommission(size, price)
    assert commcost == size * commission

    newprice = 5.0
    pnl = comm.profitandloss(pos.size, pos.price, newprice)
    assert pnl == pos.size * (newprice - price) * mult

    ca = comm.cashadjust(size, price, newprice)
    assert ca == size * (newprice - price) * mult


def test_run(main=False):
    check_stocks()
    check_futures()


if __name__ == '__main__':
    test_run(main=True)
