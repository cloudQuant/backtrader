"""Read-only Backtrader strategy for collecting native research factors."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Tuple

from .. import Strategy
from ..utils import num2date
from .factor_indicator import FactorIndicator


class FactorStrategy(Strategy):
    """Construct factor indicators and collect their lines on a declared UTC grid.

    The strategy never advances indicators itself. Backtrader owns every
    ``prenext``/``nextstart``/``next`` and runonce callback; this class only
    validates the grid and samples the resulting native lines.
    """

    params = (("factors", None), ("grid", ()))

    def __init__(self) -> None:
        self._grid = self._validate_grid(self.p.grid)
        if not self.datas:
            raise ValueError("FactorStrategy requires at least one data feed")

        self._data_names = tuple(getattr(data, "_name", "") for data in self.datas)
        if any(not isinstance(name, str) or not name for name in self._data_names):
            raise ValueError("every FactorStrategy feed needs a non-empty Cerebro name")
        if len(set(self._data_names)) != len(self._data_names):
            raise ValueError("FactorStrategy feed names must be unique")

        factor_specs = self.p.factors
        if not isinstance(factor_specs, Mapping) or not factor_specs:
            raise ValueError("factors must be a non-empty mapping")

        self.factor_instances = {}
        self._factor_panel_lines = {}
        for factor_name, spec in factor_specs.items():
            if not isinstance(factor_name, str) or not factor_name:
                raise ValueError("factor names must be non-empty strings")
            if not isinstance(spec, Mapping):
                raise TypeError("each factor specification must be a mapping")
            unknown = set(spec) - {"indicator", "params", "panel_line"}
            if unknown:
                raise ValueError("unsupported factor specification fields: %s" % sorted(unknown))
            indicator = spec.get("indicator")
            if not isinstance(indicator, type) or not issubclass(indicator, FactorIndicator):
                raise TypeError("research factors must subclass FactorIndicator")
            if "panel_line" not in spec:
                raise ValueError("each factor specification must select a panel_line")
            factor_params = spec.get("params", {})
            if not isinstance(factor_params, Mapping):
                raise TypeError("factor params must be a mapping")
            panel_line = spec.get("panel_line", "factor")
            if (
                not isinstance(panel_line, str)
                or panel_line not in indicator._factor_template_names()
            ):
                raise ValueError("panel_line must name a declared factor output template")

            instance = indicator.bind(*self.datas, **dict(factor_params))
            instance._bind_grid(self._grid)
            self.factor_instances[factor_name] = instance
            self._factor_panel_lines[factor_name] = panel_line

        self._dataset_rows = []
        self._grid_cursor = 0

    @staticmethod
    def _validate_grid(grid: Any) -> Tuple[datetime, ...]:
        if not isinstance(grid, tuple) or not grid:
            raise TypeError("grid must be a non-empty tuple of UTC datetimes")
        normalized = []
        for point in grid:
            if not isinstance(point, datetime) or point.tzinfo is None:
                raise TypeError("every grid point must be a timezone-aware datetime")
            offset = point.utcoffset()
            if offset != timedelta(0):
                raise ValueError("every grid point must use UTC (zero offset)")
            normalized.append(point.astimezone(timezone.utc))
        if any(right <= left for left, right in zip(normalized, normalized[1:])):
            raise ValueError("grid must be strictly increasing with no duplicates")
        return tuple(normalized)

    def prenext(self) -> None:
        self._collect_current_grid_point()

    def next(self) -> None:
        self._collect_current_grid_point()

    def _collect_current_grid_point(self) -> None:
        if self._grid_cursor >= len(self._grid):
            raise RuntimeError("FactorStrategy received more callbacks than grid points")
        current = num2date(float(self.datetime[0]), tz=timezone.utc, naive=False)
        expected = self._grid[self._grid_cursor]
        if current != expected:
            raise RuntimeError("FactorStrategy callback time does not match the declared UTC grid")

        for data in self.datas:
            feed_time = num2date(float(data.datetime[0]), tz=timezone.utc, naive=False)
            if feed_time != current:
                raise RuntimeError("FactorStrategy requires feeds prealigned to its UTC grid")

        for asset_name, data in zip(self._data_names, self.datas):
            row = {"time": current, "asset": asset_name}
            for factor_name, indicator in self.factor_instances.items():
                line_name = self._factor_panel_lines[factor_name]
                row[factor_name] = indicator.outputs[data][line_name][0]
            self._dataset_rows.append(row)
        self._grid_cursor += 1

    def stop(self) -> None:
        if self._grid_cursor != len(self._grid):
            raise RuntimeError("FactorStrategy did not collect every declared grid point")
        for factor_name, indicator in self.factor_instances.items():
            for nested in self._factor_tree(indicator):
                diagnostic = nested.lifecycle_diagnostics
                if not diagnostic["grid_matches"]:
                    raise RuntimeError(
                        "factor %s did not run exactly once per grid point" % factor_name
                    )

    @staticmethod
    def _factor_tree(root: FactorIndicator) -> Tuple[FactorIndicator, ...]:
        factors = []
        seen = set()

        def visit(current: FactorIndicator) -> None:
            if id(current) in seen:
                return
            seen.add(id(current))
            factors.append(current)
            for children in getattr(current, "_lineiterators", {}).values():
                for child in children:
                    if isinstance(child, FactorIndicator):
                        visit(child)

        visit(root)
        return tuple(factors)

    def get_dataset(self) -> Any:
        """Return the collected panel as a DataFrame indexed by time and asset."""
        import pandas as pd

        columns = list(self.factor_instances)
        frame = pd.DataFrame(self._dataset_rows, columns=["time", "asset"] + columns)
        return frame.set_index(["time", "asset"])
