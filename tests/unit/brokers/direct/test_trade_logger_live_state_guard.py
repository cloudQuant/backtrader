"""TradeLogger never overwrites a direct-mode live_state snapshot (iteration 62).

UNIT: real ``TradeLogger._save_position_snapshot`` / ``_snapshot_owned_by_live_state``
on a bare logger object; real ``backtrader.live_state`` snapshot files.
"""

import hashlib
from types import SimpleNamespace

import pytest

yaml = pytest.importorskip("yaml")

from backtrader import live_state as ls
from backtrader.observers.trade_logger import TradeLogger

STAMP = "2026-11-05 10:00:00"


def _bare_logger(log_dir):
    logger = object.__new__(TradeLogger)
    logger.p = SimpleNamespace(
        log_dir=str(log_dir), snapshot_file="current_position.yaml", log_to_console=False
    )
    logger._get_datetime_str = lambda: STAMP
    logger._get_strategy_name = lambda: "DirectStrategy"
    logger._iter_position_datas = lambda: []
    return logger


def _live_snapshot(strategy_dir):
    state = ls.StrategyStateDir.initialize(strategy_dir)
    state.snapshot.write(
        {
            "mode": "live",
            "strategy_uuid": state.strategy_uuid,
            "account_hash": hashlib.sha256(b"CTP___FUTURE|acct").hexdigest(),
            "exchange_name": "CTP___FUTURE",
            "trading_day": "20261105",
            "positions": {
                "rb2701": {
                    "long": {"total": 2, "today": 2, "yesterday": 0},
                    "short": {"total": 0, "today": 0, "yesterday": 0},
                    "net": 2,
                }
            },
            "local_seq_high": 3,
            "applied_trades": {"20261105": ["SHFE|T1|buy|1001"]},
            "position_prices": {"rb2701": {"long": 3505.0, "short": 0.0}},
        }
    )
    return state


def test_live_state_snapshot_is_not_overwritten(tmp_path):
    strategy_dir = tmp_path / "strategy"
    strategy_dir.mkdir()
    state = _live_snapshot(strategy_dir)
    path = strategy_dir / "logs" / "current_position.yaml"
    before = path.read_bytes()
    logger = _bare_logger(strategy_dir / "logs")
    logger._save_position_snapshot()
    logger._save_position_snapshot()  # cached decision, still untouched
    assert path.read_bytes() == before
    assert state.snapshot.read()["positions"]["rb2701"]["net"] == 2


def test_legacy_snapshot_is_still_written(tmp_path):
    path = tmp_path / "current_position.yaml"
    path.write_text(
        yaml.safe_dump({"datetime": "old", "strategy": "S", "positions": {"X": {"size": 1}}}),
        encoding="utf-8",
    )
    _bare_logger(tmp_path)._save_position_snapshot()
    written = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert written == {"datetime": STAMP, "strategy": "DirectStrategy", "positions": {}}


def test_missing_snapshot_is_written(tmp_path):
    _bare_logger(tmp_path)._save_position_snapshot()
    written = yaml.safe_load((tmp_path / "current_position.yaml").read_text(encoding="utf-8"))
    assert written["datetime"] == STAMP


def test_backtest_mode_live_state_snapshot_is_also_owned(tmp_path):
    path = tmp_path / "current_position.yaml"
    path.write_text(
        yaml.safe_dump({"version": 2, "mode": "backtest", "strategy_uuid": "u", "positions": {}}),
        encoding="utf-8",
    )
    assert _bare_logger(tmp_path)._snapshot_owned_by_live_state(str(path)) is True


def test_unparseable_live_state_text_is_treated_as_owned(tmp_path):
    path = tmp_path / "current_position.yaml"
    path.write_text("version: 2\nstrategy_uuid: abc\npositions: [unclosed\n", encoding="utf-8")
    before = path.read_bytes()
    _bare_logger(tmp_path)._save_position_snapshot()
    assert path.read_bytes() == before
