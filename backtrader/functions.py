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
import logging
import math

from .linebuffer import LineActions
from .utils.py3 import cmp, range

logger = logging.getLogger(__name__)


def _sanitize_cmp_value(value):
    if value is None:
        return 0.0

    if isinstance(value, float) and not math.isfinite(value):
        return 0.0

    return value


def _sanitize_div_value(value):
    if value is None:
        return 0.0

    if isinstance(value, float) and not math.isfinite(value):
        return 0.0

    return value


def _sanitize_numeric_values(values):
    return [_sanitize_div_value(value) for value in values]


def _value_at(array, index, default=0.0):
    try:
        return array[index]
    except (IndexError, TypeError):
        try:
            return array[-1]
        except (IndexError, TypeError):
            return default


def _maxlogic(values):
    return max(_sanitize_numeric_values(values))


def _minlogic(values):
    return min(_sanitize_numeric_values(values))


def _sumlogic(values):
    return math.fsum(_sanitize_numeric_values(values))


# Generate a List equivalent which uses "is" for contains
# Create a new List class, overriding __contains__ method, if any element in list has hash value equal to other's hash value, return True
class List(list):
    """List subclass that uses hash equality for contains checks.

    This class overrides __contains__ to check if any element has
    the same hash value as the target, rather than using identity comparison.
    """

    def __contains__(self, other):
        return any(x is other for x in self)


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

    def _next(self):
        self.advance()
        self.next()
        for binding in self.bindings:
            binding[0] = self[0]


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
        self.a = self.args[0]
        self.b = self.args[1]
        self.zero = zero

    def next(self):
        """Calculate the next value with zero-division protection."""
        a = _sanitize_div_value(self.a[0])
        b = _sanitize_div_value(self.b[0])
        self[0] = a / b if b else self.zero

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

        # Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        for i in range(start, end):
            a = _sanitize_div_value(_value_at(srca, i))
            b = _sanitize_div_value(_value_at(srcb, i))
            dst[i] = a / b if b else zero


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
        self.a = self.args[0]
        self.b = self.args[1]
        self.single = single
        self.dual = dual

    def next(self):
        """Calculate the next value with zero/zero indetermination protection."""
        b = _sanitize_div_value(self.b[0])
        a = _sanitize_div_value(self.a[0])
        if b == 0.0:
            self[0] = self.dual if a == 0.0 else self.single
        else:
            self[0] = a / b

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

        # Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        for i in range(start, end):
            b = _sanitize_div_value(_value_at(srcb, i))
            a = _sanitize_div_value(_value_at(srca, i))
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
        self[0] = cmp(_sanitize_cmp_value(self.a[0]), _sanitize_cmp_value(self.b[0]))

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

        # Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        for i in range(start, end):
            dst[i] = cmp(
                _sanitize_cmp_value(_value_at(srca, i)),
                _sanitize_cmp_value(_value_at(srcb, i)),
            )


