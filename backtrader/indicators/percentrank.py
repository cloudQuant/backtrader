#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from math import fsum

from . import BaseApplyN


__all__ = ["PercentRank", "PctRank"]


# 计算百分比排序，如果依次升高，值是0，如果依次下降，值是1
class PercentRank(BaseApplyN):
    """
    Measures the percent rank of the current value with respect to that of
    period bars ago
    """

    alias = ("PctRank",)
    lines = ("pctrank",)
    params = (
        ("period", 50),
        ("func", lambda d: fsum(x < d[-1] for x in d) / len(d)),
    )


PctRank = PercentRank
