"""Shared builders for live_state tests (no I/O)."""

import os

ACCOUNT_HASH = "a" * 64
OTHER_HASH = "b" * 64


def place_record(strategy_uuid, **overrides):
    record = {
        "operation": "place",
        "host_scope": strategy_uuid,
        "exchange_name": "CTP___FUTURE",
        "symbol": "rb2601",
        "client_order_id": "000000000001",
        "native_identity": {"front_id": 1, "session_id": 7, "trading_day": "20261105"},
        "request_summary": {"side": "buy", "qty": 1, "price": 3500.0},
        "trading_day": "20261105",
        "session_generation": 3,
        "created_at_utc": "2026-11-05T01:00:00+00:00",
    }
    record.update(overrides)
    return record


def waiting_order(**overrides):
    order = {
        "local_seq": 1,
        "bt_ref": 11,
        "symbol": "rb2601",
        "exchange_name": "CTP___FUTURE",
        "side": "buy",
        "size": 1,
        "exectype": "Limit",
        "price": 3500.0,
        "offset": "close_today",
        "valid_intent": {"kind": "day", "value": None},
        "target_session": {
            "trading_day": "20261106",
            "continuous_start_utc": "2026-11-05T13:00:00+00:00",
            "session_end_utc": "2026-11-05T15:00:00+00:00",
        },
    }
    order.update(overrides)
    return order


def live_snapshot(strategy_uuid, **overrides):
    snapshot = {
        "mode": "live",
        "strategy_uuid": strategy_uuid,
        "account_hash": ACCOUNT_HASH,
        "exchange_name": "CTP___FUTURE",
        "trading_day": "20261105",
        "positions": {
            "rb2601": {
                "long": {"total": 3, "today": 1, "yesterday": 2},
                "short": {"total": 1, "today": None, "yesterday": None},
                "net": 2,
            }
        },
        "local_seq_high": 4,
    }
    snapshot.update(overrides)
    return snapshot


def temp_files(directory):
    return sorted(name for name in os.listdir(directory) if name.endswith(".tmp"))