# Compare two lines, a and b, return corresponding r1 value when a<b, return r2 value when a=b, return r3 value when a>b
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
        a0 = _sanitize_cmp_value(self.a[0])
        b0 = _sanitize_cmp_value(self.b[0])

        if a0 < b0:
            self[0] = _sanitize_div_value(self.r1[0])
        elif a0 > b0:
            self[0] = _sanitize_div_value(self.r3[0])
        else:
            self[0] = _sanitize_div_value(self.r2[0])

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

        # Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        for i in range(start, end):
            ai = _sanitize_cmp_value(_value_at(srca, i))
            bi = _sanitize_cmp_value(_value_at(srcb, i))

            if ai < bi:
                dst[i] = _sanitize_div_value(_value_at(r1, i))
            elif ai > bi:
                dst[i] = _sanitize_div_value(_value_at(r3, i))
            else:
                dst[i] = _sanitize_div_value(_value_at(r2, i))


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
        super().__init__(cond, a, b)
        self.cond = self.args[0]
        self.a = self.args[1]
        self.b = self.args[2]

    def next(self):
        """Calculate the next conditional value."""
        cond_val = _sanitize_div_value(self.cond[0])
        value = self.a[0] if cond_val else self.b[0]
        self[0] = _sanitize_div_value(value)

    def _has_self_reference(self):
        """Check if this If operation has a self-referencing pattern.

        Detects patterns like: self.lines.direction = bt.If(..., direction(-1))
        where the output line appears as an input via _LineDelay.
        """
        if not self.bindings:
            return False

        # Get the bound line(s)
        bound_lines = set(id(b) for b in self.bindings)

        # Check if any operand references a bound line (via _LineDelay)
        def _check_ref(obj, depth=0):
            if depth > 10:
                return False
            if hasattr(obj, 'a'):
                # _LineDelay: check if obj.a is one of our bound lines
                if id(getattr(obj, 'a', None)) in bound_lines:
                    return True
                # Check if obj.a's array is the same as a bound line's array
                obj_a = getattr(obj, 'a', None)
                if obj_a is not None:
                    for binding in self.bindings:
                        if hasattr(obj_a, 'array') and hasattr(binding, 'array'):
                            if obj_a.array is binding.array:
                                return True
                    if _check_ref(obj_a, depth + 1):
                        return True
            if hasattr(obj, 'b'):
                obj_b = getattr(obj, 'b', None)
                if obj_b is not None:
                    if id(obj_b) in bound_lines:
                        return True
                    if hasattr(obj_b, 'array'):
                        for binding in self.bindings:
                            if hasattr(binding, 'array') and obj_b.array is binding.array:
                                return True
                    if _check_ref(obj_b, depth + 1):
                        return True
            if hasattr(obj, 'args'):
                for arg in getattr(obj, 'args', []):
                    if _check_ref(arg, depth + 1):
                        return True
            if hasattr(obj, 'cond'):
                if _check_ref(getattr(obj, 'cond', None), depth + 1):
                    return True
            return False

        return _check_ref(self.a) or _check_ref(self.b) or _check_ref(self.cond)

    def once(self, start, end):
        """Calculate all conditional values at once.

        Supports self-referencing patterns like:
            self.lines.direction = bt.If(cond, 1, bt.If(cond2, -1, self.lines.direction(-1)))

        For self-referencing patterns, processes bar-by-bar using next() semantics
        to ensure previously computed values are available for the next bar.

        Args:
            start: Starting index for calculation.
            end: Ending index for calculation.
        """
        dst = self.array

        # Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        # Also ensure bound line arrays are sized
        for binding in self.bindings:
            while len(binding.array) < end:
                binding.array.append(0.0)

        # For self-referencing patterns, use bar-by-bar processing
        # This ensures _LineDelay can read previously computed values
        if self.bindings and self._has_self_reference():
            self._once_sequential(start, end)
            return

        # Standard If expressions can contain nested LinesOperation/_LineDelay
        # operands which are not always scheduled separately by LineIterator.
        # Compute them explicitly before reading their arrays below.
        for operand in (self.cond, self.a, self.b):
            if hasattr(operand, 'once') and len(getattr(operand, 'array', [])) < end:
                try:
                    operand.once(0, end)
                except Exception as e:
                    logger.debug("If operand once() failed: %s", e)

        # Standard batch processing for non-self-referencing patterns
        self._once_batch(start, end)

    def _once_sequential(self, start, end):
        """Process bar-by-bar for self-referencing patterns.

        Ensures all operand arrays are computed first, then processes
        sequentially with immediate binding propagation so _LineDelay
        can read previously written values.
        """
        dst = self.array
        has_bindings = bool(self.bindings)

        # Ensure operand arrays are computed first
        # The condition (LinesOperation) needs its once() called
        if hasattr(self.cond, 'once') and len(getattr(self.cond, 'array', [])) < end:
            try:
                self.cond.once(start, end)
            except Exception:
                pass

        # The 'a' operand (could be constant or LinesOperation)
        if hasattr(self.a, 'once') and len(getattr(self.a, 'array', [])) < end:
            try:
                self.a.once(start, end)
            except Exception:
                pass

        # The 'b' operand - for self-referencing, this is typically another bt.If
        # We need to compute it BUT it contains the self-reference, so we handle it specially
        if hasattr(self.b, 'once') and len(getattr(self.b, 'array', [])) < end:
            # Check if b itself has self-reference (nested bt.If with direction(-1))
            # If so, we need to compute b bar-by-bar too
            if hasattr(self.b, '_has_self_reference') and self.b._has_self_reference():
                # Don't call b.once() - we'll compute b[i] dynamically
                pass
            else:
                try:
                    self.b.once(start, end)
                except Exception:
                    pass

        # Get arrays for direct access where possible
        cond_array = getattr(self.cond, 'array', [])
        cond_has_array = len(cond_array) >= end
        a_array = getattr(self.a, 'array', [])
        a_has_array = len(a_array) >= end
        # Check if a is a constant (_LineDelay wrapping PseudoArray)
        a_is_constant = False
        a_constant_val = None
        if not a_has_array:
            try:
                a_constant_val = self.a[0]
                a_is_constant = True
            except Exception:
                pass

        b_array = getattr(self.b, 'array', [])
        b_has_array = len(b_array) >= end

        for i in range(start, end):
            # Get condition value
            if cond_has_array:
                cond_val = cond_array[i]
            else:
                try:
                    cond_val = self.cond.array[i] if i < len(getattr(self.cond, 'array', [])) else 0.0
                except (IndexError, TypeError):
                    cond_val = 0.0

            cond_bool = (cond_val != 0.0) and (
                not (isinstance(cond_val, float) and math.isnan(cond_val))
            )

            if cond_bool:
                # Get a value
                if a_is_constant:
                    val = a_constant_val
                elif a_has_array:
                    val = a_array[i]
                else:
                    try:
                        val = self.a.array[i] if i < len(getattr(self.a, 'array', [])) else 0.0
                    except (IndexError, TypeError):
                        val = 0.0
            else:
                # Get b value - for self-referencing, b is the inner bt.If
                # which reads from _LineDelay(direction, -1)
                if b_has_array:
                    val = b_array[i]
                else:
                    # b's array isn't fully computed - compute dynamically
                    # For nested bt.If with self-reference, we need to evaluate it
                    try:
                        val = self._eval_operand_at(self.b, i)
                    except Exception:
                        val = 0.0

            val = _sanitize_div_value(val)

            dst[i] = val

            # Propagate to bindings immediately for self-referencing
            if has_bindings:
                for binding in self.bindings:
                    binding.array[i] = val

    def _eval_operand_at(self, operand, i):
        """Evaluate an operand at absolute index i.

        For nested bt.If with self-reference, recursively evaluates
        the condition and branches at the given index.
        """
        if isinstance(operand, If):
            # Recursively evaluate the nested If
            # Get condition
            cond_arr = getattr(operand.cond, 'array', [])
            if i < len(cond_arr):
                cond_val = cond_arr[i]
            else:
                cond_val = 0.0

            cond_bool = (cond_val != 0.0) and (
                not (isinstance(cond_val, float) and math.isnan(cond_val))
            )

            if cond_bool:
                return self._eval_operand_at(operand.a, i)
            else:
                return self._eval_operand_at(operand.b, i)

        # For _LineDelay, read from its source array at offset
        if hasattr(operand, 'ago') and hasattr(operand, 'a'):
            src_array = getattr(operand.a, 'array', [])
            src_idx = i + operand.ago
            if 0 <= src_idx < len(src_array):
                return src_array[src_idx]
            return 0.0

        # For arrays, direct access
        arr = getattr(operand, 'array', [])
        if i < len(arr):
            return arr[i]

        # Constant
        try:
            return operand[0]
        except Exception:
            return 0.0

    def _once_batch(self, start, end):
        """Standard batch processing for non-self-referencing patterns."""
        dst = self.array

        # Detect constants
        a_is_constant = False
        a_constant_val = None
        try:
            srca = self.a.array
            a_has_array = len(srca) > 0
            if not a_has_array:
                try:
                    a_constant_val = self.a[0]
                    a_is_constant = True
                except Exception:
                    pass
        except (AttributeError, TypeError):
            srca = []
            a_has_array = False
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
                try:
                    b_constant_val = self.b[0]
                    b_is_constant = True
                except Exception:
                    pass
        except (AttributeError, TypeError):
            srcb = []
            b_has_array = False
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

        a_use_dynamic = not a_is_constant and not a_has_array and hasattr(self.a, "__getitem__")
        b_use_dynamic = not b_is_constant and not b_has_array and hasattr(self.b, "__getitem__")
        has_bindings = bool(self.bindings)

        for i in range(start, end):
            if cond_has_array:
                try:
                    cond_val = cond[i] if i < len(cond) else (cond[-1] if cond else 0.0)
                except (IndexError, TypeError):
                    cond_val = 0.0
            else:
                try:
                    cond_val = self.cond[i] if hasattr(self.cond, "__getitem__") else 0.0
                except Exception:
                    cond_val = 0.0

            cond_bool = (cond_val != 0.0) and (
                not (isinstance(cond_val, float) and math.isnan(cond_val))
            )

            if a_is_constant:
                a_val = a_constant_val
            elif a_has_array:
                try:
                    a_val = srca[i] if i < len(srca) else (srca[-1] if srca else 0.0)
                except (IndexError, TypeError):
                    a_val = 0.0
            elif a_use_dynamic:
                try:
                    a_val = self.a[i]
                except Exception:
                    a_val = 0.0
            else:
                a_val = 0.0

            if b_is_constant:
                b_val = b_constant_val
            elif b_has_array:
                try:
                    b_val = srcb[i] if i < len(srcb) else (srcb[-1] if srcb else 0.0)
                except (IndexError, TypeError):
                    b_val = 0.0
            elif b_use_dynamic:
                try:
                    b_val = self.b[i]
                except Exception:
                    b_val = 0.0
            else:
                b_val = 0.0

            a_val = _sanitize_div_value(a_val)
            b_val = _sanitize_div_value(b_val)

            val = a_val if cond_bool else b_val
            dst[i] = val

            # Propagate to bindings for consistency
            if has_bindings:
                for binding in self.bindings:
                    binding.array[i] = val


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

        # Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        arrays = [arg.array for arg in self.args]
        flogic = self.flogic

        for i in range(start, end):
            dst[i] = flogic([_value_at(arr, i) for arr in arrays])


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

    flogic = staticmethod(_maxlogic)


# Find minimum value
class Min(MultiLogic):
    """Minimum operation across all arguments.

    Returns the minimum value from all input lines.
    """

    flogic = staticmethod(_minlogic)


# Calculate sum
class Sum(MultiLogic):
    """Sum operation across all arguments.

    Returns the sum of all input values using math.fsum
    for better floating point precision.
    """

    flogic = staticmethod(_sumlogic)


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
