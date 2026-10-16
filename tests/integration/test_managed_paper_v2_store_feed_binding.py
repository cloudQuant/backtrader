"""Bind the real Store feed's quote cursor to a V2 managed-paper fill.

This is a narrow companion to the accepted fresh-process recovery fixture. It
reuses that fixture's real local ServiceHost, SDK runtime, BtApiBroker,
ServiceExecutionSession, and managed-paper strategy, while replacing the
market-data and final paper-quote provider leaves with deterministic synthetic
sources. The old ACK/recovery node remains a separate accepted input and is
not invoked here.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import multiprocessing
import time
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal

import pytest

pytest.importorskip("bt_api_py")
if importlib.util.find_spec("bt_api_execution") is None:
    pytest.skip(
        "bt_api_execution package is not installed", allow_module_level=True
    )
pytest.importorskip("zmq")

import backtrader as bt  # noqa: E402
from backtrader.events import TickEvent  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store  # noqa: E402
from tests.integration import (
    test_managed_paper_v2_fresh_process_recovery as _accepted,
)  # noqa: E402


_INSTRUMENT = _accepted._INSTRUMENT
_DATA_NAME = "managed-paper-store-feed"
_QUOTE_AS_OF_NS = None


@dataclass(frozen=True)
class _SyntheticQuoteFixture:
    source_ref: str = _accepted._QUOTE_SOURCE_REF
    generation: str = _accepted._QUOTE_GENERATION
    cursor: int = 1
    instrument: str = _INSTRUMENT
    metadata_version: str = _accepted._METADATA_VERSION
    bid: Decimal = Decimal("10.00")
    ask: Decimal = _accepted._FILL_PRICE
    depth: Decimal = Decimal("5")


_QUOTE = _SyntheticQuoteFixture()


class _FiniteSyntheticTickClient(FakeBtApiClient):
    """Finite market-data leaf with a public final event-time watermark."""

    def __init__(self, ticks):
        super().__init__(
            balance={"cash": 1_000.0},
            positions=[],
            open_orders=[],
            live_ticks={_INSTRUMENT: ticks},
        )
        self.served_cursors: list[tuple[str, int]] = []
        self.final_event_time = ticks[-1].datetime

    def poll_tick(self, dataname):
        tick = super().poll_tick(dataname)
        if tick is not None:
            self.served_cursors.append(
                (tick.connection_generation, tick.ingest_seq)
            )
        return tick

    def is_source_exhausted(self, dataname):
        queue = self.live_ticks.get(dataname)
        return dataname == _INSTRUMENT and not queue

    def get_source_event_time_watermark(self, dataname):
        if dataname != _INSTRUMENT:
            return None
        return self.final_event_time


class _StoreFeedPaperQuoteSource:
    """The final paper matcher reads the same immutable synthetic quote."""

    def __init__(self):
        self.calls: list[str] = []

    def read_quote(self, instrument):
        from bt_api_execution import PaperQuoteV1

        self.calls.append(instrument)
        if instrument != _QUOTE.instrument:
            return None
        return PaperQuoteV1(
            source_ref=_QUOTE.source_ref,
            generation=_QUOTE.generation,
            cursor=_QUOTE.cursor,
            instrument=_QUOTE.instrument,
            metadata_version=_QUOTE.metadata_version,
            quote_currency="USDT",
            bid=_QUOTE.bid,
            ask=_QUOTE.ask,
            bid_quantity=_QUOTE.depth,
            ask_quantity=_QUOTE.depth,
            as_of_ns=_QUOTE_AS_OF_NS,
        )


def _host_process_with_store_feed_quote(
    control, raw_config, registry_path, store_path, keys, quote_as_of_ns
):
    """Run the accepted Host fixture with this test's final quote provider."""

    global _QUOTE_AS_OF_NS
    _QUOTE_AS_OF_NS = quote_as_of_ns
    _accepted._QUOTE_CURSOR = _QUOTE.cursor
    _accepted._SyntheticQuoteSource = _StoreFeedPaperQuoteSource
    _accepted._host_process(control, raw_config, registry_path, store_path, keys)


