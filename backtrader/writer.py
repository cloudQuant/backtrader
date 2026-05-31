#!/usr/bin/env python
"""Writer Module - Output writing for strategy execution results.

This module provides classes for writing strategy execution results
to files or stdout. It supports CSV output and custom formatting.

Classes:
    WriterBase: Base class for writers.
    WriterFile: Writes execution results to file or stdout.

Example:
    Using WriterFile with cerebro:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addwriter(bt.WriterFile, out='results.csv', csv=True)
    >>> results = cerebro.run()
"""

import io
import itertools
import sys
from collections.abc import Iterable
from typing import List, Optional, Union, cast

from .lineseries import LineSeries
from .parameters import ParameterizedBase
from .utils.py3 import integer_types, map, string_types


# WriterBase class - refactored to not use metaclass
class WriterBase(ParameterizedBase):
    """Base class for writers.

    This is the base class for all writer implementations.
    Subclasses should override the writing methods to provide
    custom output formatting.
    """


# WriterFile class - refactored to not use metaclass
class WriterFile(WriterBase):
    """The system-wide writer class.

    Writes strategy execution results to a file or stdout.

    Params:
        out: Output stream (default: sys.stdout). If a string is passed,
            it's treated as a filename. Use None for multiprocess optimization.
        close_out: If True, explicitly close the output stream (default: False).
        csv: If True, write CSV data during execution (default: False).
        csv_filternan: If True, replace NaN values with empty fields (default: True).
        csvsep: CSV separator character (default: ',').
        indent: Indentation for formatted output (default: 2).

    Example:
        >>> cerebro.addwriter(bt.WriterFile, out='results.csv', csv=True)
    """

    params = (  # type: ignore[assignment]
        ("out", None),
        ("close_out", False),
        ("csv", False),
        ("csvsep", ","),
        ("csv_filternan", True),
        ("csv_counter", True),
        ("indent", 2),
        ("separators", ["=", "-", "+", "*", ".", "~", '"', "^", "#"]),
        ("seplen", 79),
        ("rounding", None),
    )

    # Initialize
    def __init__(self, **kwargs):
        """Initialize the WriterFile instance.

        Sets up the counter, headers list, and values list for tracking
        data during execution.

        Args:
            **kwargs: Keyword arguments for writer parameters.
        """
        # Initialize parent class first
        super().__init__(**kwargs)
        # _len is a counter
        # CRITICAL FIX: Change counter start value from 1 to 0 to match test expectations
        # This fixes assertion error in test_writer.py: assert count == 256
        self._len: "itertools.count[int]" = itertools.count(0)
        # headers
        self.headers: List[str] = []
        # values
        self.values: List[str] = []
        # out and close_out are set in _start_output when start() is called
        self.out: Optional[Union[io.TextIOBase, io.TextIOWrapper]] = None
        self.close_out: bool = True

    # Start output
    def _start_output(self):
        # open file if needed
        # If there's no out attribute or self.out is None
        if not hasattr(self, "out") or not self.out:
            # If out parameter is None, set out to standard output, and close_out to False
            if self.p.out is None:
                self.out = cast(Union[io.TextIOBase, io.TextIOWrapper], sys.stdout)
                self.close_out = False
            # If self.p.out is a string_types, open file in write mode, close_out needs to be True
            elif isinstance(self.p.out, string_types):
                self.out = cast(
                    Union[io.TextIOBase, io.TextIOWrapper],
                    open(self.p.out, "w"),
                )
                self.close_out = True
            # If self.p.out is neither None nor string format, self.out equals self.p.out
            else:
                self.out = cast(Union[io.TextIOBase, io.TextIOWrapper], self.p.out)
                self.close_out = self.p.close_out

    # Start
    def start(self):
        """Initialize the writer at the start of execution.

        Opens the output file/stream and writes CSV headers if CSV mode
        is enabled.
        """
        # Call _start_output to prepare for output
        self._start_output()
        # If csv is True
        if self.p.csv:
            # Write line separator
            self.writelineseparator()
            # Write column names to file, first column defaults to Id
            self.writeiterable(self.headers, counter="Id")

    # Stop, if close_out is True, close self.out
    def stop(self):
        """Close the output stream when execution ends.

        Closes the output file if close_out parameter is True.
        """
        if self.close_out and self.out is not None:
            try:
                self.out.close()
            except OSError:
                # Stream already closed or not closable; nothing more to do.
                pass

    def __enter__(self):
        """Support context manager protocol."""
        self._start_output()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensure output stream is closed when exiting context."""
        self.stop()
        return False

    # If csv is True, save values to self.out each time, and set self.values to empty list
    def next(self):
        """Write accumulated values to output.

        Called during execution to write the current set of values
        to the CSV output and reset the values list.
        """
        if self.p.csv:
            self.writeiterable(self.values, func=str, counter=next(self._len))
            self.values = []

    # If csv is True, add column names
    def addheaders(self, headers):
        """Add column headers for CSV output.

        Args:
            headers: List of header names to add.
        """
        if self.p.csv:
            self.headers.extend(headers)

    # If csv is True and need to filter nan, replace nan with '', and add values to self.values
    def addvalues(self, values):
        """Add values to be written to CSV output.

        Args:
            values: Iterable of values to add.
        """
        if self.p.csv:
            if self.p.csv_filternan:
                values = map(lambda x: x if x == x else "", values)
            self.values.extend(values)

    # Process iterable objects and write to standard output or csv file
    def writeiterable(self, iterable, func=None, counter=""):
        """Write an iterable to the output as a CSV line.

        Args:
            iterable: The data to write.
            func: Optional function to apply to each element.
            counter: Optional counter value to prepend.
        """
        # If saving csv counter, add counter before iterable
        if self.p.csv_counter:
            iterable = itertools.chain([counter], iterable)
        # If func is not None, apply func to iterable
        if func is not None:
            iterable = map(lambda x: func(x), iterable)
        # Separate iterable with csv separator to form line
        line = self.p.csvsep.join(iterable)
        # Write line to self.out
        self.writeline(line)

    # Write line to self.out
    def writeline(self, line):
        """Write a single line to the output.

        Args:
            line: The line content to write.
        """
        if self.out is None:
            raise RuntimeError("Writer output not initialized; call start() first")
        self.out.write(line + "\n")

    # Write multiple lines to self.out
    def writelines(self, lines):
        """Write multiple lines to the output.

        Args:
            lines: Iterable of line contents to write.
        """
        if self.out is None:
            raise RuntimeError("Writer output not initialized; call start() first")
        for line in lines:
            self.out.write(line + "\n")

    # Write line separator
    def writelineseparator(self, level=0):
        """Write a separator line for visual formatting.

        Args:
            level: Indentation level that determines separator style.
        """
        # Decide which separator to use, default is first separator "="
        sepnum = level % len(self.p.separators)
        separator = self.p.separators[sepnum]
        # Leading spaces, defaults to 0
        line = " " * (level * self.p.indent)
        # Entire line content
        line += separator * (self.p.seplen - (level * self.p.indent))
        self.writeline(line)

    # Write dictionary
    def writedict(self, dct, level=0, recurse=False):
        """Write a dictionary to the output with formatting.

        Args:
            dct: Dictionary to write.
            level: Indentation level for nested output.
            recurse: Whether this is a recursive call.
        """
        # If not recursing, write line separator
        if not recurse:
            self.writelineseparator(level)
        # First line indentation
        indent0 = level * self.p.indent
        # Iterate dictionary
        for key, val in dct.items():
            # First line spaces
            kline = " " * indent0
            # If recursing, add a character '- '
            if recurse:
                kline += "- "
            # Add a key :
            kline += str(key) + ":"
            # Check if val is a subclass of lineseries
            try:
                sclass = issubclass(val, LineSeries)
            except TypeError:
                sclass = False
            # If subclass, add a space, add val name
            if sclass:
                kline += " " + val.__name__
                self.writeline(kline)
            # If string
            elif isinstance(val, string_types):
                # Add val to kline
                kline += " " + val
                # Write kline to self.out
                self.writeline(kline)
            # If integer
            elif isinstance(val, integer_types):
                # Convert val to string, add to kline
                kline += " " + str(val)
                self.writeline(kline)
            # If float
            elif isinstance(val, float):
                # If rounding is not None, round the float
                if self.p.rounding is not None:
                    val = round(val, self.p.rounding)
                # Convert val to string, add to kline
                kline += " " + str(val)
                self.writeline(kline)
            # If val is a dictionary
            elif isinstance(val, dict):
                # If recursing, write level
                if recurse:
                    self.writelineseparator(level=level)
                self.writeline(kline)
                # Write dictionary
                self.writedict(val, level=level + 1, recurse=True)
            # If val is an iterable object
            elif isinstance(val, (list, tuple)) or (
                not isinstance(val, (str, dict)) and isinstance(val, Iterable)
            ):
                # Form line and save to self.out
                line = ", ".join(map(str, val))
                self.writeline(kline + " " + line)
            # In other cases, convert val to string and save
            else:
                kline += " " + str(val)
                self.writeline(kline)


# Write StringIO - refactored to not use metaclass
class WriterStringIO(WriterFile):
    """Writer that outputs to an in-memory StringIO buffer.

    This writer stores all output in memory rather than writing to a file.
    Useful for testing or when you need to capture output programmatically.

    Attributes:
        _stringio: The StringIO buffer holding the output.

    Example:
        >>> writer = WriterStringIO()
        >>> cerebro.addwriter(writer)
        >>> results = cerebro.run()
        >>> output = writer.getvalue()
    """

    # Parameter out set to StringIO
    params = (("out", io.StringIO),)  # type: ignore[assignment]

    def __init__(self, **kwargs):
        """Initialize the WriterStringIO instance.

        Creates a new StringIO buffer for storing output.

        Args:
            **kwargs: Keyword arguments for writer parameters.
        """
        self._stringio = io.StringIO()
        self.close_out = False
        super().__init__(**kwargs)

    @property
    def out(self):
        """Always return our StringIO object."""
        return self._stringio

    @out.setter
    def out(self, value):
        """Ignore attempts to set out - we control it."""

    def stop(self):
        """Seek to beginning for reading."""
        if self._stringio:
            self._stringio.seek(0)

    def getvalue(self):
        """Get the content from the StringIO object."""
        if self._stringio:
            return self._stringio.getvalue()
        return ""
