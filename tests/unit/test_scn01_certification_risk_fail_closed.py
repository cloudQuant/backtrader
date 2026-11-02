from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO = Path(__file__).resolve().parents[2]
_CERTIFICATION_ROOT = _REPO / "examples/live/000_live_certification"
_VENUES = ("binance", "okx", "simnow")
_MISSING = object()


def _load_runner(venue: str):
    package_name = f"_scn01_{venue}_risk_certlib"
    certlib_path = _CERTIFICATION_ROOT / f"{venue}_penetration/certlib/__init__.py"
    previous_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == package_name or name.startswith(package_name + ".")
    }
    for name in previous_modules:
        sys.modules.pop(name, None)

    spec = importlib.util.spec_from_file_location(
        package_name,
        certlib_path,
        submodule_search_locations=[str(certlib_path.parent)],
    )
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = package
    try:
        spec.loader.exec_module(package)
        runner = importlib.import_module(f"{package_name}.runner")
    except Exception:
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        raise
    return package_name, runner, previous_modules


@pytest.fixture(params=_VENUES)
def runner_module(request):
    package_name, runner, previous_modules = _load_runner(request.param)
    yield runner
    for name in tuple(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name, None)
    sys.modules.update(previous_modules)


def _declaration(value):
    if value is _MISSING:
        return SimpleNamespace()
    return SimpleNamespace(RISK=value)


def _install_in_memory_strategy_loader(
    runner_module, monkeypatch, module_name, strategy_risk, module_risk, run_calls
):
    class T01Strategy:
        def run(self, ctx):
            run_calls.append((self, ctx))

    if strategy_risk is not _MISSING:
        T01Strategy.RISK = strategy_risk

    class InMemoryLoader:
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.T01Strategy = T01Strategy
            if module_risk is not _MISSING:
                module.RISK = module_risk

    def in_memory_spec(_name, path):
        return importlib.machinery.ModuleSpec(
            module_name,
            InMemoryLoader(),
            origin=str(path),
        )

    monkeypatch.setattr(
        runner_module.importlib.util,
        "spec_from_file_location",
        in_memory_spec,
    )


@pytest.mark.parametrize("risk", ["READ", "WRITE", "DANGEROUS"])
def test_resolves_only_exact_unambiguous_risk_declarations(runner_module, risk):
    assert runner_module._resolve_case_risk(_declaration(risk), _declaration(risk)) == risk
    assert runner_module._resolve_case_risk(_declaration(_MISSING), _declaration(risk)) == risk
    assert runner_module._resolve_case_risk(_declaration(risk), _declaration(_MISSING)) == risk


@pytest.mark.parametrize(
    ("strategy_risk", "module_risk", "reason"),
    [
        (_MISSING, _MISSING, "case_risk_missing"),
        (None, _MISSING, "case_risk_invalid"),
        ("", "READ", "case_risk_invalid"),
        (_MISSING, "", "case_risk_invalid"),
        ("TYPO", "READ", "case_risk_invalid"),
        (_MISSING, "write", "case_risk_invalid"),
        (1, _MISSING, "case_risk_invalid"),
        ("READ", "WRITE", "case_risk_conflict"),
    ],
)
def test_rejects_missing_empty_unknown_and_conflicting_risk(
    runner_module, strategy_risk, module_risk, reason
):
    with pytest.raises(runner_module._RiskMetadataError) as caught:
        runner_module._resolve_case_risk(
            _declaration(strategy_risk), _declaration(module_risk)
        )

    assert caught.value.reason == reason


@pytest.mark.parametrize(
    ("strategy_risk", "module_risk", "reason"),
    [
        (_MISSING, _MISSING, "case_risk_missing"),
        (None, "READ", "case_risk_invalid"),
        ("", "READ", "case_risk_invalid"),
        ("TYPO", "READ", "case_risk_invalid"),
        ("READ", "WRITE", "case_risk_conflict"),
    ],
)
def test_main_case_blocks_invalid_risk_before_env_or_client(
    runner_module, monkeypatch, capsys, strategy_risk, module_risk, reason
):
    venue = next(
        name for name in _VENUES
        if f"_scn01_{name}_risk_certlib" in runner_module.__package__
    )
    case_dir = _CERTIFICATION_ROOT / f"{venue}_penetration/cases/T01"
    module_name = f"_scn01_{venue}_synthetic_risk_case"
    previous_module = sys.modules.get(module_name, _MISSING)
    env_calls = []
    client_calls = []
    run_calls = []

    monkeypatch.setattr(
        runner_module,
        "_load_yaml",
        lambda _path: {"case_id": "T01", "topology": {}},
    )
    _install_in_memory_strategy_loader(
        runner_module,
        monkeypatch,
        module_name,
        strategy_risk,
        module_risk,
        run_calls,
    )

    def forbidden_env(*args, **kwargs):
        env_calls.append((args, kwargs))
        raise AssertionError("invalid risk reached environment loading")

    def forbidden_client(*args, **kwargs):
        client_calls.append((args, kwargs))
        raise AssertionError("invalid risk reached client construction")

    monkeypatch.setattr(runner_module.envfile, "load_env", forbidden_env)
    monkeypatch.setattr(runner_module, "make_client", forbidden_client)
    monkeypatch.setattr(sys, "argv", [str(case_dir / "run.py")])

    try:
        exit_code = runner_module.main_case(
            ["--live", "--allow-write", "--allow-dangerous"]
        )
        summary = json.loads(capsys.readouterr().out.strip())
        assert exit_code == 2
        assert summary == {
            "case": "T01",
            "venue": venue,
            "status": "BLOCKED",
            "reason": reason,
        }
        assert env_calls == []
        assert client_calls == []
        assert run_calls == []
    finally:
        if previous_module is _MISSING:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module

    assert sys.modules.get(module_name, _MISSING) is previous_module


@pytest.mark.parametrize(
    ("risk", "allow_write", "allow_dangerous", "reason"),
    [
        ("READ", False, False, None),
        ("WRITE", False, False, "write_grant_required"),
        ("WRITE", True, False, None),
        ("DANGEROUS", False, False, "write_grant_required"),
        ("DANGEROUS", True, False, "dangerous_grant_required"),
        ("DANGEROUS", False, True, "write_grant_required"),
        ("DANGEROUS", True, True, None),
    ],
)
def test_preserves_valid_risk_grant_requirements(
    runner_module, risk, allow_write, allow_dangerous, reason
):
    assert (
        runner_module._risk_grant_block(risk, allow_write, allow_dangerous) == reason
    )