def _synthetic_ticks(quote_as_of_ns):
    first = quote_as_of_ns / 1_000_000_000
    events = []
    for sequence, timestamp in ((1, first), (2, first + 1.0)):
        tick = TickEvent(
            timestamp=timestamp,
            symbol=_INSTRUMENT,
            exchange="synthetic-paper",
            asset_type="spot",
            local_time=timestamp,
            price=float(_QUOTE.ask),
            volume=1.0,
            direction="buy",
            trade_id=f"store-feed-synthetic-{sequence}",
            bid_price=float(_QUOTE.bid),
            ask_price=float(_QUOTE.ask),
            bid_volume=float(_QUOTE.depth),
            ask_volume=float(_QUOTE.depth),
        )
        tick.datetime = dt.datetime.fromtimestamp(
            timestamp, dt.timezone.utc
        ).replace(tzinfo=None)
        tick.connection_generation = _QUOTE.generation
        tick.ingest_seq = sequence
        events.append(tick)
    return events


def _build_store_feed_cerebro(broker, control, crash_on_fill, captured):
    store = broker.store
    feed = store.getdata(
        dataname=_INSTRUMENT,
        timeframe=bt.TimeFrame.Ticks,
        compression=1,
        backfill_start=False,
        service_recovery_quote_binding=True,
        service_recovery_quote_source_ref=_QUOTE.source_ref,
    )
    if type(feed) is not BtApiFeed:
        raise AssertionError("BtApiStore.getdata did not construct the production BtApiFeed")

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    cerebro.adddata(feed, name=_DATA_NAME)
    cerebro.addstrategy(
        _accepted._ManagedV2RecoveryStrategy,
        pipe=control,
        crash_on_fill=crash_on_fill,
    )
    captured["feed"] = feed
    captured["store"] = store
    return cerebro


def _run_process_with_store_feed(control, endpoint, keys, run_id, journal_path,
                                 crash_on_fill, stale_lease_token,
                                 quote_as_of_ns):
    """Install synthetic Store/feed leaves inside the spawned runner process."""

    global _QUOTE_AS_OF_NS
    _QUOTE_AS_OF_NS = quote_as_of_ns
    captured = {}
    original_make_store = _accepted.make_store
    original_build_cerebro = _accepted._build_cerebro
    original_strategy_facts = _accepted._strategy_facts

    class _DeferredRunDoneControl:
        """Let the fixture finish cleanup before publishing the final facts."""

        def __init__(self, connection):
            self.connection = connection
            self.run_done = None

        def send(self, message):
            if message and message[0] == "run_done":
                self.run_done = message
            else:
                self.connection.send(message)

        def close(self):
            # _run_process closes this facade before returning; the wrapper
            # publishes run_done after its store/runtime finally block.
            return None

    def _make_store_with_ticks(*, api=None, provider="btapi", **kwargs):
        synthetic_api = _FiniteSyntheticTickClient(
            _synthetic_ticks(quote_as_of_ns)
        )
        store = make_store(api=synthetic_api, provider=provider, **kwargs)
        captured["api"] = synthetic_api
        captured["store"] = store
        return store

    def _build_cerebro(broker, run_control, should_crash):
        return _build_store_feed_cerebro(
            broker, run_control, should_crash, captured
        )

    def _capture_recovery_facts(strategy, broker, session, runtime):
        facts = original_strategy_facts(strategy, broker, session, runtime)
        adapter = session.adapter
        facts["intent_context"] = adapter.recovery_intent_execution_context(
            _accepted._INTENT_ID
        )
        intent_events = tuple(
            row
            for row in adapter.recovery_history()
            if row.get("event", {}).get("intent_id") == _accepted._INTENT_ID
        )
        facts["intent_event_receipts"] = intent_events
        filled_receipts = tuple(
            row
            for row in intent_events
            if row.get("event", {}).get("event_type") == "provider_observation"
            and row.get("event", {}).get("state") == "FILLED"
        )
        if len(filled_receipts) == 1:
            facts["fill_projection_receipt_id"] = filled_receipts[0]["receipt_id"]
            facts["fill_projection"] = adapter.recovery_fill_projection(
                filled_receipts[0]["receipt_id"]
            )

        feed = captured["feed"]
        store = captured["store"]
        api = captured["api"]
        facts["store_feed_evidence"] = {
            "feed_class": f"{type(feed).__module__}.{type(feed).__qualname__}",
            "is_btapi_feed": type(feed) is BtApiFeed,
            "feed_store_matches": feed.store is store,
            "quote_binding_enabled": bool(feed.p.service_recovery_quote_binding),
            "quote_source_ref": feed.p.service_recovery_quote_source_ref,
            "subscriptions": tuple(api.subscriptions),
            "served_cursors": tuple(api.served_cursors),
            "store_connected": bool(store.is_connected),
            "api_connected": bool(api.connected),
        }
        return facts

    # Windows spawn imports the accepted fixture in a fresh interpreter, so
    # bind its runtime globals inside this child instead of relying on a
    # parent-process monkeypatch.
    _accepted.make_store = _make_store_with_ticks
    _accepted._build_cerebro = _build_cerebro
    _accepted._strategy_facts = _capture_recovery_facts
    control_proxy = _DeferredRunDoneControl(control)
    try:
        _accepted._run_process(
            control_proxy,
            endpoint,
            keys,
            run_id,
            journal_path,
            crash_on_fill,
            stale_lease_token,
        )
        if control_proxy.run_done is not None:
            _, facts = control_proxy.run_done
            evidence = facts["store_feed_evidence"]
            evidence["store_connected"] = bool(captured["store"].is_connected)
            evidence["api_connected"] = bool(captured["api"].connected)
            control.send(control_proxy.run_done)
    finally:
        _accepted.make_store = original_make_store
        _accepted._build_cerebro = original_build_cerebro
        _accepted._strategy_facts = original_strategy_facts
        control.close()


