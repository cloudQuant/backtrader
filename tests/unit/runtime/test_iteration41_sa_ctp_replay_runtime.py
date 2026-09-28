"""Iteration 41 acceptance for the 013_3 and 014_2 replay-only wrappers.

The tests prove invalid runtime contracts fail before a strategy/provider import,
and real fixture runs have no network or provider writes.  They do not admit
SimNow, CTP accounts, or managed execution.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest
import yaml

from backtrader_runtime import (
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
    validate_runtime_config,
)

REPO = Path(__file__).resolve().parents[3]
CASES = (
    {
        "name": "013_3",
        "directory": "013_3_sa_midfreq_simnow",
        "module": "examples.013_3_sa_midfreq_simnow.run_runtime",
        "strategy_id": "example.013_3.sa_midfreq_simnow",
        "scenario": "no_signal",
    },
    {
        "name": "014_2",
        "directory": "014_2_ctp_options_midfreq",
        "module": "examples.014_2_ctp_options_midfreq.run_runtime",
        "strategy_id": "example.014_2.ctp_options_midfreq",
        "scenario": "no_edge",
    },
)


@pytest.fixture(params=CASES, ids=lambda value: value["name"])
def case(request):
    return request.param


@pytest.fixture
def runner(case):
    return importlib.import_module(case["module"])


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """Reject DNS, TCP, and UDP operations rather than trusting report fields."""
    attempted = []

    def reject(*args, **kwargs):
        attempted.append((args, kwargs))
        raise AssertionError("Iteration 41 replay must not access the network")

    monkeypatch.setattr(socket, "getaddrinfo", reject)
    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)
    monkeypatch.setattr(socket.socket, "sendto", reject)
    yield
    assert attempted == []


@pytest.fixture
def runtime(tmp_path, case, runner):
    directory = tmp_path / "runtime"
    directory.mkdir()
    source = REPO / "examples" / case["directory"] / "runtime" / "config.example.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    registry = RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=directory,
                strategy_id=runner.STRATEGY_ID,
                allowed_presets=("replay",),
                allowed_parameter_keys=("scenario",),
            ),
        )
    )
    return directory, raw, registry


def _write_config(directory, raw):
    (directory / "config.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")


def _run_sealed(runner, directory, registry):
    """Invoke an example runner only with a loader-issued effective config."""

    effective = validate_runtime_config(directory, registry)
    return runner.run_runtime(directory, registry=registry, effective=effective)


def _forbid_strategy_import(monkeypatch, runner):
    def reject():
        pytest.fail("Rejected configuration must not load a strategy, Store, or adapter")

    monkeypatch.setattr(runner, "_load_replay_runner", reject)


def test_config_example_exposes_only_the_replay_scenario(case):
    source = REPO / "examples" / case["directory"] / "runtime" / "config.example.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))

    assert set(raw) == {"config_schema_version", "strategy", "runtime", "parameters"}
    assert raw["config_schema_version"] == 4
    assert raw["strategy"] == {"id": case["strategy_id"]}
    assert raw["runtime"] == {"mode": "simulation", "preset": "replay"}
    assert set(raw["parameters"]) == {"scenario"}


def test_missing_runtime_config_rejects_before_strategy_load(runner, runtime, monkeypatch):
    directory, _, registry = runtime
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == "CONFIG_REQUIRED"
    assert failure.value.reason == "missing_config"


@pytest.mark.parametrize(
    "mode,preset,expected_code",
    (
        ("live", "managed_live_direct", "PRESET_POLICY_VIOLATION"),
        ("backtest", "local_backtest", "PRESET_POLICY_VIOLATION"),
        ("live", "replay", "MODE_PRESET_MISMATCH"),
    ),
)
def test_illegal_mode_rejects_before_strategy_load(
    runner, runtime, monkeypatch, mode, preset, expected_code
):
    directory, raw, registry = runtime
    raw["runtime"] = {"mode": mode, "preset": preset}
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == expected_code


@pytest.mark.parametrize("scenario", ("simnow", "", True, ["no_edge"]))
def test_invalid_scenario_rejects_before_strategy_load(runner, runtime, monkeypatch, scenario):
    directory, raw, registry = runtime
    raw["parameters"]["scenario"] = scenario
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == "CONFIG_SCHEMA_UNSUPPORTED"
    assert failure.value.field_path == "parameters.scenario"


def test_secret_reference_rejects_before_strategy_load(runner, runtime, monkeypatch):
    directory, raw, registry = runtime
    raw["secrets_ref"] = "runtime_secrets"
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == "ENVIRONMENT_MISMATCH"
    assert failure.value.field_path == "secrets_ref"


def test_real_replay_has_no_network_or_provider_writes(case, runner, runtime, monkeypatch):
    directory, raw, registry = runtime
    raw["parameters"]["scenario"] = case["scenario"]
    _write_config(directory, raw)

    if case["name"] == "013_3":
        from backtrader.brokers.btapibroker import BtApiBroker
        from backtrader.brokers.bbroker import BackBroker
        from backtrader.stores.btapistore import BtApiStore

        provider_calls = {"constructors": 0, "order_writes": 0, "inherited_matcher": 0}

        def reject_provider_construction(*args, **kwargs):
            provider_calls["constructors"] += 1
            pytest.fail("local replay must not construct a CTP Store or Broker")

        def reject_write(*args, **kwargs):
            provider_calls["order_writes"] += 1
            pytest.fail("local replay must not submit or cancel a provider order")

        def reject_inherited_matcher(*args, **kwargs):
            provider_calls["inherited_matcher"] += 1
            pytest.fail("local replay must not invoke BackBroker's matching engine")

        monkeypatch.setattr(BtApiBroker, "__init__", reject_provider_construction)
        monkeypatch.setattr(BtApiBroker, "submit", reject_write)
        monkeypatch.setattr(BtApiBroker, "cancel", reject_write)
        monkeypatch.setattr(BtApiStore, "__init__", reject_provider_construction)
        monkeypatch.setattr(BtApiStore, "submit_order", reject_write)
        monkeypatch.setattr(BtApiStore, "cancel_order", reject_write)
        monkeypatch.setattr(BackBroker, "next", reject_inherited_matcher)

    report = _run_sealed(runner, directory, registry)

    assert report["status"] == "LOCAL_REPLAY_PASS"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}
    accepted = report["runtime_config"]
    assert accepted["strategy_id"] == case["strategy_id"]
    assert accepted["mode"] == "simulation"
    assert accepted["preset"] == "replay"
    assert accepted["scope"] == "LOCAL_REPLAY_ONLY"
    assert accepted["config_digest"]
    assert accepted["effective_digest"]
    assert not accepted["allows_network"]
    assert not accepted["allows_external_writes"]
    assert not accepted["allows_production_writes"]

    if case["name"] == "013_3":
        assert report["orders"] == []
        assert report["sdk_write_requests"] == 0
        assert provider_calls == {
            "constructors": 0,
            "order_writes": 0,
            "inherited_matcher": 0,
        }
        chain = report["runtime_chain"]
        assert chain["store"].endswith(".LocalReplayStore")
        assert chain["broker"].endswith(".LocalReplayBroker")
        assert chain["feed_provider"] == "local_replay"
        assert "ctp" not in chain["store"].lower()
        assert "ctp" not in chain["broker"].lower()
        assert accepted["research_status"] == "RESEARCH_NOT_ESTABLISHED"
        assert accepted["simnow_admission_boundary"] == "INDEPENDENT_SIMNOW_ADMISSION_REQUIRED"
    else:
        assert report["orders_submitted"] == 0
        assert report["external_network_requests"] == 0
        assert report["external_trade_writes"] == 0
        assert (
            accepted["evidence_boundary"] == "SYNTHETIC_CPF_REPLAY_ONLY_NOT_CTP_OR_SIMNOW_EVIDENCE"
        )


def test_runtime_identity_probe_does_not_import_sdk_parent_package(tmp_path, monkeypatch):
    replay = importlib.import_module("examples.013_3_sa_midfreq_simnow.run")
    package = tmp_path / "bt_api_py"
    package.mkdir()
    marker = tmp_path / "provider-parent-initialized.txt"
    (package / "__init__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('initialized', encoding='utf-8')\n"
        "raise RuntimeError('poisoned provider parent initializer executed')\n",
        encoding="utf-8",
    )
    (package / "bt_api.py").write_text("# inert fake facade\n", encoding="utf-8")
    (package / "_execution_session.py").write_text(
        "# inert fake session module\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    for name in tuple(sys.modules):
        if name == "bt_api_py" or name.startswith("bt_api_py."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    identities = replay.runtime_component_identities()

    assert identities["bt_api_py"]["found"]
    assert identities["bt_api_py_facade"]["found"]
    assert identities["bt_api_py_execution_session"]["found"]
    assert not marker.exists()
    assert "bt_api_py" not in sys.modules


def test_0133_local_replay_composition_has_no_provider_or_order_entry(monkeypatch):
    replay = importlib.import_module("examples.013_3_sa_midfreq_simnow.run")
    from backtrader.brokers.bbroker import BackBroker

    def reject_inherited_matcher(*args, **kwargs):
        pytest.fail("local replay must not invoke BackBroker's matching engine")

    monkeypatch.setattr(BackBroker, "next", reject_inherited_matcher)

    client = replay.ReplayClient((), replay.ReplayClock(0.0), eof_event_time_watermark=1.0)
    store = replay.LocalReplayStore(client, contract_metadata={})
    assert not hasattr(store, "provider")
    assert not hasattr(store, "submit_order")
    assert not hasattr(store, "cancel_order")
    with pytest.raises(replay.RunnerConfigurationError, match="explicit ReplayClient"):
        replay.LocalReplayStore(object(), contract_metadata={})

    broker = replay.LocalReplayBroker(cash=1000.0)
    assert broker.next() is None
    forbidden = (
        lambda: broker.submit(object()),
        lambda: broker.cancel(object()),
        lambda: broker.transmit(object()),
        lambda: broker.submit_accept(object()),
        lambda: broker.add_order_history([]),
        lambda: broker.buy(owner=object(), data=object(), size=1),
        lambda: broker.sell(owner=object(), data=object(), size=1),
    )
    for operation in forbidden:
        with pytest.raises(replay.RunnerConfigurationError):
            operation()
    assert broker.orders == []
    assert list(broker.pending) == []
    assert list(broker.submitted) == []
    broker.pending.append(object())
    with pytest.raises(replay.RunnerConfigurationError, match="no order fill path"):
        broker.next()
    broker.pending.clear()


def _copied_wrapper(tmp_path, case):
    """Copy only the public runtime shell, never the legacy provider fixture."""
    source = REPO / "examples" / case["directory"]
    copied = tmp_path / case["directory"]
    copied.mkdir()
    shutil.copy2(source / "run_runtime.py", copied / "run_runtime.py")
    runtime = copied / "runtime"
    runtime.mkdir()
    shutil.copy2(source / "runtime" / "config.example.yaml", runtime / "config.yaml")
    return copied


def _run_copied_cli(example):
    """Exercise direct-script rejection in a fresh interpreter with I/O guards."""
    program = """
