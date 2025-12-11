#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import functools
import itertools
import math

from .linebuffer import LineActions
from .utils.py3 import cmp, range


# Generate a List equivalent which uses "is" for contains
# 创建一个新的List类,改写了__contains__方法,如果list中有一个元素的哈希值等于other的哈希值，那么就返回True
class List(list):
    def __contains__(self, other):
        return any(x.__hash__() == other.__hash__() for x in self)


# 创建一个类，把其中的元素进行序列化
class Logic(LineActions):
    def __init__(self, *args):
        super(Logic, self).__init__()
        self.args = [self.arrayize(arg) for arg in args]


# 避免两个line想除的时候有值是0，如果分母是0,除以得到的值是0
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
        super(DivByZero, self).__init__(a, b)
        self.a = a
        self.b = b
        self.zero = zero

    def next(self):
        b = self.b[0]
        self[0] = self.a[0] / b if b else self.zero

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b.array
        zero = self.zero

        for i in range(start, end):
            b = srcb[i]
            dst[i] = srca[i] / b if b else zero


# 考虑分母分子都可能是0的两个line的想除操作
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
        super(DivZeroByZero, self).__init__(a, b)
        self.a = a
        self.b = b
        self.single = single
        self.dual = dual

    def next(self):
        b = self.b[0]
        a = self.a[0]
        if b == 0.0:
            self[0] = self.dual if a == 0.0 else self.single
        else:
            self[0] = self.a[0] / b

    def once(self, start, end):
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


# 对比a和b,a和b很可能是line
class Cmp(Logic):
    def __init__(self, a, b):
        super(Cmp, self).__init__(a, b)
        self.a = self.args[0]
        self.b = self.args[1]

    def next(self):
        self[0] = cmp(self.a[0], self.b[0])

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b.array

        for i in range(start, end):
            dst[i] = cmp(srca[i], srcb[i])


# 对比两个line,a和b，a<b的时候，返回r1相应的值，a=b的时候，返回r2相应的值，a>b的时候，返回r3相应的值
# todo 在backtrader量化交流群中有一个朋友指出了这个问题
class CmpEx(Logic):
    def __init__(self, a, b, r1, r2, r3):
        super(CmpEx, self).__init__(a, b, r1, r2, r3)
        self.a = self.args[0]
        self.b = self.args[1]
        self.r1 = self.args[2]
        self.r2 = self.args[3]
        self.r3 = self.args[4]

    def next(self):
        # self[0] = cmp(self.a[0], self.b[0])
        if self.a[0] < self.b[0]:
            self[0] = self.r1[0]
        elif self.a[0] > self.b[0]:
            self[0] = self.r3[0]
        else:
            self[0] = self.r2[0]

    def once(self, start, end):
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


