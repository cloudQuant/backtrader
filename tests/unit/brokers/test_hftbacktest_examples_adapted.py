import pytest
from tests.test_utils.hft_scenarios import compare_scenario, get_hft_scenario_specs


def _scenario_by_name(name):
    return next(spec for spec in get_hft_scenario_specs() if spec.name == name)


def test_adapted_hftbacktest_plain_grid_trading_matches_backtrader_result():
    result = compare_scenario(_scenario_by_name("plain_grid"))

    assert result["matches"] == {
        "cash": True,
        "position": True,
        "fills": True,
        "trade_count": True,
    }
    assert result["backtrader"]["cash"] == pytest.approx(1001.0)
    assert result["backtrader"]["position"] == pytest.approx(0.0)
    assert len(result["backtrader"]["fills"]) == 2
    assert result["state_values"]["num_trades"] == 2


def test_adapted_hftbacktest_queue_market_making_matches_backtrader_result():
    result = compare_scenario(_scenario_by_name("queue_market_making"))

    assert result["matches"] == {
        "cash": True,
        "position": True,
        "fills": True,
        "trade_count": True,
    }
    assert result["backtrader"]["cash"] == pytest.approx(1001.0)
    assert result["backtrader"]["position"] == pytest.approx(0.0)
    assert result["backtrader"]["fills"][-1]["price"] == pytest.approx(101.0)


def test_adapted_hftbacktest_obi_alpha_market_making_matches_backtrader_result():
    result = compare_scenario(_scenario_by_name("obi_alpha_market_making"))

    assert result["matches"] == {
        "cash": True,
        "position": True,
        "fills": True,
        "trade_count": True,
    }
    assert result["backtrader"]["cash"] == pytest.approx(1002.0)
    assert result["backtrader"]["position"] == pytest.approx(0.0)
    assert len(result["backtrader"]["fills"]) == 4
    assert result["state_values"]["num_trades"] == 4
