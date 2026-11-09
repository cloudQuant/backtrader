"""Offline contract tests for explicit execution time interpretation."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from bt_api_py.gateway_execution_time import GatewayExecutionTimeError, GatewayExecutionTimePolicy


def policy(zone="UTC"):
    return GatewayExecutionTimePolicy(route="route", timezone=zone)


def test_utc_and_natural_date_crossing_utc_day():
    assert policy().project("20241103", "12:34:56") == datetime(
        2024, 11, 3, 12, 34, 56, tzinfo=timezone.utc
    )
    # The supplied natural date is interpreted directly: no trading-day input exists.
    assert policy("Asia/Shanghai").project("20241103", "01:02:03") == datetime(
        2024, 11, 2, 17, 2, 3, tzinfo=timezone.utc
    )


@pytest.mark.parametrize("date,time", [(None, None), (None, "12:00:00"), ("20240101", None)])
def test_missing_is_unknown(date, time):
    assert policy().project(date, time) is None


@pytest.mark.parametrize(
    "date,time",
    [
        (None, "99:99:99"),
        (None, "12:00:00 "),
        (None, True),
        ("20230229", None),
        ("2024011", None),
        (False, None),
    ],
)
def test_missing_does_not_hide_invalid_known_field(date, time):
    with pytest.raises(GatewayExecutionTimeError) as error:
        policy().project(date, time)
    assert error.value.code in {"INVALID_DATE", "INVALID_TIME", "INVALID_DATE_TIME"}
    assert str(error.value) == error.value.code


@pytest.mark.parametrize(
    "date,time",
    [
        ("20240230", "12:00:00"),
        ("00000101", "12:00:00"),
        ("2024011", "12:00:00"),
        (" 20240101", "12:00:00"),
        ("20240101", "24:00:00"),
        ("20240101", "12:60:00"),
        ("20240101", "12:00:60"),
        ("20240101", "12:00:00 "),
        (True, "12:00:00"),
        (20240101, "12:00:00"),
        ("20240101", False),
        ("20240101", 120000),
        ("２０２４０１０１", "12:00:00"),
    ],
)
def test_invalid_date_time_values_are_not_echoed(date, time):
    with pytest.raises(GatewayExecutionTimeError) as error:
        policy().project(date, time)
    assert error.value.code in {"INVALID_DATE", "INVALID_TIME", "INVALID_DATE_TIME"}
    assert str(error.value) == error.value.code


@pytest.mark.parametrize("date,time", [("20240310", "02:30:00"), ("20241103", "01:30:00")])
def test_dst_gap_and_fold_rejected(date, time):
    with pytest.raises(GatewayExecutionTimeError, match="^AMBIGUOUS_OR_NONEXISTENT_TIME$"):
        policy("America/New_York").project(date, time)


def test_dst_unambiguous_time_works():
    assert policy("America/New_York").project("20241103", "03:30:00") == datetime(
        2024, 11, 3, 8, 30, tzinfo=timezone.utc
    )


def test_mapping_digest_and_immutable_policy():
    value = policy("Asia/Shanghai")
    mapping = {
        "route": "route",
        "timezone": "Asia/Shanghai",
        "format": "date_hms_seconds_v1",
        "schema_version": 1,
    }
    assert value.to_mapping() == mapping
    assert GatewayExecutionTimePolicy.from_mapping(dict(reversed(list(mapping.items())))) == value
    assert value.digest == "eb7165b5a6e564ff9a3e87eb8ad6d9d7a198289d084fc8d2fa89417e74ceac9a"
    assert value.digest != policy().digest
    with pytest.raises(FrozenInstanceError):
        value.timezone = "UTC"
    mapping["timezone"] = "UTC"
    assert value.timezone == "Asia/Shanghai"


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"route": "route", "timezone": "UTC"},
        {
            "route": "route",
            "timezone": "UTC",
            "format": "date_hms_seconds_v1",
            "schema_version": 1,
            "extra": 1,
        },
    ],
)
def test_mapping_requires_exact_keys(value):
    with pytest.raises(GatewayExecutionTimeError, match="^INVALID_MAPPING$"):
        GatewayExecutionTimePolicy.from_mapping(value)


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"route": "secret-route ", "timezone": "UTC"}, "INVALID_ROUTE"),
        ({"route": "route\x7fvalue", "timezone": "UTC"}, "INVALID_ROUTE"),
        ({"route": "route\x80value", "timezone": "UTC"}, "INVALID_ROUTE"),
        ({"route": "route\x9fvalue", "timezone": "UTC"}, "INVALID_ROUTE"),
        ({"route": "x" * 257, "timezone": "UTC"}, "INVALID_ROUTE"),
        ({"route": True, "timezone": "UTC"}, "INVALID_ROUTE"),
        ({"route": "route", "timezone": "secret-invalid-zone"}, "INVALID_TIMEZONE"),
        ({"route": "route", "timezone": " UTC"}, "INVALID_TIMEZONE"),
        ({"route": "route", "timezone": True}, "INVALID_TIMEZONE"),
        (
            {"route": "route", "timezone": "UTC", "format": "secret-invalid-format"},
            "INVALID_FORMAT",
        ),
        ({"route": "route", "timezone": "UTC", "schema_version": True}, "INVALID_SCHEMA_VERSION"),
    ],
)
def test_invalid_policy_errors_do_not_echo_values(kwargs, code):
    with pytest.raises(GatewayExecutionTimeError) as error:
        GatewayExecutionTimePolicy(**kwargs)
    assert error.value.code == code
    assert str(error.value) == code
