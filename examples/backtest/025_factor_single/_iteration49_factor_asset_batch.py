"""Private collection support shared by the 025 and 026 factor examples."""

from __future__ import annotations

import gc
import weakref
from typing import Any, Callable, Dict, Mapping, Sequence, Tuple


def run_batched_factor_collection(
    config: Mapping[str, Any],
    panel: Mapping[str, Any],
    runnext: bool,
    batch_size: int,
    factor_names: Sequence[str],
    expected_classes: Mapping[str, Any],
    factor_mode: str,
    directions: Mapping[str, int],
    create_research_spec: Callable[[Mapping[str, Any], Mapping[str, Any]], Any],
    run_native_collection: Callable[..., Tuple[Any, Any, Any]],
    actual_factor_mode: Callable[[Any, str], str],
) -> Tuple[Any, Dict[str, int]]:
    """Collect independent assets in bounded Cerebro batches, then assemble once."""
    import numpy as np
    import pandas as pd

    from backtrader.research import FactorPanel

    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("asset batch size must be a positive integer")
    factor_names = tuple(factor_names)
    assets = tuple(panel["assets"])
    feeds = panel["feeds"]
    if (
        not factor_names
        or not assets
        or len(set(assets)) != len(assets)
        or set(feeds) != set(assets)
        or tuple(expected_classes) != factor_names
    ):
        raise ValueError("asset batches require unique targets and matching ordered factors/feeds")

    research = create_research_spec(config, panel)
    grid = research.grid
    grid_index = grid.index
    study_index = grid_index[(grid_index >= research.start) & (grid_index <= research.end)]
    universe = research.universe.unstack("asset")
    universe.index = pd.DatetimeIndex(study_index, name="close_time", freq=None)
    universe = universe.reindex(index=study_index, columns=list(assets))
    universe.columns.name = None
    factor_values = np.empty(
        (len(study_index), len(assets), len(factor_names)), dtype="float64"
    )
    prices_open = np.empty((len(grid_index), len(assets)), dtype="float64")
    prices_close = np.empty((len(grid_index), len(assets)), dtype="float64")
    total_submits = 0
    total_cancels = 0
    assigned_assets = []
    source_identity = None

    for first in range(0, len(assets), batch_size):
        batch_assets = assets[first : first + batch_size]
        batch_input = dict(panel)
        batch_input["assets"] = batch_assets
        batch_strategy = batch_panel = batch_broker = None
        release_refs = None
        batch_verified = False
        try:
            batch_strategy, batch_panel, batch_broker = run_native_collection(
                config, batch_input, runnext, consume_source_frames=True
            )
            if actual_factor_mode(batch_strategy, factor_mode) != factor_mode:
                raise RuntimeError("asset batch selected an unexpected factor mode")
            specs = batch_strategy._factor_specs_by_name
            if tuple(specs) != factor_names or any(
                specs[name].indicator is not expected_classes[name] for name in factor_names
            ):
                raise RuntimeError("asset batch factor class order or identity changed")
            current_source_identity = tuple(
                (name, specs[name].to_metadata()) for name in factor_names
            )
            if source_identity is None:
                source_identity = current_source_identity
            elif current_source_identity != source_identity:
                raise RuntimeError("factor source or evaluation identity changed between batches")
            if (batch_broker.submit_count, batch_broker.cancel_count) != (0, 0):
                raise RuntimeError("research-only asset batch submitted or cancelled an order")
            if (
                batch_panel.target_order != batch_assets
                or batch_panel.factor_order != factor_names
                or not batch_panel.grid.index.equals(grid_index)
                or batch_panel.start != research.start
                or batch_panel.end != research.end
            ):
                raise RuntimeError("asset batch panel metadata does not match its input slice")
            expected_index = pd.MultiIndex.from_product(
                [study_index, batch_assets], names=("time", "asset")
            )
            if not batch_panel.factors.index.equals(expected_index):
                raise RuntimeError("asset batch factors are missing, duplicated, or reordered")
            if tuple(batch_panel.factors.columns) != factor_names:
                raise RuntimeError("asset batch factor columns changed")
            if (
                not batch_panel.prices_open.index.equals(grid_index)
                or not batch_panel.prices_close.index.equals(grid_index)
                or tuple(batch_panel.prices_open.columns) != batch_assets
                or tuple(batch_panel.prices_close.columns) != batch_assets
            ):
                raise RuntimeError("asset batch price grid or target order changed")
            if (
                batch_panel.groups != {asset: research.groups[asset] for asset in batch_assets}
                or batch_panel.directions != directions
            ):
                raise RuntimeError("asset batch group or direction metadata changed")
            if not batch_panel.universe.equals(universe.loc[:, list(batch_assets)]):
                raise RuntimeError("asset batch universe metadata changed")
            if len(batch_strategy.datas) != len(batch_assets):
                raise RuntimeError("asset batch strategy does not retain every input feed")
            release_refs = _capture_batch_graph_refs(batch_strategy)
            feed_ref_count = sum(kind == "feed" for kind, _ in release_refs)
            factor_ref_count = sum(kind == "factor_instance" for kind, _ in release_refs)
            if feed_ref_count != len(batch_assets) or factor_ref_count < len(factor_names):
                raise RuntimeError("asset batch strategy is missing feed or factor release sentinels")

            last = first + len(batch_assets)
            factor_values[:, first:last, :] = batch_panel.factors.to_numpy(
                dtype="float64", copy=False
            ).reshape(len(study_index), len(batch_assets), len(factor_names))
            prices_open[:, first:last] = batch_panel.prices_open.to_numpy(
                dtype="float64", copy=False
            )
            prices_close[:, first:last] = batch_panel.prices_close.to_numpy(
                dtype="float64", copy=False
            )
            total_submits += batch_broker.submit_count
            total_cancels += batch_broker.cancel_count
            assigned_assets.extend(batch_assets)
            batch_verified = True
        finally:
            del batch_strategy, batch_panel, batch_broker, batch_input
            gc.collect()
            if batch_verified and release_refs is not None:
                expected_counts = {}
                retained_counts = {}
                for kind, reference in release_refs:
                    expected_counts[kind] = expected_counts.get(kind, 0) + 1
                    if reference() is not None:
                        retained_counts[kind] = retained_counts.get(kind, 0) + 1
                retained = {
                    kind: count for kind, count in retained_counts.items() if count
                }
                if retained:
                    details = ", ".join(
                        "%s=%d/%d" % (kind, retained[kind], expected_counts[kind])
                        for kind in ("strategy", "feed", "factor_instance")
                        if retained.get(kind, 0)
                    )
                    raise RuntimeError(
                        "asset batch release check retained live references: %s" % details
                    )

    if tuple(assigned_assets) != assets or feeds:
        raise RuntimeError("asset batch collection did not consume each selected feed exactly once")

    factor_index = pd.MultiIndex.from_product([study_index, assets], names=("time", "asset"))
    merged_factors = pd.DataFrame(
        factor_values.reshape(len(factor_index), len(factor_names)),
        index=factor_index,
        columns=factor_names,
    )
    merged_open = pd.DataFrame(prices_open, index=grid_index, columns=assets)
    merged_close = pd.DataFrame(prices_close, index=grid_index, columns=assets)
    merged_panel = FactorPanel(
        factors=merged_factors,
        grid=grid,
        prices_open=merged_open,
        prices_close=merged_close,
        universe=universe,
        groups=research.groups,
        start=research.start,
        end=research.end,
        target_order=assets,
        factor_order=factor_names,
        directions=directions,
    )
    return merged_panel, {"submit": total_submits, "cancel": total_cancels}


def _capture_batch_graph_refs(strategy: Any) -> Tuple[Tuple[str, Any], ...]:
    """Hold weak references to every top-level object owned by one batch graph."""
    references = []
    seen = set()

    def capture(kind: str, value: Any) -> None:
        identity = id(value)
        if identity not in seen:
            seen.add(identity)
            references.append((kind, weakref.ref(value)))

    capture("strategy", strategy)
    for feed in strategy.datas:
        capture("feed", feed)
    for instances in strategy._factor_instances_by_name.values():
        for instance in instances:
            capture("factor_instance", instance)
    return tuple(references)
