"""Snapshot regression for per-symbol today/yesterday split binding.

UNIT: calls the real direct-mode snapshot writer with synthetic position legs.
"""

from types import SimpleNamespace

from backtrader.brokers._btapi_direct_mode import BtApiDirectModeMixin


class _SnapshotRecorder:
    def __init__(self):
        self.payload = None

    def write(self, payload):
        self.payload = payload


class _SnapshotWriter:
    _direct_write_snapshot = BtApiDirectModeMixin._direct_write_snapshot

    def __init__(self):
        self._direct_uuid = "strategy-uuid"
        self._direct_account_hash = "account-hash"
        self._direct_exchange = "TEST"
        self._direct_trading_day = "20261120"
        self._direct_state = SimpleNamespace(
            snapshot=_SnapshotRecorder(),
            sequence=SimpleNamespace(local_seq=7),
        )
        self._direct_applied = {}
        self.long_positions = {
            "A": SimpleNamespace(size=3.25, price=101.5),
            "B": SimpleNamespace(size=4.0, price=202.5),
        }
        self.short_positions = {
            "A": SimpleNamespace(size=0.0, price=0.0),
            "B": SimpleNamespace(size=-1.5, price=203.5),
        }
        self.splits = {
            "A": {
                "today": {"long": 1.25, "short": None},
                "yesterday": {"long": 2.0, "short": None},
            },
            "B": {
                "today": {"long": 3.5, "short": 0.75},
                "yesterday": {"long": 0.5, "short": 0.75},
            },
        }

    def _direct_split_of(self, symbol):
        return self.splits[symbol]


def test_snapshot_binds_each_symbol_to_its_own_position_split():
    writer = _SnapshotWriter()

    writer._direct_write_snapshot()

    positions = writer._direct_state.snapshot.payload["positions"]
    assert positions["A"] == {
        "long": {"total": 3.25, "today": 1.25, "yesterday": 2},
        "short": {"total": 0, "today": None, "yesterday": None},
        "net": 3.25,
    }
    assert positions["B"] == {
        "long": {"total": 4, "today": 3.5, "yesterday": 0.5},
        "short": {"total": 1.5, "today": 0.75, "yesterday": 0.75},
        "net": 2.5,
    }
