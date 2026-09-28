from __future__ import annotations

import importlib
import socket
import subprocess
from dataclasses import FrozenInstanceError, replace

import pytest

from backtrader_runtime.ctp_simnow_managed_operator import (
    ctp_simnow_front_pair_set_sha256,
)
from backtrader_runtime.inventory import ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
from tests.unit.live_certification.test_managed_case_invocation import (
    _issued_case_scope,
    _synthetic_runtime,
)

receipt_module = importlib.import_module(
    "examples.007_ctp.live_certification.simnow_penetration.managed_case_front_selection"
)


def _install_fake_sockets(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    calls: list[tuple[str, int]] = []

    class FakeSocket:
        def settimeout(self, _timeout: float) -> None:
            return None

        def connect(self, address: tuple[str, int]) -> None:
            calls.append((address[0], address[1]))

        def close(self) -> None:
            return None

    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: FakeSocket())

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline receipt test attempted a real network route")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    return calls


def _scope_and_runtime(tmp_path, monkeypatch, *, second_pair=None):
    effective, registry = _synthetic_runtime(
        tmp_path, monkeypatch, second_pair=second_pair
    )
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    identities = set(
        receipt_module.ctp_configured_front_check._SUPPORTED_PRIVATE_RUNTIME_IDENTITIES
    )
    identities.add(
        (effective.registration.runtime_id, effective.registration.runtime_dir)
    )
    monkeypatch.setattr(
        receipt_module.ctp_configured_front_check,
        "_SUPPORTED_PRIVATE_RUNTIME_IDENTITIES",
        frozenset(identities),
    )
    return scope, effective, registry


def test_receipt_binds_selected_probe_to_sealed_ordered_pair_set_and_redacts(
    tmp_path, monkeypatch
):
    scope, effective, registry = _scope_and_runtime(
        tmp_path,
        monkeypatch,
        second_pair=("tcp://127.0.0.1:21002", "tcp://127.0.0.1:22002"),
    )
    calls = _install_fake_sockets(monkeypatch)

    receipt = receipt_module.check_case_front_selection(scope, effective, registry)
    receipt_module.validate_case_front_selection_receipt(
        receipt, scope, effective, registry
    )

    assert receipt.runtime_id == ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
    assert receipt.config_digest == effective.config_digest
    assert receipt.effective_digest == effective.effective_digest
    assert receipt.ordered_front_pair_set_sha256 == ctp_simnow_front_pair_set_sha256(
        effective.config.ctp.front_pairs
    )
    assert receipt.configured_pair_count == 2
    assert receipt.selected_config_index in (0, 1)
    assert len(receipt.probe_result_sha256) == 64
    assert receipt.probe_origin == "local_007_configured_tcp_front_check"
    assert receipt.clock_origin == "local_system_utc_clock"
    with pytest.raises(FrozenInstanceError):
        receipt.selected_config_index = receipt.selected_config_index
    assert receipt.as_redacted_dict()["provider_authenticated"] is False
    assert receipt.as_redacted_dict()["authorization_granted"] is False
    assert len(calls) == 2 * 2 * 3

    rendered = repr(receipt) + repr(receipt.as_redacted_dict())
    assert "offline-case-test-password" not in rendered
    assert "offline-case-account" not in rendered
    assert "tcp://127.0.0.1" not in rendered


def test_receipt_rejects_changed_config_after_probe(tmp_path, monkeypatch):
    scope, effective, registry = _scope_and_runtime(tmp_path, monkeypatch)
    _install_fake_sockets(monkeypatch)
    receipt = receipt_module.check_case_front_selection(scope, effective, registry)

    config_path = effective.registration.runtime_dir / "config.yaml"
    changed = config_path.read_text(encoding="utf-8").replace("21001", "21999", 1)
    config_path.write_text(changed, encoding="utf-8")

    with pytest.raises(receipt_module.ManagedCaseFrontSelectionError) as error:
        receipt_module.validate_case_front_selection_receipt(
            receipt, scope, effective, registry
        )
    assert error.value.reason in {
        "front_selection_sealed_runtime_invalid",
        "front_selection_runtime_config_changed",
    }


