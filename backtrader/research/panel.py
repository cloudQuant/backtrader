"""Plain-frame research panel collected by :class:`FactorStrategy`.

A panel is an ordinary container: five frames plus a few interval/order
parameters.  It is deliberately *not* an immutable, fingerprinted snapshot and
it carries no dataset identity.  Validation happens once on construction (and
once on CSV load); consumers own any copies they need.

Frames (all float64 except flags):

``factors``
    Wide ``(time, asset)`` long-form source in memory is stored wide; index is a
    unique UTC ``(time, asset)`` MultiIndex covering the inclusive study window
    (``start`` through ``end``) x targets, columns are the ordered factor names.
    Missing values stay ``NaN``; rows are never dropped or filled.
``grid``
    Ordered unique UTC ``close_time`` index with the existing ``open_time``
    column.  ``start``/``end`` are exact grid points.
``prices_open`` / ``prices_close``
    Wide float64 frames on the **full** grid index, including warm-up before
    ``start`` and label tails after ``end``, columns ordered exactly like targets.
``universe``
    Boolean wide frame on the study window (``start``..``end``) x targets.
    When the caller does not supply one it defaults to all ``True``; a supplied
    one is never silently widened.
``groups``
    Asset -> research group mapping.  This is not an industry-neutralization
    label; it only partitions targets for grouped statistics.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from ..errors import DatasetError, ResearchConfigError
from .specs import require_research_runtime

_CSV_FILES = (
    "factors.csv",
    "grid.csv",
    "prices_open.csv",
    "prices_close.csv",
    "universe.csv",
    "groups.csv",
)


def _require_utc_index(index: Any, name: str, pd: Any) -> Any:
    if not isinstance(index, pd.DatetimeIndex):
        raise ResearchConfigError("%s must be a DatetimeIndex" % name)
    if index.tz is None:
        raise ResearchConfigError("%s must be timezone-aware UTC" % name)
    converted = index.tz_convert("UTC")
    if not converted.is_unique or not converted.is_monotonic_increasing:
        raise DatasetError("%s must be unique and strictly increasing" % name)
    return converted


def _as_float_frame(frame: Any, name: str, columns: Sequence[str], index: Any, pd: Any) -> Any:
    if not isinstance(frame, pd.DataFrame):
        raise ResearchConfigError("%s must be a pandas DataFrame" % name)
    if tuple(frame.columns) != tuple(columns):
        raise ResearchConfigError(
            "%s columns must be exactly the declared order %s" % (name, list(columns))
        )
    if not frame.index.equals(index):
        raise DatasetError("%s index must equal the panel grid index" % name)
    result = frame.astype("float64")
    result.index = pd.DatetimeIndex(index, name="close_time", freq=None)
    values = result.to_numpy(dtype="float64", copy=False)
    if not (values == values).all() or (abs(values) == float("inf")).any():
        # NaN is a legitimate missing value; infinity is not.
        import numpy as np

        if np.isinf(values).any():
            raise DatasetError("%s contains non-finite infinite values" % name)
    return result


def _as_bool_frame(frame: Any, name: str, index: Any, columns: Sequence[str], pd: Any) -> Any:
    if not isinstance(frame, pd.DataFrame):
        raise ResearchConfigError("%s must be a pandas DataFrame" % name)
    if tuple(frame.columns) != tuple(columns):
        raise ResearchConfigError("%s columns must be exactly the declared targets" % name)
    if not frame.index.equals(index):
        raise DatasetError("%s index must cover the study window exactly" % name)
    if frame.isna().any().any() or not all(
        pd.api.types.is_bool_dtype(dtype) for dtype in frame.dtypes
    ):
        raise DatasetError("%s must contain non-missing boolean values" % name)
    result = frame.astype(bool, copy=True)
    result.columns.name = None
    return result


class FactorPanel:
    """Five plain frames plus start/end, order and direction declarations."""

    __slots__ = (
        "factors",
        "grid",
        "prices_open",
        "prices_close",
        "universe",
        "groups",
        "start",
        "end",
        "target_order",
        "factor_order",
        "directions",
    )

    def __init__(
        self,
        *,
        factors: Any,
        grid: Any,
        prices_open: Any,
        prices_close: Any,
        universe: Any = None,
        groups: Optional[Mapping[str, str]] = None,
        start: Any = None,
        end: Any = None,
        target_order: Optional[Sequence[str]] = None,
        factor_order: Optional[Sequence[str]] = None,
        directions: Optional[Mapping[str, int]] = None,
        validate: bool = True,
    ) -> None:
        if not validate:
            self.factors = factors
            self.grid = grid
            self.prices_open = prices_open
            self.prices_close = prices_close
            self.universe = universe
            self.groups = dict(groups or {})
            self.start = start
            self.end = end
            self.target_order = tuple(target_order or ())
            self.factor_order = tuple(factor_order or ())
            self.directions = dict(directions or {})
            return
        self._build(
            factors=factors,
            grid=grid,
            prices_open=prices_open,
            prices_close=prices_close,
            universe=universe,
            groups=groups,
            start=start,
            end=end,
            target_order=target_order,
            factor_order=factor_order,
            directions=directions,
        )

    def _build(
        self,
        *,
        factors: Any,
        grid: Any,
        prices_open: Any,
        prices_close: Any,
        universe: Any,
        groups: Optional[Mapping[str, str]],
        start: Any,
        end: Any,
        target_order: Optional[Sequence[str]],
        factor_order: Optional[Sequence[str]],
        directions: Optional[Mapping[str, int]],
    ) -> None:
        pd = require_research_runtime()
        if not isinstance(grid, pd.DataFrame):
            raise ResearchConfigError("grid must be a pandas DataFrame")
        if grid.index.name != "close_time":
            raise ResearchConfigError("grid index must be named 'close_time'")
        grid_index = _require_utc_index(grid.index, "grid close_time", pd)
        if grid_index.empty:
            raise ResearchConfigError("grid must not be empty")
        # ``freq`` is derivable metadata that a CSV cannot retain; normalize it
        # so an in-memory panel and its CSV round-trip compare equal.
        grid_index = pd.DatetimeIndex(grid_index, name="close_time", freq=None)
        if "open_time" not in grid.columns:
            raise ResearchConfigError("grid requires an open_time column")
        open_times = pd.DatetimeIndex(pd.to_datetime(grid["open_time"], errors="coerce"))
        if open_times.isna().any() or open_times.tz is None:
            raise ResearchConfigError("grid open_time values must be timezone-aware UTC")
        open_times = open_times.tz_convert("UTC")
        if (open_times > grid_index).any():
            raise ResearchConfigError("grid open_time must not follow its close_time")
        normalized_grid = grid.copy(deep=True)
        normalized_grid.index = grid_index
        normalized_grid["open_time"] = open_times

        start_value = pd.Timestamp(start) if start is not None else grid_index[0]
        end_value = pd.Timestamp(end) if end is not None else grid_index[-1]
        for label, value in (("start", start_value), ("end", end_value)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ResearchConfigError("%s must be timezone-aware" % label)
            value = value.tz_convert("UTC")
            if value not in grid_index:
                raise ResearchConfigError("%s must be an exact grid close_time" % label)
        start_value = start_value.tz_convert("UTC")
        end_value = end_value.tz_convert("UTC")
        if start_value > end_value:
            raise ResearchConfigError("start must not follow end")

        if not isinstance(factors, pd.DataFrame):
            raise ResearchConfigError("factors must be a pandas DataFrame")
        if not isinstance(factors.index, pd.MultiIndex) or tuple(factors.index.names) != (
            "time",
            "asset",
        ):
            raise ResearchConfigError("factors index must be a named (time, asset) MultiIndex")
        if not factors.index.is_unique:
            raise DatasetError("factors index contains duplicate (time, asset) keys")
        factor_columns = tuple(factors.columns)
        if not factors.columns.is_unique:
            raise ResearchConfigError("factor columns must be unique")
        if factor_order is not None and tuple(factor_order) != factor_columns:
            raise ResearchConfigError("factor_order must equal the factors column order")
        if not factor_columns:
            raise ResearchConfigError("at least one factor column is required")
        if any(not isinstance(name, str) or not name for name in factor_columns):
            raise ResearchConfigError("factor names must be non-empty strings")

        times = factors.index.get_level_values("time")
        if getattr(times, "tz", None) is None:
            raise ResearchConfigError("factor times must be timezone-aware UTC")
        times = times.tz_convert("UTC")
        assets = tuple(pd.Index(factors.index.get_level_values("asset")).drop_duplicates())
        targets = tuple(target_order) if target_order is not None else assets
        if not targets:
            raise ResearchConfigError("at least one target asset is required")
        if len(set(targets)) != len(targets) or any(
            not isinstance(name, str) or not name for name in targets
        ):
            raise ResearchConfigError("target_order must contain unique non-empty names")
        if set(assets) != set(targets):
            raise DatasetError("factor assets do not match the declared target order")
        study_index = grid_index[(grid_index >= start_value) & (grid_index <= end_value)]
        expected = pd.MultiIndex.from_product([study_index, targets], names=("time", "asset"))
        normalized = factors.copy(deep=True)
        normalized.index = pd.MultiIndex.from_arrays(
            [times, factors.index.get_level_values("asset")], names=("time", "asset")
        )
        if not normalized.index.equals(expected):
            raise DatasetError("factors must cover exactly the study window x targets product")
        normalized = normalized.loc[:, list(factor_columns)].astype("float64")
        _reject_infinite(normalized, "factors")

        prices_open = _as_float_frame(prices_open, "prices_open", targets, grid_index, pd)
        prices_close = _as_float_frame(prices_close, "prices_close", targets, grid_index, pd)

        if universe is None:
            normalized_universe = pd.DataFrame(
                True, index=study_index, columns=list(targets), dtype=bool
            )
        else:
            normalized_universe = _as_bool_frame(universe, "universe", study_index, targets, pd)
            normalized_universe = normalized_universe.reindex(
                index=study_index, columns=list(targets)
            )

        if groups is None:
            normalized_groups = dict.fromkeys(targets, "default")
        elif isinstance(groups, Mapping):
            if set(groups) != set(targets):
                raise ResearchConfigError("groups must cover exactly the target assets")
            normalized_groups = {
                asset: str(groups[asset]) for asset in targets if str(groups[asset])
            }
            if len(normalized_groups) != len(targets):
                raise ResearchConfigError("group names must be non-empty strings")
        else:
            raise ResearchConfigError("groups must be an asset-to-group mapping")

        if directions is None:
            raise ResearchConfigError("directions must declare +1/-1 for every factor")
        normalized_directions: Dict[str, int] = {}
        for name in factor_columns:
            if name not in directions:
                raise ResearchConfigError("directions is missing factor %s" % name)
            value = directions[name]
            if type(value) is not int or value not in (-1, 1):
                raise ResearchConfigError("direction for %s must be integer +1 or -1" % name)
            normalized_directions[name] = int(value)
        if set(directions) - set(factor_columns):
            raise ResearchConfigError("directions declares unknown factors")

        self.factors = normalized
        self.grid = normalized_grid
        self.prices_open = prices_open
        self.prices_close = prices_close
        self.universe = normalized_universe
        self.groups = normalized_groups
        self.start = start_value
        self.end = end_value
        self.target_order = targets
        self.factor_order = factor_columns
        self.directions = normalized_directions

    # -- views -----------------------------------------------------------

    def factor_values(self, name: str) -> Any:
        """Return one factor column without copying the other factors."""
        if name not in self.factor_order:
            raise KeyError("factor %r is not in the panel" % name)
        return self.factors[name]

    def price(self, name: str) -> Any:
        if name == "open":
            return self.prices_open
        if name == "close":
            return self.prices_close
        raise KeyError("price %r is not in the panel" % name)

    def study_factors(self) -> Any:
        """Factor rows restricted to the study window (same object otherwise)."""
        mask = self.factors.index.get_level_values("time") <= self.end
        selected = self.factors.loc[mask]
        return selected

    # -- CSV exchange ----------------------------------------------------

    def to_csv(self, directory: Any) -> Path:
        """Write the six CSVs; publish by renaming a fresh temporary directory."""
        pd = require_research_runtime()
        target = Path(directory)
        if target.exists() or target.is_symlink():
            raise DatasetError("CSV panel directory already exists: %s" % target)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".panel-", dir=str(target.parent)))
        try:
            factors = self.factors.reset_index().melt(
                id_vars=["time", "asset"],
                value_vars=list(self.factor_order),
                var_name="factor",
                value_name="value",
            )
            factors.to_csv(staging / "factors.csv", index=False)
            grid = self.grid.reset_index()
            grid.to_csv(staging / "grid.csv", index=False)
            self.prices_open.reset_index().rename(
                columns={self.prices_open.index.name or "index": "close_time"}
            ).to_csv(staging / "prices_open.csv", index=False)
            self.prices_close.reset_index().rename(
                columns={self.prices_close.index.name or "index": "close_time"}
            ).to_csv(staging / "prices_close.csv", index=False)
            universe = self.universe.reset_index().melt(
                id_vars=["close_time"],
                value_vars=list(self.target_order),
                var_name="asset",
                value_name="universe",
            )
            universe.rename(columns={"close_time": "time"}).to_csv(
                staging / "universe.csv", index=False
            )
            pd.DataFrame(
                {"asset": list(self.groups), "group": list(self.groups.values())}
            ).to_csv(staging / "groups.csv", index=False)
            os.rename(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target

    @classmethod
    def from_csv(
        cls,
        directory: Any,
        *,
        start: Any,
        end: Any,
        directions: Mapping[str, int],
        target_order: Sequence[str],
        factor_order: Sequence[str],
        groups: Optional[Mapping[str, str]] = None,
    ) -> "FactorPanel":
        """Reconstruct a panel from the six CSVs with explicit configuration.

        The research interval, directions and both orders must be supplied by
        the caller: they are configuration, not something to infer from the
        first/last non-empty value or the row order of a long CSV.
        """
        pd = require_research_runtime()
        root = Path(directory)
        missing = [name for name in _CSV_FILES if not (root / name).is_file()]
        if missing:
            raise DatasetError(
                "panel CSV directory is incomplete", report={"missing": tuple(missing)}
            )
        if not target_order or not factor_order:
            raise ResearchConfigError("from_csv requires explicit target_order and factor_order")
        targets = tuple(target_order)
        factors_expected = tuple(factor_order)

        grid_frame = pd.read_csv(root / "grid.csv")
        if "close_time" not in grid_frame.columns:
            raise DatasetError("grid.csv requires a close_time column")
        grid_frame["close_time"] = pd.to_datetime(grid_frame["close_time"], utc=True)
        grid_frame = grid_frame.set_index("close_time")
        grid_frame.index.name = "close_time"

        long = pd.read_csv(
            root / "factors.csv", dtype={"asset": str}, float_precision="round_trip"
        )
        required = {"time", "asset", "factor", "value"}
        if not required.issubset(long.columns):
            raise DatasetError("factors.csv requires time/asset/factor/value columns")
        if long.empty:
            raise DatasetError("factors.csv is empty")
        long["time"] = pd.to_datetime(long["time"], utc=True)
        if long.duplicated(["time", "asset", "factor"]).any():
            raise DatasetError("factors.csv contains duplicate (time, asset, factor) keys")
        if set(long["factor"]) != set(factors_expected):
            raise DatasetError("factors.csv factors do not match factor_order")
        wide = long.pivot(index=["time", "asset"], columns="factor", values="value")
        wide.index = wide.index.set_names(("time", "asset"))
        wide = wide.reindex(columns=list(factors_expected))
        wide.columns.name = None
        # Restore the caller's declared order; pivot sorts the (time, asset)
        # index, which would otherwise reject an unsorted target_order.
        start_stamp = pd.Timestamp(start)
        end_stamp = pd.Timestamp(end)
        if start_stamp.tzinfo is None:
            start_stamp = start_stamp.tz_localize("UTC")
        if end_stamp.tzinfo is None:
            end_stamp = end_stamp.tz_localize("UTC")
        study_index = grid_frame.index[
            (grid_frame.index >= start_stamp.tz_convert("UTC"))
            & (grid_frame.index <= end_stamp.tz_convert("UTC"))
        ]
        expected = pd.MultiIndex.from_product([study_index, list(targets)], names=("time", "asset"))
        if set(wide.index) != set(expected):
            raise DatasetError("factors.csv does not cover exactly the study window x targets")
        wide = wide.reindex(expected)
        for name in factors_expected:
            # A NaN cell still has a row; a truncated file does not.  Counting
            # rows per factor keeps the two cases distinguishable.
            if int((long["factor"] == name).sum()) != len(wide.index):
                raise DatasetError(
                    "factors.csv is truncated for factor %s: a NaN cell must still "
                    "have a row" % name
                )
        return cls(
            factors=wide,
            grid=grid_frame,
            prices_open=_read_wide(root / "prices_open.csv", targets, pd),
            prices_close=_read_wide(root / "prices_close.csv", targets, pd),
            universe=_read_universe(root / "universe.csv", targets, pd),
            groups=groups if groups is not None else _read_groups(root / "groups.csv", pd),
            start=start,
            end=end,
            target_order=targets,
            factor_order=factors_expected,
            directions=directions,
        )

    def __repr__(self) -> str:  # pragma: no cover - diagnostics helper
        return (
            "FactorPanel(factors=%d, targets=%d, grid=%d, start=%s, end=%s)"
            % (
                len(self.factor_order),
                len(self.target_order),
                len(self.grid),
                self.start,
                self.end,
            )
        )


def _reject_infinite(frame: Any, name: str) -> None:
    import numpy as np

    if np.isinf(frame.to_numpy(dtype="float64", copy=False)).any():
        raise DatasetError("%s contains infinite values" % name)


def _read_wide(path: Path, columns: Sequence[str], pd: Any) -> Any:
    frame = pd.read_csv(path, dtype={"asset": str}, float_precision="round_trip")
    key = "close_time" if "close_time" in frame.columns else frame.columns[0]
    frame[key] = pd.to_datetime(frame[key], utc=True)
    frame = frame.set_index(key)
    frame.index.name = "close_time"
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise DatasetError("%s is missing target columns" % path.name)
    return frame.loc[:, list(columns)].astype("float64")


def _read_universe(path: Path, columns: Sequence[str], pd: Any) -> Any:
    frame = pd.read_csv(path, dtype={"asset": str}, float_precision="round_trip")
    required = {"time", "asset", "universe"}
    if not required.issubset(frame.columns):
        raise DatasetError("universe.csv requires time/asset/universe columns")
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    wide = frame.pivot(index="time", columns="asset", values="universe")
    wide.index.name = "close_time"
    wide.columns.name = None
    missing = [name for name in columns if name not in wide.columns]
    if missing:
        raise DatasetError("universe.csv is missing target columns")
    return wide.loc[:, list(columns)].astype(bool)


def _read_groups(path: Path, pd: Any) -> Dict[str, str]:
    frame = pd.read_csv(path, dtype={"asset": str}, float_precision="round_trip")
    if not {"asset", "group"}.issubset(frame.columns):
        raise DatasetError("groups.csv requires asset/group columns")
    return {str(row.asset): str(row.group) for row in frame.itertuples(index=False)}


def iter_factor_names(panel: FactorPanel) -> Iterable[str]:
    return iter(panel.factor_order)


__all__ = ("FactorPanel",)
