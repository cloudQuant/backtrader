"""Focused contract checks for the installed execution fixture's stream-health leaf."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "iteration50_installed_fixture.py"
)


def _load_fixture():
    spec = importlib.util.spec_from_file_location(
        "iteration50_execution_stream_health_fixture", _FIXTURE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_execution_leaf_health_tracks_generation_and_disconnect():
    fixture = _load_fixture()

    class ExecutionApi(RegisteredSimWrapper, fixture._ExecutionProviderLeaf):
        pass

    api = ExecutionApi(
        registered_sim_allow_writes=True,
        bars={"DCE.M": ()},
        slot_count=1,
    )
    store = RegisteredSimStore(allow_writes=True, api=api, autostart=False)

    class CohortFeed:
        _dataname = "DCE.M"
        live_bar_cohort = object()

        def __init__(self, owner):
            self.store = owner

    store._data_feeds.append(CohortFeed(store))
    api.connect()

    healthy = store.get_stream_health("DCE.M")
    assert healthy["generation_callbacks_supported"] is True
    assert healthy["source_generation"] == 1
    assert healthy["source_revision"] == 0
    assert healthy["source_tick_drop_count"] == 0
    assert healthy["source_tick_drop_reason"] == ""
    assert healthy["stale"] is False

    api.disconnect()
    disconnected = store.get_stream_health("DCE.M")
    assert disconnected["source_revision"] == 1
    assert disconnected["stale"] is True
    assert disconnected["stale_reason"] == "ctp_front_disconnected"
