#!/usr/bin/env python
from . import GenericCSVData


#  时间格式是'%Y/%m/%d'的读取方式
class SierraChartCSVData(GenericCSVData):
    """
    Parses a `SierraChart <http://www.sierrachart.com>`_ CSV exported file.

    Specific parameters (or specific meaning):

      - ``dataname``: The filename to parse or a file-like object

      - Uses GenericCSVData and simply modifies the dateformat (dtformat) to
    """

    params = (("dtformat", "%Y/%m/%d"),)
