#!/usr/bin/env python
"""Smoke tests for backtrader.mathsupport.

Covers the pure statistical helpers (average / variance / standarddev) and the
is_finite_real guard, including the edge cases the implementation explicitly
guards against (empty input, Bessel denominator <= 0, non-finite values).
"""

import math

import pytest

from backtrader import mathsupport as ms


def test_is_finite_real():
    assert ms.is_finite_real(1.0)
    assert ms.is_finite_real(-3)
    assert not ms.is_finite_real(float("nan"))
    assert not ms.is_finite_real(float("inf"))
    assert not ms.is_finite_real(complex(1, 2))
    assert not ms.is_finite_real("not a number")
    assert not ms.is_finite_real(None)


def test_average_basic():
    assert ms.average([2.0, 4.0, 6.0]) == 4.0
    # single element
    assert ms.average([5.0]) == 5.0


def test_average_bessel_and_guard():
    # bessel divides by len-1
    assert ms.average([2.0, 4.0], bessel=True) == 6.0  # fsum=6 / (2-1)
    # denominator <= 0 guarded -> 0.0 (single element with bessel)
    assert ms.average([5.0], bessel=True) == 0.0
    # empty input -> denominator <= 0 -> 0.0
    assert ms.average([]) == 0.0


def test_variance():
    assert ms.variance([]) == []
    # variance terms around the mean (mean of [1,3] is 2 -> [1.0, 1.0])
    assert ms.variance([1.0, 3.0]) == [1.0, 1.0]
    # explicit avgx is honored
    assert ms.variance([1.0, 3.0], avgx=0.0) == [1.0, 9.0]


def test_standarddev():
    assert ms.standarddev([]) == 0.0
    # population std of [1,3] is 1.0
    assert ms.standarddev([1.0, 3.0]) == pytest.approx(1.0)
    # sample std (Bessel) of [1,3] is sqrt(2)
    assert ms.standarddev([1.0, 3.0], bessel=True) == pytest.approx(math.sqrt(2.0))
    # never returns NaN/negative
    assert ms.standarddev([2.0, 2.0, 2.0]) == 0.0
