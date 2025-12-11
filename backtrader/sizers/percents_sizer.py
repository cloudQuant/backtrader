#!/usr/bin/env python

from ..parameters import Float, ParameterDescriptor
from ..sizer import Sizer

__all__ = ["PercentSizer", "AllInSizer", "PercentSizerInt", "AllInSizerInt"]


# 百分比手数，根据可以利用的现金的百分比下单
class PercentSizer(Sizer):
    """This sizer return percentages of available cash

    This class has been refactored from legacy params tuple to the new
    ParameterDescriptor system for Day 36-38 of the metaprogramming removal project.

    Params:
      - ``percents`` (default: ``20``)
      - ``retint`` (default: ``False``) return an int size or rather the float value
    """

    # 使用新的参数描述符系统定义参数
    percents = ParameterDescriptor(
        default=20,
        type_=float,
        validator=Float(min_val=0.0, max_val=100.0),
        doc="Percentage of available cash to use",
    )
    retint = ParameterDescriptor(
        default=False, type_=bool, doc="Return an int size or rather the float value"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # 如果当前没有持仓，根据现金的百分比计算可以下单的数目
    # 如果当前有持仓，根据，直接使用持仓的大小作为下单的手数
    # 如果需要转化成整数，那么就转化为整数
    def _getsizing(self, comminfo, cash, data, isbuy):
        position = self.broker.getposition(data)
        if not position:
            size = cash / data.close[0] * (self.get_param("percents") / 100)
        else:
            size = position.size

        if self.get_param("retint"):
            size = int(size)

        return size


# 利用所有的现金进行下单
class AllInSizer(PercentSizer):
    """This sizer return all available cash of broker

    Params:
      - ``percents`` (default: ``100``)
    """

    # 重新定义percents参数的默认值
    percents = ParameterDescriptor(
        default=100,
        type_=float,
        validator=Float(min_val=0.0, max_val=100.0),
        doc="Percentage of available cash to use (100% for all-in)",
    )


# 按照百分比进行计算下单的手数，然后要取整
class PercentSizerInt(PercentSizer):
    """This sizer return percentages of available cash in the form of size truncated
    to an int

    Params:
      - ``percents`` (default: ``20``)
    """

    # 重新定义retint参数的默认值
    retint = ParameterDescriptor(
        default=True, type_=bool, doc="Return an int size or rather the float value (True for int)"
    )


# 根据所有的现金进行下单，手数要取整
class AllInSizerInt(PercentSizerInt):
    """This sizer returns all available cash of broker with the
    size truncated to an int

     Params:
       - ``percents`` (default: ``100``)
    """

    # 重新定义percents参数的默认值
    percents = ParameterDescriptor(
        default=100,
        type_=float,
        validator=Float(min_val=0.0, max_val=100.0),
        doc="Percentage of available cash to use (100% for all-in)",
    )
