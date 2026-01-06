#!/usr/bin/env python
from . import GenericCSVData


# Read format with time format '%Y/%m/%d'
class SierraChartCSVData(GenericCSVData):
    """
    Parses a `SierraChart <http://www.sierrachart.com>`_ CSV exported file.

    Specific parameters (or specific meaning):

      - ``dataname``: The filename to parse or a file-like object

      - Uses GenericCSVData and simply modifies the dateformat (dtformat) to
    """

    params = (("dtformat", "%Y/%m/%d"),)
