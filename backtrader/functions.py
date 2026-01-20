#!/usr/bin/env python
"""Functions Module - Common operations on line objects.

This module provides utility functions and classes for performing
operations on line objects. It includes arithmetic operations with
zero-division protection, logical operations, comparison operations,
and mathematical functions.

Classes:
    Logic: Base class for logical operations on lines.
    DivByZero: Division with zero-division protection.
    DivZeroByZero: Division with zero/zero indetermination protection.
    And/Or/Not/If/Max/Min/MinN/MaxN: Logical and comparison operations.
    Sum/Average/StdDev/TSMean: Statistical operations.

Example:
    Using indicator functions:
    >>> from backtrader.functions import And, Or
    >>> condition = And(indicator1 > indicator2, indicator3 > 0)
"""

import functools
import math

from .linebuffer import LineActions
from .utils.py3 import cmp, range


# Generate a List equivalent which uses "is" for contains
# Create a new List class, overriding __contains__ method, if any element in list has hash value equal to other's hash value, return True
class List(list):
    """List subclass that uses hash equality for contains checks.

    This class overrides __contains__ to check if any element has
    the same hash value as the target, rather than using identity comparison.
    """

    def __contains__(self, other):
        return any(x.__hash__() == other.__hash__() for x in self)


# Create a class to serialize elements within it
class Logic(LineActions):
    """Base class for logical operations on line objects.

    Handles argument conversion to arrays and manages minperiod
    propagation from operands.
    """

    def __init__(self, *args):
        """Initialize the Logic operation.

        Converts all arguments to arrays and propagates minperiod
        from operands to ensure proper synchronization.

        Args:
            *args: Line objects or values to operate on.
        """
        super().__init__()
        self.args = [self.arrayize(arg) for arg in args]

        # CRITICAL FIX: Collect minperiods from args and update own minperiod
        # This ensures functions like And, Or, etc. inherit the max minperiod from their operands
        _minperiods = []
        for arg in self.args:
            mp = getattr(arg, "_minperiod", 1)
            _minperiods.append(mp)

        if _minperiods:
            max_minperiod = max(_minperiods)
            self.updateminperiod(max_minperiod)


# Avoid division by zero when dividing two lines, if denominator is 0, division result is 0
class DivByZero(Logic):
    """This operation is a Lines object and fills it values by executing a
    division on the numerator / denominator arguments and avoiding a division
    by zero exception by checking the denominator

    Params:
      - a: numerator (numeric or iterable object ... mostly a Lines object)
      - b: denominator (numeric or iterable object ... mostly a Lines object)
      - zero (def: 0.0): value to apply if division by zero is raised

    """

    def __init__(self, a, b, zero=0.0):
        """Initialize the DivByZero operation.

        Args:
            a: Numerator line or value.
            b: Denominator line or value.
            zero: Value to return when division by zero occurs.
        """
        super().__init__(a, b)
        self.a = a
        self.b = b
        self.zero = zero

    def next(self):
        """Calculate the next value with zero-division protection."""
        b = self.b[0]
        self[0] = self.a[0] / b if b else self.zero

    def once(self, start, end):
        """Calculate all values at once with zero-division protection.

        Args:
            start: Starting index for calculation.
            end: Ending index for calculation.
        """
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b.array
        zero = self.zero

        for i in range(start, end):
            b = srcb[i]
            dst[i] = srca[i] / b if b else zero


# Division operation for two lines considering both numerator and denominator may be 0
class DivZeroByZero(Logic):
    """This operation is a Lines object and fills it values by executing a
    division on the numerator / denominator arguments and avoiding a division
    by zero exception or an indetermination by checking the
    denominator/numerator pair

    Params:
      - a: numerator (numeric or iterable object ... mostly a Lines object)
      - b: denominator (numeric or iterable object ... mostly a Lines object)
      - single (def: +inf): value to apply if division is x / 0
      - dual (def: 0.0): value to apply if division is 0 / 0
    """

    def __init__(self, a, b, single=float("inf"), dual=0.0):
        """Initialize the DivZeroByZero operation.

        Args:
            a: Numerator line or value.
            b: Denominator line or value.
            single: Value to return when numerator is non-zero and denominator is zero.
            dual: Value to return when both numerator and denominator are zero.
        """
        super().__init__(a, b)
        self.a = a
        self.b = b
        self.single = single
        self.dual = dual

    def next(self):
        """Calculate the next value with zero/zero indetermination protection."""
        b = self.b[0]
        a = self.a[0]
        if b == 0.0:
            self[0] = self.dual if a == 0.0 else self.single
        else:
            self[0] = self.a[0] / b

    def once(self, start, end):
        """Calculate all values at once with zero/zero indetermination protection.

        Args:
            start: Starting index for calculation.
            end: Ending index for calculation.
        """
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b.array
        single = self.single
        dual = self.dual

        for i in range(start, end):
            b = srcb[i]
            a = srca[i]
            if b == 0.0:
                dst[i] = dual if a == 0.0 else single
            else:
                dst[i] = a / b