# if判断，对于cond满足的时候，返回a相应的值，不满足的时候，返回b相应的值
class If(Logic):
    def __init__(self, cond, a, b):
        super(If, self).__init__(a, b)
        self.a = self.args[0]
        self.b = self.args[1]
        self.cond = self.arrayize(cond)

    def next(self):
        self[0] = self.a[0] if self.cond[0] else self.b[0]

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.array

        # CRITICAL FIX: Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        # CRITICAL FIX: Try to get arrays, but also prepare fallback to direct access
        # Also, if arrays are empty, try to manually process the source objects
        try:
            srca = self.a.array
            a_has_array = True
            # If array is empty, try to manually process the source object
            if len(srca) == 0 and hasattr(self.a, "_once"):
                try:
                    # Try to process the source object manually
                    self.a._once(start, end)
                    srca = self.a.array
                except Exception:
                    pass
        except (AttributeError, TypeError):
            srca = []
            a_has_array = False

        try:
            srcb = self.b.array
            b_has_array = True
            # If array is empty, try to manually process the source object
            if len(srcb) == 0 and hasattr(self.b, "_once"):
                try:
                    # Try to process the source object manually
                    self.b._once(start, end)
                    srcb = self.b.array
                except Exception:
                    pass
        except (AttributeError, TypeError):
            srcb = []
            b_has_array = False

        try:
            cond = self.cond.array
            cond_has_array = True
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

            # Get a value
            a_val = None
            a_val_set = False
            if a_has_array:
                try:
                    if i < len(srca):
                        a_val = srca[i]
                        a_val_set = True
                    elif len(srca) > 0:
                        a_val = srca[-1]  # Use last value if index out of bounds
                        a_val_set = True
                except (IndexError, TypeError):
                    pass
            # Fallback: try to get value directly from a object if array didn't work
            if not a_val_set:
                try:
                    if hasattr(self.a, "__getitem__"):
                        a_val = self.a[0]  # Try to get current value
                        a_val_set = True
                    elif hasattr(self.a, "a") and hasattr(self.a.a, "wrapped"):
                        # Try to extract constant from PseudoArray
                        wrapped = self.a.a.wrapped
                        if isinstance(wrapped, itertools.repeat):
                            a_val = next(iter(wrapped))
                            a_val_set = True
                except Exception:
                    pass
            if a_val is None:
                a_val = 0.0

            # Get b value
            b_val = None
            b_val_set = False
            if b_has_array:
                try:
                    if i < len(srcb):
                        b_val = srcb[i]
                        b_val_set = True
                    elif len(srcb) > 0:
                        b_val = srcb[-1]  # Use last value if index out of bounds
                        b_val_set = True
                except (IndexError, TypeError):
                    pass
            # Fallback: try to get value directly from b object if array didn't work
            if not b_val_set:
                try:
                    if hasattr(self.b, "__getitem__"):
                        b_val = self.b[0]  # Try to get current value
                        b_val_set = True
                    elif hasattr(self.b, "a") and hasattr(self.b.a, "wrapped"):
                        # Try to extract constant from PseudoArray
                        wrapped = self.b.a.wrapped
                        if isinstance(wrapped, itertools.repeat):
                            b_val = next(iter(wrapped))
                            b_val_set = True
                except Exception:
                    pass
            if b_val is None:
                b_val = 0.0

            # Ensure values are not None or NaN
            if a_val is None or (isinstance(a_val, float) and math.isnan(a_val)):
                a_val = 0.0
            if b_val is None or (isinstance(b_val, float) and math.isnan(b_val)):
                b_val = 0.0

            # Select value based on condition
            dst[i] = a_val if cond_bool else b_val


# 一个逻辑应用到多个元素上
class MultiLogic(Logic):
    def next(self):
        self[0] = self.flogic([arg[0] for arg in self.args])

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        arrays = [arg.array for arg in self.args]
        flogic = self.flogic

        for i in range(start, end):
            dst[i] = flogic([arr[i] for arr in arrays])


# 主要是调用了functools.partial生成偏函数，functools.reduce,对一个sequence迭代使用function
class MultiLogicReduce(MultiLogic):
    def __init__(self, *args, **kwargs):
        super(MultiLogicReduce, self).__init__(*args)
        if "initializer" not in kwargs:
            self.flogic = functools.partial(functools.reduce, self.flogic)
        else:
            self.flogic = functools.partial(
                functools.reduce, self.flogic, initializer=kwargs["initializer"]
            )


# 继承类，对flogic进行处理
class Reduce(MultiLogicReduce):
    def __init__(self, flogic, *args, **kwargs):
        self.flogic = flogic
        super(Reduce, self).__init__(*args, **kwargs)


# The _xxxlogic functions are defined at module scope to make them
# pickable and therefore compatible with multiprocessing


# 判断x和y是不是都是True
def _andlogic(x, y):
    return bool(x and y)


# 判断是否是所有的元素都是True的
class And(MultiLogicReduce):
    flogic = staticmethod(_andlogic)


# 判断x或者y中有没有一个是真的
def _orlogic(x, y):
    return bool(x or y)


# 判断序列中是否有一个是真的
class Or(MultiLogicReduce):
    flogic = staticmethod(_orlogic)


# 求最大值
class Max(MultiLogic):
    flogic = max


# 求最小值
class Min(MultiLogic):
    flogic = min


# 求和
class Sum(MultiLogic):
    flogic = math.fsum


# 是否有一个
class Any(MultiLogic):
    flogic = any


# 是否所有的
class All(MultiLogic):
    flogic = all
