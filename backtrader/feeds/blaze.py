#!/usr/bin/env python
"""Blaze Data Feed Module - Blaze data interface.

.. deprecated::
    The Blaze project (blaze.pydata.org) is no longer maintained.
    This module is retained for backward compatibility but will be
    removed in a future release. Consider using PandasData instead.

Classes:
    BlazeData: Blaze Data object feed.

Example:
    >>> import blaze as bz
    >>> data = bz.Data('data.csv')
    >>> feed = bt.feeds.BlazeData(dataname=data)
    >>> cerebro.adddata(feed)
"""

import warnings

warnings.warn(
    "backtrader.feeds.blaze is deprecated (Blaze is unmaintained). Consider using PandasData instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ..feed import DataBase  # noqa: E402
from ..lineseries import LineAlias  # noqa: E402
from ..parameters import ParameterAccessor, ParameterManager  # noqa: E402
from ..utils import date2num  # noqa: E402

_MISSING = object()


# This class is for backtrader to interface with Blaze data
# blaze introduction: https://blaze.readthedocs.io/en/latest/index.html
class BlazeData(DataBase):
    """
    Support for `Blaze <blaze.pydata.org>`_ ``Data`` objects.

    Only numeric indices to columns are supported.

    Note:

      - The ``dataname`` parameter is a blaze ``Data`` object

      - A negative value in any of the parameters for the Data lines
        indicates it's not present in the DataFrame
        it is
    """

    # Parameters
    params = (
        # datetime must be present
        ("datetime", 0),
        # pass -1 for any of the following to indicate absence
        ("open", 1),
        ("high", 2),
        ("low", 3),
        ("close", 4),
        ("volume", 5),
        ("openinterest", 6),
    )

    # Column names
    datafields = ["datetime", "open", "high", "low", "close", "volume", "openinterest"]
    _field_plan = None

    def __init__(self):
        """Initialize the Blaze data feed.

        Sets up internal row iterator and cached field resolution plan.
        """
        super().__init__()
        self._rows = None
        self._field_plan = None

    def _build_field_plan(self):
        """Precompute direct parameter/line lookup bindings when safe.

        Keeps column-index lookups live against ``ParameterManager._values`` and
        line-buffer lookups live against ``self.lines.lines`` so runtime
        parameter changes, line-buffer replacements after ``start()``, and
        ``datafields`` mutations retain exact dynamic semantics.  Returns
        ``None`` for non-standard params/lines containers so ``_load`` falls
        back to standard ``getattr`` resolution.
        """
        params = self.params
        if type(params) is not ParameterAccessor:
            return None

        pm = getattr(params, "_param_manager", None)
        if type(pm) is not ParameterManager:
            return None

        pm_values = pm._values
        if type(pm_values) is not dict:
            return None

        datafields = self.datafields
        datafields_type = type(datafields)
        if datafields_type not in (list, tuple) or not datafields:
            return None

        lines_obj = self.lines
        lines_list = getattr(lines_obj, "lines", None)
        lines_dict = getattr(lines_obj, "__dict__", None)
        if type(lines_list) is not list or type(lines_dict) is not dict:
            return None

        lines_cls = type(lines_obj)
        lines_len = len(lines_list)
        line_bindings = []
        for field in datafields:
            if not isinstance(field, str) or field not in pm_values or field in lines_dict:
                return None
            desc = None
            for cls in lines_cls.__mro__:
                if field in cls.__dict__:
                    desc = cls.__dict__[field]
                    break
            if type(desc) is not LineAlias or not (0 <= desc.line < lines_len):
                return None
            line_bindings.append((field, desc.line))

        dt_field, dt_line_idx = line_bindings[0]
        other_fields = tuple(line_bindings[1:])
        datafields_snapshot = list(datafields) if datafields_type is list else datafields
        return (
            params,
            pm_values.get,
            lines_obj,
            lines_cls,
            lines_list,
            lines_len,
            lines_dict,
            frozenset(lines_dict.keys()),
            datafields_type,
            datafields_snapshot,
            dt_field,
            dt_line_idx,
            other_fields,
        )

    def start(self):
        """Start the Blaze data feed.

        Initializes the row iterator from the dataname and precomputes the
        field-to-line resolution plan.
        """
        super().start()

        # reset the iterator on each start
        self._rows = iter(self.p.dataname)
        self._field_plan = self._build_field_plan()

    def _load_row_fallback(self, row):
        """Load one row using full dynamic attribute lookup."""
        for datafield in self.datafields[1:]:
            colidx = getattr(self.params, datafield)
            if colidx < 0:
                continue
            line = getattr(self.lines, datafield)
            line[0] = row[colidx]

        colidx = getattr(self.params, self.datafields[0])
        dt = row[colidx]
        dtnum = date2num(dt)
        line = getattr(self.lines, self.datafields[0])
        line[0] = dtnum
        return True

    # Load data
    def _load(self):
        # Try to get next row data, if doesn't exist, return False, indicating data loading finished
        try:
            row = next(self._rows)
        except StopIteration:
            return False

        plan = self._field_plan
        datafields = self.datafields
        if (
            plan is None
            or self.params is not plan[0]
            or self.lines is not plan[2]
            or type(plan[2]) is not plan[3]
            or plan[2].lines is not plan[4]
            or len(plan[4]) != plan[5]
            or plan[6].keys() != plan[7]
            or type(datafields) is not plan[8]
            or (datafields != plan[9] if plan[8] is list else datafields is not plan[9])
        ):
            plan = self._field_plan = self._build_field_plan()

        if plan is not None:
            pm_get = plan[1]
            lines_list = plan[4]
            dt_colidx = pm_get(plan[10], _MISSING)
            if dt_colidx is not _MISSING:
                for field, line_idx in plan[12]:
                    colidx = pm_get(field, _MISSING)
                    if colidx is _MISSING:
                        self._field_plan = None
                        return self._load_row_fallback(row)
                    if colidx < 0:
                        continue
                    lines_list[line_idx][0] = row[colidx]

                lines_list[plan[11]][0] = date2num(row[dt_colidx])
                return True

            self._field_plan = None

        return self._load_row_fallback(row)
