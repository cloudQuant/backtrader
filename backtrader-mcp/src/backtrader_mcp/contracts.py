"""Typed product contracts independent from MCP transport models."""

from __future__ import annotations

import keyword
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .errors import InvalidRequest
from .util import sha256_json

ARCHETYPES = (
    "single_data_indicator",
    "multi_indicator_system",
    "multi_asset_allocation",
    "multi_timeframe",
    "pairs_spread",
    "order_risk",
    "precomputed_ml",
)
SCAFFOLD_PROFILES = ("single_test", "python_bundle")
LEGACY_ARCHETYPES = {
    "multi_indicator": "multi_indicator_system",
    "multi_asset": "multi_asset_allocation",
}
PARAMETER_TYPES = {"int", "float", "bool", "str"}
FEED_ROLES = {"execution", "signal", "benchmark", "hedge", "cash_proxy"}
STANDARD_LINES = ("open", "high", "low", "close", "volume", "openinterest")


@dataclass(frozen=True)
class StrategySpec:
    spec_version: str
    name: str
    slug: str
    category: str
    archetype: str
    output_profile: str
    dataset_id: str
    feeds: list[dict[str, Any]] = field(default_factory=list)
    parameters: list[dict[str, Any]] = field(default_factory=list)
    entry: dict[str, Any] = field(default_factory=dict)
    exit: dict[str, Any] = field(default_factory=dict)
    sizing: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    run_modes: list[str] = field(default_factory=lambda: ["runonce", "runnext"])
    allowed_imports: list[str] = field(default_factory=lambda: ["backtrader"])
    cash_value: float = 100_000.0
    commission_value: float = 0.001
    spec_hash: str = ""
    dataset_feed_names: tuple[str, ...] = field(default_factory=tuple, repr=False)

    @classmethod
    def parse(cls, value: dict[str, Any], output_profile_hint: str | None = None) -> "StrategySpec":
        if not isinstance(value, dict):
            raise InvalidRequest("StrategySpec must be an object")
        canonical_fields = {
            "spec_version",
            "name",
            "slug",
            "category",
            "archetype",
            "output_profile",
            "dataset_id",
            "feeds",
            "parameters",
            "entry",
            "exit",
            "sizing",
            "risk",
            "run_modes",
            "allowed_imports",
            "cash",
            "commission",
            "spec_hash",
            "ir",
            "extensions",
            "non_goals",
            "undecided",
        }
        legacy_fields = {
            "class_name",
            "dataset_ids",
            "starting_cash",
            "commission",
            "description",
        }
        unknown = set(value) - canonical_fields - legacy_fields
        if unknown:
            raise InvalidRequest(f"StrategySpec has unknown fields: {', '.join(sorted(unknown))}")
        if "spec_version" in value and value["spec_version"] != "strategy-spec-v1":
            raise InvalidRequest("StrategySpec spec_version must be strategy-spec-v1")
        archetype = LEGACY_ARCHETYPES.get(value.get("archetype"), value.get("archetype"))
        if archetype not in ARCHETYPES:
            raise InvalidRequest("StrategySpec archetype is invalid")
        legacy_class_name = value.get("class_name", "GeneratedStrategy")
        name = value.get("name", legacy_class_name)
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise InvalidRequest("StrategySpec name must be 1-120 characters")
        slug = value.get("slug")
        if slug is None:
            slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "generated-strategy"
        if (
            not isinstance(slug, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)
            or len(slug) > 120
        ):
            raise InvalidRequest("StrategySpec slug must be lowercase kebab-case")
        category = value.get("category", "strategy")
        if not isinstance(category, str) or not category.strip() or len(category) > 120:
            raise InvalidRequest("StrategySpec category must be 1-120 characters")
        output_profile = value.get("output_profile", output_profile_hint or "single_test")
        if output_profile not in SCAFFOLD_PROFILES:
            raise InvalidRequest("StrategySpec output_profile is invalid")
        if output_profile_hint is not None and output_profile != output_profile_hint:
            raise InvalidRequest("StrategySpec output_profile conflicts with scaffold profile")
        legacy_dataset_ids = value.get("dataset_ids", [])
        dataset_id = value.get("dataset_id", legacy_dataset_ids[0] if legacy_dataset_ids else None)
        if not isinstance(dataset_id, str) or not re.fullmatch(r"ds_[0-9a-f]{64}", dataset_id):
            raise InvalidRequest("StrategySpec dataset_id must be ds_ plus 64 lowercase hex")
        feeds = value.get("feeds")
        if feeds is None:
            count = (
                2
                if archetype
                in {
                    "multi_asset_allocation",
                    "multi_timeframe",
                    "pairs_spread",
                }
                else 1
            )
            feeds = [{"name": "primary" if index == 0 else "secondary"} for index in range(count)]
        if not isinstance(feeds, list) or not 1 <= len(feeds) <= 16:
            raise InvalidRequest("StrategySpec feeds must contain 1-16 feed bindings")
        normalized_feeds: list[dict[str, Any]] = []
        dataset_feed_names: list[str] = []
        for index, feed in enumerate(feeds):
            if not isinstance(feed, dict):
                raise InvalidRequest("StrategySpec feed binding is invalid")
            feed_name = feed.get("name", f"data{index}")
            if not isinstance(feed_name, str) or not feed_name.isidentifier():
                raise InvalidRequest("StrategySpec feed name is invalid")
            role = feed.get("role", "execution" if index == 0 else "signal")
            if role not in FEED_ROLES:
                raise InvalidRequest("StrategySpec feed role is invalid")
            symbol = feed.get("symbol", feed_name)
            timeframe = feed.get("timeframe", "manifest")
            lines = feed.get("lines", list(STANDARD_LINES))
            if (
                not isinstance(symbol, str)
                or not symbol
                or not isinstance(timeframe, str)
                or not timeframe
                or not isinstance(lines, list)
                or not lines
                or any(not isinstance(line, str) or not line.isidentifier() for line in lines)
            ):
                raise InvalidRequest("StrategySpec feed descriptor is invalid")
            normalized_feeds.append(
                {
                    "name": feed_name,
                    "role": role,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "lines": sorted(set(lines)),
                }
            )
            dataset_feed = feed.get("dataset_feed", feed_name if index == 0 else "primary")
            if not isinstance(dataset_feed, str) or not dataset_feed.isidentifier():
                raise InvalidRequest("StrategySpec dataset feed binding is invalid")
            dataset_feed_names.append(dataset_feed)
        parameters = value.get("parameters", {})
        if isinstance(parameters, dict):
            parameters = [
                {
                    "name": parameter_name,
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
                for parameter_name, default in parameters.items()
            ]
        if not isinstance(parameters, list) or len(parameters) > 64:
            raise InvalidRequest("StrategySpec parameters must be a bounded descriptor array")
        normalized_parameters: list[dict[str, Any]] = []
        parameter_names: set[str] = set()
        for parameter in parameters:
            if not isinstance(parameter, dict):
                raise InvalidRequest("StrategySpec parameter descriptor is invalid")
            parameter_name = parameter.get("name")
            parameter_type = parameter.get("type")
            default = parameter.get("default")
            if (
                not isinstance(parameter_name, str)
                or not parameter_name.isidentifier()
                or parameter_name.startswith("_")
                or parameter_name in parameter_names
                or parameter_type not in PARAMETER_TYPES
            ):
                raise InvalidRequest(f"invalid strategy parameter: {parameter_name!r}")
            expected_type = {"int": int, "float": (int, float), "bool": bool, "str": str}[
                parameter_type
            ]
            if not isinstance(default, expected_type) or (
                parameter_type in {"int", "float"} and isinstance(default, bool)
            ):
                raise InvalidRequest(
                    f"strategy parameter {parameter_name!r} has the wrong default type"
                )
            normalized = {"name": parameter_name, "type": parameter_type, "default": default}
            for bound in ("minimum", "maximum"):
                if bound in parameter:
                    if not isinstance(parameter[bound], (int, float)):
                        raise InvalidRequest(
                            f"strategy parameter {parameter_name!r} has an invalid {bound}"
                        )
                    normalized[bound] = parameter[bound]
            normalized_parameters.append(normalized)
            parameter_names.add(parameter_name)

        def rule_references(raw: Any) -> dict[str, list[str]]:
            if isinstance(raw, dict) and isinstance(raw.get("rule_names"), list):
                names = raw["rule_names"]
            elif isinstance(raw, dict) and isinstance(raw.get("rule"), str):
                names = [raw["rule"]]
            elif isinstance(raw, str):
                names = [raw]
            else:
                names = ["archetype_default"]
            if not names or any(not isinstance(item, str) or not item for item in names):
                raise InvalidRequest("StrategySpec rule references are invalid")
            return {"rule_names": sorted(set(names))}

        entry = rule_references(value.get("entry"))
        exit_rules = rule_references(value.get("exit"))
        sizing = value.get(
            "sizing",
            {
                "mode": "fixed_fraction",
                "starting_cash": value.get("starting_cash", 100_000.0),
            },
        )
        risk = value.get(
            "risk",
            {
                "commission": value.get("commission", 0.001),
                "live_trading": False,
            },
        )
        for label, contract in (
            ("entry", entry),
            ("exit", exit_rules),
            ("sizing", sizing),
            ("risk", risk),
        ):
            if not isinstance(contract, dict) or len(contract) > 64:
                raise InvalidRequest(f"StrategySpec {label} must be a bounded object")
        starting_cash = sizing.get("starting_cash", 100_000.0)
        commission = risk.get("commission", 0.001)
        if not isinstance(starting_cash, (int, float)) or starting_cash <= 0:
            raise InvalidRequest("sizing.starting_cash must be positive")
        if not isinstance(commission, (int, float)) or not 0 <= commission < 1:
            raise InvalidRequest("risk.commission must be in [0, 1)")
        run_modes = value.get("run_modes", ["runonce", "runnext"])
        if run_modes != ["runonce", "runnext"]:
            raise InvalidRequest("StrategySpec run_modes must be exactly runonce then runnext")
        allowed_imports = value.get("allowed_imports", ["backtrader"])
        if allowed_imports != ["backtrader"]:
            raise InvalidRequest("StrategySpec allowed_imports must be exactly ['backtrader']")
        cash = value.get("cash", sizing.get("starting_cash", 100_000.0))
        commission = value.get("commission", risk.get("commission", 0.001))
        if not isinstance(cash, (int, float)) or isinstance(cash, bool) or cash <= 0:
            raise InvalidRequest("cash must be positive")
        if (
            not isinstance(commission, (int, float))
            or isinstance(commission, bool)
            or not 0 <= commission < 1
        ):
            raise InvalidRequest("commission must be in [0, 1)")
        parsed = cls(
            spec_version="strategy-spec-v1",
            name=name,
            slug=slug,
            category=category,
            archetype=archetype,
            output_profile=output_profile,
            dataset_id=dataset_id,
            feeds=normalized_feeds,
            parameters=normalized_parameters,
            entry=entry,
            exit=exit_rules,
            sizing=sizing,
            risk=risk,
            run_modes=run_modes,
            allowed_imports=allowed_imports,
            cash_value=float(cash),
            commission_value=float(commission),
            dataset_feed_names=tuple(dataset_feed_names),
        )
        object.__setattr__(parsed, "spec_hash", sha256_json(parsed.as_dict(include_hash=False)))
        return parsed

    @property
    def class_name(self) -> str:
        generated = "".join(part.capitalize() for part in self.slug.split("-")) + "Strategy"
        if not generated.isidentifier() or keyword.iskeyword(generated):
            raise InvalidRequest("StrategySpec slug cannot produce a Python class name")
        return generated

    @property
    def starting_cash(self) -> float:
        return self.cash_value

    @property
    def commission(self) -> float:
        return self.commission_value

    @property
    def parameter_defaults(self) -> dict[str, int | float | str | bool]:
        return {parameter["name"]: parameter["default"] for parameter in self.parameters}

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        result = asdict(self)
        result.pop("dataset_feed_names")
        result["cash"] = result.pop("cash_value")
        result["commission"] = result.pop("commission_value")
        if not include_hash:
            result.pop("spec_hash")
        return result
