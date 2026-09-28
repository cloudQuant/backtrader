from __future__ import annotations

from dataclasses import replace

import pytest

from offline_cutover_validator import (
    LEGACY_SOURCE,
    SCHEMA,
    V21_SOURCE,
    ActionRefEvidence,
    CutoverBundle,
    CutoverRejected,
    make_snapshot,
    validate_cutover,
)

ACCOUNT = "account:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def row(
    *,
    account: str = ACCOUNT,
    action: str = "action-1",
    intent: str = "intent-1",
    ref: int = 41,
    state: str = "COMPLETED",
    trading_day: str = "20260927",
    scope: str = "scope:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    runtime_order: str = "bt-managed-v1:" + "c" * 64,
    order_ref: str = "000000000123",
) -> ActionRefEvidence:
    return ActionRefEvidence(
        account_key=account,
        trading_day=trading_day,
        scope_key=scope,
        managed_action_id=action,
        managed_intent_id=intent,
        runtime_order_id=runtime_order,
        order_ref=order_ref,
        native_action_ref=ref,
        state=state,
    )


def bundle(
    legacy_rows: tuple[ActionRefEvidence, ...] | None = None,
    v21_rows: tuple[ActionRefEvidence, ...] | None = None,
    *,
    legacy_high: int = 41,
    v21_high: int = 41,
    legacy_complete: bool = True,
    v21_complete: bool = True,
    legacy_read_error: str | None = None,
    v21_read_error: str | None = None,
    legacy_boundary: str = "synthetic-boundary-1",
    v21_boundary: str = "synthetic-boundary-1",
) -> CutoverBundle:
    legacy_rows = (row(),) if legacy_rows is None else legacy_rows
    v21_rows = legacy_rows if v21_rows is None else v21_rows
    return CutoverBundle(
        schema=SCHEMA,
        account_key=ACCOUNT,
        legacy=make_snapshot(
            source=LEGACY_SOURCE,
            account_key=ACCOUNT,
            rows=legacy_rows,
            high_water_action_ref=legacy_high,
            snapshot_boundary_id=legacy_boundary,
            complete=legacy_complete,
            read_error=legacy_read_error,
        ),
        v21=make_snapshot(
            source=V21_SOURCE,
            account_key=ACCOUNT,
            rows=v21_rows,
            high_water_action_ref=v21_high,
            snapshot_boundary_id=v21_boundary,
            complete=v21_complete,
            read_error=v21_read_error,
        ),
    )


def rejects(code: str, candidate: CutoverBundle) -> None:
    with pytest.raises(CutoverRejected) as error:
        validate_cutover(candidate)
    assert error.value.code == code


def test_exact_mapping_is_consistent_but_report_has_no_authority() -> None:
    result = validate_cutover(bundle())
    assert result.consistent is True
    assert result.matched_action_count == 1
    assert result.authority is False
    assert result.write_enabled is False


def test_row_order_does_not_change_snapshot_digest_or_mapping_result() -> None:
    first = row(action="action-a", intent="intent-a", ref=41)
    second = row(action="action-b", intent="intent-b", ref=42, order_ref="000000000124")
    candidate = bundle((first, second), (second, first), legacy_high=42, v21_high=42)
    assert validate_cutover(candidate).matched_action_count == 2


def test_missing_mapping_on_either_side_fails_closed() -> None:
    first = row()
    second = row(action="action-2", intent="intent-2", ref=42, order_ref="000000000124")
    rejects(
        "mapping_missing_from_one_source",
        bundle((first, second), (first,), legacy_high=42, v21_high=42),
    )
    rejects(
        "mapping_missing_from_one_source",
        bundle((first,), (first, second), legacy_high=41, v21_high=42),
    )


def test_same_reference_different_action_or_identity_fields_fails() -> None:
    rejects(
        "mapping_field_conflict",
        bundle((row(),), (row(action="different-action"),)),
    )
    rejects(
        "mapping_field_conflict",
        bundle((row(),), (row(order_ref="000000000999"),)),
    )
    rejects(
        "mapping_field_conflict",
        bundle((row(),), (row(runtime_order="bt-managed-v1:" + "d" * 64),)),
    )


@pytest.mark.parametrize(
    ("field", "changed", "expected"),
    [
        ("trading_day", "20260928", "mapping_field_conflict"),
        ("scope_key", "scope:" + "d" * 64, "mapping_field_conflict"),
        ("managed_action_id", "different-action", "mapping_field_conflict"),
        ("managed_intent_id", "different-intent", "mapping_field_conflict"),
        ("runtime_order_id", "bt-managed-v1:" + "d" * 64, "mapping_field_conflict"),
        ("order_ref", "000000000999", "mapping_field_conflict"),
        ("native_action_ref", 42, "mapping_missing_from_one_source"),
    ],
)
def test_every_shared_identity_field_must_match(
    field: str, changed: object, expected: str
) -> None:
    original = row()
    altered = replace(original, **{field: changed})
    rejects(expected, bundle((original,), (altered,), legacy_high=41, v21_high=42))


