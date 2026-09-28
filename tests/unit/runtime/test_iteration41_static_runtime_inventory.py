"""Keep the reviewed Iteration 41 replay inventory aligned with shipped entrypoints.

This is a static consistency test.  It does not replace the dedicated replay
or zero-I/O legacy-CLI tests listed in the inventory; those tests distinguish
the two config-first fail-closed pair scripts from the remaining retained
legacy paths.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import yaml

from backtrader_runtime.cli import build_parser
from backtrader_runtime.inventory import iteration41_runtime_registry


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
INVENTORY_PATH = REPOSITORY_ROOT / "examples" / "iteration41-runtime-inventory.json"
EXPECTED_RUNTIME_FIELDS = {
    "config_schema_version",
    "strategy",
    "runtime",
    "parameters",
}
EXPECTED_MODE_PRESET = {"mode": "simulation", "preset": "replay"}


def _load_inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _assignment_value(source_path: Path, name: str) -> object:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{source_path} does not assign {name}")


def _cli_options(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    options = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        options.update(
            argument.value
            for argument in node.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        )
    return options


def _registration_by_runtime_dir() -> dict[str, object]:
    root = REPOSITORY_ROOT.resolve()
    entries = {}
    for registration in iteration41_runtime_registry().registrations:
        if (
            registration.offline_managed_execution
            or registration.allowed_presets != ("replay",)
            or not _is_example_runtime(registration)
        ):
            continue
        relative = registration.runtime_dir.resolve().relative_to(root / "examples")
        entries["examples/" + relative.as_posix()] = registration
    return entries


def _is_example_runtime(registration: object) -> bool:
    """Keep the examples-only inventory separate from packaged fixtures."""

    try:
        registration.runtime_dir.resolve().relative_to(REPOSITORY_ROOT.resolve() / "examples")
    except ValueError:
        return False
    return True


def _managed_replay_registrations() -> tuple[object, ...]:
    return tuple(
        registration
        for registration in iteration41_runtime_registry().registrations
        if registration.offline_managed_execution
    )


def _public_market_shadow_registrations() -> tuple[object, ...]:
    return tuple(
        registration
        for registration in iteration41_runtime_registry().registrations
        if registration.allowed_presets == ("shadow",)
        and not registration.offline_managed_execution
        and _is_example_runtime(registration)
    )


def test_registered_runtime_private_config_and_secret_paths_are_git_ignored_and_untracked() -> None:
    """Keep private runtime files out of the Git index without runtime Git I/O.

    The loader deliberately works in installed deployments that need not have a
    Git checkout.  Repository/CI hygiene owns this complementary assertion.
    """

    relative_paths = tuple(
        sorted(
            f"{registration.runtime_dir.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()}/{name}"
            for registration in iteration41_runtime_registry().registrations
            if _is_example_runtime(registration)
            for name in ("config.yaml", "secrets.yaml")
        )
    )
    tracked = subprocess.run(
        ["git", "ls-files", "--", *relative_paths],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, tracked.stderr
    assert tracked.stdout.splitlines() == []

    for relative_path in relative_paths:
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", relative_path],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert ignored.returncode == 0, f"{relative_path} is not ignored: {ignored.stderr}"


def test_runtime_inventory_has_only_the_reviewed_replay_scope() -> None:
    inventory = _load_inventory()

    assert inventory["schema_version"] == "iteration41.example-runtime-inventory.v3"
    assert (
        inventory["evidence_scope"]
        == "STATIC_ENTRYPOINT_AND_TARGETED_TEST_REVIEW_NOT_PRODUCTION_OR_SIMNOW_ACCEPTANCE"
    )
    canonical = inventory["canonical_runtime_contract"]
    assert canonical["config_schema_version"] == 4
    assert canonical["required_config"] == "<registered runtime_dir>/config.yaml"
    assert canonical["config_template"] == "<registered runtime_dir>/config.example.yaml"
    assert canonical["supported_mode_preset"] == EXPECTED_MODE_PRESET
    assert canonical["external_network"] is False
    assert canonical["external_writes"] is False
    assert canonical["production_writes"] is False
    assert canonical["managed_execution"] == "NOT_WIRED_BY_THIS_RUNTIME_INVENTORY"
    assert canonical["copied_runtime_behavior"] == "REJECTED_BEFORE_FRAMEWORK_OR_PROVIDER_IMPORT"


def test_runtime_inventory_matches_the_code_owned_registry_and_templates() -> None:
    inventory = _load_inventory()
    entries = inventory["iteration41_entrypoints"]
    registrations = _registration_by_runtime_dir()

    assert len(entries) == 11
    assert {"examples/" + entry["runtime_dir"] for entry in entries} == set(registrations)
    runner_modules = [entry["runner_module"] for entry in entries]
    assert all(runner_modules)
    assert len(runner_modules) == len(set(runner_modules))

    for entry in entries:
        source_path = REPOSITORY_ROOT / "examples" / entry["path"]
        runtime_dir = REPOSITORY_ROOT / "examples" / entry["runtime_dir"]
        template_path = runtime_dir / entry["config_template"]
        test_paths = [REPOSITORY_ROOT / test_path for test_path in entry["verification_tests"]]
        registration = registrations["examples/" + entry["runtime_dir"]]

        assert entry["status"] == "LOCAL_REPLAY_ONLY"
        assert entry["required_config"] == "config.yaml"
        assert entry["config_schema_version"] == 4
        assert entry["supported_mode_preset"] == EXPECTED_MODE_PRESET
        assert entry["allowed_parameter_keys"] == ["scenario"]
        assert entry["external_network"] is False
        assert entry["external_writes"] is False
        assert entry["production_writes"] is False
        assert entry["managed_execution"] == "NOT_WIRED_BY_THIS_RUNTIME_ENTRYPOINT"

        assert source_path.is_file()
        assert template_path.is_file()
        runner_path = entry["path"]
        if runner_path.endswith(".py"):
            runner_path = runner_path[:-3]
        expected_module = "examples." + runner_path.replace("/", ".")
        assert entry["runner_module"] == expected_module
        assert _assignment_value(source_path, "STRATEGY_ID") == entry["strategy_id"]
        assert _cli_options(source_path) == {"--runtime-dir"}

        template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
        assert set(template) == EXPECTED_RUNTIME_FIELDS
        assert template["config_schema_version"] == entry["config_schema_version"]
        assert template["strategy"] == {"id": entry["strategy_id"]}
        assert template["runtime"] == entry["supported_mode_preset"]
        assert set(template["parameters"]) == set(entry["allowed_parameter_keys"])
        ignored_runtime_files = (
            (runtime_dir / ".gitignore").read_text(encoding="utf-8").splitlines()
        )
        assert "/config.yaml" in ignored_runtime_files
        assert "/secrets.yaml" in ignored_runtime_files

        assert registration.strategy_id == entry["strategy_id"]
        assert registration.runner_module == entry["runner_module"]
        assert registration.runner_module
        assert registration.runner_entrypoint == "run_runtime"
        assert registration.allowed_presets == ("replay",)
        assert registration.allowed_parameter_keys == ("scenario",)
        assert registration.sandbox_write_policy == "deny"
        assert registration.available_capabilities == ()

        for test_path in test_paths:
            evidence_source = test_path.read_text(encoding="utf-8")
            assert "LOCAL_REPLAY_ONLY" in evidence_source
            assert "external_request_counts" in evidence_source
        if "research_status" in entry:
            assert entry["research_status"] in test_paths[0].read_text(encoding="utf-8")
        if "hft_admission" in entry:
            assert entry["hft_admission"] == "HFT_NOT_ADMITTED"
            assert entry["report_hft_status"] in test_paths[0].read_text(encoding="utf-8")


def test_public_market_shadow_inventory_is_separate_from_the_replay_contract() -> None:
    inventory = _load_inventory()
    contract = inventory["public_market_shadow_contract"]
    entries = inventory["public_market_shadow_entrypoints"]
    registrations = _public_market_shadow_registrations()

    assert inventory["canonical_runtime_contract"]["supported_mode_preset"] == {
        "mode": "simulation",
        "preset": "replay",
    }
    assert inventory["canonical_runtime_contract"]["external_network"] is False
    assert len(inventory["iteration41_entrypoints"]) == 11
    assert contract["supported_mode_preset"] == {"mode": "simulation", "preset": "shadow"}
    assert contract["external_network"] is True
    assert contract["external_writes"] is False
    assert contract["production_writes"] is False
    assert contract["account_access"] == "PUBLIC_MARKET_ONLY"
    assert contract["credentials_accepted"] is False
    assert contract["hypothetical_fills"] is False
    assert contract["strategy_execution"] == "NOT_RUN"
    assert contract["requested_orderbook_limit"] == 5
    assert contract["provider_dependencies"] == {
        "optional_extra": "okx-public-shadow",
        "ccxt": "4.5.83",
        "aiohttp": "3.14.3",
    }
    assert len(entries) == len(registrations) == 1

    entry = entries[0]
    registration = registrations[0]
    source_path = REPOSITORY_ROOT / "examples" / entry["path"]
    runtime_dir = REPOSITORY_ROOT / "examples" / entry["runtime_dir"]
    template = yaml.safe_load((runtime_dir / entry["config_template"]).read_text(encoding="utf-8"))
    bootstrap_parameters = dict(registration.bootstrap_parameters)

    assert entry["status"] == "PUBLIC_MARKET_SHADOW_ONLY"
    assert entry["strategy_id"] == registration.strategy_id
    assert entry["runtime_id"] == registration.runtime_id
    assert entry["runner_module"] == registration.runner_module
    assert entry["runner_module"] == "examples.010_live_examples.run_okx_shadow_runtime"
    assert entry["runtime_dir"] == "010_live_examples/runtime-okx-shadow"
    assert entry["supported_mode_preset"] == contract["supported_mode_preset"]
    assert entry["allowed_parameter_keys"] == ["symbols", "duration_seconds", "orderbook_limit"]
    assert registration.allowed_presets == ("shadow",)
    assert registration.allowed_parameter_keys == tuple(entry["allowed_parameter_keys"])
    assert registration.allowed_secrets_refs == ("none",)
    assert registration.capability_modules == ()
    assert bootstrap_parameters == {
        "symbols": ("BTC/USDT:USDT", "ETH/USDT:USDT"),
        "duration_seconds": 10,
        "orderbook_limit": 5,
    }
    assert entry["code_owned_bootstrap_parameters"] == {
        "symbols": list(bootstrap_parameters["symbols"]),
        "duration_seconds": bootstrap_parameters["duration_seconds"],
        "orderbook_limit": bootstrap_parameters["orderbook_limit"],
    }
    assert entry["provider_dependencies"] == contract["provider_dependencies"]
    assert entry["external_network"] is True
    assert entry["external_writes"] is False
    assert entry["production_writes"] is False
    assert entry["credentials_accepted"] is False
    assert entry["hypothetical_fills"] is False
    assert entry["strategy_execution"] == "NOT_RUN"
    assert _assignment_value(source_path, "STRATEGY_ID") == entry["strategy_id"]
    assert template["config_schema_version"] == 4
    assert template["strategy"] == {"id": entry["strategy_id"]}
    assert template["runtime"] == entry["supported_mode_preset"]
    assert template["parameters"] == entry["code_owned_bootstrap_parameters"]

    ignored = (runtime_dir / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/config.yaml" in ignored
    assert "/secrets.yaml" in ignored


def _main_call_names(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    return {
        node.func.id
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_standalone_runtime_entrypoints_use_sealed_config_first_dispatch() -> None:
    """Legacy script shims must not bypass the CLI-equivalent sealed dispatch."""

    inventory = _load_inventory()
    source_paths = [
        REPOSITORY_ROOT / "examples" / entry["path"]
        for entry in (
            inventory["iteration41_entrypoints"] + inventory["managed_replay_l2_entrypoints"]
        )
    ]
    source_paths.extend(
        (
            REPOSITORY_ROOT / "backtrader_runtime" / "_iteration41_l2_fixture" / "managed_013_3.py",
            REPOSITORY_ROOT
            / "backtrader_runtime"
            / "_iteration41_l2_fixture"
            / "mechanical_p1b.py",
        )
    )

    for source_path in source_paths:
        calls = _main_call_names(source_path)
        assert "dispatch_configured_runtime" in calls
        assert "run_runtime" not in calls


def test_managed_replay_l2_inventory_is_separate_from_the_ordinary_replays() -> None:
    inventory = _load_inventory()
    entries = inventory["managed_replay_l2_entrypoints"]
    registrations = _managed_replay_registrations()

    assert len(entries) == len(registrations) == 2
    registrations_by_runtime_id = {
        registration.runtime_id: registration for registration in registrations
    }
    assert (
        {entry["runtime_id"] for entry in entries}
        == set(registrations_by_runtime_id)
        == {
            "example.013_3.sa_midfreq_simnow.managed_replay_l2",
            "example.ctp_options_simnow.mechanical_managed_replay_l2",
        }
    )

    for entry in entries:
        registration = registrations_by_runtime_id[entry["runtime_id"]]
        source_path = REPOSITORY_ROOT / "examples" / entry["path"]
        runtime_dir = REPOSITORY_ROOT / "examples" / entry["runtime_dir"]
        template_path = runtime_dir / entry["config_template"]
        test_paths = [REPOSITORY_ROOT / path for path in entry["verification_tests"]]

        assert entry["status"] in {
            "LOCAL_MANAGED_FAKE_PROVIDER_L2",
            "LOCAL_CTP_MECHANICAL_MANAGED_FAKE_PROVIDER_L2",
        }
        assert entry["required_config"] == "config.yaml"
        assert entry["config_schema_version"] == 4
        assert entry["supported_mode_preset"] == EXPECTED_MODE_PRESET
        assert entry["allowed_parameter_keys"] == []
        assert entry["external_network"] is False
        assert entry["external_writes"] is False
        assert entry["production_writes"] is False
        assert entry["managed_execution"] == "REVIEWED_OFFLINE_FAKE_PROVIDER_EXECUTION_RISK_MONITOR"

        assert source_path.is_file()
        assert template_path.is_file()
        assert test_paths[0].is_file()
        assert _assignment_value(source_path, "STRATEGY_ID") == entry["strategy_id"]
        assert _cli_options(source_path) == {"--runtime-dir"}
        template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
        assert set(template) == EXPECTED_RUNTIME_FIELDS
        assert template["strategy"] == {"id": entry["strategy_id"]}
        assert template["runtime"] == entry["supported_mode_preset"]
        assert template["parameters"] == {}
        ignored_runtime_files = (
            (runtime_dir / ".gitignore").read_text(encoding="utf-8").splitlines()
        )
        assert "/config.yaml" in ignored_runtime_files
        assert "/secrets.yaml" in ignored_runtime_files

        assert registration.runtime_id == entry["runtime_id"]
        assert registration.strategy_id == entry["strategy_id"]
        assert registration.runner_module == entry["runner_module"]
        assert registration.runner_entrypoint == "run_runtime"
        assert registration.allowed_presets == ("replay",)
        assert registration.allowed_parameter_keys == ()
        assert registration.allowed_secrets_refs == ("none",)
        assert registration.offline_managed_execution is True
        assert registration.sandbox_write_policy == "deny"
        assert registration.available_capabilities == ("execution", "risk", "monitor")

    mechanical = next(
        entry
        for entry in entries
        if entry["runtime_id"] == "example.ctp_options_simnow.mechanical_managed_replay_l2"
    )
    assert mechanical["evidence_boundary"] == (
        "FAKE_PROVIDER_L2_ONLY_NOT_CTP_SIMNOW_OR_REAL_TRADING_EVIDENCE"
    )
    mechanical_readme = (
        REPOSITORY_ROOT / "examples" / mechanical["runtime_dir"] / "README.md"
    ).read_text(encoding="utf-8")
    assert "does **not** connect to CTP or SimNow" in mechanical_readme
    assert "production or SimNow startup entrypoint" in mechanical_readme

    registry = iteration41_runtime_registry()
    runtime_sets = {item.name: item.runtime_ids for item in registry.runtime_sets}
    assert runtime_sets["iteration41-replay"] == (
        "example.012_1.midfreq_cross_exchange",
        "example.012_2.event_driven_cross_exchange",
        "example.013_1.midfreq_cross_arbitrage",
        "example.013_2.highfreq_calendar_arbitrage",
        "example.013_3.sa_midfreq_simnow",
        "example.014_1.ctp_options_lowfreq",
        "example.014_2.ctp_options_midfreq",
        "example.015.ctp_options_highfreq",
        "example.sample.ctp_legacy",
        "example.007_ctp.legacy_direct",
        "example.010_live_examples.simnow_legacy",
    )
    assert runtime_sets["iteration41-managed-replay-l2"] == (
        "example.013_3.sa_midfreq_simnow.managed_replay_l2",
        "example.ctp_options_simnow.mechanical_managed_replay_l2",
    )


def test_example_readmes_use_the_shipped_bootstrap_and_replay_cli_contract() -> None:
    inventory = _load_inventory()
    entries = {entry["example_dir"]: entry for entry in inventory["iteration41_entrypoints"]}
    parser = build_parser()

    assert len(entries) == 11
    for directory, entry in entries.items():
        readme = (REPOSITORY_ROOT / "examples" / directory / "README.md").read_text(
            encoding="utf-8"
        )
        runtime_dir = "examples/" + entry["runtime_dir"]

        assert entry["config_template"] in readme
        assert "runtime/config.yaml" in readme
        assert "CONFIG_REQUIRED" in readme
        assert "CONFIG_EXISTS" in readme
        assert "LOCAL_REPLAY_ONLY" in readme
        assert "run.py" in readme
        bootstrap_command = "bt-runtime bootstrap --strategy-dir " + runtime_dir
        run_command = "bt-runtime run --strategy-dir " + runtime_dir
        assert bootstrap_command in readme
        assert run_command in readme
        assert readme.index(bootstrap_command) < readme.index(run_command)
        assert "bt-runtime run --runtime-dir" not in readme

        bootstrap_arguments = parser.parse_args(["bootstrap", "--strategy-dir", runtime_dir])
        assert bootstrap_arguments.command == "bootstrap"
        assert bootstrap_arguments.strategy_dir == Path(runtime_dir)
        assert bootstrap_arguments.preset is None

        run_arguments = parser.parse_args(["run", "--strategy-dir", runtime_dir])
        assert run_arguments.command == "run"
        assert run_arguments.strategy_dir == Path(runtime_dir)

    assert "FAIL/NOT_ADMITTED" in (
        REPOSITORY_ROOT / "examples" / "013_2_highfreq_calendar_arbitrage" / "README.md"
    ).read_text(encoding="utf-8")


def test_legacy_entrypoints_are_explicitly_outside_the_v4_runtime_contract() -> None:
    """Classify legacy scripts without treating an old CLI as a write escape hatch."""

    inventory = _load_inventory()
    entries_by_path = {entry["path"]: entry for entry in inventory["iteration41_entrypoints"]}
    legacy_entries = inventory["legacy_entrypoints"]
    config_first_paths = {
        "007_ctp/ctp_sa_dual_ma_strategy.py",
        "007_ctp/ctp_bbroker_5s_examples/backtest/run.py",
        "007_ctp/ctp_bbroker_5s_examples/live/run.py",
        "007_ctp/ctp_mixbroker_5s_examples/backtest/run.py",
        "007_ctp/ctp_mixbroker_5s_examples/live/run.py",
        "007_ctp/ctp_mixbroker_examples/backtest/run.py",
        "007_ctp/ctp_mixbroker_examples/live/run.py",
        "007_ctp/ctp_tickbroker_5s_examples/backtest/run.py",
        "007_ctp/ctp_tickbroker_5s_examples/live/run.py",
        "007_ctp/ctp_tickbroker_examples/backtest/run.py",
        "007_ctp/ctp_tickbroker_examples/live/run.py",
        "007_ctp/live_certification/simnow_penetration/run_case.py",
        "007_ctp/live_certification/simnow_penetration/run_all.py",
        "007_ctp/live_certification/hongyuan_penetration/run_case.py",
        "007_ctp/live_certification/hongyuan_penetration/run_all.py",
        "010_live_examples/test_simnow_ctp.py",
        "010_live_examples/test_simnow_trade_logger_certification.py",
        "013_1_midfreq_cross_arbitrage/run.py",
        "013_2_highfreq_calendar_arbitrage/run.py",
        "013_3_sa_midfreq_simnow/run.py",
        "014_1_ctp_options_lowfreq/run.py",
        "014_2_ctp_options_midfreq/run.py",
    }
    config_first_boundary = (
        "Direct CLI reaches only the registered config-v4 replay route; missing or unsupported "
        "config and every historical flag fail before framework/provider import. Direct CTP/SimNow "
        "execution is NOT_SUPPORTED."
    )

    assert len(legacy_entries) == 25
    assert len(entries_by_path) == 11
    assert "sample.py" not in {legacy["path"] for legacy in legacy_entries}
    assert config_first_paths <= {legacy["path"] for legacy in legacy_entries}
    for legacy in legacy_entries:
        legacy_path = REPOSITORY_ROOT / "examples" / legacy["path"]
        replacement = legacy["iteration41_replacement"]

        assert legacy_path.is_file()
        assert replacement in entries_by_path
        if legacy["path"] in config_first_paths:
            assert legacy["status"] == "LEGACY_CLI_CONFIG_FIRST_FAIL_CLOSED"
            assert legacy["boundary"] == config_first_boundary
        else:
            assert legacy["status"] == "LEGACY_RETAINED_OUTSIDE_ITERATION41_RUNTIME_CONTRACT"
            assert (
                legacy["boundary"]
                == "Do not use this path as evidence of config-v4 validation, replay-only behavior, "
                "or execution admission."
            )