# Compare a and b, a and b are likely lines
class Cmp(Logic):
    """Comparison operation that returns comparison results.

    Compares two line objects and returns standard comparison values:
    -1 if a < b, 0 if a == b, 1 if a > b.
    """

    def __init__(self, a, b):
        """Initialize the comparison operation.

        Args:
            a: First line or value to compare.
            b: Second line or value to compare.
        """
        super().__init__(a, b)
        self.a = self.args[0]
        self.b = self.args[1]

    def next(self):
        """Calculate the next comparison value."""
        self[0] = cmp(self.a[0], self.b[0])

    def once(self, start, end):
        """Calculate all comparison values at once.

        Args:
            start: Starting index for calculation.
            end: Ending index for calculation.
        """
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b.array

        for i in range(start, end):
            dst[i] = cmp(srca[i], srcb[i])


# Compare two lines, a and b, return corresponding r1 value when a<b, return r2 value when a=b, return r3 value when a>b
# todo A friend in the backtrader quantitative trading group pointed out this issue
class CmpEx(Logic):
    """Extended comparison operation with three possible return values.

    Compares two line objects and returns one of three values based on
    the comparison result:
    - r1 if a < b
    - r2 if a == b
    - r3 if a > b
    """

    def __init__(self, a, b, r1, r2, r3):
        """Initialize the extended comparison operation.

        Args:
            a: First line or value to compare.
            b: Second line or value to compare.
            r1: Value to return when a < b.
            r2: Value to return when a == b.
            r3: Value to return when a > b.
        """
        super().__init__(a, b, r1, r2, r3)
        self.a = self.args[0]
        self.b = self.args[1]
        self.r1 = self.args[2]
        self.r2 = self.args[3]
        self.r3 = self.args[4]

    def next(self):
        """Calculate the next extended comparison value."""
        # self[0] = cmp(self.a[0], self.b[0])
        if self.a[0] < self.b[0]:
            self[0] = self.r1[0]
        elif self.a[0] > self.b[0]:
            self[0] = self.r3[0]
        else:
            self[0] = self.r2[0]

    def once(self, start, end):
        """Calculate all extended comparison values at once.

        Args:
            start: Starting index for calculation.
            end: Ending index for calculation.
        """
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b.array
        r1 = self.r1.array
        r2 = self.r2.array
        r3 = self.r3.array

        for i in range(start, end):
            ai = srca[i]
            bi = srcb[i]

            if ai < bi:
                dst[i] = r1[i]
            elif ai > bi:
                dst[i] = r3[i]
            else:
                dst[i] = r2[i]


# If statement, return corresponding a value when cond is satisfied, return b value when not satisfied
class If(Logic):
    """Conditional selection operation.

    Returns a value from a or b based on a condition:
    - Returns a if condition is True
    - Returns b if condition is False
    """

    def __init__(self, cond, a, b):
        """Initialize the conditional operation.

        Args:
            cond: Condition line - must evaluate to boolean.
            a: Value to return when condition is True.
            b: Value to return when condition is False.
        """
        super().__init__(a, b)
        self.a = self.args[0]
        self.b = self.args[1]
        self.cond = self.arrayize(cond)

    def next(self):
        """Calculate the next conditional value."""
        self[0] = self.a[0] if self.cond[0] else self.b[0]

    def once(self, start, end):
        """Calculate all conditional values at once.

        Args:
            start: Starting index for calculation.
            end: Ending index for calculation.
        """
        # cache python dictionary lookups
        dst = self.array

        # CRITICAL FIX: Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        # CRITICAL FIX: Check if a and b are LineNum constants (scalar values)
        # LineNum creates _LineDelay(PseudoArray(repeat(num)), 0) which has empty array
        # but supports __getitem__ access that returns the constant value
        a_is_constant = False
        a_constant_val = None
        try:
            srca = self.a.array
            a_has_array = len(srca) > 0
            if not a_has_array:
                # Empty array - might be a LineNum constant, try direct access
                try:
                    a_constant_val = self.a[0]
                    a_is_constant = True
                except Exception:
                    pass
        except (AttributeError, TypeError):
            srca = []
            a_has_array = False
            # Try direct access for constants
            try:
                a_constant_val = self.a[0]
                a_is_constant = True
            except Exception:
                pass

        b_is_constant = False
        b_constant_val = None
        try:
            srcb = self.b.array
            b_has_array = len(srcb) > 0
            if not b_has_array:
                # Empty array - might be a LineNum constant, try direct access
                try:
                    b_constant_val = self.b[0]
                    b_is_constant = True
                except Exception:
                    pass
        except (AttributeError, TypeError):
            srcb = []
            b_has_array = False
            # Try direct access for constants
            try:
                b_constant_val = self.b[0]
                b_is_constant = True
            except Exception:
                pass

        try:
            cond = self.cond.array
            cond_has_array = len(cond) > 0
        except (AttributeError, TypeError):
            cond = []
            cond_has_array = False

        for i in range(start, end):
            # Get condition value - convert to boolean properly
            cond_val = 0.0
            if cond_has_array:
                try:
                    if i < len(cond):
                        cond_val = cond[i]
                    elif len(cond) > 0:
                        cond_val = cond[-1]  # Use last value if index out of bounds
                except (IndexError, TypeError):
                    pass
            else:
                # Fallback: try to get value directly from cond object
                try:
                    cond_val = self.cond[i] if hasattr(self.cond, "__getitem__") else 0.0
                except Exception:
                    cond_val = 0.0

            # Convert to boolean: non-zero values are True, zero is False
            # Use explicit comparison to handle float precision issues
            cond_bool = (cond_val != 0.0) and (
                not (isinstance(cond_val, float) and math.isnan(cond_val))
            )

            # Get a value - use constant if detected, otherwise array
            if a_is_constant:
                a_val = a_constant_val
            elif a_has_array:
                try:
                    if i < len(srca):
                        a_val = srca[i]
                    elif len(srca) > 0:
                        a_val = srca[-1]
                    else:
                        a_val = 0.0
                except (IndexError, TypeError):
                    a_val = 0.0
            else:
                a_val = 0.0

            # Get b value - use constant if detected, otherwise array
            if b_is_constant:
                b_val = b_constant_val
            elif b_has_array:
                try:
                    if i < len(srcb):
                        b_val = srcb[i]
                    elif len(srcb) > 0:
                        b_val = srcb[-1]
                    else:
                        b_val = 0.0
                except (IndexError, TypeError):
                    b_val = 0.0
            else:
                b_val = 0.0

            # Ensure values are not None or NaN
            if a_val is None or (isinstance(a_val, float) and math.isnan(a_val)):
                a_val = 0.0
            if b_val is None or (isinstance(b_val, float) and math.isnan(b_val)):
                b_val = 0.0

            # Select value based on condition
            dst[i] = a_val if cond_bool else b_val


