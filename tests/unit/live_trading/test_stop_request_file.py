"""Opt-in stop-request file source (iteration 66, §5.2 B1 remainder).

The runtime publishes ``bt_api_stop_request/v1`` into its own control
directory; the strategy process consumes it read-only and turns a provable
request into the same graceful stop as a signal.  These tests cover the
fail-closed cases (malformed, unknown schema, forged/cross-unit, old, expired,
duplicate) and prove the source writes nothing.

Evidence: UNIT/FAKE.  No provider, account or network is touched.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

from backtrader.live_trading import (
    STOP_REQUEST_FILE_SCHEMA,
    STOP_REQUEST_SOURCE,
    StopRequestFileSource,
    stop_on_terminate,
)

RUN_ID = str(uuid.uuid4())
STRATEGY_UUID = str(uuid.uuid4())
COMMAND_ID = str(uuid.uuid4())
NONCE = str(uuid.uuid4())
_UTC = datetime.timezone.utc

_AUDIT_EVENTS = []
_AUDIT_ROOT = [None]


def _audit_hook(event, args):
    if event != "open" or _AUDIT_ROOT[0] is None:
        return
    path = args[0]
    try:
        text = os.fspath(path)
    except TypeError:
        return
    if isinstance(text, str) and text.startswith(_AUDIT_ROOT[0]):
        _AUDIT_EVENTS.append((text, args[1], args[2]))


sys.addaudithook(_audit_hook)


def _moment(offset_s=0.0):
    return (datetime.datetime.now(_UTC) + datetime.timedelta(seconds=offset_s)).isoformat()


def _document(**overrides):
    document = {
        "schema": STOP_REQUEST_FILE_SCHEMA,
        "strategy_uuid": STRATEGY_UUID,
        "run_id": RUN_ID,
        "command_id": COMMAND_ID,
        "nonce": NONCE,
        "requested_at_utc": _moment(-1.0),
        "expires_at_utc": _moment(300.0),
    }
    document.update(overrides)
    return document


def _write(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _source(path, **overrides):
    values = {"strategy_uuid": STRATEGY_UUID, "run_id": RUN_ID}
    values.update(overrides)
    return StopRequestFileSource(path, **values)


def test_a_valid_request_names_its_source_and_time(tmp_path):
    document = _document()
    path = _write(tmp_path / "stop_request.json", document)

    assert _source(path).poll() == (STOP_REQUEST_SOURCE, document["requested_at_utc"])


def test_the_same_nonce_is_idempotent_and_a_second_nonce_is_refused(tmp_path):
    document = _document()
    path = _write(tmp_path / "stop_request.json", document)
    source = _source(path)
    first = _source(path).poll()
    assert first == (STOP_REQUEST_SOURCE, document["requested_at_utc"])

    # A duplicate read of the same one-time request returns the same result.
    assert source.poll() == first
    assert source.poll() == first

    # A different request for the same run cannot reset the accepted one.
    _write(path, _document(nonce=str(uuid.uuid4()), requested_at_utc=_moment()))
    assert source.poll() is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"strategy_uuid": str(uuid.uuid4())},  # cross-unit / forged
        {"run_id": str(uuid.uuid4())},  # old or another run
        {"schema": "bt_api_stop_request/v2"},
        {"nonce": "not-a-uuid"},
        {"command_id": ""},
        {"requested_at_utc": "not-a-time"},
        {"expires_at_utc": "2026-11-15T12:00:00"},  # naive, not UTC
        {"extra": "value"},
    ],
)
def test_a_foreign_or_invalid_document_is_not_a_request(tmp_path, overrides):
    path = _write(tmp_path / "stop_request.json", _document(**overrides))
    assert _source(path).poll() is None


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        json.dumps({}),
        json.dumps(_document()).replace('"schema"', '"unknown"'),
    ],
)
def test_malformed_documents_are_ignored(tmp_path, payload):
    path = tmp_path / "stop_request.json"
    path.write_text(payload, encoding="utf-8")
    assert _source(path).poll() is None


def test_a_missing_file_is_not_a_request(tmp_path):
    assert _source(tmp_path / "absent.json").poll() is None


def test_an_expired_request_is_refused(tmp_path):
    path = _write(
        tmp_path / "stop_request.json",
        _document(requested_at_utc=_moment(-600.0), expires_at_utc=_moment(-300.0)),
    )
    assert _source(path).poll() is None


def test_a_future_or_overlong_request_is_refused(tmp_path):
    future = _write(
        tmp_path / "future.json",
        _document(requested_at_utc=_moment(600.0), expires_at_utc=_moment(900.0)),
    )
    assert _source(future).poll() is None

    overlong = _write(
        tmp_path / "overlong.json",
        _document(requested_at_utc=_moment(-1.0), expires_at_utc=_moment(200000.0)),
    )
    assert _source(overlong).poll() is None


def test_an_oversized_document_is_refused(tmp_path):
    path = tmp_path / "stop_request.json"
    path.write_text("{" + " " * 8000 + "}", encoding="utf-8")
    assert _source(path).poll() is None


def test_a_symlink_is_not_followed(tmp_path):
    target = _write(tmp_path / "target.json", _document())
    link = tmp_path / "stop_request.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # pragma: no cover - platform
        pytest.skip("symlinks are unavailable")
    assert _source(link).poll() is None


def test_the_source_only_reads_and_leaves_the_document_untouched(tmp_path):
    document = _document()
    path = _write(tmp_path / "stop_request.json", document)
    before = path.read_bytes()
    _AUDIT_EVENTS.clear()
    _AUDIT_ROOT[0] = str(tmp_path)
    try:
        assert _source(path).poll() == (
            STOP_REQUEST_SOURCE,
            document["requested_at_utc"],
        )
    finally:
        _AUDIT_ROOT[0] = None

    assert _AUDIT_EVENTS, "the source must have read the request"
    for opened, mode, flags in _AUDIT_EVENTS:
        assert isinstance(opened, str)
        if isinstance(mode, str):
            assert not any(flag in mode for flag in "wax+"), (opened, mode)
        if isinstance(flags, int):
            assert flags & (os.O_WRONLY | os.O_RDWR) == 0, (opened, flags)
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# TerminateStop integration
# ---------------------------------------------------------------------------
class _FakeCerebro:
    def __init__(self, active=True):
        self._run_active = active
        self.stops = 0

    def runstop(self):
        self.stops += 1


def _wait_stops(cerebro, timeout=3.0):
    deadline = time.monotonic() + timeout
    while cerebro.stops == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    return cerebro.stops


def test_the_stop_file_requests_the_same_graceful_stop_as_a_signal(tmp_path):
    requested_at = _moment(-1.0)
    path = _write(
        tmp_path / "stop_request.json",
        _document(requested_at_utc=requested_at),
    )
    cerebro = _FakeCerebro()
    with stop_on_terminate(
        cerebro,
        stop_request_file=str(path),
        stop_request_strategy_uuid=STRATEGY_UUID,
        stop_request_run_id=RUN_ID,
    ) as termination:
        assert _wait_stops(cerebro) == 1
        assert termination.request_state() == (STOP_REQUEST_SOURCE, requested_at)


def test_a_forged_or_malformed_stop_file_never_stops_the_run(tmp_path):
    for name, document in (
        ("other-unit.json", _document(strategy_uuid=str(uuid.uuid4()))),
        ("other-run.json", _document(run_id=str(uuid.uuid4()))),
        (
            "expired.json",
            _document(requested_at_utc=_moment(-600.0), expires_at_utc=_moment(-300.0)),
        ),
        ("unknown-schema.json", _document(schema="bt_api_stop_request/v2")),
    ):
        path = _write(tmp_path / name, document)
        cerebro = _FakeCerebro()
        with stop_on_terminate(
            cerebro,
            stop_request_file=str(path),
            stop_request_strategy_uuid=STRATEGY_UUID,
            stop_request_run_id=RUN_ID,
        ):
            time.sleep(0.5)
            assert cerebro.stops == 0, name


def test_the_file_channel_requires_an_explicit_identity(tmp_path):
    path = _write(tmp_path / "stop_request.json", _document())
    with pytest.raises(ValueError):
        stop_on_terminate(_FakeCerebro(), stop_request_file=str(path))
    with pytest.raises(ValueError):
        stop_on_terminate(
            _FakeCerebro(),
            stop_request_file=str(path),
            stop_request_strategy_uuid=STRATEGY_UUID,
        )


def test_a_request_before_the_run_opens_is_latched_like_a_signal(tmp_path):
    path = _write(tmp_path / "stop_request.json", _document())
    cerebro = _FakeCerebro(active=False)
    with stop_on_terminate(
        cerebro,
        stop_request_file=str(path),
        stop_request_strategy_uuid=STRATEGY_UUID,
        stop_request_run_id=RUN_ID,
    ):
        time.sleep(0.5)
        assert cerebro.stops == 0  # runstop() before the scope would be lost
        cerebro._run_active = True
        assert _wait_stops(cerebro) == 1
