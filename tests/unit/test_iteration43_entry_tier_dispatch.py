"""Iteration 43: unified main dispatch is checked with synthetic tier decisions.

Each ``examples/unified/<entry>/run.py`` must

* accept ``--dry`` as an explicit offline self-check,
* resolve ``entry.tier`` through its folder-local ``entry_tier`` copy,
* let a mode flag keep or **lower** the declared tier but never raise it, and
* block a malformed declaration before any handler runs.

Every entry's actual ``main`` is exercised against synthetic configuration and
fake handlers across config-tier, CLI-tier, write-grant, and supported auxiliary
flag combinations. The separate subprocess checks use staged public runner
sources and synthetic configuration; they never copy checkout ``config.yaml``.

Two evidence keys must not be confused: ``entry_tier`` is this channel decision,
while ``tier`` in a live summary is the pre-existing *outcome* label (for example
``fill_round_trip`` or ``observation_only_tick_arrival``) that iteration-42
evidence already records.  Overwriting the outcome label with the decision would
change the meaning of a historical field, so the split is guarded below.
"""

from __future__ import annotations

import ast
import argparse
import copy
import importlib.util
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
UNIFIED = ROOT / "examples" / "unified"
CANONICAL_HELPER = ROOT / "examples" / "_support" / "entry_tier.py"

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
LIVE_REFUSAL_ENTRIES = ("014_2_ctp_options_midfreq", "015_ctp_options_highfreq")
ENTRY_012 = ("012_1_midfreq_cross_exchange", "012_2_event_driven_cross_exchange")
ENTRY_013_3 = "013_3_sa_midfreq_simnow"
AUXILIARY_FLAGS = {
    "012_1_midfreq_cross_exchange": ("--mechanical-smoke", "mechanical_smoke"),
    "012_2_event_driven_cross_exchange": ("--mechanical-smoke", "mechanical_smoke"),
    "013_1_midfreq_cross_arbitrage": ("--drill", "drill"),
    "013_2_highfreq_calendar_arbitrage": ("--drill", "drill"),
    "013_3_sa_midfreq_simnow": ("--drill", "drill"),
    "014_1_ctp_options_lowfreq": ("--drill", "drill"),
}

_SCHEMA_HELPERS_NAME = "_iteration43_entry_schema_dispatch_helpers"
_SCHEMA_HELPERS_SPEC = importlib.util.spec_from_file_location(
    _SCHEMA_HELPERS_NAME, Path(__file__).with_name("test_iteration43_entry_schema.py")
)
assert _SCHEMA_HELPERS_SPEC is not None and _SCHEMA_HELPERS_SPEC.loader is not None
_SCHEMA_HELPERS = importlib.util.module_from_spec(_SCHEMA_HELPERS_SPEC)
sys.modules[_SCHEMA_HELPERS_NAME] = _SCHEMA_HELPERS
_SCHEMA_HELPERS_SPEC.loader.exec_module(_SCHEMA_HELPERS)


def _run(entry: str, argv: list[str], cwd: Path, *, evidence: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "run.py", *argv]
    if evidence is not None:
        command += ["--evidence-dir", str(evidence)]
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )


