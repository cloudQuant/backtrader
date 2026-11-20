"""Absolute funding-rate anomaly warnings across push and file replay paths."""

import csv
import json
import logging
import math
from contextlib import contextmanager

import pytest

from backtrader.channel import StreamingEventQueue
from backtrader.channels import funding as funding_module
from backtrader.channels.funding import FundingRateChannel
from backtrader.events import FundingEvent


_PRIVATE_SYMBOL = "private-symbol-sentinel"


class _MemoryHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextmanager
def _capture_funding_warnings():
    logger = funding_module.logger
    handler = _MemoryHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _event(rate, timestamp):
    return FundingEvent(
        timestamp=timestamp,
        symbol=_PRIVATE_SYMBOL,
        rate=rate,
        mark_price=100.0,
    )


def test_first_over_threshold_push_warns_but_remains_accepted():
    channel = FundingRateChannel(symbol=_PRIVATE_SYMBOL, rate_threshold=0.01)

    with _capture_funding_warnings() as records:
        accepted = channel.push(_event(-0.02, 1.0))

    assert accepted is True
    assert channel.event_count == 1
    assert channel.latest.rate == -0.02
    assert channel.get_validation_errors() == []
    assert len(records) == 1
    assert records[0].getMessage() == (
        "Funding rate exceeded configured absolute warning threshold"
    )
    assert _PRIVATE_SYMBOL not in records[0].getMessage()
    assert "0.02" not in records[0].getMessage()


def test_validator_retains_non_blocking_absolute_warning_result():
    channel = FundingRateChannel(symbol="TEST", rate_threshold=0.01)

    with _capture_funding_warnings() as records:
        result = channel._validate_event(_event(0.02, 1.0))

    assert result.valid is True
    assert result.warnings == ["High funding rate: 0.02 (threshold: 0.01)"]
    assert len(records) == 1


def test_push_uses_absolute_threshold_and_strict_boundary():
    channel = FundingRateChannel(symbol="TEST", rate_threshold=0.01)

    with _capture_funding_warnings() as records:
        assert channel.push(_event(0.01, 1.0)) is True
        assert channel.push(_event(-0.009, 2.0)) is True
        # The rate moved by more than 0.01, but neither absolute rate is over it.
        assert channel.push(_event(0.009, 3.0)) is True

    assert records == []
    assert channel.event_count == 3


@pytest.mark.parametrize(
    ("rate", "threshold"),
    [(float("nan"), 0.01), (0.0, float("nan"))],
)
def test_push_preserves_greater_than_nan_behavior_without_warning(rate, threshold):
    channel = FundingRateChannel(symbol="TEST", rate_threshold=threshold)

    with _capture_funding_warnings() as records:
        assert channel.push(_event(rate, 1.0)) is True

    assert channel.event_count == 1
    assert records == []


def test_unformattable_float_subclass_warning_remains_non_blocking():
    class _UnformattableRate(float):
        def __format__(self, format_spec):
            raise ValueError("private rate formatting failure")

    event = _event(_UnformattableRate(0.02), 1.0)
    channel = FundingRateChannel(symbol="TEST", rate_threshold=0.01)

    with _capture_funding_warnings() as records:
        assert channel.push(event) is True

    assert channel.latest is event
    assert channel.event_count == 1
    assert channel.get_validation_errors() == []
    assert len(records) == 1
    assert records[0].getMessage() == (
        "Funding rate exceeded configured absolute warning threshold"
    )
    result = channel._validate_event(_event(_UnformattableRate(0.03), 2.0))
    assert result.valid is True
    assert result.warnings == [
        "High funding rate exceeded the configured absolute threshold"
    ]


@pytest.mark.parametrize("subclass_side", ["rate", "threshold"])
def test_float_subclass_metaclass_comparison_cannot_break_push(subclass_side):
    metaclass_comparisons = []

    class _AdversarialFloatMeta(type):
        def __eq__(cls, other):
            metaclass_comparisons.append(other)
            raise RuntimeError("type comparison failure")

    class _AdversarialFloat(float, metaclass=_AdversarialFloatMeta):
        def __format__(self, format_spec):
            raise ValueError("private rate formatting failure")

    threshold = 0.01
    rate = 0.02
    if subclass_side == "rate":
        rate = _AdversarialFloat(rate)
    else:
        threshold = _AdversarialFloat(threshold)
    event = _event(rate, 1.0)
    channel = FundingRateChannel(symbol="TEST", rate_threshold=threshold)

    with _capture_funding_warnings() as records:
        assert channel.push(event) is True

    assert channel.latest is event
    assert channel.event_count == 1
    assert channel.get_validation_errors() == []
    assert len(records) == 1
    assert records[0].getMessage() == (
        "Funding rate exceeded configured absolute warning threshold"
    )
    assert metaclass_comparisons == []


def test_validate_false_push_accepts_without_anomaly_warning():
    channel = FundingRateChannel(
        symbol=_PRIVATE_SYMBOL, rate_threshold=0.01, validate=False
    )

    with _capture_funding_warnings() as records:
        assert channel.push(_event(0.02, 1.0)) is True

    assert channel.event_count == 1
    assert records == []


@pytest.mark.parametrize("file_format", ["csv", "jsonl"])
@pytest.mark.parametrize("validate", [True, False])
@pytest.mark.parametrize("threshold", [0.01, float("nan")])
def test_streaming_replay_uses_absolute_threshold_without_changing_events(
    tmp_path, file_format, validate, threshold
):
    path = tmp_path / f"funding.{file_format}"
    rows = [
        {"timestamp": 1.0, "rate": 0.02, "mark_price": 100.0, "symbol": _PRIVATE_SYMBOL},
        {"timestamp": 2.0, "rate": 0.001, "mark_price": 101.0, "symbol": _PRIVATE_SYMBOL},
    ]
    if file_format == "csv":
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    else:
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    channel = FundingRateChannel(
        symbol=_PRIVATE_SYMBOL,
        dataname=str(path),
        rate_threshold=threshold,
        validate=validate,
    )
    with _capture_funding_warnings() as records:
        queue = StreamingEventQueue(channels=[channel])
        replayed = []
        while True:
            item = queue.pop()
            if item is None:
                break
            replayed.append(item.data)

    assert [(event.timestamp, event.rate, event.mark_price) for event in replayed] == [
        (1.0, 0.02, 100.0),
        (2.0, 0.001, 101.0),
    ]
    assert channel.event_count == 0
    should_warn = validate and not math.isnan(threshold) and threshold < 0.02
    assert len(records) == (1 if should_warn else 0)
    if records:
        assert records[0].getMessage() == (
            "Funding rate exceeded configured absolute warning threshold"
        )
        assert _PRIVATE_SYMBOL not in records[0].getMessage()
        assert "0.02" not in records[0].getMessage()
