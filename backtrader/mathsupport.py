#!/usr/bin/env python
"""Math Support Module - Mathematical functions for indicator calculations.

This module provides mathematical utility functions for calculating
statistics used in technical indicators, such as average, variance,
and standard deviation.

Functions:
    average: Calculate arithmetic mean with optional Bessel's correction.
    variance: Calculate variance from a sequence.
    standarddev: Calculate standard deviation with Bessel's correction option.

Note:
    These functions are primarily used for indicator calculations.
    For large datasets, numpy-based implementations would provide
    better performance.
"""

import math


def is_finite_real(value):
    """Check if a value is a finite real number (not complex, not NaN, not inf).

    Args:
        value: The value to check.

    Returns:
        bool: True if value is a finite real number, False otherwise.
    """
    try:
        return not isinstance(value, complex) and math.isfinite(value)
    except TypeError:
        return False

# These functions are mainly used for calculating indicators, not used in main code. Commented for now, will review later whether Cython optimization is needed, no immediate need.
# However, these functions could potentially be optimized using numpy, which provides specific functions for calculating mean and standard deviation


# This calculates the average, with a parameter bessel to determine whether to subtract one from the denominator. The numerator uses math.fsum for calculating sum
def average(x, bessel=False):
    """
    Args:
      :param x: iterable with len
      :param bessel: default False, reduces the length of the array for the
                division.

    Returns:
      A float with the average of the elements of x
    """
    # CRITICAL FIX: Prevent division by zero and negative denominator
    denominator = len(x) - bessel
    if denominator <= 0:
        return 0.0
    return math.fsum(x) / denominator


# Used to calculate variance. Obviously, converting this function to Cython or numpy would greatly improve efficiency. But this is an edge function, temporarily ignoring optimization.
# This function first checks if avgx is None, if None it calculates the average of an iterable, then calculates variance.
def variance(x, avgx=None):
    """
    Args:
      x: iterable with len
      avgx: average of x

    Returns:
      A list with the variance for each element of x
    """
    if not x:
        return []
    if avgx is None:
        avgx = average(x)
    return [pow(y - avgx, 2.0) for y in x]


# This function calculates the standard deviation of an iterable object x.
def standarddev(x, avgx=None, bessel=False):
    """
    Args:
      x: iterable with len
      avgx: average of x
      bessel: (default ``False``) to be passed to the average to divide by
      ``N - 1`` (Bessel's correction)

    Returns:
      A float with the standard deviation of the elements of x
    """
    if not x:
        return 0.0
    avg_var = average(variance(x, avgx), bessel=bessel)
    if avg_var < 0.0:
        return 0.0
    return math.sqrt(avg_var)
