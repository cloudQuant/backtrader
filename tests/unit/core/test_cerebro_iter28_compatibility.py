"""Public Cerebro contracts that a private-mixin refactor must preserve."""

import inspect
import json
import os
from pathlib import Path
import pickle
import re
import signal
import subprocess
import sys

import pytest

import backtrader as bt
import backtrader.cerebro as cerebro_module
from backtrader.parameters import ParameterDescriptor, ParameterizedBase

REPO = Path(__file__).resolve().parents[3]
EVIDENCE = REPO / "docs/_internal/opts/requirements/迭代28-Cerebro模块化拆分/evidence"


class RestoredStrategy(bt.Strategy):
    """A real completed strategy whose allocation requires an active owner."""

    construction_count = 0

    def __init__(self):
        type(self).construction_count += 1


class CustomReducedStrategy(RestoredStrategy):
    def __reduce__(self):
        return (str, ("custom strategy reduction",))


def _isolated_python(args, *, env=None, timeout=90):
    """Use the active test interpreter, with bounded cleanup of spawned workers."""
    proc = subprocess.Popen(
        [sys.executable, *args],
        cwd=REPO,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            if proc.poll() is None:
                proc.kill()
        stdout, stderr = proc.communicate()
        pytest.fail(f"isolated Cerebro probe timed out: {stdout}\n{stderr}")
    assert proc.returncode == 0, f"{stdout}\n{stderr}"
    return stdout


def test_public_api_signatures_and_descriptors_match_frozen_presplit_baseline():
    baseline = json.loads((EVIDENCE / "m0/exports-default.json").read_text())
    for name, expected in baseline["cerebro_api"].items():
        if expected["kind"] not in {
            "function",
            "staticmethod",
            "classmethod",
            "property",
            "ParameterDescriptor",
        }:
            continue  # Lazy parameter caches may already be populated by another test.
        actual = inspect.getattr_static(bt.Cerebro, name)
        assert type(actual).__name__ == expected["kind"], name
        if "signature" in expected:
            fn = actual.__func__ if isinstance(actual, (staticmethod, classmethod)) else actual
            assert str(inspect.signature(fn)) == expected["signature"], name
    actual_descriptors = {
        name: {
            "default": repr(value.default),
            "type": getattr(value.type_, "__name__", None),
            "doc": value.doc,
        }
        for name, value in vars(bt.Cerebro).items()
        if isinstance(value, ParameterDescriptor)
    }
    assert len(actual_descriptors) == 19
    assert actual_descriptors == baseline["descriptors"]
    assert bt.Cerebro.broker.fget is bt.Cerebro.getbroker
    assert bt.Cerebro.broker.fset is bt.Cerebro.setbroker
    assert inspect.signature(inspect.unwrap(bt.Cerebro.run)) == inspect.signature(bt.Cerebro.run)
    assert bt.Cerebro.__mro__[-2:] == (ParameterizedBase, object)


@pytest.mark.parametrize("mode", ["default", "light"])
def test_fresh_import_exports_and_type_identity_match_presplit_baseline(mode):
    env = os.environ.copy()
    env.pop("BACKTRADER_LIGHT_IMPORT", None)
    if mode == "light":
        env["BACKTRADER_LIGHT_IMPORT"] = "1"
    report = json.loads(_isolated_python(["-m", "scripts.iter28_m0_exports", mode], env=env))
    baseline = json.loads((EVIDENCE / f"m0/exports-{mode}.json").read_text())
    assert report["cerebro_star"] == baseline["cerebro_star"]
    for name, value in baseline["identity"].items():
        if name != "cerebro_file":
            assert report["identity"][name] == value, name
    assert Path(report["identity"]["cerebro_file"]).resolve() == REPO / "backtrader/cerebro.py"


def test_descriptor_and_legacy_subclasses_keep_parameter_caches_and_instances_isolated():
    class Modern(bt.Cerebro):
        preload = ParameterDescriptor(default=False, type_=bool)
        audit_count = ParameterDescriptor(default=3, type_=int, validator=lambda value: value > 0)

    class Legacy(Modern):
        params = (("audit_count", 8), ("oldsync", True))

    class Sibling(bt.Cerebro):
        pass

    parent = bt.Cerebro()
    modern = Modern(audit_count=5)
    legacy = Legacy(audit_count=9)
    sibling = Sibling()
    assert modern.p is modern.params
    assert legacy.p is legacy.params
    assert modern.p.audit_count == 5
    assert legacy.p.audit_count == 9
    assert not modern.p.preload and not legacy.p.preload
    assert legacy.p.oldsync and not modern.p.oldsync
    assert parent.p.preload and sibling.p.preload
    modern.p.audit_count = 6
    assert legacy.p.audit_count == 9
    assert Modern().p.audit_count == 3
    assert Legacy().p.audit_count == 8
    caches = [cls._compute_parameter_descriptors() for cls in (bt.Cerebro, Modern, Legacy, Sibling)]
    assert len({id(cache) for cache in caches}) == 4
    assert "audit_count" not in caches[0] and "audit_count" not in caches[3]
    with pytest.raises(ValueError):
        modern.audit_count = 0
    modern.adddata(bt.feeds.BacktraderCSVData(dataname=str(REPO / "tests/datas/2006-day-001.txt")))
    modern.run(audit_count=7, oldsync=True)
    assert modern.p.audit_count == 7 and modern.p.oldsync


def test_broker_property_preserves_bound_accessors_and_subclass_super():
    class Child(bt.Cerebro):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.events = []

        def getbroker(self):
            return "overridden accessor"

        def adddata(self, data, name=None):
            self.events.append(name)
            return super().adddata(data, name=name)

    engine = Child(preload=False)
    assert engine.getbroker() == "overridden accessor"
    assert engine.broker is engine._broker
    broker = bt.brokers.BackBroker()
    engine.broker = broker
    assert engine.broker is broker and broker.cerebro is engine
    data = bt.feeds.BacktraderCSVData(dataname=str(REPO / "tests/datas/2006-day-001.txt"))
    assert engine.adddata(data, name="audit") is data
    assert engine.events == ["audit"] and data._env is engine


def test_pickle_recreates_inactive_scope_and_accepts_old_state_without_logging_config():
    engine = bt.Cerebro(stdstats=False)
    original_event, original_lock = engine._event_stop, engine._runstop_lock
    state = engine.__getstate__()
    assert "_event_stop" not in state and "_runstop_lock" not in state
    state.pop("_logging_config", None)
    state_before = state.copy()
    restored = bt.Cerebro.__new__(bt.Cerebro)
    restored.__setstate__(state)
    assert state == state_before
    assert restored._event_stop is not original_event
    assert restored._runstop_lock is not original_lock
    assert not restored._event_stop and not restored._run_active
    assert restored._external_channel_token is None
    assert restored.p is restored.params
    assert type(pickle.loads(pickle.dumps(engine))) is cerebro_module.Cerebro


def test_real_spawn_matches_serial_for_full_strategy_and_optreturn_results():
    result = json.loads(_isolated_python(["-m", "scripts.iter28_spawn_probe"], timeout=150))
    assert result["start_method"] == "spawn"
    assert len(result["checks"]) == 4
    assert all(check["callbacks"] == [2, 4, 6] for check in result["checks"])


def test_real_spawn_inherits_split_logging_without_duplicate_worker_records(tmp_path):
    result = json.loads(
        _isolated_python(
            ["-m", "scripts.iter28_spawn_probe", "--log-dir", str(tmp_path)], timeout=150
        )
    )
    text = "\n".join(path.read_text() for path in tmp_path.rglob("warning*.log"))
    emitted = re.findall(r"spawn-contract pid=(\d+) period=(\d+)", text)
    for check in result["checks"]:
        for row, pid in zip(check["rows"], check["pids"]):
            assert pid != result["parent_pid"]
            assert emitted.count((str(pid), str(row["period"]))) == 1


@pytest.mark.parametrize("protocol", [0, pickle.HIGHEST_PROTOCOL])
def test_strategy_unpickle_restores_state_without_running_constructor(protocol):
    engine = bt.Cerebro(stdstats=False)
    engine.adddata(bt.feeds.BacktraderCSVData(dataname=str(REPO / "tests/datas/2006-day-001.txt")))
    engine.addstrategy(RestoredStrategy)
    strategy = engine.run()[0]
    previous_count = RestoredStrategy.construction_count
    restored = pickle.loads(pickle.dumps(strategy, protocol=protocol))
    assert type(restored) is RestoredStrategy
    assert RestoredStrategy.construction_count == previous_count
    assert restored._id == strategy._id
    assert len(restored.data) == len(strategy.data) > 0
    assert restored.broker.getvalue() == strategy.broker.getvalue()


def test_strategy_pickle_honors_user_defined_reducer():
    instance = object.__new__(CustomReducedStrategy)
    assert pickle.loads(pickle.dumps(instance)) == "custom strategy reduction"


@pytest.mark.parametrize("oldsync", [False, True])
@pytest.mark.parametrize("runonce", [False, True])
def test_all_strategies_skipped_returns_empty_and_retires_scope(oldsync, runonce):
    class Skipped(bt.Strategy):
        def __init__(self):
            raise bt.errors.StrategySkipError

    engine = bt.Cerebro(oldsync=oldsync, runonce=runonce, stdstats=False)
    engine.adddata(bt.feeds.BacktraderCSVData(dataname=str(REPO / "tests/datas/2006-day-001.txt")))
    engine.addstrategy(Skipped)
    assert engine.run() == []
    assert not engine._run_active and not engine._event_stop
