#!/usr/bin/env python
"""Sierra Chart CSV Data Feed Module - SierraChart CSV parsing.

This module provides the SierraChartCSVData feed for parsing
Sierra Chart exported CSV files.

Classes:
    SierraChartCSVData: Parses SierraChart CSV format files.

Example:
    >>> data = bt.feeds.SierraChartCSVData(dataname='sierra.csv')
    >>> cerebro.adddata(data)
"""

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
