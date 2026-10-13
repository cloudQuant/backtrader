"""Component boundaries for the standard entries and retired Optional16 CLIs.

The Optional16 matrix and live gateway-capability acceptance commands are
retired; their source remains for historical context. The iteration-42
example entries keep their reviewable routes closed (SimNow uses the direct
registered-sim chain; disabled components must never be imported accidentally).
These tests pin that boundary in the repository test net:

* importing any standard entry never imports a component package;
* the entries reject component-mount-shaped flags instead of silently
  routing through a component;
* the retired Optional16 command names stop before configuration, credential,
  subprocess, or output-file operations; the lightweight spec remains usable
  to interpret historical matrix records.
"""

from __future__ import annotations

import importlib
import importlib.util
import io
import json
import os
import subprocess
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


@pytest.mark.parametrize("script", ("run_matrix.py", "gateway_capability_check.py"))
@pytest.mark.parametrize("argv", ((), ("--dry",), ("--live",)))
def test_optional16_acceptance_clis_are_retired_without_side_effects(
    script, argv, tmp_path, monkeypatch
) -> None:
    path = OPTIONAL16 / script
    module_name = "iter42_retired_" + script[:-3]
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: pytest.fail("config read"))
    monkeypatch.setattr(Path, "write_text", lambda *_args, **_kwargs: pytest.fail("artifact write"))
    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: pytest.fail("journal creation"))
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: pytest.fail("case process"))
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("child process"))

    output = io.StringIO()
    with redirect_stdout(output):
        assert module.main(list(argv)) == 2

    assert json.loads(output.getvalue()) == {
        "status": "BLOCKED",
        "reason": "optional16_acceptance_retired",
    }
    assert list(tmp_path.iterdir()) == []


def _load_entry(path: Path):
    module_name = f"examples.unified.{path.parent.name}.run"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


_PACKAGE_IMPORT_PROBE = r"""
import importlib
import json
import sys

module_name = sys.argv[1]
components = tuple(json.loads(sys.argv[2]))
module = importlib.import_module(module_name)
loaded = set(sys.modules)
leaked = sorted(
    name
    for name in loaded
    if any(name == package or name.startswith(package + ".") for package in components)
)
print(json.dumps({
    "module_name": module.__name__,
    "module_path": module.__file__,
    "helper_path": module.entry_tier.__file__,
    "component_modules": leaked,
}))
"""


@pytest.mark.parametrize("name", sorted(ENTRIES), ids=sorted(ENTRIES))
def test_standard_entry_import_never_pulls_a_component_package(name: str) -> None:
    module_name = f"examples.unified.{ENTRIES[name].parent.name}.run"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _PACKAGE_IMPORT_PROBE,
            module_name,
            json.dumps(COMPONENT_PACKAGES),
        ],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, (
        f"{name} package import failed without PYTHONPATH: {completed.stderr[-1000:]}"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["module_name"] == module_name
    assert Path(payload["module_path"]).resolve() == ENTRIES[name].resolve()
    expected_helper = (ENTRIES[name].parent / "entry_tier.py").resolve()
    assert Path(payload["helper_path"]).resolve() == expected_helper
    assert payload["component_modules"] == [], (
        f"{name} entry imported component packages: {payload['component_modules']}"
    )


@pytest.mark.parametrize("name", sorted(ENTRIES), ids=sorted(ENTRIES))
@pytest.mark.parametrize("flag", ("--execution", "--risk", "--monitor", "--gateway"))
def test_standard_entry_rejects_component_mount_flags(name: str, flag: str) -> None:
    module = _load_entry(ENTRIES[name])
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
