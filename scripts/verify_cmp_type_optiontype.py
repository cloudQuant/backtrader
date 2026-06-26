#!/usr/bin/env python3
"""Verify bt.Cmp + bt.If Type/OptionType classification behavior.

This script reproduces the option type / moneyness classification pattern:

    _Type[d._name] = bt.If(bt.Cmp(d.type, 1.0) == 0, "CE", ...)
    _OptionType[d._name] = bt.If(bt.And(...), "ATM", ...)

It intentionally runs several variants so the failure mode is explicit:

* cmp: direct numeric bt.Cmp outputs
* private-string: the original private _Type/_OptionType string expression shape
* public-string: the same string expressions stored in public strategy attributes
* numeric-code: a supported numeric-code version with labels mapped in next()

Typical usage:
    python scripts/verify_cmp_type_optiontype.py
    python scripts/verify_cmp_type_optiontype.py --case private-string --runonce false
    python scripts/verify_cmp_type_optiontype.py --use-installed
    python scripts/verify_cmp_type_optiontype.py --json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


def _resolved_path(path_entry: str) -> Path | None:
    """Resolve a sys.path entry, returning None for invalid entries."""

    try:
        return Path(path_entry or ".").resolve()
    except OSError:
        return None


USE_INSTALLED = "--use-installed" in sys.argv
if USE_INSTALLED:
    sys.path[:] = [entry for entry in sys.path if _resolved_path(entry) != REPO]
elif str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

import backtrader as bt  # noqa: E402

TYPE_LABELS = {
    1.0: "CE",
    -1.0: "PE",
    2.0: "F",
    3.0: "Index",
}
MONEYNESS_LABELS = {
    0.0: "ATM",
    1.0: "ITM",
    -1.0: "OTM",
}


class OptionData(bt.feeds.PandasData):
    """Pandas feed exposing the custom option classification lines."""

    lines = ("type", "option_moneyness")
    params = (
        ("type", -1),
        ("option_moneyness", -1),
    )


def build_frame() -> pd.DataFrame:
    """Build deterministic sample option rows covering CE/PE/F/Index and moneyness."""

    idx = pd.date_range("2026-06-10 15:25:39", periods=5, freq="s")
    return pd.DataFrame(
        {
            "open": [1.0] * 5,
            "high": [1.0] * 5,
            "low": [1.0] * 5,
            "close": [1.0] * 5,
            "volume": [1.0] * 5,
            "openinterest": [0.0] * 5,
            "type": [1.0, -1.0, 2.0, 3.0, 9.0],
            "option_moneyness": [0.0, 1.0, -1.0, 9.0, 0.0],
        },
        index=idx,
    )


def read_line_value(line: Any) -> Any:
    """Read current line value and convert NaN/errors into printable values."""

    try:
        value = line[0]
    except Exception as exc:  # noqa: BLE001 - diagnostic script reports exact failure
        return f"ERROR:{type(exc).__name__}:{exc}"

    if isinstance(value, float) and math.isnan(value):
        return "nan"
    return value


def type_string_expr(data: Any) -> Any:
    """Build the original string Type expression."""

    return bt.If(
        bt.Cmp(data.type, 1.0) == 0,
        "CE",
        bt.If(
            bt.Cmp(data.type, -1.0) == 0,
            "PE",
            bt.If(
                bt.Cmp(data.type, 2.0) == 0,
                "F",
                bt.If(bt.Cmp(data.type, 3.0) == 0, "Index", "Unknown"),
            ),
        ),
    )


def option_type_string_expr(data: Any) -> Any:
    """Build the original string OptionType expression."""

    moneyness = data.option_moneyness
    mon_valid = bt.And(moneyness > -2.0, moneyness < 2.0)
    return bt.If(
        bt.And(mon_valid, bt.Cmp(moneyness, 0.0) == 0),
        "ATM",
        bt.If(
            bt.And(mon_valid, bt.Cmp(moneyness, 1.0) == 0),
            "ITM",
            bt.If(
                bt.And(mon_valid, bt.Cmp(moneyness, -1.0) == 0),
                "OTM",
                "Unknown",
            ),
        ),
    )


def type_code_expr(data: Any) -> Any:
    """Build a numeric-code Type expression that can be stored in line buffers."""

    return bt.If(
        bt.Cmp(data.type, 1.0) == 0,
        1.0,
        bt.If(
            bt.Cmp(data.type, -1.0) == 0,
            -1.0,
            bt.If(
                bt.Cmp(data.type, 2.0) == 0,
                2.0,
                bt.If(bt.Cmp(data.type, 3.0) == 0, 3.0, 99.0),
            ),
        ),
    )


def option_type_code_expr(data: Any) -> Any:
    """Build a numeric-code OptionType expression that can be stored in line buffers."""

    moneyness = data.option_moneyness
    mon_valid = bt.And(moneyness > -2.0, moneyness < 2.0)
    return bt.If(
        bt.And(mon_valid, bt.Cmp(moneyness, 0.0) == 0),
        0.0,
        bt.If(
            bt.And(mon_valid, bt.Cmp(moneyness, 1.0) == 0),
            1.0,
            bt.If(
                bt.And(mon_valid, bt.Cmp(moneyness, -1.0) == 0),
                -1.0,
                99.0,
            ),
        ),
    )


class CmpProbe(bt.Strategy):
    """Verify direct bt.Cmp outputs."""

    def __init__(self) -> None:
        data = self.data
        self.cmp_type_ce = bt.Cmp(data.type, 1.0)
        self.cmp_type_pe = bt.Cmp(data.type, -1.0)
        self.cmp_money_atm = bt.Cmp(data.option_moneyness, 0.0)
        self.rows: list[dict[str, Any]] = []

    def next(self) -> None:
        self.rows.append(
            {
                "bar": len(self),
                "raw_type": read_line_value(self.data.type),
                "raw_moneyness": read_line_value(self.data.option_moneyness),
                "cmp_type_ce": read_line_value(self.cmp_type_ce),
                "cmp_type_pe": read_line_value(self.cmp_type_pe),
                "cmp_moneyness_atm": read_line_value(self.cmp_money_atm),
            }
        )


class PrivateStringProbe(bt.Strategy):
    """Verify the original _Type/_OptionType private dictionary string expression."""

    def __init__(self) -> None:
        self._Type: dict[str, Any] = {}
        self._OptionType: dict[str, Any] = {}
        _Type = self._Type
        _OptionType = self._OptionType

        for data in self.datas:
            _Type[data._name] = type_string_expr(data)
            _OptionType[data._name] = option_type_string_expr(data)

        self.rows: list[dict[str, Any]] = []

    def next(self) -> None:
        for data in self.datas:
            self.rows.append(
                {
                    "bar": len(self),
                    "data": data._name,
                    "type_expr": read_line_value(self._Type[data._name]),
                    "option_type_expr": read_line_value(self._OptionType[data._name]),
                }
            )


class PublicStringProbe(bt.Strategy):
    """Verify the same string expressions when strategy scanning advances them."""

    def __init__(self) -> None:
        self.Type: dict[str, Any] = {}
        self.OptionType: dict[str, Any] = {}

        for data in self.datas:
            self.Type[data._name] = type_string_expr(data)
            self.OptionType[data._name] = option_type_string_expr(data)

        self.rows: list[dict[str, Any]] = []

    def next(self) -> None:
        for data in self.datas:
            self.rows.append(
                {
                    "bar": len(self),
                    "data": data._name,
                    "type_expr": read_line_value(self.Type[data._name]),
                    "option_type_expr": read_line_value(self.OptionType[data._name]),
                }
            )


class NumericCodeProbe(bt.Strategy):
    """Verify a numeric-code version and map labels in next()."""

    def __init__(self) -> None:
        self.type_codes: dict[str, Any] = {}
        self.option_type_codes: dict[str, Any] = {}

        for data in self.datas:
            self.type_codes[data._name] = type_code_expr(data)
            self.option_type_codes[data._name] = option_type_code_expr(data)

        self.rows: list[dict[str, Any]] = []

    def next(self) -> None:
        for data in self.datas:
            type_code = read_line_value(self.type_codes[data._name])
            option_type_code = read_line_value(self.option_type_codes[data._name])
            self.rows.append(
                {
                    "bar": len(self),
                    "data": data._name,
                    "type_code": type_code,
                    "type_label": TYPE_LABELS.get(type_code, "Unknown"),
                    "option_type_code": option_type_code,
                    "option_type_label": MONEYNESS_LABELS.get(option_type_code, "Unknown"),
                }
            )


CASES = {
    "cmp": CmpProbe,
    "private-string": PrivateStringProbe,
    "public-string": PublicStringProbe,
    "numeric-code": NumericCodeProbe,
}


def run_case(case: str, runonce: bool) -> dict[str, Any]:
    """Run one strategy case and return a structured diagnostic result."""

    cerebro = bt.Cerebro()
    cerebro.adddata(OptionData(dataname=build_frame(), name="nifty16jun26c23200_1s"))
    cerebro.addstrategy(CASES[case])

    try:
        strategy = cerebro.run(runonce=runonce, stdstats=False)[0]
    except Exception as exc:  # noqa: BLE001 - diagnostic script reports exact failure
        return {
            "case": case,
            "runonce": runonce,
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    return {
        "case": case,
        "runonce": runonce,
        "status": "ok",
        "rows": strategy.rows,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=("all", *CASES.keys()),
        default="all",
        help="Which verification case to run.",
    )
    parser.add_argument(
        "--runonce",
        choices=("both", "true", "false"),
        default="both",
        help="Which Cerebro runonce mode to run.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--use-installed",
        action="store_true",
        help="Import the installed backtrader package instead of this working tree.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any selected case errors or produces a string 'nan' value.",
    )
    return parser.parse_args()


def selected_runonce(value: str) -> list[bool]:
    """Resolve the runonce selector into concrete boolean values."""

    if value == "both":
        return [False, True]
    return [value == "true"]


def contains_nan_string(value: Any) -> bool:
    """Return True if a nested result contains the printable 'nan' marker."""

    if value == "nan":
        return True
    if isinstance(value, dict):
        return any(contains_nan_string(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_nan_string(item) for item in value)
    return False


def print_text(results: list[dict[str, Any]]) -> None:
    """Print human-readable diagnostics."""

    for result in results:
        print(f"\n[{result['case']}] runonce={result['runonce']} status={result['status']}")
        if result["status"] == "error":
            print(f"  {result['error_type']}: {result['error']}")
            continue
        for row in result["rows"]:
            print(f"  {row}")


def main() -> int:
    """Run selected verification cases."""

    args = parse_args()
    case_names = list(CASES) if args.case == "all" else [args.case]

    results = [
        run_case(case_name, runonce)
        for case_name in case_names
        for runonce in selected_runonce(args.runonce)
    ]

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print(f"backtrader: {bt.__file__}")
        print_text(results)

    if args.strict:
        has_error = any(result["status"] == "error" for result in results)
        has_nan = any(contains_nan_string(result) for result in results)
        return 1 if has_error or has_nan else 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
