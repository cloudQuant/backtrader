"""Tests for fail-closed CTP example support helpers."""

import importlib.util
import sys
from pathlib import Path

import pytest

from backtrader_runtime.errors import RuntimeConfigError


_SUPPORT_PATH = (
    Path(__file__).resolve().parents[2] / "examples" / "007_ctp" / "ctp_example_support.py"
)
_SPEC = importlib.util.spec_from_file_location("ctp_example_support", _SUPPORT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
support = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = support
_SPEC.loader.exec_module(support)


def test_create_live_store_rejects_before_store_or_account_helpers(monkeypatch):
    """Legacy direct Store construction cannot bypass the registered runtime."""
    calls = []
    monkeypatch.setattr(
        support,
        "BtApiStore",
        lambda **kwargs: calls.append(kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        support,
        "create_simnow_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("account helper reached")),
    )

    with pytest.raises(RuntimeConfigError) as failure:
        support.create_live_store({"simnow_env": "auto"})

    assert failure.value.reason == "legacy_direct_execution_not_supported"
    assert calls == []


def test_legacy_simnow_credential_helpers_reject_before_environment_lookup(monkeypatch):
    """Retired helper calls do not read credential values from process state."""

    def reject_environment_lookup(*args, **kwargs):
        raise AssertionError("legacy helper read process environment")

    monkeypatch.setattr(support.os, "getenv", reject_environment_lookup)

    for helper, args in (
        (support.get_simnow_credentials, ()),
        (support.create_simnow_connection, ("new_7x24",)),
    ):
        with pytest.raises(RuntimeConfigError) as failure:
            helper(*args)

        assert failure.value.reason == "legacy_direct_execution_not_supported"
