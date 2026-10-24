"""Source-backed ordinary Alpha003 live order path over RegisteredSim.

Only the provider SDK leaves are synthetic.  The 028 Runner, Alpha003 Strategy,
cohort, Broker, Store, query refresh, execution coordinator, and journal are
the production implementations.
"""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import threading
import time

from tests.unit import test_alpha003_simnow_runner as runner_fixtures
from tests.unit.stores import test_factor_execution as execution_fixtures
from tests.unit.stores import test_factor_execution_facts as facts_fixtures


RUNNER = runner_fixtures.RUNNER
UTC = timezone.utc


def test_alpha003_live_strategy_submits_and_cancels_through_registered_sim(tmp_path, monkeypatch):
    """Ordinary Alpha003 decisions traverse real Store/Broker/query lifecycles."""
    import backtrader.stores.execution_decision_journal as journal_module
    import backtrader.stores.registered_sim as registered_sim_module
    import backtrader.brokers.btapibroker as broker_module
    import backtrader.stores.factor_execution as factor_execution_module

    start_day = runner_fixtures.CURRENT_DAY
    decision_at = runner_fixtures.DECISION_AT
    config = runner_fixtures._base_config(tmp_path, "live")
    config_path, config, full_plan, tape, _quotes = runner_fixtures._write_source_inputs(
        tmp_path,
        config,
        current_day=start_day,
        decision_at=decision_at,
    )

    # Fifty actual factor bars are enough to reach the fixture's first Alpha003
    # target while keeping this order-chain regression small.
    minute_count = 50
    plan = dict(full_plan)
    plan["grid"] = replace(full_plan["grid"], minutes=full_plan["grid"].minutes[:minute_count])
    planned_closes = {minute.close_time for minute in plan["grid"].minutes}
    target_by_instrument = {
        plan["routes"][plan["product_by_target"][target]]: target for target in plan["targets"]
    }
    bars_by_instrument = defaultdict(deque)

    def refill_bars():
        for source in tape["bars"]:
            end = datetime.fromisoformat(source["bucket_end"].replace("Z", "+00:00"))
            if end not in planned_closes:
                continue
            event = dict(source)
            for name in ("bucket_start", "bucket_end", "available_at"):
                event[name] = datetime.fromisoformat(event[name].replace("Z", "+00:00"))
            bars_by_instrument[event["instrument"]].append(event)

    refill_bars()

    def make_query_rows():
        rows = facts_fixtures._query_rows()
        rows["instruments_result"] = [
            {
                "InstrumentID": instrument,
                "ExchangeID": exchange,
                "IsTrading": 1,
                "VolumeMultiple": 10,
                "PriceTick": 0.1,
                "LowerLimitPrice": 80,
                "UpperLimitPrice": 130,
            }
            for instrument, exchange in route_rows
        ]
        rows["instrument_margin_rate_result"] = [
            {
                "InstrumentID": instrument,
                "ExchangeID": exchange,
                "HedgeFlag": "1",
                "LongMarginRatioByMoney": "0.1",
                "LongMarginRatioByVolume": "0",
                "ShortMarginRatioByMoney": "0.1",
                "ShortMarginRatioByVolume": "0",
            }
            for instrument, exchange in route_rows
        ]
        return rows

    route_rows = [
        (
            plan["routes"][plan["product_by_target"][target]],
            plan["product_by_target"][target].exchange_id,
        )
        for target in plan["targets"]
    ]
    query_rows = make_query_rows()

    event_times = tuple(
        sorted(
            {
                event["available_at"] + timedelta(milliseconds=200)
                for rows in bars_by_instrument.values()
                for event in rows
            }
        )
    )

    class SourceClock:
        """UTC follows explicit bar availability; monotonic remains real."""

        def __init__(self, times):
            self._times = tuple(times)
            self._index = 0
            # Keep the first close inside the Runner's cohort window; its
            # bucket begins about one minute before event availability.
            self._now = self._times[0] - timedelta(seconds=65)
            self._lock = threading.RLock()

        def utc_now(self):
            with self._lock:
                return self._now

        def monotonic_ns(self):
            return time.monotonic_ns()

        def advance(self, delta):
            with self._lock:
                self._now += delta
                return self._now

        def reset(self, times):
            with self._lock:
                self._times = tuple(times)
                self._index = 0
                self._now = self._times[0] - timedelta(seconds=65)

        def time_ns(self):
            return int(self.utc_now().timestamp() * 1_000_000_000)

        def wait(self, timeout_seconds):
            del timeout_seconds

        def wait_interruptibly(self, timeout_seconds, wait_for_event):
            if wait_for_event(0.0):
                return True
            with self._lock:
                while self._index < len(self._times) and self._times[self._index] <= self._now:
                    self._index += 1
                if self._index < len(self._times):
                    self._now = max(self._now, self._times[self._index])
                    self._index += 1
                    return False
            return wait_for_event(min(float(timeout_seconds), 0.01))

    clock = SourceClock(event_times)
    refresh_condition = threading.Condition()
    # Keep the ordinary Strategy projection and the real refresh/publication
    # transaction on one deterministic fake-provider turn.  SourceClock's
    # lock protects only its timestamp and cannot protect the query-set
    # receipt while QueryRefreshLoop temporarily invalidates it.
    fact_turn_lock = threading.RLock()
    refresh_state = {"started": 0, "completed": 0, "errors": []}
    refresh_receipts = []
    api_instances = []
    fill_timeline = []

    def note_fill_event(kind, **facts):
        if len(fill_timeline) >= 512 or not api_instances or api_instances[-1]._phase != 1:
            return
        fill_timeline.append(
            {
                "sequence": len(fill_timeline),
                "kind": kind,
                "source_time": clock.utc_now().isoformat(),
                "monotonic_ns": time.monotonic_ns(),
                **facts,
            }
        )

    store_write_calls = []
    broker_rejections = []
    reconciliation_observations = []
    broker_position_observations = []
    book_position_observations = []
    broker_update_observations = []

    original_terminal_reconcile = (
        factor_execution_module.FactorExecutionCoordinator.reconcile_terminal_order_observations
    )

    def traced_terminal_reconcile(coordinator, facts, **kwargs):
        page = original_terminal_reconcile(coordinator, facts, **kwargs)
        observation = {
            "query_set_id": getattr(facts, "query_set_id", None),
            "available_at": getattr(facts, "available_at", None),
            "observation_count": getattr(page, "observation_count", None),
            "truncated": getattr(page, "truncated", None),
            "items": tuple(
                (
                    getattr(item, "observation_id", None),
                    getattr(item, "status", None),
                    getattr(item, "blocker_code", None),
                    getattr(item, "intent_id", None),
                )
                for item in getattr(page, "items", ())
            ),
        }
        reconciliation_observations.append(observation)
        if any(
            item[1] not in {"RESOLVED", "DUPLICATE", "EXTERNAL_TERMINAL_FLAT"}
            for item in observation["items"]
        ):
            note_fill_event("terminal_reconciliation_blocked", **observation)
        return page

    monkeypatch.setattr(
        factor_execution_module.FactorExecutionCoordinator,
        "reconcile_terminal_order_observations",
        traced_terminal_reconcile,
    )

    original_reject_order = broker_module.BtApiBroker._reject_order

    def traced_reject_order(broker, order, error_code, error_msg):
        broker_rejections.append(
            {
                "ref": getattr(order, "ref", None),
                "data_name": getattr(getattr(order, "data", None), "_name", None),
                "size": getattr(order, "size", None),
                "error_code": error_code,
                "error_msg": error_msg,
            }
        )
        return original_reject_order(broker, order, error_code, error_msg)

    monkeypatch.setattr(broker_module.BtApiBroker, "_reject_order", traced_reject_order)

    original_position_snapshot = broker_module.BtApiBroker.execution_position_snapshot

    def traced_position_snapshot(broker, data):
        snapshot = original_position_snapshot(broker, data)
        broker_position_observations.append(
            (
                getattr(data, "_name", None),
                None if snapshot is None else getattr(snapshot, "quantity", None),
                None if snapshot is None else getattr(snapshot, "long_quantity", None),
                None if snapshot is None else getattr(snapshot, "short_quantity", None),
            )
        )
        return snapshot

    monkeypatch.setattr(
        broker_module.BtApiBroker, "execution_position_snapshot", traced_position_snapshot
    )

    for method_name in ("_apply_order_update", "_apply_trade_update"):
        original_method = getattr(broker_module.BtApiBroker, method_name)

        def trace_broker_update(broker, update, *args, _method=original_method, **kwargs):
            position_before = tuple(
                (key, getattr(position, "size", None)) for key, position in broker.positions.items()
            )
            result = _method(broker, update, *args, **kwargs)
            position_after = tuple(
                (key, getattr(position, "size", None)) for key, position in broker.positions.items()
            )
            broker_update_observations.append(
                (
                    _method.__name__,
                    update.get("kind"),
                    update.get("status"),
                    update.get("order_ref"),
                    update.get("trade_id"),
                    result,
                    position_after,
                )
            )
            note_fill_event(
                "broker_update_applied",
                method=_method.__name__,
                update_kind=update.get("kind"),
                status=update.get("status"),
                order_ref=update.get("order_ref"),
                trade_id=update.get("trade_id"),
                result=result,
                position_before=position_before,
                position_after=position_after,
            )
            return result

        monkeypatch.setattr(broker_module.BtApiBroker, method_name, trace_broker_update)

    import backtrader.stores.factor_position_book as position_book_module

    original_book_snapshot = position_book_module.FactorPositionBook.snapshot

    def traced_book_snapshot(book, **kwargs):
        snapshot = original_book_snapshot(book, **kwargs)
        book_position_observations.append(
            (
                kwargs.get("instrument"),
                getattr(snapshot, "status", None),
                getattr(snapshot, "blocker_code", None),
                getattr(snapshot, "signed_quantity", None),
                getattr(snapshot, "attributed_signed_quantity", None),
                getattr(snapshot, "owner_intent_id", None),
            )
        )
        return snapshot

    monkeypatch.setattr(position_book_module.FactorPositionBook, "snapshot", traced_book_snapshot)

    original_store_submit = registered_sim_module.RegisteredSimStore.submit_order

    def traced_store_submit(store, order):
        identity = {
            "ref": getattr(order, "ref", None),
            "data_name": getattr(getattr(order, "data", None), "_name", None),
            "size": getattr(order, "size", None),
            "price": getattr(order, "price", None),
            "info": dict(getattr(order, "info", {})),
        }
        try:
            result = original_store_submit(store, order)
        except Exception as exc:
            store_write_calls.append(
                {
                    "operation": "submit",
                    "identity": identity,
                    "error_type": type(exc).__name__,
                    "error_code": getattr(exc, "code", None),
                    "error": str(exc),
                }
            )
            raise
        store_write_calls.append(
            {"operation": "submit", "identity": identity, "result": repr(result)}
        )
        return result

    monkeypatch.setattr(
        registered_sim_module.RegisteredSimStore, "submit_order", traced_store_submit
    )

    class Alpha003Provider(execution_fixtures._FakeProviderClient):
        """Synthetic CTP query/order/tick leaves under the production wrapper."""

        def __init__(self, **kwargs):
            super().__init__(
                query_rows=query_rows,
                query_time=clock.utc_now(),
                ticks={},
                **kwargs,
            )
            client = self.trader_client
            client._account_fingerprint = "alpha003-factor-chain-account"
            client._trading_day = start_day.strftime("%Y%m%d")
            client._front_id = 4
            client._session_id = 7
            # The production wrapper grants one exact native instrument at a
            # time.  Model the SDK's public opaque-capability revoke boundary
            # so a later factor-selected target can be armed through the real
            # multi-route switch path.
            client._fake_active_capability = None
            original_arm = client.arm_execution_for_registered_sim

            def arm_execution_for_registered_sim(**arm_kwargs):
                result = original_arm(**arm_kwargs)
                client._fake_active_capability = result[0]
                return result

            def disarm_execution_gate(capability, reason):
                if capability is not client._fake_active_capability:
                    raise AssertionError("fake SDK disarm must name the active capability")
                client._fake_active_capability = None
                state = dict(client._gate_state)
                state.update(
                    managed=False,
                    armed=False,
                    instrument=None,
                    authorized_instruments=[],
                    revocation_reason=reason,
                )
                client._gate_state = state
                return {"revoked": True}

            client.arm_execution_for_registered_sim = arm_execution_for_registered_sim
            client.disarm_execution_gate = disarm_execution_gate
            client.is_ready = True
            client.is_read_only_ready = True
            client.is_trading_ready = True
            client.wait_ready = lambda timeout: True
            client._gate_state.update(
                connection_generation=client._connection_generation,
                trading_day=client._trading_day,
            )
            self._source_bars = bars_by_instrument
            self._phase = len(api_instances)
            self._sent_tick_for = {}
            self._winddown_metadata = {
                instrument: dict(rows[-1]) for instrument, rows in self._source_bars.items() if rows
            }
            self._winddown_sequences = {
                instrument: max(int(row["bar_sequence"]) for row in rows)
                for instrument, rows in self._source_bars.items()
                if rows
            }
            self._winddown_query_set_for = {}
            self._pending_fill_callback = None
            self._pending_fill_instrument = None
            self._applied_fill_query = False
            self.broker_callback_events = []
            self.tick_observations = []
            self.winddown_tick_observations = []
            self.winddown_poll_attempts = 0
            self.winddown_poll_blockers = []
            self._required_refresh_start = None
            self.closed = False
            api_instances.append(self)

        def _query_family(self, family, request_type, **filters):
            # QueryResult completion is observed after any preceding journal
            # receipt, in the same injected source clock used by the Strategy.
            started_at = clock.utc_now()
            clock.advance(timedelta(milliseconds=5))
            self.query_time = clock.utc_now()
            result = super()._query_family(family, request_type, **filters)
            note_fill_event(
                "query_completed",
                family=family,
                request_id=getattr(result, "request_id", None),
                query_started_at=started_at.isoformat(),
                query_completed_at=str(getattr(result, "completed_at_utc", None)),
                row_count=(
                    None if getattr(result, "records", None) is None else len(result.records)
                ),
                query_complete=getattr(result, "complete", None),
            )
            return result

        def get_balance(self):
            return {"cash": 1_000_000.0, "value": 1_000_000.0}

        def get_positions(self):
            """Project the same exact CTP position rows used by query facts."""
            normalized = []
            for row in query_rows["positions_result"]:
                instrument_id = row["InstrumentID"]
                exchange_id = row["ExchangeID"]
                target = target_by_instrument.get(instrument_id)
                if target is None:
                    raise AssertionError(
                        f"position row is outside the configured feed scope: {instrument_id}"
                    )
                if exchange_id != plan["product_by_target"][target].exchange_id:
                    raise AssertionError(
                        f"position exchange does not match its configured feed: {row!r}"
                    )

                quantity = Decimal(str(row["Position"]))
                if quantity <= 0:
                    continue
                position_direction = str(row["PosiDirection"])
                if position_direction == "2":
                    direction = "long"
                    ctp_direction = "0"
                elif position_direction == "3":
                    direction = "short"
                    ctp_direction = "1"
                else:
                    raise AssertionError(f"position row has no explicit CTP side: {row!r}")

                opening_trades = [
                    trade
                    for trade in query_rows["trades_result"]
                    if trade["InstrumentID"] == instrument_id
                    and trade["ExchangeID"] == exchange_id
                    and str(trade["Direction"]) == ctp_direction
                    and str(trade["OffsetFlag"]) == "0"
                    and str(trade["HedgeFlag"]) == str(row["HedgeFlag"])
                ]
                opening_quantity = sum(
                    (Decimal(str(trade["Volume"])) for trade in opening_trades),
                    Decimal("0"),
                )
                if opening_quantity < quantity:
                    raise AssertionError(
                        "provider position exceeds its query-backed OPEN trades: "
                        f"instrument={instrument_id!r}, position={quantity!r}, "
                        f"opening_quantity={opening_quantity!r}"
                    )
                if opening_quantity <= 0:
                    raise AssertionError(
                        f"position has no query-backed OPEN trade: {instrument_id}"
                    )
                average_price = (
                    sum(
                        (
                            Decimal(str(trade["Volume"])) * Decimal(str(trade["Price"]))
                            for trade in opening_trades
                        ),
                        Decimal("0"),
                    )
                    / opening_quantity
                )
                product = plan["product_by_target"][target]
                data_name = f"{exchange_id}.{product.product_id}"
                normalized.append(
                    {
                        "data_name": data_name,
                        "instrument": data_name,
                        "symbol": data_name,
                        "instrument_id": instrument_id,
                        "exchange_id": exchange_id,
                        "direction": direction,
                        "volume": float(quantity),
                        "size": float(quantity if direction == "long" else -quantity),
                        "price": float(average_price),
                        "avg_price": float(average_price),
                    }
                )
            return normalized

        def fetch_open_orders(self):
            return []

        def get_open_orders(self):
            return []

        def subscribe(self, _symbols):
            return None

        def connect(self):
            return None

        def disconnect(self):
            self.closed = True

        def poll_broker_update(self):
            update = super().poll_broker_update()
            if update is not None:
                self.broker_callback_events.append(dict(update))
                note_fill_event(
                    "callback_dequeued",
                    update_kind=update.get("kind"),
                    status=update.get("status"),
                    order_ref=update.get("order_ref"),
                    trade_id=update.get("trade_id"),
                    details=dict(update.get("details") or {}),
                )
            return update

        def _mark_refresh_required(self):
            with refresh_condition:
                self._required_refresh_start = refresh_state["started"] + 1

        def _wait_for_refresh(self):
            with refresh_condition:
                required = self._required_refresh_start
                if required is None:
                    return
                if not refresh_condition.wait_for(
                    lambda: refresh_state["completed"] >= required,
                    timeout=4.0,
                ):
                    raise AssertionError(
                        "complete provider query refresh did not follow order write"
                    )
                self._required_refresh_start = None

        def submit_order(self, payload):
            result = super().submit_order(payload)
            identity = self._provider_orders[str(result["order_ref"])]
            day_text = start_day.strftime("%Y%m%d")
            order_ref = str(result["order_ref"])
            query_rows["orders_result"][:] = [
                row for row in query_rows["orders_result"] if str(row.get("OrderRef")) != order_ref
            ]
            query_rows["orders_result"].append(
                {
                    "OrderRef": order_ref,
                    "InstrumentID": identity["instrument_id"],
                    "ExchangeID": identity["exchange_id"],
                    "TradingDay": day_text,
                    "FrontID": 4,
                    "SessionID": 7,
                    "OrderStatus": "3",
                    "Direction": "0" if identity["side"] == "buy" else "1",
                    "CombOffsetFlag": "0",
                    "VolumeTotalOriginal": str(identity["size"]),
                    "VolumeTraded": "0",
                    "VolumeTotal": str(identity["size"]),
                }
            )
            if (
                self._phase == 1
                and self._pending_fill_callback is None
                and not self._applied_fill_query
                and identity["offset"] == "open"
            ):
                self._pending_fill_callback = order_ref
                self._pending_fill_instrument = identity["instrument_id"]
            elif self._phase == 1 and identity["offset"] == "close":
                close_time = clock.utc_now() + timedelta(milliseconds=1)
                ctp_time = close_time.astimezone(timezone(timedelta(hours=8)))
                trade_id = "alpha003-close-{}".format(order_ref)
                self.emit_provider_order_callback(
                    order_ref, status="completed", filled=identity["size"], remaining=0
                )
                self._order_updates[-1]["details"]["OrderStatus"] = "0"
                self.emit_provider_trade_callback(
                    order_ref,
                    trade_id=trade_id,
                    quantity=identity["size"],
                    offset="close",
                    when=close_time,
                )
                self._order_updates[-1]["details"].update(
                    TradingDay=day_text,
                    TradeDate=ctp_time.strftime("%Y%m%d"),
                    TradeTime=ctp_time.strftime("%H:%M:%S.%f"),
                    HedgeFlag="1",
                )
                query_rows["orders_result"][-1].update(
                    OrderStatus="0",
                    CombOffsetFlag="1",
                    VolumeTraded=str(identity["size"]),
                    VolumeTotal="0",
                )
                query_rows["trades_result"].append(
                    {
                        "TradeID": trade_id,
                        "OrderRef": order_ref,
                        "OrderSysID": "",
                        "InstrumentID": identity["instrument_id"],
                        "ExchangeID": identity["exchange_id"],
                        "Direction": "1" if identity["side"] == "sell" else "0",
                        "OffsetFlag": "1",
                        "HedgeFlag": "1",
                        "Volume": str(identity["size"]),
                        "Price": "100",
                        "TradeDate": ctp_time.strftime("%Y%m%d"),
                        "TradeTime": ctp_time.strftime("%H:%M:%S.%f"),
                        "TradingDay": day_text,
                    }
                )
                query_rows["positions_result"][:] = [
                    row
                    for row in query_rows["positions_result"]
                    if row.get("InstrumentID") != identity["instrument_id"]
                ]
            self._mark_refresh_required()
            return result

        def cancel_order(self, order_ref, dataname=None):
            result = super().cancel_order(order_ref, dataname=dataname)
            identity = self._provider_orders[str(order_ref)]
            query_rows["orders_result"][:] = [
                row
                for row in query_rows["orders_result"]
                if str(row.get("OrderRef")) != str(order_ref)
            ]
            query_rows["orders_result"].append(
                {
                    "OrderRef": str(order_ref),
                    "InstrumentID": identity["instrument_id"],
                    "ExchangeID": identity["exchange_id"],
                    "TradingDay": start_day.strftime("%Y%m%d"),
                    "FrontID": 4,
                    "SessionID": 7,
                    "OrderStatus": "5",
                    "Direction": "0" if identity["side"] == "buy" else "1",
                    "CombOffsetFlag": "0",
                    "VolumeTotalOriginal": str(identity["size"]),
                    "VolumeTraded": "0",
                    "VolumeTotal": "0",
                }
            )
            self.emit_provider_order_callback(order_ref, status="canceled", filled=0, remaining=0)
            # The generated CTP wrapper keeps the raw numeric status in the
            # source details but normalizes the callback's top-level status
            # before Store.poll_broker_update() hands it to Broker.
            self._order_updates[-1]["details"]["OrderStatus"] = "5"
            self._mark_refresh_required()
            return result

        def poll_tick(self, instrument):
            rows = self._source_bars.get(instrument)
            if not rows:
                # Successful cohort winddown polls the same provider tick
                # method through BtApiFeed's bounded quote-only drain. Emit a
                # typed source event only after a complete current query set
                # has finished; never relabel an old bar or processing time as
                # a fresh quote.
                if self._phase != 1:
                    return None
                self.winddown_poll_attempts += 1
                with refresh_condition:
                    if (
                        refresh_state["started"] == 0
                        or refresh_state["started"] != refresh_state["completed"]
                        or not refresh_receipts
                    ):
                        self.winddown_poll_blockers.append("refresh_not_quiescent")
                        return None
                    receipt = dict(refresh_receipts[-1])
                    if receipt["attempt"] != refresh_state["completed"]:
                        self.winddown_poll_blockers.append("receipt_attempt_not_current")
                        return None

                if (
                    not receipt["query_set_id"]
                    or receipt["blockers"]
                    or receipt["pending_families"]
                    or receipt["cancelled"]
                    or receipt["deadline_reached"]
                    or tuple(receipt["attempted_families"]) != tuple(receipt["requested_families"])
                ):
                    self.winddown_poll_blockers.append("latest_receipt_incomplete")
                    return None
                provenance = tuple(receipt["provenance"])
                if len(provenance) != len(receipt["requested_families"]):
                    return None
                if any(
                    query_complete is not True
                    or source_owned is not True
                    or (target_id is None and scope_complete is not True)
                    or not request_id
                    or completed_at is None
                    for (
                        _family,
                        target_id,
                        query_complete,
                        source_owned,
                        scope_complete,
                        request_id,
                        completed_at,
                    ) in provenance
                ):
                    self.winddown_poll_blockers.append("query_provenance_incomplete")
                    return None
                query_set_id = receipt["query_set_id"]
                if self._winddown_query_set_for.get(instrument) == query_set_id:
                    self.winddown_poll_blockers.append("quote_already_sent_for_query_set")
                    return None
                row = self._winddown_metadata.get(instrument)
                if row is None:
                    self.winddown_poll_blockers.append("source_bar_metadata_missing")
                    return None

                completed_times = []
                for item in provenance:
                    value = item[-1]
                    if isinstance(value, datetime):
                        completed_at = value
                    else:
                        completed_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    if completed_at.tzinfo is None or completed_at.utcoffset() != timedelta(0):
                        self.winddown_poll_blockers.append("query_time_not_utc")
                        return None
                    completed_times.append(completed_at)
                if not completed_times:
                    self.winddown_poll_blockers.append("query_completion_time_missing")
                    return None

                source_now = clock.utc_now()
                latest_query_time = max(completed_times)
                if source_now < latest_query_time:
                    clock.advance(latest_query_time - source_now)
                event_time = clock.advance(timedelta(milliseconds=1))
                sequence = self._winddown_sequences.get(instrument, 0) + 1
                self._winddown_sequences[instrument] = sequence
                tick = facts_fixtures._quote(
                    event_time=event_time,
                    received_at=event_time,
                    symbol=instrument,
                    exchange=row["exchange"],
                    generation=client_generation(self),
                    sequence=sequence,
                    trading_day=row["trading_day"].replace("-", ""),
                )
                tick.clock_domain_id = row["clock_domain_id"]
                tick.session_segment = row["session_segment"]
                tick.timezone_id = row["timezone_id"]
                tick.volume = 0.0
                self._winddown_query_set_for[instrument] = query_set_id
                observation = {
                    "instrument": instrument,
                    "instrument_id": tick.instrument_id,
                    "query_set_id": query_set_id,
                    "query_completed_at": latest_query_time,
                    "event_time": event_time,
                    "received_at": event_time,
                    "sequence": sequence,
                    "event_id": tick.event_id,
                }
                self.winddown_tick_observations.append(observation)
                note_fill_event("quote_only_tick_returned", **observation)
                return tick
            row = rows[0]
            if row["available_at"] > clock.utc_now():
                return None
            bar_id = row["bar_id"]
            if self._sent_tick_for.get(instrument) == bar_id:
                return None
            self._sent_tick_for[instrument] = bar_id
            close = row["bucket_end"]
            tick = facts_fixtures._quote(
                event_time=close + timedelta(seconds=2, milliseconds=10),
                received_at=close + timedelta(seconds=2, milliseconds=20),
                symbol=instrument,
                exchange="DCE",
                generation=client_generation(self),
                sequence=row["bar_sequence"],
                # Provider ticks carry CTP's compact TradingDay; the separate
                # completed-bar tape uses the cohort's ISO calendar day.
                trading_day=row["trading_day"].replace("-", ""),
            )
            # The cohort only accepts quote provenance from the same declared
            # clock/session contract as its completed member bar.
            tick.clock_domain_id = row["clock_domain_id"]
            tick.session_segment = row["session_segment"]
            tick.timezone_id = row["timezone_id"]
            # This leaf delivers the trade-backed bar separately through
            # poll_bar; the consumed event here is a quote observation, not a
            # second trade contribution that could create a conflicting bar.
            tick.volume = 0.0
            self.tick_observations.append(
                (instrument, bar_id, tick.connection_generation, row["connection_generation"])
            )
            return tick

        def poll_bar(self, instrument):
            self._wait_for_refresh()
            if (
                self._phase == 1
                and instrument == self._pending_fill_instrument
                and self._pending_fill_callback is not None
                and not self._applied_fill_query
            ):
                order_ref = self._pending_fill_callback
                identity = self._provider_orders[order_ref]
                fill_time = clock.utc_now() + timedelta(milliseconds=1)
                ctp_time = fill_time.astimezone(timezone(timedelta(hours=8)))
                trade_id = "alpha003-open-{}".format(order_ref)
                note_fill_event(
                    "callback_emitted",
                    order_ref=order_ref,
                    trade_id=trade_id,
                    trade_event_time=fill_time.isoformat(),
                    query_position_before=tuple(
                        (row.get("InstrumentID"), row.get("Position"))
                        for row in query_rows["positions_result"]
                    ),
                )
                self.emit_provider_order_callback(
                    order_ref, status="completed", filled=identity["size"], remaining=0
                )
                self._order_updates[-1]["details"]["OrderStatus"] = "0"
                self.emit_provider_trade_callback(
                    order_ref,
                    trade_id=trade_id,
                    quantity=identity["size"],
                    offset="open",
                    when=fill_time,
                )
                self._order_updates[-1]["details"].update(
                    TradingDay=start_day.strftime("%Y%m%d"),
                    TradeDate=ctp_time.strftime("%Y%m%d"),
                    TradeTime=ctp_time.strftime("%H:%M:%S.%f"),
                    HedgeFlag="1",
                )
                for row in query_rows["orders_result"]:
                    if str(row.get("OrderRef")) == order_ref:
                        row.update(
                            OrderStatus="0",
                            VolumeTraded=str(identity["size"]),
                            VolumeTotal="0",
                        )
                query_rows["trades_result"].append(
                    {
                        "TradeID": trade_id,
                        "OrderRef": order_ref,
                        "OrderSysID": "",
                        "InstrumentID": identity["instrument_id"],
                        "ExchangeID": identity["exchange_id"],
                        "Direction": "0" if identity["side"] == "buy" else "1",
                        "OffsetFlag": "0",
                        "HedgeFlag": "1",
                        "Volume": str(identity["size"]),
                        "Price": "100",
                        "TradeDate": ctp_time.strftime("%Y%m%d"),
                        "TradeTime": ctp_time.strftime("%H:%M:%S.%f"),
                        "TradingDay": start_day.strftime("%Y%m%d"),
                    }
                )
                position = facts_fixtures._dated_position_row(
                    identity["size"],
                    side="LONG" if identity["side"] == "buy" else "SHORT",
                    trading_day=start_day.strftime("%Y%m%d"),
                )
                position.update(InstrumentID=identity["instrument_id"], ExchangeID="DCE")
                query_rows["positions_result"][:] = [
                    row
                    for row in query_rows["positions_result"]
                    if row.get("InstrumentID") != identity["instrument_id"]
                ]
                query_rows["positions_result"].append(position)
                note_fill_event(
                    "fill_rows_published",
                    order_ref=order_ref,
                    trade_id=trade_id,
                    order_status=query_rows["orders_result"][-1].get("OrderStatus"),
                    trade_count=len(query_rows["trades_result"]),
                    position_rows=tuple(
                        (row.get("InstrumentID"), row.get("Position"))
                        for row in query_rows["positions_result"]
                    ),
                )
                self._pending_fill_callback = None
                self._pending_fill_instrument = None
                self._applied_fill_query = True
                self._mark_refresh_required()
            rows = self._source_bars.get(instrument)
            if not rows:
                return None
            if rows[0]["available_at"] > clock.utc_now():
                return None
            row = rows.popleft()
            self._sent_tick_for.pop(instrument, None)
            return row

    def client_generation(api):
        return api.trader_client._connection_generation

    original_factory = registered_sim_module._make_api_factory
    monkeypatch.setattr(
        registered_sim_module,
        "_make_api_factory",
        lambda allow_writes, history_limit, terminal_limit, api_cls: original_factory(
            allow_writes, history_limit, terminal_limit, Alpha003Provider
        ),
    )
    monkeypatch.setattr(RUNNER, "_live_env_config", lambda _config: ({}, {}))
    monkeypatch.setattr(RUNNER, "RunnerWallClock", lambda: clock)

    captured_strategies = []
    strategy_decision_trace = []
    idle_decision_trace = []
    store_tick_trace = []
    chain_trace = []
    risk_scope_trace = []
    risk_dispatch_trace = []
    diagnostic_path = (
        Path(__file__).resolve().parents[2]
        / ".codex-tmp"
        / "alpha003_registered_sim_order_chain_{}.json".format(time.time_ns())
    )

    def persist_diagnostic(stage, *, result_value=None, error=None, archive_evidence=None):
        def result_summary(value):
            if not isinstance(value, dict):
                return None
            if "phase1" in value or "phase2" in value:
                return {
                    phase: result_summary(value.get(phase))
                    for phase in ("phase1", "phase2")
                    if phase in value
                }
            summary = {
                key: value.get(key)
                for key in (
                    "write_mode",
                    "shutdown_status",
                    "cleanup_complete",
                    "resource_shutdown",
                    "strategy_shutdown_blocker",
                    "strategy_shutdown_post_join_blocker",
                    "decision_tape",
                    "decision_tape_readback",
                )
                if key in value
            }
            events = value.get("strategy_order_events")
            if isinstance(events, dict):
                summary["strategy_order_events"] = {
                    "events": tuple(tuple(events.get("events") or ())[-32:])
                }
            return summary

        strategy = captured_strategies[-1] if captured_strategies else None
        refresh_loop = (
            getattr(getattr(strategy, "p", None), "control_refresh_loop", None)
            if strategy is not None
            else None
        )
        fact = getattr(strategy, "last_execution_facts", None)
        plan_now = getattr(strategy, "last_order_plan", None)
        payload = {
            "schema": "alpha003_registered_sim_order_chain_diagnostic_v1",
            "stage": stage,
            "captured_at_utc": clock.utc_now().isoformat(),
            "argv": tuple(sys.argv),
            "error": (None if error is None else (type(error).__name__, str(error)[:512])),
            "refresh": {
                "started": refresh_state["started"],
                "completed": refresh_state["completed"],
                "errors": tuple(refresh_state["errors"][-16:]),
                "receipts": tuple(refresh_receipts[-32:]),
                "published_query_set_id": getattr(
                    getattr(getattr(refresh_loop, "last_receipt", None), "query_set", None),
                    "query_set_id",
                    None,
                ),
                "published_facts_query_set_id": getattr(
                    getattr(refresh_loop, "last_facts", None), "query_set_id", None
                ),
                "last_error_code": getattr(refresh_loop, "last_error_code", None),
            },
            "strategy": (
                None
                if strategy is None
                else {
                    "last_batch_id": strategy._last_batch_id,
                    "last_execution_block_reason": strategy.last_execution_block_reason,
                    "facts": (
                        None
                        if fact is None
                        else {
                            "snapshot_id": getattr(fact, "snapshot_id", None),
                            "query_set_id": getattr(fact, "query_set_id", None),
                            "available_at": getattr(fact, "available_at", None),
                            "blockers": getattr(fact, "blockers", None),
                            "risk_reduction_blockers": getattr(
                                fact, "risk_reduction_blockers", None
                            ),
                            "order_cancel_blockers": getattr(fact, "order_cancel_blockers", None),
                            "quotes": tuple(
                                (
                                    getattr(quote, "instrument", None),
                                    getattr(quote, "source", None),
                                    getattr(quote, "sequence", None),
                                    getattr(quote, "event_time", None),
                                    getattr(quote, "available_at", None),
                                    getattr(quote, "quality", None),
                                )
                                for quote in getattr(fact, "quotes", ())
                            ),
                        }
                    ),
                    "plan": (
                        None
                        if plan_now is None
                        else {
                            "status": getattr(plan_now, "status", None),
                            "reason": getattr(plan_now, "reason", None),
                            "actions": tuple(
                                (
                                    getattr(action, "action", None),
                                    getattr(action, "instrument", None),
                                    getattr(action, "position_effect", None),
                                    getattr(action, "quantity", None),
                                    getattr(action, "offset", None),
                                    getattr(action, "reason", None),
                                )
                                for action in getattr(plan_now, "actions", ())
                            ),
                        }
                    ),
                    "order_events": tuple(
                        dict(event) if hasattr(event, "items") else str(event)[:512]
                        for event in tuple(getattr(strategy, "order_events", ()) or ())[-16:]
                    ),
                }
            ),
            "apis": tuple(
                {
                    "phase": current_api._phase,
                    "closed": current_api.closed,
                    "native_calls": tuple(current_api.native_calls[-64:]),
                }
                for current_api in api_instances[-2:]
            ),
            "provider_rows": {
                family: tuple(query_rows.get(family, ())[-32:])
                for family in (
                    "account_result",
                    "positions_result",
                    "orders_result",
                    "trades_result",
                    "instruments_result",
                    "instrument_margin_rate_result",
                )
            },
            "archive_evidence": archive_evidence,
            "refresh_counts": (refresh_state["started"], refresh_state["completed"]),
            "strategy_callbacks": tuple(strategy_decision_trace[-256:]),
            "provider_timeline": tuple(fill_timeline[-512:]),
            "store_ticks": tuple(store_tick_trace[-128:]),
            "chain_trace": tuple(chain_trace[-128:]),
            "risk_scopes": tuple(risk_scope_trace[-64:]),
            "risk_dispatch": tuple(risk_dispatch_trace[-32:]),
            "reconciliation": tuple(reconciliation_observations[-32:]),
            "store_write_calls": tuple(store_write_calls[-64:]),
            "broker_rejections": tuple(broker_rejections[-64:]),
            "result": result_summary(result_value),
        }
        diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostic_path.write_text(
            json.dumps(payload, default=str, sort_keys=True, indent=2), encoding="utf-8"
        )
        return str(diagnostic_path)

    original_scope_enter = factor_execution_module.FactorExecutionDecisionScope.__enter__

    def traced_scope_enter(scope):
        try:
            result = original_scope_enter(scope)
        except Exception as error:
            if getattr(scope, "risk_only", False):
                risk_scope_trace.append(
                    {
                        "kind": "risk_scope_enter_failed",
                        "decision_kind": getattr(scope.key, "decision_kind", None),
                        "close_time": getattr(scope.key, "close_time", None),
                        "intents": tuple(scope.intent_keys),
                        "error": (type(error).__name__, str(error)),
                    }
                )
            raise
        if getattr(scope, "risk_only", False):
            risk_scope_trace.append(
                {
                    "kind": "risk_scope_entered",
                    "decision_kind": getattr(scope.key, "decision_kind", None),
                    "close_time": getattr(scope.key, "close_time", None),
                    "decision_id": scope.decision_id,
                    "intent_keys": tuple(scope.intent_keys),
                    "dispatch_allowed": scope.dispatch_allowed,
                    "is_new_grid": scope.is_new_grid,
                    "run_order_intents_used": scope.run_order_intents_used,
                }
            )
        if len(risk_scope_trace) > 64:
            del risk_scope_trace[:-64]
        return result

    monkeypatch.setattr(
        factor_execution_module.FactorExecutionDecisionScope,
        "__enter__",
        traced_scope_enter,
    )
    original_bind_strategy = RUNNER.QueryRefreshLoop.bind_strategy

    def capture_bound_strategy(loop, strategy):
        original_bind_strategy(loop, strategy)
        captured_strategies.append(strategy)

        original_next = strategy.next
        original_notify_idle = strategy.notify_idle
        original_run_live = strategy._run_live

        def trace_strategy_turn(callback_name, callback, *args, **kwargs):
            with fact_turn_lock:
                # This timestamp is the strategy turn's first source-clock
                # observation, after it owns the same lock as query refresh.
                callback_requested_at = clock.utc_now()
                refresh_loop = strategy.p.control_refresh_loop
                receipt_before = getattr(refresh_loop, "last_receipt", None)
                before_query_set = getattr(
                    getattr(receipt_before, "query_set", None), "query_set_id", None
                )
                before_refresh = (refresh_state["started"], refresh_state["completed"])
                try:
                    result = callback(*args, **kwargs)
                except Exception as exc:
                    if len(strategy_decision_trace) < 256:
                        strategy_decision_trace.append(
                            {
                                "kind": "strategy_callback_error",
                                "callback": callback_name,
                                "requested_at": callback_requested_at.isoformat(),
                                "query_set_before": before_query_set,
                                "refresh_started_completed_before": before_refresh,
                                "error": (type(exc).__name__, str(exc)[:512]),
                            }
                        )
                    raise
                api = api_instances[-1] if api_instances else None
                if api is not None and api._phase == 1 and len(strategy_decision_trace) < 256:
                    facts = strategy.last_execution_facts
                    plan_now = strategy.last_order_plan
                    receipt_after = getattr(refresh_loop, "last_receipt", None)
                    strategy_decision_trace.append(
                        {
                            "kind": "strategy_callback",
                            "callback": callback_name,
                            "requested_at": callback_requested_at.isoformat(),
                            "entered_at": clock.utc_now().isoformat(),
                            "refresh_started_completed_before": before_refresh,
                            "refresh_started_completed_after": (
                                refresh_state["started"],
                                refresh_state["completed"],
                            ),
                            "query_set_before": before_query_set,
                            "query_set_after": getattr(
                                getattr(receipt_after, "query_set", None),
                                "query_set_id",
                                None,
                            ),
                            "last_error_code": getattr(refresh_loop, "last_error_code", None),
                            "batch_id": strategy._last_batch_id,
                            "execution_block_reason": strategy.last_execution_block_reason,
                            "facts": (
                                None
                                if facts is None
                                else {
                                    "snapshot_id": getattr(facts, "snapshot_id", None),
                                    "query_set_id": getattr(facts, "query_set_id", None),
                                    "available_at": getattr(facts, "available_at", None),
                                    "blockers": getattr(facts, "blockers", None),
                                    "risk_reduction_blockers": getattr(
                                        facts, "risk_reduction_blockers", None
                                    ),
                                    "order_cancel_blockers": getattr(
                                        facts, "order_cancel_blockers", None
                                    ),
                                    "quotes": tuple(
                                        (
                                            getattr(quote, "instrument", None),
                                            getattr(quote, "source", None),
                                            getattr(quote, "sequence", None),
                                            getattr(quote, "event_time", None),
                                            getattr(quote, "available_at", None),
                                            getattr(quote, "quality", None),
                                        )
                                        for quote in getattr(facts, "quotes", ())
                                    ),
                                }
                            ),
                            "plan": (
                                None
                                if plan_now is None
                                else {
                                    "status": getattr(plan_now, "status", None),
                                    "reason": getattr(plan_now, "reason", None),
                                    "actions": tuple(
                                        (
                                            getattr(action, "action", None),
                                            getattr(action, "instrument", None),
                                            getattr(action, "position_effect", None),
                                            getattr(action, "quantity", None),
                                            getattr(action, "offset", None),
                                            getattr(action, "reason", None),
                                        )
                                        for action in getattr(plan_now, "actions", ())
                                    ),
                                }
                            ),
                        }
                    )
                return result

        def traced_next(*args, **kwargs):
            return trace_strategy_turn("next", original_next, *args, **kwargs)

        def traced_notify_idle(*args, **kwargs):
            return trace_strategy_turn("notify_idle", original_notify_idle, *args, **kwargs)

        strategy.next = traced_next
        strategy.notify_idle = traced_notify_idle

        def traced_run_live(batch, snapshot, now, ordinal, session_close, run_end, **kwargs):
            result = original_run_live(
                batch, snapshot, now, ordinal, session_close, run_end, **kwargs
            )
            api = api_instances[-1] if api_instances else None
            if api is not None and api._phase == 1 and strategy.shutdown_requested:
                facts = strategy.last_execution_facts
                plan_now = strategy.last_order_plan
                observation = {
                    "sequence": len(chain_trace),
                    "kind": "strategy_run_live",
                    "now": now.isoformat() if hasattr(now, "isoformat") else now,
                    "batch_id": getattr(batch, "batch_id", None),
                    "run_end": run_end,
                    "snapshot_id": getattr(facts, "snapshot_id", None),
                    "query_set_id": getattr(facts, "query_set_id", None),
                    "facts_available_at": getattr(facts, "available_at", None),
                    "risk_reduction_ready": getattr(facts, "risk_reduction_ready", None),
                    "risk_reduction_blockers": getattr(facts, "risk_reduction_blockers", None),
                    "positions": tuple(
                        (
                            getattr(position, "instrument", None),
                            getattr(position, "quantity", None),
                            getattr(position, "position_book_status", None),
                            getattr(position, "position_book_blocker_code", None),
                            getattr(position, "owner_strategy_scope", None),
                            getattr(position, "owner_intent_id", None),
                            getattr(position, "stop_price", None),
                        )
                        for position in getattr(facts, "positions", ())
                    ),
                    "quotes": tuple(
                        (
                            getattr(quote, "instrument", None),
                            getattr(quote, "event_time", None),
                            getattr(quote, "available_at", None),
                            getattr(quote, "quality", None),
                        )
                        for quote in getattr(facts, "quotes", ())
                    ),
                    "plan": (
                        getattr(plan_now, "status", None),
                        getattr(plan_now, "reason", None),
                        tuple(
                            (
                                getattr(action, "action", None),
                                getattr(action, "instrument", None),
                                getattr(action, "position_effect", None),
                                getattr(action, "quantity", None),
                                getattr(action, "offset", None),
                                getattr(action, "reason", None),
                            )
                            for action in getattr(plan_now, "actions", ())
                        ),
                    ),
                    "shutdown": (
                        strategy.shutdown_ready,
                        strategy.shutdown_blocker,
                    ),
                    "latest_winddown_ticks": tuple(api.winddown_tick_observations[-3:]),
                }
                idle_decision_trace.append(observation)
                chain_trace.append(observation)
                if len(idle_decision_trace) > 128:
                    del idle_decision_trace[:-128]
                if len(chain_trace) > 128:
                    del chain_trace[:-128]
            return result

        strategy._run_live = traced_run_live

        original_dispatch_live_actions = strategy._dispatch_live_actions

        def traced_dispatch_live_actions(actions, batch):
            result = original_dispatch_live_actions(actions, batch)
            api = api_instances[-1] if api_instances else None
            if api is not None and api._phase == 1:
                risk_dispatch_trace.append(
                    {
                        "kind": "dispatch_live_actions_returned",
                        "actions": tuple(
                            (
                                getattr(action, "action", None),
                                getattr(action, "instrument", None),
                                getattr(action, "side", None),
                                getattr(action, "position_effect", None),
                                getattr(action, "quantity", None),
                                getattr(action, "offset", None),
                            )
                            for action in actions
                        ),
                        "orders": tuple(
                            (
                                ref,
                                getattr(order, "status", None),
                                getattr(getattr(order, "data", None), "_name", None),
                                getattr(order, "size", None),
                                getattr(getattr(order, "info", None), "factor_intent_id", None),
                            )
                            for ref, order in getattr(strategy, "_orders_by_broker_ref", {}).items()
                        )[-8:],
                        "store_writes": len(store_write_calls),
                        "native_calls": len(api.native_calls),
                    }
                )
                if len(risk_dispatch_trace) > 32:
                    del risk_dispatch_trace[:-32]
            return result

        strategy._dispatch_live_actions = traced_dispatch_live_actions

        store = getattr(getattr(strategy, "broker", None), "store", None)
        original_poll_tick = getattr(store, "poll_tick", None)
        if callable(original_poll_tick):

            def traced_store_poll_tick(dataname):
                tick = original_poll_tick(dataname)
                api = api_instances[-1] if api_instances else None
                if tick is not None and api is not None and api._phase == 1:
                    observation = {
                        "sequence": len(chain_trace),
                        "kind": "store_poll_tick_returned",
                        "instrument": dataname,
                        "event_id": getattr(tick, "event_id", None),
                        "event_time": getattr(tick, "event_time", None),
                        "received_wall_time": getattr(tick, "received_wall_time", None),
                        "source": getattr(tick, "source", None),
                        "query_set_id": api._winddown_query_set_for.get(dataname),
                        "source_clock": clock.utc_now().isoformat(),
                    }
                    store_tick_trace.append(observation)
                    chain_trace.append(observation)
                    if len(store_tick_trace) > 128:
                        del store_tick_trace[:-128]
                    if len(chain_trace) > 128:
                        del chain_trace[:-128]
                return tick

            store.poll_tick = traced_store_poll_tick

    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "bind_strategy", capture_bound_strategy)

    original_refresh = RUNNER.QueryRefreshLoop.refresh_once

    def counted_refresh(loop):
        # The test fake provider advances its event clock during each typed
        # query. Keep the entire refresh transaction, including publication
        # and its bounded trace record, indivisible from Strategy clock reads.
        with fact_turn_lock:
            with refresh_condition:
                refresh_state["started"] += 1
                started = refresh_state["started"]
                refresh_condition.notify_all()
            refresh_started_at = clock.utc_now()
            try:
                receipt = original_refresh(loop)
                refresh_receipts.append(
                    {
                        "attempt": started,
                        "started_at": refresh_started_at.isoformat(),
                        "completed_at": clock.utc_now().isoformat(),
                        "error_code": getattr(loop, "last_error_code", None),
                        "query_set_id": getattr(
                            getattr(receipt, "query_set", None), "query_set_id", None
                        ),
                        "requested_families": getattr(receipt, "requested_families", None),
                        "attempted_families": getattr(receipt, "attempted_families", None),
                        "pending_families": getattr(receipt, "pending_families", None),
                        "cancelled": getattr(receipt, "cancelled", None),
                        "deadline_reached": getattr(receipt, "deadline_reached", None),
                        "blockers": getattr(receipt, "blockers", None),
                        "provenance": tuple(
                            (
                                getattr(item, "family", None),
                                getattr(item, "target_id", None),
                                getattr(item, "query_complete", None),
                                getattr(item, "source_owned", None),
                                getattr(item, "scope_complete", None),
                                getattr(item, "request_id", None),
                                getattr(item, "completed_at", None),
                            )
                            for item in getattr(receipt, "query_provenance", ())
                        ),
                    }
                )
                return receipt
            except Exception as exc:
                with refresh_condition:
                    refresh_state["errors"].append(
                        (
                            clock.utc_now().isoformat(),
                            type(exc).__name__,
                            getattr(exc, "code", None),
                            str(exc)[:512],
                        )
                    )
                note_fill_event(
                    "refresh_failed",
                    exception_type=type(exc).__name__,
                    code=getattr(exc, "code", None),
                    message=str(exc)[:512],
                )
                raise
            finally:
                with refresh_condition:
                    refresh_state["completed"] = max(refresh_state["completed"], started)
                    refresh_condition.notify_all()

    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "refresh_once", counted_refresh)
    # Journal timestamps are a test clock leaf, aligned with the typed query
    # source and the same virtual event clock. Production code remains intact.
    monkeypatch.setattr(
        journal_module,
        "time",
        SimpleNamespace(time_ns=clock.time_ns, monotonic=time.monotonic),
    )

    config["live"].update(
        account_scope="alpha003-factor-chain-account",
        strategy_scope="alpha003-factor-chain",
        logical_run_id="alpha003-factor-chain-run",
        journal_path=str(tmp_path / "factor-chain.sqlite"),
        ready_timeout_seconds=1.0,
        refresh_timeout_seconds=1.0,
        refresh_overall_timeout_seconds=5.0,
        refresh_interval_seconds=0.01,
        quote_max_age_seconds=60.0,
        query_max_age_seconds=7200.0,
        shutdown_grace_seconds=5.0,
        allow_writes=True,
        arm_templates=[
            {
                "target": target,
                "md_front": "tcp://127.0.0.1:1",
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "alpha003-factor-chain-" + target,
                "preflight_sha256": "b" * 64,
            }
            for target in plan["authorized_targets"]
        ],
    )
    config["risk"]["run_end_policy"] = "CLOSE_ALL"
    config["cohort"].update(
        max_pending_slots=1,
        max_live_bar_age_seconds=30.0,
        max_future_skew_seconds=0.0,
    )
    config["output"]["decision_tape_path"] = str(tmp_path / "factor-chain-tape.jsonl")
    config["output"]["decision_tape_max_bytes"] = 50_000_000
    config_path.write_text(
        runner_fixtures.yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    try:
        result = RUNNER.run_live(
            config,
            config_path,
            plan,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=True,
        )
    except Exception as exc:
        persist_diagnostic("known_cancel_run_exception", error=exc)
        observations = tuple(item for api in api_instances for item in api.tick_observations[-9:])
        cleanup = getattr(exc, "cleanup_results", None)
        failure = getattr(exc, "live_epoch_evidence", None)
        resources = getattr(exc, "retained_live_resources", {})
        resource_names = tuple(resources) if hasattr(resources, "__iter__") else ()
        refresh_loop = resources.get("refresh_loop") if hasattr(resources, "get") else None
        broker = resources.get("broker") if hasattr(resources, "get") else None
        store = resources.get("store") if hasattr(resources, "get") else None
        try:
            broker_shutdown = broker.get_shutdown_summary() if broker is not None else None
        except Exception as summary_error:
            broker_shutdown = type(summary_error).__name__
        try:
            store_health = store.get_command_health() if store is not None else None
        except Exception as health_error:
            store_health = type(health_error).__name__
        strategy = (
            getattr(refresh_loop, "_strategy", None)
            if refresh_loop is not None
            else (captured_strategies[-1] if captured_strategies else None)
        )
        strategy_events = tuple(dict(event) for event in getattr(strategy, "order_events", ()))[
            -12:
        ]
        fact = getattr(strategy, "last_execution_facts", None)
        fact_summary = (
            None
            if fact is None
            else {
                "blockers": getattr(fact, "blockers", None),
                "risk_reduction_blockers": getattr(fact, "risk_reduction_blockers", None),
                "order_cancel_blockers": getattr(fact, "order_cancel_blockers", None),
                "query_set_id": getattr(fact, "query_set_id", None),
            }
        )
        native_calls = tuple(call for api in api_instances for call in api.native_calls)
        raise AssertionError(
            f"actual Cerebro chain failed: {exc}; ticks={observations!r}; "
            f"native_calls={native_calls!r}; resources={resource_names!r}; "
            f"store_write_calls={tuple(store_write_calls)!r}; "
            f"broker_rejections={tuple(broker_rejections)!r}; "
            f"refresh_errors={tuple(refresh_state['errors'])!r}; "
            f"refresh_receipts={tuple(refresh_receipts[-8:])!r}; "
            f"refresh_counts={(refresh_state['started'], refresh_state['completed'])!r}; "
            f"terminal_reconciliation={tuple(reconciliation_observations[-8:])!r}; "
            f"provider_terminal_rows={tuple(query_rows['orders_result'])!r}; "
            f"broker_shutdown={broker_shutdown!r}; store_health={store_health!r}; "
            f"strategy_block_reason={getattr(strategy, 'last_execution_block_reason', None)!r}; "
            f"strategy_events={strategy_events!r}; facts={fact_summary!r}; "
            f"cleanup={cleanup!r}; live_failure={failure!r}"
        ) from exc

    persist_diagnostic("known_cancel_run_returned", result_value={"phase1": result})
    assert len(api_instances) == 1
    cancel_api = api_instances[0]
    assert cancel_api.closed is True
    inserts = [call for call in cancel_api.native_calls if call[0] == "insert"]
    cancels = [call for call in cancel_api.native_calls if call[0] == "cancel"]
    assert inserts, (
        result,
        tuple(store_write_calls),
        tuple(broker_rejections),
        tuple(refresh_receipts[-8:]),
        tuple(
            (
                getattr(strategy, "last_execution_block_reason", None),
                getattr(getattr(strategy, "last_order_plan", None), "status", None),
                getattr(getattr(strategy, "last_order_plan", None), "reason", None),
                getattr(strategy, "last_execution_facts", None),
            )
            for strategy in captured_strategies[-1:]
        ),
        str(diagnostic_path),
    )
    assert cancels, result
    assert all(call[2] == "DCE" for call in inserts + cancels)
    assert result["write_mode"] is True
    assert result["shutdown_status"] == "PASS"
    events = result["strategy_order_events"]["events"]
    assert any(event["status"] == "ACCEPTED" for event in events), events
    assert any(event["status"] == "CANCELED" for event in events), events
    assert result["cleanup_complete"] is True

    # Start a second source-backed run on fresh journal/query state.  Its
    # factor OPEN receives one full CTP fill through the ordinary callback
    # queue, and the strategy then sends its configured run-end CLOSE_ALL.
    query_rows.clear()
    query_rows.update(make_query_rows())
    bars_by_instrument.clear()
    refill_bars()
    clock.reset(event_times)
    # The first run also exercises a fast refresh cadence while bars arrive.
    # During the second run, allow one bounded quote-only maintenance turn to
    # consume every target's real post-query tick before the next full query
    # set supersedes that snapshot. Query age and quote freshness gates remain
    # unchanged; only the fake run's refresh schedule is realistic for this
    # three-feed provider cadence.
    config["live"]["refresh_interval_seconds"] = 0.25
    config["live"].update(
        logical_run_id="alpha003-factor-chain-fill-close-run",
        journal_path=str(tmp_path / "factor-chain-fill-close.sqlite"),
    )
    config["output"]["decision_tape_path"] = str(tmp_path / "factor-chain-fill-close-tape.jsonl")
    config_path.write_text(
        runner_fixtures.yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    try:
        fill_close_result = RUNNER.run_live(
            config,
            config_path,
            plan,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=True,
        )
    except Exception as exc:
        persist_diagnostic("fill_close_run_exception", result_value={"phase1": result}, error=exc)
        resources = getattr(exc, "retained_live_resources", {})
        refresh_loop = resources.get("refresh_loop") if hasattr(resources, "get") else None
        live_failure = getattr(exc, "live_epoch_evidence", None)
        live_failure_summary = (
            None
            if not isinstance(live_failure, dict)
            else {
                key: live_failure.get(key)
                for key in (
                    "engine_winddown_status",
                    "engine_winddown_reason",
                    "strategy_shutdown_requested",
                    "strategy_shutdown_ready",
                    "strategy_shutdown_blocker",
                    "strategy_shutdown_post_join_confirmed",
                    "strategy_shutdown_post_join_blocker",
                    "refresh_status",
                    "refresh_blocker",
                    "refresh_error_code",
                    "reconciliation_blockers",
                    "strategy_order_events",
                )
            }
        )
        strategy = (
            getattr(refresh_loop, "_strategy", None)
            if refresh_loop is not None
            else (captured_strategies[-1] if captured_strategies else None)
        )
        broker = resources.get("broker") if hasattr(resources, "get") else None
        broker_positions = []
        if broker is not None and strategy is not None:
            for data in tuple(getattr(strategy, "datas", ())):
                try:
                    position = broker.execution_position_snapshot(data)
                    broker_positions.append(
                        (getattr(data, "_name", None), position, broker.getposition(data).size)
                    )
                except Exception as snapshot_error:
                    broker_positions.append(
                        (getattr(data, "_name", None), type(snapshot_error).__name__)
                    )
        fact = getattr(strategy, "last_execution_facts", None)
        native_calls = tuple(call for api in api_instances for call in api.native_calls)
        first_bad_reconciliation = next(
            (
                observation
                for observation in reconciliation_observations
                if any(
                    item[1] not in {"RESOLVED", "DUPLICATE", "EXTERNAL_TERMINAL_FLAT"}
                    for item in observation["items"]
                )
            ),
            None,
        )
        callback_index = next(
            (
                index
                for index, event in enumerate(fill_timeline)
                if event["kind"] == "callback_emitted"
            ),
            0,
        )
        fill_timing_window = tuple(fill_timeline[callback_index : callback_index + 28])
        terminal_tail = tuple(
            (
                observation["query_set_id"],
                observation["available_at"],
                tuple((item[1], item[2]) for item in observation["items"]),
            )
            for observation in reconciliation_observations[-8:]
        )
        refresh_tail = tuple(
            (
                receipt["attempt"],
                receipt["error_code"],
                receipt["query_set_id"],
                receipt["blockers"],
            )
            for receipt in refresh_receipts[-8:]
        )
        strategy_state = (
            None
            if strategy is None
            else (
                getattr(strategy, "shutdown_requested", None),
                getattr(strategy, "shutdown_ready", None),
                getattr(strategy, "shutdown_blocker", None),
                getattr(strategy, "last_execution_block_reason", None),
            )
        )
        plan = getattr(strategy, "last_order_plan", None)
        plan_summary = (
            None
            if plan is None
            else {
                "status": getattr(plan, "status", None),
                "reason": getattr(plan, "reason", None),
                "actions": tuple(
                    (
                        getattr(action, "action", None),
                        getattr(action, "target_id", None),
                        getattr(action, "instrument", None),
                        getattr(action, "side", None),
                        getattr(action, "position_effect", None),
                        getattr(action, "quantity", None),
                        getattr(action, "offset", None),
                        getattr(action, "reason", None),
                    )
                    for action in getattr(plan, "actions", ())
                ),
                "decision_available_at": getattr(plan, "decision_available_at", None),
                "decision_batch_id": getattr(plan, "decision_batch_id", None),
            }
        )
        fact_summary = (
            None
            if fact is None
            else {
                "blockers": getattr(fact, "blockers", None),
                "risk_reduction_blockers": getattr(fact, "risk_reduction_blockers", None),
                "order_cancel_blockers": getattr(fact, "order_cancel_blockers", None),
                "risk_reduction_ready": getattr(fact, "risk_reduction_ready", None),
                "open_risk_ready": getattr(fact, "open_risk_ready", None),
                "snapshot_id": getattr(fact, "snapshot_id", None),
                "query_set_id": getattr(fact, "query_set_id", None),
                "available_at": getattr(fact, "available_at", None),
                "account": getattr(fact, "account", None),
                "positions": tuple(
                    (
                        getattr(position, "target_id", None),
                        getattr(position, "instrument", None),
                        getattr(position, "quantity", None),
                        getattr(position, "owner_strategy_scope", None),
                        getattr(position, "owner_intent_id", None),
                        getattr(position, "average_price", None),
                        getattr(position, "stop_price", None),
                        getattr(position, "held_eligible_bars", None),
                        getattr(position, "position_book_status", None),
                        getattr(position, "position_book_blocker_code", None),
                    )
                    for position in getattr(fact, "positions", ())
                ),
                "quotes": tuple(
                    (
                        getattr(quote, "instrument", None),
                        getattr(quote, "bid", None),
                        getattr(quote, "ask", None),
                        getattr(quote, "event_time", None),
                        getattr(quote, "available_at", None),
                        getattr(quote, "quality", None),
                    )
                    for quote in getattr(fact, "quotes", ())
                ),
                "working_orders": tuple(
                    (
                        getattr(order, "instrument", None),
                        getattr(order, "state", None),
                        getattr(order, "position_effect", None),
                        getattr(order, "owner_intent_id", None),
                        getattr(order, "remaining_quantity", None),
                    )
                    for order in getattr(fact, "working_orders", ())
                ),
            }
        )
        query_completion_trace = tuple(
            (
                receipt["attempt"],
                receipt["query_set_id"],
                max((item[-1] for item in receipt["provenance"]), default=None),
            )
            for receipt in refresh_receipts[-8:]
        )
        tick_trace_summary = tuple(
            (
                item["sequence"],
                item["instrument"],
                item["query_set_id"],
                item["event_time"],
                item["received_wall_time"],
                item["source_clock"],
            )
            for item in store_tick_trace[-12:]
        )
        store_write_summary = tuple(
            (
                call.get("operation"),
                ((call.get("identity") or {}).get("info") or {}).get("instrument_id"),
                ((call.get("identity") or {}).get("info") or {}).get("exchange_id"),
                (call.get("identity") or {}).get("size"),
                ((call.get("identity") or {}).get("info") or {}).get("factor_position_effect"),
                ((call.get("identity") or {}).get("info") or {}).get("factor_intent_id"),
                ((call.get("identity") or {}).get("info") or {}).get("offset"),
                call.get("result"),
            )
            for call in store_write_calls[-12:]
        )
        idle_trace_summary = tuple(
            (
                item["sequence"],
                item["now"],
                item["query_set_id"],
                item["facts_available_at"],
                item["risk_reduction_ready"],
                item["risk_reduction_blockers"],
                item["positions"],
                item["quotes"],
                item["plan"],
                item["shutdown"],
            )
            for item in idle_decision_trace[-12:]
        )
        raise AssertionError(
            f"factor-driven OPEN/fill/CLOSE run failed: {exc}; "
            f"native_calls={native_calls!r}; "
            f"store_writes={store_write_summary!r}; "
            f"risk_scopes={tuple(risk_scope_trace[-8:])!r}; "
            f"risk_dispatch={tuple(risk_dispatch_trace[-8:])!r}; "
            f"broker_rejections={tuple(broker_rejections[-8:])!r}; "
            f"refresh_errors={tuple(refresh_state['errors'][:4])!r}; "
            f"refresh_tail={refresh_tail!r}; "
            f"fill_timing_window={fill_timing_window!r}; "
            f"query_completion_trace={query_completion_trace!r}; "
            f"terminal_tail={terminal_tail!r}; "
            f"first_bad_terminal_reconciliation={first_bad_reconciliation!r}; "
            f"broker_updates={tuple(broker_update_observations[-8:])!r}; "
            f"strategy_state={strategy_state!r}; "
            f"strategy_plan={plan_summary!r}; strategy_fact={fact_summary!r}; "
            f"live_failure={live_failure_summary!r}; "
            f"quote_only_tail={tuple(api_instances[-1].winddown_tick_observations[-9:])!r}; "
            f"store_tick_trace={tick_trace_summary!r}; "
            f"idle_decision_trace={idle_trace_summary!r}; "
            f"last_execution_block_reason={getattr(strategy, 'last_execution_block_reason', None)!r}; "
            f"remaining_source_bars={tuple((key, len(value)) for key, value in api_instances[-1]._source_bars.items())!r}; "
            f"winddown_poll_attempts={api_instances[-1].winddown_poll_attempts}; "
            f"winddown_poll_blockers={tuple(api_instances[-1].winddown_poll_blockers[-8:])!r}"
        ) from exc

    persist_diagnostic(
        "fill_close_run_returned",
        result_value={"phase1": result, "phase2": fill_close_result},
    )
    assert len(api_instances) == 2
    fill_close_api = api_instances[1]
    assert fill_close_api.closed is True
    submissions = [call for call in store_write_calls if call["operation"] == "submit"]
    assert any(
        call["identity"]["info"].get("factor_position_effect") == "OPEN" for call in submissions
    ), submissions
    assert any(
        call["identity"]["info"].get("factor_position_effect") == "CLOSE" for call in submissions
    ), (
        "ordinary Alpha003 produced no factor CLOSE; "
        f"submissions={tuple((call['identity']['data_name'], call['identity']['size'], call['identity']['info'].get('factor_position_effect'), call['identity']['info'].get('factor_intent_id'), call['identity']['info'].get('factor_reason'), call['identity']['info'].get('offset')) for call in submissions)!r}; "
        f"native_calls={tuple(fill_close_api.native_calls)!r}; "
        f"strategy_events={fill_close_result['strategy_order_events']!r}; "
        f"reconciliation={tuple(reconciliation_observations[-12:])!r}; "
        f"broker_updates={tuple(broker_update_observations[-12:])!r}; "
        f"fill_timeline={tuple(fill_timeline)!r}; "
        f"provider_positions={tuple(query_rows['positions_result'])!r}; "
        f"provider_trades={tuple(query_rows['trades_result'])!r}; "
        f"shutdown={(fill_close_result['shutdown_status'], fill_close_result['strategy_shutdown_blocker'], fill_close_result['strategy_shutdown_post_join_blocker'])!r}"
    )
    filled_open_instruments = {
        str(row.get("InstrumentID"))
        for row in query_rows["trades_result"]
        if str(row.get("OffsetFlag")) == "0"
    }
    assert filled_open_instruments, query_rows["trades_result"]
    assert any(
        call[0] == "insert" and call[1] in filled_open_instruments
        for call in fill_close_api.native_calls
    ), (fill_close_api.native_calls, filled_open_instruments)
    assert any(call[0] == "cancel" for call in fill_close_api.native_calls)
    assert fill_close_result["write_mode"] is True
    assert fill_close_result["shutdown_status"] == "PASS"
    fill_close_events = fill_close_result["strategy_order_events"]["events"]
    assert any(event["status"] == "COMPLETED" for event in fill_close_events), fill_close_events
    assert any(event["status"] == "CANCELED" for event in fill_close_events), fill_close_events
    assert fill_close_result["cleanup_complete"] is True

    shutdown = {item["resource"]: item for item in fill_close_result["resource_shutdown"]}
    assert shutdown["query_refresh"]["joined"] is True, shutdown
    assert shutdown["query_refresh"]["status"] == "RETURNED", shutdown
    assert shutdown["broker"]["status"] == "PASS", shutdown
    assert shutdown["broker"]["store_shutdown_state"] == "PASS", shutdown
    assert shutdown["store"]["status"] == "CLOSED_BY_BROKER", shutdown
    assert shutdown["store"]["shutdown_state"] == "PASS", shutdown
    assert shutdown["journal"]["status"] == "CLOSED", shutdown
    assert shutdown["decision_tape"]["status"] == "CLOSED", shutdown
    assert fill_close_result["decision_tape"]["closed"] is True
    assert fill_close_result["decision_tape"]["failed"] is False
    assert fill_close_result["decision_tape_readback"]["record_count"] == (
        fill_close_result["decision_tape"]["record_count"]
    )

    close_submissions = [
        call
        for call in submissions
        if call["identity"]["info"].get("factor_position_effect") == "CLOSE"
    ]
    assert len(close_submissions) == 1, close_submissions
    close_identity = close_submissions[0]["identity"]
    close_intent_id = close_identity["info"].get("factor_intent_id")
    assert isinstance(close_intent_id, str) and close_intent_id
    close_trades = [
        row
        for row in query_rows["trades_result"]
        if str(row.get("InstrumentID")) == str(close_identity["info"].get("instrument_id"))
        and str(row.get("OffsetFlag")) == "1"
    ]
    assert len(close_trades) == 1, close_trades
    close_trade = close_trades[0]

    # Reopen the exact run journal only after Runner reports it CLOSED.  The
    # archive verifier and the read-only SQL below bind the provider callback,
    # native OrderRef, complete-query terminal observation, flat position
    # snapshot, and durable intent resolution for this actual Strategy CLOSE.
    from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
    from backtrader.stores.execution_journal_archive import (
        verify_execution_journal_archive,
    )

    journal_path = tmp_path / "factor-chain-fill-close.sqlite"
    archive_path = tmp_path / "factor-chain-fill-close-archive.sqlite3"
    archive_writer = ExecutionDecisionJournal(journal_path)
    try:
        archive_receipt = archive_writer.archive_snapshot(archive_path)
    finally:
        archive_writer.close()
    assert (
        verify_execution_journal_archive(
            archive_path,
            expected_schema_version=ExecutionDecisionJournal._SCHEMA_VERSION,
            expected_sha256=archive_receipt.sha256,
        )
        == archive_receipt
    )
    with closing(sqlite3.connect(archive_path.as_uri() + "?mode=ro", uri=True)) as archived:
        archived.execute("PRAGMA query_only = ON")
        terminal_chain = archived.execute(
            """SELECT n.order_ref,n.instrument,n.exchange,n.trading_day,
                      c.callback_id,c.acknowledged,c.evidence_payload_json,
                      r.query_id,r.state,r.terminal_state,r.terminal_event_id,
                      r.position_snapshot_id,r.position_flat,
                      z.terminal_state,z.terminal_event_id,z.reconciliation_id,
                      z.position_snapshot_id,z.position_flat
               FROM execution_decision_intents AS i
               JOIN execution_native_intent_identities AS n ON n.intent_id=i.intent_id
               JOIN execution_decision_callbacks AS c ON c.intent_id=i.intent_id
               JOIN execution_intent_reconciliations AS r ON r.intent_id=i.intent_id
               JOIN execution_intent_resolutions AS z ON z.intent_id=i.intent_id
               WHERE i.intent_id=?
               ORDER BY r.created_at_ns DESC LIMIT 1""",
            (close_intent_id,),
        ).fetchone()
    assert terminal_chain is not None, close_intent_id
    (
        native_order_ref,
        native_instrument,
        native_exchange,
        native_trading_day,
        callback_id,
        callback_acknowledged,
        callback_payload_json,
        query_id,
        reconciliation_state,
        terminal_state,
        terminal_event_id,
        position_snapshot_id,
        position_flat,
        resolution_state,
        resolution_event_id,
        resolution_id,
        resolution_snapshot_id,
        resolution_flat,
    ) = terminal_chain
    callback_payload = json.loads(callback_payload_json)
    assert native_order_ref == str(close_trade["OrderRef"]), terminal_chain
    assert native_instrument == str(close_trade["InstrumentID"]), terminal_chain
    assert native_exchange == str(close_trade["ExchangeID"]), terminal_chain
    assert native_trading_day == str(close_trade["TradingDay"]), terminal_chain
    assert callback_id and callback_acknowledged == 1, terminal_chain
    assert callback_payload["provider_trade_id"] == str(close_trade["TradeID"]), (
        callback_payload,
        close_trade,
    )
    assert query_id == terminal_event_id
    assert reconciliation_state == "KNOWN"
    assert terminal_state == resolution_state == "FILLED"
    assert resolution_event_id == terminal_event_id
    assert resolution_id
    assert position_snapshot_id == resolution_snapshot_id
    assert position_flat == resolution_flat == 1
    assert any(
        call[0] == "insert"
        and call[1] == native_instrument
        and call[2] == native_exchange
        and call[3] == native_order_ref
        for call in fill_close_api.native_calls
    ), (fill_close_api.native_calls, terminal_chain)
    persist_diagnostic(
        "complete",
        result_value={"phase1": result, "phase2": fill_close_result},
        archive_evidence={
            "path": str(archive_path),
            "sha256": archive_receipt.sha256,
            "size_bytes": archive_receipt.size_bytes,
            "table_row_counts": dict(archive_receipt.table_row_counts),
            "verified": True,
            "terminal_chain": terminal_chain,
            "provider_trade_id": close_trade.get("TradeID"),
        },
    )
