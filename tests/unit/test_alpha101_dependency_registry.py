"""Independent static audit of the Appendix A Alpha101 dependency register.

This test parses the preserved source-expression strings itself. It never imports
or executes a candidate Alpha101 implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "research"
    / "alpha101_dependencies.json"
)
COVERAGE_DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "_internal"
    / "opts"
    / "requirements"
    / "迭代45-Indicator因子研究与多因子合成"
    / "Alpha101覆盖清单.md"
)

CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
INPUT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:open|high|low|close|volume|vwap|returns|cap|adv\d+)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
INDCLASS_RE = re.compile(r"\bIndClass\.(sector|industry|subindustry)\b", re.IGNORECASE)
TOKEN_RE = re.compile(
    r"\s*(?:(?P<number>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)|"
    r"(?P<identifier>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)|"
    r"(?P<operator>\|\||==|!=|<=|>=|[()+\-*/^<>?,:]))"
)

PHYSICAL_FIELDS = {"open", "high", "low", "close", "volume", "vwap"}
CS_FUNCTIONS = {"rank", "scale", "indneutralize"}
WINDOW_FUNCTIONS = {
    "delay", "delta", "correlation", "covariance", "decay_linear", "ts_min", "ts_max",
    "ts_argmax", "ts_argmin", "ts_rank", "sum", "product", "stddev",
}
TS_OPERATOR_CLASSES = {
    "Delay", "Delta", "RollingCorrelation", "RollingCovariance", "DecayLinear", "TsMin",
    "TsMax", "TsArgMin", "TsArgMax", "TsRank", "RollingSum", "RollingProduct", "RollingStd",
}

SOURCE_FUNCTION_CLASS = {
    "abs": "Abs",
    "log": "Log",
    "sign": "Sign",
    "signedpower": "SignedPower",
    "rank": "CrossSectionalRank",
    "scale": "CrossSectionalScale",
    "indneutralize": "IndNeutralize",
    "delay": "Delay",
    "delta": "Delta",
    "correlation": "RollingCorrelation",
    "covariance": "RollingCovariance",
    "decay_linear": "DecayLinear",
    "ts_min": "TsMin",
    "ts_max": "TsMax",
    "ts_argmax": "TsArgMax",
    "ts_argmin": "TsArgMin",
    "ts_rank": "TsRank",
    "sum": "RollingSum",
    "product": "RollingProduct",
    "stddev": "RollingStd",
}

EXPECTED_SOURCE_FUNCTIONS = {
    "abs", "correlation", "covariance", "decay_linear", "delay", "delta", "indneutralize",
    "log", "max", "min", "product", "rank", "scale", "sign", "signedpower", "stddev",
    "sum", "ts_argmax", "ts_argmin", "ts_max", "ts_min", "ts_rank",
}
EXPECTED_SOURCE_SYMBOLS = {"+", "-", "*", "/", "^", "<", "==", "||", "?"}
EXPECTED_RUNTIME_OPERATOR_CLASSES = {
    "Abs", "Add", "CrossSectionalRank", "CrossSectionalScale", "DecayLinear", "Delay", "Delta",
    "Divide", "EqualTo", "IndNeutralize", "LessThan", "Log", "LogicalOr", "Maximum", "Minimum",
    "Multiply", "Negate", "Power", "RollingCorrelation", "RollingCovariance", "RollingProduct",
    "RollingStd", "RollingSum", "Sign", "SignedPower", "Subtract", "TsArgMax", "TsArgMin",
    "TsMax", "TsMin", "TsRank", "Where",
}


def _close_paren(text: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError(f"unclosed call in source formula near {text[opening - 20:opening + 20]!r}")


def _arguments(text: str) -> list[str]:
    if not text.strip():
        return []
    arguments: list[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(text):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            arguments.append(text[start:index].strip())
            start = index + 1
    arguments.append(text[start:].strip())
    return arguments


def _literal(text: str) -> str | None:
    match = re.fullmatch(r"\s*([+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)\s*", text)
    return match.group(1) if match else None


def _lex(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    offset = 0
    while offset < len(text):
        match = TOKEN_RE.match(text, offset)
        assert match, f"unrecognized Appendix A token at {text[offset:offset + 24]!r}"
        offset = match.end()
        if match.group("number") is not None:
            tokens.append(("number", match.group("number")))
        elif match.group("identifier") is not None:
            tokens.append(("identifier", match.group("identifier")))
        else:
            tokens.append(("operator", match.group("operator")))
    return tokens


def _numeric_literals(tokens: list[tuple[str, str]]) -> list[str]:
    unary_predecessors = {
        "(", ",", "?", ":", "+", "-", "*", "/", "^", "<", ">", "<=", ">=", "==", "!=", "||"
    }
    literals: list[str] = []
    for index, (kind, value) in enumerate(tokens):
        if kind != "number":
            continue
        if index >= 1:
            sign_kind, sign = tokens[index - 1]
            before_sign = tokens[index - 2] if index >= 2 else None
            before_sign_operator = (
                before_sign[1] if before_sign is not None and before_sign[0] == "operator" else None
            )
            if sign_kind == "operator" and sign in {"+", "-"} and (
                index == 1 or before_sign_operator in unary_predecessors
            ):
                value = sign + value
        literals.append(value)
    return literals


def _calls(formula: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for match in CALL_RE.finditer(formula):
        opening = formula.find("(", match.start())
        closing = _close_paren(formula, opening)
        arguments = _arguments(formula[opening + 1 : closing])
        spelling = match.group(1)
        name = spelling.casefold()
        raw_window = None
        argument_index = None
        if name in {"correlation", "covariance"} and len(arguments) >= 3:
            raw_window = _literal(arguments[2])
            argument_index = 3
        elif (name in WINDOW_FUNCTIONS and len(arguments) >= 2) or (
            name in {"min", "max"} and len(arguments) == 2
        ):
            raw_window = _literal(arguments[1])
            argument_index = 2

        if name == "min":
            canonical = "TsMin" if raw_window is not None else "Minimum"
        elif name == "max":
            canonical = "TsMax" if raw_window is not None else "Maximum"
        else:
            canonical = SOURCE_FUNCTION_CLASS.get(name)
            assert canonical is not None, f"source function {spelling!r} missing from static audit"
        result.append(
            {
                "source_name": spelling,
                "canonical_operator": canonical,
                "arity": len(arguments),
                "window_raw": raw_window,
                "window_floor": math.floor(float(raw_window)) if raw_window is not None else None,
                "window_argument_index": argument_index if raw_window is not None else None,
            }
        )
    return result


def _symbol_classes(tokens: list[tuple[str, str]]) -> tuple[set[str], Counter[str]]:
    classes: set[str] = set()
    structural_tokens = {"(", ")", ",", ":"}
    counts: Counter[str] = Counter(
        value
        for kind, value in tokens
        if kind == "operator" and value not in structural_tokens
    )
    previous: tuple[str, str] | None = None
    unary_predecessors = {"(", ",", "?", ":", "+", "-", "*", "/", "^", "<", ">", "<=", ">=", "==", "!=", "||"}
    for kind, value in tokens:
        if kind != "operator":
            previous = (kind, value)
            continue
        previous_operator = previous[1] if previous and previous[0] == "operator" else None
        if value == "+":
            if previous is not None and previous_operator not in unary_predecessors:
                classes.add("Add")
        elif value == "-":
            if previous is None or previous_operator in unary_predecessors:
                classes.add("Negate")
            else:
                classes.add("Subtract")
        else:
            symbol_class = {
                "*": "Multiply",
                "/": "Divide",
                "^": "Power",
                "<": "LessThan",
                ">": "GreaterThan",
                "==": "EqualTo",
                "!=": "NotEqualTo",
                "<=": "LessEqual",
                ">=": "GreaterEqual",
                "||": "LogicalOr",
                "?": "Where",
            }.get(value)
            if symbol_class:
                classes.add(symbol_class)
        previous = ("operator", value)
    return classes, counts


def _expected_field_requirement(name: str) -> dict[str, object]:
    if name in PHYSICAL_FIELDS:
        return {
            "name": name,
            "kind": "market_field",
            "pit_rule": "bind the explicit feed line or full-index external table; value must be available by the closed-bar grid; no fill across missing bars",
        }
    if name == "returns":
        return {
            "name": name,
            "kind": "derived_formula_field",
            "derivation": "close[t] / close[t-1] - 1 on the same adjusted-price convention",
            "source_lookback_grid_bars": 1,
            "pit_rule": "both current and preceding close values must be available by the current grid; do not bind a future label",
        }
    if name == "cap":
        return {
            "name": name,
            "kind": "point_in_time_external_field",
            "definition": "market capitalization",
            "pit_rule": "as-of value available at the current grid; do not recompute historical cap from later-published shares; no constant placeholder",
        }
    match = re.fullmatch(r"adv(\d+)", name)
    assert match, f"unclassified formula field: {name}"
    window = int(match.group(1))
    return {
        "name": name,
        "kind": "average_daily_dollar_volume",
        "window": window,
        "source_contract": "exactly one: direct precomputed ADV field OR explicit dollar_volume source with a complete-window mean; no silent close*volume or share-volume substitute",
        "direct_source": {
            "engine_lookback_grid_bars": 0,
            "provenance_source_lookback_grid_bars": window - 1,
            "pit_rule": "available_at <= current grid; metadata declares dollar unit/currency, window, complete-window convention, source version and availability",
        },
        "derived_source": {
            "source_field": "dollar_volume",
            "operator": "RollingMean",
            "window": window,
            "engine_lookback_grid_bars": window - 1,
            "pit_rule": "all dollar_volume values in the complete N-grid window must be available by their respective grid points; no gap compression or forward fill",
        },
    }


def _source_projection(formula: str) -> dict[str, object]:
    calls = _calls(formula)
    names = [str(call["source_name"]).casefold() for call in calls]
    ordered_fields = list(dict.fromkeys(match.group(0).casefold() for match in INPUT_RE.finditer(formula)))
    windows = [
        {
            "source_operator": call["source_name"],
            "canonical_operator": call["canonical_operator"],
            "raw_parameter": call["window_raw"],
            "floor_parameter": call["window_floor"],
            "argument_index": call["window_argument_index"],
        }
        for call in calls
        if call["window_raw"] is not None
    ]
    delays = [
        window
        for window, call in zip(windows, [call for call in calls if call["window_raw"] is not None])
        if str(call["source_name"]).casefold() in {"delay", "delta"}
    ]
    class_calls = [
        {"level": match.group(1).casefold(), "ordinal": ordinal}
        for ordinal, match in enumerate(INDCLASS_RE.finditer(formula), start=1)
    ]
    class_levels = list(dict.fromkeys(call["level"] for call in class_calls))
    call_classes = {str(call["canonical_operator"]) for call in calls}
    tokens = _lex(formula)
    symbol_classes, symbol_counts = _symbol_classes(tokens)
    operator_classes = sorted(call_classes | symbol_classes)
    has_cs = any(name in CS_FUNCTIONS for name in names)
    has_industry = "indneutralize" in names
    has_ts = any(name in WINDOW_FUNCTIONS for name in names) or any(
        call["canonical_operator"] in {"TsMin", "TsMax"} for call in calls
    )
    group = "industry" if has_industry else "CS" if has_cs else "TS"
    has_derived_history = "returns" in ordered_fields or any(field.startswith("adv") for field in ordered_fields)
    if windows and has_derived_history:
        warmup = "formula_windows_plus_derived_input_history"
    elif windows:
        warmup = "formula_window_or_delay_history"
    elif has_derived_history:
        warmup = "derived_input_history_only"
    else:
        warmup = "current_grid_only"

    spans = []
    for call, match in zip(calls, CALL_RE.finditer(formula)):
        opening = formula.find("(", match.start())
        spans.append((str(call["source_name"]).casefold(), str(call["canonical_operator"]), opening + 1, _close_paren(formula, opening)))
    cs_to_ts = any(
        operator_class in TS_OPERATOR_CLASSES
        and any(inner_name in CS_FUNCTIONS for inner_name, _, inner_start, inner_end in spans if start <= inner_start and inner_end <= end)
        for _, operator_class, start, end in spans
    )
    ts_to_cs = any(
        name in CS_FUNCTIONS
        and any(inner_class in TS_OPERATOR_CLASSES for _, inner_class, inner_start, inner_end in spans if start <= inner_start and inner_end <= end)
        for name, _, start, end in spans
    )
    if cs_to_ts and ts_to_cs:
        composition = "both_cross_sectional_to_temporal_and_temporal_to_cross_sectional"
    elif cs_to_ts:
        composition = "cross_sectional_nested_in_temporal"
    elif ts_to_cs:
        composition = "temporal_nested_in_cross_sectional"
    elif has_cs and has_ts:
        composition = "mixed_without_direct_operator_nesting"
    elif has_cs:
        composition = "cross_sectional_only"
    elif has_ts:
        composition = "temporal_only"
    else:
        composition = "pointwise_only"

    return {
        "calls": calls,
        "call_counts": dict(sorted(Counter(names).items())),
        "fields": ordered_fields,
        "physical_fields": [field for field in ordered_fields if field in PHYSICAL_FIELDS],
        "formula_fields": [field for field in ordered_fields if field == "returns" or field == "cap" or field.startswith("adv")],
        "windows": windows,
        "delays": delays,
        "class_calls": class_calls,
        "class_levels": class_levels,
        "class_level_counts": dict(Counter(call["level"] for call in class_calls)),
        "numeric_literals": _numeric_literals(tokens),
        "symbol_counts": dict(sorted(symbol_counts.items())),
        "function_names": set(names),
        "operator_classes": operator_classes,
        "group": group,
        "has_cs": has_cs,
        "warmup": warmup,
        "composition": composition,
    }


def test_registry_contains_every_original_formula_and_static_dependency():
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert registry["registry_kind"] == "static_dependency_catalog_only"
    assert registry["profile_id"] == "alpha101-v1"
    assert registry["source"]["url"] == "https://arxiv.org/pdf/1601.00991"
    assert registry["source"]["formula_source_locator"] == "Appendix A.1, Alpha#1 through Alpha#101"
    assert registry["source"]["source_pdf_sha256"] == "1f9c21afe32dcb3ee77b31548acdaea00451fbfa1c0ee10c907867bcc736fce9"
    assert registry["source"]["formula_text_normalization"] == (
        "Original formula tokens and punctuation preserved; whitespace collapsed to one ASCII space after PDF text extraction."
    )
    assert registry["scope"]["does_not_compile_or_execute_formulas"] is True
    assert registry["scope"]["does_not_calculate_exact_lookback_h"] is True
    assert registry["scope"]["does_not_claim_any_formula_implemented"] is True
    assert registry["scope"]["does_not_claim_any_acceptance_pass"] is True

    entries = registry["formulas"]
    assert len(entries) == 101
    assert [entry["id"] for entry in entries] == list(range(1, 102))

    group_counts: Counter[str] = Counter()
    all_functions: set[str] = set()
    all_operator_classes: set[str] = set()
    all_symbols: set[str] = set()
    for entry in entries:
        source_formula = entry["source_formula"]
        assert source_formula and "\n" not in source_formula
        assert entry["source_formula_sha256"] == hashlib.sha256(source_formula.encode("utf-8")).hexdigest()
        parsed = _source_projection(source_formula)
        group_counts[parsed["group"]] += 1
        all_functions.update(parsed["function_names"])
        all_operator_classes.update(parsed["operator_classes"])
        all_symbols.update(parsed["symbol_counts"])

        assert entry["required_input_fields"] == parsed["fields"]
        assert entry["direct_market_fields"] == parsed["physical_fields"]
        assert entry["formula_fields"] == parsed["formula_fields"]
        assert entry["field_requirements"] == [
            _expected_field_requirement(field) for field in parsed["fields"]
        ]
        assert entry["operator_calls"] == parsed["calls"]
        assert entry["operator_call_counts"] == parsed["call_counts"]
        assert entry["formula_operator_classes"] == parsed["operator_classes"]
        assert entry["symbol_operator_counts"] == parsed["symbol_counts"]
        assert entry["numeric_literals"] == parsed["numeric_literals"]
        assert entry["window_parameters"] == parsed["windows"]
        assert entry["delay_and_delta_parameters"] == parsed["delays"]
        assert entry["classification_requirements"]["calls"] == parsed["class_calls"]
        assert entry["classification_requirements"]["required_levels"] == parsed["class_levels"]
        assert entry["classification_requirements"]["level_counts"] == parsed["class_level_counts"]
        assert entry["warmup_category"] == parsed["warmup"]
        assert entry["cross_sectional_temporal_composition"] == parsed["composition"]
        assert entry["paper_signal_timing"] == (
            "delay_0" if entry["id"] in {42, 48, 53, 54} else "not_identified_as_delay_0_in_paper"
        )
        universe = entry["formula_universe_requirement"]
        assert universe["required_for_output_eligibility"] is True
        assert universe["required_for_cross_sectional_nodes"] is parsed["has_cs"]
        assert universe["research_group_required_for_cross_sectional_nodes"] is parsed["has_cs"]
        assert "complete (time, asset) boolean matrix" in universe["coverage"]
        assert universe["unknown_member_state"].startswith("reject dataset completion")
        pit = entry["point_in_time_requirements"]
        assert pit["classifications"] == parsed["class_levels"]
        assert pit["all_bound_inputs"] == (
            "source availability must be known and <= the grid at which the value is used; "
            "absent timing metadata is rejected rather than guessed"
        )
        assert "label evaluability" in pit["formula_universe"]

    assert dict(group_counts) == {"TS": 18, "CS": 65, "industry": 18}
    assert registry["scope"]["group_counts"] == dict(group_counts)
    assert all_functions == EXPECTED_SOURCE_FUNCTIONS
    assert all_symbols == EXPECTED_SOURCE_SYMBOLS
    assert all_operator_classes == EXPECTED_RUNTIME_OPERATOR_CLASSES
    assert registry["scope"]["formula_operator_classes_union"] == sorted(all_operator_classes)
    assert registry["scope"]["conditionally_required_input_provisioning_operator_classes_union"] == sorted(
        all_operator_classes | {"RollingMean"}
    )
    assert registry["scope"]["source_signal_delay_zero_ids"] == [42, 48, 53, 54]


def test_registry_preserves_source_formula_101_and_known_complex_dependencies():
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    entries = {entry["id"]: entry for entry in registry["formulas"]}

    # Alpha#101 is kept byte-for-byte at the token level from Appendix A; in particular `.001` is not rewritten.
    alpha101 = entries[101]
    assert alpha101["source_formula"] == "((close - open) / ((high - low) + .001))"
    assert alpha101["required_input_fields"] == ["close", "open", "high", "low"]
    assert alpha101["formula_operator_classes"] == ["Add", "Divide", "Subtract"]
    assert alpha101["numeric_literals"] == [".001"]
    assert alpha101["window_parameters"] == []
    assert alpha101["warmup_category"] == "current_grid_only"
    assert alpha101["formula_universe_requirement"]["required_for_output_eligibility"] is True
    assert alpha101["formula_universe_requirement"]["required_for_cross_sectional_nodes"] is False
    coverage_doc = COVERAGE_DOC_PATH.read_text(encoding="utf-8")
    assert "| #101 | D:O,H,L,C | — | — | `(C−O)/(H−L+0.001)`" in coverage_doc

    # These rows exercise overloaded operators, embedded comparisons, fractional windows,
    # per-call PIT classification bindings, and a time-varying SignedPower exponent.
    alpha29 = entries[29]
    assert alpha29["required_input_fields"] == ["close", "returns"]
    assert alpha29["operator_call_counts"] == {
        "delay": 1, "delta": 1, "log": 1, "min": 1, "product": 1, "rank": 5,
        "scale": 1, "sum": 1, "ts_min": 1, "ts_rank": 1,
    }
    assert [(item["canonical_operator"], item["raw_parameter"], item["floor_parameter"]) for item in alpha29["window_parameters"]] == [
        ("TsMin", "5", 5), ("RollingProduct", "1", 1), ("RollingSum", "1", 1),
        ("TsMin", "2", 2), ("Delta", "5", 5), ("TsRank", "5", 5), ("Delay", "6", 6),
    ]
    assert "RollingMean" not in alpha29["formula_operator_classes"]
    assert alpha29["field_requirements"][1]["derivation"].startswith("close[t] / close[t-1]")

    alpha58 = entries[58]
    assert alpha58["classification_requirements"]["calls"] == [{"level": "sector", "ordinal": 1}]
    assert [(item["raw_parameter"], item["floor_parameter"]) for item in alpha58["window_parameters"]] == [
        ("5.50322", 5), ("7.89291", 7), ("3.92795", 3)
    ]

    alpha62 = entries[62]
    assert alpha62["group"] == "CS"
    assert alpha62["operator_call_counts"]["rank"] == 6
    assert alpha62["symbol_operator_counts"]["<"] == 2
    assert alpha62["numeric_literals"] == ["22.4101", "9.91009", "2", "-1"]
    assert alpha62["formula_universe_requirement"]["required_for_cross_sectional_nodes"] is True

    alpha67 = entries[67]
    assert alpha67["classification_requirements"]["calls"] == [
        {"level": "sector", "ordinal": 1},
        {"level": "subindustry", "ordinal": 2},
    ]
    assert alpha67["formula_operator_classes"].count("IndNeutralize") == 1
    assert alpha67["operator_call_counts"]["indneutralize"] == 2

    alpha81 = entries[81]
    assert alpha81["operator_call_counts"]["product"] == 1
    assert alpha81["formula_operator_classes"].count("Power") == 1
    assert "Log" in alpha81["formula_operator_classes"]
    assert "adv10" in alpha81["required_input_fields"]

    alpha84 = entries[84]
    assert alpha84["required_input_fields"] == ["vwap", "close"]
    assert alpha84["operator_call_counts"]["signedpower"] == 1
    assert alpha84["operator_call_counts"]["delta"] == 1
    assert alpha84["cross_sectional_temporal_composition"] == "temporal_only"

    alpha92 = entries[92]
    assert alpha92["operator_call_counts"]["min"] == 1
    assert alpha92["operator_calls"][0]["canonical_operator"] == "Minimum"
    assert alpha92["operator_calls"][0]["window_raw"] is None
    assert alpha92["operator_call_counts"]["rank"] == 2

    alpha100 = entries[100]
    assert alpha100["classification_requirements"]["calls"] == [
        {"level": "subindustry", "ordinal": 1},
        {"level": "subindustry", "ordinal": 2},
        {"level": "subindustry", "ordinal": 3},
    ]
    assert alpha100["operator_call_counts"]["scale"] == 2
    assert alpha100["operator_call_counts"]["indneutralize"] == 3
    assert alpha100["formula_operator_classes"].count("IndNeutralize") == 1


def test_adv_and_classification_pit_contracts_are_explicit_per_formula():
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    entries = {entry["id"]: entry for entry in registry["formulas"]}

    for entry in entries.values():
        for requirement in entry["field_requirements"]:
            if requirement["name"].startswith("adv"):
                window = int(requirement["name"][3:])
                assert requirement["kind"] == "average_daily_dollar_volume"
                assert requirement["window"] == window
                assert requirement["direct_source"]["engine_lookback_grid_bars"] == 0
                assert requirement["direct_source"]["provenance_source_lookback_grid_bars"] == window - 1
                assert requirement["derived_source"]["operator"] == "RollingMean"
                assert requirement["derived_source"]["window"] == window
                assert requirement["derived_source"]["engine_lookback_grid_bars"] == window - 1
                assert "exactly one" in requirement["source_contract"]
        levels = entry["classification_requirements"]["required_levels"]
        assert entry["point_in_time_requirements"]["classifications"] == levels
        if levels:
            assert "effective_at" in entry["classification_requirements"]["pit_rule"]
            assert "available_at" in entry["classification_requirements"]["pit_rule"]
            assert "taxonomy_version" in entry["classification_requirements"]["pit_rule"]
        else:
            assert entry["classification_requirements"]["calls"] == []
    assert entries[56]["required_input_fields"] == ["returns", "cap"]
    assert entries[56]["field_requirements"][1]["kind"] == "point_in_time_external_field"
