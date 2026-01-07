#!/usr/bin/env python
"""Benchmark Observer Module - Strategy vs benchmark comparison.

This module provides the Benchmark observer for tracking strategy returns
against a reference asset (benchmark).

Classes:
    Benchmark: Observer that compares strategy performance to a benchmark.

Example:
    >>> cerebro = bt.Cerebro()
    >>> data = bt.feeds.GenericCSVData(dataname='benchmark.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addobserver(bt.observers.Benchmark, data=data)
"""

from ..analyzers.timereturn import TimeReturn as TimeReturnAnalyzer
from .timereturn import TimeReturn


# Benchmark
class Benchmark(TimeReturn):
    """This observer stores the *returns* of the strategy and the *return* of a
    reference asset which is one of the datas passed to the system.

    Params:

      - ``timeframe`` (default: ``None``)
        If ``None`` then the complete return over the entire backtested period
        will be reported

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

      - ``data`` (default: ``None``)

        Reference asset to track to allow for comparison.

        :note:: this data must have been added to a ``cerebro`` instance with
                  ``addata``, ``resampledata`` or ``replaydata``.


      - ``_doprenext`` (default: ``False``)

        Benchmarking will take place from the point at which the strategy kicks
        in (i.e.: when the minimum period of the strategy has been met).

        Setting this to ``True`` will record benchmarking values from the
        starting point of the data feeds

      - ``firstopen`` (default: ``False``)

        Keepint it as ``False`` ensures that the 1st comparison point between
        the value and the benchmark starts at 0%, because the benchmark will
        not use its opening price.

        See the ``TimeReturn`` analyzer reference for a full explanation of the
        meaning of the parameter

      - ``fund`` (default: ``None``)

        If `None`, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Remember that at any moment of a `run` the current values can be checked
    by looking at the *lines* by name at index ``0``.

    """

    _stclock = True

    lines = ("benchmark",)
    plotlines = dict(benchmark=dict(_name="Benchmark"))

    params = (
        ("data", None),
        ("_doprenext", False),
        # Set to False, to ensure the asset is measured at 0% in the 1st tick
        ("firstopen", False),
        ("fund", None),
    )

    def _plotlabel(self):
        labels = super()._plotlabel()
        labels.append(self.p.data._name)
        return labels

    # Initialize, if no data set, use first data
    def __init__(self):
        if self.p.data is None:  # use the 1st data in the system if none given
            self.p.data = self.data0

        super().__init__()  # treturn including data parameter
        # Create a time return object without the data
        kwargs = self.p._getkwargs()
        kwargs.update(data=None)  # to create a return for the strategy
        # Get return rate
        t = self._owner._addanalyzer_slave(TimeReturnAnalyzer, **kwargs)

        # swap for consistency
        self.treturn, self.tbench = t, self.treturn

    # Set benchmark value
    def next(self):
        super().next()
        self.lines.benchmark[0] = self.tbench.rets.get(self.treturn.dtkey, float("NaN"))

    # prenext
    def prenext(self):
        if self.p._doprenext:
            super(TimeReturn, self).prenext()
