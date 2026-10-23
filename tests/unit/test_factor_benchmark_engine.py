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