def _payload(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    lines = [line for line in completed.stdout.strip().splitlines() if line.strip()]
    assert lines, f"no JSON on stdout (exit {completed.returncode}): {completed.stderr[-400:]}"
    payload = json.loads(lines[-1])
    assert isinstance(payload, Mapping), payload
    return dict(payload)


def _tier(payload: Mapping[str, Any]) -> dict[str, Any]:
    tier = payload.get("entry_tier")
    assert isinstance(tier, Mapping), f"report carries no entry_tier evidence: {payload}"
    return dict(tier)


def _stage(tmp_path: Path, entry: str, *, declaration: str | None = None) -> Path:
    """Copy public runner sources and write only a synthetic config into *tmp_path*."""

    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard", f"examples/unified/{entry}"],
        capture_output=True,
        text=True,
    )
    if listing.returncode != 0:
        pytest.skip("git is unavailable in this environment")
    target = tmp_path / entry
    prefix = f"examples/unified/{entry}/"
    for relative in (line for line in listing.stdout.splitlines() if line.startswith(prefix)):
        # A tracked config may also be ignored locally. Never read its checkout
        # bytes; the test config below is assembled from public templates or
        # A04's synthetic fixtures only.
        if Path(relative).name in {"config.yaml", ".env"}:
            continue
        destination = target / Path(relative[len(prefix) :])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    # Subprocess checks retain the complete public legacy/replay schema so the
    # real dry/replay handlers and validators still run against faithful inputs.
    # The bytes come from Git HEAD (or A04's equivalent sanitized public 013_3
    # fixture), never from a checkout config.
    config = _stage_config(entry)
    base_entry = copy.deepcopy(config.get("entry"))
    config.pop("entry", None)
    if declaration is not None:
        overlay = yaml.safe_load(declaration)
        if isinstance(overlay, dict):
            nested = overlay.get("entry")
            if entry in ENTRY_012 and isinstance(nested, dict):
                entry_config = base_entry
                if not isinstance(entry_config, dict):
                    entry_config = copy.deepcopy(_SCHEMA_HELPERS._valid_012_config()["entry"])
                else:
                    entry_config = copy.deepcopy(entry_config)
                entry_config.update(nested)
                overlay["entry"] = entry_config
            config.update(overlay)
    (target / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return target


def _synthetic_config(entry: str) -> dict[str, Any]:
    if entry in ENTRY_012:
        public = copy.deepcopy(_public_config(entry))
        public["entry"] = copy.deepcopy(_SCHEMA_HELPERS._valid_012_config()["entry"])
        return public
    if entry == ENTRY_013_3:
        return copy.deepcopy(_SCHEMA_HELPERS._valid_013_3_config())
    public = copy.deepcopy(_public_config(entry))
    public["entry"] = {"tier": "dry"}
    return public


def _stage_config(entry: str) -> dict[str, Any]:
    if entry == ENTRY_013_3:
        return copy.deepcopy(_SCHEMA_HELPERS._valid_013_3_config())
    return copy.deepcopy(_public_config(entry))


@lru_cache(maxsize=None)
def _public_config(entry: str) -> dict[str, Any]:
    """Read a committed public template through Git, never a checkout config."""

    path = f"examples/unified/{entry}/config.yaml"
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    parsed = yaml.safe_load(completed.stdout)
    assert isinstance(parsed, dict), f"committed public config template for {entry} is not a mapping"

    def sanitize(value: Any, key: str = "", in_credentials: bool = False) -> Any:
        if isinstance(value, dict):
            return {
                child_key: sanitize(
                    child,
                    str(child_key),
                    in_credentials or "credential" in str(child_key).lower(),
                )
                for child_key, child in value.items()
            }
        if isinstance(value, list):
            return [sanitize(child, key, in_credentials) for child in value]
        lowered = key.lower()
        if isinstance(value, str) and (
            in_credentials
            or lowered.endswith("_env")
            or any(token in lowered for token in ("api_key", "secret", "password", "passphrase", "auth_code"))
        ):
            return f"SYNTHETIC_{''.join(ch if ch.isalnum() else '_' for ch in key).upper()}"
        return value

    return sanitize(parsed)


def _matrix_config(entry: str, declared_tier: str | None) -> dict[str, Any]:
    config = _synthetic_config(entry)
    if declared_tier is None:
        config.pop("entry", None)
    else:
        entry_config = copy.deepcopy(config.get("entry", {}))
        entry_config["tier"] = declared_tier
        config["entry"] = entry_config
    return config


def _expected_decision(config_tier: str | None, cli_tier: str | None) -> dict[str, Any]:
    if config_tier is None:
        effective = cli_tier or "dry"
        reason = "cli_requested" if cli_tier is not None else "default_dry"
    else:
        configured_effective = "replay" if config_tier == "backtest" else config_tier
        rank = {"dry": 0, "replay": 1, "live": 2}
        if cli_tier is None or cli_tier == configured_effective:
            effective, reason = configured_effective, "config_default"
        elif rank[cli_tier] > rank[configured_effective]:
            effective, reason = configured_effective, "config_tier_conflict"
        else:
            effective, reason = cli_tier, "cli_override"
    return {
        "config_tier": config_tier,
        "cli_tier": cli_tier,
        "effective_tier": effective,
        "tier_selection_reason": reason,
    }


def _cli_args(cli_tier: str | None, allow_write: bool, aux_flag: str | None) -> list[str]:
    args = {"dry": ["--dry"], "replay": ["--replay"], "live": ["--live"]}.get(cli_tier, [])
    args = list(args)
    if allow_write:
        args.append("--allow-write")
    if aux_flag is not None:
        args.append(aux_flag)
    return args


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_main_fake_dispatch_matrix_uses_only_synthetic_configs(
    entry: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Exercise every tier/CLI/grant/auxiliary combination through the real main."""

    module, _initial_calls, provider_trap = _SCHEMA_HELPERS._load_runner(entry, monkeypatch)
    calls: list[dict[str, Any]] = []
    parsed_args: list[argparse.Namespace] = []
    aux_pair = AUXILIARY_FLAGS.get(entry)
    aux_flag, aux_attr = aux_pair if aux_pair is not None else (None, None)

    original_parser = argparse.ArgumentParser

    class _TrackingParser(original_parser):
        def parse_known_args(self, args=None, namespace=None):
            parsed, unknown = super().parse_known_args(args, namespace)
            parsed_args.append(parsed)
            return parsed, unknown

    # Capture the actual parsed consent/auxiliary flags even on dry/replay, whose
    # handler signatures intentionally do not accept those live-only options.
    # argparse's constructor refers to its own global ArgumentParser. Replacing
    # that global with a subclass makes super() recurse on Python 3.11.
    monkeypatch.setattr(module, "argparse", SimpleNamespace(ArgumentParser=_TrackingParser))

    def _install_fake(name: str) -> None:
        def _fake(*args, **kwargs):
            decision = None
            live_namespace = args[0] if name in {"run_live", "run_live_observe"} else None
            if name == "run_dry":
                decision = args[0]
            elif name == "run_replay":
                decision = args[2]
            elif live_namespace is not None:
                decision = live_namespace.tier_decision.as_evidence()
            record = {
                "handler": name,
                "args": args,
                "kwargs": kwargs,
                "decision": dict(decision) if isinstance(decision, Mapping) else decision,
                "allow_write": getattr(live_namespace, "allow_write", None),
                "auxiliary": getattr(live_namespace, aux_attr, None) if aux_attr else None,
            }
            calls.append(record)
            print(
                json.dumps(
                    {
                        "status": "FAKE_HANDLER",
                        "handler": name,
                        "entry_tier": record["decision"],
                        "allow_write": record["allow_write"],
                        "auxiliary": record["auxiliary"],
                    },
                    sort_keys=True,
                )
            )
            return 0

        monkeypatch.setattr(module, name, _fake)

    for handler_name in _SCHEMA_HELPERS.HANDLER_NAMES:
        if callable(getattr(module, handler_name, None)):
            _install_fake(handler_name)

    config_dir = tmp_path / entry
    config_dir.mkdir(parents=True, exist_ok=True)
    config_tiers: tuple[str | None, ...] = (None, "dry", "replay", "backtest", "live")
    cli_tiers: tuple[str | None, ...] = (None, "dry", "replay", "live")
    aux_values = (False, True) if aux_flag is not None else (False,)

    for config_tier in config_tiers:
        for cli_tier in cli_tiers:
            for allow_write in (False, True):
                for use_aux in aux_values:
                    calls.clear()
                    provider_trap.attempts.clear()
                    before_parses = len(parsed_args)
                    config = _matrix_config(entry, config_tier)
                    _SCHEMA_HELPERS._write_document(module, config_dir, config, monkeypatch)
                    argv = _cli_args(cli_tier, allow_write, aux_flag if use_aux else None)
                    result = module.main(argv)
                    parsed = parsed_args[before_parses]
                    captured = capsys.readouterr()
                    payload = _payload(
                        subprocess.CompletedProcess(args=[], returncode=result, stdout=captured.out, stderr=captured.err)
                    )
                    expected = _expected_decision(config_tier, cli_tier)
                    label = (entry, config_tier, cli_tier, allow_write, use_aux)

                    assert parsed.allow_write is allow_write, (label, vars(parsed))
                    if aux_attr is not None:
                        assert getattr(parsed, aux_attr) is use_aux, (label, vars(parsed))
                    assert bool(getattr(parsed, "dry", False)) == (cli_tier == "dry"), label
                    assert bool(getattr(parsed, "replay", False)) == (cli_tier == "replay"), label
                    assert bool(getattr(parsed, "live", False)) == (cli_tier == "live"), label
                    assert provider_trap.attempts == [], (label, provider_trap.attempts)

                    if expected["tier_selection_reason"] == "config_tier_conflict":
                        assert result == 2, (label, payload)
                        assert payload.get("status") == "BLOCKED", (label, payload)
                        assert payload.get("reason") == "config_tier_conflict", (label, payload)
                        assert payload.get("entry_tier") == expected, (label, payload)
                        assert payload.get("write_grant_result") == "not_evaluated_tier_unresolved", (label, payload)
                        assert calls == [], (label, calls)
                        continue

                    effective = expected["effective_tier"]
                    if effective == "dry":
                        expected_handler = "run_dry"
                    elif effective == "replay":
                        expected_handler = "run_replay"
                    elif entry in LIVE_REFUSAL_ENTRIES or allow_write:
                        expected_handler = "run_live"
                    else:
                        expected_handler = "run_live_observe"
                    assert result == 0, (label, payload)
                    assert payload.get("status") == "FAKE_HANDLER", (label, payload)
                    assert payload.get("handler") == expected_handler, (label, payload)
                    assert payload.get("entry_tier") == expected, (label, payload)
                    assert len(calls) == 1 and calls[0]["handler"] == expected_handler, (label, calls)
                    call = calls[0]
                    assert call["decision"] == expected, (label, call)
                    if expected_handler in {"run_live", "run_live_observe"}:
                        assert call["allow_write"] is allow_write, (label, call)
                        if aux_attr is not None:
                            assert call["auxiliary"] is use_aux, (label, call)
                        assert payload.get("allow_write") is allow_write, (label, payload)
                        if aux_attr is not None:
                            assert payload.get("auxiliary") is use_aux, (label, payload)


@pytest.mark.parametrize("entry", LIVE_REFUSAL_ENTRIES)
@pytest.mark.parametrize("flag", ("--drill", "--mechanical-smoke"))
def test_unsupported_auxiliary_flag_is_rejected_before_dispatch(
    entry: str, flag: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    module, calls, provider_trap = _SCHEMA_HELPERS._load_runner(entry, monkeypatch)
    _SCHEMA_HELPERS._write_document(module, tmp_path / entry, {"entry": {"tier": "dry"}}, monkeypatch)
    result = module.main([flag])
    payload = _payload(
        subprocess.CompletedProcess(args=[], returncode=result, stdout=capsys.readouterr().out, stderr="")
    )
    assert result == 2, payload
    assert payload.get("status") == "REJECTED", payload
    assert payload.get("error") == "unknown_arguments_rejected", payload
    assert calls == [], calls
    assert provider_trap.attempts == [], provider_trap.attempts


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_missing_config_with_live_grant_never_dispatches(
    entry: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The loader's missing-file path fails closed without reaching a handler."""

    module, calls, provider_trap = _SCHEMA_HELPERS._load_runner(entry, monkeypatch)
    config_dir = tmp_path / entry
    monkeypatch.setattr(module, "HERE", config_dir)
    legacy_runner = getattr(module, "_iteration43_legacy_runner", None)
    if legacy_runner is not None:
        monkeypatch.setattr(legacy_runner, "DEFAULT_CONFIG", config_dir / "config.yaml")
    result = module.main(["--live", "--allow-write"])
    captured = capsys.readouterr()
    payload = _payload(
        subprocess.CompletedProcess(args=[], returncode=result, stdout=captured.out, stderr=captured.err)
    )
    assert result == 2, payload
    assert payload.get("status") == "BLOCKED", payload
    assert payload.get("entry_tier") == {}, payload
    assert payload.get("write_grant_result") == "not_evaluated", payload
    assert calls == [], calls
    assert provider_trap.attempts == [], provider_trap.attempts


# The fake-main matrix above covers backtest -> replay and CLI lowering for
# every entry. Running a staged legacy engine here would test package provenance
# rather than dispatch; that independent contract belongs to copy-out QA.
@pytest.mark.parametrize("entry", ALL_ENTRIES)
@pytest.mark.parametrize(
    ("declaration", "argv", "reason"),
    (
        ("\nentry:\n  tier: dry\n", ["--live"], "config_tier_conflict"),
        ("\nentry:\n  tier: replay\n", ["--live"], "config_tier_conflict"),
        ("\nentry:\n  tier: nonsense\n", [], "config_tier_invalid"),
        ("\nentry:\n", [], "config_tier_invalid"),
        ("\nentry: not-a-mapping\n", [], "config_tier_invalid"),
    ),
)
def test_gate_blocks_before_any_handler(entry: str, tmp_path: Path, declaration: str, argv: list[str], reason: str) -> None:
    """Escalation and malformed declarations stop before a handler, and never fall back to live."""

    staged = _stage(tmp_path, entry, declaration=declaration)
    completed = _run(entry, argv, staged, evidence=tmp_path / "evidence")
    payload = _payload(completed)
    assert completed.returncode == 2, payload
    assert payload["status"] == "BLOCKED", payload
    assert payload["reason"] == reason, payload
    assert payload["entry_tier"]["tier_selection_reason"] == reason, payload
    assert payload.get("write_grant_result") == "not_evaluated_tier_unresolved", payload
    # An unresolved tier must not have reached the live channel: every entry names
    # its own live-tier precondition, and none of those may appear here.
    for live_marker in ("live_tier_requires_python_3_11", "front_selection", "provider_preflight_started"):
        assert live_marker not in json.dumps(payload), payload


@pytest.mark.parametrize("entry", LIVE_REFUSAL_ENTRIES)
def test_declared_live_tier_reaches_the_live_channel(entry: str, tmp_path: Path) -> None:
    """A declared ``live`` tier really dispatches ``run_live``.

    ``--allow-write`` is used only as the probe: both entries refuse it as their
    very first statement, so reaching that refusal proves the live handler ran
    without any provider side effect.  ``mode`` is emitted only by ``run_live``,
    so it identifies the handler without depending on the tier wiring that R5b
    adds to the live summaries.
    """

    staged = _stage(tmp_path, entry, declaration="\nentry:\n  tier: live\n")
    completed = _run(entry, ["--allow-write"], staged)
    payload = _payload(completed)
    assert completed.returncode == 2, payload
    assert payload["status"] == "BLOCKED", payload
    assert payload["mode"] == "live", payload
    assert payload["reason"] == "write_tier_not_implemented_for_decision_only_strategy", payload
    assert _tier(payload)["effective_tier"] == "live", payload
    assert payload["write_grant_result"] == "refused_no_order_path_by_contract", payload


@pytest.mark.parametrize("entry", ("012_1_midfreq_cross_exchange", "012_2_event_driven_cross_exchange"))
def test_crypto_live_without_grant_states_the_missing_channel(entry: str, tmp_path: Path) -> None:
    """The crypto entries report the absent observation path, not a consent error.

    Their live tier is the demo write acceptance, so this row is the honest
    capability statement: nothing is connected, nothing is ordered, and the
    reason names the gap rather than implying an observation path was refused.
    """

    staged = _stage(tmp_path, entry, declaration="\nentry:\n  tier: live\n")
    completed = _run(entry, [], staged)
    payload = _payload(completed)
    assert completed.returncode == 2, payload
    assert payload["status"] == "BLOCKED", payload
    assert payload["mode"] == "live" and payload["channel"] == "observe", payload
    assert payload["reason"] == "live_observation_unavailable", payload
    assert payload["write_grant_result"] == "not_requested", payload
    assert _tier(payload)["effective_tier"] == "live", payload


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_folder_local_helper_is_a_byte_copy(entry: str) -> None:
    vendored = UNIFIED / entry / "entry_tier.py"
    assert vendored.is_file(), f"{entry} has no folder-local tier helper"
    assert vendored.read_bytes() == CANONICAL_HELPER.read_bytes(), f"{entry}'s tier helper drifted"


@pytest.mark.parametrize("entry", ("014_1_ctp_options_lowfreq", "014_2_ctp_options_midfreq", "015_ctp_options_highfreq"))
def test_entry_projection_keeps_the_frozen_replay_contract_strict(entry: str, tmp_path: Path) -> None:
    """Admitting ``entry`` must not loosen the strict replay key set.

    The three entries that project the section away before validating still have
    to reject any *other* unknown top-level key.
    """

    declaration = "\nentry:\n  tier: replay\nbogus_iteration43_key: 1\n"
    staged = _stage(tmp_path, entry, declaration=declaration)
    completed = _run(entry, ["--replay"], staged, evidence=tmp_path / "evidence")
    payload = _payload(completed)
    assert completed.returncode != 0, payload
    assert payload["status"] in {"REJECTED", "BLOCKED"}, payload
    assert "bogus_iteration43_key" in json.dumps(payload) or "schema" in json.dumps(payload).lower(), payload


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_decision_evidence_never_overwrites_the_outcome_label(entry: str) -> None:
    """``summary["tier"]`` stays the iteration-42 outcome label.

    Iteration-42 evidence records a live ``tier`` such as ``fill_round_trip``; the
    channel decision belongs in ``entry_tier`` and must not be written over it.
    """

    source = (UNIFIED / entry / "run.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "tier"
            ):
                written = ast.dump(node.value)
                assert "decision" not in written and "tier_evidence" not in written, (
                    f"{entry}:{node.lineno} writes the channel decision into the outcome label"
                )


@pytest.mark.parametrize(
    "entry",
    (
        "012_1_midfreq_cross_exchange",
        "012_2_event_driven_cross_exchange",
        "013_1_midfreq_cross_arbitrage",
        "013_2_highfreq_calendar_arbitrage",
        "013_3_sa_midfreq_simnow",
        "014_1_ctp_options_lowfreq",
    ),
)
def test_live_summary_carries_channel_evidence_separately(entry: str) -> None:
    source = (UNIFIED / entry / "run.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    run_live = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_live"
    )
    summaries = []
    for node in run_live.body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if any(isinstance(target, ast.Name) and target.id == "summary" for target in targets):
            assert isinstance(node.value, ast.Dict), entry
            summaries.append(node.value)
    assert len(summaries) == 1, f"{entry}: expected one live summary initializer"
    keys = {key.value for key in summaries[0].keys if isinstance(key, ast.Constant)}
    assert {"entry_tier", "write_grant_result"} <= keys, (
        f"{entry}: live summary omitted channel or write-grant evidence"
    )
