"""Typed core contracts with deterministic hashes."""

import re
from dataclasses import dataclass
from typing import Any, Dict

from .canonical import hash_object
from .errors import AgentError

ARCHETYPES = {
    "single_data_indicator",
    "multi_indicator_system",
    "multi_asset_allocation",
    "multi_timeframe",
    "pairs_spread",
    "order_risk",
    "precomputed_ml",
}
PROFILES = {"single_test", "python_bundle"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATASET_ID_RE = re.compile(r"^ds_[0-9a-f]{64}$")
ARCHETYPE_ALIASES = {
    "single_indicator": "single_data_indicator",
    "multi_indicator": "multi_indicator_system",
    "multi_asset": "multi_asset_allocation",
}


def _require_text(value: Dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise AgentError("BTAG-SPEC-REQUIRED", f"StrategySpec field '{field}' is required")
    return item.strip()


@dataclass(frozen=True)
class StrategySpec:
    value: Dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "StrategySpec":
        version = raw.get("spec_version", raw.get("schema_version"))
        if version != "strategy-spec-v1":
            raise AgentError("BTAG-SPEC-VERSION", "StrategySpec must use strategy-spec-v1")
        source = dict(raw)
        archetype = ARCHETYPE_ALIASES.get(source.get("archetype"), source.get("archetype"))
        output_profile = source.get("output_profile", source.get("profile"))
        name = _require_text(source, "name")
        slug = _require_text(source, "slug").replace("_", "-")
        category = _require_text(source, "category")
        dataset_id = _require_text(source, "dataset_id")
        if not SLUG_RE.fullmatch(slug) or len(slug) > 120:
            raise AgentError("BTAG-SPEC-SLUG", "slug must be lowercase kebab-case")
        if not DATASET_ID_RE.fullmatch(dataset_id):
            raise AgentError(
                "BTAG-SPEC-DATASET",
                "dataset_id must be ds_ followed by the full 64-hex semantic hash",
            )
        if archetype not in ARCHETYPES:
            raise AgentError("BTAG-SPEC-ARCHETYPE", "archetype is not one of the seven P0 values")
        if output_profile not in PROFILES:
            raise AgentError(
                "BTAG-SPEC-PROFILE",
                "output_profile must be single_test or python_bundle",
            )
        raw_feeds = source.get("feeds")
        if not isinstance(raw_feeds, list) or not raw_feeds:
            raise AgentError("BTAG-SPEC-FEEDS", "at least one feed is required")
        feeds = []
        for index, feed in enumerate(raw_feeds):
            if not isinstance(feed, dict):
                raise AgentError("BTAG-SPEC-FEEDS", "feed descriptors must be objects")
            feed_name = feed.get("name", f"data{index}")
            role = feed.get("role", "execution" if index == 0 else "signal")
            lines = feed.get("lines", ["open", "high", "low", "close", "volume", "openinterest"])
            if (
                not isinstance(feed_name, str)
                or not feed_name.isidentifier()
                or role not in {"execution", "signal", "benchmark", "hedge", "cash_proxy"}
                or not isinstance(lines, list)
                or not lines
            ):
                raise AgentError("BTAG-SPEC-FEEDS", "feed descriptor is invalid")
            feeds.append(
                {
                    "name": feed_name,
                    "role": role,
                    "symbol": str(feed.get("symbol", feed_name)),
                    "timeframe": str(feed.get("timeframe", "manifest")),
                    "lines": sorted({str(line) for line in lines}),
                }
            )
        sizing = source.get("sizing")
        risk = source.get("risk")
        if not isinstance(sizing, dict) or not sizing:
            raise AgentError("BTAG-SPEC-SIZING", "sizing rules must be explicit")
        if not isinstance(risk, dict) or not risk:
            raise AgentError("BTAG-SPEC-RISK", "risk rules must be explicit")
        questions = source.get("open_questions", [])
        if questions:
            raise AgentError("BTAG-SPEC-OPEN", "open questions must be resolved before rendering")
        raw_parameters = source.get("parameters", [])
        if isinstance(raw_parameters, dict):
            raw_parameters = [
                (
                    {
                        "name": parameter_name,
                        "type": descriptor.get("type", "str"),
                        "default": descriptor.get("default"),
                        **({"minimum": descriptor["minimum"]} if "minimum" in descriptor else {}),
                        **({"maximum": descriptor["maximum"]} if "maximum" in descriptor else {}),
                    }
                    if isinstance(descriptor, dict)
                    else {
                        "name": parameter_name,
                        "type": (
                            "bool"
                            if isinstance(descriptor, bool)
                            else (
                                "int"
                                if isinstance(descriptor, int)
                                else "float" if isinstance(descriptor, float) else "str"
                            )
                        ),
                        "default": descriptor,
                    }
                )
                for parameter_name, descriptor in raw_parameters.items()
            ]
        if not isinstance(raw_parameters, list) or len(raw_parameters) > 64:
            raise AgentError("BTAG-SPEC-PARAMETERS", "parameters must be a bounded array")
        parameters = []
        parameter_names = set()
        for parameter in raw_parameters:
            if not isinstance(parameter, dict):
                raise AgentError("BTAG-SPEC-PARAMETERS", "parameter descriptor is invalid")
            descriptor = dict(parameter)
            descriptor["type"] = {"integer": "int", "number": "float", "boolean": "bool"}.get(
                descriptor.get("type"), descriptor.get("type")
            )
            parameter_name = descriptor.get("name")
            if (
                not isinstance(parameter_name, str)
                or not parameter_name.isidentifier()
                or parameter_name in parameter_names
                or descriptor.get("type") not in {"int", "float", "bool", "str"}
                or "default" not in descriptor
            ):
                raise AgentError("BTAG-SPEC-PARAMETERS", "parameter descriptor is invalid")
            parameters.append(
                {
                    key: descriptor[key]
                    for key in ("name", "type", "default", "minimum", "maximum")
                    if key in descriptor
                }
            )
            parameter_names.add(parameter_name)

        def rules(value: Any, default: str) -> Dict[str, Any]:
            if isinstance(value, dict) and isinstance(value.get("rule_names"), list):
                names = value["rule_names"]
            elif isinstance(value, str):
                names = [default]
            else:
                names = [default]
            if not names or any(not isinstance(item, str) or not item for item in names):
                raise AgentError("BTAG-SPEC-RULES", "rule references are invalid")
            return {"rule_names": sorted(set(names))}

        run_modes = source.get("run_modes", source.get("execution_modes", ["runonce", "runnext"]))
        if run_modes != ["runonce", "runnext"]:
            raise AgentError("BTAG-SPEC-MODES", "run_modes must be exactly runonce then runnext")
        if source.get("allowed_imports", ["backtrader"]) not in (
            ["backtrader"],
            ["backtrader", "json", "os", "math"],
        ):
            raise AgentError("BTAG-SPEC-IMPORTS", "allowed_imports exceeds the P0 allowlist")
        extensions = source.get("extensions", {})
        extension_config = (
            extensions.get("backtrader_agent", {}) if isinstance(extensions, dict) else {}
        )
        analyzers = source.get(
            "analyzers",
            extension_config.get("analyzers", ["TradeAnalyzer", "DrawDown"]),
        )
        if not isinstance(analyzers, list) or any(
            not isinstance(analyzer, str) or not analyzer for analyzer in analyzers
        ):
            raise AgentError("BTAG-SPEC-ANALYZERS", "analyzers must be a list of names")
        normalized = {
            "spec_version": "strategy-spec-v1",
            "name": name,
            "slug": slug,
            "category": category,
            "archetype": archetype,
            "output_profile": output_profile,
            "dataset_id": dataset_id,
            "feeds": feeds,
            "parameters": parameters,
            "entry": rules(source.get("entry"), "enter"),
            "exit": rules(source.get("exit"), "exit"),
            "sizing": sizing,
            "risk": risk,
            "cash": float(source.get("cash", 100000.0)),
            "commission": float(source.get("commission", 0.0)),
            "run_modes": run_modes,
            "allowed_imports": ["backtrader"],
            "non_goals": [str(item) for item in source.get("non_goals", [])],
            "extensions": {"backtrader_agent": {"analyzers": analyzers}},
        }
        normalized["spec_hash"] = hash_object(
            {key: item for key, item in normalized.items() if key != "spec_hash"}
        )
        return cls(normalized)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.value)

    @property
    def slug(self) -> str:
        return self.value["slug"]

    @property
    def archetype(self) -> str:
        return self.value["archetype"]

    @property
    def profile(self) -> str:
        return self.value["output_profile"]

    @property
    def spec_hash(self) -> str:
        return self.value["spec_hash"]

    @property
    def module_slug(self) -> str:
        return self.slug.replace("-", "_")

    @property
    def parameter_defaults(self) -> Dict[str, Any]:
        return {item["name"]: item["default"] for item in self.value["parameters"]}


@dataclass(frozen=True)
class DatasetManifest:
    value: Dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "DatasetManifest":
        if raw.get("schema_version") != "dataset-manifest-v1":
            raise AgentError("BTAG-DATASET-VERSION", "DatasetManifest version is unsupported")
        if not isinstance(raw.get("feeds"), list) or not raw["feeds"]:
            raise AgentError("BTAG-DATASET-FEEDS", "DatasetManifest requires feeds")
        for feed in raw["feeds"]:
            if feed.get("format") not in {
                "generic_csv",
                "backtrader_csv",
                "yahoo_csv",
                "mt5_csv",
                "pandas",
                "pandas_custom_lines",
                "canonical_csv_v1",
            }:
                raise AgentError("BTAG-DATASET-FORMAT", "dataset adapter is not allowlisted")
        return cls(dict(raw))

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.value)
