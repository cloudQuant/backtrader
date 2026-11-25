"""Regression tests for Iter 73.07: unreadable-position backoff in 007_ctp_gateway strategies.

Ensures tick-driven Gateway strategies do not hammer Gateway with synchronous
``get_strategy_position()`` RPCs on every tick while the Gateway strategy ledger
has no baseline (which stalled tick consumption behind the market replay window
and caused repeated ``RESYNC_REQUIRED``), while remaining strictly fail-closed
(never submitting an order while a symbol's position is unreadable).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

EXAMPLES_007_GATEWAY = (
    Path(__file__).resolve().parents[2] / "examples" / "live" / "007_ctp_gateway"
)

TEN_STRATEGY_FILES = (
    "bbroker_5s_pair_arbitrage_gateway/pair_spread_strategy.py",
    "bbroker_5s_single_symbol_gateway/single_symbol_ma_strategy.py",
    "mixbroker_5s_pair_arbitrage_gateway/pair_spread_strategy.py",
    "mixbroker_5s_single_symbol_gateway/single_symbol_ma_strategy.py",
    "mixbroker_pair_arbitrage_gateway/pair_mix_arbitrage_strategy.py",
    "mixbroker_single_symbol_gateway/single_symbol_mix_strategy.py",
    "tickbroker_5s_pair_arbitrage_gateway/pair_spread_strategy.py",
    "tickbroker_5s_single_symbol_gateway/single_symbol_ma_strategy.py",
    "tickbroker_pair_arbitrage_gateway/pair_tick_arbitrage_strategy.py",
    "tickbroker_single_symbol_gateway/single_symbol_tick_strategy.py",
)


def _load_module(rel_path: str):
    path = EXAMPLES_007_GATEWAY / rel_path
    mod_name = f"_iter73_{path.parent.name}_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_bare_strategy(mod, *, backoff: float = 3.0):
    cls = mod.ConfigurableFuturesStrategyBase
    inst = object.__new__(cls)
    params = SimpleNamespace(
        printlog=False,
        enable_trading=True,
        order_exectype="limit",
        price_tick=1.0,
        slippage_ticks=2,
        reject_backoff_seconds=3.0,
        position_read_backoff_seconds=backoff,
    )
    inst.__dict__["_params_instance"] = params
    inst.__dict__["params"] = params
    inst.__dict__["p"] = params
    inst.pending_refs = set()
    inst.pending_orders = {}
    inst.pending_order_submitted_ticks = {}
    inst.position_cache = {}
    inst.placeholder_data = {}
    inst.signal_count = 0
    inst.completed_roundtrips = 0
    inst.data_status = {}
    inst._last_order_status = {}
    inst.datas = []
    inst.broker = SimpleNamespace()
    return inst


def test_all_ten_007_gateway_strategies_declare_position_read_backoff():
    for rel_path in TEN_STRATEGY_FILES:
        mod = _load_module(rel_path)
        params_dict = dict(mod.BASE_FUTURES_STRATEGY_PARAMS)
        assert params_dict.get("position_read_backoff_seconds") == 3.0, rel_path
        assert callable(getattr(mod.ConfigurableFuturesStrategyBase, "_position_read_backoff", None)), rel_path


@pytest.mark.parametrize(
    "rel_path",
    (
        "mixbroker_pair_arbitrage_gateway/pair_mix_arbitrage_strategy.py",
        "tickbroker_pair_arbitrage_gateway/pair_tick_arbitrage_strategy.py",
        "mixbroker_single_symbol_gateway/single_symbol_mix_strategy.py",
        "tickbroker_single_symbol_gateway/single_symbol_tick_strategy.py",
    ),
)
def test_unreadable_position_backs_off_and_stays_fail_closed_until_recovery(
    rel_path: str, monkeypatch: pytest.MonkeyPatch
):
    mod = _load_module(rel_path)
    now = [100.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])

    strat = _make_bare_strategy(mod, backoff=3.0)
    calls = []
    readable = [False]
    submitted = []

    def fake_get_strategy_position(data):
        calls.append((data.symbol, now[0]))
        if not readable[0]:
            raise RuntimeError("STRATEGY_POSITION_UNAVAILABLE")
        return SimpleNamespace(size=0.0)

    def fake_submit_one(side, symbol, data, quantity, offset, signal_tag):
        submitted.append((side, symbol, quantity, offset, signal_tag))
        return SimpleNamespace(ref=1)

    strat.get_strategy_position = fake_get_strategy_position
    strat._submit_one = fake_submit_one

    # Tick 1 at t=100.0: first position read fails -> marks unreadable + sets 3.0s backoff.
    assert strat._position_size("rb2701") == 0.0
    assert "rb2701" in strat._unreadable_positions()
    assert len(calls) == 1

    # Same tick _submit_market must NOT issue a second RPC and MUST refuse order (fail closed).
    assert strat._submit_market("sell", "rb2701", 1, "open", "test_sig") is None
    assert len(calls) == 1
    assert submitted == []

    # Next 10 ticks within [100.2, 102.9]: zero additional RPCs, still unreadable, zero orders.
    for dt in (0.2, 0.5, 1.0, 1.5, 2.0, 2.5, 2.9):
        now[0] = 100.0 + dt
        assert strat._position_size("rb2701") == 0.0
        assert "rb2701" in strat._unreadable_positions()
        assert strat._submit_market("sell", "rb2701", 1, "open", "test_sig") is None
    assert len(calls) == 1
    assert submitted == []

    # At t=103.0 (backoff expired), still unreadable -> exactly 1 retry, re-arms backoff to 106.0.
    now[0] = 103.0
    assert strat._position_size("rb2701") == 0.0
    assert len(calls) == 2
    assert "rb2701" in strat._unreadable_positions()
    assert strat._submit_market("sell", "rb2701", 1, "open", "test_sig") is None
    assert len(calls) == 2
    assert submitted == []

    # At t=106.0, Gateway ledger recovers -> retry succeeds, clears unreadable & backoff.
    now[0] = 106.0
    readable[0] = True
    assert strat._position_size("rb2701") == 0.0
    assert len(calls) == 3
    assert "rb2701" not in strat._unreadable_positions()
    assert "rb2701" not in strat._position_read_backoff()

    # Now order submission proceeds normally on fresh confirmed position.
    order = strat._submit_market("sell", "rb2701", 1, "open", "test_sig")
    assert order is not None
    assert len(submitted) == 1
