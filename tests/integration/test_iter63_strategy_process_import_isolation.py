"""INV63-12 on the strategy side: a backtrader strategy process loads no Risk or Execution package.

Risk and Execution are separate services. A strategy process that trades through a
Gateway (Cerebro, BtApiStore, BtApiBroker and its feed) never imports ``bt_api_risk`` or
``bt_api_execution``, and without a selected monitor it does not import
``bt_api_monitor`` either. The plan asks for an observation over the whole life of an
isolated process: the strategy process of an existing scenario, and the Gateway process
it talks to, each report at their end which of the watched packages they hold.

Synthetic Gateway with a real Registry and journal over CURVE on loopback; no venue.
"""

import functools
import importlib
import importlib.util
import multiprocessing
import os
import queue
import sys

from tests.integration import test_iter63_gateway_lease_blocked_cerebro as scenario
from tests.integration.test_iter63_gateway_lease_blocked_cerebro import (
    _blocked_cerebro_client as _run_strategy,
)
from tests.integration.test_iter63_gateway_lease_blocked_cerebro import (
    _short_lease_gateway as _run_gateway,
)

WATCHED = ("bt_api_execution", "bt_api_monitor", "bt_api_risk")


def _loaded():
    return sorted({name.split(".")[0] for name in sys.modules} & set(WATCHED))


def _observed_strategy(reports, *args):
    try:
        _run_strategy(*args)
    finally:
        reports.put(("strategy", os.getpid(), _loaded()))


def _observed_gateway(reports, *args):
    try:
        _run_gateway(*args)
    finally:
        reports.put(("gateway", os.getpid(), _loaded()))


def _control_process(reports):
    # Shows that the observation sees a load: this process imports every watched
    # package that can be imported here and reports the same way.
    for name in WATCHED:
        if importlib.util.find_spec(name) is not None:
            importlib.import_module(name)
    reports.put(("control", os.getpid(), _loaded()))


def test_cerebro_strategy_process_loads_no_risk_execution_or_monitor(tmp_path, monkeypatch):
    ctx = multiprocessing.get_context("spawn")
    reports = ctx.Queue()
    monkeypatch.setattr(
        scenario, "_blocked_cerebro_client", functools.partial(_observed_strategy, reports)
    )
    monkeypatch.setattr(
        scenario, "_short_lease_gateway", functools.partial(_observed_gateway, reports)
    )
    # A Cerebro strategy process registers with the Gateway, runs, blocks in next() for
    # several lease periods while its lease is renewed, and ends; then the Gateway stops.
    scenario.test_blocked_cerebro_strategy_keeps_its_gateway_lease(tmp_path, True)
    seen = []
    while True:
        try:
            seen.append(reports.get(timeout=2))
        except queue.Empty:
            break
    assert sorted(role for role, _, _ in seen) == ["gateway", "strategy"], seen
    assert os.getpid() not in {pid for _, pid, _ in seen}
    assert all(loaded == [] for _, _, loaded in seen), seen


def test_the_observation_reports_a_loaded_package():
    ctx = multiprocessing.get_context("spawn")
    reports = ctx.Queue()
    child = ctx.Process(target=_control_process, args=(reports,))
    child.start()
    try:
        role, pid, loaded = reports.get(timeout=30)
    finally:
        child.join(15)
    importable = sorted(name for name in WATCHED if importlib.util.find_spec(name) is not None)
    assert role == "control" and pid == child.pid and child.exitcode == 0
    assert loaded == importable
    # Without at least one importable watched package the first test could not fail.
    assert importable, "none of the watched packages is installed here"
