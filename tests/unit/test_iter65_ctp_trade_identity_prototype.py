"""CTP trade-key experiment using synthetic input and a local Gateway journal.

CTP's pure projection assumes its caller already checked provenance; these
rows have none. The facts are passed unchanged to an isolated local journal,
without command registration, synthetic source authority or identity binding.
Results therefore describe unowned journal conflict handling, not strategy
attribution, live CTP behavior or any venue's actual TradeID uniqueness.
"""

import sys
from pathlib import Path

import pytest

import backtrader
import bt_api_base
import bt_api_ctp
import bt_api_gateway
import bt_api_py
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_ctp.gateway_return_projection import project_gateway_return
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_execution_journal import GatewayDirectExecutionLedger
from bt_api_gateway.session_guard import LocalAccountSessionGuard

WORKSPACE = Path(__file__).resolve().parents[3]
ACCOUNT = "synthetic-account"
DAY = "20300101"


@pytest.fixture(scope="module", autouse=True)
def check_module_origins():
    required = (backtrader, bt_api_base, bt_api_ctp, bt_api_gateway, bt_api_py)
    for module in required:
        assert Path(module.__file__).resolve().is_relative_to(WORKSPACE), module.__file__
    yield
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(WORKSPACE):
                escaped[name] = source
    assert not escaped, f"non-worktree imports: {escaped}"


@pytest.fixture
def journal(tmp_path):
    guards = tmp_path / "guards"
    guards.mkdir()
    guard = LocalAccountSessionGuard(guards, ACCOUNT, "synthetic-owner")
    generation = guard.acquire()
    store = GatewayDirectCommandJournal.create(tmp_path / "journal.db", ACCOUNT,
        generation=generation, max_records=20, execution_max_facts=20)
    try:
        yield store, GatewayDirectExecutionLedger(store, guard)
    finally:
        guard.release()


def project_trade(*, direction="0", day=DAY, symbol="rb2612", source="synthetic-source",
                  order_sys="synthetic-order"):
    row = {
        "BrokerID": "0999", "InvestorID": "synthetic-investor", "TradingDay": day,
        "ExchangeID": "SHFE", "InstrumentID": symbol, "OrderRef": "1",
        "OrderSysID": order_sys, "TradeID": "synthetic-trade",
        "Direction": direction, "OffsetFlag": "0", "Volume": 2,
        "Price": 123.45, "TradeTime": "09:30:00",
    }
    instrument = MarketInstrumentKey("ctp", "SHFE", "synthetic", "future", symbol, symbol)
    return project_gateway_return("trade", row, account_scope=ACCOUNT, source_ref=source,
        expected_trading_day=day, expected_broker="0999", expected_investor="synthetic-investor",
        instrument=instrument, source_generation=1).fact


@pytest.mark.parametrize("sell_order_sys", ["synthetic-order", "another-synthetic-order"])
def test_opposite_direction_same_key_is_retained_as_conflict_without_attribution(journal, sell_order_sys):
    store, ledger = journal
    buy = project_trade(direction="0")
    sell = project_trade(direction="1", order_sys=sell_order_sys)
    assert (buy.side, sell.side) == ("buy", "sell")
    assert buy.trade_key == sell.trade_key == (DAY, "SHFE", "rb2612", "synthetic-trade")
    assert buy.trade_content_digest() != sell.trade_content_digest()
    assert buy.identity_keys == sell.identity_keys == ()
    first = ledger.ingest(buy)
    assert (first.disposition, first.reason, first.applied) == ("UNATTRIBUTED", "UNMATCHED", False)
    second = ledger.ingest(sell)
    assert (second.disposition, second.reason, second.applied) == ("CONFLICT", "TRADE_CONTENT_CONFLICT", False)
    replay = ledger.ingest(buy)
    assert (replay.disposition, replay.reason, replay.applied) == ("CONFLICT", "TRADE_CONFLICT_RETAINED", False)
    with store._transaction() as db:
        assert db.execute("SELECT count(*) FROM direct_execution_trades").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM direct_execution_conflicts").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM direct_execution_positions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM direct_execution_events").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["next_day", "different_instrument"])
def test_day_or_instrument_changes_key_and_facts_remain_unattributed(journal, change):
    store, ledger = journal
    first = project_trade()
    other = project_trade(day="20300102") if change == "next_day" else project_trade(symbol="hc2612")
    repeat = project_trade(source="another-synthetic-source")
    assert repeat.fact_digest() == first.fact_digest()
    assert first.trade_key != other.trade_key
    assert first.identity_keys == other.identity_keys == ()
    a, b = ledger.ingest(first), ledger.ingest(other)
    assert (a.disposition, a.reason, a.applied) == ("UNATTRIBUTED", "UNMATCHED", False)
    assert (b.disposition, b.reason, b.applied) == ("UNATTRIBUTED", "UNMATCHED", False)
    assert not ledger.ingest(repeat).applied and not ledger.ingest(other).applied
    with store._transaction() as db:
        assert db.execute("SELECT count(*) FROM direct_execution_facts").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM direct_execution_trades").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM direct_execution_conflicts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM direct_execution_positions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM direct_execution_events").fetchone()[0] == 0
