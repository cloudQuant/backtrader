"""Offline CTP synthetic-session and locally-bound-command collision experiment.

The existing fake native session never connects; both orders are synthetic
journal reservations with locally persisted session identity keys. They do not
pass RPC ACL, market/risk admission, or provide provider/venue authority. No
claim is made that a real account or exchange permits these opposite fills.
"""

import importlib.util
import json
from pathlib import Path
import sys

import backtrader
import bt_api_base
import bt_api_ctp
import bt_api_gateway
import bt_api_py
import pytest
from bt_api_base.direct_write_protocol import DirectExecutionEventKind, NativeOrderIdentity
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_execution_journal import GatewayDirectExecutionLedger
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py.ctp_gateway_return_ingestion import CtpGatewayReturnIngestor
from bt_api_py.direct_write import project_direct_strong_identity_keys

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    for module in (backtrader, bt_api_base, bt_api_ctp, bt_api_gateway, bt_api_py):
        assert Path(module.__file__).resolve().is_relative_to(ROOT), module.__file__
    yield
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(ROOT):
                escaped[name] = source
    assert not escaped, f"non-worktree modules: {escaped}"


def fixtures():
    """Load the SDK fixture by exact path, avoiding the two tests/ namespaces."""
    path = ROOT / "bt_api_py/tests/integration/test_iter63_ctp_gateway_return_ingestion.py"
    assert path.is_file() and path.resolve().is_relative_to(ROOT)
    spec = importlib.util.spec_from_file_location("iter65_ctp_offline_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(journal, fixture, label, ref, side):
    """Locally register a synthetic command; no ACL or order admission is tested."""
    strategy, key, principal = "strategy-" + label, "key-" + label, "principal-" + label
    row = journal.reserve(strategy, key, principal,
        {"symbol": "rb2701", "side": side, "offset": "open", "quantity": "2"})
    identity = NativeOrderIdentity("CTP___FUTURE", ref,
        {"trading_day": fixture.DAY, "order_ref": ref, "front_id": 7, "session_id": 19}, None)
    keys = project_direct_strong_identity_keys(identity, day_scoped_ids=True)
    wire = {"exchange_name": "CTP___FUTURE", "client_order_id": ref,
        "fields_json": json.dumps(dict(identity.fields), sort_keys=True, separators=(",", ":")),
        "session_generation": None}
    journal.begin_dispatch(strategy, key, row.reservation_id, row.digest, principal, row.version, wire, keys)
    return row


@pytest.mark.parametrize("same_sys", [False, True], ids=["distinct_orders", "same_order_sys_id"])
@pytest.mark.parametrize("reverse", [False, True], ids=["buy_first", "sell_first"])
def test_locally_bound_two_order_collision_and_replay(tmp_path, same_sys, reverse):
    f = fixtures()
    reader, _client, native = f._reader()
    (tmp_path / "guard").mkdir()
    guard = LocalAccountSessionGuard(tmp_path / "guard", f.ACCOUNT, "synthetic-owner")
    generation = guard.acquire()
    try:
        path = tmp_path / "journal.sqlite"
        journal = GatewayDirectCommandJournal.create(path, f.ACCOUNT, generation=generation)
        ledger = GatewayDirectExecutionLedger(journal, guard)
        ingestor = CtpGatewayReturnIngestor(reader, ledger, account_key=f.ACCOUNT_KEY,
                                             instruments=(f.INSTRUMENT,))
        refs = {"a": "000000000001", "b": "000000000002"}
        systems = {"a": "synthetic-sys-a", "b": "synthetic-sys-a" if same_sys else "synthetic-sys-b"}
        for label, side in (("a", "buy"), ("b", "sell")):
            command(journal, f, label, refs[label], side)
        with journal._transaction() as db:
            assert db.execute("SELECT count(DISTINCT reservation_id) FROM direct_journal_strong_keys").fetchone()[0] == 2
        labels = ("b", "a") if reverse else ("a", "b")
        directions = {"a": "0", "b": "1"}
        order_summaries = []
        for label in labels:
            native.rows["orders"] = [f._order(OrderRef=refs[label], OrderSysID=systems[label],
                                               Direction=directions[label])]
            order_summaries.append(ingestor.read_and_ingest("orders", timeout=1))
        assert order_summaries[0].attributed_count == 1
        assert order_summaries[1].conflict_count == (1 if same_sys else 0)
        assert order_summaries[1].attributed_count == (0 if same_sys else 1)
        trade_summaries = []
        for label in labels:
            native.rows["trades"] = [f._trade(OrderRef=refs[label], OrderSysID=systems[label],
                                               Direction=directions[label], TradeID="same-synthetic-trade")]
            trade_summaries.append(ingestor.read_and_ingest("trades", timeout=1))
        assert [(s.attributed_count, s.unattributed_count, s.conflict_count) for s in trade_summaries] == [
            (1, 0, 0), (0, 0, 1)
        ]
        with journal._transaction() as db:
            assert [tuple(row) for row in db.execute(
                "SELECT disposition,reason FROM direct_execution_facts ORDER BY rowid"
            )] == [
                ("ATTRIBUTED", "MATCHED"),
                ("CONFLICT", "IDENTITY_CONFLICT") if same_sys else ("ATTRIBUTED", "MATCHED"),
                ("ATTRIBUTED", "MATCHED"), ("CONFLICT", "TRADE_CONTENT_CONFLICT"),
            ]
            revision = journal._assert_anchor(db)
        positions = tuple(ledger.position("strategy-" + label, f.INSTRUMENT) for label in ("a", "b"))
        event_counts = tuple(len(ledger.read_events("strategy-" + label)) for label in ("a", "b"))
        assert positions == ((None, "-1") if reverse else ("1", None))
        assert event_counts == ((0 if same_sys else 1, 2) if reverse else (2, 0 if same_sys else 1))
        (trade_event,) = [event for event in ledger.read_events("strategy-" + labels[0])
                          if event.fact.kind is DirectExecutionEventKind.TRADE]
        assert trade_event.fact.trade_key == (f.DAY, "SHFE", "rb2701", "same-synthetic-trade")
        assert trade_event.fact.side == ("sell" if reverse else "buy")
        reopened = GatewayDirectCommandJournal(path, f.ACCOUNT, generation=journal.generation,
            expected_journal_id=journal.journal_id, minimum_revision=revision)
        reloaded = GatewayDirectExecutionLedger(reopened, guard)
        assert tuple(reloaded.position("strategy-" + label, f.INSTRUMENT) for label in ("a", "b")) == positions
        assert tuple(len(reloaded.read_events("strategy-" + label)) for label in ("a", "b")) == event_counts
        # Re-read each synthetic fact; this is not a repeat of a real account call.
        for label in labels:
            native.rows["trades"] = [f._trade(OrderRef=refs[label], OrderSysID=systems[label],
                                               Direction=directions[label], TradeID="same-synthetic-trade")]
            replay = ingestor.read_and_ingest("trades", timeout=1)
            assert (replay.attributed_count, replay.unattributed_count, replay.conflict_count) == (0, 0, 1)
        assert tuple(ledger.position("strategy-" + label, f.INSTRUMENT) for label in ("a", "b")) == positions
        assert tuple(len(ledger.read_events("strategy-" + label)) for label in ("a", "b")) == event_counts
    finally:
        guard.release()


def test_distinct_order_and_trade_ids_can_apply_both_synthetic_strategies(tmp_path):
    """Control: separate synthetic venue order/trade IDs reach each local book."""
    f = fixtures()
    reader, _client, native = f._reader()
    (tmp_path / "guard").mkdir()
    guard = LocalAccountSessionGuard(tmp_path / "guard", f.ACCOUNT, "synthetic-owner")
    generation = guard.acquire()
    try:
        journal = GatewayDirectCommandJournal.create(tmp_path / "journal.sqlite", f.ACCOUNT,
                                                      generation=generation)
        ledger = GatewayDirectExecutionLedger(journal, guard)
        ingestor = CtpGatewayReturnIngestor(reader, ledger, account_key=f.ACCOUNT_KEY,
                                             instruments=(f.INSTRUMENT,))
        for label, ref, side, direction in (("a", "000000000001", "buy", "0"),
                                            ("b", "000000000002", "sell", "1")):
            command(journal, f, label, ref, side)
            native.rows["orders"] = [f._order(OrderRef=ref, OrderSysID="synthetic-sys-" + label,
                                               Direction=direction)]
            assert ingestor.read_and_ingest("orders", timeout=1).attributed_count == 1
            native.rows["trades"] = [f._trade(OrderRef=ref, OrderSysID="synthetic-sys-" + label,
                                               Direction=direction, TradeID="synthetic-trade-" + label)]
            assert ingestor.read_and_ingest("trades", timeout=1).attributed_count == 1
        assert (ledger.position("strategy-a", f.INSTRUMENT),
                ledger.position("strategy-b", f.INSTRUMENT)) == ("1", "-1")
        assert (len(ledger.read_events("strategy-a")), len(ledger.read_events("strategy-b"))) == (2, 2)
    finally:
        guard.release()
