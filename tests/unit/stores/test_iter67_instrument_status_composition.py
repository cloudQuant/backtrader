"""Read-only Store accessor over the committed SDK 67.06 status composition.

Evidence level: UNIT/FAKE.  The calendar is a real temporary SDK version store
published by the committed SDK tooling; observations are real CTP projections
and ledger views built from synthetic callback fields.  No account, provider,
network or order path is used, and no result authorizes trading.
"""

import socket
from datetime import date, datetime, timezone

import pytest

pytest.importorskip("bt_api_py", reason="the composition needs the bt_api_py SDK")
pytest.importorskip("bt_api_ctp", reason="observations need the bt_api_ctp projection")

from bt_api_ctp.instrument_status_observation import (
    RECEIVE_CLOCK_MONOTONIC_NS,
    InstrumentStatusLedger,
    InstrumentStatusSessionFacts,
    project_native_instrument_status,
)
from bt_api_py.instrument_status_composition import (
    REASON_CALENDAR_CONTINUOUS_NO_OBSERVATION,
    REASON_OBSERVATION_CLOSED,
    REASON_OBSERVATION_CONTINUOUS,
    REASON_OBSERVATION_PAUSED,
    STATE_CLOSED,
    STATE_PAUSED,
    STATE_TRADABLE,
    STATE_UNKNOWN,
)

from backtrader.stores.btapistore import BtApiStoreError, _InstrumentStatusUnavailable
from tests.unit.stores.test_iter67_calendar_config_wiring import local_store
from tests.unit.stores.test_iter67_trading_calendar_query import publish
from tests.unit.stores.test_iter67_trading_calendar_status import make_store

ROUTE = "CTP___FUTURE"
VENUE = "XSH"
PRODUCT = "cu"
CONTRACT = "cu2601"
KIND = "future"
MONDAY = date(2026, 10, 12)
GENERATION = "1"
# The published day window is 09:00-11:00 Asia/Shanghai = 01:00-03:00 UTC.
IN_WINDOW = datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)
OUT_OF_WINDOW = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)


class Port:
    """Explicit observation port: records scopes, returns one fixed view."""

    def __init__(self, view=None, *, error=None):
        self.view = view
        self.error = error
        self.scopes = []

    def observation(self, scope):
        self.scopes.append(scope)
        if self.error is not None:
            raise self.error
        return self.view


def native_fields(status, *, venue=VENUE, symbol=CONTRACT):
    return {
        "ExchangeID": venue,
        "ExchangeInstID": symbol,
        "InstrumentID": symbol,
        "InstrumentStatus": status,
        "TradingSegmentSN": 1,
        "EnterTime": "09:00:00",
        "EnterReason": "1",
    }


def view(status, *, generation=GENERATION, day=MONDAY, symbol=CONTRACT, ledger=None):
    """A current ledger view for one synthetic callback, or a stale one."""
    projection = project_native_instrument_status(
        native_fields(status, symbol=symbol),
        session=InstrumentStatusSessionFacts(
            session_generation=generation,
            trading_day=day.strftime("%Y%m%d"),
            source_sequence=1,
            receive_clock_domain=RECEIVE_CLOCK_MONOTONIC_NS,
            receive_time=1001,
            source_available=True,
        ),
    )
    assert projection.accepted is True
    store = ledger or InstrumentStatusLedger(
        session_generation=generation, trading_day=day.strftime("%Y%m%d")
    )
    applied = store.observe(projection)
    assert applied.applied is True
    return store.view(VENUE, symbol)


def status(store, port, **overrides):
    fields = {
        "route": ROUTE,
        "venue": VENUE,
        "kind": KIND,
        "product": PRODUCT,
        "instrument": CONTRACT,
        "trading_day": MONDAY,
        "session_generation": GENERATION,
        "at": IN_WINDOW,
    }
    fields.update(overrides)
    store.configure_instrument_status_port(port)
    return store.instrument_status(**fields)


@pytest.fixture
def published(monkeypatch, tmp_path):
    publish(tmp_path / "calendars/ctp")
    store, _api = local_store(monkeypatch, tmp_path)
    return store


def test_tradable_paused_and_closed_delegate_to_the_sdk(published):
    port = Port(view("2"))  # continuous
    result = status(published, port)
    assert (result.state, result.reason_code, result.session_phase) == (
        STATE_TRADABLE,
        REASON_OBSERVATION_CONTINUOUS,
        "CONTINUOUS",
    )
    assert (result.source, result.observation_state, result.calendar_state) == (
        "OBSERVATION",
        "CURRENT",
        "COMPLETE",
    )
    assert result.calendar_ref is not None and result.conflict is None
    assert result.authorizes_trading is False
    assert [
        (scope.venue, scope.instrument, scope.trading_day, scope.session_generation)
        for scope in port.scopes
    ] == [(VENUE, CONTRACT, MONDAY, GENERATION)]

    paused = status(published, Port(view("1")))  # no_trading
    assert (paused.state, paused.reason_code, paused.session_phase) == (
        STATE_PAUSED,
        REASON_OBSERVATION_PAUSED,
        "PAUSED",
    )
    closed = status(published, Port(view("6")))  # closed
    assert (closed.state, closed.reason_code) == (STATE_CLOSED, REASON_OBSERVATION_CLOSED)
    # A valid real-time state wins over the plan calendar and the conflict is kept.
    assert closed.conflict == "CALENDAR_OBSERVATION_CONFLICT"
    assert closed.calendar_stale is False


