"""StrategySpec v1 and its restricted, typed strategy IR."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from .canonical import canonical_hash, safe_identifier
from .errors import ContractError

ARCHETYPES = (
    "single_data_indicator",
    "multi_indicator_system",
    "multi_asset_allocation",
    "multi_timeframe",
    "pairs_spread",
    "order_risk",
    "precomputed_ml",
)
OUTPUT_PROFILES = ("single_test", "python_bundle")
EXPRESSION_KINDS = {"constant", "parameter", "data_line", "indicator", "state", "operator"}
OPERATORS = {
    "and",
    "or",
    "not",
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "add",
    "sub",
    "mul",
    "div",
    "abs",
    "min",
    "max",
    "cross_up",
    "cross_down",
    "highest",
    "lowest",
}
ACTIONS = {"buy", "sell", "close", "cancel", "set_stop", "set_target"}
INDICATORS = {"sma", "ema", "rsi", "atr", "stddev"}
ORDER_TYPES = {"market", "limit", "stop"}
STAGES = {"prenext", "nextstart", "next", "always"}
PARAMETER_TYPES = {"int", "float", "bool", "str"}
DATA_LINES = {"open", "high", "low", "close", "volume", "openinterest"}


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _typed_default(parameter: dict[str, Any]) -> Any:
    parameter_type = parameter["type"]
    default = parameter["default"]
    if parameter_type == "int" and (not isinstance(default, int) or isinstance(default, bool)):
        raise ContractError(f"parameter {parameter['name']} default must be int")
    if parameter_type == "float":
        if not isinstance(default, (int, float)) or isinstance(default, bool):
            raise ContractError(f"parameter {parameter['name']} default must be float")
        default = float(default)
        if not math.isfinite(default):
            raise ContractError(f"parameter {parameter['name']} default must be finite")
    if parameter_type == "bool" and not isinstance(default, bool):
        raise ContractError(f"parameter {parameter['name']} default must be bool")
    if parameter_type == "str" and not isinstance(default, str):
        raise ContractError(f"parameter {parameter['name']} default must be str")
    minimum = parameter.get("minimum")
    maximum = parameter.get("maximum")
    if minimum is not None and default < minimum:
        raise ContractError(f"parameter {parameter['name']} default is below minimum")
    if maximum is not None and default > maximum:
        raise ContractError(f"parameter {parameter['name']} default is above maximum")
    return default


def validate_expression(
    value: Any,
    *,
    parameters: set[str],
    indicators: set[str],
    states: set[str],
    feed_count: int,
    custom_lines: set[str],
    depth: int = 0,
) -> dict[str, Any]:
    if depth > 20:
        raise ContractError("expression nesting exceeds 20 levels")
    node = deepcopy(_require_object(value, "Expression"))
    kind = node.get("kind")
    if kind not in EXPRESSION_KINDS:
        raise ContractError(f"unsupported Expression kind: {kind}")
    if kind == "constant":
        constant = node.get("value")
        if not isinstance(constant, (bool, int, float)) or (
            isinstance(constant, float) and not math.isfinite(constant)
        ):
            raise ContractError("constant Expression must be a finite scalar")
        return {"kind": kind, "value": constant}
    if kind == "parameter":
        name = str(node.get("name", ""))
        if name not in parameters:
            raise ContractError(f"unknown parameter reference: {name}")
        return {"kind": kind, "name": name}
    if kind == "state":
        name = str(node.get("name", ""))
        if name not in states:
            raise ContractError(f"unknown state reference: {name}")
        return {"kind": kind, "name": name}
    if kind in {"data_line", "indicator"}:
        feed = int(node.get("feed", 0))
        if feed < 0 or feed >= feed_count:
            raise ContractError(f"feed index is outside the declared range: {feed}")
        offset = int(node.get("offset", 0))
        if offset > 0:
            raise ContractError("positive data offsets are look-ahead and are forbidden")
        if offset < -10000:
            raise ContractError("data offset is outside the supported range")
        if kind == "data_line":
            line = str(node.get("line", ""))
            if line not in DATA_LINES | custom_lines:
                raise ContractError(f"unsupported data line: {line}")
            return {"kind": kind, "feed": feed, "line": line, "offset": offset}
        name = str(node.get("name", ""))
        if name not in indicators:
            raise ContractError(f"unknown indicator reference: {name}")
        return {"kind": kind, "name": name, "offset": offset}
    operator = node.get("op")
    if operator not in OPERATORS:
        raise ContractError(f"unsupported Expression operator: {operator}")
    raw_args = node.get("args")
    if not isinstance(raw_args, list):
        raise ContractError("operator Expression args must be a list")
    arity = {
        "not": (1, 1),
        "abs": (1, 1),
        "cross_up": (2, 2),
        "cross_down": (2, 2),
        "highest": (2, 2),
        "lowest": (2, 2),
        "eq": (2, 2),
        "ne": (2, 2),
        "gt": (2, 2),
        "gte": (2, 2),
        "lt": (2, 2),
        "lte": (2, 2),
        "sub": (2, 2),
        "div": (2, 2),
        "and": (2, 16),
        "or": (2, 16),
        "add": (2, 16),
        "mul": (2, 16),
        "min": (2, 16),
        "max": (2, 16),
    }[operator]
    if not arity[0] <= len(raw_args) <= arity[1]:
        raise ContractError(f"operator {operator} expects {arity[0]}..{arity[1]} arguments")
    args = [
        validate_expression(
            item,
            parameters=parameters,
            indicators=indicators,
            states=states,
            feed_count=feed_count,
            custom_lines=custom_lines,
            depth=depth + 1,
        )
        for item in raw_args
    ]
    if operator in {"highest", "lowest"}:
        period = args[1]
        if period["kind"] != "constant" or not isinstance(period["value"], int):
            raise ContractError(f"{operator} period must be an integer constant")
        if not 1 <= period["value"] <= 10000:
            raise ContractError(f"{operator} period is outside 1..10000")
    return {"kind": kind, "op": operator, "args": args}


def validate_strategy_spec(value: dict[str, Any]) -> dict[str, Any]:
    source = deepcopy(_require_object(value, "StrategySpec"))
    aliases = {
        "version": "spec_version",
        "strategy_name": "name",
        "strategy_slug": "slug",
        "target_archetype": "archetype",
        "archetype_id": "archetype",
        "profile": "output_profile",
        "target_profile": "output_profile",
        "output": "output_profile",
        "dataset_manifest_id": "dataset_id",
        "data_feeds": "feeds",
        "params": "parameters",
    }
    for alias, canonical in aliases.items():
        if canonical not in source and alias in source:
            source[canonical] = source[alias]
    if "dataset_id" not in source:
        dataset_alias = source.get("dataset")
        if isinstance(dataset_alias, str):
            source["dataset_id"] = dataset_alias
        elif isinstance(dataset_alias, dict):
            source["dataset_id"] = dataset_alias.get("dataset_id", dataset_alias.get("id"))
    archetype_aliases = {
        "single_data": "single_data_indicator",
        "multi_indicator": "multi_indicator_system",
        "multi_asset": "multi_asset_allocation",
        "multi_data": "multi_asset_allocation",
        "multi_clock": "multi_timeframe",
        "pairs": "pairs_spread",
        "order_management": "order_risk",
        "risk_management": "order_risk",
        "ml_signals": "precomputed_ml",
        "machine_learning": "precomputed_ml",
    }
    profile_aliases = {
        "test": "single_test",
        "pytest": "single_test",
        "bundle": "python_bundle",
        "python": "python_bundle",
    }
    source_archetype = source.get("archetype")
    source["archetype"] = (
        archetype_aliases.get(source_archetype, source_archetype)
        if isinstance(source_archetype, str)
        else source_archetype
    )
    source_profile = source.get("output_profile")
    source["output_profile"] = (
        profile_aliases.get(source_profile, source_profile)
        if isinstance(source_profile, str)
        else source_profile
    )
    if source.get("spec_version") != "strategy-spec-v1":
        raise ContractError("spec_version must be strategy-spec-v1")
    name = str(source.get("name", "")).strip()
    if not name or len(name) > 100:
        raise ContractError("strategy name must contain 1 to 100 characters")
    slug = str(source.get("slug", ""))
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", slug):
        raise ContractError("slug must be lowercase kebab-case")
    archetype = source.get("archetype")
    if archetype not in ARCHETYPES:
        raise ContractError(f"unsupported archetype: {archetype}")
    output_profile = source.get("output_profile")
    if output_profile not in OUTPUT_PROFILES:
        raise ContractError(f"unsupported output_profile: {output_profile}")
    dataset_id = safe_identifier(str(source.get("dataset_id", "")), field="dataset_id")
    if not re.fullmatch(r"ds_[0-9a-f]{64}", dataset_id):
        raise ContractError("dataset_id must be 'ds_' followed by the full 64-hex semantic hash")
    raw_feeds = source.get("feeds")
    if raw_feeds is None:
        raw_feeds = [
            {"name": f"data{index}", "role": "execution" if index == 0 else "signal"}
            for index in range(int(source.get("feed_count", 1)))
        ]
    if not isinstance(raw_feeds, list) or not raw_feeds:
        raise ContractError("StrategySpec feeds must be a non-empty list")
    feeds = []
    feed_names: set[str] = set()
    for index, raw_feed in enumerate(raw_feeds):
        if isinstance(raw_feed, str):
            raw_feed = {"name": raw_feed}
        feed = _require_object(raw_feed, "strategy feed")
        feed_name = safe_identifier(
            str(feed.get("name", f"data{index}")), field="strategy feed name"
        )
        if feed_name in feed_names:
            raise ContractError(f"duplicate strategy feed: {feed_name}")
        role = str(feed.get("role", "execution" if index == 0 else "signal"))
        if role not in {"execution", "signal", "benchmark", "hedge", "cash_proxy"}:
            raise ContractError(f"unsupported strategy feed role: {role}")
        feeds.append(
            {
                "name": feed_name,
                "role": role,
                "symbol": str(feed.get("symbol", feed_name)),
                "timeframe": str(feed.get("timeframe", "manifest")),
                "lines": sorted({str(line) for line in feed.get("lines", list(DATA_LINES))}),
            }
        )
        feed_names.add(feed_name)
    feed_count = len(feeds)
    if feed_count < 1 or feed_count > 32:
        raise ContractError("feed_count must be between 1 and 32")
    ir_source = source.get("ir", source)
    if not isinstance(ir_source, dict):
        raise ContractError("StrategySpec ir must be an object")
    custom_lines = {
        str(item) for item in ir_source.get("custom_lines", source.get("custom_lines", []))
    }
    parameters: list[dict[str, Any]] = []
    parameter_names: set[str] = set()
    raw_parameters = source.get("parameters", [])
    if isinstance(raw_parameters, dict):
        raw_parameters = [
            {
                "name": key,
                "type": (
                    "bool"
                    if isinstance(default, bool)
                    else (
                        "int"
                        if isinstance(default, int)
                        else "float" if isinstance(default, float) else "str"
                    )
                ),
                "default": default,
            }
            for key, default in raw_parameters.items()
        ]
    for raw in raw_parameters:
        parameter = _require_object(raw, "parameter")
        parameter_name = safe_identifier(str(parameter.get("name", "")), field="parameter")
        if parameter_name in parameter_names:
            raise ContractError(f"duplicate parameter: {parameter_name}")
        parameter_type = parameter.get("type")
        if parameter_type not in PARAMETER_TYPES:
            raise ContractError(f"unsupported parameter type: {parameter_type}")
        normalized_parameter = {
            "name": parameter_name,
            "type": parameter_type,
            "default": parameter.get("default"),
        }
        if "minimum" in parameter:
            normalized_parameter["minimum"] = parameter["minimum"]
        if "maximum" in parameter:
            normalized_parameter["maximum"] = parameter["maximum"]
        normalized_parameter["default"] = _typed_default(normalized_parameter)
        parameters.append(normalized_parameter)
        parameter_names.add(parameter_name)
    indicators: list[dict[str, Any]] = []
    indicator_names: set[str] = set()
    for raw in ir_source.get("indicators", []):
        indicator = _require_object(raw, "indicator")
        indicator_name = safe_identifier(str(indicator.get("id", "")), field="indicator id")
        if indicator_name in indicator_names:
            raise ContractError(f"duplicate indicator id: {indicator_name}")
        indicator_type = indicator.get("type")
        if indicator_type not in INDICATORS:
            raise ContractError(f"unsupported indicator type: {indicator_type}")
        feed_index = int(indicator.get("feed", 0))
        if feed_index < 0 or feed_index >= feed_count:
            raise ContractError(f"indicator feed index is outside the declared range: {feed_index}")
        line = str(indicator.get("line", "close"))
        if line not in DATA_LINES | custom_lines:
            raise ContractError(f"indicator uses unsupported line: {line}")
        period = indicator.get("period", 14)
        if isinstance(period, str):
            if period not in parameter_names:
                raise ContractError(f"indicator period references unknown parameter: {period}")
        elif not isinstance(period, int) or not 1 <= period <= 10000:
            raise ContractError("indicator period must be an integer or parameter name")
        indicators.append(
            {
                "id": indicator_name,
                "type": indicator_type,
                "feed": feed_index,
                "line": line,
                "period": period,
            }
        )
        indicator_names.add(indicator_name)
    states = []
    state_names: set[str] = set()
    for raw in ir_source.get("state_variables", []):
        state = _require_object(raw, "state variable")
        state_name = safe_identifier(str(state.get("name", "")), field="state variable")
        if state_name in state_names:
            raise ContractError(f"duplicate state variable: {state_name}")
        initial = state.get("initial")
        if not isinstance(initial, (bool, int, float, str)) or (
            isinstance(initial, float) and not math.isfinite(initial)
        ):
            raise ContractError("state variable initial value must be a finite scalar")
        states.append({"name": state_name, "initial": initial})
        state_names.add(state_name)
    rules: list[dict[str, Any]] = []
    rule_names: set[str] = set()
    raw_rules = ir_source.get("state_rules", [])
    if not raw_rules:
        raw_rules = []
        for rule_name, priority in (("entry", 10), ("exit", 20)):
            section = source.get(rule_name)
            if isinstance(section, dict) and "when" in section and "actions" in section:
                raw_rules.append(
                    {
                        "name": rule_name,
                        "stage": section.get("stage", "next"),
                        "when": section["when"],
                        "actions": section["actions"],
                        "priority": section.get("priority", priority),
                        "exclusive_group": section.get("exclusive_group", "position"),
                    }
                )
    for raw in raw_rules:
        rule = _require_object(raw, "StateRule")
        rule_name = safe_identifier(str(rule.get("name", "")), field="rule")
        if rule_name in rule_names:
            raise ContractError(f"duplicate StateRule name: {rule_name}")
        stage = rule.get("stage", "next")
        if stage not in STAGES:
            raise ContractError(f"unsupported StateRule stage: {stage}")
        when = validate_expression(
            rule.get("when"),
            parameters=parameter_names,
            indicators=indicator_names,
            states=state_names,
            feed_count=feed_count,
            custom_lines=custom_lines,
        )
        raw_actions = rule.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raise ContractError("StateRule must contain at least one Action")
        actions = [
            _validate_action(
                item,
                parameters=parameter_names,
                indicators=indicator_names,
                states=state_names,
                feed_count=feed_count,
                custom_lines=custom_lines,
            )
            for item in raw_actions
        ]
        rules.append(
            {
                "name": rule_name,
                "stage": stage,
                "when": when,
                "actions": actions,
                "priority": int(rule.get("priority", 100)),
                "exclusive_group": rule.get("exclusive_group"),
            }
        )
        rule_names.add(rule_name)
    if not rules:
        raise ContractError("StrategySpec requires at least one StateRule")
    allowed_imports = sorted(set(source.get("allowed_imports", ["backtrader"])))
    if allowed_imports != ["backtrader"]:
        raise ContractError("P0 generated strategies only allow the backtrader import")
    run_modes = source.get("run_modes", ["runonce", "runnext"])
    if run_modes != ["runonce", "runnext"]:
        raise ContractError("P0 StrategySpec run_modes must be exactly runonce then runnext")
    entry_default = [
        rule["name"]
        for rule in rules
        if rule["name"] in {"enter", "entry"} or rule["name"].startswith("enter_")
    ]
    exit_default = [
        rule["name"] for rule in rules if rule["name"] == "exit" or rule["name"].startswith("exit_")
    ]
    entry_refs = _rule_references(source.get("entry"), entry_default)
    exit_refs = _rule_references(source.get("exit"), exit_default)
    if not entry_refs or not exit_refs:
        raise ContractError("StrategySpec must identify entry and exit StateRule names")
    unknown_refs = (set(entry_refs) | set(exit_refs)) - rule_names
    if unknown_refs:
        raise ContractError(
            f"entry/exit reference unknown StateRules: {', '.join(sorted(unknown_refs))}"
        )
    sizing_source = source.get("sizing", source.get("sizer", {}))
    if not isinstance(sizing_source, dict):
        raise ContractError("sizing must be an object")
    sizing: dict[str, Any] = {
        "type": str(sizing_source.get("type", "fixed")),
        "stake": int(sizing_source.get("stake", 1)),
    }
    if sizing["type"] != "fixed" or sizing["stake"] < 1:
        raise ContractError("P0 sizing supports fixed positive stake only")
    risk = source.get("risk", {})
    if not isinstance(risk, dict):
        raise ContractError("risk must be an object")
    sorted_rules = sorted(rules, key=lambda item: (item["priority"], item["name"]))
    normalized = {
        "spec_version": "strategy-spec-v1",
        "name": name,
        "slug": slug,
        "category": str(source.get("category", archetype)),
        "archetype": archetype,
        "output_profile": output_profile,
        "dataset_id": dataset_id,
        "feeds": feeds,
        "parameters": parameters,
        "entry": {"rule_names": entry_refs},
        "exit": {"rule_names": exit_refs},
        "sizing": sizing,
        "risk": risk,
        "cash": float(source.get("cash", 100000.0)),
        "commission": float(source.get("commission", 0.0)),
        "run_modes": run_modes,
        "allowed_imports": allowed_imports,
        "non_goals": [str(item) for item in source.get("non_goals", [])],
        "undecided": [str(item) for item in source.get("undecided", [])],
        "ir": {
            "ir_version": "strategy-ir-v1",
            "custom_lines": sorted(custom_lines),
            "indicators": indicators,
            "state_variables": states,
            "state_rules": sorted_rules,
            "minperiod": int(ir_source.get("minperiod", source.get("minperiod", 1))),
        },
        "extensions": {
            "backtrader_skills": {
                "analyzers": [
                    "sharpe_ratio",
                    "annual_return",
                    "max_drawdown",
                    "trade_analyzer",
                ]
            }
        },
    }
    if normalized["ir"]["minperiod"] < 1:
        raise ContractError("minperiod must be positive")
    if normalized["cash"] <= 0 or not math.isfinite(normalized["cash"]):
        raise ContractError("cash must be finite and positive")
    if normalized["commission"] < 0 or not math.isfinite(normalized["commission"]):
        raise ContractError("commission must be finite and non-negative")
    normalized["spec_hash"] = canonical_hash(normalized)
    return normalized


def _rule_references(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, dict) and "rule_names" in value:
        references = value["rule_names"]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        references = value
    else:
        return sorted(default)
    if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
        raise ContractError("entry/exit rule_names must be a string list")
    return sorted(set(references))


def _validate_action(
    value: Any,
    *,
    parameters: set[str],
    indicators: set[str],
    states: set[str],
    feed_count: int,
    custom_lines: set[str],
) -> dict[str, Any]:
    action = _require_object(value, "Action")
    kind = action.get("kind")
    if kind not in ACTIONS:
        raise ContractError(f"unsupported Action kind: {kind}")
    feed = int(action.get("feed", 0))
    if feed < 0 or feed >= feed_count:
        raise ContractError(f"Action feed index is outside the declared range: {feed}")
    normalized: dict[str, Any] = {"kind": kind, "feed": feed}
    if kind in {"buy", "sell"}:
        order_type = action.get("order_type", "market")
        if order_type not in ORDER_TYPES:
            raise ContractError(f"unsupported order type: {order_type}")
        normalized["order_type"] = order_type
        if "size" in action:
            normalized["size"] = validate_expression(
                action["size"],
                parameters=parameters,
                indicators=indicators,
                states=states,
                feed_count=feed_count,
                custom_lines=custom_lines,
            )
        if order_type != "market":
            if "price" not in action:
                raise ContractError(f"{order_type} order requires a price Expression")
            normalized["price"] = validate_expression(
                action["price"],
                parameters=parameters,
                indicators=indicators,
                states=states,
                feed_count=feed_count,
                custom_lines=custom_lines,
            )
    if kind in {"set_stop", "set_target"}:
        if "price" not in action:
            raise ContractError(f"{kind} requires a price Expression")
        normalized["price"] = validate_expression(
            action["price"],
            parameters=parameters,
            indicators=indicators,
            states=states,
            feed_count=feed_count,
            custom_lines=custom_lines,
        )
    return normalized


def default_strategy_spec(
    archetype: str,
    output_profile: str,
    dataset_id: str,
    *,
    feed_count: int = 1,
    custom_lines: list[str] | None = None,
) -> dict[str, Any]:
    """Build a real, deterministic starter StrategySpec for an acceptance matrix cell."""

    if archetype not in ARCHETYPES or output_profile not in OUTPUT_PROFILES:
        raise ContractError("unsupported archetype or output profile")
    custom_lines = custom_lines or []
    effective_feed_count = max(
        feed_count, 2 if archetype in {"multi_asset_allocation", "pairs_spread"} else 1
    )
    signal_feed = 1 if archetype == "multi_timeframe" and feed_count > 1 else 0
    parameters = [
        {"name": "fast_period", "type": "int", "default": 5, "minimum": 2, "maximum": 200},
        {"name": "slow_period", "type": "int", "default": 15, "minimum": 3, "maximum": 500},
    ]
    indicators = [
        {
            "id": "fast",
            "type": "sma",
            "feed": signal_feed,
            "line": "close",
            "period": "fast_period",
        },
        {
            "id": "slow",
            "type": "sma",
            "feed": signal_feed,
            "line": "close",
            "period": "slow_period",
        },
    ]
    entry_expression: dict[str, Any] = {
        "kind": "operator",
        "op": "cross_up",
        "args": [
            {"kind": "indicator", "name": "fast"},
            {"kind": "indicator", "name": "slow"},
        ],
    }
    exit_expression: dict[str, Any] = {
        "kind": "operator",
        "op": "cross_down",
        "args": [
            {"kind": "indicator", "name": "fast"},
            {"kind": "indicator", "name": "slow"},
        ],
    }
    if archetype == "pairs_spread":
        entry_expression = {
            "kind": "operator",
            "op": "gt",
            "args": [
                {
                    "kind": "operator",
                    "op": "sub",
                    "args": [
                        {"kind": "data_line", "feed": 0, "line": "close"},
                        {"kind": "data_line", "feed": 1, "line": "close"},
                    ],
                },
                {"kind": "constant", "value": 0.0},
            ],
        }
    if archetype == "precomputed_ml" and "signal" in custom_lines:
        entry_expression = {
            "kind": "operator",
            "op": "gt",
            "args": [
                {"kind": "data_line", "feed": 0, "line": "signal"},
                {"kind": "constant", "value": 0.0},
            ],
        }
        exit_expression = {
            "kind": "operator",
            "op": "lte",
            "args": [
                {"kind": "data_line", "feed": 0, "line": "signal"},
                {"kind": "constant", "value": 0.0},
            ],
        }
    actions = [{"kind": "buy", "feed": 0, "order_type": "market"}]
    if archetype == "order_risk":
        actions.extend(
            [
                {
                    "kind": "set_stop",
                    "feed": 0,
                    "price": {
                        "kind": "operator",
                        "op": "mul",
                        "args": [
                            {"kind": "data_line", "feed": 0, "line": "close"},
                            {"kind": "constant", "value": 0.95},
                        ],
                    },
                },
                {
                    "kind": "set_target",
                    "feed": 0,
                    "price": {
                        "kind": "operator",
                        "op": "mul",
                        "args": [
                            {"kind": "data_line", "feed": 0, "line": "close"},
                            {"kind": "constant", "value": 1.10},
                        ],
                    },
                },
            ]
        )
    raw = {
        "spec_version": "strategy-spec-v1",
        "name": f"{archetype.replace('_', ' ').title()} Scaffold",
        "slug": archetype.replace("_", "-"),
        "category": archetype,
        "archetype": archetype,
        "output_profile": output_profile,
        "dataset_id": dataset_id,
        "feeds": [
            {
                "name": f"data{index}",
                "role": "execution" if index == 0 else "signal",
                "symbol": f"DATA{index}",
                "timeframe": "manifest",
                "lines": [*DATA_LINES, *custom_lines],
            }
            for index in range(effective_feed_count)
        ],
        "custom_lines": custom_lines,
        "parameters": parameters,
        "indicators": indicators,
        "state_variables": [],
        "state_rules": [
            {
                "name": "enter",
                "stage": "next",
                "when": entry_expression,
                "actions": actions,
                "priority": 10,
                "exclusive_group": "position",
            },
            {
                "name": "exit",
                "stage": "next",
                "when": exit_expression,
                "actions": [{"kind": "close", "feed": 0}],
                "priority": 20,
                "exclusive_group": "position",
            },
        ],
        "minperiod": 15,
        "cash": 100000.0,
        "commission": 0.001,
        "sizing": {"type": "fixed", "stake": 1},
        "risk": {
            "live_trading": False,
            "profit_guarantee": False,
            "rule_names": ["enter", "exit"],
        },
        "run_modes": ["runonce", "runnext"],
        "allowed_imports": ["backtrader"],
        "non_goals": ["live trading", "online data download", "profit guarantee"],
        "undecided": [],
    }
    return validate_strategy_spec(raw)
