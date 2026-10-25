"""Focused offline contracts for 028's official SimNow profile validator."""

from __future__ import annotations

import pytest

from test_alpha003_simnow_runner import RUNNER

SDK_SELECTOR = pytest.importorskip("bt_api_ctp.ctp_env_selector")


def _official(profile="set1_group1"):
    td_front, md_front = SDK_SELECTOR.official_simnow_fronts(profile)
    return profile, td_front, md_front


def _validate(config, api_kwargs=None):
    return RUNNER.validate_official_simnow_store_profile(config, api_kwargs or {})


def test_official_simnow_pair_returns_only_sanitized_profile_evidence():
    profile, td_front, md_front = _official()

    result = _validate(
        {
            "td_address": td_front,
            "md_address": md_front,
            "ctp_env_profile": profile,
            "password": "fixture-secret",
            "auth_code": "fixture-auth-code",
        }
    )

    assert result == {"verified": True, "environment": "simnow", "profile": profile}
    assert "fixture-secret" not in repr(result)
    assert "fixture-auth-code" not in repr(result)
    assert td_front not in repr(result)
    assert md_front not in repr(result)


def test_official_pair_without_profile_claim_uses_sdk_lookup_or_fails_closed():
    profile, td_front, md_front = _official("set1_group2")

    if not callable(getattr(SDK_SELECTOR, "official_simnow_profile_for_td_front", None)):
        with pytest.raises(RUNNER.SimNowProfileValidationError) as error:
            _validate({"td_front": td_front, "md_front": md_front})
        assert error.value.reason == "CTP_PROFILE_LOOKUP_UNAVAILABLE"
        return

    result = _validate({"td_front": td_front, "md_front": md_front})
    assert result == {"verified": True, "environment": "simnow", "profile": profile}


def test_missing_fronts_fail_closed_without_values_in_error():
    with pytest.raises(RUNNER.SimNowProfileValidationError) as error:
        _validate({})

    assert error.value.reason == "CTP_FRONT_MISSING"
    assert "tcp://" not in str(error.value)


def test_non_simnow_registered_broker_pair_is_rejected():
    from bt_api_ctp.ctp_env_selector import registered_broker_sim_fronts

    td_front, md_front = registered_broker_sim_fronts("hongyuan_sim_telecom")

    with pytest.raises(RUNNER.SimNowProfileValidationError) as error:
        _validate(
            {
                "td_front": td_front,
                "md_front": md_front,
                "ctp_env_profile": "hongyuan_sim_telecom",
            }
        )

    assert error.value.reason == "CTP_PROFILE_NOT_OFFICIAL_SIMNOW"
    assert td_front not in str(error.value)


def test_official_but_mismatched_pair_is_rejected():
    first_profile, td_front, _md_front = _official("set1_group1")
    _other_profile, _other_td_front, md_front = _official("set1_group2")

    with pytest.raises(RUNNER.SimNowProfileValidationError) as error:
        _validate(
            {
                "td_front": td_front,
                "md_front": md_front,
                "ctp_env_profile": first_profile,
            }
        )

    assert error.value.reason == "CTP_PROFILE_FRONT_MISMATCH"


def test_api_kwargs_overrides_same_name_config_values_like_the_store():
    profile, td_front, md_front = _official("set2_7x24")
    other_profile, other_td_front, other_md_front = _official("set1_group1")

    result = _validate(
        {
            "td_address": other_td_front,
            "md_address": other_md_front,
            "ctp_env_profile": other_profile,
        },
        {
            "td_address": td_front,
            "md_address": md_front,
            "ctp_env_profile": profile,
        },
    )

    assert result == {"verified": True, "environment": "simnow", "profile": profile}


def test_address_alias_wins_over_conflicting_front_after_store_merge():
    profile, td_front, md_front = _official()
    _other_profile, other_td_front, _other_md_front = _official("set1_group2")

    result = _validate(
        {
            "td_address": td_front,
            "td_front": other_td_front,
            "md_address": md_front,
            "ctp_env_profile": profile,
        }
    )

    assert result == {"verified": True, "environment": "simnow", "profile": profile}


def test_api_kwargs_front_alias_does_not_override_config_address():
    profile, td_front, md_front = _official()
    _other_profile, other_td_front, _other_md_front = _official("set1_group2")

    result = _validate(
        {
            "td_address": td_front,
            "md_address": md_front,
            "ctp_env_profile": profile,
        },
        {"td_front": other_td_front},
    )

    assert result == {"verified": True, "environment": "simnow", "profile": profile}


def test_inconsistent_environment_claim_is_rejected():
    profile, td_front, md_front = _official()

    with pytest.raises(RUNNER.SimNowProfileValidationError) as error:
        _validate(
            {
                "td_front": td_front,
                "md_front": md_front,
                "ctp_env_profile": profile,
                "environment": "production",
            }
        )

    assert error.value.reason == "CTP_ENVIRONMENT_NOT_SIMNOW"
