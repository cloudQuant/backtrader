#!/usr/bin/env python
"""Pandas Data Feed Module - Pandas DataFrame integration.

This module provides data feeds for loading market data from
Pandas DataFrames.

Classes:
    PandasDirectData: Uses DataFrame tuples as data source.
    PandasData: Uses DataFrame columns as data source.

Example:
    >>> import pandas as pd
    >>> df = pd.read_csv('data.csv')
    >>> data = bt.feeds.PandasData(dataname=df)
    >>> cerebro.adddata(data)
"""

from ..feed import DataBase
from ..utils import date2num
from ..utils.py3 import filter, integer_types, string_types


class PandasDirectData(DataBase):
    """
    Uses a Pandas DataFrame as the feed source, iterating directly over the
    tuples returned by "itertuples".

    This means that all parameters related to lines must have numeric
    values as indices into the tuples

    Note:

      - The ``dataname`` parameter is a Pandas DataFrame

      - A negative value in any of the parameters for the Data lines
        indicates it's not present in the DataFrame
        it is
    """

    # Parameters
    params = (
        ("datetime", 0),
        ("open", 1),
        ("high", 2),
        ("low", 3),
        ("close", 4),
        ("volume", 5),
        ("openinterest", 6),
    )
    # Column names
    datafields = ["datetime", "open", "high", "low", "close", "volume", "openinterest"]

    def __init__(self):
        """Initialize the PandasDirect data feed.

        Prepares for iterating over DataFrame rows.
        """
        super().__init__()  # CRITICAL FIX: Must call parent __init__
        self._rows = None

    def start(self):
        """Start the PandasDirect data feed.

        Creates iterator from DataFrame.
        """
        super().start()

        # reset the iterator on each start
        self._rows = self.p.dataname.itertuples()

    def _load(self):
        # Try to get next row, return False if error
        try:
            row = next(self._rows)
        except StopIteration:
            return False

        # Set the standard datafields - except for datetime
        # For columns other than datetime, add data to lines based on column names
        for datafield in self.getlinealiases():
            if datafield == "datetime":
                continue

            # get the column index
            colidx = getattr(self.params, datafield)

            if colidx < 0:
                # column is not present -- skip
                continue

            # get the line to be set
            line = getattr(self.lines, datafield)
            # print(colidx,datafield,row)
            # indexing for pandas: 1st is colum, then row
            line[0] = row[colidx]

        # datetime
        # For datetime, get the index of datetime column, then get time
        colidx = getattr(self.params, "datetime")
        tstamp = row[colidx]

        # convert to float via datetime and store it
        # Convert timestamp to specific datetime format, then convert to number
        dt = tstamp.to_pydatetime()
        dtnum = date2num(dt)

        # get the line to be set
        # Get datetime line, then save this number
        line = getattr(self.lines, "datetime")
        line[0] = dtnum

        # Done ... return
        return True


