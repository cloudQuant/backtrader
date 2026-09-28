"""Narrow offline checks for the current managed SimNow required scope."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = (
    REPO_ROOT
    / "examples"
    / "007_ctp"
    / "live_certification"
    / "simnow_penetration"
    / "managed_case_entry.py"
)
_ENTRY_SPEC = importlib.util.spec_from_file_location(
    "iteration41_007_managed_case_entry_required_scope", ENTRY_PATH
)
assert _ENTRY_SPEC is not None and _ENTRY_SPEC.loader is not None
managed_case_entry = importlib.util.module_from_spec(_ENTRY_SPEC)
_ENTRY_SPEC.loader.exec_module(managed_case_entry)


_HISTORICAL_OPTIONAL_CASE_IDS = frozenset(("O01", "O02", "O03", "TH05", "TH06"))


def test_registry_requires_all_33_cases_and_preserves_historical_optional_flags():
    scenarios = managed_case_entry._load_code_owned_scenarios()

    assert len(managed_case_entry._CURRENT_REQUIRED_CASE_IDS) == 33
    assert set(scenarios) == managed_case_entry._CURRENT_REQUIRED_CASE_IDS
    assert {
        case_id for case_id, scenario in scenarios.items() if scenario.optional
    } == _HISTORICAL_OPTIONAL_CASE_IDS
    assert _HISTORICAL_OPTIONAL_CASE_IDS <= managed_case_entry._CURRENT_REQUIRED_CASE_IDS


def test_registry_missing_o01_fails_closed():
    incomplete_case_ids = set(managed_case_entry._CURRENT_REQUIRED_CASE_IDS) - {"O01"}

    with pytest.raises(
        managed_case_entry._ScopeRejected,
        match="managed_ctp_certification_registry_invalid",
    ):
        managed_case_entry._validate_current_required_case_ids(incomplete_case_ids)
