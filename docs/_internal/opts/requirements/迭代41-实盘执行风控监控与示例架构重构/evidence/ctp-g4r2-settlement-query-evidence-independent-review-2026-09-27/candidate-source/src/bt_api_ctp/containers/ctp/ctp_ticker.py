from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from bt_api_base.containers.tickers.ticker import TickerData
from bt_api_base.functions.utils import (
    from_dict_get_float,
    from_dict_get_int,
    from_dict_get_string,
)


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return result if result >= 0 else 0


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number > 0 else None


class CtpTickerData(TickerData):
    def __init__(
        self,
        ticker_info,
        symbol_name=None,
        asset_type="UNKNOWN",
        has_been_json_encoded=False,
        connection_generation=0,
        ingest_seq=0,
        recv_time_utc=None,
        recv_monotonic_ns=None,
        subscription_epoch=0,
        rules_hash="",
        clock_domain_id="",
        source="ctp.native.md",
        source_clock_quality="unknown",
        receive_clock_quality="unknown",
        source_clock_error_ms=None,
        receive_clock_error_ms=None,
        freshness_verified=False,
        product_class=None,
        contract_type=None,
        option_type=None,
        underlying_instrument=None,
        strike_price=None,
    ):
        super().__init__(ticker_info, has_been_json_encoded)
        self.symbol_name = symbol_name
        self.asset_type = asset_type
        self.exchange_name = "CTP"
        self._initialized = False
        self._data_initialized = False
        self.instrument_id = None
        self.last_price_val = None
        self.pre_settlement_price = None
        self.open_price_val = None
        self.highest_price = None
        self.lowest_price = None
        self.bid_price_1 = None
        self.bid_volume_1 = None
        self.ask_price_1 = None
        self.ask_volume_1 = None
        self.volume_val = None
        self.turnover = None
        self.open_interest = None
        self.upper_limit_price = None
        self.lower_limit_price = None
        self.update_time_val = None
        self.update_millisec = None
        self.trading_day = None
        self.exchange_id = None
        self.action_day = None
        self.connection_generation = _nonnegative_int(connection_generation)
        self.ingest_seq = _nonnegative_int(ingest_seq)
        self.subscription_epoch = _nonnegative_int(subscription_epoch)
        self.rules_hash = str(rules_hash or "")
        self.clock_domain_id = str(clock_domain_id or "")
        self.source = str(source or "unknown")
        self.source_clock_quality = str(source_clock_quality or "unknown").strip().lower()
        self.receive_clock_quality = str(receive_clock_quality or "unknown").strip().lower()
        self.source_clock_error_ms = source_clock_error_ms
        self.receive_clock_error_ms = receive_clock_error_ms
        # A source must explicitly attest freshness.  CTP native fields alone
        # carry no clock-calibration proof, so the default remains false.
        self.freshness_verified = freshness_verified is True
        # Product identity comes from the separately queried CTP instrument
        # reference data.  A depth quote does not prove it, so retain only
        # caller-supplied fields and never infer an option/future relationship
        # from the instrument string.
        self.product_class = _optional_text(product_class)
        self.contract_type = _optional_text(contract_type) or "unknown"
        self.option_type = _optional_text(option_type)
        self.underlying_instrument = _optional_text(underlying_instrument)
        self.strike_price = _positive_finite_number(strike_price)
        if isinstance(recv_time_utc, (int, float)):
            recv_time_utc = datetime.fromtimestamp(float(recv_time_utc), timezone.utc)
        elif isinstance(recv_time_utc, str):
            recv_time_utc = datetime.fromisoformat(recv_time_utc.replace("Z", "+00:00"))
        self.recv_time_utc = recv_time_utc or datetime.now(timezone.utc)
        if self.recv_time_utc.tzinfo is None:
            self.recv_time_utc = self.recv_time_utc.replace(tzinfo=timezone.utc)
        self.recv_monotonic_ns = int(recv_monotonic_ns or time.monotonic_ns())
        self.event_time_utc = None
        self.event_time_source = "unresolved"
        self.schema_version = "ctp.quote.v2"
        self.cum_volume = None
        self.delta_volume = None
        self.volume_semantics = "cumulative"
        self.volume_complete = False
        self.volume_quality = "uninitialized"
        self.continuity_status = "gap"
        # Direct native containers carry no parent-issued transport attestation
        # and must never self-promote an execution decision.
        self.execution_eligible = False
        self.quality_flags = []

    def init_data(self):
        if self._data_initialized:
            return self
        info = self.ticker_info
        if isinstance(info, dict):
            self.instrument_id = from_dict_get_string(info, "InstrumentID")
            self.last_price_val = from_dict_get_float(info, "LastPrice")
            self.pre_settlement_price = from_dict_get_float(info, "PreSettlementPrice")
            self.open_price_val = from_dict_get_float(info, "OpenPrice")
            self.highest_price = from_dict_get_float(info, "HighestPrice")
            self.lowest_price = from_dict_get_float(info, "LowestPrice")
            self.bid_price_1 = from_dict_get_float(info, "BidPrice1")
            self.bid_volume_1 = from_dict_get_int(info, "BidVolume1", 0)
            self.ask_price_1 = from_dict_get_float(info, "AskPrice1")
            self.ask_volume_1 = from_dict_get_int(info, "AskVolume1", 0)
            self.volume_val = from_dict_get_int(info, "Volume", 0)
            self.turnover = from_dict_get_float(info, "Turnover", 0.0)
            self.open_interest = from_dict_get_float(info, "OpenInterest", 0.0)
            self.upper_limit_price = from_dict_get_float(info, "UpperLimitPrice")
            self.lower_limit_price = from_dict_get_float(info, "LowerLimitPrice")
            self.update_time_val = from_dict_get_string(info, "UpdateTime")
            self.update_millisec = from_dict_get_int(info, "UpdateMillisec", 0)
            self.trading_day = from_dict_get_string(info, "TradingDay")
            self.action_day = from_dict_get_string(info, "ActionDay")
            self.exchange_id = from_dict_get_string(info, "ExchangeID")
            self.cum_volume = self.volume_val
        self._data_initialized = True
        self._initialized = True
        return self

    def get_exchange_name(self):
        self._ensure_init()
        return self.exchange_name or ""

    def get_local_update_time(self):
        self._ensure_init()
        return self.recv_time_utc.timestamp()

    def get_symbol_name(self):
        self._ensure_init()
        return self.instrument_id or self.symbol_name or ""

    def get_ticker_symbol_name(self):
        return self.instrument_id or self.symbol_name or ""

    def get_asset_type(self):
        return self.asset_type or ""

    def get_server_time(self):
        self._ensure_init()
        if self.event_time_utc is None:
            return None
        return self.event_time_utc.timestamp()

    def get_bid_price(self):
        self._ensure_init()
        return self.bid_price_1

    def get_ask_price(self):
        self._ensure_init()
        return self.ask_price_1

    def get_bid_volume(self):
        self._ensure_init()
        return self.bid_volume_1

    def get_ask_volume(self):
        self._ensure_init()
        return self.ask_volume_1

    def get_last_price(self):
        self._ensure_init()
        return self.last_price_val

    def get_last_volume(self):
        self._ensure_init()
        if self.volume_semantics == "delta" and self.delta_volume is not None:
            return self.delta_volume
        return self.volume_val

    def get_cumulative_volume(self):
        self._ensure_init()
        return self.cum_volume

    def get_delta_volume(self):
        self._ensure_init()
        return self.delta_volume

    def apply_volume_delta(self, delta, *, complete, quality):
        """Attach the one authoritative cumulative-to-delta conversion."""
        self._ensure_init()
        self.delta_volume = float(delta or 0.0)
        self.volume_semantics = "delta"
        self.volume_complete = bool(complete)
        self.volume_quality = str(quality)
        self.continuity_status = (
            "continuous"
            if self.volume_complete and self.volume_quality.upper() == "CONTINUOUS"
            else "gap"
        )
        self.execution_eligible = False
        return self

    def resolve_event_time(self):
        """Resolve ActionDay + UpdateTime to UTC or mark receive-time fallback."""
        self._ensure_init()
        event_time = self.recv_time_utc
        day = str(self.action_day or "")
        update_time = str(self.update_time_val or "")
        if len(day) == 8 and day.isdigit() and update_time:
            try:
                local_time = datetime.strptime(f"{day} {update_time}", "%Y%m%d %H:%M:%S").replace(
                    microsecond=int(self.update_millisec or 0) * 1000,
                    tzinfo=timezone(timedelta(hours=8)),
                )
            except (TypeError, ValueError):
                self.quality_flags.append("INVALID_EVENT_TIME")
                self.event_time_source = "receive_fallback"
            else:
                event_time = local_time.astimezone(timezone.utc)
                self.event_time_source = "action_day"
        else:
            self.quality_flags.append("AMBIGUOUS_EVENT_DATE")
            self.event_time_source = "receive_fallback"
        self.event_time_utc = event_time
        return event_time

    def get_open_interest(self):
        return self.open_interest

    def get_upper_limit_price(self):
        return self.upper_limit_price

    def get_lower_limit_price(self):
        return self.lower_limit_price

    def get_all_data(self):
        self._ensure_init()
        return {
            "exchange_name": self.exchange_name,
            "asset_type": self.asset_type,
            "symbol": self.get_symbol_name(),
            "symbol_name": self.symbol_name,
            "instrument_id": self.instrument_id,
            "product_class": self.product_class,
            "contract_type": self.contract_type,
            "option_type": self.option_type,
            "underlying_instrument": self.underlying_instrument,
            "strike_price": self.strike_price,
            "price": self.last_price_val,
            "last_price": self.last_price_val,
            "pre_settlement_price": self.pre_settlement_price,
            "open_price": self.open_price_val,
            "highest_price": self.highest_price,
            "lowest_price": self.lowest_price,
            "bid_price_1": self.bid_price_1,
            "bid_volume_1": self.bid_volume_1,
            "ask_price_1": self.ask_price_1,
            "ask_volume_1": self.ask_volume_1,
            "bid_price": self.bid_price_1,
            "bid_volume": self.bid_volume_1,
            "ask_price": self.ask_price_1,
            "ask_volume": self.ask_volume_1,
            "volume": self.get_last_volume(),
            "cum_volume": self.cum_volume,
            "cumulative_volume": self.cum_volume,
            "delta_volume": self.delta_volume,
            "volume_semantics": self.volume_semantics,
            "volume_complete": self.volume_complete,
            "volume_quality": self.volume_quality,
            "continuity_status": self.continuity_status,
            "turnover": self.turnover,
            "open_interest": self.open_interest,
            "upper_limit_price": self.upper_limit_price,
            "lower_limit_price": self.lower_limit_price,
            "update_time": self.update_time_val,
            "update_millisec": self.update_millisec,
            "trading_day": self.trading_day,
            "action_day": self.action_day,
            "exchange_id": self.exchange_id,
            "event_time_utc": self.event_time_utc,
            "event_time_source": self.event_time_source,
            "recv_time_utc": self.recv_time_utc,
            "recv_monotonic_ns": self.recv_monotonic_ns,
            "connection_generation": self.connection_generation,
            "ingest_seq": self.ingest_seq,
            "subscription_epoch": self.subscription_epoch,
            "rules_hash": self.rules_hash,
            "clock_domain_id": self.clock_domain_id,
            "source": self.source,
            "source_clock_quality": self.source_clock_quality,
            "receive_clock_quality": self.receive_clock_quality,
            "source_clock_error_ms": self.source_clock_error_ms,
            "receive_clock_error_ms": self.receive_clock_error_ms,
            "freshness_verified": self.freshness_verified,
            "schema_version": self.schema_version,
            # Eligibility is a parent-owned admission decision.  This native
            # container can expose evidence, but it cannot serialize a
            # self-issued approval even if a caller mutates the public object.
            "execution_eligible": False,
            "quality_flags": list(self.quality_flags),
        }

    def __str__(self):
        return str(self.get_all_data())

    def __repr__(self):
        return self.__str__()
