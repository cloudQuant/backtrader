"""Iteration-42 component interaction boundaries for the standard entries.

The four optional SDK components (``bt_api_gateway``, ``bt_api_risk``,
``bt_api_monitor``, ``bt_api_execution``) are opt-in mounts for the sanctioned
``000`` optional16 acceptance path; the iteration-42 example entries keep
their reviewable routes closed (SimNow uses the direct registered-sim chain;
disabled components must never be imported accidentally).  These tests pin
that boundary in the repository test net:

* importing any standard entry never imports a component package;
* the entries reject component-mount-shaped flags instead of silently
  routing through a component;
* the optional16 topology matrix (the component-positive path) stays a valid
  2x2x2x2 grid whose combo ids/flag mapping do not drift.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COMPONENT_PACKAGES = (
    "bt_api_py",
    "bt_api_risk",
    "bt_api_monitor",
    "bt_api_execution",
    "bt_api_gateway",
)
ENTRIES = {
    "012_1": REPO / "examples" / "unified" / "012_1_midfreq_cross_exchange" / "run.py",
    "012_2": REPO / "examples" / "unified" / "012_2_event_driven_cross_exchange" / "run.py",
    "013_1": REPO / "examples" / "unified" / "013_1_midfreq_cross_arbitrage" / "run.py",
    "013_2": REPO / "examples" / "unified" / "013_2_highfreq_calendar_arbitrage" / "run.py",
    "013_3": REPO / "examples" / "unified" / "013_3_sa_midfreq_simnow" / "run.py",
    "014_1": REPO / "examples" / "unified" / "014_1_ctp_options_lowfreq" / "run.py",
    "014_2": REPO / "examples" / "unified" / "014_2_ctp_options_midfreq" / "run.py",
    "015": REPO / "examples" / "unified" / "015_ctp_options_highfreq" / "run.py",
}
OPTIONAL16 = REPO / "examples" / "live" / "000_live_certification" / "optional16"


def _load_entry(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(f"iter42_entry_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", sorted(ENTRIES), ids=sorted(ENTRIES))
def test_standard_entry_import_never_pulls_a_component_package(name: str) -> None:
    before = set(sys.modules)
    _load_entry(name, ENTRIES[name])
    newly_loaded = set(sys.modules) - before
    leaked = sorted(
        module
        for module in newly_loaded
        if any(module == pkg or module.startswith(pkg + ".") for pkg in COMPONENT_PACKAGES)
    )
    assert leaked == [], f"{name} entry imported component packages: {leaked}"


@pytest.mark.parametrize("name", sorted(ENTRIES), ids=sorted(ENTRIES))
@pytest.mark.parametrize("flag", ("--execution", "--risk", "--monitor", "--gateway"))
def test_standard_entry_rejects_component_mount_flags(name: str, flag: str) -> None:
    module = _load_entry(f"{name}_{flag.strip('-')}", ENTRIES[name])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = module.main([flag])
    output = buffer.getvalue()
    assert code == 2, f"{name} accepted {flag}: {output[-200:]}"
    assert "unknown_arguments_rejected" in output


@pytest.fixture(scope="module")
def optional16_spec():
    spec = importlib.util.spec_from_file_location("iter42_optional16_spec", OPTIONAL16 / "spec.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_optional16_matrix_remains_a_full_2x2x2x2_grid(optional16_spec) -> None:
    specs = optional16_spec.matrix_specs()
    ids = [optional16_spec.combo_id(item) for item in specs]
    assert len(specs) == 16
    assert len(set(ids)) == 16
    # Transport x execution x risk x monitor is fully covered.
    transports = {optional16_spec.combo_id(item).split("-", 1)[0] for item in specs}
    assert transports == {"direct", "gateway_zmq"}
    for suffix in ("-e0-r0-m0", "-e1-r1-m1"):
        assert any(combo.endswith(suffix) for combo in ids)


def test_optional16_component_flags_stay_named_and_off_by_default(optional16_spec) -> None:
    config = {}
    spec = optional16_spec.from_config(config)
    assert optional16_spec.combo_id(spec) == "direct-e0-r0-m0"
    assert tuple(optional16_spec.COMPONENT_FLAGS) == ("execution", "risk", "monitor")
    assert tuple(optional16_spec.TRANSPORTS) == ("direct", "gateway_zmq")
