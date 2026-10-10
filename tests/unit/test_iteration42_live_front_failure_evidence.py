"""Iteration 42 live entries must persist front-selection failure details.

The 2026-10-10 bounded rehearsal was cleanly BLOCKED with
``no_front_pair_eligible``, but the persisted ``run.json`` kept only the
reason string: ``SimNowDirectError`` fell through to the generic handler and
its value-free ``details`` (per-pair probe samples) were lost, forcing a
manual re-probe to tell a vendor outage apart from a code defect.  Every
SimNow live entry now carries a dedicated branch that persists ``reason`` and
``details`` before the generic blocker.

013_1/013_2 are driven end-to-end through the real ``run_live`` with a fake
``simnow_direct`` module; the remaining entries share the identical handler
shape and are covered by a source-consistency guard (their pre-selector flows
need heavier per-file scaffolding that adds no additional signal here).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"
ENTRIES = {
    "013_1": EXAMPLES / "013_1_midfreq_cross_arbitrage",
    "013_2": EXAMPLES / "013_2_highfreq_calendar_arbitrage",
    "013_3": EXAMPLES / "013_3_sa_midfreq_simnow",
    "014_1": EXAMPLES / "014_1_ctp_options_lowfreq",
    "014_2": EXAMPLES / "014_2_ctp_options_midfreq",
    "015": EXAMPLES / "015_ctp_options_highfreq",
}

DETAILS = {
    "rejected": [
        {
            "index": 4,
            "kind": "7x24",
            "td_success": 0,
            "md_success": 0,
            "reason": "no_whole_pair_connection",
        }
    ],
    "samples": 3,
}


def _load_entry(directory: Path, name: str):
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location(name, directory / "run.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(directory))
    return module


@pytest.mark.parametrize("example_id", ("013_1", "013_2"))
def test_live_entry_persists_front_selection_failure_details(example_id, tmp_path):
    if sys.version_info[:2] != (3, 11):
        pytest.skip("live entries require the reviewed Python 3.11 interpreter")

    directory = ENTRIES[example_id]
    entry = _load_entry(directory, f"entry_{example_id}")

    class SimNowDirectError(RuntimeError):
        def __init__(self, reason, details=None):
            super().__init__(reason)
            self.reason = str(reason)
            self.details = dict(details or {})

    fake = types.ModuleType("simnow_direct")
    fake.SimNowDirectError = SimNowDirectError

    def _reject(*args, **kwargs):
        raise SimNowDirectError("no_front_pair_eligible", DETAILS)

    fake.select_front_pair = _reject

    config, _config_path = entry._load_config()
    credentials = config.get("credentials") or {}
    env = {
        str(credentials[key]): "dummy"
        for key in (
            "broker_id_env",
            "user_id_env",
            "password_env",
            "app_id_env",
            "auth_code_env",
        )
    }

    entry._load_env = lambda: env
    entry._ensure_dev_sdk_path = lambda *, strict=False: None
    entry._resolve_live_contracts = lambda cfg: [("rb2701", "SHFE"), ("rb2705", "SHFE")]

    evidence_dir = tmp_path / "ev"
    args = SimpleNamespace(
        allow_write=True,
        run_seconds=None,
        evidence_dir=str(evidence_dir),
        drill=False,
    )

    saved_modules = {key: sys.modules.get(key) for key in ("simnow_direct", "legacy_runner")}
    sys.modules["simnow_direct"] = fake
    sys.path.insert(0, str(directory))
    try:
        rc = entry.run_live(args)
    finally:
        sys.path.remove(str(directory))
        for key, value in saved_modules.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value

    assert rc == 2  # EXIT_BLOCKED
    payload = json.loads((evidence_dir / "run.json").read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "no_front_pair_eligible"
    assert payload["details"]["samples"] == DETAILS["samples"]
    assert payload["details"]["rejected"][0]["reason"] == "no_whole_pair_connection"


@pytest.mark.parametrize("example_id", sorted(ENTRIES))
def test_every_live_entry_carries_the_dedicated_handler(example_id):
    source = (ENTRIES[example_id] / "run.py").read_text(encoding="utf-8")
    clause = "except simnow_direct.SimNowDirectError as exc:"
    assert source.count(clause) == 1
    generic = (
        "except Exception as exc:\n"
        '        summary.update({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"})'
    )
    assert generic in source
    assert source.index(clause) < source.index(generic)
