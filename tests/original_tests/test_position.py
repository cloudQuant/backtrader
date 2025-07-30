#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from backtrader import position


def test_run(main=False):
    size = 10
    price = 10.0

    pos = position.Position(size=size, price=price)
    assert pos.size == size
    assert pos.price == price

    upsize = 5
    upprice = 12.5
    nsize, nprice, opened, closed = pos.update(size=upsize, price=upprice)

    if main:
        print('pos.size/price', pos.size, pos.price)
        print('nsize, nprice, opened, closed', nsize, nprice, opened, closed)

    assert pos.size == size + upsize
    assert pos.size == nsize
    assert pos.price == ((size * price) + (upsize * upprice)) / pos.size
    assert pos.price == nprice
    assert opened == upsize
    assert not closed

    size = pos.size
    price = pos.price
    upsize = -7
    upprice = 14.5

    nsize, nprice, opened, closed = pos.update(size=upsize, price=upprice)

    if main:
        print('pos.size/price', pos.size, pos.price)
        print('nsize, nprice, opened, closed', nsize, nprice, opened, closed)

    assert pos.size == size + upsize

    assert pos.size == nsize
    assert pos.price == price
    assert pos.price == nprice
    assert not opened
    assert closed == upsize  # the closed must have the sign of "update" size

    size = pos.size
    price = pos.price
    upsize = -15
    upprice = 17.5

    nsize, nprice, opened, closed = pos.update(size=upsize, price=upprice)

    if main:
        print('pos.size/price', pos.size, pos.price)
        print('nsize, nprice, opened, closed', nsize, nprice, opened, closed)

    assert pos.size == size + upsize
    assert pos.size == nsize
    assert pos.price == upprice
    assert pos.price == nprice
    assert opened == size + upsize
    assert closed == -size


if __name__ == '__main__':
    test_run(main=True)
