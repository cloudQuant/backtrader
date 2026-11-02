"""One-reindex alignment of closed-bar frames to a research grid.

This replaces the old ``prealign_bars`` heavy path.  Per asset it keeps the
caller's source frame and produces exactly one reindexed frame, a boolean
``present`` flag per grid point and the open/close price vectors.  There is no
``available_at`` bookkeeping, no point-in-time as-of selection and no second
full-frame copy hanging off the feed.

``present`` says only "the source had a bar at this grid time".  A reindexed
row that exists because of the grid is *not* a bar, so ``feed_time ==
grid_time`` alone does not prove a real bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..errors import DatasetError, ResearchConfigError
from .specs import ResearchSpec, require_research_runtime

_FEED_MARKER = "_factor_research_alignment_v2"
_PRICE_COLUMNS = ("open", "close")


def _utc_index(values: Any, source_timezone: str, pd: Any, label: str) -> Any:
    try:
        index = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce"))
    except (TypeError, ValueError) as exc:
        raise DatasetError("%s must contain datetime values" % label) from exc
    if index.isna().any():
        raise DatasetError("%s contains invalid or missing timestamps" % label)
    if index.tz is None:
        try:
            index = index.tz_localize(source_timezone, ambiguous="raise", nonexistent="raise")
        except Exception as exc:
            raise DatasetError("%s cannot be localized without ambiguity" % label) from exc
    return index.tz_convert("UTC")


def _numeric_column(frame: Any, name: str) -> Any:
    import numpy as np

    values = frame[name].to_numpy(dtype="float64", copy=True) if name in frame else None
    if values is None:
        return None
    values[~np.isfinite(values)] = np.nan
    return values


@dataclass(frozen=True, init=False)
class AlignedFeed:
    """A calculation-grid ``PandasData`` feed plus full-grid price vectors."""

    asset: str
    feed: Any = field(repr=False, compare=False)
    present: Any = field(repr=False, compare=False)
    prices_open: Any = field(repr=False, compare=False)
    prices_close: Any = field(repr=False, compare=False)
    grid_sha256: str
    data_version: Optional[str]

    def __init__(
        self,
        *,
        asset: str,
        feed: Any,
        present: Any,
        prices_open: Any,
        prices_close: Any,
        grid_sha256: str,
        data_version: Optional[str],
    ) -> None:
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "feed", feed)
        object.__setattr__(self, "present", present)
        object.__setattr__(self, "prices_open", prices_open)
        object.__setattr__(self, "prices_close", prices_close)
        object.__setattr__(self, "grid_sha256", grid_sha256)
        object.__setattr__(self, "data_version", data_version)


def align_to_grid(
    frame: Any,
    research: ResearchSpec,
    asset: str,
    *,
    data_version: Optional[str] = None,
) -> AlignedFeed:
    """Align once; stop the feed at ``end`` and retain full-grid price arrays."""
    pd = require_research_runtime()
    if not isinstance(research, ResearchSpec):
        raise ResearchConfigError("research must be a ResearchSpec")
    if not isinstance(frame, pd.DataFrame):
        raise DatasetError("bar input must be a pandas DataFrame")
    if not isinstance(asset, str) or not asset:
        raise ResearchConfigError("asset must be a non-empty feed name")
    if not frame.columns.is_unique:
        raise DatasetError("bar input contains duplicate columns")
    if not frame.index.is_unique:
        raise DatasetError("bar input contains duplicate timestamps")
    if data_version is not None and (
        not isinstance(data_version, str) or not data_version.strip()
    ):
        raise ResearchConfigError("data_version must be None or a non-empty string")

    grid = research.grid
    grid_index = grid.index
    source_index = _utc_index(frame.index, research.source_timezone, pd, "bar input index")
    if not source_index.is_monotonic_increasing:
        raise DatasetError("bar input timestamps must be strictly increasing")
    outside = source_index.difference(grid_index)
    if len(outside):
        raise DatasetError(
            "bar input contains timestamps outside the declared grid",
            code="INVALID_DATASET",
            report={"asset": asset, "outside_count": int(len(outside))},
        )

    source = frame.copy(deep=False)
    source.index = source_index
    source.index.name = "close_time"
    aligned = source.reindex(grid_index)
    present = (
        pd.Series(True, index=source_index, dtype=bool)
        .reindex(grid_index, fill_value=False)
        .to_numpy(dtype=bool)
    )

    calculation_end = research.end
    calculation_mask = grid_index <= calculation_end
    import numpy as np

    field_present = {}
    for column in aligned.columns:
        numeric = pd.to_numeric(aligned[column], errors="coerce").to_numpy(dtype="float64")
        field_present[str(column)] = present & np.isfinite(numeric)
    from ..feeds.pandafeed import PandasData

    feed = PandasData(dataname=aligned.loc[calculation_mask])
    setattr(
        feed,
        "_factor_research_datetime_hint",
        (
            feed.p.dataname.index,
            research._feed_datetime_nums,
            research._feed_datetime_index_signature,
        ),
    )
    prices = {name: _numeric_column(aligned, name) for name in _PRICE_COLUMNS}
    metadata = {
        "version": 2,
        "asset": asset,
        "grid_sha256": research.grid_sha256,
        "present": present[calculation_mask],
        "field_present": {
            name: values[calculation_mask] for name, values in field_present.items()
        },
        "prices_open": prices["open"],
        "prices_close": prices["close"],
        "data_version": data_version,
    }
    setattr(feed, _FEED_MARKER, metadata)
    return AlignedFeed(
        asset=asset,
        feed=feed,
        present=present[calculation_mask],
        prices_open=prices["open"],
        prices_close=prices["close"],
        grid_sha256=research.grid_sha256,
        data_version=data_version,
    )


def feed_alignment(data: Any) -> Optional[Any]:
    """Return the alignment metadata attached by :func:`align_to_grid`."""
    return getattr(data, _FEED_MARKER, None)


__all__ = ("AlignedFeed", "align_to_grid", "feed_alignment")
