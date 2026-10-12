"""Strict config-entry schema checks through the real unified-runner main loaders."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from importlib.abc import MetaPathFinder
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
UNIFIED = ROOT / "examples" / "unified"
ALL_ENTRIES = (
    "012_1_midfreq_cross_exchange",
    "012_2_event_driven_cross_exchange",
    "013_1_midfreq_cross_arbitrage",
    "013_2_highfreq_calendar_arbitrage",
    "013_3_sa_midfreq_simnow",
    "014_1_ctp_options_lowfreq",
    "014_2_ctp_options_midfreq",
    "015_ctp_options_highfreq",
)
ENTRY_012 = ("012_1_midfreq_cross_exchange", "012_2_event_driven_cross_exchange")
ENTRY_013_3 = "013_3_sa_midfreq_simnow"
PUBLIC_013_3_CONFIG = "examples/unified/013_3_sa_midfreq_simnow/config.yaml"
HANDLER_NAMES = ("run_dry", "run_replay", "run_live", "run_live_observe")
_013_3_LOCAL_ALIASES = (
    "legacy_runner",
    "account_lock",
    "reporting",
    "risk",
    "features",
    "signal_model",
    "sa_midfreq_strategy",
)
PROVIDER_IMPORT_ROOTS = {
    "binance",
    "bt_api_ctp",
    "bt_api_py",
    "ccxt",
    "ccxtpro",
    "ctpbee",
    "hftbacktest",
    "okx",
    "pybit",
    "simnow_direct",
}


class _ProviderImportTrap(MetaPathFinder):
    """Record and deny provider imports while a synthetic config reaches main."""

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in PROVIDER_IMPORT_ROOTS:
            self.attempts.append(fullname)
            raise AssertionError(f"provider import attempted during config dispatch: {fullname}")
        return None


def _load_runner(entry: str, monkeypatch: pytest.MonkeyPatch):
    """Load the real runner with its folder-local helper and a provider import trap."""

    runner_path = UNIFIED / entry / "run.py"
    entry_dir = runner_path.parent
    module_name = f"_iteration43_schema_{entry}"
    provider_trap = _ProviderImportTrap()
    monkeypatch.setattr(sys, "meta_path", [provider_trap, *sys.meta_path])
    monkeypatch.syspath_prepend(str(entry_dir))

    legacy_runner = None
    if entry == ENTRY_013_3:
        # legacy_runner uses bare folder-local imports. Remove any same-named
        # aliases left by another example, then let monkeypatch restore them
        # after this test. This makes the runner and all its leaves come from
        # the 013_3 directory without leaking aliases into sibling examples.
        missing_alias = object()
        for alias in _013_3_LOCAL_ALIASES:
            prior = sys.modules.get(alias, missing_alias)
            # Record even an originally absent alias. The subsequent import
            # may create it, and teardown must remove that new local module.
            monkeypatch.setitem(sys.modules, alias, prior)
            monkeypatch.delitem(sys.modules, alias)
        legacy_path = entry_dir / "legacy_runner.py"
        legacy_spec = importlib.util.spec_from_file_location("legacy_runner", legacy_path)
        assert legacy_spec is not None and legacy_spec.loader is not None
        legacy_runner = importlib.util.module_from_spec(legacy_spec)
        monkeypatch.setitem(sys.modules, "legacy_runner", legacy_runner)
        legacy_spec.loader.exec_module(legacy_runner)

    # The direct-script branches resolve the folder-local helper as ``entry_tier``.
    # Restore any helper another test already imported after this isolated load.
    missing = object()
    previous_helper = sys.modules.pop("entry_tier", missing)
    try:
        spec = importlib.util.spec_from_file_location(module_name, runner_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("entry_tier", None)
        if previous_helper is not missing:
            sys.modules["entry_tier"] = previous_helper

    if legacy_runner is not None:
        monkeypatch.setattr(module, "_iteration43_legacy_runner", legacy_runner, raising=False)
        monkeypatch.setattr(
            module,
            "_iteration43_synthetic_config",
            _valid_013_3_config(),
            raising=False,
        )

    calls: list[str] = []
    installed_handlers = []
    for name in HANDLER_NAMES:
        if not callable(getattr(module, name, None)):
            continue

        def _fake_handler(*args, _name=name, **kwargs):
            calls.append(_name)
            print(json.dumps({"status": "FAKE_HANDLER", "handler": _name}, sort_keys=True))
            return 0

        monkeypatch.setattr(module, name, _fake_handler)
        installed_handlers.append(name)

    assert "run_dry" in installed_handlers, f"{entry} exposes no dry handler"
    return module, calls, provider_trap


def _write_document(module, directory: Path, document: str | dict[str, Any], monkeypatch) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    text = document if isinstance(document, str) else yaml.safe_dump(document, sort_keys=False)
    config_path = directory / "config.yaml"
    config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(module, "HERE", directory)
    legacy_runner = getattr(module, "_iteration43_legacy_runner", None)
    if legacy_runner is not None:
        # 013_3's production loader reads legacy_runner.DEFAULT_CONFIG, not
        # run.py.HERE. Point the actual loader at the synthetic file on every
        # invocation so no test can fall through to a checkout config.
        monkeypatch.setattr(legacy_runner, "DEFAULT_CONFIG", config_path)


def _valid_013_3_config() -> dict[str, Any]:
    """Build an isolated synthetic entry from the committed public template."""

    completed = subprocess.run(
        ["git", "show", f"HEAD:{PUBLIC_013_3_CONFIG}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    config = yaml.safe_load(completed.stdout.decode("utf-8-sig"))
    assert isinstance(config, dict), "the committed 013_3 config template must be a mapping"
    config = deepcopy(config)
    config["entry"] = {"tier": "dry"}

    credentials = config.get("credentials")
    assert isinstance(credentials, dict) and credentials
    for key in credentials:
        credentials[key] = f"SYNTHETIC_{str(key).upper()}"

    front_pairs = (config.get("fronts") or {}).get("pairs")
    assert isinstance(front_pairs, list) and front_pairs
    for index, pair in enumerate(front_pairs):
        assert isinstance(pair, dict)
        pair["td_env"] = f"SYNTHETIC_TD_FRONT_{index}"
        pair["md_env"] = f"SYNTHETIC_MD_FRONT_{index}"

    # Keep the public v0 legacy fields required by the real validator, while
    # making all Iteration-42 selections explicitly synthetic and read-only.
    config["schema_version"] = 2
    config["venue"] = "simnow"
    config["policy"]["allow_write"] = False
    return config


def _last_payload(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, f"runner emitted no JSON: {stdout!r}"
    payload = json.loads(lines[-1])
    assert isinstance(payload, dict), payload
    return payload


def _run_main(module, directory: Path, document: str | dict[str, Any], monkeypatch, capsys):
    has_legacy_loader = getattr(module, "_iteration43_legacy_runner", None) is not None
    if isinstance(document, dict) and has_legacy_loader:
        synthetic = deepcopy(module._iteration43_synthetic_config)
        synthetic.update(document)
        document = synthetic
    _write_document(module, directory, document, monkeypatch)
    result = module.main([])
    captured = capsys.readouterr()
    return result, _last_payload(captured.out), captured.out


def _assert_config_blocked(result: int, payload: dict[str, Any]) -> None:
    assert result == 2, payload
    assert payload.get("status") == "BLOCKED", payload
    assert payload.get("reason") == "config_tier_invalid", payload
    assert (
        payload.get("entry_tier", {}).get("tier_selection_reason") == "config_tier_invalid"
    ), payload
    assert payload.get("entry_tier", {}).get("effective_tier") == "dry", payload


def _valid_012_config(*, include_evidence_boundary: bool = True) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "tier": "dry",
        "venue": ["okx", "binance"],
        "credentials": {
            "okx_api_key_env": "SYNTHETIC_OKX_API_KEY",
            "okx_secret_env": "SYNTHETIC_OKX_SECRET",
            "okx_passphrase_env": "SYNTHETIC_OKX_PASSPHRASE",
            "binance_api_key_env": "SYNTHETIC_BINANCE_API_KEY",
            "binance_secret_env": "SYNTHETIC_BINANCE_SECRET",
        },
        "policy": {
            "max_actions": 2,
            "max_order_notional_usdt": 100.0,
            "max_round_trips": 1,
        },
        "timeouts": {"run_seconds": 1, "stop_seconds": 1},
    }
    if include_evidence_boundary:
        entry["evidence_boundary"] = "SYNTHETIC_LOCAL_TEST_ONLY"
    return {"entry": entry}


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_main_loader_blocks_malformed_yaml_and_entry_shapes_before_handlers(
    entry: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Use only temporary YAML and prove invalid roots/declarations never dispatch."""

    module, handlers, provider_trap = _load_runner(entry, monkeypatch)
    config_dir = tmp_path / entry
    malformed_documents: tuple[tuple[str, str | dict[str, Any]], ...] = (
        ("yaml_false", "false\n"),
        ("yaml_zero", "0\n"),
        ("yaml_null", "null\n"),
        ("yaml_string", "synthetic_root_string\n"),
        ("yaml_list", "- synthetic_root_item\n"),
        (
            "unknown_entry_key",
            {"entry": {"tier": "dry", "unexpected_iteration43_key": "SYNTHETIC_VALUE"}},
        ),
        ("null_entry", {"entry": None}),
        ("false_entry", {"entry": False}),
        ("zero_entry", {"entry": 0}),
        ("string_entry", {"entry": "synthetic_tier"}),
        ("list_entry", {"entry": ["dry"]}),
        ("false_tier", {"entry": {"tier": False}}),
        ("zero_tier", {"entry": {"tier": 0}}),
        ("null_tier", {"entry": {"tier": None}}),
        ("unknown_string_tier", {"entry": {"tier": "synthetic_tier"}}),
        ("list_tier", {"entry": {"tier": ["dry"]}}),
    )

    for case, document in malformed_documents:
        handlers.clear()
        provider_trap.attempts.clear()
        result, payload, stdout = _run_main(module, config_dir, document, monkeypatch, capsys)

        assert result == 2, (entry, case, payload)
        assert payload.get("status") == "BLOCKED", (entry, case, payload)
        assert handlers == [], (entry, case, handlers)
        assert provider_trap.attempts == [], (entry, case, provider_trap.attempts)
        if case not in {"yaml_false", "yaml_zero", "yaml_null", "yaml_string", "yaml_list"}:
            _assert_config_blocked(result, payload)
        assert "SYNTHETIC_VALUE" not in stdout, (entry, case, stdout)


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_main_dispatches_valid_synthetic_dry_config_without_provider_imports(
    entry: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The default strict schema accepts its valid config and reaches only fake dry code."""

    module, handlers, provider_trap = _load_runner(entry, monkeypatch)
    if entry in ENTRY_012:
        config = _valid_012_config()
    elif entry == ENTRY_013_3:
        config = _valid_013_3_config()
    else:
        config = {"entry": {"tier": "dry"}}
    result, payload, _stdout = _run_main(module, tmp_path / entry, config, monkeypatch, capsys)

    assert result == 0, payload
    assert payload == {"handler": "run_dry", "status": "FAKE_HANDLER"}
    assert handlers == ["run_dry"]
    assert provider_trap.attempts == []


@pytest.mark.parametrize("entry", ENTRY_012)
def test_012_main_reuses_nested_entry_schema_and_preserves_existing_validators(
    entry: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Only 012 opts into its wider schema; the existing validator still runs before dispatch."""

    from copy import deepcopy

    module, handlers, provider_trap = _load_runner(entry, monkeypatch)
    config_dir = tmp_path / entry

    # evidence_boundary is an allowed optional projection, while the five
    # credential, three policy, and two timeout keys remain accepted.
    for include_boundary in (True, False):
        handlers.clear()
        provider_trap.attempts.clear()
        result, payload, _stdout = _run_main(
            module,
            config_dir,
            _valid_012_config(include_evidence_boundary=include_boundary),
            monkeypatch,
            capsys,
        )
        assert result == 0, payload
        assert payload == {"handler": "run_dry", "status": "FAKE_HANDLER"}
        assert handlers == ["run_dry"]
        assert provider_trap.attempts == []

    invalid_mutations = (
        (
            "unknown_credential",
            lambda item: item["credentials"].update({"unexpected_key": "SYNTHETIC_SECRET"}),
        ),
        ("unknown_policy", lambda item: item["policy"].update({"unexpected_key": 1})),
        ("unknown_timeout", lambda item: item["timeouts"].update({"unexpected_key": 1})),
        ("invalid_venue", lambda item: item.update({"venue": ["okx"]})),
        (
            "invalid_credential_env",
            lambda item: item["credentials"].update({"okx_api_key_env": " "}),
        ),
        ("invalid_policy", lambda item: item["policy"].update({"max_actions": 0})),
        ("invalid_timeout", lambda item: item["timeouts"].update({"run_seconds": 0})),
    )
    for case, mutate_entry in invalid_mutations:
        config = deepcopy(_valid_012_config())
        mutate_entry(config["entry"])
        handlers.clear()
        provider_trap.attempts.clear()
        result, payload, stdout = _run_main(module, config_dir, config, monkeypatch, capsys)

        _assert_config_blocked(result, payload)
        assert handlers == [], (entry, case, handlers)
        assert provider_trap.attempts == [], (entry, case, provider_trap.attempts)
        assert "SYNTHETIC_SECRET" not in stdout, (entry, case, stdout)
