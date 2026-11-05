import os

import pytest
import yaml

from backtrader.live_state import (
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateNotInitialized,
    PositionSnapshotStore,
)

from ._helpers import ACCOUNT_HASH, OTHER_HASH, live_snapshot, temp_files


def test_write_read_round_trip(state):
    store = state.snapshot
    written = store.write(live_snapshot(state.strategy_uuid))
    assert written["version"] == 2
    assert store.path.endswith(os.path.join("logs", "current_position.yaml"))
    read = store.read()
    assert read == written
    assert read["positions"]["rb2601"]["net"] == 2
    assert temp_files(os.path.dirname(store.path)) == []


def test_read_missing_returns_none_but_live_read_fails_closed(state):
    assert state.snapshot.read() is None
    with pytest.raises(LiveStateNotInitialized):
        state.snapshot.read_for_live(ACCOUNT_HASH, "CTP___FUTURE")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["positions"]["rb2601"].update(net=1),
        lambda s: s["positions"]["rb2601"]["long"].update(today=2),
        lambda s: s["positions"]["rb2601"]["long"].update(total=float("nan")),
        lambda s: s["positions"]["rb2601"]["long"].update(total=-0.5),
        lambda s: s["positions"]["rb2601"]["long"].update(total=True),
        lambda s: s["positions"]["rb2601"]["short"].update(total=-1),
        lambda s: s.update(mode="paper"),
        lambda s: s.update(account_hash="123456"),
        lambda s: s.update(account_hash=None),
        lambda s: s.update(trading_day="2026-11-05"),
        lambda s: s.update(version=3),
        lambda s: s.update(extra_key=1),
    ],
)
def test_write_rejects_invalid_snapshots(state, mutate):
    snapshot = live_snapshot(state.strategy_uuid)
    mutate(snapshot)
    with pytest.raises(LiveStateError) as info:
        state.snapshot.write(snapshot)
    assert info.value.code == "snapshot_invalid"
    assert not os.path.exists(state.snapshot.path)


def test_backtest_snapshot_may_omit_account(state):
    snapshot = live_snapshot(
        state.strategy_uuid, mode="backtest", account_hash=None, exchange_name=None
    )
    assert state.snapshot.write(snapshot)["mode"] == "backtest"


def test_unknown_version_on_disk_is_corrupt(state):
    state.snapshot.write(live_snapshot(state.strategy_uuid))
    with open(state.snapshot.path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    data["version"] = 9
    with open(state.snapshot.path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle)
    with pytest.raises(LiveStateCorrupt) as info:
        state.snapshot.read()
    assert info.value.reason == "version_unsupported"


def test_mode_and_account_guard_for_live_reads(state):
    store = state.snapshot
    store.write(live_snapshot(state.strategy_uuid))
    assert store.read_for_live(ACCOUNT_HASH, "CTP___FUTURE", strategy_uuid=state.strategy_uuid)
    cases = [
        ((OTHER_HASH, "CTP___FUTURE"), {}, "snapshot_account_mismatch"),
        ((ACCOUNT_HASH, "OKX___SWAP"), {}, "snapshot_exchange_mismatch"),
        (
            (ACCOUNT_HASH, "CTP___FUTURE"),
            {"strategy_uuid": "1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b"},
            "snapshot_strategy_mismatch",
        ),
    ]
    for args, kwargs, code in cases:
        with pytest.raises(LiveStateIdentityMismatch) as info:
            store.read_for_live(*args, **kwargs)
        assert info.value.code == code


def test_backtest_snapshot_is_never_used_for_live(state):
    store = state.snapshot
    store.write(live_snapshot(state.strategy_uuid, mode="backtest"))
    with pytest.raises(LiveStateIdentityMismatch) as info:
        store.read_for_live(ACCOUNT_HASH, "CTP___FUTURE")
    assert info.value.code == "snapshot_mode_mismatch"


def test_backtest_cannot_clobber_live_snapshot_without_explicit_replace(state):
    store = state.snapshot
    store.write(live_snapshot(state.strategy_uuid))
    backtest = live_snapshot(state.strategy_uuid, mode="backtest")
    with pytest.raises(LiveStateIdentityMismatch) as info:
        store.write(backtest)
    assert info.value.code == "snapshot_foreign"
    assert store.read()["mode"] == "live"
    store.write(backtest, replace_foreign=True)
    assert store.read()["mode"] == "backtest"
    backups = [
        name
        for name in os.listdir(os.path.dirname(store.path))
        if name.startswith("current_position.yaml.replaced-")
    ]
    assert len(backups) == 1
    with open(os.path.join(os.path.dirname(store.path), backups[0]), encoding="utf-8") as handle:
        assert yaml.safe_load(handle)["mode"] == "live"


LEGACY = """\
datetime: '2026-11-04 14:59:00'
strategy: SaDualMa
positions:
  rb2601:
    size: 2.0
    price: 3500.0
    value: 70000.0
    current_price: 3500.0
  hc2601:
    size: -1
    price: 3300.0
"""


def test_legacy_trade_logger_snapshot(state):
    os.makedirs(os.path.dirname(state.snapshot.path), exist_ok=True)
    with open(state.snapshot.path, "w", encoding="utf-8") as handle:
        handle.write(LEGACY)
    with pytest.raises(LiveStateCorrupt) as info:
        state.snapshot.read()
    assert info.value.reason == "legacy_format"
    legacy = state.snapshot.read_legacy()
    assert legacy.legacy is True
    assert dict(legacy) == {"rb2601": 2, "hc2601": -1}
    assert type(legacy["rb2601"]) is int
    assert legacy.strategy == "SaDualMa"
    with pytest.raises(LiveStateCorrupt):
        state.snapshot.read_for_live(ACCOUNT_HASH, "CTP___FUTURE")


def test_read_legacy_rejects_v2_file(state):
    state.snapshot.write(live_snapshot(state.strategy_uuid))
    with pytest.raises(LiveStateError) as info:
        state.snapshot.read_legacy()
    assert info.value.code == "snapshot_not_legacy"


def test_garbage_snapshot_is_corrupt(state):
    os.makedirs(os.path.dirname(state.snapshot.path), exist_ok=True)
    with open(state.snapshot.path, "w", encoding="utf-8") as handle:
        handle.write("positions: [unclosed")
    with pytest.raises(LiveStateCorrupt):
        state.snapshot.read()


def test_snapshot_store_needs_no_identity(tmp_path):
    store = PositionSnapshotStore(tmp_path)
    assert store.read() is None


def test_write_does_not_create_missing_strategy_dir(tmp_path):
    missing = tmp_path / "typo"
    store = PositionSnapshotStore(missing)
    snapshot = live_snapshot("1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b")
    with pytest.raises(LiveStateError) as info:
        store.write(snapshot)
    assert info.value.code == "strategy_dir_missing"
    assert not missing.exists()


def test_fractional_venue_quantities_round_trip(state):
    """Crypto venues hold fractional quantities (e.g. 0.002 BTC); never rounded away."""
    snapshot = live_snapshot(state.strategy_uuid)
    snapshot["positions"] = {
        "BTCUSDT": {
            "long": {"total": 0.002, "today": None, "yesterday": None},
            "short": {"total": 0, "today": None, "yesterday": None},
            "net": 0.002,
        }
    }
    state.snapshot.write(snapshot)
    loaded = state.snapshot.read()
    assert loaded["positions"]["BTCUSDT"]["long"]["total"] == 0.002
    assert loaded["positions"]["BTCUSDT"]["net"] == 0.002
