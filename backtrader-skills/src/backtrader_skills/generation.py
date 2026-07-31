"""Render both artifact profiles from one validated StrategySpec IR."""

from __future__ import annotations

import pprint
from dataclasses import dataclass
from typing import Any

from .canonical import bytes_hash, canonical_bytes
from .ir import validate_strategy_spec


@dataclass(frozen=True)
class ArtifactFile:
    relative_path: str
    role: str
    content: bytes

    @property
    def sha256(self) -> str:
        return bytes_hash(self.content)


@dataclass(frozen=True)
class RenderedArtifact:
    spec: dict[str, Any]
    artifact_id: str
    strategy_source_hash: str
    files: tuple[ArtifactFile, ...]


STRATEGY_RUNTIME = r'''
import backtrader as bt


STRATEGY_IR = {ir_literal}


class GeneratedStrategy(bt.Strategy):
    """Generated from StrategySpec v1; direct bt.Strategy init intentionally omits super()."""

    params = {params_literal}
    backtrader_skills_generated = True
    backtrader_skills_spec_hash = {spec_hash_literal}
    backtrader_skills_ir = STRATEGY_IR

    def __init__(self):
        self._skills_indicators = {{}}
        self._skills_orders = {{}}
        self._skills_stop = {{}}
        self._skills_target = {{}}
        self._skills_bar_num = 0
        self._skills_buy_count = 0
        self._skills_sell_count = 0
        self._skills_win_count = 0
        self._skills_loss_count = 0
        self._skills_trade_num = 0
        self._skills_events = []
        self.bar_num = 0
        for state in STRATEGY_IR["state_variables"]:
            setattr(self, state["name"], state["initial"])
        for indicator in STRATEGY_IR["indicators"]:
            data = self.datas[indicator["feed"]]
            line = getattr(data, indicator["line"])
            period = indicator["period"]
            if isinstance(period, str):
                period = getattr(self.p, period)
            if indicator["type"] == "sma":
                value = bt.indicators.SMA(line, period=period)
            elif indicator["type"] == "ema":
                value = bt.indicators.EMA(line, period=period)
            elif indicator["type"] == "rsi":
                value = bt.indicators.RSI(line, period=period)
            elif indicator["type"] == "atr":
                value = bt.indicators.ATR(data, period=period)
            elif indicator["type"] == "stddev":
                value = bt.indicators.StdDev(line, period=period)
            else:
                raise ValueError("unsupported validated indicator")
            self._skills_indicators[indicator["id"]] = value
        self.addminperiod(STRATEGY_IR["minperiod"])

    def _expr(self, node, ago=0):
        kind = node["kind"]
        if kind == "constant":
            return node["value"]
        if kind == "parameter":
            return getattr(self.p, node["name"])
        if kind == "state":
            return getattr(self, node["name"])
        if kind == "data_line":
            return getattr(self.datas[node["feed"]], node["line"])[ago + node["offset"]]
        if kind == "indicator":
            return self._skills_indicators[node["name"]][ago + node["offset"]]
        op = node["op"]
        args = node["args"]
        if op == "cross_up":
            return self._expr(args[0], 0) > self._expr(args[1], 0) and self._expr(
                args[0], -1
            ) <= self._expr(args[1], -1)
        if op == "cross_down":
            return self._expr(args[0], 0) < self._expr(args[1], 0) and self._expr(
                args[0], -1
            ) >= self._expr(args[1], -1)
        if op in ("highest", "lowest"):
            period = int(self._expr(args[1]))
            values = [self._expr(args[0], -offset) for offset in range(period)]
            return max(values) if op == "highest" else min(values)
        values = [self._expr(item, ago) for item in args]
        if op == "and":
            return all(values)
        if op == "or":
            return any(values)
        if op == "not":
            return not values[0]
        if op == "eq":
            return values[0] == values[1]
        if op == "ne":
            return values[0] != values[1]
        if op == "gt":
            return values[0] > values[1]
        if op == "gte":
            return values[0] >= values[1]
        if op == "lt":
            return values[0] < values[1]
        if op == "lte":
            return values[0] <= values[1]
        if op == "add":
            return sum(values)
        if op == "sub":
            return values[0] - values[1]
        if op == "mul":
            result = 1.0
            for value in values:
                result *= value
            return result
        if op == "div":
            return values[0] / values[1]
        if op == "abs":
            return abs(values[0])
        if op == "min":
            return min(values)
        if op == "max":
            return max(values)
        raise ValueError("unsupported validated expression")

    def _act(self, action):
        feed = action["feed"]
        data = self.datas[feed]
        kind = action["kind"]
        if kind == "cancel":
            order = self._skills_orders.get(feed)
            if order is not None:
                self.cancel(order)
            return
        if kind == "set_stop":
            self._skills_stop[feed] = float(self._expr(action["price"]))
            return
        if kind == "set_target":
            self._skills_target[feed] = float(self._expr(action["price"]))
            return
        if kind == "close":
            self._skills_orders[feed] = self.close(data=data)
            return
        size = self._expr(action["size"]) if "size" in action else None
        kwargs = {{"data": data}}
        if size is not None:
            kwargs["size"] = size
        if action["order_type"] == "limit":
            kwargs["exectype"] = bt.Order.Limit
            kwargs["price"] = self._expr(action["price"])
        elif action["order_type"] == "stop":
            kwargs["exectype"] = bt.Order.Stop
            kwargs["price"] = self._expr(action["price"])
        if kind == "buy":
            self._skills_orders[feed] = self.buy(**kwargs)
        elif kind == "sell":
            self._skills_orders[feed] = self.sell(**kwargs)

    def _run_rules(self, stage):
        fired_groups = set()
        for rule in STRATEGY_IR["state_rules"]:
            if rule["stage"] not in (stage, "always"):
                continue
            group = rule.get("exclusive_group")
            if group and group in fired_groups:
                continue
            if self._expr(rule["when"]):
                for action in rule["actions"]:
                    self._act(action)
                if group:
                    fired_groups.add(group)

    def prenext(self):
        self._skills_bar_num += 1
        self.bar_num = self._skills_bar_num
        self._run_rules("prenext")

    def nextstart(self):
        self._skills_bar_num += 1
        self.bar_num = self._skills_bar_num
        self._run_rules("nextstart")

    def next(self):
        self._skills_bar_num += 1
        self.bar_num = self._skills_bar_num
        for feed, stop in list(self._skills_stop.items()):
            if self.getposition(self.datas[feed]).size and self.datas[feed].close[0] <= stop:
                self._skills_orders[feed] = self.close(data=self.datas[feed])
        for feed, target in list(self._skills_target.items()):
            if self.getposition(self.datas[feed]).size and self.datas[feed].close[0] >= target:
                self._skills_orders[feed] = self.close(data=self.datas[feed])
        self._run_rules("next")

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self._skills_buy_count += 1
            elif order.issell():
                self._skills_sell_count += 1
        if order.status in (
            order.Completed,
            order.Canceled,
            order.Margin,
            order.Rejected,
            order.Expired,
        ):
            self._skills_events.append(
                {{
                    "sequence": len(self._skills_events),
                    "kind": "order",
                    "data": order.data._name,
                    "size": float(order.executed.size),
                    "price": float(order.executed.price),
                    "status": order.getstatusname(),
                }}
            )

    def notify_trade(self, trade):
        if trade.isclosed:
            self._skills_trade_num += 1
            if trade.pnlcomm >= 0:
                self._skills_win_count += 1
            else:
                self._skills_loss_count += 1
            self._skills_events.append(
                {{
                    "sequence": len(self._skills_events),
                    "kind": "trade",
                    "data": trade.data._name,
                    "size": float(trade.size),
                    "price": float(trade.price),
                    "status": "won" if trade.pnlcomm >= 0 else "lost",
                }}
            )
'''.strip()


