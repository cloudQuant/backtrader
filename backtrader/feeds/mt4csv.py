#!/usr/bin/env python
"""MetaTrader 4 CSV Data Feed Module - MT4 CSV parsing.

This module provides the MT4CSVData feed for parsing MetaTrader 4
History Center exported CSV files.

Classes:
    MT4CSVData: Parses MT4 CSV format files.

Example:
    >>> data = bt.feeds.MT4CSVData(dataname='mt4_data.csv')
    >>> cerebro.adddata(data)
"""

from . import GenericCSVData


class MT4CSVData(GenericCSVData):
    """
    Parses a `Metatrader4 <https://www.metaquotes.net/en/metatrader4>`_ History
    center CSV exported file.

    Specific parameters (or specific meaning):

      - ``dataname``: The filename to parse or a file-like object

      - Uses GenericCSVData and simply modifies the params
    """

    # MT4 data class inheriting from CSV, only modifies parameters
    params = (
        ("dtformat", "%Y.%m.%d"),
        ("tmformat", "%H:%M"),
        ("datetime", 0),
        ("time", 1),
        ("open", 2),
        ("high", 3),
        ("low", 4),
        ("close", 5),
        ("volume", 6),
        ("openinterest", -1),
    )
