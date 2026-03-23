import pytest
from tests.test_utils.hft_scenarios import compare_scenario, get_hft_scenario_specs


def _scenario_by_name(name):
    return next(spec for spec in get_hft_scenario_specs() if spec.name == name)


@pytest.mark.parametrize(
    ("scenario_name", "expected_cash", "expected_fill_count", "expected_last_fill_price"),
    [
        ("plain_grid", 1001.0, 2, 101.0),
        ("queue_market_making", 1001.0, 2, 101.0),
        ("obi_alpha_market_making", 1002.0, 4, 101.0),
        ("basis_alpha_market_making", 1001.0, 2, 101.0),
        ("apt_alpha_market_making", 1001.0, 2, 101.0),
        ("glft_market_making", 1001.0, 2, 101.0),
    ],
)
def test_adapted_hftbacktest_scenarios_match_backtrader_result(
    scenario_name,
    expected_cash,
    expected_fill_count,
    expected_last_fill_price,
):
    result = compare_scenario(_scenario_by_name(scenario_name))

    assert result["matches"] == {
        "cash": True,
        "position": True,
        "fills": True,
        "trade_count": True,
    }
    assert result["backtrader"]["cash"] == pytest.approx(expected_cash)
    assert result["backtrader"]["position"] == pytest.approx(0.0)
    assert len(result["backtrader"]["fills"]) == expected_fill_count
    assert result["backtrader"]["fills"][-1]["price"] == pytest.approx(expected_last_fill_price)
    assert result["state_values"]["num_trades"] == expected_fill_count