# Apply one logic to multiple elements
class MultiLogic(Logic):
    """Base class for operations that apply a function to multiple arguments.

    The flogic attribute should be set to a callable that takes
    an iterable of values and returns a single result.
    """

    def next(self):
        """Apply the logic function to current values from all arguments."""
        self[0] = self.flogic([arg[0] for arg in self.args])

    def once(self, start, end):
        """Apply the logic function to all values across the specified range.

        Args:
            start: Starting index for calculation.
            end: Ending index for calculation.
        """
        # cache python dictionary lookups
        dst = self.array
        arrays = [arg.array for arg in self.args]
        flogic = self.flogic

        for i in range(start, end):
            dst[i] = flogic([arr[i] for arr in arrays])


# Mainly uses functools.partial to generate partial function, functools.reduce, iterates function on a sequence
class MultiLogicReduce(MultiLogic):
    """MultiLogic that uses functools.reduce for cumulative operations.

    This class applies a reduction function cumulatively to all arguments,
    combining them into a single result.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the reduction operation.

        Args:
            *args: Line objects or values to reduce.
            **kwargs: Optional keyword arguments including 'initializer'.
        """
        super().__init__(*args)
        if "initializer" not in kwargs:
            self.flogic = functools.partial(functools.reduce, self.flogic)
        else:
            self.flogic = functools.partial(
                functools.reduce, self.flogic, initializer=kwargs["initializer"]
            )


# Inheritance class, process flogic
class Reduce(MultiLogicReduce):
    """Generic reduction operation with a custom function.

    Allows any reduction function to be applied to the arguments.
    """

    def __init__(self, flogic, *args, **kwargs):
        """Initialize the custom reduction operation.

        Args:
            flogic: Function to use for reduction.
            *args: Line objects or values to reduce.
            **kwargs: Optional keyword arguments.
        """
        self.flogic = flogic
        super().__init__(*args, **kwargs)


# The _xxxlogic functions are defined at module scope to make them
# pickable and therefore compatible with multiprocessing


# Determine if both x and y are True
def _andlogic(x, y):
    """Logical AND operation for reduction."""
    return bool(x and y)


# Determine if all elements are True
class And(MultiLogicReduce):
    """Logical AND operation across all arguments.

    Returns True only if all input values are truthy.
    """

    flogic = staticmethod(_andlogic)


# Determine if either x or y is true
def _orlogic(x, y):
    """Logical OR operation for reduction."""
    return bool(x or y)


# Determine if any element in the sequence is true
class Or(MultiLogicReduce):
    """Logical OR operation across all arguments.

    Returns True if any input value is truthy.
    """

    flogic = staticmethod(_orlogic)


# Find maximum value
class Max(MultiLogic):
    """Maximum operation across all arguments.

    Returns the maximum value from all input lines.
    """

    flogic = max


# Find minimum value
class Min(MultiLogic):
    """Minimum operation across all arguments.

    Returns the minimum value from all input lines.
    """

    flogic = min


# Calculate sum
class Sum(MultiLogic):
    """Sum operation across all arguments.

    Returns the sum of all input values using math.fsum
    for better floating point precision.
    """

    flogic = math.fsum


# Check if any exists
class Any(MultiLogic):
    """Any operation across all arguments.

    Returns True if any input value is truthy.
    """

    flogic = any


# Check if all
class All(MultiLogic):
    """All operation across all arguments.

    Returns True only if all input values are truthy.
    """

    flogic = all