def test_managed_paper_v2_store_feed_binds_synthetic_quote_to_fill(tmp_path):
    """A Store tick must become the exact quote binding persisted on a fill."""

    context = multiprocessing.get_context("spawn")
    endpoint = _accepted._endpoint()
    keys = _accepted._curve_keys()
    quote_as_of_ns = (int(time.time()) - 2) * 1_000_000_000
    registry_path = str(tmp_path / "store-feed-registry.sqlite3")
    execution_store_path = str(tmp_path / "store-feed-execution.sqlite3")
    journal_path = str(tmp_path / "store-feed-recovery-journal.sqlite3")
    host_pipe = context.Pipe(duplex=True)
    host_process = context.Process(
        target=_host_process_with_store_feed_quote,
        args=(
            host_pipe[1],
            _accepted._service_config(endpoint),
            registry_path,
            execution_store_path,
            keys,
            quote_as_of_ns,
        ),
        name="managed-paper-store-feed-host",
    )
    run_pipe = None
    run_process = None
    host = None
    facts = None
    metrics = None
    failure = None
    failure_summary = None
    cleanup_evidence = {}
    try:
        host_process.start()
        host_pipe[1].close()
        host = {"pipe": host_pipe[0], "process": host_process}
        ready = _accepted._receive(host["pipe"], timeout=_accepted._HOST_READY_TIMEOUT)
        assert ready[0] == "ready", ready
        assert ready[1] == endpoint
        assert ready[2] == "started"
        assert ready[3] is True, ready

        run_pipe = context.Pipe(duplex=True)
        run_process = context.Process(
            target=_run_process_with_store_feed,
            args=(
                run_pipe[1],
                endpoint,
                keys,
                "managed-paper-store-feed-run-r1",
                journal_path,
                False,
                None,
                quote_as_of_ns,
            ),
            name="managed-paper-store-feed-run",
        )
        run_process.start()
        run_pipe[1].close()
        configured = _accepted._receive(run_pipe[0], timeout=30.0)
        assert configured[0] == "configured", configured
        run_done = _accepted._receive(run_pipe[0], timeout=90.0)
        assert run_done[0] == "run_done", run_done
        run_process.join(30.0)
        assert run_process.exitcode == 0
        facts = run_done[1]

        # The concrete Store/client/feed assertions are captured inside the
        # spawned process and returned as primitive evidence with run_done.
        feed_evidence = facts["store_feed_evidence"]
        assert feed_evidence["is_btapi_feed"] is True
        assert feed_evidence["feed_class"] == (
            "backtrader.feeds.btapifeed.BtApiFeed"
        )
        assert feed_evidence["feed_store_matches"] is True
        assert feed_evidence["quote_binding_enabled"] is True
        assert feed_evidence["quote_source_ref"] == _QUOTE.source_ref
        assert feed_evidence["subscriptions"] == (_INSTRUMENT,)
        assert feed_evidence["served_cursors"] == (
            (_QUOTE.generation, 1),
            (_QUOTE.generation, 2),
        )
        assert feed_evidence["store_connected"] is False
        assert feed_evidence["api_connected"] is False


        assert facts["submit_calls"] == 1
        assert len(facts["trade_callbacks"]) == 1, facts["trade_callbacks"]
        trade_callback = facts["trade_callbacks"][0]
        assert trade_callback[1] == float(_accepted._FILL_QUANTITY)
        assert trade_callback[2] == float(_QUOTE.ask)
        assert facts["session_state"] == "closed"
        assert facts["cleanup_errors"] == ()
        assert facts["runtime_state"] == "closed"
        intent_receipts = facts["intent_event_receipts"]
        # One intent produces a lifecycle of journal event receipts; receipt
        # cardinality is not intent cardinality.
        assert len(intent_receipts) == 4, intent_receipts
        assert {
            row["event"]["intent_id"] for row in intent_receipts
        } == {_accepted._INTENT_ID}
        assert len({row["receipt_id"] for row in intent_receipts}) == 4
        assert all(
            row["sequence"] == row["event"]["sequence"]
            for row in intent_receipts
        )
        assert tuple(
            (
                row["sequence"],
                row["event"]["event_type"],
                row["event"]["state"],
            )
            for row in intent_receipts
        ) == (
            (1, "intent_recorded", "PENDING_ADMISSION"),
            (2, "intent_admitted", "PENDING_DISPATCH"),
            (3, "dispatch_claimed", "DISPATCHING"),
            (4, "provider_observation", "FILLED"),
        )
        assert all(row["matched_manifest"] is True for row in intent_receipts)
        fill_receipts = tuple(
            row
            for row in intent_receipts
            if row["event"]["event_type"] == "provider_observation"
            and row["event"]["state"] == "FILLED"
        )
        assert len(fill_receipts) == 1, fill_receipts
        fill_receipt = fill_receipts[0]
        assert fill_receipt["callback_pending"] is False
        assert fill_receipt["callback_acknowledged"] is True
        assert facts["fill_projection_receipt_id"] == fill_receipt["receipt_id"]
        provider_details = fill_receipt["event"]["details"]
        assert provider_details["source"] == "provider"
        assert Decimal(provider_details["filled_quantity"]) == (
            _accepted._FILL_QUANTITY
        )
        assert Decimal(provider_details["average_price"]) == _QUOTE.ask
        paper_fill = provider_details["paper_fill_v2"]
        assert paper_fill["quote_source_ref"] == _QUOTE.source_ref
        assert paper_fill["quote_generation"] == _QUOTE.generation
        assert paper_fill["quote_cursor"] == _QUOTE.cursor
        assert paper_fill["quote_instrument"] == _QUOTE.instrument

        intent_context = facts["intent_context"]
        assert intent_context is not None
        quote_binding = intent_context["quote_binding"]
        assert intent_context["feed"]["feed_class"] == (
            "backtrader.feeds.btapifeed.BtApiFeed"
        )
        assert intent_context["feed"]["data_name"] == _DATA_NAME
        assert intent_context["feed"]["instrument"] == _INSTRUMENT
        assert quote_binding == {
            "source_ref": _QUOTE.source_ref,
            "generation": _QUOTE.generation,
            "cursor": 1,
            "instrument": _INSTRUMENT,
            "as_of_ns": quote_as_of_ns,
            "data_name": _DATA_NAME,
            "bar_index": 1,
            "datetime_hex": intent_context["decision"]["datetime_hex"],
        }
        assert quote_binding["as_of_ns"] > 0

        projection = facts["fill_projection"]
        assert projection["status"] == "READY"
        assert projection["reason"] is None
        fill = projection["fill"]
        event_context = projection["event_context"]
        assert fill["quote_source_ref"] == quote_binding["source_ref"]
        assert fill["quote_generation"] == quote_binding["generation"]
        assert fill["quote_cursor"] == quote_binding["cursor"]
        assert fill["quote_instrument"] == quote_binding["instrument"]
        assert event_context["quote_source_ref"] == quote_binding["source_ref"]
        assert event_context["quote_generation"] == quote_binding["generation"]
        assert event_context["quote_cursor"] == quote_binding["cursor"]
        assert event_context["quote_instrument"] == quote_binding["instrument"]
        assert event_context["quote_as_of_ns"] == quote_binding["as_of_ns"]
        assert event_context["data_name"] == _DATA_NAME
        assert event_context["instrument"] == _INSTRUMENT
        assert event_context["bar_index"] == quote_binding["bar_index"] == 1
        assert event_context["datetime_hex"] == quote_binding["datetime_hex"]
        # These values come from the Host-persisted V2 paper fill projection,
        # not from a test-built expected receipt.
        assert Decimal(fill["quantity"]) == _accepted._FILL_QUANTITY
        assert Decimal(fill["price"]) == _QUOTE.ask
        assert fill["match_time_ns"] >= quote_binding["as_of_ns"]
        assert projection["trade_notification"] == [
            {
                "callback": "notify_trade",
                "data_name": _DATA_NAME,
                "tradeid": 0,
            }
        ]

        metric_reply = _accepted._host_command(host, ("metrics",))
        assert metric_reply[0] == "metrics", metric_reply
        metrics = metric_reply[1]
        assert metrics["record_state"] == "FILLED"
        assert metrics["dispatch_attempts"] == 1
        assert metrics["receipt_state"] == "FILLED"
        assert metrics["filled_quantity"] == str(_accepted._FILL_QUANTITY)
        assert metrics["average_price"] == str(_QUOTE.ask)
        assert metrics["receipt_price"] == str(_QUOTE.ask)
        assert metrics["book_positions"] == (
            (_INSTRUMENT, str(_accepted._FILL_QUANTITY), str(_QUOTE.ask)),
        )
        assert metrics["receipt_quote"] == (
            _QUOTE.source_ref,
            _QUOTE.generation,
            _QUOTE.cursor,
        )
        assert metrics["quote_calls"] == (_INSTRUMENT,)
        assert metrics["provider_event_count"] == 1
    except Exception as error:
        failure = error
        failure_summary = f"{type(error).__name__}: {str(error)[:300]}"
    finally:
        if run_pipe is not None:
            with suppress(Exception):
                run_pipe[0].close()
            with suppress(Exception):
                if not run_pipe[1].closed:
                    run_pipe[1].close()
        if host is not None and host["process"].is_alive():
            try:
                close_reply = _accepted._host_command(host, ("close",))
                cleanup_evidence["host_close"] = {
                    "reply": close_reply[0],
                    "state": close_reply[1],
                    "cleanup_errors": tuple(close_reply[2]),
                    "close_calls": close_reply[3],
                }
            except Exception as error:
                cleanup_evidence["host_close_error_type"] = type(error).__name__
        if run_process is not None and run_process.pid is not None:
            cleanup_evidence["runner_reap"] = _accepted._reap(
                run_process, run_pipe[0]
            )
            cleanup_evidence["runner_pipes_closed"] = (
                run_pipe[0].closed,
                run_pipe[1].closed,
            )
        if host is not None and host["process"].pid is not None:
            cleanup_evidence["host_reap"] = _accepted._reap(
                host["process"], host["pipe"]
            )
        elif host_process.pid is not None:
            cleanup_evidence["host_reap"] = _accepted._reap(
                host_process, host_pipe[0]
            )
        for connection in host_pipe:
            with suppress(Exception):
                if not connection.closed:
                    connection.close()
        cleanup_evidence["host_pipes_closed"] = (
            host_pipe[0].closed,
            host_pipe[1].closed,
        )

    if failure is not None:
        raise AssertionError(
            f"Store-feed integration failed ({failure_summary}); "
            f"cleanup evidence: {cleanup_evidence!r}"
        ) from failure

    assert cleanup_evidence.get("host_close") == {
        "reply": "closed",
        "state": "closed",
        "cleanup_errors": (),
        "close_calls": 1,
    }, cleanup_evidence
    assert cleanup_evidence.get("runner_reap") == {
        "exitcode": 0,
        "forced_cleanup": False,
    }, cleanup_evidence
    assert cleanup_evidence.get("runner_pipes_closed") == (
        True,
        True,
    ), cleanup_evidence
    assert cleanup_evidence.get("host_reap") == {
        "exitcode": 0,
        "forced_cleanup": False,
    }, cleanup_evidence
    assert cleanup_evidence.get("host_pipes_closed") == (
        True,
        True,
    ), cleanup_evidence
    assert cleanup_evidence.get("host_reap") == {
        "exitcode": 0,
        "forced_cleanup": False,
    }, cleanup_evidence
    assert cleanup_evidence.get("runner_pipes_closed") == (
        True,
        True,
    ), cleanup_evidence
    assert cleanup_evidence.get("host_pipes_closed") == (
        True,
        True,
    ), cleanup_evidence

    assert host is not None
    assert host["process"].exitcode == 0
    assert facts is not None
    assert metrics is not None