def test_absent_observation_composes_from_the_plan_calendar(published):
    # The SDK composition may let the plan calendar answer when nothing was
    # observed; the answer records the absent observation explicitly and the
    # direct-mode gate (covered separately) refuses a calendar-only answer.
    result = status(published, Port(None))
    assert (result.state, result.source) == (STATE_TRADABLE, "CALENDAR")
    assert result.observation_state == "ABSENT"
    assert result.reason_code == REASON_CALENDAR_CONTINUOUS_NO_OBSERVATION


def test_generation_mismatch_and_stale_source_are_unknown(published):
    mismatched = status(published, Port(view("2", generation="2")))
    assert mismatched.state == STATE_UNKNOWN
    assert mismatched.reason_code == "OBSERVATION_GENERATION_MISMATCH"

    other_day = status(published, Port(view("2", day=date(2026, 10, 9))))
    assert other_day.state == STATE_UNKNOWN
    assert other_day.reason_code == "OBSERVATION_TRADING_DAY_MISMATCH"

    ledger = InstrumentStatusLedger(
        session_generation=GENERATION, trading_day=MONDAY.strftime("%Y%m%d")
    )
    view("2", ledger=ledger)
    ledger.mark_source_unavailable()
    stale_view = ledger.view(VENUE, CONTRACT)
    assert stale_view.state == "stale"
    stale = status(published, Port(stale_view))
    assert stale.state == STATE_UNKNOWN
    assert stale.reason_code == "OBSERVATION_SOURCE_UNAVAILABLE"


def test_unknown_category_is_unknown(published):
    result = status(published, Port(view("9")))
    assert result.state == STATE_UNKNOWN
    assert result.reason_code == "OBSERVATION_CATEGORY_UNKNOWN"


def test_open_day_without_a_window_is_unknown(published):
    # No ``at`` and no ``window_id``: an open day has no classified phase.
    result = status(published, Port(view("2")), at=None)
    assert result.state == STATE_UNKNOWN
    assert result.reason_code == "CALENDAR_PHASE_UNSPECIFIED"


def test_explicit_window_and_observation_override_the_port(published):
    port = Port(view("6"))
    result = status(published, port, window_id="day", observation=view("2"))
    assert (result.state, result.source) == (STATE_TRADABLE, "OBSERVATION")
    assert port.scopes == []  # an explicit observation never consults the port

    unknown_window = status(published, Port(view("2")), window_id="absent")
    assert unknown_window.state == STATE_UNKNOWN


def test_store_without_a_configured_calendar_stays_unknown(monkeypatch):
    store, _api = make_store(monkeypatch)
    result = status(store, Port(view("2")))
    assert result.state == STATE_UNKNOWN
    assert result.calendar_state in ("UNKNOWN", "INVALID")
    assert result.calendar_reason in (
        "CALENDAR_UNAVAILABLE",
        "CALENDAR_INVALID",
        "CALENDAR_MISSING",
        "CALENDAR_SCOPE_MISMATCH",
    )
    assert result.authorizes_trading is False


def test_unproven_scope_route_and_port_failure_are_unavailable(published):
    invalid_day = status(published, Port(None), trading_day="2026-10-12")
    assert isinstance(invalid_day, _InstrumentStatusUnavailable)
    assert (invalid_day.state, invalid_day.reason_code) == ("UNKNOWN", "INVALID_SCOPE")

    unconfigured = status(published, Port(None), route="MISSING___FUTURE")
    assert unconfigured.reason_code == "ROUTE_UNCONFIGURED"

    port = Port(error=RuntimeError("provider details must not escape"))
    failed = status(published, port)
    assert (failed.state, failed.reason_code) == ("UNKNOWN", "STATUS_PORT_UNAVAILABLE")

    # No port and no explicit observation is the SDK's explicit absence: the
    # plan calendar may answer, and the absence itself is reported.
    no_port = status(published, None)
    assert no_port.observation_state == "ABSENT"
    assert no_port.reason_code == REASON_CALENDAR_CONTINUOUS_NO_OBSERVATION


def test_observation_for_another_instrument_is_unknown(published):
    result = status(published, Port(view("2", symbol="cu9999")))
    assert result.state == STATE_UNKNOWN
    assert result.reason_code == "OBSERVATION_SCOPE_MISMATCH"


def test_no_network_and_no_calendar_write(monkeypatch, tmp_path, published):
    def blocked(*_args, **_kwargs):
        raise AssertionError("the status accessor must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    before = sorted(
        (path.relative_to(tmp_path), path.read_bytes())
        for path in (tmp_path / "calendars").rglob("*")
        if path.is_file()
    )
    result = status(published, Port(view("2")))
    after = sorted(
        (path.relative_to(tmp_path), path.read_bytes())
        for path in (tmp_path / "calendars").rglob("*")
        if path.is_file()
    )
    assert result.state == STATE_TRADABLE
    assert before == after


def test_source_configuration_is_explicit_and_validated(published):
    assert published.instrument_status_source_configured() is False
    with pytest.raises(BtApiStoreError) as refused:
        published.configure_instrument_status_port(object())
    assert refused.value.args == ("instrument_status_port_invalid",)
    port = Port(view("2"))
    published.configure_instrument_status_port(port)
    assert published.instrument_status_source_configured() is True
    published.configure_instrument_status_port(None)
    assert published.instrument_status_source_configured() is False
