from __future__ import annotations

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.errors import ConfigError
from backtrader.research.factor_indicator import FactorIndicator


class _EqualitySensitivePandasData(bt.feeds.PandasData):
    __hash__ = object.__hash__

    def __eq__(self, other: object) -> bool:
        self.equality_calls += 1
        if self.equality_raises:
            raise AssertionError("feed equality must not be used for binding")
        return self.equality_result


class _IdentityBoundFactor(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)

    def next(self) -> None:
        pass


def _feed(name: str, *, equality_result: bool = False, equality_raises: bool = False):
    index = pd.date_range("2026-01-01", periods=1, freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [10.0],
            "openinterest": [0.0],
        },
        index=index,
    )
    feed = _EqualitySensitivePandasData(dataname=frame)
    feed._name = name
    feed.equality_calls = 0
    feed.equality_result = equality_result
    feed.equality_raises = equality_raises
    return feed


def _bind(*datas, output_datas):
    return _IdentityBoundFactor._bind_for_research(
        *datas,
        output_datas=output_datas,
        asset_names=tuple("asset_%d" % index for index in range(len(output_datas))),
        factor_name=None,
        field_bindings={"close": "feed:target:close"},
        classification_bindings={},
        research=None,
        strict=False,
    )


def test_factor_binding_and_field_lookup_use_feed_identity() -> None:
    first = _feed("AAA", equality_raises=True)
    target = _feed("BBB", equality_raises=True)

    factor = _bind(first, target, output_datas=(target,))

    assert factor.target_datas[0] is target
    assert factor.field("close", target) is factor.field_lines("close")[0]
    assert first.equality_calls == 0
    assert target.equality_calls == 0

    foreign = _feed("BBB", equality_result=True)
    with pytest.raises(ConfigError, match="factor target feed"):
        factor.field("close", foreign)
    assert foreign.equality_calls == 0


def test_factor_binding_rejects_foreign_target_that_compares_equal() -> None:
    native = _feed("AAA", equality_result=True)
    foreign = _feed("AAA", equality_result=True)

    with pytest.raises(ConfigError, match="native indicator inputs"):
        _bind(native, output_datas=(foreign,))

    assert native.equality_calls == 0
    assert foreign.equality_calls == 0
