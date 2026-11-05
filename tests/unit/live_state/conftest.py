import pytest

from backtrader.live_state import StrategyStateDir


@pytest.fixture
def strategy_dir(tmp_path):
    path = tmp_path / "strategy"
    path.mkdir()
    return path


@pytest.fixture
def state(strategy_dir):
    return StrategyStateDir.initialize(strategy_dir)
