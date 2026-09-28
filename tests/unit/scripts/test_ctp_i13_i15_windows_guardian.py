"""Offline tests for the unregistered inert-only Windows guardian candidate."""

import os

import pytest

from scripts import ctp_i13_i15_windows_guardian as guardian


def test_guardian_cli_requires_inert_only_acknowledgement():
    with pytest.raises(SystemExit) as captured:
        guardian._arguments(
            [
                "--child-seconds",
                "3",
                "--stop-deadline-monotonic",
                "99",
                "--deadline-monotonic",
                "100",
                "--receipt-root",
                os.path.abspath("."),
            ]
        )

    assert captured.value.code == 2


def test_guardian_cli_rejects_arbitrary_receipt_filename():
    with pytest.raises(SystemExit) as captured:
        guardian._arguments(
            [
                "--inert-only",
                "--child-seconds",
                "3",
                "--stop-deadline-monotonic",
                "99",
                "--deadline-monotonic",
                "100",
                "--receipt",
                os.path.abspath("arbitrary.json"),
            ]
        )

    assert captured.value.code == 2


@pytest.mark.parametrize("duration", ["0", "301", "nan", "inf"])
def test_guardian_cli_rejects_unbounded_or_nonfinite_inert_sleep(duration: str):
    with pytest.raises(SystemExit) as captured:
        guardian._arguments(
            [
                "--inert-only",
                "--child-seconds",
                duration,
                "--stop-deadline-monotonic",
                "99",
                "--deadline-monotonic",
                "100",
                "--receipt-root",
                os.path.abspath("."),
            ]
        )

    assert captured.value.code == 2

