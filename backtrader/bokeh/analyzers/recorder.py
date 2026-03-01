#!/usr/bin/env python
"""
Data recording analyzer.

Records data during strategy execution for subsequent plotting or analysis.
"""

from collections import OrderedDict

import backtrader as bt


class RecorderAnalyzer(bt.Analyzer):
    """
    Data recording analyzer.

    Records OHLCV data and indicator data during strategy execution.

    Args:
        indicators: Whether to record indicator data
        observers: Whether to record observer data

    Example:
        cerebro.addanalyzer(RecorderAnalyzer, indicators=True)

        # Get data after running
        result = cerebro.run()
        recorder = result[0].analyzers.recorderanalyzer
        data = recorder.get_analysis()
    """

    params = (
        ("indicators", True),  # Whether to record indicators
        ("observers", False),  # Whether to record observers
    )

    def __init__(self):
        """Initialize recorder analyzer.

        Sets up storage for data sources, indicators, and observers based
        on parameter configuration.
        """
        super().__init__()

        # Data storage
        self._data = OrderedDict()

        # Initialize data source storage
        for i, data in enumerate(self.strategy.datas):
            name = getattr(data, "_name", None) or f"data{i}"
            self._data[name] = {
                "datetime": [],
                "open": [],
                "high": [],
                "low": [],
                "close": [],
                "volume": [],
            }

        # Initialize indicator storage
        if self.p.indicators:
            self._indicators = OrderedDict()

        # Initialize observer storage
        if self.p.observers:
            self._observers = OrderedDict()

    def start(self):
        """Analyzer start."""
        pass

    def next(self):
        """Record data for each bar."""
        # Record data sources
        for i, data in enumerate(self.strategy.datas):
            name = getattr(data, "_name", f"data{i}")

            if name in self._data:
                try:
                    self._data[name]["datetime"].append(data.datetime.datetime(0))
                    self._data[name]["open"].append(data.open[0])
                    self._data[name]["high"].append(data.high[0])
                    self._data[name]["low"].append(data.low[0])
                    self._data[name]["close"].append(data.close[0])
                    self._data[name]["volume"].append(
                        data.volume[0] if hasattr(data, "volume") else 0
                    )
                except Exception:
                    pass

        # Record indicators
        if self.p.indicators and hasattr(self.strategy, "_lineiterators"):
            indicators = self.strategy._lineiterators.get(1, [])  # IndType = 1

            for ind in indicators:
                ind_name = ind.__class__.__name__

                if ind_name not in self._indicators:
                    self._indicators[ind_name] = OrderedDict()
                    # Initialize line storage
                    for line_name in ind.lines._getlinealiases():
                        self._indicators[ind_name][line_name] = []

                # Record value for each line
                for line_name in ind.lines._getlinealiases():
                    try:
                        line = getattr(ind.lines, line_name)
                        value = line[0] if len(line) > 0 else None
                        self._indicators[ind_name][line_name].append(value)
                    except Exception:
                        self._indicators[ind_name][line_name].append(None)

        # Record observers
        if self.p.observers and hasattr(self.strategy, "_lineiterators"):
            observers = self.strategy._lineiterators.get(2, [])  # ObsType = 2

            for obs in observers:
                obs_name = obs.__class__.__name__

                if obs_name not in self._observers:
                    self._observers[obs_name] = OrderedDict()
                    for line_name in obs.lines._getlinealiases():
                        self._observers[obs_name][line_name] = []

                for line_name in obs.lines._getlinealiases():
                    try:
                        line = getattr(obs.lines, line_name)
                        value = line[0] if len(line) > 0 else None
                        self._observers[obs_name][line_name].append(value)
                    except Exception:
                        self._observers[obs_name][line_name].append(None)

    def stop(self):
        """Analyzer stop."""
        pass

    def get_analysis(self):
        """Return recorded data.

        Returns:
            OrderedDict: Dictionary containing data, indicators and observers
        """
        result = OrderedDict()

        result["data"] = self._data

        if self.p.indicators:
            result["indicators"] = getattr(self, "_indicators", OrderedDict())

        if self.p.observers:
            result["observers"] = getattr(self, "_observers", OrderedDict())

        return result

    def get_dataframe(self, data_name=None):
        """Convert data to pandas DataFrame.

        Args:
            data_name: Data source name, None means first data source

        Returns:
            pandas.DataFrame or None
        """
        try:
            import pandas as pd
        except ImportError:
            return None

        if data_name is None:
            data_name = list(self._data.keys())[0] if self._data else None

        if data_name is None or data_name not in self._data:
            return None

        df = pd.DataFrame(self._data[data_name])

        if "datetime" in df.columns:
            df.set_index("datetime", inplace=True)

        return df
