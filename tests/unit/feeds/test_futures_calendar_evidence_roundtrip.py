"""Calendar snapshot loading preserves both public evidence variants."""

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")  # SDK-free envs skip

from backtrader.futures import (
    ExpectedRuleEvidence,
    PublicSourceEvidence,
    load_exchange_session_calendar,
)


_AVAILABLE_AT = "2026-10-20T00:00:00+00:00"
_RETRIEVED_AT = "2026-10-20T01:00:00+00:00"
_SOURCE_ID = "fixture.calendar"


def _calendar_document(evidence_kind):
    source = {
        "evidence_kind": evidence_kind,
        "source_id": _SOURCE_ID,
        "version": "fixture-v1",
        "available_at": _AVAILABLE_AT,
        "retrieved_at": _RETRIEVED_AT,
    }
    if evidence_kind == "public_source_bytes":
        source.update(
            {
                "source_url": "https://fixture.invalid/calendar",
                "sha256": "a" * 64,
            }
        )
        evidence_mode = "source_backed"
    else:
        source.update(
            {
                "source_urls": ["https://fixture.invalid/calendar"],
                "rules_manifest_sha256": "b" * 64,
                "limitations": ["fixture expected schedule"],
            }
        )
        evidence_mode = "expected_rule_derived"
    return {
        "schema": "backtrader.exchange_session_calendar.v1",
        "exchange_id": "SHFE",
        "calendar_source_id": _SOURCE_ID,
        "coverage_start": "2026-10-22",
        "coverage_through": "2026-10-22",
        "complete": True,
        "evidence_mode": evidence_mode,
        "trading_days": ["2026-10-22"],
        "product_universe": [{"exchange_id": "SHFE", "product_id": "CU"}],
        "sources": [source],
        "product_days": [
            {
                "product": {"exchange_id": "SHFE", "product_id": "CU"},
                "trading_day": "2026-10-22",
                "source_id": _SOURCE_ID,
                "closed_reason": "fixture closed day",
                "windows": [],
            }
        ],
    }


@pytest.mark.parametrize(
    ("evidence_kind", "expected_type"),
    (
        ("public_source_bytes", PublicSourceEvidence),
        ("expected_rule_derived", ExpectedRuleEvidence),
    ),
)
def test_calendar_snapshot_roundtrip_preserves_evidence_discriminator(
    evidence_kind, expected_type
):
    restored = load_exchange_session_calendar(_calendar_document(evidence_kind))

    assert type(restored.sources[0]) is expected_type

    serialized = restored.to_dict()
    reloaded = load_exchange_session_calendar(serialized)

    assert reloaded == restored
    assert type(reloaded.sources[0]) is expected_type
    assert reloaded.to_dict() == serialized