import importlib.abc
import runpy
import socket
import sys
from pathlib import Path

def reject(*args, **kwargs):
    raise AssertionError('copied replay wrapper attempted network access')

socket.getaddrinfo = reject
socket.create_connection = reject
socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.socket.sendto = reject

class RejectFramework(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'backtrader', 'bt_api_py'}:
            raise AssertionError('rejected copied wrapper imported framework/provider code')

sys.meta_path.insert(0, RejectFramework())
sys.argv = sys.argv[1:]
sys.path.insert(0, str(Path(sys.argv[0]).resolve().parent))
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO)
    return subprocess.run(
        [sys.executable, "-c", program, str(example / "run_runtime.py")],
        cwd=example.parent,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_copied_directory_is_rejected_before_framework_or_provider_import(case, tmp_path):
    copied = _copied_wrapper(tmp_path, case)
    result = _run_copied_cli(copied)

    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "REJECTED"
    assert report["error"]["error_code"] == "PRESET_POLICY_VIOLATION"
    assert report["error"]["reason"] == "runtime_not_registered"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


@pytest.mark.parametrize("case", (CASES[0],), ids=lambda value: value["name"])
def test_sa_replay_refuses_an_admitted_legacy_fixture(case, runner, runtime, monkeypatch):
    """The replay shell cannot inherit a later SimNow research admission."""
    directory, raw, registry = runtime
    _write_config(directory, raw)

    class Legacy:
        class RunnerConfigurationError(RuntimeError):
            pass

        DEFAULT_CONFIG = Path("legacy-config.yaml")

        @staticmethod
        def load_config(_path):
            return {"research": {"status": "RESEARCH_ADMITTED"}}, Path("legacy-config.yaml")

    monkeypatch.setattr(runner, "_load_replay_runner", lambda: Legacy)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "replay_research_status_not_established"


@pytest.mark.parametrize("case", (CASES[1],), ids=lambda value: value["name"])
def test_cpf_replay_refuses_a_non_replay_legacy_fixture(case, runner, runtime, monkeypatch):
    """The wrapper must never promote an old engineering fixture into replay."""
    directory, raw, registry = runtime
    _write_config(directory, raw)

    class Legacy:
        class ConfigurationError(RuntimeError):
            pass

        EXAMPLE_DIR = Path("legacy-example")

        @staticmethod
        def load_config(_path):
            return {"mode": "engineering_observation"}

    monkeypatch.setattr(runner, "_load_replay_runner", lambda: Legacy)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "replay_fixture_mode_not_bound"
