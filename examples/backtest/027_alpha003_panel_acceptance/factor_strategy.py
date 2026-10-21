"""Example-local panel prototype: fields, cross-sectional rank, correlation, negation.

This is not the public Iteration 45 API. A declaration builds a graph once;
the shared strategy advances it after Cerebro has synchronized the feeds.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import math

import backtrader as bt
import pandas as pd


@dataclass(frozen=True)
class PanelExpr:
    """Immutable expression; structural equality enables shared evaluation."""

    operation: str
    inputs: tuple = ()
    field: str = ""
    window: int = 0

    def __neg__(self):
        return PanelExpr("negate", (self,))


class PanelContext:
    """Only the four operations needed by this prototype are available."""

    open = PanelExpr("field", field="open")
    volume = PanelExpr("field", field="volume")

    def rank(self, expression):
        return PanelExpr("rank", (expression,))

    def correlation(self, left, right, window):
        if type(window) is not int or window < 2:
            raise ValueError("correlation window must be an integer >= 2")
        return PanelExpr("correlation", (left, right), window=window)


class PanelFactorIndicator(bt.Indicator):
    """Declaration container: build() is called; no Indicator instance is made."""

    def __new__(cls, *args, **kwargs):
        raise TypeError("Use this panel declaration in FactorStrategy; do not instantiate it")

    @classmethod
    def build(cls, ctx):
        raise NotImplementedError


class PanelEngine:
    """Small event-driven evaluator for a fixed asset universe and explicit grid."""

    def __init__(self, assets, outputs):
        self.assets = tuple(sorted(assets))
        self.outputs = outputs
        ordered = []
        seen = set()

        def visit(node):
            if not isinstance(node, PanelExpr):
                raise TypeError("build() must return PanelExpr nodes")
            if node in seen:
                return
            if node.operation not in {"field", "rank", "correlation", "negate"}:
                raise ValueError("unsupported prototype operation: " + node.operation)
            for child in node.inputs:
                visit(child)
            seen.add(node)
            ordered.append(node)

        for expression in outputs.values():
            visit(expression)
        self.nodes = tuple(ordered)
        self.node_ids = {node: "n%d" % index for index, node in enumerate(self.nodes)}
        self.history = defaultdict(list)
        self.evaluation_counts = dict.fromkeys(self.node_ids.values(), 0)
        self.lookbacks = {}
        for node in self.nodes:
            depth = max((self.lookbacks[x] for x in node.inputs), default=0)
            self.lookbacks[node] = depth + (
                node.window - 1 if node.operation == "correlation" else 0
            )
        self.rows = []
        self.diagnostics = []

    def advance(self, timestamp, snapshot):
        """Evaluate every shared node once, using only the current closed bars."""
        for node in self.nodes:
            values, reasons = self._evaluate(node, snapshot)
            self.history[node].append(values)
            node_id = self.node_ids[node]
            self.evaluation_counts[node_id] += 1
            for asset in self.assets:
                self.diagnostics.append(
                    {
                        "time": timestamp,
                        "asset": asset,
                        "node": node_id,
                        "operation": node.operation,
                        "field": node.field,
                        "value": values[asset],
                        "reason": reasons[asset],
                    }
                )
        for asset in self.assets:
            row = {"time": timestamp, "asset": asset}
            row.update({name: self.history[node][-1][asset] for name, node in self.outputs.items()})
            self.rows.append(row)

    def _evaluate(self, node, snapshot):
        values = dict.fromkeys(self.assets, math.nan)
        reasons = dict.fromkeys(self.assets, "MISSING_INPUT")
        if node.operation == "field":
            for asset in self.assets:
                value = float(snapshot[asset][node.field])
                if math.isinf(value):
                    raise ValueError("infinite source value: %s/%s" % (asset, node.field))
                values[asset] = value
                if math.isfinite(value):
                    reasons[asset] = "OK"
        elif node.operation == "rank":
            source = self.history[node.inputs[0]][-1]
            ordered = sorted(
                (value, asset) for asset, value in source.items() if math.isfinite(value)
            )
            start = 0
            while start < len(ordered):
                end = start + 1
                while end < len(ordered) and ordered[end][0] == ordered[start][0]:
                    end += 1
                rank = (start + 1 + end) / (2.0 * len(ordered))
                for _, asset in ordered[start:end]:
                    values[asset], reasons[asset] = rank, "OK"
                start = end
        elif node.operation == "negate":
            source = self.history[node.inputs[0]][-1]
            for asset in self.assets:
                values[asset] = -source[asset]
                reasons[asset] = "OK" if math.isfinite(source[asset]) else "UPSTREAM_INVALID"
        else:
            left, right = (self.history[child] for child in node.inputs)
            for asset in self.assets:
                if len(left) < node.window:
                    reasons[asset] = "WARMUP"
                    continue
                x = [row[asset] for row in left[-node.window :]]
                y = [row[asset] for row in right[-node.window :]]
                if not all(math.isfinite(v) for v in x + y):
                    reasons[asset] = "INCOMPLETE_WINDOW"
                    continue
                mx, my = math.fsum(x) / node.window, math.fsum(y) / node.window
                dx, dy = [v - mx for v in x], [v - my for v in y]
                xx, yy = math.fsum(v * v for v in dx), math.fsum(v * v for v in dy)
                if xx == 0 or yy == 0:
                    reasons[asset] = "ZERO_VARIANCE"
                    continue
                values[asset] = math.fsum(a * b for a, b in zip(dx, dy)) / math.sqrt(xx * yy)
                reasons[asset] = "OK"
        return values, reasons


def _utc_bar_time(data):
    return bt.num2date(data.datetime[0]).replace(tzinfo=timezone.utc)


class FactorStrategy(bt.Strategy):
    """Reusable example template. Factor authors only provide a build() class."""

    params = (("factors", None), ("grid", None))

    def __init__(self):
        # Direct bt.Strategy subclasses in this fork must not call super().__init__().
        self._feeds = {data._name: data for data in self.datas}
        if len(self._feeds) != len(self.datas) or not all(self._feeds):
            raise ValueError("feed names must be non-empty and unique")
        self._grid = tuple(self.p.grid)
        if (
            not self._grid
            or any(not isinstance(t, datetime) or t.tzinfo is None for t in self._grid)
            or any(a >= b for a, b in zip(self._grid, self._grid[1:]))
        ):
            raise ValueError("grid must contain strictly increasing timezone-aware datetimes")
        self._grid = tuple(t.astimezone(timezone.utc) for t in self._grid)
        outputs = {}
        for name, spec in self.p.factors.items():
            if not isinstance(name, str) or not name or name in {"time", "asset"}:
                raise ValueError("factor names must be non-empty and not time/asset")
            cls = spec["indicator"]
            if not isinstance(cls, type) or not issubclass(cls, PanelFactorIndicator):
                raise TypeError("indicator must be a PanelFactorIndicator declaration class")
            if (
                spec.get("execution") != "panel"
                or spec.get("operator_profile") != "alpha101-v1"
                or spec.get("field_bindings")
                != {"open": "feedline:open", "volume": "feedline:volume"}
            ):
                raise ValueError("prototype requires panel/alpha101-v1 and open/volume bindings")
            outputs[name] = cls.build(PanelContext())
        if not outputs:
            raise ValueError("at least one factor declaration is required")
        self.engine = PanelEngine(self._feeds, outputs)
        self._grid_cursor = 0
        self._finished = False

    def _advance_grid(self, now):
        while self._grid_cursor < len(self._grid):
            timestamp = self._grid[self._grid_cursor]
            if timestamp > now:
                break
            snapshot = {}
            for asset, data in self._feeds.items():
                fresh = len(data) and _utc_bar_time(data) == timestamp
                snapshot[asset] = {
                    field: float(getattr(data, field)[0]) if fresh else math.nan
                    for field in ("open", "volume")
                }
            self.engine.advance(timestamp, snapshot)
            self._grid_cursor += 1

    def prenext(self):
        self.next()

    def nextstart(self):
        self.next()

    def next(self):
        clocks = [_utc_bar_time(data) for data in self.datas if len(data)]
        if clocks:
            self._advance_grid(max(clocks))

    def stop(self):
        self._advance_grid(self._grid[-1])
        self._finished = True

    def get_dataset(self):
        if not self._finished:
            raise RuntimeError("dataset is available after Cerebro.run() has finished")
        return pd.DataFrame(self.engine.rows).set_index(["time", "asset"]).sort_index()

    def get_diagnostics(self):
        return pd.DataFrame(self.engine.diagnostics)