def test_action_id_cannot_move_to_another_reference() -> None:
    left = row(action="same-action", intent="same-intent", ref=41)
    right = row(
        action="same-action", intent="same-intent", ref=42, order_ref="000000000124"
    )
    rejects(
        "mapping_missing_from_one_source",
        bundle((left,), (right,), legacy_high=41, v21_high=42),
    )


def test_duplicate_identity_or_reference_is_not_coalesced() -> None:
    first = row()
    duplicate = row()
    rejects(
        "duplicate_or_conflicting_source_identity",
        bundle((first, duplicate), (first, duplicate)),
    )


def test_unknown_or_missing_state_fails_on_either_source() -> None:
    rejects(
        "unknown_action_present",
        bundle((row(state="UNKNOWN"),), (row(state="COMPLETED"),)),
    )
    rejects(
        "row_state_missing_or_unrecognized",
        bundle((row(state=""),), (row(state="COMPLETED"),)),
    )


def test_unreadable_or_incomplete_history_fails_closed() -> None:
    rejects("snapshot_unreadable", bundle(legacy_read_error="sqlite read failed"))
    rejects("snapshot_incomplete", bundle(v21_complete=False))


def test_v21_high_water_below_legacy_source_fails_closed() -> None:
    rejects("v21_high_water_below_legacy_source", bundle(legacy_high=50, v21_high=49))


def test_nonzero_high_water_without_mapping_rows_fails_closed() -> None:
    rejects(
        "snapshot_high_water_without_rows", bundle((), (), legacy_high=1, v21_high=1)
    )


def test_snapshot_high_water_below_observed_row_fails_closed() -> None:
    rejects("snapshot_high_water_below_rows", bundle(legacy_high=40, v21_high=41))


def test_declared_row_count_or_digest_tampering_is_rejected() -> None:
    candidate = bundle()
    rejects(
        "snapshot_digest_mismatch",
        replace(
            candidate,
            legacy=replace(candidate.legacy, rows=(row(action="changed-action"),)),
        ),
    )
    rejects(
        "snapshot_row_count_mismatch",
        replace(candidate, v21=replace(candidate.v21, row_count=2)),
    )


def test_cross_account_row_is_rejected_even_if_manifest_is_recomputed() -> None:
    wrong = row(account="account:" + "e" * 64)
    candidate = bundle((wrong,), (wrong,))
    rejects("row_account_mismatch", candidate)


def test_invalid_action_ref_and_order_ref_are_rejected() -> None:
    rejects(
        "row_action_ref_invalid",
        bundle((row(ref=0),), (row(ref=0),), legacy_high=0, v21_high=0),
    )
    rejects(
        "row_order_ref_invalid",
        bundle((row(order_ref="123"),), (row(order_ref="123"),)),
    )


def test_source_high_water_must_cover_every_observed_reference() -> None:
    row42 = row(
        ref=42, action="action-42", intent="intent-42", order_ref="000000000124"
    )
    rejects(
        "snapshot_high_water_below_rows",
        bundle((row42,), (row42,), legacy_high=41, v21_high=42),
    )


def test_state_mismatch_at_same_boundary_fails_closed() -> None:
    rejects(
        "mapping_state_conflict",
        bundle((row(state="READY"),), (row(state="COMPLETED"),)),
    )


def test_different_snapshot_boundaries_fail_closed() -> None:
    rejects(
        "snapshot_boundary_mismatch",
        bundle(legacy_boundary="barrier-1", v21_boundary="barrier-2"),
    )


def test_hostile_schema_comparison_is_not_invoked() -> None:
    calls: list[str] = []

    class HostileSchema:
        def __ne__(self, other: object) -> bool:
            calls.append("ne")
            return False

    rejects("bundle_schema_type_invalid", replace(bundle(), schema=HostileSchema()))
    assert calls == []


def test_malformed_row_callback_is_not_invoked_before_rejection() -> None:
    calls: list[str] = []

    class HostileRow:
        def to_payload(self) -> dict[str, object]:
            calls.append("to_payload")
            return {}

    candidate = bundle()
    malformed = replace(candidate.legacy, rows=(HostileRow(),))
    rejects("row_type_invalid", replace(candidate, legacy=malformed))
    assert calls == []


def test_nonprimitive_row_field_is_rejected_without_comparison_callback() -> None:
    calls: list[str] = []

    class HostileText:
        def __eq__(self, other: object) -> bool:
            calls.append("eq")
            return True

    candidate = bundle()
    malformed_row = replace(row(), account_key=HostileText())
    malformed_snapshot = replace(candidate.legacy, rows=(malformed_row,))
    rejects("row_field_type_invalid", replace(candidate, legacy=malformed_snapshot))
    assert calls == []


def test_snapshot_source_identity_cannot_be_relabelled() -> None:
    candidate = bundle()
    wrong = make_snapshot(
        source=V21_SOURCE,
        account_key=ACCOUNT,
        rows=candidate.legacy.rows,
        high_water_action_ref=41,
    )
    rejects("snapshot_source_mismatch", replace(candidate, legacy=wrong))
