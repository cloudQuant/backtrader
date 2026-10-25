"""Focused contracts for the external Iteration 51 installed-wheel CLI fixture."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
from types import ModuleType, SimpleNamespace
from typing import Optional

import pytest


_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "iteration51_installed_fixture.py"


def _load_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "iteration51_installed_fixture_test", _FIXTURE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_example(path: Path) -> dict[str, bytes]:
    path.mkdir(parents=True)
    payloads = {
        "run.py": b"public runner\n",
        "entry_tier.py": b"public tier helper\n",
        "alpha003_strategy.py": b"public strategy\n",
        "config.yaml": b"schema: backtrader.alpha003.simnow_runner.v1\nmode: dry\n",
    }
    for name, payload in payloads.items():
        (path / name).write_bytes(payload)
    return payloads


def _write_test_selector_source(
    path: Path,
    fixture: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    source = path / "sdk-source" / "ctp_env_selector.py"
    source.parent.mkdir(parents=True)
    payload = b"test-only pinned selector source bytes"
    source.write_bytes(payload)
    monkeypatch.setattr(fixture, "SDK_SELECTOR_SOURCE_SIZE_BYTES", len(payload))
    monkeypatch.setattr(fixture, "SDK_SELECTOR_SOURCE_SHA256", hashlib.sha256(payload).hexdigest())
    return source


def test_copy_public_example_pins_exact_four_files_and_separate_config(
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    workspace.mkdir()
    source = workspace / "source"
    payloads = _write_example(source)
    offline_config = workspace / "research-fixture.yaml"
    offline_config.write_text("mode: research\n", encoding="utf-8")

    copied, config_path, pins = fixture.copy_public_example(
        source,
        workspace / "copy",
        offline_config=offline_config,
    )

    assert config_path == copied / "fixture-config.yaml"
    assert {path.name for path in copied.iterdir()} == set(fixture.PUBLIC_FILES) | {
        "fixture-config.yaml"
    }
    assert set(pins) == set(fixture.PUBLIC_FILES) | {"fixture-config.yaml"}
    for name, payload in payloads.items():
        assert (copied / name).read_bytes() == payload
        assert pins[name]["sha256"] == hashlib.sha256(payload).hexdigest()


def test_copy_public_example_rejects_incomplete_or_reused_destination(tmp_path: Path) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    workspace.mkdir()
    source = workspace / "source"
    source.mkdir()
    for name in fixture.PUBLIC_FILES[:-1]:
        (source / name).write_text("public\n", encoding="utf-8")
    with pytest.raises(fixture.InstalledFixtureError, match="missing or not regular"):
        fixture.copy_public_example(source, workspace / "copy")

    complete_source = workspace / "complete"
    _write_example(complete_source)
    existing = workspace / "existing"
    existing.mkdir()
    with pytest.raises(fixture.InstalledFixtureError, match="must not already exist"):
        fixture.copy_public_example(complete_source, existing)


def test_offline_paths_must_be_staged_and_confined_to_external_workspace(
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    workspace.mkdir()
    example = workspace / "example"
    example.mkdir()
    config_path = example / "fixture-config.yaml"
    config_path.write_text("unused\n", encoding="utf-8")
    bundle = workspace / "bundle.json"
    bundle.write_text("{}\n", encoding="utf-8")
    minute = workspace / "minute.json"
    minute.write_text('{"bars": []}\n', encoding="utf-8")
    output = {
        "directory": "outputs",
        "evaluate_with_fincore": False,
        "decision_tape_path": None,
    }
    selection = {"bundle": "../bundle.json", "daily_bundles": []}
    inputs = {
        "minute_tape": "../minute.json",
        "execution_quotes": None,
        "instrument_metadata": None,
    }

    resolved = fixture._config_paths(
        {"mode": "research", "output": output, "selection": selection, "inputs": inputs},
        config_path,
        workspace,
        "research",
    )
    assert resolved["selection.bundle"] == str(bundle.resolve())
    assert resolved["inputs.minute_tape"] == str(minute.resolve())
    assert fixture._input_evidence(resolved)["inputs.minute_tape"] == {
        "path": str(minute.resolve()),
        "sha256": hashlib.sha256(minute.read_bytes()).hexdigest(),
        "size_bytes": minute.stat().st_size,
    }

    inputs["minute_tape"] = str(Path(tmp_path) / "outside-minute.json")
    with pytest.raises(fixture.InstalledFixtureError, match="inside the external workspace"):
        fixture._config_paths(
            {"mode": "research", "output": output, "selection": selection, "inputs": inputs},
            config_path,
            workspace,
            "research",
        )


def test_replay_config_requires_all_inputs_and_new_confined_outputs(tmp_path: Path) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    example = workspace / "example"
    fixtures = workspace / "inputs"
    example.mkdir(parents=True)
    fixtures.mkdir()
    config_path = example / "replay.yaml"
    config_path.write_text("unused\n", encoding="utf-8")
    paths = {}
    for name in ("bundle", "minute", "quotes", "metadata"):
        source = fixtures / (name + ".json")
        source.write_text("{}\n", encoding="utf-8")
        paths[name] = "../inputs/" + source.name
    config = {
        "mode": "replay",
        "selection": {"bundle": paths["bundle"], "daily_bundles": []},
        "inputs": {
            "minute_tape": paths["minute"],
            "execution_quotes": paths["quotes"],
            "instrument_metadata": paths["metadata"],
        },
        "output": {
            "directory": "../output",
            "decision_tape_path": "../decision.jsonl",
            "evaluate_with_fincore": False,
        },
    }

    resolved = fixture._config_paths(config, config_path, workspace, "replay")
    assert resolved["inputs.minute_tape"] == str((fixtures / "minute.json").resolve())
    assert resolved["output.decision_tape_path"] == str((workspace / "decision.jsonl").resolve())

    (workspace / "output").mkdir()
    with pytest.raises(fixture.InstalledFixtureError, match="output directory must be new"):
        fixture._config_paths(config, config_path, workspace, "replay")


def test_cli_case_uses_isolated_child_and_reused_installed_origin_verifier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    config = example / "config.yaml"
    config.write_text("mode: dry\n", encoding="utf-8")
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for command construction")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    monkeypatch.setenv("PYTHONPATH", "checkout-shadow")
    monkeypatch.setenv("BT_SIMNOW_CONFIG_JSON", "must-not-reach-child")
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        child = {
            "exit_code": 0,
            "wheel_sha256": wheel_hash,
            "loaded_modules_verified": 17,
            "fresh_bytecode_cache": True,
        }
        stdout = json.dumps({"status": "DRY_VALIDATION_COMPLETE"}) + "\n"
        stdout += fixture._CHILD_MARKER + json.dumps(child) + "\n"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(fixture.subprocess, "run", fake_run)
    result = fixture.run_cli_case(
        example_dir=example,
        config_path=config,
        wheel_path=wheel,
        wheel_sha256=wheel_hash,
        mode="dry",
        factor_mode="native",
    )

    assert result["status"] == "DRY_VALIDATION_COMPLETE"
    assert result["summary"] == {"status": "DRY_VALIDATION_COMPLETE"}
    assert observed["command"][1:3] == ["-I", "-c"]
    assert "iteration50_installed_fixture.py" in observed["command"][4]
    compile(observed["command"][3], "<iteration51-installed-child>", "exec")
    assert json.loads(observed["command"][-1]) == result["cli_argv"]
    assert "--allow-write" not in observed["command"]
    assert result["cli_argv"] == [
        str((example / "run.py").resolve()),
        "--config",
        str(config.resolve()),
        "--mode",
        "dry",
        "--factor-mode",
        "native",
    ]
    assert observed["kwargs"]["cwd"] == str(example.resolve())
    assert "PYTHONPATH" not in observed["kwargs"]["env"]
    assert "BT_SIMNOW_CONFIG_JSON" not in observed["kwargs"]["env"]
    assert observed["kwargs"]["timeout"] == 180.0


def test_cli_timeout_preserves_partial_output_and_unknown_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    config = example / "config.yaml"
    config.write_text("mode: dry\n", encoding="utf-8")
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for timeout command")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    stdout = b"partial public CLI stdout\r\n"
    stderr = b"partial public CLI stderr\r\n"

    def timeout_run(*_args, **_kwargs):
        raise fixture.subprocess.TimeoutExpired(
            cmd=["public-cli"], timeout=2.0, output=stdout, stderr=stderr
        )

    monkeypatch.setattr(fixture.subprocess, "run", timeout_run)
    with pytest.raises(
        fixture.InstalledFixtureError,
        match="exit status is unknown",
    ):
        fixture.run_cli_case(
            example_dir=example,
            config_path=config,
            wheel_path=wheel,
            wheel_sha256=wheel_hash,
            mode="dry",
            factor_mode="native",
            timeout_seconds=2.0,
        )

    workspace = tmp_path
    stem = "iteration51-installed-cli-dry-native"
    stdout_path = workspace / (stem + ".stdout.bin")
    stderr_path = workspace / (stem + ".stderr.bin")
    exit_path = workspace / (stem + ".exit.txt")
    assert stdout_path.read_bytes() == stdout
    assert stderr_path.read_bytes() == stderr
    assert exit_path.read_bytes() == b"UNKNOWN_TIMEOUT\n"


def test_cli_fixture_rejects_live_and_write_options() -> None:
    fixture = _load_fixture()
    with pytest.raises(fixture.InstalledFixtureError, match="safe installed-fixture set"):
        fixture._child_command(
            verifier_path=_FIXTURE_PATH,
            wheel_path=_FIXTURE_PATH,
            wheel_sha256="0" * 64,
            example_dir=_FIXTURE_PATH.parent,
            config_path=_FIXTURE_PATH,
            mode="live",
            factor_mode="native",
        )


def test_synthetic_live_child_is_separate_from_the_offline_allowlist() -> None:
    fixture = _load_fixture()

    assert fixture.SAFE_MODES == ("dry", "research", "replay")
    assert fixture.SYNTHETIC_LIVE_CASES == (
        "read-only",
        "write",
        "write-denied",
        "tier-escalation",
    )
    assert len(fixture._SYNTHETIC_LIVE_CHILD_CODE) > 32767
    compile(fixture._SYNTHETIC_LIVE_CHILD_CODE, "<synthetic-live-child>", "exec")
    with pytest.raises(fixture.InstalledFixtureError, match="fixed local set"):
        fixture._synthetic_live_child_command(
            child_script_path=_FIXTURE_PATH,
            wheel_path=_FIXTURE_PATH,
            wheel_sha256="0" * 64,
            example_dir=_FIXTURE_PATH.parent,
            workspace=_FIXTURE_PATH.parent,
            selector_source_path=_FIXTURE_PATH,
            case="live",
            factor_mode="native",
        )


def test_sdk_selector_source_uses_the_fixed_public_pin_and_external_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    assert fixture.SDK_SELECTOR_SOURCE_COMMIT == "48b476ea90665791c7d2f86935720ce238931520"
    assert fixture.SDK_SELECTOR_SOURCE_SIZE_BYTES == 21403
    assert fixture.SDK_SELECTOR_SOURCE_SHA256 == (
        "ca8fa2b48293e7c5d79c1a0cfc20fd229879693290b99b56440b84c72cae12c3"
    )
    source = _write_test_selector_source(tmp_path, fixture, monkeypatch)

    evidence = fixture._pinned_sdk_selector_source(source)

    assert evidence == {
        "source_commit": fixture.SDK_SELECTOR_SOURCE_COMMIT,
        "source_path": fixture.SDK_SELECTOR_SOURCE_RELATIVE_PATH,
        "path": str(source.resolve()),
        "module": "bt_api_ctp.ctp_env_selector",
        "size_bytes": len(source.read_bytes()),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    with pytest.raises(fixture.InstalledFixtureError, match="outside the checkout"):
        fixture._pinned_sdk_selector_source(_FIXTURE_PATH)

    source.write_bytes(b"changed")
    with pytest.raises(fixture.InstalledFixtureError, match="fixed public size"):
        fixture._pinned_sdk_selector_source(source)
    source.write_bytes(b"x" * fixture.SDK_SELECTOR_SOURCE_SIZE_BYTES)
    with pytest.raises(fixture.InstalledFixtureError, match="fixed public pin"):
        fixture._pinned_sdk_selector_source(source)


def test_live_child_loads_pinned_selector_before_run_and_runner_uses_official_api() -> None:
    fixture = _load_fixture()
    child_source = fixture._SYNTHETIC_LIVE_CHILD_CODE
    assert "component.is_symlink()" in child_source
    assert "selector_path.relative_to(repository_root)" in child_source
    assert "len(selector_source_bytes) != SDK_SELECTOR_SOURCE_SIZE_BYTES" in child_source
    assert 'compile(selector_source_bytes, str(selector_path), "exec")' in child_source
    assert child_source.index(
        "sys.modules[SDK_SELECTOR_MODULE] = selector_module"
    ) < child_source.index("runpy.run_path(")
    mutable_bar_copy = "target: [dict(row) for row in target_rows]"
    assert "include_extra_fields=False" in child_source
    metadata_assignment = 'target_row["trading_day"] = trading_day.isoformat()'
    assert mutable_bar_copy in child_source
    assert child_source.index(mutable_bar_copy) < child_source.index(metadata_assignment)
    assert '"live_tick_provenance"' in child_source
    assert '"clock_domain_id": helper._CLOCK_DOMAIN' in child_source
    assert '"rules_hash": "a" * 64' in child_source
    assert '"session_segment": "regular"' in child_source
    assert "def _trace_live_cohort_exception(frame, event, arg):" in child_source
    assert '"backtrader.research.live_cohort"' in child_source
    assert '"live-cohort-exception-diagnostics.json"' in child_source
    for function_name in (
        "official_simnow_fronts",
        "official_simnow_profile_for_td_front",
        "verify_official_simnow_profile",
    ):
        assert function_name in child_source

    runner_path = (
        _FIXTURE_PATH.parents[1] / "examples" / "unified" / "028_alpha003_simnow_minute" / "run.py"
    )
    runner_source = runner_path.read_text(encoding="utf-8")
    assert "import bt_api_ctp.ctp_env_selector as selector" in runner_source
    assert "validate_official_simnow_store_profile(store_config, api_kwargs)" in runner_source
    assert "official_simnow_profile_for_td_front(td_front)" in runner_source


def test_synthetic_ctp_leaf_matches_registered_order_and_price_tick_contracts() -> None:
    fixture = _load_fixture()
    child_source = fixture._SYNTHETIC_LIVE_CHILD_CODE

    assert "def _synthetic_ctp_payload(fields):" in child_source
    assert "return types.SimpleNamespace(**fields)" in child_source
    assert "_synthetic_ctp_payload(payload)" in child_source
    assert child_source.count("_synthetic_ctp_payload(") == 3
    assert "self._req_id = 100" in child_source
    assert "wrapper_frame = leaf_frame.f_back" in child_source
    assert 'wrapper_frame.f_code.co_name != "connect"' in child_source
    assert '_emit_order_status("3", 0, quantity)' in child_source
    assert '_emit_order_status("0", quantity, 0)' in child_source
    assert "OrderStatus=ctp_status" in child_source
    assert 'fake_state["ctp_order_callback_count"] += 1' in child_source
    assert 'fake_state["ctp_trade_callback_count"] += 1' in child_source
    assert 'fake_state["synthetic_fill_count"] += 1' in child_source
    assert 'order_sys_id = "iteration51-sys-" + order_ref' in child_source
    assert "OrderSysID=order_sys_id" in child_source
    assert "price_tick = price_tick_by_target[target]" in child_source
    assert 'tick_units = (Decimal(str(price)) / price_tick).quantize(Decimal("1"))' in child_source
    assert "bid_price = last_price - price_tick" in child_source
    assert "ask_price = last_price + price_tick" in child_source
    assert '"BidPrice1": float(bid_price)' in child_source
    assert '"AskPrice1": float(ask_price)' in child_source
    assert (
        "tick_volume_base, tick_volume_remainder = divmod(bar_volume, len(values))" in child_source
    )
    assert "cumulative_volume += tick_volume" in child_source
    assert 'fake_state["ctp_order_callback_associations"].append({' in child_source
    assert 'fake_state["arm_scope_observations"].append({' in child_source
    assert 'fake_state["disarm_scope_observations"].append(' in child_source
    assert 'query_order_row["OrderSysID"] = order_sys_id' in child_source
    assert 'query_trade_row["OrderSysID"] = order_sys_id' in child_source
    assert 'fake_state["ctp_trade_callback_associations"].append({' in child_source

    child_tree = ast.parse(child_source, filename="iteration51-synthetic-live-child.py")
    owner_helper = next(
        node
        for node in child_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_wrapper_owner_from_sdk_constructor"
    )
    namespace = {
        "sys": sys,
        "fake_state": {
            "wrapper_mros": [],
            "wrapper_write_flags": [],
            "wrapper_api_instances": [],
        },
        "leaf_bindings": [],
    }
    exec(
        compile(ast.Module(body=[owner_helper], type_ignores=[]), "<pinned-helper>", "exec"),
        namespace,
    )

    class RegisteredSimWrapper:
        _registered_sim_allow_writes = False

    class CtpClientWrapper:
        def connect(self):
            def synthetic_sdk_leaf_constructor():
                namespace["leaf_bindings"].append(
                    namespace["_wrapper_owner_from_sdk_constructor"]()
                )

            synthetic_sdk_leaf_constructor()

    class SyntheticRegisteredClient(RegisteredSimWrapper, CtpClientWrapper):
        pass

    wrapper = SyntheticRegisteredClient()
    wrapper.connect()
    assert namespace["fake_state"]["wrapper_api_instances"] == [wrapper]
    assert namespace["leaf_bindings"] == [wrapper]
    assert namespace["fake_state"]["wrapper_mros"][0][:3] == [
        "SyntheticRegisteredClient",
        "RegisteredSimWrapper",
        "CtpClientWrapper",
    ]
    assert namespace["fake_state"]["wrapper_write_flags"] == [False]


def test_synthetic_ctp_payload_matches_attribute_backed_sdk_leaf_contract() -> None:
    fixture = _load_fixture()
    child_tree = ast.parse(
        fixture._SYNTHETIC_LIVE_CHILD_CODE,
        filename="iteration51-synthetic-live-child.py",
    )
    payload_helper = next(
        node
        for node in child_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_synthetic_ctp_payload"
    )
    namespace = {"types": types}
    exec(
        compile(
            ast.Module(body=[payload_helper], type_ignores=[]),
            "<synthetic-ctp-payload-helper>",
            "exec",
        ),
        namespace,
    )

    payload = namespace["_synthetic_ctp_payload"](
        {
            "InstrumentID": "M2601",
            "TradingDay": "20261026",
            "ActionDay": "20261025",
            "UpdateTime": "09:00:01",
            "UpdateMillisec": 0,
            "LastPrice": 230.0,
        }
    )

    assert not isinstance(payload, dict)
    assert payload.InstrumentID == "M2601"
    assert payload.TradingDay == "20261026"
    assert payload.ActionDay == "20261025"
    assert payload.UpdateTime == "09:00:01"
    assert payload.UpdateMillisec == 0
    assert payload.LastPrice == 230.0


def test_synthetic_authorization_scope_receipt_is_exact_and_disarmed() -> None:
    fixture = _load_fixture()
    read_only = {
        "arm_calls": 0,
        "disarm_calls": 0,
        "arm_scope_observations": [],
        "disarm_scope_observations": [],
    }
    assert fixture._synthetic_authorization_scope_is_valid("read-only", read_only)
    assert not fixture._synthetic_authorization_scope_is_valid(
        "read-only",
        {
            **read_only,
            "arm_calls": 1,
            "arm_scope_observations": [
                {
                    "requested_instrument_id": "Y2611",
                    "authorized_instruments": ["Y2611"],
                }
            ],
        },
    )

    write = {
        "arm_calls": 2,
        "disarm_calls": 2,
        "synthetic_leaf_actions": [
            {"action": "insert", "order_ref": "1", "exchange": "DCE", "instrument": "M2611"},
            {"action": "insert", "order_ref": "2", "exchange": "DCE", "instrument": "A2611"},
        ],
        "arm_scope_observations": [
            {
                "requested_instrument_id": "M2611",
                "authorized_instruments": ["M2611"],
            },
            {
                "requested_instrument_id": "A2611",
                "authorized_instruments": ["A2611"],
            },
        ],
        "disarm_scope_observations": [["A2611"], ["M2611"]],
    }
    assert fixture._synthetic_authorization_scope_is_valid("write", write)
    wrong_target = {
        **write,
        "arm_scope_observations": [
            write["arm_scope_observations"][0],
            {
                "requested_instrument_id": "Y2611",
                "authorized_instruments": ["Y2611"],
            },
        ],
    }
    assert not fixture._synthetic_authorization_scope_is_valid("write", wrong_target)
    unmatched_disarm = {**write, "disarm_scope_observations": [["A2611"], ["Y2611"]]}
    assert not fixture._synthetic_authorization_scope_is_valid("write", unmatched_disarm)


def _synthetic_order_receipt(order_specs: tuple[tuple[str, str], ...]) -> dict[str, object]:
    actions = []
    arm_observations = []
    accepted_associations = []
    filled_associations = []
    trade_callbacks = []
    trade_queries = []
    for order_ref, instrument in order_specs:
        order_sys_id = "iteration51-sys-" + order_ref
        trade_id = "iteration51-" + order_ref
        actions.append(
            {"action": "insert", "order_ref": order_ref, "instrument": instrument, "exchange": "DCE"}
        )
        arm_observations.append(
            {
                "requested_instrument_id": instrument,
                "authorized_instruments": [instrument],
            }
        )
        accepted_associations.append(
            {
                "order_ref": order_ref,
                "status": "3",
                "callback_order_sys_id": order_sys_id,
                "query_order_sys_id": order_sys_id,
                "query_order_sys_id_matches": True,
                "callback_owner_is_wrapper": True,
                "pending_order_present": False,
                "pending_order_ref_matches": False,
                "system_id_order_ref_matches": True,
                "system_id_uses_full_pending_order": False,
            }
        )
        filled_associations.append(
            {
                "order_ref": order_ref,
                "status": "0",
                "callback_order_sys_id": order_sys_id,
                "query_order_sys_id": order_sys_id,
                "query_order_sys_id_matches": True,
                "callback_owner_is_wrapper": True,
                "pending_order_present": True,
                "pending_order_ref_matches": True,
                "system_id_order_ref_matches": True,
                "system_id_uses_full_pending_order": True,
            }
        )
        trade_callbacks.append(
            {"trade_id": trade_id, "order_ref": order_ref, "order_sys_id": order_sys_id}
        )
        trade_queries.append(
            {
                "trade_id": trade_id,
                "order_ref": order_ref,
                "callback_order_sys_id": order_sys_id,
                "query_order_sys_id": order_sys_id,
                "query_order_sys_id_matches": True,
            }
        )
    return {
        "max_order_intents_per_run": 20,
        "synthetic_leaf_actions": actions,
        "arm_calls": len(order_specs),
        "disarm_calls": len(order_specs),
        "arm_scope_observations": arm_observations,
        "disarm_scope_observations": [
            [instrument] for _order_ref, instrument in order_specs
        ],
        "synthetic_fill_count": len(order_specs),
        "ctp_order_callback_count": len(accepted_associations) + len(filled_associations),
        "ctp_order_callback_associations": accepted_associations + filled_associations,
        "ctp_trade_callback_count": len(trade_callbacks),
        "ctp_trade_callback_associations": trade_callbacks,
        "ctp_trade_query_associations": trade_queries,
    }


def test_synthetic_order_and_trade_query_ids_match_callback_ids_per_insert() -> None:
    fixture = _load_fixture()
    child = _synthetic_order_receipt((("12", "M2611"), ("13", "A2611")))
    assert fixture._synthetic_order_sys_id_provenance_is_valid(child)
    mismatched_query = json.loads(json.dumps(child))
    mismatched_query["ctp_trade_query_associations"][0]["query_order_sys_id"] = "wrong"
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(mismatched_query)
    missing_callback = json.loads(json.dumps(child))
    missing_callback["ctp_order_callback_associations"].pop(1)
    missing_callback["ctp_order_callback_count"] -= 1
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(missing_callback)
    duplicate_callback = json.loads(json.dumps(child))
    duplicate_callback["ctp_order_callback_associations"].append(
        dict(duplicate_callback["ctp_order_callback_associations"][0])
    )
    duplicate_callback["ctp_order_callback_count"] += 1
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(duplicate_callback)
    duplicate_ref = json.loads(json.dumps(child))
    duplicate_ref["synthetic_leaf_actions"].append(
        dict(duplicate_ref["synthetic_leaf_actions"][0])
    )
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(duplicate_ref)
    duplicate_trade = json.loads(json.dumps(child))
    duplicate_trade["ctp_trade_callback_associations"].append(
        dict(duplicate_trade["ctp_trade_callback_associations"][0])
    )
    duplicate_trade["ctp_trade_query_associations"].append(
        dict(duplicate_trade["ctp_trade_query_associations"][0])
    )
    duplicate_trade["ctp_trade_callback_count"] += 1
    duplicate_trade["synthetic_fill_count"] += 1
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(duplicate_trade)
    missing_trade = json.loads(json.dumps(child))
    missing_trade["ctp_trade_callback_associations"].pop()
    missing_trade["ctp_trade_query_associations"].pop()
    missing_trade["ctp_trade_callback_count"] -= 1
    missing_trade["synthetic_fill_count"] -= 1
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(missing_trade)
    wrong_ref = json.loads(json.dumps(child))
    wrong_ref["ctp_order_callback_associations"][1]["order_ref"] = "uninserted"
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(wrong_ref)
    orphan_trade = json.loads(json.dumps(child))
    for rows in (
        orphan_trade["ctp_trade_callback_associations"],
        orphan_trade["ctp_trade_query_associations"],
    ):
        rows[0]["order_ref"] = "uninserted"
        rows[0]["trade_id"] = "iteration51-uninserted"
        if "order_sys_id" in rows[0]:
            rows[0]["order_sys_id"] = "iteration51-sys-uninserted"
        else:
            rows[0]["callback_order_sys_id"] = "iteration51-sys-uninserted"
            rows[0]["query_order_sys_id"] = "iteration51-sys-uninserted"
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(orphan_trade)
    orphan_callback = {**child, "synthetic_leaf_actions": []}
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(orphan_callback)
    reduced_limit = {**child, "max_order_intents_per_run": 1}
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(reduced_limit)
    over_limit = _synthetic_order_receipt(
        tuple((str(index), "M2611") for index in range(1, 22))
    )
    assert not fixture._synthetic_order_sys_id_provenance_is_valid(over_limit)


@pytest.mark.parametrize(
    (
        "case",
        "exit_code",
        "status",
        "error_code",
        "write_enabled",
        "planned_slot_count",
        "expected_evidence_level",
    ),
    (
        (
            "read-only",
            0,
            "LIVE_EPOCH_SEQUENCE_COMPLETE",
            None,
            False,
            64,
            "INSTALLED_BT_WHEEL_PUBLIC_SDK_SOURCE_FIXTURE",
        ),
        (
            "write",
            0,
            "LIVE_EPOCH_SEQUENCE_COMPLETE",
            None,
            True,
            64,
            "INSTALLED_BT_WHEEL_PUBLIC_SDK_SOURCE_FIXTURE",
        ),
        (
            "write-denied",
            2,
            "BLOCKED",
            "LIVE_WRITE_GRANT_MISSING_IN_CONFIG",
            False,
            64,
            "INSTALLED_BT_WHEEL_PUBLIC_SDK_SOURCE_FIXTURE",
        ),
        (
            "tier-escalation",
            2,
            "BLOCKED",
            "ENTRY_TIER_ESCALATION_DENIED",
            False,
            64,
            "INSTALLED_BT_WHEEL_PUBLIC_SDK_SOURCE_FIXTURE",
        ),
        (
            "read-only",
            0,
            "LIVE_EPOCH_SEQUENCE_COMPLETE",
            None,
            False,
            32,
            "SYNTHETIC_DIAGNOSTIC_ONLY",
        ),
    ),
)
def test_synthetic_live_case_runs_isolated_command_and_checks_finite_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
    exit_code: int,
    status: str,
    error_code: Optional[str],
    write_enabled: bool,
    planned_slot_count: int,
    expected_evidence_level: str,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    (example / "config.yaml").write_text("schema: public-template\n", encoding="utf-8")
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    live_case_dir = workspace / "iteration51-live-case-test"
    live_case_dir.mkdir()
    live_config = live_case_dir / "runner.yaml"
    live_config.write_text("synthetic test config\n", encoding="utf-8")
    diagnostic_path = live_case_dir / "live-cohort-exception-diagnostics.json"
    diagnostic_document = {
        "schema": "backtrader.iteration51.synthetic_live_cohort_diagnostics.v1",
        "capture": "installed live_cohort exception events during copied public CLI run",
        "captured_exception_count": 0,
        "exceptions": [],
        "runner_summary": None,
    }
    diagnostic_bytes = json.dumps(
        diagnostic_document, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    diagnostic_path.write_bytes(diagnostic_bytes)
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for synthetic live command")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    selector_source_path = _write_test_selector_source(tmp_path, fixture, monkeypatch)
    selector_source = fixture._pinned_sdk_selector_source(selector_source_path)
    cli_argv = [
        str((example / "run.py").resolve()),
        "--config",
        str(live_config.resolve()),
        "--mode",
        "live",
        "--factor-mode",
        "native",
    ]
    if case in {"write", "write-denied"}:
        cli_argv.append("--allow-write")
    order_specs = (("1", "M2611"), ("2", "A2611")) if case == "write" else ()
    order_receipt = _synthetic_order_receipt(order_specs)
    if error_code is None:
        summary = {
            "status": status,
            "mode": "live",
            "cleanup_complete": True,
            "epoch_count": 1,
            "write_mode": write_enabled,
            "selection_source": "ctp_query_snapshot_equal_weight_v1",
            "epochs": [
                {
                    "status": "LIVE_RUN_COMPLETE",
                    "cleanup_complete": True,
                    "simnow_profile": {
                        "verified": True,
                        "environment": "simnow",
                        "profile": fixture.SDK_SELECTOR_PROFILE,
                    },
                    "routes": {"DCE.M": "M2611", "DCE.Y": "Y2611", "DCE.A": "A2611"},
                    "selection_source": "saved_bundle_legacy",
                    "scheduler_clock": "host-utc-plus-monotonic",
                    "selection_evidence": {
                        "routes": {
                            "DCE.M": "M2611",
                            "DCE.Y": "Y2611",
                            "DCE.A": "A2611",
                        },
                        "authorized_targets": ["DCE.M", "DCE.A"],
                    },
                    "strategy_order_events": {
                        "status": "AVAILABLE",
                        "events": [
                            {
                                "ref": int(order_ref),
                                "target": "DCE.M" if instrument == "M2611" else "DCE.A",
                            }
                            for order_ref, instrument in order_specs
                        ],
                    },
                }
            ],
        }
        instances = 1
        flags = [write_enabled]
    else:
        summary = {"status": status, "code": error_code}
        instances = 0
        flags = []
    child = {
        "case": case,
        "exit_code": exit_code,
        "cli_argv": cli_argv,
        "wheel_sha256": wheel_hash,
        "loaded_modules_verified": 12,
        "fresh_bytecode_cache": True,
        "ctp_wrapper_factory_unchanged": True,
        "ctp_wrapper_mro_verified": bool(instances),
        "ctp_trader_leaf_instances": instances,
        "ctp_md_leaf_instances": instances,
        "ctp_trader_leaf_wrapper_matches_registered_instance": bool(instances),
        "ctp_md_leaf_wrapper_matches_registered_instance": bool(instances),
        "ctp_wrapper_mros": (
            [["RegisteredSimClient", "RegisteredSimWrapper", "CtpClientWrapper", "object"]]
            if instances
            else []
        ),
        "store_write_flags": flags,
        "network_attempts": 0,
        **order_receipt,
        "selection_bundle_sha256": "a" * 64,
        "sdk_selector_source": {
            **selector_source,
            "module_origin": selector_source["path"],
            "profile_id": fixture.SDK_SELECTOR_PROFILE,
            "official_fronts_lookup": True,
            "td_front_profile_lookup": True,
            "official_profile_verification": True,
        },
        "sdk_selector_profile_id": fixture.SDK_SELECTOR_PROFILE,
        "sdk_selector_profile_verified": True,
        "synthetic_only": True,
        "virtual_scheduler": True,
        "virtual_scheduler_monotonic_is_real": True,
        "virtual_scheduler_advance_count": 1 if error_code is None else 0,
        "virtual_scheduler_delivered_ticks": 1 if error_code is None else 0,
        "virtual_scheduler_callback_delivery_count": len(order_specs),
        "virtual_scheduler_pending_callbacks": 0,
        "virtual_scheduler_late_callback_schedule_count": 0,
        "virtual_scheduler_final_utc": "2026-10-25T00:01:00+00:00",
        "runner_clock_patch_binding": "run.__globals__['RunnerWallClock']",
        "runner_clock_patch_target_is_function_globals": True,
        "runner_clock_patch_origin": str((example / "run.py").resolve()),
        "clock_origins": {
            "runner_wall_clock_binding": "copied run.py run.__globals__['RunnerWallClock']",
            "ctp_receive_wall_clock": (
                "backtrader.stores.btapistore.time.time -> synthetic virtual UTC"
            ),
            "monotonic_clock": "host time.monotonic_ns forwarded without virtualization",
            "scheduler_shared_state": (
                "RunnerWallClock and CTP leaves share one child-local instance"
            ),
        },
        "runner_clock_constructor_calls": 1 if error_code is None else 0,
        "runner_clock_shared_with_virtual_scheduler": error_code is None,
        "store_environment_shape_valid": True,
        "store_environment_api_kwargs_keys": ["fixture_marker", "live_tick_provenance"],
        "store_live_tick_provenance": {
            "clock_domain_id": "iteration50-installed-fixture-v1",
            "rules_hash": "a" * 64,
            "session_segment": "regular",
        },
        "live_cohort_exception_diagnostics": {
            "path": str(diagnostic_path),
            "size_bytes": len(diagnostic_bytes),
            "sha256": hashlib.sha256(diagnostic_bytes).hexdigest(),
            "captured_exception_count": 0,
        },
        "planned_slot_count": planned_slot_count,
        "query_families": ["account", "orders", "positions", "trades"]
        if error_code is None
        else [],
        "subscriptions": ["A2611", "M2611", "Y2611"] if error_code is None else [],
        "runner_summary_scheduler_clock_labels": (
            [{"path": "epochs[0]", "value": "host-utc-plus-monotonic"}]
            if error_code is None
            else []
        ),
        "runner_summary_scheduler_clock_label_meaning": (
            "production summary default identifier; not the injected runtime clock"
        ),
        "synthetic_leaf_close_receipt": {
            "trader_client_count": instances,
            "md_client_count": instances,
            "trader_stop_calls": instances,
            "trader_disconnect_calls": instances,
            "md_stop_calls": instances,
            "trader_connected_after_close": [False] if instances else [],
            "trader_ready_after_close": [False] if instances else [],
            "md_started_after_close": [False] if instances else [],
            "wrappers_connected_after_close": [False] if instances else [],
        },
        "authorized_products": ["DCE.M", "DCE.A"],
    }
    child["raw_cli_summary_sha256"] = hashlib.sha256(
        json.dumps(summary).encode("utf-8")
    ).hexdigest()
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        stdout = json.dumps(summary) + "\n"
        stdout += fixture._LIVE_CHILD_MARKER + json.dumps(child) + "\n"
        observed["stdout"] = stdout.encode("utf-8")
        observed["stderr"] = b""
        return SimpleNamespace(returncode=exit_code, stdout=observed["stdout"], stderr=b"")

    monkeypatch.setenv("PYTHONPATH", "checkout-shadow")
    monkeypatch.setenv("BT_SIMNOW_CONFIG_JSON", "ambient-must-not-reach-child")
    monkeypatch.setattr(fixture.subprocess, "run", fake_run)
    result = fixture.run_synthetic_live_case(
        example_dir=example,
        workspace=workspace,
        wheel_path=wheel,
        wheel_sha256=wheel_hash,
        selector_source_path=selector_source_path,
        case=case,
        planned_slot_count=planned_slot_count,
    )

    assert result["case"] == case
    assert result["status"] == status
    assert result["evidence_level"] == expected_evidence_level
    assert result["planned_slot_count"] == planned_slot_count
    assert result["formal_64_slot_acceptance"] is (planned_slot_count == 64)
    assert result["acceptance_status"] == (
        "SYNTHETIC_64_SLOT_CASE_ACCEPTED"
        if planned_slot_count == 64
        else "SYNTHETIC_DIAGNOSTIC_ONLY"
    )
    assert result["sdk_selector_source"] == selector_source
    assert observed["command"][1] == "-I"
    child_script = Path(observed["command"][2])
    assert child_script.parent == workspace.resolve()
    assert child_script.name == "iteration51-synthetic-live-child-native-" + case + ".py"
    assert "iteration50_installed_fixture.py" in observed["command"][3]
    child_source = child_script.read_bytes()
    assert child_source == fixture._SYNTHETIC_LIVE_CHILD_CODE.encode("utf-8")
    compile(child_source, str(child_script), "exec")
    assert len(fixture.subprocess.list2cmdline(observed["command"])) < 32767
    assert result["child_launcher"] == {
        "path": str(child_script),
        "size_bytes": len(child_source),
        "sha256": hashlib.sha256(child_source).hexdigest(),
    }
    child_output = result["child_process_output"]
    assert Path(child_output["stdout_path"]).read_bytes() == observed["stdout"]
    assert Path(child_output["stderr_path"]).read_bytes() == observed["stderr"]
    assert Path(child_output["exit_path"]).read_text(encoding="ascii") == f"{exit_code}\n"
    assert child_output["exit_code"] == exit_code
    assert child_output["exit_status"] == "returned"
    assert child_output["stdout_sha256"] == hashlib.sha256(observed["stdout"]).hexdigest()
    assert child_output["stderr_sha256"] == hashlib.sha256(observed["stderr"]).hexdigest()
    assert observed["command"][-4] == str(selector_source_path.resolve())
    assert observed["command"][-3:] == [case, "native", str(planned_slot_count)]
    assert observed["kwargs"]["cwd"] == str(example.resolve())
    assert "PYTHONPATH" not in observed["kwargs"]["env"]
    assert "BT_SIMNOW_CONFIG_JSON" not in observed["kwargs"]["env"]
    assert observed["kwargs"]["timeout"] == 300.0


def test_synthetic_live_child_output_is_preserved_before_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    (example / "config.yaml").write_text("schema: public-template\n", encoding="utf-8")
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for synthetic live command")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    selector_source_path = _write_test_selector_source(tmp_path, fixture, monkeypatch)
    stdout = b"child traceback bytes\r\n"
    stderr = b"raw child stderr\r\n"
    monkeypatch.setattr(
        fixture.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=9, stdout=stdout, stderr=stderr),
    )

    with pytest.raises(fixture.InstalledFixtureError, match="did not emit a JSON result"):
        fixture.run_synthetic_live_case(
            example_dir=example,
            workspace=workspace,
            wheel_path=wheel,
            wheel_sha256=wheel_hash,
            selector_source_path=selector_source_path,
            case="read-only",
        )

    stem = "iteration51-synthetic-live-child-native-read-only"
    assert (workspace / (stem + ".stdout.bin")).read_bytes() == stdout
    assert (workspace / (stem + ".stderr.bin")).read_bytes() == stderr
    assert (workspace / (stem + ".exit.txt")).read_text(encoding="ascii") == "9\n"


def test_synthetic_live_timeout_preserves_partial_output_and_unknown_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    (example / "config.yaml").write_text("schema: public-template\n", encoding="utf-8")
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for synthetic live command")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    selector_source_path = _write_test_selector_source(tmp_path, fixture, monkeypatch)
    stdout = b"partial child stdout before timeout\r\n"
    stderr = b"partial child stderr before timeout\r\n"

    def timeout_run(*_args, **_kwargs):
        raise fixture.subprocess.TimeoutExpired(
            cmd=["synthetic-child"],
            timeout=3.0,
            output=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(fixture.subprocess, "run", timeout_run)
    with pytest.raises(
        fixture.InstalledFixtureError,
        match="exit status is unknown",
    ):
        fixture.run_synthetic_live_case(
            example_dir=example,
            workspace=workspace,
            wheel_path=wheel,
            wheel_sha256=wheel_hash,
            selector_source_path=selector_source_path,
            case="read-only",
        )

    stem = "iteration51-synthetic-live-child-native-read-only"
    assert (workspace / (stem + ".stdout.bin")).read_bytes() == stdout
    assert (workspace / (stem + ".stderr.bin")).read_bytes() == stderr
    assert (workspace / (stem + ".exit.txt")).read_text(encoding="ascii") == ("UNKNOWN_TIMEOUT\n")


def test_synthetic_live_matrix_requires_fixed_64_slot_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_fixture()
    calls = []

    def accepted_case(**kwargs):
        calls.append(kwargs)
        return {
            "case": kwargs["case"],
            "planned_slot_count": kwargs["planned_slot_count"],
            "formal_64_slot_acceptance": kwargs["planned_slot_count"] == 64,
            "acceptance_status": "SYNTHETIC_64_SLOT_CASE_ACCEPTED",
        }

    monkeypatch.setattr(fixture, "run_synthetic_live_case", accepted_case)
    results = fixture.run_synthetic_live_matrix(
        example_dir=Path("example"),
        workspace=Path("workspace"),
        wheel_path=Path("wheel.whl"),
        wheel_sha256="a" * 64,
        selector_source_path=Path("selector.py"),
    )
    assert [call["case"] for call in calls] == list(fixture.SYNTHETIC_LIVE_CASES)
    assert all(call["planned_slot_count"] == 64 for call in calls)
    assert all(result["formal_64_slot_acceptance"] is True for result in results)

    def diagnostic_case(**kwargs):
        return {
            "case": kwargs["case"],
            "planned_slot_count": 32,
            "formal_64_slot_acceptance": False,
            "acceptance_status": "SYNTHETIC_DIAGNOSTIC_ONLY",
        }

    monkeypatch.setattr(fixture, "run_synthetic_live_case", diagnostic_case)
    with pytest.raises(fixture.InstalledFixtureError, match="fixed 64-slot gate"):
        fixture.run_synthetic_live_matrix(
            example_dir=Path("example"),
            workspace=Path("workspace"),
            wheel_path=Path("wheel.whl"),
            wheel_sha256="a" * 64,
            selector_source_path=Path("selector.py"),
        )
