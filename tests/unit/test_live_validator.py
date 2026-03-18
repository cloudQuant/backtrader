from types import SimpleNamespace

import pytest

from backtrader.channels.live_validator import LiveDataValidator


def test_live_validator_rejects_invalid_timestamp():
    validator = LiveDataValidator()
    event = SimpleNamespace(
        channel_type="tick",
        channel_name="rb2610",
        timestamp="bad-timestamp",
        data=SimpleNamespace(price=3500.0, volume=1),
    )

    assert validator.validate(event) is False
    assert validator.get_anomaly_report()[("tick", "rb2610")]["invalid_timestamp"] == 1
    assert validator.stats["total_rejected"] == 1


def test_live_validator_rejects_invalid_tick_price_payload():
    validator = LiveDataValidator()
    event = SimpleNamespace(
        channel_type="tick",
        channel_name="rb2610",
        timestamp=1,
        data=SimpleNamespace(price="not-a-number", volume=1),
    )

    assert validator.validate(event) is False
    assert validator.get_anomaly_report()[("tick", "rb2610")]["invalid_price"] == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_time_jump": -1}, "max_time_jump must be a non-negative number"),
        ({"max_clock_drift": -1}, "max_clock_drift must be a non-negative number"),
        ({"max_time_jump": "oops"}, "max_time_jump must be a non-negative number"),
    ],
)
def test_live_validator_validates_constructor_arguments(kwargs, message):
    with pytest.raises(ValueError, match=message):
        LiveDataValidator(**kwargs)
