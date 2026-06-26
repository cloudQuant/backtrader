"""Regression tests for strategy-owned private LineActions."""

import math

import pandas as pd
import pytest

import backtrader as bt


class OptionData(bt.feeds.PandasData):
    lines = ("type", "option_moneyness")
    params = (
        ("type", -1),
        ("option_moneyness", -1),
    )


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


def build_frame(type_code, moneyness_code):
    idx = pd.date_range("2026-06-10 15:25:39", periods=3, freq="s")
    return pd.DataFrame(
        {
            "open": [1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0],
            "close": [1.0, 1.0, 1.0],
            "volume": [1.0, 1.0, 1.0],
            "openinterest": [0.0, 0.0, 0.0],
            "type": [type_code, type_code, type_code],
            "option_moneyness": [moneyness_code, moneyness_code, moneyness_code],
        },
        index=idx,
    )


def add_option_feeds(cerebro):
    samples = (
        ("call", 1.0, 1.0),
        ("put", -1.0, -1.0),
        ("future", 2.0, 99.0),
        ("index", 3.0, 99.0),
    )
    for name, type_code, moneyness_code in samples:
        cerebro.adddata(OptionData(dataname=build_frame(type_code, moneyness_code), name=name))


def read_line_value(line):
    value = line[0]
    if isinstance(value, float) and math.isnan(value):
        return "nan"
    return value


def type_code_expr(data):
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


def option_type_code_expr(data):
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


def type_string_expr(data):
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


class PrivateNumericLineActions(bt.Strategy):
    def __init__(self):
        self._Type = {}
        self._OptionType = {}
        for data in self.datas:
            self._Type[data._name] = type_code_expr(data)
            self._OptionType[data._name] = option_type_code_expr(data)
        self.rows = []

    def next(self):
        for data in self.datas:
            type_code = read_line_value(self._Type[data._name])
            option_type_code = read_line_value(self._OptionType[data._name])
            self.rows.append(
                (
                    data._name,
                    type_code,
                    TYPE_LABELS.get(type_code),
                    option_type_code,
                    MONEYNESS_LABELS.get(option_type_code),
                )
            )


class PrivateStringLineActions(bt.Strategy):
    def __init__(self):
        self._Type = {data._name: type_string_expr(data) for data in self.datas}

    def next(self):
        for data in self.datas:
            self._Type[data._name][0]


class EmptyMultiDataStrategy(bt.Strategy):
    def __init__(self):
        self.rows = []

    def next(self):
        self.rows.append(len(self))


def run_strategy(strategy, runonce):
    cerebro = bt.Cerebro()
    add_option_feeds(cerebro)
    cerebro.addstrategy(strategy)
    return cerebro.run(runonce=runonce, stdstats=False)[0]


@pytest.mark.parametrize("runonce", [False, True])
def test_private_numeric_lineactions_advance_like_original_backtrader(runonce):
    strategy = run_strategy(PrivateNumericLineActions, runonce)

    assert strategy.rows[:4] == [
        ("call", 1.0, "CE", 1.0, "ITM"),
        ("put", -1.0, "PE", -1.0, "OTM"),
        ("future", 2.0, "F", 99.0, "Unknown"),
        ("index", 3.0, "Index", 99.0, "Unknown"),
    ]


@pytest.mark.parametrize("runonce", [False, True])
def test_private_string_lineactions_raise_instead_of_staying_nan(runonce):
    with pytest.raises(TypeError, match="must be real number"):
        run_strategy(PrivateStringLineActions, runonce)


def test_multi_data_without_lineactions_does_not_use_single_data_fast_path():
    strategy = run_strategy(EmptyMultiDataStrategy, runonce=False)

    assert strategy.rows == [1, 2, 3]
