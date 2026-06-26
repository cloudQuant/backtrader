#!/usr/bin/env python3
"""Reproduce issue #17 with the reporter CSV attachment.

The attached HTRFI strategy is not self-contained: it imports TPCR, Redis-backed
symbol selection, data_config, and live feed construction. This script extracts
only the reported Type / OptionType classification logic and feeds it with rows
from the attached CSV.

Cases:
* cmp: direct numeric bt.Cmp checks on data.type / data.option_moneyness.
* private-string: the original private _Type/_OptionType string-return bt.If.
* private-numeric: the same private dictionaries, but strings converted to
  numeric codes.
* public-numeric: numeric codes stored on public attributes so the current fork
  advances the expressions.

Use PYTHONPATH plus --use-installed to compare against an isolated original
backtrader install, for example:

    PYTHONPATH=/tmp/backtrader_orig_1_9_78_123 \
      python scripts/reproduce_issue17_from_csv.py --use-installed
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CSV = Path("/tmp/backtrader_issue17/standard.Original.BT.csv")
DEFAULT_SYMBOLS = (
    "nifty30jun26c24050_1s",
    "nifty30jun26p24050_1s",
    "nifty30jun26f_1s",
    "nifty50_1s",
)


def _resolved_path(path_entry: str) -> Path | None:
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
    99.0: "Unknown",
}
MONEYNESS_LABELS = {
    0.0: "ATM",
    1.0: "ITM",
    -1.0: "OTM",
    99.0: "Unknown",
}


class Issue17Data(bt.feeds.PandasData):
    """Pandas feed exposing the custom option classification lines."""

    lines = ("type", "option_moneyness")
    params = (
        ("type", -1),
        ("option_moneyness", -1),
    )


def infer_type_code(symbol: str) -> float:
    """Infer the option/future/index type code from a reporter CSV symbol."""

    name = symbol.lower()
    if re.search(r"c\d+_", name):
        return 1.0
    if re.search(r"p\d+_", name):
        return -1.0
    if re.search(r"\d+[a-z]{3}\d+f_", name):
        return 2.0
    return 3.0


def build_symbol_frame(raw: pd.DataFrame, symbol: str, max_rows: int) -> pd.DataFrame:
    """Build a Backtrader-ready OHLCV frame for one CSV symbol."""

    rows = raw.loc[raw["symbol"] == symbol].copy()
    if rows.empty:
        raise ValueError(f"symbol not found in CSV: {symbol}")

    rows["datetime"] = pd.to_datetime(rows["datetime"], format="%d-%m-%Y %H:%M")
    rows = rows.sort_values("datetime").head(max_rows)

    type_code = infer_type_code(symbol)
    if type_code == 1.0:
        moneyness = rows["ce_option_moneyness"]
    elif type_code == -1.0:
        moneyness = rows["pe_option_moneyness"]
    else:
        moneyness = pd.Series(99.0, index=rows.index)

    close = pd.to_numeric(rows["close"], errors="coerce").ffill().bfill().fillna(1.0)
    money_values = pd.to_numeric(moneyness, errors="coerce").fillna(99.0).to_numpy()
    close_values = close.to_numpy()
    frame = pd.DataFrame(
        {
            "open": close_values,
            "high": close_values,
            "low": close_values,
            "close": close_values,
            "volume": 1.0,
            "openinterest": 0.0,
            "type": type_code,
            "option_moneyness": money_values,
        },
        index=rows["datetime"].to_numpy(),
    )
    return frame


def read_line_value(line: Any) -> Any:
    """Read current line value and convert NaN/errors into printable values."""

    try:
        value = line[0]
    except Exception as exc:  # noqa: BLE001 - diagnostic script reports failures
        return f"ERROR:{type(exc).__name__}:{exc}"

    if isinstance(value, float) and math.isnan(value):
        return "nan"
    return value


def type_string_expr(data: Any) -> Any:
    """Build the original string Type expression from the issue."""

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
    """Build the original string OptionType expression from the issue."""

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
    """Build a numeric-code Type expression."""

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
    """Build a numeric-code OptionType expression."""

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


def summarize_data(data: Any) -> dict[str, Any]:
    """Return raw classification inputs for the current bar."""

    raw_type = read_line_value(data.type)
    raw_money = read_line_value(data.option_moneyness)
    return {
        "data": data._name,
        "raw_type": raw_type,
        "raw_type_label": TYPE_LABELS.get(raw_type, "Unknown"),
        "raw_moneyness": raw_money,
        "raw_moneyness_label": MONEYNESS_LABELS.get(raw_money, "Unknown"),
    }


class CmpProbe(bt.Strategy):
    """Verify direct bt.Cmp outputs from the reporter CSV data."""

    def __init__(self) -> None:
        self.cmp_type_ce = {data._name: bt.Cmp(data.type, 1.0) for data in self.datas}
        self.cmp_type_pe = {data._name: bt.Cmp(data.type, -1.0) for data in self.datas}
        self.cmp_money_atm = {data._name: bt.Cmp(data.option_moneyness, 0.0) for data in self.datas}
        self.rows: list[dict[str, Any]] = []

    def next(self) -> None:
        for data in self.datas:
            row = {"bar": len(self), **summarize_data(data)}
            row.update(
                {
                    "cmp_type_ce": read_line_value(self.cmp_type_ce[data._name]),
                    "cmp_type_pe": read_line_value(self.cmp_type_pe[data._name]),
                    "cmp_moneyness_atm": read_line_value(self.cmp_money_atm[data._name]),
                }
            )
            self.rows.append(row)


class PrivateStringProbe(bt.Strategy):
    """Original private _Type/_OptionType string expression shape."""

    def __init__(self) -> None:
        self._Type: dict[str, Any] = {}
        self._OptionType: dict[str, Any] = {}
        for data in self.datas:
            self._Type[data._name] = type_string_expr(data)
            self._OptionType[data._name] = option_type_string_expr(data)
        self.rows: list[dict[str, Any]] = []

    def next(self) -> None:
        for data in self.datas:
            row = {"bar": len(self), **summarize_data(data)}
            row.update(
                {
                    "type_expr": read_line_value(self._Type[data._name]),
                    "option_type_expr": read_line_value(self._OptionType[data._name]),
                }
            )
            self.rows.append(row)


class PrivateNumericProbe(bt.Strategy):
    """String labels converted to numeric codes, but still in private attrs."""

    def __init__(self) -> None:
        self._Type: dict[str, Any] = {}
        self._OptionType: dict[str, Any] = {}
        for data in self.datas:
            self._Type[data._name] = type_code_expr(data)
            self._OptionType[data._name] = option_type_code_expr(data)
        self.rows: list[dict[str, Any]] = []

    def next(self) -> None:
        for data in self.datas:
            type_code = read_line_value(self._Type[data._name])
            option_type_code = read_line_value(self._OptionType[data._name])
            row = {"bar": len(self), **summarize_data(data)}
            row.update(
                {
                    "type_code": type_code,
                    "type_label": TYPE_LABELS.get(type_code, "Unknown"),
                    "option_type_code": option_type_code,
                    "option_type_label": MONEYNESS_LABELS.get(option_type_code, "Unknown"),
                }
            )
            self.rows.append(row)


class PublicNumericProbe(bt.Strategy):
    """Numeric code expressions stored on public attrs so current fork advances them."""

    def __init__(self) -> None:
        self.Type: dict[str, Any] = {}
        self.OptionType: dict[str, Any] = {}
        for data in self.datas:
            self.Type[data._name] = type_code_expr(data)
            self.OptionType[data._name] = option_type_code_expr(data)
        self.rows: list[dict[str, Any]] = []

    def next(self) -> None:
        for data in self.datas:
            type_code = read_line_value(self.Type[data._name])
            option_type_code = read_line_value(self.OptionType[data._name])
            row = {"bar": len(self), **summarize_data(data)}
            row.update(
                {
                    "type_code": type_code,
                    "type_label": TYPE_LABELS.get(type_code, "Unknown"),
                    "option_type_code": option_type_code,
                    "option_type_label": MONEYNESS_LABELS.get(option_type_code, "Unknown"),
                }
            )
            self.rows.append(row)


CASES = {
    "cmp": CmpProbe,
    "private-string": PrivateStringProbe,
    "private-numeric": PrivateNumericProbe,
    "public-numeric": PublicNumericProbe,
}


def add_csv_feeds(cerebro: Any, csv_path: Path, symbols: list[str], max_rows: int) -> None:
    """Add one Backtrader feed per selected symbol."""

    raw = pd.read_csv(csv_path)
    required = {"symbol", "datetime", "close", "ce_option_moneyness", "pe_option_moneyness"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    for symbol in symbols:
        frame = build_symbol_frame(raw, symbol, max_rows)
        cerebro.adddata(Issue17Data(dataname=frame, name=symbol))


def run_case(case: str, runonce: bool, csv_path: Path, symbols: list[str], max_rows: int) -> dict:
    """Run one reproduction case and return structured output."""

    cerebro = bt.Cerebro()
    add_csv_feeds(cerebro, csv_path, symbols, max_rows)
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


def selected_runonce(value: str) -> list[bool]:
    if value == "both":
        return [False, True]
    return [value == "true"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Reporter CSV path.")
    parser.add_argument(
        "--case",
        choices=("all", *CASES.keys()),
        default="all",
        help="Which reproduction case to run.",
    )
    parser.add_argument(
        "--runonce",
        choices=("both", "true", "false"),
        default="both",
        help="Which Cerebro runonce mode to run.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=list(DEFAULT_SYMBOLS),
        help="CSV symbols to include as feeds.",
    )
    parser.add_argument("--max-rows", type=int, default=3, help="Rows per symbol to load.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--use-installed",
        action="store_true",
        help="Import installed/PYTHONPATH backtrader instead of this working tree.",
    )
    return parser.parse_args()


def print_text(results: list[dict[str, Any]], max_print_rows: int) -> None:
    for result in results:
        print(f"\n[{result['case']}] runonce={result['runonce']} status={result['status']}")
        if result["status"] == "error":
            print(f"  {result['error_type']}: {result['error']}")
            continue
        for row in result["rows"][:max_print_rows]:
            print(f"  {row}")
        remaining = len(result["rows"]) - max_print_rows
        if remaining > 0:
            print(f"  ... {remaining} more rows")


def main() -> int:
    args = parse_args()
    if not args.csv.exists():
        raise SystemExit(f"CSV not found: {args.csv}")

    case_names = list(CASES) if args.case == "all" else [args.case]
    results = [
        run_case(case_name, runonce, args.csv, args.symbols, args.max_rows)
        for case_name in case_names
        for runonce in selected_runonce(args.runonce)
    ]

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print(f"backtrader: {bt.__file__}")
        print(f"csv: {args.csv}")
        print(f"symbols: {', '.join(args.symbols)}")
        print_text(results, max_print_rows=max(4, len(args.symbols)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