def test_receipt_is_bound_to_the_exact_issued_case_scope(tmp_path, monkeypatch):
    scope, effective, registry = _scope_and_runtime(tmp_path, monkeypatch)
    _install_fake_sockets(monkeypatch)
    receipt = receipt_module.check_case_front_selection(scope, effective, registry)
    altered_scope = replace(scope, case_id="T02")

    with pytest.raises(receipt_module.ManagedCaseFrontSelectionError) as error:
        receipt_module.validate_case_front_selection_receipt(
            receipt, altered_scope, effective, registry
        )
    assert error.value.reason == "front_selection_receipt_invalid"


def test_receipt_matching_seam_requires_issued_fresh_receipt_and_matches_scope(
    tmp_path, monkeypatch
):
    scope, effective, registry = _scope_and_runtime(tmp_path, monkeypatch)
    _install_fake_sockets(monkeypatch)
    receipt = receipt_module.check_case_front_selection(scope, effective, registry)
    selection = {
        "config_digest": receipt.config_digest,
        "effective_digest": receipt.effective_digest,
        "ordered_front_pair_set_sha256": receipt.ordered_front_pair_set_sha256,
        "selected_config_index": receipt.selected_config_index,
    }

    receipt_module.validate_receipt_matches_selection(
        receipt, scope, effective, registry, **selection
    )

    # dataclasses.replace makes a self-consistent public clone, including the
    # original receipt digest and hidden fields, but does not issue that object.
    manual_clone = replace(receipt)
    with pytest.raises(receipt_module.ManagedCaseFrontSelectionError) as clone_error:
        receipt_module.validate_receipt_matches_selection(
            manual_clone, scope, effective, registry, **selection
        )
    assert clone_error.value.reason == "front_selection_receipt_invalid"

    with pytest.raises(receipt_module.ManagedCaseFrontSelectionError) as mismatch:
        receipt_module.validate_receipt_matches_selection(
            receipt,
            scope,
            effective,
            registry,
            **{**selection, "selected_config_index": receipt.selected_config_index + 1},
        )
    assert mismatch.value.reason == "front_selection_receipt_selection_mismatch"


def test_selection_matching_seam_rechecks_fresh_sealed_config(tmp_path, monkeypatch):
    scope, effective, registry = _scope_and_runtime(tmp_path, monkeypatch)
    _install_fake_sockets(monkeypatch)
    receipt = receipt_module.check_case_front_selection(scope, effective, registry)
    selection = {
        "config_digest": receipt.config_digest,
        "effective_digest": receipt.effective_digest,
        "ordered_front_pair_set_sha256": receipt.ordered_front_pair_set_sha256,
        "selected_config_index": receipt.selected_config_index,
    }
    config_path = effective.registration.runtime_dir / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("21001", "21999", 1),
        encoding="utf-8",
    )

    with pytest.raises(receipt_module.ManagedCaseFrontSelectionError) as error:
        receipt_module.validate_receipt_matches_selection(
            receipt, scope, effective, registry, **selection
        )
    assert error.value.reason in {
        "front_selection_sealed_runtime_invalid",
        "front_selection_runtime_config_changed",
    }


def test_unsuccessful_front_check_does_not_issue_a_selection_receipt(
    tmp_path, monkeypatch
):
    scope, effective, registry = _scope_and_runtime(tmp_path, monkeypatch)
    failed = receipt_module.ctp_configured_front_check.CtpConfiguredFrontCheckResult(
        "no_pair_reachable",
        "no_configured_pair_reachable",
        1,
        None,
        (
            receipt_module.ctp_configured_front_check.CtpConfiguredFrontPairCheck(
                0, 0, 3, 0, 3, "unreachable"
            ),
        ),
    )
    monkeypatch.setattr(
        receipt_module.ctp_configured_front_check,
        "check_configured_ctp_fronts",
        lambda *_args, **_kwargs: failed,
    )

    with pytest.raises(receipt_module.ManagedCaseFrontSelectionError) as error:
        receipt_module.check_case_front_selection(scope, effective, registry)
    assert error.value.reason == "front_selection_probe_not_selected"