class PandasData(DataBase):
    """
    Uses a Pandas DataFrame as the feed source, using indices into column
    names (which can be "numeric")

    This means that all parameters related to lines must have numeric
    values as indices into the tuples

    Params:

      - ``nocase`` (default *True*) case-insensitive match of column names

    Note:

      - The ``dataname`` parameter is a Pandas DataFrame

      - Values possible for datetime

        - None: the index contains the datetime
        - -1: no index, autodetect column
        - >= 0 or string: specific colum identifier

      - For other lines parameters

        - None: column not present
        - -1: autodetect
        - >= 0 or string: specific colum identifier
    """

    # Parameters and their meanings
    params = (
        ("nocase", True),
        # Possible values for datetime (must always be present)
        #  None: datetime is the "index" in the Pandas Dataframe
        #  -1: autodetect position or case-wise equal name
        #  >= 0: numeric index to the colum in the pandas dataframe
        #  string: column name (as index) in the pandas dataframe
        ("datetime", None),
        # The possible values below:
        #  None : column not present
        #  -1: autodetect position or case-wise equal name
        #  >= 0: numeric index to the colum in the pandas dataframe
        #  string: column name (as index) in the pandas dataframe
        ("open", -1),
        ("high", -1),
        ("low", -1),
        ("close", -1),
        ("volume", -1),
        ("openinterest", -1),
    )
    # Column names of data
    datafields = ["datetime", "open", "high", "low", "close", "volume", "openinterest"]

    def __init__(self):
        """Initialize the Pandas data feed.

        Creates column mappings for DataFrame data access.
        """
        super().__init__()

        # these "colnames" can be strings or numeric types
        # Column names, list format
        self._idx = None
        self._df_len = 0
        self._loaditems = None
        self._df_values = None
        self._dt_dtnum = None
        self._coldtime = None
        colnames = list(self.p.dataname.columns.values)
        # If datetime is in index
        if self.p.datetime is None:
            # datetime is expected as index col and hence not returned
            pass

        # try to autodetect if all columns are numeric
        # Try to determine if cstrings are strings, filter out non-strings
        cstrings = filter(lambda x: isinstance(x, string_types), colnames)
        # If there is a string, colsnumeric is False, only returns True when all are numbers
        colsnumeric = not len(list(cstrings))
        if colsnumeric:
            # If all column names are numbers, this flag is True, keep behavior unchanged here
            pass

        # Where each datafield find its value
        # Define a dictionary
        self._colmapping = dict()

        # Build the column mappings to internal fields in advance
        # Iterate through each column
        for datafield in self.getlinealiases():
            # Index where column is located
            defmapping = getattr(self.params, datafield)
            # If column index is number and less than 0, need auto-detection
            if isinstance(defmapping, integer_types) and defmapping < 0:
                # autodetection requested
                for colname in colnames:
                    # If column name is string
                    if isinstance(colname, string_types):
                        # If case-insensitive, compare lowercase equality, if equal means found,
                        # otherwise directly compare if equal
                        if self.p.nocase:
                            found = datafield.lower() == colname.lower()
                        else:
                            found = datafield == colname
                        # If found, map datafield to colname one-to-one, then exit this loop, continue with datafield
                        if found:
                            self._colmapping[datafield] = colname
                            break
                # If searched through df columns and not found, set to None
                if datafield not in self._colmapping:
                    # autodetection requested and not found
                    self._colmapping[datafield] = None
                    continue

            # If user defined datafield themselves, directly use user's definition
            else:
                # all other cases -- used given index
                self._colmapping[datafield] = defmapping

    def start(self):
        """Start the Pandas data feed.

        Resets index and converts column names to indices.
        """
        super().start()
        # Before starting, reset _idx first
        # reset the length with each start
        self._idx = -1

        # Transform names (valid for .ix) into indices (good for .iloc)
        # If case-insensitive, convert column names to lowercase, if sensitive, keep original
        if self.p.nocase:
            colnames = [x.lower() for x in self.p.dataname.columns.values]
        else:
            colnames = [x for x in self.p.dataname.columns.values]

        # Iterate through datafield and column names
        for k, v in self._colmapping.items():
            # If column name is None, represents this column is likely datetime
            if v is None:
                continue  # special marker for datetime
            # If column name is string, if case-insensitive, convert to lowercase first,
            # if sensitive, ignore, then get column index based on column name

            if isinstance(v, string_types):
                # Some code below seems ineffective, can be ignored, directly use
                # self._colmapping[k] = colnames.index(v) as replacement
                try:
                    if self.p.nocase:
                        v = colnames.index(v.lower())
                    else:
                        v = colnames.index(v)
                except ValueError as e:
                    defmap = getattr(self.params, k)
                    if isinstance(defmap, integer_types) and defmap < 0:
                        v = None
                    else:
                        raise e  # let user now something failed
            # If not string, user defined specific integer, directly use user's definition
            self._colmapping[k] = v

        df = self.p.dataname
        self._df_len = len(df)

        linealiases = self.getlinealiases()
        loaditems = []
        for datafield in linealiases:
            if datafield == "datetime":
                continue
            colindex = self._colmapping.get(datafield)
            if colindex is None:
                continue
            loaditems.append((getattr(self.lines, datafield), colindex))

        self._loaditems = loaditems
        self._coldtime = self._colmapping.get("datetime")

        self._df_values = None
        try:
            self._df_values = df.to_numpy(copy=False)
        except Exception:
            self._df_values = None

        self._dt_dtnum = None
        try:
            coldtime = self._coldtime
            ts = df.index if coldtime is None else df.iloc[:, coldtime]
            try:
                py_dts = ts.to_pydatetime()
            except Exception:
                try:
                    py_dts = ts.dt.to_pydatetime()
                except Exception:
                    py_dts = [x.to_pydatetime() if hasattr(x, "to_pydatetime") else x for x in ts]
            self._dt_dtnum = [date2num(d) for d in py_dts]
        except Exception:
            self._dt_dtnum = None

    def _load(self):
        # Load one row at a time, _idx increments by 1 each time
        self._idx += 1
        # If _idx exceeds data length, return False
        if self._idx >= self._df_len:
            # exhausted all rows
            return False

        row = self._idx
        values = self._df_values
        loaditems = self._loaditems
        dt_dtnum = self._dt_dtnum
        if values is not None and loaditems is not None and dt_dtnum is not None:
            for line, col in loaditems:
                line[0] = values[row, col]

            self.lines.datetime[0] = dt_dtnum[row]
            return True

        df = self.p.dataname
        if loaditems is None:
            for datafield in self.getlinealiases():
                if datafield == "datetime":
                    continue

                colindex = self._colmapping[datafield]
                if colindex is None:
                    continue

                line = getattr(self.lines, datafield)
                line[0] = df.iloc[row, colindex]
        else:
            for line, col in loaditems:
                line[0] = df.iloc[row, col]

        coldtime = self._coldtime
        if coldtime is None:
            tstamp = df.index[row]
        else:
            tstamp = df.iloc[row, coldtime]

        dt = tstamp.to_pydatetime() if hasattr(tstamp, "to_pydatetime") else tstamp
        self.lines.datetime[0] = date2num(dt)

        return True
