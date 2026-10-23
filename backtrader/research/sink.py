"""Collection sinks for :class:`FactorStrategy`.

A sink receives finished per-grid results; it never advances an indicator or
owns a clock.  ``MemorySink`` is the default and builds one :class:`FactorPanel`
in ``finalize``.  ``CsvSink`` builds the same panel and also writes the six CSV
files, staging them in a fresh temporary directory before publishing.

Both sinks need the complete panel in memory while collecting.  ``CsvSink`` is
an output convenience, not a low-memory streaming promise.
"""

from __future__ import annotations

from array import array
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..errors import DatasetError, ResearchConfigError
from .panel import FactorPanel


@dataclass(frozen=True)
class PanelContext:
    """Everything ``finalize`` needs that is not a per-point observation."""

    grid: Any
    start: Any
    end: Any
    target_order: Tuple[str, ...]
    factor_order: Tuple[str, ...]
    directions: Mapping[str, int]
    universe: Any = None
    groups: Optional[Mapping[str, str]] = None
    prices_open: Any = None
    prices_close: Any = None


class FactorSink:
    """Minimal sink interface; subclasses implement ``on_point``/``finalize``."""

    def on_point(
        self,
        time: Any,
        asset: str,
        values: Mapping[str, float],
        open_price: float,
        close_price: float,
        present: bool,
    ) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def finalize(self, context: PanelContext) -> FactorPanel:  # pragma: no cover - interface
        raise NotImplementedError

    def write(self, panel: FactorPanel) -> None:
        """Optional output step, run after ``finalize`` and before ``close``."""

    def close(self) -> None:
        """Release buffers; must be idempotent."""

    @property
    def panel(self) -> Optional[FactorPanel]:
        return None


class MemorySink(FactorSink):
    """Collect rows in memory and build one panel at the end of the run."""

    def __init__(self) -> None:
        self._times: List[Any] = []
        self._assets: List[str] = []
        self._values: List[array] = []
        self._open = array("d")
        self._close = array("d")
        self._empty_factor_rows = 0
        self._factor_order: Tuple[str, ...] = ()
        self._panel: Optional[FactorPanel] = None
        self._closed = False

    def on_point(
        self,
        time: Any,
        asset: str,
        values: Mapping[str, float],
        open_price: float,
        close_price: float,
        present: bool,
    ) -> None:
        if self._closed:
            raise RuntimeError("sink is closed")
        if self._panel is not None:
            raise RuntimeError("sink is finalized")
        order = tuple(values)
        if not self._factor_order:
            self._factor_order = order
            self._values = [array("d") for _ in order]
        elif order != self._factor_order:
            raise DatasetError("factor columns changed between grid points")
        self._times.append(time)
        self._assets.append(asset)
        row = tuple(float(values[name]) for name in self._factor_order)
        if not row:
            self._empty_factor_rows += 1
        for column, value in zip(self._values, row):
            column.append(value)
        self._open.append(float(open_price))
        self._close.append(float(close_price))
        _ = bool(present)

    def finalize(self, context: PanelContext) -> FactorPanel:
        if self._panel is not None:
            return self._panel
        if self._closed:
            raise RuntimeError("sink is closed before finalize")
        if not self._times:
            raise DatasetError("no grid points were collected")
        pd = _pandas()
        factor_order = tuple(context.factor_order)
        if factor_order != self._factor_order:
            raise DatasetError("collected factor order does not match the panel context")
        if factor_order and self._empty_factor_rows:
            # Preserve the old tuple-row failure when an empty first mapping
            # is followed by a populated one.
            raise IndexError("tuple index out of range")

        frame = pd.DataFrame(
            {
                "time": self._times,
                "asset": self._assets,
                **dict(zip(factor_order, self._values)),
            }
        )
        factors = frame.set_index(["time", "asset"]).loc[:, list(factor_order)]

        grid = context.grid
        grid_index = grid.index
        if context.prices_open is not None and context.prices_close is not None:
            prices_open = context.prices_open
            prices_close = context.prices_close
        else:
            observed = pd.DataFrame(
                {
                    "time": self._times,
                    "asset": self._assets,
                    "open": self._open,
                    "close": self._close,
                }
            )
            prices_open = (
                observed.pivot(index="time", columns="asset", values="open")
                .reindex(index=grid_index, columns=list(context.target_order))
            )
            prices_close = (
                observed.pivot(index="time", columns="asset", values="close")
                .reindex(index=grid_index, columns=list(context.target_order))
            )

        self._panel = FactorPanel(
            factors=factors,
            grid=grid,
            prices_open=prices_open,
            prices_close=prices_close,
            universe=context.universe,
            groups=context.groups,
            start=context.start,
            end=context.end,
            target_order=context.target_order,
            factor_order=factor_order,
            directions=context.directions,
        )
        return self._panel

    def close(self) -> None:
        self._times = []
        self._assets = []
        self._values = []
        self._open = array("d")
        self._close = array("d")
        self._empty_factor_rows = 0
        self._closed = True

    @property
    def panel(self) -> Optional[FactorPanel]:
        return self._panel


class CsvSink(MemorySink):
    """Memory sink that materializes the panel as CSV at finalize time."""

    def __init__(self, directory: Any) -> None:
        super().__init__()
        self._directory = Path(directory)
        self._written_panel: Optional[FactorPanel] = None

    def finalize(self, context: PanelContext) -> FactorPanel:
        panel = super().finalize(context)
        if self._written_panel is not panel:
            self.write(panel)
        return panel

    def write(self, panel: FactorPanel) -> None:
        if self._written_panel is panel:
            return
        panel.to_csv(self._directory)
        self._written_panel = panel


def _pandas() -> Any:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ResearchConfigError("factor research requires pandas") from exc
    return pd


__all__ = ("CsvSink", "FactorSink", "MemorySink", "PanelContext")
