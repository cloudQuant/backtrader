"""Benchmark engine assertions must use actual instrumented loop calls."""

import pytest

from tests.unit.test_factor_examples_benchmark_universe import _load_script


@pytest.mark.parametrize(
    ("phases", "expected"),
    (
        ({"engine_runonce": {"calls": 2}}, "runonce"),
        ({"engine_runnext": {"calls": 1}}, "runnext"),
        ({"engine_runonce": {"calls": 0}, "engine_runnext": {"calls": 1}}, "runnext"),
        ({"engine_runonce": {"calls": 1}, "engine_runnext": {"calls": 1}}, "mixed"),
        ({}, None),
    ),
)
def test_observed_engine_uses_actual_calls(phases, expected):
    runner = _load_script("factor_benchmark_engine", "scripts/benchmark_factor_examples.py")
    assert runner._observed_engine(phases) == expected


def test_timers_wrap_inherited_and_override_once_and_skip_missing_optional():
    runner = _load_script("factor_benchmark_timers", "scripts/benchmark_factor_examples.py")
    calls = []

    class BaseFeed:
        def preload(self):
            calls.append("base")

    class InheritedFeed(BaseFeed):
        pass

    class OverrideFeed(BaseFeed):
        def preload(self):
            calls.append("override")
            return super().preload()

    timers = runner.Timers()
    assert timers.wrap(InheritedFeed, "preload", "inherited_preload")
    InheritedFeed().preload()
    assert calls == ["base"]
    assert timers.rows["inherited_preload"]["calls"] == 1

    assert timers.wrap(OverrideFeed, "preload", "override_preload")
    OverrideFeed().preload()
    assert calls == ["base", "override", "base"]
    assert timers.rows["override_preload"]["calls"] == 1

    portfolio = type("PortfolioModule", (), {"positions": lambda self: "positions"})()
    assert timers.wrap(portfolio, "positions", "fincore_positions")
    assert portfolio.positions() == "positions"
    assert timers.rows["fincore_positions"]["calls"] == 1
    assert not timers.wrap(portfolio, "_positions_float64_fastpath", "positions_fastpath")
