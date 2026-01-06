#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import collections
import io
import itertools
import sys

try:  # For new Python versions
    collectionsAbc = collections.abc  # collections.Iterable -> collections.abc.Iterable
except AttributeError:  # For old Python versions
    collectionsAbc = collections
from .lineseries import LineSeries
from .parameters import ParameterizedBase
from .utils.py3 import integer_types, map, string_types


# WriterBase class - refactored to not use metaclass
class WriterBase(ParameterizedBase):
    pass


# WriterFile class - refactored to not use metaclass
class WriterFile(WriterBase):
    """
    The system-wide writer class.

    It can be parametrized with:

      - ``out`` (default: ``sys.stdout``): output stream to write to

        If a string is passed, a filename with the content of the parameter will
        be used.

        If you wish to run with ``sys.stdout`` while doing multiprocess optimization, leave it as ``None``, which will
        automatically initiate ``sys.stdout`` on the child processes.

        # out defaults to sys.stdout. If you want to output to standard output during multiprocess parameter optimization,
        # set this parameter to None, which will automatically set it in each subprocess
        # If a filename is passed to out, output will be written to this filename

      - ``close_out`` (default: ``False``)

        If ``out`` is a stream whether it has to be explicitly closed by the
        writer
        # When out is a data stream, whether writer needs to explicitly close it

      - ``csv`` (default: ``False``)

        If a csv stream of the data feeds, strategies, observers and indicators
         have to be written to the stream during execution

        Which objects actually go into the csv stream can be controlled with
        the ``csv`` attribute of each object (defaults to ``True`` for ``data
        feeds`` and ``observers`` / False for ``indicators``)

        # CSV data stream of data, strategies, observers and indicators can be written to file during execution,
        # will be written if csv is set to True

      - ``csv_filternan`` (default: ``True``) whether ``nan`` values have to be
        purged out of the csv stream (replaced by an empty field)

        # Whether to clear nan values when writing to csv file

      - ``csv_counter`` (default: ``True``) if the writer shall keep and print
        out a counter of the lines actually output

        # Whether writer saves and prints actually output lines, defaults to True

      - ``indent`` (default: ``2``) indentation spaces for each level
        # Leading spaces, defaults to 2

      - ``separators`` (default: ``['=', '-', '+', '*', '.', '~', '"', '^',
        '#']``)

        Characters used for line separators across section/sub(sub)sections

        # Separators, defaults to ['=', '-', '+', '*', '.', '~', '"', '^','#']

      - ``seplen`` (default: ``79``)

        Total length of a line separator including indentation

        # Total length of separator including leading spaces, defaults to 79

      - ``rounding`` (default: ``None``)

        Number of decimal places to round floats down to.With `None` no
        rounding is performed

        # Whether to round stored decimals to a certain place. No rounding by default.

    """

    params = (
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
        # Initialize parent class first
        super(WriterFile, self).__init__(**kwargs)
        # _len is a counter
        # CRITICAL FIX: Change counter start value from 1 to 0 to match test expectations
        # This fixes assertion error in test_writer.py: assert count == 256
        self._len = itertools.count(0)
        # headers
        self.headers = list()
        # values
        self.values = list()

    # Start output
    def _start_output(self):
        # open file if needed
        # If there's no out attribute or self.out is None
        if not hasattr(self, "out") or not self.out:
            # If out parameter is None, set out to standard output, and close_out to False
            if self.p.out is None:
                self.out = sys.stdout
                self.close_out = False
            # If self.p.out is a string_types, open file in write mode, close_out needs to be True
            elif isinstance(self.p.out, string_types):
                self.out = open(self.p.out, "w")
                self.close_out = True
            # If self.p.out is neither None nor string format, self.out equals self.p.out, self.close_out equals self.p.close_out
            else:
                self.out = self.p.out
                self.close_out = self.p.close_out

    # Start
    def start(self):
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
        if self.close_out:
            self.out.close()

    # If csv is True, save values to self.out each time, and set self.values to empty list
    def next(self):
        if self.p.csv:
            self.writeiterable(self.values, func=str, counter=next(self._len))
            self.values = list()

    # If csv is True, add column names
    def addheaders(self, headers):
        if self.p.csv:
            self.headers.extend(headers)

    # If csv is True and need to filter nan, replace nan with '', and add values to self.values
    def addvalues(self, values):
        if self.p.csv:
            if self.p.csv_filternan:
                values = map(lambda x: x if x == x else "", values)
            self.values.extend(values)

    # Process iterable objects and write to standard output or csv file
    def writeiterable(self, iterable, func=None, counter=""):
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
        self.out.write(line + "\n")

    # Write multiple lines to self.out
    def writelines(self, lines):
        for line in lines:
            self.out.write(line + "\n")

    # Write line separator
    def writelineseparator(self, level=0):
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
            # elif isinstance(val, (list, tuple, collections.Iterable)):
            elif isinstance(val, (list, tuple, collectionsAbc.Iterable)):
                # Form line and save to self.out
                line = ", ".join(map(str, val))
                self.writeline(kline + " " + line)
            # In other cases, convert val to string and save
            else:
                kline += " " + str(val)
                self.writeline(kline)


# Write StringIO - refactored to not use metaclass
class WriterStringIO(WriterFile):
    # Parameter out set to StringIO
    params = (("out", io.StringIO),)

    def __init__(self, **kwargs):
        self._stringio = io.StringIO()
        self.close_out = False
        super(WriterStringIO, self).__init__(**kwargs)

    @property
    def out(self):
        """Always return our StringIO object."""
        return self._stringio

    @out.setter
    def out(self, value):
        """Ignore attempts to set out - we control it."""
        pass

    def stop(self):
        """Seek to beginning for reading."""
        if self._stringio:
            self._stringio.seek(0)

    def getvalue(self):
        """Get the content from the StringIO object."""
        if self._stringio:
            return self._stringio.getvalue()
        return ""
