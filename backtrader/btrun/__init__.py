#!/usr/bin/env python
"""BtRun Module - Command-line interface for backtrader.

This module provides the btrun command-line tool for running backtrader
scripts from the command line without writing Python code.

Example:
    Running from command line:
    $ btrun --strategy MyStrategy --data data.csv
"""

from .btrun import btrun as btrun