SINGLE_TEST_SUFFIX = r"""


def test_generated_strategy_contract():
    # The approved runner performs both execution modes.
    assert issubclass(GeneratedStrategy, bt.Strategy)
    assert GeneratedStrategy.backtrader_skills_generated is True
    assert GeneratedStrategy.backtrader_skills_spec_hash == STRATEGY_IR["spec_hash"]
    assert STRATEGY_IR["dataset_id"].startswith("ds_")
    assert len(STRATEGY_IR["dataset_id"]) == 67
""".strip()


def render_strategy(spec_value: dict[str, Any]) -> RenderedArtifact:
    spec = validate_strategy_spec(spec_value)
    strategy_ir = {
        "spec_version": spec["spec_version"],
        "spec_hash": spec["spec_hash"],
        "dataset_id": spec["dataset_id"],
        "archetype": spec["archetype"],
        "feed_count": len(spec["feeds"]),
        "feeds": spec["feeds"],
        "parameters": spec["parameters"],
        "entry": spec["entry"],
        "exit": spec["exit"],
        "risk": spec["risk"],
        "cash": spec["cash"],
        "commission": spec["commission"],
        "sizer": spec["sizing"],
        **spec["ir"],
    }
    ir_literal = pprint.pformat(strategy_ir, width=96, sort_dicts=True)
    params = tuple((item["name"], item["default"]) for item in spec["parameters"])
    strategy_source = (
        STRATEGY_RUNTIME.format(
            ir_literal=ir_literal,
            params_literal=repr(params),
            spec_hash_literal=repr(spec["spec_hash"]),
        ).strip()
        + "\n"
    )
    strategy_hash = bytes_hash(strategy_source.encode("utf-8"))
    artifact_id = f"art_{spec['spec_hash'][:12]}"
    slug = spec["slug"]
    archetype = spec["archetype"]
    files: tuple[ArtifactFile, ...]
    if spec["output_profile"] == "single_test":
        relative = (
            f"tests/functional/strategies/generated/{archetype}/" f"test_{artifact_id}_{slug}.py"
        )
        test_source = strategy_source + "\n" + SINGLE_TEST_SUFFIX + "\n"
        files = (
            ArtifactFile(
                relative_path=relative, role="generated_test", content=test_source.encode()
            ),
        )
    else:
        base = f"strategies/generated/{archetype}/{artifact_id}_{slug}"
        config = {
            "schema_version": "generated-strategy-config-v1",
            "artifact_id": artifact_id,
            "strategy_spec": spec,
            "strategy_source_hash": strategy_hash,
        }
        readme = (
            f"# {spec['name']}\n\n"
            f"Generated from `StrategySpec v1` hash `{spec['spec_hash']}`.\n\n"
            "Run only through `backtrader-skills run prepare/execute`; the fixed runner "
            "revalidates the dataset and candidate hashes before execution.\n"
        )
        files = (
            ArtifactFile(
                relative_path=f"{base}/strategy.py",
                role="strategy",
                content=strategy_source.encode(),
            ),
            ArtifactFile(
                relative_path=f"{base}/config.json",
                role="configuration",
                content=canonical_bytes(config) + b"\n",
            ),
            ArtifactFile(
                relative_path=f"{base}/README.md",
                role="documentation",
                content=readme.encode(),
            ),
        )
    return RenderedArtifact(
        spec=spec,
        artifact_id=artifact_id,
        strategy_source_hash=strategy_hash,
        files=files,
    )


def render_summary(artifact: RenderedArtifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "spec_hash": artifact.spec["spec_hash"],
        "strategy_source_hash": artifact.strategy_source_hash,
        "output_profile": artifact.spec["output_profile"],
        "files": [
            {
                "path": item.relative_path,
                "role": item.role,
                "bytes": len(item.content),
                "sha256": item.sha256,
            }
            for item in artifact.files
        ],
    }
